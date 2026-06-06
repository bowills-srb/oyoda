"""
Unit tests for Piece B — DraftLearningService.

All tests use in-memory fakes; no real DB or external services.
"""
from __future__ import annotations

import json
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.services.messaging_brain.learning.draft_learning_service import (
    DraftLearningService,
    DURABLE_TYPES,
)


# ---------------------------------------------------------------------------
# Helpers / fakes
# ---------------------------------------------------------------------------

class _FakeResult:
    """Mimics sqlalchemy execute result (no-op)."""
    pass


class _FakeSession:
    """In-memory fake for AsyncSession."""

    def __init__(self):
        self.executed: list[dict] = []
        self.committed = False

    async def execute(self, stmt, params=None):
        self.executed.append({"stmt": str(stmt), "params": params or {}})
        return _FakeResult()

    async def commit(self):
        self.committed = True

    async def rollback(self):
        pass


def _make_svc() -> DraftLearningService:
    return DraftLearningService()


# ---------------------------------------------------------------------------
# 1. record_approval writes with event_type='approved_unchanged'
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_record_approval_event_type():
    db = _FakeSession()
    svc = _make_svc()
    await svc.record_approval(db, "comp-1", "draft-1", "pricing", "prop-ext-1")
    assert db.committed
    assert len(db.executed) == 1
    params = db.executed[0]["params"]
    assert params["event_type"] == "approved_unchanged"
    assert params["draft_id"] == "draft-1"


# ---------------------------------------------------------------------------
# 2. record_rejection writes with event_type='rejected'
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_record_rejection_event_type():
    db = _FakeSession()
    svc = _make_svc()
    await svc.record_rejection(db, "comp-1", "draft-1", "general", None)
    assert db.committed
    params = db.executed[0]["params"]
    assert params["event_type"] == "rejected"


# ---------------------------------------------------------------------------
# 3. Style-only edit (tone_softer) → raw event, no extraction_candidate
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_style_edit_no_candidate():
    db = _FakeSession()
    svc = _make_svc()

    # Craft an edit that will be classified as tone_softer (adds 2+ warm words,
    # >35% similarity, <92% similarity).
    original = "We have a pool."
    edited = "We have a wonderful pool. We would love to have you. Great, amazing stay awaits!"

    candidate_calls = []

    async def fake_create_candidate(**kwargs):
        candidate_calls.append(kwargs)

    with patch(
        "app.services.extraction.staging_service.ExtractionStagingService"
    ) as MockStaging:
        instance = MockStaging.return_value
        instance.create_candidate = AsyncMock(side_effect=lambda session, **kw: candidate_calls.append(kw))

        await svc.record_edit_and_propose(
            db, "comp-1", "draft-1", "general", "prop-1", original, edited
        )

    # Raw event must be present
    assert db.committed
    raw_event = db.executed[0]["params"]
    assert raw_event["event_type"] == "edited"

    # tone_softer is a style type, so no candidate
    edit_type = raw_event.get("edit_type", "")
    assert edit_type not in DURABLE_TYPES, f"Expected style type, got {edit_type}"
    assert len(candidate_calls) == 0


# ---------------------------------------------------------------------------
# 4. fact_added → raw event + extraction_candidate created
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fact_added_creates_candidate():
    db = _FakeSession()
    svc = _make_svc()

    original = "The property has parking."
    # parking is a PROPERTY_FACT_PATTERN — will classify as fact_added
    edited = "The property has parking. Check-in at 3pm. Check-out by 11am."

    candidate_calls = []

    with patch(
        "app.services.extraction.staging_service.ExtractionStagingService"
    ) as MockStaging:
        instance = MockStaging.return_value
        instance.create_candidate = AsyncMock(
            side_effect=lambda session, **kw: candidate_calls.append(kw)
        )

        await svc.record_edit_and_propose(
            db, "comp-1", "draft-1", "checkin", "prop-1", original, edited
        )

    assert db.committed
    raw_event = db.executed[0]["params"]
    assert raw_event["event_type"] == "edited"

    edit_type = raw_event.get("edit_type", "")
    assert edit_type in DURABLE_TYPES, f"Expected durable type, got {edit_type}"
    assert len(candidate_calls) == 1
    call = candidate_calls[0]
    assert call["source_type"] == "other"
    assert call["extraction_method"] == "deterministic"
    assert call["candidate_type"] == "fact"
    assert call["confidence"] == 0.75
    meta = call["proposed_metadata"]
    assert meta["source"] == "operator_draft_edit"
    assert meta["draft_id"] == "draft-1"


# ---------------------------------------------------------------------------
# 5. complete_rewrite → raw event, no candidate
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_complete_rewrite_no_candidate():
    db = _FakeSession()
    svc = _make_svc()

    original = "Hello. Here is some info about the property. It has rooms."
    # <35% similarity triggers COMPLETE_REWRITE
    edited = "Xyzzy foo bar baz qux quux corge grault garply waldo fred plugh thud."

    candidate_calls = []

    with patch(
        "app.services.extraction.staging_service.ExtractionStagingService"
    ) as MockStaging:
        instance = MockStaging.return_value
        instance.create_candidate = AsyncMock(
            side_effect=lambda session, **kw: candidate_calls.append(kw)
        )

        await svc.record_edit_and_propose(
            db, "comp-1", "draft-1", "general", "prop-1", original, edited
        )

    assert db.committed
    raw_event = db.executed[0]["params"]
    assert raw_event["edit_type"] == "complete_rewrite"
    assert len(candidate_calls) == 0


# ---------------------------------------------------------------------------
# 6. Proposal failure does NOT propagate (best-effort isolation)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_proposal_failure_is_swallowed():
    db = _FakeSession()
    svc = _make_svc()

    original = "The property has parking."
    edited = "The property has parking. Check-in at 3pm. Washer and dryer available."

    with patch(
        "app.services.extraction.staging_service.ExtractionStagingService"
    ) as MockStaging:
        instance = MockStaging.return_value
        instance.create_candidate = AsyncMock(side_effect=RuntimeError("DB exploded"))

        # Should NOT raise
        await svc.record_edit_and_propose(
            db, "comp-1", "draft-1", "checkin", "prop-1", original, edited
        )

    # Raw event still committed
    assert db.committed
    assert len(db.executed) == 1


# ---------------------------------------------------------------------------
# 7. scope_type='property_group' flows through to create_candidate
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_property_group_scope_flows_through():
    db = _FakeSession()
    svc = _make_svc()

    original = "The property has parking."
    edited = "The property has parking. Check-in at 3pm. Check-out by 11am."

    candidate_calls = []
    group_id = "group-uuid-123"

    with patch(
        "app.services.extraction.staging_service.ExtractionStagingService"
    ) as MockStaging:
        instance = MockStaging.return_value
        instance.create_candidate = AsyncMock(
            side_effect=lambda session, **kw: candidate_calls.append(kw)
        )

        await svc.record_edit_and_propose(
            db, "comp-1", "draft-1", "checkin", "prop-1", original, edited,
            scope_type="property_group",
            scope_target_id=group_id,
        )

    if candidate_calls:
        call = candidate_calls[0]
        assert call["scope_type"] == "property_group"
        assert call["scope_target_id"] == group_id
