from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class StayPmsFeedService:
    async def load_feed(
        self,
        session: AsyncSession,
        tenant_id: str,
        *,
        reservation_id: str | None,
        property_code: str | None,
        property_name: str | None,
        check_in: Any = None,
        check_out: Any = None,
    ) -> dict[str, Any]:
        if not await self._table_exists(session, "pms_bookings"):
            return {"available": False, "reason": "pms_bookings_unavailable", "derived_events": []}

        booking = await self._load_booking(
            session,
            tenant_id,
            reservation_id=reservation_id,
            property_code=property_code,
            property_name=property_name,
            check_in=check_in,
            check_out=check_out,
        )
        if not booking:
            return {"available": False, "reason": "booking_not_matched", "derived_events": []}

        check_in_date = self._coerce_date(booking.get("check_in"))
        check_out_date = self._coerce_date(booking.get("check_out"))
        now = datetime.now(timezone.utc).date()
        derived_events = self._derived_events(booking, check_in_date, check_out_date, now)

        return {
            "available": True,
            "provider": booking.get("pms_provider") or "unknown",
            "reservation_id": booking.get("reservation_id"),
            "listing_external_id": booking.get("listing_external_id"),
            "listing_name": booking.get("listing_name"),
            "booking_channel": booking.get("booking_channel"),
            "status": booking.get("status"),
            "guest_count": booking.get("guest_count"),
            "check_in": check_in_date.isoformat() if check_in_date else None,
            "check_out": check_out_date.isoformat() if check_out_date else None,
            "booked_at": self._iso(booking.get("booked_at")),
            "phase_hint": self._phase_hint(check_in_date, check_out_date, now),
            "derived_events": derived_events,
        }

    def normalize_pms_event(
        self,
        provider: str,
        event_type: str,
        *,
        note: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized = str(event_type or "").strip().lower()
        payload = payload if isinstance(payload, dict) else {}
        mapping = {
            "reservation_checked_in": ("guest_checked_in", "stay"),
            "checked_in": ("guest_checked_in", "stay"),
            "reservation_checked_out": ("guest_checked_out", "turnover"),
            "checked_out": ("guest_checked_out", "turnover"),
            "turnover_started": ("housekeeping_arrived", "turnover"),
            "housekeeping_started": ("housekeeping_arrived", "turnover"),
            "turnover_completed": ("housekeeping_completed", "turnover"),
            "housekeeping_completed": ("housekeeping_completed", "turnover"),
            "property_ready": ("property_ready", "turnover"),
            "walkthrough_completed": ("documentation_completed", "walkthrough"),
            "documentation_completed": ("documentation_completed", "walkthrough"),
            "vendor_arrived": ("vendor_arrived", "vendor"),
            "vendor_completed": ("vendor_completed", "vendor"),
        }
        normalized_event_type, domain = mapping.get(normalized, (normalized, "ops"))
        merged_payload = dict(payload)
        merged_payload["provider_event_type"] = normalized
        merged_payload["provider"] = provider
        return {
            "event_type": normalized_event_type,
            "event_domain": domain,
            "source": f"pms:{provider or 'unknown'}",
            "note": note,
            "payload": merged_payload,
        }

    async def _load_booking(
        self,
        session: AsyncSession,
        tenant_id: str,
        *,
        reservation_id: str | None,
        property_code: str | None,
        property_name: str | None,
        check_in: Any = None,
        check_out: Any = None,
    ) -> dict[str, Any]:
        has_listings = await self._table_exists(session, "pms_listings")
        join_sql = "LEFT JOIN pms_listings l ON l.id = b.listing_id" if has_listings else ""
        listing_name_sql = "l.property_name AS listing_name," if has_listings else "NULL::text AS listing_name,"
        listing_id_sql = "l.external_id AS listing_external_id," if has_listings else "b.external_listing_id AS listing_external_id,"
        provider_sql = "l.pms_provider AS pms_provider," if has_listings else "NULL::text AS pms_provider,"

        where = ["b.company_id = CAST(:tid AS uuid)"]
        params: dict[str, Any] = {"tid": tenant_id}

        if reservation_id:
            where.append("b.external_id = :reservation_id")
            params["reservation_id"] = reservation_id
        else:
            check_in_date = self._coerce_date(check_in)
            check_out_date = self._coerce_date(check_out)
            if check_in_date:
                where.append("b.check_in = :check_in")
                params["check_in"] = check_in_date
            if check_out_date:
                where.append("b.check_out = :check_out")
                params["check_out"] = check_out_date
            if property_name and has_listings:
                where.append("COALESCE(l.property_name, '') = :property_name")
                params["property_name"] = property_name
            elif property_code and has_listings:
                where.append("COALESCE(l.external_id, '') = :property_code")
                params["property_code"] = property_code

        row = (
            await session.execute(
                text(
                    f"""
                    SELECT b.external_id AS reservation_id,
                           {listing_id_sql}
                           {listing_name_sql}
                           {provider_sql}
                           b.booking_channel,
                           b.status,
                           b.guest_count,
                           b.booked_at,
                           b.check_in,
                           b.check_out
                    FROM pms_bookings b
                    {join_sql}
                    WHERE {' AND '.join(where)}
                    ORDER BY b.updated_at DESC, b.created_at DESC
                    LIMIT 1
                    """
                ),
                params,
            )
        ).mappings().first()
        return dict(row) if row else {}

    def _derived_events(
        self,
        booking: dict[str, Any],
        check_in: date | None,
        check_out: date | None,
        now: date,
    ) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        if check_in:
            events.append(
                {
                    "event_type": "scheduled_arrival",
                    "event_domain": "arrival",
                    "scheduled_for": check_in.isoformat(),
                    "status": "upcoming" if now < check_in else "current" if now == check_in else "past",
                }
            )
        if check_out:
            events.append(
                {
                    "event_type": "scheduled_checkout",
                    "event_domain": "turnover",
                    "scheduled_for": check_out.isoformat(),
                    "status": "upcoming" if now < check_out else "current" if now == check_out else "past",
                }
            )
        if check_out and now >= check_out:
            events.append(
                {
                    "event_type": "turnover_window_open",
                    "event_domain": "turnover",
                    "scheduled_for": check_out.isoformat(),
                    "status": "ready",
                }
            )
        return events

    def _phase_hint(self, check_in: date | None, check_out: date | None, now: date) -> str:
        if check_in and now < check_in:
            return "pre_arrival"
        if check_in and check_out and check_in <= now < check_out:
            return "in_stay"
        if check_out and now == check_out:
            return "departure_day"
        if check_out and now > check_out:
            return "post_stay"
        return "unknown"

    def _coerce_date(self, value: Any) -> date | None:
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, str):
            try:
                return date.fromisoformat(value[:10])
            except Exception:
                return None
        return None

    def _iso(self, value: Any) -> str | None:
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, date):
            return value.isoformat()
        if value is None:
            return None
        return str(value)

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


_SERVICE = StayPmsFeedService()


def get_stay_pms_feed_service() -> StayPmsFeedService:
    return _SERVICE
