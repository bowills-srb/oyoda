"""
pre_booking.py — provider-agnostic pre-booking brain layer.

Session 5 establishes the split-provider seam for pre-booking:

  TransportAdapter
      normalizes inbound transport payloads (email today, PMS-native
      messaging later) into a provider-neutral PreBookingInquiry.

  ContextAdapter
      normalizes PMS/property/policy context into a provider-neutral
      overlay the existing messaging brain can consume.

  PreBookingBrainOrchestrator
      binds the two adapters together, converts the inquiry into the
      existing InboundGuestMessage contract, and routes it through the
      same GuestMessageBrainOrchestrator used elsewhere.

Escapia is modeled here as a CONTEXT provider, not a message transport.
That is deliberate: Escapia is the first proof of the split-provider
pattern (email transport + Escapia context), not a special case baked
into the core orchestrator.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable
from uuid import UUID

from app.services.connectors.booking_data_provider import BookingPropertyRef
from app.services.integrations.email_inbound import ParsedEmailMessage
from app.services.messaging.identity_resolver import GuestIdentityResolution
from app.services.messaging_brain.agents.booking_context_agent import (
    BookingContextAgent,
)
from app.services.messaging_brain.agents.booking_inquiry_agent import (
    _AVAILABILITY_PATTERNS,
    _GROUP_SIZE_PATTERNS,
)
from app.services.messaging_brain.agents.deterministic_intake_prefilter import (
    legacy_intent_from_classification,
)
from app.services.messaging_brain.booking_context_types import (
    RequestedStay,
    write_booking_context_overlay,
)
from app.services.messaging_brain.orchestrator import (
    GuestMessageBrainOrchestrator,
)
from app.services.orchestration.messaging_brain_contracts import (
    AgentAuditRecord,
    GuestResponseDraft,
    InboundGuestMessage,
    MessagingLifecycle,
    RecommendedAction,
)

logger = logging.getLogger(__name__)


def _fallback_draft(
    guest_name: str,
    intent: str,
    property_data: Dict[str, Any],
    policies: Dict[str, Any],
    message: str = "",
) -> str:
    """Honest hold-path copy when the brain cannot produce a confident draft."""
    prop = (
        property_data.get("display_name")
        or property_data.get("property_name")
        or "the home"
    )
    first = (guest_name or "there").split()[0]

    if intent == "local_area":
        return (
            f"Hi {first}! Thanks for reaching out about {prop}. "
            f"I want to confirm the exact beach and area details before I answer so I give you the most accurate information."
        )
    if intent == "amenities":
        return (
            f"Hi {first}! Thanks for reaching out about {prop}. "
            f"I'm confirming the exact amenity details now so I can give you a precise answer."
        )
    if intent == "group_size":
        return (
            f"Hi {first}! Thanks for reaching out about {prop}. "
            f"I want to confirm the exact sleeping and occupancy details before I answer so I'm giving you the right information."
        )
    if intent == "pet_policy":
        lowered_message = (message or "").lower()
        mentions_service_animal = any(
            phrase in lowered_message
            for phrase in ("service dog", "service dogs", "service animal", "service animals")
        )
        if policies.get("pet_policy") == "allowed":
            return (
                f"Hi {first}! We do welcome well-behaved pets at {prop} with a pet fee. "
                f"Happy to answer any other questions about the stay."
            )
        if mentions_service_animal:
            return (
                f"Hi {first}! Thanks for checking on that for {prop}. "
                f"While the home does not accommodate pets, service animals are handled separately, and I'm confirming the exact property details so I can respond accurately."
            )
        return (
            f"Hi {first}! Unfortunately we're not able to accommodate pets at {prop}. "
            f"Happy to help with any other questions about the property."
        )
    if intent == "availability":
        return (
            f"Hi {first}! Thanks for your interest in {prop}. "
            f"Happy to answer any other questions about the property or stay details."
        )
    if intent == "check_in_process":
        return (
            f"Hi {first}! Thanks for reaching out about your arrival timing at {prop}. "
            f"I'm confirming the exact arrival details now so I can answer accurately."
        )
    if intent == "pricing":
        return (
            f"Hi {first}! Thanks for reaching out about {prop}. "
            f"I'm checking the exact rate details and will make sure you have the clearest answer."
        )
    if intent == "review_response":
        return (
            f"Hi {first}! Thank you for taking the time to share your feedback about {prop}. "
            f"We truly appreciate it and would be glad to welcome you back for a future stay."
        )
    if any(term in (message or "").lower() for term in ("beach", "walk", "distance", "close")):
        return (
            f"Hi {first}! Thanks for reaching out about {prop}. "
            f"I'm confirming the exact location details now so I can give you the most accurate answer."
        )
    return (
        f"Hi {first}! Thanks for reaching out about {prop}. "
        f"I want to confirm the exact details before I answer so I give you the most accurate information."
    )


def _looks_like_booking_inquiry(
    inquiry: "PreBookingInquiry",
) -> tuple[bool, Optional[str]]:
    if inquiry.requested_check_in or inquiry.requested_check_out:
        return True, "date_range_detected"

    text = inquiry.message_text or ""
    if any(pattern.search(text) for pattern in _AVAILABILITY_PATTERNS):
        return True, "availability_keyword"
    if any(pattern.search(text) for pattern in _GROUP_SIZE_PATTERNS):
        return True, "group_size_keyword"
    return False, None


def _build_property_ref_from_inquiry(
    inquiry: "PreBookingInquiry",
    *,
    provider: str,
) -> Optional[BookingPropertyRef]:
    property_code = (inquiry.property_code or "").strip() or None
    provider_property_id = str(
        (inquiry.metadata or {}).get("provider_property_id") or ""
    ).strip() or None
    if not property_code and not provider_property_id:
        return None
    return BookingPropertyRef(
        provider=provider,
        provider_listing_id=provider_property_id,
        property_code=property_code,
    )


def _build_requested_stay_from_inquiry(
    inquiry: "PreBookingInquiry",
) -> Optional[RequestedStay]:
    check_in = inquiry.requested_check_in
    check_out = inquiry.requested_check_out
    guests = inquiry.requested_guests

    if not check_in and not check_out and guests is None:
        return None

    nights: Optional[int] = None
    if check_in and check_out and check_out > check_in:
        nights = (check_out - check_in).days

    return RequestedStay(
        check_in=check_in,
        check_out=check_out,
        nights=nights,
        guests=guests,
    )


@dataclass(frozen=True)
class PreBookingInquiry:
    """Provider-neutral inbound pre-booking inquiry."""

    inquiry_id: str
    tenant_id: str
    channel: str
    transport_provider: str
    context_provider: str
    platform: str

    guest_name: str
    message_text: str
    property_code: str
    property_name: str = ""
    raw_property_mention: str = ""
    platform_listing_id: str = ""
    platform_unit_id: str = ""
    source_property_id: str = ""
    provider_property_id: str = ""

    message_id: str = ""
    thread_id: str = ""
    guest_email: str = ""
    guest_phone: str = ""
    reservation_id: str = ""
    identity: Optional[GuestIdentityResolution] = None

    requested_check_in: Optional[date] = None
    requested_check_out: Optional[date] = None
    requested_guests: Optional[int] = None

    received_at: datetime = field(default_factory=datetime.utcnow)
    structured_asks: List[str] = field(default_factory=list)
    conversation_context: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_inbound_message(
        self,
        *,
        context_overlay: Optional[Dict[str, Any]] = None,
    ) -> InboundGuestMessage:
        """Translate the inquiry into the core brain's inbound contract."""
        metadata = dict(self.metadata)
        metadata["pre_booking_context_provider"] = self.context_provider
        metadata.setdefault("raw_property_mention", self.raw_property_mention)
        metadata.setdefault("property_name", self.property_name)
        metadata.setdefault("platform_listing_id", self.platform_listing_id)
        metadata.setdefault("platform_unit_id", self.platform_unit_id)
        metadata.setdefault("source_property_id", self.source_property_id)
        metadata.setdefault("provider_property_id", self.provider_property_id)
        if context_overlay:
            metadata["context_adapter_overlay"] = context_overlay

        return InboundGuestMessage(
            message_id=self.message_id or self.inquiry_id,
            tenant_id=self.tenant_id,
            channel=self.channel,
            source_provider=self.transport_provider,
            text=self.message_text,
            full_thread_text=self.conversation_context,
            guest_email=self.guest_email,
            guest_phone=self.guest_phone,
            guest_name=self.guest_name,
            identity=self.identity,
            reservation_id=self.reservation_id,
            property_code=self.property_code,
            lifecycle=MessagingLifecycle.PRE_BOOKING,
            thread_id=self.thread_id,
            received_at=self.received_at,
            raw_subject=str(metadata.get("raw_subject") or ""),
            structured_asks=list(self.structured_asks),
            parser_used="pre_booking_transport_adapter",
            metadata=metadata,
        )


