from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.concierge.thread_property_inheritance import (
    InheritedPropertyBinding,
    inherit_property_from_thread_context,
)


class _FakeResult:
    def __init__(self, *, rows=None, scalar=None):
        self._rows = rows or []
        self._scalar = scalar

    def fetchall(self):
        return list(self._rows)

    def scalar_one_or_none(self):
        return self._scalar


class _FakeDb:
    def __init__(self, actions):
        self.actions = list(actions)
        self.executed = []

    async def execute(self, statement, params=None):
        self.executed.append((str(statement), params or {}))
        action = self.actions.pop(0)
        if isinstance(action, Exception):
            raise action
        return action


@pytest.mark.asyncio
async def test_inherit_prefers_same_thread_match():
    db = _FakeDb(
        [
            _FakeResult(rows=[("prior-message", "31GARD", "raw_property_mention")]),
            _FakeResult(scalar=1),
        ]
    )

    inherited = await inherit_property_from_thread_context(
        db,
        tenant_id=uuid4(),
        source_thread_id="thread-123",
        current_message_id="message-456",
    )

    assert inherited == InheritedPropertyBinding(
        property_code="31GARD",
        inherited_from_message_id="prior-message",
        inherited_from_match_type="raw_property_mention",
        inheritance_source="same_thread",
    )


@pytest.mark.asyncio
async def test_inherit_falls_back_to_reply_headers_when_thread_has_no_match():
    db = _FakeDb(
        [
            _FakeResult(rows=[]),
            _FakeResult(rows=[("prior-message", "31GARD", "canonical_ref")]),
            _FakeResult(scalar=1),
        ]
    )

    inherited = await inherit_property_from_thread_context(
        db,
        tenant_id=uuid4(),
        source_thread_id="thread-123",
        current_message_id="message-456",
        in_reply_to="<prior@example.com>",
        references=["<older@example.com>", "<prior@example.com>"],
    )

    assert inherited == InheritedPropertyBinding(
        property_code="31GARD",
        inherited_from_message_id="prior-message",
        inherited_from_match_type="canonical_ref",
        inheritance_source="reply_headers",
    )


@pytest.mark.asyncio
async def test_inherit_skips_untrusted_reply_header_match_types():
    db = _FakeDb(
        [
            _FakeResult(rows=[]),
            _FakeResult(rows=[("prior-message", "31GARD", "raw_property_mention")]),
        ]
    )

    inherited = await inherit_property_from_thread_context(
        db,
        tenant_id=uuid4(),
        source_thread_id="thread-123",
        current_message_id="message-456",
        in_reply_to="<prior@example.com>",
    )

    assert inherited is None


@pytest.mark.asyncio
async def test_inherit_returns_none_on_db_failure(caplog):
    db = _FakeDb([RuntimeError("boom")])

    inherited = await inherit_property_from_thread_context(
        db,
        tenant_id=uuid4(),
        source_thread_id="thread-123",
        current_message_id="message-456",
    )

    assert inherited is None
    assert "lookup failed" in caplog.text
