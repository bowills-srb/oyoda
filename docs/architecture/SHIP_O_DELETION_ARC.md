# Ship O — Legacy runtime deletion arc

**Status:** Brief written May 20, 2026, after Ship N completed proactive runtime migration onto `messaging_brain` and after the pre-booking `4.5.A-G` migration arc landed on `main`.

**Scope discipline:** Ship O is a **deletion arc**, not a migration arc. It removes now-dead legacy runtime ownership only after the Brain-owned path has been verified as the sole live caller. It does **not** introduce new Brain features, does **not** redesign operator UX, and does **not** bundle cleanup that lacks prove-dead evidence.

**Why this is its own ship:** The migration work is done. Brain now owns:

- reactive `/concierge/message` across all lifecycles
- reactive session channels (SMS / mobile / phone / Gmail in-stay attribution)
- proactive guest-journey composition and trigger handling
- pre-booking runtime ownership through the Brain lifecycle seam

That means the work left is different in kind. Migration ships asked:

`how do we move capability X into Brain without duplicating it?`

Ship O asks:

`which legacy modules now have zero legitimate runtime ownership, and what is the safest order to delete them?`

That requires a stricter discipline:

1. prove the live caller is gone
2. prove the fallback window has elapsed
3. delete in small isolated commits
4. verify no imports/call sites remain

Ship O fails if it acts like a migration ship and deletes on intuition instead of evidence.

---

## The decision this ship operationalizes

The retirement plan’s long-term target is now true at the runtime-ownership level:

`messaging_brain` is the one answer for guest-message orchestration.

So the remaining legacy modules should not linger as shadow runtimes, compatibility crutches, or dormant “just in case” implementations. They should either:

- be deleted because the Brain owns that behavior now, or
- remain only as narrow shared helpers with no alternate runtime semantics

Ship O is the formal cleanup step that turns:

- `MIGRATING`

into:

- `BRAIN-ACTIVE`
- then `RETIRED`

for the remaining deletion targets.

---

## What Ship O ships

Six deliverables, in order:

1. **Inventory and verification windows per target.**
2. **Delete `ConciergeRunner` runtime ownership.**
3. **Delete `VoicePod.respond(...)` runtime ownership.**
4. **Delete remaining proactive template/runtime leftovers.**
5. **Delete or collapse `pre_booking_auto_send.py` legacy orchestration scaffolding.**
6. **Update the retirement plan status machine with explicit retired states.**

Each deletion is its own evidence gate. If one target is not yet dead, Ship O ships the others and leaves that target behind for a follow-up delete ship.

---

## The prove-dead rule

Every deletion target in Ship O must satisfy **all** of these before removal:

1. **Zero live call sites in code** by `rg`, excluding comments/docs/tests that are explicitly grandfathered.
2. **A named verification window** that the Brain-owned replacement has already survived.
3. **A rollback story** that does not depend on the deleted module still existing.
4. **A focused test or smoke check** proving the replacement path still works with the legacy import removed.

Recommended default verification window where no stronger evidence exists:

- **one Beach Habitats canary cycle or two weeks of production traffic**

If a target has higher blast radius, require the longer window. If a target has airtight call-site proof and dedicated test coverage, the window can be shorter, but the brief must name why.

**Eligibility rule:** a target is deletable only after the Brain-owned replacement has already been live in real production traffic for the named window. A replacement that landed "today" has not yet earned its delete window "tomorrow," even if tests are green. This means Ship O may legitimately split across multiple sessions:

1. inventory + call-site audit now
2. deletion commits only after the relevant windows have actually elapsed

**Parallel window rule:** verification windows run in parallel, not serially. If multiple replacements landed on the same date, their observation windows begin on that same date. Ship O should not wait for one target’s window to finish before starting audit work for another target.

This rule is the guardrail against the reverse of the old `kb_gap_manager` problem:

- not “code that looked live but was dead”
- but “code that looked dead but still had one caller”

---

## Deletion targets

### Target A — `ConciergeRunner`

**What it used to own**

- `/concierge/message` legacy reactive flow
- `/concierge/proactive` preview flow
- old voice endpoint behavior

**Why it is now a retirement target**

- Ship K moved lifecycle-correct reactive entry into Brain
- Ship L moved reactive concierge ownership into Brain specialists
- Ship N moved proactive ownership into Brain triggers/specialist

At this point `ConciergeRunner` should no longer own any canonical guest runtime behavior.

**What must be proven before deletion**

- `rg` shows no production runtime route still calling `get_concierge_runner()` for canonical behavior
- any remaining references are:
  - dead legacy endpoints
  - docs/comments
  - isolated non-prod test harnesses

**Likely files**

- `app/services/concierge/concierge_runner.py`
- `app/services/orchestration/concierge_runner.py`
- imports in `app/api/v1/endpoints/concierge.py`
- imports in `app/api/v1/endpoints/voice.py`
- re-export shims in `app/services/concierge/__init__.py`
- re-export shims in `app/services/orchestration/__init__.py`

---

### Target B — `VoicePod.respond(...)` as a runtime owner

**Important clarification**

