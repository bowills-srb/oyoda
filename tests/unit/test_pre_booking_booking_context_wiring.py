from __future__ import annotations

import logging
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.connectors.booking_data_provider import (
    BookingFetchError,
    BookingFetchErrorType,
    BookingPropertyRef,
)
from app.services.messaging_brain.booking_context_types import (
    BookingContext,
    read_booking_context_overlay,
)
from app.services.messaging_brain.pre_booking import (
    EscapiaContextAdapter,
    EscapiaContextPayload,
    _build_property_ref_from_inquiry,
    _build_requested_stay_from_inquiry,
    _looks_like_booking_inquiry,
)


def _make_inquiry(**overrides):
    base = dict(
        inquiry_id="inq-001",
        tenant_id="11111111-1111-1111-1111-111111111111",
        channel="email",
        transport_provider="gmail",
        context_provider="escapia",
        platform="vrbo",
        guest_name="Taylor",
        message_text="Is this available for July 15 to July 20?",
        property_code="GULF_VIEW_204",
        message_id="msg-001",
        thread_id="thread-001",
        guest_email="guest@example.com",
        guest_phone="",
        reservation_id="",
        requested_check_in=date(2026, 7, 15),
        requested_check_out=date(2026, 7, 20),
        requested_guests=4,
        metadata={"provider_property_id": "escapia-prop-204"},
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_predicate_short_circuits_on_parsed_dates():
    triggered, reason = _looks_like_booking_inquiry(_make_inquiry())
    assert triggered is True
    assert reason == "date_range_detected"


def test_predicate_matches_availability_keywords_without_dates():
    inquiry = _make_inquiry(
        requested_check_in=None,
        requested_check_out=None,
        message_text="Do you have anything available next month?",
    )
    triggered, reason = _looks_like_booking_inquiry(inquiry)
    assert triggered is True
    assert reason == "availability_keyword"


def test_predicate_matches_group_size_keywords():
    inquiry = _make_inquiry(
        requested_check_in=None,
        requested_check_out=None,
        message_text="Can it fit 10 people?",
    )
    triggered, reason = _looks_like_booking_inquiry(inquiry)
    assert triggered is True
    assert reason == "group_size_keyword"


def test_predicate_returns_false_when_no_signal():
    inquiry = _make_inquiry(
        requested_check_in=None,
        requested_check_out=None,
        requested_guests=None,
        message_text="Thanks so much for the quick reply.",
    )
    triggered, reason = _looks_like_booking_inquiry(inquiry)
    assert triggered is False
    assert reason is None


def test_build_property_ref_from_inquiry_uses_property_code_and_provider_property_id():
    ref = _build_property_ref_from_inquiry(_make_inquiry(), provider="escapia")
    assert ref == BookingPropertyRef(
        provider="escapia",
        provider_listing_id="escapia-prop-204",
        property_code="GULF_VIEW_204",
    )


def test_build_property_ref_from_inquiry_returns_none_when_unresolved():
    ref = _build_property_ref_from_inquiry(
        _make_inquiry(property_code="", metadata={}),
        provider="escapia",
    )
    assert ref is None


def test_build_requested_stay_from_inquiry_derives_nights():
    stay = _build_requested_stay_from_inquiry(_make_inquiry())
    assert stay is not None
    assert stay.nights == 5
    assert stay.guests == 4


def test_build_requested_stay_from_inquiry_ignores_inverted_dates_for_nights():
    stay = _build_requested_stay_from_inquiry(
        _make_inquiry(
            requested_check_in=date(2026, 7, 20),
            requested_check_out=date(2026, 7, 15),
        )
    )
    assert stay is not None
    assert stay.nights is None


def test_build_requested_stay_from_inquiry_returns_none_when_no_data():
    stay = _build_requested_stay_from_inquiry(
        _make_inquiry(
            requested_check_in=None,
            requested_check_out=None,
            requested_guests=None,
        )
    )
    assert stay is None


def test_constructor_warns_when_agent_missing(caplog):
    with caplog.at_level(logging.WARNING):
        EscapiaContextAdapter()
    assert "booking_context_agent" in caplog.text


@pytest.mark.asyncio
async def test_load_context_leaves_overlay_unchanged_when_predicate_false():
    agent = AsyncMock()
    adapter = EscapiaContextAdapter(booking_context_agent=agent)
    inquiry = _make_inquiry(
        requested_check_in=None,
        requested_check_out=None,
        requested_guests=None,
        message_text="Thanks again for the details.",
    )

    envelope = await adapter.load_context(
        inquiry=inquiry,
        payload=EscapiaContextPayload(property_data={"wifi": "yes"}, operator_policies={}),
        db_session=object(),
    )

    assert read_booking_context_overlay(envelope.overlay) is None
    agent.build.assert_not_called()


@pytest.mark.asyncio
async def test_load_context_writes_booking_context_overlay_when_triggered():
    booking_context = BookingContext(triggered_by="date_range_detected")
    agent = AsyncMock()
    agent.build = AsyncMock(return_value=booking_context)
    adapter = EscapiaContextAdapter(booking_context_agent=agent)

    envelope = await adapter.load_context(
        inquiry=_make_inquiry(),
        payload=EscapiaContextPayload(property_data={}, operator_policies={}),
        db_session=object(),
    )

    assert read_booking_context_overlay(envelope.overlay) == booking_context
    agent.build.assert_awaited_once()


@pytest.mark.asyncio
async def test_load_context_passes_none_property_ref_when_no_identifiers():
    booking_context = BookingContext(
        triggered_by="availability_keyword",
        fetch_errors=(
            BookingFetchError(
                source="booking_context_agent",
                operation="build",
                error_type=BookingFetchErrorType.NOT_FOUND,
                message="Property could not be resolved for booking-context lookup.",
            ),
        ),
    )
    agent = AsyncMock()
    agent.build = AsyncMock(return_value=booking_context)
    adapter = EscapiaContextAdapter(booking_context_agent=agent)

    inquiry = _make_inquiry(
        property_code="",
        metadata={},
        requested_check_in=None,
        requested_check_out=None,
        message_text="Do you have anything available next month?",
    )
    await adapter.load_context(
        inquiry=inquiry,
        payload=EscapiaContextPayload(),
        db_session=object(),
    )

    _, kwargs = agent.build.await_args
    assert kwargs["property_ref"] is None


@pytest.mark.asyncio
async def test_load_context_builds_requested_stay_for_agent():
    booking_context = BookingContext(triggered_by="date_range_detected")
    agent = AsyncMock()
    agent.build = AsyncMock(return_value=booking_context)
    adapter = EscapiaContextAdapter(booking_context_agent=agent)

    await adapter.load_context(
        inquiry=_make_inquiry(),
        payload=EscapiaContextPayload(),
        db_session=object(),
    )

    _, kwargs = agent.build.await_args
    stay = kwargs["requested_stay"]
    assert stay is not None
    assert stay.check_in == date(2026, 7, 15)
    assert stay.check_out == date(2026, 7, 20)
    assert stay.nights == 5
    assert stay.guests == 4


@pytest.mark.asyncio
async def test_load_context_passes_trigger_reason_to_agent():
    booking_context = BookingContext(triggered_by="group_size_keyword")
    agent = AsyncMock()
    agent.build = AsyncMock(return_value=booking_context)
    adapter = EscapiaContextAdapter(booking_context_agent=agent)

    inquiry = _make_inquiry(
        requested_check_in=None,
        requested_check_out=None,
        message_text="Can it fit 8 people?",
    )
    await adapter.load_context(
        inquiry=inquiry,
        payload=EscapiaContextPayload(),
        db_session=object(),
    )

    _, kwargs = agent.build.await_args
    assert kwargs["triggered_by"] == "group_size_keyword"


@pytest.mark.asyncio
async def test_load_context_propagates_agent_programmer_errors():
    agent = AsyncMock()
    agent.build = AsyncMock(side_effect=RuntimeError("agent exploded"))
    adapter = EscapiaContextAdapter(booking_context_agent=agent)

    with pytest.raises(RuntimeError, match="agent exploded"):
        await adapter.load_context(
            inquiry=_make_inquiry(),
            payload=EscapiaContextPayload(),
            db_session=object(),
        )


@pytest.mark.asyncio
async def test_load_context_preserves_existing_overlay_fields_when_enriching():
    booking_context = BookingContext(triggered_by="date_range_detected")
    agent = AsyncMock()
    agent.build = AsyncMock(return_value=booking_context)
    adapter = EscapiaContextAdapter(booking_context_agent=agent)

    envelope = await adapter.load_context(
        inquiry=_make_inquiry(),
        payload=EscapiaContextPayload(
            property_data={"wifi": "Network"},
            operator_policies={"pet_policy": "not_allowed"},
        ),
        db_session=object(),
    )

    assert envelope.overlay["property_facts"]["wifi"] == "Network"
    assert envelope.overlay["house_rules"]["pet_policy"] == "not_allowed"
    assert read_booking_context_overlay(envelope.overlay) == booking_context
