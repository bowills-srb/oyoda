from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional

from sqlalchemy import text

REPO_ROOT = Path(__file__).resolve().parents[1]
if not (REPO_ROOT / "app").exists():
    cwd_root = Path.cwd()
    if (cwd_root / "app").exists():
        REPO_ROOT = cwd_root
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.database import get_db_session
from app.services.messaging.inbox_adapters import (
    InboxAdapterBuildError,
    InboxAdapterConfig,
    build_inbox_adapter,
)
from app.workers.tasks import (
    _DryRunLLMExtractor,
    _REPLAY_DEFAULT_STATES,
    _replay_discrepancy_category,
    _replay_route_bucket,
)


DEFAULT_TENANT_ID = "e07980b2-a990-4b24-91d1-c8cb71ab70e1"


@dataclass
class WindowReplaySummary:
    label: str
    start_at: str
    end_at: str
    states_considered: List[str]
    messages_selected: int
    messages_analyzed: int
    messages_missing: int
    messages_fetch_errors: int
    messages_unsupported_provider: int
    counts_by_new_route: Dict[str, int]
    counts_by_new_parser: Dict[str, int]
    counts_by_original_parser: Dict[str, int]
    counts_by_discrepancy: Dict[str, int]
    sample_concerns: List[Dict[str, Any]]
    sample_disagreements: List[Dict[str, Any]]


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat()


async def _load_window_rows(
    *,
    tenant_id: str,
    start_at: datetime,
    end_at: datetime,
    include_states: List[str],
    scan_limit: Optional[int],
) -> List[Dict[str, Any]]:
    state_clause = ""
    params: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "start_at": start_at,
        "end_at": end_at,
    }
    if include_states:
        placeholders = []
        for idx, state in enumerate(include_states):
            key = f"state_{idx}"
            params[key] = state
            placeholders.append(f":{key}")
        state_clause = f"AND COALESCE(gpm.processing_status, '') IN ({', '.join(placeholders)})"

    limit_clause = ""
    if scan_limit is not None and scan_limit > 0:
        params["scan_limit"] = int(scan_limit)
        limit_clause = "LIMIT :scan_limit"

    async with get_db_session() as db:
        result = await db.execute(
            text(
                f"""
                SELECT
                    gpm.operator_id,
                    gpm.gmail_message_id,
                    COALESCE(gpm.processing_status, '') AS processing_status,
                    COALESCE(gpm.last_failure_reason, '') AS last_failure_reason,
                    gc.tenant_id,
                    gc.watched_email,
                    gc.refresh_token,
                    COALESCE(gc.email_provider, 'gmail') AS email_provider,
                    COALESCE(mn.parser_used, '') AS original_parser_used,
                    COALESCE(mn.route_outcome, '') AS original_route_outcome,
                    COALESCE(mn.raw_subject, '') AS original_subject,
                    COALESCE(mn.sender_address, '') AS original_sender_address,
                    COALESCE(gpm.last_attempted_at, gpm.processed_at, gpm.first_seen_at) AS activity_at
                FROM gmail_processed_messages gpm
                JOIN operator_gmail_creds gc
                  ON gc.operator_id = CAST(gpm.operator_id AS uuid)
                LEFT JOIN message_normalizations mn
                  ON mn.tenant_id = gc.tenant_id
                 AND mn.source_channel = 'email'
                 AND mn.source_message_id = gpm.gmail_message_id
                WHERE gc.tenant_id = CAST(:tenant_id AS uuid)
                  AND COALESCE(gpm.last_attempted_at, gpm.processed_at, gpm.first_seen_at) >= :start_at
                  AND COALESCE(gpm.last_attempted_at, gpm.processed_at, gpm.first_seen_at) < :end_at
                {state_clause}
                ORDER BY activity_at DESC NULLS LAST
                {limit_clause}
                """
            ),
            params,
        )
        return [dict(row) for row in result.mappings().all()]


