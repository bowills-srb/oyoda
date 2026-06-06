"""Brain-owned historical-question import.

Routes historical guest Q&A records into the right canonical store:

  * records with an answer + property scope  → scoped knowledge (property)
  * records with an answer + tenant scope    → global FAQ
  * records without an answer                → knowledge gaps

Replaces `ConciergeKnowledgeService.import_historical_questions` in
`app/services/concierge/knowledge_service.py`. The legacy implementation
wrote per-property FAQs into `concierge_knowledge.faq` (JSONB array) via
`_append_faq_answer` and applied an amenity-tokens "similar property"
fan-out to copy the answer across visually-similar properties. Both go
away with the legacy table:

  * Per-property writes now go through scoped knowledge, keyed on
    (tenant, scope_type='property', scope_target_id, question_key).
  * The "similar properties" fan-out is dropped. It depended on the
    legacy `property_context` and amenity tokens that don't exist in
    the scoped schema. The `apply_to_similar_properties` parameter is
    accepted for API compatibility but is a no-op.

If cross-property FAQ borrowing is wanted later, build it against the
canonical scoped table — not by porting the legacy heuristic.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.messaging_brain.knowledge.gap_recorder import (
    _write_property_faq_via_scoped,
    record_gap,
)
from app.services.messaging_brain.knowledge.global_faq import upsert_global_faq

logger = logging.getLogger(__name__)


def _try_uuid(value: Optional[str]) -> Optional[UUID]:
    if not value:
        return None
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


async def import_historical_questions(
    session: AsyncSession,
    tenant_id: UUID,
    records: List[Dict[str, Any]],
    apply_to_similar_properties: bool = True,
) -> Dict[str, Any]:
    """
    Import a batch of historical guest questions.

    Each record may include:
      question_text       (required)
      answer_text         (optional; absence routes to gap)
      property_id         (optional UUID; property-scoped FAQ)
      property_external_id(optional string; resolved to property_id)
      stage, channel, detected_intent, confidence_score, metadata
                          (passed through to gap recording if no answer)

    Returns counts:
      imported_answers  — FAQ rows created or updated (property or tenant)
      imported_gaps     — new gap rows (deduped ones not counted)
      skipped           — records missing question_text
      total_records     — input count

    `apply_to_similar_properties` is accepted for backward compatibility
    with the legacy API but has no effect — see module docstring.
    """
    _ = apply_to_similar_properties  # intentionally unused; see docstring

    imported_gaps = 0
    imported_answers = 0
    skipped = 0

    for record in records:
        question = str(record.get("question_text") or "").strip()
        if not question:
            skipped += 1
            continue

        answer = str(record.get("answer_text") or "").strip()
        property_external_id = record.get("property_external_id") or None
        property_id = _try_uuid(record.get("property_id"))
        stage = record.get("stage")
        channel = record.get("channel") or "text"

        if answer:
            if property_id or property_external_id:
                # Property-scoped historical FAQ → scoped knowledge.
                updated = await _write_property_faq_via_scoped(
                    session=session,
                    tenant_id=tenant_id,
                    property_id=property_id,
                    property_external_id=property_external_id,
                    question=question,
                    answer=answer,
                    source="historical_import",
                )
            else:
                # No property scope → tenant-wide global FAQ.
                await upsert_global_faq(
                    session=session,
                    tenant_id=tenant_id,
                    question_text=question,
                    answer_text=answer,
                    source="historical_import",
                )
                updated = 1
            if updated > 0:
                imported_answers += 1
            continue

        # No answer → gap.
        result = await record_gap(
            session=session,
            tenant_id=tenant_id,
            question_text=question,
            property_id=property_id,
            property_external_id=property_external_id,
            stage=stage,
            channel=channel,
            source="historical_import",
            detected_intent=record.get("detected_intent"),
            confidence_score=_to_float(record.get("confidence_score")),
            metadata=record.get("metadata") or {},
        )
        if not result.get("deduped"):
            imported_gaps += 1

    return {
        "imported_gaps": imported_gaps,
        "imported_answers": imported_answers,
        "skipped": skipped,
        "total_records": len(records),
    }


__all__ = ["import_historical_questions"]
