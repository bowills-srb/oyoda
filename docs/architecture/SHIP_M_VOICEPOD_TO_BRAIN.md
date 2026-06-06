# Ship M — VoicePod reactive channels onto `messaging_brain`

**Status:** Brief written May 20, 2026, after Ships K and L moved `/concierge/message` lifecycle and reactive ownership into the Brain and after a sweep of the remaining non-Brain concierge runtimes.

**Scope discipline:** Ship M migrates the **reactive channel runtime** for SMS, mobile chat, mobile v3 chat, phone, and Gmail in-stay replies from `VoicePod` onto `messaging_brain`. It does **not** migrate proactive messaging, does **not** redesign the mobile UI, and does **not** duplicate VoicePod’s knowledge, escalation, or dining systems inside Brain. It replaces VoicePod as the reactive runtime owner for these channels.

**Additive-only rule:** Ship M must not create a second Brain beside the existing Brain. It must:

- reuse `GuestMessageBrainOrchestrator`
- reuse existing Brain specialists and policy gate
- reuse canonical helper/services where they already exist
- introduce only a thin channel/session adapter layer where Brain currently lacks one

Ship M becomes a bad ship if it recreates VoicePod’s router, quick-answer logic, retrieval stack, or escalation layer as a parallel Brain subsystem.

---

## The decision this ship operationalizes

Today the codebase still has **two live guest-message runtimes**:

1. `messaging_brain`
   - already owns `/concierge/message` runtime-on traffic
   - already owns pre-booking
   - already owns the new reactive concierge specialists from Ship L

2. `VoicePod`
   - still owns SMS in [sms.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/api/v1/endpoints/sms.py)
   - still owns mobile chat via `_run_voice_pod(...)` in [mobile_v2.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/api/v1/endpoints/mobile_v2.py)
   - still owns mobile v3 chat in [mobile_v3.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/api/v1/endpoints/mobile_v3.py)
   - still owns phone in [phone.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/api/v1/endpoints/phone.py)
   - still owns Gmail in-stay replies through `_generate_in_stay_reply(...)` in [gmail_inbox_poller.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/integrations/gmail_inbox_poller.py)

That is still two answers to “where does a guest message get handled?”

Ship M resolves that by making the Brain the runtime owner for those channels too.

---

## What Ship M ships

Five deliverables, in order:

1. **Create a Brain channel adapter for session-based guest channels.**
2. **Route SMS / mobile / mobile v3 / phone / Gmail in-stay replies through that Brain adapter.**
3. **Preserve VoicePod-only helper capabilities by reusing their canonical services, not by reimplementing them.**
4. **Make VoicePod a compatibility/fallback layer, not the owning runtime.**
5. **Document the new ownership boundary.**

No proactive migration in this ship.

---

## The load-bearing seam

The current channel entry points all converge on VoicePod:

- [sms.py::_generate_via_voice_pod](/Users/dhuntermckenzie/Downloads/oyvoda/app/api/v1/endpoints/sms.py)
- [mobile_v2.py::_run_voice_pod](/Users/dhuntermckenzie/Downloads/oyvoda/app/api/v1/endpoints/mobile_v2.py)
- [mobile_v3.py::guest_chat_v3](/Users/dhuntermckenzie/Downloads/oyvoda/app/api/v1/endpoints/mobile_v3.py)
- [phone.py::_generate_via_voice_pod](/Users/dhuntermckenzie/Downloads/oyvoda/app/api/v1/endpoints/phone.py)
- [gmail_inbox_poller.py::_generate_in_stay_reply](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/integrations/gmail_inbox_poller.py)

And `VoicePod.respond(...)` in [voice_pod.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/knowledge/voice_pod.py) still owns:

- route decision
- escalation shortcut
- quick-answer shortcut
- PMS-query handling
- retrieval / librarian use
- LLM response generation

Ship M does **not** copy those subsystems into a new Brain-side twin. It moves the **runtime entry** onto Brain and only extracts/reuses whatever helper seams are truly canonical.

---

## Explicit lifecycle rules by channel

