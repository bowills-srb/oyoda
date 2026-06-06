from app.services.integrations.review_feedback_signals import (
    extract_review_feedback_signals,
    summarize_feedback_signal_outcome,
)


def test_extract_review_feedback_signals_respects_property_truth():
    signals = extract_review_feedback_signals(
        (
            "Wish we would have had more time with the house guide - didn't realize there "
            "wasn't a pack n play provided until after check in. Wifi was iffy the whole trip. "
            "Some of the TVs didn't work at all."
        ),
        property_data={
            "wifi_available": True,
            "property_summary": "Family-friendly home with pack n play and streaming TVs.",
            "description": "Pack n play available on request. Smart TV in living room.",
        },
    )

    by_theme = {item["theme"]: item for item in signals}
    assert by_theme["pack_n_play"]["validation_status"] == "possible_listing_mismatch"
    assert by_theme["pack_n_play"]["kb_gap_candidate"] is True
    assert by_theme["wifi_reliability"]["validation_status"] == "observed_issue"
    assert by_theme["tv_functionality"]["validation_status"] == "observed_issue"
    assert by_theme["house_guide_discoverability"]["validation_status"] == "needs_operator_review"


def test_extract_review_feedback_signals_does_not_infer_gap_without_listing_support():
    signals = extract_review_feedback_signals(
        "The only minor disappointment we had was the lack of toilet paper and trash bags, and we wished there was a pack n play.",
        property_data={
            "wifi_available": False,
            "property_summary": "Beach cottage near pool and boardwalk.",
            "description": "Charming family retreat with bright interiors.",
        },
    )

    by_theme = {item["theme"]: item for item in signals}
    assert by_theme["pack_n_play"]["validation_status"] == "expectation_only"
    assert by_theme["pack_n_play"]["kb_gap_candidate"] is False
    assert by_theme["starter_supplies"]["validation_status"] == "observed_issue"

    summary = summarize_feedback_signal_outcome(signals)
    assert summary["count"] == len(signals)
    assert summary["kb_gap_candidates"] == 0


def test_extract_review_feedback_signals_handles_beach_towel_expectation():
    signals = extract_review_feedback_signals(
        (
            "The one thing I would recommend for future guests is to have designated beach towels available. "
            "We did not realize the rental did not come with beach towels."
        ),
        property_data={
            "property_summary": "Walkable condo near the beach with beach gear closet and towel package included.",
            "description": "Beach towels and chairs are included for guest use.",
        },
    )

    by_theme = {item["theme"]: item for item in signals}
    assert by_theme["beach_towels"]["family"] == "amenity_expectation"
    assert by_theme["beach_towels"]["validation_status"] == "possible_listing_mismatch"
    assert by_theme["beach_towels"]["kb_gap_candidate"] is True


def test_extract_review_feedback_signals_handles_cold_storage_appliance_issue():
    signals = extract_review_feedback_signals(
        (
            "We had a little snafu with the freezer not working, but we appreciated how quickly "
            "someone came out to look at it."
        ),
        property_data={
            "property_summary": "Large family home with full kitchen and ice maker.",
            "description": "Spacious kitchen with refrigerator, freezer, and plenty of prep space.",
        },
    )

    by_theme = {item["theme"]: item for item in signals}
    assert by_theme["cold_storage_appliance"]["family"] == "device_issue"
    assert by_theme["cold_storage_appliance"]["validation_status"] == "observed_issue"
    assert by_theme["cold_storage_appliance"]["kb_gap_candidate"] is False
