from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class LLMUsageRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def totals_summary(
        self,
        *,
        hours: int = 24,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        where, params = _build_common_filters(tenant_id=tenant_id, hours=hours)
        query = text(
            f"""
            SELECT
                COUNT(*) AS call_count,
                COALESCE(SUM(estimated_cost_usd), 0) AS total_cost_usd,
                COUNT(*) FILTER (WHERE success IS FALSE) AS failed_calls,
                AVG(latency_ms) AS avg_latency_ms
            FROM llm_usage_events
            WHERE {' AND '.join(where)}
            """
        )
        row = (await self.db.execute(query, params)).mappings().one()
        return {
            "call_count": int(row["call_count"] or 0),
            "total_cost_usd": _decimal_to_str(row["total_cost_usd"]),
            "failed_calls": int(row["failed_calls"] or 0),
            "avg_latency_ms": int(row["avg_latency_ms"] or 0),
        }

    async def recent_calls(
        self,
        *,
        limit: int = 100,
        tenant_id: UUID | None = None,
        service_name: str | None = None,
        provider: str | None = None,
        success: bool | None = None,
        hours: int | None = None,
    ) -> list[dict[str, Any]]:
        where, params = _build_common_filters(
            tenant_id=tenant_id,
            service_name=service_name,
            provider=provider,
            success=success,
            hours=hours,
        )
        params["limit"] = max(1, min(limit, 500))
        query = text(
            f"""
            SELECT
                created_at,
                service_name,
                tenant_id,
                request_type,
                provider,
                model_id,
                input_tokens,
                output_tokens,
                estimated_cost_usd,
                success,
                error_type,
                latency_ms,
                fallback_position,
                metadata
            FROM llm_usage_events
            WHERE {' AND '.join(where)}
            ORDER BY created_at DESC
            LIMIT :limit
            """
        )
        rows = (await self.db.execute(query, params)).mappings().all()
        return [_normalize_row(row) for row in rows]

    async def totals_by_service(
        self,
        *,
        hours: int = 24,
        tenant_id: UUID | None = None,
    ) -> list[dict[str, Any]]:
        where, params = _build_common_filters(tenant_id=tenant_id, hours=hours)
        query = text(
            f"""
            SELECT
                service_name,
                COUNT(*) AS call_count,
                COALESCE(SUM(estimated_cost_usd), 0) AS total_cost_usd,
                AVG(latency_ms) AS avg_latency_ms,
                AVG(CASE WHEN success THEN 1 ELSE 0 END) AS success_ratio
            FROM llm_usage_events
            WHERE {' AND '.join(where)}
            GROUP BY service_name
            ORDER BY total_cost_usd DESC, call_count DESC, service_name ASC
            """
        )
        rows = (await self.db.execute(query, params)).mappings().all()
        return [
            {
                "service_name": row["service_name"],
                "call_count": int(row["call_count"] or 0),
                "total_cost_usd": _decimal_to_str(row["total_cost_usd"]),
                "avg_latency_ms": int(row["avg_latency_ms"] or 0),
                "success_ratio": float(row["success_ratio"] or 0.0),
            }
            for row in rows
        ]

    async def totals_by_provider(
        self,
        *,
        hours: int = 24,
        tenant_id: UUID | None = None,
    ) -> list[dict[str, Any]]:
        where, params = _build_common_filters(tenant_id=tenant_id, hours=hours)
        query = text(
            f"""
            SELECT
                provider,
                model_id,
                COUNT(*) AS call_count,
                COALESCE(SUM(estimated_cost_usd), 0) AS total_cost_usd,
                AVG(input_tokens) AS avg_input_tokens,
                AVG(output_tokens) AS avg_output_tokens
            FROM llm_usage_events
            WHERE {' AND '.join(where)}
            GROUP BY provider, model_id
            ORDER BY total_cost_usd DESC, call_count DESC, provider ASC, model_id ASC
            """
        )
        rows = (await self.db.execute(query, params)).mappings().all()
        return [
            {
                "provider": row["provider"],
                "model_id": row["model_id"],
                "call_count": int(row["call_count"] or 0),
                "total_cost_usd": _decimal_to_str(row["total_cost_usd"]),
                "avg_input_tokens": int(row["avg_input_tokens"] or 0),
                "avg_output_tokens": int(row["avg_output_tokens"] or 0),
            }
            for row in rows
        ]

    async def totals_by_tenant(
        self,
        *,
        hours: int = 24,
    ) -> list[dict[str, Any]]:
        where, params = _build_common_filters(hours=hours)
        query = text(
            f"""
            SELECT
                tenant_id,
                COUNT(*) AS call_count,
                COALESCE(SUM(estimated_cost_usd), 0) AS total_cost_usd,
                COUNT(*) FILTER (WHERE success IS FALSE) AS failed_calls
            FROM llm_usage_events
            WHERE {' AND '.join(where)}
            GROUP BY tenant_id
            ORDER BY total_cost_usd DESC, call_count DESC, tenant_id NULLS LAST
            """
        )
        rows = (await self.db.execute(query, params)).mappings().all()
        return [
            {
                "tenant_id": str(row["tenant_id"]) if row["tenant_id"] else None,
                "call_count": int(row["call_count"] or 0),
                "total_cost_usd": _decimal_to_str(row["total_cost_usd"]),
                "failed_calls": int(row["failed_calls"] or 0),
            }
            for row in rows
        ]

    async def hourly_spend_rate(
        self,
        *,
        hours: int = 24,
        tenant_id: UUID | None = None,
    ) -> list[dict[str, Any]]:
        where, params = _build_common_filters(tenant_id=tenant_id, hours=hours)
        query = text(
            f"""
            SELECT
                date_trunc('hour', created_at) AS hour_bucket,
                provider,
                COALESCE(SUM(estimated_cost_usd), 0) AS total_cost_usd,
                COUNT(*) AS call_count
            FROM llm_usage_events
            WHERE {' AND '.join(where)}
            GROUP BY date_trunc('hour', created_at), provider
            ORDER BY hour_bucket DESC, provider ASC
            """
        )
        rows = (await self.db.execute(query, params)).mappings().all()
        return [
            {
                "hour_bucket": row["hour_bucket"].isoformat() if row["hour_bucket"] else None,
                "provider": row["provider"],
                "total_cost_usd": _decimal_to_str(row["total_cost_usd"]),
                "call_count": int(row["call_count"] or 0),
            }
            for row in rows
        ]


def _build_common_filters(
    *,
    tenant_id: UUID | None = None,
    service_name: str | None = None,
    provider: str | None = None,
    success: bool | None = None,
    hours: int | None = None,
) -> tuple[list[str], dict[str, Any]]:
    where = ["1=1"]
    params: dict[str, Any] = {}

    if tenant_id is not None:
        where.append("tenant_id = CAST(:tenant_id AS uuid)")
        params["tenant_id"] = str(tenant_id)
    if service_name:
        where.append("service_name = :service_name")
        params["service_name"] = service_name
    if provider:
        where.append("provider = :provider")
        params["provider"] = provider
    if success is not None:
        where.append("success = :success")
        params["success"] = success
    if hours is not None:
        where.append("created_at >= NOW() - (:hours || ' hours')::interval")
        params["hours"] = str(max(1, min(hours, 24 * 30)))

    return where, params


def _decimal_to_str(value: Any) -> str:
    if value is None:
        return "0"
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)


def _normalize_row(row: Any) -> dict[str, Any]:
    return {
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "service_name": row["service_name"],
        "tenant_id": str(row["tenant_id"]) if row["tenant_id"] else None,
        "request_type": row["request_type"],
        "provider": row["provider"],
        "model_id": row["model_id"],
        "input_tokens": int(row["input_tokens"] or 0),
        "output_tokens": int(row["output_tokens"] or 0),
        "estimated_cost_usd": _decimal_to_str(row["estimated_cost_usd"]),
        "success": bool(row["success"]),
        "error_type": row["error_type"],
        "latency_ms": int(row["latency_ms"] or 0),
        "fallback_position": int(row["fallback_position"] or 1),
        "metadata": row["metadata"] or {},
    }
