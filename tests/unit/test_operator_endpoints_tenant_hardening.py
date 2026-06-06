from __future__ import annotations

import inspect
import sys
import types
from dataclasses import dataclass
from datetime import date
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import ProgrammingError

if "jose" not in sys.modules:
    jose_stub = types.ModuleType("jose")
    jose_stub.jwt = types.SimpleNamespace(decode=lambda *args, **kwargs: {})
    jose_stub.JWTError = Exception
    sys.modules["jose"] = jose_stub

from app.api.v1.endpoints import operator as operator_endpoint


class _AsyncSessionContext:
    def __init__(self, db):
        self._db = db

    async def __aenter__(self):
        return self._db

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeResult:
    def __init__(self, *, rows=None, row=None, scalar_value=None, scalar_one_or_none=None):
        self._rows = list(rows or [])
        self._row = row
        self._scalar_value = scalar_value
        self._scalar_one_or_none = scalar_one_or_none

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._row

    def scalar(self):
        return self._scalar_value

    def scalar_one_or_none(self):
        return self._scalar_one_or_none


class _CaptureDb:
    def __init__(self, *, result=None, error: Exception | None = None):
        self.result = result or _FakeResult()
        self.error = error
        self.executed: list[tuple[object, dict]] = []
        self.committed = 0

    async def execute(self, statement, params=None):
        self.executed.append((statement, params or {}))
        if self.error is not None:
            raise self.error
        return self.result

    async def commit(self):
        self.committed += 1


def _request():
    return SimpleNamespace(headers={}, cookies={})


def _base_session_payload() -> operator_endpoint.CreateSessionRequest:
    return operator_endpoint.CreateSessionRequest(
        reservation_id="R-1",
        property_code="P-1",
        guest_first_name="Ada",
        guest_last_name="Lovelace",
        check_in=date(2026, 6, 1),
        check_out=date(2026, 6, 5),
    )


@pytest.mark.parametrize(
    ("factory", "expected_detail"),
    [
        (
            lambda: operator_endpoint.create_session(
                _base_session_payload(),
                _request(),
            ),
            "Authentication required: no tenant in token or cookie.",
        ),
        (
            lambda: operator_endpoint.list_sessions(
                _request(),
            ),
            "Authentication required: no tenant in token or cookie.",
        ),
        (
            lambda: operator_endpoint.list_knowledge_gaps(
                _request(),
            ),
            "Authentication required: no tenant in token or cookie.",
        ),
        (
            lambda: operator_endpoint.resolve_knowledge_gap(
                _request(),
                str(uuid4()),
            ),
            "Authentication required: no tenant in token or cookie.",
        ),
        (
            lambda: operator_endpoint.get_analytics(
                _request(),
            ),
            "Authentication required: no tenant in token or cookie.",
        ),
        (
            lambda: operator_endpoint.get_inquiry_heatmap(
                _request(),
            ),
            "Authentication required: no tenant in token or cookie.",
        ),
        (
            lambda: operator_endpoint.get_property_analytics(
                _request(),
            ),
            "Authentication required: no tenant in token or cookie.",
        ),
        (
            lambda: operator_endpoint.get_response_time_distribution(
                _request(),
            ),
            "Authentication required: no tenant in token or cookie.",
        ),
        (
            lambda: operator_endpoint.get_revenue_impact(
                _request(),
            ),
            "Authentication required: no tenant in token or cookie.",
        ),
        (
            lambda: operator_endpoint.get_upsell_rates(
                _request(),
            ),
            "Authentication required: no tenant in token or cookie.",
        ),
        (
            lambda: operator_endpoint.set_upsell_rates(
                _request(),
                {"late_checkout": 75.0},
            ),
            "Authentication required: no tenant in token or cookie.",
        ),
        (
            lambda: operator_endpoint.list_repeat_guests(
                _request(),
            ),
            "Authentication required: no tenant in token or cookie.",
        ),
        (
            lambda: operator_endpoint.get_guest_profile(
                _request(),
                str(uuid4()),
            ),
            "Authentication required: no tenant in token or cookie.",
        ),
        (
            lambda: operator_endpoint.update_guest_preferences(
                _request(),
                str(uuid4()),
                {"custom_notes": "VIP"},
            ),
            "Authentication required: no tenant in token or cookie.",
        ),
        (
            lambda: operator_endpoint.get_stats(
                _request(),
            ),
            "Authentication required: no tenant in token or cookie.",
        ),
    ],
)
@pytest.mark.asyncio
async def test_hardened_endpoints_return_401_without_tenant(monkeypatch, factory, expected_detail):
    monkeypatch.setattr(operator_endpoint, "resolve_request_tenant_id", lambda _request: None)
    with pytest.raises(HTTPException) as exc_info:
        await factory()
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == expected_detail


