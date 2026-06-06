## Phase 3A Production Apply Plan

Date: 2026-05-14
Status: Reviewed plan for production application of `068_phase_3a_create_tenant_identity`

This plan covers production application of Phase 3A only.

Scope:
- create `tenants`
- create `operator_users`
- backfill both tables from `operator_accounts`
- verify identity-table integrity

This phase does not mutate operational tables. It establishes canonical identity
tables only.

## 1. Pre-Apply State Capture

### a. Confirm current production head

```sql
SELECT version_num FROM alembic_version;
```

Expected:
- `067_adopt_operator_policies_and_deprecate_legacy_setup_tables`

If not:
- stop
- reconcile production migration state before applying `068`

### b. Confirm `operator_accounts` state

```sql
SELECT
  COUNT(*) AS account_count,
  COUNT(DISTINCT tenant_id) AS distinct_tenant_ids,
  COUNT(*) FILTER (WHERE email IS NULL) AS null_email_rows,
  COUNT(*) FILTER (WHERE owner_name IS NULL) AS null_owner_rows,
  COUNT(*) FILTER (WHERE password_hash IS NULL) AS null_password_rows,
  COUNT(*) FILTER (WHERE company_name IS NULL) AS null_company_rows
FROM operator_accounts;
```

Expected:
- `account_count >= 1`
- `account_count = distinct_tenant_ids`
- all null counts = `0`

Hard stops:
- any null count `> 0`
- `account_count != distinct_tenant_ids`

Reason:
- `tenants.id` is backfilled from `operator_accounts.tenant_id`
- duplicate tenant ids would break canonical tenant creation
- null auth/profile fields would create incomplete `operator_users`

### c. Confirm `tenants` and `operator_users` do not yet exist

```sql
SELECT to_regclass('public.tenants') AS tenants_exists;
SELECT to_regclass('public.operator_users') AS users_exists;
```

Expected:
- both `NULL`

If either already exists:
- stop
- inspect whether a partial/manual Phase 3A attempt already happened

### d. Confirm Beach Habitats operations healthy

```sql
SELECT MAX(created_at) FROM pre_booking_inquiries;
SELECT MAX(processed_at) FROM gmail_processed_messages;
SELECT MAX(created_at) FROM operator_prebooking_queue_read_models;
```

Expected:
- all three timestamps recent and moving normally

Optional richer check:

```sql
SELECT 'pre_booking_inquiries', COUNT(*), MAX(created_at) FROM pre_booking_inquiries
UNION ALL
SELECT 'gmail_processed_messages', COUNT(*), MAX(processed_at) FROM gmail_processed_messages
UNION ALL
SELECT 'operator_prebooking_queue_read_models', COUNT(*), MAX(created_at) FROM operator_prebooking_queue_read_models;
```

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

- Phase 3A is technically safe to apply at any time because it does not change
  operational tables
- however, establish the discipline pattern now:
  - apply during a low-traffic window
  - preferred timing: overnight or early morning Central Time
- Hunter monitors live during the apply
- expected duration at current Beach Habitats scale: under 30 seconds

### Migration apply

Apply only Phase 3A, not `upgrade head`.

```bash
ALEMBIC_USE_DIRECT_URL=true .venv/bin/alembic -c alembic.ini upgrade 068_phase_3a_create_tenant_identity
```

Discipline:
- one migration set only
- no combined apply with future Phase 3B+
- monitor logs during execution

Why Phase 3A is safe:
- creates new tables only
- no operational table mutation
- no production traffic path changes yet

## 3. Post-Apply Verification

### a. Confirm new production head

```sql
SELECT version_num FROM alembic_version;
```

Expected:
- `068_phase_3a_create_tenant_identity`

### b. Confirm tables now exist

```sql
SELECT to_regclass('public.tenants') AS tenants_exists;
SELECT to_regclass('public.operator_users') AS users_exists;
```

Expected:
- both non-null

### c. Verify backfill counts

```sql
SELECT COUNT(*) FROM operator_accounts;
SELECT COUNT(*) FROM tenants WHERE source_operator_account_id IS NOT NULL;
SELECT COUNT(*) FROM operator_users WHERE source_operator_account_id IS NOT NULL;
```

