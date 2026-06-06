"""
test_general_agent.py — Ship L verification gates.

Covers:
  * import smoke and package-level export
  * greeting / thanks handling
  * local recommendation fallback
  * event-planning helper reuse via Brain-owned decision path
  * default orchestrator registration and routing
"""

from __future__ import annotations

from datetime import date

import pytest

from app.services.messaging_brain import GuestMessageBrainOrchestrator
from app.services.messaging_brain.agents.agent_router import AgentRouter
from app.services.messaging_brain.agents.general_agent import GeneralAgent
from app.services.orchestration.messaging_brain_contracts import (
    GuestContextBundle,
    InboundGuestMessage,
    IntentType,
    MessageClassification,
    MessagingLifecycle,
    RecommendedAction,
    Urgency,
)


def _make_inbound(text: str, *, check_in: str | None = None, check_out: str | None = None) -> InboundGuestMessage:
    return InboundGuestMessage(
        message_id="MSG_GENERAL_001",
        tenant_id="11111111-1111-1111-1111-111111111111",
        channel="http",
        source_provider="concierge_api",
        text=text,
        property_id="22222222-2222-2222-2222-222222222222",
        property_code="GULF_VIEW_204",
        metadata={
            "check_in_date": check_in,
            "check_out_date": check_out,
        },
    )


def _make_classification(topic: str) -> MessageClassification:
    return MessageClassification(
        intent_type=IntentType.QUESTION,
        intent_topic=topic,
        confidence=0.84,
        urgency=Urgency.LOW,
    )


def _make_context() -> GuestContextBundle:
    return GuestContextBundle(
        tenant_id="11111111-1111-1111-1111-111111111111",
        property_id="22222222-2222-2222-2222-222222222222",
        property_code="GULF_VIEW_204",
        lifecycle=MessagingLifecycle.IN_STAY,
    )


def test_general_agent_module_imports_cleanly():
    from app.services.messaging_brain.agents import general_agent

    assert hasattr(general_agent, "GeneralAgent")
    agent = general_agent.GeneralAgent()
    assert agent.name == "GeneralAgent"
    assert agent.handles_topics == ("general", "local_recommendation")


def test_general_agent_exported_from_packages():
    from app.services.messaging_brain import GeneralAgent as A1
    from app.services.messaging_brain.agents import GeneralAgent as A2

    assert A1 is A2 is GeneralAgent


@pytest.mark.asyncio
async def test_greeting_path_recommends_draft_only():
    agent = GeneralAgent()
    decision = await agent.run(
        message=_make_inbound("Hi there"),
        classification=_make_classification("general"),
        context=_make_context(),
    )

    assert decision.recommended_action == RecommendedAction.DRAFT_ONLY
    assert decision.intent_topic == "general"
    assert "what can i assist you with" in decision.draft_text.lower()


@pytest.mark.asyncio
async def test_thanks_path_recommends_draft_only():
    agent = GeneralAgent()
    decision = await agent.run(
        message=_make_inbound("Thanks so much for the help"),
        classification=_make_classification("general"),
        context=_make_context(),
    )

    assert decision.recommended_action == RecommendedAction.DRAFT_ONLY
    assert "very welcome" in decision.draft_text.lower()


@pytest.mark.asyncio
async def test_thanks_with_substantive_question_does_not_short_circuit_to_signoff():
    agent = GeneralAgent()
    decision = await agent.run(
        message=_make_inbound("Thanks again. Which bedroom are the bunk beds in?"),
        classification=_make_classification("general"),
        context=_make_context(),
    )

    assert decision.recommended_action == RecommendedAction.DRAFT_ONLY
    assert "very welcome" not in decision.draft_text.lower()
    assert "happy to help" not in decision.draft_text.lower()


@pytest.mark.asyncio
async def test_thanks_with_access_question_without_question_mark_does_not_short_circuit():
    agent = GeneralAgent()
    decision = await agent.run(
        message=_make_inbound("Thank you again, how do we get into the house for our stay"),
        classification=_make_classification("general"),
        context=_make_context(),
    )

    assert decision.recommended_action == RecommendedAction.DRAFT_ONLY
    assert "very welcome" not in decision.draft_text.lower()


@pytest.mark.asyncio
async def test_local_recommendation_dining_path_stays_review_first():
    agent = GeneralAgent()
    decision = await agent.run(
        message=_make_inbound("Any good seafood restaurants nearby?"),
        classification=_make_classification("local_recommendation"),
        context=_make_context(),
    )

    assert decision.recommended_action == RecommendedAction.DRAFT_ONLY
    assert decision.intent_topic == "local_recommendation"
    assert "dining ideas" in decision.draft_text.lower()


@pytest.mark.asyncio
async def test_event_questions_reuse_canonical_event_planning_service(monkeypatch):
    agent = GeneralAgent()

    class _FakePlanner:
        async def build_trip_plan(self, **kwargs):
            assert kwargs["check_in_date"] == date(2026, 6, 10)
            assert kwargs["check_out_date"] == date(2026, 6, 15)
            return {"summary": "There’s a food festival during your stay, so dining reservations would help."}

    monkeypatch.setattr(
        "app.services.messaging_brain.agents.general_agent.get_event_planning_service",
        lambda: _FakePlanner(),
    )

    decision = await agent.run(
        message=_make_inbound(
            "Any events happening during our stay?",
            check_in="2026-06-10",
            check_out="2026-06-15",
        ),
        classification=_make_classification("local_recommendation"),
        context=_make_context(),
        db_session=object(),
    )

    assert decision.recommended_action == RecommendedAction.DRAFT_ONLY
    assert decision.intent_topic == "local_recommendation"
    assert "food festival" in decision.draft_text.lower()


def test_default_orchestrator_registers_general_agent():
    orch = GuestMessageBrainOrchestrator()

    assert "GeneralAgent" in orch._specialists
    assert isinstance(orch._specialists["GeneralAgent"], GeneralAgent)


def test_router_maps_general_and_local_recommendation_to_general_agent():
    router = AgentRouter()

    local = router.route(_make_classification("local_recommendation"))
    general = router.route(_make_classification("general"))

    assert local.agent_names == ["GeneralAgent"]
    assert general.agent_names == ["GeneralAgent"]
