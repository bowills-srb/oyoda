from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

from app.services.operator.stay_action_agent import StayActionAgent


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


def test_sync_actions_persists_stay_actions():
    agent = StayActionAgent()
    db = _FakeSession(
        [
            ("scalar", True),   # action queue exists
            ("scalar", False),  # vendors exists
            ("mappings", []),   # existing actions
            ("ok", None),       # proactive_outreach upsert
            ("ok", None),       # knowledge_response upsert
            ("ok", None),       # owner_internal_update upsert
            ("scalar", True),   # list_actions table exists
            ("mappings", [
                {
                    "workflow_ref": "8f49ef3f-eafb-4378-94e1-0db73738f100",
                    "action_type": "knowledge_response",
                    "status": "ready",
                    "priority": "medium",
                    "property_code": "LANIER-1",
                    "payload_json": {},
                    "result_json": {},
                    "due_at": None,
                        "created_at": None,
                        "updated_at": None,
                        "completed_at": None,
                    }
                    ,
                    {
                        "workflow_ref": "8f49ef3f-eafb-4378-94e1-0db73738f100",
                        "action_type": "proactive_outreach",
                        "status": "ready",
                        "priority": "medium",
                        "property_code": "LANIER-1",
                        "payload_json": {},
                        "result_json": {},
                        "due_at": None,
                        "created_at": None,
                        "updated_at": None,
                        "completed_at": None,
                    }
                    ,
                    {
                        "workflow_ref": "8f49ef3f-eafb-4378-94e1-0db73738f100",
                        "action_type": "owner_internal_update",
                        "status": "ready",
                        "priority": "medium",
                        "property_code": "LANIER-1",
                        "payload_json": {},
                        "result_json": {},
                        "due_at": None,
                        "created_at": None,
                        "updated_at": None,
                        "completed_at": None,
                    }
                ]),
            ]
        )
    row = {
        "session_id": "8f49ef3f-eafb-4378-94e1-0db73738f100",
        "property_code": "LANIER-1",
        "guest_name": "Guest",
        "guest_phone": "+15555550000",
        "phase": "pre_arrival",
        "latest_message_content": "What time is check in?",
        "latest_message_intent": "arrival_question",
        "check_in": "2026-04-25",
        "check_out": "2026-04-29",
        "notification_count": 0,
        "open_escalations": 0,
    }
    workflow = {
        "phase": "pre_arrival",
        "guest_update_state": "idle",
        "journey": {},
        "proactive": {
            "eligible": True,
            "touch_type": "pre_arrival_welcome",
            "message": "Hi Guest - you're a few days out from arrival.",
            "receptiveness_score": 0.7,
            "cadence_bucket": "pre_arrival",
        },
        "vendor_eta_minutes": None,
    }

    with patch(
        "app.services.messaging_brain.proactive_trigger_adapter.build_stay_workflow_intent",
        new_callable=AsyncMock,
    ) as mock_build, patch(
        "app.services.messaging_brain.proactive_trigger_adapter.compose_proactive_draft",
        new_callable=AsyncMock,
    ) as mock_compose:
        mock_build.return_value = object()
        mock_compose.return_value = type("Draft", (), {"response_text": "brain proactive text"})()
        actions = asyncio.run(
            agent.sync_actions(
                db,
                "00000000-0000-0000-0000-000000000001",
                row,
                workflow,
            )
        )

    upserts = [sql for sql, _ in db.executed if "INSERT INTO operator_workflow_action_queue" in sql]
    assert len(upserts) == 3


