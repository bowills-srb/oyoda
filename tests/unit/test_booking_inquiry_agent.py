"""
test_booking_inquiry_agent.py — Phase 2 Session 6 verification gates.

Focused tests for BookingInquiryAgent:
  * requested-date handling for availability questions
  * occupancy/group-size handling from provider-normalized context
  * canonical booking-context lookup integration
  * orchestrator default registration
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.messaging_brain.agents.booking_inquiry_agent import (
    BookingInquiryAgent,
)
from app.services.messaging_brain.orchestrator import (
    GuestMessageBrainOrchestrator,
)
from app.services.orchestration.messaging_brain_contracts import (
    GuestContextBundle,
    InboundGuestMessage,
    IntentType,
    MessageClassification,
    RecommendedAction,
    Urgency,
)


def _make_message(text: str = "Is this available for July 10 to July 14?") -> InboundGuestMessage:
    return InboundGuestMessage(
        message_id="booking-msg-001",
        tenant_id="11111111-1111-1111-1111-111111111111",
        channel="email",
        source_provider="gmail",
        text=text,
        property_code="GULF_VIEW_204",
    )


def _make_classification() -> MessageClassification:
    return MessageClassification(
        intent_type=IntentType.QUESTION,
        intent_topic="booking_inquiry",
        confidence=0.8,
        urgency=Urgency.MEDIUM,
    )


def _make_context(
    *,
    reservation_facts: dict | None = None,
    house_rules: dict | None = None,
    evidence_keys: list[str] | None = None,
) -> GuestContextBundle:
    return GuestContextBundle(
        tenant_id="11111111-1111-1111-1111-111111111111",
        property_code="GULF_VIEW_204",
        lifecycle="pre_booking",
        reservation_facts=reservation_facts or {},
        house_rules=house_rules or {},
        evidence_keys=evidence_keys or [],
    )


def test_booking_inquiry_agent_imports_cleanly():
    from app.services.messaging_brain.agents import booking_inquiry_agent

    assert hasattr(booking_inquiry_agent, "BookingInquiryAgent")


@pytest.mark.asyncio
async def test_availability_question_without_dates_requests_dates():
    agent = BookingInquiryAgent()

    decision = await agent.run(
        message=_make_message(),
        classification=_make_classification(),
        context=_make_context(),
        db_session=None,
    )

    assert decision.intent_topic == "booking_inquiry"
    assert decision.recommended_action == RecommendedAction.CLARIFY
    assert "requested_dates" in decision.missing_info
    assert decision.clarification_questions == ["Which dates are you considering?"]
    assert "booking_availability_unverified" in decision.risk_flags
    assert "share the dates" in decision.draft_text.lower()


@pytest.mark.asyncio
async def test_gathering_request_emits_clarify_questions():
    agent = BookingInquiryAgent()
    context = _make_context(
        house_rules={"max_guests": 10},
        evidence_keys=["house_rules.max_guests"],
    )

    decision = await agent.run(
        message=_make_message(
            "We recently eloped and would love to celebrate with our family at the home."
        ),
        classification=_make_classification(),
        context=context,
        db_session=None,
    )

    assert decision.recommended_action == RecommendedAction.CLARIFY
    assert decision.missing_info == ["requested_guests", "event_type"]
    assert len(decision.clarification_questions) == 2
    assert "up to 10 guests" in decision.draft_text.lower()


@pytest.mark.asyncio
async def test_availability_question_with_overlap_returns_review_draft():
    agent = BookingInquiryAgent()
    context = _make_context(
        reservation_facts={
            "requested_check_in": "2026-07-10",
            "requested_check_out": "2026-07-14",
        },
        evidence_keys=[
            "reservation_facts.requested_check_in",
            "reservation_facts.requested_check_out",
        ],
    )

    with patch.object(
        agent,
        "_lookup_booking_context",
        AsyncMock(return_value={
            "available": True,
            "match_strategy": "property_code+dates",
            "booking": {"status": "confirmed"},
        }),
    ):
        decision = await agent.run(
            message=_make_message(),
            classification=_make_classification(),
            context=context,
            db_session=MagicMock(),
        )

    assert decision.confidence == pytest.approx(0.85)
    assert "property_code+dates" in decision.answer_summary
    assert "confirmed stay overlapping" in decision.draft_text.lower()
    assert decision.evidence_used == [
        "reservation_facts.requested_check_in",
        "reservation_facts.requested_check_out",
    ]


@pytest.mark.asyncio
async def test_availability_question_without_overlap_stays_conservative():
    agent = BookingInquiryAgent()
    context = _make_context(
        reservation_facts={
            "requested_check_in": "2026-07-10",
            "requested_check_out": "2026-07-14",
        },
        evidence_keys=[
            "reservation_facts.requested_check_in",
            "reservation_facts.requested_check_out",
        ],
    )

    with patch.object(
        agent,
        "_lookup_booking_context",
        AsyncMock(return_value={
            "available": False,
            "match_strategy": "property_code+dates",
        }),
    ):
        decision = await agent.run(
            message=_make_message(),
            classification=_make_classification(),
            context=context,
            db_session=MagicMock(),
        )

    assert decision.confidence == pytest.approx(0.68)
    assert "look promising" in decision.draft_text.lower()
    assert "final_availability_confirmation" in decision.missing_info


@pytest.mark.asyncio
async def test_group_size_without_max_guests_holds_for_review():
    agent = BookingInquiryAgent()
    message = _make_message("Can it fit 9 people?")
    context = _make_context(
        reservation_facts={"requested_guests": 9},
        evidence_keys=["reservation_facts.requested_guests"],
    )

    with patch.object(agent, "_lookup_booking_context", AsyncMock(return_value=None)):
        decision = await agent.run(
            message=message,
            classification=_make_classification(),
            context=context,
            db_session=MagicMock(),
        )

    assert "max_guests" in decision.missing_info
    assert "booking_group_size_review" in decision.risk_flags


@pytest.mark.asyncio
async def test_group_size_without_requested_guest_count_prompts_for_count():
    agent = BookingInquiryAgent()
    message = _make_message("How many guests can stay?")
    context = _make_context(
        house_rules={"max_guests": 8},
        evidence_keys=["house_rules.max_guests"],
    )

    decision = await agent.run(
        message=message,
        classification=_make_classification(),
        context=context,
        db_session=None,
    )

    assert decision.confidence == pytest.approx(0.68)
    assert "requested_guests" in decision.missing_info
    assert "up to 8 guests" in decision.draft_text.lower()


@pytest.mark.asyncio
async def test_group_size_over_limit_calls_out_limit():
    agent = BookingInquiryAgent()
    message = _make_message("Can it fit 10 people?")
    context = _make_context(
        reservation_facts={"requested_guests": 10},
        house_rules={"max_guests": 8},
        evidence_keys=[
            "reservation_facts.requested_guests",
            "house_rules.max_guests",
        ],
    )

    decision = await agent.run(
        message=message,
        classification=_make_classification(),
        context=context,
        db_session=None,
    )

    assert decision.confidence == pytest.approx(0.85)
    assert "exceed max occupancy" in decision.answer_summary
    assert "above the usual limit" in decision.draft_text.lower()


@pytest.mark.asyncio
async def test_group_size_within_limit_answers_conservatively():
    agent = BookingInquiryAgent()
    message = _make_message("Can it fit 6 people?")
    context = _make_context(
        reservation_facts={"requested_guests": 6},
        house_rules={"max_guests": 8},
        evidence_keys=[
            "reservation_facts.requested_guests",
            "house_rules.max_guests",
        ],
    )

    decision = await agent.run(
        message=message,
        classification=_make_classification(),
        context=context,
        db_session=None,
    )

    assert decision.confidence == pytest.approx(0.85)
    assert "should fit well" in decision.draft_text.lower()
    assert decision.evidence_used == [
        "house_rules.max_guests",
        "reservation_facts.requested_guests",
    ]


@pytest.mark.asyncio
async def test_group_size_falls_back_to_bedroom_heuristic_from_lookup():
    agent = BookingInquiryAgent()
    message = _make_message("Can it fit 5 people?")
    context = _make_context(
        reservation_facts={"requested_guests": 5},
        evidence_keys=["reservation_facts.requested_guests"],
    )

    with patch.object(
        agent,
        "_lookup_booking_context",
        AsyncMock(return_value={"property": {"bedrooms": 3}}),
    ):
        decision = await agent.run(
            message=message,
            classification=_make_classification(),
            context=context,
            db_session=MagicMock(),
        )

    assert "should fit well" in decision.draft_text.lower()


def test_default_orchestrator_has_booking_inquiry_registered():
    orch = GuestMessageBrainOrchestrator()
    assert "BookingInquiryAgent" in orch._specialists
