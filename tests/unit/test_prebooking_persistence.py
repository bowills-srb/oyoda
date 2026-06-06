from __future__ import annotations

import asyncio
from datetime import date, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.services.identity.dual_write import IdentityResolutionError
from app.services.integrations.gmail_inbox_poller import (
    GmailInboxPoller,
    ParsedGmailMessage,
    _build_canonical_from_parsed_gmail,
)
from app.services.messaging.inbound_normalizer import CanonicalInboundMessage
from app.services.messaging_brain.persistence.prebooking_inquiry_store import (
    _insert_pre_booking_inquiry,
    _save_inquiry,
    save_inquiry_from_canonical,
)
from app.services.messaging_brain.persistence.prebooking_inquiry_types import (
    InquirySaveContext,
    SaveInquiryResult,
)


class _FakeRowResult:
    def __init__(self, row=None, rowcount: int = 1):
        self._row = row
        self.rowcount = rowcount

    def fetchone(self):
        return self._row

    def scalar_one_or_none(self):
        return self._row


class _FakeDb:
    def __init__(self, actions):
        self.actions = list(actions)
        self.commits = 0
        self.rollbacks = 0
        self.executed = []

    async def execute(self, statement, params=None):
        self.executed.append((str(statement), params or {}))
        action = self.actions.pop(0)
        if isinstance(action, Exception):
            raise action
        return action

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


def _sample_inbound(**overrides):
    payload = {
        "source_channel": "email",
        "source_provider": "gmail",
        "source_thread_id": "thread-123",
        "source_message_id": "message-123",
        "sender_role": "guest",
        "sender_display_name": "Jordan",
        "sender_address": "jordan@example.com",
        "sent_at": datetime(2026, 5, 8, 12, 0, 0),
        "raw_subject": "Question about the pool",
        "latest_guest_turn": "Is the pool heated?",
        "prior_thread_context": "",
        "full_message_text": "Is the pool heated?",
        "guest_name": "Jordan",
        "guest_email": "jordan@example.com",
    }
    payload.update(overrides)
    return CanonicalInboundMessage(**payload)


def _sample_context(**overrides):
    payload = {
        "draft_id": "INQ-TEST123",
        "company_id": uuid4(),
        "intent": "pool_heat",
        "confidence": 0.91,
        "draft_text": "Let me confirm the pool heat details for you.",
        "decision": "hold",
        "selected_property_code": "BEACH-1",
        "requested_guests": 4,
        "policy_flags": ["flag-1"],
        "policy_warnings": ["warning-1"],
        "guest_thread_id": str(uuid4()),
    }
    payload.update(overrides)
    return InquirySaveContext(**payload)


def test_save_inquiry_commits_before_best_effort_queue_sync(monkeypatch):
    db = _FakeDb([_FakeRowResult(rowcount=1)])

    class _GuestThreadService:
        async def ensure_inquiry_thread(self, *args, **kwargs):
            return str(uuid4())

    class _QueueService:
        async def sync_draft(self, session, tenant_id, draft_id):
            await session.rollback()
            return False

    monkeypatch.setattr(
        "app.services.concierge.guest_thread_service.get_guest_thread_service",
        lambda: _GuestThreadService(),
    )
    monkeypatch.setattr(
        "app.services.concierge.operator_bridge.get_prebooking_queue_service",
        lambda: _QueueService(),
    )
    monkeypatch.setattr(
        "app.services.events.event_triggers.emit_event",
        lambda *args, **kwargs: None,
    )

    save_result = asyncio.run(
        _save_inquiry(
            db=db,
            draft_id="INQ-TEST123",
            thread_id="thread-123",
            message_id="message-123",
            company_id=uuid4(),
            platform="gmail",
            guest_name="Misty",
            message_text="Is the beach walkable?",
            check_in=None,
            check_out=None,
            guests=2,
            property_external_id="BEACH-1",
            intent="local_area",
            confidence=0.92,
            draft_text="Hi Misty! Yes, the beach is an easy walk from the home.",
            policy_flags=[],
            policy_warnings=[],
            decision="hold",
        )
    )

    assert bool(save_result) is True
    assert save_result.status == "saved"
    assert db.commits == 1
    assert db.rollbacks == 0
    insert_params = db.executed[-1][1]
    assert insert_params["autonomy_decision"] == "routed_to_action_auto_off"


