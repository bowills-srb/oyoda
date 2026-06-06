from __future__ import annotations

import asyncio
import json

from app.services.operator.work_order_service import OperatorWorkOrderService


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


def test_create_or_refresh_work_order_creates_new_record():
    service = OperatorWorkOrderService()
    db = _FakeSession(
        [
            ("scalar", True),
            ("mappings", []),
            ("mappings", [{"work_order_id": "wo-1"}]),
        ]
    )

    result = asyncio.run(
        service.create_or_refresh_work_order(
            db,
            "00000000-0000-0000-0000-000000000001",
            workflow_type="stay",
            workflow_ref="sess-1",
            property_code="LANIER-1",
            vendor_name="Lanier HVAC",
            issue_category="maintenance",
            summary="AC out",
            dispatch_state="scheduled",
            eta_visibility_mode="live_tracking",
            tracking_url="https://example.com/track/wo-1",
            last_known_distance_text="12 minutes away",
            payload={"decision": "preferred_vendor"},
        )
    )

    assert result["work_order_id"] == "wo-1"
    _, params = db.executed[-1]
    assert params["status"] == "scheduled"
    assert params["eta_visibility_mode"] == "live_tracking"
    assert json.loads(params["payload_json"]) == {"decision": "preferred_vendor"}


def test_summarize_work_orders_counts_open_items():
    service = OperatorWorkOrderService()
    db = _FakeSession(
        [
            ("scalar", True),
            ("scalar", True),
            ("mappings", [
                {
                    "work_order_id": "wo-1",
                    "workflow_ref": "sess-1",
                    "property_code": "LANIER-1",
                    "vendor_id": None,
                    "vendor_name": "Lanier HVAC",
                    "vendor_phone": "555-1000",
                    "issue_category": "maintenance",
                    "status": "scheduled",
                    "priority": "high",
                    "summary": "AC outage",
                    "details": "Guest says AC is out",
                    "dispatch_state": "scheduled",
                    "eta_minutes": 45,
                    "eta_visibility_mode": "estimated",
                    "tracking_url": None,
                    "last_known_distance_text": None,
                    "asset_id": None,
                    "verification_state": "pending",
                    "invoice_state": "not_received",
                    "invoice_amount": None,
                    "invoice_reference": None,
                    "last_actor_label": "ops@example.com",
                    "payload_json": {},
                    "resolution_json": {},
                    "created_at": None,
                    "updated_at": None,
                    "accepted_at": None,
                    "scheduled_at": None,
                    "completed_at": None,
                    "verified_at": None,
                    "closed_at": None,
                },
                {
                    "work_order_id": "wo-2",
                    "workflow_ref": "sess-1",
                    "property_code": "LANIER-1",
                    "vendor_id": None,
                    "vendor_name": "Lanier HVAC",
                    "vendor_phone": "555-1000",
                    "issue_category": "maintenance",
                    "status": "closed",
                    "priority": "high",
                    "summary": "AC outage",
                    "details": "Resolved",
                    "dispatch_state": "completed",
                    "eta_minutes": 45,
                    "eta_visibility_mode": "estimated",
                    "tracking_url": None,
                    "last_known_distance_text": None,
                    "asset_id": None,
                    "verification_state": "verified",
                    "invoice_state": "approved",
                    "invoice_amount": None,
                    "invoice_reference": None,
                    "last_actor_label": "ops@example.com",
                    "payload_json": {},
                    "resolution_json": {},
                    "created_at": None,
                    "updated_at": None,
                    "accepted_at": None,
                    "scheduled_at": None,
                    "completed_at": None,
                    "verified_at": None,
                    "closed_at": None,
                },
            ]),
        ]
    )

    summary = asyncio.run(
        service.summarize_work_orders(
            db,
            "00000000-0000-0000-0000-000000000001",
            workflow_type="stay",
            workflow_ref="sess-1",
        )
    )

    assert summary["open_count"] == 1
    assert summary["total_count"] == 2
    assert "scheduled" in summary["statuses"]
