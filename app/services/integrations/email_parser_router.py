from __future__ import annotations

import logging
import re
from typing import Any, Callable, Dict, Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from app.services.integrations.email_type_classifier import (
    EMAIL_TYPE_CLASSIFIER,
    MessageType,
)
from app.services.integrations.direct_email_parsers import parse_direct_inquiry
from app.services.integrations.inbound_source_router import detect_inbound_source_route
from app.services.integrations.llm_email_extractor import (
    LLMEmailExtractor,
    LLMEmailExtractorFallback,
)
from app.services.integrations.non_guest_patterns import NON_GUEST_REGISTRY
from app.services.integrations.ota_email_parsers import parse_ota_inquiry
from app.services.integrations.ota_reservation_events import parse_ota_reservation_event
from app.services.integrations.vendor_email_parsers import parse_vendor_coordination_email

logger = logging.getLogger(__name__)
_PREFILTER_DROP_OVERRIDE_KEY = "inbound_prefilter_drop_overrides"


_PREBOOKING_SUBJECT_PATTERNS = (
    re.compile(r"\binquiry from\b", re.I),
    re.compile(r"\bnew inquiry\b", re.I),
    re.compile(r"\bquestion about\b", re.I),
    re.compile(r"\binquiry about\b", re.I),
)

_REVIEW_SUBJECT_PATTERNS = (
    re.compile(r"\breview\b", re.I),
    re.compile(r"\bnew review\b", re.I),
    re.compile(r"\breview received\b", re.I),
)

_RESERVATION_SUBJECT_PATTERNS = (
    re.compile(r"\breservation confirmed\b", re.I),
    re.compile(r"\breservation reminder\b", re.I),
    re.compile(r"\bbooking confirmed\b", re.I),
    re.compile(r"\bcancellation\b", re.I),
    re.compile(r"\bnew reservation\b", re.I),
)

_MARKETING_SUBJECT_PATTERNS = (
    re.compile(r"\bnewsletter\b", re.I),
    re.compile(r"\bpromotional?\b", re.I),
    re.compile(r"\bhere's to more time, together\b", re.I),
    re.compile(r"\breceipt from\b", re.I),
)

_DROP_SENDER_PATTERNS = (
    "@cmacommunities.com",
    "@expediagroup.com",
    "receipts+",
    "@stripe.com",
    "noreply@mybookingpal.com",
    "automated@airbnb.com",
    "no-reply@supportmessaging.airbnb.com",
    "resolutions@airbnb.com",
    "mailer-daemon",
    "postmaster@",
)

_BOUNCE_MARKERS = (
    "delivery has failed",
    "message could not be delivered",
    "mail delivery subsystem",
    "undeliverable",
)


def _log_layer1_drop(
    *,
    source_message_id: str,
    sender: str,
    subject: str,
    reason: str,
) -> None:
    logger.info(
        "[IntakeLayer1] drop source_message_id=%s sender=%s subject=%r layer=layer1_deterministic reason=%s",
        source_message_id,
        sender,
        subject[:200],
        reason,
    )


def _log_pattern_drop(
    *,
    source_message_id: str,
    sender: str,
    subject: str,
    reason: str,
) -> None:
    logger.info(
        "[IntakeLayer1] drop source_message_id=%s sender=%s subject=%r layer=pattern_registry reason=%s",
        source_message_id,
        sender,
        subject[:200],
        reason,
    )


def _log_type_drop(
    *,
    source_message_id: str,
    sender: str,
    subject: str,
    reason: str,
) -> None:
    logger.info(
        "[IntakeTypeClassifier] drop source_message_id=%s sender=%s subject=%r reason=%s",
        source_message_id,
        sender,
        subject[:200],
        reason,
    )


def _looks_like_markup_noise(text: str) -> bool:
    body = (text or "").strip()
    if len(body) < 80:
        return False
    css_hits = len(re.findall(r"[.#]?[A-Za-z0-9_-]+\s*\{", body))
    markup_hits = len(re.findall(r"</?[a-z][^>]*>", body, flags=re.I))
    human_sentence = bool(re.search(r"[A-Z][a-z]{2,}\s+[a-z]{2,}", body))
    return (css_hits >= 3 or markup_hits >= 8) and not human_sentence


