"""
Airbnb Market Scraper.

Collects market-level signals from Airbnb listings.
Writes to MarketEvidence - does NOT compute projections or make decisions.

WHAT THIS SCRAPES (safe + useful):
- Listing count by date
- Availability density over time
- Minimum night rules
- Calendar blocking patterns
- ADR proxies (if visible)
- Booking velocity (change in availability)
- Lead-time compression

WHAT THIS DOES NOT SCRAPE:
- Exact booking revenue
- Private guest details
- Sensitive host data

USAGE:
    scraper = AirbnbMarketScraper(market_id="30a", geo_bounds=...)
    evidence = await scraper.scrape()
    # → List[MarketEvidence] ready for persistence
"""

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

# httpx is optional - only needed for actual API calls
try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    httpx = None
    HAS_HTTPX = False

logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================

@dataclass
class GeoBounds:
    """Geographic bounding box for search."""
    ne_lat: float  # Northeast latitude
    ne_lng: float  # Northeast longitude
    sw_lat: float  # Southwest latitude
    sw_lng: float  # Southwest longitude
    
    def to_dict(self) -> Dict[str, float]:
        return {
            "ne_lat": self.ne_lat,
            "ne_lng": self.ne_lng,
            "sw_lat": self.sw_lat,
            "sw_lng": self.sw_lng,
        }


@dataclass
class ScraperConfig:
    """Configuration for market scraper."""
    market_id: str
    geo_bounds: GeoBounds
    
    # Search parameters
    check_in_offset_days: int = 7  # Start searching X days from now
    search_window_days: int = 90   # How far ahead to look
    
    # Rate limiting
    requests_per_minute: int = 10
    retry_count: int = 3
    retry_delay_seconds: int = 5
    
    # Filtering
    min_bedrooms: int = 1
    max_bedrooms: int = 10


# Pre-defined market bounds
MARKET_BOUNDS = {
    "30a": GeoBounds(
        ne_lat=30.38, ne_lng=-85.85,
        sw_lat=30.28, sw_lng=-86.45,
    ),
    "destin": GeoBounds(
        ne_lat=30.42, ne_lng=-86.35,
        sw_lat=30.35, sw_lng=-86.55,
    ),
    "panama_city_beach": GeoBounds(
        ne_lat=30.25, ne_lng=-85.70,
        sw_lat=30.15, sw_lng=-85.90,
    ),
    "gulf_shores": GeoBounds(
        ne_lat=30.30, ne_lng=-87.60,
        sw_lat=30.22, sw_lng=-87.80,
    ),
}


# =============================================================================
# MARKET EVIDENCE TYPES
# =============================================================================

@dataclass
class MarketEvidence:
    """Evidence record for persistence."""
    evidence_id: str = field(default_factory=lambda: str(uuid4()))
    market_id: str = ""
    evidence_type: str = ""  # availability_snapshot, pricing_signal, supply_count
    data: Dict[str, Any] = field(default_factory=dict)
    source: str = "airbnb_scraper"
    confidence: float = 0.7
    observed_at: datetime = field(default_factory=datetime.utcnow)
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "market_id": self.market_id,
            "evidence_type": self.evidence_type,
            "data": self.data,
            "source": self.source,
            "confidence": self.confidence,
            "observed_at": self.observed_at.isoformat(),
            "valid_from": self.valid_from.isoformat() if self.valid_from else None,
            "valid_until": self.valid_until.isoformat() if self.valid_until else None,
        }


# =============================================================================
# LISTING DATA STRUCTURES
# =============================================================================

