"""gap_backfill — one-time historical cleanup for pre-fix NULL property_id gaps.

Run once after gap_recorder.record_gap has been updated to resolve
property_id at write time (the forward fix). This script handles the
historical rows that were recorded before the fix landed.

TWO operations, both read-only safe until explicitly executed:

  1. BACKFILL (--backfill):  Rows with property_external_id but NULL property_id.
     Resolve external_id → property_id via the properties table and UPDATE those
     rows.  Recoverable, semantics-preserving.  Estimated ~100 rows for the live
     tenant.

  2. QUARANTINE (--quarantine): Rows with BOTH property_id = NULL AND
     property_external_id NULL/empty.  Permanently unattributable — neither field
     gives us anything to resolve against.  Flag them in metadata as
     attribution_status="unattributable" and mark resolved=True with
     resolved_reason="unattributable" so they fall out of scoring inputs without
     being deleted.  Do NOT purge — they are real records.
     Estimated ~473 rows for the live tenant.

Usage (from repo root, with DB env vars set):

    python -m app.services.messaging_brain.knowledge.gap_backfill \\
        --tenant e07980b2-a990-4b24-91d1-c8cb71ab70e1 \\
        --dry-run     ← always run dry first; prints counts without writing

    python -m app.services.messaging_brain.knowledge.gap_backfill \\
        --tenant e07980b2-a990-4b24-91d1-c8cb71ab70e1 \\
        --backfill --quarantine

Verification after running:
    SELECT attribution_status, COUNT(*)
    FROM (
        SELECT metadata->>'attribution_status' AS attribution_status
        FROM concierge_knowledge_gaps
        WHERE tenant_id = '<tid>'
    ) sub GROUP BY 1;
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from typing import Any, Dict, List
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.messaging_brain.knowledge.gap_recorder import (
    resolve_property_id_from_external,
)

logger = logging.getLogger(__name__)


async def _fetch_backfillable(
    session: AsyncSession,
    tenant_id: UUID,
) -> List[Dict[str, Any]]:
    """Rows with property_external_id but no property_id."""
    rows = (
        await session.execute(
            text(
                """
                SELECT gap_id::text, property_external_id
                FROM concierge_knowledge_gaps
                WHERE tenant_id = :tid
                  AND property_id IS NULL
                  AND property_external_id IS NOT NULL
                  AND property_external_id <> ''
                  AND (metadata->>'attribution_status') IS DISTINCT FROM 'unattributable'
                """
            ),
            {"tid": str(tenant_id)},
        )
    ).mappings().all()
    return [dict(r) for r in rows]


async def _fetch_unattributable(
    session: AsyncSession,
    tenant_id: UUID,
) -> List[str]:
    """Rows with neither property_id nor property_external_id — permanently unattributable."""
    rows = (
        await session.execute(
            text(
                """
                SELECT gap_id::text
                FROM concierge_knowledge_gaps
                WHERE tenant_id = :tid
                  AND property_id IS NULL
                  AND (property_external_id IS NULL OR property_external_id = '')
                  AND (metadata->>'attribution_status') IS DISTINCT FROM 'unattributable'
                """
            ),
            {"tid": str(tenant_id)},
        )
    ).mappings().all()
    return [r["gap_id"] for r in rows]


async def run_backfill(
    session: AsyncSession,
    tenant_id: UUID,
    dry_run: bool,
) -> Dict[str, int]:
    rows = await _fetch_backfillable(session, tenant_id)
    resolved = 0
    missed = 0

    for row in rows:
        gap_id = row["gap_id"]
        ext_id = row["property_external_id"]
        property_id_str = await resolve_property_id_from_external(
            session=session,
            tenant_id=tenant_id,
            property_external_id=ext_id,
        )
        if not property_id_str:
            missed += 1
            logger.debug("[gap_backfill] backfill miss: ext_id=%r no match", ext_id)
            continue
        if not dry_run:
            await session.execute(
                text(
                    """
                    UPDATE concierge_knowledge_gaps
                    SET property_id = CAST(:pid AS uuid),
                        metadata = jsonb_set(
                            COALESCE(metadata, '{}'),
                            '{attribution_status}',
                            '"backfilled"'
                        )
                    WHERE gap_id = CAST(:gid AS uuid)
                    """
                ),
                {"pid": property_id_str, "gid": gap_id},
            )
        resolved += 1

    if not dry_run:
        await session.commit()

    return {"backfillable": len(rows), "resolved": resolved, "missed": missed}


async def run_quarantine(
    session: AsyncSession,
    tenant_id: UUID,
    dry_run: bool,
) -> Dict[str, int]:
    gap_ids = await _fetch_unattributable(session, tenant_id)

    if not dry_run and gap_ids:
        # Process in batches to avoid giant IN clauses
        batch_size = 200
        for i in range(0, len(gap_ids), batch_size):
            batch = gap_ids[i : i + batch_size]
            placeholders = ", ".join(f":id_{j}" for j in range(len(batch)))
            params = {f"id_{j}": bid for j, bid in enumerate(batch)}
            await session.execute(
                text(
                    f"""
                    UPDATE concierge_knowledge_gaps
                    SET metadata = jsonb_set(
                            COALESCE(metadata, '{{}}'),
                            '{{attribution_status}}',
                            '"unattributable"'
                        ),
                        resolved = TRUE
                    WHERE gap_id IN ({placeholders})
                    """  # noqa: S608
                ),
                params,
            )
        await session.commit()

    return {"quarantined": len(gap_ids)}


async def main(
    tenant_id_str: str,
    do_backfill: bool,
    do_quarantine: bool,
    dry_run: bool,
) -> None:
    from app.core.database import get_db_session

    tenant_id = UUID(tenant_id_str)
    prefix = "[DRY RUN] " if dry_run else ""

    async with get_db_session() as session:
        if do_backfill:
            result = await run_backfill(session, tenant_id, dry_run)
            print(
                f"{prefix}BACKFILL: found {result['backfillable']} rows with external_id, "
                f"resolved {result['resolved']}, missed {result['missed']}"
            )

        if do_quarantine:
            result = await run_quarantine(session, tenant_id, dry_run)
            print(
                f"{prefix}QUARANTINE: flagged {result['quarantined']} unattributable rows "
                f"(resolved=True, attribution_status='unattributable') — NOT deleted"
            )

    if not do_backfill and not do_quarantine:
        print("Nothing to do — pass --backfill and/or --quarantine")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    parser = argparse.ArgumentParser(description="Gap property-attribution backfill + quarantine")
    parser.add_argument("--tenant", required=True, help="tenant_id UUID")
    parser.add_argument("--backfill", action="store_true")
    parser.add_argument("--quarantine", action="store_true")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Print counts without writing (default: True — must pass --no-dry-run to write)",
    )
    parser.add_argument("--no-dry-run", dest="dry_run", action="store_false")
    parser.set_defaults(dry_run=True)
    args = parser.parse_args()

    asyncio.run(
        main(
            tenant_id_str=args.tenant,
            do_backfill=args.backfill,
            do_quarantine=args.quarantine,
            dry_run=args.dry_run,
        )
    )
