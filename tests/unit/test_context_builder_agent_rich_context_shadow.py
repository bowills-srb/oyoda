"""Unit tests for ContextBuilderAgent._load_rich_context shadow branching."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.services.messaging_brain.agents.context_builder_agent import (
    ContextBuilderAgent,
)


SEAM = "app.services.messaging_brain.agents.context_builder_agent"


@pytest.fixture
def agent():
    return ContextBuilderAgent()


@pytest.fixture
def base_kwargs():
    return {
        "tenant_id": "tenant-1",
        "property_code": "BH-001",
        "message_text": "Is the pool heated in November?",
        "intent": "amenity_question",
        "guidebook_knowledge": {
            "facts": {"pool_heated": True},
            "sections": {"amenities": "Heated pool, hot tub"},
        },
        "db_session": AsyncMock(),
        "message_id": "msg-abc",
    }


@pytest.mark.asyncio
async def test_db_session_none_returns_empty(agent, base_kwargs):
    base_kwargs["db_session"] = None
    result = await agent._load_rich_context(**base_kwargs)
    assert result == ({}, [], "")


@pytest.mark.asyncio
async def test_flag_off_shadow_off_returns_empty_no_writer(agent, base_kwargs):
    with patch(
        f"{SEAM}.is_messaging_brain_rich_context_enabled",
        AsyncMock(return_value=False),
    ), patch(
        f"{SEAM}.is_messaging_brain_rich_context_shadow_enabled",
        AsyncMock(return_value=False),
    ), patch(
        f"{SEAM}.record_rich_context_shadow_observation",
        AsyncMock(),
    ) as writer:
        result = await agent._load_rich_context(**base_kwargs)
        assert result == ({}, [], "")
        writer.assert_not_called()


@pytest.mark.asyncio
async def test_flag_off_shadow_on_no_message_id_skips_shadow(agent, base_kwargs):
    base_kwargs["message_id"] = None
    shadow_flag = AsyncMock(return_value=True)
    with patch(
        f"{SEAM}.is_messaging_brain_rich_context_enabled",
        AsyncMock(return_value=False),
    ), patch(
        f"{SEAM}.is_messaging_brain_rich_context_shadow_enabled",
        shadow_flag,
    ), patch(
        f"{SEAM}.record_rich_context_shadow_observation",
        AsyncMock(),
    ) as writer:
        result = await agent._load_rich_context(**base_kwargs)
        assert result == ({}, [], "")
        shadow_flag.assert_not_called()
        writer.assert_not_called()


@pytest.mark.asyncio
async def test_flag_off_shadow_on_all_succeed_writes_full_row(agent, base_kwargs):
    sample_richness = {"score": 0.42, "missing": []}
    sample_evidence = [
        {"source": "facts", "label": "pool_heated", "text": "True", "score": 1.0},
    ]
    sample_preferences = "Guest prefers ground-floor units."

    with patch(
        f"{SEAM}.is_messaging_brain_rich_context_enabled",
        AsyncMock(return_value=False),
    ), patch(
        f"{SEAM}.is_messaging_brain_rich_context_shadow_enabled",
        AsyncMock(return_value=True),
    ), patch(
        f"{SEAM}.assess_prebooking_knowledge_richness",
        return_value=sample_richness,
    ), patch(
        f"{SEAM}.retrieve_prebooking_property_evidence",
        return_value=sample_evidence,
    ), patch(
        f"{SEAM}.build_preference_context",
        AsyncMock(return_value=sample_preferences),
    ), patch(
        f"{SEAM}.record_rich_context_shadow_observation",
        AsyncMock(),
    ) as writer:
        result = await agent._load_rich_context(**base_kwargs)
        assert result == ({}, [], "")
        writer.assert_called_once()
        kwargs = writer.call_args.kwargs
        assert kwargs["tenant_id"] == "tenant-1"
        assert kwargs["property_code"] == "BH-001"
        assert kwargs["message_id"] == "msg-abc"
        assert kwargs["intent"] == "amenity_question"
        assert kwargs["richness_shadow"] == sample_richness
        assert kwargs["evidence_shadow"] == sample_evidence
        assert kwargs["preferences_block_shadow"] == sample_preferences
        assert kwargs["shadow_exceptions"] == {}


@pytest.mark.asyncio
async def test_shadow_on_richness_raises_logged_to_exceptions(agent, base_kwargs):
    with patch(
        f"{SEAM}.is_messaging_brain_rich_context_enabled",
        AsyncMock(return_value=False),
    ), patch(
        f"{SEAM}.is_messaging_brain_rich_context_shadow_enabled",
        AsyncMock(return_value=True),
    ), patch(
        f"{SEAM}.assess_prebooking_knowledge_richness",
        side_effect=ValueError("bad threshold"),
    ), patch(
        f"{SEAM}.retrieve_prebooking_property_evidence",
        return_value=[],
    ), patch(
        f"{SEAM}.build_preference_context",
        AsyncMock(return_value=""),
    ), patch(
        f"{SEAM}.record_rich_context_shadow_observation",
        AsyncMock(),
    ) as writer:
        result = await agent._load_rich_context(**base_kwargs)
        assert result == ({}, [], "")
        kwargs = writer.call_args.kwargs
        assert kwargs["richness_shadow"] == {}
        assert kwargs["shadow_exceptions"] == {
            "richness": {"type": "ValueError", "message": "bad threshold"},
        }


@pytest.mark.asyncio
async def test_shadow_on_evidence_raises_logged_to_exceptions(agent, base_kwargs):
    with patch(
        f"{SEAM}.is_messaging_brain_rich_context_enabled",
        AsyncMock(return_value=False),
    ), patch(
        f"{SEAM}.is_messaging_brain_rich_context_shadow_enabled",
        AsyncMock(return_value=True),
    ), patch(
        f"{SEAM}.assess_prebooking_knowledge_richness",
        return_value={"score": 0.5},
    ), patch(
        f"{SEAM}.retrieve_prebooking_property_evidence",
        side_effect=RuntimeError("retrieval blew up"),
    ), patch(
        f"{SEAM}.build_preference_context",
        AsyncMock(return_value=""),
    ), patch(
        f"{SEAM}.record_rich_context_shadow_observation",
        AsyncMock(),
    ) as writer:
        result = await agent._load_rich_context(**base_kwargs)
        assert result == ({}, [], "")
        kwargs = writer.call_args.kwargs
        assert kwargs["richness_shadow"] == {"score": 0.5}
        assert kwargs["evidence_shadow"] == []
        assert kwargs["shadow_exceptions"] == {
            "evidence": {"type": "RuntimeError", "message": "retrieval blew up"},
        }


@pytest.mark.asyncio
async def test_shadow_on_preferences_raises_logged_to_exceptions(agent, base_kwargs):
    with patch(
        f"{SEAM}.is_messaging_brain_rich_context_enabled",
        AsyncMock(return_value=False),
    ), patch(
        f"{SEAM}.is_messaging_brain_rich_context_shadow_enabled",
        AsyncMock(return_value=True),
    ), patch(
        f"{SEAM}.assess_prebooking_knowledge_richness",
        return_value={"score": 0.5},
    ), patch(
        f"{SEAM}.retrieve_prebooking_property_evidence",
        return_value=[],
    ), patch(
        f"{SEAM}.build_preference_context",
        AsyncMock(side_effect=ConnectionError("preference svc down")),
    ), patch(
        f"{SEAM}.record_rich_context_shadow_observation",
        AsyncMock(),
    ) as writer:
        result = await agent._load_rich_context(**base_kwargs)
        assert result == ({}, [], "")
        kwargs = writer.call_args.kwargs
        assert kwargs["preferences_block_shadow"] == ""
        assert kwargs["shadow_exceptions"] == {
            "preferences": {
                "type": "ConnectionError",
                "message": "preference svc down",
            },
        }


@pytest.mark.asyncio
async def test_flag_on_shadow_not_checked_returns_rich_no_writer(agent, base_kwargs):
    sample_richness = {"score": 0.42}
    sample_evidence = [
        {"source": "facts", "label": "x", "text": "y", "score": 1.0},
    ]
    sample_preferences = "prefs"

    shadow_flag = AsyncMock(return_value=True)
    with patch(
        f"{SEAM}.is_messaging_brain_rich_context_enabled",
        AsyncMock(return_value=True),
    ), patch(
        f"{SEAM}.is_messaging_brain_rich_context_shadow_enabled",
        shadow_flag,
    ), patch(
        f"{SEAM}.assess_prebooking_knowledge_richness",
        return_value=sample_richness,
    ), patch(
        f"{SEAM}.retrieve_prebooking_property_evidence",
        return_value=sample_evidence,
    ), patch(
        f"{SEAM}.build_preference_context",
        AsyncMock(return_value=sample_preferences),
    ), patch(
        f"{SEAM}.record_rich_context_shadow_observation",
        AsyncMock(),
    ) as writer:
        result = await agent._load_rich_context(**base_kwargs)
        assert result == (sample_richness, sample_evidence, sample_preferences)
        shadow_flag.assert_not_called()
        writer.assert_not_called()


@pytest.mark.asyncio
async def test_shadow_flag_lookup_raises_behaves_as_off(agent, base_kwargs):
    with patch(
        f"{SEAM}.is_messaging_brain_rich_context_enabled",
        AsyncMock(return_value=False),
    ), patch(
        f"{SEAM}.is_messaging_brain_rich_context_shadow_enabled",
        AsyncMock(side_effect=ConnectionError("flag svc down")),
    ), patch(
        f"{SEAM}.record_rich_context_shadow_observation",
        AsyncMock(),
    ) as writer:
        result = await agent._load_rich_context(**base_kwargs)
        assert result == ({}, [], "")
        writer.assert_not_called()
