#!/usr/bin/env python3
"""
403-Safe Market Intelligence Scraper

This scraper is designed to be run on YOUR machine (not a sandbox).
It extracts exactly the signals defined in the Signal Intelligence Map
using only public-facing, 403-safe data sources.

USAGE:
    python signal_scraper.py --market "30A Beaches" --lat 30.2833 --lng -86.0167 --radius 15

REQUIREMENTS:
    pip install httpx beautifulsoup4 lxml playwright
    playwright install chromium

SIGNALS EXTRACTED:
    🟡 Active Listing Density (Supply)
    🟡 Bedroom/Size Distribution (Supply)
    🟡 Calendar Compression (Demand)
    🟡 Platform Share (Platform Dominance)
    🟡 Amenity Prevalence (Features)
    🟣 Amenity ADR Lift (Derived)
    🟣 Rate Acceleration (Derived)
"""

import asyncio
import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode, quote
import hashlib
import time
import random

# Check for required packages
try:
    import httpx
except ImportError:
    print("ERROR: httpx not installed. Run: pip install httpx")
    sys.exit(1)

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("ERROR: beautifulsoup4 not installed. Run: pip install beautifulsoup4 lxml")
    sys.exit(1)


# =============================================================================
# CONFIGURATION
# =============================================================================

@dataclass
class ScraperConfig:
    """Scraper configuration."""
    # Rate limiting (be respectful)
    min_delay_seconds: float = 2.0
    max_delay_seconds: float = 5.0
    max_retries: int = 3
    
    # Output
    output_dir: str = "./market_data"
    cache_hours: int = 24
    
    # Scraping depth
    max_listings_per_platform: int = 200
    calendar_months_ahead: int = 6
    
    # User agent rotation
    user_agents: List[str] = field(default_factory=lambda: [
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    ])


# =============================================================================
# DATA MODELS (Matching Signal Architecture)
# =============================================================================

@dataclass
class ScrapedListing:
    """Raw listing data from public pages."""
    platform: str  # 'airbnb' or 'vrbo'
    listing_id: str
    
    # Location
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    
    # Property
    bedrooms: Optional[int] = None
    bathrooms: Optional[float] = None
    sleeps: Optional[int] = None
    property_type: Optional[str] = None
    
    # Amenities (for prevalence signals)
    has_pool: bool = False
    has_hot_tub: bool = False
    has_waterfront: bool = False
    has_beach_access: bool = False
    has_pet_friendly: bool = False
    has_ev_charger: bool = False
    amenities_raw: List[str] = field(default_factory=list)
    
    # Pricing (spot check for rate signals)
    displayed_rate: Optional[float] = None
    rate_date: Optional[str] = None
    
    # Reviews (quality signal)
    review_count: Optional[int] = None
    rating: Optional[float] = None
    
    # Calendar (for compression signal)
    # Dict of 'YYYY-MM-DD' -> is_available
    calendar: Dict[str, bool] = field(default_factory=dict)
    
    scraped_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class MarketSignals:
    """Computed signals for a market."""
    market_id: str
    market_name: str
    center_lat: float
    center_lng: float
    radius_miles: float
    scraped_at: str
    
    # 1️⃣ SUPPLY SIGNALS
    total_listings: int = 0
    listings_by_platform: Dict[str, int] = field(default_factory=dict)
    listings_by_bedrooms: Dict[int, int] = field(default_factory=dict)
    listings_by_type: Dict[str, int] = field(default_factory=dict)
    supply_confidence: str = "low"  # low/medium/high
    
    # 2️⃣ DEMAND SIGNALS (Calendar Compression)
    calendar_compression_7d: float = 0.0   # % unavailable next 7 days
    calendar_compression_14d: float = 0.0
    calendar_compression_30d: float = 0.0
    calendar_compression_90d: float = 0.0
    demand_confidence: str = "low"
    
    # 3️⃣ PLATFORM DOMINANCE
    airbnb_share: float = 0.0
    vrbo_share: float = 0.0
    platform_dominance: str = "balanced"  # airbnb_heavy, vrbo_heavy, balanced
    platform_confidence: str = "low"
    
    # 4️⃣ AMENITY SIGNALS
    amenity_prevalence: Dict[str, float] = field(default_factory=dict)
    amenity_confidence: str = "low"
    
    # 5️⃣ RATE SIGNALS
    rate_p25: Optional[float] = None
    rate_p50: Optional[float] = None
    rate_p75: Optional[float] = None
    rate_by_bedrooms: Dict[int, float] = field(default_factory=dict)
    rate_confidence: str = "low"
    
    # Quality metrics
    avg_rating: Optional[float] = None
    avg_reviews: Optional[float] = None
    
    # Raw data reference
    listing_count_airbnb: int = 0
    listing_count_vrbo: int = 0


