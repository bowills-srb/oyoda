# Intake Path Reconciliation -- 2026-05-04

Reconciliation note enumerating every code path that writes to
`pre_booking_inquiries`, classified against the canonical contract
commitment defined in `docs/MESSAGING_ARCHITECTURE.md`.

This is Phase 1b of the architecture rollout sequence: audit existing
intake paths and classify each one. It produces a mapping artifact, not
code changes. Subsequent sessions execute against the findings here.

## Purpose

The architecture document commits to one canonical message contract,
with all extraction strategies producing `CanonicalInboundMessage`
before downstream components consume the data. This commitment is
partially realized in the codebase. Some intake paths route through
the canonical contract; others write directly to `pre_booking_inquiries`
without producing a canonical message.

This note enumerates every path that can result in a row landing in
`pre_booking_inquiries`, classifies each path against the canonical
contract, and recommends next-step disposition for each.

## Classification legend

Each path is tagged with two axes.

**Contract relationship:**

- **Canonical** -- path produces a `CanonicalInboundMessage` upstream
  of the write. The write is canonical-aligned.
- **Adaptable** -- path does not currently produce a canonical message
  but could be modified to route through `inbound_normalizer`.
- **Fallback-keep** -- path is a deliberate fallback that should
  remain. The non-canonical write is intentional (e.g., last-resort
  capture when canonical persistence fails).
- **Retire** -- path is dead code, superseded by another path, or no
  longer reachable. Recommend deletion.

**Activity status:**

- **Active** -- path is known to be exercised in production.
- **Suspected inactive** -- path exists but no evidence of recent
  invocation; needs runtime verification.
- **Unknown** -- path's activity status cannot be determined from
  static analysis alone.

## Method

Inventory generated 2026-05-04 via grep across `app/`:

- Direct SQL writes: `INSERT INTO pre_booking_inquiries`
- Save function definitions: `def _save_inquiry`, `def _save_draft`,
  `def _save_fallback_pre_booking_inquiry`
- Save function callers: `_save_inquiry(`, `_save_draft(`,
  `_save_fallback_pre_booking_inquiry(`
- Repository/ORM patterns: `PreBookingInquiry`, `*Repository`

Each path identified was traced to its call site to determine whether
upstream code produces a `CanonicalInboundMessage` before reaching the
write.

## Path inventory

The audit identified three distinct intake paths writing to
`pre_booking_inquiries`. Each is described below with classification,
activity status, and architectural notes.

### Path 1 -- `pre_booking_auto_send._save_inquiry`

**Location:** `app/services/concierge/pre_booking_auto_send.py:2589`

**Classification:** Adaptable / Active

**Reached from:**
- Primary: `pre_booking_auto_send.PreBookingFlowExecutor.persist_and_dispatch(...)`
  at line 2073, invoked via the main dispatch flow
  (`email_dispatch.dispatch_pre_booking -> process_pre_booking_inquiry_with_draft -> ...`)
- Fallback: `gmail_inbox_poller._save_fallback_pre_booking_inquiry`
  at line 2162 (see Path 3)

**Contract relationship:**

`_save_inquiry` accepts a legacy fragmented argument bundle (`thread_id`,
`message_id`, `platform`, `guest_name`, `message_text`, `check_in`,
`check_out`, `guests`, `property_external_id`, `intent`, `confidence`,
`draft_text`, `policy_flags`, `policy_warnings`, `decision`). It does
not accept a `CanonicalInboundMessage`.

The call site in `persist_and_dispatch(...)` shreds `self.request`
(of type `PreBookingInquiryInput`, defined at line 1885) into individual
arguments. `PreBookingInquiryInput` is itself a pre-canonical request
shape, distinct from `CanonicalInboundMessage`.

The path takes canonical data upstream (the dispatch flow does
canonicalize), converts it into `PreBookingInquiryInput`, then shreds
that bundle into `_save_inquiry`'s positional argument list. Two
layers of legacy contract between canonical input and persistence
output.

**Why adaptable rather than canonical:**

