from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.ops_auth import require_ops_access
from app.api.dependencies.request_tenant import resolve_request_tenant_id
from app.db.session import get_async_session
from app.services.agents.healer_agent import get_healer_agent


router = APIRouter(
    prefix="/healer",
    tags=["Healer"],
    dependencies=[Depends(require_ops_access)],
)


class HealerProposalOut(BaseModel):
    proposal_id: str
    proposal_kind: str
    signal_source: str
    summary: str
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    proposed_change: dict[str, Any] = Field(default_factory=dict)
    status: str
    confidence: float
    cluster_size: int
    created_at: datetime
    reviewed_at: datetime | None = None
    reviewed_by: str | None = None
    review_notes: str | None = None


def _require_tenant(request: Request) -> UUID:
    tenant_id = resolve_request_tenant_id(request)
    if tenant_id is None:
        raise HTTPException(status_code=401, detail="Authenticated tenant context required.")
    return tenant_id


@router.get("/proposals", response_model=list[HealerProposalOut])
async def list_pending_proposals(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
) -> list[HealerProposalOut]:
    tenant_id = _require_tenant(request)
    rows = await get_healer_agent().list_pending_proposals(db, tenant_id)
    return [HealerProposalOut.model_validate({**row, "proposal_id": str(row["proposal_id"])}) for row in rows]


@router.get("/proposals/canonical-aliases", response_model=list[HealerProposalOut])
async def list_pending_canonical_alias_reviews(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
) -> list[HealerProposalOut]:
    tenant_id = _require_tenant(request)
    rows = (
        await db.execute(
            text(
                """
                SELECT
                    review_id,
                    ref_value,
                    canonical_property_code,
                    confidence,
                    candidate_payload,
                    metadata,
                    created_at
                FROM canonical_property_link_reviews
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND status = 'pending'
                ORDER BY created_at DESC
                """
            ),
            {"tenant_id": str(tenant_id)},
        )
    ).mappings().all()
    return [
        HealerProposalOut(
            proposal_id=str(row["review_id"]),
            proposal_kind="property_alias_suggestion",
            signal_source="canonical_property_link_review",
            summary=(
                f"Pending canonical alias review for {row.get('ref_value') or ''}"
                f"{' → ' + str(row.get('canonical_property_code')) if row.get('canonical_property_code') else ''}"
            ),
            evidence=list(row.get("candidate_payload") or []),
            proposed_change={
                "kind": "property_alias_suggestion",
                "extracted_mention": str(row.get("ref_value") or ""),
                "canonical_property_code": str(row.get("canonical_property_code") or ""),
            },
            status="pending",
            confidence=float(row.get("confidence") or 0.0),
            cluster_size=max(1, len(list(row.get("candidate_payload") or []))),
            created_at=row["created_at"],
            reviewed_at=None,
            reviewed_by=None,
            review_notes=None,
        )
        for row in rows
    ]
