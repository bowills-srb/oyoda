# Phase 4.5.F — Brain pre-booking lifecycle cutover

Date: 2026-05-20  
Phase: 4.5.F

## Decision

After 4.5.E, the remaining hybrid seam is no longer about individual draft
capabilities. It is about lifecycle ownership.

Today the live pre-booking runtime does this:

1. `email_dispatch.py` decides pre-booking applies
2. when `MESSAGING_BRAIN_RUNTIME` is on, it calls
   `PreBookingBrainOrchestrator().handle(...)`
3. the resulting Brain draft is then handed back into legacy
   `process_pre_booking_inquiry_with_draft(...)`
4. legacy `PreBookingPipelineOrchestrator.persist_and_dispatch(...)` still owns:
   - queue persistence
   - operator alerts
   - timeout-send scheduling
   - final transport send

Phase 4.5.F cuts that seam. The Brain becomes the owner of the full
pre-booking lifecycle after draft generation, while preserving the existing
operator-facing table and path-agnostic send/alert helpers.

This is the orchestrator cutover phase named in
[LEGACY_RETIREMENT_PLAN.md](/Users/dhuntermckenzie/Downloads/oyvoda/docs/architecture/LEGACY_RETIREMENT_PLAN.md).
It is not a dashboard ship and it is not a queue redesign.

## What 4.5.F migrates

Per the retirement plan, 4.5.F covers three remaining legacy areas:

1. pipeline orchestration
2. persistence to `pre_booking_inquiries`
3. operator alerts and timeout-send scheduling

Concretely, these are the remaining legacy-owned runtime seams:

- `process_pre_booking_inquiry(...)`
- `process_pre_booking_inquiry_with_draft(...)`
- `PreBookingPipelineOrchestrator`
- `persist_and_dispatch(...)`
- `_save_inquiry` / `_insert_pre_booking_inquiry`
- `_alert_operator_for_review(...)`
- `_schedule_timeout_send(...)`
- `_log_required_mode_event(...)`
- `_send_via_escapia(...)` as called from the legacy orchestrator

The goal is not to rewrite every helper immediately. The goal is to make the
Brain the sole caller and lifecycle owner.

## Runtime truth this brief targets

As of 4.5.E, production pre-booking is:

- Brain-owned for:
  - intake bridge
  - policy bridge
  - composer bridge
  - knowledge-gap bridge
- legacy-owned for:
  - lifecycle shell after draft generation
  - persistence call site
  - operator review alerting
  - timeout-send scheduling
  - final send dispatch

The most important call site is in
[email_dispatch.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/integrations/email_dispatch.py):

- with `MESSAGING_BRAIN_RUNTIME=ON`, the runtime still does:
  - `PreBookingBrainOrchestrator().handle(...)`
  - `_review_brain_pre_booking_draft(...)`
  - `process_pre_booking_inquiry_with_draft(...)`

That last handoff is the seam 4.5.F removes.

## New runtime shape

### New primary flag

- `BRAIN_PREBOOKING_LIFECYCLE_PRIMARY`

Behavior:

- when `OFF`:
  - keep the current hybrid shape
  - Brain draft still feeds into legacy
    `process_pre_booking_inquiry_with_draft(...)`
- when `ON`:
  - `email_dispatch.py` no longer hands Brain output back into legacy
  - a Brain-owned lifecycle path persists the inquiry, decides send-vs-hold,
    dispatches operator alerts, schedules timeout sends, and returns the
    same result contract the caller expects today

This matches the proven migration pattern:

- one narrow primary flag
- one entrypoint seam moved
- no dashboard/product redesign bundled into the cutover

### New Brain lifecycle module

Recommended file:

- `app/services/messaging_brain/pre_booking_lifecycle.py`

This module should own the post-draft lifecycle for Brain pre-booking flows.
Suggested responsibilities:

- take normalized inbound + existing `PreBookingDraftResult` + review metadata
- persist to `pre_booking_inquiries`
- send immediately when approved
- alert operator when held/reviewed
- schedule timeout auto-send when applicable
- adapt to the same result shape currently returned by legacy pre-booking only
  at the caller boundary when needed

This should not be a giant copy-paste of `PreBookingPipelineOrchestrator`.
The 4.5.A-E work already moved most *decision* logic into Brain-owned agents.
4.5.F should therefore be mostly:

- lifecycle assembly
- persistence ownership
- side-effect ownership

## Existing code to reuse, not redesign

4.5.F should aggressively reuse path-agnostic pieces that already exist:

- `save_inquiry_from_canonical(...)`
  - already points at invariant-enforcing persistence
  - do not reintroduce a second custom row writer
- `save_inquiry_from_canonical(...)`'s underlying canonical write seam
  - this is already more canonical than `_save_inquiry`
- `_send_via_escapia(...)`
  - transport helper can stay where it is in this phase if needed
- `_alert_operator_for_review(...)`
  - path-agnostic helper can stay where it is in this phase if needed
- `_schedule_timeout_send(...)`
  - path-agnostic helper can stay where it is in this phase if needed
