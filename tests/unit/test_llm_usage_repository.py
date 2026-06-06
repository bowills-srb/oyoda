from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from app.repositories.llm_usage_repository import LLMUsageRepository


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def one(self):
        return self._rows[0]


class _FakeSession:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    async def execute(self, query, params):
        self.calls.append((str(query), params))
        return _FakeResult(self.rows)


@pytest.mark.asyncio
async def test_recent_calls_normalizes_fields():
    tenant_id = uuid4()
    db = _FakeSession(
        [
            {
                "created_at": datetime(2026, 5, 13, 12, 47, 39, tzinfo=UTC),
                "service_name": "topic_classifier",
                "tenant_id": tenant_id,
                "request_type": "topic_classification",
                "provider": "groq",
                "model_id": "meta-llama/llama-4-scout-17b-16e-instruct",
                "input_tokens": 420,
                "output_tokens": 61,
                "estimated_cost_usd": Decimal("0.000296"),
                "success": True,
                "error_type": None,
                "latency_ms": 510,
                "fallback_position": 1,
                "metadata": {"message_chars": 39},
            }
        ]
    )
    repo = LLMUsageRepository(db)

    rows = await repo.recent_calls(limit=10, tenant_id=tenant_id)

    assert rows[0]["service_name"] == "topic_classifier"
    assert rows[0]["tenant_id"] == str(tenant_id)
    assert rows[0]["estimated_cost_usd"] == "0.000296"
    assert rows[0]["metadata"] == {"message_chars": 39}
    assert "tenant_id = CAST(:tenant_id AS uuid)" in db.calls[0][0]


@pytest.mark.asyncio
async def test_totals_by_service_formats_summary():
    db = _FakeSession(
        [
            {
                "service_name": "llm_email_extractor",
                "call_count": 3,
                "total_cost_usd": Decimal("0.001234"),
                "avg_latency_ms": 120.4,
                "success_ratio": 1.0,
            }
        ]
    )
    repo = LLMUsageRepository(db)

    rows = await repo.totals_by_service(hours=24)

    assert rows == [
        {
            "service_name": "llm_email_extractor",
            "call_count": 3,
            "total_cost_usd": "0.001234",
            "avg_latency_ms": 120,
            "success_ratio": 1.0,
        }
    ]


@pytest.mark.asyncio
async def test_totals_summary_formats_totals():
    db = _FakeSession(
        [
            {
                "call_count": 4,
                "total_cost_usd": Decimal("0.004200"),
                "failed_calls": 1,
                "avg_latency_ms": 342.9,
            }
        ]
    )
    repo = LLMUsageRepository(db)

    row = await repo.totals_summary(hours=24)

    assert row == {
        "call_count": 4,
        "total_cost_usd": "0.004200",
        "failed_calls": 1,
        "avg_latency_ms": 342,
    }


@pytest.mark.asyncio
async def test_hourly_spend_rate_formats_buckets():
    db = _FakeSession(
        [
            {
                "hour_bucket": datetime(2026, 5, 13, 12, 0, tzinfo=UTC),
                "provider": "anthropic",
                "total_cost_usd": Decimal("0.023100"),
                "call_count": 5,
            }
        ]
    )
    repo = LLMUsageRepository(db)

    rows = await repo.hourly_spend_rate(hours=12)

    assert rows == [
        {
            "hour_bucket": "2026-05-13T12:00:00+00:00",
            "provider": "anthropic",
            "total_cost_usd": "0.023100",
            "call_count": 5,
        }
    ]