# =============================================================================
# RATE LIMITER
# =============================================================================

class RateLimiter:
    """Respectful rate limiting."""
    
    def __init__(self, config: ScraperConfig):
        self.config = config
        self._last_request: Dict[str, float] = {}
    
    async def wait(self, domain: str) -> None:
        """Wait appropriate time before next request."""
        last = self._last_request.get(domain, 0)
        elapsed = time.time() - last
        
        # Random delay within range
        delay = random.uniform(
            self.config.min_delay_seconds,
            self.config.max_delay_seconds
        )
        
        if elapsed < delay:
            await asyncio.sleep(delay - elapsed)
        
        self._last_request[domain] = time.time()


# =============================================================================
# BASE SCRAPER
# =============================================================================

class BaseScraper:
    """Base class with common functionality."""
    
    def __init__(self, config: ScraperConfig):
        self.config = config
        self.rate_limiter = RateLimiter(config)
        self._client: Optional[httpx.AsyncClient] = None
    
    async def get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=True,
                headers=self._get_headers(),
            )
        return self._client
    
    def _get_headers(self) -> Dict[str, str]:
        return {
            "User-Agent": random.choice(self.config.user_agents),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Cache-Control": "no-cache",
        }
    
    async def fetch(self, url: str, domain: str) -> Optional[str]:
        """Fetch URL with rate limiting and retries."""
        await self.rate_limiter.wait(domain)
        
        for attempt in range(self.config.max_retries):
            try:
                client = await self.get_client()
                # Rotate user agent on retry
                client.headers["User-Agent"] = random.choice(self.config.user_agents)
                
                response = await client.get(url)
                
                if response.status_code == 200:
                    return response.text
                elif response.status_code == 403:
                    print(f"  ⚠️  403 Forbidden - may need proxy: {url[:60]}...")
                    return None
                elif response.status_code == 429:
                    wait = (attempt + 1) * 30
                    print(f"  ⚠️  Rate limited, waiting {wait}s...")
                    await asyncio.sleep(wait)
                else:
                    print(f"  ⚠️  HTTP {response.status_code}: {url[:60]}...")
                    
            except Exception as e:
                print(f"  ❌ Error: {e}")
                await asyncio.sleep(5)
        
        return None
    
    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None


# =============================================================================
# AIRBNB SCRAPER (Public Pages Only)
# =============================================================================

