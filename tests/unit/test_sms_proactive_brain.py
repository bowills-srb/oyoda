from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_sms_proactive_uses_brain_draft_when_available():
    from app.api.v1.endpoints.sms import (
        ProactiveMessageRequest,
        send_proactive_message,
    )

    session_row = SimpleNamespace(
        tenant_id="tenant-123",
        property_id="prop-123",
        property_code="SEA_LA_VIE",
        property_name="Sea La Vie",
        token="sess-123",
        phase="pre_arrival",
        guest_name="Jordan Smith",
        guest_phone="+15555550123",
        guest_email="jordan@example.com",
        reservation_id="res-123",
        check_in=None,
        check_out=None,
    )

    with patch(
        "app.api.v1.endpoints.sms._lookup_session_by_phone",
        new_callable=AsyncMock,
    ) as mock_lookup, patch(
        "app.services.messaging_brain.proactive_trigger_adapter.build_sms_proactive_intent",
        new_callable=AsyncMock,
    ) as mock_build, patch(
        "app.services.messaging_brain.proactive_trigger_adapter.compose_proactive_draft",
        new_callable=AsyncMock,
    ) as mock_compose, patch(
        "app.api.v1.endpoints.sms.send_sms",
        new_callable=AsyncMock,
    ) as mock_send:
        mock_lookup.return_value = session_row
        mock_build.return_value = object()
        mock_compose.return_value = type("Draft", (), {"response_text": "Brain proactive SMS"})()
        mock_send.return_value = {"sid": "SM123", "status": "queued"}

        result = await send_proactive_message(
            ProactiveMessageRequest(
                property_code="SEA_LA_VIE",
                guest_phone="+15555550123",
                message_type="pre_arrival_3day",
            ),
            db=AsyncMock(),
        )

    assert result["sid"] == "SM123"
    sent_message = mock_send.await_args.args[0]
    assert sent_message.body == "Brain proactive SMS"


@pytest.mark.asyncio
async def test_sms_proactive_falls_back_to_template_on_brain_error():
    from app.api.v1.endpoints.sms import (
        ProactiveMessageRequest,
        send_proactive_message,
    )

    session_row = SimpleNamespace(
        tenant_id="tenant-123",
        property_id="prop-123",
        property_code="SEA_LA_VIE",
        property_name="Sea La Vie",
        token="sess-123",
        phase="pre_arrival",
        guest_name="Jordan Smith",
        guest_phone="+15555550123",
        guest_email="jordan@example.com",
        reservation_id="res-123",
        check_in=None,
        check_out=None,
    )

    with patch(
        "app.api.v1.endpoints.sms._lookup_session_by_phone",
        new_callable=AsyncMock,
    ) as mock_lookup, patch(
        "app.services.messaging_brain.proactive_trigger_adapter.build_sms_proactive_intent",
        new_callable=AsyncMock,
    ) as mock_build, patch(
        "app.services.messaging_brain.proactive_trigger_adapter.compose_proactive_draft",
        new_callable=AsyncMock,
    ) as mock_compose, patch(
        "app.api.v1.endpoints.sms.send_sms",
        new_callable=AsyncMock,
    ) as mock_send:
        mock_lookup.return_value = session_row
        mock_build.return_value = object()
        mock_compose.side_effect = RuntimeError("boom")
        mock_send.return_value = {"sid": "SM124", "status": "queued"}

        result = await send_proactive_message(
            ProactiveMessageRequest(
                property_code="SEA_LA_VIE",
                guest_phone="+15555550123",
                message_type="pre_arrival_3day",
            ),
            db=AsyncMock(),
        )

    assert result["sid"] == "SM124"
    sent_message = mock_send.await_args.args[0]
    assert "Sea La Vie" in sent_message.body
