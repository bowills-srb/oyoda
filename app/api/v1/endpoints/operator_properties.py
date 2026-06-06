"""
Operator portfolio reconciliation endpoints.

This endpoint is the canonical replacement for the legacy /knowledge/index/*
routes. Operators declare the current portfolio and the API reconciles that
declaration against properties plus knowledge_embeddings in one idempotent flow.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.request_tenant import resolve_request_tenant_id
from app.db.session import get_async_session
from app.services.concierge.guidebook_ingest_service import (
    GuidebookFetchStop,
    get_guidebook_ingest_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/operator/properties",
    tags=["Operator Portfolio"],
)


def _require_tenant(request: Request) -> UUID:
    """Require canonical tenant scope from the caller's auth context."""
    tenant_id = resolve_request_tenant_id(request)
    if tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required: no tenant in token or cookie.",
        )
    return tenant_id


class ReconcilePropertyInput(BaseModel):
    property_code: str = Field(..., min_length=1, max_length=50)
    address: str = Field(..., min_length=1, max_length=500)
    guidebook_url: Optional[str] = Field(None, max_length=1000)


class ReconcilePortfolioRequest(BaseModel):
    properties: List[ReconcilePropertyInput] = Field(..., min_length=1, max_length=500)


class ReconcilePropertyOutcome(BaseModel):
    property_code: str
    action: str
    guidebook_status: str
    chunks_inserted: int = 0
    chunks_updated: int = 0
    chunks_deleted: int = 0
    scoped_knowledge_written: int = 0
    scoped_knowledge_failed: int = 0
    scoped_knowledge_skipped_no_property: bool = False
    error: Optional[str] = None


class ReconcileResponse(BaseModel):
    tenant_id: str
    properties_active: int
    properties_deactivated: int
    embeddings_deleted_for_deactivated: int
    outcomes: List[ReconcilePropertyOutcome]


