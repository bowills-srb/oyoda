from __future__ import annotations

import sys
import types
from types import SimpleNamespace
from uuid import UUID
import pytest

if "jose" not in sys.modules:
    jose_stub = types.ModuleType("jose")
    jose_stub.jwt = types.SimpleNamespace(decode=lambda *args, **kwargs: {})
    jose_stub.JWTError = Exception
    sys.modules["jose"] = jose_stub

from app.api.v1.endpoints import operator_policies as operator_policies_endpoint


class _FakeResult:
    def __init__(self, row=None):
        self._row = row

    def mappings(self):
        return self

    def first(self):
        return self._row


class _FakeSession:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.executed = []
        self.committed = False

    async def execute(self, stmt, params=None):
        self.executed.append((str(stmt), params or {}))
        row = self.rows.pop(0) if self.rows else None
        return _FakeResult(row=row)

    async def commit(self):
        self.committed = True


def _request():
    return SimpleNamespace(headers={}, cookies={})


@pytest.mark.asyncio
async def test_get_returns_defaults_when_no_row(monkeypatch):
    operator_policies_endpoint.resolve_request_tenant_id = lambda request: UUID("11111111-1111-1111-1111-111111111111")
    body = await operator_policies_endpoint.get_policies(_request(), _FakeSession(rows=[None]))
    assert body["exists"] is False
    assert body["policies"]["discount_policies"] == {"rules": []}


@pytest.mark.asyncio
async def test_patch_creates_row():
    fake_db = _FakeSession(
        rows=[
            None,
            {"tenant_id": "11111111-1111-1111-1111-111111111111", "pets_allowed": "yes"},
        ]
    )
    operator_policies_endpoint.resolve_request_tenant_id = lambda request: UUID("11111111-1111-1111-1111-111111111111")
    body = await operator_policies_endpoint.patch_policies(
        operator_policies_endpoint.PolicyPatch(pets_allowed="yes"),
        _request(),
        fake_db,
    )
    assert body["exists"] is True
    assert fake_db.committed is True


@pytest.mark.asyncio
async def test_patch_creates_row_with_partial_unique_index():
    fake_db = _FakeSession(
        rows=[
            None,
            {"tenant_id": "11111111-1111-1111-1111-111111111111", "pets_allowed": "yes"},
        ]
    )
    operator_policies_endpoint.resolve_request_tenant_id = lambda request: UUID("11111111-1111-1111-1111-111111111111")
    await operator_policies_endpoint.patch_policies(
        operator_policies_endpoint.PolicyPatch(pets_allowed="yes"),
        _request(),
        fake_db,
    )
    executed_sql = fake_db.executed[0][0]
    assert "ON CONFLICT (tenant_id) WHERE tenant_id IS NOT NULL DO UPDATE" in executed_sql


@pytest.mark.asyncio
async def test_patch_partial_update():
    fake_db = _FakeSession(rows=[{"tenant_id": "11111111-1111-1111-1111-111111111111", "support_phone": "555-1111"}])
    operator_policies_endpoint.resolve_request_tenant_id = lambda request: UUID("11111111-1111-1111-1111-111111111111")
    await operator_policies_endpoint.patch_policies(
        operator_policies_endpoint.PolicyPatch(support_phone="555-1111"),
        _request(),
        fake_db,
    )
    assert "support_phone" in fake_db.executed[0][1]


@pytest.mark.asyncio
async def test_patch_updates_existing_row():
    fake_db = _FakeSession(
        rows=[
            None,
            {"tenant_id": "11111111-1111-1111-1111-111111111111", "pets_allowed": "no"},
        ]
    )
    operator_policies_endpoint.resolve_request_tenant_id = lambda request: UUID("11111111-1111-1111-1111-111111111111")
    body = await operator_policies_endpoint.patch_policies(
        operator_policies_endpoint.PolicyPatch(pets_allowed="no"),
        _request(),
        fake_db,
    )
    executed_sql = fake_db.executed[0][0]
    assert "ON CONFLICT (tenant_id) WHERE tenant_id IS NOT NULL DO UPDATE" in executed_sql
    assert body["exists"] is True


@pytest.mark.asyncio
async def test_patch_validates_discount_policies():
    fake_db = _FakeSession()
    operator_policies_endpoint.resolve_request_tenant_id = lambda request: UUID("11111111-1111-1111-1111-111111111111")
    with pytest.raises(operator_policies_endpoint.HTTPException) as exc_info:
        await operator_policies_endpoint.patch_policies(
            operator_policies_endpoint.PolicyPatch(
                discount_policies={
                    "rules": [
                        {
                            "id": "x",
                            "type": "next_night_extension",
                            "condition": {"kind": "gap_night_available"},
                            "offer": {"discount_pct": 500},
                        }
                    ]
                }
            ),
            _request(),
            fake_db,
        )
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_patch_accepts_valid_discount_policies():
    fake_db = _FakeSession(
        rows=[
            None,
            {
                "tenant_id": "11111111-1111-1111-1111-111111111111",
                "discount_policies": {
                    "rules": [
                        {
                            "id": "x",
                            "type": "next_night_extension",
                            "condition": {"kind": "gap_night_available"},
                            "offer": {"discount_pct": 10},
                        }
                    ]
                },
            },
        ]
    )
    operator_policies_endpoint.resolve_request_tenant_id = lambda request: UUID("11111111-1111-1111-1111-111111111111")
    body = await operator_policies_endpoint.patch_policies(
        operator_policies_endpoint.PolicyPatch(
            discount_policies={
                "rules": [
                    {
                        "id": "x",
                        "type": "next_night_extension",
                        "condition": {"kind": "gap_night_available"},
                        "offer": {"discount_pct": 10},
                    }
                ]
            }
        ),
        _request(),
        fake_db,
    )
    assert body["exists"] is True


@pytest.mark.asyncio
async def test_patch_empty_body_idempotent():
    fake_db = _FakeSession(
        rows=[
            {"tenant_id": "11111111-1111-1111-1111-111111111111"},
            {"tenant_id": "11111111-1111-1111-1111-111111111111"},
            {"tenant_id": "11111111-1111-1111-1111-111111111111"},
            {"tenant_id": "11111111-1111-1111-1111-111111111111"},
        ]
    )
    operator_policies_endpoint.resolve_request_tenant_id = lambda request: UUID("11111111-1111-1111-1111-111111111111")
    await operator_policies_endpoint.patch_policies(
        operator_policies_endpoint.PolicyPatch(),
        _request(),
        fake_db,
    )
    await operator_policies_endpoint.patch_policies(
        operator_policies_endpoint.PolicyPatch(),
        _request(),
        fake_db,
    )
    assert "ON CONFLICT (tenant_id) WHERE tenant_id IS NOT NULL DO NOTHING" in fake_db.executed[0][0]
    assert "ON CONFLICT (tenant_id) WHERE tenant_id IS NOT NULL DO NOTHING" in fake_db.executed[2][0]


@pytest.mark.asyncio
async def test_patch_requires_tenant_context():
    operator_policies_endpoint.resolve_request_tenant_id = lambda request: None
    with pytest.raises(operator_policies_endpoint.HTTPException) as exc_info:
        await operator_policies_endpoint.patch_policies(
            operator_policies_endpoint.PolicyPatch(pets_allowed="yes"),
            _request(),
            _FakeSession(),
        )
    assert exc_info.value.status_code == 401
