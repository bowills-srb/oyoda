# Ship L — Reactive concierge ownership into `messaging_brain`

**Status:** Brief written May 20, 2026, after Ship K made lifecycle an explicit Brain inbound input and after re-auditing what `ConciergeRunner` still owns in the live `/concierge/message` path.

**Scope discipline:** Ship L migrates **reactive** `/concierge/message` ownership from `ConciergeRunner` into `messaging_brain`. It does **not** move VoicePod, does **not** move proactive messaging, and does **not** delete `ConciergeRunner` wholesale if other channels still import it. It removes `ConciergeRunner` as the reactive runtime owner for `/concierge/message`.

**Additive-only rule:** Ship L must not duplicate capabilities already present in Brain agents. If Brain already owns a capability, Ship L routes to it. If `ConciergeRunner` still owns a capability Brain does not yet have, Ship L migrates only that missing capability. No parallel “Brain v2” agents, no duplicate FAQ/event/market systems, no second intent vocabulary.

---

## The decision this ship operationalizes

After Ship K, `/concierge/message` can enter the Brain with the correct lifecycle. The next remaining seam is ownership: the endpoint still uses a split runtime.

Today the `/concierge/message` stack is:

1. maintenance pre-track
2. FAQ direct-answer shortcut
3. event-planning shortcut
4. `ConciergeRunner.handle_message(...)`
5. BD insight suffix
6. post-reply gap capture

When the runtime flag is on, `_handle_via_brain(...)` bypasses most of that and calls the Brain directly, but the **capability inventory** is still defined by what the legacy path can do. Ship L makes Brain the canonical owner of the reactive concierge capabilities for this endpoint.

The important nuance is that `ConciergeRunner` is not purely “legacy logic waiting to move.” Parts of its old capability set already exist in Brain:

- maintenance → `MaintenanceAgent`
- WiFi / check-in / checkout / access → `AccessAgent`
- many property/house-rules asks → `HouseRulesAgent`
- booking/availability/group-size → `BookingInquiryAgent`

Ship L must **reuse those**, not recreate them.

What still remains uniquely owned by `ConciergeRunner` in the `/concierge/message` path is narrower:

- the simple reactive intent classification shell used by that endpoint
- late checkout / early check-in handling branch
- generic concierge response path for dining / events / local info / greetings / thanks / unknown fallback
- the fact that `/concierge/message` still treats the Brain and `ConciergeRunner` as two separate reactive runtimes

Ship L resolves that.

---

## What Ship L ships

Five deliverables, in order:

1. **Inventory and lock the overlap boundary.**
2. **Move `/concierge/message` reactive intent ownership fully onto Brain.**
3. **Migrate the remaining `ConciergeRunner`-only reactive capabilities into Brain.**
4. **Make `_handle_via_existing(...)` a compatibility fallback, not the definition of capability.**
5. **Document `ConciergeRunner` as no longer the reactive runtime owner for `/concierge/message`.**

No proactive work. No VoicePod work. No event-planning duplication.

---

## The overlap boundary — what Brain already has

These capabilities already exist in the Brain path and must **not** be reimplemented:

- [MaintenanceAgent](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/messaging_brain/agents/maintenance_agent.py)
- [AccessAgent](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/messaging_brain/agents/access_agent.py)
- [HouseRulesAgent](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/messaging_brain/agents/house_rules_agent.py)
- [BookingInquiryAgent](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/messaging_brain/agents/booking_inquiry_agent.py)

These map to much of what `ConciergeRunner` historically answered through its own executor path:

- maintenance
- WiFi
- parking / access / check-in / checkout
- some amenities / house-rules asks
- booking / availability / party-size style inquiries

Ship L must treat those as already-migrated.

---

## What still remains outside Brain for reactive `/concierge/message`

From [concierge_runner.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/concierge/concierge_runner.py), the remaining reactive ownership seams are:

1. **Late checkout request handling**
2. **Early check-in request handling**
3. **Dining / events / local-info / greeting / thanks / unknown concierge response path**
4. **The endpoint-level assumption that `ConciergeRunner` is the general reactive runtime**

Also note:

- FAQ direct-answer and weak-match gap logging in `_handle_via_existing(...)` are **canonical helper/service behavior**, not `ConciergeRunner` behavior
- event-planning shortcut is also a helper/service behavior, not `ConciergeRunner` behavior
- Brain should be allowed to call those helpers; Ship L must not duplicate them inside specialist agents unless there is a strong reason

---

## Deliverable 1 — Lock the overlap boundary

### What Ship L does

Before implementation, capture the overlap boundary in code/tests/comments:

- Brain already owns maintenance/access/house-rules/booking-inquiry
- Ship L must not add new agents for those domains
- if an ask currently routes through those existing agents, Ship L uses them as-is

This can be lightweight:

- a brief code comment in the ship’s implementation files
- regression tests showing the endpoint Brain path still routes these known asks through the existing agents

### Acceptance criteria

- No new Brain agent is introduced for maintenance, access, house rules, or booking inquiry in Ship L.
- Any new routing or intent-translation logic points those asks at the existing agents.

---

## Deliverable 2 — Move `/concierge/message` reactive intent ownership fully onto Brain

### What Ship L does

For the Brain-on path in `_handle_via_brain(...)`, make the Brain’s intake/router path the authoritative reactive classifier/dispatcher for `/concierge/message`.

Concretely:

- the endpoint should not rely on `ConciergeRunner.classify_intent(...)`
- the endpoint should not need a parallel legacy reactive intent shell once the request has entered the Brain

This deliverable is less about deleting code immediately and more about making the Brain path the one that defines how reactive asks are interpreted.

### Acceptance criteria

- When `MESSAGING_BRAIN_RUNTIME` is on, `/concierge/message` reactive intent ownership is entirely inside Brain.
- No Brain-on request depends on `ConciergeRunner.classify_intent(...)`.

---

## Deliverable 3 — Migrate the remaining `ConciergeRunner`-only reactive capabilities into Brain

### What Ship L does

Ship L adds Brain-owned handling only for the capability holes that are still uniquely owned by `ConciergeRunner`.

Those are expected to be:

1. **Late checkout**
2. **Early check-in**
3. **General concierge fallback / hospitality responses** for greetings, thanks, and uncategorized light concierge asks
4. **Dining / local-info / event-question orchestration**, but only to the extent needed to make Brain the owner of the decision path

Important constraint:

- Ship L should **reuse** the existing event-planning service and market/context helpers
- Ship L should **not** duplicate trip-planning, market-intelligence, or FAQ systems inside Brain

Ship L locks the structural shape up front:

- **one** new Brain specialist for operational permission asks:
  - handles both late checkout and early check-in
- **one** new Brain specialist for general concierge fallback / hospitality asks:
  - greetings
  - thanks
  - light dining / local-info / events concierge asks that do not already belong to existing Brain specialists
- event-planning remains a helper/service call, not a new specialist family

So Ship L adds at most **two** new specialists. No more.

### Policy stance

The new Ship L capabilities must default to the same conservative policy stance as the current Brain specialists:

- recommend `DRAFT_ONLY` by default
- let [ResponsePolicyAgent](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/messaging_brain/agents/response_policy_agent.py) make the final decision
- do **not** introduce an implicit AUTO_SEND shortcut for greetings, thanks, dining, or local-info asks

This matters because hospitality-style asks are exactly where autonomy can quietly widen. Ship L preserves the current retirement-plan discipline: no new reactive capability becomes auto-send by default just because it feels low-risk.

### Acceptance criteria

- A Brain-on late-checkout request no longer requires `ConciergeRunner` to produce a response.
- A Brain-on early-check-in request no longer requires `ConciergeRunner`.
- A Brain-on dining/local-info/events/greeting-style request no longer requires `ConciergeRunner` as the reactive owner.
- Existing helper services may still be called under the Brain path.
- The new operational-permission specialist recommends `DRAFT_ONLY` by default.
- The new general concierge specialist recommends `DRAFT_ONLY` by default.