def test_sync_actions_prefers_brain_proactive_message_when_available():
    agent = StayActionAgent()
    db = _FakeSession(
        [
            ("scalar", True),
            ("scalar", False),
            ("mappings", []),
            ("ok", None),
            ("scalar", True),
            ("mappings", []),
        ]
    )
    row = {
        "session_id": "8f49ef3f-eafb-4378-94e1-0db73738f100",
        "property_code": "LANIER-1",
        "property_name": "Lanier",
        "guest_name": "Guest",
        "guest_phone": "+15555550000",
        "phase": "pre_arrival",
    }
    workflow = {
        "phase": "pre_arrival",
        "journey": {},
        "proactive": {
            "eligible": True,
            "touch_type": "pre_arrival_welcome",
            "message": "legacy helper text",
            "receptiveness_score": 0.7,
            "cadence_bucket": "pre_arrival",
        },
        "intelligence_context": {},
    }

    with patch(
        "app.services.messaging_brain.proactive_trigger_adapter.build_stay_workflow_intent",
        new_callable=AsyncMock,
    ) as mock_build, patch(
        "app.services.messaging_brain.proactive_trigger_adapter.compose_proactive_draft",
        new_callable=AsyncMock,
    ) as mock_compose:
        mock_build.return_value = object()
        mock_compose.return_value = type("Draft", (), {"response_text": "brain proactive text"})()
        asyncio.run(
            agent.sync_actions(
                db,
                "00000000-0000-0000-0000-000000000001",
                row,
                workflow,
            )
        )

    inserts = [
        params
        for sql, params in db.executed
        if "INSERT INTO operator_workflow_action_queue" in sql
    ]
    proactive_payload = next(item for item in inserts if item.get("action_type") == "proactive_outreach")
    payload = json.loads(proactive_payload["payload_json"])
    assert payload["message_text"] == "brain proactive text"


def test_sync_actions_adds_reactive_guest_status_response_for_open_escalation():
    agent = StayActionAgent()
    db = _FakeSession(
        [
            ("scalar", True),   # action queue exists
            ("scalar", False),  # vendors exists
            ("mappings", []),   # existing actions
            ("ok", None),       # guest_status_response upsert
            ("ok", None),       # proactive_outreach upsert
            ("ok", None),       # ops review upsert
            ("ok", None),       # owner/internal upsert
            ("scalar", True),   # list_actions table exists
            ("mappings", [
                {
                    "workflow_ref": "8f49ef3f-eafb-4378-94e1-0db73738f100",
                    "action_type": "guest_status_response",
                    "status": "ready",
                    "priority": "high",
                    "property_code": "LANIER-1",
                    "payload_json": {},
                    "result_json": {},
                    "due_at": None,
                    "created_at": None,
                    "updated_at": None,
                    "completed_at": None,
                }
            ]),
        ]
    )
    row = {
        "session_id": "8f49ef3f-eafb-4378-94e1-0db73738f100",
        "property_code": "LANIER-1",
        "property_name": "Lanier",
        "guest_name": "Guest",
        "guest_phone": "+15555550000",
        "phase": "in_stay",
        "latest_message_content": "Any update on where things stand?",
        "latest_message_intent": "guest_issue",
        "latest_message_direction": "inbound",
        "notification_count": 1,
        "open_escalations": 1,
        "token": "sess-1",
    }
    workflow = {
        "phase": "in_stay",
        "guest_update_state": "awaiting_operator",
        "journey": {},
        "proactive": {
            "eligible": False,
            "touch_type": None,
            "message": None,
            "receptiveness_score": 0.2,
            "cadence_bucket": "in_stay",
        },
        "vendor_eta_minutes": None,
    }

    actions = asyncio.run(
        agent.sync_actions(
            db,
            "00000000-0000-0000-0000-000000000001",
            row,
            workflow,
        )
    )

    upserts = [
        params.get("action_type")
        for sql, params in db.executed
        if "INSERT INTO operator_workflow_action_queue" in sql
    ]
    assert "guest_status_response" in upserts
    assert "ops_review" in upserts
    assert isinstance(actions, list)


def test_sync_actions_skips_archived_stays():
    agent = StayActionAgent()
    db = _FakeSession(
        [
            ("scalar", True),
        ]
    )
    row = {
        "session_id": "8f49ef3f-eafb-4378-94e1-0db73738f100",
        "property_code": "LANIER-1",
        "guest_name": "Guest",
        "phase": "post_stay",
    }
    workflow = {
        "phase": "post_stay",
        "operational_state": "archived",
    }

    actions = asyncio.run(
        agent.sync_actions(
            db,
            "00000000-0000-0000-0000-000000000001",
            row,
            workflow,
        )
    )

    assert actions == []
    assert not any("INSERT INTO operator_workflow_action_queue" in sql for sql, _ in db.executed)


