#!/usr/bin/env bash
# ============================================================================
# setup_local_db.sh — one-command local database bring-up (V1.0 prototype)
# ============================================================================
# Idempotent: safe to re-run. Brings a local PostgreSQL from empty to a fully
# migrated, seeded state for the operator queue + activity feed.
#
# Assumes a local PostgreSQL is running and that .env.local provides
# DATABASE_URL / ALEMBIC_DATABASE_URL (the committed defaults already do).
# ============================================================================
set -euo pipefail
cd "$(dirname "$0")/.."

# Load .env.local so ALEMBIC_DATABASE_URL / DATABASE_URL are available here too.
set -a
# shellcheck disable=SC1091
[ -f .env.local ] && . ./.env.local
set +a

ALEMBIC_URL="${ALEMBIC_DATABASE_URL:?Set ALEMBIC_DATABASE_URL (see .env.local)}"
DEFAULT_TENANT="00000000-0000-0000-0000-000000000001"

echo "==> 1/5 Ensuring role + database (needs a postgres superuser; skipped if present)"
if command -v runuser >/dev/null 2>&1; then SU="runuser -u postgres --"; else SU="sudo -u postgres"; fi
if ! $SU psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='oyvoda'" 2>/dev/null | grep -q 1; then
  $SU psql -c "CREATE ROLE oyvoda WITH LOGIN SUPERUSER PASSWORD 'oyvoda'" 2>/dev/null \
    || echo "   (could not auto-create role 'oyvoda'; create it manually if migrations fail)"
fi
if ! $SU psql -tAc "SELECT 1 FROM pg_database WHERE datname='oyvoda'" 2>/dev/null | grep -q 1; then
  $SU psql -c "CREATE DATABASE oyvoda OWNER oyvoda" 2>/dev/null \
    || echo "   (could not auto-create database 'oyvoda'; create it manually if migrations fail)"
fi

echo "==> 2/5 Ensuring pgvector extension"
psql "$ALEMBIC_URL" -v ON_ERROR_STOP=1 -c "CREATE EXTENSION IF NOT EXISTS vector;"

echo "==> 3/5 Applying migrations up to 071 (creates canonical knowledge_embeddings)"
alembic -c alembic.ini upgrade 071_phase_3_knowledge_embeddings_tenant_id

echo "==> 4/5 Satisfying production data-guards (072 ivfflat, 088 legacy drop), then upgrade head"
psql "$ALEMBIC_URL" -v ON_ERROR_STOP=1 <<SQL
-- 072 requires a non-empty knowledge_embeddings to build the ivfflat index.
INSERT INTO knowledge_embeddings (doc_id, operator_id, doc_type, content, tenant_id, embedding)
VALUES ('bootstrap_ivfflat_placeholder','op_bootstrap','bootstrap','ivfflat bootstrap',
        '${DEFAULT_TENANT}', ('[1' || repeat(',0',383) || ']')::vector)
ON CONFLICT DO NOTHING;
-- 088 refuses to drop legacy concierge_knowledge without an archive snapshot.
DO \$\$ BEGIN
  IF to_regclass('public.concierge_knowledge') IS NOT NULL
     AND to_regclass('public.concierge_knowledge_archive_2026_05_23') IS NULL THEN
    EXECUTE 'CREATE TABLE concierge_knowledge_archive_2026_05_23 (LIKE concierge_knowledge INCLUDING DEFAULTS)';
  END IF;
END \$\$;
SQL
alembic -c alembic.ini upgrade head
psql "$ALEMBIC_URL" -v ON_ERROR_STOP=1 -c "DELETE FROM knowledge_embeddings WHERE doc_id='bootstrap_ivfflat_placeholder';"

echo "==> 5/5 Seeding local mock data"
python3 scripts/seed_local_dev.py

echo ""
echo "✅ Local database ready. Start the app with:"
echo "     uvicorn app.main:app --reload"
