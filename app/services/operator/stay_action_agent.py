from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.operator.handoff_service import get_operator_handoff_service
from app.services.operator.work_order_service import get_operator_work_order_service
from app.services.operator.vendor_intelligence_service import get_vendor_intelligence_service
from app.services.operator.stay_detector_service import get_stay_detector_service


logger = logging.getLogger(__name__)


class StayActionAgent:
    ACTION_PROACTIVE = "proactive_outreach"
    ACTION_GUEST_STATUS = "guest_status_response"
    ACTION_KNOWLEDGE = "knowledge_response"
    ACTION_OPS_REVIEW = "ops_review"
    ACTION_VENDOR = "vendor_coordination"
    ACTION_GUEST_ETA = "guest_eta_update"
    ACTION_TURNOVER = "turnover_coordination"
    ACTION_WALKTHROUGH = "post_checkout_walkthrough"
    ACTION_OWNER_INTERNAL = "owner_internal_update"
    ACTION_ACCOUNTING = "accounting_claim_handoff"

    async def sync_actions(
        self,
        session: AsyncSession,
        tenant_id: str,
        row: dict[str, Any],
        workflow: dict[str, Any],
    ) -> list[dict[str, Any]]:
        session_id = str(row.get("session_id") or "")
        if not session_id:
            return []
        if not await self._table_exists(session, "operator_workflow_action_queue"):
            return []
        if str(workflow.get("operational_state") or "").lower() == "archived":
            return []

        signals = get_stay_detector_service().detect(row, workflow)
        desired_actions = await self._desired_actions(session, tenant_id, row, workflow, signals)
        existing = await self._existing_actions(session, tenant_id, session_id)

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
                            (CAST(:tid AS uuid), 'stay', :workflow_ref, :action_type, :status, :priority,
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
                        "workflow_ref": session_id,
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
                          AND workflow_type = 'stay'
                          AND workflow_ref = :workflow_ref
                          AND action_type = :action_type
                        """
                    ),
                    {
                        "tid": tenant_id,
                        "workflow_ref": session_id,
                        "action_type": action_type,
                        "result_json": json.dumps(current_result),
                    },
                )

            action_map = await self.list_actions(session, tenant_id, [session_id])
            return action_map.get(session_id, [])
        except Exception as exc:
            logger.warning("[StayActionAgent] sync_actions failed: %s", exc)
            try:
                await session.rollback()
            except Exception:
                pass
            return []

    async def list_actions(
        self,
        session: AsyncSession,
        tenant_id: str,
        session_ids: list[str],
    ) -> dict[str, list[dict[str, Any]]]:
        if not session_ids or not await self._table_exists(session, "operator_workflow_action_queue"):
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
                          AND workflow_type = 'stay'
                          AND workflow_ref = ANY(CAST(:session_ids AS text[]))
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
                    {"tid": tenant_id, "session_ids": session_ids},
                )
            ).mappings().all()
        except Exception as exc:
            logger.warning("[StayActionAgent] list_actions failed: %s", exc)
            try:
                await session.rollback()
            except Exception:
                pass
            return {}

        result: dict[str, list[dict[str, Any]]] = {session_id: [] for session_id in session_ids}
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
        session_id: str,
        action_type: str,
        *,
        actor_label: Optional[str] = None,
    ) -> dict[str, Any]:
        if not await self._table_exists(session, "operator_workflow_action_queue"):
            raise RuntimeError("Workflow action queue is not available")

        row = await self._load_action_context(session, tenant_id, session_id, action_type)
        if not row:
            raise RuntimeError("Workflow action not found")

        current_status = str(row.get("status") or "").lower()
        if current_status == "completed":
            return {"ok": True, "status": "completed", "already_completed": True}

        await self._set_action_status(session, tenant_id, session_id, action_type, "in_progress", {"started_by": actor_label or "operator"})

        if action_type == self.ACTION_KNOWLEDGE:
            result = await self._execute_knowledge_response(session, tenant_id, row, actor_label)
        elif action_type == self.ACTION_PROACTIVE:
            result = await self._execute_proactive_outreach(session, tenant_id, row, actor_label)
        elif action_type == self.ACTION_GUEST_STATUS:
            result = await self._execute_guest_status_response(session, tenant_id, row, actor_label)
        elif action_type == self.ACTION_OPS_REVIEW:
            result = await self._execute_ops_review(session, tenant_id, row, actor_label)
        elif action_type == self.ACTION_VENDOR:
            result = await self._execute_vendor_coordination(session, tenant_id, row, actor_label)
        elif action_type == self.ACTION_GUEST_ETA:
            result = await self._execute_guest_eta_update(session, tenant_id, row, actor_label)
        elif action_type == self.ACTION_TURNOVER:
            result = await self._execute_turnover_coordination(session, tenant_id, row, actor_label)
        elif action_type == self.ACTION_WALKTHROUGH:
            result = await self._execute_walkthrough_review(session, tenant_id, row, actor_label)
        elif action_type == self.ACTION_OWNER_INTERNAL:
            result = await self._execute_owner_internal_update(session, tenant_id, row, actor_label)
        elif action_type == self.ACTION_ACCOUNTING:
            result = await self._execute_accounting_handoff(session, tenant_id, row, actor_label)
        else:
            raise RuntimeError(f"Unsupported workflow action: {action_type}")

        final_status = result.get("status") or "completed"
        await self._set_action_status(session, tenant_id, session_id, action_type, final_status, result)
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
        proactive = workflow.get("proactive") if isinstance(workflow.get("proactive"), dict) else {}

        if signals.get("reactive_status_response_needed"):
            status_message = self._compose_reactive_status_message(row, workflow, signals)
            if status_message:
                actions.append(
                    {
                        "action_type": self.ACTION_GUEST_STATUS,
                        "priority": "high" if signals.get("urgent_tone") else self._action_priority(row, "guest"),
                        "property_code": property_code,
                        "due_at": self._default_due_at(row, minutes=5),
                        "payload": {
                            "message_text": status_message,
                            "response_type": signals.get("reactive_response_type") or "service_acknowledgement",
                            "workflow_domain": signals.get("workflow_domain"),
                            "signals": signals,
                        },
                    }
                )

        if proactive.get("eligible") and proactive.get("touch_type") and proactive.get("message"):
            from app.services.messaging_brain.proactive_trigger_adapter import (
                build_stay_workflow_intent,
                compose_proactive_draft,
            )

            message_text = str(proactive.get("message") or "").strip()
            try:
                intent = await build_stay_workflow_intent(
                    tenant_id=tenant_id,
                    row=row,
                    workflow=workflow,
                    touch_type=str(proactive.get("touch_type") or ""),
                )
                draft = await compose_proactive_draft(intent, db_session=session)
                if str(draft.response_text or "").strip():
                    message_text = str(draft.response_text).strip()
            except Exception as exc:
                logger.warning("[StayActionAgent] proactive brain draft failed; using eligibility helper text: %s", exc)

            actions.append(
                {
                    "action_type": self.ACTION_PROACTIVE,
                    "priority": self._action_priority(row, "proactive"),
                    "property_code": property_code,
                    "due_at": self._default_due_at(row, minutes=10),
                    "payload": {
                        "touch_type": proactive.get("touch_type"),
                        "message_text": message_text,
                        "receptiveness_score": proactive.get("receptiveness_score"),
                        "cadence_bucket": proactive.get("cadence_bucket"),
                        "workflow_domain": signals.get("workflow_domain"),
                        "signals": signals,
                    },
                }
            )

        if signals.get("knowledge_response_candidate"):
            actions.append(
                {
                    "action_type": self.ACTION_KNOWLEDGE,
                    "priority": self._action_priority(row, "knowledge"),
                    "property_code": property_code,
                    "due_at": self._default_due_at(row, minutes=5),
                    "payload": {
                        "guest_name": row.get("guest_name"),
                        "property_name": row.get("property_name"),
                        "latest_message": row.get("latest_message_content"),
                        "latest_intent": row.get("latest_message_intent"),
                        "workflow_domain": signals.get("workflow_domain"),
                        "signals": signals,
                    },
                }
            )

        if signals.get("ops_review_needed"):
            actions.append(
                {
                    "action_type": self.ACTION_OPS_REVIEW,
                    "priority": self._action_priority(row, "ops"),
                    "property_code": property_code,
                    "due_at": self._default_due_at(row, minutes=10),
                    "payload": {
                        "guest_name": row.get("guest_name"),
                        "phase": row.get("phase"),
                        "open_escalations": int(row.get("open_escalations") or 0),
                        "workflow_domain": signals.get("workflow_domain"),
                        "signals": signals,
                    },
                }
            )

        operations = workflow.get("operations") if isinstance(workflow.get("operations"), dict) else {}
        modules = operations.get("modules") if isinstance(operations.get("modules"), dict) else {}
        tasks = operations.get("tasks") if isinstance(operations.get("tasks"), list) else []
        maintenance_enabled = bool(modules.get("maintenance_workflows", True))
        turnover_enabled = bool(modules.get("turnover_workflows", True))

        if signals.get("vendor_dispatch_needed") and (
            (signals.get("maintenance_issue") and maintenance_enabled)
            or (signals.get("turnover_coordination_needed") and turnover_enabled)
            or (not signals.get("maintenance_issue") and not signals.get("turnover_coordination_needed"))
        ):
            actions.append(
                {
                    "action_type": self.ACTION_VENDOR,
                    "priority": self._action_priority(row, "vendor"),
                    "property_code": property_code,
                    "due_at": self._default_due_at(row, minutes=15),
                    "payload": {
                        "session_token": row.get("token"),
                        "guest_name": row.get("guest_name"),
                        "summary": workflow.get("latest_message_summary"),
                        "recommended_vendors": recommended_vendors,
                        "workflow_domain": signals.get("workflow_domain"),
                        "signals": signals,
                    },
                }
            )

        if signals.get("turnover_coordination_needed") and turnover_enabled:
            actions.append(
                {
                    "action_type": self.ACTION_TURNOVER,
                    "priority": self._action_priority(row, "turnover"),
                    "property_code": property_code,
                    "due_at": self._default_due_at(row, minutes=20),
                    "payload": {
                        "session_token": row.get("token"),
                        "guest_name": row.get("guest_name"),
                        "phase": row.get("phase"),
                        "recommended_vendors": recommended_vendors,
                        "workflow_domain": signals.get("workflow_domain"),
                        "signals": signals,
                    },
                }
            )

        if any(
            str(task.get("key") or "") == "post_checkout_walkthrough"
            and str(task.get("status") or "") in {"pending", "in_progress"}
            for task in tasks
        ):
            actions.append(
                {
                    "action_type": self.ACTION_WALKTHROUGH,
                    "priority": self._action_priority(row, "ops"),
                    "property_code": property_code,
                    "due_at": self._default_due_at(row, minutes=30),
                    "payload": {
                        "session_token": row.get("token"),
                        "guest_name": row.get("guest_name"),
                        "phase": row.get("phase"),
                        "workflow_domain": "walkthrough",
                        "signals": signals,
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
                        "vendor_name": workflow.get("vendor_name"),
                        "eta_minutes": workflow.get("vendor_eta_minutes"),
                        "workflow_domain": signals.get("workflow_domain"),
                        "signals": signals,
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
                        "session_token": row.get("token"),
                        "guest_name": row.get("guest_name"),
                        "phase": row.get("phase"),
                        "workflow_domain": signals.get("workflow_domain"),
                        "signals": signals,
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
                        "session_token": row.get("token"),
                        "guest_name": row.get("guest_name"),
                        "phase": row.get("phase"),
                        "workflow_domain": signals.get("workflow_domain"),
                        "signals": signals,
                    },
                }
            )

        return actions

    async def _load_action_context(
        self,
        session: AsyncSession,
        tenant_id: str,
        session_id: str,
        action_type: str,
    ) -> Optional[dict[str, Any]]:
        try:
            row = (
                await session.execute(
                    text(
                        """
                        SELECT a.action_type, a.status, a.payload_json, a.result_json,
                               s.session_id, s.token, s.property_id, s.property_code, s.property_name,
                               s.guest_name, s.guest_phone, s.guest_email, s.phase, s.status,
                               s.check_in, s.check_out, s.property_context
                        FROM operator_workflow_action_queue a
                        LEFT JOIN concierge_guest_sessions s
                          ON CAST(s.session_id AS text) = a.workflow_ref
                        WHERE a.tenant_id = CAST(:tid AS uuid)
                          AND a.workflow_type = 'stay'
                          AND a.workflow_ref = :session_id
                          AND a.action_type = :action_type
                        LIMIT 1
                        """
                    ),
                    {"tid": tenant_id, "session_id": session_id, "action_type": action_type},
                )
            ).mappings().first()
            if not row:
                return None
            data = dict(row)
            for key in ("payload_json", "result_json"):
                value = data.get(key)
                if isinstance(value, str):
                    try:
                        data[key] = json.loads(value)
                    except Exception:
                        data[key] = {}
            return data
        except Exception as exc:
            logger.warning("[StayActionAgent] load_action_context failed: %s", exc)
            try:
                await session.rollback()
            except Exception:
                pass
            return None

    async def _existing_actions(
        self,
        session: AsyncSession,
        tenant_id: str,
        session_id: str,
    ) -> dict[str, dict[str, Any]]:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT action_type, status, payload_json, result_json
                    FROM operator_workflow_action_queue
                    WHERE tenant_id = CAST(:tid AS uuid)
                      AND workflow_type = 'stay'
                      AND workflow_ref = :workflow_ref
                    """
                ),
                {"tid": tenant_id, "workflow_ref": session_id},
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

    async def _execute_knowledge_response(
        self,
        session: AsyncSession,
        tenant_id: str,
        row: dict[str, Any],
        actor_label: Optional[str],
    ) -> dict[str, Any]:
        payload = row.get("payload_json") if isinstance(row.get("payload_json"), dict) else {}
        await self._create_notification(
            session,
            tenant_id,
            kind="stay_knowledge_response",
            severity="info",
            title=f"AI knowledge response ready for {row.get('property_code') or 'property'}",
            body=(
                f"Guest {payload.get('guest_name') or row.get('guest_name') or 'guest'} "
                f"asked a question that likely maps to knowledge-based handling. "
                f"Latest message: {payload.get('latest_message') or 'No message summary'}."
            ),
            link_target="sessions",
            link_label="Open guest session",
        )
        return {
            "status": "completed",
            "message": "Knowledge-response recommendation logged for operator review",
            "actor": actor_label or "operator",
        }

    async def _execute_guest_status_response(
        self,
        session: AsyncSession,
        tenant_id: str,
        row: dict[str, Any],
        actor_label: Optional[str],
    ) -> dict[str, Any]:
        payload = row.get("payload_json") if isinstance(row.get("payload_json"), dict) else {}
        guest_phone = row.get("guest_phone")
        message_text = str(payload.get("message_text") or "").strip()
        response_type = str(payload.get("response_type") or "service_acknowledgement").strip().lower()
        if not guest_phone or not message_text:
            return {
                "status": "blocked",
                "message": "Reactive guest status response is missing a guest phone or message text",
                "actor": actor_label or "operator",
            }

        from app.services.messaging.channel_router import get_channel_router, ChannelMessage
        from app.services.operator.concierge_bridge import get_db_session_service

        delivery = await get_channel_router().send(
            to=str(guest_phone),
            message=ChannelMessage(body=message_text),
            session_id=row.get("session_id"),
        )
        if not delivery.success:
            return {
                "status": "failed",
                "message": delivery.error or "Reactive guest status delivery failed",
                "actor": actor_label or "operator",
            }

        svc = get_db_session_service(UUID(str(tenant_id)))
        await svc.add_message(
            db=session,
            session_id=row["session_id"],
            direction="outbound",
            content=message_text,
            content_type="text",
            detected_intent=f"reactive_{response_type}",
        )
        return {
            "status": "completed",
            "message": "Reactive guest status response sent",
            "actor": actor_label or "operator",
            "response_type": response_type,
            "channel": str(delivery.channel.value if hasattr(delivery.channel, "value") else delivery.channel),
            "message_sid": delivery.message_sid,
        }

    async def _execute_proactive_outreach(
        self,
        session: AsyncSession,
        tenant_id: str,
        row: dict[str, Any],
        actor_label: Optional[str],
    ) -> dict[str, Any]:
        payload = row.get("payload_json") if isinstance(row.get("payload_json"), dict) else {}
        guest_phone = row.get("guest_phone")
        message_text = str(payload.get("message_text") or "").strip()
        touch_type = str(payload.get("touch_type") or "proactive_outreach").strip().lower()
        if not guest_phone or not message_text:
            return {
                "status": "blocked",
                "message": "Proactive outreach is missing a guest phone or message text",
                "actor": actor_label or "operator",
            }

        from app.services.messaging.channel_router import get_channel_router, ChannelMessage
        from app.services.operator.concierge_bridge import get_db_session_service

        delivery = await get_channel_router().send(
            to=str(guest_phone),
            message=ChannelMessage(body=message_text),
            session_id=row.get("session_id"),
        )
        if not delivery.success:
            return {
                "status": "failed",
                "message": delivery.error or "Proactive outreach delivery failed",
                "actor": actor_label or "operator",
            }

        svc = get_db_session_service(UUID(str(tenant_id)))
        await svc.add_message(
            db=session,
            session_id=row["session_id"],
            direction="outbound",
            content=message_text,
            content_type="text",
            detected_intent=f"proactive_{touch_type}",
        )
        await self._mark_proactive_touch(session, row["session_id"], touch_type)
        return {
            "status": "completed",
            "message": "Proactive outreach sent",
            "actor": actor_label or "operator",
            "touch_type": touch_type,
            "channel": str(delivery.channel.value if hasattr(delivery.channel, "value") else delivery.channel),
            "message_sid": delivery.message_sid,
        }

    async def _execute_ops_review(
        self,
        session: AsyncSession,
        tenant_id: str,
        row: dict[str, Any],
        actor_label: Optional[str],
    ) -> dict[str, Any]:
        await self._create_notification(
            session,
            tenant_id,
            kind="stay_ops_review",
            severity="warning",
            title=f"Ops review needed for {row.get('property_code') or 'property'}",
            body=(
                f"Guest session {row.get('token') or row.get('session_id')} needs operator review. "
                f"Phase: {row.get('phase') or 'unknown'}."
            ),
            link_target="sessions",
            link_label="Review session",
        )
        return {
            "status": "completed",
            "message": "Ops review notification created",
            "actor": actor_label or "operator",
        }

    async def _execute_vendor_coordination(
        self,
        session: AsyncSession,
        tenant_id: str,
        row: dict[str, Any],
        actor_label: Optional[str],
    ) -> dict[str, Any]:
        payload = row.get("payload_json") if isinstance(row.get("payload_json"), dict) else {}
        recommended_vendors = payload.get("recommended_vendors") or []
        selected_vendor = recommended_vendors[0] if recommended_vendors else {}

        await self._upsert_stay_workflow_vendor_state(
            session,
            tenant_id,
            str(row.get("session_id") or ""),
            {
                "selected_vendor_id": selected_vendor.get("vendor_id"),
                "name": selected_vendor.get("name"),
                "phone": selected_vendor.get("phone"),
                "category_slug": selected_vendor.get("category_slug"),
                "dispatch_state": "recommended" if selected_vendor else "coordination_required",
                "eta_minutes": None,
                "selected_at": datetime.now(timezone.utc).isoformat() if selected_vendor else None,
                "last_updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        await self._create_notification(
            session,
            tenant_id,
            kind="stay_vendor_coordination",
            severity="warning",
            title=f"Vendor coordination needed for {row.get('property_code') or 'property'}",
            body=(
                f"Guest session {row.get('token') or row.get('session_id')} needs vendor coordination. "
                f"Latest issue: {payload.get('summary') or 'No summary provided'}."
            ),
            link_target="sessions",
            link_label="Open session",
        )
        await get_operator_work_order_service().create_or_refresh_work_order(
            session,
            tenant_id,
            workflow_type="stay",
            workflow_ref=str(row.get("session_id") or ""),
            property_code=row.get("property_code"),
            vendor_id=selected_vendor.get("vendor_id") if selected_vendor else None,
            vendor_name=selected_vendor.get("name") if selected_vendor else None,
            vendor_phone=selected_vendor.get("phone") if selected_vendor else None,
            issue_category=str(payload.get("issue_category") or row.get("latest_message_intent") or "maintenance"),
            priority=str(row.get("priority") or "medium"),
            summary=str(payload.get("summary") or row.get("latest_message_content") or "Vendor coordination needed"),
            details=str(row.get("latest_message_content") or ""),
            dispatch_state="recommended" if selected_vendor else "opened",
            eta_minutes=selected_vendor.get("eta_minutes") if selected_vendor else None,
            eta_visibility_mode="estimated",
            last_actor_label=actor_label or "operator",
            payload={
                "recommended_vendors": recommended_vendors,
                "selected_vendor": selected_vendor or None,
                "token": row.get("token"),
            },
        )
        return {
            "status": "in_progress",
            "message": "Vendor coordination task opened for stay workflow",
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
        payload = row.get("payload_json") if isinstance(row.get("payload_json"), dict) else {}
        guest_phone = row.get("guest_phone") or payload.get("guest_phone")
        vendor_name = payload.get("vendor_name")
        eta_minutes = payload.get("eta_minutes")
        if not guest_phone or not vendor_name or eta_minutes is None:
            return {
                "status": "blocked",
                "message": "Guest ETA update is missing guest phone, vendor name, or ETA",
                "actor": actor_label or "operator",
            }

        from app.services.messaging.channel_router import get_channel_router, ChannelMessage
        from app.services.operator.concierge_bridge import get_db_session_service

        body = (
            f"{vendor_name} is on the way to {row.get('property_name') or 'the property'} "
            f"and the current ETA is about {int(eta_minutes)} minutes."
        )
        delivery = await get_channel_router().send(
            to=str(guest_phone),
            message=ChannelMessage(body=body),
            session_id=row.get("session_id"),
        )
        if not delivery.success:
            return {
                "status": "failed",
                "message": delivery.error or "Guest ETA delivery failed",
                "actor": actor_label or "operator",
            }

        svc = get_db_session_service(UUID(str(tenant_id)))
        await svc.add_message(
            db=session,
            session_id=row["session_id"],
            direction="outbound",
            content=body,
            content_type="text",
            detected_intent="guest_eta_update",
        )
        await self._upsert_stay_workflow_vendor_state(
            session,
            tenant_id,
            str(row.get("session_id") or ""),
            {
                "name": vendor_name,
                "dispatch_state": "en_route",
                "eta_minutes": int(eta_minutes),
                "last_updated_at": datetime.now(timezone.utc).isoformat(),
            },
            guest_update_patch={
                "status": "sent_to_guest",
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "note": body,
            },
        )
        return {
            "status": "completed",
            "message": "Guest ETA update sent",
            "actor": actor_label or "operator",
            "channel": str(delivery.channel.value if hasattr(delivery.channel, "value") else delivery.channel),
            "message_sid": delivery.message_sid,
        }

    async def _execute_turnover_coordination(
        self,
        session: AsyncSession,
        tenant_id: str,
        row: dict[str, Any],
        actor_label: Optional[str],
    ) -> dict[str, Any]:
        payload = row.get("payload_json") if isinstance(row.get("payload_json"), dict) else {}
        recommended_vendors = payload.get("recommended_vendors") or []
        selected_vendor = recommended_vendors[0] if recommended_vendors else {}
        await self._create_notification(
            session,
            tenant_id,
            kind="stay_turnover_coordination",
            severity="warning",
            title=f"Turnover coordination needed for {row.get('property_code') or 'property'}",
            body=(
                f"Stay workflow for {row.get('property_code') or 'property'} needs turnover or cleaning coordination. "
                f"Phase: {payload.get('phase') or row.get('phase') or 'unknown'}."
            ),
            link_target="sessions",
            link_label="Review stay workflow",
        )
        await self._upsert_stay_workflow_turnover_state(
            session,
            tenant_id,
            str(row.get("session_id") or ""),
            {
                "status": "in_progress",
                "started_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "updated_by": actor_label or "operator",
                "assigned_vendor_id": selected_vendor.get("vendor_id"),
                "assigned_vendor_name": selected_vendor.get("vendor_name"),
                "note": "Turnover coordination started",
            },
        )
        return {
            "status": "in_progress",
            "message": "Turnover coordination task opened",
            "actor": actor_label or "operator",
            "recommended_vendors": recommended_vendors,
        }

    async def _execute_walkthrough_review(
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
            workflow_type="stay",
            workflow_ref=str(row.get("session_id") or ""),
            handoff_type="walkthrough_review",
            property_code=row.get("property_code"),
            priority="medium",
            subject=f"Post-checkout documentation for {row.get('property_code') or 'property'}",
            body=f"Post-checkout documentation or walkthrough requested for stay {row.get('token') or row.get('session_id')}.",
            payload={
                "session_token": row.get("token"),
                "guest_name": row.get("guest_name"),
                "phase": row.get("phase"),
                "workflow_domain": payload.get("workflow_domain"),
                "signals": payload.get("signals") or {},
            },
        )
        await self._upsert_stay_workflow_walkthrough_state(
            session,
            tenant_id,
            str(row.get("session_id") or ""),
            {
                "status": "in_progress",
                "required": True,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "updated_by": actor_label or "operator",
                "note": "Post-checkout documentation opened",
            },
        )
        return {
            "status": "in_progress",
            "message": "Post-checkout documentation opened",
            "actor": actor_label or "operator",
            "handoff_id": handoff.get("handoff_id"),
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
            workflow_type="stay",
            workflow_ref=str(row.get("session_id") or ""),
            handoff_type="owner_internal",
            property_code=row.get("property_code"),
            priority="high" if str(payload.get("workflow_domain") or "") in {"maintenance", "turnover"} else "medium",
            subject=f"Owner/internal update for {row.get('property_code') or 'property'}",
            body=f"Stay session {row.get('token') or row.get('session_id')} needs owner/internal visibility.",
            payload={
                "session_token": row.get("token"),
                "guest_name": row.get("guest_name"),
                "phase": row.get("phase"),
                "workflow_domain": payload.get("workflow_domain"),
                "signals": payload.get("signals") or {},
            },
        )
        await self._create_notification(
            session,
            tenant_id,
            kind="stay_owner_internal_update",
            severity="warning",
            title=f"Internal update needed for {row.get('property_code') or 'property'}",
            body=(
                f"Guest session {row.get('token') or row.get('session_id')} needs owner/internal visibility."
            ),
            link_target="sessions",
            link_label="Open session",
        )
        return {
            "status": "completed",
            "message": "Owner/internal update created",
            "actor": actor_label or "operator",
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
            workflow_type="stay",
            workflow_ref=str(row.get("session_id") or ""),
            handoff_type="accounting_claims",
            property_code=row.get("property_code"),
            priority="high",
            subject=f"Accounting/claims review for {row.get('property_code') or 'property'}",
            body=f"Guest session {row.get('token') or row.get('session_id')} may require billing or claims follow-up.",
            payload={
                "session_token": row.get("token"),
                "guest_name": row.get("guest_name"),
                "phase": row.get("phase"),
                "workflow_domain": payload.get("workflow_domain"),
                "signals": payload.get("signals") or {},
            },
        )
        await self._create_notification(
            session,
            tenant_id,
            kind="stay_accounting_claim_handoff",
            severity="warning",
            title=f"Accounting review needed for {row.get('property_code') or 'property'}",
            body=(
                f"Guest session {row.get('token') or row.get('session_id')} may require billing or claims follow-up."
            ),
            link_target="sessions",
            link_label="Open session",
        )
        return {
            "status": "completed",
            "message": "Accounting/claims handoff created",
            "actor": actor_label or "operator",
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
        session_id: str,
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
                  AND workflow_type = 'stay'
                  AND workflow_ref = :workflow_ref
                  AND action_type = :action_type
                """
            ),
            {
                "tid": tenant_id,
                "workflow_ref": session_id,
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
        phase = str(row.get("phase") or "").lower()
        if category == "proactive":
            return "medium" if phase in {"pre_arrival", "in_stay", "departure_day"} else "low"
        if category == "guest" and int(row.get("open_escalations") or 0) > 0:
            return "high"
        if category in {"vendor", "turnover"} and phase in {"arrival_day", "departure_day"}:
            return "high"
        if category == "ops" and int(row.get("open_escalations") or 0) > 0:
            return "high"
        return "medium"

    def _compose_reactive_status_message(
        self,
        row: dict[str, Any],
        workflow: dict[str, Any],
        signals: dict[str, Any],
    ) -> str | None:
        policy_root = workflow.get("policy") if isinstance(workflow.get("policy"), dict) else {}
        escalation_policy = policy_root.get("escalation_guest") if isinstance(policy_root, dict) else {}
        escalation_policy = escalation_policy if isinstance(escalation_policy, dict) else {}
        guest = str(row.get("guest_name") or "there").split()[0]
        property_name = row.get("property_name") or "the property"
        vendor_name = workflow.get("vendor_name")
        eta_minutes = workflow.get("vendor_eta_minutes")
        response_type = str(signals.get("reactive_response_type") or "").lower()
        allow_eta_updates = bool(escalation_policy.get("allow_eta_updates", True))
        allow_reassurance_without_eta = bool(escalation_policy.get("allow_reassurance_without_eta", True))

        if allow_eta_updates and vendor_name and eta_minutes is not None:
            return (
                f"Hi {guest} - thanks for checking in. {vendor_name} is currently on the way to {property_name}, "
                f"and the latest ETA is about {int(eta_minutes)} minutes. I’ll keep you updated if anything changes."
            )
        if allow_reassurance_without_eta and response_type == "status_followup":
            return (
                f"Hi {guest} - thanks for checking in. We’re actively working on the issue at {property_name} right now, "
                f"and I’ll share the next concrete update as soon as we have it."
            )
        if allow_reassurance_without_eta and int(row.get("open_escalations") or 0) > 0:
            return (
                f"Hi {guest} - we’re actively coordinating on the issue at {property_name}. "
                f"I’ll keep you posted with the next concrete update."
            )
        return None

    def _default_due_at(self, row: dict[str, Any], *, minutes: int) -> str:
        return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()

    async def _mark_proactive_touch(
        self,
        session: AsyncSession,
        session_id: Any,
        touch_type: str,
    ) -> None:
        if not await self._table_exists(session, "concierge_guest_journeys"):
            return
        assignments = ["updated_at = NOW()"]
        if touch_type in {"pre_arrival_welcome", "arrival_day_checkin"}:
            assignments.extend(["welcome_sent = TRUE", "welcome_sent_at = NOW()"])
        if touch_type == "arrival_info":
            assignments.extend(["checkin_reminder_sent = TRUE", "checkin_reminder_sent_at = NOW()"])
        if touch_type == "checkout_prep":
            assignments.extend(["checkout_reminder_sent = TRUE", "checkout_reminder_sent_at = NOW()"])
        if touch_type == "extend_offer":
            assignments.extend(["extend_offer_sent = TRUE", "extend_offer_sent_at = NOW()"])
        await session.execute(
            text(
                f"""
                UPDATE concierge_guest_journeys
                SET {', '.join(assignments)}
                WHERE session_id = CAST(:session_id AS uuid)
                """
            ),
            {"session_id": str(session_id)},
        )
        if await self._table_exists(session, "concierge_guest_sessions"):
            await session.execute(
                text(
                    """
                    UPDATE concierge_guest_sessions
                    SET proactive_triggered_at = NOW(),
                        updated_at = NOW()
                    WHERE session_id = CAST(:session_id AS uuid)
                    """
                ),
                {"session_id": str(session_id)},
            )

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
                        SELECT vendor_id, category_slug, name, phone, website, priority,
                               apply_scope, property_ids, active, operational_metadata
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

        text_blob = " ".join(str(row.get(key) or "") for key in ("latest_message_content", "latest_message_intent", "phase")).lower()
        property_id = str(row.get("property_id") or "").strip()
        property_code = str(row.get("property_code") or "").strip()
        vendor_intelligence = get_vendor_intelligence_service()
        issue_tags = vendor_intelligence.infer_issue_tags(text_blob)
        emergency = any(tag in issue_tags for tag in {"emergency", "safety"})
        property_profile = await self._load_property_vendor_context(session, tenant_id, property_id, property_code)
        in_scope_rows: list[dict[str, Any]] = []
        for vendor in rows:
            item = dict(vendor)
            scope = str(item.get("apply_scope") or "all").strip().lower()
            property_ids = self._json_list(item.get("property_ids"))
            if scope != "all" and property_id and property_id not in property_ids:
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
        property_id: str,
        property_code: str,
    ) -> dict[str, Any]:
        if not await self._table_exists(session, "properties"):
            return {}
        if not property_id and not property_code:
            return {}
        where_sql = "CAST(id AS text) = :property_id" if property_id else "property_code = :property_code"
        params = {"tid": tenant_id, "property_id": property_id, "property_code": property_code}
        try:
            row = (
                await session.execute(
                    text(
                        f"""
                        SELECT id, property_code, thermostat_type, hvac_instructions, emergency_contact,
                               general_notes, known_issues, warranty_items
                        FROM properties
                        WHERE tenant_id = CAST(:tid AS uuid)
                          AND {where_sql}
                        LIMIT 1
                        """
                    ),
                    params,
                )
            ).mappings().first()
        except Exception:
            await self._rollback_quietly(session)
            return {}
        return get_vendor_intelligence_service().normalize_property_profile(dict(row) if row else {})

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

    async def _upsert_stay_workflow_vendor_state(
        self,
        session: AsyncSession,
        tenant_id: str,
        session_id: str,
        vendor_patch: dict[str, Any],
        *,
        guest_update_patch: Optional[dict[str, Any]] = None,
        vendor_event: Optional[dict[str, Any]] = None,
    ) -> None:
        if not session_id or not await self._table_exists(session, "operator_stay_workflow_read_models"):
            return
        try:
            row = (
                await session.execute(
                    text(
                        """
                        SELECT workflow_json
                        FROM operator_stay_workflow_read_models
                        WHERE tenant_id = CAST(:tid AS uuid)
                          AND session_id = CAST(:sid AS uuid)
                        LIMIT 1
                        """
                    ),
                    {"tid": tenant_id, "sid": session_id},
                )
            ).mappings().first()
            workflow = row.get("workflow_json") if row else {}
            if isinstance(workflow, str):
                try:
                    workflow = json.loads(workflow)
                except Exception:
                    workflow = {}
            workflow = workflow if isinstance(workflow, dict) else {}
            vendor = workflow.get("vendor") if isinstance(workflow.get("vendor"), dict) else {}
            prior_dispatch_state = str(vendor.get("dispatch_state") or "").strip().lower() or None
            vendor.update({k: v for k, v in vendor_patch.items() if v is not None})
            next_dispatch_state = str(vendor.get("dispatch_state") or "").strip().lower() or None
            if next_dispatch_state != prior_dispatch_state:
                vendor["previous_dispatch_state"] = prior_dispatch_state
                vendor["status_changed_at"] = datetime.now(timezone.utc).isoformat()
            if vendor_event:
                vendor["status_changed_by"] = vendor_event.get("changed_by") or vendor.get("status_changed_by")
                vendor["last_transition_note"] = vendor_event.get("note") or vendor.get("last_transition_note")
                if vendor_event.get("replace_existing"):
                    vendor["replacement_count"] = int(vendor.get("replacement_count") or 0) + 1
            workflow["vendor"] = vendor
            workflow["vendor_name"] = vendor.get("name")
            workflow["vendor_eta_minutes"] = vendor.get("eta_minutes")
            if vendor_event:
                history = workflow.get("vendor_history") if isinstance(workflow.get("vendor_history"), list) else []
                history.append(vendor_event)
                workflow["vendor_history"] = history[-20:]
            if guest_update_patch:
                guest_update = workflow.get("guest_update") if isinstance(workflow.get("guest_update"), dict) else {}
                guest_update.update({k: v for k, v in guest_update_patch.items() if v is not None})
                workflow["guest_update"] = guest_update
                workflow["guest_update_state"] = guest_update.get("status") or workflow.get("guest_update_state")
            await session.execute(
                text(
                    """
                    UPDATE operator_stay_workflow_read_models
                    SET workflow_json = CAST(:workflow_json AS jsonb),
                        guest_update_state = :guest_update_state,
                        updated_at = NOW(),
                        refreshed_at = NOW()
                    WHERE tenant_id = CAST(:tid AS uuid)
                      AND session_id = CAST(:sid AS uuid)
                    """
                ),
                {
                    "tid": tenant_id,
                    "sid": session_id,
                    "workflow_json": json.dumps(workflow),
                    "guest_update_state": workflow.get("guest_update_state"),
                },
            )
        except Exception:
            await session.rollback()

    async def _upsert_stay_workflow_turnover_state(
        self,
        session: AsyncSession,
        tenant_id: str,
        session_id: str,
        turnover_patch: dict[str, Any],
    ) -> None:
        if not session_id or not await self._table_exists(session, "operator_stay_workflow_read_models"):
            return
        try:
            row = (
                await session.execute(
                    text(
                        """
                        SELECT workflow_json
                        FROM operator_stay_workflow_read_models
                        WHERE tenant_id = CAST(:tid AS uuid)
                          AND session_id = CAST(:sid AS uuid)
                        LIMIT 1
                        """
                    ),
                    {"tid": tenant_id, "sid": session_id},
                )
            ).mappings().first()
            workflow = row.get("workflow_json") if row else {}
            if isinstance(workflow, str):
                try:
                    workflow = json.loads(workflow)
                except Exception:
                    workflow = {}
            workflow = workflow if isinstance(workflow, dict) else {}
            turnover = workflow.get("turnover") if isinstance(workflow.get("turnover"), dict) else {}
            turnover.update({k: v for k, v in turnover_patch.items() if v is not None})
            workflow["turnover"] = turnover
            if turnover.get("status") in {"ready", "archived"}:
                archived_at = turnover.get("archived_at") or datetime.now(timezone.utc).isoformat()
                workflow["operational_state"] = "archived"
                workflow["archive_eligible"] = True
                workflow["stage"] = "archived"
                turnover["archived_at"] = archived_at
            await session.execute(
                text(
                    """
                    UPDATE operator_stay_workflow_read_models
                    SET workflow_json = CAST(:workflow_json AS jsonb),
                        workflow_stage = :workflow_stage,
                        updated_at = NOW(),
                        refreshed_at = NOW()
                    WHERE tenant_id = CAST(:tid AS uuid)
                      AND session_id = CAST(:sid AS uuid)
                    """
                ),
                {
                    "tid": tenant_id,
                    "sid": session_id,
                    "workflow_json": json.dumps(workflow),
                    "workflow_stage": workflow.get("stage") or "post_stay_followup",
                },
            )
        except Exception:
            await session.rollback()

    async def _upsert_stay_workflow_walkthrough_state(
        self,
        session: AsyncSession,
        tenant_id: str,
        session_id: str,
        walkthrough_patch: dict[str, Any],
    ) -> None:
        if not session_id or not await self._table_exists(session, "operator_stay_workflow_read_models"):
            return
        try:
            row = (
                await session.execute(
                    text(
                        """
                        SELECT workflow_json
                        FROM operator_stay_workflow_read_models
                        WHERE tenant_id = CAST(:tid AS uuid)
                          AND session_id = CAST(:sid AS uuid)
                        LIMIT 1
                        """
                    ),
                    {"tid": tenant_id, "sid": session_id},
                )
            ).mappings().first()
            workflow = row.get("workflow_json") if row else {}
            if isinstance(workflow, str):
                try:
                    workflow = json.loads(workflow)
                except Exception:
                    workflow = {}
            workflow = workflow if isinstance(workflow, dict) else {}
            walkthrough = workflow.get("walkthrough") if isinstance(workflow.get("walkthrough"), dict) else {}
            walkthrough.update({k: v for k, v in walkthrough_patch.items() if v is not None})
            workflow["walkthrough"] = walkthrough
            await session.execute(
                text(
                    """
                    UPDATE operator_stay_workflow_read_models
                    SET workflow_json = CAST(:workflow_json AS jsonb),
                        updated_at = NOW(),
                        refreshed_at = NOW()
                    WHERE tenant_id = CAST(:tid AS uuid)
                      AND session_id = CAST(:sid AS uuid)
                    """
                ),
                {
                    "tid": tenant_id,
                    "sid": session_id,
                    "workflow_json": json.dumps(workflow),
                },
            )
        except Exception:
            await session.rollback()

    async def update_dispatch_state(
        self,
        session: AsyncSession,
        tenant_id: str,
        session_id: str,
        *,
        vendor_patch: dict[str, Any],
        guest_update_patch: Optional[dict[str, Any]] = None,
        vendor_event: Optional[dict[str, Any]] = None,
    ) -> bool:
        await self._upsert_stay_workflow_vendor_state(
            session,
            tenant_id,
            session_id,
            vendor_patch,
            guest_update_patch=guest_update_patch,
            vendor_event=vendor_event,
        )
        workflow_map = {}
        try:
            from app.services.operator.stay_workflow_service import get_stay_workflow_service

            workflow_map = await get_stay_workflow_service().workflow_map(session, tenant_id, [session_id])
        except Exception:
            workflow_map = {}
        workflow = workflow_map.get(session_id) if isinstance(workflow_map, dict) else {}
        workflow = workflow if isinstance(workflow, dict) else {}
        vendor = workflow.get("vendor") if isinstance(workflow.get("vendor"), dict) else {}
        try:
            await get_operator_work_order_service().create_or_refresh_work_order(
                session,
                tenant_id,
                workflow_type="stay",
                workflow_ref=session_id,
                property_code=str(workflow.get("property_code") or ""),
                vendor_id=vendor_patch.get("selected_vendor_id") or vendor.get("selected_vendor_id"),
                vendor_name=vendor_patch.get("name") or vendor.get("name"),
                vendor_phone=vendor_patch.get("phone") or vendor.get("phone"),
                issue_category="maintenance",
                priority=str(workflow.get("priority") or "medium"),
                summary=str((workflow.get("guest_update") or {}).get("note") or workflow.get("stage") or "Stay work order"),
                details=str((vendor_event or {}).get("note") or ""),
                dispatch_state=str(vendor_patch.get("dispatch_state") or vendor.get("dispatch_state") or "opened"),
                eta_minutes=vendor_patch.get("eta_minutes") or vendor.get("eta_minutes"),
                eta_visibility_mode=(vendor_event or {}).get("eta_visibility_mode") or "estimated",
                tracking_url=(vendor_event or {}).get("tracking_url"),
                last_known_distance_text=(vendor_event or {}).get("last_known_distance_text"),
                asset_id=(vendor_event or {}).get("asset_id"),
                last_actor_label=(vendor_event or {}).get("changed_by"),
                payload={"vendor_event": vendor_event or {}, "guest_update_patch": guest_update_patch or {}},
            )
        except Exception:
            pass
        return True

    async def update_turnover_state(
        self,
        session: AsyncSession,
        tenant_id: str,
        session_id: str,
        *,
        turnover_patch: dict[str, Any],
    ) -> bool:
        await self._upsert_stay_workflow_turnover_state(
            session,
            tenant_id,
            session_id,
            turnover_patch,
        )
        return True

    async def update_walkthrough_state(
        self,
        session: AsyncSession,
        tenant_id: str,
        session_id: str,
        *,
        walkthrough_patch: dict[str, Any],
    ) -> bool:
        await self._upsert_stay_workflow_walkthrough_state(
            session,
            tenant_id,
            session_id,
            walkthrough_patch,
        )
        return True


_SERVICE = StayActionAgent()


def get_stay_action_agent() -> StayActionAgent:
    return _SERVICE
