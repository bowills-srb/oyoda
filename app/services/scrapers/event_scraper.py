"""
event_scraper.py — Market-parameterized event scraping with TTL-aware indexing.

Pulls hyper-local event data for any operator market and indexes it into the
knowledge base with automatic expiration so Coral never recommends past events.

Architecture:
  - EventSource: abstract base, one concrete implementation per data source
  - MarketEventScraper: orchestrates sources for a given market_id
  - TTL-aware indexing: events expire from vector store after their end date
  - Demand pressure signals: high-attendance events emit DEMAND_PRESSURE signals
    which Coral uses to warn guests about crowds, suggest early reservations, etc.

Supported sources (2026):
  - Google Places API "events nearby" search
  - Eventbrite public API (no auth required for public events)
  - VisitFlorida / regional tourism board scrapers (market-specific)
  - Existing 30A sources: 30a.com events, VisitSouthWalton (already built)

To add a new market's event sources, add entries to MARKET_EVENT_SOURCES below.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional
from abc import ABC, abstractmethod

import httpx

logger = logging.getLogger(__name__)

GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY", "")
EVENTBRITE_TOKEN = os.getenv("EVENTBRITE_TOKEN", "")  # optional, improves rate limits


# ─────────────────────────────────────────────────────────────────────────────
# Event data model
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class MarketEvent:
    """A local event scraped from any source."""
    event_id: str               # stable dedup key (hash of name+date+market)
    name: str
    description: str
    market_id: str
    neighborhood: Optional[str]  # None = whole market
    start_date: date
    end_date: date
    venue: str
    venue_lat: Optional[float]
    venue_lng: Optional[float]
    category: str               # music | art | food | sports | festival | holiday | other
    attendance_estimate: str    # "small" | "medium" | "large" | "massive"
    is_free: bool
    ticket_url: Optional[str]
    source: str
    demand_pressure: float      # 0-1, fed into concierge signals
    scraped_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def is_current(self) -> bool:
        """True if event is happening now or in the future."""
        return self.end_date >= date.today()

    @property
    def ttl_days(self) -> int:
        """Days until this event should expire from the knowledge base."""
        delta = self.end_date - date.today()
        return max(delta.days + 1, 0)

    def to_index_content(self) -> str:
        """Rich text for vector store indexing."""
        parts = [f"Event: {self.name}"]
        if self.neighborhood:
            parts.append(f"in {self.neighborhood}")
        else:
            parts.append(f"in {self.market_id.replace('MARKET_', '').title()}")

        date_str = (
            self.start_date.strftime("%B %d")
            if self.start_date == self.end_date
            else f"{self.start_date.strftime('%B %d')} through {self.end_date.strftime('%B %d, %Y')}"
        )
        parts.append(f"on {date_str}.")
        parts.append(self.description)
        parts.append(f"Venue: {self.venue}.")
        parts.append(f"Category: {self.category}.")
        if not self.is_free:
            parts.append("Ticketed event.")
        if self.attendance_estimate in ("large", "massive"):
            parts.append("Expect large crowds — book restaurants early.")
        return " ".join(parts)

    def make_event_id(self) -> str:
        raw = f"{self.market_id}|{self.name}|{self.start_date}"
        return hashlib.md5(raw.encode()).hexdigest()[:16]


# ─────────────────────────────────────────────────────────────────────────────
# Abstract event source
# ─────────────────────────────────────────────────────────────────────────────

class EventSource(ABC):
    """Base class for all event scrapers."""

    @property
    @abstractmethod
    def source_name(self) -> str: ...

    @abstractmethod
    async def fetch_events(
        self,
        market_id: str,
        lat: float,
        lng: float,
        radius_km: float,
        days_ahead: int = 60,
    ) -> List[MarketEvent]: ...


# ─────────────────────────────────────────────────────────────────────────────
# Eventbrite source
# ─────────────────────────────────────────────────────────────────────────────

EVENTBRITE_SEARCH_URL = "https://www.eventbriteapi.com/v3/events/search/"

CATEGORY_MAP = {
    "103": "music",
    "110": "food",
    "111": "art",
    "104": "sports",
    "101": "festival",
    "108": "holiday",
    "115": "sports",
}

ATTENDANCE_MAP = {
    range(0, 200):    "small",
    range(200, 1000): "medium",
    range(1000, 5000):"large",
}


def _attendance_bucket(capacity: Optional[int]) -> str:
    if not capacity:
        return "medium"
    for r, label in ATTENDANCE_MAP.items():
        if capacity in r:
            return label
    return "massive"


def _demand_pressure(attendance: str) -> float:
    return {"small": 0.1, "medium": 0.3, "large": 0.7, "massive": 1.0}.get(attendance, 0.3)


class EventbriteSource(EventSource):
    """Pulls public events from Eventbrite API."""

    @property
    def source_name(self) -> str:
        return "eventbrite"

    async def fetch_events(
        self,
        market_id: str,
        lat: float,
        lng: float,
        radius_km: float,
        days_ahead: int = 60,
    ) -> List[MarketEvent]:
        headers = {}
        if EVENTBRITE_TOKEN:
            headers["Authorization"] = f"Bearer {EVENTBRITE_TOKEN}"

        today = date.today()
        end_date = today + timedelta(days=days_ahead)
        radius_miles = int(radius_km * 0.621371)

        params = {
            "location.latitude": lat,
            "location.longitude": lng,
            "location.within": f"{radius_miles}mi",
            "start_date.range_start": datetime.combine(today, datetime.min.time()).isoformat() + "Z",
            "start_date.range_end": datetime.combine(end_date, datetime.min.time()).isoformat() + "Z",
            "expand": "venue,ticket_availability,category",
            "page_size": 50,
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(EVENTBRITE_SEARCH_URL, params=params, headers=headers)
                if resp.status_code == 429:
                    logger.warning("[EventScraper] Eventbrite rate limited")
                    return []
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:
            logger.warning("[EventScraper] Eventbrite fetch failed: %s", e)
            return []

        events = []
        for item in data.get("events", []):
            try:
                ev = self._parse_event(item, market_id)
                if ev:
                    events.append(ev)
            except Exception as e:
                logger.debug("[EventScraper] parse error: %s", e)

        return events

    def _parse_event(self, item: Dict[str, Any], market_id: str) -> Optional[MarketEvent]:
        name = item.get("name", {}).get("text", "")
        if not name:
            return None

        desc = item.get("description", {}).get("text", "") or item.get("summary", "")
        start_str = (item.get("start") or {}).get("local", "")
        end_str = (item.get("end") or {}).get("local", "")

        try:
            start = date.fromisoformat(start_str[:10])
            end = date.fromisoformat(end_str[:10])
        except Exception:
            return None

        venue = item.get("venue") or {}
        venue_name = venue.get("name", "")
        addr = venue.get("address") or {}
        vlat = float(addr.get("latitude", 0)) or None
        vlng = float(addr.get("longitude", 0)) or None

        cat_id = str(item.get("category_id", ""))
        category = CATEGORY_MAP.get(cat_id, "other")

        capacity = item.get("ticket_availability", {}).get("maximum_ticket_price") or None
        attendance = _attendance_bucket(int(capacity) if capacity else None)

        is_free = item.get("is_free", False)
        ticket_url = item.get("url", "")

        ev = MarketEvent(
            event_id="",
            name=name,
            description=desc[:400] if desc else f"{category.title()} event at {venue_name}",
            market_id=market_id,
            neighborhood=None,
            start_date=start,
            end_date=end,
            venue=venue_name,
            venue_lat=vlat,
            venue_lng=vlng,
            category=category,
            attendance_estimate=attendance,
            is_free=is_free,
            ticket_url=ticket_url if ticket_url else None,
            source=self.source_name,
            demand_pressure=_demand_pressure(attendance),
        )
        ev.event_id = ev.make_event_id()
        return ev


# ─────────────────────────────────────────────────────────────────────────────
# Google Places "events" search source
# ─────────────────────────────────────────────────────────────────────────────

class GoogleEventsSource(EventSource):
    """
    Uses Google Places Text Search to find recurring/notable events near a location.
    Not a perfect event calendar, but surfaces festivals and known recurring events.
    """

    TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"

    @property
    def source_name(self) -> str:
        return "google_places_events"

    async def fetch_events(
        self,
        market_id: str,
        lat: float,
        lng: float,
        radius_km: float,
        days_ahead: int = 60,
    ) -> List[MarketEvent]:
        if not GOOGLE_PLACES_API_KEY:
            return []

        today = date.today()
        queries = [
            "festival this weekend",
            "concert event",
            "art show exhibition",
            "food festival",
            "outdoor market",
        ]

        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": GOOGLE_PLACES_API_KEY,
            "X-Goog-FieldMask": (
                "places.id,places.displayName,places.formattedAddress,"
                "places.location,places.types,places.editorialSummary"
            ),
        }

        events = []
        for query in queries:
            body = {
                "textQuery": query,
                "locationBias": {
                    "circle": {
                        "center": {"latitude": lat, "longitude": lng},
                        "radius": float(radius_km * 1000),
                    }
                },
                "maxResultCount": 5,
            }
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.post(self.TEXT_SEARCH_URL, json=body, headers=headers)
                    resp.raise_for_status()
                    data = resp.json()

                for item in data.get("places", []):
                    ev = self._parse_place_as_event(item, market_id, today)
                    if ev:
                        events.append(ev)
                await asyncio.sleep(0.1)
            except Exception as e:
                logger.debug("[EventScraper] Google events search failed: %s", e)

        return events

    def _parse_place_as_event(
        self,
        item: Dict[str, Any],
        market_id: str,
        today: date,
    ) -> Optional[MarketEvent]:
        name = item.get("displayName", {}).get("text", "")
        if not name:
            return None
        summary = (item.get("editorialSummary") or {}).get("text", "")
        loc = item.get("location", {})
        vlat = loc.get("latitude")
        vlng = loc.get("longitude")
        addr = item.get("formattedAddress", "")

        # Treat as a ~2 day event window from today
        ev = MarketEvent(
            event_id="",
            name=name,
            description=summary or f"Popular event venue: {name}",
            market_id=market_id,
            neighborhood=None,
            start_date=today,
            end_date=today + timedelta(days=2),
            venue=name,
            venue_lat=float(vlat) if vlat else None,
            venue_lng=float(vlng) if vlng else None,
            category="other",
            attendance_estimate="medium",
            is_free=True,
            ticket_url=None,
            source=self.source_name,
            demand_pressure=0.3,
        )
        ev.event_id = ev.make_event_id()
        return ev


# ─────────────────────────────────────────────────────────────────────────────
# Known major events registry (hard-coded annual events per market)
# These are high-confidence, high-demand events that are worth seeding
# regardless of whether the scraper finds them.
# ─────────────────────────────────────────────────────────────────────────────

def _year() -> int:
    return datetime.utcnow().year


KNOWN_ANNUAL_EVENTS: Dict[str, List[Dict]] = {
    "MARKET_MIAMI": [
        {"name": "Art Basel Miami Beach",       "start": (12, 4),  "end": (12, 8),  "venue": "Miami Beach Convention Center", "category": "art",     "attendance": "massive", "neighborhood": "South Beach"},
        {"name": "Ultra Music Festival",         "start": (3, 21),  "end": (3, 23),  "venue": "Bayfront Park",                "category": "music",   "attendance": "massive", "neighborhood": "Downtown"},
        {"name": "Miami Open Tennis",            "start": (3, 17),  "end": (3, 30),  "venue": "Hard Rock Stadium",            "category": "sports",  "attendance": "large",   "neighborhood": None},
        {"name": "Miami International Boat Show","start": (2, 12),  "end": (2, 16),  "venue": "Miami Beach Convention Center","category": "festival","attendance": "large",   "neighborhood": "South Beach"},
        {"name": "South Beach Wine & Food Fest", "start": (2, 20),  "end": (2, 23),  "venue": "South Beach",                  "category": "food",    "attendance": "large",   "neighborhood": "South Beach"},
        {"name": "Calle Ocho Music Festival",    "start": (3, 8),   "end": (3, 8),   "venue": "Calle Ocho, Little Havana",    "category": "festival","attendance": "massive", "neighborhood": "Little Havana"},
        {"name": "Miami Carnival",               "start": (10, 4),  "end": (10, 5),  "venue": "Miami-Dade County Fairgrounds","category": "festival","attendance": "large",   "neighborhood": None},
        {"name": "Formula E Miami",              "start": (4, 5),   "end": (4, 6),   "venue": "Miami Street Circuit",         "category": "sports",  "attendance": "large",   "neighborhood": "Downtown"},
    ],
    "MARKET_ORLANDO": [
        {"name": "Walt Disney World Marathon Weekend",  "start": (1, 8),  "end": (1, 12),  "venue": "Walt Disney World",         "category": "sports",  "attendance": "large", "neighborhood": "wdw_area"},
        {"name": "Epcot International Food & Wine",    "start": (8, 28), "end": (11, 22), "venue": "Epcot",                     "category": "food",    "attendance": "massive","neighborhood": "wdw_area"},
        {"name": "Universal Mardi Gras",               "start": (2, 1),  "end": (4, 19),  "venue": "Universal Studios",         "category": "festival","attendance": "large", "neighborhood": "universal"},
        {"name": "Halloween Horror Nights",            "start": (9, 5),  "end": (11, 2),  "venue": "Universal Studios",         "category": "festival","attendance": "massive","neighborhood": "universal"},
        {"name": "Orlando City Soccer Season",         "start": (2, 22), "end": (10, 19), "venue": "Inter&Co Stadium",          "category": "sports",  "attendance": "medium","neighborhood": None},
    ],
    "MARKET_TAMPA": [
        {"name": "Gasparilla Pirate Festival",      "start": (1, 25),  "end": (1, 25),  "venue": "Downtown Tampa",       "category": "festival","attendance": "massive","neighborhood": "downtown_tampa"},
        {"name": "Tampa Bay Lightning Playoffs",    "start": (4, 15),  "end": (6, 15),  "venue": "Amalie Arena",         "category": "sports", "attendance": "large",  "neighborhood": "channelside"},
        {"name": "Taste of Tampa",                  "start": (10, 10), "end": (10, 12), "venue": "Downtown Tampa",       "category": "food",   "attendance": "medium", "neighborhood": "downtown_tampa"},
        {"name": "Tampa Bay Margarita Festival",    "start": (3, 14),  "end": (3, 16),  "venue": "Tampa Riverwalk",      "category": "food",   "attendance": "medium", "neighborhood": "channelside"},
        {"name": "Florida State Fair",              "start": (2, 6),   "end": (2, 17),  "venue": "Florida State Fairgrounds","category": "festival","attendance": "large","neighborhood": None},
    ],
    "MARKET_KEYS": [
        {"name": "Key West Fantasy Fest",          "start": (10, 17), "end": (10, 26), "venue": "Duval Street",          "category": "festival","attendance": "massive","neighborhood": "key_west"},
        {"name": "Hemingway Days Festival",        "start": (7, 18),  "end": (7, 21),  "venue": "Key West",              "category": "festival","attendance": "medium", "neighborhood": "key_west"},
        {"name": "Islamorada Fishing Tournament",  "start": (4, 5),   "end": (4, 6),   "venue": "Islamorada",            "category": "sports", "attendance": "medium", "neighborhood": "islamorada"},
        {"name": "Key West New Year's Eve",        "start": (12, 31), "end": (12, 31), "venue": "Mallory Square",        "category": "holiday","attendance": "massive","neighborhood": "key_west"},
    ],
    "MARKET_30A": [
        {"name": "30A Songwriters Festival",        "start": (1, 16),  "end": (1, 19),  "venue": "30A Communities",      "category": "music",  "attendance": "large", "neighborhood": None},
        {"name": "Digital Graffiti at Alys Beach",  "start": (5, 16),  "end": (5, 17),  "venue": "Alys Beach",           "category": "art",    "attendance": "medium","neighborhood": "alys_beach"},
        {"name": "WaterColor Film Festival",        "start": (10, 9),  "end": (10, 12), "venue": "WaterColor",           "category": "art",    "attendance": "medium","neighborhood": "watercolor"},
        {"name": "Seeing Red Wine Festival",        "start": (11, 7),  "end": (11, 9),  "venue": "Rosemary Beach",       "category": "food",   "attendance": "medium","neighborhood": "rosemary_beach"},
    ],
    "MARKET_NAPLES": [
        {"name": "Naples National Art Festival",    "start": (2, 22),  "end": (2, 23),  "venue": "Cambier Park",         "category": "art",    "attendance": "large", "neighborhood": "naples"},
        {"name": "Stone Crab Festival",             "start": (10, 18), "end": (10, 19), "venue": "Naples",               "category": "food",   "attendance": "medium","neighborhood": "naples"},
        {"name": "Naples Half Marathon",            "start": (1, 18),  "end": (1, 18),  "venue": "Naples",               "category": "sports", "attendance": "medium","neighborhood": "naples"},
    ],
}


def get_known_events(market_id: str, days_ahead: int = 90) -> List[MarketEvent]:
    """Return known annual events for a market that are upcoming within days_ahead."""
    today = date.today()
    cutoff = today + timedelta(days=days_ahead)
    events = []

    for evt in KNOWN_ANNUAL_EVENTS.get(market_id, []):
        year = _year()
        m_start, d_start = evt["start"]
        m_end, d_end = evt["end"]

        try:
            start = date(year, m_start, d_start)
            end = date(year, m_end, d_end)
            # If the event already passed this year, try next year
            if end < today:
                start = date(year + 1, m_start, d_start)
                end = date(year + 1, m_end, d_end)
            # Only include if within window
            if start > cutoff:
                continue
        except ValueError:
            continue

        attendance = evt.get("attendance", "medium")
        ev = MarketEvent(
            event_id="",
            name=evt["name"],
            description=f"{evt['category'].title()} event in {market_id.replace('MARKET_', '').title()}.",
            market_id=market_id,
            neighborhood=evt.get("neighborhood"),
            start_date=start,
            end_date=end,
            venue=evt["venue"],
            venue_lat=None,
            venue_lng=None,
            category=evt["category"],
            attendance_estimate=attendance,
            is_free=False,
            ticket_url=None,
            source="known_events_registry",
            demand_pressure=_demand_pressure(attendance),
        )
        ev.event_id = ev.make_event_id()
        events.append(ev)

    return events


# ─────────────────────────────────────────────────────────────────────────────
# Market-parameterized event scraper orchestrator
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class EventScrapeResult:
    market_id: str
    events_found: int
    events_indexed: int
    demand_signals_emitted: int
    errors: List[str]
    duration_seconds: float


class MarketEventScraper:
    """
    Orchestrates event scraping for any market.

    Usage:
        scraper = MarketEventScraper()
        result = await scraper.scrape_and_index(
            market_id="MARKET_MIAMI",
            operator_id="op_brickell_stays",
            lat=25.760, lng=-80.195,
            radius_km=10.0,
            db_session=db,
        )
    """

    def __init__(self):
        self.sources: List[EventSource] = [
            EventbriteSource(),
            GoogleEventsSource(),
        ]

    async def scrape_and_index(
        self,
        market_id: str,
        operator_id: str,
        lat: float,
        lng: float,
        radius_km: float = 10.0,
        days_ahead: int = 90,
        db_session=None,
    ) -> EventScrapeResult:
        start_ts = datetime.utcnow()
        errors: List[str] = []
        all_events: List[MarketEvent] = []

        # ── 1. Known annual events (always included, no API calls) ────────
        known = get_known_events(market_id, days_ahead)
        all_events.extend(known)

        # ── 2. Live scrape from external sources ──────────────────────────
        for source in self.sources:
            try:
                evts = await source.fetch_events(market_id, lat, lng, radius_km, days_ahead)
                all_events.extend(evts)
            except Exception as e:
                errors.append(f"{source.source_name}: {e}")
                logger.warning("[EventScraper] %s", errors[-1])

        # ── 3. Deduplicate by event_id ────────────────────────────────────
        seen: set = set()
        unique: List[MarketEvent] = []
        for ev in all_events:
            if ev.event_id not in seen and ev.is_current:
                seen.add(ev.event_id)
                unique.append(ev)

        # ── 4. Index with TTL ─────────────────────────────────────────────
        indexed = 0
        if db_session and unique:
            indexed = await self._index_events(unique, operator_id, db_session)

        # ── 5. Emit demand pressure signals for high-attendance events ────
        signals_emitted = 0
        try:
            from app.services.events.event_triggers import get_event_service, EventType, EventSeverity
            svc = get_event_service()
            for ev in unique:
                if ev.demand_pressure >= 0.6:
                    svc.emit_event(
                        event_type=EventType.LOCAL_EVENT_DETECTED,
                        description=f"{ev.name} ({ev.start_date} – {ev.end_date})",
                        severity=EventSeverity.MEDIUM if ev.demand_pressure < 0.9 else EventSeverity.HIGH,
                        geo_id=market_id,
                        data={
                            "event_id": ev.event_id,
                            "demand_pressure": ev.demand_pressure,
                            "attendance": ev.attendance_estimate,
                            "category": ev.category,
                            "neighborhood": ev.neighborhood,
                        },
                    )
                    signals_emitted += 1
        except Exception as e:
            logger.debug("[EventScraper] signal emit failed: %s", e)

        duration = (datetime.utcnow() - start_ts).total_seconds()
        logger.info(
            "[EventScraper] %s: %d unique events, %d indexed, %d signals, %.1fs",
            market_id, len(unique), indexed, signals_emitted, duration,
        )

        return EventScrapeResult(
            market_id=market_id,
            events_found=len(unique),
            events_indexed=indexed,
            demand_signals_emitted=signals_emitted,
            errors=errors,
            duration_seconds=duration,
        )

    async def _index_events(
        self,
        events: List[MarketEvent],
        operator_id: str,
        db_session,
    ) -> int:
        """
        Index events into the vector store with TTL metadata.
        Old events for this operator+market are pruned first.
        """
        try:
            from app.services.knowledge.knowledge_indexer import KnowledgeIndexer
            from app.services.knowledge.vector_store import Document

            indexer = KnowledgeIndexer(db_session)
            store = await indexer._get_store()

            # Prune expired events
            await self._prune_expired_events(operator_id, db_session)

            documents = []
            for ev in events:
                documents.append(Document(
                    content=ev.to_index_content(),
                    metadata={
                        "operator_id": operator_id,
                        "doc_type": "market_event",
                        "event_id": ev.event_id,
                        "event_name": ev.name,
                        "market_id": ev.market_id,
                        "neighborhood": ev.neighborhood,
                        "start_date": ev.start_date.isoformat(),
                        "end_date": ev.end_date.isoformat(),
                        "category": ev.category,
                        "attendance_estimate": ev.attendance_estimate,
                        "demand_pressure": ev.demand_pressure,
                        "is_free": ev.is_free,
                        "venue": ev.venue,
                        "source": ev.source,
                        "expires_at": (ev.end_date + timedelta(days=1)).isoformat(),
                        "ttl_days": ev.ttl_days,
                    }
                ))

            result = await store.add_documents(documents)
            return result.get("inserted", 0) + result.get("updated", 0)

        except Exception as e:
            logger.warning("[EventScraper] index failed: %s", e)
            return 0

    async def _prune_expired_events(self, operator_id: str, db_session) -> int:
        """Remove past events from the vector store."""
        try:
            from sqlalchemy import text
            today_str = date.today().isoformat()
            result = await db_session.execute(
                text("""
                    DELETE FROM knowledge_embeddings
                    WHERE operator_id = :op
                      AND doc_type = 'market_event'
                      AND (metadata->>'end_date') < :today
                    RETURNING id
                """),
                {"op": operator_id, "today": today_str},
            )
            deleted = len(result.fetchall())
            if deleted:
                logger.info("[EventScraper] pruned %d expired events for %s", deleted, operator_id)
            await db_session.commit()
            return deleted
        except Exception as e:
            logger.debug("[EventScraper] prune failed (non-fatal): %s", e)
            return 0


# ─────────────────────────────────────────────────────────────────────────────
# Weekly refresh — wired into main.py background workers
# ─────────────────────────────────────────────────────────────────────────────

async def run_weekly_event_refresh(db_session) -> None:
    """
    Refresh event data for all active operators.
    Called weekly from main.py background worker.
    """
    try:
        from sqlalchemy import text
        result = await db_session.execute(
            text("""
                SELECT DISTINCT
                    tenant_id AS operator_id,
                    market_id,
                    AVG(latitude)  AS lat,
                    AVG(longitude) AS lng
                FROM properties
                WHERE latitude IS NOT NULL
                  AND longitude IS NOT NULL
                  AND deleted_at IS NULL
                GROUP BY tenant_id, market_id
            """)
        )
        rows = result.mappings().all()
    except Exception as e:
        logger.warning("[EventScraper] weekly refresh query failed: %s", e)
        return

    scraper = MarketEventScraper()
    for row in rows:
        market_id = row.get("market_id") or "MARKET_UNKNOWN"
        try:
            await scraper.scrape_and_index(
                market_id=market_id,
                operator_id=row["operator_id"],
                lat=float(row["lat"]),
                lng=float(row["lng"]),
                radius_km=15.0,
                days_ahead=90,
                db_session=db_session,
            )
        except Exception as e:
            logger.warning("[EventScraper] weekly refresh error for %s: %s", market_id, e)
