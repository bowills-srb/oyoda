#!/usr/bin/env python3
"""
Migration 018 runner — complete standalone version.

Bypasses Alembic entirely. Runs all required SQL directly via asyncpg.
Safe to re-run (uses IF NOT EXISTS / ADD COLUMN IF NOT EXISTS throughout).

Usage:
    cd ~/Downloads/STR-Beach_Habitats
    python3 scripts/run_migration_018.py
"""
import asyncio, pathlib, sys, os, subprocess, venv, time

PROJECT_ROOT = pathlib.Path(__file__).parent.parent
DB_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://rental:rental@localhost:5433/rental_revenue"  # 5433 = Docker db port
).replace("postgresql+asyncpg://", "postgresql://").replace("+asyncpg", "")

VENV_DIR = PROJECT_ROOT / ".migration_venv"

# ── Step 0: ensure venv with asyncpg ─────────────────────────────────────────
venv_python = VENV_DIR / "bin" / "python3"
if str(sys.executable) != str(venv_python):
    if not venv_python.exists():
        print("Creating local venv...")
        venv.create(str(VENV_DIR), with_pip=True)
        print("Installing asyncpg...")
        subprocess.check_call(
            [str(venv_python), "-m", "pip", "install", "asyncpg", "-q"],
            stdout=subprocess.DEVNULL,
        )
        print("✅ asyncpg installed\n")
    os.execv(str(venv_python), [str(venv_python)] + sys.argv)

import asyncpg  # noqa: E402

# =============================================================================
# SQL BLOCKS — run in order, each is idempotent
# =============================================================================

# Core prerequisite tables (subsets of what Alembic migrations 001-013 create).
# Only the tables that migration_018 depends on via FK or ALTER.
PREREQS = [

# ── Extension & UUID support ──────────────────────────────────────────────────
"""
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
""",



# ── knowledge_embeddings (required by startup checks) ───────────────────────────
# Minimal schema — no indexes that reference columns that may not exist
# in whatever version the Alembic migrations created
"""
CREATE TABLE IF NOT EXISTS knowledge_embeddings (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    content     TEXT NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
""",

# ── concierge_escalations (required by startup checks) ──────────────────────
"""
CREATE TABLE IF NOT EXISTS concierge_escalations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_token   TEXT,
    property_code   TEXT NOT NULL DEFAULT '',
    reason          TEXT NOT NULL DEFAULT 'unknown',
    priority        TEXT NOT NULL DEFAULT 'medium',
    status          TEXT NOT NULL DEFAULT 'open',
    summary         TEXT,
    guest_name      TEXT,
    property_name   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
""",

# ── concierge_guest_sessions (needed for column additions in 018) ─────────────
"""
CREATE TABLE IF NOT EXISTS concierge_guest_sessions (
    session_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL,
    token               TEXT UNIQUE NOT NULL,
    property_id         UUID,   -- FK to properties.id (no constraint here to avoid dependency issues)
    property_code       TEXT NOT NULL,
    property_name       TEXT NOT NULL,
    guest_name          TEXT NOT NULL,
    guest_phone         TEXT,
    guest_email         TEXT,
    num_guests          INTEGER DEFAULT 1,
    check_in            DATE NOT NULL,
    check_out           DATE NOT NULL,
    status              TEXT NOT NULL DEFAULT 'active',
    phase               TEXT NOT NULL DEFAULT 'pre_arrival',
    conversation_count  INTEGER DEFAULT 0,
    last_message_at     TIMESTAMPTZ,
    pms_synced_at       TIMESTAMPTZ,
    property_context    JSONB NOT NULL DEFAULT '{}',
    operator_id         TEXT,
    reservation_id      TEXT,
    feedback_rating     INTEGER,
    feedback_text       TEXT,
    feedback_at         TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_concierge_session_tenant_status
    ON concierge_guest_sessions (tenant_id, status);
CREATE INDEX IF NOT EXISTS ix_concierge_session_tenant_property
    ON concierge_guest_sessions (tenant_id, property_code);
CREATE INDEX IF NOT EXISTS ix_concierge_session_checkin
    ON concierge_guest_sessions (check_in);
CREATE INDEX IF NOT EXISTS ix_concierge_session_checkout
    ON concierge_guest_sessions (check_out);
""",

]

# The 018 migration SQL (all 21 new tables)
SQL_018_PATH = PROJECT_ROOT / "scripts" / "migration_018.sql"

# Column additions to concierge_guest_sessions (done individually so each is idempotent)
SESSION_COLS = [
    ("property_external_id",     "TEXT"),
    ("booking_channel",          "TEXT DEFAULT 'direct'"),
    ("gate_code_last_requested", "TIMESTAMPTZ"),
    ("company_id",               "UUID"),
]

