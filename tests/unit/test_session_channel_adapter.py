from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.services.messaging_brain.session_channel_adapter import (
    phase_to_lifecycle,
    run_session_channel_message,
)
from app.services.messaging.identity_resolver import GuestIdentityResolution
from app.services.orchestration.messaging_brain_contracts import (
    GuestResponseDraft,
    MessagingLifecycle,
    RecommendedAction,
)


def _make_session_row(phase: str = "in_stay"):
    return SimpleNamespace(
        tenant_id="tenant-123",
        token="gh_test_123",
        phase=phase,
        property_code="SUNSET_1",
        property_name="Sunset Villa",
        property_context={"support_phone": "(850) 999-0000"},
        operator_id="op-123",
        guest_name="Jordan Smith",
        guest_phone="+15555550123",
        guest_email="jordan@example.com",
        reservation_id="res-123",
        property_id=str(uuid4()),
        check_in=SimpleNamespace(isoformat=lambda: "2026-05-22"),
        check_out=SimpleNamespace(isoformat=lambda: "2026-05-26"),
    )


class _ResolvedPropertyContext:
    def __init__(self):
        self._data = {
            "wifi_network": "Beach_5G",
            "wifi_password": "surf2024",
            "door_code": "9999",
            "check_in_time": "4:00 PM",
            "check_out_time": "10:00 AM",
            "pets_allowed": True,
            "support_phone": "(850) 999-0000",
            "check_in_instructions": "Text when you arrive.",
        }

    def to_dict(self):
        return dict(self._data)


@pytest.mark.parametrize(
    ("phase", "expected"),
    [
        ("pre_arrival", MessagingLifecycle.PRE_ARRIVAL),
        ("arrival_day", MessagingLifecycle.IN_STAY),
        ("in_stay", MessagingLifecycle.IN_STAY),
        ("departure_day", MessagingLifecycle.IN_STAY),
        ("post_stay", MessagingLifecycle.POST_STAY),
        ("", MessagingLifecycle.IN_STAY),
    ],
)
def test_phase_to_lifecycle_maps_session_phases(phase, expected):
    assert phase_to_lifecycle(phase, default=MessagingLifecycle.IN_STAY) == expected


@pytest.mark.asyncio
async def test_run_session_channel_message_builds_inbound_with_overlay():
    db_row = _make_session_row(phase="pre_arrival")
    resolved = _ResolvedPropertyContext()

    captured = {}

    class _FakeOrchestrator:
        async def handle_inbound_message(self, message, *, db_session, shadow_mode):
            captured["message"] = message
            return GuestResponseDraft(
                response_text="Welcome reply",
                confidence=0.88,
                confidence_source="gate_code_intercept",
                final_action=RecommendedAction.AUTO_SEND,
            )

    with patch(
        "app.services.messaging_brain.session_channel_adapter.get_messaging_brain_orchestrator",
        return_value=_FakeOrchestrator(),
    ), patch(
        "app.services.concierge.property_router.get_property_router",
        return_value=SimpleNamespace(resolve=AsyncMock(return_value=resolved)),
    ), patch(
        "app.services.messaging_brain.session_channel_adapter.resolve_guest_identity",
        new=AsyncMock(
            return_value=GuestIdentityResolution(
                state="identified",
                reservation_id="res-123",
                session_token="gh_test_123",
                resolution_source="session_token",
                confidence=0.99,
            )
        ),
    ):
        result = await run_session_channel_message(
            message_text="What time is check-in?",
            db_session=AsyncMock(),
            db_row=db_row,
            session_tenant_id=db_row.tenant_id,
            token=db_row.token,
            channel="sms",
            source_provider="twilio_sms",
        )

    inbound = captured["message"]
    assert result.response_text == "Welcome reply"
    assert result.quick_answer_used is True
    assert result.quick_answer_source == "gate_code"
    assert inbound.identity.state == "identified"
    assert inbound.lifecycle == MessagingLifecycle.PRE_ARRIVAL
    assert inbound.metadata["check_in_date"] == "2026-05-22"
    assert inbound.metadata["check_out_date"] == "2026-05-26"
    overlay = inbound.metadata["context_adapter_overlay"]
    assert overlay["property_facts"]["wifi"] == "Beach_5G / Password: surf2024"
    assert overlay["property_facts"]["check_in"] == "4:00 PM"
    assert overlay["property_facts"]["check_out"] == "10:00 AM"
    assert overlay["reservation_facts"]["check_in_date"] == "2026-05-22"
    assert "property_facts.wifi" in overlay["evidence_keys"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("confidence_source", "expected_source"),
    [
        ("gate_code_intercept", "gate_code"),
        ("escalation_routed", "escalation"),
        (None, None),
    ],
)
async def test_run_session_channel_message_surfaces_quick_answer_source(
    confidence_source,
    expected_source,
):
    db_row = _make_session_row()
    resolved = _ResolvedPropertyContext()

    class _FakeOrchestrator:
        async def handle_inbound_message(self, message, *, db_session, shadow_mode):
            return GuestResponseDraft(
                response_text="Reply",
                confidence=0.9,
                confidence_source=confidence_source,
                final_action=RecommendedAction.AUTO_SEND,
            )

    with patch(
        "app.services.messaging_brain.session_channel_adapter.get_messaging_brain_orchestrator",
        return_value=_FakeOrchestrator(),
    ), patch(
        "app.services.concierge.property_router.get_property_router",
        return_value=SimpleNamespace(resolve=AsyncMock(return_value=resolved)),
    ), patch(
        "app.services.messaging_brain.session_channel_adapter.resolve_guest_identity",
        new=AsyncMock(return_value=GuestIdentityResolution(state="identified")),
    ):
        result = await run_session_channel_message(
            message_text="Hi",
            db_session=AsyncMock(),
            db_row=db_row,
            session_tenant_id=db_row.tenant_id,
            token=db_row.token,
            channel="sms",
            source_provider="twilio_sms",
        )

    assert result.quick_answer_source == expected_source
    assert result.quick_answer_used is (expected_source is not None)
