"""
Knowledge Curator Agent

Closes the loop from unanswered guest questions to knowledge base updates.

The gap-to-KB pipeline:
  1. VoicePod / ConciergeMCP records unanswered questions via
     ConciergeMCP.record_gap(question, session_token)
  2. This agent periodically scans the knowledge_gaps table
  3. Groups similar gaps (deduplication via embedding clustering)
  4. Drafts proposed FAQ entries for operator review
  5. Operator approves via dashboard → KnowledgeMCP.index_document()
  6. Next retrieval attempt for that topic → hits the index

Without this loop:
  - Same question ("do you have beach chairs?") shows up as a gap repeatedly
  - Retrieval hit rate stays low for that property
  - Knowledge MCP degradation SLO fires repeatedly

Design:
  - Gaps are grouped by semantic similarity (simple token overlap if no
    embeddings available, cosine similarity when vectorstore is active)
  - Draft FAQ entries are templated, not LLM-generated, to keep cost zero
  - Operator approval is required before any document is indexed
  - Full audit trail: gap_id → draft_id → doc_id chain is stored

Usage:
    from app.services.agents.knowledge_curator_agent import (
        KnowledgeCuratorAgent, get_knowledge_curator_agent
    )

    curator = get_knowledge_curator_agent()

    # Called by background task (daily)
    report = await curator.curate_gaps(db, property_code="CORAL")

    # Called by operator dashboard to approve a draft
    doc_id = await curator.approve_draft(db, draft_id="draft_abc", operator="jane@beach")
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session_safety import safe_rollback

logger = logging.getLogger(__name__)

# Minimum number of similar gaps before we draft a FAQ entry
MIN_GAP_CLUSTER_SIZE = 2

# How old gaps can be before we include them in curation
GAP_LOOKBACK_DAYS = 7


@dataclass
class KnowledgeGap:
    gap_id: str
    tenant_id: str
    question: str
    session_token: str
    property_code: str
    created_at: datetime
    count: int = 1  # how many times this question appeared


@dataclass
class FAQDraft:
    draft_id: str
    tenant_id: str
    property_code: str
    question: str           # canonical question (most frequent variant)
    answer_hint: str        # operator fills in; agent provides scaffold
    gap_ids: List[str]      # which gaps this covers
    occurrence_count: int   # how many guests hit this gap
    created_at: datetime = field(default_factory=datetime.utcnow)
    status: str = "pending_review"   # pending_review | approved | rejected


@dataclass
class CurationReport:
    tenant_id: str
    property_code: str
    gaps_scanned: int = 0
    clusters_found: int = 0
    drafts_created: int = 0
    drafts_already_pending: int = 0
    errors: int = 0
    top_gaps: List[Dict[str, Any]] = field(default_factory=list)


class KnowledgeCuratorAgent:
    """
    Scans knowledge gaps, clusters similar questions, and drafts FAQ entries
    for operator review.

    Core loop:
      1. Load unresolved gaps for a property (last GAP_LOOKBACK_DAYS days)
      2. Cluster by token overlap (quick, no LLM cost)
      3. For clusters >= MIN_GAP_CLUSTER_SIZE → create FAQDraft in DB
      4. Drafts surface in operator dashboard Knowledge Gaps tab
      5. Operator fills in answer + approves → indexed into vector store
    """

    def __init__(self) -> None:
        self._watch = None

    def _get_watch(self):
        if self._watch is None:
            from app.services.observability.watch_layer import get_watch_layer
            self._watch = get_watch_layer()
        return self._watch

    # ─────────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────────

    async def curate_gaps(
        self,
        db: AsyncSession,
        tenant_id: Optional[str] = None,
        property_code: Optional[str] = None,
    ) -> CurationReport:
        """
        Run curation for one or all properties.

        Scans recent gaps, clusters similar questions, creates FAQ drafts
        for operator review.  Safe to call repeatedly — won't duplicate drafts.
        """
        report = CurationReport(tenant_id=tenant_id or "all", property_code=property_code or "all")

        try:
            gaps = await self._load_gaps(db, tenant_id, property_code)
            report.gaps_scanned = len(gaps)
            logger.info("[Curator] Loaded %d gaps to curate", len(gaps))

            if not gaps:
                return report

            # Group by property_code first, then cluster within each property
            by_property: Dict[tuple[str, str], List[KnowledgeGap]] = {}
            for g in gaps:
                by_property.setdefault((g.tenant_id, g.property_code), []).append(g)

            for (_tid, prop), prop_gaps in by_property.items():
                clusters = self._cluster_gaps(prop_gaps)
                report.clusters_found += len(clusters)

                for cluster in clusters:
                    if len(cluster) < MIN_GAP_CLUSTER_SIZE:
                        continue
                    try:
                        created = await self._maybe_create_draft(db, cluster)
                        if created:
                            report.drafts_created += 1
                        else:
                            report.drafts_already_pending += 1
                    except (ProgrammingError, DBAPIError) as exc:
                        await safe_rollback(db)
                        logger.error("[Curator] Draft creation error: %s", exc)
                        report.errors += 1

            # Top gaps for report summary
            sorted_gaps = sorted(gaps, key=lambda g: g.count, reverse=True)
            report.top_gaps = [
                {"question": g.question, "count": g.count, "property": g.property_code}
                for g in sorted_gaps[:10]
            ]

        except (ProgrammingError, DBAPIError) as exc:
            await safe_rollback(db)
            logger.error("[Curator] curate_gaps error: %s", exc)
            report.errors += 1

        # Watch Layer metric
        import asyncio
        watch = self._get_watch()
        asyncio.ensure_future(
            watch.log_agent_run(
                agent_name="knowledge_curator",
                operator_id=tenant_id or "system",
                success=report.errors == 0,
                latency_ms=0,
                metadata={
                    "gaps_scanned": report.gaps_scanned,
                    "clusters_found": report.clusters_found,
                    "drafts_created": report.drafts_created,
                    "property_code": property_code,
                    "tenant_id": tenant_id,
                },
            )
        )

        return report

    async def approve_draft(
        self,
        db: AsyncSession,
        tenant_id: str,
        draft_id: str,
        operator: str,
        answer: Optional[str] = None,
    ) -> Optional[str]:
        """
        Approve a FAQ draft and index it into the knowledge base.

        If `answer` is provided, it overrides the draft's answer_hint.
        Returns the indexed document ID, or None on failure.
        """
        draft = await self._load_draft(db, tenant_id, draft_id)
        if draft is None:
            logger.warning("[Curator] Draft not found: %s", draft_id)
            return None

        final_answer = answer or draft.answer_hint
        if not final_answer or final_answer.startswith("["):
            logger.warning("[Curator] Draft %s has no answer yet — operator must provide", draft_id)
            return None

        # Index into knowledge MCP
        doc_id = await self._index_faq(
            tenant_id=draft.tenant_id,
            property_code=draft.property_code,
            question=draft.question,
            answer=final_answer,
        )

        if doc_id:
            await self._close_draft(db, tenant_id, draft_id, operator, doc_id)
            await self._mark_gaps_resolved(db, draft.gap_ids)
            logger.info(
                "[Curator] Draft %s approved by %s → doc_id=%s",
                draft_id, operator, doc_id,
            )
        return doc_id

    async def reject_draft(
        self,
        db: AsyncSession,
        tenant_id: str,
        draft_id: str,
        operator: str,
        reason: Optional[str] = None,
    ) -> bool:
        """Reject a draft so it doesn't surface in the dashboard again."""
        try:
            await db.execute(
                text("""
                    UPDATE knowledge_gap_drafts
                    SET status = 'rejected', reviewed_by = :op,
                        reviewed_at = NOW(), rejection_reason = :reason
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                      AND draft_id = :did
                """),
                {"tenant_id": tenant_id, "did": draft_id, "op": operator, "reason": reason or ""},
            )
            await db.commit()
            return True
        except Exception as exc:
            await safe_rollback(db)
            logger.error("[Curator] reject_draft error: %s", exc)
            return False

    async def get_pending_drafts(
        self,
        db: AsyncSession,
        tenant_id: str,
        property_code: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        List drafts awaiting operator review.
        Used by operator dashboard Knowledge Gaps tab.
        """
        try:
            params: Dict[str, Any] = {}
            where = "WHERE tenant_id = CAST(:tenant_id AS uuid) AND status = 'pending_review'"
            params["tenant_id"] = tenant_id
            if property_code:
                where += " AND property_code = :prop"
                params["prop"] = property_code

            result = await db.execute(
                text(f"""
                    SELECT draft_id, property_code, question, answer_hint,
                           occurrence_count, created_at, gap_ids
                    FROM knowledge_gap_drafts
                    {where}
                    ORDER BY occurrence_count DESC, created_at DESC
                    LIMIT 50
                """),
                params,
            )
            rows = result.fetchall()
            return [
                {
                    "draft_id": r.draft_id,
                    "property_code": r.property_code,
                    "question": r.question,
                    "answer_hint": r.answer_hint,
                    "occurrence_count": r.occurrence_count,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ]
        except Exception as exc:
            await safe_rollback(db)
            logger.error("[Curator] get_pending_drafts error: %s", exc)
            return []

    # ─────────────────────────────────────────────────────────────────────────
    # Gap clustering (token-overlap, no LLM cost)
    # ─────────────────────────────────────────────────────────────────────────

    def _cluster_gaps(self, gaps: List[KnowledgeGap]) -> List[List[KnowledgeGap]]:
        """
        Group gaps by semantic similarity using token-overlap Jaccard index.

        Two questions are in the same cluster if their token-set Jaccard
        similarity >= 0.4.  This is intentionally simple and cheap — no
        embeddings, no LLM calls.  For large deployments with embeddings
        active, swap this for cosine similarity on stored vectors.
        """
        THRESHOLD = 0.4
        clustered: List[bool] = [False] * len(gaps)
        clusters: List[List[KnowledgeGap]] = []

        def tokenize(text: str) -> Set[str]:
            # Lowercase, strip punctuation, split on whitespace
            import re
            return set(re.sub(r"[^\w\s]", "", text.lower()).split())

        tokens = [tokenize(g.question) for g in gaps]

        for i in range(len(gaps)):
            if clustered[i]:
                continue
            cluster = [gaps[i]]
            clustered[i] = True
            for j in range(i + 1, len(gaps)):
                if clustered[j]:
                    continue
                # Jaccard similarity
                union = tokens[i] | tokens[j]
                if not union:
                    continue
                similarity = len(tokens[i] & tokens[j]) / len(union)
                if similarity >= THRESHOLD:
                    cluster.append(gaps[j])
                    clustered[j] = True
            clusters.append(cluster)

        return clusters

    # ─────────────────────────────────────────────────────────────────────────
    # FAQ draft creation
    # ─────────────────────────────────────────────────────────────────────────

    def _build_answer_hint(self, canonical_question: str) -> str:
        """
        Generate a scaffold answer for the operator to fill in.

        This is intentionally a stub prompt, not LLM-generated.
        The operator knows their property; we just save them the blank-page problem.
        """
        q = canonical_question.lower()

        if any(kw in q for kw in ("beach chair", "chairs", "umbrella")):
            return "[Yes/No — describe what's provided and where it's stored, e.g. 'Yes, 4 beach chairs and 2 umbrellas are in the garage.']"
        if any(kw in q for kw in ("kayak", "paddleboard", "paddle board")):
            return "[Yes/No — describe available watercraft, launch location, and any rules, e.g. 'Two kayaks are available under the deck. Life vests in the storage bin.']"
        if any(kw in q for kw in ("pet", "dog", "cat", "animal")):
            return "[Pet policy — e.g. 'One dog up to 30lbs is welcome with the $75 pet fee. No cats. Please keep pets off furniture.']"
        if any(kw in q for kw in ("park", "parking", "car")):
            return "[Parking instructions — e.g. 'Up to 2 vehicles in the driveway. No street parking on Gulf Drive. Additional parking at the public lot on Beach St.']"
        if any(kw in q for kw in ("pool", "heat", "hot tub")):
            return "[Pool/hot tub info — e.g. 'Heated pool (78°F year-round). Hot tub seats 6. Pool hours 8am–10pm.']"
        if any(kw in q for kw in ("wifi", "wi-fi", "internet", "password")):
            return "[WiFi credentials — Note: these should already be in the Quick Facts. Add here only if there's secondary or guest network info.]"
        if any(kw in q for kw in ("grill", "bbq", "barbecue")):
            return "[Grill instructions — e.g. 'Gas grill on back deck. Propane tank in outdoor cabinet. Please clean after use.']"
        if any(kw in q for kw in ("trash", "garbage", "recycling")):
            return "[Trash instructions — e.g. 'Trash pickup Tuesdays. Bins on left side of house. Blue bin is recycling.']"

        # Generic scaffold
        return f"[Answer the guest's question: '{canonical_question}'. Be specific about your property.]"

    async def _maybe_create_draft(
        self,
        db: AsyncSession,
        cluster: List[KnowledgeGap],
    ) -> bool:
        """
        Create a FAQDraft for this cluster if one doesn't already exist.
        Returns True if a new draft was created, False if already pending.
        """
        # Use the most-asked variant as the canonical question
        canonical = max(cluster, key=lambda g: g.count).question
        tenant_id = cluster[0].tenant_id
        property_code = cluster[0].property_code
        total_count = sum(g.count for g in cluster)
        gap_ids = [g.gap_id for g in cluster]

        # Check for existing pending draft covering these gaps
        existing = await self._find_existing_draft(db, tenant_id, property_code, canonical)
        if existing:
            return False

        draft_id = f"draft_{uuid.uuid4().hex[:12]}"
        answer_hint = self._build_answer_hint(canonical)

        await self._persist_draft(
            db=db,
            draft_id=draft_id,
            tenant_id=tenant_id,
            property_code=property_code,
            question=canonical,
            answer_hint=answer_hint,
            gap_ids=gap_ids,
            occurrence_count=total_count,
        )

        logger.info(
            "[Curator] Draft created: %s q='%s...' count=%d property=%s",
            draft_id, canonical[:50], total_count, property_code,
        )
        return True

    # ─────────────────────────────────────────────────────────────────────────
    # Knowledge MCP indexing
    # ─────────────────────────────────────────────────────────────────────────

    async def _index_faq(
        self,
        tenant_id: str,
        property_code: str,
        question: str,
        answer: str,
    ) -> Optional[str]:
        """Index an approved FAQ entry into the knowledge vector store."""
        try:
            from app.mcp.registry import get_mcp_registry
            registry = get_mcp_registry()
            content = f"Q: {question}\nA: {answer}"
            result = await registry.call(
                server_name="knowledge",
                tool_name="index_document",
                operator_id=tenant_id,
                params={
                    "content": content,
                    "doc_type": "faq",
                    "property_code": property_code,
                    "source": "curator_approved",
                },
            )
            if result.success and result.data:
                return result.data.get("doc_id", f"faq_{uuid.uuid4().hex[:8]}")
        except Exception as exc:
            logger.error("[Curator] _index_faq error: %s", exc)
        return None

    # ─────────────────────────────────────────────────────────────────────────
    # DB helpers
    # ─────────────────────────────────────────────────────────────────────────

    async def _load_gaps(
        self,
        db: AsyncSession,
        tenant_id: Optional[str],
        property_code: Optional[str],
    ) -> List[KnowledgeGap]:
        try:
            cutoff = datetime.utcnow() - timedelta(days=GAP_LOOKBACK_DAYS)
            params: Dict[str, Any] = {"cutoff": cutoff}
            where = "WHERE created_at >= :cutoff AND resolved = FALSE"
            if tenant_id:
                where += " AND tenant_id = CAST(:tenant_id AS uuid)"
                params["tenant_id"] = tenant_id
            if property_code:
                where += " AND property_external_id = :prop"
                params["prop"] = property_code

            result = await db.execute(
                text(f"""
                    SELECT gap_id, question_text, property_external_id,
                           tenant_id, created_at,
                           COUNT(*) OVER (
                               PARTITION BY LOWER(question_text), COALESCE(property_external_id, '')
                           ) AS question_count
                    FROM concierge_knowledge_gaps
                    {where}
                    ORDER BY question_count DESC, created_at DESC
                    LIMIT 500
                """),
                params,
            )
            rows = result.fetchall()
            return [
                KnowledgeGap(
                    gap_id=str(r.gap_id),
                    tenant_id=str(r.tenant_id or ""),
                    question=r.question_text,
                    session_token="",
                    property_code=r.property_external_id or "",
                    created_at=r.created_at,
                    count=int(r.question_count or 1),
                )
                for r in rows
            ]
        except (ProgrammingError, DBAPIError) as exc:
            await safe_rollback(db)
            logger.error("[Curator] _load_gaps error: %s", exc)
            return []

    async def _find_existing_draft(
        self,
        db: AsyncSession,
        tenant_id: str,
        property_code: str,
        question: str,
    ) -> bool:
        try:
            result = await db.execute(
                text("""
                    SELECT 1 FROM knowledge_gap_drafts
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                      AND property_code = :prop
                      AND LOWER(question) = LOWER(:q)
                      AND status = 'pending_review'
                    LIMIT 1
                """),
                {"tenant_id": tenant_id, "prop": property_code, "q": question},
            )
            return result.fetchone() is not None
        except (ProgrammingError, DBAPIError) as exc:
            await safe_rollback(db)
            logger.debug("[Curator] _find_existing_draft error: %s", exc)
            return False

    async def _persist_draft(
        self,
        db: AsyncSession,
        draft_id: str,
        tenant_id: str,
        property_code: str,
        question: str,
        answer_hint: str,
        gap_ids: List[str],
        occurrence_count: int,
    ) -> None:
        import json
        from sqlalchemy import text
        await db.execute(
            text("""
                INSERT INTO knowledge_gap_drafts
                    (draft_id, tenant_id, property_code, operator_id, question, answer_hint,
                     gap_ids, occurrence_count, status, created_at)
                VALUES
                    (:did, CAST(:tenant_id AS uuid), :prop, :op, :q, :hint, :gids, :cnt, 'pending_review', NOW())
                ON CONFLICT (draft_id) DO NOTHING
            """),
            {
                "did": draft_id,
                "tenant_id": tenant_id,
                "prop": property_code,
                "op": tenant_id,
                "q": question,
                "hint": answer_hint,
                "gids": json.dumps(gap_ids),
                "cnt": occurrence_count,
            },
        )
        await db.commit()

    async def _load_draft(self, db: AsyncSession, tenant_id: str, draft_id: str) -> Optional[FAQDraft]:
        try:
            import json
            result = await db.execute(
                text("""
                    SELECT draft_id, tenant_id, property_code, operator_id, question,
                           answer_hint, gap_ids, occurrence_count, status
                    FROM knowledge_gap_drafts
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                      AND draft_id = :did
                    LIMIT 1
                """),
                {"tenant_id": tenant_id, "did": draft_id},
            )
            row = result.fetchone()
            if not row:
                return None
            return FAQDraft(
                draft_id=row.draft_id,
                tenant_id=str(row.tenant_id),
                property_code=row.property_code,
                question=row.question,
                answer_hint=row.answer_hint,
                gap_ids=json.loads(row.gap_ids) if row.gap_ids else [],
                occurrence_count=row.occurrence_count or 0,
                status=row.status,
            )
        except (ProgrammingError, DBAPIError) as exc:
            await safe_rollback(db)
            logger.error("[Curator] _load_draft error: %s", exc)
            return None

    async def _close_draft(
        self,
        db: AsyncSession,
        tenant_id: str,
        draft_id: str,
        operator: str,
        doc_id: str,
    ) -> None:
        from sqlalchemy import text
        await db.execute(
            text("""
                UPDATE knowledge_gap_drafts
                SET status = 'approved', reviewed_by = :op,
                    reviewed_at = NOW(), indexed_doc_id = :doc
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND draft_id = :did
            """),
            {"tenant_id": tenant_id, "did": draft_id, "op": operator, "doc": doc_id},
        )
        await db.commit()

    async def _mark_gaps_resolved(
        self,
        db: AsyncSession,
        gap_ids: List[str],
    ) -> None:
        if not gap_ids:
            return
        try:
            placeholders = ", ".join(f":id{i}" for i in range(len(gap_ids)))
            params = {f"id{i}": gid for i, gid in enumerate(gap_ids)}
            await db.execute(
                text(f"""
                    UPDATE concierge_knowledge_gaps
                    SET resolved = TRUE
                    WHERE gap_id IN ({placeholders})
                """),
                params,
            )
            await db.commit()
        except Exception as exc:
            await safe_rollback(db)
            logger.debug("[Curator] _mark_gaps_resolved error (non-fatal): %s", exc)


# =============================================================================
# Singleton
# =============================================================================

_curator: Optional[KnowledgeCuratorAgent] = None


def get_knowledge_curator_agent() -> KnowledgeCuratorAgent:
    global _curator
    if _curator is None:
        _curator = KnowledgeCuratorAgent()
    return _curator