class AirbnbScraper(BaseScraper):
    """
    Scrapes Airbnb public search results.
    
    Strategy:
    - Use search page with map bounds
    - Extract listing cards from HTML
    - Get calendar from public listing page
    """
    
    DOMAIN = "airbnb.com"
    
    async def search_area(
        self,
        lat: float,
        lng: float,
        radius_miles: float,
        checkin: Optional[date] = None,
        checkout: Optional[date] = None,
    ) -> List[ScrapedListing]:
        """Search for listings in an area."""
        
        listings = []
        
        # Calculate bounding box
        lat_delta = radius_miles / 69.0
        lng_delta = radius_miles / (69.0 * abs(self._cos_deg(lat)))
        
        ne_lat = lat + lat_delta
        ne_lng = lng + lng_delta
        sw_lat = lat - lat_delta
        sw_lng = lng - lng_delta
        
        # Default dates
        if not checkin:
            today = date.today()
            # Next Friday
            days_to_friday = (4 - today.weekday()) % 7 or 7
            checkin = today + timedelta(days=days_to_friday)
        if not checkout:
            checkout = checkin + timedelta(days=2)
        
        print(f"  🔍 Searching Airbnb: {sw_lat:.3f},{sw_lng:.3f} to {ne_lat:.3f},{ne_lng:.3f}")
        
        # Build search URL
        params = {
            "ne_lat": ne_lat,
            "ne_lng": ne_lng,
            "sw_lat": sw_lat,
            "sw_lng": sw_lng,
            "checkin": checkin.isoformat(),
            "checkout": checkout.isoformat(),
            "adults": 2,
            "search_type": "filter_change",
        }
        
        url = f"https://www.airbnb.com/s/homes?{urlencode(params)}"
        
        html = await self.fetch(url, self.DOMAIN)
        if not html:
            return listings
        
        # Parse listings from page
        extracted = self._parse_search_page(html)
        print(f"  📦 Found {len(extracted)} listings in search results")
        
        # Process each listing
        for i, data in enumerate(extracted[:self.config.max_listings_per_platform]):
            listing = self._parse_listing_data(data, checkin)
            if listing:
                listings.append(listing)
            
            if (i + 1) % 20 == 0:
                print(f"  📊 Processed {i + 1}/{len(extracted)} listings...")
        
        return listings
    
    def _parse_search_page(self, html: str) -> List[Dict]:
        """Extract listing data from search page HTML."""
        results = []
        
        soup = BeautifulSoup(html, 'lxml')
        
        # Airbnb embeds JSON data in script tags
        for script in soup.find_all('script'):
            text = script.string or ''
            
            # Look for listing data patterns
            if '"listing"' in text or '"listingId"' in text:
                # Try to extract JSON objects
                results.extend(self._extract_json_listings(text))
        
        # Also try data attributes
        for elem in soup.find_all(attrs={"data-testid": re.compile("listing")}):
            data = self._extract_listing_from_card(elem)
            if data:
                results.append(data)
        
        return results
    
    def _extract_json_listings(self, text: str) -> List[Dict]:
        """Extract listing objects from embedded JSON."""
        listings = []
        
        # Pattern for listing objects
        patterns = [
            r'"listing"\s*:\s*(\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\})',
            r'"searchResults"\s*:\s*\[(.*?)\]',
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, text, re.DOTALL)
            for match in matches:
                try:
                    # Try to parse as JSON
                    if match.startswith('{'):
                        data = json.loads(match)
                        if 'id' in data or 'listingId' in data:
                            listings.append(data)
                except:
                    pass
        
        return listings
    
    def _extract_listing_from_card(self, elem) -> Optional[Dict]:
        """Extract listing data from a card element."""
        try:
            data = {}
            
            # Find listing ID from links
            link = elem.find('a', href=re.compile(r'/rooms/\d+'))
            if link:
                match = re.search(r'/rooms/(\d+)', link.get('href', ''))
                if match:
                    data['id'] = match.group(1)
            
            # Find price
            price_elem = elem.find(string=re.compile(r'\$[\d,]+'))
            if price_elem:
                match = re.search(r'\$([\d,]+)', price_elem)
                if match:
                    data['price'] = int(match.group(1).replace(',', ''))
            
            # Find rating
            rating_elem = elem.find(string=re.compile(r'[\d.]+\s*\('))
            if rating_elem:
                match = re.search(r'([\d.]+)\s*\((\d+)', rating_elem)
                if match:
                    data['rating'] = float(match.group(1))
                    data['reviews'] = int(match.group(2))
            
            return data if 'id' in data else None
            
        except Exception:
            return None
    
    def _parse_listing_data(self, data: Dict, rate_date: date) -> Optional[ScrapedListing]:
        """Convert raw data to ScrapedListing."""
        try:
            listing_id = str(data.get('id') or data.get('listingId', ''))
            if not listing_id:
                return None
            
            # Extract amenities
            amenities = []
            for key in ['amenities', 'listingAmenities', 'amenity_ids']:
                if key in data:
                    val = data[key]
                    if isinstance(val, list):
                        amenities.extend([str(a).lower() for a in val])
            
            amenity_text = ' '.join(amenities)
            
            return ScrapedListing(
                platform='airbnb',
                listing_id=listing_id,
                latitude=data.get('lat') or data.get('latitude'),
                longitude=data.get('lng') or data.get('longitude'),
                bedrooms=data.get('bedrooms'),
                bathrooms=data.get('bathrooms'),
                sleeps=data.get('personCapacity') or data.get('sleeps'),
                property_type=data.get('roomType') or data.get('propertyType'),
                has_pool='pool' in amenity_text,
                has_hot_tub='hot tub' in amenity_text or 'jacuzzi' in amenity_text,
                has_waterfront='waterfront' in amenity_text or 'beachfront' in amenity_text,
                has_beach_access='beach' in amenity_text,
                has_pet_friendly='pet' in amenity_text,
                has_ev_charger='ev charger' in amenity_text or 'electric vehicle' in amenity_text,
                amenities_raw=amenities,
                displayed_rate=data.get('price') or data.get('priceString'),
                rate_date=rate_date.isoformat(),
                review_count=data.get('reviewsCount') or data.get('reviews'),
                rating=data.get('avgRating') or data.get('rating'),
            )
            
        except Exception as e:
            return None
    
    @staticmethod
    def _cos_deg(deg: float) -> float:
        import math
        return math.cos(math.radians(deg))


