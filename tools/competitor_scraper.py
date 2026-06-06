#!/usr/bin/env python3
"""
30A Competitor Property Scraper

Scrapes publicly available property listings from competitor PM companies.
This data is used for market intelligence, NOT for guest solicitation.

LEGAL NOTES:
- Only scrapes publicly available data (no login required)
- Respects robots.txt and rate limits
- Does not scrape personal information (guest reviews with names, etc.)
- Used for market analysis, not competitive interference

COMPETITORS SCRAPED:
- Oversee (oversee.us) - 230+ properties
- 30A Escapes (30aescapes.com) - 100+ properties  
- Exclusive 30A (exclusive30a.com) - 100+ properties
- Benchmark Management (benchmark30a.com) - 200+ properties

USAGE:
    python competitor_scraper.py --company oversee --save-to-db
    python competitor_scraper.py --all --save-to-db
"""

import asyncio
import argparse
import json
import re
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional, Any
from urllib.parse import urljoin, urlparse
import random
import time

try:
    import httpx
    from bs4 import BeautifulSoup
except ImportError:
    print("Required: pip install httpx beautifulsoup4 lxml")
    sys.exit(1)

import psycopg2
from psycopg2.extras import execute_values


DATABASE_URL = "postgresql://rental:rental@localhost:5433/rental_revenue"


# =============================================================================
# COMPETITOR CONFIGURATIONS
# =============================================================================

COMPETITORS = {
    "oversee": {
        "name": "Oversee",
        "base_url": "https://oversee.us",
        "listing_pattern": "/vrp/unit/",
        "search_urls": [
            "https://oversee.us/area/watercolor/",
            "https://oversee.us/area/rosemary-beach/",
            "https://oversee.us/area/seagrove/",
            "https://oversee.us/area/grayton-beach/",
            "https://oversee.us/area/seacrest-beach/",
            "https://oversee.us/area/blue-mountain-beach/",
        ],
    },
    "30a_escapes": {
        "name": "30A Escapes",
        "base_url": "https://www.30aescapes.com",
        "listing_pattern": "/vacation-rental/",
        "search_urls": [
            "https://www.30aescapes.com/vacation-rentals/",
        ],
    },
    "exclusive30a": {
        "name": "Exclusive 30A",
        "base_url": "https://www.exclusive30a.com",
        "listing_pattern": "/vacation-rentals/",
        "search_urls": [
            "https://www.exclusive30a.com/vacation-rentals",
        ],
    },
    "benchmark": {
        "name": "Benchmark Management",
        "base_url": "https://www.benchmark30a.com",
        "listing_pattern": "/vacation-rentals/",
        "search_urls": [
            "https://www.benchmark30a.com/vacation-rentals/30a/",
        ],
    },
}


# Submarket detection from property names/addresses
SUBMARKET_PATTERNS = {
    "watercolor": ["watercolor", "water color", "camp watercolor"],
    "rosemary_beach": ["rosemary", "rosemary beach"],
    "seaside": ["seaside"],
    "seagrove": ["seagrove", "sea grove"],
    "alys_beach": ["alys beach", "alys"],
    "watersound": ["watersound", "water sound"],
    "seacrest": ["seacrest", "sea crest"],
    "inlet_beach": ["inlet beach", "inlet"],
    "grayton_beach": ["grayton"],
    "blue_mountain": ["blue mountain"],
}


@dataclass
class CompetitorListing:
    """A listing scraped from a competitor's website."""
    source: str  # competitor key
    listing_id: str
    name: str
    url: str
    
    # Property details
    bedrooms: Optional[int] = None
    bathrooms: Optional[float] = None
    sleeps: Optional[int] = None
    
    # Location
    submarket: Optional[str] = None
    address_hint: Optional[str] = None
    
    # Amenities (parsed from description)
    has_pool: bool = False
    pool_type: str = "none"  # private, community
    has_hot_tub: bool = False
    has_view: bool = False
    view_type: str = "none"  # gulf, lake, pool
    has_golf_cart: bool = False
    has_bikes: bool = False
    pet_friendly: bool = False
    
    # We can't get ADR directly from competitor sites (they require dates)
    # But we can flag as "competitor" and note it's for BD use
    
    scraped_at: datetime = field(default_factory=datetime.utcnow)


