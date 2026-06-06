from __future__ import annotations

from app.services.operator.stay_event_service import StayEventService


def test_summarize_event_rows_tracks_turnover_and_documentation_markers():
    service = StayEventService()

    summary = service.summarize_event_rows(
        [
            {
                "event_type": "property_ready",
                "event_domain": "turnover",
                "occurred_at": "2026-04-22T16:00:00+00:00",
                "created_at": "2026-04-22T16:00:00+00:00",
            },
            {
                "event_type": "documentation_completed",
                "event_domain": "walkthrough",
                "occurred_at": "2026-04-22T15:30:00+00:00",
                "created_at": "2026-04-22T15:30:00+00:00",
            },
            {
                "event_type": "housekeeping_arrived",
                "event_domain": "turnover",
                "occurred_at": "2026-04-22T14:00:00+00:00",
                "created_at": "2026-04-22T14:00:00+00:00",
            },
        ]
    )

    assert summary["count"] == 3
    assert summary["counts_by_domain"]["turnover"] == 2
    assert summary["property_ready_at"] == "2026-04-22T16:00:00+00:00"
    assert summary["documentation_completed_at"] == "2026-04-22T15:30:00+00:00"
    assert summary["housekeeping_arrived_at"] == "2026-04-22T14:00:00+00:00"
