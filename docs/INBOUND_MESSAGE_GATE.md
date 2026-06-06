# Inbound Message Gate

This note defines the design for the inbound message gate that sits in
front of the pre-booking email dispatch path.

Its purpose is narrow:

- classify inbound emails as guest vs non-guest before DB-backed
  pre-booking processing begins
- keep every gate decision observable in a dedicated table
- default uncertain cases to operator-visible review instead of silent
  suppression

This is a design and rollout reference, not an incident log. For the
incident that motivated it, see
`docs/INCIDENT_2026_05_05_DROPPED_DRAFTS.md`.

## Summary

The gate is a thin first-stage classifier that runs at the top of
`dispatch_pre_booking(...)`, before `load_property_context(...)` and
before the messaging brain or legacy pre-booking path.

It exists to prevent operational notifications and other non-guest
inbound traffic from reaching code paths that assume guest content and
guest-reply semantics.

The gate does not replace the existing messaging brain intake logic. It
answers a different question:

- gate question: "is this a real guest message that should enter the
  guest-reply pipeline at all?"
- existing brain intake question: "for a real guest message, what kind
  of guest intent is this?"

## Placement

Current pre-booking dispatch shape:

1. parsed email reaches `dispatch_pre_booking(...)`
2. property context is loaded
3. feature flags are read
4. messaging-brain or legacy pre-booking path runs
5. inquiry draft is persisted or deduped

Target shape with gate:

1. parsed email reaches `dispatch_pre_booking(...)`
2. inbound gate classifies it
3. gate decision is persisted to `inbound_classifications`
4. if classified as guest and confidence is high enough:
   continue into property-context load, flags, brain/legacy pre-booking
5. otherwise:
   skip downstream guest processing or route to review, depending on
   classification and rollout mode

The load-bearing design choice is step 2 before step 4. The gate must
run before `load_property_context(...)` so operational notifications do
not reach the DB-backed code paths implicated in the 2026-05-05
incident.

## Inputs and Outputs

### Input

The gate consumes the same parsed-email object the current dispatch path
already receives. In repo terms, that is the transport-normalized
`ParsedEmailMessage` shape, not raw provider-specific payloads.

The gate should use whatever fields are actually present on that object
in the current repo. Missing headers are acceptable in v1. Accuracy may
improve when additional email headers are exposed upstream, but the gate
does not depend on that enrichment to be useful.

Fields the gate uses, in approximate order of classification value:

- `subject` and `body`
  - always required
- `from_header`
  - high value
- `reply_to`
  - high value for Airbnb specifically; its presence or absence is a
    strong discriminator between real guest-message digest shapes and
    operational-notification shapes
- `x_template` and `x_category`
  - high value for OTA traffic
- `return_path`
  - moderate value

The gate degrades gracefully when some of these are missing. Accuracy is
highest when all are present.

### Output

The gate returns a structured decision with:

- `classification`
- `confidence`
- `reasoning`
- optional extracted guest fields when classification is
  `guest_message`
- diagnostic metadata such as model name, raw response, and error

The classification vocabulary is:

- `guest_message`
- `operational_notification`
- `marketing`
- `bounce_or_system`
- `unclear`

The operational contract is:

- only high-confidence `guest_message` proceeds into normal downstream
  guest processing
- `unclear` is always operator-visible
- low-confidence `guest_message` is operator-visible
- non-guest classes are either surfaced for review or suppressed,
  depending on rollout mode

## Persistence and Observability

Every gate decision is written to `inbound_classifications`.

This table is the observability surface for:

- validating classification quality in rollout
- measuring distribution of inbound traffic by type
- identifying operational notifications the gate prevented from reaching
  the guest pipeline
- auditing low-confidence or unclear cases

Important design choices:

- the gate decision write uses its own DB session
- failure to write the decision must not poison the shared dispatch
  transaction
- the table intentionally has no FK to downstream inquiry tables
- v1 linkage to later inquiry records is via `gmail_message_id`

This keeps the observability surface usable even if unrelated schema or
transaction issues exist elsewhere in the system.

## Flags

Two flags are required.

### `INBOUND_MESSAGE_GATE_ENABLED`

When off:

- behavior is identical to today
- the gate does not run

When on:

- every inbound pre-booking email is classified by the gate before
  property-context loading or guest-pipeline processing

### `INBOUND_MESSAGE_GATE_REVIEW_ALL`

When off:

- only `unclear` and low-confidence `guest_message` are forced to
  review
- high-confidence non-guest classifications can be suppressed from the
  guest pipeline

When on:

- every gate decision remains operator-visible during audit rollout
- this does not change `should_proceed_as_guest`
- confident guest messages still proceed downstream
- the flag affects review visibility, not whether the guest pipeline
  runs