def test_save_inquiry_re_resolves_missing_precomputed_guest_thread(monkeypatch):
    resolved_guest_thread_id = str(uuid4())
    db = _FakeDb([
        _FakeRowResult(row=None),
        _FakeRowResult(rowcount=1),
    ])

    class _GuestThreadService:
        async def ensure_inquiry_thread(self, *args, **kwargs):
            return resolved_guest_thread_id

    class _QueueService:
        async def sync_draft(self, session, tenant_id, draft_id):
            return False

    monkeypatch.setattr(
        "app.services.concierge.guest_thread_service.get_guest_thread_service",
        lambda: _GuestThreadService(),
    )
    monkeypatch.setattr(
        "app.services.concierge.operator_bridge.get_prebooking_queue_service",
        lambda: _QueueService(),
    )
    monkeypatch.setattr(
        "app.services.events.event_triggers.emit_event",
        lambda *args, **kwargs: None,
    )

    save_result = asyncio.run(
        _save_inquiry(
            db=db,
            draft_id="INQ-TEST456",
            thread_id="thread-456",
            message_id="message-456",
            company_id=uuid4(),
            platform="gmail",
            guest_name="Casey",
            message_text="Can the pool be heated?",
            check_in=None,
            check_out=None,
            guests=6,
            property_external_id="",
            intent="general",
            confidence=0.5,
            draft_text="Thanks for asking. I am checking on pool heating now.",
            policy_flags=[],
            policy_warnings=[],
            decision="hold",
            guest_thread_id=str(uuid4()),
        )
    )

    assert bool(save_result) is True
    assert save_result.status == "saved"
    assert save_result.guest_thread_id == resolved_guest_thread_id
    assert db.commits == 1


@pytest.mark.asyncio
async def test_save_inquiry_retries_after_missing_guest_thread_fk(monkeypatch):
    resolved_guest_thread_id = str(uuid4())
    fk_error = IntegrityError(
        statement="INSERT INTO pre_booking_inquiries",
        params={},
        orig=Exception(
            'insert or update on table "pre_booking_inquiries" violates foreign key constraint '
            '"fk_pre_booking_inquiries_guest_thread" DETAIL: Key (guest_thread_id) is not present in table "guest_threads".'
        ),
    )
    db = _FakeDb([
        _FakeRowResult(row=1),
        fk_error,
        _FakeRowResult(rowcount=1),
    ])

    class _GuestThreadService:
        async def ensure_inquiry_thread(self, *args, **kwargs):
            return resolved_guest_thread_id

    class _QueueService:
        async def sync_draft(self, session, tenant_id, draft_id):
            return False

    monkeypatch.setattr(
        "app.services.concierge.guest_thread_service.get_guest_thread_service",
        lambda: _GuestThreadService(),
    )
    monkeypatch.setattr(
        "app.services.concierge.operator_bridge.get_prebooking_queue_service",
        lambda: _QueueService(),
    )
    monkeypatch.setattr(
        "app.services.events.event_triggers.emit_event",
        lambda *args, **kwargs: None,
    )

    save_result = await _save_inquiry(
        db=db,
        draft_id="INQ-TEST789",
        thread_id="thread-789",
        message_id="message-789",
        company_id=uuid4(),
        platform="vrbo",
        guest_name="Jordan",
        message_text="Is there parking?",
        check_in=None,
        check_out=None,
        guests=2,
        property_external_id="",
        intent="parking",
        confidence=0.7,
        draft_text="Yes, there is parking available.",
        policy_flags=[],
        policy_warnings=[],
        decision="hold",
        guest_thread_id=str(uuid4()),
    )

    assert bool(save_result) is True
    assert save_result.status == "saved"
    assert save_result.guest_thread_id == resolved_guest_thread_id
    assert db.rollbacks == 1


