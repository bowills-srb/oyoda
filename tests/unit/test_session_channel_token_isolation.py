from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest

from app.services.messaging.identity_resolver import GuestIdentityResolution
from app.services.messaging_brain import GuestMessageBrainOrchestrator
from app.services.messaging_brain.session_channel_adapter import (
    run_session_channel_message,
)
from app.services.messaging_brain.stages.fast_path_stage import FastPathResult
from app.services.orchestration.messaging_brain_contracts import (
    AgentAuditRecord,
    GuestContextBundle,
    GuestResponseDraft,
    InboundGuestMessage,
    IntentType,
    MessageClassification,
    MessagingLifecycle,
    RecommendedAction,
    ResponsePolicyDecision,
    Urgency,
)


def _make_session_row(*, token: str, guest_name: str, guest_email: str):
    return SimpleNamespace(
        tenant_id="tenant-123",
        token=token,
        phase="in_stay",
        property_code="LANIER_001",
        property_name="Lanier Beach House",
        property_context={"support_phone": "(850) 999-0000"},
        operator_id="op-123",
        guest_name=guest_name,
        guest_phone="+15555550123",
        guest_email=guest_email,
        reservation_id=f"res-{token[-1]}",
        property_id=str(uuid4()),
        check_in=SimpleNamespace(isoformat=lambda: "2026-05-22"),
        check_out=SimpleNamespace(isoformat=lambda: "2026-05-26"),
    )


class _ResolvedPropertyContext:
    def to_dict(self):
        return {
            "wifi_network": "Beach_5G",
            "wifi_password": "surf2024",
            "door_code": "9999",
            "check_in_time": "4:00 PM",
            "check_out_time": "10:00 AM",
            "support_phone": "(850) 999-0000",
        }


def _make_inbound_message(
    *,
    token: str,
    guest_name: str,
    guest_email: str,
    message_id: str,
    text: str,
) -> InboundGuestMessage:
    return InboundGuestMessage(
        message_id=message_id,
        tenant_id="11111111-1111-1111-1111-111111111111",
        channel="sms",
        source_provider="twilio_sms",
        text=text,
        guest_name=guest_name,
        guest_email=guest_email,
        guest_phone="+15555550123",
        reservation_id=f"res-{token[-1]}",
        property_id="11111111-2222-3333-4444-555555555555",
        property_code="LANIER_001",
        lifecycle=MessagingLifecycle.IN_STAY,
        thread_id=token,
        session_token=token,
        identity=GuestIdentityResolution(
            state="identified",
            reservation_id=f"res-{token[-1]}",
            session_token=token,
            guest_name=guest_name,
            guest_email=guest_email,
            resolution_source="session_token",
            confidence=0.99,
            property_code="LANIER_001",
            check_in_date="2026-05-22",
            check_out_date="2026-05-26",
        ),
    )


def _make_context(message: InboundGuestMessage) -> GuestContextBundle:
    return GuestContextBundle(
        tenant_id=message.tenant_id,
        property_id=message.property_id,
        property_code=message.property_code,
        reservation_id=message.reservation_id,
        lifecycle=MessagingLifecycle.IN_STAY,
        property_facts={
            "hvac_info": "Thermostat is in the hallway.",
            "wifi": "Beach_5G / surf2024",
        },
        reservation_facts={
            "guest_name": message.guest_name,
            "reservation_id": message.reservation_id,
        },
        evidence_keys=["property_facts", "property_facts.hvac_info", "property_facts.wifi"],
    )


class _RecordingAuditWriter:
    def __init__(self) -> None:
        self.records: list[AgentAuditRecord] = []

    async def persist_inbound(self, db_session, message: InboundGuestMessage) -> UUID:
        return uuid4()

    async def write(self, record: AgentAuditRecord, *, db_session=None, original_message=None) -> None:
        self.records.append(record.model_copy(deep=True))


class _FakeIntake:
    name = "FakeIntake"

    async def classify(self, message: InboundGuestMessage, db_session=None) -> MessageClassification:
        text = (message.text or "").lower()
        if "ac" in text:
            return MessageClassification(
                intent_type=IntentType.PROBLEM,
                intent_topic="maintenance",
                confidence=0.95,
                urgency=Urgency.MEDIUM,
                reason="maintenance keyword",
            )
        return MessageClassification(
            intent_type=IntentType.QUESTION,
            intent_topic="general",
            confidence=0.92,
            urgency=Urgency.LOW,
            reason="wifi fast-path test",
        )


class _FakeContextBuilder:
    name = "FakeContextBuilder"

    async def build(self, message: InboundGuestMessage, classification: MessageClassification, *, db_session=None) -> GuestContextBundle:
        return _make_context(message)


class _FakePolicy:
    name = "FakePolicy"

    async def evaluate(
        self,
        *,
        message: InboundGuestMessage,
        context: GuestContextBundle,
        decisions,
        triggered_by_message_id,
        db_session=None,
    ) -> ResponsePolicyDecision:
        module_events = []
        for decision in decisions:
            module_events.extend(decision.module_events)
        return ResponsePolicyDecision(
            final_action=RecommendedAction.DRAFT_ONLY,
            confidence=max((decision.confidence for decision in decisions), default=0.0),
            reasons=["test review mode"],
            approval_mode_at_decision="required",
            module_events_to_dispatch=module_events,
        )


