from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

from app.services.messaging_brain.agents.knowledge_gap_agent import (
    KnowledgeGapAgent,
    _find_tagged_concierge_knowledge,
)
from app.services.messaging_brain.knowledge.topic_registry import get_knowledge_topic
from app.services.orchestration.messaging_brain_contracts import (
    GuestContextBundle,
    IntentType,
    MessageClassification,
    MessagingLifecycle,
    Urgency,
)


def _make_classification(*, topic: str = "general") -> MessageClassification:
    return MessageClassification(
        intent_type=IntentType.QUESTION,
        intent_topic=topic,
        confidence=0.85,
        urgency=Urgency.LOW,
    )


def _make_context(**kwargs) -> GuestContextBundle:
    defaults: dict = {
        "tenant_id": str(uuid4()),
        "property_code": "PROP-TEST-001",
        "lifecycle": MessagingLifecycle.IN_STAY,
    }
    defaults.update(kwargs)
    return GuestContextBundle(**defaults)


def test_brain_gap_agent_uses_property_knowledge_to_resolve_topics(monkeypatch):
    """property_knowledge (concierge_knowledge) with a properly tagged FAQ
    resolves the corresponding topic — equivalent to the old property_data
    concierge_knowledge path."""
    async def _fake_classify(message: str, tenant_id=None):
        return SimpleNamespace(topic_ids=["beach_gear"])

    monkeypatch.setattr(
        "app.services.messaging_brain.agents.knowledge_gap_agent.classify_message_topics",
        _fake_classify,
    )

    context = _make_context(
        property_knowledge={
            "faq": [
                {
                    "question": "Does the home have beach gear?",
                    "answer": "The home includes four beach chairs and a rolling cooler.",
                    "topic": "beach_gear",
                }
            ]
        },
    )

    analysis = asyncio.run(
        KnowledgeGapAgent().analyze(
            message="Does the home come with beach chairs or a cooler?",
            classification=_make_classification(topic="amenities"),
            context=context,
        )
    )

    assert "beach_gear" not in analysis.missing_topic_ids


def test_brain_gap_agent_passes_tenant_id_to_topic_classifier(monkeypatch):
    """context.tenant_id is coerced to a UUID and forwarded to
    classify_message_topics as tenant_id."""
    captured: dict[str, object] = {}

    async def _fake_classify(message: str, tenant_id=None):
        captured["message"] = message
        captured["tenant_id"] = tenant_id
        return SimpleNamespace(topic_ids=[])

    monkeypatch.setattr(
        "app.services.messaging_brain.agents.knowledge_gap_agent.classify_message_topics",
        _fake_classify,
    )

    tenant_uuid = uuid4()
    context = _make_context(tenant_id=str(tenant_uuid))

    analysis = asyncio.run(
        KnowledgeGapAgent().analyze(
            message="Can we check in early?",
            classification=_make_classification(topic="early_check_in"),
            context=context,
        )
    )

    # Classifier returned no topics → fallback to intent_topic "early_check_in"
    # which expands to the "early_check_in" topic via expand_legacy_topics.
    # With an empty context (no operator_policies), it's a gap.
    assert "early_check_in" in analysis.missing_topic_ids
    assert captured == {
        "message": "Can we check in early?",
        "tenant_id": tenant_uuid,
    }


def test_brain_gap_agent_short_circuits_negative_pool_heat_closure(monkeypatch):
    """pool_heated=False in property_facts → negative-closure resolution for
    pool_heating_cost (no gap, no invented answer needed)."""
    async def _fake_classify(message: str, tenant_id=None):
        return SimpleNamespace(topic_ids=["pool_heating_cost"])

    monkeypatch.setattr(
        "app.services.messaging_brain.agents.knowledge_gap_agent.classify_message_topics",
        _fake_classify,
    )

    context = _make_context(
        property_facts={"has_pool": True, "pool_heated": False},
    )

    analysis = asyncio.run(
        KnowledgeGapAgent().analyze(
            message="How much does pool heating cost?",
            classification=_make_classification(topic="general"),
            context=context,
        )
    )

    assert "pool_heating_cost" not in analysis.missing_topic_ids


def test_brain_gap_agent_uses_tagged_concierge_faq_answer(monkeypatch):
    """A tagged FAQ entry in property_knowledge resolves the corresponding topic
    even when operator_policies alone wouldn't be enough."""
    async def _fake_classify(message: str, tenant_id=None):
        return SimpleNamespace(topic_ids=["pet_fee"])

    monkeypatch.setattr(
        "app.services.messaging_brain.agents.knowledge_gap_agent.classify_message_topics",
        _fake_classify,
    )

    context = _make_context(
        property_knowledge={
            "faq": [
                {
                    "question": "What is the pet fee?",
                    "answer": "$75 per stay.",
                    "topic": "pet_fee",
                }
            ]
        },
        operator_policies={"pet_policy": "allowed"},
    )

    analysis = asyncio.run(
        KnowledgeGapAgent().analyze(
            message="How much is the pet fee?",
            classification=_make_classification(topic="general"),
            context=context,
        )
    )

    assert "pet_fee" not in analysis.missing_topic_ids


def test_find_tagged_concierge_knowledge_rejects_freeform_faq_without_topic_or_tags():
    topic = get_knowledge_topic("pet_fee")

    assert topic is not None
    assert not _find_tagged_concierge_knowledge(
        topic=topic,
        property_data={
            "concierge_knowledge": {
                "faq": [
                    {
                        "question": "Are pets allowed?",
                        "answer": "Yes, with approval.",
                    }
                ]
            }
        },
    )


def test_brain_gap_agent_matches_documented_production_gap_shape_inq_3007c78e(monkeypatch):
    """
    Production note: docs/SESSION_14_DIAGNOSTIC_FOLLOWUP_2026_05_03.md records
    INQ-3007C78E carrying legacy warning
    `missing_property_knowledge:beach_access,local_area`.

    This fixture preserves that documented Beach Habitats gap shape in the
    Brain-side regression suite. The load-bearing parity check here is that
    the beach-access knowledge gap remains surfaced as a hold-worthy missing
    topic through the Brain bridge.
    """
    async def _fake_classify(message: str, tenant_id=None):
        return SimpleNamespace(topic_ids=["beach_access", "local_area"])

    monkeypatch.setattr(
        "app.services.messaging_brain.agents.knowledge_gap_agent.classify_message_topics",
        _fake_classify,
    )

    context = _make_context(
        property_knowledge={"faq": []},
    )

    analysis = asyncio.run(
        KnowledgeGapAgent().analyze(
            message="How close is the beach access, and what part of the area is this home in?",
            classification=_make_classification(topic="general"),
            context=context,
        )
    )

    assert "beach_access" in analysis.missing_topic_ids
