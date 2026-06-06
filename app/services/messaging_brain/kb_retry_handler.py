from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import text

from app.services.feature_flags import is_ship_i_kb_retry_primary_enabled
from app.services.messaging_brain.pre_booking_retry import (
    reevaluate_existing_prebooking_inquiry,
)

logger = logging.getLogger(__name__)


def _normalize_topic(value: str | None) -> str:
    return str(value or "").strip().lower()


async def find_held_inquiries_blocked_by_topic(
    *,
    db,
    tenant_id: str,
    topic: str,
    limit: int = 50,
) -> List[str]:
    normalized = _normalize_topic(topic)
    if not normalized:
        return []
    rows = (
        await db.execute(
            text(
                """
                SELECT draft_id
                FROM pre_booking_inquiries
                WHERE company_id = CAST(:tid AS uuid)
                  AND archived_at IS NULL
                  AND status = 'pending_review'
                  AND (
                    :topic = ANY(COALESCE(blocked_by_gap_topics, ARRAY[]::text[]))
                    OR CAST(policy_warnings AS text) ILIKE :warning_like
                  )
                ORDER BY received_at DESC
                LIMIT :limit
                """
            ),
            {
                "tid": tenant_id,
                "topic": normalized,
                "warning_like": f"%missing_property_knowledge:%{normalized}%",
                "limit": max(1, min(int(limit or 50), 200)),
            },
        )
    ).fetchall()
    return [str(row[0]) for row in rows if row and row[0]]


async def _run_retry_task(
    *,
    db_factory,
    tenant_id: str,
    operator_id: str,
    draft_id: str,
) -> None:
    try:
        async with db_factory() as db:
            await reevaluate_existing_prebooking_inquiry(
                db=db,
                tenant_id=tenant_id,
                operator_id=operator_id,
                draft_id=draft_id,
                auto_send_if_allowed=True,
            )
    except Exception as exc:
        logger.exception("[ShipI] KB retry failed for draft_id=%s: %s", draft_id, exc)


async def kb_post_save_retry_held_inquiries(
    *,
    db,
    db_factory,
    tenant_id: str,
    operator_id: str,
    topic: Optional[str],
) -> Dict[str, Any]:
    if not await is_ship_i_kb_retry_primary_enabled(db=db, tenant_id=tenant_id):
        return {"triggered_regenerations": [], "triggered_regeneration_count": 0}

    normalized = _normalize_topic(topic)
    if not normalized:
        return {"triggered_regenerations": [], "triggered_regeneration_count": 0}

    draft_ids = await find_held_inquiries_blocked_by_topic(
        db=db,
        tenant_id=tenant_id,
        topic=normalized,
    )
    scheduled_at = datetime.now(timezone.utc).isoformat()
    triggered = [
        {"inquiry_id": draft_id, "topic": normalized, "scheduled_at": scheduled_at}
        for draft_id in draft_ids
    ]
    for draft_id in draft_ids:
        asyncio.create_task(
            _run_retry_task(
                db_factory=db_factory,
                tenant_id=tenant_id,
                operator_id=operator_id,
                draft_id=draft_id,
            )
        )
    return {
        "triggered_regenerations": triggered,
        "triggered_regeneration_count": len(triggered),
    }