The persistence seam itself is non-canonical. Even when canonical-aware
code feeds the path upstream, the writer boundary expresses the inquiry
in legacy fragmented terms. Future work to make this path canonical
would either:

- Wrap `_save_inquiry` behind a canonical-typed interface that accepts
  `CanonicalInboundMessage` (plus the inquiry-specific fields like
  draft, decision, policy state) and converts internally
- Or replace `_save_inquiry` with a canonical-native writer that
  accepts the canonical shape directly

The first is lower-risk; the second is structurally cleaner.

**Why active:**

This is the primary persistence mechanism for pre-booking inquiries
in the current operator base. Beach Habitats traffic flows through it.
Removing or significantly modifying it without careful migration would
break operator-facing flows.

**Notes:**

- The function performs side effects beyond the SQL insert: it ensures
  a guest thread exists via `get_guest_thread_service().ensure_inquiry_thread(...)`,
  and (per the observability investigation on 2026-05-03) is part of
  the dispatch chain that should produce a `message_normalizations`
  attribution row via downstream `update_normalization_outcome(...)`
- The function is the convergence point: both the main flow and the
  poller fallback ultimately route here, which makes it the natural
  candidate for canonical adaptation if Path 3 stays as a deliberate
  fallback

### Path 2 -- `pre_booking_handler._save_draft`

**Location:** `app/services/concierge/pre_booking_handler.py:720`

**Classification:** Adaptable / Activity unresolved (depends on worker-tier resolution)

**Reached from:**
- Inbound: `pre_booking_handler.EscapiaMessageService.process_inquiry(...)`
  at line 713, which is itself reached from
  `app/workers/tasks.py:1027` via Celery task
- The Gmail poller reference at `gmail_inbox_poller.py:2486` is
  **outbound-only** (Escapia reply fallback when Gmail reply path
  is unavailable). Not evidence of inbound invocation.

**Contract relationship:**

`_save_draft(...)` accepts an `InquiryDraft` object. The function
extracts fields from `draft.inquiry.*` (a dedicated `PreBookingInquiry`
domain object specific to this handler) and writes them to
`pre_booking_inquiries`. This is a separate non-canonical persistence
contract from Path 1 -- same destination table, different upstream
shape.

The file's docstring describes a richer Escapia integration: polling
via Celery every 5 minutes, optional webhook intake, multi-channel
support (Vrbo/Airbnb/HomeAway/direct Escapia). This is a fully
separate intake pipeline from the email-bridged Gmail path Beach
Habitats currently uses.

**Why activity is unresolved:**

The only evidence of inbound `_save_draft` invocation in production
is the Celery task at `app/workers/tasks.py:1027`. Whether that task
is actually being consumed depends on the Celery worker tier
configuration, which remains in the unresolved state from the
2026-05-02 topology snapshot (`cf868ea`):

- `oyvoda-worker` was found misconfigured as an API-shaped process
  (using `docker/Dockerfile.api` with `uvicorn` start command), not
  as a Celery worker
- No process was confirmed to be consuming Celery task queues
- `oyvoda-beat` schedules tasks; nothing has been verified to consume
  them

If no Celery consumer exists, the task definition at `tasks.py:1027`
is structurally live but functionally dormant. `_save_draft` would
be unreachable from production traffic in that case.

**Why adaptable rather than retire:**

Even if the Celery consumer is confirmed missing today, the path may
be intended to be re-activated when the worker tier is fixed. The
file is a deliberate Escapia integration, not abandoned code. Retiring
it without confirming non-use risks deleting work that the worker-tier
fix is meant to restore.

**Recommendation:**

Defer disposition decision until worker-tier topology is resolved. At
that point:

- If Celery consumer is added and tasks fire -> Path 2 becomes "active,
  adaptable" with the same canonical-migration considerations as Path 1
- If Celery worker tier is intentionally not built and Escapia direct
  intake is abandoned -> Path 2 becomes "retire," subject to a separate
  retirement session
- If Escapia direct intake is replaced by the email-bridged path
  permanently -> Path 2 retires; the file's outbound-reply functionality
  may need extraction before deletion

