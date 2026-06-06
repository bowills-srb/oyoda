from __future__ import annotations

from datetime import date, datetime, timezone

from app.services.concierge.post_booking_routing import (
    infer_session_dates,
    is_non_pre_booking_intent,
)


def test_non_pre_booking_intent_detection_matches_closed_set():
    assert is_non_pre_booking_intent("general") is False
    assert is_non_pre_booking_intent("general_inquiry") is False
    assert is_non_pre_booking_intent("review_response") is True
    assert is_non_pre_booking_intent("availability") is False


def test_infer_session_dates_prefers_requested_dates():
    check_in, check_out = infer_session_dates(
        requested_check_in=date(2026, 7, 1),
        requested_check_out=date(2026, 7, 5),
        received_at=datetime(2026, 5, 17, tzinfo=timezone.utc),
    )
    assert check_in == date(2026, 7, 1)
    assert check_out == date(2026, 7, 5)


def test_infer_session_dates_falls_back_to_received_at_date():
    check_in, check_out = infer_session_dates(
        requested_check_in=None,
        requested_check_out=None,
        received_at=datetime(2026, 5, 17, 15, 0, tzinfo=timezone.utc),
    )
    assert check_in == date(2026, 5, 17)
    assert check_out == date(2026, 5, 17)