Expected:
- all three counts equal

### d. Verify every `operator_account` got a tenant

```sql
SELECT COUNT(*)
FROM operator_accounts oa
LEFT JOIN tenants t ON t.id = oa.tenant_id
WHERE t.id IS NULL;
```

Expected:
- `0`

### e. Verify every `operator_account` got an initial owner user

```sql
SELECT COUNT(*)
FROM operator_accounts oa
LEFT JOIN operator_users ou
  ON ou.source_operator_account_id = oa.id
WHERE ou.id IS NULL;
```

Expected:
- `0`

### f. Verify no `operator_users` have null `tenant_id`

```sql
SELECT COUNT(*) FROM operator_users WHERE tenant_id IS NULL;
```

Expected:
- `0`

### g. Verify `operator_users` source refs are valid

```sql
SELECT COUNT(*)
FROM operator_users ou
LEFT JOIN operator_accounts oa ON oa.id = ou.source_operator_account_id
WHERE ou.source_operator_account_id IS NOT NULL
  AND oa.id IS NULL;
```

Expected:
- `0`

### h. Verify required indexes

```sql
SELECT tablename, indexname
FROM pg_indexes
WHERE schemaname = 'public'
  AND tablename IN ('tenants', 'operator_users')
ORDER BY tablename, indexname;
```

Expected indexes:
- `tenants_pkey`
- `ux_tenants_source_operator_account_id`
- `operator_users_pkey`
- `ux_operator_users_tenant_email`
- `ix_operator_users_tenant_role`
- `ix_operator_users_email`
- `ux_operator_users_source_operator_account_id`

## 4. Operational Sanity After Apply

Even though Phase 3A does not touch live operational tables, verify no
collateral impact.

```sql
SELECT MAX(created_at) FROM pre_booking_inquiries;
SELECT MAX(processed_at) FROM gmail_processed_messages;
SELECT MAX(created_at) FROM operator_prebooking_queue_read_models;
```

And app-level sanity:
- inbox poller still running
- pre-booking queue still loads
- Beach Habitats operator dashboard still loads
- no auth failures introduced by the new tables existing

## 5. Monitoring Window

Recommended:
- no separate multi-day waiting period is required before Phase 3B
- Phase 3A is schema-only, so success is determined by immediate post-apply
  verification rather than an extended stability window

Immediate post-apply monitoring should still check:
- error rates on auth/signup/dashboard
- DB connection wait time
- migration-related log noise
- any accidental reads/writes to `tenants` / `operator_users`
- Beach Habitats operational health

Success criteria for moving to Phase 3B:
- no production regressions
- no backfill inconsistencies
- no unexpected app behavior from coexistence with `operator_accounts`
- once those checks pass, Phase 3B drafting can continue immediately
- Phase 3B apply requires only successful Phase 3A verification, not a
  separate waiting period

## 6. Rollback Plan

Because Phase 3A only creates new tables:
- simplest rollback is Alembic downgrade to `067`
- only safe if we decide Phase 3A introduced an issue and we want to fully
  remove the tables before later phases depend on them

Rollback command:

```bash
ALEMBIC_USE_DIRECT_URL=true .venv/bin/alembic -c alembic.ini downgrade 067_adopt_operator_policies_and_deprecate_legacy_setup_tables
```

Rollback verification:

```sql
SELECT version_num FROM alembic_version;
SELECT to_regclass('public.tenants');
SELECT to_regclass('public.operator_users');
```

Expected after rollback:
- head back at `067...`
- both new tables absent

Important:
- do not roll back after Phase 3B+ starts depending on these tables without a
  new plan

## 7. Criteria Mapping

This migration advances:
- `A1`: canonical tenant table established
- `A2`: tenant-leading indexes on canonical user table
- `B3`: required indexes for canonical user access
- `H1`: schema described by migration
- `H2`: round-trip passes

Verified before production apply:
- round-trip passes through `068`
- required indexes present on fresh schema
- no operational tables touched
