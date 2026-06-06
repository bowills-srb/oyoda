from __future__ import annotations

from typing import Union
from uuid import UUID


class IdentityResolutionError(Exception):
    """Raised when dual-write identity keys diverge during Phase 3."""


def resolve_dual_write_identity(
    *,
    tenant_id: Union[UUID, str],
    company_id: Union[UUID, str],
    context: str,
) -> tuple[UUID, UUID]:
    """
    Normalize and assert consistency between tenant_id and company_id.

    During Phase 3C, company_id still exists as the legacy identity key on some
    operational tables while tenant_id becomes canonical. For the first dual-
    write wave, production reality is that company_id already stores the same
    UUID value as tenant_id. Any mismatch is therefore a real identity-
    resolution bug and should fail loudly rather than silently writing drift.
    """
    tenant_uuid = tenant_id if isinstance(tenant_id, UUID) else UUID(str(tenant_id))
    company_uuid = company_id if isinstance(company_id, UUID) else UUID(str(company_id))

    if tenant_uuid != company_uuid:
        raise IdentityResolutionError(
            f"Identity divergence in {context}: "
            f"tenant_id={tenant_uuid} != company_id={company_uuid}"
        )

    return tenant_uuid, company_uuid
