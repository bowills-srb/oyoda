from __future__ import annotations

import logging
import uuid as _uuid
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.services.messaging_brain.persistence.prebooking_inquiry_types import (
    AutoSendPolicy,
    PolicyCheckResult,
    PreBookingClassificationStage,
    PreBookingDecisionStage,
    SendDecision,
)
from app.services.messaging.inbound_normalizer import CanonicalInboundMessage
from app.services.messaging_brain.notifications.prebooking_review_alerts import (
    send_prebooking_review_alert,
    _log_required_mode_event,
)
from app.services.messaging_brain.policy.platform_compliance import (
    apply_pre_booking_draft_source_policy,
    evaluate_pre_booking_policy,
)
from app.services.messaging_brain.persistence.prebooking_inquiry_store import (
    save_inquiry_from_canonical,
)
from app.services.messaging_brain.pre_booking import PreBookingDraftResult
from app.services.messaging_brain.persistence.prebooking_inquiry_types import (
    InquirySaveContext,
    PreBookingDraftStage,
    PreBookingInquiryInput,
    SaveInquiryResult,
)

_STUB_SPECIALIST_SENTINEL = "__stub_specialist__"
_BRAIN_DEFAULT_POLICY = AutoSendPolicy(auto_send_on_timeout=False)
logger = logging.getLogger(__name__)


def _resolve_autonomy_decision(
    *,
    approval_mode: str,
    decision: SendDecision,
    missing_knowledge_topics: list[str],
    policy_warnings: list[str],
    review_verdict: Optional[str],
) -> str:
    if decision == SendDecision.SEND_NOW:
        return "auto_sent"
    if missing_knowledge_topics:
        return "routed_to_action_kb_gap"
    if policy_warnings or review_verdict in {"hold", "revise"}:
        return "routed_to_action_policy_review"
    if approval_mode == "auto":
        return "routed_to_action_below_threshold"
    return "routed_to_action_auto_off"


def _build_canonical_from_request(
    request: PreBookingInquiryInput,
) -> CanonicalInboundMessage:
    selected_property_code = (request.property_external_id or "").strip()
    property_candidates: List[Dict[str, Any]] = []
    if selected_property_code:
        property_candidates.append(
            {
                "candidate_type": "property_code",
                "value": selected_property_code,
                "confidence": 1.0,
                "source": "prebooking_request",
            }
        )

    return CanonicalInboundMessage(
        source_channel="email",
        source_provider=request.platform or "email",
        source_thread_id=request.thread_id or "",
        source_message_id=request.message_id or "",
        sender_role="guest",
        sender_display_name=request.guest_name or "Guest",
        sender_address="",
        sent_at=datetime.now(UTC),
        raw_subject="",
        latest_guest_turn=request.message or "",
        prior_thread_context=request.conversation_context or "",
        full_message_text=request.message or "",
        structured_asks=list(request.structured_asks or []),
        prior_operator_commitments=[],
        property_binding_candidates=property_candidates,
        channel_constraints={},
        parser_used="prebooking_request",
        parser_version="v1",
        parser_notes=[],
        latest_turn_confidence=0.0,
        latest_turn_extracted=bool(request.conversation_context and request.message),
        guest_name=request.guest_name or "Guest",
        guest_email="",
    )


def _requested_nights(request: PreBookingInquiryInput) -> Optional[int]:
    if (
        request.requested_check_in is None
        or request.requested_check_out is None
        or request.requested_check_out <= request.requested_check_in
    ):
        return None
    return (request.requested_check_out - request.requested_check_in).days


def _brain_missing_knowledge_topics(brain_result: PreBookingDraftResult) -> List[str]:
    record = brain_result.audit_record
    if record is None:
        return []
    topics: List[str] = []
    for decision in record.decisions:
        for item in decision.missing_info or []:
            topic = str(item or "").strip()
            if not topic or topic == _STUB_SPECIALIST_SENTINEL:
                continue
            topics.append(topic)
    return sorted(set(topics))


def _resolve_brain_draft_confidence(
    brain_result: PreBookingDraftResult,
) -> Optional[float]:
    """Best-effort confidence extraction for pre-booking persistence.

    The intended source is brain_result.brain_draft.confidence. If that
    ever arrives unset due to an upstream wiring regression, fall back to
    the audit-layer final response and then the policy confidence so we do
    not silently degrade persisted rows to intent_only.
    """
    candidates = [
        getattr(getattr(brain_result, "brain_draft", None), "confidence", None),
        getattr(getattr(getattr(brain_result, "audit_record", None), "final_response", None), "confidence", None),
        getattr(getattr(getattr(brain_result, "audit_record", None), "policy", None), "confidence", None),
    ]
    for value in candidates:
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            logger.warning(
                "[PreBookingLifecycle] ignoring non-numeric brain draft confidence candidate: %r",
                value,
            )
    return None


