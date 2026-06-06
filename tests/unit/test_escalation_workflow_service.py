from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from app.services.operator.escalation_workflow_service import EscalationWorkflowService


class _FakeMappingsResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class _FakeScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value


class _FakeSession:
    def __init__(self, scripted):
        self.scripted = list(scripted)
        self.executed = []
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, statement, params=None):
        self.executed.append((str(statement), params or {}))
        if not self.scripted:
            return _FakeMappingsResult([])
        kind, payload = self.scripted.pop(0)
        if kind == "mappings":
            return _FakeMappingsResult(payload)
        raise AssertionError(f"Unknown action: {kind}")

    async def scalar(self, statement, params=None):
        kind, payload = self.scripted.pop(0)
        assert kind == "scalar"
        return payload

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


def test_build_workflow_moves_into_vendor_dispatch_and_guest_update():
    service = EscalationWorkflowService()
    row = {
        "ticket_id": "ESC-1234",
        "session_token": "sess-1",
        "property_code": "LANIER-1",
        "priority": "high",
        "status": "acknowledged",
        "reason": "maintenance",
        "summary": "AC not working",
        "assigned_to": "ops@lanier.com",
        "watchers": ["mgr@lanier.com"],
        "watchers_notified_at": datetime(2026, 4, 22, tzinfo=timezone.utc),
        "vendor_name": "Lanier HVAC",
        "vendor_phone": "555-555-1212",
        "vendor_eta_minutes": 45,
        "vendor_status": "scheduled",
        "guest_updated_at": None,
        "guest_update_status": "draft_needed",
        "guest_update_due_at": None,
        "guest_update_note": None,
        "acknowledged_at": datetime(2026, 4, 22, tzinfo=timezone.utc),
        "resolved_at": None,
        "created_at": datetime(2026, 4, 22, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 4, 22, tzinfo=timezone.utc),
        "ack_sla_breached": False,
        "resolve_sla_breached": False,
    }

    workflow = service._build_workflow(row)

    assert workflow["stage"] == "vendor_dispatch"
    assert workflow["owner_state"] == "assigned"
    assert workflow["watcher_state"] == "notified"
    assert workflow["vendor_state"] == "scheduled"
    assert workflow["guest_update_state"] == "draft_needed"
    assert workflow["vendor"]["eta_minutes"] == 45


def test_record_vendor_transition_updates_vendor_lifecycle_state():
    service = EscalationWorkflowService()
    fake_db = _FakeSession(
        [
            ("scalar", True),
            ("scalar", True),
            ("mappings", [
                {
                    "workflow_json": {
                        "vendor": {
                            "name": "Old Vendor",
                            "status": "contacted",
                            "replacement_count": 0,
                        },
                        "vendor_history": [],
                    }
                }
            ]),
            ("mappings", []),
        ]
    )

    result = asyncio.run(
        service.record_vendor_transition(
            fake_db,
            "00000000-0000-0000-0000-000000000001",
            "ESC-1234",
            {
                "changed_at": "2026-04-22T15:00:00+00:00",
                "changed_by": "ops@example.com",
                "vendor_name": "Backup Vendor",
                "vendor_status": "reassigned",
                "previous_vendor_name": "Old Vendor",
                "replace_existing": True,
                "note": "Original vendor could not make it",
            },
        )
    )

    assert result is True
    _, params = fake_db.executed[-1]
    workflow = json.loads(params["workflow_json"])
    assert workflow["vendor"]["previous_status"] == "contacted"
    assert workflow["vendor"]["status"] == "reassigned"
    assert workflow["vendor"]["replacement_count"] == 1
    assert workflow["vendor"]["status_changed_by"] == "ops@example.com"


def test_sync_ticket_persists_workflow_row():
    service = EscalationWorkflowService()
    fake_db = _FakeSession(
        [
            ("mappings", [
                {
                    "ticket_id": "ESC-1234",
                    "session_token": "sess-1",
                    "property_code": "LANIER-1",
                    "priority": "high",
                    "status": "pending",
                    "reason": "maintenance",
                    "summary": "AC not working",
                    "assigned_to": None,
                    "watchers": [],
                    "watchers_notified_at": None,
                    "vendor_name": None,
                    "vendor_phone": None,
                    "vendor_eta_minutes": None,
                    "vendor_status": None,
                    "guest_updated_at": None,
                    "guest_update_status": None,
                    "guest_update_due_at": None,
                    "guest_update_note": None,
                    "acknowledged_at": None,
                    "resolved_at": None,
                    "created_at": datetime(2026, 4, 22, tzinfo=timezone.utc),
                    "updated_at": datetime(2026, 4, 22, tzinfo=timezone.utc),
                    "ack_sla_breached": False,
                    "resolve_sla_breached": False,
                }
            ]),
            ("scalar", False),
            ("scalar", False),
            ("scalar", False),
            ("scalar", False),
            ("scalar", True),
        ]
    )

    result = asyncio.run(
        service.sync_ticket(
            fake_db,
            "00000000-0000-0000-0000-000000000001",
            "ESC-1234",
        )
    )

    assert result is True
    insert_sql, insert_params = next((entry for entry in reversed(fake_db.executed) if "operator_escalation_workflow_read_models" in entry[0]), ("", {}))
    assert "operator_escalation_workflow_read_models" in insert_sql
    assert insert_params["workflow_stage"] == "detected"
    assert fake_db.commits == 1
