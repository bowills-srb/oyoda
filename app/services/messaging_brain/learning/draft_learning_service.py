"""
DraftLearningService — Piece B of the Oyvoda learning loop.

Captures operator approval/rejection/edit signals into operator_draft_events
and, for durable edits, proposes an ExtractionCandidate for operator review.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

DURABLE_TYPES: frozenset[str] = frozenset(
    ["fact_added", "fact_corrected", "policy_clarified", "price_added", "price_declined"]
)

_STYLE_TYPES: frozenset[str] = frozenset(
    ["tone_softer", "tone_firmer", "length_shortened", "length_expanded",
     "cta_changed", "minor_polish", "complete_rewrite"]
)


class DraftLearningService:
    """Records operator draft interactions and proposes extraction candidates."""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def record_approval(
        self,
        db: AsyncSession,
        company_id: str,
        draft_id: str,
        intent: str,
        property_external_id: Optional[str],
    ) -> None:
        await self._insert_event(
            db,
            company_id=company_id,
            draft_id=draft_id,
            intent=intent,
            property_external_id=property_external_id,
            event_type="approved_unchanged",
        )
        await db.commit()

    async def record_rejection(
        self,
        db: AsyncSession,
        company_id: str,
        draft_id: str,
        intent: str,
        property_external_id: Optional[str],
    ) -> None:
        await self._insert_event(
            db,
            company_id=company_id,
            draft_id=draft_id,
            intent=intent,
            property_external_id=property_external_id,
            event_type="rejected",
        )
        await db.commit()

    async def record_edit_and_propose(
        self,
        db: AsyncSession,
        company_id: str,
        draft_id: str,
        intent: str,
        property_external_id: Optional[str],
        original_draft: str,
        edited_text: str,
        scope_type: str = "property",
        scope_target_id: Optional[str] = None,
    ) -> None:
        # Step 1: analyze
        from app.services.concierge.operator_learning import EditAnalyzer
        analyzer = EditAnalyzer()
        analysis = analyzer.analyze(original_draft, edited_text)

        # Step 2: insert raw event
        await self._insert_event(
            db,
            company_id=company_id,
            draft_id=draft_id,
            intent=intent,
            property_external_id=property_external_id,
            event_type="edited",
            original_draft=original_draft,
            edited_text=edited_text,
            edit_type=analysis.edit_type.value,
            similarity_score=analysis.similarity_score,
            added_phrases=analysis.added_phrases,
            price_signals=analysis.price_signals,
            policy_signals=analysis.policy_signals,
            property_facts=analysis.property_facts,
        )
        await db.commit()

        # Step 3: propose candidate for durable edits
        if analysis.edit_type.value in DURABLE_TYPES:
            try:
                final_scope_target_id = scope_target_id if scope_target_id else company_id
                from app.services.extraction.staging_service import ExtractionStagingService
                staging = ExtractionStagingService()
                # Map intent to a registry topic_id when the intent string matches
                # exactly — this makes the proposal classifiable by Gap 4's coverage
                # check (which requires topic_id IS NOT NULL). Non-matching intents
                # (e.g. "general") produce topic_id=None; that's honest, not broken.
                from app.services.messaging_brain.knowledge.topic_registry import TOPIC_REGISTRY
                topic_id_for_candidate = intent if intent in TOPIC_REGISTRY else None

                await staging.create_candidate(
                    session=db,
                    tenant_id=company_id,
                    scope_type=scope_type,
                    scope_target_id=final_scope_target_id,
                    source_type="other",
                    extraction_method="deterministic",
                    candidate_type="fact",
                    proposed_question_text=f"Draft edit ({analysis.edit_type.value}): {intent}",
                    proposed_answer_text=edited_text,
                    proposed_topic_id=topic_id_for_candidate,
                    confidence=0.75,
                    evidence_excerpt=edited_text[:300],
                    proposed_metadata={
                        "draft_id": draft_id,
                        "edit_type": analysis.edit_type.value,
                        "original_draft": original_draft[:300],
                        "source": "operator_draft_edit",
                    },
                )
            except Exception as proposal_exc:
                logger.debug(
                    "[DraftLearning] candidate proposal failed for draft %s: %s",
                    draft_id,
                    proposal_exc,
                )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _insert_event(
        self,
        db: AsyncSession,
        *,
        company_id: str,
        draft_id: str,
        intent: str,
        property_external_id: Optional[str],
        event_type: str,
        original_draft: Optional[str] = None,
        edited_text: Optional[str] = None,
        edit_type: Optional[str] = None,
        similarity_score: Optional[float] = None,
        added_phrases: Optional[list] = None,
        price_signals: Optional[list] = None,
        policy_signals: Optional[list] = None,
        property_facts: Optional[list] = None,
    ) -> str:
        event_id = str(uuid4())
        await db.execute(
            text("""
                INSERT INTO operator_draft_events (
                    id, company_id, draft_id, intent, property_external_id,
                    event_type, original_draft, edited_text, edit_type,
                    similarity_score, added_phrases, price_signals,
                    policy_signals, property_facts, created_at
                ) VALUES (
                    CAST(:id AS uuid),
                    CAST(:company_id AS uuid),
                    :draft_id,
                    :intent,
                    :property_external_id,
                    :event_type,
                    :original_draft,
                    :edited_text,
                    :edit_type,
                    :similarity_score,
                    :added_phrases,
                    :price_signals,
                    :policy_signals,
                    :property_facts,
                    :created_at
                )
            """),
            {
                "id": event_id,
                "company_id": company_id,
                "draft_id": draft_id,
                "intent": intent,
                "property_external_id": property_external_id,
                "event_type": event_type,
                "original_draft": original_draft,
                "edited_text": edited_text,
                "edit_type": edit_type,
                "similarity_score": similarity_score,
                "added_phrases": json.dumps(added_phrases) if added_phrases is not None else None,
                "price_signals": json.dumps(price_signals) if price_signals is not None else None,
                "policy_signals": json.dumps(policy_signals) if policy_signals is not None else None,
                "property_facts": json.dumps(property_facts) if property_facts is not None else None,
                "created_at": datetime.now(timezone.utc),
            },
        )
        return event_id


def get_draft_learning_service() -> DraftLearningService:
    """Return a DraftLearningService instance (stateless, cheap to construct)."""
    return DraftLearningService()
