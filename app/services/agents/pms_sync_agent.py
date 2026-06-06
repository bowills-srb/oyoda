"""
PMS Sync Agent

Reconciles live session/property state from the PMS (Escapia/Guesty/Track)
so the concierge never gives a guest stale credentials or wrong check-in times.

Problem it solves:
  When a reservation changes in the PMS (door code re-keyed, unit swap,
  early checkout, etc.) the concierge works with the old property_context
  JSON that was captured at session-creation time.  A guest can get the
  wrong door code — embarrassing and a support escalation waiting to happen.

What it does:
  1. Polls active sessions whose `pms_synced_at` is older than SYNC_INTERVAL
  2. Calls PMS MCP `get_property_info` for each session's property
  3. Compares returned fields against DB property_context
  4. If any credential/time field changed → updates DB + logs a Watch Layer alert
  5. If PMS is offline (stub response) → skips update, logs degraded status

Integration points:
  - Called by Celery task `sync_pms_sessions` (hourly)
  - Can be called on-demand from operator dashboard or PMS webhook
  - Watch Layer alert fires whenever a credential change is detected

Usage:
    from app.services.agents.pms_sync_agent import PMSSyncAgent

    agent = PMSSyncAgent()
    result = await agent.sync_all_active_sessions(db)
    # result.synced, result.skipped, result.changed, result.errors
"""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session_safety import safe_rollback

logger = logging.getLogger(__name__)

# Fields we care about reconciling from PMS → property_context
_PMS_CREDENTIAL_FIELDS = {
    "door_code",
    "wifi_password",
    "wifi_network",
    "check_in_time",
    "check_out_time",
}

# How stale a session's PMS data can be before we re-sync
SYNC_INTERVAL_HOURS = 1


@dataclass
class PMSSyncResult:
    synced: int = 0       # sessions successfully checked against PMS
    skipped: int = 0      # PMS offline or too recent
    changed: int = 0      # sessions where at least one field was updated
    errors: int = 0       # unexpected errors (non-fatal)
    changes: List[Dict[str, Any]] = field(default_factory=list)  # audit log


