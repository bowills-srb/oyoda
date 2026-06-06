from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone

from app.services.operator.stay_detector_service import StayDetectorService
from app.services.operator.stay_proactive_service import StayProactiveService
from app.services.operator.stay_receptiveness_service import StayReceptivenessService
from app.services.operator.stay_workflow_service import StayWorkflowService


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
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, statement, params=None):
        self.executed.append((str(statement), params or {}))
        if not self.scripted:
            return _FakeMappingsResult([])
        kind, payload = self.scripted.pop(0)
        if kind == "mappings":
            return _FakeMappingsResult(payload)
        if kind == "ok":
            return _FakeMappingsResult([])
        raise AssertionError(f"Unknown action: {kind}")

    async def scalar(self, statement, params=None):
        self.executed.append((str(statement), params or {}))
        kind, payload = self.scripted.pop(0)
        assert kind == "scalar"
        return payload

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


def test_stay_detector_marks_arrival_and_turnover_and_accounting_paths():
    service = StayDetectorService()
    row = {
        "phase": "arrival_day",
        "latest_message_content": "We can't get in, the code does not work and we may need a refund",
        "latest_message_intent": "guest_issue",
        "open_escalations": 1,
    }
    workflow = {
        "phase": "arrival_day",
        "guest_update_state": "awaiting_operator",
        "vendor_eta_minutes": None,
    }

    signals = service.detect(row, workflow)

    assert signals["arrival_issue"] is True
    assert signals["ops_review_needed"] is True
    assert signals["owner_internal_update_needed"] is True
    assert signals["accounting_claim_handoff_needed"] is True


def test_stay_proactive_service_recommends_pre_arrival_welcome():
    service = StayProactiveService()
    row = {
        "phase": "pre_arrival",
        "guest_name": "Guest Example",
        "property_name": "Lanier",
        "conversation_count": 0,
        "notification_count": 0,
        "open_escalations": 0,
        "latest_message_direction": None,
        "latest_message_created_at": None,
        "check_in": "2026-04-25",
        "check_out": "2026-04-29",
        "property_context": {"wifi_name": "LanierWiFi"},
    }
    workflow = {"phase": "pre_arrival", "guest_update_state": "idle", "journey": {}}

    proactive = service.evaluate(row, workflow)

    assert proactive["eligible"] is True
    assert proactive["touch_type"] == "pre_arrival_welcome"
    assert proactive["backoff_active"] is False


def test_stay_proactive_service_uses_unified_intelligence_context_in_message():
    service = StayProactiveService()
    row = {
        "phase": "pre_arrival",
        "guest_name": "Guest Example",
        "property_name": "Lanier",
        "conversation_count": 0,
        "notification_count": 0,
        "open_escalations": 0,
        "latest_message_direction": None,
        "latest_message_created_at": None,
        "check_in": "2026-04-25",
        "check_out": "2026-04-29",
        "property_context": {"wifi_name": "LanierWiFi"},
    }
    workflow = {
        "phase": "pre_arrival",
        "guest_update_state": "idle",
        "journey": {},
        "intelligence_context": {
            "market_brain": {
                "live_conditions": ["Weather: Tonight | 31F | Snow showers likely"],
                "active_alerts": ["Winter Weather Advisory"],
                "upcoming_events": ["Food & Wine Classic at Wagner Park on 2026-06-14"],
            }
        },
    }

    proactive = service.evaluate(row, workflow)

    assert proactive["eligible"] is True
    assert "Winter Weather Advisory" in (proactive["message"] or "")


def test_stay_proactive_service_switches_to_controlled_service_updates_for_open_escalation():
    service = StayProactiveService()
    row = {
        "phase": "in_stay",
        "guest_name": "Guest Example",
        "property_name": "Lanier",
        "conversation_count": 3,
        "notification_count": 1,
        "open_escalations": 1,
        "latest_message_direction": "inbound",
        "latest_message_created_at": "2026-04-22T10:00:00+00:00",
        "check_in": "2026-04-20",
        "check_out": "2026-04-25",
        "proactive_triggered_at": None,
    }
    workflow = {"phase": "in_stay", "guest_update_state": "idle", "journey": {}}

    proactive = service.evaluate(row, workflow)

    assert proactive["eligible"] is True
    assert proactive["touch_type"] == "service_update_reassurance"
    assert proactive["suppression_mode"] == "soft"
    assert proactive["allowed_touch_family"] == "service_updates_only"


