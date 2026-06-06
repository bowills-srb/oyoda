"""Step 3: tests for ContextBuilderAgent._load_rich_context."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


_FLAG_PATH = (
    "app.services.messaging_brain.agents.context_builder_agent."
    "is_messaging_brain_rich_context_enabled"
)
_RICHNESS_PATH = (
    "app.services.messaging_brain.agents.context_builder_agent."
    "assess_prebooking_knowledge_richness"
)
_EVIDENCE_PATH = (
    "app.services.messaging_brain.agents.context_builder_agent."
    "retrieve_prebooking_property_evidence"
)
_PREFERENCE_PATH = (
    "app.services.messaging_brain.agents.context_builder_agent."
    "build_preference_context"
)


def _make_agent():
    from app.services.messaging_brain.agents.context_builder_agent import (
        ContextBuilderAgent,
    )

    return ContextBuilderAgent(knowledge_service=MagicMock())


@pytest.mark.asyncio
async def test_load_rich_context_db_session_none_returns_empty():
    agent = _make_agent()
    with patch(_FLAG_PATH) as mock_flag:
        result = await agent._load_rich_context(
            tenant_id="tenant-1",
            property_code="P1",
            message_text="hi",
            intent="greeting",
            guidebook_knowledge={"facts": {"x": "y"}},
            db_session=None,
        )
    assert result == ({}, [], "")
    mock_flag.assert_not_called()


@pytest.mark.asyncio
async def test_load_rich_context_flag_off_returns_empty():
    agent = _make_agent()
    with patch(_FLAG_PATH, new=AsyncMock(return_value=False)), patch(
        _RICHNESS_PATH
    ) as mock_rich, patch(_EVIDENCE_PATH) as mock_ev, patch(
        _PREFERENCE_PATH
    ) as mock_pref:
        result = await agent._load_rich_context(
            tenant_id="tenant-1",
            property_code="P1",
            message_text="hi",
            intent="greeting",
            guidebook_knowledge={"facts": {"x": "y"}},
            db_session=MagicMock(),
        )
    assert result == ({}, [], "")
    mock_rich.assert_not_called()
    mock_ev.assert_not_called()
    mock_pref.assert_not_called()


@pytest.mark.asyncio
async def test_load_rich_context_flag_check_raises_returns_empty():
    agent = _make_agent()
    with patch(_FLAG_PATH, new=AsyncMock(side_effect=RuntimeError("flag boom"))), patch(
        _RICHNESS_PATH
    ) as mock_rich, patch(_PREFERENCE_PATH) as mock_pref:
        result = await agent._load_rich_context(
            tenant_id="tenant-1",
            property_code="P1",
            message_text="hi",
            intent="greeting",
            guidebook_knowledge={"facts": {"x": "y"}},
            db_session=MagicMock(),
        )
    assert result == ({}, [], "")
    mock_rich.assert_not_called()
    mock_pref.assert_not_called()


@pytest.mark.asyncio
async def test_load_rich_context_flag_on_full_happy_path():
    agent = _make_agent()
    expected_richness = {"score": 0.6, "label": "medium", "summary": "..."}
    expected_evidence = [
        {"source": "facts", "label": "wifi", "text": "abc", "score": 2}
    ]
    expected_preferences = "operator prefers casual tone"

    with patch(_FLAG_PATH, new=AsyncMock(return_value=True)), patch(
        _RICHNESS_PATH, return_value=expected_richness
    ), patch(_EVIDENCE_PATH, return_value=expected_evidence), patch(
        _PREFERENCE_PATH, new=AsyncMock(return_value=expected_preferences)
    ):
        richness, evidence, prefs = await agent._load_rich_context(
            tenant_id="tenant-1",
            property_code="P1",
            message_text="what's the wifi",
            intent="amenities",
            guidebook_knowledge={"facts": {"wifi_password": "abc"}},
            db_session=MagicMock(),
        )

    assert richness == expected_richness
    assert evidence == expected_evidence
    assert prefs == expected_preferences


@pytest.mark.asyncio
async def test_load_rich_context_shared_helper_raises_preferences_still_load():
    agent = _make_agent()
    with patch(_FLAG_PATH, new=AsyncMock(return_value=True)), patch(
        _RICHNESS_PATH, side_effect=RuntimeError("richness boom")
    ), patch(_EVIDENCE_PATH) as mock_ev, patch(
        _PREFERENCE_PATH, new=AsyncMock(return_value="prefs block")
    ):
        richness, evidence, prefs = await agent._load_rich_context(
            tenant_id="tenant-1",
            property_code="P1",
            message_text="hi",
            intent="greeting",
            guidebook_knowledge={"facts": {"x": "y"}},
            db_session=MagicMock(),
        )

    assert richness == {}
    assert evidence == mock_ev.return_value
    assert prefs == "prefs block"
    mock_ev.assert_called_once()


@pytest.mark.asyncio
async def test_load_rich_context_evidence_raises_preferences_still_load():
    agent = _make_agent()
    with patch(_FLAG_PATH, new=AsyncMock(return_value=True)), patch(
        _RICHNESS_PATH, return_value={"score": 0.5, "label": "medium", "summary": "..."}
    ), patch(_EVIDENCE_PATH, side_effect=RuntimeError("evidence boom")), patch(
        _PREFERENCE_PATH, new=AsyncMock(return_value="prefs block")
    ):
        richness, evidence, prefs = await agent._load_rich_context(
            tenant_id="tenant-1",
            property_code="P1",
            message_text="hi",
            intent="greeting",
            guidebook_knowledge={"facts": {"x": "y"}},
            db_session=MagicMock(),
        )

    assert richness == {"score": 0.5, "label": "medium", "summary": "..."}
    assert evidence == []
    assert prefs == "prefs block"


@pytest.mark.asyncio
async def test_load_rich_context_preference_raises_richness_evidence_still_load():
    agent = _make_agent()
    expected_richness = {"score": 0.6, "label": "medium", "summary": "..."}
    expected_evidence = [{"source": "facts", "label": "x", "text": "y", "score": 1}]

    with patch(_FLAG_PATH, new=AsyncMock(return_value=True)), patch(
        _RICHNESS_PATH, return_value=expected_richness
    ), patch(_EVIDENCE_PATH, return_value=expected_evidence), patch(
        _PREFERENCE_PATH, new=AsyncMock(side_effect=RuntimeError("pref boom"))
    ):
        richness, evidence, prefs = await agent._load_rich_context(
            tenant_id="tenant-1",
            property_code="P1",
            message_text="hi",
            intent="greeting",
            guidebook_knowledge={"facts": {"x": "y"}},
            db_session=MagicMock(),
        )

    assert richness == expected_richness
    assert evidence == expected_evidence
    assert prefs == ""


@pytest.mark.asyncio
async def test_load_rich_context_both_subsystems_fail():
    agent = _make_agent()
    with patch(_FLAG_PATH, new=AsyncMock(return_value=True)), patch(
        _RICHNESS_PATH, side_effect=RuntimeError("rich boom")
    ), patch(_PREFERENCE_PATH, new=AsyncMock(side_effect=RuntimeError("pref boom"))):
        result = await agent._load_rich_context(
            tenant_id="tenant-1",
            property_code="P1",
            message_text="hi",
            intent="greeting",
            guidebook_knowledge={"facts": {"x": "y"}},
            db_session=MagicMock(),
        )
    assert result == ({}, [], "")


@pytest.mark.asyncio
async def test_load_rich_context_passes_correct_args_to_preference():
    agent = _make_agent()
    pref_mock = AsyncMock(return_value="block")
    with patch(_FLAG_PATH, new=AsyncMock(return_value=True)), patch(
        _RICHNESS_PATH, return_value={"score": 0.5, "label": "medium", "summary": "x"}
    ), patch(_EVIDENCE_PATH, return_value=[]), patch(_PREFERENCE_PATH, new=pref_mock):
        await agent._load_rich_context(
            tenant_id="tenant-uuid-123",
            property_code="PROP-456",
            message_text="hi",
            intent="amenities",
            guidebook_knowledge={"facts": {"x": "y"}},
            db_session=MagicMock(),
        )

    pref_mock.assert_awaited_once()
    kwargs = pref_mock.await_args.kwargs
    assert kwargs["company_id"] == "tenant-uuid-123"
    assert kwargs["intent"] == "amenities"
    assert kwargs["property_external_id"] == "PROP-456"


@pytest.mark.asyncio
async def test_load_rich_context_proactive_empty_message_evidence_is_empty():
    agent = _make_agent()
    ev_mock = MagicMock(return_value=[])
    with patch(_FLAG_PATH, new=AsyncMock(return_value=True)), patch(
        _RICHNESS_PATH, return_value={"score": 0.5, "label": "medium", "summary": "x"}
    ), patch(_EVIDENCE_PATH, new=ev_mock), patch(
        _PREFERENCE_PATH, new=AsyncMock(return_value="block")
    ):
        _, evidence, _ = await agent._load_rich_context(
            tenant_id="tenant-1",
            property_code="P1",
            message_text="",
            intent="checkin_reminder",
            guidebook_knowledge={"facts": {"x": "y"}},
            db_session=MagicMock(),
        )

    assert evidence == []
    ev_mock.assert_called_once()
    assert ev_mock.call_args.kwargs["message"] == ""
