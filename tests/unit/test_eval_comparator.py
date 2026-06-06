"""
test_eval_comparator.py — Unit tests for eval_comparator.
"""

from __future__ import annotations

import pytest

from app.services.messaging_brain.eval.eval_comparator import (
    ComparisonResult,
    EvalCase,
    _has_non_empty_value,
    compare_classification,
)
from app.services.orchestration.messaging_brain_contracts import (
    IntentType,
    MessageClassification,
    Urgency,
)


def _classification(
    *,
    intent_topic: str = "booking_inquiry",
    secondary_topics=None,
    sub_intents=None,
    extracted_constraints=None,
    requires_human_review: bool = False,
    urgency: Urgency = Urgency.MEDIUM,
) -> MessageClassification:
    return MessageClassification(
        intent_type=IntentType.QUESTION,
        intent_topic=intent_topic,
        secondary_topics=secondary_topics or [],
        sub_intents=sub_intents or [],
        extracted_constraints=extracted_constraints or {},
        confidence=0.85,
        urgency=urgency,
        requires_human_review=requires_human_review,
        reason="test",
    )


def _case(
    *,
    expected_intent_topic: str = "booking_inquiry",
    expected_secondary_topics=None,
    expected_sub_intents=None,
    expected_constraint_keys=None,
    expected_review: bool = False,
    expected_urgency=None,
) -> EvalCase:
    return EvalCase(
        case_id="case-uuid",
        case_key="test_case",
        message_text="test message",
        market_tag="coastal_30a",
        source="curated_seed",
        expected_intent_topic=expected_intent_topic,
        expected_secondary_topics=expected_secondary_topics or [],
        expected_sub_intents=expected_sub_intents or [],
        expected_constraint_keys=expected_constraint_keys or [],
        expected_review=expected_review,
        expected_urgency=expected_urgency,
    )


def test_matching_topic_passes():
    result = compare_classification(
        _classification(intent_topic="booking_inquiry"),
        _case(expected_intent_topic="booking_inquiry"),
        classifier_source="llm",
    )
    assert result.passed
    assert result.failures == []


def test_mismatched_topic_fails():
    result = compare_classification(
        _classification(intent_topic="general"),
        _case(expected_intent_topic="booking_inquiry"),
        classifier_source="llm",
    )
    assert not result.passed
    assert any("intent_topic_mismatch" in f for f in result.failures)


def test_review_match_passes():
    result = compare_classification(
        _classification(requires_human_review=True),
        _case(expected_review=True),
        classifier_source="llm",
    )
    assert result.passed


def test_review_mismatch_fails():
    result = compare_classification(
        _classification(requires_human_review=True),
        _case(expected_review=False),
        classifier_source="llm",
    )
    assert not result.passed
    assert any("review_mismatch" in f for f in result.failures)


def test_secondary_topics_exact_match_passes():
    result = compare_classification(
        _classification(secondary_topics=["complaint"]),
        _case(expected_secondary_topics=["complaint"]),
        classifier_source="llm",
    )
    assert result.passed


def test_secondary_topics_extras_in_actual_pass():
    result = compare_classification(
        _classification(secondary_topics=["complaint", "maintenance"]),
        _case(expected_secondary_topics=["complaint"]),
        classifier_source="llm",
    )
    assert result.passed


def test_secondary_topics_missing_expected_fails():
    result = compare_classification(
        _classification(secondary_topics=["maintenance"]),
        _case(expected_secondary_topics=["complaint"]),
        classifier_source="llm",
    )
    assert not result.passed
    assert any("secondary_topics_missing" in f for f in result.failures)


def test_secondary_topics_checked_for_keyword_classifier_too():
    result = compare_classification(
        _classification(secondary_topics=[]),
        _case(expected_secondary_topics=["complaint"]),
        classifier_source="keyword",
    )
    assert not result.passed
    assert any("secondary_topics_missing" in f for f in result.failures)


def test_sub_intents_subset_match_passes_for_llm():
    result = compare_classification(
        _classification(sub_intents=["pricing", "availability"]),
        _case(expected_sub_intents=["pricing"]),
        classifier_source="llm",
    )
    assert result.passed


def test_sub_intents_missing_fails_for_llm():
    result = compare_classification(
        _classification(sub_intents=[]),
        _case(expected_sub_intents=["pricing"]),
        classifier_source="llm",
    )
    assert not result.passed
    assert any("sub_intents_missing" in f for f in result.failures)


def test_sub_intents_skipped_for_keyword_classifier():
    result = compare_classification(
        _classification(sub_intents=[]),
        _case(expected_sub_intents=["pricing", "availability"]),
        classifier_source="keyword",
    )
    assert result.passed


