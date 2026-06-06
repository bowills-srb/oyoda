# Phase 4.5 — Legacy-to-Brain Migration Arc

## The constraint that governs this entire phase

The new brain (`app/services/messaging_brain/`) is the only runtime pipeline. The legacy pre-booking path (`app/services/concierge/pre_booking_auto_send.py` and its helpers) is a deprecation target. Every useful capability in legacy migrates *into* the brain in a named sub-phase, then the legacy implementation is deleted. Nothing valuable is thrown away; everything valuable moves.

The reasoning is in `docs/architecture/LEGACY_RETIREMENT_PLAN.md`, which is the source of truth for the inventory. This brief is the execution plan.

Two pipelines is a permanent cost. The brain was built specifically to handle 100K+ units and 1K+ operators; keeping legacy alive undermines what the brain was built for. After this arc, when a future session asks "where does X happen?", there is exactly one answer, and that answer is in `messaging_brain/`.

## Hard constraints (apply to every sub-phase)

- **Brain-only target**. No new code in legacy. Every sub-phase moves code *out* of legacy or marks it for deletion.
- **No throwing away**. If a legacy capability is useful, it migrates. If it's not useful, the audit doc explains why and it gets deleted.
- **Accuracy first, then cost discipline**. The system must produce 90-95% accurate auto-sent drafts — below that, the business doesn't work. Within that accuracy bar, the cost target is 60-70% of inquiries auto-resolved (deterministic-certain + LLM-grounded with auto-send confidence) and the remainder held for operator review. Deterministic layers do not guess: they either get it right with near-100% precision or they hand off. See the *Accuracy and cost discipline principles* section below for the rules this implies.
- **Parity before cutover**. Each sub-phase ends with a parity check: a real production message produces equivalent or better output through the brain compared to legacy. The Christina Moser case is the canonical regression message; each sub-phase adds at least one more case from production.
- **Feature flag per cutover**. Each sub-phase adds a flag so its specific migration can roll back per-piece if production behavior degrades.
- **Tenant-isolated, audit-first, schema-shape regression preserved**. Same disciplines as 4.3/4.4.
- **Specific exception handling**, `safe_rollback`, no bare `except Exception`.
- **Documentation alongside code**. After each sub-phase, update `LEGACY_RETIREMENT_PLAN.md` with new statuses (LEGACY-ACTIVE → BRAIN-ACTIVE → RETIRED) and the relevant architecture doc.
- **Each sub-phase ships independently**. Do NOT combine. Audit-first discipline is the whole point of the arc.

## Accuracy and cost discipline principles

The brain serves two non-negotiable targets, in priority order:

1. **Accuracy** — 90-95% of auto-sent drafts must be correct (operator does not need to correct or recall them).
2. **Cost** — 60-70% of inquiries should auto-resolve (deterministic-certain or LLM-grounded auto-send) so LLM costs stay sustainable at 100K+ units.

The two are not in conflict, but only if the architecture respects a strict precision-over-coverage discipline. The shape is **three layers**, not two:

```
Layer 1 — Deterministic-certain    → near-100% precision, coverage = whatever it is
                                       resolves easy structurally-unambiguous cases
Layer 2 — LLM-grounded               → 90%+ accuracy via grounding review
                                       handles synthesis where source is well-defined
Layer 3 — Operator review            → 100% accuracy (human in the loop)
                                       handles everything Layers 1 and 2 weren't confident on
```

The 60-70% cost target = Layer 1 + Layer 2 auto-send. The remaining 30-40% goes to Layer 3 and that's fine — pre-booking is already designed around operator approval, and a held draft approved by an operator is a correct outcome.

### The precision principle (rule zero)

**Deterministic layers do not guess. They either get it right with near-certainty or they hand off.**

This is the rule that everything else hangs on. The temptation under cost pressure is to lower the deterministic confidence threshold to capture more inquiries cheaply. That trade is fatal at a 90-95% accuracy target. A deterministic layer at 80% accuracy with 70% coverage produces 56% correct drafts before any LLM runs — well below the accuracy floor.

Correct deterministic resolution at the precision the business needs looks like:

- **Property-data direct answer**: only when the message asks about a field that exists in `pms_listings` with a definite value (e.g. `wifi_available=true`, `has_washer_dryer=true`). Not "if the message contains 'pool'" — only if the inquiry maps unambiguously to the property fact.
- **FAQ match**: only when the guidebook FAQ token-overlap is high enough that the match is structural, not approximate.
- **Templated responses**: only when the template *is* the answer (verification follow-up, knowledge-gap hold, portfolio-match-not-grounded hold). These don't claim correctness; they claim "I'm checking."
- **Pricing-policy decline**: only when the exact pattern fires (`'discount' AND 'first time' AND direct-channel`). One mis-classification here sends a wrong policy reply.

When the deterministic layer can't hit that bar, it hands off to Layer 2 (LLM-grounded) or Layer 3 (operator review). Coverage stays where precision allows it. The healer grows coverage *correctly*, not by lowering thresholds.

