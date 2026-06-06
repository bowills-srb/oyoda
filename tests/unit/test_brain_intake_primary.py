from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.messaging_brain.orchestrator import GuestMessageBrainOrchestrator
from app.services.orchestration.messaging_brain_contracts import (
    ClassifierMetadata,
    InboundGuestMessage,
    IntentType,
    MessageClassification,
    Urgency,
)


def _message() -> InboundGuestMessage:
    return InboundGuestMessage(
        message_id="msg-123",
        tenant_id="11111111-1111-1111-1111-111111111111",
        channel="email",
        source_provider="gmail",
        text="Do you have a high chair and pack and play?",
        guest_name="Christina Moser",
        property_code="100SL2D",
    )


@pytest.mark.asyncio
async def test_brain_intake_primary_prefers_llm_before_deterministic() -> None:
    orch = GuestMessageBrainOrchestrator()
    orch._is_brain_intake_primary_enabled = AsyncMock(return_value=True)
    orch._intake_prefilter.classify_with_metadata = AsyncMock()
    orch._intake_llm_prefilter.classify_with_metadata = AsyncMock(
        return_value=(
            MessageClassification(
                intent_type=IntentType.QUESTION,
                intent_topic="booking_inquiry",
                sub_intents=["amenities"],
                confidence=0.88,
                urgency=Urgency.MEDIUM,
            ),
            ClassifierMetadata(
                classifier_source="llm",
                provider_used="groq",
                latency_ms=90,
            ),
        )
    )

    classification, metadata = await orch.classify_message(_message(), db_session=SimpleNamespace())

    assert classification.intent_topic == "booking_inquiry"
    assert metadata.classifier_source == "llm_primary"
    assert metadata.provider_used == "groq"
    assert metadata.deterministic_gate_decision == "bypassed_llm_primary"
    assert metadata.deterministic_handoff_reason is None
    orch._intake_prefilter.classify_with_metadata.assert_not_awaited()


@pytest.mark.asyncio
async def test_brain_intake_primary_uses_deterministic_only_after_llm_keyword_fallback() -> None:
    orch = GuestMessageBrainOrchestrator()
    orch._is_brain_intake_primary_enabled = AsyncMock(return_value=True)
    orch._intake_prefilter.classify_with_metadata = AsyncMock(
        return_value=(
            MessageClassification(
                intent_type=IntentType.QUESTION,
                intent_topic="local_recommendation",
                sub_intents=["local_area"],
                confidence=0.18,
                urgency=Urgency.LOW,
            ),
            ClassifierMetadata(
                classifier_source="deterministic",
                threshold=0.40,
                original_intent="local_area",
                original_confidence=0.18,
                contradictory_signals=True,
                legacy_intent="local_area",
            ),
        )
    )
    orch._intake_llm_prefilter.classify_with_metadata = AsyncMock(
        return_value=(
            MessageClassification(
                intent_type=IntentType.QUESTION,
                intent_topic="local_recommendation",
                sub_intents=["local_area"],
                confidence=0.18,
                urgency=Urgency.LOW,
            ),
            ClassifierMetadata(
                classifier_source="keyword_fallback",
                latency_ms=120,
                fallback_stage="keyword_after_llm_chain",
            ),
        )
    )

    classification, metadata = await orch.classify_message(_message(), db_session=SimpleNamespace())

    assert classification.intent_topic == "local_recommendation"
    assert metadata.classifier_source == "llm_failed_keyword_default"
    assert metadata.original_intent == "local_area"
    assert metadata.escalated_topic is None
    assert metadata.deterministic_gate_decision == "handoff_to_llm"
    assert metadata.deterministic_handoff_reason == "low_confidence+contradictory_signals"


@pytest.mark.asyncio
async def test_brain_intake_primary_records_missing_llm_handoff_boundary() -> None:
    orch = GuestMessageBrainOrchestrator()
    orch._is_brain_intake_primary_enabled = AsyncMock(return_value=True)
    orch._intake_prefilter.classify_with_metadata = AsyncMock(
        return_value=(
            MessageClassification(
                intent_type=IntentType.QUESTION,
                intent_topic="local_recommendation",
                sub_intents=["local_area"],
                confidence=0.18,
                urgency=Urgency.LOW,
            ),
            ClassifierMetadata(
                classifier_source="deterministic",
                threshold=0.40,
                original_intent="local_area",
                original_confidence=0.18,
                contradictory_signals=True,
                legacy_intent="local_area",
            ),
        )
    )
    orch._intake_llm_prefilter = None

    classification, metadata = await orch.classify_message(_message(), db_session=SimpleNamespace())

    assert classification.intent_topic == "local_recommendation"
    assert metadata.classifier_source == "deterministic"
    assert metadata.deterministic_gate_decision == "handoff_required_no_llm"
    assert metadata.deterministic_handoff_reason == "low_confidence+contradictory_signals"
