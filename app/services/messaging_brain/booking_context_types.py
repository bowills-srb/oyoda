from __future__ import annotations

"""Composer-facing booking context payloads and overlay helpers.

Scope boundary
--------------
BookingContext carries PMS-derived booking/property facts plus upstream-derived
requested-stay information for the pre-booking composer path.

It deliberately does *not* duplicate operator guidance / house-rules text.
That context already flows through:

    app.services.messaging_brain.context.operator_guidance.load_operator_guidance()
        -> ContextBuilderAgent
        -> GuestContextBundle.operator_guidance

Keeping operator guidance on its existing path prevents double-loading the same
operator-authored notes through two parallel seams.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Any, MutableMapping, Optional

from app.services.connectors.booking_data_provider import (
    AvailabilityWindow,
    BookingFetchError,
    BookingPropertyRef,
    PropertySummary,
    RateSummary,
)


@dataclass(frozen=True)
class RequestedStay:
    """Requested stay information parsed from the inbound guest message.

    `check_out` is exclusive when both dates are present. `nights` should agree
    with `(check_out - check_in).days` when all three are populated, but this is
    intentionally not enforced here: contradictory guest wording is useful for
    the composer to see and clarify.
    """

    check_in: Optional[date] = None
    check_out: Optional[date] = None
    nights: Optional[int] = None
    guests: Optional[int] = None


@dataclass(frozen=True)
class BookingContext:
    """Final booking context block injected into the brain overlay.

    `triggered_by` is instrumentation only. Current expected values include:
    `availability_keyword`, `group_size_keyword`, and `date_range_detected`.
    Callers should not branch business logic on it.
    """

    property_ref: Optional[BookingPropertyRef] = None
    property_summary: Optional[PropertySummary] = None
    availability: Optional[AvailabilityWindow] = None
    rate_summary: Optional[RateSummary] = None
    requested_stay: Optional[RequestedStay] = None
    fetch_errors: tuple[BookingFetchError, ...] = field(default_factory=tuple)
    triggered_by: Optional[str] = None


BOOKING_CONTEXT_OVERLAY_KEY = "booking_context"


def write_booking_context_overlay(
    overlay: MutableMapping[str, Any],
    context: BookingContext,
) -> None:
    overlay[BOOKING_CONTEXT_OVERLAY_KEY] = context


def read_booking_context_overlay(
    overlay: MutableMapping[str, Any] | None,
) -> Optional[BookingContext]:
    """Return the typed booking context, or None for missing/stale values."""

    if not overlay:
        return None
    value = overlay.get(BOOKING_CONTEXT_OVERLAY_KEY)
    if isinstance(value, BookingContext):
        return value
    return None


def has_booking_context_overlay(overlay: MutableMapping[str, Any] | None) -> bool:
    return read_booking_context_overlay(overlay) is not None


def clear_booking_context_overlay(overlay: MutableMapping[str, Any]) -> None:
    overlay.pop(BOOKING_CONTEXT_OVERLAY_KEY, None)


__all__ = [
    "BOOKING_CONTEXT_OVERLAY_KEY",
    "BookingContext",
    "RequestedStay",
    "clear_booking_context_overlay",
    "has_booking_context_overlay",
    "read_booking_context_overlay",
    "write_booking_context_overlay",
]
