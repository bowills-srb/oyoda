from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest

from app.services.connectors.adapter_backed_booking_data_provider import (
    AdapterBackedBookingDataProvider,
)
from app.services.connectors.booking_data_provider import (
    BookingDataCapability,
    BookingFetchErrorType,
    BookingPropertyRef,
    NotSupportedError,
)


class _FakeAdapter:
    def __init__(self, payload=None, error: Exception | None = None):
        self.payload = payload
        self.error = error
        self.calls: list[object] = []

    async def lookup(self, db_session, lookup):
        self.calls.append((db_session, lookup))
        if self.error:
            raise self.error
        return self.payload


def _provider(payload=None, *, error: Exception | None = None, provider_key: str = "escapia"):
    return AdapterBackedBookingDataProvider(
        company_id=UUID("11111111-1111-1111-1111-111111111111"),
        provider_key=provider_key,
        adapter=_FakeAdapter(payload=payload, error=error),
    )


def _property_ref(**overrides) -> BookingPropertyRef:
    return BookingPropertyRef(
        provider=overrides.pop("provider", "escapia"),
        provider_listing_id=overrides.pop("provider_listing_id", None),
        provider_unit_id=overrides.pop("provider_unit_id", None),
        property_code=overrides.pop("property_code", "GULF_VIEW_204"),
    )


def _full_lookup() -> dict:
    return {
        "property": {
            "property_code": "GULF_VIEW_204",
            "property_name": "Gulf View 204",
            "provider": "escapia",
            "city": "Santa Rosa Beach",
            "state": "FL",
            "bedrooms": 3,
            "bathrooms": 2.5,
            "property_type": "condo",
            "beach_access": "public",
            "has_pool": True,
            "has_hot_tub": True,
            "pet_friendly": False,
        },
        "booking": {
            "nightly_rate": 425.0,
            "cleaning_fee": 210.0,
            "taxes": 64.5,
        },
        "active_booking": {
            "nightly_rate": 450.0,
            "cleaning_fee": 225.0,
            "taxes": 70.0,
        },
        "next_booking": {
            "nightly_rate": 475.0,
            "cleaning_fee": 230.0,
            "taxes": 72.0,
        },
        "lookup": {"property_code": "GULF_VIEW_204"},
    }


def test_capabilities_match_declared_surface() -> None:
    provider = _provider({})
    assert provider.capabilities == frozenset(
        {
            BookingDataCapability.GET_PROPERTY_SUMMARY,
            BookingDataCapability.GET_RATE_SUMMARY,
        }
    )


def test_supports_agrees_with_capabilities() -> None:
    provider = _provider({})
    assert provider.supports(BookingDataCapability.GET_PROPERTY_SUMMARY) is True
    assert provider.supports(BookingDataCapability.GET_RATE_SUMMARY) is True
    assert provider.supports(BookingDataCapability.GET_AVAILABILITY) is False


def test_provider_property_reports_expected_key() -> None:
    provider = _provider({}, provider_key="guesty")
    assert provider.provider == "guesty"


@pytest.mark.asyncio
async def test_property_summary_translates_full_snapshot() -> None:
    provider = _provider(_full_lookup())
    summary, errors = await provider.get_property_summary(
        db_session=object(),
        property_ref=_property_ref(),
    )

    assert errors == []
    assert summary is not None
    assert summary.display_name == "Gulf View 204"
    assert summary.bedrooms == 3
    assert summary.bathrooms == Decimal("2.5")
    assert summary.address_summary == "Santa Rosa Beach, FL"
    assert summary.key_features == (
        "Beach access (public)",
        "Pool",
        "Hot tub",
    )


@pytest.mark.asyncio
async def test_property_summary_missing_required_fields_returns_malformed() -> None:
    provider = _provider({"property": {"property_code": "X1"}})
    summary, errors = await provider.get_property_summary(
        db_session=object(),
        property_ref=_property_ref(),
    )

    assert summary is None
    assert errors[-1].error_type == BookingFetchErrorType.MALFORMED


@pytest.mark.asyncio
async def test_property_summary_without_property_returns_not_found() -> None:
    provider = _provider({"lookup": {"property_code": "GULF_VIEW_204"}})
    summary, errors = await provider.get_property_summary(
        db_session=object(),
        property_ref=_property_ref(),
    )

    assert summary is None
    assert errors[-1].error_type == BookingFetchErrorType.NOT_FOUND


@pytest.mark.asyncio
async def test_property_summary_surfaces_adapter_exception_as_provider_error() -> None:
    provider = _provider(error=RuntimeError("cache offline"))
    summary, errors = await provider.get_property_summary(
        db_session=object(),
        property_ref=_property_ref(),
    )

    assert summary is None
    assert errors[-1].error_type == BookingFetchErrorType.PROVIDER_RETURNED_ERROR
    assert "cache offline" in errors[-1].message


