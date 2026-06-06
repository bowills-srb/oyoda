from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from uuid import UUID

from app.services.messaging_brain.knowledge.dashboard_kb_service import (
    DashboardKnowledgeService,
)


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
        raise AssertionError(f"Unexpected SQL: {sql}")

    async def commit(self):
        self.commits += 1


def test_count_dashboard_entries_uses_scoped_table():
    tenant_id = UUID("00000000-0000-0000-0000-000000000001")
    session = _FakeSession(
        [
            (
                lambda sql: "FROM concierge_scoped_knowledge" in sql and "COUNT(*)" in sql,
                _FakeResult(scalar_value=17),
            ),
        ]
    )

    total = asyncio.run(
        DashboardKnowledgeService().count_dashboard_entries(session, tenant_id)
    )

    assert total == 17


def test_list_dashboard_entries_returns_tenant_and_property_rows():
    tenant_id = UUID("00000000-0000-0000-0000-000000000001")
    session = _FakeSession(
        [
            (
                lambda sql: "FROM concierge_scoped_knowledge k" in sql,
                _FakeResult(
                    rows=[
                        SimpleNamespace(
                            knowledge_entry_id=UUID("11111111-1111-1111-1111-111111111111"),
                            scope_type="tenant",
                            scope_target_id=tenant_id,
                            topic_id=None,
                            question_text="What time is check in?",
                            answer_text="Check-in starts at 4 PM.",
                            tags=json.dumps([]),
                            source="operator_dashboard",
                            metadata=json.dumps({"category": "Check In", "confidence": 0.93}),
                            version=1,
                            property_code=None,
                            external_id=None,
                        ),
                        SimpleNamespace(
                            knowledge_entry_id=UUID("22222222-2222-2222-2222-222222222222"),
                            scope_type="property",
                            scope_target_id=UUID("33333333-3333-3333-3333-333333333333"),
                            topic_id="parking",
                            question_text="Where do we park?",
                            answer_text="Two cars fit in the driveway.",
                            tags=json.dumps(["parking"]),
                            source="operator_dashboard",
                            metadata=json.dumps({"confidence": 0.88}),
                            version=1,
                            property_code="P-303",
                            external_id="P-303",
                        ),
                    ]
                ),
            ),
        ]
    )

    entries = asyncio.run(
        DashboardKnowledgeService().list_dashboard_entries(session, tenant_id)
    )

    assert len(entries) == 2
    assert entries[0]["property_label"] == "All Properties"
    assert entries[0]["category"] == "Check In"
    assert entries[1]["property_label"] == "P-303"
    assert entries[1]["category"] == "Parking"
    assert entries[1]["property_id"] == "33333333-3333-3333-3333-333333333333"


def test_create_dashboard_entry_uses_tenant_scope_for_all_properties():
    tenant_id = UUID("00000000-0000-0000-0000-000000000001")
    entry_id = UUID("44444444-4444-4444-4444-444444444444")
    session = _FakeSession(
        [
            (
                lambda sql: "INSERT INTO concierge_scoped_knowledge" in sql,
                _FakeResult(rows=[SimpleNamespace(knowledge_entry_id=entry_id)]),
            ),
        ]
    )

    entry = asyncio.run(
        DashboardKnowledgeService().create_dashboard_entry(
            session=session,
            tenant_id=tenant_id,
            question="Is the pool heated?",
            answer="Yes, it stays heated year-round.",
            category="Amenities",
            property_external_id="__all_properties__",
        )
    )

    assert entry["id"] == str(entry_id)
    assert entry["property_label"] == "All Properties"
    assert session.commits == 1


def test_test_dashboard_question_matches_best_entry():
    tenant_id = UUID("00000000-0000-0000-0000-000000000001")
    service = DashboardKnowledgeService()

    async def _fake_list(*_args, **_kwargs):
        return [
            {
                "question": "Where do we park?",
                "answer": "Driveway only.",
                "category": "Parking",
                "property_label": "P-101",
            },
            {
                "question": "What time is check in?",
                "answer": "4 PM.",
                "category": "Check In",
                "property_label": "P-101",
            },
        ]

    service.list_dashboard_entries = _fake_list  # type: ignore[method-assign]

    result = asyncio.run(
        service.test_dashboard_question(
            session=object(),
            tenant_id=tenant_id,
            question="where do we park",
        )
    )

    assert result["best"]["answer"] == "Driveway only."
    assert result["score"] >= 0.8
