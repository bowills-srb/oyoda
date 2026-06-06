"""
test_eval_case_store.py — Unit tests for eval_case_store.
"""

from __future__ import annotations

import uuid

import pytest

from app.services.messaging_brain.eval.eval_case_store import (
    ensure_eval_tables,
    fail_run,
    finish_run,
    get_case_by_key,
    get_run_case_details,
    get_run_summary,
    list_active_cases,
    record_run_case,
    start_run,
    upsert_case,
)


@pytest.mark.asyncio
async def test_ensure_eval_tables_is_idempotent(stub_db):
    await ensure_eval_tables(stub_db)
    await ensure_eval_tables(stub_db)


@pytest.mark.asyncio
async def test_upsert_case_inserts_new(stub_db):
    case_id = await upsert_case(
        stub_db,
        case_key="test_case_1",
        message_text="Hello world",
        market_tag="coastal_30a",
        source="curated_seed",
        expected_intent_topic="booking_inquiry",
        expected_review=False,
    )
    assert case_id
    cases = await list_active_cases(stub_db)
    assert len(cases) == 1
    assert cases[0].case_key == "test_case_1"
    assert cases[0].message_text == "Hello world"


@pytest.mark.asyncio
async def test_upsert_case_updates_existing_keeps_id(stub_db):
    id1 = await upsert_case(
        stub_db,
        case_key="test_case_dup",
        message_text="v1",
        market_tag="coastal_30a",
        source="curated_seed",
        expected_intent_topic="general",
        expected_review=False,
    )
    id2 = await upsert_case(
        stub_db,
        case_key="test_case_dup",
        message_text="v2",
        market_tag="coastal_30a",
        source="curated_seed",
        expected_intent_topic="general",
        expected_review=True,
    )
    assert id1 == id2
    cases = await list_active_cases(stub_db)
    assert len(cases) == 1
    assert cases[0].message_text == "v2"
    assert cases[0].expected_review is True


@pytest.mark.asyncio
async def test_upsert_case_with_full_arrays(stub_db):
    await upsert_case(
        stub_db,
        case_key="test_case_arrays",
        message_text="msg",
        market_tag="coastal_30a",
        source="curated_seed",
        expected_intent_topic="booking_inquiry",
        expected_secondary_topics=["complaint"],
        expected_sub_intents=["pricing", "availability"],
        expected_constraint_keys=["dates.check_in", "budget.amount"],
        expected_review=False,
        expected_urgency="medium",
        notes="test notes",
    )
    cases = await list_active_cases(stub_db)
    case = cases[0]
    assert case.expected_secondary_topics == ["complaint"]
    assert case.expected_sub_intents == ["pricing", "availability"]
    assert case.expected_constraint_keys == ["dates.check_in", "budget.amount"]
    assert case.expected_urgency == "medium"
    assert case.notes == "test notes"


@pytest.mark.asyncio
async def test_list_active_cases_returns_all_active(stub_db):
    for i in range(3):
        await upsert_case(
            stub_db,
            case_key=f"case_{i}",
            message_text=f"msg {i}",
            market_tag="coastal_30a" if i < 2 else "breckenridge_ski",
            source="curated_seed",
            expected_intent_topic="booking_inquiry",
            expected_review=False,
        )
    cases = await list_active_cases(stub_db)
    assert len(cases) == 3


@pytest.mark.asyncio
async def test_list_active_cases_market_filter(stub_db):
    await upsert_case(
        stub_db,
        case_key="coastal_a",
        message_text="m",
        market_tag="coastal_30a",
        source="curated_seed",
        expected_intent_topic="booking_inquiry",
        expected_review=False,
    )
    await upsert_case(
        stub_db,
        case_key="ski_a",
        message_text="m",
        market_tag="breckenridge_ski",
        source="curated_seed",
        expected_intent_topic="booking_inquiry",
        expected_review=False,
    )
    cases = await list_active_cases(stub_db, market_tag="coastal_30a")
    assert len(cases) == 1
    assert cases[0].case_key == "coastal_a"


@pytest.mark.asyncio
async def test_list_active_cases_case_keys_filter(stub_db):
    for key in ["a", "b", "c"]:
        await upsert_case(
            stub_db,
            case_key=key,
            message_text="m",
            market_tag="coastal_30a",
            source="curated_seed",
            expected_intent_topic="booking_inquiry",
            expected_review=False,
        )
    cases = await list_active_cases(stub_db, case_keys=["a", "c"])
    assert {c.case_key for c in cases} == {"a", "c"}


@pytest.mark.asyncio
async def test_get_case_by_key_returns_match(stub_db):
    await upsert_case(
        stub_db,
        case_key="lookup_me",
        message_text="m",
        market_tag="coastal_30a",
        source="curated_seed",
        expected_intent_topic="general",
        expected_review=False,
    )
    case = await get_case_by_key(stub_db, "lookup_me")
    assert case is not None
    assert case.case_key == "lookup_me"


@pytest.mark.asyncio
async def test_get_case_by_key_returns_none_for_missing(stub_db):
    case = await get_case_by_key(stub_db, "nonexistent")
    assert case is None


@pytest.mark.asyncio
async def test_start_run_returns_run_id(stub_db):
    run_id = await start_run(
        stub_db,
        invocation_id=str(uuid.uuid4()),
        classifier_source="llm",
    )
    assert run_id


@pytest.mark.asyncio
async def test_start_run_initial_status_is_in_progress(stub_db):
    run_id = await start_run(
        stub_db,
        invocation_id=str(uuid.uuid4()),
        classifier_source="llm",
    )
    summary = await get_run_summary(stub_db, run_id)
    assert summary is not None
    assert summary.status == "in_progress"
    assert summary.run_completed_at is None


