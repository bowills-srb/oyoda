from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest
from unittest.mock import AsyncMock, patch

from app.services.messaging_brain.intake.intent_escalator import PreBookingClassifierMetadata
from app.services.integrations.reservation_aware_routing import MatchedReservation
from app.services.messaging.parser_notes_schema import (
    BrainClassifierMetadataPayload,
    HealerProposalRecordedPayload,
    IntentClassifierMetadataPayload,
    PropertyMentionSurfaceAuditPayload,
    ReservationRoutingMetadataPayload,
    supported_parser_note_types,
    validate_parser_note_payload,
)
from app.services.messaging_brain.audit import MessageEventStoreAuditWriter
from app.services.orchestration.messaging_brain_contracts import (
    AgentAuditRecord,
    ClassifierMetadata,
    InboundGuestMessage,
    IntentType,
    MessageClassification,
)


def test_supported_parser_note_types_are_registry_backed() -> None:
    assert supported_parser_note_types() == (
        "intent_classifier_metadata",
        "brain_classifier_metadata",
        "reservation_routing_metadata",
        "property_mention_surface_audit",
        "healer_proposal_recorded",
    )


def test_prebooking_classifier_audit_payload_matches_registry() -> None:
    payload = PreBookingClassifierMetadata(
        classifier_source="llm_escalated_anthropic",
        threshold=0.40,
        original_intent="local_area",
        original_confidence=0.10,
        escalated=True,
        contradictory_signals=True,
        escalation_provider="anthropic",
        escalated_confidence=0.82,
        escalated_topic="amenities",
        notes=["competing_intents:['local_area', 'amenities']"],
    ).audit_payload()

    validated = validate_parser_note_payload(payload)

    assert isinstance(validated, IntentClassifierMetadataPayload)
    assert validated.escalated_topic == "amenities"


def test_reservation_routing_payload_matches_registry() -> None:
    payload = MatchedReservation(
        reservation_id="res-123",
        guest_name="Christina Moser",
        guest_email="christina@example.com",
        check_in=date(2026, 5, 23),
        check_out=date(2026, 5, 30),
        property_code="100SL2D",
        match_method="email",
    ).parser_notes_payload(routing_source="pms_reservation_matched")

    validated = validate_parser_note_payload(payload)

    assert isinstance(validated, ReservationRoutingMetadataPayload)
    assert validated.pms_match_method == "email"
    assert validated.lifecycle_resolved == "in_stay"


def test_property_mention_surface_audit_payload_matches_registry() -> None:
    payload = {
        "type": "property_mention_surface_audit",
        "parser_path": "deterministic_fallback",
        "selected_surface": "quoted_context",
        "selected_mention": "100 S Spooky Lane Unit 2D",
        "selected_confidence": 0.4,
        "available_surfaces": ["subject", "quoted_context"],
        "candidate_surfaces": ["subject", "quoted_context"],
        "matched_surfaces": ["quoted_context"],
        "agreement": None,
    }

    validated = validate_parser_note_payload(payload)

    assert isinstance(validated, PropertyMentionSurfaceAuditPayload)
    assert validated.selected_surface == "quoted_context"


def test_healer_proposal_recorded_payload_matches_registry() -> None:
    payload = {
        "type": "healer_proposal_recorded",
        "proposal_id": str(uuid4()),
        "proposal_kind": "property_alias_suggestion",
        "signal_source": "property_mention_surface_audit",
        "recorded_at": "2026-05-18T14:00:00+00:00",
    }

    validated = validate_parser_note_payload(payload)

    assert isinstance(validated, HealerProposalRecordedPayload)
    assert validated.proposal_kind == "property_alias_suggestion"


@pytest.mark.asyncio
async def test_brain_classifier_payload_matches_registry() -> None:
    writer = MessageEventStoreAuditWriter()
    record = AgentAuditRecord(
        record_id=str(uuid4()),
        tenant_id="11111111-1111-1111-1111-111111111111",
        message_id="gmail-msg-123",
        channel="gmail",
        classification=MessageClassification(
            intent_type=IntentType.QUESTION,
            intent_topic="general",
            confidence=0.74,
            reason="keyword amenities match",
        ),
        classifier_metadata=ClassifierMetadata(
            classifier_source="deterministic",
            provider_used=None,
            fallback_stage="keyword",
            latency_ms=12,
            input_tokens=None,
            output_tokens=None,
            coercion_notes=["keyword_only"],
            threshold=0.40,
            original_intent="amenities",
            original_confidence=0.74,
            legacy_intent="amenities",
            matched_terms=["high chair", "crib"],
            matched_override_keywords=["crib"],
            resolved_via_override=True,
            deterministic_gate_decision="accepted",
            deterministic_handoff_reason=None,
        ),
    )
    message = InboundGuestMessage(
        message_id="gmail-msg-123",
        tenant_id="11111111-1111-1111-1111-111111111111",
        channel="gmail",
        source_provider="gmail",
        text="Do you have a high chair?",
        guest_email="guest@example.com",
        guest_name="Jamie Guest",
        property_code="100SL2D",
    )

    with patch(
        "app.services.messaging_brain.audit.update_normalization_outcome",
        new=AsyncMock(return_value=None),
    ) as mock_outcome:
        await writer.write(record, db_session=object(), original_message=message)

    parser_notes_append = mock_outcome.await_args.kwargs["parser_notes_append"]
    assert len(parser_notes_append) == 1

    validated = validate_parser_note_payload(parser_notes_append[0])

    assert isinstance(validated, BrainClassifierMetadataPayload)
    assert validated.intent_topic == "general"
    assert validated.original_intent == "amenities"
    assert validated.matched_terms == ["high chair", "crib"]
    assert validated.matched_override_keywords == ["crib"]
    assert validated.resolved_via_override is True
    assert validated.deterministic_gate_decision == "accepted"