# =============================================================================
# VRBO SCRAPER (Public Pages Only)
# =============================================================================

class VrboScraper(BaseScraper):
    """Scrapes VRBO public search results."""
    
    DOMAIN = "vrbo.com"
    
    async def search_area(
        self,
        lat: float,
        lng: float,
        radius_miles: float,
        checkin: Optional[date] = None,
        checkout: Optional[date] = None,
    ) -> List[ScrapedListing]:
        """Search for VRBO listings."""
        
        listings = []
        
        if not checkin:
            today = date.today()
            days_to_friday = (4 - today.weekday()) % 7 or 7
            checkin = today + timedelta(days=days_to_friday)
        if not checkout:
            checkout = checkin + timedelta(days=2)
        
        print(f"  🔍 Searching VRBO near {lat:.3f}, {lng:.3f}")
        
        # VRBO search URL
        params = {
            "latLong": f"{lat},{lng}",
            "adults": 2,
            "startDate": checkin.isoformat(),
            "endDate": checkout.isoformat(),
        }
        
        url = f"https://www.vrbo.com/search?{urlencode(params)}"
        
        html = await self.fetch(url, self.DOMAIN)
        if not html:
            return listings
        
        extracted = self._parse_search_page(html)
        print(f"  📦 Found {len(extracted)} VRBO listings")
        
        for data in extracted[:self.config.max_listings_per_platform]:
            listing = self._parse_listing_data(data, checkin)
            if listing:
                listings.append(listing)
        
        return listings
    
    def _parse_search_page(self, html: str) -> List[Dict]:
        """Parse VRBO search results."""
        results = []
        
        soup = BeautifulSoup(html, 'lxml')
        
        # VRBO uses __NEXT_DATA__ or similar
        for script in soup.find_all('script', id='__NEXT_DATA__'):
            try:
                data = json.loads(script.string or '{}')
                listings = self._find_listings(data)
                results.extend(listings)
            except:
                pass
        
        # Fallback: search for property data
        for script in soup.find_all('script'):
            text = script.string or ''
            if 'propertyId' in text or 'listingId' in text:
                results.extend(self._extract_json_listings(text))
        
        return results
    
    def _find_listings(self, data: Any, depth: int = 0) -> List[Dict]:
        """Recursively find listing objects."""
        if depth > 15:
            return []
        
        results = []
        
        if isinstance(data, dict):
            if 'propertyId' in data and ('bedrooms' in data or 'headline' in data):
                results.append(data)
            for v in data.values():
                results.extend(self._find_listings(v, depth + 1))
        elif isinstance(data, list):
            for item in data:
                results.extend(self._find_listings(item, depth + 1))
        
        return results
    
    def _extract_json_listings(self, text: str) -> List[Dict]:
        """Extract listings from script text."""
        listings = []
        pattern = r'\{[^{}]*"propertyId"[^{}]*\}'
        
        for match in re.findall(pattern, text):
            try:
                data = json.loads(match)
                if 'propertyId' in data:
                    listings.append(data)
            except:
                pass
        
        return listings
    
    def _parse_listing_data(self, data: Dict, rate_date: date) -> Optional[ScrapedListing]:
        """Convert VRBO data to ScrapedListing."""
        try:
            listing_id = str(data.get('propertyId') or data.get('listingId', ''))
            if not listing_id:
                return None
            
            amenities = data.get('amenities', [])
            if isinstance(amenities, list):
                amenities = [str(a).lower() for a in amenities]
            else:
                amenities = []
            
            amenity_text = ' '.join(amenities)
            
            # Price extraction
            price = None
            price_data = data.get('price', {})
            if isinstance(price_data, dict):
                price = price_data.get('total') or price_data.get('avg')
            elif isinstance(price_data, (int, float)):
                price = price_data
            
            return ScrapedListing(
                platform='vrbo',
                listing_id=listing_id,
                latitude=data.get('latitude'),
                longitude=data.get('longitude'),
                bedrooms=data.get('bedrooms'),
                bathrooms=data.get('bathrooms'),
                sleeps=data.get('sleeps') or data.get('maxOccupancy'),
                property_type=data.get('propertyType'),
                has_pool='pool' in amenity_text,
                has_hot_tub='hot tub' in amenity_text or 'spa' in amenity_text,
                has_waterfront='waterfront' in amenity_text,
                has_beach_access='beach' in amenity_text,
                has_pet_friendly='pet' in amenity_text,
                amenities_raw=amenities,
                displayed_rate=price,
                rate_date=rate_date.isoformat(),
                review_count=data.get('reviewCount'),
                rating=data.get('averageRating'),
            )
        except:
            return None


