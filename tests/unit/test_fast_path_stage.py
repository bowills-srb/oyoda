from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.services.messaging_brain.orchestrator import GuestMessageBrainOrchestrator
from app.services.messaging_brain.stages.fast_path_stage import FastPathResult, FastPathStage
from app.services.orchestration.messaging_brain_contracts import (
    AgentAuditRecord,
    ClassifierMetadata,
    InboundGuestMessage,
    IntentType,
    MessageClassification,
    MessagingLifecycle,
    RecommendedAction,
    Urgency,
)


STAGE_SEAM = "app.services.messaging_brain.stages.fast_path_stage"
ORCH_SEAM = "app.services.messaging_brain.orchestrator"


def _make_inbound(*, text: str = "What's the wifi password?") -> InboundGuestMessage:
    message = InboundGuestMessage(
        message_id="MSG_FAST_001",
        tenant_id="11111111-1111-1111-1111-111111111111",
        channel="sms",
        source_provider="twilio",
        text=text,
        guest_name="Alex Guest",
        property_code="100SL2C",
        received_at=datetime.utcnow(),
        metadata={"context_adapter_overlay": {"access_info": {"support_phone": "(850) 555-0123"}}},
    )
    object.__setattr__(message, "lifecycle", MessagingLifecycle.IN_STAY)
    return message


def _set_identity(message: InboundGuestMessage, state: str) -> InboundGuestMessage:
    object.__setattr__(message, "identity", SimpleNamespace(state=state))
    return message


def _set_stay_dates(
    message: InboundGuestMessage,
    *,
    check_in: str = "2026-05-24",
    check_out: str = "2026-05-28",
) -> InboundGuestMessage:
    message.metadata["check_in_date"] = check_in
    message.metadata["check_out_date"] = check_out
    return message


def _set_session_token(
    message: InboundGuestMessage,
    token: str = "gh_test_123",
) -> InboundGuestMessage:
    object.__setattr__(message, "session_token", token)
    return message


def _make_classification(*, topic: str = "access") -> MessageClassification:
    return MessageClassification(
        intent_type=IntentType.QUESTION,
        intent_topic=topic,
        confidence=0.9,
        urgency=Urgency.LOW,
    )


@pytest.mark.asyncio
async def test_fast_path_stage_returns_none_for_access_and_house_rules_topics():
    """access / house_rules / general topics now fall through to the full LLM pipeline.
    The FAQ deterministic answerer was retired in Step 6A; only the escalation and
    gate-code deciders remain in FastPathStage."""
    stage = FastPathStage(escalation_detector=MagicMock(detect_escalation=MagicMock(return_value=None)))
    for topic in ("access", "house_rules", "general"):
        result = await stage.run(
            message=_make_inbound(),
            classification=_make_classification(topic=topic),
            db_session=MagicMock(),
        )
        assert result is None, f"Expected None for topic={topic!r} — falls through to LLM composer"



@pytest.mark.asyncio
async def test_fast_path_stage_escalates_first(monkeypatch):
    """Escalation fires before gate-code lookup (and before anything else)."""
    intercept = AsyncMock()
    monkeypatch.setattr(f"{STAGE_SEAM}.intercept_gate_code_request", intercept)

    detector = MagicMock()
    detector.detect_escalation.return_value = {
        "needed": True,
        "priority": "urgent",
        "reason": "safety",
    }
    stage = FastPathStage(escalation_detector=detector)
    result = await stage.run(
        message=_make_inbound(text="There is a fire in the kitchen."),
        classification=_make_classification(topic="emergency"),
        db_session=MagicMock(),
    )

    assert result is not None
    assert result.confidence_source == "escalation_routed"
    assert result.final_action == RecommendedAction.ESCALATE
    intercept.assert_not_awaited()


