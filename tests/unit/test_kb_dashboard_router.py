from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import operator_dashboard_api as dashboard_api


class _StubKbService:
    async def list_dashboard_entries(self, session, tenant_id, property_ref=None):
        return [
            {
                "id": "legacy-entry-1",
                "parent_id": "legacy-entry-1",
                "faq_index": 0,
                "question": "What time is check in?",
                "answer": "Check-in starts at 4 PM.",
                "confidence": 0.93,
                "category": "Check In",
                "usage_count": 0,
                "property_id": None,
                "property_label": "P-101",
                "source": "legacy_qna",
                "updated_at": None,
            }
        ]


async def _fake_session_dep():
    yield object()


class _FakeMappingsResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows


class _FakeScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value


class _DashboardDb:
    def __init__(self, scripted: list[tuple[str, Any]]):
        self.scripted = list(scripted)
        self.executed: list[tuple[str, dict]] = []

    async def execute(self, statement, params=None):
        sql = str(statement)
        payload = params or {}
        self.executed.append((sql, payload))
        kind, rows = self.scripted.pop(0)
        if kind == "mappings":
            return _FakeMappingsResult(rows)
        if kind == "scalar":
            return _FakeScalarResult(rows)
        raise AssertionError(f"Unknown scripted action: {kind}")

    async def rollback(self):
        return None


def test_kb_route_returns_stable_contract(monkeypatch):
    app = FastAPI()
    app.include_router(dashboard_api.router)
    app.dependency_overrides[dashboard_api.get_async_session] = _fake_session_dep

    monkeypatch.setattr(
        dashboard_api,
        "_require_context",
        lambda _request: {
            "operator_id": "op-test",
            "tenant_id": "00000000-0000-0000-0000-000000000001",
            "role": "owner",
            "email": "owner@example.com",
        },
    )
    monkeypatch.setattr(
        dashboard_api,
        "get_dashboard_kb_service",
        lambda: _StubKbService(),
    )

    client = TestClient(app)
    response = client.get("/app/api/kb")

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["entries"][0]["id"] == "legacy-entry-1"
    assert payload["entries"][0]["property_label"] == "P-101"
    assert payload["entries"][0]["source"] == "legacy_qna"


async def _boom(*args, **kwargs):
    raise RuntimeError("simulated onboarding failure")