---

## Deliverable 4 — Make `_handle_via_existing(...)` a compatibility fallback, not the definition of capability

### What Ship L does

After Deliverables 2 and 3, `_handle_via_existing(...)` remains only for:

- flag-off compatibility
- rollback safety
- operators not yet on the Brain runtime

It should no longer be the place where the “real” reactive concierge capability lives first.

This means:

- new reactive feature work after Ship L targets Brain only
- if a helper/service is called from both paths during transition, the helper remains canonical, but the Brain path is the owning caller for runtime-on traffic

### Acceptance criteria

- Brain-on `/concierge/message` requests can satisfy the supported reactive asks without falling back to `ConciergeRunner`.
- `_handle_via_existing(...)` remains a compatibility path, not the source of truth for supported behavior.

---

## Deliverable 5 — Documentation cleanup

### What Ship L does

Update the relevant architecture docs so they reflect the new ownership boundary:

- `ConciergeRunner` is no longer the reactive owner for `/concierge/message`
- Brain owns reactive concierge handling for runtime-on traffic
- helper services like FAQ/event-planning/knowledge remain canonical utilities, not alternative runtimes

### Acceptance criteria

- The docs no longer imply that `ConciergeRunner` is the canonical reactive path once the Brain runtime is enabled.

---

## What Ship L does **not** change

Ship L does **not**:

- migrate VoicePod / SMS / mobile chat
- migrate proactive messaging
- remove template-driven proactive SMS
- duplicate event-planning service logic inside Brain
- duplicate FAQ direct-answer logic inside Brain if the existing knowledge service remains canonical
- delete `ConciergeRunner` outright if other non-reactive or legacy paths still import it

Those belong to later ships.

---

## Why this is additive and not duplicative

Ship L is additive because it:

- reuses existing Brain specialists where they already exist
- reuses canonical services where they already exist
- migrates only the remaining ownership seams still unique to `ConciergeRunner`

Ship L becomes duplicative only if it:

- creates Brain copies of access / house-rules / booking-inquiry / maintenance logic
- reimplements event-planning or FAQ systems inside Brain
- leaves `ConciergeRunner` and Brain as equal reactive runtimes after the ship

That is explicitly banned.

---

## Verification pattern

1. Add focused tests for the new Brain-owned reactive capabilities.
2. Confirm existing Brain-path endpoint tests still pass.
3. For each migrated ask category, verify:
   - Brain-on path succeeds without `ConciergeRunner`
   - flag-off compatibility path still works
4. Run `python3 -m py_compile` on touched Python files.

### Suggested regression asks

- late checkout request
- early check-in request
- WiFi question
- parking/check-in/check-out question
- restaurant recommendation
- local events question
- greeting / thanks

These should be enough to prove that Brain owns the supported reactive surface without reintroducing duplicates.

---

## Files likely to change

- `app/api/v1/endpoints/concierge.py`
- `app/services/messaging_brain/agents/` for the truly missing reactive capabilities
- `app/services/messaging_brain/orchestrator.py`
- tests around `/concierge/message`

### Files likely not to change much

- `app/services/concierge/knowledge_service.py`
- `app/services/concierge/response_reviewer.py`
- `app/services/concierge/hallucination_guard.py`
- `app/services/concierge/concierge_runner.py`

If Ship L starts heavily rewriting those helper modules, scope is probably drifting.

---

## Follow-on ships this enables

Once Ship L lands:

- **Ship M** can converge VoicePod/SMS/mobile onto Brain
- **Ship N** can move proactive messaging onto Brain
- **Ship O** can continue the deletion arc around remaining concierge reactive scaffolding

Ship L is the bridge from “Brain is lifecycle-correct” to “Brain is the reactive concierge runtime owner.”
