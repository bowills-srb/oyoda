from __future__ import annotations

from dataclasses import dataclass, field
import asyncio
import logging
import time
from typing import Iterable, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.extraction.canonical_block_service import CanonicalBlock, CanonicalBlockManifest, CanonicalBlockService
from app.services.extraction.chunkers import chunk_canonical_block
from app.services.extraction.deterministic_extractors import ExtractionCandidatePayload, extract_deterministic_candidates
from app.services.extraction.llm_extractor import LLMBatchExtractionResult, LLMExtractor
from app.services.extraction.staging_service import ExtractionStagingService, get_extraction_staging_service
from db.models.documents import DocumentModel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BlockExtractionResult:
    render_type: str
    block_hash: str
    candidates_created: int
    auto_promoted: int
    staged_for_review: int
    skipped: bool = False
    failed_chunks: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0
    latency_ms: float = 0.0
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ExtractionRunResult:
    document_id: UUID
    tenant_id: UUID
    property_id: UUID
    canonical_blocks_processed: int
    candidates_created: int
    auto_promoted: int
    staged_for_review: int
    deterministic_candidates_created: int
    llm_candidates_created: int
    failed_blocks: int
    failed_chunks: int
    total_input_tokens: int
    total_output_tokens: int
    total_estimated_cost_usd: float
    total_latency_ms: float
    candidate_ids: list[UUID]
    auto_promoted_candidate_ids: list[UUID]
    staged_candidate_ids: list[UUID]
    block_results: list[BlockExtractionResult]
    errors: list[str]


@dataclass(frozen=True)
class PortfolioRunResult:
    tenant_id: UUID
    document_ids: list[UUID]
    manifest_canonical_blocks: int
    documents_processed: int
    candidates_created: int
    auto_promoted: int
    staged_for_review: int
    deterministic_candidates_created: int
    llm_candidates_created: int
    failed_documents: int
    failed_blocks: int
    failed_chunks: int
    total_input_tokens: int
    total_output_tokens: int
    total_estimated_cost_usd: float
    total_latency_ms: float
    results: list[ExtractionRunResult]
    errors: list[str]


