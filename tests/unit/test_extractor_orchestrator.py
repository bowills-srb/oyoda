from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from app.services.extraction import (
    CanonicalBlock,
    CanonicalBlockManifest,
    ExtractionCandidatePayload,
    ExtractorOrchestrator,
    LLMBatchExtractionResult,
    LLMExtractionResult,
    LLMUsage,
)
from db.models.documents import DocumentModel


TENANT_ID = UUID("11111111-1111-1111-1111-111111111111")
PROP_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
PROP_B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


@dataclass(frozen=True)
class _PromotionResult:
    candidate_id: UUID


@dataclass(frozen=True)
class _CreatedCandidate:
    candidate_id: UUID


class _FakeStagingService:
    def __init__(self) -> None:
        self.created: list[dict] = []

    async def create_candidate(self, session, **payload):
        candidate_id = uuid4()
        self.created.append({"candidate_id": candidate_id, **payload})
        return _CreatedCandidate(candidate_id=candidate_id)

    async def auto_promote_eligible(self, session, tenant_id, reviewed_by_user_id=None, candidate_ids=None):
        promoted = []
        created_by_id = {row["candidate_id"]: row for row in self.created}
        for candidate_id in candidate_ids or []:
            row = created_by_id[candidate_id]
            if row["extraction_method"] == "deterministic" and float(row["confidence"]) >= 0.95:
                promoted.append(_PromotionResult(candidate_id=candidate_id))
        return {"auto_promoted": len(promoted), "results": promoted}


class _FakeLLMExtractor:
    def __init__(self, *, fail_render_types: set[str] | None = None) -> None:
        self.calls: list[tuple[list[str], dict[str, CanonicalBlock], int]] = []
        self.fail_render_types = fail_render_types or set()

    async def extract_from_chunks_batch(self, chunks, canonical_blocks, concurrency=5):
        block = next(iter(canonical_blocks.values()))
        if block.render_type in self.fail_render_types:
            raise RuntimeError(f"forced failure for {block.render_type}")
        self.calls.append(([chunk.chunk_id for chunk in chunks], canonical_blocks, concurrency))
        results_by_chunk = {}
        detailed_results = {}
        for chunk in chunks:
            candidate = ExtractionCandidatePayload(
                scope_type=block.scope_type,
                scope_target_id=str(block.tenant_id if block.scope_type == "tenant" else block.canonical_source_property_id),
                source_type="guidebook",
                extraction_method="llm",
                candidate_type="fact",
                proposed_question_text=f"What does {chunk.section_title or 'this section'} say?",
                proposed_question_key=f"q_{chunk.chunk_id}",
                proposed_answer_text=chunk.content_text,
                proposed_topic_id="cancellation_policy" if "cancel" in chunk.content_text.lower() else None,
                proposed_tags=["llm_extracted"],
                proposed_metadata={"chunk_id": chunk.chunk_id},
                confidence=0.92,
                evidence_excerpt=chunk.content_text,
                source_section=chunk.section_title or block.render_type,
            )
            usage = LLMUsage(
                model="claude-sonnet-4-20250514",
                input_tokens=100,
                output_tokens=40,
                estimated_cost_usd=0.001,
                latency_ms=150.0,
                attempts=1,
                retry_count=0,
                retry_wait_time_seconds=0.0,
                failed_after_max_retries=False,
            )
            results_by_chunk[chunk.chunk_id] = [candidate]
            detailed_results[chunk.chunk_id] = LLMExtractionResult(
                chunk_id=chunk.chunk_id,
                candidates=[candidate],
                usage=usage,
                raw_text="[]",
                error=None,
            )
        return LLMBatchExtractionResult(
            results_by_chunk=results_by_chunk,
            detailed_results=detailed_results,
            total_input_tokens=100 * len(chunks),
            total_output_tokens=40 * len(chunks),
            total_estimated_cost_usd=0.001 * len(chunks),
            total_retry_count=0,
            total_retry_wait_time_seconds=0.0,
            failed_after_max_retries=0,
            failed_chunks=[],
        )


