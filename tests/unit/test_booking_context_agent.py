from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.services.connectors.booking_data_provider import (
    AvailabilityWindow,
    BookingDataCapability,
    BookingDataProvider,
    BookingFetchError,
    BookingFetchErrorType,
    BookingPropertyRef,
    PropertySummary,
    RateSummary,
)
from app.services.messaging_brain.agents.booking_context_agent import (
    AGENT_ERROR_SOURCE,
    BookingContextAgent,
)
from app.services.messaging_brain.booking_context_types import RequestedStay


class _FakeProvider(BookingDataProvider):
    def __init__(
        self,
        *,
        capabilities: frozenset[BookingDataCapability],
        property_summary: PropertySummary | None = None,
        property_errors: list[BookingFetchError] | None = None,
        rate_summary: RateSummary | None = None,
        rate_errors: list[BookingFetchError] | None = None,
        availability: AvailabilityWindow | None = None,
        availability_errors: list[BookingFetchError] | None = None,
    ) -> None:
        self._capabilities = capabilities
        self._property_summary = property_summary
        self._property_errors = property_errors or []
        self._rate_summary = rate_summary
        self._rate_errors = rate_errors or []
        self._availability = availability
        self._availability_errors = availability_errors or []
        self.calls: list[tuple[str, dict]] = []

    @property
    def provider(self) -> str:
        return "fake"

    @property
    def capabilities(self) -> frozenset[BookingDataCapability]:
        return self._capabilities

    async def get_property_summary(self, **kwargs):
        self.calls.append(("property", kwargs))
        return self._property_summary, list(self._property_errors)

    async def get_rate_summary(self, **kwargs):
        self.calls.append(("rate", kwargs))
        return self._rate_summary, list(self._rate_errors)

    async def get_availability(self, **kwargs):
        self.calls.append(("availability", kwargs))
        return self._availability, list(self._availability_errors)


def _property_ref() -> BookingPropertyRef:
    return BookingPropertyRef(provider="fake", property_code="GULF_VIEW_204")


def _property_summary() -> PropertySummary:
    return PropertySummary(
        property_ref=_property_ref(),
        display_name="Gulf View 204",
        bedrooms=3,
    )


def _rate_summary() -> RateSummary:
    return RateSummary(
        property_ref=_property_ref(),
        base_nightly_rate=Decimal("425.00"),
        cleaning_fee=Decimal("210.00"),
    )


def _requested_stay() -> RequestedStay:
    return RequestedStay(
        check_in=date(2026, 7, 15),
        check_out=date(2026, 7, 20),
        nights=5,
        guests=4,
    )


@pytest.mark.asyncio
async def test_build_happy_path_accumulates_property_and_rate_context() -> None:
    provider = _FakeProvider(
        capabilities=frozenset(
            {
                BookingDataCapability.GET_PROPERTY_SUMMARY,
                BookingDataCapability.GET_RATE_SUMMARY,
            }
        ),
        property_summary=_property_summary(),
        rate_summary=_rate_summary(),
        rate_errors=[
            BookingFetchError(
                source="fake_provider",
                operation="get_rate_summary",
                error_type=BookingFetchErrorType.PROVIDER_RETURNED_PARTIAL,
                message="Rate inferred from booking history.",
            )
        ],
    )
    agent = BookingContextAgent(data_provider=provider, db_session=object())

    context = await agent.build(
        property_ref=_property_ref(),
        requested_stay=_requested_stay(),
        triggered_by="availability_keyword",
    )

    assert context.property_summary == _property_summary()
    assert context.rate_summary == _rate_summary()
    assert context.requested_stay == _requested_stay()
    assert context.triggered_by == "availability_keyword"
    assert len(context.fetch_errors) == 1
    assert context.fetch_errors[0].source == "fake_provider"


@pytest.mark.asyncio
async def test_build_returns_structured_error_when_property_missing() -> None:
    provider = _FakeProvider(capabilities=frozenset({BookingDataCapability.GET_PROPERTY_SUMMARY}))
    agent = BookingContextAgent(data_provider=provider, db_session=object())

    context = await agent.build(
        property_ref=None,
        requested_stay=_requested_stay(),
        triggered_by="date_range_detected",
    )

    assert context.property_ref is None
    assert context.property_summary is None
    assert context.fetch_errors[0].source == AGENT_ERROR_SOURCE
    assert context.fetch_errors[0].error_type == BookingFetchErrorType.NOT_FOUND
    assert provider.calls == []