@pytest.mark.asyncio
async def test_property_summary_allows_partial_address_city_only() -> None:
    payload = _full_lookup()
    payload["property"]["state"] = None
    provider = _provider(payload)
    summary, errors = await provider.get_property_summary(
        db_session=object(),
        property_ref=_property_ref(),
    )

    assert errors == []
    assert summary is not None
    assert summary.address_summary == "Santa Rosa Beach"


@pytest.mark.asyncio
async def test_property_summary_keeps_none_property_code_when_unresolved() -> None:
    payload = _full_lookup()
    payload["property"]["property_code"] = None
    provider = _provider(payload)
    summary, errors = await provider.get_property_summary(
        db_session=object(),
        property_ref=_property_ref(property_code=None),
    )

    assert errors == []
    assert summary is not None
    assert summary.property_ref.property_code is None


@pytest.mark.asyncio
async def test_rate_summary_prefers_active_booking() -> None:
    provider = _provider(_full_lookup())
    rate, errors = await provider.get_rate_summary(
        db_session=object(),
        property_ref=_property_ref(),
    )

    assert rate is not None
    assert rate.base_nightly_rate == Decimal("450.0")
    assert rate.cleaning_fee == Decimal("225.0")
    assert rate.taxes == Decimal("70.0")
    assert errors[-1].error_type == BookingFetchErrorType.PROVIDER_RETURNED_PARTIAL


@pytest.mark.asyncio
async def test_rate_summary_falls_back_to_booking_then_next_booking() -> None:
    payload = _full_lookup()
    payload["active_booking"] = None
    provider = _provider(payload)
    rate, _ = await provider.get_rate_summary(
        db_session=object(),
        property_ref=_property_ref(),
    )
    assert rate is not None
    assert rate.base_nightly_rate == Decimal("425.0")

    payload["booking"] = None
    provider = _provider(payload)
    rate, _ = await provider.get_rate_summary(
        db_session=object(),
        property_ref=_property_ref(),
    )
    assert rate is not None
    assert rate.base_nightly_rate == Decimal("475.0")


@pytest.mark.asyncio
async def test_rate_summary_without_booking_returns_not_found() -> None:
    provider = _provider({"lookup": {"property_code": "GULF_VIEW_204"}})
    rate, errors = await provider.get_rate_summary(
        db_session=object(),
        property_ref=_property_ref(),
    )
    assert rate is None
    assert errors[-1].error_type == BookingFetchErrorType.NOT_FOUND


@pytest.mark.asyncio
async def test_rate_summary_provenance_message_is_honest() -> None:
    provider = _provider(_full_lookup())
    _, errors = await provider.get_rate_summary(
        db_session=object(),
        property_ref=_property_ref(),
    )
    assert "booking history" in errors[-1].message.lower()
    assert "not authoritative current rate card" in errors[-1].message.lower()


@pytest.mark.asyncio
async def test_rate_summary_carries_cleaning_fee_through() -> None:
    provider = _provider(_full_lookup())
    rate, _ = await provider.get_rate_summary(
        db_session=object(),
        property_ref=_property_ref(),
    )
    assert rate is not None
    assert rate.cleaning_fee == Decimal("225.0")


@pytest.mark.asyncio
async def test_availability_raises_for_undeclared_capability() -> None:
    provider = _provider(_full_lookup())
    with pytest.raises(NotSupportedError):
        await provider.get_availability(
            db_session=object(),
            property_ref=_property_ref(),
            requested_start=__import__("datetime").date(2026, 7, 15),
            requested_end=__import__("datetime").date(2026, 7, 20),
        )


@pytest.mark.asyncio
async def test_provider_key_mismatch_raises_value_error() -> None:
    provider = _provider(_full_lookup(), provider_key="escapia")
    with pytest.raises(ValueError):
        await provider.get_property_summary(
            db_session=object(),
            property_ref=_property_ref(provider="guesty"),
        )


@pytest.mark.asyncio
async def test_non_dict_lookup_payload_fails_loudly_as_malformed() -> None:
    provider = _provider(["not", "a", "dict"])
    summary, errors = await provider.get_property_summary(
        db_session=object(),
        property_ref=_property_ref(),
    )
    assert summary is None
    assert errors[-1].error_type == BookingFetchErrorType.MALFORMED


@pytest.mark.asyncio
async def test_schema_sanity_surfaces_missing_amenity_key_through_features() -> None:
    payload = _full_lookup()
    payload["property"].pop("has_pool")
    provider = _provider(payload)
    summary, errors = await provider.get_property_summary(
        db_session=object(),
        property_ref=_property_ref(),
    )
    assert errors == []
    assert summary is not None
    assert "Pool" not in summary.key_features


@pytest.mark.asyncio
async def test_property_summary_preserves_ref_when_provider_snapshot_omits_provider() -> None:
    payload = _full_lookup()
    payload["property"]["provider"] = None
    provider = _provider(payload)
    summary, errors = await provider.get_property_summary(
        db_session=object(),
        property_ref=_property_ref(provider="escapia"),
    )
    assert errors == []
    assert summary is not None
    assert summary.property_ref.provider == "escapia"
