from __future__ import annotations

import sys
import types
from types import SimpleNamespace
from uuid import uuid4

if "jose" not in sys.modules:
    jose_stub = types.ModuleType("jose")
    jose_stub.jwt = types.SimpleNamespace(decode=lambda *args, **kwargs: {})
    jose_stub.JWTError = Exception
    sys.modules["jose"] = jose_stub

from app.api.dependencies import request_tenant


def _request(*, cookie_token: str | None = None, authorization: str | None = None, scoped_tid: str | None = None):
    cookies = {}
    headers = {}
    if cookie_token:
        cookies["oyvoda_access"] = cookie_token
    if authorization:
        headers["authorization"] = authorization
    if scoped_tid:
        cookies["oyvoda_scoped_tid"] = scoped_tid
    return SimpleNamespace(cookies=cookies, headers=headers)


def test_resolve_request_tenant_id_honors_super_admin_scoped_cookie(monkeypatch):
    tenant_id = uuid4()
    scoped_tid = uuid4()

    monkeypatch.setattr(
        request_tenant,
        "decode_token",
        lambda token: SimpleNamespace(company_id=str(tenant_id), roles=["super_admin"]),
    )

    resolved = request_tenant.resolve_request_tenant_id(
        _request(cookie_token="cookie-token", scoped_tid=str(scoped_tid))
    )

    assert resolved == scoped_tid
