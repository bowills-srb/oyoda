"""Gap 4 — proactive group knowledge-gap surfacer tests.

Tests cover:
  1. Registry: expected_at_group_scope field added; new topics present.
  2. Coverage math: expected - present = missing (basic set arithmetic).
  3. Honesty rules:
     - Group with no members → not surfaced.
     - Group with all topics present → not surfaced.
     - Group with members + missing topics → surfaced with correct missing list.
  4. Partial coverage: one topic present, others missing → only missing reported.
  5. Multiple groups: each computed independently.

All tests are in-memory — no DB required. The surfacer's DB calls are patched
via a fake session so we test the logic, not the SQL transport layer.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

import pytest

from app.services.messaging_brain.knowledge.topic_registry import (
    get_group_expected_topics,
    TOPIC_REGISTRY,
)
from app.services.messaging_brain.knowledge.group_gap_surfacer import (
    GroupKnowledgeGap,
    _expected_topic_ids,
    get_group_knowledge_gaps,
)


# ---------------------------------------------------------------------------
# Helpers / fakes
# ---------------------------------------------------------------------------

@dataclass
class _FakeRow:
    """Minimal mapping-like object for SQLAlchemy row fakes."""
    _data: Dict[str, Any]

    def __getitem__(self, key):
        return self._data[key]

    def get(self, key, default=None):
        return self._data.get(key, default)


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return [_FakeRow(r) for r in self._rows]


class _FakeSession:
    """Configurable fake session. Call configure() to set return values."""

    def __init__(self):
        self._calls: List[str] = []
        self._group_rows: List[Dict] = []
        self._knowledge_rows: List[Dict] = []

    def configure(self, *, groups=None, knowledge=None):
        self._group_rows = groups or []
        self._knowledge_rows = knowledge or []

    async def execute(self, stmt, params=None):
        sql = str(stmt).lower()
        self._calls.append(sql[:60])
        if "property_groups" in sql:
            return _FakeResult(self._group_rows)
        if "concierge_scoped_knowledge" in sql:
            return _FakeResult(self._knowledge_rows)
        return _FakeResult([])


# ---------------------------------------------------------------------------
# Registry tests
# ---------------------------------------------------------------------------

def test_expected_at_group_scope_field_exists():
    """KnowledgeTopicDefinition must have the expected_at_group_scope field."""
    from app.services.messaging_brain.knowledge.topic_registry import KnowledgeTopicDefinition
    t = KnowledgeTopicDefinition(topic_id="test", description="test")
    assert hasattr(t, "expected_at_group_scope")
    assert t.expected_at_group_scope is False  # default


def test_new_group_topics_in_registry():
    """The four new group-scope topics must be in TOPIC_REGISTRY."""
    for topic_id in ("hoa_rules", "required_vendors", "gate_code", "community_amenities"):
        assert topic_id in TOPIC_REGISTRY, f"missing topic: {topic_id}"
        assert TOPIC_REGISTRY[topic_id].expected_at_group_scope is True


def test_conservative_existing_topics_marked():
    """parking, quiet_hours, trash_disposal, local_area should be group-expected."""
    for topic_id in ("parking", "quiet_hours", "trash_disposal", "local_area"):
        assert TOPIC_REGISTRY[topic_id].expected_at_group_scope is True, (
            f"{topic_id} should be expected_at_group_scope=True"
        )


def test_property_only_topics_not_marked():
    """Property-only topics (pool_access, check_in_process, etc.) must NOT be marked."""
    property_only = ("pool_access", "check_in_process", "pet_policy", "wifi_access",
                     "sleeping_arrangement", "smoking_policy")
    for topic_id in property_only:
        if topic_id in TOPIC_REGISTRY:
            assert TOPIC_REGISTRY[topic_id].expected_at_group_scope is False, (
                f"{topic_id} should NOT be expected_at_group_scope — "
                "it's a property-level concern"
            )


def test_get_group_expected_topics_returns_only_marked():
    """get_group_expected_topics() must return exactly the topics marked True."""
    expected = get_group_expected_topics()
    assert len(expected) >= 8, "expected at least 4 new + 4 existing marked topics"
    for t in expected:
        assert t.expected_at_group_scope is True
    all_ids = {t.topic_id for t in expected}
    assert "hoa_rules" in all_ids
    assert "required_vendors" in all_ids
    assert "gate_code" in all_ids
    assert "community_amenities" in all_ids
    assert "pool_access" not in all_ids  # property-only


def test_existing_topics_not_broken():
    """The registry extension must not break existing topic lookups."""
    assert "pool_access" in TOPIC_REGISTRY
    assert "check_in_process" in TOPIC_REGISTRY
    assert len(TOPIC_REGISTRY) >= 31  # 27 original + 4 new


# ---------------------------------------------------------------------------
# Coverage math tests (in-memory)
# ---------------------------------------------------------------------------

def test_group_with_no_members_not_surfaced():
    """Honesty rule: groups with no member properties must not appear in gaps."""
    session = _FakeSession()
    # No group rows (JOIN with memberships filters them out)
    session.configure(groups=[], knowledge=[])

    gaps = asyncio.run(get_group_knowledge_gaps(session, uuid4()))
    assert gaps == [], "groups with no members must not be surfaced"


def test_group_with_members_and_no_knowledge_gets_all_missing():
    """A group with members but zero group-scoped entries → all expected topics missing."""
    tid = uuid4()
    gid = uuid4()
    session = _FakeSession()
    session.configure(
        groups=[{
            "group_id": gid,
            "group_name": "WaterSound",
            "group_type": "neighborhood",
            "member_count": 12,
        }],
        knowledge=[],  # nothing written at group scope
    )

    gaps = asyncio.run(get_group_knowledge_gaps(session, tid))
    assert len(gaps) == 1
    gap = gaps[0]
    assert gap.group_name == "WaterSound"
    assert gap.member_count == 12

    expected = _expected_topic_ids()
    assert set(gap.missing_topics) == expected, (
        "all expected topics should be missing when nothing is present"
    )
    assert gap.present_topics == []


def test_group_with_all_topics_covered_not_surfaced():
    """A group with all expected topics covered must not appear in gaps."""
    tid = uuid4()
    gid = uuid4()
    expected = _expected_topic_ids()
    session = _FakeSession()
    session.configure(
        groups=[{
            "group_id": gid,
            "group_name": "FullyCovered",
            "group_type": "neighborhood",
            "member_count": 3,
        }],
        knowledge=[
            {"scope_target_id": gid, "topic_id": tid_str}
            for tid_str in expected
        ],
    )

    gaps = asyncio.run(get_group_knowledge_gaps(session, tid))
    assert gaps == [], "fully-covered group must not appear in gaps"


def test_partial_coverage_reports_only_missing():
    """Group has hoa_rules and quiet_hours; others missing → only others in missing."""
    tid = uuid4()
    gid = uuid4()
    expected = _expected_topic_ids()
    present = {"hoa_rules", "quiet_hours"}
    missing_expected = sorted(expected - present)

    session = _FakeSession()
    session.configure(
        groups=[{
            "group_id": gid,
            "group_name": "PartialGroup",
            "group_type": "hoa",
            "member_count": 5,
        }],
        knowledge=[
            {"scope_target_id": gid, "topic_id": t} for t in present
        ],
    )

    gaps = asyncio.run(get_group_knowledge_gaps(session, tid))
    assert len(gaps) == 1
    gap = gaps[0]
    assert sorted(gap.missing_topics) == missing_expected
    assert sorted(gap.present_topics) == sorted(present)


def test_add_topic_removes_from_missing():
    """After staging a group-scoped hoa_rules entry, hoa_rules drops from missing."""
    tid = uuid4()
    gid = uuid4()

    def _gaps_for(knowledge_topic_ids):
        session = _FakeSession()
        session.configure(
            groups=[{
                "group_id": gid,
                "group_name": "WaterSound",
                "group_type": "neighborhood",
                "member_count": 8,
            }],
            knowledge=[
                {"scope_target_id": gid, "topic_id": t} for t in knowledge_topic_ids
            ],
        )
        return asyncio.run(get_group_knowledge_gaps(session, tid))

    # Before: no hoa_rules
    gaps_before = _gaps_for([])
    assert len(gaps_before) == 1
    assert "hoa_rules" in gaps_before[0].missing_topics

    # After: hoa_rules added
    gaps_after = _gaps_for(["hoa_rules"])
    assert len(gaps_after) == 1
    assert "hoa_rules" not in gaps_after[0].missing_topics
    assert "hoa_rules" in gaps_after[0].present_topics


def test_multiple_groups_computed_independently():
    """Each group's gaps are computed independently; one covered group doesn't help another."""
    tid = uuid4()
    gid1, gid2 = uuid4(), uuid4()
    expected = _expected_topic_ids()

    session = _FakeSession()
    session.configure(
        groups=[
            {"group_id": gid1, "group_name": "GroupA", "group_type": "neighborhood", "member_count": 3},
            {"group_id": gid2, "group_name": "GroupB", "group_type": "neighborhood", "member_count": 5},
        ],
        knowledge=[
            # GroupA has all topics covered
            {"scope_target_id": gid1, "topic_id": t} for t in expected
        ] + [
            # GroupB has nothing
        ],
    )

    gaps = asyncio.run(get_group_knowledge_gaps(session, tid))
    assert len(gaps) == 1, "only GroupB should have gaps"
    assert gaps[0].group_name == "GroupB"


def test_to_dict_shape():
    """to_dict() must include all fields the frontend needs."""
    gap = GroupKnowledgeGap(
        group_id=uuid4(),
        group_name="TestGroup",
        group_type="hoa",
        member_count=7,
        missing_topics=["hoa_rules", "gate_code"],
        present_topics=["quiet_hours"],
    )
    d = gap.to_dict()
    assert "group_id" in d
    assert "group_name" in d
    assert "member_count" in d
    assert "missing_topics" in d
    assert "present_topics" in d
    assert "coverage_fraction" in d
    assert d["coverage_fraction"] == pytest.approx(1 / 3)  # 1 present / 3 total expected
