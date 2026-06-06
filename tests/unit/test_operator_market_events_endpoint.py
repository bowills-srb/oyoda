from __future__ import annotations

from datetime import date
import inspect
from types import SimpleNamespace
from uuid import UUID

import pytest
import sys
import types
from fastapi import HTTPException
from sqlalchemy.exc import ProgrammingError

if "jose" not in sys.modules:
    jose_stub = types.ModuleType("jose")
    jose_stub.jwt = types.SimpleNamespace(decode=lambda *args, **kwargs: {})
    jose_stub.JWTError = Exception
    sys.modules["jose"] = jose_stub

from app.api.v1.endpoints import operator as operator_endpoint


class _FakeScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalar(self):
        return self._value


class _FakeRowsResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class _FakeDb:
    def __init__(self, *, market_id: str | None = "30a_fl", event_question_count: int = 3):
        self.market_id = market_id
        self.event_question_count = event_question_count
        self.executed: list[tuple[object, dict]] = []

    async def execute(self, statement, params=None):
        self.executed.append((statement, params or {}))
        sql = str(statement)
        if "SELECT market_id" in sql and "FROM operator_policies" in sql:
            return _FakeScalarResult(self.market_id)
        if "FROM market_events" in sql:
            return _FakeRowsResult(
                [
                    SimpleNamespace(
                        event_id="11111111-1111-1111-1111-111111111111",
                        title="Wine Festival",
                        category="festival",
                        start_date=date(2026, 6, 1),
                        end_date=date(2026, 6, 2),
                        is_multi_day=True,
                        venue_name="Town Green",
                        demand_impact_score=0.9,
                        estimated_attendance=5000,
                        is_free=False,
                        ticket_url="https://example.test/tickets",
                        source_url="https://example.test/source",
                    )
                ]
            )
        if "count" in sql.lower():
            return _FakeScalarResult(self.event_question_count)
        raise AssertionError(f"Unexpected statement: {sql}")

def _request():
    return SimpleNamespace(headers={}, cookies={})


@pytest.mark.asyncio
async def test_market_events_returns_401_without_auth(monkeypatch):
    monkeypatch.setattr(operator_endpoint, "resolve_request_tenant_id", lambda _request: None)

    with pytest.raises(HTTPException) as exc_info:
        await operator_endpoint.get_market_events(_request(), db=_FakeDb())

    assert exc_info.value.status_code == 401
    assert "no tenant" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_market_events_uses_jwt_tenant(monkeypatch):
    tenant_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    db = _FakeDb(market_id="destin_fl", event_question_count=7)
    monkeypatch.setattr(operator_endpoint, "_require_tenant", lambda _request: tenant_id)

    payload = await operator_endpoint.get_market_events(_request(), limit=5, days_ahead=30, db=db)
    assert payload["market_id"] == "destin_fl"
    assert payload["event_question_count"] == 7
    assert len(payload["events"]) == 1

    policy_params = db.executed[0][1]
    assert policy_params["tenant_id"] == str(tenant_id)

    count_statement = str(db.executed[2][0])
    assert "concierge_guest_sessions.tenant_id" in count_statement


@pytest.mark.asyncio
async def test_market_events_does_not_accept_operator_id_parameter(monkeypatch):
    tenant_id = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
    db = _FakeDb(market_id="gulf_shores_al", event_question_count=2)
    monkeypatch.setattr(operator_endpoint, "_require_tenant", lambda _request: tenant_id)

    payload = await operator_endpoint.get_market_events(_request(), limit=5, days_ahead=30, db=db)
    assert payload["market_id"] == "gulf_shores_al"
    assert db.executed[0][1]["tenant_id"] == str(tenant_id)
    assert "operator_id" not in inspect.signature(operator_endpoint.get_market_events).parameters


def test_market_events_signature_has_no_operator_id():
    assert "operator_id" not in inspect.signature(operator_endpoint.get_market_events).parameters


class _PolicyErrorDb(_FakeDb):
    async def execute(self, statement, params=None):
        sql = str(statement)
        self.executed.append((statement, params or {}))
        if "SELECT market_id" in sql and "FROM operator_policies" in sql:
            raise ProgrammingError("SELECT", {}, Exception("missing column"))
        if "FROM market_events" in sql:
            return _FakeRowsResult([])
        if "count" in sql.lower():
            return _FakeScalarResult(0)
        raise AssertionError(f"Unexpected statement: {sql}")


@pytest.mark.asyncio
async def test_market_events_falls_back_to_default_market_on_policy_schema_error(monkeypatch, caplog):
    tenant_id = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
    db = _PolicyErrorDb()
    monkeypatch.setattr(operator_endpoint, "_require_tenant", lambda _request: tenant_id)

    payload = await operator_endpoint.get_market_events(_request(), limit=5, days_ahead=30, db=db)

    assert payload["market_id"] == "30a_fl"
    assert "schema issue" in caplog.text
