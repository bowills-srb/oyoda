from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.messaging_brain.agents.context_builder_agent import ContextBuilderAgent
from app.services.orchestration.messaging_brain_contracts import (
    InboundGuestMessage,
    IntentType,
    MessageClassification,
    OutboundIntent,
    Urgency,
)


SEAM = "app.services.messaging_brain.agents.context_builder_agent"


def _make_inbound(*, text: str, property_code: str = "100SL2C") -> InboundGuestMessage:
    return InboundGuestMessage(
        message_id="MSG_LAZY_001",
        tenant_id="11111111-1111-1111-1111-111111111111",
        channel="sms",
        source_provider="twilio",
        text=text,
        guest_phone="+18505551234",
        property_code=property_code,
    )


def _make_classification(*, topic: str = "general") -> MessageClassification:
    return MessageClassification(
        intent_type=IntentType.QUESTION,
        intent_topic=topic,
        confidence=0.8,
        urgency=Urgency.LOW,
    )


def _make_outbound(*, trigger_type: str) -> OutboundIntent:
    return OutboundIntent(
        tenant_id="11111111-1111-1111-1111-111111111111",
        trigger_type=trigger_type,
        property_code="100SL2C",
    )


def _legacy_knowledge():
    return SimpleNamespace(
        facts={"wifi": "legacy wifi"},
        sections={},
        faq=[],
    )


@pytest.mark.asyncio
async def test_lazy_context_stage_skips_rich_and_vector_for_generic_inbound(monkeypatch):
    monkeypatch.setattr(f"{SEAM}.is_messaging_brain_canonical_kb_read_enabled", AsyncMock(return_value=False))
    monkeypatch.setattr(f"{SEAM}.is_messaging_brain_lazy_context_stage_enabled", AsyncMock(return_value=True))
    monkeypatch.setattr(f"{SEAM}.is_messaging_brain_vector_fallback_enabled", AsyncMock(return_value=True))
    monkeypatch.setattr(f"{SEAM}.is_messaging_brain_vector_fallback_shadow_enabled", AsyncMock(return_value=False))
    monkeypatch.setattr(f"{SEAM}.load_operator_guidance", AsyncMock(return_value=""))

    agent = ContextBuilderAgent(knowledge_service=MagicMock(get_for_property=AsyncMock(return_value=_legacy_knowledge())))
    load_rich = AsyncMock(return_value=({}, [], ""))
    retrieve = AsyncMock(return_value=[])
    monkeypatch.setattr(agent, "_load_rich_context", load_rich)
    monkeypatch.setattr(agent, "_retrieve_vector_chunks", retrieve)

    bundle = await agent.build(
        _make_inbound(text="Thanks again for everything."),
        _make_classification(topic="general"),
        db_session=MagicMock(),
    )

    load_rich.assert_not_awaited()
    retrieve.assert_not_awaited()
    assert "guidebook_richness" not in bundle.evidence_keys
    assert "vector_retrieval" not in bundle.evidence_keys


@pytest.mark.asyncio
async def test_lazy_context_stage_keeps_rich_context_for_property_fact_questions(monkeypatch):
    monkeypatch.setattr(f"{SEAM}.is_messaging_brain_canonical_kb_read_enabled", AsyncMock(return_value=False))
    monkeypatch.setattr(f"{SEAM}.is_messaging_brain_lazy_context_stage_enabled", AsyncMock(return_value=True))
    monkeypatch.setattr(f"{SEAM}.is_messaging_brain_vector_fallback_enabled", AsyncMock(return_value=True))
    monkeypatch.setattr(f"{SEAM}.is_messaging_brain_vector_fallback_shadow_enabled", AsyncMock(return_value=False))
    monkeypatch.setattr(f"{SEAM}.load_operator_guidance", AsyncMock(return_value=""))

    agent = ContextBuilderAgent(knowledge_service=MagicMock(get_for_property=AsyncMock(return_value=_legacy_knowledge())))
    load_rich = AsyncMock(return_value=({"score": 0.5}, [], ""))
    retrieve = AsyncMock(return_value=[])
    monkeypatch.setattr(agent, "_load_rich_context", load_rich)
    monkeypatch.setattr(agent, "_retrieve_vector_chunks", retrieve)

    bundle = await agent.build(
        _make_inbound(text="What's the wifi password?"),
        _make_classification(topic="access"),
        db_session=MagicMock(),
    )

    load_rich.assert_awaited_once()
    retrieve.assert_not_awaited()
    assert "guidebook_richness" in bundle.evidence_keys


@pytest.mark.asyncio
async def test_lazy_context_stage_keeps_vector_for_local_recommendation_questions(monkeypatch):
    monkeypatch.setattr(f"{SEAM}.is_messaging_brain_canonical_kb_read_enabled", AsyncMock(return_value=False))
    monkeypatch.setattr(f"{SEAM}.is_messaging_brain_lazy_context_stage_enabled", AsyncMock(return_value=True))
    monkeypatch.setattr(f"{SEAM}.is_messaging_brain_vector_fallback_enabled", AsyncMock(return_value=True))
    monkeypatch.setattr(f"{SEAM}.is_messaging_brain_vector_fallback_shadow_enabled", AsyncMock(return_value=False))
    monkeypatch.setattr(f"{SEAM}.load_operator_guidance", AsyncMock(return_value=""))

    agent = ContextBuilderAgent(knowledge_service=MagicMock(get_for_property=AsyncMock(return_value=_legacy_knowledge())))
    load_rich = AsyncMock(return_value=({}, [], ""))
    retrieve = AsyncMock(return_value=[{"type": "vector_chunk", "doc_id": "doc-1", "score": 0.9}])
    monkeypatch.setattr(agent, "_load_rich_context", load_rich)
    monkeypatch.setattr(agent, "_retrieve_vector_chunks", retrieve)

    bundle = await agent.build(
        _make_inbound(text="Any good seafood restaurants nearby?"),
        _make_classification(topic="local_recommendation"),
        db_session=MagicMock(),
    )

    load_rich.assert_awaited_once()
    retrieve.assert_awaited_once()
    assert "vector_retrieval" in bundle.evidence_keys


@pytest.mark.asyncio
async def test_lazy_context_stage_skips_proactive_rich_and_vector_for_generic_trigger(monkeypatch):
    monkeypatch.setattr(f"{SEAM}.is_messaging_brain_canonical_kb_read_enabled", AsyncMock(return_value=False))
    monkeypatch.setattr(f"{SEAM}.is_messaging_brain_lazy_context_stage_enabled", AsyncMock(return_value=True))
    monkeypatch.setattr(f"{SEAM}.is_messaging_brain_vector_fallback_enabled", AsyncMock(return_value=True))
    monkeypatch.setattr(f"{SEAM}.is_messaging_brain_vector_fallback_shadow_enabled", AsyncMock(return_value=False))
    monkeypatch.setattr(f"{SEAM}.load_operator_guidance", AsyncMock(return_value=""))

    agent = ContextBuilderAgent(knowledge_service=MagicMock(get_for_property=AsyncMock(return_value=_legacy_knowledge())))
    load_rich = AsyncMock(return_value=({}, [], ""))
    retrieve = AsyncMock(return_value=[])
    monkeypatch.setattr(agent, "_load_rich_context", load_rich)
    monkeypatch.setattr(agent, "_retrieve_vector_chunks", retrieve)

    await agent.build_for_proactive(
        _make_outbound(trigger_type="post_stay_thanks"),
        db_session=MagicMock(),
    )

    load_rich.assert_not_awaited()
    retrieve.assert_not_awaited()