Ship K made lifecycle an explicit Brain input. Ship M must not reintroduce silent lifecycle inference for session-backed channels. The shared channel adapter therefore owns lifecycle resolution with one explicit rule per channel:

- **SMS**: default to `IN_STAY`; if an active session row is present with `phase` in `pre_arrival`, `arrival_day`, `in_stay`, `departure_day`, or `post_stay`, map that phase authoritatively.
- **Mobile v2 / mobile v3**: same rule as SMS. Use the active session row when present; otherwise default to `IN_STAY`.
- **Phone**: use the active session row when present; otherwise default to `IN_STAY`. Phone is the loosest transport, so session truth wins whenever available.
- **Gmail in-stay replies**: force `IN_STAY`. This path only exists after reservation-aware inbound matching has already identified a live stay thread for reply generation.

Phase-to-lifecycle mapping:

- `pre_arrival` -> `PRE_ARRIVAL`
- `arrival_day` -> `IN_STAY`
- `in_stay` -> `IN_STAY`
- `departure_day` -> `IN_STAY`
- `post_stay` -> `POST_STAY`

This mapping lives in the shared adapter, not spread across five endpoints.

---

## What must stay single-source, not duplicated

The following are canonical helper/service concerns and must not be reimplemented as “Brain copies”:

- property/session hydration from the existing guest-session / property-router stack
- event-planning service
- dining reservation service
- knowledge retrieval services / librarian stack where still needed
- escalation ticket creation helpers
- watch-layer / observability logging

The Brain should become the **caller**. These helpers should stay **single implementation** utilities.

---

## Deliverable 1 — Create a Brain channel adapter

### What Ship M does

Add one thin adapter that converts a session-based guest-channel request into:

- `InboundGuestMessage`
- a rich `context_adapter_overlay`
- the correct `MessagingLifecycle`

This adapter is the bridge between session/channel context and Brain contracts.

It should be the new shared seam used by:

- SMS
- mobile chat
- mobile v3 chat
- phone
- Gmail in-stay replies

### Required inputs

The adapter must preserve what VoicePod currently gets from session/property context:

- tenant/operator identity
- guest identity
- reservation/session token
- property binding
- lifecycle/stage
- stay dates
- property context facts already available from property router / session row

### Review/send stance by channel

Ship M preserves the current product semantics of each transport rather than silently importing pre-booking review behavior:

- **SMS / mobile / mobile v3 / phone** remain live reactive channels. They keep their current direct guest-response behavior, gated by the Brain policy path rather than by VoicePod.
- **Gmail in-stay replies** also preserve their current direct-reply behavior in Ship M. This ship does **not** convert them into operator-review queue drafts. If a future ship wants Gmail in-stay to become review-first, that is a separate product decision.

The adapter must therefore carry enough channel metadata for downstream logging/source attribution to distinguish Gmail in-stay from the interactive transports, but the send/reply model stays as-is in this ship.

### Structural rule

Ship M adds **one adapter seam**, not four different one-off channel shims.

### Acceptance criteria

- A single shared adapter exists for session-based guest channels.
- It produces `InboundGuestMessage` plus any needed metadata/context overlay for Brain consumption.
- It carries lifecycle explicitly rather than relying on later inference.

---

## Deliverable 2 — Route the reactive channels through Brain

### What Ship M does

Change the owning runtime for:

- SMS inbound
- mobile chat
- mobile v3 chat
- phone chat
- Gmail in-stay reply generation

so they invoke the Brain adapter + `GuestMessageBrainOrchestrator`, not `VoicePod.respond(...)`.

### Important nuance

This is a runtime-ownership cutover, not a UI/product rewrite:

- Twilio webhook remains Twilio webhook
- mobile endpoint remains mobile endpoint
- mobile v3 endpoint remains mobile v3 endpoint
- phone endpoint remains phone endpoint
- Gmail reply flow remains Gmail reply flow

What changes is the AI runtime they call.

### Acceptance criteria

- SMS no longer requires `VoicePod.respond(...)` for reactive reply generation.
- Mobile chat no longer requires `VoicePod.respond(...)`.
- Mobile v3 chat no longer requires `VoicePod.respond(...)`.
- Phone no longer requires `VoicePod.respond(...)`.
- Gmail in-stay reply generation no longer requires `VoicePod.respond(...)`.
- All five paths call the shared Brain adapter.

