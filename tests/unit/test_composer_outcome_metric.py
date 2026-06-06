"""
test_composer_outcome_metric.py

Tests for the composer-outcome Prometheus metric emitted at orchestrator
step 6.  Three layers:

  1. Table test: observe_composer_outcome maps every (source, notes) combo
     to the expected (composer_source, fallback_cause) label pair.  Six
     cases (healthy LLM, orchestrator error, no keys, providers failed,
     empty, flag-off).

  2. Orchestrator path tests: confirm emit-once, emit-nothing on fast-path
     early return, and emit-nothing on pre-step-6 exception.

  3. Integration test: when the composer flag is ON but no API keys are set,
     the resulting ComposerMetadata carries a no_key* note, and the helper
     maps it to fallback_cause="no_keys".

Background:
  May 21-26 silent outage — keys weren't reaching the running process for
  5 days.  19 guests received canned concatenation with no alert fired.
  This metric + the ComposerFallbackSustained alert rule closes that gap.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, List, Optional
from unittest.mock import AsyncMock, MagicMock, call, patch
from uuid import uuid4

import pytest

from app.services.observability.slo_metrics import observe_composer_outcome
from app.services.orchestration.messaging_brain_contracts import (
    AgentDecision,
    ClassifierMetadata,
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
# 1. Table tests — observe_composer_outcome label mapping
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "composer_source, composer_notes, expected_source, expected_cause",
    [
        # Healthy LLM paths
        (
            "llm_anthropic",
            [],
            "llm_anthropic",
            "none",
        ),
        (
            "llm_groq",
            ["some_note"],
            "llm_groq",
            "none",
        ),
        (
            "llm_gemini",
            [],
            "llm_gemini",
            "none",
        ),
        # fallback_concatenation — orchestrator crash
        (
            "fallback_concatenation",
            ["composer_orchestrator_error:ValueError"],
            "fallback_concatenation",
            "orchestrator_error",
        ),
        # fallback_concatenation — keys missing (the May 21-26 signature)
        (
            "fallback_concatenation",
            ["composer_no_key:anthropic", "other_note"],
            "fallback_concatenation",
            "no_keys",
        ),
        (
            "fallback_concatenation",
            ["composer_no_keys_configured"],
            "fallback_concatenation",
            "no_keys",
        ),
        # fallback_concatenation — provider-failure fallback (neither error note)
        (
            "fallback_concatenation",
            ["anthropic_timeout", "groq_timeout"],
            "fallback_concatenation",
            "providers_failed",
        ),
        (
            "fallback_concatenation",
            [],
            "fallback_concatenation",
            "providers_failed",
        ),
        # Benign empty — no decisions to compose
        (
            "fallback_empty",
            [],
            "fallback_empty",
            "empty",
        ),
        # Composer flag off (caller passes "none")
        (
            "none",
            [],
            "none",
            "flag_off",
        ),
    ],
    ids=[
        "healthy_llm_anthropic",
        "healthy_llm_groq",
        "healthy_llm_gemini",
        "fallback_orchestrator_error",
        "fallback_no_key_anthropic",
        "fallback_no_keys_configured",
        "fallback_providers_failed_with_notes",
        "fallback_providers_failed_empty_notes",
        "fallback_empty",
        "flag_off",
    ],
)
def test_observe_composer_outcome_label_mapping(
    composer_source,
    composer_notes,
    expected_source,
    expected_cause,
):
    """observe_composer_outcome emits the correct (composer_source, fallback_cause)
    label pair for each input combination."""
    mock_counter = MagicMock()
    mock_slo = MagicMock()

    with (
        patch("app.services.observability.slo_metrics.COMPOSER_OUTCOME_TOTAL", mock_counter),
        patch("app.services.observability.slo_metrics.SLO_BREACH_TOTAL", mock_slo),
    ):
        observe_composer_outcome(
            composer_source=composer_source,
            composer_notes=composer_notes,
        )

    mock_counter.labels.assert_called_once_with(
        composer_source=expected_source,
        fallback_cause=expected_cause,
    )
    mock_counter.labels.return_value.inc.assert_called_once()


def test_observe_composer_outcome_slo_breach_on_page_causes():
    """PAGE-severity causes (no_keys, orchestrator_error) also increment
    SLO_BREACH_TOTAL(slo="composer_fallback")."""
    mock_counter = MagicMock()
    mock_slo = MagicMock()

    for source, notes in [
        ("fallback_concatenation", ["composer_no_key:anthropic"]),
        ("fallback_concatenation", ["composer_orchestrator_error:RuntimeError"]),
    ]:
        mock_slo.reset_mock()
        with (
            patch("app.services.observability.slo_metrics.COMPOSER_OUTCOME_TOTAL", mock_counter),
            patch("app.services.observability.slo_metrics.SLO_BREACH_TOTAL", mock_slo),
        ):
            observe_composer_outcome(composer_source=source, composer_notes=notes)

        mock_slo.labels.assert_called_with(slo="composer_fallback")
        mock_slo.labels.return_value.inc.assert_called()


def test_observe_composer_outcome_no_slo_breach_on_warn_and_benign_causes():
    """WARN-severity (providers_failed) and benign causes (empty, flag_off,
    healthy LLM) do NOT increment SLO_BREACH_TOTAL(slo='composer_fallback')."""
    benign_inputs = [
        ("llm_anthropic", []),
        ("fallback_empty", []),
        ("none", []),
        ("fallback_concatenation", []),          # providers_failed
    ]
    for source, notes in benign_inputs:
        mock_counter = MagicMock()
        mock_slo = MagicMock()
        with (
            patch("app.services.observability.slo_metrics.COMPOSER_OUTCOME_TOTAL", mock_counter),
            patch("app.services.observability.slo_metrics.SLO_BREACH_TOTAL", mock_slo),
        ):
            observe_composer_outcome(composer_source=source, composer_notes=notes)

        # SLO breach should not be called for composer_fallback
        for call_args in mock_slo.labels.call_args_list:
            assert call_args != call(slo="composer_fallback"), (
                f"Expected no SLO breach for source={source!r} notes={notes!r}, "
                f"but SLO_BREACH_TOTAL.labels(slo='composer_fallback') was called"
            )


# ─────────────────────────────────────────────────────────────────────────────
# 2. Orchestrator path tests
#
# Uses the same helper pattern as test_orchestrator_uses_composer_when_flag_enabled.py:
# build the orchestrator with injected mocks via constructor args, then use
# patch() context managers for flag lookups.  No monkeypatch needed.
# ─────────────────────────────────────────────────────────────────────────────


_TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
_PROPERTY_CODE = "PROP-METRIC-001"


def _make_inbound(text: str = "Is the pool heated?") -> InboundGuestMessage:
    return InboundGuestMessage(
        message_id="MSG-METRIC-001",
        tenant_id=_TENANT,
        channel="email",
        source_provider="gmail",
        text=text,
        guest_name="Test Guest",
        guest_email="guest@example.com",
        property_code=_PROPERTY_CODE,
        received_at=datetime.now(timezone.utc),
        metadata={},
    )


def _make_decision(draft_text: str = "Pool hours are 8am-10pm.") -> AgentDecision:
    return AgentDecision(
        agent_name="HouseRulesAgent",
        intent_topic="house_rules",
        confidence=0.8,
        answer_summary="test",
        evidence_used=[],
        missing_info=[],
        risk_flags=[],
        recommended_action=RecommendedAction.DRAFT_ONLY,
        draft_text=draft_text,
        module_events=[],
    )


def _make_classification() -> MessageClassification:
    return MessageClassification(
        intent_type=IntentType.QUESTION,
        intent_topic="house_rules",
        confidence=0.85,
        urgency=Urgency.MEDIUM,
        reason="test",
    )


def _make_context() -> GuestContextBundle:
    return GuestContextBundle(
        tenant_id=_TENANT,
        property_code=_PROPERTY_CODE,
        property_id=None,
        guest_id=None,
        lifecycle=MessagingLifecycle.IN_STAY,
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
) -> ResponsePolicyDecision:
    return ResponsePolicyDecision(
        final_action=final_action,
        confidence=0.8,
        reasons=[],
        approval_mode_at_decision="required",
        blocking_escalation_id=None,
        module_events_to_dispatch=[],
    )


def _build_orch(
    decisions: Optional[List[AgentDecision]] = None,
    *,
    policy: Optional[ResponsePolicyDecision] = None,
    fast_path_stage: Any = None,
    context_builder: Any = None,
):
    """Build an isolated GuestMessageBrainOrchestrator for metric tests."""
    from app.services.messaging_brain.orchestrator import GuestMessageBrainOrchestrator

    decisions = decisions or [_make_decision()]
    classification = _make_classification()
    context = _make_context()
    policy = policy or _make_policy()

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

    if context_builder is None:
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
        def __init__(self, names):
            self.agent_names = names
            self.reason = "test"

    router.route = MagicMock(return_value=_RouteOutcome(agent_names))

    composer = MagicMock()
    composer.compose = AsyncMock()

    orch = GuestMessageBrainOrchestrator(
        router=router,
        intake=intake,
        context_builder=context_builder,
        policy=policy_agent,
        audit_writer=audit_writer,
        composer=composer,
        fast_path_stage=fast_path_stage,
        shadow_mode=False,
    )

    for name, decision in zip(agent_names, decisions):
        fake = MagicMock()
        fake.name = name
        fake.handles_topics = (classification.intent_topic,)
        fake.run = AsyncMock(return_value=decision)
        orch._specialists[name] = fake

    return orch


@pytest.mark.asyncio
async def test_metric_emitted_once_when_composer_flag_off():
    """When composer flag is OFF, observe_composer_outcome is called exactly
    once with composer_source='none' (which maps to fallback_cause='flag_off')."""
    orch = _build_orch()

    observe_mock = MagicMock()
    with (
        patch("app.services.messaging_brain.orchestrator.is_messaging_brain_llm_composer_enabled",
              new=AsyncMock(return_value=False)),
        patch("app.services.messaging_brain.orchestrator.is_messaging_brain_fast_path_stage_enabled",
              new=AsyncMock(return_value=False)),
        patch("app.services.messaging_brain.orchestrator.observe_composer_outcome", observe_mock),
    ):
        await orch.handle_inbound_message(_make_inbound(), db_session=AsyncMock())

    observe_mock.assert_called_once_with(
        composer_source="none",
        composer_notes=[],
    )


@pytest.mark.asyncio
async def test_metric_not_emitted_on_fast_path_early_return():
    """When fast-path stage fires and returns early (before step 6), the
    composer metric is NOT emitted."""
    from app.services.messaging_brain.stages.fast_path_stage import FastPathResult

    fast_path_stage = MagicMock()
    fast_path_stage.name = "FastPathStage"
    fast_path_stage.run = AsyncMock(return_value=FastPathResult(
        response_text="Pool hours are 8am-10pm.",
        confidence=0.95,
        confidence_source="fast_path_faq",
        final_action=RecommendedAction.DRAFT_ONLY,
        escalation_required=False,
        reason_for_escalation="",
        notes=["fast_path:faq_hit"],
    ))

    orch = _build_orch(fast_path_stage=fast_path_stage)

    observe_mock = MagicMock()
    with (
        patch("app.services.messaging_brain.orchestrator.is_messaging_brain_fast_path_stage_enabled",
              new=AsyncMock(return_value=True)),
        patch("app.services.messaging_brain.orchestrator.observe_composer_outcome", observe_mock),
    ):
        draft = await orch.handle_inbound_message(_make_inbound(), db_session=AsyncMock())

    assert draft is not None
    observe_mock.assert_not_called(), (
        "observe_composer_outcome must not fire on fast-path early return"
    )


@pytest.mark.asyncio
async def test_metric_not_emitted_on_pre_step6_exception():
    """When the pipeline throws before step 6 (e.g. context builder crash),
    observe_composer_outcome is NOT called — the pipeline exception handler
    returns a fallback draft, but no composer outcome was reached."""
    crashing_context_builder = MagicMock()
    crashing_context_builder.name = "MockContextBuilder"
    crashing_context_builder.build = AsyncMock(
        side_effect=RuntimeError("context builder exploded — pre-step-6")
    )

    orch = _build_orch(context_builder=crashing_context_builder)

    observe_mock = MagicMock()
    with (
        patch("app.services.messaging_brain.orchestrator.is_messaging_brain_fast_path_stage_enabled",
              new=AsyncMock(return_value=False)),
        patch("app.services.messaging_brain.orchestrator.observe_composer_outcome", observe_mock),
    ):
        draft = await orch.handle_inbound_message(_make_inbound(), db_session=AsyncMock())

    # Pipeline fell back gracefully — no composer reached
    assert draft is not None
    observe_mock.assert_not_called(), (
        "observe_composer_outcome must not fire when pipeline threw before step 6"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 3. Integration test — no-keys path produces fallback_cause=no_keys
# ─────────────────────────────────────────────────────────────────────────────


def test_integration_no_api_keys_produces_no_keys_cause():
    """When no ANTHROPIC_API_KEY or GROQ_API_KEY is configured and the composer
    is invoked, the resulting ComposerMetadata carries a 'composer_no_key:*'
    note, and observe_composer_outcome maps that to fallback_cause='no_keys'.

    This is a unit-level integration test: it drives observe_composer_outcome
    with the exact notes the LLMComposerAgent emits when keys are absent,
    verifying the full mapping chain without actually calling any LLM API.
    """
    # These are the exact note strings LLMComposerAgent emits when keys
    # are absent (confirmed from llm_composer_agent.py and the May 21-26
    # incident read-out).
    no_key_note_variants = [
        "composer_no_key:anthropic",
        "composer_no_key:groq",
        "composer_no_keys_configured",
    ]

    for note in no_key_note_variants:
        mock_counter = MagicMock()
        mock_slo = MagicMock()
        with (
            patch("app.services.observability.slo_metrics.COMPOSER_OUTCOME_TOTAL", mock_counter),
            patch("app.services.observability.slo_metrics.SLO_BREACH_TOTAL", mock_slo),
        ):
            observe_composer_outcome(
                composer_source="fallback_concatenation",
                composer_notes=[note],
            )

        mock_counter.labels.assert_called_once_with(
            composer_source="fallback_concatenation",
            fallback_cause="no_keys",
        ), f"Expected fallback_cause='no_keys' for note={note!r}"
        mock_slo.labels.assert_called_with(slo="composer_fallback"), (
            f"Expected SLO breach on no_keys for note={note!r}"
        )