The path is non-canonical at the writer seam in any case. Even if
re-activated, it would need the same canonical-adaptation work as
Path 1.

**Notes:**

- The file's outbound capability (`send_approved_reply`) is reached
  from the Gmail poller as a reply fallback. Any retirement decision
  must preserve that capability or migrate it before deletion. The
  outbound fallback is orthogonal to the inbound writer classification.
- `_save_draft` uses `ON CONFLICT (thread_id, message_id) DO UPDATE`
  semantics, where Path 1 does not. Behavioral difference worth noting
  if paths converge later.
- The file has a configured logger (line ~67), so the observability
  commitment is met for this path's exception handling, contingent on
  exception paths actually logging at WARNING/ERROR (not verified in
  this audit).

### Path 3 -- `gmail_inbox_poller._save_fallback_pre_booking_inquiry`

**Location:** `app/services/integrations/gmail_inbox_poller.py:2140`

**Classification:** Fallback-keep / Active in code, inactive in observed history

**Empirical activity (as of 2026-05-04):**

A query against `pre_booking_inquiries` filtered for fallback policy
warnings returned zero invocations across 265 historical rows
(including 211 in the last 7 days). The fallback exists as
architectural insurance that has not been called on in the operator
data captured to date. This does not change the classification -- the
function's role is safety-net coverage for primary-path failures, and
its absence of invocation reflects primary-path reliability rather
than fallback obsolescence.

**Reached from:**

The fallback is registered as a callback on `EmailDispatchServices`
(line 1591) and invoked by `email_dispatch` code when the primary
draft pipeline fails. It is not a parallel intake path; it is a
deliberate safety net.

**Contract relationship:**

