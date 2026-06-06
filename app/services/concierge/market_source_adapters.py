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
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.knowledge.beach_flag_scraper import get_beach_flag_scraper

logger = logging.getLogger(__name__)

GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY", "")


@dataclass
class MarketSourceContext:
    market_id: str
    market_name: Optional[str]
    market_type: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    sources_config: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MarketSourcePayload:
    live_conditions: List[str] = field(default_factory=list)
    active_alerts: List[str] = field(default_factory=list)
    upcoming_events: List[str] = field(default_factory=list)
    featured_places: List[str] = field(default_factory=list)
    weather_summary: Optional[str] = None
    weather_source: Optional[str] = None
    source_attribution: List[str] = field(default_factory=list)


class MarketSourceAdapter:
    async def fetch(self, context: MarketSourceContext) -> MarketSourcePayload:
        return MarketSourcePayload()


def _source_config(context: MarketSourceContext, key: str) -> Dict[str, Any]:
    if not isinstance(context.sources_config, dict):
        return {}
    cfg = context.sources_config.get(key)
    return cfg if isinstance(cfg, dict) else {}


async def _table_columns(session: AsyncSession, table_name: str) -> set[str]:
    rows = (
        await session.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = :table_name
                """
            ),
            {"table_name": table_name},
        )
    ).fetchall()
    return {str(row[0]) for row in rows}


class MarketEventsDbAdapter(MarketSourceAdapter):
    def __init__(self, session: AsyncSession, limit: int = 3):
        self.session = session
        self.limit = limit

    async def fetch(self, context: MarketSourceContext) -> MarketSourcePayload:
        columns = await _table_columns(self.session, "market_events")
        if not columns or "market_id" not in columns or "title" not in columns:
            return MarketSourcePayload()

        order_expr = "COALESCE(start_date, CURRENT_DATE) ASC"
        if "booking_urgency_score" in columns:
            order_expr = f"COALESCE(booking_urgency_score, 0) DESC, {order_expr}"
        if "guest_relevance_score" in columns:
            order_expr = f"COALESCE(guest_relevance_score, 0) DESC, {order_expr}"

        rows = (
            await self.session.execute(
                text(
                    f"""
                    SELECT title, venue_name, start_date
                    FROM market_events
                    WHERE market_id = :market_id
                      AND COALESCE(is_active, true) = true
                      AND (start_date IS NULL OR start_date >= CURRENT_DATE)
                    ORDER BY {order_expr}
                    LIMIT :limit
                    """
                ),
                {"market_id": context.market_id, "limit": self.limit},
            )
        ).mappings().all()

        events: List[str] = []
        for row in rows:
            title = str(row.get("title") or "").strip()
            if not title:
                continue
            venue = str(row.get("venue_name") or "").strip()
            when = str(row.get("start_date") or "").strip()
            detail = title
            if venue:
                detail += f" at {venue}"
            if when:
                detail += f" on {when}"
            events.append(detail)

        payload = MarketSourcePayload(upcoming_events=events[: self.limit])
        if events:
            payload.source_attribution.append("market_events_db")
        return payload


class WeatherGovAdapter(MarketSourceAdapter):
    def _enabled(self, context: MarketSourceContext) -> bool:
        cfg = _source_config(context, "weather")
        return bool(cfg.get("enabled", True))

    async def fetch(self, context: MarketSourceContext) -> MarketSourcePayload:
        if not self._enabled(context) or context.latitude is None or context.longitude is None:
            return MarketSourcePayload()

        user_agent = "OyvodaMarketBrain/1.0 (ops@oyvoda.com)"
        headers = {
            "User-Agent": user_agent,
            "Accept": "application/geo+json, application/json",
        }
        async with httpx.AsyncClient(timeout=8.0, headers=headers) as client:
            point_resp = await client.get(f"https://api.weather.gov/points/{context.latitude},{context.longitude}")
            point_resp.raise_for_status()
            point_data = point_resp.json().get("properties", {})

            forecast_url = point_data.get("forecast")
            forecast_summary: Optional[str] = None
            if forecast_url:
                forecast_resp = await client.get(forecast_url)
                forecast_resp.raise_for_status()
                periods = forecast_resp.json().get("properties", {}).get("periods", [])
                if periods:
                    first = periods[0]
                    pieces = [
                        str(first.get("name") or "").strip(),
                        f"{first.get('temperature')}\N{DEGREE SIGN}{first.get('temperatureUnit')}"
                        if first.get("temperature") is not None and first.get("temperatureUnit")
                        else "",
                        str(first.get("shortForecast") or "").strip(),
                    ]
                    forecast_summary = " | ".join(piece for piece in pieces if piece)

            alerts: List[str] = []
            alerts_resp = await client.get(
                "https://api.weather.gov/alerts/active",
                params={"point": f"{context.latitude},{context.longitude}"},
            )
            alerts_resp.raise_for_status()
            features = alerts_resp.json().get("features", [])
            for feature in features[:3]:
                props = feature.get("properties", {}) or {}
                event = str(props.get("event") or "").strip()
                headline = str(props.get("headline") or "").strip()
                if event and headline:
                    alerts.append(f"{event}: {headline}")
                elif event:
                    alerts.append(event)

        payload = MarketSourcePayload(
            live_conditions=[f"Weather: {forecast_summary}"] if forecast_summary else [],
            active_alerts=alerts,
            weather_summary=forecast_summary,
            weather_source="weather.gov",
            source_attribution=["weather.gov"],
        )
        return payload


class BeachFlagAdapter(MarketSourceAdapter):
    async def fetch(self, context: MarketSourceContext) -> MarketSourcePayload:
        if context.market_type != "beach":
            return MarketSourcePayload()

        beach_cfg = context.sources_config.get("beach_flag") if isinstance(context.sources_config, dict) else None
        enabled = True
        if isinstance(beach_cfg, dict):
            enabled = bool(beach_cfg.get("enabled", True))
        elif context.market_id != "MARKET_30A":
            enabled = False
        if not enabled:
            return MarketSourcePayload()

        conditions = await get_beach_flag_scraper().get_current_conditions()
        payload = MarketSourcePayload(
            live_conditions=[f"Beach conditions: {conditions.display_flag}"],
            source_attribution=[conditions.source],
        )
        if not conditions.swimming_allowed:
            payload.active_alerts.append(f"Beach access warning: {conditions.display_flag}")
        return payload


class GooglePlacesAdapter(MarketSourceAdapter):
    SEARCH_URL = "https://places.googleapis.com/v1/places:searchNearby"

    def _enabled(self, context: MarketSourceContext) -> bool:
        cfg = _source_config(context, "google_places")
        if cfg:
            return bool(cfg.get("enabled", True))
        return True

    def _types_for_market(self, market_type: Optional[str]) -> list[str]:
        if market_type == "beach":
            return ["restaurant", "grocery_store", "pharmacy"]
        if market_type == "mountain":
            return ["restaurant", "grocery_store", "tourist_attraction"]
        return ["restaurant", "grocery_store", "hospital"]

    def _radius_for_context(self, context: MarketSourceContext) -> float:
        cfg = _source_config(context, "google_places")
        configured = cfg.get("radius_meters")
        if configured is not None:
            try:
                return max(500.0, min(float(configured), 50000.0))
            except (TypeError, ValueError):
                pass
        defaults = {
            "beach": 3200.0,
            "mountain": 4500.0,
            "theme_park": 6000.0,
            "city": 2500.0,
        }
        return defaults.get((context.market_type or "").lower(), 4000.0)

    def _max_results_for_context(self, context: MarketSourceContext) -> int:
        cfg = _source_config(context, "google_places")
        configured = cfg.get("max_result_count")
        if configured is not None:
            try:
                return max(1, min(int(configured), 10))
            except (TypeError, ValueError):
                pass
        return 5

    def _included_types_for_context(self, context: MarketSourceContext) -> list[str]:
        cfg = _source_config(context, "google_places")
        configured = cfg.get("included_types")
        if isinstance(configured, list):
            cleaned = [str(item).strip() for item in configured if str(item).strip()]
            if cleaned:
                return cleaned[:5]
        return self._types_for_market(context.market_type)

    async def fetch(self, context: MarketSourceContext) -> MarketSourcePayload:
        if not GOOGLE_PLACES_API_KEY or not self._enabled(context):
            return MarketSourcePayload()
        if context.latitude is None or context.longitude is None:
            return MarketSourcePayload()

        headers = {
            "X-Goog-Api-Key": GOOGLE_PLACES_API_KEY,
            "X-Goog-FieldMask": (
                "places.displayName,places.formattedAddress,places.primaryType,places.rating"
            ),
        }
        body = {
            "includedTypes": self._included_types_for_context(context),
            "maxResultCount": self._max_results_for_context(context),
            "locationRestriction": {
                "circle": {
                    "center": {"latitude": context.latitude, "longitude": context.longitude},
                    "radius": self._radius_for_context(context),
                }
            },
        }
        async with httpx.AsyncClient(timeout=8.0, headers=headers) as client:
            response = await client.post(self.SEARCH_URL, json=body)
            response.raise_for_status()
            data = response.json()

        places: List[str] = []
        for item in data.get("places", [])[:3]:
            name = ((item.get("displayName") or {}).get("text") or "").strip()
            address = str(item.get("formattedAddress") or "").strip()
            primary_type = str(item.get("primaryType") or "").replace("_", " ").strip()
            if not name:
                continue
            detail = name
            if primary_type:
                detail += f" ({primary_type})"
            if address:
                detail += f" — {address}"
            places.append(detail)

        payload = MarketSourcePayload(featured_places=places)
        if places:
            payload.source_attribution.append("google_places")
        return payload


def _merge_payloads(payloads: List[MarketSourcePayload]) -> MarketSourcePayload:
    merged = MarketSourcePayload()
    for payload in payloads:
        for value in payload.live_conditions:
            if value and value not in merged.live_conditions:
                merged.live_conditions.append(value)
        for value in payload.active_alerts:
            if value and value not in merged.active_alerts:
                merged.active_alerts.append(value)
        for value in payload.upcoming_events:
            if value and value not in merged.upcoming_events:
                merged.upcoming_events.append(value)
        for value in payload.featured_places:
            if value and value not in merged.featured_places:
                merged.featured_places.append(value)
        for value in payload.source_attribution:
            if value and value not in merged.source_attribution:
                merged.source_attribution.append(value)
        if payload.weather_summary and not merged.weather_summary:
            merged.weather_summary = payload.weather_summary
        if payload.weather_source and not merged.weather_source:
            merged.weather_source = payload.weather_source
    return merged


async def assemble_market_source_payload(
    session: AsyncSession,
    context: MarketSourceContext,
) -> MarketSourcePayload:
    adapters: List[MarketSourceAdapter] = [
        MarketEventsDbAdapter(session),
        WeatherGovAdapter(),
        BeachFlagAdapter(),
        GooglePlacesAdapter(),
    ]
    payloads: List[MarketSourcePayload] = []
    for adapter in adapters:
        try:
            payloads.append(await adapter.fetch(context))
        except Exception as exc:
            logger.debug("[MarketSources] adapter %s skipped: %s", adapter.__class__.__name__, exc)
    return _merge_payloads(payloads)
