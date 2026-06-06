#!/usr/bin/env python3
"""
Market Scraper Builder

When a new market is detected (e.g. Breckenridge, CO) this module:

  1. Searches for that market's official tourism/events pages using a
     combination of known patterns + a lightweight web search via
     DuckDuckGo Instant Answer API (no API key, public).

  2. Probes each candidate URL to confirm it actually returns event data
     (JSON-LD Event schema or recognisable event card HTML).

  3. Writes a validated MarketSourceConfig into market_registry.sources_config
     so EventScrapeOrchestrator picks it up on the next run — no code changes,
     no deploys.

  4. Optionally persists the validated source config to a local JSON catalogue
     (tools/market_data/source_configs/) so it survives DB resets and can be
     reviewed / committed to the repo.

Architecture contract:
  - TourismBoardSource (in event_scraper.py) is the generic scraper.
    All this module does is *find* the right URL for a new market and write
    it into the sources_config that TourismBoardSource reads at runtime.
  - No scraper subclasses are generated.  The URL + domain pair IS the scraper.
  - Eventbrite is always enabled as the baseline (geo-based, needs no URL).

Called from:
  tools/event_scraper.py  → _persist_new_market()
  workers/ingestion/event_workers.py → OperatorMarketDetectWorker

Usage (CLI):
  python market_scraper_builder.py --city "Breckenridge" --state CO
  python market_scraper_builder.py --market-id breckenridge_co --dry-run
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import random
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Where we persist discovered source configs locally
SOURCE_CONFIG_DIR = Path(__file__).parent / "market_data" / "source_configs"

# ── User-agent pool ────────────────────────────────────────────────────────────
_UA = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.3 Safari/605.1.15",
]


# =============================================================================
# DATA MODEL
# =============================================================================

@dataclass
class CandidateSource:
    """A potential event source URL for a market, before validation."""
    source_key:  str          # e.g. "visit_breckenridge"
    url:         str          # Full events page URL
    domain:      str          # e.g. "gobreck.com"
    label:       str          # Human-readable: "Visit Breckenridge"
    confidence:  float = 0.0  # 0–1 after probe
    has_jsonld:  bool  = False
    has_cards:   bool  = False
    event_count: int   = 0
    probe_error: str | None = None


@dataclass
class MarketSourceConfig:
    """
    Validated source configuration for one market.
    Written into market_registry.sources_config and the local JSON catalogue.
    """
    market_id:   str
    market_name: str
    built_at:    str = field(default_factory=lambda: datetime.now(tz=timezone.utc).isoformat())

    # Always True — Eventbrite is geo-based, needs no URL
    eventbrite_enabled: bool = True

    # Discovered tourism board sources: key → {"url", "domain", "label", "enabled", "confidence"}
    tourism_sources: dict[str, dict] = field(default_factory=dict)

    # Keys that passed probe validation (confidence ≥ MIN_CONFIDENCE)
    validated_keys: list[str] = field(default_factory=list)

    def to_sources_config(self) -> dict:
        """
        Returns the dict written into market_registry.sources_config.
        Format matches what EventScrapeOrchestrator.scrape_market() reads.
        """
        cfg: dict[str, Any] = {
            "eventbrite": {
                "enabled": True,
                "parser_type": "api",
                "health": {"last_status": "ready", "zero_result_streak": 0},
            }
        }
        for key, meta in self.tourism_sources.items():
            if meta.get("enabled"):
                cfg[key] = {
                    "enabled":    True,
                    "parser_type": "html_listing",
                    "list_url":   meta["url"],
                    "url":        meta["url"],
                    "domain":     meta["domain"],
                    "label":      meta["label"],
                    "confidence": meta.get("confidence", 0.0),
                    "event_card_selectors": [
                        ".event-card",
                        ".views-row",
                        "article.event",
                    ],
                    "detail_link_selectors": [
                        "a[href*='/events/']",
                        "a[href*='/event/']",
                    ],
                    "health": {
                        "last_status": "validated",
                        "zero_result_streak": 0,
                    },
                }
        return cfg


# =============================================================================
# SEARCH STRATEGIES
# =============================================================================

# Known URL patterns for common tourism site structures.
# Filled in before web search so common markets resolve instantly.
URL_PATTERN_TEMPLATES: list[str] = [
    "https://visit{slug}.com/events",
    "https://visit{slug}.com/events/",
    "https://www.visit{slug}.com/events",
    "https://go{slug}.com/events",
    "https://www.go{slug}.com/events",
    "https://{slug}.com/events",
    "https://www.{slug}.com/events",
    "https://discover{slug}.com/events",
    "https://explore{slug}.com/events",
    "https://{slug}chamber.com/events",
    "https://www.{slug}colorado.com/events",
    "https://www.{slug}utah.com/events",
    "https://www.{slug}tn.com/events",
]

# State-level tourism URLs — used as fallback when city-level fails
STATE_TOURISM_URLS: dict[str, dict] = {
    "CO": {"url": "https://www.colorado.com/events", "domain": "colorado.com",     "label": "Colorado Tourism"},
    "UT": {"url": "https://www.visitutah.com/events", "domain": "visitutah.com",   "label": "Visit Utah"},
    "TN": {"url": "https://www.tnvacation.com/events","domain": "tnvacation.com",  "label": "Tennessee Vacation"},
    "GA": {"url": "https://www.exploregeorgia.org/events","domain": "exploregeorgia.org","label": "Explore Georgia"},
    "TX": {"url": "https://www.traveltexas.com/events","domain": "traveltexas.com","label": "Travel Texas"},
    "VA": {"url": "https://www.virginia.org/events",  "domain": "virginia.org",    "label": "Virginia Tourism"},
    "MT": {"url": "https://www.visitmt.com/events",   "domain": "visitmt.com",     "label": "Visit Montana"},
    "WY": {"url": "https://www.travelwyoming.com/events","domain": "travelwyoming.com","label": "Travel Wyoming"},
    "ID": {"url": "https://www.visitidaho.org/events","domain": "visitidaho.org",  "label": "Visit Idaho"},
    "AZ": {"url": "https://www.visitarizona.com/events","domain": "visitarizona.com","label": "Visit Arizona"},
    "NM": {"url": "https://www.newmexico.org/events", "domain": "newmexico.org",   "label": "New Mexico Tourism"},
    "OR": {"url": "https://traveloregon.com/events",  "domain": "traveloregon.com","label": "Travel Oregon"},
    "WA": {"url": "https://www.experiencewa.com/events","domain": "experiencewa.com","label": "Experience WA"},
    "ME": {"url": "https://visitmaine.com/events",    "domain": "visitmaine.com",  "label": "Visit Maine"},
    "VT": {"url": "https://www.vermontvacation.com/events","domain": "vermontvacation.com","label": "Vermont Vacation"},
    "NH": {"url": "https://www.visitnh.gov/events",   "domain": "visitnh.gov",     "label": "Visit NH"},
    "MI": {"url": "https://www.michigan.org/events",  "domain": "michigan.org",    "label": "Pure Michigan"},
    "MN": {"url": "https://www.exploreminnesota.com/events","domain": "exploreminnesota.com","label": "Explore Minnesota"},
    "WI": {"url": "https://www.travelwisconsin.com/events","domain": "travelwisconsin.com","label": "Travel Wisconsin"},
}

# Minimum probe confidence to enable a source
MIN_CONFIDENCE = 0.40


# =============================================================================
# URL DISCOVERY
# =============================================================================

class MarketURLDiscovery:
    """
    Finds candidate event page URLs for a city/market using two strategies:

    Strategy 1 — Pattern expansion
      Expand URL_PATTERN_TEMPLATES with the city slug and check HEAD responses.
      Fast (no HTML parsing), covers ~70% of tourism sites.

    Strategy 2 — DuckDuckGo Instant Answer
      Query "visit {city} {state} events" via DDG's public JSON API.
      Extracts the AbstractURL and RelatedTopics for candidate domains.
      No API key. Rate limit: ~1 req/s.
    """

    DDG_API = "https://api.duckduckgo.com/"

    def __init__(self, client: httpx.AsyncClient):
        self.client = client

    async def discover(self, city: str, state: str, market_id: str) -> list[CandidateSource]:
        """Return a ranked list of candidate sources for the market."""
        candidates: list[CandidateSource] = []
        slug = city.lower().replace(" ", "").replace("-", "")

        # ── Strategy 1: URL pattern expansion ────────────────────────────────
        pattern_candidates = await self._expand_patterns(slug, city, market_id)
        candidates.extend(pattern_candidates)

        # ── Strategy 2: DuckDuckGo search ────────────────────────────────────
        ddg_candidates = await self._ddg_search(city, state, market_id)
        # Merge: avoid duplicates by domain
        existing_domains = {c.domain for c in candidates}
        for c in ddg_candidates:
            if c.domain not in existing_domains:
                candidates.append(c)
                existing_domains.add(c.domain)

        # ── Strategy 3: State-level fallback ─────────────────────────────────
        if state.upper() in STATE_TOURISM_URLS:
            st = STATE_TOURISM_URLS[state.upper()]
            if st["domain"] not in existing_domains:
                candidates.append(CandidateSource(
                    source_key  = f"state_{state.lower()}_tourism",
                    url         = st["url"],
                    domain      = st["domain"],
                    label       = st["label"],
                    confidence  = 0.30,  # low prior — state pages are broad
                ))

        logger.info(f"[Discover] {city}, {state}: {len(candidates)} candidates found")
        return candidates

    async def _expand_patterns(
        self, slug: str, city: str, market_id: str
    ) -> list[CandidateSource]:
        """Check HEAD for each URL pattern template."""
        results: list[CandidateSource] = []
        seen_domains: set[str] = set()

        for template in URL_PATTERN_TEMPLATES:
            url = template.format(slug=slug)
            domain = urlparse(url).netloc.lstrip("www.")
            if domain in seen_domains:
                continue

            try:
                await asyncio.sleep(random.uniform(0.3, 0.8))
                r = await self.client.head(
                    url,
                    headers={"User-Agent": random.choice(_UA)},
                    timeout=8,
                    follow_redirects=True,
                )
                if r.status_code in (200, 301, 302):
                    final_url = str(r.url)
                    final_domain = urlparse(final_url).netloc.lstrip("www.")
                    source_key = f"visit_{slug}" if len(results) == 0 else f"visit_{slug}_{len(results)}"
                    results.append(CandidateSource(
                        source_key = source_key,
                        url        = final_url,
                        domain     = final_domain,
                        label      = f"Visit {city}",
                        confidence = 0.50,  # HEAD hit — pending probe
                    ))
                    seen_domains.add(final_domain)
                    seen_domains.add(domain)
                    logger.debug(f"[Pattern] HIT: {url} → {final_url}")
                    if len(results) >= 3:
                        break
            except Exception:
                pass  # HEAD miss — silent

        return results

    async def _ddg_search(
        self, city: str, state: str, market_id: str
    ) -> list[CandidateSource]:
        """Query DuckDuckGo Instant Answer API for tourism event URLs."""
        results: list[CandidateSource] = []
        queries = [
            f"visit {city} {state} events official",
            f"{city} {state} tourism events calendar",
        ]

        for query in queries:
            try:
                await asyncio.sleep(random.uniform(1.0, 2.0))
                r = await self.client.get(
                    self.DDG_API,
                    params={"q": query, "format": "json", "no_redirect": "1", "no_html": "1"},
                    headers={"User-Agent": "BeachHabitats/1.0 (market-builder)"},
                    timeout=10,
                )
                if r.status_code != 200:
                    continue
                data = r.json()
            except Exception as e:
                logger.debug(f"[DDG] query failed: {e}")
                continue

            # AbstractURL — usually the most authoritative result
            abstract_url = data.get("AbstractURL", "").strip()
            if abstract_url and _looks_like_events_page(abstract_url):
                domain = urlparse(abstract_url).netloc.lstrip("www.")
                results.append(CandidateSource(
                    source_key = f"ddg_{domain.replace('.', '_')}",
                    url        = abstract_url,
                    domain     = domain,
                    label      = data.get("AbstractSource") or f"Visit {city}",
                    confidence = 0.55,
                ))

            # RelatedTopics — secondary hits
            for topic in data.get("RelatedTopics", [])[:5]:
                url = topic.get("FirstURL", "")
                if not url or not _looks_like_events_page(url):
                    continue
                domain = urlparse(url).netloc.lstrip("www.")
                if any(c.domain == domain for c in results):
                    continue
                results.append(CandidateSource(
                    source_key = f"ddg_{domain.replace('.', '_')}",
                    url        = url,
                    domain     = domain,
                    label      = f"Visit {city}",
                    confidence = 0.40,
                ))

            if results:
                break  # Stop at first query that returns results

        return results


# =============================================================================
# SOURCE PROBER  (validates candidates by actually fetching the page)
# =============================================================================

class SourceProber:
    """
    Fetches each candidate URL and scores it by how much event data it contains.

    Scoring:
      +0.50  JSON-LD with @type Event/Festival found
      +0.30  recognisable event card HTML elements
      +0.10  per 5 events detected (up to +0.20 bonus)
      -0.20  page returned non-200
      -0.10  page is clearly a homepage redirect (no /event in path)
    """

    # CSS selectors that indicate event cards on tourism sites
    EVENT_CARD_SELECTORS = [
        ".event-card", ".event-item", ".tribe-event",
        "article.event", "[data-type='event']",
        ".views-row", ".event-listing", ".calendar-item",
        "[class*='event']", "[id*='event']",
    ]

    def __init__(self, client: httpx.AsyncClient):
        self.client = client

    async def probe(self, candidate: CandidateSource) -> CandidateSource:
        """Fetch the URL and score it. Returns the same object with updated fields."""
        try:
            await asyncio.sleep(random.uniform(1.5, 3.0))
            r = await self.client.get(
                candidate.url,
                headers={"User-Agent": random.choice(_UA)},
                timeout=15,
                follow_redirects=True,
            )
            if r.status_code != 200:
                candidate.confidence = max(0.0, candidate.confidence - 0.20)
                candidate.probe_error = f"HTTP {r.status_code}"
                return candidate

            soup = BeautifulSoup(r.text, "lxml")
            score = candidate.confidence  # start from discovery confidence

            # ── JSON-LD check ─────────────────────────────────────────────────
            jsonld_events = 0
            for script in soup.find_all("script", type="application/ld+json"):
                try:
                    data = json.loads(script.string or "{}")
                    items = data if isinstance(data, list) else [data]
                    for item in items:
                        t = item.get("@type", "")
                        if t in ("Event", "Festival", "MusicEvent",
                                 "SportsEvent", "FoodEvent", "ExhibitionEvent"):
                            jsonld_events += 1
                except Exception:
                    pass

            if jsonld_events > 0:
                candidate.has_jsonld = True
                score += 0.50
                score += min(0.20, jsonld_events * 0.02)
                candidate.event_count = jsonld_events

            # ── HTML card check ───────────────────────────────────────────────
            card_count = 0
            for selector in self.EVENT_CARD_SELECTORS:
                cards = soup.select(selector)
                if cards:
                    card_count += len(cards)
                    break  # one selector match is enough

            if card_count > 0:
                candidate.has_cards = True
                score += 0.30
                score += min(0.20, card_count * 0.01)
                if candidate.event_count == 0:
                    candidate.event_count = card_count

            # ── Path sanity check ─────────────────────────────────────────────
            path = urlparse(str(r.url)).path
            if "event" not in path.lower() and not candidate.has_jsonld and not candidate.has_cards:
                score -= 0.10  # redirected away from events page

            candidate.confidence = max(0.0, min(1.0, score))
            logger.debug(
                f"[Probe] {candidate.domain}: score={candidate.confidence:.2f} "
                f"jsonld={jsonld_events} cards={card_count}"
            )

        except Exception as e:
            candidate.confidence = 0.0
            candidate.probe_error = str(e)
            logger.debug(f"[Probe] {candidate.domain} error: {e}")

        return candidate

    async def probe_all(
        self, candidates: list[CandidateSource]
    ) -> list[CandidateSource]:
        """Probe all candidates concurrently (with a semaphore to be polite)."""
        sem = asyncio.Semaphore(3)  # max 3 concurrent fetches

        async def _probe_one(c: CandidateSource) -> CandidateSource:
            async with sem:
                return await self.probe(c)

        return list(await asyncio.gather(*[_probe_one(c) for c in candidates]))


# =============================================================================
# MAIN BUILDER
# =============================================================================

class MarketScraperBuilder:
    """
    Orchestrates discovery + probing for a new market, then writes the
    validated config into:
      1. market_registry.sources_config  (DB)
      2. tools/market_data/source_configs/{market_id}.json  (local catalogue)
      3. In-memory TOURISM_SOURCES dict in event_scraper.py  (runtime)

    Called automatically by _persist_new_market() when a new market is created.
    """

    def __init__(self, client: httpx.AsyncClient | None = None):
        self._owned_client = client is None
        self._client = client

    async def __aenter__(self):
        if self._owned_client:
            self._client = httpx.AsyncClient(follow_redirects=True, timeout=20)
        return self

    async def __aexit__(self, *_):
        if self._owned_client and self._client:
            await self._client.aclose()

    @property
    def client(self) -> httpx.AsyncClient:
        if not self._client:
            raise RuntimeError("Use `async with MarketScraperBuilder()` context manager")
        return self._client

    async def build(
        self,
        market_id:   str,
        market_name: str,
        city:        str,
        state:       str,
        dry_run:     bool = False,
    ) -> MarketSourceConfig:
        """
        Discover, probe, and persist source config for a new market.
        Returns the MarketSourceConfig (persisted unless dry_run=True).
        """
        logger.info(f"[Builder] Building scraper config for {market_name} ({market_id})")

        discovery = MarketURLDiscovery(self.client)
        prober    = SourceProber(self.client)

        # ── 1. Discover candidates ────────────────────────────────────────────
        candidates = await discovery.discover(city, state, market_id)

        if not candidates:
            logger.warning(f"[Builder] No candidates found for {market_name}")
            config = MarketSourceConfig(
                market_id   = market_id,
                market_name = market_name,
            )
            if not dry_run:
                await self._persist(config)
            return config

        # ── 2. Probe all candidates ───────────────────────────────────────────
        probed = await prober.probe_all(candidates)
        probed.sort(key=lambda c: c.confidence, reverse=True)

        # ── 3. Build config from validated candidates ─────────────────────────
        config = MarketSourceConfig(
            market_id   = market_id,
            market_name = market_name,
        )

        seen_domains: set[str] = set()
        for c in probed:
            if c.domain in seen_domains:
                continue
            seen_domains.add(c.domain)

            enabled = c.confidence >= MIN_CONFIDENCE
            config.tourism_sources[c.source_key] = {
                "url":        c.url,
                "domain":     c.domain,
                "label":      c.label,
                "enabled":    enabled,
                "confidence": round(c.confidence, 3),
                "has_jsonld": c.has_jsonld,
                "has_cards":  c.has_cards,
                "event_count":c.event_count,
                "probe_error":c.probe_error,
            }
            if enabled:
                config.validated_keys.append(c.source_key)

        logger.info(
            f"[Builder] {market_name}: {len(config.validated_keys)} sources validated "
            f"out of {len(probed)} probed — {config.validated_keys}"
        )

        # ── 4. Register validated sources with TourismBoardSource at runtime ──
        if not dry_run:
            _register_runtime_sources(config)
            await self._persist(config)

        return config

    async def _persist(self, config: MarketSourceConfig):
        """Write validated config to DB + local JSON catalogue."""
        await self._persist_to_db(config)
        self._persist_to_catalogue(config)

    async def _persist_to_db(self, config: MarketSourceConfig):
        """Update market_registry.sources_config for this market."""
        try:
            from app.db.session import get_async_session
            from db.models.market_events import MarketRegistryModel
            from sqlalchemy import update
            async with get_async_session() as db:
                await db.execute(
                    update(MarketRegistryModel)
                    .where(MarketRegistryModel.market_id == config.market_id)
                    .values(sources_config=config.to_sources_config())
                )
                await db.commit()
            logger.info(f"[Builder] DB updated for {config.market_id}")
        except Exception as e:
            logger.warning(f"[Builder] DB persist failed (non-fatal): {e}")

    def _persist_to_catalogue(self, config: MarketSourceConfig):
        """Write JSON to tools/market_data/source_configs/{market_id}.json."""
        try:
            SOURCE_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            path = SOURCE_CONFIG_DIR / f"{config.market_id}.json"
            path.write_text(
                json.dumps(asdict(config), indent=2, default=str),
                encoding="utf-8",
            )
            logger.info(f"[Builder] Catalogue written: {path}")
        except Exception as e:
            logger.warning(f"[Builder] Catalogue write failed (non-fatal): {e}")


# =============================================================================
# RUNTIME SOURCE REGISTRATION
# =============================================================================

def _register_runtime_sources(config: MarketSourceConfig):
    """
    Inject newly discovered sources into TOURISM_SOURCES in event_scraper.py
    so that EventScrapeOrchestrator.scrape_market() uses them immediately
    without a restart.

    This mutates the module-level TOURISM_SOURCES dict in event_scraper —
    safe because the orchestrator reads it fresh on each call.
    """
    try:
        from tools import event_scraper
        for key, meta in config.tourism_sources.items():
            if meta.get("enabled") and key not in event_scraper.TOURISM_SOURCES:
                event_scraper.TOURISM_SOURCES[key] = {
                    "url":    meta["url"],
                    "list_url": meta["url"],
                    "domain": meta["domain"],
                    "label":  meta["label"],
                    "parser_type": "html_listing",
                }
                logger.info(f"[Builder] Registered runtime source: {key} → {meta['url']}")
    except Exception as e:
        logger.warning(f"[Builder] Runtime registration failed (non-fatal): {e}")


def load_catalogue_config(market_id: str) -> MarketSourceConfig | None:
    """
    Load a previously built source config from the local catalogue.
    Used on startup to restore discovered sources without hitting the network.
    """
    path = SOURCE_CONFIG_DIR / f"{market_id}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return MarketSourceConfig(**data)
    except Exception as e:
        logger.warning(f"[Builder] Failed to load catalogue for {market_id}: {e}")
        return None


def restore_all_catalogue_sources():
    """
    Called at app startup. Loads all previously discovered market source
    configs from the catalogue and registers them into TOURISM_SOURCES
    so they are available without hitting the network again.
    """
    if not SOURCE_CONFIG_DIR.exists():
        return
    loaded = 0
    for path in SOURCE_CONFIG_DIR.glob("*.json"):
        market_id = path.stem
        config = load_catalogue_config(market_id)
        if config:
            _register_runtime_sources(config)
            loaded += 1
    if loaded:
        logger.info(f"[Builder] Restored {loaded} market source configs from catalogue")


# =============================================================================
# INTEGRATION HOOK  (called from event_scraper._persist_new_market)
# =============================================================================

async def auto_build_for_new_market(
    market_id:   str,
    market_name: str,
    city:        str,
    state:       str,
) -> dict:
    """
    Entry point called by _persist_new_market() after a new market row is
    created.  Runs the full discovery + probe + persist pipeline.

    Returns a summary dict for logging.
    """
    async with MarketScraperBuilder() as builder:
        config = await builder.build(
            market_id   = market_id,
            market_name = market_name,
            city        = city,
            state       = state,
        )

    return {
        "market_id":        config.market_id,
        "sources_validated":config.validated_keys,
        "sources_total":    len(config.tourism_sources),
        "eventbrite":       True,
    }


# =============================================================================
# HELPERS
# =============================================================================

def _looks_like_events_page(url: str) -> bool:
    """Heuristic: does this URL look like an events calendar page?"""
    url_lower = url.lower()
    if any(kw in url_lower for kw in ["/event", "/calendar", "/festival", "/things-to-do"]):
        return True
    # Exclude clearly wrong domains
    bad = ["facebook.com", "instagram.com", "twitter.com", "youtube.com",
           "tripadvisor.com", "yelp.com", "airbnb.com", "vrbo.com",
           "google.com", "wikipedia.org", "reddit.com"]
    return not any(b in url_lower for b in bad)


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

    parser = argparse.ArgumentParser(description="Market Scraper Builder")
    parser.add_argument("--city",      required=False, help="City name (e.g. 'Breckenridge')")
    parser.add_argument("--state",     required=False, help="State code (e.g. 'CO')")
    parser.add_argument("--market-id", required=False, help="Override market_id slug")
    parser.add_argument("--dry-run",   action="store_true", help="Discover + probe but don't write to DB")
    args = parser.parse_args()

    if not args.city or not args.state:
        parser.error("--city and --state are required")

    city      = args.city.strip()
    state     = args.state.strip().upper()
    market_id = args.market_id or f"{city.lower().replace(' ', '_')}_{state.lower()}"
    market_name = f"{city}, {state}"

    async def _run():
        async with MarketScraperBuilder() as builder:
            config = await builder.build(
                market_id   = market_id,
                market_name = market_name,
                city        = city,
                state       = state,
                dry_run     = args.dry_run,
            )

        print(f"\n{'='*60}")
        print(f"Market:  {config.market_name}  ({config.market_id})")
        print(f"Built:   {config.built_at}")
        print(f"Sources: {len(config.tourism_sources)} discovered, "
              f"{len(config.validated_keys)} validated\n")

        for key, meta in sorted(
            config.tourism_sources.items(),
            key=lambda x: x[1]["confidence"],
            reverse=True,
        ):
            status = "✅ ENABLED " if meta["enabled"] else "⚠️  SKIPPED"
            print(f"  {status}  [{meta['confidence']:.2f}]  {meta['label']}")
            print(f"           {meta['url']}")
            if meta.get("probe_error"):
                print(f"           error: {meta['probe_error']}")
            print()

        print(f"sources_config written: {not args.dry_run}")
        if args.dry_run:
            print("\n(dry-run — nothing persisted)")
        print(f"{'='*60}\n")

    asyncio.run(_run())
