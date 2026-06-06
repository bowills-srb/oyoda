## Phase 3C Verification Plan

Date: 2026-05-14  
Status: Draft verification plan for the Phase 3C dual-write code change

Phase 3C is a code-change phase, not a migration phase.

Scope:
- add dual-write of `tenant_id` and `company_id` in the three primary writer
  paths:
  - `pre_booking_handler.py::_save_draft`
  - `pre_booking_auto_send.py::_insert_pre_booking_inquiry`
  - `incidents.py` `POST /incidents`
- use a shared helper in `app/services/identity/dual_write.py`
- assert identity consistency before writing:
  - `tenant_id == company_id`
  - fail loudly on divergence

This phase does not change read paths yet. `company_id` remains the live read
key until Phase 3D.

Divergence assertion note:
- its strongest immediate value is in `incidents.py`, where the code compares:
  - auth-resolved canonical tenant identity
  - payload-provided legacy `company_id`
- in `pre_booking_handler.py` and `pre_booking_auto_send.py`, the current
  production reality is that both values come from the same upstream identity
  source today
- the helper is still intentionally present there:
  - it fails loudly on missing identity
  - it keeps the SQL dual-write explicit
  - it becomes a real divergence tripwire if those writers later begin resolving
    tenant identity from a separate source during later Phase 3 work

## 1. Pre-Deploy Verification

- code audit confirms only the 3 primary writers need Phase 3C dual-write
  changes
- secondary update paths were reviewed and do not write identity columns
- unit tests pass:
  - helper tests cover:
    - matching UUIDs
    - matching string UUIDs
    - mixed UUID/string normalization
    - divergence raises `IdentityResolutionError`
    - invalid UUID string raises `ValueError`
  - writer tests cover:
    - pre-booking insert path writes both `tenant_id` and `company_id`
    - pre-booking divergence path raises and does not write
    - incidents create path writes both `tenant_id` and `company_id`
    - incidents divergence path fails visibly and does not write
- `py_compile` passes on all changed files

## 2. Deploy

- code change PR merged to `main`
- Railway deploys automatically
- no Alembic migration runs in Phase 3C because there is no migration file in
  this phase

## 3. Immediate Post-Deploy Verification

Run within 15 minutes of deploy.

### a. Verify recent inquiry rows have both keys populated and matching

```sql
SELECT
  id,
  tenant_id,
  company_id,
  tenant_id = company_id AS matches,
  created_at
FROM pre_booking_inquiries
WHERE created_at > NOW() - INTERVAL '15 minutes'
ORDER BY created_at DESC;
```

Expected:
- every new row has non-null `tenant_id`
- every new row has `tenant_id = company_id`

### b. Verify no new inquiry rows have null `tenant_id`

```sql
SELECT COUNT(*)
FROM pre_booking_inquiries
WHERE created_at > NOW() - INTERVAL '15 minutes'
  AND tenant_id IS NULL;
```

Expected:
- `0`

### c. Verify no `IdentityResolutionError` appeared in logs

Expected:
- `0` occurrences

### d. Verify Beach Habitats inbox flow still works

Expected:
- normal inbound polling continues
- new Beach Habitats inquiries still appear
- pre-booking queue still loads in dashboard

### e. Verify incidents endpoint still works

Expected:
- no new `500`/`403` spike for normal operator use
- create path succeeds for valid tenant-scoped requests

## 4. Operational Health

Within 15-30 minutes after deploy:

- Beach Habitats inbox still processing
- pre-booking queue still loading on dashboard
- no visible regression in operator actions on pending inquiries
- no incident-create failures for normal operator workflows

## 5. Monitoring Window

Duration:
- 3-7 days

Daily checks:

### a. Divergence count for new inquiries

```sql
SELECT COUNT(*)
FROM pre_booking_inquiries
WHERE created_at >= CURRENT_DATE
  AND tenant_id IS NOT NULL
  AND company_id IS NOT NULL
  AND tenant_id != company_id;
```

Expected:
- `0`

### b. Null `tenant_id` count for new inquiries

```sql
SELECT COUNT(*)
FROM pre_booking_inquiries
WHERE created_at >= CURRENT_DATE
  AND tenant_id IS NULL;
```

Expected:
- `0`

### c. Beach Habitats traffic still flowing

```sql
SELECT COUNT(*), MAX(created_at)
FROM pre_booking_inquiries
WHERE tenant_id = 'e07980b2-a990-4b24-91d1-c8cb71ab70e1'::uuid
  AND created_at >= CURRENT_DATE;
```

Expected:
- non-zero during normal traffic periods
- latest timestamp continues to move

### d. Log scan

Expected:
- no `IdentityResolutionError`
- no unexplained write failures in the three primary writer paths

## 6. Phase 3C Complete When

- 3-7 day monitoring window passes with no divergence
- all new rows show consistent dual-write
- no identity-resolution errors appear in logs
- Beach Habitats operations remain unchanged
- incidents create path remains healthy for normal operator use

Only then should Phase 3D read-cutover drafting begin.

## 7. Failure Handling / Rollback

If the monitoring window fails:
- investigate root cause
- do not proceed to Phase 3D
- fix the inconsistent writer path and redeploy

Rollback shape:
- revert the Phase 3C code change PR
- Railway deploys the reverted code
- no DB rollback is needed

Why no DB rollback is needed:
- Phase 3C does not alter schema
- rows written during the Phase 3C window keep valid `tenant_id` values
- pre-Phase-3C code can continue ignoring the extra populated column safely
