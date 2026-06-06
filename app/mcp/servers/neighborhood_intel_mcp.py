"""
NeighborhoodIntelligenceMCPServer

Discovers hyper-local event sources for any neighborhood — Wynwood, Brickell,
Coral Gables, Buckhead, Wicker Park — without hardcoded URL lists.

WHY THIS EXISTS:
  MarketScraperBuilder finds city-level tourism boards (visitmiami.com) using
  URL pattern templates.  It cannot reliably find neighborhood-level sources
  (Wynwood BID events calendar, Coral Gables Cultural Affairs, Buckhead
  Coalition) because these have completely unpredictable URL patterns.

  Google Places finds businesses with coordinates. Eventbrite finds ticketed
  events geo-searched by lat/lng. But neither surfaces the community art walk,
  the neighborhood farmer's market, or the BID street festival that a local
  insider would know about.

  This MCP uses the LLM already powering Coral to generate targeted, intelligent
  search queries — "Wynwood Miami events calendar BID" — probes the results with
  the existing SourceProber, validates pages that actually contain event data,
  and caches them permanently so the work is done exactly once per neighborhood.

DEDUPLICATION STRATEGY:
  Every document written to knowledge_embeddings gets a doc_id that is a
  deterministic MD5 hash of content[:200] + operator_id + doc_type.
  The same place/event from multiple sources produces different content →
  different doc_ids → both indexed, similarity search surfaces the best match.
  The same event scraped twice produces identical content → same doc_id →
  upsert (no duplicate).

  For cross-source entity deduplication (same restaurant found via Google Places
  AND a tourism board scrape), we use a separate `source_dedup` metadata field:
    - google_place_id for Google Places results
    - eventbrite_event_id for Eventbrite results
    - neighborhood_source_key + url_hash for scraped sources
  Before indexing we check if any existing document has the same source key.
  If yes we upsert, not insert.

TOOLS EXPOSED:
  discover_neighborhood_sources(neighborhood, city, lat, lng)
    → Finds, probes, and caches event sources for a neighborhood

  get_neighborhood_events(neighborhood, market_id, operator_id)
    → Returns current events from all cached sources for a neighborhood

  get_cached_sources(market_id)
    → Lists all discovered sources for a market (dashboard use)

  invalidate_source(source_key)
    → Mark a source as stale so it gets re-discovered on next run

CALLED FROM:
  onboarding_agent._handle_knowledge_base() — once per new operator
  market_intelligence_worker — on weekly refresh cycle
  MarketScraperBuilder.auto_build_for_new_market() — for unknown markets
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from app.mcp.base import MCPResult, MCPServer, MCPTool

logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY", "")

# Source cache TTL — re-probe after 30 days
SOURCE_TTL_DAYS = 30

# Minimum probe confidence to cache a source
MIN_CONFIDENCE = 0.40

_UA = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.3 Safari/605.1.15",
]


# ─────────────────────────────────────────────────────────────────────────────
# Data models
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class NeighborhoodSource:
    """A validated event source for a specific neighborhood."""
    source_key: str          # deterministic: f"{market_id}_{neighborhood_slug}_{domain_slug}"
    neighborhood: str        # e.g. "Wynwood"
    neighborhood_slug: str   # e.g. "wynwood"
    market_id: str           # e.g. "MARKET_MIAMI"
    url: str
    domain: str
    label: str               # e.g. "Wynwood Arts District"
    confidence: float        # 0-1 from probe
    has_jsonld: bool
    has_event_cards: bool
    event_count_estimate: int
    discovered_at: str       # ISO datetime
    last_probed_at: str
    is_valid: bool = True

    @property
    def is_stale(self) -> bool:
        try:
            last = datetime.fromisoformat(self.last_probed_at)
            return datetime.utcnow() - last > timedelta(days=SOURCE_TTL_DAYS)
        except Exception:
            return True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_key": self.source_key,
            "neighborhood": self.neighborhood,
            "neighborhood_slug": self.neighborhood_slug,
            "market_id": self.market_id,
            "url": self.url,
            "domain": self.domain,
            "label": self.label,
            "confidence": self.confidence,
            "has_jsonld": self.has_jsonld,
            "has_event_cards": self.has_event_cards,
            "event_count_estimate": self.event_count_estimate,
            "discovered_at": self.discovered_at,
            "last_probed_at": self.last_probed_at,
            "is_valid": self.is_valid,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "NeighborhoodSource":
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


@dataclass
class DiscoveryResult:
    """Result of discovering sources for a neighborhood."""
    neighborhood: str
    market_id: str
    sources_found: int
    sources_validated: int
    source_keys: List[str]
    queries_used: List[str]
    duration_seconds: float
    errors: List[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# LLM query generator
# ─────────────────────────────────────────────────────────────────────────────

async def _generate_search_queries(
    neighborhood: str,
    city: str,
    lat: float,
    lng: float,
    market_type: str = "city",
) -> List[str]:
    """
    Use Claude to generate targeted search queries for this specific neighborhood.

    This is the key advantage over MarketScraperBuilder's template approach —
    the LLM knows that "Wynwood" has a BID with an arts calendar, that
    "Coral Gables" has a city cultural affairs office, that "Buckhead" has a
    business improvement district with an events page.

    Falls back to generic queries if the API call fails.
    """
    if not ANTHROPIC_API_KEY:
        return _fallback_queries(neighborhood, city)

    prompt = f"""You are helping find hyper-local event calendar websites for the {neighborhood} neighborhood in {city}.

