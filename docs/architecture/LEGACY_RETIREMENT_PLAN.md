# Legacy Retirement Plan

## The principle

The messaging brain (`app/services/messaging_brain/`) is the only runtime pipeline. Everything in legacy (`app/services/concierge/pre_booking_auto_send.py` and the surrounding helpers it pulls in) is a deprecation target. Two pipelines is a permanent cost — every feature decision becomes "wire to which side?", every bug doubles, every behavior has two implementations that can drift. The brain was built specifically to handle 100K+ units and 1K+ operators; keeping legacy alive undermines what the brain was built for.

The migration principle:

1. Every useful capability in legacy moves *into* the brain
2. Nothing useful is thrown away — capabilities migrate, they don't get deleted
3. Once a capability lives in the brain and the brain is consuming it, the legacy implementation is deleted
4. New work targets the brain only

## The cost discipline that governs the migration

The brain serves two non-negotiable targets, in priority order:

1. **Accuracy** — 90-95% of auto-sent drafts must be correct. Below that, the business doesn't work.
2. **Cost** — 60-70% of inquiries should auto-resolve (deterministic-certain + LLM-grounded auto-send) so LLM costs stay sustainable at 100K+ units.

The two are reconciled by a three-layer architecture:

- **Layer 1 — Deterministic-certain**: near-100% precision, coverage = whatever it is. Resolves easy structurally-unambiguous cases (property-data direct answer, FAQ exact-match, templated holds).
- **Layer 2 — LLM-grounded**: 90%+ accuracy via grounding review. Handles synthesis where source is well-defined.
- **Layer 3 — Operator review**: 100% accuracy via human in the loop. Handles anything Layers 1 and 2 weren't confident on.

The 60-70% auto-resolve target = Layer 1 + Layer 2. The remaining 30-40% goes to Layer 3 and that's a feature — pre-booking is designed around operator approval.

**The precision principle (rule zero)**: deterministic layers do not guess. They either get it right with near-certainty or they hand off. A deterministic layer with 80% accuracy at 70% coverage produces 56% correct drafts before any LLM runs — well below the accuracy floor. Lowering thresholds to chase coverage is fatal to the business model.

The healer agent exists to keep the deterministic layer *correct and growing*: as new inquiry patterns appear, operators approve new keyword/alias/policy additions through the healer flow. The healer adds *correct* patterns, never relaxed thresholds. The healer approval flow shows the operator the evidence cluster, the proposed effect on historical messages, and the reversibility path — a bad approved override is more expensive than no override at all.

The healer itself must be deterministic. An LLM-per-audit-row healer moves the cost from per-inquiry to per-audit (often at a higher rate). Healers analyze deterministic signals with deterministic techniques (token frequency, Jaccard overlap, dict grouping). LLM judgment, if ever needed, runs on clusters not rows. The current healer (commit 82f9bb9) respects this.

This document tracks every legacy capability, where it goes, when it goes, and what counts as evidence it can be retired — always with the accuracy bar (90-95%) and cost discipline (60-70% auto-resolve) preserved.

## Status legend

- **LEGACY-ACTIVE**: lives in legacy, still serving traffic
- **MIGRATING**: actively being moved to brain in a named sub-phase
- **BRAIN-ACTIVE**: lives in brain, brain is the consumer; legacy version may still exist but is dead code
- **RETIRED**: legacy version deleted from codebase

## Inventory: legacy capabilities and their migration targets

### 1. Intent classification (deterministic pre-filter + LLM fallback)

