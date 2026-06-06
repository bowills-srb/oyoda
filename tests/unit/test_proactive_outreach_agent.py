from __future__ import annotations

import pytest

from app.services.messaging_brain.agents.proactive_outreach_agent import (
    ProactiveOutreachAgent,
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


async def _run_agent(topic: str, *, lifecycle: MessagingLifecycle, payload: dict):
    agent = ProactiveOutreachAgent()
    message = InboundGuestMessage(
        message_id="msg-1",
        tenant_id="tenant-1",
        channel="proactive",
        text=f"[proactive:{topic}]",
        guest_name="Jordan Smith",
        property_code="SEA_LA_VIE",
        lifecycle=lifecycle,
        metadata={"proactive_payload": payload},
    )
    classification = MessageClassification(
        intent_type=IntentType.SYSTEM_EVENT,
        intent_topic=topic,
        confidence=1.0,
        urgency=Urgency.LOW,
        reason="test proactive trigger",
    )
    context = GuestContextBundle(
        tenant_id="tenant-1",
        property_code="SEA_LA_VIE",
        lifecycle=lifecycle,
        property_facts={
            "check_in_time": "4:00 PM",
            "check_out_time": "10:00 AM",
            "wifi": "Beach_5G / Password: surf2024",
        },
        evidence_keys=["property_facts.check_in_time", "property_facts.wifi"],
    )
    return await agent.run(
        message=message,
        classification=classification,
        context=context,
        db_session=None,
    )


@pytest.mark.asyncio
async def test_system_welcome_uses_pre_arrival_context():
    decision = await _run_agent(
        "system_welcome",
        lifecycle=MessagingLifecycle.PRE_ARRIVAL,
        payload={"property_name": "Sea La Vie", "days_until_checkin": 3},
    )
    assert "Sea La Vie" in decision.draft_text
    assert "3 days away from arrival" in decision.draft_text
    assert decision.recommended_action == RecommendedAction.DRAFT_ONLY


@pytest.mark.asyncio
async def test_system_checkout_reminder_mentions_checkout_time():
    decision = await _run_agent(
        "system_checkout_reminder",
        lifecycle=MessagingLifecycle.IN_STAY,
        payload={"property_name": "Sea La Vie"},
    )
    assert "10:00 AM" in decision.draft_text
    assert "late checkout" in decision.draft_text.lower()
