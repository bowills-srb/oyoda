## Phase 3B Production Apply Plan

Date: 2026-05-14  
Status: Draft plan for production application of `069_phase_3b_add_tenant_id_to_operational_tables`

This plan covers production application of Phase 3B only.

Scope:
- add nullable `tenant_id` to:
  - `pre_booking_inquiries`
  - `operator_market_links`
  - `property_incidents`
- backfill `tenant_id` from `company_id` by joining through `operator_accounts`
- create tenant-leading indexes for the new read patterns
- verify backfill integrity before any code paths begin using the new columns

This phase touches operational tables, but it does not change live application
reads or writes yet. The new columns and indexes are inert until later Phase 3
code changes.

## 1. Pre-Apply State Capture

### a. Confirm current production head

```sql
SELECT version_num FROM alembic_version;
```

Expected:
- `068_phase_3a_create_tenant_identity`

If not:
- stop
- reconcile production migration state before applying `069`

### b. Confirm Phase 3A identity tables are present and consistent

```sql
SELECT to_regclass('public.tenants') AS tenants_exists;
SELECT to_regclass('public.operator_users') AS operator_users_exists;
```

Expected:
- both non-null

```sql
SELECT
  (SELECT COUNT(*) FROM operator_accounts) AS operator_accounts_count,
  (SELECT COUNT(*) FROM tenants WHERE source_operator_account_id IS NOT NULL) AS seeded_tenants_count,
  (SELECT COUNT(*) FROM operator_users WHERE source_operator_account_id IS NOT NULL) AS seeded_operator_users_count;
```

Expected:
- all three counts equal

If not:
- stop
- Phase 3A verification did not complete cleanly

### c. Confirm target table row counts

```sql
SELECT 'pre_booking_inquiries' AS table_name, COUNT(*) AS row_count FROM pre_booking_inquiries
UNION ALL
SELECT 'operator_market_links', COUNT(*) FROM operator_market_links
UNION ALL
SELECT 'property_incidents', COUNT(*) FROM property_incidents;
```

Record these counts before apply for post-apply comparison.

Expected current scale:
- `pre_booking_inquiries` has live rows
- `operator_market_links` may be zero
- `property_incidents` may be zero

### d. Confirm target tables still use `company_id` and do not yet have `tenant_id`

```sql
SELECT table_name, column_name
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name IN ('pre_booking_inquiries', 'operator_market_links', 'property_incidents')
  AND column_name IN ('company_id', 'tenant_id')
ORDER BY table_name, column_name;
```

Expected:
- `company_id` exists on all three tables
- `tenant_id` does not yet exist on any of them

If not:
- stop
- inspect whether a partial/manual Phase 3B attempt already happened

### e. Confirm `operator_accounts.tenant_id` consistency

```sql
SELECT
  COUNT(*) FILTER (WHERE tenant_id IS NULL) AS null_tenant_id_rows,
  COUNT(*) AS account_count,
  COUNT(DISTINCT tenant_id) AS distinct_tenant_ids
FROM operator_accounts;
```

Expected:
- `null_tenant_id_rows = 0`
- `account_count = distinct_tenant_ids`

Hard stops:
- any null `tenant_id`
- duplicate `tenant_id` values

### f. Confirm target-table `company_id` values map to `operator_accounts.tenant_id`

```sql
SELECT 'pre_booking_inquiries' AS table_name,
       COUNT(*) FILTER (WHERE company_id IS NOT NULL) AS rows_with_company_id,
       COUNT(*) FILTER (WHERE oa.id IS NOT NULL) AS mapped_rows
FROM pre_booking_inquiries pbi
LEFT JOIN operator_accounts oa ON oa.tenant_id = pbi.company_id
UNION ALL
SELECT 'operator_market_links',
       COUNT(*) FILTER (WHERE company_id IS NOT NULL),
       COUNT(*) FILTER (WHERE oa.id IS NOT NULL)
FROM operator_market_links oml
LEFT JOIN operator_accounts oa ON oa.tenant_id = oml.company_id
UNION ALL
SELECT 'property_incidents',
       COUNT(*) FILTER (WHERE company_id IS NOT NULL),
       COUNT(*) FILTER (WHERE oa.id IS NOT NULL)
FROM property_incidents pi
LEFT JOIN operator_accounts oa ON oa.tenant_id = pi.company_id;
```

