from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class OperatorHandoffService:
    async def create_or_refresh_handoff(
        self,
        session: AsyncSession,
        tenant_id: str,
        *,
        workflow_type: str,
        workflow_ref: str,
        handoff_type: str,
        property_code: str | None = None,
        priority: str = "medium",
        subject: str = "",
        body: str = "",
        assignee_user_id: str | None = None,
        assignee_label: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not workflow_ref or not await self._table_exists(session, "operator_workflow_handoffs"):
            return {}

        existing = (
            await session.execute(
                text(
                    """
                    SELECT CAST(handoff_id AS text) AS handoff_id, status
                    FROM operator_workflow_handoffs
                    WHERE tenant_id = CAST(:tid AS uuid)
                      AND workflow_type = :workflow_type
                      AND workflow_ref = :workflow_ref
                      AND handoff_type = :handoff_type
                      AND status IN ('open', 'in_progress', 'blocked')
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """
                ),
                {
                    "tid": tenant_id,
                    "workflow_type": workflow_type,
                    "workflow_ref": workflow_ref,
                    "handoff_type": handoff_type,
                },
            )
        ).mappings().first()

        if existing:
            await session.execute(
                text(
                    """
                    UPDATE operator_workflow_handoffs
                    SET priority = :priority,
                        property_code = :property_code,
                        assignee_user_id = COALESCE(:assignee_user_id, assignee_user_id),
                        assignee_label = COALESCE(:assignee_label, assignee_label),
                        subject = :subject,
                        body = :body,
                        payload_json = CAST(:payload_json AS jsonb),
                        updated_at = NOW()
                    WHERE handoff_id = CAST(:handoff_id AS uuid)
                    """
                ),
                {
                    "handoff_id": existing["handoff_id"],
                    "priority": priority,
                    "property_code": property_code,
                    "assignee_user_id": assignee_user_id,
                    "assignee_label": assignee_label,
                    "subject": subject,
                    "body": body,
                    "payload_json": json.dumps(payload or {}),
                },
            )
            return {
                "handoff_id": str(existing["handoff_id"]),
                "status": str(existing.get("status") or "open"),
                "workflow_type": workflow_type,
                "workflow_ref": workflow_ref,
                "handoff_type": handoff_type,
            }

        created = (
            await session.execute(
                text(
                    """
                    INSERT INTO operator_workflow_handoffs
                        (tenant_id, workflow_type, workflow_ref, handoff_type, status, priority,
                         property_code, assignee_user_id, assignee_label, subject, body, payload_json)
                    VALUES
                        (CAST(:tid AS uuid), :workflow_type, :workflow_ref, :handoff_type, 'open', :priority,
                         :property_code, :assignee_user_id, :assignee_label, :subject, :body, CAST(:payload_json AS jsonb))
                    RETURNING CAST(handoff_id AS text) AS handoff_id, status
                    """
                ),
                {
                    "tid": tenant_id,
                    "workflow_type": workflow_type,
                    "workflow_ref": workflow_ref,
                    "handoff_type": handoff_type,
                    "priority": priority,
                    "property_code": property_code,
                    "assignee_user_id": assignee_user_id,
                    "assignee_label": assignee_label,
                    "subject": subject,
                    "body": body,
                    "payload_json": json.dumps(payload or {}),
                },
            )
        ).mappings().first()
        return {
            "handoff_id": str(created["handoff_id"]) if created else "",
            "status": str(created.get("status") or "open") if created else "open",
            "workflow_type": workflow_type,
            "workflow_ref": workflow_ref,
            "handoff_type": handoff_type,
        }

    async def list_handoffs(
        self,
        session: AsyncSession,
        tenant_id: str,
        *,
        workflow_type: str,
        workflow_refs: list[str],
    ) -> dict[str, list[dict[str, Any]]]:
        if not workflow_refs or not await self._table_exists(session, "operator_workflow_handoffs"):
            return {}
        rows = (
            await session.execute(
                text(
                    """
                    SELECT CAST(handoff_id AS text) AS handoff_id,
                           workflow_ref, handoff_type, status, priority, property_code,
                           assignee_user_id, assignee_label, subject, body,
                           payload_json, resolution_json, created_at, updated_at, closed_at
                    FROM operator_workflow_handoffs
                    WHERE tenant_id = CAST(:tid AS uuid)
                      AND workflow_type = :workflow_type
                      AND workflow_ref = ANY(CAST(:workflow_refs AS text[]))
                    ORDER BY
                        CASE status
                            WHEN 'open' THEN 0
                            WHEN 'in_progress' THEN 1
                            WHEN 'blocked' THEN 2
                            ELSE 3
                        END,
                        updated_at DESC
                    """
                ),
                {
                    "tid": tenant_id,
                    "workflow_type": workflow_type,
                    "workflow_refs": workflow_refs,
                },
            )
        ).mappings().all()
        result: dict[str, list[dict[str, Any]]] = {ref: [] for ref in workflow_refs}
        for row in rows:
            payload = row.get("payload_json")
            resolution = row.get("resolution_json")
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except Exception:
                    payload = {}
            if isinstance(resolution, str):
                try:
                    resolution = json.loads(resolution)
                except Exception:
                    resolution = {}
            result.setdefault(str(row["workflow_ref"]), []).append(
                {
                    "handoff_id": str(row["handoff_id"]),
                    "handoff_type": row["handoff_type"],
                    "status": row["status"],
                    "priority": row["priority"],
                    "property_code": row.get("property_code"),
                    "assignee_user_id": row.get("assignee_user_id"),
                    "assignee_label": row.get("assignee_label"),
                    "subject": row.get("subject"),
                    "body": row.get("body"),
                    "payload": payload if isinstance(payload, dict) else {},
                    "resolution": resolution if isinstance(resolution, dict) else {},
                    "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
                    "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
                    "closed_at": row["closed_at"].isoformat() if row.get("closed_at") else None,
                }
            )
        return result

    async def update_handoff(
        self,
        session: AsyncSession,
        tenant_id: str,
        handoff_id: str,
        *,
        status: str | None = None,
        assignee_user_id: str | None = None,
        assignee_label: str | None = None,
        resolution: dict[str, Any] | None = None,
    ) -> bool:
        if not handoff_id or not await self._table_exists(session, "operator_workflow_handoffs"):
            return False
        next_status = (status or "").strip().lower() or None
        if next_status and next_status not in {"open", "in_progress", "blocked", "completed", "cancelled"}:
            raise ValueError("Invalid handoff status")
        await session.execute(
            text(
                """
                UPDATE operator_workflow_handoffs
                SET status = COALESCE(:status, status),
                    assignee_user_id = COALESCE(:assignee_user_id, assignee_user_id),
                    assignee_label = COALESCE(:assignee_label, assignee_label),
                    resolution_json = CASE
                        WHEN :resolution_json IS NULL THEN resolution_json
                        ELSE CAST(:resolution_json AS jsonb)
                    END,
                    closed_at = CASE
                        WHEN COALESCE(:status, status) IN ('completed', 'cancelled') THEN NOW()
                        ELSE NULL
                    END,
                    updated_at = NOW()
                WHERE tenant_id = CAST(:tid AS uuid)
                  AND handoff_id = CAST(:handoff_id AS uuid)
                """
            ),
            {
                "tid": tenant_id,
                "handoff_id": handoff_id,
                "status": next_status,
                "assignee_user_id": assignee_user_id,
                "assignee_label": assignee_label,
                "resolution_json": json.dumps(resolution) if resolution is not None else None,
            },
        )
        return True

    async def get_handoff(
        self,
        session: AsyncSession,
        tenant_id: str,
        handoff_id: str,
    ) -> dict[str, Any]:
        if not handoff_id or not await self._table_exists(session, "operator_workflow_handoffs"):
            return {}
        row = (
            await session.execute(
                text(
                    """
                    SELECT CAST(handoff_id AS text) AS handoff_id,
                           workflow_type, workflow_ref, handoff_type, status, priority,
                           property_code, assignee_user_id, assignee_label,
                           subject, body, payload_json, resolution_json,
                           created_at, updated_at, closed_at
                    FROM operator_workflow_handoffs
                    WHERE tenant_id = CAST(:tid AS uuid)
                      AND handoff_id = CAST(:handoff_id AS uuid)
                    LIMIT 1
                    """
                ),
                {"tid": tenant_id, "handoff_id": handoff_id},
            )
        ).mappings().first()
        if not row:
            return {}
        item = dict(row)
        for key in ("payload_json", "resolution_json"):
            value = item.get(key)
            if isinstance(value, str):
                try:
                    item[key] = json.loads(value)
                except Exception:
                    item[key] = {}
        return item

    async def summarize_handoffs(
        self,
        session: AsyncSession,
        tenant_id: str,
        *,
        workflow_type: str,
        workflow_ref: str,
    ) -> dict[str, Any]:
        if not workflow_ref or not await self._table_exists(session, "operator_workflow_handoffs"):
            return {"open_count": 0, "total_count": 0, "types": [], "items": []}
        items = (await self.list_handoffs(session, tenant_id, workflow_type=workflow_type, workflow_refs=[workflow_ref])).get(workflow_ref, [])
        open_items = [item for item in items if str(item.get("status") or "").lower() in {"open", "in_progress", "blocked"}]
        return {
            "open_count": len(open_items),
            "total_count": len(items),
            "types": sorted({str(item.get("handoff_type") or "") for item in items if item.get("handoff_type")}),
            "items": items[:10],
        }

    async def _table_exists(self, session: AsyncSession, table_name: str) -> bool:
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


_SERVICE = OperatorHandoffService()


def get_operator_handoff_service() -> OperatorHandoffService:
    return _SERVICE
