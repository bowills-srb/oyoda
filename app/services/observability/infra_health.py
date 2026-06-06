"""
Infrastructure health snapshot for operator-facing visibility.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import httpx
import redis as redis_sync

from app.core.config import get_settings
from app.services.observability.deployment_runtime import get_runtime_signal_snapshot


@dataclass
class InfraHealthSnapshot:
    pgbouncer: Dict[str, Any]
    exporter: Dict[str, Any]
    queues: Dict[str, Any]
    workers: Dict[str, Any]
    runtime_signals: Dict[str, Any]


def _to_sync_dsn(url: str) -> str:
    if url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql+asyncpg://", "postgresql://", 1)
    return url


def _pgbouncer_admin_dsn(database_url: str) -> str:
    sync_dsn = _to_sync_dsn(database_url)
    parts = urlsplit(sync_dsn)
    return urlunsplit((parts.scheme, parts.netloc, "/pgbouncer", parts.query, parts.fragment))


async def _collect_pgbouncer(database_url: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "reachable": False,
        "version": None,
        "pool_count": 0,
        "clients_active": 0,
        "clients_waiting": 0,
        "servers_active": 0,
        "servers_idle": 0,
        "error": None,
    }
    try:
        conn = await asyncpg.connect(dsn=_pgbouncer_admin_dsn(database_url), timeout=2)
        try:
            ver = await conn.fetchval("SHOW VERSION;")
            pools = await conn.fetch("SHOW POOLS;")
            result["reachable"] = True
            result["version"] = ver
            result["pool_count"] = len(pools)
            result["clients_active"] = int(sum(int(r.get("cl_active", 0)) for r in pools))
            result["clients_waiting"] = int(sum(int(r.get("cl_waiting", 0)) for r in pools))
            result["servers_active"] = int(sum(int(r.get("sv_active", 0)) for r in pools))
            result["servers_idle"] = int(sum(int(r.get("sv_idle", 0)) for r in pools))
        finally:
            await conn.close()
    except Exception as exc:
        result["error"] = str(exc)
    return result


async def _collect_exporter() -> Dict[str, Any]:
    targets = [
        "http://pgbouncer-exporter:9127/metrics",
        "http://localhost:9127/metrics",
    ]
    out: Dict[str, Any] = {"up": False, "target": None, "status_code": None}
    async with httpx.AsyncClient(timeout=2.0) as client:
        for target in targets:
            try:
                resp = await client.get(target)
                if resp.status_code == 200:
                    out["up"] = True
                    out["target"] = target
                    out["status_code"] = resp.status_code
                    return out
                out["target"] = target
                out["status_code"] = resp.status_code
            except Exception:
                continue
    return out


def _collect_queues(broker_url: str) -> Dict[str, Any]:
    queue_names: List[str] = ["concierge", "ingestion", "operations", "celery"]
    out: Dict[str, Any] = {"connected": False, "depths": {}, "total_depth": 0, "error": None}
    try:
        client = redis_sync.from_url(broker_url, decode_responses=True)
        depths = {}
        for q in queue_names:
            depths[q] = int(client.llen(q))
        out["connected"] = True
        out["depths"] = depths
        out["total_depth"] = int(sum(depths.values()))
    except Exception as exc:
        out["error"] = str(exc)
    return out


def _collect_workers() -> Dict[str, Any]:
    out: Dict[str, Any] = {"online": 0, "workers": [], "error": None}
    try:
        from app.workers.celery_app import celery_app

        inspector = celery_app.control.inspect(timeout=1.0)
        ping = inspector.ping() or {}
        workers = sorted(list(ping.keys()))
        out["online"] = len(workers)
        out["workers"] = workers
    except Exception as exc:
        out["error"] = str(exc)
    return out


async def get_infra_health_snapshot() -> InfraHealthSnapshot:
    settings = get_settings()
    pgbouncer = await _collect_pgbouncer(settings.database_url)
    exporter = await _collect_exporter()
    queues = _collect_queues(settings.celery_broker_url)
    workers = _collect_workers()
    runtime_signals = get_runtime_signal_snapshot(settings.redis_url)
    return InfraHealthSnapshot(
        pgbouncer=pgbouncer,
        exporter=exporter,
        queues=queues,
        workers=workers,
        runtime_signals=runtime_signals,
    )
