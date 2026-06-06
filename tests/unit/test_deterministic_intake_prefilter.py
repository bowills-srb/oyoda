from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from unittest.mock import AsyncMock

from app.services.messaging_brain.agents.deterministic_intake_prefilter import (
    DeterministicIntakePreFilter,
    legacy_intent_from_classification,
)
from app.services.orchestration.messaging_brain_contracts import (
    InboundGuestMessage,
    IntentType,
    MessageClassification,
    Urgency,
)


def _message(text: str) -> InboundGuestMessage:
    return InboundGuestMessage(
        message_id="msg-1",
        tenant_id=str(uuid4()),
        channel="email",
        source_provider="gmail",
        text=text,
        guest_name="Christina Moser",
        property_code="100SL2D",
    )


@pytest.mark.asyncio
async def test_christina_message_resolves_deterministically_to_amenities() -> None:
    agent = DeterministicIntakePreFilter()

    classification, metadata = await agent.classify_with_metadata(
        _message(
            "Hello- can you confirm if the unit has the following? "
            "High chair Pack and play Baby gate Beach toys Beach chairs"
        ),
        db_session=None,
    )

    assert classification.intent_type == IntentType.QUESTION
    assert classification.intent_topic == "booking_inquiry"
    assert "amenities" in classification.sub_intents
    assert classification.confidence >= 0.40
    assert metadata.classifier_source == "deterministic"
    assert metadata.original_intent == "amenities"
    assert metadata.legacy_intent == "amenities"
    assert "high chair" in metadata.matched_terms
    assert "pack and play" in metadata.matched_terms
    assert metadata.matched_override_keywords == []
    assert metadata.resolved_via_override is False


@pytest.mark.asyncio
async def test_prefilter_merges_operator_keyword_overrides() -> None:
    agent = DeterministicIntakePreFilter()
    tenant_id = uuid4()

    class _FetchOne:
        def fetchone(self):
            return ({"intent_classifier_keyword_overrides": {"amenities": ["crib"]}},)

    db = SimpleNamespace(execute=AsyncMock(return_value=_FetchOne()))

    details = await agent.classify_with_details(
        "Do you have a crib for the baby?",
        tenant_id=tenant_id,
        db_session=db,
    )

    assert details["intent"] == "amenities"
    assert details["confidence"] >= 0.40
    assert details["matched_override_keywords"] == ["crib"]
    assert "crib" in details["matched_terms"]


def test_legacy_intent_adapter_maps_brain_topics_back_to_prebooking_intents() -> None:
    classification = MessageClassification(
        intent_type=IntentType.QUESTION,
        intent_topic="booking_inquiry",
        sub_intents=["pricing", "discount"],
        confidence=0.82,
        urgency=Urgency.MEDIUM,
    )

    assert legacy_intent_from_classification(classification, message_text="Any discount?") == "pricing"
