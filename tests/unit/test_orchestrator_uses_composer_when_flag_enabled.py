"""
test_orchestrator_uses_composer_when_flag_enabled.py

C2 verification: GuestMessageBrainOrchestrator routes step 6 through
LLMComposerAgent when MESSAGING_BRAIN_LLM_COMPOSER is on, attaches
ComposerMetadata to the audit record, and respects the
MESSAGING_BRAIN_LLM_COMPOSER_SHADOW flag for shadow-vs-live routing.

Test cases (from docs/SESSION_12_COMPOSER_DESIGN.md test plan, with
audit-writer persistence test deferred to step 7):

  1. Flag OFF: orchestrator's operator-facing draft comes from the
     brain concatenation fallback. composer_metadata is None on the
     audit record.

  2. Flag ON, composer succeeds: orchestrator's operator-facing draft
     is the composer candidate output. composer_metadata.composer_source
     is "llm_anthropic" and composer_response_text is the LLM output.

  3. Flag ON, composer falls through all LLM providers: operator-facing
     draft is the brain concatenation fallback. composer_metadata.
     composer_source is "fallback_concatenation" and
     composer_response_text is the concatenation output.

  4. Flag ON, shadow mode ON: operator-facing draft is the brain
     concatenation fallback (compare mode), but composer_metadata
     is populated with the LLM source and the LLM's text. This is
     the load-bearing test for the "store composer output even when
     it doesn't reach the operator" guardrail.

  5. Flag ON, empty decisions list: orchestrator's operator-facing
     draft is the empty-fallback line. composer_metadata.composer_source
     is "fallback_empty" and composer_response_text is the existing
     "Thanks for the message" line.

  6. Flag ON, composer integration crashes: operator-facing draft is
     the brain concatenation fallback. composer_metadata is populated
     with composer_source="fallback_concatenation" AND a notes line
     containing "composer_orchestrator_error:<ExcType>". This
     distinguishes "composer didn't run" (None) from "composer was
     attempted but broke" (synthetic fallback metadata with error
     note).

  7. Flag-lookup failure: composer flag lookup raises → composer is
     skipped (fail-closed). Audit notes record
     "composer_flag_lookup_error:<ExcType>".

  8. Shadow-flag-lookup failure: composer flag is on, shadow flag
     lookup raises → shadow=True (fail-closed; concatenation stays
     operator-facing). Audit notes record
     "composer_shadow_flag_lookup_error:<ExcType>".

The audit-writer persistence test (test 6 in the design doc — verifying
composer fields survive into the DB layer) is implemented in step 7
of C2 once update_normalization_composer_metadata exists.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.services.messaging_brain.orchestrator import (
    GuestMessageBrainOrchestrator,
)
from app.services.orchestration.messaging_brain_contracts import (
    AgentDecision,
    ClassifierMetadata,
    ComposerMetadata,
    GuestContextBundle,
    InboundGuestMessage,
    IntentType,
    MessageClassification,
    MessagingLifecycle,
    RecommendedAction,
    ResponsePolicyDecision,
    Urgency,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers (mirror the B2 test file's pattern; kept local for readability)
# ─────────────────────────────────────────────────────────────────────────────


_TENANT = "11111111-1111-1111-1111-111111111111"
_PROPERTY_CODE = "GULF_VIEW_204"


def _make_inbound(
    text: str = "is the property pet friendly?",
    message_id: str = "EMAIL_001",
) -> InboundGuestMessage:
    return InboundGuestMessage(
        message_id=message_id,
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
    confidence: float = 0.6,
    recommended_action: RecommendedAction = RecommendedAction.DRAFT_ONLY,
    evidence_used: Optional[List[str]] = None,
    missing_info: Optional[List[str]] = None,
) -> AgentDecision:
    return AgentDecision(
        agent_name=agent_name,
        intent_topic=intent_topic,
        confidence=confidence,
        answer_summary="test decision",
        evidence_used=evidence_used or [],
        missing_info=missing_info or [],
        risk_flags=[],
        recommended_action=recommended_action,
        draft_text=draft_text,
        module_events=[],
    )


def _make_classification(
    intent_topic: str = "house_rules",
) -> MessageClassification:
    return MessageClassification(
        intent_type=IntentType.QUESTION,
        intent_topic=intent_topic,
        confidence=0.85,
        urgency=Urgency.MEDIUM,
        reason="test classification",
    )


def _make_context() -> GuestContextBundle:
    return GuestContextBundle(
        tenant_id=_TENANT,
        property_code=_PROPERTY_CODE,
        property_id=None,
        guest_id=None,
        lifecycle=MessagingLifecycle.PRE_BOOKING,
        property_facts={},
        property_knowledge={},
        reservation_facts={},
        house_rules={},
        access_info={},
        evidence_keys=[],
        missing_context=[],
    )


def _make_policy(
    final_action: RecommendedAction = RecommendedAction.DRAFT_ONLY,
    confidence: float = 0.6,
) -> ResponsePolicyDecision:
    return ResponsePolicyDecision(
        final_action=final_action,
        confidence=confidence,
        reasons=[],
        approval_mode_at_decision="required",
        blocking_escalation_id=None,
        module_events_to_dispatch=[],
    )


def _build_orchestrator_with_decisions(
    decisions: List[AgentDecision],
    *,
    classification: Optional[MessageClassification] = None,
    policy: Optional[ResponsePolicyDecision] = None,
    composer: Optional[Any] = None,
) -> GuestMessageBrainOrchestrator:
    """Build an orchestrator that produces the given decisions and uses
    the given composer (defaults to a MagicMock that won't be called
    unless the test sets up a return value on it).

    Same shape as the B2 test file's helper, with a composer slot added.
    """
    classification = classification or _make_classification()
    policy = policy or _make_policy()
    context = _make_context()

    intake = MagicMock()
    intake.name = "MockIntake"
    intake.classify_with_metadata = AsyncMock(
        return_value=(
            classification,
            ClassifierMetadata(
                classifier_source="test",
                provider_used=None,
                latency_ms=0,
            ),
        )
    )

    context_builder = MagicMock()
    context_builder.name = "MockContextBuilder"
    context_builder.build = AsyncMock(return_value=context)

    audit_writer = MagicMock()
    audit_writer.persist_inbound = AsyncMock(return_value=uuid4())
    audit_writer.write = AsyncMock()

    policy_agent = MagicMock()
    policy_agent.name = "MockPolicyAgent"
    policy_agent.evaluate = AsyncMock(return_value=policy)

    router = MagicMock()
    agent_names = [f"FakeAgent{i}" for i in range(len(decisions))]

    class _RouteOutcome:
        def __init__(self, names: List[str]) -> None:
            self.agent_names = names
            self.reason = "test route"

    router.route = MagicMock(return_value=_RouteOutcome(agent_names))

    # If the test didn't supply a composer, build a MagicMock with
    # an AsyncMock compose. Tests that exercise the composer-on path
    # configure compose.return_value explicitly.
    if composer is None:
        composer = MagicMock()
        composer.compose = AsyncMock()

    orch = GuestMessageBrainOrchestrator(
        router=router,
        intake=intake,
        context_builder=context_builder,
        policy=policy_agent,
        audit_writer=audit_writer,
        composer=composer,
        shadow_mode=False,
    )

    for name, decision in zip(agent_names, decisions):
        fake = MagicMock()
        fake.name = name
        fake.handles_topics = (classification.intent_topic,)
        fake.run = AsyncMock(return_value=decision)
        orch._specialists[name] = fake

    return orch


def _capture_record(orch: GuestMessageBrainOrchestrator) -> Dict[str, Any]:
    """Replace audit_writer.write with a side_effect that captures the
    AgentAuditRecord. Returns a dict whose 'record' key is populated
    after handle_inbound_message completes."""
    captured: Dict[str, Any] = {}

    async def _capture(record, *, db_session, original_message):
        captured["record"] = record

    orch._audit.write = AsyncMock(side_effect=_capture)
    return captured


def _composer_metadata(
    *,
    source: str = "llm_anthropic",
    text: str = "Composer candidate output here.",
    notes: Optional[List[str]] = None,
) -> ComposerMetadata:
    return ComposerMetadata(
        composer_source=source,
        composer_response_text=text,
        composer_latency_ms=120,
        composer_input_tokens=100,
        composer_output_tokens=40,
        composer_notes=notes or [],
    )


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_flag_off_uses_concatenation_no_metadata():
    """Composer flag off → operator-facing draft is brain concatenation;
    composer_metadata is None; composer is never called."""
    decisions = [
        _make_decision(draft_text="First specialist hold."),
        _make_decision(agent_name="A2", draft_text="Second specialist hold."),
    ]
    orch = _build_orchestrator_with_decisions(decisions)
    captured = _capture_record(orch)

    # Composer must not run.
    orch._composer.compose = AsyncMock(
        side_effect=AssertionError("composer should not run when flag is off")
    )

    with patch(
        "app.services.messaging_brain.orchestrator.is_messaging_brain_llm_composer_enabled",
        new=AsyncMock(return_value=False),
    ), patch(
        "app.services.messaging_brain.orchestrator.is_messaging_brain_llm_composer_shadow_enabled",
        new=AsyncMock(side_effect=AssertionError("shadow lookup should not run when composer is off")),
    ), patch(
        "app.services.messaging_brain.orchestrator.is_brain_composer_preferences_enabled",
        new=AsyncMock(side_effect=AssertionError("preferences lookup should not run when composer is off")),
    ):
        draft = await orch.handle_inbound_message(_make_inbound(), db_session=None)

    record = captured["record"]
    assert record.composer_metadata is None
    assert draft.response_text == "First specialist hold.\n\nSecond specialist hold."
    orch._composer.compose.assert_not_awaited()


@pytest.mark.asyncio
async def test_flag_on_composer_succeeds_uses_composer_text():
    """Composer flag on, shadow off, composer returns LLM output →
    operator-facing draft is the composer text. composer_metadata
    populated with llm_anthropic source."""
    decisions = [_make_decision(draft_text="Concatenation fallback text.")]
    expected_composer_text = (
        "Thanks for reaching out — let me confirm the pet policy "
        "with the operator and follow up shortly."
    )

    composer = MagicMock()
    composer.compose = AsyncMock(
        return_value=_composer_metadata(
            source="llm_anthropic",
            text=expected_composer_text,
        )
    )

    orch = _build_orchestrator_with_decisions(decisions, composer=composer)
    captured = _capture_record(orch)

    with patch(
        "app.services.messaging_brain.orchestrator.is_messaging_brain_llm_composer_enabled",
        new=AsyncMock(return_value=True),
    ), patch(
        "app.services.messaging_brain.orchestrator.is_messaging_brain_llm_composer_shadow_enabled",
        new=AsyncMock(return_value=False),
    ):
        draft = await orch.handle_inbound_message(_make_inbound(), db_session=None)

    record = captured["record"]
    assert draft.response_text == expected_composer_text
    assert record.composer_metadata is not None
    assert record.composer_metadata.composer_source == "llm_anthropic"
    assert record.composer_metadata.composer_response_text == expected_composer_text
    composer.compose.assert_awaited_once()
    # Audit notes capture the live-mode signal.
    assert any(
        n.startswith("composer_live_mode:") for n in record.notes
    )


@pytest.mark.asyncio
async def test_flag_on_composer_internal_fallback_concatenation():
    """Composer flag on, composer's own internal logic falls through
    all LLM providers → composer_source='fallback_concatenation'.
    Operator-facing draft is the composer's concatenation text. No
    composer_orchestrator_error note (the composer didn't crash, it
    just fell back internally)."""
    decisions = [_make_decision(draft_text="Concatenation fallback text.")]

    composer = MagicMock()
    composer.compose = AsyncMock(
        return_value=_composer_metadata(
            source="fallback_concatenation",
            text="Concatenation fallback text.",
            notes=["composer_no_keys_configured"],
        )
    )

    orch = _build_orchestrator_with_decisions(decisions, composer=composer)
    captured = _capture_record(orch)

    with patch(
        "app.services.messaging_brain.orchestrator.is_messaging_brain_llm_composer_enabled",
        new=AsyncMock(return_value=True),
    ), patch(
        "app.services.messaging_brain.orchestrator.is_messaging_brain_llm_composer_shadow_enabled",
        new=AsyncMock(return_value=False),
    ):
        draft = await orch.handle_inbound_message(_make_inbound(), db_session=None)

    record = captured["record"]
    assert draft.response_text == "Concatenation fallback text."
    assert record.composer_metadata is not None
    assert record.composer_metadata.composer_source == "fallback_concatenation"
    # No orchestrator-error note — the composer's own internal logic
    # fell back, which is distinct from an integration crash.
    assert not any(
        "composer_orchestrator_error" in n
        for n in record.composer_metadata.composer_notes
    )


@pytest.mark.asyncio
async def test_flag_on_shadow_on_operator_sees_concatenation():
    """Composer flag on, shadow flag on → operator-facing draft is the
    brain concatenation fallback, but composer_metadata is populated
    with the LLM's text. This is the load-bearing test for the
    'store composer output even when it doesn't reach operator' guardrail.
    """
    decisions = [
        _make_decision(draft_text="First specialist hold."),
        _make_decision(agent_name="A2", draft_text="Second specialist hold."),
    ]
    composer_text = (
        "A nicely synthesized warm reply that the operator should "
        "NOT see in shadow mode."
    )
    expected_concatenation = "First specialist hold.\n\nSecond specialist hold."

    composer = MagicMock()
    composer.compose = AsyncMock(
        return_value=_composer_metadata(
            source="llm_anthropic",
            text=composer_text,
        )
    )

    orch = _build_orchestrator_with_decisions(decisions, composer=composer)
    captured = _capture_record(orch)

    with patch(
        "app.services.messaging_brain.orchestrator.is_messaging_brain_llm_composer_enabled",
        new=AsyncMock(return_value=True),
    ), patch(
        "app.services.messaging_brain.orchestrator.is_messaging_brain_llm_composer_shadow_enabled",
        new=AsyncMock(return_value=True),
    ):
        draft = await orch.handle_inbound_message(_make_inbound(), db_session=None)

    record = captured["record"]
    # Operator sees concatenation.
    assert draft.response_text == expected_concatenation
    # Composer metadata still records the LLM text for compare.
    assert record.composer_metadata is not None
    assert record.composer_metadata.composer_source == "llm_anthropic"
    assert record.composer_metadata.composer_response_text == composer_text
    # Audit notes capture the shadow-mode signal.
    assert any(
        n.startswith("composer_shadow_mode:") for n in record.notes
    )


@pytest.mark.asyncio
async def test_flag_on_empty_decisions_returns_fallback_empty():
    """Composer flag on, decisions list empty → composer's empty
    fallback runs. composer_source='fallback_empty',
    composer_response_text is the existing 'Thanks for the message'
    line. Operator sees that line."""
    composer = MagicMock()
    composer.compose = AsyncMock(
        return_value=_composer_metadata(
            source="fallback_empty",
            text="Thanks for the message — I'll get back to you shortly.",
        )
    )

    orch = _build_orchestrator_with_decisions([], composer=composer)
    captured = _capture_record(orch)

    with patch(
        "app.services.messaging_brain.orchestrator.is_messaging_brain_llm_composer_enabled",
        new=AsyncMock(return_value=True),
    ), patch(
        "app.services.messaging_brain.orchestrator.is_messaging_brain_llm_composer_shadow_enabled",
        new=AsyncMock(return_value=False),
    ):
        draft = await orch.handle_inbound_message(_make_inbound(), db_session=None)

    record = captured["record"]
    assert record.composer_metadata is not None
    assert record.composer_metadata.composer_source == "fallback_empty"
    assert "Thanks for the message" in record.composer_metadata.composer_response_text
    assert "Thanks for the message" in draft.response_text


@pytest.mark.asyncio
async def test_flag_on_composer_crash_records_synthetic_metadata():
    """Composer flag on, composer.compose raises → orchestrator returns
    operator-facing draft = brain concatenation, AND
    composer_metadata is populated with synthetic
    composer_source='fallback_concatenation' AND
    composer_notes containing 'composer_orchestrator_error:<ExcType>'.

    This distinguishes 'composer didn't run' (None) from 'composer
    was attempted but broke' (synthetic fallback metadata)."""
    decisions = [_make_decision(draft_text="Concatenation fallback text.")]

    composer = MagicMock()
    composer.compose = AsyncMock(side_effect=RuntimeError("composer integration broken"))

    orch = _build_orchestrator_with_decisions(decisions, composer=composer)
    captured = _capture_record(orch)

    with patch(
        "app.services.messaging_brain.orchestrator.is_messaging_brain_llm_composer_enabled",
        new=AsyncMock(return_value=True),
    ), patch(
        "app.services.messaging_brain.orchestrator.is_messaging_brain_llm_composer_shadow_enabled",
        new=AsyncMock(return_value=False),
    ):
        draft = await orch.handle_inbound_message(_make_inbound(), db_session=None)

    record = captured["record"]
    # Operator-facing draft is the concatenation.
    assert draft.response_text == "Concatenation fallback text."
    # composer_metadata is NOT None — composer was attempted.
    assert record.composer_metadata is not None
    assert record.composer_metadata.composer_source == "fallback_concatenation"
    assert record.composer_metadata.composer_response_text == "Concatenation fallback text."
    # The error is recorded in composer_notes, not record.notes — that's
    # the audit-state distinction we want.
    assert any(
        "composer_orchestrator_error:RuntimeError" in n
        for n in record.composer_metadata.composer_notes
    )


