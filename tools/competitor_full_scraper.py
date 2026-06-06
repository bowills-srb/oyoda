#!/usr/bin/env python3
"""
30A Competitor Full Scraper - WITH PRICING & AVAILABILITY

Uses similar techniques to Beach Habitats scrapers:
- Extract JS config for availability (rcItemAvailForm pattern)
- Intercept AJAX responses for pricing
- Parse embedded calendar data

COMPETITORS BY PMS:
- Oversee: Track PMS (trackhs.com)
- Benchmark: Escapia + Rezfusion (same as BH!)
- 30A Escapes: Custom/InterCoastal
- Exclusive 30A: Unknown

USAGE:
    python competitor_full_scraper.py --company oversee --limit 10
    python competitor_full_scraper.py --company benchmark --limit 10 --with-pricing
    python competitor_full_scraper.py --summary
"""

import argparse
import asyncio
import json
import os
import re
import sys
import random
from dataclasses import dataclass, field, asdict
from datetime import datetime, date, timedelta, timezone
from decimal import Decimal
from typing import List, Dict, Optional, Any, Tuple
from urllib.parse import urljoin

try:
    from playwright.async_api import async_playwright
except ImportError:
    print("ERROR: Playwright required. Run: pip install playwright && playwright install chromium")
    sys.exit(1)

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    HAS_POSTGRES = True
except ImportError:
    HAS_POSTGRES = False
    print("WARNING: psycopg2 not installed.")


DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://rental:rental@localhost:5433/rental_revenue")


# =============================================================================
# COMPETITOR CONFIGURATIONS
# =============================================================================

COMPETITORS = {
    "oversee": {
        "name": "Oversee",
        "base_url": "https://oversee.us",
        "pms": "track",
        "search_urls": [
            "https://oversee.us/area/watercolor/",
            "https://oversee.us/area/rosemary-beach/",
            "https://oversee.us/area/seagrove/",
            "https://oversee.us/area/seacrest/",
            "https://oversee.us/area/watersound/",
            "https://oversee.us/area/inlet-beach/",
            "https://oversee.us/area/grayton-beach/",
        ],
        "listing_pattern": r"/vrp/unit/[\w_-]+",
    },
    "benchmark": {
        "name": "Benchmark Management",
        "base_url": "https://www.benchmark30a.com",
        "pms": "escapia",  # Same as Beach Habitats!
        "search_urls": [
            "https://www.benchmark30a.com/emerald-coast-vacation-rentals/30a",
            "https://www.benchmark30a.com/emerald-coast-vacation-rentals/destin",
            "https://www.benchmark30a.com/emerald-coast-vacation-rentals/panama-city-beach",
        ],
        "listing_pattern": r"/emerald-coast-vacation-rentals/[^/]+$",
    },
}

SUBMARKET_PATTERNS = {
    "watercolor": ["watercolor", "water color"],
    "rosemary_beach": ["rosemary beach", "rosemary"],
    "seaside": ["seaside"],
    "seagrove": ["seagrove", "sea grove"],
    "alys_beach": ["alys beach", "alys"],
    "watersound": ["watersound", "water sound"],
    "seacrest": ["seacrest", "sea crest"],
    "inlet_beach": ["inlet beach", "inlet"],
    "grayton_beach": ["grayton beach", "grayton"],
    "blue_mountain": ["blue mountain"],
    "gulf_place": ["gulf place"],
    "carillon": ["carillon"],
    "destin": ["destin"],
    "miramar": ["miramar"],
}


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class CompetitorProperty:
    source: str
    listing_id: str
    name: str
    url: str
    submarket: Optional[str] = None
    bedrooms: Optional[int] = None
    bathrooms: Optional[float] = None
    sleeps: Optional[int] = None
    has_pool: bool = False
    pool_type: str = "none"
    has_hot_tub: bool = False
    has_view: bool = False
    has_golf_cart: bool = False
    has_bikes: bool = False
    pet_friendly: bool = False
    scraped_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class CompetitorPricing:
    source: str
    listing_id: str
    check_in: date
    check_out: date
    nights: int
    nightly_rate: Optional[Decimal] = None
    total_price: Optional[Decimal] = None
    cleaning_fee: Optional[Decimal] = None
    adr: Optional[Decimal] = None
    scraped_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class CompetitorAvailability:
    source: str
    listing_id: str
    booked_dates: List[str] = field(default_factory=list)
    available_dates: List[str] = field(default_factory=list)
    scraped_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# =============================================================================
# SCRAPER CLASS
# =============================================================================

