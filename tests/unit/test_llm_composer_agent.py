"""
test_llm_composer_agent.py — unit tests for LLMComposerAgent.

Covers Session 12 / Phase C2 of docs/IMPLEMENTATION_QUEUE_2026_05_05.md.
See docs/SESSION_12_COMPOSER_DESIGN.md for the full design.

These tests exercise the composer in isolation — no orchestrator, no
HTTP. Provider methods (_call_anthropic / _call_groq / _call_gemini)
are patched at the agent-instance level so we observe the composer's
exact decision logic without making real network calls.

Test cases:
  1. Anthropic returns valid output → composer returns it
  2. Anthropic times out → falls through to Groq
  3. Groq fails (exception) → falls through to Gemini
  4. All three providers fail → fallback_concatenation
  5. Empty decisions list → fallback_empty
  6. Output below 30 chars → invalid → falls through
  7. Output containing placeholder phrase → invalid → falls through
  8. Output exceeding 700 char cap → invalid → falls through
  9. No API keys configured at all → fallback_concatenation
       immediately, no LLM calls attempted
 10. Per-provider timeout enforced
 11. Operator-guidance precedence: operator_guidance text appears in
       the rendered user message with FOLLOW THESE EXACTLY framing
 12. Notes-only grounding heuristic flags dollar amounts, percentages,
       time-of-day, phone numbers, email addresses without invalidating
       output
 13. composer_response_text is populated even on fallback paths
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.services.messaging_brain.agents.llm_composer_agent import (
    LLMComposerAgent,
    SYSTEM_PROMPT,
)
from app.services.observability.llm_usage_tracker import LLMUsageTracker
from app.services.orchestration.messaging_brain_contracts import (
    AgentDecision,
    ComposerMetadata,
    GuestContextBundle,
    InboundGuestMessage,
    MessagingLifecycle,
    RecommendedAction,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


_TENANT = "11111111-1111-1111-1111-111111111111"
_PROPERTY_CODE = "GULF_VIEW_204"


def _make_inbound(text: str = "is the property pet friendly?") -> InboundGuestMessage:
    return InboundGuestMessage(
        message_id="EMAIL_001",
        tenant_id=_TENANT,
        channel="email",
        source_provider="gmail",
        text=text,
        guest_name="Jane Guest",
        guest_email="jane@example.com",
        property_code=_PROPERTY_CODE,
        received_at=datetime.utcnow(),
        metadata={},
    )


def _make_decision(
    *,
    agent_name: str = "HouseRulesAgent",
    intent_topic: str = "house_rules",
    draft_text: str = "I'll confirm the pet policy and follow up shortly.",
    confidence: float = 0.7,
    missing_info: Optional[List[str]] = None,
    recommended_action: RecommendedAction = RecommendedAction.DRAFT_ONLY,
    evidence_used: Optional[List[str]] = None,
    clarification_questions: Optional[List[str]] = None,
) -> AgentDecision:
    return AgentDecision(
        agent_name=agent_name,
        intent_topic=intent_topic,
        confidence=confidence,
        answer_summary="test decision",
        evidence_used=evidence_used or [],
        missing_info=missing_info or [],
        clarification_questions=clarification_questions or [],
        risk_flags=[],
        recommended_action=recommended_action,
        draft_text=draft_text,
        module_events=[],
    )


def _make_context(
    *,
    operator_guidance: str = "",
    learned_preferences: str = "",
    property_facts: Optional[Dict[str, Any]] = None,
) -> GuestContextBundle:
    return GuestContextBundle(
        tenant_id=_TENANT,
        property_code=_PROPERTY_CODE,
        property_id=None,
        guest_id=None,
        lifecycle=MessagingLifecycle.PRE_BOOKING,
        property_facts=property_facts or {},
        property_knowledge={},
        reservation_facts={},
        house_rules={},
        access_info={},
        operator_guidance=operator_guidance,
        learned_preferences_block=learned_preferences,
        evidence_keys=[],
        missing_context=[],
    )


def _extract_block(user_message: str, heading: str) -> str:
    marker = f"## {heading}\n"
    if marker not in user_message:
        return ""
    rest = user_message.split(marker, 1)[1]
    if "\n\n## " in rest:
        return rest.split("\n\n## ", 1)[0].strip()
    return rest.strip()


def _build_agent(
    *,
    anthropic_key: str = "anth-key",
    groq_key: str = "groq-key",
    gemini_key: str = "gemini-key",
) -> LLMComposerAgent:
    return LLMComposerAgent(
        anthropic_key=anthropic_key,
        groq_key=groq_key,
        gemini_key=gemini_key,
        per_provider_timeout_seconds=4.0,
        total_budget_seconds=6.0,
    )


def _ok_response(text: str, input_tokens: int = 100, output_tokens: int = 50) -> Dict[str, Any]:
    return {
        "text": text,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_anthropic_returns_valid_output():
    """Happy path — Anthropic returns valid text and the composer
    returns it as the candidate output."""
    agent = _build_agent()
    expected_text = (
        "Thanks for reaching out — I'll confirm the pet policy with the "
        "operator and get right back to you."
    )

    agent._call_anthropic = AsyncMock(
        return_value=_ok_response(expected_text)
    )
    agent._call_groq = AsyncMock(side_effect=AssertionError("groq should not run"))
    agent._call_gemini = AsyncMock(side_effect=AssertionError("gemini should not run"))

    with patch.object(LLMUsageTracker, "record", new=AsyncMock()) as tracker:
        metadata = await agent.compose(
            message=_make_inbound(),
            decisions=[_make_decision()],
            context=_make_context(),
        )

    assert metadata.composer_source == "llm_anthropic"
    assert metadata.composer_response_text == expected_text
    assert metadata.composer_input_tokens == 100
    assert metadata.composer_output_tokens == 50
    assert metadata.composer_latency_ms >= 0
    assert metadata.clarification_chosen is False
    # No invalid-output, timeout, or fallback notes.
    assert not any(n.startswith("composer_invalid_output") for n in metadata.composer_notes)
    assert not any(n.startswith("composer_timeout") for n in metadata.composer_notes)
    tracker.assert_awaited_once()
    assert tracker.await_args.kwargs["service_name"] == "brain_composer"
    assert tracker.await_args.kwargs["request_type"] == "brain_draft_generation"
    assert tracker.await_args.kwargs["tenant_id"] == UUID(_TENANT)
    agent._call_anthropic.assert_awaited_once()
    agent._call_groq.assert_not_awaited()
    agent._call_gemini.assert_not_awaited()


def test_build_user_message_omits_preferences_when_flag_disabled():
    message = _make_inbound()
    context = _make_context(learned_preferences="Prefer a softer tone for pet questions.")
    user_message = LLMComposerAgent._build_user_message(
        message=message,
        decisions=[_make_decision()],
        context=context,
        include_learned_preferences=False,
        missing_topic_ids=[],
    )

    assert _extract_block(user_message, "4. Learned Preferences") == "(none)"


def test_build_user_message_includes_preferences_when_flag_enabled():
    message = _make_inbound()
    context = _make_context(learned_preferences="Prefer a softer tone for pet questions.")
    user_message = LLMComposerAgent._build_user_message(
        message=message,
        decisions=[_make_decision()],
        context=context,
        include_learned_preferences=True,
        missing_topic_ids=[],
    )

    assert "Prefer a softer tone for pet questions." in _extract_block(
        user_message,
        "4. Learned Preferences",
    )


@pytest.mark.asyncio
async def test_anthropic_timeout_falls_through_to_groq():
    """When Anthropic times out, the composer tries Groq and uses its
    output. The fallthrough is recorded in composer_notes."""
    agent = _build_agent()
    expected_text = "I'll confirm the pet policy with the operator and follow up shortly."

    async def _slow_anthropic(*args, **kwargs):
        await asyncio.sleep(10)
        return _ok_response("never reached")

    agent._call_anthropic = AsyncMock(side_effect=_slow_anthropic)
    agent._call_groq = AsyncMock(return_value=_ok_response(expected_text))
    agent._call_gemini = AsyncMock(side_effect=AssertionError("gemini should not run"))
    # Tighten the per-provider timeout for this test so it runs fast.
    agent._per_provider_timeout = 0.05

    metadata = await agent.compose(
        message=_make_inbound(),
        decisions=[_make_decision()],
        context=_make_context(),
    )

    assert metadata.composer_source == "llm_groq"
    assert metadata.composer_response_text == expected_text
    assert any(n == "composer_timeout:anthropic" for n in metadata.composer_notes)
    agent._call_groq.assert_awaited_once()


@pytest.mark.asyncio
async def test_groq_exception_falls_through_to_gemini():
    """Anthropic returns invalid output, Groq raises, Gemini succeeds.
    Both prior failures are recorded."""
    agent = _build_agent()
    expected_text = "I'll confirm the pet policy with the operator and follow up shortly."

    agent._call_anthropic = AsyncMock(
        return_value=_ok_response("could not generate a response right now")
    )
    agent._call_groq = AsyncMock(side_effect=RuntimeError("groq down"))
    agent._call_gemini = AsyncMock(return_value=_ok_response(expected_text))

    metadata = await agent.compose(
        message=_make_inbound(),
        decisions=[_make_decision()],
        context=_make_context(),
    )

    assert metadata.composer_source == "llm_gemini"
    assert metadata.composer_response_text == expected_text
    assert any(
        n.startswith("composer_invalid_output:anthropic:placeholder_phrase")
        for n in metadata.composer_notes
    )
    assert any(
        n == "composer_exception:groq:RuntimeError"
        for n in metadata.composer_notes
    )


@pytest.mark.asyncio
async def test_all_providers_fail_falls_through_to_concatenation():
    """When all three LLM providers fail, the composer returns the
    brain concatenation fallback. composer_response_text is the
    concatenation, not empty."""
    agent = _build_agent()
    decisions = [
        _make_decision(draft_text="First specialist hold."),
        _make_decision(agent_name="AccessAgent", draft_text="Second specialist hold."),
    ]

    agent._call_anthropic = AsyncMock(side_effect=RuntimeError("down"))
    agent._call_groq = AsyncMock(side_effect=RuntimeError("down"))
    agent._call_gemini = AsyncMock(side_effect=RuntimeError("down"))

    metadata = await agent.compose(
        message=_make_inbound(),
        decisions=decisions,
        context=_make_context(),
    )

    assert metadata.composer_source == "fallback_concatenation"
    assert metadata.composer_response_text == "First specialist hold.\n\nSecond specialist hold."
    assert any(n == "composer_all_providers_failed" for n in metadata.composer_notes)
    assert metadata.composer_input_tokens is None
    assert metadata.composer_output_tokens is None


@pytest.mark.asyncio
async def test_empty_decisions_returns_fallback_empty():
    """Empty decisions list → fast path with no LLM call attempted.
    composer_source is fallback_empty and composer_response_text is
    the existing 'Thanks for the message' line."""
    agent = _build_agent()

    agent._call_anthropic = AsyncMock(side_effect=AssertionError("anth should not run"))
    agent._call_groq = AsyncMock(side_effect=AssertionError("groq should not run"))
    agent._call_gemini = AsyncMock(side_effect=AssertionError("gemini should not run"))

    metadata = await agent.compose(
        message=_make_inbound(),
        decisions=[],
        context=_make_context(),
    )

    assert metadata.composer_source == "fallback_empty"
    assert metadata.composer_response_text == "Thanks for the message — I'll get back to you shortly."
    agent._call_anthropic.assert_not_awaited()
    agent._call_groq.assert_not_awaited()
    agent._call_gemini.assert_not_awaited()


@pytest.mark.asyncio
async def test_output_below_min_chars_invalidates():
    """Anthropic returns under 30 chars → invalid → falls through
    to Groq."""
    agent = _build_agent()

    agent._call_anthropic = AsyncMock(return_value=_ok_response("Too short."))
    agent._call_groq = AsyncMock(
        return_value=_ok_response(
            "I'll confirm the pet policy with the operator and follow up shortly."
        )
    )
    agent._call_gemini = AsyncMock()

    metadata = await agent.compose(
        message=_make_inbound(),
        decisions=[_make_decision()],
        context=_make_context(),
    )

    assert metadata.composer_source == "llm_groq"
    assert any(
        n.startswith("composer_invalid_output:anthropic:too_short")
        for n in metadata.composer_notes
    )


@pytest.mark.asyncio
async def test_placeholder_phrase_invalidates():
    """Anthropic output containing a placeholder phrase → invalid →
    falls through."""
    agent = _build_agent()

    agent._call_anthropic = AsyncMock(
        return_value=_ok_response(
            "As an AI language model, I can confirm the pet policy and follow up shortly."
        )
    )
    valid_text = "I'll confirm the pet policy with the operator and follow up shortly."
    agent._call_groq = AsyncMock(return_value=_ok_response(valid_text))
    agent._call_gemini = AsyncMock()

    metadata = await agent.compose(
        message=_make_inbound(),
        decisions=[_make_decision()],
        context=_make_context(),
    )

    assert metadata.composer_source == "llm_groq"
    assert metadata.composer_response_text == valid_text
    assert any(
        n.startswith("composer_invalid_output:anthropic:placeholder_phrase")
        for n in metadata.composer_notes
    )


@pytest.mark.asyncio
async def test_output_exceeding_cap_invalidates():
    """Anthropic returns >700 chars → invalid → falls through."""
    agent = _build_agent()
    long_text = "A" * 800
    valid_text = "I'll confirm the pet policy with the operator and follow up shortly."

    agent._call_anthropic = AsyncMock(return_value=_ok_response(long_text))
    agent._call_groq = AsyncMock(return_value=_ok_response(valid_text))
    agent._call_gemini = AsyncMock()

    metadata = await agent.compose(
        message=_make_inbound(),
        decisions=[_make_decision()],
        context=_make_context(),
    )

    assert metadata.composer_source == "llm_groq"
    assert any(
        n.startswith("composer_invalid_output:anthropic:too_long")
        for n in metadata.composer_notes
    )


@pytest.mark.asyncio
async def test_no_keys_configured_falls_through_immediately():
    """No API keys at all → no LLM calls attempted, immediate fallback
    to concatenation. Audit trail records composer_no_key:* per
    provider plus composer_no_keys_configured."""
    agent = _build_agent(anthropic_key="", groq_key="", gemini_key="")

    agent._call_anthropic = AsyncMock(side_effect=AssertionError("should not run"))
    agent._call_groq = AsyncMock(side_effect=AssertionError("should not run"))
    agent._call_gemini = AsyncMock(side_effect=AssertionError("should not run"))

    metadata = await agent.compose(
        message=_make_inbound(),
        decisions=[_make_decision(draft_text="Hold response.")],
        context=_make_context(),
    )

    assert metadata.composer_source == "fallback_concatenation"
    assert metadata.composer_response_text == "Hold response."
    assert any(n == "composer_no_key:anthropic" for n in metadata.composer_notes)
    assert any(n == "composer_no_key:groq" for n in metadata.composer_notes)
    assert any(n == "composer_no_key:gemini" for n in metadata.composer_notes)
    assert any(n == "composer_no_keys_configured" for n in metadata.composer_notes)
    agent._call_anthropic.assert_not_awaited()


@pytest.mark.asyncio
async def test_per_provider_timeout_enforced():
    """asyncio.wait_for is what enforces the per-provider cap. Verify
    the composer respects it: a slow Anthropic gets cancelled, Groq
    runs."""
    agent = _build_agent()
    agent._per_provider_timeout = 0.05

    started_groq = asyncio.Event()
    valid_text = "I'll confirm the pet policy with the operator and follow up shortly."

    async def _slow_anthropic(*args, **kwargs):
        await asyncio.sleep(5)
        return _ok_response("never reached")

    async def _fast_groq(*args, **kwargs):
        started_groq.set()
        return _ok_response(valid_text)

    agent._call_anthropic = AsyncMock(side_effect=_slow_anthropic)
    agent._call_groq = AsyncMock(side_effect=_fast_groq)
    agent._call_gemini = AsyncMock()

    metadata = await agent.compose(
        message=_make_inbound(),
        decisions=[_make_decision()],
        context=_make_context(),
    )

    assert metadata.composer_source == "llm_groq"
    assert started_groq.is_set()
    assert any(n == "composer_timeout:anthropic" for n in metadata.composer_notes)


@pytest.mark.asyncio
async def test_operator_guidance_renders_with_follow_exactly_framing():
    """The user message sent to providers must include operator_guidance
    under the FOLLOW THESE EXACTLY heading. We verify by inspecting the
    user_message argument the provider received."""
    agent = _build_agent()
    captured_user_message = {}

    async def _capture(user_message: str):
        captured_user_message["text"] = user_message
        return _ok_response(
            "I'll confirm the pet policy with the operator and follow up shortly."
        )

    agent._call_anthropic = AsyncMock(side_effect=_capture)

    operator_text = "No pets allowed at this property under any circumstances."
    metadata = await agent.compose(
        message=_make_inbound(text="can we bring our dog?"),
        decisions=[_make_decision()],
        context=_make_context(operator_guidance=operator_text),
    )

    assert metadata.composer_source == "llm_anthropic"
    rendered = captured_user_message["text"]
    assert "## 3. Operator House Rules & Policy (FOLLOW THESE EXACTLY)" in rendered
    assert operator_text in rendered
    # Current prompt layout splits history and newest message into
    # separate blocks; the newest guest turn should appear in Block 6.
    assert "## 5. Conversation history so far" in rendered
    assert "## 6. Newest guest message to reply to" in rendered
    assert "can we bring our dog?" in rendered


@pytest.mark.asyncio
async def test_composer_can_choose_clarification_without_specialist_clarify():
    agent = _build_agent()
    clarify_text = (
        "Congratulations on your elopement. Could you share how many people would be joining you, "
        "and whether you’re picturing a small family gathering or something more event-style?"
    )

    agent._call_anthropic = AsyncMock(return_value=_ok_response(clarify_text))
    metadata = await agent.compose(
        message=_make_inbound(
            text="We recently eloped and would love to celebrate with our family at the home."
        ),
        decisions=[
            _make_decision(
                agent_name="BookingInquiryAgent",
                intent_topic="booking_inquiry",
                draft_text="I’m confirming the details now.",
                recommended_action=RecommendedAction.DRAFT_ONLY,
                missing_info=["event_type"],
            )
        ],
        context=_make_context(
            property_facts={"max_guests": 10},
        ),
    )

    assert metadata.composer_source == "llm_anthropic"
    assert metadata.composer_response_text == clarify_text
    assert metadata.clarification_chosen is True
    assert "how many people" in metadata.composer_response_text.lower()


@pytest.mark.asyncio
async def test_grounding_heuristic_flags_without_invalidating():
    """Composer output containing dollar amounts, percentages, time-of-day,
    phone numbers, or email addresses produces composer_grounding_warning
    notes but does NOT invalidate the output."""
    agent = _build_agent()
    suspect_text = (
        "The cleaning fee is $150 and we offer 10% off. Check-in is at 4pm. "
        "Reach out to manager@example.com or 555-123-4567 for questions."
    )

    agent._call_anthropic = AsyncMock(return_value=_ok_response(suspect_text))
    agent._call_groq = AsyncMock(side_effect=AssertionError("groq should not run"))
    agent._call_gemini = AsyncMock(side_effect=AssertionError("gemini should not run"))

    metadata = await agent.compose(
        message=_make_inbound(),
        decisions=[_make_decision()],
        context=_make_context(),
    )

    # Output is still used — not invalidated.
    assert metadata.composer_source == "llm_anthropic"
    assert metadata.composer_response_text == suspect_text

    notes = metadata.composer_notes
    # Each pattern produced at least one warning.
    assert any(n.startswith("composer_grounding_warning:dollar_amount:") for n in notes)
    assert any(n.startswith("composer_grounding_warning:percentage:") for n in notes)
    assert any(n.startswith("composer_grounding_warning:time_of_day:") for n in notes)
    assert any(n.startswith("composer_grounding_warning:phone_number:") for n in notes)
    assert any(n.startswith("composer_grounding_warning:email_address:") for n in notes)


@pytest.mark.asyncio
async def test_composer_response_text_populated_on_all_paths():
    """composer_response_text must always be populated, regardless of
    which path produced the result. This is the load-bearing field
    for shadow-mode compare."""
    # Path 1: empty decisions → fallback_empty.
    agent = _build_agent(anthropic_key="", groq_key="", gemini_key="")
    metadata = await agent.compose(
        message=_make_inbound(),
        decisions=[],
        context=_make_context(),
    )
    assert metadata.composer_source == "fallback_empty"
    assert metadata.composer_response_text  # non-empty
    assert "Thanks for the message" in metadata.composer_response_text

    # Path 2: no keys → fallback_concatenation.
    metadata = await agent.compose(
        message=_make_inbound(),
        decisions=[_make_decision(draft_text="Specialist hold language.")],
        context=_make_context(),
    )
    assert metadata.composer_source == "fallback_concatenation"
    assert metadata.composer_response_text == "Specialist hold language."

    # Path 3: keys present, LLM succeeds.
    agent = _build_agent()
    agent._call_anthropic = AsyncMock(
        return_value=_ok_response(
            "I'll confirm the pet policy with the operator and follow up shortly."
        )
    )
    metadata = await agent.compose(
        message=_make_inbound(),
        decisions=[_make_decision()],
        context=_make_context(),
    )
    assert metadata.composer_source == "llm_anthropic"
    assert metadata.composer_response_text  # non-empty
    assert "pet policy" in metadata.composer_response_text
