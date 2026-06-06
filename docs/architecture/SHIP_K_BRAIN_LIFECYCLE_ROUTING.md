# Ship K — Brain lifecycle-correct routing for `/concierge/message`

**Status:** Brief written May 20, 2026, after Phase 4.5.A-G landed and the remaining multi-runtime concierge seams were re-audited against live code.

**Scope discipline:** Ship K fixes the lifecycle ownership seam at the `/concierge/message` boundary. It does **not** migrate VoicePod, does **not** retire `ConciergeRunner`, and does **not** move proactive messaging. It makes the Brain path lifecycle-correct for `pre_booking`, `booked`/pre-arrival, `in_stay`, and `post_stay` without duplicating existing event-planning, FAQ, market, or knowledge services.

**Why this ship exists first:** Before we consolidate the rest of concierge onto the Brain path, the Brain path needs to know what lifecycle it is actually handling. Today `/concierge/message` can route to the Brain wrapper, but the wrapper does not map `request.stage` into an authoritative Brain lifecycle input. That means booked/pre-arrival and in-stay requests can silently enter the Brain and then be lifecycle-inferred later. Every larger consolidation ship depends on fixing that first.

---

## The decision this ship operationalizes

`messaging_brain` is the runtime owner of guest-message lifecycle decisions. The API boundary must pass lifecycle explicitly into the Brain, not rely on a default or a best-effort downstream inference.

This ship therefore does **one** load-bearing thing:

- when `/concierge/message` routes to `_handle_via_brain(...)`, the Brain receives an `InboundGuestMessage` whose lifecycle reflects the operator-facing `request.stage`

This ship deliberately does **not** try to solve the larger "multiple concierge runtimes" problem. It prepares that work by removing the lifecycle ambiguity at the first entry seam.

---

## What Ship K ships

Four deliverables, in order:

1. **Make lifecycle a first-class Brain inbound field.**
2. **Explicit stage → Brain lifecycle mapping in `_handle_via_brain(...)`.**
3. **Brain-path tests for all four lifecycle stages.**
4. **Boundary-documentation cleanup so the seam is no longer misleading.**

No feature flags. This is a correctness fix inside the already-flagged Brain path, not a new migration bridge.

---

## What's wrong now

In [concierge.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/api/v1/endpoints/concierge.py), `_handle_via_brain(...)` constructs an `InboundGuestMessage` from the HTTP request and calls `GuestMessageBrainOrchestrator.handle_inbound_message(...)`.

The shape mapping currently passes:

- tenant
- property
- reservation ID
- guest ID
- message text

But it does **not** pass `request.stage` into an authoritative Brain lifecycle field.

That matters because:

- [MessagingLifecycle](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/orchestration/messaging_brain_contracts.py) distinguishes `PRE_BOOKING`, `PRE_ARRIVAL`, `IN_STAY`, and `POST_STAY`
- [ResponsePolicyAgent](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/messaging_brain/agents/response_policy_agent.py) maps those lifecycle values into different autonomy-gate stages
- [ContextBuilderAgent](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/messaging_brain/agents/context_builder_agent.py) still contains best-effort lifecycle inference logic intended for older canary scenarios, not an authoritative API boundary

And there is a second seam underneath that one: [InboundGuestMessage](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/orchestration/messaging_brain_contracts.py) does not currently carry lifecycle as a first-class field. So the context builder falls back to lifecycle inference later in the pipeline.

So today the Brain wrapper can receive:

- `request.stage = "booked"` but no explicit Brain lifecycle
- `request.stage = "in_stay"` but no explicit Brain lifecycle
- `request.stage = "post_stay"` but no explicit Brain lifecycle

The real current hazard is therefore not "default to pre-booking." It is "drop lifecycle truth at the API boundary, then infer lifecycle later." That is exactly the kind of silent seam that creates drift when pre-arrival and in-stay capabilities start moving over.

---

## Deliverable 1 — Make lifecycle a first-class Brain inbound field

### What Ship K does

Extend [InboundGuestMessage](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/orchestration/messaging_brain_contracts.py) to carry a `lifecycle` field.

Recommended shape:

- `lifecycle: Optional[MessagingLifecycle] = None`

Then update [ContextBuilderAgent.build()](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/messaging_brain/agents/context_builder_agent.py) so:

- if `message.lifecycle` is present, it is authoritative
- only when `message.lifecycle` is absent does the builder fall back to `_lifecycle_from_classification(...)`

This preserves compatibility for older callers while making the `/concierge/message` Brain boundary explicit and correct.

### Acceptance criteria

- `InboundGuestMessage` has a first-class lifecycle field.
- `ContextBuilderAgent.build()` uses `message.lifecycle` when present.
- Existing callers that do not yet set lifecycle still work via the fallback inference path.

---

## Deliverable 2 — Explicit stage mapping into Brain lifecycle

### What Ship K does

In `_handle_via_brain(...)` in [concierge.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/api/v1/endpoints/concierge.py), add a single boundary mapping function:

`request.stage` → `MessagingLifecycle`

Exact mapping:

- `pre_booking` → `MessagingLifecycle.PRE_BOOKING`
- `booked` → `MessagingLifecycle.PRE_ARRIVAL`
- `in_stay` → `MessagingLifecycle.IN_STAY`
- `post_stay` → `MessagingLifecycle.POST_STAY`

This mapping should live in a small helper such as:

`_request_stage_to_brain_lifecycle(stage: str) -> MessagingLifecycle`

The helper is the only place that decides. `_handle_via_brain(...)` calls it when constructing `InboundGuestMessage`.

### Why `booked` maps to `PRE_ARRIVAL`

