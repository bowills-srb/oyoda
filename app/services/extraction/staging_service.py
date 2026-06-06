from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from functools import lru_cache
from typing import Any, Iterable, Optional
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.messaging_brain.knowledge.scoped_knowledge_service import ScopedKnowledgeService
from app.services.operator.property_asset_service import OperatorPropertyAssetService


def _coerce_uuid(value: UUID | str | None) -> Optional[UUID]:
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    text_value = str(value).strip()
    if not text_value:
        return None
    return UUID(text_value)


def _coerce_json(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return default
    return value


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


@dataclass(frozen=True)
class ExtractionCandidate:
    candidate_id: UUID
    tenant_id: UUID
    scope_type: str
    scope_target_id: UUID
    source_type: str
    source_document_id: Optional[UUID]
    source_url: Optional[str]
    extraction_method: str
    candidate_type: str
    proposed_question_text: Optional[str]
    proposed_question_key: Optional[str]
    proposed_answer_text: Optional[str]
    proposed_topic_id: Optional[str]
    proposed_tags: list[str]
    proposed_metadata: dict[str, Any]
    confidence: float
    evidence_excerpt: Optional[str]
    source_section: Optional[str]
    review_status: str
    reviewed_by_user_id: Optional[UUID]
    reviewed_at: Optional[datetime]
    review_notes: Optional[str]
    promoted_to_table: Optional[str]
    promoted_to_id: Optional[UUID]
    promoted_at: Optional[datetime]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]


@dataclass(frozen=True)
class ExtractionCandidateFilters:
    scope_target_id: Optional[UUID | str] = None
    candidate_type: Optional[str] = None
    source_type: Optional[str] = None
    source_document_id: Optional[UUID | str] = None
    confidence_min: Optional[float] = None
    confidence_max: Optional[float] = None


@dataclass(frozen=True)
class ExtractionPromotionResult:
    candidate_id: UUID
    review_status: str
    promoted_to_table: Optional[str]
    promoted_to_id: Optional[UUID]


