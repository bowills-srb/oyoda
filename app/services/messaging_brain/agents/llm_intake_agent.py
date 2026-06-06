"""
llm_intake_agent.py — LLM-based intent classifier for the messaging brain.

Session 9 (Phase 2) — see docs/PHASE_2_SEAM_MAP.md.

Replaces the keyword-based IntakeAgent's wrapping of ConciergeRouter with
a direct LLM classification call. Same MessageClassification output
contract (with two additive fields: sub_intents, extracted_constraints)
so nothing downstream changes.

Provider chain:
    Groq llama-4-scout           (primary)
        ↓ (timeout / failure / no key)
    Anthropic Claude Haiku 4.5  (secondary)
        ↓ (timeout / failure / no key)
    Keyword IntakeAgent          (ultimate fallback)

Total budget: 4.0s. Per-provider timeout: 2.5s. The keyword fallback
has no timeout — it's local keyword matching.

This agent is stateless across calls. Per-call metadata is returned
explicitly via classify_with_metadata() rather than stored on the
instance. The orchestrator may share one instance across concurrent
message handlers — there must be no mutable per-call state on self.

The prompt is the contract boundary. See PROMPT below for the exact
text sent to the model. Coercion of model output happens in
_post_process(): every coercion step is recorded as an audit note in
ClassifierMetadata.coercion_notes so failures are queryable later.

Default: not used in production. The brain orchestrator selects
between this agent and the keyword IntakeAgent at message-handling
time based on the MESSAGING_BRAIN_LLM_INTAKE feature flag, which
defaults OFF. Session 9 ships the code; later rollout work is when it
gets turned on for any real traffic.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

import httpx

from app.services.messaging_brain.agents.intake_agent import IntakeAgent
from app.services.observability.llm_usage_tracker import LLMUsageTracker
from app.services.orchestration.messaging_brain_contracts import (
    ClassifierMetadata,
    InboundGuestMessage,
    IntentType,
    KNOWN_INTENT_TOPICS,
    MessageClassification,
    Urgency,
)

logger = logging.getLogger(__name__)


def _coerce_tenant_uuid(value: str | None) -> UUID | None:
    try:
        return UUID(str(value)) if value else None
    except (TypeError, ValueError):
        return None


# ─────────────────────────────────────────────────────────────────────────────
# The prompt
# ─────────────────────────────────────────────────────────────────────────────

PROMPT = """You are an inbound-message classifier for a vacation-rental property management
platform. You classify guest messages so the right downstream agent can answer
them. Your output must be a single JSON object that validates against the schema
below — no commentary, no markdown, no extra text.

# Output Schema

{
  "intent_type": "question" | "request" | "problem",
  "intent_topic": "access" | "maintenance" | "house_rules" | "local_recommendation"
                  | "late_checkout" | "booking_inquiry" | "complaint"
                  | "emergency" | "general",
  "secondary_topics": [<topics from the same enum, optional>],
  "sub_intents": [<strings, see Sub-Intent Vocabulary below>],
  "confidence": <float 0.0 to 1.0>,
  "urgency": "low" | "medium" | "high" | "emergency",
  "requires_human_review": <bool>,
  "reason": <short string explaining the classification>,
  "extracted_constraints": <object, see below>
}

# Topic Definitions (use ONLY these for intent_topic and secondary_topics)

- access: door codes, parking, wifi password, check-in instructions, lockboxes,
  garage, gate codes, key handoff. CREDENTIAL/INSTRUCTION-shaped questions.
- maintenance: anything broken, malfunctioning, dirty, pest-related, or
  requesting repair/cleaning DURING a stay.
- house_rules: pets, smoking, quiet hours, occupancy limits, parties/events,
  rules around amenity use.
- local_recommendation: restaurants, activities, things to do, kid-friendly
  options, beach/lake/mountain recommendations, transportation, local services.
- late_checkout: timing flexibility around arrival or departure for an
  existing/upcoming booking — late checkout, EARLY CHECK-IN, extending the
  stay, adding nights. Both early-arrival and late-departure live here.
