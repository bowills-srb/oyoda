from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from sqlalchemy.exc import DBAPIError, ProgrammingError

from app.services.agents.escalation_handoff_agent import EscalationHandoffAgent
from app.services.agents.knowledge_curator_agent import KnowledgeCuratorAgent
from app.services.agents.pms_sync_agent import PMSSyncAgent
from app.services.integrations import email_dispatch
from app.services.integrations.email_dispatch import EmailDispatchServices
from app.services.integrations.reservation_aware_routing import _load_operator_settings_extra


class _FakeResult:
    def fetchone(self):
        return None


def _programming_error() -> ProgrammingError:
    return ProgrammingError("SELECT 1", {}, RuntimeError("boom"))


@pytest.mark.asyncio
async def test_reservation_routing_operator_settings_rolls_back_on_db_error():
    db = AsyncMock()
    db.execute.side_effect = _programming_error()

    result = await _load_operator_settings_extra(
        tenant_id=UUID("11111111-1111-1111-1111-111111111111"),
        db=db,
    )

    assert result == {}
    db.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_escalation_handoff_load_open_tickets_rolls_back_on_db_error():
    db = AsyncMock()
    db.execute.side_effect = DBAPIError("SELECT 1", {}, RuntimeError("boom"))
    agent = EscalationHandoffAgent()

    tickets = await agent._load_open_tickets(db)

    assert tickets == []
    db.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_pms_sync_load_stale_sessions_rolls_back_on_db_error():
    db = AsyncMock()
    db.execute.side_effect = DBAPIError("SELECT 1", {}, RuntimeError("boom"))
    agent = PMSSyncAgent()

    rows = await agent._load_stale_sessions(db)

    assert rows == []
    db.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_knowledge_curator_load_gaps_rolls_back_on_db_error():
    db = AsyncMock()
    db.execute.side_effect = _programming_error()
    agent = KnowledgeCuratorAgent()

    gaps = await agent._load_gaps(db, "tenant-1", "100SL2D")

    assert gaps == []
    db.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_thread_identity_failure_rolls_back_before_fallback(monkeypatch):
    services = EmailDispatchServices(
        company_id=UUID("11111111-1111-1111-1111-111111111111"),
        db=type("DB", (), {"rollback": AsyncMock()})(),
        watched_email="host@example.com",
        operator_name="Beach Habitats",
        infer_property_match_type=lambda parsed, code: "exact",
        load_property_context=AsyncMock(return_value=({}, {})),
        store_thread_context=AsyncMock(),
        maybe_record_pre_booking_gap=AsyncMock(),
        save_fallback_pre_booking_inquiry=AsyncMock(return_value=False),
        record_kb_gap=AsyncMock(),
        record_property_binding_gap=AsyncMock(),
        build_reply_sender=lambda: None,
        generate_in_stay_reply=AsyncMock(return_value="ok"),
        load_review_event_policy=AsyncMock(return_value={}),
        find_session_by_reservation_context=AsyncMock(return_value=None),
        create_provisional_session_from_system_event=AsyncMock(return_value=False),
        persist_review_event=AsyncMock(),
    )
    parsed = type(
        "Parsed",
        (),
        {
            "guest_name": "Christina",
            "message_id": "msg-1",
            "gmail_message_id": "gmail-1",
            "guest_email": "guest@example.com",
            "property_code": "100SL2D",
            "platform": "email",
            "subject": "hello",
            "requested_check_in": None,
            "requested_check_out": None,
            "requested_guests": None,
        },
    )()

    class _BrokenThreadService:
        async def ensure_inquiry_thread(self, *args, **kwargs):
            raise RuntimeError("broken")

    monkeypatch.setattr(
        "app.services.concierge.guest_thread_service.get_guest_thread_service",
        lambda: _BrokenThreadService(),
    )

    guest_thread_id, history = await email_dispatch._resolve_thread_identity_and_history(
        services=services,
        parsed=parsed,
    )

    assert guest_thread_id is None
    assert history == ""
    services.db.rollback.assert_awaited_once()
