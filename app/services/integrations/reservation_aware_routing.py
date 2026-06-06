from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Optional
from uuid import UUID

import httpx
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from app.db.session_safety import safe_rollback
from app.services.connectors.escapia_connector import EscapiaConnectorV2
from app.services.connectors.integration_gateway import (
    IntegrationProvider,
    get_integration_credential_store,
)
from app.services.feature_flags import FeatureFlag, get_feature_flags

logger = logging.getLogger(__name__)

_BEACH_HABITATS_TENANT_ID = UUID("e07980b2-a990-4b24-91d1-c8cb71ab70e1")
_CACHE_TTL_SECONDS = 60.0
_LISTING_CACHE_TTL_SECONDS = 600.0
_LOOKUP_FAILED = object()
_NO_MATCH = object()
_RESERVATION_CACHE: dict[tuple[Any, ...], tuple[float, object]] = {}
_LISTING_CACHE: dict[str, tuple[float, list[dict[str, str]]]] = {}

DEFAULT_WINDOW_PAST_DAYS = 14
DEFAULT_WINDOW_FUTURE_DAYS = 30


@dataclass(frozen=True)
class ReservationAwareWindow:
    past_days: int
    future_days: int


@dataclass(frozen=True)
class MatchedReservation:
    reservation_id: str
    guest_name: str
    guest_email: str
    check_in: date
    check_out: date
    property_code: str
    match_method: str
    provider: str = "escapia"

    @property
    def lifecycle_resolved(self) -> str:
        return determine_lifecycle(
            check_in=self.check_in,
            check_out=self.check_out,
        )

    def parser_notes_payload(self, *, routing_source: str) -> dict[str, Any]:
        return {
            "type": "reservation_routing_metadata",
            "lifecycle_routing_source": routing_source,
            "pms_match_method": self.match_method,
            "reservation_id": self.reservation_id,
            "reservation_check_in": self.check_in.isoformat(),
            "reservation_check_out": self.check_out.isoformat(),
            "lifecycle_resolved": self.lifecycle_resolved,
            "property_code": self.property_code,
            "provider": self.provider,
        }


@dataclass(frozen=True)
class ReservationRoutingDecision:
    routing_source: str
    matched_reservation: Optional[MatchedReservation] = None
    failure_reason: str = ""

    def parser_notes_payload(self) -> dict[str, Any]:
        if self.matched_reservation is not None:
            return self.matched_reservation.parser_notes_payload(
                routing_source=self.routing_source,
            )
        payload: dict[str, Any] = {
            "type": "reservation_routing_metadata",
            "lifecycle_routing_source": self.routing_source,
            "pms_match_method": None,
            "lifecycle_resolved": "pre_booking",
        }
        if self.failure_reason:
            payload["failure_reason"] = self.failure_reason[:200]
        return payload


async def load_reservation_routing_window(
    *,
    tenant_id: UUID,
    db: Any = None,
) -> ReservationAwareWindow:
    extra = await _load_operator_settings_extra(tenant_id=tenant_id, db=db)
    past = _clamp_int(
        extra.get("reservation_aware_routing_window_days_past"),
        default=DEFAULT_WINDOW_PAST_DAYS,
        minimum=0,
        maximum=60,
    )
    future = _clamp_int(
        extra.get("reservation_aware_routing_window_days_future"),
        default=DEFAULT_WINDOW_FUTURE_DAYS,
        minimum=0,
        maximum=90,
    )
    return ReservationAwareWindow(past_days=past, future_days=future)


def determine_lifecycle(
    *,
    check_in: date,
    check_out: date,
    today: Optional[date] = None,
) -> str:
    anchor = today or date.today()
    if anchor < check_in:
        return "pre_arrival"
    if check_in <= anchor <= check_out:
        return "in_stay"
    return "post_stay"