async def _analyze_window(
    *,
    tenant_id: str,
    start_at: datetime,
    end_at: datetime,
    include_states: List[str],
    scan_limit: Optional[int],
    sample_limit: int,
) -> WindowReplaySummary:
    rows = await _load_window_rows(
        tenant_id=tenant_id,
        start_at=start_at,
        end_at=end_at,
        include_states=include_states,
        scan_limit=scan_limit,
    )

    poller_cache: Dict[str, Any] = {}
    headers_cache: Dict[str, Dict[str, str]] = {}
    counts_by_new_route: Counter[str] = Counter()
    counts_by_new_parser: Counter[str] = Counter()
    counts_by_original_parser: Counter[str] = Counter()
    counts_by_discrepancy: Counter[str] = Counter()
    sample_concerns: List[Dict[str, Any]] = []
    sample_disagreements: List[Dict[str, Any]] = []
    missing_messages = 0
    fetch_errors = 0
    unsupported_rows = 0
    analyzed = 0

    async with get_db_session() as db:
        for row in rows:
            operator_id = str(row["operator_id"])
            provider = (row["email_provider"] or "gmail").strip().lower()
            normalized_provider = "gmail" if provider in {"gmail", "google"} else provider
            if normalized_provider != "gmail":
                unsupported_rows += 1
                continue

            poller = poller_cache.get(operator_id)
            headers = headers_cache.get(operator_id)
            if poller is None:
                try:
                    poller = build_inbox_adapter(
                        InboxAdapterConfig(
                            operator_id=operator_id,
                            company_id=row["tenant_id"],
                            watched_email=row["watched_email"],
                            refresh_token=row["refresh_token"],
                            provider=normalized_provider,
                        ),
                        db=db,
                    )
                except InboxAdapterBuildError:
                    unsupported_rows += 1
                    continue

                if not poller or not hasattr(poller, "_get_full_message") or not hasattr(poller, "_parse_with_ota_fallback"):
                    unsupported_rows += 1
                    continue

                token = await poller.token_manager.get_access_token()
                headers = poller.token_manager.auth_header(token)
                poller_cache[operator_id] = poller
                headers_cache[operator_id] = headers

            gmail_message_id = str(row["gmail_message_id"] or "").strip()
            if not gmail_message_id:
                continue

            try:
                raw_message = await poller._get_full_message(gmail_message_id, headers)
            except Exception:
                fetch_errors += 1
                continue

            if not raw_message:
                missing_messages += 1
                continue

            parsed = await poller._parse_with_ota_fallback(
                raw_message,
                llm_extractor_factory=_DryRunLLMExtractor,
            )
            non_guest_reason = getattr(poller, "_last_non_guest_reason", "") or ""
            new_parser_source = getattr(parsed, "parser_source", "") if parsed else ""
            new_route_bucket = _replay_route_bucket(
                new_parser_source,
                non_guest_reason=non_guest_reason,
            )
            original_parser_used = str(row["original_parser_used"] or "")
            original_route_outcome = str(row["original_route_outcome"] or "")
            discrepancy_category = _replay_discrepancy_category(
                original_parser_used=original_parser_used,
                original_route_outcome=original_route_outcome,
                new_route_bucket=new_route_bucket,
            )

            counts_by_new_route[new_route_bucket] += 1
            counts_by_new_parser[new_parser_source or "(none)"] += 1
            counts_by_original_parser[original_parser_used or "(none)"] += 1
            counts_by_discrepancy[discrepancy_category] += 1
            analyzed += 1

            sample = {
                "gmail_message_id": gmail_message_id,
                "operator_id": operator_id,
                "processing_status": str(row["processing_status"] or ""),
                "activity_at": _iso(row["activity_at"]),
                "original_parser_used": original_parser_used or None,
                "original_route_outcome": original_route_outcome or None,
                "new_route_bucket": new_route_bucket,
                "new_parser_source": new_parser_source or None,
                "non_guest_reason": non_guest_reason or None,
                "subject": (getattr(parsed, "subject", "") or str(row["original_subject"] or ""))[:200],
                "sender": (getattr(parsed, "raw_from", "") or str(row["original_sender_address"] or ""))[:200],
            }
            if discrepancy_category != "none" and len(sample_concerns) < sample_limit:
                sample_concerns.append({**sample, "discrepancy": discrepancy_category})
            if (
                original_parser_used
                and new_parser_source
                and original_parser_used != new_parser_source
                and len(sample_disagreements) < sample_limit
            ):
                sample_disagreements.append(sample)

    return WindowReplaySummary(
        label=f"{start_at.date()}..{(end_at - timedelta(seconds=1)).date()}",
        start_at=_iso(start_at),
        end_at=_iso(end_at),
        states_considered=include_states,
        messages_selected=len(rows),
        messages_analyzed=analyzed,
        messages_missing=missing_messages,
        messages_fetch_errors=fetch_errors,
        messages_unsupported_provider=unsupported_rows,
        counts_by_new_route=dict(sorted(counts_by_new_route.items())),
        counts_by_new_parser=dict(sorted(counts_by_new_parser.items())),
        counts_by_original_parser=dict(sorted(counts_by_original_parser.items())),
        counts_by_discrepancy=dict(sorted(counts_by_discrepancy.items())),
        sample_concerns=sample_concerns,
        sample_disagreements=sample_disagreements,
    )


