# Ship N — Proactive guest journey onto `messaging_brain`

**Status:** Brief written May 20, 2026, after Ship M moved the remaining reactive session channels off `VoicePod` and after a sweep of the still-live proactive paths.

**Scope discipline:** Ship N migrates **proactive guest outreach ownership** onto `messaging_brain`. It does **not** delete `ConciergeRunner` outright, does **not** redesign operator workflow UI, and does **not** introduce a template-only shortcut path beside Brain. It replaces the current split between `/concierge/proactive`, `stay_proactive_service`, and templated SMS with one Brain-owned proactive trigger path.

**Additive-only rule:** Ship N must not create a second proactive Brain beside the existing Brain. It must:

- reuse `GuestMessageBrainOrchestrator.handle_proactive_trigger(...)`
- add the missing real proactive specialist (`ProactiveOutreachAgent`)
- reuse canonical cadence/policy helpers where they already exist
- reuse canonical event-planning and property/session context services
- introduce only a thin trigger adapter where Brain currently lacks one

Ship N becomes a bad ship if it leaves proactive welcomes on template strings while also adding a Brain proactive path for the same guest journey.

---

## The decision this ship operationalizes

Once a guest books, the relationship has started. That booking event is not just a database fact; it is the first proactive guest-journey trigger. The system should have **one answer** to:

`how do we decide whether to welcome this guest, on what channel, with what message, using what context and policy gate?`

Today that answer is still split:

1. `/concierge/proactive` in [concierge.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/api/v1/endpoints/concierge.py)
   - still uses `ConciergeRunner`
   - still builds proactive messages outside Brain
2. [stay_proactive_service.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/operator/stay_proactive_service.py)
   - still owns eligibility/cadence text for:
     - `pre_arrival_welcome`
     - `arrival_day_checkin`
     - `in_stay_checkin`
     - `checkout_prep`
     - `extend_offer`
     - `service_update_reassurance`
3. `/sms/proactive` in [sms.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/api/v1/endpoints/sms.py)
   - still uses `PROACTIVE_TEMPLATES`
   - still bypasses Brain entirely
4. `messaging_brain`
   - already has `handle_proactive_trigger(...)`
   - already routes system topics to `ProactiveOutreachAgent`
   - but **no real `ProactiveOutreachAgent` exists yet**

Ship N resolves that by making the Brain the runtime owner for proactive guest messaging too.

---

## What Ship N ships

Five deliverables, in order:

1. **Create the real `ProactiveOutreachAgent`.**
2. **Create a Brain proactive trigger adapter.**
3. **Route booking/stay proactive decisions through Brain.**
4. **Move outbound message composition off template-only proactive paths.**
5. **Document the new proactive ownership boundary.**

No reactive-channel work in this ship. No VoicePod deletion in this ship.

---

## The load-bearing seam

The current proactive stack is split between:

- `ConciergeRunner` message suggestions from `/concierge/proactive`
- `StayProactiveService.evaluate(...)` deciding whether a touch should happen
- hardcoded `PROACTIVE_TEMPLATES` in `/sms/proactive`
- Brain system-event routes that point to a specialist that does not yet exist

That means:

- proactive lifecycle awareness is not Brain-owned
- welcome/check-in/checkout copy is not going through the same policy/composition path as reactive messages
- the guest’s first impression after booking is still vulnerable to template drift and split ownership

Ship N does **not** copy this whole stack into a second proactive subsystem. It moves trigger ownership and copy generation onto Brain, and reuses any existing policy/cadence helpers that remain canonical.

---

## What must stay single-source, not duplicated

The following are canonical helper/service concerns and must not be reimplemented as Brain-local copies:

- event-planning service
- property/session hydration
- stay workflow and receptiveness inputs where already canonical
- outbound transport senders (SMS/email/etc.)
- operator policy / escalation / observability services

The Brain should become the **caller**. These helpers should stay **single implementation** utilities.

---

## Deliverable 1 — Create the real `ProactiveOutreachAgent`

### What Ship N does