def test_stay_proactive_service_hard_suppresses_when_operator_update_is_pending():
    service = StayProactiveService()
    row = {
        "phase": "in_stay",
        "guest_name": "Guest Example",
        "property_name": "Lanier",
        "conversation_count": 3,
        "notification_count": 1,
        "open_escalations": 1,
        "latest_message_direction": "inbound",
        "latest_message_created_at": "2026-04-22T10:00:00+00:00",
        "check_in": "2026-04-20",
        "check_out": "2026-04-25",
    }
    workflow = {"phase": "in_stay", "guest_update_state": "awaiting_operator", "journey": {}}

    proactive = service.evaluate(row, workflow)

    assert proactive["eligible"] is False
    assert proactive["suppression_mode"] == "hard"
    assert proactive["suppression_scope"] == "proactive_only"
    assert proactive["allowed_touch_family"] == "none"
    assert proactive["backoff_reason"] == "waiting_on_operator"


def test_stay_receptiveness_service_marks_fatigue_when_guest_is_not_replying():
    service = StayReceptivenessService()
    row = {
        "recent_outbound_count": 4,
        "recent_inbound_count": 0,
        "consecutive_outbound_without_reply": 3,
        "notification_count": 6,
        "open_escalations": 0,
        "latest_message_direction": "outbound",
    }

    result = service.evaluate(row, {})

    assert result["fatigue_state"] == "high"
    assert result["should_backoff_proactive"] is True
    assert "multiple_outbound_without_reply" in result["evidence"]


def test_stay_receptiveness_service_allows_more_prearrival_silence():
    service = StayReceptivenessService()
    row = {
        "phase": "pre_arrival",
        "recent_outbound_count": 2,
        "recent_inbound_count": 0,
        "consecutive_outbound_without_reply": 2,
        "notification_count": 2,
        "open_escalations": 0,
        "latest_message_direction": "outbound",
    }

    result = service.evaluate(row, {"phase": "pre_arrival"})

    assert result["should_backoff_proactive"] is False
    assert result["backoff_thresholds"]["pending_outbound"] == 4
    assert "prearrival_concierge_allowance" in result["evidence"]


def test_build_workflow_preserves_existing_vendor_dispatch_state():
    service = StayWorkflowService()
    row = {
        "session_id": "8f49ef3f-eafb-4378-94e1-0db73738f100",
        "token": "sess-1",
        "property_code": "LANIER-1",
        "property_name": "Lanier",
        "guest_name": "Guest",
        "status": "active",
        "phase": "in_stay",
        "open_escalations": 1,
        "notification_count": 1,
        "latest_message_content": "The AC is not working",
        "latest_message_intent": "maintenance_issue",
        "latest_message_direction": "inbound",
        "latest_message_created_at": datetime(2026, 4, 22, tzinfo=timezone.utc),
        "last_message_at": datetime(2026, 4, 22, tzinfo=timezone.utc),
        "check_in": date(2026, 4, 20),
        "check_out": date(2026, 4, 25),
    }
    existing = {
        "vendor": {
            "name": "Lanier HVAC",
            "phone": "555-1212",
            "dispatch_state": "en_route",
            "eta_minutes": 35,
            "selected_vendor_id": "vendor-1",
            "status_changed_at": "2026-04-22T10:00:00+00:00",
            "replacement_count": 1,
        },
        "guest_update": {
            "status": "sent_to_guest",
        },
        "vendor_history": [{"vendor_status": "scheduled"}],
    }

    workflow = service._build_workflow(row, existing)

    assert workflow["vendor"]["name"] == "Lanier HVAC"
    assert workflow["vendor"]["dispatch_state"] == "en_route"
    assert workflow["vendor_eta_minutes"] == 35
    assert workflow["vendor"]["status_changed_at"] == "2026-04-22T10:00:00+00:00"
    assert workflow["vendor"]["replacement_count"] == 1
    assert workflow["vendor_history"] == [{"vendor_status": "scheduled"}]


