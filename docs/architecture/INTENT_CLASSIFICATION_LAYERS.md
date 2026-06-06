# Intent Classification Layers

Date: 2026-05-18
Status: Implemented in Phase 4.3-M

## Summary

Inbound guest intent classification now follows the same pattern as the email
extractor layer:

- deterministic classifier first
- LLM escalation only for uncertainty
- explicit router confidence gates before specialist dispatch
- audit metadata persisted into `message_normalizations.parser_notes`

This closes the Christina-class failure mode where a low-signal keyword match
could send a message to a specialist that was incapable of answering the real
question.

## Pre-booking path

Code path:

- [pre_booking_auto_send.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/concierge/pre_booking_auto_send.py)
- [intent_classification_escalator.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/concierge/intent_classification_escalator.py)

Flow:

1. `InquiryIntentClassifier` runs locally and returns:
   - `intent`
   - `confidence`
   - competing-intent metadata
   - contradictory-signal flag
2. `classify_with_escalation()` checks the tenant threshold.
3. If keyword confidence is below threshold, or the classifier sees competing
   low-signal intents, escalation runs:
   - Anthropic `claude-haiku-4-5`
   - Groq `meta-llama/llama-4-scout-17b-16e-instruct`
4. If escalation succeeds with confidence above threshold, the escalated result
   becomes the routed intent.
5. If escalation fails or remains low confidence, the original keyword result is
   preserved but the router demotes specialist routing to `general`.

Default threshold:

- `intent_classifier_escalation_threshold = 0.40`

Configuration source:

- `operator_settings.extra.intent_classifier_escalation_threshold`

## Brain path

Code path:

- [agent_router.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/messaging_brain/agents/agent_router.py)
- [orchestrator.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/messaging_brain/orchestrator.py)

The Brain-side `LLMIntakeAgent` already existed before Phase 4.3-M and remains
flag-gated by `MESSAGING_BRAIN_LLM_INTAKE` with default `OFF`.

What changed in this phase is the router gate:

- below threshold, the Brain routes to `GeneralAgent`
- above threshold, the existing topic-to-specialist routing remains unchanged

Default threshold:

- `brain_router_confidence_threshold = 0.30`

Configuration source:

- `operator_settings.extra.brain_router_confidence_threshold`

## Audit persistence

Both paths now persist classifier observability into
`message_normalizations.parser_notes`.

Pre-booking writes an appended JSON object with:

- `classifier_source`
- `threshold`
- `original_intent`
- `original_confidence`
- `escalated`
- `contradictory_signals`
- `escalation_provider`
- `escalated_confidence`
- `escalated_topic`

Brain writes an appended JSON object with:

- `classifier_source`
- `provider_used`
- `fallback_stage`
- `latency_ms`
- `input_tokens`
- `output_tokens`
- `coercion_notes`
- final `confidence`
- final `intent_topic`

## Cost observability

Every pre-booking escalation attempt records an `llm_usage_events` row with:

- `service_name = intent_classification_escalator`
- `request_type = intent_reclassification`

This makes escalation rate, fallback rate, and provider cost measurable without
adding new reporting tables.