@pytest.mark.asyncio
async def test_save_inquiry_from_canonical_translates_fields_exactly(monkeypatch):
    captured = {}
    expected_result = SaveInquiryResult(inserted=True, status="saved", guest_thread_id="guest-thread-1")

    async def _fake_persist(**kwargs):
        captured.update(kwargs)
        return expected_result

    monkeypatch.setattr(
        "app.services.concierge.inquiry_persistence.persist_pre_booking_inquiry_with_normalization",
        _fake_persist,
    )

    inbound = _sample_inbound()
    context = _sample_context()

    result = await save_inquiry_from_canonical(db="db-session", inbound=inbound, context=context)

    assert result is expected_result
    assert captured == {
        "db": "db-session",
        "inbound": inbound,
        "context": context,
        "normalization_kwargs": None,
    }


@pytest.mark.asyncio
async def test_save_inquiry_from_canonical_handles_empty_property_and_missing_guest_thread(monkeypatch):
    captured = {}

    async def _fake_persist(**kwargs):
        captured.update(kwargs)
        return SaveInquiryResult(inserted=False, status="duplicate")

    monkeypatch.setattr(
        "app.services.concierge.inquiry_persistence.persist_pre_booking_inquiry_with_normalization",
        _fake_persist,
    )

    inbound = _sample_inbound(source_provider="", source_channel="email", guest_name="", latest_guest_turn="")
    context = _sample_context(
        selected_property_code="",
        draft_text="",
        guest_thread_id=None,
        policy_flags=[],
        policy_warnings=[],
    )

    await save_inquiry_from_canonical(db="db-session", inbound=inbound, context=context)

    assert captured["db"] == "db-session"
    assert captured["inbound"] is inbound
    assert captured["context"] is context


@pytest.mark.asyncio
async def test_insert_pre_booking_inquiry_writes_tenant_and_company_ids():
    db = _FakeDb([_FakeRowResult(rowcount=1)])
    company_id = uuid4()

    await _insert_pre_booking_inquiry(
        db,
        resolved_guest_thread_id=str(uuid4()),
        draft_id="INQ-3C-001",
        thread_id="thread-3c",
        message_id="msg-3c",
        company_id=company_id,
        platform="gmail",
        guest_name="Jordan",
        message_text="Can we heat the pool?",
        check_in=None,
        check_out=None,
        guests=4,
        property_external_id="BH-101",
        intent="pool_heat",
        confidence=0.88,
        draft_text="Yes, pool heat is available.",
        policy_flags=[],
        policy_warnings=[],
        decision="hold",
        blocked_by_gap_topics=["pool_heating_cost"],
    )

    statement, params = db.executed[0]
    assert "tenant_id, company_id" in statement
    assert params["tid"] == company_id
    assert params["cid"] == company_id
    assert params["blocked_topics"] == ["pool_heating_cost"]


@pytest.mark.asyncio
async def test_insert_pre_booking_inquiry_propagates_identity_divergence(monkeypatch):
    async_db = _FakeDb([])

    monkeypatch.setattr(
        "app.services.messaging_brain.persistence.prebooking_inquiry_store.resolve_dual_write_identity",
        lambda **kwargs: (_ for _ in ()).throw(IdentityResolutionError("boom")),
    )

    with pytest.raises(IdentityResolutionError):
        await _insert_pre_booking_inquiry(
            async_db,
            resolved_guest_thread_id=str(uuid4()),
            draft_id="INQ-3C-002",
            thread_id="thread-3c",
            message_id="msg-3c",
            company_id=uuid4(),
            platform="gmail",
            guest_name="Jordan",
            message_text="Can we heat the pool?",
            check_in=None,
            check_out=None,
            guests=4,
            property_external_id="BH-101",
            intent="pool_heat",
            confidence=0.88,
            draft_text="Yes, pool heat is available.",
            policy_flags=[],
            policy_warnings=[],
            decision="hold",
            blocked_by_gap_topics=[],
        )


def _sample_parsed_gmail(**overrides):
    payload = {
        "source_provider": "gmail",
        "source_message_id": "gmail-msg-123",
        "source_thread_id": "gmail-thread-123",
        "gmail_message_id": "gmail-msg-123",
        "gmail_thread_id": "gmail-thread-123",
        "message_id_header": "<gmail-msg-123@example.com>",
        "guest_name": "Misty",
        "guest_email": "Misty@example.com",
        "sender_role": "guest",
        "reply_channel_address": "misty@example.com",
        "subject": "Question about the pool",
        "body": "Full thread body here.",
        "latest_guest_message": "Can the pool be heated?",
        "conversation_context": "Earlier host note.",
        "full_body": "Full thread body here.",
        "asks": [],
        "platform": "vrbo",
        "is_inquiry": True,
        "parser_source": "generic_gmail_parser",
        "property_name": "Beach House",
        "property_code": "BH-1",
        "requested_check_in": date(2026, 7, 4),
        "requested_check_out": date(2026, 7, 8),
        "requested_guests": 5,
        "received_at": datetime(2026, 5, 8, 16, 55, 0),
    }
    payload.update(overrides)
    return ParsedGmailMessage(**payload)


