"""
test_eval_case_store_integration.py — Real-Postgres integration test for
the brain eval store.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import text


try:
    from app.db.session import SessionLocal

    _SESSION_AVAILABLE = True
except Exception as _import_exc:
    _SESSION_AVAILABLE = False
    _SESSION_IMPORT_ERROR = str(_import_exc)


pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not _SESSION_AVAILABLE,
        reason=(
            f"SessionLocal not available: "
            f"{_SESSION_IMPORT_ERROR if not _SESSION_AVAILABLE else ''}"
        ),
    ),
]


async def _check_eval_tables_exist(db: Any) -> bool:
    result = await db.execute(
        text(
            """
            SELECT COUNT(*)::int AS count
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name IN (
                'brain_eval_cases',
                'brain_eval_runs',
                'brain_eval_run_cases'
              )
            """
        )
    )
    row = result.first()
    return row is not None and row[0] == 3


@pytest_asyncio.fixture
async def real_db():
    db = None
    try:
        session_cm = SessionLocal()
        db = await session_cm.__aenter__()
        tables_exist = await _check_eval_tables_exist(db)
    except Exception as exc:  # noqa: BLE001
        if db is not None:
            try:
                await session_cm.__aexit__(type(exc), exc, exc.__traceback__)
            except Exception:
                pass
        pytest.skip(
            f"Cannot reach Postgres for integration test: "
            f"{type(exc).__name__}: {exc}"
        )

    try:
        if not tables_exist:
            pytest.fail(
                "brain_eval_* tables are missing in the test database. "
                "Migration 051_brain_eval_tables has not been applied. "
                "Run `alembic upgrade head` and re-run this test."
            )
        yield db
    finally:
        try:
            await session_cm.__aexit__(None, None, None)
        except Exception:
            pass


async def test_full_case_store_and_runner_lifecycle_against_postgres(real_db):
    from app.services.messaging_brain.eval.eval_case_store import (
        finish_run,
        get_case_by_key,
        get_run_case_details,
        get_run_summary,
        list_active_cases,
        record_run_case,
        start_run,
        upsert_case,
    )

    db = real_db
    run_token = uuid.uuid4().hex[:12]
    case_key_a = f"itest_{run_token}_alpha"
    case_key_b = f"itest_{run_token}_beta"
    market_tag = f"itest_market_{run_token}"

    created_case_ids: list[str] = []
    created_run_ids: list[str] = []

    try:
        case_id_a = await upsert_case(
            db,
            case_key=case_key_a,
            message_text="alpha message",
            market_tag=market_tag,
            source="curated_seed",
            expected_intent_topic="booking_inquiry",
            expected_secondary_topics=[],
            expected_sub_intents=["pricing"],
            expected_constraint_keys=["dates.check_in"],
            expected_review=False,
            expected_urgency="medium",
            notes="integration test alpha",
        )
        created_case_ids.append(case_id_a)

        case_id_b = await upsert_case(
            db,
            case_key=case_key_b,
            message_text="beta message",
            market_tag=market_tag,
            source="curated_seed",
            expected_intent_topic="emergency",
            expected_review=True,
        )
        created_case_ids.append(case_id_b)

        same_id = await upsert_case(
            db,
            case_key=case_key_a,
            message_text="alpha message v2",
            market_tag=market_tag,
            source="curated_seed",
            expected_intent_topic="booking_inquiry",
            expected_review=False,
        )
        assert same_id == case_id_a

        cases = await list_active_cases(db, market_tag=market_tag)
        assert len(cases) == 2
        assert {c.case_key for c in cases} == {case_key_a, case_key_b}

        alpha = next(c for c in cases if c.case_key == case_key_a)
        assert alpha.message_text == "alpha message v2"
        assert alpha.expected_sub_intents == []

        beta = await get_case_by_key(db, case_key_b)
        assert beta is not None
        assert beta.expected_intent_topic == "emergency"
        assert beta.expected_review is True

        invocation_id = str(uuid.uuid4())
        run_id = await start_run(
            db,
            invocation_id=invocation_id,
            classifier_source="llm",
            market_filter=market_tag,
            notes="integration test run",
        )
        created_run_ids.append(run_id)

        await record_run_case(
            db,
            run_id=run_id,
            case_id=case_id_a,
            passed=True,
            failure_reasons=[],
            urgency_note=None,
            actual_intent_topic="booking_inquiry",
            actual_secondary_topics=[],
            actual_sub_intents=["pricing"],
            actual_review=False,
            actual_urgency="medium",
            latency_ms=523,
            classifier_provider="anthropic",
        )
        await record_run_case(
            db,
            run_id=run_id,
            case_id=case_id_b,
            passed=False,
            failure_reasons=[
                "intent_topic_mismatch: expected='emergency', got='general'",
                "review_mismatch: expected=True, got=False",
            ],
            urgency_note="urgency_soft_mismatch: expected='emergency', got='medium'",
            actual_intent_topic="general",
            actual_secondary_topics=["maintenance"],
            actual_sub_intents=[],
            actual_review=False,
            actual_urgency="medium",
            latency_ms=489,
            classifier_provider="anthropic",
        )

        await finish_run(
            db,
            run_id,
            cases_evaluated=2,
            cases_passed=1,
            cases_failed=1,
            accuracy_overall=0.5,
            accuracy_by_market={market_tag: 0.5},
        )

        summary = await get_run_summary(db, run_id)
        assert summary is not None
        assert summary.invocation_id == invocation_id
        assert summary.classifier_source == "llm"
        assert summary.market_filter == market_tag
        assert summary.cases_evaluated == 2
        assert summary.cases_passed == 1
        assert summary.cases_failed == 1
        assert summary.accuracy_overall == 0.5
        assert summary.accuracy_by_market == {market_tag: 0.5}
        assert summary.run_completed_at is not None

        details = await get_run_case_details(db, run_id)
        assert len(details) == 2
        details_by_key = {d.case_key: d for d in details}
        assert details_by_key[case_key_a].passed is True
        assert details_by_key[case_key_a].failure_reasons == []
        assert details_by_key[case_key_b].passed is False
        assert len(details_by_key[case_key_b].failure_reasons) == 2
        assert details_by_key[case_key_b].urgency_note is not None

    finally:
        for run_id in created_run_ids:
            await db.execute(
                text("DELETE FROM brain_eval_runs WHERE id = :run_id"),
                {"run_id": run_id},
            )
        for case_id in created_case_ids:
            await db.execute(
                text("DELETE FROM brain_eval_cases WHERE id = :case_id"),
                {"case_id": case_id},
            )
        await db.commit()


async def test_fk_cascade_deletes_run_cases(real_db):
    from app.services.messaging_brain.eval.eval_case_store import (
        record_run_case,
        start_run,
        upsert_case,
    )

    db = real_db
    run_token = uuid.uuid4().hex[:12]
    case_key = f"itest_cascade_{run_token}"

    try:
        case_id = await upsert_case(
            db,
            case_key=case_key,
            message_text="cascade test",
            market_tag=f"itest_market_{run_token}",
            source="curated_seed",
            expected_intent_topic="general",
            expected_review=False,
        )
        run_id = await start_run(
            db,
            invocation_id=str(uuid.uuid4()),
            classifier_source="keyword",
        )
        await record_run_case(
            db,
            run_id=run_id,
            case_id=case_id,
            passed=True,
            failure_reasons=[],
            urgency_note=None,
            actual_intent_topic="general",
            actual_secondary_topics=[],
            actual_sub_intents=[],
            actual_review=False,
            actual_urgency=None,
        )

        result = await db.execute(
            text("SELECT COUNT(*)::int FROM brain_eval_run_cases WHERE run_id = :rid"),
            {"rid": run_id},
        )
        assert result.first()[0] == 1

        await db.execute(
            text("DELETE FROM brain_eval_runs WHERE id = :rid"),
            {"rid": run_id},
        )
        await db.commit()

        result = await db.execute(
            text("SELECT COUNT(*)::int FROM brain_eval_run_cases WHERE run_id = :rid"),
            {"rid": run_id},
        )
        assert result.first()[0] == 0
    finally:
        await db.execute(
            text("DELETE FROM brain_eval_cases WHERE case_key = :ck"),
            {"ck": case_key},
        )
        await db.commit()


async def test_record_run_case_is_idempotent_on_duplicate(real_db):
    from app.services.messaging_brain.eval.eval_case_store import (
        record_run_case,
        start_run,
        upsert_case,
    )

    db = real_db
    run_token = uuid.uuid4().hex[:12]
    case_key = f"itest_dup_{run_token}"
    run_id = None

    try:
        case_id = await upsert_case(
            db,
            case_key=case_key,
            message_text="dup test",
            market_tag=f"itest_market_{run_token}",
            source="curated_seed",
            expected_intent_topic="booking_inquiry",
            expected_review=False,
        )
        run_id = await start_run(
            db,
            invocation_id=str(uuid.uuid4()),
            classifier_source="llm",
        )

        await record_run_case(
            db,
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
            db,
            run_id=run_id,
            case_id=case_id,
            passed=False,
            failure_reasons=["intent_topic_mismatch: ..."],
            urgency_note="urgency_soft_mismatch: ...",
            actual_intent_topic="general",
            actual_secondary_topics=["maintenance"],
            actual_sub_intents=[],
            actual_review=True,
            actual_urgency="high",
            latency_ms=999,
            classifier_provider="groq",
        )

        result = await db.execute(
            text(
                """
                SELECT COUNT(*)::int FROM brain_eval_run_cases
                WHERE run_id = :rid AND case_id = :cid
                """
            ),
            {"rid": run_id, "cid": case_id},
        )
        assert result.first()[0] == 1

        result = await db.execute(
            text(
                """
                SELECT passed, actual_intent_topic, actual_review,
                       actual_urgency, classifier_provider, latency_ms
                FROM brain_eval_run_cases
                WHERE run_id = :rid AND case_id = :cid
                """
            ),
            {"rid": run_id, "cid": case_id},
        )
        row = result.mappings().first()
        assert row["passed"] is False
        assert row["actual_intent_topic"] == "general"
        assert row["actual_review"] is True
        assert row["actual_urgency"] == "high"
        assert row["classifier_provider"] == "groq"
        assert row["latency_ms"] == 999
    finally:
        if run_id is not None:
            await db.execute(
                text("DELETE FROM brain_eval_runs WHERE id = :rid"),
                {"rid": run_id},
            )
        await db.execute(
            text("DELETE FROM brain_eval_cases WHERE case_key = :ck"),
            {"ck": case_key},
        )
        await db.commit()