def test_hardened_endpoint_signatures_remove_operator_id():
    hardened_functions = [
        operator_endpoint.list_sessions,
        operator_endpoint.list_knowledge_gaps,
        operator_endpoint.resolve_knowledge_gap,
        operator_endpoint.get_analytics,
        operator_endpoint.get_inquiry_heatmap,
        operator_endpoint.get_property_analytics,
        operator_endpoint.get_response_time_distribution,
        operator_endpoint.get_revenue_impact,
        operator_endpoint.get_upsell_rates,
        operator_endpoint.set_upsell_rates,
        operator_endpoint.list_repeat_guests,
        operator_endpoint.get_guest_profile,
        operator_endpoint.update_guest_preferences,
        operator_endpoint.get_stats,
    ]

    for fn in hardened_functions:
        assert "operator_id" not in inspect.signature(fn).parameters


@pytest.mark.asyncio
async def test_list_sessions_uses_authenticated_tenant(monkeypatch):
    tenant_a = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    captured = {}

    class _Svc:
        async def list_sessions(self, db, *, property_code, phase, limit, tenant_id):
            captured["tenant_id"] = tenant_id
            return []

    monkeypatch.setattr(operator_endpoint, "_require_tenant", lambda _request: tenant_a)
    monkeypatch.setattr(
        "app.services.concierge.db_session_service.get_db_session_service",
        lambda: _Svc(),
    )
    monkeypatch.setattr(
        "app.services.concierge.notification_service.get_notification_service",
        lambda: SimpleNamespace(get_concierge_url=lambda token: f"https://example.test/{token}"),
    )
    monkeypatch.setattr("app.db.session.get_async_session", lambda: _AsyncSessionContext(_CaptureDb()))

    result = await operator_endpoint.list_sessions(_request())

    assert result == []
    assert captured["tenant_id"] == tenant_a


@pytest.mark.asyncio
async def test_get_analytics_uses_authenticated_tenant(monkeypatch):
    tenant_a = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    db = _CaptureDb(error=RuntimeError("stop after capture"))

    monkeypatch.setattr(operator_endpoint, "_require_tenant", lambda _request: tenant_a)
    monkeypatch.setattr("app.db.session.get_async_session", lambda: _AsyncSessionContext(db))

    result = await operator_endpoint.get_analytics(_request())

    assert result["period_days"] == 30
    assert db.executed[0][1]["tid"] == str(tenant_a)


@pytest.mark.asyncio
async def test_resolve_knowledge_gap_uses_authenticated_tenant(monkeypatch):
    tenant_a = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    db = _CaptureDb()
    gap_id = str(uuid4())

    monkeypatch.setattr(operator_endpoint, "_require_tenant", lambda _request: tenant_a)
    monkeypatch.setattr("app.db.session.get_async_session", lambda: _AsyncSessionContext(db))

    result = await operator_endpoint.resolve_knowledge_gap(_request(), gap_id, notes="resolved")

    assert result == {"status": "ok", "gap_id": gap_id}
    statement = db.executed[0][0]
    compiled = statement.compile()
    assert str(tenant_a) in compiled.params.values()


