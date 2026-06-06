# Implementation Queue — 2026-05-05

This is the canonical work order consolidating three previously-separate
threads:

1. The Sessions 9-13 messaging-brain build queue, planned in the
   2026-05-01 conversation. Session 9 (LLMIntakeAgent) shipped.
   Sessions 10-13 were deferred and have not been built.
2. The Workstreams 1-6 safety/quality queue from
   `docs/SESSION_RESUME_2026_05_05.md`, focused on thin-grounding
   behavior, reply-channel mechanics, intake hygiene, thread-state
   modeling, hold-rate methodology, and deployment seam reliability.
3. The 2026-05-05 architecture audit (Areas 1-4) which surfaced new
   implementation items not covered by either of the above, and which
   resolved several handoff claims that turned out to be wrong.

The audit revealed one load-bearing fact that reframes everything:

> The messaging brain's `_compose_response` is currently a string
> concatenator. The docstring explicitly says "Phase 1.3a strategy:
> concatenate non-empty draft_text in order with a blank line between.
> Real composition (LLM-based merging, deduping, tone smoothing) is a
> Phase 4 task." The Phase 4 LLM composer that was the design's whole
> point of having structured specialist outputs has not been built.
> Verified at `app/services/messaging_brain/orchestrator.py` line 709.

Until the composer lands, the brain runtime is structurally narrower
than the legacy drafting path. Flipping `MESSAGING_BRAIN_RUNTIME=true`
for production traffic today would degrade response quality, not
improve it. This is not an architecture choice. It is a deferred
build step that has not landed.

This queue exists so the next session does not re-discover that fact.

## What is and isn't already wired

Verified against the current repo (not memory):

- **Cross-operator preferences** are wired into the brain. The
  `GuestContextBundle.learned_preferences_block` field exists in
  `app/services/orchestration/messaging_brain_contracts.py` (line 542),
  and `ContextBuilderAgent` already loads it via
  `build_preference_context(...)` in
  `app/services/messaging_brain/agents/context_builder_agent.py`
  (line 230). The earlier audit framing that "preferences may be
  swallowed" applies to the legacy path's injection, not the brain.
- **Operator guidance (House Rules text)** is *not* wired into the
  brain. The legacy path loads it via `_load_operator_guidance(...)`
  in `pre_booking_auto_send.py` and injects it verbatim into the
  system prompt. The brain has no field for it on
  `GuestContextBundle`. This is the real gap.
- **Hallucination guard / KB gap manager** are imported and called in
  the legacy concierge path. They are *not* imported anywhere under
  `app/services/messaging_brain/`. The "never imported" claim was
  wrong for legacy and right for the brain.
- **`_compose_response`** is concatenation only. Confirmed at
  `app/services/messaging_brain/orchestrator.py` line 709.

## Closed items from earlier sessions

- Session 9 (LLMIntakeAgent) — shipped. File:
  `app/services/messaging_brain/agents/llm_intake_agent.py`. Default
  off via `MESSAGING_BRAIN_LLM_INTAKE` flag.
- Stage 1 of topology cleanup — completed 2026-05-05. `oyvoda-worker`
  redeployed at `cc03cfcc` with `RUN_GMAIL_POLLING_WORKER=false`.
  Read-state regression resolved; verified via 12:44 inbound staying
  unread.
- §6.3 closed by `ecbbfd2`.
- §6.6 closed by `3599502`.
- §6.1 reframed and conditionally closed as Outcome B.

## Open items, sequenced for execution

The sequencing principle is: surgical brain-context wins first
(unlocks the composer), then the composer itself (the load-bearing
unbuilt piece), then pre-rollout safety items, then evaluation, then
the long tail.

### Phase B — Brain-context surgical wins

**B1. Route `_load_operator_guidance` output into the brain.**

The legacy drafting path loads the operator's free-form House Rules
text from the `operator_ai_guidance` table and injects it verbatim
into the system prompt. The brain path bypasses this entirely. Whatever
the operator writes in Settings → AI Guidance has no effect on brain-
path drafts today.

Concrete change:

- Add a new field `operator_guidance: str = ""` to `GuestContextBundle`
  in `messaging_brain_contracts.py`.
- Promote `_load_operator_guidance(company_id, db)` from a private
  helper in `pre_booking_auto_send.py` to a shared module that both
  the legacy path and the brain path consume. Suggested location:
  `app/services/concierge/operator_guidance.py`. Both call sites move
  to import from the new module. Behavior unchanged for legacy.
- In `ContextBuilderAgent.build()`, call the shared loader and
  populate the new field.
- Add `"operator_guidance"` to `evidence_keys` only when the field is
  non-empty.
- Update `_summarize_context` to surface `has_operator_guidance: bool`.

This is a precondition for the composer (Phase C): the composer must
see House Rules to produce operator-respectful drafts.

**B2. Emit KB gap from the brain orchestrator after specialist
decisions, using `AgentDecision.missing_info`.**

The legacy path calls `kb_gap_manager.log_gap_async` whenever
grounding flags or blocks. The brain path has no entry point into
this loop. When the brain holds a draft because of missing context,
no KB gap row is written, and cross-operator learning has nothing to
learn from.

