from __future__ import annotations

import pytest

from app.services.messaging_brain.agents.house_rules_agent import HouseRulesAgent
from app.services.messaging_brain.policy.platform_compliance import (
    SERVICE_ANIMAL_ACCOMMODATION_RESPONSE,
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


def _message(text: str) -> InboundGuestMessage:
    return InboundGuestMessage(
        message_id="msg-pets",
        tenant_id="11111111-1111-1111-1111-111111111111",
        channel="sms",
        source_provider="twilio",
        text=text,
        property_code="100SL2C",
    )


def _classification() -> MessageClassification:
    return MessageClassification(
        intent_type=IntentType.QUESTION,
        intent_topic="house_rules",
        confidence=0.8,
        urgency=Urgency.LOW,
    )


def _context(**kwargs) -> GuestContextBundle:
    base = dict(
        tenant_id="11111111-1111-1111-1111-111111111111",
        property_code="100SL2C",
        lifecycle=MessagingLifecycle.IN_STAY,
        property_facts={},
        operator_policies={},
        evidence_keys=[],
    )
    base.update(kwargs)
    return GuestContextBundle(**base)


@pytest.mark.asyncio
async def test_property_pet_friendly_false_declines_cleanly():
    decision = await HouseRulesAgent().run(
        message=_message("Are dogs allowed?"),
        classification=_classification(),
        context=_context(
            property_facts={"pet_friendly": False},
            evidence_keys=["property_facts.pet_friendly"],
        ),
    )

    assert "does not allow pets" in decision.draft_text
    assert decision.recommended_action == RecommendedAction.DRAFT_ONLY


@pytest.mark.asyncio
async def test_property_pet_friendly_true_uses_operator_fees_and_prompts_for_details():
    decision = await HouseRulesAgent().run(
        message=_message("Can we bring our dog?"),
        classification=_classification(),
        context=_context(
            property_facts={"pet_friendly": True},
            operator_policies={
                "_authored": True,
                "pet_fee": 50.0,
                "pet_max_weight": 35,
                "pet_notes": "One dog max.",
            },
            evidence_keys=[
                "property_facts.pet_friendly",
                "operator_policies.pet_fee",
                "operator_policies.pet_max_weight",
                "operator_policies.pet_notes",
            ],
        ),
    )

    assert "This property allows pets." in decision.draft_text
    assert "$50" in decision.draft_text
    assert "35 lbs" in decision.draft_text
    assert "breed, weight, and number" in decision.draft_text
    assert decision.recommended_action == RecommendedAction.DRAFT_ONLY


@pytest.mark.asyncio
async def test_property_pet_friendly_unknown_defers():
    decision = await HouseRulesAgent().run(
        message=_message("Can we bring our cat?"),
        classification=_classification(),
        context=_context(),
    )

    assert decision.missing_info == ["property_facts.pet_friendly"]
    assert decision.recommended_action == RecommendedAction.DRAFT_ONLY


@pytest.mark.asyncio
async def test_service_animal_request_bypasses_property_decline():
    decision = await HouseRulesAgent().run(
        message=_message("I am traveling with a service animal."),
        classification=_classification(),
        context=_context(
            property_facts={"pet_friendly": False},
            evidence_keys=["platform_compliance.service_animal", "property_facts.pet_friendly"],
        ),
    )

    assert decision.draft_text == SERVICE_ANIMAL_ACCOMMODATION_RESPONSE
    assert decision.evidence_used == ["platform_compliance.service_animal"]


@pytest.mark.asyncio
async def test_esa_request_escalates():
    decision = await HouseRulesAgent().run(
        message=_message("We have an emotional support animal."),
        classification=_classification(),
        context=_context(evidence_keys=["platform_compliance.esa"]),
    )

    assert decision.recommended_action == RecommendedAction.ESCALATE
    assert "case-by-case" in decision.draft_text
