# Messaging Brain Pre-Booking Lifecycle Primary -- Beach Habitats Rollout

Operational doc for enabling the pre-booking brain lifecycle primary cutover
for Beach Habitats in review-required mode.

Authored Session 14. Update in place if rollout conditions, metrics, or
rollback procedures change.

## Scope

This doc covers Beach Habitats only:

- `company_id = e07980b2-a990-4b24-91d1-c8cb71ab70e1`
- lane = pre-booking only
- mode = review-required only

This rollout enables the pre-booking brain lifecycle path in
`dispatch_pre_booking(...)`, where
`brain_prebooking_lifecycle_primary` is now the lane-specific ownership
switch. `messaging_brain_runtime` may still be enabled more broadly for
other messaging-brain surfaces, but pre-booking lifecycle dispatch no
longer requires both overlapping flags to be true in order to enter
`PreBookingBrainOrchestrator().handle(...)` and
`run_brain_pre_booking_lifecycle(...)` with
`force_approval_mode="required"`.

This doc does not cover:

- post-booking, pre-arrival, in-stay, or post-stay brain runtime
- autonomous-send progression
- OTA inquiry identity unification with booked-stay identity
- rejection-reason capture (the reject endpoint has no reason field)

## Prerequisites

The following shipped state is assumed before cutover:

- `d3e71d6` -- rich-context rollout doc
- `74e2a3e` -- `scripts/run_feature_flag.py`
- `c81d88e` -- `scripts/rich_context_shadow_analysis.sql`
- `f17b9ea` -- pre-booking brain drafts surface as review-ready

Current production state before this cutover:

- Beach Habitats already had `messaging_brain_runtime = true`
- Beach Habitats already had `messaging_brain_llm_intake = true`
- Beach Habitats did **not** yet have
  `brain_prebooking_lifecycle_primary = true`
- no tenant override existed for `brain_prebooking_lifecycle_primary`,
  so the code intentionally fell back to `brain_runtime_not_primary`
- after the cutover, pre-booking dispatch was tightened so
  `brain_prebooking_lifecycle_primary` itself is the lane-specific gate,
  reducing drift from the previous two-flag overlap

## Enablement

Enablement is one company-scoped row in `operator_feature_flags`:

- `flag_name = 'brain_prebooking_lifecycle_primary'`
- `company_id = 'e07980b2-a990-4b24-91d1-c8cb71ab70e1'`
- `property_code = NULL`
- `enabled = TRUE`

This matches the upsert shape used by
`FeatureFlagService._set_flag(...)`.

Replace `<operator>` below with the actual operator identifier
(email or username) running the cutover.

```sql
INSERT INTO operator_feature_flags
    (id, company_id, property_code, flag_name, enabled,
     enabled_at, enabled_by, notes, created_at)
VALUES
    (gen_random_uuid(),
     'e07980b2-a990-4b24-91d1-c8cb71ab70e1',
     NULL,
     'brain_prebooking_lifecycle_primary',
     TRUE,
     NOW(),
     '<operator>',
     'Phase 1 cutover: Beach Habitats brain pre-booking lifecycle primary enabled',
     NOW())
ON CONFLICT (company_id, property_code, flag_name)
DO UPDATE SET
    enabled = EXCLUDED.enabled,
    enabled_at = EXCLUDED.enabled_at,
    enabled_by = EXCLUDED.enabled_by,
    notes = EXCLUDED.notes;
```

This flag is not currently exposed through
[scripts/run_feature_flag.py](/Users/dhuntermckenzie/Downloads/oyvoda/scripts/run_feature_flag.py),
so the operational path is a direct upsert with immediate read-back.

## Live Cutover Record

Cutover completed:

- Timestamp: `2026-05-27 23:26:23 UTC`
- Tenant: `e07980b2-a990-4b24-91d1-c8cb71ab70e1`
- Flag: `brain_prebooking_lifecycle_primary = true`
- Enabled by: `codex`

Read-back after write:

- `company_id = e07980b2-a990-4b24-91d1-c8cb71ab70e1`
- `property_code = NULL`
- `flag_name = brain_prebooking_lifecycle_primary`
- `enabled = true`
- `enabled_at = 2026-05-27 23:26:23.586134+00`

Replay artifacts tied to this cutover:

- [docs/scratch/BRAIN_PRIMARY_REPLAY_PLAN.md](/Users/dhuntermckenzie/Downloads/oyvoda/docs/scratch/BRAIN_PRIMARY_REPLAY_PLAN.md)
- `INQ-6220E2F5` (`tela hurt`) replay:
  - `dispatch_outcome = pre_booking_new`
  - `save_status = saved`
  - `draft_source = messaging_brain`
  - `intent = pricing`
  - `approval_mode = required`
- `INQ-REPLAY-19E50030` (Spooky gate-code class) replay:
  - `dispatch_outcome = pre_booking_new`
  - `save_status = saved`
  - `draft_source = messaging_brain`
  - `intent = check_in_process`
  - `approval_mode = required`

## Acknowledged Side Effect

Beach Habitats already has `MESSAGING_BRAIN_RICH_CONTEXT_SHADOW` on. As
soon as `messaging_brain_runtime` is enabled for the pre-booking lane,
`rich_context_shadow_observations` will begin populating for traffic
that enters the brain.

This is verified safe. In
[context_builder_agent.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/messaging_brain/agents/context_builder_agent.py:133),
when rich-context is shadow-on but not production-on, the system
computes richness/evidence/preferences, writes a shadow observation row,
and then returns empty rich-context values so production behavior is
unchanged.

This side effect is observational only. It does not alter the draft text
path by itself.

## Metrics

Session 14 tracks review-mode signal only. It does not attempt to decide
autonomous readiness.

The source of truth is:

- `pre_booking_inquiries` for queue state
- `message_normalizations` for `draft_source` attribution
- `operator_draft_events` for behavioral metrics (approval, edit,
  rejection, and time-to-decision)

Metrics to track:

1. Approval rate: `pending_review -> replied` without operator edit for
   brain-sourced drafts.
2. Edit rate and edit magnitude: how often operators edit brain drafts,
   and how large those edits are.
3. Rejection rate: `pending_review -> rejected` for brain drafts.
4. Time-to-decision: `replied_at - received_at` for brain drafts vs.
   legacy drafts.
5. Brain-branch failure rate: cases where runtime is enabled but the
   brain branch falls back to the legacy pre-booking path after an
   exception.

Metrics SQL belongs in
`scripts/prebooking_review_metrics.sql`. This doc names the metrics and
their meaning; the SQL artifact is the durable rerunnable analysis tool.

## How To Verify Cutover Succeeded

Within the first hour after enabling
`brain_prebooking_lifecycle_primary`, verify
all three of these:

1. A new row appears in `pre_booking_inquiries` with
   `status = 'pending_review'`.
2. The corresponding `message_normalizations` row has
   `draft_source = 'messaging_brain'`.
3. A new row appears in `rich_context_shadow_observations` with
   `tenant_id = 'e07980b2-a990-4b24-91d1-c8cb71ab70e1'`.

Interpretation:

- If all three are true, pre-booking brain runtime is live and producing
  observable signal.
- If `pre_booking_inquiries` fills but
  `rich_context_shadow_observations` does not, check production logs for
  the fallback path:
  `[EmailDispatch] Brain pre-booking draft failed, saving fallback instead`
- If no new `pre_booking_inquiries` rows appear, either no qualifying
  traffic has arrived yet or the lane is not being entered.

## Verification Record

Verification completed on `2026-05-28` using direct table queries against
`pre_booking_inquiries`, `message_normalizations`, and
`rich_context_shadow_observations` rather than the queue service.

Confirmed:

1. A new Beach Habitats row appeared in `pre_booking_inquiries` after the
   cutover with `status = 'pending_review'`.
