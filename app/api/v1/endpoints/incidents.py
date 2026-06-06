"""
Property Incidents API

Endpoints for the Incidents panel in the operator dashboard.
Reads from the property_incidents table created in migration_018.
"""

import logging
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.api.dependencies.ops_auth import require_ops_access
from app.api.dependencies.request_tenant import resolve_request_tenant_id
from app.db.session import get_async_session
from app.services.identity.dual_write import (
    IdentityResolutionError,
    resolve_dual_write_identity,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/incidents", tags=["Incidents"])


def _resolve_request_tenant_id(request: Request) -> UUID:
    tenant_id = resolve_request_tenant_id(request)
    if tenant_id is None:
        raise HTTPException(status_code=403, detail="Tenant context required")
    return tenant_id


class IncidentCreate(BaseModel):
    company_id: str
    property_external_id: str
    property_name: Optional[str] = None
    incident_type: str = "maintenance"
    priority: str = "medium"
    title: str
    description: Optional[str] = None
    guest_name: Optional[str] = None
    guest_phone: Optional[str] = None
    compensation_requested: bool = False
    compensation_amount: Optional[float] = None
    compensation_type: Optional[str] = None
    compensation_notes: Optional[str] = None
    vendor_name: Optional[str] = None
    vendor_eta_minutes: Optional[int] = None
    operator_notes: Optional[str] = None


class IncidentUpdate(BaseModel):
    status: Optional[str] = None
    priority: Optional[str] = None
    operator_notes: Optional[str] = None
    vendor_name: Optional[str] = None
    vendor_eta_minutes: Optional[int] = None
    compensation_requested: Optional[bool] = None
    compensation_amount: Optional[float] = None
    compensation_type: Optional[str] = None
    compensation_notes: Optional[str] = None
    compensation_approved_by: Optional[str] = None
    resolution_summary: Optional[str] = None


@router.get("")
async def list_incidents(
    company_id: str = Query(...),
    status: Optional[str] = Query(default=None),
    property_id: Optional[str] = Query(default=None),
    limit: int = Query(default=50, le=200),
    db: AsyncSession = Depends(get_async_session),
):
    """List incidents for an operator, optionally filtered by status or property."""
    try:
        where_clauses = ["company_id = :cid::uuid"]
        params: dict = {"cid": company_id, "limit": limit}

        if status:
            where_clauses.append("status = :status")
            params["status"] = status
        if property_id:
            where_clauses.append("property_external_id = :prop")
            params["prop"] = property_id

        where_sql = " AND ".join(where_clauses)
        rows = (await db.execute(text(f"""
            SELECT
                id::text, company_id::text, property_external_id, property_name,
                incident_type, priority, title, description,
                guest_name, guest_phone,
                compensation_requested, compensation_amount, compensation_type,
                compensation_notes, compensation_approved_by, compensation_approved_at,
                status, vendor_name, vendor_eta_minutes,
                operator_notes, resolution_summary,
                reported_at, created_at, updated_at
            FROM property_incidents
            WHERE {where_sql}
            ORDER BY
                CASE priority WHEN 'urgent' THEN 1 WHEN 'high' THEN 2
                              WHEN 'medium' THEN 3 ELSE 4 END,
                reported_at DESC
            LIMIT :limit
        """), params)).fetchall()

        return {
            "company_id": company_id,
            "count": len(rows),
            "incidents": [_row_to_dict(r) for r in rows],
        }
    except Exception as e:
        logger.warning(f"list_incidents failed: {e}")
        return {"company_id": company_id, "count": 0, "incidents": []}


@router.post("")
async def create_incident(
    data: IncidentCreate,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
    _=Depends(require_ops_access),
):
    """Create a new incident record."""
    import uuid
    incident_id = str(uuid.uuid4())
    try:
        tenant_uuid, company_uuid = resolve_dual_write_identity(
            tenant_id=_resolve_request_tenant_id(request),
            company_id=data.company_id,
            context="incidents.create_incident",
        )
        await db.execute(text("""
            INSERT INTO property_incidents (
                id, tenant_id, company_id, property_external_id, property_name,
                incident_type, priority, title, description,
                guest_name, guest_phone,
                compensation_requested, compensation_amount, compensation_type,
                compensation_notes, vendor_name, vendor_eta_minutes,
                operator_notes, status, reported_at, created_at, updated_at
            ) VALUES (
                :id::uuid, :tid::uuid, :cid::uuid, :prop, :pname,
                :itype, :priority, :title, :desc,
                :gname, :gphone,
                :comp_req, :comp_amt, :comp_type,
                :comp_notes, :vendor, :vendor_eta,
                :notes, 'open', NOW(), NOW(), NOW()
            )
        """), {
            "id": incident_id,
            "tid": str(tenant_uuid),
            "cid": str(company_uuid),
            "prop": data.property_external_id,
            "pname": data.property_name,
            "itype": data.incident_type,
            "priority": data.priority,
            "title": data.title,
            "desc": data.description,
            "gname": data.guest_name,
            "gphone": data.guest_phone,
            "comp_req": data.compensation_requested,
            "comp_amt": data.compensation_amount,
            "comp_type": data.compensation_type,
            "comp_notes": data.compensation_notes,
            "vendor": data.vendor_name,
            "vendor_eta": data.vendor_eta_minutes,
            "notes": data.operator_notes,
        })
        await db.commit()
        return {"incident_id": incident_id, "status": "created"}
    except IdentityResolutionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/{incident_id}")
async def update_incident(
    incident_id: str,
    company_id: str,
    data: IncidentUpdate,
    db: AsyncSession = Depends(get_async_session),
    _=Depends(require_ops_access),
):
    """Update incident status, notes, vendor, or compensation."""
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    if not updates:
        return {"incident_id": incident_id, "status": "no_changes"}

    set_clauses = ", ".join(f"{k} = :{k}" for k in updates)
    updates["incident_id"] = incident_id
    updates["cid"] = company_id

    # Auto-set resolved_at when status becomes resolved
    if updates.get("status") == "resolved":
        set_clauses += ", resolved_at = NOW()"

    try:
        result = await db.execute(text(f"""
            UPDATE property_incidents
            SET {set_clauses}, updated_at = NOW()
            WHERE id = :incident_id::uuid AND company_id = :cid::uuid
            RETURNING id
        """), updates)
        if not result.fetchone():
            raise HTTPException(status_code=404, detail="Incident not found")
        await db.commit()
        return {"incident_id": incident_id, "status": "updated"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/summary")
async def get_incidents_summary(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_async_session),
):
    """Quick summary counts for the dashboard badge."""
    try:
        row = (await db.execute(text("""
            SELECT
                COUNT(*) FILTER (WHERE status IN ('open','acknowledged','in_progress')) AS active,
                COUNT(*) FILTER (WHERE priority = 'urgent' AND status != 'resolved') AS urgent,
                COUNT(*) FILTER (WHERE compensation_requested AND compensation_approved_by IS NULL) AS pending_compensation,
                COUNT(*) AS total_30d
            FROM property_incidents
            WHERE company_id = :cid::uuid
              AND reported_at >= NOW() - INTERVAL '30 days'
        """), {"cid": company_id})).fetchone()

        return {
            "active_count": row.active or 0,
            "urgent_count": row.urgent or 0,
            "pending_compensation": row.pending_compensation or 0,
            "total_30d": row.total_30d or 0,
        }
    except Exception as e:
        logger.warning(f"incidents_summary failed: {e}")
        return {"active_count": 0, "urgent_count": 0, "pending_compensation": 0, "total_30d": 0}


def _row_to_dict(r) -> dict:
    return {
        "id": r.id,
        "company_id": r.company_id,
        "property_external_id": r.property_external_id,
        "property_name": r.property_name,
        "incident_type": r.incident_type,
        "priority": r.priority,
        "title": r.title,
        "description": r.description,
        "guest_name": r.guest_name,
        "guest_phone": r.guest_phone,
        "compensation_requested": r.compensation_requested,
        "compensation_amount": float(r.compensation_amount) if r.compensation_amount else None,
        "compensation_type": r.compensation_type,
        "compensation_notes": r.compensation_notes,
        "compensation_approved_by": r.compensation_approved_by,
        "compensation_approved_at": r.compensation_approved_at.isoformat() if r.compensation_approved_at else None,
        "status": r.status,
        "vendor_name": r.vendor_name,
        "vendor_eta_minutes": r.vendor_eta_minutes,
        "operator_notes": r.operator_notes,
        "resolution_summary": r.resolution_summary,
        "reported_at": r.reported_at.isoformat() if r.reported_at else None,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }
