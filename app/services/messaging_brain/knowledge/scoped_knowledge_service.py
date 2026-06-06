from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
from typing import Any, Dict, Iterable, Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.knowledge_helpers import (
    flush_quietly as _flush_quietly,
    normalize_question_key as _normalize_question_key,
)
from app.services.messaging_brain.knowledge.topic_registry import TOPIC_REGISTRY


@dataclass
class ScopedKnowledgeWriteResult:
    status: str
    knowledge_entry_id: UUID
    scope_type: str
    scope_target_id: UUID
    topic_id: Optional[str]
    question_text: str
    question_key: str
    version: int
    previous_version_archived: bool


@dataclass(frozen=True)
class ScopedKnowledgeEntry:
    knowledge_entry_id: Optional[UUID]
    tenant_id: UUID
    scope_type: str
    scope_target_id: UUID
    topic_id: Optional[str]
    question_text: str
    question_key: str
    answer_text: str
    tags: list[str]
    source: str
    metadata: Dict[str, Any]
    created_by_user_id: Optional[str]
    version: int
    is_active: bool = True


@dataclass(frozen=True)
class ScopedKnowledgeProvenance:
    entry: ScopedKnowledgeEntry
    scope_origin: str


@dataclass(frozen=True)
class EffectiveKnowledgeResult:
    effective_by_topic: Dict[str, ScopedKnowledgeEntry]
    effective_freeform_faq: list[ScopedKnowledgeEntry]
    all_entries_with_provenance: list[ScopedKnowledgeProvenance]
    retrieval_source: str = "unified"


def _coerce_uuid(value: UUID | str) -> UUID:
    if isinstance(value, UUID):
        return value
    return UUID(str(value))


