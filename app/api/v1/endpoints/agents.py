"""
Agent Management API

Exposes the escalation handoff agent (SLA tracking / resolve workflow),
the knowledge curator agent (gap drafts / approve / reject), and the
experiment registry (prompt variant change control) to the operator dashboard.

Endpoints:
  Escalation:
    POST /api/v1/agents/escalations/{ticket_id}/acknowledge
    POST /api/v1/agents/escalations/{ticket_id}/resolve
    GET  /api/v1/agents/escalations/sla-stats

  Knowledge Curator:
    GET  /api/v1/agents/knowledge/drafts
    POST /api/v1/agents/knowledge/drafts/{draft_id}/approve
    POST /api/v1/agents/knowledge/drafts/{draft_id}/reject

  Knowledge Health:
    GET  /api/v1/agents/knowledge/retrieval-stats

  PMS Sync:
    POST /api/v1/agents/pms/sync/{session_token}

  Experiment / Prompt Ops:
    GET  /api/v1/agents/experiments                              ← stats for all variants
    POST /api/v1/agents/experiments/variants                     ← register new variant
    POST /api/v1/agents/experiments/variants/{variant_id}/pause  ← hard rollback
    POST /api/v1/agents/experiments/variants/{variant_id}/resume ← re-enable
"""

import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.api.dependencies.ops_auth import require_ops_access
from app.api.dependencies.request_tenant import resolve_request_tenant_id
from app.services.observability.deployment_runtime import get_deployment_runtime_snapshot

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agents", tags=["Agent Management"])


# ─────────────────────────────────────────────────────────────────────────────
# DB session dependency
# ─────────────────────────────────────────────────────────────────────────────

async def _get_db():
    try:
        from app.core.database import get_db_session
        async with get_db_session() as db:
            yield db
    except Exception:
        # Fallback if database module isn't configured yet
        yield None


# ─────────────────────────────────────────────────────────────────────────────
# Request models
# ─────────────────────────────────────────────────────────────────────────────

class AcknowledgeRequest(BaseModel):
    operator: str  # operator username / email


class ResolveRequest(BaseModel):
    operator: str
    note: str
    resolution_code: Optional[str] = None   # "resolved" | "maintenance" | "refund" | etc.


class ApproveDraftRequest(BaseModel):
    operator: str
    answer: Optional[str] = None   # operator-supplied answer (overrides hint)


class RejectDraftRequest(BaseModel):
    operator: str
    reason: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# Escalation SLA endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/escalations/{ticket_id}/acknowledge")
async def acknowledge_escalation(
    ticket_id: str,
    body: AcknowledgeRequest,
    db: AsyncSession = Depends(_get_db),
):
    """
    Acknowledge an escalation ticket — stops the ack SLA clock.
    Called from the operator dashboard "Acknowledge" button.
    """
    if db is None:
        raise HTTPException(503, "Database not available")

    from app.services.agents.escalation_handoff_agent import get_escalation_handoff_agent
    agent = get_escalation_handoff_agent()
    ok = await agent.acknowledge_ticket(db, ticket_id=ticket_id, operator=body.operator)

    if not ok:
        raise HTTPException(404, f"Ticket {ticket_id} not found or already acknowledged")

    return {"status": "acknowledged", "ticket_id": ticket_id, "operator": body.operator}


@router.post("/escalations/{ticket_id}/resolve")
async def resolve_escalation(
    ticket_id: str,
    body: ResolveRequest,
    db: AsyncSession = Depends(_get_db),
):
    """
    Mark an escalation ticket as resolved.  Records the closure in the
    Watch Layer for p95 resolve time SLO tracking.

    Called from the operator dashboard "Resolve" button.
    """
    if db is None:
        raise HTTPException(503, "Database not available")

    from app.services.agents.escalation_handoff_agent import get_escalation_handoff_agent
    agent = get_escalation_handoff_agent()
    ok = await agent.close_ticket(
        db,
        ticket_id=ticket_id,
        operator=body.operator,
        note=body.note,
        resolution_code=body.resolution_code,
    )

    if not ok:
        raise HTTPException(404, f"Ticket {ticket_id} not found")

    return {
        "status": "resolved",
        "ticket_id": ticket_id,
        "operator": body.operator,
        "resolution_code": body.resolution_code or "resolved",
    }