The original B2 draft proposed emitting from `ContextBuilderAgent`
using `bundle.missing_context`. That is the wrong seam.
`ContextBuilderAgent.build()` only knows what context is absent, not
whether the guest actually needed that fact or whether a specialist
successfully answered anyway. Emitting at that layer creates noisy
false positives — operators would see KB gap rows for facts that
weren't relevant to the inquiry.

The right seam is after specialist decisions, using
`AgentDecision.missing_info`, which is each specialist's explicit
statement of what it needed and didn't have.

Concrete change:

- In `GuestMessageBrainOrchestrator.handle_inbound_message`, after
  step 5 (policy evaluation) and before step 6 (compose response),
  inspect each `AgentDecision.missing_info` list.
- For each non-empty `missing_info`, emit
  `kb_gap_manager.log_gap_async(...)` with the specialist's intent
  topic, the missing fact tags, the message text, and provenance
  (which agent produced the gap).
- Filter out the sentinel value `__stub_specialist__` so stub
  fallbacks don't pollute the gap table.
- Wrap the call in a try/except that logs at WARNING (not silent
  swallow). KB gap recording is best-effort; failure must not abort
  the pipeline, but it must be visible.
- Record in the audit record's `notes` that gaps were emitted (count
  and topics).

**B3. Tests.**

- `test_context_builder_agent_loads_operator_guidance.py` — verifies
  `operator_guidance` field is populated, surfaced in `evidence_keys`
  only when non-empty, and reflected in `_summarize_context`.
- `test_orchestrator_emits_kb_gap_from_specialist_decisions.py` —
  verifies that a specialist with `missing_info=["beach_access"]`
  produces a KB gap call with the expected shape, and that
  `__stub_specialist__` is filtered.

**Commit point.** "Wire operator House Rules into brain context;
emit KB gap from orchestrator after specialist decisions."

### Phase C — Session 12: LLM composer with rich evidence input

**C1. Design doc.**

Write `docs/SESSION_12_COMPOSER_DESIGN.md` covering:

- The `LLMComposerAgent` contract: input is `decisions: List[AgentDecision]`,
  `context: GuestContextBundle`, `policy: ResponsePolicyDecision`, and the
  original `InboundGuestMessage`. Output is `GuestResponseDraft` with
  `response_text` synthesized rather than concatenated.
- The system prompt shape, including the uncertainty-handling rule
  ("if grounding is thin, say you'll confirm rather than fabricating")
  that the legacy path's prompt already gets right.
