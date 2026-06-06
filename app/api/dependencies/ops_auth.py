"""
Ops auth/RBAC dependencies for observability/admin surfaces.
"""

from __future__ import annotations

from typing import Optional

from fastapi import Cookie, Header, HTTPException

from app.core.config import get_settings
from app.core.security import decode_token


def _payload_has_ops_access(payload) -> bool:
    roles = set(payload.roles or [])
    perms = set(payload.permissions or [])
    return bool(
        roles.intersection({"super_admin", "company_admin", "ops_admin"})
        or perms.intersection({"company:admin", "ops:read", "ops:admin"})
    )


def _token_has_ops_access(authorization: Optional[str]) -> bool:
    if not authorization:
        return False
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return False
    payload = decode_token(parts[1])
    return _payload_has_ops_access(payload)


def require_ops_access(
    authorization: Optional[str] = Header(default=None),
    x_ops_key: Optional[str] = Header(default=None, alias="X-Ops-Key"),
    oyvoda_access: Optional[str] = Cookie(default=None),
) -> None:
    """
    Require ops access when `enforce_ops_auth` is enabled.

    Allowed auth:
    - X-Ops-Key header matching settings.ops_api_key
    - Bearer JWT with admin role/permission
    """
    settings = get_settings()
    if not settings.enforce_ops_auth:
        return

    if settings.ops_api_key and x_ops_key == settings.ops_api_key:
        return

    try:
        if _token_has_ops_access(authorization):
            return
        if oyvoda_access and _payload_has_ops_access(decode_token(oyvoda_access)):
            return
    except Exception:
        pass

    raise HTTPException(status_code=401, detail="Ops authentication required")


def require_metrics_access(
    authorization: Optional[str] = Header(default=None),
    x_metrics_key: Optional[str] = Header(default=None, alias="X-Metrics-Key"),
    x_ops_key: Optional[str] = Header(default=None, alias="X-Ops-Key"),
    oyvoda_access: Optional[str] = Cookie(default=None),
) -> None:
    """
    Require metrics access when auth is enabled.

    Allowed auth:
    - X-Metrics-Key header matching settings.metrics_api_key
    - X-Ops-Key header matching settings.ops_api_key
    - Bearer JWT with admin role/permission
    """
    settings = get_settings()
    if not settings.enforce_ops_auth:
        return

    if settings.metrics_api_key and x_metrics_key == settings.metrics_api_key:
        return
    if settings.ops_api_key and x_ops_key == settings.ops_api_key:
        return

    try:
        if _token_has_ops_access(authorization):
            return
        if oyvoda_access and _payload_has_ops_access(decode_token(oyvoda_access)):
            return
    except Exception:
        pass

    raise HTTPException(status_code=401, detail="Metrics authentication required")