- booking_inquiry: ANY pre-booking question about a property — availability,
  pricing/rates, discounts, amenities (pool, hot tub, beach gear, ski
  storage), property layout, sleeping arrangements, group size fit, what's
  included, "do you have anything available," "how much does it cost,"
  "does the property have X," portfolio search ("looking for a property
  with..."), and similar.
- complaint: angry guest, refund request, damage dispute, frustrated
  emotional content.
- emergency: safety, injury, fire, gas leak, locked out at night, hurricane
  evacuation, medical situation.
- general: doesn't fit any of the above. Lean toward picking the closest
  topic above unless truly ambiguous.

# Coercion Rules (CRITICAL — apply before emitting intent_topic)

These messages MUST classify as `booking_inquiry` (NOT a different topic),
with nuance carried in sub_intents + reason + extracted_constraints:

- pricing or rate questions → booking_inquiry, sub_intents: ["pricing"]
- discount or deal requests → booking_inquiry, sub_intents: ["pricing", "discount"]
- availability for specific dates → booking_inquiry, sub_intents: ["availability"]
- amenity questions BEFORE booking ("does it have a pool?") →
  booking_inquiry, sub_intents: ["amenities"]
- group/party size fit → booking_inquiry, sub_intents: ["group_size"]
- bed configuration / sleeping arrangement BEFORE booking →
  booking_inquiry, sub_intents: ["sleeping_arrangement"]
- portfolio searches ("any property with X for these dates") →
  booking_inquiry, sub_intents: ["portfolio_search"]
- "is this property right for us" framing → booking_inquiry

DURING-STAY versions of similar questions ("the pool isn't working",
"the wifi is broken") are NOT booking_inquiry — those are maintenance.
Pre-booking vs. in-stay is the discriminator.

These messages MUST classify as `late_checkout` (NOT access or general):

- "early check-in" or "arrive early" or "can we get in before [time]"
- "late checkout" or "leave late" or "checkout late"
- "extend my stay" or "extra night" or "stay longer"
- Any timing flexibility around arrival OR departure for an existing booking

Access credentials/instructions ("what's the wifi password," "where's the
lockbox," "what's the door code") stay in `access` — those are about
HOW to enter/use, not WHEN to arrive/leave.

# secondary_topics

Use ONLY topic strings from the same enum as intent_topic. If a message has
multiple genuine routeable concerns (e.g. a complaint that also mentions
maintenance: "the AC has been broken all night and I want a refund"), put
the secondary topic here.

Do NOT put advisory tags like "pricing" or "availability" in secondary_topics.
Those go in sub_intents.

If there is no genuine secondary routeable topic, return an empty array.

# Sub-Intent Vocabulary (open — preferred examples, not exhaustive)

sub_intents is advisory metadata for downstream agents. Open vocabulary —
you may emit any string that captures a meaningful nuance.

Preferred values when applicable (use these phrasings when possible):

  pricing                 amenities             availability
  discount                portfolio_search      group_size
  sleeping_arrangement    early_check_in        late_checkout
  payment_coordination    road_access           local_services
  refund_request          policy_question       reservation_modification

If a guest message has a market-specific concern not in this list, emit a
short snake_case tag that captures it (e.g. "altitude_concern",
"hurricane_evac", "boat_access"). Don't force concerns into the preferred
list if they don't fit.

# extracted_constraints Schema (loose — include only what's stated)

Optional object. Include any of these fields if the guest stated them:

{
  "dates": {
    "check_in": "YYYY-MM-DD" or "YYYY-MM" or natural-language string,
    "check_out": "YYYY-MM-DD" or natural-language string,
    "nights": <int>
  },
  "party_size": {
    "adults": <int>, "children": <int>, "total": <int>
  },
  "budget": {
    "amount": <number>, "currency": "USD"|"EUR"|..., "scope": "total"|"per_night"
  },
  "bedroom_count": <int>,
  "community": <string>,
  "pricing_concern": <string — e.g. "first_time_discount", "rate_match", "long_stay">,
  "amenity_asks": [<list of asked-about amenities>],
  "sleeping_concern": <string describing the specific concern>,
  "other": <string for anything not covered above>,
  "portfolio_search": {
    "anchor_property": <string — the property the guest referenced by name, e.g. "the xyz house">,
    "compare_on": [<"bedrooms"|"bathrooms"|"price"|"location"|"sleeps">],
    "date_window": {
      "check_in": "YYYY-MM-DD",
      "check_out": "YYYY-MM-DD"
    },
    "result_limit_hint": <int, optional — how many options the guest asked for>
  }
}

Include `portfolio_search` only when sub_intents contains "portfolio_search".
anchor_property is advisory — if you can infer it from context, include it;
if not, omit rather than guessing. Malformed or partial → omit the whole block.

If a field doesn't apply, omit it entirely. Don't include null values.

# Urgency Guidance

- emergency: safety, fire, gas leak, injury, "I'm locked out at midnight"
- high: damage, refund disputes, immediate-stay issues, anger
- medium: most pre-booking inquiries, in-stay questions, requests
- low: casual questions, recommendations, informational

# Confidence Guidance

- 0.90+: unambiguous (clear emergency, clear single ask)
- 0.70-0.89: confident but message has minor ambiguity
- 0.50-0.69: probable classification but real ambiguity exists
- below 0.50: significant ambiguity; downstream should treat as low-confidence

# Reason

In `reason`, briefly explain WHY you classified this way. One sentence.
Use it to surface anything downstream agents should know that doesn't fit
elsewhere — edge cases, multi-topic messages, pricing nuance,
market-specific concerns.

# Output

Return ONE JSON object. No markdown, no code fences, no commentary."""


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

_INBOUND_TOPICS: frozenset[str] = frozenset(
    topic for topic in KNOWN_INTENT_TOPICS if not topic.startswith("system_")
)

# Enumerate the topics hardcoded in PROMPT to catch drift if the prompt is
# edited but messaging_brain_contracts.py is not updated.
_PROMPT_TOPICS: frozenset[str] = frozenset({
    "access", "maintenance", "house_rules", "local_recommendation",
    "late_checkout", "booking_inquiry", "complaint", "emergency", "general",
})
_prompt_not_in_contract = _PROMPT_TOPICS - KNOWN_INTENT_TOPICS
if _prompt_not_in_contract:
    raise RuntimeError(
        f"LLM intake PROMPT lists topics absent from KNOWN_INTENT_TOPICS: "
        f"{sorted(_prompt_not_in_contract)}. Update messaging_brain_contracts.py."
    )

_INBOUND_INTENT_TYPES: frozenset[str] = frozenset({
    "question",
    "request",
    "problem",
})

_BOOKING_INQUIRY_SUB_INTENTS: frozenset[str] = frozenset({
    "pricing",
    "rate",
    "rates",
    "discount",
    "deal",
    "deals",
    "availability",
    "available",
    "amenities",
    "amenity",
    "portfolio_search",
    "portfolio",
    "group_size",
    "group",
    "sleeping_arrangement",
    "sleeping",
})

_LATE_CHECKOUT_SUB_INTENTS: frozenset[str] = frozenset({
    "early_check_in",
    "early_checkin",
    "early_arrival",
    "late_checkout",
    "late_check_out",
    "late_departure",
    "extend_stay",
    "extra_night",
})

_URGENCY_VALUES: frozenset[str] = frozenset({
    "low",
    "medium",
    "high",
    "emergency",
})

_SUB_INTENT_NORMALIZATION: Dict[str, str] = {
    "discount_request": "discount",
    "discount_inquiry": "discount",
    "snow_chains": "road_access",
    "chains_required": "road_access",
    "chair_service": "local_services",
    "beach_service": "local_services",
    "pricing_negotiation": "pricing",
    "rate_match": "pricing",
    "early_arrival": "early_check_in",
    "early_checkin": "early_check_in",
    "early-check-in": "early_check_in",
}

_HEAVY_COERCION_PREFIXES: tuple[str, ...] = (
    "llm_invalid_json",
    "llm_missing_required",
    "llm_topic_coerced",
    "llm_constraints_malformed",
)


class LLMIntakeAgent:
    """LLM-based intent classifier. Same interface as IntakeAgent."""

    name = "IntakeAgent"

    def __init__(
        self,
        *,
        anthropic_key: Optional[str] = None,
        groq_key: Optional[str] = None,
        keyword_fallback: Optional[IntakeAgent] = None,
        per_provider_timeout_seconds: float = 2.5,
        total_budget_seconds: float = 4.0,
        model_anthropic: str = "claude-haiku-4-5",
        model_groq: str = "meta-llama/llama-4-scout-17b-16e-instruct",
        max_output_tokens: int = 600,
    ) -> None:
        self._anthropic_key = (
            anthropic_key
            if anthropic_key is not None
            else os.getenv("ANTHROPIC_API_KEY", "")
        )
        self._groq_key = (
            groq_key
            if groq_key is not None
            else os.getenv("GROQ_API_KEY", "")
        )
        self._fallback = keyword_fallback or IntakeAgent()
        self._per_provider_timeout = per_provider_timeout_seconds
        self._total_budget = total_budget_seconds
        self._model_anthropic = model_anthropic
        self._model_groq = model_groq
        self._max_output_tokens = max_output_tokens

    async def classify(
        self,
        message: InboundGuestMessage,
        *,
        db_session: Any = None,
    ) -> MessageClassification:
        classification, _ = await self.classify_with_metadata(
            message,
            db_session=db_session,
        )
        return classification

    async def classify_with_metadata(
        self,
        message: InboundGuestMessage,
        *,
        db_session: Any = None,
    ) -> Tuple[MessageClassification, ClassifierMetadata]:
        start = time.monotonic()
        notes: List[str] = []
        tenant_id = _coerce_tenant_uuid(message.tenant_id)

        if self._groq_key:
            remaining = min(
                self._total_budget,
                self._per_provider_timeout,
            )
            groq_started = time.monotonic()
            raw, provider_notes, input_tokens, output_tokens, error_type = await self._try_provider(
                provider="groq",
                fn=self._call_groq,
                message=message,
                timeout_override=remaining,
            )
            notes.extend(provider_notes)
            if raw is not None:
                try:
                    classification, coerce_notes = self._post_process(
                        raw,
                        message,
                        provider="groq",
                    )
                except _ProviderParseFailure as exc:
                    await self._record_usage(
                        tenant_id=tenant_id,
                        provider="groq",
                        model_id=self._model_groq,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        success=False,
                        started_at=groq_started,
                        fallback_position=1,
                        error_type="parse_failure",
                        message=message,
                    )
                    notes.append(str(exc))
                except _MissingRequiredFieldError as exc:
                    await self._record_usage(
                        tenant_id=tenant_id,
                        provider="groq",
                        model_id=self._model_groq,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        success=False,
                        started_at=groq_started,
                        fallback_position=1,
                        error_type="missing_required_field",
                        message=message,
                    )
                    notes.extend(exc.notes)
                else:
                    notes.extend(coerce_notes)
                    await self._record_usage(
                        tenant_id=tenant_id,
                        provider="groq",
                        model_id=self._model_groq,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        success=True,
                        started_at=groq_started,
                        fallback_position=1,
                        message=message,
                    )
                    metadata = self._build_metadata(
                        classifier_source="llm",
                        provider_used="groq",
                        fallback_stage="groq_primary",
                        start=start,
                        notes=notes,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                    )
                    classification = self._apply_heavy_coercion_review(
                        classification,
                        notes,
                    )
                    return classification, metadata
            else:
                await self._record_usage(
                    tenant_id=tenant_id,
                    provider="groq",
                    model_id=self._model_groq,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    success=False,
                    started_at=groq_started,
                    fallback_position=1,
                    error_type=error_type or "provider_failure",
                    message=message,
                )
        else:
            notes.append("llm_no_groq_key")

        elapsed = time.monotonic() - start
        if elapsed >= self._total_budget:
            notes.append("llm_budget_exhausted_before_anthropic")
        elif self._anthropic_key:
            remaining = min(
                self._total_budget - elapsed,
                self._per_provider_timeout,
            )
            anthropic_started = time.monotonic()
            raw, provider_notes, input_tokens, output_tokens, error_type = await self._try_provider(
                provider="anthropic",
                fn=self._call_anthropic,
                message=message,
                timeout_override=remaining,
            )
            notes.extend(provider_notes)
            if raw is not None:
                try:
                    classification, coerce_notes = self._post_process(
                        raw,
                        message,
                        provider="anthropic",
                    )
                except _ProviderParseFailure as exc:
                    await self._record_usage(
                        tenant_id=tenant_id,
                        provider="anthropic",
                        model_id=self._model_anthropic,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        success=False,
                        started_at=anthropic_started,
                        fallback_position=2 if self._groq_key else 1,
                        error_type="parse_failure",
                        message=message,
                    )
                    notes.append(str(exc))
                except _MissingRequiredFieldError as exc:
                    await self._record_usage(
                        tenant_id=tenant_id,
                        provider="anthropic",
                        model_id=self._model_anthropic,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        success=False,
                        started_at=anthropic_started,
                        fallback_position=2 if self._groq_key else 1,
                        error_type="missing_required_field",
                        message=message,
                    )
                    notes.extend(exc.notes)
                else:
                    notes.extend(coerce_notes)
                    await self._record_usage(
                        tenant_id=tenant_id,
                        provider="anthropic",
                        model_id=self._model_anthropic,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        success=True,
                        started_at=anthropic_started,
                        fallback_position=2 if self._groq_key else 1,
                        message=message,
                    )
                    metadata = self._build_metadata(
                        classifier_source="llm",
                        provider_used="anthropic",
                        fallback_stage=(
                            "anthropic_after_groq_failed"
                            if self._groq_key
                            else None
                        ),
                        start=start,
                        notes=notes,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                    )
                    classification = self._apply_heavy_coercion_review(
                        classification,
                        notes,
                    )
                    return classification, metadata
            else:
                await self._record_usage(
                    tenant_id=tenant_id,
                    provider="anthropic",
                    model_id=self._model_anthropic,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    success=False,
                    started_at=anthropic_started,
                    fallback_position=2 if self._groq_key else 1,
                    error_type=error_type or "provider_failure",
                    message=message,
                )
        else:
            notes.append("llm_no_anthropic_key")

        if not self._anthropic_key and not self._groq_key:
            notes.append("llm_no_keys_configured")
        else:
            notes.append("llm_all_providers_failed")

        classification = await self._fallback.classify(message, db_session=db_session)
        metadata = self._build_metadata(
            classifier_source="keyword_fallback",
            provider_used=None,
            fallback_stage="keyword_after_llm_chain",
            start=start,
            notes=notes,
            input_tokens=None,
            output_tokens=None,
        )
        return classification, metadata

    async def _try_provider(
        self,
        *,
        provider: str,
        fn: Any,
        message: InboundGuestMessage,
        timeout_override: Optional[float] = None,
    ) -> Tuple[Optional[Dict[str, Any]], List[str], Optional[int], Optional[int], Optional[str]]:
        notes: List[str] = []
        timeout = (
            timeout_override
            if timeout_override is not None
            else self._per_provider_timeout
        )

        try:
            response = await asyncio.wait_for(fn(message), timeout=timeout)
        except asyncio.TimeoutError:
            notes.append(f"llm_timeout:{provider}")
            return None, notes, None, None, "timeout"
        except Exception as exc:  # noqa: BLE001
            notes.append(f"llm_exception:{provider}:{type(exc).__name__}")
            logger.warning("[LLMIntakeAgent] %s provider failed: %s", provider, exc)
            return None, notes, None, None, type(exc).__name__

        if response is None:
            notes.append(f"llm_empty_response:{provider}")
            return None, notes, None, None, "empty_response"

        # Backward-compatible test seam: older mocks may still return
        # (text, usage_dict) tuples. Normalize them into the canonical
        # response dict shape used by the real provider helpers.
        if isinstance(response, tuple) and len(response) == 2:
            text, usage = response
            usage = usage or {}
            response = {
                "text": text,
                "input_tokens": usage.get("input_tokens"),
                "output_tokens": usage.get("output_tokens"),
            }

        text = response.get("text", "")
        input_tokens = response.get("input_tokens")
        output_tokens = response.get("output_tokens")
        if not text or not str(text).strip():
            notes.append(f"llm_empty_response:{provider}")
            return None, notes, input_tokens, output_tokens, "empty_response"

        return response, notes, input_tokens, output_tokens, None

    async def _record_usage(
        self,
        *,
        tenant_id: UUID | None,
        provider: str,
        model_id: str,
        input_tokens: Optional[int],
        output_tokens: Optional[int],
        success: bool,
        started_at: float,
        fallback_position: int,
        message: InboundGuestMessage,
        error_type: str | None = None,
    ) -> None:
        await LLMUsageTracker.record(
            service_name="brain_intake_classifier",
            tenant_id=tenant_id,
            request_type="brain_intake_classification",
            provider=provider,
            model_id=model_id,
            input_tokens=input_tokens or 0,
            output_tokens=output_tokens or 0,
            success=success,
            latency_ms=int((time.monotonic() - started_at) * 1000),
            fallback_position=fallback_position,
            error_type=error_type,
            metadata={
                "message_id": message.message_id,
                "property_code": message.property_code or "",
            },
        )

    async def _call_anthropic(
        self,
        message: InboundGuestMessage,
    ) -> Optional[Dict[str, Any]]:
        async with httpx.AsyncClient(timeout=self._per_provider_timeout) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self._anthropic_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self._model_anthropic,
                    "max_tokens": self._max_output_tokens,
                    "system": PROMPT,
                    "messages": [{"role": "user", "content": message.text or ""}],
                    "temperature": 0.0,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        try:
            text = data["content"][0]["text"]
        except (KeyError, IndexError, TypeError):
            return None

        usage = data.get("usage") or {}
        return {
            "text": text,
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
        }

    async def _call_groq(
        self,
        message: InboundGuestMessage,
    ) -> Optional[Dict[str, Any]]:
        async with httpx.AsyncClient(timeout=self._per_provider_timeout) as client:
            resp = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._groq_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self._model_groq,
                    "messages": [
                        {"role": "system", "content": PROMPT},
                        {"role": "user", "content": message.text or ""},
                    ],
                    "max_tokens": self._max_output_tokens,
                    "temperature": 0.0,
                    "response_format": {"type": "json_object"},
                },
            )
            resp.raise_for_status()
            data = resp.json()

        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return None

        usage = data.get("usage") or {}
        return {
            "text": text,
            "input_tokens": usage.get("prompt_tokens"),
            "output_tokens": usage.get("completion_tokens"),
        }

    def _post_process(
        self,
        raw: Dict[str, Any],
        message: InboundGuestMessage,
        *,
        provider: str,
    ) -> Tuple[MessageClassification, List[str]]:
        notes: List[str] = []
        payload = self._parse_payload_text(raw.get("text", ""), provider=provider)

        for required in ("intent_type", "intent_topic", "confidence"):
            if required not in payload:
                notes.append(f"llm_missing_required:{required}")
                notes.append(f"llm_missing_required:{required}:{provider}")
                raise _MissingRequiredFieldError(required, notes)

        intent_type_raw = str(payload.get("intent_type", "")).lower().strip()
        intent_type = self._coerce_intent_type(intent_type_raw, notes)

        intent_topic_raw = str(payload.get("intent_topic", "")).lower().strip()
        intent_topic, sub_intents_from_topic = self._coerce_intent_topic(
            intent_topic_raw,
            notes,
        )

        confidence = self._coerce_confidence(payload.get("confidence"), notes)
        urgency = self._coerce_urgency(payload.get("urgency"), notes)

        secondary_topics_raw = payload.get("secondary_topics", [])
        secondary_topics, promoted_to_sub = self._coerce_secondary_topics(
            secondary_topics_raw,
            intent_topic,
            notes,
        )

        sub_intents_raw = payload.get("sub_intents", [])
        sub_intents = self._coerce_sub_intents(sub_intents_raw, notes)
        for item in sub_intents_from_topic:
            if item not in sub_intents:
                sub_intents.append(item)
        for item in promoted_to_sub:
            if item not in sub_intents:
                sub_intents.append(item)

        constraints_raw = payload.get("extracted_constraints", {})
        if isinstance(constraints_raw, dict):
            extracted_constraints = constraints_raw
        else:
            notes.append("llm_constraints_malformed")
            extracted_constraints = {}

        requires_review_raw = payload.get("requires_human_review")
        requires_review = self._coerce_requires_review(
            requires_review_raw,
            intent_topic,
            urgency,
            notes,
        )

        reason = str(payload.get("reason", "") or "").strip()

        classification = MessageClassification(
            intent_type=intent_type,
            intent_topic=intent_topic,
            secondary_topics=secondary_topics,
            sub_intents=sub_intents,
            extracted_constraints=extracted_constraints,
            confidence=confidence,
            urgency=urgency,
            requires_human_review=requires_review,
            reason=reason,
            matched_keyword=None,
            matched_route=None,
        )
        return classification, notes

    def _parse_payload_text(
        self,
        text: str,
        *,
        provider: str,
    ) -> Dict[str, Any]:
        candidate = str(text or "").strip()
        if not candidate:
            raise _ProviderParseFailure(f"llm_empty_response:{provider}")

        if candidate.startswith("```"):
            lines = candidate.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            candidate = "\n".join(lines).strip()

        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError as exc:
            raise _ProviderParseFailure(f"llm_invalid_json:{provider}") from exc

        if not isinstance(payload, dict):
            raise _ProviderParseFailure(f"llm_invalid_json:{provider}")
        return payload

    @staticmethod
    def _coerce_intent_type(raw: str, notes: List[str]) -> IntentType:
        if raw in _INBOUND_INTENT_TYPES:
            return IntentType(raw)

        aliases = {
            "informational": IntentType.QUESTION,
            "info": IntentType.QUESTION,
            "action": IntentType.REQUEST,
            "issue": IntentType.PROBLEM,
            "complaint": IntentType.PROBLEM,
        }
        if raw in aliases:
            notes.append(f"llm_intent_type_coerced:{raw}->{aliases[raw].value}")
            return aliases[raw]

        notes.append(f"llm_intent_type_coerced:{raw}->question")
        return IntentType.QUESTION

    @staticmethod
    def _coerce_intent_topic(
        raw: str,
        notes: List[str],
    ) -> Tuple[str, List[str]]:
        if raw in _INBOUND_TOPICS:
            return raw, []

        if raw.startswith("system_"):
            notes.append(f"llm_topic_coerced:{raw}->general")
            return "general", []

        if raw in _BOOKING_INQUIRY_SUB_INTENTS:
            notes.append(f"llm_topic_coerced:{raw}->booking_inquiry")
            return "booking_inquiry", [raw]

        if raw in _LATE_CHECKOUT_SUB_INTENTS:
            notes.append(f"llm_topic_coerced:{raw}->late_checkout")
            return "late_checkout", [raw]

        notes.append(f"llm_topic_coerced:{raw}->general")
        return "general", []

    @staticmethod
    def _coerce_confidence(raw: Any, notes: List[str]) -> float:
        if raw is None:
            notes.append("llm_confidence_missing")
            return 0.50
        try:
            value = float(raw)
        except (TypeError, ValueError):
            notes.append("llm_confidence_default")
            return 0.50
        if value < 0.0 or value > 1.0:
            notes.append(f"llm_confidence_clamped:{value}")
            value = max(0.0, min(1.0, value))
        return value

    @staticmethod
    def _coerce_urgency(raw: Any, notes: List[str]) -> Urgency:
        if raw is None:
            return Urgency.MEDIUM
        value = str(raw).lower().strip()
        if value in _URGENCY_VALUES:
            return Urgency(value)

        aliases = {
            "normal": Urgency.MEDIUM,
            "standard": Urgency.MEDIUM,
            "critical": Urgency.EMERGENCY,
            "none": Urgency.LOW,
            "info": Urgency.LOW,
        }
        if value in aliases:
            notes.append(f"llm_urgency_coerced:{value}->{aliases[value].value}")
            return aliases[value]

        notes.append(f"llm_urgency_coerced:{value}->medium")
        return Urgency.MEDIUM

    @staticmethod
    def _coerce_secondary_topics(
        raw: Any,
        primary_topic: str,
        notes: List[str],
    ) -> Tuple[List[str], List[str]]:
        if not isinstance(raw, list):
            notes.append("llm_secondary_malformed")
            return [], []

        clean: List[str] = []
        promoted: List[str] = []
        seen: set[str] = set()
        deduped_primary = False
        deduped_other = False

        for entry in raw:
            if not isinstance(entry, str):
                continue
            normalized = entry.lower().strip()
            if not normalized:
                continue
            if normalized == primary_topic:
                deduped_primary = True
                continue
            if normalized in seen:
                deduped_other = True
                continue
            seen.add(normalized)
            if normalized in _INBOUND_TOPICS:
                clean.append(normalized)
            else:
                notes.append(
                    f"llm_secondary_promoted_to_sub_intent:{normalized}"
                )
                promoted.append(normalized)

        if deduped_primary:
            notes.append("llm_secondary_deduped_primary")
        if deduped_other:
            notes.append("llm_secondary_deduped")

        return clean, promoted

    @staticmethod
    def _coerce_sub_intents(raw: Any, notes: List[str]) -> List[str]:
        if not isinstance(raw, list):
            notes.append("llm_sub_intents_malformed")
            return []

        clean: List[str] = []
        seen: set[str] = set()
        filtered = False

        for entry in raw:
            if not isinstance(entry, str):
                filtered = True
                continue
            normalized = entry.lower().strip().replace(" ", "_").replace("-", "_")
            if not normalized:
                continue
            normalized = _SUB_INTENT_NORMALIZATION.get(normalized, normalized)
            if normalized in seen:
                continue
            seen.add(normalized)
            clean.append(normalized)

        if filtered:
            notes.append("llm_sub_intents_filtered")
        return clean

    @staticmethod
    def _coerce_requires_review(
        raw: Any,
        intent_topic: str,
        urgency: Urgency,
        notes: List[str],
    ) -> bool:
        if isinstance(raw, bool):
            return raw
        notes.append("llm_review_default")
        if intent_topic in {"complaint", "emergency"}:
            return True
        if urgency in {Urgency.HIGH, Urgency.EMERGENCY}:
            return True
        return False

    @staticmethod
    def _apply_heavy_coercion_review(
        classification: MessageClassification,
        notes: List[str],
    ) -> MessageClassification:
        for note in notes:
            if note.startswith(_HEAVY_COERCION_PREFIXES):
                if not classification.requires_human_review:
                    return classification.model_copy(
                        update={"requires_human_review": True},
                    )
                break
        return classification

    @staticmethod
    def _build_metadata(
        *,
        classifier_source: str,
        provider_used: Optional[str],
        fallback_stage: Optional[str],
        start: float,
        notes: List[str],
        input_tokens: Optional[int],
        output_tokens: Optional[int],
    ) -> ClassifierMetadata:
        return ClassifierMetadata(
            classifier_source=classifier_source,
            provider_used=provider_used,
            fallback_stage=fallback_stage,
            latency_ms=int((time.monotonic() - start) * 1000),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            coercion_notes=list(notes),
        )


class _MissingRequiredFieldError(Exception):
    """Raised when the LLM omits a required field."""

    def __init__(self, field: str, notes: List[str]) -> None:
        super().__init__(f"missing required field: {field}")
        self.field = field
        self.notes = notes


class _ProviderParseFailure(Exception):
    """Signal that one provider response should fail closed and allow fallback."""
