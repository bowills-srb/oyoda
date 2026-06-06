from __future__ import annotations

import argparse
import asyncio
import logging
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from app.db.session import SessionLocal
from app.db.session_safety import safe_rollback
from app.services.agents.healer_agent import get_healer_agent


logger = logging.getLogger(__name__)


async def _list_recently_active_tenants(db, window_hours: int) -> list[UUID]:
    try:
        rows = (
            await db.execute(
                text(
                    """
                    SELECT DISTINCT tenant_id
                    FROM message_normalizations
                    WHERE created_at >= NOW() - make_interval(hours => :window_hours)
                    ORDER BY tenant_id
                    """
                ),
                {"window_hours": int(window_hours)},
            )
        ).fetchall()
        return [row[0] for row in rows if row and row[0] is not None]
    except (DBAPIError, ProgrammingError) as exc:
        await safe_rollback(db)
        logger.warning("[HealerRunner] tenant discovery failed: %s", exc, exc_info=True)
        return []


async def scan_all_tenants(*, window_hours: int = 24) -> dict[UUID, int]:
    counts: dict[UUID, int] = {}
    agent = get_healer_agent()
    async with SessionLocal() as db:
        tenant_ids = await _list_recently_active_tenants(db, window_hours)
        for tenant_id in tenant_ids:
            try:
                proposals = await agent.scan_for_proposals(db, tenant_id, window_hours=window_hours)
                await agent.save_proposals(db, tenant_id, proposals)
                counts[tenant_id] = len(proposals)
            except (DBAPIError, ProgrammingError) as exc:
                await safe_rollback(db)
                logger.warning("[HealerRunner] scan failed tenant_id=%s err=%s", tenant_id, exc, exc_info=True)
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Scan healer proposals across active tenants.")
    parser.add_argument("--window-hours", type=int, default=24)
    args = parser.parse_args()
    results = asyncio.run(scan_all_tenants(window_hours=args.window_hours))
    for tenant_id, count in results.items():
        print(f"{tenant_id}\t{count}")


if __name__ == "__main__":
    main()
