from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple
from uuid import UUID

from app.db.session_safety import safe_rollback
from app.services.integrations.non_guest_patterns import NON_GUEST_REGISTRY
from app.services.messaging.message_event_store import update_normalization_outcome
from app.services.messaging_brain.property_resolution_writeback import (
    get_property_resolution_writeback,
)
from app.services.messaging_brain.inbound_classification_store import (
    persist_gate_decision,
)
from app.services.messaging_brain.inbound_message_gate import (
    InboundClassification,
    InboundMessageGate,
)
from app.services.orchestration.messaging_brain_contracts import RecommendedAction
from app.services.operator.stay_action_agent import StayActionAgent
from sqlalchemy import text

logger = logging.getLogger(__name__)
_DETERMINISTIC_GUEST_PARSER_PREFIXES = (
    "ota_parser_",
    "direct_website_form_parser",
)


def _normalization_source_channel() -> str:
    return "email"


def _message_id(parsed) -> str:
    return getattr(parsed, "message_id", "") or getattr(parsed, "gmail_message_id", "") or ""


def _pre_booking_route_outcome(result: Dict[str, Any]) -> str:
    save_status = (result.get("save_status") or "").strip().lower()
    if save_status == "saved":
        return "pre_booking_new"
    if save_status == "duplicate":
        return "pre_booking_duplicate"
    if save_status == "save_failed":
        return "pre_booking_save_failed"
    return "pre_booking_new" if result.get("saved") else "pre_booking_duplicate"


def _draft_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:8]