class ExtractionStagingService:
    _ALLOWED_SCOPE_TYPES = {"property", "tenant", "property_group"}
    _ALLOWED_SOURCE_TYPES = {"guidebook", "pdf", "pms", "spreadsheet", "dashboard_extraction", "other"}
    _ALLOWED_METHODS = {"deterministic", "llm", "hybrid"}
    _ALLOWED_CANDIDATE_TYPES = {"fact", "asset", "document_metadata"}

    def __init__(
        self,
        *,
        scoped_knowledge_service: Optional[ScopedKnowledgeService] = None,
        property_asset_service: Optional[OperatorPropertyAssetService] = None,
    ) -> None:
        self._scoped_knowledge_service = scoped_knowledge_service or ScopedKnowledgeService()
        self._property_asset_service = property_asset_service or OperatorPropertyAssetService()

    async def create_candidate(
        self,
        session: AsyncSession,
        *,
        tenant_id: UUID | str,
        scope_type: str,
        scope_target_id: UUID | str,
        source_type: str,
        extraction_method: str,
        candidate_type: str,
        source_document_id: UUID | str | None = None,
        source_url: Optional[str] = None,
        proposed_question_text: Optional[str] = None,
        proposed_question_key: Optional[str] = None,
        proposed_answer_text: Optional[str] = None,
        proposed_topic_id: Optional[str] = None,
        proposed_tags: Optional[Iterable[str]] = None,
        proposed_metadata: Optional[dict[str, Any]] = None,
        confidence: float = 0.0,
        evidence_excerpt: Optional[str] = None,
        source_section: Optional[str] = None,
    ) -> ExtractionCandidate:
        tenant_uuid = _coerce_uuid(tenant_id)
        target_uuid = _coerce_uuid(scope_target_id)
        document_uuid = _coerce_uuid(source_document_id)
        if tenant_uuid is None or target_uuid is None:
            raise ValueError("tenant_id and scope_target_id are required")
        scope_value = _normalize_text(scope_type).lower()
        source_value = _normalize_text(source_type).lower()
        method_value = _normalize_text(extraction_method).lower()
        candidate_value = _normalize_text(candidate_type).lower()
        if scope_value not in self._ALLOWED_SCOPE_TYPES:
            raise ValueError(f"unsupported scope_type: {scope_type}")
        if source_value not in self._ALLOWED_SOURCE_TYPES:
            raise ValueError(f"unsupported source_type: {source_type}")
        if method_value not in self._ALLOWED_METHODS:
            raise ValueError(f"unsupported extraction_method: {extraction_method}")
        if candidate_value not in self._ALLOWED_CANDIDATE_TYPES:
            raise ValueError(f"unsupported candidate_type: {candidate_type}")

        payload = {
            "candidate_id": str(uuid4()),
            "tenant_id": str(tenant_uuid),
            "scope_type": scope_value,
            "scope_target_id": str(target_uuid),
            "source_type": source_value,
            "source_document_id": str(document_uuid) if document_uuid else None,
            "source_url": source_url,
            "extraction_method": method_value,
            "candidate_type": candidate_value,
            "proposed_question_text": proposed_question_text,
            "proposed_question_key": proposed_question_key,
            "proposed_answer_text": proposed_answer_text,
            "proposed_topic_id": proposed_topic_id,
            "proposed_tags": json.dumps(list(proposed_tags or [])),
            "proposed_metadata": json.dumps(proposed_metadata or {}),
            "confidence": float(confidence),
            "evidence_excerpt": evidence_excerpt,
            "source_section": source_section,
        }
        row = await self._insert_candidate(session, payload)
        return self._candidate_from_record(row)

    async def get_pending_candidates(
        self,
        session: AsyncSession,
        tenant_id: UUID | str,
        filters: Optional[ExtractionCandidateFilters] = None,
    ) -> list[ExtractionCandidate]:
        records = await self._load_candidates(
            session,
            tenant_id=_coerce_uuid(tenant_id),
            review_status="pending",
            filters=filters or ExtractionCandidateFilters(),
        )
        return [self._candidate_from_record(record) for record in records]

    async def approve_candidate(
        self,
        session: AsyncSession,
        candidate_id: UUID | str,
        reviewed_by_user_id: UUID | str,
        edits: Optional[dict[str, Any]] = None,
        *,
        review_status_override: Optional[str] = None,
        _is_auto_promoted: bool = False,
    ) -> ExtractionPromotionResult:
        candidate = await self._require_candidate(session, candidate_id)
        if candidate.review_status not in {"pending", "approved", "edited", "auto_promoted"}:
            raise ValueError(f"candidate not approvable from status {candidate.review_status}")

        merged = self._apply_edits(candidate, edits or {})
        promoted_to_table, promoted_to_id = await self._promote_candidate(
            session=session,
            candidate=merged,
            reviewed_by_user_id=_coerce_uuid(reviewed_by_user_id),
            is_auto_promoted=_is_auto_promoted,
        )
        final_status = review_status_override or ("edited" if edits else "approved")
        await self._update_candidate_review(
            session,
            candidate_id=merged.candidate_id,
            review_status=final_status,
            reviewed_by_user_id=_coerce_uuid(reviewed_by_user_id),
            review_notes=(edits or {}).get("review_notes"),
            promoted_to_table=promoted_to_table,
            promoted_to_id=promoted_to_id,
            persisted_candidate=merged,
        )
        return ExtractionPromotionResult(
            candidate_id=merged.candidate_id,
            review_status=final_status,
            promoted_to_table=promoted_to_table,
            promoted_to_id=promoted_to_id,
        )

    async def reject_candidate(
        self,
        session: AsyncSession,
        candidate_id: UUID | str,
        reviewed_by_user_id: UUID | str,
        notes: Optional[str] = None,
    ) -> ExtractionPromotionResult:
        candidate = await self._require_candidate(session, candidate_id)
        await self._update_candidate_review(
            session,
            candidate_id=candidate.candidate_id,
            review_status="rejected",
            reviewed_by_user_id=_coerce_uuid(reviewed_by_user_id),
            review_notes=notes,
            promoted_to_table=None,
            promoted_to_id=None,
            persisted_candidate=candidate,
        )
        return ExtractionPromotionResult(
            candidate_id=candidate.candidate_id,
            review_status="rejected",
            promoted_to_table=None,
            promoted_to_id=None,
        )

    async def bulk_approve(
        self,
        session: AsyncSession,
        candidate_ids: Optional[Iterable[UUID | str]],
        reviewed_by_user_id: UUID | str,
        filters: Optional[ExtractionCandidateFilters] = None,
        tenant_id: UUID | str | None = None,
    ) -> dict[str, Any]:
        items: list[ExtractionCandidate]
        if candidate_ids:
            items = [await self._require_candidate(session, candidate_id) for candidate_id in candidate_ids]
        else:
            if tenant_id is None:
                raise ValueError("tenant_id is required for filter-based bulk approval")
            items = await self.get_pending_candidates(session, tenant_id, filters)
        approved = 0
        results: list[ExtractionPromotionResult] = []
        for item in items:
            if item.review_status != "pending":
                continue
            results.append(await self.approve_candidate(session, item.candidate_id, reviewed_by_user_id))
            approved += 1
        return {"approved": approved, "skipped": len(items) - approved, "results": results}

    async def auto_promote_eligible(
        self,
        session: AsyncSession,
        tenant_id: UUID | str,
        reviewed_by_user_id: UUID | str | None = None,
        candidate_ids: Optional[Iterable[UUID | str]] = None,
    ) -> dict[str, Any]:
        pending = await self.get_pending_candidates(session, tenant_id)
        candidate_id_filter = {
            _coerce_uuid(candidate_id)
            for candidate_id in (candidate_ids or [])
            if _coerce_uuid(candidate_id) is not None
        }
        results: list[ExtractionPromotionResult] = []
        for candidate in pending:
            if candidate_id_filter and candidate.candidate_id not in candidate_id_filter:
                continue
            if self._is_auto_promotable(candidate):
                reviewer = (
                    _coerce_uuid(reviewed_by_user_id)
                    or candidate.reviewed_by_user_id
                    or UUID("00000000-0000-0000-0000-000000000001")
                )
                results.append(
                    await self.approve_candidate(
                        session,
                        candidate.candidate_id,
                        reviewer,
                        review_status_override="auto_promoted",
                        _is_auto_promoted=True,
                    )
                )
        return {"auto_promoted": len(results), "results": results}

    def _is_auto_promotable(self, candidate: ExtractionCandidate) -> bool:
        if candidate.extraction_method == "llm":
            return False
        if candidate.confidence < 0.7:
            return False
        if candidate.source_type == "pms" and candidate.confidence >= 0.99:
            return True
        if (
            candidate.confidence >= 0.95
            and candidate.extraction_method == "deterministic"
            and candidate.candidate_type in {"fact", "asset"}
        ):
            return True
        return False

    async def _promote_candidate(
        self,
        *,
        session: AsyncSession,
        candidate: ExtractionCandidate,
        reviewed_by_user_id: Optional[UUID],
        is_auto_promoted: bool = False,
    ) -> tuple[Optional[str], Optional[UUID]]:
        if candidate.candidate_type == "fact":
            if reviewed_by_user_id is None:
                raise ValueError("reviewed_by_user_id is required for fact promotion")
            # Human verification: set verified_at/by only when a human approved.
            # Auto-promoted facts are "system-confident, unverified" — confidence is
            # set but verified_* stays NULL so "show me unverified facts" queries work.
            verified_at = (
                None if is_auto_promoted
                else datetime.now(timezone.utc)
            )
            verified_by = None if is_auto_promoted else reviewed_by_user_id
            result = await self._scoped_knowledge_service.write_scoped_knowledge(
                session=session,
                tenant_id=candidate.tenant_id,
                user_id=reviewed_by_user_id,
                scope_type=candidate.scope_type,
                scope_target_id=candidate.scope_target_id,
                topic_id=candidate.proposed_topic_id,
                question_text=candidate.proposed_question_text or "",
                answer_text=candidate.proposed_answer_text or "",
                tags=candidate.proposed_tags,
                source=f"extraction_candidate:{candidate.source_type}",
                metadata={
                    **candidate.proposed_metadata,
                    "source_document_id": str(candidate.source_document_id) if candidate.source_document_id else None,
                    "source_url": candidate.source_url,
                    "evidence_excerpt": candidate.evidence_excerpt,
                    "source_section": candidate.source_section,
                    "candidate_id": str(candidate.candidate_id),
                    "extraction_method": candidate.extraction_method,
                },
                confidence=candidate.confidence,
                verified_at=verified_at,
                verified_by_user_id=verified_by,
            )
            return "concierge_scoped_knowledge", result.knowledge_entry_id
        if candidate.candidate_type == "asset":
            # Assets are property-specific. A group-scoped asset candidate is invalid —
            # there is no single property to attach it to. Reject cleanly rather than
            # mis-resolving the group_id as a property id.
            if candidate.scope_type == "property_group":
                raise ValueError(
                    "asset candidates cannot have scope_type='property_group'; "
                    "assets are property-specific. Use scope_type='property' and "
                    "target the individual property, or use candidate_type='fact' "
                    "to store group-level information."
                )
            property_code = await self._resolve_property_code(
                session=session,
                tenant_id=candidate.tenant_id,
                scope_target_id=candidate.scope_target_id,
            )
            metadata = dict(candidate.proposed_metadata or {})
            asset_result = await self._property_asset_service.upsert_asset(
                session,
                str(candidate.tenant_id),
                property_code=property_code,
                asset_type=str(metadata.get("asset_type") or "document"),
                asset_name=str(metadata.get("asset_name") or candidate.proposed_question_text or "Extracted asset"),
                manufacturer=metadata.get("manufacturer"),
                model_number=metadata.get("model_number"),
                serial_number=metadata.get("serial_number"),
                notes=str(metadata.get("notes") or candidate.proposed_answer_text or candidate.evidence_excerpt or ""),
                metadata={
                    **metadata,
                    "candidate_id": str(candidate.candidate_id),
                    "source_type": candidate.source_type,
                    "source_document_id": str(candidate.source_document_id) if candidate.source_document_id else None,
                },
            )
            asset_id = _coerce_uuid(asset_result.get("asset_id")) if asset_result else None
            return "operator_property_assets", asset_id
        if candidate.candidate_type == "document_metadata":
            if candidate.source_document_id is None:
                raise ValueError("source_document_id is required for document_metadata promotion")
            existing = await self._load_document_extracted_fields(session, candidate.source_document_id)
            merged = dict(existing or {})
            doc_meta = dict(_coerce_json(merged.get("document_metadata"), {}))
            doc_meta.update(candidate.proposed_metadata or {})
            if candidate.proposed_answer_text:
                doc_meta["summary"] = candidate.proposed_answer_text
            if candidate.evidence_excerpt:
                doc_meta["evidence_excerpt"] = candidate.evidence_excerpt
            if candidate.source_section:
                doc_meta["source_section"] = candidate.source_section
            merged["document_metadata"] = doc_meta
            await session.execute(
                text(
                    """
                    UPDATE documents
                    SET extracted_fields = CAST(:extracted_fields AS jsonb),
                        processed_at = NOW()
                    WHERE id = CAST(:document_id AS uuid)
                    """
                ),
                {
                    "document_id": str(candidate.source_document_id),
                    "extracted_fields": json.dumps(merged),
                },
            )
            return "documents", candidate.source_document_id
        raise ValueError(f"unsupported candidate_type: {candidate.candidate_type}")

    async def _resolve_property_code(
        self,
        *,
        session: AsyncSession,
        tenant_id: UUID,
        scope_target_id: UUID,
    ) -> str:
        row = (
            await session.execute(
                text(
                    """
                    SELECT property_code
                    FROM properties
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                      AND id = CAST(:scope_target_id AS uuid)
                    LIMIT 1
                    """
                ),
                {"tenant_id": str(tenant_id), "scope_target_id": str(scope_target_id)},
            )
        ).mappings().first()
        if not row or not row.get("property_code"):
            raise ValueError("property_code not found for candidate scope_target_id")
        return str(row["property_code"])

    async def _load_document_extracted_fields(self, session: AsyncSession, document_id: UUID) -> dict[str, Any]:
        row = (
            await session.execute(
                text(
                    """
                    SELECT extracted_fields
                    FROM documents
                    WHERE id = CAST(:document_id AS uuid)
                    LIMIT 1
                    """
                ),
                {"document_id": str(document_id)},
            )
        ).mappings().first()
        return _coerce_json(row.get("extracted_fields") if row else {}, {})

    def _apply_edits(self, candidate: ExtractionCandidate, edits: dict[str, Any]) -> ExtractionCandidate:
        if not edits:
            return candidate
        return ExtractionCandidate(
            candidate_id=candidate.candidate_id,
            tenant_id=candidate.tenant_id,
            scope_type=str(edits.get("scope_type") or candidate.scope_type),
            scope_target_id=_coerce_uuid(edits.get("scope_target_id") or candidate.scope_target_id) or candidate.scope_target_id,
            source_type=candidate.source_type,
            source_document_id=candidate.source_document_id,
            source_url=edits.get("source_url") or candidate.source_url,
            extraction_method=candidate.extraction_method,
            candidate_type=str(edits.get("candidate_type") or candidate.candidate_type),
            proposed_question_text=edits.get("proposed_question_text", candidate.proposed_question_text),
            proposed_question_key=edits.get("proposed_question_key", candidate.proposed_question_key),
            proposed_answer_text=edits.get("proposed_answer_text", candidate.proposed_answer_text),
            proposed_topic_id=edits.get("proposed_topic_id", candidate.proposed_topic_id),
            proposed_tags=list(edits.get("proposed_tags", candidate.proposed_tags)),
            proposed_metadata=dict(edits.get("proposed_metadata", candidate.proposed_metadata)),
            confidence=float(edits.get("confidence", candidate.confidence)),
            evidence_excerpt=edits.get("evidence_excerpt", candidate.evidence_excerpt),
            source_section=edits.get("source_section", candidate.source_section),
            review_status=candidate.review_status,
            reviewed_by_user_id=candidate.reviewed_by_user_id,
            reviewed_at=candidate.reviewed_at,
            review_notes=edits.get("review_notes", candidate.review_notes),
            promoted_to_table=candidate.promoted_to_table,
            promoted_to_id=candidate.promoted_to_id,
            promoted_at=candidate.promoted_at,
            created_at=candidate.created_at,
            updated_at=candidate.updated_at,
        )

    def _candidate_from_record(self, row: Any) -> ExtractionCandidate:
        getter = row.get if isinstance(row, dict) else lambda key, default=None: getattr(row, key, default)
        return ExtractionCandidate(
            candidate_id=_coerce_uuid(getter("candidate_id")) or UUID(int=0),
            tenant_id=_coerce_uuid(getter("tenant_id")) or UUID(int=0),
            scope_type=str(getter("scope_type") or ""),
            scope_target_id=_coerce_uuid(getter("scope_target_id")) or UUID(int=0),
            source_type=str(getter("source_type") or ""),
            source_document_id=_coerce_uuid(getter("source_document_id")),
            source_url=getter("source_url"),
            extraction_method=str(getter("extraction_method") or ""),
            candidate_type=str(getter("candidate_type") or ""),
            proposed_question_text=getter("proposed_question_text"),
            proposed_question_key=getter("proposed_question_key"),
            proposed_answer_text=getter("proposed_answer_text"),
            proposed_topic_id=getter("proposed_topic_id"),
            proposed_tags=list(_coerce_json(getter("proposed_tags"), [])),
            proposed_metadata=dict(_coerce_json(getter("proposed_metadata"), {})),
            confidence=float(getter("confidence") or 0.0),
            evidence_excerpt=getter("evidence_excerpt"),
            source_section=getter("source_section"),
            review_status=str(getter("review_status") or "pending"),
            reviewed_by_user_id=_coerce_uuid(getter("reviewed_by_user_id")),
            reviewed_at=getter("reviewed_at"),
            review_notes=getter("review_notes"),
            promoted_to_table=getter("promoted_to_table"),
            promoted_to_id=_coerce_uuid(getter("promoted_to_id")),
            promoted_at=getter("promoted_at"),
            created_at=getter("created_at"),
            updated_at=getter("updated_at"),
        )

    async def _require_candidate(self, session: AsyncSession, candidate_id: UUID | str) -> ExtractionCandidate:
        row = await self._load_candidate_record(session, _coerce_uuid(candidate_id))
        if not row:
            raise ValueError("candidate not found")
        return self._candidate_from_record(row)

    async def _insert_candidate(self, session: AsyncSession, payload: dict[str, Any]) -> dict[str, Any]:
        row = (
            await session.execute(
                text(
                    """
                    INSERT INTO extraction_candidates (
                        candidate_id,
                        tenant_id,
                        scope_type,
                        scope_target_id,
                        source_type,
                        source_document_id,
                        source_url,
                        extraction_method,
                        candidate_type,
                        proposed_question_text,
                        proposed_question_key,
                        proposed_answer_text,
                        proposed_topic_id,
                        proposed_tags,
                        proposed_metadata,
                        confidence,
                        evidence_excerpt,
                        source_section
                    ) VALUES (
                        CAST(:candidate_id AS uuid),
                        CAST(:tenant_id AS uuid),
                        :scope_type,
                        CAST(:scope_target_id AS uuid),
                        :source_type,
                        CAST(:source_document_id AS uuid),
                        :source_url,
                        :extraction_method,
                        :candidate_type,
                        :proposed_question_text,
                        :proposed_question_key,
                        :proposed_answer_text,
                        :proposed_topic_id,
                        CAST(:proposed_tags AS jsonb),
                        CAST(:proposed_metadata AS jsonb),
                        :confidence,
                        :evidence_excerpt,
                        :source_section
                    )
                    RETURNING *
                    """
                ),
                payload,
            )
        ).mappings().first()
        return dict(row) if row else payload

    async def _load_candidate_record(self, session: AsyncSession, candidate_id: Optional[UUID]) -> Optional[dict[str, Any]]:
        if candidate_id is None:
            return None
        row = (
            await session.execute(
                text("SELECT * FROM extraction_candidates WHERE candidate_id = CAST(:candidate_id AS uuid) LIMIT 1"),
                {"candidate_id": str(candidate_id)},
            )
        ).mappings().first()
        return dict(row) if row else None

    async def _load_candidates(
        self,
        session: AsyncSession,
        *,
        tenant_id: Optional[UUID],
        review_status: Optional[str],
        filters: ExtractionCandidateFilters,
    ) -> list[dict[str, Any]]:
        clauses = []
        params: dict[str, Any] = {}
        if tenant_id:
            clauses.append("tenant_id = CAST(:tenant_id AS uuid)")
            params["tenant_id"] = str(tenant_id)
        if review_status:
            clauses.append("review_status = :review_status")
            params["review_status"] = review_status
        if filters.scope_target_id:
            clauses.append("scope_target_id = CAST(:scope_target_id AS uuid)")
            params["scope_target_id"] = str(_coerce_uuid(filters.scope_target_id))
        if filters.candidate_type:
            clauses.append("candidate_type = :candidate_type")
            params["candidate_type"] = filters.candidate_type
        if filters.source_type:
            clauses.append("source_type = :source_type")
            params["source_type"] = filters.source_type
        if filters.source_document_id:
            clauses.append("source_document_id = CAST(:source_document_id AS uuid)")
            params["source_document_id"] = str(_coerce_uuid(filters.source_document_id))
        if filters.confidence_min is not None:
            clauses.append("confidence >= :confidence_min")
            params["confidence_min"] = float(filters.confidence_min)
        if filters.confidence_max is not None:
            clauses.append("confidence <= :confidence_max")
            params["confidence_max"] = float(filters.confidence_max)
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = (
            await session.execute(
                text(f"SELECT * FROM extraction_candidates {where_sql} ORDER BY created_at ASC"),
                params,
            )
        ).mappings().all()
        return [dict(row) for row in rows]

    async def _update_candidate_review(
        self,
        session: AsyncSession,
        *,
        candidate_id: UUID,
        review_status: str,
        reviewed_by_user_id: Optional[UUID],
        review_notes: Optional[str],
        promoted_to_table: Optional[str],
        promoted_to_id: Optional[UUID],
        persisted_candidate: ExtractionCandidate,
    ) -> None:
        await session.execute(
            text(
                """
                UPDATE extraction_candidates
                SET proposed_question_text = :proposed_question_text,
                    proposed_question_key = :proposed_question_key,
                    proposed_answer_text = :proposed_answer_text,
                    proposed_topic_id = :proposed_topic_id,
                    proposed_tags = CAST(:proposed_tags AS jsonb),
                    proposed_metadata = CAST(:proposed_metadata AS jsonb),
                    confidence = :confidence,
                    evidence_excerpt = :evidence_excerpt,
                    source_section = :source_section,
                    review_status = :review_status,
                    reviewed_by_user_id = CAST(:reviewed_by_user_id AS uuid),
                    reviewed_at = NOW(),
                    review_notes = :review_notes,
                    promoted_to_table = :promoted_to_table,
                    promoted_to_id = CAST(:promoted_to_id AS uuid),
                    promoted_at = CAST(:promoted_at AS timestamptz),
                    updated_at = NOW()
                WHERE candidate_id = CAST(:candidate_id AS uuid)
                """
            ),
            {
                "candidate_id": str(candidate_id),
                "proposed_question_text": persisted_candidate.proposed_question_text,
                "proposed_question_key": persisted_candidate.proposed_question_key,
                "proposed_answer_text": persisted_candidate.proposed_answer_text,
                "proposed_topic_id": persisted_candidate.proposed_topic_id,
                "proposed_tags": json.dumps(persisted_candidate.proposed_tags),
                "proposed_metadata": json.dumps(persisted_candidate.proposed_metadata),
                "confidence": persisted_candidate.confidence,
                "evidence_excerpt": persisted_candidate.evidence_excerpt,
                "source_section": persisted_candidate.source_section,
                "review_status": review_status,
                "reviewed_by_user_id": str(reviewed_by_user_id) if reviewed_by_user_id else None,
                "review_notes": review_notes,
                "promoted_to_table": promoted_to_table,
                "promoted_to_id": str(promoted_to_id) if promoted_to_id else None,
                "promoted_at": datetime.now(timezone.utc) if promoted_to_table else None,
            },
        )


@lru_cache()
def get_extraction_staging_service() -> ExtractionStagingService:
    return ExtractionStagingService()