This target is about deleting **VoicePod as the live reactive runtime owner**, not about deleting every useful helper or session/context facility around it.

If anything in `voice_pod.py` is still canonical utility logic that Brain should call, that logic gets extracted or left as a helper. What gets retired is the alternate runtime path:

- `VoicePod.from_session(...)`
- `VoicePod.respond(...)`
- channel seams that still treat VoicePod as the source of message decisions

**Why it is now a retirement target**

- Ship M moved live reactive session-channel ownership onto Brain adapters
- Brain now owns the decision path for SMS/mobile/phone/Gmail in-stay attribution

**What must be proven before deletion**

- no live guest-facing channel still depends on `VoicePod.respond(...)`
- any remaining references are:
  - non-prod diagnostics
  - controlled test endpoints
  - comments/docs

**Likely files**

- `app/services/knowledge/voice_pod.py`
- `app/api/v1/endpoints/mobile_v2.py`
- `app/api/v1/endpoints/mobile_v3.py`
- `app/api/v1/endpoints/phone.py`
- `app/api/v1/endpoints/sms.py`
- `app/services/messaging/channel_router.py`
- `app/api/v1/endpoints/knowledge.py` voice-pod test endpoint

**Decision rule**

If `voice_pod.py` still contains useful extraction-worthy helper logic that Brain does not yet own anywhere else, do **not** delete the whole file in one shot.

This is a hard sequencing rule, not a preference:

1. first land a separate extraction commit that preserves the shared utility in a non-runtime home
2. only after that lands, ship a second commit deleting `VoicePod` runtime entrypoints

If that extraction has not happened yet, the runtime-ownership deletion for Target B is not ready.

---

### Target C — `PROACTIVE_TEMPLATES` and template-owned proactive composition

**What it used to own**

- direct proactive SMS composition bypassing Brain

**Why it is now a retirement target**

- Ship N made Brain the proactive composition owner
- the template path is now an explicit failure fallback only

**Deletion rule**

This target is deleted only after the fallback usage has been measured and deemed unnecessary.

That means Ship O may split this into two stages:

1. keep fallback but prove it is never or almost never used
2. delete templates once proactive Brain reliability is proven

**Required evidence**

- proactive Brain compose reliability window is named and complete
- fallback usage is observable and near-zero or zero

If this evidence does not yet exist, Ship O should **not** delete `PROACTIVE_TEMPLATES` in the same pass as the other runtime removals.

---

### Target D — `StayProactiveService` as message-body owner

**Clarification**

Ship N intentionally kept `StayProactiveService.evaluate(...)` as the **eligibility/cadence helper** while Brain became the composition owner.

So `StayProactiveService` is **not automatically deletable**.

Ship O must first answer:

- is `StayProactiveService` now purely a canonical eligibility helper the Brain/operator workflow still should call?
- or has equivalent cadence logic already been absorbed elsewhere?

**Deletion rule**

- If it is still the canonical cadence helper, it stays.
- If its remaining behavior is redundant, only the redundant message-body logic gets removed.

Ship O fails if it deletes the cadence logic just because the message text moved.

---

### Target E — `pre_booking_auto_send.py` orchestration scaffolding

**What it used to own**

- pre-booking classify → route → draft → persist → dispatch orchestration
- pre-booking side-effect shell
- legacy compatibility evaluator during the 4.5.A-G migration

**Why it is now a retirement target**

- 4.5.A-G moved useful capability ownership into Brain
- Ship F / the pre-booking lifecycle cut moved runtime ownership into Brain

What remains should now be either:

- dead legacy orchestration
- thin helper seams that Brain still calls

**Critical caution**

This is the highest-risk deletion target in Ship O.

Do **not** delete `pre_booking_auto_send.py` wholesale until every live import is audited. Right now the known likely remaining live seams include:

- worker/task helpers
- persistence/send helper imports
- pre-booking lifecycle compatibility shims

So this target likely lands as a staged collapse:

1. remove dead orchestration classes/functions
2. move any surviving path-agnostic helpers to a clearer shared home
3. shrink `pre_booking_auto_send.py` to a thin shim
4. delete the shim only when imports hit zero

**Granularity rule:** deletion commits for `pre_booking_auto_send.py` must be per logical symbol-group, not per file and not "whatever happens to be nearby." Examples:

- one commit deleting `InquiryIntentClassifier` and its immediately-related private helpers
- one commit deleting `PreBookingPipelineOrchestrator`
- one commit deleting a narrow persistence helper cluster

This keeps rollback scoped to one retired capability group at a time and matches the retirement plan’s `MIGRATING -> BRAIN-ACTIVE -> RETIRED` discipline.

**Likely files**

- `app/services/concierge/pre_booking_auto_send.py`
- `app/services/messaging_brain/pre_booking_lifecycle.py`
- `app/services/integrations/email_dispatch.py`
- `app/workers/tasks.py`
- `app/services/concierge/inquiry_persistence.py`
- `app/services/concierge/pre_booking_handler.py`
- `app/api/v1/endpoints/operator_prebooking.py`
- `app/services/integrations/gmail_inbox_poller.py`

