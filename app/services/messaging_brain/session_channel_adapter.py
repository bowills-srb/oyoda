from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging
from typing import Any, Optional
from uuid import uuid4

from app.services.messaging_brain import get_messaging_brain_orchestrator
from app.services.messaging.identity_resolver import resolve_guest_identity
from app.services.orchestration.messaging_brain_contracts import (
    GuestResponseDraft,
    InboundGuestMessage,
    MessagingLifecycle,
    RecommendedAction,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SessionChannelBrainResult:
    draft: GuestResponseDraft
    lifecycle: MessagingLifecycle
    quick_answer_used: bool = False
    quick_answer_source: Optional[str] = None
    should_request_feedback: bool = False

    @property
    def response_text(self) -> str:
        return self.draft.response_text


def phase_to_lifecycle(phase: Optional[str], *, default: MessagingLifecycle) -> MessagingLifecycle:
    phase_value = str(phase or "").strip().lower()
    if phase_value == "pre_arrival":
        return MessagingLifecycle.PRE_ARRIVAL
    if phase_value in {"arrival_day", "in_stay", "departure_day"}:
        return MessagingLifecycle.IN_STAY
    if phase_value == "post_stay":
        return MessagingLifecycle.POST_STAY
    return default


def should_request_feedback(phase: Optional[str]) -> bool:
    return str(phase or "").strip().lower() in {"departure_day", "post_stay"}


def _quick_answer_source_for_draft(draft: GuestResponseDraft) -> Optional[str]:
    source = str(draft.confidence_source or "").strip().lower()
    if source == "gate_code_intercept":
        return "gate_code"
    if source == "escalation_routed":
        return "escalation"
    return None


def build_context_overlay(
    *,
    db_row: Any,
    property_context: dict[str, Any],
) -> dict[str, Any]:
    wifi_network = property_context.get("wifi_network")
    wifi_password = property_context.get("wifi_password")
    wifi_value = ""
    if wifi_network and wifi_password:
        wifi_value = f"{wifi_network} / Password: {wifi_password}"
    elif wifi_network:
        wifi_value = str(wifi_network)
    elif wifi_password:
        wifi_value = f"Password: {wifi_password}"

    check_in_time = property_context.get("check_in_time") or "4:00 PM"
    check_out_time = property_context.get("check_out_time") or "10:00 AM"

    property_facts: dict[str, Any] = {
        "check_in": check_in_time,
        "check_out": check_out_time,
        "check_in_time": check_in_time,
        "check_out_time": check_out_time,
        "pet_friendly": bool(property_context.get("pets_allowed", False)),
    }
    evidence_keys = [
        "property_facts.check_in",
        "property_facts.check_out",
        "property_facts.check_in_time",
        "property_facts.check_out_time",
        "property_facts.pet_friendly",
    ]
    if wifi_value:
        property_facts["wifi"] = wifi_value
        evidence_keys.append("property_facts.wifi")

    reservation_facts: dict[str, Any] = {}
    if getattr(db_row, "check_in", None):
        reservation_facts["check_in_date"] = db_row.check_in.isoformat()
    if getattr(db_row, "check_out", None):
        reservation_facts["check_out_date"] = db_row.check_out.isoformat()

    access_info = {
        "wifi_network": wifi_network,
        "wifi_password": wifi_password,
        "door_code": property_context.get("door_code"),
        "support_phone": property_context.get("support_phone"),
        "check_in_instructions": property_context.get("check_in_instructions"),
    }

    return {
        "property_facts": property_facts,
        "reservation_facts": reservation_facts,
        "access_info": access_info,
        "evidence_keys": evidence_keys,
    }


async def run_session_channel_message(
    *,
    message_text: str,
    db_session: Any,
    db_row: Any,
    session_tenant_id: Any,
    token: str,
    channel: str,
    source_provider: str,
    fallback_support_phone: Optional[str] = None,
    fallback_lifecycle: MessagingLifecycle = MessagingLifecycle.IN_STAY,
    force_lifecycle: Optional[MessagingLifecycle] = None,
    source_message_id: Optional[str] = None,
    source_thread_id: Optional[str] = None,
    raw_subject: str = "",
    received_at: Optional[Any] = None,
    parser_used: str = "",
    parser_confidence: float = 0.0,
    full_thread_text: str = "",
    structured_asks: Optional[list[str]] = None,
) -> SessionChannelBrainResult:
    from app.services.concierge.property_router import get_property_router

    try:
        property_router = get_property_router()
        property_context = await property_router.resolve(
            db=db_session,
            tenant_id=str(session_tenant_id),
            property_code=getattr(db_row, "property_code", "") or "",
            operator_id=str(getattr(db_row, "operator_id", None) or session_tenant_id),
            session_property_context=getattr(db_row, "property_context", None) or {},
        )
        property_dict = property_context.to_dict()

        lifecycle = force_lifecycle or phase_to_lifecycle(
            getattr(db_row, "phase", None),
            default=fallback_lifecycle,
        )
        identity = await resolve_guest_identity(
            db=db_session,
            tenant_id=str(session_tenant_id),
            session_token=token or "",
            guest_email=str(getattr(db_row, "guest_email", "") or ""),
            guest_name=str(getattr(db_row, "guest_name", "") or ""),
            guest_phone=str(getattr(db_row, "guest_phone", "") or ""),
            reservation_id=str(getattr(db_row, "reservation_id", "") or ""),
            property_code=str(getattr(db_row, "property_code", "") or ""),
            requested_check_in=getattr(db_row, "check_in", None),
            requested_check_out=getattr(db_row, "check_out", None),
        )

        inbound = InboundGuestMessage(
            message_id=(source_message_id or f"{source_provider}_{uuid4()}"),
            tenant_id=str(session_tenant_id),
            channel=channel,
            source_provider=source_provider,
            text=message_text,
            full_thread_text=full_thread_text,
            identity=identity,
            guest_email=str(getattr(db_row, "guest_email", "") or ""),
            guest_phone=str(getattr(db_row, "guest_phone", "") or ""),
            guest_name=str(getattr(db_row, "guest_name", "") or ""),
            reservation_id=str(getattr(db_row, "reservation_id", "") or ""),
            property_id=(
                str(getattr(db_row, "property_id"))
                if getattr(db_row, "property_id", None)
                else None
            ),
            property_code=str(getattr(db_row, "property_code", "") or ""),
            lifecycle=lifecycle,
            session_token=token or "",
            thread_id=(source_thread_id or token or ""),
            received_at=received_at if received_at is not None else datetime.utcnow(),
            raw_subject=raw_subject,
            structured_asks=list(structured_asks or []),
            parser_used=parser_used,
            parser_confidence=parser_confidence,
            metadata={
                "check_in_date": (
                    getattr(db_row, "check_in", None).isoformat()
                    if getattr(db_row, "check_in", None)
                    else None
                ),
                "check_out_date": (
                    getattr(db_row, "check_out", None).isoformat()
                    if getattr(db_row, "check_out", None)
                    else None
                ),
                "session_phase": str(getattr(db_row, "phase", "") or ""),
                "session_channel_runtime": "messaging_brain",
                "context_adapter_overlay": build_context_overlay(
                    db_row=db_row,
                    property_context=property_dict,
                ),
            },
        )

        orch = get_messaging_brain_orchestrator()
        draft = await orch.handle_inbound_message(
            inbound,
            db_session=db_session,
            shadow_mode=False,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("[session_channel_adapter] brain routing failed: %s", exc, exc_info=True)
        property_dict = getattr(locals().get("property_context", None), "to_dict", lambda: {})()
        lifecycle = force_lifecycle or phase_to_lifecycle(
            getattr(db_row, "phase", None),
            default=fallback_lifecycle,
        )
        support = fallback_support_phone or property_dict.get("support_phone") or "your host"
        guest_first = (str(getattr(db_row, "guest_name", "") or "").split() or ["Guest"])[0]
        draft = GuestResponseDraft(
            response_text=(
                f"I'm so sorry, {guest_first} — I'm having a technical issue right now. "
                f"For immediate help please call **{support}**."
            ),
            confidence=0.0,
            final_action=RecommendedAction.ESCALATE,
            escalation_required=True,
            reason_for_escalation=f"session channel brain error: {type(exc).__name__}",
        )

    quick_answer_source = _quick_answer_source_for_draft(draft)
    return SessionChannelBrainResult(
        draft=draft,
        lifecycle=lifecycle,
        quick_answer_used=quick_answer_source is not None,
        quick_answer_source=quick_answer_source,
        should_request_feedback=should_request_feedback(getattr(db_row, "phase", None)),
    )