def _has_prebooking_subject(subject: str) -> bool:
    return any(pattern.search(subject or "") for pattern in _PREBOOKING_SUBJECT_PATTERNS)


def _classify_layer1(
    *,
    source_message_id: str,
    headers: Dict[str, str],
    subject: str,
    plain_text: str,
    raw_html: str,
    dynamic_drop_overrides: Optional[list[dict[str, str]]] = None,
) -> tuple[str, str]:
    header_map = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
    from_header = header_map.get("from", "")
    sender = from_header.lower()
    reply_to = (header_map.get("reply-to", "") or "").lower()
    subject_text = subject or ""
    plain = plain_text or ""
    body_for_noise = plain or raw_html or ""

    ota_site = (header_map.get("x-mediated-site", "") or "").strip().lower()
    ota_message_type = (header_map.get("x-mediated-message-type", "") or "").strip().upper()
    ota_sender = any(marker in sender for marker in ("airbnb", "vrbo", "homeaway"))

    if ota_site == "vrbo":
        # Vrbo guest-inquiry header types. INQUIRY is the bare variant Vrbo
        # uses for older messages and for reply-thread-originated inquiries
        # alongside the more common NEW_INQUIRY. Both are unambiguous guest-
        # initiated pre-booking signals, so we admit positively.
        if ota_message_type in {"NEW_INQUIRY", "NEW_BOOKING_REQUEST", "INQUIRY"}:
            return "admit", f"ota_message_type:{ota_message_type}"
        # REPLIED was previously a hard drop with a reason string claiming
        # "guest_session" routing. That routing does not exist — the caller
        # treats a layer-1 drop as "do not process this email" and the
        # message dies in the operator inbox.
        #
        # A Vrbo REPLIED could be: (a) a follow-up on an active pre-booking
        # thread, (b) a new question that happened to come back on a reply
        # channel, (c) an in-stay guest message, or (d) confirmation/reply
        # to an operator outbound. Deterministic cannot tell these apart
        # with certainty, so per the strict-positive-gate contract it must
        # hand off to downstream classification rather than terminate.
        # EMAIL_TYPE_CLASSIFIER + the OTA parser + the LLM extractor are
        # the layers designed to disambiguate; let them.
        if ota_message_type == "REPLIED":
            return "unclear", "ota_message_type:REPLIED"
        # Reservation-event header types are positively handled downstream
        # by EMAIL_TYPE_CLASSIFIER (the _BOOKING_EVENT_HEADER_TYPES set maps
        # them to VRBO_BOOKING_EVENT, which parse_structured_inbound_email
        # routes to parse_ota_reservation_event). Dropping them at layer 1
        # preempts that pipeline for no benefit — these messages are real
        # operational signal for the stay/booking lifecycle. Hand off.
        if ota_message_type in {"RESERVATION_CONFIRMED", "CANCELLED", "REMINDER"}:
            return "unclear", f"ota_message_type:{ota_message_type}"
        if ota_message_type:
            return "unclear", f"ota_message_type:{ota_message_type}"

    if "list-unsubscribe" in header_map:
        _log_layer1_drop(
            source_message_id=source_message_id,
            sender=from_header,
            subject=subject_text,
            reason="header:list_unsubscribe",
        )
        return "drop", "header:list_unsubscribe"

    if "auto-generated" in header_map.get("auto-submitted", "").lower():
        _log_layer1_drop(
            source_message_id=source_message_id,
            sender=from_header,
            subject=subject_text,
            reason="header:auto_submitted",
        )
        return "drop", "header:auto_submitted"

    if any(pattern.search(subject_text) for pattern in _REVIEW_SUBJECT_PATTERNS):
        _log_layer1_drop(
            source_message_id=source_message_id,
            sender=from_header,
            subject=subject_text,
            reason="subject:review_pattern",
        )
        return "drop", "subject:review_pattern"

    if any(pattern.search(subject_text) for pattern in _RESERVATION_SUBJECT_PATTERNS):
        if ota_site in {"vrbo", "airbnb"} or ota_message_type or ota_sender:
            return "unclear", "subject:reservation_pattern_ota_candidate"
        _log_layer1_drop(
            source_message_id=source_message_id,
            sender=from_header,
            subject=subject_text,
            reason="subject:reservation_pattern",
        )
        return "drop", "subject:reservation_pattern"

    if any(pattern.search(subject_text) for pattern in _MARKETING_SUBJECT_PATTERNS):
        _log_layer1_drop(
            source_message_id=source_message_id,
            sender=from_header,
            subject=subject_text,
            reason="subject:marketing_pattern",
        )
        return "drop", "subject:marketing_pattern"

    if any(marker in sender for marker in _DROP_SENDER_PATTERNS):
        _log_layer1_drop(
            source_message_id=source_message_id,
            sender=from_header,
            subject=subject_text,
            reason="sender:drop_pattern",
        )
        return "drop", "sender:drop_pattern"

    dynamic_reason = _match_dynamic_drop_override(
        from_header=from_header,
        subject=subject_text,
        body_text=plain,
        overrides=dynamic_drop_overrides or [],
    )
    if dynamic_reason:
        _log_layer1_drop(
            source_message_id=source_message_id,
            sender=from_header,
            subject=subject_text,
            reason=dynamic_reason,
        )
        return "drop", dynamic_reason

    if any(marker in sender for marker in ("@reply.airbnb.com",)) and _has_prebooking_subject(subject_text):
        return "admit", "sender:reply_airbnb_with_inquiry_subject"

    lowered_plain = plain.lower()
    if any(marker in lowered_plain for marker in _BOUNCE_MARKERS):
        _log_layer1_drop(
            source_message_id=source_message_id,
            sender=from_header,
            subject=subject_text,
            reason="body:bounce_marker",
        )
        return "drop", "body:bounce_marker"

    if _looks_like_markup_noise(body_for_noise):
        _log_layer1_drop(
            source_message_id=source_message_id,
            sender=from_header,
            subject=subject_text,
            reason="body:markup_noise",
        )
        return "drop", "body:markup_noise"

    if _has_prebooking_subject(subject_text):
        return "admit", "subject:prebooking_pattern"

    return "unclear", "no_confident_layer1_match"


