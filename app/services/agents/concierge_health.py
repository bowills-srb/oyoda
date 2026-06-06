"""
Concierge health checks.

Single place to verify the concierge-critical runtime surfaces:
- MCP registry wiring
- Core agent factories
- Detector registry presence (market signal feed readiness)
- Optional DB checks for active sessions/escalations
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from app.services.observability.slo_metrics import update_runtime_gauges


@dataclass
class ConciergeHealthReport:
    healthy: bool
    checked_at: str
    checks: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


async def run_concierge_health_checks(
    db: Optional[AsyncSession] = None,
) -> ConciergeHealthReport:
    checks: Dict[str, Any] = {}
    warnings: List[str] = []
    errors: List[str] = []

    # MCP readiness
    try:
        from app.mcp.registry import get_mcp_registry

        registry = get_mcp_registry()
        server_names = {s["name"] for s in registry.list_servers()}
        required = {"concierge", "knowledge", "pms"}
        missing = sorted(required - server_names)
        checks["mcp"] = {
            "servers": sorted(server_names),
            "required": sorted(required),
            "missing": missing,
        }
        if missing:
            errors.append(f"Missing required MCP servers: {', '.join(missing)}")
    except Exception as exc:
        errors.append(f"MCP check failed: {exc}")

    # Core agent readiness (constructor-level)
    try:
        from app.services.agents.pms_sync_agent import get_pms_sync_agent
        from app.services.agents.escalation_handoff_agent import (
            get_escalation_handoff_agent,
        )
        from app.services.agents.knowledge_curator_agent import (
            get_knowledge_curator_agent,
        )

        _ = get_pms_sync_agent()
        _ = get_escalation_handoff_agent()
        _ = get_knowledge_curator_agent()
        checks["agents"] = {
            "pms_sync": "ready",
            "escalation_handoff": "ready",
            "knowledge_curator": "ready",
        }
    except Exception as exc:
        errors.append(f"Agent readiness check failed: {exc}")

    # Detector registry visibility
    try:
        from app.services.detectors.detector_engine import DetectorRegistry

        registered = sorted(DetectorRegistry._detector_classes.keys())  # noqa: SLF001
        try:
            # Ensure detector workers are imported/registered.
            import workers.detectors.detector_workers  # noqa: F401
            from workers.base import WorkerCategory, WorkerRegistry

            worker_detectors = WorkerRegistry.get_workers_by_category(
                WorkerCategory.ANALYTICS
            )
            worker_detector_names = sorted(
                {w.name for w in worker_detectors if w is not None}
            )
        except Exception:
            worker_detector_names = []

        checks["detectors"] = {
            "registered_count": len(registered),
            "registered_types": registered,
            "worker_detector_count": len(worker_detector_names),
            "worker_detectors": worker_detector_names,
        }
        if not registered:
            warnings.append("No detector classes registered")
    except Exception as exc:
        warnings.append(f"Detector check unavailable: {exc}")

    # Optional DB checks
    if db is not None:
        try:
            from sqlalchemy import text

            active_sessions = await db.scalar(
                text(
                    """
                    SELECT COUNT(*) FROM concierge_guest_sessions
                    WHERE status = 'active'
                    """
                )
            )
            open_escalations = await db.scalar(
                text(
                    """
                    SELECT COUNT(*) FROM concierge_escalations
                    WHERE status IN ('pending', 'acknowledged', 'in_progress')
                    """
                )
            )
            checks["db"] = {
                "active_sessions": int(active_sessions or 0),
                "open_escalations": int(open_escalations or 0),
            }
            update_runtime_gauges(
                active_sessions=int(active_sessions or 0),
                open_escalations=int(open_escalations or 0),
            )
        except Exception as exc:
            warnings.append(f"DB concierge check failed: {exc}")
    else:
        checks["db"] = {"status": "skipped"}

    return ConciergeHealthReport(
        healthy=len(errors) == 0,
        checked_at=datetime.now(timezone.utc).isoformat(),
        checks=checks,
        warnings=warnings,
        errors=errors,
    )