---

## Deliverable 3 — Preserve helper capabilities without parallel Brain subsystems

### What Ship M does

Any capability currently reached through VoicePod that still matters must be handled one of three ways:

1. It already exists in Brain → route to the existing Brain specialist / policy path.
2. It is a helper/service concern → Brain calls the helper.
3. It is a small, load-bearing capability that is neither already in Brain nor a clean helper → add a narrowly-scoped Brain specialist in Ship M.

Examples:

- escalation helper logic should not become a second Brain escalation system
- dining booking should remain a helper/service call, not a new runtime
- trip/event planning should remain the canonical event-planning service

### Named decision rule for uncovered VoicePod capability

The executor should spend the first 30 minutes decomposing `VoicePod.respond(...)`, but the action rule is explicit:

- If the capability is already covered by an existing Brain specialist, reuse it.
- If the capability is a canonical helper/service, call that helper from Brain.
- If the capability is small and load-bearing for SMS/mobile/phone/Gmail parity, add one narrowly-scoped specialist in Ship M.
- If the capability is broader than that, do **not** smuggle VoicePod back in through a mega-adapter. Leave a narrow, explicit fallback at the channel boundary and document the follow-up ship needed to retire it.

### Specific non-goal

Do **not** port the entirety of `VoicePod.respond(...)` into one giant Brain agent. That just renames the second runtime.

### Acceptance criteria

- No “BrainVoicePodAgent” or equivalent mega-adapter is created.
- Existing Brain specialists remain the owners of their domains.
- Canonical helper/service behavior stays single-source.
- Any temporary fallback for an uncovered capability is narrow, explicit, and documented rather than hidden inside a Brain-side VoicePod clone.

---

## Deliverable 4 — VoicePod becomes compatibility/fallback only

### What Ship M does

After the cutover, VoicePod should no longer be the runtime owner of reactive guest message handling.

It may remain temporarily for:

- rollback
- legacy fallback
- non-migrated experiments

But it is no longer the place new reactive behavior is added first.

### Acceptance criteria

- New reactive feature work targets Brain only.
- VoicePod is no longer the canonical answer for SMS/mobile/mobile v3/phone/Gmail reactive handling.

---

## Deliverable 5 — Documentation cleanup

### What Ship M does

Update the relevant docs so they reflect:

- Brain owns reactive concierge handling across HTTP + session-based channels
- VoicePod is transitional/fallback, not the primary runtime
- proactive migration is still separate work

### Acceptance criteria

- The docs no longer describe VoicePod as the canonical runtime for these reactive channels once Ship M lands.

---

## What Ship M does **not** change

Ship M does **not**:

- migrate proactive SMS / pre-arrival / guest-journey triggers
- rewrite proactive templates into Brain
- delete VoicePod outright in the same ship
- redesign mobile or phone transport surfaces
- replace canonical service helpers with new Brain-local versions

Those belong to later ships.

---

## Why this is additive and not duplicative

Ship M is additive because it:

- reuses `GuestMessageBrainOrchestrator`
- reuses the Brain specialists already migrated in Ships K and L
- reuses canonical helper/services instead of rewriting them
- adds only the missing channel/session adapter seam

Ship M becomes duplicative if it:

- copies VoicePod’s router into a new Brain-local router
- copies retrieval/quick-answer/escalation subsystems into new parallel Brain utilities
- leaves Brain and VoicePod as equal reactive runtimes afterward

That is explicitly banned.

---

## Notes for the executor

- The first 30 minutes should be spent identifying which parts of `VoicePod.respond(...)` are true helper seams versus runtime ownership logic. Preserve the former, retire the latter.
- The adapter is the load-bearing design decision. If it is clean, the channel cutovers stay small. If each channel gets its own custom Brain translation, the ship will sprawl.
- Gmail in-stay reply generation is part of this ship because it currently reuses the same VoicePod seam. Leaving it behind would preserve a hidden second runtime.