def test_build_workflow_enters_turnover_state_for_post_stay_sessions():
    service = StayWorkflowService()
    row = {
        "session_id": "8f49ef3f-eafb-4378-94e1-0db73738f100",
        "token": "sess-1",
        "property_code": "LANIER-1",
        "property_name": "Lanier",
        "guest_name": "Guest",
        "status": "active",
        "phase": "post_stay",
        "open_escalations": 0,
        "notification_count": 0,
        "latest_message_content": None,
        "latest_message_intent": None,
        "latest_message_direction": None,
        "latest_message_created_at": None,
        "last_message_at": datetime(2026, 4, 26, tzinfo=timezone.utc),
        "check_in": date(2026, 4, 20),
        "check_out": date(2026, 4, 25),
    }

    workflow = service._build_workflow(row)

    assert workflow["stage"] == "turnover_in_progress"
    assert workflow["operational_state"] == "active"
    assert workflow["turnover"]["status"] == "pending"
    assert workflow["turnover"]["ready_for_next_guest"] is False


def test_build_workflow_archives_when_turnover_is_ready():
    service = StayWorkflowService()
    row = {
        "session_id": "8f49ef3f-eafb-4378-94e1-0db73738f100",
        "token": "sess-1",
        "property_code": "LANIER-1",
        "property_name": "Lanier",
        "guest_name": "Guest",
        "status": "active",
        "phase": "post_stay",
        "open_escalations": 0,
        "notification_count": 0,
        "latest_message_content": None,
        "latest_message_intent": None,
        "latest_message_direction": None,
        "latest_message_created_at": None,
        "last_message_at": datetime(2026, 4, 26, tzinfo=timezone.utc),
        "check_in": date(2026, 4, 20),
        "check_out": date(2026, 4, 25),
    }
    existing = {
        "turnover": {
            "status": "ready",
            "ready_at": "2026-04-25T18:00:00+00:00",
        }
    }

    workflow = service._build_workflow(row, existing)

    assert workflow["stage"] == "archived"
    assert workflow["operational_state"] == "archived"
    assert workflow["archive_eligible"] is True
    assert workflow["turnover"]["ready_for_next_guest"] is True


def test_apply_event_summary_marks_property_ready_and_documentation_complete():
    service = StayWorkflowService()
    workflow = {
        "phase": "post_stay",
        "turnover": {"status": "pending", "ready_for_next_guest": False},
        "walkthrough": {"status": "pending", "required": True},
        "events": {
            "property_ready_at": "2026-04-22T16:00:00+00:00",
            "documentation_started_at": "2026-04-22T15:00:00+00:00",
            "documentation_completed_at": "2026-04-22T15:30:00+00:00",
            "housekeeping_arrived_at": "2026-04-22T14:00:00+00:00",
            "housekeeping_completed_at": "2026-04-22T15:00:00+00:00",
        },
    }

    service._apply_event_summary(workflow)

    assert workflow["turnover"]["status"] == "ready"
    assert workflow["turnover"]["ready_for_next_guest"] is True
    assert workflow["walkthrough"]["status"] == "completed"
    assert workflow["walkthrough"]["completed_at"] == "2026-04-22T15:30:00+00:00"


def test_apply_operational_rules_requires_walkthrough_before_archive():
    service = StayWorkflowService()
    workflow = {
        "phase": "post_stay",
        "stage": "archived",
        "open_escalations": 0,
        "turnover": {"status": "ready", "ready_for_next_guest": True},
        "walkthrough": {"status": "pending"},
        "operations": {
            "modules": {
                "turnover_workflows": True,
                "post_checkout_walkthrough": True,
                "walkthrough_required_before_ready": True,
                "auto_archive_when_turnover_ready": True,
            }
        },
        "handoffs": {"items": []},
    }

    service._apply_operational_rules({"phase": "post_stay", "open_escalations": 0}, workflow)

    assert workflow["stage"] == "turnover_in_progress"
    assert workflow["operational_state"] == "active"
    assert workflow["archive_eligible"] is False
    assert workflow["walkthrough"]["status"] == "pending"


