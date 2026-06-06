from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from app.services.concierge.knowledge_gap_recorder import (
    record_gap_async,
    schedule_gap_record,
)


@pytest.mark.asyncio
async def test_record_gap_async_calls_canonical_service_with_translated_fields(monkeypatch):
    session = MagicMock(name="session")
    record_gap_mock = AsyncMock(return_value={"gap_id": "gap-123"})

    @asynccontextmanager
    async def _fake_session():
        yield session

    monkeypatch.setattr(
        "app.core.database.get_db_session",
        _fake_session,
    )
    monkeypatch.setattr(
        "app.services.messaging_brain.knowledge.gap_recorder.record_gap",
        record_gap_mock,
    )

    result = await record_gap_async(
        tenant_id="11111111-1111-1111-1111-111111111111",
        question="What is the pet policy?",
        answer_attempt="I'm checking on that now.",
        confidence_score=0.42,
        property_code="BEACH-1",
        used_kb_chunks=False,
        was_deflected=True,
        detected_intent="house_rules",
        stage="pre_booking",
        channel="email",
        source="messaging_brain_orchestrator",
        metadata={"missing_info": ["pet_policy"]},
    )

    assert result == {"gap_id": "gap-123"}
    record_gap_mock.assert_awaited_once()
    call = record_gap_mock.await_args
    assert call.kwargs["session"] is session
    assert call.kwargs["tenant_id"] == UUID("11111111-1111-1111-1111-111111111111")
    assert call.kwargs["question_text"] == "What is the pet policy?"
    assert call.kwargs["property_external_id"] == "BEACH-1"
    assert call.kwargs["stage"] == "pre_booking"
    assert call.kwargs["channel"] == "email"
    assert call.kwargs["source"] == "messaging_brain_orchestrator"
    assert call.kwargs["detected_intent"] == "house_rules"
    assert call.kwargs["confidence_score"] == 0.42
    assert call.kwargs["metadata"]["answer_attempt"] == "I'm checking on that now."
    assert call.kwargs["metadata"]["used_kb_chunks"] is False
    assert call.kwargs["metadata"]["was_deflected"] is True
    assert call.kwargs["metadata"]["missing_info"] == ["pet_policy"]


@pytest.mark.asyncio
async def test_record_gap_async_returns_none_for_invalid_tenant():
    result = await record_gap_async(
        tenant_id="not-a-uuid",
        question="What is the pet policy?",
        answer_attempt="draft",
        confidence_score=0.1,
        property_code="BEACH-1",
        used_kb_chunks=False,
        was_deflected=True,
    )

    assert result is None


@pytest.mark.asyncio
async def test_record_gap_async_swallows_canonical_service_failure(monkeypatch):
    session = MagicMock(name="session")

    @asynccontextmanager
    async def _fake_session():
        yield session

    monkeypatch.setattr(
        "app.core.database.get_db_session",
        _fake_session,
    )
    monkeypatch.setattr(
        "app.services.messaging_brain.knowledge.gap_recorder.record_gap",
        AsyncMock(side_effect=RuntimeError("db down")),
    )

    result = await record_gap_async(
        tenant_id="11111111-1111-1111-1111-111111111111",
        question="What is the pet policy?",
        answer_attempt="draft",
        confidence_score=0.1,
        property_code="BEACH-1",
        used_kb_chunks=False,
        was_deflected=True,
    )

    assert result is None


def test_schedule_gap_record_swallows_create_task_failure(monkeypatch):
    def _failing_create_task(coro):
        coro.close()
        raise RuntimeError("scheduler down")

    monkeypatch.setattr(
        "app.services.messaging_brain.knowledge.gap_recorder.asyncio.create_task",
        _failing_create_task,
    )

    schedule_gap_record(
        tenant_id="11111111-1111-1111-1111-111111111111",
        question="What is the pet policy?",
        answer_attempt="draft",
        confidence_score=0.1,
        property_code="BEACH-1",
        used_kb_chunks=False,
        was_deflected=True,
    )
