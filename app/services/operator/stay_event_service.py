from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


_EVENT_DOMAIN_BY_TYPE = {
    "guest_review_received": "post_stay",
    "guest_review_signal": "post_stay",
    "guest_checked_out": "turnover",
    "housekeeping_arrived": "turnover",
    "housekeeping_completed": "turnover",
    "linen_pickup_started": "turnover",
    "linen_returned": "turnover",
    "property_ready": "turnover",
    "documentation_started": "walkthrough",
    "documentation_completed": "walkthrough",
    "walkthrough_started": "walkthrough",
    "walkthrough_completed": "walkthrough",
    "vendor_arrived": "vendor",
    "vendor_completed": "vendor",
}


class StayEventService:
    def summarize_event_rows(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        counts_by_domain: dict[str, int] = {}
        latest_by_type: dict[str, dict[str, Any]] = {}
        recent: list[dict[str, Any]] = []

        for row in rows:
            event = dict(row)
            event_type = str(event.get("event_type") or "").strip().lower()
            event_domain = str(event.get("event_domain") or "").strip().lower() or _EVENT_DOMAIN_BY_TYPE.get(event_type, "ops")
            event["event_type"] = event_type
            event["event_domain"] = event_domain
            counts_by_domain[event_domain] = counts_by_domain.get(event_domain, 0) + 1
            if event_type and event_type not in latest_by_type:
                latest_by_type[event_type] = event
            recent.append(event)

        def _ts(event_type: str) -> str | None:
            event = latest_by_type.get(event_type) or {}
            return event.get("occurred_at") or event.get("created_at")

        documentation_completed_at = (
            _ts("documentation_completed")
            or _ts("walkthrough_completed")
        )
        documentation_started_at = (
            _ts("documentation_started")
            or _ts("walkthrough_started")
        )

        return {
            "count": len(recent),
            "counts_by_domain": counts_by_domain,
            "recent": recent[:8],
            "last_event_type": recent[0].get("event_type") if recent else None,
            "property_ready_at": _ts("property_ready"),
            "housekeeping_arrived_at": _ts("housekeeping_arrived"),
            "housekeeping_completed_at": _ts("housekeeping_completed"),
            "documentation_started_at": documentation_started_at,
            "documentation_completed_at": documentation_completed_at,
            "latest_by_type": latest_by_type,
        }

    async def list_events(
        self,
        session: AsyncSession,
        tenant_id: str,
        session_id: str,
        *,
        limit: int = 40,
    ) -> list[dict[str, Any]]:
        if not session_id or not await self._table_exists(session, "operator_stay_events"):
            return []
        rows = (
            await session.execute(
                text(
                    """
                    SELECT CAST(stay_event_id AS text) AS stay_event_id,
                           CAST(session_id AS text) AS session_id,
                           session_token,
                           property_code,
                           event_type,
                           event_domain,
                           status,
                           source,
                           note,
                           payload_json,
                           created_by,
                           occurred_at,
                           created_at,
                           updated_at
                    FROM operator_stay_events
                    WHERE tenant_id = CAST(:tid AS uuid)
                      AND session_id = CAST(:sid AS uuid)
                    ORDER BY occurred_at DESC, created_at DESC
                    LIMIT :limit
                    """
                ),
                {"tid": tenant_id, "sid": session_id, "limit": int(limit)},
            )
        ).mappings().all()
        return [self._serialize_event_row(row) for row in rows]

    async def summarize_events(
        self,
        session: AsyncSession,
        tenant_id: str,
        session_id: str,
    ) -> dict[str, Any]:
        rows = await self.list_events(session, tenant_id, session_id, limit=25)
        return self.summarize_event_rows(rows)

    async def record_event(
        self,
        session: AsyncSession,
        tenant_id: str,
        *,
        session_id: str,
        session_token: str | None,
        property_code: str | None,
        event_type: str,
        status: str = "completed",
        source: str = "operator",
        note: str | None = None,
        payload: dict[str, Any] | None = None,
        occurred_at: str | None = None,
        created_by: str | None = None,
    ) -> dict[str, Any]:
        if not await self._table_exists(session, "operator_stay_events"):
            return {}

        normalized_event_type = str(event_type or "").strip().lower()
        event_domain = _EVENT_DOMAIN_BY_TYPE.get(normalized_event_type, "ops")
        payload = payload if isinstance(payload, dict) else {}
        note = (note or "").strip() or None
        created_by = (created_by or "").strip() or "operator"
        source = (source or "").strip() or "operator"
        status = (status or "").strip().lower() or "completed"
        occurred_at_value = occurred_at or datetime.now(timezone.utc).isoformat()

        row = (
            await session.execute(
                text(
                    """
                    INSERT INTO operator_stay_events
                        (tenant_id, session_id, session_token, property_code,
                         event_type, event_domain, status, source, note,
                         payload_json, occurred_at, created_by)
                    VALUES
                        (CAST(:tid AS uuid), CAST(:sid AS uuid), :session_token, :property_code,
                         :event_type, :event_domain, :status, :source, :note,
                         CAST(:payload_json AS jsonb), CAST(:occurred_at AS timestamptz), :created_by)
                    RETURNING CAST(stay_event_id AS text) AS stay_event_id,
                              CAST(session_id AS text) AS session_id,
                              session_token,
                              property_code,
                              event_type,
                              event_domain,
                              status,
                              source,
                              note,
                              payload_json,
                              created_by,
                              occurred_at,
                              created_at,
                              updated_at
                    """
                ),
                {
                    "tid": tenant_id,
                    "sid": session_id,
                    "session_token": session_token or "",
                    "property_code": property_code or "",
                    "event_type": normalized_event_type,
                    "event_domain": event_domain,
                    "status": status,
                    "source": source,
                    "note": note,
                    "payload_json": json.dumps(payload),
                    "occurred_at": occurred_at_value,
                    "created_by": created_by,
                },
            )
        ).mappings().first()
        return self._serialize_event_row(row or {})

    def _serialize_event_row(self, row: dict[str, Any]) -> dict[str, Any]:
        event = dict(row)
        payload = event.get("payload_json")
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                payload = {}
        event["payload_json"] = payload if isinstance(payload, dict) else {}
        for key in ("occurred_at", "created_at", "updated_at"):
            value = event.get(key)
            if isinstance(value, datetime):
                event[key] = value.isoformat()
        return event

    async def _table_exists(self, session: AsyncSession, table_name: str) -> bool:
        try:
            exists = await session.scalar(
                text(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM information_schema.tables
                        WHERE table_schema = 'public'
                          AND table_name = :table_name
                    )
                    """
                ),
                {"table_name": table_name},
            )
            return bool(exists)
        except Exception:
            return False


_SERVICE = StayEventService()


def get_stay_event_service() -> StayEventService:
    return _SERVICE
