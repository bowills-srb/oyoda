from __future__ import annotations

import pytest

from app.services.integrations.gmail_inbox_poller import GmailReplySender


class _FakeTokenManager:
    async def get_access_token(self) -> str:
        return "token"

    def auth_header(self, token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}


class _FakeResponse:
    def __init__(self, *, status_code: int = 200, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")

    def json(self) -> dict:
        return self._payload


class _FakeAsyncClient:
    def __init__(self, scripted, calls):
        self._scripted = scripted
        self._calls = calls

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, **kwargs):
        self._calls.append(("GET", url, kwargs))
        return self._scripted.pop(0)

    async def post(self, url, **kwargs):
        self._calls.append(("POST", url, kwargs))
        return self._scripted.pop(0)


def _patch_client(monkeypatch, scripted, calls):
    monkeypatch.setattr(
        "app.services.integrations.gmail_inbox_poller.httpx.AsyncClient",
        lambda *args, **kwargs: _FakeAsyncClient(scripted, calls),
    )


@pytest.mark.asyncio
async def test_gmail_reply_sender_applies_thread_label(monkeypatch):
    calls: list[tuple[str, str, dict]] = []
    scripted = [
        _FakeResponse(payload={"id": "sent"}),
        _FakeResponse(),
        _FakeResponse(payload={"labels": [{"id": "LBL1", "name": "Oyvoda/Sent"}]}),
        _FakeResponse(),
    ]
    _patch_client(monkeypatch, scripted, calls)

    sender = GmailReplySender(_FakeTokenManager(), sent_label="Oyvoda/Sent")
    sent = await sender.reply(
        thread_id="thread-123",
        in_reply_to="<msg@example.com>",
        to_address="guest@example.com",
        to_name="Guest",
        subject="Re: Hello",
        body="Body",
        operator_name="Host",
    )

    assert sent is True
    assert any(call[1].endswith("/users/me/messages/send") for call in calls)
    assert any(call[1].endswith("/users/me/threads/thread-123/modify") and call[2].get("json") == {"removeLabelIds": ["UNREAD"]} for call in calls)
    assert any(call[1].endswith("/users/me/threads/thread-123/modify") and call[2].get("json") == {"addLabelIds": ["LBL1"]} for call in calls)


@pytest.mark.asyncio
async def test_gmail_reply_sender_creates_label_on_first_use(monkeypatch):
    calls: list[tuple[str, str, dict]] = []
    scripted = [
        _FakeResponse(payload={"id": "sent"}),
        _FakeResponse(),
        _FakeResponse(payload={"labels": []}),
        _FakeResponse(payload={"id": "NEWLBL"}),
        _FakeResponse(),
    ]
    _patch_client(monkeypatch, scripted, calls)

    sender = GmailReplySender(_FakeTokenManager(), sent_label="Oyvoda/Sent")
    sent = await sender.reply(
        thread_id="thread-123",
        in_reply_to="<msg@example.com>",
        to_address="guest@example.com",
        to_name="Guest",
        subject="Re: Hello",
        body="Body",
        operator_name="Host",
    )

    assert sent is True
    assert any(call[1].endswith("/users/me/labels") and call[0] == "POST" for call in calls)
    assert any(call[1].endswith("/users/me/threads/thread-123/modify") and call[2].get("json") == {"addLabelIds": ["NEWLBL"]} for call in calls)


@pytest.mark.asyncio
async def test_gmail_reply_sender_label_failure_does_not_break_send(monkeypatch):
    calls: list[tuple[str, str, dict]] = []
    scripted = [
        _FakeResponse(payload={"id": "sent"}),
        _FakeResponse(),
        _FakeResponse(status_code=500),
    ]
    _patch_client(monkeypatch, scripted, calls)

    sender = GmailReplySender(_FakeTokenManager(), sent_label="Oyvoda/Sent")
    sent = await sender.reply(
        thread_id="thread-123",
        in_reply_to="<msg@example.com>",
        to_address="guest@example.com",
        to_name="Guest",
        subject="Re: Hello",
        body="Body",
        operator_name="Host",
    )

    assert sent is True
    assert any(call[1].endswith("/users/me/messages/send") for call in calls)


@pytest.mark.asyncio
async def test_gmail_reply_sender_reuses_cached_label_id(monkeypatch):
    calls: list[tuple[str, str, dict]] = []
    scripted = [
        _FakeResponse(payload={"id": "sent-1"}),
        _FakeResponse(),
        _FakeResponse(payload={"labels": [{"id": "LBL1", "name": "Oyvoda/Sent"}]}),
        _FakeResponse(),
        _FakeResponse(payload={"id": "sent-2"}),
        _FakeResponse(),
        _FakeResponse(),
    ]
    _patch_client(monkeypatch, scripted, calls)

    sender = GmailReplySender(_FakeTokenManager(), sent_label="Oyvoda/Sent")

    first = await sender.reply(
        thread_id="thread-123",
        in_reply_to="<msg1@example.com>",
        to_address="guest@example.com",
        to_name="Guest",
        subject="Re: Hello",
        body="Body 1",
        operator_name="Host",
    )
    second = await sender.reply(
        thread_id="thread-123",
        in_reply_to="<msg2@example.com>",
        to_address="guest@example.com",
        to_name="Guest",
        subject="Re: Hello again",
        body="Body 2",
        operator_name="Host",
    )

    assert first is True
    assert second is True
    label_list_calls = [call for call in calls if call[1].endswith("/users/me/labels") and call[0] == "GET"]
    assert len(label_list_calls) == 1