class ReservationAwareRoutingService:
    def __init__(self, *, company_id: UUID, db: Any = None) -> None:
        self.company_id = company_id
        self.db = db

    async def is_enabled(self, *, property_code: str = "") -> bool:
        if self.company_id == _BEACH_HABITATS_TENANT_ID:
            return True
        try:
            flags = get_feature_flags(self.db)
            return await flags.is_enabled(
                FeatureFlag.RESERVATION_AWARE_ROUTING_ENABLED,
                company_id=str(self.company_id),
                property_code=property_code or None,
            )
        except Exception:
            logger.warning(
                "[ReservationAwareRouting] feature-flag lookup failed tenant_id=%s",
                self.company_id,
                exc_info=True,
            )
            return False

    async def find_matching_reservation(self, parsed) -> Optional[MatchedReservation]:
        return (await self.evaluate(parsed)).matched_reservation

    async def evaluate(self, parsed) -> ReservationRoutingDecision:
        if not await self.is_enabled(property_code=getattr(parsed, "property_code", "") or ""):
            return ReservationRoutingDecision(routing_source="pms_lookup_disabled")

        cache_key = self._cache_key(parsed)
        cached = self._cache_get(cache_key)
        if cached is _LOOKUP_FAILED:
            return ReservationRoutingDecision(
                routing_source="pms_lookup_failed",
                failure_reason="cached_lookup_failed",
            )
        if cached is _NO_MATCH:
            return ReservationRoutingDecision(routing_source="no_match_pre_booking")
        if isinstance(cached, MatchedReservation):
            return ReservationRoutingDecision(
                routing_source="pms_reservation_matched",
                matched_reservation=cached,
            )

        window = await load_reservation_routing_window(
            tenant_id=self.company_id,
            db=self.db,
        )
        local_match = await self._find_in_pms_bookings(parsed, window=window)
        if local_match is not None:
            self._cache_set(cache_key, local_match)
            return ReservationRoutingDecision(
                routing_source="pms_reservation_matched",
                matched_reservation=local_match,
            )

        try:
            live_match = await self._find_via_escapia_api(parsed, window=window)
        except httpx.TimeoutException as exc:
            logger.warning(
                "[ReservationAwareRouting] PMS timeout tenant_id=%s err=%s",
                self.company_id,
                str(exc),
            )
            self._cache_set(cache_key, _LOOKUP_FAILED)
            return ReservationRoutingDecision(
                routing_source="pms_lookup_failed",
                failure_reason=f"timeout:{type(exc).__name__}",
            )
        except httpx.HTTPError as exc:
            logger.error(
                "[ReservationAwareRouting] PMS HTTP failure tenant_id=%s err=%s",
                self.company_id,
                str(exc),
                exc_info=True,
            )
            self._cache_set(cache_key, _LOOKUP_FAILED)
            return ReservationRoutingDecision(
                routing_source="pms_lookup_failed",
                failure_reason=f"http:{type(exc).__name__}",
            )
        except ValueError as exc:
            logger.warning(
                "[ReservationAwareRouting] credential or parse failure tenant_id=%s err=%s",
                self.company_id,
                str(exc),
            )
            self._cache_set(cache_key, _LOOKUP_FAILED)
            return ReservationRoutingDecision(
                routing_source="pms_lookup_failed",
                failure_reason=f"value:{type(exc).__name__}",
            )

        self._cache_set(cache_key, live_match if live_match is not None else _NO_MATCH)
        if live_match is not None:
            return ReservationRoutingDecision(
                routing_source="pms_reservation_matched",
                matched_reservation=live_match,
            )
        return ReservationRoutingDecision(routing_source="no_match_pre_booking")

    async def _find_in_pms_bookings(
        self,
        parsed,
        *,
        window: ReservationAwareWindow,
    ) -> Optional[MatchedReservation]:
        if self.db is None:
            return None

        today = date.today()
        if getattr(parsed, "reservation_id", ""):
            row = await self._fetch_cached_row(
                """
                SELECT external_id, guest_first_name, guest_last_name, guest_email, check_in, check_out
                FROM pms_bookings
                WHERE company_id = CAST(:company_id AS uuid)
                  AND external_id = :reservation_id
                  AND status = 'confirmed'
                LIMIT 1
                """,
                {
                    "company_id": str(self.company_id),
                    "reservation_id": parsed.reservation_id,
                },
            )
            if row is not None:
                return MatchedReservation(
                    reservation_id=str(row.external_id),
                    guest_name=_join_name(row.guest_first_name, row.guest_last_name),
                    guest_email=str(row.guest_email or ""),
                    check_in=row.check_in,
                    check_out=row.check_out,
                    property_code=getattr(parsed, "property_code", "") or "",
                    match_method="reservation_id",
                )

        guest_email = (getattr(parsed, "guest_email", "") or "").strip().lower()
        if guest_email:
            row = await self._fetch_cached_row(
                """
                SELECT external_id, guest_first_name, guest_last_name, guest_email, check_in, check_out
                FROM pms_bookings
                WHERE company_id = CAST(:company_id AS uuid)
                  AND LOWER(COALESCE(guest_email, '')) = :guest_email
                  AND status = 'confirmed'
                  AND check_out >= :window_start
                  AND check_in <= :window_end
                ORDER BY check_in ASC
                LIMIT 1
                """,
                {
                    "company_id": str(self.company_id),
                    "guest_email": guest_email,
                    "window_start": today - timedelta(days=window.past_days),
                    "window_end": today + timedelta(days=window.future_days),
                },
            )
            if row is not None:
                return MatchedReservation(
                    reservation_id=str(row.external_id),
                    guest_name=_join_name(row.guest_first_name, row.guest_last_name),
                    guest_email=str(row.guest_email or ""),
                    check_in=row.check_in,
                    check_out=row.check_out,
                    property_code=getattr(parsed, "property_code", "") or "",
                    match_method="email",
                )
            return None

        return None

    async def _find_via_escapia_api(
        self,
        parsed,
        *,
        window: ReservationAwareWindow,
    ) -> Optional[MatchedReservation]:
        credentials = self._load_escapia_credentials()
        if not credentials:
            return None

        connector = EscapiaConnectorV2(self.company_id, credentials)
        today = date.today()
        bookings = await _fetch_escapia_bookings_raw(
            connector=connector,
            start_date=today - timedelta(days=window.past_days),
            end_date=today + timedelta(days=window.future_days),
        )
        listing_map = await self._load_listing_map(connector)

        reservation_id = (getattr(parsed, "reservation_id", "") or "").strip()
        if reservation_id:
            matched = _match_reservation_id(bookings, reservation_id=reservation_id, listing_map=listing_map)
            if matched is not None:
                return matched

        guest_email = (getattr(parsed, "guest_email", "") or "").strip().lower()
        if guest_email:
            matched = _match_guest_email(
                bookings,
                guest_email=guest_email,
                property_code=(getattr(parsed, "property_code", "") or "").strip(),
                listing_map=listing_map,
            )
            if matched is not None:
                return matched
            return None

        return _match_name_dates(
            bookings,
            guest_name=(getattr(parsed, "guest_name", "") or "").strip(),
            property_code=(getattr(parsed, "property_code", "") or "").strip(),
            requested_check_in=getattr(parsed, "requested_check_in", None),
            requested_check_out=getattr(parsed, "requested_check_out", None),
            listing_map=listing_map,
        )

    async def _load_listing_map(self, connector: EscapiaConnectorV2) -> list[dict[str, str]]:
        cache_key = str(self.company_id)
        cached = _LISTING_CACHE.get(cache_key)
        now = time.monotonic()
        if cached and (now - cached[0]) <= _LISTING_CACHE_TTL_SECONDS:
            return cached[1]

        try:
            listings = await connector.fetch_listings()
        except httpx.TimeoutException:
            raise
        except httpx.HTTPError:
            raise
        except Exception as exc:
            raise ValueError(f"Escapia listings lookup failed: {exc}") from exc

        mapped = [
            {
                "listing_external_id": str(getattr(item, "provider_listing_id", "") or getattr(item, "external_id", "") or ""),
                "property_code": str(getattr(item, "provider_unit_id", "") or ""),
                "property_name": str(getattr(item, "property_name", "") or ""),
            }
            for item in listings
        ]
        _LISTING_CACHE[cache_key] = (now, mapped)
        return mapped

    def _load_escapia_credentials(self) -> dict[str, str]:
        try:
            creds = get_integration_credential_store().get_credentials(
                self.company_id,
                IntegrationProvider.ESCAPIA,
            )
            if creds:
                return creds
        except ValueError:
            pass

        api_key = os.getenv("ESCAPIA_API_KEY", "").strip()
        if not api_key:
            return {}
        credentials = {"api_key": api_key}
        pmc = os.getenv("ESCAPIA_PMC", "").strip()
        if pmc:
            credentials["provider_account_id"] = pmc
        return credentials

    async def _fetch_cached_row(self, sql: str, params: dict[str, Any]):
        try:
            result = await self.db.execute(text(sql), params)
            return result.fetchone()
        except ProgrammingError:
            await safe_rollback(self.db)
            logger.error(
                "[ReservationAwareRouting] schema issue during cached booking lookup tenant_id=%s",
                self.company_id,
                exc_info=True,
            )
            return None
        except DBAPIError:
            await safe_rollback(self.db)
            logger.warning(
                "[ReservationAwareRouting] cached booking lookup failed tenant_id=%s",
                self.company_id,
                exc_info=True,
            )
            return None

    def _cache_key(self, parsed) -> tuple[Any, ...]:
        guest_email = (getattr(parsed, "guest_email", "") or "").strip().lower()
        if guest_email:
            return ("email", str(self.company_id), guest_email)
        return (
            "name_dates",
            str(self.company_id),
            _normalize_name(getattr(parsed, "guest_name", "") or ""),
            (getattr(parsed, "property_code", "") or "").strip().lower(),
            getattr(parsed, "requested_check_in", None).isoformat() if getattr(parsed, "requested_check_in", None) else "",
            getattr(parsed, "requested_check_out", None).isoformat() if getattr(parsed, "requested_check_out", None) else "",
        )

    def _cache_get(self, key: tuple[Any, ...]) -> object | None:
        entry = _RESERVATION_CACHE.get(key)
        if not entry:
            return None
        if (time.monotonic() - entry[0]) > _CACHE_TTL_SECONDS:
            _RESERVATION_CACHE.pop(key, None)
            return None
        return entry[1]

    def _cache_set(self, key: tuple[Any, ...], value: object | None) -> None:
        cached_value = _LOOKUP_FAILED if value is _LOOKUP_FAILED else value
        _RESERVATION_CACHE[key] = (time.monotonic(), cached_value)


