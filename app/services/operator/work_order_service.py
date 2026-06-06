from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


_ACTIVE_STATUSES = {"opened", "contacting_vendor", "accepted", "scheduled", "en_route", "on_site", "work_completed", "awaiting_verification", "invoice_received", "invoice_approved"}
_TERMINAL_STATUSES = {"verified", "closed", "cancelled", "failed", "reassigned"}


class OperatorWorkOrderService:
    async def create_or_refresh_work_order(
        self,
        session: AsyncSession,
        tenant_id: str,
        *,
        workflow_type: str,
        workflow_ref: str,
        property_code: str | None = None,
        vendor_id: str | None = None,
        vendor_name: str | None = None,
        vendor_phone: str | None = None,
        issue_category: str = "maintenance",
        priority: str = "medium",
        summary: str = "",
        details: str = "",
        dispatch_state: str = "opened",
        eta_minutes: int | None = None,
        eta_visibility_mode: str = "estimated",
        tracking_url: str | None = None,
        last_known_distance_text: str | None = None,
        asset_id: str | None = None,
        last_actor_label: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not workflow_ref or not await self._table_exists(session, "operator_work_orders"):
            return {}

        existing = (
            await session.execute(
                text(
                    """
                    SELECT CAST(work_order_id AS text) AS work_order_id,
                           status, verification_state, invoice_state
                    FROM operator_work_orders
                    WHERE tenant_id = CAST(:tid AS uuid)
                      AND workflow_type = :workflow_type
                      AND workflow_ref = :workflow_ref
                      AND status <> 'closed'
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """
                ),
                {"tid": tenant_id, "workflow_type": workflow_type, "workflow_ref": workflow_ref},
            )
        ).mappings().first()

        next_status = self._status_from_dispatch(dispatch_state)
        verification_state = self._verification_from_status(next_status)

        if existing:
            await session.execute(
                text(
                    """
                    UPDATE operator_work_orders
                    SET property_code = COALESCE(:property_code, property_code),
                        vendor_id = CASE WHEN :vendor_id = '' THEN vendor_id ELSE CAST(:vendor_id AS uuid) END,
                        vendor_name = COALESCE(:vendor_name, vendor_name),
                        vendor_phone = COALESCE(:vendor_phone, vendor_phone),
                        issue_category = :issue_category,
                        priority = :priority,
                        summary = :summary,
                        details = :details,
                        dispatch_state = :dispatch_state,
                        status = :status,
                        eta_minutes = COALESCE(:eta_minutes, eta_minutes),
                        eta_visibility_mode = :eta_visibility_mode,
                        tracking_url = COALESCE(:tracking_url, tracking_url),
                        last_known_distance_text = COALESCE(:last_known_distance_text, last_known_distance_text),
                        asset_id = CASE WHEN :asset_id = '' THEN asset_id ELSE CAST(:asset_id AS uuid) END,
                        verification_state = :verification_state,
                        last_actor_label = COALESCE(:last_actor_label, last_actor_label),
                        payload_json = CAST(:payload_json AS jsonb),
                        updated_at = NOW(),
                        accepted_at = CASE WHEN :status = 'accepted' AND accepted_at IS NULL THEN NOW() ELSE accepted_at END,
                        scheduled_at = CASE WHEN :status IN ('scheduled','en_route','on_site','work_completed','awaiting_verification','verified','closed') AND scheduled_at IS NULL THEN NOW() ELSE scheduled_at END,
                        completed_at = CASE WHEN :status IN ('work_completed','awaiting_verification','verified','closed') THEN NOW() ELSE completed_at END,
                        verified_at = CASE WHEN :status IN ('verified','closed') THEN NOW() ELSE verified_at END,
                        closed_at = CASE WHEN :status = 'closed' THEN NOW() ELSE closed_at END
                    WHERE work_order_id = CAST(:work_order_id AS uuid)
                    """
                ),
                {
                    "work_order_id": existing["work_order_id"],
                    "property_code": property_code,
                    "vendor_id": vendor_id or "",
                    "vendor_name": vendor_name,
                    "vendor_phone": vendor_phone,
                    "issue_category": issue_category,
                    "priority": priority,
                    "summary": summary,
                    "details": details,
                    "dispatch_state": dispatch_state,
                    "status": next_status,
                    "eta_minutes": eta_minutes,
                    "eta_visibility_mode": eta_visibility_mode,
                    "tracking_url": tracking_url,
                    "last_known_distance_text": last_known_distance_text,
                    "asset_id": asset_id or "",
                    "verification_state": verification_state,
                    "last_actor_label": last_actor_label,
                    "payload_json": json.dumps(payload or {}),
                },
            )
            return {
                "work_order_id": str(existing["work_order_id"]),
                "status": next_status,
                "verification_state": verification_state,
                "invoice_state": str(existing.get("invoice_state") or "not_received"),
            }

        created = (
            await session.execute(
                text(
                    """
                    INSERT INTO operator_work_orders
                        (tenant_id, workflow_type, workflow_ref, property_code,
                         vendor_id, vendor_name, vendor_phone, issue_category,
                         status, priority, summary, details, dispatch_state, eta_minutes, eta_visibility_mode, tracking_url, last_known_distance_text, asset_id,
                         verification_state, invoice_state, last_actor_label, payload_json,
                         accepted_at, scheduled_at, completed_at, verified_at, closed_at)
                    VALUES
                        (CAST(:tid AS uuid), :workflow_type, :workflow_ref, :property_code,
                         CASE WHEN :vendor_id = '' THEN NULL ELSE CAST(:vendor_id AS uuid) END, :vendor_name, :vendor_phone, :issue_category,
                         :status, :priority, :summary, :details, :dispatch_state, :eta_minutes, :eta_visibility_mode, :tracking_url, :last_known_distance_text, CASE WHEN :asset_id = '' THEN NULL ELSE CAST(:asset_id AS uuid) END,
                         :verification_state, 'not_received', :last_actor_label, CAST(:payload_json AS jsonb),
                         CASE WHEN :status = 'accepted' THEN NOW() ELSE NULL END,
                         CASE WHEN :status IN ('scheduled','en_route','on_site','work_completed','awaiting_verification','verified','closed') THEN NOW() ELSE NULL END,
                         CASE WHEN :status IN ('work_completed','awaiting_verification','verified','closed') THEN NOW() ELSE NULL END,
                         CASE WHEN :status IN ('verified','closed') THEN NOW() ELSE NULL END,
                         CASE WHEN :status = 'closed' THEN NOW() ELSE NULL END)
                    RETURNING CAST(work_order_id AS text) AS work_order_id
                    """
                ),
                {
                    "tid": tenant_id,
                    "workflow_type": workflow_type,
                    "workflow_ref": workflow_ref,
                    "property_code": property_code,
                    "vendor_id": vendor_id or "",
                    "vendor_name": vendor_name,
                    "vendor_phone": vendor_phone,
                    "issue_category": issue_category,
                    "status": next_status,
                    "priority": priority,
                    "summary": summary,
                    "details": details,
                    "dispatch_state": dispatch_state,
                    "eta_minutes": eta_minutes,
                    "eta_visibility_mode": eta_visibility_mode,
                    "tracking_url": tracking_url,
                    "last_known_distance_text": last_known_distance_text,
                    "asset_id": asset_id or "",
                    "verification_state": verification_state,
                    "last_actor_label": last_actor_label,
                    "payload_json": json.dumps(payload or {}),
                },
            )
        ).mappings().first()
        return {
            "work_order_id": str(created["work_order_id"]) if created else "",
            "status": next_status,
            "verification_state": verification_state,
            "invoice_state": "not_received",
        }

    async def list_work_orders(
        self,
        session: AsyncSession,
        tenant_id: str,
        *,
        workflow_type: str,
        workflow_refs: list[str],
    ) -> dict[str, list[dict[str, Any]]]:
        if not workflow_refs or not await self._table_exists(session, "operator_work_orders"):
            return {}
        rows = (
            await session.execute(
                text(
                    """
                    SELECT CAST(work_order_id AS text) AS work_order_id,
                           workflow_ref, property_code, vendor_id, vendor_name, vendor_phone,
                           issue_category, status, priority, summary, details, dispatch_state,
                           eta_minutes, eta_visibility_mode, tracking_url, last_known_distance_text, asset_id,
                           verification_state, invoice_state, invoice_amount, invoice_reference,
                           last_actor_label, payload_json, resolution_json,
                           created_at, updated_at, accepted_at, scheduled_at, completed_at, verified_at, closed_at
                    FROM operator_work_orders
                    WHERE tenant_id = CAST(:tid AS uuid)
                      AND workflow_type = :workflow_type
                      AND workflow_ref = ANY(CAST(:workflow_refs AS text[]))
                    ORDER BY updated_at DESC
                    """
                ),
                {"tid": tenant_id, "workflow_type": workflow_type, "workflow_refs": workflow_refs},
            )
        ).mappings().all()
        result: dict[str, list[dict[str, Any]]] = {ref: [] for ref in workflow_refs}
        for row in rows:
            item = dict(row)
            for key in ("payload_json", "resolution_json"):
                value = item.get(key)
                if isinstance(value, str):
                    try:
                        item[key] = json.loads(value)
                    except Exception:
                        item[key] = {}
            result.setdefault(str(row["workflow_ref"]), []).append(
                {
                    "work_order_id": str(row["work_order_id"]),
                    "workflow_ref": str(row["workflow_ref"]),
                    "workflow_type": workflow_type,
                    "property_code": row.get("property_code"),
                    "vendor_id": str(row["vendor_id"]) if row.get("vendor_id") else None,
                    "vendor_name": row.get("vendor_name"),
                    "vendor_phone": row.get("vendor_phone"),
                    "issue_category": row.get("issue_category"),
                    "status": row.get("status"),
                    "priority": row.get("priority"),
                    "summary": row.get("summary"),
                    "details": row.get("details"),
                    "dispatch_state": row.get("dispatch_state"),
                    "eta_minutes": row.get("eta_minutes"),
                    "eta_visibility_mode": row.get("eta_visibility_mode") or "estimated",
                    "tracking_url": row.get("tracking_url"),
                    "last_known_distance_text": row.get("last_known_distance_text"),
                    "asset_id": str(row["asset_id"]) if row.get("asset_id") else None,
                    "verification_state": row.get("verification_state"),
                    "invoice_state": row.get("invoice_state"),
                    "invoice_amount": float(row["invoice_amount"]) if row.get("invoice_amount") is not None else None,
                    "invoice_reference": row.get("invoice_reference"),
                    "last_actor_label": row.get("last_actor_label"),
                    "payload": item.get("payload_json") if isinstance(item.get("payload_json"), dict) else {},
                    "resolution": item.get("resolution_json") if isinstance(item.get("resolution_json"), dict) else {},
                    "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
                    "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
                    "accepted_at": row["accepted_at"].isoformat() if row.get("accepted_at") else None,
                    "scheduled_at": row["scheduled_at"].isoformat() if row.get("scheduled_at") else None,
                    "completed_at": row["completed_at"].isoformat() if row.get("completed_at") else None,
                    "verified_at": row["verified_at"].isoformat() if row.get("verified_at") else None,
                    "closed_at": row["closed_at"].isoformat() if row.get("closed_at") else None,
                }
            )
        return result

    async def get_work_order(self, session: AsyncSession, tenant_id: str, work_order_id: str) -> dict[str, Any]:
        if not work_order_id or not await self._table_exists(session, "operator_work_orders"):
            return {}
        row = (
            await session.execute(
                text(
                    """
                    SELECT CAST(work_order_id AS text) AS work_order_id,
                           workflow_type, workflow_ref, property_code, vendor_id, vendor_name, vendor_phone,
                           issue_category, status, priority, summary, details, dispatch_state,
                           eta_minutes, eta_visibility_mode, tracking_url, last_known_distance_text, asset_id,
                           verification_state, invoice_state, invoice_amount, invoice_reference,
                           last_actor_label, payload_json, resolution_json,
                           created_at, updated_at, accepted_at, scheduled_at, completed_at, verified_at, closed_at
                    FROM operator_work_orders
                    WHERE tenant_id = CAST(:tid AS uuid)
                      AND work_order_id = CAST(:work_order_id AS uuid)
                    LIMIT 1
                    """
                ),
                {"tid": tenant_id, "work_order_id": work_order_id},
            )
        ).mappings().first()
        if not row:
            return {}
        items = (
            await self.list_work_orders(
                session,
                tenant_id,
                workflow_type=str(row["workflow_type"]),
                workflow_refs=[str(row["workflow_ref"])],
            )
        ).get(str(row["workflow_ref"]), [])
        for item in items:
            if str(item.get("work_order_id") or "") == work_order_id:
                return item
        return {}

    async def update_work_order(
        self,
        session: AsyncSession,
        tenant_id: str,
        work_order_id: str,
        *,
        status: str | None = None,
        dispatch_state: str | None = None,
        verification_state: str | None = None,
        invoice_state: str | None = None,
        invoice_amount: float | None = None,
        invoice_reference: str | None = None,
        eta_minutes: int | None = None,
        eta_visibility_mode: str | None = None,
        tracking_url: str | None = None,
        last_known_distance_text: str | None = None,
        asset_id: str | None = None,
        last_actor_label: str | None = None,
        resolution: dict[str, Any] | None = None,
    ) -> bool:
        if not work_order_id or not await self._table_exists(session, "operator_work_orders"):
            return False
        next_status = (status or "").strip().lower() or None
        next_dispatch_state = (dispatch_state or "").strip().lower() or None
        next_verification_state = (verification_state or "").strip().lower() or None
        next_invoice_state = (invoice_state or "").strip().lower() or None
        if next_status and next_status not in (_ACTIVE_STATUSES | _TERMINAL_STATUSES):
            raise ValueError("Invalid work order status")
        if next_verification_state and next_verification_state not in {"pending", "needs_review", "verified", "rejected"}:
            raise ValueError("Invalid verification state")
        if next_invoice_state and next_invoice_state not in {"not_received", "received", "approved", "disputed", "paid"}:
            raise ValueError("Invalid invoice state")
        await session.execute(
            text(
                """
                UPDATE operator_work_orders
                SET status = COALESCE(:status, status),
                    dispatch_state = COALESCE(:dispatch_state, dispatch_state),
                    verification_state = COALESCE(:verification_state, verification_state),
                    invoice_state = COALESCE(:invoice_state, invoice_state),
                    invoice_amount = COALESCE(:invoice_amount, invoice_amount),
                    invoice_reference = COALESCE(:invoice_reference, invoice_reference),
                    eta_minutes = COALESCE(:eta_minutes, eta_minutes),
                    eta_visibility_mode = COALESCE(:eta_visibility_mode, eta_visibility_mode),
                    tracking_url = COALESCE(:tracking_url, tracking_url),
                    last_known_distance_text = COALESCE(:last_known_distance_text, last_known_distance_text),
                    asset_id = CASE WHEN :asset_id = '' THEN asset_id ELSE CAST(:asset_id AS uuid) END,
                    last_actor_label = COALESCE(:last_actor_label, last_actor_label),
                    resolution_json = CASE WHEN :resolution_json IS NULL THEN resolution_json ELSE CAST(:resolution_json AS jsonb) END,
                    updated_at = NOW(),
                    completed_at = CASE WHEN COALESCE(:status, status) IN ('work_completed','awaiting_verification','verified','closed') THEN NOW() ELSE completed_at END,
                    verified_at = CASE WHEN COALESCE(:verification_state, verification_state) = 'verified' OR COALESCE(:status, status) IN ('verified','closed') THEN NOW() ELSE verified_at END,
                    closed_at = CASE WHEN COALESCE(:status, status) = 'closed' THEN NOW() ELSE closed_at END
                WHERE tenant_id = CAST(:tid AS uuid)
                  AND work_order_id = CAST(:work_order_id AS uuid)
                """
            ),
            {
                "tid": tenant_id,
                "work_order_id": work_order_id,
                "status": next_status,
                "dispatch_state": next_dispatch_state,
                "verification_state": next_verification_state,
                "invoice_state": next_invoice_state,
                "invoice_amount": invoice_amount,
                "invoice_reference": invoice_reference,
                "eta_minutes": eta_minutes,
                "eta_visibility_mode": eta_visibility_mode,
                "tracking_url": tracking_url,
                "last_known_distance_text": last_known_distance_text,
                "asset_id": asset_id or "",
                "last_actor_label": last_actor_label,
                "resolution_json": json.dumps(resolution) if resolution is not None else None,
            },
        )
        return True

    async def summarize_work_orders(
        self,
        session: AsyncSession,
        tenant_id: str,
        *,
        workflow_type: str,
        workflow_ref: str,
    ) -> dict[str, Any]:
        if not workflow_ref or not await self._table_exists(session, "operator_work_orders"):
            return {"open_count": 0, "total_count": 0, "statuses": [], "items": []}
        items = (await self.list_work_orders(session, tenant_id, workflow_type=workflow_type, workflow_refs=[workflow_ref])).get(workflow_ref, [])
        open_items = [item for item in items if str(item.get("status") or "").lower() not in _TERMINAL_STATUSES]
        return {
            "open_count": len(open_items),
            "total_count": len(items),
            "statuses": sorted({str(item.get("status") or "") for item in items if item.get("status")}),
            "items": items[:10],
        }

    def _status_from_dispatch(self, dispatch_state: str | None) -> str:
        state = str(dispatch_state or "").strip().lower()
        mapping = {
            "opened": "opened",
            "recommended": "opened",
            "contacted": "contacting_vendor",
            "dispatched": "accepted",
            "accepted": "accepted",
            "scheduled": "scheduled",
            "en_route": "en_route",
            "on_site": "on_site",
            "completed": "work_completed",
            "failed": "failed",
            "reassigned": "reassigned",
            "cancelled": "cancelled",
            "verified": "verified",
            "closed": "closed",
        }
        return mapping.get(state, "opened")

    def _verification_from_status(self, status: str) -> str:
        if status in {"work_completed", "awaiting_verification"}:
            return "needs_review"
        if status in {"verified", "closed"}:
            return "verified"
        return "pending"

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


_SERVICE = OperatorWorkOrderService()


def get_operator_work_order_service() -> OperatorWorkOrderService:
    return _SERVICE
