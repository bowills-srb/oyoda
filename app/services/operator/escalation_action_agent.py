from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.messaging.operator_alerts import AlertType, ESCALATION_TIMEOUTS, get_alert_router
from app.services.operator.handoff_service import get_operator_handoff_service
from app.services.operator.work_order_service import get_operator_work_order_service
from app.services.operator.escalation_detector_service import get_escalation_detector_service
from app.services.operator.vendor_intelligence_service import get_vendor_intelligence_service


logger = logging.getLogger(__name__)


class EscalationActionAgent:
    ACTION_VENDOR = "vendor_coordination"
    ACTION_GUEST_ETA = "guest_eta_update"
    ACTION_OWNER_INTERNAL = "owner_internal_update"
    ACTION_ACCOUNTING = "accounting_claim_handoff"

    async def sync_actions(
        self,
        session: AsyncSession,
        tenant_id: str,
        row: dict[str, Any],
        workflow: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if not row.get("ticket_id"):
            return []
        if not await self._table_exists(session, "operator_workflow_action_queue"):
            return []

        safety_policy = await self._load_safety_policy(session, tenant_id)
        signals = get_escalation_detector_service().detect(row, workflow, policy=safety_policy)
        desired_actions = await self._desired_actions(session, tenant_id, row, workflow, signals)
        existing = await self._existing_actions(session, tenant_id, str(row["ticket_id"]))

        try:
            for action in desired_actions:
                current = existing.get(action["action_type"]) or {}
                status = self._desired_status(current)
                result_json = current.get("result_json") if isinstance(current.get("result_json"), dict) else {}
                await session.execute(
                    text(
                        """
                        INSERT INTO operator_workflow_action_queue
                            (tenant_id, workflow_type, workflow_ref, action_type, status, priority,
                             property_code, payload_json, result_json, due_at, updated_at, completed_at)
                        VALUES
                            (CAST(:tid AS uuid), 'escalation', :workflow_ref, :action_type, :status, :priority,
                             :property_code, CAST(:payload_json AS jsonb), CAST(:result_json AS jsonb),
                             CAST(:due_at AS timestamptz), NOW(),
                             CASE WHEN :status = 'completed' THEN NOW() ELSE NULL END)
                        ON CONFLICT (workflow_type, workflow_ref, action_type) DO UPDATE SET
                            status = EXCLUDED.status,
                            priority = EXCLUDED.priority,
                            property_code = EXCLUDED.property_code,
                            payload_json = EXCLUDED.payload_json,
                            result_json = CASE
                                WHEN operator_workflow_action_queue.status = 'completed'
                                    THEN operator_workflow_action_queue.result_json
                                ELSE EXCLUDED.result_json
                            END,
                            due_at = EXCLUDED.due_at,
                            updated_at = NOW(),
                            completed_at = CASE
                                WHEN EXCLUDED.status = 'completed' THEN NOW()
                                WHEN EXCLUDED.status <> 'completed' THEN NULL
                                ELSE operator_workflow_action_queue.completed_at
                            END
                        """
                    ),
                    {
                        "tid": tenant_id,
                        "workflow_ref": str(row["ticket_id"]),
                        "action_type": action["action_type"],
                        "status": status,
                        "priority": action["priority"],
                        "property_code": action.get("property_code") or row.get("property_code"),
                        "payload_json": json.dumps(action["payload"]),
                        "result_json": json.dumps(result_json or {}),
                        "due_at": action.get("due_at"),
                    },
                )

            desired_types = {str(action["action_type"]) for action in desired_actions}
            for action_type, current in existing.items():
                if action_type in desired_types:
                    continue
                current_status = str(current.get("status") or "").lower()
                if current_status == "completed":
                    continue
                current_result = current.get("result_json") if isinstance(current.get("result_json"), dict) else {}
                current_result = {
                    **(current_result or {}),
                    "suppressed_reason": "workflow_progressed",
                    "suppressed_at": datetime.now(timezone.utc).isoformat(),
                }
                await session.execute(
                    text(
                        """
                        UPDATE operator_workflow_action_queue
                        SET status = 'blocked',
                            result_json = CAST(:result_json AS jsonb),
                            updated_at = NOW()
                        WHERE tenant_id = CAST(:tid AS uuid)
                          AND workflow_type = 'escalation'
                          AND workflow_ref = :workflow_ref
                          AND action_type = :action_type
                        """
                    ),
                    {
                        "tid": tenant_id,
                        "workflow_ref": str(row["ticket_id"]),
                        "action_type": action_type,
                        "result_json": json.dumps(current_result),
                    },
                )

            action_map = await self.list_actions(session, tenant_id, [str(row["ticket_id"])])
            return action_map.get(str(row["ticket_id"]), [])
        except Exception as exc:
            logger.warning("[EscalationActionAgent] sync_actions failed: %s", exc)
            try:
                await session.rollback()
            except Exception:
                pass
            return []

    async def list_actions(
        self,
        session: AsyncSession,
        tenant_id: str,
        ticket_ids: list[str],
    ) -> dict[str, list[dict[str, Any]]]:
        if not ticket_ids or not await self._table_exists(session, "operator_workflow_action_queue"):
            return {}
        try:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT workflow_ref, action_type, status, priority, property_code,
                               payload_json, result_json, due_at, created_at, updated_at, completed_at
                        FROM operator_workflow_action_queue
                        WHERE tenant_id = CAST(:tid AS uuid)
                          AND workflow_type = 'escalation'
                          AND workflow_ref = ANY(CAST(:ticket_ids AS text[]))
                        ORDER BY
                            CASE status
                                WHEN 'ready' THEN 0
                                WHEN 'in_progress' THEN 1
                                WHEN 'failed' THEN 2
                                WHEN 'blocked' THEN 3
                                ELSE 4
                            END,
                            updated_at DESC
                        """
                    ),
                    {"tid": tenant_id, "ticket_ids": ticket_ids},
                )
            ).mappings().all()
        except Exception as exc:
            logger.warning("[EscalationActionAgent] list_actions failed: %s", exc)
            try:
                await session.rollback()
            except Exception:
                pass
            return {}

        result: dict[str, list[dict[str, Any]]] = {ticket_id: [] for ticket_id in ticket_ids}
        for row in rows:
            payload = row.get("payload_json")
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except Exception:
                    payload = {}
            result_json = row.get("result_json")
            if isinstance(result_json, str):
                try:
                    result_json = json.loads(result_json)
                except Exception:
                    result_json = {}
            result.setdefault(str(row["workflow_ref"]), []).append(
                {
                    "action_type": row["action_type"],
                    "status": row["status"],
                    "priority": row["priority"],
                    "property_code": row["property_code"],
                    "payload": payload if isinstance(payload, dict) else {},
                    "result": result_json if isinstance(result_json, dict) else {},
                    "due_at": row["due_at"].isoformat() if row.get("due_at") else None,
                    "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
                    "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
                    "completed_at": row["completed_at"].isoformat() if row.get("completed_at") else None,
                }
            )
        return result

    async def execute_action(
        self,
        session: AsyncSession,
        tenant_id: str,
        ticket_id: str,
        action_type: str,
        *,
        actor_label: Optional[str] = None,
    ) -> dict[str, Any]:
        if not await self._table_exists(session, "operator_workflow_action_queue"):
            raise RuntimeError("Workflow action queue is not available")

        row = await self._load_action_context(session, tenant_id, ticket_id, action_type)
        if not row:
            raise RuntimeError("Workflow action not found")

        current_status = str(row.get("status") or "").lower()
        if current_status == "completed":
            return {"ok": True, "status": "completed", "already_completed": True}

        await self._set_action_status(session, tenant_id, ticket_id, action_type, "in_progress", {"started_by": actor_label or "operator"})

        if action_type == self.ACTION_VENDOR:
            result = await self._execute_vendor_coordination(session, tenant_id, row, actor_label)
        elif action_type == self.ACTION_GUEST_ETA:
            result = await self._execute_guest_eta_update(session, tenant_id, row, actor_label)
        elif action_type == self.ACTION_OWNER_INTERNAL:
            result = await self._execute_owner_internal_update(session, tenant_id, row, actor_label)
        elif action_type == self.ACTION_ACCOUNTING:
            result = await self._execute_accounting_handoff(session, tenant_id, row, actor_label)
        else:
            raise RuntimeError(f"Unsupported workflow action: {action_type}")

        final_status = result.get("status") or "completed"
        await self._set_action_status(session, tenant_id, ticket_id, action_type, final_status, result)
        return {"ok": True, **result}

    async def _desired_actions(
        self,
        session: AsyncSession,
        tenant_id: str,
        row: dict[str, Any],
        workflow: dict[str, Any],
        signals: dict[str, Any],
    ) -> list[dict[str, Any]]:
        actions: list[dict[str, Any]] = []
        property_code = row.get("property_code")
        recommended_vendors = await self._recommended_dispatch_vendors(session, tenant_id, row)
        routing_snapshot = await self._routing_snapshot(session, tenant_id, row)
        safety_protocol = signals.get("safety_protocol") or {}

        if signals.get("vendor_dispatch_needed"):
            actions.append(
                {
                    "action_type": self.ACTION_VENDOR,
                    "priority": self._action_priority(row, "vendor"),
                    "property_code": property_code,
                    "due_at": self._default_due_at(row, minutes=15),
                    "payload": {
                        "summary": row.get("summary"),
                        "reason": row.get("reason"),
                        "priority": row.get("priority"),
                        "property_code": property_code,
                        "vendor": workflow.get("vendor") or {},
                        "recommended_vendors": recommended_vendors,
                        "workflow_domain": signals.get("primary_domain"),
                        "detectors": signals,
                        "safety_protocol": safety_protocol,
                    },
                }
            )

        if signals.get("guest_eta_ready"):
            actions.append(
                {
                    "action_type": self.ACTION_GUEST_ETA,
                    "priority": self._action_priority(row, "guest"),
                    "property_code": property_code,
                    "due_at": self._default_due_at(row, minutes=10),
                    "payload": {
                        "guest_phone": row.get("guest_phone"),
                        "guest_name": row.get("guest_name"),
                        "issue_description": row.get("summary") or row.get("reason") or "maintenance issue",
                        "vendor_name": (workflow.get("vendor") or {}).get("name"),
                        "eta_minutes": (workflow.get("vendor") or {}).get("eta_minutes"),
                        "workflow_domain": signals.get("primary_domain"),
                        "detectors": signals,
                        "safety_protocol": safety_protocol,
                    },
                }
            )

        if signals.get("owner_internal_update_needed"):
            actions.append(
                {
                    "action_type": self.ACTION_OWNER_INTERNAL,
                    "priority": self._action_priority(row, "internal"),
                    "property_code": property_code,
                    "due_at": self._default_due_at(row, minutes=20),
                    "payload": {
                        "summary": row.get("summary"),
                        "priority": row.get("priority"),
                        "reason": row.get("reason"),
                        "property_code": property_code,
                        "assigned_to": row.get("assigned_to"),
                        "watchers": row.get("watchers") or [],
                        "routing_snapshot": routing_snapshot,
                        "workflow_domain": signals.get("primary_domain"),
                        "signals": signals,
                        "safety_protocol": safety_protocol,
                    },
                }
            )

        if signals.get("accounting_claim_handoff_needed"):
            actions.append(
                {
                    "action_type": self.ACTION_ACCOUNTING,
                    "priority": self._action_priority(row, "accounting"),
                    "property_code": property_code,
                    "due_at": self._default_due_at(row, minutes=30),
                    "payload": {
                        "summary": row.get("summary"),
                        "priority": row.get("priority"),
                        "reason": row.get("reason"),
                        "property_code": property_code,
                        "guest_name": row.get("guest_name"),
                        "safety_or_claims_risk": bool(signals.get("safety_or_claims_risk")),
                        "routing_snapshot": routing_snapshot,
                        "workflow_domain": signals.get("primary_domain"),
                        "signals": signals,
                        "safety_protocol": safety_protocol,
                    },
                }
            )

        return actions

    async def _load_action_context(
        self,
        session: AsyncSession,
        tenant_id: str,
        ticket_id: str,
        action_type: str,
    ) -> Optional[dict[str, Any]]:
        try:
            row = (
                await session.execute(
                    text(
                        """
                        SELECT a.action_type, a.status, a.payload_json, a.result_json,
                               e.ticket_id, e.session_token, e.property_code, e.priority, e.reason,
                               e.summary, e.last_message, e.assigned_to, e.watchers,
                               e.vendor_name, e.vendor_phone, e.vendor_eta_minutes, e.vendor_status,
                               e.guest_update_status, e.guest_update_note,
                               s.session_id, s.guest_phone, s.guest_name
                        FROM operator_workflow_action_queue a
                        LEFT JOIN concierge_escalations e
                          ON e.ticket_id = a.workflow_ref
                        LEFT JOIN concierge_guest_sessions s
                          ON s.token = e.session_token
                        WHERE a.tenant_id = CAST(:tid AS uuid)
                          AND a.workflow_type = 'escalation'
                          AND a.workflow_ref = :ticket_id
                          AND a.action_type = :action_type
                        LIMIT 1
                        """
                    ),
                    {"tid": tenant_id, "ticket_id": ticket_id, "action_type": action_type},
                )
            ).mappings().first()
            if not row:
                return None
            data = dict(row)
            for key in ("payload_json", "result_json", "watchers"):
                value = data.get(key)
                if isinstance(value, str):
                    try:
                        data[key] = json.loads(value)
                    except Exception:
                        data[key] = {}
            if data.get("watchers") is None:
                data["watchers"] = []
            return data
        except Exception as exc:
            logger.warning("[EscalationActionAgent] load_action_context failed: %s", exc)
            try:
                await session.rollback()
            except Exception:
                pass
            return None

    async def _existing_actions(
        self,
        session: AsyncSession,
        tenant_id: str,
        ticket_id: str,
    ) -> dict[str, dict[str, Any]]:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT action_type, status, payload_json, result_json
                    FROM operator_workflow_action_queue
                    WHERE tenant_id = CAST(:tid AS uuid)
                      AND workflow_type = 'escalation'
                      AND workflow_ref = :workflow_ref
                    """
                ),
                {"tid": tenant_id, "workflow_ref": ticket_id},
            )
        ).mappings().all()
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            item = dict(row)
            for key in ("payload_json", "result_json"):
                value = item.get(key)
                if isinstance(value, str):
                    try:
                        item[key] = json.loads(value)
                    except Exception:
                        item[key] = {}
            result[str(item["action_type"])] = item
        return result

    async def _execute_vendor_coordination(
        self,
        session: AsyncSession,
        tenant_id: str,
        row: dict[str, Any],
        actor_label: Optional[str],
    ) -> dict[str, Any]:
        payload = row.get("payload_json") if isinstance(row.get("payload_json"), dict) else {}
        if str(row.get("vendor_name") or "").strip():
            return {
                "status": "completed",
                "message": "Vendor already selected for escalation",
                "actor": actor_label or "operator",
            }
        recommended_vendors = payload.get("recommended_vendors") or []
        selected_vendor = recommended_vendors[0] if recommended_vendors else {}
        if selected_vendor:
            await session.execute(
                text(
                    """
                    UPDATE concierge_escalations
                    SET vendor_name = :vendor_name,
                        vendor_phone = :vendor_phone,
                        vendor_status = 'recommended',
                        updated_at = NOW()
                    WHERE ticket_id = :ticket_id
                    """
                ),
                {
                    "ticket_id": row["ticket_id"],
                    "vendor_name": selected_vendor.get("name"),
                    "vendor_phone": selected_vendor.get("phone"),
                },
            )

        await self._create_notification(
            session,
            tenant_id,
            kind="vendor_coordination_required",
            severity="warning",
            title=f"Vendor coordination needed for {row.get('property_code') or 'property'}",
            body=(
                f"Escalation {row.get('ticket_id')} requires vendor coordination. "
                f"Reason: {row.get('reason') or 'maintenance'}. Summary: {row.get('summary') or 'No summary'}."
            ),
            link_target="escalations",
            link_label="Open escalation",
        )
        try:
            await get_operator_work_order_service().create_or_refresh_work_order(
                session,
                tenant_id,
                workflow_type="escalation",
                workflow_ref=str(row.get("ticket_id") or ""),
                property_code=row.get("property_code"),
                vendor_id=selected_vendor.get("vendor_id") if selected_vendor else None,
                vendor_name=selected_vendor.get("name") if selected_vendor else None,
                vendor_phone=selected_vendor.get("phone") if selected_vendor else None,
                issue_category=str(row.get("reason") or "maintenance"),
                priority=self._action_priority(row, "vendor"),
            summary=str(row.get("summary") or row.get("reason") or "Vendor coordination needed"),
            details=str(row.get("last_message") or row.get("summary") or ""),
            dispatch_state="recommended" if selected_vendor else "opened",
            eta_minutes=selected_vendor.get("eta_minutes") if selected_vendor else None,
            eta_visibility_mode="estimated",
            last_actor_label=actor_label or "operator",
            payload={
                "recommended_vendors": recommended_vendors,
                    "selected_vendor": selected_vendor or None,
                },
            )
        except Exception:
            pass
        return {
            "status": "in_progress",
            "message": "Vendor coordination task opened for operator follow-up",
            "actor": actor_label or "operator",
            "recommended_vendors": recommended_vendors,
            "selected_vendor": selected_vendor or None,
        }

    async def _execute_guest_eta_update(
        self,
        session: AsyncSession,
        tenant_id: str,
        row: dict[str, Any],
        actor_label: Optional[str],
    ) -> dict[str, Any]:
        guest_phone = row.get("guest_phone") or (row.get("payload_json") or {}).get("guest_phone")
        vendor_name = row.get("vendor_name") or (row.get("payload_json") or {}).get("vendor_name")
        eta_minutes = row.get("vendor_eta_minutes") or (row.get("payload_json") or {}).get("eta_minutes")
        issue_description = row.get("summary") or (row.get("payload_json") or {}).get("issue_description") or "maintenance issue"

        if not guest_phone or not vendor_name or eta_minutes is None:
            return {
                "status": "blocked",
                "message": "Guest ETA update is missing guest phone, vendor name, or ETA",
                "actor": actor_label or "operator",
            }

        from app.services.messaging.channel_router import get_channel_router

        delivery = await get_channel_router().send_maintenance_eta(
            guest_phone=str(guest_phone),
            vendor_name=str(vendor_name),
            eta_minutes=int(eta_minutes),
            issue_description=str(issue_description),
        )
        if not delivery.success:
            return {
                "status": "failed",
                "message": delivery.error or "Guest ETA delivery failed",
                "actor": actor_label or "operator",
            }

        await session.execute(
            text(
                """
                UPDATE concierge_escalations
                SET guest_update_status = 'sent_to_guest',
                    guest_update_note = :note,
                    guest_updated_at = NOW(),
                    updated_at = NOW()
                WHERE ticket_id = :ticket_id
                """
            ),
            {
                "ticket_id": row["ticket_id"],
                "note": f"ETA update sent: {vendor_name} ETA {eta_minutes} minutes",
            },
        )
        return {
            "status": "completed",
            "message": "Guest ETA update sent",
            "actor": actor_label or "operator",
            "channel": str(delivery.channel.value if hasattr(delivery.channel, "value") else delivery.channel),
            "message_sid": delivery.message_sid,
        }

    async def _execute_owner_internal_update(
        self,
        session: AsyncSession,
        tenant_id: str,
        row: dict[str, Any],
        actor_label: Optional[str],
    ) -> dict[str, Any]:
        payload = row.get("payload_json") if isinstance(row.get("payload_json"), dict) else {}
        handoff = await get_operator_handoff_service().create_or_refresh_handoff(
            session,
            tenant_id,
            workflow_type="escalation",
            workflow_ref=str(row.get("ticket_id") or ""),
            handoff_type="owner_internal",
            property_code=row.get("property_code"),
            priority=str(row.get("priority") or "medium").lower() or "medium",
            subject=f"Owner/internal escalation update for {row.get('property_code') or 'property'}",
            body=(
                f"Escalation {row.get('ticket_id')} at {row.get('property_code') or 'unknown property'} "
                f"needs owner/internal visibility."
            ),
            payload={
                "ticket_id": row.get("ticket_id"),
                "session_token": row.get("session_token"),
                "summary": row.get("summary"),
                "reason": row.get("reason"),
                "routing_snapshot": payload.get("routing_snapshot") or {},
                "workflow_domain": payload.get("workflow_domain"),
                "signals": payload.get("signals") or {},
            },
        )
        await self._create_notification(
            session,
            tenant_id,
            kind="owner_internal_update",
            severity="warning" if str(row.get("priority") or "").lower() in {"high", "urgent"} else "info",
            title=f"Internal update needed for escalation {row.get('ticket_id')}",
            body=(
                f"Escalation {row.get('ticket_id')} at {row.get('property_code') or 'unknown property'} "
                f"needs owner/internal visibility. Summary: {row.get('summary') or 'No summary'}."
            ),
            link_target="escalations",
            link_label="Open escalation",
        )
        return {
            "status": "completed",
            "message": "Owner/internal update notification created",
            "actor": actor_label or "operator",
            "routing_snapshot": payload.get("routing_snapshot") or {},
            "handoff_id": handoff.get("handoff_id"),
        }

    async def _execute_accounting_handoff(
        self,
        session: AsyncSession,
        tenant_id: str,
        row: dict[str, Any],
        actor_label: Optional[str],
    ) -> dict[str, Any]:
        payload = row.get("payload_json") if isinstance(row.get("payload_json"), dict) else {}
        handoff = await get_operator_handoff_service().create_or_refresh_handoff(
            session,
            tenant_id,
            workflow_type="escalation",
            workflow_ref=str(row.get("ticket_id") or ""),
            handoff_type="accounting_claims",
            property_code=row.get("property_code"),
            priority="high",
            subject=f"Accounting/claims handoff for {row.get('property_code') or 'property'}",
            body=(
                f"Escalation {row.get('ticket_id')} may require billing, reimbursement, insurance, or claims follow-up."
            ),
            payload={
                "ticket_id": row.get("ticket_id"),
                "session_token": row.get("session_token"),
                "summary": row.get("summary"),
                "reason": row.get("reason"),
                "routing_snapshot": payload.get("routing_snapshot") or {},
                "workflow_domain": payload.get("workflow_domain"),
                "signals": payload.get("signals") or {},
            },
        )
        await self._create_notification(
            session,
            tenant_id,
            kind="accounting_claim_handoff",
            severity="warning",
            title=f"Accounting/claims review needed for {row.get('property_code') or 'property'}",
            body=(
                f"Escalation {row.get('ticket_id')} may require billing, reimbursement, insurance, or claims follow-up. "
                f"Reason: {row.get('reason') or 'unknown'}. Summary: {row.get('summary') or 'No summary'}."
            ),
            link_target="escalations",
            link_label="Review escalation",
        )
        return {
            "status": "completed",
            "message": "Accounting/claims handoff created",
            "actor": actor_label or "operator",
            "routing_snapshot": payload.get("routing_snapshot") or {},
            "handoff_id": handoff.get("handoff_id"),
        }

    async def _create_notification(
        self,
        session: AsyncSession,
        tenant_id: str,
        *,
        kind: str,
        severity: str,
        title: str,
        body: str,
        link_target: str,
        link_label: str,
    ) -> None:
        if not await self._table_exists(session, "operator_notifications"):
            return
        await session.execute(
            text(
                """
                INSERT INTO operator_notifications
                    (tenant_id, kind, severity, title, body, link_target, link_label)
                VALUES
                    (CAST(:tid AS uuid), :kind, :severity, :title, :body, :link_target, :link_label)
                """
            ),
            {
                "tid": tenant_id,
                "kind": kind,
                "severity": severity,
                "title": title,
                "body": body,
                "link_target": link_target,
                "link_label": link_label,
            },
        )

    async def _set_action_status(
        self,
        session: AsyncSession,
        tenant_id: str,
        ticket_id: str,
        action_type: str,
        status: str,
        result: dict[str, Any],
    ) -> None:
        await session.execute(
            text(
                """
                UPDATE operator_workflow_action_queue
                SET status = :status,
                    result_json = CAST(:result_json AS jsonb),
                    updated_at = NOW(),
                    completed_at = CASE WHEN :status = 'completed' THEN NOW() ELSE completed_at END
                WHERE tenant_id = CAST(:tid AS uuid)
                  AND workflow_type = 'escalation'
                  AND workflow_ref = :workflow_ref
                  AND action_type = :action_type
                """
            ),
            {
                "tid": tenant_id,
                "workflow_ref": ticket_id,
                "action_type": action_type,
                "status": status,
                "result_json": json.dumps(result),
            },
        )

    def _desired_status(self, current: dict[str, Any]) -> str:
        current_status = str(current.get("status") or "").lower()
        if current_status in {"in_progress", "completed"}:
            return current_status
        return "ready"

    def _action_priority(self, row: dict[str, Any], category: str) -> str:
        priority = str(row.get("priority") or "medium").lower()
        if category in {"guest", "vendor"} and priority in {"high", "urgent"}:
            return "high"
        if category == "accounting" and priority == "urgent":
            return "high"
        return priority if priority in {"low", "medium", "high", "urgent"} else "medium"

    def _default_due_at(self, row: dict[str, Any], *, minutes: int) -> str:
        base = datetime.now(timezone.utc)
        priority = str(row.get("priority") or "").lower()
        if priority == "urgent":
            minutes = min(minutes, 5)
        elif priority == "high":
            minutes = min(minutes, 15)
        return (base + timedelta(minutes=minutes)).isoformat()

    async def _recommended_dispatch_vendors(
        self,
        session: AsyncSession,
        tenant_id: str,
        row: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if not await self._table_exists(session, "vendors"):
            return []
        try:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT vendor_id, category_slug, name, phone, website, internal_notes,
                               priority, apply_scope, property_ids, active, operational_metadata
                        FROM vendors
                        WHERE tenant_id = CAST(:tid AS uuid)
                          AND active = TRUE
                        ORDER BY priority ASC, created_at ASC
                        """
                    ),
                    {"tid": tenant_id},
                )
            ).mappings().all()
        except Exception:
            return []

        text_blob = " ".join(str(row.get(key) or "") for key in ("reason", "summary", "last_message")).lower()
        property_code = str(row.get("property_code") or "").strip()
        vendor_intelligence = get_vendor_intelligence_service()
        issue_tags = vendor_intelligence.infer_issue_tags(text_blob)
        emergency = any(tag in issue_tags for tag in {"emergency", "safety"})
        property_profile = await self._load_property_vendor_context(session, tenant_id, property_code)
        in_scope_rows: list[dict[str, Any]] = []
        for vendor in rows:
            item = dict(vendor)
            scope = str(item.get("apply_scope") or "all").strip().lower()
            property_ids = self._json_list(item.get("property_ids"))
            if scope != "all" and property_code and property_code not in property_ids:
                continue
            in_scope_rows.append(item)
        recommended = vendor_intelligence.recommend_vendors(
            in_scope_rows,
            text_blob=text_blob,
            issue_tags=issue_tags,
            property_code=property_code,
            property_profile=property_profile,
            emergency=emergency,
            warranty_sensitive=bool(re.search(r"warranty|covered|manufacturer", text_blob)),
            limit=5,
        )
        return [
            {
                "vendor_id": str(item.get("vendor_id")),
                "name": item.get("name"),
                "phone": item.get("phone"),
                "website": item.get("website"),
                "category_slug": item.get("category_slug"),
                "priority": item.get("priority"),
                "score": item.get("score"),
                "decision": item.get("decision") or {},
                "operational_metadata": vendor_intelligence.normalize_metadata(item.get("operational_metadata")),
            }
            for item in recommended
        ]

    async def _load_property_vendor_context(
        self,
        session: AsyncSession,
        tenant_id: str,
        property_code: str,
    ) -> dict[str, Any]:
        if not property_code or not await self._table_exists(session, "properties"):
            return {}
        try:
            row = (
                await session.execute(
                    text(
                        """
                        SELECT id, property_code, thermostat_type, hvac_instructions, emergency_contact,
                               general_notes, known_issues, warranty_items
                        FROM properties
                        WHERE tenant_id = CAST(:tid AS uuid)
                          AND property_code = :property_code
                        LIMIT 1
                        """
                    ),
                    {"tid": tenant_id, "property_code": property_code},
                )
            ).mappings().first()
        except Exception:
            await self._rollback_quietly(session)
            return {}
        return get_vendor_intelligence_service().normalize_property_profile(dict(row) if row else {})

    async def _routing_snapshot(
        self,
        session: AsyncSession,
        tenant_id: str,
        row: dict[str, Any],
    ) -> dict[str, Any]:
        if not await self._table_exists(session, "operator_alert_contacts"):
            return {}
        try:
            alert_type = self._alert_type_for_escalation(
                row.get("reason"),
                row.get("summary"),
                row.get("last_message"),
            )
            router = get_alert_router(db=session)
            available, skipped = await router.get_recipients(
                company_id=tenant_id,
                alert_type=alert_type,
                property_code=row.get("property_code"),
            )
            return {
                "alert_type": alert_type.value,
                "timeout_minutes": int(ESCALATION_TIMEOUTS.get(alert_type, 30)),
                "available_contacts": [
                    {
                        "id": contact.id,
                        "contact_name": contact.contact_name,
                        "contact_phone": contact.contact_phone,
                        "contact_email": contact.contact_email,
                        "property_code": contact.property_code,
                        "escalation_order": int(contact.escalation_order or 1),
                        "availability_reason": contact.availability_reason(),
                    }
                    for contact in available
                ],
                "skipped_contacts": [
                    {
                        "id": contact.id,
                        "contact_name": contact.contact_name,
                        "contact_phone": contact.contact_phone,
                        "contact_email": contact.contact_email,
                        "property_code": contact.property_code,
                        "escalation_order": int(contact.escalation_order or 1),
                        "availability_reason": contact.availability_reason(),
                    }
                    for contact in skipped
                ],
            }
        except Exception as exc:
            logger.warning("[EscalationActionAgent] routing snapshot failed: %s", exc)
            return {}

    def _json_list(self, value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(v) for v in value]
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, list):
                    return [str(v) for v in parsed]
            except Exception:
                return []
        return []

    def _alert_type_for_escalation(
        self,
        reason: Optional[str],
        summary: Optional[str],
        last_message: Optional[str],
    ) -> AlertType:
        reason_value = str(reason or "").strip().lower()
        text_blob = " ".join([reason or "", summary or "", last_message or ""]).lower()
        if reason_value in {"maintenance", "property_issue"}:
            return AlertType.MAINTENANCE
        if reason_value == "safety" or any(token in text_blob for token in ("fire", "flood", "gas leak", "medical", "unsafe", "injured", "911", "locked out")):
            return AlertType.SAFETY
        if reason_value == "billing" or any(token in text_blob for token in ("refund", "charge", "billing", "payment", "money back", "claim", "insurance")):
            return AlertType.BILLING
        return AlertType.ESCALATION

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

    async def _rollback_quietly(self, session: AsyncSession) -> None:
        try:
            await session.rollback()
        except Exception:
            pass

    async def _load_safety_policy(self, session: AsyncSession, tenant_id: str) -> dict[str, Any]:
        defaults = {
            "require_human_ack_for_property_damage": True,
            "auto_hold_unit_on_life_safety": True,
            "auto_hold_unit_on_property_damage": True,
            "allow_non_life_safety_guest_reassurance": True,
        }
        if not await self._table_exists(session, "operator_settings"):
            return defaults
        try:
            row = (
                await session.execute(
                    text(
                        """
                        SELECT extra
                        FROM operator_settings
                        WHERE tenant_id = CAST(:tid AS uuid)
                        LIMIT 1
                        """
                    ),
                    {"tid": tenant_id},
                )
            ).mappings().first()
        except Exception:
            return defaults
        extra = row.get("extra") if row else {}
        if isinstance(extra, str):
            try:
                extra = json.loads(extra)
            except Exception:
                extra = {}
        merged = dict(defaults)
        if isinstance(extra, dict):
            merged.update(extra.get("safety_policy") or {})
        return merged


_SERVICE = EscalationActionAgent()


def get_escalation_action_agent() -> EscalationActionAgent:
    return _SERVICE
