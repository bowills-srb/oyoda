from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock

import httpx
import pytest

from app.services.messaging_brain.inbound_message_gate import (
    InboundClassification,
    InboundMessageGate,
)


EML_GUEST_AIR_FRYER = {
    "from_header": "Airbnb <express@airbnb.com>",
    "subject": "RE: Inquiry for Coastal Haven | Close to Camp with NEW Golf Cart, Aug 5 - 9",
    "reply_to": "4chj00sp5kky6q1vbsuovwfm8gw9x0oorkvx@reply.airbnb.com",
    "x_template": "MESSAGING_NEW_MESSAGE_EMAIL_DIGEST",
    "x_category": "message",
    "return_path": "mail@express.airbnb.com",
    "body_text": (
        "INQUIRY FOR COASTAL HAVEN\n\n"
        "KRISTEN\n\n"
        "I know this might sound silly - but does the home have an air fryer to use?\n"
    ),
    "expected": InboundClassification.GUEST_MESSAGE,
}

EML_GUEST_EMERALD_BEACH = {
    "from_header": "Airbnb <express@airbnb.com>",
    "subject": "RE: Inquiry for Emerald Bliss | NatureWalk 30A, Golf Cart + Bikes, May 23 - 29",
    "reply_to": "4vw2s91yett7fza4kzngwyhoak0d1162tde2@reply.airbnb.com",
    "x_template": "MESSAGING_NEW_MESSAGE_EMAIL_DIGEST",
    "x_category": "message",
    "return_path": "mail@express.airbnb.com",
    "body_text": (
        "KERI\n\n"
        "Good evening. Looking at your property and was wondering how far the beach "
        "is from this house? Via bike? Via golf cart?\n"
    ),
    "expected": InboundClassification.GUEST_MESSAGE,
}

EML_OP_BOOKING_INITIAL = {
    "from_header": "Airbnb <automated@airbnb.com>",
    "subject": "Inquiry for Emerald Bliss | NatureWalk 30A, Golf Cart + Bikes for May 23 - 29, 2026",
    "reply_to": None,
    "x_template": "BOOKING_INITIAL_INQUIRY",
    "x_category": "support",
    "return_path": "mail@automated.airbnb.com",
    "body_text": (
        "RESPOND TO KERI'S INQUIRY\n\n"
        "Pre-approve / Decline\n\n"
        "YOU HAVE 24 HOURS TO RESPOND\n"
    ),
    "expected": InboundClassification.OPERATIONAL_NOTIFICATION,
}

EML_OP_RESERVATION_REMINDER = {
    "from_header": '"Keri (Airbnb)" <express@airbnb.com>',
    "subject": "Inquiry for Emerald Bliss | NatureWalk 30A, Golf Cart + Bikes for May 23 - 29, 2026",
    "reply_to": None,
    "x_template": "RESERVATION_INQUIRIES_REMINDER",
    "x_category": "reminders",
    "return_path": "mail@express.airbnb.com",
    "body_text": (
        "RESPOND TO KERI'S INQUIRY\n\n"
        "Maintain your response rate and help Keri finalize their trip.\n"
    ),
    "expected": InboundClassification.OPERATIONAL_NOTIFICATION,
}

EML_OP_RESOLUTIONS = {
    "from_header": "Airbnb <resolutions@airbnb.com>",
    "subject": "Airbnb Reimbursement Request [CLSF-05819862] [HMTAZXMB3N]",
    "reply_to": None,
    "x_template": "RESOLUTION_CENTER_NOTIFICATION",
    "x_category": "support",
    "return_path": "mail@automated.airbnb.com",
    "body_text": "A guest has filed a reimbursement request for damages.",
    "expected": InboundClassification.OPERATIONAL_NOTIFICATION,
}

EML_GUEST_VRBO_INQUIRY = {
    "from_header": "Adrienne Wallace <sender@messages.homeaway.com>",
    "subject": "Inquiry from Adrienne Wallace: Jul 30 - Aug 2, 2026 - Vrbo #2174163",
    "reply_to": "13604589-c9d3-4cf5-b6d4-37ff6cd3ad7d@messages.homeaway.com",
    "x_template": None,
    "x_category": None,
    "return_path": "msprvs1=20106Q1J4bT7F=info@beachhabitats30a.com@sp.bounces.messages.homeaway.com",
    "body_text": (
        "Further info\n\n"
        "Hi, we are interested in your property and wanted to confirm whether the "
        "beach is walkable for young kids.\n"
    ),
    "expected": InboundClassification.GUEST_MESSAGE,
}

