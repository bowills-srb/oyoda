from __future__ import annotations

import asyncio
from uuid import UUID

import numpy as np
import pytest

from app.services.knowledge.vector_store import Document, VectorStore


class _FakeEmbedder:
    def encode(self, texts):
        return np.zeros((len(texts), 384), dtype=np.float32)


class _FakeSession:
    async def execute(self, statement, params=None):
        raise AssertionError(f"execute should not be reached: {statement}")

    async def commit(self):
        raise AssertionError("commit should not be reached")


def test_require_tenant_id_raises_when_missing():
    with pytest.raises(ValueError, match="tenant_id"):
        VectorStore._require_tenant_id({})


def test_require_tenant_id_normalizes_uuid_to_string():
    uid = UUID("e07980b2-a990-4b24-91d1-c8cb71ab70e1")
    assert VectorStore._require_tenant_id({"tenant_id": uid}) == str(uid)
    assert VectorStore._require_tenant_id({"tenant_id": str(uid)}) == str(uid)


def test_add_documents_raises_when_document_metadata_missing_tenant_id(monkeypatch):
    monkeypatch.setattr(
        "app.services.knowledge.vector_store.EmbeddingModel.get_instance",
        lambda: _FakeEmbedder(),
    )
    store = VectorStore(_FakeSession())
    doc = Document(content="hello world", metadata={})

    with pytest.raises(ValueError, match="tenant_id"):
        asyncio.run(store.add_documents([doc]))
