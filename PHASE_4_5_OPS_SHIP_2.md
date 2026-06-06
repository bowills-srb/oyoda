# Ship 2 — Per-Property AUTO Toggle

## Goal

Give Lanier one-click control over which properties auto-send drafts and which stay in operator-review mode. Reversible at any time. No engineering involvement for normal operational decisions.

## Why this matters

After Ship 1, Beach Habitats's queue is healthy but every draft requires Lanier's manual approval. The product value proposition is auto-handling messages — but only when the operator trusts each property's drafts. Ship 2 builds the surface where Lanier promotes properties from REQUIRED to AUTO as her confidence grows, and rolls back instantly if something starts to go wrong.

## What's already built

`StagedRolloutService.set_approval_mode()` already exists at `app/services/staged_rollout.py:870`. It takes a company_id, property_id, mode (REQUIRED or AUTO), and set_by string. It updates `property_rollout_phases.approval_mode` and records the change in `approval_mode_set_by` and `approval_mode_set_at`. The runtime already respects this value at every relevant decision point.

So Ship 2 is small: a thin operator-facing API endpoint that calls this function, plus a UI control that calls the endpoint.

## Required reading

- `OPERATOR_READINESS_ARC.md`
- `app/services/staged_rollout.py` — `set_approval_mode`, `get_approval_mode`, the `ApprovalMode` enum
- `app/api/v1/endpoints/operator_prebooking.py` — pattern for tenant-scoped operator endpoints (auth via JWT cookie)
- `app/api/v1/endpoints/operator_properties.py` — another tenant-scoped endpoint pattern, returns property data
- The existing dashboard HTML in `operator_dashboard_v2.py` or wherever the queue page is rendered — where the UI control needs to live

## Tasks

### 1. Backend endpoints

Add to a new file `app/api/v1/endpoints/operator_approval_mode.py` (or extend `operator_properties.py` if simpler):

**POST `/app/api/properties/{property_id}/approval-mode`** — flip a single property
- Authenticated via operator JWT cookie (existing pattern in `operator_prebooking.py`)
- Tenant-scoped: resolves tenant_id from auth, never trusts request body for tenant
- Body: `{"mode": "auto" | "required"}`
- Calls `StagedRolloutService.set_approval_mode(tenant_id, property_id, mode, set_by="<operator_id>")`
- Returns: `{"ok": true, "property_id": "...", "mode": "auto", "set_at": "..."}`
- Error handling: 400 for invalid mode, 404 if property doesn't have a rollout row, 403 if operator doesn't own the property

**POST `/app/api/properties/approval-mode/bulk`** — flip multiple properties at once
- Same auth/tenant-scoping
- Body: `{"property_ids": ["...", "...", ...], "mode": "auto" | "required"}`
- Loops over property_ids calling `set_approval_mode` for each
- Returns: `{"ok": true, "updated": N, "results": [{"property_id": "...", "ok": true/false, "error": "..."}, ...]}`
- Use case: tenant-wide flip ("turn on AUTO for all 45 properties") and tenant-wide rollback ("flip everything back to REQUIRED")

**GET `/app/api/properties/approval-modes`** — read current state for the operator's properties
- Returns: `{"properties": [{"property_id": "...", "property_name": "...", "phase": "...", "approval_mode": "required" | "auto", "set_at": "...", "set_by": "..."}, ...]}`
- Used by UI to render the current state and the toggle buttons

### 2. UI control

Add to the dashboard's property list view (probably the operator dashboard sidebar or a dedicated "Properties" page):

**Per-property toggle:**
- Each property row shows its current approval mode as a clear badge ("AUTO" or "REQUIRED")
- A toggle switch next to the badge — clicking it calls the single-property endpoint
- Optimistic UI update with rollback on failure
- Success state: brief confirmation ("Auto-send enabled for Sea La Vie")
- Failure state: error message, toggle reverts

**Tenant-wide actions:**
- Two prominent buttons at the top of the properties list:
  - **"Enable auto-send for all properties"** — calls bulk endpoint with all property_ids and `mode=auto`. Confirmation modal first ("This will turn on auto-send for all 45 active properties. New inquiries will start auto-sending when confidence is high. You can flip any property back to required at any time.")
  - **"Pause auto-send for all properties"** — same bulk endpoint with `mode=required`. Confirmation modal ("This will hold all drafts for your review across all 45 properties. New inquiries will appear in your queue but won't auto-send.")

**Status panel:**
- Summary near the top of the page: "12 properties auto-sending, 33 requiring review" (counts update live as toggles change)

### 3. Audit logging

`set_approval_mode` already records the change in the rollout row. Additionally, log to a new audit table or to the existing `property_rollout_history` table whenever the mode changes via the operator UI:

```sql
INSERT INTO property_rollout_history (
    company_id, property_id, from_phase, to_phase,
    advanced_by, approval_mode, metrics_at_time, created_at
)
VALUES (
    :tid, :prop, :phase, :phase,  -- phase doesn't change, mode does
    :operator_id, :mode,
    jsonb_build_object('action', 'approval_mode_change', 'previous_mode', :prev_mode),
    NOW()
);
```

This gives us a clean audit trail of who flipped what when. Useful for diagnosing "why did this property auto-send when I expected it to hold."

### 4. Visibility in the queue UI

In the pre-booking review queue (the existing queue page), add a badge next to each inquiry showing the property's current approval mode:
- AUTO badge in amber/gold (matches the design system)
- REQUIRED badge in muted gray

Lanier should be able to see at a glance which drafts came in to AUTO properties (those drafts that exceeded confidence thresholds already auto-sent — they appear in the `replied` view rather than `pending_review`) vs which came in to REQUIRED properties (still in `pending_review`).

### 5. Tests

- Unit tests for the single-property endpoint: auth required, tenant scoping enforced, mode validation, success path, error paths
- Unit tests for the bulk endpoint: partial failures (some properties succeed, some fail) return appropriate result list
- Integration test: flip a property to AUTO, send a high-confidence inquiry to it, verify it auto-sends; flip back to REQUIRED, send another, verify it holds

## Ship criteria

- Single-property endpoint exists, tested, deployed
- Bulk endpoint exists, tested, deployed
- GET endpoint returns current state for all operator's properties
- UI shows per-property toggle and current mode badge
- UI shows tenant-wide bulk actions with confirmation modals
- Audit log captures every mode change with operator_id and timestamp
- Lanier can flip a property to AUTO in one click, sees confirmation, the next high-confidence inquiry to that property auto-sends within minutes
- Lanier can flip back to REQUIRED in one click, the next inquiry holds for review
- `OPERATOR_READINESS_ARC.md` status updated: Ship 2 → DEPLOYED → VERIFIED

## What this ship does NOT do

- Does NOT change draft quality (Ship 3)
- Does NOT add the CLARIFY action (Ship 3)
- Does NOT add the property knowledge UI (Ship 4)
- Does NOT redesign the queue review workflow (Ship 5)

Stays focused on the AUTO toggle and rollback path.

## Codex commit-message format

```
phase 4.5 ops ship 2: per-property auto toggle

- added POST /app/api/properties/{id}/approval-mode for single-property flips
- added POST /app/api/properties/approval-mode/bulk for tenant-wide actions
- added GET /app/api/properties/approval-modes for current state
- ui: per-property toggle + tenant-wide bulk actions + status panel
- audit log captures every mode change

verification:
  - single property flip: tested with property 111VW
  - bulk flip: tested with all 45 properties
  - rollback: flipped 111VW to auto, then back to required, confirmed both states
  - high-confidence inquiry to auto property: auto-sent
  - high-confidence inquiry to required property: held in queue
```
