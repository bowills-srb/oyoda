from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.messaging_brain.agents.context_builder_agent import (
    ContextBuilderAgent,
)
from app.services.messaging_brain.orchestrator import (
    GuestMessageBrainOrchestrator,
)
from app.services.orchestration.messaging_brain_contracts import (
    InboundGuestMessage,
    IntentType,
    MessageClassification,
    Urgency,
)


@dataclass
class _LegacyKnowledgeFake:
    property_external_id: Optional[str] = None
    facts: dict = field(default_factory=dict)
    sections: dict = field(default_factory=dict)
    faq: list = field(default_factory=list)


def _make_inbound() -> InboundGuestMessage:
    return InboundGuestMessage(
        message_id="MSG_GUIDANCE_001",
        tenant_id="11111111-1111-1111-1111-111111111111",
        channel="sms",
        source_provider="twilio",
        text="Can we bring our dog?",
        guest_phone="+18505551234",
        property_code="GULF_VIEW_204",
    )


def _make_classification() -> MessageClassification:
    return MessageClassification(
        intent_type=IntentType.QUESTION,
        intent_topic="house_rules",
        confidence=0.8,
        urgency=Urgency.LOW,
    )


def _agent_with_knowledge(knowledge: Optional[_LegacyKnowledgeFake]) -> ContextBuilderAgent:
    fake_service = MagicMock()
    fake_service.get_for_property = AsyncMock(return_value=knowledge)
    return ContextBuilderAgent(knowledge_service=fake_service)


@pytest.mark.asyncio
async def test_context_builder_surfaces_operator_guidance_when_present(monkeypatch):
    async def _fake_load_operator_guidance(_company_id, _db):
        return "Never approve pets without manager confirmation."

    monkeypatch.setattr(
        "app.services.messaging_brain.agents.context_builder_agent.load_operator_guidance",
        _fake_load_operator_guidance,
    )

    agent = _agent_with_knowledge(_LegacyKnowledgeFake())

    bundle = await agent.build(
        _make_inbound(),
        _make_classification(),
        db_session=MagicMock(),
    )

    assert bundle.operator_guidance == "Never approve pets without manager confirmation."
    assert "operator_guidance" in bundle.evidence_keys

    summary = GuestMessageBrainOrchestrator._summarize_context(bundle)
    assert summary["has_operator_guidance"] is True


@pytest.mark.asyncio
async def test_context_builder_omits_operator_guidance_evidence_when_empty(monkeypatch):
    async def _fake_load_operator_guidance(_company_id, _db):
        return ""

    monkeypatch.setattr(
        "app.services.messaging_brain.agents.context_builder_agent.load_operator_guidance",
        _fake_load_operator_guidance,
    )

    agent = _agent_with_knowledge(_LegacyKnowledgeFake())

    bundle = await agent.build(
        _make_inbound(),
        _make_classification(),
        db_session=MagicMock(),
    )

    assert bundle.operator_guidance == ""
    assert "operator_guidance" not in bundle.evidence_keys

    summary = GuestMessageBrainOrchestrator._summarize_context(bundle)
    assert summary["has_operator_guidance"] is False