Expected:
- for each table, `mapped_rows = rows_with_company_id`

If not:
- stop
- identify the unmapped `company_id` values before attempting the migration

### g. Confirm Beach Habitats operations healthy

```sql
SELECT MAX(created_at) FROM pre_booking_inquiries;
SELECT MAX(processed_at) FROM gmail_processed_messages;
SELECT MAX(updated_at) FROM operator_prebooking_queue_read_models;
```

Expected:
- all three timestamps recent and moving normally

If any table looks unexpectedly stalled:
- stop
- verify app health before migration

### Pre-Apply Gate

- all checks in Section 1 must pass before proceeding to Section 2
- if any hard stop triggers:
  - stop
  - investigate
  - document the issue
  - do not re-attempt until resolved
- do not proceed to `alembic upgrade` with any Section 1 failure

## 2. Apply Window and Migration Apply

### Apply window guidance

- Phase 3B does not change active code paths, so it does not require a multi-day
  waiting window before Phase 3C drafting
- however, it does mutate operational tables and build new indexes, so apply
  during a low-traffic window
- preferred timing: overnight or early morning Central Time
- Hunter monitors live during the apply
- expected duration at current Beach Habitats scale: short, but longer than
  Phase 3A because operational-table DDL and index builds are involved

### Migration apply

Apply only Phase 3B, not `upgrade head`.

```bash
ALEMBIC_USE_DIRECT_URL=true .venv/bin/alembic -c alembic.ini upgrade 069_phase_3b_add_tenant_id_to_operational_tables
```

Discipline:
- one migration set only
- no combined apply with future Phase 3C+
- monitor logs during execution

## 3. Post-Apply Verification

### a. Confirm new production head

```sql
SELECT version_num FROM alembic_version;
```

Expected:
- `069_phase_3b_add_tenant_id_to_operational_tables`

### b. Confirm `tenant_id` columns now exist

```sql
SELECT table_name, column_name
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name IN ('pre_booking_inquiries', 'operator_market_links', 'property_incidents')
  AND column_name = 'tenant_id'
ORDER BY table_name;
```

Expected:
- one `tenant_id` row for each of the three target tables

### c. Verify every row with `company_id` now has `tenant_id`

```sql
SELECT 'pre_booking_inquiries' AS table_name,
       COUNT(*) FILTER (WHERE company_id IS NOT NULL AND tenant_id IS NULL) AS missing_tenant_rows
FROM pre_booking_inquiries
UNION ALL
SELECT 'operator_market_links',
       COUNT(*) FILTER (WHERE company_id IS NOT NULL AND tenant_id IS NULL)
FROM operator_market_links
UNION ALL
SELECT 'property_incidents',
       COUNT(*) FILTER (WHERE company_id IS NOT NULL AND tenant_id IS NULL)
FROM property_incidents;
```

Expected:
- `0` for all three tables

### d. Verify tenant references are valid

```sql
SELECT 'pre_booking_inquiries' AS table_name,
       COUNT(*) AS orphan_tenant_rows
FROM pre_booking_inquiries pbi
LEFT JOIN tenants t ON t.id = pbi.tenant_id
WHERE pbi.tenant_id IS NOT NULL
  AND t.id IS NULL
UNION ALL
SELECT 'operator_market_links',
       COUNT(*)
FROM operator_market_links oml
LEFT JOIN tenants t ON t.id = oml.tenant_id
WHERE oml.tenant_id IS NOT NULL
  AND t.id IS NULL
UNION ALL
SELECT 'property_incidents',
       COUNT(*)
FROM property_incidents pi
LEFT JOIN tenants t ON t.id = pi.tenant_id
WHERE pi.tenant_id IS NOT NULL
  AND t.id IS NULL;
```

