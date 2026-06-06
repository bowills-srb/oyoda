from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import date
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import text

from app.db.session_safety import safe_rollback

_CACHE_TTL_SECONDS = 60.0
_IDENTITY_CACHE: dict[tuple[Any, ...], tuple[float, "GuestIdentityResolution"]] = {}

_MASKED_EMAIL_PATTERNS = (
    re.compile(r"@reply\.airbnb\.com$", re.I),
    re.compile(r"@supportmessaging\.airbnb\.com$", re.I),
    re.compile(r"@messages\.(homeaway|vrbo)\.com$", re.I),
)


@dataclass(frozen=True)
class GuestIdentityResolution:
    state: str
    reservation_id: str = ""
    session_token: str = ""
    guest_name: str = ""
    guest_email: str = ""
    guest_phone: str = ""
    resolution_source: str = ""
    confidence: float = 0.0
    property_code: str = ""
    check_in_date: str = ""
    check_out_date: str = ""


async def resolve_guest_identity(
    *,
    db: Any,
    tenant_id: UUID | str,
    session_token: str = "",
    guest_email: str = "",
    guest_name: str = "",
    guest_phone: str = "",
    reservation_id: str = "",
    property_code: str = "",
    requested_check_in: Optional[date] = None,
    requested_check_out: Optional[date] = None,
) -> GuestIdentityResolution:
    tenant_value = str(tenant_id)
    cache_key = (
        tenant_value,
        session_token.strip(),
        guest_email.strip().lower(),
        reservation_id.strip(),
        property_code.strip(),
        requested_check_in.isoformat() if requested_check_in else "",
        requested_check_out.isoformat() if requested_check_out else "",
    )
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    identity = await _resolve_guest_identity_uncached(
        db=db,
        tenant_id=tenant_value,
        session_token=session_token,
        guest_email=guest_email,
        guest_name=guest_name,
        guest_phone=guest_phone,
        reservation_id=reservation_id,
        property_code=property_code,
        requested_check_in=requested_check_in,
        requested_check_out=requested_check_out,
    )
    _cache_set(cache_key, identity)
    return identity


def clear_identity_resolution_cache() -> None:
    _IDENTITY_CACHE.clear()


async def _resolve_guest_identity_uncached(
    *,
    db: Any,
    tenant_id: str,
    session_token: str,
    guest_email: str,
    guest_name: str,
    guest_phone: str,
    reservation_id: str,
    property_code: str,
    requested_check_in: Optional[date],
    requested_check_out: Optional[date],
) -> GuestIdentityResolution:
    clean_email = (guest_email or "").strip().lower()
    clean_name = (guest_name or "").strip()
    clean_phone = (guest_phone or "").strip()
    clean_reservation_id = (reservation_id or "").strip()
    clean_property_code = (property_code or "").strip()
    clean_session_token = (session_token or "").strip()

    if db is not None and clean_session_token:
        row = await _lookup_session_by_token(
            db=db,
            tenant_id=tenant_id,
            session_token=clean_session_token,
        )
        if row is not None:
            status = str(row.status or "").strip().lower()
            state = "identified" if status not in {"expired", "closed"} else "linked"
            return GuestIdentityResolution(
                state=state,
                reservation_id=str(row.reservation_id or clean_reservation_id or ""),
                session_token=clean_session_token,
                guest_name=str(row.guest_name or clean_name or ""),
                guest_email=str(row.guest_email or clean_email or ""),
                guest_phone=str(row.guest_phone or clean_phone or ""),
                resolution_source="session_token",
                confidence=0.99 if state == "identified" else 0.85,
                property_code=str(row.property_code or clean_property_code or ""),
                check_in_date=row.check_in.isoformat() if getattr(row, "check_in", None) else "",
                check_out_date=row.check_out.isoformat() if getattr(row, "check_out", None) else "",
            )

    if db is not None:
        row = await _lookup_pms_booking(
            db=db,
            tenant_id=tenant_id,
            guest_email=clean_email,
            reservation_id=clean_reservation_id,
            requested_check_in=requested_check_in,
            requested_check_out=requested_check_out,
        )
        if row is not None:
            resolved_name = " ".join(
                part for part in [str(row.guest_first_name or "").strip(), str(row.guest_last_name or "").strip()] if part
            )
            return GuestIdentityResolution(
                state="linked",
                reservation_id=str(row.external_id or clean_reservation_id or ""),
                session_token="",
                guest_name=resolved_name or clean_name,
                guest_email=str(row.guest_email or clean_email or ""),
                guest_phone=str(row.guest_phone or clean_phone or ""),
                resolution_source="reservation_match",
                confidence=0.90,
                property_code=clean_property_code,
                check_in_date=row.check_in.isoformat() if getattr(row, "check_in", None) else "",
                check_out_date=row.check_out.isoformat() if getattr(row, "check_out", None) else "",
            )

    if _is_masked_ota_email(clean_email):
        return GuestIdentityResolution(
            state="pseudonymous",
            reservation_id=clean_reservation_id,
            session_token="",
            guest_name=clean_name,
            guest_email=clean_email,
            guest_phone=clean_phone,
            resolution_source="ota_masked_email",
            confidence=0.55,
            property_code=clean_property_code,
            check_in_date=requested_check_in.isoformat() if requested_check_in else "",
            check_out_date=requested_check_out.isoformat() if requested_check_out else "",
        )

    return GuestIdentityResolution(
        state="anonymous",
        reservation_id=clean_reservation_id,
        session_token=clean_session_token,
        guest_name=clean_name,
        guest_email=clean_email,
        guest_phone=clean_phone,
        resolution_source="none",
        confidence=0.0,
        property_code=clean_property_code,
        check_in_date=requested_check_in.isoformat() if requested_check_in else "",
        check_out_date=requested_check_out.isoformat() if requested_check_out else "",
    )


