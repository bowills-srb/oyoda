# Session 12 — LLM Composer Design

**Status:** design draft, pending review
**Phase:** C1 of `docs/IMPLEMENTATION_QUEUE_2026_05_05.md`
**Owner:** Hunter + Claude
**Predecessors:** Phase B (commit `edba367`) wired operator House Rules into
brain context and emitted KB gaps from the orchestrator. Both are
prerequisites for the composer.

## What this document is

A reviewable design artifact for the LLM composer that replaces the
current string-concatenation `_compose_response` at
`app/services/messaging_brain/orchestrator.py` line 709.

The composer is the unbuilt half of the brain. The Phase 0 design
assumed it. The current `_compose_response` docstring explicitly says
"Phase 1.3a strategy: concatenate non-empty draft_text in order with
a blank line between. Real composition (LLM-based merging, deduping,
tone smoothing) is a Phase 4 task." This is Phase 4.

This document is the contract Hunter is reviewing before any code is
written. If anything in here is wrong, fix it here, not in code.

## What this document is not

- Not a rollout plan. Rollout sequencing belongs in
  `docs/MESSAGING_BRAIN_PREBOOKING_BEACH_HABITATS_ROLLOUT.md` and gets
  updated after C2 ships.
- Not a Session 11 (knowledge schema) or Session 13 (portfolio) doc.
  Those depend on this composer being real and evaluated.
- Not a refactor of the legacy path. Legacy keeps doing what it does.

## Why this is the load-bearing piece

The brain today is two halves: deterministic specialists that produce
verifiable facts, and a stub composer that concatenates their templated
hold sentences. Until the composer is real, flipping
`MESSAGING_BRAIN_RUNTIME=true` for production traffic produces *narrower*
drafts than the legacy path, not better ones. That is not a design
choice. It is a deferred build step that was supposed to land before
the brain became default.

The composer turns the brain from "verifiable but narrow" into
"verifiable and synthesized." It is what makes the architecture's
verifiability promise also be a quality promise.

## Vocabulary (used precisely throughout this doc)

These terms are not interchangeable. Mixing them up was one of the
review issues with the first draft of this document.

- **Legacy path** —
  `app/services/concierge/pre_booking_auto_send.py::process_pre_booking_inquiry(...)`.
  The pre-existing pre-booking pipeline. Wraps an LLM call directly
  with its own grounding check and KB gap logging. Used today for any
  tenant where `MESSAGING_BRAIN_RUNTIME=off`. Not changed by this
  session.

- **Brain concatenation fallback** —
  `GuestMessageBrainOrchestrator._compose_response(...)`'s current
  string-join behavior. Lives inside the brain pipeline. Used today
  for any tenant where the brain runtime is on. Replaced by the LLM
  composer when the new flag is on, retained as the ultimate fallback
  when LLM providers fail.

- **Composer candidate output** — the synthesized text the
  `LLMComposerAgent` produces. May or may not become the
  operator-facing draft, depending on flag state and shadow mode.

- **Operator-facing draft** — the `response_text` on the
  `GuestResponseDraft` returned to whoever called the brain. This is
  what the operator sees in their dashboard.

When the doc says one of these, it means that one specifically.

## Design

### Contract

A new agent `LLMComposerAgent` lives at
`app/services/messaging_brain/agents/llm_composer_agent.py`.

**Inputs** (passed by the orchestrator at step 6):

- `message: InboundGuestMessage` — the original guest message.
- `decisions: List[AgentDecision]` — every specialist's structured
  output for this message. Each decision carries `intent_topic`,
  `confidence`, `evidence_used`, `missing_info`, `risk_flags`,
  `recommended_action`, `draft_text` (the templated hold), and
  `answer_summary`.
- `context: GuestContextBundle` — typed property facts, house rules,
  reservation facts, access info, FAQ, operator guidance text (B1),
  learned preferences block (already wired pre-B1).
- `policy: ResponsePolicyDecision` — final action and approval mode.
  Available to the orchestrator but **not passed into the LLM prompt**;
  see Q4 below.

**Output:**

- `ComposedResponse` — a small dataclass with:
  - `response_text: str` — the synthesized guest-facing reply (the
    composer candidate output, in the vocabulary above).
  - `composer_source: str` — one of `"llm_anthropic"`, `"llm_groq"`,
    `"llm_gemini"`, `"fallback_concatenation"`, `"fallback_empty"`.
  - `composer_latency_ms: int`
  - `composer_input_tokens: Optional[int]`
  - `composer_output_tokens: Optional[int]`
  - `composer_notes: List[str]` — coercion notes, fallback reasons,
    evidence-violation warnings.

