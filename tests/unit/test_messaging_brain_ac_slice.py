"""
test_messaging_brain_ac_slice.py — Phase 1.3a verification gates.

The AC vertical slice: a guest sends "the AC is broken" via SMS, the brain
runs the full pipeline (real agents + module dispatch), and we verify
seven invariants:

  1. Full slice: classification → maintenance, ModuleEvent emitted,
     evidence cited from context, work order created via module dispatch
  2. Evidence-when-present: when context has hvac evidence, it gets cited
  3. Evidence-when-absent: when context has no hvac evidence, agent
     emits missing_info but still runs the module
  4. Ordering: persist_inbound completes BEFORE policy.evaluate runs
     (Rule 1 — autonomy_gate needs the internal message UUID)
  5. No-dispatch-on-ESCALATE: when policy escalates, NO module call
  6. Shadow mode: modules skip side effects, audit still written,
     concierge_event_id link is preserved in the would-have payload
  7. Linking: through full live pipeline, the work order's
     payload_json["concierge_event_id"] references the concierge event

Each test injects mocks for the existing services (autonomy_gate,
knowledge_service, concierge_maintenance_service, work_order_service,
message_event_store) so the brain runs in isolation against typed
fakes — no DB required.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.services.messaging.autonomy_gate import (
    AutonomyDecision,
    GateResult,
)
from app.services.messaging_brain import (
    ContextBuilderAgent,
    GuestMessageBrainOrchestrator,
    MaintenanceModule,
    ModuleRegistry,
)
from app.services.orchestration.messaging_brain_contracts import (
    GuestContextBundle,
    InboundGuestMessage,
    IntentType,
    MessagingLifecycle,
    MessageClassification,
    RecommendedAction,
    Urgency,
)


# ─────────────────────────────────────────────────────────────────────────────
# Test helpers
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class _LegacyKnowledgeFake:
    """Mimics the _LegacyKnowledgeCompat shape ContextBuilderAgent reads."""
    property_external_id: Optional[str] = None
    facts: dict = None  # type: ignore[assignment]
    sections: dict = None  # type: ignore[assignment]
    faq: list = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.facts = self.facts or {}
        self.sections = self.sections or {}
        self.faq = self.faq or []


def _make_inbound(
    text: str = "the AC is broken in the master bedroom",
    message_id: str = "SMS_AC_001",
    tenant_id: str = "11111111-1111-1111-1111-111111111111",
    property_code: str = "GULF_VIEW_204",
    property_id: Optional[str] = "22222222-2222-2222-2222-222222222222",
) -> InboundGuestMessage:
    return InboundGuestMessage(
        message_id=message_id,
        tenant_id=tenant_id,
        channel="sms",
        source_provider="twilio",
        text=text,
        guest_phone="+18505551234",
        guest_name="Alex Guest",
        property_code=property_code,
        property_id=property_id,
        reservation_id="resv_xyz",
    )


def _knowledge_with_hvac() -> _LegacyKnowledgeFake:
    return _LegacyKnowledgeFake(
        property_external_id="GULF_VIEW_204",
        facts={"check_in": "4pm", "check_out": "10am",
               "wifi": "GuestNet / pass: beach123"},
        faq=[
            {"question": "How does the AC work?",
             "answer": "Thermostat is in the hallway. Set to 72°F."},
        ],
    )


def _knowledge_empty() -> _LegacyKnowledgeFake:
    return _LegacyKnowledgeFake(property_external_id="GULF_VIEW_204")


def _make_persisted_uuid() -> UUID:
    return uuid4()


def _bundle_from_legacy_fake(
    knowledge: _LegacyKnowledgeFake,
    *,
    tenant_id: str,
    property_id: Optional[str],
    property_code: str,
    reservation_id: str,
    guest_id: Optional[str],
) -> GuestContextBundle:
    property_facts: Dict[str, Any] = {}
    property_knowledge: Dict[str, Any] = {}
    evidence_keys: List[str] = []

    if knowledge.facts:
        property_facts.update(knowledge.facts)
    if knowledge.faq:
        faq_entries = []
        for item in knowledge.faq:
            question = str(item.get("question") or "")
            answer = str(item.get("answer") or "")
            faq_entries.append({"question": question, "answer": answer})
            haystack = f"{question} {answer}".lower()
            if "ac" in haystack or "a/c" in haystack or "thermostat" in haystack or "hvac" in haystack:
                property_facts["hvac_info"] = answer or question
        property_knowledge["faq"] = faq_entries
        property_knowledge["faq_count"] = len(faq_entries)
    if property_facts:
        evidence_keys.append("property_facts")
        if "hvac_info" in property_facts:
            evidence_keys.append("property_facts.hvac_info")
    if property_knowledge:
        evidence_keys.append("property_knowledge")

    return GuestContextBundle(
        tenant_id=tenant_id,
        property_id=property_id,
        property_code=property_code,
        reservation_id=reservation_id,
        guest_id=guest_id,
        lifecycle=MessagingLifecycle.IN_STAY,
        property_facts=property_facts,
        property_knowledge=property_knowledge,
        guidebook_knowledge={},
        guidebook_richness={},
        guidebook_evidence=[],
        learned_preferences_block="",
        operator_policies={},
        operator_guidance="",
        reservation_facts={},
        house_rules={},
        access_info={},
        maintenance_status={},
        local_guidebook_facts={},
        market_signals={},
        prior_guest_messages=[],
        operator_commitments=[],
        evidence_keys=evidence_keys,
        missing_context=[] if property_knowledge else ["no_knowledge_for_property"],
    )


# ─────────────────────────────────────────────────────────────────────────────
# Patch fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def patch_external_services():
    """Patch every external service the brain calls so tests run in isolation.

    Yields a dict of MagicMock/AsyncMock handles so individual tests can
    customize return values, raise exceptions, or assert call ordering.

    Patched targets:
      - persist_canonical_inbound_message — audit writer's persist call
      - update_normalization_outcome — audit writer's outcome call
      - autonomy_gate.evaluate — policy gate
      - ContextBuilderAgent.build — context builder
      - ConciergeMaintenanceService.auto_track_from_message — concierge tracking
      - OperatorWorkOrderService.create_or_refresh_work_order — work order
    """
    persisted_uuid = _make_persisted_uuid()

    persist_mock = AsyncMock(return_value={
        "normalization_id": str(uuid4()),
        "message_id": str(persisted_uuid),
        "conversation_id": str(uuid4()),
        "channel_id": str(uuid4()),
    })
    update_mock = AsyncMock(return_value=None)

    gate_mock = AsyncMock(return_value=GateResult(
        decision=AutonomyDecision.REVIEW,
        reason="default test: review mode",
        approval_mode_at_decision="required",
    ))
    brain_router_threshold_mock = AsyncMock(return_value=0.55)
    prebooking_threshold_mock = AsyncMock(return_value=0.70)

    knowledge_mock = AsyncMock(return_value=_knowledge_with_hvac())
    build_context_mock = AsyncMock()

    async def _build_context_side_effect(
        message: InboundGuestMessage,
        classification: MessageClassification,
        *,
        db_session: Any,
    ) -> GuestContextBundle:
        knowledge = await knowledge_mock()
        return _bundle_from_legacy_fake(
            knowledge,
            tenant_id=message.tenant_id,
            property_id=message.property_id,
            property_code=message.property_code or "",
            reservation_id=message.reservation_id,
            guest_id=message.guest_id,
        )

    build_context_mock.side_effect = _build_context_side_effect

    concierge_event_id = str(uuid4())
    auto_track_mock = AsyncMock(return_value={
        "created": {
            "event_id": concierge_event_id,
            "category": "hvac",
            "severity": "medium",
            "status": "open",
        },
        "resolved": None,
    })

    send_alert_mock = AsyncMock(return_value=None)
    alert_router_mock = MagicMock(send_alert=send_alert_mock)

    work_order_id = str(uuid4())
    work_order_mock = AsyncMock(return_value={
        "work_order_id": work_order_id,
        "status": "opened",
        "verification_state": "pending",
        "invoice_state": "not_received",
    })

    with patch(
        "app.services.messaging_brain.audit.persist_canonical_inbound_message",
        new=persist_mock,
    ), patch(
        "app.services.messaging_brain.audit.update_normalization_outcome",
        new=update_mock,
    ), patch(
        "app.services.messaging_brain.agents.response_policy_agent.autonomy_evaluate",
        new=gate_mock,
    ), patch(
        "app.services.messaging_brain.orchestrator.load_brain_router_threshold",
        new=brain_router_threshold_mock,
    ), patch(
        "app.services.messaging_brain.orchestrator.load_prebooking_escalation_threshold",
        new=prebooking_threshold_mock,
    ), patch.object(
        ContextBuilderAgent,
        "build",
        new=build_context_mock,
    ), patch(
        "app.services.messaging_brain.modules.maintenance_module."
        "get_concierge_maintenance_service",
        return_value=MagicMock(
            auto_track_from_message=auto_track_mock,
        ),
    ), patch(
        "app.services.messaging_brain.modules.maintenance_module."
        "get_operator_work_order_service",
        return_value=MagicMock(
            create_or_refresh_work_order=work_order_mock,
        ),
    ), patch(
        "app.services.messaging_brain.modules.maintenance_module.get_alert_router",
        return_value=alert_router_mock,
    ):
        yield {
            "persist": persist_mock,
            "update_outcome": update_mock,
            "gate": gate_mock,
            "brain_router_threshold": brain_router_threshold_mock,
            "prebooking_threshold": prebooking_threshold_mock,
            "knowledge": knowledge_mock,
            "build_context": build_context_mock,
            "auto_track": auto_track_mock,
            "work_order": work_order_mock,
            "send_alert": send_alert_mock,
            "persisted_uuid": persisted_uuid,
            "concierge_event_id": concierge_event_id,
            "work_order_id": work_order_id,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_full_slice_ac_message_runs_pipeline_end_to_end(
    patch_external_services,
):
    """Test 1: Full AC slice — pipeline runs, classifies as maintenance,
    emits hvac module event, dispatches to MaintenanceModule, returns
    a draft."""
    mocks = patch_external_services
    orch = GuestMessageBrainOrchestrator()
    inbound = _make_inbound()

    draft = await orch.handle_inbound_message(
        inbound, db_session=MagicMock(),
    )

    # Pipeline produced a real draft
    assert draft is not None
    assert draft.final_action == RecommendedAction.DRAFT_ONLY
    assert "team" in draft.response_text.lower()
    assert "MaintenanceAgent" in draft.contributing_agents

    # All external services called
    assert mocks["persist"].await_count == 1
    assert mocks["knowledge"].await_count == 1
    assert mocks["gate"].await_count == 1
    assert mocks["auto_track"].await_count == 1
    assert mocks["work_order"].await_count == 1
    # Operator alert fired once (notify-only model)
    assert mocks["send_alert"].await_count == 1
    alert_call = mocks["send_alert"].await_args
    from app.services.messaging.operator_alerts import AlertType
    assert alert_call.kwargs.get("alert_type") == AlertType.MAINTENANCE

    # Audit writer captured the full record
    audit_record = orch._audit.last_record
    assert audit_record is not None
    assert audit_record.classification.intent_topic == "maintenance"
    assert audit_record.classification.intent_type == IntentType.PROBLEM
    assert audit_record.classification.urgency == Urgency.HIGH
    assert "MaintenanceAgent" in audit_record.agent_path
    assert "ResponsePolicyAgent" in audit_record.agent_path
    # Module response captured
    assert len(audit_record.module_responses) == 1
    assert audit_record.module_responses[0].success is True


@pytest.mark.asyncio
async def test_evidence_used_populated_when_context_has_hvac_facts(
    patch_external_services,
):
    """Test 2: When ContextBuilderAgent finds HVAC FAQ in knowledge,
    MaintenanceAgent cites property_facts.hvac_info as evidence."""
    mocks = patch_external_services
    mocks["knowledge"].return_value = _knowledge_with_hvac()

    orch = GuestMessageBrainOrchestrator()
    await orch.handle_inbound_message(
        _make_inbound(), db_session=MagicMock(),
    )

    audit = orch._audit.last_record
    assert audit is not None
    assert len(audit.decisions) == 1
    maint_decision = audit.decisions[0]
    assert maint_decision.agent_name == "MaintenanceAgent"
    assert "property_facts.hvac_info" in maint_decision.evidence_used


@pytest.mark.asyncio
async def test_evidence_empty_and_missing_info_populated_when_no_hvac_data(
    patch_external_services,
):
    """Test 3 (renumbered to 2b): When knowledge has no HVAC FAQ,
    MaintenanceAgent's evidence_used is empty AND missing_info notes
    the gap. The agent still runs and emits the ModuleEvent."""
    mocks = patch_external_services
    mocks["knowledge"].return_value = _knowledge_empty()

    orch = GuestMessageBrainOrchestrator()
    await orch.handle_inbound_message(
        _make_inbound(), db_session=MagicMock(),
    )

    audit = orch._audit.last_record
    assert audit is not None
    maint_decision = audit.decisions[0]
    # No evidence cited
    assert maint_decision.evidence_used == []
    # But missing_info notes what we wanted
    assert "property_facts.hvac_info" in maint_decision.missing_info
    # Module still ran
    assert mocks["work_order"].await_count == 1
    # No evidence-violation in audit notes
    violations = [n for n in audit.notes if "evidence-violation" in n]
    assert violations == []


@pytest.mark.asyncio
async def test_ordering_persist_inbound_completes_before_policy_evaluate(
    patch_external_services,
):
    """Test 3 (Watch 1): persist_inbound MUST complete before policy.evaluate.

    autonomy_gate.evaluate requires the internal messages.message_id UUID
    returned by persist_canonical_inbound_message. Reordering breaks
    blocking-escalation lookups and silently corrupts policy decisions.
    """
    mocks = patch_external_services
    call_order: List[str] = []

    async def persist_side_effect(*args, **kwargs):
        call_order.append("persist")
        return {
            "normalization_id": str(uuid4()),
            "message_id": str(mocks["persisted_uuid"]),
            "conversation_id": str(uuid4()),
            "channel_id": str(uuid4()),
        }

    async def gate_side_effect(*args, **kwargs):
        call_order.append("gate")
        # Verify the gate was called with the UUID persist returned
        assert kwargs.get("triggered_by_message_id") == mocks["persisted_uuid"], (
            f"gate called with triggered_by_message_id="
            f"{kwargs.get('triggered_by_message_id')!r}, "
            f"expected {mocks['persisted_uuid']!r}"
        )
        return GateResult(
            decision=AutonomyDecision.REVIEW,
            reason="ordering test",
            approval_mode_at_decision="required",
        )

    mocks["persist"].side_effect = persist_side_effect
    mocks["gate"].side_effect = gate_side_effect

    orch = GuestMessageBrainOrchestrator()
    await orch.handle_inbound_message(
        _make_inbound(), db_session=MagicMock(),
    )

    # The "persist" entry must come before "gate"
    assert "persist" in call_order
    assert "gate" in call_order
    assert call_order.index("persist") < call_order.index("gate"), (
        f"ordering violation: {call_order}"
    )


@pytest.mark.asyncio
async def test_no_module_dispatch_when_policy_escalates(
    patch_external_services,
):
    """Test 4 (Watch 2): When policy returns ESCALATE, modules are NOT
    dispatched. The escalation goes to operator review, not a parallel
    work order."""
    mocks = patch_external_services
    # Force the gate to return BLOCKED_BY_ESCALATION
    blocking_id = uuid4()
    mocks["gate"].return_value = GateResult(
        decision=AutonomyDecision.BLOCKED_BY_ESCALATION,
        reason="related escalation is open",
        approval_mode_at_decision="required",
        blocking_escalation_id=blocking_id,
    )

    orch = GuestMessageBrainOrchestrator()
    draft = await orch.handle_inbound_message(
        _make_inbound(), db_session=MagicMock(),
    )

    assert draft.final_action == RecommendedAction.ESCALATE
    assert draft.escalation_required is True

    # Module services were NOT called
    assert mocks["auto_track"].await_count == 0, (
        "concierge auto_track was called despite ESCALATE"
    )
    assert mocks["work_order"].await_count == 0, (
        "work_order create was called despite ESCALATE"
    )

    # Audit confirms dispatch was skipped
    audit = orch._audit.last_record
    assert any(
        "module_dispatch_skipped" in n for n in audit.notes
    ), f"expected skip note, got notes={audit.notes}"


@pytest.mark.asyncio
async def test_shadow_mode_skips_module_writes_but_writes_audit(
    patch_external_services,
):
    """Test 5 (Watch 3): shadow_mode=True suppresses module side effects
    (no work order, no concierge event) but the audit row IS still
    written. The shadow ModuleResponse describes what would have happened."""
    mocks = patch_external_services

    orch = GuestMessageBrainOrchestrator()
    draft = await orch.handle_inbound_message(
        _make_inbound(), db_session=MagicMock(), shadow_mode=True,
    )

    # Pipeline still produced a draft
    assert draft is not None
    assert draft.final_action == RecommendedAction.DRAFT_ONLY

    # NO module side effects
    assert mocks["auto_track"].await_count == 0, (
        "concierge auto_track called in shadow mode"
    )
    assert mocks["work_order"].await_count == 0, (
        "work_order called in shadow mode"
    )
    assert mocks["send_alert"].await_count == 0, (
        "operator alert fired in shadow mode"
    )

    # BUT: audit was still written (persist_inbound + update_outcome)
    assert mocks["persist"].await_count == 1, (
        "audit persist_inbound should still run in shadow mode"
    )
    assert mocks["update_outcome"].await_count == 1, (
        "audit update_outcome should still run in shadow mode"
    )

    # The module response describes what would have happened
    audit = orch._audit.last_record
    assert audit is not None
    assert len(audit.module_responses) == 1
    resp = audit.module_responses[0]
    assert resp.success is True
    assert resp.result.get("shadow") is True
    assert resp.result.get("would_have_created_concierge_event") is True
    assert resp.result.get("would_have_created_work_order") is True
    # workflow_ref preserved in shadow response
    assert resp.result.get("would_have_workflow_ref") == "SMS_AC_001"

    # Audit notes record shadow mode
    assert any("shadow_mode=true" in n for n in audit.notes)


@pytest.mark.asyncio
async def test_linking_concierge_event_id_present_in_work_order_payload(
    patch_external_services,
):
    """Test 6 (Watch 4): Through the full live pipeline, the work order's
    payload_json contains concierge_event_id pointing at the concierge
    event written in the same MaintenanceModule call.

    This is the architectural invariant for Rule 2 — the dual-table
    relationship is real, not aspirational."""
    mocks = patch_external_services

    orch = GuestMessageBrainOrchestrator()
    await orch.handle_inbound_message(
        _make_inbound(), db_session=MagicMock(),
    )

    # work_order_service.create_or_refresh_work_order was called once
    assert mocks["work_order"].await_count == 1
    call_args = mocks["work_order"].await_args
    payload = call_args.kwargs.get("payload") or {}

    # Linking invariant
    assert "concierge_event_id" in payload, (
        f"work order payload missing concierge_event_id: {payload}"
    )
    assert payload["concierge_event_id"] == mocks["concierge_event_id"], (
        f"link broken: expected {mocks['concierge_event_id']!r}, "
        f"got {payload['concierge_event_id']!r}"
    )

    # Other linking fields populated correctly
    assert payload["source_message_id"] == "SMS_AC_001"
    assert payload["category"] == "hvac"
    assert payload["module_event_id"]  # non-empty


@pytest.mark.asyncio
async def test_operator_alert_failure_does_not_flip_module_success(
    patch_external_services,
):
    """Alert send failure is non-blocking: ModuleResponse.success stays True
    and the error is recorded in result but does NOT propagate up.

    The work order and concierge event are the operational spine.  A
    notification failure is bad but is not a reason to mark the module
    failed — that would suppress the audit trail and mislead operators
    into thinking no work order was created."""
    mocks = patch_external_services
    mocks["send_alert"].side_effect = RuntimeError("SMS gateway timeout")

    orch = GuestMessageBrainOrchestrator()
    draft = await orch.handle_inbound_message(
        _make_inbound(), db_session=MagicMock(),
    )

    # Pipeline still produced a draft
    assert draft is not None
    assert draft.final_action == RecommendedAction.DRAFT_ONLY

    # Work order still written despite alert failure
    assert mocks["work_order"].await_count == 1

    # Module response is still success=True
    audit = orch._audit.last_record
    assert audit is not None
    assert len(audit.module_responses) == 1
    resp = audit.module_responses[0]
    assert resp.success is True, (
        "operator alert failure must NOT flip module success to False"
    )
    # Error captured in result dict for observability
    assert "operator_alert_error" in resp.result, (
        "alert error should be recorded in module result for audit visibility"
    )


@pytest.mark.asyncio
async def test_audit_record_json_serializable_after_full_pipeline(
    patch_external_services,
):
    """Regression test from 1.2: the full AgentAuditRecord remains
    JSON-roundtrippable after a real pipeline run. Catches future
    additions that might break Pydantic serialization."""
    from app.services.orchestration.messaging_brain_contracts import (
        AgentAuditRecord,
    )

    orch = GuestMessageBrainOrchestrator()
    await orch.handle_inbound_message(
        _make_inbound(), db_session=MagicMock(),
    )

    audit = orch._audit.last_record
    assert audit is not None

    # Round-trip
    serialized = audit.model_dump_json()
    rehydrated = AgentAuditRecord.model_validate_json(serialized)
    assert rehydrated.message_id == audit.message_id
    assert rehydrated.classification.intent_topic == "maintenance"
    assert len(rehydrated.module_events) == len(audit.module_events)
    assert len(rehydrated.module_responses) == len(audit.module_responses)


@pytest.mark.asyncio
async def test_default_orchestrator_has_maintenance_registered():
    """The default orchestrator construction must register MaintenanceAgent
    and MaintenanceModule. Tests don't need any patching to verify
    registration shape."""
    orch = GuestMessageBrainOrchestrator()

    # MaintenanceAgent registered as specialist
    assert "MaintenanceAgent" in orch._specialists

    # MaintenanceModule registered in the module registry
    assert "maintenance" in orch._modules.keys()
    assert isinstance(orch._modules.get("maintenance"), MaintenanceModule)
