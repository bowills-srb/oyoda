"""
test_late_checkout_agent.py — Ship L verification gates.

Covers:
  * import smoke and package-level export
  * early check-in policy path
  * late checkout review-first fallback path
  * always-DRAFT_ONLY posture
  * default orchestrator registration and routing
"""

from __future__ import annotations

import pytest

from app.services.messaging_brain import GuestMessageBrainOrchestrator
from app.services.messaging_brain.agents.agent_router import AgentRouter
from app.services.messaging_brain.agents.late_checkout_agent import (
    LateCheckoutAgent,
)
from app.services.orchestration.messaging_brain_contracts import (
    GuestContextBundle,
    InboundGuestMessage,
    IntentType,
    MessageClassification,
    MessagingLifecycle,
    RecommendedAction,
    Urgency,
)


def _make_inbound(text: str) -> InboundGuestMessage:
    return InboundGuestMessage(
        message_id="MSG_LATE_CHECKOUT_001",
        tenant_id="11111111-1111-1111-1111-111111111111",
        channel="http",
        source_provider="concierge_api",
        text=text,
        property_id="22222222-2222-2222-2222-222222222222",
        property_code="GULF_VIEW_204",
    )


def _make_classification() -> MessageClassification:
    return MessageClassification(
        intent_type=IntentType.REQUEST,
        intent_topic="late_checkout",
        confidence=0.91,
        urgency=Urgency.MEDIUM,
    )


def _make_context(*, operator_policies=None, property_facts=None, evidence_keys=None) -> GuestContextBundle:
    return GuestContextBundle(
        tenant_id="11111111-1111-1111-1111-111111111111",
        property_id="22222222-2222-2222-2222-222222222222",
        property_code="GULF_VIEW_204",
        lifecycle=MessagingLifecycle.PRE_ARRIVAL,
        operator_policies=operator_policies or {},
        property_facts=property_facts or {},
        evidence_keys=evidence_keys or [],
    )


def test_late_checkout_agent_module_imports_cleanly():
    from app.services.messaging_brain.agents import late_checkout_agent

    assert hasattr(late_checkout_agent, "LateCheckoutAgent")
    agent = late_checkout_agent.LateCheckoutAgent()
    assert agent.name == "LateCheckoutAgent"
    assert agent.handles_topics == ("late_checkout",)


def test_late_checkout_agent_exported_from_packages():
    from app.services.messaging_brain import LateCheckoutAgent as A1
    from app.services.messaging_brain.agents import LateCheckoutAgent as A2

    assert A1 is A2 is LateCheckoutAgent


@pytest.mark.asyncio
async def test_early_checkin_policy_path_uses_operator_policies():
    agent = LateCheckoutAgent()
    decision = await agent.run(
        message=_make_inbound("Can we get an early check-in?"),
        classification=_make_classification(),
        context=_make_context(
            operator_policies={
                "_authored": True,
                "early_checkin_available": True,
                "early_checkin_earliest": "1:00 PM",
                "early_checkin_fee": 50,
                "early_checkin_subject_to_availability": True,
            },
            property_facts={"check_in_time": "4:00 PM"},
            evidence_keys=[
                "operator_policies.early_checkin_available",
                "operator_policies.early_checkin_earliest",
                "operator_policies.early_checkin_fee",
                "operator_policies.early_checkin_subject_to_availability",
                "property_facts.check_in_time",
            ],
        ),
    )

    assert decision.recommended_action == RecommendedAction.DRAFT_ONLY
    assert decision.intent_topic == "late_checkout"
    assert "1:00 PM" in decision.draft_text
    assert "$50" in decision.draft_text
    assert "Standard check-in is 4:00 PM." in decision.draft_text
    assert "arrival_timing_review" in decision.risk_flags
    assert "operator_policies.early_checkin_available" in decision.evidence_used


@pytest.mark.asyncio
async def test_late_checkout_without_policies_stays_review_first():
    agent = LateCheckoutAgent()
    decision = await agent.run(
        message=_make_inbound("Can we get a late checkout?"),
        classification=_make_classification(),
        context=_make_context(
            property_facts={"check_out_time": "11:00 AM"},
            evidence_keys=["property_facts.check_out_time"],
        ),
    )

    assert decision.recommended_action == RecommendedAction.DRAFT_ONLY
    assert decision.intent_topic == "late_checkout"
    assert "check on late checkout availability" in decision.draft_text.lower()
    assert "Standard check-out is 11:00 AM." in decision.draft_text
    assert "arrival_timing_requires_operational_review" in decision.missing_info
    assert "arrival_timing_review" in decision.risk_flags


def test_default_orchestrator_registers_late_checkout_agent():
    orch = GuestMessageBrainOrchestrator()

    assert "LateCheckoutAgent" in orch._specialists
    assert isinstance(orch._specialists["LateCheckoutAgent"], LateCheckoutAgent)


def test_router_maps_late_checkout_to_late_checkout_agent():
    outcome = AgentRouter().route(_make_classification())

    assert outcome.agent_names == ["LateCheckoutAgent"]
