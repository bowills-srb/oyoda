from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

import httpx
import pytest

from app.services.concierge.guidebook_ingest_service import (
    GuideFetchResponse,
    GuidebookFetchStop,
    GuidebookIngestService,
    extract_guide_token,
)


class _ExecuteResult:
    def __init__(self, *, rowcount: int = 0):
        self.rowcount = rowcount


class _FetchOneResult:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _FakeSession:
    def __init__(self, *, delete_rowcount: int = 0, property_id: UUID | None = None):
        self.delete_rowcount = delete_rowcount
        self.property_id = property_id
        self.executed: list[tuple[str, dict[str, Any]]] = []
        self.commit_count = 0
        self.call_order: list[str] = []

    async def execute(self, statement, params=None):
        sql = str(statement)
        payload = params or {}
        self.executed.append((sql, payload))
        if "SELECT id" in sql and "FROM properties" in sql:
            return _FetchOneResult((str(self.property_id),) if self.property_id else None)
        if "DELETE FROM knowledge_embeddings" in sql:
            self.call_order.append("delete")
            return _ExecuteResult(rowcount=self.delete_rowcount)
        raise AssertionError(f"Unexpected SQL: {sql}")

    async def commit(self):
        self.commit_count += 1
        self.call_order.append("commit")


class _FakeVectorStore:
    def __init__(self, session: _FakeSession, result: dict[str, int]):
        self.session = session
        self.result = result
        self.calls: list[tuple[list[Any], int]] = []

    async def add_documents(self, documents, batch_size=100):
        self.calls.append((documents, batch_size))
        self.session.call_order.append("add_documents")
        return dict(self.result)


def _good_payload() -> dict[str, Any]:
    return {
        "pages": [
            {
                "title": "Welcome",
                "sections": [
                    {
                        "title": "House Rules",
                        "blocks": [
                            {
                                "title": "Quiet Hours",
                                "data": (
                                    "<p>Quiet hours begin at 10 PM and end at 8 AM. "
                                    "Please respect neighbors, keep music low, and "
                                    "use outdoor spaces responsibly after sunset.</p>"
                                ),
                            }
                        ],
                    }
                ],
            }
        ]
    }


async def _fetch_response(*args, **kwargs):
    return GuideFetchResponse(
        status=200,
        final_url="https://api.breezeway.io/public/guides/test",
        content_type="application/json",
        body=(
            b'{"pages":[{"title":"Welcome","sections":[{"title":"House Rules","blocks":'
            b'[{"title":"Quiet Hours","data":"<p>Quiet hours begin at 10 PM and end at 8 AM. '
            b'Please respect neighbors, keep music low, and use outdoor spaces responsibly after sunset.</p>"}]}]}]}'
        ),
    )


def test_extract_guide_token_valid():
    assert extract_guide_token("https://guide.breezeway.io/abc123") == "abc123"


def test_extract_guide_token_rejects_malformed():
    with pytest.raises(ValueError, match="Unsupported guidebook URL"):
        extract_guide_token("https://other.host/abc123")
    with pytest.raises(ValueError, match="Unsupported guidebook URL"):
        extract_guide_token("")


def test_ingest_property_guidebook_happy_path(monkeypatch):
    session = _FakeSession(delete_rowcount=3)
    store = _FakeVectorStore(session, {"inserted": 5, "updated": 0})
    service = GuidebookIngestService(session)
    service.vector_store = store

    monkeypatch.setattr(
        "app.services.concierge.guidebook_ingest_service.fetch_guide_payload",
        _fetch_response,
    )

    result = asyncio.run(
        service.ingest_property_guidebook(
            tenant_id=UUID("e07980b2-a990-4b24-91d1-c8cb71ab70e1"),
            property_code="TEST",
            property_address="123 Main",
            guidebook_url="https://guide.breezeway.io/test",
        )
    )

    assert result.inserted == 5
    assert result.updated == 0
    assert result.chunk_count > 0
    assert len(store.calls) == 1
    documents, batch_size = store.calls[0]
    assert batch_size == len(documents)
    assert session.call_order == ["delete", "add_documents"]


