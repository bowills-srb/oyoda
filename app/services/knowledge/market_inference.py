"""
market_inference.py — Automatic market detection from property coordinates.

Instead of asking operators to select their market during onboarding,
we infer it from the lat/lng of their imported properties.

Flow:
  1. Properties are imported with coordinates
  2. infer_market_from_properties() finds the geographic centroid
  3. We match that centroid against MARKET_REGISTRY neighborhoods
  4. Fallback: reverse-geocode via Google Geocoding API for unknown markets
  5. Onboarding confirms: "Your properties appear to be in Miami — correct?"

This makes market selection a confirmation step, not a manual choice.
"""

from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass
from typing import List, Optional, Tuple

import httpx

from app.services.knowledge.places_pipeline import (
    MARKET_REGISTRY,
    MarketDefinition,
    Neighborhood,
    get_neighborhood_for_coords,
)

logger = logging.getLogger(__name__)

GOOGLE_GEOCODING_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY", "")  # reuse same key
GEOCODING_URL = "https://maps.googleapis.com/maps/api/geocode/json"


# ─────────────────────────────────────────────────────────────────────────────
# Result types
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class MarketInferenceResult:
    """Result of automatic market detection."""
    market_id: str              # e.g. "MARKET_MIAMI"
    market_name: str            # e.g. "Miami, Florida"
    market_type: str            # "city" | "beach" | "mountain" | "theme_park"
    neighborhood: Optional[str] # e.g. "Brickell" (for city markets)
    confidence: float           # 0-1
    centroid_lat: float
    centroid_lng: float
    property_count: int
    inferred_from: str          # "registry_match" | "geocode" | "fallback"
    confirmation_message: str   # shown to operator: "Your properties appear to be in..."


# ─────────────────────────────────────────────────────────────────────────────
# Core inference engine
# ─────────────────────────────────────────────────────────────────────────────

def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Distance between two lat/lng points in kilometers."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlng / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def compute_centroid(coords: List[Tuple[float, float]]) -> Tuple[float, float]:
    """Compute geographic centroid of a list of (lat, lng) pairs."""
    if not coords:
        return 0.0, 0.0
    lat = sum(c[0] for c in coords) / len(coords)
    lng = sum(c[1] for c in coords) / len(coords)
    return lat, lng


def _match_registry(lat: float, lng: float) -> Optional[Tuple[MarketDefinition, float, Optional[Neighborhood]]]:
    """
    Try to match a coordinate against the MARKET_REGISTRY.

    Returns (market, distance_km, neighborhood) or None if no close match.
    For large markets we match against neighborhood centers. For smaller
    curated markets we match against the market center coordinates.
    """
    best_market: Optional[MarketDefinition] = None
    best_dist: float = float("inf")
    best_hood: Optional[Neighborhood] = None
    THRESHOLD_KM = 60.0

    for market in MARKET_REGISTRY.values():
        if market.neighborhoods:
            for hood in market.neighborhoods:
                dist = haversine_km(lat, lng, hood.center_lat, hood.center_lng)
                if dist < best_dist:
                    best_dist = dist
                    best_market = market
                    best_hood = hood
            continue

        if market.center_lat is None or market.center_lng is None:
            continue
        dist = haversine_km(lat, lng, market.center_lat, market.center_lng)
        if dist < best_dist:
            best_dist = dist
            best_market = market
            best_hood = None

    if best_market and best_dist <= THRESHOLD_KM:
        return best_market, best_dist, best_hood

    return None


