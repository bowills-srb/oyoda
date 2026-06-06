"""
eval_case_store.py — Persistence layer for brain eval.

Session 10 (Phase 2) — see docs/PHASE_2_SEAM_MAP.md.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from app.services.messaging_brain.eval.eval_comparator import EvalCase

logger = logging.getLogger(__name__)


async def ensure_eval_tables(db: Any) -> None:
    """No-op. Eval tables are created by Alembic migration
    051_brain_eval_tables.
    """
    return None


async def upsert_case(
    db: Any,
    *,
    case_key: str,
    message_text: str,
    market_tag: str,
    source: str,
    expected_intent_topic: str,
    expected_secondary_topics: Optional[List[str]] = None,
    expected_sub_intents: Optional[List[str]] = None,
    expected_constraint_keys: Optional[List[str]] = None,
    expected_review: bool = False,
    expected_urgency: Optional[str] = None,
    notes: Optional[str] = None,
    is_active: bool = True,
) -> str:
    """Insert or update an eval case by case_key. Returns the case_id."""
    result = await db.execute(
        text(
            """
            INSERT INTO brain_eval_cases (
                case_key, message_text, market_tag, source,
                expected_intent_topic, expected_secondary_topics,
                expected_sub_intents, expected_constraint_keys,
                expected_review, expected_urgency, notes, is_active
            )
            VALUES (
                :case_key, :message_text, :market_tag, :source,
                :expected_intent_topic, :expected_secondary_topics,
                :expected_sub_intents, :expected_constraint_keys,
                :expected_review, :expected_urgency, :notes, :is_active
            )
            ON CONFLICT (case_key) DO UPDATE SET
                message_text              = EXCLUDED.message_text,
                market_tag                = EXCLUDED.market_tag,
                source                    = EXCLUDED.source,
                expected_intent_topic     = EXCLUDED.expected_intent_topic,
                expected_secondary_topics = EXCLUDED.expected_secondary_topics,
                expected_sub_intents      = EXCLUDED.expected_sub_intents,
                expected_constraint_keys  = EXCLUDED.expected_constraint_keys,
                expected_review           = EXCLUDED.expected_review,
                expected_urgency          = EXCLUDED.expected_urgency,
                notes                     = EXCLUDED.notes,
                is_active                 = EXCLUDED.is_active,
                updated_at                = NOW()
            RETURNING id
            """
        ),
        {
            "case_key": case_key,
            "message_text": message_text,
            "market_tag": market_tag,
            "source": source,
            "expected_intent_topic": expected_intent_topic,
            "expected_secondary_topics": expected_secondary_topics or [],
            "expected_sub_intents": expected_sub_intents or [],
            "expected_constraint_keys": expected_constraint_keys or [],
            "expected_review": expected_review,
            "expected_urgency": expected_urgency,
            "notes": notes,
            "is_active": is_active,
        },
    )
    row = result.first()
    await db.commit()
    return str(row[0])


async def list_active_cases(
    db: Any,
    *,
    market_tag: Optional[str] = None,
    case_keys: Optional[List[str]] = None,
) -> List[EvalCase]:
    """Return active eval cases, optionally filtered by market or case_keys."""
    query = """
        SELECT id, case_key, message_text, market_tag, source,
               expected_intent_topic, expected_secondary_topics,
               expected_sub_intents, expected_constraint_keys,
               expected_review, expected_urgency, notes
        FROM brain_eval_cases
        WHERE is_active = TRUE
    """
    params: Dict[str, Any] = {}
    if market_tag:
        query += " AND market_tag = :market_tag"
        params["market_tag"] = market_tag
    if case_keys:
        query += " AND case_key = ANY(:case_keys)"
        params["case_keys"] = list(case_keys)
    query += " ORDER BY market_tag, case_key"

    result = await db.execute(text(query), params)
    rows = result.mappings().all()
    return [
        EvalCase(
            case_id=str(row["id"]),
            case_key=row["case_key"],
            message_text=row["message_text"],
            market_tag=row["market_tag"],
            source=row["source"],
            expected_intent_topic=row["expected_intent_topic"],
            expected_secondary_topics=list(row["expected_secondary_topics"] or []),
            expected_sub_intents=list(row["expected_sub_intents"] or []),
            expected_constraint_keys=list(row["expected_constraint_keys"] or []),
            expected_review=bool(row["expected_review"]),
            expected_urgency=row["expected_urgency"],
            notes=row["notes"] or "",
        )
        for row in rows
    ]


async def get_case_by_key(db: Any, case_key: str) -> Optional[EvalCase]:
    """Look up a single eval case by case_key."""
    cases = await list_active_cases(db, case_keys=[case_key])
    return cases[0] if cases else None


async def start_run(
    db: Any,
    *,
    invocation_id: str,
    classifier_source: str,
    market_filter: Optional[str] = None,
    notes: Optional[str] = None,
) -> str:
    """Open a new brain_eval_runs row. Returns the run_id."""
    result = await db.execute(
        text(
            """
            INSERT INTO brain_eval_runs (
                invocation_id, classifier_source, market_filter, notes
            )
            VALUES (
                :invocation_id, :classifier_source, :market_filter, :notes
            )
            RETURNING id
            """
        ),
        {
            "invocation_id": invocation_id,
            "classifier_source": classifier_source,
            "market_filter": market_filter,
            "notes": notes,
        },
    )
    row = result.first()
    await db.commit()
    return str(row[0])


async def finish_run(
    db: Any,
    run_id: str,
    *,
    cases_evaluated: int,
    cases_passed: int,
    cases_failed: int,
    accuracy_overall: float,
    accuracy_by_market: Dict[str, Optional[float]],
) -> None:
    """Close out a brain_eval_runs row with aggregates."""
    await db.execute(
        text(
            """
            UPDATE brain_eval_runs
               SET run_completed_at   = NOW(),
                   status             = 'completed',
                   cases_evaluated    = :cases_evaluated,
                   cases_passed       = :cases_passed,
                   cases_failed       = :cases_failed,
                   accuracy_overall   = :accuracy_overall,
                   accuracy_by_market = CAST(:accuracy_by_market AS jsonb)
             WHERE id = :run_id
            """
        ),
        {
            "run_id": run_id,
            "cases_evaluated": cases_evaluated,
            "cases_passed": cases_passed,
            "cases_failed": cases_failed,
            "accuracy_overall": accuracy_overall,
            "accuracy_by_market": json.dumps(accuracy_by_market),
        },
    )
    await db.commit()


async def fail_run(
    db: Any,
    run_id: str,
    *,
    error_note: Optional[str] = None,
) -> None:
    """Mark a run as failed and set run_completed_at.

    Failed runs are durable evidence that something went wrong. Aggregates
    are left at whatever values had already been persisted.
    """
    if error_note:
        await db.execute(
            text(
                """
                UPDATE brain_eval_runs
                   SET status = 'failed',
                       run_completed_at = NOW(),
                       notes = COALESCE(notes || E'\\n', '') || :error_note
                 WHERE id = :run_id
                """
            ),
            {"run_id": run_id, "error_note": error_note},
        )
    else:
        await db.execute(
            text(
                """
                UPDATE brain_eval_runs
                   SET status = 'failed',
                       run_completed_at = NOW()
                 WHERE id = :run_id
                """
            ),
            {"run_id": run_id},
        )
    await db.commit()


async def record_run_case(
    db: Any,
    *,
    run_id: str,
    case_id: str,
    passed: bool,
    failure_reasons: List[str],
    urgency_note: Optional[str],
    actual_intent_topic: str,
    actual_secondary_topics: List[str],
    actual_sub_intents: List[str],
    actual_review: bool,
    actual_urgency: Optional[str],
    latency_ms: Optional[int] = None,
    classifier_provider: Optional[str] = None,
) -> None:
    """Insert a brain_eval_run_cases row capturing the per-case outcome."""
    await db.execute(
        text(
            """
            INSERT INTO brain_eval_run_cases (
                run_id, case_id, passed, failure_reasons, urgency_note,
                actual_intent_topic, actual_secondary_topics,
                actual_sub_intents, actual_review, actual_urgency,
                latency_ms, classifier_provider
            )
            VALUES (
                :run_id, :case_id, :passed, :failure_reasons, :urgency_note,
                :actual_intent_topic, :actual_secondary_topics,
                :actual_sub_intents, :actual_review, :actual_urgency,
                :latency_ms, :classifier_provider
            )
            ON CONFLICT (run_id, case_id) DO UPDATE SET
                passed                  = EXCLUDED.passed,
                failure_reasons         = EXCLUDED.failure_reasons,
                urgency_note            = EXCLUDED.urgency_note,
                actual_intent_topic     = EXCLUDED.actual_intent_topic,
                actual_secondary_topics = EXCLUDED.actual_secondary_topics,
                actual_sub_intents      = EXCLUDED.actual_sub_intents,
                actual_review           = EXCLUDED.actual_review,
                actual_urgency          = EXCLUDED.actual_urgency,
                latency_ms              = EXCLUDED.latency_ms,
                classifier_provider     = EXCLUDED.classifier_provider,
                created_at              = NOW()
            """
        ),
        {
            "run_id": run_id,
            "case_id": case_id,
            "passed": passed,
            "failure_reasons": failure_reasons,
            "urgency_note": urgency_note,
            "actual_intent_topic": actual_intent_topic,
            "actual_secondary_topics": actual_secondary_topics,
            "actual_sub_intents": actual_sub_intents,
            "actual_review": actual_review,
            "actual_urgency": actual_urgency,
            "latency_ms": latency_ms,
            "classifier_provider": classifier_provider,
        },
    )
    await db.commit()


@dataclass(frozen=True)
class RunSummary:
    """Compact view of a brain_eval_runs row for CLI reporting."""

    run_id: str
    invocation_id: str
    classifier_source: str
    market_filter: Optional[str]
    status: str
    cases_evaluated: int
    cases_passed: int
    cases_failed: int
    accuracy_overall: Optional[float]
    accuracy_by_market: Dict[str, Any]
    run_started_at: datetime
    run_completed_at: Optional[datetime]


async def get_run_summary(db: Any, run_id: str) -> Optional[RunSummary]:
    """Fetch a single brain_eval_runs row as a RunSummary."""
    result = await db.execute(
        text(
            """
            SELECT id, invocation_id, classifier_source, market_filter,
                   status, cases_evaluated, cases_passed, cases_failed,
                   accuracy_overall, accuracy_by_market,
                   run_started_at, run_completed_at
            FROM brain_eval_runs
            WHERE id = :run_id
            """
        ),
        {"run_id": run_id},
    )
    row = result.mappings().first()
    if not row:
        return None
    return RunSummary(
        run_id=str(row["id"]),
        invocation_id=str(row["invocation_id"]),
        classifier_source=row["classifier_source"],
        market_filter=row["market_filter"],
        status=row["status"],
        cases_evaluated=row["cases_evaluated"],
        cases_passed=row["cases_passed"],
        cases_failed=row["cases_failed"],
        accuracy_overall=(
            float(row["accuracy_overall"])
            if row["accuracy_overall"] is not None
            else None
        ),
        accuracy_by_market=dict(row["accuracy_by_market"] or {}),
        run_started_at=row["run_started_at"],
        run_completed_at=row["run_completed_at"],
    )


@dataclass(frozen=True)
class RunCaseDetail:
    """Per-case outcome for CLI reporting."""

    case_key: str
    market_tag: str
    passed: bool
    failure_reasons: List[str]
    urgency_note: Optional[str]


async def get_run_case_details(db: Any, run_id: str) -> List[RunCaseDetail]:
    """Fetch all per-case outcomes for a run."""
    result = await db.execute(
        text(
            """
            SELECT c.case_key, c.market_tag, rc.passed,
                   rc.failure_reasons, rc.urgency_note
            FROM brain_eval_run_cases rc
            JOIN brain_eval_cases c ON c.id = rc.case_id
            WHERE rc.run_id = :run_id
            ORDER BY c.market_tag, c.case_key
            """
        ),
        {"run_id": run_id},
    )
    rows = result.mappings().all()
    return [
        RunCaseDetail(
            case_key=row["case_key"],
            market_tag=row["market_tag"],
            passed=bool(row["passed"]),
            failure_reasons=list(row["failure_reasons"] or []),
            urgency_note=row["urgency_note"],
        )
        for row in rows
    ]