@router.post(
    "/reconcile",
    response_model=ReconcileResponse,
)
async def reconcile_properties(
    payload: ReconcilePortfolioRequest,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
):
    tenant_id = _require_tenant(request)

    seen_codes = set()
    duplicate_codes = []
    for prop in payload.properties:
        code = prop.property_code.strip()
        if code in seen_codes:
            duplicate_codes.append(code)
        seen_codes.add(code)
    if duplicate_codes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Duplicate property_code values in payload: {sorted(set(duplicate_codes))}",
        )

    result = await session.execute(
        text(
            """
            SELECT property_code, address_street, property_guide_url, is_active
            FROM properties
            WHERE tenant_id = CAST(:tenant_id AS uuid)
            """
        ),
        {"tenant_id": str(tenant_id)},
    )
    current_rows = result.mappings().all()
    current_by_code: Dict[str, Dict[str, object]] = {
        str(row["property_code"]): dict(row) for row in current_rows
    }

    payload_by_code = {prop.property_code.strip(): prop for prop in payload.properties}
    current_codes = set(current_by_code.keys())
    payload_codes = set(payload_by_code.keys())

    to_insert = sorted(payload_codes - current_codes)
    to_update = sorted(payload_codes & current_codes)
    to_deactivate = sorted(
        code for code in current_codes - payload_codes if bool(current_by_code[code]["is_active"])
    )

    outcomes_by_code: Dict[str, ReconcilePropertyOutcome] = {}

    for code in to_insert:
        prop = payload_by_code[code]
        await session.execute(
            text(
                """
                INSERT INTO properties (
                    tenant_id,
                    property_code,
                    address_street,
                    property_guide_url,
                    is_active,
                    data_source
                )
                VALUES (
                    CAST(:tenant_id AS uuid),
                    :property_code,
                    :address_street,
                    :property_guide_url,
                    true,
                    'import'
                )
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "property_code": code,
                "address_street": prop.address,
                "property_guide_url": prop.guidebook_url,
            },
        )
        outcomes_by_code[code] = ReconcilePropertyOutcome(
            property_code=code,
            action="inserted",
            guidebook_status="pending",
        )

    for code in to_update:
        prop = payload_by_code[code]
        current = current_by_code[code]
        address_changed = str(current["address_street"]) != prop.address
        url_changed = (current["property_guide_url"] or None) != prop.guidebook_url
        was_inactive = not bool(current["is_active"])
        action = "updated" if (address_changed or url_changed or was_inactive) else "unchanged"

        await session.execute(
            text(
                """
                UPDATE properties
                SET address_street = :address_street,
                    property_guide_url = :property_guide_url,
                    is_active = true,
                    updated_at = NOW()
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND property_code = :property_code
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "property_code": code,
                "address_street": prop.address,
                "property_guide_url": prop.guidebook_url,
            },
        )
        outcomes_by_code[code] = ReconcilePropertyOutcome(
            property_code=code,
            action=action,
            guidebook_status="pending",
        )

    embeddings_deleted_for_deactivated = 0
    deactivated_outcomes: List[ReconcilePropertyOutcome] = []
    for code in to_deactivate:
        await session.execute(
            text(
                """
                UPDATE properties
                SET is_active = false,
                    updated_at = NOW()
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND property_code = :property_code
                """
            ),
            {"tenant_id": str(tenant_id), "property_code": code},
        )
        delete_result = await session.execute(
            text(
                """
                DELETE FROM knowledge_embeddings
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND property_code = :property_code
                RETURNING doc_id
                """
            ),
            {"tenant_id": str(tenant_id), "property_code": code},
        )
        deleted_rows = delete_result.fetchall()
        deleted_count = len(deleted_rows)
        embeddings_deleted_for_deactivated += deleted_count
        deactivated_outcomes.append(
            ReconcilePropertyOutcome(
                property_code=code,
                action="deactivated",
                guidebook_status="skipped_deactivated",
                chunks_deleted=deleted_count,
            )
        )

    await session.commit()

    ingest_service = await get_guidebook_ingest_service(session)
    for code in sorted(payload_codes):
        prop = payload_by_code[code]
        outcome = outcomes_by_code[code]
        if not prop.guidebook_url:
            outcome.guidebook_status = "skipped_no_url"
            continue

        try:
            ingest_result = await ingest_service.ingest_property_guidebook(
                tenant_id=tenant_id,
                property_code=code,
                property_address=prop.address,
                guidebook_url=prop.guidebook_url,
            )
            outcome.guidebook_status = "ingested"
            outcome.chunks_inserted = ingest_result.inserted
            outcome.chunks_updated = ingest_result.updated
            outcome.chunks_deleted = ingest_result.deleted
            outcome.scoped_knowledge_written = ingest_result.scoped_knowledge_written
            outcome.scoped_knowledge_failed = ingest_result.scoped_knowledge_failed
            outcome.scoped_knowledge_skipped_no_property = (
                ingest_result.scoped_knowledge_skipped_no_property
            )
        except GuidebookFetchStop as exc:
            message = str(exc)
            if "guide_not_configured" in message:
                outcome.guidebook_status = "skipped_not_configured"
            else:
                outcome.guidebook_status = "failed"
                outcome.error = message
            logger.warning("reconcile guidebook ingest stop: %s", message)
        except Exception as exc:  # pragma: no cover - defensive runtime guard
            outcome.guidebook_status = "failed"
            outcome.error = f"{type(exc).__name__}: {exc}"
            logger.exception("reconcile guidebook ingest unexpected error for %s", code)

    outcomes = sorted(
        [*outcomes_by_code.values(), *deactivated_outcomes],
        key=lambda outcome: outcome.property_code,
    )
    return ReconcileResponse(
        tenant_id=str(tenant_id),
        properties_active=len(payload_codes),
        properties_deactivated=len(to_deactivate),
        embeddings_deleted_for_deactivated=embeddings_deleted_for_deactivated,
        outcomes=outcomes,
    )
