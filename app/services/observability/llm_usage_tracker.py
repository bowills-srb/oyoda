from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from decimal import Decimal
from time import monotonic
from typing import Any
from uuid import UUID

from sqlalchemy import text

from app.core.database import get_db_session
from app.services.observability.model_pricing import calculate_cost

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LLMUsageRecord:
    service_name: str
    tenant_id: UUID | None
    request_type: str
    provider: str
    model_id: str
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: Decimal
    success: bool
    latency_ms: int
    fallback_position: int = 1
    error_type: str | None = None
    metadata: dict[str, Any] | None = None


class LLMUsageTracker:
    @staticmethod
    async def record(
        *,
        service_name: str,
        tenant_id: UUID | None,
        request_type: str,
        provider: str,
        model_id: str,
        input_tokens: int,
        output_tokens: int,
        success: bool,
        latency_ms: int,
        fallback_position: int = 1,
        error_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        record = LLMUsageRecord(
            service_name=service_name,
            tenant_id=tenant_id,
            request_type=request_type,
            provider=provider,
            model_id=model_id,
            input_tokens=max(input_tokens, 0),
            output_tokens=max(output_tokens, 0),
            estimated_cost_usd=calculate_cost(model_id, input_tokens, output_tokens),
            success=success,
            latency_ms=max(latency_ms, 0),
            fallback_position=max(fallback_position, 1),
            error_type=error_type,
            metadata=metadata or {},
        )

        payload = {
            "service_name": record.service_name,
            "tenant_id": str(record.tenant_id) if record.tenant_id else None,
            "request_type": record.request_type,
            "provider": record.provider,
            "model_id": record.model_id,
            "input_tokens": record.input_tokens,
            "output_tokens": record.output_tokens,
            "estimated_cost_usd": str(record.estimated_cost_usd),
            "success": record.success,
            "error_type": record.error_type,
            "latency_ms": record.latency_ms,
            "fallback_position": record.fallback_position,
            "metadata": json.dumps(record.metadata, default=str),
        }

        try:
            async with get_db_session() as db:
                await db.execute(
                    text(
                        """
                        INSERT INTO llm_usage_events (
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
                        ) VALUES (
                            :service_name,
                            CAST(:tenant_id AS uuid),
                            :request_type,
                            :provider,
                            :model_id,
                            :input_tokens,
                            :output_tokens,
                            CAST(:estimated_cost_usd AS numeric(10, 6)),
                            :success,
                            :error_type,
                            :latency_ms,
                            :fallback_position,
                            CAST(:metadata AS jsonb)
                        )
                        """
                    ),
                    payload,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[LLMUsageTracker] failed to record service=%s provider=%s model=%s error=%s",
                service_name,
                provider,
                model_id,
                type(exc).__name__,
            )


class LLMCallTimer:
    def __init__(self) -> None:
        self._start = monotonic()

    def elapsed_ms(self) -> int:
        return int((monotonic() - self._start) * 1000)