def _match_dynamic_drop_override(
    *,
    from_header: str,
    subject: str,
    body_text: str,
    overrides: list[dict[str, str]],
) -> Optional[str]:
    sender = (from_header or "").lower()
    sender_domain = sender.rsplit("@", 1)[-1] if "@" in sender else sender
    lowered_subject = (subject or "").lower()
    lowered_body = (body_text or "").lower()
    for override in overrides:
        rule_name = str(override.get("name") or "dynamic_drop_override").strip()
        rule_domain = str(override.get("sender_domain") or "").strip().lower()
        sender_contains = str(override.get("sender_contains") or "").strip().lower()
        subject_contains = str(override.get("subject_contains") or "").strip().lower()
        body_contains = str(override.get("body_contains") or "").strip().lower()
        if rule_domain and not (
            sender_domain == rule_domain or sender_domain.endswith(f".{rule_domain}")
        ):
            continue
        if sender_contains and sender_contains not in sender:
            continue
        if subject_contains and subject_contains not in lowered_subject:
            continue
        if body_contains and body_contains not in lowered_body:
            continue
        return f"override:{rule_name}"
    return None


async def _load_prefilter_drop_overrides(*, tenant_id: UUID | str | None, db: Any = None) -> list[dict[str, str]]:
    if db is None or tenant_id is None:
        return []
    try:
        row = (
            await db.execute(
                text(
                    """
                    SELECT extra
                    FROM operator_settings
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                    LIMIT 1
                    """
                ),
                {"tenant_id": str(tenant_id)},
            )
        ).scalar_one_or_none()
    except ProgrammingError:
        logger.error(
            "[EmailParserRouter] operator_settings schema issue tenant_id=%s",
            tenant_id,
            exc_info=True,
        )
        return []
    except DBAPIError:
        logger.warning(
            "[EmailParserRouter] operator_settings lookup failed tenant_id=%s",
            tenant_id,
            exc_info=True,
        )
        return []
    if not isinstance(row, dict):
        return []
    overrides = row.get(_PREFILTER_DROP_OVERRIDE_KEY) or []
    return [dict(item) for item in overrides if isinstance(item, dict)]