This split is deliberate. One flag controls whether the gate exists in
the path; the other controls audit behavior during rollout.

## Route Outcomes

The dispatch path should use explicit route outcomes for gate behavior
rather than overloading existing pre-booking outcomes.

Route outcomes:

- `pre_booking_new`
- `pre_booking_duplicate`
- `pre_booking_fallback`
- `pre_booking_gate_review`
- `pre_booking_gate_skipped`
- `pre_booking_gate_error`

Definitions:

- `pre_booking_new`
  a guest message reached the normal pre-booking pipeline and created a
  new inquiry/draft

- `pre_booking_duplicate`
  a guest message reached the normal pre-booking pipeline but deduped
  against an existing inquiry

- `pre_booking_fallback`
  a guest message reached the normal path, that path failed, and the
  existing fallback save path created a reviewable inquiry

- `pre_booking_gate_review`
  the gate intentionally surfaced the inbound for operator-visible
  review instead of allowing normal downstream guest processing

- `pre_booking_gate_skipped`
  the gate confidently identified non-guest operational noise and
  suppressed downstream guest processing

- `pre_booking_gate_error`
  the gate itself failed unexpectedly and the system used a fail-safe
  review path

`pre_booking_gate_skipped` and `pre_booking_gate_error` must remain
distinct. A gate-model outage or parse failure must not look identical
to a healthy rise in operational notifications.

## Counter Semantics

`GmailPollResult` should track gate outcomes separately rather than
co-mingling them with normal inquiry counts.

Recommended counters:

- existing:
  - `pre_booking_routed`
  - `new_pending_inquiries`
  - `duplicate_inquiry_skips`
  - `fallback_inquiries_saved`
- new:
  - `gate_review_routed`
  - `gate_skipped`
  - `gate_errors`

Counter meanings:

- `pre_booking_routed`
  only messages that actually entered the normal pre-booking pipeline

- `new_pending_inquiries`
  only real new inquiry rows created for the operator’s pre-booking
  queue

- `gate_review_routed`
  messages the gate intentionally surfaced for operator review

- `gate_skipped`
  messages the gate confidently suppressed from downstream guest
  processing

- `gate_errors`
  failures of the gate itself, not healthy classifications

Important non-goals:

- `pre_booking_gate_review` should not increment
  `new_pending_inquiries` just because it created an operator-visible
  review artifact
- `pre_booking_gate_error` should not increment `pre_booking_routed`
  because the normal guest pipeline never ran

The counters should mean what their names say.

## Read-State Policy

Recommended Gmail read/unread policy by route outcome:

- `pre_booking_new`
  mark processed/read

- `pre_booking_duplicate`
  mark processed/read

- `pre_booking_fallback`
  mark processed/read

- `pre_booking_gate_review`
  leave unread

- `pre_booking_gate_error`
  leave unread

- `pre_booking_gate_skipped`
  - if `INBOUND_MESSAGE_GATE_REVIEW_ALL` is off: mark processed/read
  - if `INBOUND_MESSAGE_GATE_REVIEW_ALL` is on: leave unread

This section governs Gmail-side read/unread behavior only.
Operator-visible review behavior in Oyvoda is separate and is governed
by whether the gate outcome is surfaced for review.

This gives the operator clean visibility semantics:

- ambiguity stays visible
- gate failures stay visible
- confidently-classified noise can disappear once the gate is trusted
- audit mode keeps even confident skips visible while validating the
  gate

## Rollout Phases

### Phase 1 — Code and migration only

- run the migration for `inbound_classifications`
- deploy code with `INBOUND_MESSAGE_GATE_ENABLED = off`
- verify the deploy actually lands
- observe at least one normal inbound traffic cycle with no behavior
  change

Progression criterion:

- migration successful
- code deployed
- gate confirmed off
- no unexpected behavior in the existing pre-booking path

### Phase 2 — Audit mode

- set `INBOUND_MESSAGE_GATE_ENABLED = on`
- set `INBOUND_MESSAGE_GATE_REVIEW_ALL = on`
- every inbound is classified
- every gate decision remains operator-visible

Implications:

- the visible review surface will grow faster than normal
- operational notifications, marketing, and bounce/system mail will be
  visible during this audit phase by design

Progression criterion:

- review at least 24-48 hours of real inbound traffic
- inspect distribution of `inbound_classifications`
- spot-check at least 10 decisions per observed category, or every
  decision in a category if fewer than 10 exist in the review window
- observe zero false-positive `operational_notification` decisions on
  real guest traffic
- observe no spike in `gate_errors`

