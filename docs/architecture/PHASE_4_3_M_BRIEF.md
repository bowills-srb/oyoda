# Phase 4.3-M Codex Brief — Intent-Classification AI Escalation + Router Confidence Gate

Date: 2026-05-18  
Phase: 4.3-M  
Status: Ready for implementation  
Scope: low-confidence intent escalation and confidence-threshold routing across pre-booking and Brain classification paths

## Context

Phase 4.3-K and the follow-on production investigations surfaced two distinct failures in inbound message routing. Both come from the same architectural gap: deterministic keyword classification is allowed to route uncertain messages directly to specialist agents instead of escalating uncertainty or falling through to a generalist.

Concrete production failure:

- Christina Moser, `INQ-A38A9382`, on `2026-05-17`
- subject referenced `100 S Spooky Lane Unit 2D`
- body asked about `high chair`, `pack and play`, `baby gate`, `beach toys`, and `beach chairs`
- property resolution was correct via raw property mention
- `InquiryIntentClassifier` in `pre_booking_auto_send.py` matched `beach` and classified the message as `local_area` at `0.10` confidence
- the pre-booking router accepted that classification and dispatched to `LocalRecommendationAgent`
- the Brain then composed a hedged, apologetic draft because the wrong specialist was running

This is not just a one-message anomaly. It demonstrates a general failure mode:

- low-confidence deterministic classification is currently treated as authoritative
- contradictory or ambiguous signals are not escalated for reconsideration
- routers do not gate on confidence before choosing a specialist

Two intent-classification paths currently exist in production:

1. Brain path
   Files:
   - [app/services/messaging_brain/agents/intake_agent.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/messaging_brain/agents/intake_agent.py)
   - [app/services/messaging_brain/agents/llm_intake_agent.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/messaging_brain/agents/llm_intake_agent.py)
   - [app/services/messaging_brain/agents/agent_router.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/messaging_brain/agents/agent_router.py)

   Facts:
   - keyword intake already exists
   - `LLMIntakeAgent` already exists with the right provider chain: Anthropic primary, Groq fallback, keyword ultimate fallback
   - `MESSAGING_BRAIN_LLM_INTAKE` exists and remains default `OFF`
   - `AgentRouter.route()` currently consumes confidence but does not gate on it

2. Pre-booking path
   File:
   - [app/services/concierge/pre_booking_auto_send.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/concierge/pre_booking_auto_send.py)

   Facts:
   - `InquiryIntentClassifier` is pure keyword logic
   - it can return confidence as low as `0.10`
   - there is no LLM escalation path
   - downstream routing accepts whatever it returns
   - this is the path Christina’s message took

The Brain-side LLM intake is already built. The pre-booking path is the larger gap. Phase 4.3-M brings the deterministic-first, LLM-when-uncertain pattern to both layers.

## Authoritative Reading Before Starting

- [app/services/concierge/pre_booking_auto_send.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/concierge/pre_booking_auto_send.py)
- [app/services/messaging_brain/agents/intake_agent.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/messaging_brain/agents/intake_agent.py)
- [app/services/messaging_brain/agents/llm_intake_agent.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/messaging_brain/agents/llm_intake_agent.py)
- [app/services/messaging_brain/agents/agent_router.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/messaging_brain/agents/agent_router.py)
- [app/services/orchestration/messaging_brain_contracts.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/orchestration/messaging_brain_contracts.py)
- [app/services/agents/router_agent.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/agents/router_agent.py)
- [docs/PHASE_2_SEAM_MAP.md](/Users/dhuntermckenzie/Downloads/oyvoda/docs/PHASE_2_SEAM_MAP.md)
- [docs/architecture/EXCEPTION_HANDLING_AUDIT.md](/Users/dhuntermckenzie/Downloads/oyvoda/docs/architecture/EXCEPTION_HANDLING_AUDIT.md)

Also use the recent Christina case as a concrete regression target while implementing.

## Goal

After this phase:

- pre-booking classification escalates low-confidence or contradictory keyword results to an LLM-based reclassifier before routing
- pre-booking routing refuses to send low-confidence messages directly to narrow specialist agents and falls through to a generalist path instead
- Brain-side `AgentRouter` adds a conservative confidence-threshold gate so low-confidence classifications route to fallback or generalist agents
- both paths emit observable classifier metadata describing whether routing came from plain keyword logic, low-confidence fallback, successful LLM escalation, or failed LLM escalation
- escalation is cost-bounded and only used in the uncertainty band, not on already-high-confidence traffic
- high-confidence existing behavior remains unchanged

