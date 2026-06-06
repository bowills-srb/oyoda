"""
Operator API Endpoints

Endpoints for property managers to:
- Create guest sessions manually
- Send/resend concierge links
- View escalations
- Manage sessions
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from datetime import date, datetime
from typing import Optional, List
from uuid import UUID
import sqlalchemy as sa
import logging
import json

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import DBAPIError, ProgrammingError
from app.api.dependencies.request_tenant import resolve_request_tenant_id
from app.db.session import SessionLocal, get_async_session

from app.api.dependencies.ops_auth import require_ops_access
logger = logging.getLogger(__name__)

_PLATFORM_UPSELL_DEFAULTS: dict[str, float] = {
    "late_checkout": 35.0,
    "early_checkin": 35.0,
    "beach_chairs": 35.0,
    "pontoon": 250.0,
    "fishing": 180.0,
    "dolphin": 120.0,
    "golf": 150.0,
    "bikes": 40.0,
    "spa": 120.0,
    "groceries": 15.0,
    "mid_stay_clean": 75.0,
    "pool_heat": 50.0,
}

# Phase 4.3-D (resolved 2026-05-16):
# Previously, many endpoints here fell back to a sentinel tenant when the
# operator_id query param was absent. They now resolve tenant from JWT/cookie
# only via _require_tenant(request). The operator_id query parameter has been
# removed entirely. Super-admin scope-switching via oyvoda_scoped_tid cookie
# is honored upstream by resolve_request_tenant_id().
#
# Some endpoints here remain scheduled for retirement in Phase 4.6 (legacy
# concierge teardown). See docs/architecture/TENANT_ISOLATION_AUDIT.md for the
# hardening-vs-retirement classification of each endpoint.

router = APIRouter(
    prefix="/operator",
    tags=["Operator Dashboard"],
    dependencies=[Depends(require_ops_access)],
)


def _resolve_request_tenant_id(request: Request) -> Optional[UUID]:
    return resolve_request_tenant_id(request)


def _require_tenant(request: Request) -> UUID:
    """Require an authenticated tenant context."""
    tenant_id = resolve_request_tenant_id(request)
    if not tenant_id:
        raise HTTPException(
            status_code=401,
            detail="Authentication required: no tenant in token or cookie.",
        )
    return tenant_id


# =============================================================================
# Request Models
# =============================================================================

class CreateSessionRequest(BaseModel):
    """Create a new guest session"""
    reservation_id: str
    property_code: str
    property_name: Optional[str] = None  # If not provided, will look up from database
    guest_first_name: str
    guest_last_name: str
    guest_email: Optional[str] = None
    guest_phone: Optional[str] = None
    check_in: date
    check_out: date
    num_guests: int = 1
    operator_id: Optional[str] = None  # Operator scoping — defaults to Beach Habitats
    
    # Property context (WiFi, codes, etc.)
    wifi_network: Optional[str] = None
    wifi_password: Optional[str] = None
    door_code: Optional[str] = None
    check_in_time: str = "4:00 PM"
    check_out_time: str = "10:00 AM"
    parking_info: Optional[str] = None
    pool_heated: bool = False
    beach_access: Optional[str] = None
    special_notes: Optional[str] = None


class SendLinkRequest(BaseModel):
    """Send/resend concierge link"""
    send_sms: bool = True
    send_email: bool = True


class SessionResponse(BaseModel):
    token: str
    reservation_id: str
    property_name: str
    guest_name: str
    guest_phone: Optional[str]
    guest_email: Optional[str]
    check_in: date
    check_out: date
    phase: str
    concierge_url: str
    conversation_count: int
    created_at: str


class EscalationResponse(BaseModel):
    id: str
    guest_name: str
    property_name: str
    reason: str
    priority: str
    status: str
    summary: str
    created_at: str


# =============================================================================
# Session Management
# =============================================================================

@router.post("/sessions", response_model=SessionResponse)
async def create_session(payload: CreateSessionRequest, request: Request):
    """
    Create a new guest session and optionally send the link.
    
    Use this when:
    - Manually adding a guest (before Escapia integration)
    - Creating a session for a direct booking
    """
    from app.services.concierge.guest_session import get_session_manager
    from app.services.concierge.notification_service import get_notification_service
    
    manager = get_session_manager()
    notifications = get_notification_service()
    tenant_id = _require_tenant(request)
    
    # Look up property name from database if not provided
    property_name = payload.property_name
    if not property_name:
        try:
            # Try to look up from database by property code
            from app.db.session import get_db_session
            from sqlalchemy import text
            
            async with get_db_session() as db:
                result = await db.execute(
                    text("SELECT name FROM properties WHERE property_code = :code LIMIT 1"),
                    {"code": payload.property_code}
                )
                row = result.fetchone()
                if row:
                    property_name = row[0]
        except Exception as e:
            logger.warning(f"Could not look up property name: {e}")
    
    # Fallback to property code if still no name
    if not property_name:
        property_name = payload.property_code
    
    # Build property context
    property_context = {
        "wifi_network": payload.wifi_network,
        "wifi_password": payload.wifi_password,
        "door_code": payload.door_code,
        "check_in_time": payload.check_in_time,
        "check_out_time": payload.check_out_time,
        "parking_info": payload.parking_info,
        "pool_heated": payload.pool_heated,
        "beach_access": payload.beach_access,
        "special_notes": payload.special_notes,
    }
    # Remove None values
    property_context = {k: v for k, v in property_context.items() if v is not None}
    
    # Resolve operator branding from registry
    try:
        from app.models.operator import get_operator
        op = get_operator(payload.operator_id)
    except Exception:
        from app.models.operator import BEACH_HABITATS as op

    # Create session with operator branding
    session = await manager.create_session(
        reservation_id=payload.reservation_id,
        property_id=payload.property_code,  # Using code as ID for now
        property_code=payload.property_code,
        property_name=property_name,
        guest_first_name=payload.guest_first_name,
        guest_last_name=payload.guest_last_name,
        guest_email=payload.guest_email,
        guest_phone=payload.guest_phone,
        check_in=payload.check_in,
        check_out=payload.check_out,
        num_guests=payload.num_guests,
        property_context=property_context,
        tenant_id=tenant_id,
        operator_id=op.id,
        operator_name=op.name,
        operator_logo_url=op.branding.logo_url,
        operator_primary_color=op.branding.primary_color,
        operator_support_phone=op.branding.support_phone,
        concierge_name=op.branding.concierge_name,
        concierge_emoji=op.branding.concierge_emoji,
    )
    
    # ── Repeat-guest memory lookup ──────────────────────────────────────────
    # If we recognise this guest from a prior stay, fetch their profile
    # and inject context into the session so the concierge greets them
    # as a returning guest from message #1.
    try:
        from app.db.session import get_async_session as _gas
        from app.services.concierge.guest_profile_service import build_concierge_context

        _tid = tenant_id
        async with _gas() as _gdb:
            guest_ctx = await build_concierge_context(
                _gdb,
                tenant_id=_tid,
                phone=payload.guest_phone,
                email=payload.guest_email,
            )
        if guest_ctx:
            # Merge into property_context so the concierge MCP tool sees it
            merged_ctx = {**property_context, "guest_profile": guest_ctx}
            session.property_context = merged_ctx
            await manager.update_session(session)
            logger.info(
                f"Repeat guest detected — {payload.guest_first_name}, "
                f"{guest_ctx.get('total_stays')} prior stays"
            )
    except Exception as e:
        logger.warning(f"Guest profile lookup failed (non-fatal): {e}")

    return SessionResponse(
        token=session.token,
        reservation_id=session.reservation_id,
        property_name=session.property_name,
        guest_name=session.guest_name,
        guest_phone=session.guest_phone,
        guest_email=session.guest_email,
        check_in=session.check_in,
        check_out=session.check_out,
        phase=session.phase.value,
        concierge_url=notifications.get_concierge_url(session.token),
        conversation_count=session.conversation_count,
        created_at=session.created_at.isoformat(),
    )


@router.post("/sessions/{token}/send-link")
async def send_concierge_link(token: str, request: SendLinkRequest):
    """
    Send or resend the concierge link to a guest.
    
    Use this to:
    - Send initial welcome message
    - Resend if guest lost the link
    - Send check-in day reminder
    """
    from app.services.concierge.guest_session import get_session_manager
    from app.services.concierge.notification_service import get_notification_service
    
    manager = get_session_manager()
    notifications = get_notification_service()
    
    session = await manager.get_session(token)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    results = await notifications.send_welcome_notification(
        session,
        send_sms=request.send_sms,
        send_email=request.send_email,
    )
    
    return {
        "status": "ok",
        "token": token,
        "concierge_url": notifications.get_concierge_url(token),
        "delivery_results": results,
    }


@router.get("/sessions", response_model=List[SessionResponse])
async def list_sessions(
    request: Request,
    property_code: Optional[str] = None,
    phase: Optional[str] = None,
):
    """List all guest sessions from DB, optionally filtered."""
    from app.services.concierge.db_session_service import get_db_session_service
    from app.services.concierge.notification_service import get_notification_service
    from app.db.session import get_async_session

    notifications = get_notification_service()
    svc = get_db_session_service()
    tenant_id = _require_tenant(request)

    async with get_async_session() as db:
        db_sessions = await svc.list_sessions(
            db,
            property_code=property_code,
            phase=phase,
            limit=200,
            tenant_id=tenant_id,
        )

    return [
        SessionResponse(
            token=s.token,
            reservation_id=str(s.session_id),
            property_name=s.property_name,
            guest_name=s.guest_name,
            guest_phone=s.guest_phone,
            guest_email=s.guest_email,
            check_in=s.check_in,
            check_out=s.check_out,
            phase=s.phase,
            concierge_url=notifications.get_concierge_url(s.token),
            conversation_count=s.conversation_count or 0,
            created_at=s.created_at.isoformat(),
        )
        for s in db_sessions
    ]


@router.get("/sessions/{token}", response_model=SessionResponse)
async def get_session(token: str):
    """Get session details"""
    from app.services.concierge.guest_session import get_session_manager
    from app.services.concierge.notification_service import get_notification_service
    
    manager = get_session_manager()
    notifications = get_notification_service()
    
    session = await manager.get_session(token)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return SessionResponse(
        token=session.token,
        reservation_id=session.reservation_id,
        property_name=session.property_name,
        guest_name=session.guest_name,
        guest_phone=session.guest_phone,
        guest_email=session.guest_email,
        check_in=session.check_in,
        check_out=session.check_out,
        phase=session.phase.value,
        concierge_url=notifications.get_concierge_url(session.token),
        conversation_count=session.conversation_count,
        created_at=session.created_at.isoformat(),
    )


# =============================================================================
# Escalations
# =============================================================================

@router.get("/escalations", response_model=List[EscalationResponse])
async def list_escalations(status: Optional[str] = None, operator_id: Optional[str] = None):
    """List escalation tickets"""
    from app.services.concierge.escalation_service import get_escalation_service
    
    service = get_escalation_service()
    
    # Refresh from DB if in-memory cache is empty (e.g. after restart)
    if not service._tickets:
        await service.load_pending_from_db()
    
    if status == "pending":
        tickets = service.get_pending_tickets()
    else:
        tickets = list(service._tickets.values())
    
    # Sort by priority then time
    priority_order = {"urgent": 0, "high": 1, "medium": 2, "low": 3}
    tickets.sort(key=lambda t: (priority_order.get(t.priority.value, 4), t.created_at))
    
    return [
        EscalationResponse(
            id=t.id,
            guest_name=t.guest_name,
            property_name=t.property_name,
            reason=t.reason.value,
            priority=t.priority.value,
            status=t.status.value,
            summary=t.summary,
            created_at=t.created_at.isoformat(),
        )
        for t in tickets
    ]


@router.post("/escalations/{ticket_id}/acknowledge")
async def acknowledge_escalation(ticket_id: str, operator: str = "operator"):
    """
    Acknowledge an escalation ticket.
    Starts the SLA clock — ack_sla_breached will fire if not resolved in time.
    """
    from app.services.agents.escalation_handoff_agent import get_escalation_handoff_agent
    from app.db.session import get_async_session

    agent = get_escalation_handoff_agent()
    async with get_async_session() as db:
        ok = await agent.acknowledge_ticket(db, ticket_id, operator)

    if not ok:
        raise HTTPException(status_code=404, detail="Ticket not found")

    return {"status": "ok", "ticket_id": ticket_id}


@router.post("/escalations/{ticket_id}/resolve")
async def resolve_escalation(
    ticket_id: str,
    operator: str = "operator",
    note: str = "Resolved",
    resolution_code: Optional[str] = None,
):
    """
    Resolve an escalation ticket.
    Records resolve time, checks SLA compliance, logs to Watch Layer.
    """
    from app.services.agents.escalation_handoff_agent import get_escalation_handoff_agent
    from app.db.session import get_async_session

    agent = get_escalation_handoff_agent()
    async with get_async_session() as db:
        ok = await agent.close_ticket(db, ticket_id, operator, note, resolution_code)

    if not ok:
        raise HTTPException(status_code=404, detail="Ticket not found")

    return {"status": "ok", "ticket_id": ticket_id}


@router.get("/escalations/sla-stats")
async def get_escalation_sla_stats():
    """
    SLA performance stats across all escalation tickets.

    Returns p50/p95 ack and resolve times, breach counts, and breach rate.
    Used by the Escalations tab to surface SLA health at a glance.
    """
    from app.services.agents.escalation_handoff_agent import get_escalation_handoff_agent
    from app.db.session import get_async_session

    agent = get_escalation_handoff_agent()
    async with get_async_session() as db:
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
    }


# =============================================================================
# Proactive Journey
# =============================================================================

@router.get("/sessions/{token}/journey")
async def get_guest_journey(token: str, db: AsyncSession = Depends(get_async_session)):
    """Get proactive journey status for a guest"""
    from app.services.operator.stay_journey_service import get_journey_summary_by_token

    summary = await get_journey_summary_by_token(db, token)
    if not summary:
        raise HTTPException(status_code=404, detail="Journey not found")

    return summary


@router.post("/sessions/{token}/journey/{activity_type}/status")
async def update_activity_status(
    token: str,
    activity_type: str,
    status: str = "handled",
    notes: Optional[str] = None,
    db: AsyncSession = Depends(get_async_session),
):
    """Update the status of an activity (booked, not_interested, handled)"""
    from app.services.operator.stay_journey_service import update_activity_status_by_token

    status_map = {
        "booked": "booked",
        "not_interested": "not_interested",
        "handled": "handled",
        "info_provided": "info_provided",
    }

    normalized_status = status_map.get(status)
    if not normalized_status:
        raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

    activity = await update_activity_status_by_token(
        db,
        token,
        activity_type=activity_type,
        status=normalized_status,
        notes=notes,
    )

    if not activity:
        raise HTTPException(status_code=404, detail="Journey not found")

    return {"status": "ok", "activity": activity}


@router.get("/sessions/{token}/journey/welcome")
async def get_welcome_message(token: str, db: AsyncSession = Depends(get_async_session)):
    """Preview the current canonical welcome-style proactive message, if due."""
    from app.services.operator.stay_journey_service import get_canonical_proactive_preview_by_token

    preview = await get_canonical_proactive_preview_by_token(
        db,
        token,
        allowed_touch_types={"pre_arrival_welcome", "arrival_day_checkin", "arrival_info"},
    )
    if not preview:
        return {"message": None, "already_sent": True}

    return {"message": preview["message"], "already_sent": False, "touch_type": preview["touch_type"]}


@router.get("/sessions/{token}/journey/extend-offer")
async def get_extend_stay_offer(
    token: str,
    next_guest_arriving: bool = False,
    db: AsyncSession = Depends(get_async_session),
):
    """
    Get extend stay offer (10% off extra night).
    Only returns offer if no guest arriving the next day.
    
    Call this the day before checkout to offer the guest an extra night.
    """
    from app.services.operator.stay_journey_service import get_canonical_proactive_preview_by_token

    if next_guest_arriving:
        return {
            "offer_available": False,
            "reason": "Next guest arriving",
            "message": None,
        }

    preview = await get_canonical_proactive_preview_by_token(
        db,
        token,
        allowed_touch_types={"extend_offer"},
    )
    if not preview:
        return {
            "offer_available": False,
            "reason": "No extend-offer touch currently due",
            "message": None,
        }

    return {
        "offer_available": True,
        "discount": "10%",
        "message": preview["message"],
    }


# =============================================================================
# Knowledge Curator — gap drafts
# =============================================================================

@router.get("/knowledge-gap-drafts")
async def list_gap_drafts(
    property_code: Optional[str] = None,
    status: str = "pending_review",
):
    """
    List FAQ drafts generated by KnowledgeCuratorAgent from clustered gaps.

    Default returns drafts awaiting operator review.  Operator fills in the
    answer and calls /approve to index it into the vector store.
    """
    from app.services.agents.knowledge_curator_agent import get_knowledge_curator_agent
    from app.db.session import get_async_session

    agent = get_knowledge_curator_agent()
    async with get_async_session() as db:
        drafts = await agent.get_pending_drafts(db, property_code=property_code)

    return drafts


@router.post("/knowledge-gap-drafts/{draft_id}/approve")
async def approve_gap_draft(
    draft_id: str,
    operator: str = "operator",
    answer: Optional[str] = None,
):
    """
    Approve a FAQ draft and index it into the property knowledge base.

    If `answer` is provided it overrides the draft's answer_hint.
    On success the FAQ is indexed and retrieval hit rate improves for the
    property the next time a guest asks a similar question.
    """
    from app.services.agents.knowledge_curator_agent import get_knowledge_curator_agent
    from app.db.session import get_async_session

    agent = get_knowledge_curator_agent()
    async with get_async_session() as db:
        doc_id = await agent.approve_draft(db, draft_id=draft_id, operator=operator, answer=answer)

    if not doc_id:
        raise HTTPException(
            status_code=422,
            detail="Draft not found, already processed, or answer is missing.",
        )

    return {"status": "ok", "draft_id": draft_id, "doc_id": doc_id}


@router.post("/knowledge-gap-drafts/{draft_id}/reject")
async def reject_gap_draft(
    draft_id: str,
    operator: str = "operator",
    reason: Optional[str] = None,
):
    """Reject a draft so it no longer appears in the review queue."""
    from app.services.agents.knowledge_curator_agent import get_knowledge_curator_agent
    from app.db.session import get_async_session

    agent = get_knowledge_curator_agent()
    async with get_async_session() as db:
        ok = await agent.reject_draft(db, draft_id=draft_id, operator=operator, reason=reason)

    if not ok:
        raise HTTPException(status_code=404, detail="Draft not found")

    return {"status": "ok", "draft_id": draft_id}


@router.post("/knowledge-gap-drafts/run-curation")
async def trigger_knowledge_curation(
    property_code: Optional[str] = None,
):
    """
    Trigger an on-demand knowledge curation run (normally runs daily via Celery).

    Scans recent gaps, clusters similar questions, and creates drafts for
    operator review.  Useful after onboarding a new property or after a spike
    in guest questions.
    """
    from app.services.agents.knowledge_curator_agent import get_knowledge_curator_agent
    from app.db.session import get_async_session

    agent = get_knowledge_curator_agent()
    async with get_async_session() as db:
        report = await agent.curate_gaps(db, property_code=property_code)

    return {
        "status": "ok",
        "gaps_scanned": report.gaps_scanned,
        "clusters_found": report.clusters_found,
        "drafts_created": report.drafts_created,
        "drafts_already_pending": report.drafts_already_pending,
        "errors": report.errors,
        "top_gaps": report.top_gaps,
    }


# =============================================================================
# PMS Sync — on-demand
# =============================================================================

@router.post("/sessions/{token}/sync-pms")
async def force_pms_sync(token: str):
    """
    Force an immediate PMS sync for a single session.

    Use this when the property manager knows a change was made in Escapia
    (new door code, unit swap, etc.) and doesn't want to wait for the hourly
    background sync to pick it up.

    Returns the changed fields, or empty dict if PMS offline or no change.
    """
    from app.services.agents.pms_sync_agent import get_pms_sync_agent
    from app.db.session import get_async_session

    agent = get_pms_sync_agent()
    async with get_async_session() as db:
        changes = await agent.sync_single_session(db, session_token=token)

    if changes is None:
        return {"status": "no_change", "message": "PMS offline or session not found"}

    if not changes.get("changed_fields"):
        return {"status": "no_change", "message": "Session already up to date"}

    return {"status": "updated", "changes": changes}


# =============================================================================
# Conversation History
# =============================================================================

@router.get("/sessions/{token}/messages")
async def get_session_messages(token: str, limit: int = 50):
    """Get conversation history for a session."""
    from app.db.session import get_async_session
    from sqlalchemy import select, text
    from db.models.concierge_sessions import ConciergeMessageModel, ConciergeGuestSessionModel

    try:
        async with get_async_session() as db:
            # Resolve token -> session_id
            sess_row = (await db.execute(
                select(ConciergeGuestSessionModel.session_id)
                .where(ConciergeGuestSessionModel.token == token)
            )).scalar_one_or_none()

            if not sess_row:
                raise HTTPException(status_code=404, detail="Session not found")

            messages = (await db.execute(
                select(ConciergeMessageModel)
                .where(ConciergeMessageModel.session_id == sess_row)
                .order_by(ConciergeMessageModel.created_at.asc())
                .limit(limit)
            )).scalars().all()

        return [
            {
                "message_id": str(m.message_id),
                "direction": m.direction,
                "content": m.content,
                "content_type": m.content_type,
                "detected_intent": m.detected_intent,
                "was_quick_answer": m.was_quick_answer,
                "response_time_ms": m.response_time_ms,
                "created_at": m.created_at.isoformat(),
            }
            for m in messages
        ]
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"Messages query failed: {e}")
        return []


# =============================================================================
# Knowledge Gaps
# =============================================================================

@router.get("/knowledge-gaps")
async def list_knowledge_gaps(
    request: Request,
    resolved: Optional[bool] = False,
    limit: int = 100,
):
    """List unanswered / weak guest questions for operator review."""
    from app.db.session import get_async_session
    from sqlalchemy import select
    from db.models.concierge_knowledge import ConciergeKnowledgeGapModel
    tenant = str(_require_tenant(request))
    try:
        async with get_async_session() as db:
            q = (
                select(ConciergeKnowledgeGapModel)
                .where(
                    ConciergeKnowledgeGapModel.tenant_id == tenant,
                    ConciergeKnowledgeGapModel.resolved == resolved,
                )
                .order_by(ConciergeKnowledgeGapModel.created_at.desc())
                .limit(limit)
            )
            gaps = (await db.execute(q)).scalars().all()

        return [
            {
                "gap_id": str(g.gap_id),
                "question_text": g.question_text,
                "property_external_id": g.property_external_id,
                "stage": g.stage,
                "channel": g.channel,
                "detected_intent": g.detected_intent,
                "confidence_score": g.confidence_score,
                "resolved": g.resolved,
                "resolution_notes": g.resolution_notes,
                "created_at": g.created_at.isoformat(),
            }
            for g in gaps
        ]
    except Exception as e:
        logger.warning(f"Knowledge gaps query failed: {e}")
        return []


@router.post("/knowledge-gaps/{gap_id}/resolve")
async def resolve_knowledge_gap(request: Request, gap_id: str, notes: str = ""):
    """Mark a knowledge gap as resolved with optional resolution notes."""
    from app.db.session import get_async_session
    from sqlalchemy import update
    from db.models.concierge_knowledge import ConciergeKnowledgeGapModel
    import uuid
    tenant_id = str(_require_tenant(request))

    try:
        async with get_async_session() as db:
            await db.execute(
                update(ConciergeKnowledgeGapModel)
                .where(
                    ConciergeKnowledgeGapModel.gap_id == uuid.UUID(gap_id),
                    ConciergeKnowledgeGapModel.tenant_id == tenant_id,
                )
                .values(resolved=True, resolution_notes=notes)
            )
            await db.commit()
        return {"status": "ok", "gap_id": gap_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Analytics
# =============================================================================

@router.get("/analytics")
async def get_analytics(request: Request, days: int = 30):
    """
    Conversation analytics for the past N days.
    Returns daily message volumes, intent breakdown, quick-answer rate,
    response time distribution, and escalation trend.
    """
    from app.db.session import get_async_session
    from sqlalchemy import select, func, text
    from db.models.concierge_sessions import (
        ConciergeGuestSessionModel,
        ConciergeMessageModel,
    )
    from db.models.concierge_knowledge import ConciergeKnowledgeGapModel
    import datetime as _dt

    cutoff = _dt.datetime.utcnow() - _dt.timedelta(days=days)

    result = {
        "period_days": days,
        "daily_volumes": [],
        "intent_breakdown": {},
        "quick_answer_rate": 0.0,
        "avg_response_ms": 0,
        "total_inbound": 0,
        "total_outbound": 0,
        "total_gaps": 0,
        "sessions_created": 0,
        "phase_distribution": {},
    }

    analytics_tenant = str(_require_tenant(request))
    try:
        async with get_async_session() as db:
            # Daily message volume (inbound only, last N days)
            daily_rows = (await db.execute(text("""
                SELECT
                    DATE(m.created_at) AS day,
                    COUNT(*) FILTER (WHERE m.direction = 'inbound') AS inbound,
                    COUNT(*) FILTER (WHERE m.direction = 'outbound') AS outbound,
                    COUNT(*) FILTER (WHERE m.was_quick_answer = true) AS quick
                FROM concierge_messages m
                JOIN concierge_guest_sessions s ON s.session_id = m.session_id
                WHERE s.tenant_id = :tid
                  AND m.created_at >= :cutoff
                GROUP BY DATE(m.created_at)
                ORDER BY day ASC
            """), {"tid": analytics_tenant, "cutoff": cutoff})).fetchall()

            result["daily_volumes"] = [
                {"date": str(r.day), "inbound": r.inbound, "outbound": r.outbound, "quick": r.quick}
                for r in daily_rows
            ]

            # Totals
            totals = (await db.execute(text("""
                SELECT
                    COUNT(*) FILTER (WHERE m.direction = 'inbound') AS total_in,
                    COUNT(*) FILTER (WHERE m.direction = 'outbound') AS total_out,
                    COUNT(*) FILTER (WHERE m.was_quick_answer = true) AS total_quick,
                    AVG(m.response_time_ms) FILTER (WHERE m.direction = 'outbound' AND m.response_time_ms IS NOT NULL) AS avg_ms
                FROM concierge_messages m
                JOIN concierge_guest_sessions s ON s.session_id = m.session_id
                WHERE s.tenant_id = :tid AND m.created_at >= :cutoff
            """), {"tid": analytics_tenant, "cutoff": cutoff})).fetchone()

            if totals:
                ti = totals.total_in or 0
                tq = totals.total_quick or 0
                result["total_inbound"] = ti
                result["total_outbound"] = totals.total_out or 0
                result["quick_answer_rate"] = round(tq / ti, 3) if ti > 0 else 0.0
                result["avg_response_ms"] = int(totals.avg_ms or 0)

            # Intent breakdown
            intent_rows = (await db.execute(text("""
                SELECT detected_intent, COUNT(*) AS cnt
                FROM concierge_messages m
                JOIN concierge_guest_sessions s ON s.session_id = m.session_id
                WHERE s.tenant_id = :tid
                  AND m.direction = 'inbound'
                  AND m.detected_intent IS NOT NULL
                  AND m.created_at >= :cutoff
                GROUP BY detected_intent
                ORDER BY cnt DESC
                LIMIT 15
            """), {"tid": analytics_tenant, "cutoff": cutoff})).fetchall()

            result["intent_breakdown"] = {r.detected_intent: r.cnt for r in intent_rows}

            # Sessions created in period
            sess_count = (await db.execute(text("""
                SELECT COUNT(*) FROM concierge_guest_sessions
                WHERE tenant_id = :tid AND created_at >= :cutoff
            """), {"tid": analytics_tenant, "cutoff": cutoff})).scalar()
            result["sessions_created"] = sess_count or 0

            # Phase distribution (current active sessions)
            phase_rows = (await db.execute(text("""
                SELECT phase, COUNT(*) AS cnt
                FROM concierge_guest_sessions
                WHERE tenant_id = :tid AND status = 'active'
                GROUP BY phase
            """), {"tid": analytics_tenant})).fetchall()
            result["phase_distribution"] = {r.phase: r.cnt for r in phase_rows}

            # Open knowledge gaps
            gap_count = (await db.execute(text("""
                SELECT COUNT(*) FROM concierge_knowledge_gaps
                WHERE tenant_id = :tid AND resolved = false
            """), {"tid": analytics_tenant})).scalar()
            result["total_gaps"] = gap_count or 0

    except Exception as e:
        logger.warning(f"Analytics query failed: {e}")

    return result


# =============================================================================
# Inquiry Heatmap  (day-of-week × hour-of-day message volume)
# =============================================================================

@router.get("/analytics/heatmap")
async def get_inquiry_heatmap(
    request: Request,
    days: int = 90,
):
    """
    Returns a 7×24 matrix of inbound message counts bucketed by
    day-of-week (0=Sun … 6=Sat) and hour-of-day (0–23, America/Chicago).

    Used to render the operator dashboard inquiry heatmap so property
    managers can see exactly when guests are most active and plan staffing.

    Each cell: { day: int, hr: int, value: int }
    """
    from sqlalchemy import text
    import datetime as _dt

    tenant = str(_require_tenant(request))
    cutoff = _dt.datetime.utcnow() - _dt.timedelta(days=days)

    try:
        async with get_async_session() as db:
            rows = (await db.execute(text("""
                SELECT
                    EXTRACT(DOW  FROM m.created_at AT TIME ZONE 'America/Chicago')::int AS dow,
                    EXTRACT(HOUR FROM m.created_at AT TIME ZONE 'America/Chicago')::int AS hr,
                    COUNT(*) AS value
                FROM concierge_messages m
                JOIN concierge_guest_sessions s ON s.session_id = m.session_id
                WHERE s.tenant_id = :tid
                  AND m.direction   = 'inbound'
                  AND m.created_at >= :cutoff
                GROUP BY dow, hr
                ORDER BY dow, hr
            """), {"tid": tenant, "cutoff": cutoff})).fetchall()

        # Build a full 7×24 grid so the frontend never has to deal with missing cells
        grid: dict[tuple[int, int], int] = {(r.dow, r.hr): r.value for r in rows}
        cells = [
            {"day": dow, "hr": hr, "value": grid.get((dow, hr), 0)}
            for dow in range(7)
            for hr  in range(24)
        ]
        return {"days": days, "timezone": "America/Chicago", "cells": cells}

    except Exception as e:
        logger.warning(f"Heatmap query failed: {e}")
        return {"days": days, "timezone": "America/Chicago", "cells": []}


# =============================================================================
# Per-Property Analytics  (CSAT, resolution rate, inquiry volume, issues)
# =============================================================================

@router.get("/analytics/properties")
async def get_property_analytics(
    request: Request,
    days: int = 30,
    limit: int = 50,
):
    """
    Per-property breakdown used by the Property Leaderboard dashboard tab.

    For each property returns:
      - inquiry_count          total inbound messages in period
      - avg_csat               mean guest feedback_rating (1–5)
      - resolution_rate_pct    % of inbound messages answered by quick-answer or AI
      - escalation_count       open escalations for the property
      - kb_gap_count           unresolved knowledge gaps
      - session_count          sessions active in period

    Sorted by inquiry_count DESC so the noisiest properties surface first
    (high inquiry count often means unclear listing info or missing KB entries).
    """
    from app.db.session import get_async_session
    from sqlalchemy import text
    import datetime as _dt

    tenant = str(_require_tenant(request))
    cutoff = _dt.datetime.utcnow() - _dt.timedelta(days=days)

    try:
        async with get_async_session() as db:
            rows = (await db.execute(text("""
                SELECT
                    s.property_code,
                    MAX(s.property_name)                                        AS property_name,
                    COUNT(DISTINCT s.session_id)                                AS session_count,
                    COUNT(m.message_id) FILTER (WHERE m.direction = 'inbound') AS inquiry_count,
                    ROUND(
                        AVG(s.feedback_rating) FILTER (WHERE s.feedback_rating IS NOT NULL),
                        2
                    )                                                           AS avg_csat,
                    ROUND(
                        100.0 * COUNT(m.message_id) FILTER (
                            WHERE m.direction = 'inbound'
                              AND m.was_quick_answer = true
                        ) / NULLIF(
                            COUNT(m.message_id) FILTER (WHERE m.direction = 'inbound'), 0
                        ),
                        1
                    )                                                           AS resolution_rate_pct
                FROM concierge_guest_sessions s
                LEFT JOIN concierge_messages m
                       ON m.session_id = s.session_id
                      AND m.created_at >= :cutoff
                WHERE s.tenant_id = :tid
                  AND s.created_at >= :cutoff
                GROUP BY s.property_code
                ORDER BY inquiry_count DESC
                LIMIT :lim
            """), {"tid": tenant, "cutoff": cutoff, "lim": limit})).fetchall()

            # Escalation counts per property (open only)
            esc_rows = (await db.execute(text("""
                SELECT property_code, COUNT(*) AS cnt
                FROM concierge_escalations
                WHERE status NOT IN ('resolved', 'closed')
                GROUP BY property_code
            """))).fetchall()
            esc_map: dict[str, int] = {r.property_code: r.cnt for r in esc_rows}

            # KB gap counts per property
            gap_rows = (await db.execute(text("""
                SELECT property_external_id, COUNT(*) AS cnt
                FROM concierge_knowledge_gaps
                WHERE tenant_id = :tid AND resolved = false
                  AND property_external_id IS NOT NULL
                GROUP BY property_external_id
            """), {"tid": tenant})).fetchall()
            gap_map: dict[str, int] = {r.property_external_id: r.cnt for r in gap_rows}

        return [
            {
                "property_code":        r.property_code,
                "property_name":        r.property_name,
                "session_count":        r.session_count or 0,
                "inquiry_count":        r.inquiry_count or 0,
                "avg_csat":             float(r.avg_csat) if r.avg_csat else None,
                "resolution_rate_pct":  float(r.resolution_rate_pct) if r.resolution_rate_pct else None,
                "escalation_count":     esc_map.get(r.property_code, 0),
                "kb_gap_count":         gap_map.get(r.property_code, 0),
            }
            for r in rows
        ]

    except Exception as e:
        logger.warning(f"Property analytics query failed: {e}")
        return []


# =============================================================================
# Response Time Distribution  (bucket message response_time_ms)
# =============================================================================

@router.get("/analytics/response-times")
async def get_response_time_distribution(
    request: Request,
    days: int = 30,
):
    """
    Buckets outbound AI response times into four ranges and returns counts
    + percentages.  Used by the Response Time Distribution dashboard card.

    Buckets:
      - sub_1s      response_time_ms < 1 000
      - one_to_3s   1 000 – 2 999 ms
      - three_to_10s 3 000 – 9 999 ms
      - over_10s    >= 10 000 ms

    Also returns p50 / p95 / p99 percentiles and the overall mean.
    """
    from app.db.session import get_async_session
    from sqlalchemy import text
    import datetime as _dt

    tenant = str(_require_tenant(request))
    cutoff = _dt.datetime.utcnow() - _dt.timedelta(days=days)

    try:
        async with get_async_session() as db:
            row = (await db.execute(text("""
                SELECT
                    COUNT(*) FILTER (WHERE m.response_time_ms < 1000)                  AS sub_1s,
                    COUNT(*) FILTER (WHERE m.response_time_ms BETWEEN 1000 AND 2999)   AS one_to_3s,
                    COUNT(*) FILTER (WHERE m.response_time_ms BETWEEN 3000 AND 9999)   AS three_to_10s,
                    COUNT(*) FILTER (WHERE m.response_time_ms >= 10000)                AS over_10s,
                    COUNT(*) FILTER (WHERE m.response_time_ms IS NOT NULL)             AS total,
                    ROUND(AVG(m.response_time_ms))                                     AS avg_ms,
                    PERCENTILE_CONT(0.50) WITHIN GROUP
                        (ORDER BY m.response_time_ms) FILTER (WHERE m.response_time_ms IS NOT NULL) AS p50,
                    PERCENTILE_CONT(0.95) WITHIN GROUP
                        (ORDER BY m.response_time_ms) FILTER (WHERE m.response_time_ms IS NOT NULL) AS p95,
                    PERCENTILE_CONT(0.99) WITHIN GROUP
                        (ORDER BY m.response_time_ms) FILTER (WHERE m.response_time_ms IS NOT NULL) AS p99
                FROM concierge_messages m
                JOIN concierge_guest_sessions s ON s.session_id = m.session_id
                WHERE s.tenant_id     = :tid
                  AND m.direction     = 'outbound'
                  AND m.created_at   >= :cutoff
                  AND m.content_type != 'system'
            """), {"tid": tenant, "cutoff": cutoff})).fetchone()

        if not row or not row.total:
            return {"buckets": [], "percentiles": {}, "avg_ms": 0, "total": 0}

        total = row.total or 1  # guard div/0
        buckets = [
            {
                "range":  "< 1s",
                "label":  "sub_1s",
                "count":  row.sub_1s      or 0,
                "pct":    round((row.sub_1s      or 0) / total * 100, 1),
            },
            {
                "range":  "1 – 3s",
                "label":  "one_to_3s",
                "count":  row.one_to_3s   or 0,
                "pct":    round((row.one_to_3s   or 0) / total * 100, 1),
            },
            {
                "range":  "3 – 10s",
                "label":  "three_to_10s",
                "count":  row.three_to_10s or 0,
                "pct":    round((row.three_to_10s or 0) / total * 100, 1),
            },
            {
                "range":  "> 10s",
                "label":  "over_10s",
                "count":  row.over_10s    or 0,
                "pct":    round((row.over_10s    or 0) / total * 100, 1),
            },
        ]
        return {
            "days":    days,
            "total":   row.total,
            "avg_ms":  int(row.avg_ms or 0),
            "buckets": buckets,
            "percentiles": {
                "p50": int(row.p50 or 0),
                "p95": int(row.p95 or 0),
                "p99": int(row.p99 or 0),
            },
        }

    except Exception as e:
        logger.warning(f"Response time distribution query failed: {e}")
        return {"buckets": [], "percentiles": {}, "avg_ms": 0, "total": 0}


# =============================================================================
# Revenue & Upsell Impact
# =============================================================================

@router.get("/analytics/revenue")
async def get_revenue_impact(
    request: Request,
    months: int = 6,
):
    """
    Quantifies the dollar value Beach Habitats AI created for the operator.

    Two revenue streams tracked:

    1. Staff hours saved
       Each AI-resolved inbound message = ~4 min of staff time avoided.
       Valued at $25/hr (conservative front-desk/PM rate).
       Formula: (quick_answer_count * 4 / 60) * 25

    2. Upsell conversions
       Tracks booked activities from concierge_journey_activities grouped
       by activity_type.  Each activity type carries a default revenue
       estimate (configurable via operator_policy in the future).

    Returns:
      - monthly[]  { month, staff_hours_saved, staff_value_usd,
                     upsell_bookings, upsell_value_usd, total_value_usd }
      - upsell_breakdown[]  { activity_type, bookings, estimated_value_usd }
      - totals     { staff_value_usd, upsell_value_usd, total_value_usd,
                     hours_saved, total_upsell_bookings }
    """
    from app.db.session import get_async_session
    from sqlalchemy import text
    import datetime as _dt

    cutoff = _dt.datetime.utcnow() - _dt.timedelta(days=months * 30)

    # ── Platform-wide default upsell rates (USD) ────────────────────────────
    # These are overridden per-activity by operator_policies.upsell_rates.
    # Operators set their own rates during onboarding; if a rate is missing
    # from their policy record we fall back to this table.
    STAFF_RATE_USD    = 25.0   # $/hr
    MINS_PER_MSG      = 4.0    # staff-minutes saved per AI-resolved message

    # ── Load operator-specific upsell rates from policy table ─────────────────
    operator_upsell_rates: dict[str, float] = {}
    upsell_rates_configured: bool | None = None
    tenant = str(_require_tenant(request))
    try:
        async with SessionLocal() as _pdb:
            _policy_row = (await _pdb.execute(text("""
                SELECT upsell_rates, upsell_rates_configured
                FROM operator_policies
                WHERE tenant_id = CAST(:tid AS uuid)
                LIMIT 1
            """), {"tid": tenant})).fetchone()
            if _policy_row and _policy_row.upsell_rates:
                operator_upsell_rates = dict(_policy_row.upsell_rates)
                upsell_rates_configured = _policy_row.upsell_rates_configured
    except ProgrammingError as exc:
        logger.warning(
            "operator_policies upsell rate load hit schema issue; tenant_id=%s endpoint=revenue err=%s",
            tenant,
            exc,
            exc_info=True,
        )
    except DBAPIError as exc:
        logger.warning(
            "operator_policies upsell rate load failed; tenant_id=%s endpoint=revenue err=%s",
            tenant,
            exc,
        )

    # Merge: operator rates win over platform defaults, per-key
    UPSELL_VALUES: dict[str, float] = {**_PLATFORM_UPSELL_DEFAULTS, **operator_upsell_rates}
    avg_upsell_val_base = sum(_PLATFORM_UPSELL_DEFAULTS.values()) / len(_PLATFORM_UPSELL_DEFAULTS)

    try:
        async with SessionLocal() as db:
            # Monthly quick-answer counts (staff time saved)
            monthly_qa = (await db.execute(text("""
                SELECT
                    TO_CHAR(m.created_at AT TIME ZONE 'America/Chicago', 'YYYY-MM') AS month,
                    COUNT(*) FILTER (WHERE m.was_quick_answer = true)                AS quick_count,
                    COUNT(*) FILTER (WHERE m.direction = 'inbound')                  AS inbound_count
                FROM concierge_messages m
                JOIN concierge_guest_sessions s ON s.session_id = m.session_id
                WHERE s.tenant_id   = :tid
                  AND m.created_at >= :cutoff
                GROUP BY month
                ORDER BY month ASC
            """), {"tid": tenant, "cutoff": cutoff})).fetchall()

            # Monthly upsell bookings from journey activities
            monthly_upsell = (await db.execute(text("""
                SELECT
                    TO_CHAR(a.updated_at AT TIME ZONE 'America/Chicago', 'YYYY-MM') AS month,
                    COUNT(*) AS bookings
                FROM concierge_journey_activities a
                JOIN concierge_guest_journeys    j ON j.journey_id  = a.journey_id
                JOIN concierge_guest_sessions    s ON s.session_id  = j.session_id
                WHERE s.tenant_id  = :tid
                  AND a.status     = 'booked'
                  AND a.updated_at >= :cutoff
                GROUP BY month
                ORDER BY month ASC
            """), {"tid": tenant, "cutoff": cutoff})).fetchall()

            # Upsell breakdown by activity type
            upsell_breakdown = (await db.execute(text("""
                SELECT
                    a.activity_type,
                    COUNT(*) AS bookings
                FROM concierge_journey_activities a
                JOIN concierge_guest_journeys    j ON j.journey_id = a.journey_id
                JOIN concierge_guest_sessions    s ON s.session_id = j.session_id
                WHERE s.tenant_id  = :tid
                  AND a.status     = 'booked'
                  AND a.updated_at >= :cutoff
                GROUP BY a.activity_type
                ORDER BY bookings DESC
            """), {"tid": tenant, "cutoff": cutoff})).fetchall()

        # Build month-keyed maps
        qa_map: dict[str, tuple[int, int]] = {
            r.month: (r.quick_count, r.inbound_count) for r in monthly_qa
        }
        upsell_map: dict[str, int] = {r.month: r.bookings for r in monthly_upsell}

        # Collect all months present in either dataset
        all_months = sorted(set(qa_map) | set(upsell_map))

        # Fallback upsell value for unknown activity types
        avg_upsell_val = avg_upsell_val_base

        monthly_out = []
        for month in all_months:
            quick, inbound = qa_map.get(month, (0, 0))
            hours_saved       = round(quick * MINS_PER_MSG / 60, 2)
            staff_value       = round(hours_saved * STAFF_RATE_USD, 2)
            upsell_bookings   = upsell_map.get(month, 0)
            upsell_value      = round(upsell_bookings * avg_upsell_val, 2)
            monthly_out.append({
                "month":            month,
                "quick_answers":    quick,
                "inbound_messages": inbound,
                "hours_saved":      hours_saved,
                "staff_value_usd":  staff_value,
                "upsell_bookings":  upsell_bookings,
                "upsell_value_usd": upsell_value,
                "total_value_usd":  round(staff_value + upsell_value, 2),
            })

        # Per-activity upsell breakdown with known rate lookups
        breakdown_out = [
            {
                "activity_type":       r.activity_type,
                "bookings":            r.bookings,
                "unit_value_usd":      UPSELL_VALUES.get(r.activity_type, avg_upsell_val),
                "estimated_value_usd": round(
                    r.bookings * UPSELL_VALUES.get(r.activity_type, avg_upsell_val), 2
                ),
            }
            for r in upsell_breakdown
        ]

        # Aggregate totals
        total_staff   = sum(m["staff_value_usd"]  for m in monthly_out)
        total_upsell  = sum(m["upsell_value_usd"] for m in monthly_out)
        total_hours   = sum(m["hours_saved"]       for m in monthly_out)
        total_bookings = sum(r["bookings"]          for r in breakdown_out)

        return {
            "months":                  months,
            "staff_rate_usd_hr":       STAFF_RATE_USD,
            "mins_per_msg":            MINS_PER_MSG,
            "upsell_rates_source":     "operator" if operator_upsell_rates else "platform_defaults",
            "upsell_rates_configured": upsell_rates_configured,
            "monthly":                 monthly_out,
            "upsell_breakdown":        breakdown_out,
            "totals": {
                "hours_saved":          round(total_hours, 1),
                "staff_value_usd":      round(total_staff, 2),
                "upsell_value_usd":     round(total_upsell, 2),
                "total_value_usd":      round(total_staff + total_upsell, 2),
                "total_upsell_bookings": total_bookings,
            },
        }

    except DBAPIError as exc:
        logger.warning("Revenue impact query failed for tenant_id=%s err=%s", tenant, exc)
        return {
            "months": months,
            "monthly": [],
            "upsell_breakdown": [],
            "totals": {
                "hours_saved": 0,
                "staff_value_usd": 0,
                "upsell_value_usd": 0,
                "total_value_usd": 0,
                "total_upsell_bookings": 0,
            },
        }


# =============================================================================
# Guest Feedback Submission  (guest-facing, no ops auth required)
# =============================================================================

class FeedbackRequest(BaseModel):
    rating: int                        # 1–5
    would_recommend: bool
    comments: Optional[str] = None
    property_rating: Optional[int] = None
    concierge_rating: Optional[int] = None


# Note: this endpoint breaks out of the require_ops_access router dependency
# because it is called by the guest UI (no operator credentials).
# It is registered separately below via a dedicated router.


async def _handle_feedback_submission(
    token: str,
    request: FeedbackRequest,
) -> dict:
    """
    Shared logic called by both the guest endpoint and internal tooling.

    1. Records feedback on the session.
    2. Writes / updates the GuestProfile (close_stay) so the concierge
       remembers this guest on their next booking.
    3. Returns a summary for the caller.
    """
    from app.services.concierge.guest_session import get_session_manager
    from app.db.session import get_async_session
    from app.services.concierge.guest_profile_service import close_stay
    from sqlalchemy import text

    manager = get_session_manager()
    session = await manager.get_session(token)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Record on in-memory / Redis / DB session
    await manager.submit_feedback(
        token=token,
        rating=request.rating,
        would_recommend=request.would_recommend,
        comments=request.comments,
    )

    # Resolve tenant for this session
    tenant = str(session.tenant_id) if getattr(session, "tenant_id", None) else None
    try:
        async with get_async_session() as _tdb:
            _tid_row = (await _tdb.execute(text("""
                SELECT tenant_id FROM concierge_guest_sessions
                WHERE token = :tok LIMIT 1
            """), {"tok": token})).scalar_one_or_none()
            if _tid_row:
                tenant = str(_tid_row)
    except Exception:
        pass

    if not tenant:
        raise HTTPException(status_code=500, detail="Session tenant could not be resolved")

    # Pull upsells booked this stay from journey activities
    upsells_booked: list[str] = []
    try:
        async with get_async_session() as _udb:
            _rows = (await _udb.execute(text("""
                SELECT a.activity_type
                FROM concierge_journey_activities a
                JOIN concierge_guest_journeys j ON j.journey_id = a.journey_id
                JOIN concierge_guest_sessions s ON s.session_id = j.session_id
                WHERE s.token = :tok AND a.status = 'booked'
            """), {"tok": token})).fetchall()
            upsells_booked = [r.activity_type for r in _rows]
    except Exception:
        pass

    # Pull escalation reasons this stay
    escalation_reasons: list[str] = []
    try:
        async with get_async_session() as _edb:
            _erows = (await _edb.execute(text("""
                SELECT reason FROM concierge_escalations
                WHERE session_token = :tok
            """), {"tok": token})).fetchall()
            escalation_reasons = [r.reason for r in _erows]
    except Exception:
        pass

    # Update guest profile (creates one if first-time guest)
    try:
        async with get_async_session() as _pdb:
            await close_stay(
                db=_pdb,
                tenant_id=tenant,
                session_token=token,
                phone=session.guest_phone,
                email=session.guest_email,
                first_name=session.guest_first_name,
                last_name=session.guest_last_name,
                property_code=session.property_code,
                property_name=session.property_name,
                reservation_id=session.reservation_id,
                check_in_str=session.check_in.isoformat() if session.check_in else "",
                check_out_str=session.check_out.isoformat() if session.check_out else "",
                nights=session.nights,
                num_guests=session.num_guests,
                csat=request.rating,
                would_recommend=request.would_recommend,
                feedback_text=request.comments,
                upsells_booked=upsells_booked,
                escalation_reasons=escalation_reasons,
            )
            await _pdb.commit()
        logger.info(f"GuestProfile updated after feedback for session {token}")
    except Exception as e:
        logger.warning(f"GuestProfile update failed (non-fatal): {e}")

    return {
        "status": "ok",
        "token": token,
        "rating": request.rating,
        "would_recommend": request.would_recommend,
        "profile_updated": True,
    }


# Guest-facing feedback router (no ops auth)
_guest_router = APIRouter(prefix="/guest", tags=["Guest Concierge"])


@_guest_router.post("/sessions/{token}/feedback")
async def submit_guest_feedback(token: str, request: FeedbackRequest):
    """
    Guest submits post-stay feedback from the mobile concierge UI.
    Updates the guest profile so the concierge remembers this guest next time.
    """
    return await _handle_feedback_submission(token, request)


# Ops-authenticated version for operator-submitted corrections
@router.post("/sessions/{token}/feedback")
async def submit_operator_feedback(token: str, request: FeedbackRequest):
    """
    Operator submits or corrects feedback for a session.
    Same pipeline as guest submission — updates the guest profile.
    """
    return await _handle_feedback_submission(token, request)


# =============================================================================
# Upsell Rate Configuration  (operator sets their own rates)
# =============================================================================

@router.get("/upsell-rates")
async def get_upsell_rates(request: Request):
    """
    Returns the operator's configured upsell rates, merged with platform
    defaults for any missing keys.  Also returns a flag indicating whether
    the operator has completed their upsell-rate onboarding step.

    The dashboard uses `upsell_rates_configured=null` to display a
    "Set your upsell rates" prompt so revenue analytics are accurate.
    """
    from sqlalchemy import text

    tenant = str(_require_tenant(request))
    try:
        async with SessionLocal() as db:
            row = (await db.execute(text("""
                SELECT upsell_rates, upsell_rates_configured
                FROM operator_policies
                WHERE tenant_id = CAST(:tid AS uuid)
                LIMIT 1
            """), {"tid": tenant})).fetchone()

        op_rates = dict(row.upsell_rates) if row and row.upsell_rates else {}
        configured = row.upsell_rates_configured if row else None
        merged = {**_PLATFORM_UPSELL_DEFAULTS, **op_rates}
        return {
            "upsell_rates_configured": configured,
            "source": "operator" if op_rates else "platform_defaults",
            "rates": merged,
            "platform_defaults": _PLATFORM_UPSELL_DEFAULTS,
        }
    except ProgrammingError as exc:
        logger.warning(
            "get_upsell_rates schema issue; tenant_id=%s err=%s",
            tenant,
            exc,
            exc_info=True,
        )
    except DBAPIError as exc:
        logger.warning("get_upsell_rates failed; tenant_id=%s err=%s", tenant, exc)

    return {
        "upsell_rates_configured": None,
        "source": "platform_defaults",
        "rates": _PLATFORM_UPSELL_DEFAULTS,
        "platform_defaults": _PLATFORM_UPSELL_DEFAULTS,
    }


@router.post("/upsell-rates")
async def set_upsell_rates(
    request: Request,
    rates: dict,
):
    """
    Save operator-specific upsell rates.  Accepts a partial dict —
    only the keys provided are updated; the rest continue to use
    platform defaults.  Marks upsell_rates_configured = true.

    Called from the onboarding wizard and the Settings → Revenue tab.
    """
    from sqlalchemy import text

    tenant = str(_require_tenant(request))
    try:
        async with SessionLocal() as db:
            # Upsert into operator_policies
            await db.execute(text("""
                INSERT INTO operator_policies (
                    id, tenant_id, upsell_rates, upsell_rates_configured, created_at, updated_at
                )
                VALUES (
                    gen_random_uuid(), CAST(:tid AS uuid), :rates::jsonb, true, NOW(), NOW()
                )
                ON CONFLICT (tenant_id) WHERE tenant_id IS NOT NULL DO UPDATE
                  SET upsell_rates            = :rates::jsonb,
                      upsell_rates_configured = true,
                      updated_at              = NOW()
            """), {"tid": tenant, "rates": json.dumps(rates)})
            await db.commit()
        return {"status": "ok", "rates_saved": len(rates)}
    except ProgrammingError as exc:
        logger.warning(
            "set_upsell_rates schema issue; tenant_id=%s err=%s",
            tenant,
            exc,
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Could not save upsell rates.") from exc
    except DBAPIError as exc:
        logger.warning("set_upsell_rates failed; tenant_id=%s err=%s", tenant, exc)
        raise HTTPException(status_code=500, detail="Could not save upsell rates.") from exc


# =============================================================================
# Repeat Guest Profiles
# =============================================================================

@router.get("/guests")
async def list_repeat_guests(
    request: Request,
    min_stays: int = 2,
    limit: int = 100,
    offset: int = 0,
):
    """
    List repeat guests for the operator dashboard — guests with 2+ stays
    by default.  Returns stay history, CSAT arc, upsell history, and
    any preference notes the operator has added.
    """
    tenant = str(_require_tenant(request))
    from app.db.session import get_async_session
    from app.services.concierge.guest_profile_service import list_guest_profiles

    async with get_async_session() as db:
        profiles = await list_guest_profiles(
            db, tenant_id=tenant,
            min_stays=min_stays, limit=limit, offset=offset,
        )

    return [
        {
            "profile_id":          str(p.profile_id),
            "first_name":          p.first_name,
            "last_name":           p.last_name,
            "phone":               p.phone,
            "email":               p.email,
            "total_stays":         p.total_stays,
            "total_nights":        p.total_nights,
            "avg_party_size":      p.avg_party_size,
            "avg_csat":            p.avg_csat,
            "last_csat":           p.last_csat,
            "csat_trend":          p.csat_trend,
            "recommend_rate":      p.recommend_rate,
            "upsells_ever_booked": p.upsells_ever_booked,
            "escalation_count":    p.escalation_count,
            "preferences":         p.preferences,
            "stay_history":        p.stay_history[:5],    # last 5 for API response
            "first_stay_at":       p.first_stay_at.isoformat() if p.first_stay_at else None,
            "last_stay_at":        p.last_stay_at.isoformat()  if p.last_stay_at  else None,
        }
        for p in profiles
    ]


@router.get("/guests/{profile_id}")
async def get_guest_profile(
    request: Request,
    profile_id: str,
):
    """Full guest profile including complete stay history."""
    tenant = str(_require_tenant(request))
    from app.db.session import get_async_session
    from sqlalchemy import select
    from db.models.guest_profiles import GuestProfileModel
    import uuid

    async with get_async_session() as db:
        p = (await db.execute(
            select(GuestProfileModel).where(
                GuestProfileModel.tenant_id  == tenant,
                GuestProfileModel.profile_id == uuid.UUID(profile_id),
            )
        )).scalar_one_or_none()

    if not p:
        raise HTTPException(status_code=404, detail="Guest profile not found")

    return {
        "profile_id":          str(p.profile_id),
        "first_name":          p.first_name,
        "last_name":           p.last_name,
        "phone":               p.phone,
        "email":               p.email,
        "total_stays":         p.total_stays,
        "total_nights":        p.total_nights,
        "avg_party_size":      p.avg_party_size,
        "avg_csat":            p.avg_csat,
        "last_csat":           p.last_csat,
        "csat_trend":          p.csat_trend,
        "recommend_rate":      p.recommend_rate,
        "upsells_ever_booked": p.upsells_ever_booked,
        "escalation_count":    p.escalation_count,
        "last_escalation":     p.last_escalation_reason,
        "preferences":         p.preferences,
        "stay_history":        p.stay_history,
        "concierge_context":   p.to_concierge_context(),
        "prompt_snippet":      p.to_prompt_snippet(),
        "first_stay_at":       p.first_stay_at.isoformat() if p.first_stay_at else None,
        "last_stay_at":        p.last_stay_at.isoformat()  if p.last_stay_at  else None,
    }


@router.patch("/guests/{profile_id}/preferences")
async def update_guest_preferences(
    request: Request,
    profile_id: str,
    patch: dict,
):
    """
    Operator adds/updates preference notes for a guest.
    Accepts any subset of the preferences schema — merged, not replaced.

    Example body: { "custom_notes": "Loves sunrise views. Always asks about kayaking.",
                    "dietary": ["gluten-free"], "party_type": "family" }
    """
    tenant = str(_require_tenant(request))
    from app.db.session import get_async_session
    from app.services.concierge.guest_profile_service import update_guest_preferences

    async with get_async_session() as db:
        p = await update_guest_preferences(db, tenant_id=tenant,
                                           profile_id=profile_id,
                                           preference_patch=patch)
        if not p:
            raise HTTPException(status_code=404, detail="Guest profile not found")
        await db.commit()

    return {"status": "ok", "preferences": p.preferences}


# =============================================================================
# Quick Stats
# =============================================================================

@router.get("/stats")
async def get_stats(request: Request):
    """Get quick stats for dashboard."""
    from app.services.concierge.db_session_service import get_db_session_service
    from app.services.concierge.escalation_service import get_escalation_service
    from app.db.session import get_async_session
    from sqlalchemy import func, select
    from db.models.concierge_sessions import ConciergeGuestSessionModel

    escalation_svc = get_escalation_service()

    stats_tenant = str(_require_tenant(request))
    try:
        async with get_async_session() as db:
            result = await db.execute(
                select(
                    func.count().label("total"),
                    func.sum(
                        func.cast(ConciergeGuestSessionModel.phase.in_(["in_stay", "arrival_day"]), sa.Integer)
                    ).label("in_stay"),
                    func.sum(
                        func.cast(ConciergeGuestSessionModel.phase == "arrival_day", sa.Integer)
                    ).label("arriving_today"),
                    func.sum(
                        func.cast(ConciergeGuestSessionModel.phase == "departure_day", sa.Integer)
                    ).label("departing_today"),
                    func.coalesce(func.sum(ConciergeGuestSessionModel.conversation_count), 0).label("total_convos"),
                ).where(
                    ConciergeGuestSessionModel.tenant_id == stats_tenant,
                    ConciergeGuestSessionModel.status == "active",
                )
            )
            row = result.fetchone()
            total = row.total or 0
            in_stay = int(row.in_stay or 0)
            arriving_today = int(row.arriving_today or 0)
            departing_today = int(row.departing_today or 0)
            total_convos = int(row.total_convos or 0)
    except Exception as e:
        logger.warning(f"Stats DB query failed: {e}")
        total = in_stay = arriving_today = departing_today = total_convos = 0

    return {
        "total_sessions": total,
        "in_stay": in_stay,
        "arriving_today": arriving_today,
        "departing_today": departing_today,
        "pending_escalations": len(escalation_svc.get_pending_tickets()),
        "total_conversations": total_convos,
    }


# =============================================================================
# MARKET EVENTS  (dashboard widget)
# =============================================================================

@router.get("/operator/market-events")
async def get_market_events(
    request: Request,
    limit: int = Query(default=5, ge=1, le=20),
    days_ahead: int = Query(default=30, ge=1, le=90),
    db: AsyncSession = Depends(get_async_session),
):
    """
    Upcoming high-impact market events for the operator's market, plus
    a count of how many guest questions in the last 30 days were
    event-related (detected_intent contains 'event' or knowledge category
    is 'local_events').

    Used by the Overview and Market Intel dashboard panels.
    """
    from datetime import date, timedelta
    import sqlalchemy as sa

    tenant_id = _require_tenant(request)
    today      = date.today()
    cutoff     = today + timedelta(days=days_ahead)
    msg_cutoff = datetime.utcnow() - timedelta(days=30)

    events: list[dict] = []
    event_question_count = 0
    market_id = None

    try:
        policy_row = await db.execute(
            sa.text(
                """
                SELECT market_id
                FROM operator_policies
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                ORDER BY updated_at DESC NULLS LAST, created_at DESC NULLS LAST
                LIMIT 1
                """
            ),
            {"tenant_id": str(tenant_id)},
        )
        market_id = policy_row.scalar_one_or_none()
    except ProgrammingError as exc:
        logger.warning(
            "market-events market lookup hit schema issue; tenant_id=%s err=%s",
            tenant_id,
            exc,
            exc_info=True,
        )
    except DBAPIError as exc:
        logger.warning("market-events market lookup failed; tenant_id=%s err=%s", tenant_id, exc)

    if not market_id:
        logger.info("market-events using default market fallback; tenant_id=%s fallback=%s", tenant_id, "30a_fl")
        market_id = "30a_fl"

    try:
        # ── Upcoming events sorted by impact + date ────────────────────────
        from db.models.market_events import MarketEventModel

        rows = await db.execute(
            sa.select(MarketEventModel)
            .where(
                MarketEventModel.market_id == market_id,
                MarketEventModel.is_active.is_(True),
                MarketEventModel.start_date >= today,
                MarketEventModel.start_date <= cutoff,
            )
            .order_by(
                MarketEventModel.demand_impact_score.desc(),
                MarketEventModel.start_date.asc(),
            )
            .limit(limit)
        )
        for ev in rows.scalars().all():
            events.append({
                "event_id":            str(ev.event_id),
                "title":               ev.title,
                "category":            ev.category,
                "start_date":          ev.start_date.isoformat(),
                "end_date":            ev.end_date.isoformat(),
                "is_multi_day":        ev.is_multi_day,
                "venue_name":          ev.venue_name,
                "demand_impact_score": round(float(ev.demand_impact_score or 0), 2),
                "estimated_attendance":ev.estimated_attendance,
                "is_free":             ev.is_free,
                "ticket_url":          ev.ticket_url,
                "source_url":          ev.source_url,
            })
    except DBAPIError as exc:
        logger.warning("market-events event query failed; tenant_id=%s market_id=%s err=%s", tenant_id, market_id, exc)

    # ── Event-related guest questions (last 30 days) ─────────────────
    # Strategy: count messages whose detected_intent is event-related.
    # This endpoint previously referenced knowledge_source_category, but
    # ConciergeMessageModel does not expose that field.
    try:
        from db.models.concierge_sessions import (
            ConciergeGuestSessionModel,
            ConciergeMessageModel,
        )
        q_count = await db.execute(
            sa.select(sa.func.count())
            .select_from(ConciergeMessageModel)
            .join(
                ConciergeGuestSessionModel,
                ConciergeMessageModel.session_id == ConciergeGuestSessionModel.session_id,
            )
            .where(
                ConciergeGuestSessionModel.tenant_id == tenant_id,
                ConciergeMessageModel.direction == "inbound",
                ConciergeMessageModel.created_at >= msg_cutoff,
                sa.or_(
                    ConciergeMessageModel.detected_intent.ilike("%event%"),
                    ConciergeMessageModel.detected_intent.ilike("%what%happening%"),
                    ConciergeMessageModel.detected_intent.ilike("%festival%"),
                    ConciergeMessageModel.detected_intent.ilike("%concert%"),
                ),
            )
        )
        event_question_count = q_count.scalar() or 0
    except DBAPIError as exc:
        logger.debug("Event question count query failed (non-fatal); tenant_id=%s err=%s", tenant_id, exc)

    return {
        "market_id":            market_id or "unknown",
        "events":               events,
        "event_question_count": event_question_count,
        "days_ahead":           days_ahead,
    }