def test_constraint_present_passes_for_llm():
    result = compare_classification(
        _classification(extracted_constraints={"dates": {"check_in": "2026-05-29"}}),
        _case(expected_constraint_keys=["dates.check_in"]),
        classifier_source="llm",
    )
    assert result.passed


def test_constraint_missing_fails_for_llm():
    result = compare_classification(
        _classification(extracted_constraints={}),
        _case(expected_constraint_keys=["dates.check_in"]),
        classifier_source="llm",
    )
    assert not result.passed
    assert any("constraint_missing: dates.check_in" in f for f in result.failures)


def test_constraint_empty_value_fails():
    result = compare_classification(
        _classification(extracted_constraints={"dates": {"check_in": ""}}),
        _case(expected_constraint_keys=["dates.check_in"]),
        classifier_source="llm",
    )
    assert not result.passed
    assert any("constraint_missing" in f for f in result.failures)


def test_constraints_skipped_for_keyword_classifier():
    result = compare_classification(
        _classification(extracted_constraints={}),
        _case(expected_constraint_keys=["dates.check_in"]),
        classifier_source="keyword",
    )
    assert result.passed


def test_constraint_value_not_compared():
    result = compare_classification(
        _classification(
            extracted_constraints={"dates": {"check_in": "May 29 (approximate)"}}
        ),
        _case(expected_constraint_keys=["dates.check_in"]),
        classifier_source="llm",
    )
    assert result.passed


def test_urgency_match_no_note():
    result = compare_classification(
        _classification(urgency=Urgency.HIGH),
        _case(expected_urgency="high"),
        classifier_source="llm",
    )
    assert result.passed
    assert result.urgency_note is None


def test_urgency_mismatch_does_not_fail_case():
    result = compare_classification(
        _classification(urgency=Urgency.LOW),
        _case(expected_urgency="emergency"),
        classifier_source="llm",
    )
    assert result.passed
    assert result.urgency_note is not None
    assert "urgency_soft_mismatch" in result.urgency_note


def test_urgency_unset_in_expected_does_not_check():
    result = compare_classification(
        _classification(urgency=Urgency.LOW),
        _case(expected_urgency=None),
        classifier_source="llm",
    )
    assert result.passed
    assert result.urgency_note is None


def test_multiple_failures_all_reported():
    result = compare_classification(
        _classification(
            intent_topic="general",
            secondary_topics=[],
            sub_intents=[],
            requires_human_review=False,
            extracted_constraints={},
        ),
        _case(
            expected_intent_topic="booking_inquiry",
            expected_secondary_topics=["complaint"],
            expected_sub_intents=["pricing"],
            expected_constraint_keys=["dates.check_in"],
            expected_review=True,
        ),
        classifier_source="llm",
    )
    assert not result.passed
    failure_text = " ".join(result.failures)
    assert "intent_topic_mismatch" in failure_text
    assert "review_mismatch" in failure_text
    assert "secondary_topics_missing" in failure_text
    assert "sub_intents_missing" in failure_text
    assert "constraint_missing" in failure_text


def test_has_non_empty_value_simple_present():
    assert _has_non_empty_value({"a": "x"}, "a")


def test_has_non_empty_value_simple_missing():
    assert not _has_non_empty_value({"a": "x"}, "b")


def test_has_non_empty_value_nested_present():
    assert _has_non_empty_value({"a": {"b": "x"}}, "a.b")


def test_has_non_empty_value_nested_missing_inner():
    assert not _has_non_empty_value({"a": {"b": "x"}}, "a.c")


def test_has_non_empty_value_nested_missing_outer():
    assert not _has_non_empty_value({"a": {"b": "x"}}, "z.b")


def test_has_non_empty_value_empty_string():
    assert not _has_non_empty_value({"a": ""}, "a")


def test_has_non_empty_value_empty_list():
    assert not _has_non_empty_value({"a": []}, "a")


def test_has_non_empty_value_empty_dict():
    assert not _has_non_empty_value({"a": {}}, "a")


def test_has_non_empty_value_none():
    assert not _has_non_empty_value({"a": None}, "a")


def test_has_non_empty_value_zero_is_present():
    assert _has_non_empty_value({"a": 0}, "a")


def test_has_non_empty_value_false_is_present():
    assert _has_non_empty_value({"a": False}, "a")


def test_has_non_empty_value_traverses_through_non_dict():
    assert not _has_non_empty_value({"a": "not_a_dict"}, "a.b")


def test_has_non_empty_value_root_not_dict():
    assert not _has_non_empty_value("not a dict", "a")


def test_comparison_result_is_frozen():
    result = ComparisonResult(passed=True, failures=[], urgency_note=None)
    with pytest.raises(Exception):
        result.passed = False  # type: ignore[misc]
