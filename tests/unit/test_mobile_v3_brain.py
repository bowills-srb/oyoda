from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_guest_chat_v3_routes_through_brain_adapter():
    from app.api.v1.endpoints.mobile_v3 import ChatRequest, guest_chat_v3

    session = SimpleNamespace(
        tenant_id="tenant-123",
        operator_id="op-123",
    )

    with patch(
        "app.services.concierge.db_session_service.get_db_session_service",
        return_value=SimpleNamespace(get_session_by_token=AsyncMock(return_value=session)),
    ), patch(
        "app.services.messaging_brain.session_channel_adapter.run_session_channel_message",
        new_callable=AsyncMock,
    ) as mock_run:
        mock_run.return_value = SimpleNamespace(
            response_text="Brain reply",
            should_request_feedback=True,
        )
        response = await guest_chat_v3(
            token="gh_123",
            request=ChatRequest(message="Hi there", channel="mobile"),
            db=AsyncMock(),
        )

    assert response.response == "Brain reply"
    assert response.should_request_feedback is True
    assert mock_run.await_args.kwargs["source_provider"] == "mobile_v3"
