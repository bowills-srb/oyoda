from __future__ import annotations

from datetime import date

from app.services.operator.stay_pms_feed_service import StayPmsFeedService


def test_normalize_pms_event_maps_checkout_and_turnover_into_stay_events():
    service = StayPmsFeedService()

    checked_out = service.normalize_pms_event("guesty", "checked_out", note="Guest departed")
    turnover_done = service.normalize_pms_event("hostaway", "turnover_completed", payload={"vendor": "Housekeeping"})

    assert checked_out["event_type"] == "guest_checked_out"
    assert checked_out["source"] == "pms:guesty"
    assert checked_out["payload"]["provider_event_type"] == "checked_out"
    assert turnover_done["event_type"] == "housekeeping_completed"
    assert turnover_done["payload"]["provider"] == "hostaway"


def test_load_feed_derives_arrival_and_turnover_schedule():
    service = StayPmsFeedService()
    booking = {
        "pms_provider": "guesty",
        "reservation_id": "res-1",
        "listing_external_id": "listing-1",
        "listing_name": "Lanier",
        "booking_channel": "direct",
        "status": "confirmed",
        "guest_count": 6,
        "booked_at": None,
        "check_in": date(2026, 4, 25),
        "check_out": date(2026, 4, 29),
    }

    derived = service._derived_events(booking, booking["check_in"], booking["check_out"], date(2026, 4, 29))

    assert derived[0]["event_type"] == "scheduled_arrival"
    assert derived[1]["event_type"] == "scheduled_checkout"
    assert derived[2]["event_type"] == "turnover_window_open"
    assert derived[2]["status"] == "ready"