EML_GUEST_VRBO_REPLY = {
    "from_header": "Danielle Burk <sender@messages.homeaway.com>",
    "subject": "Reservation from Danielle Burk: Aug 12 - Aug 16, 2026 - Vrbo #2813936",
    "reply_to": "2d5b8f9e-4d39-43b6-9b13-02f3d2f7a2ca@messages.homeaway.com",
    "x_template": None,
    "x_category": None,
    "return_path": "msprvs1=abcdef@sp.bounces.messages.homeaway.com",
    "body_text": (
        "Vrbo: Danielle Burk has replied to your message\n\n"
        "Thanks so much. Is the pool heated in mid-August?\n"
    ),
    "expected": InboundClassification.GUEST_MESSAGE,
}

ALL_KNOWN_EMAILS = [
    EML_GUEST_AIR_FRYER,
    EML_GUEST_EMERALD_BEACH,
    EML_OP_BOOKING_INITIAL,
    EML_OP_RESERVATION_REMINDER,
    EML_OP_RESOLUTIONS,
    EML_GUEST_VRBO_INQUIRY,
    EML_GUEST_VRBO_REPLY,
]


def _make_gate() -> InboundMessageGate:
    return InboundMessageGate(anthropic_api_key="test-key")


@pytest.mark.asyncio
async def test_classifies_guest_message_proceeds_when_high_confidence(monkeypatch):
    gate = _make_gate()
    monkeypatch.setattr(
        gate,
        "_call_anthropic",
        AsyncMock(
            return_value=(
                json.dumps(
                    {
                        "classification": "guest_message",
                        "confidence": 0.95,
                        "reasoning": "reply path and clear guest text",
                        "extracted": {
                            "guest_text": "does the home have an air fryer",
                            "guest_name": "Kristen",
                            "property_reference": "Coastal Haven",
                            "reply_path": EML_GUEST_AIR_FRYER["reply_to"],
                            "thread_id": None,
                        },
                    }
                ),
                100,
                50,
            )
        ),
    )
    decision = await gate.classify(**{k: v for k, v in EML_GUEST_AIR_FRYER.items() if k != "expected"})
    assert decision.classification == InboundClassification.GUEST_MESSAGE
    assert decision.should_proceed_as_guest is True
    assert decision.should_route_to_review is False
    assert decision.extracted is not None
    assert decision.extracted.guest_name == "Kristen"


@pytest.mark.asyncio
async def test_low_confidence_guest_message_routes_to_review(monkeypatch):
    gate = _make_gate()
    monkeypatch.setattr(
        gate,
        "_call_anthropic",
        AsyncMock(
            return_value=(
                json.dumps(
                    {
                        "classification": "guest_message",
                        "confidence": 0.55,
                        "reasoning": "looks guest-like but confidence is low",
                        "extracted": {"guest_text": "..."},
                    }
                ),
                100,
                50,
            )
        ),
    )
    decision = await gate.classify(**{k: v for k, v in EML_GUEST_AIR_FRYER.items() if k != "expected"})
    assert decision.should_proceed_as_guest is False
    assert decision.should_route_to_review is True


@pytest.mark.asyncio
async def test_operational_notification_does_not_proceed(monkeypatch):
    gate = _make_gate()
    monkeypatch.setattr(
        gate,
        "_call_anthropic",
        AsyncMock(
            return_value=(
                json.dumps(
                    {
                        "classification": "operational_notification",
                        "confidence": 0.93,
                        "reasoning": "automation template and action prompts",
                        "extracted": None,
                    }
                ),
                100,
                50,
            )
        ),
    )
    decision = await gate.classify(**{k: v for k, v in EML_OP_BOOKING_INITIAL.items() if k != "expected"})
    assert decision.classification == InboundClassification.OPERATIONAL_NOTIFICATION
    assert decision.should_proceed_as_guest is False
    assert decision.should_route_to_review is False


@pytest.mark.asyncio
async def test_unclear_routes_to_review(monkeypatch):
    gate = _make_gate()
    monkeypatch.setattr(
        gate,
        "_call_anthropic",
        AsyncMock(
            return_value=(
                json.dumps(
                    {
                        "classification": "unclear",
                        "confidence": 0.4,
                        "reasoning": "signals conflict",
                        "extracted": None,
                    }
                ),
                100,
                50,
            )
        ),
    )
    decision = await gate.classify(**{k: v for k, v in EML_GUEST_AIR_FRYER.items() if k != "expected"})
    assert decision.classification == InboundClassification.UNCLEAR
    assert decision.should_route_to_review is True


@pytest.mark.asyncio
async def test_anthropic_failure_returns_unclear(monkeypatch):
    gate = _make_gate()
    monkeypatch.setattr(
        gate,
        "_call_anthropic",
        AsyncMock(side_effect=RuntimeError("simulated network failure")),
    )
    decision = await gate.classify(**{k: v for k, v in EML_GUEST_AIR_FRYER.items() if k != "expected"})
    assert decision.classification == InboundClassification.UNCLEAR
    assert decision.error is not None
    assert "simulated network failure" in decision.error


