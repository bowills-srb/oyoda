#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="${ROUNDTRIP_PG_IMAGE:-pgvector/pgvector:pg15}"
CONTAINER_NAME="${ROUNDTRIP_PG_CONTAINER:-oyvoda-migration-roundtrip}"
PORT="${ROUNDTRIP_PG_PORT:-55432}"
DB_NAME="${ROUNDTRIP_PG_DB:-oyvoda_phase2}"
DB_USER="${ROUNDTRIP_PG_USER:-postgres}"
DB_PASSWORD="${ROUNDTRIP_PG_PASSWORD:-postgres}"
SNAPSHOT_PATH="${ROUNDTRIP_PROD_SNAPSHOT:-/tmp/part1_schema_audit.json}"
FRESH_SCHEMA_PATH="${ROUNDTRIP_FRESH_SCHEMA_OUT:-/tmp/phase2_roundtrip_fresh_schema.json}"
COMPARE_PATH="${ROUNDTRIP_COMPARE_OUT:-/tmp/phase2_roundtrip_compare.json}"
ALEMBIC_LOG="${ROUNDTRIP_ALEMBIC_LOG:-/tmp/phase2_alembic_upgrade.log}"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required for the migration round-trip harness" >&2
  exit 1
fi

if ! docker ps >/dev/null 2>&1; then
  echo "docker daemon is not available; start Docker and rerun ${BASH_SOURCE[0]}" >&2
  exit 1
fi

