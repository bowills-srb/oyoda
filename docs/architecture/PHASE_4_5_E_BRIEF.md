# Phase 4.5.E — Brain knowledge-gap detection and hold-draft bridge

Date: 2026-05-20  
Phase: 4.5.E

## Decision

Knowledge-gap detection and knowledge-gap hold drafting move into the Brain
using the same bridge pattern already used in 4.5.A through 4.5.D:

1. create Brain-owned agents for the capability
2. add a narrow feature-flag bridge in
   `app/services/concierge/pre_booking_auto_send.py`
3. preserve legacy behavior while parity is measured
4. update the retirement plan to mark the legacy capability as Brain-active
   once the bridge is carrying traffic

This is a structural migration of existing proven logic. It is not a product
redesign and it is not Ship I. The dashboard and operator workflow stay as-is.

## Scope

Sub-phase 4.5.E covers exactly two legacy capabilities named in
[LEGACY_RETIREMENT_PLAN.md](/Users/dhuntermckenzie/Downloads/oyvoda/docs/architecture/LEGACY_RETIREMENT_PLAN.md):

1. `detect_missing_knowledge(...)`
2. `_generate_knowledge_gap_hold_draft(...)`

Both currently live in
[pre_booking_auto_send.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/concierge/pre_booking_auto_send.py)
and are still called directly from the live hybrid seam:

- `PreBookingPipelineOrchestrator.evaluate_routing()` calls
  `detect_missing_knowledge(...)`
- `PreBookingPipelineOrchestrator.draft()` calls
  `_generate_knowledge_gap_hold_draft(...)` when missing topics exist

This brief migrates those two decisions into Brain-owned agents and bridges the
legacy orchestrator to them behind a flag.

## Why this is next

4.5.A through 4.5.D already moved these adjacent decisions into Brain-owned
agents behind focused flags:

- 4.5.A: deterministic intake pre-filter
- 4.5.B: composer preference injection
- 4.5.C: policy enforcement
- 4.5.D: pricing-policy, portfolio matching, grounded fallback,
  verification hold, and LLM draft path

The remaining conspicuous legacy-only branch in the live pre-booking seam is
knowledge-gap handling. Until this moves, the production path is still:

- Brain for intake/classification/composition scaffolding
- legacy for knowledge-gap detection + hold-draft generation

4.5.E removes that next chunk of hybrid behavior without changing the operator
surface.

## Runtime shape

### New agents

- `app/services/messaging_brain/agents/knowledge_gap_agent.py`
  - owns missing-topic detection
  - returns a Brain-owned structured result equivalent to
    `KnowledgeGapAnalysis`
- `app/services/messaging_brain/agents/knowledge_gap_hold_agent.py`
  - owns the guest-facing hold draft when missing topics exist
  - returns `(draft_text, draft_source)` equivalent semantics to the legacy
    hold-draft path

### New bridge flag

- `BRAIN_GAP_DETECTION_PRIMARY`

Behavior:

- when `OFF`:
  - `evaluate_routing()` uses legacy `detect_missing_knowledge(...)`
  - `draft()` uses legacy `_generate_knowledge_gap_hold_draft(...)`
- when `ON`:
  - `evaluate_routing()` calls the Brain knowledge-gap agent
  - `draft()` calls the Brain hold-draft agent
  - legacy policy/draft scaffolding remains in place exactly as in 4.5.D

No shadow flag is required in this first cut unless parity work shows a real
need for dual-emission auditing. The shipped pattern so far is:

- primary flag when the result can be asserted by focused regression tests
- shadow flag only when production comparison metadata is materially valuable

Concrete trigger for adding a shadow flag:

- if the focused parity tests pass on synthetic fixtures but we cannot build a
  trustworthy regression fixture for at least one real Beach Habitats
  production knowledge-gap inquiry, then add `BRAIN_GAP_DETECTION_SHADOW`
  and run it for one canary observation window before enabling
  `BRAIN_GAP_DETECTION_PRIMARY`

If that trigger does not fire, a primary-only bridge is acceptable and
preferred.

## Agent contracts

### `KnowledgeGapAgent`

The Brain agent should preserve the semantics of the legacy path, not invent a
new model:

- inputs:
  - `message`
  - `intent`
  - `structured_asks`
  - `company_id`
  - `property_data`
  - `operator_policies`
- outputs:
  - a structured result containing:
    - `topic_classification`
    - `resolved_topics`
    - `gap_topics`
    - `ambiguity_flags`
    - `missing_topic_ids`

The fastest, safest implementation is to extract the current structured logic
into the Brain agent with minimal behavioral change:

- topic classification
- structured topic closure
- tagged FAQ hit
- evidence-hit fallback

This is the same philosophy used in 4.5.A: migrate proven logic verbatim into
the Brain side first, redesign later only if needed.

### `KnowledgeGapHoldAgent`

The Brain hold-draft agent owns the guest-facing copy when missing knowledge is
present.

- inputs:
  - `guest_name`
  - `platform`
  - `message`
  - `intent`
  - `property_data`
  - `operator_policies`
  - `company_id`
  - `db`
  - `missing_topics`
- outputs:
  - `draft_text`
  - `draft_source`

It should preserve the existing behavior envelope:

- deterministic fallback exists
- provider-backed upgrade path exists when configured
- no guessing
- same polished operator tone
- same `draft_source` semantics as legacy

`draft_source` decision for 4.5.E:

- preserve the literal legacy sentinel `kb_gap_required` for the no-provider /
  fallback hold path
- preserve the existing provider-derived shapes
  (`kb_gap_model_anthropic`, `kb_gap_model_groq`, `kb_gap_model_gemini`) when
  the provider-backed path succeeds

This is intentionally not renamed in 4.5.E. Downstream consumers already key
off these values, including dashboard-side knowledge-gap detection.

## Bridge points

### 1. Routing-stage bridge

In `PreBookingPipelineOrchestrator.evaluate_routing()`:

- today:
  - always calls legacy `detect_missing_knowledge(...)`
- after 4.5.E:
  - call Brain `KnowledgeGapAgent.analyze(...)` when
    `BRAIN_GAP_DETECTION_PRIMARY` is enabled
  - fall back to legacy `detect_missing_knowledge(...)` when disabled

Important constraint:

- the returned `missing_knowledge_topics` must preserve the exact meaning the
  downstream policy logic expects today
- `BRAIN_POLICY_PRIMARY` behavior must stay unchanged
- no changes to action-queue UI, review states, or persistence shape in this
  phase

### 2. Draft-stage bridge

In `PreBookingPipelineOrchestrator.draft()`:

- today:
  - if `decision_stage.missing_knowledge_topics`, call legacy
    `_generate_knowledge_gap_hold_draft(...)`
- after 4.5.E:
  - if `decision_stage.missing_knowledge_topics` and
    `BRAIN_GAP_DETECTION_PRIMARY` is enabled, call Brain
    `KnowledgeGapHoldAgent.maybe_compose(...)`
  - otherwise fall back to the legacy hold-draft function

This keeps the seam consistent with 4.5.D: Brain owns the capability, legacy
orchestrator still hosts the bridge until 4.5.F deletes the seam itself.

## Acceptance criteria

### Capability migration

- A Brain-owned
  [knowledge_gap_agent.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/messaging_brain/agents/knowledge_gap_agent.py)
  exists and covers the same missing-topic semantics as legacy
  `detect_missing_knowledge(...)`.
- A Brain-owned
  [knowledge_gap_hold_agent.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/messaging_brain/agents/knowledge_gap_hold_agent.py)
  exists and covers the same hold-draft semantics as legacy
  `_generate_knowledge_gap_hold_draft(...)`.
- A new feature flag `BRAIN_GAP_DETECTION_PRIMARY` exists in
  [feature_flags.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/feature_flags.py).

### Bridge behavior

- With `BRAIN_GAP_DETECTION_PRIMARY=OFF`, legacy behavior is unchanged.
- With `BRAIN_GAP_DETECTION_PRIMARY=ON`, `evaluate_routing()` uses the Brain
  knowledge-gap agent instead of the legacy function.
- With `BRAIN_GAP_DETECTION_PRIMARY=ON`, `draft()` uses the Brain hold-draft
  agent instead of the legacy function when missing topics exist.