@dataclass
class ListingSnapshot:
    """Snapshot of a single listing."""
    listing_id: str
    name: str
    bedrooms: int
    bathrooms: float
    
    # Pricing
    base_price: Optional[float] = None
    currency: str = "USD"
    
    # Availability
    available_dates: List[date] = field(default_factory=list)
    blocked_dates: List[date] = field(default_factory=list)
    min_nights: int = 1
    
    # Location
    lat: Optional[float] = None
    lng: Optional[float] = None
    
    # Metadata
    scraped_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class AvailabilitySnapshot:
    """Aggregated availability for a market."""
    market_id: str
    snapshot_date: date
    
    # Counts
    total_listings: int = 0
    available_listings: int = 0
    
    # Availability by bedroom count
    by_bedroom: Dict[int, Dict[str, int]] = field(default_factory=dict)
    
    # Date-specific availability
    availability_by_date: Dict[str, int] = field(default_factory=dict)
    
    # Pricing signals
    avg_base_price: Optional[float] = None
    median_base_price: Optional[float] = None
    price_by_bedroom: Dict[int, float] = field(default_factory=dict)
    
    # Minimum nights
    avg_min_nights: float = 1.0


# =============================================================================
# SCRAPER (MOCK IMPLEMENTATION)
# =============================================================================

