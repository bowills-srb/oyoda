"""
app.services.messaging_brain.eval — Brain eval infrastructure.

Session 10 (Phase 2) — see docs/PHASE_2_SEAM_MAP.md.

Public API:

  EvalCase, ComparisonResult, compare_classification
    — pure comparison logic (no I/O)

  EvalRunner-shaped:
    run_eval(...)          — async, runs a classifier against active cases
    EvalRunResult          — aggregate result from a run
    CaseRunResult          — per-case result inside a run
    format_run_report(...) — text report formatter for CLI

  Persistence:
    ensure_eval_tables(db)
    upsert_case(db, ...)
    list_active_cases(db, *, market_tag=None, case_keys=None)
    get_case_by_key(db, case_key)
    get_run_summary(db, run_id)
    get_run_case_details(db, run_id)
"""

from app.services.messaging_brain.eval.eval_case_store import (
    RunCaseDetail,
    RunSummary,
    ensure_eval_tables,
    finish_run,
    get_case_by_key,
    get_run_case_details,
    get_run_summary,
    list_active_cases,
    record_run_case,
    start_run,
    upsert_case,
)
from app.services.messaging_brain.eval.eval_comparator import (
    ComparisonResult,
    EvalCase,
    compare_classification,
)
from app.services.messaging_brain.eval.eval_runner import (
    CaseRunResult,
    ClassifierProtocol,
    EvalRunResult,
    format_run_report,
    run_eval,
)

__all__ = [
    "EvalCase",
    "ComparisonResult",
    "compare_classification",
    "ClassifierProtocol",
    "CaseRunResult",
    "EvalRunResult",
    "run_eval",
    "format_run_report",
    "ensure_eval_tables",
    "upsert_case",
    "list_active_cases",
    "get_case_by_key",
    "start_run",
    "finish_run",
    "record_run_case",
    "get_run_summary",
    "get_run_case_details",
    "RunSummary",
    "RunCaseDetail",
]
