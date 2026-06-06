from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import logging
from typing import Any, Optional
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.concierge.db_session_service import generate_token
from app.services.concierge.guest_thread_service import get_guest_thread_service
from db.models.concierge_sessions import (
    ConciergeGuestJourneyModel,
    ConciergeGuestSessionModel,
    ConciergeJourneyActivityModel,
    ConciergeMessageModel,
)


logger = logging.getLogger(__name__)


NON_PRE_BOOKING_INTENTS = frozenset({
    "review_response",
})

_JOURNEY_ACTIVITY_TYPES = (
    "beach_chairs",
    "fishing",
    "golf",
    "bikes",
    "pontoon",
    "dolphin",
    "spa",
    "groceries",
    "restaurants",
)


@dataclass(frozen=True)
class GuestSessionRouteResult:
    created: bool
    session_id: Optional[str]
    guest_thread_id: Optional[str]
    status: str


def is_non_pre_booking_intent(intent: Optional[str]) -> bool:
    return str(intent or "").strip().lower() in NON_PRE_BOOKING_INTENTS


def infer_session_dates(
    *,
    requested_check_in: Optional[date],
    requested_check_out: Optional[date],
    received_at: Optional[datetime],
) -> tuple[date, date]:
    if requested_check_in and requested_check_out:
        return requested_check_in, requested_check_out
    if requested_check_in and not requested_check_out:
        return requested_check_in, requested_check_in
    if requested_check_out and not requested_check_in:
        return requested_check_out, requested_check_out
    anchor = (received_at or datetime.now(timezone.utc)).date()
    return anchor, anchor


def _phase_for_dates(check_in: date, check_out: date) -> str:
    today = date.today()
    if check_in > today:
        return "pre_arrival"
    if check_in == today:
        return "arrival_day"
    if check_out > today:
        return "in_stay"
    if check_out == today:
        return "departure_day"
    return "post_stay"


def _split_guest_name(guest_name: Optional[str]) -> tuple[str, str]:
    value = " ".join((guest_name or "").strip().split()) or "Guest"
    parts = value.split(" ", 1)
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[1]


async def _find_existing_session(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    source_message_id: str,
    draft_id: str,
) -> Optional[ConciergeGuestSessionModel]:
    if not source_message_id and not draft_id:
        return None
    result = await db.execute(
        select(ConciergeGuestSessionModel).where(
            ConciergeGuestSessionModel.tenant_id == tenant_id
        ).where(
            text(
                """
                (
                  property_context -> 'migration_source' ->> 'source_message_id' = :source_message_id
                  OR property_context -> 'migration_source' ->> 'draft_id' = :draft_id
                )
                """
            )
        ),
        {
            "source_message_id": source_message_id,
            "draft_id": draft_id,
        },
    )
    return result.scalar_one_or_none()


async def persist_inbound_from_inquiry(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    property_code: str,
    property_name: str,
    guest_name: str,
    guest_email: Optional[str],
    message_text: str,
    intent: str,
    received_at: Optional[datetime],
    requested_check_in: Optional[date],
    requested_check_out: Optional[date],
    requested_guests: Optional[int],
    source_message_id: str,
    inquiry_thread_id: str,
    existing_guest_thread_id: Optional[str],
    source_label: str,
    draft_id: str = "",
    archive_reason: str = "",
    reservation_id: str = "",
) -> GuestSessionRouteResult:
    existing = await _find_existing_session(
        db,
        tenant_id=tenant_id,
        source_message_id=source_message_id,
        draft_id=draft_id,
    )
    if existing:
        return GuestSessionRouteResult(
            created=False,
            session_id=str(existing.session_id),
            guest_thread_id=str(existing.guest_thread_id) if existing.guest_thread_id else None,
            status="already_exists",
        )

    guest_thread_id = existing_guest_thread_id
    if not guest_thread_id:
        guest_thread_id = await get_guest_thread_service().ensure_inquiry_thread(
            db,
            tenant_id=str(tenant_id),
            property_code=property_code or "",
            guest_name=guest_name or "Guest",
            inquiry_thread_id=inquiry_thread_id or "",
        )

    check_in, check_out = infer_session_dates(
        requested_check_in=requested_check_in,
        requested_check_out=requested_check_out,
        received_at=received_at,
    )
    phase = _phase_for_dates(check_in, check_out)
    token = generate_token()
    session_id = uuid4()
    first_name, last_name = _split_guest_name(guest_name)
    property_context = {
        "migration_source": {
            "source": source_label,
            "draft_id": draft_id,
            "source_message_id": source_message_id,
            "archive_reason": archive_reason,
        }
    }

    session = ConciergeGuestSessionModel(
        session_id=session_id,
        guest_thread_id=UUID(str(guest_thread_id)) if guest_thread_id else None,
        tenant_id=tenant_id,
        token=token,
        property_id=None,
        reservation_id=reservation_id or None,
        property_code=property_code or "__unknown__",
        property_name=property_name or property_code or "Unknown property",
        guest_name=f"{first_name} {last_name}".strip() or "Guest",
        guest_phone=None,
        guest_email=guest_email,
        check_in=check_in,
        check_out=check_out,
        num_guests=int(requested_guests or 1),
        status="active",
        phase=phase,
        property_context=property_context,
    )
    db.add(session)

    journey = ConciergeGuestJourneyModel(
        journey_id=uuid4(),
        tenant_id=tenant_id,
        session_id=session_id,
    )
    db.add(journey)

    for activity_type in _JOURNEY_ACTIVITY_TYPES:
        db.add(
            ConciergeJourneyActivityModel(
                activity_id=uuid4(),
                journey_id=journey.journey_id,
                activity_type=activity_type,
                status="not_discussed",
            )
        )

    db.add(
        ConciergeMessageModel(
            message_id=uuid4(),
            session_id=session_id,
            direction="inbound",
            content=message_text or "",
            content_type="text",
            detected_intent=intent,
            was_quick_answer=False,
            response_time_ms=None,
        )
    )

    logger.info(
        "[PostBookingRouting] staged guest-session route source=%s source_message_id=%s draft_id=%s intent=%s property=%s",
        source_label,
        source_message_id,
        draft_id,
        intent,
        property_code,
    )
    return GuestSessionRouteResult(
        created=True,
        session_id=str(session_id),
        guest_thread_id=str(guest_thread_id) if guest_thread_id else None,
        status="created",
    )
