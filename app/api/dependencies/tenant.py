"""
Tenant context dependency.

Enforces that API calls are scoped to one company/tenant.
"""

from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from fastapi import Header, HTTPException

from app.core.security import decode_token


@dataclass
class TenantContext:
    company_id: UUID
    user_id: Optional[UUID] = None


def get_tenant_context(
    authorization: Optional[str] = Header(default=None),
    x_company_id: Optional[str] = Header(default=None, alias="X-Company-Id"),
) -> TenantContext:
    """
    Resolve tenant context from JWT and/or X-Company-Id header.

    Rules:
    - If JWT is present, company_id is taken from token.
    - If header and JWT are both present, they must match.
    - If no JWT, X-Company-Id is required.
    """
    token_company_id: Optional[UUID] = None
    token_user_id: Optional[UUID] = None

    if authorization:
        parts = authorization.split(" ", 1)
        if len(parts) != 2 or parts[0].lower() != "bearer":
            raise HTTPException(status_code=401, detail="Invalid Authorization header format")
        payload = decode_token(parts[1])
        token_company_id = UUID(payload.company_id)
        token_user_id = UUID(payload.sub)

    header_company_id: Optional[UUID] = None
    if x_company_id:
        try:
            header_company_id = UUID(x_company_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="X-Company-Id must be a valid UUID")

    if token_company_id and header_company_id and token_company_id != header_company_id:
        raise HTTPException(status_code=403, detail="Tenant mismatch between token and X-Company-Id header")

    resolved_company = token_company_id or header_company_id
    if not resolved_company:
        raise HTTPException(
            status_code=401,
            detail="Tenant context missing. Provide Bearer token or X-Company-Id header.",
        )

    return TenantContext(company_id=resolved_company, user_id=token_user_id)