async def _load_operator_settings_extra(*, tenant_id: UUID, db: Any = None) -> dict[str, Any]:
    if db is None:
        return {}
    try:
        row = (
            await db.execute(
                text(
                    """
                    SELECT extra
                    FROM operator_settings
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                    LIMIT 1
                    """
                ),
                {"tenant_id": str(tenant_id)},
            )
        ).scalar_one_or_none()
    except ProgrammingError:
        await safe_rollback(db)
        logger.error(
            "[ReservationAwareRouting] operator_settings schema issue tenant_id=%s",
            tenant_id,
            exc_info=True,
        )
        return {}
    except DBAPIError:
        await safe_rollback(db)
        logger.warning(
            "[ReservationAwareRouting] operator_settings lookup failed tenant_id=%s",
            tenant_id,
            exc_info=True,
        )
        return {}
    if isinstance(row, dict):
        return row
    return {}


def _clamp_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        return default
    return min(max(numeric, minimum), maximum)


async def _fetch_escapia_bookings_raw(
    *,
    connector: EscapiaConnectorV2,
    start_date: date,
    end_date: date,
) -> list[dict[str, Any]]:
    headers = await connector._get_auth_headers()
    bookings: list[dict[str, Any]] = []
    offset = 0
    limit = 50
    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            response = await client.get(
                f"{connector.BASE_URL}/reservations",
                headers=headers,
                params={
                    "offset": offset,
                    "limit": limit,
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                },
            )
            response.raise_for_status()
            data = response.json()
            items = data.get("results", data.get("reservations", data.get("data", [])))
            if not items:
                break
            for item in items:
                booking = connector._normalize_booking(item)
                bookings.append(
                    {
                        "booking": booking,
                        "listing_external_id": str(item.get("listing_id", item.get("property_id", item.get("id", ""))) or ""),
                        "property_code": str(item.get("unit_code", item.get("property_code", item.get("unit_id", item.get("code", "")))) or ""),
                    }
                )
            if len(items) < limit:
                break
            offset += limit
    return bookings


