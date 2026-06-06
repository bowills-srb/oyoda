from __future__ import annotations

import json
import logging
from typing import List, Optional

from app.services.identity.dual_write import resolve_dual_write_identity
from app.services.messaging.inbound_normalizer import CanonicalInboundMessage
from app.services.messaging_brain.persistence.prebooking_inquiry_types import (
    InquirySaveContext,
    SaveInquiryResult,
    _pg_text_array_literal,
)


logger = logging.getLogger(__name__)


async def save_inquiry_from_canonical(
    *,
    db,
    inbound: CanonicalInboundMessage,
    context: InquirySaveContext,
    normalization_kwargs: Optional[dict[str, object]] = None,
) -> SaveInquiryResult:
    from app.services.concierge.inquiry_persistence import (
        persist_pre_booking_inquiry_with_normalization,
    )

    return await persist_pre_booking_inquiry_with_normalization(
        db=db,
        inbound=inbound,
        context=context,
        normalization_kwargs=normalization_kwargs,
    )


async def _guest_thread_exists(db, guest_thread_id: str) -> bool:
    from sqlalchemy import text

    row = await db.execute(
        text(
            """
            SELECT 1
            FROM guest_threads
            WHERE guest_thread_id = CAST(:guest_thread_id AS uuid)
            LIMIT 1
            """
        ),
        {"guest_thread_id": guest_thread_id},
    )
    return row.scalar_one_or_none() is not None


async def _resolve_guest_thread_id_for_save(
    db,
    *,
    company_id,
    property_external_id,
    guest_name,
    thread_id,
    guest_thread_id: Optional[str],
) -> str:
    from app.services.concierge.guest_thread_service import get_guest_thread_service

    if guest_thread_id:
        if await _guest_thread_exists(db, guest_thread_id):
            return guest_thread_id
        logger.warning(
            "[PreBooking] Missing pre-resolved guest_thread_id=%s for thread_id=%s message persistence; re-resolving",
            guest_thread_id,
            thread_id,
        )

    return await get_guest_thread_service().ensure_inquiry_thread(
        db,
        tenant_id=str(company_id),
        property_code=property_external_id,
        guest_name=guest_name,
        inquiry_thread_id=thread_id,
    )


async def _insert_pre_booking_inquiry(
    db,
    *,
    resolved_guest_thread_id: str,
    draft_id: str,
    thread_id: str,
    message_id: str,
    company_id,
    platform: str,
    guest_name: str,
    message_text: str,
    check_in,
    check_out,
    guests,
    property_external_id: str,
    intent: str,
    confidence: float,
    draft_text: str,
    policy_flags,
    policy_warnings,
    decision: str,
    blocked_by_gap_topics,
    triggered_by: Optional[str] = None,
    intent_confidence: Optional[float] = None,
    draft_confidence: Optional[float] = None,
    confidence_source: str = "intent_only",
    review_verdict: Optional[str] = None,
    autonomy_decision: str = "routed_to_action_auto_off",
):
    from sqlalchemy import text

    tenant_uuid, company_uuid = resolve_dual_write_identity(
        tenant_id=company_id,
        company_id=company_id,
        context="prebooking_inquiry_store._insert_pre_booking_inquiry",
    )

    return await db.execute(
        text(
            """
            INSERT INTO pre_booking_inquiries (
                guest_thread_id,
                draft_id, thread_id, message_id, tenant_id, company_id,
                platform, guest_name, message_text,
                requested_check_in, requested_check_out, requested_guests,
                property_external_id, intent, confidence,
                intent_confidence, draft_confidence,
                confidence_source, review_verdict, autonomy_decision,
                draft_text, policy_flags, policy_warnings,
                blocked_by_gap_topics, triggered_by,
                status, received_at, created_at
            ) VALUES (
                CAST(:guest_thread_id AS uuid),
                :draft_id, :thread_id, :msg_id, :tid, :cid,
                :platform, :guest, :msg,
                :ci, :co, :guests,
                :prop, :intent, :conf,
                :intent_conf, :draft_conf,
                CAST(:conf_source AS confidence_source),
                CAST(:review_verdict AS review_verdict),
                CAST(:autonomy_decision AS autonomy_decision),
                :draft, :flags, :warnings,
                CAST(:blocked_topics AS text[]), :triggered_by,
                :status, NOW(), NOW()
            )
            ON CONFLICT (thread_id, message_id) DO NOTHING
            """
        ),
        {
            "guest_thread_id": resolved_guest_thread_id,
            "draft_id": draft_id,
            "thread_id": thread_id,
            "msg_id": message_id or "",
            "tid": tenant_uuid,
            "cid": company_uuid,
            "platform": platform,
            "guest": guest_name,
            "msg": message_text,
            "ci": check_in,
            "co": check_out,
            "guests": guests,
            "prop": property_external_id,
            "intent": intent,
            "conf": confidence,
            "intent_conf": intent_confidence,
            "draft_conf": draft_confidence,
            "conf_source": confidence_source,
            "review_verdict": review_verdict,
            "autonomy_decision": autonomy_decision,
            "draft": draft_text,
            "flags": json.dumps(policy_flags),
            "warnings": json.dumps(policy_warnings),
            "blocked_topics": _pg_text_array_literal(blocked_by_gap_topics),
            "triggered_by": triggered_by,
            "status": "replied" if decision == "send_now" else "pending_review",
        },
    )