Generate 5 highly targeted Google search queries that would find:
1. The official neighborhood BID (Business Improvement District) events calendar
2. Local arts district or cultural center event listings
3. City government or community organization event pages specific to {neighborhood}
4. Neighborhood-specific event aggregators or community boards
5. Local venue or restaurant association event pages for {neighborhood}

Neighborhood: {neighborhood}
City: {city}
Market type: {market_type}

Return ONLY a JSON array of 5 search query strings. No explanation, no markdown, just the JSON array.
Example format: ["query 1", "query 2", "query 3", "query 4", "query 5"]

Make queries specific and targeted. Include the neighborhood name, city, and terms like "events calendar", "BID", "arts district", "community events". Avoid generic tourism board queries."""

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 300,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            resp.raise_for_status()
            data = resp.json()
            text = data["content"][0]["text"].strip()
            # Strip any markdown fences
            text = text.replace("```json", "").replace("```", "").strip()
            queries = json.loads(text)
            if isinstance(queries, list) and len(queries) > 0:
                logger.info(
                    "[NeighborhoodIntel] LLM generated %d queries for %s, %s",
                    len(queries), neighborhood, city,
                )
                return queries[:5]
    except Exception as e:
        logger.warning("[NeighborhoodIntel] LLM query generation failed: %s", e)

    return _fallback_queries(neighborhood, city)


def _fallback_queries(neighborhood: str, city: str) -> List[str]:
    """Generic fallback queries when LLM is unavailable."""
    slug = neighborhood.lower().replace(" ", "+")
    city_slug = city.lower().replace(" ", "+")
    return [
        f"{slug}+{city_slug}+events+calendar",
        f"{slug}+{city_slug}+BID+events",
        f"{slug}+arts+district+events+{city_slug}",
        f"{slug}+community+events+{city_slug}",
        f"things+to+do+{slug}+{city_slug}+this+weekend",
    ]


# ─────────────────────────────────────────────────────────────────────────────
# DuckDuckGo search (no API key, free, rate-limited)
# ─────────────────────────────────────────────────────────────────────────────

async def _ddg_search(
    query: str,
    client: httpx.AsyncClient,
    max_results: int = 5,
) -> List[Dict[str, str]]:
    """
    Search DuckDuckGo Instant Answer API and return candidate URLs.
    Returns list of {url, domain, title} dicts.
    """
    results = []
    try:
        await asyncio.sleep(random.uniform(1.0, 2.0))  # polite rate limiting
        resp = await client.get(
            "https://api.duckduckgo.com/",
            params={
                "q": query,
                "format": "json",
                "no_redirect": "1",
                "no_html": "1",
            },
            headers={"User-Agent": "Oyvoda/1.0 (neighborhood-intel)"},
            timeout=10,
        )
        if resp.status_code != 200:
            return results
        data = resp.json()

        # AbstractURL — primary result
        abstract_url = data.get("AbstractURL", "").strip()
        if abstract_url and _is_candidate_url(abstract_url):
            domain = urlparse(abstract_url).netloc.lstrip("www.")
            results.append({
                "url": abstract_url,
                "domain": domain,
                "title": data.get("AbstractSource", domain),
            })

        # RelatedTopics — secondary results
        for topic in data.get("RelatedTopics", [])[:max_results]:
            url = topic.get("FirstURL", "")
            if not url or not _is_candidate_url(url):
                continue
            domain = urlparse(url).netloc.lstrip("www.")
            if not any(r["domain"] == domain for r in results):
                results.append({
                    "url": url,
                    "domain": domain,
                    "title": topic.get("Text", domain)[:80],
                })
            if len(results) >= max_results:
                break

    except Exception as e:
        logger.debug("[NeighborhoodIntel] DDG search failed: %s", e)

    return results


def _is_candidate_url(url: str) -> bool:
    """Filter out known non-event-calendar domains."""
    url_lower = url.lower()
    # Must look like it could contain events
    has_event_signal = any(kw in url_lower for kw in [
        "/event", "/calendar", "/festival", "/things-to-do",
        "events", "calendar", "whatson", "happening",
    ])
    # Exclude known irrelevant domains
    bad_domains = [
        "facebook.com", "instagram.com", "twitter.com", "x.com",
        "youtube.com", "tripadvisor.com", "yelp.com", "airbnb.com",
        "vrbo.com", "google.com", "wikipedia.org", "reddit.com",
        "linkedin.com", "tiktok.com", "pinterest.com",
    ]
    is_bad = any(b in url_lower for b in bad_domains)
    return not is_bad  # Accept any non-bad URL (probe will filter low quality)


# ─────────────────────────────────────────────────────────────────────────────
# Source prober — validates a URL contains actual event data
# ─────────────────────────────────────────────────────────────────────────────

EVENT_CARD_SELECTORS = [
    ".event-card", ".event-item", ".tribe-event",
    "article.event", "[data-type='event']",
    ".views-row", ".event-listing", ".calendar-item",
    "[class*='event']", "[id*='event']",
    ".fc-event",            # FullCalendar
    ".tribe_events_cat",    # The Events Calendar (WordPress)
    ".eventlist-event",     # Squarespace events
    ".sqs-events-collection-item",
]


async def _probe_url(
    url: str,
    client: httpx.AsyncClient,
) -> Dict[str, Any]:
    """
    Fetch a URL and score it for event calendar content.
    Returns {confidence, has_jsonld, has_cards, event_count, error}.
    """
    result = {
        "confidence": 0.0,
        "has_jsonld": False,
        "has_cards": False,
        "event_count": 0,
        "error": None,
    }
    try:
        await asyncio.sleep(random.uniform(1.5, 3.0))
        resp = await client.get(
            url,
            headers={"User-Agent": random.choice(_UA)},
            timeout=15,
            follow_redirects=True,
        )
        if resp.status_code != 200:
            result["error"] = f"HTTP {resp.status_code}"
            return result

        soup = BeautifulSoup(resp.text, "lxml")
        score = 0.3  # base for a live page

        # JSON-LD event schema check
        jsonld_count = 0
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "{}")
                items = data if isinstance(data, list) else [data]
                for item in items:
                    t = item.get("@type", "")
                    if t in ("Event", "Festival", "MusicEvent", "SportsEvent",
                             "FoodEvent", "ExhibitionEvent", "SocialEvent"):
                        jsonld_count += 1
            except Exception:
                pass

        if jsonld_count > 0:
            result["has_jsonld"] = True
            score += 0.50
            score += min(0.20, jsonld_count * 0.02)
            result["event_count"] = jsonld_count

        # HTML event card check
        card_count = 0
        for selector in EVENT_CARD_SELECTORS:
            cards = soup.select(selector)
            if cards:
                card_count = len(cards)
                break

        if card_count > 0:
            result["has_cards"] = True
            score += 0.30
            score += min(0.15, card_count * 0.01)
            if result["event_count"] == 0:
                result["event_count"] = card_count

        # Keyword density check for pages that use inline text
        text_lower = soup.get_text().lower()
        event_keywords = ["event", "festival", "concert", "exhibition", "market",
                          "opening", "workshop", "live music", "art walk"]
        keyword_hits = sum(1 for kw in event_keywords if kw in text_lower)
        if keyword_hits >= 4:
            score += 0.15

        result["confidence"] = min(1.0, score)

    except Exception as e:
        result["error"] = str(e)[:120]
        logger.debug("[NeighborhoodIntel] probe failed %s: %s", url, e)

    return result


# ─────────────────────────────────────────────────────────────────────────────
# In-memory source cache (backed by DB on persist)
# ─────────────────────────────────────────────────────────────────────────────

class NeighborhoodSourceCache:
    """
    In-memory cache of discovered neighborhood sources, backed by the
    market_sources DB table (or a JSON fallback if DB unavailable).

    Keyed by source_key for O(1) dedup checks.
    """

    def __init__(self):
        self._sources: Dict[str, NeighborhoodSource] = {}  # source_key → source
        self._by_market: Dict[str, List[str]] = {}         # market_id → [source_keys]
        self._by_neighborhood: Dict[str, List[str]] = {}   # "{market_id}_{slug}" → [source_keys]

    def add(self, source: NeighborhoodSource) -> None:
        self._sources[source.source_key] = source
        self._by_market.setdefault(source.market_id, [])
        if source.source_key not in self._by_market[source.market_id]:
            self._by_market[source.market_id].append(source.source_key)
        nk = f"{source.market_id}_{source.neighborhood_slug}"
        self._by_neighborhood.setdefault(nk, [])
        if source.source_key not in self._by_neighborhood[nk]:
            self._by_neighborhood[nk].append(source.source_key)

    def get(self, source_key: str) -> Optional[NeighborhoodSource]:
        return self._sources.get(source_key)

    def get_for_market(self, market_id: str) -> List[NeighborhoodSource]:
        keys = self._by_market.get(market_id, [])
        return [self._sources[k] for k in keys if k in self._sources]

    def get_for_neighborhood(
        self, market_id: str, neighborhood_slug: str
    ) -> List[NeighborhoodSource]:
        nk = f"{market_id}_{neighborhood_slug}"
        keys = self._by_neighborhood.get(nk, [])
        return [self._sources[k] for k in keys if k in self._sources]

    def has_fresh_sources(self, market_id: str, neighborhood_slug: str) -> bool:
        sources = self.get_for_neighborhood(market_id, neighborhood_slug)
        valid = [s for s in sources if s.is_valid and not s.is_stale]
        return len(valid) > 0

    def invalidate(self, source_key: str) -> bool:
        src = self._sources.get(source_key)
        if src:
            src.is_valid = False
            return True
        return False

    async def persist(self, db_session) -> None:
        """Write all sources to the DB neighborhood_sources table."""
        if not db_session:
            return
        try:
            from sqlalchemy import text
            for source in self._sources.values():
                await db_session.execute(
                    text("""
                        INSERT INTO neighborhood_sources
                            (source_key, neighborhood, neighborhood_slug, market_id,
                             url, domain, label, confidence, has_jsonld, has_event_cards,
                             event_count_estimate, discovered_at, last_probed_at, is_valid, metadata)
                        VALUES
                            (:source_key, :neighborhood, :slug, :market_id,
                             :url, :domain, :label, :confidence, :has_jsonld, :has_cards,
                             :event_count, :discovered_at, :last_probed_at, :is_valid, :metadata)
                        ON CONFLICT (source_key) DO UPDATE SET
                            confidence       = EXCLUDED.confidence,
                            has_jsonld       = EXCLUDED.has_jsonld,
                            has_event_cards  = EXCLUDED.has_event_cards,
                            event_count_estimate = EXCLUDED.event_count_estimate,
                            last_probed_at   = EXCLUDED.last_probed_at,
                            is_valid         = EXCLUDED.is_valid
                    """),
                    {
                        "source_key":     source.source_key,
                        "neighborhood":   source.neighborhood,
                        "slug":           source.neighborhood_slug,
                        "market_id":      source.market_id,
                        "url":            source.url,
                        "domain":         source.domain,
                        "label":          source.label,
                        "confidence":     source.confidence,
                        "has_jsonld":     source.has_jsonld,
                        "has_cards":      source.has_event_cards,
                        "event_count":    source.event_count_estimate,
                        "discovered_at":  source.discovered_at,
                        "last_probed_at": source.last_probed_at,
                        "is_valid":       source.is_valid,
                        "metadata":       json.dumps(source.to_dict()),
                    },
                )
            await db_session.commit()
        except Exception as e:
            logger.warning("[NeighborhoodIntel] DB persist failed (non-fatal): %s", e)

    async def load_from_db(self, db_session) -> int:
        """Load all sources from DB into memory cache."""
        if not db_session:
            return 0
        loaded = 0
        try:
            from sqlalchemy import text
            result = await db_session.execute(
                text("SELECT metadata FROM neighborhood_sources WHERE is_valid = TRUE")
            )
            for row in result.fetchall():
                try:
                    data = json.loads(row[0])
                    src = NeighborhoodSource.from_dict(data)
                    self.add(src)
                    loaded += 1
                except Exception:
                    pass
        except Exception as e:
            logger.debug("[NeighborhoodIntel] DB load failed (non-fatal): %s", e)
        return loaded


# Module-level cache singleton
_source_cache = NeighborhoodSourceCache()


def get_source_cache() -> NeighborhoodSourceCache:
    return _source_cache


# ─────────────────────────────────────────────────────────────────────────────
# Deduplication helpers for knowledge_embeddings
# ─────────────────────────────────────────────────────────────────────────────

def make_source_dedup_key(
    source_type: str,
    identifier: str,
    operator_id: str,
) -> str:
    """
    Build a stable dedup key for cross-source deduplication.

    source_type: "google_places" | "eventbrite" | "neighborhood_scrape"
    identifier:  google_place_id | eventbrite_event_id | url_hash
    operator_id: tenant scope

    This key is stored in knowledge_embeddings.metadata->>'source_dedup_key'.
    Before indexing, we check if a document with this key already exists for
    this operator — if yes, we upsert to update it rather than creating a
    duplicate.
    """
    raw = f"{source_type}|{identifier}|{operator_id}"
    return hashlib.md5(raw.encode()).hexdigest()[:20]


async def dedup_check(
    db_session,
    source_dedup_key: str,
    operator_id: str,
) -> Optional[str]:
    """
    Check if a document with this dedup key already exists.
    Returns existing doc_id if found, None otherwise.
    """
    try:
        from sqlalchemy import text
        result = await db_session.execute(
            text("""
                SELECT doc_id FROM knowledge_embeddings
                WHERE operator_id = :op
                  AND metadata->>'source_dedup_key' = :key
                LIMIT 1
            """),
            {"op": operator_id, "key": source_dedup_key},
        )
        row = result.fetchone()
        return row[0] if row else None
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Main MCP server
# ─────────────────────────────────────────────────────────────────────────────

class NeighborhoodIntelligenceMCPServer(MCPServer):
    """
    Discovers hyper-local event sources for specific neighborhoods using
    LLM-generated search queries + URL probing.

    This fills the gap between:
    - Google Places (business directory, no events)
    - Eventbrite (ticketed events only)
    - MarketScraperBuilder (city-level tourism boards)

    And surfaces neighborhood-specific event calendars from BIDs, arts
    districts, community organizations, and local venue associations.
    """

    server_name = "neighborhood_intel"
    server_description = "Hyper-local neighborhood event source discovery and caching"

    def __init__(self) -> None:
        super().__init__()
        self._db_session = None
        self._cache = get_source_cache()

    def set_db_session(self, db_session) -> None:
        self._db_session = db_session

    def get_tools(self) -> List[MCPTool]:
        return [
            MCPTool(
                name="discover_neighborhood_sources",
                description=(
                    "Use LLM-powered search to find hyper-local event calendars for a "
                    "specific neighborhood (BIDs, arts districts, community orgs). "
                    "Results are cached permanently — call once per neighborhood."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "neighborhood":      {"type": "string", "description": "e.g. 'Wynwood'"},
                        "city":              {"type": "string", "description": "e.g. 'Miami'"},
                        "market_id":         {"type": "string", "description": "e.g. 'MARKET_MIAMI'"},
                        "lat":               {"type": "number"},
                        "lng":               {"type": "number"},
                        "market_type":       {"type": "string", "default": "city"},
                        "force_rediscover":  {"type": "boolean", "default": False},
                    },
                    "required": ["neighborhood", "city", "market_id", "lat", "lng"],
                },
                returns="DiscoveryResult with sources_found, sources_validated, source_keys",
                category="knowledge",
            ),
            MCPTool(
                name="get_neighborhood_events",
                description=(
                    "Scrape current events from all cached sources for a neighborhood. "
                    "Returns events indexed into the vector store with TTL metadata."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "neighborhood_slug": {"type": "string", "description": "e.g. 'wynwood'"},
                        "market_id":         {"type": "string"},
                        "operator_id":       {"type": "string"},
                        "days_ahead":        {"type": "integer", "default": 60},
                    },
                    "required": ["neighborhood_slug", "market_id", "operator_id"],
                },
                returns="Dict with events_found, events_indexed counts",
                category="knowledge",
            ),
            MCPTool(
                name="get_cached_sources",
                description="List all discovered neighborhood sources for a market",
                parameters={
                    "type": "object",
                    "properties": {
                        "market_id": {"type": "string"},
                    },
                    "required": ["market_id"],
                },
                returns="List of source dicts with url, label, confidence, neighborhood",
                category="knowledge",
            ),
            MCPTool(
                name="invalidate_source",
                description="Mark a source as stale so it gets re-discovered on next run",
                parameters={
                    "type": "object",
                    "properties": {
                        "source_key": {"type": "string"},
                    },
                    "required": ["source_key"],
                },
                returns="Boolean success",
                category="knowledge",
            ),
        ]

    async def call(
        self,
        tool_name: str,
        operator_id: str,
        params: Dict[str, Any],
    ) -> MCPResult:
        if tool_name == "discover_neighborhood_sources":
            return await self._discover_sources(operator_id, params)
        elif tool_name == "get_neighborhood_events":
            return await self._get_neighborhood_events(operator_id, params)
        elif tool_name == "get_cached_sources":
            return await self._get_cached_sources(operator_id, params)
        elif tool_name == "invalidate_source":
            return await self._invalidate_source(operator_id, params)
        return MCPResult(success=False, message=f"Unknown tool: {tool_name}")

    # ── Tool implementations ──────────────────────────────────────────────────

    async def _discover_sources(
        self,
        operator_id: str,
        params: Dict[str, Any],
    ) -> MCPResult:
        neighborhood    = params["neighborhood"]
        city            = params["city"]
        market_id       = params["market_id"]
        lat             = float(params["lat"])
        lng             = float(params["lng"])
        market_type     = params.get("market_type", "city")
        force           = params.get("force_rediscover", False)

        neighborhood_slug = neighborhood.lower().replace(" ", "_").replace("-", "_")

        # Skip if fresh sources already exist
        if not force and self._cache.has_fresh_sources(market_id, neighborhood_slug):
            existing = self._cache.get_for_neighborhood(market_id, neighborhood_slug)
            return MCPResult(
                success=True,
                data={
                    "neighborhood": neighborhood,
                    "market_id": market_id,
                    "sources_found": len(existing),
                    "sources_validated": len([s for s in existing if s.confidence >= MIN_CONFIDENCE]),
                    "source_keys": [s.source_key for s in existing],
                    "cached": True,
                },
                message=f"Using {len(existing)} cached sources for {neighborhood}",
            )

        start = datetime.utcnow()
        errors: List[str] = []
        all_candidates: List[Dict[str, str]] = []
        queries_used: List[str] = []

        # ── Step 1: LLM generates targeted queries ────────────────────────
        queries = await _generate_search_queries(neighborhood, city, lat, lng, market_type)
        queries_used = queries

        # ── Step 2: DuckDuckGo search for each query ──────────────────────
        async with httpx.AsyncClient(follow_redirects=True, timeout=20) as client:
            seen_domains: set = set()
            for query in queries:
                try:
                    results = await _ddg_search(query, client)
                    for r in results:
                        if r["domain"] not in seen_domains:
                            all_candidates.append(r)
                            seen_domains.add(r["domain"])
                except Exception as e:
                    errors.append(f"DDG search failed: {e}")

            # ── Step 3: Probe each candidate ──────────────────────────────
            validated: List[NeighborhoodSource] = []
            sem = asyncio.Semaphore(3)

            async def _probe_one(candidate: Dict) -> Optional[NeighborhoodSource]:
                async with sem:
                    probe = await _probe_url(candidate["url"], client)
                    if probe["confidence"] < MIN_CONFIDENCE:
                        return None

                    source_key = _make_source_key(
                        market_id, neighborhood_slug, candidate["domain"]
                    )
                    now_iso = datetime.utcnow().isoformat()
                    return NeighborhoodSource(
                        source_key=source_key,
                        neighborhood=neighborhood,
                        neighborhood_slug=neighborhood_slug,
                        market_id=market_id,
                        url=candidate["url"],
                        domain=candidate["domain"],
                        label=candidate.get("title", candidate["domain"]),
                        confidence=probe["confidence"],
                        has_jsonld=probe["has_jsonld"],
                        has_event_cards=probe["has_cards"],
                        event_count_estimate=probe["event_count"],
                        discovered_at=now_iso,
                        last_probed_at=now_iso,
                        is_valid=True,
                    )

            probe_results = await asyncio.gather(
                *[_probe_one(c) for c in all_candidates],
                return_exceptions=True,
            )

            for r in probe_results:
                if isinstance(r, NeighborhoodSource):
                    validated.append(r)
                    self._cache.add(r)
                    # Register with MarketScraperBuilder runtime sources
                    try:
                        from tools.market_scraper_builder import _register_runtime_sources
                        from tools.market_scraper_builder import MarketSourceConfig
                        cfg = MarketSourceConfig(
                            market_id=market_id,
                            market_name=f"{neighborhood}, {city}",
                        )
                        cfg.tourism_sources[r.source_key] = {
                            "url": r.url, "domain": r.domain,
                            "label": r.label, "enabled": True,
                            "confidence": r.confidence,
                        }
                        cfg.validated_keys = [r.source_key]
                        _register_runtime_sources(cfg)
                    except Exception:
                        pass

        # ── Step 4: Persist to DB ─────────────────────────────────────────
        await self._cache.persist(self._db_session)

        duration = (datetime.utcnow() - start).total_seconds()
        logger.info(
            "[NeighborhoodIntel] %s/%s: %d candidates, %d validated, %.1fs",
            market_id, neighborhood, len(all_candidates), len(validated), duration,
        )

        return MCPResult(
            success=True,
            data={
                "neighborhood": neighborhood,
                "market_id": market_id,
                "sources_found": len(all_candidates),
                "sources_validated": len(validated),
                "source_keys": [s.source_key for s in validated],
                "queries_used": queries_used,
                "duration_seconds": duration,
                "errors": errors,
                "cached": False,
            },
            message=(
                f"Discovered {len(validated)} event sources for {neighborhood} "
                f"({len(all_candidates)} candidates probed)"
            ),
        )

    async def _get_neighborhood_events(
        self,
        operator_id: str,
        params: Dict[str, Any],
    ) -> MCPResult:
        """
        Scrape current events from all cached sources for a neighborhood and
        index them into the vector store with TTL and deduplication.
        """
        neighborhood_slug = params["neighborhood_slug"]
        market_id         = params["market_id"]
        days_ahead        = params.get("days_ahead", 60)

        sources = self._cache.get_for_neighborhood(market_id, neighborhood_slug)
        valid_sources = [s for s in sources if s.is_valid and not s.is_stale]

        if not valid_sources:
            return MCPResult(
                success=True,
                data={"events_found": 0, "events_indexed": 0, "sources_checked": 0},
                message=f"No cached sources for {neighborhood_slug} — run discover first",
            )

        events_found = 0
        events_indexed = 0
        errors: List[str] = []

        async with httpx.AsyncClient(follow_redirects=True, timeout=20) as client:
            for source in valid_sources:
                try:
                    raw_events = await _scrape_events_from_source(
                        source, client, days_ahead
                    )
                    events_found += len(raw_events)

                    if self._db_session and raw_events:
                        indexed = await _index_neighborhood_events(
                            raw_events, source, operator_id, self._db_session
                        )
                        events_indexed += indexed

                except Exception as e:
                    errors.append(f"{source.domain}: {e}")
                    logger.warning("[NeighborhoodIntel] scrape error %s: %s", source.domain, e)

        return MCPResult(
            success=True,
            data={
                "events_found": events_found,
                "events_indexed": events_indexed,
                "sources_checked": len(valid_sources),
                "errors": errors,
            },
            message=f"Indexed {events_indexed} events from {len(valid_sources)} sources for {neighborhood_slug}",
        )

    async def _get_cached_sources(
        self,
        operator_id: str,
        params: Dict[str, Any],
    ) -> MCPResult:
        market_id = params["market_id"]

        # Try loading from DB if cache is empty
        if not self._cache.get_for_market(market_id) and self._db_session:
            await self._cache.load_from_db(self._db_session)

        sources = self._cache.get_for_market(market_id)
        return MCPResult(
            success=True,
            data={
                "market_id": market_id,
                "sources": [s.to_dict() for s in sources],
                "count": len(sources),
            },
            message=f"Found {len(sources)} cached sources for {market_id}",
        )

    async def _invalidate_source(
        self,
        operator_id: str,
        params: Dict[str, Any],
    ) -> MCPResult:
        source_key = params["source_key"]
        ok = self._cache.invalidate(source_key)
        if ok and self._db_session:
            await self._cache.persist(self._db_session)
        return MCPResult(
            success=ok,
            data={"source_key": source_key, "invalidated": ok},
            message=f"Source {'invalidated' if ok else 'not found'}: {source_key}",
        )


# ─────────────────────────────────────────────────────────────────────────────
# Event scraping from a validated source URL
# ─────────────────────────────────────────────────────────────────────────────

async def _scrape_events_from_source(
    source: NeighborhoodSource,
    client: httpx.AsyncClient,
    days_ahead: int,
) -> List[Dict[str, Any]]:
    """
    Scrape events from a validated neighborhood source URL.
    Returns raw event dicts ready for indexing.
    """
    events = []
    try:
        await asyncio.sleep(random.uniform(1.0, 2.0))
        resp = await client.get(
            source.url,
            headers={"User-Agent": random.choice(_UA)},
            timeout=15,
        )
        if resp.status_code != 200:
            return events

        soup = BeautifulSoup(resp.text, "lxml")

        # Strategy 1: JSON-LD structured events
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "{}")
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") in (
                        "Event", "Festival", "MusicEvent", "SportsEvent",
                        "FoodEvent", "ExhibitionEvent", "SocialEvent"
                    ):
                        ev = _parse_jsonld_event(item, source)
                        if ev:
                            events.append(ev)
            except Exception:
                pass

        # Strategy 2: HTML event cards
        if not events:
            for selector in EVENT_CARD_SELECTORS:
                cards = soup.select(selector)
                if cards:
                    for card in cards[:20]:
                        ev = _parse_html_card(card, source)
                        if ev:
                            events.append(ev)
                    break

    except Exception as e:
        logger.debug("[NeighborhoodIntel] scrape error %s: %s", source.url, e)

    return events


def _parse_jsonld_event(item: Dict, source: NeighborhoodSource) -> Optional[Dict]:
    name = item.get("name", "")
    if not name:
        return None
    start_str = (item.get("startDate") or "")[:10]
    end_str = (item.get("endDate") or start_str)[:10]
    location = item.get("location") or {}
    venue = location.get("name", "") if isinstance(location, dict) else str(location)
    description = item.get("description", "")[:300]
    url = item.get("url", source.url)

    return {
        "name": name,
        "description": description,
        "start_date": start_str,
        "end_date": end_str,
        "venue": venue or source.neighborhood,
        "url": url,
        "source": source.source_key,
        "neighborhood": source.neighborhood,
        "market_id": source.market_id,
        "source_type": "jsonld",
        "source_url": source.url,
    }


def _parse_html_card(card, source: NeighborhoodSource) -> Optional[Dict]:
    name_el = card.select_one("h2, h3, h4, .event-title, .title, strong")
    if not name_el:
        return None
    name = name_el.get_text(strip=True)
    if not name or len(name) < 3:
        return None

    desc_el = card.select_one("p, .description, .excerpt, .summary")
    description = desc_el.get_text(strip=True)[:200] if desc_el else ""

    link_el = card.select_one("a[href]")
    url = link_el["href"] if link_el else source.url
    if url.startswith("/"):
        url = f"https://{source.domain}{url}"

    return {
        "name": name,
        "description": description,
        "start_date": "",  # unknown without structured data
        "end_date": "",
        "venue": source.neighborhood,
        "url": url,
        "source": source.source_key,
        "neighborhood": source.neighborhood,
        "market_id": source.market_id,
        "source_type": "html_card",
        "source_url": source.url,
    }


async def _index_neighborhood_events(
    events: List[Dict],
    source: NeighborhoodSource,
    operator_id: str,
    db_session,
) -> int:
    """
    Index neighborhood events into knowledge_embeddings with dedup and TTL.

    Deduplication: before inserting, check if a document with the same
    source_dedup_key already exists. If yes, upsert to update content.
    If no, insert fresh. This prevents the same event appearing twice from
    two different scrape runs, while still updating stale content.
    """
    try:
        from app.services.knowledge.vector_store import Document, VectorStore

        store = VectorStore(db_session)
        documents = []
        today_str = __import__("datetime").date.today().isoformat()

        for ev in events:
            # Build the searchable content string
            parts = [f"Event: {ev['name']}"]
            if ev.get("neighborhood"):
                parts.append(f"in {ev['neighborhood']}")
            if ev.get("start_date"):
                parts.append(f"on {ev['start_date']}")
            if ev.get("description"):
                parts.append(ev["description"])
            if ev.get("venue"):
                parts.append(f"Venue: {ev['venue']}.")
            content = " ".join(parts)

            # Dedup key — stable across scrape runs for the same event
            url_hash = hashlib.md5(ev.get("url", ev["name"]).encode()).hexdigest()[:12]
            dedup_key = make_source_dedup_key(
                "neighborhood_scrape",
                f"{source.source_key}_{url_hash}",
                operator_id,
            )

            # Check for existing document with this dedup key
            existing_doc_id = await dedup_check(db_session, dedup_key, operator_id)

            # TTL: events with known end dates expire naturally
            expires_at = ev.get("end_date") or ""

            metadata = {
                "operator_id":      operator_id,
                "doc_type":         "neighborhood_event",
                "event_name":       ev["name"],
                "market_id":        ev["market_id"],
                "neighborhood":     ev["neighborhood"],
                "start_date":       ev.get("start_date", ""),
                "end_date":         expires_at,
                "venue":            ev.get("venue", ""),
                "source":           source.source_key,
                "source_url":       source.url,
                "source_label":     source.label,
                "source_dedup_key": dedup_key,
                "expires_at":       expires_at or "",
                "scraped_at":       today_str,
            }

            doc = Document(
                content=content,
                metadata=metadata,
                # Force same doc_id if we found an existing match, so it upserts
                doc_id=existing_doc_id if existing_doc_id else None,
            )
            documents.append(doc)

        if not documents:
            return 0

        result = await store.add_documents(documents)
        return result.get("inserted", 0) + result.get("updated", 0)

    except Exception as e:
        logger.warning("[NeighborhoodIntel] index error: %s", e)
        return 0


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_source_key(market_id: str, neighborhood_slug: str, domain: str) -> str:
    """Deterministic source key from market + neighborhood + domain."""
    domain_slug = domain.replace(".", "_").replace("-", "_")
    return f"{market_id}_{neighborhood_slug}_{domain_slug}"


# ─────────────────────────────────────────────────────────────────────────────
# DB migration helper — creates the neighborhood_sources table if missing
# ─────────────────────────────────────────────────────────────────────────────

MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS neighborhood_sources (
    id               BIGSERIAL PRIMARY KEY,
    source_key       TEXT UNIQUE NOT NULL,
    neighborhood     TEXT NOT NULL,
    neighborhood_slug TEXT NOT NULL,
    market_id        TEXT NOT NULL,
    url              TEXT NOT NULL,
    domain           TEXT NOT NULL,
    label            TEXT,
    confidence       FLOAT DEFAULT 0.0,
    has_jsonld       BOOLEAN DEFAULT FALSE,
    has_event_cards  BOOLEAN DEFAULT FALSE,
    event_count_estimate INT DEFAULT 0,
    discovered_at    TIMESTAMPTZ DEFAULT NOW(),
    last_probed_at   TIMESTAMPTZ DEFAULT NOW(),
    is_valid         BOOLEAN DEFAULT TRUE,
    metadata         JSONB DEFAULT '{}'::jsonb,
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    updated_at       TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_neighborhood_sources_market
    ON neighborhood_sources (market_id);

CREATE INDEX IF NOT EXISTS idx_neighborhood_sources_slug
    ON neighborhood_sources (market_id, neighborhood_slug);
"""


async def ensure_neighborhood_sources_table(db_session) -> None:
    """Run migration to create neighborhood_sources table if it doesn't exist."""
    try:
        from sqlalchemy import text
        await db_session.execute(text(MIGRATION_SQL))
        await db_session.commit()
        logger.info("[NeighborhoodIntel] neighborhood_sources table ready")
    except Exception as e:
        logger.warning("[NeighborhoodIntel] migration failed (non-fatal): %s", e)
