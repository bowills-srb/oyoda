from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from app.services.property_canonical_service import CanonicalPropertyService


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def mappings(self):
        return self

    def first(self):
        return self._row


@pytest.mark.asyncio
async def test_operator_defaults_flow_through_when_no_property_overrides():
    session = MagicMock()
    session.execute = AsyncMock(
        return_value=_FakeResult(
            {
                "tenant_id": "11111111-1111-1111-1111-111111111111",
                "pet_fee": 50.0,
                "pet_notes": "One dog max.",
                "discount_policies": {"rules": []},
                "additional_policies": {},
                "pet_restricted_breeds": [],
                "beach_chair_rental_partners": [],
            }
        )
    )
    svc = CanonicalPropertyService(session)

    policies = await svc._load_operator_policies(
        UUID("11111111-1111-1111-1111-111111111111"),
        property_row={"property_policy_overrides": {}},
        property_pet_friendly=True,
    )

    assert policies["pet_fee"] == 50.0
    assert policies["pet_policy"] == "allowed"
    assert policies["_source_provenance"]["pet_fee"] == "operator_default"
    assert policies["_source_provenance"]["pet_policy"] == "property_fact"


@pytest.mark.asyncio
async def test_property_override_wins_and_tracks_source():
    session = MagicMock()
    session.execute = AsyncMock(
        return_value=_FakeResult(
            {
                "tenant_id": "11111111-1111-1111-1111-111111111111",
                "pool_heat_daily_fee": 50.0,
                "discount_policies": {"rules": []},
                "additional_policies": {},
                "pet_restricted_breeds": [],
                "beach_chair_rental_partners": [],
            }
        )
    )
    svc = CanonicalPropertyService(session)

    policies = await svc._load_operator_policies(
        UUID("11111111-1111-1111-1111-111111111111"),
        property_row={"property_policy_overrides": {"pool_heat_daily_fee": 100.0}},
    )

    assert policies["pool_heat_daily_fee"] == 100.0
    assert policies["_source_provenance"]["pool_heat_daily_fee"] == "property_override"


@pytest.mark.asyncio
async def test_property_override_accepts_forward_compat_key():
    session = MagicMock()
    session.execute = AsyncMock(return_value=_FakeResult(None))
    svc = CanonicalPropertyService(session)

    policies = await svc._load_operator_policies(
        UUID("11111111-1111-1111-1111-111111111111"),
        property_row={"property_policy_overrides": {"pet_cleaning_fee": 125.0}},
    )

    assert policies["pet_cleaning_fee"] == 125.0
    assert policies["_source_provenance"]["pet_cleaning_fee"] == "property_override"
