from __future__ import annotations

"""Capture production schema snapshots for offline schema-shape regression tests.

Usage:
    DATABASE_URL=postgresql+asyncpg://... PYTHONPATH=. .venv/bin/python \
        scripts/capture_production_schema_snapshot.py
"""

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.db_connect import is_pgbouncer_url, sqlalchemy_connect_args


COVERED_TABLES = (
    "operator_policies",
    "operator_settings",
    "message_normalizations",
    "canonical_property_link_reviews",
    "concierge_knowledge_gaps",
    "knowledge_gap_drafts",
    "pre_booking_inquiries",
    "pms_bookings",
    "healer_proposals",
)

SNAPSHOT_DIR = (
    Path(__file__).resolve().parent.parent
    / "tests"
    / "fixtures"
    / "production_schema_snapshots"
)


async def _alembic_version(engine) -> str:
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text("SELECT version_num FROM alembic_version ORDER BY version_num DESC LIMIT 1")
            )
        ).fetchone()
    return str(row[0]) if row else "unknown"


async def _capture_table(engine, table_name: str, *, alembic_version: str) -> dict[str, Any]:
    async with engine.connect() as conn:
        columns = (
            await conn.execute(
                text(
                    """
                    SELECT
                        column_name,
                        data_type,
                        udt_name,
                        (is_nullable = 'YES') AS is_nullable,
                        column_default
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = :table_name
                    ORDER BY ordinal_position
                    """
                ),
                {"table_name": table_name},
            )
        ).mappings().all()
        indexes = (
            await conn.execute(
                text(
                    """
                    SELECT
                        idx.relname AS indexname,
                        ix.indisunique AS is_unique,
                        COALESCE(
                            array_agg(att.attname ORDER BY key.ordinality)
                                FILTER (WHERE att.attname IS NOT NULL),
                            ARRAY[]::text[]
                        ) AS columns,
                        pg_get_indexdef(ix.indexrelid) AS indexdef
                    FROM pg_class tbl
                    JOIN pg_namespace ns
                      ON ns.oid = tbl.relnamespace
                    JOIN pg_index ix
                      ON tbl.oid = ix.indrelid
                    JOIN pg_class idx
                      ON idx.oid = ix.indexrelid
                    LEFT JOIN LATERAL unnest(ix.indkey) WITH ORDINALITY AS key(attnum, ordinality)
                      ON TRUE
                    LEFT JOIN pg_attribute att
                      ON att.attrelid = tbl.oid
                     AND att.attnum = key.attnum
                    WHERE ns.nspname = 'public'
                      AND tbl.relname = :table_name
                    GROUP BY idx.relname, ix.indisunique, ix.indexrelid
                    ORDER BY idx.relname
                    """
                ),
                {"table_name": table_name},
            )
        ).mappings().all()

    return {
        "table": table_name,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "alembic_version": alembic_version,
        "columns": [dict(row) for row in columns],
        "indexes": [dict(row) for row in indexes],
    }


async def main() -> None:
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL is required to capture schema snapshots.")

    engine_kwargs: dict[str, Any] = {
        "echo": False,
        "connect_args": sqlalchemy_connect_args(database_url),
    }
    if is_pgbouncer_url(database_url):
        engine_kwargs["poolclass"] = NullPool
    engine = create_async_engine(database_url, **engine_kwargs)
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

    try:
        version = await _alembic_version(engine)
        for table_name in COVERED_TABLES:
            snapshot = await _capture_table(engine, table_name, alembic_version=version)
            path = SNAPSHOT_DIR / f"{table_name}.json"
            path.write_text(json.dumps(snapshot, indent=2, sort_keys=True, default=str) + "\n")
            print(
                f"Captured {table_name}: {len(snapshot['columns'])} columns, "
                f"{len(snapshot['indexes'])} indexes"
            )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