cleanup() {
  docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true

docker run -d \
  --name "$CONTAINER_NAME" \
  -e POSTGRES_USER="$DB_USER" \
  -e POSTGRES_PASSWORD="$DB_PASSWORD" \
  -e POSTGRES_DB="$DB_NAME" \
  -p "127.0.0.1:${PORT}:5432" \
  "$IMAGE" >/dev/null

for _ in $(seq 1 60); do
  if docker exec "$CONTAINER_NAME" pg_isready -U "$DB_USER" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if ! docker exec "$CONTAINER_NAME" pg_isready -U "$DB_USER" >/dev/null 2>&1; then
  echo "postgres container did not become ready" >&2
  docker logs "$CONTAINER_NAME" >&2 || true
  exit 1
fi

# Production has several extensions enabled. The current migration tree
# actually relies on these three:
# - pgcrypto: gen_random_uuid()
# - uuid-ossp: historical UUID usage
# - vector: pgvector-backed embedding storage
# supabase_vault is enabled in production but is not required by migrations.
for ext in pgcrypto "\"uuid-ossp\"" vector; do
  docker exec "$CONTAINER_NAME" psql -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 -c "CREATE EXTENSION IF NOT EXISTS ${ext};" >/dev/null
done

export ALEMBIC_DATABASE_URL="postgresql://${DB_USER}:${DB_PASSWORD}@127.0.0.1:${PORT}/${DB_NAME}?sslmode=disable"

cd "$ROOT_DIR"
.venv/bin/alembic -c alembic.ini upgrade head >"$ALEMBIC_LOG" 2>&1

python3 - "$ALEMBIC_DATABASE_URL" "$SNAPSHOT_PATH" "$FRESH_SCHEMA_PATH" "$COMPARE_PATH" <<'PY'
import json
import sys
from pathlib import Path

import psycopg2


def load_snapshot(path_str: str):
    path = Path(path_str)
    if not path.exists():
        return None
    obj = json.loads(path.read_text())
    return obj["tables"]


def collect_schema(conn):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema='public' AND table_type='BASE TABLE'
        ORDER BY table_name
        """
    )
    tables = [r[0] for r in cur.fetchall()]
    out = {}
    for table in tables:
        cur.execute(
            """
            SELECT ordinal_position, column_name, data_type, udt_name, is_nullable,
                   COALESCE(column_default, '')
            FROM information_schema.columns
            WHERE table_schema='public' AND table_name=%s
            ORDER BY ordinal_position
            """,
            (table,),
        )
        columns = [
            {
                "ordinal_position": r[0],
                "column_name": r[1],
                "data_type": r[2],
                "udt_name": r[3],
                "is_nullable": r[4],
                "column_default": r[5],
            }
            for r in cur.fetchall()
        ]
        cur.execute(
            """
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE schemaname='public' AND tablename=%s
            ORDER BY indexname
            """,
            (table,),
        )
        indexes = [{"indexname": r[0], "indexdef": r[1]} for r in cur.fetchall()]
        cur.execute(
            """
            SELECT tc.constraint_name, tc.constraint_type,
                   COALESCE(string_agg(kcu.column_name, ',' ORDER BY kcu.ordinal_position), '') AS columns
            FROM information_schema.table_constraints tc
            LEFT JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema = kcu.table_schema
             AND tc.table_name = kcu.table_name
            WHERE tc.table_schema='public' AND tc.table_name=%s
            GROUP BY tc.constraint_name, tc.constraint_type
            ORDER BY tc.constraint_name
            """,
            (table,),
        )
        constraints = [
            {
                "constraint_name": r[0],
                "constraint_type": r[1],
                "columns": r[2],
            }
            for r in cur.fetchall()
        ]
        out[table] = {
            "columns": columns,
            "indexes": indexes,
            "constraints": constraints,
        }
    return {"tables": out}


def compare(prod_tables, fresh_tables):
    prod_names = set(prod_tables)
    fresh_names = set(fresh_tables)
    shared = sorted(prod_names & fresh_names)
    report = {
        "only_in_production_snapshot": sorted(prod_names - fresh_names),
        "only_in_fresh_db": sorted(fresh_names - prod_names),
        "tables_with_differences": {},
    }
    for table in shared:
        p = prod_tables[table]
        f = fresh_tables[table]
        pcols = {c["column_name"]: (c["data_type"], c["udt_name"], c["is_nullable"]) for c in p["columns"]}
        fcols = {c["column_name"]: (c["data_type"], c["udt_name"], c["is_nullable"]) for c in f["columns"]}
        pidx = {i["indexname"] for i in p["indexes"]}
        fidx = {i["indexname"] for i in f["indexes"]}
        pcons = {(c["constraint_name"], c["constraint_type"], c["columns"]) for c in p["constraints"]}
        fcons = {(c["constraint_name"], c["constraint_type"], c["columns"]) for c in f["constraints"]}
        diff = {}
        if set(pcols) != set(fcols):
            diff["column_name_only_in_prod"] = sorted(set(pcols) - set(fcols))
            diff["column_name_only_in_fresh"] = sorted(set(fcols) - set(pcols))
        type_diffs = {}
        for col in sorted(set(pcols) & set(fcols)):
            if pcols[col] != fcols[col]:
                type_diffs[col] = {"prod": pcols[col], "fresh": fcols[col]}
        if type_diffs:
            diff["column_shape_differences"] = type_diffs
        if pidx != fidx:
            diff["index_only_in_prod"] = sorted(pidx - fidx)
            diff["index_only_in_fresh"] = sorted(fidx - pidx)
        if pcons != fcons:
            diff["constraint_only_in_prod_count"] = len(pcons - fcons)
            diff["constraint_only_in_fresh_count"] = len(fcons - pcons)
        if diff:
            report["tables_with_differences"][table] = diff
    return report


database_url, snapshot_path, fresh_out, compare_out = sys.argv[1:5]
conn = psycopg2.connect(database_url)
fresh = collect_schema(conn)
Path(fresh_out).write_text(json.dumps(fresh, indent=2, sort_keys=True))

prod = load_snapshot(snapshot_path)
if prod is None:
    print(f"fresh schema written to {fresh_out}")
    sys.exit(0)

report = compare(prod, fresh["tables"])
Path(compare_out).write_text(json.dumps(report, indent=2, sort_keys=True))
print("fresh_tables", len(fresh["tables"]))
print("prod_tables", len(prod))
print("only_in_prod", len(report["only_in_production_snapshot"]))
print("only_in_fresh", len(report["only_in_fresh_db"]))
print("tables_with_differences", len(report["tables_with_differences"]))
for table in list(sorted(report["tables_with_differences"]))[:20]:
    print("DIFF", table, ",".join(report["tables_with_differences"][table].keys()))
print(f"fresh schema written to {fresh_out}")
print(f"comparison written to {compare_out}")
PY
