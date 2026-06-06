from __future__ import annotations

import sys
import types
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

if "jose" not in sys.modules:
    jose_stub = types.ModuleType("jose")
    jose_stub.JWTError = Exception
    jose_stub.jwt = types.SimpleNamespace()
    sys.modules["jose"] = jose_stub

from app.api.v1.endpoints.incidents import (
    IncidentCreate,
    _resolve_request_tenant_id,
    create_incident,
)


class _FakeResult:
    def __init__(self, rowcount: int = 1):
        self.rowcount = rowcount

    def fetchone(self):
        return None


class _FakeDb:
    def __init__(self):
        self.executed = []
        self.commits = 0

    async def execute(self, statement, params=None):
        self.executed.append((str(statement), params or {}))
        return _FakeResult()

    async def commit(self):
        self.commits += 1


def _request(*, cookie_token: str | None = None, authorization: str | None = None):
    cookies = {}
    headers = {}
    if cookie_token:
        cookies["oyvoda_access"] = cookie_token
    if authorization:
        headers["authorization"] = authorization
    return SimpleNamespace(cookies=cookies, headers=headers)


def test_resolve_request_tenant_id_prefers_cookie(monkeypatch):
    tenant_id = uuid4()

    monkeypatch.setattr(
        "app.api.dependencies.request_tenant.decode_token",
        lambda token: SimpleNamespace(company_id=str(tenant_id)),
    )

    resolved = _resolve_request_tenant_id(_request(cookie_token="cookie-token"))

    assert resolved == tenant_id


def test_resolve_request_tenant_id_falls_back_to_bearer_header(monkeypatch):
    tenant_id = uuid4()

    monkeypatch.setattr(
        "app.api.dependencies.request_tenant.decode_token",
        lambda token: SimpleNamespace(company_id=str(tenant_id)),
    )

    resolved = _resolve_request_tenant_id(_request(authorization="Bearer access-token"))

    assert resolved == tenant_id


def test_resolve_request_tenant_id_requires_context():
    with pytest.raises(HTTPException) as exc:
        _resolve_request_tenant_id(_request())

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_create_incident_writes_tenant_and_company_ids(monkeypatch):
    tenant_id = uuid4()
    db = _FakeDb()

    monkeypatch.setattr(
        "app.api.v1.endpoints.incidents._resolve_request_tenant_id",
        lambda request: tenant_id,
    )

    response = await create_incident(
        IncidentCreate(
            company_id=str(tenant_id),
            property_external_id="BH-101",
            title="AC not cooling",
        ),
        _request(cookie_token="cookie-token"),
        db=db,
        _=None,
    )

    statement, params = db.executed[0]
    assert "tenant_id, company_id" in statement
    assert params["tid"] == str(tenant_id)
    assert params["cid"] == str(tenant_id)
    assert response["status"] == "created"
    assert db.commits == 1


@pytest.mark.asyncio
async def test_create_incident_rejects_identity_divergence(monkeypatch):
    auth_tenant_id = uuid4()
    payload_company_id = uuid4()
    db = _FakeDb()

    monkeypatch.setattr(
        "app.api.v1.endpoints.incidents._resolve_request_tenant_id",
        lambda request: auth_tenant_id,
    )

    with pytest.raises(HTTPException) as exc:
        await create_incident(
            IncidentCreate(
                company_id=str(payload_company_id),
                property_external_id="BH-101",
                title="AC not cooling",
            ),
            _request(cookie_token="cookie-token"),
            db=db,
            _=None,
        )

    assert exc.value.status_code == 403
    assert db.executed == []
