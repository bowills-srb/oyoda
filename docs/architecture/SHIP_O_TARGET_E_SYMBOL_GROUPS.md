# Ship O — Target E symbol-group inventory (`pre_booking_auto_send.py`)

**Status:** Inventory written May 20, 2026. This is a prerequisite audit for Ship O, not a deletion commit.

## Purpose

`pre_booking_auto_send.py` is too large and too entangled for file-level deletion planning.

Ship O needs symbol-group granularity. This inventory groups the file into logical retirement clusters so delete work can happen one capability group at a time.

---

## Current structural reality

`pre_booking_auto_send.py` is still both:

1. a compatibility evaluator/orchestration shell
2. a shared helper home for pre-booking persistence/send side effects

That means Ship O must treat it as a staged collapse, not a binary delete.

---

## Symbol groups

### Group 1 — Portfolio / special deterministic draft helpers

Representative symbols:

- `PortfolioSearchCriteria`
- `_looks_like_portfolio_search_inquiry`
- `_extract_portfolio_search_criteria`
- `_find_portfolio_match_candidates`
- `_portfolio_match_draft`
- `_portfolio_match_hold_draft`
- `_grounded_pricing_policy_draft`
- `_direct_grounded_fallback_draft`
- `_answer_from_property_data`
- `_answer_from_guidebook_knowledge`
- `_should_create_verification_follow_up`
- `_verification_follow_up_draft`

**Migration status**

These were the core 4.5.D / 4.5.E bridge targets.

**Likely deletion shape**

- good first-wave deletion candidates once tests are moved off the legacy orchestrator harness

**Blockers**

- current unit tests still instantiate `PreBookingPipelineOrchestrator` to prove parity for these capabilities

---

### Group 2 — Knowledge-gap detection and hold semantics

Representative symbols:

- `KnowledgeTopicAssessment`
- `KnowledgeGapAnalysis`
- `_find_tagged_concierge_knowledge`
- `_topic_specific_evidence_hit`
- `_resolve_structured_topic`
- `detect_missing_knowledge`
- `_knowledge_gap_hold_draft`
- `_generate_knowledge_gap_hold_draft`

**Migration status**

- 4.5.E moved runtime ownership to Brain agents

**Likely deletion shape**

- candidate for deletion after parity tests stop using the legacy shell directly

**Blockers**

- still imported/used via `PreBookingPipelineOrchestrator` compatibility path

---

### Group 3 — Policy / send-decision layer

Representative symbols:

- `AutoSendPolicy`
- `SendDecision`
- `PolicyCheckResult`
- `check_inquiry_policy`
- `make_send_decision`
- `_apply_special_draft_source_policy`
- `_get_approval_mode`
- `_load_auto_send_policy`

**Migration status**

- runtime ownership moved during 4.5.C / 4.5.F
- but compatibility lifecycle still calls into this policy shell

**Likely deletion shape**

- not an early delete candidate until the Brain lifecycle no longer reuses these semantics through the legacy orchestrator compatibility layer

---

### Group 4 — Draft generation and provider path

Representative symbols:

- `_call_prebooking_groq`
- `_call_prebooking_claude`
- `_call_prebooking_gemini`
- `_ordered_prebooking_providers`
- `generate_inquiry_draft`
- `_is_usable_draft`
- `_build_reasoning_notes`
- `_fallback_draft`
- `_build_prebooking_grounding_context`
- `_ground_inquiry_draft`

**Migration status**

- runtime composition ownership moved to Brain agents/composer path
- but the legacy compatibility shell still references grounding/policy interactions around reviewed drafts

**Likely deletion shape**

- medium-risk symbol group
- should not be first-wave deletion

---

### Group 5 — Canonical input/stage structs

Representative symbols:

- `PreBookingInquiryInput`
- `PreBookingClassificationStage`
- `PreBookingDecisionStage`
- `PreBookingDraftStage`
- `SaveInquiryResult`
- `InquirySaveContext`

**Migration status**

- still actively imported by `messaging_brain/pre_booking_lifecycle.py`

**Delete eligibility**

- **not deletable**

**Needed before deletion**

- move these to a clearer shared home if they are still canonical

---

### Group 6 — Persistence / send / alert helper seams

Representative symbols:

- `save_inquiry_from_canonical`
- `_send_via_escapia`
- `_alert_operator_for_review`
- `_schedule_timeout_send`
- `_schedule_timeout_auto_send`
- `_log_required_mode_event`
- `_resolve_guest_thread_id_for_save`
- `_insert_pre_booking_inquiry`
- `_save_inquiry`

**Migration status**

- still actively imported by `messaging_brain/pre_booking_lifecycle.py`
- still referenced by worker/task runtime

**Delete eligibility**

- **not deletable today**

**Needed before deletion**

- either leave as shared helpers in a new non-legacy module
- or move callers away first

This is helper-extraction work, not simple deletion.

---

### Group 7 — Orchestration shell

Representative symbols:

- `PreBookingPipelineOrchestrator`
- `process_pre_booking_inquiry`
- `process_pre_booking_inquiry_with_draft`

**Migration status**

- Brain owns runtime, but these still participate in compatibility and fallback paths

**Delete eligibility**

- **not deletable today**

**Reason**

- `email_dispatch.py` still contains fallback to `process_pre_booking_inquiry_with_draft(...)`
- `messaging_brain/pre_booking_lifecycle.py` still instantiates `PreBookingPipelineOrchestrator`

This is the final-collapse group, not the first.

---

## Recommended deletion order inside Target E

When the verification window and compatibility callers allow it, the likely safest order is:

1. Group 1 — special deterministic draft helpers
2. Group 2 — knowledge-gap legacy internals
3. Group 4 — legacy draft/provider path
4. Group 3 — policy/send-decision layer
5. Group 7 — orchestration shell
6. Group 6 + 5 only after shared-helper relocation is complete

This order is tentative and should be rechecked against real callers before each delete commit.

---

## Bottom line

The first practical Ship O move for Target E is not deletion. It is:

- decide which groups are truly dead
- identify which groups are still canonical helper seams
- move tests off the legacy orchestrator harness where appropriate

Only then should symbol-group deletions begin.