TABLES_018 = [
    "companies", "operator_feature_flags", "pms_listings", "pms_bookings",
    "operator_sync_log", "listing_id_aliases", "escapia_message_history",
    "message_orphan_queue", "pre_booking_inquiries", "operator_pre_booking_policies",
    "property_rollout_phases", "property_rollout_history", "operator_learned_preferences",
    "operator_draft_events", "platform_learning_events", "platform_intelligence",
    "gate_code_deliveries", "operator_alert_contacts", "operator_alert_acks",
    "operator_alert_log", "property_incidents",
]


def ensure_docker_db():
    print("Checking Docker db container...")
    r = subprocess.run(
        "docker compose ps db", shell=True, cwd=PROJECT_ROOT,
        capture_output=True, text=True,
    )
    if "running" not in r.stdout.lower() and "healthy" not in r.stdout.lower():
        print("  Starting db container...")
        subprocess.run("docker compose up -d db pgbouncer", shell=True, cwd=PROJECT_ROOT)
        print("  Waiting for postgres", end="", flush=True)
        for _ in range(30):
            time.sleep(1)
            r2 = subprocess.run(
                "docker compose exec -T db pg_isready -U rental -d rental_revenue",
                shell=True, cwd=PROJECT_ROOT, capture_output=True,
            )
            if r2.returncode == 0:
                print(" ✅")
                return
            print(".", end="", flush=True)
        print("\n❌ Postgres not ready"); sys.exit(1)
    else:
        print("  ✅ db container running")


async def main():
    print(f"\n{'='*60}")
    print(f"  Migration 018 — Pre-Booking Pipeline")
    print(f"  Target: {DB_URL.split('@')[-1]}")
    print(f"{'='*60}\n")

    # Only check Docker DB if targeting localhost
    if 'localhost' in DB_URL or '127.0.0.1' in DB_URL:
        ensure_docker_db()
    else:
        print("  Connecting to external database (Supabase)...")

    try:
        # asyncpg older versions can't resolve hostnames from DSN strings directly.
        # Parse the URL and pass components explicitly.
        import urllib.parse as _urlparse
        parsed = _urlparse.urlparse(DB_URL)
        host = parsed.hostname
        port = parsed.port or 5432
        user = parsed.username
        password = parsed.password
        database = parsed.path.lstrip('/')
        ssl_ctx = 'require' if 'supabase.co' in DB_URL else None
        conn = await asyncpg.connect(
            host=host, port=port,
            user=user, password=password,
            database=database, ssl=ssl_ctx,
        )
    except Exception as e:
        print(f"❌ Cannot connect: {e}")
        sys.exit(1)

    try:
        # ── Step 1: prereq tables ─────────────────────────────────────────────
        print("Step 1/4  Creating prerequisite tables (properties, sessions)...")
        for sql in PREREQS:
            await conn.execute(sql)
        print("  ✅ Prerequisite tables ready")

        # ── Step 2: 018 migration ─────────────────────────────────────────────
        print("Step 2/4  Running migration_018.sql (21 tables)...")
        sql_018 = SQL_018_PATH.read_text()
        await conn.execute(sql_018)
        print("  ✅ migration_018.sql complete")

        # ── Step 3: column additions ──────────────────────────────────────────
        print("Step 3/4  Adding columns to concierge_guest_sessions...")
        added = []
        for col, col_type in SESSION_COLS:
            exists = await conn.fetchval(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name='concierge_guest_sessions' AND column_name=$1", col
            )
            if not exists:
                await conn.execute(
                    f"ALTER TABLE concierge_guest_sessions ADD COLUMN {col} {col_type}"
                )
                added.append(col)
        if added:
            print(f"  ✅ Added: {added}")
        else:
            print(f"  ✅ All columns already present")

        # ── Step 4: verify ────────────────────────────────────────────────────
        print("Step 4/4  Verifying all 21 tables...")
        rows = await conn.fetch(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name=ANY($1::text[]) ORDER BY table_name",
            TABLES_018,
        )
        found = {r["table_name"] for r in rows}
        missing = [t for t in TABLES_018 if t not in found]

        for t in sorted(found):
            print(f"    ✓ {t}")
        if missing:
            print(f"\n  ⚠️  Missing: {missing}")

        print(f"\n{'='*60}")
        if not missing:
            print("  ✅ ALL 21 TABLES PRESENT — migration complete!")
            print()
            print("  Bring up the full stack:")
            print("    docker compose up -d")
            print()
            print("  First-operator setup:")
            print("    python3 scripts/pre_booking_setup.py \\")
            print("      --company-id '<uuid>' \\")
            print("      --api-key 'esc_live_...' \\")
            print("      --alert-phone '+1850...' \\")
            print("      --alert-email 'owner@example.com'")
        else:
            print(f"  ⚠️  {len(missing)} tables missing")
        print(f"{'='*60}\n")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback; traceback.print_exc()
        sys.exit(1)
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
