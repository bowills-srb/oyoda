# Phase 4.3-L.1 Codex Brief — `operator_policies` Reconciliation

Date: 2026-05-18  
Phase: 4.3-L.1  
Status: Ready for implementation  
Scope: `operator_policies` schema reconciliation, code-path migration to canonical `tenant_id`, and targeted exception-handling tightening on touched paths

## Context

Phase 4.3-L documented real production schema drift in `operator_policies`.

Confirmed production state from [SCHEMA_DRIFT_AUDIT.md](/Users/dhuntermckenzie/Downloads/oyvoda/docs/architecture/SCHEMA_DRIFT_AUDIT.md):

- production Alembic revision is `079_pre_booking_inquiries_archive_columns`
- `market_registry` and `market_events` tables exist
- `operator_policies.market_id` does not exist
- `ix_operator_policies_market_id` does not exist
- `operator_policies` currently has `0` rows
- `074_operator_policies_tenant_id_canonical.py` added canonical `tenant_id` and unique `ux_operator_policies_tenant_id`, but did not drop `operator_id` and did not add or restore `market_id`

This means production is not merely "behind migrations." It is on a later revision while missing two artifacts that `017_market_events_registry.py` says should exist.

Current code confirms a three-way split:

- legacy read path in [operator.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/api/v1/endpoints/operator.py:1608): `GET /operator/upsell-rates` reads `operator_policies` by `operator_id = :oid`, where `tenant = str(_require_tenant(request))`
- legacy write path in [operator.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/api/v1/endpoints/operator.py:1646): `POST /operator/upsell-rates` inserts `operator_id` using that same tenant-UUID-as-string pattern
- legacy analytics read in [operator.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/api/v1/endpoints/operator.py:1287): revenue analytics also reads `operator_policies` by `operator_id = :oid`
- canonical-but-drift-masked read in [operator.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/api/v1/endpoints/operator.py:1881): `market-events` filters by canonical `tenant_id`, but selects `market_id` from a column missing in production and falls back to `"30a_fl"`
- adjacent service path in `pre_booking_auto_send.py` was previously suspected; current tree does not show a direct SQL read, so Codex must verify rather than assume

The risk is still partly dormant because the table is empty. Once operator-authored rows start landing, dormant drift becomes active shape risk.

## Authoritative Reading Before Starting

Read these before making changes:

- [db/migrations/versions/017_market_events_registry.py](/Users/dhuntermckenzie/Downloads/oyvoda/db/migrations/versions/017_market_events_registry.py)
- [db/migrations/versions/074_operator_policies_tenant_id_canonical.py](/Users/dhuntermckenzie/Downloads/oyvoda/db/migrations/versions/074_operator_policies_tenant_id_canonical.py)
- [db/migrations/versions/022_merge_all_heads.py](/Users/dhuntermckenzie/Downloads/oyvoda/db/migrations/versions/022_merge_all_heads.py)
- [app/api/v1/endpoints/operator.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/api/v1/endpoints/operator.py)
- [app/services/concierge/pre_booking_auto_send.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/concierge/pre_booking_auto_send.py)
- [docs/architecture/SCHEMA_DRIFT_AUDIT.md](/Users/dhuntermckenzie/Downloads/oyvoda/docs/architecture/SCHEMA_DRIFT_AUDIT.md)
- [docs/architecture/EXCEPTION_HANDLING_AUDIT.md](/Users/dhuntermckenzie/Downloads/oyvoda/docs/architecture/EXCEPTION_HANDLING_AUDIT.md)
- [docs/architecture/TENANT_ISOLATION_AUDIT.md](/Users/dhuntermckenzie/Downloads/oyvoda/docs/architecture/TENANT_ISOLATION_AUDIT.md)
- [docs/architecture/CANONICAL_OPERATOR_KNOWLEDGE_MODEL.md](/Users/dhuntermckenzie/Downloads/oyvoda/docs/architecture/CANONICAL_OPERATOR_KNOWLEDGE_MODEL.md)

Use production schema inspection as the source of truth, not migration intent.

## Goal

After this phase:

- `operator_policies` schema matches the code contract needed by surviving paths: `market_id` exists with its expected index, and `tenant_id` is the authoritative identity key
- touched `operator_policies` reads and writes in `operator.py` use canonical `tenant_id`, not legacy `operator_id`
- `market-events` reads a real `market_id` when configured, and only falls back when an operator truly has no configuration
- exception handling is tightened on touched `operator_policies` paths so schema drift and DB-shape failures stop disappearing silently into default payloads
- Phase 4.3-B operator UI work can land onto a coherent schema and code model