def _is_missing_guest_thread_fk(exc: Exception) -> bool:
    message = str(exc)
    return (
        "fk_pre_booking_inquiries_guest_thread" in message
        and "guest_threads" in message
    )


async def _save_inquiry(
    db,
    draft_id,
    thread_id,
    message_id,
    company_id,
    platform,
    guest_name,
    message_text,
    check_in,
    check_out,
    guests,
    property_external_id,
    intent,
    confidence,
    draft_text,
    policy_flags,
    policy_warnings,
    decision,
    guest_thread_id: Optional[str] = None,
    blocked_by_gap_topics: Optional[List[str]] = None,
    triggered_by: Optional[str] = None,
    intent_confidence: Optional[float] = None,
    draft_confidence: Optional[float] = None,
    confidence_source: str = "intent_only",
    review_verdict: Optional[str] = None,
    autonomy_decision: str = "routed_to_action_auto_off",
) -> SaveInquiryResult:
    resolved_guest_thread_id: Optional[str] = None
    try:
        resolved_guest_thread_id = await _resolve_guest_thread_id_for_save(
            db,
            company_id=company_id,
            property_external_id=property_external_id,
            guest_name=guest_name,
            thread_id=thread_id,
            guest_thread_id=guest_thread_id,
        )
        result = await _insert_pre_booking_inquiry(
            db,
            resolved_guest_thread_id=resolved_guest_thread_id,
            draft_id=draft_id,
            thread_id=thread_id,
            message_id=message_id,
            company_id=company_id,
            platform=platform,
            guest_name=guest_name,
            message_text=message_text,
            check_in=check_in,
            check_out=check_out,
            guests=guests,
            property_external_id=property_external_id,
            intent=intent,
            confidence=confidence,
            draft_text=draft_text,
            policy_flags=policy_flags,
            policy_warnings=policy_warnings,
            decision=decision,
            blocked_by_gap_topics=blocked_by_gap_topics,
            triggered_by=triggered_by,
            intent_confidence=intent_confidence,
            draft_confidence=draft_confidence,
            confidence_source=confidence_source,
            review_verdict=review_verdict,
            autonomy_decision=autonomy_decision,
        )
        await db.commit()
        inserted = getattr(result, "rowcount", 0) > 0
        return SaveInquiryResult(
            inserted=inserted,
            status="saved" if inserted else "duplicate_skipped",
            guest_thread_id=resolved_guest_thread_id,
        )
    except Exception as exc:
        await db.rollback()
        if not _is_missing_guest_thread_fk(exc):
            logger.warning("[PreBooking] save inquiry failed: %s", exc, exc_info=True)
            return SaveInquiryResult(
                inserted=False,
                status="save_failed",
                guest_thread_id=resolved_guest_thread_id or guest_thread_id,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )

        logger.warning(
            "[PreBooking] guest_thread FK race for draft=%s thread=%s; re-resolving and retrying",
            draft_id,
            thread_id,
        )
        try:
            resolved_guest_thread_id = await _resolve_guest_thread_id_for_save(
                db,
                company_id=company_id,
                property_external_id=property_external_id,
                guest_name=guest_name,
                thread_id=thread_id,
                guest_thread_id=None,
            )
            result = await _insert_pre_booking_inquiry(
                db,
                resolved_guest_thread_id=resolved_guest_thread_id,
                draft_id=draft_id,
                thread_id=thread_id,
                message_id=message_id,
                company_id=company_id,
                platform=platform,
                guest_name=guest_name,
                message_text=message_text,
                check_in=check_in,
                check_out=check_out,
                guests=guests,
                property_external_id=property_external_id,
                intent=intent,
                confidence=confidence,
                draft_text=draft_text,
                policy_flags=policy_flags,
                policy_warnings=policy_warnings,
                decision=decision,
                blocked_by_gap_topics=blocked_by_gap_topics,
                triggered_by=triggered_by,
                intent_confidence=intent_confidence,
                draft_confidence=draft_confidence,
                confidence_source=confidence_source,
                review_verdict=review_verdict,
                autonomy_decision=autonomy_decision,
            )
            await db.commit()
            inserted = getattr(result, "rowcount", 0) > 0
            return SaveInquiryResult(
                inserted=inserted,
                status="saved" if inserted else "duplicate_skipped",
                guest_thread_id=resolved_guest_thread_id,
            )
        except Exception as retry_exc:
            await db.rollback()
            logger.warning(
                "[PreBooking] save inquiry retry failed: %s",
                retry_exc,
                exc_info=True,
            )
            return SaveInquiryResult(
                inserted=False,
                status="save_failed",
                guest_thread_id=resolved_guest_thread_id or guest_thread_id,
                error_type=type(retry_exc).__name__,
                error_message=str(retry_exc),
            )
