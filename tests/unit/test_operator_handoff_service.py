from __future__ import annotations

import asyncio
import json

from app.services.operator.handoff_service import OperatorHandoffService


class _FakeMappingsResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class _FakeSession:
    def __init__(self, scripted):
        self.scripted = list(scripted)
        self.executed = []

    async def execute(self, statement, params=None):
        self.executed.append((str(statement), params or {}))
        if not self.scripted:
            return _FakeMappingsResult([])
        kind, payload = self.scripted.pop(0)
        assert kind == "mappings"
        return _FakeMappingsResult(payload)

    async def scalar(self, statement, params=None):
        self.executed.append((str(statement), params or {}))
        kind, payload = self.scripted.pop(0)
        assert kind == "scalar"
        return payload


def test_create_or_refresh_handoff_creates_new_record():
    service = OperatorHandoffService()
    db = _FakeSession(
        [
            ("scalar", True),
            ("mappings", []),
            ("mappings", [{"handoff_id": "h-1", "status": "open"}]),
        ]
    )

    result = asyncio.run(
        service.create_or_refresh_handoff(
            db,
            "00000000-0000-0000-0000-000000000001",
            workflow_type="stay",
            workflow_ref="sess-1",
            handoff_type="owner_internal",
            subject="Owner update",
            body="Needs visibility",
            payload={"foo": "bar"},
        )
    )

    assert result["handoff_id"] == "h-1"
    _, params = db.executed[-1]
    assert json.loads(params["payload_json"]) == {"foo": "bar"}


def test_summarize_handoffs_counts_open_items():
    service = OperatorHandoffService()
    db = _FakeSession(
        [
            ("scalar", True),
            ("scalar", True),
            ("mappings", [
                {
                    "handoff_id": "h-1",
                    "workflow_ref": "sess-1",
                    "handoff_type": "owner_internal",
                    "status": "open",
                    "priority": "high",
                    "property_code": "LANIER-1",
                    "assignee_user_id": None,
                    "assignee_label": None,
                    "subject": "Owner update",
                    "body": "Needs visibility",
                    "payload_json": {},
                    "resolution_json": {},
                    "created_at": None,
                    "updated_at": None,
                    "closed_at": None,
                },
                {
                    "handoff_id": "h-2",
                    "workflow_ref": "sess-1",
                    "handoff_type": "accounting_claims",
                    "status": "completed",
                    "priority": "high",
                    "property_code": "LANIER-1",
                    "assignee_user_id": None,
                    "assignee_label": None,
                    "subject": "Claims review",
                    "body": "Needs review",
                    "payload_json": {},
                    "resolution_json": {},
                    "created_at": None,
                    "updated_at": None,
                    "closed_at": None,
                },
            ]),
        ]
    )

    summary = asyncio.run(
        service.summarize_handoffs(
            db,
            "00000000-0000-0000-0000-000000000001",
            workflow_type="stay",
            workflow_ref="sess-1",
        )
    )

    assert summary["open_count"] == 1
    assert summary["total_count"] == 2
    assert "owner_internal" in summary["types"]
