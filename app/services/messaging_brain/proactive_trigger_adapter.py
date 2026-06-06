from __future__ import annotations

from datetime import date
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.messaging_brain import get_messaging_brain_orchestrator
from app.services.orchestration.messaging_brain_contracts import (
    GuestResponseDraft,
    MessagingLifecycle,
    OutboundIntent,
)


def proactive_touch_to_trigger(touch_type: str, *, lifecycle: MessagingLifecycle) -> str:
    touch = str(touch_type or "").strip().lower()
    if touch in {"pre_arrival_welcome"}:
        return "system_welcome"
    if touch in {"arrival_info", "dinner_planning"}:
        return "system_pre_arrival"
    if touch in {"arrival_day_checkin", "in_stay_checkin", "service_update_reassurance"}:
        return "system_morning_brief"
    if touch in {"checkout_prep"}:
        return "system_checkout_reminder"
    if touch in {"extend_offer"}:
        return "system_extend_stay"
    if lifecycle == MessagingLifecycle.POST_STAY:
        return "system_post_stay"
    if lifecycle == MessagingLifecycle.PRE_ARRIVAL:
        return "system_pre_arrival"
    return "system_morning_brief"


def stage_to_lifecycle(stage: str) -> MessagingLifecycle:
    stage_key = str(stage or "").strip().lower()
    if stage_key == "pre_booking":
        return MessagingLifecycle.PRE_BOOKING
    if stage_key == "booked":
        return MessagingLifecycle.PRE_ARRIVAL
    if stage_key == "post_stay":
        return MessagingLifecycle.POST_STAY
    return MessagingLifecycle.IN_STAY


def stay_phase_to_lifecycle(phase: str) -> MessagingLifecycle:
    phase_key = str(phase or "").strip().lower()
    if phase_key == "pre_arrival":
        return MessagingLifecycle.PRE_ARRIVAL
    if phase_key == "post_stay":
        return MessagingLifecycle.POST_STAY
    return MessagingLifecycle.IN_STAY


def choose_channel(
    *,
    payload_channel: str = "",
    guest_phone: str = "",
    guest_email: str = "",
    property_context: Optional[dict[str, Any]] = None,
    sms_appropriate: bool = True,
) -> str:
    explicit = str(payload_channel or "").strip().lower()
    if explicit:
        return explicit

    context = property_context if isinstance(property_context, dict) else {}
    configured = str(context.get("preferred_proactive_channel") or "").strip().lower()
    if configured:
        return configured
    if sms_appropriate and str(guest_phone or "").strip():
        return "sms"
    if str(guest_email or "").strip():
        return "email"
    return ""


async def _load_property_row(session: AsyncSession, property_id: str) -> dict[str, Any]:
    row = (
        await session.execute(
            text(
                """
                SELECT id::text AS property_id,
                       tenant_id::text AS tenant_id,
                       property_code,
                       COALESCE(property_name, name, property_code) AS property_name
                FROM properties
                WHERE id = CAST(:property_id AS uuid)
                LIMIT 1
                """
            ),
            {"property_id": property_id},
        )
    ).mappings().first()
    return dict(row) if row else {}


async def build_preview_intent(
    *,
    session: AsyncSession,
    property_id: str,
    market_id: str,
    stage: str,
    guest_type: str,
    has_children: bool,
    lead_time_days: Optional[int],
    check_in_date: Optional[date],
    check_out_date: Optional[date],
) -> OutboundIntent:
    prop = await _load_property_row(session, property_id)
    lifecycle = stage_to_lifecycle(stage)
    return OutboundIntent(
        tenant_id=str(prop.get("tenant_id") or ""),
        trigger_type=(
            "system_post_stay"
            if lifecycle == MessagingLifecycle.POST_STAY
            else "system_morning_brief"
            if lifecycle == MessagingLifecycle.IN_STAY
            else "system_welcome"
        ),
        property_id=str(prop.get("property_id") or property_id),
        property_code=str(prop.get("property_code") or ""),
        lifecycle=lifecycle,
        channel_preference="",
        payload={
            "property_name": str(prop.get("property_name") or prop.get("property_code") or "your stay"),
            "market_id": market_id,
            "guest_type": guest_type,
            "has_children": has_children,
            "lead_time_days": lead_time_days,
            "days_until_checkin": lead_time_days,
            "check_in_date": check_in_date.isoformat() if check_in_date else None,
            "check_out_date": check_out_date.isoformat() if check_out_date else None,
        },
    )


