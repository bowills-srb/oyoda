"""
Alert Contact Management API

Endpoints for operator self-service management of alert contacts,
including OOO / vacation mode and escalation chain configuration.

All endpoints require ops auth (X-Ops-Key header).

Routes:
    GET    /alert-contacts                    List all contacts for operator
    POST   /alert-contacts                    Add a new contact
    PATCH  /alert-contacts/{id}               Update contact
    DELETE /alert-contacts/{id}               Remove contact
    POST   /alert-contacts/{id}/ooo           Mark contact OOO until date
    POST   /alert-contacts/{id}/available     Restore contact to available
    GET    /alert-contacts/coverage           Check coverage gaps right now
    GET    /alert-contacts/status             Full status board (who's available, who's OOO)
"""

import logging
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.ops_auth import require_ops_access as require_ops_auth
from app.db.session import get_async_session
from app.services.messaging.operator_alerts import (
    AlertType,
    get_alert_router,
    ESCALATION_TIMEOUTS,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/alert-contacts", tags=["Alert Contacts"])


# =============================================================================
# REQUEST / RESPONSE MODELS
# =============================================================================

class AlertContactCreate(BaseModel):
    company_id: str
    alert_type: AlertType = AlertType.GENERAL
    property_code: Optional[str] = None
    contact_name: str
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None
    is_primary: bool = True
    escalation_order: int = 1
    escalation_timeout_minutes: Optional[int] = None
    active_hours_start: Optional[str] = None   # "07:00"
    active_hours_end: Optional[str] = None     # "21:00"
    notes: Optional[str] = None


class AlertContactUpdate(BaseModel):
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None
    alert_type: Optional[AlertType] = None
    property_code: Optional[str] = None
    is_primary: Optional[bool] = None
    escalation_order: Optional[int] = None
    escalation_timeout_minutes: Optional[int] = None
    active_hours_start: Optional[str] = None
    active_hours_end: Optional[str] = None
    notes: Optional[str] = None


class OOORequest(BaseModel):
    unavailable_until: datetime = Field(
        description="UTC datetime when this contact returns. Auto-restores at this time."
    )
    redirect_to_id: Optional[str] = Field(
        default=None,
        description="Optional: redirect all this contact's alerts to another contact while OOO."
    )
    reason: Optional[str] = Field(
        default="vacation",
        description="Internal note (vacation, sick, parental leave, etc.)"
    )


class ContactStatusResponse(BaseModel):
    id: str
    contact_name: str
    contact_phone: Optional[str]
    alert_type: str
    property_code: Optional[str]
    escalation_order: int
    is_available: bool
    unavailable_until: Optional[datetime]
    redirect_to_id: Optional[str]
    status_label: str          # "Available", "OOO until Mar 24", "Outside hours"
    active_hours: Optional[str]


class CoverageCheckResponse(BaseModel):
    alert_type: str
    has_coverage: bool
    available_contacts: List[str]
    ooo_contacts: List[str]
    gap_details: Optional[str]


# =============================================================================
# HELPERS
# =============================================================================

async def _get_company_id(db: AsyncSession, ops_key: str) -> Optional[str]:
    """Resolve company_id from ops auth key. Simplified for now."""
    # In production: look up company from API key table
    # For now: accept company_id from request header or first active company
    from sqlalchemy import text
    try:
        result = await db.execute(text("SELECT id FROM companies LIMIT 1"))
        row = result.fetchone()
        return str(row.id) if row else None
    except Exception:
        return None


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get("/status")
async def get_contact_status(
    company_id: str,
    db: AsyncSession = Depends(get_async_session),
    _=Depends(require_ops_auth),
):
    """
    Full status board: every contact, their availability, OOO status,
    redirect target if set. Use this to drive the Settings → Alert Routing UI.
    """
    from sqlalchemy import text

    rows = await db.execute(
        text("""
            SELECT
                c.id::text, c.contact_name, c.contact_phone, c.contact_email,
                c.alert_type, c.property_code, c.escalation_order, c.is_primary,
                c.is_available, c.unavailable_until, c.redirect_to_id::text,
                c.active_hours_start, c.active_hours_end, c.notes,
                r.contact_name AS redirect_name
            FROM operator_alert_contacts c
            LEFT JOIN operator_alert_contacts r ON r.id = c.redirect_to_id
            WHERE c.company_id = :cid
            ORDER BY c.alert_type, c.escalation_order, c.contact_name
        """),
        {"cid": company_id},
    )

    contacts = []
    for row in rows.fetchall():
        # Auto-expire OOO if past
        is_available = row.is_available
        unavailable_until = row.unavailable_until
        if not is_available and unavailable_until and datetime.utcnow() >= unavailable_until:
            is_available = True
            unavailable_until = None

        if not is_available and unavailable_until:
            status_label = f"OOO until {unavailable_until.strftime('%b %d, %I:%M %p')} UTC"
        elif not is_available:
            status_label = "Unavailable"
        elif row.active_hours_start and row.active_hours_end:
            status_label = f"Active {row.active_hours_start}–{row.active_hours_end}"
        else:
            status_label = "Available 24/7"

        contacts.append({
            "id": row.id,
            "contact_name": row.contact_name,
            "contact_phone": row.contact_phone,
            "contact_email": row.contact_email,
            "alert_type": row.alert_type,
            "property_code": row.property_code,
            "escalation_order": row.escalation_order,
            "is_primary": row.is_primary,
            "is_available": is_available,
            "unavailable_until": unavailable_until.isoformat() if unavailable_until else None,
            "redirect_to_id": row.redirect_to_id,
            "redirect_name": row.redirect_name,
            "status_label": status_label,
            "active_hours": (
                f"{row.active_hours_start}–{row.active_hours_end}"
                if row.active_hours_start else "24/7"
            ),
            "notes": row.notes,
        })

    return {"company_id": company_id, "contacts": contacts, "total": len(contacts)}


@router.get("/coverage")
async def check_coverage(
    company_id: str,
    db: AsyncSession = Depends(get_async_session),
    _=Depends(require_ops_auth),
):
    """
    Check right now whether each alert type has at least one available contact.
    Returns gaps so operator knows before a real alert fires.
    """
    router_svc = get_alert_router(db=db)
    results = []

    for alert_type in AlertType:
        available, skipped = await router_svc.get_recipients(
            company_id=company_id,
            alert_type=alert_type,
        )
        results.append({
            "alert_type": alert_type.value,
            "has_coverage": len(available) > 0,
            "available_count": len(available),
            "available_contacts": [c.contact_name for c in available],
            "ooo_contacts": [
                f"{c.contact_name} ({c.availability_reason()})"
                for c in skipped
            ],
            "escalation_timeout_minutes": ESCALATION_TIMEOUTS.get(alert_type, 30),
            "gap_details": (
                f"No available contacts — alerts will go to Oyvoda ops fallback"
                if not available else None
            ),
        })

    gaps = [r for r in results if not r["has_coverage"]]
    return {
        "company_id": company_id,
        "checked_at": datetime.utcnow().isoformat(),
        "all_covered": len(gaps) == 0,
        "gap_count": len(gaps),
        "coverage": results,
    }


@router.post("/{contact_id}/ooo")
async def mark_contact_ooo(
    contact_id: str,
    request: OOORequest,
    company_id: str,
    db: AsyncSession = Depends(get_async_session),
    _=Depends(require_ops_auth),
):
    """
    Mark a contact as OOO until a specific datetime.

    - Sets is_available = FALSE on the contact
    - Optionally sets redirect_to_id (all alerts reroute to that contact)
    - Celery beat (restore_expired_ooo) auto-restores at unavailable_until

    Example request:
        POST /alert-contacts/abc-123/ooo
        {
            "unavailable_until": "2026-03-28T12:00:00Z",
            "redirect_to_id": "def-456",
            "reason": "Spring break vacation"
        }
    """
    alert_router = get_alert_router(db=db)
    success = await alert_router.mark_ooo(
        contact_id=contact_id,
        company_id=company_id,
        unavailable_until=request.unavailable_until,
        redirect_to_id=request.redirect_to_id,
        marked_by=f"operator ({reason_str(request.reason)})",
    )
    if not success:
        raise HTTPException(status_code=404, detail="Contact not found or update failed")

    return {
        "contact_id": contact_id,
        "status": "ooo",
        "unavailable_until": request.unavailable_until.isoformat(),
        "redirect_to_id": request.redirect_to_id,
        "auto_restores_at": request.unavailable_until.isoformat(),
        "message": (
            f"Contact marked OOO until {request.unavailable_until.strftime('%b %d %Y %I:%M %p')} UTC. "
            + (f"Alerts redirected to contact {request.redirect_to_id}." if request.redirect_to_id
               else "Alerts will escalate to next contact in chain.")
        ),
    }


@router.post("/{contact_id}/available")
async def mark_contact_available(
    contact_id: str,
    company_id: str,
    db: AsyncSession = Depends(get_async_session),
    _=Depends(require_ops_auth),
):
    """
    Manually restore a contact to available (early return from vacation).
    Clears OOO flag and redirect immediately.
    """
    alert_router = get_alert_router(db=db)
    success = await alert_router.mark_available(
        contact_id=contact_id,
        company_id=company_id,
    )
    if not success:
        raise HTTPException(status_code=404, detail="Contact not found or update failed")

    return {
        "contact_id": contact_id,
        "status": "available",
        "message": "Contact restored to available. Will receive alerts immediately.",
    }


@router.post("")
async def create_contact(
    data: AlertContactCreate,
    db: AsyncSession = Depends(get_async_session),
    _=Depends(require_ops_auth),
):
    """Add a new alert contact for an operator."""
    from sqlalchemy import text
    import uuid as _uuid
    from datetime import time as _time

    def parse_time(t: Optional[str]):
        if not t:
            return None
        h, m = t.split(":")
        return _time(int(h), int(m))

    timeout = data.escalation_timeout_minutes or ESCALATION_TIMEOUTS.get(data.alert_type, 30)

    contact_id = str(_uuid.uuid4())
    await db.execute(
        text("""
            INSERT INTO operator_alert_contacts
                (id, company_id, alert_type, property_code, contact_name,
                 contact_phone, contact_email, is_primary, escalation_order,
                 escalation_timeout_minutes, active_hours_start, active_hours_end,
                 is_available, notes, created_at, updated_at)
            VALUES
                (:id, :cid, :atype, :prop, :name,
                 :phone, :email, :primary, :order,
                 :timeout, :start, :end,
                 TRUE, :notes, NOW(), NOW())
        """),
        {
            "id": contact_id,
            "cid": data.company_id,
            "atype": data.alert_type.value,
            "prop": data.property_code,
            "name": data.contact_name,
            "phone": data.contact_phone,
            "email": data.contact_email,
            "primary": data.is_primary,
            "order": data.escalation_order,
            "timeout": timeout,
            "start": parse_time(data.active_hours_start),
            "end": parse_time(data.active_hours_end),
            "notes": data.notes,
        },
    )
    await db.commit()

    return {"contact_id": contact_id, "status": "created"}


@router.delete("/{contact_id}")
async def delete_contact(
    contact_id: str,
    company_id: str,
    db: AsyncSession = Depends(get_async_session),
    _=Depends(require_ops_auth),
):
    """Remove an alert contact."""
    from sqlalchemy import text
    result = await db.execute(
        text("""
            DELETE FROM operator_alert_contacts
            WHERE id = :cid AND company_id = :company
            RETURNING id
        """),
        {"cid": contact_id, "company": company_id},
    )
    if not result.fetchone():
        raise HTTPException(status_code=404, detail="Contact not found")
    await db.commit()
    return {"contact_id": contact_id, "status": "deleted"}


# =============================================================================
# HELPERS
# =============================================================================

def reason_str(reason: Optional[str]) -> str:
    return reason or "vacation"
