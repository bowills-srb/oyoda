"""
eval_runner.py — Runs a classifier against the active eval set.

Session 10 (Phase 2) — see docs/PHASE_2_SEAM_MAP.md.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol

from app.services.messaging_brain.eval.eval_case_store import (
    fail_run,
    finish_run,
    list_active_cases,
    record_run_case,
    start_run,
)
from app.services.messaging_brain.eval.eval_comparator import (
    ComparisonResult,
    EvalCase,
    compare_classification,
)
from app.services.orchestration.messaging_brain_contracts import (
    InboundGuestMessage,
    MessageClassification,
)

logger = logging.getLogger(__name__)


class ClassifierProtocol(Protocol):
    """Either IntakeAgent (keyword) or LLMIntakeAgent satisfies this."""

    name: str

    async def classify(
        self,
        message: InboundGuestMessage,
        *,
        db_session: Any = None,
    ) -> MessageClassification: ...


@dataclass
class CaseRunResult:
    """In-memory result for a single case in a single run."""

    case: EvalCase
    classification: MessageClassification
    comparison: ComparisonResult
    latency_ms: int
    classifier_provider: Optional[str]


@dataclass
class EvalRunResult:
    """Aggregate result for a full run. Returned by run_eval()."""

    run_id: Optional[str]
    invocation_id: str
    classifier_source: str
    market_filter: Optional[str]
    cases_evaluated: int
    cases_passed: int
    cases_failed: int
    accuracy_overall: float
    accuracy_by_market: Dict[str, Optional[float]]
    case_results: List[CaseRunResult] = field(default_factory=list)
    dry_run: bool = False


async def run_eval(
    *,
    db: Any,
    classifier: ClassifierProtocol,
    classifier_source: str,
    invocation_id: Optional[str] = None,
    market_filter: Optional[str] = None,
    case_keys: Optional[List[str]] = None,
    dry_run: bool = False,
    notes: Optional[str] = None,
) -> EvalRunResult:
    """Run the active eval set against the given classifier."""
    if classifier_source not in ("llm", "keyword"):
        raise ValueError(
            f"classifier_source must be 'llm' or 'keyword', got {classifier_source!r}"
        )

    invocation = invocation_id or str(uuid.uuid4())
    cases = await list_active_cases(db, market_tag=market_filter, case_keys=case_keys)
    if not cases:
        logger.warning(
            "[EvalRunner] No active cases match filter: market_tag=%r, case_keys=%r",
            market_filter,
            case_keys,
        )
        return EvalRunResult(
            run_id=None,
            invocation_id=invocation,
            classifier_source=classifier_source,
            market_filter=market_filter,
            cases_evaluated=0,
            cases_passed=0,
            cases_failed=0,
            accuracy_overall=0.0,
            accuracy_by_market={},
            case_results=[],
            dry_run=dry_run,
        )

    run_id: Optional[str] = None
    if not dry_run:
        run_id = await start_run(
            db,
            invocation_id=invocation,
            classifier_source=classifier_source,
            market_filter=market_filter,
            notes=notes,
        )

    case_results: List[CaseRunResult] = []
    try:
        for case in cases:
            result = await _evaluate_case(
                case=case,
                classifier=classifier,
                classifier_source=classifier_source,
                db_session=db,
            )
            case_results.append(result)

            if not dry_run and run_id is not None:
                actual_urgency = (
                    result.classification.urgency.value
                    if hasattr(result.classification.urgency, "value")
                    else str(result.classification.urgency)
                )
                await record_run_case(
                    db,
                    run_id=run_id,
                    case_id=case.case_id,
                    passed=result.comparison.passed,
                    failure_reasons=result.comparison.failures,
                    urgency_note=result.comparison.urgency_note,
                    actual_intent_topic=result.classification.intent_topic,
                    actual_secondary_topics=list(result.classification.secondary_topics),
                    actual_sub_intents=list(result.classification.sub_intents),
                    actual_review=bool(result.classification.requires_human_review),
                    actual_urgency=actual_urgency,
                    latency_ms=result.latency_ms,
                    classifier_provider=result.classifier_provider,
                )
    except Exception as exc:
        if not dry_run and run_id is not None:
            try:
                await fail_run(
                    db,
                    run_id,
                    error_note=f"{type(exc).__name__}: {exc}",
                )
            except Exception:
                logger.exception(
                    "[EvalRunner] fail_run() raised while handling run loop error"
                )
        raise

    cases_passed = sum(1 for r in case_results if r.comparison.passed)
    cases_failed = len(case_results) - cases_passed
    accuracy_overall = cases_passed / len(case_results) if case_results else 0.0
    accuracy_by_market = _compute_accuracy_by_market(case_results)

    if not dry_run and run_id is not None:
        try:
            await finish_run(
                db,
                run_id,
                cases_evaluated=len(case_results),
                cases_passed=cases_passed,
                cases_failed=cases_failed,
                accuracy_overall=accuracy_overall,
                accuracy_by_market=accuracy_by_market,
            )
        except Exception as exc:
            try:
                await fail_run(
                    db,
                    run_id,
                    error_note=f"finish_run_failed: {type(exc).__name__}: {exc}",
                )
            except Exception:
                logger.exception(
                    "[EvalRunner] fail_run() raised while handling finish_run error"
                )
            raise

    return EvalRunResult(
        run_id=run_id,
        invocation_id=invocation,
        classifier_source=classifier_source,
        market_filter=market_filter,
        cases_evaluated=len(case_results),
        cases_passed=cases_passed,
        cases_failed=cases_failed,
        accuracy_overall=accuracy_overall,
        accuracy_by_market=accuracy_by_market,
        case_results=case_results,
        dry_run=dry_run,
    )


async def _evaluate_case(
    *,
    case: EvalCase,
    classifier: ClassifierProtocol,
    classifier_source: str,
    db_session: Any = None,
) -> CaseRunResult:
    """Classify one case's message_text and compare to expected."""
    message = InboundGuestMessage(
        message_id=f"eval_{case.case_key}",
        tenant_id="00000000-0000-0000-0000-000000000000",
        channel="eval",
        text=case.message_text,
    )

    start = time.monotonic()
    classifier_provider: Optional[str] = None

    classify_with_metadata = getattr(classifier, "classify_with_metadata", None)
    if callable(classify_with_metadata):
        classification, metadata = await classify_with_metadata(
            message, db_session=db_session
        )
        classifier_provider = metadata.provider_used
    else:
        classification = await classifier.classify(message, db_session=db_session)

    latency_ms = int((time.monotonic() - start) * 1000)
    comparison = compare_classification(
        classification,
        case,
        classifier_source=classifier_source,
    )

    return CaseRunResult(
        case=case,
        classification=classification,
        comparison=comparison,
        latency_ms=latency_ms,
        classifier_provider=classifier_provider,
    )


