from __future__ import annotations

from uuid import uuid4

import pytest

from app.services.identity.dual_write import (
    IdentityResolutionError,
    resolve_dual_write_identity,
)


def test_resolve_dual_write_identity_accepts_matching_uuid_objects():
    tenant_id = uuid4()

    tenant_uuid, company_uuid = resolve_dual_write_identity(
        tenant_id=tenant_id,
        company_id=tenant_id,
        context="test",
    )

    assert tenant_uuid == tenant_id
    assert company_uuid == tenant_id


def test_resolve_dual_write_identity_normalizes_matching_strings():
    tenant_id = uuid4()

    tenant_uuid, company_uuid = resolve_dual_write_identity(
        tenant_id=str(tenant_id),
        company_id=str(tenant_id),
        context="test",
    )

    assert tenant_uuid == tenant_id
    assert company_uuid == tenant_id


def test_resolve_dual_write_identity_normalizes_mixed_types():
    tenant_id = uuid4()

    tenant_uuid, company_uuid = resolve_dual_write_identity(
        tenant_id=tenant_id,
        company_id=str(tenant_id),
        context="test",
    )

    assert tenant_uuid == tenant_id
    assert company_uuid == tenant_id


def test_resolve_dual_write_identity_raises_on_divergence():
    with pytest.raises(IdentityResolutionError):
        resolve_dual_write_identity(
            tenant_id=uuid4(),
            company_id=uuid4(),
            context="test",
        )


def test_resolve_dual_write_identity_raises_value_error_for_invalid_uuid_string():
    with pytest.raises(ValueError):
        resolve_dual_write_identity(
            tenant_id="not-a-uuid",
            company_id=str(uuid4()),
            context="test",
        )
