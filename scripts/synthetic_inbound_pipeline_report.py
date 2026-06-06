from __future__ import annotations

import argparse
import asyncio
import json
import sys
import types
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import httpx
from fastapi import FastAPI

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

if "jose" not in sys.modules:
    jose_module = types.ModuleType("jose")

    class _JWTError(Exception):
        pass

    jose_module.JWTError = _JWTError
    jose_module.jwt = types.SimpleNamespace(
        encode=lambda *args, **kwargs: "synthetic-token",
        decode=lambda *args, **kwargs: {},
    )
    sys.modules["jose"] = jose_module

from app.api.dependencies import TenantContext
from app.api.v1.endpoints import concierge
from app.services.feature_flags import FeatureFlag
from app.services.integrations.direct_email_parsers import parse_direct_inquiry
from app.services.integrations.email_dispatch import EmailDispatchServices, dispatch_pre_booking
from app.services.integrations.email_inbound import ParsedEmailMessage
from app.services.integrations.email_parser_router import parse_structured_inbound_email
from app.services.integrations.gmail_inbox_poller import GmailEmailParser
from app.services.integrations.inbound_source_router import detect_inbound_source_route
from app.services.integrations.llm_email_extractor import (
    ExtractedEmailFields,
    LLMEmailExtractorFallback,
    LLMEmailExtractorParseFailure,
)
from app.services.integrations.ota_email_parsers import parse_ota_inquiry
from app.services.integrations.vendor_email_parsers import parse_vendor_coordination_email
from app.services.messaging_brain.inbound_message_gate import (
    GateDecision,
    InboundClassification,
)
from app.services.messaging_brain.session_channel_adapter import run_session_channel_message
from app.services.orchestration.messaging_brain_contracts import (
    GuestResponseDraft,
    MessagingLifecycle,
    OutboundIntent,
    RecommendedAction,
)


TENANT_ID = UUID("11111111-1111-1111-1111-111111111111")
PROPERTY_ID = UUID("22222222-2222-2222-2222-222222222222")
PROPERTY_CODE = "GULF_VIEW_204"


@dataclass(frozen=True)
class FlagProfile:
    name: str
    description: str
    values: dict[str, bool]


def _flag_values(*, runtime: bool, lifecycle: bool, ship_i: bool) -> dict[str, bool]:
    return {
        FeatureFlag.INBOUND_MESSAGE_GATE_ENABLED: True,
        FeatureFlag.INBOUND_MESSAGE_GATE_REVIEW_ALL: False,
        FeatureFlag.MESSAGING_BRAIN_RUNTIME: runtime,
        FeatureFlag.MESSAGING_BRAIN_SHADOW_MODE: False,
        FeatureFlag.BRAIN_INTAKE_PRIMARY: runtime,
        FeatureFlag.BRAIN_POLICY_PRIMARY: runtime,
        FeatureFlag.BRAIN_COMPOSER_PRIMARY: runtime,
        FeatureFlag.BRAIN_GAP_DETECTION_PRIMARY: runtime,
        FeatureFlag.BRAIN_PREBOOKING_LIFECYCLE_PRIMARY: lifecycle,
        FeatureFlag.SHIP_I_KB_RETRY_PRIMARY: ship_i,
    }


PROFILES: dict[str, FlagProfile] = {
    "brain_primary": FlagProfile(
        name="brain_primary",
        description="Current brain-era runtime: dispatch through Brain lifecycle and Ship I substrate off.",
        values=_flag_values(runtime=True, lifecycle=True, ship_i=False),
    ),
    "ship_i_canary": FlagProfile(
        name="ship_i_canary",
        description="Brain-era runtime with Ship I retry substrate enabled.",
        values=_flag_values(runtime=True, lifecycle=True, ship_i=True),
    ),
    "legacy_runtime_off": FlagProfile(
        name="legacy_runtime_off",
        description="Compatibility control with messaging brain runtime disabled.",
        values=_flag_values(runtime=False, lifecycle=False, ship_i=False),
    ),
}


@dataclass(frozen=True)
class Expectation:
    stage: str
    observed_outcome: str
    result_class: str
    lifecycle: str
    route_contains: str = ""
    response_contains: str = ""
    parser_source_contains: str = ""
    blocked_topics: tuple[str, ...] = ()
    triggered_by: str = ""
    skipped: bool = False


@dataclass(frozen=True)
class PreBookingEmailCase:
    kind: str
    name: str
    lifecycle: str
    channel: str
    provider: str
    subject: str
    headers: dict[str, str]
    plain_text: str
    raw_html: str = ""
    llm_mode: str = "success"
    llm_payload: Optional[dict[str, Any]] = None
    gate_classification: str = "guest_message"
    gate_confidence: float = 0.95
    gate_review_all: bool = False
    dispatch_plan: str = "brain_hold"
    notes: str = ""
    expectations: dict[str, Expectation] = field(default_factory=dict)


@dataclass(frozen=True)
class ConciergeMessageCase:
    kind: str
    name: str
    lifecycle: str
    channel: str
    provider: str
    stage_value: str
    message_text: str
    check_in_date: str = ""
    check_out_date: str = ""
    notes: str = ""
    expectations: dict[str, Expectation] = field(default_factory=dict)


@dataclass(frozen=True)
class SessionChannelCase:
    kind: str
    name: str
    lifecycle: str
    channel: str
    provider: str
    phase: str
    message_text: str
    notes: str = ""
    expectations: dict[str, Expectation] = field(default_factory=dict)


@dataclass(frozen=True)
class ProactivePreviewCase:
    kind: str
    name: str
    lifecycle: str
    channel: str
    provider: str
    stage_value: str
    guest_type: str
    has_children: bool
    lead_time_days: int
    check_in_date: str
    check_out_date: str
    notes: str = ""
    expectations: dict[str, Expectation] = field(default_factory=dict)


HarnessCase = PreBookingEmailCase | ConciergeMessageCase | SessionChannelCase | ProactivePreviewCase


@dataclass
class ReplayResult:
    profile: str
    name: str
    lifecycle: str
    channel: str
    provider: str
    stage: str
    observed_outcome: str
    result_class: str
    route: str = ""
    parser_source: str = ""
    response_excerpt: str = ""
    blocked_topics: list[str] = field(default_factory=list)
    triggered_by: str = ""
    notes: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return not self.failures


