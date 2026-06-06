from __future__ import annotations

import asyncio

from app.services.operator.dashboard_summary_service import DashboardSummaryService


def test_build_summary_with_explicit_empty_scope_bypasses_cached_summary():
    service = DashboardSummaryService()
    calls: list[tuple[str, object]] = []

    async def _fake_load_cached_summary(session, tenant_id):
        calls.append(("load_cached", tenant_id))
        return {"sessions": {"active": 999}}

    async def _fake_compute_live_summary(**kwargs):
        calls.append(("compute_live", kwargs.get("visible_property_codes")))
        return {"sessions": {"active": 0}}

    async def _fake_persist_summary(session, tenant_id, summary):
        calls.append(("persist", tenant_id))

    service._load_cached_summary = _fake_load_cached_summary  # type: ignore[method-assign]
    service._compute_live_summary = _fake_compute_live_summary  # type: ignore[method-assign]
    service._persist_summary = _fake_persist_summary  # type: ignore[method-assign]

    result = asyncio.run(
        service.build_summary(
            session=object(),
            tenant_id="00000000-0000-0000-0000-000000000001",
            operator_id="00000000-0000-0000-0000-000000000002",
            property_meta={"where_sql": "TRUE", "code_expr": "property_code"},
            notification_filter_sql="TRUE",
            inbox_row=None,
            visible_property_codes=[],
        )
    )

    assert calls == [("compute_live", [])]
    assert result["cache_source"] == "live"
    assert result["sessions"]["active"] == 0
