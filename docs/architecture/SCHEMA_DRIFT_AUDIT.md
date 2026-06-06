# Schema Drift Audit

Date: 2026-05-18  
Phase: 4.3-L  
Scope: `operator_policies` first, with adjacent migration-history notes

## Summary

Production schema for `operator_policies` does not fully match migration history or current code expectations.

Confirmed production state:

- `operator_policies.operator_id` exists and is `character varying`
- `operator_policies.tenant_id` exists and is `uuid`
- `operator_policies.market_id` does **not** exist
- `operator_policies` has `0` rows
- `market_registry` and `market_events` tables do exist in production
- `ix_operator_policies_market_id` does **not** exist
- production Alembic revision is `079_pre_booking_inquiries_archive_columns`

This is not a simple "migrations never ran" situation. Production is on a late Alembic revision that descends from the branch containing `017_market_events_registry`, and the market tables from that migration exist. But the `operator_policies.market_id` column and its index from the same migration do not exist, and no later migration drops them.

The result is real production schema drift.

Current impact is mixed:

- **Dormant risk** for operator-authored policy rows, because `operator_policies` is still empty
- **Active masked bug** for code paths that read `operator_policies.market_id`, because those reads now rely on fallback behavior instead of a real column

## Production State

### Alembic version

```sql
SELECT version_num FROM alembic_version;
```

Result:

```text
079_pre_booking_inquiries_archive_columns
```

### `operator_policies` columns

```sql
SELECT
  column_name,
  data_type,
  is_nullable
FROM information_schema.columns
WHERE table_name = 'operator_policies'
ORDER BY ordinal_position;
```

Relevant result:

```text
id                                uuid                        NOT NULL
operator_id                       character varying           NULL
...
upsell_rates                      jsonb                       NULL
upsell_rates_configured           boolean                     NULL
created_at                        timestamp with time zone    NOT NULL
updated_at                        timestamp with time zone    NOT NULL
tenant_id                         uuid                        NULL
```

Notably absent:

```text
market_id
```

### `operator_policies` indexes

```sql
SELECT indexname, indexdef
FROM pg_indexes
WHERE tablename = 'operator_policies'
ORDER BY indexname;
```

Relevant result:

```text
ix_operator_policies_operator_id
operator_policies_operator_id_key
operator_policies_pkey
ux_operator_policies_tenant_id
```

Notably absent:

```text
ix_operator_policies_market_id
```

### Related production objects

```sql
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN ('market_registry', 'market_events')
ORDER BY table_name;
```

Result:

```text
market_events
market_registry
```

### Row count

```sql
SELECT COUNT(*) FROM operator_policies;
```

Result:

```text
0
```

## Migration-History Expectations

### `010_operator_policies_markets.py`

This migration creates the original `operator_policies` table with:

- `operator_id` as required string identity
- no `tenant_id`
- no `market_id`

This is the legacy operator-scoped shape.

### `017_market_events_registry.py`

This migration explicitly adds:

- `market_registry`
- `market_events`
- `operator_policies.market_id`
- `ix_operator_policies_market_id`

Relevant lines:

```python
op.add_column(
    "operator_policies",
    sa.Column("market_id", sa.String(100), nullable=True),
)
op.create_index(
    "ix_operator_policies_market_id",
    "operator_policies",
    ["market_id"],
    unique=False,
)
```

### `018_pre_booking_pipeline.py`

This migration has:

```python
down_revision = "017"
```

So the main runtime chain after `017` continues through `018`.

### `020_merge_runtime_schema_branches.py`

This migration merges:

- `018_pre_booking_pipeline`
- `019`

That means the `017` chain is part of the merged runtime lineage.

### `021_runtime_tables_to_alembic.py`

This migration continues from:

```python
down_revision = "020_merge_branches"
```

### `022_merge_all_heads.py`

This migration merges:

- `010_operator_policies_markets`
- `021_runtime_tables_to_alembic`

This is the point where the older operator-policy branch and the runtime-schema branch are reconciled in Alembic history.

### `074_operator_policies_tenant_id_canonical.py`

This migration canonicalizes `operator_policies` toward tenant-scoped identity:

- adds `tenant_id` if missing
- makes `operator_id` nullable
- creates unique partial index on `tenant_id`
- retains `operator_id`

It does **not** drop `market_id`.

## Drift Findings

### 1. Production is beyond revision `017`, so the missing column is real drift

Production Alembic revision is `079_pre_booking_inquiries_archive_columns`, which is later than `074` and well beyond the `017 -> 018 -> 020 -> 021 -> 022` chain.

That means `operator_policies.market_id` is not missing because production is "behind" the migration that should add it. Production claims to be newer than that.

### 2. The `017` market-tables branch is at least partially present in production

`market_registry` and `market_events` both exist in production.

That matters because `017_market_events_registry.py` adds those tables and the `operator_policies.market_id` column in the same migration.

So the drift is not explained by "`017` never applied at all."

### 3. `operator_policies.market_id` and its index are missing without a matching drop migration

The repository contains:

- a migration that adds `market_id`
- no later migration that drops `market_id`

Production contains:

