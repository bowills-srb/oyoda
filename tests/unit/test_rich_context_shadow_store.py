"""Unit tests for the rich-context shadow writer."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.services.messaging_brain.agents.rich_context_shadow_store import (
    build_exception_entry,
    record_rich_context_shadow_observation,
)


@pytest.mark.asyncio
async def test_writer_swallows_db_errors():
    """Writer must never raise into the caller — guest-path safety."""
    failing_db = AsyncMock()
    failing_db.execute = AsyncMock(side_effect=RuntimeError("db down"))

    await record_rich_context_shadow_observation(
        failing_db,
        tenant_id="tenant-x",
        property_code=None,
        message_id="msg-x",
        intent="general",
        richness_shadow={},
        evidence_shadow=[],
        preferences_block_shadow="",
        shadow_exceptions={},
    )


def test_build_exception_entry_truncates_long_messages():
    long_message = "x" * 1000
    entry = build_exception_entry(ValueError(long_message))
    assert entry["type"] == "ValueError"
    assert len(entry["message"]) == 500


def test_build_exception_entry_captures_type_name():
    entry = build_exception_entry(ConnectionError("svc down"))
    assert entry["type"] == "ConnectionError"
    assert entry["message"] == "svc down"
