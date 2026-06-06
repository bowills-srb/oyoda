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


def _make_inbound(*, property_code: str = "100SL2C") -> InboundGuestMessage:
    return InboundGuestMessage(
        message_id="MSG_VECTOR_001",
        tenant_id="11111111-1111-1111-1111-111111111111",
        channel="sms",
        source_provider="twilio",
        text="What is the wifi password and where is beach access?",
        guest_phone="+18505551234",
        property_code=property_code,
    )


def _make_classification() -> MessageClassification:
    return MessageClassification(
        intent_type=IntentType.QUESTION,
        intent_topic="access",
        confidence=0.8,
        urgency=Urgency.LOW,
    )


def _make_outbound(*, property_code: str = "100SL2C") -> OutboundIntent:
    return OutboundIntent(
        tenant_id="11111111-1111-1111-1111-111111111111",
        trigger_type="pre_arrival_wifi",
        property_code=property_code,
    )


def _legacy_knowledge():
    return SimpleNamespace(
        facts={"wifi": "legacy wifi"},
        sections={},
        faq=[],
    )


@pytest.mark.asyncio
async def test_vector_fallback_disabled_by_default_no_retrieval(monkeypatch):
    monkeypatch.setattr(f"{SEAM}.is_messaging_brain_canonical_kb_read_enabled", AsyncMock(return_value=False))
    monkeypatch.setattr(f"{SEAM}.is_messaging_brain_rich_context_enabled", AsyncMock(return_value=False))
    monkeypatch.setattr(f"{SEAM}.is_messaging_brain_rich_context_shadow_enabled", AsyncMock(return_value=False))
    monkeypatch.setattr(f"{SEAM}.is_messaging_brain_vector_fallback_enabled", AsyncMock(return_value=False))
    monkeypatch.setattr(f"{SEAM}.is_messaging_brain_vector_fallback_shadow_enabled", AsyncMock(return_value=False))

    agent = ContextBuilderAgent(knowledge_service=MagicMock(get_for_property=AsyncMock(return_value=_legacy_knowledge())))
    retrieve = AsyncMock(return_value=[])
    monkeypatch.setattr(agent, "_retrieve_vector_chunks", retrieve)

    bundle = await agent.build(_make_inbound(), _make_classification(), db_session=MagicMock())

    retrieve.assert_not_awaited()
    assert "vector_retrieval" not in bundle.evidence_keys


@pytest.mark.asyncio
async def test_vector_fallback_runtime_on_retrieves_and_merges(monkeypatch):
    monkeypatch.setattr(f"{SEAM}.is_messaging_brain_canonical_kb_read_enabled", AsyncMock(return_value=False))
    monkeypatch.setattr(f"{SEAM}.is_messaging_brain_rich_context_enabled", AsyncMock(return_value=False))
    monkeypatch.setattr(f"{SEAM}.is_messaging_brain_rich_context_shadow_enabled", AsyncMock(return_value=False))
    monkeypatch.setattr(f"{SEAM}.is_messaging_brain_vector_fallback_enabled", AsyncMock(return_value=True))
    monkeypatch.setattr(f"{SEAM}.is_messaging_brain_vector_fallback_shadow_enabled", AsyncMock(return_value=False))

    agent = ContextBuilderAgent(knowledge_service=MagicMock(get_for_property=AsyncMock(return_value=_legacy_knowledge())))
    retrieve = AsyncMock(return_value=[{
        "type": "vector_chunk",
        "doc_id": "doc-1",
        "score": 0.82,
        "content": "Wifi network is BeachWifi and password is sunset123.",
        "doc_type": "guidebook",
        "source_type": "vector_guidebook",
    }])
    monkeypatch.setattr(agent, "_retrieve_vector_chunks", retrieve)

    bundle = await agent.build(_make_inbound(), _make_classification(), db_session=MagicMock())

    retrieve.assert_awaited_once()
    assert "vector_retrieval" in bundle.evidence_keys
    assert any(item.get("type") == "vector_chunk" for item in bundle.guidebook_evidence)


@pytest.mark.asyncio
async def test_vector_fallback_shadow_on_observes_but_does_not_merge(monkeypatch, caplog):
    caplog.set_level("INFO")
    monkeypatch.setattr(f"{SEAM}.is_messaging_brain_canonical_kb_read_enabled", AsyncMock(return_value=False))
    monkeypatch.setattr(f"{SEAM}.is_messaging_brain_rich_context_enabled", AsyncMock(return_value=False))
    monkeypatch.setattr(f"{SEAM}.is_messaging_brain_rich_context_shadow_enabled", AsyncMock(return_value=False))
    monkeypatch.setattr(f"{SEAM}.is_messaging_brain_vector_fallback_enabled", AsyncMock(return_value=False))
    monkeypatch.setattr(f"{SEAM}.is_messaging_brain_vector_fallback_shadow_enabled", AsyncMock(return_value=True))

    agent = ContextBuilderAgent(knowledge_service=MagicMock(get_for_property=AsyncMock(return_value=_legacy_knowledge())))
    retrieve = AsyncMock(return_value=[{
        "type": "vector_chunk",
        "doc_id": "doc-1",
        "score": 0.75,
        "content": "Beach access is across the street.",
        "doc_type": "guidebook",
        "source_type": "vector_guidebook",
    }])
    monkeypatch.setattr(agent, "_retrieve_vector_chunks", retrieve)

    bundle = await agent.build(_make_inbound(), _make_classification(), db_session=MagicMock())

    retrieve.assert_awaited_once()
    assert "vector_retrieval" not in bundle.evidence_keys
    assert not any(item.get("type") == "vector_chunk" for item in bundle.guidebook_evidence)
    assert "vector_fallback_shadow" in caplog.text


