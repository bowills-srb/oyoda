from app.services.operator.autonomy_score_service import (
    _compute_portfolio_score_from_inputs,
    _property_snapshot_from_inputs,
    _rollup_property_inquiry_score,
)


def test_well_documented_large_profile_scores_high() -> None:
    scores = _compute_portfolio_score_from_inputs(
        property_count=50,
        kb_entries=2000,
        distinct_gaps=30,
        escalation_open=0,
        escalation_resolved=0,
        recent_session_count=250,
    )

    assert 0.7 <= scores["portfolio"] <= 0.85
    assert scores["escalation"] > 0.8
    assert scores["readiness"] > 0.75


def test_sparse_small_profile_scores_low() -> None:
    scores = _compute_portfolio_score_from_inputs(
        property_count=5,
        kb_entries=20,
        distinct_gaps=30,
        escalation_open=5,
        escalation_resolved=0,
        recent_session_count=25,
    )

    assert 0.2 <= scores["portfolio"] <= 0.35
    assert scores["readiness"] < 0.5
    assert scores["escalation"] == 0.0


def test_new_low_signal_profile_stays_neutralish() -> None:
    scores = _compute_portfolio_score_from_inputs(
        property_count=3,
        kb_entries=5,
        distinct_gaps=0,
        escalation_open=0,
        escalation_resolved=0,
        recent_session_count=0,
    )

    assert 0.3 <= scores["portfolio"] <= 0.45
    assert scores["escalation"] == 0.5


def test_mid_profile_scores_in_the_middle() -> None:
    scores = _compute_portfolio_score_from_inputs(
        property_count=20,
        kb_entries=300,
        distinct_gaps=60,
        escalation_open=4,
        escalation_resolved=6,
        recent_session_count=80,
    )

    assert 0.45 <= scores["portfolio"] <= 0.65
    assert 0.4 <= scores["escalation"] <= 0.7


def test_more_gaps_lower_the_score() -> None:
    low_gap = _compute_portfolio_score_from_inputs(
        property_count=20,
        kb_entries=300,
        distinct_gaps=10,
        escalation_open=1,
        escalation_resolved=4,
        recent_session_count=80,
    )
    high_gap = _compute_portfolio_score_from_inputs(
        property_count=20,
        kb_entries=300,
        distinct_gaps=60,
        escalation_open=1,
        escalation_resolved=4,
        recent_session_count=80,
    )

    assert high_gap["readiness"] < low_gap["readiness"]
    assert high_gap["portfolio"] < low_gap["portfolio"]


def test_zero_escalations_with_traffic_scores_higher_than_no_signal() -> None:
    pristine = _compute_portfolio_score_from_inputs(
        property_count=10,
        kb_entries=100,
        distinct_gaps=5,
        escalation_open=0,
        escalation_resolved=0,
        recent_session_count=50,
    )
    no_signal = _compute_portfolio_score_from_inputs(
        property_count=10,
        kb_entries=100,
        distinct_gaps=5,
        escalation_open=0,
        escalation_resolved=0,
        recent_session_count=0,
    )

    assert pristine["escalation"] > no_signal["escalation"]
    assert pristine["portfolio"] > no_signal["portfolio"]


def test_per_property_high_signal_profile_scores_high() -> None:
    snapshot = _property_snapshot_from_inputs(
        property_id="prop-1",
        property_code="111VW",
        traffic_count=18,
        kb_entries=12,
        distinct_gaps=0,
        shared_escalation_open=0,
        shared_escalation_resolved=0,
        shared_recent_session_count=50,
    )

    assert snapshot["signal_status"] == "computed"
    assert 0.8 <= snapshot["domain_bands"]["inquiry"]["score"] <= 1.0
    assert snapshot["domain_bands"]["inquiry"]["band"] == "Autonomous"


def test_per_property_sparse_profile_scores_lower() -> None:
    snapshot = _property_snapshot_from_inputs(
        property_id="prop-2",
        property_code="222AB",
        traffic_count=12,
        kb_entries=2,
        distinct_gaps=8,
        shared_escalation_open=3,
        shared_escalation_resolved=1,
        shared_recent_session_count=50,
    )

    assert snapshot["signal_status"] == "computed"
    assert snapshot["domain_bands"]["inquiry"]["score"] < 0.45
    assert snapshot["domain_bands"]["inquiry"]["band"] == "Emerging"


def test_per_property_no_traffic_stays_insufficient_signal() -> None:
    snapshot = _property_snapshot_from_inputs(
        property_id="prop-3",
        property_code="333CD",
        traffic_count=0,
        kb_entries=15,
        distinct_gaps=0,
        shared_escalation_open=0,
        shared_escalation_resolved=0,
        shared_recent_session_count=50,
    )

    assert snapshot["signal_status"] == "insufficient_signal"
    assert snapshot["domain_bands"]["inquiry"]["score"] is None
    assert snapshot["domain_bands"]["inquiry"]["band"] == "Insufficient Signal"


def test_per_property_rollup_excludes_insufficient_signal_rows() -> None:
    high_signal = _property_snapshot_from_inputs(
        property_id="prop-1",
        property_code="111VW",
        traffic_count=20,
        kb_entries=12,
        distinct_gaps=0,
        shared_escalation_open=0,
        shared_escalation_resolved=0,
        shared_recent_session_count=50,
    )
    low_signal = _property_snapshot_from_inputs(
        property_id="prop-2",
        property_code="222AB",
        traffic_count=14,
        kb_entries=3,
        distinct_gaps=6,
        shared_escalation_open=2,
        shared_escalation_resolved=1,
        shared_recent_session_count=50,
    )
    no_signal = _property_snapshot_from_inputs(
        property_id="prop-3",
        property_code="333CD",
        traffic_count=0,
        kb_entries=20,
        distinct_gaps=0,
        shared_escalation_open=0,
        shared_escalation_resolved=0,
        shared_recent_session_count=50,
    )

    rollup = _rollup_property_inquiry_score([high_signal, low_signal, no_signal])

    expected = round(
        (
            high_signal["domain_bands"]["inquiry"]["score"]
            + low_signal["domain_bands"]["inquiry"]["score"]
        ) / 2,
        4,
    )
    assert rollup["inquiry_score"] == expected
    assert rollup["included_properties"] == 2
    assert rollup["excluded_properties"] == 1