- the market tables from that branch
- but not the `market_id` column
- and not the `ix_operator_policies_market_id` index

The most likely explanations are:

1. `017` was applied incompletely or interrupted in a historical environment
2. `market_id` was removed manually outside Alembic history
3. production schema was patched ad hoc while Alembic versioning continued forward

The audit does not prove which of those three happened, but it does rule out "head was never deployed."

### 4. Code expectations are internally inconsistent

Current code uses `operator_policies` in two incompatible ways.

Legacy string-keyed reads/writes still exist in [operator.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/api/v1/endpoints/operator.py:1282) and [operator.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/api/v1/endpoints/operator.py:1646):

- `get_upsell_rates` reads by `operator_id = :oid`
- `set_upsell_rates` upserts by `operator_id`
- `get_revenue_impact` preloads upsell rates by `operator_id`

Newer tenant-canonical code in [operator_policies.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/api/v1/endpoints/operator_policies.py:107) reads and writes by `tenant_id`:

- `get_policies` reads by `tenant_id`
- `patch_policies` upserts on unique `tenant_id`

And `market-events` in [operator.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/api/v1/endpoints/operator.py:1880) expects:

- `tenant_id`-scoped rows
- a `market_id` column that production does not have

So the table is currently in a transitional identity state in code:

- legacy callers think in `operator_id`
- newer callers think in `tenant_id`
- `market-events` assumes the tenant-canonical shape plus a column absent in production

### 5. Current harm is mostly dormant, but one active bug is masked by fallback

Because `operator_policies` has `0` rows today:

- `get_upsell_rates` and related revenue reads currently fall back to platform defaults because no rows exist
- no operator-authored policy data is currently being silently lost or misread

However, `market-events` is already an active mismatch:

- current code queries `SELECT market_id FROM operator_policies WHERE tenant_id = ...`
- production lacks the `market_id` column
- the endpoint therefore relies on fallback behavior instead of real data

For Beach Habitats this is masked because fallback market `30a_fl` happens to match the operator's actual geography. For a future non-30A operator, the mismatch becomes operator-visible.

## Current Impact vs Future Risk

### Current impact

- Beach Habitats is not losing saved `operator_policies` data today because there are no rows
- the market-events endpoint is still structurally wrong against production schema, even though its fallback masks that for Beach Habitats

### Future risk

Once Phase `4.3-B` or any other operator-policy authoring path begins creating rows:

- mixed `operator_id` vs `tenant_id` writes can create split identity behavior
- code that expects `market_id` will continue to drift from the actual table shape
- future operators outside `30a_fl` can receive the wrong market context if fallback remains in place

This is exactly the kind of dormant drift that becomes a real data-shaping bug the moment the table starts being used as an operator-authored write target.

## Recommended Next Fix Phase

### Recommendation: `Phase 4.3-L.1 — operator_policies reconciliation`

This should be a focused implementation phase with three goals:

1. Reconcile schema to code expectations for `operator_policies.market_id`
   - either add the missing column/index with a corrective migration
   - or remove the code dependency if `market_id` is no longer meant to live there

2. Reconcile identity semantics
   - define the canonical key as `tenant_id`
   - explicitly treat `operator_id` as legacy/backward-compat only
   - migrate remaining read/write paths in `operator.py` off `operator_id` lookups

3. Add drift verification to the workflow
   - `alembic_version` alone is not sufficient proof of real schema state
   - Phase `4.3-L.1` should include a concrete production-schema verification step for the touched table

## Honest Assessment

This is a real drift finding, but it is not a fire tonight.

Why:

- `operator_policies` is empty, so there is no current operator-authored data to repair
- the broken `market_id` dependency is currently masked by fallback for Beach Habitats

Why it still matters:

- the table is about to become important once operator-policy authoring ships
- unresolved drift here will turn into incorrect writes and confusing reads later
- this is exactly the right moment to fix it: before `4.3-B` builds product surface on top of a table whose runtime meaning is still split

Recommended sequencing:

1. finish current deploy/observation verifications already in flight
2. implement `Phase 4.3-L.1` as a focused schema + identity reconciliation
3. then build operator-policy authoring UI on the reconciled table

## Phase 4.3-L.1 Reconciliation Outcome

Target implementation for Phase 4.3-L.1:

- add corrective migration `080_operator_policies_market_id_corrective`
- restore missing `operator_policies.market_id` and `ix_operator_policies_market_id`
- keep `operator_id` in place as deprecated or transitional, while treating `tenant_id` as canonical
- migrate surviving `operator.py` policy reads and writes from legacy `operator_id` usage to canonical `tenant_id`
- make `/operator/operator/market-events` fallback explicit so unconfigured operators still degrade safely, but schema drift no longer hides silently
- tighten exception handling on touched `operator_policies` paths with DB-focused logging rather than broad success-shaped masking

Post-phase verification should include:

```sql
SELECT column_name
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'operator_policies'
ORDER BY ordinal_position;

SELECT indexname
FROM pg_indexes
WHERE schemaname = 'public'
  AND tablename = 'operator_policies'
ORDER BY indexname;
```