**Legacy**: `pre_booking_auto_send.py::InquiryIntentClassifier` (keyword-pattern dict + `classify_with_details`).
**Migration target**: `messaging_brain/agents/deterministic_intake_prefilter.py` (new). The PATTERNS dict and confidence math migrate verbatim — this is proven code that resolves the majority of Beach Habitats inquiries deterministically. The brain's existing `LLMIntakeAgent` becomes the escalation path for low-confidence cases.
**Sub-phase**: 4.5.A
**Cost discipline note**: the pre-filter is the cost model's foundation at the intake layer. Phase 4.3-M's data shows ~84% of Beach Habitats inquiries currently resolve at or above the 0.40 confidence threshold; the migrated pre-filter must preserve that rate. The healer's `intent_classifier_keyword_suggestion` proposal kind exists specifically to keep this rate high as new patterns emerge.
**Retirement evidence**: every classification in production routes through the brain pre-filter; production deterministic resolution rate >= 60% measured and documented via [PRODUCTION_METRICS_QUERIES.md](/Users/dhuntermckenzie/Downloads/oyvoda/docs/architecture/PRODUCTION_METRICS_QUERIES.md); `InquiryIntentClassifier` has zero call sites; deleted.
**Status**: MIGRATING

### 2. Operator keyword overrides

**Legacy**: `operator_settings.extra.intent_classifier_keyword_overrides` (written by the healer, consumed by nothing).
**Migration target**: read by `messaging_brain/agents/deterministic_intake_prefilter.py` at classification time. Operator-approved keywords merge into the pre-filter's PATTERNS dict per-tenant, extending deterministic resolution coverage.
**Sub-phase**: 4.5.A (paired with intent classification migration)
**Retirement evidence**: the brain pre-filter reads this column at classification time; the healer's `intent_classifier_keyword_suggestion` scans `brain_classifier_metadata` (not the legacy audit); an approved keyword suggestion measurably changes the deterministic resolution rate for that tenant.
**Status**: MIGRATING

### 3. Policy enforcement

**Legacy**: `pre_booking_auto_send.py::check_inquiry_policy`, `make_send_decision`, `AutoSendPolicy`, `PolicyCheckResult`, `SendDecision`. These enforce min-nights, max-guests, pricing-flag, pet-flag, and the confidence-threshold send decision.
**Migration target**: `messaging_brain/agents/response_policy_agent.py` + `messaging_brain/policy/platform_compliance.py`.
**Current bridge**: `BRAIN_POLICY_PRIMARY` routes legacy pre-booking policy and draft-source hold decisions through the brain-owned deterministic helpers while legacy draft generation remains in place for parity.
**Sub-phase**: 4.5.C
**Retirement evidence**: brain's `ResponsePolicyAgent` produces the same `SEND_NOW` / `REVIEW` / `HOLD` decisions for the same inputs; regression suite includes the Christina Moser case and other production messages; legacy `check_inquiry_policy` and `make_send_decision` deleted.
**Status**: MIGRATING

### 4. Operator-learning preference injection

**Legacy**: `operator_learning.py::build_preference_context` injected into legacy `generate_inquiry_draft`'s system prompt.
**Migration target**: `messaging_brain/agents/llm_composer_agent.py` reads `operator_learned_preferences` and injects them into its composer prompt.
**Sub-phase**: 4.5.B
**Retirement evidence**: brain's composer prompt includes the preference block; new operator-edit events captured on brain-generated drafts feed `OperatorLearningService.record_edit`; legacy injection point in `generate_inquiry_draft` cut.
**Status**: MIGRATING

### 5. Knowledge-gap detection

**Legacy**: `pre_booking_auto_send.py::detect_missing_knowledge`, `KnowledgeGapAnalysis`, `_resolve_structured_topic`, `_find_tagged_concierge_knowledge`, `_topic_specific_evidence_hit`.
**Migration target**: new `messaging_brain/agents/knowledge_gap_agent.py`, or extend `ContextBuilderAgent`.
**Sub-phase**: 4.5.E
**Current bridge**: `BRAIN_GAP_DETECTION_PRIMARY` routes `PreBookingPipelineOrchestrator.evaluate_routing()` through `messaging_brain/agents/knowledge_gap_agent.py` while the legacy orchestrator shell remains in place for parity.
**Retirement evidence**: brain produces the same `KnowledgeGapAnalysis.missing_topic_ids` for the same inputs; the gap-hold draft generation path is also in the brain.
**Status**: MIGRATING