class _TestOrchestrator(ExtractorOrchestrator):
    def __init__(self, *, documents, manifest, staging_service, llm_extractor):
        super().__init__(staging_service=staging_service, llm_extractor=llm_extractor)
        self._documents = {document.id: document for document in documents}
        self._manifest = manifest

    async def _load_document(self, session, *, document_id, tenant_id):
        return self._documents[UUID(str(document_id))]

    async def _load_portfolio_documents(self, session, *, tenant_id, document_ids):
        if document_ids is None:
            return list(self._documents.values())
        filter_ids = {UUID(str(value)) for value in document_ids}
        return [document for document in self._documents.values() if document.id in filter_ids]

    async def extract_for_portfolio(self, session, *, tenant_id, document_ids=None, concurrency=3):
        semaphore = concurrency  # keep signature parity for assertions if needed
        _ = semaphore
        return await super().extract_for_portfolio(session, tenant_id=tenant_id, document_ids=document_ids, concurrency=concurrency)


def _document(document_id: str, property_id: UUID, source_url: str | None = "https://guide.example.com/token") -> DocumentModel:
    return DocumentModel(
        id=UUID(document_id),
        tenant_id=TENANT_ID,
        property_id=property_id,
        document_group_id=UUID(document_id),
        scope_type="property",
        version_number=1,
        document_type="guidebook_api",
        filename="api_response.json",
        file_path="tenant/doc/original/api_response.json",
        storage_backend="r2",
        file_size=100,
        mime_type="application/json",
        content_hash="abc",
        upload_method="guidebook_api",
        extraction_status="completed",
        extracted_fields={"source_url": source_url} if source_url else {},
        uploaded_at=datetime.now(timezone.utc),
    )


def _block(
    *,
    render_type: str,
    source_property_id: UUID,
    page_id: int,
    applicable_property_ids: list[UUID],
    scope_type: str = "property",
    data=None,
    title: str = "",
    duplicate_group_metadata=None,
) -> CanonicalBlock:
    return CanonicalBlock(
        block_hash=f"{render_type}:{page_id}:{source_property_id}",
        render_type=render_type,
        tenant_id=TENANT_ID,
        canonical_source_property_id=source_property_id,
        canonical_page_id=page_id,
        applicable_property_ids=applicable_property_ids,
        scope_type=scope_type,
        duplicate_group_metadata=duplicate_group_metadata,
        duplicate_count=len(applicable_property_ids),
        block_content={"id": page_id, "title": title, "page_title": title, "data": data},
    )


def _manifest(*blocks: CanonicalBlock) -> CanonicalBlockManifest:
    grouped: dict[str, list[CanonicalBlock]] = {}
    for block in blocks:
        grouped.setdefault(block.render_type, []).append(block)
    return CanonicalBlockManifest(
        canonical_blocks=grouped,
        duplicate_groups={},
        page_mapping={},
        skip_render_types=set(),
        empty_content_property_ids={},
    )


@pytest.mark.asyncio
async def test_extract_from_document_routes_deterministic_and_llm_candidates():
    doc = _document("00000000-0000-0000-0000-000000000001", PROP_A)
    manifest = _manifest(
        _block(
            render_type="widget.wifi",
            source_property_id=PROP_A,
            page_id=101,
            applicable_property_ids=[PROP_A],
            data={"wifi_name": "BeachWifi", "wifi_password": "sunshine"},
            title="Arrival",
        ),
        _block(
            render_type="widget.email_address",
            source_property_id=PROP_A,
            page_id=102,
            applicable_property_ids=[PROP_A, PROP_B],
            scope_type="tenant",
            data="info@example.com",
            title="Contact",
        ),
        _block(
            render_type="guide_content.rules",
            source_property_id=PROP_A,
            page_id=103,
            applicable_property_ids=[PROP_A],
            data="<ul><li>Quiet hours are from 10pm to 9am.</li></ul>",
            title="General",
        ),
    )
    staging = _FakeStagingService()
    llm = _FakeLLMExtractor()
    orchestrator = _TestOrchestrator(documents=[doc], manifest=manifest, staging_service=staging, llm_extractor=llm)

    result = await orchestrator.extract_from_document(None, document_id=doc.id, tenant_id=TENANT_ID, canonical_manifest=manifest)

    assert result.candidates_created == 4
    assert result.auto_promoted == 3
    assert result.staged_for_review == 1
    assert result.deterministic_candidates_created == 3
    assert result.llm_candidates_created == 1
    assert result.failed_blocks == 0
    assert result.total_input_tokens == 100
    assert result.total_output_tokens == 40
    assert len(staging.created) == 4
    tenant_candidate = next(row for row in staging.created if row["scope_type"] == "tenant")
    assert tenant_candidate["scope_target_id"] == str(TENANT_ID)
    assert tenant_candidate["source_url"] == "https://guide.example.com/token"
    llm_candidate = next(row for row in staging.created if row["extraction_method"] == "llm")
    assert llm_candidate["confidence"] == 0.92