def _compute_accuracy_by_market(
    case_results: List[CaseRunResult],
) -> Dict[str, Optional[float]]:
    """Return per-market accuracy as a dict."""
    grouped: Dict[str, List[bool]] = {}
    for result in case_results:
        market = result.case.market_tag
        grouped.setdefault(market, []).append(result.comparison.passed)

    return {
        market: (sum(passes) / len(passes)) if passes else None
        for market, passes in grouped.items()
    }


def format_run_report(result: EvalRunResult) -> str:
    """Produce a human-readable text report of an EvalRunResult."""
    lines: List[str] = []
    header = f"Brain eval - classifier: {result.classifier_source}"
    if result.dry_run:
        header += " (dry run, not persisted)"
    lines.append(header)
    if result.run_id:
        lines.append(f"  run_id: {result.run_id}")
    lines.append(f"  invocation_id: {result.invocation_id}")
    if result.market_filter:
        lines.append(f"  market_filter: {result.market_filter}")
    lines.append("")
    lines.append(f"Cases evaluated: {result.cases_evaluated}")
    lines.append(f"Cases passed:    {result.cases_passed}")
    lines.append(f"Cases failed:    {result.cases_failed}")
    lines.append(f"Overall accuracy: {result.accuracy_overall:.3f}")
    lines.append("")

    if result.accuracy_by_market:
        lines.append("Per-market accuracy:")
        for market in sorted(result.accuracy_by_market):
            acc = result.accuracy_by_market[market]
            count = sum(1 for r in result.case_results if r.case.market_tag == market)
            passed = sum(
                1
                for r in result.case_results
                if r.case.market_tag == market and r.comparison.passed
            )
            acc_str = f"{acc:.3f}" if acc is not None else "n/a"
            lines.append(f"  {market}: {passed}/{count} ({acc_str})")
        lines.append("")

    failures = [r for r in result.case_results if not r.comparison.passed]
    if failures:
        lines.append("Failures:")
        for r in failures:
            lines.append(f"  {r.case.case_key} ({r.case.market_tag}):")
            for reason in r.comparison.failures:
                lines.append(f"    - {reason}")
            if r.comparison.urgency_note:
                lines.append(f"    (urgency note: {r.comparison.urgency_note})")
        lines.append("")

    urgency_only = [
        r for r in result.case_results if r.comparison.passed and r.comparison.urgency_note
    ]
    if urgency_only:
        lines.append("Urgency soft-mismatches (not counted in pass/fail):")
        for r in urgency_only:
            lines.append(f"  {r.case.case_key}: {r.comparison.urgency_note}")
        lines.append("")

    return "\n".join(lines)