@pytest.mark.asyncio
async def test_fast_path_stage_gate_code_requires_identified_identity(monkeypatch):
    monkeypatch.setenv("ESCAPIA_API_KEY", "test-key")
    monkeypatch.setenv("FIRST_OPERATOR_COMPANY_ID", "11111111-1111-1111-1111-111111111111")
    intercept = AsyncMock(return_value="🔑 Your gate code is 4321")
    monkeypatch.setattr(f"{STAGE_SEAM}.intercept_gate_code_request", intercept)

    stage = FastPathStage(escalation_detector=MagicMock(detect_escalation=MagicMock(return_value=None)))
    message = _make_inbound(text="What's the gate code?")
    result = await stage.run(
        message=_set_identity(message, "pseudonymous"),
        classification=_make_classification(topic="access"),
        db_session=MagicMock(),
    )

    assert result is None
    intercept.assert_not_awaited()


@pytest.mark.asyncio
async def test_fast_path_stage_gate_code_intercept_fires(monkeypatch):
    """When identity is 'identified' and Escapia keys are set, the gate-code
    intercept fires and returns AUTO_SEND."""
    monkeypatch.setenv("ESCAPIA_API_KEY", "test-key")
    monkeypatch.setenv("FIRST_OPERATOR_COMPANY_ID", "11111111-1111-1111-1111-111111111111")
    intercept = AsyncMock(return_value="🔑 Your gate code is 4321")
    monkeypatch.setattr(f"{STAGE_SEAM}.intercept_gate_code_request", intercept)

    stage = FastPathStage(escalation_detector=MagicMock(detect_escalation=MagicMock(return_value=None)))
    message = _make_inbound(text="What's the code?")
    result = await stage.run(
        message=_set_session_token(_set_stay_dates(_set_identity(message, "identified"))),
        classification=_make_classification(topic="access"),
        db_session=MagicMock(),
    )

    assert result is not None
    assert result.confidence_source == "gate_code_intercept"
    assert result.final_action == RecommendedAction.AUTO_SEND
    intercept.assert_awaited_once()


@pytest.mark.asyncio
async def test_orchestrator_short_circuits_when_fast_path_hits(monkeypatch):
    captured: dict[str, AgentAuditRecord] = {}

    intake = MagicMock()
    intake.classify_with_metadata = AsyncMock(
        return_value=(
            _make_classification(topic="access"),
            ClassifierMetadata(classifier_source="test", provider_used=None, latency_ms=0),
        )
    )
    context_builder = MagicMock()
    context_builder.name = "ContextBuilderAgent"
    context_builder.build = AsyncMock()
    policy = MagicMock()
    policy.evaluate = AsyncMock()
    router = MagicMock()
    audit_writer = MagicMock()
    audit_writer.persist_inbound = AsyncMock(return_value=uuid4())

    async def _capture_write(record, **kwargs):
        captured["record"] = record

    audit_writer.write = AsyncMock(side_effect=_capture_write)

    fast_path_stage = MagicMock()
    fast_path_stage.name = "FastPathStage"
    fast_path_stage.run = AsyncMock(
        return_value=FastPathResult(
            response_text="The wifi password is sunset123.",
            confidence=0.95,
            confidence_source="gate_code_intercept",
            notes=["fast_path: gate_code_intercept"],
        )
    )

    monkeypatch.setattr(f"{ORCH_SEAM}.is_messaging_brain_fast_path_stage_enabled", AsyncMock(return_value=True))

    orch = GuestMessageBrainOrchestrator(
        router=router,
        intake=intake,
        context_builder=context_builder,
        policy=policy,
        audit_writer=audit_writer,
        fast_path_stage=fast_path_stage,
    )

    draft = await orch.handle_inbound_message(_make_inbound(), db_session=MagicMock())

    assert draft.response_text == "The wifi password is sunset123."
    context_builder.build.assert_not_awaited()
    policy.evaluate.assert_not_awaited()
    fast_path_stage.run.assert_awaited_once()
    assert captured["record"].final_response.response_text == "The wifi password is sunset123."
    assert "FastPathStage" in captured["record"].agent_path
