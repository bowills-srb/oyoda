from __future__ import annotations

import pytest

from app.services.messaging_brain.agents.context_builder_agent import ContextBuilderAgent
from app.services.orchestration.messaging_brain_contracts import (
    InboundGuestMessage,
    IntentType,
    MessageClassification,
    MessagingLifecycle,
    Urgency,
)


def _message(*, lifecycle: MessagingLifecycle | None):
    return InboundGuestMessage(
        message_id="msg-1",
        tenant_id="11111111-1111-1111-1111-111111111111",
        channel="http",
        source_provider="concierge_api",
        text="Can I check in early?",
        property_code="BEACH-1",
        lifecycle=lifecycle,
    )


def _classification() -> MessageClassification:
    return MessageClassification(
        intent_type=IntentType.QUESTION,
        intent_topic="check_in",
        confidence=0.75,
        urgency=Urgency.MEDIUM,
        reason="test",
    )


@pytest.mark.asyncio
async def test_context_builder_uses_explicit_message_lifecycle_when_present():
    agent = ContextBuilderAgent()

    bundle = await agent.build(
        _message(lifecycle=MessagingLifecycle.POST_STAY),
        _classification(),
        db_session=None,
    )

    assert bundle.lifecycle == MessagingLifecycle.POST_STAY


@pytest.mark.asyncio
async def test_context_builder_falls_back_to_inference_when_lifecycle_absent():
    agent = ContextBuilderAgent()

    bundle = await agent.build(
        _message(lifecycle=None),
        _classification(),
        db_session=None,
    )

    assert bundle.lifecycle == MessagingLifecycle.IN_STAY
