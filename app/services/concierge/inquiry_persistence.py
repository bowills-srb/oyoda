from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy import text

from app.services.messaging.message_event_store import (
    persist_canonical_inbound_message,
    update_normalization_outcome,
)


logger = logging.getLogger(__name__)


async def _load_selected_property_code_from_normalization(
    *,
    db,
    tenant_id,
    source_channel: str,
    source_message_id: str,
) -> str:
    if not db or not source_message_id:
        return ""
    try:
        row = await db.execute(
            text(
                """
                SELECT selected_property_code
                FROM message_normalizations
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND source_channel = :source_channel
                  AND source_message_id = :source_message_id
                LIMIT 1
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "source_channel": source_channel,
                "source_message_id": source_message_id,
            },
        )
        record = row.fetchone()
        return str(getattr(record, "selected_property_code", "") or "").strip()
    except Exception:
        logger.warning(
            "[InquiryPersistence] failed to load selected_property_code tenant=%s source_message_id=%s",
            tenant_id,
            source_message_id,
            exc_info=True,
        )
        return ""


async def persist_pre_booking_inquiry_with_normalization(
    *,
    db,
    inbound,
    context,
    normalization_kwargs: Optional[dict[str, Any]] = None,
):
    """Persist the inquiry row only after the normalization row exists.

    This is the single sanctioned seam for creating pre-booking inquiry
    rows from canonical inbound data. It ensures a matching
    ``message_normalizations`` row exists before the inquiry row is
    inserted, then records best-effort outcome metadata after the save.
    """
    from app.services.messaging_brain.persistence.prebooking_inquiry_store import (
        SaveInquiryResult,
        _save_inquiry,
    )

    if not db:
        return SaveInquiryResult(inserted=False, status="save_failed")

    normalization_result = await persist_canonical_inbound_message(
        db,
        context.company_id,
        inbound,
    )
    if inbound.source_message_id and not normalization_result.get("normalization_id"):
        logger.error(
            "[InquiryPersistence] missing normalization row tenant=%s source_message_id=%s",
            context.company_id,
            inbound.source_message_id,
        )
        return SaveInquiryResult(
            inserted=False,
            status="save_failed",
            guest_thread_id=context.guest_thread_id,
            error_type="MissingNormalizationRow",
            error_message="persist_canonical_inbound_message did not create a normalization row",
        )

    selected_property_code = (context.selected_property_code or "").strip()
    if not selected_property_code:
        selected_property_code = await _load_selected_property_code_from_normalization(
            db=db,
            tenant_id=context.company_id,
            source_channel=inbound.source_channel,
            source_message_id=inbound.source_message_id,
        )

    save_result = await _save_inquiry(
        db=db,
        draft_id=context.draft_id,
        thread_id=inbound.source_thread_id,
        message_id=inbound.source_message_id,
        company_id=context.company_id,
        platform=inbound.source_provider or inbound.source_channel,
        guest_name=inbound.guest_name or inbound.sender_display_name or "Guest",
        message_text=inbound.latest_guest_turn or inbound.full_message_text,
        check_in=context.requested_check_in,
        check_out=context.requested_check_out,
        guests=context.requested_guests,
        property_external_id=selected_property_code,
        intent=context.intent,
        confidence=context.confidence,
        draft_text=context.draft_text,
        policy_flags=context.policy_flags,
        policy_warnings=context.policy_warnings,
        decision=context.decision,
        guest_thread_id=context.guest_thread_id,
        blocked_by_gap_topics=context.blocked_by_gap_topics,
        triggered_by=context.triggered_by,
        # Phase 1 confidence split. These come from InquirySaveContext
        # with safe defaults (intent_only / NULLs). Real values arrive
        # in commit 2B when call sites that build the context populate
        # them from the brain and exception paths.
        intent_confidence=context.intent_confidence,
        draft_confidence=context.draft_confidence,
        confidence_source=context.confidence_source,
        review_verdict=context.review_verdict,
    )

    outcome_payload = {
        "selected_property_code": selected_property_code,
        "route_outcome": "pre_booking_saved" if save_result.inserted else save_result.status,
        "draft_source": context.draft_source,
        "fallback_reason": " | ".join(context.policy_warnings or [])[:400],
    }
    if normalization_kwargs:
        outcome_payload.update({k: v for k, v in normalization_kwargs.items() if v is not None})

    await update_normalization_outcome(
        db,
        context.company_id,
        inbound.source_channel,
        inbound.source_message_id,
        **outcome_payload,
    )
    return save_result