Implement the specialist that the router already expects:

- `system_welcome`
- `system_pre_arrival`
- `system_morning_brief`
- `system_extend_stay`
- `system_checkout_reminder`
- `system_post_stay`

This specialist owns proactive message decision/composition for system-triggered outreach. It must not be a template expander with a new private policy stack.

### Structural rule

Ship N creates **one** proactive specialist, not a parallel family of template handlers.

### Policy stance

Ship N keeps the same conservative policy posture as the Brain’s other migrated paths:

- proactive messages go through `ResponsePolicyAgent`
- the new specialist does **not** introduce an AUTO_SEND bypass
- if proactive sends are allowed live for a channel, that is because the Brain path approved them, not because the trigger bypassed policy

### Acceptance criteria

- A real `ProactiveOutreachAgent` exists.
- It is registered on the orchestrator, replacing the current stub resolution for proactive system topics.
- It handles all currently-routed system topics above.
- It composes proactive copy through Brain-owned logic rather than hardcoded template strings.

---

## Deliverable 2 — Create a Brain proactive trigger adapter

### What Ship N does

Add one thin adapter that converts proactive trigger sources into `OutboundIntent` for Brain consumption.

Sources in scope:

- booking-triggered welcome / pre-arrival outreach
- arrival-day check-in
- in-stay check-in
- checkout reminder
- extend-stay offer
- post-stay follow-up
- service-update reassurance when proactive policy allows it

### Required inputs

The adapter must preserve the data the current proactive paths already use:

- tenant/operator identity
- guest identity
- reservation/session token when present
- property binding
- lifecycle/phase
- stay dates
- policy/receptiveness/cadence snapshot where available
- property/session context facts
- channel preference / sending surface

### Channel tiebreaker rule

If the trigger source already specifies the sending surface, the adapter preserves it. If it does not, the Brain proactive path decides using this order:

1. explicit operator-configured preferred proactive channel for that property/tenant
2. otherwise SMS if a guest mobile number is present and the touch type is SMS-appropriate
3. otherwise email if a guest email is present
4. otherwise no send, with the trigger recorded as draft-only / unsent in audit

Ship N must not hide this choice behind transport defaults. The sending surface is an explicit Brain-side decision.

### Explicit lifecycle rules

Ship N must not reintroduce hidden lifecycle inference:

- booking-triggered welcome / pre-arrival reminder -> `PRE_ARRIVAL`
- arrival-day check-in -> `IN_STAY`
- in-stay check-in -> `IN_STAY`
- checkout reminder / extend offer on departure day -> `IN_STAY`
- post-stay follow-up -> `POST_STAY`
- service-update reassurance -> lifecycle comes from the active stay row; most commonly `IN_STAY`, but must honor `POST_STAY` when that is the active phase

### Acceptance criteria

- A single shared proactive trigger adapter exists.
- It produces `OutboundIntent` plus any needed metadata/context overlay for Brain consumption.
- It carries lifecycle explicitly rather than relying on later inference.

---

## Deliverable 3 — Route proactive decision ownership through Brain

### What Ship N does

Change the owning runtime for proactive guest outreach so Brain decides:

- whether a touch should happen now
- what lifecycle/system topic it is
- what copy draft should be produced

The decision boundary with `StayProactiveService.evaluate(...)` is explicit in this ship:

- `StayProactiveService` may remain as an **eligibility/cadence helper**
- the Brain becomes the **composition owner**
- the service no longer owns the final proactive message body

So the split is:

- helper decides: should this touch happen now, given cadence/receptiveness/prior touches?
- Brain decides: what proactive topic this is, what draft to compose, and what policy-approved outbound content should be used

The likely live call sites are:

- `/concierge/proactive` in [concierge.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/api/v1/endpoints/concierge.py)
- `StayProactiveService.evaluate(...)` in [stay_proactive_service.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/operator/stay_proactive_service.py)
- `/sms/proactive` in [sms.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/api/v1/endpoints/sms.py)

### Important nuance

This is an ownership cutover, not a transport rewrite:

- SMS sending remains SMS sending
- existing operator/workflow services can remain the trigger sources
- the Brain becomes the decision/composition owner they call

### Acceptance criteria

- `/concierge/proactive` no longer depends on `ConciergeRunner` for proactive message generation.
- `StayProactiveService` no longer owns the final proactive copy body; it may remain a cadence/input helper only if still useful.
- `/sms/proactive` no longer depends on `PROACTIVE_TEMPLATES` for canonical proactive content.
- Booking-triggered welcome flows through Brain, not a template shortcut.

---

## Deliverable 4 — Remove template-only proactive ownership

### What Ship N does

Retire template-only proactive copy as the canonical answer.

This does **not** mean deleting every literal string in the same ship. It means:

- template strings stop being the source of truth for proactive guest messaging
- Brain-produced drafts become the canonical proactive content
- any remaining literal templates are compatibility fallback only and explicitly marked as such

### Explicit fallback trigger

Template fallback is allowed only under a narrow, named failure condition:

- the Brain proactive composition path raises, or
- it returns an empty/invalid draft after its normal retry/fallback handling

In that case only, a compatibility template may execute as the transport fallback. When that happens, the path must emit an explicit audit marker in the same spirit as the existing Brain composer fallback discipline:

- a proactive composer/source marker indicating fallback execution
- a note explaining the failure cause (for example `proactive_composer_fallback:<ExcType>` or equivalent)

Template fallback is **not** allowed as an implementation shortcut for incomplete Brain integration. If the Brain path is available, it is the canonical path.

### Why this matters

The booking-triggered welcome is the guest’s first impression of Beach Habitats. It should pass through the same Brain context, policy, and composition discipline as reactive replies. Ship N explicitly rejects the shortcut of “proactive is simpler, so a template is good enough.”

### Acceptance criteria

- The canonical proactive welcome path is Brain-generated, not template-expanded.
- The canonical arrival/check-in/checkout/extend-stay paths are Brain-generated, not template-expanded.
- Any remaining fallback template use is triggered only by explicit Brain proactive composition failure and is audit-marked when it occurs.

---

## Deliverable 5 — Documentation cleanup

### What Ship N does

Update the relevant docs so they reflect:

- Brain owns proactive guest-journey messaging
- booking is a Brain-owned proactive trigger
- `ConciergeRunner` and template-only SMS proactive paths are transitional/fallback, not primary runtime

### Acceptance criteria

- The docs no longer describe proactive guest messaging as `ConciergeRunner`-owned once Ship N lands.

---

## What Ship N does **not** change

Ship N does **not**:

- delete `ConciergeRunner` outright in the same ship
- delete `VoicePod` outright in the same ship
- redesign operator dashboard proactive UI
- rewrite reactive channel routing
- change pre-booking/operator-review behavior

Those belong to later deletion/cleanup ships.

---

## Why this is additive and not duplicative

Ship N is additive because it:

- reuses `GuestMessageBrainOrchestrator.handle_proactive_trigger(...)`
- fills in the missing real proactive specialist rather than inventing a new runtime
- reuses canonical helper/services instead of rewriting them
- adds only the missing proactive trigger adapter seam

Ship N becomes duplicative if it:

- leaves `/concierge/proactive` and `/sms/proactive` as parallel canonical proactive runtimes after Brain lands
- adds a second proactive policy stack beside `ResponsePolicyAgent`
- keeps template-only welcomes as the “real” path while Brain proactive exists beside it

That is explicitly banned.

---

## Notes for the executor

- The first 30 minutes should confirm whether `StayProactiveService` is best treated as:
  - a retained cadence/input helper under Brain ownership, or
  - logic to absorb into `ProactiveOutreachAgent`
  Either is acceptable, but the decision must preserve one proactive owner.
- The booking-triggered welcome is the load-bearing moment in this ship. Get that path onto Brain first, then let the other lifecycle touches follow the same pattern.
- Do not special-case proactive as “safe enough for templates.” This ship exists to end that split.