def test_ingest_property_guidebook_empty_payload_commits_delete(monkeypatch):
    session = _FakeSession(delete_rowcount=4)
    store = _FakeVectorStore(session, {"inserted": 0, "updated": 0})
    service = GuidebookIngestService(session)
    service.vector_store = store

    async def _empty_fetch(*args, **kwargs):
        return GuideFetchResponse(
            status=200,
            final_url="https://api.breezeway.io/public/guides/test",
            content_type="application/json",
            body=b'{"pages":[]}',
        )

    monkeypatch.setattr(
        "app.services.concierge.guidebook_ingest_service.fetch_guide_payload",
        _empty_fetch,
    )

    result = asyncio.run(
        service.ingest_property_guidebook(
            tenant_id=UUID("e07980b2-a990-4b24-91d1-c8cb71ab70e1"),
            property_code="TEST",
            property_address="123 Main",
            guidebook_url="https://guide.breezeway.io/test",
        )
    )

    assert result.chunk_count == 0
    assert result.inserted == 0
    assert result.updated == 0
    assert store.calls == []
    assert session.commit_count == 1
    assert session.call_order == ["delete", "commit"]


def test_ingest_property_guidebook_wraps_httpx_errors(monkeypatch):
    session = _FakeSession()
    service = GuidebookIngestService(session)

    async def _boom(*args, **kwargs):
        raise httpx.ConnectError("simulated")

    monkeypatch.setattr(
        "app.services.concierge.guidebook_ingest_service.fetch_guide_payload",
        _boom,
    )

    with pytest.raises(GuidebookFetchStop, match="TEST: ConnectError: simulated"):
        asyncio.run(
            service.ingest_property_guidebook(
                tenant_id=UUID("e07980b2-a990-4b24-91d1-c8cb71ab70e1"),
                property_code="TEST",
                property_address="123 Main",
                guidebook_url="https://guide.breezeway.io/test",
            )
        )


@pytest.mark.parametrize("status_code", [401, 403, 429])
def test_ingest_property_guidebook_stop_statuses_raise(monkeypatch, status_code):
    session = _FakeSession()
    service = GuidebookIngestService(session)

    async def _stop_fetch(*args, **kwargs):
        return GuideFetchResponse(
            status=status_code,
            final_url="https://api.breezeway.io/public/guides/test",
            content_type="application/json",
            body=b'{"error":"nope"}',
        )

    monkeypatch.setattr(
        "app.services.concierge.guidebook_ingest_service.fetch_guide_payload",
        _stop_fetch,
    )

    with pytest.raises(GuidebookFetchStop, match=f"HTTP {status_code}"):
        asyncio.run(
            service.ingest_property_guidebook(
                tenant_id=UUID("e07980b2-a990-4b24-91d1-c8cb71ab70e1"),
                property_code="TEST",
                property_address="123 Main",
                guidebook_url="https://guide.breezeway.io/test",
            )
        )


def test_ingest_property_guidebook_guide_not_configured_raises(monkeypatch):
    session = _FakeSession()
    service = GuidebookIngestService(session)

    async def _skip_fetch(*args, **kwargs):
        return GuideFetchResponse(
            status=422,
            final_url="https://api.breezeway.io/public/guides/test",
            content_type="application/json",
            body=(
                b'{"description":"Home Guide is not available",'
                b'"error":"Bad request","status_code":422}'
            ),
        )

    monkeypatch.setattr(
        "app.services.concierge.guidebook_ingest_service.fetch_guide_payload",
        _skip_fetch,
    )

    with pytest.raises(GuidebookFetchStop, match="guide_not_configured"):
        asyncio.run(
            service.ingest_property_guidebook(
                tenant_id=UUID("e07980b2-a990-4b24-91d1-c8cb71ab70e1"),
                property_code="TEST",
                property_address="123 Main",
                guidebook_url="https://guide.breezeway.io/test",
            )
        )