### 6. Knowledge-gap hold draft generation

**Legacy**: `pre_booking_auto_send.py::_generate_knowledge_gap_hold_draft` — produces a polite "I'm confirming the details" hold reply when knowledge is missing.
**Migration target**: brain agent paired with knowledge-gap detection (likely the same `KnowledgeGapAgent` or `LLMComposerAgent` with a hold-mode prompt).
**Sub-phase**: 4.5.E
**Current bridge**: `BRAIN_GAP_DETECTION_PRIMARY` routes `PreBookingPipelineOrchestrator.draft()` through `messaging_brain/agents/knowledge_gap_hold_agent.py` when missing topics exist, preserving the legacy `draft_source` semantics (`kb_gap_required`, `kb_gap_model_*`) while the orchestration shell remains transitional.
**Retirement evidence**: brain produces equivalent hold drafts; legacy function deleted.
**Status**: MIGRATING

### 7. Grounded pricing-policy draft (first-time discount handler)

**Legacy**: `pre_booking_auto_send.py::_grounded_pricing_policy_draft` — special-case handler for "first time renter discount" requests with demand-aware response.
**Migration target**: brain agent — either `LLMComposerAgent` with policy-aware prompt context, or a dedicated `PricingPolicyAgent`. The `get_market_demand` call needs to be accessible from the brain.
**Sub-phase**: 4.5.D
**Retirement evidence**: a "first time renter, can I get a discount?" inquiry routed through the brain produces a demand-aware policy reply.
**Current bridge**: `BRAIN_COMPOSER_PRIMARY` routes the pricing-policy special case through `messaging_brain/agents/pricing_policy_agent.py` before legacy `generate_inquiry_draft` runs.
**Status**: MIGRATING

### 8. Portfolio search and match

**Legacy**: `pre_booking_auto_send.py::_looks_like_portfolio_search_inquiry`, `_extract_portfolio_search_criteria`, `_find_portfolio_match_candidates`, `_portfolio_match_draft`, `_portfolio_match_hold_draft`. Handles "send me a few properties that match X criteria" inquiries.
**Migration target**: dedicated `messaging_brain/agents/portfolio_matching_agent.py`, or fold into `BookingInquiryAgent` as a sub-mode.
**Sub-phase**: 4.5.D
**Retirement evidence**: a portfolio-search inquiry routed through the brain produces a multi-property recommendation draft.
**Current bridge**: `BRAIN_COMPOSER_PRIMARY` routes portfolio-search detection, candidate selection, and hold/draft copy through `messaging_brain/agents/portfolio_matching_agent.py` before legacy `generate_inquiry_draft` runs.
**Status**: MIGRATING

### 9. Verification follow-up gate

**Legacy**: `pre_booking_auto_send.py::_should_create_verification_follow_up`, `_verification_follow_up_draft`, `_verification_focus_line`. Generates a "I'm checking that for you" reply when the AI needs to confirm before promising specifics (golf cart inquiries, laundry inquiries, etc.).
**Migration target**: brain composer or a hold-mode pattern.
**Sub-phase**: 4.5.D
**Retirement evidence**: a verification-required inquiry routed through the brain produces an equivalent hold reply.
**Current bridge**: `BRAIN_COMPOSER_PRIMARY` routes verification-hold detection and templated hold copy through `messaging_brain/agents/verification_hold_agent.py` before legacy `generate_inquiry_draft` runs.
**Status**: MIGRATING

### 10. Grounded fallback drafts (no LLM available)

