"""
test_llm_composer_agent_smoke.py — live-API smoke tests for LLMComposerAgent.

Covers Session 12 / Phase C2 of docs/IMPLEMENTATION_QUEUE_2026_05_05.md.
See docs/SESSION_12_COMPOSER_DESIGN.md for the full design.

Gating:

  * Master flag: RUN_LIVE_LLM_TESTS=1 in the environment. When unset
    (the default in CI and on most laptops), every test in this file
    is skipped.

    The env-var name matches tests/unit/test_llm_intake_agent_smoke.py
    so a single flip turns on live LLM tests across the whole brain.

  * Per-provider key gates: each test additionally requires the matching
    API key. Anthropic uses ANTHROPIC_API_KEY, Groq uses GROQ_API_KEY,
    Gemini uses GEMINI_API_KEY or GOOGLE_API_KEY (composer accepts
    either).

  * Default state: skipped. Live runs are for development / pre-rollout
    validation, not CI.

Cases:

  1. Anthropic with a Beach-Habitats-shaped pre-booking inquiry returns
     a draft that is non-empty, under 700 chars, and contains the
     property name.

  2. Same for Groq.

  3. Same for Gemini, additionally guarded by key presence (smoke
     skips cleanly when no Google key is configured).

  4. Operator-guidance precedence: with operator_guidance="no pets
     allowed at this property" and a specialist draft suggesting pets
     are welcome, the Anthropic-backed composer's output declines pets
     rather than echoing the specialist's permissive language. This is
     the load-bearing behavioral check for B1 → composer plumbing.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import pytest

from app.services.messaging_brain.agents.llm_composer_agent import (
    LLMComposerAgent,
)
from app.services.orchestration.messaging_brain_contracts import (
    AgentDecision,
    GuestContextBundle,
    InboundGuestMessage,
    MessagingLifecycle,
    RecommendedAction,
)


# ─────────────────────────────────────────────────────────────────────────────
# Gating
# ─────────────────────────────────────────────────────────────────────────────


_RUN_LIVE = os.getenv("RUN_LIVE_LLM_TESTS") == "1"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


_TENANT = "11111111-1111-1111-1111-111111111111"
_PROPERTY_CODE = "BEACH_HABITATS_30A_GULFVIEW"
_PROPERTY_NAME = "Beach Habitats Gulf View"


def _beach_habitats_inbound(text: str) -> InboundGuestMessage:
    return InboundGuestMessage(
        message_id=f"SMOKE_{datetime.utcnow().isoformat()}",
        tenant_id=_TENANT,
        channel="email",
        source_provider="gmail",
        text=text,
        guest_name="Smoke Tester",
        guest_email="smoke@example.com",
        property_code=_PROPERTY_CODE,
        received_at=datetime.utcnow(),
        metadata={},
    )


def _beach_habitats_context(
    *,
    operator_guidance: str = "",
    learned_preferences: str = "",
) -> GuestContextBundle:
    return GuestContextBundle(
        tenant_id=_TENANT,
        property_code=_PROPERTY_CODE,
        property_id=None,
        guest_id=None,
        lifecycle=MessagingLifecycle.PRE_BOOKING,
        property_facts={
            "property_name": _PROPERTY_NAME,
            "bedrooms": 4,
            "bathrooms": 3,
            "sleeps": 10,
            "location": "30A, Florida",
            "distance_to_beach_steps": 75,
        },
        property_knowledge={
            "checkin_time": "4:00 PM",
            "checkout_time": "10:00 AM",
        },
        reservation_facts={},
        house_rules={
            "max_occupancy": 10,
            "events_allowed": False,
        },
        access_info={},
        operator_guidance=operator_guidance,
        learned_preferences_block=learned_preferences,
        evidence_keys=[
            "property_facts",
            "property_knowledge",
            "house_rules",
        ],
        missing_context=[],
    )


def _hold_decision(
    draft_text: str = (
        "Thanks for the message — let me confirm a couple of details "
        "with the property owner and follow up shortly."
    ),
    intent_topic: str = "booking_inquiry",
) -> AgentDecision:
    return AgentDecision(
        agent_name="BookingInquiryAgent",
        intent_topic=intent_topic,
        confidence=0.65,
        answer_summary="hold for owner confirmation",
        evidence_used=["property_facts"],
        missing_info=["specific_pricing_for_dates"],
        risk_flags=[],
        recommended_action=RecommendedAction.DRAFT_ONLY,
        draft_text=draft_text,
        module_events=[],
    )


def _assert_smoke_output_shape(text: str) -> None:
    """Common shape assertions for any successful LLM response.

    Smoke tests assert shape, not exact content — content varies across
    providers and runs. Shape is what we care about: the validator
    accepted it, the cap held, the property name made it through.
    """
    assert text, "composer_response_text is empty"
    assert len(text) <= 700, f"composer output exceeded cap: {len(text)} chars"
    # Property name should appear since it's in the facts block. This
    # is an indirect check that the composer is grounding in context.
    assert _PROPERTY_NAME.lower() in text.lower(), (
        f"property name {_PROPERTY_NAME!r} not in composer output: {text!r}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.skipif(not _RUN_LIVE, reason="RUN_LIVE_LLM_TESTS=1 required")
async def test_smoke_anthropic_returns_grounded_draft():
    if not os.getenv("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set")

    # Anthropic-only: empty Groq and Gemini keys so the chain doesn't
    # silently fall through to a different provider on a soft failure.
    agent = LLMComposerAgent(groq_key="", gemini_key="")

    metadata = await agent.compose(
        message=_beach_habitats_inbound(
            "Hi! Looking at your Gulf View property for late June — does it sleep "
            "10 comfortably and how close is it to the beach?"
        ),
        decisions=[_hold_decision()],
        context=_beach_habitats_context(),
    )

    assert metadata.composer_source == "llm_anthropic", (
        f"expected llm_anthropic, got {metadata.composer_source} "
        f"(notes={metadata.composer_notes})"
    )
    _assert_smoke_output_shape(metadata.composer_response_text)

    print(f"\n=== smoke: anthropic ===")
    print(f"Output: {metadata.composer_response_text!r}")
    print(f"Latency: {metadata.composer_latency_ms}ms")
    print(f"Tokens: in={metadata.composer_input_tokens}, out={metadata.composer_output_tokens}")
    print(f"Notes: {metadata.composer_notes}")


@pytest.mark.asyncio
@pytest.mark.skipif(not _RUN_LIVE, reason="RUN_LIVE_LLM_TESTS=1 required")
async def test_smoke_groq_returns_grounded_draft():
    if not os.getenv("GROQ_API_KEY"):
        pytest.skip("GROQ_API_KEY not set")

    # Groq-only: empty Anthropic and Gemini keys.
    agent = LLMComposerAgent(anthropic_key="", gemini_key="")

    metadata = await agent.compose(
        message=_beach_habitats_inbound(
            "Hi! Looking at your Gulf View property for late June — does it sleep "
            "10 comfortably and how close is it to the beach?"
        ),
        decisions=[_hold_decision()],
        context=_beach_habitats_context(),
    )

    assert metadata.composer_source == "llm_groq", (
        f"expected llm_groq, got {metadata.composer_source} "
        f"(notes={metadata.composer_notes})"
    )
    _assert_smoke_output_shape(metadata.composer_response_text)

    print(f"\n=== smoke: groq ===")
    print(f"Output: {metadata.composer_response_text!r}")
    print(f"Latency: {metadata.composer_latency_ms}ms")
    print(f"Tokens: in={metadata.composer_input_tokens}, out={metadata.composer_output_tokens}")
    print(f"Notes: {metadata.composer_notes}")


@pytest.mark.asyncio
@pytest.mark.skipif(not _RUN_LIVE, reason="RUN_LIVE_LLM_TESTS=1 required")
async def test_smoke_gemini_returns_grounded_draft():
    if not (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")):
        pytest.skip("GEMINI_API_KEY/GOOGLE_API_KEY not set")

    # Gemini-only: empty Anthropic and Groq keys.
    agent = LLMComposerAgent(anthropic_key="", groq_key="")

    metadata = await agent.compose(
        message=_beach_habitats_inbound(
            "Hi! Looking at your Gulf View property for late June — does it sleep "
            "10 comfortably and how close is it to the beach?"
        ),
        decisions=[_hold_decision()],
        context=_beach_habitats_context(),
    )

    assert metadata.composer_source == "llm_gemini", (
        f"expected llm_gemini, got {metadata.composer_source} "
        f"(notes={metadata.composer_notes})"
    )
    _assert_smoke_output_shape(metadata.composer_response_text)

    print(f"\n=== smoke: gemini ===")
    print(f"Output: {metadata.composer_response_text!r}")
    print(f"Latency: {metadata.composer_latency_ms}ms")
    print(f"Tokens: in={metadata.composer_input_tokens}, out={metadata.composer_output_tokens}")
    print(f"Notes: {metadata.composer_notes}")


@pytest.mark.asyncio
@pytest.mark.skipif(not _RUN_LIVE, reason="RUN_LIVE_LLM_TESTS=1 required")
async def test_smoke_operator_guidance_precedence_anthropic():
    """The load-bearing behavioral check for the operator-guidance →
    composer pipeline (B1 + Phase C combined).

    Setup:
      * operator_guidance: explicit "no pets allowed"
      * specialist draft_text: warmer/permissive language about pets
      * guest message: asks about bringing a dog

    Expectation:
      * composer's output must DECLINE pets
      * must not echo the specialist's permissive draft language

    This is asserted by checking that the output contains a refusal
    signal AND that operator_guidance was actually populated in the
    rendered prompt (the unit test already covers the prompt
    rendering; this test covers behavior).

    If a future model behaves differently, this test will surface the
    regression at smoke time before it reaches operators.
    """
    if not os.getenv("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set")

    agent = LLMComposerAgent(groq_key="", gemini_key="")

    permissive_specialist_draft = (
        "Hi! We absolutely love hosting four-legged guests — happy to "
        "accommodate your dog at the Beach Habitats Gulf View property. "
        "Looking forward to having you both!"
    )

    metadata = await agent.compose(
        message=_beach_habitats_inbound(
            "Hi! We have a small dog — is he welcome at your property?"
        ),
        decisions=[
            AgentDecision(
                agent_name="HouseRulesAgent",
                intent_topic="house_rules",
                confidence=0.7,
                answer_summary="permissive draft (intentionally wrong)",
                evidence_used=["property_facts"],
                missing_info=[],
                risk_flags=[],
                recommended_action=RecommendedAction.DRAFT_ONLY,
                draft_text=permissive_specialist_draft,
                module_events=[],
            )
        ],
        context=_beach_habitats_context(
            operator_guidance=(
                "PETS: This property does NOT allow pets of any kind, "
                "under any circumstances. No dogs, no cats, no exceptions. "
                "Any guest who asks about bringing a pet should be "
                "politely told the property is not pet-friendly."
            ),
        ),
    )

    assert metadata.composer_source == "llm_anthropic", (
        f"expected llm_anthropic, got {metadata.composer_source} "
        f"(notes={metadata.composer_notes})"
    )
    output = metadata.composer_response_text.lower()
    _assert_smoke_output_shape(metadata.composer_response_text)

    # Refusal signal: at least one of these phrases should appear. We
    # use a permissive list because models phrase refusals differently —
    # what we don't want is the model echoing "we love hosting your dog"
    # from the specialist draft.
    refusal_signals = [
        "not pet",
        "no pets",
        "doesn't allow",
        "does not allow",
        "isn't pet-friendly",
        "is not pet-friendly",
        "unfortunately",
        "afraid",
        "can't accommodate",
        "cannot accommodate",
    ]
    matched = [signal for signal in refusal_signals if signal in output]
    assert matched, (
        f"composer output did not decline pets; expected one of "
        f"{refusal_signals!r} in output. Got: {metadata.composer_response_text!r}"
    )

    # Negative check: the specialist's permissive language should not
    # have been echoed. "absolutely love hosting" is a phrase from the
    # draft that would only appear if the composer treated the draft
    # as a fact source rather than a tone reference.
    assert "absolutely love hosting" not in output, (
        f"composer echoed specialist's permissive language despite "
        f"operator policy: {metadata.composer_response_text!r}"
    )

    print(f"\n=== smoke: operator-guidance precedence ===")
    print(f"Output: {metadata.composer_response_text!r}")
    print(f"Refusal signals matched: {matched}")
    print(f"Latency: {metadata.composer_latency_ms}ms")