### Cost discipline rules

These rules implement the cost target *while preserving* the precision principle:

1. **Every brain stage tries the deterministic path first.** Classification, policy enforcement, knowledge-gap detection, draft composition, fallback answers. LLM is the escalation, not the entry point. The deterministic path either resolves with high precision or returns "not certain, escalate" — never "low-confidence guess."

2. **The healer keeps the deterministic layer growing in coverage, not relaxing in precision.** Healer proposals add new correct patterns (operator-approved keywords, aliases, FAQ entries). Operators see the cluster evidence before approving so they catch incorrect proposals before they ship. The deterministic layer never gets a relaxed threshold; it gets more specific patterns.

3. **The healer itself must be deterministic.** An LLM-per-audit-row healer moves the cost from per-inquiry to per-audit, often at a higher rate. Healers analyze deterministic signals using deterministic techniques: token frequency, Jaccard overlap, dict grouping, threshold counting. The current healer (commit 82f9bb9) respects this.

4. **If a healer scanner ever needs LLM judgment, it operates on clusters, not rows.** One LLM call per cluster of 5-20 rows is cheap; one per row at 20K rows is not. Rare carve-out, used sparingly.

5. **Healers run on a schedule, not per-inquiry.** Daily Celery beat. Cost scales with proposal volume (small), not inquiry volume (large).