@dataclass(frozen=True)
class EscapiaContextPayload:
    """Escapia-backed property/policy context supplied to the binding."""

    property_data: Dict[str, Any] = field(default_factory=dict)
    operator_policies: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PreBookingContextEnvelope:
    """Normalized context returned by a ContextAdapter."""

    provider: str
    property_data: Dict[str, Any] = field(default_factory=dict)
    operator_policies: Dict[str, Any] = field(default_factory=dict)
    overlay: Dict[str, Any] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class PreBookingDraftResult:
    """Result of running one pre-booking inquiry through the brain."""

    inquiry: PreBookingInquiry
    context: PreBookingContextEnvelope
    inbound_message: InboundGuestMessage
    brain_draft: GuestResponseDraft
    effective_action: RecommendedAction
    requires_operator_review: bool
    audit_record: Optional[AgentAuditRecord] = None
    legacy_intent: str = "general"
    intent_confidence: float = 0.0


@dataclass(frozen=True)
class PreBookingProviderBinding:
    """Split-provider binding: one transport adapter + one context adapter."""

    transport: "TransportAdapter"
    context: "ContextAdapter"


@runtime_checkable
class TransportAdapter(Protocol):
    provider: str

    async def normalize(
        self,
        *,
        payload: Any,
        company_id: UUID | str,
        context_provider: str,
    ) -> PreBookingInquiry:
        ...


