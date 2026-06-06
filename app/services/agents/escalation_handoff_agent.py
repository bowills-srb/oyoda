"""
Escalation Handoff Agent

Adds SLA tracking and closure-loop accountability on top of EscalationService.

What EscalationService already does:
  - Detect trigger keywords and EQ-crisis signals
  - Create EscalationTicket objects
  - Persist them to concierge_escalations table
  - Notify operator (stub)

What this agent adds:
  - SLA enforcement: urgent → 15min ack, 1hr resolve; high → 1hr ack, 4hr resolve
  - Automatic SLA breach detection via background polling
  - Closure loop: resolved ticket → Watch Layer metric + optional guest follow-up
  - SLA dashboard stats: p95 ack time, p95 resolve time, breach rate by priority
  - Re-alert on SLA breach (fires Watch Layer alert hook)

Usage:
    from app.services.agents.escalation_handoff_agent import (
        EscalationHandoffAgent, get_escalation_handoff_agent
    )

    agent = get_escalation_handoff_agent()

    # Called by background task (every 5 minutes)
    breaches = await agent.check_sla_breaches(db)

    # Called when operator resolves a ticket
    await agent.close_ticket(db, ticket_id="ESC-ABCD1234", operator="jane@beach", note="Fixed AC unit")

    # Called on startup to rebuild in-memory state from DB
    await agent.load_open_tickets(db)
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session_safety import safe_rollback

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# SLA definitions
# ─────────────────────────────────────────────────────────────────────────────

SLA_POLICY: Dict[str, Dict[str, int]] = {
    # priority → {ack_minutes, resolve_minutes}
    "urgent": {"ack_minutes": 15,   "resolve_minutes": 60},
    "high":   {"ack_minutes": 60,   "resolve_minutes": 240},
    "medium": {"ack_minutes": 240,  "resolve_minutes": 1440},  # 4h / 24h
    "low":    {"ack_minutes": 1440, "resolve_minutes": 4320},  # 24h / 72h
}


@dataclass
class SLABreach:
    ticket_id: str
    session_token: str
    priority: str
    breach_type: str            # "ack" | "resolve"
    sla_minutes: int            # SLA target
    elapsed_minutes: float      # how long it's actually been
    property_code: str = ""
    operator_id: str = ""
    guest_name: str = ""


@dataclass
class EscalationSLAStats:
    total_tickets: int = 0
    open_tickets: int = 0
    ack_breach_count: int = 0
    resolve_breach_count: int = 0
    p50_ack_minutes: Optional[float] = None
    p95_ack_minutes: Optional[float] = None
    p50_resolve_minutes: Optional[float] = None
    p95_resolve_minutes: Optional[float] = None
    breach_rate_pct: float = 0.0


class EscalationHandoffAgent:
    """
    SLA enforcement and closure-loop tracking for escalation tickets.

    Works alongside EscalationService — does not replace it.
    EscalationService owns ticket creation; this agent owns SLA enforcement.
    """

    def __init__(self) -> None:
        self._watch = None

    def _get_watch(self):
        if self._watch is None:
            from app.services.observability.watch_layer import get_watch_layer
            self._watch = get_watch_layer()
        return self._watch

    # ─────────────────────────────────────────────────────────────────────────
    # SLA breach detection
    # ─────────────────────────────────────────────────────────────────────────

    async def check_sla_breaches(self, db: AsyncSession) -> List[SLABreach]:
        """
        Scan open escalation tickets for SLA breaches.
        Called by the `check_escalation_slas` Celery task every 5 minutes.

        Returns a list of breaches found.  For each breach:
        - A Watch Layer alert fires (non-blocking)
        - The ticket's `sla_breached` flag is set in DB

        Does NOT automatically close tickets — that's the operator's job.
        """
        breaches: List[SLABreach] = []
        tickets = await self._load_open_tickets(db)
        now = datetime.utcnow()

        for ticket in tickets:
            priority = getattr(ticket, "priority", "medium")
            policy = SLA_POLICY.get(priority, SLA_POLICY["medium"])
            created_at = getattr(ticket, "created_at", now)
            acked_at = getattr(ticket, "acknowledged_at", None)
            status = getattr(ticket, "status", "pending")

            elapsed_total = (now - created_at).total_seconds() / 60

            # Ack SLA breach
            if acked_at is None and elapsed_total > policy["ack_minutes"]:
                breach = SLABreach(
                    ticket_id=ticket.ticket_id,
                    session_token=ticket.session_token,
                    priority=priority,
                    breach_type="ack",
                    sla_minutes=policy["ack_minutes"],
                    elapsed_minutes=elapsed_total,
                    property_code=getattr(ticket, "property_code", ""),
                    operator_id="",
                    guest_name=getattr(ticket, "guest_name", ""),
                )
                breaches.append(breach)
                await self._fire_breach_alert(breach)
                await self._stamp_breach(db, ticket.ticket_id, "ack")

            # Resolve SLA breach (ticket not resolved after resolve_minutes)
            if status not in ("resolved", "closed") and elapsed_total > policy["resolve_minutes"]:
                breach = SLABreach(
                    ticket_id=ticket.ticket_id,
                    session_token=ticket.session_token,
                    priority=priority,
                    breach_type="resolve",
                    sla_minutes=policy["resolve_minutes"],
                    elapsed_minutes=elapsed_total,
                    property_code=getattr(ticket, "property_code", ""),
                    operator_id="",
                    guest_name=getattr(ticket, "guest_name", ""),
                )
                breaches.append(breach)
                await self._fire_breach_alert(breach)
                await self._stamp_breach(db, ticket.ticket_id, "resolve")

        if breaches:
            logger.warning(
                "[EscalationSLA] %d SLA breach(es) detected", len(breaches)
            )

        return breaches

    # ─────────────────────────────────────────────────────────────────────────
    # Ticket closure (operator action)
    # ─────────────────────────────────────────────────────────────────────────

    async def close_ticket(
        self,
        db: AsyncSession,
        ticket_id: str,
        operator: str,
        note: str,
        resolution_code: Optional[str] = None,
    ) -> bool:
        """
        Mark a ticket as resolved and record the closure in the Watch Layer.

        Called from:
        - Operator dashboard "Resolve" button
        - POST /api/v1/operator/escalations/{ticket_id}/resolve

        Returns True if ticket was found and closed.
        """
        ticket = await self._load_ticket_by_id(db, ticket_id)
        if ticket is None:
            logger.warning("[EscalationHandoff] close_ticket: not found %s", ticket_id)
            return False

        created_at = getattr(ticket, "created_at", datetime.utcnow())
        resolve_time = (datetime.utcnow() - created_at).total_seconds() / 60

        # Persist closure
        await self._resolve_in_db(db, ticket_id, operator, note, resolution_code)

        # EscalationService in-memory cache
        try:
            from app.services.concierge.escalation_service import get_escalation_service
            svc = get_escalation_service()
            svc.resolve_ticket(ticket_id, operator, note)
        except Exception as exc:
            logger.debug("[EscalationHandoff] EscalationService cache update skipped: %s", exc)

        # Watch Layer metric — feeds p95 resolve time SLO
        priority = getattr(ticket, "priority", "medium")
        policy = SLA_POLICY.get(priority, SLA_POLICY["medium"])
        met_sla = resolve_time <= policy["resolve_minutes"]

        watch = self._get_watch()
        import asyncio
        asyncio.ensure_future(
            watch.log_agent_run(
                agent_name="escalation_handoff",
                operator_id=operator,
                success=True,
                latency_ms=resolve_time * 60 * 1000,  # convert minutes → ms
                metadata={
                    "event": "ticket_closed",
                    "ticket_id": ticket_id,
                    "priority": priority,
                    "resolve_minutes": round(resolve_time, 1),
                    "met_sla": met_sla,
                    "sla_target_minutes": policy["resolve_minutes"],
                    "resolution_code": resolution_code,
                    "property_code": getattr(ticket, "property_code", ""),
                },
            )
        )

        logger.info(
            "[EscalationHandoff] Ticket %s closed by %s in %.1f min (SLA %s)",
            ticket_id, operator, resolve_time,
            "MET" if met_sla else "BREACHED",
        )
        return True

    async def acknowledge_ticket(
        self,
        db: AsyncSession,
        ticket_id: str,
        operator: str,
    ) -> bool:
        """
        Mark a ticket as acknowledged.  Stops the ack SLA clock.
        Called from operator dashboard "Acknowledge" button.
        """
        ticket = await self._load_ticket_by_id(db, ticket_id)
        if ticket is None:
            return False

        created_at = getattr(ticket, "created_at", datetime.utcnow())
        ack_time = (datetime.utcnow() - created_at).total_seconds() / 60
        priority = getattr(ticket, "priority", "medium")
        policy = SLA_POLICY.get(priority, SLA_POLICY["medium"])
        met_sla = ack_time <= policy["ack_minutes"]

        await self._ack_in_db(db, ticket_id, operator)

        # EscalationService in-memory cache
        try:
            from app.services.concierge.escalation_service import get_escalation_service
            svc = get_escalation_service()
            svc.acknowledge_ticket(ticket_id, operator)
        except Exception:
            pass

        watch = self._get_watch()
        import asyncio
        asyncio.ensure_future(
            watch.log_agent_run(
                agent_name="escalation_handoff",
                operator_id=operator,
                success=True,
                latency_ms=ack_time * 60 * 1000,
                metadata={
                    "event": "ticket_acknowledged",
                    "ticket_id": ticket_id,
                    "priority": priority,
                    "ack_minutes": round(ack_time, 1),
                    "met_sla": met_sla,
                },
            )
        )
        return True

    # ─────────────────────────────────────────────────────────────────────────
    # SLA stats
    # ─────────────────────────────────────────────────────────────────────────

    async def get_sla_stats(self, db: AsyncSession) -> EscalationSLAStats:
        """
        Compute SLA stats for operator dashboard.
        Returns p50/p95 ack and resolve times, breach counts.
        """
        try:
            from sqlalchemy import text
            result = await db.execute(text("""
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN status IN ('pending','acknowledged','in_progress') THEN 1 ELSE 0 END) AS open_cnt,
                    SUM(CASE WHEN ack_sla_breached = TRUE THEN 1 ELSE 0 END) AS ack_breaches,
                    SUM(CASE WHEN resolve_sla_breached = TRUE THEN 1 ELSE 0 END) AS resolve_breaches,
                    PERCENTILE_CONT(0.5) WITHIN GROUP (
                        ORDER BY EXTRACT(EPOCH FROM (acknowledged_at - created_at))/60
                    ) FILTER (WHERE acknowledged_at IS NOT NULL) AS p50_ack,
                    PERCENTILE_CONT(0.95) WITHIN GROUP (
                        ORDER BY EXTRACT(EPOCH FROM (acknowledged_at - created_at))/60
                    ) FILTER (WHERE acknowledged_at IS NOT NULL) AS p95_ack,
                    PERCENTILE_CONT(0.5) WITHIN GROUP (
                        ORDER BY EXTRACT(EPOCH FROM (resolved_at - created_at))/60
                    ) FILTER (WHERE resolved_at IS NOT NULL) AS p50_resolve,
                    PERCENTILE_CONT(0.95) WITHIN GROUP (
                        ORDER BY EXTRACT(EPOCH FROM (resolved_at - created_at))/60
                    ) FILTER (WHERE resolved_at IS NOT NULL) AS p95_resolve
                FROM concierge_escalations
            """))
            row = result.fetchone()
            if row:
                total = row.total or 0
                breaches = (row.ack_breaches or 0) + (row.resolve_breaches or 0)
                return EscalationSLAStats(
                    total_tickets=total,
                    open_tickets=row.open_cnt or 0,
                    ack_breach_count=row.ack_breaches or 0,
                    resolve_breach_count=row.resolve_breaches or 0,
                    p50_ack_minutes=row.p50_ack,
                    p95_ack_minutes=row.p95_ack,
                    p50_resolve_minutes=row.p50_resolve,
                    p95_resolve_minutes=row.p95_resolve,
                    breach_rate_pct=round(breaches / total * 100, 1) if total > 0 else 0.0,
                )
        except Exception as exc:
            logger.error("[EscalationHandoff] get_sla_stats error: %s", exc)

        return EscalationSLAStats()

    # ─────────────────────────────────────────────────────────────────────────
    # Startup loader
    # ─────────────────────────────────────────────────────────────────────────

    async def load_open_tickets(self, db: AsyncSession) -> int:
        """
        Load open tickets from DB into EscalationService in-memory cache.
        Call at app startup so the dashboard always has current data.
        """
        try:
            from app.services.concierge.escalation_service import get_escalation_service
            svc = get_escalation_service()
            return await svc.load_pending_from_db()
        except Exception as exc:
            logger.error("[EscalationHandoff] load_open_tickets error: %s", exc)
            return 0

    # ─────────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────────────────────────────────────

    async def _load_open_tickets(self, db: AsyncSession) -> list:
        try:
            from sqlalchemy import text
            result = await db.execute(text("""
                SELECT ticket_id, session_token, guest_name, property_code,
                       priority, status, created_at, acknowledged_at, resolved_at,
                       ack_sla_breached, resolve_sla_breached
                FROM concierge_escalations
                WHERE status IN ('pending', 'acknowledged', 'in_progress')
                ORDER BY created_at ASC
                LIMIT 500
            """))
            return result.fetchall()
        except Exception as exc:
            await safe_rollback(db)
            logger.error("[EscalationHandoff] _load_open_tickets error: %s", exc)
            return []

    async def _load_ticket_by_id(self, db: AsyncSession, ticket_id: str):
        try:
            from sqlalchemy import text
            result = await db.execute(
                text("""
                    SELECT ticket_id, session_token, guest_name, property_code,
                           priority, status, created_at, acknowledged_at, resolved_at
                    FROM concierge_escalations
                    WHERE ticket_id = :tid
                    LIMIT 1
                """),
                {"tid": ticket_id},
            )
            return result.fetchone()
        except Exception as exc:
            await safe_rollback(db)
            logger.error("[EscalationHandoff] _load_ticket_by_id error: %s", exc)
            return None

    async def _stamp_breach(self, db: AsyncSession, ticket_id: str, breach_type: str) -> None:
        try:
            from sqlalchemy import text
            col = "ack_sla_breached" if breach_type == "ack" else "resolve_sla_breached"
            await db.execute(
                text(f"UPDATE concierge_escalations SET {col} = TRUE WHERE ticket_id = :tid"),
                {"tid": ticket_id},
            )
            await db.commit()
        except Exception as exc:
            await safe_rollback(db)
            logger.debug("[EscalationHandoff] _stamp_breach error (non-fatal): %s", exc)

    async def _resolve_in_db(
        self,
        db: AsyncSession,
        ticket_id: str,
        operator: str,
        note: str,
        resolution_code: Optional[str],
    ) -> None:
        import json
        from sqlalchemy import text
        from app.services.operator.escalation_workflow_service import get_escalation_workflow_service
        await db.execute(
            text("""
                UPDATE concierge_escalations
                SET status = 'resolved',
                    resolved_at = NOW(),
                    assigned_to = :operator,
                    resolution_code = :code,
                    notes = notes || :note_json::jsonb
                WHERE ticket_id = :tid
            """),
            {
                "tid": ticket_id,
                "operator": operator,
                "code": resolution_code or "resolved",
                "note_json": json.dumps([{
                    "author": operator,
                    "text": note,
                    "timestamp": datetime.utcnow().isoformat(),
                }]),
            },
        )
        await db.commit()
        tenant_row = await db.execute(
            text(
                """
                SELECT s.tenant_id
                FROM concierge_escalations e
                JOIN concierge_guest_sessions s ON s.token = e.session_token
                WHERE e.ticket_id = :tid
                LIMIT 1
                """
            ),
            {"tid": ticket_id},
        )
        tenant = tenant_row.fetchone()
        if tenant and tenant[0]:
            await get_escalation_workflow_service().sync_ticket(db, str(tenant[0]), ticket_id)

    async def _ack_in_db(self, db: AsyncSession, ticket_id: str, operator: str) -> None:
        from sqlalchemy import text
        from app.services.operator.escalation_workflow_service import get_escalation_workflow_service
        await db.execute(
            text("""
                UPDATE concierge_escalations
                SET status = 'acknowledged',
                    acknowledged_at = NOW(),
                    assigned_to = :operator
                WHERE ticket_id = :tid AND acknowledged_at IS NULL
            """),
            {"tid": ticket_id, "operator": operator},
        )
        await db.commit()
        tenant_row = await db.execute(
            text(
                """
                SELECT s.tenant_id
                FROM concierge_escalations e
                JOIN concierge_guest_sessions s ON s.token = e.session_token
                WHERE e.ticket_id = :tid
                LIMIT 1
                """
            ),
            {"tid": ticket_id},
        )
        tenant = tenant_row.fetchone()
        if tenant and tenant[0]:
            await get_escalation_workflow_service().sync_ticket(db, str(tenant[0]), ticket_id)

    async def _fire_breach_alert(self, breach: SLABreach) -> None:
        import asyncio
        watch = self._get_watch()
        asyncio.ensure_future(
            watch.log_agent_run(
                agent_name="escalation_sla",
                operator_id=breach.operator_id or "ops",
                success=False,  # breach = failure
                latency_ms=breach.elapsed_minutes * 60 * 1000,
                metadata={
                    "event": "sla_breach",
                    "ticket_id": breach.ticket_id,
                    "breach_type": breach.breach_type,
                    "priority": breach.priority,
                    "sla_target_minutes": breach.sla_minutes,
                    "elapsed_minutes": round(breach.elapsed_minutes, 1),
                    "property_code": breach.property_code,
                    "guest_name": breach.guest_name,
                },
            )
        )
        logger.warning(
            "[EscalationSLA] BREACH ticket=%s priority=%s type=%s elapsed=%.0fmin sla=%dmin",
            breach.ticket_id, breach.priority, breach.breach_type,
            breach.elapsed_minutes, breach.sla_minutes,
        )


# =============================================================================
# Singleton
# =============================================================================

_handoff_agent: Optional[EscalationHandoffAgent] = None


def get_escalation_handoff_agent() -> EscalationHandoffAgent:
    global _handoff_agent
    if _handoff_agent is None:
        _handoff_agent = EscalationHandoffAgent()
    return _handoff_agent
