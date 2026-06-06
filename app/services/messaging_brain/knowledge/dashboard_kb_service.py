from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _parse_json(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return default
    return value


class DashboardKnowledgeService:
    """Scoped-knowledge-backed dashboard KB service."""

    async def count_dashboard_entries(
        self,
        session: AsyncSession,
        tenant_id: UUID,
    ) -> int:
        result = await session.execute(
            text(
                """
                SELECT COUNT(*)
                FROM concierge_scoped_knowledge
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND COALESCE(is_active, TRUE) = TRUE
                  AND scope_type IN ('tenant', 'property', 'property_group')
                """
            ),
            {"tenant_id": str(tenant_id)},
        )
        return int(result.scalar() or 0)

    async def list_dashboard_entries(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        property_ref: Optional[str] = None,
        group_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        params: dict[str, Any] = {"tenant_id": str(tenant_id)}
        filter_sql = ""
        if group_id:
            params["group_id"] = group_id
            filter_sql = """
              AND k.scope_type = 'property_group'
              AND k.scope_target_id = CAST(:group_id AS uuid)
            """
        elif property_ref:
            params["property_ref"] = property_ref
            filter_sql = """
              AND (
                    (k.scope_type = 'tenant' AND :property_ref = '__all_properties__')
                 OR (k.scope_type = 'property' AND (
                        k.scope_target_id::text = :property_ref
                     OR p.property_code = :property_ref
                     OR p.external_id = :property_ref
                 ))
              )
            """

        rows = (
            await session.execute(
                text(
                    f"""
                    SELECT
                        k.knowledge_entry_id,
                        k.scope_type,
                        k.scope_target_id,
                        k.topic_id,
                        k.question_text,
                        k.answer_text,
                        k.tags,
                        k.source,
                        k.metadata,
                        k.version,
                        p.property_code,
                        p.external_id,
                        g.name AS group_name
                    FROM concierge_scoped_knowledge k
                    LEFT JOIN properties p
                      ON k.scope_type = 'property'
                     AND p.id = k.scope_target_id
                     AND p.tenant_id = k.tenant_id
                    LEFT JOIN property_groups g
                      ON k.scope_type = 'property_group'
                     AND g.id = k.scope_target_id
                     AND g.tenant_id = k.tenant_id
                    WHERE k.tenant_id = CAST(:tenant_id AS uuid)
                      AND COALESCE(k.is_active, TRUE) = TRUE
                      AND k.scope_type IN ('tenant', 'property', 'property_group')
                      {filter_sql}
                    ORDER BY
                        CASE WHEN k.scope_type = 'tenant' THEN 0
                             WHEN k.scope_type = 'property_group' THEN 1
                             ELSE 2 END,
                        COALESCE(g.name, p.property_code, p.external_id, ''),
                        k.question_text,
                        k.knowledge_entry_id
                    """
                ),
                params,
            )
        ).fetchall()

        entries: list[dict[str, Any]] = []
        for row in rows:
            metadata = _parse_json(getattr(row, "metadata", None), {})
            if not isinstance(metadata, dict):
                metadata = {}
            tags = _parse_json(getattr(row, "tags", None), [])
            if not isinstance(tags, list):
                tags = []
            topic_id = _normalize_text(getattr(row, "topic_id", ""))
            category = (
                _normalize_text(metadata.get("category"))
                or _normalize_text(topic_id).replace("_", " ").title()
                or "General"
            )
            scope_type_str = str(getattr(row, "scope_type", ""))
            if scope_type_str == "tenant":
                property_label = "All Properties"
                scope_kind = "portfolio"
            elif scope_type_str == "property_group":
                property_label = (
                    _normalize_text(getattr(row, "group_name", ""))
                    or "Unknown Group"
                )
                scope_kind = "neighborhood"
            else:
                property_label = (
                    _normalize_text(getattr(row, "property_code", ""))
                    or _normalize_text(getattr(row, "external_id", ""))
                    or "Unknown Property"
                )
                scope_kind = "property"
            updated_at = metadata.get("updated_at") or metadata.get("created_at")
            entries.append(
                {
                    "id": str(row.knowledge_entry_id),
                    "parent_id": str(row.knowledge_entry_id),
                    "faq_index": 0,
                    "question": _normalize_text(getattr(row, "question_text", "")),
                    "answer": _normalize_text(getattr(row, "answer_text", "")),
                    "confidence": float(metadata.get("confidence") or 0.92),
                    "category": category,
                    "usage_count": int(metadata.get("usage_count") or 0),
                    "property_id": (
                        str(getattr(row, "scope_target_id"))
                        if scope_type_str == "property"
                        else None
                    ),
                    "property_label": property_label,
                    "source": _normalize_text(getattr(row, "source", "")) or "operator_dashboard",
                    "updated_at": updated_at,
                    "topic_id": topic_id or None,
                    "scope_type": scope_type_str,
                    "scope_kind": scope_kind,
                    "tags": [str(tag) for tag in tags if _normalize_text(tag)],
                }
            )
        return entries

    async def create_dashboard_entry(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        question: str,
        answer: str,
        category: str = "General",
        property_id: Optional[str] = None,
        property_external_id: Optional[str] = None,
        property_group_id: Optional[str] = None,
        autocommit: bool = True,
        user_id: Optional[UUID] = None,
    ) -> Dict[str, Any]:
        scope = await self._resolve_scope(
            session=session,
            tenant_id=tenant_id,
            property_id=property_id,
            property_external_id=property_external_id,
            property_group_id=property_group_id,
        )
        metadata = {
            "category": _normalize_text(category) or "General",
            "confidence": 0.92,
            "usage_count": 0,
        }
        # Operator-authored entries: a human wrote it → verified, but no numeric
        # extraction confidence (confidence column stays NULL per brief recommendation).
        now_ts = datetime.now(timezone.utc) if user_id else None
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
                        last_verified_at,
                        verified_by_user_id
                    ) VALUES (
                        CAST(:tenant_id AS uuid),
                        :scope_type,
                        CAST(:scope_target_id AS uuid),
                        :topic_id,
                        :question_text,
                        LOWER(:question_text),
                        :answer_text,
                        CAST(:tags AS jsonb),
                        'operator_dashboard',
                        CAST(:metadata AS jsonb),
                        CAST(:created_by_user_id AS uuid),
                        CAST(:verified_at AS timestamptz),
                        CAST(:verified_by AS uuid)
                    )
                    RETURNING knowledge_entry_id
                    """
                ),
                {
                    "tenant_id": str(tenant_id),
                    "scope_type": scope["scope_type"],
                    "scope_target_id": scope["scope_target_id"],
                    "topic_id": _normalize_text(category).lower().replace(" ", "_") or None,
                    "question_text": _normalize_text(question),
                    "answer_text": _normalize_text(answer),
                    "tags": json.dumps([]),
                    "metadata": json.dumps(metadata),
                    "created_by_user_id": str(user_id) if user_id else None,
                    "verified_at": now_ts,
                    "verified_by": str(user_id) if user_id else None,
                },
            )
        ).fetchone()
        if autocommit:
            await session.commit()
        return {
            "id": str(row.knowledge_entry_id),
            "parent_id": str(row.knowledge_entry_id),
            "faq_index": 0,
            "question": _normalize_text(question),
            "answer": _normalize_text(answer),
            "confidence": 0.92,
            "category": metadata["category"],
            "usage_count": 0,
            "property_id": scope["property_id"],
            "property_label": scope["property_label"],
            "source": "operator_dashboard",
            "updated_at": None,
        }

    async def update_dashboard_entry(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        entry_id: str,
        body: Dict[str, Any],
        user_id: Optional[UUID] = None,
    ) -> bool:
        row = (
            await session.execute(
                text(
                    """
                    SELECT metadata
                    FROM concierge_scoped_knowledge
                    WHERE knowledge_entry_id = CAST(:entry_id AS uuid)
                      AND tenant_id = CAST(:tenant_id AS uuid)
                      AND COALESCE(is_active, TRUE) = TRUE
                    LIMIT 1
                    """
                ),
                {"entry_id": entry_id, "tenant_id": str(tenant_id)},
            )
        ).fetchone()
        if not row:
            return False
        metadata = _parse_json(getattr(row, "metadata", None), {})
        if not isinstance(metadata, dict):
            metadata = {}
        if "category" in body:
            metadata["category"] = _normalize_text(body["category"]) or "General"
        # A human edited this entry — advance verified timestamp.
        now_ts = datetime.now(timezone.utc) if user_id else None
        await session.execute(
            text(
                """
                UPDATE concierge_scoped_knowledge
                SET question_text = COALESCE(:question_text, question_text),
                    answer_text = COALESCE(:answer_text, answer_text),
                    metadata = CAST(:metadata AS jsonb),
                    updated_at = NOW(),
                    last_verified_at = COALESCE(CAST(:verified_at AS timestamptz), last_verified_at),
                    verified_by_user_id = COALESCE(CAST(:verified_by AS uuid), verified_by_user_id)
                WHERE knowledge_entry_id = CAST(:entry_id AS uuid)
                  AND tenant_id = CAST(:tenant_id AS uuid)
                """
            ),
            {
                "entry_id": entry_id,
                "tenant_id": str(tenant_id),
                "question_text": _normalize_text(body["question"]) if "question" in body else None,
                "answer_text": _normalize_text(body["answer"]) if "answer" in body else None,
                "metadata": json.dumps(metadata),
                "verified_at": now_ts,
                "verified_by": str(user_id) if user_id else None,
            },
        )
        await session.commit()
        return True

    async def delete_dashboard_entry(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        entry_id: str,
    ) -> bool:
        result = await session.execute(
            text(
                """
                UPDATE concierge_scoped_knowledge
                SET is_active = FALSE, updated_at = NOW()
                WHERE knowledge_entry_id = CAST(:entry_id AS uuid)
                  AND tenant_id = CAST(:tenant_id AS uuid)
                """
            ),
            {"entry_id": entry_id, "tenant_id": str(tenant_id)},
        )
        await session.commit()
        return bool(result.rowcount)

    async def test_dashboard_question(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        question: str,
    ) -> Dict[str, Any]:
        entries = await self.list_dashboard_entries(session, tenant_id)
        q_words = {w for w in question.split() if len(w) > 2}
        best = None
        best_score = 0.0
        for item in entries:
            q_text = str(item.get("question") or "").lower()
            q_text_words = {w for w in q_text.split() if len(w) > 2}
            if not q_text_words:
                continue
            overlap = len(q_words & q_text_words)
            union = len(q_words | q_text_words)
            score = (overlap / union) if union else 0.0
            if question in q_text or q_text in question:
                score = max(score, 0.8)
            if score > best_score:
                best_score = score
                best = item
        return {"best": best, "score": best_score}

    async def _resolve_scope(
        self,
        *,
        session: AsyncSession,
        tenant_id: UUID,
        property_id: Optional[str],
        property_external_id: Optional[str],
        property_group_id: Optional[str] = None,
    ) -> Dict[str, Optional[str]]:
        if property_id:
            row = (
                await session.execute(
                    text(
                        """
                        SELECT id, property_code, external_id
                        FROM properties
                        WHERE tenant_id = CAST(:tenant_id AS uuid)
                          AND id = CAST(:property_id AS uuid)
                        LIMIT 1
                        """
                    ),
                    {
                        "tenant_id": str(tenant_id),
                        "property_id": property_id,
                    },
                )
            ).fetchone()
            if row:
                return {
                    "scope_type": "property",
                    "scope_target_id": str(row.id),
                    "property_id": str(row.id),
                    "property_label": _normalize_text(getattr(row, "property_code", "")) or _normalize_text(getattr(row, "external_id", "")) or "Unknown Property",
                }

        if property_external_id and property_external_id != "__all_properties__":
            row = (
                await session.execute(
                    text(
                        """
                        SELECT id, property_code, external_id
                        FROM properties
                        WHERE tenant_id = CAST(:tenant_id AS uuid)
                          AND (property_code = :property_external_id OR external_id = :property_external_id)
                        LIMIT 1
                        """
                    ),
                    {
                        "tenant_id": str(tenant_id),
                        "property_external_id": property_external_id,
                    },
                )
            ).fetchone()
            if row:
                return {
                    "scope_type": "property",
                    "scope_target_id": str(row.id),
                    "property_id": str(row.id),
                    "property_label": _normalize_text(getattr(row, "property_code", "")) or _normalize_text(getattr(row, "external_id", "")) or property_external_id,
                }

        if property_group_id:
            row = (
                await session.execute(
                    text(
                        """
                        SELECT id, name
                        FROM property_groups
                        WHERE tenant_id = CAST(:tenant_id AS uuid)
                          AND id = CAST(:group_id AS uuid)
                        LIMIT 1
                        """
                    ),
                    {
                        "tenant_id": str(tenant_id),
                        "group_id": property_group_id,
                    },
                )
            ).fetchone()
            if row:
                return {
                    "scope_type": "property_group",
                    "scope_target_id": str(row.id),
                    "property_id": None,
                    "property_label": _normalize_text(getattr(row, "name", "")) or "Unknown Group",
                    "scope_kind": "neighborhood",
                }

        return {
            "scope_type": "tenant",
            "scope_target_id": str(tenant_id),
            "property_id": None,
            "property_label": "All Properties",
            "scope_kind": "portfolio",
        }


_DASHBOARD_KB_SERVICE = DashboardKnowledgeService()


def get_dashboard_kb_service() -> DashboardKnowledgeService:
    return _DASHBOARD_KB_SERVICE
