from __future__ import annotations

import asyncio

from app.services.integrations.email_inbound import ParsedEmailMessage
from app.services.integrations.email_routing import decide_email_route
from app.services.integrations.reservation_aware_routing import (
    MatchedReservation,
    ReservationRoutingDecision,
)
from datetime import date


def _parsed_message(**overrides):
    base = ParsedEmailMessage(
        gmail_message_id="gmail-1",
        gmail_thread_id="thread-1",
        message_id_header="<message-1@example.com>",
        guest_name="Misty",
        guest_email="misty@example.com",
        subject="Question",
        body="Is the beach walkable?",
        platform="vrbo",
        is_inquiry=True,
        property_name="Sun Kissed on Hickory",
        property_code="31Hickor",
        intake_layer1_decision="admit",
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def test_email_route_decision_prefers_system_events():
    async def _fake_find_active_session(parsed):
        return object()

    decision = asyncio.run(
        decide_email_route(
            _parsed_message(system_generated=True),
            find_active_session=_fake_find_active_session,
            evaluate_reservation_routing=None,
        )
    )

    assert decision.route_kind == "system_event"
    assert decision.session_row is None


def test_email_route_decision_uses_active_session_for_in_stay():
    session_row = object()

    async def _fake_find_active_session(parsed):
        return session_row

    decision = asyncio.run(
        decide_email_route(
            _parsed_message(),
            find_active_session=_fake_find_active_session,
            evaluate_reservation_routing=None,
        )
    )

    assert decision.route_kind == "in_stay"
    assert decision.session_row is session_row


def test_email_route_decision_routes_layer1_admit_to_pre_booking():
    async def _fake_find_active_session(parsed):
        return None

    decision = asyncio.run(
        decide_email_route(
            _parsed_message(),
            find_active_session=_fake_find_active_session,
            evaluate_reservation_routing=None,
        )
    )

    assert decision.route_kind == "pre_booking"
    assert decision.session_row is None


def test_email_route_decision_routes_layer1_unclear_to_pre_booking():
    async def _fake_find_active_session(parsed):
        return None

    decision = asyncio.run(
        decide_email_route(
            _parsed_message(intake_layer1_decision="unclear"),
            find_active_session=_fake_find_active_session,
            evaluate_reservation_routing=None,
        )
    )

    assert decision.route_kind == "pre_booking"
    assert decision.session_row is None


def test_email_route_decision_routes_layer1_drop_to_drop():
    async def _fake_find_active_session(parsed):
        return None

    decision = asyncio.run(
        decide_email_route(
            _parsed_message(intake_layer1_decision="drop"),
            find_active_session=_fake_find_active_session,
            evaluate_reservation_routing=None,
        )
    )

    assert decision.route_kind == "drop"
    assert decision.session_row is None


def test_email_route_decision_drops_missing_layer1_decision():
    async def _fake_find_active_session(parsed):
        return None

    decision = asyncio.run(
        decide_email_route(
            _parsed_message(intake_layer1_decision=""),
            find_active_session=_fake_find_active_session,
            evaluate_reservation_routing=None,
        )
    )

    assert decision.route_kind == "drop"
    assert decision.session_row is None


def test_email_route_decision_routes_confirmed_guest_before_pre_booking():
    async def _fake_find_active_session(parsed):
        return None

    reservation = MatchedReservation(
        reservation_id="res-123",
        guest_name="Misty",
        guest_email="misty@example.com",
        check_in=date(2026, 5, 23),
        check_out=date(2026, 5, 30),
        property_code="31Hickor",
        match_method="email",
    )

    async def _evaluate_reservation_routing(parsed):
        return ReservationRoutingDecision(
            routing_source="pms_reservation_matched",
            matched_reservation=reservation,
        )

    decision = asyncio.run(
        decide_email_route(
            _parsed_message(),
            find_active_session=_fake_find_active_session,
            evaluate_reservation_routing=_evaluate_reservation_routing,
        )
    )

    assert decision.route_kind == "confirmed_guest"
    assert decision.reservation_match is reservation
    assert decision.routing_metadata["lifecycle_routing_source"] == "pms_reservation_matched"
