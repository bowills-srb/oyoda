from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest

from app.services.messaging_brain.audit import MessageEventStoreAuditWriter
from app.services.orchestration.messaging_brain_contracts import (
    AgentAuditRecord,
    ComposerMetadata,
    InboundGuestMessage,
)


_TENANT = "11111111-1111-1111-1111-111111111111"
_PROPERTY_CODE = "BEACH_COTTAGE_01"
_MESSAGE_ID = "gmail-msg-123"


def _make_message() -> InboundGuestMessage:
    return InboundGuestMessage(
        message_id=_MESSAGE_ID,
        tenant_id=_TENANT,
        channel="gmail",
        source_provider="gmail",
        text="Can we bring our dog?",
        guest_email="guest@example.com",
        guest_name="Jamie Guest",
        property_code=_PROPERTY_CODE,
        reservation_id="res-123",
    )


def _make_record(*, composer_metadata: ComposerMetadata | None) -> AgentAuditRecord:
    return AgentAuditRecord(
        record_id=str(uuid4()),
        tenant_id=_TENANT,
        message_id=_MESSAGE_ID,
        channel="gmail",
        composer_metadata=composer_metadata,
    )


def _make_composer_metadata() -> ComposerMetadata:
    return ComposerMetadata(
        composer_source="llm_anthropic",
        composer_response_text="Pets are not permitted at this property.",
        composer_latency_ms=321,
        composer_input_tokens=111,
        composer_output_tokens=27,
        composer_notes=[
            "composer_live_mode: operator-facing=composer",
            "composer_grounding_warning:email_address:ops@example.com",
        ],
    )


@pytest.mark.asyncio
async def test_write_outcome_persists_composer_metadata_when_present() -> None:
    writer = MessageEventStoreAuditWriter()
    record = _make_record(composer_metadata=_make_composer_metadata())
    message = _make_message()
    db_session = object()

    with patch(
        "app.services.messaging_brain.audit.update_normalization_outcome",
        new=AsyncMock(return_value=None),
    ) as mock_outcome, patch(
        "app.services.messaging_brain.audit.update_normalization_composer_metadata",
        new=AsyncMock(return_value=None),
    ) as mock_composer:
        await writer.write(
            record,
            db_session=db_session,
            original_message=message,
        )

    mock_outcome.assert_awaited_once()
    mock_composer.assert_awaited_once_with(
        db_session,
        tenant_id=UUID(_TENANT),
        source_channel="gmail",
        source_message_id=_MESSAGE_ID,
        composer_source="llm_anthropic",
        composer_response_text="Pets are not permitted at this property.",
        composer_latency_ms=321,
        composer_input_tokens=111,
        composer_output_tokens=27,
        composer_notes=[
            "composer_live_mode: operator-facing=composer",
            "composer_grounding_warning:email_address:ops@example.com",
        ],
    )


@pytest.mark.asyncio
async def test_write_outcome_skips_composer_persistence_when_metadata_absent() -> None:
    writer = MessageEventStoreAuditWriter()
    record = _make_record(composer_metadata=None)
    message = _make_message()
    db_session = object()

    with patch(
        "app.services.messaging_brain.audit.update_normalization_outcome",
        new=AsyncMock(return_value=None),
    ) as mock_outcome, patch(
        "app.services.messaging_brain.audit.update_normalization_composer_metadata",
        new=AsyncMock(return_value=None),
    ) as mock_composer:
        await writer.write(
            record,
            db_session=db_session,
            original_message=message,
        )

    mock_outcome.assert_awaited_once()
    mock_composer.assert_not_awaited()


def test_adapt_inbound_to_canonical_builds_property_binding_candidates_from_metadata() -> None:
    message = InboundGuestMessage(
        message_id=_MESSAGE_ID,
        tenant_id=_TENANT,
        channel="email",
        source_provider="gmail",
        text="Can we book 17 Lyonia May 13-18?",
        guest_email="guest@example.com",
        guest_name="Jamie Guest",
        property_code="",
        raw_subject="Question about 17 Lyonia",
        metadata={
            "property_name": "17 Lyonia Lane",
            "raw_property_mention": "17 Lyonia",
            "platform_listing_id": "listing-17",
            "platform_unit_id": "unit-17",
        },
    )

    canonical = MessageEventStoreAuditWriter._adapt_inbound_to_canonical(message)
    candidates = canonical.property_binding_candidates
    candidate_types = {candidate["candidate_type"] for candidate in candidates}
    candidate_values = {candidate["value"] for candidate in candidates}

    assert {"platform_listing_id", "platform_unit_id", "raw_property_mention", "property_name"} <= candidate_types
    assert {"listing-17", "unit-17", "17 Lyonia", "17 Lyonia Lane"} <= candidate_values