async def execute_pre_booking_lifecycle(
    *,
    request: PreBookingInquiryInput,
    classification: PreBookingClassificationStage,
    decision_stage: PreBookingDecisionStage,
    draft_stage: PreBookingDraftStage,
) -> Dict[str, Any]:
    draft_id = f"INQ-{_uuid.uuid4().hex[:8].upper()}"
    save_result = SaveInquiryResult(inserted=False, status="save_failed")
    is_brain_path = (
        draft_stage.draft_source == "messaging_brain"
        or request.brain_draft_confidence is not None
    )

    if request.db:
        inbound = _build_canonical_from_request(request)

        # Phase 1 confidence split. Choose confidence_source based on what
        # actually produced this row:
        #   - knowledge gap held the inquiry         → gap_blocked
        #   - reviewer held the draft                → held_for_review
        #   - brain composed and reviewer accepted   → model_composer
        #   - legacy path (no brain confidence set)  → intent_only
        # The explicit override on the request wins when the caller knows
        # better (e.g. the email_dispatch exception fallback path will pass
        # 'exception_fallback' so we can measure how often it fires).
        if request.confidence_source_override:
            resolved_confidence_source = request.confidence_source_override
        elif decision_stage.missing_knowledge_topics:
            resolved_confidence_source = "gap_blocked"
        elif request.review_verdict == "hold":
            resolved_confidence_source = "held_for_review"
        elif request.brain_draft_confidence is not None:
            resolved_confidence_source = "model_composer"
        else:
            resolved_confidence_source = "intent_only"

        # draft_confidence is only meaningful when the brain produced a
        # sendable draft. Gap-blocked and held-for-review rows record
        # NULL so the autonomy gate cannot auto-send them.
        if resolved_confidence_source in {"gap_blocked", "held_for_review"}:
            resolved_draft_confidence: Optional[float] = None
        else:
            resolved_draft_confidence = request.brain_draft_confidence

        save_context = InquirySaveContext(
            draft_id=draft_id,
            company_id=request.company_id,
            selected_property_code=request.property_external_id,
            requested_check_in=request.requested_check_in,
            requested_check_out=request.requested_check_out,
            requested_guests=request.requested_guests,
            intent=classification.intent,
            confidence=classification.confidence,
            draft_text=draft_stage.draft_text,
            draft_source=draft_stage.draft_source,
            policy_flags=decision_stage.policy_result.flags,
            policy_warnings=decision_stage.policy_result.warnings,
            decision=decision_stage.decision.value,
            guest_thread_id=request.guest_thread_id,
            blocked_by_gap_topics=list(decision_stage.missing_knowledge_topics or []),
            triggered_by=(
                "auto_fresh"
                if not is_brain_path and decision_stage.decision == SendDecision.SEND_NOW
                else None
            ),
            intent_confidence=classification.confidence,
            draft_confidence=resolved_draft_confidence,
            confidence_source=resolved_confidence_source,
            review_verdict=request.review_verdict,
            autonomy_decision=_resolve_autonomy_decision(
                approval_mode=decision_stage.approval_mode,
                decision=decision_stage.decision,
                missing_knowledge_topics=list(decision_stage.missing_knowledge_topics or []),
                policy_warnings=list(decision_stage.policy_result.warnings or []),
                review_verdict=request.review_verdict,
            ),
        )
        save_result = await save_inquiry_from_canonical(
            db=request.db,
            inbound=inbound,
            context=save_context,
            normalization_kwargs={
                "parser_notes_append": (
                    ([classification.metadata.audit_payload()] if classification.metadata is not None else [])
                    + list(classification.shadow_parser_notes or [])
                ),
            },
        )

    inquiry_saved = bool(save_result)
    sent = False
    await send_prebooking_review_alert(
        company_id=request.company_id,
        draft_id=draft_id,
        platform=request.platform,
        guest_name=request.guest_name,
        message=request.message,
        draft_text=draft_stage.draft_text,
        decision=decision_stage.decision,
        approval_mode=decision_stage.approval_mode,
        flags=decision_stage.policy_result.flags,
        warnings=decision_stage.policy_result.warnings,
        property_name=request.property_data.get("property_name", request.property_external_id),
        review_window_hours=decision_stage.auto_send_policy.review_window_hours,
        review_verdict=request.review_verdict,
    )

    if decision_stage.approval_mode == "required":
        await _log_required_mode_event(
            company_id=request.company_id,
            property_external_id=request.property_external_id,
            draft_id=draft_id,
            db=request.db,
        )

    return {
        "saved": inquiry_saved,
        "save_status": save_result.status,
        "save_error_type": save_result.error_type,
        "save_error_message": save_result.error_message,
        "guest_thread_id": save_result.guest_thread_id,
        "draft_id": draft_id,
        "draft_text": draft_stage.draft_text,
        "draft_source": draft_stage.draft_source,
        "intent": classification.intent,
        "confidence": classification.confidence,
        "decision": decision_stage.decision.value,
        "sent": sent,
        "approval_mode": decision_stage.approval_mode,
        "policy_flags": decision_stage.policy_result.flags,
        "policy_warnings": decision_stage.policy_result.warnings,
        "message_id": request.message_id,
        "thread_id": request.thread_id,
    }


