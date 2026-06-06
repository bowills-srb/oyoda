# Brain Pre-Booking Lifecycle Primary — Replay/Regression Plan

Date: 2026-05-27
Tenant under test: Beach Habitats (`e07980b2-a990-4b24-91d1-c8cb71ab70e1`)
Status: plan only, no execution yet
Anchor: [docs/scratch/BRAIN_PREBOOKING_PRIMARY_SAFETY.md](BRAIN_PREBOOKING_PRIMARY_SAFETY.md)
Discipline: [docs/architecture/MIGRATION_DISCIPLINE.md](../architecture/MIGRATION_DISCIPLINE.md) — Principles 3 (audit before fix) and 5 (cutover completeness documented per tenant)

## Purpose

Verify that flipping `brain_prebooking_lifecycle_primary = true` for Beach
Habitats produces correct end-to-end behavior on representative real inbound
traffic, with a defined rollback procedure, before any operator-visible flip
happens.

This is the "first live rollout" risk the safety doc names: the flag exists,
the code path is implemented, but production has no tenant currently running
this exact gate enabled. Replay is how we de-risk that.

## What "primary on" actually changes

With both:

- `messaging_brain_runtime = true` (already on)
- `brain_prebooking_lifecycle_primary = true` (currently off)

the path through
[app/services/integrations/email_dispatch.py](../../app/services/integrations/email_dispatch.py)
`dispatch_pre_booking` changes from:

```
parsed → [layer1] → [gate] → [classifier] → fallback path → gmail_fallback_saved row
```

to:

```
parsed → [layer1] → [gate] → [classifier]
       → load_property_context
       → resolve_thread_identity_and_history
       → PreBookingBrainOrchestrator.handle(...)         ← LLM call(s)
       → _review_brain_pre_booking_draft(...)            ← adversarial review LLM call
       → run_brain_pre_booking_lifecycle(...)            ← canonical persistence
       → save_inquiry_from_canonical(...)                ← pre_booking_inquiries row
       → update_normalization_outcome(... pre_booking_new ...)
       → _maybe_writeback_property_resolution(...)
       → maybe_record_pre_booking_gap(...)
```

So enabling the flag changes both per-message cost (multiple LLM calls per
inbound) and per-message persistence shape (a real brain-owned draft instead
of the boilerplate hold). Both need verification.

## Confirmation: `approval_mode` is forced to "required"

Read at [app/services/integrations/email_dispatch.py:1188](../../app/services/integrations/email_dispatch.py). The dispatch passes
`force_approval_mode="required"` into `run_brain_pre_booking_lifecycle(...)`,
which means **flipping this flag does not turn on auto-send**. Every saved
draft still goes to the operator review queue. This is the safety property
that makes the flip recoverable: even if the brain produces a bad draft, no
guest ever sees it without operator review.

This is a Principle 6 requirement (hybrid states must be honest in the UI):
operators see drafts marked from the brain in the v2 Pre-Booking Held queue,
not auto-sent.

## Replay strategy

Two approaches are possible. We use both, in order.

### Approach 1 — Shadow replay (preferred, runs first)

Re-run a small set of recent Beach Habitats inquiries through the live
dispatch code *with the flag set to true for that single replay*, writing
output to a parallel inspection surface rather than mutating the real
`pre_booking_inquiries` rows. This is the safest first step.

Requirements:

- A replay harness that loads a recent `pre_booking_inquiries` row, the
  matching `message_normalizations` row, and the original parsed email
  payload (recoverable from `gmail_processed_messages` joined to message
  normalization parser notes, or the raw Gmail message if the
  `gmail_message_id` is still pollable).
- Re-instantiate the parsed message object with the original metadata.
- Invoke `dispatch_pre_booking` with the brain-lifecycle-primary flag
  overridden to true *for that replay session only*.
- Write the resulting draft + persistence output to a shadow table or
  log file, not the live `pre_booking_inquiries` row.

If a clean shadow harness doesn't exist yet, codex should propose one in
a follow-up doc before writing replay code. Do not improvise a replay
harness that writes to live tables.

Implemented harness: [scripts/replay_brain_prebooking_primary.py](/Users/dhuntermckenzie/Downloads/oyvoda/scripts/replay_brain_prebooking_primary.py)
now performs this shadow replay by:

- loading a real `pre_booking_inquiries` + `message_normalizations` source
- cloning it to a shadow `source_message_id`
- seeding a shadow normalization row
- forcing `brain_prebooking_lifecycle_primary = true` for that replay only
- calling the real `dispatch_pre_booking(...)` seam
- capturing the shadow inquiry/normalization result
- rolling the DB transaction back

