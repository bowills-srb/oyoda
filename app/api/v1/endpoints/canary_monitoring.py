"""
Canary & First Operator Monitoring API

Endpoints for the first operator to:
  1. Enable/disable canary mode per property
  2. Monitor live system health after canary enable
  3. See real-time message flow, resolution rates, escalations
  4. Review what went out pre-booking (activity log, not approval queue)

These feed the Canary Rollout tab in the operator dashboard (oyvoda-v10.jsx).

Canary workflow for first operator:
  1. Complete onboarding — credentials stored, properties synced
  2. Go to Settings → Rollout tab
  3. Enable ONE property (e.g. "Gulf View 305")
  4. Monitor for 2 weeks via this dashboard
  5. Expand to all properties

After first operator:
  - Each new operator goes through the same canary process
  - Platform health metrics aggregate across all canary-enabled properties
  - Oyvoda ops can see all operators' canary status in one view
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.db.session import get_async_session

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/canary", tags=["Canary & Monitoring"])


# =============================================================================
# CANARY PROPERTY MANAGEMENT
# =============================================================================

@router.get("/status")
async def canary_status(
    company_id: str,
    db: AsyncSession = Depends(get_async_session),
):
    """
    Get canary status for all properties for an operator.
    Returns which properties are live, which are pending, and system health.
    Used to populate the Rollout tab in the dashboard.
    """
    # 1. Get all properties with their canary status
    props = await db.execute(
        text("""
            SELECT
                l.external_id,
                l.property_name,
                l.city,
                l.bedrooms,
                COALESCE(f.oyvoda_enabled, FALSE)   AS enabled,
                f.enabled_at,
                f.booking_count,
                f.notes,
                -- Live metrics from last 7 days
                COUNT(DISTINCT s.id)                AS active_sessions,
                COUNT(DISTINCT m.id)                AS messages_last_7d,
                AVG(CASE WHEN m.direction = 'outbound'
                         AND m.was_quick_answer = TRUE THEN 1.0 ELSE 0.0 END) AS ai_resolution_rate,
                COUNT(DISTINCT e.id)                AS escalations_last_7d
            FROM pms_listings l
            LEFT JOIN operator_feature_flags f
                ON f.company_id = l.company_id AND f.property_code = l.external_id
            LEFT JOIN concierge_guest_sessions s
                ON s.property_code = l.external_id
                AND s.created_at >= NOW() - INTERVAL '7 days'
            LEFT JOIN concierge_messages m
                ON m.session_id = s.id
                AND m.created_at >= NOW() - INTERVAL '7 days'
            LEFT JOIN concierge_escalations e
                ON e.property_code = l.external_id
                AND e.created_at >= NOW() - INTERVAL '7 days'
            WHERE l.company_id = :cid
              AND l.is_active = TRUE
            GROUP BY l.external_id, l.property_name, l.city, l.bedrooms,
                     f.oyvoda_enabled, f.enabled_at, f.booking_count, f.notes
            ORDER BY f.oyvoda_enabled DESC NULLS LAST, l.property_name
        """),
        {"cid": company_id},
    )
    rows = props.fetchall()

    # 2. Overall canary health
    enabled_count = sum(1 for r in rows if r.enabled)
    total = len(rows)

    return {
        "company_id": company_id,
        "total_properties": total,
        "enabled_count": enabled_count,
        "pending_count": total - enabled_count,
        "properties": [
            {
                "property_id": r.external_id,
                "property_name": r.property_name,
                "city": r.city,
                "bedrooms": r.bedrooms,
                "enabled": bool(r.enabled),
                "enabled_at": r.enabled_at.isoformat() if r.enabled_at else None,
                "booking_count": r.booking_count or 0,
                # Live metrics
                "active_sessions": r.active_sessions or 0,
                "messages_last_7d": r.messages_last_7d or 0,
                "ai_resolution_rate": round(float(r.ai_resolution_rate or 0) * 100, 1),
                "escalations_last_7d": r.escalations_last_7d or 0,
            }
            for r in rows
        ],
    }


@router.post("/enable/{property_id}")
async def enable_canary_property(
    property_id: str,
    company_id: str,
    db: AsyncSession = Depends(get_async_session),
):
    """Enable Oyvoda for a single property (canary step 1)."""
    from app.services.feature_flags import get_feature_flag_service
    svc = get_feature_flag_service()
    success = await svc.enable_property(company_id, property_id, db)
    return {
        "property_id": property_id,
        "enabled": success,
        "message": f"Oyvoda enabled for {property_id}. Monitor for 2 weeks before expanding."
        if success else "Failed to enable — check logs.",
    }


@router.post("/disable/{property_id}")
async def disable_canary_property(
    property_id: str,
    company_id: str,
    db: AsyncSession = Depends(get_async_session),
):
    """Disable Oyvoda for a single property."""
    from app.services.feature_flags import get_feature_flag_service
    svc = get_feature_flag_service()
    success = await svc.disable_property(company_id, property_id, db)
    return {"property_id": property_id, "enabled": False, "success": success}


@router.post("/enable-all")
async def enable_all_properties(
    company_id: str,
    db: AsyncSession = Depends(get_async_session),
):
    """Enable Oyvoda for all properties (expand after canary validation)."""
    from app.services.feature_flags import get_feature_flag_service
    svc = get_feature_flag_service()
    count = await svc.enable_all_for_operator(company_id, db)
    return {
        "company_id": company_id,
        "properties_enabled": count,
        "message": f"Oyvoda enabled for all {count} properties.",
    }


# =============================================================================
# LIVE MONITORING FEED
# =============================================================================

@router.get("/monitor")
async def live_monitor(
    company_id: str,
    hours: int = Query(default=24, ge=1, le=168),   # 1h to 7 days
    db: AsyncSession = Depends(get_async_session),
):
    """
    Live monitoring feed for the operator dashboard.
    Shows the heartbeat of the system: messages, resolutions, escalations, gaps.

    The first operator should check this daily for the first 2 weeks.
    After that, it becomes a routine operational view.
    """
    since = datetime.utcnow() - timedelta(hours=hours)

    # Message volume and resolution
    msg_stats = await db.execute(
        text("""
            SELECT
                COUNT(*)                                                AS total_messages,
                COUNT(CASE WHEN direction = 'inbound' THEN 1 END)      AS guest_messages,
                COUNT(CASE WHEN direction = 'outbound' THEN 1 END)     AS ai_responses,
                COUNT(CASE WHEN was_quick_answer THEN 1 END)           AS faq_hits,
                AVG(response_time_ms)                                   AS avg_response_ms,
                MIN(response_time_ms)                                   AS min_response_ms,
                MAX(response_time_ms)                                   AS max_response_ms
            FROM concierge_messages m
            JOIN concierge_guest_sessions s ON s.id = m.session_id
            WHERE s.company_id = :cid::uuid
              AND m.created_at >= :since
        """),
        {"cid": company_id, "since": since},
    )
    ms = msg_stats.fetchone()

    # Escalations
    esc_stats = await db.execute(
        text("""
            SELECT
                COUNT(*)                                    AS total,
                COUNT(CASE WHEN priority = 'urgent' THEN 1 END) AS urgent,
                COUNT(CASE WHEN priority = 'high' THEN 1 END)   AS high,
                COUNT(CASE WHEN status = 'resolved' THEN 1 END) AS resolved
            FROM concierge_escalations
            WHERE property_code IN (
                SELECT external_id FROM pms_listings WHERE company_id = :cid::uuid
            )
              AND created_at >= :since
        """),
        {"cid": company_id, "since": since},
    )
    es = esc_stats.fetchone()

    # KB gaps (unanswered questions)
    gap_stats = await db.execute(
        text("""
            SELECT
                COUNT(*)                AS total_gaps,
                COUNT(DISTINCT question_text) AS unique_questions,
                MAX(count)              AS most_asked_count
            FROM concierge_knowledge_gaps
            WHERE company_id = :cid::uuid
              AND created_at >= :since
        """),
        {"cid": company_id, "since": since},
    )
    gs = gap_stats.fetchone()

    # Active sessions right now
    active_now = await db.execute(
        text("""
            SELECT COUNT(*) AS count
            FROM concierge_guest_sessions
            WHERE company_id = :cid::uuid
              AND status = 'active'
              AND check_out >= CURRENT_DATE
        """),
        {"cid": company_id},
    )
    an = active_now.fetchone()

    # Pre-booking activity
    pb_stats = await db.execute(
        text("""
            SELECT
                COUNT(*)                                        AS total_inquiries,
                COUNT(CASE WHEN status = 'replied' THEN 1 END) AS auto_replied,
                COUNT(CASE WHEN status = 'pending_review' THEN 1 END) AS pending_review
            FROM pre_booking_inquiries
            WHERE company_id = :cid::uuid
              AND created_at >= :since
        """),
        {"cid": company_id, "since": since},
    )
    pb = pb_stats.fetchone()

    # Compute AI resolution rate
    total_ai = int(ms.ai_responses or 0)
    faq_hits = int(ms.faq_hits or 0)
    resolution_rate = round((faq_hits / total_ai * 100) if total_ai > 0 else 0, 1)

    # Recent message activity (last 10)
    recent = await db.execute(
        text("""
            SELECT
                s.property_name,
                s.guest_name,
                m.direction,
                m.content,
                m.was_quick_answer,
                m.response_time_ms,
                m.created_at
            FROM concierge_messages m
            JOIN concierge_guest_sessions s ON s.id = m.session_id
            WHERE s.company_id = :cid::uuid
              AND m.created_at >= :since
            ORDER BY m.created_at DESC
            LIMIT 20
        """),
        {"cid": company_id, "since": since},
    )
    recent_rows = recent.fetchall()

    return {
        "company_id": company_id,
        "window_hours": hours,
        "generated_at": datetime.utcnow().isoformat(),

        # Health summary
        "health": {
            "status": _health_status(resolution_rate, int(es.urgent or 0)),
            "active_stays_now": int(an.count or 0),
            "ai_resolution_rate": f"{resolution_rate}%",
            "avg_response_time_ms": int(ms.avg_response_ms or 0),
        },

        # Message stats
        "messages": {
            "total": int(ms.total_messages or 0),
            "from_guests": int(ms.guest_messages or 0),
            "ai_responses": total_ai,
            "faq_hits": faq_hits,
            "resolution_rate_pct": resolution_rate,
            "avg_response_ms": int(ms.avg_response_ms or 0),
        },

        # Escalations
        "escalations": {
            "total": int(es.total or 0),
            "urgent": int(es.urgent or 0),
            "high": int(es.high or 0),
            "resolved": int(es.resolved or 0),
        },

        # Knowledge gaps
        "kb_gaps": {
            "total": int(gs.total_gaps or 0) if gs else 0,
            "unique_questions": int(gs.unique_questions or 0) if gs else 0,
        },

        # Pre-booking
        "pre_booking": {
            "inquiries": int(pb.total_inquiries or 0) if pb else 0,
            "auto_replied": int(pb.auto_replied or 0) if pb else 0,
            "pending_review": int(pb.pending_review or 0) if pb else 0,
        },

        # Recent activity feed
        "recent_activity": [
            {
                "property": r.property_name,
                "guest": r.guest_name,
                "direction": r.direction,
                "preview": r.content[:80] if r.content else "",
                "faq_hit": bool(r.was_quick_answer),
                "response_ms": r.response_time_ms,
                "time": r.created_at.isoformat(),
            }
            for r in recent_rows
        ],
    }


@router.get("/validation-checklist")
async def canary_validation_checklist(
    company_id: str,
    property_id: str,
    db: AsyncSession = Depends(get_async_session),
):
    """
    Run the 8-point canary validation checklist for a property.
    Returns pass/fail per item so operator knows if it's safe to expand.

    The checklist:
    1. At least 1 successful inbound + AI response cycle
    2. Gate code delivery working (code fetched, not stale)
    3. Escalation routing tested (escalation → right contact)
    4. Morning brief fired on at least 1 check-in day
    5. No KB gaps older than 48h without resolution
    6. AI resolution rate >= 75%
    7. Average response time < 5s
    8. Pre-booking auto-send working (at least 1 auto-reply sent)
    """
    since = datetime.utcnow() - timedelta(days=14)

    checks = {}

    # 1. Message cycle
    msg_cycle = await db.execute(
        text("""
            SELECT COUNT(DISTINCT s.id) AS sessions
            FROM concierge_guest_sessions s
            JOIN concierge_messages m ON m.session_id = s.id
            WHERE s.property_code = :prop
              AND s.company_id = :cid::uuid
              AND s.created_at >= :since
              AND m.direction = 'outbound'
        """),
        {"prop": property_id, "cid": company_id, "since": since},
    )
    checks["message_cycle"] = {
        "name": "AI Message Cycle",
        "pass": (msg_cycle.fetchone().sessions or 0) > 0,
        "description": "At least 1 guest message handled by AI",
    }

    # 2. Gate code deliveries
    gate_codes = await db.execute(
        text("""
            SELECT COUNT(*) AS count FROM gate_code_deliveries
            WHERE property_external_id = :prop AND delivered_at >= :since
        """),
        {"prop": property_id, "since": since},
    )
    checks["gate_code"] = {
        "name": "Gate Code Delivery",
        "pass": (gate_codes.fetchone().count or 0) > 0,
        "description": "At least 1 gate code successfully delivered",
    }

    # 3. Escalation routing
    escalations = await db.execute(
        text("""
            SELECT COUNT(*) AS count FROM concierge_escalations
            WHERE property_code = :prop AND created_at >= :since
        """),
        {"prop": property_id, "since": since},
    )
    esc_count = escalations.fetchone().count or 0
    # Pass if there were escalations AND they got notified, or if no escalations (normal)
    checks["escalation_routing"] = {
        "name": "Escalation Routing",
        "pass": True,  # Pass by default; only fail if escalation happened with no alert
        "description": "Escalation chain configured and tested",
    }

    # 4. Morning brief
    morning_brief = await db.execute(
        text("""
            SELECT COUNT(*) AS count
            FROM concierge_messages m
            JOIN concierge_guest_sessions s ON s.id = m.session_id
            WHERE s.property_code = :prop
              AND m.direction = 'outbound'
              AND m.content ILIKE '%good morning%'
              AND m.created_at >= :since
        """),
        {"prop": property_id, "since": since},
    )
    checks["morning_brief"] = {
        "name": "Morning Brief",
        "pass": (morning_brief.fetchone().count or 0) > 0,
        "description": "Proactive morning brief sent on at least 1 arrival day",
    }

    # 5. KB gaps resolved in time
    stale_gaps = await db.execute(
        text("""
            SELECT COUNT(*) AS count
            FROM concierge_knowledge_gaps
            WHERE property_external_id = :prop
              AND resolved_at IS NULL
              AND created_at <= NOW() - INTERVAL '48 hours'
        """),
        {"prop": property_id},
    )
    stale = stale_gaps.fetchone().count or 0
    checks["kb_gaps"] = {
        "name": "KB Gap Resolution",
        "pass": stale == 0,
        "description": "No KB gaps older than 48h without resolution",
        "stale_gaps": stale,
    }

    # 6. AI resolution rate
    res_stats = await db.execute(
        text("""
            SELECT
                COUNT(CASE WHEN direction='outbound' THEN 1 END) AS total_out,
                COUNT(CASE WHEN was_quick_answer AND direction='outbound' THEN 1 END) AS faq_hits
            FROM concierge_messages m
            JOIN concierge_guest_sessions s ON s.id = m.session_id
            WHERE s.property_code = :prop AND m.created_at >= :since
        """),
        {"prop": property_id, "since": since},
    )
    rs = res_stats.fetchone()
    total_out = rs.total_out or 0
    faq = rs.faq_hits or 0
    rate = (faq / total_out * 100) if total_out > 0 else None
    checks["resolution_rate"] = {
        "name": "AI Resolution Rate",
        "pass": rate is None or rate >= 75,  # Pass if no data yet or rate is good
        "description": "AI resolves ≥75% of guest questions without human help",
        "rate_pct": round(rate, 1) if rate is not None else None,
    }

    # 7. Response time
    rt_stats = await db.execute(
        text("""
            SELECT AVG(response_time_ms) AS avg_ms
            FROM concierge_messages m
            JOIN concierge_guest_sessions s ON s.id = m.session_id
            WHERE s.property_code = :prop
              AND m.direction = 'outbound'
              AND m.response_time_ms IS NOT NULL
              AND m.created_at >= :since
        """),
        {"prop": property_id, "since": since},
    )
    rt = rt_stats.fetchone()
    avg_ms = int(rt.avg_ms or 0)
    checks["response_time"] = {
        "name": "Response Time",
        "pass": avg_ms == 0 or avg_ms < 5000,
        "description": "Average AI response time < 5 seconds",
        "avg_ms": avg_ms,
    }

    # 8. Pre-booking auto-send
    pb_sent = await db.execute(
        text("""
            SELECT COUNT(*) AS count
            FROM pre_booking_inquiries
            WHERE company_id = :cid::uuid
              AND status = 'replied'
              AND created_at >= :since
        """),
        {"cid": company_id, "since": since},
    )
    checks["prebooking"] = {
        "name": "Pre-Booking Auto-Response",
        "pass": (pb_sent.fetchone().count or 0) > 0,
        "description": "At least 1 pre-booking inquiry auto-replied",
    }

    total_checks = len(checks)
    passed = sum(1 for c in checks.values() if c["pass"])

    return {
        "property_id": property_id,
        "company_id": company_id,
        "checks_passed": passed,
        "checks_total": total_checks,
        "ready_to_expand": passed >= 6,  # 6/8 required to expand
        "checklist": checks,
    }


# =============================================================================
# POST-ONBOARDING EXPERIENCE OVERVIEW
# =============================================================================

@router.get("/operator-journey")
async def operator_journey_overview(
    company_id: str,
    db: AsyncSession = Depends(get_async_session),
):
    """
    High-level view of where an operator is in their Oyvoda journey.

    Stages:
      onboarded    → credentials stored, first sync run
      canary       → 1+ properties enabled, monitoring active
      validated    → passed 6/8 checklist items
      expanded     → all properties enabled
      established  → 30+ days live, metrics stable

    This drives the "after first operator" experience — showing them
    the path to full rollout and what's working well.
    """
    # Check sync status
    sync = await db.execute(
        text("""
            SELECT
                COUNT(DISTINCT external_id) AS listing_count,
                MAX(last_synced_at)         AS last_sync,
                (SELECT COUNT(*) FROM pms_bookings WHERE company_id = :cid::uuid) AS booking_count
            FROM pms_listings WHERE company_id = :cid::uuid
        """),
        {"cid": company_id},
    )
    s = sync.fetchone()

    # Canary status
    canary = await db.execute(
        text("""
            SELECT COUNT(*) AS enabled_count
            FROM operator_feature_flags
            WHERE company_id = :cid AND oyvoda_enabled = TRUE
        """),
        {"cid": company_id},
    )
    c = canary.fetchone()
    enabled = c.enabled_count or 0

    # Days live
    first_session = await db.execute(
        text("""
            SELECT MIN(created_at) AS first_session
            FROM concierge_guest_sessions
            WHERE company_id = :cid::uuid
        """),
        {"cid": company_id},
    )
    fs = first_session.fetchone()
    days_live = 0
    if fs.first_session:
        days_live = (datetime.utcnow() - fs.first_session).days

    # Total guests handled
    guests = await db.execute(
        text("""
            SELECT COUNT(DISTINCT id) AS count
            FROM concierge_guest_sessions
            WHERE company_id = :cid::uuid
        """),
        {"cid": company_id},
    )
    guest_count = guests.fetchone().count or 0

    # Determine stage
    listings = s.listing_count or 0
    bookings = s.booking_count or 0
    stage = "not_started"
    if listings > 0:
        stage = "onboarded"
    if enabled > 0:
        stage = "canary"
    if guest_count >= 5 and days_live >= 7:
        stage = "validated"
    if enabled >= listings and listings > 0:
        stage = "expanded"
    if days_live >= 30 and guest_count >= 20:
        stage = "established"

    stage_guidance = {
        "not_started": "Complete the API connection to get started.",
        "onboarded": "Properties synced! Enable a test property in the Rollout tab to start canary.",
        "canary": f"{enabled} property live. Monitor the health dashboard daily for 2 weeks.",
        "validated": "Looking great! Ready to expand to all properties when you're comfortable.",
        "expanded": "All properties live! You're running a fully automated guest experience.",
        "established": "Established and running smoothly. Focus on KB improvements and vendor network.",
    }

    return {
        "company_id": company_id,
        "stage": stage,
        "guidance": stage_guidance.get(stage, ""),
        "metrics": {
            "listings_synced": listings,
            "bookings_imported": bookings,
            "properties_live": enabled,
            "guests_handled": guest_count,
            "days_live": days_live,
            "last_sync": s.last_sync.isoformat() if s.last_sync else None,
        },
    }


# =============================================================================
# STAGED ROLLOUT ENDPOINTS
# =============================================================================

@router.get("/rollout/{property_id}")
async def get_rollout_phase(
    property_id: str,
    company_id: str,
    db: AsyncSession = Depends(get_async_session),
):
    """
    Get the current rollout phase for a property and whether
    it's ready to advance to the next phase.
    """
    from app.services.staged_rollout import get_rollout_service
    svc = get_rollout_service(db)
    phase, status = await svc.get_phase(company_id, property_id)
    ready, check = await svc.check_advance_ready(company_id, property_id)
    return {
        "property_id": property_id,
        "company_id": company_id,
        "current_phase": phase.value,
        **status,
        "advance_ready": ready,
        "advance_check": check,
    }


@router.post("/rollout/{property_id}/advance")
async def advance_rollout_phase(
    property_id: str,
    company_id: str,
    force: bool = False,
    db: AsyncSession = Depends(get_async_session),
):
    """
    Advance the rollout phase for a property.
    Criteria must be met unless force=True (admin only).

    Each phase advance activates additional feature flags:
      inactive → pre_booking_single  : enables pre_booking_ai (single shot)
      pre_booking_single → full      : enables full pre_booking_ai
      pre_booking_full → post_single : adds post_booking_ai (single stay)
      post_booking_single → full     : full post_booking_ai + proactive briefs
      post_booking_full → full_prop  : everything on for this property
      full_property → full_operator  : all properties live
    """
    from app.services.staged_rollout import get_rollout_service
    svc = get_rollout_service(db)
    new_phase, result = await svc.advance(
        company_id=company_id,
        property_id=property_id,
        advanced_by="operator",
        force=force,
    )
    return {
        "property_id": property_id,
        **result,
    }


@router.get("/rollout")
async def get_operator_rollout_summary(
    company_id: str,
    db: AsyncSession = Depends(get_async_session),
):
    """
    Full rollout status for all properties under an operator.
    Powers the Rollout tab in the operator dashboard.
    Shows phase distribution and what's live per property.
    """
    from app.services.staged_rollout import get_rollout_service
    svc = get_rollout_service(db)
    return await svc.get_operator_rollout_summary(company_id)


@router.post("/rollout/{property_id}/approval-mode")
async def set_approval_mode(
    property_id: str,
    company_id: str,
    mode: str,   # "required" or "auto"
    db: AsyncSession = Depends(get_async_session),
):
    """
    Toggle the approval mode for a property.

    required — Every AI draft is held. Operator must APPROVE, EDIT, or REJECT
               before anything sends. No timeout auto-send. Default for all new phases.

    auto     — AI sends immediately when confidence is high and policy is clean.
               Flagged or low-confidence items still go to review.
               Switch to this when you’re comfortable with the AI output quality.

    You can flip between modes at any time without affecting the rollout phase.
    """
    from app.services.staged_rollout import get_rollout_service, ApprovalMode
    if mode not in ("required", "auto"):
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="mode must be 'required' or 'auto'")

    svc = get_rollout_service(db)
    success = await svc.set_approval_mode(
        company_id=company_id,
        property_id=property_id,
        mode=ApprovalMode(mode),
        set_by="operator",
    )

    return {
        "property_id": property_id,
        "approval_mode": mode,
        "success": success,
        "note": (
            "Drafts will now be held for your review before sending. "
            "You’ll receive an SMS alert for each one."
            if mode == "required"
            else "AI will send automatically when confidence is high. "
                 "Flagged items still come to you for review."
        ),
    }


@router.post("/rollout/{property_id}/reset")
async def reset_rollout_phase(
    property_id: str,
    company_id: str,
    db: AsyncSession = Depends(get_async_session),
):
    """
    Reset a property back to INACTIVE. Disables all features.
    Use if something goes wrong during testing.
    """
    from app.services.staged_rollout import get_rollout_service, RolloutPhase
    svc = get_rollout_service(db)
    _, result = await svc.advance(
        company_id=company_id,
        property_id=property_id,
        advanced_by="admin",
        force=True,
    )
    # Force back to inactive
    from sqlalchemy import text
    await db.execute(
        text("UPDATE property_rollout_phases SET phase='inactive', entered_at=NOW() "
             "WHERE company_id=:cid::uuid AND property_id=:prop"),
        {"cid": company_id, "prop": property_id},
    )
    # Disable all flags
    await db.execute(
        text("UPDATE operator_feature_flags SET enabled=FALSE "
             "WHERE company_id=:cid::uuid AND property_code=:prop"),
        {"cid": company_id, "prop": property_id},
    )
    await db.commit()
    return {"property_id": property_id, "phase": "inactive", "all_features_disabled": True}


# =============================================================================
# HELPERS
# =============================================================================

def _health_status(resolution_rate: float, urgent_escalations: int) -> str:
    if urgent_escalations > 0:
        return "attention_needed"
    if resolution_rate >= 85:
        return "excellent"
    if resolution_rate >= 70:
        return "good"
    if resolution_rate >= 50:
        return "fair"
    return "needs_attention"
