from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import text

from app.services.messaging_brain.persistence.prebooking_inquiry_types import (
    PolicyCheckResult,
    PreBookingClassificationStage,
    PreBookingDecisionStage,
    SendDecision,
)
from app.services.messaging_brain.agents.deterministic_intake_prefilter import (
    legacy_intent_from_classification,
)
from app.services.messaging_brain.policy.platform_compliance import (
    apply_pre_booking_draft_source_policy,
    evaluate_pre_booking_policy,
)
from app.services.messaging_brain.pre_booking import (
    EscapiaContextAdapter,
    EscapiaContextPayload,
    PreBookingDraftResult,
    PreBookingInquiry,
)
from app.services.messaging_brain.pre_booking_lifecycle import (
    _BRAIN_DEFAULT_POLICY,
    _brain_missing_knowledge_topics,
    _requested_nights,
)
from app.services.messaging_brain.persistence.prebooking_inquiry_types import (
    PreBookingDraftStage,
    PreBookingInquiryInput,
    _pg_text_array_literal,
)
from app.services.messaging_brain.orchestrator import GuestMessageBrainOrchestrator
from app.services.orchestration.messaging_brain_contracts import RecommendedAction
from app.services.operator.prebooking_queue_service import get_prebooking_queue_service

logger = logging.getLogger(__name__)


def _safe_json_list(value: Any) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return []
    return value or []


async def _hydrate_inquiry_context(
    *,
    db,
    tenant_id: str,
    operator_id: str,
    row,
) -> Dict[str, Any]:
    from app.api.v1.endpoints.operator_prebooking import _build_inbox_adapter_for_tenant

    parsed = None
    parser_mode = "stored_inquiry"
    gmail_poller = await _build_inbox_adapter_for_tenant(db, operator_id, tenant_id)
    if gmail_poller and row.gmail_message_id:
        try:
            token = await gmail_poller.token_manager.get_access_token()
            headers = gmail_poller.token_manager.auth_header(token)
            raw = await gmail_poller._get_full_message(row.gmail_message_id, headers)
            if raw:
                parsed = await gmail_poller._parse_with_ota_fallback(raw)
                if parsed:
                    parsed.property_code = await gmail_poller._resolve_property_code(parsed)
                    await gmail_poller._enrich_with_link_context(parsed)
                    parser_mode = parsed.parser_source or "gmail_refetch"
        except Exception as exc:
            logger.warning("[ShipI] regenerate Gmail refetch failed for %s: %s", row.draft_id, exc)

    if parsed:
        message_text = parsed.latest_guest_message or parsed.body or row.message_text or ""
        guest_name = parsed.guest_name or row.guest_name or "Guest"
        guest_email = parsed.guest_email or row.guest_email or ""
        property_external_id = parsed.property_code or row.property_external_id or ""
        requested_check_in = parsed.requested_check_in or row.requested_check_in
        requested_check_out = parsed.requested_check_out or row.requested_check_out
        requested_guests = parsed.requested_guests if parsed.requested_guests is not None else row.requested_guests
        platform = parsed.platform or row.platform or "email"
        property_data, operator_policies = await gmail_poller._load_property_context(parsed.property_code or row.property_external_id or "")
        property_data["operator_name"] = gmail_poller._get_operator_name()
        parser_source = parsed.parser_source or "gmail_refetch"
        asks = parsed.asks or []
        platform_listing_id = parsed.platform_listing_id or ""
        platform_unit_id = parsed.platform_unit_id or ""
        conversation_context = parsed.conversation_context or ""
        thread_id = parsed.thread_id or getattr(row, "gmail_thread_id", None) or getattr(row, "thread_id", None) or ""
        message_id = parsed.message_id or getattr(row, "gmail_message_id", None) or getattr(row, "message_id", None) or ""
    else:
        message_text = row.message_text or ""
        guest_name = row.guest_name or "Guest"
        guest_email = row.guest_email or ""
        property_external_id = row.property_external_id or ""
        requested_check_in = row.requested_check_in
        requested_check_out = row.requested_check_out
        requested_guests = row.requested_guests
        platform = row.platform or "email"
        property_data = {}
        operator_policies = {"min_nights": 3, "pet_policy": "not_allowed"}
        if gmail_poller:
            property_data, operator_policies = await gmail_poller._load_property_context(property_external_id)
            property_data["operator_name"] = gmail_poller._get_operator_name()
        parser_source = "stored_inquiry"
        asks = []
        platform_listing_id = ""
        platform_unit_id = ""
        conversation_context = ""
        if gmail_poller:
            newest_turn, older_context = gmail_poller._parser.dissect_thread_content(message_text)
            message_text = newest_turn or message_text
            conversation_context = older_context
        thread_id = getattr(row, "gmail_thread_id", None) or getattr(row, "thread_id", None) or ""
        message_id = getattr(row, "gmail_message_id", None) or getattr(row, "message_id", None) or ""

    return {
        "parser_mode": parser_mode,
        "message_text": message_text,
        "guest_name": guest_name,
        "guest_email": guest_email,
        "property_external_id": property_external_id,
        "requested_check_in": requested_check_in,
        "requested_check_out": requested_check_out,
        "requested_guests": requested_guests,
        "platform": platform,
        "property_data": property_data,
        "operator_policies": operator_policies,
        "parser_source": parser_source,
        "asks": asks,
        "platform_listing_id": platform_listing_id,
        "platform_unit_id": platform_unit_id,
        "conversation_context": conversation_context,
        "thread_id": thread_id,
        "message_id": message_id,
    }


