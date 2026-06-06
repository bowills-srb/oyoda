# LLM Usage Coverage Audit

Date: 2026-05-27

Purpose: identify whether `llm_usage_events` is currently complete enough to support a per-tenant admin cost dashboard.

## Current conclusion

Coverage is partial, not complete.

The tracking foundation is good:

- `app/services/observability/llm_usage_tracker.py`
- `llm_usage_events` table exists in production
- several key messaging-brain and parsing paths already record usage

But there are still live model-call paths that do not record usage. If we ship the dashboard before filling those gaps, per-tenant cost will be undercounted.

## Confirmed tracked call paths

These files import `LLMUsageTracker` and call `record(...)` directly:

- `app/services/integrations/llm_email_extractor.py`
- `app/services/messaging_brain/agents/llm_intake_agent.py`
- `app/services/messaging_brain/agents/llm_composer_agent.py`
- `app/services/messaging_brain/grounding/response_reviewer.py`
- `app/services/messaging_brain/agents/knowledge_gap_hold_agent.py`
- `app/services/messaging_brain/intake/topic_classifier.py`
- `app/services/messaging_brain/intake/intent_escalator.py`
- `app/services/backfill/structured_property_backfill.py`

That means the current dashboard backend should already have meaningful events for:

- LLM-first email extraction
- Groq/Anthropic intake classification
- LLM composer
- adversarial review
- KB hold drafting
- topic-classifier / escalation sidecars
- structured-property backfill

## Confirmed untracked model-call paths

These files make direct LLM API calls but do not currently record usage through `LLMUsageTracker`:

### Production-relevant

- `app/services/knowledge/voice_pod.py`
  - Groq primary, Gemini fallback
  - this matters because session-channel and SMS flows can route through VoicePod

- `app/services/extraction/llm_extractor.py`
  - Anthropic extraction for document/guidebook normalization
  - returns usage in memory, but does not persist it to `llm_usage_events`

- `app/services/messaging_brain/inbound_message_gate.py`
  - Anthropic gating/classification path
  - no persisted usage event

- `app/services/voice/voice_session.py`
  - Anthropic voice-session generation path
  - no persisted usage event

### Lower-priority / non-core

- `app/api/v1/endpoints/mobile.py`
  - direct Groq fallback path
  - legacy/demo-ish surface, but still untracked if used

- `app/api/v1/endpoints/landing.py`
  - direct Groq demo chat path
  - likely not operationally critical, but still omitted from cost totals

## Important nuance

`app/services/extraction/extractor_orchestrator.py` aggregates token/cost stats in memory from `LLMExtractor`, but that is not the same as writing tenant-attributed usage rows to `llm_usage_events`.

So:

- extraction runs may have local run summaries
- but the admin dashboard will still undercount them unless `LLMUsageTracker.record(...)` is called inside the extraction path

## Recommended fix order

1. `voice_pod.py`
   - largest practical blind spot for guest-session / SMS usage

2. `llm_extractor.py`
   - largest blind spot for ingestion / normalization cost

3. `inbound_message_gate.py`
   - needed if that gate remains active in any tenant flow

4. `voice_session.py`
   - smaller surface, but still real

5. `mobile.py` and `landing.py`
   - optional before admin-v1 if we want to keep the first dashboard focused on operational costs only

## Minimum bar before building the admin dashboard

Before shipping the v2 admin LLM-cost dashboard, we should have:

- all production guest-message classification paths tracked
- all production guest-message response-generation paths tracked
- all production ingestion / normalization paths tracked

Today we are close, but not there yet.
