"""Phase 4.3-H: migrate mis-routed post-booking inquiries into guest sessions.

Usage:
    python scripts/phase_4_3_h_route_post_booking_to_sessions.py [--dry-run]
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
from app.services.concierge.post_booking_routing import persist_inbound_from_inquiry


TENANT_ID = UUID("e07980b2-a990-4b24-91d1-c8cb71ab70e1")
TARGET_INTENTS = ("general", "general_inquiry")


async def _run(dry_run: bool) -> dict:
    report = {
        "tenant_id": str(TENANT_ID),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": dry_run,
        "target_intents": list(TARGET_INTENTS),
        "candidates": 0,
        "migrated": 0,
        "skipped": 0,
        "errors": [],
    }
    async with SessionLocal() as db:
        rows = (
            await db.execute(
                text(
                    """
                    SELECT
                        draft_id,
                        CAST(guest_thread_id AS text) AS guest_thread_id,
                        gmail_message_id,
                        gmail_thread_id,
                        guest_name,
                        guest_email,
                        message_text,
                        intent,
                        property_external_id,
                        requested_check_in,
                        requested_check_out,
                        requested_guests,
                        received_at
                    FROM pre_booking_inquiries
                    WHERE company_id = CAST(:tid AS uuid)
                      AND archived_at IS NULL
                      AND intent = ANY(:intents)
                    ORDER BY received_at ASC
                    """
                ),
                {"tid": str(TENANT_ID), "intents": list(TARGET_INTENTS)},
            )
        ).mappings().all()
        report["candidates"] = len(rows)
        for row in rows:
            if dry_run:
                report["migrated"] += 1
                continue
            try:
                await persist_inbound_from_inquiry(
                    db,
                    tenant_id=TENANT_ID,
                    property_code=str(row["property_external_id"] or "").strip(),
                    property_name=str(row["property_external_id"] or "Unknown property").strip(),
                    guest_name=str(row["guest_name"] or "Guest").strip(),
                    guest_email=str(row["guest_email"] or "").strip() or None,
                    message_text=str(row["message_text"] or "").strip(),
                    intent=str(row["intent"] or "general_inquiry").strip(),
                    received_at=row["received_at"],
                    requested_check_in=row["requested_check_in"],
                    requested_check_out=row["requested_check_out"],
                    requested_guests=row["requested_guests"],
                    source_message_id=str(row["gmail_message_id"] or "").strip(),
                    inquiry_thread_id=str(row["gmail_thread_id"] or "").strip(),
                    existing_guest_thread_id=str(row["guest_thread_id"] or "").strip() or None,
                    source_label="phase_4_3_h_historical_migration",
                    draft_id=str(row["draft_id"] or "").strip(),
                    archive_reason="post_booking_misroute",
                )
                await db.execute(
                    text(
                        """
                        UPDATE pre_booking_inquiries
                        SET archived_at = NOW(),
                            archive_reason = 'post_booking_misroute'
                        WHERE company_id = CAST(:tid AS uuid)
                          AND draft_id = :draft_id
                          AND archived_at IS NULL
                        """
                    ),
                    {
                        "tid": str(TENANT_ID),
                        "draft_id": str(row["draft_id"] or "").strip(),
                    },
                )
                await db.commit()
                report["migrated"] += 1
            except Exception as exc:
                await db.rollback()
                report["errors"].append(
                    {
                        "draft_id": str(row["draft_id"] or ""),
                        "error": str(exc),
                    }
                )
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
    path = report_dir / f"phase_4_3_h_migration_report_{suffix}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}.json"
    path.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    print(f"wrote_report={path}")


if __name__ == "__main__":
    main()