**Legacy**: `pre_booking_auto_send.py::_direct_grounded_fallback_draft`, `_answer_from_property_data`, `_answer_from_guidebook_knowledge`, `_fallback_draft`. Produces deterministic answers from property data when no LLM is available or model returns low-signal output.
**Migration target**: brain's composer fallback path. The brain has its own fallback mechanism; this logic gets folded in.
**Sub-phase**: 4.5.D
**Retirement evidence**: brain composer handles the no-LLM and low-signal cases producing grounded fallback replies.
**Current bridge**: `BRAIN_COMPOSER_PRIMARY` routes the grounded direct-answer rungs (`property_data`, `guidebook`, `FAQ`) through `messaging_brain/agents/grounded_fallback_agent.py` before legacy `generate_inquiry_draft` runs. The generic `_fallback_draft` template remains legacy until the verification-hold and LLM stages migrate.
**Status**: MIGRATING

### 11. Draft grounding and hallucination guard

**Legacy**: `pre_booking_auto_send.py::_ground_inquiry_draft`, `_build_prebooking_grounding_context`, with calls to `response_reviewer.review_concierge_response` and `hallucination_guard.check_grounding`.
**Migration target**: brain composer should run the same grounding step. The shared services (`response_reviewer`, `hallucination_guard`) stay where they are — they're path-agnostic; the *call site* moves into brain.
**Sub-phase**: 4.5.D (paired with composer migration)
**Retirement evidence**: brain composer applies grounding checks before emitting drafts; gap-logging on rejected drafts continues to fire.
**Current bridge**: `BRAIN_COMPOSER_PRIMARY` now routes the pre-booking LLM/provider path through `messaging_brain/agents/prebooking_llm_draft_agent.py`, and the resulting draft is still passed through `_ground_inquiry_draft` before it reaches the queue.
**Status**: MIGRATING

### 12. Pipeline orchestration

**Legacy**: `pre_booking_auto_send.py::PreBookingPipelineOrchestrator`, `process_pre_booking_inquiry`, `process_pre_booking_inquiry_with_draft`. The five-stage staged orchestration: classify → evaluate routing → draft → persist → dispatch.
**Migration target**: `messaging_brain/orchestrator.py` is the brain's orchestrator. Pre-booking inquiry intake gets routed there directly, with brain agents handling each stage.
**Sub-phase**: 4.5.F
**Retirement evidence**: brain-on `email_dispatch.py` now routes `PreBookingBrainOrchestrator().handle(...)` through `messaging_brain/pre_booking_lifecycle.py` instead of handing reviewed drafts back into `process_pre_booking_inquiry_with_draft(...)`; `PreBookingPipelineOrchestrator` remains as a compatibility evaluator during the migration.
**Phase 1 execution artifact**: [scripts/replay_brain_prebooking_primary.py](/Users/dhuntermckenzie/Downloads/oyvoda/scripts/replay_brain_prebooking_primary.py) is the canonical replay harness for this seam. It drives the live `dispatch_pre_booking(...)` gate with `brain_prebooking_lifecycle_primary = true` for a single shadow replay, captures the resulting inquiry/normalization shape, and rolls the DB transaction back. This is the required evidence before cutting the remaining tenant-scoped fallback seam.
**Status**: MIGRATING

### 13. Persistence to `pre_booking_inquiries`

**Legacy**: `pre_booking_auto_send.py::_save_inquiry`, `_insert_pre_booking_inquiry`, `_resolve_guest_thread_id_for_save`, `save_inquiry_from_canonical`.
**Migration target**: stays as a thin persistence helper or moves into `messaging_brain/`. The `pre_booking_inquiries` table itself stays — it's the operator-facing queue that the dashboard reads. What changes is who writes to it (the brain orchestrator instead of the legacy orchestrator).
**Sub-phase**: 4.5.F (paired with orchestration migration)
**Retirement evidence**: brain lifecycle runtime now owns the call to the canonical `save_inquiry_from_canonical(...)` seam; the queue table stays unchanged while ownership of the write call moves off the legacy dispatch wrapper.
**Remaining retirement seam**: `dispatch_pre_booking(...)._persist_fallback("brain_runtime_not_primary")` is still a tenant-scoped compatibility branch while `brain_prebooking_lifecycle_primary` remains off. After the Beach Habitats cutover, pre-booking dispatch was tightened so `brain_prebooking_lifecycle_primary` itself is the lane-specific ownership switch; the older two-flag overlap with `messaging_brain_runtime` no longer controls whether this lane enters the brain lifecycle.
**Status**: MIGRATING