async def build_stay_workflow_intent(
    *,
    tenant_id: str,
    row: dict[str, Any],
    workflow: dict[str, Any],
    touch_type: str,
) -> OutboundIntent:
    lifecycle = stay_phase_to_lifecycle(str(row.get("phase") or workflow.get("phase") or ""))
    property_context = row.get("property_context") if isinstance(row.get("property_context"), dict) else {}
    market_brain = (
        (((workflow.get("intelligence_context") or {}) if isinstance(workflow.get("intelligence_context"), dict) else {})
         .get("market_brain"))
        if isinstance(workflow.get("intelligence_context"), dict) else {}
    )
    payload = {
        "touch_type": touch_type,
        "property_name": row.get("property_name"),
        "check_in_date": _iso_date(row.get("check_in")),
        "check_out_date": _iso_date(row.get("check_out")),
        "days_until_checkin": (workflow.get("proactive") or {}).get("days_until_checkin") if isinstance(workflow.get("proactive"), dict) else None,
        "market_brain": market_brain if isinstance(market_brain, dict) else {},
        "service_update_note": (workflow.get("proactive") or {}).get("message") if isinstance(workflow.get("proactive"), dict) and touch_type == "service_update_reassurance" else "",
    }
    return OutboundIntent(
        tenant_id=tenant_id,
        trigger_type=proactive_touch_to_trigger(touch_type, lifecycle=lifecycle),
        guest_id=str(row.get("guest_id") or ""),
        guest_email=str(row.get("guest_email") or ""),
        guest_phone=str(row.get("guest_phone") or ""),
        guest_name=str(row.get("guest_name") or ""),
        reservation_id=str(row.get("reservation_id") or ""),
        property_id=str(row.get("property_id") or "") or None,
        property_code=str(row.get("property_code") or ""),
        session_token=str(row.get("token") or ""),
        lifecycle=lifecycle,
        channel_preference=choose_channel(
            guest_phone=str(row.get("guest_phone") or ""),
            guest_email=str(row.get("guest_email") or ""),
            property_context=property_context,
            sms_appropriate=True,
        ),
        payload=payload,
    )


async def build_sms_proactive_intent(
    *,
    session_row: Any,
    message_type: str,
) -> OutboundIntent:
    lifecycle = stay_phase_to_lifecycle(str(getattr(session_row, "phase", "") or ""))
    touch_type_map = {
        "pre_arrival_3day": "pre_arrival_welcome",
        "pre_arrival_1day": "arrival_info",
        "arrival_day": "arrival_day_checkin",
        "mid_stay": "in_stay_checkin",
        "pre_checkout": "checkout_prep",
        "post_stay": "post_stay_followup",
    }
    touch_type = touch_type_map.get(str(message_type or "").strip().lower(), "pre_arrival_welcome")
    return OutboundIntent(
        tenant_id=str(getattr(session_row, "tenant_id", "") or ""),
        trigger_type=proactive_touch_to_trigger(touch_type, lifecycle=lifecycle),
        guest_email=str(getattr(session_row, "guest_email", "") or ""),
        guest_phone=str(getattr(session_row, "guest_phone", "") or ""),
        guest_name=str(getattr(session_row, "guest_name", "") or ""),
        reservation_id=str(getattr(session_row, "reservation_id", "") or ""),
        property_id=str(getattr(session_row, "property_id", "") or "") or None,
        property_code=str(getattr(session_row, "property_code", "") or ""),
        session_token=str(getattr(session_row, "token", "") or ""),
        lifecycle=lifecycle,
        channel_preference="sms",
        payload={
            "touch_type": touch_type,
            "property_name": getattr(session_row, "property_name", None),
            "check_in_date": _iso_date(getattr(session_row, "check_in", None)),
            "check_out_date": _iso_date(getattr(session_row, "check_out", None)),
        },
    )


async def compose_proactive_draft(
    intent: OutboundIntent,
    *,
    db_session: AsyncSession,
) -> GuestResponseDraft:
    orch = get_messaging_brain_orchestrator()
    return await orch.handle_proactive_trigger(
        intent,
        db_session=db_session,
        shadow_mode=False,
    )


def _iso_date(value: Any) -> Optional[str]:
    if isinstance(value, date):
        return value.isoformat()
    text_value = str(value or "").strip()
    return text_value[:10] or None