@pytest.mark.asyncio
async def test_composer_flag_lookup_failure_skips_composer():
    """is_messaging_brain_llm_composer_enabled raises → composer skipped
    (fail-closed). composer_metadata is None. Audit notes record the
    error so the failure is queryable."""
    decisions = [_make_decision(draft_text="Concatenation fallback text.")]

    composer = MagicMock()
    composer.compose = AsyncMock(
        side_effect=AssertionError("composer should not run when flag lookup fails")
    )

    orch = _build_orchestrator_with_decisions(decisions, composer=composer)
    captured = _capture_record(orch)

    with patch(
        "app.services.messaging_brain.orchestrator.is_messaging_brain_llm_composer_enabled",
        new=AsyncMock(side_effect=RuntimeError("flag db down")),
    ), patch(
        "app.services.messaging_brain.orchestrator.is_messaging_brain_llm_composer_shadow_enabled",
        new=AsyncMock(side_effect=AssertionError("shadow lookup should not run after composer-flag fails")),
    ):
        draft = await orch.handle_inbound_message(_make_inbound(), db_session=None)

    record = captured["record"]
    assert record.composer_metadata is None
    assert draft.response_text == "Concatenation fallback text."
    assert any(
        n.startswith("composer_flag_lookup_error:RuntimeError")
        for n in record.notes
    )