@runtime_checkable
class ContextAdapter(Protocol):
    provider: str

    async def load_context(
        self,
        *,
        inquiry: PreBookingInquiry,
        payload: Any,
        db_session: Any = None,
    ) -> PreBookingContextEnvelope:
        ...


class EmailTransportAdapter:
    """Normalize provider-backed inbox mail into a PreBookingInquiry."""

    provider = "email"

    async def normalize(
        self,
        *,
        payload: Any,
        company_id: UUID | str,
        context_provider: str,
    ) -> PreBookingInquiry:
        if not isinstance(payload, ParsedEmailMessage):
            raise TypeError("EmailTransportAdapter expects ParsedEmailMessage")

        tenant_id = str(company_id)
        message_text = payload.latest_guest_message or payload.body or payload.full_body
        platform = (payload.platform or "unknown").lower()
        transport_provider = payload.source_provider or payload.parser_source or self.provider
        inquiry_id = payload.message_id or payload.thread_id or payload.message_id_header

        return PreBookingInquiry(
            inquiry_id=inquiry_id or f"prebooking_email_{payload.thread_id}",
            tenant_id=tenant_id,
            channel="email",
            transport_provider=transport_provider,
            context_provider=context_provider,
            platform=platform,
            guest_name=payload.guest_name or "Guest",
            message_text=message_text,
            property_code=payload.property_code,
            property_name=payload.property_name or "",
            raw_property_mention=payload.raw_property_mention or payload.property_name or "",
            platform_listing_id=payload.platform_listing_id or "",
            platform_unit_id=payload.platform_unit_id or "",
            source_property_id=payload.source_property_id or "",
            provider_property_id=payload.provider_property_id or "",
            message_id=payload.message_id,
            thread_id=payload.thread_id,
            guest_email=payload.guest_email,
            guest_phone="",
            reservation_id=payload.reservation_id or "",
            identity=getattr(payload, "identity", None),
            requested_check_in=payload.requested_check_in,
            requested_check_out=payload.requested_check_out,
            requested_guests=payload.requested_guests,
            received_at=payload.received_at,
            structured_asks=list(payload.asks or []),
            conversation_context=payload.conversation_context or payload.full_body or "",
            metadata={
                "property_name": payload.property_name or "",
                "raw_property_mention": payload.raw_property_mention or payload.property_name or "",
                "platform_listing_id": payload.platform_listing_id,
                "platform_unit_id": payload.platform_unit_id,
                "source_property_id": payload.source_property_id,
                "provider_property_id": payload.provider_property_id,
                "provider_account_id": payload.provider_account_id,
                "source_interaction_id": payload.source_interaction_id,
                "reply_channel_address": payload.reply_channel_address,
                "raw_from": payload.raw_from,
                "raw_subject": payload.subject or "",
            },
        )