def _draft_preview(text: str, limit: int = 100) -> str:
    compact = " ".join((text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def _reservation_routing_parser_notes(parsed) -> list[dict[str, Any]]:
    notes: list[dict[str, Any]] = []
    metadata = getattr(parsed, "_reservation_routing_metadata", None)
    if isinstance(metadata, dict):
        notes.append(metadata)
    property_surface_audit = getattr(parsed, "property_mention_surface_audit", None)
    if isinstance(property_surface_audit, dict) and property_surface_audit:
        notes.append(property_surface_audit)
    return notes


def _guest_session_action_priority(session_row: Any) -> str:
    phase = (getattr(session_row, "phase", "") or "").strip().lower()
    if phase in {"arrival_day", "in_stay", "departure_day"}:
        return "high"
    return "medium"


async def _queue_guest_session_review_action(
    *,
    db: Any,
    tenant_id: UUID,
    session_row: Any,
    action_type: str,
    payload: Dict[str, Any],
    priority: str,
) -> None:
    if not db:
        return

    session_id = str(getattr(session_row, "session_id", "") or "")
    if not session_id:
        return

    await db.execute(
        text(
            """
            INSERT INTO operator_workflow_action_queue
                (tenant_id, workflow_type, workflow_ref, action_type, status, priority,
                 property_code, payload_json, result_json, due_at, updated_at, completed_at)
            VALUES
                (CAST(:tid AS uuid), 'stay', :workflow_ref, :action_type, 'ready', :priority,
                 :property_code, CAST(:payload_json AS jsonb), '{}'::jsonb, NULL, NOW(), NULL)
            ON CONFLICT (workflow_type, workflow_ref, action_type) DO UPDATE SET
                status = 'ready',
                priority = EXCLUDED.priority,
                property_code = EXCLUDED.property_code,
                payload_json = EXCLUDED.payload_json,
                result_json = '{}'::jsonb,
                due_at = NULL,
                updated_at = NOW(),
                completed_at = NULL
            """
        ),
        {
            "tid": str(tenant_id),
            "workflow_ref": session_id,
            "action_type": action_type,
            "priority": priority,
            "property_code": getattr(session_row, "property_code", "") or "",
            "payload_json": json.dumps(payload),
        },
    )


async def _build_in_stay_review_result(
    *,
    services: "EmailDispatchServices",
    parsed,
    session_row: Any,
):
    from app.services.messaging_brain.session_channel_adapter import run_session_channel_message

    body_text = (
        getattr(parsed, "latest_guest_message", "")
        or getattr(parsed, "body", "")
        or ""
    ).strip()
    if not body_text:
        body_text = (getattr(parsed, "full_body", "") or "").strip()

    provider = (
        getattr(parsed, "source_provider", "")
        or getattr(parsed, "platform", "")
        or "email"
    )
    thread_id = (
        getattr(parsed, "source_interaction_id", "")
        or getattr(parsed, "thread_id", "")
        or getattr(parsed, "gmail_thread_id", "")
        or getattr(session_row, "token", "")
        or ""
    )
    source_message_id = _message_id(parsed)
    parser_confidence = 0.92 if getattr(parsed, "conversation_context", None) else 0.72

    return await run_session_channel_message(
        message_text=body_text,
        db_session=services.db,
        db_row=session_row,
        session_tenant_id=services.company_id,
        token=getattr(session_row, "token", "") or "",
        channel="email",
        source_provider=str(provider),
        source_message_id=source_message_id,
        source_thread_id=thread_id,
        raw_subject=getattr(parsed, "subject", "") or "",
        received_at=getattr(parsed, "received_at", None),
        parser_used=getattr(parsed, "parser_source", "") or "email_dispatch_in_stay",
        parser_confidence=parser_confidence,
        full_thread_text=(
            getattr(parsed, "conversation_context", "")
            or getattr(parsed, "full_body", "")
            or getattr(parsed, "body", "")
            or ""
        ),
        structured_asks=list(getattr(parsed, "asks", []) or []),
    )


def _should_admit_retryable_gate_error(parsed) -> bool:
    parser_source = (getattr(parsed, "parser_source", "") or "").strip().lower()
    if not any(parser_source.startswith(prefix) for prefix in _DETERMINISTIC_GUEST_PARSER_PREFIXES):
        return False
    body_text = (
        getattr(parsed, "latest_guest_message", "")
        or getattr(parsed, "body", "")
        or getattr(parsed, "full_body", "")
        or ""
    ).strip()
    if len(body_text) < 12:
        return False
    if not ((getattr(parsed, "reply_channel_address", "") or "").strip() or (getattr(parsed, "guest_email", "") or "").strip()):
        return False
    non_guest_match = NON_GUEST_REGISTRY.classify(
        from_header=getattr(parsed, "raw_from", "") or "",
        subject=getattr(parsed, "subject", "") or "",
        plain_text=body_text,
        raw_html="",
    )
    return non_guest_match is None


async def _maybe_writeback_property_resolution(
    *,
    db_session: Any,
    tenant_id: UUID,
    draft_id: str,
    selected_property_code: str,
    selected_property_match_type: str,
) -> None:
    if not db_session or not draft_id or not selected_property_code:
        return
    writeback = get_property_resolution_writeback()
    await writeback.writeback_for_inquiry(
        db_session,
        tenant_id=tenant_id,
        draft_id=draft_id,
        resolved_property_code=selected_property_code,
        match_type=selected_property_match_type,
    )


def _review_warning(
    *,
    review_result,
    original_text: str,
    final_text: str,
) -> str:
    flags = ",".join(review_result.flags or []) or "none"
    rationale = " ".join((review_result.rationale or "").split())[:240] or "none"
    return (
        "adversarial_review:"
        f"verdict={review_result.verdict}"
        f"|source={review_result.review_source}"
        f"|flags={flags}"
        f"|rationale={rationale}"
        f"|revised={'true' if final_text != original_text else 'false'}"
        f"|orig_hash={_draft_hash(original_text)}"
        f"|final_hash={_draft_hash(final_text)}"
        f"|orig_preview={_draft_preview(original_text)}"
        f"|final_preview={_draft_preview(final_text)}"
    )


async def _review_brain_pre_booking_draft(
    *,
    guest_name: str,
    platform: str,
    message: str,
    intent: str,
    property_data: Dict[str, Any],
    operator_policies: Dict[str, Any],
    draft_text: str,
    tenant_id: UUID | None,
) -> tuple[str, list[str], list[str], str]:
    """Run the adversarial reviewer on a brain-composed draft.

    Returns ``(final_text, additional_flags, additional_warnings, review_verdict)``.

    ``review_verdict`` is one of ``"pass" | "revise" | "hold"`` and is
    threaded forward to persistence so the row's confidence_source and
    review_verdict columns can be tagged correctly:

      pass   — reviewer accepted the brain draft unchanged.
      revise — reviewer polished the draft text; final_text reflects the
               polished version.
      hold   — reviewer rejected the draft. final_text is the empty string.
               Persistence tags the row as confidence_source='held_for_review'
               with NULL draft_confidence; the operator-facing SMS and
               dashboard branch on review_verdict='hold' rather than on
               text content. The previous _fallback_draft substitution
               was retired in Commit 2C-flip — it hid the truth that the
               reviewer said no, by replacing the held draft with chipper
               boilerplate that operators read as "AI is confident enough
               to send this." The placeholder-guard fallback (further
               down in this function) is a different code path and
               remains intact.
    """
    from app.services.messaging_brain.pre_booking import _fallback_draft
    from app.services.messaging_brain.grounding.prebooking_grounding import (
        _build_prebooking_grounding_context,
    )
    from app.services.messaging_brain.grounding.response_reviewer import (
        match_placeholder_pattern,
        review_concierge_response,
    )

    source_context = _build_prebooking_grounding_context(
        guest_name=guest_name,
        platform=platform,
        message=message,
        intent=intent,
        property_data=property_data,
        operator_policies=operator_policies,
    )
    review_result = await review_concierge_response(
        guest_message=message,
        draft_response=draft_text,
        source_context=source_context,
        lifecycle_stage="pre_booking",
        property_name=property_data.get("property_name", ""),
        tenant_id=tenant_id,
    )

    final_text = draft_text
    additional_flags: list[str] = []
    review_verdict = "pass"
    if review_result.verdict == "revise" and review_result.reviewed_response:
        final_text = review_result.reviewed_response.strip()
        review_verdict = "revise"
        additional_flags.append(
            "ℹ️ Adversarial review revised the brain draft before operator display"
        )
    elif review_result.verdict in {"human_review", "block"}:
        # Commit 2C-flip: the previous behavior here was to substitute a
        # _fallback_draft boilerplate. That hid the reviewer's hold from
        # operators by replacing the held text with chipper "happy to
        # confirm details" copy, which operators read as a confident AI
        # draft. Persistence now tags the row review_verdict='hold' +
        # confidence_source='held_for_review' with NULL draft_confidence;
        # the alert SMS and dashboard branch on the verdict, not on text.
        # Empty text is the honest signal: there is no draft to show.
        final_text = ""
        review_verdict = "hold"
        additional_flags.append(
            f"ℹ️ Adversarial review forced operator hold ({review_result.verdict})"
        )

    draft_placeholder_match = match_placeholder_pattern(draft_text)
    final_placeholder_match = match_placeholder_pattern(final_text)
    if draft_placeholder_match or final_placeholder_match:
        source_label = "draft" if draft_placeholder_match else "final"
        matched_pattern = draft_placeholder_match or final_placeholder_match or ""
        logger.warning(
            "[EmailDispatch] Defensive placeholder guard tripped: source=%s matched=%r "
            "draft_hash=%s final_hash=%s draft_preview=%r final_preview=%r",
            source_label,
            matched_pattern,
            _draft_hash(draft_text),
            _draft_hash(final_text),
            _draft_preview(draft_text),
            _draft_preview(final_text),
        )
        if final_placeholder_match:
            final_text = _fallback_draft(
                guest_name,
                intent,
                property_data,
                operator_policies,
            )
        additional_flags.append(
            "ℹ️ Defensive placeholder guard caught residual placeholder text"
        )
        additional_warnings = [
            f"defensive_placeholder_guard:source={source_label}|matched={matched_pattern}"
        ]
    else:
        additional_warnings = []

    additional_warnings.append(
        _review_warning(
            review_result=review_result,
            original_text=draft_text,
            final_text=final_text,
        )
    )
    logger.info(
        "[EmailDispatch] Brain draft adversarial review verdict=%s source=%s revised=%s "
        "orig_hash=%s final_hash=%s orig_preview=%r final_preview=%r flags=%s rationale=%r",
        review_result.verdict,
        review_result.review_source,
        final_text != draft_text,
        _draft_hash(draft_text),
        _draft_hash(final_text),
        _draft_preview(draft_text),
        _draft_preview(final_text),
        review_result.flags,
        review_result.rationale,
    )
    return final_text, additional_flags, additional_warnings, review_verdict


@dataclass
class EmailDispatchServices:
    company_id: UUID
    db: Any
    watched_email: str
    operator_name: str
    infer_property_match_type: Callable[[Any, str], str]
    load_property_context: Callable[[str], Awaitable[tuple[Dict[str, Any], Dict[str, Any]]]]
    store_thread_context: Callable[[Any, str], Awaitable[None]]
    maybe_record_pre_booking_gap: Callable[[Any, Dict[str, Any]], Awaitable[None]]
    save_fallback_pre_booking_inquiry: Callable[[Any, str], Awaitable[bool]]
    record_kb_gap: Callable[[Any, str, float, Dict[str, Any]], Awaitable[None]]
    record_property_binding_gap: Callable[[Any, str], Awaitable[None]]
    build_reply_sender: Callable[[], Any]
    generate_in_stay_reply: Callable[[str, Any], Awaitable[str]]
    load_review_event_policy: Callable[[], Awaitable[Dict[str, bool]]]
    find_session_by_reservation_context: Callable[[Any], Awaitable[Any]]
    create_provisional_session_from_system_event: Callable[[Any], Awaitable[bool]]
    persist_review_event: Callable[[Any, Any, Dict[str, bool]], Awaitable[None]]


# ─────────────────────────────────────────────────────────────────────────────
# Thread-identity inputs (single source of truth for keying)
#
# Both the early prompt-time history resolver and the later persistence
# layer need to ask `ensure_inquiry_thread` with IDENTICAL inputs so they
# match the same `guest_thread_id`. If they don't, follow-up drafts can
# load the wrong history (or no history) for threads where the inputs
# diverge — particularly when `parsed.property_code` is empty and only
# the display name is available, since `guest_thread_service` falls back
# to `(tenant_id, property_code, guest_name_norm)` matching there.
#
# This helper is the single source of truth for those inputs. Both the
# early resolver in dispatch and the late `_save_inquiry`-driven path go
# through it (or through the value computed from it). If any future caller
# needs to compute the same identity, route through this helper rather
# than recomputing the expression inline.
# ─────────────────────────────────────────────────────────────────────────────


def thread_identity_inputs(
    *,
    company_id: UUID,
    parsed,
) -> Dict[str, str]:
    """Return the kwargs `ensure_inquiry_thread` should be called with.

    Centralizes the identity expression so the early prompt-time resolver
    and the later `_save_inquiry`-driven persistence path cannot diverge.
    Returns a dict with keys matching `GuestThreadService.ensure_inquiry_thread`'s
    keyword arguments.
    """
    return {
        "tenant_id": str(company_id),
        "property_code": parsed.property_code or "",
        "guest_name": parsed.guest_name or "",
        "inquiry_thread_id": parsed.thread_id or "",
    }


async def _resolve_thread_identity_and_history(
    *,
    services: EmailDispatchServices,
    parsed,
) -> Tuple[Optional[str], str]:
    """Resolve guest_thread_id and load formatted prior turns.

    Returns a tuple of `(guest_thread_id, formatted_history_block)`.

    The guest_thread_id is the canonical identity for this conversation
    in the `guest_threads` table. It's used here to load prior turns for
    the prompt, AND it's threaded forward to the brain lifecycle
    persistence path so the row save uses the SAME ID rather than
    re-resolving from possibly-divergent inputs (the re-resolution would
    still match because both sites use `thread_identity_inputs()`, but
    threading the value forward avoids the redundant DB call AND
    eliminates any future risk of divergence).

    If anything fails — DB unavailable, schema missing, exception during
    lookup — returns `(None, "")` so callers fall through to existing
    behavior. Drafting MUST NOT fail because of history-load failure.
    """
    if not services.db:
        return None, ""

    try:
        from app.services.concierge.guest_thread_service import (
            get_guest_thread_service,
        )
        from app.services.messaging_brain.context.conversation_history import (
            load_history_for_prompt,
        )

        identity_kwargs = thread_identity_inputs(
            company_id=services.company_id,
            parsed=parsed,
        )
        guest_thread_id = await get_guest_thread_service().ensure_inquiry_thread(
            services.db,
            **identity_kwargs,
        )
        if not guest_thread_id:
            return None, ""

        history_block = await load_history_for_prompt(
            services.db,
            guest_thread_id=guest_thread_id,
            exclude_message_id=parsed.message_id or parsed.gmail_message_id or "",
        )
        return guest_thread_id, history_block
    except Exception as exc:
        # Never let history-load failure block drafting. Fall through to
        # whatever conversation_context the parser already extracted, and
        # let `_save_inquiry`'s own `ensure_inquiry_thread` call resolve
        # identity as the safety net.
        await safe_rollback(services.db)
        logger.warning(
            "[EmailDispatch] thread-identity resolution failed for %s: %s",
            parsed.guest_name,
            exc,
        )
        return None, ""


async def dispatch_pre_booking(
    *,
    services: EmailDispatchServices,
    parsed,
) -> str:
    from app.services.concierge.post_booking_routing import (
        is_non_pre_booking_intent,
        persist_inbound_from_inquiry,
    )
    from app.services.messaging_brain.agents.deterministic_intake_prefilter import (
        DeterministicIntakePreFilter,
        legacy_intent_from_classification,
    )
    from app.services.connectors.adapter_backed_booking_data_provider import (
        AdapterBackedBookingDataProvider,
    )
    from app.services.feature_flags import FeatureFlag, get_feature_flags
    from app.services.feature_flags import (
        is_brain_prebooking_lifecycle_primary_enabled,
    )
    from app.services.messaging_brain.agents.booking_context_agent import (
        BookingContextAgent,
    )
    from app.services.messaging_brain.pre_booking_lifecycle import (
        run_brain_pre_booking_lifecycle,
    )
    from app.services.messaging_brain.pre_booking import (
        EmailTransportAdapter,
        EscapiaContextAdapter,
        EscapiaContextPayload,
        PreBookingBrainOrchestrator,
        PreBookingProviderBinding,
    )
    from app.services.orchestration.messaging_brain_contracts import (
        InboundGuestMessage,
        MessagingLifecycle,
    )

    gate_enabled = False
    gate_review_all = False
    runtime_enabled = False
    shadow_mode = False
    brain_lifecycle_primary = False
    layer1_decision = (getattr(parsed, "intake_layer1_decision", "") or "").strip().lower()
    gate_uncertainty_note = ""

    async def _persist_fallback(reason: str) -> str:
        if await services.save_fallback_pre_booking_inquiry(parsed, reason):
            logger.warning(
                "[EmailDispatch] Saved fallback pre-booking inquiry for %s after routing failure",
                parsed.guest_name,
            )
            await services.record_kb_gap(
                parsed,
                "email_prebooking_fallback",
                0.0,
                {
                    "reason": "email_routing_fallback",
                    "error": reason[:200],
                    "link_context_summary": parsed.link_context_summary or "",
                    "parser_source": parsed.parser_source,
                    "asks": parsed.asks or [],
                    "platform_listing_id": parsed.platform_listing_id or "",
                    "platform_unit_id": parsed.platform_unit_id or "",
                },
            )
            await update_normalization_outcome(
                services.db,
                services.company_id,
                _normalization_source_channel(),
                _message_id(parsed),
                selected_property_code=parsed.property_code or "",
                selected_property_match_type=services.infer_property_match_type(parsed, parsed.property_code or ""),
                route_outcome="pre_booking_fallback",
                draft_source="fallback_saved",
                fallback_reason=reason[:400],
                parser_notes_append=_reservation_routing_parser_notes(parsed),
            )
            return "pre_booking_fallback"
        raise RuntimeError(f"pre-booking fallback save failed: {reason}")

    if services.db:
        try:
            flags = get_feature_flags(services.db)
            gate_enabled = await flags.is_enabled(
                FeatureFlag.INBOUND_MESSAGE_GATE_ENABLED,
                company_id=str(services.company_id),
                property_code=parsed.property_code or "",
            )
            gate_review_all = await flags.is_enabled(
                FeatureFlag.INBOUND_MESSAGE_GATE_REVIEW_ALL,
                company_id=str(services.company_id),
                property_code=parsed.property_code or "",
            )
            runtime_enabled = await flags.is_enabled(
                FeatureFlag.MESSAGING_BRAIN_RUNTIME,
                company_id=str(services.company_id),
                property_code=parsed.property_code or "",
            )
            shadow_mode = await flags.is_enabled(
                FeatureFlag.MESSAGING_BRAIN_SHADOW_MODE,
                company_id=str(services.company_id),
                property_code=parsed.property_code or "",
            )
            brain_lifecycle_primary = await is_brain_prebooking_lifecycle_primary_enabled(
                db=services.db,
                tenant_id=str(services.company_id),
                property_code=parsed.property_code or "",
            )
        except Exception:
            logger.exception("[EmailDispatch] Flag lookup failed, defaulting gate/brain off")

    try:
        if layer1_decision == "drop":
            await update_normalization_outcome(
                services.db,
                services.company_id,
                _normalization_source_channel(),
                _message_id(parsed),
                selected_property_code=parsed.property_code or "",
                selected_property_match_type=services.infer_property_match_type(parsed, parsed.property_code or ""),
                route_outcome="layer1_drop",
                draft_source="layer1",
                fallback_reason=(getattr(parsed, "intake_layer1_reason", "") or "")[:400],
                parser_notes_append=_reservation_routing_parser_notes(parsed),
            )
            return "dropped"

        should_run_gate = layer1_decision == "unclear"
        if should_run_gate and gate_enabled:
            gate = InboundMessageGate()
            decision = await gate.classify(
                tenant_id=services.company_id,
                from_header=parsed.raw_from or "",
                subject=parsed.subject or "",
                reply_to=parsed.reply_channel_address or None,
                x_template=None,
                x_category=None,
                return_path=None,
                body_text=parsed.full_body or parsed.body or "",
            )
            admit_on_uncertainty = (
                decision.classification == InboundClassification.UNCLEAR
                or (
                    decision.classification == InboundClassification.GUEST_MESSAGE
                    and not decision.should_proceed_as_guest
                )
            )
            proceeded_as_guest = decision.should_proceed_as_guest or admit_on_uncertainty
            routed_to_review = gate_review_all and not proceeded_as_guest
            await persist_gate_decision(
                decision=decision,
                tenant_id=services.company_id,
                gmail_message_id=parsed.gmail_message_id,
                source_message_id=_message_id(parsed),
                parser_source=parsed.parser_source,
                from_header=parsed.raw_from,
                subject=parsed.subject,
                proceeded_as_guest=proceeded_as_guest,
                routed_to_review=routed_to_review,
            )

            if decision.error:
                if decision.retryable and _should_admit_retryable_gate_error(parsed):
                    gate_uncertainty_note = (
                        f"inbound_gate_retryable_error_admitted: {decision.reasoning}"
                    )[:400]
                else:
                    saved = await services.save_fallback_pre_booking_inquiry(
                        parsed,
                        f"inbound_gate_error: {decision.reasoning}",
                    )
                    if not saved:
                        raise RuntimeError(f"inbound gate error fallback save failed: {decision.reasoning}")
                    await update_normalization_outcome(
                        services.db,
                        services.company_id,
                        _normalization_source_channel(),
                        _message_id(parsed),
                        selected_property_code=parsed.property_code or "",
                        selected_property_match_type=services.infer_property_match_type(parsed, parsed.property_code or ""),
                        route_outcome="pre_booking_gate_error",
                        draft_source="inbound_gate",
                        fallback_reason=decision.reasoning[:400],
                        parser_notes_append=_reservation_routing_parser_notes(parsed),
                    )
                    return "pre_booking_gate_error"

            if decision.error and gate_uncertainty_note:
                pass
            elif admit_on_uncertainty:
                gate_uncertainty_note = (
                    f"inbound_gate_unclear_admitted: {decision.classification.value}: {decision.reasoning}"
                )[:400]
            elif not decision.should_proceed_as_guest:
                if routed_to_review:
                    saved = await services.save_fallback_pre_booking_inquiry(
                        parsed,
                        f"inbound_gate_review: {decision.classification.value}: {decision.reasoning}",
                    )
                    if not saved:
                        raise RuntimeError(
                            f"inbound gate review fallback save failed: {decision.classification.value}"
                        )
                    await update_normalization_outcome(
                        services.db,
                        services.company_id,
                        _normalization_source_channel(),
                        _message_id(parsed),
                        selected_property_code=parsed.property_code or "",
                        selected_property_match_type=services.infer_property_match_type(parsed, parsed.property_code or ""),
                        route_outcome="pre_booking_gate_review",
                        draft_source="inbound_gate",
                        fallback_reason=decision.reasoning[:400],
                        parser_notes_append=_reservation_routing_parser_notes(parsed),
                    )
                    return "pre_booking_gate_review"

                await update_normalization_outcome(
                    services.db,
                    services.company_id,
                    _normalization_source_channel(),
                    _message_id(parsed),
                    selected_property_code=parsed.property_code or "",
                    selected_property_match_type=services.infer_property_match_type(parsed, parsed.property_code or ""),
                    route_outcome="pre_booking_gate_skipped",
                    draft_source="inbound_gate",
                    fallback_reason=decision.reasoning[:400],
                    parser_notes_append=_reservation_routing_parser_notes(parsed),
                )
                logger.info(
                    "[EmailDispatch] Gate skipped parser=%s classification=%s confidence=%.2f",
                    parsed.parser_source,
                    decision.classification.value,
                    decision.confidence,
                )
                return "pre_booking_gate_skipped"
        elif should_run_gate and not gate_enabled:
            gate_uncertainty_note = "inbound_gate_disabled_admitted: layer1_unclear"

        gate_message = InboundGuestMessage(
            message_id=_message_id(parsed) or parsed.thread_id or "prebooking-dispatch",
            tenant_id=str(services.company_id),
            channel="email",
            source_provider=parsed.platform or parsed.parser_source or "email",
            text=parsed.latest_guest_message or parsed.body or "",
            full_thread_text=parsed.conversation_context or parsed.full_body or "",
            identity=getattr(parsed, "identity", None),
            guest_email=parsed.guest_email or "",
            guest_name=parsed.guest_name or "Guest",
            reservation_id=getattr(parsed, "reservation_id", "") or "",
            property_code=parsed.property_code or "",
            lifecycle=MessagingLifecycle.PRE_BOOKING,
            thread_id=parsed.thread_id or "",
            received_at=getattr(parsed, "received_at", None),
            raw_subject=parsed.subject or "",
            structured_asks=list(parsed.asks or []),
            parser_used=parsed.parser_source or "",
            metadata={},
        )
        classification, classifier_metadata = await DeterministicIntakePreFilter().classify_with_metadata(
            gate_message,
            db_session=services.db,
        )
        inferred_intent = (
            classifier_metadata.legacy_intent
            or legacy_intent_from_classification(
                classification,
                message_text=gate_message.text or "",
            )
        )
        inferred_confidence = classification.confidence
        parsed_lifecycle_stage = (getattr(parsed, "lifecycle_stage", "") or "").strip().lower()
        if parsed_lifecycle_stage in {"pre_arrival", "in_stay", "post_stay"}:
            routed_intent = (
                next((str(item).strip() for item in (parsed.asks or []) if str(item).strip()), "")
                or inferred_intent
                or "general_inquiry"
            )
            route_outcome = "pending_session_resolution"
            fallback_reason = "email_dispatch_lifecycle_reroute:db_unavailable"
            if services.db:
                try:
                    route_result = await persist_inbound_from_inquiry(
                        services.db,
                        tenant_id=services.company_id,
                        property_code=parsed.property_code or "",
                        property_name=parsed.property_name or parsed.property_code or "Unknown property",
                        guest_name=parsed.guest_name or "Guest",
                        guest_email=parsed.guest_email or None,
                        message_text=parsed.latest_guest_message or parsed.body or "",
                        intent=routed_intent,
                        received_at=getattr(parsed, "received_at", None),
                        requested_check_in=getattr(parsed, "requested_check_in", None),
                        requested_check_out=getattr(parsed, "requested_check_out", None),
                        requested_guests=getattr(parsed, "requested_guests", None),
                        source_message_id=_message_id(parsed),
                        inquiry_thread_id=parsed.thread_id or "",
                        existing_guest_thread_id=None,
                        source_label="email_dispatch_lifecycle_reroute",
                        reservation_id=getattr(parsed, "reservation_id", "") or "",
                    )
                    await services.db.commit()
                    route_status = (getattr(route_result, "status", "") or "").strip().lower() or "unknown"
                    fallback_reason = f"email_dispatch_lifecycle_reroute:{route_status}"
                    if getattr(route_result, "created", False):
                        route_outcome = "guest_session_routed"
                    elif route_status == "already_exists":
                        route_outcome = "guest_session_existing"
                except Exception as exc:
                    await safe_rollback(services.db)
                    route_outcome = "guest_session_route_failed"
                    fallback_reason = f"email_dispatch_lifecycle_reroute:{type(exc).__name__}"
                    logger.exception(
                        "[EmailDispatch] guest-session persistence failed source=email_dispatch_lifecycle_reroute message_id=%s",
                        _message_id(parsed),
                    )
            await update_normalization_outcome(
                services.db,
                services.company_id,
                _normalization_source_channel(),
                _message_id(parsed),
                selected_property_code=parsed.property_code or "",
                selected_property_match_type=services.infer_property_match_type(parsed, parsed.property_code or ""),
                route_outcome=route_outcome,
                draft_source="lifecycle_router",
                fallback_reason=f"lifecycle_stage:{parsed_lifecycle_stage}:{fallback_reason}",
                parser_notes_append=_reservation_routing_parser_notes(parsed),
            )
            return route_outcome
        if is_non_pre_booking_intent(inferred_intent):
            route_outcome = "pending_session_resolution"
            fallback_reason = "email_dispatch_non_prebooking:db_unavailable"
            if services.db:
                try:
                    route_result = await persist_inbound_from_inquiry(
                        services.db,
                        tenant_id=services.company_id,
                        property_code=parsed.property_code or "",
                        property_name=parsed.property_name or parsed.property_code or "Unknown property",
                        guest_name=parsed.guest_name or "Guest",
                        guest_email=parsed.guest_email or None,
                        message_text=parsed.latest_guest_message or parsed.body or "",
                        intent=inferred_intent,
                        received_at=getattr(parsed, "received_at", None),
                        requested_check_in=getattr(parsed, "requested_check_in", None),
                        requested_check_out=getattr(parsed, "requested_check_out", None),
                        requested_guests=getattr(parsed, "requested_guests", None),
                        source_message_id=_message_id(parsed),
                        inquiry_thread_id=parsed.thread_id or "",
                        existing_guest_thread_id=None,
                        source_label="email_dispatch_non_prebooking",
                        reservation_id=getattr(parsed, "reservation_id", "") or "",
                    )
                    await services.db.commit()
                    route_status = (getattr(route_result, "status", "") or "").strip().lower() or "unknown"
                    fallback_reason = f"email_dispatch_non_prebooking:{route_status}"
                    if getattr(route_result, "created", False):
                        route_outcome = "guest_session_routed"
                    elif route_status == "already_exists":
                        route_outcome = "guest_session_existing"
                except Exception as exc:
                    await safe_rollback(services.db)
                    route_outcome = "guest_session_route_failed"
                    fallback_reason = f"email_dispatch_non_prebooking:{type(exc).__name__}"
                    logger.exception(
                        "[EmailDispatch] guest-session persistence failed source=email_dispatch_non_prebooking message_id=%s",
                        _message_id(parsed),
                    )
            await update_normalization_outcome(
                services.db,
                services.company_id,
                _normalization_source_channel(),
                _message_id(parsed),
                selected_property_code=parsed.property_code or "",
                selected_property_match_type=services.infer_property_match_type(parsed, parsed.property_code or ""),
                route_outcome=route_outcome,
                draft_source="guest_session_router",
                fallback_reason=f"non_pre_booking_intent:{inferred_intent}:{inferred_confidence}:{fallback_reason}",
                parser_notes_append=_reservation_routing_parser_notes(parsed),
            )
            return route_outcome

        property_data, operator_policies = await services.load_property_context(parsed.property_code)
        property_data["operator_name"] = services.operator_name
        api_key = os.getenv("ESCAPIA_API_KEY", "")

        # ── Multi-turn thread context (Gap #1) ──────────────────────────────
        # Resolve guest_thread_id ONCE here, load prior turns from the DB,
        # and thread the SAME id forward to persistence. This eliminates
        # two distinct sources of fragility:
        #   1. The early resolver and the later `_save_inquiry`-driven
        #      `ensure_inquiry_thread` call could in principle key
        #      different threads if their inputs diverged. Threading
        #      `guest_thread_id` forward removes the second call entirely.
        #   2. Even when both calls would resolve to the same id, the
        #      duplicate DB round-trip is unnecessary.
        #
        # If history loading returns empty (first message of a new thread,
        # or anything fails), `guest_thread_id` may still be a valid UUID
        # (the row was created by `ensure_inquiry_thread`); we still pass
        # it forward so persistence reuses it.
        guest_thread_id, thread_history_block = await _resolve_thread_identity_and_history(
            services=services,
            parsed=parsed,
        )
        if thread_history_block:
            parsed.conversation_context = thread_history_block
            logger.info(
                "[EmailDispatch] Injected DB-backed thread history (%d chars) for guest=%s thread=%s guest_thread_id=%s",
                len(thread_history_block),
                parsed.guest_name,
                parsed.thread_id,
                guest_thread_id,
            )

        # Phase 1 cutover retirement: for pre-booking dispatch, the
        # lifecycle-primary flag is now the ownership switch. Keep the
        # broader runtime flag for tenants that have not cut over yet, but
        # once lifecycle-primary is enabled we should not require a second
        # overlapping gate for this lane.
        brain_prebooking_enabled = brain_lifecycle_primary or runtime_enabled

        result = None
        if not brain_prebooking_enabled:
            return await _persist_fallback("brain_runtime_not_primary")

        try:
            booking_context_agent = BookingContextAgent(
                data_provider=AdapterBackedBookingDataProvider(
                    company_id=services.company_id,
                    provider_key="escapia",
                ),
                db_session=services.db,
            )
            binding = PreBookingProviderBinding(
                transport=EmailTransportAdapter(),
                context=EscapiaContextAdapter(
                    booking_context_agent=booking_context_agent,
                ),
            )
            brain_result = await PreBookingBrainOrchestrator().handle(
                binding=binding,
                transport_payload=parsed,
                context_payload=EscapiaContextPayload(
                    property_data=property_data,
                    operator_policies=operator_policies,
                ),
                company_id=services.company_id,
                db_session=services.db,
                shadow_mode=shadow_mode,
            )
            reviewed_draft_text, reviewer_flags, reviewer_warnings, review_verdict = await _review_brain_pre_booking_draft(
                guest_name=parsed.guest_name,
                platform=parsed.platform,
                message=parsed.latest_guest_message or parsed.body,
                intent=brain_result.inquiry.structured_asks[0]
                if getattr(brain_result, "inquiry", None) and brain_result.inquiry.structured_asks
                else "general",
                property_data=property_data,
                operator_policies=operator_policies,
                draft_text=brain_result.brain_draft.response_text,
                tenant_id=services.company_id,
            )
            result = await run_brain_pre_booking_lifecycle(
                brain_result=brain_result,
                company_id=services.company_id,
                api_key=api_key,
                force_approval_mode="required",
                db=services.db,
                guest_thread_id=guest_thread_id,
                reviewed_draft_text=reviewed_draft_text,
                reviewer_flags=reviewer_flags,
                reviewer_warnings=reviewer_warnings + ([gate_uncertainty_note] if gate_uncertainty_note else []),
                review_verdict=review_verdict,
            )
        except Exception as exc:
            logger.error("[EmailDispatch] Brain pre-booking draft failed, saving fallback instead: %s", exc)
            return await _persist_fallback(f"brain_exception:{type(exc).__name__}:{exc}")

        if gate_uncertainty_note:
            result.setdefault("policy_warnings", [])
            if gate_uncertainty_note not in result["policy_warnings"]:
                result["policy_warnings"].append(gate_uncertainty_note)

        if services.db:
            await services.store_thread_context(parsed, result.get("draft_id"))

        logger.info(
            "[EmailDispatch] Pre-booking routed: %s draft=%s decision=%s",
            parsed.guest_name,
            result.get("draft_id"),
            result.get("decision"),
        )
        route_outcome = _pre_booking_route_outcome(result)
        if route_outcome == "pre_booking_save_failed":
            logger.error(
                "[EmailDispatch] Pre-booking save failed tenant=%s thread_id=%s message_id=%s error_type=%s error=%s",
                services.company_id,
                result.get("thread_id") or parsed.thread_id,
                result.get("message_id") or _message_id(parsed),
                result.get("save_error_type") or "",
                result.get("save_error_message") or "",
            )

        await update_normalization_outcome(
            services.db,
            services.company_id,
            _normalization_source_channel(),
            _message_id(parsed),
            selected_property_code=parsed.property_code or "",
            selected_property_match_type=services.infer_property_match_type(parsed, parsed.property_code or ""),
            route_outcome=route_outcome,
            draft_source=result.get("draft_source") or "",
            fallback_reason=" | ".join(result.get("policy_warnings") or [])[:400],
            parser_notes_append=_reservation_routing_parser_notes(parsed),
        )
        await _maybe_writeback_property_resolution(
            db_session=services.db,
            tenant_id=services.company_id,
            draft_id=str(result.get("draft_id") or ""),
            selected_property_code=parsed.property_code or "",
            selected_property_match_type=services.infer_property_match_type(parsed, parsed.property_code or ""),
        )
        await services.maybe_record_pre_booking_gap(parsed, result)
        return route_outcome
    except Exception as exc:
        logger.error("[EmailDispatch] Pre-booking routing failed: %s", exc)
        return await _persist_fallback(str(exc))


async def dispatch_confirmed_guest(
    *,
    services: EmailDispatchServices,
    parsed,
    reservation_match,
) -> str:
    parsed.lifecycle_stage = getattr(reservation_match, "lifecycle_resolved", "") or "pre_arrival"
    parser_notes = _reservation_routing_parser_notes(parsed)
    if not parser_notes and hasattr(reservation_match, "parser_notes_payload"):
        parser_notes = [
            reservation_match.parser_notes_payload(
                routing_source="pms_reservation_matched",
            )
        ]
    await update_normalization_outcome(
        services.db,
        services.company_id,
        _normalization_source_channel(),
        _message_id(parsed),
        selected_property_code=parsed.property_code or "",
        selected_property_match_type=services.infer_property_match_type(parsed, parsed.property_code or ""),
        route_outcome="confirmed_guest_email_received",
        draft_source="reservation_aware_routing",
        fallback_reason=(
            f"reservation_match:{getattr(reservation_match, 'match_method', '')}:"
            f"{getattr(reservation_match, 'lifecycle_resolved', '')}"
        )[:400],
        parser_notes_append=parser_notes,
    )
    logger.info(
        "[EmailDispatch] Confirmed guest routed before pre-booking tenant_id=%s "
        "guest_email=%s reservation_id=%s lifecycle=%s match_method=%s",
        services.company_id,
        getattr(parsed, "guest_email", "") or "",
        getattr(reservation_match, "reservation_id", "") or "",
        getattr(reservation_match, "lifecycle_resolved", "") or "",
        getattr(reservation_match, "match_method", "") or "",
    )
    return "confirmed_guest_email_received"


async def dispatch_in_stay(
    *,
    services: EmailDispatchServices,
    parsed,
    session_row,
) -> str:
    from app.services.feature_flags import get_feature_flags

    post_booking_enabled = False
    if services.db:
        try:
            flags = get_feature_flags(services.db)
            post_booking_enabled = await flags.is_enabled(
                "post_booking_ai",
                company_id=str(services.company_id),
                property_code=parsed.property_code or "",
            )
        except Exception:
            logger.exception(
                "[EmailDispatch] post_booking_ai flag lookup failed; defaulting send-off"
            )

    if not post_booking_enabled:
        logger.info(
            "[EmailDispatch] post_booking_ai disabled; guest-session email will be queued for review "
            "tenant=%s property=%s guest=%s thread=%s",
            services.company_id,
            parsed.property_code or "",
            parsed.guest_name or "",
            parsed.thread_id or "",
        )

    draft_source = "messaging_brain"
    final_action = RecommendedAction.DRAFT_ONLY
    response_text = ""
    review_reason = "Queued for operator review."

    try:
        brain_result = await _build_in_stay_review_result(
            services=services,
            parsed=parsed,
            session_row=session_row,
        )
        response_text = str(brain_result.response_text or "").strip()
        final_action = brain_result.draft.final_action
        draft_source = (
            str(brain_result.draft.confidence_source or "").strip()
            or "messaging_brain"
        )
        if brain_result.draft.escalation_required:
            review_reason = (
                brain_result.draft.reason_for_escalation
                or "The guest-session message needs operator review before responding."
            )
        elif final_action == RecommendedAction.AUTO_SEND:
            review_reason = "Auto mode approved this guest-session reply."
        else:
            review_reason = "Review mode held this guest-session reply for operator approval."
    except Exception:
        logger.exception(
            "[EmailDispatch] session-brain review build failed; falling back to voice-pod reply generation"
        )
        response_text = (await services.generate_in_stay_reply(parsed.body, session_row)).strip()
        draft_source = "voice_pod_fallback"
        review_reason = "Messaging-brain review build failed; queued fallback draft for operator review."

    should_auto_send = post_booking_enabled and final_action == RecommendedAction.AUTO_SEND and bool(response_text)
    if should_auto_send:
        sender = services.build_reply_sender()
        await sender.reply(
            thread_id=parsed.thread_id,
            in_reply_to=parsed.message_id_header,
            to_address=parsed.guest_email,
            to_name=parsed.guest_name,
            subject=f"Re: {parsed.subject}",
            body=response_text,
            operator_name=services.operator_name,
        )
        logger.info("[EmailDispatch] In-stay reply sent to %s via email", parsed.guest_name)
        await update_normalization_outcome(
            services.db,
            services.company_id,
            _normalization_source_channel(),
            _message_id(parsed),
            selected_property_code=parsed.property_code or "",
            selected_property_match_type=services.infer_property_match_type(parsed, parsed.property_code or ""),
            route_outcome="in_stay",
            draft_source=draft_source,
            parser_notes_append=_reservation_routing_parser_notes(parsed),
        )
        return "in_stay"

    # Email-originated guest-session holds are intentionally queued as
    # internal ops review, not as "send this now" actions. The Today
    # action executor's guest_status_response path currently delivers via
    # SMS; using it here would preview the right draft but commit the
    # wrong transport. Queue the held draft for human review without
    # implying one-click email send support that we don't yet have.
    action_type = StayActionAgent.ACTION_OPS_REVIEW
    action_payload = {
        "message_text": response_text,
        "response_type": "email_guest_reply_review",
        "guest_message_text": (
            getattr(parsed, "latest_guest_message", "")
            or getattr(parsed, "body", "")
            or ""
        ),
        "source_channel": "email",
        "source_message_id": _message_id(parsed),
        "thread_id": getattr(parsed, "thread_id", "") or "",
        "subject": getattr(parsed, "subject", "") or "",
        "review_reason": review_reason,
        "queued_at": datetime.now(timezone.utc).isoformat(),
    }
    await _queue_guest_session_review_action(
        db=services.db,
        tenant_id=services.company_id,
        session_row=session_row,
        action_type=action_type,
        payload=action_payload,
        priority=_guest_session_action_priority(session_row),
    )
    await services.db.commit()
    logger.info(
        "[EmailDispatch] In-stay guest email queued for operator review tenant=%s property=%s guest=%s action=%s",
        services.company_id,
        parsed.property_code or "",
        parsed.guest_name or "",
        action_type,
    )
    await update_normalization_outcome(
        services.db,
        services.company_id,
        _normalization_source_channel(),
        _message_id(parsed),
        selected_property_code=parsed.property_code or "",
        selected_property_match_type=services.infer_property_match_type(parsed, parsed.property_code or ""),
        route_outcome="in_stay_pending_review",
        draft_source=draft_source if response_text else "operator_review_required",
        fallback_reason=review_reason[:400],
        parser_notes_append=_reservation_routing_parser_notes(parsed),
    )
    return "in_stay_pending_review"


async def dispatch_system_event(
    *,
    services: EmailDispatchServices,
    parsed,
) -> str:
    if parsed.system_event_type == "vendor_ops_email":
        await update_normalization_outcome(
            services.db,
            services.company_id,
            _normalization_source_channel(),
            _message_id(parsed),
            selected_property_code=parsed.property_code or "",
            selected_property_match_type=services.infer_property_match_type(parsed, parsed.property_code or ""),
            route_outcome="vendor_ops_email",
            draft_source=parsed.parser_source,
        )
        return "vendor_ops_email"

    if parsed.system_event_type == "review_received":
        return await dispatch_review_event(services=services, parsed=parsed)

    existing = await services.find_session_by_reservation_context(parsed)
    if existing:
        await update_normalization_outcome(
            services.db,
            services.company_id,
            _normalization_source_channel(),
            _message_id(parsed),
            selected_property_code=parsed.property_code or "",
            selected_property_match_type=services.infer_property_match_type(parsed, parsed.property_code or ""),
            route_outcome="system_event_existing_session",
            draft_source=parsed.parser_source,
        )
        return "system_event_existing_session"

    if not parsed.property_code:
        await services.record_property_binding_gap(parsed, "missing_property_binding_for_system_event")
        await update_normalization_outcome(
            services.db,
            services.company_id,
            _normalization_source_channel(),
            _message_id(parsed),
            route_outcome="system_event_missing_property_binding",
            draft_source=parsed.parser_source,
            fallback_reason=f"missing_property_binding platform={parsed.platform} listing_id={parsed.platform_listing_id}",
        )
        return "system_event_missing_property_binding"

    created = await services.create_provisional_session_from_system_event(parsed)
    await update_normalization_outcome(
        services.db,
        services.company_id,
        _normalization_source_channel(),
        _message_id(parsed),
        selected_property_code=parsed.property_code or "",
        selected_property_match_type=services.infer_property_match_type(parsed, parsed.property_code or ""),
        route_outcome="system_event_session_created" if created else "system_event_session_failed",
        draft_source=parsed.parser_source,
        fallback_reason="" if created else "session_create_failed",
    )
    return "system_event_session_created" if created else "system_event_session_failed"


async def dispatch_review_event(
    *,
    services: EmailDispatchServices,
    parsed,
) -> str:
    policy = await services.load_review_event_policy()
    if not policy.get("ingest_review_events", True):
        await update_normalization_outcome(
            services.db,
            services.company_id,
            _normalization_source_channel(),
            _message_id(parsed),
            selected_property_code=parsed.property_code or "",
            selected_property_match_type=services.infer_property_match_type(parsed, parsed.property_code or ""),
            route_outcome="review_event_ignored",
            draft_source=parsed.parser_source,
        )
        return "review_event_ignored"

    session_row = await services.find_session_by_reservation_context(parsed)
    if not session_row and parsed.property_code:
        created = await services.create_provisional_session_from_system_event(parsed)
        if created:
            session_row = await services.find_session_by_reservation_context(parsed)

    if not session_row and not parsed.property_code:
        await services.record_property_binding_gap(parsed, "missing_property_binding_for_review_event")
        await update_normalization_outcome(
            services.db,
            services.company_id,
            _normalization_source_channel(),
            _message_id(parsed),
            route_outcome="review_event_missing_property_binding",
            draft_source=parsed.parser_source,
            fallback_reason=f"missing_property_binding platform={parsed.platform} listing_id={parsed.platform_listing_id}",
        )
        return "review_event_missing_property_binding"

    if session_row:
        await services.persist_review_event(session_row, parsed, policy)
        route_outcome = (
            "review_event_recorded_with_draft"
            if parsed.system_event_payload.get("suggested_response")
            else "review_event_recorded"
        )
        await update_normalization_outcome(
            services.db,
            services.company_id,
            _normalization_source_channel(),
            _message_id(parsed),
            selected_property_code=parsed.property_code or "",
            selected_property_match_type=services.infer_property_match_type(parsed, parsed.property_code or ""),
            route_outcome=route_outcome,
            draft_source=parsed.parser_source,
        )
        return route_outcome

    await update_normalization_outcome(
        services.db,
        services.company_id,
        _normalization_source_channel(),
        _message_id(parsed),
        selected_property_code=parsed.property_code or "",
        selected_property_match_type=services.infer_property_match_type(parsed, parsed.property_code or ""),
        route_outcome="review_event_unmatched_session",
        draft_source=parsed.parser_source,
        fallback_reason="review_session_match_failed",
    )
    return "review_event_unmatched_session"