@pytest.mark.asyncio
async def test_composer_shadow_flag_lookup_failure_defaults_to_live_mode():
    """Composer flag on, shadow flag lookup raises → fail-open to
    shadow=False. Operator sees composer output; composer_metadata
    populated; audit note records the shadow-flag lookup error."""
    decisions = [_make_decision(draft_text="Concatenation fallback text.")]
    composer_text = "Composer candidate (should NOT reach operator)."

    composer = MagicMock()
    composer.compose = AsyncMock(
        return_value=_composer_metadata(
            source="llm_anthropic",
            text=composer_text,
        )
    )

    orch = _build_orchestrator_with_decisions(decisions, composer=composer)
    captured = _capture_record(orch)

    with patch(
        "app.services.messaging_brain.orchestrator.is_messaging_brain_llm_composer_enabled",
        new=AsyncMock(return_value=True),
    ), patch(
        "app.services.messaging_brain.orchestrator.is_messaging_brain_llm_composer_shadow_enabled",
        new=AsyncMock(side_effect=RuntimeError("flag db down for shadow lookup")),
    ):
        draft = await orch.handle_inbound_message(_make_inbound(), db_session=None)

    record = captured["record"]
    # Fail-open behavior: operator sees composer output when the shadow
    # flag cannot be read.
    assert draft.response_text == composer_text
    # Composer ran; metadata captured.
    assert record.composer_metadata is not None
    assert record.composer_metadata.composer_response_text == composer_text
    # We record the lookup error but do not mark shadow mode.
    assert any(
        n.startswith("composer_shadow_flag_lookup_error:RuntimeError")
        for n in record.notes
    )
    assert any(
        n.startswith("composer_live_mode:") for n in record.notes
    )
    assert not any(
        n.startswith("composer_shadow_mode:") for n in record.notes
    )


@pytest.mark.asyncio
async def test_composer_preferences_flag_flows_into_compose_call():
    decisions = [_make_decision(draft_text="Specialist hold.")]
    composer = MagicMock()
    composer.compose = AsyncMock(
        return_value=_composer_metadata(
            source="llm_anthropic",
            text="Preference-aware output.",
        )
    )

    orch = _build_orchestrator_with_decisions(decisions, composer=composer)

    with patch(
        "app.services.messaging_brain.orchestrator.is_messaging_brain_llm_composer_enabled",
        new=AsyncMock(return_value=True),
    ), patch(
        "app.services.messaging_brain.orchestrator.is_messaging_brain_llm_composer_shadow_enabled",
        new=AsyncMock(return_value=False),
    ), patch(
        "app.services.messaging_brain.orchestrator.is_brain_composer_preferences_enabled",
        new=AsyncMock(return_value=True),
    ):
        await orch.handle_inbound_message(_make_inbound(), db_session=None)

    assert composer.compose.await_args.kwargs["include_learned_preferences"] is True
