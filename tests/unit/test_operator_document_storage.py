from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

from app.api.v1.endpoints.operator_app import _persist_source_document, _save_document_extraction
from db.models.documents import DocumentModel


class FakeStored:
    def __init__(self, key: str) -> None:
        self.key = key
        self.bucket = "bucket"
        self.version = 1


class FakeR2Client:
    def __init__(self) -> None:
        self.calls = []

    async def upload_file(self, tenant_id, document_id, filename, content, *, content_type=None, version=None):
        self.calls.append((tenant_id, document_id, filename, content, content_type, version))
        if version is None:
            return FakeStored(f"{tenant_id}/{document_id}/original/{filename}")
        return FakeStored(f"{tenant_id}/{document_id}/versions/{version}/{filename}")


class FakeResult:
    def __init__(self, row) -> None:
        self.row = row

    def scalar_one_or_none(self):
        return self.row


class FakeSession:
    def __init__(self, latest=None):
        self.latest = latest
        self.added = []
        self.deleted = []
        self.flushed = False

    async def scalar(self, _stmt):
        return self.latest

    def add(self, row):
        self.added.append(row)

    async def flush(self):
        self.flushed = True

    async def execute(self, stmt):
        self.deleted.append(stmt)
        return FakeResult(None)


def _field(name: str, value, confidence: str = "medium"):
    return SimpleNamespace(
        field_name=name,
        value=value,
        confidence=SimpleNamespace(value=confidence),
        source_document_type="house_manual",
        source_page=1,
        source_text="snippet",
        field_id=uuid4(),
        extracted_at=SimpleNamespace(isoformat=lambda: "2026-05-09T00:00:00"),
    )


def test_persist_source_document_creates_first_version(monkeypatch):
    fake_client = FakeR2Client()
    monkeypatch.setattr("app.api.v1.endpoints.operator_app.get_r2_client", lambda: fake_client)
    session = FakeSession()

    row, stored_new, reused = asyncio.run(
        _persist_source_document(
            session,
            tenant_id=str(uuid4()),
            property_id=None,
            scope="portfolio",
            document_type="portfolio_policy",
            filename="policy.pdf",
            content=b"policy-bytes",
            content_type="application/pdf",
            upload_method="operator_upload",
            uploaded_by="owner@example.com",
            content_hash="hash1",
        )
    )

    assert stored_new is True
    assert reused is False
    assert row.version_number == 1
    assert row.scope_type == "portfolio"
    assert row.file_path.endswith("/original/policy.pdf")
    assert session.flushed is True


def test_persist_source_document_reuses_identical_hash():
    latest = DocumentModel(
        tenant_id=uuid4(),
        property_id=None,
        document_group_id=uuid4(),
        scope_type="portfolio",
        version_number=1,
        document_type="portfolio_policy",
        filename="policy.pdf",
        file_path="existing",
        storage_backend="r2",
        content_hash="same-hash",
    )
    session = FakeSession(latest=latest)

    row, stored_new, reused = asyncio.run(
        _persist_source_document(
            session,
            tenant_id=str(latest.tenant_id),
            property_id=None,
            scope="portfolio",
            document_type="portfolio_policy",
            filename="policy.pdf",
            content=b"same",
            content_type="application/pdf",
            upload_method="operator_upload",
            uploaded_by="owner@example.com",
            content_hash="same-hash",
        )
    )

    assert row is latest
    assert stored_new is False
    assert reused is True


def test_save_document_extraction_updates_row_and_field_records():
    row = DocumentModel(
        tenant_id=uuid4(),
        property_id=uuid4(),
        document_group_id=uuid4(),
        scope_type="property",
        version_number=1,
        document_type="house_manual",
        filename="manual.pdf",
        file_path="existing",
        storage_backend="r2",
    )
    row.id = uuid4()
    session = FakeSession()
    extraction = SimpleNamespace(
        fields=[_field("wifi_password", "beach123", "high"), _field("lock_code", "2468", "medium")],
        errors=[],
    )

    asyncio.run(_save_document_extraction(session, document_row=row, extraction=extraction))

    assert row.extraction_status == "completed"
    assert len(row.extracted_fields) == 2
    assert len(session.added) == 2