## Hard Constraints

1. Verify migration `017` artifacts comprehensively before assuming only two objects are missing.
2. The corrective migration must use defensive existence checks, matching the pattern already used in `074`.
3. No data migration is allowed in this phase. Immediately before applying the corrective migration, verify `SELECT COUNT(*) FROM operator_policies`. If the count is non-zero, stop and produce a separate data-migration brief.
4. `operator_id` stays in the table for now as deprecated or transitional. Do not remove it in this phase.
5. Tenant resolution stays auth-context-driven per Phase 4.3-D. Do not reintroduce query-param tenant overrides or sentinel fallbacks.
6. Migrate all discovered `operator_policies` code paths in one phase. Do not leave half the reads on `operator_id` and half on `tenant_id`.
7. Tighten exception handling on touched `operator_policies` paths, but preserve intended user-facing behavior unless silent schema masking is the behavior being removed.
8. If a lightweight existing test harness supports this cleanly, add a regression test. If not, document the exact test gap and defer the broader scaffold to Phase 4.3-I.1 rather than blocking this phase.

## Investigation Steps

### Step 1: Comprehensive verification of migration `017` artifacts

Before authoring the corrective migration, verify all `017` artifacts in production, not just the already-known missing ones.

Run:

```sql
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN ('market_registry', 'market_events')
ORDER BY table_name;

SELECT table_name, column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'public'
  AND (
    (table_name = 'operator_policies' AND column_name = 'market_id')
    OR table_name IN ('market_registry', 'market_events')
  )
ORDER BY table_name, ordinal_position;

SELECT tablename, indexname, indexdef
FROM pg_indexes
WHERE schemaname = 'public'
  AND indexname IN (
    'ix_operator_policies_market_id',
    'ix_market_events_source_dedup',
    'ix_market_events_market_dates',
    'ix_market_events_upcoming',
    'ix_market_events_rag_pending',
    'ix_market_events_market_id'
  )
ORDER BY tablename, indexname;

SELECT market_id, market_name
FROM market_registry
ORDER BY market_id;
```

Document exactly which `017` operations completed and which did not. If anything beyond `operator_policies.market_id` and `ix_operator_policies_market_id` is missing, expand the corrective migration accordingly.

### Step 2: Verify actual production shape of `operator_policies`

Run:

```sql
SELECT column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = 'operator_policies'
ORDER BY ordinal_position;

SELECT indexname, indexdef
FROM pg_indexes
WHERE schemaname = 'public' AND tablename = 'operator_policies'
ORDER BY indexname;

SELECT COUNT(*) AS row_count
FROM operator_policies;
```

Expected current state from the audit:

- `operator_id` is `character varying`
- `tenant_id` is `uuid`
- `market_id` is absent
- `ux_operator_policies_tenant_id` exists
- `ix_operator_policies_operator_id` exists
- row count is `0`

### Step 3: Complete the code-side inventory

Search the codebase for all `operator_policies` reads and writes:

```bash
rg "operator_policies" app/ --type py -n
```

For every hit, classify:

- reads or writes by `operator_id` as legacy
- reads or writes by `tenant_id` as canonical
- reads of `market_id` as schema-drift-sensitive
- broad exception handling around these paths as audit targets

Known current hits to include:

- [app/api/v1/endpoints/operator.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/api/v1/endpoints/operator.py:1287) revenue analytics legacy read
- [app/api/v1/endpoints/operator.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/api/v1/endpoints/operator.py:1608) `get_upsell_rates` legacy read
- [app/api/v1/endpoints/operator.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/api/v1/endpoints/operator.py:1646) `set_upsell_rates` legacy write
- [app/api/v1/endpoints/operator.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/api/v1/endpoints/operator.py:1881) `market-events` canonical read of drifted column

Also verify whether `pre_booking_auto_send.py` still performs any direct `operator_policies` SQL reads in the current tree. Do not assume older notes remain current.

### Step 4: Author the corrective migration

Create a new migration with the next verified revision number, for example:

- `080_operator_policies_market_id_corrective.py` if `079` is still head in the target environment

Required shape:

- defensive `_column_exists` and `_index_exists` checks
- row-count guard that raises if `operator_policies` is non-empty
- add `market_id` if missing
- add `ix_operator_policies_market_id` if missing
- if Step 1 found any other missing `017` artifacts, reconcile them in the same corrective migration

The migration should be explicitly documented as a production drift reconciliation, not a new feature.

### Step 5: Migrate code paths off legacy `operator_id`

Migrate all discovered `operator_policies` accesses in this phase.

At minimum:

- `get_upsell_rates`: switch `WHERE operator_id = :oid` to canonical `tenant_id`
- `set_upsell_rates`: write `tenant_id` and use the canonical unique constraint or conflict target already present in production
- revenue analytics in `operator.py`: migrate the `operator_policies` lookup to canonical `tenant_id`
- `market-events`: keep canonical `tenant_id` lookup and make `market_id` fallback explicit and intentionally degraded rather than drift-masked
- any additional discovered path: migrate in the same phase

`operator_id` may remain present in the table, but touched code should stop treating it as the authoritative key.

### Step 6: Tighten exception handling on touched paths

On touched `operator_policies` endpoints or helpers:

- replace broad silent masking with narrower DB-focused handling where practical
- preserve intended fallback behavior when the endpoint is intentionally resilient
- do not preserve silent schema masking that makes drift invisible
- add structured logging with enough context to diagnose production issues quickly

This is a targeted retrofit, not a whole-file exception-handling rewrite. The purpose is to stop column-missing and shape-mismatch failures from looking like healthy defaults.

### Step 7: Tests or explicit test-gap note

If there is already a lightweight place to add this coverage, add a regression test that:

- exercises the canonical `tenant_id` path for writing and reading policy data
- verifies `market_id`-dependent behavior no longer depends on the legacy drift shape

If adding that test would require building new infra or a large scaffold, document the precise gap and defer the broader schema-shape regression harness to Phase 4.3-I.1. Do not let test scaffolding block the reconciliation.

### Step 8: Documentation update

Update [SCHEMA_DRIFT_AUDIT.md](/Users/dhuntermckenzie/Downloads/oyvoda/docs/architecture/SCHEMA_DRIFT_AUDIT.md) with a short “Phase 4.3-L.1 Reconciliation Outcome” section documenting:

- what the corrective migration changed
- which code paths moved to canonical `tenant_id`
- what exception-handling tightening landed
- what remains intentionally deferred

Update [CANONICAL_OPERATOR_KNOWLEDGE_MODEL.md](/Users/dhuntermckenzie/Downloads/oyvoda/docs/architecture/CANONICAL_OPERATOR_KNOWLEDGE_MODEL.md) if needed so it clearly states that `tenant_id` is the canonical identity for `operator_policies` and `operator_id` is transitional.

## Pre-flight Before Commit

- all `017` artifacts verified against production
- `operator_policies` row count confirmed `0` immediately before migration
- corrective migration is defensive and idempotent
- all discovered `operator_policies` reads and writes migrated to canonical `tenant_id`
- touched exception handling tightened without unnecessary behavior churn
- regression test added if lightweight, otherwise explicit test-gap note documented
- schema-drift audit updated with reconciliation outcome
- post-migration verification queries confirm canonical shape

## Commit Message Template

```text
Phase 4.3-L.1: reconcile operator_policies schema and identity paths

Reconciles production drift surfaced by Phase 4.3-L:
- adds operator_policies.market_id and ix_operator_policies_market_id
- verifies and reconciles missing 017 artifacts as needed
- migrates surviving operator_policies reads/writes to canonical tenant_id
- tightens exception handling on touched operator_policies paths

Safety:
- defensive existence checks
- row-count guard requiring operator_policies to be empty before migration

operator_id remains in the table as deprecated/transitional.
```

## Out of Scope

- removing the `operator_id` column
- backfilling or transforming non-empty production data
- Phase 4.3-B operator UI implementation
- Phase 4.3-M router confidence-threshold or intent-classifier work
- sweeping exception-handling cleanup outside touched `operator_policies` paths
- building a broad schema-shape regression framework if one does not already exist
- unrelated drift audits outside `operator_policies`

## Required Completion Report Back

When this phase is complete, report back with:

- commit SHA
- resulting Alembic head or production `alembic_version`
- updated `operator_policies` column list and indexes
- list of code paths migrated
- note on whether a regression test was added or explicitly deferred
- confirmation of how exception handling was tightened on the touched paths
