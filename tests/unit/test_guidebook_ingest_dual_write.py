from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

import pytest

from app.services.concierge.guidebook_ingest_service import (
    GuideFetchResponse,
    GuidebookChunk,
    GuidebookIngestService,
    build_scoped_projections,
    chunk_to_topic_id,
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
    def __init__(self, *, delete_rowcount: int = 0):
        self.delete_rowcount = delete_rowcount
        self.executed: list[tuple[str, dict[str, Any]]] = []
        self.commit_count = 0
        self.call_order: list[str] = []

    async def execute(self, statement, params=None):
        sql = str(statement)
        payload = params or {}
        self.executed.append((sql, payload))
        if "DELETE FROM knowledge_embeddings" in sql:
            self.call_order.append("delete")
            return _ExecuteResult(rowcount=self.delete_rowcount)
        if "SELECT id" in sql and "FROM properties" in sql:
            return _FetchOneResult(None)
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


async def _fetch_response(*args, **kwargs):
    return GuideFetchResponse(
        status=200,
        final_url="https://api.breezeway.io/public/guides/test",
        content_type="application/json",
        body=(
            b'{"pages":[{"title":"Welcome","sections":[{"title":"House Rules","blocks":'
            b'[{"title":"Quiet Hours","data":"<p>Quiet hours begin at 10 PM and end at 8 AM. '
            b'Please respect neighbors, keep music low, and use outdoor spaces responsibly after sunset.</p>"}]},'
            b'{"title":"Arrival","blocks":[{"title":"Check-In","data":"<p>Check in starts at 4 PM. '
            b'Use the keypad on the front door with your unique code when you arrive.</p>"}]}]}]}'
        ),
    )


def test_dual_write_writes_to_both_surfaces(monkeypatch):
    session = _FakeSession(delete_rowcount=2)
    store = _FakeVectorStore(session, {"inserted": 2, "updated": 0})
    service = GuidebookIngestService(session)
    service.vector_store = store

    writes: list[dict[str, Any]] = []

    async def _fake_resolve_property_id(*, tenant_id, property_code):
        return UUID("00000000-0000-0000-0000-000000000123")

    async def _fake_write(self, session, tenant_id, user_id, scope_type, scope_target_id, topic_id, question_text, answer_text, tags, source, metadata):
        writes.append(
            {
                "topic_id": topic_id,
                "question_text": question_text,
                "answer_text": answer_text,
                "tags": list(tags or []),
                "source": source,
                "metadata": dict(metadata or {}),
                "scope_type": scope_type,
                "scope_target_id": str(scope_target_id),
            }
        )

    monkeypatch.setattr(
        "app.services.concierge.guidebook_ingest_service.fetch_guide_payload",
        _fetch_response,
    )
    monkeypatch.setattr(service, "_resolve_property_id", _fake_resolve_property_id)
    monkeypatch.setattr(
        "app.services.messaging_brain.knowledge.scoped_knowledge_service.ScopedKnowledgeService.write_scoped_knowledge",
        _fake_write,
    )

    result = asyncio.run(
        service.ingest_property_guidebook(
            tenant_id=UUID("e07980b2-a990-4b24-91d1-c8cb71ab70e1"),
            property_code="TEST",
            property_address="123 Main",
            guidebook_url="https://guide.breezeway.io/test",
        )
    )

    assert len(store.calls) == 1
    assert result.scoped_knowledge_written == len(writes)
    assert result.scoped_knowledge_failed == 0
    assert result.scoped_knowledge_skipped_no_property is False
    assert all(item["source"] == "guidebook_ingest_v2" for item in writes)
    assert any(item["topic_id"] == "check_in_process" for item in writes)
    assert any(item["topic_id"] is None for item in writes)


def test_scoped_write_failure_does_not_block_vector_write(monkeypatch, caplog):
    session = _FakeSession(delete_rowcount=1)
    store = _FakeVectorStore(session, {"inserted": 2, "updated": 0})
    service = GuidebookIngestService(session)
    service.vector_store = store

    async def _fake_resolve_property_id(*, tenant_id, property_code):
        return UUID("00000000-0000-0000-0000-000000000123")

    calls = {"count": 0}

    async def _failing_write(self, session, tenant_id, user_id, scope_type, scope_target_id, topic_id, question_text, answer_text, tags, source, metadata):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("simulated scoped write failure")

    monkeypatch.setattr(
        "app.services.concierge.guidebook_ingest_service.fetch_guide_payload",
        _fetch_response,
    )
    monkeypatch.setattr(service, "_resolve_property_id", _fake_resolve_property_id)
    monkeypatch.setattr(
        "app.services.messaging_brain.knowledge.scoped_knowledge_service.ScopedKnowledgeService.write_scoped_knowledge",
        _failing_write,
    )

    with caplog.at_level("WARNING"):
        result = asyncio.run(
            service.ingest_property_guidebook(
                tenant_id=UUID("e07980b2-a990-4b24-91d1-c8cb71ab70e1"),
                property_code="TEST",
                property_address="123 Main",
                guidebook_url="https://guide.breezeway.io/test",
            )
        )

    assert len(store.calls) == 1
    assert result.scoped_knowledge_failed == 1
    assert result.scoped_knowledge_written >= 0
    assert "scoped_knowledge_write_failed" in caplog.text


def test_missing_property_id_skips_scoped_only(monkeypatch):
    session = _FakeSession(delete_rowcount=1)
    store = _FakeVectorStore(session, {"inserted": 2, "updated": 0})
    service = GuidebookIngestService(session)
    service.vector_store = store

    async def _missing_property_id(*, tenant_id, property_code):
        return None

    scoped_calls = {"count": 0}

    async def _unexpected_write(*args, **kwargs):
        scoped_calls["count"] += 1

    monkeypatch.setattr(
        "app.services.concierge.guidebook_ingest_service.fetch_guide_payload",
        _fetch_response,
    )
    monkeypatch.setattr(service, "_resolve_property_id", _missing_property_id)
    monkeypatch.setattr(
        "app.services.messaging_brain.knowledge.scoped_knowledge_service.ScopedKnowledgeService.write_scoped_knowledge",
        _unexpected_write,
    )

    result = asyncio.run(
        service.ingest_property_guidebook(
            tenant_id=UUID("e07980b2-a990-4b24-91d1-c8cb71ab70e1"),
            property_code="TEST",
            property_address="123 Main",
            guidebook_url="https://guide.breezeway.io/test",
        )
    )

    assert len(store.calls) == 1
    assert result.scoped_knowledge_skipped_no_property is True
    assert result.scoped_knowledge_written == 0
    assert result.scoped_knowledge_failed == 0
    assert scoped_calls["count"] == 0


@pytest.mark.parametrize(
    ("chunk", "expected_topic_id"),
    [
        (
            GuidebookChunk(
                property_code="A",
                property_address="123 Main",
                section_title="Pet Policy",
                content="Dogs are allowed with approval and a pet fee may apply.",
                doc_type="property_rules",
            ),
            "pet_fee",
        ),
        (
            GuidebookChunk(
                property_code="A",
                property_address="123 Main",
                section_title="Check-In",
                content="Check in starts at 4 PM and your door code arrives before arrival.",
                doc_type="property_info",
            ),
            "check_in_process",
        ),
        (
            GuidebookChunk(
                property_code="A",
                property_address="123 Main",
                section_title="Parking",
                content="Parking is limited to the driveway and garage spaces only.",
                doc_type="property_info",
            ),
            "parking",
        ),
    ],
)
def test_topic_mapping_known_topics(chunk, expected_topic_id):
    assert chunk_to_topic_id(chunk) == expected_topic_id


def test_topic_mapping_freeform_fallback():
    chunk = GuidebookChunk(
        property_code="A",
        property_address="123 Main",
        section_title="WiFi Access",
        content="The WiFi network and password are listed on the kitchen chalkboard.",
        doc_type="property_info",
    )

    assert chunk_to_topic_id(chunk) is None

    projections = build_scoped_projections(
        [chunk],
        guidebook_url="https://guide.breezeway.io/test",
        ingest_run_id="run-1",
    )
    assert len(projections) == 1
    assert projections[0].topic_id is None
    assert "wifi" in projections[0].question_text.lower()