def _apply_layer1_metadata(parsed: Any, decision: str, reason: str, headers: Dict[str, str]) -> Any:
    setattr(parsed, "intake_layer1_decision", decision)
    setattr(parsed, "intake_layer1_reason", reason)
    header_map = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
    setattr(parsed, "ota_site", (header_map.get("x-mediated-site", "") or "").strip().lower())
    setattr(parsed, "conversation_id", (header_map.get("x-mediated-conversation-id", "") or "").strip())
    setattr(parsed, "message_type", (header_map.get("x-mediated-message-type", "") or "").strip().upper())
    setattr(parsed, "recipient_type", (header_map.get("x-mediated-recipient-type", "") or "").strip().upper())
    reservation_header = (header_map.get("x-mediated-reservation-id", "") or "").strip()
    if reservation_header and not getattr(parsed, "reservation_id", ""):
        setattr(parsed, "reservation_id", reservation_header)
    return parsed


def _has_ota_inquiry_signal(parsed_ota: Any, adapted: Any) -> bool:
    return bool(
        getattr(parsed_ota, "thread_event_type", "") in {"inquiry", "guest_reply", "operator_reply"}
        or (getattr(parsed_ota, "latest_guest_turn", "") or "").strip()
        or getattr(adapted, "platform_listing_id", "")
        or getattr(adapted, "platform_unit_id", "")
    )


