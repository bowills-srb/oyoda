from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session_safety import safe_rollback
from app.services.integrations.non_guest_patterns import NON_GUEST_REGISTRY
from app.services.property_canonical_write_service import get_canonical_property_write_service
from app.services.agents.agent_framework import (
    AgentCapability,
    AgentResponse,
    AgentTask,
    AgentType,
    BaseAgent,
)


logger = logging.getLogger(__name__)

MIN_HEALER_CLUSTER_SIZE = 2
_PREFILTER_DROP_OVERRIDE_KEY = "inbound_prefilter_drop_overrides"
_SAFE_PREFILTER_SUBJECT_MARKERS = (
    "receipt",
    "payout",
    "review",
    "survey",
    "reimbursement",
    "support",
    "newsletter",
    "superhost",
    "host club",
    "community",
)
_COMMON_WORDS = {
    "a", "an", "and", "are", "at", "be", "can", "do", "for", "from", "have",
    "hi", "how", "i", "if", "in", "is", "it", "my", "of", "on", "or", "our",
    "the", "to", "we", "what", "when", "where", "with", "you", "your",
}


@dataclass(frozen=True)
class PropertyAliasEvidence:
    normalization_id: str
    selected_mention: str
    selected_property_code: str
    selected_surface: str


@dataclass(frozen=True)
class ProposedHeal:
    proposal_kind: str
    signal_source: str
    dedup_key: str
    summary: str
    evidence: list[dict[str, Any]]
    proposed_change: dict[str, Any]
    confidence: float
    cluster_size: int


@dataclass(frozen=True)
class IntentSuggestionEvidence:
    normalization_id: str
    original_intent: str
    escalated_intent: str
    latest_guest_turn: str


@dataclass(frozen=True)
class PrefilterDropSuggestionEvidence:
    normalization_id: str
    sender_address: str
    raw_subject: str
    latest_guest_turn: str
    sender_domain: str
    subject_marker: str


