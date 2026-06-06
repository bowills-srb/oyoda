"""
test_intake_agent_eq.py — Phase 2 Session 7 verification gates.

Focused tests for the Session 7 EQ enrichment seam:
  * IntakeAgent wires an EQ analyzer into ConciergeRouter
  * EQ-driven crisis routing becomes complaint + requires_human_review
  * EscalationAgent surfaces escalation_emotional_distress on EQ-driven
    complaint paths
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.services.agents.router_agent import Route, RoutingDecision
from app.services.messaging_brain.agents.escalation_agent import (
    EscalationAgent,
)
from app.services.messaging_brain.agents.intake_agent import IntakeAgent
from app.services.orchestration.messaging_brain_contracts import (
    InboundGuestMessage,
    IntentType,
    MessageClassification,
    Urgency,
)


def _make_message(text: str = "I have been waiting forever and still can't get in") -> InboundGuestMessage:
    return InboundGuestMessage(
        message_id="eq-msg-001",
        tenant_id="11111111-1111-1111-1111-111111111111",
        channel="email",
        source_provider="gmail",
        text=text,
        property_code="GULF_VIEW_204",
    )


class _FakeRouter:
    last_instance = None

    def __init__(self, *, context, eq_analyzer, watch, session_id):
        self.context = context
        self.eq_analyzer = eq_analyzer
        self.watch = watch
        self.session_id = session_id
        self.route = AsyncMock(return_value=RoutingDecision(
            route=Route.ESCALATE_EQ,
            reason="EQ-detected crisis — no hard keyword match",
            trigger="eq_crisis",
            metadata={"priority": "high", "emotional_state": "angry"},
        ))
        _FakeRouter.last_instance = self


def test_intake_agent_eq_module_imports_cleanly():
    from app.services.messaging_brain.agents import intake_agent

    assert hasattr(intake_agent, "IntakeAgent")


@pytest.mark.asyncio
async def test_intake_agent_passes_eq_analyzer_to_router():
    fake_eq = object()
    agent = IntakeAgent(eq_analyzer=fake_eq, router_factory=_FakeRouter)

    classification = await agent.classify(_make_message())

    assert _FakeRouter.last_instance is not None
    assert _FakeRouter.last_instance.eq_analyzer is fake_eq
    assert classification.intent_type == IntentType.PROBLEM
    assert classification.intent_topic == "complaint"
    assert classification.urgency == Urgency.HIGH
    assert classification.requires_human_review is True
    assert classification.matched_keyword == "eq_crisis"
    assert classification.matched_route == Route.ESCALATE_EQ.value


@pytest.mark.asyncio
async def test_escalation_agent_adds_emotional_distress_flag_for_eq_crisis():
    agent = EscalationAgent()
    classification = MessageClassification(
        intent_type=IntentType.PROBLEM,
        intent_topic="complaint",
        confidence=0.85,
        urgency=Urgency.HIGH,
        requires_human_review=True,
        matched_keyword="eq_crisis",
        matched_route=Route.ESCALATE_EQ.value,
        reason="EQ-detected crisis — no hard keyword match",
    )

    decision = await agent.run(
        message=_make_message(),
        classification=classification,
        context=None,  # unused by EscalationAgent
        db_session=None,
    )

    assert "escalation_complaint" in decision.risk_flags
    assert "escalation_emotional_distress" in decision.risk_flags
    assert decision.intent_topic == "complaint"
