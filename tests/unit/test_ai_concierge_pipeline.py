from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.services.concierge import ai_concierge


def test_get_ai_response_routes_through_session_channel_adapter(monkeypatch):
    captured = {}

    session_row = SimpleNamespace(
        tenant_id="tenant-123",
        token="sess-123",
        phase="arrival_day",
        property_code="31Hickor",
        property_name="Sun Kissed on Hickory",
        property_context={"support_phone": "(850) 555-0123"},
        operator_id="op_test",
        guest_name="Ashley",
        guest_phone="",
        guest_email="",
        reservation_id="res-1",
        property_id=None,
        check_in=None,
        check_out=None,
    )

    async def _fake_run_session_channel_message(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(response_text="final response")

    monkeypatch.setattr(
        ai_concierge,
        "_resolve_session_row",
        AsyncMock(return_value=session_row),
    )
    monkeypatch.setattr(
        ai_concierge,
        "run_session_channel_message",
        _fake_run_session_channel_message,
    )

    result = asyncio.run(
        ai_concierge.get_ai_response(
            message="Can we check in a little early?",
            property_context={"support_phone": "(850) 555-0123"},
            guest_name="Guest",
            property_name="Unknown",
            operator_id="op_test",
            property_code="31Hickor",
            session_token="sess-123",
            tenant_id="tenant-123",
        )
    )

    assert result == "final response"
    assert captured["message_text"] == "Can we check in a little early?"
    assert captured["db_row"] is session_row
    assert captured["session_tenant_id"] == "tenant-123"
    assert captured["token"] == "sess-123"
    assert captured["channel"] == "web_session"
    assert captured["source_provider"] == "concierge_runner"
    assert captured["fallback_support_phone"] == "(850) 555-0123"