@pytest.mark.asyncio
async def test_build_skips_rate_when_capability_missing() -> None:
    provider = _FakeProvider(
        capabilities=frozenset({BookingDataCapability.GET_PROPERTY_SUMMARY}),
        property_summary=_property_summary(),
    )
    agent = BookingContextAgent(data_provider=provider, db_session=object())

    context = await agent.build(
        property_ref=_property_ref(),
        requested_stay=_requested_stay(),
        triggered_by="group_size_keyword",
    )

    assert context.rate_summary is None
    assert [name for name, _ in provider.calls] == ["property"]


@pytest.mark.asyncio
async def test_build_skips_availability_when_capability_missing() -> None:
    provider = _FakeProvider(
        capabilities=frozenset({BookingDataCapability.GET_PROPERTY_SUMMARY}),
        property_summary=_property_summary(),
    )
    agent = BookingContextAgent(data_provider=provider, db_session=object())

    context = await agent.build(
        property_ref=_property_ref(),
        requested_stay=_requested_stay(),
        triggered_by="availability_keyword",
    )

    assert context.availability is None
    assert [name for name, _ in provider.calls] == ["property"]


@pytest.mark.asyncio
async def test_build_adds_partial_error_when_availability_supported_but_dates_missing() -> None:
    provider = _FakeProvider(
        capabilities=frozenset(
            {
                BookingDataCapability.GET_PROPERTY_SUMMARY,
                BookingDataCapability.GET_AVAILABILITY,
            }
        ),
        property_summary=_property_summary(),
    )
    agent = BookingContextAgent(data_provider=provider, db_session=object())

    context = await agent.build(
        property_ref=_property_ref(),
        requested_stay=RequestedStay(),
        triggered_by="availability_keyword",
    )

    assert context.availability is None
    assert any(err.source == AGENT_ERROR_SOURCE for err in context.fetch_errors)
    assert [name for name, _ in provider.calls] == ["property"]


@pytest.mark.asyncio
async def test_build_skips_availability_when_no_requested_stay_at_all() -> None:
    provider = _FakeProvider(
        capabilities=frozenset(
            {
                BookingDataCapability.GET_PROPERTY_SUMMARY,
                BookingDataCapability.GET_AVAILABILITY,
            }
        ),
        property_summary=_property_summary(),
    )
    agent = BookingContextAgent(data_provider=provider, db_session=object())

    context = await agent.build(
        property_ref=_property_ref(),
        requested_stay=None,
        triggered_by="availability_keyword",
    )

    assert context.availability is None
    assert any("missing" in err.message.lower() for err in context.fetch_errors)
    assert [name for name, _ in provider.calls] == ["property"]


@pytest.mark.asyncio
async def test_build_calls_availability_when_supported_and_dates_present() -> None:
    availability = AvailabilityWindow(
        property_ref=_property_ref(),
        requested_start=date(2026, 7, 15),
        requested_end=date(2026, 7, 20),
    )
    provider = _FakeProvider(
        capabilities=frozenset(
            {
                BookingDataCapability.GET_PROPERTY_SUMMARY,
                BookingDataCapability.GET_AVAILABILITY,
            }
        ),
        property_summary=_property_summary(),
        availability=availability,
    )
    agent = BookingContextAgent(data_provider=provider, db_session=object())

    context = await agent.build(
        property_ref=_property_ref(),
        requested_stay=_requested_stay(),
        triggered_by="date_range_detected",
    )

    assert context.availability == availability
    assert [name for name, _ in provider.calls] == ["property", "availability"]


@pytest.mark.asyncio
async def test_build_passes_through_property_errors() -> None:
    provider = _FakeProvider(
        capabilities=frozenset({BookingDataCapability.GET_PROPERTY_SUMMARY}),
        property_errors=[
            BookingFetchError(
                source="fake_provider",
                operation="get_property_summary",
                error_type=BookingFetchErrorType.MALFORMED,
                message="bad shape",
            )
        ],
    )
    agent = BookingContextAgent(data_provider=provider, db_session=object())

    context = await agent.build(
        property_ref=_property_ref(),
        requested_stay=_requested_stay(),
        triggered_by="availability_keyword",
    )

    assert len(context.fetch_errors) == 1
    assert context.fetch_errors[0].message == "bad shape"


@pytest.mark.asyncio
async def test_build_passes_through_rate_errors() -> None:
    provider = _FakeProvider(
        capabilities=frozenset(
            {
                BookingDataCapability.GET_PROPERTY_SUMMARY,
                BookingDataCapability.GET_RATE_SUMMARY,
            }
        ),
        property_summary=_property_summary(),
        rate_errors=[
            BookingFetchError(
                source="fake_provider",
                operation="get_rate_summary",
                error_type=BookingFetchErrorType.PROVIDER_RETURNED_ERROR,
                message="rate source unavailable",
            )
        ],
    )
    agent = BookingContextAgent(data_provider=provider, db_session=object())

    context = await agent.build(
        property_ref=_property_ref(),
        requested_stay=_requested_stay(),
        triggered_by="availability_keyword",
    )

    assert any(err.message == "rate source unavailable" for err in context.fetch_errors)