class EscapiaContextAdapter:
    """Normalize Escapia-backed property + policy data into brain context."""

    provider = "escapia"

    def __init__(
        self,
        *,
        booking_context_agent: BookingContextAgent | None = None,
    ) -> None:
        self._booking_context_agent = booking_context_agent
        if booking_context_agent is None:
            logger.warning(
                "[PreBooking] EscapiaContextAdapter constructed without booking_context_agent; booking-context enrichment disabled"
            )

    async def load_context(
        self,
        *,
        inquiry: PreBookingInquiry,
        payload: Any,
        db_session: Any = None,
    ) -> PreBookingContextEnvelope:
        if payload is None:
            payload = EscapiaContextPayload()
        if not isinstance(payload, EscapiaContextPayload):
            raise TypeError("EscapiaContextAdapter expects EscapiaContextPayload")

        property_data = dict(payload.property_data or {})
        operator_policies = dict(payload.operator_policies or {})
        overlay = self._build_overlay(
            inquiry=inquiry,
            property_data=property_data,
            operator_policies=operator_policies,
        )
        triggered, trigger_reason = _looks_like_booking_inquiry(inquiry)
        if triggered and self._booking_context_agent is not None:
            property_ref = _build_property_ref_from_inquiry(
                inquiry,
                provider=self.provider,
            )
            requested_stay = _build_requested_stay_from_inquiry(inquiry)
            booking_context = await self._booking_context_agent.build(
                property_ref=property_ref,
                requested_stay=requested_stay,
                triggered_by=trigger_reason,
            )
            write_booking_context_overlay(overlay, booking_context)
            logger.info(
                "[PreBooking] booking-context enrichment fired trigger=%s errors=%d",
                trigger_reason,
                len(booking_context.fetch_errors),
            )

        return PreBookingContextEnvelope(
            provider=self.provider,
            property_data=property_data,
            operator_policies=operator_policies,
            overlay=overlay,
            notes=["split_provider: email transport + escapia context"],
        )

    def _build_overlay(
        self,
        *,
        inquiry: PreBookingInquiry,
        property_data: Dict[str, Any],
        operator_policies: Dict[str, Any],
    ) -> Dict[str, Any]:
        property_facts: Dict[str, Any] = {}
        property_knowledge: Dict[str, Any] = {}
        reservation_facts: Dict[str, Any] = {}
        house_rules: Dict[str, Any] = {}
        access_info: Dict[str, Any] = {}
        evidence_keys: List[str] = []

        for src_key, bundle_key in (
            ("wifi", "wifi"),
            ("check_in", "check_in"),
            ("check_out", "check_out"),
        ):
            value = property_data.get(src_key)
            if value:
                property_facts[bundle_key] = value
                evidence_keys.append(f"property_facts.{bundle_key}")

        faq = property_data.get("faq") or property_data.get("faqs") or []
        if isinstance(faq, list) and faq:
            property_knowledge["faq"] = list(faq)
            property_knowledge["faq_count"] = len(faq)
            evidence_keys.extend([
                "property_knowledge.faq",
                "property_knowledge.faq_count",
            ])

        for key in (
            "pet_policy",
            "pet_fee",
            "smoking_policy",
            "quiet_hours",
            "max_guests",
            "min_nights",
            "pricing_negotiation",
        ):
            value = operator_policies.get(key)
            if value not in (None, "", [], {}):
                house_rules[key] = value
                evidence_keys.append(f"house_rules.{key}")

        for key in (
            "parking",
            "parking_instructions",
            "beach_access",
            "door_code_policy",
        ):
            value = property_data.get(key)
            if value not in (None, "", [], {}):
                access_info[key] = value
                evidence_keys.append(f"access_info.{key}")

        if inquiry.requested_check_in:
            reservation_facts["requested_check_in"] = inquiry.requested_check_in.isoformat()
            evidence_keys.append("reservation_facts.requested_check_in")
        if inquiry.requested_check_out:
            reservation_facts["requested_check_out"] = inquiry.requested_check_out.isoformat()
            evidence_keys.append("reservation_facts.requested_check_out")
        if inquiry.requested_guests is not None:
            reservation_facts["requested_guests"] = inquiry.requested_guests
            evidence_keys.append("reservation_facts.requested_guests")

        return {
            "property_facts": property_facts,
            "property_knowledge": property_knowledge,
            "reservation_facts": reservation_facts,
            "house_rules": house_rules,
            "access_info": access_info,
            "evidence_keys": evidence_keys,
            "missing_context": [f"context_provider:{self.provider}"],
        }


