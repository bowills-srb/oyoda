from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.ops_auth import require_ops_access
from app.api.v1.endpoints import operator_properties
from app.services.concierge.guidebook_ingest_service import GuidebookFetchStop, GuidebookIngestResult


class _FakeMappingsResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class _FakeDeleteResult:
    def __init__(self, count: int):
        self._count = count

    def fetchall(self):
        return [(f"doc-{idx}",) for idx in range(self._count)]


@dataclass
class _CurrentProperty:
    address_street: str
    property_guide_url: str | None
    is_active: bool


class _FakeSession:
    def __init__(self, current=None, embedding_delete_counts=None):
        self.current: dict[str, _CurrentProperty] = current or {}
        self.embedding_delete_counts = embedding_delete_counts or {}
        self.executed: list[tuple[str, dict[str, Any]]] = []
        self.commit_calls = 0
        self.call_order: list[str] = []

    async def execute(self, statement, params=None):
        sql = str(statement)
        payload = params or {}
        self.executed.append((sql, payload))

        if "SELECT property_code, address_street, property_guide_url, is_active" in sql:
            rows = [
                {
                    "property_code": code,
                    "address_street": prop.address_street,
                    "property_guide_url": prop.property_guide_url,
                    "is_active": prop.is_active,
                }
                for code, prop in self.current.items()
            ]
            return _FakeMappingsResult(rows)

        if "INSERT INTO properties" in sql:
            code = payload["property_code"]
            self.current[code] = _CurrentProperty(
                address_street=payload["address_street"],
                property_guide_url=payload["property_guide_url"],
                is_active=True,
            )
            self.call_order.append(f"insert:{code}")
            return _FakeMappingsResult([])

        if "UPDATE properties" in sql:
            code = payload["property_code"]
            current = self.current.setdefault(
                code,
                _CurrentProperty(address_street=payload.get("address_street", ""), property_guide_url=None, is_active=False),
            )
            if "address_street" in payload:
                current.address_street = payload["address_street"]
                current.property_guide_url = payload["property_guide_url"]
                current.is_active = True
            else:
                current.is_active = False
            self.call_order.append(f"update:{code}")
            return _FakeMappingsResult([])

        if "DELETE FROM knowledge_embeddings" in sql:
            code = payload["property_code"]
            deleted = self.embedding_delete_counts.get(code, 0)
            self.call_order.append(f"delete_embeddings:{code}")
            return _FakeDeleteResult(deleted)

        raise AssertionError(f"Unexpected SQL: {sql}")

    async def commit(self):
        self.commit_calls += 1
        self.call_order.append("commit")


class _FakeIngestService:
    def __init__(self, outcomes=None):
        self.outcomes = outcomes or {}
        self.calls: list[str] = []
        self.call_order: list[str] = []

    async def ingest_property_guidebook(self, *, tenant_id, property_code, property_address, guidebook_url):
        self.calls.append(property_code)
        self.call_order.append(f"ingest:{property_code}")
        outcome = self.outcomes.get(property_code)
        if isinstance(outcome, Exception):
            raise outcome
        if outcome is None:
            return GuidebookIngestResult(
                property_code=property_code,
                fetched=True,
                deleted=0,
                inserted=10,
                updated=0,
                chunk_count=10,
                source_url=guidebook_url,
            )
        return outcome


def _build_app(monkeypatch, fake_session, ingest_service, tenant_id: UUID | None):
    app = FastAPI()
    app.include_router(operator_properties.router)

    async def _session_dep():
        return fake_session

    async def _ingest_dep(_session):
        return ingest_service

    app.dependency_overrides[require_ops_access] = lambda: None
    app.dependency_overrides[operator_properties.get_async_session] = _session_dep
    monkeypatch.setattr(operator_properties, "get_guidebook_ingest_service", _ingest_dep)
    monkeypatch.setattr(operator_properties, "resolve_request_tenant_id", lambda _request: tenant_id)
    return app


