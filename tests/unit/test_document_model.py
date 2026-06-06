from __future__ import annotations

import asyncio
from uuid import uuid4

from db.models.documents import DocumentModel


class FakeR2Client:
    def __init__(self) -> None:
        self.upload_calls = []

    async def get_presigned_url(self, tenant_id, document_id, filename, *, expires_in, version=None):
        return f"url://{tenant_id}/{document_id}/{version or 'original'}/{filename}?exp={expires_in}"

    async def get_file(self, tenant_id, document_id, filename, *, version=None):
        return f"{tenant_id}:{document_id}:{version or 'original'}:{filename}".encode()

    async def upload_file(self, tenant_id, document_id, filename, content, *, version=None, content_type=None):
        self.upload_calls.append((tenant_id, document_id, filename, content, version, content_type))
        if version is None:
            key = f"{tenant_id}/{document_id}/original/{filename}"
        else:
            key = f"{tenant_id}/{document_id}/versions/{version}/{filename}"
        return type("Stored", (), {"key": key, "bucket": "bucket", "version": version or 1})()


class FakeSession:
    def __init__(self, current_max=1) -> None:
        self.current_max = current_max
        self.added = []
        self.flushed = False

    async def scalar(self, _query):
        return self.current_max

    def add(self, row):
        self.added.append(row)

    async def flush(self):
        self.flushed = True


def test_get_storage_url_and_content(monkeypatch):
    fake_client = FakeR2Client()
    monkeypatch.setattr("db.models.documents.get_r2_client", lambda: fake_client)
    doc = DocumentModel(
        tenant_id=uuid4(),
        property_id=uuid4(),
        document_group_id=uuid4(),
        scope_type="property",
        version_number=1,
        document_type="house_manual",
        filename="manual.pdf",
        file_path="ignored",
        storage_backend="r2",
    )

    url = asyncio.run(doc.get_storage_url(expires_in=120))
    content = asyncio.run(doc.get_content())

    assert "original/manual.pdf" in url
    assert content.endswith(b":original:manual.pdf")


def test_create_version_writes_new_row(monkeypatch):
    fake_client = FakeR2Client()
    monkeypatch.setattr("db.models.documents.get_r2_client", lambda: fake_client)
    doc = DocumentModel(
        tenant_id=uuid4(),
        property_id=uuid4(),
        document_group_id=uuid4(),
        scope_type="property",
        version_number=1,
        document_type="house_manual",
        filename="manual.pdf",
        file_path="tenant/doc/original/manual.pdf",
        storage_backend="r2",
        upload_method="operator_upload",
        mime_type="application/pdf",
    )
    session = FakeSession(current_max=1)

    created = asyncio.run(
        doc.create_version(
            session,
            b"new version",
            mime_type="application/pdf",
            uploaded_by="tester",
            content_hash="abc123",
        )
    )

    assert session.flushed is True
    assert session.added == [created]
    assert created.document_group_id == doc.document_group_id
    assert created.version_number == 2
    assert created.file_path.endswith("/versions/2/manual.pdf")
    assert created.content_hash == "abc123"
    assert fake_client.upload_calls[0][4] == 2
