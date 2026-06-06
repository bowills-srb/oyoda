from __future__ import annotations

import base64
import json

import pytest

from app.services.integrations.gmail_push import (
    decode_gmail_push_pubsub_payload,
    should_trigger_push_sync,
)


def _payload(*, email: str, history_id: str) -> dict:
    inner = json.dumps({"emailAddress": email, "historyId": history_id}).encode("utf-8")
    encoded = base64.urlsafe_b64encode(inner).decode("utf-8").rstrip("=")
    return {
        "message": {
            "data": encoded,
            "messageId": "123",
            "publishTime": "2026-05-28T00:00:00Z",
        },
        "subscription": "projects/demo/subscriptions/gmail-push",
    }


def test_decode_gmail_push_pubsub_payload_extracts_email_and_history_id() -> None:
    notification = decode_gmail_push_pubsub_payload(
        _payload(email="Info@BeachHabitats30A.com", history_id="987654321")
    )

    assert notification.watched_email == "info@beachhabitats30a.com"
    assert notification.history_id == "987654321"
    assert notification.message_id == "123"


def test_decode_gmail_push_pubsub_payload_rejects_missing_data() -> None:
    with pytest.raises(ValueError, match="Missing Pub/Sub message data"):
        decode_gmail_push_pubsub_payload({"message": {}})


def test_should_trigger_push_sync_only_for_newer_history_ids() -> None:
    assert should_trigger_push_sync(incoming_history_id="11", last_known_history_id="10") is True
    assert should_trigger_push_sync(incoming_history_id="10", last_known_history_id="10") is False
    assert should_trigger_push_sync(incoming_history_id="9", last_known_history_id="10") is False
    assert should_trigger_push_sync(incoming_history_id="11", last_known_history_id="") is True