def test_reconcile_returns_401_without_tenant(monkeypatch):
    app = _build_app(monkeypatch, _FakeSession(), _FakeIngestService(), None)
    client = TestClient(app)

    response = client.post(
        "/operator/properties/reconcile",
        json={"properties": [{"property_code": "A", "address": "123 Main", "guidebook_url": "https://guide.breezeway.io/a"}]},
    )

    assert response.status_code == 401


def test_reconcile_returns_422_for_duplicate_property_codes(monkeypatch):
    tenant_id = UUID("e07980b2-a990-4b24-91d1-c8cb71ab70e1")
    app = _build_app(monkeypatch, _FakeSession(), _FakeIngestService(), tenant_id)
    client = TestClient(app)

    response = client.post(
        "/operator/properties/reconcile",
        json={
            "properties": [
                {"property_code": "X", "address": "123 Main", "guidebook_url": "https://guide.breezeway.io/x"},
                {"property_code": "X", "address": "456 Main", "guidebook_url": "https://guide.breezeway.io/y"},
            ]
        },
    )

    assert response.status_code == 422
    assert "X" in response.json()["detail"]


def test_reconcile_pure_insert_path(monkeypatch):
    tenant_id = UUID("e07980b2-a990-4b24-91d1-c8cb71ab70e1")
    session = _FakeSession()
    ingest_service = _FakeIngestService(
        outcomes={
            "A": GuidebookIngestResult("A", True, 0, 10, 0, 10, "https://guide.breezeway.io/a"),
            "B": GuidebookIngestResult("B", True, 0, 10, 0, 10, "https://guide.breezeway.io/b"),
        }
    )
    app = _build_app(monkeypatch, session, ingest_service, tenant_id)
    client = TestClient(app)

    response = client.post(
        "/operator/properties/reconcile",
        json={
            "properties": [
                {"property_code": "A", "address": "123 Main", "guidebook_url": "https://guide.breezeway.io/a"},
                {"property_code": "B", "address": "456 Main", "guidebook_url": "https://guide.breezeway.io/b"},
            ]
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["properties_active"] == 2
    assert payload["properties_deactivated"] == 0
    assert payload["embeddings_deleted_for_deactivated"] == 0
    assert [item["action"] for item in payload["outcomes"]] == ["inserted", "inserted"]
    assert [item["guidebook_status"] for item in payload["outcomes"]] == ["ingested", "ingested"]
    assert all(item["chunks_inserted"] == 10 for item in payload["outcomes"])
    assert sum(1 for sql, _ in session.executed if "INSERT INTO properties" in sql) == 2
    assert "commit" in session.call_order
    assert session.call_order.index("commit") < ingest_service.call_order.index("ingest:A")


def test_reconcile_idempotent_rerun_reports_unchanged(monkeypatch):
    tenant_id = UUID("e07980b2-a990-4b24-91d1-c8cb71ab70e1")
    session = _FakeSession(
        current={
            "A": _CurrentProperty("123 Main", "https://guide.breezeway.io/a", True),
            "B": _CurrentProperty("456 Main", "https://guide.breezeway.io/b", True),
        }
    )
    ingest_service = _FakeIngestService(
        outcomes={
            "A": GuidebookIngestResult("A", True, 10, 0, 10, 10, "https://guide.breezeway.io/a"),
            "B": GuidebookIngestResult("B", True, 10, 0, 10, 10, "https://guide.breezeway.io/b"),
        }
    )
    app = _build_app(monkeypatch, session, ingest_service, tenant_id)
    client = TestClient(app)

    response = client.post(
        "/operator/properties/reconcile",
        json={
            "properties": [
                {"property_code": "A", "address": "123 Main", "guidebook_url": "https://guide.breezeway.io/a"},
                {"property_code": "B", "address": "456 Main", "guidebook_url": "https://guide.breezeway.io/b"},
            ]
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert [item["action"] for item in payload["outcomes"]] == ["unchanged", "unchanged"]
    assert [item["chunks_inserted"] for item in payload["outcomes"]] == [0, 0]
    assert [item["chunks_updated"] for item in payload["outcomes"]] == [10, 10]
    assert [item["chunks_deleted"] for item in payload["outcomes"]] == [10, 10]
    assert payload["properties_deactivated"] == 0
    assert sum(1 for sql, _ in session.executed if "UPDATE properties" in sql and "address_street" in sql) == 2


def test_reconcile_deactivation_deletes_embeddings(monkeypatch):
    tenant_id = UUID("e07980b2-a990-4b24-91d1-c8cb71ab70e1")
    session = _FakeSession(
        current={
            "A": _CurrentProperty("123 Main", "https://guide.breezeway.io/a", True),
            "B": _CurrentProperty("456 Main", "https://guide.breezeway.io/b", True),
            "C": _CurrentProperty("789 Main", "https://guide.breezeway.io/c", True),
        },
        embedding_delete_counts={"C": 47},
    )
    ingest_service = _FakeIngestService()
    app = _build_app(monkeypatch, session, ingest_service, tenant_id)
    client = TestClient(app)

    response = client.post(
        "/operator/properties/reconcile",
        json={
            "properties": [
                {"property_code": "A", "address": "123 Main", "guidebook_url": "https://guide.breezeway.io/a"},
                {"property_code": "B", "address": "456 Main", "guidebook_url": "https://guide.breezeway.io/b"},
            ]
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["properties_deactivated"] == 1
    assert payload["embeddings_deleted_for_deactivated"] == 47
    outcome_c = next(item for item in payload["outcomes"] if item["property_code"] == "C")
    assert outcome_c["action"] == "deactivated"
    assert outcome_c["guidebook_status"] == "skipped_deactivated"
    assert outcome_c["chunks_deleted"] == 47
    assert "C" not in ingest_service.calls


def test_reconcile_guidebook_failures_do_not_break_other_properties(monkeypatch):
    tenant_id = UUID("e07980b2-a990-4b24-91d1-c8cb71ab70e1")
    session = _FakeSession()
    ingest_service = _FakeIngestService(
        outcomes={
            "A": GuidebookIngestResult("A", True, 0, 10, 0, 10, "https://guide.breezeway.io/a"),
            "B": GuidebookFetchStop("B: guide_not_configured"),
        }
    )
    app = _build_app(monkeypatch, session, ingest_service, tenant_id)
    client = TestClient(app)

    response = client.post(
        "/operator/properties/reconcile",
        json={
            "properties": [
                {"property_code": "A", "address": "123 Main", "guidebook_url": "https://guide.breezeway.io/a"},
                {"property_code": "B", "address": "456 Main", "guidebook_url": "https://guide.breezeway.io/b"},
            ]
        },
    )

    assert response.status_code == 200
    payload = response.json()
    outcome_a = next(item for item in payload["outcomes"] if item["property_code"] == "A")
    outcome_b = next(item for item in payload["outcomes"] if item["property_code"] == "B")
    assert outcome_a["guidebook_status"] == "ingested"
    assert outcome_b["guidebook_status"] == "skipped_not_configured"
    assert outcome_b["error"] is None
    assert session.call_order.index("commit") < ingest_service.call_order.index("ingest:A")


def test_reconcile_skips_properties_without_guidebook_url(monkeypatch):
    tenant_id = UUID("e07980b2-a990-4b24-91d1-c8cb71ab70e1")
    session = _FakeSession()
    ingest_service = _FakeIngestService()
    app = _build_app(monkeypatch, session, ingest_service, tenant_id)
    client = TestClient(app)

    response = client.post(
        "/operator/properties/reconcile",
        json={"properties": [{"property_code": "A", "address": "123 Main", "guidebook_url": None}]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["outcomes"][0]["guidebook_status"] == "skipped_no_url"
    assert ingest_service.calls == []
