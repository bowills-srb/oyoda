from __future__ import annotations

import sys
import types
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

if "jose" not in sys.modules:
    jose_stub = types.ModuleType("jose")
    jose_stub.JWTError = Exception
    jose_stub.jwt = types.SimpleNamespace()
    sys.modules["jose"] = jose_stub

from app.api.v1.endpoints import admin_llm_usage


def test_parse_window_accepts_supported_values():
    assert admin_llm_usage._parse_window("24h") == 24
    assert admin_llm_usage._parse_window("7d") == 168
    assert admin_llm_usage._parse_window("30d") == 720


def test_parse_window_rejects_invalid_value():
    with pytest.raises(HTTPException) as exc:
        admin_llm_usage._parse_window("2d")
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_summary_endpoint_combines_repository_outputs(monkeypatch):
    repo = AsyncMock()
    repo.totals_summary.side_effect = [
        {"call_count": 5, "total_cost_usd": "0.010000", "failed_calls": 0, "avg_latency_ms": 100},
        {"call_count": 7, "total_cost_usd": "0.020000", "failed_calls": 1, "avg_latency_ms": 120},
        {"call_count": 9, "total_cost_usd": "0.030000", "failed_calls": 2, "avg_latency_ms": 140},
    ]
    repo.hourly_spend_rate.return_value = [
        {"hour_bucket": "2026-05-13T13:00:00+00:00", "provider": "groq", "total_cost_usd": "0.001200", "call_count": 2},
        {"hour_bucket": "2026-05-13T13:00:00+00:00", "provider": "anthropic", "total_cost_usd": "0.002300", "call_count": 1},
    ]

    monkeypatch.setattr(admin_llm_usage, "LLMUsageRepository", lambda db: repo)

    payload = await admin_llm_usage.get_llm_usage_summary(window="24h", tenant_id=None, db=object())

    assert payload["window"] == "24h"
    assert payload["selected_window"]["total_cost_usd"] == "0.010000"
    assert payload["last_24h"]["total_cost_usd"] == "0.020000"
    assert payload["last_7d"]["total_cost_usd"] == "0.030000"
    assert payload["current_hourly_burn_usd"] == "0.003500"