def _coerce_json(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return default
    return value


def _normalize_text(value: str) -> str:
    return " ".join((value or "").strip().split())


def _compute_question_key(question_text: str) -> str:
    normalized = _normalize_question_key(question_text)
    if normalized:
        return normalized
    return _normalize_text(question_text).lower()


def _normalize_tags(tags: Optional[Iterable[str]], topic_id: Optional[str]) -> list[str]:
    values: list[str] = []
    for item in tags or ():
        tag = _normalize_text(str(item))
        if tag:
            values.append(tag)
    if topic_id and topic_id not in values:
        values.append(topic_id)
    return list(dict.fromkeys(values))


def _entry_from_row(row: Any) -> ScopedKnowledgeEntry:
    metadata = _coerce_json(getattr(row, "metadata", None), {})
    tags = _coerce_json(getattr(row, "tags", None), [])
    return ScopedKnowledgeEntry(
        knowledge_entry_id=_coerce_uuid(row.knowledge_entry_id) if getattr(row, "knowledge_entry_id", None) else None,
        tenant_id=_coerce_uuid(row.tenant_id),
        scope_type=str(row.scope_type),
        scope_target_id=_coerce_uuid(row.scope_target_id),
        topic_id=(str(row.topic_id).strip() if getattr(row, "topic_id", None) not in (None, "") else None),
        question_text=_normalize_text(getattr(row, "question_text", "")),
        question_key=_normalize_text(getattr(row, "question_key", "")),
        answer_text=_normalize_text(getattr(row, "answer_text", "")),
        tags=[str(tag) for tag in tags if str(tag).strip()],
        source=_normalize_text(getattr(row, "source", "")),
        metadata=metadata if isinstance(metadata, dict) else {},
        created_by_user_id=str(getattr(row, "created_by_user_id", "")) or None,
        version=int(getattr(row, "version", 1) or 1),
        is_active=bool(getattr(row, "is_active", True)),
    )


def project_to_legacy_concierge_knowledge_shape(
    effective_result: EffectiveKnowledgeResult,
) -> dict[str, Any]:
    faq: list[dict[str, Any]] = []
    facts: dict[str, str] = {}

    for topic_id, entry in effective_result.effective_by_topic.items():
        if entry.answer_text:
            facts[topic_id] = entry.answer_text
        faq.append(
            {
                "question": entry.question_text,
                "answer": entry.answer_text,
                "topic": topic_id,
                "tags": list(dict.fromkeys([*entry.tags, topic_id])),
                "source": entry.source,
                "scope_type": entry.scope_type,
                "metadata": entry.metadata,
            }
        )

    for entry in effective_result.effective_freeform_faq:
        faq.append(
            {
                "question": entry.question_text,
                "answer": entry.answer_text,
                "topic": entry.topic_id,
                "tags": list(entry.tags),
                "source": entry.source,
                "scope_type": entry.scope_type,
                "metadata": entry.metadata,
            }
        )

    return {
        "facts": facts,
        "sections": {},
        "faq": faq,
    }


def _build_metadata(
    *,
    prior_metadata: Optional[Dict[str, Any]],
    input_metadata: Dict[str, Any],
    scope_type: str,
    scope_target_id: UUID,
    topic_id: Optional[str],
    source: str,
    tags: list[str],
    user_id: UUID,
    created_at: str,
    updated_at: str,
    version: int,
) -> Dict[str, Any]:
    merged: Dict[str, Any] = dict(prior_metadata or {})
    merged.update(input_metadata)
    merged["scope_type"] = scope_type
    merged["scope_target_id"] = str(scope_target_id)
    merged["topic_id"] = topic_id
    merged["source"] = source
    merged["tags"] = tags
    merged["created_by_user_id"] = str(user_id)
    merged["created_at"] = created_at
    merged["updated_at"] = updated_at
    merged["version"] = version
    return merged


class ScopedKnowledgeService:
    _ALLOWED_SCOPE_TYPES = {"property", "tenant", "property_group"}

    async def get_effective_knowledge_for_property(
        self,
        session: AsyncSession,
        tenant_id: UUID | str,
        property_id: UUID | str,
    ) -> EffectiveKnowledgeResult:
        tenant_uuid = _coerce_uuid(tenant_id)
        property_uuid = _coerce_uuid(property_id)
        tenant_entries = await self._load_entries_for_scope(
            session=session,
            tenant_id=tenant_uuid,
            scope_type="tenant",
            scope_target_id=tenant_uuid,
        )
        group_ids = await self._load_group_ids_for_property(
            session=session,
            tenant_id=tenant_uuid,
            property_id=property_uuid,
        )
        group_entries_by_group: Dict[UUID, list[ScopedKnowledgeEntry]] = {}
        for group_id in group_ids:
            try:
                group_entries_by_group[group_id] = await self._load_entries_for_scope(
                    session=session,
                    tenant_id=tenant_uuid,
                    scope_type="property_group",
                    scope_target_id=group_id,
                )
            except Exception as exc:  # noqa: BLE001
                logging.getLogger(__name__).warning(
                    "[ScopedKnowledgeService] group entries load failed: tenant=%s group=%s error=%s",
                    tenant_uuid,
                    group_id,
                    exc,
                    exc_info=True,
                )
        property_entries = await self._load_entries_for_scope(
            session=session,
            tenant_id=tenant_uuid,
            scope_type="property",
            scope_target_id=property_uuid,
        )

        effective_by_topic: Dict[str, ScopedKnowledgeEntry] = {}
        all_entries_with_provenance: list[ScopedKnowledgeProvenance] = []
        tenant_freeform: list[ScopedKnowledgeEntry] = []

        for entry in tenant_entries:
            all_entries_with_provenance.append(
                ScopedKnowledgeProvenance(entry=entry, scope_origin="tenant")
            )
            if entry.topic_id:
                effective_by_topic[entry.topic_id] = entry
            else:
                tenant_freeform.append(entry)

        group_freeform: list[ScopedKnowledgeEntry] = []
        for group_id in sorted(group_entries_by_group.keys(), key=str):
            for entry in group_entries_by_group[group_id]:
                all_entries_with_provenance.append(
                    ScopedKnowledgeProvenance(entry=entry, scope_origin="property_group")
                )
                if entry.topic_id:
                    effective_by_topic[entry.topic_id] = entry
                else:
                    group_freeform.append(entry)

        property_freeform: list[ScopedKnowledgeEntry] = []
        for entry in property_entries:
            all_entries_with_provenance.append(
                ScopedKnowledgeProvenance(entry=entry, scope_origin="property")
            )
            if entry.topic_id:
                effective_by_topic[entry.topic_id] = entry
            else:
                property_freeform.append(entry)

        return EffectiveKnowledgeResult(
            effective_by_topic=effective_by_topic,
            effective_freeform_faq=[*property_freeform, *group_freeform, *tenant_freeform],
            all_entries_with_provenance=all_entries_with_provenance,
            retrieval_source="unified",
        )

    async def write_scoped_knowledge(
        self,
        session: AsyncSession,
        tenant_id: UUID | str,
        user_id: UUID | str,
        scope_type: str,
        scope_target_id: UUID | str,
        topic_id: Optional[str],
        question_text: str,
        answer_text: str,
        tags: Optional[Iterable[str]],
        source: str,
        metadata: Optional[Dict[str, Any]],
        *,
        confidence: Optional[float] = None,
        verified_at: Optional[datetime] = None,
        verified_by_user_id: Optional[UUID | str] = None,
    ) -> ScopedKnowledgeWriteResult:
        tenant_uuid = _coerce_uuid(tenant_id)
        user_uuid = _coerce_uuid(user_id)
        target_uuid = _coerce_uuid(scope_target_id)

        normalized_scope = _normalize_text(scope_type).lower()
        if normalized_scope not in self._ALLOWED_SCOPE_TYPES:
            raise ValueError(f"unsupported scope_type: {scope_type}")

        normalized_topic = _normalize_text(topic_id or "") or None
        if normalized_topic and normalized_topic not in TOPIC_REGISTRY:
            raise ValueError(f"unknown topic_id: {topic_id}")

        normalized_question = _normalize_text(question_text)
        if not normalized_question:
            raise ValueError("question_text is required")

        normalized_answer = _normalize_text(answer_text)
        if not normalized_answer:
            raise ValueError("answer_text is required")

        normalized_source = _normalize_text(source)
        if not normalized_source:
            raise ValueError("source is required")

        question_key = _compute_question_key(normalized_question)
        if not question_key:
            raise ValueError("question_text must yield a non-empty question_key")

        normalized_tags = _normalize_tags(tags, normalized_topic)
        metadata_dict = dict(metadata or {})

        # Provenance columns — callers pass these explicitly; the service does not infer them.
        # confidence: numeric 0-1 extracted or human-assigned. Clamp to [0,1].
        norm_confidence: Optional[float] = (
            max(0.0, min(1.0, float(confidence))) if confidence is not None else None
        )
        # verified_at/by: set ONLY when a human approved/authored. Never inferred.
        verified_by_uuid: Optional[UUID] = (
            _coerce_uuid(verified_by_user_id) if verified_by_user_id is not None else None
        )

        lock_key = f"{tenant_uuid}:{normalized_scope}:{target_uuid}:{normalized_topic or question_key}"
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
            {"lock_key": lock_key},
        )

        existing = await self._fetch_existing_entry(
            session=session,
            tenant_id=tenant_uuid,
            scope_type=normalized_scope,
            scope_target_id=target_uuid,
            topic_id=normalized_topic,
            question_key=question_key,
        )

        now_iso = datetime.now(timezone.utc).isoformat()

        if existing:
            previous_metadata = _coerce_json(existing.metadata, {})
            previous_version = int(existing.version or 1)
            created_at = str(
                previous_metadata.get("created_at")
                or (existing.created_at.isoformat() if existing.created_at else now_iso)
            )
            next_version = previous_version + 1
            new_metadata = _build_metadata(
                prior_metadata=previous_metadata,
                input_metadata=metadata_dict,
                scope_type=normalized_scope,
                scope_target_id=target_uuid,
                topic_id=normalized_topic,
                source=normalized_source,
                tags=normalized_tags,
                user_id=user_uuid,
                created_at=created_at,
                updated_at=now_iso,
                version=next_version,
            )
            await session.execute(
                text(
                    """
                    INSERT INTO concierge_scoped_knowledge_history (
                        knowledge_entry_id,
                        tenant_id,
                        version,
                        previous_question_text,
                        previous_answer_text,
                        previous_metadata,
                        changed_by_user_id,
                        change_type
                    ) VALUES (
                        CAST(:knowledge_entry_id AS uuid),
                        CAST(:tenant_id AS uuid),
                        :version,
                        :previous_question_text,
                        :previous_answer_text,
                        CAST(:previous_metadata AS jsonb),
                        CAST(:changed_by_user_id AS uuid),
                        'updated'
                    )
                    """
                ),
                {
                    "knowledge_entry_id": str(existing.knowledge_entry_id),
                    "tenant_id": str(tenant_uuid),
                    "version": previous_version,
                    "previous_question_text": existing.question_text,
                    "previous_answer_text": existing.answer_text,
                    "previous_metadata": json.dumps(previous_metadata),
                    "changed_by_user_id": str(user_uuid),
                },
            )
            await session.execute(
                text(
                    """
                    UPDATE concierge_scoped_knowledge
                    SET topic_id = :topic_id,
                        question_text = :question_text,
                        question_key = :question_key,
                        answer_text = :answer_text,
                        tags = CAST(:tags AS jsonb),
                        source = :source,
                        metadata = CAST(:metadata AS jsonb),
                        created_by_user_id = COALESCE(created_by_user_id, CAST(:created_by_user_id AS uuid)),
                        updated_at = NOW(),
                        version = :version,
                        confidence = COALESCE(CAST(:confidence AS numeric), confidence),
                        last_verified_at = COALESCE(CAST(:verified_at AS timestamptz), last_verified_at),
                        verified_by_user_id = COALESCE(CAST(:verified_by AS uuid), verified_by_user_id)
                    WHERE knowledge_entry_id = CAST(:knowledge_entry_id AS uuid)
                    """
                ),
                {
                    "knowledge_entry_id": str(existing.knowledge_entry_id),
                    "topic_id": normalized_topic,
                    "question_text": normalized_question,
                    "question_key": question_key,
                    "answer_text": normalized_answer,
                    "tags": json.dumps(normalized_tags),
                    "source": normalized_source,
                    "metadata": json.dumps(new_metadata),
                    "created_by_user_id": str(user_uuid),
                    "version": next_version,
                    "confidence": norm_confidence,
                    "verified_at": verified_at if verified_at else None,
                    "verified_by": str(verified_by_uuid) if verified_by_uuid else None,
                },
            )
            await _flush_quietly(session)
            return ScopedKnowledgeWriteResult(
                status="updated",
                knowledge_entry_id=_coerce_uuid(existing.knowledge_entry_id),
                scope_type=normalized_scope,
                scope_target_id=target_uuid,
                topic_id=normalized_topic,
                question_text=normalized_question,
                question_key=question_key,
                version=next_version,
                previous_version_archived=True,
            )

        new_metadata = _build_metadata(
            prior_metadata=None,
            input_metadata=metadata_dict,
            scope_type=normalized_scope,
            scope_target_id=target_uuid,
            topic_id=normalized_topic,
            source=normalized_source,
            tags=normalized_tags,
            user_id=user_uuid,
            created_at=now_iso,
            updated_at=now_iso,
            version=1,
        )
        row = (
            await session.execute(
                text(
                    """
                    INSERT INTO concierge_scoped_knowledge (
                        tenant_id,
                        scope_type,
                        scope_target_id,
                        topic_id,
                        question_text,
                        question_key,
                        answer_text,
                        tags,
                        source,
                        metadata,
                        created_by_user_id,
                        confidence,
                        last_verified_at,
                        verified_by_user_id
                    ) VALUES (
                        CAST(:tenant_id AS uuid),
                        :scope_type,
                        CAST(:scope_target_id AS uuid),
                        :topic_id,
                        :question_text,
                        :question_key,
                        :answer_text,
                        CAST(:tags AS jsonb),
                        :source,
                        CAST(:metadata AS jsonb),
                        CAST(:created_by_user_id AS uuid),
                        CAST(:confidence AS numeric),
                        CAST(:verified_at AS timestamptz),
                        CAST(:verified_by AS uuid)
                    )
                    RETURNING knowledge_entry_id
                    """
                ),
                {
                    "tenant_id": str(tenant_uuid),
                    "scope_type": normalized_scope,
                    "scope_target_id": str(target_uuid),
                    "topic_id": normalized_topic,
                    "question_text": normalized_question,
                    "question_key": question_key,
                    "answer_text": normalized_answer,
                    "tags": json.dumps(normalized_tags),
                    "source": normalized_source,
                    "metadata": json.dumps(new_metadata),
                    "created_by_user_id": str(user_uuid),
                    "confidence": norm_confidence,
                    "verified_at": verified_at if verified_at else None,
                    "verified_by": str(verified_by_uuid) if verified_by_uuid else None,
                },
            )
        ).fetchone()
        knowledge_entry_id = _coerce_uuid(row.knowledge_entry_id)
        await session.execute(
            text(
                """
                INSERT INTO concierge_scoped_knowledge_history (
                    knowledge_entry_id,
                    tenant_id,
                    version,
                    previous_question_text,
                    previous_answer_text,
                    previous_metadata,
                    changed_by_user_id,
                    change_type
                ) VALUES (
                    CAST(:knowledge_entry_id AS uuid),
                    CAST(:tenant_id AS uuid),
                    1,
                    NULL,
                    NULL,
                    NULL,
                    CAST(:changed_by_user_id AS uuid),
                    'created'
                )
                """
            ),
            {
                "knowledge_entry_id": str(knowledge_entry_id),
                "tenant_id": str(tenant_uuid),
                "changed_by_user_id": str(user_uuid),
            },
        )
        await _flush_quietly(session)
        return ScopedKnowledgeWriteResult(
            status="created",
            knowledge_entry_id=knowledge_entry_id,
            scope_type=normalized_scope,
            scope_target_id=target_uuid,
            topic_id=normalized_topic,
            question_text=normalized_question,
            question_key=question_key,
            version=1,
            previous_version_archived=False,
        )

    async def _fetch_existing_entry(
        self,
        *,
        session: AsyncSession,
        tenant_id: UUID,
        scope_type: str,
        scope_target_id: UUID,
        topic_id: Optional[str],
        question_key: str,
    ):
        if topic_id:
            sql = text(
                """
                SELECT knowledge_entry_id, topic_id, question_text, question_key,
                       answer_text, metadata, version, created_at
                FROM concierge_scoped_knowledge
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND scope_type = :scope_type
                  AND scope_target_id = CAST(:scope_target_id AS uuid)
                  AND topic_id = :topic_id
                LIMIT 1
                """
            )
            params = {
                "tenant_id": str(tenant_id),
                "scope_type": scope_type,
                "scope_target_id": str(scope_target_id),
                "topic_id": topic_id,
            }
        else:
            sql = text(
                """
                SELECT knowledge_entry_id, topic_id, question_text, question_key,
                       answer_text, metadata, version, created_at
                FROM concierge_scoped_knowledge
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND scope_type = :scope_type
                  AND scope_target_id = CAST(:scope_target_id AS uuid)
                  AND topic_id IS NULL
                  AND question_key = :question_key
                LIMIT 1
                """
            )
            params = {
                "tenant_id": str(tenant_id),
                "scope_type": scope_type,
                "scope_target_id": str(scope_target_id),
                "question_key": question_key,
            }
        return (await session.execute(sql, params)).fetchone()

    async def _load_entries_for_scope(
        self,
        *,
        session: AsyncSession,
        tenant_id: UUID,
        scope_type: str,
        scope_target_id: UUID,
    ) -> list[ScopedKnowledgeEntry]:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT knowledge_entry_id,
                           tenant_id,
                           scope_type,
                           scope_target_id,
                           topic_id,
                           question_text,
                           question_key,
                           answer_text,
                           tags,
                           source,
                           metadata,
                           created_by_user_id,
                           version,
                           is_active
                    FROM concierge_scoped_knowledge
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                      AND scope_type = :scope_type
                      AND scope_target_id = CAST(:scope_target_id AS uuid)
                      AND COALESCE(is_active, TRUE) = TRUE
                    ORDER BY CASE WHEN topic_id IS NULL THEN 1 ELSE 0 END,
                             question_text ASC,
                             knowledge_entry_id ASC
                    """
                ),
                {
                    "tenant_id": str(tenant_id),
                    "scope_type": scope_type,
                    "scope_target_id": str(scope_target_id),
                },
            )
        ).fetchall()
        return [
            entry
            for entry in (_entry_from_row(row) for row in rows)
            if entry.is_active
        ]

    async def _load_group_ids_for_property(
        self,
        *,
        session: AsyncSession,
        tenant_id: UUID,
        property_id: UUID,
    ) -> list[UUID]:
        """Return active property-group memberships for the property."""
        try:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT m.property_group_id
                        FROM property_group_memberships m
                        JOIN property_groups g ON g.id = m.property_group_id
                        WHERE m.tenant_id = CAST(:tenant_id AS uuid)
                          AND m.property_id = CAST(:property_id AS uuid)
                          AND COALESCE(g.is_active, TRUE) = TRUE
                        ORDER BY m.property_group_id ASC
                        """
                    ),
                    {
                        "tenant_id": str(tenant_id),
                        "property_id": str(property_id),
                    },
                )
            ).fetchall()
            group_ids: list[UUID] = []
            for row in rows:
                if hasattr(row, "property_group_id"):
                    raw_group_id = row.property_group_id
                elif isinstance(row, dict):
                    raw_group_id = row.get("property_group_id")
                else:
                    raw_group_id = row[0]
                group_ids.append(_coerce_uuid(raw_group_id))
            return group_ids
        except Exception as exc:  # noqa: BLE001
            logging.getLogger(__name__).warning(
                "[ScopedKnowledgeService] group membership lookup failed: tenant=%s property=%s error=%s",
                tenant_id,
                property_id,
                exc,
                exc_info=True,
            )
            return []

_SCOPED_KNOWLEDGE_SERVICE = ScopedKnowledgeService()


def get_scoped_knowledge_service() -> ScopedKnowledgeService:
    return _SCOPED_KNOWLEDGE_SERVICE