async def _run_report(args: argparse.Namespace) -> Dict[str, Any]:
    end_at = datetime.now(UTC)
    windows: List[WindowReplaySummary] = []
    aggregate_route: Counter[str] = Counter()
    aggregate_discrepancy: Counter[str] = Counter()

    for idx in range(args.weeks):
        window_end = end_at - timedelta(days=7 * idx)
        window_start = window_end - timedelta(days=7)
        summary = await _analyze_window(
            tenant_id=args.tenant_id,
            start_at=window_start,
            end_at=window_end,
            include_states=args.include_states,
            scan_limit=args.scan_limit,
            sample_limit=args.sample_limit,
        )
        windows.append(summary)
        aggregate_route.update(summary.counts_by_new_route)
        aggregate_discrepancy.update(summary.counts_by_discrepancy)

    windows.reverse()

    return {
        "tenant_id": args.tenant_id,
        "generated_at": _iso(datetime.now(UTC)),
        "weeks": args.weeks,
        "include_states": args.include_states,
        "scan_limit_per_window": args.scan_limit,
        "aggregate_counts_by_new_route": dict(sorted(aggregate_route.items())),
        "aggregate_counts_by_discrepancy": dict(sorted(aggregate_discrepancy.items())),
        "windows": [asdict(window) for window in windows],
        "notes": [
            "Uses the live Gmail parsing chain against historical messages.",
            "Does not call external LLMs; dry-run LLM routing is marked with parser_source=dryrun_llm_route_only_groq.",
            "Does not mutate production state.",
            "Validates transport/parser/router behavior, not downstream send behavior.",
        ],
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Replay recent historical inbox traffic in rolling 7-day windows without mutating production state.",
    )
    parser.add_argument("--tenant-id", default=DEFAULT_TENANT_ID)
    parser.add_argument("--weeks", type=int, default=4)
    parser.add_argument(
        "--include-state",
        dest="include_states",
        action="append",
        default=list(_REPLAY_DEFAULT_STATES),
        help="Repeatable gmail_processed_messages.processing_status filter.",
    )
    parser.add_argument(
        "--scan-limit",
        type=int,
        default=None,
        help="Optional per-window row cap after date filtering.",
    )
    parser.add_argument(
        "--sample-limit",
        type=int,
        default=10,
        help="Max concern/disagreement samples to retain per window.",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Optional path to write the JSON report.",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    report = asyncio.run(_run_report(args))
    payload = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.write("\n")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