@pytest.mark.asyncio
async def test_get_upsell_rates_uses_authenticated_tenant(monkeypatch):
    tenant_a = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    db = _CaptureDb(result=_FakeResult(row=None))

    monkeypatch.setattr(operator_endpoint, "_require_tenant", lambda _request: tenant_a)
    monkeypatch.setattr(operator_endpoint, "SessionLocal", lambda: _AsyncSessionContext(db))

    result = await operator_endpoint.get_upsell_rates(_request())

    assert result["source"] == "platform_defaults"
    assert db.executed[0][1]["tid"] == str(tenant_a)


@pytest.mark.asyncio
async def test_get_upsell_rates_falls_back_on_schema_error(monkeypatch, caplog):
    tenant_a = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    db = _CaptureDb(error=ProgrammingError("SELECT", {}, Exception("missing column")))

    monkeypatch.setattr(operator_endpoint, "_require_tenant", lambda _request: tenant_a)
    monkeypatch.setattr(operator_endpoint, "SessionLocal", lambda: _AsyncSessionContext(db))

    result = await operator_endpoint.get_upsell_rates(_request())

    assert result["source"] == "platform_defaults"
    assert result["rates"] == operator_endpoint._PLATFORM_UPSELL_DEFAULTS
    assert "schema issue" in caplog.text


@pytest.mark.asyncio
async def test_set_upsell_rates_uses_authenticated_tenant(monkeypatch):
    tenant_a = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    db = _CaptureDb()

    monkeypatch.setattr(operator_endpoint, "_require_tenant", lambda _request: tenant_a)
    monkeypatch.setattr(operator_endpoint, "SessionLocal", lambda: _AsyncSessionContext(db))

    result = await operator_endpoint.set_upsell_rates(_request(), {"late_checkout": 75.0})

    assert result == {"status": "ok", "rates_saved": 1}
    assert db.executed[0][1]["tid"] == str(tenant_a)
    assert "ON CONFLICT (tenant_id) WHERE tenant_id IS NOT NULL DO UPDATE" in str(db.executed[0][0])
    assert db.committed == 1


@pytest.mark.asyncio
async def test_get_revenue_impact_uses_canonical_policy_tenant(monkeypatch):
    tenant_a = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")

    class _RevenueDb:
        def __init__(self):
            self.executed = []

        async def execute(self, statement, params=None):
            self.executed.append((statement, params or {}))
            sql = str(statement)
            if "FROM operator_policies" in sql:
                return _FakeResult(row=None)
            if "TO_CHAR(m.created_at" in sql:
                return _FakeResult(rows=[])
            if "TO_CHAR(a.updated_at" in sql:
                return _FakeResult(rows=[])
            if "GROUP BY a.activity_type" in sql:
                return _FakeResult(rows=[])
            raise AssertionError(f"Unexpected statement: {sql}")

    db = _RevenueDb()

    monkeypatch.setattr(operator_endpoint, "_require_tenant", lambda _request: tenant_a)
    monkeypatch.setattr(operator_endpoint, "SessionLocal", lambda: _AsyncSessionContext(db))

    result = await operator_endpoint.get_revenue_impact(_request())

    assert result["upsell_rates_source"] == "platform_defaults"
    assert db.executed[0][1]["tid"] == str(tenant_a)


@pytest.mark.asyncio
async def test_get_stats_uses_authenticated_tenant(monkeypatch):
    tenant_a = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    db = _CaptureDb(
        result=_FakeResult(
            row=SimpleNamespace(
                total=0,
                in_stay=0,
                arriving_today=0,
                departing_today=0,
                total_convos=0,
            )
        )
    )

    monkeypatch.setattr(operator_endpoint, "_require_tenant", lambda _request: tenant_a)
    monkeypatch.setattr("app.db.session.get_async_session", lambda: _AsyncSessionContext(db))
    monkeypatch.setattr(
        "app.services.concierge.escalation_service.get_escalation_service",
        lambda: SimpleNamespace(get_pending_tickets=lambda: []),
    )

    result = await operator_endpoint.get_stats(_request())

    assert result["total_sessions"] == 0
    statement = db.executed[0][0]
    compiled = statement.compile()
    assert str(tenant_a) in compiled.params.values()
