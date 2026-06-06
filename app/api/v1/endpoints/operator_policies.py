"""Tenant-scoped operator policy authoring API."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.ops_auth import require_ops_access
from app.api.dependencies.request_tenant import resolve_request_tenant_id
from app.db.session import get_async_session
from app.services.operator_policies.discount_rules import (
    ValidationError,
    default_operator_policies,
    normalize_operator_policies,
    validate_discount_policies,
)

router = APIRouter(
    prefix="/operator-policies",
    tags=["Operator Policies"],
    dependencies=[Depends(require_ops_access)],
)


class PolicyPatch(BaseModel):
    check_in_time: Optional[str] = None
    check_out_time: Optional[str] = None
    late_checkout_available: Optional[bool] = None
    late_checkout_max_time: Optional[str] = None
    late_checkout_fee: Optional[float] = None
    late_checkout_requires_approval: Optional[bool] = None
    early_checkin_available: Optional[bool] = None
    early_checkin_earliest: Optional[str] = None
    early_checkin_fee: Optional[float] = None
    early_checkin_subject_to_availability: Optional[bool] = None
    cancellation_full_refund_days: Optional[int] = None
    cancellation_partial_refund_days: Optional[int] = None
    cancellation_partial_refund_percent: Optional[int] = Field(default=None, ge=0, le=100)
    pets_allowed: Optional[str] = None
    pet_fee: Optional[float] = None
    pet_max_weight: Optional[int] = None
    pet_restricted_breeds: Optional[List[str]] = None
    pet_notes: Optional[str] = None
    pool_heat_available: Optional[bool] = None
    pool_heat_daily_fee: Optional[float] = None
    pool_heat_advance_notice_hours: Optional[int] = None
    beach_chairs_included: Optional[bool] = None
    beach_chair_rental_partners: Optional[List[Dict[str, Any]]] = None
    discount_policies: Optional[Dict[str, Any]] = None
    additional_policies: Optional[Dict[str, Any]] = None
    support_phone: Optional[str] = None
    support_email: Optional[str] = None
    emergency_phone: Optional[str] = None


def _tenant_id_or_401(request: Request) -> str:
    tenant_id = resolve_request_tenant_id(request)
    if not tenant_id:
        raise HTTPException(status_code=401, detail="tenant context required")
    return str(tenant_id)


@router.get("")
async def get_policies(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
) -> Dict[str, Any]:
    tenant_id = _tenant_id_or_401(request)
    row = (
        await db.execute(
            text(
                """
                SELECT
                    tenant_id,
                    check_in_time,
                    check_out_time,
                    late_checkout_available,
                    late_checkout_max_time,
                    late_checkout_fee,
                    late_checkout_requires_approval,
                    early_checkin_available,
                    early_checkin_earliest,
                    early_checkin_fee,
                    early_checkin_subject_to_availability,
                    cancellation_full_refund_days,
                    cancellation_partial_refund_days,
                    cancellation_partial_refund_percent,
                    pets_allowed,
                    pet_fee,
                    pet_max_weight,
                    pet_restricted_breeds,
                    pet_notes,
                    pool_heat_available,
                    pool_heat_daily_fee,
                    pool_heat_advance_notice_hours,
                    beach_chairs_included,
                    beach_chair_rental_partners,
                    discount_policies,
                    additional_policies,
                    support_phone,
                    support_email,
                    emergency_phone
                FROM operator_policies
                WHERE tenant_id = CAST(:tid AS uuid)
                LIMIT 1
                """
            ),
            {"tid": tenant_id},
        )
    ).mappings().first()

    if not row:
        return {
            "tenant_id": tenant_id,
            "exists": False,
            "policies": default_operator_policies(),
        }

    return {
        "tenant_id": tenant_id,
        "exists": True,
        "policies": normalize_operator_policies(dict(row)),
    }


@router.patch("")
async def patch_policies(
    patch: PolicyPatch,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
) -> Dict[str, Any]:
    tenant_id = _tenant_id_or_401(request)
    updates = patch.model_dump(exclude_unset=True)

    if "discount_policies" in updates:
        try:
            updates["discount_policies"] = validate_discount_policies(updates["discount_policies"])
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=exc.errors()) from exc

    if "pets_allowed" in updates and updates["pets_allowed"] is not None:
        allowed = str(updates["pets_allowed"]).strip().lower()
        if allowed not in {"no", "yes", "some_properties"}:
            raise HTTPException(status_code=422, detail="pets_allowed must be no, yes, or some_properties")
        updates["pets_allowed"] = allowed

    if "pet_restricted_breeds" in updates and updates["pet_restricted_breeds"] is None:
        updates["pet_restricted_breeds"] = []
    if "beach_chair_rental_partners" in updates and updates["beach_chair_rental_partners"] is None:
        updates["beach_chair_rental_partners"] = []
    if "additional_policies" in updates and updates["additional_policies"] is None:
        updates["additional_policies"] = {}

    if updates:
        ordered_keys = list(updates.keys())
        insert_cols = ", ".join(["id", "tenant_id", *ordered_keys, "created_at", "updated_at"])
        insert_vals = ", ".join(["gen_random_uuid()", "CAST(:tid AS uuid)", *(f":{key}" for key in ordered_keys), "NOW()", "NOW()"])
        set_clause = ", ".join(f"{key} = EXCLUDED.{key}" for key in ordered_keys)
        await db.execute(
            text(
                f"""
                INSERT INTO operator_policies ({insert_cols})
                VALUES ({insert_vals})
                ON CONFLICT (tenant_id) WHERE tenant_id IS NOT NULL DO UPDATE
                SET {set_clause}, updated_at = NOW()
                """
            ),
            {"tid": tenant_id, **updates},
        )
    else:
        await db.execute(
            text(
                """
                INSERT INTO operator_policies (id, tenant_id, created_at, updated_at)
                VALUES (gen_random_uuid(), CAST(:tid AS uuid), NOW(), NOW())
                ON CONFLICT (tenant_id) WHERE tenant_id IS NOT NULL DO NOTHING
                """
            ),
            {"tid": tenant_id},
        )

    await db.commit()
    return await get_policies(request, db)