async def _reverse_geocode(lat: float, lng: float) -> Optional[dict]:
    """
    Call Google Geocoding API to get city/state/country for a coordinate.
    Returns a dict with 'city', 'state', 'country', 'formatted_address'.
    Returns None if API key not set or call fails.
    """
    if not GOOGLE_GEOCODING_API_KEY:
        return None
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                GEOCODING_URL,
                params={
                    "latlng": f"{lat},{lng}",
                    "key": GOOGLE_GEOCODING_API_KEY,
                    "result_type": "locality|administrative_area_level_2",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        if data.get("status") != "OK" or not data.get("results"):
            return None

        result = data["results"][0]
        components = {c["types"][0]: c["long_name"] for c in result.get("address_components", [])}
        return {
            "city": components.get("locality") or components.get("administrative_area_level_2", ""),
            "state": components.get("administrative_area_level_1", ""),
            "country": components.get("country", ""),
            "formatted_address": result.get("formatted_address", ""),
        }
    except Exception as e:
        logger.debug("[MarketInference] reverse geocode failed: %s", e)
        return None


def _build_dynamic_market_id(city: str, state: str) -> str:
    """Build a market ID for a city not in the registry."""
    clean = city.upper().replace(" ", "_").replace(",", "")
    return f"MARKET_{clean}"


async def infer_market_from_properties(
    property_coords: List[Tuple[float, float]],
    fallback_market_id: Optional[str] = None,
) -> MarketInferenceResult:
    """
    Infer the market for an operator based on their property coordinates.

    Args:
        property_coords: List of (lat, lng) tuples from imported properties
        fallback_market_id: If set, use this if inference fails

    Returns:
        MarketInferenceResult with market_id, name, neighborhood, confidence
    """
    if not property_coords:
        return _fallback_result(fallback_market_id)

    lat, lng = compute_centroid(property_coords)
    count = len(property_coords)

    # ── Step 1: Registry match ────────────────────────────────────────────
    match = _match_registry(lat, lng)
    if match:
        market, dist_km, hood = match

        # Confidence based on distance: 0km = 1.0, 60km = 0.3
        confidence = max(0.3, 1.0 - (dist_km / 60.0) * 0.7)

        # For city markets, find the closest neighborhood specifically
        if market.is_large_city and market.neighborhoods:
            hood = get_neighborhood_for_coords(market.market_id, lat, lng)

        hood_name = hood.name if hood else None
        display = market.display_name
        if hood_name and market.is_large_city:
            display_full = f"{hood_name}, {market.display_name}"
        else:
            display_full = display

        return MarketInferenceResult(
            market_id=market.market_id,
            market_name=market.display_name,
            market_type=market.market_type,
            neighborhood=hood_name,
            confidence=round(confidence, 2),
            centroid_lat=round(lat, 5),
            centroid_lng=round(lng, 5),
            property_count=count,
            inferred_from="registry_match",
            confirmation_message=(
                f"Your properties appear to be in **{display_full}**. Is that correct?"
            ),
        )

    # ── Step 2: Reverse geocode for unknown markets ───────────────────────
    geo = await _reverse_geocode(lat, lng)
    if geo and geo.get("city"):
        city = geo["city"]
        state = geo.get("state", "")
        market_id = _build_dynamic_market_id(city, state)
        display_name = f"{city}, {state}" if state else city

        return MarketInferenceResult(
            market_id=market_id,
            market_name=display_name,
            market_type="city",       # generic default
            neighborhood=None,
            confidence=0.75,          # geocode is reliable but market type unknown
            centroid_lat=round(lat, 5),
            centroid_lng=round(lng, 5),
            property_count=count,
            inferred_from="geocode",
            confirmation_message=(
                f"Your properties appear to be in **{display_name}**. Is that correct?"
            ),
        )

    # ── Step 3: Fallback ─────────────────────────────────────────────────
    return _fallback_result(fallback_market_id, lat, lng, count)


def _fallback_result(
    fallback_market_id: Optional[str] = None,
    lat: float = 0.0,
    lng: float = 0.0,
    count: int = 0,
) -> MarketInferenceResult:
    """Return a low-confidence fallback result."""
    if fallback_market_id and fallback_market_id in MARKET_REGISTRY:
        m = MARKET_REGISTRY[fallback_market_id]
        return MarketInferenceResult(
            market_id=m.market_id,
            market_name=m.display_name,
            market_type=m.market_type,
            neighborhood=None,
            confidence=0.4,
            centroid_lat=lat,
            centroid_lng=lng,
            property_count=count,
            inferred_from="fallback",
            confirmation_message=(
                f"We've set your market to **{m.display_name}**. "
                f"You can change this from your dashboard."
            ),
        )
    return MarketInferenceResult(
        market_id="MARKET_UNKNOWN",
        market_name="Unknown Market",
        market_type="city",
        neighborhood=None,
        confidence=0.1,
        centroid_lat=lat,
        centroid_lng=lng,
        property_count=count,
        inferred_from="fallback",
        confirmation_message=(
            "We couldn't automatically detect your market. "
            "Please select it below so we can personalise your concierge."
        ),
    )


async def infer_market_from_db(
    db_session,
    operator_id: str,
    fallback_market_id: Optional[str] = None,
) -> MarketInferenceResult:
    """
    Infer market from properties already in the database.
    Convenience wrapper used by the onboarding agent and weekly refresh.
    """
    try:
        from sqlalchemy import text
        result = await db_session.execute(
            text("""
                SELECT latitude, longitude
                FROM properties
                WHERE tenant_id = :op
                  AND latitude IS NOT NULL
                  AND longitude IS NOT NULL
                  AND deleted_at IS NULL
            """),
            {"op": operator_id},
        )
        rows = result.fetchall()
        coords = [(float(r[0]), float(r[1])) for r in rows if r[0] and r[1]]
    except Exception as e:
        logger.warning("[MarketInference] DB query failed: %s", e)
        coords = []

    return await infer_market_from_properties(coords, fallback_market_id)
