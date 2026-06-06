"""Brain-owned canonical knowledge-gap recorder.

Owns the `concierge_knowledge_gaps` table. This module is the source of
truth for gap reads and writes — no other module should touch the table
directly.

Public surface:
  record_gap            — main async write
  list_gaps             — read unresolved/resolved gaps
  resolve_gap           — mark a gap resolved, optionally append FAQ answer
  record_gap_async      — convenience wrapper around record_gap that
                          opens its own DB session (for fire-and-forget
                          paths in the gmail/email pipeline)
  schedule_gap_record   — fire-and-forget scheduler around record_gap_async

This file used to be a re-export shim of
`app/services/concierge/knowledge_gap_recorder.py`, which itself called
`ConciergeKnowledgeService.record_gap` in `knowledge_service.py`. That
chain was created during the brain-only migration to give callers a
stable brain import path while the implementation was still in
`knowledge_service.py`. With the legacy concierge_knowledge table being
dropped, the implementation now lives here and the chain collapses.

The functions below are lifted verbatim from
`ConciergeKnowledgeService.record_gap` / `list_gaps` / `resolve_gap` in
`knowledge_service.py`, with two changes:
  1. Class methods become module-level async functions
  2. The `_append_faq_answer` and `upsert_global_faq` helper calls in
     `resolve_gap` now route through scoped knowledge and the brain's
     global_faq module instead of the legacy concierge_knowledge table.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.concierge_knowledge import ConciergeKnowledgeGapModel

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Question-key normalization
#
# Same canonical hash used everywhere else (scoped knowledge service, the
# retire_concierge_knowledge.py migration script). Inlined here so this
# module has no dependency on knowledge_service.py.
# ---------------------------------------------------------------------------


def _normalize_message_tokens(text: str) -> set[str]:
    stopwords = {
        "the", "and", "for", "with", "that", "this", "from", "your", "you", "are",
        "can", "could", "would", "should", "what", "when", "where", "which", "who",
        "how", "why", "does", "did", "have", "has", "had", "our", "about", "into",
        "them", "they", "will", "just", "need", "any", "all", "get", "let", "know",
    }
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {w for w in words if len(w) > 2 and w not in stopwords}


def _normalize_question_key(text: str) -> str:
    return " ".join(sorted(_normalize_message_tokens(text)))


def normalize_question_key(text: str) -> str:
    """Public wrapper so scoring and cleanup reuse the recorder's dedupe key."""
    return _normalize_question_key(text)


def _property_identifier_candidates(raw_value: str) -> List[str]:
    """
    Generate tenant-scoped property identifier candidates in stable order.

    Handles common Escapia / Vrbo shapes seen in Beach Habitats traffic:
      - `ExternalID:2403-280970`
      - `2403-280970`
      - `2403 280970`
      - bare suffixes such as `280970`
      - canonical property codes such as `100SL2C`
    """
    raw = (raw_value or "").strip()
    if not raw:
        return []

    values: List[str] = []

    def _push(candidate: str) -> None:
        normalized = " ".join((candidate or "").strip().split())
        if normalized and normalized not in values:
            values.append(normalized)

    _push(raw)

    if ":" in raw:
        _, suffix = raw.split(":", 1)
        _push(suffix)

    collapsed = re.sub(r"\s+", "", raw)
    dashed = re.sub(r"[\s_]+", "-", raw)
    _push(collapsed)
    _push(dashed)

    company_prefixed = re.search(r"(?<!\d)(\d{4})[-\s_]+(\d{4,})(?!\d)", raw)
    if company_prefixed:
        company_id, suffix = company_prefixed.groups()
        _push(f"{company_id}-{suffix}")
        _push(suffix)

    ext_marker = re.search(r"externalid[:\s_-]*([0-9]{4})[-\s_]*([0-9]{4,})", raw, flags=re.I)
    if ext_marker:
        company_id, suffix = ext_marker.groups()
        _push(f"{company_id}-{suffix}")
        _push(suffix)

    bare_numeric = re.fullmatch(r"\d{4,}", collapsed)
    if bare_numeric:
        _push(bare_numeric.group(0))

    return values