- Existing `BRAIN_POLICY_PRIMARY` and `BRAIN_COMPOSER_PRIMARY` behavior is
  unchanged.

### Parity

- Focused unit tests demonstrate that Brain gap detection and legacy gap
  detection produce equivalent `missing_topic_ids` for representative cases:
  - property-scoped answer present
  - tagged FAQ answer present
  - evidence-hit answer present
  - true missing topic remains missing
  - negative-closure topic stays resolved, not missing
- At least one regression fixture is built from a real Beach Habitats
  production inquiry that currently exercises the legacy knowledge-gap path.
  Use a concrete `INQ-*` case captured from production so parity is proven
  against a known live gap shape, not only synthetic examples.
- Focused unit tests demonstrate that Brain hold drafts preserve the current
  behavior envelope:
  - deterministic fallback works with no provider keys
  - provider-backed path still respects no-guessing and returns usable copy
- Regression tests demonstrate that the live bridge in
  `PreBookingPipelineOrchestrator` switches correctly by flag.

### Documentation

- [LEGACY_RETIREMENT_PLAN.md](/Users/dhuntermckenzie/Downloads/oyvoda/docs/architecture/LEGACY_RETIREMENT_PLAN.md)
  is updated:
  - `4.5.E` entries describe the new bridge
  - statuses advance from `LEGACY-ACTIVE` to `MIGRATING` or `BRAIN-ACTIVE`
    based on what the commit actually accomplishes
- If a separate architectural note is helpful, add
  `docs/architecture/KNOWLEDGE_GAP_CANONICAL_PATH.md` in the same style as
  `CLASSIFIER_CANONICAL_PATH.md`

## Files anticipated to change

- `app/services/feature_flags.py`
- `app/services/concierge/pre_booking_auto_send.py`
- `app/services/messaging_brain/agents/knowledge_gap_agent.py`
- `app/services/messaging_brain/agents/knowledge_gap_hold_agent.py`
- `app/services/messaging_brain/agents/__init__.py`
- optionally `app/services/messaging_brain/orchestrator.py` only if shared
  Brain-side helpers belong there
- `tests/unit/test_knowledge_gap_agent.py`
- `tests/unit/test_knowledge_gap_hold_agent.py`
- `tests/unit/test_prebooking_intent_routing_regression.py`
- `docs/architecture/LEGACY_RETIREMENT_PLAN.md`
- optionally `docs/architecture/KNOWLEDGE_GAP_CANONICAL_PATH.md`

## Deliberately not in scope

- Ship I dashboard behavior
- queue reintegration of knowledge gaps
- KB-save-triggered retries
- regeneration path refactors
- `kb_gap_manager.py` retirement (`4.5.G`)
- orchestration/persistence cutover (`4.5.F`)

Those are later steps. 4.5.E is about moving the capability into the Brain,
not about changing the operator product.

## Test pattern

Follow the exact pattern already used in 4.5.A-D:

1. unit tests for the new Brain agent
2. regression tests for the legacy seam bridge
3. at least one real-production Beach Habitats gap fixture in the regression
   suite
4. retirement-plan update in the same commit

Recommended minimal commands:

```bash
node --check app/static/dashboard/js/main.js
pytest tests/unit/test_knowledge_gap_agent.py
pytest tests/unit/test_knowledge_gap_hold_agent.py
pytest tests/unit/test_prebooking_intent_routing_regression.py
```

The `node --check` line is not load-bearing for 4.5.E; include it only if any
dashboard-facing file is incidentally touched. The Python tests are the actual
gate here.

## Follow-on shape for 4.5.F

Once 4.5.E lands, 4.5.F gets much simpler:

- remove the remaining capability bridges from the legacy pre-booking
  orchestrator
- route inbound pre-booking directly through Brain orchestration
- move persistence to Brain-owned write helpers
- keep the operator-facing `pre_booking_inquiries` table
- keep path-agnostic send/alert helpers

The key sequencing logic is:

1. 4.5.E moves the remaining major decision branch into Brain-owned agents
2. 4.5.F moves the orchestration shell itself
3. 4.5.G deletes `kb_gap_manager.py`

That is the shortest path from today's hybrid seam to the retirement-plan end
state of "exactly one answer."
