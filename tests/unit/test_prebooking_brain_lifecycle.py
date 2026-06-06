from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.messaging_brain.persistence.prebooking_inquiry_types import (
    PreBookingDraftStage,
    PreBookingInquiryInput,
)
from app.services.messaging_brain.persistence.prebooking_inquiry_types import (
    AutoSendPolicy,
    PolicyCheckResult,
    PreBookingClassificationStage,
    PreBookingDecisionStage,
    SendDecision,
)
from app.services.messaging_brain.pre_booking_lifecycle import (
    execute_pre_booking_lifecycle,
    run_brain_pre_booking_lifecycle,
)


def _request(**overrides):
    payload = dict(
        thread_id="thread-1",
        platform="vrbo",
        guest_name="Taylor",
        message="Can you confirm the pet policy?",
        property_external_id="SEA_LA_VIE",
        company_id=uuid4(),
        api_key="api-key",
        property_data={"property_name": "Sea La Vie"},
        operator_policies={},
        structured_asks=["pets"],
        conversation_context="",
        requested_check_in=None,
        requested_check_out=None,
        requested_guests=4,
        message_id="msg-1",
        force_approval_mode="required",
        db="db-session",
        guest_thread_id="guest-thread-1",
        brain_draft_confidence=0.61,
        review_verdict="pass",
    )
    payload.update(overrides)
    return PreBookingInquiryInput(**payload)


def _classification(**overrides):
    payload = dict(
        intent="pet_policy",
        confidence=0.83,
        metadata=None,
        shadow_parser_notes=[],
    )
    payload.update(overrides)
    return PreBookingClassificationStage(**payload)


def _decision(**overrides):
    payload = dict(
        approval_mode="required",
        auto_send_policy=AutoSendPolicy(
            auto_send_threshold=0.75,
            auto_send_on_timeout=False,
            review_window_hours=2,
            flag_pricing_inquiries=True,
            flag_pet_inquiries=False,
        ),
        policy_result=PolicyCheckResult(flags=[], warnings=[], block_send=False),
        missing_knowledge_topics=[],
        knowledge_gap_analysis=None,
        decision=SendDecision.HOLD,
    )
    payload.update(overrides)
    return PreBookingDecisionStage(**payload)


def _save_result():
    return SimpleNamespace(
        inserted=True,
        status="saved",
        error_type=None,
        error_message=None,
        guest_thread_id="guest-thread-1",
        __bool__=lambda self: True,
    )


@pytest.mark.asyncio
async def test_execute_prebooking_lifecycle_model_composer_persists_draft_confidence(monkeypatch):
    save_calls = []
    alert_calls = []
    log_calls = []

    async def fake_save(**kwargs):
        save_calls.append(kwargs)
        return _save_result()

    async def fake_alert(**kwargs):
        alert_calls.append(kwargs)

    async def fake_log(**kwargs):
        log_calls.append(kwargs)

    monkeypatch.setattr(
        "app.services.messaging_brain.pre_booking_lifecycle.save_inquiry_from_canonical",
        fake_save,
    )
    monkeypatch.setattr(
        "app.services.messaging_brain.pre_booking_lifecycle.send_prebooking_review_alert",
        fake_alert,
    )
    monkeypatch.setattr(
        "app.services.messaging_brain.pre_booking_lifecycle._log_required_mode_event",
        fake_log,
    )

    result = await execute_pre_booking_lifecycle(
        request=_request(),
        classification=_classification(),
        decision_stage=_decision(),
        draft_stage=PreBookingDraftStage(
            draft_text="Absolutely, pets are welcome.",
            draft_source="messaging_brain",
        ),
    )

    context = save_calls[0]["context"]
    assert context.confidence_source == "model_composer"
    assert context.draft_confidence == 0.61
    assert context.intent_confidence == 0.83
    assert context.autonomy_decision == "routed_to_action_auto_off"
    assert result["sent"] is False
    assert result["decision"] == "hold"
    assert len(alert_calls) == 1
    assert len(log_calls) == 1