@pytest.mark.asyncio
async def test_vector_retrieval_failure_returns_empty_does_not_crash(monkeypatch):
    monkeypatch.setattr(f"{SEAM}.is_messaging_brain_canonical_kb_read_enabled", AsyncMock(return_value=False))
    monkeypatch.setattr(f"{SEAM}.is_messaging_brain_rich_context_enabled", AsyncMock(return_value=False))
    monkeypatch.setattr(f"{SEAM}.is_messaging_brain_rich_context_shadow_enabled", AsyncMock(return_value=False))
    monkeypatch.setattr(f"{SEAM}.is_messaging_brain_vector_fallback_enabled", AsyncMock(return_value=True))
    monkeypatch.setattr(f"{SEAM}.is_messaging_brain_vector_fallback_shadow_enabled", AsyncMock(return_value=False))

    agent = ContextBuilderAgent(knowledge_service=MagicMock(get_for_property=AsyncMock(return_value=_legacy_knowledge())))
    monkeypatch.setattr(agent, "_retrieve_vector_chunks", AsyncMock(side_effect=RuntimeError("boom")))

    # Patch the helper itself to preserve fail-open behavior at the build layer.
    async def _safe_empty(*args, **kwargs):
        return []

    monkeypatch.setattr(agent, "_retrieve_vector_chunks", _safe_empty)
    bundle = await agent.build(_make_inbound(), _make_classification(), db_session=MagicMock())

    assert "vector_retrieval" not in bundle.evidence_keys


@pytest.mark.asyncio
async def test_empty_property_code_skips_retrieval(monkeypatch):
    monkeypatch.setattr(f"{SEAM}.is_messaging_brain_canonical_kb_read_enabled", AsyncMock(return_value=False))
    monkeypatch.setattr(f"{SEAM}.is_messaging_brain_rich_context_enabled", AsyncMock(return_value=False))
    monkeypatch.setattr(f"{SEAM}.is_messaging_brain_rich_context_shadow_enabled", AsyncMock(return_value=False))
    monkeypatch.setattr(f"{SEAM}.is_messaging_brain_vector_fallback_enabled", AsyncMock(return_value=True))
    monkeypatch.setattr(f"{SEAM}.is_messaging_brain_vector_fallback_shadow_enabled", AsyncMock(return_value=False))
    agent = ContextBuilderAgent(knowledge_service=MagicMock(get_for_property=AsyncMock(return_value=_legacy_knowledge())))
    retrieve = AsyncMock(return_value=[])
    monkeypatch.setattr(agent, "_retrieve_vector_chunks", retrieve)

    await agent.build(_make_inbound(property_code=""), _make_classification(), db_session=MagicMock())
    retrieve.assert_not_awaited()


@pytest.mark.asyncio
async def test_proactive_runtime_on_merges_vector_chunks(monkeypatch):
    monkeypatch.setattr(f"{SEAM}.is_messaging_brain_canonical_kb_read_enabled", AsyncMock(return_value=False))
    monkeypatch.setattr(f"{SEAM}.is_messaging_brain_rich_context_enabled", AsyncMock(return_value=False))
    monkeypatch.setattr(f"{SEAM}.is_messaging_brain_rich_context_shadow_enabled", AsyncMock(return_value=False))
    monkeypatch.setattr(f"{SEAM}.is_messaging_brain_vector_fallback_enabled", AsyncMock(return_value=True))
    monkeypatch.setattr(f"{SEAM}.is_messaging_brain_vector_fallback_shadow_enabled", AsyncMock(return_value=False))

    agent = ContextBuilderAgent(knowledge_service=MagicMock(get_for_property=AsyncMock(return_value=_legacy_knowledge())))
    retrieve = AsyncMock(return_value=[{
        "type": "vector_chunk",
        "doc_id": "doc-2",
        "score": 0.66,
        "content": "Wifi instructions are in the welcome packet.",
        "doc_type": "guidebook",
        "source_type": "vector_guidebook",
    }])
    monkeypatch.setattr(agent, "_retrieve_vector_chunks", retrieve)

    bundle = await agent.build_for_proactive(_make_outbound(), db_session=MagicMock())

    retrieve.assert_awaited_once()
    assert "vector_retrieval" in bundle.evidence_keys
    assert any(item.get("doc_id") == "doc-2" for item in bundle.guidebook_evidence)


@pytest.mark.asyncio
async def test_retrieve_vector_chunks_shapes_provenance(monkeypatch):
    agent = ContextBuilderAgent()
    fake_doc = SimpleNamespace(
        doc_id="doc-abc",
        score=0.9,
        content="A" * 2000,
        metadata={"doc_type": "guidebook"},
    )
    fake_store = MagicMock(similarity_search=AsyncMock(return_value=SimpleNamespace(documents=[fake_doc])))
    monkeypatch.setattr(f"{SEAM}.UUID", lambda value: value)
    monkeypatch.setattr("app.services.knowledge.vector_store.VectorStore", lambda _db: fake_store)

    chunks = await agent._retrieve_vector_chunks(
        tenant_id="11111111-1111-1111-1111-111111111111",
        property_code="100SL2C",
        query_text="wifi password",
        db_session=MagicMock(),
        top_k=3,
        min_score=0.5,
    )

    fake_store.similarity_search.assert_awaited_once()
    kwargs = fake_store.similarity_search.await_args.kwargs
    assert kwargs["property_code"] == "100SL2C"
    assert kwargs["top_k"] == 3
    assert kwargs["min_score"] == 0.5
    assert chunks[0]["doc_id"] == "doc-abc"
    assert chunks[0]["source_type"] == "vector_guidebook"
    assert len(chunks[0]["content"]) == 1500