async def _run_brain_prebooking_retry(
    *,
    db,
    tenant_id: str,
    operator_id: str,
    row,
) -> tuple[PreBookingDraftResult, str, List[str], List[str], Dict[str, Any]]:
    from app.services.connectors.adapter_backed_booking_data_provider import AdapterBackedBookingDataProvider
    from app.services.integrations.email_dispatch import _review_brain_pre_booking_draft
    from app.services.messaging_brain.agents.booking_context_agent import BookingContextAgent

    hydrated = await _hydrate_inquiry_context(
        db=db,
        tenant_id=tenant_id,
        operator_id=operator_id,
        row=row,
    )

    inquiry = PreBookingInquiry(
        inquiry_id=row.draft_id,
        tenant_id=tenant_id,
        channel="email",
        transport_provider=hydrated["parser_source"] or "stored_inquiry",
        context_provider="escapia",
        platform=hydrated["platform"],
        guest_name=hydrated["guest_name"],
        message_text=hydrated["message_text"],
        property_code=hydrated["property_external_id"],
        platform_listing_id=hydrated["platform_listing_id"],
        platform_unit_id=hydrated["platform_unit_id"],
        message_id=hydrated["message_id"],
        thread_id=hydrated["thread_id"],
        guest_email=hydrated["guest_email"],
        requested_check_in=hydrated["requested_check_in"],
        requested_check_out=hydrated["requested_check_out"],
        requested_guests=hydrated["requested_guests"],
        structured_asks=list(hydrated["asks"] or []),
        conversation_context=hydrated["conversation_context"] or "",
        metadata={
            "raw_subject": "",
            "platform_listing_id": hydrated["platform_listing_id"],
            "platform_unit_id": hydrated["platform_unit_id"],
        },
    )

    booking_context_agent = BookingContextAgent(
        data_provider=AdapterBackedBookingDataProvider(
            company_id=UUID(str(tenant_id)),
            provider_key="escapia",
        ),
        db_session=db,
    )
    context_adapter = EscapiaContextAdapter(booking_context_agent=booking_context_agent)
    context = await context_adapter.load_context(
        inquiry=inquiry,
        payload=EscapiaContextPayload(
            property_data=hydrated["property_data"],
            operator_policies=hydrated["operator_policies"],
        ),
        db_session=db,
    )
    inbound = inquiry.to_inbound_message(context_overlay=context.overlay)
    brain = GuestMessageBrainOrchestrator()
    draft = await brain.handle_inbound_message(
        inbound,
        db_session=db,
        shadow_mode=False,
    )
    audit_record = getattr(getattr(brain, "_audit", None), "last_record", None)
    classification = getattr(audit_record, "classification", None)
    classifier_metadata = getattr(audit_record, "classifier_metadata", None)
    brain_result = PreBookingDraftResult(
        inquiry=inquiry,
        context=context,
        inbound_message=inbound,
        brain_draft=draft,
        effective_action=RecommendedAction.ESCALATE if draft.final_action == RecommendedAction.ESCALATE else RecommendedAction.DRAFT_ONLY,
        requires_operator_review=draft.final_action != RecommendedAction.AUTO_SEND,
        audit_record=audit_record,
        legacy_intent=(
            str(
                getattr(classifier_metadata, "legacy_intent", None)
                or legacy_intent_from_classification(
                    classification,
                    message_text=inbound.text or "",
                )
            )
            if classification is not None else
            "general"
        ),
        intent_confidence=float(getattr(classification, "confidence", 0.0) or 0.0),
    )
    reviewed_draft_text, reviewer_flags, reviewer_warnings, _review_verdict = await _review_brain_pre_booking_draft(
        guest_name=inquiry.guest_name,
        platform=inquiry.platform,
        message=inquiry.message_text,
        intent=inquiry.structured_asks[0] if inquiry.structured_asks else "general",
        property_data=hydrated["property_data"],
        operator_policies=hydrated["operator_policies"],
        draft_text=brain_result.brain_draft.response_text,
        tenant_id=UUID(str(tenant_id)),
    )
    return brain_result, reviewed_draft_text, reviewer_flags, reviewer_warnings, hydrated


