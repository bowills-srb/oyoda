from __future__ import annotations

"""Assemble composer-facing booking context from a BookingDataProvider.

NOT A SECOND BOOKING PATH. There is one canonical booking-read source
(CanonicalBookingContextAdapter, reading pms_bookings/pms_listings). This agent
is the per-request ORCHESTRATOR over a BookingDataProvider; the provider
abstraction is the deliberate seam for multi-PMS support (each PMS = a new
provider_key/implementation behind the same contract, not a new path). Do not
"consolidate" this away as a duplicate — the invariant is enforced by
test_booking_data_provider_per_request_isolation in test_brain_invariants.py.

This agent is intentionally narrow:
  - trigger decisions happen upstream
  - requested-stay parsing happens upstream
  - property resolution happens upstream

Given those inputs, the agent orchestrates provider calls, accumulates partial
errors, and returns a stable BookingContext payload suitable for writing into
the pre-booking context overlay.

Every real BookingDataProvider is expected to support property summary. The
agent therefore calls `get_property_summary()` unconditionally when a property
ref is present. Providers that violate that expectation should fail loudly so
the provider implementation gets fixed rather than silently degrading the
contract.
"""

from dataclasses import replace
from typing import Optional

from app.services.connectors.booking_data_provider import (
    BookingDataCapability,
    BookingDataProvider,
    BookingFetchError,
    BookingFetchErrorType,
    BookingPropertyRef,
)
from app.services.messaging_brain.booking_context_types import (
    BookingContext,
    RequestedStay,
)

AGENT_ERROR_SOURCE = "booking_context_agent"


class BookingContextAgent:
    """Orchestrates BookingDataProvider calls into one BookingContext."""

    def __init__(self, *, data_provider: BookingDataProvider, db_session: object) -> None:
        self._data_provider = data_provider
        self._db_session = db_session

    async def build(
        self,
        *,
        property_ref: Optional[BookingPropertyRef],
        requested_stay: Optional[RequestedStay],
        triggered_by: Optional[str],
    ) -> BookingContext:
        if property_ref is None:
            return BookingContext(
                property_ref=None,
                requested_stay=requested_stay,
                triggered_by=triggered_by,
                fetch_errors=(
                    BookingFetchError(
                        source=AGENT_ERROR_SOURCE,
                        operation="build",
                        error_type=BookingFetchErrorType.NOT_FOUND,
                        message="Property could not be resolved for booking-context lookup.",
                    ),
                ),
            )

        property_summary, property_errors = await self._data_provider.get_property_summary(
            db_session=self._db_session,
            property_ref=property_ref,
        )

        context = BookingContext(
            property_ref=property_ref,
            property_summary=property_summary,
            requested_stay=requested_stay,
            triggered_by=triggered_by,
            fetch_errors=tuple(property_errors),
        )

        if self._data_provider.supports(BookingDataCapability.GET_RATE_SUMMARY):
            rate_summary, rate_errors = await self._data_provider.get_rate_summary(
                db_session=self._db_session,
                property_ref=property_ref,
                requested_start=requested_stay.check_in if requested_stay else None,
                requested_end=requested_stay.check_out if requested_stay else None,
            )
            context = replace(
                context,
                rate_summary=rate_summary,
                fetch_errors=context.fetch_errors + tuple(rate_errors),
            )

        if self._data_provider.supports(BookingDataCapability.GET_AVAILABILITY):
            if requested_stay and requested_stay.check_in and requested_stay.check_out:
                availability, availability_errors = await self._data_provider.get_availability(
                    db_session=self._db_session,
                    property_ref=property_ref,
                    requested_start=requested_stay.check_in,
                    requested_end=requested_stay.check_out,
                )
                context = replace(
                    context,
                    availability=availability,
                    fetch_errors=context.fetch_errors + tuple(availability_errors),
                )
            else:
                context = replace(
                    context,
                    fetch_errors=context.fetch_errors
                    + (
                        BookingFetchError(
                            source=AGENT_ERROR_SOURCE,
                            operation="build",
                            error_type=BookingFetchErrorType.PROVIDER_RETURNED_PARTIAL,
                            message="Availability lookup supported but requested stay dates were missing.",
                        ),
                    ),
                )

        return context


__all__ = ["AGENT_ERROR_SOURCE", "BookingContextAgent"]
