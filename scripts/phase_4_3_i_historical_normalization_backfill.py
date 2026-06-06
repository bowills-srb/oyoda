"""Phase 4.3-I: backfill missing normalization rows for active inquiries."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from sqlalchemy import text

from app.db.session import SessionLocal
from app.services.messaging.inbound_normalizer import CanonicalInboundMessage
from app.services.messaging.message_event_store import (
    persist_canonical_inbound_message,
    update_normalization_outcome,
)


TENANT_ID = UUID("e07980b2-a990-4b24-91d1-c8cb71ab70e1")


def _build_canonical_from_row(row) -> CanonicalInboundMessage:
    property_candidates = []
    property_code = str(row["property_external_id"] or "").strip()
    if property_code:
        property_candidates.append(
            {
                "candidate_type": "property_code",
                "value": property_code,
                "confidence": 1.0,
                "source": "historical_pre_booking_backfill",
            }
        )

    received_at = row["received_at"] or datetime.now(timezone.utc)
    return CanonicalInboundMessage(
        source_channel="email",
        source_provider=str(row["platform"] or "email"),
        source_thread_id=str(row["thread_id"] or ""),
        source_message_id=str(row["message_id"] or ""),
        sender_role="guest",
        sender_display_name=str(row["guest_name"] or "Guest"),
        sender_address="",
        sent_at=received_at,
        raw_subject="",
        latest_guest_turn=str(row["message_text"] or ""),
        prior_thread_context="",
        full_message_text=str(row["message_text"] or ""),
        structured_asks=[],
        prior_operator_commitments=[],
        property_binding_candidates=property_candidates,
        channel_constraints={},
        parser_used="phase_4_3_i_backfill",
        parser_version="v1",
        parser_notes=[],
        latest_turn_confidence=float(row["confidence"] or 0.0),
        latest_turn_extracted=bool(row["message_text"]),
        guest_name=str(row["guest_name"] or "Guest"),
        guest_email="",
    )


async def _run(dry_run: bool) -> dict:
    report = {
        "tenant_id": str(TENANT_ID),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": dry_run,
        "candidates": 0,
        "backfilled": 0,
        "skipped": 0,
        "errors": [],
    }
    async with SessionLocal() as db:
        rows = (
            await db.execute(
                text(
                    """
                    SELECT
                        pbi.draft_id,
                        pbi.thread_id,
                        pbi.message_id,
                        pbi.platform,
                        pbi.guest_name,
                        pbi.message_text,
                        pbi.property_external_id,
                        pbi.intent,
                        pbi.confidence,
                        pbi.received_at
                    FROM pre_booking_inquiries pbi
                    LEFT JOIN message_normalizations mn
                      ON mn.tenant_id = pbi.company_id
                     AND mn.source_channel = 'email'
                     AND mn.source_message_id = pbi.message_id
                    WHERE pbi.company_id = CAST(:tid AS uuid)
                      AND pbi.archived_at IS NULL
                      AND pbi.message_id <> ''
                      AND mn.source_message_id IS NULL
                    ORDER BY pbi.received_at ASC
                    """
                ),
                {"tid": str(TENANT_ID)},
            )
        ).mappings().all()
        report["candidates"] = len(rows)
        for row in rows:
            if dry_run:
                report["backfilled"] += 1
                continue
            try:
                inbound = _build_canonical_from_row(row)
                result = await persist_canonical_inbound_message(db, TENANT_ID, inbound)
                if not result.get("normalization_id"):
                    raise RuntimeError("persist_canonical_inbound_message did not create a normalization row")
                await update_normalization_outcome(
                    db,
                    TENANT_ID,
                    "email",
                    str(row["message_id"] or ""),
                    selected_property_code=str(row["property_external_id"] or ""),
                    route_outcome="historical_unprocessed",
                    draft_source="phase_4_3_i_backfill",
                    fallback_reason="retrospective_normalization_no_draft_generation",
                )
                report["backfilled"] += 1
            except Exception as exc:  # noqa: BLE001
                report["errors"].append(
                    {
                        "draft_id": str(row["draft_id"] or ""),
                        "message_id": str(row["message_id"] or ""),
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
    path = report_dir / f"phase_4_3_i_backfill_report_{suffix}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}.json"
    path.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    print(f"wrote_report={path}")


if __name__ == "__main__":
    main()
