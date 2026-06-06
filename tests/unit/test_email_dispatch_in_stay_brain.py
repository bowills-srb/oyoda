from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from app.services.integrations.email_dispatch import (
    EmailDispatchServices,
    dispatch_in_stay,
)
from app.services.orchestration.messaging_brain_contracts import (
    GuestResponseDraft,
    MessagingLifecycle,
    RecommendedAction,
)


def _make_services() -> EmailDispatchServices:
    db = SimpleNamespace(
        commit=AsyncMock(),
        rollback=AsyncMock(),
    )
    sender = MagicMock()
    sender.reply = AsyncMock()
    return EmailDispatchServices(
        company_id=UUID("11111111-1111-1111-1111-111111111111"),
        db=db,
        watched_email="host@example.com",
        operator_name="Beach Habitats",
        infer_property_match_type=lambda parsed, code: "exact",
        load_property_context=AsyncMock(return_value=({"property_name": "100 S Spooky Lane"}, {})),
        store_thread_context=AsyncMock(),
        maybe_record_pre_booking_gap=AsyncMock(),
        save_fallback_pre_booking_inquiry=AsyncMock(return_value=False),
        record_kb_gap=AsyncMock(),
        record_property_binding_gap=AsyncMock(),
        build_reply_sender=lambda: sender,
        generate_in_stay_reply=AsyncMock(return_value="in-stay reply"),
        load_review_event_policy=AsyncMock(return_value={}),
        find_session_by_reservation_context=AsyncMock(return_value=None),
        create_provisional_session_from_system_event=AsyncMock(return_value=False),
        persist_review_event=AsyncMock(),
    )


class _FakeBrainResult:
    class draft:
        final_action = RecommendedAction.AUTO_SEND
        confidence_source = ""
        escalation_required = False
        reason_for_escalation = None
        response_text = "I'll check on the WiFi password for you."

    response_text = "I'll check on the WiFi password for you."


class _FakeFlags:
    async def is_enabled(self, *_args, **_kwargs):
        return True


@pytest.mark.asyncio
async def test_dispatch_in_stay_marks_messaging_brain_as_draft_source(monkeypatch):
    services = _make_services()
    parsed = SimpleNamespace(
        body="Can we get the WiFi password?",
        thread_id="thread-001",
        message_id_header="mid-001",
        guest_email="guest@example.com",
        guest_name="Taylor",
        subject="Need help",
        property_code="SUNSET_1",
        message_id="msg-001",
        _reservation_routing_metadata={},
    )
    session_row = SimpleNamespace(token="gh_123")
    normalization = AsyncMock()
    monkeypatch.setattr(
        "app.services.integrations.email_dispatch.update_normalization_outcome",
        normalization,
    )
    monkeypatch.setattr(
        "app.services.integrations.email_dispatch._build_in_stay_review_result",
        AsyncMock(return_value=_FakeBrainResult()),
    )
    monkeypatch.setattr(
        "app.services.feature_flags.get_feature_flags",
        lambda _db: _FakeFlags(),
    )

    outcome = await dispatch_in_stay(
        services=services,
        parsed=parsed,
        session_row=session_row,
    )

    assert outcome == "in_stay"
    normalization.assert_awaited_once()
    assert normalization.await_args.kwargs["draft_source"] == "messaging_brain"
