"""
test_pre_booking_brain_layer.py — Phase 2 Session 5 verification gates.

Session 5 establishes the provider-agnostic pre-booking seam:

  * transport adapter normalizes inbox mail into a neutral inquiry shape
  * context adapter normalizes PMS/property/policy context into an
    overlay the existing brain can consume
  * the same GuestMessageBrainOrchestrator runs on that split-provider
    binding without special-casing Escapia in core orchestration
  * ContextBuilderAgent merges adapter-supplied overlay data additively

This file pins those contracts before Session 6 (BookingInquiryAgent)
depends on them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from app.services.integrations.email_inbound import ParsedEmailMessage
from app.services.integrations.email_dispatch import _review_brain_pre_booking_draft
from app.services.messaging_brain.agents.context_builder_agent import (
    ContextBuilderAgent,
)
from app.services.messaging_brain.pre_booking import (
    EmailTransportAdapter,
    EscapiaContextAdapter,
    EscapiaContextPayload,
    PreBookingBrainOrchestrator,
    PreBookingProviderBinding,
)
from app.services.orchestration.messaging_brain_contracts import (
    GuestResponseDraft,
    InboundGuestMessage,
    IntentType,
    MessageClassification,
    RecommendedAction,
    Urgency,
)


@dataclass
class _LegacyKnowledgeFake:
    property_external_id: Optional[str] = None
    facts: dict = field(default_factory=dict)
    sections: dict = field(default_factory=dict)
    faq: list = field(default_factory=list)


def _make_parsed_email() -> ParsedEmailMessage:
    return ParsedEmailMessage(
        gmail_message_id="gmail-msg-001",
        gmail_thread_id="gmail-thread-001",
        message_id_header="<guest-001@example.com>",
        guest_name="Taylor",
        guest_email="guest@example.com",
        subject="Question about your place",
        body="Hi, is the pool heated and do you allow dogs?",
        latest_guest_message="Is the pool heated and do you allow dogs?",
        conversation_context="Guest asked about amenities and pets.",
        platform="vrbo",
        is_inquiry=True,
        property_name="Gulf View 204",
        property_code="GULF_VIEW_204",
        raw_property_mention="Gulf View 204",
        platform_listing_id="listing-204",
        platform_unit_id="unit-204",
        source_property_id="src-prop-204",
        provider_property_id="provider-prop-204",
        source_provider="gmail",
        requested_guests=4,
    )


def _make_classification() -> MessageClassification:
    return MessageClassification(
        intent_type=IntentType.QUESTION,
        intent_topic="house_rules",
        confidence=0.8,
        urgency=Urgency.MEDIUM,
    )


def _make_inbound_with_overlay() -> InboundGuestMessage:
    return InboundGuestMessage(
        message_id="overlay-msg-001",
        tenant_id="11111111-1111-1111-1111-111111111111",
        channel="email",
        source_provider="gmail",
        text="Can we bring a dog and where do we park?",
        property_code="GULF_VIEW_204",
        metadata={
            "context_adapter_overlay": {
                "property_facts": {"check_in": "4pm"},
                "property_knowledge": {
                    "faq": [
                        {
                            "question": "Are pets allowed?",
                            "answer": "Sorry, no pets.",
                        },
                    ],
                    "faq_count": 1,
                },
                "reservation_facts": {"requested_guests": 4},
                "house_rules": {"pet_policy": "not_allowed"},
                "access_info": {"parking": "Two spaces in the driveway"},
                "operator_commitments": ["No pricing negotiation without approval"],
                "evidence_keys": [
                    "property_facts.check_in",
                    "property_knowledge.faq",
                    "property_knowledge.faq_count",
                    "reservation_facts.requested_guests",
                    "house_rules.pet_policy",
                    "access_info.parking",
                ],
                "missing_context": ["context_provider:escapia"],
            },
        },
    )


def _agent_with_knowledge(knowledge: Optional[_LegacyKnowledgeFake]) -> ContextBuilderAgent:
    fake_service = MagicMock()
    fake_service.get_for_property = AsyncMock(return_value=knowledge)
    return ContextBuilderAgent(knowledge_service=fake_service)


def test_pre_booking_layer_imports_cleanly():
    from app.services.messaging_brain import pre_booking

    assert hasattr(pre_booking, "PreBookingBrainOrchestrator")
    assert hasattr(pre_booking, "EmailTransportAdapter")
    assert hasattr(pre_booking, "EscapiaContextAdapter")


@pytest.mark.asyncio
async def test_email_transport_adapter_normalizes_parsed_email():
    adapter = EmailTransportAdapter()

    inquiry = await adapter.normalize(
        payload=_make_parsed_email(),
        company_id="11111111-1111-1111-1111-111111111111",
        context_provider="escapia",
    )

    assert inquiry.channel == "email"
    assert inquiry.transport_provider == "gmail"
    assert inquiry.context_provider == "escapia"
    assert inquiry.platform == "vrbo"
    assert inquiry.property_code == "GULF_VIEW_204"
    assert inquiry.property_name == "Gulf View 204"
    assert inquiry.raw_property_mention == "Gulf View 204"
    assert inquiry.platform_listing_id == "listing-204"
    assert inquiry.platform_unit_id == "unit-204"
    assert inquiry.source_property_id == "src-prop-204"
    assert inquiry.provider_property_id == "provider-prop-204"
    assert inquiry.message_text == "Is the pool heated and do you allow dogs?"
    assert inquiry.thread_id == "gmail-thread-001"
    assert inquiry.message_id == "gmail-msg-001"
    assert inquiry.metadata["raw_property_mention"] == "Gulf View 204"
    assert inquiry.metadata["property_name"] == "Gulf View 204"


@pytest.mark.asyncio
async def test_email_transport_adapter_preserves_multiple_property_hints_without_property_code():
    parsed = _make_parsed_email()
    parsed.property_code = ""
    parsed.property_name = "17 Lyonia Lane"
    parsed.raw_property_mention = "17 Lyonia"
    parsed.platform_listing_id = "airbnb-listing-17"
    parsed.platform_unit_id = "unit-17"

    inquiry = await EmailTransportAdapter().normalize(
        payload=parsed,
        company_id="11111111-1111-1111-1111-111111111111",
        context_provider="escapia",
    )

    assert inquiry.property_code == ""
    assert inquiry.property_name == "17 Lyonia Lane"
    assert inquiry.raw_property_mention == "17 Lyonia"
    assert inquiry.platform_listing_id == "airbnb-listing-17"
    assert inquiry.platform_unit_id == "unit-17"


@pytest.mark.asyncio
async def test_escapia_context_adapter_builds_overlay():
    adapter = EscapiaContextAdapter()
    inquiry = await EmailTransportAdapter().normalize(
        payload=_make_parsed_email(),
        company_id="11111111-1111-1111-1111-111111111111",
        context_provider="escapia",
    )

    envelope = await adapter.load_context(
        inquiry=inquiry,
        payload=EscapiaContextPayload(
            property_data={
                "wifi": "Network: GulfView / Password: beachtime",
                "check_in": "4pm",
                "parking": "Driveway for 2 cars",
                "faq": [
                    {
                        "question": "Are pets allowed?",
                        "answer": "Sorry, no pets.",
                    },
                ],
            },
            operator_policies={
                "pet_policy": "not_allowed",
                "min_nights": 3,
            },
        ),
    )

    assert envelope.provider == "escapia"
    assert envelope.overlay["property_facts"]["wifi"].startswith("Network:")
    assert envelope.overlay["property_knowledge"]["faq_count"] == 1
    assert envelope.overlay["house_rules"]["pet_policy"] == "not_allowed"
    assert envelope.overlay["access_info"]["parking"] == "Driveway for 2 cars"
    assert "property_knowledge.faq" in envelope.overlay["evidence_keys"]


@pytest.mark.asyncio
async def test_context_builder_merges_context_adapter_overlay():
    agent = _agent_with_knowledge(None)

    bundle = await agent.build(
        _make_inbound_with_overlay(),
        _make_classification(),
        db_session=MagicMock(),
    )

    assert bundle.property_facts["check_in"] == "4pm"
    assert bundle.property_knowledge["faq_count"] == 1
    assert bundle.property_knowledge["faq"][0]["question"] == "Are pets allowed?"
    assert bundle.reservation_facts["requested_guests"] == 4
    assert bundle.house_rules["pet_policy"] == "not_allowed"
    assert bundle.access_info["parking"] == "Two spaces in the driveway"
    assert bundle.operator_commitments == ["No pricing negotiation without approval"]
    assert "context_provider:escapia" in bundle.missing_context
    assert "property_knowledge.faq" in bundle.evidence_keys


@pytest.mark.asyncio
async def test_context_builder_overlay_augments_but_does_not_override_kb_facts():
    knowledge = _LegacyKnowledgeFake(
        facts={"wifi": "Canonical WiFi", "check_in": "3pm"},
    )
    agent = _agent_with_knowledge(knowledge)
    message = _make_inbound_with_overlay()
    message.metadata["context_adapter_overlay"]["property_facts"]["wifi"] = "Overlay WiFi"

    bundle = await agent.build(
        message,
        _make_classification(),
        db_session=MagicMock(),
    )

    assert bundle.property_facts["wifi"] == "Canonical WiFi"
    assert bundle.property_facts["check_in"] == "3pm"


@pytest.mark.asyncio
async def test_pre_booking_brain_orchestrator_runs_split_provider_binding():
    brain = MagicMock()
    brain.handle_inbound_message = AsyncMock(
        return_value=GuestResponseDraft(
            response_text="Thanks for asking — a host will confirm pet policy shortly.",
            confidence=0.82,
            final_action=RecommendedAction.DRAFT_ONLY,
            auto_send_allowed=False,
            escalation_required=False,
            evidence_references=["property_knowledge.faq"],
            contributing_agents=["HouseRulesAgent"],
        )
    )

    orchestrator = PreBookingBrainOrchestrator(brain=brain)
    binding = PreBookingProviderBinding(
        transport=EmailTransportAdapter(),
        context=EscapiaContextAdapter(),
    )

    result = await orchestrator.handle(
        binding=binding,
        transport_payload=_make_parsed_email(),
        context_payload=EscapiaContextPayload(
            property_data={
                "faq": [
                    {
                        "question": "Are pets allowed?",
                        "answer": "Sorry, no pets.",
                    },
                ],
            },
            operator_policies={"pet_policy": "not_allowed"},
        ),
        company_id="11111111-1111-1111-1111-111111111111",
        db_session=MagicMock(),
    )

    assert result.inquiry.transport_provider == "gmail"
    assert result.inquiry.context_provider == "escapia"
    assert result.inbound_message.channel == "email"
    assert result.inbound_message.metadata["pre_booking_context_provider"] == "escapia"
    assert "context_adapter_overlay" in result.inbound_message.metadata
    assert result.brain_draft.response_text.startswith("Thanks for asking")
    assert result.effective_action == RecommendedAction.DRAFT_ONLY
    assert result.requires_operator_review is True
    brain.handle_inbound_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_pre_booking_brain_orchestrator_holds_auto_send_by_default():
    brain = MagicMock()
    brain.handle_inbound_message = AsyncMock(
        return_value=GuestResponseDraft(
            response_text="Yes, we do allow well-behaved dogs.",
            confidence=0.94,
            final_action=RecommendedAction.AUTO_SEND,
            auto_send_allowed=True,
            escalation_required=False,
            contributing_agents=["HouseRulesAgent"],
        )
    )
    orchestrator = PreBookingBrainOrchestrator(brain=brain)

    result = await orchestrator.handle(
        binding=PreBookingProviderBinding(
            transport=EmailTransportAdapter(),
            context=EscapiaContextAdapter(),
        ),
        transport_payload=_make_parsed_email(),
        context_payload=EscapiaContextPayload(),
        company_id="11111111-1111-1111-1111-111111111111",
    )

    assert result.brain_draft.final_action == RecommendedAction.AUTO_SEND
    assert result.effective_action == RecommendedAction.DRAFT_ONLY
    assert result.requires_operator_review is True


@pytest.mark.asyncio
async def test_pre_booking_brain_orchestrator_preserves_escalate():
    brain = MagicMock()
    brain.handle_inbound_message = AsyncMock(
        return_value=GuestResponseDraft(
            response_text="Please call 911 if there is immediate danger.",
            confidence=0.98,
            final_action=RecommendedAction.ESCALATE,
            auto_send_allowed=False,
            escalation_required=True,
            reason_for_escalation="emergency",
            contributing_agents=["EscalationAgent"],
        )
    )
    orchestrator = PreBookingBrainOrchestrator(brain=brain)

    result = await orchestrator.handle(
        binding=PreBookingProviderBinding(
            transport=EmailTransportAdapter(),
            context=EscapiaContextAdapter(),
        ),
        transport_payload=_make_parsed_email(),
        context_payload=EscapiaContextPayload(),
        company_id="11111111-1111-1111-1111-111111111111",
    )

    assert result.effective_action == RecommendedAction.ESCALATE
    assert result.requires_operator_review is True


@pytest.mark.asyncio
async def test_brain_review_helper_passes_tenant_id_to_response_reviewer():
    tenant_id = UUID("11111111-1111-1111-1111-111111111111")
    review_result = MagicMock(
        verdict="approve",
        reviewed_response="",
        flags=[],
        rationale="ok",
        review_source="groq_adversarial",
    )

    with patch(
        "app.services.messaging_brain.grounding.prebooking_grounding._build_prebooking_grounding_context",
        return_value="source context",
    ), patch(
        "app.services.messaging_brain.grounding.response_reviewer.review_concierge_response",
        new=AsyncMock(return_value=review_result),
    ) as reviewer:
        final_text, additional_flags, additional_warnings, review_verdict = await _review_brain_pre_booking_draft(
            guest_name="Taylor",
            platform="airbnb",
            message="Can we check in early?",
            intent="check_in_process",
            property_data={"property_name": "Gulf View 204"},
            operator_policies={},
            draft_text="I'll confirm whether early check-in is possible.",
            tenant_id=tenant_id,
        )

    assert final_text == "I'll confirm whether early check-in is possible."
    assert additional_flags == []
    assert review_verdict == "pass"
    assert len(additional_warnings) == 1
    assert reviewer.await_args.kwargs["tenant_id"] == tenant_id