@router.get("/escalations/sla-stats")
async def get_escalation_sla_stats(db: AsyncSession = Depends(_get_db)):
    """
    SLA performance stats for operator dashboard — p50/p95 ack and resolve
    times, breach counts, breach rate.
    """
    if db is None:
        return {"error": "database not available", "data": None}

    from app.services.agents.escalation_handoff_agent import get_escalation_handoff_agent
    agent = get_escalation_handoff_agent()
    stats = await agent.get_sla_stats(db)

    return {
        "total_tickets": stats.total_tickets,
        "open_tickets": stats.open_tickets,
        "ack_breach_count": stats.ack_breach_count,
        "resolve_breach_count": stats.resolve_breach_count,
        "p50_ack_minutes": stats.p50_ack_minutes,
        "p95_ack_minutes": stats.p95_ack_minutes,
        "p50_resolve_minutes": stats.p50_resolve_minutes,
        "p95_resolve_minutes": stats.p95_resolve_minutes,
        "breach_rate_pct": stats.breach_rate_pct,
        "sla_policy": {
            "urgent":  {"ack_minutes": 15,  "resolve_minutes": 60},
            "high":    {"ack_minutes": 60,  "resolve_minutes": 240},
            "medium":  {"ack_minutes": 240, "resolve_minutes": 1440},
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# Knowledge Curator endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/knowledge/drafts")
async def get_pending_knowledge_drafts(
    request: Request,
    property_code: Optional[str] = None,
    db: AsyncSession = Depends(_get_db),
    _auth: None = Depends(require_ops_access),
):
    """
    List FAQ drafts awaiting operator review — operator dashboard Knowledge Gaps tab.

    Drafts are ordered by occurrence_count DESC so the most-asked unanswered
    questions surface first.
    """
    if db is None:
        return {"drafts": [], "error": "database not available"}
    tenant_id = resolve_request_tenant_id(request)
    if tenant_id is None:
        raise HTTPException(401, "Authenticated tenant context required")

    from app.services.agents.knowledge_curator_agent import get_knowledge_curator_agent
    curator = get_knowledge_curator_agent()
    drafts = await curator.get_pending_drafts(db, tenant_id=str(tenant_id), property_code=property_code)

    return {"drafts": drafts, "count": len(drafts)}


@router.post("/knowledge/drafts/{draft_id}/approve")
async def approve_knowledge_draft(
    draft_id: str,
    request: Request,
    body: ApproveDraftRequest,
    db: AsyncSession = Depends(_get_db),
    _auth: None = Depends(require_ops_access),
):
    """
    Approve a FAQ draft and index it into the knowledge vector store.

    If `answer` is provided, it overrides the curator's scaffold hint.
    Returns the indexed document ID on success.

    After this endpoint returns, the next guest asking that question will
    get a direct quick-answer from the vector store instead of "I'm not sure".
    """
    if db is None:
        raise HTTPException(503, "Database not available")
    tenant_id = resolve_request_tenant_id(request)
    if tenant_id is None:
        raise HTTPException(401, "Authenticated tenant context required")

    from app.services.agents.knowledge_curator_agent import get_knowledge_curator_agent
    curator = get_knowledge_curator_agent()
    doc_id = await curator.approve_draft(
        db,
        tenant_id=str(tenant_id),
        draft_id=draft_id,
        operator=body.operator,
        answer=body.answer,
    )

    if doc_id is None:
        raise HTTPException(
            400,
            "Approval failed — draft not found, already processed, or answer not provided. "
            "Supply an answer in the request body if the hint is still a placeholder.",
        )

    return {
        "status": "approved",
        "draft_id": draft_id,
        "doc_id": doc_id,
        "operator": body.operator,
        "message": "FAQ indexed — retrieval hit rate should improve for this property.",
    }


@router.post("/knowledge/drafts/{draft_id}/reject")
async def reject_knowledge_draft(
    draft_id: str,
    request: Request,
    body: RejectDraftRequest,
    db: AsyncSession = Depends(_get_db),
    _auth: None = Depends(require_ops_access),
):
    """
    Reject a FAQ draft so it doesn't resurface in the dashboard.

    Use this when the question is too specific, out-of-scope, or already
    answered by existing documentation.
    """
    if db is None:
        raise HTTPException(503, "Database not available")
    tenant_id = resolve_request_tenant_id(request)
    if tenant_id is None:
        raise HTTPException(401, "Authenticated tenant context required")

    from app.services.agents.knowledge_curator_agent import get_knowledge_curator_agent
    curator = get_knowledge_curator_agent()
    ok = await curator.reject_draft(
        db,
        tenant_id=str(tenant_id),
        draft_id=draft_id,
        operator=body.operator,
        reason=body.reason,
    )

    if not ok:
        raise HTTPException(404, f"Draft {draft_id} not found")

    return {"status": "rejected", "draft_id": draft_id, "operator": body.operator}


# ─────────────────────────────────────────────────────────────────────────────
# Knowledge health / retrieval SLO
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/knowledge/retrieval-stats")
async def get_knowledge_retrieval_stats():
    """
    Per-property knowledge retrieval hit rate since last server restart.

    A property with hit_rate < 0.4 and attempts >= 10 is marked `degraded`.
    This means the vector store has no indexed documents for that property —
    the operator should upload the house manual and run indexing.

    Note: counters reset on server restart.  For persistent SLO tracking,
    pipe Watch Layer events to your metrics backend.
    """
    from app.services.observability.watch_layer import get_watch_layer
    watch = get_watch_layer()
    return watch.get_retrieval_stats()


@router.get("/slo/summary")
async def get_concierge_slo_summary(
    db: AsyncSession = Depends(_get_db),
    _auth: None = Depends(require_ops_access),
):
    """
    Concierge SLO summary for dashboards.

    Returns thresholds + runtime counters/gauges + DB truth counts.
    """
    from app.services.observability.slo_metrics import (
        get_runtime_snapshot,
        get_slo_thresholds,
    )

    db_counts = {"active_sessions": 0, "open_escalations": 0}
    if db is not None:
        try:
            db_counts["active_sessions"] = int(
                await db.scalar(
                    text(
                        "SELECT COUNT(*) FROM concierge_guest_sessions WHERE status = 'active'"
                    )
                )
                or 0
            )
            db_counts["open_escalations"] = int(
                await db.scalar(
                    text(
                        """
                        SELECT COUNT(*) FROM concierge_escalations
                        WHERE status IN ('pending', 'acknowledged', 'in_progress')
                        """
                    )
                )
                or 0
            )
        except Exception as exc:
            logger.warning("Failed to read SLO DB counts: %s", exc)

    return {
        "thresholds": get_slo_thresholds(),
        "runtime": get_runtime_snapshot(),
        "db": db_counts,
        "deployment": {
            "api_workers": int(os.getenv("API_WORKERS", "4")),
            "celery_concierge_concurrency": int(os.getenv("CELERY_CONCIERGE_CONCURRENCY", "16")),
            "celery_ingestion_concurrency": int(os.getenv("CELERY_INGESTION_CONCURRENCY", "6")),
            "celery_operations_concurrency": int(os.getenv("CELERY_OPERATIONS_CONCURRENCY", "4")),
        },
    }


@router.get("/infra/summary")
async def get_infra_summary(_auth: None = Depends(require_ops_access)):
    """
    Infra summary for operator dashboard:
    - PgBouncer reachability and pool pressure
    - PgBouncer exporter reachability
    - Redis/Celery queue depth
    - Celery worker online count
    """
    from app.services.observability.infra_health import get_infra_health_snapshot

    snap = await get_infra_health_snapshot()
    return {
        "pgbouncer": snap.pgbouncer,
        "exporter": snap.exporter,
        "queues": snap.queues,
        "workers": snap.workers,
        "deployment_runtime": get_deployment_runtime_snapshot(),
        "deployment_runtime_signals": snap.runtime_signals,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Concierge health
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/health/concierge")
async def get_concierge_health(db: AsyncSession = Depends(_get_db)):
    """
    Concierge runtime health:
    - required MCP servers
    - core agent factories
    - detector registry visibility
    - DB status for active sessions/escalations
    """
    from app.services.agents.concierge_health import run_concierge_health_checks

    report = await run_concierge_health_checks(db)
    return {
        "healthy": report.healthy,
        "checked_at": report.checked_at,
        "checks": report.checks,
        "warnings": report.warnings,
        "errors": report.errors,
    }


# ─────────────────────────────────────────────────────────────────────────────
# PMS Sync — on-demand force-sync
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/pms/sync/{session_token}")
async def force_sync_pms_session(
    session_token: str,
    db: AsyncSession = Depends(_get_db),
):
    """
    Force-sync a single session against the PMS immediately.

    Use this when the operator knows the PMS just updated (new door code
    issued, unit swap, etc.) and doesn't want to wait for the hourly batch.

    Returns a dict of changed fields, or an empty dict if PMS offline or
    no changes detected.
    """
    if db is None:
        raise HTTPException(503, "Database not available")

    from app.services.agents.pms_sync_agent import get_pms_sync_agent
    agent = get_pms_sync_agent()
    changes = await agent.sync_single_session(db, session_token=session_token)

    if changes is None:
        return {
            "status": "skipped",
            "reason": "PMS offline or session not found",
            "session_token": session_token,
        }

    return {
        "status": "synced",
        "session_token": session_token,
        "changed_fields": changes.get("changed_fields", {}),
        "synced_at": changes.get("synced_at"),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Experiment / Prompt Ops
# ─────────────────────────────────────────────────────────────────────────────

class RegisterVariantRequest(BaseModel):
    variant_id: str
    description: str
    canary_pct: float          # 0–100, e.g. 5.0 = 5 % canary
    system_prompt_override: Optional[str] = None
    config_overrides: dict = {}  # e.g. {"temperature": 0.5, "max_tokens": 100}
    auto_pause_thresholds: dict = {}  # e.g. {"escalation_rate": 2.0}


class PauseVariantRequest(BaseModel):
    reason: str = "manual"


@router.get("/experiments")
async def get_experiment_stats():
    """
    Per-variant aggregate metrics: sessions, turns, escalation rate,
    fallback rate, avg latency, avg cost.  Also includes auto-pause
    event history and current rollback status.

    Feed this into the operator dashboard Experiment tab.
    """
    from app.services.agents.experiment_registry import get_experiment_registry
    return get_experiment_registry().get_stats()


@router.post("/experiments/variants", status_code=201)
async def register_variant(req: RegisterVariantRequest):
    """
    Register a new prompt variant (or replace an existing candidate).

    The total canary percentage across all non-paused candidates must not
    exceed 100.  Control always receives the remainder.

    Example body:
      {
        "variant_id": "tone_b",
        "description": "Shorter, punchier responses",
        "canary_pct": 5,
        "config_overrides": {"max_tokens": 100}
      }
    """
    from app.services.agents.experiment_registry import (
        get_experiment_registry, PromptVariant
    )
    registry = get_experiment_registry()

    try:
        variant = PromptVariant(
            variant_id=req.variant_id,
            description=req.description,
            canary_pct=req.canary_pct,
            system_prompt_override=req.system_prompt_override,
            config_overrides=req.config_overrides,
            auto_pause_thresholds=req.auto_pause_thresholds or {
                "escalation_rate": 2.0,
                "fallback_rate": 3.0,
            },
        )
        registry.register(variant)
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    return {"status": "registered", "variant_id": req.variant_id}


@router.post("/experiments/variants/{variant_id}/pause")
async def pause_variant(variant_id: str, req: PauseVariantRequest, db: AsyncSession = Depends(_get_db)):
    """
    Hard rollback: immediately stop assigning sessions to this variant.
    Any in-flight session using this variant reverts to CONTROL on its
    next message turn.

    This is the primary safety lever — use it when a prompt change is
    causing elevated escalation or fallback rates.
    """
    from app.services.agents.experiment_registry import get_experiment_registry, persist_variant_event
    ok = get_experiment_registry().pause(variant_id, reason=req.reason)
    if not ok:
        raise HTTPException(404, f"Variant '{variant_id}' not found or is control")
    if db is not None:
        import asyncio
        asyncio.ensure_future(persist_variant_event(
            variant_id=variant_id, event_type="paused", db=db, reason=req.reason
        ))
    return {"status": "paused", "variant_id": variant_id, "reason": req.reason}


@router.post("/experiments/variants/{variant_id}/resume")
async def resume_variant(variant_id: str, db: AsyncSession = Depends(_get_db)):
    """
    Re-enable a paused variant.  Sessions will be re-assigned on their
    next turn.  Metrics are preserved — the rolling window continues.

    Only use after investigating the cause of the auto-pause or manual pause.
    """
    from app.services.agents.experiment_registry import get_experiment_registry, persist_variant_event
    ok = get_experiment_registry().resume(variant_id)
    if not ok:
        raise HTTPException(404, f"Variant '{variant_id}' not found or is control")
    if db is not None:
        import asyncio
        asyncio.ensure_future(persist_variant_event(
            variant_id=variant_id, event_type="resumed", db=db
        ))
    return {"status": "resumed", "variant_id": variant_id}
