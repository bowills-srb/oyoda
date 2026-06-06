"""
Piece A: property_group scope support in DashboardKnowledgeService.

Tests cover:
- _resolve_scope returns property_group scope when group_id provided
- list_dashboard_entries includes group entries with correct scope_kind / property_label
- list_dashboard_entries group_id filter generates correct SQL
- count_dashboard_entries includes property_group in scope filter
- create_dashboard_entry with property_group_id resolves to group scope
- update/delete work for group entries (scope-agnostic, keyed on entry_id)
- property and tenant operations unchanged (regression)
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.services.messaging_brain.knowledge.dashboard_kb_service import (
    DashboardKnowledgeService,
)

TENANT_ID = UUID("aaaaaaaa-0000-0000-0000-000000000001")
PROPERTY_ID = UUID("bbbbbbbb-0000-0000-0000-000000000002")
GROUP_ID = UUID("cccccccc-0000-0000-0000-000000000003")
ENTRY_ID = UUID("dddddddd-0000-0000-0000-000000000004")


class _FakeResult:
    def __init__(self, rows=None, scalar_value=None, rowcount=1):
        self._rows = rows or []
        self._scalar_value = scalar_value
        self.rowcount = rowcount

    def scalar(self):
        return self._scalar_value

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _FakeSession:
    def __init__(self, handlers):
        self._handlers = handlers
        self.executed = []
        self.commits = 0

    async def execute(self, statement, params=None):
        sql = str(statement)
        payload = params or {}
        self.executed.append((sql, payload))
        for predicate, result in self._handlers:
            if predicate(sql):
                return result(sql, payload) if callable(result) else result
        raise AssertionError(f"Unexpected SQL:\n{sql}")

    async def commit(self):
        self.commits += 1


# ---------------------------------------------------------------------------
# _resolve_scope
# ---------------------------------------------------------------------------

def test_resolve_scope_returns_property_group_scope():
    """When property_group_id is provided, scope_type = 'property_group'."""
    group_row = SimpleNamespace(id=GROUP_ID, name="Blue Mountain Beach")
    session = _FakeSession(
        [
            (
                lambda sql: "FROM property_groups" in sql,
                _FakeResult(rows=[group_row]),
            ),
        ]
    )
    svc = DashboardKnowledgeService()
    scope = asyncio.run(
        svc._resolve_scope(
            session=session,
            tenant_id=TENANT_ID,
            property_id=None,
            property_external_id=None,
            property_group_id=str(GROUP_ID),
        )
    )
    assert scope["scope_type"] == "property_group"
    assert scope["scope_target_id"] == str(GROUP_ID)
    assert scope["property_id"] is None
    assert scope["property_label"] == "Blue Mountain Beach"
    assert scope["scope_kind"] == "neighborhood"


def test_resolve_scope_property_group_not_found_falls_to_tenant():
    """If the group_id is not found in DB, fall through to tenant scope."""
    session = _FakeSession(
        [
            (
                lambda sql: "FROM property_groups" in sql,
                _FakeResult(rows=[]),
            ),
        ]
    )
    svc = DashboardKnowledgeService()
    scope = asyncio.run(
        svc._resolve_scope(
            session=session,
            tenant_id=TENANT_ID,
            property_id=None,
            property_external_id=None,
            property_group_id=str(GROUP_ID),
        )
    )
    assert scope["scope_type"] == "tenant"
    assert scope["scope_kind"] == "portfolio"


def test_resolve_scope_property_takes_precedence_over_group():
    """property_id wins if both property_id and property_group_id are provided."""
    property_row = SimpleNamespace(id=PROPERTY_ID, property_code="PROP1", external_id="EXT1")
    session = _FakeSession(
        [
            (
                lambda sql: "FROM properties" in sql and ":property_id" in sql,
                _FakeResult(rows=[property_row]),
            ),
        ]
    )
    svc = DashboardKnowledgeService()
    scope = asyncio.run(
        svc._resolve_scope(
            session=session,
            tenant_id=TENANT_ID,
            property_id=str(PROPERTY_ID),
            property_external_id=None,
            property_group_id=str(GROUP_ID),
        )
    )
    assert scope["scope_type"] == "property"


def test_resolve_scope_tenant_fallthrough_has_scope_kind():
    """Tenant fallthrough now includes scope_kind='portfolio'."""
    session = _FakeSession([])
    svc = DashboardKnowledgeService()
    scope = asyncio.run(
        svc._resolve_scope(
            session=session,
            tenant_id=TENANT_ID,
            property_id=None,
            property_external_id=None,
        )
    )
    assert scope["scope_type"] == "tenant"
    assert scope["scope_kind"] == "portfolio"


# ---------------------------------------------------------------------------
# list_dashboard_entries
# ---------------------------------------------------------------------------

def _make_group_row():
    return SimpleNamespace(
        knowledge_entry_id=ENTRY_ID,
        scope_type="property_group",
        scope_target_id=GROUP_ID,
        topic_id=None,
        question_text="What are the check-in hours?",
        answer_text="Check-in is from 3pm.",
        tags=json.dumps([]),
        source="operator_dashboard",
        metadata=json.dumps({"category": "Check-In", "confidence": 0.92, "usage_count": 0}),
        version=1,
        property_code=None,
        external_id=None,
        group_name="Blue Mountain Beach",
    )


def test_list_dashboard_entries_includes_group_entries():
    """list_dashboard_entries returns scope_kind='neighborhood' for group entries."""
    session = _FakeSession(
        [
            (
                lambda sql: "FROM concierge_scoped_knowledge" in sql and "SELECT" in sql,
                _FakeResult(rows=[_make_group_row()]),
            ),
        ]
    )
    svc = DashboardKnowledgeService()
    entries = asyncio.run(
        svc.list_dashboard_entries(session=session, tenant_id=TENANT_ID)
    )
    assert len(entries) == 1
    e = entries[0]
    assert e["scope_type"] == "property_group"
    assert e["scope_kind"] == "neighborhood"
    assert e["property_label"] == "Blue Mountain Beach"
    assert e["property_id"] is None


def test_list_dashboard_entries_group_id_filter_passes_param():
    """When group_id is provided, the executed SQL params include 'group_id'."""
    session = _FakeSession(
        [
            (
                lambda sql: "FROM concierge_scoped_knowledge" in sql and "SELECT" in sql,
                _FakeResult(rows=[_make_group_row()]),
            ),
        ]
    )
    svc = DashboardKnowledgeService()
    asyncio.run(
        svc.list_dashboard_entries(
            session=session, tenant_id=TENANT_ID, group_id=str(GROUP_ID)
        )
    )
    _, params = session.executed[0]
    assert "group_id" in params
    assert params["group_id"] == str(GROUP_ID)


def test_list_dashboard_entries_group_id_sql_contains_property_group_filter():
    """SQL generated for group_id filter contains scope_type = 'property_group'."""
    session = _FakeSession(
        [
            (
                lambda sql: "FROM concierge_scoped_knowledge" in sql and "SELECT" in sql,
                _FakeResult(rows=[]),
            ),
        ]
    )
    svc = DashboardKnowledgeService()
    asyncio.run(
        svc.list_dashboard_entries(
            session=session, tenant_id=TENANT_ID, group_id=str(GROUP_ID)
        )
    )
    sql, _ = session.executed[0]
    assert "property_group" in sql


def test_list_dashboard_entries_tenant_scope_kind_is_portfolio():
    """Tenant-scoped entries get scope_kind='portfolio'."""
    tenant_row = SimpleNamespace(
        knowledge_entry_id=ENTRY_ID,
        scope_type="tenant",
        scope_target_id=TENANT_ID,
        topic_id=None,
        question_text="What is Wi-Fi password?",
        answer_text="BeachLife123",
        tags=json.dumps([]),
        source="operator_dashboard",
        metadata=json.dumps({"category": "Wi-Fi", "confidence": 0.92, "usage_count": 0}),
        version=1,
        property_code=None,
        external_id=None,
        group_name=None,
    )
    session = _FakeSession(
        [
            (
                lambda sql: "FROM concierge_scoped_knowledge" in sql and "SELECT" in sql,
                _FakeResult(rows=[tenant_row]),
            ),
        ]
    )
    svc = DashboardKnowledgeService()
    entries = asyncio.run(svc.list_dashboard_entries(session=session, tenant_id=TENANT_ID))
    assert entries[0]["scope_kind"] == "portfolio"


def test_list_dashboard_entries_property_scope_kind_is_property():
    """Property-scoped entries get scope_kind='property'."""
    prop_row = SimpleNamespace(
        knowledge_entry_id=ENTRY_ID,
        scope_type="property",
        scope_target_id=PROPERTY_ID,
        topic_id=None,
        question_text="Parking details?",
        answer_text="Street parking only.",
        tags=json.dumps([]),
        source="operator_dashboard",
        metadata=json.dumps({"category": "Parking", "confidence": 0.92, "usage_count": 0}),
        version=1,
        property_code="PROP1",
        external_id="EXT1",
        group_name=None,
    )
    session = _FakeSession(
        [
            (
                lambda sql: "FROM concierge_scoped_knowledge" in sql and "SELECT" in sql,
                _FakeResult(rows=[prop_row]),
            ),
        ]
    )
    svc = DashboardKnowledgeService()
    entries = asyncio.run(svc.list_dashboard_entries(session=session, tenant_id=TENANT_ID))
    assert entries[0]["scope_kind"] == "property"
    assert entries[0]["property_id"] == str(PROPERTY_ID)


# ---------------------------------------------------------------------------
# count_dashboard_entries
# ---------------------------------------------------------------------------

def test_count_dashboard_entries_includes_property_group_scope():
    """count_dashboard_entries SQL must include 'property_group' in scope filter."""
    session = _FakeSession(
        [
            (
                lambda sql: "FROM concierge_scoped_knowledge" in sql and "COUNT(*)" in sql,
                _FakeResult(scalar_value=5),
            ),
        ]
    )
    svc = DashboardKnowledgeService()
    asyncio.run(svc.count_dashboard_entries(session=session, tenant_id=TENANT_ID))
    sql, _ = session.executed[0]
    assert "property_group" in sql


# ---------------------------------------------------------------------------
# create_dashboard_entry
# ---------------------------------------------------------------------------

def test_create_dashboard_entry_with_group_id_resolves_group_scope():
    """create_dashboard_entry with property_group_id stores scope_type='property_group'."""
    group_row = SimpleNamespace(id=GROUP_ID, name="Blue Mountain Beach")
    inserted_row = SimpleNamespace(knowledge_entry_id=ENTRY_ID)

    session = _FakeSession(
        [
            (
                lambda sql: "FROM property_groups" in sql,
                _FakeResult(rows=[group_row]),
            ),
            (
                lambda sql: "INSERT INTO concierge_scoped_knowledge" in sql,
                _FakeResult(rows=[inserted_row]),
            ),
        ]
    )
    svc = DashboardKnowledgeService()
    entry = asyncio.run(
        svc.create_dashboard_entry(
            session=session,
            tenant_id=TENANT_ID,
            question="What time is pool open?",
            answer="Pool is open 8am-10pm.",
            property_group_id=str(GROUP_ID),
        )
    )
    assert entry["id"] == str(ENTRY_ID)
    assert entry["property_label"] == "Blue Mountain Beach"

    # Verify the INSERT received the correct scope params
    insert_sql, insert_params = next(
        (sql, params)
        for sql, params in session.executed
        if "INSERT INTO concierge_scoped_knowledge" in sql
    )
    assert insert_params["scope_type"] == "property_group"
    assert insert_params["scope_target_id"] == str(GROUP_ID)


def test_create_dashboard_entry_without_group_id_still_works():
    """create_dashboard_entry without group_id regresses correctly to tenant scope."""
    inserted_row = SimpleNamespace(knowledge_entry_id=ENTRY_ID)
    session = _FakeSession(
        [
            (
                lambda sql: "INSERT INTO concierge_scoped_knowledge" in sql,
                _FakeResult(rows=[inserted_row]),
            ),
        ]
    )
    svc = DashboardKnowledgeService()
    entry = asyncio.run(
        svc.create_dashboard_entry(
            session=session,
            tenant_id=TENANT_ID,
            question="General question?",
            answer="General answer.",
        )
    )
    assert entry["property_label"] == "All Properties"
    _, params = next(
        (sql, p) for sql, p in session.executed if "INSERT" in sql
    )
    assert params["scope_type"] == "tenant"


# ---------------------------------------------------------------------------
# update_dashboard_entry (regression: scope-agnostic)
# ---------------------------------------------------------------------------

def test_update_dashboard_entry_works_for_group_scope_entry():
    """update_dashboard_entry is scope-agnostic — works for any entry_id."""
    existing_row = SimpleNamespace(metadata=json.dumps({"category": "Check-In"}))
    session = _FakeSession(
        [
            (
                lambda sql: "SELECT metadata" in sql,
                _FakeResult(rows=[existing_row]),
            ),
            (
                lambda sql: "UPDATE concierge_scoped_knowledge" in sql,
                _FakeResult(rowcount=1),
            ),
        ]
    )
    svc = DashboardKnowledgeService()
    updated = asyncio.run(
        svc.update_dashboard_entry(
            session=session,
            tenant_id=TENANT_ID,
            entry_id=str(ENTRY_ID),
            body={"answer": "Check-in is from 4pm now."},
        )
    )
    assert updated is True


def test_update_dashboard_entry_returns_false_when_not_found():
    session = _FakeSession(
        [
            (
                lambda sql: "SELECT metadata" in sql,
                _FakeResult(rows=[]),
            ),
        ]
    )
    svc = DashboardKnowledgeService()
    updated = asyncio.run(
        svc.update_dashboard_entry(
            session=session,
            tenant_id=TENANT_ID,
            entry_id=str(ENTRY_ID),
            body={"answer": "Whatever"},
        )
    )
    assert updated is False


# ---------------------------------------------------------------------------
# delete_dashboard_entry (regression: scope-agnostic)
# ---------------------------------------------------------------------------

def test_delete_dashboard_entry_works_for_group_scope_entry():
    """delete_dashboard_entry is scope-agnostic — soft-deletes by entry_id."""
    session = _FakeSession(
        [
            (
                lambda sql: "UPDATE concierge_scoped_knowledge" in sql and "is_active = FALSE" in sql,
                _FakeResult(rowcount=1),
            ),
        ]
    )
    svc = DashboardKnowledgeService()
    deleted = asyncio.run(
        svc.delete_dashboard_entry(
            session=session,
            tenant_id=TENANT_ID,
            entry_id=str(ENTRY_ID),
        )
    )
    assert deleted is True


def test_delete_dashboard_entry_returns_false_when_not_found():
    session = _FakeSession(
        [
            (
                lambda sql: "UPDATE concierge_scoped_knowledge" in sql and "is_active = FALSE" in sql,
                _FakeResult(rowcount=0),
            ),
        ]
    )
    svc = DashboardKnowledgeService()
    deleted = asyncio.run(
        svc.delete_dashboard_entry(
            session=session,
            tenant_id=TENANT_ID,
            entry_id=str(ENTRY_ID),
        )
    )
    assert deleted is False
