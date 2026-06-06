"""
Verify that GuestMessageBrainOrchestrator emits canonical knowledge-gap
records from specialist decisions only when the decision materially
deflected the guest.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.messaging_brain.orchestrator import GuestMessageBrainOrchestrator
from app.services.orchestration.messaging_brain_contracts import (
    AgentDecision,
    ClassifierMetadata,
    GuestContextBundle,
    InboundGuestMessage,
    IntentType,
    MessageClassification,
    MessagingLifecycle,
    OutboundIntent,
    RecommendedAction,
    ResponsePolicyDecision,
    Urgency,
)


_TENANT = "11111111-1111-1111-1111-111111111111"
_PROPERTY_CODE = "GULF_VIEW_204"


def _make_inbound(
    *,
    text: str = "is the property pet friendly?",
    message_id: str = "EMAIL_001",
) -> InboundGuestMessage:
    message = InboundGuestMessage(
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
    # The orchestrator currently reads lifecycle from the inbound shim.
    object.__setattr__(message, "lifecycle", MessagingLifecycle.PRE_BOOKING)
    return message


def _make_decision(
    *,
    agent_name: str = "HouseRulesAgent",
    intent_topic: str = "house_rules",
    missing_info: Optional[List[str]] = None,
    recommended_action: RecommendedAction = RecommendedAction.DRAFT_ONLY,
    confidence: float = 0.6,
    draft_text: str = "I'm confirming the pet policy now.",
    evidence_used: Optional[List[str]] = None,
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


def _make_classification(intent_topic: str = "house_rules") -> MessageClassification:
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
) -> GuestMessageBrainOrchestrator:
    classification = classification or _make_classification()
    policy = policy or _make_policy()
    context = _make_context()

    intake = MagicMock()
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
    context_builder.build = AsyncMock(return_value=context)

    audit_writer = MagicMock()
    audit_writer.persist_inbound = AsyncMock(return_value=uuid4())
    audit_writer.write = AsyncMock()

    policy_agent = MagicMock()
    policy_agent.evaluate = AsyncMock(return_value=policy)

    router = MagicMock()
    agent_names = [f"FakeAgent{i}" for i in range(len(decisions))]

    class _RouteOutcome:
        def __init__(self, names: List[str]) -> None:
            self.agent_names = names
            self.reason = "test route"

    router.route = MagicMock(return_value=_RouteOutcome(agent_names))

    orchestrator = GuestMessageBrainOrchestrator(
        router=router,
        intake=intake,
        context_builder=context_builder,
        policy=policy_agent,
        audit_writer=audit_writer,
        shadow_mode=False,
    )

    for name, decision in zip(agent_names, decisions):
        specialist = MagicMock()
        specialist.name = name
        specialist.handles_topics = (classification.intent_topic,)
        specialist.run = AsyncMock(return_value=decision)
        orchestrator._specialists[name] = specialist

    return orchestrator


@pytest.mark.asyncio
async def test_emits_gap_for_draft_only_with_missing_info():
    decision = _make_decision(
        intent_topic="house_rules",
        missing_info=["pet_policy"],
        recommended_action=RecommendedAction.DRAFT_ONLY,
        draft_text="I'm confirming the pet policy now.",
        confidence=0.55,
        evidence_used=[],
    )
    orchestrator = _build_orchestrator_with_decisions([decision])
    inbound = _make_inbound(text="is this property pet friendly?")

    with patch(
        "app.services.messaging_brain.orchestrator.schedule_gap_record",
        new=MagicMock(),
    ) as recorder:
        await orchestrator.handle_inbound_message(inbound, db_session=None)

    assert recorder.call_count == 1
    call = recorder.call_args
    assert call.kwargs["tenant_id"] == _TENANT
    assert call.kwargs["question"] == "is this property pet friendly?"
    assert call.kwargs["answer_attempt"] == "I'm confirming the pet policy now."
    assert call.kwargs["confidence_score"] == 0.55
    assert call.kwargs["used_kb_chunks"] is False
    assert call.kwargs["was_deflected"] is True
    assert call.kwargs["property_code"] == _PROPERTY_CODE
    assert call.kwargs["stage"] == "pre_booking"
    assert call.kwargs["channel"] == "email"
    assert call.kwargs["source"] == "messaging_brain_orchestrator"
    assert call.kwargs["detected_intent"] == "house_rules"
    assert call.kwargs["metadata"]["agent_name"] == "HouseRulesAgent"
    assert call.kwargs["metadata"]["missing_info"] == ["pet_policy"]


@pytest.mark.asyncio
async def test_skips_emission_when_missing_info_only_contains_stub_sentinel():
    decision = _make_decision(
        intent_topic="general",
        missing_info=["__stub_specialist__"],
        recommended_action=RecommendedAction.DRAFT_ONLY,
    )
    orchestrator = _build_orchestrator_with_decisions([decision])

    with patch(
        "app.services.messaging_brain.orchestrator.schedule_gap_record",
        new=MagicMock(),
    ) as recorder:
        await orchestrator.handle_inbound_message(_make_inbound(), db_session=None)

    recorder.assert_not_called()


@pytest.mark.asyncio
async def test_skips_emission_when_recommended_action_is_auto_send():
    decision = _make_decision(
        intent_topic="house_rules",
        missing_info=["secondary_pet_fee_detail"],
        recommended_action=RecommendedAction.AUTO_SEND,
        confidence=0.92,
    )
    orchestrator = _build_orchestrator_with_decisions([decision])

    with patch(
        "app.services.messaging_brain.orchestrator.schedule_gap_record",
        new=MagicMock(),
    ) as recorder:
        await orchestrator.handle_inbound_message(_make_inbound(), db_session=None)

    recorder.assert_not_called()


@pytest.mark.asyncio
async def test_filters_stub_sentinel_but_emits_for_real_missing_info():
    decision = _make_decision(
        intent_topic="access",
        missing_info=["__stub_specialist__", "door_code"],
        recommended_action=RecommendedAction.DRAFT_ONLY,
    )
    orchestrator = _build_orchestrator_with_decisions([decision])

    with patch(
        "app.services.messaging_brain.orchestrator.schedule_gap_record",
        new=MagicMock(),
    ) as recorder:
        await orchestrator.handle_inbound_message(
            _make_inbound(text="what is the door code"),
            db_session=None,
        )

    assert recorder.call_count == 1
    assert recorder.call_args.kwargs["metadata"]["missing_info"] == ["door_code"]


@pytest.mark.asyncio
async def test_emits_one_gap_per_emittable_decision():
    decisions = [
        _make_decision(agent_name="A1", intent_topic="house_rules", missing_info=["pet_policy"]),
        _make_decision(agent_name="A2", intent_topic="access", missing_info=["door_code"]),
        _make_decision(agent_name="A3", intent_topic="general", missing_info=["__stub_specialist__"]),
    ]
    orchestrator = _build_orchestrator_with_decisions(decisions)

    with patch(
        "app.services.messaging_brain.orchestrator.schedule_gap_record",
        new=MagicMock(),
    ) as recorder:
        await orchestrator.handle_inbound_message(_make_inbound(), db_session=None)

    assert recorder.call_count == 2


@pytest.mark.asyncio
async def test_records_audit_note_with_count_and_topics():
    decisions = [
        _make_decision(agent_name="A1", intent_topic="house_rules", missing_info=["pet_policy"]),
        _make_decision(agent_name="A2", intent_topic="access", missing_info=["door_code"]),
    ]
    orchestrator = _build_orchestrator_with_decisions(decisions)
    captured_record = {}

    async def _capture_write(record, *, db_session, original_message):
        captured_record["record"] = record

    orchestrator._audit.write = AsyncMock(side_effect=_capture_write)

    with patch(
        "app.services.messaging_brain.orchestrator.schedule_gap_record",
        new=MagicMock(),
    ):
        await orchestrator.handle_inbound_message(_make_inbound(), db_session=None)

    record = captured_record["record"]
    matching = [note for note in record.notes if note.startswith("kb_gaps_emitted:")]
    assert len(matching) == 1
    assert "count=2" in matching[0]
    assert "['access', 'house_rules']" in matching[0]


@pytest.mark.asyncio
async def test_no_emission_on_proactive_path():
    decision = _make_decision(
        intent_topic="welcome",
        missing_info=["arrival_instructions"],
        recommended_action=RecommendedAction.DRAFT_ONLY,
    )
    orchestrator = _build_orchestrator_with_decisions([decision])
    orchestrator._context_builder.build_for_proactive = AsyncMock(return_value=_make_context())

    intent = OutboundIntent(
        intent_id=str(uuid4()),
        tenant_id=_TENANT,
        trigger_type="welcome",
        guest_id="",
        guest_email="jane@example.com",
        guest_phone="",
        guest_name="Jane Guest",
        reservation_id="",
        property_id="",
        property_code=_PROPERTY_CODE,
        session_token="",
        payload={},
    )

    with patch(
        "app.services.messaging_brain.orchestrator.schedule_gap_record",
        new=MagicMock(),
    ) as recorder:
        await orchestrator.handle_proactive_trigger(intent, db_session=None)

    recorder.assert_not_called()


@pytest.mark.asyncio
async def test_emission_failure_does_not_abort_pipeline():
    decision = _make_decision(missing_info=["pet_policy"])
    orchestrator = _build_orchestrator_with_decisions([decision])

    with patch(
        "app.services.messaging_brain.orchestrator.schedule_gap_record",
        side_effect=RuntimeError("scheduler down"),
    ):
        draft = await orchestrator.handle_inbound_message(_make_inbound(), db_session=None)

    assert draft is not None
    assert draft.response_text