- `_log_required_mode_event(...)`
  - can stay a utility if Brain becomes its caller

Verified reuse status:

- `save_inquiry_from_canonical(...)` is already a thin canonical write seam.
  It does not depend on `PreBookingPipelineOrchestrator` instance state.
- `_send_via_escapia(...)` is callable via explicit arguments only
  (`api_key`, `thread_id`, `reply_text`, `draft_id`, optional `db`) and has no
  hidden orchestrator coupling.
- `_alert_operator_for_review(...)` is callable via explicit arguments only and
  has no hidden dependency on legacy orchestrator instance state.
- `_schedule_timeout_send(...)` and `_log_required_mode_event(...)` are likewise
  explicit-argument helpers with no hidden `self.request` or legacy instance
  coupling.

So the reuse claim in this brief is not speculative: these helpers may still
live in legacy-home modules today, but they are already callable from a Brain
lifecycle context without first extracting hidden orchestrator state.

## Review-step seam

`_review_brain_pre_booking_draft(...)` currently lives in
`email_dispatch.py`, and that is intentional for 4.5.F.

Current role:

- it runs immediately after `PreBookingBrainOrchestrator().handle(...)`
- it performs adversarial review / placeholder defense
- it produces the reviewed draft text plus additive flags/warnings that are
  then threaded into the lifecycle result

Decision for 4.5.F:

- keep `_review_brain_pre_booking_draft(...)` at the dispatch boundary
- treat it as a pre-lifecycle review shim, not as part of the lifecycle
  cutover itself

Why:

- the 4.5.F seam we are cutting is Brain draft -> legacy lifecycle wrapper
- moving the review shim at the same time would create a second cut point and
  make it harder to tell whether regressions belong to review movement or
  lifecycle movement

Follow-up note:

- once 4.5.F is stable, a later cleanup ship can decide whether
  `_review_brain_pre_booking_draft(...)` belongs in a Brain-side review module
  instead of `email_dispatch.py`

The migration principle here is:

- move *ownership and call sites* first
- move helper homes later only if they are still legacy-shaped after the cutover
- reuse existing Brain-native contracts; add only a thin compatibility adapter
  at the `email_dispatch.py` boundary when the caller still expects a dict

## Scope

### Deliverable 1 — Brain lifecycle result contract

Do not create a second Brain result vocabulary.

4.5.F must reuse the Brain-native contracts that already exist:

- `PreBookingDraftResult`
- `RecommendedAction`
- the existing Brain draft / policy outputs that already feed them

What 4.5.F adds is a lifecycle wrapper that **consumes** those existing
contracts and performs persistence/send/alert side effects.

If `email_dispatch.py` still needs the legacy dict-shaped return payload, the
Brain lifecycle path may add a thin compatibility adapter at the boundary that
translates from existing Brain-native objects into that dict shape. That is
acceptable because it is a caller shim, not a new Brain contract.

It must preserve the caller-visible fields the existing runtime already uses at
the `email_dispatch.py` boundary:

- `saved`
- `save_status`
- `save_error_type`
- `save_error_message`
- `guest_thread_id`
- `draft_id`
- `draft_text`
- `draft_source`
- `intent`
- `confidence`
- `decision`
- `sent`
- `approval_mode`
- `policy_flags`
- `policy_warnings`
- `message_id`
- `thread_id`

This is important because `email_dispatch.py` and downstream storage/update
logic already expect this shape.

Explicit non-goal:

- do not define a parallel Brain-only `Result`, `Decision`, or `Action`
  vocabulary that duplicates `PreBookingDraftResult` / `RecommendedAction`

### Deliverable 2 — Brain-owned persistence

Move the post-draft persistence call site out of legacy
`persist_and_dispatch(...)` and into the Brain lifecycle path.

Acceptance target:

- the Brain lifecycle path becomes the caller of
  `save_inquiry_from_canonical(...)`
- the legacy `persist_and_dispatch(...)` is no longer in the live Brain-on
  runtime path

This does **not** require deleting `_save_inquiry` in the same commit.
Deletion happens after the cutover is verified.

### Deliverable 3 — Brain-owned send / alert / timeout lifecycle

Move ownership of these side effects into the Brain lifecycle path:

- immediate send
- operator review alert
- timeout-send scheduling
- required-mode audit event

The helpers may remain where they are if needed, but the Brain lifecycle path
must become their caller.

### Deliverable 4 — Email dispatch seam cut

Change the runtime branch in `email_dispatch.py` so that when:

- `MESSAGING_BRAIN_RUNTIME=ON`
- `BRAIN_PREBOOKING_LIFECYCLE_PRIMARY=ON`

the code path is:

1. `PreBookingBrainOrchestrator().handle(...)`
2. `_review_brain_pre_booking_draft(...)`
3. Brain lifecycle execution
4. result returned to `email_dispatch.py`

and **not**:

1. `PreBookingBrainOrchestrator().handle(...)`
2. `_review_brain_pre_booking_draft(...)`
3. `process_pre_booking_inquiry_with_draft(...)`

That is the cutover.

