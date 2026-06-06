"""
places_pipeline.py — Dynamic local knowledge seeding via Google Places API.

Replaces the static local_area_data.py approach for large, multi-neighborhood
markets (Miami, Orlando, Tampa, etc.) where a curated static file is not
scalable.

Flow:
  1. Operator registers a geofence polygon during onboarding
  2. PlacesPipeline.seed_market() fires automatically
  3. We query Google Places for each category within the polygon
  4. Results are normalized into Place objects and indexed into the vector store
  5. The knowledge indexer and local intelligence service consume them normally

For tight curated markets (30A, Destin), the static local_area_data.py
continues to be used — this pipeline supplements, not replaces it.

Google Places API (New) pricing (2026):
  - Nearby Search: $0.032/request
  - Place Details: $0.017/request
  - Text Search:   $0.032/request
  A full Miami seed (~15 neighborhoods × 8 categories) = ~120 requests ≈ $3.84
  Re-seed runs weekly — ~$15/month per large market.

Set GOOGLE_PLACES_API_KEY in Railway env vars to enable.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY", "")

# ─────────────────────────────────────────────────────────────────────────────
# Market registry — knows how to slice large cities into neighborhoods
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Neighborhood:
    """A geographic sub-zone within a large market."""
    name: str           # Human name, e.g. "South Beach"
    slug: str           # machine slug, e.g. "south_beach"
    center_lat: float
    center_lng: float
    radius_km: float    # Search radius for Places API
    tags: List[str] = field(default_factory=list)  # e.g. ["beachfront", "nightlife"]


@dataclass
class MarketDefinition:
    """Defines how a market is structured for local intelligence seeding."""
    market_id: str
    display_name: str
    market_type: str            # beach | city | mountain | lake | theme_park
    is_large_city: bool         # True → use Places API, False → use static file
    center_lat: Optional[float] = None
    center_lng: Optional[float] = None
    neighborhoods: List[Neighborhood] = field(default_factory=list)
    # For small markets, which communities from local_area_data.py to use
    static_communities: List[str] = field(default_factory=list)
    # Concierge persona name suggestions by market type
    name_suggestions: List[str] = field(default_factory=list)


MARKET_REGISTRY: Dict[str, MarketDefinition] = {
    # ── Existing curated markets (static file) ────────────────────────────
    "MARKET_30A": MarketDefinition(
        market_id="MARKET_30A",
        display_name="30A Florida",
        market_type="beach",
        is_large_city=False,
        center_lat=30.2833,
        center_lng=-86.0167,
        static_communities=[
            "watercolor", "seaside", "seagrove", "rosemary_beach",
            "alys_beach", "watersound", "seacrest", "inlet_beach",
            "grayton_beach", "santa_rosa",
        ],
        name_suggestions=["Coral", "Sandy", "Marina", "Shelly", "Finn"],
    ),
    "MARKET_DESTIN": MarketDefinition(
        market_id="MARKET_DESTIN",
        display_name="Destin Florida",
        market_type="beach",
        is_large_city=False,
        center_lat=30.3935,
        center_lng=-86.4958,
        static_communities=["destin"],
        name_suggestions=["Coral", "Sandy", "Reef", "Gulf"],
    ),
    "MARKET_PCB": MarketDefinition(
        market_id="MARKET_PCB",
        display_name="Panama City Beach",
        market_type="beach",
        is_large_city=False,
        center_lat=30.1766,
        center_lng=-85.8055,
        static_communities=["panama_city_beach"],
        name_suggestions=["Sandy", "Surf", "Gulf", "Wave"],
    ),

    # ── Large city markets (Places API) ───────────────────────────────────
    "MARKET_MIAMI": MarketDefinition(
        market_id="MARKET_MIAMI",
        display_name="Miami, Florida",
        market_type="city",
        is_large_city=True,
        name_suggestions=["Sol", "Biscayne", "Bay", "Cayo", "Mia"],
        neighborhoods=[
            Neighborhood("South Beach",       "south_beach",      25.7907, -80.1300, 1.8,
                         ["beachfront", "nightlife", "art_deco", "tourist"]),
            Neighborhood("Mid Beach",         "mid_beach",        25.8100, -80.1220, 1.5,
                         ["beachfront", "family", "quieter"]),
            Neighborhood("Bal Harbour / Surfside", "bal_harbour", 25.8900, -80.1220, 2.0,
                         ["luxury", "shopping", "beachfront"]),
            Neighborhood("Sunny Isles Beach", "sunny_isles",      25.9400, -80.1220, 2.0,
                         ["high_rise", "beachfront", "family"]),
            Neighborhood("Brickell",          "brickell",         25.7600, -80.1950, 1.5,
                         ["urban", "financial_district", "rooftop_bars", "young_professional"]),
            Neighborhood("Downtown Miami",    "downtown",         25.7750, -80.1950, 1.5,
                         ["urban", "business", "arts", "bayside"]),
            Neighborhood("Wynwood",           "wynwood",          25.8020, -80.1990, 1.2,
                         ["art", "galleries", "street_art", "food_hall", "trendy"]),
            Neighborhood("Design District",   "design_district",  25.8120, -80.1930, 1.0,
                         ["luxury_shopping", "restaurants", "art", "upscale"]),
            Neighborhood("Little Havana",     "little_havana",    25.7700, -80.2300, 1.5,
                         ["cuban_culture", "calle_ocho", "authentic", "historic"]),
            Neighborhood("Coconut Grove",     "coconut_grove",    25.7300, -80.2400, 1.8,
                         ["bohemian", "waterfront", "marina", "family", "village"]),
            Neighborhood("Coral Gables",      "coral_gables",     25.7200, -80.2680, 2.0,
                         ["upscale", "mediterranean", "restaurants", "family"]),
            Neighborhood("Edgewater",         "edgewater",        25.8000, -80.1870, 1.0,
                         ["waterfront", "modern", "galleries", "up_and_coming"]),
            Neighborhood("Key Biscayne",      "key_biscayne",     25.6910, -80.1620, 2.0,
                         ["island", "beachfront", "park", "family", "secluded"]),
            Neighborhood("Aventura",          "aventura",         25.9520, -80.1420, 2.0,
                         ["shopping_mall", "high_rise", "family", "affluent"]),
        ],
    ),

    "MARKET_ORLANDO": MarketDefinition(
        market_id="MARKET_ORLANDO",
        display_name="Orlando, Florida",
        market_type="theme_park",
        is_large_city=True,
        name_suggestions=["Pixie", "Magic", "Scout", "Orbit", "Spark"],
        neighborhoods=[
            Neighborhood("Walt Disney World Area", "wdw_area",     28.3852, -81.5639, 5.0,
                         ["disney", "theme_park", "family", "resort"]),
            Neighborhood("International Drive",    "i_drive",      28.4312, -81.4695, 3.0,
                         ["tourist", "restaurants", "attractions", "nightlife"]),
            Neighborhood("Kissimmee",              "kissimmee",    28.2919, -81.4076, 4.0,
                         ["family", "budget_friendly", "vacation_homes"]),
            Neighborhood("Universal Studios Area", "universal",    28.4747, -81.4674, 2.0,
                         ["universal", "theme_park", "family"]),
            Neighborhood("Lake Buena Vista",       "lbv",          28.3699, -81.5103, 2.5,
                         ["shopping", "disney_adjacent", "restaurants"]),
            Neighborhood("ChampionsGate",          "champions_gate", 28.2600, -81.6000, 3.0,
                         ["golf", "resort", "vacation_homes", "family"]),
            Neighborhood("Winter Garden / Horizon West", "horizon_west", 28.5250, -81.6000, 3.0,
                         ["residential", "family", "newer_development"]),
        ],
    ),

    "MARKET_TAMPA": MarketDefinition(
        market_id="MARKET_TAMPA",
        display_name="Tampa Bay, Florida",
        market_type="city",
        is_large_city=True,
        name_suggestions=["Bay", "Palma", "Gulf", "Surge"],
        neighborhoods=[
            Neighborhood("Ybor City",        "ybor_city",      27.9600, -82.4400, 1.5,
                         ["historic", "nightlife", "cuban_heritage", "restaurants"]),
            Neighborhood("Downtown Tampa",   "downtown_tampa", 27.9480, -82.4600, 1.5,
                         ["urban", "riverwalk", "business"]),
            Neighborhood("Hyde Park",        "hyde_park",      27.9320, -82.4700, 1.2,
                         ["upscale", "shopping", "restaurants", "walkable"]),
            Neighborhood("Channelside",      "channelside",    27.9430, -82.4510, 1.0,
                         ["waterfront", "entertainment", "nightlife"]),
            Neighborhood("St. Pete Beach",   "st_pete_beach",  27.7300, -82.7400, 2.5,
                         ["beachfront", "family", "waterfront"]),
            Neighborhood("Clearwater Beach", "clearwater_beach", 27.9780, -82.8270, 2.0,
                         ["beachfront", "tourist", "family", "award_winning"]),
            Neighborhood("St. Petersburg",   "st_pete",        27.7700, -82.6400, 3.0,
                         ["arts", "waterfront", "restaurants", "museums"]),
        ],
    ),

    "MARKET_KEYS": MarketDefinition(
        market_id="MARKET_KEYS",
        display_name="Florida Keys",
        market_type="beach",
        is_large_city=True,
        name_suggestions=["Reef", "Conch", "Keys", "Cayo", "Marlin"],
        neighborhoods=[
            Neighborhood("Key Largo",       "key_largo",   25.0865, -80.4473, 5.0,
                         ["diving", "snorkeling", "fishing", "eco_tours"]),
            Neighborhood("Islamorada",      "islamorada",  24.9246, -80.6274, 4.0,
                         ["fishing_capital", "restaurants", "sunsets", "boutique"]),
            Neighborhood("Marathon",        "marathon",    24.7214, -81.0854, 4.0,
                         ["family", "diving", "turtle_hospital", "midway"]),
            Neighborhood("Big Pine Key",    "big_pine",    24.6686, -81.3596, 5.0,
                         ["wildlife", "key_deer", "quiet", "snorkeling"]),
            Neighborhood("Key West",        "key_west",    24.5551, -81.7800, 3.0,
                         ["historic", "nightlife", "duval_street", "southernmost"]),
        ],
    ),

    "MARKET_NAPLES": MarketDefinition(
        market_id="MARKET_NAPLES",
        display_name="Naples / Fort Myers, Florida",
        market_type="beach",
        is_large_city=True,
        name_suggestions=["Gulf", "Palm", "Marco", "Bay"],
        neighborhoods=[
            Neighborhood("Naples",            "naples",       26.1420, -81.7948, 3.0,
                         ["luxury", "shopping", "beachfront", "golf"]),
            Neighborhood("Marco Island",      "marco_island", 25.9406, -81.7177, 3.0,
                         ["beachfront", "family", "fishing", "resort"]),
            Neighborhood("Fort Myers Beach",  "ft_myers_beach", 26.4505, -81.9531, 2.5,
                         ["beachfront", "family", "casual", "fishing"]),
            Neighborhood("Bonita Springs",    "bonita_springs", 26.3398, -81.7787, 3.0,
                         ["beachfront", "golf", "family", "quieter"]),
            Neighborhood("Cape Coral",        "cape_coral",   26.5629, -81.9495, 4.0,
                         ["canal_city", "boating", "family", "waterfront"]),
        ],
    ),
}


# ─────────────────────────────────────────────────────────────────────────────
# Category → Google Places type mapping
# ─────────────────────────────────────────────────────────────────────────────

PLACE_CATEGORIES: List[Dict[str, Any]] = [
    {"oyvoda_type": "dining_fine",      "google_type": "restaurant",          "keyword": "fine dining restaurant",     "max_results": 8},
    {"oyvoda_type": "dining_casual",    "google_type": "restaurant",          "keyword": "casual restaurant",          "max_results": 10},
    {"oyvoda_type": "dining_seafood",   "google_type": "restaurant",          "keyword": "seafood restaurant",         "max_results": 8},
    {"oyvoda_type": "dining_breakfast", "google_type": "restaurant",          "keyword": "breakfast brunch",           "max_results": 6},
    {"oyvoda_type": "dining_coffee",    "google_type": "cafe",                "keyword": "coffee shop cafe",           "max_results": 5},
    {"oyvoda_type": "activity_outdoor", "google_type": "tourist_attraction",  "keyword": "outdoor activities park",    "max_results": 8},
    {"oyvoda_type": "activity_water",   "google_type": "tourist_attraction",  "keyword": "water sports snorkeling diving kayak", "max_results": 6},
    {"oyvoda_type": "retail_grocery",   "google_type": "grocery_or_supermarket", "keyword": "grocery store",           "max_results": 4},
    {"oyvoda_type": "service_spa",      "google_type": "spa",                 "keyword": "spa massage wellness",       "max_results": 4},
    {"oyvoda_type": "attraction_entertainment", "google_type": "tourist_attraction", "keyword": "entertainment nightlife bar", "max_results": 6},
]


# ─────────────────────────────────────────────────────────────────────────────
# PlacesPipeline
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SeededPlace:
    """A place returned from the Places API, ready for indexing."""
    name: str
    category: str           # matches oyvoda_type
    neighborhood: str       # neighborhood slug
    neighborhood_display: str
    market_id: str
    lat: float
    lng: float
    address: str
    rating: Optional[float]
    review_count: int
    price_level: str        # "$", "$$", "$$$", "$$$$"
    google_place_id: str
    types: List[str]
    opening_hours: Optional[str]
    phone: Optional[str]
    website: Optional[str]
    source: str = "google_places"
    seeded_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class SeedResult:
    """Result of seeding a market."""
    market_id: str
    neighborhoods_seeded: int
    places_found: int
    places_indexed: int
    by_category: Dict[str, int]
    errors: List[str]
    duration_seconds: float


class PlacesPipeline:
    """
    Seeds the local knowledge base for any market using Google Places API.

    Usage:
        pipeline = PlacesPipeline()

        # Full market seed (runs during onboarding)
        result = await pipeline.seed_market(
            market_id="MARKET_MIAMI",
            operator_id="op_brickell_stays",
            operator_geofence_lat=25.760,
            operator_geofence_lng=-80.195,
            radius_km=3.0,          # operator's property radius
        )

        # Re-seed specific neighborhood (runs weekly)
        result = await pipeline.seed_neighborhood(
            market_id="MARKET_MIAMI",
            neighborhood_slug="brickell",
            operator_id="op_brickell_stays",
        )
    """

    NEARBY_SEARCH_URL = "https://places.googleapis.com/v1/places:searchNearby"
    TEXT_SEARCH_URL   = "https://places.googleapis.com/v1/places:searchText"
    DETAILS_URL       = "https://places.googleapis.com/v1/places/{place_id}"

    def __init__(self):
        self.api_key = GOOGLE_PLACES_API_KEY
        self._request_count = 0
        self._last_request_at: Optional[datetime] = None

    def is_available(self) -> bool:
        return bool(self.api_key)

    # ── Public API ────────────────────────────────────────────────────────

    async def seed_market(
        self,
        market_id: str,
        operator_id: str,
        operator_geofence_lat: float,
        operator_geofence_lng: float,
        radius_km: float = 3.0,
        db_session=None,
    ) -> SeedResult:
        """
        Seed local knowledge for an operator's market.

        Strategy:
        - For large city markets: find which neighborhood(s) the operator's
          properties fall within, seed those neighborhoods specifically.
        - For small/beach markets: use static local_area_data.py (no API call).

        Args:
            market_id:                  e.g. "MARKET_MIAMI"
            operator_id:                operator's ID
            operator_geofence_lat/lng:  centroid of operator's property cluster
            radius_km:                  search radius around each neighborhood center
            db_session:                 optional AsyncSession for indexing
        """
        start = datetime.now(timezone.utc)
        market = MARKET_REGISTRY.get(market_id)

        if not market:
            return SeedResult(
                market_id=market_id,
                neighborhoods_seeded=0, places_found=0, places_indexed=0,
                by_category={}, errors=[f"Unknown market: {market_id}"],
                duration_seconds=0,
            )

        if not market.is_large_city:
            # Static market — nothing to do, knowledge_indexer handles it
            return SeedResult(
                market_id=market_id,
                neighborhoods_seeded=0, places_found=0, places_indexed=0,
                by_category={}, errors=[],
                duration_seconds=0,
            )

        if not self.is_available():
            logger.warning(
                "[PlacesPipeline] GOOGLE_PLACES_API_KEY not set — "
                "local area knowledge will be empty for %s", market_id
            )
            return SeedResult(
                market_id=market_id,
                neighborhoods_seeded=0, places_found=0, places_indexed=0,
                by_category={},
                errors=["GOOGLE_PLACES_API_KEY not configured — set in Railway env vars"],
                duration_seconds=0,
            )

        # Find which neighborhoods are relevant to this operator
        relevant_hoods = self._find_relevant_neighborhoods(
            market, operator_geofence_lat, operator_geofence_lng, radius_km
        )

        all_places: List[SeededPlace] = []
        by_category: Dict[str, int] = {}
        errors: List[str] = []
        indexed = 0

        for hood in relevant_hoods:
            for category in PLACE_CATEGORIES:
                try:
                    places = await self._search_nearby(
                        lat=hood.center_lat,
                        lng=hood.center_lng,
                        radius_meters=int(hood.radius_km * 1000),
                        google_type=category["google_type"],
                        keyword=category.get("keyword", ""),
                        max_results=category["max_results"],
                        neighborhood=hood,
                        market_id=market_id,
                        oyvoda_category=category["oyvoda_type"],
                    )
                    all_places.extend(places)
                    by_category[category["oyvoda_type"]] = (
                        by_category.get(category["oyvoda_type"], 0) + len(places)
                    )
                    # Rate limiting — 100ms between requests
                    await asyncio.sleep(0.1)
                except Exception as e:
                    errors.append(f"{hood.slug}/{category['oyvoda_type']}: {e}")
                    logger.warning("[PlacesPipeline] %s", errors[-1])

        # Deduplicate by google_place_id
        seen: set = set()
        unique_places = []
        for p in all_places:
            if p.google_place_id not in seen:
                seen.add(p.google_place_id)
                unique_places.append(p)

        # Index into vector store if db_session provided
        if db_session and unique_places:
            indexed = await self._index_places(unique_places, operator_id, db_session)

        duration = (datetime.now(timezone.utc) - start).total_seconds()

        logger.info(
            "[PlacesPipeline] %s seeded: %d neighborhoods, %d unique places, "
            "%d indexed, %.1fs, %d errors",
            market_id, len(relevant_hoods), len(unique_places),
            indexed, duration, len(errors),
        )

        return SeedResult(
            market_id=market_id,
            neighborhoods_seeded=len(relevant_hoods),
            places_found=len(unique_places),
            places_indexed=indexed,
            by_category=by_category,
            errors=errors,
            duration_seconds=duration,
        )

    async def seed_neighborhood(
        self,
        market_id: str,
        neighborhood_slug: str,
        operator_id: str,
        db_session=None,
    ) -> SeedResult:
        """Re-seed a single neighborhood (for weekly refresh jobs)."""
        market = MARKET_REGISTRY.get(market_id)
        if not market:
            return SeedResult(market_id=market_id, neighborhoods_seeded=0,
                              places_found=0, places_indexed=0, by_category={},
                              errors=[f"Unknown market: {market_id}"], duration_seconds=0)

        hood = next((n for n in market.neighborhoods if n.slug == neighborhood_slug), None)
        if not hood:
            return SeedResult(market_id=market_id, neighborhoods_seeded=0,
                              places_found=0, places_indexed=0, by_category={},
                              errors=[f"Unknown neighborhood: {neighborhood_slug}"], duration_seconds=0)

        # Temporarily override relevant_hoods to just this one
        original_neighborhoods = market.neighborhoods
        market.neighborhoods = [hood]
        result = await self.seed_market(
            market_id=market_id,
            operator_id=operator_id,
            operator_geofence_lat=hood.center_lat,
            operator_geofence_lng=hood.center_lng,
            radius_km=hood.radius_km,
            db_session=db_session,
        )
        market.neighborhoods = original_neighborhoods
        return result

    # ── Internal helpers ──────────────────────────────────────────────────

    def _find_relevant_neighborhoods(
        self,
        market: MarketDefinition,
        op_lat: float,
        op_lng: float,
        operator_radius_km: float,
    ) -> List[Neighborhood]:
        """
        Return neighborhoods whose center is within operator_radius_km * 2
        of the operator's centroid.  Always returns at least 1 neighborhood.
        """
        import math

        def haversine(lat1, lng1, lat2, lng2) -> float:
            R = 6371
            dlat = math.radians(lat2 - lat1)
            dlng = math.radians(lng2 - lng1)
            a = (math.sin(dlat/2)**2 +
                 math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
                 math.sin(dlng/2)**2)
            return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

        threshold_km = max(operator_radius_km * 2.5, 3.0)
        candidates = []
        for hood in market.neighborhoods:
            dist = haversine(op_lat, op_lng, hood.center_lat, hood.center_lng)
            candidates.append((dist, hood))

        candidates.sort(key=lambda x: x[0])

        # Always include the closest neighborhood
        within = [h for d, h in candidates if d <= threshold_km]
        if not within:
            within = [candidates[0][1]]

        return within

    async def _search_nearby(
        self,
        lat: float,
        lng: float,
        radius_meters: int,
        google_type: str,
        keyword: str,
        max_results: int,
        neighborhood: Neighborhood,
        market_id: str,
        oyvoda_category: str,
    ) -> List[SeededPlace]:
        """Call Google Places Nearby Search (New) and return SeededPlace objects."""
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": (
                "places.id,places.displayName,places.formattedAddress,"
                "places.location,places.rating,places.userRatingCount,"
                "places.priceLevel,places.types,places.nationalPhoneNumber,"
                "places.websiteUri,places.currentOpeningHours"
            ),
        }

        body = {
            "includedTypes": [google_type],
            "locationRestriction": {
                "circle": {
                    "center": {"latitude": lat, "longitude": lng},
                    "radius": float(radius_meters),
                }
            },
            "maxResultCount": min(max_results, 20),
            "rankPreference": "POPULARITY",
        }
        if keyword:
            body["textQuery"] = keyword  # acts as an additional filter

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(self.NEARBY_SEARCH_URL, json=body, headers=headers)
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:
            raise RuntimeError(f"Google Places API error: {e}") from e

        places = []
        for item in data.get("places", []):
            try:
                place = self._normalize_place(
                    item, neighborhood, market_id, oyvoda_category
                )
                places.append(place)
            except Exception as e:
                logger.debug("[PlacesPipeline] normalize error: %s", e)

        return places

    def _normalize_place(
        self,
        item: Dict[str, Any],
        neighborhood: Neighborhood,
        market_id: str,
        oyvoda_category: str,
    ) -> SeededPlace:
        """Convert a Google Places API response item into a SeededPlace."""
        price_map = {
            "PRICE_LEVEL_FREE": "$",
            "PRICE_LEVEL_INEXPENSIVE": "$",
            "PRICE_LEVEL_MODERATE": "$$",
            "PRICE_LEVEL_EXPENSIVE": "$$$",
            "PRICE_LEVEL_VERY_EXPENSIVE": "$$$$",
        }
        loc = item.get("location", {})
        hours_periods = (item.get("currentOpeningHours") or {}).get("weekdayDescriptions", [])
        hours_str = " | ".join(hours_periods[:2]) if hours_periods else None

        return SeededPlace(
            name=item.get("displayName", {}).get("text", "Unknown"),
            category=oyvoda_category,
            neighborhood=neighborhood.slug,
            neighborhood_display=neighborhood.name,
            market_id=market_id,
            lat=loc.get("latitude", neighborhood.center_lat),
            lng=loc.get("longitude", neighborhood.center_lng),
            address=item.get("formattedAddress", ""),
            rating=item.get("rating"),
            review_count=item.get("userRatingCount", 0),
            price_level=price_map.get(item.get("priceLevel", ""), "$$"),
            google_place_id=item.get("id", ""),
            types=item.get("types", []),
            opening_hours=hours_str,
            phone=item.get("nationalPhoneNumber"),
            website=item.get("websiteUri"),
        )

    async def _index_places(
        self,
        places: List[SeededPlace],
        operator_id: str,
        db_session,
    ) -> int:
        """Index places into the vector store via KnowledgeIndexer."""
        try:
            from app.services.knowledge.knowledge_indexer import KnowledgeIndexer, DocType
            from app.services.knowledge.vector_store import Document

            indexer = KnowledgeIndexer(db_session)
            store = await indexer._get_store()

            documents = []
            for p in places:
                # Build rich searchable text
                parts = [f"{p.category.replace('_', ' ').title()}: {p.name}"]
                parts.append(f"in {p.neighborhood_display}, {p.market_id.replace('MARKET_', '').title()}")
                if p.price_level:
                    parts.append(f"({p.price_level})")
                if p.address:
                    parts.append(f". Address: {p.address}.")
                if p.rating:
                    parts.append(f"Rated {p.rating}/5 ({p.review_count} reviews).")
                if p.opening_hours:
                    parts.append(f"Hours: {p.opening_hours}.")
                if p.phone:
                    parts.append(f"Phone: {p.phone}.")
                if p.types:
                    readable_types = [t.replace("_", " ") for t in p.types[:3]]
                    parts.append(f"Type: {', '.join(readable_types)}.")

                documents.append(Document(
                    content=" ".join(parts),
                    metadata={
                        "operator_id": operator_id,
                        "doc_type": p.category,
                        "name": p.name,
                        "neighborhood": p.neighborhood,
                        "neighborhood_display": p.neighborhood_display,
                        "market_id": p.market_id,
                        "lat": p.lat,
                        "lng": p.lng,
                        "rating": p.rating,
                        "review_count": p.review_count,
                        "price_level": p.price_level,
                        "google_place_id": p.google_place_id,
                        "source": "google_places",
                    }
                ))

            result = await store.add_documents(documents)
            return result.get("inserted", 0) + result.get("updated", 0)

        except Exception as e:
            logger.warning("[PlacesPipeline] index error: %s", e)
            return 0


# ─────────────────────────────────────────────────────────────────────────────
# Market lookup helpers used by onboarding agent + knowledge indexer
# ─────────────────────────────────────────────────────────────────────────────

def get_market(market_id: str) -> Optional[MarketDefinition]:
    return MARKET_REGISTRY.get(market_id)


def is_large_city_market(market_id: str) -> bool:
    m = get_market(market_id)
    return m.is_large_city if m else False


def get_name_suggestions(market_id: str) -> List[str]:
    m = get_market(market_id)
    return m.name_suggestions if m else ["Coral", "Scout", "Guide"]


def get_neighborhood_for_coords(
    market_id: str,
    lat: float,
    lng: float,
) -> Optional[Neighborhood]:
    """Return the closest neighborhood to a given coordinate."""
    import math
    m = get_market(market_id)
    if not m or not m.neighborhoods:
        return None

    def dist(hood: Neighborhood) -> float:
        dlat = math.radians(lat - hood.center_lat)
        dlng = math.radians(lng - hood.center_lng)
        a = (math.sin(dlat/2)**2 +
             math.cos(math.radians(lat)) * math.cos(math.radians(hood.center_lat)) *
             math.sin(dlng/2)**2)
        return 6371 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return min(m.neighborhoods, key=dist)


# ─────────────────────────────────────────────────────────────────────────────
# Weekly refresh scheduler — called from main.py background workers
# ─────────────────────────────────────────────────────────────────────────────

async def run_weekly_places_refresh(db_session) -> None:
    """
    Refresh Places API data for all large-city markets with active operators.
    Called weekly from the background worker scheduler in main.py.
    """
    if not GOOGLE_PLACES_API_KEY:
        return

    try:
        from sqlalchemy import text
        result = await db_session.execute(
            text("""
                SELECT DISTINCT market_id, tenant_id,
                       ST_Y(ST_Centroid(geofence_polygon)) AS lat,
                       ST_X(ST_Centroid(geofence_polygon)) AS lng
                FROM geofences
                WHERE purpose = 'primary_market'
                  AND deleted_at IS NULL
            """)
        )
        rows = result.mappings().all()
    except Exception as e:
        logger.warning("[PlacesPipeline] weekly refresh DB query failed: %s", e)
        return

    pipeline = PlacesPipeline()
    for row in rows:
        market_id = row.get("market_id", "")
        if not is_large_city_market(market_id):
            continue
        try:
            result = await pipeline.seed_market(
                market_id=market_id,
                operator_id=row["tenant_id"],
                operator_geofence_lat=float(row["lat"]),
                operator_geofence_lng=float(row["lng"]),
                db_session=db_session,
            )
            logger.info(
                "[PlacesPipeline] weekly refresh %s: %d places",
                market_id, result.places_indexed,
            )
        except Exception as e:
            logger.warning("[PlacesPipeline] weekly refresh error for %s: %s", market_id, e)
