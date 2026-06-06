from __future__ import annotations

import asyncio

import pytest

from app.services.operator.escalation_action_agent import EscalationActionAgent
from app.services.operator.escalation_detector_service import EscalationDetectorService


class _FakeMappingsResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class _FakeExecuteResult:
    rowcount = 1


class _FakeSession:
    def __init__(self, scripted):
        self.scripted = list(scripted)
        self.executed = []
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, statement, params=None):
        self.executed.append((str(statement), params or {}))
        if not self.scripted:
            return _FakeExecuteResult()
        action = self.scripted.pop(0)
        if isinstance(action, Exception):
            raise action
        kind, payload = action
        if kind == "mappings":
            return _FakeMappingsResult(payload)
        if kind == "ok":
            return _FakeExecuteResult()
        raise AssertionError(f"Unknown execute action: {kind}")

    async def scalar(self, statement, params=None):
        self.executed.append((str(statement), params or {}))
        action = self.scripted.pop(0)
        if isinstance(action, Exception):
            raise action
        kind, payload = action
        assert kind == "scalar"
        return payload

    async def rollback(self):
        self.rollbacks += 1

    async def commit(self):
        self.commits += 1


def test_detector_derives_vendor_eta_internal_and_accounting_signals():
    service = EscalationDetectorService()
    row = {
        "reason": "maintenance",
        "summary": "Water damage and refund requested after HVAC leak",
        "last_message": "Can someone send help and explain refund options?",
        "priority": "high",
    }
    workflow = {
        "stage": "triaged",
        "vendor_state": "selected",
        "guest_update_state": "pending",
        "vendor": {"eta_minutes": 35},
        "sla": {"ack_breached": False, "resolve_breached": True},
    }

    signals = service.detect(row, workflow)

    assert signals["maintenance_issue"] is True
    assert signals["vendor_dispatch_needed"] is True
    assert signals["guest_eta_ready"] is True
    assert signals["owner_internal_update_needed"] is True
    assert signals["accounting_claim_handoff_needed"] is True


def test_detector_marks_life_safety_and_booking_hold_for_gas():
    service = EscalationDetectorService()
    row = {
        "reason": "safety",
        "summary": "Guest reports strong gas smell near stove",
        "last_message": "We smell gas and left the property",
        "priority": "urgent",
    }
    workflow = {"stage": "detected", "vendor_state": "", "guest_update_state": "pending", "vendor": {}, "sla": {}}

    signals = service.detect(row, workflow)

    assert signals["life_safety_emergency"] is True
    assert signals["booking_hold_required"] is True
    assert signals["human_ack_required"] is True
    assert signals["safety_protocol"]["protocol"] == "evacuate_now"


def test_sync_actions_persists_desired_queue_rows(monkeypatch):
    agent = EscalationActionAgent()
    async def _fake_vendors(*args, **kwargs):
        return [{"name": "Lanier HVAC", "phone": "555-1000", "score": 18}]

    async def _fake_routing(*args, **kwargs):
        return {"alert_type": "maintenance", "available_contacts": [{"contact_name": "Ops Lead"}], "skipped_contacts": []}

    monkeypatch.setattr(agent, "_recommended_dispatch_vendors", _fake_vendors)
    monkeypatch.setattr(agent, "_routing_snapshot", _fake_routing)
    db = _FakeSession(
        [
            ("scalar", True),
            ("scalar", False),
            ("mappings", []),
            ("ok", None),
            ("ok", None),
            ("ok", None),
            ("ok", None),
            ("scalar", True),
            ("mappings", [
                {
                    "workflow_ref": "ESC-1",
                    "action_type": "vendor_coordination",
                    "status": "ready",
                    "priority": "high",
                    "property_code": "LANIER-1",
                    "payload_json": {},
                    "result_json": {},
                    "due_at": None,
                    "created_at": None,
                    "updated_at": None,
                    "completed_at": None,
                },
                {
                    "workflow_ref": "ESC-1",
                    "action_type": "guest_eta_update",
                    "status": "ready",
                    "priority": "high",
                    "property_code": "LANIER-1",
                    "payload_json": {},
                    "result_json": {},
                    "due_at": None,
                    "created_at": None,
                    "updated_at": None,
                    "completed_at": None,
                },
                {
                    "workflow_ref": "ESC-1",
                    "action_type": "owner_internal_update",
                    "status": "ready",
                    "priority": "high",
                    "property_code": "LANIER-1",
                    "payload_json": {},
                    "result_json": {},
                    "due_at": None,
                    "created_at": None,
                    "updated_at": None,
                    "completed_at": None,
                },
                {
                    "workflow_ref": "ESC-1",
                    "action_type": "accounting_claim_handoff",
                    "status": "ready",
                    "priority": "high",
                    "property_code": "LANIER-1",
                    "payload_json": {},
                    "result_json": {},
                    "due_at": None,
                    "created_at": None,
                    "updated_at": None,
                    "completed_at": None,
                },
            ]),
        ]
    )

    row = {
        "ticket_id": "ESC-1",
        "property_code": "LANIER-1",
        "guest_phone": "+15555551212",
        "guest_name": "Guest",
        "priority": "high",
        "reason": "maintenance",
        "summary": "Water damage and refund requested",
        "last_message": "Please send someone quickly",
        "assigned_to": "ops@lanier.com",
        "watchers": ["mgr@lanier.com"],
    }
    workflow = {
        "stage": "vendor_dispatch",
        "vendor_state": "selected",
        "guest_update_state": "pending",
        "vendor": {"name": "Lanier HVAC", "eta_minutes": 35},
        "sla": {"ack_breached": False, "resolve_breached": True},
    }

    actions = asyncio.run(
        agent.sync_actions(
            db,
            "00000000-0000-0000-0000-000000000001",
            row,
            workflow,
        )
    )

    assert len(actions) == 4
    upserts = [sql for sql, _ in db.executed if "INSERT INTO operator_workflow_action_queue" in sql]
    assert len(upserts) == 4


def test_execute_vendor_coordination_marks_action_in_progress():
    agent = EscalationActionAgent()
    db = _FakeSession(
        [
            ("scalar", True),
            ("mappings", [
                {
                    "action_type": "vendor_coordination",
                    "status": "ready",
                    "payload_json": {},
                    "result_json": {},
                    "ticket_id": "ESC-9",
                    "session_token": "sess-9",
                    "property_code": "LANIER-9",
                    "priority": "high",
                    "reason": "maintenance",
                    "summary": "AC out",
                    "last_message": "Please help",
                    "assigned_to": None,
                    "watchers": [],
                    "vendor_name": None,
                    "vendor_phone": None,
                    "vendor_eta_minutes": None,
                    "vendor_status": None,
                    "guest_update_status": None,
                    "guest_update_note": None,
                    "session_id": "sess-db-9",
                    "guest_phone": "+15555550000",
                    "guest_name": "Guest",
                }
            ]),
            ("ok", None),
            ("scalar", True),
            ("ok", None),
            ("ok", None),
        ]
    )

    result = asyncio.run(
        agent.execute_action(
            db,
            "00000000-0000-0000-0000-000000000001",
            "ESC-9",
            "vendor_coordination",
            actor_label="ops@lanier.com",
        )
    )

    assert result["status"] == "in_progress"
    assert "Vendor coordination" in result["message"]