class _SelectiveFastPathStage:
    name = "FastPathStage"

    async def run(self, *, message: InboundGuestMessage, classification: MessageClassification, db_session=None):
        if "wifi" not in (message.text or "").lower():
            return None
        return FastPathResult(
            response_text="The wifi password is surf2024.",
            confidence=0.95,
            confidence_source="gate_code_intercept",
            final_action=RecommendedAction.AUTO_SEND,
            notes=["fast_path: gate_code_intercept"],
        )


def _build_real_orchestrator(audit_writer: _RecordingAuditWriter) -> GuestMessageBrainOrchestrator:
    return GuestMessageBrainOrchestrator(
        intake=_FakeIntake(),
        context_builder=_FakeContextBuilder(),
        policy=_FakePolicy(),
        audit_writer=audit_writer,
        fast_path_stage=_SelectiveFastPathStage(),
    )


@pytest.mark.asyncio
async def test_run_session_channel_message_keeps_tokens_isolated():
    token_a = "gh_alice_123"
    token_b = "gh_bob_456"
    row_a = _make_session_row(token=token_a, guest_name="Alice", guest_email="alice@example.com")
    row_b = _make_session_row(token=token_b, guest_name="Bob", guest_email="bob@example.com")
    resolved = _ResolvedPropertyContext()
    captured = []

    class _FakeOrchestrator:
        async def handle_inbound_message(self, message, *, db_session, shadow_mode):
            captured.append(message)
            if "wifi" in (message.text or "").lower():
                return GuestResponseDraft(
                    response_text="The wifi password is surf2024.",
                    confidence=0.95,
                    confidence_source="gate_code_intercept",
                    final_action=RecommendedAction.AUTO_SEND,
                )
            return GuestResponseDraft(
                response_text="I've alerted the team about the AC issue.",
                confidence=0.82,
                final_action=RecommendedAction.DRAFT_ONLY,
            )

    async def _fake_resolve_identity(*, session_token: str, **kwargs):
        return GuestIdentityResolution(
            state="identified",
            reservation_id=f"res-{session_token[-1]}",
            session_token=session_token,
            guest_name="Alice" if session_token == token_a else "Bob",
            guest_email="alice@example.com" if session_token == token_a else "bob@example.com",
            resolution_source="session_token",
            confidence=0.99,
            property_code="LANIER_001",
            check_in_date="2026-05-22",
            check_out_date="2026-05-26",
        )

    with patch(
        "app.services.messaging_brain.session_channel_adapter.get_messaging_brain_orchestrator",
        return_value=_FakeOrchestrator(),
    ), patch(
        "app.services.concierge.property_router.get_property_router",
        return_value=SimpleNamespace(resolve=AsyncMock(return_value=resolved)),
    ), patch(
        "app.services.messaging_brain.session_channel_adapter.resolve_guest_identity",
        new=_fake_resolve_identity,
    ):
        result_a = await run_session_channel_message(
            message_text="The AC is broken in the primary bedroom",
            db_session=AsyncMock(),
            db_row=row_a,
            session_tenant_id=row_a.tenant_id,
            token=token_a,
            channel="sms",
            source_provider="twilio_sms",
        )
        result_b = await run_session_channel_message(
            message_text="What's the wifi password?",
            db_session=AsyncMock(),
            db_row=row_b,
            session_tenant_id=row_b.tenant_id,
            token=token_b,
            channel="sms",
            source_provider="twilio_sms",
        )

    assert len(captured) == 2
    first, second = captured
    assert first.session_token == token_a
    assert second.session_token == token_b
    assert first.thread_id == token_a
    assert second.thread_id == token_b
    assert first.guest_name == "Alice"
    assert second.guest_name == "Bob"
    assert first.identity.session_token == token_a
    assert second.identity.session_token == token_b
    assert first.property_code == second.property_code == "LANIER_001"
    assert result_a.quick_answer_used is False
    assert result_b.quick_answer_used is True
    assert result_b.quick_answer_source == "gate_code"


