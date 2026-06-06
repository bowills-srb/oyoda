## Classifier Canonical Path

Date: 2026-05-18  
Phase: 4.5.A

### Decision

Intent classification is now committed to a deterministic-first Brain path:

1. `DeterministicIntakePreFilter` runs first
2. if confidence is at or above the tenant threshold and there are no contradictory signals, that result is final
3. otherwise `LLMIntakeAgent` is the escalation path
4. healer proposals add keywords into `operator_settings.extra.intent_classifier_keyword_overrides`
5. the pre-filter reads those overrides at runtime

This is a structural migration of the Phase 4.3-M pattern into
`app/services/messaging_brain/`. It is not a redesign.

### Threshold

- deterministic escalation threshold: `0.40`
- source: `operator_settings.extra.intent_classifier_escalation_threshold`
- default rationale: preserves the current Beach Habitats behavior from Phase 4.3-M, where roughly 84% of inquiries resolved deterministically and only the uncertainty band escalated

The threshold stays tenant-configurable. The default remains conservative:
deterministic routing only owns the cases it can classify with high precision.

### Runtime shape

- new agent: [deterministic_intake_prefilter.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/messaging_brain/agents/deterministic_intake_prefilter.py)
- orchestrator gate: [orchestrator.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/messaging_brain/orchestrator.py)
- legacy bridge flag: `BRAIN_INTAKE_PRIMARY`
- shadow audit flag: `BRAIN_INTAKE_SHADOW`

While `BRAIN_INTAKE_PRIMARY` is `OFF`, the old Brain intake selection stays
available and legacy pre-booking keeps its current classifier path.

When `BRAIN_INTAKE_PRIMARY` is `ON`:

- the Brain always runs the deterministic pre-filter first
- low-confidence or contradictory cases escalate to `LLMIntakeAgent`
- `brain_classifier_metadata.classifier_source` records:
  - `deterministic`
  - `llm_escalated`
  - `llm_failed_keyword_default`

When `BRAIN_INTAKE_PRIMARY` is `OFF` but `BRAIN_INTAKE_SHADOW` is `ON`:

- legacy pre-booking still owns the live classification result
- the Brain deterministic-first classifier runs in shadow for audit only
- a `brain_classifier_metadata` parser-note payload is appended beside the
  legacy `intent_classifier_metadata` payload so agreement can be measured
  without changing production routing

### Legacy parity bridge

Phase 4.5.A does not delete the full legacy pre-booking pipeline yet.
Instead, it replaces the legacy classifier call site with a bridge into the
Brain classification stage behind `BRAIN_INTAKE_PRIMARY`.

That means:

- legacy drafting and policy logic can keep running during this cutover phase
- the actual intent decision comes from the Brain stage when the flag is on
- parity can be measured before the later deletion step

### Healer commitment

The healer now scans `brain_classifier_metadata`, not legacy
`intent_classifier_metadata`.

Approved `intent_classifier_keyword_suggestion` proposals write into
`operator_settings.extra.intent_classifier_keyword_overrides`, and the new
pre-filter reads that dict at classification time. That closes the full
deterministic learning loop inside the Brain path.

### Deferred deletion

The following legacy pieces are intentionally not deleted in this commit:

- `InquiryIntentClassifier`
- `classify_with_escalation()`
- `intent_classifier_metadata` legacy audit payload emission

Those are removed after:

1. parity validation is complete
2. `BRAIN_INTAKE_PRIMARY` has been on in production for one deployment cycle
3. deterministic resolution rate remains at or above the target floor
