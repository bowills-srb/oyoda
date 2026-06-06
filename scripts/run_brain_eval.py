#!/usr/bin/env python3
"""
run_brain_eval.py — CLI entry point for brain eval.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from typing import List, Optional

from app.services.messaging_brain.eval.eval_runner import (
    EvalRunResult,
    format_run_report,
    run_eval,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run brain eval against active cases.")
    parser.add_argument(
        "--classifier",
        choices=("keyword", "llm", "both"),
        default="both",
        help="Which classifier to evaluate (default: both).",
    )
    parser.add_argument(
        "--market",
        default=None,
        help="Filter to cases with this market_tag (e.g. coastal_30a).",
    )
    parser.add_argument(
        "--case-key",
        default=None,
        action="append",
        help="Run only this case_key. Repeatable.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't write brain_eval_runs / brain_eval_run_cases rows.",
    )
    parser.add_argument(
        "--notes",
        default=None,
        help="Free-form notes to attach to the run header(s).",
    )
    return parser.parse_args()


async def _run_one_classifier(
    *,
    db,
    classifier_source: str,
    invocation_id: str,
    market_filter: Optional[str],
    case_keys: Optional[List[str]],
    dry_run: bool,
    notes: Optional[str],
) -> EvalRunResult:
    """Construct the requested classifier and run eval."""
    if classifier_source == "llm":
        from app.services.messaging_brain.agents.llm_intake_agent import LLMIntakeAgent

        classifier = LLMIntakeAgent()
    else:
        from app.services.messaging_brain.agents.intake_agent import IntakeAgent

        classifier = IntakeAgent()

    return await run_eval(
        db=db,
        classifier=classifier,
        classifier_source=classifier_source,
        invocation_id=invocation_id,
        market_filter=market_filter,
        case_keys=case_keys,
        dry_run=dry_run,
        notes=notes,
    )


async def _run(args: argparse.Namespace) -> int:
    from app.db.session import SessionLocal

    invocation_id = str(uuid.uuid4())
    classifiers_to_run: List[str]
    if args.classifier == "both":
        classifiers_to_run = ["keyword", "llm"]
    else:
        classifiers_to_run = [args.classifier]

    print(f"Invocation: {invocation_id}")
    if args.dry_run:
        print("(dry-run — no rows will be written)")
    print()

    async with SessionLocal() as db:
        for source in classifiers_to_run:
            try:
                result = await _run_one_classifier(
                    db=db,
                    classifier_source=source,
                    invocation_id=invocation_id,
                    market_filter=args.market,
                    case_keys=args.case_key,
                    dry_run=args.dry_run,
                    notes=args.notes,
                )
            except Exception as exc:
                print(f"[{source}] FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
                continue
            print(format_run_report(result))
            print("─" * 72)
    return 0


def main() -> int:
    args = _parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
