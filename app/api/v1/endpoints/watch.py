"""
Watch Layer API — Observability endpoints for the operator dashboard.

Provides:
- GET  /watch/stats          — Aggregate metrics
- GET  /watch/events         — Recent events (filterable)
- GET  /watch/stream         — SSE stream of real-time events
- GET  /watch/eq-alerts      — Recent EQ crisis alerts
- POST /watch/approvals/{id} — Approve or reject pending tool actions
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Any, AsyncGenerator, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.services.observability.watch_layer import (
    EventType,
    WatchEvent,
    get_watch_layer,
)
from app.services.agents.task_execution.tool_executor import (
    ApprovalStatus,
    get_tool_executor,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/watch", tags=["observability"])


# =========================================================================
# RESPONSE SCHEMAS
# =========================================================================

class StatsResponse(BaseModel):
    total_interactions: int
    total_cost_usd: float
    avg_latency_ms: float
    eq_alerts: int
    tool_executions: int
    errors: int
    timestamp: str


class EventResponse(BaseModel):
    event_type: str
    timestamp: str
    session_id: Optional[str]
    operator_id: Optional[str]
    property_code: Optional[str]
    latency_ms: Optional[float]
    cost_usd: Optional[float]
    success: Optional[bool]
    data: Dict[str, Any]
    tags: List[str]


class ApprovalActionRequest(BaseModel):
    action: str  # "approve" or "reject"
    actor: str   # User/admin who is approving
    rejection_reason: Optional[str] = None


class ApprovalActionResponse(BaseModel):
    request_id: str
    status: str
    actor: str
    timestamp: str


# =========================================================================
# ENDPOINTS
# =========================================================================

@router.get("/stats", response_model=StatsResponse)
async def get_stats():
    """
    Get aggregate observability stats.
    
    Returns:
    - Total voice interactions
    - Total cost (USD)
    - Average latency (ms)
    - EQ crisis alert count
    - Tool execution count
    - Error count
    """
    watch = get_watch_layer()
    stats = watch.get_stats()
    return StatsResponse(
        **stats,
        timestamp=datetime.utcnow().isoformat(),
    )


@router.get("/events", response_model=List[EventResponse])
async def get_events(
    n: int = Query(50, ge=1, le=500, description="Number of events to return"),
    event_type: Optional[str] = Query(None, description="Filter by event type"),
    operator_id: Optional[str] = Query(None, description="Filter by operator"),
):
    """
    Get recent events from the ring buffer.
    
    Useful for populating the operator dashboard activity feed.
    """
    watch = get_watch_layer()
    
    et = None
    if event_type:
        try:
            et = EventType(event_type)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid event_type. Must be one of: {[e.value for e in EventType]}",
            )
    
    events = watch.get_recent_events(n=n, event_type=et, operator_id=operator_id)
    
    return [
        EventResponse(
            event_type=e.event_type.value,
            timestamp=e.timestamp,
            session_id=e.session_id,
            operator_id=e.operator_id,
            property_code=e.property_code,
            latency_ms=e.latency_ms,
            cost_usd=e.cost_usd,
            success=e.success,
            data=e.data,
            tags=e.tags,
        )
        for e in events
    ]


@router.get("/eq-alerts", response_model=List[EventResponse])
async def get_eq_alerts(
    operator_id: Optional[str] = Query(None),
    n: int = Query(20, ge=1, le=100),
):
    """
    Get recent EQ crisis alerts.
    
    These are guests detected as frustrated, angry, or in crisis.
    Operators should follow up on these sessions.
    """
    watch = get_watch_layer()
    events = watch.get_recent_events(
        n=n,
        event_type=EventType.EQ_ALERT,
        operator_id=operator_id,
    )
    return [
        EventResponse(
            event_type=e.event_type.value,
            timestamp=e.timestamp,
            session_id=e.session_id,
            operator_id=e.operator_id,
            property_code=e.property_code,
            latency_ms=e.latency_ms,
            cost_usd=e.cost_usd,
            success=e.success,
            data=e.data,
            tags=e.tags,
        )
        for e in events
    ]


@router.get("/stream")
async def stream_events(
    operator_id: Optional[str] = Query(None, description="Filter to one operator"),
):
    """
    Server-Sent Events (SSE) stream of real-time observability events.
    
    Connect from the dashboard:
        const es = new EventSource('/api/v1/watch/stream?operator_id=op_123');
        es.onmessage = (e) => updateDashboard(JSON.parse(e.data));
    
    Events are pushed every time a new event is logged.
    Heartbeat sent every 15s to keep the connection alive.
    """
    watch = get_watch_layer()
    last_buffer_len = len(watch._event_buffer)
    
    async def generate() -> AsyncGenerator[str, None]:
        nonlocal last_buffer_len
        
        # Send initial stats snapshot
        stats = watch.get_stats()
        yield f"data: {json.dumps({'type': 'stats', 'payload': stats})}\n\n"
        
        heartbeat_counter = 0
        while True:
            await asyncio.sleep(1)
            heartbeat_counter += 1
            
            # Check for new events
            current_len = len(watch._event_buffer)
            if current_len > last_buffer_len:
                new_events = watch._event_buffer[last_buffer_len:current_len]
                last_buffer_len = current_len
                
                for event in new_events:
                    # Filter by operator if requested
                    if operator_id and event.operator_id != operator_id:
                        continue
                    
                    payload = {
                        "type": "event",
                        "payload": {
                            "event_type": event.event_type.value,
                            "timestamp": event.timestamp,
                            "session_id": event.session_id,
                            "operator_id": event.operator_id,
                            "property_code": event.property_code,
                            "latency_ms": event.latency_ms,
                            "cost_usd": event.cost_usd,
                            "success": event.success,
                            "data": event.data,
                            "tags": event.tags,
                        }
                    }
                    yield f"data: {json.dumps(payload)}\n\n"
            
            # Heartbeat every 15s
            if heartbeat_counter % 15 == 0:
                yield f"data: {json.dumps({'type': 'heartbeat', 'timestamp': datetime.utcnow().isoformat()})}\n\n"
    
    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/pending-approvals")
async def get_pending_approvals(operator_id: Optional[str] = Query(None)):
    """
    Get all pending tool action approvals.
    
    These are high-risk actions that need human sign-off before executing
    (refunds, booking modifications, etc.).
    """
    executor = get_tool_executor()
    pending = [
        {
            "request_id": req_id,
            "title": approval.title,
            "summary": approval.summary,
            "urgency": approval.urgency,
            "requested_at": approval.requested_at.isoformat(),
            "action_type": approval.action.action_type,
            "operator_id": approval.action.operator_id,
            "financial_impact": str(approval.action.financial_impact)
                if approval.action.financial_impact else None,
        }
        for req_id, approval in executor.guardrails._pending_approvals.items()
        if approval.status == ApprovalStatus.PENDING
        and (operator_id is None or approval.action.operator_id == operator_id)
    ]
    return {"pending": pending, "count": len(pending)}


@router.post("/approvals/{request_id}", response_model=ApprovalActionResponse)
async def handle_approval(request_id: str, body: ApprovalActionRequest):
    """
    Approve or reject a pending tool action.
    
    Body:
        {
            "action": "approve" | "reject",
            "actor": "admin@beachhabitats.com",
            "rejection_reason": "Too large a refund without documentation"  # optional
        }
    """
    executor = get_tool_executor()
    
    if body.action == "approve":
        result = await executor.guardrails.approve(request_id, body.actor)
        if not result:
            raise HTTPException(status_code=404, detail=f"Approval request {request_id} not found")
        status = "approved"
    elif body.action == "reject":
        if not body.rejection_reason:
            raise HTTPException(status_code=400, detail="rejection_reason required when rejecting")
        result = await executor.guardrails.reject(request_id, body.actor, body.rejection_reason)
        if not result:
            raise HTTPException(status_code=404, detail=f"Approval request {request_id} not found")
        status = "rejected"
    else:
        raise HTTPException(status_code=400, detail="action must be 'approve' or 'reject'")
    
    # Log the approval action
    watch = get_watch_layer()
    await watch.log_agent_run(
        agent_name="approval_workflow",
        operator_id=body.actor,
        success=True,
        latency_ms=0,
        metadata={
            "request_id": request_id,
            "action": body.action,
            "actor": body.actor,
        },
    )
    
    return ApprovalActionResponse(
        request_id=request_id,
        status=status,
        actor=body.actor,
        timestamp=datetime.utcnow().isoformat(),
    )
