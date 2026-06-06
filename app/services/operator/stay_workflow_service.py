from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.operator.stay_action_agent import get_stay_action_agent
from app.services.operator.stay_detector_service import get_stay_detector_service
from app.services.operator.handoff_service import get_operator_handoff_service
from app.services.operator.work_order_service import get_operator_work_order_service
from app.services.operator.stay_event_service import get_stay_event_service
from app.services.operator.stay_operations_service import get_stay_operations_service
from app.services.operator.stay_proactive_service import get_stay_proactive_service
from app.services.operator.stay_receptiveness_service import get_stay_receptiveness_service
from app.services.concierge.market_brain import build_market_brain_bundle


logger = logging.getLogger(__name__)


def _iso(value):
    if not value:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


class StayWorkflowService:
    async def sync_session(
        self,
        session: AsyncSession,
        tenant_id: str,
        session_id: str,
    ) -> bool:
        if not session_id:
            return False
        rows = await self._load_session_rows(session, tenant_id, [session_id])
        if not rows:
            return False
        if not await self._table_exists(session, "operator_stay_workflow_read_models"):
            return False
        try:
            row = rows[0]
            workflow = await self._workflow_for_row(session, tenant_id, row)
            await self._persist_workflow(session, tenant_id, row, workflow)
            return True
        except Exception as exc:
            logger.warning("[StayWorkflowService] sync_session failed: %s", exc)
            try:
                await session.rollback()
            except Exception:
                pass
            return False

    async def sync_sessions(
        self,
        session: AsyncSession,
        tenant_id: str,
        session_ids: list[str],
    ) -> None:
        if not session_ids or not await self._table_exists(session, "operator_stay_workflow_read_models"):
            return
        rows = await self._load_session_rows(session, tenant_id, session_ids)
        if not rows:
            return
        try:
            for row in rows:
                workflow = await self._workflow_for_row(session, tenant_id, row)
                await self._persist_workflow(session, tenant_id, row, workflow, commit=False)
            await session.commit()
        except Exception as exc:
            logger.warning("[StayWorkflowService] sync_sessions failed: %s", exc)
            try:
                await session.rollback()
            except Exception:
                pass

    async def workflow_map(
        self,
        session: AsyncSession,
        tenant_id: str,
        session_ids: list[str],
    ) -> dict[str, dict]:
        if not session_ids or not await self._table_exists(session, "operator_stay_workflow_read_models"):
            return {}
        try:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT CAST(session_id AS text) AS session_id, workflow_json
                        FROM operator_stay_workflow_read_models
                        WHERE tenant_id = CAST(:tid AS uuid)
                          AND session_id = ANY(CAST(:session_ids AS uuid[]))
                        """
                    ),
                    {"tid": tenant_id, "session_ids": session_ids},
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
                result[str(row["session_id"])] = workflow if isinstance(workflow, dict) else {}
            return result
        except Exception as exc:
            logger.warning("[StayWorkflowService] workflow_map failed: %s", exc)
            try:
                await session.rollback()
            except Exception:
                pass
            return {}

    async def _workflow_for_row(
        self,
        session: AsyncSession,
        tenant_id: str,
        row: dict[str, Any],
    ) -> dict[str, Any]:
        existing_workflow = await self._existing_workflow(session, tenant_id, str(row.get("session_id") or ""))
        workflow = self._build_workflow(row, existing_workflow)
        workflow["policy"] = await self._load_policy(session, tenant_id)
        workflow["intelligence_context"] = await self._build_intelligence_context(session, row)
        workflow["events"] = await get_stay_event_service().summarize_events(
            session,
            tenant_id,
            str(row.get("session_id") or ""),
        )
        self._apply_event_summary(workflow)
        workflow["operations"] = get_stay_operations_service().evaluate(row, workflow)
        workflow["receptiveness"] = get_stay_receptiveness_service().evaluate(row, workflow)
        workflow["proactive"] = get_stay_proactive_service().evaluate(row, workflow)
        workflow["detectors"] = get_stay_detector_service().detect(row, workflow)
        workflow["actions"] = await get_stay_action_agent().sync_actions(session, tenant_id, row, workflow)
        workflow["handoffs"] = await get_operator_handoff_service().summarize_handoffs(
            session,
            tenant_id,
            workflow_type="stay",
            workflow_ref=str(row.get("session_id") or ""),
        )
        try:
            workflow["work_orders"] = await get_operator_work_order_service().summarize_work_orders(
                session,
                tenant_id,
                workflow_type="stay",
                workflow_ref=str(row.get("session_id") or ""),
            )
        except Exception:
            workflow["work_orders"] = {"open_count": 0, "total_count": 0, "statuses": [], "items": []}
        self._apply_operational_rules(row, workflow)
        return workflow

    async def _build_intelligence_context(
        self,
        session: AsyncSession,
        row: dict[str, Any],
    ) -> dict[str, Any]:
        property_context = row.get("property_context") if isinstance(row.get("property_context"), dict) else {}
        has_inline_coords = bool(property_context.get("latitude") and property_context.get("longitude"))
        if getattr(session, "bind", None) is None and not has_inline_coords:
            return {"property_context": property_context}
        try:
            bundle = await build_market_brain_bundle(
                session,
                property_code=str(row.get("property_code") or "") or None,
                property_name=str(row.get("property_name") or "") or None,
                property_facts=property_context,
                session_data={
                    "check_in": _iso(row.get("check_in")),
                    "check_out": _iso(row.get("check_out")),
                },
            )
            return {
                "market_brain": bundle.to_dict(),
                "property_context": property_context,
            }
        except Exception as exc:
            logger.warning("[StayWorkflowService] intelligence context build failed: %s", exc)
            return {"property_context": property_context}

    async def _load_session_rows(
        self,
        session: AsyncSession,
        tenant_id: str,
        session_ids: list[str],
    ) -> list[dict[str, Any]]:
        if not session_ids:
            return []
        has_messages = await self._table_exists(session, "concierge_messages")
        has_journeys = await self._table_exists(session, "concierge_guest_journeys")
        has_notifications = await self._table_exists(session, "concierge_notifications")

        latest_message_join = """
            LEFT JOIN LATERAL (
                SELECT content AS latest_message_content,
                       detected_intent AS latest_message_intent,
                       direction AS latest_message_direction,
                       created_at AS latest_message_created_at
                FROM concierge_messages
                WHERE session_id = s.session_id
                ORDER BY created_at DESC
                LIMIT 1
            ) msg ON TRUE
            LEFT JOIN LATERAL (
                SELECT
                    COUNT(*) FILTER (
                        WHERE direction = 'outbound'
                          AND created_at >= NOW() - INTERVAL '72 hours'
                    ) AS recent_outbound_count,
                    COUNT(*) FILTER (
                        WHERE direction = 'inbound'
                          AND created_at >= NOW() - INTERVAL '72 hours'
                    ) AS recent_inbound_count,
                    COUNT(*) FILTER (
                        WHERE direction = 'outbound'
                          AND created_at > COALESCE(
                              (
                                SELECT MAX(created_at)
                                FROM concierge_messages mi
                                WHERE mi.session_id = s.session_id
                                  AND mi.direction = 'inbound'
                              ),
                              TO_TIMESTAMP(0)
                          )
                    ) AS consecutive_outbound_without_reply
                FROM concierge_messages stats
                WHERE stats.session_id = s.session_id
            ) msg_stats ON TRUE
        """ if has_messages else """
            LEFT JOIN LATERAL (
                SELECT NULL::text AS latest_message_content,
                       NULL::text AS latest_message_intent,
                       NULL::text AS latest_message_direction,
                       NULL::timestamptz AS latest_message_created_at
            ) msg ON TRUE
            LEFT JOIN LATERAL (
                SELECT 0::bigint AS recent_outbound_count,
                       0::bigint AS recent_inbound_count,
                       0::bigint AS consecutive_outbound_without_reply
            ) msg_stats ON TRUE
        """

        journey_join = """
            LEFT JOIN concierge_guest_journeys j
              ON j.session_id = s.session_id
        """ if has_journeys else """
            LEFT JOIN LATERAL (
                SELECT NULL::boolean AS welcome_sent,
                       NULL::boolean AS checkin_reminder_sent,
                       NULL::boolean AS checkout_reminder_sent,
                       NULL::boolean AS extend_offer_sent,
                       NULL::boolean AS pool_heat_offered,
                       NULL::boolean AS pool_heat_accepted
            ) j ON TRUE
        """

        notification_join = """
            LEFT JOIN (
                SELECT session_id, COUNT(*) AS notification_count
                FROM concierge_notifications
                GROUP BY session_id
            ) notif ON notif.session_id = s.session_id
        """ if has_notifications else """
            LEFT JOIN LATERAL (
                SELECT 0::bigint AS notification_count
            ) notif ON TRUE
        """

        try:
            rows = (
                await session.execute(
                    text(
                        f"""
                        SELECT s.session_id, s.token, s.property_id, s.property_code, s.property_name,
                               s.guest_name, s.guest_phone, s.guest_email,
                               s.status, s.phase, s.check_in, s.check_out,
                               s.conversation_count, s.last_message_at,
                               s.reservation_id, s.pms_synced_at, s.proactive_triggered_at, s.property_context,
                               COALESCE(j.welcome_sent, FALSE) AS welcome_sent,
                               COALESCE(j.checkin_reminder_sent, FALSE) AS checkin_reminder_sent,
                               COALESCE(j.checkout_reminder_sent, FALSE) AS checkout_reminder_sent,
                               COALESCE(j.extend_offer_sent, FALSE) AS extend_offer_sent,
                               COALESCE(j.pool_heat_offered, FALSE) AS pool_heat_offered,
                               COALESCE(j.pool_heat_accepted, FALSE) AS pool_heat_accepted,
                               COALESCE(notif.notification_count, 0) AS notification_count,
                               COALESCE(esc.open_escalations, 0) AS open_escalations,
                               msg.latest_message_content,
                               msg.latest_message_intent,
                               msg.latest_message_direction,
                               msg.latest_message_created_at,
                               COALESCE(msg_stats.recent_outbound_count, 0) AS recent_outbound_count,
                               COALESCE(msg_stats.recent_inbound_count, 0) AS recent_inbound_count,
                               COALESCE(msg_stats.consecutive_outbound_without_reply, 0) AS consecutive_outbound_without_reply
                        FROM concierge_guest_sessions s
                        {journey_join}
                        {notification_join}
                        LEFT JOIN (
                            SELECT session_token, COUNT(*) FILTER (WHERE status IN ('pending', 'acknowledged')) AS open_escalations
                            FROM concierge_escalations
                            GROUP BY session_token
                        ) esc ON esc.session_token = s.token
                        {latest_message_join}
                        WHERE s.tenant_id = CAST(:tid AS uuid)
                          AND s.session_id = ANY(CAST(:session_ids AS uuid[]))
                        """
                    ),
                    {"tid": tenant_id, "session_ids": session_ids},
                )
            ).mappings().all()
            return [dict(row) for row in rows]
        except Exception as exc:
            logger.warning("[StayWorkflowService] load session rows failed: %s", exc)
            try:
                await session.rollback()
            except Exception:
                pass
            return []

    def _build_workflow(self, row: dict[str, Any], existing_workflow: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        existing_workflow = existing_workflow if isinstance(existing_workflow, dict) else {}
        status = str(row.get("status") or "active").lower()
        phase = str(row.get("phase") or "pre_arrival").lower()
        open_escalations = int(row.get("open_escalations") or 0)
        latest_direction = str(row.get("latest_message_direction") or "").lower()
        notification_count = int(row.get("notification_count") or 0)
        existing_turnover = existing_workflow.get("turnover") if isinstance(existing_workflow.get("turnover"), dict) else {}
        turnover_status = str(existing_turnover.get("status") or "").lower()

        if not turnover_status:
            if phase == "post_stay":
                turnover_status = "pending"
            elif phase == "departure_day":
                turnover_status = "planned"
            else:
                turnover_status = "not_needed"

        turnover_ready = turnover_status in {"ready", "archived"}
        archive_eligible = turnover_ready and open_escalations == 0
        terminal_status = status in {"closed", "expired"}

        if archive_eligible or terminal_status:
            workflow_stage = "archived"
            operational_state = "archived"
        elif phase == "post_stay" and turnover_status in {"pending", "planned", "in_progress", "reassigned"}:
            workflow_stage = "turnover_in_progress"
            operational_state = "active"
        elif open_escalations > 0:
            workflow_stage = "issue_active"
            operational_state = "active"
        elif phase in {"pre_arrival", "arrival_day"}:
            workflow_stage = "arrival_prep"
            operational_state = "active"
        elif phase == "in_stay":
            workflow_stage = "in_stay_active"
            operational_state = "active"
        elif phase == "departure_day":
            workflow_stage = "checkout_prep"
            operational_state = "active"
        else:
            workflow_stage = "post_stay_followup"
            operational_state = "active"

        guest_update_state = (
            "awaiting_operator"
            if latest_direction == "inbound"
            else "guest_notified" if latest_direction == "outbound" else "idle"
        )
        escalation_state = "open" if open_escalations > 0 else "clear"

        timeline = [
            {"key": "arrival_prep", "label": "Arrival prep", "done": phase not in {"pre_arrival"}, "at": _iso(row.get("check_in"))},
            {"key": "in_stay_active", "label": "In stay", "done": phase in {"in_stay", "departure_day", "post_stay"}, "at": _iso(row.get("latest_message_created_at"))},
            {"key": "checkout_prep", "label": "Checkout prep", "done": phase in {"departure_day", "post_stay"}, "at": _iso(row.get("check_out"))},
            {"key": "post_stay_followup", "label": "Post stay", "done": phase == "post_stay", "at": _iso(row.get("check_out"))},
            {"key": "turnover_in_progress", "label": "Turnover", "done": turnover_status in {"ready", "archived"}, "at": _iso(existing_turnover.get("updated_at") or existing_turnover.get("ready_at"))},
            {"key": "archived", "label": "Archived", "done": operational_state == "archived", "at": _iso(existing_turnover.get("archived_at") or existing_turnover.get("ready_at"))},
        ]

        existing_vendor = existing_workflow.get("vendor") if isinstance(existing_workflow.get("vendor"), dict) else {}
        existing_guest_update = existing_workflow.get("guest_update") if isinstance(existing_workflow.get("guest_update"), dict) else {}
        vendor_history = existing_workflow.get("vendor_history") if isinstance(existing_workflow.get("vendor_history"), list) else []
        existing_walkthrough = existing_workflow.get("walkthrough") if isinstance(existing_workflow.get("walkthrough"), dict) else {}

        return {
            "stage": workflow_stage,
            "phase": phase,
            "operational_state": operational_state,
            "archive_eligible": archive_eligible,
            "escalation_state": escalation_state,
            "guest_update_state": guest_update_state,
            "guest_name": row.get("guest_name"),
            "property_code": row.get("property_code"),
            "property_name": row.get("property_name"),
            "reservation_id": row.get("reservation_id"),
            "notification_count": notification_count,
            "open_escalations": open_escalations,
            "latest_message_summary": row.get("latest_message_content"),
            "latest_message_intent": row.get("latest_message_intent"),
            "latest_message_at": _iso(row.get("latest_message_created_at") or row.get("last_message_at")),
            "vendor_name": existing_vendor.get("name"),
            "vendor_eta_minutes": existing_vendor.get("eta_minutes"),
            "vendor": {
                "selected_vendor_id": existing_vendor.get("selected_vendor_id"),
                "name": existing_vendor.get("name"),
                "phone": existing_vendor.get("phone"),
                "category_slug": existing_vendor.get("category_slug"),
                "dispatch_state": existing_vendor.get("dispatch_state", "not_started"),
                "previous_dispatch_state": existing_vendor.get("previous_dispatch_state"),
                "eta_minutes": existing_vendor.get("eta_minutes"),
                "selected_at": existing_vendor.get("selected_at"),
                "last_updated_at": existing_vendor.get("last_updated_at"),
                "status_changed_at": existing_vendor.get("status_changed_at"),
                "status_changed_by": existing_vendor.get("status_changed_by"),
                "replacement_count": int(existing_vendor.get("replacement_count") or 0),
                "last_transition_note": existing_vendor.get("last_transition_note"),
            },
            "vendor_history": vendor_history,
            "guest_update": {
                "status": existing_guest_update.get("status", "idle"),
                "updated_at": existing_guest_update.get("updated_at"),
                "note": existing_guest_update.get("note"),
            },
            "turnover": {
                "status": turnover_status,
                "ready_for_next_guest": turnover_ready,
                "assigned_vendor_id": existing_turnover.get("assigned_vendor_id") or existing_vendor.get("selected_vendor_id"),
                "assigned_vendor_name": existing_turnover.get("assigned_vendor_name") or existing_vendor.get("name"),
                "started_at": existing_turnover.get("started_at"),
                "ready_at": existing_turnover.get("ready_at"),
                "archived_at": existing_turnover.get("archived_at"),
                "updated_at": existing_turnover.get("updated_at"),
                "updated_by": existing_turnover.get("updated_by"),
                "note": existing_turnover.get("note"),
            },
            "walkthrough": {
                "status": str(existing_walkthrough.get("status") or "not_required").lower(),
                "required": bool(existing_walkthrough.get("required")),
                "completed_at": existing_walkthrough.get("completed_at"),
                "updated_at": existing_walkthrough.get("updated_at"),
                "updated_by": existing_walkthrough.get("updated_by"),
                "note": existing_walkthrough.get("note"),
            },
            "journey": {
                "welcome_sent": bool(row.get("welcome_sent")),
                "checkin_reminder_sent": bool(row.get("checkin_reminder_sent")),
                "checkout_reminder_sent": bool(row.get("checkout_reminder_sent")),
                "extend_offer_sent": bool(row.get("extend_offer_sent")),
                "pool_heat_offered": bool(row.get("pool_heat_offered")),
                "pool_heat_accepted": bool(row.get("pool_heat_accepted")),
            },
            "message_memory": {
                "recent_outbound_count": int(row.get("recent_outbound_count") or 0),
                "recent_inbound_count": int(row.get("recent_inbound_count") or 0),
                "consecutive_outbound_without_reply": int(row.get("consecutive_outbound_without_reply") or 0),
            },
            "timeline": timeline,
            "refreshed_at": datetime.now(timezone.utc).isoformat(),
        }

    async def _existing_workflow(
        self,
        session: AsyncSession,
        tenant_id: str,
        session_id: str,
    ) -> dict[str, Any]:
        if not session_id:
            return {}
        if not await self._table_exists(session, "operator_stay_workflow_read_models"):
            return {}
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
            return workflow if isinstance(workflow, dict) else {}
        except Exception:
            await _rollback_quietly(session)
            return {}

    async def _load_policy(self, session: AsyncSession, tenant_id: str) -> dict[str, Any]:
        proactive_defaults = {
            "enabled_touch_types": [
                "pre_arrival_welcome",
                "arrival_info",
                "dinner_planning",
                "arrival_day_checkin",
                "in_stay_checkin",
                "checkout_prep",
                "extend_offer",
                "service_update_reassurance",
            ],
            "min_hours_between_proactive_touches": 18,
            "min_hours_between_service_updates": 4,
            "max_notifications_per_stay_window": 6,
            "allow_service_updates_during_escalation": True,
        }
        escalation_defaults = {
            "allow_eta_updates": True,
            "allow_reassurance_without_eta": True,
            "operator_approval_required_for_status_updates": False,
        }
        stay_operations_defaults = {
            "workflow_profile": "assisted_ops",
            "enable_access_workflows": True,
            "enable_rental_workflows": True,
            "enable_turnover_workflows": True,
            "enable_maintenance_workflows": True,
            "enable_post_checkout_walkthrough": False,
            "walkthrough_required_before_ready": False,
            "auto_archive_when_turnover_ready": True,
        }
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
            await _rollback_quietly(session)
            row = None

        extra = row.get("extra") if row else {}
        if isinstance(extra, str):
            try:
                extra = json.loads(extra)
            except Exception:
                extra = {}
        extra = extra if isinstance(extra, dict) else {}
        proactive = dict(proactive_defaults)
        proactive.update(extra.get("proactive_policy") or {})
        escalation = dict(escalation_defaults)
        escalation.update(extra.get("escalation_guest_policy") or {})
        stay_operations = dict(stay_operations_defaults)
        stay_operations.update(extra.get("stay_operations_policy") or {})
        return {
            "proactive": proactive,
            "escalation_guest": escalation,
            "stay_operations": stay_operations,
        }

    def _apply_operational_rules(self, row: dict[str, Any], workflow: dict[str, Any]) -> None:
        operations = workflow.get("operations") if isinstance(workflow.get("operations"), dict) else {}
        modules = operations.get("modules") if isinstance(operations.get("modules"), dict) else {}
        handoffs = workflow.get("handoffs") if isinstance(workflow.get("handoffs"), dict) else {}
        handoff_items = handoffs.get("items") if isinstance(handoffs.get("items"), list) else []
        work_orders = workflow.get("work_orders") if isinstance(workflow.get("work_orders"), dict) else {}
        work_order_items = work_orders.get("items") if isinstance(work_orders.get("items"), list) else []
        turnover = workflow.get("turnover") if isinstance(workflow.get("turnover"), dict) else {}
        walkthrough = workflow.get("walkthrough") if isinstance(workflow.get("walkthrough"), dict) else {}
        phase = str(workflow.get("phase") or row.get("phase") or "").lower()
        open_escalations = int(workflow.get("open_escalations") or row.get("open_escalations") or 0)

        walkthrough_required = bool(modules.get("post_checkout_walkthrough") and modules.get("walkthrough_required_before_ready"))
        walkthrough_handoffs = [item for item in handoff_items if str(item.get("handoff_type") or "") == "walkthrough_review"]
        walkthrough_open = any(str(item.get("status") or "").lower() in {"open", "in_progress", "blocked"} for item in walkthrough_handoffs)
        walkthrough_completed_item = next((item for item in walkthrough_handoffs if str(item.get("status") or "").lower() == "completed"), None)

        if modules.get("post_checkout_walkthrough") and phase == "post_stay":
            walkthrough["required"] = True
            if walkthrough_open:
                walkthrough["status"] = "in_progress"
            elif walkthrough_completed_item:
                walkthrough["status"] = "completed"
                walkthrough["completed_at"] = walkthrough_completed_item.get("closed_at")
            else:
                walkthrough["status"] = "pending"
        elif not modules.get("post_checkout_walkthrough"):
            walkthrough["required"] = False
            walkthrough["status"] = "not_required"
        workflow["walkthrough"] = walkthrough
        if work_order_items:
            latest_order = work_order_items[0]
            turnover["active_work_order_status"] = latest_order.get("status")
            turnover["active_dispatch_state"] = latest_order.get("dispatch_state")
        workflow["turnover"] = turnover

        turnover_ready = bool(turnover.get("ready_for_next_guest"))
        auto_archive = bool(modules.get("auto_archive_when_turnover_ready"))
        turnover_enabled = bool(modules.get("turnover_workflows"))

        if not turnover_enabled and phase == "post_stay" and open_escalations == 0:
            turnover["status"] = "not_tracked"
            turnover["ready_for_next_guest"] = True
            workflow["turnover"] = turnover
            workflow["archive_eligible"] = True
            workflow["operational_state"] = "archived" if auto_archive else "active"
            if auto_archive:
                workflow["stage"] = "archived"
            return

        if turnover_ready and open_escalations == 0:
            if walkthrough_required and walkthrough.get("status") != "completed":
                workflow["archive_eligible"] = False
                workflow["operational_state"] = "active"
                workflow["stage"] = "turnover_in_progress"
            else:
                workflow["archive_eligible"] = True
                if auto_archive:
                    workflow["operational_state"] = "archived"
                    workflow["stage"] = "archived"
        elif turnover_enabled and phase in {"departure_day", "post_stay"} and workflow.get("stage") in {"post_stay_followup", "checkout_prep"}:
            workflow["operational_state"] = "active"
            workflow["stage"] = "turnover_in_progress"

    def _apply_event_summary(self, workflow: dict[str, Any]) -> None:
        events = workflow.get("events") if isinstance(workflow.get("events"), dict) else {}
        turnover = workflow.get("turnover") if isinstance(workflow.get("turnover"), dict) else {}
        walkthrough = workflow.get("walkthrough") if isinstance(workflow.get("walkthrough"), dict) else {}
        phase = str(workflow.get("phase") or "").lower()

        property_ready_at = events.get("property_ready_at")
        housekeeping_arrived_at = events.get("housekeeping_arrived_at")
        housekeeping_completed_at = events.get("housekeeping_completed_at")
        documentation_started_at = events.get("documentation_started_at")
        documentation_completed_at = events.get("documentation_completed_at")

        if housekeeping_arrived_at and turnover.get("status") in {"", "planned", "pending", "reassigned"}:
            turnover["status"] = "in_progress"
            turnover["started_at"] = turnover.get("started_at") or housekeeping_arrived_at
        if housekeeping_completed_at and turnover.get("status") in {"planned", "pending"}:
            turnover["status"] = "in_progress"
            turnover["updated_at"] = housekeeping_completed_at
        if property_ready_at:
            turnover["status"] = "ready"
            turnover["ready_for_next_guest"] = True
            turnover["ready_at"] = property_ready_at
        if phase == "post_stay" and documentation_started_at and walkthrough.get("status") in {"not_required", "", "pending"}:
            walkthrough["status"] = "in_progress"
            walkthrough["updated_at"] = documentation_started_at
        if documentation_completed_at:
            walkthrough["status"] = "completed"
            walkthrough["completed_at"] = documentation_completed_at
            walkthrough["updated_at"] = documentation_completed_at
        workflow["turnover"] = turnover
        workflow["walkthrough"] = walkthrough

    async def _persist_workflow(
        self,
        session: AsyncSession,
        tenant_id: str,
        row: dict[str, Any],
        workflow: dict[str, Any],
        *,
        commit: bool = True,
    ) -> None:
        await session.execute(
            text(
                """
                INSERT INTO operator_stay_workflow_read_models
                    (session_id, tenant_id, session_token, property_code, workflow_stage, phase,
                     escalation_state, guest_update_state, workflow_json, refreshed_at, updated_at)
                VALUES
                    (CAST(:session_id AS uuid), CAST(:tid AS uuid), :session_token, :property_code, :workflow_stage, :phase,
                     :escalation_state, :guest_update_state, CAST(:workflow_json AS jsonb), NOW(), NOW())
                ON CONFLICT (session_id) DO UPDATE SET
                    session_token = EXCLUDED.session_token,
                    property_code = EXCLUDED.property_code,
                    workflow_stage = EXCLUDED.workflow_stage,
                    phase = EXCLUDED.phase,
                    escalation_state = EXCLUDED.escalation_state,
                    guest_update_state = EXCLUDED.guest_update_state,
                    workflow_json = EXCLUDED.workflow_json,
                    refreshed_at = NOW(),
                    updated_at = NOW()
                """
            ),
            {
                "session_id": str(row["session_id"]),
                "tid": tenant_id,
                "session_token": row.get("token") or "",
                "property_code": row.get("property_code") or "",
                "workflow_stage": workflow.get("stage") or "arrival_prep",
                "phase": workflow.get("phase"),
                "escalation_state": workflow.get("escalation_state"),
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


async def _rollback_quietly(session: AsyncSession) -> None:
    try:
        await session.rollback()
    except Exception:
        pass


_SERVICE = StayWorkflowService()


def get_stay_workflow_service() -> StayWorkflowService:
    return _SERVICE