async def run_brain_pre_booking_lifecycle(
    *,
    brain_result: PreBookingDraftResult,
    company_id: UUID,
    api_key: str,
    force_approval_mode: Optional[str],
    db,
    guest_thread_id: Optional[str],
    reviewed_draft_text: str,
    reviewer_flags: Optional[List[str]] = None,
    reviewer_warnings: Optional[List[str]] = None,
    # Phase 1 confidence split. The caller (email_dispatch) knows the
    # reviewer's verdict from _review_brain_pre_booking_draft; threading it
    # forward here means execute_pre_booking_lifecycle can tag the row's
    # confidence_source and review_verdict correctly without needing to
    # reach back through the orchestrator.
    review_verdict: Optional[str] = None,
) -> Dict[str, Any]:
    inquiry = brain_result.inquiry
    resolved_brain_draft_confidence = _resolve_brain_draft_confidence(brain_result)
    request = PreBookingInquiryInput(
        thread_id=inquiry.thread_id,
        platform=inquiry.platform,
        guest_name=inquiry.guest_name,
        message=inquiry.message_text,
        property_external_id=inquiry.property_code,
        company_id=company_id,
        api_key=api_key,
        property_data=dict(brain_result.context.property_data or {}),
        operator_policies=dict(brain_result.context.operator_policies or {}),
        structured_asks=list(inquiry.structured_asks or []),
        conversation_context=inquiry.conversation_context or "",
        requested_check_in=inquiry.requested_check_in,
        requested_check_out=inquiry.requested_check_out,
        requested_guests=inquiry.requested_guests,
        message_id=inquiry.message_id,
        force_approval_mode=force_approval_mode,
        db=db,
        guest_thread_id=guest_thread_id,
        # Real brain confidence — distinct from the keyword classifier's
        # intent confidence that classification.confidence carries.
        brain_draft_confidence=resolved_brain_draft_confidence,
        review_verdict=review_verdict,
    )
    missing_knowledge_topics = _brain_missing_knowledge_topics(brain_result)
    classification = PreBookingClassificationStage(
        intent=brain_result.legacy_intent or "general",
        confidence=float(brain_result.intent_confidence or 0.0),
        metadata=None,
        shadow_parser_notes=[],
    )
    approval_mode = force_approval_mode or "required"
    policy_outcome = evaluate_pre_booking_policy(
        message=request.message,
        intent=classification.intent,
        confidence=classification.confidence,
        requested_nights=_requested_nights(request),
        requested_guests=request.requested_guests,
        property_data=request.property_data,
        operator_policies=request.operator_policies,
        auto_send_threshold=_BRAIN_DEFAULT_POLICY.auto_send_threshold,
        flag_pricing_inquiries=_BRAIN_DEFAULT_POLICY.flag_pricing_inquiries,
        flag_pet_inquiries=_BRAIN_DEFAULT_POLICY.flag_pet_inquiries,
        approval_mode=approval_mode,
        missing_knowledge_topics=missing_knowledge_topics,
    )
    draft_stage = PreBookingDraftStage(
        draft_text=reviewed_draft_text,
        draft_source="messaging_brain",
    )
    policy_outcome = apply_pre_booking_draft_source_policy(
        outcome=policy_outcome,
        draft_source=draft_stage.draft_source,
        intent=classification.intent,
        message=request.message,
    )
    decision_stage = PreBookingDecisionStage(
        approval_mode=approval_mode,
        auto_send_policy=_BRAIN_DEFAULT_POLICY,
        policy_result=PolicyCheckResult(
            flags=list(policy_outcome.flags),
            warnings=list(policy_outcome.warnings),
            block_send=policy_outcome.block_send,
        ),
        missing_knowledge_topics=list(missing_knowledge_topics),
        knowledge_gap_analysis=None,
        decision=SendDecision.HOLD,
    )
    if reviewer_flags:
        decision_stage.policy_result.flags.extend(reviewer_flags)
    if reviewer_warnings:
        decision_stage.policy_result.warnings.extend(reviewer_warnings)
    return await execute_pre_booking_lifecycle(
        request=request,
        classification=classification,
        decision_stage=decision_stage,
        draft_stage=draft_stage,
    )
