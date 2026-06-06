"""
maintenance_module.py — Maintenance work handler.

OWNERSHIP RULE (see docs/PHASE_1_3_SEAM_MAP.md "Rule 2"):

  This module is the SOLE owner of the relationship between two tables:

    1. concierge_maintenance_events — lightweight issue tracking
       (severity classification, dedupe window, optional notifications)
    2. operator_work_orders — operational dispatch
       (vendor lifecycle, ETA, status, invoice, verification)

  No other code in the brain may write to either table. The two tables
  are LINKED via operator_work_orders.payload_json["concierge_event_id"].
  Future readers can join on this field.

BRAIN_SCHEMA_LOCKDOWN invariant 1:

  MaintenanceModule (this file) is the SOLE automatic writer of
  concierge_maintenance_events. The only other permitted writer is the
  manual operator endpoint (POST /concierge/maintenance/events, handled
  by the manual CRUD handlers in app/api/v1/endpoints/concierge.py).

  The legacy /concierge/message endpoint previously called
  auto_track_from_message as a side-effect of every in-stay message.
  That call was retired in Step 10 (zero live traffic for 30+ days).

  CI grep allowlist — the ONLY files that may call auto_track_from_message:
    - app/services/concierge/maintenance_service.py  (defines it)
    - app/services/messaging_brain/modules/maintenance_module.py  (calls it)

  If you find code outside this file writing to either table:
    - If it's new brain-side code: that's a bug. Route it through this
      module instead.

VENDOR ROUTING (future):

  Phase 1.3 routes everything to the operator (vendor fields stay null).
  The work order created here becomes the operational spine. Vendor
  routing is added later by:
    - Adding a per-property toggle (similar shape to property_ai_autonomy)
    - Branching inside this module's handle_event(): if vendor enabled,
      pick a vendor via vendor_intelligence_service and populate
      vendor_id/vendor_name/vendor_phone on the work order
    - Vendor responses update the SAME work order via update_work_order
      (status lifecycle, ETA), they NEVER create a parallel record

  The brain's MaintenanceAgent does not change. The orchestrator's
  pipeline does not change. New module replaces or extends this one;
  registry gets updated.

SHADOW MODE (see docs/PHASE_1_3_SEAM_MAP.md "Rule 5"):

  When shadow_mode=True, this module produces a structured ModuleResponse
  describing what would have happened, but performs NO writes. This is
  how operators validate the brain works before flipping the live switch.
  The audit trail still records the would-be event for visibility.

REUSE OF PRIVATE HELPERS:

  We intentionally import _category_for and _severity_for from
  concierge/maintenance_service.py. These are private (underscore-prefixed)
  but they are stable, well-tested classifiers that the existing codebase
  already relies on. Re-implementing them here would create drift.
  If they are ever promoted to a public helper, replace these imports.
"""

from __future__ import annotations

import logging
from typing import Any, Optional
from uuid import UUID

# Stable private classifiers from the existing concierge maintenance service.
# Intentional reuse — see "REUSE OF PRIVATE HELPERS" note above.
from app.services.concierge.maintenance_service import (
    _category_for,
    _severity_for,
    get_concierge_maintenance_service,
)
from app.services.messaging.operator_alerts import (
    AlertType,
    format_maintenance_alert,
    get_alert_router,
)
from app.services.operator.work_order_service import (
    get_operator_work_order_service,
)
from app.services.orchestration.messaging_brain_contracts import (
    ModuleEvent,
    ModuleResponse,
)

logger = logging.getLogger(__name__)


# Workflow type identifies brain-created work orders so they can be
# distinguished from work orders created by other paths (escalation
# workflow, dashboard, etc.). Stable string — do not rename without
# updating downstream readers.
_WORKFLOW_TYPE = "messaging_brain_maintenance"


def _try_uuid(value: Optional[str]) -> Optional[UUID]:
    """Best-effort UUID cast; returns None for invalid or empty input."""
    if not value:
        return None
    try:
        return UUID(value)
    except (ValueError, AttributeError, TypeError):
        return None


