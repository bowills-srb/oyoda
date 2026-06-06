"""
eval_comparator.py — Pure comparison logic for brain eval.

Session 10 (Phase 2) — see docs/PHASE_2_SEAM_MAP.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.services.orchestration.messaging_brain_contracts import (
    MessageClassification,
)


@dataclass(frozen=True)
class EvalCase:
    """A single eval case — input message + expected classification fields."""

    case_id: str
    case_key: str
    message_text: str
    market_tag: str
    source: str

    expected_intent_topic: str
    expected_secondary_topics: List[str] = field(default_factory=list)
    expected_sub_intents: List[str] = field(default_factory=list)
    expected_constraint_keys: List[str] = field(default_factory=list)
    expected_review: bool = False
    expected_urgency: Optional[str] = None
    notes: str = ""


@dataclass(frozen=True)
class ComparisonResult:
    """Result of comparing an actual classification to an expected case."""

    passed: bool
    failures: List[str] = field(default_factory=list)
    urgency_note: Optional[str] = None


def compare_classification(
    actual: MessageClassification,
    expected: EvalCase,
    *,
    classifier_source: str,
) -> ComparisonResult:
    """Compare an actual classification against an expected eval case."""
    failures: List[str] = []

    if actual.intent_topic != expected.expected_intent_topic:
        failures.append(
            f"intent_topic_mismatch: expected={expected.expected_intent_topic!r}, "
            f"got={actual.intent_topic!r}"
        )

    if actual.requires_human_review != expected.expected_review:
        failures.append(
            f"review_mismatch: expected={expected.expected_review}, "
            f"got={actual.requires_human_review}"
        )

    missing_secondary = [
        t for t in expected.expected_secondary_topics if t not in actual.secondary_topics
    ]
    if missing_secondary:
        failures.append(f"secondary_topics_missing: {missing_secondary}")

    if classifier_source == "llm":
        missing_sub = [
            s for s in expected.expected_sub_intents if s not in actual.sub_intents
        ]
        if missing_sub:
            failures.append(f"sub_intents_missing: {missing_sub}")

        for key_path in expected.expected_constraint_keys:
            if not _has_non_empty_value(actual.extracted_constraints, key_path):
                failures.append(f"constraint_missing: {key_path}")

    urgency_note: Optional[str] = None
    if expected.expected_urgency:
        actual_urgency_str = (
            actual.urgency.value if hasattr(actual.urgency, "value") else str(actual.urgency)
        )
        if actual_urgency_str != expected.expected_urgency:
            urgency_note = (
                f"urgency_soft_mismatch: expected={expected.expected_urgency!r}, "
                f"got={actual_urgency_str!r}"
            )

    return ComparisonResult(
        passed=len(failures) == 0,
        failures=failures,
        urgency_note=urgency_note,
    )


def _has_non_empty_value(obj: Dict[str, Any], key_path: str) -> bool:
    """Return True iff the given dotted key path resolves to a non-empty value."""
    if not isinstance(obj, dict):
        return False

    parts = key_path.split(".")
    current: Any = obj
    for part in parts:
        if not isinstance(current, dict):
            return False
        if part not in current:
            return False
        current = current[part]

    if current is None:
        return False
    if isinstance(current, (str, list, dict)) and len(current) == 0:
        return False
    return True