## Hard Constraints

1. Audit first inside the phase. Run a production diagnostic query on recent Beach Habitats confidence values before locking the threshold.
2. The pre-booking escalation threshold must be configurable per tenant. Default `0.40`, but production data may justify tuning.
3. Reuse the existing Brain-side `LLMIntakeAgent` provider chain where practical. Do not introduce a parallel provider stack with different ordering.
4. `MESSAGING_BRAIN_LLM_INTAKE` remains default `OFF`. This phase does not enable that flag; it only adds routing confidence gates and pre-booking-side escalation.
5. Brain-side confidence gating should be conservative. Start with `0.30` on the Brain side unless production evidence argues otherwise.
6. Preserve behavior for high-confidence cases. This phase is for the low-confidence band, not a full routing rewrite.
7. LLM escalation failures must degrade explicitly back to keyword classification with audit metadata, not disappear silently.
8. Record LLM escalation cost and usage from day one.
9. Before adding schema, verify whether existing normalization metadata columns or JSONB fields already support the needed audit fields. Prefer reusing an existing structured metadata surface if that keeps scope smaller and observability equivalent.

## Investigation Steps

### Step 1: Production diagnostic — confidence distribution

Before writing escalation logic, inspect recent production confidence values for Beach Habitats:

```sql
SELECT
  ROUND(pbi.confidence::numeric, 1) AS confidence_bucket,
  COUNT(*) AS inquiry_count,
  COUNT(*) FILTER (
    WHERE pbi.property_external_id IS NOT NULL
      AND pbi.property_external_id != ''
  ) AS bound_count,
  COUNT(*) FILTER (WHERE pbi.intent = 'local_area') AS local_area_count,
  COUNT(*) FILTER (WHERE pbi.intent = 'general') AS general_count,
  ROUND(AVG(LENGTH(pbi.message_text))::numeric, 0) AS avg_msg_len
FROM pre_booking_inquiries pbi
WHERE pbi.company_id = 'e07980b2-a990-4b24-91d1-c8cb71ab70e1'
  AND pbi.received_at > NOW() - INTERVAL '30 days'
  AND pbi.archived_at IS NULL
GROUP BY confidence_bucket
ORDER BY confidence_bucket;
```

Validate or adjust the default threshold based on the real distribution. The starting assumption is `0.40`, not an untouchable constant.

### Step 2: Add pre-booking escalation hook

Replace the direct `InquiryIntentClassifier` call path with an escalation-aware wrapper.

Create:

- [app/services/concierge/intent_classification_escalator.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/concierge/intent_classification_escalator.py)

Conceptual shape:

```python
async def classify_with_escalation(
    *,
    message: str,
    conversation_context: str = "",
    tenant_id: UUID,
    db: Optional[AsyncSession] = None,
    threshold: Optional[float] = None,
) -> tuple[str, float, PreBookingClassifierMetadata]:
    ...
```

Expected behavior:

- run existing keyword classifier first
- if confidence is above threshold, return keyword result directly
- if confidence is below threshold or contradiction heuristics detect uncertainty, escalate to the LLM classifier
- if LLM returns a stronger result, use it
- if the LLM path fails or remains too uncertain, return the original keyword result with explicit metadata describing the failed escalation

Classifier source values should be explicit, for example:

- `keyword`
- `keyword_low_confidence_fallback`
- `llm_escalated_anthropic`
- `llm_escalated_groq`
- `llm_failed_keyword_default`

### Step 3: Reuse the Brain LLM intake path where it fits

`LLMIntakeAgent` already exists and already implements:

- provider chain
- prompt shape
- coercion and post-processing patterns
- deterministic fallback model

Prefer reuse or a thin wrapper over building a fully parallel pre-booking classifier stack, unless the pre-booking vocabulary mismatch makes reuse materially worse.

If reuse is awkward, share infrastructure rather than duplicating provider-call logic.

### Step 4: Add pre-booking router confidence gating

In the pre-booking orchestration path, if final confidence remains below threshold after escalation, do not route directly to a narrow specialist agent like `LocalRecommendationAgent`.

Instead:

- route to the existing generalist or fallback path
- ensure the resulting draft is safe for ambiguous or mixed-intent messages
- preserve specialist routing when confidence is clearly above threshold

The Christina regression should be impossible after this change: her message must not route to `local_recommendation` at `0.10` confidence.

### Step 5: Add Brain-side router confidence gating

In [agent_router.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/messaging_brain/agents/agent_router.py), add a confidence threshold gate so below-threshold classifications route to fallback agents regardless of primary topic.

Conceptual behavior:

```python
if classification.confidence < self._confidence_threshold:
    return RouteOutcome(
        agent_names=list(self._fallback),
        primary_topic=classification.intent_topic,
        secondary_topics=classification.secondary_topics,
        reason=...,
    )
```

This should be observable in the route reason and audit trail.

### Step 6: Audit metadata flow

Both classification paths must expose enough metadata to answer:

- what the original keyword intent was
- what the original confidence was
- whether escalation fired
- which provider handled escalation
- what escalated intent and confidence came back
- whether the system ultimately fell back to keyword classification

Before adding schema:

- inspect current `message_normalizations` shape and any existing metadata or JSONB fields
- prefer an existing structured metadata surface if it can store these cleanly
- only add a schema migration if there is no good existing place to put the data

### Step 7: Cost observability

Each LLM escalation call should be recorded in `LLMUsageTracker` with:

- `service_name="intent_classification_escalator"`
- `request_type="intent_reclassification"`
- provider, model, success, latency, fallback position
- metadata containing original and escalated intent plus confidence

This is required so escalation rate and cost can be measured immediately.

### Step 8: Exception handling

Apply specific exception handling on the new escalation path:

- structured logging with tenant id and bounded message context
- explicit fallback to keyword classification
- no silent masking

Use the patterns in [EXCEPTION_HANDLING_AUDIT.md](/Users/dhuntermckenzie/Downloads/oyvoda/docs/architecture/EXCEPTION_HANDLING_AUDIT.md) as the standard.

### Step 9: Tests

Add unit tests for:

- no escalation on high-confidence keyword results
- escalation on low-confidence keyword results
- LLM success replacing the keyword result
- LLM provider failure falling back to keyword with metadata
- Brain router low-confidence fallthrough to fallback agents
- Brain router preserving high-confidence specialist routing
- tenant-configured threshold overriding the default

Add an integration or regression test for Christina’s message shape:

```text
Hello- can you confirm if the unit has the following?
High chair
Pack and play
Baby gate
Beach toys
Beach chairs
```

This message must not route to `local_recommendation` at low confidence.

### Step 10: Documentation

Update architecture docs with:

- a short intent-classification layering doc or equivalent section
- threshold configuration notes
- escalation metadata notes
- exception-model notes for the new escalator

Also update operator knowledge or configuration docs if a tenant-level threshold setting is introduced there.

## Pre-flight Before Commit

- production diagnostic query run and threshold validated empirically
- `intent_classification_escalator.py` implemented
- pre-booking call sites migrated to the escalator
- Brain `AgentRouter` wired with confidence threshold logic
- metadata persistence shape verified in production before adding schema
- `LLMUsageTracker` records intent reclassification calls
- Christina regression test passes
- high-confidence existing behavior remains unchanged
- exception handling on new escalation paths is explicit and observable
- docs updated

## Commit Message Template

```text
Phase 4.3-M: intent-classification AI escalation + router confidence gate

Brings the deterministic-first-LLM-fallback pattern to intent
classification and routing, closing the low-confidence gap that produced
Christina Moser's mis-routed inquiry.

Changes:
- new intent classification escalator for pre-booking
- low-confidence LLM escalation using the existing Anthropic -> Groq chain
- pre-booking routing confidence gate
- Brain AgentRouter confidence gate
- classifier metadata and cost observability
- Christina regression coverage

Behavior preserving for high-confidence cases.
```

## Out of Scope

- enabling `MESSAGING_BRAIN_LLM_INTAKE` by default
- reservation-aware routing changes
- subject-line or quoted-body extraction fixes outside intent classification
- healer-agent architecture
- broad schema-regression framework work beyond the classification metadata need
- removing `operator_id` from `operator_policies`

## Required Completion Report Back

When the phase completes, report back with:

- commit SHA
- empirical threshold used
- observed escalation rate on a representative sample
- Christina regression result
- list of code paths migrated
