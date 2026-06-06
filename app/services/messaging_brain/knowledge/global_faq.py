"""Brain-owned canonical global FAQ writer/reader.

Owns the `concierge_global_faq` table. Global FAQ entries are
tenant-scoped (not property-scoped) — they apply across every property
the operator manages.

Public surface:
  upsert_global_faq — write or update one global FAQ entry, keyed by
                      tenant + normalized question
  list_global_faq   — return all global FAQ entries for a tenant

Lifted from `ConciergeKnowledgeService.upsert_global_faq` and
`ConciergeKnowledgeService.list_global_faq` in
`app/services/concierge/knowledge_service.py`, with the class wrapping
removed. The logic is unchanged — only the canonical table
(`concierge_global_faq`) is touched, and that table is staying.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.concierge_knowledge import ConciergeGlobalFAQModel

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Question-key normalization
#
# Same canonical hash used by gap_recorder, scoped_knowledge_service, and
# the retire_concierge_knowledge.py migration script. Inlined so this
# module has no dependency on knowledge_service.py.
# ---------------------------------------------------------------------------


def _normalize_message_tokens(text: str) -> set[str]:
    import re

    stopwords = {
        "the", "and", "for", "with", "that", "this", "from", "your", "you", "are",
        "can", "could", "would", "should", "what", "when", "where", "which", "who",
        "how", "why", "does", "did", "have", "has", "had", "our", "about", "into",
        "them", "they", "will", "just", "need", "any", "all", "get", "let", "know",
    }
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {w for w in words if len(w) > 2 and w not in stopwords}


def _normalize_question_key(text: str) -> str:
    return " ".join(sorted(_normalize_message_tokens(text)))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def upsert_global_faq(
    session: AsyncSession,
    tenant_id: UUID,
    question_text: str,
    answer_text: str,
    source: str = "manual",
    tags: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Insert or update a tenant-global FAQ entry.

    Match is by normalized question_key under the same tenant. If a match
    exists, its answer/source/tags/metadata are updated in place. If not,
    a new row is inserted.

    Raises ValueError if question_text or answer_text are empty.
    """
    question = (question_text or "").strip()
    answer = (answer_text or "").strip()
    if not question or not answer:
        raise ValueError("question_text and answer_text are required")

    key = _normalize_question_key(question)
    row = (
        await session.execute(
            select(ConciergeGlobalFAQModel).where(
                ConciergeGlobalFAQModel.tenant_id == tenant_id,
                ConciergeGlobalFAQModel.question_key == key,
            )
        )
    ).scalar_one_or_none()

    if row:
        row.question_text = question
        row.answer_text = answer
        row.source = source
        row.tags = tags or row.tags or []
        row.metadata_json = metadata or row.metadata_json or {}
    else:
        row = ConciergeGlobalFAQModel(
            tenant_id=tenant_id,
            question_text=question,
            question_key=key,
            answer_text=answer,
            source=source,
            tags=tags or [],
            metadata_json=metadata or {},
        )
        session.add(row)

    await session.commit()
    await session.refresh(row)
    return {
        "faq_id": str(row.faq_id),
        "question_text": row.question_text,
        "answer_text": row.answer_text,
        "source": row.source,
        "tags": row.tags or [],
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


async def list_global_faq(
    session: AsyncSession,
    tenant_id: UUID,
    limit: int = 200,
) -> List[Dict[str, Any]]:
    """Return all global FAQ entries for a tenant, newest-updated first.

    `limit` is clamped to [1, 1000].
    """
    rows = list(
        (
            await session.execute(
                select(ConciergeGlobalFAQModel)
                .where(ConciergeGlobalFAQModel.tenant_id == tenant_id)
                .order_by(ConciergeGlobalFAQModel.updated_at.desc())
                .limit(max(1, min(limit, 1000)))
            )
        ).scalars()
    )
    return [
        {
            "faq_id": str(r.faq_id),
            "question_text": r.question_text,
            "answer_text": r.answer_text,
            "source": r.source,
            "tags": r.tags or [],
            "created_at": r.created_at.isoformat(),
            "updated_at": r.updated_at.isoformat(),
        }
        for r in rows
    ]


__all__ = ["upsert_global_faq", "list_global_faq"]