def test_apply_operational_rules_archives_post_stay_when_turnover_tracking_disabled():
    service = StayWorkflowService()
    workflow = {
        "phase": "post_stay",
        "stage": "post_stay_followup",
        "open_escalations": 0,
        "turnover": {"status": "pending", "ready_for_next_guest": False},
        "walkthrough": {"status": "not_required"},
        "operations": {
            "modules": {
                "turnover_workflows": False,
                "post_checkout_walkthrough": False,
                "walkthrough_required_before_ready": False,
                "auto_archive_when_turnover_ready": True,
            }
        },
        "handoffs": {"items": []},
    }

    service._apply_operational_rules({"phase": "post_stay", "open_escalations": 0}, workflow)

    assert workflow["stage"] == "archived"
    assert workflow["operational_state"] == "archived"
    assert workflow["turnover"]["status"] == "not_tracked"


def test_stay_proactive_service_respects_policy_disabled_touch_types():
    service = StayProactiveService()
    row = {
        "phase": "pre_arrival",
        "guest_name": "Guest Example",
        "property_name": "Lanier",
        "conversation_count": 0,
        "notification_count": 0,
        "open_escalations": 0,
        "latest_message_direction": None,
        "latest_message_created_at": None,
        "check_in": "2026-04-25",
        "check_out": "2026-04-29",
    }
    workflow = {
        "phase": "pre_arrival",
        "guest_update_state": "idle",
        "journey": {},
        "policy": {"proactive": {"enabled_touch_types": ["arrival_info"]}},
    }

    proactive = service.evaluate(row, workflow)

    assert proactive["eligible"] is False
    assert proactive["touch_type"] is None


def test_stay_proactive_service_uses_receptiveness_memory_for_backoff():
    service = StayProactiveService()
    row = {
        "phase": "pre_arrival",
        "guest_name": "Guest Example",
        "property_name": "Lanier",
        "conversation_count": 0,
        "notification_count": 0,
        "open_escalations": 0,
        "latest_message_direction": None,
        "latest_message_created_at": None,
        "check_in": "2026-04-25",
        "check_out": "2026-04-29",
    }
    workflow = {
        "phase": "pre_arrival",
        "guest_update_state": "idle",
        "journey": {},
        "receptiveness": {"score": 0.18, "should_backoff_proactive": True, "fatigue_state": "high"},
    }

    proactive = service.evaluate(row, workflow)

    assert proactive["eligible"] is False
    assert proactive["backoff_reason"] == "guest_contact_fatigue"
    assert proactive["suppression_mode"] == "hard"


def test_stay_proactive_service_can_disable_service_updates_during_escalation():
    service = StayProactiveService()
    row = {
        "phase": "in_stay",
        "guest_name": "Guest Example",
        "property_name": "Lanier",
        "conversation_count": 3,
        "notification_count": 1,
        "open_escalations": 1,
        "latest_message_direction": "inbound",
        "latest_message_created_at": "2026-04-22T10:00:00+00:00",
        "check_in": "2026-04-20",
        "check_out": "2026-04-25",
        "proactive_triggered_at": None,
    }
    workflow = {
        "phase": "in_stay",
        "guest_update_state": "idle",
        "journey": {},
        "policy": {"proactive": {"allow_service_updates_during_escalation": False}},
    }

    proactive = service.evaluate(row, workflow)

    assert proactive["eligible"] is False
    assert proactive["suppression_mode"] == "hard"
    assert proactive["backoff_reason"] == "open_escalation_messages_disabled"


def test_stay_detector_requests_reactive_status_response_during_open_escalation():
    service = StayDetectorService()
    row = {
        "phase": "in_stay",
        "latest_message_content": "Any update on when someone will arrive?",
        "latest_message_intent": "guest_issue",
        "latest_message_direction": "inbound",
        "open_escalations": 1,
    }
    workflow = {
        "phase": "in_stay",
        "guest_update_state": "awaiting_operator",
        "vendor_eta_minutes": None,
    }

    signals = service.detect(row, workflow)

    assert signals["reactive_status_response_needed"] is True
    assert signals["reactive_response_type"] == "status_followup"
    assert "reactive_status_response_needed" in signals["evidence"]