class AirbnbMarketScraper:
    """
    Scrapes Airbnb market data.
    
    NOTE: This is a MOCK implementation that generates realistic data.
    Production implementation would use actual API calls or web scraping.
    
    The mock demonstrates the exact data flow and evidence format
    that real scrapers should produce.
    """
    
    def __init__(self, config: ScraperConfig):
        self.config = config
        self.client = None
    
    async def __aenter__(self):
        if HAS_HTTPX:
            self.client = httpx.AsyncClient(timeout=30.0)
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.client:
            await self.client.aclose()
    
    async def scrape(self) -> List[MarketEvidence]:
        """
        Scrape market and return evidence records.
        
        Returns:
            List of MarketEvidence ready for persistence
        """
        logger.info(f"Starting scrape for market: {self.config.market_id}")
        
        evidence = []
        
        # 1. Scrape listing inventory
        listings = await self._scrape_listings()
        
        # 2. Build availability snapshot
        snapshot = self._build_availability_snapshot(listings)
        
        # 3. Convert to evidence records
        evidence.extend(self._snapshot_to_evidence(snapshot))
        
        # 4. Extract pricing signals
        evidence.extend(self._extract_pricing_evidence(listings))
        
        # 5. Extract supply/demand signals
        evidence.extend(self._extract_supply_demand_evidence(snapshot))
        
        logger.info(f"Scrape complete: {len(evidence)} evidence records")
        return evidence
    
    async def _scrape_listings(self) -> List[ListingSnapshot]:
        """
        Scrape individual listings.
        
        MOCK: Returns simulated data.
        PRODUCTION: Would call Airbnb search API or scrape search results.
        """
        # In production, this would be actual API calls
        # For now, generate realistic mock data
        
        listings = []
        
        # Simulate 50-200 listings per market
        import random
        num_listings = random.randint(50, 200)
        
        for i in range(num_listings):
            listing = self._generate_mock_listing(i)
            listings.append(listing)
            
            # Simulate rate limiting
            if i % 10 == 0:
                await asyncio.sleep(0.1)
        
        return listings
    
    def _generate_mock_listing(self, index: int) -> ListingSnapshot:
        """Generate a realistic mock listing."""
        import random
        
        # Bedroom distribution (realistic for vacation markets)
        bedroom_weights = {1: 0.1, 2: 0.2, 3: 0.3, 4: 0.25, 5: 0.1, 6: 0.05}
        bedrooms = random.choices(
            list(bedroom_weights.keys()),
            weights=list(bedroom_weights.values())
        )[0]
        
        # Base price by bedroom (realistic for 30A/coastal markets)
        base_prices = {1: 150, 2: 200, 3: 300, 4: 400, 5: 550, 6: 700}
        base_price = base_prices.get(bedrooms, 300) * random.uniform(0.8, 1.4)
        
        # Availability (simulate booking patterns)
        today = date.today()
        available_dates = []
        blocked_dates = []
        
        for day_offset in range(90):
            check_date = today + timedelta(days=day_offset)
            
            # Weekends more likely to be booked
            is_weekend = check_date.weekday() >= 4
            book_probability = 0.6 if is_weekend else 0.4
            
            # Peak season more likely to be booked
            if check_date.month in [6, 7, 8]:
                book_probability += 0.2
            
            if random.random() > book_probability:
                available_dates.append(check_date)
            else:
                blocked_dates.append(check_date)
        
        # Min nights (vacation markets typically 3-7)
        min_nights = random.choices([2, 3, 4, 5, 7], weights=[0.1, 0.3, 0.3, 0.2, 0.1])[0]
        
        return ListingSnapshot(
            listing_id=f"mock-{self.config.market_id}-{index}",
            name=f"Beach House #{index}",
            bedrooms=bedrooms,
            bathrooms=bedrooms + random.choice([0, 0.5, 1]),
            base_price=round(base_price, 0),
            available_dates=available_dates,
            blocked_dates=blocked_dates,
            min_nights=min_nights,
            lat=self.config.geo_bounds.sw_lat + random.random() * (self.config.geo_bounds.ne_lat - self.config.geo_bounds.sw_lat),
            lng=self.config.geo_bounds.sw_lng + random.random() * (self.config.geo_bounds.ne_lng - self.config.geo_bounds.sw_lng),
        )
    
    def _build_availability_snapshot(
        self, 
        listings: List[ListingSnapshot]
    ) -> AvailabilitySnapshot:
        """Build aggregated availability snapshot from listings."""
        today = date.today()
        
        snapshot = AvailabilitySnapshot(
            market_id=self.config.market_id,
            snapshot_date=today,
            total_listings=len(listings),
        )
        
        # Count available listings (available in next 30 days)
        next_30_days = {today + timedelta(days=i) for i in range(30)}
        available_count = 0
        
        for listing in listings:
            if any(d in next_30_days for d in listing.available_dates):
                available_count += 1
        
        snapshot.available_listings = available_count
        
        # Group by bedroom count
        by_bedroom: Dict[int, Dict[str, int]] = {}
        for listing in listings:
            br = listing.bedrooms
            if br not in by_bedroom:
                by_bedroom[br] = {"total": 0, "available": 0}
            by_bedroom[br]["total"] += 1
            if any(d in next_30_days for d in listing.available_dates):
                by_bedroom[br]["available"] += 1
        
        snapshot.by_bedroom = by_bedroom
        
        # Availability by date (next 90 days)
        availability_by_date: Dict[str, int] = {}
        for day_offset in range(90):
            check_date = today + timedelta(days=day_offset)
            date_str = check_date.isoformat()
            count = sum(
                1 for listing in listings 
                if check_date in listing.available_dates
            )
            availability_by_date[date_str] = count
        
        snapshot.availability_by_date = availability_by_date
        
        # Pricing
        prices = [l.base_price for l in listings if l.base_price]
        if prices:
            snapshot.avg_base_price = sum(prices) / len(prices)
            sorted_prices = sorted(prices)
            snapshot.median_base_price = sorted_prices[len(sorted_prices) // 2]
        
        # Price by bedroom
        price_by_br: Dict[int, List[float]] = {}
        for listing in listings:
            if listing.base_price:
                br = listing.bedrooms
                if br not in price_by_br:
                    price_by_br[br] = []
                price_by_br[br].append(listing.base_price)
        
        snapshot.price_by_bedroom = {
            br: sum(prices) / len(prices) 
            for br, prices in price_by_br.items()
        }
        
        # Min nights
        min_nights_values = [l.min_nights for l in listings]
        snapshot.avg_min_nights = sum(min_nights_values) / len(min_nights_values) if min_nights_values else 1.0
        
        return snapshot
    
    def _snapshot_to_evidence(
        self, 
        snapshot: AvailabilitySnapshot
    ) -> List[MarketEvidence]:
        """Convert availability snapshot to evidence records."""
        evidence = []
        
        # Main availability evidence
        evidence.append(MarketEvidence(
            market_id=self.config.market_id,
            evidence_type="availability_snapshot",
            data={
                "total_listings": snapshot.total_listings,
                "available_listings": snapshot.available_listings,
                "availability_rate": snapshot.available_listings / snapshot.total_listings if snapshot.total_listings > 0 else 0,
                "by_bedroom": snapshot.by_bedroom,
                "avg_min_nights": snapshot.avg_min_nights,
            },
            confidence=0.8,
            valid_from=datetime.utcnow(),
            valid_until=datetime.utcnow() + timedelta(hours=24),
        ))
        
        # Daily availability evidence (for trend analysis)
        evidence.append(MarketEvidence(
            market_id=self.config.market_id,
            evidence_type="daily_availability",
            data={
                "availability_by_date": snapshot.availability_by_date,
                "total_listings": snapshot.total_listings,
            },
            confidence=0.8,
            valid_from=datetime.utcnow(),
            valid_until=datetime.utcnow() + timedelta(hours=24),
        ))
        
        return evidence
    
    def _extract_pricing_evidence(
        self, 
        listings: List[ListingSnapshot]
    ) -> List[MarketEvidence]:
        """Extract pricing signals from listings."""
        evidence = []
        
        # Aggregate pricing
        prices = [l.base_price for l in listings if l.base_price]
        if not prices:
            return evidence
        
        # Price by bedroom
        price_by_br: Dict[int, List[float]] = {}
        for listing in listings:
            if listing.base_price:
                br = listing.bedrooms
                if br not in price_by_br:
                    price_by_br[br] = []
                price_by_br[br].append(listing.base_price)
        
        avg_by_br = {
            br: round(sum(p) / len(p), 0)
            for br, p in price_by_br.items()
        }
        
        evidence.append(MarketEvidence(
            market_id=self.config.market_id,
            evidence_type="pricing_signal",
            data={
                "avg_base_price": round(sum(prices) / len(prices), 0),
                "median_base_price": round(sorted(prices)[len(prices) // 2], 0),
                "min_price": round(min(prices), 0),
                "max_price": round(max(prices), 0),
                "price_by_bedroom": avg_by_br,
                "sample_size": len(prices),
            },
            confidence=0.75,
            valid_from=datetime.utcnow(),
            valid_until=datetime.utcnow() + timedelta(days=7),
        ))
        
        return evidence
    
    def _extract_supply_demand_evidence(
        self, 
        snapshot: AvailabilitySnapshot
    ) -> List[MarketEvidence]:
        """Extract supply/demand signals."""
        evidence = []
        
        # Calculate availability rate
        avail_rate = (
            snapshot.available_listings / snapshot.total_listings 
            if snapshot.total_listings > 0 else 0.5
        )
        
        # Determine pressure level
        if avail_rate < 0.2:
            pressure = "very_tight"
        elif avail_rate < 0.35:
            pressure = "tight"
        elif avail_rate < 0.5:
            pressure = "balanced"
        elif avail_rate < 0.65:
            pressure = "loose"
        else:
            pressure = "very_loose"
        
        evidence.append(MarketEvidence(
            market_id=self.config.market_id,
            evidence_type="supply_demand",
            data={
                "availability_rate": round(avail_rate, 3),
                "pressure": pressure,
                "total_supply": snapshot.total_listings,
                "available_supply": snapshot.available_listings,
            },
            confidence=0.7,
            valid_from=datetime.utcnow(),
            valid_until=datetime.utcnow() + timedelta(hours=12),
        ))
        
        return evidence


# =============================================================================
# FACTORY FUNCTIONS
# =============================================================================

def get_scraper_for_market(market_id: str) -> AirbnbMarketScraper:
    """Get a configured scraper for a market."""
    if market_id not in MARKET_BOUNDS:
        raise ValueError(f"Unknown market: {market_id}. Known markets: {list(MARKET_BOUNDS.keys())}")
    
    config = ScraperConfig(
        market_id=market_id,
        geo_bounds=MARKET_BOUNDS[market_id],
    )
    
    return AirbnbMarketScraper(config)


async def scrape_market(market_id: str) -> List[MarketEvidence]:
    """
    Convenience function to scrape a market.
    
    Usage:
        evidence = await scrape_market("30a")
        # Persist evidence...
    """
    scraper = get_scraper_for_market(market_id)
    async with scraper:
        return await scraper.scrape()
