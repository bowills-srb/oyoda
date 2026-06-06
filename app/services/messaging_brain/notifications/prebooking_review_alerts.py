from __future__ import annotations

import logging
from typing import Any, List, Optional
from uuid import UUID


logger = logging.getLogger(__name__)


async def send_prebooking_review_alert(
    company_id: UUID,
    draft_id: str,
    platform: str,
    guest_name: str,
    message: str,
    draft_text: str,
    decision: Any,
    approval_mode: str,
    flags: List[str],
    warnings: List[str],
    property_name: str,
    review_window_hours: int,
    review_verdict: Optional[str] = None,
) -> None:
    try:
        from app.services.messaging.operator_alerts import AlertType, get_alert_router
        from app.services.messaging_brain.persistence.prebooking_inquiry_types import SendDecision

        if approval_mode == "required":
            action_line = (
                "\n\n⚠️ Approval required — this will NOT send automatically.\n"
                "Reply APPROVE to send, EDIT [new text] to modify, or REJECT to skip."
            )
        elif getattr(decision, "value", decision) == SendDecision.REVIEW.value:
            action_line = (
                f"\n\n⏱ Auto-sends in {review_window_hours}h unless you act.\n"
                "Reply APPROVE, EDIT [new text], or REJECT."
            )
        else:
            action_line = "\n\nReply APPROVE, EDIT [new text], or REJECT."

        warning_str = ("\n\n" + "\n".join(warnings)) if warnings else ""
        flag_str = ("\n" + "\n".join(flags)) if flags else ""

        if review_verdict == "hold":
            draft_block = (
                "── AI declined to draft ──\n"
                "The adversarial reviewer held this draft for operator attention. "
                "No automated text is available; please draft a response manually.\n"
                "──────────────────────────"
            )
        else:
            draft_block = (
                "── AI Draft ──\n"
                f"{draft_text}\n"
                "──────────────"
            )

        msg = (
            f"📬 {platform.upper()} Inquiry — {property_name}\n\n"
            f"From: {guest_name}\n"
            f"Message: \"{message[:200]}\"\n\n"
            f"{draft_block}"
            f"{flag_str}"
            f"{warning_str}"
            f"{action_line}\n\n"
            f"ID: {draft_id}"
        )

        router = get_alert_router()
        await router.send_alert(
            company_id=company_id,
            alert_type=AlertType.PRE_BOOKING_INBOUND,
            message=msg,
            alert_id=draft_id,
        )
    except Exception as exc:
        logger.error("[PreBooking] Alert failed: %s", exc)


async def _log_required_mode_event(
    company_id: UUID,
    property_external_id: str,
    draft_id: str,
    db=None,
) -> None:
    try:
        from app.services.events.event_triggers import EventSeverity, EventType, emit_event

        emit_event(
            EventType.DRAFT_GENERATED,
            f"Pre-booking draft {draft_id} held for required approval",
            severity=EventSeverity.LOW,
            tenant_id=company_id,
            data={
                "draft_id": draft_id,
                "property_code": property_external_id,
                "approval_mode": "required",
            },
        )
    except Exception as exc:
        logger.warning(
            "[PreBooking] Required-mode audit log failed for %s: %s",
            draft_id,
            exc,
        )
