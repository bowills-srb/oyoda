from __future__ import annotations

import sys
import types

if "jose" not in sys.modules:
    jose_stub = types.ModuleType("jose")
    jose_stub.JWTError = Exception
    jose_stub.jwt = types.SimpleNamespace()
    sys.modules["jose"] = jose_stub

from app.api.dependencies import ops_auth


class _Settings:
    enforce_ops_auth = True
    ops_api_key = ""
    metrics_api_key = ""


class _Payload:
    def __init__(self, *, roles=None, permissions=None):
        self.roles = roles or []
        self.permissions = permissions or []


def test_require_ops_access_accepts_dashboard_cookie(monkeypatch):
    monkeypatch.setattr(ops_auth, "get_settings", lambda: _Settings())
    monkeypatch.setattr(
        ops_auth,
        "decode_token",
        lambda token: _Payload(roles=["ops_admin"]) if token == "cookie-token" else _Payload(),
    )

    ops_auth.require_ops_access(authorization=None, x_ops_key=None, oyvoda_access="cookie-token")