class CompetitorFullScraper:
    
    def __init__(self, company_key: str):
        if company_key not in COMPETITORS:
            raise ValueError(f"Unknown competitor: {company_key}")
        
        self.company_key = company_key
        self.config = COMPETITORS[company_key]
        self.browser = None
        self.context = None
        self.page = None
    
    async def setup(self):
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=True)
        self.context = await self.browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        )
        self.page = await self.context.new_page()
        self.request_count = 0
        self.last_request_time = None
    
    async def cleanup(self):
        if self.browser:
            await self.browser.close()
        if hasattr(self, 'playwright') and self.playwright:
            await self.playwright.stop()
    
    async def _rate_limit(self):
        """Respectful rate limiting to avoid getting blocked."""
        self.request_count += 1
        
        # Every 50 requests, take a longer break
        if self.request_count % 50 == 0:
            print(f"\n   ⏸️  Rate limit pause ({self.request_count} requests)...")
            await asyncio.sleep(30)  # 30 second break
            # Refresh browser context to get new connection
            await self.context.close()
            self.context = await self.browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            )
            self.page = await self.context.new_page()
        
        # Normal delay between requests
        await asyncio.sleep(random.uniform(3.0, 6.0))
    
    async def scrape_all(
        self, 
        limit: Optional[int] = None,
        with_pricing: bool = False,
        with_availability: bool = False,
    ) -> Tuple[List[CompetitorProperty], List[CompetitorPricing], List[CompetitorAvailability]]:
        
        print(f"\n{'='*60}")
        print(f"🏠 SCRAPING: {self.config['name']}")
        print(f"   PMS: {self.config.get('pms', 'unknown')}")
        print(f"   Pricing: {'YES' if with_pricing else 'NO'}")
        print(f"   Availability: {'YES' if with_availability else 'NO'}")
        print(f"{'='*60}")
        
        await self.setup()
        
        try:
            # Get listing URLs with submarkets
            print(f"\n📄 Finding property listings...")
            listing_data = await self._get_listing_urls()  # Returns [(url, submarket), ...]
            print(f"   Found {len(listing_data)} listings")
            
            if limit:
                listing_data = listing_data[:limit]
                print(f"   Limited to {limit} for testing")
            
            # Scrape each listing
            properties = []
            pricing_quotes = []
            availability_data = []
            
            for i, (url, area_submarket) in enumerate(listing_data):
                print(f"\n📍 [{i+1}/{len(listing_data)}] {url.split('/')[-1][:40]}...")
                
                try:
                    # Get property details + availability
                    prop, avail = await self._scrape_property_full(url, area_submarket=area_submarket)
                    
                    if prop:
                        properties.append(prop)
                        pool_str = f"🏊{prop.pool_type}" if prop.pool_type != 'none' else "no pool"
                        print(f"   ✅ {prop.name[:25]} | {prop.bedrooms}BR | {prop.submarket} | {pool_str}")
                        
                        if avail and (avail.booked_dates or avail.available_dates):
                            availability_data.append(avail)
                            total_dates = len(avail.booked_dates) + len(avail.available_dates)
                            if total_dates > 0:
                                booked_pct = len(avail.booked_dates) / total_dates
                                print(f"      📅 {len(avail.booked_dates)} booked / {total_dates} dates ({booked_pct:.0%})")
                        
                        # Get pricing
                        if with_pricing:
                            quotes = await self._scrape_pricing(url, prop.listing_id)
                            if quotes:
                                pricing_quotes.extend(quotes)
                                avg_rate = sum(float(q.nightly_rate or 0) for q in quotes) / len(quotes)
                                print(f"      💰 {len(quotes)} quotes, avg ${avg_rate:.0f}/night")
                    
                    # Rate limiting
                    await self._rate_limit()
                    
                except Exception as e:
                    print(f"   ❌ Error: {str(e)[:60]}")
                    continue
            
            print(f"\n{'='*60}")
            print(f"✅ COMPLETE: {len(properties)} properties, {len(pricing_quotes)} quotes")
            print(f"{'='*60}")
            
            return properties, pricing_quotes, availability_data
            
        finally:
            await self.cleanup()
    
    async def _get_listing_urls(self) -> List[Tuple[str, Optional[str]]]:
        """Returns list of (url, submarket) tuples."""
        urls = {}  # url -> submarket
        base_url = self.config['base_url']
        pms = self.config.get('pms', 'unknown')
        
        for search_url in self.config.get('search_urls', []):
            # Extract submarket from search URL
            area_slug = search_url.rstrip('/').split('/')[-1]
            area_to_submarket = {
                'watercolor': 'watercolor',
                'rosemary-beach': 'rosemary_beach',
                'seagrove': 'seagrove',
                'seacrest': 'seacrest',
                'watersound': 'watersound',
                'inlet-beach': 'inlet_beach',
                'grayton-beach': 'grayton_beach',
                'seaside': 'seaside',
                'alys-beach': 'alys_beach',
                '30a': None,
                'destin': 'destin',
                'panama-city-beach': None,
            }
            area_submarket = area_to_submarket.get(area_slug)
            
            print(f"   Checking: {area_slug}")
            try:
                await self.page.goto(search_url, wait_until='domcontentloaded', timeout=20000)
                await asyncio.sleep(2)
                
                # Scroll to load more
                for _ in range(3):
                    await self.page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                    await asyncio.sleep(1)
                
                # PMS-specific link extraction
                if pms == 'track':
                    links = await self.page.query_selector_all('a[href*="/vrp/unit/"]')
                    for link in links:
                        try:
                            href = await link.get_attribute('href')
                            if href:
                                match = re.search(r'/vrp/unit/([\w_-]+)', href)
                                if match:
                                    listing_id = match.group(1)
                                    clean_url = f"{base_url}/vrp/unit/{listing_id}"
                                    # Only set submarket if not already set (first area wins)
                                    if clean_url not in urls:
                                        urls[clean_url] = area_submarket
                        except:
                            continue
                
                elif pms == 'escapia':
                    # Benchmark uses /emerald-coast-vacation-rentals/{slug} pattern
                    links = await self.page.query_selector_all('a[href*="/emerald-coast-vacation-rentals/"]')
                    for link in links:
                        try:
                            href = await link.get_attribute('href')
                            if href and '/emerald-coast-vacation-rentals/' in href:
                                full_url = urljoin(base_url, href)
                                clean_url = full_url.split('?')[0]
                                # Skip category pages
                                slug = clean_url.rstrip('/').split('/')[-1]
                                skip_slugs = ['30a', 'destin', 'panama-city-beach', 'large-group-vacation-rentals', 
                                             'pet-friendly', 'pool', 'beachfront', 'gulf-view', 'luxury',
                                             'condominium', 'private-home', 'golf-cart', 'destin-miramar-beach',
                                             'beachfront-vacation-rentals', 'new-listings', 'specials']
                                if slug not in skip_slugs and len(clean_url) < 200:
                                    if clean_url not in urls:
                                        urls[clean_url] = area_submarket
                        except:
                            continue
                
                print(f"      Found {len(urls)} total")
                
            except Exception as e:
                print(f"   ⚠️ Error: {str(e)[:40]}")
                continue
        
        # Return as list of tuples
        return [(url, submarket) for url, submarket in urls.items()]
    
    async def _scrape_property_full(self, url: str, retries: int = 2, area_submarket: Optional[str] = None) -> Tuple[Optional[CompetitorProperty], Optional[CompetitorAvailability]]:
        """Scrape property details AND availability from embedded JS."""
        
        for attempt in range(retries + 1):
            try:
                await self.page.goto(url, wait_until='domcontentloaded', timeout=25000)
                await asyncio.sleep(2)
                break
            except Exception as e:
                if attempt < retries:
                    wait_time = (attempt + 1) * 10  # 10s, 20s
                    print(f"      ↻ Retry {attempt + 1}/{retries} in {wait_time}s...")
                    await asyncio.sleep(wait_time)
                else:
                    raise e
        
        html = await self.page.content()
        text = await self.page.inner_text('body')
        text_lower = text.lower()
        
        pms = self.config.get('pms', 'unknown')
        
        # Extract listing ID
        if pms == 'track':
            match = re.search(r'/vrp/unit/([\w_-]+)', url)
            listing_id = match.group(1) if match else url.split('/')[-1]
        else:
            listing_id = url.rstrip('/').split('/')[-1]
        
        # Extract name
        name = listing_id.replace('_', ' ').replace('-', ' ')
        name = re.sub(r'\s+\d+\s*\d*$', '', name).strip()
        
        try:
            h1 = await self.page.query_selector('h1')
            if h1:
                h1_text = (await h1.inner_text()).strip()
                if h1_text and 3 < len(h1_text) < 80 and '<' not in h1_text:
                    name = h1_text
        except:
            pass
        
        # Extract details - try multiple patterns
        # Also search in HTML for structured data
        html_lower = html.lower()
        
        bedrooms = self._extract_number(text_lower + ' ' + html_lower, [
            r'(\d+)\s*br\b',
            r'(\d+)\s*bed(?:room)?s?',
            r'boasting\s*(\d+)\s*bed',
            r'>(\d+)\s*br<',  # HTML: >4 BR<
            r'(\d+)\s*bedroom',
        ])
        bathrooms = self._extract_number(text_lower + ' ' + html_lower, [
            r'(\d+(?:\.\d+)?)\s*ba\b',
            r'(\d+(?:\.\d+)?)\s*bath',
            r'>(\d+(?:\.\d+)?)\s*ba<',  # HTML: >3.5 BA<
        ])
        sleeps = self._extract_number(text_lower + ' ' + html_lower, [
            r'sleeps\s*(\d+)',
            r'(\d+)\s*guests?',
            r'accommodates?\s*(?:up\s*to\s*)?(\d+)',
            r'>(\d+)\s*guests?<',  # HTML: >14 Guests<
        ])
        
        # Detect submarket - use area_submarket from URL if available, otherwise detect from content
        submarket = area_submarket or self._detect_submarket(name + ' ' + url + ' ' + text_lower)
        
        # Detect amenities - check both text and HTML for structured amenity lists
        search_text = text_lower + ' ' + html_lower
        
        # POOL DETECTION - Private vs Community
        # Private pool indicators (the property has its own pool)
        private_pool_indicators = [
            'private pool', 'pvt pool', 'own pool', 'personal pool',
            'private heated pool', 'heated private pool',
            'pool (heated', 'pool heated',  # Often means private
            'plunge pool', 'splash pool', 'dipping pool',
        ]
        # Community pool indicators (shared amenity access)
        community_pool_indicators = [
            'community pool', 'neighborhood pool', 'hoa pool',
            'access to pool', 'pool access', 'amenity pool',
            'camp watercolor', 'watercolor pool', 'beach club pool',
            'dragonfly pool', 'frog pool',  # WaterColor community pools
        ]
        
        has_private_pool = any(indicator in search_text for indicator in private_pool_indicators)
        has_community_pool = any(indicator in search_text for indicator in community_pool_indicators)
        
        # Determine pool_type: private > community > none
        # Only mark has_pool=True if there's a PRIVATE pool (valuable amenity)
        # Community pool access is assumed for most 30A properties
        if has_private_pool:
            pool_type = 'private'
            has_pool = True
        elif has_community_pool:
            pool_type = 'community'
            has_pool = False  # Community pool access is common, not a differentiator
        else:
            pool_type = 'none'
            has_pool = False
        
        has_hot_tub = 'hot tub' in search_text or 'jacuzzi' in search_text or 'spa' in search_text
        has_view = 'gulf view' in search_text or 'ocean view' in search_text or 'beach view' in search_text or 'beachfront' in search_text
        has_golf_cart = 'golf cart' in search_text
        has_bikes = bool(re.search(r'\d+\s*bikes?', search_text)) or 'bike' in search_text
        pet_friendly = 'pet friendly' in search_text or 'pets allowed' in search_text or 'dog friendly' in search_text or 'dog-friendly' in search_text
        
        prop = CompetitorProperty(
            source=self.company_key,
            listing_id=listing_id,
            name=name,
            url=url,
            submarket=submarket,
            bedrooms=bedrooms,
            bathrooms=bathrooms,
            sleeps=sleeps,
            has_pool=has_pool,  # Only True for PRIVATE pools
            pool_type=pool_type,
            has_hot_tub=has_hot_tub,
            has_view=has_view,
            has_golf_cart=has_golf_cart,
            has_bikes=has_bikes,
            pet_friendly=pet_friendly,
        )
        
        # Extract availability from embedded JS
        avail = await self._extract_availability_from_js(html, listing_id)
        
        return prop, avail
    
    async def _extract_availability_from_js(self, html: str, listing_id: str) -> Optional[CompetitorAvailability]:
        """Extract availability from embedded JavaScript config."""
        
        booked_dates = []
        available_dates = []
        
        pms = self.config.get('pms', 'unknown')
        
        if pms == 'track':
            # Track PMS embeds availability in JavaScript
            # Look for unavailable dates array
            patterns = [
                r'"unavailable"\s*:\s*\[(.*?)\]',
                r"'unavailable'\s*:\s*\[(.*?)\]",
                r'"blocked"\s*:\s*\[(.*?)\]',
                r'"booked"\s*:\s*\[(.*?)\]',
            ]
            
            for pattern in patterns:
                match = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
                if match:
                    dates_str = match.group(1)
                    date_matches = re.findall(r'["\'](\d{4}-\d{2}-\d{2})["\']', dates_str)
                    booked_dates.extend(date_matches)
        
        elif pms == 'escapia':
            # Escapia uses rcItemAvailForm pattern (same as Beach Habitats!)
            # Look for avail array with 'a':'0' (unavailable) or 'a':'1' (available)
            avail_match = re.search(r"'avail'\s*:\s*\[([\s\S]*?)\]", html)
            if avail_match:
                avail_str = avail_match.group(1)
                # Parse each range: {'b':'2026-03-01','e':'2026-03-05','a':'0'}
                for m in re.finditer(r"\{'b':'([^']+)','e':'([^']+)','a':'([^']+)'", avail_str):
                    start_str, end_str, avail = m.groups()
                    try:
                        start = datetime.strptime(start_str, '%Y-%m-%d').date()
                        end = datetime.strptime(end_str, '%Y-%m-%d').date()
                        is_available = avail == '1'
                        
                        current = start
                        while current <= end:
                            if is_available:
                                available_dates.append(current.isoformat())
                            else:
                                booked_dates.append(current.isoformat())
                            current += timedelta(days=1)
                    except:
                        continue
        
        # Deduplicate and sort
        booked_dates = sorted(list(set(booked_dates)))
        available_dates = sorted(list(set(available_dates)))
        
        if booked_dates or available_dates:
            return CompetitorAvailability(
                source=self.company_key,
                listing_id=listing_id,
                booked_dates=booked_dates,
                available_dates=available_dates,
            )
        
        return None
    
    async def _scrape_pricing(self, url: str, listing_id: str) -> List[CompetitorPricing]:
        """Scrape pricing by intercepting AJAX responses or parsing page."""
        
        quotes = []
        today = date.today()
        pms = self.config.get('pms', 'unknown')
        
        # Store captured pricing responses
        pricing_responses = []
        
        async def capture_pricing_response(response):
            try:
                resp_url = response.url.lower()
                if any(x in resp_url for x in ['pricing', 'quote', 'rate', 'avail']):
                    if response.status == 200:
                        try:
                            body = await response.text()
                            if '$' in body or 'total' in body.lower():
                                pricing_responses.append(body)
                        except:
                            pass
            except:
                pass
        
        self.page.on('response', capture_pricing_response)
        
        try:
            # Reload page to capture any initial pricing
            await self.page.goto(url, wait_until='domcontentloaded', timeout=15000)
            await asyncio.sleep(2)
            
            html = await self.page.content()
            
            if pms == 'escapia':
                # Escapia: Find available ranges and set dates via JS
                avail_ranges = []
                for m in re.finditer(r"\{'b':'([^']+)','e':'([^']+)','a':'1'", html):
                    avail_ranges.append((m.group(1), m.group(2)))
                
                for start_str, end_str in avail_ranges[:2]:  # Try first 2 ranges
                    try:
                        start = datetime.strptime(start_str, '%Y-%m-%d').date()
                        end = datetime.strptime(end_str, '%Y-%m-%d').date()
                        
                        if end <= today or (end - start).days < 3:
                            continue
                        
                        check_in = max(start, today + timedelta(days=1))
                        check_out = min(check_in + timedelta(days=3), end)
                        nights = (check_out - check_in).days
                        
                        if nights < 3:
                            continue
                        
                        # Set dates via JavaScript (Escapia pattern)
                        begin_fmt = check_in.strftime('%m/%d/%Y')
                        end_fmt = check_out.strftime('%m/%d/%Y')
                        
                        pricing_responses.clear()
                        
                        await self.page.evaluate(f"""
                            () => {{
                                const b = document.querySelector('input.begin, input[name*="checkin"], input[name*="check_in"]');
                                const e = document.querySelector('input.end, input[name*="checkout"], input[name*="check_out"]');
                                if (b && e) {{
                                    b.value = '{begin_fmt}';
                                    e.value = '{end_fmt}';
                                    b.dispatchEvent(new Event('change', {{bubbles: true}}));
                                    e.dispatchEvent(new Event('change', {{bubbles: true}}));
                                }}
                            }}
                        """)
                        
                        await asyncio.sleep(2)
                        
                        # Parse captured responses
                        for resp in pricing_responses:
                            parsed = self._parse_pricing_response(resp)
                            if parsed and parsed.get('total', 0) > 0:
                                lodging = Decimal(str(parsed.get('lodging', 0)))
                                total = Decimal(str(parsed['total']))
                                adr = lodging / nights if lodging > 0 else total / nights * Decimal("0.85")
                                
                                quotes.append(CompetitorPricing(
                                    source=self.company_key,
                                    listing_id=listing_id,
                                    check_in=check_in,
                                    check_out=check_out,
                                    nights=nights,
                                    nightly_rate=adr,
                                    total_price=total,
                                    cleaning_fee=Decimal(str(parsed.get('cleaning', 0))),
                                    adr=adr,
                                ))
                                break
                    except:
                        continue
            
            else:
                # Generic: Try to find pricing in page text
                text = await self.page.inner_text('body')
                
                # Look for nightly rate pattern
                match = re.search(r'\$\s*([\d,]+)\s*(?:/|per)\s*night', text, re.IGNORECASE)
                if match:
                    rate = Decimal(match.group(1).replace(',', ''))
                    if 50 < rate < 5000:
                        quotes.append(CompetitorPricing(
                            source=self.company_key,
                            listing_id=listing_id,
                            check_in=today + timedelta(days=14),
                            check_out=today + timedelta(days=17),
                            nights=3,
                            nightly_rate=rate,
                            adr=rate,
                        ))
        
        finally:
            self.page.remove_listener('response', capture_pricing_response)
        
        return quotes
    
    def _parse_pricing_response(self, content: str) -> Dict:
        """Parse pricing from AJAX response content."""
        result = {'lodging': 0, 'taxes': 0, 'total': 0, 'cleaning': 0}
        
        # Unescape
        content = content.replace('\\u003C', '<').replace('\\u003E', '>')
        content = content.replace('\\u0022', '"').replace('\\/', '/')
        
        # Find lodging
        m = re.search(r'Lodging[^$]*\$([\d,]+(?:\.\d{2})?)', content, re.I)
        if m:
            result['lodging'] = float(m.group(1).replace(',', ''))
        
        # Find taxes
        m = re.search(r'(?:Tax|Taxes)[^$]*\$([\d,]+(?:\.\d{2})?)', content, re.I)
        if m:
            result['taxes'] = float(m.group(1).replace(',', ''))
        
        # Find cleaning
        m = re.search(r'Clean[^$]*\$([\d,]+(?:\.\d{2})?)', content, re.I)
        if m:
            result['cleaning'] = float(m.group(1).replace(',', ''))
        
        # Total is usually largest amount
        amounts = re.findall(r'\$([\d,]+(?:\.\d{2})?)', content)
        if amounts:
            parsed = [float(a.replace(',', '')) for a in amounts]
            result['total'] = max(parsed)
        
        return result
    
    def _extract_number(self, text: str, patterns: List[str]) -> Optional[int]:
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                try:
                    return int(float(match.group(1)))
                except:
                    pass
        return None
    
    def _detect_submarket(self, text: str) -> Optional[str]:
        text = text.lower()
        for submarket, patterns in SUBMARKET_PATTERNS.items():
            for pattern in patterns:
                if pattern in text:
                    return submarket
        return None