@pytest.mark.asyncio
async def test_extract_for_portfolio_processes_tenant_scope_only_once():
    doc_a = _document("00000000-0000-0000-0000-000000000001", PROP_A)
    doc_b = _document("00000000-0000-0000-0000-000000000002", PROP_B)
    manifest = _manifest(
        _block(
            render_type="widget.email_address",
            source_property_id=PROP_A,
            page_id=201,
            applicable_property_ids=[PROP_A, PROP_B],
            scope_type="tenant",
            data="info@example.com",
            title="Contact",
        ),
        _block(
            render_type="widget.wifi",
            source_property_id=PROP_A,
            page_id=202,
            applicable_property_ids=[PROP_A],
            data={"wifi_name": "WifiA", "wifi_password": "alpha"},
            title="Arrival",
        ),
        _block(
            render_type="widget.wifi",
            source_property_id=PROP_B,
            page_id=203,
            applicable_property_ids=[PROP_B],
            data={"wifi_name": "WifiB", "wifi_password": "bravo"},
            title="Arrival",
        ),
    )
    staging = _FakeStagingService()
    orchestrator = _TestOrchestrator(
        documents=[doc_a, doc_b],
        manifest=manifest,
        staging_service=staging,
        llm_extractor=_FakeLLMExtractor(),
    )
    orchestrator._canonical_block_service.build_manifest_for_portfolio = _fake_manifest_builder(manifest)

    result = await orchestrator.extract_for_portfolio(None, tenant_id=TENANT_ID)

    assert result.documents_processed == 2
    assert result.candidates_created == 5
    assert result.auto_promoted == 5
    assert len([row for row in staging.created if row["scope_type"] == "tenant"]) == 1


@pytest.mark.asyncio
async def test_extract_from_document_isolates_block_failures():
    doc = _document("00000000-0000-0000-0000-000000000003", PROP_A)
    manifest = _manifest(
        _block(
            render_type="widget.wifi",
            source_property_id=PROP_A,
            page_id=301,
            applicable_property_ids=[PROP_A],
            data={"wifi_name": "BeachWifi", "wifi_password": "sunshine"},
            title="Arrival",
        ),
        _block(
            render_type="guide_content.rules",
            source_property_id=PROP_A,
            page_id=302,
            applicable_property_ids=[PROP_A],
            data="<ul><li>Quiet hours are from 10pm to 9am.</li></ul>",
            title="General",
        ),
    )
    staging = _FakeStagingService()
    llm = _FakeLLMExtractor(fail_render_types={"guide_content.rules"})
    orchestrator = _TestOrchestrator(documents=[doc], manifest=manifest, staging_service=staging, llm_extractor=llm)

    result = await orchestrator.extract_from_document(None, document_id=doc.id, tenant_id=TENANT_ID, canonical_manifest=manifest)

    assert result.candidates_created == 2
    assert result.auto_promoted == 2
    assert result.failed_blocks == 1
    assert any("block_failed" in error for error in result.errors)


def _fake_manifest_builder(manifest):
    async def _builder(session, tenant_id, document_ids=None):
        return manifest

    return _builder
