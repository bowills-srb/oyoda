from __future__ import annotations

import pytest

from app.services.messaging_brain.agents.house_rules_agent import HouseRulesAgent
from app.services.orchestration.messaging_brain_contracts import (
    GuestContextBundle,
    InboundGuestMessage,
    IntentType,
    MessageClassification,
    MessagingLifecycle,
    Urgency,
)


@pytest.mark.asyncio
async def test_pet_question_prefers_operator_policies():
    agent = HouseRulesAgent()
    decision = await agent.run(
        message=InboundGuestMessage(
            message_id="msg1",
            tenant_id="11111111-1111-1111-1111-111111111111",
            channel="sms",
            source_provider="twilio",
            text="Are pets allowed?",
            property_code="100SL2C",
        ),
        classification=MessageClassification(
            intent_type=IntentType.QUESTION,
            intent_topic="house_rules",
            confidence=0.8,
            urgency=Urgency.LOW,
        ),
        context=GuestContextBundle(
            tenant_id="11111111-1111-1111-1111-111111111111",
            property_code="100SL2C",
            lifecycle=MessagingLifecycle.IN_STAY,
            property_facts={
                "pet_friendly": True,
            },
            operator_policies={
                "_authored": True,
                "pet_fee": 50.0,
                "pet_policy": "allowed",
            },
            evidence_keys=[
                "property_facts.pet_friendly",
                "operator_policies.pet_fee",
            ],
        ),
    )

    assert "This property allows pets." in decision.draft_text
    assert "property_facts.pet_friendly" in decision.evidence_used