@pytest.mark.asyncio
async def test_build_passes_requested_stay_through_unchanged() -> None:
    provider = _FakeProvider(
        capabilities=frozenset({BookingDataCapability.GET_PROPERTY_SUMMARY}),
        property_summary=_property_summary(),
    )
    agent = BookingContextAgent(data_provider=provider, db_session=object())
    stay = _requested_stay()

    context = await agent.build(
        property_ref=_property_ref(),
        requested_stay=stay,
        triggered_by="date_range_detected",
    )

    assert context.requested_stay == stay


@pytest.mark.asyncio
async def test_build_passes_triggered_by_through_unchanged() -> None:
    provider = _FakeProvider(
        capabilities=frozenset({BookingDataCapability.GET_PROPERTY_SUMMARY}),
        property_summary=_property_summary(),
    )
    agent = BookingContextAgent(data_provider=provider, db_session=object())

    context = await agent.build(
        property_ref=_property_ref(),
        requested_stay=None,
        triggered_by="group_size_keyword",
    )

    assert context.triggered_by == "group_size_keyword"


@pytest.mark.asyncio
async def test_build_uses_requested_dates_when_fetching_rate_summary() -> None:
    provider = _FakeProvider(
        capabilities=frozenset(
            {
                BookingDataCapability.GET_PROPERTY_SUMMARY,
                BookingDataCapability.GET_RATE_SUMMARY,
            }
        ),
        property_summary=_property_summary(),
        rate_summary=_rate_summary(),
    )
    agent = BookingContextAgent(data_provider=provider, db_session=object())
    stay = _requested_stay()

    await agent.build(
        property_ref=_property_ref(),
        requested_stay=stay,
        triggered_by="availability_keyword",
    )

    _, kwargs = provider.calls[1]
    assert kwargs["requested_start"] == stay.check_in
    assert kwargs["requested_end"] == stay.check_out


@pytest.mark.asyncio
async def test_build_allows_missing_requested_dates_for_rate_lookup() -> None:
    provider = _FakeProvider(
        capabilities=frozenset(
            {
                BookingDataCapability.GET_PROPERTY_SUMMARY,
                BookingDataCapability.GET_RATE_SUMMARY,
            }
        ),
        property_summary=_property_summary(),
        rate_summary=_rate_summary(),
    )
    agent = BookingContextAgent(data_provider=provider, db_session=object())

    await agent.build(
        property_ref=_property_ref(),
        requested_stay=None,
        triggered_by="availability_keyword",
    )

    _, kwargs = provider.calls[1]
    assert kwargs["requested_start"] is None
    assert kwargs["requested_end"] is None


@pytest.mark.asyncio
async def test_build_keeps_partial_context_when_summary_missing_but_rate_exists() -> None:
    provider = _FakeProvider(
        capabilities=frozenset(
            {
                BookingDataCapability.GET_PROPERTY_SUMMARY,
                BookingDataCapability.GET_RATE_SUMMARY,
            }
        ),
        property_summary=None,
        property_errors=[
            BookingFetchError(
                source="fake_provider",
                operation="get_property_summary",
                error_type=BookingFetchErrorType.NOT_FOUND,
                message="no summary",
            )
        ],
        rate_summary=_rate_summary(),
    )
    agent = BookingContextAgent(data_provider=provider, db_session=object())

    context = await agent.build(
        property_ref=_property_ref(),
        requested_stay=_requested_stay(),
        triggered_by="availability_keyword",
    )

    assert context.property_summary is None
    assert context.rate_summary == _rate_summary()
    assert any(err.message == "no summary" for err in context.fetch_errors)


@pytest.mark.asyncio
async def test_build_orders_calls_property_then_rate_then_availability() -> None:
    availability = AvailabilityWindow(
        property_ref=_property_ref(),
        requested_start=date(2026, 7, 15),
        requested_end=date(2026, 7, 20),
    )
    provider = _FakeProvider(
        capabilities=frozenset(
            {
                BookingDataCapability.GET_PROPERTY_SUMMARY,
                BookingDataCapability.GET_RATE_SUMMARY,
                BookingDataCapability.GET_AVAILABILITY,
            }
        ),
        property_summary=_property_summary(),
        rate_summary=_rate_summary(),
        availability=availability,
    )
    agent = BookingContextAgent(data_provider=provider, db_session=object())

    await agent.build(
        property_ref=_property_ref(),
        requested_stay=_requested_stay(),
        triggered_by="availability_keyword",
    )

    assert [name for name, _ in provider.calls] == ["property", "rate", "availability"]
