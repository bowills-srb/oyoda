"""
test_llm_intake_agent.py — LLMIntakeAgent verification gates.

Unit tests for LLMIntakeAgent. Covers:

  * Provider chain: Groq primary, Anthropic fallback, keyword ultimate fallback
  * Every coercion rule (invalid topic, urgency, confidence, secondary topics, etc.)
  * Concurrency safety (no shared per-call state)
  * Heavy-coercion → forced requires_human_review
  * Light sub_intent normalization

Provider ordering: Groq is PRIMARY (cost/speed), Anthropic is SECONDARY (quality
fallback). Stage labels: "groq_primary" when Groq succeeds; "anthropic_after_groq_failed"
when Groq fails and Anthropic recovers; None when no Groq key (Anthropic runs as sole
provider).

Live LLM tests are gated behind RUN_LIVE_LLM_TESTS=1 env var and live in
test_llm_intake_agent_smoke.py.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest

from app.services.messaging_brain.agents.intake_agent import IntakeAgent
from app.services.messaging_brain.agents.llm_intake_agent import (
    LLMIntakeAgent,
    _BOOKING_INQUIRY_SUB_INTENTS,
    _LATE_CHECKOUT_SUB_INTENTS,
)
from app.services.observability.llm_usage_tracker import LLMUsageTracker
from app.services.orchestration.messaging_brain_contracts import (
    InboundGuestMessage,
    IntentType,
    MessageClassification,
    Urgency,
)


def _make_inbound(
    text: str = "Is the property available next weekend?",
    *,
    message_id: str = "MSG_LLM_INTAKE_TEST",
    tenant_id: str = "11111111-1111-1111-1111-111111111111",
    property_code: str = "GULF_VIEW_204",
) -> InboundGuestMessage:
    return InboundGuestMessage(
        message_id=message_id,
        tenant_id=tenant_id,
        channel="email",
        source_provider="ota_parser_vrbo",
        text=text,
        property_code=property_code,
    )


def _good_response(
    *,
    intent_type: str = "question",
    intent_topic: str = "booking_inquiry",
    secondary_topics: Optional[list] = None,
    sub_intents: Optional[list] = None,
    confidence: float = 0.85,
    urgency: str = "medium",
    requires_human_review: bool = False,
    reason: str = "Test classification",
    extracted_constraints: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "intent_type": intent_type,
        "intent_topic": intent_topic,
        "secondary_topics": secondary_topics if secondary_topics is not None else [],
        "sub_intents": sub_intents if sub_intents is not None else [],
        "confidence": confidence,
        "urgency": urgency,
        "requires_human_review": requires_human_review,
        "reason": reason,
        "extracted_constraints": extracted_constraints if extracted_constraints is not None else {},
    }


def _llm_response_envelope(
    payload: Dict[str, Any],
    *,
    input_tokens: int = 200,
    output_tokens: int = 100,
) -> Dict[str, Any]:
    return {
        "text": json.dumps(payload),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }


@pytest.mark.asyncio
async def test_groq_succeeds_returns_classification_and_metadata():
    """Groq is primary — when it succeeds on the first try the result is labelled
    groq_primary and token counts flow through to metadata."""
    agent = LLMIntakeAgent(anthropic_key="test-anth", groq_key="test-groq")
    payload = _good_response(intent_topic="booking_inquiry", confidence=0.92)

    with patch.object(
        agent,
        "_call_groq",
        new=AsyncMock(return_value=_llm_response_envelope(payload)),
    ), patch.object(LLMUsageTracker, "record", new=AsyncMock()) as tracker:
        classification, metadata = await agent.classify_with_metadata(_make_inbound())

    assert classification.intent_topic == "booking_inquiry"
    assert classification.confidence == pytest.approx(0.92)
    assert metadata.classifier_source == "llm"
    assert metadata.provider_used == "groq"
    assert metadata.fallback_stage == "groq_primary"
    assert metadata.input_tokens == 200
    assert metadata.output_tokens == 100
    tracker.assert_awaited_once()
    assert tracker.await_args.kwargs["service_name"] == "brain_intake_classifier"
    assert tracker.await_args.kwargs["request_type"] == "brain_intake_classification"
    assert tracker.await_args.kwargs["tenant_id"] == UUID("11111111-1111-1111-1111-111111111111")


@pytest.mark.asyncio
async def test_anthropic_used_when_groq_key_absent():
    """When no Groq key is configured Anthropic runs as the sole provider.
    fallback_stage is None (no groq_key means the 'after_groq_failed' label
    does not apply even though Anthropic is the secondary provider)."""
    agent = LLMIntakeAgent(anthropic_key="test-anth", groq_key="")
    payload = _good_response(intent_topic="access", confidence=0.88)

    with patch.object(
        agent,
        "_call_anthropic",
        new=AsyncMock(return_value=_llm_response_envelope(payload)),
    ):
        classification, metadata = await agent.classify_with_metadata(_make_inbound())

    assert classification.intent_topic == "access"
    assert metadata.classifier_source == "llm"
    assert metadata.provider_used == "anthropic"
    assert metadata.fallback_stage is None


@pytest.mark.asyncio
async def test_anthropic_used_when_groq_fails():
    """Groq is primary — when it raises, Anthropic is the fallback.
    fallback_stage="anthropic_after_groq_failed"; the Groq exception is
    captured in coercion_notes."""
    agent = LLMIntakeAgent(anthropic_key="test-anth", groq_key="test-groq")
    payload = _good_response()

    with patch.object(
        agent,
        "_call_groq",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ), patch.object(
        agent,
        "_call_anthropic",
        new=AsyncMock(return_value=_llm_response_envelope(payload)),
    ):
        classification, metadata = await agent.classify_with_metadata(_make_inbound())

    assert metadata.provider_used == "anthropic"
    assert metadata.fallback_stage == "anthropic_after_groq_failed"
    assert any(n.startswith("llm_exception:groq:") for n in metadata.coercion_notes)


@pytest.mark.asyncio
async def test_groq_timeout_falls_through_to_anthropic():
    """Groq is primary — when it times out, Anthropic is the fallback.
    The timeout is recorded in coercion_notes as llm_timeout:groq."""
    agent = LLMIntakeAgent(
        anthropic_key="test-anth",
        groq_key="test-groq",
        per_provider_timeout_seconds=0.05,
    )
    payload = _good_response()

    async def slow_groq(_msg):
        await asyncio.sleep(1.0)
        return _llm_response_envelope(payload)

    with patch.object(agent, "_call_groq", new=slow_groq), patch.object(
        agent,
        "_call_anthropic",
        new=AsyncMock(return_value=_llm_response_envelope(payload)),
    ):
        classification, metadata = await agent.classify_with_metadata(_make_inbound())

    assert metadata.provider_used == "anthropic"
    assert "llm_timeout:groq" in metadata.coercion_notes


@pytest.mark.asyncio
async def test_no_keys_falls_through_to_keyword():
    agent = LLMIntakeAgent(anthropic_key="", groq_key="")

    classification, metadata = await agent.classify_with_metadata(_make_inbound())

    assert metadata.classifier_source == "keyword_fallback"
    assert metadata.provider_used is None
    assert metadata.fallback_stage == "keyword_after_llm_chain"
    assert "llm_no_keys_configured" in metadata.coercion_notes


@pytest.mark.asyncio
async def test_both_providers_fail_falls_through_to_keyword():
    agent = LLMIntakeAgent(anthropic_key="test-anth", groq_key="test-groq")

    with patch.object(
        agent,
        "_call_anthropic",
        new=AsyncMock(side_effect=RuntimeError("anth boom")),
    ), patch.object(
        agent,
        "_call_groq",
        new=AsyncMock(side_effect=RuntimeError("groq boom")),
    ):
        classification, metadata = await agent.classify_with_metadata(_make_inbound())

    assert metadata.classifier_source == "keyword_fallback"
    assert "llm_all_providers_failed" in metadata.coercion_notes
    assert any(n.startswith("llm_exception:anthropic:") for n in metadata.coercion_notes)
    assert any(n.startswith("llm_exception:groq:") for n in metadata.coercion_notes)


@pytest.mark.asyncio
async def test_invalid_json_falls_through_to_next_provider():
    """Groq (primary) returns non-JSON text → parse failure → Anthropic
    (fallback) succeeds. The parse failure is recorded as llm_invalid_json:groq."""
    agent = LLMIntakeAgent(anthropic_key="test-anth", groq_key="test-groq")
    bad = {"text": "this is not json at all", "input_tokens": 10, "output_tokens": 5}
    payload = _good_response()

    with patch.object(
        agent,
        "_call_groq",
        new=AsyncMock(return_value=bad),
    ), patch.object(
        agent,
        "_call_anthropic",
        new=AsyncMock(return_value=_llm_response_envelope(payload)),
    ):
        classification, metadata = await agent.classify_with_metadata(_make_inbound())

    assert metadata.provider_used == "anthropic"
    assert "llm_invalid_json:groq" in metadata.coercion_notes


@pytest.mark.asyncio
async def test_missing_required_field_falls_through_to_next_provider():
    """Groq (primary) returns valid JSON but omits a required field →
    _MissingRequiredFieldError → Anthropic (fallback) succeeds.
    The missing-field note is recorded regardless of which provider emitted it."""
    agent = LLMIntakeAgent(anthropic_key="test-anth", groq_key="test-groq")
    bad_payload = {
        "intent_type": "question",
        "confidence": 0.8,
        "urgency": "medium",
    }
    good_payload = _good_response()

    with patch.object(
        agent,
        "_call_groq",
        new=AsyncMock(return_value=_llm_response_envelope(bad_payload)),
    ), patch.object(
        agent,
        "_call_anthropic",
        new=AsyncMock(return_value=_llm_response_envelope(good_payload)),
    ):
        classification, metadata = await agent.classify_with_metadata(_make_inbound())

    assert metadata.provider_used == "anthropic"
    assert "llm_missing_required:intent_topic" in metadata.coercion_notes


@pytest.mark.asyncio
async def test_invalid_topic_coerces_to_general_with_review():
    agent = LLMIntakeAgent(anthropic_key="test-anth")
    payload = _good_response(intent_topic="not_a_real_topic")

    with patch.object(
        agent,
        "_call_anthropic",
        new=AsyncMock(return_value=_llm_response_envelope(payload)),
    ):
        classification, metadata = await agent.classify_with_metadata(_make_inbound())

    assert classification.intent_topic == "general"
    assert classification.requires_human_review is True
    assert any(n.startswith("llm_topic_coerced:not_a_real_topic") for n in metadata.coercion_notes)


@pytest.mark.asyncio
@pytest.mark.parametrize("raw_topic", sorted(_BOOKING_INQUIRY_SUB_INTENTS))
async def test_sub_intent_topic_coerces_to_booking_inquiry(raw_topic):
    agent = LLMIntakeAgent(anthropic_key="test-anth")
    payload = _good_response(intent_topic=raw_topic)

    with patch.object(
        agent,
        "_call_anthropic",
        new=AsyncMock(return_value=_llm_response_envelope(payload)),
    ):
        classification, _metadata = await agent.classify_with_metadata(_make_inbound())

    assert classification.intent_topic == "booking_inquiry"
    assert raw_topic in classification.sub_intents


@pytest.mark.asyncio
@pytest.mark.parametrize("raw_topic", sorted(_LATE_CHECKOUT_SUB_INTENTS))
async def test_late_checkout_sub_intent_coerces_to_late_checkout(raw_topic):
    agent = LLMIntakeAgent(anthropic_key="test-anth")
    payload = _good_response(intent_topic=raw_topic)

    with patch.object(
        agent,
        "_call_anthropic",
        new=AsyncMock(return_value=_llm_response_envelope(payload)),
    ):
        classification, _metadata = await agent.classify_with_metadata(_make_inbound())

    assert classification.intent_topic == "late_checkout"


@pytest.mark.asyncio
async def test_system_topic_coerces_to_general():
    agent = LLMIntakeAgent(anthropic_key="test-anth")
    payload = _good_response(intent_topic="system_welcome")

    with patch.object(
        agent,
        "_call_anthropic",
        new=AsyncMock(return_value=_llm_response_envelope(payload)),
    ):
        classification, _metadata = await agent.classify_with_metadata(_make_inbound())

    assert classification.intent_topic == "general"


@pytest.mark.asyncio
async def test_invalid_intent_type_coerces_to_question():
    agent = LLMIntakeAgent(anthropic_key="test-anth")
    payload = _good_response(intent_type="random_nonsense")

    with patch.object(
        agent,
        "_call_anthropic",
        new=AsyncMock(return_value=_llm_response_envelope(payload)),
    ):
        classification, metadata = await agent.classify_with_metadata(_make_inbound())

    assert classification.intent_type == IntentType.QUESTION
    assert any(n.startswith("llm_intent_type_coerced:random_nonsense") for n in metadata.coercion_notes)


@pytest.mark.asyncio
async def test_intent_type_alias_action_maps_to_request():
    agent = LLMIntakeAgent(anthropic_key="test-anth")
    payload = _good_response(intent_type="action")

    with patch.object(
        agent,
        "_call_anthropic",
        new=AsyncMock(return_value=_llm_response_envelope(payload)),
    ):
        classification, _metadata = await agent.classify_with_metadata(_make_inbound())

    assert classification.intent_type == IntentType.REQUEST


@pytest.mark.asyncio
async def test_invalid_urgency_coerces_to_medium():
    agent = LLMIntakeAgent(anthropic_key="test-anth")
    payload = _good_response(urgency="moderate")

    with patch.object(
        agent,
        "_call_anthropic",
        new=AsyncMock(return_value=_llm_response_envelope(payload)),
    ):
        classification, _metadata = await agent.classify_with_metadata(_make_inbound())

    assert classification.urgency == Urgency.MEDIUM


@pytest.mark.asyncio
async def test_critical_urgency_coerces_to_emergency():
    agent = LLMIntakeAgent(anthropic_key="test-anth")
    payload = _good_response(urgency="critical")

    with patch.object(
        agent,
        "_call_anthropic",
        new=AsyncMock(return_value=_llm_response_envelope(payload)),
    ):
        classification, _metadata = await agent.classify_with_metadata(_make_inbound())

    assert classification.urgency == Urgency.EMERGENCY


@pytest.mark.asyncio
async def test_confidence_clamped_when_out_of_range():
    agent = LLMIntakeAgent(anthropic_key="test-anth")
    payload = _good_response(confidence=1.5)

    with patch.object(
        agent,
        "_call_anthropic",
        new=AsyncMock(return_value=_llm_response_envelope(payload)),
    ):
        classification, metadata = await agent.classify_with_metadata(_make_inbound())

    assert classification.confidence == 1.0
    assert any(n.startswith("llm_confidence_clamped") for n in metadata.coercion_notes)


@pytest.mark.asyncio
async def test_confidence_default_when_non_numeric():
    agent = LLMIntakeAgent(anthropic_key="test-anth")
    payload = _good_response()
    payload["confidence"] = "very high"

    with patch.object(
        agent,
        "_call_anthropic",
        new=AsyncMock(return_value=_llm_response_envelope(payload)),
    ):
        classification, metadata = await agent.classify_with_metadata(_make_inbound())

    assert classification.confidence == 0.50
    assert "llm_confidence_default" in metadata.coercion_notes


@pytest.mark.asyncio
async def test_invalid_secondary_topic_promoted_to_sub_intents():
    agent = LLMIntakeAgent(anthropic_key="test-anth")
    payload = _good_response(
        intent_topic="booking_inquiry",
        secondary_topics=["pricing", "complaint"],
    )

    with patch.object(
        agent,
        "_call_anthropic",
        new=AsyncMock(return_value=_llm_response_envelope(payload)),
    ):
        classification, metadata = await agent.classify_with_metadata(_make_inbound())

    assert classification.secondary_topics == ["complaint"]
    assert "pricing" in classification.sub_intents
    assert "llm_secondary_promoted_to_sub_intent:pricing" in metadata.coercion_notes


@pytest.mark.asyncio
async def test_secondary_topic_matching_primary_is_deduped():
    agent = LLMIntakeAgent(anthropic_key="test-anth")
    payload = _good_response(
        intent_topic="booking_inquiry",
        secondary_topics=["booking_inquiry", "complaint"],
    )

    with patch.object(
        agent,
        "_call_anthropic",
        new=AsyncMock(return_value=_llm_response_envelope(payload)),
    ):
        classification, metadata = await agent.classify_with_metadata(_make_inbound())

    assert classification.secondary_topics == ["complaint"]
    assert "llm_secondary_deduped_primary" in metadata.coercion_notes


@pytest.mark.asyncio
async def test_secondary_topics_dedupes_duplicates():
    agent = LLMIntakeAgent(anthropic_key="test-anth")
    payload = _good_response(
        intent_topic="booking_inquiry",
        secondary_topics=["complaint", "complaint", "maintenance"],
    )

    with patch.object(
        agent,
        "_call_anthropic",
        new=AsyncMock(return_value=_llm_response_envelope(payload)),
    ):
        classification, metadata = await agent.classify_with_metadata(_make_inbound())

    assert classification.secondary_topics == ["complaint", "maintenance"]
    assert "llm_secondary_deduped" in metadata.coercion_notes


@pytest.mark.asyncio
async def test_sub_intent_normalization_discount_request():
    agent = LLMIntakeAgent(anthropic_key="test-anth")
    payload = _good_response(sub_intents=["discount_request"])

    with patch.object(
        agent,
        "_call_anthropic",
        new=AsyncMock(return_value=_llm_response_envelope(payload)),
    ):
        classification, _metadata = await agent.classify_with_metadata(_make_inbound())

    assert "discount" in classification.sub_intents
    assert "discount_request" not in classification.sub_intents


@pytest.mark.asyncio
async def test_sub_intent_normalization_snow_chains():
    agent = LLMIntakeAgent(anthropic_key="test-anth")
    payload = _good_response(sub_intents=["snow_chains"])

    with patch.object(
        agent,
        "_call_anthropic",
        new=AsyncMock(return_value=_llm_response_envelope(payload)),
    ):
        classification, _metadata = await agent.classify_with_metadata(_make_inbound())

    assert "road_access" in classification.sub_intents


@pytest.mark.asyncio
async def test_sub_intent_unknown_open_vocab_preserved():
    agent = LLMIntakeAgent(anthropic_key="test-anth")
    payload = _good_response(sub_intents=["altitude_concern", "boat_access"])

    with patch.object(
        agent,
        "_call_anthropic",
        new=AsyncMock(return_value=_llm_response_envelope(payload)),
    ):
        classification, _metadata = await agent.classify_with_metadata(_make_inbound())

    assert "altitude_concern" in classification.sub_intents
    assert "boat_access" in classification.sub_intents


@pytest.mark.asyncio
async def test_malformed_extracted_constraints_forces_review():
    agent = LLMIntakeAgent(anthropic_key="test-anth")
    payload = _good_response(extracted_constraints={})
    payload["extracted_constraints"] = "not a dict"

    with patch.object(
        agent,
        "_call_anthropic",
        new=AsyncMock(return_value=_llm_response_envelope(payload)),
    ):
        classification, metadata = await agent.classify_with_metadata(_make_inbound())

    assert classification.extracted_constraints == {}
    assert classification.requires_human_review is True
    assert "llm_constraints_malformed" in metadata.coercion_notes


@pytest.mark.asyncio
async def test_missing_review_flag_defaults_true_for_complaint():
    agent = LLMIntakeAgent(anthropic_key="test-anth")
    payload = _good_response(intent_topic="complaint")
    payload.pop("requires_human_review")

    with patch.object(
        agent,
        "_call_anthropic",
        new=AsyncMock(return_value=_llm_response_envelope(payload)),
    ):
        classification, _metadata = await agent.classify_with_metadata(_make_inbound())

    assert classification.requires_human_review is True


@pytest.mark.asyncio
async def test_missing_review_flag_defaults_false_for_booking_inquiry():
    agent = LLMIntakeAgent(anthropic_key="test-anth")
    payload = _good_response(intent_topic="booking_inquiry", urgency="medium")
    payload.pop("requires_human_review")

    with patch.object(
        agent,
        "_call_anthropic",
        new=AsyncMock(return_value=_llm_response_envelope(payload)),
    ):
        classification, _metadata = await agent.classify_with_metadata(_make_inbound())

    assert classification.requires_human_review is False


@pytest.mark.asyncio
async def test_concurrent_classify_calls_do_not_share_metadata():
    agent = LLMIntakeAgent(anthropic_key="test-anth", groq_key="")

    msg_a = _make_inbound("Question A about availability", message_id="MSG_A")
    msg_b = _make_inbound("Question B about pricing", message_id="MSG_B")

    payload_a = _good_response(intent_topic="booking_inquiry", reason="A reason", confidence=0.81)
    payload_b = _good_response(intent_topic="booking_inquiry", reason="B reason", confidence=0.82)

    async def per_message_response(message: InboundGuestMessage):
        await asyncio.sleep(0.05)
        if message.message_id == "MSG_A":
            return _llm_response_envelope(payload_a, input_tokens=100, output_tokens=50)
        return _llm_response_envelope(payload_b, input_tokens=200, output_tokens=80)

    with patch.object(agent, "_call_anthropic", new=per_message_response):
        results = await asyncio.gather(
            agent.classify_with_metadata(msg_a),
            agent.classify_with_metadata(msg_b),
        )

    (cls_a, meta_a), (cls_b, meta_b) = results
    assert cls_a.reason == "A reason"
    assert cls_b.reason == "B reason"
    assert cls_a.confidence == pytest.approx(0.81)
    assert cls_b.confidence == pytest.approx(0.82)
    assert meta_a.input_tokens == 100
    assert meta_b.input_tokens == 200
    assert meta_a is not meta_b


@pytest.mark.asyncio
async def test_heavy_coercion_forces_review_even_when_model_said_false():
    agent = LLMIntakeAgent(anthropic_key="test-anth")
    payload = _good_response(
        intent_topic="completely_made_up",
        requires_human_review=False,
    )

    with patch.object(
        agent,
        "_call_anthropic",
        new=AsyncMock(return_value=_llm_response_envelope(payload)),
    ):
        classification, _metadata = await agent.classify_with_metadata(_make_inbound())

    assert classification.requires_human_review is True


@pytest.mark.asyncio
async def test_markdown_fenced_json_is_parsed():
    agent = LLMIntakeAgent(anthropic_key="test-anth")
    payload = _good_response(intent_topic="access")
    fenced_text = f"```json\n{json.dumps(payload)}\n```"

    with patch.object(
        agent,
        "_call_anthropic",
        new=AsyncMock(return_value={
            "text": fenced_text,
            "input_tokens": 50,
            "output_tokens": 30,
        }),
    ):
        classification, metadata = await agent.classify_with_metadata(_make_inbound())

    assert classification.intent_topic == "access"
    assert metadata.classifier_source == "llm"


@pytest.mark.asyncio
async def test_classify_returns_only_classification():
    agent = LLMIntakeAgent(anthropic_key="test-anth")
    payload = _good_response()

    with patch.object(
        agent,
        "_call_anthropic",
        new=AsyncMock(return_value=_llm_response_envelope(payload)),
    ):
        result = await agent.classify(_make_inbound())

    assert isinstance(result, MessageClassification)


def test_agent_name_matches_keyword_agent():
    llm = LLMIntakeAgent(anthropic_key="x", groq_key="y")
    kw = IntakeAgent()
    assert llm.name == kw.name == "IntakeAgent"
