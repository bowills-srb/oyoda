from __future__ import annotations

from uuid import uuid4

import pytest

from app.services.messaging_brain.intake.intent_escalator import (
    classify_with_escalation,
)


@pytest.mark.asyncio
async def test_classify_with_escalation_skips_llm_for_high_confidence(monkeypatch):
    calls: list[str] = []

    async def _fake_run_llm_escalation(**kwargs):
        calls.append("llm")
        return None

    monkeypatch.setattr(
        "app.services.messaging_brain.intake.intent_escalator._run_llm_escalation",
        _fake_run_llm_escalation,
    )

    intent, confidence, metadata = await classify_with_escalation(
        message="Is the pool heated and is there wifi?",
        conversation_context="",
        tenant_id=uuid4(),
        keyword_result={
            "intent": "amenities",
            "confidence": 0.82,
            "competing_intents": [],
            "contradictory_signals": False,
        },
        threshold=0.40,
    )

    assert intent == "amenities"
    assert confidence == 0.82
    assert metadata.classifier_source == "keyword"
    assert calls == []


@pytest.mark.asyncio
async def test_classify_with_escalation_uses_llm_result(monkeypatch):
    async def _fake_run_llm_escalation(**kwargs):
        return {
            "provider": "anthropic",
            "intent": "amenities",
            "confidence": 0.88,
            "reason": "Baby gear and beach gear are amenities.",
        }

    monkeypatch.setattr(
        "app.services.messaging_brain.intake.intent_escalator._run_llm_escalation",
        _fake_run_llm_escalation,
    )

    intent, confidence, metadata = await classify_with_escalation(
        message="Do you have a high chair, pack and play, beach toys, and beach chairs?",
        conversation_context="",
        tenant_id=uuid4(),
        keyword_result={
            "intent": "local_area",
            "confidence": 0.22,
            "competing_intents": ["amenities"],
            "contradictory_signals": True,
        },
        threshold=0.40,
    )

    assert intent == "amenities"
    assert confidence == 0.88
    assert metadata.classifier_source == "llm_escalated_anthropic"
    assert metadata.escalated is True
    assert metadata.escalated_topic == "amenities"


@pytest.mark.asyncio
async def test_classify_with_escalation_falls_back_when_llm_fails(monkeypatch):
    async def _fake_run_llm_escalation(**kwargs):
        return None

    monkeypatch.setattr(
        "app.services.messaging_brain.intake.intent_escalator._run_llm_escalation",
        _fake_run_llm_escalation,
    )

    intent, confidence, metadata = await classify_with_escalation(
        message="Can we arrive early and also what is nearby for dinner?",
        conversation_context="",
        tenant_id=uuid4(),
        keyword_result={
            "intent": "check_in_process",
            "confidence": 0.25,
            "competing_intents": ["local_area"],
            "contradictory_signals": True,
        },
        threshold=0.40,
    )

    assert intent == "check_in_process"
    assert confidence == 0.25
    assert metadata.classifier_source == "llm_failed_keyword_default"
    assert metadata.escalated is True
