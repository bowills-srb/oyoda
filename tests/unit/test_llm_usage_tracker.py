from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from app.services.observability.llm_usage_tracker import LLMUsageTracker
from app.services.observability.model_pricing import calculate_cost


def test_calculate_cost_for_claude_haiku():
    cost = calculate_cost("claude-haiku-4-5", 1000, 500)
    assert cost == Decimal("0.003500")


def test_calculate_cost_for_unknown_model_is_zero():
    cost = calculate_cost("unknown-model", 1000, 500)
    assert cost == Decimal("0.000000")


@pytest.mark.asyncio
async def test_tracker_swallows_storage_failure(monkeypatch):
    class _BrokenSession:
        async def __aenter__(self):
            raise RuntimeError("db unavailable")

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        "app.services.observability.llm_usage_tracker.get_db_session",
        lambda: _BrokenSession(),
    )

    await LLMUsageTracker.record(
        service_name="llm_email_extractor",
        tenant_id=uuid4(),
        request_type="inbox_parse",
        provider="groq",
        model_id="meta-llama/llama-4-scout-17b-16e-instruct",
        input_tokens=123,
        output_tokens=45,
        success=True,
        latency_ms=80,
    )