- House Rules injection (consumes B1's `context.operator_guidance`).
- Cross-operator preferences injection (consumes the existing
  `context.learned_preferences_block` field, already populated by
  `ContextBuilderAgent` — no new wiring needed).
- Evidence-only synthesis: composer must reason from
  `context.property_facts`, `context.house_rules`, `context.access_info`,
  `context.operator_guidance`, `context.learned_preferences_block`,
  specialist `evidence_used`, and `decision.draft_text` only. Anything
  outside these is fabrication and the prompt must say so explicitly.
- Failure behavior: if all LLM providers fail, fall back to the
  Phase 1.3a string-concatenation path (current `_compose_response`)
  so we don't regress below today's behavior.
- Flag: `MESSAGING_BRAIN_LLM_COMPOSER`, default off, per-tenant
  resolvable via the standard three-tier path. Independent of
  `MESSAGING_BRAIN_RUNTIME` so brain-on/composer-off and
  brain-on/composer-on are separate rollout states.
- Shadow-mode plan: when both `MESSAGING_BRAIN_RUNTIME` and
  `MESSAGING_BRAIN_LLM_COMPOSER` are on but
  `MESSAGING_BRAIN_SHADOW_MODE` is also on, run the composer alongside
  the legacy path, persist both drafts side-by-side in the audit row,
  and compare.

This doc gets reviewed before any code is written for C2.

**C2. Implementation.**

- New file: `app/services/messaging_brain/agents/llm_composer_agent.py`.
- Provider chain: Anthropic Haiku 4.5 (primary) → Groq llama-4-scout
  (secondary) → Gemini (tertiary) → keyword concatenation (ultimate
  fallback). Same shape as `LLMIntakeAgent`.
- Per-provider timeout: 4s (longer than intake because composition
  produces more tokens). Total budget: 6s.
- Wire into `GuestMessageBrainOrchestrator._compose_response` behind
  the flag. The current concatenation logic stays as the fallback.

**C3. Tests.**

- Unit tests for the composer contract.
- Integration test that exercises the full brain pipeline with composer
  enabled and verifies it produces a synthesized response, not a
  concatenated one.
- Shadow-mode test that verifies both drafts land in the audit row.

**C4. Commit point.** "Session 12: LLM composer for messaging brain
(flag-gated, default off)."

### Phase D — Pre-rollout safety items

**D1. Gate read-state deviation.**

In `gmail_inbox_poller.py::_process_one_message`, the
`pre_booking_gate_skipped` branch unconditionally calls `_mark_read`.
Per `INBOUND_MESSAGE_GATE.md` design, audit-mode behavior should not
alter Gmail read state independently of the `GATE_REVIEW_ALL` flag.

Concrete change:

- Look up `INBOUND_MESSAGE_GATE_REVIEW_ALL` flag for the tenant in
  `_process_one_message` (or thread the value down from
  `dispatch_pre_booking` where it's already evaluated).
- Only call `_mark_read` if the operator has explicitly opted into the
  audit-mode-marks-read behavior. Default behavior preserves read state.

**D2. Brain-failure annotation in dispatch.**

In `email_dispatch.py::dispatch_pre_booking`, when
`PreBookingBrainOrchestrator.handle()` raises, the code logs and falls
through to legacy with `result = None`. The operator-facing draft then
appears as a normal legacy draft with no signal that the brain
attempted and failed.

Concrete change:

- `process_pre_booking_inquiry` does not currently accept a
  `draft_source` override; it derives one. Add an optional
  `draft_source_override: Optional[str] = None` parameter.
- When the legacy path runs after a brain failure, pass
  `draft_source_override="legacy_after_brain_failure"`.
- The operator dashboard should display a small badge for these drafts
  so we can spot patterns.

**D3. Commit point.** "Pre-rollout safety: gate read-state preservation
and brain-failure draft annotation."

### Phase E — Session 10: evaluation infrastructure

This was specified in the 2026-05-01 conversation and is what makes
"did this composer change actually help" answerable.

**E1. Schema.**

- New table: `evaluation_cases` with columns for `case_id`,
  `inbound_text`, `expected_intent_topic`, `expected_sub_intents`,
  `market`, `property_type`, `expected_draft_quality_label`
  (good/acceptable/bad), `notes`, `created_at`.
- New table: `evaluation_runs` with `run_id`, `commit_sha`,
  `composer_enabled`, `accuracy_overall`, `accuracy_by_market`,
  `created_at`.

**E2. Evaluator.**

- `tools/run_evaluation.py` — runs the current pipeline against every
  case, compares classification + draft against expectations, writes
  one `evaluation_runs` row.
- Nightly job (Celery beat or embedded worker) that runs the
  evaluator and reports.
- Easy way to add new cases as operators surface failure modes
  (a small operator-dashboard UI page or CLI tool).

**E3. Commit point.** "Session 10: evaluation infrastructure."

### Phase F — Long tail

These are real items but they are not blockers for the brain composer
shipping. They get done after E.

**F1. Stage 4 topology cleanup.** Retire `oyvoda-worker` or realign it
to `railway-worker.toml`. Pair with defaulting
`run_gmail_polling_worker=False` in `Settings` so opt-in is the
explicit invariant.

**F2. Stage 2 + Stage 3.** Verify Celery worker absence via Redis
queue depth check; audit beat schedule against embedded equivalents.

**F3. Dedup discipline.** `_is_already_processed` returns False on DB
exception. A DB hiccup can cause reprocessing. Decide whether to
fail-closed (raise) or add bounded retry, then implement.

**F4. Swallow-path observability.** Multiple swallow sites surfaced
in the audit. Prioritize:
- The shared `_load_operator_guidance` (B1 makes this load-bearing —
  must distinguish "no row" from "DB error").
- `build_preference_context` (cross-operator learning is invisible
  when this swallows; both legacy and brain paths use it).
- Canonical shadow persist (silently failing without instrumentation).

**F5. Commit `ota_inquiry_parsers.py` and its test suite** if it's
still on disk and still correct relative to the current
`email_parser_router.py`. Otherwise document why abandoned.

### Phase G — Session 11 + Session 13

Property knowledge schema improvements (Session 11) and portfolio
capability hardening (Session 13) come after the composer is real
and evaluated. Session 11 in particular benefits from having the
composer working so the schema improvements can be measured against
real composer output, not templated stand-ins.

## Provenance

- Sessions 9-13 sequence: 2026-05-01 conversation
  `94c881d3-e7fe-4b26-a7b6-d9fd254cff41`
- Workstreams 1-6: `docs/SESSION_RESUME_2026_05_05.md`
- Areas 1-4 audit findings + composer-not-built discovery: 2026-05-05
  audit session, this document
- Phase 0 brain audit (foundational): `docs/PHASE_0_BRAIN_AUDIT.md`
- Pre-booking rollout context:
  `docs/MESSAGING_BRAIN_PREBOOKING_BEACH_HABITATS_ROLLOUT.md`
- Rich-context rollout (Phase 1.3a follow-on):
  `docs/MESSAGING_BRAIN_RICH_CONTEXT_ROLLOUT.md`
- Seam maps: `docs/PHASE_1_3_SEAM_MAP.md`,
  `docs/PHASE_2_SEAM_MAP.md`

## Resume line

Next session reads:

1. This file.
2. `docs/SESSION_RESUME_2026_05_05.md` (the safety/quality
   workstreams it lists are still active and tracked here as
   Workstreams 1-6 → mostly absorbed into Phases D and F above).
3. Then proceeds to Phase B if it has not yet shipped, otherwise to
   the next unshipped phase in sequence.
