"""Tenant ID normalization — boundary helper.

Used at every edge that accepts `tenant_id` from a less-trusted source
(API layer, session row, caller code that may have built the value from
a string config or env var). Normalizes to UUID, raises loud on invalid
input. Same discipline as Phase 3's GuestSession.__post_init__ and the
VectorStore._require_tenant_id pattern.

Why this exists:
  Postgres will accept the string "None" as a query parameter and
  return zero rows. The router's `try/except Exception` swallows the
  silent miss. Result: a corrupted tenant_id value silently degrades
  to the empty-tier fallback instead of failing loud. This helper
  closes that boundary.
"""

from __future__ import annotations

from typing import Optional, Union
from uuid import UUID


class InvalidTenantIdError(ValueError):
    """Raised when a tenant_id value cannot be normalized to a UUID."""


def normalize_tenant_id(value: Union[UUID, str, None]) -> UUID:
    """Normalize a tenant_id input to a UUID."""
    if value is None:
        raise InvalidTenantIdError("tenant_id is required, got None")
    if isinstance(value, UUID):
        return value
    if not isinstance(value, str):
        raise InvalidTenantIdError(
            f"tenant_id must be UUID or str, got {type(value).__name__}"
        )

    stripped = value.strip()
    if not stripped:
        raise InvalidTenantIdError("tenant_id is required, got empty string")
    if stripped == "None":
        raise InvalidTenantIdError(
            'tenant_id received the literal string "None" '
            "(likely from str(None) at an upstream boundary)"
        )
    try:
        return UUID(stripped)
    except ValueError as exc:
        raise InvalidTenantIdError(
            f"tenant_id is not a valid UUID: {stripped!r}"
        ) from exc


def normalize_tenant_id_optional(value: Union[UUID, str, None]) -> Optional[UUID]:
    """Normalize a tenant_id input to UUID or None for optional boundaries."""
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    if not isinstance(value, str):
        raise InvalidTenantIdError(
            f"tenant_id must be UUID or str or None, got {type(value).__name__}"
        )

    stripped = value.strip()
    if not stripped:
        return None
    if stripped == "None":
        raise InvalidTenantIdError(
            'tenant_id received the literal string "None" '
            "(likely from str(None) at an upstream boundary)"
        )
    try:
        return UUID(stripped)
    except ValueError as exc:
        raise InvalidTenantIdError(
            f"tenant_id is not a valid UUID: {stripped!r}"
        ) from exc
