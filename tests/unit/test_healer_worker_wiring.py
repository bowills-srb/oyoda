from __future__ import annotations

from uuid import UUID
from unittest.mock import patch

from celery.schedules import crontab

from app.workers import tasks
from app.workers.celery_app import beat_schedule, task_routes


def test_scan_healer_proposals_task_reports_counts() -> None:
    tenant_a = UUID("11111111-1111-1111-1111-111111111111")
    tenant_b = UUID("22222222-2222-2222-2222-222222222222")

    def _consume_coro(coro):
        coro.close()
        return {tenant_a: 2, tenant_b: 1}

    with patch(
        "app.workers.tasks._run_async",
        side_effect=_consume_coro,
    ) as run_async:
        result = tasks.scan_healer_proposals.run(window_hours=168)

    assert result == {
        "status": "success",
        "window_hours": 168,
        "tenants_scanned": 2,
        "proposals_drafted": 3,
        "per_tenant_counts": {
            str(tenant_a): 2,
            str(tenant_b): 1,
        },
    }
    run_async.assert_called_once()


def test_scan_healer_proposals_task_route_is_concierge() -> None:
    assert task_routes["app.workers.tasks.scan_healer_proposals"] == {"queue": "concierge"}


def test_scan_healer_proposals_is_scheduled_daily() -> None:
    schedule = beat_schedule["scan-healer-proposals-daily"]

    assert schedule["task"] == "app.workers.tasks.scan_healer_proposals"
    assert schedule["kwargs"] == {"window_hours": 24}
    assert schedule["schedule"] == crontab(hour=5, minute=0)
