from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from app.services.agents.knowledge_curator_agent import KnowledgeCuratorAgent, KnowledgeGap


class _FetchOneResult:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _FetchAllResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


@pytest.mark.asyncio
async def test_curate_gaps_clusters_and_creates_single_draft() -> None:
    db = AsyncMock()
    agent = KnowledgeCuratorAgent()
    gaps = [
        KnowledgeGap(
            gap_id="gap-1",
            tenant_id="11111111-1111-1111-1111-111111111111",
            question="Do you have beach chairs at the house?",
            session_token="",
            property_code="100SL2D",
            created_at=datetime.utcnow(),
            count=2,
        ),
        KnowledgeGap(
            gap_id="gap-2",
            tenant_id="11111111-1111-1111-1111-111111111111",
            question="Are beach chairs provided at the house?",
            session_token="",
            property_code="100SL2D",
            created_at=datetime.utcnow(),
            count=1,
        ),
        KnowledgeGap(
            gap_id="gap-3",
            tenant_id="11111111-1111-1111-1111-111111111111",
            question="What is the wifi password?",
            session_token="",
            property_code="100SL2D",
            created_at=datetime.utcnow(),
            count=1,
        ),
    ]
    agent._load_gaps = AsyncMock(return_value=gaps)
    agent._persist_draft = AsyncMock()
    agent._find_existing_draft = AsyncMock(return_value=False)

    report = await agent.curate_gaps(
        db,
        tenant_id="11111111-1111-1111-1111-111111111111",
        property_code="100SL2D",
    )

    assert report.gaps_scanned == 3
    assert report.drafts_created == 1
    assert report.drafts_already_pending == 0
    agent._persist_draft.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_pending_drafts_scopes_by_tenant() -> None:
    db = AsyncMock()
    db.execute.return_value = _FetchAllResult([
        type(
            "Row",
            (),
            {
                "draft_id": "draft_123",
                "property_code": "100SL2D",
                "question": "Do you have beach chairs?",
                "answer_hint": "[Yes/No]",
                "occurrence_count": 3,
                "created_at": datetime(2026, 5, 18, 10, 0, 0),
                "gap_ids": ["gap-1", "gap-2"],
            },
        )()
    ])

    drafts = await KnowledgeCuratorAgent().get_pending_drafts(
        db,
        tenant_id="11111111-1111-1111-1111-111111111111",
        property_code="100SL2D",
    )

    assert len(drafts) == 1
    sql = str(db.execute.await_args.args[0])
    assert "tenant_id = CAST(:tenant_id AS uuid)" in sql


@pytest.mark.asyncio
async def test_approve_draft_indexes_and_closes() -> None:
    db = AsyncMock()
    agent = KnowledgeCuratorAgent()
    draft = type(
        "Draft",
        (),
        {
            "tenant_id": "11111111-1111-1111-1111-111111111111",
            "answer_hint": "Yes, four chairs are in the garage.",
            "question": "Do you have beach chairs?",
            "property_code": "100SL2D",
            "gap_ids": ["gap-1", "gap-2"],
        },
    )()
    agent._load_draft = AsyncMock(return_value=draft)
    agent._index_faq = AsyncMock(return_value="doc-123")
    agent._close_draft = AsyncMock()
    agent._mark_gaps_resolved = AsyncMock()

    doc_id = await agent.approve_draft(
        db,
        tenant_id="11111111-1111-1111-1111-111111111111",
        draft_id="draft_123",
        operator="ops@example.com",
    )

    assert doc_id == "doc-123"
    agent._close_draft.assert_awaited_once()
    agent._mark_gaps_resolved.assert_awaited_once_with(db, ["gap-1", "gap-2"])