2. The corresponding `message_normalizations` row had
   `source_channel = 'email'`, `draft_source = 'messaging_brain'`, and
   `route_outcome = 'pre_booking_new'`.
3. A corresponding `rich_context_shadow_observations` row existed for the
   same tenant/message window.

Result:

- Phase 1 cutover is verified healthy.
- Remaining operator-dashboard degradation after the cutover was traced to
  the queue reader's stale `source_channel = 'gmail'` join and fixed in
  commit `ccfd1d9`.
- Beach Habitats pre-booking remains on the brain lifecycle primary path in
  review-required mode.

## Watch Window

The first watch window is:

- first 2 hours for active cutover confirmation, then
- first 50 brain drafts, or
- first 7 days,

whichever comes first.

During this window:

- do not broaden scope beyond pre-booking
- do not discuss autonomous mode as a rollout decision
- Hunter reviews metrics daily by running
  `scripts/prebooking_review_metrics.sql`

Immediate cutover confirmation checks for the first 2 hours:

1. New Beach Habitats inbound rows show `draft_source = messaging_brain`.
2. New rows remain `status = pending_review` because approval remains forced.
3. New rows have non-zero `confidence`.
4. No `brain_exception:*` fallback reasons appear for new Beach Habitats
   pre-booking traffic.

Session 15 verification concluded that the lane is healthy enough to proceed
to the next workstream. Ongoing observation continues through normal metrics
review; no rollback was required.

## Rollback

Rollback is the same company-scoped flag primitive used for enablement:

- set `brain_prebooking_lifecycle_primary = FALSE` for
  `company_id = e07980b2-a990-4b24-91d1-c8cb71ab70e1`

Operational notes:

1. Feature-flag cache TTL is 300 seconds. Rollback takes effect across
   workers as caches expire.
2. The fallback branch is still recoverable and still review-required.
   Rolling this flag back returns Beach Habitats to the
   `brain_runtime_not_primary` compatibility path.
3. If queue burden, draft quality, or operator trust degrades, disable
   runtime first and inspect metrics second.
4. For sub-300-second rollback, the feature-flag cache can be cleared
   programmatically via `_cache.clear()`, but no admin endpoint exists
   for this today. See Known Debt.

`messaging_brain_runtime` and `messaging_brain_llm_intake` do not need
to be changed as part of this rollback. This procedure is specifically
for the lifecycle-primary cutover seam, which is now the authoritative
pre-booking lifecycle switch for this lane.

## Explicit Non-Goals

The following are out of scope for Session 14:

- deciding if Beach Habitats is ready for autonomous send
- adding rejection reasons to the operator API
- adding a fast cache-clear primitive for sub-5-minute rollback
- enabling post-booking or in-stay messaging brain runtime

## Known Debt

Several items below are also listed under Non-Goals. Non-Goals means
"out of scope this session"; Known Debt means "worth doing later."
Items appearing in both sections are deliberate cross-references.

- `draft_source = 'messaging_brain'` is a string literal duplicated
  across the pre-booking runtime chain. Today it is emitted in
  `email_dispatch.py`, encoded into policy warnings in
  `pre_booking_auto_send.py`, parsed back out in
  `operator_prebooking.py`, and matched again in the
  review-ready helper. Promote this to a shared constant or enum before
  broader rollout to avoid silent drift.
- Rejection reasons are not captured today. Rejection rate is
  measurable, but rejection intent is not.
- Fast cache-clear for emergency rollback is possible only through
  programmatic `_cache.clear()` or worker restart. No operator-facing
  endpoint exists.
- Brain-branch failure rate is currently log-derived from
  `[EmailDispatch] Brain pre-booking draft failed, falling back to legacy path`.
  If this becomes a durable rollout metric, promote it into a structured
  DB or read-model field in a later session.
- `prebooking_queue_service.py` currently joins `message_normalizations`
  on `source_channel = 'gmail'` while the email dispatch path writes
  `source_channel = 'email'`. Either the queue service reads through a
  different write path or it is silently missing rows. Verify and
  reconcile in a later session.
