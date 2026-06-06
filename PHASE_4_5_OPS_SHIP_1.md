# Ship 1 — Queue Restoration (Forward Flow)

## Goal

Get Beach Habitats's pre-booking queue into a clean state where new inquiries flow in and reach Lanier's review queue within minutes of arrival. Empty the 14-day-old backlog from view. Keep all properties in REQUIRED mode so the operator approves each draft before it sends; AUTO toggle ships in Ship 2.

## Hard constraints

- All 45 active properties (filtered by `properties.is_active = true`) are initialized with `approval_mode='required'`
- Full backlog clear: ALL 507 `pre_booking_inquiries` rows for Beach Habitats currently in `pending_review` status get moved to `backlog_held`. No age cutoff — full clear.
- Backlog rows are NOT deleted, just status-changed. Recoverable if needed.
- Writeback patch (committed at 28fc0ca) deploys with the app code
- Deploy ordering matters: backlog status-gate UPDATE first, then rollout-init upsert, then app deploy with writeback patch, then verification

## Required reading

- `OPERATOR_READINESS_ARC.md` — the parent document
- `app/services/staged_rollout.py` — particularly `set_approval_mode`, `get_approval_mode`, `MIGRATION_SQL`, and the phase metadata table
- `app/services/concierge/inquiry_persistence.py` — the writeback patch already lives here
- Existing Ship 1 deploy plan (Codex's prior output) — the SQL shapes there are still valid, just need to be regenerated for 45 properties instead of 12

## Tasks

### 1. Confirm the 45 active properties

Run:

```sql
SELECT property_id, property_code, property_name
FROM properties
WHERE company_id = 'e07980b2-a990-4b24-91d1-c8cb71ab70e1'
  AND is_active = true
ORDER BY property_code;
```

Confirm count = 45. Document the list in `docs/architecture/SHIP_1_PROPERTY_LIST.md` so we have a reference for what got initialized.

### 2. Generate backlog status-gate UPDATE

```sql
-- Run FIRST, before rollout init
UPDATE pre_booking_inquiries
SET status = 'backlog_held'
WHERE company_id = 'e07980b2-a990-4b24-91d1-c8cb71ab70e1'
  AND status = 'pending_review';
```

This is the full-clear variant (Option A). All 507 stuck rows move to `backlog_held`. No age cutoff.

### 3. Generate rollout-init upsert for 45 properties in REQUIRED mode

```sql
-- Run SECOND, after backlog is locked
INSERT INTO property_rollout_phases (
    company_id,
    property_id,
    phase,
    approval_mode,
    approval_mode_set_by,
    approval_mode_set_at,
    entered_at,
    created_at
)
VALUES
    -- 45 rows, one per active property
    ('e07980b2-a990-4b24-91d1-c8cb71ab70e1'::uuid, '<property_code>', 'pre_booking_full', 'required', 'ship_1_init', NOW(), NOW(), NOW()),
    ...
ON CONFLICT (company_id, property_id)
DO UPDATE SET
    phase = EXCLUDED.phase,
    approval_mode = EXCLUDED.approval_mode,
    approval_mode_set_by = EXCLUDED.approval_mode_set_by,
    approval_mode_set_at = EXCLUDED.approval_mode_set_at,
    entered_at = EXCLUDED.entered_at;
```

Codex generates the full VALUES list from the property list in Task 1.

### 4. Deploy app code with writeback patch (28fc0ca)

Already committed. Deploys with the Railway app deploy as part of this ship.

### 5. Verification queries

Run all four after deploy:

**Q1 — Rollout state for 45 properties:**
```sql
SELECT phase, approval_mode, COUNT(*) AS property_count
FROM property_rollout_phases
WHERE company_id = 'e07980b2-a990-4b24-91d1-c8cb71ab70e1'::uuid
GROUP BY phase, approval_mode
ORDER BY phase, approval_mode;
```
Expected: 45 rows in `pre_booking_full` / `required`.

**Q2 — Backlog lock:**
```sql
SELECT status, COUNT(*)
FROM pre_booking_inquiries
WHERE company_id = 'e07980b2-a990-4b24-91d1-c8cb71ab70e1'
GROUP BY status
ORDER BY status;
```
Expected: 0 in `pending_review`, 507+ in `backlog_held`.

**Q3 — Forward flow check (run 24-48h after deploy):**
```sql
SELECT
    DATE(received_at) AS day,
    COUNT(*) AS new_inquiries,
    COUNT(*) FILTER (WHERE draft_text IS NOT NULL AND draft_text != '') AS has_draft,
    COUNT(*) FILTER (WHERE property_external_id IS NOT NULL AND property_external_id != '') AS bound
FROM pre_booking_inquiries
WHERE company_id = 'e07980b2-a990-4b24-91d1-c8cb71ab70e1'
  AND received_at >= NOW() - INTERVAL '48 hours'
  AND status = 'pending_review'
GROUP BY DATE(received_at)
ORDER BY day DESC;
```
Expected: non-zero `new_inquiries`, most should have `has_draft = 1` and `bound = 1`.

**Q4 — Writeback patch spot-check:**
```sql
SELECT
  p.draft_id,
  p.property_external_id,
  m.selected_property_code
FROM pre_booking_inquiries p
LEFT JOIN message_normalizations m
  ON m.tenant_id = p.company_id
 AND m.source_message_id = p.message_id
WHERE p.company_id = 'e07980b2-a990-4b24-91d1-c8cb71ab70e1'
  AND p.received_at >= NOW() - INTERVAL '48 hours'
  AND p.property_external_id IS NULL OR p.property_external_id = ''
ORDER BY p.received_at DESC
LIMIT 20;
```
Expected: any rows where `property_external_id` is blank should also have `selected_property_code` blank (the writeback patch ensures these stay aligned). If we see blank `property_external_id` with non-blank `selected_property_code`, the patch isn't firing.

## Ship criteria

- All 4 verification queries return expected results
- 24-hour observation window: new inquiries flow into `pending_review` status, brain processes them, drafts appear
- Lanier sees an empty queue at the start, populated with fresh inquiries by end of day 1
- `OPERATOR_READINESS_ARC.md` status updated: Ship 1 → DEPLOYED → VERIFIED

## What this ship does NOT do

- Does NOT enable any auto-sending (everything held for operator review)
- Does NOT fix draft quality (drafts will still have Taylor-style dodge issues until Ship 3)
- Does NOT add a UI toggle for AUTO mode (Ship 2)
- Does NOT touch the 43-row property-binding gap (Ship 6)

These are deliberate scope limits to keep Ship 1 small and deployable today.

## Codex commit-message format

```
phase 4.5 ops ship 1: queue restoration

- initialized 45 active beach habitats properties in pre_booking_full / required mode
- backlog status-gate moved 507 rows from pending_review to backlog_held
- deployed writeback patch (28fc0ca) for normalization-to-inquiry property code

verification:
  - rollout rows: 45 in pre_booking_full / required
  - backlog locked: 507 in backlog_held, 0 in pending_review
  - forward flow check: scheduled for 24h post-deploy
```