def test_build_workflow_enters_issue_active_with_open_escalation():
    service = StayWorkflowService()
    row = {
        "session_id": "8f49ef3f-eafb-4378-94e1-0db73738f100",
        "token": "sess-1",
        "property_code": "LANIER-1",
        "property_name": "Lanier",
        "guest_name": "Guest",
        "status": "active",
        "phase": "in_stay",
        "open_escalations": 2,
        "notification_count": 1,
        "latest_message_content": "The AC is not working",
        "latest_message_intent": "maintenance_issue",
        "latest_message_direction": "inbound",
        "latest_message_created_at": datetime(2026, 4, 22, tzinfo=timezone.utc),
        "last_message_at": datetime(2026, 4, 22, tzinfo=timezone.utc),
        "check_in": date(2026, 4, 20),
        "check_out": date(2026, 4, 25),
    }

    workflow = service._build_workflow(row)

    assert workflow["stage"] == "issue_active"
    assert workflow["escalation_state"] == "open"
    assert workflow["guest_update_state"] == "awaiting_operator"


def test_sync_session_persists_read_model():
    service = StayWorkflowService()
    fake_db = _FakeSession(
        [
            ("scalar", True),   # has messages
            ("scalar", False),  # has journeys
            ("scalar", False),  # has notifications
            ("mappings", [
                {
                    "session_id": "8f49ef3f-eafb-4378-94e1-0db73738f100",
                    "token": "sess-1",
                    "property_id": None,
                    "property_code": "LANIER-1",
                    "property_name": "Lanier",
                    "guest_name": "Guest",
                    "guest_phone": "+15555550000",
                    "guest_email": None,
                    "status": "active",
                    "phase": "pre_arrival",
                    "check_in": date(2026, 4, 25),
                    "check_out": date(2026, 4, 29),
                    "conversation_count": 2,
                    "last_message_at": datetime(2026, 4, 22, tzinfo=timezone.utc),
                    "reservation_id": "RES-1",
                    "pms_synced_at": None,
                    "proactive_triggered_at": None,
                    "welcome_sent": False,
                    "checkin_reminder_sent": False,
                    "checkout_reminder_sent": False,
                    "extend_offer_sent": False,
                    "pool_heat_offered": False,
                    "pool_heat_accepted": False,
                    "notification_count": 0,
                    "open_escalations": 0,
                    "latest_message_content": "What time is check in?",
                    "latest_message_intent": "arrival_question",
                    "latest_message_direction": "inbound",
                    "latest_message_created_at": datetime(2026, 4, 22, tzinfo=timezone.utc),
                    "recent_outbound_count": 0,
                    "recent_inbound_count": 1,
                    "consecutive_outbound_without_reply": 0,
                }
            ]),
            ("scalar", True),   # read model exists
            ("scalar", True),   # existing workflow read model exists
            ("mappings", []),   # no existing workflow row
            ("mappings", []),   # settings row unavailable
            ("scalar", False),  # stay events table does not exist
            ("scalar", True),   # action queue exists
            ("scalar", False),  # vendors exists
            ("mappings", []),   # existing actions
            ("ok", None),       # upsert knowledge response
            ("ok", None),       # upsert owner/internal update
            ("scalar", True),   # list_actions table exists
            ("mappings", []),   # list actions return
            ("scalar", False),  # handoffs table does not exist
            ("ok", None),       # persist workflow
        ]
    )

    result = asyncio.run(
        service.sync_session(
            fake_db,
            "00000000-0000-0000-0000-000000000001",
            "8f49ef3f-eafb-4378-94e1-0db73738f100",
        )
    )

    assert result is True
    insert_sql, insert_params = fake_db.executed[-1]
    assert "operator_stay_workflow_read_models" in insert_sql
    assert insert_params["workflow_stage"] == "arrival_prep"
    assert fake_db.commits == 1
