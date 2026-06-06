from __future__ import annotations

"""Canonical booking-read source: the ONE place booking/listing facts are read
from pms_bookings/pms_listings. CanonicalBookingContextAdapter is wrapped by
AdapterBackedBookingDataProvider to satisfy the BookingDataProvider contract,
and orchestrated by BookingContextAgent. This is one path exposed through a
provider abstraction for multi-PMS support — NOT a duplicate of the agent.
Invariant: test_booking_data_provider_per_request_isolation.
"""

from dataclasses import dataclass
from datetime import date
from typing import Optional, Protocol, runtime_checkable
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class BookingContextAdapterConfig:
    company_id: UUID
    provider: str = "canonical"


@dataclass(frozen=True)
class BookingContextLookup:
    session_id: Optional[str] = None
    reservation_id: Optional[str] = None
    property_code: Optional[str] = None
    guest_email: Optional[str] = None
    guest_phone: Optional[str] = None
    check_in: Optional[date] = None
    check_out: Optional[date] = None
    as_of: Optional[date] = None


class BookingContextBuildError(RuntimeError):
    pass


@runtime_checkable
class BookingContextAdapter(Protocol):
    company_id: UUID
    provider: str

    async def lookup(self, db: AsyncSession, lookup: BookingContextLookup) -> dict: ...


