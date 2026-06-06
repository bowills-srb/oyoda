from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.concierge.inquiry_persistence import (
    persist_pre_booking_inquiry_with_normalization,
)
from app.services.messaging.inbound_normalizer import CanonicalInboundMessage
from app.services.messaging_brain.persistence.prebooking_inquiry_types import (
    InquirySaveContext,
    SaveInquiryResult,
)


def _sample_inbound() -> CanonicalInboundMessage:
    return CanonicalInboundMessage(
        source_channel="email",
        source_provider="gmail",
        source_thread_id="thread-123",
        source_message_id="message-123",
        sender_role="guest",
        sender_display_name="Jordan",
        sender_address="jordan@example.com",
        sent_at=datetime(2026, 5, 17, 12, 0, 0),
        raw_subject="Question",
        latest_guest_turn="Can we check in early?",
        prior_thread_context="",
        full_message_text="Can we check in early?",
        structured_asks=[],
        prior_operator_commitments=[],
        property_binding_candidates=[],
        channel_constraints={},
        parser_used="test",
        parser_version="v1",
        parser_notes=[],
        latest_turn_confidence=0.0,
        latest_turn_extracted=True,
        guest_name="Jordan",
        guest_email="jordan@example.com",
    )


def _sample_context() -> InquirySaveContext:
    return InquirySaveContext(
        draft_id="INQ-TEST123",
        company_id=uuid4(),
        selected_property_code="17LL",
        requested_check_in=None,
        requested_check_out=None,
        requested_guests=2,
        intent="availability",
        confidence=0.9,
        draft_text="Draft text",
        draft_source="messaging_brain",
        policy_flags=[],
        policy_warnings=[],
        decision="hold",
        guest_thread_id=None,
    )


@pytest.mark.asyncio
async def test_persist_pre_booking_inquiry_with_normalization_requires_base_row(monkeypatch):
    async def _fake_persist(*args, **kwargs):
        return {}

    monkeypatch.setattr(
        "app.services.concierge.inquiry_persistence.persist_canonical_inbound_message",
        _fake_persist,
    )

    result = await persist_pre_booking_inquiry_with_normalization(
        db=SimpleNamespace(),
        inbound=_sample_inbound(),
        context=_sample_context(),
    )

    assert result.status == "save_failed"
    assert result.error_type == "MissingNormalizationRow"


@pytest.mark.asyncio
async def test_persist_pre_booking_inquiry_with_normalization_updates_outcome(monkeypatch):
    calls = {}

    async def _fake_persist(*args, **kwargs):
        calls["persist"] = True
        return {"normalization_id": "norm-1"}

    async def _fake_save_inquiry(**kwargs):
        calls["save"] = kwargs
        return SaveInquiryResult(inserted=True, status="saved", guest_thread_id="thread-uuid")

    async def _fake_update(*args, **kwargs):
        calls["update"] = kwargs

    monkeypatch.setattr(
        "app.services.concierge.inquiry_persistence.persist_canonical_inbound_message",
        _fake_persist,
    )
    monkeypatch.setattr(
        "app.services.messaging_brain.persistence.prebooking_inquiry_store._save_inquiry",
        _fake_save_inquiry,
    )
    monkeypatch.setattr(
        "app.services.concierge.inquiry_persistence.update_normalization_outcome",
        _fake_update,
    )

    result = await persist_pre_booking_inquiry_with_normalization(
        db=SimpleNamespace(),
        inbound=_sample_inbound(),
        context=_sample_context(),
    )

    assert result.status == "saved"
    assert calls["persist"] is True
    assert calls["save"]["message_id"] == "message-123"
    assert calls["update"]["route_outcome"] == "pre_booking_saved"
    assert calls["update"]["draft_source"] == "messaging_brain"


@pytest.mark.asyncio
async def test_persist_pre_booking_inquiry_with_normalization_backfills_selected_property_code(monkeypatch):
    calls = {}
    context = replace(_sample_context(), selected_property_code="")

    async def _fake_persist(*args, **kwargs):
        return {"normalization_id": "norm-1"}

    async def _fake_load_selected_property_code_from_normalization(**kwargs):
        calls["load"] = kwargs
        return "100SL2D"

    async def _fake_save_inquiry(**kwargs):
        calls["save"] = kwargs
        return SaveInquiryResult(inserted=True, status="saved", guest_thread_id="thread-uuid")

    async def _fake_update(*args, **kwargs):
        calls["update"] = kwargs

    monkeypatch.setattr(
        "app.services.concierge.inquiry_persistence.persist_canonical_inbound_message",
        _fake_persist,
    )
    monkeypatch.setattr(
        "app.services.concierge.inquiry_persistence._load_selected_property_code_from_normalization",
        _fake_load_selected_property_code_from_normalization,
    )
    monkeypatch.setattr(
        "app.services.messaging_brain.persistence.prebooking_inquiry_store._save_inquiry",
        _fake_save_inquiry,
    )
    monkeypatch.setattr(
        "app.services.concierge.inquiry_persistence.update_normalization_outcome",
        _fake_update,
    )

    result = await persist_pre_booking_inquiry_with_normalization(
        db=SimpleNamespace(),
        inbound=_sample_inbound(),
        context=context,
    )

    assert result.status == "saved"
    assert calls["load"]["source_message_id"] == "message-123"
    assert calls["save"]["property_external_id"] == "100SL2D"
    assert calls["update"]["selected_property_code"] == "100SL2D"
