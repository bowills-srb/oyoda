import asyncio
from datetime import date

from app.services.integrations.email_inbound import ParsedEmailMessage
from app.services.integrations.email_pipeline import EmailPipelineServices, process_routed_email
from app.services.integrations.reservation_aware_routing import (
    MatchedReservation,
    ReservationRoutingDecision,
)


def _parsed_email(*, system_generated=False, guest_email="guest@example.com"):
    return ParsedEmailMessage(
        source_provider="gmail",
        source_message_id="msg-1",
        source_thread_id="thread-1",
        gmail_message_id="msg-1",
        gmail_thread_id="thread-1",
        message_id_header="<msg-1@example.com>",
        guest_name="Guest",
        guest_email=guest_email,
        subject="Question",
        body="Can we check in early?",
        latest_guest_message="Can we check in early?",
        platform="vrbo",
        is_inquiry=True,
        property_name="Seabreeze",
        property_code="SB1",
        system_generated=system_generated,
        intake_layer1_decision="admit" if not system_generated else "",
    )


def test_email_pipeline_routes_system_events_to_system_dispatch():
    parsed = _parsed_email(system_generated=True)
    calls = []

    async def _find_active_session(_parsed):
        return None

    async def _evaluate_reservation_routing(_parsed):
        return ReservationRoutingDecision(routing_source="no_match_pre_booking")

    async def _dispatch_system_event(_parsed):
        calls.append("system")
        return "system_event_existing_session"

    async def _dispatch_in_stay(_parsed, _session):
        calls.append("stay")
        return "in_stay"

    async def _dispatch_pre_booking(_parsed):
        calls.append("pre")
        return "pre_booking_new"

    result = asyncio.run(
        process_routed_email(
            parsed,
            services=EmailPipelineServices(
                find_active_session=_find_active_session,
                evaluate_reservation_routing=_evaluate_reservation_routing,
                dispatch_system_event=_dispatch_system_event,
                dispatch_in_stay=_dispatch_in_stay,
                dispatch_confirmed_guest=lambda _parsed, _reservation: None,
                dispatch_pre_booking=_dispatch_pre_booking,
            ),
        )
    )

    assert result == "system_event_existing_session"
    assert calls == ["system"]


def test_email_pipeline_routes_active_sessions_to_in_stay_dispatch():
    parsed = _parsed_email()
    calls = []
    session_row = object()

    async def _find_active_session(_parsed):
        return session_row

    async def _evaluate_reservation_routing(_parsed):
        return ReservationRoutingDecision(routing_source="no_match_pre_booking")

    async def _dispatch_system_event(_parsed):
        calls.append("system")
        return "system"

    async def _dispatch_in_stay(_parsed, passed_session):
        calls.append(("stay", passed_session))
        return "in_stay"

    async def _dispatch_pre_booking(_parsed):
        calls.append("pre")
        return "pre_booking_new"

    result = asyncio.run(
        process_routed_email(
            parsed,
            services=EmailPipelineServices(
                find_active_session=_find_active_session,
                evaluate_reservation_routing=_evaluate_reservation_routing,
                dispatch_system_event=_dispatch_system_event,
                dispatch_in_stay=_dispatch_in_stay,
                dispatch_confirmed_guest=lambda _parsed, _reservation: None,
                dispatch_pre_booking=_dispatch_pre_booking,
            ),
        )
    )

    assert result == "in_stay"
    assert calls == [("stay", session_row)]


def test_email_pipeline_routes_layer1_admit_to_pre_booking_dispatch():
    parsed = _parsed_email()
    calls = []

    async def _find_active_session(_parsed):
        return None

    async def _evaluate_reservation_routing(_parsed):
        return ReservationRoutingDecision(routing_source="no_match_pre_booking")

    async def _dispatch_system_event(_parsed):
        calls.append("system")
        return "system"

    async def _dispatch_in_stay(_parsed, _session):
        calls.append("stay")
        return "in_stay"

    async def _dispatch_pre_booking(_parsed):
        calls.append("pre")
        return "pre_booking_new"

    result = asyncio.run(
        process_routed_email(
            parsed,
            services=EmailPipelineServices(
                find_active_session=_find_active_session,
                evaluate_reservation_routing=_evaluate_reservation_routing,
                dispatch_system_event=_dispatch_system_event,
                dispatch_in_stay=_dispatch_in_stay,
                dispatch_confirmed_guest=lambda _parsed, _reservation: None,
                dispatch_pre_booking=_dispatch_pre_booking,
            ),
        )
    )

    assert result == "pre_booking_new"
    assert calls == ["pre"]