class ExtractorOrchestrator:
    def __init__(
        self,
        *,
        canonical_block_service: Optional[CanonicalBlockService] = None,
        staging_service: Optional[ExtractionStagingService] = None,
        llm_extractor: Optional[LLMExtractor] = None,
        llm_chunk_concurrency: int = 2,
    ) -> None:
        self._canonical_block_service = canonical_block_service or CanonicalBlockService()
        self._staging_service = staging_service or get_extraction_staging_service()
        self._llm_extractor = llm_extractor or LLMExtractor()
        self._llm_chunk_concurrency = max(1, llm_chunk_concurrency)

    async def extract_from_document(
        self,
        session: AsyncSession,
        *,
        document_id: UUID | str,
        tenant_id: UUID | str,
        canonical_manifest: CanonicalBlockManifest,
    ) -> ExtractionRunResult:
        tenant_uuid = _coerce_uuid(tenant_id)
        document = await self._load_document(session, document_id=document_id, tenant_id=tenant_uuid)
        return await self._extract_from_document_record(
            session,
            document=document,
            canonical_manifest=canonical_manifest,
            restrict_tenant_scope_to_canonical_source=False,
        )

    async def extract_for_portfolio(
        self,
        session: AsyncSession,
        *,
        tenant_id: UUID | str,
        document_ids: Optional[Iterable[UUID | str]] = None,
        concurrency: int = 1,
    ) -> PortfolioRunResult:
        tenant_uuid = _coerce_uuid(tenant_id)
        documents = await self._load_portfolio_documents(session, tenant_id=tenant_uuid, document_ids=document_ids)
        manifest = await self._canonical_block_service.build_manifest_for_portfolio(
            session,
            tenant_uuid,
            document_ids=[document.id for document in documents],
        )
        semaphore = asyncio.Semaphore(max(1, concurrency))

        async def _run(document: DocumentModel) -> ExtractionRunResult:
            async with semaphore:
                return await self._extract_from_document_record(
                    session,
                    document=document,
                    canonical_manifest=manifest,
                    restrict_tenant_scope_to_canonical_source=True,
                )

        results = await asyncio.gather(*[_run(document) for document in documents], return_exceptions=True)
        run_results: list[ExtractionRunResult] = []
        errors: list[str] = []
        failed_documents = 0
        for result in results:
            if isinstance(result, Exception):
                failed_documents += 1
                errors.append(str(result))
                continue
            run_results.append(result)
            if result.errors:
                errors.extend(result.errors)

        return PortfolioRunResult(
            tenant_id=tenant_uuid,
            document_ids=[document.id for document in documents],
            manifest_canonical_blocks=manifest.total_canonical_blocks,
            documents_processed=len(run_results),
            candidates_created=sum(result.candidates_created for result in run_results),
            auto_promoted=sum(result.auto_promoted for result in run_results),
            staged_for_review=sum(result.staged_for_review for result in run_results),
            deterministic_candidates_created=sum(result.deterministic_candidates_created for result in run_results),
            llm_candidates_created=sum(result.llm_candidates_created for result in run_results),
            failed_documents=failed_documents,
            failed_blocks=sum(result.failed_blocks for result in run_results),
            failed_chunks=sum(result.failed_chunks for result in run_results),
            total_input_tokens=sum(result.total_input_tokens for result in run_results),
            total_output_tokens=sum(result.total_output_tokens for result in run_results),
            total_estimated_cost_usd=sum(result.total_estimated_cost_usd for result in run_results),
            total_latency_ms=sum(result.total_latency_ms for result in run_results),
            results=run_results,
            errors=errors,
        )

    async def _extract_from_document_record(
        self,
        session: AsyncSession,
        *,
        document: DocumentModel,
        canonical_manifest: CanonicalBlockManifest,
        restrict_tenant_scope_to_canonical_source: bool,
    ) -> ExtractionRunResult:
        if document.property_id is None:
            raise ValueError(f"document {document.id} missing property_id")

        block_results: list[BlockExtractionResult] = []
        candidate_ids: list[UUID] = []
        auto_promoted_candidate_ids: list[UUID] = []
        staged_candidate_ids: list[UUID] = []
        errors: list[str] = []
        total_input_tokens = 0
        total_output_tokens = 0
        total_cost = 0.0
        total_latency_ms = 0.0
        deterministic_created = 0
        llm_created = 0
        failed_blocks = 0
        failed_chunks = 0

        source_url = _document_source_url(document)
        blocks = self._blocks_for_document(
            canonical_manifest,
            property_id=document.property_id,
            restrict_tenant_scope_to_canonical_source=restrict_tenant_scope_to_canonical_source,
        )

        for block in blocks:
            try:
                block_result = await self._process_block(
                    session,
                    document=document,
                    block=block,
                    source_url=source_url,
                )
                block_results.append(block_result)
                total_input_tokens += block_result.input_tokens
                total_output_tokens += block_result.output_tokens
                total_cost += block_result.estimated_cost_usd
                total_latency_ms += block_result.latency_ms
                failed_chunks += block_result.failed_chunks
                if block_result.errors:
                    failed_blocks += 1
                    errors.extend(block_result.errors)
            except Exception as exc:  # pragma: no cover
                failed_blocks += 1
                message = f"block_failed render_type={block.render_type} block_hash={block.block_hash} error={exc}"
                logger.warning("[ExtractorOrchestrator] %s", message)
                errors.append(message)
                block_results.append(
                    BlockExtractionResult(
                        render_type=block.render_type,
                        block_hash=block.block_hash,
                        candidates_created=0,
                        auto_promoted=0,
                        staged_for_review=0,
                        errors=[message],
                    )
                )
                continue

            candidate_ids.extend(block_result.metadata_candidate_ids)
            auto_promoted_candidate_ids.extend(block_result.metadata_auto_promoted_candidate_ids)
            staged_candidate_ids.extend(block_result.metadata_staged_candidate_ids)
            deterministic_created += block_result.metadata_deterministic_created
            llm_created += block_result.metadata_llm_created

        return ExtractionRunResult(
            document_id=document.id,
            tenant_id=document.tenant_id,
            property_id=document.property_id,
            canonical_blocks_processed=len(blocks),
            candidates_created=len(candidate_ids),
            auto_promoted=len(auto_promoted_candidate_ids),
            staged_for_review=len(staged_candidate_ids),
            deterministic_candidates_created=deterministic_created,
            llm_candidates_created=llm_created,
            failed_blocks=failed_blocks,
            failed_chunks=failed_chunks,
            total_input_tokens=total_input_tokens,
            total_output_tokens=total_output_tokens,
            total_estimated_cost_usd=total_cost,
            total_latency_ms=total_latency_ms,
            candidate_ids=candidate_ids,
            auto_promoted_candidate_ids=auto_promoted_candidate_ids,
            staged_candidate_ids=staged_candidate_ids,
            block_results=block_results,
            errors=errors,
        )

    def _blocks_for_document(
        self,
        manifest: CanonicalBlockManifest,
        *,
        property_id: UUID,
        restrict_tenant_scope_to_canonical_source: bool,
    ) -> list[CanonicalBlock]:
        blocks: list[CanonicalBlock] = []
        for render_type in sorted(manifest.canonical_blocks):
            for block in manifest.canonical_blocks[render_type]:
                if property_id not in block.applicable_property_ids:
                    continue
                if (
                    restrict_tenant_scope_to_canonical_source
                    and block.scope_type == "tenant"
                    and block.canonical_source_property_id != property_id
                ):
                    continue
                blocks.append(block)
        return blocks

    async def _process_block(
        self,
        session: AsyncSession,
        *,
        document: DocumentModel,
        block: CanonicalBlock,
        source_url: Optional[str],
    ) -> "_InternalBlockResult":
        deterministic_payloads = extract_deterministic_candidates(block)
        deterministic_created, deterministic_promoted, deterministic_staged, deterministic_ids, deterministic_auto_ids = await self._persist_payloads(
            session,
            document=document,
            source_url=source_url,
            payloads=deterministic_payloads,
        )

        llm_batch: Optional[LLMBatchExtractionResult] = None
        llm_payloads: list[ExtractionCandidatePayload] = []
        if not deterministic_payloads:
            chunks = chunk_canonical_block(block)
            if chunks:
                llm_batch = await self._llm_extractor.extract_from_chunks_batch(
                    chunks,
                    {block.block_hash: block},
                    concurrency=self._llm_chunk_concurrency,
                )
                for candidates in llm_batch.results_by_chunk.values():
                    llm_payloads.extend(candidates)

        llm_created, llm_promoted, llm_staged, llm_ids, llm_auto_ids = await self._persist_payloads(
            session,
            document=document,
            source_url=source_url,
            payloads=llm_payloads,
        )

        llm_usage_input = llm_batch.total_input_tokens if llm_batch else 0
        llm_usage_output = llm_batch.total_output_tokens if llm_batch else 0
        llm_usage_cost = llm_batch.total_estimated_cost_usd if llm_batch else 0.0
        llm_failed_chunks = len(llm_batch.failed_chunks) if llm_batch else 0
        llm_latency_ms = 0.0
        if llm_batch:
            llm_latency_ms = sum(
                result.usage.latency_ms
                for result in llm_batch.detailed_results.values()
                if result.usage is not None
            )

        errors: list[str] = []
        if llm_batch:
            for chunk_id in llm_batch.failed_chunks:
                errors.append(f"llm_chunk_failed render_type={block.render_type} block_hash={block.block_hash} chunk_id={chunk_id}")

        return _InternalBlockResult(
            render_type=block.render_type,
            block_hash=block.block_hash,
            candidates_created=deterministic_created + llm_created,
            auto_promoted=deterministic_promoted + llm_promoted,
            staged_for_review=deterministic_staged + llm_staged,
            failed_chunks=llm_failed_chunks,
            input_tokens=llm_usage_input,
            output_tokens=llm_usage_output,
            estimated_cost_usd=llm_usage_cost,
            latency_ms=llm_latency_ms,
            errors=errors,
            metadata_candidate_ids=[*deterministic_ids, *llm_ids],
            metadata_auto_promoted_candidate_ids=[*deterministic_auto_ids, *llm_auto_ids],
            metadata_staged_candidate_ids=[
                *[candidate_id for candidate_id in deterministic_ids if candidate_id not in set(deterministic_auto_ids)],
                *[candidate_id for candidate_id in llm_ids if candidate_id not in set(llm_auto_ids)],
            ],
            metadata_deterministic_created=deterministic_created,
            metadata_llm_created=llm_created,
        )

    async def _persist_payloads(
        self,
        session: AsyncSession,
        *,
        document: DocumentModel,
        source_url: Optional[str],
        payloads: list[ExtractionCandidatePayload],
    ) -> tuple[int, int, int, list[UUID], list[UUID]]:
        if not payloads:
            return 0, 0, 0, [], []

        created_ids: list[UUID] = []
        for payload in payloads:
            candidate = await self._staging_service.create_candidate(
                session,
                tenant_id=document.tenant_id,
                scope_type=payload.scope_type,
                scope_target_id=payload.scope_target_id,
                source_type=payload.source_type,
                extraction_method=payload.extraction_method,
                candidate_type=payload.candidate_type,
                source_document_id=document.id,
                source_url=source_url,
                proposed_question_text=payload.proposed_question_text,
                proposed_question_key=payload.proposed_question_key,
                proposed_answer_text=payload.proposed_answer_text,
                proposed_topic_id=payload.proposed_topic_id,
                proposed_tags=payload.proposed_tags,
                proposed_metadata=payload.proposed_metadata,
                confidence=payload.confidence,
                evidence_excerpt=payload.evidence_excerpt,
                source_section=payload.source_section,
            )
            created_ids.append(candidate.candidate_id)

        promotion = await self._staging_service.auto_promote_eligible(
            session,
            document.tenant_id,
            candidate_ids=created_ids,
        )
        auto_promoted = int(promotion.get("auto_promoted") or 0)
        auto_promoted_ids = [
            result.candidate_id
            for result in (promotion.get("results") or [])
            if getattr(result, "candidate_id", None) is not None
        ]
        staged_for_review = len(created_ids) - auto_promoted
        return len(created_ids), auto_promoted, staged_for_review, created_ids, auto_promoted_ids

    async def _load_document(
        self,
        session: AsyncSession,
        *,
        document_id: UUID | str,
        tenant_id: UUID,
    ) -> DocumentModel:
        document_uuid = _coerce_uuid(document_id)
        stmt = (
            select(DocumentModel)
            .where(DocumentModel.id == document_uuid)
            .where(DocumentModel.tenant_id == tenant_id)
            .limit(1)
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise ValueError(f"document {document_uuid} not found for tenant {tenant_id}")
        return row

    async def _load_portfolio_documents(
        self,
        session: AsyncSession,
        *,
        tenant_id: UUID,
        document_ids: Optional[Iterable[UUID | str]],
    ) -> list[DocumentModel]:
        stmt = (
            select(DocumentModel)
            .where(DocumentModel.tenant_id == tenant_id)
            .where(DocumentModel.document_type == "guidebook_api")
            .where(DocumentModel.extraction_status == "completed")
            .order_by(DocumentModel.property_id, DocumentModel.version_number.desc(), DocumentModel.uploaded_at.desc())
        )
        rows = (await session.execute(stmt)).scalars().all()
        filter_ids = None
        if document_ids is not None:
            filter_ids = {_coerce_uuid(value) for value in document_ids}
        latest: dict[UUID, DocumentModel] = {}
        for row in rows:
            if row.property_id is None:
                continue
            if filter_ids is not None and row.id not in filter_ids:
                continue
            latest.setdefault(row.property_id, row)
        return sorted(latest.values(), key=lambda item: str(item.property_id))


@dataclass(frozen=True)
class _InternalBlockResult(BlockExtractionResult):
    metadata_candidate_ids: list[UUID] = field(default_factory=list)
    metadata_auto_promoted_candidate_ids: list[UUID] = field(default_factory=list)
    metadata_staged_candidate_ids: list[UUID] = field(default_factory=list)
    metadata_deterministic_created: int = 0
    metadata_llm_created: int = 0


def _coerce_uuid(value: UUID | str) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


def _document_source_url(document: DocumentModel) -> Optional[str]:
    extracted_fields = document.extracted_fields or {}
    if not isinstance(extracted_fields, dict):
        return None
    source_url = extracted_fields.get("source_url")
    if source_url:
        return str(source_url)
    document_metadata = extracted_fields.get("document_metadata")
    if isinstance(document_metadata, dict) and document_metadata.get("source_url"):
        return str(document_metadata["source_url"])
    return None