class HealerAgent(BaseAgent):
    agent_type = AgentType.HEALER
    name = "Healer Agent"
    description = "deterministic-logic proposal curation from parser/classifier audit signals"
    capabilities = [
        AgentCapability(
            name="scan_for_proposals",
            description="scan recent audit rows and draft reviewable deterministic-healing proposals",
        ),
        AgentCapability(
            name="approve_proposal",
            description="approve an existing healer proposal and apply the canonical write path for that proposal kind",
        ),
    ]

    async def execute(self, task: AgentTask) -> AgentResponse:
        if task.task_type == "scan_for_proposals":
            tenant_id = UUID(str(task.input_data["tenant_id"]))
            window_hours = int(task.input_data.get("window_hours", 24))
            proposals = await self.scan_for_proposals(task.input_data["db"], tenant_id, window_hours=window_hours)
            return AgentResponse(
                task_id=task.id,
                success=True,
                data={"proposal_count": len(proposals)},
                message=f"Drafted {len(proposals)} healer proposals",
            )
        if task.task_type == "approve_proposal":
            tenant_id = UUID(str(task.input_data["tenant_id"]))
            proposal_id = UUID(str(task.input_data["proposal_id"]))
            operator_id = str(task.input_data["operator_id"])
            approved = await self.approve_proposal(
                task.input_data["db"],
                tenant_id,
                proposal_id,
                operator_id,
                review_notes=str(task.input_data.get("review_notes", "") or ""),
            )
            return AgentResponse(
                task_id=task.id,
                success=approved,
                data={"approved": approved},
                message="Proposal approved" if approved else "Proposal not found",
            )
        return AgentResponse(
            task_id=task.id,
            success=False,
            message=f"Unsupported healer task_type={task.task_type!r}",
        )

    async def scan_for_proposals(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        *,
        window_hours: int = 24,
    ) -> list[ProposedHeal]:
        proposals: list[ProposedHeal] = []
        proposals.extend(await self._scan_property_alias_signals(db, tenant_id, window_hours))
        proposals.extend(await self._scan_intent_classifier_signals(db, tenant_id, window_hours))
        proposals.extend(await self._scan_prefilter_gate_failure_signals(db, tenant_id, window_hours))
        return proposals

    async def save_proposals(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        proposals: list[ProposedHeal],
    ) -> list[str]:
        if not proposals:
            return []

        saved_ids: list[str] = []
        try:
            for proposal in proposals:
                result = await db.execute(
                    text(
                        """
                        INSERT INTO healer_proposals (
                            tenant_id,
                            proposal_kind,
                            signal_source,
                            dedup_key,
                            summary,
                            evidence,
                            proposed_change,
                            status,
                            confidence,
                            cluster_size
                        )
                        VALUES (
                            CAST(:tenant_id AS uuid),
                            :proposal_kind,
                            :signal_source,
                            :dedup_key,
                            :summary,
                            CAST(:evidence AS jsonb),
                            CAST(:proposed_change AS jsonb),
                            'pending',
                            :confidence,
                            :cluster_size
                        )
                        ON CONFLICT (tenant_id, proposal_kind, dedup_key)
                        WHERE status = 'pending'
                        DO UPDATE SET
                            signal_source = EXCLUDED.signal_source,
                            summary = EXCLUDED.summary,
                            evidence = EXCLUDED.evidence,
                            proposed_change = EXCLUDED.proposed_change,
                            confidence = EXCLUDED.confidence,
                            cluster_size = EXCLUDED.cluster_size
                        RETURNING proposal_id
                        """
                    ),
                    {
                        "tenant_id": str(tenant_id),
                        "proposal_kind": proposal.proposal_kind,
                        "signal_source": proposal.signal_source,
                        "dedup_key": proposal.dedup_key,
                        "summary": proposal.summary,
                        "evidence": json.dumps(proposal.evidence),
                        "proposed_change": json.dumps(proposal.proposed_change),
                        "confidence": proposal.confidence,
                        "cluster_size": proposal.cluster_size,
                    },
                )
                proposal_id = str(result.scalar_one())
                saved_ids.append(proposal_id)
                await self._record_healer_audit(
                    db,
                    tenant_id=tenant_id,
                    proposal_id=proposal_id,
                    proposal_kind=proposal.proposal_kind,
                    signal_source=proposal.signal_source,
                    normalization_ids=[
                        str(item["normalization_id"])
                        for item in proposal.evidence
                        if item.get("normalization_id")
                    ],
                )
            await db.commit()
            return saved_ids
        except (DBAPIError, ProgrammingError) as exc:
            await safe_rollback(db)
            logger.warning(
                "[HealerAgent] save_proposals failed tenant_id=%s err=%s",
                tenant_id,
                exc,
                exc_info=True,
            )
            return []

    async def approve_proposal(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        proposal_id: UUID,
        operator_id: str,
        *,
        review_notes: str = "",
    ) -> bool:
        try:
            row = (
                await db.execute(
                    text(
                        """
                        SELECT proposal_kind, proposed_change
                        FROM healer_proposals
                        WHERE tenant_id = CAST(:tenant_id AS uuid)
                          AND proposal_id = CAST(:proposal_id AS uuid)
                          AND status = 'pending'
                        LIMIT 1
                        """
                    ),
                    {
                        "tenant_id": str(tenant_id),
                        "proposal_id": str(proposal_id),
                    },
                )
            ).mappings().first()
            if not row:
                return False

            proposal_kind = str(row["proposal_kind"])
            proposed_change = row.get("proposed_change") or {}
            if proposal_kind == "property_alias_suggestion":
                await self._apply_property_alias_suggestion(
                    db,
                    tenant_id=tenant_id,
                    proposal_id=proposal_id,
                    operator_id=operator_id,
                    proposed_change=proposed_change,
                )
            elif proposal_kind == "intent_classifier_keyword_suggestion":
                await self._apply_intent_keyword_suggestion(
                    db,
                    tenant_id=tenant_id,
                    proposal_id=proposal_id,
                    operator_id=operator_id,
                    proposed_change=proposed_change,
                )
            elif proposal_kind == "prefilter_drop_pattern_suggestion":
                await self._apply_prefilter_drop_pattern_suggestion(
                    db,
                    tenant_id=tenant_id,
                    proposal_id=proposal_id,
                    operator_id=operator_id,
                    proposed_change=proposed_change,
                )
            else:
                logger.warning("[HealerAgent] unknown proposal kind %s", proposal_kind)
                return False

            result = await db.execute(
                text(
                    """
                    UPDATE healer_proposals
                    SET status = 'approved',
                        reviewed_at = NOW(),
                        reviewed_by = :reviewed_by,
                        review_notes = :review_notes
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                      AND proposal_id = CAST(:proposal_id AS uuid)
                      AND status = 'pending'
                    RETURNING proposal_id
                    """
                ),
                {
                    "tenant_id": str(tenant_id),
                    "proposal_id": str(proposal_id),
                    "reviewed_by": operator_id,
                    "review_notes": review_notes or None,
                },
            )
            updated = result.scalar_one_or_none() is not None
            await db.commit()
            return updated
        except (DBAPIError, ProgrammingError) as exc:
            await safe_rollback(db)
            logger.warning(
                "[HealerAgent] approve_proposal failed tenant_id=%s proposal_id=%s err=%s",
                tenant_id,
                proposal_id,
                exc,
                exc_info=True,
            )
            return False

    async def list_pending_proposals(
        self,
        db: AsyncSession,
        tenant_id: UUID,
    ) -> list[dict[str, Any]]:
        try:
            rows = (
                await db.execute(
                    text(
                        """
                        SELECT
                            proposal_id,
                            proposal_kind,
                            signal_source,
                            summary,
                            evidence,
                            proposed_change,
                            status,
                            confidence,
                            cluster_size,
                            created_at,
                            reviewed_at,
                            reviewed_by,
                            review_notes
                        FROM healer_proposals
                        WHERE tenant_id = CAST(:tenant_id AS uuid)
                          AND status = 'pending'
                        ORDER BY created_at DESC
                        """
                    ),
                    {"tenant_id": str(tenant_id)},
                )
            ).mappings().all()
            return [dict(row) for row in rows]
        except (DBAPIError, ProgrammingError) as exc:
            await safe_rollback(db)
            logger.warning(
                "[HealerAgent] list_pending_proposals failed tenant_id=%s err=%s",
                tenant_id,
                exc,
                exc_info=True,
            )
            return []

    async def _scan_property_alias_signals(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        window_hours: int,
    ) -> list[ProposedHeal]:
        rows = await self._fetch_disagreement_audits(db, tenant_id, window_hours)
        clusters = self._cluster_property_alias_rows(rows)
        proposals: list[ProposedHeal] = []
        for cluster in clusters:
            if len(cluster) < MIN_HEALER_CLUSTER_SIZE:
                continue
            proposals.append(self._draft_alias_proposal(cluster))
        return proposals

    async def _scan_intent_classifier_signals(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        window_hours: int,
    ) -> list[ProposedHeal]:
        rows = await self._fetch_intent_disagreement_audits(db, tenant_id, window_hours)
        clusters = self._cluster_intent_suggestion_rows(rows)
        proposals: list[ProposedHeal] = []
        for cluster in clusters:
            if len(cluster) < MIN_HEALER_CLUSTER_SIZE:
                continue
            proposal = self._draft_intent_keyword_proposal(cluster)
            if proposal.proposed_change.get("suggested_keywords"):
                proposals.append(proposal)
        return proposals

    async def _scan_prefilter_gate_failure_signals(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        window_hours: int,
    ) -> list[ProposedHeal]:
        rows = await self._fetch_prefilter_gate_failure_audits(db, tenant_id, window_hours)
        clusters = self._cluster_prefilter_rows(rows)
        proposals: list[ProposedHeal] = []
        for cluster in clusters:
            if len(cluster) < MIN_HEALER_CLUSTER_SIZE:
                continue
            proposals.append(self._draft_prefilter_drop_proposal(cluster))
        return proposals

    async def _fetch_disagreement_audits(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        window_hours: int,
    ) -> list[PropertyAliasEvidence]:
        try:
            rows = (
                await db.execute(
                    text(
                        """
                        SELECT
                            mn.normalization_id,
                            mn.selected_property_code,
                            note->>'selected_mention' AS selected_mention,
                            note->>'selected_surface' AS selected_surface
                        FROM message_normalizations AS mn
                        CROSS JOIN LATERAL jsonb_array_elements(COALESCE(mn.parser_notes, '[]'::jsonb)) AS note
                        WHERE mn.tenant_id = CAST(:tenant_id AS uuid)
                          AND mn.created_at >= NOW() - make_interval(hours => :window_hours)
                          AND note->>'type' = 'property_mention_surface_audit'
                          AND note->>'parser_path' = 'llm_primary'
                          AND COALESCE(note->>'selected_mention', '') <> ''
                          AND COALESCE(mn.selected_property_code, '') <> ''
                          AND note->>'agreement' = 'false'
                        ORDER BY mn.created_at DESC
                        """
                    ),
                    {
                        "tenant_id": str(tenant_id),
                        "window_hours": int(window_hours),
                    },
                )
            ).mappings().all()
            return [
                PropertyAliasEvidence(
                    normalization_id=str(row["normalization_id"]),
                    selected_mention=str(row["selected_mention"]),
                    selected_property_code=str(row["selected_property_code"]),
                    selected_surface=str(row["selected_surface"] or "unknown"),
                )
                for row in rows
            ]
        except (DBAPIError, ProgrammingError) as exc:
            await safe_rollback(db)
            logger.warning(
                "[HealerAgent] disagreement audit scan failed tenant_id=%s err=%s",
                tenant_id,
                exc,
                exc_info=True,
            )
            return []

    async def _fetch_intent_disagreement_audits(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        window_hours: int,
    ) -> list[IntentSuggestionEvidence]:
        try:
            rows = (
                await db.execute(
                    text(
                        """
                        SELECT
                            mn.normalization_id,
                            mn.latest_guest_turn,
                            note->>'original_intent' AS original_intent,
                            note->>'escalated_topic' AS escalated_topic
                        FROM message_normalizations AS mn
                        CROSS JOIN LATERAL jsonb_array_elements(COALESCE(mn.parser_notes, '[]'::jsonb)) AS note
                        WHERE mn.tenant_id = CAST(:tenant_id AS uuid)
                          AND mn.created_at >= NOW() - make_interval(hours => :window_hours)
                          AND note->>'type' = 'brain_classifier_metadata'
                          AND note->>'escalated' = 'true'
                          AND COALESCE(note->>'escalated_topic', '') <> ''
                          AND COALESCE(note->>'original_intent', '') <> COALESCE(note->>'escalated_topic', '')
                        ORDER BY mn.created_at DESC
                        """
                    ),
                    {"tenant_id": str(tenant_id), "window_hours": int(window_hours)},
                )
            ).mappings().all()
            return [
                IntentSuggestionEvidence(
                    normalization_id=str(row["normalization_id"]),
                    original_intent=str(row["original_intent"]),
                    escalated_intent=str(row["escalated_topic"]),
                    latest_guest_turn=str(row.get("latest_guest_turn") or ""),
                )
                for row in rows
            ]
        except (DBAPIError, ProgrammingError) as exc:
            await safe_rollback(db)
            logger.warning(
                "[HealerAgent] intent disagreement audit scan failed tenant_id=%s err=%s",
                tenant_id,
                exc,
                exc_info=True,
            )
            return []

    async def _fetch_prefilter_gate_failure_audits(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        window_hours: int,
    ) -> list[PrefilterDropSuggestionEvidence]:
        try:
            rows = (
                await db.execute(
                    text(
                        """
                        SELECT
                            normalization_id,
                            COALESCE(sender_address, '') AS sender_address,
                            COALESCE(raw_subject, '') AS raw_subject,
                            COALESCE(latest_guest_turn, '') AS latest_guest_turn
                        FROM message_normalizations
                        WHERE tenant_id = CAST(:tenant_id AS uuid)
                          AND created_at >= NOW() - make_interval(hours => :window_hours)
                          AND COALESCE(route_outcome, '') = 'pre_booking_gate_error'
                          AND COALESCE(draft_source, '') = 'inbound_gate'
                        ORDER BY created_at DESC
                        """
                    ),
                    {"tenant_id": str(tenant_id), "window_hours": int(window_hours)},
                )
            ).mappings().all()
        except (DBAPIError, ProgrammingError) as exc:
            await safe_rollback(db)
            logger.warning(
                "[HealerAgent] prefilter gate failure scan failed tenant_id=%s err=%s",
                tenant_id,
                exc,
                exc_info=True,
            )
            return []

        evidence_rows: list[PrefilterDropSuggestionEvidence] = []
        for row in rows:
            sender_address = str(row.get("sender_address") or "").strip().lower()
            raw_subject = str(row.get("raw_subject") or "").strip()
            latest_guest_turn = str(row.get("latest_guest_turn") or "").strip()
            sender_domain = sender_address.rsplit("@", 1)[-1] if "@" in sender_address else ""
            subject_marker = self._extract_prefilter_subject_marker(raw_subject)
            if not sender_domain or not subject_marker:
                continue
            if NON_GUEST_REGISTRY.classify(
                from_header=sender_address,
                subject=raw_subject,
                plain_text=latest_guest_turn,
                raw_html="",
            ):
                continue
            evidence_rows.append(
                PrefilterDropSuggestionEvidence(
                    normalization_id=str(row["normalization_id"]),
                    sender_address=sender_address,
                    raw_subject=raw_subject,
                    latest_guest_turn=latest_guest_turn,
                    sender_domain=sender_domain,
                    subject_marker=subject_marker,
                )
            )
        return evidence_rows

    def _cluster_property_alias_rows(
        self,
        rows: list[PropertyAliasEvidence],
    ) -> list[list[PropertyAliasEvidence]]:
        grouped: dict[tuple[str, str], list[PropertyAliasEvidence]] = {}
        for row in rows:
            normalized = self._normalize_mention(row.selected_mention)
            if not normalized or not row.selected_property_code:
                continue
            grouped.setdefault((normalized, row.selected_property_code), []).append(row)
        return list(grouped.values())

    def _cluster_intent_suggestion_rows(
        self,
        rows: list[IntentSuggestionEvidence],
    ) -> list[list[IntentSuggestionEvidence]]:
        grouped: dict[tuple[str, str], list[IntentSuggestionEvidence]] = {}
        for row in rows:
            key = (row.original_intent.strip(), row.escalated_intent.strip())
            grouped.setdefault(key, []).append(row)
        return list(grouped.values())

    def _cluster_prefilter_rows(
        self,
        rows: list[PrefilterDropSuggestionEvidence],
    ) -> list[list[PrefilterDropSuggestionEvidence]]:
        grouped: dict[tuple[str, str], list[PrefilterDropSuggestionEvidence]] = {}
        for row in rows:
            key = (row.sender_domain.strip(), row.subject_marker.strip())
            grouped.setdefault(key, []).append(row)
        return list(grouped.values())

    def _draft_alias_proposal(
        self,
        cluster: list[PropertyAliasEvidence],
    ) -> ProposedHeal:
        exemplar = cluster[0]
        normalized_mention = self._normalize_mention(exemplar.selected_mention)
        canonical_property_code = exemplar.selected_property_code
        dedup_key = self._dedup_key(
            {
                "normalized_mention": normalized_mention,
                "canonical_property_code": canonical_property_code,
                "proposal_kind": "property_alias_suggestion",
            }
        )
        evidence = [
            {
                "normalization_id": row.normalization_id,
                "selected_mention": row.selected_mention,
                "selected_property_code": row.selected_property_code,
                "selected_surface": row.selected_surface,
            }
            for row in cluster
        ]
        cluster_size = len(cluster)
        confidence = min(0.5 + (0.1 * cluster_size), 1.0)
        summary = (
            f"LLM extracted '{exemplar.selected_mention}' across {cluster_size} messages "
            f"that resolved to property {canonical_property_code}; deterministic matching missed it."
        )
        proposed_change = {
            "kind": "property_alias_suggestion",
            "extracted_mention": exemplar.selected_mention,
            "normalized_mention": normalized_mention,
            "canonical_property_code": canonical_property_code,
            "alias_kind": "name",
            "evidence_normalization_ids": [row.normalization_id for row in cluster],
        }
        return ProposedHeal(
            proposal_kind="property_alias_suggestion",
            signal_source="property_mention_surface_audit",
            dedup_key=dedup_key,
            summary=summary,
            evidence=evidence,
            proposed_change=proposed_change,
            confidence=confidence,
            cluster_size=cluster_size,
        )

    def _draft_intent_keyword_proposal(
        self,
        cluster: list[IntentSuggestionEvidence],
    ) -> ProposedHeal:
        exemplar = cluster[0]
        suggested_keywords = self._common_keywords([row.latest_guest_turn for row in cluster])
        dedup_key = self._dedup_key(
            {
                "proposal_kind": "intent_classifier_keyword_suggestion",
                "original_intent": exemplar.original_intent,
                "target_intent": exemplar.escalated_intent,
                "sorted_keywords": sorted(suggested_keywords),
            }
        )
        evidence = [
            {
                "normalization_id": row.normalization_id,
                "original_intent": row.original_intent,
                "escalated_intent": row.escalated_intent,
                "latest_guest_turn": row.latest_guest_turn,
            }
            for row in cluster
        ]
        cluster_size = len(cluster)
        confidence = min(0.45 + (0.1 * cluster_size), 1.0)
        summary = (
            f"Keyword classifier routed {cluster_size} messages from {exemplar.original_intent} "
            f"to {exemplar.escalated_intent} after escalation. Consider adding {', '.join(suggested_keywords[:4])}."
        )
        proposed_change = {
            "kind": "intent_classifier_keyword_suggestion",
            "original_intent": exemplar.original_intent,
            "target_intent": exemplar.escalated_intent,
            "suggested_keywords": suggested_keywords,
            "evidence_normalization_ids": [row.normalization_id for row in cluster],
        }
        return ProposedHeal(
            proposal_kind="intent_classifier_keyword_suggestion",
            signal_source="brain_classifier_metadata",
            dedup_key=dedup_key,
            summary=summary,
            evidence=evidence,
            proposed_change=proposed_change,
            confidence=confidence,
            cluster_size=cluster_size,
        )

    def _draft_prefilter_drop_proposal(
        self,
        cluster: list[PrefilterDropSuggestionEvidence],
    ) -> ProposedHeal:
        exemplar = cluster[0]
        dedup_key = self._dedup_key(
            {
                "proposal_kind": "prefilter_drop_pattern_suggestion",
                "sender_domain": exemplar.sender_domain,
                "subject_marker": exemplar.subject_marker,
            }
        )
        evidence = [
            {
                "normalization_id": row.normalization_id,
                "sender_address": row.sender_address,
                "raw_subject": row.raw_subject,
                "latest_guest_turn": row.latest_guest_turn,
                "sender_domain": row.sender_domain,
                "subject_marker": row.subject_marker,
            }
            for row in cluster
        ]
        cluster_size = len(cluster)
        confidence = min(0.4 + (0.1 * cluster_size), 0.95)
        summary = (
            f"Gate failures hit {cluster_size} messages from {exemplar.sender_domain} "
            f"with subject marker '{exemplar.subject_marker}'. Propose a deterministic prefilter drop override."
        )
        proposed_change = {
            "kind": "prefilter_drop_pattern_suggestion",
            "name": self._prefilter_rule_name(exemplar.sender_domain, exemplar.subject_marker),
            "sender_domain": exemplar.sender_domain,
            "subject_contains": exemplar.subject_marker,
            "evidence_normalization_ids": [row.normalization_id for row in cluster],
        }
        return ProposedHeal(
            proposal_kind="prefilter_drop_pattern_suggestion",
            signal_source="pre_booking_gate_error",
            dedup_key=dedup_key,
            summary=summary,
            evidence=evidence,
            proposed_change=proposed_change,
            confidence=confidence,
            cluster_size=cluster_size,
        )

    async def _apply_property_alias_suggestion(
        self,
        db: AsyncSession,
        *,
        tenant_id: UUID,
        proposal_id: UUID,
        operator_id: str,
        proposed_change: dict[str, Any],
    ) -> None:
        extracted_mention = str(proposed_change.get("extracted_mention") or "").strip()
        canonical_property_code = str(proposed_change.get("canonical_property_code") or "").strip()
        if not extracted_mention or not canonical_property_code:
            raise ValueError("property_alias_suggestion missing extracted_mention or canonical_property_code")
        await get_canonical_property_write_service(db).link_property_identity(
            tenant_id,
            canonical_property_code=canonical_property_code,
            ref_value=extracted_mention,
            provider="internal",
            ref_kind="alias",
            source="healer_proposal_approved",
            confidence=0.99,
            metadata={"proposal_id": str(proposal_id), "approved_by": operator_id},
        )

    async def _apply_intent_keyword_suggestion(
        self,
        db: AsyncSession,
        *,
        tenant_id: UUID,
        proposal_id: UUID,
        operator_id: str,
        proposed_change: dict[str, Any],
    ) -> None:
        target_intent = str(proposed_change.get("target_intent") or "").strip()
        suggested_keywords = [
            str(keyword).strip().casefold()
            for keyword in list(proposed_change.get("suggested_keywords") or [])
            if str(keyword).strip()
        ]
        if not target_intent or not suggested_keywords:
            raise ValueError("intent_classifier_keyword_suggestion missing target_intent or suggested_keywords")

        row = (
            await db.execute(
                text(
                    """
                    SELECT extra
                    FROM operator_settings
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                    LIMIT 1
                    """
                ),
                {"tenant_id": str(tenant_id)},
            )
        ).fetchone()
        extra = dict(row[0] or {}) if row and row[0] is not None else {}
        overrides = dict(extra.get("intent_classifier_keyword_overrides") or {})
        existing = [
            str(keyword).strip().casefold()
            for keyword in list(overrides.get(target_intent) or [])
            if str(keyword).strip()
        ]
        merged = sorted(set(existing + suggested_keywords))
        overrides[target_intent] = merged
        extra["intent_classifier_keyword_overrides"] = overrides
        extra.setdefault("healer_keyword_approvals", []).append(
            {
                "proposal_id": str(proposal_id),
                "target_intent": target_intent,
                "approved_by": operator_id,
            }
        )
        await db.execute(
            text(
                """
                INSERT INTO operator_settings (tenant_id, extra)
                VALUES (CAST(:tenant_id AS uuid), CAST(:extra AS jsonb))
                ON CONFLICT (tenant_id)
                DO UPDATE SET
                    extra = CAST(:extra AS jsonb),
                    updated_at = NOW()
                """
            ),
            {"tenant_id": str(tenant_id), "extra": json.dumps(extra)},
        )

    async def _apply_prefilter_drop_pattern_suggestion(
        self,
        db: AsyncSession,
        *,
        tenant_id: UUID,
        proposal_id: UUID,
        operator_id: str,
        proposed_change: dict[str, Any],
    ) -> None:
        sender_domain = str(proposed_change.get("sender_domain") or "").strip().lower()
        subject_contains = str(proposed_change.get("subject_contains") or "").strip().lower()
        if not sender_domain or not subject_contains:
            raise ValueError("prefilter_drop_pattern_suggestion missing sender_domain or subject_contains")

        row = (
            await db.execute(
                text(
                    """
                    SELECT extra
                    FROM operator_settings
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                    LIMIT 1
                    """
                ),
                {"tenant_id": str(tenant_id)},
            )
        ).fetchone()
        extra = dict(row[0] or {}) if row and row[0] is not None else {}
        existing_overrides = [
            dict(item)
            for item in list(extra.get(_PREFILTER_DROP_OVERRIDE_KEY) or [])
            if isinstance(item, dict)
        ]
        name = self._prefilter_rule_name(sender_domain, subject_contains)
        new_override = {
            "name": name,
            "sender_domain": sender_domain,
            "subject_contains": subject_contains,
            "proposal_id": str(proposal_id),
            "approved_by": operator_id,
        }
        merged: list[dict[str, Any]] = []
        replaced = False
        for override in existing_overrides:
            if (
                str(override.get("sender_domain") or "").strip().lower() == sender_domain
                and str(override.get("subject_contains") or "").strip().lower() == subject_contains
            ):
                merged.append(new_override)
                replaced = True
            else:
                merged.append(override)
        if not replaced:
            merged.append(new_override)
        extra[_PREFILTER_DROP_OVERRIDE_KEY] = merged
        extra.setdefault("healer_prefilter_approvals", []).append(
            {
                "proposal_id": str(proposal_id),
                "sender_domain": sender_domain,
                "subject_contains": subject_contains,
                "approved_by": operator_id,
            }
        )
        await db.execute(
            text(
                """
                INSERT INTO operator_settings (tenant_id, extra)
                VALUES (CAST(:tenant_id AS uuid), CAST(:extra AS jsonb))
                ON CONFLICT (tenant_id)
                DO UPDATE SET
                    extra = CAST(:extra AS jsonb),
                    updated_at = NOW()
                """
            ),
            {"tenant_id": str(tenant_id), "extra": json.dumps(extra)},
        )

    async def _record_healer_audit(
        self,
        db: AsyncSession,
        *,
        tenant_id: UUID,
        proposal_id: str,
        proposal_kind: str,
        signal_source: str,
        normalization_ids: list[str],
    ) -> None:
        if not normalization_ids:
            return
        payload = json.dumps(
            [
                {
                    "type": "healer_proposal_recorded",
                    "proposal_id": proposal_id,
                    "proposal_kind": proposal_kind,
                    "signal_source": signal_source,
                    "recorded_at": datetime.now(timezone.utc).isoformat(),
                }
            ]
        )
        for normalization_id in normalization_ids:
            await db.execute(
                text(
                    """
                    UPDATE message_normalizations
                    SET parser_notes = COALESCE(parser_notes, '[]'::jsonb) || CAST(:payload AS jsonb),
                        updated_at = NOW()
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                      AND normalization_id = CAST(:normalization_id AS uuid)
                      AND NOT EXISTS (
                            SELECT 1
                            FROM jsonb_array_elements(COALESCE(parser_notes, '[]'::jsonb)) AS note
                            WHERE note->>'type' = 'healer_proposal_recorded'
                              AND note->>'proposal_id' = :proposal_id
                      )
                    """
                ),
                {
                    "tenant_id": str(tenant_id),
                    "normalization_id": normalization_id,
                    "proposal_id": proposal_id,
                    "payload": payload,
                },
            )

    @staticmethod
    def _normalize_mention(value: str) -> str:
        return " ".join((value or "").casefold().split())

    @staticmethod
    def _dedup_key(payload: dict[str, Any]) -> str:
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _extract_prefilter_subject_marker(subject: str) -> str:
        lowered = (subject or "").casefold()
        for marker in _SAFE_PREFILTER_SUBJECT_MARKERS:
            if marker in lowered:
                return marker
        return ""

    @staticmethod
    def _prefilter_rule_name(sender_domain: str, subject_marker: str) -> str:
        normalized_marker = re.sub(r"[^a-z0-9]+", "_", (subject_marker or "").casefold()).strip("_") or "pattern"
        normalized_domain = re.sub(r"[^a-z0-9]+", "_", (sender_domain or "").casefold()).strip("_") or "domain"
        return f"{normalized_domain}_{normalized_marker}"

    @staticmethod
    def _common_keywords(messages: list[str]) -> list[str]:
        if not messages:
            return []
        tokenized: list[list[str]] = []
        for message in messages:
            tokens = [
                token
                for token in re.findall(r"[a-zA-Z][a-zA-Z_-]{2,}", (message or "").casefold())
                if token not in _COMMON_WORDS
            ]
            tokenized.append(tokens)
        if not tokenized:
            return []
        threshold = max(1, int(len(tokenized) * 0.75 + 0.0001))
        counts: dict[str, int] = {}
        for tokens in tokenized:
            for token in set(tokens):
                counts[token] = counts.get(token, 0) + 1
        return sorted(
            [token for token, count in counts.items() if count >= threshold],
            key=lambda token: (-counts[token], token),
        )[:8]


def get_healer_agent() -> HealerAgent:
    return HealerAgent()
