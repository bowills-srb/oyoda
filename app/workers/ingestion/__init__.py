"""
Ingestion Workers.

Scrapers that collect market data and write to MarketEvidence.

ARCHITECTURE:
    OTA Scrapers (Airbnb / Vrbo)
            ↓
    MarketEvidence + PropertyEvidence
            ↓
    MarketContext (via builder)
            ↓
    Analytics / Concierge / BD

Scrapers do ONE job: Observe the market → write MarketEvidence
They do NOT: compute projections, decide pricing, speak to guests

AVAILABLE SCRAPERS:
- AirbnbMarketScraper: Listings, availability, pricing signals
- EventScraper: Festivals, conferences, holidays

USAGE:
    from app.workers.ingestion import scrape_market, scrape_events
    
    # Scrape Airbnb data
    evidence = await scrape_market("30a")
    
    # Scrape events
    events = await scrape_events("30a")
"""

from .airbnb_market_scraper import (
    AirbnbMarketScraper,
    ScraperConfig,
    GeoBounds,
    MARKET_BOUNDS,
    ListingSnapshot,
    AvailabilitySnapshot,
    MarketEvidence,
    get_scraper_for_market,
    scrape_market,
)

from .event_scraper import (
    EventScraper,
    RawEvent,
    KNOWN_EVENTS,
    US_HOLIDAYS_2026,
    scrape_events,
)


__all__ = [
    # Airbnb scraper
    "AirbnbMarketScraper",
    "ScraperConfig",
    "GeoBounds",
    "MARKET_BOUNDS",
    "ListingSnapshot",
    "AvailabilitySnapshot",
    "get_scraper_for_market",
    "scrape_market",
    
    # Event scraper
    "EventScraper",
    "RawEvent",
    "KNOWN_EVENTS",
    "US_HOLIDAYS_2026",
    "scrape_events",
    
    # Common
    "MarketEvidence",
]