@pytest.mark.asyncio
async def test_start_then_finish_run_persists_aggregates(stub_db):
    run_id = await start_run(
        stub_db,
        invocation_id=str(uuid.uuid4()),
        classifier_source="llm",
    )
    await finish_run(
        stub_db,
        run_id,
        cases_evaluated=10,
        cases_passed=8,
        cases_failed=2,
        accuracy_overall=0.8,
        accuracy_by_market={"coastal_30a": 0.9, "breckenridge_ski": 0.5},
    )
    summary = await get_run_summary(stub_db, run_id)
    assert summary is not None
    assert summary.status == "completed"
    assert summary.cases_evaluated == 10
    assert summary.cases_passed == 8
    assert summary.accuracy_overall == 0.8
    assert summary.accuracy_by_market == {
        "coastal_30a": 0.9,
        "breckenridge_ski": 0.5,
    }
    assert summary.run_completed_at is not None


@pytest.mark.asyncio
async def test_fail_run_sets_failed_status(stub_db):
    run_id = await start_run(
        stub_db,
        invocation_id=str(uuid.uuid4()),
        classifier_source="llm",
    )
    await fail_run(stub_db, run_id, error_note="ProviderTimeout: anthropic")
    summary = await get_run_summary(stub_db, run_id)
    assert summary is not None
    assert summary.status == "failed"
    assert summary.run_completed_at is not None
    assert summary.cases_evaluated == 0
    assert summary.accuracy_overall is None


@pytest.mark.asyncio
async def test_fail_run_without_error_note(stub_db):
    run_id = await start_run(
        stub_db,
        invocation_id=str(uuid.uuid4()),
        classifier_source="llm",
    )
    await fail_run(stub_db, run_id)
    summary = await get_run_summary(stub_db, run_id)
    assert summary is not None
    assert summary.status == "failed"


@pytest.mark.asyncio
async def test_record_run_case_persists_per_case(stub_db):
    case_id = await upsert_case(
        stub_db,
        case_key="rc_test",
        message_text="m",
        market_tag="coastal_30a",
        source="curated_seed",
        expected_intent_topic="booking_inquiry",
        expected_review=False,
    )
    run_id = await start_run(
        stub_db,
        invocation_id=str(uuid.uuid4()),
        classifier_source="llm",
    )
    await record_run_case(
        stub_db,
        run_id=run_id,
        case_id=case_id,
        passed=True,
        failure_reasons=[],
        urgency_note=None,
        actual_intent_topic="booking_inquiry",
        actual_secondary_topics=[],
        actual_sub_intents=["pricing"],
        actual_review=False,
        actual_urgency="medium",
        latency_ms=420,
        classifier_provider="anthropic",
    )
    details = await get_run_case_details(stub_db, run_id)
    assert len(details) == 1
    assert details[0].case_key == "rc_test"
    assert details[0].passed is True


@pytest.mark.asyncio
async def test_record_run_case_failures_and_urgency_note(stub_db):
    case_id = await upsert_case(
        stub_db,
        case_key="rc_fail",
        message_text="m",
        market_tag="coastal_30a",
        source="curated_seed",
        expected_intent_topic="booking_inquiry",
        expected_review=False,
    )
    run_id = await start_run(
        stub_db,
        invocation_id=str(uuid.uuid4()),
        classifier_source="llm",
    )
    await record_run_case(
        stub_db,
        run_id=run_id,
        case_id=case_id,
        passed=False,
        failure_reasons=["intent_topic_mismatch: ...", "sub_intents_missing: [...]"],
        urgency_note="urgency_soft_mismatch: expected='emergency', got='medium'",
        actual_intent_topic="general",
        actual_secondary_topics=[],
        actual_sub_intents=[],
        actual_review=False,
        actual_urgency="medium",
    )
    details = await get_run_case_details(stub_db, run_id)
    assert len(details) == 1
    assert details[0].passed is False
    assert len(details[0].failure_reasons) == 2
    assert details[0].urgency_note is not None


@pytest.mark.asyncio
async def test_get_run_summary_for_missing_run_returns_none(stub_db):
    summary = await get_run_summary(stub_db, str(uuid.uuid4()))
    assert summary is None


@pytest.mark.asyncio
async def test_record_run_case_idempotent_on_duplicate(stub_db):
    case_id = await upsert_case(
        stub_db,
        case_key="dup_unit",
        message_text="m",
        market_tag="coastal_30a",
        source="curated_seed",
        expected_intent_topic="booking_inquiry",
        expected_review=False,
    )
    run_id = await start_run(
        stub_db,
        invocation_id=str(uuid.uuid4()),
        classifier_source="llm",
    )
    await record_run_case(
        stub_db,
        run_id=run_id,
        case_id=case_id,
        passed=True,
        failure_reasons=[],
        urgency_note=None,
        actual_intent_topic="booking_inquiry",
        actual_secondary_topics=[],
        actual_sub_intents=["pricing"],
        actual_review=False,
        actual_urgency="medium",
        latency_ms=100,
        classifier_provider="anthropic",
    )
    await record_run_case(
        stub_db,
        run_id=run_id,
        case_id=case_id,
        passed=False,
        failure_reasons=["intent_topic_mismatch: ..."],
        urgency_note=None,
        actual_intent_topic="general",
        actual_secondary_topics=["maintenance"],
        actual_sub_intents=[],
        actual_review=True,
        actual_urgency="high",
        latency_ms=999,
        classifier_provider="groq",
    )
    details = await get_run_case_details(stub_db, run_id)
    assert len(details) == 1
    assert details[0].passed is False
    assert details[0].failure_reasons == ["intent_topic_mismatch: ..."]