### Deliverable 5 — Legacy path remains fallback-safe

When `BRAIN_PREBOOKING_LIFECYCLE_PRIMARY=OFF`, the current hybrid runtime must
continue to work exactly as it does today.

This gives the cutover a one-click rollback independent of the earlier Brain
flags.

## Acceptance criteria

### Lifecycle ownership

- A Brain-owned pre-booking lifecycle module exists.
- The Brain lifecycle module owns the post-draft lifecycle for Brain-on
  pre-booking traffic.
- The Brain lifecycle module consumes existing Brain-native contracts
  (`PreBookingDraftResult`, `RecommendedAction`) rather than defining parallel
  ones.
- The result contract returned to `email_dispatch.py` remains compatible with
  today’s caller expectations.

### Entry seam

- A new feature flag `BRAIN_PREBOOKING_LIFECYCLE_PRIMARY` exists.
- With the flag `OFF`, `email_dispatch.py` still hands Brain drafts into
  `process_pre_booking_inquiry_with_draft(...)`.
- With the flag `ON`, `email_dispatch.py` no longer calls
  `process_pre_booking_inquiry_with_draft(...)` for the Brain runtime path.

### Persistence

- With the flag `ON`, Brain pre-booking runtime persists via the canonical
  write seam and writes to `pre_booking_inquiries`.
- `guest_thread_id` threading remains intact; no regression to dual-resolution
  identity behavior.
- The operator-facing queue still reads the same table and same row shape.

### Side effects

- With the flag `ON`, Brain lifecycle path:
  - sends immediately on `SEND_NOW`
  - alerts operator on `REVIEW` / `HOLD`
  - schedules timeout auto-send when policy allows
  - emits required-mode audit event when applicable
- With the flag `OFF`, legacy behavior remains unchanged.

### Regression / parity

- Focused regression tests prove that Brain lifecycle primary `ON` and `OFF`
  both return compatible result payloads for the same input shape.
- At least one Brain-on pre-booking case with immediate send is covered.
- At least one Brain-on pre-booking case with knowledge-gap hold is covered.
- At least one Brain-on pre-booking case with review alert scheduling is
  covered.
- If a real Beach Habitats pre-booking result fixture already exists in the
  test corpus, use it here; otherwise use the same style of targeted seam tests
  used in 4.5.A-E and capture the real-fixture follow-up in the brief notes.

### Documentation

- `LEGACY_RETIREMENT_PLAN.md` is updated so 4.5.F moves from
  `LEGACY-ACTIVE` to `MIGRATING`
- the current bridge is documented explicitly:
  - old path: Brain draft -> legacy lifecycle wrapper
  - new path: Brain draft -> Brain lifecycle wrapper

## Files anticipated to change

- `app/services/feature_flags.py`
- `app/services/integrations/email_dispatch.py`
- `app/services/messaging_brain/pre_booking_lifecycle.py` (new)
- `app/services/messaging_brain/pre_booking.py`
- optionally `app/services/concierge/pre_booking_auto_send.py`
  - only to narrow or isolate compatibility helpers, not to deepen the seam
- tests:
  - `tests/unit/test_email_dispatch_prebooking_brain.py`
  - new focused lifecycle tests, likely
    `tests/unit/test_prebooking_brain_lifecycle.py`
  - optionally targeted persistence contract tests if needed
- `docs/architecture/LEGACY_RETIREMENT_PLAN.md`

## Deliberately not in scope

- deleting `PreBookingPipelineOrchestrator` in the same commit
- deleting `_save_inquiry` in the same commit
- deleting `_send_via_escapia` in the same commit
- deleting `_alert_operator_for_review` in the same commit
- deleting `kb_gap_manager.py` (`4.5.G`)
- any dashboard or operator UX change
- Ship I

4.5.F is the cutover, not the cleanup. Deletion follows after the cutover is
verified.

## Test pattern

Use the same house pattern as 4.5.A-E:

1. narrow flag seam
2. focused unit tests around the seam
3. no product/UI blast radius
4. retirement-plan update in the same commit

Recommended verification:

```bash
python3 -m py_compile \
  app/services/feature_flags.py \
  app/services/integrations/email_dispatch.py \
  app/services/messaging_brain/pre_booking.py \
  app/services/messaging_brain/pre_booking_lifecycle.py \
  app/services/concierge/pre_booking_auto_send.py

PYTHONPATH=/Users/dhuntermckenzie/Downloads/oyvoda:/Users/dhuntermckenzie/Downloads/oyvoda/app \
  .venv/bin/pytest \
  tests/unit/test_email_dispatch_prebooking_brain.py \
  tests/unit/test_prebooking_brain_lifecycle.py
```

Add additional focused tests if the cut touches existing persistence contract
coverage.

## Follow-on shape

If 4.5.F lands cleanly, then:

- 4.5.G becomes a true cleanup ship for `kb_gap_manager.py`
- then the deletion ship can remove dead legacy pre-booking orchestration
  shells entirely

That is the point where the answer to “where does pre-booking lifecycle
happen?” becomes “in the Brain,” full stop.