class PreBookingBrainOrchestrator:
    """Run a provider-bound pre-booking inquiry through the same brain."""

    def __init__(
        self,
        *,
        brain: Optional[GuestMessageBrainOrchestrator] = None,
    ) -> None:
        self._brain = brain or GuestMessageBrainOrchestrator()

    async def handle(
        self,
        *,
        binding: PreBookingProviderBinding,
        transport_payload: Any,
        context_payload: Any = None,
        company_id: UUID | str,
        db_session: Any = None,
        shadow_mode: bool = False,
    ) -> PreBookingDraftResult:
        inquiry = await binding.transport.normalize(
            payload=transport_payload,
            company_id=company_id,
            context_provider=binding.context.provider,
        )
        context = await binding.context.load_context(
            inquiry=inquiry,
            payload=context_payload,
            db_session=db_session,
        )
        inbound = inquiry.to_inbound_message(context_overlay=context.overlay)
        draft = await self._brain.handle_inbound_message(
            inbound,
            db_session=db_session,
            shadow_mode=shadow_mode,
        )
        audit_record = getattr(getattr(self._brain, "_audit", None), "last_record", None)
        classification = getattr(audit_record, "classification", None)
        classifier_metadata = getattr(audit_record, "classifier_metadata", None)
        legacy_intent = "general"
        intent_confidence = 0.0
        if classification is not None:
            intent_confidence = float(classification.confidence or 0.0)
            legacy_intent = str(
                getattr(classifier_metadata, "legacy_intent", None)
                or legacy_intent_from_classification(
                    classification,
                    message_text=inbound.text or "",
                )
                or "general"
            )

        # Session 5 defines the seam but does not relax the pre-booking
        # review contract. The live pipeline decides later whether a
        # property is in review-only or auto-send mode.
        effective_action = (
            RecommendedAction.ESCALATE
            if draft.final_action == RecommendedAction.ESCALATE
            else RecommendedAction.DRAFT_ONLY
        )
        return PreBookingDraftResult(
            inquiry=inquiry,
            context=context,
            inbound_message=inbound,
            brain_draft=draft,
            effective_action=effective_action,
            requires_operator_review=effective_action != RecommendedAction.AUTO_SEND,
            audit_record=audit_record,
            legacy_intent=legacy_intent,
            intent_confidence=intent_confidence,
        )


__all__ = [
    "ContextAdapter",
    "EmailTransportAdapter",
    "EscapiaContextAdapter",
    "EscapiaContextPayload",
    "PreBookingBrainOrchestrator",
    "PreBookingContextEnvelope",
    "PreBookingDraftResult",
    "PreBookingInquiry",
    "PreBookingProviderBinding",
    "TransportAdapter",
]