@pytest.mark.asyncio
async def test_invalid_json_response_returns_unclear(monkeypatch):
    gate = _make_gate()
    monkeypatch.setattr(gate, "_call_anthropic", AsyncMock(return_value=("not valid json", 100, 50)))
    decision = await gate.classify(**{k: v for k, v in EML_GUEST_AIR_FRYER.items() if k != "expected"})
    assert decision.classification == InboundClassification.UNCLEAR
    assert decision.error is not None


@pytest.mark.asyncio
async def test_retryable_http_status_retries_then_succeeds(monkeypatch):
    gate = _make_gate()
    sleep_mock = AsyncMock()

    class _FakeClient:
        def __init__(self):
            self.calls = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, *, headers=None, json=None):
            self.calls += 1
            if self.calls == 1:
                return httpx.Response(
                    429,
                    request=httpx.Request("POST", url),
                    text="rate limited",
                )
            return httpx.Response(
                200,
                request=httpx.Request("POST", url),
                json={"content": [{"type": "text", "text": "{\"classification\":\"guest_message\",\"confidence\":0.9,\"reasoning\":\"ok\",\"extracted\":null}"}]},
            )

    monkeypatch.setattr("app.services.messaging_brain.inbound_message_gate.asyncio.sleep", sleep_mock)
    monkeypatch.setattr("app.services.messaging_brain.inbound_message_gate.httpx.AsyncClient", lambda timeout: _FakeClient())

    decision = await gate.classify(**{k: v for k, v in EML_GUEST_AIR_FRYER.items() if k != "expected"})

    assert decision.classification == InboundClassification.GUEST_MESSAGE
    assert decision.error is None
    sleep_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_retryable_http_status_surfaces_status_code_and_retryable(monkeypatch):
    gate = _make_gate()
    sleep_mock = AsyncMock()

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, *, headers=None, json=None):
            return httpx.Response(
                429,
                request=httpx.Request("POST", url),
                text="rate limited by provider",
            )

    monkeypatch.setattr("app.services.messaging_brain.inbound_message_gate.asyncio.sleep", sleep_mock)
    monkeypatch.setattr("app.services.messaging_brain.inbound_message_gate.httpx.AsyncClient", lambda timeout: _FakeClient())

    decision = await gate.classify(**{k: v for k, v in EML_GUEST_AIR_FRYER.items() if k != "expected"})

    assert decision.classification == InboundClassification.UNCLEAR
    assert decision.retryable is True
    assert decision.status_code == 429
    assert "status=429" in (decision.reasoning or "")
    assert "retryable=true" in (decision.reasoning or "")
    assert sleep_mock.await_count == 2


@pytest.mark.asyncio
async def test_invalid_classification_returns_unclear(monkeypatch):
    gate = _make_gate()
    monkeypatch.setattr(
        gate,
        "_call_anthropic",
        AsyncMock(
            return_value=(
                json.dumps(
                    {
                        "classification": "made_up_category",
                        "confidence": 0.99,
                        "reasoning": "bad",
                        "extracted": None,
                    }
                ),
                100,
                50,
            )
        ),
    )
    decision = await gate.classify(**{k: v for k, v in EML_GUEST_AIR_FRYER.items() if k != "expected"})
    assert decision.classification == InboundClassification.UNCLEAR


@pytest.mark.asyncio
async def test_response_with_json_fences_still_parses(monkeypatch):
    gate = _make_gate()
    payload = {
        "classification": "guest_message",
        "confidence": 0.9,
        "reasoning": "test",
        "extracted": None,
    }
    monkeypatch.setattr(
        gate,
        "_call_anthropic",
        AsyncMock(return_value=(f"```json\n{json.dumps(payload)}\n```", 100, 50)),
    )
    decision = await gate.classify(**{k: v for k, v in EML_GUEST_AIR_FRYER.items() if k != "expected"})
    assert decision.classification == InboundClassification.GUEST_MESSAGE
    assert decision.confidence == 0.9


@pytest.mark.skipif(
    os.environ.get("RUN_LIVE_GATE_TESTS") != "1",
    reason="set RUN_LIVE_GATE_TESTS=1 to run live tests against Anthropic API",
)
@pytest.mark.parametrize("eml", ALL_KNOWN_EMAILS, ids=lambda e: e["expected"].value + "_" + e["subject"][:30])
@pytest.mark.asyncio
async def test_live_classification_matches_expected(eml):
    gate = InboundMessageGate()
    inputs = {k: v for k, v in eml.items() if k != "expected"}
    decision = await gate.classify(**inputs)
    assert decision.classification == eml["expected"], (
        f"Expected {eml['expected']}, got {decision.classification} "
        f"with confidence {decision.confidence}: {decision.reasoning}"
    )
    assert decision.confidence >= 0.7