6. **Per-inquiry LLM calls are budgeted.** The brain calls LLM for: classification escalation (when deterministic confidence < threshold), draft composition (when deterministic-certain doesn't apply), and grounding review (post-composition). That's the budget. New per-inquiry LLM uses need explicit justification and a cost model.

When Codex implements anything in this arc, two questions to ask before any addition:

- **Precision**: "Could this layer produce a wrong answer with high confidence?" If yes, the threshold is wrong and needs to be tightened or the layer needs to hand off instead.
- **Frequency**: "Is this per-inquiry, per-cluster, or per-day?" Per-inquiry is the expensive default; per-cluster and per-day are cheap.

### Healer approval safeguards

A bad healer-approved override is more expensive than no override at all — it turns the deterministic layer into a confident wrong-answer machine for that tenant. The approval flow must make it cheap to approve correctly and hard to approve incorrectly:

- **Show the evidence cluster**. The operator sees the actual messages that triggered the suggestion, not a summary. Approving "add 'pool' to pool_heat keyword set" requires reading the 3-5 source messages that supposedly justify it.
- **Show the proposed effect**. Before approval, the API surfaces: "This change will reclassify N historical messages — review them to confirm." The operator can see whether the change would have correctly routed past traffic.
- **Reversibility**. Approved overrides must be removable. The brain pre-filter reads `operator_settings.extra.intent_classifier_keyword_overrides`; the operator dashboard needs a UI to view and remove individual entries from that dict. Without a remove path, a bad approval is permanent until engineering intervenes.
- **Post-approval quality monitoring**. After an override ships, the next 24-48 hours of inquiries that the override touches are watched. If grounding-failure rate or operator-correction rate on those inquiries spikes, the healer surfaces a "recent override may be causing regressions" signal. This is a future capability and need not ship in 4.5.A, but the data plumbing should be in place.

### Measurement requirement (cross-cutting)

The accuracy and cost targets are unmeasurable today. Before the arc ships, the brain must produce:

- **Per-tenant deterministic-resolution rate**: % of inquiries resolved in Layer 1 (deterministic-certain). Computed from `brain_classifier_metadata` and the composer's draft_source field.
- **Per-tenant auto-send rate**: % of inquiries auto-sent (Layer 1 + Layer 2 with auto-send). Computed from `pre_booking_inquiries.send_decision`.
- **Per-tenant correction rate**: % of auto-sent drafts that the operator later corrected or recalled. This is the precision signal. Computed by joining `pre_booking_inquiries` with `operator_draft_events` where event_type = 'edited' or 'rejected' on a status that was already 'sent'.
- **Per-override quality score**: for each operator-approved healer override, the rate at which subsequent inquiries that match the override were correctly handled (operator didn't edit) vs incorrectly (operator edited). Surfaces bad overrides for revocation.

These metrics are part of the verification criteria for each sub-phase. Without them, we can't confirm we're hitting the accuracy bar; without them, the healer can't self-correct.

## Migration ordering rationale

The sub-phases are ordered to minimize blast radius AND to preserve cost discipline through every cutover. A naive ordering would migrate `LLMComposerAgent` first and route every draft through LLM during the transition window. The ordering below avoids that by ensuring deterministic paths land in the brain before any cutover makes LLM the default.

1. **Classification** (4.5.A) first — establishes the deterministic-first pattern at the intake layer. The keyword pre-filter lands before LLM intake becomes primary.
2. **Operator learning** (4.5.B) — moves the preference-injection point without changing draft generation yet. Pure data plumbing.
3. **Policy enforcement** (4.5.C) — pure deterministic functions, easy to mirror in the brain's policy agent. Always free of LLM cost.
4. **Draft generation** (4.5.D) — the largest sub-phase, internally ordered to migrate deterministic fallbacks FIRST and the LLM composer LAST. This prevents the regression where every draft routes through LLM during the cutover window.
5. **Knowledge-gap detection** (4.5.E) — depends on having the brain composer, since gap-detection and hold-draft are paired.
6. **Orchestration cutover** (4.5.F) — once all stages are brain-side, the legacy orchestrator becomes thin and gets retired.
7. **kb_gap_manager retirement** (4.5.G) — independent cleanup, can run any time but kept last so it doesn't get forgotten.

---

## Sub-Phase 4.5.A — Intent classification migration (deterministic-first)

**Goal**: every intent classification in production happens inside the brain, with a deterministic pre-filter handling the majority of inquiries and LLM intake as the escalation path. `InquiryIntentClassifier` migrates into the brain as the pre-filter, then the legacy file is deleted. The `intent_classifier_keyword_suggestion` healer proposal kind targets the brain's pre-filter and produces overrides the brain actually reads.

### Required reading before starting

- `docs/architecture/INTENT_CLASSIFICATION_LAYERS.md` — documents the deterministic-classifier + LLM-escalation pattern Phase 4.3-M implemented in legacy. This sub-phase is a structural lift of that exact pattern into the brain, not a redesign.
- `docs/architecture/PHASE_4_3_M_BRIEF.md` — the original brief for the pattern, useful for understanding the threshold-tuning rationale.
- `app/services/concierge/pre_booking_auto_send.py::InquiryIntentClassifier` — the proven PATTERNS dict and confidence math that migrates.
- `app/services/concierge/intent_classification_escalator.py` — the escalation wrapper that becomes the brain's escalation gate.
- `app/services/messaging_brain/agents/agent_router.py` and `llm_intake_agent.py` — the brain's existing intake, which becomes the Layer 2 (LLM-grounded) escalation path.
- `app/services/messaging_brain/audit.py` — confirms how `brain_classifier_metadata` is currently emitted; the healer will scan this audit shape after reorientation.

### Architectural commitment

The deterministic-first principle is non-negotiable here. The shape is:

```
Inquiry → DeterministicIntakePreFilter (keyword match)
            ├─ if score >= threshold → return classification, route to specialist
            └─ if score <  threshold → escalate to LLMIntakeAgent
```

The legacy `InquiryIntentClassifier` already has the keyword PATTERNS dict and confidence-score math that produces this shape. That code is the *useful piece* that migrates — it's been refined against real Beach Habitats traffic and represents earned understanding of what keywords map to what intents in the STR domain. We do not throw it away. We move it into the brain as `DeterministicIntakePreFilter`.

The escalation threshold should be tuned to hit the 60-70% deterministic target. Phase 4.3-M's empirical data showed that 15.7% of Beach Habitats inquiries fell below the 0.40 threshold — meaning ~84% were resolving deterministically. That's already above target. The threshold we land on in 4.5.A should preserve that resolution rate; the healer is the mechanism for keeping it there as new patterns emerge.

### Tasks

1. **Decision document**: `docs/architecture/CLASSIFIER_CANONICAL_PATH.md` records the deterministic-first shape, the threshold (probably 0.40 to match current production behavior), and the migration mechanics. This isn't an "A or B" decision document — it's a record of the chosen shape and the reasoning, so future sessions don't re-litigate it.

2. **Create the pre-filter agent**: `messaging_brain/agents/deterministic_intake_prefilter.py`.
   - Migrates `InquiryIntentClassifier.PATTERNS` and `classify_with_details` logic verbatim — this is proven code.
   - Outputs a `MessageClassification` (the brain's existing shape) with `confidence`, `intent_topic`, and `contradictory_signals`.
   - Reads per-tenant `operator_settings.extra.intent_classifier_keyword_overrides` and merges the operator-approved keywords into PATTERNS at classification time.
   - Stateless. Wire it as the first agent in the brain's classification stage.

3. **Wire the escalation gate**: the brain orchestrator's classification stage calls the pre-filter first. If `confidence >= threshold`, the classification is final. If `confidence < threshold`, `LLMIntakeAgent` runs and its output supersedes the pre-filter's.
   - The threshold lives in config, not hardcoded.
   - The audit payload `brain_classifier_metadata` carries `classifier_source` ("deterministic" or "llm_escalated") so the healer can scan for escalation patterns.

4. **Healer reorientation**:
   - `_scan_intent_classifier_signals` now reads `brain_classifier_metadata` (the brain's audit) instead of `intent_classifier_metadata` (legacy audit).
   - The clustering logic stays deterministic (token frequency, common-keyword extraction) — this is the cost-discipline rule #4 in action.
   - Approval writes to `operator_settings.extra.intent_classifier_keyword_overrides`, which the pre-filter now reads at runtime. The full healing loop is closed.

5. **Cut the legacy call site**:
   - `PreBookingPipelineOrchestrator.classify` calls `classify_with_escalation`. Replace with a call into the brain's classification stage.
   - Feature flag: `BRAIN_INTAKE_PRIMARY` (default OFF in 4.5.A; flip to ON after parity).

6. **Delete legacy code**: After parity passes and the flag has been ON for one deployment cycle:
   - Delete `InquiryIntentClassifier` from `pre_booking_auto_send.py` (the PATTERNS dict has been migrated; the original is dead code).
   - Delete `classify_with_escalation` from `intent_classification_escalator.py`.
   - Delete `intent_classification_escalator.py` entirely if nothing else references it.
   - Delete the `intent_classifier_metadata` audit-emission code (the brain's `brain_classifier_metadata` is the only audit now).

### Verification

- Parity test: the Christina Moser case and at least 5 other production messages produce the same intent classification through the brain's pre-filter as they did through legacy. Edge cases to include: a high-confidence keyword match (>=0.7), an ambiguous case (~0.4), a contradictory-signals case, an empty-message edge.
- Deterministic resolution rate test: against a sample of 100+ production messages, the pre-filter resolves >= 60% of them without LLM escalation. If it can't hit 60%, the threshold needs tuning; document the chosen value in `CLASSIFIER_CANONICAL_PATH.md`.
- Healer end-to-end: seed `brain_classifier_metadata` audit rows showing 3+ low-confidence escalations with common keywords; scan produces a proposal; approval writes to `operator_settings.extra.intent_classifier_keyword_overrides`; re-classifying a similar message now hits the pre-filter on the new keyword and returns high confidence.
- `LEGACY_RETIREMENT_PLAN.md` updated.

### Ship criteria

- All tests pass
- `LEGACY_RETIREMENT_PLAN.md` updated; intent classification → BRAIN-ACTIVE, then RETIRED once code is deleted
- `CLASSIFIER_CANONICAL_PATH.md` exists and records the deterministic threshold chosen
- `BRAIN_INTAKE_PRIMARY` flag ON in production for one deployment cycle without incident
- Deterministic resolution rate >= 60% in production (measured from `brain_classifier_metadata.classifier_source` field aggregated over a 24-hour window)
- Beach Habitats inquiry volume continues to flow through the brain intake without classifier drift

---

## Sub-Phase 4.5.B — Operator-learning preference injection migration

**Goal**: `LLMComposerAgent` reads `operator_learned_preferences` and injects them into the brain composer's prompt. The legacy injection point in `generate_inquiry_draft` is cut. Operator edits on brain-generated drafts feed `OperatorLearningService.record_edit`.

### Tasks

1. **Audit the brain composer's prompt assembly**: read `messaging_brain/agents/llm_composer_agent.py`. Identify where the system prompt is built and where new content can be injected.

2. **Build the preference-injection helper inside the brain**: 
   - Could be a method on `LLMComposerAgent` that calls the existing `operator_learning.build_preference_context()` — that function is already path-agnostic in its read logic; it just needs to be called from brain code.
   - Or, more cleanly: move the preference-loading logic into a brain-side helper (`messaging_brain/agents/operator_learning_adapter.py` or similar) that reads `operator_learned_preferences` directly.

3. **Wire it in**: `LLMComposerAgent` calls the helper at prompt-build time. Preferences are appended to the system prompt below the style rules, same pattern as legacy.

4. **Edit-capture from brain drafts**:
   - The operator-dashboard endpoint that handles "approve with edit" needs to call `OperatorLearningService.record_edit` with `original_draft = brain_draft_text` and `edited_text = operator_edit`.
   - Verify this is happening today for legacy drafts; mirror it for brain drafts.
   - This may already work if the operator dashboard reads `pre_booking_inquiries` rows agnostically of which pipeline produced them. Verify.

5. **Cut the legacy injection point**: Remove the `build_preference_context` call inside `generate_inquiry_draft`. Mark `generate_inquiry_draft` as legacy-only (will be deleted in 4.5.D).

6. **Feature flag**: `BRAIN_COMPOSER_PREFERENCES` (default OFF until parity check, then ON).

### Verification

- A property with a known preference (e.g. operator has edited "tone_softer" 3+ times for "pet_policy" intent) generates a brain draft that visibly applies the preference.
- An operator edit on a brain-generated draft creates a row in `operator_draft_events`.
- After 3 similar edits, a row appears in `operator_learned_preferences` with `confidence >= 0.67`.
- `LEGACY_RETIREMENT_PLAN.md` updated.

### Ship criteria

- All tests pass
- `BRAIN_COMPOSER_PREFERENCES` ON in production for one deployment cycle
- A production operator edit on a brain draft produces a recorded event

---

## Sub-Phase 4.5.C — Policy enforcement migration

**Goal**: every policy decision (min-nights, max-guests, pricing-flag, pet-flag, send-or-hold) happens inside the brain's `ResponsePolicyAgent` (or `platform_compliance.py`). Legacy `check_inquiry_policy` and `make_send_decision` are deleted.

### Tasks

1. **Audit the brain's existing policy layer**: read `messaging_brain/agents/response_policy_agent.py` and `messaging_brain/policy/platform_compliance.py`. Identify what's already there vs what needs to be added.

2. **Migrate policy checks**:
   - `min_nights` check → brain policy agent
   - `max_guests` check → brain policy agent
   - `flag_pricing_inquiries` / pricing block → brain policy agent
   - `flag_pet_inquiries` / pet policy → brain policy agent
   - `check_in_process` arrival-timing flag → brain policy agent
   - `AutoSendPolicy` configuration → brain reads from `operator_pre_booking_policies` table (same source as legacy)

3. **Migrate send decision**: `make_send_decision`'s logic (confidence + warnings → SEND_NOW / REVIEW / HOLD) becomes part of the brain's response policy. The brain's existing policy decision concepts may already cover this; verify and extend if needed.

4. **Audit payload**: when the brain enforces a policy, the existing audit shape includes `policy.final_action`. Verify that's preserved and surfaces through the same `update_normalization_outcome` path.

5. **Cut the legacy call site**: `PreBookingPipelineOrchestrator.evaluate_routing` is the seam — its policy-evaluation step routes through the brain.

6. **Delete legacy code**: After parity check, delete `check_inquiry_policy`, `make_send_decision`, `PolicyCheckResult`, `AutoSendPolicy`, `SendDecision`, `_apply_special_draft_source_policy` from `pre_booking_auto_send.py`.

7. **Feature flag**: `BRAIN_POLICY_PRIMARY`.

### Verification

- Parity test: each of the policy paths fires correctly through the brain — pricing inquiry → REVIEW, pet inquiry with pet-policy=not_allowed → flag, etc.
- The Christina Moser case still produces the right decision (`confirmed_guest_email_received` route from 4.3-N, not pre-booking).
- `LEGACY_RETIREMENT_PLAN.md` updated.

### Ship criteria

- All tests pass
- `BRAIN_POLICY_PRIMARY` ON in production for one deployment cycle
- No regression in operator-dashboard review queue volume (i.e. brain policy doesn't suddenly hold everything or send everything)

---

## Sub-Phase 4.5.D — Draft generation migration (deterministic-first ordering)

**Goal**: every legacy draft handler is migrated into the brain. `LLMComposerAgent` becomes the LLM-fallback composer, NOT the entry point — deterministic draft paths run first, the LLM only fires when no deterministic answer applies. Legacy `generate_inquiry_draft` and its helpers are deleted.

This is the largest sub-phase. The internal ordering matters for cost discipline: deterministic paths must land in the brain BEFORE the LLM composer becomes primary. If `LLMComposerAgent` is wired in as the default and the deterministic fallbacks aren't there yet, every draft routes through LLM during the cutover window — a temporary state, but at production traffic this is real money.

### Architectural shape

The brain composition pipeline, after this sub-phase:

```
Draft request → 1. Pricing-policy handler  (deterministic, special-case)
               2. Portfolio-match handler (deterministic, special-case)
               3. Grounded fallback chain (deterministic):
                    ├─ property-data direct answer
                    ├─ guidebook FAQ match
                    └─ intent-aware static fallback
               4. Verification follow-up gate (deterministic, hold-mode)
               5. LLMComposerAgent          (LLM call, last resort)
               6. Grounding review          (post-composition, on LLM output)
```

The legacy code already implements this priority order in `generate_inquiry_draft` — read the function from top to bottom and the ordering is exactly: pricing-policy first, portfolio-match second, then if no API keys are present the grounded fallback runs, otherwise the LLM call, with grounding review last. The brain inherits this same priority order.

Each deterministic handler that resolves the draft skips all downstream LLM work. At the 60-70% target, the LLM composer fires on only 30-40% of inquiries.

### Sub-task ordering (deterministic first)

#### Sub-task 4.5.D.1 — Pricing-policy handler (deterministic, special-case)

`_grounded_pricing_policy_draft`. Handles "first time renter discount" requests with `get_market_demand` integration. This is pure deterministic logic — string matching, demand lookup, templated response. Zero LLM cost.

- Migrate into the brain as a deterministic agent or a method on the composer's fallback path.
- Suggested home: `messaging_brain/agents/pricing_policy_agent.py` if the brain prefers per-concern agents, or a method on `LLMComposerAgent` named `_try_deterministic_pricing_draft` if not.
- `get_market_demand` is path-agnostic (`db_service`), no migration needed for it.
- The brain composer's flow calls this *first*. If it returns a draft, no further composition happens.

#### Sub-task 4.5.D.2 — Portfolio-match handler (deterministic, special-case)

`_looks_like_portfolio_search_inquiry`, `_extract_portfolio_search_criteria`, `_find_portfolio_match_candidates`, `_portfolio_match_draft`, `_portfolio_match_hold_draft`.

- Handles "send me a few options matching X criteria" inquiries. The detection (`_looks_like_portfolio_search_inquiry`) is regex-based; the match (`_find_portfolio_match_candidates`) is a DB query; the draft is templated. Zero LLM cost.
- Suggested home: dedicated `messaging_brain/agents/portfolio_matching_agent.py`, OR fold into `BookingInquiryAgent` as a sub-mode if that fits the brain's topology.
- Called after pricing-policy, before grounded fallback chain.

#### Sub-task 4.5.D.3 — Grounded fallback chain (deterministic)

`_direct_grounded_fallback_draft`, `_answer_from_property_data`, `_answer_from_guidebook_knowledge`, `_fallback_draft`.

- The three-stage fallback hierarchy: try direct property-data answer (washer/dryer, wifi, parking) → try guidebook FAQ token match → fall back to intent-aware templated reply.
- All deterministic. The most important sub-task in this whole sub-phase for cost discipline — this is the path that catches many easy questions without any LLM call.
- Suggested home: utility module `messaging_brain/agents/grounded_fallback.py`, called from the composer's pre-LLM phase.
- Confirm the brain has access to the same property-data and guidebook-FAQ shapes the legacy fallbacks read. If yes, the migration is largely lift-and-shift. If no, an adapter layer may be needed.

#### Sub-task 4.5.D.4 — Verification follow-up gate (deterministic, hold-mode)

`_should_create_verification_follow_up`, `_verification_follow_up_draft`, `_verification_focus_line`.

- Detects when a question needs an "I'm confirming" hold reply (golf cart, laundry, parking with no operator-provided detail). Templated response. Zero LLM cost.
- Suggested home: `messaging_brain/agents/verification_hold_agent.py` or a method on the composer.
- Called after grounded fallback, before LLM composer.

#### Sub-task 4.5.D.5 — LLM composer migration (the actual LLM call)

This is the LLM-fallback path — only reached when sub-tasks D.1-D.4 didn't resolve the draft.

- Audit the brain's existing `LLMComposerAgent`: what context does it consume, how does it build the prompt, how does it handle errors?
- Migrate any prompt-building logic from legacy `generate_inquiry_draft` that the brain composer doesn't already have. Specifically: the reasoning-notes generator (`_build_reasoning_notes`), the intent-specific context-lines builder.
- Operator-guidance loading and preference injection (from 4.5.B) should already be in place by this point.
- Provider orchestration (4.5.D.6 below) lives here.

#### Sub-task 4.5.D.6 — Provider orchestration

`_ordered_prebooking_providers`, `_call_prebooking_groq`, `_call_prebooking_claude`, `_call_prebooking_gemini`, `_record_prebooking_usage`.

- Handles the fallback chain (Anthropic → Groq → Gemini) and `LLMUsageTracker` integration.
- Check if the brain's existing LLM call infrastructure already does multi-provider fallback. If yes, delete the legacy versions. If no, the brain needs equivalent orchestration — this is important resilience that shouldn't be lost in migration.
- The simple-inquiry-fast-path heuristic (`_is_simple_prebooking_inquiry`) that reorders providers (Groq first for simple cases, Anthropic-first for complex) is a cost optimization. Preserve it.

#### Sub-task 4.5.D.7 — Grounding review (post-composition)

`_ground_inquiry_draft`, `_build_prebooking_grounding_context`, `_is_usable_draft`, call to `response_reviewer.review_concierge_response`, call to `hallucination_guard.check_grounding`.

- Runs after LLM composition. `response_reviewer` and `hallucination_guard` are shared services that stay where they are; the *call site* moves into the brain.
- The grounding context builder migrates with the composer — it formats the property/policy/marker context into the shape the reviewers expect.
- Gap-logging (`log_gap_async`) continues to fire when grounding flags or blocks a draft; that's the input signal to the KnowledgeCurator.

#### Sub-task 4.5.D.8 — Cut and delete

Once D.1 through D.7 are landed and parity is verified:

- Replace `generate_inquiry_draft` with a thin shim that calls the brain composer, then delete the shim once `PreBookingPipelineOrchestrator.draft` is gone in 4.5.F.
- Delete `_grounded_pricing_policy_draft`, `_looks_like_portfolio_search_inquiry`, `_extract_portfolio_search_criteria`, `_find_portfolio_match_candidates`, `_portfolio_match_draft`, `_portfolio_match_hold_draft`, `_portfolio_match_summary`, `_portfolio_recommendation_is_fully_grounded`, `_property_has_golf_cart_signal`, `_resolve_requested_community`, `_normalize_match_text`, `_extract_requested_guest_count`, `_extract_adult_child_counts`.
- Delete `_direct_grounded_fallback_draft`, `_answer_from_property_data`, `_answer_from_guidebook_knowledge`, `_knowledge_snippet_candidates`, `_fallback_draft`.
- Delete `_should_create_verification_follow_up`, `_verification_follow_up_draft`, `_verification_focus_line`, `_looks_like_amenity_verification_message`.
- Delete `_ordered_prebooking_providers`, `_call_prebooking_groq`, `_call_prebooking_claude`, `_call_prebooking_gemini`, `_record_prebooking_usage`, `_PREBOOKING_COMPLEX_PATTERNS`, `_is_simple_prebooking_inquiry`, `_has_multiple_request_signal`.
- Delete `_ground_inquiry_draft`, `_build_prebooking_grounding_context`, `_is_usable_draft`, `_build_reasoning_notes`, `_extract_golf_cart_grounding_markers`.
- The legacy file shrinks dramatically. What remains is the orchestrator and persistence helpers, which 4.5.F will retire.

### Feature flags

- `BRAIN_COMPOSER_PRIMARY` — master flag.
- Per sub-task flags optional: `BRAIN_PRICING_HANDLER`, `BRAIN_PORTFOLIO_MATCH`, `BRAIN_GROUNDED_FALLBACK`. Use only if granular rollback is needed during cutover.

### Verification

- Cost discipline parity test: against 100+ production messages, measure the ratio of drafts that resolve deterministically (D.1-D.4) versus those that fall through to LLM composition (D.5). Target: >= 60% deterministic. Document the measured rate in `LEGACY_RETIREMENT_PLAN.md`.
- Each of the five specialized draft paths produces equivalent output through the brain. Suggested fixtures:
  - Pricing-policy: "first time renter, can I get a discount?" → demand-aware deterministic reply, no LLM call
  - Portfolio search: "send me a few 4-bedroom places with a pool" → templated match list, no LLM call
  - Grounded fallback: a wifi question with `wifi_available=true` → deterministic answer, no LLM call
  - Verification follow-up: golf cart question with no operator detail → hold reply, no LLM call
  - LLM composer path: an ambiguous nuanced inquiry → LLM-generated draft, with grounding review applied
- Christina Moser case still routes correctly (this is the through-line regression).
- `LEGACY_RETIREMENT_PLAN.md` updated.

### Ship criteria

- All tests pass
- `BRAIN_COMPOSER_PRIMARY` ON in production for one deployment cycle
- Production deterministic resolution rate measured and documented; >= 60% threshold met
- All five draft paths produce equivalent or better output
- Lines of legacy code deleted: should be in the thousands by the end of this sub-phase

---

## Sub-Phase 4.5.E — Knowledge-gap detection migration

**Goal**: knowledge-gap detection and gap-hold draft generation happen inside the brain. Legacy `detect_missing_knowledge`, `KnowledgeGapAnalysis`, `_generate_knowledge_gap_hold_draft` are deleted.

### Tasks

1. **Decide the home in the brain**: either a new `messaging_brain/agents/knowledge_gap_agent.py` that runs between `ContextBuilderAgent` and `LLMComposerAgent`, or extend `ContextBuilderAgent` to surface gaps as part of its output.

2. **Migrate the topic-resolution logic**: `_resolve_structured_topic`, `_find_tagged_concierge_knowledge`, `_topic_specific_evidence_hit`. These are pure functions of property/operator data. Move as-is into the brain agent.

3. **Migrate the gap-hold draft generator**: paired with the composer, since it generates a draft when gaps are present. Could be a hold-mode in `LLMComposerAgent` or a sibling agent.

4. **Cut the legacy call**: `PreBookingPipelineOrchestrator.evaluate_routing` currently calls `detect_missing_knowledge`. Route through the brain instead.

5. **Delete legacy code**: `detect_missing_knowledge`, `KnowledgeGapAnalysis`, `KnowledgeTopicAssessment`, `_nested_lookup`, `_has_text`, `_has_number`, `_find_tagged_concierge_knowledge`, `_topic_specific_evidence_hit`, `_resolve_structured_topic`, `_generate_knowledge_gap_hold_draft`, `_knowledge_gap_hold_draft`.

6. **Feature flag**: `BRAIN_KNOWLEDGE_GAP_PRIMARY`.

### Verification

- A property missing pool_heated info, queried about pool heating → brain produces a hold draft asking the operator to confirm.
- The knowledge-gap log path (`log_gap_async` into `concierge_knowledge_gaps`) continues to fire, feeding the KnowledgeCurator's daily job.
- `LEGACY_RETIREMENT_PLAN.md` updated.

### Ship criteria

- All tests pass
- `BRAIN_KNOWLEDGE_GAP_PRIMARY` ON in production for one deployment cycle
- `concierge_knowledge_gaps` continues to accumulate rows at the same rate (this is the input to the curator — if it stops, the curator stops finding things to cluster)

---

## Sub-Phase 4.5.F — Orchestration cutover

**Goal**: `process_pre_booking_inquiry` either does not exist or is a 5-line shim that calls the brain orchestrator. The brain owns intake → classify → policy → draft → persist → dispatch end-to-end. `PreBookingPipelineOrchestrator` is deleted.

### Tasks

1. **Audit the brain orchestrator's current scope**: read `messaging_brain/orchestrator.py`. What does it handle today, what would it need to handle to fully replace the legacy orchestrator?

2. **Wire pre-booking inquiry intake directly to the brain orchestrator**:
   - `pre_booking_handler.py` (Escapia polling) currently calls `process_pre_booking_inquiry`.
   - Replace that call with one to the brain orchestrator.
   - The brain orchestrator handles classification (4.5.A), policy (4.5.C), draft (4.5.D), gap-detection (4.5.E), persistence, and dispatch.

3. **Migrate the persistence helper**: `save_inquiry_from_canonical`, `_save_inquiry`, `_insert_pre_booking_inquiry`, `_resolve_guest_thread_id_for_save`, `_guest_thread_exists`. These can stay where they are or move into `messaging_brain/pre_booking.py` (which already exists). Recommendation: move into brain code so the brain orchestrator is self-contained.

4. **Migrate the dispatch helpers**: `_alert_operator_for_review`, `_schedule_timeout_send`, `_schedule_timeout_auto_send`, `_log_required_mode_event`, `_send_via_escapia`. Same recommendation — move into brain code.

5. **Cut the legacy entry points**:
   - `process_pre_booking_inquiry` becomes a shim or is removed.
   - `process_pre_booking_inquiry_with_draft` is already a brain-bridge function from Session 8 — it stays or gets consolidated.
   - `PreBookingPipelineOrchestrator` is deleted.

6. **Delete legacy code**: everything else in `pre_booking_auto_send.py` that's not already gone gets deleted. Ideally the file itself is deleted; if a few save helpers are still needed for backward compatibility during a deploy window, those move out and get renamed.

7. **Feature flag**: `BRAIN_ORCHESTRATOR_PRIMARY` — the master cutover flag.

### Verification

- End-to-end: a real Escapia inquiry message arrives, gets polled, gets routed through the brain orchestrator, gets classified, gets policy-checked, gets drafted, gets persisted, and the operator sees it in their dashboard. No call to legacy code anywhere in the path.
- The Christina Moser regression: same inquiry, same route, same hold decision, same draft.
- `LEGACY_RETIREMENT_PLAN.md` updated.

### Ship criteria

- All tests pass
- `BRAIN_ORCHESTRATOR_PRIMARY` ON in production for one deployment cycle
- `pre_booking_auto_send.py` either deleted or reduced to <100 lines of shims and helpers awaiting final removal
- Operator dashboard continues to work normally (this is the test that proves nothing visible has regressed)

---

## Sub-Phase 4.5.G — kb_gap_manager retirement

**Goal**: `kb_gap_manager.py` is deleted. The tiered-gap-classification concept is documented for possible future revival.

### Tasks

1. **Document the conceptual model** in `docs/architecture/KB_GAP_MANAGER_RETIREMENT.md`: what tiered classification was meant to do, why it didn't ship (references absent tables, no callers), what would be needed to revive it on top of `concierge_knowledge_gaps` if operators ever ask for tiered triage.

2. **Verify no callers**: search the codebase for `kb_gap_manager` imports. Should be zero (this was confirmed in earlier audit).

3. **Delete the file**: `app/services/concierge/kb_gap_manager.py`.

4. **Update**: `LEGACY_RETIREMENT_PLAN.md` marks this RETIRED.

### Ship criteria

- File deleted
- All tests pass
- Documentation note exists

This is the cleanup sub-phase and can run in parallel with any other sub-phase since it has no dependencies.

---

## Final state when this arc completes

- `pre_booking_auto_send.py` either does not exist or is <50 lines of trivial shims awaiting final deletion
- `kb_gap_manager.py` does not exist
- Every intent classification, policy decision, draft generation, knowledge-gap check, and persistence write goes through `messaging_brain/`
- The healer scans brain audits, proposes changes to brain-consumable stores, and approval has runtime effect
- `LEGACY_RETIREMENT_PLAN.md` shows every legacy capability as RETIRED
- When a future engineer asks "where does X happen?" the answer is in `messaging_brain/`

## Operating note for Codex through this arc

For every commit:

- Cite which sub-phase and which sub-task is being shipped
- Include the migrated brain-side code and the deleted legacy code in the same commit (no orphan branches)
- Update `LEGACY_RETIREMENT_PLAN.md` status fields
- Add a parity test as part of the test suite — the test should fail if the brain output diverges from the spec the legacy version encoded

For every sub-phase completion message back to chat:

- Commit SHA
- Migration revision (if any new migrations)
- Feature flag set and its default
- Parity test outcomes (which production cases pass)
- Updated retirement plan status (what flipped to BRAIN-ACTIVE or RETIRED)
- Lines of code deleted from legacy (a real metric — this arc should remove thousands of lines)
- Any decisions made that should be documented in `CLASSIFIER_CANONICAL_PATH.md` or sibling docs
