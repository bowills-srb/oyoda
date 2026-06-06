"""
PRESERVATION STATUS (post-Phase-1, 2026-05-23):
This module is preserved for future product surface (pre-arrival,
in-stay, multi-guest, returning-guest personalization, BD-aware
messaging, etc.). It is not currently part of the active brain
runtime path. Do not delete in subsequent phases unless explicitly
retired by product decision.

When the relevant product surface is wired into the brain, this
module relocates to the appropriate messaging_brain/ subdirectory
and stops being marked as preserved.

Concierge maintenance event tracking service.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
import re
import smtplib
from email.message import EmailMessage
from typing import Any, Dict, List, Optional
from uuid import UUID
from urllib import error, request as urlrequest

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.concierge_knowledge import ConciergeMaintenanceEventModel


MAINTENANCE_KEYWORDS = {
    "bike": "bike",
    "bicycle": "bike",
    "dishwasher": "appliance",
    "washer": "appliance",
    "dryer": "appliance",
    "ac": "hvac",
    "a/c": "hvac",
    "air conditioning": "hvac",
    "heat": "hvac",
    "plumb": "plumbing",
    "leak": "plumbing",
    "toilet": "plumbing",
    "sink": "plumbing",
    "door": "access",
    "lock": "access",
    "keypad": "access",
    "wifi": "internet",
    "internet": "internet",
    "tv": "electronics",
    "broken": "general",
    "not working": "general",
    "issue": "general",
    "problem": "general",
}

RESOLUTION_HINTS = (
    "fixed",
    "resolved",
    "works now",
    "working now",
    "all set now",
    "no longer",
    "taken care",
    "addressed",
    "completed",
    "complete",
    "thanks for fixing",
)

ESCALATION_HINTS = (
    "urgent",
    "asap",
    "safety",
    "danger",
    "hazard",
    "flood",
    "gas",
    "fire",
    "smoke",
    "no heat",
    "no ac",
)


def _load_routing_rules() -> Dict[str, Any]:
    raw = os.getenv("CONCIERGE_MAINTENANCE_ROUTING_JSON", "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def _normalize_tokens(text: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def _has_keyword(text: str, keyword: str) -> bool:
    lowered = (text or "").lower()
    if " " in keyword:
        return keyword in lowered
    tokens = set(_normalize_tokens(lowered))
    return keyword in tokens


def _issue_key(text: str) -> str:
    tokens = sorted({t for t in _normalize_tokens(text) if len(t) > 2})
    return " ".join(tokens)[:500]


def _is_maintenance_message(text: str) -> bool:
    return any(_has_keyword(text, k) for k in MAINTENANCE_KEYWORDS.keys())


def _is_resolution_message(text: str) -> bool:
    lowered = (text or "").lower()
    return any(h in lowered for h in RESOLUTION_HINTS)


def _category_for(text: str) -> str:
    for key, category in MAINTENANCE_KEYWORDS.items():
        if _has_keyword(text, key):
            return category
    return "general"


def _severity_for(text: str) -> str:
    lowered = (text or "").lower()
    if any(h in lowered for h in ESCALATION_HINTS):
        return "high"
    if any(k in lowered for k in ("broken", "not working", "leak", "issue", "problem")):
        return "medium"
    return "low"


class ConciergeMaintenanceService:
    """CRUD and auto-detection for maintenance events."""

    async def create_event(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        issue_text: str,
        property_id: Optional[UUID] = None,
        property_external_id: Optional[str] = None,
        reservation_id: Optional[str] = None,
        source: str = "concierge_auto",
        notes: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        dedupe_window_hours: int = 72,
    ) -> Dict[str, Any]:
        text = issue_text.strip()
        key = _issue_key(text)
        if not key:
            raise ValueError("issue_text must contain meaningful content")

        cutoff = datetime.now(timezone.utc) - timedelta(hours=max(1, dedupe_window_hours))
        stmt = (
            select(ConciergeMaintenanceEventModel)
            .where(
                ConciergeMaintenanceEventModel.tenant_id == tenant_id,
                ConciergeMaintenanceEventModel.status == "open",
                ConciergeMaintenanceEventModel.updated_at >= cutoff,
            )
            .order_by(ConciergeMaintenanceEventModel.updated_at.desc())
            .limit(150)
        )
        recent = list((await session.execute(stmt)).scalars())
        for existing in recent:
            same_property = False
            if property_id and existing.property_id == property_id:
                same_property = True
            elif property_external_id and existing.property_external_id == property_external_id:
                same_property = True
            if not same_property:
                continue
            if existing.issue_key == key:
                return self._serialize(existing, deduped=True, duplicate_of_event_id=str(existing.event_id))

        severity = _severity_for(text)
        escalation_status = "pending" if severity == "high" else "none"
        category = _category_for(text)
        assigned_to = self._route_assignee(category=category, property_external_id=property_external_id)
        if assigned_to and escalation_status == "none":
            escalation_status = "assigned"
        event = ConciergeMaintenanceEventModel(
            tenant_id=tenant_id,
            property_id=property_id,
            property_external_id=property_external_id,
            issue_text=text,
            issue_key=key,
            category=category,
            severity=severity,
            source=source,
            status="open",
            escalation_status=escalation_status,
            assigned_to=assigned_to,
            reservation_id=reservation_id,
            notes=notes,
            metadata_json=metadata or {},
        )
        session.add(event)
        await session.commit()
        await session.refresh(event)
        self._notify(event)
        return self._serialize(event, deduped=False, duplicate_of_event_id=None)

    async def resolve_event(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        event_id: UUID,
        notes: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        row = (
            await session.execute(
                select(ConciergeMaintenanceEventModel).where(
                    ConciergeMaintenanceEventModel.tenant_id == tenant_id,
                    ConciergeMaintenanceEventModel.event_id == event_id,
                )
            )
        ).scalar_one_or_none()
        if not row:
            return None
        row.status = "resolved"
        row.resolved_at = datetime.now(timezone.utc)
        row.escalation_status = "none"
        if notes:
            row.notes = notes
        await session.commit()
        await session.refresh(row)
        return self._serialize(row)

    async def resolve_latest_for_property(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        resolution_text: str,
        property_id: Optional[UUID] = None,
        property_external_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        stmt = select(ConciergeMaintenanceEventModel).where(
            ConciergeMaintenanceEventModel.tenant_id == tenant_id,
            ConciergeMaintenanceEventModel.status == "open",
        )
        if property_id:
            stmt = stmt.where(ConciergeMaintenanceEventModel.property_id == property_id)
        elif property_external_id:
            stmt = stmt.where(ConciergeMaintenanceEventModel.property_external_id == property_external_id)
        stmt = stmt.order_by(ConciergeMaintenanceEventModel.updated_at.desc()).limit(1)
        row = (await session.execute(stmt)).scalar_one_or_none()
        if not row:
            return None
        row.status = "resolved"
        row.resolved_at = datetime.now(timezone.utc)
        row.escalation_status = "none"
        row.notes = resolution_text
        await session.commit()
        await session.refresh(row)
        return self._serialize(row)

    async def list_events(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        status: str = "open",
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        stmt = select(ConciergeMaintenanceEventModel).where(
            ConciergeMaintenanceEventModel.tenant_id == tenant_id
        )
        if status != "all":
            stmt = stmt.where(ConciergeMaintenanceEventModel.status == status)
        stmt = stmt.order_by(ConciergeMaintenanceEventModel.updated_at.desc()).limit(max(1, min(limit, 500)))
        rows = list((await session.execute(stmt)).scalars())
        return [self._serialize(r) for r in rows]

    async def auto_track_from_message(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        message_text: str,
        property_id: Optional[UUID] = None,
        property_external_id: Optional[str] = None,
        reservation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        text = (message_text or "").strip()
        if not text:
            return {"created": None, "resolved": None}

        if _is_resolution_message(text):
            resolved = await self.resolve_latest_for_property(
                session=session,
                tenant_id=tenant_id,
                resolution_text=text,
                property_id=property_id,
                property_external_id=property_external_id,
            )
            return {"created": None, "resolved": resolved}

        if not _is_maintenance_message(text):
            return {"created": None, "resolved": None}

        created = await self.create_event(
            session=session,
            tenant_id=tenant_id,
            issue_text=text,
            property_id=property_id,
            property_external_id=property_external_id,
            reservation_id=reservation_id,
            source="concierge_auto",
            metadata={"auto_tracked": True},
        )
        return {"created": created, "resolved": None}

    def _serialize(
        self,
        row: ConciergeMaintenanceEventModel,
        deduped: bool = False,
        duplicate_of_event_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        return {
            "event_id": str(row.event_id),
            "tenant_id": str(row.tenant_id),
            "property_id": str(row.property_id) if row.property_id else None,
            "property_external_id": row.property_external_id,
            "issue_text": row.issue_text,
            "category": row.category,
            "severity": row.severity,
            "source": row.source,
            "status": row.status,
            "escalation_status": row.escalation_status,
            "assigned_to": row.assigned_to,
            "reservation_id": row.reservation_id,
            "notes": row.notes,
            "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
            "created_at": row.created_at.isoformat(),
            "updated_at": row.updated_at.isoformat(),
            "deduped": deduped,
            "duplicate_of_event_id": duplicate_of_event_id,
        }

    def _route_assignee(self, category: str, property_external_id: Optional[str]) -> Optional[str]:
        rules = _load_routing_rules()
        if not rules:
            return None

        by_property = rules.get("by_property") or {}
        if property_external_id and property_external_id in by_property:
            scoped = by_property[property_external_id]
            if isinstance(scoped, dict):
                if category in scoped:
                    return str(scoped[category])
                if "default" in scoped:
                    return str(scoped["default"])
            elif isinstance(scoped, str):
                return scoped

        by_category = rules.get("by_category") or {}
        if category in by_category:
            return str(by_category[category])

        default = rules.get("default_assignee")
        return str(default) if default else None

    def _notify(self, event: ConciergeMaintenanceEventModel) -> None:
        if event.severity != "high":
            return
        self._notify_webhook(event)
        self._notify_email(event)

    def _notify_webhook(self, event: ConciergeMaintenanceEventModel) -> None:
        webhook_url = os.getenv("CONCIERGE_MAINTENANCE_WEBHOOK_URL", "").strip()
        if not webhook_url:
            return
        payload = {
            "event": "maintenance.high_severity.created",
            "event_id": str(event.event_id),
            "tenant_id": str(event.tenant_id),
            "property_external_id": event.property_external_id,
            "category": event.category,
            "severity": event.severity,
            "issue_text": event.issue_text,
            "assigned_to": event.assigned_to,
            "escalation_status": event.escalation_status,
            "created_at": event.created_at.isoformat(),
        }
        req = urlrequest.Request(
            url=webhook_url,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urlrequest.urlopen(req, timeout=5):
                return
        except Exception:
            return

    def _notify_email(self, event: ConciergeMaintenanceEventModel) -> None:
        to_raw = os.getenv("CONCIERGE_MAINTENANCE_ALERT_EMAILS", "").strip()
        if not to_raw:
            return
        smtp_host = os.getenv("SMTP_HOST", "").strip()
        smtp_port = int(os.getenv("SMTP_PORT", "587"))
        smtp_user = os.getenv("SMTP_USER", "").strip()
        smtp_password = os.getenv("SMTP_PASSWORD", "").strip()
        smtp_sender = os.getenv("SMTP_SENDER", smtp_user).strip()
        if not smtp_host or not smtp_sender:
            return
        recipients = [x.strip() for x in to_raw.split(",") if x.strip()]
        if not recipients:
            return

        msg = EmailMessage()
        msg["Subject"] = f"[Maintenance][HIGH] {event.property_external_id or 'unknown property'} - {event.category}"
        msg["From"] = smtp_sender
        msg["To"] = ", ".join(recipients)
        msg.set_content(
            "\n".join(
                [
                    "High-severity maintenance event created.",
                    f"Event ID: {event.event_id}",
                    f"Property: {event.property_external_id}",
                    f"Category: {event.category}",
                    f"Issue: {event.issue_text}",
                    f"Assigned To: {event.assigned_to}",
                    f"Created At: {event.created_at.isoformat()}",
                ]
            )
        )
        try:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
                server.starttls()
                if smtp_user:
                    server.login(smtp_user, smtp_password)
                server.send_message(msg)
        except Exception:
            return


_service: ConciergeMaintenanceService | None = None


def get_concierge_maintenance_service() -> ConciergeMaintenanceService:
    global _service
    if _service is None:
        _service = ConciergeMaintenanceService()
    return _service