The orchestrator's `_compose_response` returns `GuestResponseDraft`
unchanged in shape; only `response_text` source changes when the
composer is on. The composer's full result is also captured on the
`AgentAuditRecord` via a new optional field, described next.

### `ComposerMetadata` on `AgentAuditRecord`

A new dataclass `ComposerMetadata` is added to
`app/services/orchestration/messaging_brain_contracts.py`, mirroring
the shape established by `ClassifierMetadata` in Session 9.

```
ComposerMetadata:
    composer_source: str
    composer_response_text: str
    composer_latency_ms: int
    composer_input_tokens: Optional[int]
    composer_output_tokens: Optional[int]
    composer_notes: List[str]
```

`AgentAuditRecord` gets a new optional field:

```
composer_metadata: Optional[ComposerMetadata] = None
```

Additive, optional, default None — so any caller that doesn't construct
the field continues to work unchanged. Same compatibility contract as
`classifier_metadata` in Session 9.

**`composer_response_text` semantics — guardrail.**
`composer_response_text` is always the composer candidate output — the
text the LLM (or its concatenation fallback) produced. It is recorded
for audit and side-by-side comparison purposes. **It is recorded even
when shadow mode means the operator-facing draft comes from the brain
concatenation fallback rather than the composer.** The point of
shadow mode is to make composer output queryable next to whatever the
operator actually saw, so this field has to be populated whenever the
composer ran, regardless of whether its output reached the operator.

When the composer did not run at all (composer flag off, or empty
decisions list before the composer was invoked), `composer_metadata`
is None on the audit record. Distinguishing "composer didn't run" from
"composer ran but its output didn't reach the operator" is part of why
the field exists.

### Audit-writer persistence

Adding `composer_metadata` to `AgentAuditRecord` is necessary but not
sufficient. Today the audit writer
(`app/services/messaging_brain/audit.py::MessageEventStoreAuditWriter`)
persists only a curated subset of `AgentAuditRecord` fields into the
DB shadow surface. If composer metadata only lives on the in-memory
record, "queryable and side-by-side comparable" is a promise the audit
row cannot keep.

C2 must therefore include:

- Updating `MessageEventStoreAuditWriter` (and any sibling writers) so
  composer fields survive into the persisted audit row.
- Deciding on column shape: either flat columns
  (`composer_source`, `composer_response_text`, `composer_latency_ms`,
  `composer_input_tokens`, `composer_output_tokens`, `composer_notes`)
  or a single JSONB column `composer_metadata`. Lean toward flat
  columns for `composer_source` and `composer_response_text` (so
  operators can `WHERE composer_source = 'fallback_concatenation'`
  without parsing JSON), with a JSONB column for `composer_notes`
  since that's a list and rarely queried by SQL directly.
- A migration adding the new columns to the relevant table (likely
  `message_normalizations` or whichever shadow-surface table the audit
  writer targets — to be confirmed when reading the audit-writer code
  during C2).

The migration is part of C2's commit. The exact column names get
finalized when reading the audit-writer code; the design contract here
is "the composer's audit metadata must survive into the queryable
DB layer, not just the in-memory record."

### Provider chain

Mirrors `LLMIntakeAgent`'s pattern.

```
Anthropic Claude Haiku 4.5  (primary)
    ↓ (timeout / failure / no key)
Groq llama-4-scout           (secondary)
    ↓ (timeout / failure / no key)
Gemini 2.0 Flash             (tertiary)
    ↓ (timeout / failure / no key)
Brain concatenation fallback (ultimate fallback — current
                              _compose_response behavior)
```

**Timeouts:**

