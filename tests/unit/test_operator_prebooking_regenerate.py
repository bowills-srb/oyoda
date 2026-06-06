from __future__ import annotations

import asyncio
import json

from starlette.requests import Request

from app.api.v1.endpoints import operator_prebooking


class _FakeSession:
    async def execute(self, statement, params=None):  # pragma: no cover - endpoint should not hit DB directly here
        raise AssertionError("regenerate_inquiry should not query the DB directly in this test")


def _fake_request() -> Request:
    return Request({"type": "http", "headers": [], "method": "POST", "path": "/"})


def test_regenerate_delegates_to_shared_retry_service(monkeypatch):
    monkeypatch.setattr(
        operator_prebooking,
        "_require_user",
        lambda request: {
            "scoped_op": "11111111-1111-1111-1111-111111111111",
            "tid": "22222222-2222-2222-2222-222222222222",
        },
    )

    async def _fake_retry(**kwargs):
        assert kwargs["tenant_id"] == "22222222-2222-2222-2222-222222222222"
        assert kwargs["operator_id"] == "11111111-1111-1111-1111-111111111111"
        assert kwargs["draft_id"] == "INQ-1234"
        assert kwargs["auto_send_if_allowed"] is False
        return {
            "ok": True,
            "draft_id": "INQ-1234",
            "draft_text": "Need to confirm pool heat.",
            "intent": "pool_heat",
            "confidence": 0.91,
            "draft_source": "messaging_brain",
            "blocked_by_gap_topics": ["pool_heat"],
            "sent": False,
            "status": "pending_review",
        }

    monkeypatch.setattr(
        "app.services.messaging_brain.pre_booking_retry.reevaluate_existing_prebooking_inquiry",
        _fake_retry,
    )

    async def _fake_load(*args, **kwargs):
        return {
            "draft_id": "INQ-1234",
            "status": "pending_review",
        }

    async def _fake_publish(*args, **kwargs):
        return None

    monkeypatch.setattr(
        operator_prebooking,
        "_load_inquiry_state",
        _fake_load,
    )
    monkeypatch.setattr(
        operator_prebooking,
        "_publish_inquiry_event",
        _fake_publish,
    )

    response = asyncio.run(
        operator_prebooking.regenerate_inquiry(
            "INQ-1234",
            _fake_request(),
            db=_FakeSession(),
        )
    )

    payload = json.loads(response.body)
    assert response.status_code == 200
    assert payload["draft_id"] == "INQ-1234"
    assert payload["draft_text"] == "Need to confirm pool heat."
    assert payload["blocked_by_gap_topics"] == ["pool_heat"]
    assert payload["status"] == "pending_review"


def test_regenerate_surfaces_retry_service_errors(monkeypatch):
    monkeypatch.setattr(
        operator_prebooking,
        "_require_user",
        lambda request: {
            "scoped_op": "11111111-1111-1111-1111-111111111111",
            "tid": "22222222-2222-2222-2222-222222222222",
        },
    )

    async def _fake_retry(**kwargs):
        return {"ok": False, "error": "Draft not found"}

    monkeypatch.setattr(
        "app.services.messaging_brain.pre_booking_retry.reevaluate_existing_prebooking_inquiry",
        _fake_retry,
    )

    async def _fake_load(*args, **kwargs):
        return {
            "draft_id": "INQ-404",
            "status": "pending_review",
        }

    async def _fake_publish(*args, **kwargs):
        return None

    monkeypatch.setattr(
        operator_prebooking,
        "_load_inquiry_state",
        _fake_load,
    )
    monkeypatch.setattr(
        operator_prebooking,
        "_publish_inquiry_event",
        _fake_publish,
    )

    response = asyncio.run(
        operator_prebooking.regenerate_inquiry(
            "INQ-404",
            _fake_request(),
            db=_FakeSession(),
        )
    )

    payload = json.loads(response.body)
    assert response.status_code == 404
    assert payload["error"] == "Draft not found"
