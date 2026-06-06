"""
filtered_recovery_service.py — shared aggregation for filtered message counts.

FILTERED_ROUTE_OUTCOMES and compute_filtered_counts() are the single source of
truth for the filtered-message taxonomy. Both the /filtered endpoint (drawer
row list + count) and DashboardSummaryService (Home trust card) call
compute_filtered_counts so the card count and drawer total are structurally
guaranteed to agree for the same window + scope.
"""
from __future__ import annotations

import logging
import time as _time
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_WINDOW_INTERVALS = {
    "today": "1 day",
    "7d": "7 days",
    "30d": "30 days",
}

# ─────────────────────────────────────────────────────────────────────────────
# Route-outcome taxonomy
#
# Explicit allow-list (not a NOT-IN over actionable outcomes) so a newly added
# actionable outcome never silently leaks into the Filtered view, and a newly
# added suppressed outcome requires a deliberate one-line addition here.
# ─────────────────────────────────────────────────────────────────────────────

FILTERED_ROUTE_OUTCOMES: dict[str, str] = {
    # Layer-1 / pipeline suppression
    "layer1_drop": "suppressed",
    "dropped": "suppressed",
    # Inbound gate decisions
    "pre_booking_gate_skipped": "non_guest",
    "pre_booking_gate_review": "needs_review",
    "pre_booking_gate_error": "needs_review",
    # System / vendor lanes that never enter the guest queue
    "vendor_ops_email": "non_guest",
    "review_event_ignored": "system",
    "review_event_unmatched_session": "system",
    "review_event_missing_property_binding": "system",
    "system_event_missing_property_binding": "system",
    "system_event_session_failed": "system",
    # Fallback / route failures — recorded but worth an operator glance
    "pre_booking_fallback": "needs_review",
    "guest_session_route_failed": "needs_review",
    # Save failures — classified as a guest inquiry but could not be persisted
    "save_failed": "needs_review",
    "pre_booking_save_failed": "needs_review",
    # Routing exception — written by gmail poller exception handler when
    # _route_message throws and the fallback save also fails
    "route_exception": "needs_review",
    # Defensive mappings for old backfill / migration outcomes
    "historical_unprocessed": "system",
    "general": "system",
    "local_recommendation": "system",
}


def filtered_reason_for(route_outcome: str) -> Optional[str]:
    return FILTERED_ROUTE_OUTCOMES.get((route_outcome or "").strip())


async def compute_filtered_counts(
    db: AsyncSession,
    tenant_id: str,
    *,
    window: str = "today",
    visible_property_codes: Optional[list[str]] = None,
) -> dict:
    """
    Aggregate message_normalizations by filtered reason bucket for the given
    window. Returns {"total": int, "counts": {reason: int}, "window": window}.

    visible_property_codes: if provided, only rows whose selected_property_code
    is in the list (or empty/NULL) are counted — matches the scope logic in
    list_filtered.
    """
    interval = _WINDOW_INTERVALS.get(window, "1 day")
    outcomes = list(FILTERED_ROUTE_OUTCOMES.keys())

    started = _time.perf_counter()
    try:
        rows = (await db.execute(
            text(
                """
                SELECT
                    route_outcome,
                    selected_property_code
                FROM message_normalizations
                WHERE tenant_id = CAST(:tid AS uuid)
                  AND route_outcome = ANY(:outcomes)
                  AND COALESCE(sent_at, updated_at) > NOW() - CAST(:interval AS interval)
                LIMIT 2000
                """
            ),
            {"tid": tenant_id, "outcomes": outcomes, "interval": interval},
        )).mappings().all()
    except Exception:
        logger.exception(
            "[FilteredRecoveryService] compute_filtered_counts failed tenant=%s", tenant_id
        )
        try:
            await db.rollback()
        except Exception:
            pass
        return {"total": 0, "counts": {}, "window": window}

    counts: dict[str, int] = {}
    for r in rows:
        if visible_property_codes is not None:
            code = str(r["selected_property_code"] or "").strip()
            if code and code not in visible_property_codes:
                continue
        row_reason = filtered_reason_for(r["route_outcome"]) or "system"
        counts[row_reason] = counts.get(row_reason, 0) + 1

    total = sum(counts.values())
    logger.debug(
        "[FilteredRecoveryService] tenant=%s window=%s total=%s elapsed_ms=%.1f",
        tenant_id, window, total, (_time.perf_counter() - started) * 1000,
    )
    return {"total": total, "counts": counts, "window": window}