def _coerce_tenant_id(value: UUID | str | None) -> Optional[UUID]:
    if isinstance(value, UUID):
        return value
    if not value:
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _coerce_property_id(value: UUID | str | None) -> Optional[UUID]:
    if value is None or value == "":
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _to_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Core API
# ---------------------------------------------------------------------------


async def record_gap(
    session: AsyncSession,
    tenant_id: UUID,
    question_text: str,
    property_id: Optional[UUID] = None,
    property_external_id: Optional[str] = None,
    stage: Optional[str] = None,
    channel: str = "text",
    source: str = "concierge",
    detected_intent: Optional[str] = None,
    confidence_score: Optional[float] = None,
    metadata: Optional[Dict[str, Any]] = None,
    dedupe_window_hours: int = 72,
) -> Dict[str, Any]:
    """
    Record a guest question that current knowledge could not answer well.

    Dedupes against gaps recorded in the past `dedupe_window_hours` for
    the same tenant + property + normalized question key. Returns the
    canonical gap record either way; the `deduped` field tells the caller
    whether a new row was inserted or an existing one was returned.
    """
    normalized_key = _normalize_question_key(question_text)
    dedupe_cutoff = datetime.now(timezone.utc) - timedelta(
        hours=max(1, dedupe_window_hours)
    )

    dedupe_stmt = (
        select(ConciergeKnowledgeGapModel)
        .where(
            ConciergeKnowledgeGapModel.tenant_id == tenant_id,
            ConciergeKnowledgeGapModel.created_at >= dedupe_cutoff,
        )
        .order_by(ConciergeKnowledgeGapModel.created_at.desc())
        .limit(150)
    )
    recent = list((await session.execute(dedupe_stmt)).scalars())

    for existing in recent:
        same_property = False
        if property_id and existing.property_id == property_id:
            same_property = True
        elif (
            property_external_id
            and existing.property_external_id == property_external_id
        ):
            same_property = True
        if not same_property:
            continue
        if _normalize_question_key(existing.question_text) == normalized_key:
            return {
                "gap_id": str(existing.gap_id),
                "tenant_id": str(existing.tenant_id),
                "property_id": str(existing.property_id) if existing.property_id else None,
                "property_external_id": existing.property_external_id,
                "question_text": existing.question_text,
                "stage": existing.stage,
                "channel": existing.channel,
                "source": existing.source,
                "detected_intent": existing.detected_intent,
                "confidence_score": existing.confidence_score,
                "resolved": existing.resolved,
                "created_at": existing.created_at.isoformat(),
                "deduped": True,
                "duplicate_of_gap_id": str(existing.gap_id),
            }

    # Resolve property_id from external_id at write time so every new gap row
    # is property-attributed immediately, not only when resolved.  This is the
    # shared fix — all callers (gmail_poll, messaging_brain_orchestrator, …)
    # benefit without any call-site changes.  Fail-soft: if resolution returns
    # nothing we still write the row (with NULL property_id) and log the miss
    # so we can track the unattributable floor going forward.
    if not property_id and property_external_id:
        try:
            property_id_str = await resolve_property_id_from_external(
                session=session,
                tenant_id=tenant_id,
                property_external_id=property_external_id,
            )
            if property_id_str:
                from uuid import UUID as _UUID
                property_id = _UUID(property_id_str)
            else:
                logger.debug(
                    "[gap_recorder] property_external_id=%r could not be resolved "
                    "for tenant=%s; writing gap with NULL property_id",
                    property_external_id,
                    tenant_id,
                )
        except Exception as _exc:  # noqa: BLE001
            logger.debug(
                "[gap_recorder] property resolution failed (non-fatal) for "
                "external_id=%r: %s",
                property_external_id,
                _exc,
            )

    item = ConciergeKnowledgeGapModel(
        tenant_id=tenant_id,
        property_id=property_id,
        property_external_id=property_external_id,
        question_text=question_text.strip(),
        stage=stage,
        channel=channel,
        source=source,
        detected_intent=detected_intent,
        confidence_score=confidence_score,
        metadata_json=metadata or {},
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return {
        "gap_id": str(item.gap_id),
        "tenant_id": str(item.tenant_id),
        "property_id": str(item.property_id) if item.property_id else None,
        "property_external_id": item.property_external_id,
        "question_text": item.question_text,
        "stage": item.stage,
        "channel": item.channel,
        "source": item.source,
        "detected_intent": item.detected_intent,
        "confidence_score": item.confidence_score,
        "resolved": item.resolved,
        "created_at": item.created_at.isoformat(),
        "deduped": False,
        "duplicate_of_gap_id": None,
    }


async def list_gaps(
    session: AsyncSession,
    tenant_id: UUID,
    limit: int = 50,
    unresolved_only: bool = True,
) -> List[Dict[str, Any]]:
    """List knowledge gaps for a tenant, newest first."""
    stmt = select(ConciergeKnowledgeGapModel).where(
        ConciergeKnowledgeGapModel.tenant_id == tenant_id
    )
    if unresolved_only:
        stmt = stmt.where(ConciergeKnowledgeGapModel.resolved.is_(False))
    stmt = stmt.order_by(ConciergeKnowledgeGapModel.created_at.desc()).limit(
        max(1, min(limit, 200))
    )
    rows = list((await session.execute(stmt)).scalars())
    return [
        {
            "gap_id": str(r.gap_id),
            "property_id": str(r.property_id) if r.property_id else None,
            "property_external_id": r.property_external_id,
            "question_text": r.question_text,
            "stage": r.stage,
            "channel": r.channel,
            "source": r.source,
            "detected_intent": r.detected_intent,
            "confidence_score": r.confidence_score,
            "resolved": r.resolved,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


async def resolve_gap(
    session: AsyncSession,
    tenant_id: UUID,
    gap_id: UUID,
    resolution_notes: Optional[str] = None,
    faq_answer: Optional[str] = None,
    apply_to_similar_properties: bool = True,
) -> Optional[Dict[str, Any]]:
    """
    Mark a gap resolved. If `faq_answer` is provided, the answer is also
    written as canonical knowledge:

      * property-scoped (property_id or property_external_id set)
        → written to concierge_scoped_knowledge via the scoped service
      * tenant-scoped (no property)
        → written to concierge_global_faq via brain global_faq module

    `apply_to_similar_properties` is currently accepted for API
    compatibility but is a no-op for scoped writes. The legacy
    "similar property profile" cross-property fan-out depended on
    `ConciergeKnowledgeModel.property_context` / amenity tokens, which
    don't exist in the scoped schema. If we later want cross-property
    FAQ borrowing, build it against canonical scoped data instead of
    porting the legacy heuristic.
    """
    row = (
        await session.execute(
            select(ConciergeKnowledgeGapModel).where(
                ConciergeKnowledgeGapModel.tenant_id == tenant_id,
                ConciergeKnowledgeGapModel.gap_id == gap_id,
            )
        )
    ).scalar_one_or_none()
    if not row:
        return None

    faq_updates = 0
    if faq_answer and row.question_text:
        if row.property_id or row.property_external_id:
            faq_updates = await _write_property_faq_via_scoped(
                session=session,
                tenant_id=tenant_id,
                property_id=row.property_id,
                property_external_id=row.property_external_id,
                question=row.question_text,
                answer=faq_answer,
                source="gap_resolution",
            )
        else:
            # Tenant-scope. Route through brain global_faq.
            # Imported here to avoid a circular import at module load time
            # (global_faq imports nothing from gap_recorder, but downstream
            # callers may compose the two).
            from app.services.messaging_brain.knowledge.global_faq import (
                upsert_global_faq,
            )

            await upsert_global_faq(
                session=session,
                tenant_id=tenant_id,
                question_text=row.question_text,
                answer_text=faq_answer,
                source="gap_resolution",
            )
            faq_updates = 1

    row.resolved = True
    row.resolution_notes = resolution_notes
    await session.commit()

    retry_topic = None
    try:
        metadata = row.metadata_json or {}
        topics = (
            metadata.get("missing_topics")
            if isinstance(metadata, dict)
            else None
        )
        if isinstance(topics, list) and topics:
            retry_topic = str(topics[0] or "").strip().lower() or None
    except Exception:
        retry_topic = None

    return {
        "gap_id": str(row.gap_id),
        "resolved": row.resolved,
        "resolution_notes": row.resolution_notes,
        "faq_updates": faq_updates,
        "retry_topic": retry_topic,
    }


# ---------------------------------------------------------------------------
# Scoped-knowledge FAQ write helper
# ---------------------------------------------------------------------------


async def _write_property_faq_via_scoped(
    *,
    session: AsyncSession,
    tenant_id: UUID,
    property_id: Optional[UUID],
    property_external_id: Optional[str],
    question: str,
    answer: str,
    source: str,
) -> int:
    """
    Persist a property-scoped FAQ answer into concierge_scoped_knowledge.

    Returns 1 if the row was created or updated, 0 otherwise. The scoped
    service handles the create-vs-update branch internally via its
    advisory lock + existing-entry lookup.

    Replaces the legacy `ConciergeKnowledgeService._append_faq_answer`
    which mutated the JSONB `faq` array on `concierge_knowledge` rows.
    The scoped schema represents each Q&A as its own row keyed by
    (tenant, scope_type, scope_target_id, question_key).
    """
    from sqlalchemy import text

    from app.services.messaging_brain.knowledge.scoped_knowledge_service import (
        get_scoped_knowledge_service,
    )

    # Resolve property_id from property_external_id if needed. The scoped
    # service writes against property UUIDs.
    if not property_id and property_external_id:
        property_id_str = await resolve_property_id_from_external(
            session=session,
            tenant_id=tenant_id,
            property_external_id=property_external_id,
        )
        if not property_id_str:
            logger.debug(
                "[gap_recorder] cannot resolve property_external_id=%r for tenant=%s; "
                "skipping FAQ write",
                property_external_id,
                tenant_id,
            )
            return 0
        try:
            property_id = UUID(property_id_str)
        except ValueError:
            return 0

    if not property_id:
        return 0

    service = get_scoped_knowledge_service()
    try:
        await service.write_scoped_knowledge(
            session=session,
            tenant_id=tenant_id,
            user_id=tenant_id,  # gap-resolution writes attribute to the tenant
            scope_type="property",
            scope_target_id=property_id,
            topic_id=None,
            question_text=question,
            answer_text=answer,
            tags=["faq", "gap_resolution"],
            source=source,
            metadata={
                "origin": "gap_recorder.resolve_gap",
                "legacy_property_external_id": property_external_id,
            },
        )
        return 1
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[gap_recorder] scoped FAQ write failed for tenant=%s property=%s: %s",
            tenant_id,
            property_id,
            exc,
            exc_info=True,
        )
        return 0


async def resolve_property_id_from_external(
    *,
    session: AsyncSession,
    tenant_id: UUID,
    property_external_id: str,
) -> Optional[str]:
    """Look up a property UUID by tenant-scoped external/code variants."""
    from sqlalchemy import text

    for candidate in _property_identifier_candidates(property_external_id):
        row = (
            await session.execute(
                text(
                    """
                    SELECT
                        COALESCE(
                            to_jsonb(p)->>'id',
                            to_jsonb(p)->>'property_id'
                        ) AS property_id
                    FROM properties p
                    WHERE (to_jsonb(p)->>'tenant_id') = :tid
                      AND (
                            COALESCE(to_jsonb(p)->>'external_id', '') = :candidate
                         OR COALESCE(to_jsonb(p)->>'property_external_id', '') = :candidate
                         OR COALESCE(to_jsonb(p)->>'property_code', '') = :candidate
                         OR COALESCE(to_jsonb(p)->>'code', '') = :candidate
                         OR COALESCE(to_jsonb(p)->'external_ids'->>'pms', '') = :candidate
                         OR COALESCE(to_jsonb(p)->'external_ids'->>'escapia', '') = :candidate
                         OR COALESCE(to_jsonb(p)->'external_ids'->>'vrbo', '') = :candidate
                         OR COALESCE(to_jsonb(p)->'external_ids'->>'airbnb', '') = :candidate
                      )
                    ORDER BY COALESCE((to_jsonb(p)->>'updated_at')::timestamptz, NOW()) DESC
                    LIMIT 1
                    """
                ),
                {"tid": str(tenant_id), "candidate": candidate},
            )
        ).mappings().first()
        if row and row.get("property_id"):
            return str(row["property_id"])

        # Canonical property refs can hold normalized PMS/property ids even when
        # the raw value is not present on the properties row itself. Recover the
        # canonical property code there, then map code -> UUID in properties.
        canonical_row = (
            await session.execute(
                text(
                    """
                    SELECT canonical_property_code
                    FROM canonical_property_refs
                    WHERE tenant_id = CAST(:tid AS uuid)
                      AND provider = 'pms'
                      AND ref_kind = 'property_id'
                      AND normalized_ref_value = LOWER(:candidate)
                    LIMIT 1
                    """
                ),
                {"tid": str(tenant_id), "candidate": candidate},
            )
        ).mappings().first()
        canonical_code = str(canonical_row.get("canonical_property_code") or "").strip() if canonical_row else ""
        if not canonical_code:
            continue

        property_row = (
            await session.execute(
                text(
                    """
                    SELECT COALESCE(to_jsonb(p)->>'id', to_jsonb(p)->>'property_id') AS property_id
                    FROM properties p
                    WHERE (to_jsonb(p)->>'tenant_id') = :tid
                      AND COALESCE(to_jsonb(p)->>'property_code', '') = :canonical_code
                    ORDER BY COALESCE((to_jsonb(p)->>'updated_at')::timestamptz, NOW()) DESC
                    LIMIT 1
                    """
                ),
                {"tid": str(tenant_id), "canonical_code": canonical_code},
            )
        ).mappings().first()
        if property_row and property_row.get("property_id"):
            return str(property_row["property_id"])
    return None


# ---------------------------------------------------------------------------
# Fire-and-forget convenience wrappers
#
# Used by the gmail-poller and other event-driven paths where the caller
# does not have a DB session in scope.
# ---------------------------------------------------------------------------


async def record_gap_async(
    *,
    tenant_id: UUID | str | None,
    question: str,
    answer_attempt: str,
    confidence_score: Optional[float],
    property_code: Optional[str],
    used_kb_chunks: bool,
    was_deflected: bool,
    detected_intent: Optional[str] = None,
    stage: Optional[str] = None,
    channel: str = "text",
    source: str = "concierge",
    metadata: Optional[Dict[str, Any]] = None,
    dedupe_window_hours: int = 72,
) -> Optional[Dict[str, Any]]:
    """Open a DB session and record a gap. Non-fatal on failure."""
    from app.core.database import get_db_session

    normalized_tenant_id = _coerce_tenant_id(tenant_id)
    question_text = (question or "").strip()
    if not normalized_tenant_id or not question_text:
        logger.debug(
            "[gap_recorder] skipping async gap record tenant=%r question_present=%s",
            tenant_id,
            bool(question_text),
        )
        return None

    payload_metadata = {
        "answer_attempt": (answer_attempt or "")[:4000],
        "used_kb_chunks": bool(used_kb_chunks),
        "was_deflected": bool(was_deflected),
    }
    if metadata:
        payload_metadata.update(metadata)

    try:
        async with get_db_session() as session:
            return await record_gap(
                session=session,
                tenant_id=normalized_tenant_id,
                question_text=question_text[:4000],
                # Pass None (not empty string) so record_gap's resolution guard
                # triggers correctly when no property code was provided.
                property_external_id=property_code or None,
                stage=stage,
                channel=channel,
                source=source,
                detected_intent=detected_intent,
                confidence_score=confidence_score,
                metadata=payload_metadata,
                dedupe_window_hours=dedupe_window_hours,
            )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "[gap_recorder] canonical gap record failed (non-fatal): %s", exc
        )
        return None


def schedule_gap_record(**kwargs: Any) -> None:
    """Fire-and-forget gap recording. Used by callers that don't await."""
    try:
        asyncio.create_task(record_gap_async(**kwargs))
    except Exception as exc:  # noqa: BLE001
        logger.debug("[gap_recorder] schedule failed (non-fatal): %s", exc)


__all__ = [
    "record_gap",
    "list_gaps",
    "resolve_gap",
    "record_gap_async",
    "schedule_gap_record",
    "normalize_question_key",
    "resolve_property_id_from_external",
]