# =============================================================================
# DATABASE
# =============================================================================

def save_to_database(
    properties: List[CompetitorProperty],
    pricing: List[CompetitorPricing] = None,
    availability: List[CompetitorAvailability] = None,
) -> Dict[str, int]:
    
    if not HAS_POSTGRES:
        return {"error": "psycopg2 not installed"}
    
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    
    results = {"properties": 0, "pricing": 0, "availability": 0, "errors": 0}
    
    # Make sure lat/lng allow NULL
    try:
        cur.execute("""
            ALTER TABLE external_listings 
            ALTER COLUMN latitude DROP NOT NULL,
            ALTER COLUMN longitude DROP NOT NULL
        """)
        conn.commit()
    except:
        conn.rollback()
    
    # Save properties
    for prop in properties:
        try:
            if '<' in prop.listing_id or len(prop.listing_id) > 100:
                continue
            
            cur.execute("""
                INSERT INTO external_listings (
                    listing_id, source, market_id, submarket_id,
                    bedrooms, bathrooms, sleeps, property_type,
                    has_pool, pool_type, has_hot_tub, has_view,
                    pet_friendly, listing_url, title, scraped_at, is_active
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                ON CONFLICT (source, listing_id) DO UPDATE SET
                    bedrooms = COALESCE(EXCLUDED.bedrooms, external_listings.bedrooms),
                    bathrooms = COALESCE(EXCLUDED.bathrooms, external_listings.bathrooms),
                    sleeps = COALESCE(EXCLUDED.sleeps, external_listings.sleeps),
                    has_pool = EXCLUDED.has_pool,
                    has_hot_tub = EXCLUDED.has_hot_tub,
                    has_view = EXCLUDED.has_view,
                    submarket_id = COALESCE(EXCLUDED.submarket_id, external_listings.submarket_id),
                    title = COALESCE(EXCLUDED.title, external_listings.title),
                    last_updated = NOW()
            """, (
                prop.listing_id, prop.source, '30a_fl', prop.submarket,
                prop.bedrooms, prop.bathrooms, prop.sleeps, 'house',
                prop.has_pool, prop.pool_type, prop.has_hot_tub, prop.has_view,
                prop.pet_friendly, prop.url, prop.name, prop.scraped_at, True,
            ))
            conn.commit()
            results["properties"] += 1
        except Exception as e:
            conn.rollback()
            results["errors"] += 1
    
    # Save pricing
    if pricing:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS competitor_pricing (
                id SERIAL PRIMARY KEY,
                source VARCHAR(50) NOT NULL,
                listing_id VARCHAR(200) NOT NULL,
                check_in DATE NOT NULL,
                check_out DATE NOT NULL,
                nights INTEGER,
                nightly_rate DECIMAL(10, 2),
                total_price DECIMAL(10, 2),
                cleaning_fee DECIMAL(10, 2),
                adr DECIMAL(10, 2),
                scraped_at TIMESTAMP DEFAULT NOW(),
                CONSTRAINT competitor_pricing_unique UNIQUE (source, listing_id, check_in, check_out)
            )
        """)
        conn.commit()
        
        for quote in pricing:
            try:
                cur.execute("""
                    INSERT INTO competitor_pricing (
                        source, listing_id, check_in, check_out, nights,
                        nightly_rate, total_price, cleaning_fee, adr, scraped_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (source, listing_id, check_in, check_out) DO UPDATE SET
                        nightly_rate = EXCLUDED.nightly_rate,
                        total_price = EXCLUDED.total_price,
                        adr = EXCLUDED.adr,
                        scraped_at = EXCLUDED.scraped_at
                """, (
                    quote.source, quote.listing_id, quote.check_in, quote.check_out,
                    quote.nights, quote.nightly_rate, quote.total_price,
                    quote.cleaning_fee, quote.adr, quote.scraped_at,
                ))
                conn.commit()
                results["pricing"] += 1
            except:
                conn.rollback()
        
        # Update avg_adr on external_listings
        cur.execute("""
            UPDATE external_listings e
            SET avg_adr = p.avg_adr
            FROM (
                SELECT source, listing_id, ROUND(AVG(adr)::numeric, 2) as avg_adr
                FROM competitor_pricing
                WHERE adr > 0
                GROUP BY source, listing_id
            ) p
            WHERE e.source = p.source AND e.listing_id = p.listing_id
        """)
        conn.commit()
    
    # Save availability
    if availability:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS competitor_availability (
                id SERIAL PRIMARY KEY,
                source VARCHAR(50) NOT NULL,
                listing_id VARCHAR(200) NOT NULL,
                booked_dates JSONB,
                available_dates JSONB,
                scraped_at TIMESTAMP DEFAULT NOW(),
                CONSTRAINT competitor_availability_unique UNIQUE (source, listing_id)
            )
        """)
        conn.commit()
        
        for avail in availability:
            try:
                cur.execute("""
                    INSERT INTO competitor_availability (
                        source, listing_id, booked_dates, available_dates, scraped_at
                    ) VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (source, listing_id) DO UPDATE SET
                        booked_dates = EXCLUDED.booked_dates,
                        available_dates = EXCLUDED.available_dates,
                        scraped_at = EXCLUDED.scraped_at
                """, (
                    avail.source, avail.listing_id,
                    json.dumps(avail.booked_dates),
                    json.dumps(avail.available_dates),
                    avail.scraped_at,
                ))
                conn.commit()
                results["availability"] += 1
            except:
                conn.rollback()
    
    cur.close()
    conn.close()
    return results