def test_build_canonical_from_parsed_gmail_maps_fallback_fields():
    parsed = _sample_parsed_gmail(asks=["pool_heat"])

    inbound = _build_canonical_from_parsed_gmail(parsed)

    assert inbound.source_channel == "gmail"
    assert inbound.source_provider == "vrbo"
    assert inbound.source_thread_id == "gmail-thread-123"
    assert inbound.source_message_id == "gmail-msg-123"
    assert inbound.sender_role == "guest"
    assert inbound.sender_display_name == "Misty"
    assert inbound.sender_address == "misty@example.com"
    assert inbound.sent_at == datetime(2026, 5, 8, 16, 55, 0)
    assert inbound.raw_subject == "Question about the pool"
    assert inbound.latest_guest_turn == "Can the pool be heated?"
    assert inbound.prior_thread_context == "Earlier host note."
    assert inbound.full_message_text == "Full thread body here."
    assert inbound.structured_asks == ["pool_heat"]
    assert inbound.property_binding_candidates == []
    assert inbound.channel_constraints == {}
    assert inbound.parser_used == "fallback_gmail_poller"
    assert inbound.parser_notes == ["original_parser:generic_gmail_parser", "platform:vrbo"]
    assert inbound.guest_name == "Misty"
    assert inbound.guest_email == "misty@example.com"


@pytest.mark.asyncio
async def test_save_fallback_pre_booking_inquiry_uses_canonical_wrapper(monkeypatch):
    poller = GmailInboxPoller(
        operator_id="op-test",
        company_id=uuid4(),
        token_manager=SimpleNamespace(),
        watched_email="info@example.com",
        db=SimpleNamespace(),
    )
    parsed = _sample_parsed_gmail()
    captured = {}
    stored = {}

    async def _fake_save_from_canonical(*, db, inbound, context):
        captured["db"] = db
        captured["inbound"] = inbound
        captured["context"] = context
        return SaveInquiryResult(inserted=True, status="saved")

    async def _fake_store_context(saved_parsed, draft_id):
        stored["parsed"] = saved_parsed
        stored["draft_id"] = draft_id

    monkeypatch.setattr(
        "app.services.messaging_brain.persistence.prebooking_inquiry_store.save_inquiry_from_canonical",
        _fake_save_from_canonical,
    )
    monkeypatch.setattr(
        poller,
        "_store_gmail_thread_context",
        _fake_store_context,
    )

    ok = await poller._save_fallback_pre_booking_inquiry(
        parsed,
        "parser broke while generating a draft",
    )

    assert ok is True
    inbound = captured["inbound"]
    context = captured["context"]
    assert captured["db"] is poller.db
    assert inbound.source_channel == "gmail"
    assert inbound.source_provider == "vrbo"
    assert inbound.source_thread_id == parsed.gmail_thread_id
    assert inbound.source_message_id == parsed.gmail_message_id
    assert inbound.latest_guest_turn == "Can the pool be heated?"
    assert context.draft_id.startswith("INQ-")
    assert context.company_id == poller.company_id
    assert context.selected_property_code == "BH-1"
    assert context.requested_check_in == date(2026, 7, 4)
    assert context.requested_check_out == date(2026, 7, 8)
    assert context.requested_guests == 5
    assert context.intent == "general_inquiry"
    assert context.confidence == 0.0
    assert context.decision == "hold"
    assert context.draft_source == "gmail_fallback"
    assert context.guest_thread_id is None
    assert context.policy_flags == []
    assert context.policy_warnings == ["gmail_fallback_saved:parser broke while generating a draft"]
    assert "Oyvoda could not generate the AI draft automatically yet" in context.draft_text
    assert stored["parsed"] is parsed
    assert stored["draft_id"] == context.draft_id