### Phase 3 — Selective suppression

- keep `INBOUND_MESSAGE_GATE_ENABLED = on`
- set `INBOUND_MESSAGE_GATE_REVIEW_ALL = off`
- confident operational noise is suppressed from the guest pipeline and
  marked read
- `unclear` and low-confidence guest traffic remains operator-visible

Progression criterion:

- stable traffic with no meaningful `gate_errors`
- operator confirms the review surface looks correct
- operator confirms the gate is removing noise rather than hiding real
  guest work

## Audit-Mode UI Implications

During Phase 2 audit mode, the operator-visible review surface will
contain everything the gate sees, not just normal guest inquiries.

That means the queue will contain proportionally more:

- operational notifications
- marketing emails
- bounce/system mail
- unclear and low-confidence items

To make Phase 2 usable, the operator-facing review surface should make
the gate decision easy to inspect. Minimum expectations:

- display the gate classification prominently on each review item
- allow filtering by classification
- make it easy to isolate `unclear` items from confidently-classified
  operational noise

This does not need to change the gate’s backend contract. It is a
presentation requirement for the operator’s audit experience.

Operator confirmation that the review surface "looks right" is part of
the Phase 2 progression criterion. In practice, that confirmation
depends on these UI affordances being present.

## Integration Points

Primary integration point:

- `app/services/integrations/email_dispatch.py`
  - top of `dispatch_pre_booking(...)`

Supporting integration points:

- feature flag enum/service
- `GmailPollResult` accounting and route handling in
  `app/services/integrations/gmail_inbox_poller.py`
- migration for `inbound_classifications`
- tests for the gate itself and the dispatch integration

The gate should be wired against the current repo shape, not an
idealized one. In particular:

- use the repo’s actual parsed-email fields
- use the repo’s actual feature-flag resolution pattern
- use the repo’s existing Anthropic/httpx pattern unless a shared client
  abstraction is introduced deliberately

## Design Decisions

### Why a separate gate instead of expanding `LLMIntakeAgent`

Because the current messaging brain assumes the message is already a
real guest message. That downstream contract should stay stable.

The gate solves a different problem:

- guest-pipeline admission

The existing intake agent solves:

- intent classification for admitted guest messages

Keeping those separate reduces rollout risk and keeps failure modes
clean.

### Why the gate sits before `load_property_context(...)`

Because the immediate incident involved operational notifications
reaching DB-backed code paths that assumed guest-message semantics.

Putting the gate at the top of `dispatch_pre_booking(...)` means
operational notifications never reach:

- property-context loading
- feature-flag reads for guest processing
- messaging-brain or legacy pre-booking processing
- inquiry draft persistence

### Why two flags instead of one

Because rollout and audit are separate concerns.

- one flag answers: "does the gate exist in the path?"
- the other answers: "during rollout, do we want every decision to stay
  operator-visible?"

This makes rollout reversible without redeploy and lets different
operators spend different amounts of time in audit mode.

### Why no FK to `pre_booking_inquiries`

Because the gate runs before a downstream inquiry may or may not be
created, and because this table is an audit surface first, not a
normalized dependency.

Adding a FK would:

- complicate writes for a table whose value is operational observability
- create another place where schema drift could block an audit write
- solve a linkage problem that is already recoverable in v1 via
  `gmail_message_id`

### Why gate failures default to review instead of skip

Because the fail-safe direction is operator visibility, not silent
suppression.

If the model call fails, the response is malformed, or the gate cannot
classify the inbound confidently, the system should prefer:

- "a human sees it"

over:

- "we guessed it was noise"

## Out of Scope

This design does not address several other real issues identified during
the 2026-05-05 investigation:

- the within-inquiry trigger in the current dropped-drafts incident
  - see `docs/INCIDENT_2026_05_05_DROPPED_DRAFTS.md`
- the separate swallow-without-rollback sites in operator-learning and
  message-history code
  - see `docs/INCIDENT_2026_05_05_DROPPED_DRAFTS.md`
- the schema-drift cluster around `knowledge_gaps`, `kb_gaps`, and
  `operator_gap_settings`
  - see `docs/INCIDENT_2026_05_05_DROPPED_DRAFTS.md` and
    `docs/ARCHITECTURE_RECONCILIATION_TRACKER.md`
- broader Airbnb reply-channel UX and operator-flow questions
  - see `docs/SESSION_RESUME_2026_05_05.md`

Those remain separate workstreams. The inbound gate addresses the
immediate problem of operational notifications reaching the guest
pipeline, and it creates a scalable observability surface for future
classification tuning. It does not replace the need for cleanup in the
underlying transaction-handling and schema-consistency layers.