def test_update_dispatch_state_tracks_vendor_lifecycle_metadata():
    agent = StayActionAgent()
    db = _FakeSession(
        [
            ("scalar", True),
            ("mappings", [
                {
                    "workflow_json": {
                        "vendor": {
                            "name": "Old Vendor",
                            "dispatch_state": "contacted",
                            "replacement_count": 0,
                        }
                    }
                }
            ]),
            ("ok", None),
        ]
    )

    asyncio.run(
        agent.update_dispatch_state(
            db,
            "00000000-0000-0000-0000-000000000001",
            "8f49ef3f-eafb-4378-94e1-0db73738f100",
            vendor_patch={
                "name": "New Vendor",
                "dispatch_state": "scheduled",
            },
            vendor_event={
                "changed_by": "ops@example.com",
                "replace_existing": True,
                "note": "Swapped to backup vendor",
            },
        )
    )

    _, params = next((entry for entry in reversed(db.executed) if "workflow_json" in entry[1]), ("", {}))
    workflow = json.loads(params["workflow_json"])
    assert workflow["vendor"]["previous_dispatch_state"] == "contacted"
    assert workflow["vendor"]["status_changed_by"] == "ops@example.com"
    assert workflow["vendor"]["replacement_count"] == 1
    assert workflow["vendor"]["last_transition_note"] == "Swapped to backup vendor"


def test_sync_actions_adds_walkthrough_review_when_required():
    agent = StayActionAgent()
    db = _FakeSession(
        [
            ("scalar", True),   # action queue exists
            ("scalar", False),  # vendors exists
            ("mappings", []),   # existing actions
            ("ok", None),       # walkthrough upsert
            ("scalar", True),   # list_actions table exists
            ("mappings", [
                {
                    "workflow_ref": "8f49ef3f-eafb-4378-94e1-0db73738f100",
                    "action_type": "post_checkout_walkthrough",
                    "status": "ready",
                    "priority": "medium",
                    "property_code": "LANIER-1",
                    "payload_json": {},
                    "result_json": {},
                    "due_at": None,
                    "created_at": None,
                    "updated_at": None,
                    "completed_at": None,
                }
            ]),
        ]
    )
    row = {
        "session_id": "8f49ef3f-eafb-4378-94e1-0db73738f100",
        "property_code": "LANIER-1",
        "guest_name": "Guest",
        "phase": "post_stay",
        "open_escalations": 0,
    }
    workflow = {
        "phase": "post_stay",
        "guest_update_state": "idle",
        "journey": {},
        "proactive": {"eligible": False},
        "operations": {
            "modules": {
                "turnover_workflows": True,
                "maintenance_workflows": True,
            },
            "tasks": [
                {
                    "key": "post_checkout_walkthrough",
                    "status": "pending",
                }
            ],
        },
    }

    actions = asyncio.run(
        agent.sync_actions(
            db,
            "00000000-0000-0000-0000-000000000001",
            row,
            workflow,
        )
    )

    upserts = [
        params.get("action_type")
        for sql, params in db.executed
        if "INSERT INTO operator_workflow_action_queue" in sql
    ]
    assert "post_checkout_walkthrough" in upserts
    assert isinstance(actions, list)


def test_execute_guest_eta_update_blocks_without_eta():
    agent = StayActionAgent()
    db = _FakeSession(
        [
            ("scalar", True),
            ("mappings", [
                {
                    "action_type": "guest_eta_update",
                    "status": "ready",
                    "payload_json": {"guest_phone": "+15555550000", "vendor_name": "Cleaner", "eta_minutes": None},
                    "result_json": {},
                    "session_id": "8f49ef3f-eafb-4378-94e1-0db73738f100",
                    "token": "sess-1",
                    "property_id": None,
                    "property_code": "LANIER-1",
                    "property_name": "Lanier",
                    "guest_name": "Guest",
                    "guest_phone": "+15555550000",
                    "guest_email": None,
                    "phase": "departure_day",
                    "status": "active",
                    "check_in": None,
                    "check_out": None,
                }
            ]),
            ("ok", None),
            ("ok", None),
        ]
    )

    result = asyncio.run(
        agent.execute_action(
            db,
            "00000000-0000-0000-0000-000000000001",
            "8f49ef3f-eafb-4378-94e1-0db73738f100",
            "guest_eta_update",
            actor_label="ops@lanier.com",
        )
    )

    assert result["status"] == "blocked"
