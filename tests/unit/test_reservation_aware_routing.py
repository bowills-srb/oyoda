from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from app.services.integrations.reservation_aware_routing import (
    MatchedReservation,
    ReservationAwareRoutingService,
    clear_reservation_routing_caches,
    determine_lifecycle,
)


def _parsed(**overrides):
    base = SimpleNamespace(
        guest_email="guest@example.com",
        guest_name="Christina Moser",
        property_code="100SL2D",
        reservation_id="",
        requested_check_in=date.today() + timedelta(days=5),
        requested_check_out=date.today() + timedelta(days=12),
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


@pytest.fixture(autouse=True)
def _clear_caches():
    clear_reservation_routing_caches()
    yield
    clear_reservation_routing_caches()


@pytest.mark.asyncio
async def test_reservation_aware_routing_disabled_short_circuits(monkeypatch):
    service = ReservationAwareRoutingService(
        company_id=UUID("11111111-1111-1111-1111-111111111111"),
        db=None,
    )
    monkeypatch.setattr(service, "is_enabled", AsyncMock(return_value=False))
    local_lookup = AsyncMock()
    monkeypatch.setattr(service, "_find_in_pms_bookings", local_lookup)

    decision = await service.evaluate(_parsed())

    assert decision.routing_source == "pms_lookup_disabled"
    assert decision.matched_reservation is None
    local_lookup.assert_not_called()


@pytest.mark.asyncio
async def test_reservation_aware_routing_matches_local_email_and_caches(monkeypatch):
    service = ReservationAwareRoutingService(
        company_id=UUID("11111111-1111-1111-1111-111111111111"),
        db=None,
    )
    match = MatchedReservation(
        reservation_id="res-123",
        guest_name="Christina Moser",
        guest_email="guest@example.com",
        check_in=date.today() + timedelta(days=5),
        check_out=date.today() + timedelta(days=12),
        property_code="100SL2D",
        match_method="email",
    )
    monkeypatch.setattr(service, "is_enabled", AsyncMock(return_value=True))
    monkeypatch.setattr(
        "app.services.integrations.reservation_aware_routing.load_reservation_routing_window",
        AsyncMock(return_value=SimpleNamespace(past_days=14, future_days=30)),
    )
    local_lookup = AsyncMock(return_value=match)
    live_lookup = AsyncMock()
    monkeypatch.setattr(service, "_find_in_pms_bookings", local_lookup)
    monkeypatch.setattr(service, "_find_via_escapia_api", live_lookup)

    first = await service.evaluate(_parsed())
    second = await service.evaluate(_parsed())

    assert first.routing_source == "pms_reservation_matched"
    assert first.matched_reservation == match
    assert second.matched_reservation == match
    local_lookup.assert_awaited_once()
    live_lookup.assert_not_called()


@pytest.mark.asyncio
async def test_reservation_aware_routing_returns_no_match_when_enabled(monkeypatch):
    service = ReservationAwareRoutingService(
        company_id=UUID("11111111-1111-1111-1111-111111111111"),
        db=None,
    )
    monkeypatch.setattr(service, "is_enabled", AsyncMock(return_value=True))
    monkeypatch.setattr(
        "app.services.integrations.reservation_aware_routing.load_reservation_routing_window",
        AsyncMock(return_value=SimpleNamespace(past_days=14, future_days=30)),
    )
    monkeypatch.setattr(service, "_find_in_pms_bookings", AsyncMock(return_value=None))
    monkeypatch.setattr(service, "_find_via_escapia_api", AsyncMock(return_value=None))

    decision = await service.evaluate(_parsed())

    assert decision.routing_source == "no_match_pre_booking"
    assert decision.matched_reservation is None


def test_determine_lifecycle_resolves_relative_to_stay_window():
    today = date(2026, 5, 18)

    assert determine_lifecycle(
        check_in=date(2026, 5, 23),
        check_out=date(2026, 5, 30),
        today=today,
    ) == "pre_arrival"
    assert determine_lifecycle(
        check_in=date(2026, 5, 10),
        check_out=date(2026, 5, 20),
        today=today,
    ) == "in_stay"
    assert determine_lifecycle(
        check_in=date(2026, 5, 1),
        check_out=date(2026, 5, 5),
        today=today,
    ) == "post_stay"