@pytest.mark.asyncio
async def test_run_brain_prebooking_lifecycle_falls_back_to_audit_policy_confidence(monkeypatch):
    save_calls = []

    async def fake_save(**kwargs):
        save_calls.append(kwargs)
        return _save_result()

    async def fake_alert(**kwargs):
        return None

    async def fake_log(**kwargs):
        return None

    monkeypatch.setattr(
        "app.services.messaging_brain.pre_booking_lifecycle.save_inquiry_from_canonical",
        fake_save,
    )
    monkeypatch.setattr(
        "app.services.messaging_brain.pre_booking_lifecycle.send_prebooking_review_alert",
        fake_alert,
    )
    monkeypatch.setattr(
        "app.services.messaging_brain.pre_booking_lifecycle._log_required_mode_event",
        fake_log,
    )

    brain_result = SimpleNamespace(
        inquiry=SimpleNamespace(
            thread_id="thread-1",
            platform="vrbo",
            guest_name="Taylor",
            message_text="Can you confirm the pet policy?",
            property_code="SEA_LA_VIE",
            requested_check_in=None,
            requested_check_out=None,
            requested_guests=4,
            message_id="msg-1",
            structured_asks=["pets"],
            conversation_context="",
        ),
        context=SimpleNamespace(
            property_data={"property_name": "Sea La Vie"},
            operator_policies={},
        ),
        brain_draft=SimpleNamespace(
            response_text="Absolutely, pets are welcome.",
            confidence=None,
        ),
        audit_record=SimpleNamespace(
            final_response=SimpleNamespace(confidence=None),
            policy=SimpleNamespace(confidence=0.67),
            decisions=[],
        ),
        legacy_intent="pet_policy",
        intent_confidence=0.83,
    )

    await run_brain_pre_booking_lifecycle(
        brain_result=brain_result,
        company_id=uuid4(),
        api_key="api-key",
        force_approval_mode="required",
        db="db-session",
        guest_thread_id="guest-thread-1",
        reviewed_draft_text="Absolutely, pets are welcome.",
        reviewer_flags=[],
        reviewer_warnings=[],
        review_verdict="pass",
    )

    context = save_calls[0]["context"]
    assert context.confidence_source == "model_composer"
    assert context.draft_confidence == 0.67


@pytest.mark.asyncio
async def test_execute_prebooking_lifecycle_hold_nulls_draft_confidence(monkeypatch):
    save_calls = []
    alert_calls = []

    async def fake_save(**kwargs):
        save_calls.append(kwargs)
        return _save_result()

    async def fake_alert(**kwargs):
        alert_calls.append(kwargs)

    async def fake_log(**kwargs):
        return None

    monkeypatch.setattr(
        "app.services.messaging_brain.pre_booking_lifecycle.save_inquiry_from_canonical",
        fake_save,
    )
    monkeypatch.setattr(
        "app.services.messaging_brain.pre_booking_lifecycle.send_prebooking_review_alert",
        fake_alert,
    )
    monkeypatch.setattr(
        "app.services.messaging_brain.pre_booking_lifecycle._log_required_mode_event",
        fake_log,
    )

    result = await execute_pre_booking_lifecycle(
        request=_request(review_verdict="hold"),
        classification=_classification(),
        decision_stage=_decision(),
        draft_stage=PreBookingDraftStage(
            draft_text="",
            draft_source="messaging_brain",
        ),
    )

    context = save_calls[0]["context"]
    assert context.confidence_source == "held_for_review"
    assert context.draft_confidence is None
    assert context.autonomy_decision == "routed_to_action_policy_review"
    assert result["draft_text"] == ""
    assert len(alert_calls) == 1


@pytest.mark.asyncio
async def test_execute_prebooking_lifecycle_gap_blocked_takes_priority(monkeypatch):
    save_calls = []
    log_calls = []

    async def fake_save(**kwargs):
        save_calls.append(kwargs)
        return _save_result()

    async def fake_alert(**kwargs):
        return None

    async def fake_log(**kwargs):
        log_calls.append(kwargs)

    monkeypatch.setattr(
        "app.services.messaging_brain.pre_booking_lifecycle.save_inquiry_from_canonical",
        fake_save,
    )
    monkeypatch.setattr(
        "app.services.messaging_brain.pre_booking_lifecycle.send_prebooking_review_alert",
        fake_alert,
    )
    monkeypatch.setattr(
        "app.services.messaging_brain.pre_booking_lifecycle._log_required_mode_event",
        fake_log,
    )

    result = await execute_pre_booking_lifecycle(
        request=_request(review_verdict="hold"),
        classification=_classification(),
        decision_stage=_decision(
            policy_result=PolicyCheckResult(
                flags=["ℹ️ Knowledge gap detected — hold for operator review before replying"],
                warnings=["missing_property_knowledge:pet_policy"],
                block_send=False,
            ),
            missing_knowledge_topics=["pet_policy"],
        ),
        draft_stage=PreBookingDraftStage(
            draft_text="",
            draft_source="messaging_brain",
        ),
    )

    context = save_calls[0]["context"]
    assert context.confidence_source == "gap_blocked"
    assert context.draft_confidence is None
    assert context.blocked_by_gap_topics == ["pet_policy"]
    assert context.autonomy_decision == "routed_to_action_kb_gap"
    assert result["policy_warnings"] == ["missing_property_knowledge:pet_policy"]
    assert len(log_calls) == 1