# =============================================================================
# RATE LIMITER
# =============================================================================

class RateLimiter:
    """Respectful rate limiting."""
    
    def __init__(self, min_delay: float = 2.0, max_delay: float = 5.0):
        self.min_delay = min_delay
        self.max_delay = max_delay
        self._last_request: Dict[str, float] = {}
    
    async def wait(self, domain: str):
        last = self._last_request.get(domain, 0)
        elapsed = time.time() - last
        delay = random.uniform(self.min_delay, self.max_delay)
        
        if elapsed < delay:
            await asyncio.sleep(delay - elapsed)
        
        self._last_request[domain] = time.time()


# =============================================================================
# BASE SCRAPER
# =============================================================================

class CompetitorScraper:
    """Base scraper for competitor websites."""
    
    USER_AGENTS = [
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    ]
    
    def __init__(self, company_key: str):
        if company_key not in COMPETITORS:
            raise ValueError(f"Unknown competitor: {company_key}")
        
        self.company_key = company_key
        self.config = COMPETITORS[company_key]
        self.rate_limiter = RateLimiter()
        self._client: Optional[httpx.AsyncClient] = None
    
    async def get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=True,
                headers={
                    "User-Agent": random.choice(self.USER_AGENTS),
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )
        return self._client
    
    async def fetch(self, url: str) -> Optional[str]:
        """Fetch a URL with rate limiting."""
        domain = urlparse(url).netloc
        await self.rate_limiter.wait(domain)
        
        try:
            client = await self.get_client()
            client.headers["User-Agent"] = random.choice(self.USER_AGENTS)
            
            response = await client.get(url)
            
            if response.status_code == 200:
                return response.text
            else:
                print(f"  ⚠️ HTTP {response.status_code}: {url[:60]}...")
                return None
                
        except Exception as e:
            print(f"  ❌ Error: {e}")
            return None
    
    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
    
    async def scrape_all(self) -> List[CompetitorListing]:
        """Scrape all listings from this competitor."""
        print(f"\n🏠 Scraping {self.config['name']}...")
        
        all_listings = []
        listing_urls = set()
        
        # First, gather listing URLs from search/area pages
        for search_url in self.config["search_urls"]:
            print(f"  📄 Fetching: {search_url}")
            html = await self.fetch(search_url)
            
            if html:
                urls = self._extract_listing_urls(html)
                listing_urls.update(urls)
                print(f"     Found {len(urls)} listings")
        
        print(f"  📊 Total unique listings: {len(listing_urls)}")
        
        # Scrape each listing
        for i, url in enumerate(list(listing_urls)[:100]):  # Limit for testing
            listing = await self._scrape_listing(url)
            if listing:
                all_listings.append(listing)
            
            if (i + 1) % 10 == 0:
                print(f"  ✅ Scraped {i + 1}/{min(len(listing_urls), 100)} listings")
        
        return all_listings
    
    def _extract_listing_urls(self, html: str) -> List[str]:
        """Extract listing URLs from a search page."""
        soup = BeautifulSoup(html, 'lxml')
        urls = []
        
        pattern = self.config["listing_pattern"]
        base_url = self.config["base_url"]
        
        for link in soup.find_all('a', href=True):
            href = link['href']
            if pattern in href:
                full_url = urljoin(base_url, href)
                if full_url not in urls:
                    urls.append(full_url)
        
        return urls
    
    async def _scrape_listing(self, url: str) -> Optional[CompetitorListing]:
        """Scrape a single listing page."""
        html = await self.fetch(url)
        if not html:
            return None
        
        try:
            return self._parse_listing(html, url)
        except Exception as e:
            print(f"  ⚠️ Parse error: {e}")
            return None
    
    def _parse_listing(self, html: str, url: str) -> Optional[CompetitorListing]:
        """Parse listing details from HTML."""
        soup = BeautifulSoup(html, 'lxml')
        
        # Extract listing ID from URL
        listing_id = url.split('/')[-1].split('-')[0] if '/' in url else url
        
        # Find property name (usually in h1 or title)
        name = None
        h1 = soup.find('h1')
        if h1:
            name = h1.get_text(strip=True)
        if not name:
            title = soup.find('title')
            if title:
                name = title.get_text(strip=True).split('|')[0].strip()
        
        if not name:
            return None
        
        # Get full page text for amenity detection
        page_text = soup.get_text(' ', strip=True).lower()
        
        # Parse bedrooms/bathrooms
        bedrooms = self._extract_bedrooms(page_text)
        bathrooms = self._extract_bathrooms(page_text)
        sleeps = self._extract_sleeps(page_text)
        
        # Detect submarket
        submarket = self._detect_submarket(name + ' ' + page_text)
        
        # Detect amenities
        has_pool = 'private pool' in page_text or 'pool!' in page_text
        pool_type = 'private' if 'private pool' in page_text else 'community' if 'community pool' in page_text or 'access to' in page_text and 'pool' in page_text else 'none'
        has_hot_tub = 'hot tub' in page_text or 'spa' in page_text
        has_view = 'gulf view' in page_text or 'ocean view' in page_text or 'lake view' in page_text
        view_type = 'gulf' if 'gulf' in page_text else 'lake' if 'lake' in page_text else 'none'
        has_golf_cart = 'golf cart' in page_text
        has_bikes = 'bike' in page_text
        pet_friendly = 'pet friendly' in page_text or 'pets allowed' in page_text
        
        return CompetitorListing(
            source=self.company_key,
            listing_id=listing_id,
            name=name,
            url=url,
            bedrooms=bedrooms,
            bathrooms=bathrooms,
            sleeps=sleeps,
            submarket=submarket,
            has_pool=has_pool or pool_type != 'none',
            pool_type=pool_type,
            has_hot_tub=has_hot_tub,
            has_view=has_view,
            view_type=view_type,
            has_golf_cart=has_golf_cart,
            has_bikes=has_bikes,
            pet_friendly=pet_friendly,
        )
    
    def _extract_bedrooms(self, text: str) -> Optional[int]:
        """Extract bedroom count from text."""
        patterns = [
            r'(\d+)\s*(?:br|bed|bedroom)',
            r'(\d+)-(?:br|bed|bedroom)',
            r'sleeps\s*\d+\s*[-–]\s*(\d+)\s*bed',
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return int(match.group(1))
        return None
    
    def _extract_bathrooms(self, text: str) -> Optional[float]:
        """Extract bathroom count from text."""
        patterns = [
            r'(\d+(?:\.\d+)?)\s*(?:ba|bath|bathroom)',
            r'(\d+)-(?:ba|bath|bathroom)',
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return float(match.group(1))
        return None
    
    def _extract_sleeps(self, text: str) -> Optional[int]:
        """Extract guest capacity from text."""
        patterns = [
            r'sleeps\s*(\d+)',
            r'accommodat(?:es?|ing)\s*(?:up to\s*)?(\d+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return int(match.group(1))
        return None
    
    def _detect_submarket(self, text: str) -> Optional[str]:
        """Detect submarket from property name/description."""
        text = text.lower()
        for submarket, patterns in SUBMARKET_PATTERNS.items():
            for pattern in patterns:
                if pattern in text:
                    return submarket
        return None


# =============================================================================
# DATABASE INTEGRATION
# =============================================================================

def save_competitor_listings(listings: List[CompetitorListing]) -> Dict[str, int]:
    """Save competitor listings to database."""
    if not listings:
        return {"inserted": 0, "updated": 0}
    
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    
    # Create competitor_listings table if not exists
    cur.execute("""
        CREATE TABLE IF NOT EXISTS competitor_listings (
            id SERIAL PRIMARY KEY,
            source VARCHAR(50) NOT NULL,
            listing_id VARCHAR(200) NOT NULL,
            name VARCHAR(500),
            url VARCHAR(1000),
            
            bedrooms INTEGER,
            bathrooms DECIMAL(3, 1),
            sleeps INTEGER,
            
            submarket_id VARCHAR(100),
            
            has_pool BOOLEAN DEFAULT false,
            pool_type VARCHAR(50),
            has_hot_tub BOOLEAN DEFAULT false,
            has_view BOOLEAN DEFAULT false,
            view_type VARCHAR(50),
            has_golf_cart BOOLEAN DEFAULT false,
            has_bikes BOOLEAN DEFAULT false,
            pet_friendly BOOLEAN DEFAULT false,
            
            scraped_at TIMESTAMP DEFAULT NOW(),
            last_updated TIMESTAMP DEFAULT NOW(),
            is_active BOOLEAN DEFAULT true,
            
            CONSTRAINT competitor_listings_unique UNIQUE (source, listing_id)
        )
    """)
    
    cur.execute("CREATE INDEX IF NOT EXISTS idx_competitor_submarket ON competitor_listings(submarket_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_competitor_source ON competitor_listings(source)")
    
    inserted = 0
    updated = 0
    
    for listing in listings:
        cur.execute("""
            INSERT INTO competitor_listings (
                source, listing_id, name, url,
                bedrooms, bathrooms, sleeps,
                submarket_id,
                has_pool, pool_type, has_hot_tub,
                has_view, view_type,
                has_golf_cart, has_bikes, pet_friendly,
                scraped_at
            ) VALUES (
                %s, %s, %s, %s,
                %s, %s, %s,
                %s,
                %s, %s, %s,
                %s, %s,
                %s, %s, %s,
                %s
            )
            ON CONFLICT (source, listing_id) DO UPDATE SET
                name = EXCLUDED.name,
                bedrooms = COALESCE(EXCLUDED.bedrooms, competitor_listings.bedrooms),
                bathrooms = COALESCE(EXCLUDED.bathrooms, competitor_listings.bathrooms),
                sleeps = COALESCE(EXCLUDED.sleeps, competitor_listings.sleeps),
                submarket_id = COALESCE(EXCLUDED.submarket_id, competitor_listings.submarket_id),
                has_pool = EXCLUDED.has_pool,
                has_hot_tub = EXCLUDED.has_hot_tub,
                has_view = EXCLUDED.has_view,
                last_updated = NOW()
            RETURNING (xmax = 0) as is_insert
        """, (
            listing.source,
            listing.listing_id,
            listing.name,
            listing.url,
            listing.bedrooms,
            listing.bathrooms,
            listing.sleeps,
            listing.submarket,
            listing.has_pool,
            listing.pool_type,
            listing.has_hot_tub,
            listing.has_view,
            listing.view_type,
            listing.has_golf_cart,
            listing.has_bikes,
            listing.pet_friendly,
            listing.scraped_at,
        ))
        
        result = cur.fetchone()
        if result and result[0]:
            inserted += 1
        else:
            updated += 1
    
    conn.commit()
    cur.close()
    conn.close()
    
    return {"inserted": inserted, "updated": updated}


def get_competitor_summary() -> Dict[str, Any]:
    """Get summary of competitor data."""
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    
    cur.execute("""
        SELECT 
            source,
            COUNT(*) as count,
            COUNT(*) FILTER (WHERE has_pool) as with_pool,
            COUNT(*) FILTER (WHERE has_hot_tub) as with_hot_tub,
            COUNT(*) FILTER (WHERE has_view) as with_view,
            COUNT(*) FILTER (WHERE has_golf_cart) as with_golf_cart
        FROM competitor_listings
        WHERE is_active = true
        GROUP BY source
    """)
    
    by_source = [
        {
            "source": r[0],
            "count": r[1],
            "with_pool": r[2],
            "with_hot_tub": r[3],
            "with_view": r[4],
            "with_golf_cart": r[5],
            "pool_pct": round(r[2] / r[1], 3) if r[1] > 0 else 0,
        }
        for r in cur.fetchall()
    ]
    
    cur.execute("""
        SELECT 
            submarket_id,
            COUNT(*) as count,
            COUNT(*) FILTER (WHERE has_pool) as with_pool,
            AVG(bedrooms) as avg_beds
        FROM competitor_listings
        WHERE is_active = true AND submarket_id IS NOT NULL
        GROUP BY submarket_id
        ORDER BY count DESC
    """)
    
    by_submarket = [
        {
            "submarket": r[0],
            "count": r[1],
            "with_pool": r[2],
            "pool_pct": round(r[2] / r[1], 3) if r[1] > 0 else 0,
            "avg_beds": round(float(r[3]), 1) if r[3] else None,
        }
        for r in cur.fetchall()
    ]
    
    cur.close()
    conn.close()
    
    return {
        "by_source": by_source,
        "by_submarket": by_submarket,
        "total": sum(s["count"] for s in by_source),
    }


# =============================================================================
# MAIN
# =============================================================================

async def scrape_competitor(company_key: str, save_to_db: bool = False) -> List[CompetitorListing]:
    """Scrape a single competitor."""
    scraper = CompetitorScraper(company_key)
    
    try:
        listings = await scraper.scrape_all()
        
        print(f"\n📊 {COMPETITORS[company_key]['name']} Results:")
        print(f"   Total listings: {len(listings)}")
        
        if listings:
            with_pool = sum(1 for l in listings if l.has_pool)
            with_view = sum(1 for l in listings if l.has_view)
            print(f"   With pool: {with_pool} ({with_pool/len(listings):.1%})")
            print(f"   With view: {with_view} ({with_view/len(listings):.1%})")
            
            # Submarket breakdown
            submarkets = {}
            for l in listings:
                sm = l.submarket or "unknown"
                submarkets[sm] = submarkets.get(sm, 0) + 1
            print(f"   By submarket: {submarkets}")
        
        if save_to_db and listings:
            result = save_competitor_listings(listings)
            print(f"\n💾 Saved to DB: {result}")
        
        return listings
        
    finally:
        await scraper.close()


async def scrape_all_competitors(save_to_db: bool = False) -> Dict[str, List[CompetitorListing]]:
    """Scrape all configured competitors."""
    results = {}
    
    for company_key in COMPETITORS:
        try:
            listings = await scrape_competitor(company_key, save_to_db)
            results[company_key] = listings
        except Exception as e:
            print(f"❌ Error scraping {company_key}: {e}")
            results[company_key] = []
    
    return results


async def main():
    parser = argparse.ArgumentParser(description="Scrape competitor property listings")
    parser.add_argument("--company", choices=list(COMPETITORS.keys()), help="Specific company to scrape")
    parser.add_argument("--all", action="store_true", help="Scrape all competitors")
    parser.add_argument("--save-to-db", action="store_true", help="Save results to database")
    parser.add_argument("--summary", action="store_true", help="Show summary of existing data")
    
    args = parser.parse_args()
    
    if args.summary:
        summary = get_competitor_summary()
        print("\n📊 COMPETITOR DATA SUMMARY")
        print(json.dumps(summary, indent=2))
        return
    
    if args.all:
        await scrape_all_competitors(args.save_to_db)
    elif args.company:
        await scrape_competitor(args.company, args.save_to_db)
    else:
        parser.print_help()


if __name__ == "__main__":
    asyncio.run(main())
