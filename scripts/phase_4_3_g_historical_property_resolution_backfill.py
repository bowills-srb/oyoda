"""Phase 4.3-G: Historical property-resolution writeback for pre-booking inquiries.

Usage:
    python scripts/phase_4_3_g_historical_property_resolution_backfill.py [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from sqlalchemy import text

from app.db.session import SessionLocal
from app.services.messaging_brain.property_resolution_writeback import (
    TRUSTED_MATCH_TYPES,
    get_property_resolution_writeback,
)

TENANT_ID = UUID("e07980b2-a990-4b24-91d1-c8cb71ab70e1")


async def _run(dry_run: bool) -> dict:
    report = {
        "tenant_id": str(TENANT_ID),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": dry_run,
        "trusted_match_types": sorted(TRUSTED_MATCH_TYPES),
        "candidates": 0,
        "updated": 0,
        "skipped": 0,
        "errors": [],
    }
    writeback = get_property_resolution_writeback()
    async with SessionLocal() as db:
        rows = (
            await db.execute(
                text(
                    """
                    SELECT
                        pbi.draft_id,
                        pbi.property_external_id,
                        mn.selected_property_code,
                        mn.selected_property_match_type
                    FROM pre_booking_inquiries pbi
                    LEFT JOIN message_normalizations mn
                      ON mn.tenant_id = pbi.company_id
                     AND mn.source_channel = 'gmail'
                     AND mn.source_message_id = pbi.gmail_message_id
                    WHERE pbi.company_id = CAST(:tid AS uuid)
                      AND (pbi.property_external_id IS NULL OR pbi.property_external_id = '')
                      AND COALESCE(mn.selected_property_code, '') <> ''
                      AND COALESCE(mn.selected_property_match_type, '') IN (
                          'canonical_ref', 'pms_exact', 'address_exact', 'community_unique'
                      )
                    ORDER BY pbi.received_at DESC
                    """
                ),
                {"tid": str(TENANT_ID)},
            )
        ).mappings().all()
        report["candidates"] = len(rows)
        for row in rows:
            draft_id = str(row["draft_id"] or "").strip()
            selected_property_code = str(row["selected_property_code"] or "").strip()
            match_type = str(row["selected_property_match_type"] or "").strip()
            if not draft_id or not selected_property_code:
                report["skipped"] += 1
                continue
            if dry_run:
                report["updated"] += 1
                continue
            ok = await writeback.writeback_for_inquiry(
                db,
                tenant_id=TENANT_ID,
                draft_id=draft_id,
                resolved_property_code=selected_property_code,
                match_type=match_type,
            )
            if ok:
                report["updated"] += 1
            else:
                report["skipped"] += 1
    report["completed_at"] = datetime.now(timezone.utc).isoformat()
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    report = asyncio.run(_run(args.dry_run))
    report_dir = Path("tmp")
    report_dir.mkdir(exist_ok=True)
    suffix = "dry_run" if args.dry_run else "live"
    path = report_dir / f"phase_4_3_g_backfill_report_{suffix}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}.json"
    path.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    print(f"wrote_report={path}")


if __name__ == "__main__":
    main()
