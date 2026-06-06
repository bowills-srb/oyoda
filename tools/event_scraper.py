#!/usr/bin/env python3
"""
Local Event Scraper — Market-Aware, Multi-Source

Scrapes public event data from several free sources and persists results to:
  1. market_events table  (DB — canonical record, deduped)
  2. signals table        (DB — DEMAND_PRESSURE / EVENT_IMPACT signals)
  3. concierge_knowledge  (RAG — so guests can ask "what's on this weekend?")

Sources (all public, no auth required by default):
  ┌─────────────────────────┬──────────────────────────────────────────────┐
  │ Source                  │ Notes                                        │
  ├─────────────────────────┼──────────────────────────────────────────────┤
  │ Eventbrite API          │ Free tier; 1000 req/day; best structured data│
  │ VisitFlorida            │ HTML scrape; state tourism events            │
  │ VisitSouthWalton        │ HTML scrape; 30A/Walton County events        │
  │ 30a.com events          │ HTML scrape; hyper-local 30A calendar        │
  │ VisitMyrtleBeach        │ HTML scrape; SC coast (multi-market)         │
  │ Google Places (nearby)  │ Optional; needs API key (GOOGLE_PLACES_KEY)  │
  └─────────────────────────┴──────────────────────────────────────────────┘

Market auto-detection:
  When a new operator onboards, resolve_operator_market() is called with
  their property addresses.  It geocodes the centroid, matches to the nearest
  known market (or creates a new MarketRegistryModel row), and enables the
  right scrape sources for that state/region.

Usage (CLI):
  python event_scraper.py --market 30a_fl
  python event_scraper.py --market destin_fl --days-ahead 60

Usage (programmatic):
  from tools.event_scraper import EventScrapeOrchestrator
  async with EventScrapeOrchestrator() as orc:
      events = await orc.scrape_market("30a_fl")
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import random
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import urlencode, quote_plus

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


# =============================================================================
# KNOWN MARKETS  (seed list — grows automatically via resolve_operator_market)
# =============================================================================

KNOWN_MARKETS: dict[str, dict] = {
    "30a_fl": {
        "name":           "30A Beaches, FL",
        "state":          "FL",
        "lat":            30.2833,
        "lng":            -86.0167,
        "radius_miles":   15,
        "timezone":       "America/Chicago",
        "sources": {
            "eventbrite":        True,
            "visitflorida":      True,
            "visitwaltoncounty": True,
            "30a_com":           True,
        },
    },
    "destin_fl": {
        "name":           "Destin, FL",
        "state":          "FL",
        "lat":            30.3935,
        "lng":            -86.4958,
        "radius_miles":   12,
        "timezone":       "America/Chicago",
        "sources": {
            "eventbrite":   True,
            "visitflorida": True,
            "visitdestin":  True,
        },
    },
    "gulf_shores_al": {
        "name":           "Gulf Shores / Orange Beach, AL",
        "state":          "AL",
        "lat":            30.2460,
        "lng":            -87.7008,
        "radius_miles":   15,
        "timezone":       "America/Chicago",
        "sources": {
            "eventbrite":      True,
            "gulfshores_com":  True,
        },
    },
    "pensacola_fl": {
        "name":           "Pensacola Beach, FL",
        "state":          "FL",
        "lat":            30.3324,
        "lng":            -87.1384,
        "radius_miles":   15,
        "timezone":       "America/Chicago",
        "sources": {
            "eventbrite":     True,
            "visitpensacola": True,
        },
    },
    "panama_city_beach_fl": {
        "name":           "Panama City Beach, FL",
        "state":          "FL",
        "lat":            30.1766,
        "lng":            -85.8055,
        "radius_miles":   15,
        "timezone":       "America/Chicago",
        "sources": {
            "eventbrite":  True,
            "visitpcb":    True,
        },
    },
    "myrtle_beach_sc": {
        "name":           "Myrtle Beach, SC",
        "state":          "SC",
        "lat":            33.6891,
        "lng":            -78.8867,
        "radius_miles":   20,
        "timezone":       "America/New_York",
        "sources": {
            "eventbrite":        True,
            "visitmyrtlebeach":  True,
        },
    },
    "outer_banks_nc": {
        "name":           "Outer Banks, NC",
        "state":          "NC",
        "lat":            35.9135,
        "lng":            -75.6765,
        "radius_miles":   25,
        "timezone":       "America/New_York",
        "sources": {
            "eventbrite": True,
            "outerbanks": True,
        },
    },
}

# Demand impact scoring by category (0–1 scale)
# These are BASE scores for unknown-scale events of each type.
# A local singer at a bar and the 30A Songwriters Festival are both "music",
# but attendance data (from Eventbrite) separates them via the multiplier below.
CATEGORY_IMPACT: dict[str, float] = {
    "music":      0.45,   # Base: local singer. Scales to 0.90+ for major festivals.
    "festival":   0.60,   # Base: small community fest. Scales to 0.90+ for regional.
    "sports":     0.45,   # Base: local 5K. Scales up for tournaments with 1000+ entries.
    "food":       0.40,   # Base: local tasting. Scales up for wine festivals.
    "art":        0.35,   # Base: gallery opening. Low demand impact generally.
    "family":     0.35,   # Base: kid activity. Low individual demand impact.
    "holiday":    0.70,   # Holidays always high — 4th of July, Memorial Day.
    "community":  0.25,   # Farmers market, meetup — minimal demand impact.
    "other":      0.20,   # Unknown events — don't assume impact.
}

GUEST_RELEVANCE_BASE: dict[str, float] = {
    "music": 0.65,
    "festival": 0.80,
    "sports": 0.55,
    "food": 0.75,
    "art": 0.60,
    "family": 0.75,
    "holiday": 0.85,
    "community": 0.45,
    "other": 0.40,
}

SOURCE_TYPE_MAP: dict[str, str] = {
    "eventbrite": "ticketing",
    "visitflorida": "tourism",
    "visitwaltoncounty": "tourism",
    "visitdestin": "tourism",
    "visitpensacola": "tourism",
    "visitpcb": "tourism",
    "visitmyrtlebeach": "tourism",
    "gulfshores_com": "tourism",
    "outerbanks": "tourism",
    "30a_com": "calendar",
    "manual": "manual",
    "facebook": "social",
}

# When Eventbrite provides estimated_attendance, apply this boost.
# Higher attendance = bigger demand impact. This separates major events
# from local ones of the same category.
ATTENDANCE_TIERS: list[tuple[int, float]] = [
    (50_000, 2.0),   # Gulf Coast Jam, major music festivals → 0.90 cap
    (10_000, 1.8),   # Regional festival, Songwriters Festival → 0.81+
    (5_000,  1.5),   # Decent-sized event → 0.675+
    (1_000,  1.25),  # Local event with draw → 0.5+
    (200,    1.0),   # Small ticketed event — no boost
    (0,      0.8),   # Tiny event — slight reduction
]

# Venue keywords that suggest a small/local setting — dampens music score
# so "Live Music at the Fish House" doesn't look like a festival
SMALL_VENUE_KEYWORDS = [
    "bar", "grill", "fish house", "brewery", "tap", "pub", "café",
    "restaurant", "bistro", "lounge", "patio", "deck", "waterfront",
    "lake", "dock", "market", "square",
]


# =============================================================================
# SCRAPED EVENT DATACLASS
# =============================================================================

@dataclass
class ScrapedEvent:
    """Raw event before DB upsert.  Maps 1:1 to MarketEventModel columns."""
    market_id:              str
    market_name:            str
    title:                  str
    source:                 str
    start_date:             date
    end_date:               date

    description:            str  = ""
    category:               str  = "other"
    tags:                   list = field(default_factory=list)
    start_time:             str | None = None
    end_time:               str | None = None
    is_multi_day:           bool = False
    is_recurring:           bool = False
    recurrence_rule:        str | None = None

    venue_name:             str | None = None
    venue_address:          str | None = None
    venue_lat:              float | None = None
    venue_lng:              float | None = None

    estimated_attendance:   int | None = None
    demand_radius_miles:    float = 15.0
    demand_impact_score:    float | None = None
    guest_relevance_score:  float | None = None
    booking_urgency_score:  float | None = None
    event_confidence_score: float | None = None
    event_class:            str | None = None
    actionability:          str | None = None

    source_id:              str | None = None
    source_url:             str | None = None
    source_type:            str | None = None
    source_count:           int = 1
    source_types:           list[str] = field(default_factory=list)
    observed_sources:       list[str] = field(default_factory=list)
    ticket_url:             str | None = None
    ticket_price_range:     str | None = None
    is_free:                bool = False
    first_seen_at:          datetime | None = None
    last_seen_at:           datetime | None = None
    stale_after:            datetime | None = None

    def compute_impact(self) -> float:
        """
        Derive demand_impact_score from category + attendance + venue context.

        Score breakdown:
          - Category sets the BASE (0.20-0.70) for an unknown-scale event
          - Attendance BOOSTS the score when Eventbrite provides it
            (separates Gulf Coast Jam from a local bar band)
          - Small venue keywords DAMPEN music/food scores
            ("live music at the fish house" != Songwriters Festival)
          - Recurring events get a small boost (consistent demand)
          - Always capped at 1.0
        """
        base = CATEGORY_IMPACT.get(self.category, 0.20)

        # Attendance boost (only when we have data from Eventbrite)
        if self.estimated_attendance is not None:
            for threshold, multiplier in ATTENDANCE_TIERS:
                if self.estimated_attendance >= threshold:
                    base = min(1.0, base * multiplier)
                    break

        # Venue context dampener for music/food at small local venues
        # e.g. "Live music by the lake @ Old Florida Fish House" = local act
        if self.category in ("music", "food") and self.venue_name:
            venue_lower = self.venue_name.lower()
            if any(kw in venue_lower for kw in SMALL_VENUE_KEYWORDS):
                base = min(base, 0.40)  # Cap local bar music at 0.40

        # Title keywords that override venue dampening (named festivals always high)
        title_lower = (self.title or "").lower()
        if any(kw in title_lower for kw in ["festival", "fest", "jam", "songwriters",
                                             "championship", "tournament", "marathon",
                                             "concert series", "wine festival",
                                             "seafood festival", "art festival"]):
            base = max(base, 0.70)  # Named festivals always at least 0.70

        # Recurring events: slight boost (consistent demand driver)
        if self.is_recurring:
            base = min(1.0, base * 1.1)

        return round(base, 3)

    def compute_guest_relevance(self) -> float:
        base = GUEST_RELEVANCE_BASE.get(self.category, 0.40)
        title_lower = (self.title or "").lower()
        desc_lower = (self.description or "").lower()

        if any(kw in title_lower for kw in ["festival", "concert", "market", "parade", "fireworks"]):
            base = min(1.0, base + 0.10)
        if self.is_recurring and self.category in ("community", "music"):
            base = max(0.35, base - 0.10)
        if any(kw in desc_lower for kw in ["parking", "shuttle", "ticket", "sold out", "crowd"]):
            base = min(1.0, base + 0.08)
        return round(max(0.0, min(base, 1.0)), 3)

    def compute_booking_urgency(self) -> float:
        urgency = 0.15
        title_lower = (self.title or "").lower()
        if self.ticket_url:
            urgency += 0.25
        if not self.is_free:
            urgency += 0.10
        if self.category in ("festival", "food", "holiday", "sports"):
            urgency += 0.20
        if any(kw in title_lower for kw in ["festival", "tournament", "championship", "concert", "wine"]):
            urgency += 0.15
        if self.is_recurring and self.category in ("music", "community"):
            urgency -= 0.10
        return round(max(0.0, min(urgency, 1.0)), 3)

    def compute_confidence(self) -> float:
        score = 0.45
        if self.source_id:
            score += 0.15
        if self.ticket_url:
            score += 0.10
        if self.estimated_attendance is not None:
            score += 0.10
        if self.venue_name:
            score += 0.05
        score += min(0.15, 0.05 * max(self.source_count - 1, 0))
        if self.is_recurring and not self.source_id:
            score -= 0.05
        return round(max(0.0, min(score, 1.0)), 3)

    def classify_event(self) -> str:
        impact = self.demand_impact_score or self.compute_impact()
        guest = self.guest_relevance_score or self.compute_guest_relevance()
        title_lower = (self.title or "").lower()
        if self.category == "holiday" or any(kw in title_lower for kw in ["memorial day", "labor day", "spring break", "fourth of july"]):
            return "seasonal_anchor"
        if impact >= 0.60 or self.category in ("festival", "sports"):
            return "demand_driver"
        if guest >= 0.45:
            return "operational"
        return "operational"

    def classify_actionability(self) -> str:
        urgency = self.booking_urgency_score or self.compute_booking_urgency()
        if urgency >= 0.65:
            return "book_now"
        if urgency >= 0.35:
            return "plan_ahead"
        return "informational"

    def compute_stale_after(self, now: datetime | None = None) -> datetime:
        now = now or datetime.now(tz=timezone.utc)
        if self.is_recurring and self.category in ("music", "community"):
            return now + timedelta(days=7)
        return datetime.combine(self.end_date + timedelta(days=2), datetime.min.time(), tzinfo=timezone.utc)

    def enrich(self, now: datetime | None = None) -> "ScrapedEvent":
        now = now or datetime.now(tz=timezone.utc)
        self.source_type = self.source_type or SOURCE_TYPE_MAP.get(self.source, "calendar")
        self.source_types = sorted(set((self.source_types or []) + [self.source_type]))
        self.observed_sources = sorted(set((self.observed_sources or []) + [self.source]))
        self.source_count = max(1, len(self.observed_sources))
        self.demand_impact_score = self.compute_impact()
        self.guest_relevance_score = self.compute_guest_relevance()
        self.booking_urgency_score = self.compute_booking_urgency()
        self.event_confidence_score = self.compute_confidence()
        self.event_class = self.classify_event()
        self.actionability = self.classify_actionability()
        self.first_seen_at = self.first_seen_at or now
        self.last_seen_at = now
        self.stale_after = self.compute_stale_after(now)
        return self


# =============================================================================
# RATE LIMITER  (shared across all scrapers)
# =============================================================================

class _RateLimiter:
    def __init__(self):
        self._last: dict[str, float] = {}

    async def wait(self, domain: str, min_s: float = 2.0, max_s: float = 4.0):
        elapsed = time.monotonic() - self._last.get(domain, 0)
        delay = random.uniform(min_s, max_s)
        if elapsed < delay:
            await asyncio.sleep(delay - elapsed)
        self._last[domain] = time.monotonic()


_limiter = _RateLimiter()
_UA = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.3 Safari/605.1.15",
]


# =============================================================================
# SOURCE: EVENTBRITE  (API — free, no auth for public events)
# =============================================================================

class EventbriteSource:
    """
    Uses Eventbrite's public search endpoint (no API key for public events).
    Falls back gracefully if Eventbrite changes their public API.

    API docs: https://www.eventbrite.com/platform/api#/reference/event/search
    """

    BASE = "https://www.eventbriteapi.com/v3"
    # Optional: set EVENTBRITE_API_KEY in env for higher rate limits
    API_KEY = os.getenv("EVENTBRITE_API_KEY", "")

    async def fetch(
        self,
        client: httpx.AsyncClient,
        market: dict,
        days_ahead: int = 90,
    ) -> list[ScrapedEvent]:
        events: list[ScrapedEvent] = []
        today = date.today()
        end_window = today + timedelta(days=days_ahead)

        params: dict[str, Any] = {
            "location.latitude":  market["lat"],
            "location.longitude": market["lng"],
            "location.within":    f"{int(market['radius_miles'] * 1.6)}km",
            "start_date.range_start": datetime.combine(today, datetime.min.time()).isoformat() + "Z",
            "start_date.range_end":   datetime.combine(end_window, datetime.min.time()).isoformat() + "Z",
            "expand":             "venue,category",
            "page_size":          50,
        }
        headers: dict[str, str] = {"User-Agent": random.choice(_UA)}
        if self.API_KEY:
            headers["Authorization"] = f"Bearer {self.API_KEY}"

        page = 1
        while True:
            params["page"] = page
            await _limiter.wait("eventbrite.com", 1.5, 3.0)
            try:
                r = await client.get(
                    f"{self.BASE}/events/search/",
                    params=params,
                    headers=headers,
                    timeout=15,
                )
                if r.status_code != 200:
                    logger.warning(f"Eventbrite HTTP {r.status_code}")
                    break
                data = r.json()
            except Exception as e:
                logger.warning(f"Eventbrite fetch error: {e}")
                break

            for ev in data.get("events", []):
                parsed = self._parse(ev, market)
                if parsed:
                    events.append(parsed)

            pagination = data.get("pagination", {})
            if not pagination.get("has_more_items"):
                break
            page += 1
            if page > 10:  # safety cap: 500 events max
                break

        logger.info(f"[Eventbrite] {market['name']}: {len(events)} events")
        return events

    def _parse(self, ev: dict, market: dict) -> ScrapedEvent | None:
        try:
            title = (ev.get("name") or {}).get("text", "").strip()
            if not title:
                return None

            start_str = (ev.get("start") or {}).get("local", "")
            end_str   = (ev.get("end")   or {}).get("local", "")
            if not start_str:
                return None

            start_dt = datetime.fromisoformat(start_str)
            end_dt   = datetime.fromisoformat(end_str) if end_str else start_dt

            start_d = start_dt.date()
            end_d   = end_dt.date()

            # Category
            cat_obj  = ev.get("category") or {}
            cat_name = (cat_obj.get("name") or "").lower()
            category = _map_category(cat_name)

            # Venue
            venue     = ev.get("venue") or {}
            v_name    = (venue.get("name") or "").strip() or None
            v_addr    = (venue.get("address") or {})
            v_full    = v_addr.get("localized_address_display", "").strip() or None
            v_lat     = _safe_float(venue.get("latitude"))
            v_lng     = _safe_float(venue.get("longitude"))

            # Price
            is_free       = ev.get("is_free", False)
            ticket_url    = ev.get("url")
            price_min     = _safe_float((ev.get("ticket_availability") or {}).get("minimum_ticket_price", {}).get("major_value"))
            price_max     = _safe_float((ev.get("ticket_availability") or {}).get("maximum_ticket_price", {}).get("major_value"))
            price_str: str | None = None
            if is_free:
                price_str = "Free"
            elif price_min is not None:
                price_str = f"${price_min:.0f}" if price_min == price_max or price_max is None else f"${price_min:.0f}–${price_max:.0f}"

            desc = ((ev.get("description") or {}).get("text") or "").strip()[:500]

            capacity = _safe_int(ev.get("capacity"))

            evt = ScrapedEvent(
                market_id            = market["id"],
                market_name          = market["name"],
                title                = title,
                source               = "eventbrite",
                source_id            = str(ev.get("id", "")),
                source_url           = ev.get("url"),
                ticket_url           = ticket_url,
                start_date           = start_d,
                end_date             = end_d,
                start_time           = start_dt.strftime("%-I:%M %p"),
                end_time             = end_dt.strftime("%-I:%M %p") if end_str else None,
                is_multi_day         = end_d > start_d,
                description          = desc,
                category             = category,
                venue_name           = v_name,
                venue_address        = v_full,
                venue_lat            = v_lat,
                venue_lng            = v_lng,
                estimated_attendance = capacity,
                ticket_price_range   = price_str,
                is_free              = is_free,
                demand_radius_miles  = market["radius_miles"],
            )
            evt.demand_impact_score = evt.compute_impact()
            return evt
        except Exception as e:
            logger.debug(f"Eventbrite parse error: {e}")
            return None


# =============================================================================
# SOURCE: VisitSouthWalton / 30A.com  (HTML)
# =============================================================================

class VisitWaltonSource:
    """
    Scrapes https://www.visitsouthwalton.com/events  (Walton County tourism)
    Covers 30A, South Walton, Santa Rosa Beach.
    """

    URL = "https://www.visitsouthwalton.com/events/?startdate={start}&enddate={end}"

    async def fetch(
        self,
        client: httpx.AsyncClient,
        market: dict,
        days_ahead: int = 90,
    ) -> list[ScrapedEvent]:
        events: list[ScrapedEvent] = []
        today = date.today()
        end_window = today + timedelta(days=days_ahead)

        url = self.URL.format(
            start=today.strftime("%Y-%m-%d"),
            end=end_window.strftime("%Y-%m-%d"),
        )
        await _limiter.wait("visitsouthwalton.com")
        try:
            r = await client.get(url, headers={"User-Agent": random.choice(_UA)}, timeout=20)
            if r.status_code != 200:
                logger.warning(f"VisitSouthWalton HTTP {r.status_code}")
                return []
            soup = BeautifulSoup(r.text, "lxml")
        except Exception as e:
            logger.warning(f"VisitSouthWalton fetch error: {e}")
            return []

        # Event cards — selector may need updating if site redesigns
        for card in soup.select(".event-card, .views-row, article.event"):
            ev = self._parse_card(card, market)
            if ev:
                events.append(ev)

        # Also look for JSON-LD structured data
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "{}")
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") in ("Event", "Festival"):
                        ev = self._parse_jsonld(item, market)
                        if ev:
                            events.append(ev)
            except Exception:
                pass

        logger.info(f"[VisitSouthWalton] {market['name']}: {len(events)} events")
        return events

    def _parse_card(self, card, market: dict) -> ScrapedEvent | None:
        try:
            # Card structure: <div class="event-card"><a href="...">Title\nDate</a></div>
            # Title may be in h2/h3/.title OR directly in the <a> tag
            title_el = card.select_one("h2, h3, h4, .event-title, .title, strong")
            if not title_el:
                # Fall back: grab the <a> tag text, first line is title
                a_el = card.find("a")
                if a_el:
                    raw = a_el.get_text(" ", strip=True)
                    # Split on newline or date patterns to isolate title
                    lines = [l.strip() for l in raw.split("\n") if l.strip()]
                    if lines:
                        title = lines[0]
                    else:
                        return None
                else:
                    return None
            else:
                title = title_el.get_text(strip=True)
            if not title:
                return None

            # Date: look for dedicated date element, then fall back to <a> text
            date_el = card.select_one(".date, time, .event-date, [datetime], [class*='date'], [class*='when'], .meta")
            start_d = end_d = None
            if date_el:
                dt_str = date_el.get("datetime") or date_el.get_text(strip=True)
                start_d, end_d = _parse_date_range(dt_str)
            if not start_d:
                # Try to extract date from the full card text
                card_text = card.get_text(" ", strip=True)
                start_d, end_d = _parse_date_range(card_text)
            if not start_d:
                # Try to parse month/day from card text like "April 19 @ 9AM"
                import re as _re
                m = _re.search(
                    r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2})",
                    card.get_text(" ", strip=True), _re.I
                )
                if m:
                    from datetime import date as _date, datetime as _dt
                    import datetime as _datetime
                    try:
                        year = _date.today().year
                        start_d = _dt.strptime(f"{m.group(1)} {m.group(2)} {year}", "%B %d %Y").date()
                        # If parsed date is in the past, try next year
                        if start_d < _date.today():
                            start_d = _dt.strptime(f"{m.group(1)} {m.group(2)} {year+1}", "%B %d %Y").date()
                        end_d = start_d
                    except Exception:
                        pass
            if not start_d:
                start_d = end_d = date.today() + timedelta(days=1)

            desc_el = card.select_one(".description, .summary, p")
            desc = desc_el.get_text(strip=True)[:400] if desc_el else ""

            link_el = card.find("a", href=True)
            url = None
            if link_el:
                href = link_el["href"]
                if href.startswith("http"):
                    url = href
                elif href.startswith("/"):
                    url = "https://www.visitsouthwalton.com" + href

            evt = ScrapedEvent(
                market_id   = market["id"],
                market_name = market["name"],
                title       = title,
                source      = "visitwaltoncounty",
                source_url  = url,
                source_id   = _url_to_id(url) if url else None,
                start_date  = start_d,
                end_date    = end_d,
                is_multi_day= end_d > start_d,
                description = desc,
                category    = _infer_category(title + " " + desc),
                demand_radius_miles = market["radius_miles"],
            )
            evt.demand_impact_score = evt.compute_impact()
            return evt
        except Exception:
            return None

    def _parse_jsonld(self, item: dict, market: dict) -> ScrapedEvent | None:
        try:
            title = item.get("name", "").strip()
            if not title:
                return None
            start_str = item.get("startDate", "")
            end_str   = item.get("endDate", start_str)
            if not start_str:
                return None

            start_d = _parse_iso_date(start_str)
            end_d   = _parse_iso_date(end_str) if end_str else start_d
            if not start_d:
                return None

            loc = item.get("location") or {}
            venue_name = loc.get("name", "").strip() or None
            addr_obj = loc.get("address") or {}
            venue_addr = (
                addr_obj.get("streetAddress", "") + ", " +
                addr_obj.get("addressLocality", "")
            ).strip(", ") or None
            geo = loc.get("geo") or {}
            v_lat = _safe_float(geo.get("latitude"))
            v_lng = _safe_float(geo.get("longitude"))

            desc = (item.get("description") or "").strip()[:500]
            url  = item.get("url") or item.get("@id")

            evt = ScrapedEvent(
                market_id    = market["id"],
                market_name  = market["name"],
                title        = title,
                source       = "visitwaltoncounty",
                source_id    = _url_to_id(url) if url else None,
                source_url   = url,
                start_date   = start_d,
                end_date     = end_d or start_d,
                is_multi_day = (end_d or start_d) > start_d,
                description  = desc,
                category     = _infer_category(title + " " + desc),
                venue_name   = venue_name,
                venue_address= venue_addr,
                venue_lat    = v_lat,
                venue_lng    = v_lng,
                demand_radius_miles = market["radius_miles"],
            )
            evt.demand_impact_score = evt.compute_impact()
            return evt
        except Exception:
            return None


class ThirtyASource:
    """
    Scrapes https://30a.com/events/feed/ — official RSS feed.
    This is the tier-1 source: structured, machine-readable, no HTML parsing.
    
    Feed format per item:
      <title>Event Name</title>
      <link>https://30a.com/events/slug-YYYY-MM-DD/</link>
      <pubDate>Sat, 18 Apr 2026 13:00:00 +0000</pubDate>
      <description><![CDATA[Day, Month DD - H:MM am/pm - H:MM am/pm <br/>Venue<br/>Address<br/>City]]></description>
    
    Dates are also encoded in the URL slug for recurring events:
      /events/spring-sessions-2026-03-07-2026-03-14-2026-03-21-...
    We use pubDate as the canonical date (it reflects the next occurrence).
    """

    FEED_URL = "https://30a.com/events/feed/"
    CALENDAR_URL = "https://30a.com/events/"

    def __init__(self, feed_url: str | None = None):
        self.feed_url = feed_url or self.FEED_URL

    async def fetch(self, client, market, days_ahead=90):
        """
        Two-pass: RSS feed (today/tomorrow, full detail) +
        HTML calendar ?start_date= pagination (full 90-day window).
        """
        today = date.today()
        cutoff = today + timedelta(days=days_ahead)
        seen: set[str] = set()
        feed_evts = await self._fetch_rss(client, market, today, cutoff, seen)
        cal_evts  = await self._fetch_calendar(client, market, today, cutoff, seen, start_offset=2)
        all_evts  = feed_evts + cal_evts
        logger.info(f"[30a.com] {market['name']}: {len(all_evts)} events "
                    f"(RSS:{len(feed_evts)} cal:{len(cal_evts)})")
        return all_evts

    async def _fetch_rss(self, client, market, today, cutoff, seen):
        import html as _html
        events = []
        await _limiter.wait("30a.com", 1.0, 2.0)
        try:
            r = await client.get(self.feed_url, headers={"User-Agent": random.choice(_UA)},
                                 timeout=20, follow_redirects=True)
            if r.status_code != 200:
                logger.warning(f"30a.com feed HTTP {r.status_code}")
                return []
        except Exception as e:
            logger.warning(f"30a.com feed error: {e}")
            return []
        try:
            import xml.etree.ElementTree as ET
            root = ET.fromstring(r.content)
            channel = root.find("channel")
            if not channel:
                return []
            for item in channel.findall("item"):
                evt = self._parse_rss_item(item, market, today, cutoff, seen, _html)
                if evt:
                    events.append(evt)
        except Exception as e:
            logger.warning(f"30a.com RSS parse: {e}")
        return events

    def _parse_rss_item(self, item, market, today, cutoff, seen, _html):
        try:
            title = (item.findtext("title") or "").strip()
            if not title:
                return None
            link  = (item.findtext("link") or "").strip()
            guid  = (item.findtext("guid") or link).strip()
            gkey  = guid.rstrip("/").split("/")[-1]
            if gkey in seen:
                return None
            seen.add(gkey)
            start_d = _parse_rss_date(item.findtext("pubDate") or "")
            if not start_d and link:
                for ds in re.findall(r"(\d{4}-\d{2}-\d{2})", link):
                    try:
                        d = date.fromisoformat(ds)
                        if d >= today:
                            start_d = d; break
                    except ValueError:
                        pass
            if not start_d or not (today <= start_d <= cutoff):
                return None
            venue_name = venue_address = start_time = end_time = None
            dt = item.findtext("description") or ""
            if dt:
                raw = _html.unescape(dt.strip())
                parts = [p.strip() for p in re.split(r"<br\s*/?>", raw) if p.strip()]
                if parts:
                    tm = re.search(r"(\d{1,2}:\d{2}\s*[ap]m)(?:\s*-\s*(\d{1,2}:\d{2}\s*[ap]m))?",
                                   parts[0], re.I)
                    if tm:
                        start_time = tm.group(1).strip()
                        end_time   = tm.group(2).strip() if tm.group(2) else None
                    if len(parts) > 1: venue_name = parts[1].strip() or None
                    if len(parts) > 2:
                        addr = [p for p in parts[2:] if p and p != venue_name]
                        venue_address = ", ".join(addr[:2]) or None
            evt = ScrapedEvent(
                market_id=market["id"], market_name=market["name"],
                title=title, source="30a_com", source_id=gkey, source_url=link or None,
                start_date=start_d, end_date=start_d, start_time=start_time, end_time=end_time,
                category=_infer_category(title + " " + (venue_name or "")),
                venue_name=venue_name, venue_address=venue_address,
                demand_radius_miles=market.get("radius_miles", 15.0),
            )
            evt.demand_impact_score = evt.compute_impact()
            return evt
        except Exception:
            return None

    async def _fetch_calendar(self, client, market, today, cutoff, seen, start_offset=0):
        events = []
        current = today + timedelta(days=start_offset)
        while current <= cutoff:
            url = f"{self.CALENDAR_URL}?start_date={current.strftime('%Y-%m-%d')}"
            await _limiter.wait("30a.com", 1.5, 3.0)
            try:
                r = await client.get(url, headers={"User-Agent": random.choice(_UA)},
                                     timeout=25, follow_redirects=True)
                if r.status_code == 200:
                    events.extend(self._parse_calendar_page(r.text, market, today, cutoff, seen))
            except Exception as e:
                logger.debug(f"30a.com calendar {current}: {e}")
            current += timedelta(days=7)
        return events

    def _parse_calendar_page(self, html_text, market, today, cutoff, seen):
        events = []
        try:
            soup = BeautifulSoup(html_text, "lxml")
            for li in soup.select("ul.event-custom-listview li, li.event-item"):
                a = li.find("a", href=True)
                if not a:
                    continue
                href = a.get("href", "")
                if not href or "/events/" not in href:
                    continue
                if href.startswith("/"):
                    href = "https://30a.com" + href
                gkey = href.rstrip("/").split("/")[-1]
                if gkey in seen:
                    continue
                title = a.get_text(strip=True)
                if not title or len(title) < 2:
                    continue
                start_d = None
                for ds in re.findall(r"(\d{4}-\d{2}-\d{2})", href):
                    try:
                        d = date.fromisoformat(ds)
                        if today <= d <= cutoff:
                            start_d = d; break
                    except ValueError:
                        pass
                if not start_d:
                    li_text = li.get_text(" ", strip=True)
                    m = re.search(
                        r"(January|February|March|April|May|June|July|August|"
                        r"September|October|November|December)\s+(\d{1,2})",
                        li_text, re.I)
                    if m:
                        try:
                            yr = today.year
                            start_d = datetime.strptime(f"{m.group(1)} {m.group(2)} {yr}", "%B %d %Y").date()
                            if start_d < today:
                                start_d = datetime.strptime(f"{m.group(1)} {m.group(2)} {yr+1}", "%B %d %Y").date()
                        except Exception:
                            pass
                if not start_d or not (today <= start_d <= cutoff):
                    continue
                seen.add(gkey)
                li_text = li.get_text(" ", strip=True)
                venue_name = start_time = None
                if "@" in li_text:
                    venue_raw = li_text.split("@", 1)[1].strip()
                    venue_name = venue_raw.split("\n")[0].strip()[:80] or None
                tm = re.search(r"(\d{1,2}:\d{2}\s*[ap]m)", li_text, re.I)
                if tm:
                    start_time = tm.group(1)
                evt = ScrapedEvent(
                    market_id=market["id"], market_name=market["name"],
                    title=title, source="30a_com", source_id=gkey, source_url=href,
                    start_date=start_d, end_date=start_d, start_time=start_time,
                    category=_infer_category(title + " " + (venue_name or "")),
                    venue_name=venue_name,
                    demand_radius_miles=market.get("radius_miles", 15.0),
                )
                evt.demand_impact_score = evt.compute_impact()
                events.append(evt)
        except Exception as e:
            logger.warning(f"30a.com calendar parse: {e}")
        return events


def _parse_rss_date(date_str: str) -> date | None:
    """Parse RSS pubDate format: 'Sat, 18 Apr 2026 13:00:00 +0000'"""
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(date_str).date()
    except Exception:
        pass
    # Fallback: extract YYYY-MM-DD if present
    m = re.search(r"(\d{4}-\d{2}-\d{2})", date_str)
    if m:
        try:
            return date.fromisoformat(m.group(1))
        except Exception:
            pass
    return None


# =============================================================================
# SOURCE: Generic tourism site scraper (VisitFlorida, VisitDestin, etc.)
# =============================================================================

# Architecture note on source fragility:
# HTML scrapers break when sites redesign. The durable hierarchy is:
#   1. Official RSS/JSON feed (30a.com/events/feed/, iCal endpoints)
#   2. JSON-LD on individual event pages
#   3. HTML selectors stored in sources_config (updatable via DB, no deploy)
#   4. Zero-result auto-disable: if a source returns 0 events 3 runs in a row,
#      it's disabled in market_registry and an alert is logged.
#
# sources_config per source supports optional keys:
#   {"enabled": true, "feed_url": "...", "selector": ".event-card",
#    "zero_result_streak": 0, "note": "..."}
#
# New operators: market_scraper_builder.py auto-discovers feed URLs via
# DuckDuckGo + probe pipeline when a new market is created. This means
# selectors are never hardcoded for operators outside the seed list.

TOURISM_SOURCES: dict[str, dict] = {
    "visitflorida": {
        "url":    "https://www.visitflorida.com/en-us/things-to-do/events.html",
        "domain": "visitflorida.com",
        "label":  "VisitFlorida",
        "parser_type": "html_listing",
    },
    "visitdestin": {
        "url":    "https://www.destinfwb.com/events/",
        "domain": "destinfwb.com",
        "label":  "VisitDestin",
        "parser_type": "html_listing",
    },
    "gulfshores_com": {
        "url":    "https://www.gulfshores.com/events/",
        "domain": "gulfshores.com",
        "label":  "Gulf Shores",
        "parser_type": "html_listing",
    },
    "visitpensacola": {
        "url":    "https://www.visitpensacola.com/events/",
        "domain": "visitpensacola.com",
        "label":  "VisitPensacola",
        "parser_type": "html_listing",
    },
    "visitpcb": {
        "url":    "https://www.visitpanamacitybeach.com/events/",
        "domain": "visitpanamacitybeach.com",
        "label":  "VisitPCB",
        "parser_type": "html_listing",
    },
    "visitmyrtlebeach": {
        "url":    "https://www.visitmyrtlebeach.com/things-to-do/events/",
        "domain": "visitmyrtlebeach.com",
        "label":  "VisitMyrtleBeach",
        "parser_type": "html_listing",
    },
    "outerbanks": {
        "url":    "https://www.outerbanks.org/events/",
        "domain": "outerbanks.org",
        "label":  "Outer Banks",
        "parser_type": "html_listing",
    },
}

DEFAULT_EVENT_CARD_SELECTORS = [
    ".event-card",
    ".views-row",
    "article.event",
    "[data-event-id]",
    ".tribe-events-calendar-list__event-row",
    ".event-listing-item",
]
DEFAULT_DETAIL_LINK_SELECTORS = [
    "a[href*='/events/']",
    "a[href*='/event/']",
    "a[href*='/calendar/']",
]


def _source_is_enabled(cfg: Any) -> bool:
    if cfg is True:
        return True
    if isinstance(cfg, dict):
        return bool(cfg.get("enabled"))
    return False


def _normalize_market_source_config(source_key: str, cfg: Any) -> dict:
    default = TOURISM_SOURCES.get(source_key, {})
    normalized = dict(default)

    if cfg is True:
        normalized["enabled"] = True
    elif isinstance(cfg, dict):
        normalized.update(cfg)
        normalized["enabled"] = bool(cfg.get("enabled"))
    else:
        normalized["enabled"] = False

    normalized.setdefault("source_key", source_key)
    normalized.setdefault("parser_type", "html_listing")
    normalized.setdefault("list_url", normalized.get("url"))
    normalized.setdefault("event_card_selectors", DEFAULT_EVENT_CARD_SELECTORS)
    normalized.setdefault("detail_link_selectors", DEFAULT_DETAIL_LINK_SELECTORS)
    normalized.setdefault("detail_link_limit", 12)
    normalized.setdefault("health", {})
    return normalized


def _normalize_market_sources(raw_sources: dict[str, Any]) -> dict[str, dict]:
    return {
        key: _normalize_market_source_config(key, value)
        for key, value in (raw_sources or {}).items()
    }


def build_market_sources_config(raw_sources: dict[str, Any]) -> dict[str, dict]:
    normalized = _normalize_market_sources(raw_sources or {})
    if "30a_com" in normalized:
        if normalized["30a_com"].get("parser_type") in (None, "", "html_listing"):
            normalized["30a_com"]["parser_type"] = "rss"
        if not normalized["30a_com"].get("feed_url"):
            normalized["30a_com"]["feed_url"] = "https://30a.com/events/feed/"
    if "eventbrite" in normalized:
        normalized["eventbrite"]["enabled"] = bool(os.getenv("EVENTBRITE_API_KEY", "").strip()) and bool(
            normalized["eventbrite"].get("enabled")
        )
        normalized["eventbrite"].setdefault("note", "requires EVENTBRITE_API_KEY")
        normalized["eventbrite"]["parser_type"] = "api"
    return normalized


class TourismBoardSource:
    """
    Generic JSON-LD + card scraper for tourism board event pages.
    Handles the majority of official tourism sites with minimal customisation.
    """

    def __init__(self, source_key: str, source_cfg: dict | None = None):
        self.key    = source_key
        merged = dict(TOURISM_SOURCES.get(source_key, {}))
        if source_cfg:
            merged.update(source_cfg)
        self.config = _normalize_market_source_config(source_key, merged)

    async def fetch(
        self,
        client: httpx.AsyncClient,
        market: dict,
        days_ahead: int = 90,
    ) -> list[ScrapedEvent]:
        if not self.config:
            return []

        if self.config.get("feed_url"):
            feed_events = await self._fetch_feed(client, market, days_ahead)
            if feed_events:
                return feed_events

        events: list[ScrapedEvent] = []
        domain = self.config["domain"]
        url    = self.config.get("list_url") or self.config.get("url")
        label  = self.config["label"]
        cutoff = date.today() + timedelta(days=days_ahead)

        await _limiter.wait(domain)
        try:
            r = await client.get(url, headers={"User-Agent": random.choice(_UA)}, timeout=20)
            if r.status_code != 200:
                logger.warning(f"[{label}] HTTP {r.status_code}")
                return []
            soup = BeautifulSoup(r.text, "lxml")
        except Exception as e:
            logger.warning(f"[{label}] fetch error: {e}")
            return []

        events.extend(self._parse_jsonld_from_soup(soup, market, cutoff))

        card_selectors = self.config.get("event_card_selectors") or DEFAULT_EVENT_CARD_SELECTORS
        if not events and self.config.get("parser_type") in ("html_listing", "hybrid"):
            for selector in card_selectors:
                for card in soup.select(selector):
                    ev = self._parse_card(card, market)
                    if ev:
                        events.append(ev)
                if events:
                    break

        if not events and self.config.get("parser_type") in ("jsonld_detail_pages", "html_listing", "hybrid"):
            events.extend(await self._fetch_detail_page_events(client, soup, market, cutoff))

        logger.info(f"[{label}] {market['name']}: {len(events)} events")
        return events

    async def _fetch_feed(
        self,
        client: httpx.AsyncClient,
        market: dict,
        days_ahead: int,
    ) -> list[ScrapedEvent]:
        feed_url = self.config.get("feed_url")
        if not feed_url:
            return []
        label = self.config["label"]
        domain = self.config["domain"]
        await _limiter.wait(domain)
        try:
            r = await client.get(feed_url, headers={"User-Agent": random.choice(_UA)}, timeout=20)
            if r.status_code != 200:
                logger.warning(f"[{label}] feed HTTP {r.status_code}")
                return []
        except Exception as e:
            logger.warning(f"[{label}] feed fetch error: {e}")
            return []

        today = date.today()
        cutoff = today + timedelta(days=days_ahead)
        events: list[ScrapedEvent] = []
        try:
            import xml.etree.ElementTree as ET
            root = ET.fromstring(r.content)
            channel = root.find("channel")
            if channel is None:
                return []
            for item in channel.findall("item"):
                title = ((item.findtext("title") or "")).strip()
                link = ((item.findtext("link") or "")).strip()
                if not title:
                    continue
                start_d = _parse_rss_date(item.findtext("pubDate") or "")
                if not start_d or start_d < today or start_d > cutoff:
                    continue
                desc = (item.findtext("description") or "").strip()
                evt = ScrapedEvent(
                    market_id=market["id"],
                    market_name=market["name"],
                    title=title,
                    source=self.key,
                    source_id=_url_to_id(link) if link else None,
                    source_url=link or None,
                    start_date=start_d,
                    end_date=start_d,
                    description=desc[:400],
                    category=_infer_category(title + " " + desc),
                    demand_radius_miles=market["radius_miles"],
                )
                evt.demand_impact_score = evt.compute_impact()
                events.append(evt)
        except Exception as e:
            logger.warning(f"[{label}] feed parse error: {e}")
        return events

    def _parse_jsonld_from_soup(
        self,
        soup: BeautifulSoup,
        market: dict,
        cutoff: date,
    ) -> list[ScrapedEvent]:
        events: list[ScrapedEvent] = []
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "{}")
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") not in ("Event", "Festival", "MusicEvent",
                                                 "SportsEvent", "FoodEvent"):
                        continue
                    start_d = _parse_iso_date(item.get("startDate", ""))
                    if not start_d or start_d > cutoff:
                        continue
                    end_d = _parse_iso_date(item.get("endDate", "")) or start_d
                    title = item.get("name", "").strip()
                    if not title:
                        continue
                    desc = (item.get("description") or "")[:400]
                    ev_url = item.get("url")
                    loc = item.get("location") or {}
                    v_name = (loc.get("name") or "").strip() or None
                    geo = loc.get("geo") or {}
                    evt = ScrapedEvent(
                        market_id=market["id"],
                        market_name=market["name"],
                        title=title,
                        source=self.key,
                        source_id=_url_to_id(ev_url) if ev_url else None,
                        source_url=ev_url,
                        start_date=start_d,
                        end_date=end_d,
                        is_multi_day=end_d > start_d,
                        description=desc,
                        category=_infer_category(title + " " + desc),
                        venue_name=v_name,
                        venue_lat=_safe_float(geo.get("latitude")),
                        venue_lng=_safe_float(geo.get("longitude")),
                        demand_radius_miles=market["radius_miles"],
                    )
                    evt.demand_impact_score = evt.compute_impact()
                    events.append(evt)
            except Exception:
                pass
        return events

    async def _fetch_detail_page_events(
        self,
        client: httpx.AsyncClient,
        soup: BeautifulSoup,
        market: dict,
        cutoff: date,
    ) -> list[ScrapedEvent]:
        detail_links = []
        selectors = self.config.get("detail_link_selectors") or DEFAULT_DETAIL_LINK_SELECTORS
        base_url = self.config.get("list_url") or self.config.get("url")
        for selector in selectors:
            for link in soup.select(selector):
                href = (link.get("href") or "").strip()
                if not href:
                    continue
                if href.startswith("/"):
                    href = self.config.get("base_url") or f"https://{self.config['domain']}" + href
                elif not href.startswith("http"):
                    if base_url:
                        from urllib.parse import urljoin
                        href = urljoin(base_url, href)
                if href not in detail_links:
                    detail_links.append(href)
            if detail_links:
                break

        events: list[ScrapedEvent] = []
        for href in detail_links[: int(self.config.get("detail_link_limit", 12))]:
            try:
                await _limiter.wait(self.config["domain"], 0.2, 0.6)
                r = await client.get(href, headers={"User-Agent": random.choice(_UA)}, timeout=20)
                if r.status_code != 200:
                    continue
                detail_soup = BeautifulSoup(r.text, "lxml")
                events.extend(self._parse_jsonld_from_soup(detail_soup, market, cutoff))
            except Exception:
                continue
        return events

    def _parse_card(self, card, market: dict) -> ScrapedEvent | None:
        try:
            title_el = card.select_one("h1, h2, h3, h4, .title, .event-title, strong")
            link_el = card.find("a", href=True)
            title = title_el.get_text(strip=True) if title_el else ""
            if not title and link_el:
                title = link_el.get_text(" ", strip=True)
            if not title:
                return None

            text_blob = card.get_text(" ", strip=True)
            start_d, end_d = _parse_date_range(text_blob)
            if not start_d:
                return None

            desc_el = card.select_one("p, .description, .summary, .excerpt")
            desc = desc_el.get_text(" ", strip=True)[:400] if desc_el else text_blob[:400]
            url = None
            if link_el:
                href = link_el["href"]
                if href.startswith("http"):
                    url = href
                elif href.startswith("/"):
                    url = f"https://{self.config['domain']}{href}"

            evt = ScrapedEvent(
                market_id=market["id"],
                market_name=market["name"],
                title=title,
                source=self.key,
                source_id=_url_to_id(url) if url else None,
                source_url=url,
                start_date=start_d,
                end_date=end_d or start_d,
                is_multi_day=(end_d or start_d) > start_d,
                description=desc,
                category=_infer_category(title + " " + desc),
                demand_radius_miles=market["radius_miles"],
            )
            evt.demand_impact_score = evt.compute_impact()
            return evt
        except Exception:
            return None


# =============================================================================
# MARKET AUTO-DETECTION  (called on operator onboarding)
# =============================================================================

async def resolve_operator_market(
    property_addresses: list[str],
    operator_id: str,
    operator_name: str,
) -> dict | None:
    """
    Given a list of property addresses from a new operator, determine which
    market they belong to and return the matching MarketRegistryModel dict.

    Steps:
      1. Geocode the centroid of the addresses (Nominatim — free, no key needed)
      2. Compare to KNOWN_MARKETS by Haversine distance
      3. If within 30mi of a known market → return it
      4. Otherwise → create a new market entry using the resolved city/state
         and auto-select sources based on state

    Called from the onboarding agent after property import.
    Returns the market dict (with 'id' key) or None on failure.
    """
    import math

    if not property_addresses:
        return None

    # Geocode the first address (representative sample is sufficient)
    lat, lng, city, state = await _geocode_address(property_addresses[0])
    if lat is None:
        logger.warning(f"[MarketDetect] Could not geocode address for {operator_name}")
        return None

    # Find nearest known market
    def haversine(lat1, lng1, lat2, lng2) -> float:
        R = 3959  # miles
        d_lat = math.radians(lat2 - lat1)
        d_lng = math.radians(lng2 - lng1)
        a = (math.sin(d_lat / 2) ** 2
             + math.cos(math.radians(lat1))
             * math.cos(math.radians(lat2))
             * math.sin(d_lng / 2) ** 2)
        return R * 2 * math.asin(math.sqrt(a))

    closest_market = None
    closest_dist   = float("inf")
    for mid, m in KNOWN_MARKETS.items():
        d = haversine(lat, lng, m["lat"], m["lng"])
        if d < closest_dist:
            closest_dist   = d
            closest_market = {**m, "id": mid}

    if closest_market and closest_dist <= 30:
        logger.info(
            f"[MarketDetect] {operator_name} → '{closest_market['name']}' "
            f"({closest_dist:.1f}mi)"
        )
        # Register operator with market (fire-and-forget — non-blocking)
        asyncio.ensure_future(
            _register_operator_with_market(closest_market["id"], operator_id, operator_name)
        )
        return closest_market

    # New market: build slug and auto-select sources
    if not city or not state:
        logger.warning(f"[MarketDetect] Could not resolve city/state for {operator_name}")
        return None

    market_id   = f"{city.lower().replace(' ', '_')}_{state.lower()}"
    market_name = f"{city}, {state}"
    sources     = _default_sources_for_state(state)

    new_market = {
        "id":           market_id,
        "name":         market_name,
        "state":        state,
        "lat":          lat,
        "lng":          lng,
        "radius_miles": 15.0,
        "timezone":     _timezone_for_state(state),
        "sources":      sources,
    }

    # Persist new market to registry (also fire-and-forget)
    asyncio.ensure_future(
        _persist_new_market(new_market, operator_id)
    )

    logger.info(f"[MarketDetect] New market created: {market_name} ({market_id})")
    return new_market


async def _geocode_address(address: str) -> tuple[float | None, float | None, str | None, str | None]:
    """Geocode using Nominatim (free, no key). Returns (lat, lng, city, state)."""
    try:
        url = "https://nominatim.openstreetmap.org/search"
        params = {"q": address, "format": "json", "limit": 1, "addressdetails": 1}
        async with httpx.AsyncClient() as c:
            r = await c.get(url, params=params,
                            headers={"User-Agent": "BeachHabitats/1.0 (market-detection)"})
            data = r.json()
        if not data:
            return None, None, None, None
        result  = data[0]
        addr    = result.get("address", {})
        city    = addr.get("city") or addr.get("town") or addr.get("village")
        state   = addr.get("state_code") or addr.get("state", "")[:2].upper()
        return float(result["lat"]), float(result["lon"]), city, state
    except Exception as e:
        logger.warning(f"Geocode failed: {e}")
        return None, None, None, None


def _default_sources_for_state(state: str) -> dict[str, bool]:
    """Return sensible default scrape sources for a given state."""
    base = {"eventbrite": True}
    state_sources = {
        "FL": {"visitflorida": True},
        "AL": {"gulfshores_com": True},
        "SC": {"visitmyrtlebeach": True},
        "NC": {"outerbanks": True},
        "TX": {"eventbrite": True},
        "GA": {"eventbrite": True},
        "VA": {"eventbrite": True},
        "MD": {"eventbrite": True},
        "NJ": {"eventbrite": True},
    }
    return {**base, **state_sources.get(state.upper(), {})}


def _timezone_for_state(state: str) -> str:
    eastern = {"FL", "GA", "SC", "NC", "VA", "MD", "NJ", "NY", "ME", "NH",
                "VT", "MA", "RI", "CT", "PA", "DE", "OH", "MI", "IN", "KY",
                "WV", "TN"}
    central = {"AL", "MS", "LA", "AR", "MO", "IL", "WI", "MN", "IA", "KS",
                "OK", "TX", "NE", "SD", "ND"}
    if state.upper() in eastern:
        return "America/New_York"
    if state.upper() in central:
        return "America/Chicago"
    return "America/Denver"


async def _register_operator_with_market(market_id: str, operator_id: str, operator_name: str):
    """Add operator_id to market_registry.operator_ids (best-effort)."""
    try:
        from app.db.session import get_async_session
        from db.models.market_events import MarketRegistryModel
        from sqlalchemy import select
        async with get_async_session() as db:
            row = (await db.execute(
                select(MarketRegistryModel).where(MarketRegistryModel.market_id == market_id)
            )).scalar_one_or_none()
            if row:
                ids = list(row.operator_ids or [])
                if operator_id not in ids:
                    ids.append(operator_id)
                    row.operator_ids = ids
                    await db.commit()
    except Exception as e:
        logger.debug(f"_register_operator_with_market failed (non-fatal): {e}")


async def _persist_new_market(market: dict, operator_id: str):
    """Insert a new MarketRegistryModel row for a freshly discovered market."""
    try:
        from app.db.session import get_async_session
        from db.models.market_events import MarketRegistryModel
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        async with get_async_session() as db:
            stmt = pg_insert(MarketRegistryModel).values(
                market_id             = market["id"],
                market_name           = market["name"],
                state_code            = market.get("state", "??"),
                center_lat            = market["lat"],
                center_lng            = market["lng"],
                radius_miles          = market.get("radius_miles", 15.0),
                timezone              = market.get("timezone", "America/Chicago"),
                sources_config        = build_market_sources_config(market.get("sources", {})),
                operator_ids          = [operator_id],
                scrape_enabled        = True,
                scrape_interval_hours = 24,
            ).on_conflict_do_update(
                index_elements=["market_id"],
                set_={"operator_ids": pg_insert(MarketRegistryModel).excluded.operator_ids}
            )
            await db.execute(stmt)
            await db.commit()

        logger.info(f"[MarketDetect] Persisted market '{market['id']}' to market_registry")

        # Auto-build: discover tourism URLs for this market (fire-and-forget)
        city  = market.get("name", "").split(",")[0].strip()
        state = market.get("state", "")
        if city and state:
            from tools.market_scraper_builder import auto_build_for_new_market
            asyncio.ensure_future(
                auto_build_for_new_market(
                    market_id   = market["id"],
                    market_name = market["name"],
                    city        = city,
                    state       = state,
                )
            )
            logger.info(f"[MarketBuilder] Queued scraper build for {market['name']}")

    except Exception as e:
        logger.debug(f"_persist_new_market failed (non-fatal): {e}")


# =============================================================================
# MAIN ORCHESTRATOR
# =============================================================================

class EventScrapeOrchestrator:
    """
    Runs all enabled sources for a market, deduplicates, persists to DB,
    emits DEMAND_PRESSURE signals, and indexes events into concierge RAG.

    Usage:
        async with EventScrapeOrchestrator() as orc:
            events = await orc.scrape_market("30a_fl")
    """

    def __init__(self, days_ahead: int = 90):
        self.days_ahead = days_ahead
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self):
        self._client = httpx.AsyncClient(follow_redirects=True, timeout=20)
        return self

    async def __aexit__(self, *_):
        if self._client:
            await self._client.aclose()

    @property
    def client(self) -> httpx.AsyncClient:
        if not self._client:
            raise RuntimeError("Use `async with EventScrapeOrchestrator()` context manager")
        return self._client

    async def scrape_market(self, market_id: str) -> list[ScrapedEvent]:
        """
        Scrape all enabled sources for a market.
        Returns the deduplicated list of new/updated events.
        """
        market_cfg = {**KNOWN_MARKETS.get(market_id, {}), "id": market_id}
        if not market_cfg.get("name"):
            # Try to load from DB registry
            market_cfg = await self._load_market_from_db(market_id)
        if not market_cfg:
            logger.error(f"Unknown market: {market_id}")
            return []

        all_events: list[ScrapedEvent] = []
        source_counts: dict[str, int] = {}
        sources_enabled = build_market_sources_config(market_cfg.get("sources", {}))
        logger.info(f"[EventScraper] scrape_market({market_id}): cfg={market_cfg.get('name')} sources={sources_enabled}")

        for source_key, src_cfg in sources_enabled.items():
            if not _source_is_enabled(src_cfg):
                continue
            evts: list[ScrapedEvent] = []
            if source_key == "eventbrite":
                evts = await EventbriteSource().fetch(self.client, market_cfg, self.days_ahead)
            elif source_key == "visitwaltoncounty":
                evts = await VisitWaltonSource().fetch(self.client, market_cfg, self.days_ahead)
            elif source_key == "30a_com":
                evts = await ThirtyASource(feed_url=src_cfg.get("feed_url")).fetch(
                    self.client, market_cfg, self.days_ahead
                )
            else:
                evts = await TourismBoardSource(source_key, src_cfg).fetch(
                    self.client, market_cfg, self.days_ahead
                )
            source_counts[source_key] = len(evts)
            all_events.extend(evts)

        # ── Deduplicate by title+date (cross-source fuzzy dedup) ─────────────
        deduped = _deduplicate(all_events)
        deduped = [ev.enrich() for ev in deduped]

        logger.info(
            f"[EventScraper] {market_cfg['name']}: "
            f"{len(all_events)} raw → {len(deduped)} after dedup"
        )

        # ── Persist to DB ─────────────────────────────────────────────────────
        saved, skipped = await self._persist_events(deduped)
        logger.info(f"[EventScraper] DB: {saved} saved, {skipped} already exist")

        # ── Emit DEMAND_PRESSURE signals ──────────────────────────────────────
        await self._emit_signals(deduped, market_cfg)

        # ── Emit geographic spillover signals into neighboring markets ─────────
        await self._emit_spillover_signals(deduped, market_cfg, KNOWN_MARKETS)

        # ── Index into concierge RAG ──────────────────────────────────────────
        await self._index_rag(deduped)

        # ── Update market registry scrape timestamp ───────────────────────────
        await self._mark_scraped(market_id, len(deduped), source_counts)

        return deduped

    async def scrape_all_markets(self) -> dict[str, int]:
        """Scrape all markets in the registry that are due for a refresh."""
        due = await self._get_due_markets()
        results: dict[str, int] = {}
        for market_id in due:
            try:
                events = await self.scrape_market(market_id)
                results[market_id] = len(events)
            except Exception as e:
                logger.error(f"[EventScraper] Failed to scrape {market_id}: {e}")
                results[market_id] = -1
        return results

    # ── DB persistence ────────────────────────────────────────────────────────

    async def _persist_events(self, events: list[ScrapedEvent]) -> tuple[int, int]:
        saved = skipped = 0
        try:
            from scripts.db_session_standalone import get_standalone_session
            from sqlalchemy import text
            import json as _json

            from sqlalchemy.dialects.postgresql import asyncpg as pg_asyncpg
            async with get_standalone_session() as db:
                for ev in events:
                    now = datetime.now(tz=timezone.utc)
                    # Serialize to JSON string, cast in SQL — required for asyncpg+text()
                    tags_json = _json.dumps(ev.tags or [])

                    base_params = {
                        "market_id": ev.market_id, "market_name": ev.market_name,
                        "title": ev.title, "description": ev.description or None,
                        "category": ev.category, "tags": tags_json,
                        "start_date": ev.start_date, "end_date": ev.end_date,
                        "start_time": ev.start_time, "end_time": ev.end_time,
                        "is_multi_day": ev.is_multi_day, "is_recurring": ev.is_recurring,
                        "venue_name": ev.venue_name, "venue_address": ev.venue_address,
                        "venue_lat": ev.venue_lat, "venue_lng": ev.venue_lng,
                        "estimated_attendance": ev.estimated_attendance,
                        "demand_radius_miles": ev.demand_radius_miles,
                        "demand_impact_score": ev.demand_impact_score,
                        "guest_relevance_score": ev.guest_relevance_score,
                        "booking_urgency_score": ev.booking_urgency_score,
                        "event_confidence_score": ev.event_confidence_score,
                        "event_class": ev.event_class,
                        "actionability": ev.actionability,
                        "source": ev.source, "source_url": ev.source_url,
                        "source_type": ev.source_type,
                        "source_count": ev.source_count,
                        "source_types": _json.dumps(ev.source_types or []),
                        "ticket_url": ev.ticket_url,
                        "ticket_price_range": ev.ticket_price_range,
                        "is_free": ev.is_free, "scraped_at": now,
                        "first_seen_at": ev.first_seen_at or now,
                        "last_seen_at": ev.last_seen_at or now,
                        "stale_after": ev.stale_after,
                    }

                    if ev.source_id:
                        await db.execute(text("""
                            INSERT INTO market_events (
                                market_id, market_name, title, description, category,
                                tags, start_date, end_date, start_time, end_time,
                                is_multi_day, is_recurring, venue_name, venue_address,
                                venue_lat, venue_lng, estimated_attendance,
                                demand_radius_miles, demand_impact_score,
                                guest_relevance_score, booking_urgency_score,
                                event_confidence_score, event_class, actionability,
                                source, source_id, source_url, source_type,
                                source_count, source_types, ticket_url,
                                ticket_price_range, is_free, is_active, scraped_at,
                                first_seen_at, last_seen_at, stale_after
                            ) VALUES (
                                :market_id, :market_name, :title, :description, :category,
                                CAST(:tags AS JSONB), :start_date, :end_date, :start_time, :end_time,
                                :is_multi_day, :is_recurring, :venue_name, :venue_address,
                                :venue_lat, :venue_lng, :estimated_attendance,
                                :demand_radius_miles, :demand_impact_score,
                                :guest_relevance_score, :booking_urgency_score,
                                :event_confidence_score, :event_class, :actionability,
                                :source, :source_id, :source_url, :source_type,
                                :source_count, CAST(:source_types AS JSONB), :ticket_url,
                                :ticket_price_range, :is_free, true, :scraped_at,
                                :first_seen_at, :last_seen_at, :stale_after
                            )
                            ON CONFLICT (market_id, source, source_id)
                            WHERE source_id IS NOT NULL
                            DO UPDATE SET
                                title               = EXCLUDED.title,
                                description         = EXCLUDED.description,
                                start_date          = EXCLUDED.start_date,
                                end_date            = EXCLUDED.end_date,
                                demand_impact_score = EXCLUDED.demand_impact_score,
                                guest_relevance_score = EXCLUDED.guest_relevance_score,
                                booking_urgency_score = EXCLUDED.booking_urgency_score,
                                event_confidence_score = EXCLUDED.event_confidence_score,
                                event_class         = EXCLUDED.event_class,
                                actionability       = EXCLUDED.actionability,
                                source_type         = EXCLUDED.source_type,
                                source_count        = EXCLUDED.source_count,
                                source_types        = EXCLUDED.source_types,
                                scraped_at          = EXCLUDED.scraped_at,
                                last_seen_at        = EXCLUDED.last_seen_at,
                                stale_after         = EXCLUDED.stale_after,
                                updated_at          = NOW()
                        """), {**base_params, "source_id": ev.source_id})
                        saved += 1
                    else:
                        exists = (await db.execute(text("""
                            SELECT 1 FROM market_events
                            WHERE market_id=:mid AND source=:src
                              AND title=:title AND start_date=:sd LIMIT 1
                        """), {"mid": ev.market_id, "src": ev.source,
                               "title": ev.title, "sd": ev.start_date})).fetchone()
                        if not exists:
                            await db.execute(text("""
                                INSERT INTO market_events (
                                    market_id, market_name, title, description, category,
                                    tags, start_date, end_date, start_time, end_time,
                                    is_multi_day, is_recurring, venue_name, venue_address,
                                    venue_lat, venue_lng, estimated_attendance,
                                    demand_radius_miles, demand_impact_score,
                                    guest_relevance_score, booking_urgency_score,
                                    event_confidence_score, event_class, actionability,
                                    source, source_url, source_type, source_count,
                                    source_types, ticket_url,
                                    ticket_price_range, is_free, is_active, scraped_at,
                                    first_seen_at, last_seen_at, stale_after
                                ) VALUES (
                                    :market_id, :market_name, :title, :description, :category,
                                    CAST(:tags AS JSONB), :start_date, :end_date, :start_time, :end_time,
                                    :is_multi_day, :is_recurring, :venue_name, :venue_address,
                                    :venue_lat, :venue_lng, :estimated_attendance,
                                    :demand_radius_miles, :demand_impact_score,
                                    :guest_relevance_score, :booking_urgency_score,
                                    :event_confidence_score, :event_class, :actionability,
                                    :source, :source_url, :source_type, :source_count,
                                    CAST(:source_types AS JSONB), :ticket_url,
                                    :ticket_price_range, :is_free, true, :scraped_at,
                                    :first_seen_at, :last_seen_at, :stale_after
                                )
                            """), base_params)
                            saved += 1
                        else:
                            skipped += 1

                await db.commit()
        except Exception as e:
            logger.error(f"[EventScraper] DB persist failed: {e}")

        return saved, skipped

    # ── Signal emission ────────────────────────────────────────────────────────

    async def _emit_spillover_signals(
        self,
        events: list[ScrapedEvent],
        source_market: dict,
        all_markets: dict,
    ):
        """
        For high-impact events (score >= 0.70), emit attenuated spillover signals
        into neighboring markets within 120 miles.

        Decay model: impact * exp(-distance / 40)
          - At 0 miles:  100% of impact (same market)
          - At 30 miles: 47% of impact  (Destin sees Gulf Coast Jam at ~0.42)
          - At 60 miles: 22% of impact  (30A sees Gulf Coast Jam at ~0.20)
          - At 120 miles: 5% of impact  (negligible)

        Only fires for events with demand_impact_score >= 0.70 because
        a local bar band doesn't spill over anywhere.
        """
        import math
        high_impact = [ev for ev in events if (ev.demand_impact_score or 0) >= 0.70]
        if not high_impact:
            return

        src_lat = source_market.get("lat", 0)
        src_lng = source_market.get("lng", 0)

        def haversine_miles(lat1, lng1, lat2, lng2) -> float:
            R = 3959
            d_lat = math.radians(lat2 - lat1)
            d_lng = math.radians(lng2 - lng1)
            a = (math.sin(d_lat/2)**2
                 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
                 * math.sin(d_lng/2)**2)
            return R * 2 * math.asin(math.sqrt(a))

        try:
            from scripts.db_session_standalone import get_standalone_session
            from sqlalchemy import text
            import json as _json
            import uuid as _uuid

            MARKET_TENANT = "00000000-0000-0000-0000-000000000000"
            now = datetime.now(tz=timezone.utc)

            async with get_standalone_session() as db:
                for neighbor_id, neighbor in all_markets.items():
                    if neighbor_id == source_market.get("id"):
                        continue

                    dist = haversine_miles(
                        src_lat, src_lng,
                        neighbor.get("lat", 0), neighbor.get("lng", 0)
                    )
                    if dist > 120:
                        continue

                    # Exponential decay: full impact decays to ~5% at 120 miles
                    decay = math.exp(-dist / 40.0)

                    for ev in high_impact:
                        base_impact = ev.demand_impact_score or 0
                        spill_impact = round(base_impact * decay, 3)
                        if spill_impact < 0.10:
                            continue  # Not worth recording below 10%

                        signal_id = _uuid.uuid4()
                        tenant_id = _uuid.UUID(MARKET_TENANT)
                        meta = _json.dumps({
                            "explanation": (
                                f"Spillover from {source_market.get('name', source_market.get('id'))}: "
                                f"{ev.title} ({dist:.0f} miles away, {decay*100:.0f}% spillover)"
                            ),
                            "source_market": source_market.get("id"),
                            "source_event": ev.title,
                            "distance_miles": round(dist, 1),
                            "decay_factor": round(decay, 3),
                            "sample_size": 1,
                            "methodology": "geographic_decay_v1",
                        })
                        await db.execute(text("""
                            INSERT INTO signals (
                                signal_id, tenant_id, signal_type, scope, geo_id,
                                value, confidence, source, detector_name, detector_version,
                                time_window, valid_from, valid_until,
                                decay_profile, geo_sensitivity, metadata,
                                schema_version, detected_at
                            ) VALUES (
                                :sid, :tenant, 'demand_pressure', 'geo', :geo_id,
                                :value, :confidence, 'internal_analytics',
                                'spillover_detector', '1.0.0',
                                'forward_30d', :valid_from, :valid_until,
                                'ephemeral', 'regional', CAST(:metadata AS JSONB),
                                '1.0.0', :now
                            )
                            ON CONFLICT (signal_id) DO NOTHING
                        """), {
                            "sid": signal_id, "tenant": tenant_id,
                            "geo_id": neighbor_id,
                            "value": spill_impact,
                            "confidence": round(0.6 * decay, 3),  # Lower confidence for spillover
                            "valid_from": ev.start_date,
                            "valid_until": ev.end_date,
                            "metadata": meta, "now": now,
                        })

                await db.commit()
                spillover_count = sum(1 for ev in high_impact for n in all_markets
                                      if n != source_market.get("id"))
                logger.info(
                    f"[EventScraper] Spillover signals emitted for "
                    f"{len(high_impact)} high-impact events from {source_market.get('name')}"
                )
        except Exception as e:
            logger.warning(f"[EventScraper] Spillover signal emit failed (non-fatal): {e}")

    async def _emit_signals(self, events: list[ScrapedEvent], market: dict):
        """
        Emit one DEMAND_PRESSURE signal per event, scoped to GEO.
        Uses raw SQL to avoid ORM model metadata attribute conflicts.
        """
        try:
            from scripts.db_session_standalone import get_standalone_session
            from sqlalchemy import text
            import json as _json
            import uuid as _uuid
            import uuid as _uuid2  # alias used below

            MARKET_TENANT = "00000000-0000-0000-0000-000000000000"
            now = datetime.now(tz=timezone.utc)

            import uuid as _uuid2
            async with get_standalone_session() as db:
                for ev in events:
                    impact = ev.demand_impact_score or 0.3
                    confidence = min(0.9, impact + 0.1)
                    # Pass UUIDs as actual UUID objects, dict as dict — asyncpg handles the types
                    signal_id = _uuid2.uuid4()
                    tenant_id = _uuid2.UUID(MARKET_TENANT)
                    meta = _json.dumps({
                        "explanation": f"Local event: {ev.title}",
                        "sample_size": 1,
                        "methodology": "event_scraper_v1",
                    })
                    await db.execute(text("""
                        INSERT INTO signals (
                            signal_id, tenant_id, signal_type, scope, geo_id,
                            value, confidence, source, detector_name, detector_version,
                            time_window, valid_from, valid_until,
                            decay_profile, geo_sensitivity, metadata,
                            schema_version, detected_at
                        ) VALUES (
                            :sid, :tenant, 'demand_pressure', 'geo', :geo_id,
                            :value, :confidence, 'internal_analytics', 'event_scraper', '1.0.0',
                            'forward_30d', :valid_from, :valid_until,
                            'ephemeral', 'local', CAST(:metadata AS JSONB),
                            '1.0.0', :now
                        )
                        ON CONFLICT (signal_id) DO NOTHING
                    """), {
                        "sid": signal_id, "tenant": tenant_id,
                        "geo_id": ev.market_id, "value": impact,
                        "confidence": confidence, "valid_from": ev.start_date,
                        "valid_until": ev.end_date, "metadata": meta, "now": now,
                    })

                await db.commit()
                logger.info(f"[EventScraper] Emitted {len(events)} DEMAND_PRESSURE signals for {market['name']}")
        except Exception as e:
            logger.warning(f"[EventScraper] Signal emit failed (non-fatal): {e}")

    # ── RAG indexing ──────────────────────────────────────────────────────────

    async def _index_rag(self, events: list[ScrapedEvent]):
        """Insert events into concierge_knowledge for FAQ/RAG pipeline. Raw SQL."""
        try:
            from scripts.db_session_standalone import get_standalone_session
            from sqlalchemy import text
            import uuid as _uuid

            async with get_standalone_session() as db:
                for ev in events:
                    month_label = ev.start_date.strftime("%B %Y")
                    question = f"What events are happening near {ev.market_name} in {month_label}?"
                    rag_text = _event_to_rag_text(ev)
                    knowledge_id = str(_uuid.uuid5(
                        _uuid.NAMESPACE_URL,
                        f"event:{ev.market_id}:{ev.source}:{ev.source_id or ev.title}:{ev.start_date}"
                    ))
                    valid_until = ev.end_date + timedelta(days=1)

                    await db.execute(text("""
                        INSERT INTO concierge_knowledge (
                            knowledge_id, property_external_id, category,
                            question, answer, confidence, source,
                            valid_from, valid_until, is_active
                        ) VALUES (
                            :kid, :prop, 'local_events',
                            :question, :answer, 0.85, :source,
                            :valid_from, :valid_until, true
                        )
                        ON CONFLICT (knowledge_id) DO UPDATE SET
                            answer      = EXCLUDED.answer,
                            valid_until = EXCLUDED.valid_until,
                            updated_at  = NOW()
                    """), {
                        "kid": knowledge_id, "prop": ev.market_id,
                        "question": question, "answer": rag_text,
                        "source": f"event_scraper:{ev.source}",
                        "valid_from": ev.start_date, "valid_until": valid_until,
                    })

                await db.commit()
                logger.info(f"[EventScraper] RAG-indexed {len(events)} events")
        except Exception as e:
            logger.warning(f"[EventScraper] RAG index failed (non-fatal): {e}")

    # ── Housekeeping ──────────────────────────────────────────────────────────

    async def _load_market_from_db(self, market_id: str) -> dict | None:
        try:
            from scripts.db_session_standalone import get_standalone_session as get_async_session
            from db.models.market_events import MarketRegistryModel
            from sqlalchemy import select
            async with get_async_session() as db:
                row = (await db.execute(
                    select(MarketRegistryModel).where(
                        MarketRegistryModel.market_id == market_id
                    )
                )).scalar_one_or_none()
            if not row:
                return None
            return {
                "id":           row.market_id,
                "name":         row.market_name,
                "state":        row.state_code,
                "lat":          row.center_lat,
                "lng":          row.center_lng,
                "radius_miles": row.radius_miles,
                "timezone":     row.timezone,
                "sources":      build_market_sources_config(row.sources_config or {}),
            }
        except Exception as e:
            logger.warning(f"_load_market_from_db({market_id}): {e}")
            return None

    async def _get_due_markets(self) -> list[str]:
        """
        Return market_ids from market_registry that are due for a scrape.

        market_registry is seeded by migration 024 and grown by operator
        onboarding (resolve_operator_market).  This method never falls back
        to hardcoded data — if the registry is empty something is wrong with
        the deployment and we want to know about it, not silently scrape
        a hardcoded list.
        """
        from scripts.db_session_standalone import get_standalone_session as get_async_session
        from db.models.market_events import MarketRegistryModel
        from sqlalchemy import select

        async with get_async_session() as db:
            rows = (await db.execute(
                select(MarketRegistryModel).where(
                    MarketRegistryModel.scrape_enabled == True
                )
            )).scalars().all()

        if not rows:
            logger.warning(
                "[EventScraper] market_registry has no scrape-enabled markets. "
                "Run migration 024 or insert rows manually."
            )
            return []

        due = []
        now = datetime.now(tz=timezone.utc)
        for row in rows:
            if row.last_scraped_at is None:
                due.append(row.market_id)
                continue
            age_hours = (now - row.last_scraped_at).total_seconds() / 3600
            if age_hours >= (row.scrape_interval_hours or 24):
                due.append(row.market_id)

        logger.info(f"[EventScraper] {len(due)} markets due for scrape out of {len(rows)} enabled")
        return due

    async def _mark_scraped(self, market_id: str, event_count: int, source_counts: dict[str, int] | None = None):
        """Update scrape timestamp and per-source health metadata."""
        try:
            from scripts.db_session_standalone import get_standalone_session as get_async_session
            from sqlalchemy import text
            async with get_async_session() as db:
                row = (await db.execute(text(
                    "SELECT last_scrape_event_count, sources_config FROM market_registry WHERE market_id = :mid"
                ), {"mid": market_id})).fetchone()

                zero_streak = 0
                source_counts = source_counts or {}
                sc = _normalize_market_sources((row[1] or {}) if row else {})
                for source_key, count in source_counts.items():
                    source_cfg = _normalize_market_source_config(source_key, sc.get(source_key, {}))
                    health = dict(source_cfg.get("health") or {})
                    previous = int(health.get("zero_result_streak", 0) or 0)
                    zero_result_streak = previous + 1 if count == 0 else 0
                    health.update({
                        "last_run_at": datetime.now(tz=timezone.utc).isoformat(),
                        "last_event_count": count,
                        "zero_result_streak": zero_result_streak,
                        "last_status": "zero_results" if count == 0 else "success",
                    })
                    if zero_result_streak >= 3:
                        source_cfg["enabled"] = False
                        health["last_status"] = "auto_disabled"
                        logger.warning(
                            f"[EventScraper] Auto-disabled source '{source_key}' for market '{market_id}' "
                            f"after {zero_result_streak} zero-result runs"
                        )
                    source_cfg["health"] = health
                    sc[source_key] = source_cfg

                if row and event_count == 0:
                    import json as _json
                    zero_streak = sc.get("_zero_streak", 0) + 1
                    sc["_zero_streak"] = zero_streak
                    if zero_streak >= 3:
                        logger.warning(
                            f"[EventScraper] Market '{market_id}' returned 0 events "
                            f"{zero_streak} times in a row. Check source URLs/selectors."
                        )
                    await db.execute(text("""
                        UPDATE market_registry SET
                            last_scraped_at         = NOW(),
                            last_scrape_status      = :status,
                            last_scrape_event_count = :count,
                            sources_config          = CAST(:sc AS JSONB)
                        WHERE market_id = :mid
                    """), {
                        "mid": market_id, "count": event_count,
                        "status": "zero_results" if event_count == 0 else "success",
                        "sc": _json.dumps(sc),
                    })
                else:
                    import json as _json
                    sc.pop("_zero_streak", None)
                    await db.execute(text("""
                        UPDATE market_registry SET
                            last_scraped_at         = NOW(),
                            last_scrape_status      = 'success',
                            last_scrape_event_count = :count,
                            sources_config          = CAST(:sc AS JSONB)
                        WHERE market_id = :mid
                    """), {"mid": market_id, "count": event_count, "sc": _json.dumps(sc)})
                await db.commit()
        except Exception as e:
            logger.debug(f"_mark_scraped({market_id}) failed (non-fatal): {e}")


# =============================================================================
# HELPERS
# =============================================================================

def _deduplicate(events: list[ScrapedEvent]) -> list[ScrapedEvent]:
    """
    Cross-source dedup: same title + start_date = same event.
    Prefer Eventbrite (has source_id + attendance) over HTML scrapes.
    """
    seen: dict[str, ScrapedEvent] = {}
    SOURCE_PRIORITY = {"eventbrite": 3, "30a_com": 2, "visitwaltoncounty": 1}
    for ev in events:
        key = f"{ev.title.lower().strip()}|{ev.start_date}"
        existing = seen.get(key)
        if existing is None:
            ev.source_type = ev.source_type or SOURCE_TYPE_MAP.get(ev.source, "calendar")
            ev.source_types = sorted(set((ev.source_types or []) + [ev.source_type]))
            ev.observed_sources = sorted(set((ev.observed_sources or []) + [ev.source]))
            ev.source_count = max(1, len(ev.observed_sources))
            seen[key] = ev
        else:
            ev.source_type = ev.source_type or SOURCE_TYPE_MAP.get(ev.source, "calendar")
            merged_types = sorted(set((existing.source_types or []) + (ev.source_types or []) + [existing.source_type or SOURCE_TYPE_MAP.get(existing.source, "calendar"), ev.source_type]))
            merged_sources = sorted(set((existing.observed_sources or [existing.source]) + (ev.observed_sources or [ev.source])))
            existing.source_types = merged_types
            existing.observed_sources = merged_sources
            existing.source_count = len(merged_sources)
            if SOURCE_PRIORITY.get(ev.source, 0) > SOURCE_PRIORITY.get(existing.source, 0):
                ev.source_types = merged_types
                ev.observed_sources = merged_sources
                ev.source_count = len(merged_sources)
                ev.first_seen_at = existing.first_seen_at or ev.first_seen_at
                seen[key] = ev
    return list(seen.values())


def _infer_category(text: str) -> str:
    text = text.lower()
    if any(w in text for w in ["concert", "music", "band", "live music", "songwriters", "jazz", "bluegrass"]):
        return "music"
    if any(w in text for w in ["festival", "fest", "carnival"]):
        return "festival"
    if any(w in text for w in ["art", "gallery", "exhibition", "craft", "mural"]):
        return "art"
    if any(w in text for w in ["food", "wine", "beer", "tasting", "seafood", "culinary", "bbq"]):
        return "food"
    if any(w in text for w in ["run", "race", "marathon", "triathlon", "tournament", "fishing", "surf", "golf"]):
        return "sports"
    if any(w in text for w in ["kid", "family", "children", "parade"]):
        return "family"
    if any(w in text for w in ["holiday", "christmas", "halloween", "thanksgiving", "july 4", "independence"]):
        return "holiday"
    if any(w in text for w in ["market", "farmers", "bazaar", "artisan"]):
        return "community"
    return "other"


def _map_category(eventbrite_cat: str) -> str:
    mapping = {
        "music": "music", "performing arts": "music", "arts": "art",
        "food & drink": "food", "food": "food",
        "sports & fitness": "sports", "sports": "sports",
        "family & education": "family", "family": "family",
        "festivals": "festival", "festival": "festival",
        "community": "community", "holiday": "holiday",
        "film, media & entertainment": "other",
    }
    for k, v in mapping.items():
        if k in eventbrite_cat.lower():
            return v
    return "other"


def _parse_date_range(text: str) -> tuple[date | None, date | None]:
    """Best-effort date range parser for tourism site HTML."""
    text = text.strip()
    if not text:
        return None, None
    # Try ISO date
    iso = re.search(r"(\d{4}-\d{2}-\d{2})", text)
    if iso:
        d = date.fromisoformat(iso.group(1))
        return d, d
    # Try "Month DD, YYYY" or "Month DD–DD, YYYY"
    m = re.search(
        r"(\w+ \d{1,2}(?:–\d{1,2})?,?\s*\d{4})",
        text, re.I
    )
    if m:
        raw = m.group(1)
        try:
            # Single date
            d = datetime.strptime(raw, "%B %d, %Y").date()
            return d, d
        except Exception:
            pass
        # Range like "June 5–7, 2025"
        rng = re.search(r"(\w+)\s+(\d{1,2})–(\d{1,2}),?\s*(\d{4})", raw)
        if rng:
            try:
                month, d1, d2, yr = rng.groups()
                start = datetime.strptime(f"{month} {d1} {yr}", "%B %d %Y").date()
                end   = datetime.strptime(f"{month} {d2} {yr}", "%B %d %Y").date()
                return start, end
            except Exception:
                pass
    return None, None


def _parse_iso_date(s: str) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except Exception:
        return None


def _safe_float(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except Exception:
        return None


def _safe_int(v: Any) -> int | None:
    try:
        return int(v) if v is not None else None
    except Exception:
        return None


def _url_to_id(url: str | None) -> str | None:
    if not url:
        return None
    # Extract last non-trivial path segment as a stable ID
    parts = [p for p in url.rstrip("/").split("/") if p and p not in ("www",)]
    return parts[-1][:100] if parts else None


def _event_to_rag_text(ev: ScrapedEvent) -> str:
    lines = [f"EVENT: {ev.title}"]
    date_str = ev.start_date.strftime("%B %d, %Y")
    if ev.is_multi_day and ev.end_date != ev.start_date:
        date_str += f" – {ev.end_date.strftime('%B %d, %Y')}"
    if ev.start_time:
        date_str += f", {ev.start_time}"
    lines.append(f"When: {date_str}")
    if ev.venue_name:
        loc = ev.venue_name
        if ev.venue_address:
            loc += f", {ev.venue_address}"
        lines.append(f"Where: {loc}")
    if ev.description:
        desc = ev.description[:300].rstrip()
        if len(ev.description) > 300:
            desc += "…"
        lines.append(f"About: {desc}")
    if ev.ticket_price_range or ev.is_free:
        price = "Free" if ev.is_free else ev.ticket_price_range
        lines.append(f"Admission: {price}")
    if ev.ticket_url:
        lines.append(f"Tickets/Info: {ev.ticket_url}")
    if ev.tags:
        lines.append(f"Tags: {', '.join(ev.tags)}")
    return "\n".join(lines)


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    import argparse
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Local Event Scraper")
    parser.add_argument("--market", default="30a_fl",
                        help=f"Market ID ({', '.join(KNOWN_MARKETS)})")
    parser.add_argument("--days-ahead", type=int, default=90,
                        help="How many days forward to scrape")
    parser.add_argument("--all", action="store_true",
                        help="Scrape all known markets")
    args = parser.parse_args()

    async def _run():
        async with EventScrapeOrchestrator(days_ahead=args.days_ahead) as orc:
            if args.all:
                results = await orc.scrape_all_markets()
                for mid, count in results.items():
                    status = f"{count} events" if count >= 0 else "FAILED"
                    print(f"  {mid}: {status}")
            else:
                events = await orc.scrape_market(args.market)
                print(f"\n✅  {len(events)} events scraped for {args.market}")
                for ev in sorted(events, key=lambda e: e.start_date)[:10]:
                    print(f"  {ev.start_date}  [{ev.category:10s}]  {ev.title[:60]}")
                if len(events) > 10:
                    print(f"  ... and {len(events) - 10} more")

    asyncio.run(_run())
