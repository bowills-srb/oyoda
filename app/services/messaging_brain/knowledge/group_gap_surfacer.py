"""Group knowledge-gap surfacer — proactive HOA/neighborhood coverage check.

For each property_group that has ≥1 member property, computes which
expected-group-scope topics are missing from the group's scoped knowledge.

WHAT THIS IS:
  Structural / proactive gaps — "WaterSound has 12 properties but no HOA
  policy on file." Driven by expected-topic coverage, NOT by guest questions.

WHAT THIS IS NOT:
  Reactive gaps (unanswered guest questions) live in concierge_knowledge_gaps.
  Keep the two distinct: reactive = what guests asked; structural = what the
  operator should have filled before any guest arrived.

HONESTY RULES (same discipline as the rest of the session):
  - Absence of a GROUP is not a gap. Only groups that EXIST with members.
  - A property with no group membership is not flagged.
  - Surfacing is read-only analysis — it never auto-writes knowledge.
  - A surfaced gap is a prompt to the operator, not an error.
  - Beach Habitats memberships are currently empty (Gap 3 not yet run) → this
    surfaces nothing for the live tenant, which is correct/honest. Lights up
    after Gap 3 populates memberships.
  - group-scope check only: if a tenant-scope entry covers the topic, it does
    NOT suppress the structural gap for v1. The point is neighborhood-specific
    rules; a generic tenant fallback doesn't tell you WaterSound's HOA policy.
    (Decision documented, revisable in v2.)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.messaging_brain.knowledge.topic_registry import (
    KnowledgeTopicDefinition,
    get_group_expected_topics,
)


@dataclass(frozen=True)
class GroupKnowledgeGap:
    """One group's missing expected-topic coverage."""
    group_id: UUID
    group_name: str
    group_type: str
    member_count: int
    missing_topics: List[str]       # topic_ids not present at group scope
    present_topics: List[str]       # topic_ids that ARE present (for context)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "group_id": str(self.group_id),
            "group_name": self.group_name,
            "group_type": self.group_type,
            "member_count": self.member_count,
            "missing_topics": self.missing_topics,
            "present_topics": self.present_topics,
            "coverage_fraction": (
                len(self.present_topics)
                / max(1, len(self.present_topics) + len(self.missing_topics))
            ),
        }


def _expected_topic_ids() -> frozenset[str]:
    return frozenset(t.topic_id for t in get_group_expected_topics())


async def get_group_knowledge_gaps(
    session: AsyncSession,
    tenant_id: UUID | str,
) -> List[GroupKnowledgeGap]:
    """Compute structural knowledge gaps for all groups with members.

    Returns one GroupKnowledgeGap per group that has ≥1 member AND at least
    one missing expected topic. Groups with no members are excluded. Groups
    that have all expected topics covered return nothing (not in the list).
    """
    tid = str(tenant_id)
    expected = _expected_topic_ids()

    # -- Load active groups that have at least one member -----------------------
    try:
        group_rows = (await session.execute(
            text("""
                SELECT
                    g.id AS group_id,
                    g.name AS group_name,
                    COALESCE(g.group_type, 'neighborhood') AS group_type,
                    COUNT(m.property_id) AS member_count
                FROM property_groups g
                JOIN property_group_memberships m
                    ON m.property_group_id = g.id
                   AND m.tenant_id = CAST(:tid AS uuid)
                WHERE g.tenant_id = CAST(:tid AS uuid)
                  AND COALESCE(g.is_active, TRUE) = TRUE
                GROUP BY g.id, g.name, g.group_type
                HAVING COUNT(m.property_id) >= 1
                ORDER BY g.name
            """),
            {"tid": tid},
        )).mappings().all()
    except Exception:
        return []

    if not group_rows:
        return []

    group_ids = [str(row["group_id"]) for row in group_rows]

    # -- Load all active group-scoped topic_ids for these groups in one query --
    try:
        knowledge_rows = (await session.execute(
            text("""
                SELECT
                    scope_target_id,
                    topic_id
                FROM concierge_scoped_knowledge
                WHERE tenant_id = CAST(:tid AS uuid)
                  AND scope_type = 'property_group'
                  AND scope_target_id = ANY(CAST(:group_ids AS uuid[]))
                  AND topic_id IS NOT NULL
                  AND COALESCE(is_active, TRUE) = TRUE
            """),
            {"tid": tid, "group_ids": group_ids},
        )).mappings().all()
    except Exception:
        knowledge_rows = []

    # Build: group_id → set of present topic_ids
    present_by_group: Dict[str, set[str]] = {gid: set() for gid in group_ids}
    for row in knowledge_rows:
        gid = str(row["scope_target_id"])
        if gid in present_by_group and row["topic_id"]:
            present_by_group[gid].add(str(row["topic_id"]))

    # -- Compute gaps ----------------------------------------------------------
    gaps: List[GroupKnowledgeGap] = []
    for row in group_rows:
        gid = str(row["group_id"])
        present = present_by_group.get(gid, set())
        missing = sorted(expected - present)
        if not missing:
            continue  # fully covered — don't surface
        gaps.append(GroupKnowledgeGap(
            group_id=UUID(gid),
            group_name=str(row["group_name"]),
            group_type=str(row["group_type"]),
            member_count=int(row["member_count"]),
            missing_topics=missing,
            present_topics=sorted(expected & present),
        ))

    return gaps
