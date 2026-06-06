"""
Request-scoped tenant resolution helpers.

These helpers read tenant context from either platform Bearer tokens or the
operator app's HttpOnly cookies. They intentionally return only the canonical
tenant UUID so individual endpoints can decide whether missing context should
raise 401, 403, or trigger a legacy fallback.
"""

from __future__ import annotations

import os
from typing import Optional
from uuid import UUID

from fastapi import Request
from jose import jwt

from app.core.security import decode_token


def _tenant_from_token(token: str) -> Optional[UUID]:
    try:
        payload = decode_token(token)
        if payload and payload.company_id:
            return UUID(str(payload.company_id))
    except Exception:
        pass

    # Operator app cookies use `tid` / `tenant_id` instead of `company_id`.
    try:
        jwt_secret = os.getenv("JWT_SECRET", "")
        raw = jwt.decode(token, jwt_secret, algorithms=["HS256"])
        tenant_value = raw.get("company_id") or raw.get("tid") or raw.get("tenant_id")
        if tenant_value:
            return UUID(str(tenant_value))
    except Exception:
        pass

    return None


def _is_super_admin_token(token: str) -> bool:
    try:
        payload = decode_token(token)
        roles = set(payload.roles or [])
        if "super_admin" in roles:
            return True
    except Exception:
        pass

    try:
        jwt_secret = os.getenv("JWT_SECRET", "")
        raw = jwt.decode(token, jwt_secret, algorithms=["HS256"])
        roles = raw.get("roles") or []
        role = raw.get("role")
        if "super_admin" in roles or role == "super_admin":
            return True
    except Exception:
        pass

    return False


def resolve_request_tenant_id(request: Request) -> Optional[UUID]:
    """Extract canonical tenant_id from a Bearer token or oyvoda_access cookie."""
    authorization = request.headers.get("authorization")
    if authorization:
        parts = authorization.split(" ", 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            tenant = _tenant_from_token(parts[1])
            if tenant:
                return tenant

    cookie_token = request.cookies.get("oyvoda_access")
    if cookie_token:
        scoped_tid = request.cookies.get("oyvoda_scoped_tid")
        if scoped_tid and _is_super_admin_token(cookie_token):
            try:
                return UUID(str(scoped_tid))
            except Exception:
                pass
        tenant = _tenant_from_token(cookie_token)
        if tenant:
            return tenant

    return None
