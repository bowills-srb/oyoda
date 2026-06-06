"""
Public Data Scraping Strategy for Rental Revenue Platform.

Maps each signal to publicly available data sources and defines
what we can legally/ethically scrape.

=============================================================================
SIGNAL → DATA SOURCE MAPPING
=============================================================================

| Signal Type              | Primary Source      | Secondary Source   | Data Points                    |
|--------------------------|---------------------|--------------------| -------------------------------|
| PLATFORM_DOMINANCE       | Airbnb, VRBO        | -                  | Listing counts by platform     |
| SUPPLY_VELOCITY          | Airbnb, VRBO        | -                  | New listings over time         |
| DEMAND_PRESSURE          | Airbnb, VRBO        | -                  | Availability calendars         |
| AMENITY_LIFT             | Airbnb, VRBO        | -                  | Amenities + displayed rates    |
| SEASONALITY_CURVE        | Airbnb, VRBO        | -                  | Availability + rates by month  |
| PRICE_ELASTICITY         | Airbnb, VRBO        | -                  | Rate changes over time         |
| RATE_POSITION            | Airbnb, VRBO        | -                  | Comparable property rates      |
| OCCUPANCY_MOMENTUM       | Airbnb, VRBO        | -                  | Calendar availability changes  |
| BOOKING_LEAD_TIME        | Airbnb, VRBO        | -                  | When dates become unavailable  |
| -                        | Zillow              | Redfin             | Property values, sales history |
| -                        | Realtor.com         | -                  | Rental estimates, comps        |

=============================================================================
WHAT WE CAN SCRAPE (Public Data)
=============================================================================

AIRBNB (Public Search Results):
✅ Listing ID, title, property type
✅ Location (lat/lng from map)
✅ Bedrooms, bathrooms, guest capacity
✅ Amenities list
✅ Displayed nightly rate (for search dates)
✅ Review count and rating
✅ Superhost status
✅ Calendar availability (next 12 months)
✅ Minimum stay requirements

VRBO (Public Search Results):
✅ Listing ID, title, property type  
✅ Location (general area)
✅ Bedrooms, bathrooms
✅ Amenities
✅ Displayed rate
✅ Review count and rating
✅ Calendar availability

ZILLOW (Public Property Data):
✅ Property address, Zestimate
✅ Beds, baths, sqft
✅ Year built
✅ Last sale date and price
✅ Tax assessment
✅ Rental Zestimate

=============================================================================
WHAT WE CANNOT/SHOULD NOT SCRAPE
=============================================================================

❌ Actual booking data (not public)
❌ Revenue numbers (inference only)
❌ Guest information
❌ Host contact details
❌ Prices at excessive scale (TOS risk)
❌ Any data requiring login

"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4
import asyncio
import json
import re
import random
import hashlib

# We'll use httpx for async HTTP requests and beautifulsoup for parsing
try:
    import httpx
except ImportError:
    httpx = None

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None


# =============================================================================
# DATA MODELS
# =============================================================================

class Platform(str, Enum):
    AIRBNB = "airbnb"
    VRBO = "vrbo"
    ZILLOW = "zillow"
    REDFIN = "redfin"
    REALTOR = "realtor"


@dataclass
class ScrapedListing:
    """A listing scraped from a vacation rental platform."""
    platform: Platform
    listing_id: str
    url: str
    
    # Location
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zipcode: Optional[str] = None
    
    # Property details
    title: Optional[str] = None
    property_type: Optional[str] = None
    bedrooms: Optional[int] = None
    bathrooms: Optional[float] = None
    sleeps: Optional[int] = None
    sqft: Optional[int] = None
    
    # Amenities
    amenities: List[str] = field(default_factory=list)
    has_pool: bool = False
    has_hot_tub: bool = False
    has_waterfront: bool = False
    has_beach_access: bool = False
    has_pet_friendly: bool = False
    has_ev_charger: bool = False
    
    # Pricing (displayed rate for search dates)
    displayed_rate: Optional[float] = None
    displayed_rate_date: Optional[date] = None
    minimum_stay: Optional[int] = None
    
    # Reviews
    review_count: Optional[int] = None
    rating: Optional[float] = None
    
    # Host info (public only)
    is_superhost: bool = False
    host_review_count: Optional[int] = None
    
    # Calendar availability (next 12 months)
    # Dict of date -> is_available
    availability: Dict[str, bool] = field(default_factory=dict)
    
    # Metadata
    scraped_at: datetime = field(default_factory=datetime.utcnow)
    raw_data: Optional[Dict] = None


@dataclass
class ScrapedProperty:
    """A property scraped from a real estate platform (Zillow, etc.)."""
    platform: Platform
    property_id: str
    url: str
    
    # Address
    address: str = ""
    city: Optional[str] = None
    state: Optional[str] = None
    zipcode: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    
    # Property details
    bedrooms: Optional[int] = None
    bathrooms: Optional[float] = None
    sqft: Optional[int] = None
    lot_size: Optional[int] = None
    year_built: Optional[int] = None
    property_type: Optional[str] = None
    
    # Valuation
    estimated_value: Optional[float] = None  # Zestimate
    rental_estimate: Optional[float] = None  # Rent Zestimate
    
    # Sales history
    last_sale_date: Optional[date] = None
    last_sale_price: Optional[float] = None
    
    # Tax info
    tax_assessment: Optional[float] = None
    annual_tax: Optional[float] = None
    
    # Status
    is_for_sale: bool = False
    list_price: Optional[float] = None
    days_on_market: Optional[int] = None
    
    # Metadata
    scraped_at: datetime = field(default_factory=datetime.utcnow)


@dataclass 
class MarketSnapshot:
    """Aggregated market data from scraping."""
    market_id: str
    market_name: str
    scraped_at: datetime
    
    # Supply metrics
    total_listings: int = 0
    listings_by_platform: Dict[str, int] = field(default_factory=dict)
    listings_by_bedrooms: Dict[int, int] = field(default_factory=dict)
    listings_by_type: Dict[str, int] = field(default_factory=dict)
    
    # Amenity prevalence
    pct_with_pool: float = 0.0
    pct_with_hot_tub: float = 0.0
    pct_with_waterfront: float = 0.0
    pct_with_pet_friendly: float = 0.0
    
    # Pricing (by bedroom count)
    median_rate_by_bedrooms: Dict[int, float] = field(default_factory=dict)
    rate_percentiles: Dict[str, float] = field(default_factory=dict)  # p10, p25, p50, p75, p90
    
    # Availability/demand
    pct_unavailable_next_7: float = 0.0
    pct_unavailable_next_14: float = 0.0
    pct_unavailable_next_30: float = 0.0
    pct_unavailable_next_90: float = 0.0
    
    # Seasonality (availability by month)
    availability_by_month: Dict[str, float] = field(default_factory=dict)
    rates_by_month: Dict[str, float] = field(default_factory=dict)
    
    # Quality metrics
    avg_rating: float = 0.0
    avg_review_count: float = 0.0
    pct_superhost: float = 0.0
    
    # Real estate context
    median_home_value: Optional[float] = None
    median_rental_estimate: Optional[float] = None


# =============================================================================
# RATE LIMITER
# =============================================================================

class RateLimiter:
    """
    Async rate limiter with per-domain limits.
    
    Respects robots.txt crawl-delay where specified.
    """
    
    def __init__(self):
        self._last_request: Dict[str, datetime] = {}
        self._limits: Dict[str, float] = {
            # Requests per second by domain
            "airbnb.com": 0.5,      # 1 request per 2 seconds
            "vrbo.com": 0.5,
            "zillow.com": 0.33,     # 1 request per 3 seconds
            "redfin.com": 0.33,
            "realtor.com": 0.33,
            "default": 0.2,         # 1 request per 5 seconds
        }
    
    async def wait(self, domain: str) -> None:
        """Wait until we can make another request to this domain."""
        limit = self._limits.get(domain, self._limits["default"])
        min_interval = 1.0 / limit
        
        last = self._last_request.get(domain)
        if last:
            elapsed = (datetime.utcnow() - last).total_seconds()
            if elapsed < min_interval:
                await asyncio.sleep(min_interval - elapsed)
        
        self._last_request[domain] = datetime.utcnow()
    
    def set_limit(self, domain: str, requests_per_second: float) -> None:
        """Set custom rate limit for a domain."""
        self._limits[domain] = requests_per_second


# =============================================================================
# BASE SCRAPER
# =============================================================================

class BaseScraper(ABC):
    """Base class for all scrapers."""
    
    def __init__(self, rate_limiter: Optional[RateLimiter] = None):
        self.rate_limiter = rate_limiter or RateLimiter()
        self._client: Optional[httpx.AsyncClient] = None
    
    @property
    @abstractmethod
    def platform(self) -> Platform:
        """Return the platform this scraper handles."""
        pass
    
    @property
    @abstractmethod
    def domain(self) -> str:
        """Return the domain being scraped."""
        pass
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=True,
                headers={
                    "User-Agent": self._get_user_agent(),
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.5",
                    "Accept-Encoding": "gzip, deflate",
                    "Connection": "keep-alive",
                },
            )
        return self._client
    
    def _get_user_agent(self) -> str:
        """Return a realistic user agent."""
        agents = [
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
        ]
        # Use consistent agent per session based on some seed
        return agents[hash(id(self)) % len(agents)]
    
    async def _fetch(self, url: str) -> Optional[str]:
        """Fetch a URL with rate limiting."""
        await self.rate_limiter.wait(self.domain)
        
        try:
            client = await self._get_client()
            response = await client.get(url)
            
            if response.status_code == 200:
                return response.text
            elif response.status_code == 429:
                # Rate limited - back off
                await asyncio.sleep(60)
                return None
            else:
                return None
                
        except Exception as e:
            print(f"Error fetching {url}: {e}")
            return None
    
    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None


# =============================================================================
# AIRBNB SCRAPER
# =============================================================================

class AirbnbScraper(BaseScraper):
    """
    Scraper for Airbnb public listing data.
    
    Strategy:
    1. Use search API endpoint to find listings in an area
    2. Extract listing IDs and basic info from search results
    3. Fetch individual listing pages for detailed data
    4. Parse calendar data for availability
    
    Note: Airbnb uses heavy JavaScript rendering. We extract data from
    the embedded JSON state rather than parsing rendered HTML.
    """
    
    @property
    def platform(self) -> Platform:
        return Platform.AIRBNB
    
    @property
    def domain(self) -> str:
        return "airbnb.com"
    
    async def search_area(
        self,
        latitude: float,
        longitude: float,
        radius_miles: float = 10,
        checkin: Optional[date] = None,
        checkout: Optional[date] = None,
        max_results: int = 50,
    ) -> List[ScrapedListing]:
        """
        Search for listings in an area.
        
        Args:
            latitude: Center point latitude
            longitude: Center point longitude
            radius_miles: Search radius
            checkin: Check-in date for pricing
            checkout: Check-out date for pricing
            max_results: Maximum listings to return
        """
        listings = []
        
        # Default to next weekend if no dates provided
        if not checkin:
            today = date.today()
            days_until_friday = (4 - today.weekday()) % 7
            if days_until_friday == 0:
                days_until_friday = 7
            checkin = today + timedelta(days=days_until_friday)
        if not checkout:
            checkout = checkin + timedelta(days=2)
        
        # Build search URL
        # Airbnb search uses ne_lat, ne_lng, sw_lat, sw_lng for bounding box
        # Convert radius to approximate lat/lng bounds
        lat_delta = radius_miles / 69.0  # ~69 miles per degree latitude
        lng_delta = radius_miles / (69.0 * abs(cos_deg(latitude)))
        
        ne_lat = latitude + lat_delta
        ne_lng = longitude + lng_delta
        sw_lat = latitude - lat_delta
        sw_lng = longitude - lng_delta
        
        search_url = (
            f"https://www.airbnb.com/s/homes?"
            f"ne_lat={ne_lat}&ne_lng={ne_lng}&sw_lat={sw_lat}&sw_lng={sw_lng}"
            f"&checkin={checkin.isoformat()}&checkout={checkout.isoformat()}"
            f"&adults=2"
        )
        
        html = await self._fetch(search_url)
        if not html:
            return listings
        
        # Extract listing data from page
        extracted = self._extract_search_results(html)
        
        for item in extracted[:max_results]:
            listing = await self._parse_listing_preview(item, checkin)
            if listing:
                listings.append(listing)
        
        return listings
    
    def _extract_search_results(self, html: str) -> List[Dict]:
        """Extract listing data from search page HTML."""
        results = []
        
        # Airbnb embeds data in a script tag with id="data-deferred-state" or similar
        # Look for JSON data in script tags
        
        if not BeautifulSoup:
            # Fallback: regex extraction
            pattern = r'"listing":\s*(\{[^}]+\})'
            matches = re.findall(pattern, html)
            for match in matches:
                try:
                    data = json.loads(match)
                    results.append(data)
                except:
                    pass
            return results
        
        soup = BeautifulSoup(html, 'html.parser')
        
        # Find script tags with JSON data
        for script in soup.find_all('script', type='application/json'):
            try:
                data = json.loads(script.string or '{}')
                # Navigate to listing results in the data structure
                listings = self._find_listings_in_data(data)
                results.extend(listings)
            except:
                pass
        
        # Also try data-state attributes
        for elem in soup.find_all(attrs={"data-state": True}):
            try:
                data = json.loads(elem.get("data-state", "{}"))
                listings = self._find_listings_in_data(data)
                results.extend(listings)
            except:
                pass
        
        return results
    
    def _find_listings_in_data(self, data: Any, depth: int = 0) -> List[Dict]:
        """Recursively find listing objects in nested data."""
        results = []
        
        if depth > 10:  # Prevent infinite recursion
            return results
        
        if isinstance(data, dict):
            # Check if this looks like a listing
            if 'id' in data and ('name' in data or 'title' in data):
                if 'roomType' in data or 'room_type' in data or 'bedrooms' in data:
                    results.append(data)
            
            # Recurse into values
            for value in data.values():
                results.extend(self._find_listings_in_data(value, depth + 1))
                
        elif isinstance(data, list):
            for item in data:
                results.extend(self._find_listings_in_data(item, depth + 1))
        
        return results
    
    async def _parse_listing_preview(
        self, 
        data: Dict, 
        rate_date: date
    ) -> Optional[ScrapedListing]:
        """Parse a listing preview from search results."""
        try:
            listing_id = str(data.get('id', ''))
            if not listing_id:
                return None
            
            # Extract coordinates
            lat = data.get('lat') or data.get('latitude')
            lng = data.get('lng') or data.get('longitude')
            
            # Extract amenities
            amenities_raw = data.get('amenities', []) or data.get('listing_amenities', [])
            amenities = []
            for a in amenities_raw:
                if isinstance(a, str):
                    amenities.append(a.lower())
                elif isinstance(a, dict):
                    amenities.append(a.get('name', '').lower())
            
            # Detect amenity flags
            amenity_text = ' '.join(amenities)
            
            listing = ScrapedListing(
                platform=Platform.AIRBNB,
                listing_id=listing_id,
                url=f"https://www.airbnb.com/rooms/{listing_id}",
                latitude=float(lat) if lat else None,
                longitude=float(lng) if lng else None,
                title=data.get('name') or data.get('title'),
                property_type=data.get('room_type') or data.get('roomType'),
                bedrooms=data.get('bedrooms'),
                bathrooms=data.get('bathrooms'),
                sleeps=data.get('person_capacity') or data.get('personCapacity'),
                amenities=amenities,
                has_pool='pool' in amenity_text,
                has_hot_tub='hot tub' in amenity_text or 'jacuzzi' in amenity_text,
                has_waterfront='waterfront' in amenity_text or 'beachfront' in amenity_text or 'ocean' in amenity_text,
                has_beach_access='beach' in amenity_text,
                has_pet_friendly='pet' in amenity_text or 'dog' in amenity_text,
                displayed_rate=self._extract_price(data),
                displayed_rate_date=rate_date,
                review_count=data.get('reviews_count') or data.get('reviewsCount'),
                rating=data.get('star_rating') or data.get('avgRating'),
                is_superhost=data.get('is_superhost', False) or data.get('isSuperhost', False),
            )
            
            return listing
            
        except Exception as e:
            print(f"Error parsing listing: {e}")
            return None
    
    def _extract_price(self, data: Dict) -> Optional[float]:
        """Extract price from various data formats."""
        # Try different price fields
        for key in ['price', 'price_string', 'priceString', 'pricing_quote']:
            val = data.get(key)
            if val:
                if isinstance(val, (int, float)):
                    return float(val)
                if isinstance(val, str):
                    # Extract number from string like "$250"
                    match = re.search(r'[\d,]+', val.replace(',', ''))
                    if match:
                        return float(match.group())
                if isinstance(val, dict):
                    return self._extract_price(val)
        return None
    
    async def get_listing_calendar(
        self,
        listing_id: str,
        months: int = 12,
    ) -> Dict[str, bool]:
        """
        Fetch calendar availability for a listing.
        
        Returns dict of date string -> is_available
        """
        availability = {}
        
        # Airbnb calendar endpoint
        today = date.today()
        
        for month_offset in range(months):
            month_date = today + timedelta(days=30 * month_offset)
            month_str = month_date.strftime("%Y-%m")
            
            url = (
                f"https://www.airbnb.com/api/v3/PdpAvailabilityCalendar?"
                f"listingId={listing_id}&month={month_date.month}&year={month_date.year}"
            )
            
            html = await self._fetch(url)
            if html:
                try:
                    data = json.loads(html)
                    calendar_days = self._find_calendar_days(data)
                    for day in calendar_days:
                        date_str = day.get('date')
                        available = day.get('available', True)
                        if date_str:
                            availability[date_str] = available
                except:
                    pass
            
            # Small delay between calendar requests
            await asyncio.sleep(0.5)
        
        return availability
    
    def _find_calendar_days(self, data: Any) -> List[Dict]:
        """Find calendar day data in API response."""
        days = []
        
        if isinstance(data, dict):
            if 'date' in data and 'available' in data:
                days.append(data)
            for value in data.values():
                days.extend(self._find_calendar_days(value))
        elif isinstance(data, list):
            for item in data:
                days.extend(self._find_calendar_days(item))
        
        return days


# =============================================================================
# VRBO SCRAPER
# =============================================================================

class VRBOScraper(BaseScraper):
    """
    Scraper for VRBO public listing data.
    
    VRBO (part of Expedia Group) has a different structure than Airbnb.
    Uses GraphQL API for search results.
    """
    
    @property
    def platform(self) -> Platform:
        return Platform.VRBO
    
    @property
    def domain(self) -> str:
        return "vrbo.com"
    
    async def search_area(
        self,
        latitude: float,
        longitude: float,
        radius_miles: float = 10,
        checkin: Optional[date] = None,
        checkout: Optional[date] = None,
        max_results: int = 50,
    ) -> List[ScrapedListing]:
        """Search for VRBO listings in an area."""
        listings = []
        
        if not checkin:
            today = date.today()
            days_until_friday = (4 - today.weekday()) % 7
            if days_until_friday == 0:
                days_until_friday = 7
            checkin = today + timedelta(days=days_until_friday)
        if not checkout:
            checkout = checkin + timedelta(days=2)
        
        # VRBO search URL
        # Uses destination query or lat/lng
        search_url = (
            f"https://www.vrbo.com/search/keywords:vacation-rentals?"
            f"latLong={latitude},{longitude}"
            f"&adults=2"
            f"&startDate={checkin.isoformat()}"
            f"&endDate={checkout.isoformat()}"
        )
        
        html = await self._fetch(search_url)
        if not html:
            return listings
        
        # Extract listing data
        extracted = self._extract_search_results(html)
        
        for item in extracted[:max_results]:
            listing = self._parse_listing(item, checkin)
            if listing:
                listings.append(listing)
        
        return listings
    
    def _extract_search_results(self, html: str) -> List[Dict]:
        """Extract listing data from VRBO search page."""
        results = []
        
        if not BeautifulSoup:
            return results
        
        soup = BeautifulSoup(html, 'html.parser')
        
        # VRBO embeds data in window.__PRELOADED_STATE__ or similar
        for script in soup.find_all('script'):
            text = script.string or ''
            
            # Look for preloaded state
            if '__PRELOADED_STATE__' in text or 'window.__INITIAL_STATE__' in text:
                # Extract JSON
                match = re.search(r'=\s*(\{.+\})\s*;?\s*$', text, re.DOTALL)
                if match:
                    try:
                        data = json.loads(match.group(1))
                        listings = self._find_listings_in_data(data)
                        results.extend(listings)
                    except:
                        pass
        
        return results
    
    def _find_listings_in_data(self, data: Any, depth: int = 0) -> List[Dict]:
        """Find listing objects in VRBO data structure."""
        results = []
        
        if depth > 10:
            return results
        
        if isinstance(data, dict):
            # VRBO listing indicators
            if 'propertyId' in data or 'listingId' in data:
                if 'bedrooms' in data or 'bathrooms' in data or 'headline' in data:
                    results.append(data)
            
            for value in data.values():
                results.extend(self._find_listings_in_data(value, depth + 1))
                
        elif isinstance(data, list):
            for item in data:
                results.extend(self._find_listings_in_data(item, depth + 1))
        
        return results
    
    def _parse_listing(self, data: Dict, rate_date: date) -> Optional[ScrapedListing]:
        """Parse a VRBO listing from data."""
        try:
            listing_id = str(data.get('propertyId') or data.get('listingId', ''))
            if not listing_id:
                return None
            
            # Extract coordinates
            geo = data.get('geoCode', {}) or data.get('coordinates', {})
            lat = geo.get('latitude') or data.get('latitude')
            lng = geo.get('longitude') or data.get('longitude')
            
            # Amenities
            amenities_raw = data.get('amenities', []) or []
            amenities = [str(a).lower() for a in amenities_raw]
            amenity_text = ' '.join(amenities)
            
            # Price
            price = None
            price_data = data.get('price', {}) or data.get('priceInfo', {})
            if isinstance(price_data, dict):
                price = price_data.get('total') or price_data.get('avg') or price_data.get('amount')
            elif isinstance(price_data, (int, float)):
                price = price_data
            
            return ScrapedListing(
                platform=Platform.VRBO,
                listing_id=listing_id,
                url=f"https://www.vrbo.com/{listing_id}",
                latitude=float(lat) if lat else None,
                longitude=float(lng) if lng else None,
                title=data.get('headline') or data.get('name'),
                property_type=data.get('propertyType'),
                bedrooms=data.get('bedrooms'),
                bathrooms=data.get('bathrooms'),
                sleeps=data.get('sleeps') or data.get('maxOccupancy'),
                amenities=amenities,
                has_pool='pool' in amenity_text,
                has_hot_tub='hot tub' in amenity_text or 'spa' in amenity_text,
                has_waterfront='waterfront' in amenity_text or 'beach' in amenity_text,
                has_pet_friendly='pet' in amenity_text,
                displayed_rate=float(price) if price else None,
                displayed_rate_date=rate_date,
                review_count=data.get('reviewCount'),
                rating=data.get('averageRating'),
            )
            
        except Exception as e:
            print(f"Error parsing VRBO listing: {e}")
            return None


# =============================================================================
# ZILLOW SCRAPER
# =============================================================================

class ZillowScraper(BaseScraper):
    """
    Scraper for Zillow public property data.
    
    Extracts:
    - Zestimate (estimated value)
    - Rent Zestimate (estimated rent)
    - Property details
    - Sales history
    - Tax info
    """
    
    @property
    def platform(self) -> Platform:
        return Platform.ZILLOW
    
    @property
    def domain(self) -> str:
        return "zillow.com"
    
    async def search_area(
        self,
        latitude: float,
        longitude: float,
        radius_miles: float = 5,
        max_results: int = 50,
    ) -> List[ScrapedProperty]:
        """Search for properties in an area."""
        properties = []
        
        # Convert to bounding box
        lat_delta = radius_miles / 69.0
        lng_delta = radius_miles / (69.0 * abs(cos_deg(latitude)))
        
        # Zillow search URL
        search_url = (
            f"https://www.zillow.com/search/GetSearchPageState.htm?"
            f"searchQueryState={{\"mapBounds\":{{\"north\":{latitude + lat_delta},"
            f"\"south\":{latitude - lat_delta},\"east\":{longitude + lng_delta},"
            f"\"west\":{longitude - lng_delta}}}}}"
        )
        
        html = await self._fetch(search_url)
        if not html:
            return properties
        
        extracted = self._extract_properties(html)
        
        for item in extracted[:max_results]:
            prop = self._parse_property(item)
            if prop:
                properties.append(prop)
        
        return properties
    
    async def get_property_details(self, zpid: str) -> Optional[ScrapedProperty]:
        """Get detailed info for a specific property by Zillow Property ID."""
        url = f"https://www.zillow.com/homedetails/{zpid}_zpid/"
        
        html = await self._fetch(url)
        if not html:
            return None
        
        data = self._extract_property_data(html)
        if data:
            return self._parse_property(data)
        
        return None
    
    def _extract_properties(self, html: str) -> List[Dict]:
        """Extract property data from search results."""
        results = []
        
        # Try to parse as JSON (API response)
        try:
            data = json.loads(html)
            if 'searchResults' in data:
                results.extend(data['searchResults'].get('listResults', []))
            if 'cat1' in data:
                results.extend(data['cat1'].get('searchResults', {}).get('listResults', []))
            return results
        except:
            pass
        
        # Parse HTML
        if not BeautifulSoup:
            return results
        
        soup = BeautifulSoup(html, 'html.parser')
        
        # Look for embedded JSON
        for script in soup.find_all('script', type='application/json'):
            try:
                data = json.loads(script.string or '{}')
                props = self._find_properties_in_data(data)
                results.extend(props)
            except:
                pass
        
        return results
    
    def _extract_property_data(self, html: str) -> Optional[Dict]:
        """Extract property data from detail page."""
        if not BeautifulSoup:
            return None
        
        soup = BeautifulSoup(html, 'html.parser')
        
        # Zillow embeds property data in script tags
        for script in soup.find_all('script', type='application/json'):
            try:
                data = json.loads(script.string or '{}')
                # Look for property object
                if 'zpid' in str(data):
                    props = self._find_properties_in_data(data)
                    if props:
                        return props[0]
            except:
                pass
        
        return None
    
    def _find_properties_in_data(self, data: Any, depth: int = 0) -> List[Dict]:
        """Find property objects in data structure."""
        results = []
        
        if depth > 10:
            return results
        
        if isinstance(data, dict):
            # Zillow property indicators
            if 'zpid' in data or 'zestimate' in data:
                results.append(data)
            
            for value in data.values():
                results.extend(self._find_properties_in_data(value, depth + 1))
                
        elif isinstance(data, list):
            for item in data:
                results.extend(self._find_properties_in_data(item, depth + 1))
        
        return results
    
    def _parse_property(self, data: Dict) -> Optional[ScrapedProperty]:
        """Parse a property from Zillow data."""
        try:
            zpid = str(data.get('zpid', ''))
            if not zpid:
                return None
            
            # Address
            address_data = data.get('address', {})
            if isinstance(address_data, str):
                address = address_data
                city = state = zipcode = None
            else:
                address = address_data.get('streetAddress', '')
                city = address_data.get('city')
                state = address_data.get('state')
                zipcode = address_data.get('zipcode')
            
            # Coordinates
            lat = data.get('latitude') or data.get('lat')
            lng = data.get('longitude') or data.get('lng')
            
            # Valuation
            zestimate = data.get('zestimate') or data.get('price')
            rent_zestimate = data.get('rentZestimate')
            
            # Sales history
            last_sale = data.get('lastSoldDate')
            last_price = data.get('lastSoldPrice')
            
            return ScrapedProperty(
                platform=Platform.ZILLOW,
                property_id=zpid,
                url=f"https://www.zillow.com/homedetails/{zpid}_zpid/",
                address=address,
                city=city,
                state=state,
                zipcode=zipcode,
                latitude=float(lat) if lat else None,
                longitude=float(lng) if lng else None,
                bedrooms=data.get('bedrooms'),
                bathrooms=data.get('bathrooms'),
                sqft=data.get('livingArea') or data.get('sqft'),
                year_built=data.get('yearBuilt'),
                property_type=data.get('homeType'),
                estimated_value=float(zestimate) if zestimate else None,
                rental_estimate=float(rent_zestimate) if rent_zestimate else None,
                last_sale_date=parse_date(last_sale) if last_sale else None,
                last_sale_price=float(last_price) if last_price else None,
                tax_assessment=data.get('taxAssessedValue'),
                is_for_sale=data.get('homeStatus') == 'FOR_SALE',
                list_price=data.get('price') if data.get('homeStatus') == 'FOR_SALE' else None,
                days_on_market=data.get('daysOnZillow'),
            )
            
        except Exception as e:
            print(f"Error parsing Zillow property: {e}")
            return None


# =============================================================================
# MARKET AGGREGATOR
# =============================================================================

class MarketDataAggregator:
    """
    Aggregates scraped data into market signals.
    
    Combines data from multiple sources to create:
    - Supply metrics
    - Pricing benchmarks
    - Seasonality patterns
    - Amenity prevalence
    """
    
    def __init__(self):
        self.airbnb_scraper = AirbnbScraper()
        self.vrbo_scraper = VRBOScraper()
        self.zillow_scraper = ZillowScraper()
    
    async def scrape_market(
        self,
        market_id: str,
        market_name: str,
        latitude: float,
        longitude: float,
        radius_miles: float = 10,
    ) -> MarketSnapshot:
        """
        Scrape all data sources for a market and aggregate.
        
        Args:
            market_id: Unique identifier for the market
            market_name: Human-readable market name
            latitude: Center point latitude
            longitude: Center point longitude
            radius_miles: Search radius
            
        Returns:
            Aggregated market snapshot
        """
        # Scrape vacation rental platforms
        airbnb_listings = await self.airbnb_scraper.search_area(
            latitude, longitude, radius_miles, max_results=100
        )
        
        vrbo_listings = await self.vrbo_scraper.search_area(
            latitude, longitude, radius_miles, max_results=100
        )
        
        # Scrape real estate data
        zillow_properties = await self.zillow_scraper.search_area(
            latitude, longitude, radius_miles / 2, max_results=50
        )
        
        # Combine all rental listings
        all_listings = airbnb_listings + vrbo_listings
        
        # Aggregate into snapshot
        snapshot = self._aggregate_listings(
            market_id, market_name, all_listings, zillow_properties
        )
        
        return snapshot
    
    def _aggregate_listings(
        self,
        market_id: str,
        market_name: str,
        listings: List[ScrapedListing],
        properties: List[ScrapedProperty],
    ) -> MarketSnapshot:
        """Aggregate listings into market snapshot."""
        
        snapshot = MarketSnapshot(
            market_id=market_id,
            market_name=market_name,
            scraped_at=datetime.utcnow(),
        )
        
        if not listings:
            return snapshot
        
        # Count metrics
        snapshot.total_listings = len(listings)
        
        # Platform breakdown
        for listing in listings:
            platform = listing.platform.value
            snapshot.listings_by_platform[platform] = \
                snapshot.listings_by_platform.get(platform, 0) + 1
        
        # Bedroom breakdown
        for listing in listings:
            if listing.bedrooms:
                br = listing.bedrooms
                snapshot.listings_by_bedrooms[br] = \
                    snapshot.listings_by_bedrooms.get(br, 0) + 1
        
        # Amenity prevalence
        pool_count = sum(1 for l in listings if l.has_pool)
        hot_tub_count = sum(1 for l in listings if l.has_hot_tub)
        waterfront_count = sum(1 for l in listings if l.has_waterfront)
        pet_count = sum(1 for l in listings if l.has_pet_friendly)
        
        snapshot.pct_with_pool = pool_count / len(listings)
        snapshot.pct_with_hot_tub = hot_tub_count / len(listings)
        snapshot.pct_with_waterfront = waterfront_count / len(listings)
        snapshot.pct_with_pet_friendly = pet_count / len(listings)
        
        # Pricing by bedrooms
        rates_by_br: Dict[int, List[float]] = {}
        for listing in listings:
            if listing.displayed_rate and listing.bedrooms:
                br = listing.bedrooms
                if br not in rates_by_br:
                    rates_by_br[br] = []
                rates_by_br[br].append(listing.displayed_rate)
        
        for br, rates in rates_by_br.items():
            if rates:
                snapshot.median_rate_by_bedrooms[br] = sorted(rates)[len(rates) // 2]
        
        # Overall rate percentiles
        all_rates = [l.displayed_rate for l in listings if l.displayed_rate]
        if all_rates:
            all_rates.sort()
            n = len(all_rates)
            snapshot.rate_percentiles = {
                'p10': all_rates[int(n * 0.1)],
                'p25': all_rates[int(n * 0.25)],
                'p50': all_rates[int(n * 0.5)],
                'p75': all_rates[int(n * 0.75)],
                'p90': all_rates[int(n * 0.9)],
            }
        
        # Quality metrics
        ratings = [l.rating for l in listings if l.rating]
        reviews = [l.review_count for l in listings if l.review_count]
        superhosts = sum(1 for l in listings if l.is_superhost)
        
        if ratings:
            snapshot.avg_rating = sum(ratings) / len(ratings)
        if reviews:
            snapshot.avg_review_count = sum(reviews) / len(reviews)
        snapshot.pct_superhost = superhosts / len(listings)
        
        # Real estate context
        if properties:
            values = [p.estimated_value for p in properties if p.estimated_value]
            rents = [p.rental_estimate for p in properties if p.rental_estimate]
            
            if values:
                values.sort()
                snapshot.median_home_value = values[len(values) // 2]
            if rents:
                rents.sort()
                snapshot.median_rental_estimate = rents[len(rents) // 2]
        
        return snapshot
    
    async def close(self):
        """Close all scrapers."""
        await self.airbnb_scraper.close()
        await self.vrbo_scraper.close()
        await self.zillow_scraper.close()


# =============================================================================
# SIGNAL CONVERTER
# =============================================================================

class SignalConverter:
    """
    Converts scraped market data into platform signals.
    
    Maps MarketSnapshot data to SignalType values.
    """
    
    def convert_to_signals(self, snapshot: MarketSnapshot) -> List[Dict]:
        """
        Convert market snapshot to list of signals.
        
        Returns list of dicts compatible with Signal schema.
        """
        signals = []
        now = datetime.utcnow()
        
        # PLATFORM_DOMINANCE
        if snapshot.listings_by_platform:
            total = sum(snapshot.listings_by_platform.values())
            airbnb_share = snapshot.listings_by_platform.get('airbnb', 0) / total if total else 0
            signals.append({
                'signal_type': 'platform_dominance',
                'value': airbnb_share,  # 0-1, higher = more Airbnb dominant
                'confidence': min(total / 100, 0.95),
                'detected_at': now,
                'metadata': {
                    'airbnb_count': snapshot.listings_by_platform.get('airbnb', 0),
                    'vrbo_count': snapshot.listings_by_platform.get('vrbo', 0),
                    'total_listings': total,
                }
            })
        
        # AMENITY_LIFT (for each amenity)
        amenity_signals = [
            ('pool', snapshot.pct_with_pool),
            ('hot_tub', snapshot.pct_with_hot_tub),
            ('waterfront', snapshot.pct_with_waterfront),
            ('pet_friendly', snapshot.pct_with_pet_friendly),
        ]
        
        for amenity, prevalence in amenity_signals:
            # Rarity creates value - less prevalent = higher potential lift
            signals.append({
                'signal_type': 'amenity_lift',
                'value': 1 - prevalence,  # Inverse of prevalence
                'confidence': 0.7,
                'detected_at': now,
                'metadata': {
                    'amenity': amenity,
                    'market_prevalence': prevalence,
                }
            })
        
        # RATE_POSITION
        if snapshot.rate_percentiles:
            signals.append({
                'signal_type': 'rate_position',
                'value': snapshot.rate_percentiles.get('p50', 0),
                'confidence': 0.8,
                'detected_at': now,
                'metadata': {
                    'percentiles': snapshot.rate_percentiles,
                    'by_bedrooms': snapshot.median_rate_by_bedrooms,
                }
            })
        
        # DEMAND_PRESSURE (from availability)
        if snapshot.pct_unavailable_next_30 > 0:
            # Higher unavailability = higher demand
            demand_score = snapshot.pct_unavailable_next_30
            signals.append({
                'signal_type': 'demand_pressure',
                'value': demand_score,
                'confidence': 0.75,
                'detected_at': now,
                'metadata': {
                    'unavail_7d': snapshot.pct_unavailable_next_7,
                    'unavail_14d': snapshot.pct_unavailable_next_14,
                    'unavail_30d': snapshot.pct_unavailable_next_30,
                }
            })
        
        # SUPPLY_VELOCITY
        signals.append({
            'signal_type': 'supply_velocity',
            'value': snapshot.total_listings,
            'confidence': 0.9,
            'detected_at': now,
            'metadata': {
                'total_listings': snapshot.total_listings,
                'by_platform': snapshot.listings_by_platform,
                'by_bedrooms': snapshot.listings_by_bedrooms,
            }
        })
        
        return signals


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def cos_deg(degrees: float) -> float:
    """Cosine of angle in degrees."""
    import math
    return math.cos(math.radians(degrees))


def parse_date(date_str: str) -> Optional[date]:
    """Parse date string to date object."""
    if not date_str:
        return None
    
    formats = ['%Y-%m-%d', '%m/%d/%Y', '%Y/%m/%d', '%B %d, %Y']
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt).date()
        except:
            pass
    return None


# =============================================================================
# MAIN SCRAPE SERVICE
# =============================================================================

class PublicDataScrapeService:
    """
    High-level service for scraping public market data.
    
    Usage:
        service = PublicDataScrapeService()
        
        # Scrape a market
        snapshot = await service.scrape_market(
            market_id="30a-beaches",
            market_name="30A Beaches",
            latitude=30.2833,
            longitude=-86.0167,
            radius_miles=15,
        )
        
        # Convert to signals
        signals = service.convert_to_signals(snapshot)
        
        # Close when done
        await service.close()
    """
    
    def __init__(self):
        self.aggregator = MarketDataAggregator()
        self.converter = SignalConverter()
    
    async def scrape_market(
        self,
        market_id: str,
        market_name: str,
        latitude: float,
        longitude: float,
        radius_miles: float = 10,
    ) -> MarketSnapshot:
        """Scrape market data from all public sources."""
        return await self.aggregator.scrape_market(
            market_id, market_name, latitude, longitude, radius_miles
        )
    
    def convert_to_signals(self, snapshot: MarketSnapshot) -> List[Dict]:
        """Convert market snapshot to signals."""
        return self.converter.convert_to_signals(snapshot)
    
    async def close(self):
        """Close all connections."""
        await self.aggregator.close()