async def _lookup_session_by_token(
    *,
    db: Any,
    tenant_id: str,
    session_token: str,
):
    try:
        result = await db.execute(
            text(
                """
                SELECT token, status, reservation_id, guest_name, guest_email, guest_phone,
                       property_code, check_in, check_out
                FROM concierge_guest_sessions
                WHERE tenant_id::text = :tenant_id
                  AND token = :token
                ORDER BY created_at DESC
                LIMIT 1
                """
            ),
            {"tenant_id": tenant_id, "token": session_token},
        )
        return result.fetchone()
    except Exception:
        await safe_rollback(db)
        return None


async def _lookup_pms_booking(
    *,
    db: Any,
    tenant_id: str,
    guest_email: str,
    reservation_id: str,
    requested_check_in: Optional[date],
    requested_check_out: Optional[date],
):
    try:
        if reservation_id:
            result = await db.execute(
                text(
                    """
                    SELECT external_id, guest_first_name, guest_last_name, guest_email, guest_phone,
                           check_in, check_out
                    FROM pms_bookings
                    WHERE company_id = CAST(:tenant_id AS uuid)
                      AND external_id = :reservation_id
                      AND status = 'confirmed'
                    LIMIT 1
                    """
                ),
                {"tenant_id": tenant_id, "reservation_id": reservation_id},
            )
            row = result.fetchone()
            if row is not None:
                return row

        if not guest_email or _is_masked_ota_email(guest_email):
            return None

        params = {
            "tenant_id": tenant_id,
            "guest_email": guest_email,
        }
        filters = [
            "company_id = CAST(:tenant_id AS uuid)",
            "LOWER(COALESCE(guest_email, '')) = :guest_email",
            "status = 'confirmed'",
        ]
        if requested_check_in is not None:
            params["requested_check_in"] = requested_check_in
            filters.append("check_in = :requested_check_in")
        if requested_check_out is not None:
            params["requested_check_out"] = requested_check_out
            filters.append("check_out = :requested_check_out")

        result = await db.execute(
            text(
                f"""
                SELECT external_id, guest_first_name, guest_last_name, guest_email, guest_phone,
                       check_in, check_out
                FROM pms_bookings
                WHERE {' AND '.join(filters)}
                ORDER BY check_in ASC
                LIMIT 1
                """
            ),
            params,
        )
        return result.fetchone()
    except Exception:
        await safe_rollback(db)
        return None


def _is_masked_ota_email(email: str) -> bool:
    value = str(email or "").strip().lower()
    return any(pattern.search(value) for pattern in _MASKED_EMAIL_PATTERNS)


def _cache_get(key: tuple[Any, ...]) -> Optional[GuestIdentityResolution]:
    entry = _IDENTITY_CACHE.get(key)
    if not entry:
        return None
    if (time.monotonic() - entry[0]) > _CACHE_TTL_SECONDS:
        _IDENTITY_CACHE.pop(key, None)
        return None
    return entry[1]


def _cache_set(key: tuple[Any, ...], value: GuestIdentityResolution) -> None:
    _IDENTITY_CACHE[key] = (time.monotonic(), value)