This is the canonical Phase 1 execution path. It does not create a second
pre-booking pipeline.

Current harness nuance from the first live replay: the authoritative result
is the captured `brain_lifecycle_result` plus the final normalization
attempt emitted by the canonical functions during replay. The seeded shadow
`message_normalizations` row did not survive the full replay path on the
first run, so the harness records those in-memory seam outputs directly
instead of depending on the shadow audit row being queryable at the end.

### Approach 2 — Limited live flip with monitored window (if shadow replay passes)

If Approach 1 passes for all 3-5 selected cases, flip the flag for Beach
Habitats only with an explicit observation plan:

- Flag flipped at a known timestamp, recorded in this doc
- All new pre-booking inbounds for Beach Habitats are watched in real time
  for the first 2 hours
- Production `message_normalizations` table is queried every 30 minutes
  during the watch window for the verification criteria below
- If any criterion fails on a real inbound, flip the flag back immediately

The observation window is 24-48 hours of normal inbound traffic.

## Selection criteria for replay cases

Pick 3-5 Beach Habitats inquiries with the following distribution. Codex
selects actual `draft_id` values from production matching these criteria.

| Case | Shape | Why it's needed |
|------|-------|-----------------|
| 1 | Pre-booking inquiry with clean property binding, plain availability question, currently `gmail_fallback_saved` | Baseline — the easy case. If this doesn't produce a clean brain draft, the flag is not ready. |
| 2 | Pre-booking inquiry with property binding via `48SWC` style unit code, recent (last 7 days) | Confirms the OTA parser path still produces a parsed object the brain can consume. |
| 3 | Pre-booking inquiry currently in `confidence_source = gap_blocked` (Spooky Lane class) | Tests whether the new path's intent classification + KB retrieval actually skip the date-gap-block when intent is `access` or similar. This is the Phase 3 verification, embedded here as one replay case. |
| 4 | Pre-booking inquiry with `missing_property_binding` outcome — i.e. unbound | Confirms the brain handles the unbound case without crashing and produces a draft tagged for operator binding rather than confidently composing against the wrong property. |
| 5 | Pre-booking inquiry that is currently `pre_booking_duplicate` (already deduped) | Confirms dedup behavior is preserved under the new path. |

If a case in 3 or 5 doesn't exist in recent history, drop it rather than
fabricating one. 3 real cases beat 5 contrived ones.

## SQL to source replay candidates

Each query returns candidates; codex picks one per case after spot-checking
the row contents look representative.

### Case 1 — clean fallback baseline

```sql
SELECT
    draft_id,
    received_at,
    guest_name,
    property_external_id,
    LEFT(message_text, 200) AS message_preview,
    intent,
    confidence,
    confidence_source,
    draft_source
FROM pre_booking_inquiries
WHERE company_id = 'e07980b2-a990-4b24-91d1-c8cb71ab70e1'
  AND draft_source = 'gmail_fallback_saved'
  AND property_external_id IS NOT NULL
  AND property_external_id <> ''
  AND received_at > NOW() - INTERVAL '14 days'
  AND message_text NOT ILIKE '%gate code%'
  AND message_text NOT ILIKE '%check%in%'
ORDER BY received_at DESC
LIMIT 10;
```

### Case 2 — OTA-parsed unit code

```sql
SELECT
    p.draft_id,
    p.received_at,
    p.guest_name,
    p.property_external_id,
    p.parser_source,
    LEFT(p.message_text, 200) AS message_preview,
    n.parser_used,
    n.route_outcome
FROM pre_booking_inquiries p
LEFT JOIN message_normalizations n
       ON n.tenant_id = p.company_id
      AND n.source_message_id = p.gmail_message_id
WHERE p.company_id = 'e07980b2-a990-4b24-91d1-c8cb71ab70e1'
  AND p.parser_source ILIKE 'ota_parser_%'
  AND p.property_external_id IS NOT NULL
  AND p.received_at > NOW() - INTERVAL '7 days'
ORDER BY p.received_at DESC
LIMIT 10;
```

### Case 3 — gate-blocked / Spooky-class

```sql
SELECT
    draft_id,
    received_at,
    guest_name,
    property_external_id,
    LEFT(message_text, 300) AS message_preview,
    intent,
    confidence_source
FROM pre_booking_inquiries
WHERE company_id = 'e07980b2-a990-4b24-91d1-c8cb71ab70e1'
  AND confidence_source = 'gap_blocked'
  AND received_at > NOW() - INTERVAL '30 days'
ORDER BY received_at DESC
LIMIT 10;
```