def _truncate(text: str, limit: int = 90) -> str:
    compact = " ".join((text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


class _NamedFakeFlagService:
    def __init__(self, values: dict[str, bool]):
        self._values = dict(values)

    async def is_enabled(self, flag_name, company_id=None, property_code=None):
        return bool(self._values.get(str(flag_name), False))


class _FakeMappings:
    def __init__(self, row: Optional[dict[str, Any]]):
        self._row = row

    def first(self):
        return self._row

    def all(self):
        return [self._row] if self._row else []


class _FakeExecuteResult:
    def __init__(self, row: Optional[dict[str, Any]] = None):
        self._row = row

    def mappings(self):
        return _FakeMappings(self._row)

    def first(self):
        return self._row

    def fetchone(self):
        return self._row

    def scalar_one_or_none(self):
        return None

    def scalar_one(self):
        return 1


class _FakeDbSession:
    def __init__(self) -> None:
        self.property_row = {
            "property_id": str(PROPERTY_ID),
            "tenant_id": str(TENANT_ID),
            "property_code": PROPERTY_CODE,
            "property_name": "Gulf View 204",
        }
        self.commits = 0
        self.rollbacks = 0
        self.executed: list[str] = []

    async def execute(self, statement, params=None):
        sql = str(statement)
        self.executed.append(sql)
        if "FROM properties" in sql:
            return _FakeExecuteResult(self.property_row)
        return _FakeExecuteResult()

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


def _make_email_services(db: Any | None = None) -> EmailDispatchServices:
    db_session = db or _FakeDbSession()
    return EmailDispatchServices(
        company_id=TENANT_ID,
        db=db_session,
        watched_email="info@example.com",
        operator_name="Synthetic Operator",
        infer_property_match_type=lambda parsed, code: "exact" if code else "none",
        load_property_context=AsyncMock(return_value=({"property_name": "Synthetic Home"}, {})),
        store_thread_context=AsyncMock(),
        maybe_record_pre_booking_gap=AsyncMock(),
        save_fallback_pre_booking_inquiry=AsyncMock(return_value=True),
        record_kb_gap=AsyncMock(),
        record_property_binding_gap=AsyncMock(),
        build_reply_sender=lambda: MagicMock(),
        generate_in_stay_reply=AsyncMock(return_value="in-stay"),
        load_review_event_policy=AsyncMock(return_value={}),
        find_session_by_reservation_context=AsyncMock(return_value=None),
        create_provisional_session_from_system_event=AsyncMock(return_value=False),
        persist_review_event=AsyncMock(),
    )


def _build_gate_decision(case: PreBookingEmailCase) -> GateDecision:
    extracted = None
    if case.gate_classification == "guest_message":
        extracted = SimpleNamespace(
            guest_text=(case.llm_payload or {}).get("latest_guest_message") or None,
            guest_name=(case.llm_payload or {}).get("sender_name") or None,
            property_reference=(case.llm_payload or {}).get("property_code_or_name") or None,
            reply_path=case.headers.get("Reply-To"),
            thread_id=case.headers.get("X-Thread-Id"),
        )
    return GateDecision(
        decision_id=UUID("22222222-2222-2222-2222-222222222222"),
        classification=InboundClassification(case.gate_classification),
        confidence=case.gate_confidence,
        reasoning=f"synthetic:{case.gate_classification}",
        extracted=extracted,
        model="synthetic-gate",
        raw_response=None,
        error=None,
    )


def _build_prebooking_result(
    case: PreBookingEmailCase,
    *,
    draft_source: str,
) -> dict[str, Any]:
    if case.dispatch_plan == "kb_gap_hold":
        topics = ["pool_heating_cost"]
        return {
            "saved": True,
            "save_status": "saved",
            "draft_id": f"INQ-{case.name[:8].upper()}",
            "decision": "hold",
            "draft_source": draft_source,
            "policy_warnings": ["missing_property_knowledge:pool_heating_cost"],
            "draft_text": "(no AI draft generated yet)",
            "blocked_by_gap_topics": topics,
            "triggered_by": "",
        }
    return {
        "saved": True,
        "save_status": "saved",
        "draft_id": f"INQ-{case.name[:8].upper()}",
        "decision": "hold",
        "draft_source": draft_source,
        "policy_warnings": [],
        "draft_text": "Synthetic draft reply",
        "blocked_by_gap_topics": [],
        "triggered_by": "",
    }


def _make_gmail_like_message(case: PreBookingEmailCase) -> dict[str, Any]:
    headers = [{"name": k, "value": v} for k, v in case.headers.items()]
    return {
        "id": case.headers.get("Message-ID", case.name),
        "threadId": case.headers.get("X-Thread-Id", f"thread-{case.name}"),
        "payload": {"headers": headers},
    }


def _adapt_llm(case: PreBookingEmailCase, extracted: ExtractedEmailFields) -> ParsedEmailMessage:
    from_header = case.headers.get("From", "")
    reply_to = case.headers.get("Reply-To", "")
    return ParsedEmailMessage(
        source_provider="gmail",
        source_message_id=case.headers.get("Message-ID", case.name),
        source_thread_id=case.headers.get("X-Thread-Id", f"thread-{case.name}"),
        gmail_message_id=case.headers.get("Message-ID", case.name),
        gmail_thread_id=case.headers.get("X-Thread-Id", f"thread-{case.name}"),
        message_id_header=case.headers.get("Message-ID", case.name),
        guest_name=extracted.sender_name or "Guest",
        guest_email=extracted.sender_email or "guest@example.com",
        reply_channel_address=reply_to,
        subject=case.subject,
        body=extracted.latest_guest_message,
        latest_guest_message=extracted.latest_guest_message,
        conversation_context="",
        full_body=case.plain_text,
        platform=(
            "vrbo"
            if "homeaway" in from_header.lower() or "vrbo" in case.subject.lower()
            else "airbnb"
            if "airbnb" in from_header.lower()
            else "direct"
        ),
        is_inquiry=True,
        parser_source=extracted.parser_source,
        property_name=extracted.raw_property_mention,
        property_code="",
        raw_property_mention=extracted.raw_property_mention,
        requested_check_in=extracted.requested_check_in,
        requested_check_out=extracted.requested_check_out,
        requested_guests=extracted.requested_guests,
        raw_from=from_header,
    )


def _adapt_ota(case: PreBookingEmailCase, parsed_ota: Any) -> ParsedEmailMessage:
    return ParsedEmailMessage(
        source_provider="gmail",
        source_message_id=case.headers.get("Message-ID", case.name),
        source_thread_id=case.headers.get("X-Thread-Id", f"thread-{case.name}"),
        gmail_message_id=case.headers.get("Message-ID", case.name),
        gmail_thread_id=case.headers.get("X-Thread-Id", f"thread-{case.name}"),
        message_id_header=case.headers.get("Message-ID", case.name),
        guest_name=getattr(parsed_ota, "guest_name", "") or "Guest",
        guest_email="guest@example.com",
        reply_channel_address=case.headers.get("Reply-To", ""),
        subject=case.subject,
        body=getattr(parsed_ota, "message_body", "") or getattr(parsed_ota, "latest_guest_turn", "") or case.plain_text,
        latest_guest_message=getattr(parsed_ota, "latest_guest_turn", "") or getattr(parsed_ota, "message_body", "") or "",
        latest_operator_message=getattr(parsed_ota, "latest_operator_turn", "") or "",
        conversation_context=getattr(parsed_ota, "prior_thread_context", "") or "",
        full_body=case.plain_text,
        platform=getattr(parsed_ota, "platform", "vrbo") or "vrbo",
        is_inquiry=True,
        parser_source=getattr(parsed_ota, "parser_source", "ota_parser"),
        property_name=getattr(parsed_ota, "property_name_hint", "") or "",
        property_code="",
        raw_property_mention=getattr(parsed_ota, "property_name_hint", "") or "",
        requested_check_in=getattr(parsed_ota, "check_in", None),
        requested_check_out=getattr(parsed_ota, "check_out", None),
        requested_guests=getattr(parsed_ota, "guests_total", None),
        raw_from=case.headers.get("From", ""),
    )


def _adapt_direct(case: PreBookingEmailCase, parsed_direct: Any) -> ParsedEmailMessage:
    return ParsedEmailMessage(
        source_provider="gmail",
        source_message_id=case.headers.get("Message-ID", case.name),
        source_thread_id=case.headers.get("X-Thread-Id", f"thread-{case.name}"),
        gmail_message_id=case.headers.get("Message-ID", case.name),
        gmail_thread_id=case.headers.get("X-Thread-Id", f"thread-{case.name}"),
        message_id_header=case.headers.get("Message-ID", case.name),
        guest_name=getattr(parsed_direct, "guest_name", "") or "Guest",
        guest_email=getattr(parsed_direct, "guest_email", "") or "guest@example.com",
        reply_channel_address=case.headers.get("Reply-To", ""),
        subject=case.subject,
        body=getattr(parsed_direct, "message_body", "") or getattr(parsed_direct, "latest_guest_turn", "") or case.plain_text,
        latest_guest_message=getattr(parsed_direct, "latest_guest_turn", "") or getattr(parsed_direct, "message_body", "") or "",
        latest_operator_message=getattr(parsed_direct, "latest_operator_turn", "") or "",
        conversation_context=getattr(parsed_direct, "prior_thread_context", "") or "",
        full_body=case.plain_text,
        platform="direct",
        is_inquiry=True,
        parser_source=getattr(parsed_direct, "parser_source", "direct_email_parser"),
        property_name=getattr(parsed_direct, "property_name_hint", "") or "",
        property_code="",
        raw_property_mention=getattr(parsed_direct, "property_name_hint", "") or "",
        requested_check_in=getattr(parsed_direct, "check_in", None),
        requested_check_out=getattr(parsed_direct, "check_out", None),
        requested_guests=(getattr(parsed_direct, "guests_adults", 0) or 0) + (getattr(parsed_direct, "guests_children", 0) or 0) or None,
        raw_from=case.headers.get("From", ""),
    )


def _adapt_vendor(case: PreBookingEmailCase, parsed_vendor: Any) -> ParsedEmailMessage:
    return ParsedEmailMessage(
        source_provider="gmail",
        source_message_id=case.headers.get("Message-ID", case.name),
        source_thread_id=case.headers.get("X-Thread-Id", f"thread-{case.name}"),
        gmail_message_id=case.headers.get("Message-ID", case.name),
        gmail_thread_id=case.headers.get("X-Thread-Id", f"thread-{case.name}"),
        message_id_header=case.headers.get("Message-ID", case.name),
        guest_name="Vendor",
        guest_email="vendor@example.com",
        subject=case.subject,
        body=case.plain_text,
        latest_guest_message="",
        full_body=case.plain_text,
        platform="direct",
        is_inquiry=False,
        parser_source=getattr(parsed_vendor, "parser_source", "vendor_email_parser"),
        property_name="",
        property_code="",
        raw_property_mention="",
        raw_from=case.headers.get("From", ""),
        system_generated=True,
        system_event_type="vendor_ops_email",
    )


def _fallback_parse(case: PreBookingEmailCase) -> Optional[ParsedEmailMessage]:
    parser = GmailEmailParser()
    if parser.is_non_guest_email(case.subject, case.plain_text):
        return None
    return ParsedEmailMessage(
        source_provider="gmail",
        source_message_id=case.headers.get("Message-ID", case.name),
        source_thread_id=case.headers.get("X-Thread-Id", f"thread-{case.name}"),
        gmail_message_id=case.headers.get("Message-ID", case.name),
        gmail_thread_id=case.headers.get("X-Thread-Id", f"thread-{case.name}"),
        message_id_header=case.headers.get("Message-ID", case.name),
        guest_name="Guest",
        guest_email="guest@example.com",
        subject=case.subject,
        body=case.plain_text,
        latest_guest_message=case.plain_text.strip(),
        full_body=case.plain_text,
        platform="direct",
        is_inquiry=True,
        parser_source="generic_gmail_parser",
        property_name="",
        property_code="",
        raw_property_mention="",
        raw_from=case.headers.get("From", ""),
    )


async def _run_parse(case: PreBookingEmailCase) -> tuple[str, Optional[ParsedEmailMessage]]:
    async def _fake_extract(self, **kwargs):
        if case.llm_mode == "success":
            payload = case.llm_payload or {}
            return ExtractedEmailFields(
                latest_guest_message=payload.get("latest_guest_message", "Can the pool be heated?"),
                raw_property_mention=payload.get("property_code_or_name", "") or "",
                requested_check_in=None,
                requested_check_out=None,
                requested_guests=payload.get("requested_guests"),
                sender_email=payload.get("sender_email", "") or "",
                sender_name=payload.get("sender_name", "") or "",
                parser_source="llm_email_extractor_anthropic",
                parser_notes=["synthetic"],
            )
        if case.llm_mode == "fallback":
            raise LLMEmailExtractorFallback("synthetic_invalid_json")
        raise LLMEmailExtractorParseFailure("empty_latest_guest_message")

    parser = GmailEmailParser()
    with patch("app.services.integrations.llm_email_extractor.LLMEmailExtractor.extract", new=_fake_extract):
        try:
            parsed = await parse_structured_inbound_email(
                source_message_id=case.headers.get("Message-ID", case.name),
                subject=case.subject,
                plain_text=case.plain_text,
                raw_html=case.raw_html,
                headers=case.headers,
                parser=parser,
                adapt_llm_inquiry=lambda extracted: _adapt_llm(case, extracted),
                adapt_reservation_event=lambda parsed_event: None,
                adapt_ota_inquiry=lambda parsed_ota: _adapt_ota(case, parsed_ota),
                adapt_direct_inquiry=lambda parsed_direct: _adapt_direct(case, parsed_direct),
                adapt_vendor_email=lambda parsed_vendor: _adapt_vendor(case, parsed_vendor),
                fallback_parse=lambda: _fallback_parse(case),
            )
        except LLMEmailExtractorParseFailure:
            return "hard_parse_failure", None
    if parsed is None:
        return "skipped", None
    return "parsed", parsed


async def _run_prebooking_case(case: PreBookingEmailCase, profile: FlagProfile) -> ReplayResult:
    expected = case.expectations[profile.name]
    if expected.skipped:
        return ReplayResult(
            profile=profile.name,
            name=case.name,
            lifecycle=case.lifecycle,
            channel=case.channel,
            provider=case.provider,
            stage=expected.stage,
            observed_outcome="skipped",
            result_class="skipped",
            notes=[case.notes, "Skipped for this profile"],
        )

    route = detect_inbound_source_route(
        headers=case.headers,
        subject=case.subject,
        plain_text=case.plain_text,
        raw_html=case.raw_html,
    )
    parse_status, parsed = await _run_parse(case)
    result = ReplayResult(
        profile=profile.name,
        name=case.name,
        lifecycle=case.lifecycle,
        channel=case.channel,
        provider=case.provider,
        stage="parse" if parse_status != "parsed" else expected.stage,
        observed_outcome=parse_status,
        result_class="parse_failure" if parse_status != "parsed" else "",
        route=f"{route.family}/{route.provider}/{route.parser_hint}",
        parser_source=(parsed.parser_source if parsed else ""),
        response_excerpt=_truncate((parsed.latest_guest_message if parsed else "")),
        notes=[n for n in [case.notes] if n],
    )
    if parsed is None:
        if parse_status != expected.observed_outcome:
            result.failures.append(f"expected parse outcome {expected.observed_outcome}, got {parse_status}")
        return result

    db = _FakeDbSession()
    services = _make_email_services(db=db)
    gate_decision = _build_gate_decision(case)
    flags = dict(profile.values)
    flags[FeatureFlag.INBOUND_MESSAGE_GATE_REVIEW_ALL] = case.gate_review_all
    flag_service = _NamedFakeFlagService(flags)

    lifecycle_result = _build_prebooking_result(
        case,
        draft_source="messaging_brain" if profile.values.get(FeatureFlag.MESSAGING_BRAIN_RUNTIME) else "model",
    )
    last_saved: dict[str, Any] = {}

    async def _fake_brain_lifecycle(*args, **kwargs):
        last_saved.clear()
        last_saved.update(lifecycle_result)
        return dict(lifecycle_result)

    async def _fake_legacy_process(*args, **kwargs):
        legacy = _build_prebooking_result(case, draft_source="model")
        last_saved.clear()
        last_saved.update(legacy)
        return legacy

    with (
        patch("app.services.feature_flags.get_feature_flags", lambda db=None: flag_service),
        patch(
            "app.services.feature_flags.is_brain_prebooking_lifecycle_primary_enabled",
            AsyncMock(return_value=profile.values.get(FeatureFlag.BRAIN_PREBOOKING_LIFECYCLE_PRIMARY, False)),
        ),
        patch("app.services.concierge.post_booking_routing.is_non_pre_booking_intent", lambda intent: False),
        patch("app.services.integrations.email_dispatch.InboundMessageGate.classify", new=AsyncMock(return_value=gate_decision)),
        patch("app.services.integrations.email_dispatch.persist_gate_decision", new=AsyncMock(return_value=True)),
        patch("app.services.integrations.email_dispatch.update_normalization_outcome", new=AsyncMock(return_value=True)),
        patch("app.services.integrations.email_dispatch._resolve_thread_identity_and_history", new=AsyncMock(return_value=(None, ""))),
        patch("app.services.integrations.email_dispatch._maybe_writeback_property_resolution", new=AsyncMock(return_value=None)),
        patch("app.services.integrations.email_dispatch._review_brain_pre_booking_draft", new=AsyncMock(return_value=("Reviewed synthetic draft", [], [], "pass"))),
        patch(
            "app.services.messaging_brain.pre_booking.PreBookingBrainOrchestrator",
            lambda: SimpleNamespace(
                handle=AsyncMock(
                    return_value=SimpleNamespace(
                        brain_draft=SimpleNamespace(
                            response_text="Synthetic brain draft",
                            confidence=0.84,
                        ),
                        inquiry=SimpleNamespace(structured_asks=["general"]),
                    )
                )
            ),
        ),
        patch("app.services.messaging_brain.pre_booking_lifecycle.run_brain_pre_booking_lifecycle", new=AsyncMock(side_effect=_fake_brain_lifecycle)),
    ):
        dispatch_outcome = await dispatch_pre_booking(services=services, parsed=parsed)

    result.observed_outcome = dispatch_outcome
    result.stage = expected.stage
    result.result_class = expected.result_class
    result.blocked_topics = list(last_saved.get("blocked_by_gap_topics") or [])
    result.triggered_by = str(last_saved.get("triggered_by") or "")
    if last_saved:
        result.notes.append(f"draft_source={last_saved.get('draft_source', '')}")
    if dispatch_outcome != expected.observed_outcome:
        result.failures.append(f"expected dispatch {expected.observed_outcome}, got {dispatch_outcome}")
    if expected.route_contains and expected.route_contains not in result.route:
        result.failures.append(f"expected route to contain {expected.route_contains!r}, got {result.route!r}")
    if expected.parser_source_contains and expected.parser_source_contains not in result.parser_source:
        result.failures.append(
            f"expected parser source to contain {expected.parser_source_contains!r}, got {result.parser_source!r}"
        )
    if expected.blocked_topics:
        if not result.blocked_topics:
            result.failures.append("expected non-empty blocked_by_gap_topics but got []")
        elif sorted(result.blocked_topics) != sorted(expected.blocked_topics):
            result.failures.append(
                f"expected blocked topics {list(expected.blocked_topics)!r}, got {result.blocked_topics!r}"
            )
        warning_topics = []
        for warning in last_saved.get("policy_warnings", []) or []:
            if warning.startswith("missing_property_knowledge:"):
                warning_topics.extend([p.strip() for p in warning.split(":", 1)[1].split(",") if p.strip()])
        if sorted(set(warning_topics)) != sorted(result.blocked_topics):
            result.failures.append(
                f"policy_warnings missing topic mismatch: warnings={sorted(set(warning_topics))!r} "
                f"blocked={sorted(result.blocked_topics)!r}"
            )
    return result


def _build_app(monkeypatch_patches: list[Any], *, flag_runtime: bool, flag_shadow: bool = False) -> tuple[FastAPI, dict[str, Any]]:
    app = FastAPI()
    app.include_router(concierge.router)

    db_session = _FakeDbSession()

    async def _fake_session_dep():
        yield db_session

    def _fake_tenant_dep():
        return TenantContext(company_id=TENANT_ID)

    app.dependency_overrides[concierge.get_async_session] = _fake_session_dep
    app.dependency_overrides[concierge.get_tenant_context] = _fake_tenant_dep

    flags_mock = _NamedFakeFlagService(
        {
            FeatureFlag.MESSAGING_BRAIN_RUNTIME: flag_runtime,
            FeatureFlag.MESSAGING_BRAIN_SHADOW_MODE: flag_shadow,
        }
    )

    monkeypatch_patches.append(
        patch.object(concierge, "get_feature_flags", lambda db=None: flags_mock)
    )

    knowledge_service = MagicMock(name="knowledge_service")
    knowledge_service.get_for_property = AsyncMock(return_value=None)
    knowledge_service.build_property_profile = MagicMock(return_value={})
    knowledge_service.best_faq_answer_with_transfer = AsyncMock(
        return_value={
            "answer": None,
            "match_type": None,
            "score": 0.0,
            "source_property_external_id": None,
            "question": None,
        }
    )
    knowledge_service.record_gap = AsyncMock(return_value=None)
    # NOTE: concierge endpoint no longer imports get_concierge_knowledge_service;
    # it was migrated to ScopedKnowledgeService. The patch is intentionally removed.

    maintenance_service = MagicMock(name="maintenance_service")
    maintenance_service.auto_track_from_message = AsyncMock(return_value=None)
    monkeypatch_patches.append(
        patch.object(concierge, "get_concierge_maintenance_service", lambda: maintenance_service)
    )

    bd_insight_service = MagicMock(name="bd_insight_service")
    bd_insight_service.generate_summary = MagicMock(return_value=None)
    monkeypatch_patches.append(
        patch.object(concierge, "get_concierge_bd_insight_service", lambda: bd_insight_service)
    )

    runner = MagicMock(name="concierge_runner")
    reply = MagicMock(name="reply")
    reply.text = "Existing path response."
    reply.intent = "general"
    reply.suggestions = []
    reply.approved = None
    reply.requires_escalation = False
    runner.handle_message = AsyncMock(return_value=reply)
    monkeypatch_patches.append(
        patch.object(concierge, "get_concierge_runner", lambda: runner)
    )

    event_service = MagicMock(name="event_planning_service")
    event_service.build_trip_plan = AsyncMock(
        return_value={
            "summary": "Local events are light this week; beach day and easy dinner work well.",
            "action_items": [
                {"title": "Sunset dinner", "reason": "Easy arrival-night plan", "urgency": "low"},
            ],
        }
    )
    import app.services.concierge as concierge_services
    monkeypatch_patches.append(
        patch.object(concierge_services, "get_event_planning_service", lambda: event_service)
    )

    return app, {
        "db_session": db_session,
        "runner": runner,
        "event_service": event_service,
    }


async def _post_json(app: FastAPI, path: str, body: dict[str, Any], headers: Optional[dict[str, str]] = None):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.post(path, json=body, headers=headers or {})


async def _run_concierge_case(case: ConciergeMessageCase, profile: FlagProfile) -> ReplayResult:
    expected = case.expectations[profile.name]
    if expected.skipped:
        return ReplayResult(
            profile=profile.name,
            name=case.name,
            lifecycle=case.lifecycle,
            channel=case.channel,
            provider=case.provider,
            stage=expected.stage,
            observed_outcome="skipped",
            result_class="skipped",
            notes=[case.notes, "Skipped for this profile"],
        )

    patches: list[Any] = []
    app, mocks = _build_app(patches, flag_runtime=profile.values.get(FeatureFlag.MESSAGING_BRAIN_RUNTIME, False))
    orch = MagicMock(name="orchestrator")
    orch.handle_inbound_message = AsyncMock(
        return_value=GuestResponseDraft(
            response_text="Brain reactive reply.",
            confidence=0.88,
            final_action=RecommendedAction.DRAFT_ONLY,
            escalation_required=False,
            contributing_agents=["GeneralAgent"],
        )
    )
    import app.services.messaging_brain as brain_pkg

    patches.append(patch.object(brain_pkg, "get_messaging_brain_orchestrator", lambda: orch))

    for active in patches:
        active.start()
    try:
        body = {
            "property_id": str(PROPERTY_ID),
            "message_text": case.message_text,
            "stage": case.stage_value,
            "property_external_id": PROPERTY_CODE,
            "auto_track_maintenance": True,
            "auto_log_gap": True,
        }
        if case.check_in_date:
            body["check_in_date"] = case.check_in_date
        if case.check_out_date:
            body["check_out_date"] = case.check_out_date
        response = await _post_json(
            app,
            "/concierge/message",
            body,
            headers={"X-Company-Id": str(TENANT_ID)},
        )
    finally:
        for active in reversed(patches):
            active.stop()

    payload = response.json()
    result = ReplayResult(
        profile=profile.name,
        name=case.name,
        lifecycle=case.lifecycle,
        channel=case.channel,
        provider=case.provider,
        stage=expected.stage,
        observed_outcome=str(response.status_code),
        result_class=expected.result_class,
        response_excerpt=_truncate(payload.get("response_text", "")),
        notes=[n for n in [case.notes] if n],
    )
    if profile.values.get(FeatureFlag.MESSAGING_BRAIN_RUNTIME, False):
        inbound = orch.handle_inbound_message.await_args.args[0]
        result.observed_outcome = "brain_response"
        if inbound.lifecycle.value != expected.lifecycle:
            result.failures.append(f"expected lifecycle {expected.lifecycle!r}, got {inbound.lifecycle.value!r}")
        if expected.response_contains and expected.response_contains not in payload.get("response_text", ""):
            result.failures.append(
                f"expected response to contain {expected.response_contains!r}, got {payload.get('response_text', '')!r}"
            )
    else:
        result.observed_outcome = "legacy_response"
        if payload.get("response_text") != "Existing path response.":
            result.failures.append(f"legacy response drifted: {payload.get('response_text')!r}")

    if result.observed_outcome != expected.observed_outcome:
        result.failures.append(f"expected outcome {expected.observed_outcome}, got {result.observed_outcome}")
    return result


async def _run_session_case(case: SessionChannelCase, profile: FlagProfile) -> ReplayResult:
    expected = case.expectations[profile.name]
    if expected.skipped:
        return ReplayResult(
            profile=profile.name,
            name=case.name,
            lifecycle=case.lifecycle,
            channel=case.channel,
            provider=case.provider,
            stage=expected.stage,
            observed_outcome="skipped",
            result_class="skipped",
            notes=[case.notes, "Skipped for this profile"],
        )

    db_session = _FakeDbSession()
    session_row = SimpleNamespace(
        phase=case.phase,
        guest_email="guest@example.com",
        guest_phone="+15035551212",
        guest_name="Taylor",
        reservation_id="RSV-001",
        property_id=PROPERTY_ID,
        property_code=PROPERTY_CODE,
        token="sess_123",
        check_in=date(2026, 6, 10),
        check_out=date(2026, 6, 15),
        operator_id=TENANT_ID,
        property_context={},
    )
    orch = MagicMock(name="session_orchestrator")
    orch.handle_inbound_message = AsyncMock(
        return_value=GuestResponseDraft(
            response_text="Here are the arrival details and WiFi notes.",
            confidence=0.9,
            final_action=RecommendedAction.DRAFT_ONLY,
            escalation_required=False,
            contributing_agents=["AccessAgent"],
        )
    )
    property_router = MagicMock(name="property_router")
    property_router.resolve = AsyncMock(
        return_value=SimpleNamespace(
            to_dict=lambda: {
                "wifi_network": "BeachNet",
                "wifi_password": "sunset123",
                "check_in_time": "4:00 PM",
                "check_out_time": "10:00 AM",
                "pets_allowed": False,
                "support_phone": "555-555-1212",
            }
        )
    )

    with (
        patch("app.services.messaging_brain.session_channel_adapter.get_messaging_brain_orchestrator", lambda: orch),
        patch("app.services.concierge.property_router.get_property_router", lambda: property_router),
    ):
        brain_result = await run_session_channel_message(
            message_text=case.message_text,
            db_session=db_session,
            db_row=session_row,
            session_tenant_id=TENANT_ID,
            token="sess_123",
            channel=case.channel,
            source_provider=case.provider,
        )

    inbound = orch.handle_inbound_message.await_args.args[0]
    result = ReplayResult(
        profile=profile.name,
        name=case.name,
        lifecycle=case.lifecycle,
        channel=case.channel,
        provider=case.provider,
        stage=expected.stage,
        observed_outcome="brain_session",
        result_class=expected.result_class,
        response_excerpt=_truncate(brain_result.response_text),
        notes=[n for n in [case.notes] if n],
    )
    if inbound.lifecycle.value != expected.lifecycle:
        result.failures.append(f"expected lifecycle {expected.lifecycle!r}, got {inbound.lifecycle.value!r}")
    if expected.response_contains and expected.response_contains not in brain_result.response_text:
        result.failures.append(
            f"expected session response to contain {expected.response_contains!r}, got {brain_result.response_text!r}"
        )
    if result.observed_outcome != expected.observed_outcome:
        result.failures.append(f"expected outcome {expected.observed_outcome}, got {result.observed_outcome}")
    return result


async def _run_proactive_case(case: ProactivePreviewCase, profile: FlagProfile) -> ReplayResult:
    expected = case.expectations[profile.name]
    if expected.skipped:
        return ReplayResult(
            profile=profile.name,
            name=case.name,
            lifecycle=case.lifecycle,
            channel=case.channel,
            provider=case.provider,
            stage=expected.stage,
            observed_outcome="skipped",
            result_class="skipped",
            notes=[case.notes, "Skipped for this profile"],
        )

    patches: list[Any] = []
    app, mocks = _build_app(patches, flag_runtime=profile.values.get(FeatureFlag.MESSAGING_BRAIN_RUNTIME, False))
    orch = MagicMock(name="proactive_orchestrator")
    orch.handle_proactive_trigger = AsyncMock(
        return_value=GuestResponseDraft(
            response_text="We’re excited to host you and will share check-in details soon.",
            confidence=0.91,
            final_action=RecommendedAction.DRAFT_ONLY,
            escalation_required=False,
            contributing_agents=["ProactiveOutreachAgent"],
        )
    )
    patches.append(
        patch("app.services.messaging_brain.proactive_trigger_adapter.get_messaging_brain_orchestrator", lambda: orch)
    )

    for active in patches:
        active.start()
    try:
        response = await _post_json(
            app,
            "/concierge/proactive",
            {
                "property_id": str(PROPERTY_ID),
                "market_id": "30a",
                "stage": case.stage_value,
                "guest_type": case.guest_type,
                "has_children": case.has_children,
                "lead_time_days": case.lead_time_days,
                "check_in_date": case.check_in_date,
                "check_out_date": case.check_out_date,
            },
        )
    finally:
        for active in reversed(patches):
            active.stop()

    payload = response.json()
    intent = orch.handle_proactive_trigger.await_args.args[0]
    result = ReplayResult(
        profile=profile.name,
        name=case.name,
        lifecycle=case.lifecycle,
        channel=case.channel,
        provider=case.provider,
        stage=expected.stage,
        observed_outcome="proactive_preview",
        result_class=expected.result_class,
        response_excerpt=_truncate(" | ".join(payload.get("messages", []))),
        notes=[n for n in [case.notes] if n],
    )
    if intent.lifecycle.value != expected.lifecycle:
        result.failures.append(f"expected proactive lifecycle {expected.lifecycle!r}, got {intent.lifecycle.value!r}")
    if expected.response_contains and expected.response_contains not in " ".join(payload.get("messages", [])):
        result.failures.append(
            f"expected proactive response to contain {expected.response_contains!r}, got {payload.get('messages', [])!r}"
        )
    if result.observed_outcome != expected.observed_outcome:
        result.failures.append(f"expected outcome {expected.observed_outcome}, got {result.observed_outcome}")
    return result


CASES: list[HarnessCase] = [
    PreBookingEmailCase(
        kind="pre_booking_email",
        name="vrbo_initial_inquiry",
        lifecycle="pre_booking",
        channel="email",
        provider="vrbo",
        subject="Inquiry from Misty Kettinger: Vrbo #3350889",
        headers={
            "From": "Misty Kettinger <sender@messages.homeaway.com>",
            "Reply-To": "uuid@messages.homeaway.com",
            "Message-ID": "syn-001",
            "X-Thread-Id": "thread-001",
        },
        plain_text="Further info\n\nHi, we are checking in on May 16. Is early check in possible?",
        llm_payload={
            "latest_guest_message": "Hi, we are checking in on May 16. Is early check in possible?",
            "property_code_or_name": "Vrbo #3350889",
            "sender_name": "Misty Kettinger",
        },
        expectations={
            "brain_primary": Expectation("dispatch", "pre_booking_new", "brain_hold", "pre_booking", route_contains="vrbo"),
            "ship_i_canary": Expectation("dispatch", "pre_booking_new", "brain_hold", "pre_booking", route_contains="vrbo"),
            "legacy_runtime_off": Expectation("dispatch", "pre_booking_new", "legacy_hold", "pre_booking", route_contains="vrbo"),
        },
    ),
    PreBookingEmailCase(
        kind="pre_booking_email",
        name="airbnb_guest_airfryer",
        lifecycle="pre_booking",
        channel="email",
        provider="airbnb",
        subject="RE: Inquiry for Coastal Haven | Close to Camp with NEW Golf Cart, Aug 5 - 9",
        headers={
            "From": "Airbnb <express@airbnb.com>",
            "Reply-To": "reply@reply.airbnb.com",
            "Message-ID": "syn-006",
            "X-Thread-Id": "thread-006",
        },
        plain_text="KRISTEN\n\nI know this might sound silly - but does the home have an air fryer to use?",
        llm_payload={
            "latest_guest_message": "I know this might sound silly - but does the home have an air fryer to use?",
            "property_code_or_name": "Coastal Haven",
            "sender_name": "Kristen",
        },
        expectations={
            "brain_primary": Expectation("dispatch", "pre_booking_new", "brain_hold", "pre_booking", route_contains="airbnb"),
            "ship_i_canary": Expectation("dispatch", "pre_booking_new", "brain_hold", "pre_booking", route_contains="airbnb"),
            "legacy_runtime_off": Expectation("dispatch", "pre_booking_new", "legacy_hold", "pre_booking", route_contains="airbnb"),
        },
    ),
    PreBookingEmailCase(
        kind="pre_booking_email",
        name="direct_webform_occupancy",
        lifecycle="pre_booking",
        channel="email",
        provider="direct",
        subject="116 W Summersweet Lane (Santa Rosa Beach, FL - 32459)",
        headers={
            "From": "\"morgan_childress@yahoo.com via Beach Habitats 30A\" <lanier@beachhabitats30a.com>",
            "Reply-To": "morgan_childress@yahoo.com",
            "X-Mailer": "Drupal Webform",
            "Message-ID": "syn-011",
            "X-Thread-Id": "thread-011",
        },
        plain_text="Submitted values are:\nArrival Date: Tue, 09/01/2026\nDeparture Date: Sun, 09/06/2026\nAdults: 6\nChildren: 10\nComments/Questions: Are you allowed to purchase extra wrist bands?\nListing of Interest: 116 W Summersweet Lane",
        llm_payload={
            "latest_guest_message": "Are you allowed to purchase extra wrist bands?",
            "property_code_or_name": "116 W Summersweet Lane",
            "sender_name": "Morgan Childress",
        },
        expectations={
            "brain_primary": Expectation("dispatch", "pre_booking_new", "brain_hold", "pre_booking", route_contains="direct_website_form"),
            "ship_i_canary": Expectation("dispatch", "pre_booking_new", "brain_hold", "pre_booking", route_contains="direct_website_form"),
            "legacy_runtime_off": Expectation("dispatch", "pre_booking_new", "legacy_hold", "pre_booking", route_contains="direct_website_form"),
        },
    ),
    PreBookingEmailCase(
        kind="pre_booking_email",
        name="outlook_direct_parking",
        lifecycle="pre_booking",
        channel="email",
        provider="outlook",
        subject="Question about parking for our stay",
        headers={
            "From": "Guest Name <guest@outlook.com>",
            "Reply-To": "guest@outlook.com",
            "Message-ID": "syn-021",
            "X-Thread-Id": "thread-021",
            "User-Agent": "Microsoft Outlook 16.0",
        },
        plain_text="Hi there, we are arriving next month. Is parking available for two SUVs?",
        llm_payload={
            "latest_guest_message": "Is parking available for two SUVs?",
            "sender_name": "Guest Name",
            "sender_email": "guest@outlook.com",
        },
        expectations={
            "brain_primary": Expectation("dispatch", "pre_booking_new", "brain_hold", "pre_booking", route_contains="generic_email"),
            "ship_i_canary": Expectation("dispatch", "pre_booking_new", "brain_hold", "pre_booking", route_contains="generic_email"),
            "legacy_runtime_off": Expectation("dispatch", "pre_booking_new", "legacy_hold", "pre_booking", route_contains="generic_email"),
        },
    ),
    PreBookingEmailCase(
        kind="pre_booking_email",
        name="airbnb_unclear_low_confidence",
        lifecycle="pre_booking",
        channel="email",
        provider="airbnb",
        subject="RE: Inquiry for Somewhere on 30A",
        headers={
            "From": "Airbnb <express@airbnb.com>",
            "Reply-To": "reply@reply.airbnb.com",
            "Message-ID": "syn-019",
            "X-Thread-Id": "thread-019",
        },
        plain_text="Question about your place. Please call me.",
        llm_payload={"latest_guest_message": "Please call me.", "sender_name": "Unknown Guest"},
        gate_classification="guest_message",
        gate_confidence=0.55,
        gate_review_all=True,
        expectations={
            "brain_primary": Expectation("dispatch", "pre_booking_new", "gate_uncertainty_admitted", "pre_booking", route_contains="airbnb"),
            "ship_i_canary": Expectation("dispatch", "pre_booking_new", "gate_uncertainty_admitted", "pre_booking", route_contains="airbnb"),
            "legacy_runtime_off": Expectation("dispatch", "pre_booking_new", "gate_uncertainty_admitted", "pre_booking", route_contains="airbnb"),
        },
    ),
    PreBookingEmailCase(
        kind="pre_booking_email",
        name="generic_pool_heat_gap",
        lifecycle="pre_booking",
        channel="email",
        provider="direct",
        subject="Question about our October stay",
        headers={
            "From": "Karen Basham <karen@example.com>",
            "Message-ID": "syn-014",
            "X-Thread-Id": "thread-014",
        },
        plain_text="Can the pool be heated and what does that cost?",
        llm_payload={
            "latest_guest_message": "Can the pool be heated and what does that cost?",
            "sender_name": "Karen Basham",
            "sender_email": "karen@example.com",
        },
        dispatch_plan="kb_gap_hold",
        notes="Knowledge-gap hold case; blocked topics must survive into Ship I substrate.",
        expectations={
            "brain_primary": Expectation(
                "dispatch", "pre_booking_new", "kb_gap_hold", "pre_booking",
                route_contains="generic_email",
                blocked_topics=("pool_heating_cost",),
            ),
            "ship_i_canary": Expectation(
                "dispatch", "pre_booking_new", "kb_gap_hold", "pre_booking",
                route_contains="generic_email",
                blocked_topics=("pool_heating_cost",),
            ),
            "legacy_runtime_off": Expectation(
                "dispatch", "pre_booking_new", "kb_gap_hold", "pre_booking",
                route_contains="generic_email",
                blocked_topics=("pool_heating_cost",),
            ),
        },
    ),
    ConciergeMessageCase(
        kind="concierge_message",
        name="booked_checkin_question",
        lifecycle="pre_arrival",
        channel="http",
        provider="concierge_api",
        stage_value="booked",
        message_text="Can you remind us what time check-in starts?",
        check_in_date="2026-06-10",
        check_out_date="2026-06-15",
        expectations={
            "brain_primary": Expectation("route", "brain_response", "brain_reactive", "pre_arrival", response_contains="Brain reactive"),
            "ship_i_canary": Expectation("route", "brain_response", "brain_reactive", "pre_arrival", response_contains="Brain reactive"),
            "legacy_runtime_off": Expectation("route", "legacy_response", "legacy_reactive", "pre_arrival", response_contains="Existing path"),
        },
    ),
    SessionChannelCase(
        kind="session_channel",
        name="mobile_instay_wifi",
        lifecycle="in_stay",
        channel="sms",
        provider="mobile_v3",
        phase="in_stay",
        message_text="Can you send the WiFi password again?",
        expectations={
            "brain_primary": Expectation("route", "brain_session", "brain_session", "in_stay", response_contains="WiFi"),
            "ship_i_canary": Expectation("route", "brain_session", "brain_session", "in_stay", response_contains="WiFi"),
            "legacy_runtime_off": Expectation("route", "brain_session", "brain_session", "in_stay", response_contains="WiFi"),
        },
    ),
    ProactivePreviewCase(
        kind="proactive_preview",
        name="booking_welcome_preview",
        lifecycle="pre_arrival",
        channel="http",
        provider="concierge_api",
        stage_value="booked",
        guest_type="family",
        has_children=True,
        lead_time_days=7,
        check_in_date="2026-06-10",
        check_out_date="2026-06-15",
        expectations={
            "brain_primary": Expectation("route", "proactive_preview", "proactive_preview", "pre_arrival", response_contains="excited to host"),
            "ship_i_canary": Expectation("route", "proactive_preview", "proactive_preview", "pre_arrival", response_contains="excited to host"),
            "legacy_runtime_off": Expectation("route", "proactive_preview", "proactive_preview", "pre_arrival", response_contains="excited to host"),
        },
    ),
]


async def _evaluate_case(case: HarnessCase, profile: FlagProfile) -> ReplayResult:
    if isinstance(case, PreBookingEmailCase):
        return await _run_prebooking_case(case, profile)
    if isinstance(case, ConciergeMessageCase):
        return await _run_concierge_case(case, profile)
    if isinstance(case, SessionChannelCase):
        return await _run_session_case(case, profile)
    return await _run_proactive_case(case, profile)


async def run_profile(profile_name: str) -> list[ReplayResult]:
    profile = PROFILES[profile_name]
    return [await _evaluate_case(case, profile) for case in CASES]


async def run_profiles(profile_names: list[str]) -> dict[str, list[ReplayResult]]:
    results: dict[str, list[ReplayResult]] = {}
    for name in profile_names:
        results[name] = await run_profile(name)
    return results


def _render_results(results_by_profile: dict[str, list[ReplayResult]]) -> str:
    lines: list[str] = []
    generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    lines.append("# Brain-Era Regression Harness Report")
    lines.append("")
    lines.append(f"- Generated: {generated_at}")
    lines.append(f"- Profiles: {', '.join(results_by_profile.keys())}")
    lines.append(f"- Cases defined: {len(CASES)}")
    lines.append("")
    lines.append("## Interpretation")
    lines.append("- Green here is acceptable synthetic evidence for code-path verification and pre-flip rehearsal.")
    lines.append("- It is not a substitute for a live production smoke when UI or operator workflow changes.")
    lines.append("- If this harness drifts from current runtime contracts, it stops being rollout evidence.")
    lines.append("")
    for profile_name, results in results_by_profile.items():
        profile = PROFILES[profile_name]
        passed = sum(1 for result in results if result.success)
        failed = sum(1 for result in results if not result.success)
        skipped = sum(1 for result in results if result.result_class == "skipped")
        lines.append(f"## Profile: {profile_name}")
        lines.append(f"- Description: {profile.description}")
        lines.append(f"- Passed: {passed}")
        lines.append(f"- Failed: {failed}")
        lines.append(f"- Skipped: {skipped}")
        lines.append("")
        grouped: dict[str, list[ReplayResult]] = defaultdict(list)
        for result in results:
            grouped[result.lifecycle].append(result)
        for lifecycle in sorted(grouped.keys()):
            lines.append(f"### {lifecycle}")
            lines.append("| Case | Channel | Provider | Stage | Outcome | Class | Route | Parser | Blocked Topics | Notes |")
            lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
            for result in grouped[lifecycle]:
                note_bits = list(result.notes)
                if result.failures:
                    note_bits.append("FAIL: " + " ; ".join(result.failures))
                lines.append(
                    f"| {result.name} | {result.channel} | {result.provider} | {result.stage} | "
                    f"{result.observed_outcome} | {result.result_class or '-'} | {result.route or '-'} | "
                    f"{result.parser_source or '-'} | {','.join(result.blocked_topics) or '-'} | "
                    f"{' / '.join(note_bits) or '-'} |"
                )
            lines.append("")
    return "\n".join(lines)


def _jsonable(results_by_profile: dict[str, list[ReplayResult]]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for profile_name, results in results_by_profile.items():
        payload[profile_name] = [
            {
                "name": r.name,
                "lifecycle": r.lifecycle,
                "channel": r.channel,
                "provider": r.provider,
                "stage": r.stage,
                "observed_outcome": r.observed_outcome,
                "result_class": r.result_class,
                "route": r.route,
                "parser_source": r.parser_source,
                "response_excerpt": r.response_excerpt,
                "blocked_topics": r.blocked_topics,
                "triggered_by": r.triggered_by,
                "notes": r.notes,
                "failures": r.failures,
                "success": r.success,
            }
            for r in results
        ]
    return payload


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the synthetic Brain-era regression harness.")
    parser.add_argument(
        "--profile",
        choices=sorted(PROFILES.keys()),
        default="brain_primary",
        help="Run a single profile (default: brain_primary).",
    )
    parser.add_argument(
        "--flag-matrix",
        action="store_true",
        help="Run all profiles so flag flips can be compared side by side.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of Markdown.",
    )
    return parser


async def _main_async(argv: list[str]) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    profile_names = list(PROFILES.keys()) if args.flag_matrix else [args.profile]
    results_by_profile = await run_profiles(profile_names)
    if args.json:
        print(json.dumps(_jsonable(results_by_profile), indent=2, sort_keys=True))
    else:
        print(_render_results(results_by_profile))
    failures = [
        failure
        for results in results_by_profile.values()
        for result in results
        for failure in result.failures
    ]
    return 1 if failures else 0


def main(argv: Optional[list[str]] = None) -> int:
    return asyncio.run(_main_async(argv if argv is not None else sys.argv[1:]))


if __name__ == "__main__":
    raise SystemExit(main())
