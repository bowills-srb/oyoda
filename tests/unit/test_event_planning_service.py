from datetime import date

from app.services.concierge.event_planning_service import (
    _build_guest_summary,
    _event_priority,
    _generate_trip_notes,
    is_event_planning_question,
)


def test_is_event_planning_question_detects_trip_planning_language():
    assert is_event_planning_question("What is happening during our stay in six weeks?")
    assert is_event_planning_question("Should we book restaurants because of any festivals?")
    assert not is_event_planning_question("What is the wifi password?")


def test_generate_trip_notes_flags_high_demand_and_family_relevance():
    events = [
        {
            "title": "Songwriters Festival",
            "demand_impact_score": 0.82,
            "booking_urgency_score": 0.71,
            "ticket_url": "https://tickets.example.com",
            "category": "festival",
            "tags": ["music"],
        },
        {
            "title": "Seaside Family Movie Night",
            "demand_impact_score": 0.25,
            "booking_urgency_score": 0.10,
            "ticket_url": None,
            "category": "family",
            "tags": ["family"],
        },
    ]

    notes = _generate_trip_notes(events, has_children=True)

    assert any("parking" in note.lower() for note in notes)
    assert any("booking ahead" in note.lower() for note in notes)
    assert any("family-friendly" in note.lower() for note in notes)


def test_build_guest_summary_mentions_demand_pressure_for_major_events():
    events = [
        {
            "title": "Wine Festival",
            "event_class": "demand_driver",
            "start_date": date(2026, 5, 1),
            "end_date": date(2026, 5, 3),
        },
        {
            "title": "Live Music on the Green",
            "event_class": "operational",
            "start_date": date(2026, 5, 2),
            "end_date": date(2026, 5, 2),
        },
    ]

    summary = _build_guest_summary(events, date(2026, 5, 1), date(2026, 5, 4))

    assert "Wine Festival" in summary
    assert "traffic" in summary.lower()


def test_event_priority_prefers_higher_signal_event():
    arrival_date = date(2026, 5, 1)
    major = {
        "title": "Sandestin Wine Festival",
        "start_date": date(2026, 5, 2),
        "demand_impact_score": 0.80,
        "guest_relevance_score": 0.78,
        "booking_urgency_score": 0.74,
        "event_confidence_score": 0.86,
    }
    minor = {
        "title": "Weekly Singer at the Bar",
        "start_date": date(2026, 5, 2),
        "demand_impact_score": 0.20,
        "guest_relevance_score": 0.42,
        "booking_urgency_score": 0.10,
        "event_confidence_score": 0.55,
    }

    assert _event_priority(major, arrival_date) > _event_priority(minor, arrival_date)