The public API still uses the older operator-facing stage vocabulary:

- `pre_booking`
- `booked`
- `in_stay`
- `post_stay`

The Brain uses:

- `PRE_BOOKING`
- `PRE_ARRIVAL`
- `IN_STAY`
- `POST_STAY`

So `booked` is not a Brain lifecycle value. It is the API's pre-arrival label and must map to `PRE_ARRIVAL`.

### Acceptance criteria

- `_handle_via_brain(...)` sets lifecycle explicitly on every `InboundGuestMessage` it constructs.
- `request.stage="pre_booking"` results in `MessagingLifecycle.PRE_BOOKING`.
- `request.stage="booked"` results in `MessagingLifecycle.PRE_ARRIVAL`.
- `request.stage="in_stay"` results in `MessagingLifecycle.IN_STAY`.
- `request.stage="post_stay"` results in `MessagingLifecycle.POST_STAY`.
- The `/concierge/message` Brain path no longer relies on downstream lifecycle inference for lifecycle truth.

---

## Deliverable 3 — Lifecycle-stage tests on the Brain path

### What Ship K does

Extend the `/concierge/message` Brain-path test coverage so this seam stays locked.

Tests should patch the Brain orchestrator and assert the actual `InboundGuestMessage` passed to `handle_inbound_message(...)` contains the expected lifecycle value for each incoming stage.

Required cases:

1. `pre_booking` request → Brain gets `PRE_BOOKING`
2. `booked` request → Brain gets `PRE_ARRIVAL`
3. `in_stay` request → Brain gets `IN_STAY`
4. `post_stay` request → Brain gets `POST_STAY`

These belong in [test_concierge_endpoint_brain_path.py](/Users/dhuntermckenzie/Downloads/oyvoda/tests/unit/test_concierge_endpoint_brain_path.py) if that remains the seam test file. If the current environment dependency issue (`python-jose`) makes that test hard to run locally, add a narrower unit test for `_handle_via_brain(...)` that avoids the full dependency chain. The important thing is that the lifecycle mapping is asserted in code, not left manual.

### Acceptance criteria

- There is an automated test for each of the four stage mappings above.
- The tests assert on the `InboundGuestMessage` actually sent into the Brain orchestrator.
- No test infers lifecycle indirectly from response text or side effects.

---

## Deliverable 4 — Boundary documentation cleanup

### What Ship K does

Update the `_handle_via_brain(...)` docstring and any nearby seam comments so they accurately describe the lifecycle mapping.

The current shape-mapping section should explicitly say:

- `request.stage="booked"` maps to `MessagingLifecycle.PRE_ARRIVAL`
- lifecycle is passed into the Brain at the API boundary
- downstream lifecycle inference is no longer relied upon for `/concierge/message`

If the stage mapping lives in a helper, document the helper and keep the docstring concise.

### Acceptance criteria

- `_handle_via_brain(...)` no longer implies lifecycle is omitted or inferred downstream.
- The code comments match the actual mapping logic.

---

## What Ship K does **not** change

This is the most important scope guard in the brief.

Ship K does **not**:

- migrate `ConciergeRunner` capabilities into Brain
- retire `ConciergeRunner`
- change SMS / VoicePod routing
- change Gmail in-stay reply generation
- move `/concierge/proactive` onto `handle_proactive_trigger(...)`
- duplicate event-planning or market-intelligence logic inside Brain
- rewrite FAQ handling
- add a second context builder or a second lifecycle enum

Those are later consolidation ships.

Ship K is strictly the lifecycle-correct Brain boundary fix.

---

## Why this is additive and not duplicative

Ship K does not create a new lifecycle system.

It reuses:

- existing API stage vocabulary in [concierge.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/api/v1/endpoints/concierge.py)
- existing `MessagingLifecycle` enum in [messaging_brain_contracts.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/orchestration/messaging_brain_contracts.py)
- existing Brain orchestrator entrypoint in [orchestrator.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/messaging_brain/orchestrator.py)
- existing Brain policy mapping in [response_policy_agent.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/messaging_brain/agents/response_policy_agent.py)

The ship adds only:

- one lifecycle field on the existing inbound contract
- one explicit mapping helper at the boundary
- tests that enforce it

That is exactly the right additive shape.

---

## Verification pattern

1. Implement the lifecycle field, the stage-mapping helper, and the `_handle_via_brain(...)` change.
2. Run `node --check` is not relevant here; this is a Python ship.
3. Run `python3 -m py_compile` on touched Python files.
4. Run the focused lifecycle-mapping tests.
5. If the existing endpoint test file is blocked by missing local dependencies, note that explicitly and add the narrow unit coverage that keeps Ship K honest anyway.

### Files anticipated to change

- `app/services/orchestration/messaging_brain_contracts.py`
- `app/api/v1/endpoints/concierge.py`
- `app/services/messaging_brain/agents/context_builder_agent.py`
- `tests/unit/test_concierge_endpoint_brain_path.py` or a new narrow seam test file

### Likely no-change files

- `app/services/messaging_brain/orchestrator.py`
- `app/services/messaging_brain/agents/response_policy_agent.py`

If this ship starts touching those files, pause and ask whether scope is drifting. It probably is.

---

## Follow-on ships this enables

Once Ship K lands, the next consolidation ships become much safer:

- **Ship L** — migrate `ConciergeRunner` reactive ownership into Brain
- **Ship M** — converge VoicePod/SMS/mobile onto Brain
- **Ship N** — move proactive messaging onto Brain
- **Ship O** — delete remaining `pre_booking_auto_send.py` scaffolding

Ship K is intentionally small because every one of those later ships depends on lifecycle truth at the first Brain entry boundary.
