from __future__ import annotations

import asyncio

from app.api.v1.endpoints import operator_prebooking


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _FakeSession:
    def __init__(self, rows):
        self._rows = rows
        self.executed = []

    async def execute(self, statement, params=None):
        self.executed.append((str(statement), params or {}))
        return _FakeResult(self._rows)

    async def rollback(self):
        return None


def test_escalation_query_meta_supports_legacy_schema():
    db = _FakeSession(
        [
            ("ticket_id",),
            ("session_token",),
            ("reason",),
            ("priority",),
            ("status",),
            ("summary",),
            ("created_at",),
        ]
    )

    meta = asyncio.run(operator_prebooking._escalation_query_meta(db))

    assert meta == {
        "id_expr": "ticket_id",
        "type_expr": "reason",
        "priority_expr": "priority",
        "status_expr": "status",
        "summary_expr": "summary",
        "session_token_expr": "session_token",
        "created_at_expr": "created_at",
        "resolved_at_expr": None,
        "tenant_expr": None,
    }
    sql, params = db.executed[0]
    assert "information_schema.columns" in sql
    assert params == {"table": "concierge_escalations"}


def test_review_ready_draft_sources_include_messaging_brain():
    assert operator_prebooking._is_review_ready_draft_source("model") is True
    assert operator_prebooking._is_review_ready_draft_source("messaging_brain") is True
    assert operator_prebooking._is_review_ready_draft_source("kb_gap_required") is False


def test_row_visible_for_scope_keeps_unbound_inquiries_visible():
    assert operator_prebooking._row_visible_for_scope(
        {"property_external_id": ""},
        {"LANIER-1"},
    ) is True
    assert operator_prebooking._row_visible_for_scope(
        {"property_external_id": None},
        {"LANIER-1"},
    ) is True


def test_row_visible_for_scope_still_filters_bound_inquiries():
    visible = {"LANIER-1", "BEACH-1"}
    assert operator_prebooking._row_visible_for_scope(
        {"property_external_id": "LANIER-1"},
        visible,
    ) is True
    assert operator_prebooking._row_visible_for_scope(
        {"property_external_id": "OTHER-9"},
        visible,
    ) is False
