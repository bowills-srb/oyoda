from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.operator.stay_action_agent import StayActionAgent, get_stay_action_agent
from app.services.operator.stay_workflow_service import get_stay_workflow_service


logger = logging.getLogger(__name__)


class StayProactiveRuntimeService:
    """Canonical automated proactive runtime for stay sessions.

    This service preserves session-token routing while forcing all proactive
    automation through the stay workflow + action queue + brain composition
    path. Legacy schedulers may still discover candidate sessions, but they
    should call into this service rather than compose or send directly.
    """

    async def execute_due_touch_for_token(
        self,
        session: AsyncSession,
        *,
        session_token: str,
        actor_label: str = "system:proactive-runtime",
    ) -> dict[str, Any]:
        token = str(session_token or "").strip()
        if not token:
            return {"status": "skipped", "reason": "missing_session_token"}

        row = (
            await session.execute(
                text(
                    """
                    SELECT session_id::text AS session_id,
                           tenant_id::text AS tenant_id,
                           token,
                           property_code,
                           phase
                    FROM concierge_guest_sessions
                    WHERE token = :token
                      AND status = 'active'
                    LIMIT 1
                    """
                ),
                {"token": token},
            )
        ).mappings().first()
        if not row:
            return {"status": "skipped", "reason": "session_not_found", "session_token": token}

        session_id = str(row["session_id"])
        tenant_id = str(row["tenant_id"])

        synced = await get_stay_workflow_service().sync_session(session, tenant_id, session_id)
        if not synced:
            return {
                "status": "skipped",
                "reason": "workflow_sync_failed",
                "session_token": token,
                "session_id": session_id,
            }

        action_map = await get_stay_action_agent().list_actions(session, tenant_id, [session_id])
        actions = action_map.get(session_id) or []
        proactive = next(
            (item for item in actions if str(item.get("action_type") or "") == StayActionAgent.ACTION_PROACTIVE),
            None,
        )
        if not proactive:
            return {
                "status": "skipped",
                "reason": "no_due_proactive_action",
                "session_token": token,
                "session_id": session_id,
            }

        status = str(proactive.get("status") or "").lower()
        if status == "completed":
            return {
                "status": "skipped",
                "reason": "already_completed",
                "session_token": token,
                "session_id": session_id,
            }
        if status not in {"ready", "failed"}:
            return {
                "status": "skipped",
                "reason": f"action_status_{status or 'unknown'}",
                "session_token": token,
                "session_id": session_id,
            }

        result = await get_stay_action_agent().execute_action(
            session,
            tenant_id,
            session_id,
            StayActionAgent.ACTION_PROACTIVE,
            actor_label=actor_label,
        )
        await session.commit()
        await get_stay_workflow_service().sync_session(session, tenant_id, session_id)
        return {
            **result,
            "session_token": token,
            "session_id": session_id,
            "property_code": row.get("property_code"),
            "phase": row.get("phase"),
        }

    async def list_candidate_tokens(
        self,
        session: AsyncSession,
        *,
        limit: int = 200,
    ) -> list[dict[str, str]]:
        today = date.today()
        window_end = today + timedelta(days=7)
        rows = (
            await session.execute(
                text(
                    """
                    SELECT property_code, token
                    FROM concierge_guest_sessions
                    WHERE status = 'active'
                      AND (
                        (phase = 'pre_arrival' AND check_in BETWEEN :today AND :window_end)
                        OR (phase = 'arrival_day' AND check_in = :today)
                        OR (phase = 'in_stay' AND check_out >= :today)
                        OR (phase = 'departure_day' AND check_out = :today)
                      )
                      AND (
                        proactive_triggered_at IS NULL
                        OR proactive_triggered_at < NOW() - INTERVAL '4 hours'
                      )
                    ORDER BY check_in NULLS LAST, updated_at DESC
                    LIMIT :limit
                    """
                ),
                {
                    "today": today.isoformat(),
                    "window_end": window_end.isoformat(),
                    "limit": int(limit),
                },
            )
        ).mappings().all()
        return [
            {
                "property_code": str(row.get("property_code") or ""),
                "token": str(row.get("token") or ""),
            }
            for row in rows
            if row.get("token")
        ]


_SERVICE = StayProactiveRuntimeService()


def get_stay_proactive_runtime_service() -> StayProactiveRuntimeService:
    return _SERVICE