class MaintenanceModule:
    """Handles ModuleEvent(module='maintenance', ...) by writing both
    the concierge tracking event and the operator work order.

    See module docstring for ownership rules.
    """

    name = "MaintenanceModule"
    handles_event_types = (
        "hvac_issue",
        "plumbing_issue",
        "appliance_issue",
        "internet_issue",
        "access_issue",
        "electronics_issue",
        "general_issue",
        "bike_issue",
    )

    async def handle_event(
        self,
        event: ModuleEvent,
        *,
        db_session: Any,
        shadow_mode: bool = False,
    ) -> ModuleResponse:
        """Dispatch a maintenance ModuleEvent.

        Always returns a ModuleResponse. Even on partial failure (e.g.
        concierge event written but work order failed) the response is
        success=True with the failure details in result. Total failure
        (both writes raised) returns success=False so the orchestrator
        can flag it in the audit log.

        In shadow mode, no writes are attempted. The response describes
        what would have happened.
        """
        # ── Shadow mode ──────────────────────────────────────────────────
        if shadow_mode:
            return self._shadow_response(event)

        # ── Live path: write concierge event first, then work order ──────
        result: dict[str, Any] = {}
        evidence: list[str] = []
        concierge_event_id: Optional[str] = None

        # 1. Concierge event (lightweight tracking).
        # Failure here does NOT block the work order — the work order is
        # the operational spine and matters more for guest experience.
        try:
            concierge_outcome = await self._write_concierge_event(
                db_session=db_session, event=event,
            )
            result["concierge_event"] = concierge_outcome
            created = (concierge_outcome or {}).get("created")
            if isinstance(created, dict) and created.get("event_id"):
                concierge_event_id = str(created["event_id"])
                evidence.append("concierge_maintenance_events.created")
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "[MaintenanceModule] concierge event write failed: %s", exc,
            )
            result["concierge_event_error"] = f"{type(exc).__name__}: {exc}"
            # continue to work order

        # 2. Operator work order (dispatch — operational spine).
        try:
            wo_outcome = await self._write_work_order(
                db_session=db_session,
                event=event,
                concierge_event_id=concierge_event_id,
            )
            result["work_order"] = wo_outcome
            if (wo_outcome or {}).get("work_order_id"):
                evidence.append("operator_work_orders.created")
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "[MaintenanceModule] work order write failed: %s", exc,
            )
            result["work_order_error"] = f"{type(exc).__name__}: {exc}"
            # If we couldn't even create the work order, this is a real
            # failure: the operator won't see anything in their dispatch
            # queue. Mark as failed so the orchestrator surfaces it.
            return ModuleResponse(
                event_id=event.event_id,
                module="maintenance",
                success=False,
                result=result,
                evidence_used=evidence,
                error=f"work order creation failed: {exc}",
            )

        # ── Operator notification (notify-only; autonomous dispatch deferred) ─
        # Best-effort: a notification failure does NOT roll back the work
        # order or the concierge event — those writes are the operational
        # spine. A failed alert is bad but not a reason to mark the whole
        # module response as failed. The error is recorded in result so the
        # audit trail surfaces it.
        try:
            await self._notify_operator(db_session=db_session, event=event)
            evidence.append("operator_alert.maintenance_sent")
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[MaintenanceModule] operator alert send failed (non-blocking): %s", exc,
            )
            result["operator_alert_error"] = f"{type(exc).__name__}: {exc}"

        return ModuleResponse(
            event_id=event.event_id,
            module="maintenance",
            success=True,
            result=result,
            evidence_used=evidence,
        )

    # ── Shadow ──────────────────────────────────────────────────────────────

    def _shadow_response(self, event: ModuleEvent) -> ModuleResponse:
        category = (event.payload or {}).get("category", "unknown")
        severity = (event.payload or {}).get("severity", "medium")
        return ModuleResponse(
            event_id=event.event_id,
            module="maintenance",
            success=True,
            result={
                "shadow": True,
                "would_have_created_concierge_event": True,
                "would_have_created_work_order": True,
                "would_have_workflow_type": _WORKFLOW_TYPE,
                "would_have_workflow_ref": (
                    (event.payload or {}).get("source_message_id")
                    or event.event_id
                ),
                "category": category,
                "severity": severity,
                "issue_summary_preview": self._format_summary(event)[:120],
            },
            evidence_used=[],
        )

    # ── Concierge event ────────────────────────────────────────────────────

    async def _write_concierge_event(
        self,
        db_session: Any,
        event: ModuleEvent,
    ) -> dict[str, Any]:
        """Write to concierge_maintenance_events via the existing service.

        The service handles dedupe (72-hour window per property) and
        severity classification internally — we just hand it the text.
        """
        service = get_concierge_maintenance_service()
        tenant_uuid = UUID(event.tenant_id)

        property_uuid = _try_uuid(event.property_id)
        property_external_id = (event.payload or {}).get("property_code") or None
        issue_text = (event.payload or {}).get("issue_summary") or ""

        outcome = await service.auto_track_from_message(
            session=db_session,
            tenant_id=tenant_uuid,
            message_text=issue_text,
            property_id=property_uuid,
            property_external_id=property_external_id,
            reservation_id=event.reservation_id or None,
        )
        return outcome or {}

    # ── Work order ─────────────────────────────────────────────────────────

    async def _write_work_order(
        self,
        db_session: Any,
        event: ModuleEvent,
        concierge_event_id: Optional[str],
    ) -> dict[str, Any]:
        """Write to operator_work_orders via the existing service.

        Idempotent on (tenant_id, workflow_type, workflow_ref). Re-running
        on the same source message updates the existing row instead of
        creating a duplicate.
        """
        service = get_operator_work_order_service()
        payload = event.payload or {}

        # workflow_ref is the brain's stable per-message ID. Using the
        # source message ID (Twilio MessageSid, email Message-ID, etc.)
        # means retries on the same inbound message → same work order.
        workflow_ref = payload.get("source_message_id") or event.event_id

        # Build the linking payload. The concierge_event_id field is the
        # explicit link to the concierge tracking row.
        wo_payload: dict[str, Any] = {
            "module_event_id": event.event_id,
            "concierge_event_id": concierge_event_id,
            "category": payload.get("category"),
            "guest_id": event.guest_id,
            "guest_phone": payload.get("guest_phone"),
            "guest_name": payload.get("guest_name"),
            "reservation_id": event.reservation_id,
            "source_channel": payload.get("source_channel"),
            "source_message_id": payload.get("source_message_id"),
        }

        priority = payload.get("severity", "medium")  # high|medium|low
        property_code = payload.get("property_code") or None

        return await service.create_or_refresh_work_order(
            db_session,
            tenant_id=event.tenant_id,
            workflow_type=_WORKFLOW_TYPE,
            workflow_ref=workflow_ref,
            property_code=property_code,
            issue_category="maintenance",
            priority=priority,
            summary=self._format_summary(event),
            details=payload.get("issue_summary", ""),
            dispatch_state="opened",
            last_actor_label="messaging_brain",
            payload=wo_payload,
        )

    # ── Operator notification ────────────────────────────────────────────────

    async def _notify_operator(
        self,
        *,
        db_session: Any,
        event: ModuleEvent,
    ) -> None:
        """Send a maintenance alert to the operator via OperatorAlertRouter.

        Notify-only model: every confirmed maintenance issue sends an alert.
        Autonomous vendor dispatch is a future feature gated on per-property
        opt-in; until then, this notification is the operator's action signal.

        Raises on failure — the caller (handle_event) catches and logs so
        notification failure is non-blocking relative to module success.
        """
        payload = event.payload or {}
        severity = str(payload.get("severity", "medium")).lower()
        # Severity shapes the message prefix (urgent vs. standard maintenance).
        priority = "urgent" if severity == "high" else "high"
        message = format_maintenance_alert(
            guest_name=payload.get("guest_name") or "Guest",
            property_name=payload.get("property_code") or "the property",
            property_code=payload.get("property_code") or "",
            issue_description=(
                payload.get("issue_summary") or self._format_summary(event)
            ),
            priority=priority,
            session_url=None,
        )
        router = get_alert_router(db=db_session)
        await router.send_alert(
            company_id=event.tenant_id,
            alert_type=AlertType.MAINTENANCE,
            message=message,
            property_code=payload.get("property_code") or None,
            alert_id=f"maint_{event.event_id}",
        )

    # ── Helpers ─────────────────────────────────────────────────────────────

    @staticmethod
    def _format_summary(event: ModuleEvent) -> str:
        """One-line operator-facing summary for the work order list view.

        Format: "{CATEGORY} issue ({severity}) — guest reported via {channel}"
        Examples:
          "HVAC issue (medium) — guest reported via sms"
          "PLUMBING issue (high) — guest reported via email"
        """
        payload = event.payload or {}
        category = str(payload.get("category", "general")).upper()
        severity = str(payload.get("severity", "medium")).lower()
        channel = str(payload.get("source_channel", "unknown")).lower()
        return f"{category} issue ({severity}) — guest reported via {channel}"


# Re-export the classifiers so the MaintenanceAgent (built next chunk) can
# import them from one place. Keeps the "we are intentionally reusing
# private helpers from concierge/maintenance_service" comment in one file.
__all__ = [
    "MaintenanceModule",
    "_category_for",
    "_severity_for",
]
