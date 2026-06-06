from uuid import UUID, uuid4

import pytest

from app.services.identity.tenant_normalization import (
    InvalidTenantIdError,
    normalize_tenant_id,
    normalize_tenant_id_optional,
)


def test_normalize_tenant_id_accepts_uuid_instance():
    tid = uuid4()
    assert normalize_tenant_id(tid) is tid


def test_normalize_tenant_id_accepts_uuid_string():
    tid = uuid4()
    result = normalize_tenant_id(str(tid))
    assert result == tid
    assert isinstance(result, UUID)


def test_normalize_tenant_id_strips_whitespace():
    tid = uuid4()
    result = normalize_tenant_id(f"  {tid}  ")
    assert result == tid


def test_normalize_tenant_id_rejects_none():
    with pytest.raises(InvalidTenantIdError, match="got None"):
        normalize_tenant_id(None)


def test_normalize_tenant_id_rejects_empty_string():
    with pytest.raises(InvalidTenantIdError, match="empty string"):
        normalize_tenant_id("")


def test_normalize_tenant_id_rejects_whitespace_only():
    with pytest.raises(InvalidTenantIdError, match="empty string"):
        normalize_tenant_id("   ")


def test_normalize_tenant_id_rejects_none_literal_string():
    """The canonical bug shape: str(None) -> 'None' silently passes to SQL."""
    with pytest.raises(InvalidTenantIdError, match='literal string "None"'):
        normalize_tenant_id("None")


def test_normalize_tenant_id_rejects_non_uuid_string():
    with pytest.raises(InvalidTenantIdError, match="not a valid UUID"):
        normalize_tenant_id("not-a-uuid")


def test_normalize_tenant_id_rejects_non_string_non_uuid():
    with pytest.raises(InvalidTenantIdError, match="must be UUID or str"):
        normalize_tenant_id(12345)  # type: ignore[arg-type]


def test_normalize_tenant_id_optional_passes_none_through():
    assert normalize_tenant_id_optional(None) is None


def test_normalize_tenant_id_optional_passes_empty_string_as_none():
    assert normalize_tenant_id_optional("") is None


def test_normalize_tenant_id_optional_still_rejects_none_literal_string():
    """The bug case is still a bug even in the optional variant."""
    with pytest.raises(InvalidTenantIdError, match='literal string "None"'):
        normalize_tenant_id_optional("None")


def test_normalize_tenant_id_optional_still_rejects_invalid_uuid():
    with pytest.raises(InvalidTenantIdError, match="not a valid UUID"):
        normalize_tenant_id_optional("garbage")


def test_normalize_tenant_id_optional_accepts_uuid_string():
    tid = uuid4()
    result = normalize_tenant_id_optional(str(tid))
    assert result == tid
