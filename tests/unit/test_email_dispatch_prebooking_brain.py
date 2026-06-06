"""
test_email_dispatch_prebooking_brain.py — email pre-booking brain dispatch verification.

Pins the live email pre-booking entrypoint behavior:
  * non-primary runtime -> fallback row is persisted for operator review
  * runtime + lifecycle primary -> brain-backed draft path
  * brain/reviewer failure -> safe fallback row is persisted
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from app.services.integrations import email_dispatch
from app.services.integrations.email_dispatch import (
    EmailDispatchServices,
    dispatch_pre_booking,
)


def _make_services() -> EmailDispatchServices:
    db = SimpleNamespace(
        commit=AsyncMock(),
        rollback=AsyncMock(),
    )
    return EmailDispatchServices(
        company_id=UUID("11111111-1111-1111-1111-111111111111"),
        db=db,
        watched_email="host@example.com",
        operator_name="Beach Habitats",
        infer_property_match_type=lambda parsed, code: "exact",
        load_property_context=AsyncMock(return_value=({"property_name": "Gulf View 204"}, {})),
        store_thread_context=AsyncMock(),
        maybe_record_pre_booking_gap=AsyncMock(),
        save_fallback_pre_booking_inquiry=AsyncMock(return_value=False),
        record_kb_gap=AsyncMock(),
        record_property_binding_gap=AsyncMock(),
        build_reply_sender=lambda: MagicMock(),
        generate_in_stay_reply=AsyncMock(return_value="in-stay reply"),
        load_review_event_policy=AsyncMock(return_value={}),
        find_session_by_reservation_context=AsyncMock(return_value=None),
        create_provisional_session_from_system_event=AsyncMock(return_value=False),
        persist_review_event=AsyncMock(),
    )


def _make_parsed():
    return SimpleNamespace(
        gmail_message_id="gmail-msg-001",
        thread_id="thread-001",
        platform="vrbo",
        guest_name="Taylor",
        latest_guest_message="Is this available July 10-14?",
        body="Is this available July 10-14?",
        full_body="Is this available July 10-14?",
        conversation_context="",
        property_code="GULF_VIEW_204",
        property_name="Gulf View 204",
        asks=["availability"],
        requested_check_in=None,
        requested_check_out=None,
        requested_guests=4,
        message_id="msg-001",
        guest_email="guest@example.com",
        reply_channel_address="guest-thread@example.com",
        link_context_summary="",
        parser_source="test_parser",
        platform_listing_id="listing-1",
        platform_unit_id="unit-1",
        raw_from="Guest <guest@example.com>",
        subject="Inquiry for Gulf View 204",
        received_at=datetime(2026, 5, 24, 9, 0, tzinfo=timezone.utc),
        intake_layer1_decision="admit",
        intake_layer1_reason="subject:prebooking_pattern",
    )


class _FakeFlagService:
    def __init__(self, *values: bool):
        self._values = list(values)

    async def is_enabled(self, *args, **kwargs):
        return self._values.pop(0)


def _stub_prefilter(
    monkeypatch,
    *,
    legacy_intent: str = "availability",
    confidence: float = 0.82,
    intent_topic: str = "booking_inquiry",
    sub_intents: list[str] | None = None,
):
    async def _fake_classify_with_metadata(self, message, *, db_session=None):
        return (
            SimpleNamespace(
                confidence=confidence,
                intent_topic=intent_topic,
                sub_intents=list(sub_intents or []),
            ),
            SimpleNamespace(legacy_intent=legacy_intent),
        )

    monkeypatch.setattr(
        "app.services.messaging_brain.agents.deterministic_intake_prefilter.DeterministicIntakePreFilter.classify_with_metadata",
        _fake_classify_with_metadata,
    )


@pytest.mark.asyncio
async def test_dispatch_pre_booking_runtime_not_primary_saves_fallback(monkeypatch):
    services = _make_services()
    parsed = _make_parsed()
    services.save_fallback_pre_booking_inquiry = AsyncMock(return_value=True)
    normalization = AsyncMock()

    monkeypatch.setattr(
        "app.services.feature_flags.get_feature_flags",
        lambda db: _FakeFlagService(False, False, False, False, False),
    )
    _stub_prefilter(monkeypatch)
    monkeypatch.setattr(email_dispatch, "update_normalization_outcome", normalization)

    outcome = await dispatch_pre_booking(services=services, parsed=parsed)

    assert outcome == "pre_booking_fallback"
    services.save_fallback_pre_booking_inquiry.assert_awaited_once_with(
        parsed,
        "brain_runtime_not_primary",
    )
    assert normalization.await_args.kwargs["route_outcome"] == "pre_booking_fallback"


@pytest.mark.asyncio
async def test_dispatch_pre_booking_flag_on_uses_brain_lifecycle(monkeypatch):
    services = _make_services()
    parsed = _make_parsed()
    brain_lifecycle = AsyncMock(return_value={
        "saved": True,
        "draft_id": "INQ-BRAIN",
        "decision": "hold",
        "draft_source": "messaging_brain",
        "policy_warnings": [],
    })
    normalization = AsyncMock()

    class _FakeBrain:
        def __init__(self):
            self.handle = AsyncMock(return_value=SimpleNamespace(
                brain_draft=SimpleNamespace(
                    response_text="Those dates look promising and I’m confirming the final details now.",
                    confidence=0.83,
                ),
                inquiry=SimpleNamespace(structured_asks=["availability"]),
            ))

    fake_brain = _FakeBrain()
    monkeypatch.setattr(
        "app.services.feature_flags.get_feature_flags",
        lambda db: _FakeFlagService(False, False, True, False, False),
    )
    monkeypatch.setattr(
        "app.services.feature_flags.is_brain_prebooking_lifecycle_primary_enabled",
        AsyncMock(return_value=True),
    )
    _stub_prefilter(monkeypatch)
    monkeypatch.setattr(
        "app.services.messaging_brain.pre_booking.PreBookingBrainOrchestrator",
        lambda: fake_brain,
    )
    monkeypatch.setattr(
        "app.services.integrations.email_dispatch._review_brain_pre_booking_draft",
        AsyncMock(return_value=(
            "Reviewed brain draft",
            ["ℹ️ Adversarial review revised the brain draft before operator display"],
            ["adversarial_review:verdict=revise|source=test|flags=none|rationale=none|revised=true|orig_hash=aaaaaaaa|final_hash=bbbbbbbb|orig_preview=orig|final_preview=final"],
            "revise",
        )),
    )
    monkeypatch.setattr(
        "app.services.messaging_brain.pre_booking_lifecycle.run_brain_pre_booking_lifecycle",
        brain_lifecycle,
    )
    monkeypatch.setattr(email_dispatch, "update_normalization_outcome", normalization)

    outcome = await dispatch_pre_booking(services=services, parsed=parsed)

    assert outcome == "pre_booking_new"
    fake_brain.handle.assert_awaited_once()
    brain_lifecycle.assert_awaited_once()
    assert brain_lifecycle.await_args.kwargs["reviewed_draft_text"] == "Reviewed brain draft"
    assert brain_lifecycle.await_args.kwargs["reviewer_flags"] == [
        "ℹ️ Adversarial review revised the brain draft before operator display"
    ]
    assert "adversarial_review:verdict=revise" in brain_lifecycle.await_args.kwargs[
        "reviewer_warnings"
    ][0]


@pytest.mark.asyncio
async def test_dispatch_pre_booking_lifecycle_primary_uses_brain_lifecycle(monkeypatch):
    services = _make_services()
    parsed = _make_parsed()
    brain_lifecycle = AsyncMock(return_value={
        "saved": True,
        "draft_id": "INQ-BRAIN-LIFECYCLE",
        "decision": "hold",
        "draft_source": "messaging_brain",
        "policy_warnings": [],
    })
    normalization = AsyncMock()

    class _FakeBrain:
        def __init__(self):
            self.handle = AsyncMock(return_value=SimpleNamespace(
                brain_draft=SimpleNamespace(
                    response_text="Those dates look promising and I’m confirming the final details now.",
                    confidence=0.83,
                ),
                inquiry=SimpleNamespace(structured_asks=["availability"]),
            ))

    fake_brain = _FakeBrain()
    monkeypatch.setattr(
        "app.services.feature_flags.get_feature_flags",
        lambda db: _FakeFlagService(False, False, True, False, False),
    )
    monkeypatch.setattr(
        "app.services.feature_flags.is_brain_prebooking_lifecycle_primary_enabled",
        AsyncMock(return_value=True),
    )
    _stub_prefilter(monkeypatch)
    monkeypatch.setattr(
        "app.services.messaging_brain.pre_booking.PreBookingBrainOrchestrator",
        lambda: fake_brain,
    )
    monkeypatch.setattr(
        "app.services.integrations.email_dispatch._review_brain_pre_booking_draft",
        AsyncMock(return_value=("Reviewed brain draft", [], [], "pass")),
    )
    monkeypatch.setattr(
        "app.services.messaging_brain.pre_booking_lifecycle.run_brain_pre_booking_lifecycle",
        brain_lifecycle,
    )
    monkeypatch.setattr(email_dispatch, "update_normalization_outcome", normalization)

    outcome = await dispatch_pre_booking(services=services, parsed=parsed)

    assert outcome == "pre_booking_new"
    brain_lifecycle.assert_awaited_once()


@pytest.mark.asyncio
async def test_dispatch_pre_booking_lifecycle_primary_implies_runtime_for_prebooking(monkeypatch):
    services = _make_services()
    parsed = _make_parsed()
    brain_lifecycle = AsyncMock(return_value={
        "saved": True,
        "draft_id": "INQ-BRAIN-LIFECYCLE-IMPLIED",
        "decision": "hold",
        "draft_source": "messaging_brain",
        "policy_warnings": [],
    })
    normalization = AsyncMock()

    class _FakeBrain:
        def __init__(self):
            self.handle = AsyncMock(return_value=SimpleNamespace(
                brain_draft=SimpleNamespace(
                    response_text="Those dates look promising and I’m confirming the final details now.",
                    confidence=0.83,
                ),
                inquiry=SimpleNamespace(structured_asks=["availability"]),
            ))

    fake_brain = _FakeBrain()
    monkeypatch.setattr(
        "app.services.feature_flags.get_feature_flags",
        lambda db: _FakeFlagService(False, False, False, False, False),
    )
    monkeypatch.setattr(
        "app.services.feature_flags.is_brain_prebooking_lifecycle_primary_enabled",
        AsyncMock(return_value=True),
    )
    _stub_prefilter(monkeypatch)
    monkeypatch.setattr(
        "app.services.messaging_brain.pre_booking.PreBookingBrainOrchestrator",
        lambda: fake_brain,
    )
    monkeypatch.setattr(
        "app.services.integrations.email_dispatch._review_brain_pre_booking_draft",
        AsyncMock(return_value=("Reviewed brain draft", [], [], "pass")),
    )
    monkeypatch.setattr(
        "app.services.messaging_brain.pre_booking_lifecycle.run_brain_pre_booking_lifecycle",
        brain_lifecycle,
    )
    monkeypatch.setattr(email_dispatch, "update_normalization_outcome", normalization)

    outcome = await dispatch_pre_booking(services=services, parsed=parsed)

    assert outcome == "pre_booking_new"
    fake_brain.handle.assert_awaited_once()
    brain_lifecycle.assert_awaited_once()
    services.save_fallback_pre_booking_inquiry.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_pre_booking_brain_failure_saves_fallback(monkeypatch):
    services = _make_services()
    parsed = _make_parsed()
    services.save_fallback_pre_booking_inquiry = AsyncMock(return_value=True)
    normalization = AsyncMock()

    class _FakeBrain:
        def __init__(self):
            self.handle = AsyncMock(side_effect=RuntimeError("brain exploded"))

    fake_brain = _FakeBrain()
    monkeypatch.setattr(
        "app.services.feature_flags.get_feature_flags",
        lambda db: _FakeFlagService(False, False, True, False, False),
    )
    monkeypatch.setattr(
        "app.services.feature_flags.is_brain_prebooking_lifecycle_primary_enabled",
        AsyncMock(return_value=True),
    )
    _stub_prefilter(monkeypatch)
    monkeypatch.setattr(
        "app.services.messaging_brain.pre_booking.PreBookingBrainOrchestrator",
        lambda: fake_brain,
    )
    monkeypatch.setattr(email_dispatch, "update_normalization_outcome", normalization)

    outcome = await dispatch_pre_booking(services=services, parsed=parsed)

    assert outcome == "pre_booking_fallback"
    services.save_fallback_pre_booking_inquiry.assert_awaited_once()
    assert "brain_exception:RuntimeError:brain exploded" in services.save_fallback_pre_booking_inquiry.await_args.args[1]


@pytest.mark.asyncio
async def test_dispatch_pre_booking_review_failure_saves_fallback(monkeypatch):
    services = _make_services()
    parsed = _make_parsed()
    services.save_fallback_pre_booking_inquiry = AsyncMock(return_value=True)
    normalization = AsyncMock()

    class _FakeBrain:
        def __init__(self):
            self.handle = AsyncMock(return_value=SimpleNamespace(
                brain_draft=SimpleNamespace(
                    response_text="Original brain draft",
                    confidence=0.83,
                ),
                inquiry=SimpleNamespace(structured_asks=["amenities"]),
            ))

    fake_brain = _FakeBrain()
    monkeypatch.setattr(
        "app.services.feature_flags.get_feature_flags",
        lambda db: _FakeFlagService(False, False, True, False, False),
    )
    monkeypatch.setattr(
        "app.services.feature_flags.is_brain_prebooking_lifecycle_primary_enabled",
        AsyncMock(return_value=True),
    )
    _stub_prefilter(monkeypatch)
    monkeypatch.setattr(
        "app.services.messaging_brain.pre_booking.PreBookingBrainOrchestrator",
        lambda: fake_brain,
    )
    monkeypatch.setattr(
        "app.services.integrations.email_dispatch._review_brain_pre_booking_draft",
        AsyncMock(side_effect=RuntimeError("review exploded")),
    )
    monkeypatch.setattr(email_dispatch, "update_normalization_outcome", normalization)

    outcome = await dispatch_pre_booking(services=services, parsed=parsed)

    assert outcome == "pre_booking_fallback"
    services.save_fallback_pre_booking_inquiry.assert_awaited_once()
    assert "brain_exception:RuntimeError:review exploded" in services.save_fallback_pre_booking_inquiry.await_args.args[1]


@pytest.mark.asyncio
async def test_dispatch_pre_booking_surfaces_fallback_save_failure(monkeypatch):
    services = _make_services()
    parsed = _make_parsed()
    services.save_fallback_pre_booking_inquiry = AsyncMock(return_value=False)
    normalization = AsyncMock()

    monkeypatch.setattr(
        "app.services.feature_flags.get_feature_flags",
        lambda db: _FakeFlagService(False, False, False, False, False),
    )
    _stub_prefilter(monkeypatch)
    monkeypatch.setattr(email_dispatch, "update_normalization_outcome", normalization)

    with pytest.raises(RuntimeError, match="pre-booking fallback save failed: brain_runtime_not_primary"):
        await dispatch_pre_booking(services=services, parsed=parsed)

    normalization.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_pre_booking_gate_skip_short_circuits_before_property_load(monkeypatch):
    services = _make_services()
    parsed = _make_parsed()
    parsed.intake_layer1_decision = "unclear"
    normalization = AsyncMock()
    persist_gate = AsyncMock(return_value=True)

    class _FakeGate:
        async def classify(self, **kwargs):
            from app.services.messaging_brain.inbound_message_gate import GateDecision, InboundClassification
            return GateDecision(
                decision_id=UUID("22222222-2222-2222-2222-222222222222"),
                classification=InboundClassification.OPERATIONAL_NOTIFICATION,
                confidence=0.94,
                reasoning="platform reminder, not a guest turn",
                extracted=None,
                model="test",
            )

    monkeypatch.setattr(
        "app.services.feature_flags.get_feature_flags",
        lambda db: _FakeFlagService(True, False, False, False, False),
    )
    monkeypatch.setattr(
        "app.services.integrations.email_dispatch.persist_gate_decision",
        persist_gate,
    )
    monkeypatch.setattr(
        "app.services.integrations.email_dispatch.InboundMessageGate",
        lambda: _FakeGate(),
    )
    _stub_prefilter(monkeypatch)
    monkeypatch.setattr(email_dispatch, "update_normalization_outcome", normalization)

    outcome = await dispatch_pre_booking(services=services, parsed=parsed)

    assert outcome == "pre_booking_gate_skipped"
    services.load_property_context.assert_not_awaited()
    persist_gate.assert_awaited_once()


@pytest.mark.asyncio
async def test_dispatch_pre_booking_gate_review_saves_fallback(monkeypatch):
    services = _make_services()
    parsed = _make_parsed()
    parsed.intake_layer1_decision = "unclear"
    services.save_fallback_pre_booking_inquiry = AsyncMock(return_value=True)
    normalization = AsyncMock()
    persist_gate = AsyncMock(return_value=True)

    class _FakeGate:
        async def classify(self, **kwargs):
            from app.services.messaging_brain.inbound_message_gate import GateDecision, InboundClassification
            return GateDecision(
                decision_id=UUID("33333333-3333-3333-3333-333333333333"),
                classification=InboundClassification.UNCLEAR,
                confidence=0.42,
                reasoning="could not confidently separate guest from automation",
                extracted=None,
                model="test",
            )

    monkeypatch.setattr(
        "app.services.feature_flags.get_feature_flags",
        lambda db: _FakeFlagService(True, False, False, False, False),
    )
    monkeypatch.setattr(
        "app.services.integrations.email_dispatch.persist_gate_decision",
        persist_gate,
    )
    monkeypatch.setattr(
        "app.services.integrations.email_dispatch.InboundMessageGate",
        lambda: _FakeGate(),
    )
    monkeypatch.setattr(email_dispatch, "update_normalization_outcome", normalization)

    outcome = await dispatch_pre_booking(services=services, parsed=parsed)

    assert outcome == "pre_booking_fallback"
    services.save_fallback_pre_booking_inquiry.assert_awaited_once()
    services.load_property_context.assert_not_awaited()
    persist_gate.assert_awaited_once()


@pytest.mark.asyncio
async def test_dispatch_pre_booking_gate_unclear_guest_below_threshold_admits_on_uncertainty(monkeypatch):
    services = _make_services()
    parsed = _make_parsed()
    parsed.intake_layer1_decision = "unclear"
    normalization = AsyncMock()
    persist_gate = AsyncMock(return_value=True)
    brain_lifecycle = AsyncMock(return_value={
        "saved": True,
        "draft_id": "INQ-GATE-LOWCONF",
        "decision": "hold",
        "draft_source": "messaging_brain",
        "policy_warnings": [],
    })

    class _FakeGate:
        async def classify(self, **kwargs):
            from app.services.messaging_brain.inbound_message_gate import GateDecision, InboundClassification
            return GateDecision(
                decision_id=UUID("44444444-4444-4444-4444-444444444444"),
                classification=InboundClassification.GUEST_MESSAGE,
                confidence=0.42,
                reasoning="looks like a guest message but confidence is low",
                extracted=None,
                model="test",
            )

    class _FakeBrain:
        def __init__(self):
            self.handle = AsyncMock(return_value=SimpleNamespace(
                brain_draft=SimpleNamespace(
                    response_text="Brain draft",
                    confidence=0.83,
                ),
                inquiry=SimpleNamespace(structured_asks=["availability"]),
            ))

    monkeypatch.setattr(
        "app.services.feature_flags.get_feature_flags",
        lambda db: _FakeFlagService(True, False, True, False, False),
    )
    monkeypatch.setattr(
        "app.services.feature_flags.is_brain_prebooking_lifecycle_primary_enabled",
        AsyncMock(return_value=True),
    )
    _stub_prefilter(monkeypatch)
    monkeypatch.setattr(
        "app.services.integrations.email_dispatch.persist_gate_decision",
        persist_gate,
    )
    monkeypatch.setattr(
        "app.services.integrations.email_dispatch.InboundMessageGate",
        lambda: _FakeGate(),
    )
    monkeypatch.setattr(
        "app.services.messaging_brain.pre_booking.PreBookingBrainOrchestrator",
        lambda: _FakeBrain(),
    )
    monkeypatch.setattr(
        "app.services.integrations.email_dispatch._review_brain_pre_booking_draft",
        AsyncMock(return_value=("Reviewed draft", [], [], "pass")),
    )
    monkeypatch.setattr(
        "app.services.messaging_brain.pre_booking_lifecycle.run_brain_pre_booking_lifecycle",
        brain_lifecycle,
    )
    monkeypatch.setattr(email_dispatch, "update_normalization_outcome", normalization)

    outcome = await dispatch_pre_booking(services=services, parsed=parsed)

    assert outcome == "pre_booking_new"
    brain_lifecycle.assert_awaited_once()
    assert "inbound_gate_unclear_admitted" in brain_lifecycle.await_args.kwargs["reviewer_warnings"][-1]
    persist_gate.assert_awaited_once()


@pytest.mark.asyncio
async def test_dispatch_pre_booking_retryable_gate_error_admits_deterministic_guest_parser(monkeypatch):
    services = _make_services()
    parsed = _make_parsed()
    parsed.intake_layer1_decision = "unclear"
    parsed.parser_source = "ota_parser_vrbo_plain"
    parsed.reply_channel_address = "reply@messages.homeaway.com"
    normalization = AsyncMock()
    persist_gate = AsyncMock(return_value=True)
    brain_lifecycle = AsyncMock(return_value={
        "saved": True,
        "draft_id": "INQ-GATE-RETRYABLE",
        "decision": "hold",
        "draft_source": "messaging_brain",
        "policy_warnings": [],
    })

    class _FakeGate:
        async def classify(self, **kwargs):
            from app.services.messaging_brain.inbound_message_gate import GateDecision, InboundClassification
            return GateDecision(
                decision_id=UUID("45444444-4444-4444-4444-444444444444"),
                classification=InboundClassification.UNCLEAR,
                confidence=0.0,
                reasoning="gate API call failed: status=429 retryable=true body=rate limited",
                extracted=None,
                model="test",
                error="status=429 retryable=true body=rate limited",
                status_code=429,
                retryable=True,
            )

    class _FakeBrain:
        def __init__(self):
            self.handle = AsyncMock(return_value=SimpleNamespace(
                brain_draft=SimpleNamespace(
                    response_text="Brain draft",
                    confidence=0.83,
                ),
                inquiry=SimpleNamespace(structured_asks=["availability"]),
            ))

    monkeypatch.setattr(
        "app.services.feature_flags.get_feature_flags",
        lambda db: _FakeFlagService(True, False, True, False, False),
    )
    monkeypatch.setattr(
        "app.services.feature_flags.is_brain_prebooking_lifecycle_primary_enabled",
        AsyncMock(return_value=True),
    )
    _stub_prefilter(monkeypatch)
    monkeypatch.setattr(
        "app.services.integrations.email_dispatch.persist_gate_decision",
        persist_gate,
    )
    monkeypatch.setattr(
        "app.services.integrations.email_dispatch.InboundMessageGate",
        lambda: _FakeGate(),
    )
    monkeypatch.setattr(
        "app.services.messaging_brain.pre_booking.PreBookingBrainOrchestrator",
        lambda: _FakeBrain(),
    )
    monkeypatch.setattr(
        "app.services.integrations.email_dispatch._review_brain_pre_booking_draft",
        AsyncMock(return_value=("Reviewed draft", [], [], "pass")),
    )
    monkeypatch.setattr(
        "app.services.messaging_brain.pre_booking_lifecycle.run_brain_pre_booking_lifecycle",
        brain_lifecycle,
    )
    monkeypatch.setattr(email_dispatch, "update_normalization_outcome", normalization)

    outcome = await dispatch_pre_booking(services=services, parsed=parsed)

    assert outcome == "pre_booking_new"
    services.save_fallback_pre_booking_inquiry.assert_not_awaited()
    assert "inbound_gate_retryable_error_admitted" in brain_lifecycle.await_args.kwargs["reviewer_warnings"][-1]


@pytest.mark.asyncio
async def test_dispatch_pre_booking_retryable_gate_error_still_falls_back_for_non_deterministic_parser(monkeypatch):
    services = _make_services()
    parsed = _make_parsed()
    parsed.intake_layer1_decision = "unclear"
    services.save_fallback_pre_booking_inquiry = AsyncMock(return_value=True)
    normalization = AsyncMock()
    persist_gate = AsyncMock(return_value=True)

    class _FakeGate:
        async def classify(self, **kwargs):
            from app.services.messaging_brain.inbound_message_gate import GateDecision, InboundClassification
            return GateDecision(
                decision_id=UUID("46444444-4444-4444-4444-444444444444"),
                classification=InboundClassification.UNCLEAR,
                confidence=0.0,
                reasoning="gate API call failed: status=429 retryable=true body=rate limited",
                extracted=None,
                model="test",
                error="status=429 retryable=true body=rate limited",
                status_code=429,
                retryable=True,
            )

    monkeypatch.setattr(
        "app.services.feature_flags.get_feature_flags",
        lambda db: _FakeFlagService(True, False, False, False, False),
    )
    monkeypatch.setattr(
        "app.services.integrations.email_dispatch.persist_gate_decision",
        persist_gate,
    )
    monkeypatch.setattr(
        "app.services.integrations.email_dispatch.InboundMessageGate",
        lambda: _FakeGate(),
    )
    monkeypatch.setattr(email_dispatch, "update_normalization_outcome", normalization)

    outcome = await dispatch_pre_booking(services=services, parsed=parsed)

    assert outcome == "pre_booking_gate_error"
    services.save_fallback_pre_booking_inquiry.assert_awaited_once()


@pytest.mark.asyncio
async def test_dispatch_pre_booking_layer1_admit_bypasses_gate(monkeypatch):
    services = _make_services()
    parsed = _make_parsed()
    normalization = AsyncMock()
    persist_gate = AsyncMock(return_value=True)
    services.save_fallback_pre_booking_inquiry = AsyncMock(return_value=True)

    monkeypatch.setattr(
        "app.services.feature_flags.get_feature_flags",
        lambda db: _FakeFlagService(True, False, False, False, False),
    )
    _stub_prefilter(monkeypatch)
    monkeypatch.setattr(
        "app.services.integrations.email_dispatch.persist_gate_decision",
        persist_gate,
    )
    monkeypatch.setattr(email_dispatch, "update_normalization_outcome", normalization)

    outcome = await dispatch_pre_booking(services=services, parsed=parsed)

    assert outcome == "pre_booking_fallback"
    services.save_fallback_pre_booking_inquiry.assert_awaited_once()
    persist_gate.assert_not_called()


@pytest.mark.asyncio
async def test_dispatch_pre_booking_keeps_general_intent_on_prebooking_path(monkeypatch):
    services = _make_services()
    parsed = _make_parsed()
    parsed.latest_guest_message = "Please confirm the balance due."
    parsed.body = parsed.latest_guest_message
    normalization = AsyncMock()
    services.save_fallback_pre_booking_inquiry = AsyncMock(return_value=True)
    route_guest_session = AsyncMock()

    monkeypatch.setattr(
        "app.services.feature_flags.get_feature_flags",
        lambda db: _FakeFlagService(False, False, False, False),
    )
    _stub_prefilter(
        monkeypatch,
        legacy_intent="general",
        confidence=0.55,
        intent_topic="general",
    )
    monkeypatch.setattr(
        "app.services.concierge.post_booking_routing.persist_inbound_from_inquiry",
        route_guest_session,
    )
    monkeypatch.setattr(email_dispatch, "update_normalization_outcome", normalization)

    outcome = await dispatch_pre_booking(services=services, parsed=parsed)

    assert outcome == "pre_booking_fallback"
    route_guest_session.assert_not_awaited()
    services.load_property_context.assert_awaited_once()
    services.save_fallback_pre_booking_inquiry.assert_awaited_once_with(
        parsed,
        "brain_runtime_not_primary",
    )
    assert normalization.await_args.kwargs["route_outcome"] == "pre_booking_fallback"


@pytest.mark.asyncio
async def test_dispatch_pre_booking_reroutes_explicit_lifecycle_guest_message(monkeypatch):
    services = _make_services()
    parsed = _make_parsed()
    parsed.lifecycle_stage = "in_stay"
    parsed.asks = ["service_issue"]
    parsed.latest_guest_message = "We cannot find where to charge the golf cart during our stay."
    parsed.body = parsed.latest_guest_message
    normalization = AsyncMock()
    route_guest_session = AsyncMock(
        return_value=SimpleNamespace(created=True, status="created")
    )

    monkeypatch.setattr(
        "app.services.feature_flags.get_feature_flags",
        lambda db: _FakeFlagService(False, False, True, False, False),
    )
    _stub_prefilter(
        monkeypatch,
        legacy_intent="availability",
        confidence=0.62,
        intent_topic="booking_inquiry",
        sub_intents=["availability"],
    )
    monkeypatch.setattr(
        "app.services.concierge.post_booking_routing.persist_inbound_from_inquiry",
        route_guest_session,
    )
    monkeypatch.setattr(email_dispatch, "update_normalization_outcome", normalization)

    outcome = await dispatch_pre_booking(services=services, parsed=parsed)

    assert outcome == "guest_session_routed"
    route_guest_session.assert_awaited_once()
    services.load_property_context.assert_not_awaited()
    assert normalization.await_args.kwargs["draft_source"] == "lifecycle_router"
    assert (
        normalization.await_args.kwargs["fallback_reason"]
        == "lifecycle_stage:in_stay:email_dispatch_lifecycle_reroute:created"
    )