### 14. Operator alerts and timeout-send scheduling

**Legacy**: `pre_booking_auto_send.py::_alert_operator_for_review`, `_schedule_timeout_send`, `_log_required_mode_event`, `_send_via_escapia`.
**Migration target**: brain orchestrator dispatches operator alerts. The `operator_alerts.get_alert_router()` is path-agnostic and stays. The Escapia send is also path-agnostic.
**Sub-phase**: 4.5.F
**Retirement evidence**: `messaging_brain/pre_booking_lifecycle.py` is now the caller of send / alert / timeout / required-mode side effects for brain-on runtime traffic, while the helpers themselves stay in place as path-agnostic utilities during migration.
**Status**: MIGRATING

### 15. kb_gap_manager

**Legacy**: `app/services/concierge/kb_gap_manager.py`. Tiered gap classification (AUTO-HANDLE / SUGGEST / FLAG) with operator suppression. References tables (`kb_gaps`, `operator_gap_settings`) that don't exist in production.
**Migration target**: none — retire entirely. The conceptual model (tiered classification) can be revived as a layer on top of `concierge_knowledge_gaps` if operators ask for it.
**Sub-phase**: 4.5.G
**Retirement evidence**: callers now write through `concierge/knowledge_gap_recorder.py` into `ConciergeKnowledgeService.record_gap(...)` / `concierge_knowledge_gaps`; `kb_gap_manager.py` is deleted.
**Status**: RETIRED

## Out of scope for this arc

Things that look like legacy but aren't, and don't need to move:

- **`pre_booking_handler.py`** (Escapia polling) — this is the transport layer, not the pipeline. Stays. The brain orchestrator gets called from here once 4.5.F lands.
- **`operator_learning.py::EditAnalyzer`** and its storage (`operator_learned_preferences`, `operator_draft_events`, `platform_learning_events`, `platform_intelligence`) — the capture-side is path-agnostic. Migration 4.5.B is about the *injection point*, not the data model.
- **Shared services**: `response_reviewer`, `hallucination_guard`, `operator_guidance`, `operator_alerts`, `knowledge_service`, `context_builder` — these are utilities the brain already calls or will call. They stay where they are.
- **`concierge/` package as a whole** — much of this is shared infrastructure (knowledge service, escalation service, dining service, guest_thread_service, etc.). The retirement target is specifically `pre_booking_auto_send.py` and `kb_gap_manager.py`.

## Operating discipline during the migration

While the arc is in flight, both pipelines exist. To prevent drift:

1. **Every new feature lands in the brain only**. No new legacy code.
2. **Every legacy bugfix is duplicated into the brain target agent** before merging, so the migration brings parity not a backslide.
3. **Each sub-phase ends with a parity test**: a real production message (e.g. the Christina Moser case) is routed through both pipelines (in a test fixture, not production) and outputs are compared. The brain must produce equivalent or better output before the legacy step is cut.
4. **Feature flag gates each cutover**: `MESSAGING_BRAIN_RUNTIME` is already ON; each sub-phase adds a finer-grained flag for its specific migration so it can roll back per-piece if needed.
5. **Update this document after each sub-phase**: status flips from LEGACY-ACTIVE to BRAIN-ACTIVE when brain is consuming, then to RETIRED when legacy code is deleted.

## End state

When this arc completes, `app/services/concierge/pre_booking_auto_send.py` either does not exist or is a thin shim around `messaging_brain/orchestrator.py`. `kb_gap_manager.py` does not exist. The intent classifier configuration (whether deterministic, LLM, or hybrid) lives in `messaging_brain/agents/`. Every operator-policy enforcement, knowledge-gap check, draft composition, and persistence write goes through the brain.

When a future engineer (or future Claude session) asks "where does X happen?" there is exactly one answer, and that answer is in `messaging_brain/`.