- Per-provider: 4.0 seconds (longer than intake's 2.5s because
  composition produces meaningfully more output tokens than
  classification, and we'd rather wait an extra second than fall back).
- Total budget: 6.0 seconds across the LLM chain. The brain
  concatenation fallback has no timeout — it's local string ops.

**Models hardcoded in the agent**, not pulled from `settings`. Same
choice as `LLMIntakeAgent`. Worth noting as a maintenance smell —
when models upgrade, three composer call sites and three intake call
sites need touching. Pulling all six into `settings` is in Phase F4
(swallow-path / config hygiene), not Phase C.

### The system prompt

The single most consequential design decision in this whole document.

**Discipline rule (the line that prevents fabrication):**

> If the relevant property facts, operator guidance, or specialist
> evidence is missing or uncertain, do not guess. Say you'll confirm
> the detail rather than fabricating it. The specialists below have
> already produced verified hold language for cases where they could
> not answer cleanly — preserve their tone of "I'm confirming the
> detail" rather than overwriting it with a guess.

This rule mirrors the legacy path's prompt at `pre_booking_auto_send.py`
which gets uncertainty-handling right: "If the relevant property facts
are missing or uncertain, do not guess. Say you'll confirm the detail
rather than fabricating it." We carry the same rule through.

**Inputs given to the LLM, in order:**

1. **Operator identity and channel**
   `You are writing a {channel} response on behalf of {operator_name}
   for {property_name}. Tone: warm, professional, 2-3 sentences max,
   conversational not corporate.`

2. **The guest's actual message**
   The newest guest turn from `message.text`, plus
   `message.full_thread_text` as background only.

3. **Specialist decisions block (lower priority than facts/guidance)**
   For each decision: agent name, intent topic, confidence, what they
   recommended (DRAFT_ONLY / AUTO_SEND / ESCALATE), the templated
   `draft_text` they produced, the `evidence_used` keys they cited,
   the `missing_info` they flagged, and any `risk_flags`.

   The composer reads this block as supporting material: synthesize one
   reply that respects the specialists' hedges and risk flags, but do
   not introduce or modify facts based on `draft_text` alone. Facts
   come from blocks 4, 5, and 6. Specialist drafts exist to preserve
   tone and "I'm confirming this" hedges, not to be a fact source.

4. **Property facts block**
   Pulled from `context.property_facts`, `context.house_rules`,
   `context.access_info`, `context.reservation_facts`. Only populated
   keys appear. Each fact is `key: value` on its own line with no
   editorial wrapping.

5. **Operator guidance block (B1's payload)**
   `## Operator House Rules & Policy (FOLLOW THESE EXACTLY)`
   followed by `context.operator_guidance` verbatim. Same framing as
   the legacy path. The "FOLLOW THESE EXACTLY" line is critical —
   without it, models tend to treat free-form guidance as suggestion.

6. **Learned preferences block (already wired pre-B1)**
   `context.learned_preferences_block` verbatim if non-empty.

7. **What not to do**
   - Do not negotiate prices.
   - Do not promise anything not listed in the facts above.
   - Do not include calls to action like "go ahead and book" or
     "submit a booking request" in pre-booking replies.
   - Do not use filler phrases like "Great question!".
   - Do not invent neighborhood facts, vendor recommendations, or
     amenities not listed.
   - **Do not contradict any specialist's missing-info note.** If a
     specialist said they're confirming a detail, the composer must
     preserve that hedge, not overwrite it with a confident-sounding
     guess.
   - **Do not derive facts from the specialist drafts in block 3.**
     Treat those drafts as tone references and hedge preservers, not
     fact sources.

8. **Output instruction**
   `Write the guest-facing reply now, in 2-3 warm sentences, grounded
   exclusively in the verified context above.`

### Evidence discipline

The composer is constrained to reason from:
- `context.property_facts`
- `context.house_rules`
- `context.access_info`
- `context.reservation_facts`
- `context.property_knowledge` (FAQ list)
- `context.operator_guidance`
- `context.learned_preferences_block`
- Each `decision.evidence_used` key (which references the same
  `context.evidence_keys` set)
- Each `decision.draft_text` — for tone and hedges only, not facts

Anything outside these is fabrication. The prompt says so explicitly.

The orchestrator's `_enforce_evidence_contract` already runs against
specialist decisions and logs violations when a specialist cites
evidence not in `context.evidence_keys`. The composer adds a parallel
check post-hoc: if the composer's output contains specific factual
claims not derivable from the inputs, that's a quality regression and
gets logged in `composer_notes`. Phase 1 of the composer does this as
a regex-based heuristic check (numbers, dates, named entities); Phase 2
(future) replaces it with a grounding pass like the legacy path's
`hallucination_guard.check_grounding`.

For Session 12 we ship the regex heuristic only. The full grounding
pass is its own follow-on task because the legacy `check_grounding`
takes a different input shape than the brain produces, and adapting
it correctly deserves its own design pass.

### Failure behavior

**Hierarchy of fallbacks:**

1. Anthropic returns valid output → use it. `composer_source = "llm_anthropic"`.
2. Anthropic times out or errors → try Groq.
3. Groq returns valid output → use it. `composer_source = "llm_groq"`.
4. Groq fails → try Gemini.
5. Gemini returns valid output → use it. `composer_source = "llm_gemini"`.
6. All three LLMs fail or no keys configured → fall back to brain
   concatenation fallback. `composer_source = "fallback_concatenation"`.
   This is exactly today's `_compose_response` behavior. **We never
   regress below today.**
7. Decisions list is empty → produce the existing fallback line
   "Thanks for the message — I'll get back to you shortly."
   `composer_source = "fallback_empty"`. This is also today's behavior.

**"Valid output" means:**
- Non-empty after stripping.
- At least 30 characters (mirrors legacy `_is_usable_draft`).
- Does not contain the obvious placeholder phrases legacy already
  catches ("could not generate", "we captured this guest email", etc.).
- Does not exceed the length cap (700 characters; see Q3 below). 700
  is chosen for a 2-3 sentence target, which is what the prompt asks
  for. Anything longer suggests the model is rambling and we'd rather
  fall through to the next provider.

If a provider returns invalid output, log it in `composer_notes` and
move to the next provider in the chain. Do not retry the same provider.

**The fallback chain is identical in structure to `LLMIntakeAgent`'s.**
Same provider order, same timeout pattern, same notes-recording
discipline. This is intentional: one mental model for both LLM-backed
brain agents. When models upgrade or providers misbehave, the fix
shape is the same.

### Flag wiring

New flag: `MESSAGING_BRAIN_LLM_COMPOSER`.

- Default OFF for all tenants.
- Resolved per-tenant via the standard three-tier path
  (property_code → company_id → platform default → False).
- Independent of `MESSAGING_BRAIN_RUNTIME`. The matrix:

  | runtime | composer | shadow | operator-facing draft | composer ran? | composer_metadata persisted? |
  |---|---|---|---|---|---|
  | OFF | * | * | legacy path output | no | no |
  | ON | OFF | OFF | brain concatenation fallback | no | no |
  | ON | ON | OFF | composer candidate output (with concatenation as ultimate fallback) | yes | yes |
  | ON | ON | ON | brain concatenation fallback | yes | yes — for compare |

  Row 4 is the explicit shadow-mode contract: composer runs and its
  output is recorded for compare, but the operator sees the
  concatenation result. This is how we validate composer quality
  against today's behavior before flipping the composer on for real.

  Row 2 is the "brain on but composer not yet" state — it's the
  current default for any tenant where `MESSAGING_BRAIN_RUNTIME=on`
  before C2 ships. Today's narrow-brain behavior. After C2, flipping
  the composer flag is the deliberate "now you get synthesized drafts"
  moment.

- Adding the flag mirrors how `MESSAGING_BRAIN_LLM_INTAKE` was added in
  Session 9: new constant in `app/services/feature_flags.py`, new
  env-default `OYVODA_MESSAGING_BRAIN_LLM_COMPOSER`, new lookup function
  `is_messaging_brain_llm_composer_enabled()`. Same shape, no new
  mechanism to learn.

### Shadow-mode plan

Shadow mode is how we validate the composer before flipping it on for
production traffic.

When `MESSAGING_BRAIN_RUNTIME=on` and `MESSAGING_BRAIN_LLM_COMPOSER=on`
and `MESSAGING_BRAIN_SHADOW_MODE=on`:

1. The brain runs end-to-end as it does today.
2. The composer also runs against the specialist decisions.
3. The composer's full result (including `composer_response_text`) is
   written to `AgentAuditRecord.composer_metadata` and persisted to
   the audit-writer's DB surface so it's queryable and side-by-side
   comparable with the operator-facing draft.
4. The brain concatenation fallback's draft (today's behavior) is
   what gets returned to the operator. Modules respect shadow mode
   and skip side effects, per `seam-map Rule 5`.

This lets us see the composer candidate output for every brain-routed
message before we trust it. We compare in the operator dashboard or
via a SQL query against the audit table. When a tenant's
shadow-comparison looks consistently good, we flip
`MESSAGING_BRAIN_LLM_COMPOSER=on` (without shadow) for them and the
composer becomes the source of truth.

This is the same shadow-mode discipline used to validate Session 9.
No new pattern to learn — except for the `composer_response_text`
persistence, which Session 9 didn't need.

### Cost considerations

At Beach Habitats's volume (~30 inquiries/day), the composer adds at
most one LLM call per message. Haiku 4.5 at ~$0.001-0.005/call is
~$0.05/day per operator. Negligible. Worth tracking via the
`composer_input_tokens` / `composer_output_tokens` audit fields so we
can monitor cost-per-tenant as the operator base grows.

If a tenant's total daily LLM cost exceeds an alerting threshold
(say, $50/day, 10000x current expected), Phase F observability work
will surface it. Not in scope for this session.

### What is explicitly NOT in this session

- **No grounding-check pass.** Phase 1 ships regex heuristics for
  composer output. Adapting `hallucination_guard.check_grounding` to
  brain input shapes is a future task.
- **No retraining or fine-tuning.** Models are off-the-shelf.
- **No streaming output.** Responses are synchronous, single-shot.
  The Gmail send path doesn't need streaming and adding it would
  complicate the failure-fallback logic.
- **No multi-language support.** English only. International is in
  the Sessions 13+ queue.
- **No operator-edit-as-feedback loop.** Capturing operator edits
  to the composer's drafts as future training signal is a real
  follow-on, but it's a separate piece of work.
- **No composer-vs-legacy diff UI.** The audit row carries the data
  (including `composer_response_text` persistence); a dashboard view
  of side-by-side drafts is a small follow-on.

## Test plan

Three test files, mirroring the structure of `LLMIntakeAgent`'s
tests (`test_llm_intake_agent.py` + `test_llm_intake_agent_smoke.py`).

### `tests/unit/test_llm_composer_agent.py`

Unit tests for the composer in isolation. No orchestrator, no full
pipeline. Mocks the three provider HTTP clients.

Cases:
1. Anthropic returns valid output → composer returns it,
   `composer_source="llm_anthropic"`, metadata populated including
   `composer_response_text`.
2. Anthropic times out → falls through to Groq → success.
3. Groq fails → falls through to Gemini → success.
4. All three providers fail → falls through to brain concatenation
   fallback, `composer_source="fallback_concatenation"`,
   `composer_response_text` is the concatenated output (so the audit
   row still records what the operator saw).
5. Empty decisions list → `composer_source="fallback_empty"`,
   `composer_response_text` is the existing "Thanks for the message"
   fallback line.
6. Anthropic returns output below 30 characters → invalid → falls
   through. Note recorded.
7. Anthropic returns output containing placeholder phrase → invalid
   → falls through.
8. Anthropic returns output exceeding 700 character cap → invalid →
   falls through.
9. No API keys configured at all → falls back to concatenation
   immediately, no LLM calls attempted.
10. Per-provider timeout enforced (4s).
11. Total budget enforced (6s across the chain).
12. **Operator-guidance precedence test:** when `context.operator_guidance`
    contains "no pets allowed" and a specialist's `draft_text` is
    warmer/more permissive about pets, the composer respects the
    operator guidance, not the specialist draft. (This is a real-API
    smoke case, but stub-mocked at the unit-test layer to verify the
    prompt shape sends operator_guidance with the FOLLOW THESE EXACTLY
    framing.)

### `tests/unit/test_llm_composer_agent_smoke.py`

Real-API smoke tests, gated on `OYVODA_RUN_LLM_SMOKE_TESTS=1` env
var so they don't run by default in CI. Mirrors
`test_llm_intake_agent_smoke.py`'s pattern.

Cases:
1. Anthropic with a real Beach Habitats-shaped pre-booking inquiry
   produces a draft that is non-empty, under 700 chars, and contains
   the property name.
2. Same for Groq.
3. Same for Gemini.
4. **Operator-guidance precedence:** with `context.operator_guidance="no
   pets allowed at this property"` and a specialist draft suggesting
   pets are welcome, the composer's output declines pets. Run against
   Anthropic.

### `tests/unit/test_orchestrator_uses_composer_when_flag_enabled.py`

Integration test for the orchestrator-composer wiring. Uses the same
mocking style as `test_orchestrator_emits_kb_gap_from_specialist_decisions.py`.

Cases:
1. Flag OFF: orchestrator's operator-facing draft comes from the brain
   concatenation fallback. `composer_metadata` is None.
2. Flag ON, composer succeeds: orchestrator's operator-facing draft is
   the composer candidate output. `composer_metadata.composer_source ==
   "llm_anthropic"`. `composer_metadata.composer_response_text ==
   composer candidate output`.
3. Flag ON, composer falls back through all LLM providers: operator-
   facing draft is the brain concatenation fallback.
   `composer_metadata.composer_source == "fallback_concatenation"`.
   `composer_metadata.composer_response_text == concatenation output`.
4. Flag ON, shadow mode: operator-facing draft is the brain
   concatenation fallback, but `composer_metadata.composer_source` is
   one of the LLM values and `composer_metadata.composer_response_text`
   contains the LLM's output (not the concatenation). This is the
   load-bearing test for the "store composer output even when it
   doesn't reach operator" guardrail.
5. Flag ON, empty decisions: orchestrator's operator-facing draft is
   the empty-fallback line. `composer_metadata.composer_source ==
   "fallback_empty"`. `composer_metadata.composer_response_text ==
   "Thanks for the message — I'll get back to you shortly."`.
6. **Audit-writer persistence test:** with a configured audit writer
   (not the no-op test mock), verify that after `handle_inbound_message`
   completes, the persisted DB row contains the composer fields. This
   is the test that catches "we added the field to the in-memory
   record but forgot to update the writer." May require a fixture
   that spins up the actual `MessageEventStoreAuditWriter` against a
   test DB or in-memory equivalent.

## Open questions resolved

These were the spots I expected pushback on. Recording the resolutions
here so future sessions don't relitigate them.

**Q1.** Composer sees `decision.draft_text` as input —
**resolved: yes, but lower-priority than facts and guidance.**
The prompt is updated to explicitly instruct the composer to use
`draft_text` for tone and hedge preservation only, not as a fact
source. Block 3 in the prompt is reframed accordingly.

**Q2.** `composer_source` annotation on operator dashboard —
**resolved: audit row only for Phase C.**
Dashboard surface is a small follow-on, not part of this session.

**Q3.** Output length cap — **resolved: 700 characters.**
1000 was too loose for a 2-3 sentence target. 700 is closer to the
legacy path's output lengths and tighter on rambling.

**Q4.** Composer sees `policy.confidence` and `policy.final_action` —
**resolved: no.**
Excluded from the prompt. Composer's job is "synthesize the
specialists' work," and policy is already deciding send/hold/escalate.
Including policy risks the composer second-guessing the gate.

**Q5.** Empty content from a provider —
**resolved: soft fall-through.**
Matches `LLMIntakeAgent`'s discipline. Keeps the brain online during
partial provider outages. Failure note recorded in `composer_notes`.

## What "done" looks like for C2 + C3

- `app/services/messaging_brain/agents/llm_composer_agent.py` exists
  and exports `LLMComposerAgent`, `ComposerMetadata`, `ComposedResponse`.
- `app/services/orchestration/messaging_brain_contracts.py` has the
  new `ComposerMetadata` dataclass and the
  `composer_metadata: Optional[ComposerMetadata]` field on
  `AgentAuditRecord` (additive, optional, default None).
- `app/services/feature_flags.py` exposes
  `MESSAGING_BRAIN_LLM_COMPOSER` and
  `is_messaging_brain_llm_composer_enabled(...)`.
- `app/services/messaging_brain/orchestrator.py::_compose_response`
  is updated to consult the flag, instantiate the composer when on,
  fall back to brain concatenation otherwise, and attach
  `composer_metadata` to the audit record.
- `app/services/messaging_brain/audit.py::MessageEventStoreAuditWriter`
  (and any sibling writers) updated so composer fields persist into
  the queryable DB layer, not just the in-memory record.
- A migration adding the new audit columns.
- All three test files pass.
- Existing `test_messaging_brain_ac_slice.py` and
  `test_messaging_brain_contracts.py` still pass (regression check).
- The brain runtime + composer flag both ON for one canary tenant in
  shadow mode, with composer candidate output queryable in the audit
  table next to the operator-facing draft.

## Resume line

Once this design doc is reviewed and approved, the next concrete steps
are:

1. Hunter signs off on the design (or asks for changes).
2. C2: implementation. `LLMComposerAgent`, contracts update,
   feature-flag wiring, orchestrator change, audit-writer update,
   migration.
3. C3: tests for all three layers including the audit-writer
   persistence integration test.
4. C4: commit "Session 12: LLM composer for messaging brain
   (flag-gated, default off)."
5. Phase D begins: pre-rollout safety items (gate read-state,
   brain-failure annotation).