def _match_reservation_id(
    bookings: list[dict[str, Any]],
    *,
    reservation_id: str,
    listing_map: list[dict[str, str]],
) -> Optional[MatchedReservation]:
    for item in bookings:
        booking = item["booking"]
        if str(getattr(booking, "external_id", "")) != reservation_id:
            continue
        return _build_match(item, listing_map=listing_map, match_method="reservation_id")
    return None


def _match_guest_email(
    bookings: list[dict[str, Any]],
    *,
    guest_email: str,
    property_code: str,
    listing_map: list[dict[str, str]],
) -> Optional[MatchedReservation]:
    candidates: list[MatchedReservation] = []
    for item in bookings:
        booking = item["booking"]
        booking_email = str(getattr(booking, "guest_email", "") or "").strip().lower()
        if booking_email != guest_email:
            continue
        match = _build_match(item, listing_map=listing_map, match_method="email")
        if property_code and match.property_code and match.property_code != property_code:
            continue
        candidates.append(match)
    if not candidates:
        return None
    return sorted(candidates, key=lambda match: (match.check_in, match.check_out))[0]


def _match_name_dates(
    bookings: list[dict[str, Any]],
    *,
    guest_name: str,
    property_code: str,
    requested_check_in: Optional[date],
    requested_check_out: Optional[date],
    listing_map: list[dict[str, str]],
) -> Optional[MatchedReservation]:
    if not guest_name or not property_code or not requested_check_in or not requested_check_out:
        return None
    normalized_guest = _normalize_name(guest_name)
    for item in bookings:
        booking = item["booking"]
        full_name = _normalize_name(
            _join_name(
                getattr(booking, "guest_first_name", None),
                getattr(booking, "guest_last_name", None),
            )
        )
        if full_name != normalized_guest:
            continue
        match = _build_match(item, listing_map=listing_map, match_method="name_dates")
        if match.property_code != property_code:
            continue
        if match.check_in != requested_check_in or match.check_out != requested_check_out:
            continue
        return match
    return None


def _build_match(
    item: dict[str, Any],
    *,
    listing_map: list[dict[str, str]],
    match_method: str,
) -> MatchedReservation:
    booking = item["booking"]
    property_code = str(item.get("property_code") or "")
    listing_external_id = str(item.get("listing_external_id") or "")
    if not property_code and listing_external_id:
        for listing in listing_map:
            if listing.get("listing_external_id") == listing_external_id:
                property_code = listing.get("property_code", "")
                break
    return MatchedReservation(
        reservation_id=str(getattr(booking, "external_id", "") or ""),
        guest_name=_join_name(
            getattr(booking, "guest_first_name", None),
            getattr(booking, "guest_last_name", None),
        ),
        guest_email=str(getattr(booking, "guest_email", "") or ""),
        check_in=getattr(booking, "check_in"),
        check_out=getattr(booking, "check_out"),
        property_code=property_code,
        match_method=match_method,
    )


def _normalize_name(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


def _join_name(first: Any, last: Any) -> str:
    return " ".join(part for part in [str(first or "").strip(), str(last or "").strip()] if part).strip()


def clear_reservation_routing_caches() -> None:
    _RESERVATION_CACHE.clear()
    _LISTING_CACHE.clear()
