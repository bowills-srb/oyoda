from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from app.services.integrations.email_dispatch import (
    EmailDispatchServices,
    dispatch_confirmed_guest,
)
from app.services.integrations.reservation_aware_routing import MatchedReservation


def _make_services() -> EmailDispatchServices:
    db = SimpleNamespace(
        commit=AsyncMock(),
        rollback=AsyncMock(),
    )
    return EmailDispatchServices(
        company_id=UUID("11111111-1111-1111-1111-111111111111"),
        db=db,
        watched_email="host@example.com",
        operator_name="Beach Habitats",
        infer_property_match_type=lambda parsed, code: "exact",
        load_property_context=AsyncMock(return_value=({"property_name": "100 S Spooky Lane"}, {})),
        store_thread_context=AsyncMock(),
        maybe_record_pre_booking_gap=AsyncMock(),
        save_fallback_pre_booking_inquiry=AsyncMock(return_value=False),
        record_kb_gap=AsyncMock(),
        record_property_binding_gap=AsyncMock(),
        build_reply_sender=lambda: MagicMock(),
        generate_in_stay_reply=AsyncMock(return_value="in-stay reply"),
        load_review_event_policy=AsyncMock(return_value={}),
        find_session_by_reservation_context=AsyncMock(return_value=None),
        create_provisional_session_from_system_event=AsyncMock(return_value=False),
        persist_review_event=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_dispatch_confirmed_guest_records_normalization_and_skips_prebooking(monkeypatch):
    services = _make_services()
    parsed = SimpleNamespace(
        message_id="msg-001",
        gmail_message_id="gmail-msg-001",
        guest_email="christina@example.com",
        property_code="100SL2D",
        lifecycle_stage="pre_booking",
        _reservation_routing_metadata={
            "type": "reservation_routing_metadata",
            "lifecycle_routing_source": "pms_reservation_matched",
            "lifecycle_resolved": "pre_arrival",
        },
    )
    reservation = MatchedReservation(
        reservation_id="res-123",
        guest_name="Christina Moser",
        guest_email="christina@example.com",
        check_in=date.today() + timedelta(days=5),
        check_out=date.today() + timedelta(days=12),
        property_code="100SL2D",
        match_method="email",
    )
    normalization = AsyncMock()
    monkeypatch.setattr(
        "app.services.integrations.email_dispatch.update_normalization_outcome",
        normalization,
    )

    outcome = await dispatch_confirmed_guest(
        services=services,
        parsed=parsed,
        reservation_match=reservation,
    )

    assert outcome == "confirmed_guest_email_received"
    assert parsed.lifecycle_stage == "pre_arrival"
    normalization.assert_awaited_once()
    assert normalization.await_args.kwargs["route_outcome"] == "confirmed_guest_email_received"
    assert normalization.await_args.kwargs["draft_source"] == "reservation_aware_routing"
