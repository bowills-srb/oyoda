"""
Escapia ingestion service.

Performs live API pulls and returns raw payload slices for persistence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List, Optional

import httpx


@dataclass
class EscapiaSyncResult:
    listings: List[Dict[str, Any]]
    bookings: List[Dict[str, Any]]
    calendar_days: List[Dict[str, Any]]
    errors: List[str]

    @property
    def records_pulled(self) -> int:
        return len(self.listings) + len(self.bookings) + len(self.calendar_days)


class EscapiaSyncService:
    """Fetches Escapia resources with configurable endpoint paths."""

    DEFAULT_BASE_URL = "https://api.escapia.com"

    async def sync(
        self,
        credentials: Dict[str, str],
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> EscapiaSyncResult:
        base_url = credentials.get("base_url", self.DEFAULT_BASE_URL).rstrip("/")
        listings_endpoint = credentials.get("listings_endpoint", "/v1/listings")
        bookings_endpoint = credentials.get("bookings_endpoint", "/v1/bookings")
        calendar_endpoint = credentials.get("calendar_endpoint", "/v1/calendar")

        listings: List[Dict[str, Any]] = []
        bookings: List[Dict[str, Any]] = []
        calendar_days: List[Dict[str, Any]] = []
        errors: List[str] = []

        headers, auth = self._build_auth(credentials)

        async with httpx.AsyncClient(timeout=40.0) as client:
            listings_resp, listings_err = await self._safe_get(
                client=client,
                url=f"{base_url}{listings_endpoint}",
                headers=headers,
                auth=auth,
            )
            if listings_err:
                errors.append(f"listings [{base_url}{listings_endpoint}]: {listings_err}")
            else:
                listings = self._extract_records(listings_resp)

            params: Dict[str, str] = {}
            if start_date:
                params["start_date"] = start_date.isoformat()
            if end_date:
                params["end_date"] = end_date.isoformat()

            bookings_resp, bookings_err = await self._safe_get(
                client=client,
                url=f"{base_url}{bookings_endpoint}",
                headers=headers,
                auth=auth,
                params=params or None,
            )
            if bookings_err:
                errors.append(f"bookings [{base_url}{bookings_endpoint}]: {bookings_err}")
            else:
                bookings = self._extract_records(bookings_resp)

            if listings:
                # Optional pass over calendar endpoint if listing IDs are available.
                listing_ids = [
                    str(item.get("id") or item.get("listing_id"))
                    for item in listings
                    if item.get("id") or item.get("listing_id")
                ][:20]
                for listing_id in listing_ids:
                    calendar_params = {"listing_id": listing_id, **params}
                    cal_resp, cal_err = await self._safe_get(
                        client=client,
                        url=f"{base_url}{calendar_endpoint}",
                        headers=headers,
                        auth=auth,
                        params=calendar_params,
                    )
                    if cal_err:
                        errors.append(f"calendar[{listing_id}] [{base_url}{calendar_endpoint}]: {cal_err}")
                        continue
                    for day in self._extract_records(cal_resp):
                        day["_listing_id"] = listing_id
                        calendar_days.append(day)

        return EscapiaSyncResult(
            listings=listings,
            bookings=bookings,
            calendar_days=calendar_days,
            errors=errors,
        )

    def _build_auth(
        self,
        credentials: Dict[str, str],
    ) -> tuple[Dict[str, str], Optional[httpx.Auth]]:
        headers: Dict[str, str] = {"Accept": "application/json"}

        api_key = credentials.get("api_key")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
            return headers, None

        username = credentials.get("username")
        password = credentials.get("password")
        if username and password:
            return headers, httpx.BasicAuth(username=username, password=password)

        return headers, None

    async def _safe_get(
        self,
        client: httpx.AsyncClient,
        url: str,
        headers: Dict[str, str],
        auth: Optional[httpx.Auth] = None,
        params: Optional[Dict[str, str]] = None,
    ) -> tuple[Optional[Any], Optional[str]]:
        try:
            response = await client.get(url, headers=headers, auth=auth, params=params)
            if response.status_code >= 400:
                body = (response.text or "").strip()
                if not body:
                    try:
                        body = str(response.json())
                    except Exception:
                        body = "<empty response body>"
                return None, f"HTTP {response.status_code}: {body[:400]}"
            return response.json(), None
        except Exception as exc:
            return None, str(exc)

    def _extract_records(self, payload: Any) -> List[Dict[str, Any]]:
        if isinstance(payload, list):
            return [x for x in payload if isinstance(x, dict)]
        if isinstance(payload, dict):
            for key in ("results", "items", "data", "listings", "bookings", "calendar"):
                value = payload.get(key)
                if isinstance(value, list):
                    return [x for x in value if isinstance(x, dict)]
            return [payload]
        return []


_escapia_sync_service: EscapiaSyncService | None = None


def get_escapia_sync_service() -> EscapiaSyncService:
    global _escapia_sync_service
    if _escapia_sync_service is None:
        _escapia_sync_service = EscapiaSyncService()
    return _escapia_sync_service