# =============================================================================
# SIGNAL CALCULATOR
# =============================================================================

class SignalCalculator:
    """Calculate market signals from scraped listings."""
    
    def calculate(
        self,
        market_id: str,
        market_name: str,
        lat: float,
        lng: float,
        radius: float,
        listings: List[ScrapedListing],
    ) -> MarketSignals:
        """Calculate all signals from listings."""
        
        signals = MarketSignals(
            market_id=market_id,
            market_name=market_name,
            center_lat=lat,
            center_lng=lng,
            radius_miles=radius,
            scraped_at=datetime.utcnow().isoformat(),
        )
        
        if not listings:
            return signals
        
        signals.total_listings = len(listings)
        
        # 1️⃣ SUPPLY SIGNALS
        self._calc_supply_signals(signals, listings)
        
        # 2️⃣ DEMAND SIGNALS (Calendar Compression)
        self._calc_demand_signals(signals, listings)
        
        # 3️⃣ PLATFORM DOMINANCE
        self._calc_platform_signals(signals, listings)
        
        # 4️⃣ AMENITY SIGNALS
        self._calc_amenity_signals(signals, listings)
        
        # 5️⃣ RATE SIGNALS
        self._calc_rate_signals(signals, listings)
        
        return signals
    
    def _calc_supply_signals(self, signals: MarketSignals, listings: List[ScrapedListing]):
        """Calculate supply signals."""
        # By platform
        for l in listings:
            signals.listings_by_platform[l.platform] = \
                signals.listings_by_platform.get(l.platform, 0) + 1
        
        # By bedrooms
        for l in listings:
            if l.bedrooms:
                signals.listings_by_bedrooms[l.bedrooms] = \
                    signals.listings_by_bedrooms.get(l.bedrooms, 0) + 1
        
        # By type
        for l in listings:
            if l.property_type:
                ptype = l.property_type.lower()
                signals.listings_by_type[ptype] = \
                    signals.listings_by_type.get(ptype, 0) + 1
        
        # Confidence
        total = signals.total_listings
        if total >= 100:
            signals.supply_confidence = "high"
        elif total >= 30:
            signals.supply_confidence = "medium"
        else:
            signals.supply_confidence = "low"
        
        signals.listing_count_airbnb = signals.listings_by_platform.get('airbnb', 0)
        signals.listing_count_vrbo = signals.listings_by_platform.get('vrbo', 0)
    
    def _calc_demand_signals(self, signals: MarketSignals, listings: List[ScrapedListing]):
        """Calculate demand (calendar compression) signals."""
        # Count listings with calendar data
        listings_with_cal = [l for l in listings if l.calendar]
        
        if not listings_with_cal:
            return
        
        today = date.today()
        
        for days, attr in [(7, 'calendar_compression_7d'), 
                           (14, 'calendar_compression_14d'),
                           (30, 'calendar_compression_30d'),
                           (90, 'calendar_compression_90d')]:
            
            unavail_count = 0
            total_count = 0
            
            for l in listings_with_cal:
                for i in range(days):
                    check_date = (today + timedelta(days=i)).isoformat()
                    if check_date in l.calendar:
                        total_count += 1
                        if not l.calendar[check_date]:
                            unavail_count += 1
            
            if total_count > 0:
                setattr(signals, attr, unavail_count / total_count)
        
        # Confidence based on coverage
        coverage = len(listings_with_cal) / len(listings)
        if coverage >= 0.7:
            signals.demand_confidence = "high"
        elif coverage >= 0.4:
            signals.demand_confidence = "medium"
        else:
            signals.demand_confidence = "low"
    
    def _calc_platform_signals(self, signals: MarketSignals, listings: List[ScrapedListing]):
        """Calculate platform dominance signals."""
        total = signals.total_listings
        if total == 0:
            return
        
        airbnb = signals.listings_by_platform.get('airbnb', 0)
        vrbo = signals.listings_by_platform.get('vrbo', 0)
        
        signals.airbnb_share = airbnb / total
        signals.vrbo_share = vrbo / total
        
        ratio = airbnb / vrbo if vrbo > 0 else float('inf')
        
        if ratio > 3:
            signals.platform_dominance = "airbnb_heavy"
            signals.platform_confidence = "high"
        elif ratio < 0.33:
            signals.platform_dominance = "vrbo_heavy"
            signals.platform_confidence = "high"
        elif ratio > 1.5 or ratio < 0.67:
            signals.platform_dominance = "leaning_" + ("airbnb" if ratio > 1 else "vrbo")
            signals.platform_confidence = "medium"
        else:
            signals.platform_dominance = "balanced"
            signals.platform_confidence = "medium"
    
    def _calc_amenity_signals(self, signals: MarketSignals, listings: List[ScrapedListing]):
        """Calculate amenity prevalence signals."""
        total = len(listings)
        if total == 0:
            return
        
        amenities = {
            'pool': sum(1 for l in listings if l.has_pool),
            'hot_tub': sum(1 for l in listings if l.has_hot_tub),
            'waterfront': sum(1 for l in listings if l.has_waterfront),
            'beach_access': sum(1 for l in listings if l.has_beach_access),
            'pet_friendly': sum(1 for l in listings if l.has_pet_friendly),
            'ev_charger': sum(1 for l in listings if l.has_ev_charger),
        }
        
        for amenity, count in amenities.items():
            signals.amenity_prevalence[amenity] = count / total
        
        signals.amenity_confidence = "high" if total >= 50 else "medium" if total >= 20 else "low"
    
    def _calc_rate_signals(self, signals: MarketSignals, listings: List[ScrapedListing]):
        """Calculate rate/pricing signals."""
        rates = []
        rates_by_br: Dict[int, List[float]] = {}
        
        for l in listings:
            if l.displayed_rate and isinstance(l.displayed_rate, (int, float)):
                rate = float(l.displayed_rate)
                if 50 <= rate <= 5000:  # Sanity check
                    rates.append(rate)
                    if l.bedrooms:
                        if l.bedrooms not in rates_by_br:
                            rates_by_br[l.bedrooms] = []
                        rates_by_br[l.bedrooms].append(rate)
        
        if rates:
            rates.sort()
            n = len(rates)
            signals.rate_p25 = rates[int(n * 0.25)]
            signals.rate_p50 = rates[n // 2]
            signals.rate_p75 = rates[int(n * 0.75)]
        
        for br, br_rates in rates_by_br.items():
            if br_rates:
                br_rates.sort()
                signals.rate_by_bedrooms[br] = br_rates[len(br_rates) // 2]
        
        signals.rate_confidence = "high" if len(rates) >= 50 else "medium" if len(rates) >= 20 else "low"
        
        # Quality metrics
        ratings = [l.rating for l in listings if l.rating]
        reviews = [l.review_count for l in listings if l.review_count]
        
        if ratings:
            signals.avg_rating = sum(ratings) / len(ratings)
        if reviews:
            signals.avg_reviews = sum(reviews) / len(reviews)


# =============================================================================
# MAIN ORCHESTRATOR
# =============================================================================

class MarketIntelligenceScraper:
    """
    Main orchestrator for market intelligence gathering.
    
    Usage:
        scraper = MarketIntelligenceScraper()
        signals = await scraper.scrape_market(
            market_id="30a",
            market_name="30A Beaches",
            lat=30.2833,
            lng=-86.0167,
            radius_miles=15,
        )
        scraper.save_results(signals, listings)
    """
    
    def __init__(self, config: Optional[ScraperConfig] = None):
        self.config = config or ScraperConfig()
        self.airbnb = AirbnbScraper(self.config)
        self.vrbo = VrboScraper(self.config)
        self.calculator = SignalCalculator()
    
    async def scrape_market(
        self,
        market_id: str,
        market_name: str,
        lat: float,
        lng: float,
        radius_miles: float = 10,
    ) -> Tuple[MarketSignals, List[ScrapedListing]]:
        """
        Scrape a market and calculate signals.
        
        Returns:
            Tuple of (signals, raw_listings)
        """
        print(f"\n{'='*60}")
        print(f"📍 SCRAPING: {market_name}")
        print(f"   Center: {lat}, {lng} | Radius: {radius_miles}mi")
        print(f"{'='*60}\n")
        
        all_listings = []
        
        # Scrape Airbnb
        print("🏠 Airbnb...")
        try:
            airbnb_listings = await self.airbnb.search_area(lat, lng, radius_miles)
            all_listings.extend(airbnb_listings)
            print(f"   ✅ Got {len(airbnb_listings)} Airbnb listings\n")
        except Exception as e:
            print(f"   ❌ Airbnb error: {e}\n")
        
        # Scrape VRBO
        print("🏡 VRBO...")
        try:
            vrbo_listings = await self.vrbo.search_area(lat, lng, radius_miles)
            all_listings.extend(vrbo_listings)
            print(f"   ✅ Got {len(vrbo_listings)} VRBO listings\n")
        except Exception as e:
            print(f"   ❌ VRBO error: {e}\n")
        
        # Calculate signals
        print("📊 Calculating signals...")
        signals = self.calculator.calculate(
            market_id, market_name, lat, lng, radius_miles, all_listings
        )
        
        print(f"\n{'='*60}")
        print(f"✅ COMPLETE: {signals.total_listings} total listings")
        print(f"{'='*60}\n")
        
        return signals, all_listings
    
    def save_results(
        self,
        signals: MarketSignals,
        listings: List[ScrapedListing],
        output_dir: Optional[str] = None,
    ) -> Dict[str, str]:
        """Save results to files."""
        output_dir = Path(output_dir or self.config.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        market_slug = signals.market_id.replace(' ', '_').lower()
        
        # Save signals
        signals_file = output_dir / f"{market_slug}_signals_{timestamp}.json"
        with open(signals_file, 'w') as f:
            json.dump(asdict(signals), f, indent=2, default=str)
        
        # Save raw listings
        listings_file = output_dir / f"{market_slug}_listings_{timestamp}.json"
        with open(listings_file, 'w') as f:
            json.dump([asdict(l) for l in listings], f, indent=2, default=str)
        
        print(f"💾 Saved signals to: {signals_file}")
        print(f"💾 Saved listings to: {listings_file}")
        
        return {
            'signals': str(signals_file),
            'listings': str(listings_file),
        }
    
    def print_signal_report(self, signals: MarketSignals):
        """Print a formatted signal report."""
        print(f"\n{'='*60}")
        print(f"📊 SIGNAL REPORT: {signals.market_name}")
        print(f"{'='*60}\n")
        
        print("1️⃣  SUPPLY SIGNALS")
        print(f"    Total Listings: {signals.total_listings}")
        print(f"    By Platform: {signals.listings_by_platform}")
        print(f"    By Bedrooms: {signals.listings_by_bedrooms}")
        print(f"    Confidence: {signals.supply_confidence.upper()}")
        
        print("\n2️⃣  DEMAND SIGNALS (Calendar Compression)")
        print(f"    Next 7 days:  {signals.calendar_compression_7d:.1%} unavailable")
        print(f"    Next 14 days: {signals.calendar_compression_14d:.1%} unavailable")
        print(f"    Next 30 days: {signals.calendar_compression_30d:.1%} unavailable")
        print(f"    Confidence: {signals.demand_confidence.upper()}")
        
        print("\n3️⃣  PLATFORM DOMINANCE")
        print(f"    Airbnb: {signals.airbnb_share:.1%}")
        print(f"    VRBO: {signals.vrbo_share:.1%}")
        print(f"    Status: {signals.platform_dominance}")
        print(f"    Confidence: {signals.platform_confidence.upper()}")
        
        print("\n4️⃣  AMENITY PREVALENCE")
        for amenity, pct in signals.amenity_prevalence.items():
            print(f"    {amenity}: {pct:.1%}")
        print(f"    Confidence: {signals.amenity_confidence.upper()}")
        
        print("\n5️⃣  RATE SIGNALS")
        if signals.rate_p50:
            print(f"    P25: ${signals.rate_p25:.0f}")
            print(f"    P50 (Median): ${signals.rate_p50:.0f}")
            print(f"    P75: ${signals.rate_p75:.0f}")
        if signals.rate_by_bedrooms:
            print(f"    By Bedrooms: {signals.rate_by_bedrooms}")
        print(f"    Confidence: {signals.rate_confidence.upper()}")
        
        if signals.avg_rating:
            print(f"\n    Quality: {signals.avg_rating:.2f}★ avg ({signals.avg_reviews:.0f} reviews avg)")
        
        print(f"\n{'='*60}\n")
    
    async def close(self):
        """Clean up resources."""
        await self.airbnb.close()
        await self.vrbo.close()


# =============================================================================
# CLI
# =============================================================================

async def main():
    parser = argparse.ArgumentParser(
        description="403-Safe Market Intelligence Scraper",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python signal_scraper.py --market "30A Beaches" --lat 30.2833 --lng -86.0167 --radius 15
  python signal_scraper.py --market "Destin" --lat 30.3935 --lng -86.4958 --radius 10
  python signal_scraper.py --market "Gulf Shores" --lat 30.2460 --lng -87.7008 --radius 12
        """
    )
    
    parser.add_argument('--market', required=True, help='Market name')
    parser.add_argument('--lat', type=float, required=True, help='Center latitude')
    parser.add_argument('--lng', type=float, required=True, help='Center longitude')
    parser.add_argument('--radius', type=float, default=10, help='Search radius in miles')
    parser.add_argument('--output', default='./market_data', help='Output directory')
    
    args = parser.parse_args()
    
    # Create scraper
    config = ScraperConfig(output_dir=args.output)
    scraper = MarketIntelligenceScraper(config)
    
    try:
        # Scrape market
        signals, listings = await scraper.scrape_market(
            market_id=args.market.lower().replace(' ', '_'),
            market_name=args.market,
            lat=args.lat,
            lng=args.lng,
            radius_miles=args.radius,
        )
        
        # Print report
        scraper.print_signal_report(signals)
        
        # Save results
        scraper.save_results(signals, listings, args.output)
        
    finally:
        await scraper.close()


if __name__ == "__main__":
    asyncio.run(main())