def test_onboarding_status_returns_degraded_contract_on_failure(monkeypatch):
    app = FastAPI()
    app.include_router(dashboard_api.router)
    app.dependency_overrides[dashboard_api.get_async_session] = _fake_session_dep

    monkeypatch.setattr(
        dashboard_api,
        "_require_context",
        lambda _request: {
            "operator_id": "op-test",
            "tenant_id": "00000000-0000-0000-0000-000000000001",
            "role": "owner",
            "email": "owner@example.com",
        },
    )
    monkeypatch.setattr(dashboard_api, "_first_gmail_credential_row", _boom)

    client = TestClient(app)
    response = client.get("/app/api/onboarding-status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["degraded"] is True
    assert payload["inbox_connected"] is False
    assert payload["critical_incomplete"]["key"] == "connect_inbox"
    assert len(payload["steps"]) == 3


def test_onboarding_status_marks_first_inquiry_as_hidden_milestone(monkeypatch):
    app = FastAPI()
    app.include_router(dashboard_api.router)
    app.dependency_overrides[dashboard_api.get_async_session] = _fake_session_dep

    monkeypatch.setattr(
        dashboard_api,
        "_require_context",
        lambda _request: {
            "operator_id": "op-test",
            "tenant_id": "00000000-0000-0000-0000-000000000001",
            "role": "owner",
            "email": "owner@example.com",
        },
    )
    async def _no_gmail(*_args, **_kwargs):
        return None

    async def _property_meta(*_args, **_kwargs):
        return {"where_sql": "TRUE"}

    monkeypatch.setattr(dashboard_api, "_first_gmail_credential_row", _no_gmail)
    monkeypatch.setattr(dashboard_api, "_property_query_meta", _property_meta)

    class _FakeResult:
        def __init__(self, scalar=None, row=None):
            self._scalar = scalar
            self._row = row

        def scalar(self):
            return self._scalar

        def fetchone(self):
            return self._row

    class _OnboardingDb:
        async def execute(self, statement, params=None):
            sql = str(statement)
            if "SELECT COUNT(*) FROM properties" in sql:
                return _FakeResult(scalar=3)
            if "information_schema.columns" in sql and "property_ai_autonomy" in sql:
                return _FakeResult(row=None)
            if "SELECT MIN(received_at) AS first_received" in sql:
                from datetime import datetime, timezone
                return _FakeResult(row=(datetime(2026, 4, 1, tzinfo=timezone.utc),))
            if "information_schema.columns" in sql:
                class _Cols:
                    def fetchall(self):
                        return []
                return _Cols()
            raise AssertionError(sql)

        async def rollback(self):
            return None

    async def _fake_onboarding_session():
        yield _OnboardingDb()

    app.dependency_overrides[dashboard_api.get_async_session] = _fake_onboarding_session

    client = TestClient(app)
    response = client.get("/app/api/onboarding-status")

    assert response.status_code == 200
    payload = response.json()
    milestone = next(step for step in payload["steps"] if step["key"] == "first_inquiry")
    assert milestone["type"] == "milestone"
    assert milestone["visible_when_complete"] is False


def test_onboarding_status_uses_operator_account_inbox_fallback(monkeypatch):
    app = FastAPI()
    app.include_router(dashboard_api.router)

    monkeypatch.setattr(
        dashboard_api,
        "_require_context",
        lambda _request: {
            "operator_id": "op-test",
            "tenant_id": "00000000-0000-0000-0000-000000000001",
            "role": "owner",
            "email": "owner@example.com",
        },
    )

    async def _no_gmail(*_args, **_kwargs):
        return None

    async def _account_row(*_args, **_kwargs):
        return {
            "messaging_email": "lanier@example.com",
            "email": "owner@example.com",
            "email_provider": "google",
        }

    async def _property_meta(*_args, **_kwargs):
        return {"where_sql": "TRUE"}

    monkeypatch.setattr(dashboard_api, "_first_gmail_credential_row", _no_gmail)
    monkeypatch.setattr(dashboard_api, "_operator_inbox_account_row", _account_row)
    monkeypatch.setattr(dashboard_api, "_property_query_meta", _property_meta)

    class _FakeResult:
        def __init__(self, scalar=None, row=None):
            self._scalar = scalar
            self._row = row

        def scalar(self):
            return self._scalar

        def fetchone(self):
            return self._row

    class _OnboardingDb:
        async def execute(self, statement, params=None):
            sql = str(statement)
            if "SELECT COUNT(*) FROM properties" in sql:
                return _FakeResult(scalar=0)
            if "information_schema.columns" in sql:
                class _Cols:
                    def fetchall(self):
                        return []
                return _Cols()
            if "SELECT MIN(received_at) AS first_received" in sql:
                return _FakeResult(row=(None,))
            raise AssertionError(sql)

        async def rollback(self):
            return None

    async def _fake_onboarding_session():
        yield _OnboardingDb()

    app.dependency_overrides[dashboard_api.get_async_session] = _fake_onboarding_session

    client = TestClient(app)
    response = client.get("/app/api/onboarding-status")

    assert response.status_code == 200
    payload = response.json()
    connect_step = next(step for step in payload["steps"] if step["key"] == "connect_inbox")
    assert payload["inbox_connected"] is False
    assert payload["inbox_status"]["email"] == "lanier@example.com"
    assert connect_step["done"] is False


def test_dashboard_summary_returns_degraded_contract_on_failure(monkeypatch):
    app = FastAPI()
    app.include_router(dashboard_api.router)
    app.dependency_overrides[dashboard_api.get_async_session] = _fake_session_dep

    monkeypatch.setattr(
        dashboard_api,
        "_require_context",
        lambda _request: {
            "operator_id": "op-test",
            "tenant_id": "00000000-0000-0000-0000-000000000001",
            "role": "owner",
            "email": "owner@example.com",
        },
    )
    monkeypatch.setattr(dashboard_api, "_property_query_meta", _boom)

    client = TestClient(app)
    response = client.get("/app/api/dashboard-summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["degraded"] is True
    assert payload["sessions"]["active"] == 0
    assert payload["pre_booking"]["pending"] == 0
    assert payload["inbox"]["connected"] is False


def test_dashboard_summary_passes_scope_codes_to_summary_service(monkeypatch):
    app = FastAPI()
    app.include_router(dashboard_api.router)
    app.dependency_overrides[dashboard_api.get_async_session] = _fake_session_dep
    captured: dict[str, Any] = {}

    monkeypatch.setattr(
        dashboard_api,
        "_require_context",
        lambda _request: {
            "operator_id": "op-test",
            "tenant_id": "00000000-0000-0000-0000-000000000001",
            "role": "staff",
            "email": "owner@example.com",
        },
    )

    async def _fake_scope_profile(*_args, **_kwargs):
        return {
            "visible_property_codes": {"PROP-2", "PROP-1"},
            "can_assign": False,
            "can_manage_vendors": False,
            "can_manage_settings": False,
            "has_scopes": True,
        }

    async def _fake_property_meta(*_args, **_kwargs):
        return {"where_sql": "TRUE", "code_expr": "property_code"}

    async def _fake_inbox_row(*_args, **_kwargs):
        return None

    async def _fake_table_columns(*_args, **_kwargs):
        return []

    async def _fake_build_summary(*_args, **kwargs):
        captured["visible_property_codes"] = kwargs.get("visible_property_codes")
        return {
            "sessions": {"active": 1, "in_stay": 0, "arriving": 0, "total_30d": 1},
            "pre_booking": {"pending": 0, "replied_30d": 0, "total_30d": 0},
            "escalations": {"open": 0, "resolved_30d": 0},
            "properties": 2,
            "kb_entries": 0,
            "kb_gaps": 0,
            "vendors": 0,
            "messages_30d": 0,
            "notifications_unread": 0,
            "inbox": {"connected": False},
            "degraded": False,
            "cache_source": "live",
        }

    class _FakeDashboardSummaryService:
        async def build_summary(self, *_args, **kwargs):
            return await _fake_build_summary(*_args, **kwargs)

    monkeypatch.setattr(dashboard_api, "_scope_profile", _fake_scope_profile)
    monkeypatch.setattr(dashboard_api, "_property_query_meta", _fake_property_meta)
    monkeypatch.setattr(dashboard_api, "_first_gmail_credential_row", _fake_inbox_row)
    monkeypatch.setattr(dashboard_api, "_table_columns", _fake_table_columns)
    monkeypatch.setattr(dashboard_api, "get_dashboard_summary_service", lambda: _FakeDashboardSummaryService())

    client = TestClient(app)
    response = client.get("/app/api/dashboard-summary")

    assert response.status_code == 200
    assert captured["visible_property_codes"] == ["PROP-1", "PROP-2"]
    assert response.json()["sessions"]["active"] == 1


def test_vendors_route_filters_to_scoped_properties(monkeypatch):
    app = FastAPI()
    app.include_router(dashboard_api.router)
    fake_db = _DashboardDb(
        [
            ("mappings", [
                {
                    "vendor_id": "11111111-1111-1111-1111-111111111111",
                    "category_slug": "maintenance",
                    "name": "Global HVAC",
                    "phone": "",
                    "website": "",
                    "ai_script": "",
                    "internal_notes": "",
                    "priority": 1,
                    "apply_scope": "all",
                    "property_ids": [],
                    "active": True,
                    "referral_count": 0,
                    "last_referred_at": None,
                    "created_at": None,
                    "updated_at": None,
                },
                {
                    "vendor_id": "22222222-2222-2222-2222-222222222222",
                    "category_slug": "maintenance",
                    "name": "Lanier HVAC",
                    "phone": "",
                    "website": "",
                    "ai_script": "",
                    "internal_notes": "",
                    "priority": 2,
                    "apply_scope": "property",
                    "property_ids": ["prop-lanier"],
                    "active": True,
                    "referral_count": 0,
                    "last_referred_at": None,
                    "created_at": None,
                    "updated_at": None,
                },
                {
                    "vendor_id": "33333333-3333-3333-3333-333333333333",
                    "category_slug": "maintenance",
                    "name": "Beach HVAC",
                    "phone": "",
                    "website": "",
                    "ai_script": "",
                    "internal_notes": "",
                    "priority": 3,
                    "apply_scope": "property",
                    "property_ids": ["prop-beach"],
                    "active": True,
                    "referral_count": 0,
                    "last_referred_at": None,
                    "created_at": None,
                    "updated_at": None,
                },
            ]),
        ]
    )

    async def _fake_vendor_session():
        yield fake_db

    app.dependency_overrides[dashboard_api.get_async_session] = _fake_vendor_session

    monkeypatch.setattr(
        dashboard_api,
        "_require_context",
        lambda _request: {
            "operator_id": "member-1",
            "tenant_id": "00000000-0000-0000-0000-000000000001",
            "role": "staff",
            "email": "staff@example.com",
        },
    )

    async def _scope(*_args, **_kwargs):
        return {
            "visible_property_codes": {"LANIER-1"},
            "can_assign": False,
            "can_manage_vendors": False,
            "can_manage_settings": False,
        }

    async def _visible_ids(*_args, **_kwargs):
        return {"prop-lanier": "LANIER-1"}

    monkeypatch.setattr(dashboard_api, "_scope_profile", _scope)
    monkeypatch.setattr(dashboard_api, "_visible_property_id_map", _visible_ids)

    client = TestClient(app)
    response = client.get("/app/api/vendors")

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 2
    names = [item["name"] for item in payload["vendors"]]
    assert names == ["Global HVAC", "Lanier HVAC"]


def test_create_vendor_requires_scope_vendor_permission(monkeypatch):
    app = FastAPI()
    app.include_router(dashboard_api.router)
    app.dependency_overrides[dashboard_api.get_async_session] = _fake_session_dep

    monkeypatch.setattr(
        dashboard_api,
        "_require_context",
        lambda _request: {
            "operator_id": "member-1",
            "tenant_id": "00000000-0000-0000-0000-000000000001",
            "role": "staff",
            "email": "staff@example.com",
        },
    )

    async def _scope(*_args, **_kwargs):
        return {
            "visible_property_codes": {"LANIER-1"},
            "can_assign": False,
            "can_manage_vendors": False,
            "can_manage_settings": False,
        }

    monkeypatch.setattr(dashboard_api, "_scope_profile", _scope)

    client = TestClient(app)
    response = client.post(
        "/app/api/vendors",
        json={"name": "Scoped HVAC", "category_slug": "maintenance", "apply_scope": "property", "property_ids": ["prop-lanier"]},
    )

    assert response.status_code == 403
    assert "permission" in response.json()["detail"].lower()


def test_escalations_route_applies_scoped_property_filter(monkeypatch):
    app = FastAPI()
    app.include_router(dashboard_api.router)
    fake_db = _DashboardDb(
        [
            ("mappings", [("watchers",), ("watchers_notified_at",), ("vendor_name",), ("vendor_phone",), ("vendor_eta_minutes",), ("vendor_status",), ("guest_updated_at",), ("guest_update_status",), ("guest_update_due_at",), ("guest_update_note",)]),
            ("mappings", [("session_id",), ("direction",), ("content",), ("created_at",)]),
            ("mappings", []),
            ("mappings", []),
        ]
    )

    async def _fake_escalation_session():
        yield fake_db

    app.dependency_overrides[dashboard_api.get_async_session] = _fake_escalation_session

    monkeypatch.setattr(
        dashboard_api,
        "_require_context",
        lambda _request: {
            "operator_id": "member-1",
            "tenant_id": "00000000-0000-0000-0000-000000000001",
            "role": "staff",
            "email": "staff@example.com",
        },
    )

    async def _scope(*_args, **_kwargs):
        return {
            "visible_property_codes": {"LANIER-1"},
            "can_assign": False,
            "can_manage_vendors": False,
            "can_manage_settings": False,
        }

    monkeypatch.setattr(dashboard_api, "_scope_profile", _scope)

    client = TestClient(app)
    response = client.get("/app/api/escalations")

    assert response.status_code == 200
    first_sql, first_params = fake_db.executed[2]
    assert "s.property_code = ANY(CAST(:visible_property_codes AS text[]))" in first_sql
    assert first_params["visible_property_codes"] == ["LANIER-1"]


def test_update_settings_requires_scope_settings_permission(monkeypatch):
    app = FastAPI()
    app.include_router(dashboard_api.router)
    app.dependency_overrides[dashboard_api.get_async_session] = _fake_session_dep

    monkeypatch.setattr(
        dashboard_api,
        "_require_context",
        lambda _request: {
            "operator_id": "member-1",
            "tenant_id": "00000000-0000-0000-0000-000000000001",
            "role": "staff",
            "email": "staff@example.com",
        },
    )

    async def _deny(*_args, **_kwargs):
        raise dashboard_api.HTTPException(403, "You do not have permission to manage settings in this scope")

    monkeypatch.setattr(dashboard_api, "_enforce_scope_permission", _deny)

    client = TestClient(app)
    response = client.patch("/app/api/settings", json={"ai_paused": True})

    assert response.status_code == 403
    assert "manage settings" in response.json()["detail"].lower()


def test_get_settings_includes_scope_permissions(monkeypatch):
    app = FastAPI()
    app.include_router(dashboard_api.router)
    fake_db = _DashboardDb(
        [
            ("mappings", []),
            ("mappings", []),
        ]
    )

    async def _fake_settings_session():
        yield fake_db

    app.dependency_overrides[dashboard_api.get_async_session] = _fake_settings_session

    monkeypatch.setattr(
        dashboard_api,
        "_require_context",
        lambda _request: {
            "operator_id": "member-1",
            "tenant_id": "00000000-0000-0000-0000-000000000001",
            "role": "staff",
            "email": "staff@example.com",
        },
    )

    async def _scope(*_args, **_kwargs):
        return {
            "visible_property_codes": {"LANIER-1"},
            "can_assign": False,
            "can_manage_vendors": True,
            "can_manage_settings": False,
        }

    monkeypatch.setattr(dashboard_api, "_scope_profile", _scope)

    client = TestClient(app)
    response = client.get("/app/api/settings")

    assert response.status_code == 200
    payload = response.json()
    assert payload["permissions"] == {
        "can_manage_settings": False,
        "can_manage_vendors": True,
        "can_assign": False,
    }
    assert payload["settings"]["proactive_policy"]["min_hours_between_proactive_touches"] == 18
    assert payload["settings"]["escalation_guest_policy"]["allow_eta_updates"] is True
    assert payload["settings"]["review_event_policy"]["ingest_review_events"] is True
    assert payload["settings"]["review_event_policy"]["generate_review_response_drafts"] is False


def test_alert_routing_filters_contacts_to_scoped_properties(monkeypatch):
    app = FastAPI()
    app.include_router(dashboard_api.router)
    fake_db = _DashboardDb(
        [
            ("mappings", [("id",), ("company_id",), ("property_code",)]),
            ("mappings", [
                {
                    "id": "contact-1",
                    "contact_name": "Lanier On Call",
                    "contact_phone": "",
                    "contact_email": "",
                    "alert_type": "maintenance",
                    "property_code": "LANIER-1",
                    "is_primary": True,
                    "escalation_order": 1,
                    "escalation_timeout_minutes": 30,
                    "active_hours_start": None,
                    "active_hours_end": None,
                    "is_available": True,
                    "unavailable_until": None,
                    "redirect_to_id": None,
                    "notes": None,
                    "redirect_name": None,
                }
            ]),
            ("mappings", [
                {
                    "property_id": "prop-lanier",
                    "property_name": "Lanier Beach House",
                    "property_code": "LANIER-1",
                }
            ]),
        ]
    )

    async def _fake_alert_session():
        yield fake_db

    app.dependency_overrides[dashboard_api.get_async_session] = _fake_alert_session

    monkeypatch.setattr(
        dashboard_api,
        "_require_context",
        lambda _request: {
            "operator_id": "member-1",
            "tenant_id": "00000000-0000-0000-0000-000000000001",
            "role": "staff",
            "email": "staff@example.com",
        },
    )

    async def _scope(*_args, **_kwargs):
        return {
            "visible_property_codes": {"LANIER-1"},
            "can_assign": False,
            "can_manage_vendors": False,
            "can_manage_settings": False,
        }

    async def _property_meta(*_args, **_kwargs):
        return {
            "id_expr": "property_id",
            "name_expr": "property_name",
            "code_expr": "property_code",
            "where_sql": "tenant_id = CAST(:tid AS uuid)",
        }

    class _Contact:
        def __init__(self, name):
            self.contact_name = name

        def availability_reason(self):
            return "Available"

    class _Router:
        async def get_recipients(self, company_id, alert_type, property_code=None):
            return ([_Contact("Lanier On Call")], [])

    monkeypatch.setattr(dashboard_api, "_scope_profile", _scope)
    monkeypatch.setattr(dashboard_api, "_property_query_meta", _property_meta)
    monkeypatch.setattr(dashboard_api, "get_alert_router", lambda db=None: _Router())

    client = TestClient(app)
    response = client.get("/app/api/settings/alert-routing")

    assert response.status_code == 200
    payload = response.json()
    assert payload["permissions"]["can_manage_settings"] is False
    assert payload["contacts"][0]["property_code"] == "LANIER-1"
    first_contacts_sql, first_contacts_params = fake_db.executed[1]
    assert "visible_property_codes" in first_contacts_params
    assert first_contacts_params["visible_property_codes"] == ["LANIER-1"]


def test_guest_thread_timeline_returns_unified_items(monkeypatch):
    app = FastAPI()
    app.include_router(dashboard_api.router)

    monkeypatch.setattr(
        dashboard_api,
        "_require_context",
        lambda _request: {
            "operator_id": "op-test",
            "tenant_id": "00000000-0000-0000-0000-000000000001",
            "role": "owner",
            "email": "owner@example.com",
        },
    )

    async def _fake_scope_profile(*_args, **_kwargs):
        return {"visible_property_codes": None}

    monkeypatch.setattr(dashboard_api, "_scope_profile", _fake_scope_profile)

    class _ThreadDb:
        async def execute(self, statement, params=None):
            sql = str(statement)
            if "FROM pre_booking_inquiries" in sql:
                return _FakeMappingsResult([
                    {
                        "item_type": "pre_booking",
                        "item_id": "INQ-1",
                        "property_code": "LANIER-1",
                        "guest_name": "Lanier Guest",
                        "summary": "Can we bring our dog?",
                        "occurred_at": None,
                        "status": "pending_review",
                        "thread_ref": "thread-1",
                    }
                ])
            if "FROM concierge_guest_sessions" in sql:
                return _FakeMappingsResult([
                    {
                        "item_type": "session",
                        "item_id": "session-1",
                        "property_code": "LANIER-1",
                        "guest_name": "Lanier Guest",
                        "summary": "Lanier House · in_stay",
                        "occurred_at": None,
                        "status": "active",
                        "thread_ref": "gh_123",
                    }
                ])
            if "FROM concierge_escalations" in sql:
                return _FakeMappingsResult([
                    {
                        "item_type": "escalation",
                        "item_id": "ESC-1",
                        "property_code": "LANIER-1",
                        "guest_name": "Lanier Guest",
                        "summary": "AC issue",
                        "occurred_at": None,
                        "status": "pending",
                        "thread_ref": "gh_123",
                    }
                ])
            raise AssertionError(sql)

        async def rollback(self):
            return None

    async def _fake_thread_session():
        yield _ThreadDb()

    app.dependency_overrides[dashboard_api.get_async_session] = _fake_thread_session

    client = TestClient(app)
    response = client.get("/app/api/threads/11111111-1111-1111-1111-111111111111")

    assert response.status_code == 200
    payload = response.json()
    assert payload["guest_thread_id"] == "11111111-1111-1111-1111-111111111111"
    assert len(payload["timeline"]) == 3
    assert {item["item_type"] for item in payload["timeline"]} == {"pre_booking", "session", "escalation"}