@pytest.mark.asyncio
async def test_audit_records_isolated_across_tokens():
    token_a = "gh_alice_123"
    token_b = "gh_bob_456"
    inbound_a = _make_inbound_message(
        token=token_a,
        guest_name="Alice",
        guest_email="alice@example.com",
        message_id="MSG_ALICE_AC",
        text="The AC is broken in the master bedroom",
    )
    inbound_b = _make_inbound_message(
        token=token_b,
        guest_name="Bob",
        guest_email="bob@example.com",
        message_id="MSG_BOB_WIFI",
        text="What's the wifi password?",
    )
    audit_writer = _RecordingAuditWriter()
    orchestrator = _build_real_orchestrator(audit_writer)

    auto_track_mock = AsyncMock(
        return_value={"created": {"event_id": "evt-123"}, "resolved": None}
    )
    work_order_mock = AsyncMock(
        return_value={"work_order_id": "wo-123", "status": "opened"}
    )

    with patch(
        "app.services.messaging_brain.orchestrator.is_messaging_brain_fast_path_stage_enabled",
        new=AsyncMock(return_value=True),
    ), patch(
        "app.services.messaging_brain.orchestrator.load_brain_router_threshold",
        new=AsyncMock(return_value=0.55),
    ), patch(
        "app.services.messaging_brain.orchestrator.is_messaging_brain_llm_composer_enabled",
        new=AsyncMock(return_value=False),
    ), patch(
        "app.services.messaging_brain.orchestrator.schedule_gap_record",
        new=lambda *args, **kwargs: None,
    ), patch(
        "app.services.messaging_brain.modules.maintenance_module.get_concierge_maintenance_service",
        return_value=SimpleNamespace(auto_track_from_message=auto_track_mock),
    ), patch(
        "app.services.messaging_brain.modules.maintenance_module.get_operator_work_order_service",
        return_value=SimpleNamespace(create_or_refresh_work_order=work_order_mock),
    ):
        await orchestrator.handle_inbound_message(
            message=inbound_a,
            db_session=AsyncMock(),
            shadow_mode=False,
        )
        await orchestrator.handle_inbound_message(
            message=inbound_b,
            db_session=AsyncMock(),
            shadow_mode=False,
        )

    assert len(audit_writer.records) == 2
    audit_a = next(r for r in audit_writer.records if r.message_id == inbound_a.message_id)
    audit_b = next(r for r in audit_writer.records if r.message_id == inbound_b.message_id)

    assert [d.agent_name for d in audit_a.decisions] == ["MaintenanceAgent"]
    assert all(d.agent_name != "MaintenanceAgent" for d in audit_b.decisions)
    assert audit_a.final_response is not None
    assert audit_b.final_response is not None
    assert audit_a.final_response.contributing_agents == ["MaintenanceAgent"]
    assert audit_b.final_response.confidence_source == "gate_code_intercept"
    assert audit_a.message_id == inbound_a.message_id
    assert audit_b.message_id == inbound_b.message_id
    assert all(ev.payload.get("source_message_id") == inbound_a.message_id for ev in audit_a.module_events)
    assert not audit_b.module_events


@pytest.mark.asyncio
async def test_module_events_isolated_across_tokens():
    token_a = "gh_alice_123"
    token_b = "gh_bob_456"
    inbound_a = _make_inbound_message(
        token=token_a,
        guest_name="Alice",
        guest_email="alice@example.com",
        message_id="MSG_ALICE_AC",
        text="The AC is broken in the master bedroom",
    )
    inbound_b = _make_inbound_message(
        token=token_b,
        guest_name="Bob",
        guest_email="bob@example.com",
        message_id="MSG_BOB_WIFI",
        text="What's the wifi password?",
    )
    audit_writer = _RecordingAuditWriter()
    orchestrator = _build_real_orchestrator(audit_writer)

    auto_track_mock = AsyncMock(
        return_value={"created": {"event_id": "evt-123"}, "resolved": None}
    )
    work_order_mock = AsyncMock(
        return_value={"work_order_id": "wo-123", "status": "opened"}
    )

    with patch(
        "app.services.messaging_brain.orchestrator.is_messaging_brain_fast_path_stage_enabled",
        new=AsyncMock(return_value=True),
    ), patch(
        "app.services.messaging_brain.orchestrator.load_brain_router_threshold",
        new=AsyncMock(return_value=0.55),
    ), patch(
        "app.services.messaging_brain.orchestrator.is_messaging_brain_llm_composer_enabled",
        new=AsyncMock(return_value=False),
    ), patch(
        "app.services.messaging_brain.orchestrator.schedule_gap_record",
        new=lambda *args, **kwargs: None,
    ), patch(
        "app.services.messaging_brain.modules.maintenance_module.get_concierge_maintenance_service",
        return_value=SimpleNamespace(auto_track_from_message=auto_track_mock),
    ), patch(
        "app.services.messaging_brain.modules.maintenance_module.get_operator_work_order_service",
        return_value=SimpleNamespace(create_or_refresh_work_order=work_order_mock),
    ):
        await orchestrator.handle_inbound_message(
            message=inbound_a,
            db_session=AsyncMock(),
            shadow_mode=False,
        )
        await orchestrator.handle_inbound_message(
            message=inbound_b,
            db_session=AsyncMock(),
            shadow_mode=False,
        )

    assert auto_track_mock.await_count == 1
    assert work_order_mock.await_count == 1

    payload = work_order_mock.await_args.kwargs["payload"]
    assert payload["reservation_id"] == inbound_a.reservation_id
    assert payload["source_message_id"] == inbound_a.message_id
    assert payload["reservation_id"] != inbound_b.reservation_id
    assert payload["source_message_id"] != inbound_b.message_id