def get_competitor_summary() -> Dict[str, Any]:
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    cur = conn.cursor()
    
    cur.execute("""
        SELECT 
            source,
            COUNT(*) as count,
            COUNT(*) FILTER (WHERE has_pool AND pool_type = 'private') as private_pool,
            COUNT(*) FILTER (WHERE pool_type = 'community') as community_pool,
            COUNT(*) FILTER (WHERE has_hot_tub) as with_hot_tub,
            COUNT(*) FILTER (WHERE has_view) as with_view,
            ROUND(AVG(bedrooms)::numeric, 1) as avg_beds,
            ROUND(AVG(avg_adr)::numeric, 0) as avg_adr
        FROM external_listings
        WHERE is_active = true
        GROUP BY source
        ORDER BY count DESC
    """)
    by_source = [dict(r) for r in cur.fetchall()]
    
    cur.execute("""
        SELECT 
            submarket_id,
            COUNT(*) as count,
            ROUND(AVG(avg_adr)::numeric, 0) as avg_adr,
            COUNT(*) FILTER (WHERE pool_type = 'private') as private_pool,
            COUNT(*) FILTER (WHERE pool_type = 'community') as community_pool
        FROM external_listings
        WHERE is_active = true AND submarket_id IS NOT NULL
        GROUP BY submarket_id
        ORDER BY count DESC
    """)
    by_submarket = [dict(r) for r in cur.fetchall()]
    
    # Pricing summary
    pricing_summary = None
    try:
        cur.execute("""
            SELECT 
                COUNT(*) as quote_count,
                ROUND(AVG(nightly_rate)::numeric, 0) as avg_rate,
                ROUND(MIN(nightly_rate)::numeric, 0) as min_rate,
                ROUND(MAX(nightly_rate)::numeric, 0) as max_rate
            FROM competitor_pricing
        """)
        row = cur.fetchone()
        if row and row['quote_count'] > 0:
            pricing_summary = dict(row)
    except:
        pass
    
    cur.close()
    conn.close()
    
    return {
        "by_source": by_source,
        "by_submarket": by_submarket,
        "pricing_summary": pricing_summary,
        "total": sum(s['count'] for s in by_source),
    }


