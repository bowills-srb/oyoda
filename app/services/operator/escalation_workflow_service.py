from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.operator.escalation_action_agent import get_escalation_action_agent
from app.services.operator.escalation_detector_service import get_escalation_detector_service
from app.services.operator.handoff_service import get_operator_handoff_service
from app.services.operator.work_order_service import get_operator_work_order_service

logger = logging.getLogger(__name__)


def _iso(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


class EscalationWorkflowService:
    async def sync_ticket(
        self,
        session: AsyncSession,
        tenant_id: str,
        ticket_id: str,
    ) -> bool:
        if not ticket_id:
            return False
        row = await self._load_ticket_row(session, tenant_id, ticket_id)
        if not row:
            return False
        existing_workflow = await self._existing_workflow(session, tenant_id, ticket_id)
        workflow = self._build_workflow(dict(row), existing_workflow)
        workflow["detectors"] = get_escalation_detector_service().detect(dict(row), workflow)
        workflow["actions"] = await get_escalation_action_agent().sync_actions(session, tenant_id, dict(row), workflow)
        workflow["handoffs"] = await get_operator_handoff_service().summarize_handoffs(
            session,
            tenant_id,
            workflow_type="escalation",
            workflow_ref=ticket_id,
        )
        try:
            workflow["work_orders"] = await get_operator_work_order_service().summarize_work_orders(
                session,
                tenant_id,
                workflow_type="escalation",
                workflow_ref=ticket_id,
            )
        except Exception:
            workflow["work_orders"] = {"open_count": 0, "total_count": 0, "statuses": [], "items": []}
        await self._persist_workflow(session, tenant_id, dict(row), workflow)
        return True

    async def sync_rows(
        self,
        session: AsyncSession,
        tenant_id: str,
        rows: list[dict],
    ) -> None:
        if not rows:
            return
        if not await self._table_exists(session, "operator_escalation_workflow_read_models"):
            return
        try:
            for row in rows:
                existing_workflow = await self._existing_workflow(session, tenant_id, str(row.get("ticket_id") or ""))
                workflow = self._build_workflow(row, existing_workflow)
                workflow["detectors"] = get_escalation_detector_service().detect(row, workflow)
                workflow["actions"] = await get_escalation_action_agent().sync_actions(session, tenant_id, row, workflow)
                workflow["handoffs"] = await get_operator_handoff_service().summarize_handoffs(
                    session,
                    tenant_id,
                    workflow_type="escalation",
                    workflow_ref=str(row.get("ticket_id") or ""),
                )
                try:
                    workflow["work_orders"] = await get_operator_work_order_service().summarize_work_orders(
                        session,
                        tenant_id,
                        workflow_type="escalation",
                        workflow_ref=str(row.get("ticket_id") or ""),
                    )
                except Exception:
                    workflow["work_orders"] = {"open_count": 0, "total_count": 0, "statuses": [], "items": []}
                await self._persist_workflow(session, tenant_id, row, workflow, commit=False)
            await session.commit()
        except Exception as exc:
            logger.warning("[EscalationWorkflowService] sync_rows failed: %s", exc)
            try:
                await session.rollback()
            except Exception:
                pass

    async def workflow_map(
        self,
        session: AsyncSession,
        tenant_id: str,
        ticket_ids: list[str],
    ) -> dict[str, dict]:
        if not ticket_ids or not await self._table_exists(session, "operator_escalation_workflow_read_models"):
            return {}
        try:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT ticket_id, workflow_json
                        FROM operator_escalation_workflow_read_models
                        WHERE tenant_id = CAST(:tid AS uuid)
                          AND ticket_id = ANY(CAST(:ticket_ids AS text[]))
                        """
                    ),
                    {"tid": tenant_id, "ticket_ids": ticket_ids},
                )
            ).mappings().all()
            result: dict[str, dict] = {}
            for row in rows:
                workflow = row["workflow_json"]
                if isinstance(workflow, str):
                    try:
                        workflow = json.loads(workflow)
                    except Exception:
                        workflow = {}
                result[str(row["ticket_id"])] = workflow if isinstance(workflow, dict) else {}
            return result
        except Exception as exc:
            logger.warning("[EscalationWorkflowService] workflow_map failed: %s", exc)
            try:
                await session.rollback()
            except Exception:
                pass
            return {}

    async def _load_ticket_row(
        self,
        session: AsyncSession,
        tenant_id: str,
        ticket_id: str,
    ) -> Optional[dict]:
        try:
            row = (
                await session.execute(
                    text(
                        """
                        SELECT e.ticket_id,
                               e.session_token,
                               e.property_code,
                               e.priority,
                               e.status,
                               e.reason,
                               e.summary,
                               e.last_message,
                               e.assigned_to,
                               e.watchers,
                               e.watchers_notified_at,
                               e.vendor_name,
                               e.vendor_phone,
                               e.vendor_eta_minutes,
                               e.vendor_status,
                               e.guest_updated_at,
                               e.guest_update_status,
                               e.guest_update_due_at,
                               e.guest_update_note,
                               e.resolution_notes,
                               e.acknowledged_at,
                               e.resolved_at,
                               e.created_at,
                               e.updated_at,
                               e.ack_sla_breached,
                               e.resolve_sla_breached,
                               s.session_id,
                               s.guest_name,
                               s.guest_phone
                        FROM concierge_escalations e
                        JOIN concierge_guest_sessions s
                          ON s.token = e.session_token
                        WHERE e.ticket_id = :ticket_id
                          AND s.tenant_id = CAST(:tid AS uuid)
                        LIMIT 1
                        """
                    ),
                    {"ticket_id": ticket_id, "tid": tenant_id},
                )
            ).mappings().first()
            return dict(row) if row else None
        except Exception as exc:
            logger.warning("[EscalationWorkflowService] load ticket failed: %s", exc)
            try:
                await session.rollback()
            except Exception:
                pass
            return None

    def _build_workflow(self, row: dict, existing_workflow: Optional[dict] = None) -> dict:
        existing_workflow = existing_workflow if isinstance(existing_workflow, dict) else {}
        status = str(row.get("status") or "pending").lower()
        assigned_to = str(row.get("assigned_to") or "").strip()
        watchers = row.get("watchers") or []
        vendor_status = str(row.get("vendor_status") or "").strip().lower()
        guest_update_status = str(row.get("guest_update_status") or "").strip().lower()

        owner_state = "assigned" if assigned_to else ("acknowledged" if row.get("acknowledged_at") else "unassigned")
        watcher_state = (
            "notified" if row.get("watchers_notified_at") else
            ("tracking" if watchers else "none")
        )
        vendor_state = (
            vendor_status or
            ("selected" if row.get("vendor_name") else "not_started")
        )
        guest_state = (
            guest_update_status or
            ("updated" if row.get("guest_updated_at") else "pending")
        )

        if row.get("resolved_at") or status in {"resolved", "closed"}:
            workflow_stage = "resolved"
        elif vendor_state not in {"", "not_started"}:
            workflow_stage = "vendor_dispatch"
        elif owner_state in {"assigned", "acknowledged"} or watcher_state in {"tracking", "notified"}:
            workflow_stage = "triaged"
        else:
            workflow_stage = "detected"

        timeline = [
            {"key": "detected", "label": "Detected", "at": _iso(row.get("created_at")), "done": True},
            {
                "key": "triaged",
                "label": "Triaged",
                "at": _iso(row.get("acknowledged_at") or row.get("updated_at") if (assigned_to or watchers) else None),
                "done": bool(assigned_to or watchers or row.get("acknowledged_at")),
            },
            {
                "key": "vendor_dispatch",
                "label": "Vendor dispatch",
                "at": _iso(row.get("updated_at") if row.get("vendor_name") or vendor_status else None),
                "done": bool(row.get("vendor_name") or vendor_status),
            },
            {
                "key": "guest_update",
                "label": "Guest updated",
                "at": _iso(row.get("guest_updated_at")),
                "done": bool(row.get("guest_updated_at") or guest_update_status == "sent_to_guest"),
            },
            {
                "key": "resolved",
                "label": "Resolved",
                "at": _iso(row.get("resolved_at")),
                "done": bool(row.get("resolved_at") or status in {"resolved", "closed"}),
            },
        ]

        existing_vendor = existing_workflow.get("vendor") if isinstance(existing_workflow.get("vendor"), dict) else {}
        vendor_history = existing_workflow.get("vendor_history") if isinstance(existing_workflow.get("vendor_history"), list) else []

        return {
            "stage": workflow_stage,
            "owner_state": owner_state,
            "watcher_state": watcher_state,
            "vendor_state": vendor_state,
            "guest_update_state": guest_state,
            "priority": row.get("priority"),
            "reason": row.get("reason"),
            "summary": row.get("summary"),
            "assigned_to": assigned_to or None,
            "watcher_count": len(watchers) if isinstance(watchers, list) else 0,
            "vendor": {
                "name": row.get("vendor_name"),
                "phone": row.get("vendor_phone"),
                "eta_minutes": row.get("vendor_eta_minutes"),
                "status": vendor_state,
                "selected_vendor_id": row.get("vendor_id") if "vendor_id" in row else None,
                "previous_vendor_name": existing_vendor.get("previous_vendor_name"),
                "previous_status": existing_vendor.get("previous_status"),
                "status_changed_at": existing_vendor.get("status_changed_at"),
                "status_changed_by": existing_vendor.get("status_changed_by"),
                "replacement_count": int(existing_vendor.get("replacement_count") or 0),
                "last_transition_note": existing_vendor.get("last_transition_note"),
            },
            "vendor_history": vendor_history,
            "guest_update": {
                "status": guest_state,
                "due_at": _iso(row.get("guest_update_due_at")),
                "updated_at": _iso(row.get("guest_updated_at")),
                "note": row.get("guest_update_note"),
            },
            "sla": {
                "acknowledged_at": _iso(row.get("acknowledged_at")),
                "resolved_at": _iso(row.get("resolved_at")),
                "ack_breached": bool(row.get("ack_sla_breached")),
                "resolve_breached": bool(row.get("resolve_sla_breached")),
            },
            "timeline": timeline,
            "work_orders": existing_workflow.get("work_orders") if isinstance(existing_workflow.get("work_orders"), dict) else {"open_count": 0, "total_count": 0, "statuses": [], "items": []},
            "refreshed_at": datetime.now(timezone.utc).isoformat(),
        }

    async def _existing_workflow(
        self,
        session: AsyncSession,
        tenant_id: str,
        ticket_id: str,
    ) -> dict:
        if not ticket_id or not await self._table_exists(session, "operator_escalation_workflow_read_models"):
            return {}
        try:
            row = (
                await session.execute(
                    text(
                        """
                        SELECT workflow_json
                        FROM operator_escalation_workflow_read_models
                        WHERE tenant_id = CAST(:tid AS uuid)
                          AND ticket_id = :ticket_id
                        LIMIT 1
                        """
                    ),
                    {"tid": tenant_id, "ticket_id": ticket_id},
                )
            ).mappings().first()
            workflow = row.get("workflow_json") if row else {}
            if isinstance(workflow, str):
                try:
                    workflow = json.loads(workflow)
                except Exception:
                    workflow = {}
            return workflow if isinstance(workflow, dict) else {}
        except Exception:
            try:
                await session.rollback()
            except Exception:
                pass
            return {}

    async def record_vendor_transition(
        self,
        session: AsyncSession,
        tenant_id: str,
        ticket_id: str,
        entry: dict,
    ) -> bool:
        if not ticket_id or not await self._table_exists(session, "operator_escalation_workflow_read_models"):
            return False
        workflow = await self._existing_workflow(session, tenant_id, ticket_id)
        history = workflow.get("vendor_history") if isinstance(workflow.get("vendor_history"), list) else []
        history.append(entry)
        workflow["vendor_history"] = history[-20:]
        vendor = workflow.get("vendor") if isinstance(workflow.get("vendor"), dict) else {}
        previous_status = str(vendor.get("status") or "").strip().lower() or None
        next_status = str(entry.get("vendor_status") or vendor.get("status") or "").strip().lower() or None
        if next_status != previous_status:
            vendor["previous_status"] = previous_status
            vendor["status_changed_at"] = entry.get("changed_at")
        if entry.get("previous_vendor_name"):
            vendor["previous_vendor_name"] = entry.get("previous_vendor_name")
            vendor["replacement_count"] = int(vendor.get("replacement_count") or 0) + 1
        vendor["status"] = next_status
        vendor["status_changed_by"] = entry.get("changed_by") or vendor.get("status_changed_by")
        vendor["last_transition_note"] = entry.get("note") or vendor.get("last_transition_note")
        workflow["vendor"] = vendor
        await session.execute(
            text(
                """
                UPDATE operator_escalation_workflow_read_models
                SET workflow_json = CAST(:workflow_json AS jsonb),
                    updated_at = NOW(),
                    refreshed_at = NOW()
                WHERE tenant_id = CAST(:tid AS uuid)
                  AND ticket_id = :ticket_id
                """
            ),
            {
                "tid": tenant_id,
                "ticket_id": ticket_id,
                "workflow_json": json.dumps(workflow),
            },
        )
        return True

    async def _persist_workflow(
        self,
        session: AsyncSession,
        tenant_id: str,
        row: dict,
        workflow: dict,
        *,
        commit: bool = True,
    ) -> None:
        if not await self._table_exists(session, "operator_escalation_workflow_read_models"):
            return
        await session.execute(
            text(
                """
                INSERT INTO operator_escalation_workflow_read_models
                    (ticket_id, tenant_id, session_token, property_code, workflow_stage,
                     owner_state, vendor_state, guest_update_state, workflow_json, refreshed_at, updated_at)
                VALUES
                    (:ticket_id, CAST(:tid AS uuid), :session_token, :property_code, :workflow_stage,
                     :owner_state, :vendor_state, :guest_update_state, CAST(:workflow_json AS jsonb), NOW(), NOW())
                ON CONFLICT (ticket_id) DO UPDATE SET
                    tenant_id = EXCLUDED.tenant_id,
                    session_token = EXCLUDED.session_token,
                    property_code = EXCLUDED.property_code,
                    workflow_stage = EXCLUDED.workflow_stage,
                    owner_state = EXCLUDED.owner_state,
                    vendor_state = EXCLUDED.vendor_state,
                    guest_update_state = EXCLUDED.guest_update_state,
                    workflow_json = EXCLUDED.workflow_json,
                    refreshed_at = EXCLUDED.refreshed_at,
                    updated_at = EXCLUDED.updated_at
                """
            ),
            {
                "ticket_id": row.get("ticket_id"),
                "tid": tenant_id,
                "session_token": row.get("session_token") or "",
                "property_code": row.get("property_code") or "",
                "workflow_stage": workflow.get("stage") or "detected",
                "owner_state": workflow.get("owner_state"),
                "vendor_state": workflow.get("vendor_state"),
                "guest_update_state": workflow.get("guest_update_state"),
                "workflow_json": json.dumps(workflow),
            },
        )
        if commit:
            await session.commit()

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


_SERVICE = EscalationWorkflowService()


def get_escalation_workflow_service() -> EscalationWorkflowService:
    return _SERVICE