async def parse_structured_inbound_email(
    *,
    source_message_id: str,
    subject: str,
    plain_text: str,
    raw_html: str,
    headers: Dict[str, str],
    parser: Any,
    adapt_llm_inquiry: Callable[[Any], Optional[Any]],
    adapt_reservation_event: Callable[[Any], Optional[Any]],
    adapt_ota_inquiry: Callable[[Any], Optional[Any]],
    adapt_direct_inquiry: Callable[[Any], Optional[Any]],
    adapt_vendor_email: Callable[[Any], Optional[Any]],
    fallback_parse: Callable[[], Optional[Any]],
    record_non_guest_drop: Optional[Callable[[str], None]] = None,
    llm_extractor_factory: Callable[[], Any] = LLMEmailExtractor,
    tenant_id: UUID | str | None = None,
    db: Any = None,
) -> Optional[Any]:
    """Shared parser-selection flow for provider-backed email transports."""
    dynamic_drop_overrides = await _load_prefilter_drop_overrides(
        tenant_id=tenant_id,
        db=db,
    )
    layer1_decision, layer1_reason = _classify_layer1(
        source_message_id=source_message_id,
        headers=headers,
        subject=subject,
        plain_text=plain_text,
        raw_html=raw_html,
        dynamic_drop_overrides=dynamic_drop_overrides,
    )
    if layer1_decision == "drop":
        if record_non_guest_drop:
            record_non_guest_drop(layer1_reason)
        return None

    from_header = (headers or {}).get("From", (headers or {}).get("from", ""))
    registry_match = NON_GUEST_REGISTRY.classify(
        from_header=from_header,
        subject=subject,
        plain_text=plain_text,
        raw_html=raw_html,
    )
    if registry_match:
        _log_pattern_drop(
            source_message_id=source_message_id,
            sender=from_header,
            subject=subject,
            reason=registry_match.reason,
        )
        if record_non_guest_drop:
            record_non_guest_drop(registry_match.reason)
        return None

    source_route = detect_inbound_source_route(
        headers=headers,
        subject=subject,
        plain_text=plain_text,
        raw_html=raw_html,
    )

    if source_route.parser_hint == "vendor_ops_email":
        vendor = parse_vendor_coordination_email(
            headers=headers,
            subject=subject,
            plain_text=plain_text,
        )
        if vendor:
            adapted = adapt_vendor_email(vendor)
            if adapted:
                return _apply_layer1_metadata(adapted, layer1_decision, layer1_reason, headers)

    message_type = EMAIL_TYPE_CLASSIFIER.classify(
        headers=headers,
        subject=subject,
        plain_text=plain_text,
        raw_html=raw_html,
        source_route=source_route,
    )
    if message_type.message_type in {MessageType.NON_GUEST, MessageType.DIRECT_WEBSITE_FORM_OTHER}:
        _log_type_drop(
            source_message_id=source_message_id,
            sender=from_header,
            subject=subject,
            reason=message_type.reason,
        )
        if record_non_guest_drop:
            record_non_guest_drop(message_type.reason)
        return None

    if message_type.message_type in {
        MessageType.AIRBNB_BOOKING_EVENT,
        MessageType.VRBO_BOOKING_EVENT,
    }:
        reservation_event = parse_ota_reservation_event(
            headers=headers,
            subject=subject,
            plain_text=plain_text,
        )
        if reservation_event:
            adapted = adapt_reservation_event(reservation_event)
            if adapted:
                return _apply_layer1_metadata(adapted, layer1_decision, layer1_reason, headers)

    if source_route.parser_hint == "ota" and source_route.provider != "airbnb":
        ota = parse_ota_inquiry(
            raw_html=raw_html,
            headers=headers,
            subject=subject,
            plain_text=plain_text,
        )
        if ota:
            adapted = adapt_ota_inquiry(ota)
            if adapted:
                if parser.is_non_guest_email(subject, adapted.body) and not _has_ota_inquiry_signal(ota, adapted):
                    return None
                return _apply_layer1_metadata(adapted, layer1_decision, layer1_reason, headers)

    if source_route.parser_hint in {"ota", "direct_website_form", "generic"}:
        extractor = llm_extractor_factory()
        try:
            extracted = await extractor.extract(
                source_message_id=source_message_id,
                detected_shape=f"{source_route.family}:{source_route.provider}",
                subject=subject,
                plain_text=plain_text,
                raw_html=raw_html,
                headers=headers,
            )
            adapted = adapt_llm_inquiry(extracted)
            if adapted:
                return _apply_layer1_metadata(adapted, layer1_decision, layer1_reason, headers)
        except LLMEmailExtractorFallback:
            pass

    if message_type.message_type == MessageType.DIRECT_WEBSITE_FORM_INQUIRY:
        direct = parse_direct_inquiry(
            headers=headers,
            subject=subject,
            plain_text=plain_text,
            strict_form_only=True,
        )
        if direct:
            adapted = adapt_direct_inquiry(direct)
            if adapted and not parser.is_non_guest_email(subject, adapted.body):
                return _apply_layer1_metadata(adapted, layer1_decision, layer1_reason, headers)

    if plain_text and parser.is_non_guest_email(subject, plain_text):
        return None

    if source_route.parser_hint == "direct_website_form" and message_type.message_type != MessageType.DIRECT_WEBSITE_FORM_INQUIRY:
        direct = parse_direct_inquiry(
            headers=headers,
            subject=subject,
            plain_text=plain_text,
            strict_form_only=True,
        )
        if direct:
            adapted = adapt_direct_inquiry(direct)
            if adapted and not parser.is_non_guest_email(subject, adapted.body):
                return _apply_layer1_metadata(adapted, layer1_decision, layer1_reason, headers)

    parsed = fallback_parse()
    if parsed:
        return _apply_layer1_metadata(parsed, layer1_decision, layer1_reason, headers)
    return None