Expected:
- `0` for all three tables

### e. Confirm row counts unchanged

Re-run the Section 1.c row-count query.

Expected:
- same counts as pre-apply

### f. Spot-check Beach Habitats `tenant_id` propagation on inquiries

```sql
SELECT COUNT(*)
FROM pre_booking_inquiries
WHERE tenant_id = 'e07980b2-a990-4b24-91d1-c8cb71ab70e1'::uuid;
```

Expected:
- non-zero result matching Beach Habitats inquiry ownership

If needed, compare directly:

```sql
SELECT COUNT(*)
FROM pre_booking_inquiries
WHERE company_id = 'e07980b2-a990-4b24-91d1-c8cb71ab70e1'::uuid
  AND tenant_id = 'e07980b2-a990-4b24-91d1-c8cb71ab70e1'::uuid;
```

Expected:
- all Beach Habitats inquiry rows counted by `company_id` also have matching
  `tenant_id`

### g. Verify the six new indexes exist

```sql
SELECT tablename, indexname
FROM pg_indexes
WHERE schemaname = 'public'
  AND tablename IN ('pre_booking_inquiries', 'operator_market_links', 'property_incidents')
  AND indexname IN (
    'ix_pre_booking_inquiries_tenant_status_created_at',
    'ix_pre_booking_inquiries_tenant_gmail_thread',
    'ix_operator_market_links_tenant_id',
    'ux_operator_market_links_tenant_market_id',
    'ix_property_incidents_tenant_status_active',
    'ix_property_incidents_tenant_property_reported_at'
  )
ORDER BY tablename, indexname;
```

Expected:
- all six indexes present

## 4. Operational Sanity After Apply

Even though Phase 3B does not switch live code paths to `tenant_id` yet, verify
no collateral operational impact.

```sql
SELECT MAX(created_at) FROM pre_booking_inquiries;
SELECT MAX(processed_at) FROM gmail_processed_messages;
SELECT MAX(updated_at) FROM operator_prebooking_queue_read_models;
```

App-level sanity:
- Beach Habitats inbox still receiving messages
- pre-booking queue still loads
- Beach Habitats dashboard still loads
- incidents panel still loads
- market intelligence still loads

## 5. Monitoring / Sequencing

- no 7-day waiting window is required between Phase 3A and Phase 3B
- no 7-day waiting window is required between successful Phase 3B verification
  and Phase 3C drafting
- success is determined by immediate post-apply verification
- the longer monitoring windows begin when live code starts dual-writing and
  reading the new keys in later sub-phases

## 6. Rollback Plan

Because Phase 3B adds nullable columns and indexes without changing live code
paths:
- simplest rollback is Alembic downgrade to `068`
- this is only safe before later Phase 3 code changes begin depending on the
  new columns

Rollback command:

```bash
ALEMBIC_USE_DIRECT_URL=true .venv/bin/alembic -c alembic.ini downgrade 068_phase_3a_create_tenant_identity
```

Rollback verification:

```sql
SELECT version_num FROM alembic_version;

SELECT table_name, column_name
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name IN ('pre_booking_inquiries', 'operator_market_links', 'property_incidents')
  AND column_name = 'tenant_id';
```

Expected after rollback:
- head back at `068...`
- no `tenant_id` columns on the three target tables

Important:
- do not roll back after Phase 3C+ starts using these columns without a new
  plan

## 7. Criteria Mapping

This migration advances:
- `A1`: operational tables gain canonical `tenant_id`
- `A2`: tenant-leading indexes added on active operational tables
- `B3`: queue, Gmail-thread, market-link, and incidents query patterns gain
  tenant-leading indexes
- `H1`: schema described by migration
- `H2`: round-trip passes

Verified before production apply:
- `069` compiles
- round-trip passes through `069`
- in-migration backfill verification raises on inconsistency