async def reevaluate_existing_prebooking_inquiry(
    *,
    db,
    tenant_id: str,
    operator_id: str,
    draft_id: str,
    auto_send_if_allowed: bool,
) -> Dict[str, Any]:
    row = (
        await db.execute(
            text(
                """
                SELECT draft_id, platform, guest_name, guest_email, message_text,
                       gmail_message_id, gmail_thread_id, property_external_id,
                       requested_check_in, requested_check_out, requested_guests,
                       status, thread_id, message_id
                FROM pre_booking_inquiries
                WHERE draft_id = :did AND company_id = CAST(:tid AS uuid)
                LIMIT 1
                """
            ),
            {"did": draft_id, "tid": tenant_id},
        )
    ).fetchone()
    if not row:
        return {"ok": False, "error": "Draft not found", "draft_id": draft_id}
    if str(getattr(row, "status", "") or "").lower() in {"replied", "rejected"}:
        return {"ok": False, "error": f"Draft already {row.status}", "draft_id": draft_id}

    brain_result, reviewed_draft_text, reviewer_flags, reviewer_warnings, hydrated = await _run_brain_prebooking_retry(
        db=db,
        tenant_id=tenant_id,
        operator_id=operator_id,
        row=row,
    )

    request = PreBookingInquiryInput(
        thread_id=hydrated["thread_id"],
        platform=hydrated["platform"],
        guest_name=hydrated["guest_name"],
        message=hydrated["message_text"],
        property_external_id=hydrated["property_external_id"],
        company_id=UUID(str(tenant_id)),
        api_key="",
        property_data=dict(hydrated["property_data"] or {}),
        operator_policies=dict(hydrated["operator_policies"] or {}),
        structured_asks=list(hydrated["asks"] or []),
        conversation_context=hydrated["conversation_context"] or "",
        requested_check_in=hydrated["requested_check_in"],
        requested_check_out=hydrated["requested_check_out"],
        requested_guests=hydrated["requested_guests"],
        message_id=hydrated["message_id"],
        force_approval_mode=None,
        db=db,
        guest_thread_id=getattr(row, "guest_thread_id", None),
    )
    missing_knowledge_topics = _brain_missing_knowledge_topics(brain_result)
    classification = PreBookingClassificationStage(
        intent=brain_result.legacy_intent or "general",
        confidence=float(brain_result.intent_confidence or 0.0),
        metadata=None,
        shadow_parser_notes=[],
    )
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
        approval_mode="required",
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
        approval_mode="required",
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

    sent = False
    final_status = "pending_review"
    final_reply = None
    replied_at_sql = "NULL"
    triggered_by = None
    if auto_send_if_allowed:
        logger.info(
            "[PreBookingRetry] auto_send_if_allowed ignored for %s; regenerate remains review-first",
            draft_id,
        )

    await db.execute(
        text(
            f"""
            UPDATE pre_booking_inquiries
            SET guest_name = :guest_name,
                guest_email = COALESCE(NULLIF(:guest_email, ''), guest_email),
                message_text = :message_text,
                draft_text = :draft_text,
                intent = :intent,
                confidence = :confidence,
                property_external_id = :property_external_id,
                requested_check_in = :requested_check_in,
                requested_check_out = :requested_check_out,
                requested_guests = :requested_guests,
                policy_flags = CAST(:policy_flags AS jsonb),
                policy_warnings = CAST(:policy_warnings AS jsonb),
                blocked_by_gap_topics = CAST(:blocked_topics AS text[]),
                parser_source = COALESCE(NULLIF(:parser_source, ''), parser_source),
                extracted_asks = CAST(:asks_json AS jsonb),
                platform_listing_id = CASE WHEN :listing_id = '' THEN platform_listing_id ELSE :listing_id END,
                platform_unit_id = CASE WHEN :unit_id = '' THEN platform_unit_id ELSE :unit_id END,
                status = :status,
                final_reply = COALESCE(:final_reply, final_reply),
                replied_at = {replied_at_sql},
                triggered_by = COALESCE(:triggered_by, triggered_by)
            WHERE draft_id = :draft_id
              AND company_id = CAST(:tenant_id AS uuid)
            """
        ),
        {
            "guest_name": hydrated["guest_name"],
            "guest_email": hydrated["guest_email"],
            "message_text": hydrated["message_text"],
            "draft_text": draft_stage.draft_text,
            "intent": classification.intent,
            "confidence": classification.confidence,
            "property_external_id": hydrated["property_external_id"],
            "requested_check_in": hydrated["requested_check_in"],
            "requested_check_out": hydrated["requested_check_out"],
            "requested_guests": hydrated["requested_guests"],
            "policy_flags": json.dumps(decision_stage.policy_result.flags),
            "policy_warnings": json.dumps(decision_stage.policy_result.warnings),
            "blocked_topics": _pg_text_array_literal(decision_stage.missing_knowledge_topics),
            "parser_source": hydrated["parser_source"],
            "asks_json": json.dumps(list(hydrated["asks"] or [])),
            "listing_id": hydrated["platform_listing_id"],
            "unit_id": hydrated["platform_unit_id"],
            "status": final_status,
            "final_reply": final_reply,
            "triggered_by": triggered_by,
            "draft_id": draft_id,
            "tenant_id": tenant_id,
        },
    )
    await get_prebooking_queue_service().sync_draft(db, tenant_id, draft_id)
    await db.commit()
    return {
        "ok": True,
        "draft_id": draft_id,
        "draft_text": draft_stage.draft_text,
        "message_text": hydrated["message_text"],
        "intent": classification.intent,
        "confidence": classification.confidence,
        "draft_source": draft_stage.draft_source,
        "parser_source": hydrated["parser_source"],
        "parser_mode": hydrated["parser_mode"],
        "property_external_id": hydrated["property_external_id"],
        "asks": list(hydrated["asks"] or []),
        "blocked_by_gap_topics": list(decision_stage.missing_knowledge_topics or []),
        "sent": sent,
        "status": final_status,
        "triggered_by": triggered_by or "",
    }