class PMSSyncAgent:
    """
    Reconciles active concierge sessions against the live PMS.

    Design:
    - Async, fully non-blocking
    - PMS offline → skips gracefully, no DB writes
    - Credential change → updates property_context JSON in DB + Watch Layer alert
    - Never raises — errors are logged and counted in result.errors
    """

    def __init__(self) -> None:
        self._watch = None  # lazy-loaded

    def _get_watch(self):
        if self._watch is None:
            from app.services.observability.watch_layer import get_watch_layer
            self._watch = get_watch_layer()
        return self._watch

    # ─────────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────────

    async def sync_all_active_sessions(self, db: AsyncSession) -> PMSSyncResult:
        """
        Sync all active (non-expired) sessions whose PMS data is stale.
        Safe to call concurrently — each session update is independent.
        """
        result = PMSSyncResult()
        sessions = await self._load_stale_sessions(db)
        logger.info("[PMSSync] Found %d sessions to sync", len(sessions))

        for session in sessions:
            try:
                changed = await self._sync_session(db, session, result)
                result.synced += 1
                if changed:
                    result.changed += 1
            except Exception as exc:
                logger.error(
                    "[PMSSync] Error syncing session %s: %s",
                    getattr(session, "session_id", "?"), exc,
                )
                result.errors += 1

        logger.info(
            "[PMSSync] Done: synced=%d changed=%d skipped=%d errors=%d",
            result.synced, result.changed, result.skipped, result.errors,
        )
        return result

    async def sync_single_session(
        self,
        db: AsyncSession,
        session_token: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Force-sync a single session by token.  Used by operator dashboard
        or PMS webhook handler to refresh immediately after a PMS change.

        Returns a dict of changed fields, or None if PMS offline or no change.
        """
        session = await self._load_session_by_token(db, session_token)
        if session is None:
            logger.warning("[PMSSync] Session not found: %s", session_token)
            return None

        result = PMSSyncResult()
        try:
            await self._sync_session(db, session, result)
        except Exception as exc:
            logger.error("[PMSSync] sync_single_session error: %s", exc)
            return None

        return result.changes[0] if result.changes else None

    # ─────────────────────────────────────────────────────────────────────────
    # Core sync logic
    # ─────────────────────────────────────────────────────────────────────────

    async def _sync_session(
        self,
        db: AsyncSession,
        session,
        result: PMSSyncResult,
    ) -> bool:
        """
        Sync one session.  Returns True if any field changed.

        Steps:
        1. Call PMS MCP for the session's property
        2. Compare returned fields against current property_context
        3. If changed → update DB + fire Watch Layer alert
        4. Stamp pms_synced_at regardless (so we don't re-check too soon)
        """
        property_code = getattr(session, "property_code", None) or ""
        operator_id = getattr(session, "operator_id", None) or "unknown"
        session_id = getattr(session, "session_id", None)
        current_ctx = getattr(session, "property_context", None) or {}

        # ── Fetch from PMS MCP ────────────────────────────────────────────
        pms_data = await self._fetch_pms_property(operator_id, property_code)
        if pms_data is None:
            result.skipped += 1
            logger.debug("[PMSSync] PMS offline for %s — skipped", property_code)
            return False

        # ── Diff credential fields ────────────────────────────────────────
        changed_fields: Dict[str, Dict[str, Any]] = {}
        for field_name in _PMS_CREDENTIAL_FIELDS:
            pms_val = pms_data.get(field_name)
            cur_val = current_ctx.get(field_name)
            if pms_val is not None and pms_val != cur_val:
                changed_fields[field_name] = {"old": cur_val, "new": pms_val}

        # ── Persist changes ───────────────────────────────────────────────
        if changed_fields:
            new_ctx = dict(current_ctx)
            for fname, vals in changed_fields.items():
                new_ctx[fname] = vals["new"]

            await self._update_session_context(db, session, new_ctx)

            # Audit log
            change_record = {
                "session_id": str(session_id),
                "property_code": property_code,
                "operator_id": operator_id,
                "changed_fields": changed_fields,
                "synced_at": datetime.utcnow().isoformat(),
            }
            result.changes.append(change_record)

            # Watch Layer alert — ops wants to know when credentials change
            sensitive = {k for k in changed_fields if k in ("door_code", "wifi_password")}
            if sensitive:
                logger.warning(
                    "[PMSSync] CREDENTIAL CHANGE session=%s property=%s fields=%s",
                    session_id, property_code, list(sensitive),
                )
                watch = self._get_watch()
                import asyncio
                asyncio.ensure_future(
                    watch.log_agent_run(
                        agent_name="pms_sync",
                        operator_id=operator_id,
                        success=True,
                        latency_ms=0,
                        metadata={
                            "event": "credential_change",
                            "property_code": property_code,
                            "changed_fields": list(changed_fields.keys()),
                        },
                    )
                )
                # Evict PropertyRouter cache so next VoicePod call gets fresh creds
                try:
                    from app.services.agents.property_router import get_property_router
                    # tenant_id may not be on the session row — use a prefix scan
                    get_property_router().invalidate(operator_id, property_code)
                except Exception as exc:
                    logger.debug("[PMSSync] PropertyRouter cache eviction failed (non-fatal): %s", exc)
            else:
                logger.info(
                    "[PMSSync] Non-credential update session=%s property=%s fields=%s",
                    session_id, property_code, list(changed_fields.keys()),
                )

        # Stamp sync time
        await self._stamp_synced_at(db, session)
        return bool(changed_fields)

    # ─────────────────────────────────────────────────────────────────────────
    # PMS MCP call
    # ─────────────────────────────────────────────────────────────────────────

    async def _fetch_pms_property(
        self,
        operator_id: str,
        property_code: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Call PMS MCP `get_property_info`.  Returns None if PMS is offline
        (stub response) or on error — caller should skip and not write to DB.
        """
        try:
            from app.mcp.registry import get_mcp_registry
            registry = get_mcp_registry()
            result = await registry.call(
                server_name="pms",
                tool_name="get_property_info",
                operator_id=operator_id,
                params={"property_id": property_code},
            )
            if not result.success:
                return None
            data = result.data or {}
            # PMS offline → stub response; skip
            if data.get("_source") == "stub":
                return None
            return data
        except Exception as exc:
            logger.debug("[PMSSync] PMS MCP call failed: %s", exc)
            return None

    # ─────────────────────────────────────────────────────────────────────────
    # DB helpers
    # ─────────────────────────────────────────────────────────────────────────

    async def _load_stale_sessions(self, db: AsyncSession) -> list:
        """Load active sessions whose pms_synced_at is older than SYNC_INTERVAL."""
        try:
            from db.models.concierge_sessions import ConciergeGuestSessionModel

            cutoff = datetime.utcnow() - timedelta(hours=SYNC_INTERVAL_HOURS)
            result = await db.execute(
                select(ConciergeGuestSessionModel)
                .where(
                    ConciergeGuestSessionModel.status == "active",
                    ConciergeGuestSessionModel.check_out >= date.today(),
                    (
                        (ConciergeGuestSessionModel.pms_synced_at.is_(None))
                        | (ConciergeGuestSessionModel.pms_synced_at < cutoff)
                    ),
                )
                .order_by(ConciergeGuestSessionModel.pms_synced_at.asc().nullsfirst())
                .limit(200)
            )
            return list(result.scalars().all())
        except Exception as exc:
            await safe_rollback(db)
            logger.error("[PMSSync] Failed to load stale sessions: %s", exc)
            return []

    async def _load_session_by_token(self, db: AsyncSession, token: str):
        """Load a single session by token."""
        try:
            from db.models.concierge_sessions import ConciergeGuestSessionModel

            result = await db.execute(
                select(ConciergeGuestSessionModel)
                .where(
                    ConciergeGuestSessionModel.token == token,
                    ConciergeGuestSessionModel.status == "active",
                )
                .limit(1)
            )
            return result.scalar_one_or_none()
        except Exception as exc:
            await safe_rollback(db)
            logger.error("[PMSSync] Failed to load session by token: %s", exc)
            return None

    async def _update_session_context(
        self,
        db: AsyncSession,
        session,
        new_ctx: Dict[str, Any],
    ) -> None:
        """Write updated property_context back to DB."""
        session.property_context = new_ctx
        await db.commit()

    async def _stamp_synced_at(self, db: AsyncSession, session) -> None:
        """Stamp pms_synced_at so we don't re-check until SYNC_INTERVAL passes."""
        try:
            session.pms_synced_at = datetime.utcnow()
            await db.commit()
        except Exception as exc:
            await safe_rollback(db)
            # Non-fatal — next run will just re-sync this session
            logger.debug("[PMSSync] Failed to stamp pms_synced_at: %s", exc)


# =============================================================================
# Singleton
# =============================================================================

_pms_sync_agent: Optional[PMSSyncAgent] = None


def get_pms_sync_agent() -> PMSSyncAgent:
    global _pms_sync_agent
    if _pms_sync_agent is None:
        _pms_sync_agent = PMSSyncAgent()
    return _pms_sync_agent
