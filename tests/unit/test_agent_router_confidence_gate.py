from __future__ import annotations

from types import SimpleNamespace

from app.services.messaging_brain.agents.agent_router import AgentRouter
from app.services.orchestration.messaging_brain_contracts import (
    IntentType,
    MessageClassification,
    Urgency,
)


def _classification(*, topic: str, confidence: float) -> MessageClassification:
    return MessageClassification(
        intent_type=IntentType.QUESTION,
        intent_topic=topic,
        confidence=confidence,
        urgency=Urgency.MEDIUM,
    )


def test_agent_router_routes_low_confidence_to_fallback():
    router = AgentRouter(confidence_threshold=0.30)

    outcome = router.route(_classification(topic="local_recommendation", confidence=0.18))

    assert outcome.agent_names == ["GeneralAgent"]
    assert "low confidence" in outcome.reason


def test_agent_router_preserves_high_confidence_specialist_routing():
    router = AgentRouter(confidence_threshold=0.30)

    outcome = router.route(_classification(topic="booking_inquiry", confidence=0.84))

    assert outcome.agent_names == ["BookingInquiryAgent", "PortfolioMatchingAgent"]
    assert "routed primary='booking_inquiry'" in outcome.reason


def test_agent_router_filters_identity_gated_specialists():
    router = AgentRouter(confidence_threshold=0.30)
    specialists = {
        "LateCheckoutAgent": SimpleNamespace(
            eligible_for_identity=lambda state: state == "identified"
        ),
        "MaintenanceAgent": SimpleNamespace(
            eligible_for_identity=lambda state: state in {"identified", "linked"}
        ),
        "GeneralAgent": SimpleNamespace(eligible_for_identity=lambda state: True),
        "EscalationAgent": SimpleNamespace(eligible_for_identity=lambda state: True),
    }

    late = router.route(
        _classification(topic="late_checkout", confidence=0.91),
        identity_state="pseudonymous",
        specialist_lookup=specialists,
    )
    maintenance = router.route(
        _classification(topic="maintenance", confidence=0.91),
        identity_state="pseudonymous",
        specialist_lookup=specialists,
    )
    linked_maintenance = router.route(
        _classification(topic="maintenance", confidence=0.91),
        identity_state="linked",
        specialist_lookup=specialists,
    )

    assert late.agent_names == ["GeneralAgent"]
    assert "filtered topics" in late.reason
    assert maintenance.agent_names == ["GeneralAgent"]
    assert linked_maintenance.agent_names == ["MaintenanceAgent"]