**Verification requirement**

For each removed symbol, the brief executor must show the replacement caller and run `rg` before deletion.

---

## What Ship O does **not** delete

These are not deletion targets just because they live under `concierge/` or used to be touched by legacy flows:

- `knowledge_service.py`
- `response_reviewer.py`
- `hallucination_guard.py`
- `context_builder.py`
- transport send helpers if they are still canonical utilities
- event-planning / market services
- property/session hydration helpers

The rule is:

- delete alternate runtime ownership
- keep single-source shared utilities

Ship O is about removing duplicate orchestration, not flattening the entire service tree.

---

## Deliverable 1 — Inventory and verification windows

Before any delete patch, produce a target-by-target matrix:

- target
- current live call sites
- replacement path
- verification window already satisfied
- can delete now? yes/no

This matrix can live in the brief, commit message, or a small companion note, but it must exist before code deletion starts.

### Acceptance criteria

- Every deletion target has a named verification window.
- Every deletion target has an explicit replacement path.
- Any target lacking prove-dead evidence is deferred instead of deleted.

---

## Deliverable 2 — Delete `ConciergeRunner` runtime ownership

### What Ship O does

- remove canonical runtime callers
- remove re-exports if unused
- leave only non-prod or grandfathered code if still explicitly intended

### Acceptance criteria

- `rg` shows no production guest runtime path calling `get_concierge_runner()`
- if legacy voice remains, it is explicitly marked non-prod or separately retired in the same ship
- `ConciergeRunner` runtime ownership is gone

---

## Deliverable 3 — Delete `VoicePod.respond(...)` runtime ownership

### What Ship O does

- remove live channel dependency on `VoicePod.respond(...)`
- keep or extract any remaining canonical utility logic if needed
- retire the VoicePod test seam if no longer meaningful

### Acceptance criteria

- SMS/mobile/phone/Gmail in-stay canonical paths do not call `VoicePod.respond(...)`
- any remaining `VoicePod` references are explicitly non-runtime
- if `voice_pod.py` remains, it is no longer a guest-message runtime

---

## Deliverable 4 — Delete proactive template/runtime leftovers

### What Ship O does

- remove `PROACTIVE_TEMPLATES` only if fallback evidence says it is safe
- remove any now-dead template-only proactive path ownership
- keep narrow logged fallback only if reliability evidence says it is still required

### Acceptance criteria

- either:
  - templates are deleted, with reliability evidence cited
- or:
  - templates remain explicitly as fallback-only, and the brief records why Ship O did not yet delete them

Ship O should prefer honesty here over eagerness.

---

## Deliverable 5 — Collapse `pre_booking_auto_send.py`

### What Ship O does

- delete dead orchestration symbols
- move surviving shared helpers if necessary
- collapse the file toward zero runtime ownership

### Acceptance criteria

- every removed symbol has zero live call sites
- every surviving helper has a documented reason to remain
- the file either:
  - becomes a thin helper/shim with no alternate runtime ownership, or
  - is deleted entirely if imports hit zero

---

## Deliverable 6 — Retirement plan bookkeeping

### What Ship O does

Update [LEGACY_RETIREMENT_PLAN.md](/Users/dhuntermckenzie/Downloads/oyvoda/docs/architecture/LEGACY_RETIREMENT_PLAN.md) to reflect reality:

- `MIGRATING` -> `BRAIN-ACTIVE`
- `BRAIN-ACTIVE` -> `RETIRED`

Only flip to `RETIRED` when the code deletion is actually in the same commit set.

### Acceptance criteria

- status transitions match the codebase, not aspirations
- any deferred targets are left honestly marked

---

## Recommended commit order

Ship O should not be one giant delete commit.

Recommended order:

1. `ConciergeRunner` deletion commit
2. `VoicePod` runtime deletion commit
3. proactive template/fallback cleanup commit
4. pre-booking scaffolding collapse commit(s)
5. retirement-plan status update commit if not bundled with the deletes

Each commit should verify:

- `rg` zero-call-site proof for the removed symbol(s)
- focused tests for the replacement path

**Order note:** the order above is a default hypothesis, not a guarantee. Before implementation, confirm actual ship dates / elapsed production windows. `ConciergeRunner` is the most likely first target because Ships K and L landed before M and N, so its verification window is the most likely to have elapsed — but Ship O should follow evidence, not chronology aesthetics.

**Audit-ship rule:** prerequisite scope decisions should be split into small audit commits when they concern different questions or stakeholders. For example, a flag-off compatibility decision, a legacy endpoint usage audit, and a non-prod endpoint retirement decision do not need to be bundled into one patch. Ship O should prefer narrow audit commits over omnibus cleanup.

---

## Verification pattern

For each deletion target:

1. run `rg` for the symbol/module before deletion
2. patch the deletion
3. run `rg` again to confirm only allowed references remain
4. run focused tests on the replacement path
5. if relevant, smoke the live endpoint or caller seam

Ship O is successful when future engineers can ask:

`where does guest runtime ownership live?`

and the answer is:

`messaging_brain`

with no shadow runtime standing beside it.