def test_email_pipeline_routes_drop_without_dispatching():
    parsed = _parsed_email()
    parsed.intake_layer1_decision = "drop"
    calls = []

    async def _find_active_session(_parsed):
        return None

    async def _evaluate_reservation_routing(_parsed):
        return ReservationRoutingDecision(routing_source="no_match_pre_booking")

    async def _dispatch_system_event(_parsed):
        calls.append("system")
        return "system"

    async def _dispatch_in_stay(_parsed, _session):
        calls.append("stay")
        return "in_stay"

    async def _dispatch_pre_booking(_parsed):
        calls.append("pre")
        return "pre_booking_new"

    result = asyncio.run(
        process_routed_email(
            parsed,
            services=EmailPipelineServices(
                find_active_session=_find_active_session,
                evaluate_reservation_routing=_evaluate_reservation_routing,
                dispatch_system_event=_dispatch_system_event,
                dispatch_in_stay=_dispatch_in_stay,
                dispatch_confirmed_guest=lambda _parsed, _reservation: None,
                dispatch_pre_booking=_dispatch_pre_booking,
            ),
        )
    )

    assert result == "dropped"
    assert calls == []


def test_email_pipeline_routes_confirmed_guest_before_pre_booking_dispatch():
    parsed = _parsed_email()
    calls = []
    reservation = MatchedReservation(
        reservation_id="res-123",
        guest_name="Guest",
        guest_email="guest@example.com",
        check_in=date(2026, 5, 23),
        check_out=date(2026, 5, 30),
        property_code="SB1",
        match_method="email",
    )

    async def _find_active_session(_parsed):
        return None

    async def _evaluate_reservation_routing(_parsed):
        return ReservationRoutingDecision(
            routing_source="pms_reservation_matched",
            matched_reservation=reservation,
        )

    async def _dispatch_system_event(_parsed):
        calls.append("system")
        return "system"

    async def _dispatch_in_stay(_parsed, _session):
        calls.append("stay")
        return "in_stay"

    async def _dispatch_confirmed_guest(_parsed, matched_reservation):
        calls.append(("confirmed", matched_reservation))
        return "confirmed_guest_email_received"

    async def _dispatch_pre_booking(_parsed):
        calls.append("pre")
        return "pre_booking_new"

    result = asyncio.run(
        process_routed_email(
            parsed,
            services=EmailPipelineServices(
                find_active_session=_find_active_session,
                evaluate_reservation_routing=_evaluate_reservation_routing,
                dispatch_system_event=_dispatch_system_event,
                dispatch_in_stay=_dispatch_in_stay,
                dispatch_confirmed_guest=_dispatch_confirmed_guest,
                dispatch_pre_booking=_dispatch_pre_booking,
            ),
        )
    )

    assert result == "confirmed_guest_email_received"
    assert calls == [("confirmed", reservation)]
    assert parsed._reservation_routing_metadata["lifecycle_routing_source"] == "pms_reservation_matched"


def test_christina_reservation_match_routes_before_pre_booking_classifier():
    parsed = _parsed_email(guest_email="christina@example.com")
    parsed.guest_name = "Christina Moser"
    parsed.property_code = "100SL2D"
    parsed.subject = "Re: Payment due notice for 100 S Spooky Lane Unit 2D"
    parsed.body = (
        "Hello- can you confirm if the unit has the following? "
        "High chair Pack and play Baby gate Beach toys Beach chairs"
    )
    parsed.latest_guest_message = parsed.body
    calls = []
    reservation = MatchedReservation(
        reservation_id="res-christina",
        guest_name="Christina Moser",
        guest_email="christina@example.com",
        check_in=date(2026, 5, 23),
        check_out=date(2026, 5, 30),
        property_code="100SL2D",
        match_method="email",
    )

    async def _find_active_session(_parsed):
        return None

    async def _evaluate_reservation_routing(_parsed):
        return ReservationRoutingDecision(
            routing_source="pms_reservation_matched",
            matched_reservation=reservation,
        )

    async def _dispatch_system_event(_parsed):
        calls.append("system")
        return "system"

    async def _dispatch_in_stay(_parsed, _session):
        calls.append("stay")
        return "in_stay"

    async def _dispatch_confirmed_guest(_parsed, matched_reservation):
        calls.append(("confirmed", matched_reservation.reservation_id))
        return "confirmed_guest_email_received"

    async def _dispatch_pre_booking(_parsed):
        calls.append("pre")
        return "pre_booking_new"

    result = asyncio.run(
        process_routed_email(
            parsed,
            services=EmailPipelineServices(
                find_active_session=_find_active_session,
                evaluate_reservation_routing=_evaluate_reservation_routing,
                dispatch_system_event=_dispatch_system_event,
                dispatch_in_stay=_dispatch_in_stay,
                dispatch_confirmed_guest=_dispatch_confirmed_guest,
                dispatch_pre_booking=_dispatch_pre_booking,
            ),
        )
    )

    assert result == "confirmed_guest_email_received"
    assert calls == [("confirmed", "res-christina")]