The fallback delegates to `pre_booking_auto_send._save_inquiry(...)`
(Path 1's writer), so it inherits Path 1's non-canonical writer seam.
Above the writer, the fallback constructs `_save_inquiry`'s arguments
from a `ParsedGmailMessage` directly, without producing a canonical
intermediate. This is intentional -- the fallback fires when the
canonical-aware path has already failed, so re-entering canonical
production at fallback time would re-trigger whatever caused the
primary failure.

**Why fallback-keep rather than retire:**

The function exists for a specific architectural purpose stated in its
own docstring:

> "Persist a reviewable inquiry even if AI draft generation fails.
> This keeps inbound emails visible to operators instead of letting
> them disappear behind a swallowed exception in the draft pipeline."

This is exactly the pattern the architecture's observability commitment
endorses: when a load-bearing pipeline fails, surface a usable signal
rather than silently dropping the work. Operators get a visible
inquiry with a fallback draft and a `gmail_fallback_saved:<error>`
policy warning rather than an inbound email vanishing without trace.

Retiring this path would degrade operator-visibility guarantees during
primary-path failures. The pattern should be preserved even after Path
1 becomes canonical-native.

**Recommendation:**

Preserve the safety-net role through the canonical migration. When
Path 1 is adapted behind a canonical persistence interface, the
fallback's call into `_save_inquiry` should similarly be migrated
to use the canonical interface -- but the *role* of the fallback (capture
inbound when primary pipeline fails) does not change.

Sequencing matters: do not migrate the fallback before the primary
path. The fallback is the safety net for primary-path failures, so
it must remain available in its current form until the canonical
primary is proven live and stable. Premature migration of the fallback
would remove operator-visibility guarantees during the migration
window.

**Notes:**

- The fallback emits an ERROR-level log on its own failure
  (`logger.error("[GmailPoller] Fallback inquiry save failed: %s", ...)`)
  -- observability commitment is met for this path's exception handling.
- The fallback writes a synthetic draft (`fallback_draft` text)
  explaining the situation to the operator, plus a structured policy
  warning containing the error context. This is a deliberate operator
  UX choice, not just a save-and-forget.
- The fallback also calls `_store_gmail_thread_context(...)` after
  the save, ensuring thread metadata is captured even on the fallback
  path. Reply-out from the fallback-saved inquiry remains functional.

## Current state read

Three distinct intake paths write to `pre_booking_inquiries`. Two are
known active (Path 1, Path 3). One has unresolved activity status
pending worker-tier topology resolution (Path 2).

**No path is canonical at the writer seam.** All three express the
inquiry through legacy fragmented contracts at the moment of
persistence, even when canonical-aware code feeds them upstream. The
canonical contract commitment from the architecture document is not
yet realized at this seam.

**The three paths converge on the same destination but differ in
upstream shape:**

- Path 1 receives `PreBookingInquiryInput` (legacy request shape) and
  shreds it into `_save_inquiry`'s positional arguments
- Path 2 receives `InquiryDraft` (Escapia-handler domain shape) and
  shreds `draft.inquiry.*` into the SQL bind parameters directly
- Path 3 receives `ParsedGmailMessage` directly and constructs
  `_save_inquiry`'s arguments inline as a fallback

The destination table is identical; the inputs are three different
non-canonical shapes. Future canonicalization work needs to address
each of these upstream contracts, not just the writer.

**The audit revealed one secondary finding worth noting:** the Gmail
poller imports `EscapiaMessageService` at line 2486, but only as an
outbound reply fallback -- not as an inbound intake handoff. The
import is reply-side, not write-side, and does not affect Path 2's
inbound classification.

**Behavioral inconsistency between paths:** Path 2 uses
`ON CONFLICT (thread_id, message_id) DO UPDATE` semantics for
deduplication. Path 1 (and therefore Path 3 by delegation) does not.
This is a behavioral divergence between paths writing to the same
table. Worth flagging as a downstream consistency issue if Path 2
is confirmed active.

**Observability state at the writer seam:** All three paths' host
modules have configured loggers. The 2026-05-03 observability fix
(`a9b09ef`) addressed `message_event_store.py`, which is upstream of
these writers in the canonical flow. The writers themselves have
some exception logging in place; an exhaustive audit of exception
paths within these writers is out of scope for this note.

## Per-path next actions

### Path 1 -- `_save_inquiry` (adaptable / active)

Forward work, in order:

1. **Decide adaptation vs replacement.** Wrap `_save_inquiry` behind a
   canonical-typed interface accepting `CanonicalInboundMessage` plus
   inquiry-specific fields, OR replace `_save_inquiry` with a
   canonical-native writer. The first is lower-risk; the second is
   structurally cleaner.
2. **Sequence relative to Issue 3 resolution.** Do not begin
   adaptation before the canonical persistence outage from 2026-05-03
   is diagnosed and fixed. The current canonical seam is still
   unreliable; building canonical-typed interfaces against an
   unreliable seam compounds risk.
3. **Migrate `PreBookingInquiryInput` upstream.** The legacy request
   shape feeding `persist_and_dispatch` is its own non-canonical
   contract. Adapting `_save_inquiry` without addressing
   `PreBookingInquiryInput` produces a half-migration where canonical
   data is shredded into legacy request shape and then re-shredded
   into writer arguments.
4. **Preserve attribution semantics.** The path's downstream
   attribution of inquiries to extraction provenance and routing
   outcome (currently via `message_normalizations`) is load-bearing
   for metrics and verification. Any adaptation must retain or
   improve attribution behavior, not silently drop it. The exact
   mechanism may evolve as Issue 3's canonical persistence outage
   is resolved; the semantic guarantee should not.

### Path 2 -- `_save_draft` (adaptable / activity unresolved)

Forward work, gated on worker-tier resolution:

1. **Resolve worker-tier topology** (separate workstream from
   `cf868ea`). Determine whether Celery tasks at `app/workers/tasks.py`
   are being consumed in production today.
2. **Verify intake activity at runtime.** Once worker-tier is
   resolved, instrument or query to determine whether `_save_draft`
   is fired for any active operator. This may require adding
   structured logging at the function entry to capture invocation
   evidence over a measurement window.
3. **Decide disposition based on evidence:**
   - Active for any operator -> adapt behind canonical interface,
     same considerations as Path 1
   - Confirmed inactive and Escapia direct intake is abandoned ->
     retire in a separate session, with care to preserve the
     `send_approved_reply` outbound capability used as the Gmail
     poller's reply fallback
   - Active for some operator subset -> migrate per-operator at the
     dispatch level, retaining `_save_draft` until all operators are
     migrated to email-bridged or canonical-direct paths
4. **Resolve the `ON CONFLICT` divergence.** Path 2's dedup semantics
   differ from Path 1's. Pick one convention and apply consistently
   across all writers, regardless of which path is retained.

### Path 3 -- `_save_fallback_pre_booking_inquiry` (fallback-keep / active)

Forward work, sequenced after Path 1:

1. **Preserve the safety-net role through migration.** The fallback's
   purpose (operator-visibility guarantee on primary-path failure) is
   architecturally correct and should not be removed.
2. **Migrate after Path 1 is canonical.** Once `_save_inquiry` (or its
   canonical replacement) is stable, update the fallback to use the
   canonical writer interface rather than the current legacy
   delegation.
3. **Do not migrate before Path 1.** The fallback is the safety net
   for Path 1 failures. Premature migration of the fallback would
   remove operator-visibility guarantees during the migration
   window.
4. **Audit the fallback's trigger conditions** as a side check.
   Verify that the fallback fires only on genuine primary-path
   failure (not on routine paths that should be canonical-native).
   Frequent fallback invocation would indicate the primary path is
   failing more than expected.

## Open questions

The audit could not resolve the following from static analysis alone:

1. **Worker-tier consumption status.** Are Celery tasks defined in
   `app/workers/tasks.py` actually being processed by any production
   process? Resolution required for Path 2 disposition.

2. **Path 2 operator scope.** If the worker tier is fixed and
   `_save_draft` becomes reachable, which operators (current or
   prospective) would route through Escapia direct intake vs. the
   email-bridged Gmail path Beach Habitats uses? Affects whether
   Path 2 is migrated, retired, or maintained per-operator.

3. **Fallback invocation frequency** *(resolved 2026-05-04)*. A query
   against `pre_booking_inquiries` filtered by
   `policy_warnings::text LIKE '%gmail_fallback_saved%'` returned zero
   fallback invocations across all 265 historical rows, including
   211 in the last 7 days. The fallback exists as architectural
   insurance that has not been empirically exercised. Path 3's
   classification updates to: fallback-keep, active in code,
   inactive in observed history.

   Caveat worth recording: zero fallback fires confirms that the
   primary pipeline reliably gets inquiries into
   `pre_booking_inquiries`, but does not confirm the primary pipeline
   is fully healthy. The 2026-05-03 canonical persistence outage
   produced silent failures at a downstream layer (canonical
   attribution to `message_normalizations`) without triggering the
   fallback. The fallback's safety-net scope is operator-visibility
   of inquiries, not full pipeline correctness.

4. **Behavioral consistency of `ON CONFLICT` semantics.** Path 2 and
   Path 1 differ in dedup behavior. Whether this is a bug, a deliberate
   per-path choice, or a divergence that should be reconciled is not
   resolved by this audit.

5. **Exhaustive within-writer exception path audit.** The audit
   confirmed the host modules have configured loggers, but did not
   verify that every exception path within Paths 1, 2, and 3 logs
   at WARNING/ERROR with traceback. The 2026-05-03 incident showed
   that "module has logger" does not guarantee "exception paths log
   well." A targeted observability audit of these writers is
   recommended forward work.

## Out of scope

This note does not:

- Make code changes to any path
- Define migration timelines for adaptable paths
- Specify the implementation shape of canonical-routing changes
- Decide whether retirable paths are deleted in this commit or later
- Audit downstream consumers of `pre_booking_inquiries` (handled by
  separate workstream on downstream uniformity)
- Resolve outstanding architectural debt items beyond the intake path
  scope (Issue 3 canonical persistence outage, Issue 4 channel
  convention mismatch, worker tier topology)
