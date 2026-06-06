from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from app.services.property_canonical_service import CanonicalPropertyService


@pytest.mark.asyncio
async def test_build_profile_loads_authored_policies(monkeypatch):
    session = MagicMock()
    svc = CanonicalPropertyService(session)

    monkeypatch.setattr(svc, "_property_table_meta", AsyncMock(return_value={"columns": set(), "canonical_code_col": "property_code"}))
    monkeypatch.setattr(svc, "_pms_table_meta", AsyncMock(return_value={"columns": set(), "name_col": "property_name"}))
    monkeypatch.setattr(svc, "_load_property_row", AsyncMock(return_value=None))
    monkeypatch.setattr(svc, "_load_profile_row", AsyncMock(return_value=None))
    monkeypatch.setattr(svc, "_load_pms_row", AsyncMock(return_value=None))
    monkeypatch.setattr(svc, "_load_concierge_knowledge", AsyncMock(return_value=None))
    monkeypatch.setattr(
        svc,
        "_load_operator_policies",
        AsyncMock(
            return_value={
                "_authored": True,
                "pets_allowed": "yes",
                "pet_policy": "allowed",
                "pet_fee": 50.0,
                "_source_provenance": {"pet_policy": "property_fact", "pet_fee": "operator_default"},
            }
        ),
    )

    profile = await svc.build_profile(
        tenant_id=UUID("11111111-1111-1111-1111-111111111111"),
        property_code="100SL2C",
    )

    assert profile["operator_policies"]["_authored"] is True
    assert profile["operator_policies"]["pets_allowed"] == "yes"
    assert profile["source_provenance"]["operator_policies"]["pet_policy"] == "property_fact"
    assert profile["source_provenance"]["operator_policies_authored"] is True


@pytest.mark.asyncio
async def test_build_profile_returns_unauthored_defaults(monkeypatch):
    session = MagicMock()
    svc = CanonicalPropertyService(session)

    monkeypatch.setattr(svc, "_property_table_meta", AsyncMock(return_value={"columns": set(), "canonical_code_col": "property_code"}))
    monkeypatch.setattr(svc, "_pms_table_meta", AsyncMock(return_value={"columns": set(), "name_col": "property_name"}))
    monkeypatch.setattr(svc, "_load_property_row", AsyncMock(return_value=None))
    monkeypatch.setattr(svc, "_load_profile_row", AsyncMock(return_value=None))
    monkeypatch.setattr(svc, "_load_pms_row", AsyncMock(return_value=None))
    monkeypatch.setattr(svc, "_load_concierge_knowledge", AsyncMock(return_value=None))
    monkeypatch.setattr(
        svc,
        "_load_operator_policies",
        AsyncMock(
            return_value={
                "_authored": False,
                "pets_allowed": "no",
                "pet_policy": "not_allowed",
                "_source_provenance": {"pet_policy": "schema_default"},
            }
        ),
    )

    profile = await svc.build_profile(
        tenant_id=UUID("11111111-1111-1111-1111-111111111111"),
        property_code="100SL2C",
    )

    assert profile["operator_policies"]["_authored"] is False
    assert profile["operator_policies"]["pet_policy"] == "not_allowed"


@pytest.mark.asyncio
async def test_load_operator_policies_handles_db_error(caplog):
    session = MagicMock()
    session.execute = AsyncMock(side_effect=RuntimeError("boom"))
    svc = CanonicalPropertyService(session)

    policies = await svc._load_operator_policies(UUID("11111111-1111-1111-1111-111111111111"))

    assert policies["_authored"] is False
    assert policies["_load_error"] is True
    assert "operator_policies load failed" in caplog.text
