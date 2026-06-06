from __future__ import annotations

"""BookingDataProvider implementation backed by booking_context_adapters.py.

This provider is intentionally transitional. The contract is the durable piece;
the backing implementation currently wraps the canonical cache-backed lookup
adapter used elsewhere in the messaging brain.

Important honesty boundaries for this implementation:
  - It can translate property summary reliably from the adapter's `property`
    snapshot.
  - It can derive a *partial* rate summary from matched booking history.
  - It does not declare availability capability because the backing adapter
    reads listings/bookings cache tables only; it does not read a block-aware
    persisted calendar cache.
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Optional
from uuid import UUID

from app.services.connectors.booking_data_provider import (
    BookingDataCapability,
    BookingDataProvider,
    BookingFetchError,
    BookingFetchErrorType,
    BookingPropertyRef,
    NotSupportedError,
    PropertySummary,
    RateSummary,
)
from app.services.messaging.booking_context_adapters import (
    BookingContextAdapter,
    BookingContextAdapterConfig,
    build_booking_context_adapter,
)

_SOURCE_NAME = "canonical_booking_context_adapter"
_AMENITY_LABELS: tuple[tuple[str, str], ...] = (
    ("beach_access", "Beach access"),
    ("has_pool", "Pool"),
    ("has_hot_tub", "Hot tub"),
    ("pet_friendly", "Pet-friendly"),
)


def _to_decimal(value: Any) -> Optional[Decimal]:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (ArithmeticError, InvalidOperation, ValueError, TypeError):
        return None


@dataclass
class AdapterBackedBookingDataProvider(BookingDataProvider):
    """BookingDataProvider backed by the canonical booking-context adapter.

    The wrapped adapter is lookup-driven rather than calendar-query-driven.
    Property summary and booking-derived rate hints fit the contract well; true
    availability does not yet, so that capability is intentionally undeclared.

    The provider contract is property-keyed. Guest-email, phone, reservation id,
    and session-id lookup hints remain a concern of the lower booking-context
    adapter surface, not this normalized composer-facing contract.
    """

    company_id: UUID
    provider_key: str = "canonical"
    adapter: Optional[BookingContextAdapter] = None

    def __post_init__(self) -> None:
        if self.adapter is None:
            self.adapter = build_booking_context_adapter(
                BookingContextAdapterConfig(
                    company_id=self.company_id,
                    provider=self.provider_key,
                )
            )

    @property
    def provider(self) -> str:
        return self.provider_key

    @property
    def capabilities(self) -> frozenset[BookingDataCapability]:
        return frozenset(
            {
                BookingDataCapability.GET_PROPERTY_SUMMARY,
                BookingDataCapability.GET_RATE_SUMMARY,
            }
        )

    async def get_property_summary(
        self,
        *,
        db_session: object,
        property_ref: BookingPropertyRef,
    ) -> tuple[Optional[PropertySummary], list[BookingFetchError]]:
        lookup, errors = await self._lookup(db_session=db_session, property_ref=property_ref)
        if lookup is None:
            return None, errors

        raw_property = lookup.get("property")
        if raw_property is None:
            return None, errors + [
                BookingFetchError(
                    source=_SOURCE_NAME,
                    operation="get_property_summary",
                    error_type=BookingFetchErrorType.NOT_FOUND,
                    message="No property snapshot matched the requested property ref.",
                )
            ]

        summary = self._translate_property(raw_property, property_ref)
        if summary is None:
            return None, errors + [
                BookingFetchError(
                    source=_SOURCE_NAME,
                    operation="get_property_summary",
                    error_type=BookingFetchErrorType.MALFORMED,
                    message="Matched property snapshot was missing required fields.",
                )
            ]
        return summary, errors

    async def get_availability(
        self,
        *,
        db_session: object,
        property_ref: BookingPropertyRef,
        requested_start,
        requested_end,
    ):
        self._require(BookingDataCapability.GET_AVAILABILITY)
        raise NotSupportedError(
            f"{self.__class__.__name__} does not support {BookingDataCapability.GET_AVAILABILITY.value}"
        )

    async def get_rate_summary(
        self,
        *,
        db_session: object,
        property_ref: BookingPropertyRef,
        requested_start=None,
        requested_end=None,
    ) -> tuple[Optional[RateSummary], list[BookingFetchError]]:
        lookup, errors = await self._lookup(db_session=db_session, property_ref=property_ref)
        if lookup is None:
            return None, errors

        booking = lookup.get("active_booking") or lookup.get("booking") or lookup.get("next_booking")
        if not isinstance(booking, dict):
            return None, errors + [
                BookingFetchError(
                    source=_SOURCE_NAME,
                    operation="get_rate_summary",
                    error_type=BookingFetchErrorType.NOT_FOUND,
                    message="No matched booking with rate history was available.",
                )
            ]

        rate_ref = BookingPropertyRef(
            provider=property_ref.provider,
            provider_listing_id=property_ref.provider_listing_id,
            provider_unit_id=property_ref.provider_unit_id,
            property_code=property_ref.property_code or lookup.get("lookup", {}).get("property_code"),
        )
        summary = RateSummary(
            property_ref=rate_ref,
            currency="USD",
            base_nightly_rate=_to_decimal(booking.get("nightly_rate")),
            cleaning_fee=_to_decimal(booking.get("cleaning_fee")),
            taxes=_to_decimal(booking.get("taxes")),
            pricing_notes="Derived from matched booking history; not authoritative current rate card.",
        )
        errors = errors + [
            BookingFetchError(
                source=_SOURCE_NAME,
                operation="get_rate_summary",
                error_type=BookingFetchErrorType.PROVIDER_RETURNED_PARTIAL,
                message="Rate inferred from booking history; not authoritative current rate card.",
            )
        ]
        return summary, errors

    async def _lookup(
        self,
        *,
        db_session: object,
        property_ref: BookingPropertyRef,
    ) -> tuple[Optional[dict[str, Any]], list[BookingFetchError]]:
        if property_ref.provider != self.provider_key:
            raise ValueError(
                f"AdapterBackedBookingDataProvider expected provider={self.provider_key!r}, "
                f"got {property_ref.provider!r}"
            )

        # Lazy import keeps the implementation cheap to import for tests and
        # contract-only consumers.
        from app.services.messaging.booking_context_adapters import BookingContextLookup

        try:
            lookup = await self.adapter.lookup(
                db_session,  # type: ignore[arg-type]
                BookingContextLookup(property_code=property_ref.property_code),
            )
            if not isinstance(lookup, dict):
                return None, [
                    BookingFetchError(
                        source=_SOURCE_NAME,
                        operation="lookup",
                        error_type=BookingFetchErrorType.MALFORMED,
                        message="Adapter lookup returned a non-dict payload.",
                    )
                ]
            return lookup, []
        except Exception as exc:  # noqa: BLE001
            return None, [
                BookingFetchError(
                    source=_SOURCE_NAME,
                    operation="lookup",
                    error_type=BookingFetchErrorType.PROVIDER_RETURNED_ERROR,
                    message=str(exc),
                )
            ]

    def _translate_property(
        self,
        raw_property: Any,
        requested_ref: BookingPropertyRef,
    ) -> Optional[PropertySummary]:
        if not isinstance(raw_property, dict):
            return None
        display_name = raw_property.get("property_name")
        if not display_name:
            return None

        provider = str(raw_property.get("provider") or requested_ref.provider or self.provider_key)
        property_code = raw_property.get("property_code") or requested_ref.property_code
        city = raw_property.get("city")
        state = raw_property.get("state")

        address_summary = None
        if city and state:
            address_summary = f"{city}, {state}"
        elif city:
            address_summary = str(city)
        elif state:
            address_summary = str(state)

        key_features: list[str] = []
        for key, label in _AMENITY_LABELS:
            value = raw_property.get(key)
            if not value:
                continue
            if key == "beach_access" and isinstance(value, str) and value.strip():
                key_features.append(f"{label} ({value.strip()})")
            else:
                key_features.append(label)

        bedrooms = raw_property.get("bedrooms")
        bedrooms_int = int(bedrooms) if isinstance(bedrooms, (int, float)) else None

        return PropertySummary(
            property_ref=BookingPropertyRef(
                provider=provider,
                provider_listing_id=None,
                provider_unit_id=requested_ref.provider_unit_id,
                property_code=property_code,
            ),
            display_name=str(display_name),
            bedrooms=bedrooms_int,
            bathrooms=_to_decimal(raw_property.get("bathrooms")),
            max_occupancy=None,
            property_type=raw_property.get("property_type"),
            address_summary=address_summary,
            key_features=tuple(key_features),
        )


__all__ = ["AdapterBackedBookingDataProvider"]