async def _table_columns(db: AsyncSession, table_name: str) -> set[str]:
    rows = (await db.execute(
        text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = :table
        """),
        {"table": table_name},
    )).fetchall()
    return {str(r[0]) for r in rows}


class CanonicalBookingContextAdapter:
    def __init__(self, config: BookingContextAdapterConfig):
        self.company_id = config.company_id
        self.provider = "canonical"

    async def lookup(self, db: AsyncSession, lookup: BookingContextLookup) -> dict:
        as_of = lookup.as_of or date.today()
        booking_columns = await _table_columns(db, "pms_bookings")
        has_guest_identity = {
            "guest_first_name",
            "guest_last_name",
            "guest_email",
            "guest_phone",
        }.issubset(booking_columns)

        guest_first_name_sql = "b.guest_first_name" if "guest_first_name" in booking_columns else "NULL::text AS guest_first_name"
        guest_last_name_sql = "b.guest_last_name" if "guest_last_name" in booking_columns else "NULL::text AS guest_last_name"
        guest_email_sql = "b.guest_email" if "guest_email" in booking_columns else "NULL::text AS guest_email"
        guest_phone_sql = "b.guest_phone" if "guest_phone" in booking_columns else "NULL::text AS guest_phone"

        derived = await self._derive_lookup_from_session(db, lookup)
        reservation_id = lookup.reservation_id or derived.get("reservation_id")
        property_code = lookup.property_code or derived.get("property_code")
        guest_email = lookup.guest_email or derived.get("guest_email")
        guest_phone = lookup.guest_phone or derived.get("guest_phone")
        check_in = lookup.check_in or derived.get("check_in")
        check_out = lookup.check_out or derived.get("check_out")

        where = ["b.company_id = CAST(:company_id AS uuid)"]
        params: dict = {
            "company_id": str(self.company_id),
            "as_of": as_of,
            "limit": 5,
        }
        match_strategy = "tenant_recent"

        if reservation_id:
            where.append("b.external_id = :reservation_id")
            params["reservation_id"] = reservation_id
            match_strategy = "reservation_id"
        elif property_code and check_in and check_out:
            where.append("l.external_id = :property_code")
            where.append("b.check_in <= :check_out AND b.check_out >= :check_in")
            params["property_code"] = property_code
            params["check_in"] = check_in
            params["check_out"] = check_out
            match_strategy = "property_code+dates"
        elif property_code:
            where.append("l.external_id = :property_code")
            params["property_code"] = property_code
            match_strategy = "property_code"
        elif guest_email and "guest_email" in booking_columns:
            where.append("LOWER(COALESCE(b.guest_email, '')) = LOWER(:guest_email)")
            params["guest_email"] = guest_email
            match_strategy = "guest_email"
        elif guest_phone and "guest_phone" in booking_columns:
            where.append("REGEXP_REPLACE(COALESCE(b.guest_phone, ''), '[^0-9]', '', 'g') = REGEXP_REPLACE(:guest_phone, '[^0-9]', '', 'g')")
            params["guest_phone"] = guest_phone
            match_strategy = "guest_phone"

        rows = (await db.execute(
            text(f"""
                SELECT
                    b.id AS booking_row_id,
                    b.external_id AS reservation_id,
                    b.check_in,
                    b.check_out,
                    b.nights,
                    b.total_amount,
                    b.nightly_rate,
                    b.cleaning_fee,
                    b.taxes,
                    b.guest_count,
                    {guest_first_name_sql},
                    {guest_last_name_sql},
                    {guest_email_sql},
                    {guest_phone_sql},
                    b.booking_channel,
                    b.status,
                    b.booked_at,
                    l.id AS listing_row_id,
                    l.external_id AS property_code,
                    l.pms_provider,
                    l.property_name,
                    l.city,
                    l.state,
                    l.bedrooms,
                    l.bathrooms,
                    l.property_type,
                    l.has_pool,
                    l.has_hot_tub,
                    l.beach_access,
                    l.pet_friendly
                FROM pms_bookings b
                LEFT JOIN pms_listings l
                  ON l.id = b.listing_id
                WHERE {' AND '.join(where)}
                ORDER BY
                    CASE
                        WHEN b.check_in <= :as_of AND b.check_out >= :as_of THEN 0
                        WHEN b.check_in > :as_of THEN 1
                        ELSE 2
                    END,
                    ABS(EXTRACT(EPOCH FROM ((b.check_in)::timestamp - (:as_of)::timestamp))) ASC,
                    b.check_in ASC
                LIMIT :limit
            """),
            params,
        )).mappings().all()

        if not rows:
            return {
                "available": False,
                "source": "canonical_pms_cache",
                "provider": None,
                "match_strategy": match_strategy,
                "guest_identity_available": has_guest_identity,
                "lookup": self._serialize_lookup(
                    reservation_id=reservation_id,
                    property_code=property_code,
                    guest_email=guest_email,
                    guest_phone=guest_phone,
                    check_in=check_in,
                    check_out=check_out,
                    as_of=as_of,
                ),
            }

        bookings = [self._serialize_booking(row, as_of) for row in rows]
        active_booking = next((item for item in bookings if item["is_active"]), None)
        next_booking = next((item for item in bookings if item["is_upcoming"]), None)
        property_snapshot = self._serialize_property(rows[0])

        return {
            "available": True,
            "source": "canonical_pms_cache",
            "provider": rows[0]["pms_provider"],
            "match_strategy": match_strategy,
            "guest_identity_available": has_guest_identity,
            "lookup": self._serialize_lookup(
                reservation_id=reservation_id,
                property_code=property_code,
                guest_email=guest_email,
                guest_phone=guest_phone,
                check_in=check_in,
                check_out=check_out,
                as_of=as_of,
            ),
            "property": property_snapshot,
            "booking": active_booking or bookings[0],
            "active_booking": active_booking,
            "next_booking": next_booking,
            "upcoming_bookings": [item for item in bookings if item["is_upcoming"]][:3],
        }

    async def _derive_lookup_from_session(self, db: AsyncSession, lookup: BookingContextLookup) -> dict:
        if not lookup.session_id:
            return {}
        row = (await db.execute(
            text("""
                SELECT reservation_id, property_code, guest_email, guest_phone, check_in, check_out
                FROM concierge_guest_sessions
                WHERE session_id = CAST(:sid AS uuid)
                  AND tenant_id = CAST(:company_id AS uuid)
                LIMIT 1
            """),
            {"sid": lookup.session_id, "company_id": str(self.company_id)},
        )).mappings().first()
        return dict(row) if row else {}

    def _serialize_lookup(
        self,
        *,
        reservation_id: Optional[str],
        property_code: Optional[str],
        guest_email: Optional[str],
        guest_phone: Optional[str],
        check_in: Optional[date],
        check_out: Optional[date],
        as_of: date,
    ) -> dict:
        return {
            "reservation_id": reservation_id,
            "property_code": property_code,
            "guest_email": guest_email,
            "guest_phone": guest_phone,
            "check_in": check_in.isoformat() if check_in else None,
            "check_out": check_out.isoformat() if check_out else None,
            "as_of": as_of.isoformat(),
        }

    def _serialize_property(self, row) -> dict:
        return {
            "property_code": row["property_code"],
            "property_name": row["property_name"],
            "provider": row["pms_provider"],
            "city": row["city"],
            "state": row["state"],
            "bedrooms": int(row["bedrooms"] or 0),
            "bathrooms": float(row["bathrooms"] or 0),
            "property_type": row["property_type"],
            "has_pool": bool(row["has_pool"]),
            "has_hot_tub": bool(row["has_hot_tub"]),
            "beach_access": row["beach_access"],
            "pet_friendly": bool(row["pet_friendly"]),
        }

    def _serialize_booking(self, row, as_of: date) -> dict:
        check_in = row["check_in"]
        check_out = row["check_out"]
        is_active = bool(check_in and check_out and check_in <= as_of <= check_out)
        is_upcoming = bool(check_in and check_in > as_of)
        return {
            "reservation_id": row["reservation_id"],
            "status": row["status"],
            "booking_channel": row["booking_channel"],
            "check_in": check_in.isoformat() if check_in else None,
            "check_out": check_out.isoformat() if check_out else None,
            "nights": int(row["nights"] or 0),
            "guest_count": int(row["guest_count"] or 0),
            "guest_first_name": row["guest_first_name"],
            "guest_last_name": row["guest_last_name"],
            "guest_email": row["guest_email"],
            "guest_phone": row["guest_phone"],
            "total_amount": float(row["total_amount"] or 0),
            "nightly_rate": float(row["nightly_rate"] or 0),
            "cleaning_fee": float(row["cleaning_fee"] or 0) if row["cleaning_fee"] is not None else None,
            "taxes": float(row["taxes"] or 0) if row["taxes"] is not None else None,
            "booked_at": row["booked_at"].isoformat() if row["booked_at"] else None,
            "is_active": is_active,
            "is_upcoming": is_upcoming,
        }


def build_booking_context_adapter(
    config: BookingContextAdapterConfig,
) -> BookingContextAdapter:
    provider = (config.provider or "canonical").strip().lower()
    if provider in {"canonical", "pms_cache", "pms", "escapia", "guesty", "track"}:
        return CanonicalBookingContextAdapter(config)
    raise BookingContextBuildError(f"Unsupported booking context provider: {provider}")