### Case 4 — unbound inquiry

```sql
SELECT
    draft_id,
    received_at,
    guest_name,
    property_external_id,
    LEFT(message_text, 200) AS message_preview,
    intent,
    draft_source
FROM pre_booking_inquiries
WHERE company_id = 'e07980b2-a990-4b24-91d1-c8cb71ab70e1'
  AND (property_external_id IS NULL OR property_external_id = '')
  AND received_at > NOW() - INTERVAL '14 days'
ORDER BY received_at DESC
LIMIT 10;
```

### Case 5 — recent duplicate

```sql
SELECT
    draft_id,
    received_at,
    guest_name,
    property_external_id,
    LEFT(message_text, 200) AS message_preview
FROM pre_booking_inquiries
WHERE company_id = 'e07980b2-a990-4b24-91d1-c8cb71ab70e1'
  AND status IN ('duplicate', 'archived')
  AND received_at > NOW() - INTERVAL '14 days'
ORDER BY received_at DESC
LIMIT 10;
```

## Verification criteria

For each replay case, the following must all be true:

### Persistence

1. A `pre_booking_inquiries` row is produced (real or shadow, per approach).
2. `draft_source` is `messaging_brain` (or whatever the brain-owned source
   tag is — confirm against `prebooking_inquiry_store` constants), not
   `gmail_fallback_saved`.
3. `status = pending_review` (because `approval_mode = required` is forced).
4. `confidence` is populated with a real numeric value, not 0.0.
5. `confidence_source` is a brain-pathway value (e.g. `messaging_brain`,
   `faq_fast_path`, `gate_code_intercept`), not `fallback_placeholder`.

### Routing outcome

6. `message_normalizations.route_outcome` is `pre_booking_new` (or
   `pre_booking_duplicate` for Case 5), not `pre_booking_fallback`.
7. `message_normalizations.fallback_reason` does not contain
   `brain_runtime_not_primary`.

### Draft quality (manual review by Hunter)

8. The composed draft is grounded in the property data, not a generic
   placeholder.
9. The draft tone matches Beach Habitats' operator voice.
10. The draft does not contain "{{...}}" or "[PLACEHOLDER]" patterns
    (the defensive placeholder guard should have already caught these,
    but verify).

### No crashes or exceptions

11. No `RuntimeError` or `Exception` logged during the replay.
12. No `brain_exception` warning in the resulting row.
13. The adversarial reviewer ran (look for `adversarial_review:` in
    `policy_warnings`).

### Case-specific criteria

For **Case 3 (gate-blocked / Spooky)**:
- The new path should produce a real draft, not a "what dates are you
  considering" deflection.
- If the guest message is about gate codes or check-in timing, the
  classified intent should be `access` or similar, not `availability`.
- The brain should consult property KB (look for non-empty
  `used_kb_chunks` indicator).
- If the brain still cannot answer (legitimate gap), it should hold for
  review rather than fall back to the generic boilerplate.

For **Case 4 (unbound)**:
- The replay should not crash on missing property context.
- The resulting draft should either be empty (held for review) or
  explicitly flagged as needing operator binding.
- It should NOT confidently compose against an arbitrary property.

For **Case 5 (duplicate)**:
- Dedup logic still fires — the replay should produce
  `route_outcome = pre_booking_duplicate`, not a fresh inquiry.

### Cost observation

14. Track LLM cost per replayed message (intake classifier + brain compose
    + reviewer = roughly 3 LLM calls per inbound).
15. Cost per message should be in the $0.005 - $0.05 range depending on
    which models fire. Anything higher than $0.10 per message is a red
    flag worth investigating.

This depends on the Phase 4 LLM instrumentation work being complete. If
not, observe via raw provider API logs.

## Pass / fail decision rubric

| Result | Decision |
|--------|----------|
| All 5 cases pass criteria 1-13, no crashes, costs in range | **Go.** Proceed to Approach 2 (limited live flip with monitored window). |
| 4 of 5 cases pass, one case has a subtle quality issue (e.g. tone, minor draft awkwardness) | **Conditional go.** Document the issue, decide whether to flip or improve the brain composer first. |
| Any case crashes, any case produces a placeholder-pattern draft, any case bypasses the adversarial reviewer | **No-go.** Investigate the failure, fix, re-replay. |
| Case 3 (gate-blocked) still produces an `availability` classification | **Partial go possible.** The Spooky-class fix is Phase 3 work; the flip can still proceed for the other classes if Cases 1, 2, 4, 5 pass. Document the limitation. |
| LLM cost per message exceeds $0.10 average | **Investigate before flipping.** Cost runaway risk is real at scale. |

## Rollback procedure

If the flag is flipped (Approach 2) and any of the following happens during
the 24-48 hour observation window:

- New error-level logs containing `brain_exception` or `RuntimeError` from
  pre-booking dispatch
- Any saved `pre_booking_inquiries` row with `status = save_failed`
- Operator reports a draft that confidently states wrong property facts
- LLM cost per message spikes above $0.10 sustained over an hour
- Any visible regression in operator workflow

Rollback steps:

1. Set `brain_prebooking_lifecycle_primary = false` for Beach Habitats in
   `operator_feature_flags`.
2. Confirm via flag read that the value persists.
3. Send one test inbound (if controllable) or wait for next real inbound
   to confirm it falls back to `gmail_fallback_saved` again.
4. Document the rollback timestamp, the trigger condition, and the failing
   replay/observation case in this doc.

The flag flip is one DB row update. The rollback is the same row updated
back. No code deployment is involved.

## Rollout doc update

Once the flag is flipped successfully and verified, update
[docs/MESSAGING_BRAIN_PREBOOKING_BEACH_HABITATS_ROLLOUT.md](../MESSAGING_BRAIN_PREBOOKING_BEACH_HABITATS_ROLLOUT.md)
to reflect:

- Current Beach Habitats flag state including
  `brain_prebooking_lifecycle_primary = true`
- The timestamp of the flip
- The verification artifact (this doc, with the populated replay results
  table)
- The rollback procedure (link to this section)

This is the Principle 5 requirement: cutover state documented per tenant
with the verification artifact attached.

## Open questions / decisions for Hunter

1. **Shadow harness vs limited live flip.** Approach 1 (shadow harness)
   requires building a harness if one doesn't exist. Approach 2 (limited
   live flip with rollback) is faster to start but means real operator
   review queue is affected during the window. Which order?
2. **Case 3 prioritization.** If the Spooky-class case fails replay but
   the others pass, do we flip anyway with documented limitation, or hold
   the flip until Phase 3 fix lands first?
3. **Cost budget.** What's the per-message cost ceiling that triggers
   investigation? The plan suggests $0.10 — confirm or adjust.

## Status

This doc is now **partially executed**. The harness exists and one live
shadow replay has been run; the tenant flag is still off.

First executed replay:

- Source case: `INQ-6220E2F5` (`tela hurt`, `48SWC`)
- Dispatch outcome: `pre_booking_new`
- Brain lifecycle result:
  - `save_status = saved`
  - `draft_source = messaging_brain`
  - `intent = pricing`
  - `confidence = 0.85`
  - `approval_mode = required`
- Final normalization attempt:
  - `route_outcome = pre_booking_new`
  - `draft_source = messaging_brain`
  - no `brain_runtime_not_primary` fallback

Open issue from that replay:

- The shadow `message_normalizations` row was not queryable at the end of
  replay, even though the canonical normalization update attempts fired.
  This is a harness/audit-surface issue, not evidence that the brain
  lifecycle seam itself failed. The cutover seam produced a saved
  brain-owned draft.

Second executed replay:

- Source case: `INQ-REPLAY-19E50030` (`100SL2D`, Spooky gate-code class)
- Original historical shape:
  - `route_outcome = pre_booking_saved`
  - `confidence_source = gap_blocked`
  - `blocked_by_gap_topics` included `requested_dates`
- Replay result under forced lifecycle-primary:
  - `dispatch_outcome = pre_booking_new`
  - `save_status = saved`
  - `draft_source = messaging_brain`
  - `intent = check_in_process`
  - `confidence = 0.85`
  - `approval_mode = required`
- Final normalization attempt:
  - `route_outcome = pre_booking_new`
  - `draft_source = messaging_brain`
  - no `brain_runtime_not_primary` fallback

Interpretation:

- The cutover seam did not reintroduce the old Spooky failure mode.
- The replay routed to an access/check-in specialist shape instead of the
  old `booking_inquiry -> requested_dates` hold path.
- The draft still needed review and adversarial revision, but it was a real
  brain-owned held draft on the canonical path, not a fallback placeholder.

Next concrete step: select the 3-5 candidate cases and run
`scripts/replay_brain_prebooking_primary.py` for each one. If those
shadow replays pass, move to the monitored live flip in Approach 2 and
populate this doc with the actual results before the flag flips.
