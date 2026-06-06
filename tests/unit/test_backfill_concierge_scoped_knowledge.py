from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from scripts.backfill_concierge_scoped_knowledge import (
    build_metadata,
    compute_question_key,
    decide_row,
)


def _legacy_row(**overrides):
    row = {
        "knowledge_id": uuid4(),
        "tenant_id": uuid4(),
        "property_external_id": "BH-101",
        "category": "General",
        "question": "How much is pool heating?",
        "answer": "$50/day",
        "confidence": 0.9,
        "source": "legacy_seed",
        "valid_from": None,
        "valid_until": None,
        "created_at": datetime(2026, 5, 1, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 5, 2, tzinfo=timezone.utc),
    }
    row.update(overrides)
    return row


def test_compute_question_key_matches_service_behavior():
    assert compute_question_key("What is the wifi password?") == "password wifi"
    assert compute_question_key("the and if") == "the and if"
    assert compute_question_key("Where do we park?") == compute_question_key("Where do we park?!")


def test_build_metadata_carries_legacy_fields():
    row = _legacy_row(valid_from=datetime(2026, 5, 1, tzinfo=timezone.utc))
    metadata = build_metadata(
        row=row,
        migration_run_id="run-1",
        migrated_at="2026-05-09T00:00:00+00:00",
    )
    assert metadata["legacy_id"] == str(row["knowledge_id"])
    assert metadata["legacy_category"] == "General"
    assert metadata["legacy_confidence"] == 0.9
    assert metadata["legacy_valid_from"] == "2026-05-01T00:00:00+00:00"
    assert metadata["migration_run_id"] == "run-1"


def test_decide_row_skips_null_tenant():
    decision = decide_row(
        row=_legacy_row(tenant_id=None),
        property_map={"BH-101": str(uuid4())},
        existing_legacy_ids=set(),
        migration_run_id="run-1",
        migrated_at="2026-05-09T00:00:00+00:00",
    )
    assert decision.action == "skip"
    assert decision.reason == "null_tenant"


def test_decide_row_skips_unresolvable_property():
    decision = decide_row(
        row=_legacy_row(property_external_id="UNKNOWN"),
        property_map={"BH-101": str(uuid4())},
        existing_legacy_ids=set(),
        migration_run_id="run-1",
        migrated_at="2026-05-09T00:00:00+00:00",
    )
    assert decision.action == "skip"
    assert decision.reason == "unresolvable_property"


def test_decide_row_skips_already_migrated():
    row = _legacy_row()
    decision = decide_row(
        row=row,
        property_map={"BH-101": str(uuid4())},
        existing_legacy_ids={str(row["knowledge_id"])},
        migration_run_id="run-1",
        migrated_at="2026-05-09T00:00:00+00:00",
    )
    assert decision.action == "skip"
    assert decision.reason == "already_migrated"


def test_decide_row_migrates_clear_match():
    target_id = str(uuid4())
    row = _legacy_row()
    decision = decide_row(
        row=row,
        property_map={"BH-101": target_id},
        existing_legacy_ids=set(),
        migration_run_id="run-1",
        migrated_at="2026-05-09T00:00:00+00:00",
    )
    assert decision.action == "migrate"
    assert decision.scope_target_id == target_id
    assert decision.topic_id is None
    assert decision.question_key == "heating much pool"


def test_decide_row_leaves_topic_null_for_all_legacy_rows():
    row = _legacy_row(question="Where is the air fryer located?")
    decision = decide_row(
        row=row,
        property_map={"BH-101": str(uuid4())},
        existing_legacy_ids=set(),
        migration_run_id="run-1",
        migrated_at="2026-05-09T00:00:00+00:00",
    )
    assert decision.action == "migrate"
    assert decision.topic_id is None
