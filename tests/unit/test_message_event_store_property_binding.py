from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.messaging.inbound_normalizer import CanonicalInboundMessage
from app.services.messaging.message_event_store import (
    _resolve_selected_property_binding,
    persist_canonical_inbound_message,
)


class _FakeDb:
    def __init__(self) -> None:
        self.rollbacks = 0
        self.commits = 0

    async def rollback(self) -> None:
        self.rollbacks += 1

    async def commit(self) -> None:
        self.commits += 1


def _sample_canonical(**overrides) -> CanonicalInboundMessage:
    payload = {
        "source_channel": "email",
        "source_provider": "vrbo",
        "source_thread_id": "thread-123",
        "source_message_id": "message-123",
        "sender_role": "guest",
        "sender_display_name": "Taylor",
        "sender_address": "taylor@example.com",
        "sent_at": datetime(2026, 5, 18, 12, 0, 0),
        "raw_subject": "Question",
        "latest_guest_turn": "Can we celebrate with family?",
        "prior_thread_context": "",
        "full_message_text": "Can we celebrate with family?",
        "structured_asks": [],
        "prior_operator_commitments": [],
        "property_binding_candidates": [],
        "channel_constraints": {},
        "parser_used": "test_parser",
        "parser_version": "v1",
        "parser_notes": [],
        "latest_turn_confidence": 0.8,
        "latest_turn_extracted": True,
        "guest_name": "Taylor",
        "guest_email": "taylor@example.com",
    }
    payload.update(overrides)
    return CanonicalInboundMessage(**payload)


@pytest.mark.asyncio
async def test_resolve_selected_property_binding_prefers_direct_property_code() -> None:
    db = _FakeDb()
    normalized = _sample_canonical(
        property_binding_candidates=[
            {
                "candidate_type": "property_code",
                "value": "111VW",
                "confidence": 0.95,
                "source": "upstream",
            }
        ]
    )

    code, match_type = await _resolve_selected_property_binding(
        db, uuid4(), normalized
    )

    assert code == "111VW"
    assert match_type == "property_code_candidate"


@pytest.mark.asyncio
async def test_resolve_selected_property_binding_uses_canonical_service_for_raw_name(
    monkeypatch,
) -> None:
    db = _FakeDb()
    tenant_id = uuid4()
    normalized = _sample_canonical(
        source_provider="vrbo",
        property_binding_candidates=[
            {
                "candidate_type": "raw_property_mention",
                "value": "Sea La Vie",
                "confidence": 0.55,
                "source": "email_text",
            }
        ],
    )
    captured = {}

    class _FakeService:
        async def resolve_property_code(self, tenant, **kwargs):
            captured["tenant"] = tenant
            captured["kwargs"] = kwargs
            return "111VW"

    monkeypatch.setattr(
        "app.services.property_canonical_service.get_canonical_property_service",
        lambda _db: _FakeService(),
    )

    code, match_type = await _resolve_selected_property_binding(
        db, tenant_id, normalized
    )

    assert code == "111VW"
    assert match_type == "raw_property_mention"
    assert captured["tenant"] == tenant_id
    assert captured["kwargs"]["property_name"] == "Sea La Vie"
    assert captured["kwargs"]["platform"] == "vrbo"


@pytest.mark.asyncio
async def test_persist_canonical_inbound_message_passes_resolved_binding_to_upsert(
    monkeypatch,
) -> None:
    db = _FakeDb()
    tenant_id = uuid4()
    normalized = _sample_canonical()
    captured = {}

    async def _fake_table_exists(_db, _name):
        return True

    async def _fake_find_or_create_channel(_db, _tenant_id, _normalized):
        return "channel-1"

    async def _fake_find_or_create_conversation(_db, _tenant_id, _normalized):
        return "conversation-1"

    async def _fake_insert_message(**kwargs):
        return "message-uuid-1"

    async def _fake_resolve_selected_property_binding(_db, _tenant_id, _normalized):
        return "100SL2D", "raw_property_mention"

    async def _fake_upsert_normalization(**kwargs):
        captured.update(kwargs)
        return "norm-1"

    monkeypatch.setattr(
        "app.services.messaging.message_event_store._table_exists",
        _fake_table_exists,
    )
    monkeypatch.setattr(
        "app.services.messaging.message_event_store._find_or_create_channel",
        _fake_find_or_create_channel,
    )
    monkeypatch.setattr(
        "app.services.messaging.message_event_store._find_or_create_conversation",
        _fake_find_or_create_conversation,
    )
    monkeypatch.setattr(
        "app.services.messaging.message_event_store._insert_message",
        _fake_insert_message,
    )
    monkeypatch.setattr(
        "app.services.messaging.message_event_store._resolve_selected_property_binding",
        _fake_resolve_selected_property_binding,
    )
    monkeypatch.setattr(
        "app.services.messaging.message_event_store._upsert_normalization",
        _fake_upsert_normalization,
    )

    result = await persist_canonical_inbound_message(db, tenant_id, normalized)

    assert captured["selected_property_code"] == "100SL2D"
    assert captured["selected_property_match_type"] == "raw_property_mention"
    assert result["selected_property_code"] == "100SL2D"
    assert result["selected_property_match_type"] == "raw_property_mention"
    assert db.commits == 1
