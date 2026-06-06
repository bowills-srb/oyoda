from __future__ import annotations

"""Provider-agnostic booking data contract for composer-facing context.

This module defines the normalized booking-data surface the messaging brain
can depend on without knowing whether facts come from canonical cache tables,
live PMS APIs, or another provider-backed source.

Availability windows use an exclusive end-date convention: a request for
`2026-07-15` to `2026-07-20` covers the nights of the 15th, 16th, 17th, 18th,
and 19th, with checkout on the 20th.
"""

from abc import ABC
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Optional, Sequence


class AvailabilityStatus(str, Enum):
    """Normalized availability state for one calendar date."""

    AVAILABLE = "available"
    BOOKED = "booked"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


class BookingFetchErrorType(str, Enum):
    """Typed categories for partial/failed provider fetches."""

    NOT_FOUND = "not_found"
    PROVIDER_RETURNED_ERROR = "provider_returned_error"
    PROVIDER_RETURNED_PARTIAL = "provider_returned_partial"
    MALFORMED = "malformed"


class BookingDataCapability(str, Enum):
    """Capabilities exposed by a BookingDataProvider implementation."""

    GET_PROPERTY_SUMMARY = "get_property_summary"
    GET_AVAILABILITY = "get_availability"
    GET_RATE_SUMMARY = "get_rate_summary"


class NotSupportedError(RuntimeError):
    """Raised when a provider does not support a booking-data operation."""


@dataclass(frozen=True)
class BookingFetchError:
    """Structured fetch warning/error returned alongside partial data."""

    source: str
    operation: str
    error_type: BookingFetchErrorType
    message: str


@dataclass(frozen=True)
class BookingPropertyRef:
    """Minimal property identity needed for booking-context enrichment.

    `provider_listing_id` is intentionally optional. Some upstream paths only
    resolve a stable operator-facing `property_code` plus provider name; they do
    not yet surface a canonical provider listing id.
    """

    provider: str
    provider_listing_id: Optional[str] = None
    provider_unit_id: Optional[str] = None
    property_code: Optional[str] = None


@dataclass(frozen=True)
class PropertySummary:
    """Compact property snapshot safe for pre-booking reply composition."""

    property_ref: BookingPropertyRef
    display_name: str
    bedrooms: Optional[int] = None
    bathrooms: Optional[Decimal] = None
    max_occupancy: Optional[int] = None
    property_type: Optional[str] = None
    address_summary: Optional[str] = None
    key_features: Sequence[str] = field(default_factory=tuple)


@dataclass(frozen=True)
class AvailabilityDay:
    """Availability/pricing facts for one calendar date."""

    day: date
    status: AvailabilityStatus
    nightly_rate: Optional[Decimal] = None
    minimum_stay: Optional[int] = None
    block_reason: Optional[str] = None


@dataclass(frozen=True)
class AvailabilityWindow:
    """Availability facts for a requested date window.

    `requested_end` is exclusive.
    """

    property_ref: BookingPropertyRef
    requested_start: date
    requested_end: date
    days: Sequence[AvailabilityDay] = field(default_factory=tuple)
    currency: str = "USD"


@dataclass(frozen=True)
class RateSummary:
    """Compact rate context for a property or requested stay."""

    property_ref: BookingPropertyRef
    currency: str = "USD"
    base_nightly_rate: Optional[Decimal] = None
    cleaning_fee: Optional[Decimal] = None
    taxes: Optional[Decimal] = None
    pricing_notes: Optional[str] = None


class BookingDataProvider(ABC):
    """Async contract for booking-context data providers.

    Implementations may hit live PMS APIs, canonical cache tables, or other
    provider-backed sources. Callers should plan against `capabilities` and
    expect soft-fail tuples of `(data, fetch_errors)` rather than hard failures
    for ordinary provider misses or partial responses.
    """

    @property
    def provider(self) -> str:
        """Stable provider key such as `escapia`, `guesty`, or `track`."""
        raise NotImplementedError

    @property
    def capabilities(self) -> frozenset[BookingDataCapability]:
        """Declared provider capabilities for caller-side planning."""
        raise NotImplementedError

    def supports(self, capability: BookingDataCapability) -> bool:
        return capability in self.capabilities

    def _require(self, capability: BookingDataCapability) -> None:
        if capability not in self.capabilities:
            raise NotSupportedError(
                f"{self.__class__.__name__} does not support {capability.value}"
            )

    async def get_property_summary(
        self,
        *,
        db_session: object,
        property_ref: BookingPropertyRef,
    ) -> tuple[Optional[PropertySummary], list[BookingFetchError]]:
        self._require(BookingDataCapability.GET_PROPERTY_SUMMARY)
        raise NotSupportedError(
            f"{self.__class__.__name__} must override get_property_summary()"
        )

    async def get_availability(
        self,
        *,
        db_session: object,
        property_ref: BookingPropertyRef,
        requested_start: date,
        requested_end: date,
    ) -> tuple[Optional[AvailabilityWindow], list[BookingFetchError]]:
        self._require(BookingDataCapability.GET_AVAILABILITY)
        raise NotSupportedError(
            f"{self.__class__.__name__} must override get_availability()"
        )

    async def get_rate_summary(
        self,
        *,
        db_session: object,
        property_ref: BookingPropertyRef,
        requested_start: Optional[date] = None,
        requested_end: Optional[date] = None,
    ) -> tuple[Optional[RateSummary], list[BookingFetchError]]:
        self._require(BookingDataCapability.GET_RATE_SUMMARY)
        raise NotSupportedError(
            f"{self.__class__.__name__} must override get_rate_summary()"
        )


__all__ = [
    "AvailabilityDay",
    "AvailabilityStatus",
    "AvailabilityWindow",
    "BookingDataCapability",
    "BookingDataProvider",
    "BookingFetchError",
    "BookingFetchErrorType",
    "BookingPropertyRef",
    "NotSupportedError",
    "PropertySummary",
    "RateSummary",
]
