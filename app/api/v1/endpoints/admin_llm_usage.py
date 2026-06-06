from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.ops_auth import require_ops_access
from app.db.session import get_async_session
from app.repositories.llm_usage_repository import LLMUsageRepository

router = APIRouter(
    prefix="/app/api/admin/llm-usage",
    tags=["Admin LLM Usage"],
    dependencies=[Depends(require_ops_access)],
)


_WINDOW_TO_HOURS = {
    "1h": 1,
    "24h": 24,
    "7d": 24 * 7,
    "30d": 24 * 30,
}


def _parse_window(window: str) -> int:
    normalized = (window or "24h").strip().lower()
    hours = _WINDOW_TO_HOURS.get(normalized)
    if hours is None:
        raise HTTPException(
            status_code=400,
            detail="Invalid window. Use one of: 1h, 24h, 7d, 30d",
        )
    return hours


def _parse_tenant_id(tenant_id: Optional[str]) -> UUID | None:
    if not tenant_id:
        return None
    try:
        return UUID(tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid tenant_id") from exc


@router.get("/summary")
async def get_llm_usage_summary(
    window: str = Query(default="24h"),
    tenant_id: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_async_session),
):
    repo = LLMUsageRepository(db)
    hours = _parse_window(window)
    tenant_uuid = _parse_tenant_id(tenant_id)

    selected = await repo.totals_summary(hours=hours, tenant_id=tenant_uuid)
    last_24h = await repo.totals_summary(hours=24, tenant_id=tenant_uuid)
    last_7d = await repo.totals_summary(hours=24 * 7, tenant_id=tenant_uuid)
    burn_rows = await repo.hourly_spend_rate(hours=1, tenant_id=tenant_uuid)
    hourly_burn = sum(float(row["total_cost_usd"]) for row in burn_rows)

    return {
        "window": window,
        "selected_window": selected,
        "last_24h": last_24h,
        "last_7d": last_7d,
        "current_hourly_burn_usd": f"{hourly_burn:.6f}",
    }


@router.get("/by-service")
async def get_llm_usage_by_service(
    window: str = Query(default="24h"),
    tenant_id: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_async_session),
):
    repo = LLMUsageRepository(db)
    return {
        "window": window,
        "rows": await repo.totals_by_service(
            hours=_parse_window(window),
            tenant_id=_parse_tenant_id(tenant_id),
        ),
    }


@router.get("/by-provider")
async def get_llm_usage_by_provider(
    window: str = Query(default="24h"),
    tenant_id: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_async_session),
):
    repo = LLMUsageRepository(db)
    return {
        "window": window,
        "rows": await repo.totals_by_provider(
            hours=_parse_window(window),
            tenant_id=_parse_tenant_id(tenant_id),
        ),
    }


@router.get("/by-tenant")
async def get_llm_usage_by_tenant(
    window: str = Query(default="24h"),
    db: AsyncSession = Depends(get_async_session),
):
    repo = LLMUsageRepository(db)
    return {
        "window": window,
        "rows": await repo.totals_by_tenant(hours=_parse_window(window)),
    }


@router.get("/recent")
async def get_recent_llm_usage_calls(
    limit: int = Query(default=50, ge=1, le=200),
    window: str = Query(default="24h"),
    tenant_id: Optional[str] = Query(default=None),
    service_name: Optional[str] = Query(default=None),
    provider: Optional[str] = Query(default=None),
    success: Optional[bool] = Query(default=None),
    db: AsyncSession = Depends(get_async_session),
):
    repo = LLMUsageRepository(db)
    return {
        "window": window,
        "rows": await repo.recent_calls(
            limit=limit,
            tenant_id=_parse_tenant_id(tenant_id),
            service_name=service_name,
            provider=provider,
            success=success,
            hours=_parse_window(window),
        ),
    }


@router.get("/burn-rate")
async def get_llm_usage_burn_rate(
    tenant_id: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_async_session),
):
    repo = LLMUsageRepository(db)
    tenant_uuid = _parse_tenant_id(tenant_id)
    rows = await repo.hourly_spend_rate(hours=24, tenant_id=tenant_uuid)
    current_hour_rows = await repo.hourly_spend_rate(hours=1, tenant_id=tenant_uuid)
    current_hourly_burn = sum(float(row["total_cost_usd"]) for row in current_hour_rows)
    return {
        "current_hourly_burn_usd": f"{current_hourly_burn:.6f}",
        "rows": rows,
    }