# =============================================================================
# MAIN
# =============================================================================

async def main():
    parser = argparse.ArgumentParser(description="Scrape competitor PM websites")
    parser.add_argument("--company", choices=list(COMPETITORS.keys()), help="Competitor to scrape")
    parser.add_argument("--limit", type=int, help="Limit number of properties")
    parser.add_argument("--save-to-db", action="store_true", help="Save to database")
    parser.add_argument("--with-pricing", action="store_true", help="Also scrape pricing (slower)")
    parser.add_argument("--with-availability", action="store_true", help="Also scrape availability")
    parser.add_argument("--summary", action="store_true", help="Show database summary")
    parser.add_argument("--output", help="Output JSON file")
    
    args = parser.parse_args()
    
    if args.summary:
        summary = get_competitor_summary()
        print("\n📊 COMPETITOR DATA SUMMARY")
        print(json.dumps(summary, indent=2, default=str))
        return
    
    if not args.company:
        parser.print_help()
        return
    
    scraper = CompetitorFullScraper(args.company)
    properties, pricing, availability = await scraper.scrape_all(
        limit=args.limit,
        with_pricing=args.with_pricing,
        with_availability=True,  # Always get availability from JS
    )
    
    if args.save_to_db:
        results = save_to_database(properties, pricing, availability)
        print(f"\n💾 Saved to DB: {results}")
    
    if args.output:
        output = {
            "properties": [asdict(p) for p in properties],
            "pricing": [asdict(p) for p in pricing],
            "availability": [asdict(a) for a in availability],
            "scraped_at": datetime.now(timezone.utc).isoformat(),
        }
        with open(args.output, 'w') as f:
            json.dump(output, f, indent=2, default=str)
        print(f"\n📄 Saved to {args.output}")
    
    # Summary
    print(f"\n📊 SCRAPE SUMMARY")
    print(f"Properties: {len(properties)}")
    print(f"Pricing quotes: {len(pricing)}")
    print(f"With availability: {len(availability)}")
    
    if properties:
        private_pools = sum(1 for p in properties if p.pool_type == 'private')
        community_pools = sum(1 for p in properties if p.pool_type == 'community')
        no_pool = sum(1 for p in properties if p.pool_type == 'none')
        print(f"Pool types: {private_pools} private, {community_pools} community, {no_pool} none")
        print(f"has_pool=True: {sum(1 for p in properties if p.has_pool)} (only private pools count)")
        
        by_submarket = {}
        for p in properties:
            sm = p.submarket or "unknown"
            by_submarket[sm] = by_submarket.get(sm, 0) + 1
        print(f"By submarket: {by_submarket}")
    
    if pricing:
        avg_rate = sum(float(q.nightly_rate or 0) for q in pricing) / len(pricing)
        print(f"Avg nightly rate: ${avg_rate:.0f}")


if __name__ == "__main__":
    asyncio.run(main())
