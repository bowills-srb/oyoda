#!/usr/bin/env python3
"""
Escapia Competitor Pricing Scraper

Scrapes availability and pricing from Escapia-based competitors (Benchmark, etc.)
using the same rcItemAvailForm pattern as Beach Habitats.

USAGE:
    python escapia_competitor_scraper.py --company benchmark --limit 10
    python escapia_competitor_scraper.py --company benchmark --limit 50 --save-db
    python escapia_competitor_scraper.py --summary
"""

import argparse
import asyncio
import json
import os
import re
import random
from dataclasses import dataclass, field, asdict
from datetime import datetime, date, timedelta, timezone
from decimal import Decimal
from typing import List, Dict, Optional, Tuple

try:
    from playwright.async_api import async_playwright
except ImportError:
    print("ERROR: Playwright required. Run: pip install playwright && playwright install chromium")
    exit(1)

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    HAS_POSTGRES = True
except ImportError:
    HAS_POSTGRES = False


DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://rental:rental@localhost:5433/rental_revenue")


# =============================================================================
# COMPETITOR CONFIGURATIONS
# =============================================================================

ESCAPIA_COMPETITORS = {
    "benchmark": {
        "name": "Benchmark Management",
        "base_url": "https://www.benchmark30a.com",
        "search_urls": [
            "https://www.benchmark30a.com/emerald-coast-vacation-rentals/30a",
        ],
        "listing_pattern": r"/emerald-coast-vacation-rentals/[^/]+$",
        "skip_slugs": ['30a', 'destin', 'panama-city-beach', 'large-group-vacation-rentals', 
                      'pet-friendly', 'pool', 'beachfront', 'gulf-view', 'luxury',
                      'condominium', 'private-home', 'golf-cart', 'destin-miramar-beach',
                      'beachfront-vacation-rentals', 'new-listings', 'specials'],
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
    "santa_rosa": ["santa rosa"],
    "miramar": ["miramar"],
    "destin": ["destin"],
}


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class AvailabilityRange:
    start_date: date
    end_date: date
    is_available: bool
    min_stay: Optional[int] = None


@dataclass
class PricingQuote:
    check_in: date
    check_out: date
    nights: int
    lodging: Decimal = Decimal("0")
    cleaning_fee: Decimal = Decimal("0")
    taxes: Decimal = Decimal("0")
    total: Decimal = Decimal("0")
    adr: Decimal = Decimal("0")


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
    availability: List[AvailabilityRange] = field(default_factory=list)
    pricing_quotes: List[PricingQuote] = field(default_factory=list)
    avg_adr: Optional[Decimal] = None
    scraped_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# =============================================================================
# SCRAPER CLASS
# =============================================================================

class EscapiaScraper:
    
    def __init__(self, company_key: str):
        if company_key not in ESCAPIA_COMPETITORS:
            raise ValueError(f"Unknown competitor: {company_key}. Available: {list(ESCAPIA_COMPETITORS.keys())}")
        
        self.company_key = company_key
        self.config = ESCAPIA_COMPETITORS[company_key]
        self.browser = None
        self.request_count = 0
    
    async def setup(self):
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=True)
        self.context = await self.browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        )
    
    async def cleanup(self):
        if self.browser:
            await self.browser.close()
        if hasattr(self, 'playwright'):
            await self.playwright.stop()
    
    async def _rate_limit(self):
        """Respectful rate limiting."""
        self.request_count += 1
        if self.request_count % 20 == 0:
            print(f"\n   ⏸️  Rate limit pause...")
            await asyncio.sleep(15)
        await asyncio.sleep(random.uniform(2.0, 4.0))
    
    async def get_listing_urls(self) -> List[str]:
        """Get all property listing URLs."""
        urls = set()
        page = await self.context.new_page()
        
        for search_url in self.config['search_urls']:
            print(f"   Scanning: {search_url}")
            try:
                await page.goto(search_url, wait_until='domcontentloaded', timeout=30000)
                await asyncio.sleep(2)
                
                # Scroll to load more
                for _ in range(5):
                    await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                    await asyncio.sleep(1)
                
                # Find listing links
                links = await page.query_selector_all('a[href*="/emerald-coast-vacation-rentals/"]')
                for link in links:
                    href = await link.get_attribute('href')
                    if href:
                        # Clean URL
                        if not href.startswith('http'):
                            href = self.config['base_url'] + href
                        href = href.split('?')[0].rstrip('/')
                        
                        # Skip category pages
                        slug = href.split('/')[-1]
                        if slug not in self.config['skip_slugs'] and len(slug) > 3:
                            urls.add(href)
                
                print(f"      Found {len(urls)} listings so far")
                
            except Exception as e:
                print(f"      Error: {e}")
        
        await page.close()
        return list(urls)
    
    def _parse_pricing_content(self, content: str) -> Dict:
        """Parse dollar amounts from pricing HTML/JSON content."""
        result = {'lodging': 0, 'taxes': 0, 'total': 0, 'cleaning': 0}
        
        # Unescape
        content = content.replace('\\u003C', '<').replace('\\u003E', '>')
        content = content.replace('\\u0022', '"').replace('\\/', '/')
        
        # Find lodging
        m = re.search(r'Lodging[^$]*\$([\d,]+(?:\.\d{2})?)', content, re.I)
        if m:
            result['lodging'] = float(m.group(1).replace(',', ''))
        
        # Alternative: look for "Rent" or "Nightly"
        if result['lodging'] == 0:
            m = re.search(r'(?:Rent|Nightly)[^$]*\$([\d,]+(?:\.\d{2})?)', content, re.I)
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
        
        # Find total - usually largest amount
        amounts = re.findall(r'\$([\d,]+(?:\.\d{2})?)', content)
        if amounts:
            parsed = [float(a.replace(',', '')) for a in amounts]
            result['total'] = max(parsed)
        
        return result
    
    def _detect_submarket(self, text: str) -> Optional[str]:
        text = text.lower()
        for submarket, patterns in SUBMARKET_PATTERNS.items():
            for pattern in patterns:
                if pattern in text:
                    return submarket
        return None
    
    def _extract_number(self, text: str, patterns: List[str]) -> Optional[int]:
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    return int(float(match.group(1)))
                except:
                    pass
        return None
    
    async def scrape_property(self, url: str) -> Optional[CompetitorProperty]:
        """Scrape a single property for availability and pricing."""
        
        page = await self.context.new_page()
        
        # Capture pricing responses
        pricing_responses = []
        
        async def capture_response(response):
            resp_url = response.url.lower()
            if 'pricing' in resp_url or 'quote' in resp_url:
                try:
                    body = await response.text()
                    if '$' in body and len(body) > 50:
                        pricing_responses.append(body)
                except:
                    pass
        
        page.on('response', capture_response)
        
        try:
            await page.goto(url, wait_until='networkidle', timeout=45000)
            await asyncio.sleep(2)
            
            html = await page.content()
            text = await page.inner_text('body')
            text_lower = text.lower()
            
            # Extract listing ID
            listing_id = url.rstrip('/').split('/')[-1]
            
            # Extract name
            name = listing_id.replace('-', ' ').title()
            try:
                h1 = await page.query_selector('h1')
                if h1:
                    h1_text = (await h1.inner_text()).strip()
                    if h1_text and len(h1_text) < 100:
                        name = h1_text
            except:
                pass
            
            # Extract property details
            bedrooms = self._extract_number(text_lower, [r'(\d+)\s*bed', r'(\d+)\s*br\b'])
            bathrooms = self._extract_number(text_lower, [r'(\d+(?:\.\d+)?)\s*bath', r'(\d+(?:\.\d+)?)\s*ba\b'])
            sleeps = self._extract_number(text_lower, [r'sleeps\s*(\d+)', r'(\d+)\s*guests?'])
            
            # Detect submarket
            submarket = self._detect_submarket(name + ' ' + url + ' ' + text_lower)
            
            # Pool detection
            search_text = text_lower + ' ' + html.lower()
            private_pool_indicators = ['private pool', 'pvt pool', 'own pool', 'heated pool', 'plunge pool']
            community_pool_indicators = ['community pool', 'pool access', 'shared pool', 'hoa pool']
            
            has_private = any(ind in search_text for ind in private_pool_indicators)
            has_community = any(ind in search_text for ind in community_pool_indicators)
            
            if has_private:
                pool_type = 'private'
                has_pool = True
            elif has_community:
                pool_type = 'community'
                has_pool = False
            else:
                pool_type = 'none'
                has_pool = False
            
            # Create property object
            prop = CompetitorProperty(
                source=self.company_key,
                listing_id=listing_id,
                name=name,
                url=url,
                submarket=submarket,
                bedrooms=bedrooms,
                bathrooms=bathrooms,
                sleeps=sleeps,
                has_pool=has_pool,
                pool_type=pool_type,
            )
            
            # =================================================================
            # EXTRACT AVAILABILITY from rcItemAvailForm
            # =================================================================
            # Look for 'avail' or "avail" array with date ranges
            avail_match = re.search(r'["\']avail["\']\s*:\s*\[([^\]]+)\]', html, re.DOTALL)
            
            if avail_match:
                avail_content = avail_match.group(1)
                # Parse each range: {"b":"2026-02-17","e":"2026-02-23","a":"0"} or single quotes
                for m in re.finditer(r'["\']b["\']\s*:\s*["\'](\d{4}-\d{2}-\d{2})["\'].*?["\']e["\']\s*:\s*["\'](\d{4}-\d{2}-\d{2})["\'].*?["\']a["\']\s*:\s*["\'](\d)["\']', avail_content):
                    try:
                        start = date.fromisoformat(m.group(1))
                        end = date.fromisoformat(m.group(2))
                        is_avail = m.group(3) == '1'
                        prop.availability.append(AvailabilityRange(
                            start_date=start,
                            end_date=end,
                            is_available=is_avail,
                        ))
                    except:
                        continue
            
            # =================================================================
            # EXTRACT PRICING via date selection + AJAX
            # =================================================================
            today = date.today()
            quotes_collected = 0
            max_quotes = 3
            
            # Find available ranges for pricing queries
            available_ranges = [r for r in prop.availability if r.is_available and r.end_date > today]
            
            for avail_range in available_ranges[:5]:  # Try up to 5 ranges
                if quotes_collected >= max_quotes:
                    break
                
                try:
                    # Pick dates within this range
                    check_in = max(avail_range.start_date, today + timedelta(days=1))
                    check_out = min(check_in + timedelta(days=4), avail_range.end_date)
                    nights = (check_out - check_in).days
                    
                    if nights < 3:
                        continue
                    
                    # Format dates for input
                    begin_str = check_in.strftime('%m/%d/%Y')
                    end_str = check_out.strftime('%m/%d/%Y')
                    
                    pricing_responses.clear()
                    
                    # Set dates via JavaScript (same pattern as Beach Habitats)
                    await page.evaluate(f"""
                        () => {{
                            // Try various input selectors
                            const beginSelectors = ['input.begin', 'input[name*="checkin"]', 'input[name*="begin"]', 'input[name*="arrival"]'];
                            const endSelectors = ['input.end', 'input[name*="checkout"]', 'input[name*="end"]', 'input[name*="departure"]'];
                            
                            let beginInput = null;
                            let endInput = null;
                            
                            for (const sel of beginSelectors) {{
                                beginInput = document.querySelector(sel);
                                if (beginInput) break;
                            }}
                            for (const sel of endSelectors) {{
                                endInput = document.querySelector(sel);
                                if (endInput) break;
                            }}
                            
                            if (beginInput && endInput) {{
                                beginInput.value = '{begin_str}';
                                endInput.value = '{end_str}';
                                beginInput.dispatchEvent(new Event('change', {{bubbles: true}}));
                                endInput.dispatchEvent(new Event('change', {{bubbles: true}}));
                            }}
                        }}
                    """)
                    
                    # Wait for AJAX response
                    await asyncio.sleep(2.5)
                    
                    # Parse captured pricing responses
                    for resp in pricing_responses:
                        try:
                            # Try JSON parse first
                            try:
                                data = json.loads(resp)
                                content = data.get('content', '') or data.get('data', '') or resp
                            except:
                                content = resp
                            
                            parsed = self._parse_pricing_content(content)
                            
                            if parsed['total'] > 100:  # Sanity check
                                lodging = Decimal(str(parsed['lodging']))
                                total = Decimal(str(parsed['total']))
                                
                                # Calculate ADR
                                if lodging > 0:
                                    adr = lodging / nights
                                else:
                                    adr = total / nights * Decimal("0.85")  # Estimate without fees
                                
                                quote = PricingQuote(
                                    check_in=check_in,
                                    check_out=check_out,
                                    nights=nights,
                                    lodging=lodging,
                                    cleaning_fee=Decimal(str(parsed['cleaning'])),
                                    taxes=Decimal(str(parsed['taxes'])),
                                    total=total,
                                    adr=adr,
                                )
                                prop.pricing_quotes.append(quote)
                                quotes_collected += 1
                                break
                        except:
                            continue
                
                except Exception as e:
                    continue
            
            # Calculate average ADR
            if prop.pricing_quotes:
                adrs = [q.adr for q in prop.pricing_quotes if q.adr > 0]
                if adrs:
                    prop.avg_adr = sum(adrs) / len(adrs)
            
            await page.close()
            return prop
            
        except Exception as e:
            await page.close()
            return None
    
    async def scrape_all(self, limit: Optional[int] = None) -> List[CompetitorProperty]:
        """Scrape all properties from the competitor."""
        
        print(f"\n{'='*70}")
        print(f"🏠 ESCAPIA COMPETITOR SCRAPER: {self.config['name']}")
        print(f"{'='*70}")
        
        await self.setup()
        
        try:
            # Get listing URLs
            print("\n📄 Finding property listings...")
            urls = await self.get_listing_urls()
            print(f"   Found {len(urls)} total listings")
            
            if limit:
                urls = urls[:limit]
                print(f"   Limited to {limit} for this run")
            
            # Scrape each property
            properties = []
            
            for i, url in enumerate(urls):
                slug = url.split('/')[-1][:35]
                print(f"\n📍 [{i+1}/{len(urls)}] {slug}...")
                
                prop = await self.scrape_property(url)
                
                if prop:
                    properties.append(prop)
                    
                    # Summary
                    avail_count = len([r for r in prop.availability if r.is_available])
                    pricing_str = f"${float(prop.avg_adr):.0f}/night" if prop.avg_adr else "no pricing"
                    pool_str = f"🏊{prop.pool_type}" if prop.pool_type != 'none' else ""
                    
                    print(f"   ✅ {prop.name[:30]} | {prop.bedrooms}BR | {prop.submarket or 'unknown'} | {pool_str}")
                    print(f"      📅 {avail_count} available ranges | 💰 {len(prop.pricing_quotes)} quotes, {pricing_str}")
                else:
                    print(f"   ❌ Failed to scrape")
                
                await self._rate_limit()
            
            return properties
            
        finally:
            await self.cleanup()


# =============================================================================
# DATABASE
# =============================================================================

def save_to_database(properties: List[CompetitorProperty]) -> Dict:
    if not HAS_POSTGRES:
        return {"error": "psycopg2 not installed"}
    
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    
    results = {"properties": 0, "pricing": 0, "availability": 0, "errors": 0}
    
    # Ensure tables exist
    cur.execute("""
        CREATE TABLE IF NOT EXISTS competitor_pricing (
            id SERIAL PRIMARY KEY,
            source VARCHAR(50) NOT NULL,
            listing_id VARCHAR(200) NOT NULL,
            check_in DATE NOT NULL,
            check_out DATE NOT NULL,
            nights INTEGER,
            lodging DECIMAL(10, 2),
            cleaning_fee DECIMAL(10, 2),
            taxes DECIMAL(10, 2),
            total DECIMAL(10, 2),
            adr DECIMAL(10, 2),
            scraped_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE (source, listing_id, check_in, check_out)
        )
    """)
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS competitor_availability (
            id SERIAL PRIMARY KEY,
            source VARCHAR(50) NOT NULL,
            listing_id VARCHAR(200) NOT NULL,
            availability_data JSONB,
            scraped_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE (source, listing_id)
        )
    """)
    conn.commit()
    
    for prop in properties:
        try:
            # Save/update property in external_listings
            cur.execute("""
                INSERT INTO external_listings (
                    listing_id, source, market_id, submarket_id,
                    bedrooms, bathrooms, sleeps, property_type,
                    has_pool, pool_type, listing_url, title, 
                    avg_adr, scraped_at, is_active
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                ON CONFLICT (source, listing_id) DO UPDATE SET
                    bedrooms = COALESCE(EXCLUDED.bedrooms, external_listings.bedrooms),
                    bathrooms = COALESCE(EXCLUDED.bathrooms, external_listings.bathrooms),
                    sleeps = COALESCE(EXCLUDED.sleeps, external_listings.sleeps),
                    submarket_id = COALESCE(EXCLUDED.submarket_id, external_listings.submarket_id),
                    has_pool = EXCLUDED.has_pool,
                    pool_type = EXCLUDED.pool_type,
                    avg_adr = COALESCE(EXCLUDED.avg_adr, external_listings.avg_adr),
                    title = COALESCE(EXCLUDED.title, external_listings.title),
                    last_updated = NOW()
            """, (
                prop.listing_id, prop.source, '30a_fl', prop.submarket,
                prop.bedrooms, prop.bathrooms, prop.sleeps, 'house',
                prop.has_pool, prop.pool_type, prop.url, prop.name,
                float(prop.avg_adr) if prop.avg_adr else None,
                prop.scraped_at, True,
            ))
            conn.commit()
            results["properties"] += 1
            
            # Save pricing quotes
            for quote in prop.pricing_quotes:
                try:
                    cur.execute("""
                        INSERT INTO competitor_pricing (
                            source, listing_id, check_in, check_out, nights,
                            lodging, cleaning_fee, taxes, total, adr
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (source, listing_id, check_in, check_out) DO UPDATE SET
                            lodging = EXCLUDED.lodging,
                            total = EXCLUDED.total,
                            adr = EXCLUDED.adr,
                            scraped_at = NOW()
                    """, (
                        prop.source, prop.listing_id, quote.check_in, quote.check_out,
                        quote.nights, float(quote.lodging), float(quote.cleaning_fee),
                        float(quote.taxes), float(quote.total), float(quote.adr),
                    ))
                    conn.commit()
                    results["pricing"] += 1
                except:
                    conn.rollback()
            
            # Save availability
            if prop.availability:
                avail_data = [
                    {"start": r.start_date.isoformat(), "end": r.end_date.isoformat(), "available": r.is_available}
                    for r in prop.availability
                ]
                try:
                    cur.execute("""
                        INSERT INTO competitor_availability (source, listing_id, availability_data)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (source, listing_id) DO UPDATE SET
                            availability_data = EXCLUDED.availability_data,
                            scraped_at = NOW()
                    """, (prop.source, prop.listing_id, json.dumps(avail_data)))
                    conn.commit()
                    results["availability"] += 1
                except:
                    conn.rollback()
        
        except Exception as e:
            conn.rollback()
            results["errors"] += 1
    
    cur.close()
    conn.close()
    return results


def get_summary():
    """Get summary of scraped competitor data."""
    if not HAS_POSTGRES:
        return {}
    
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    cur = conn.cursor()
    
    # Properties by source with pricing
    cur.execute("""
        SELECT 
            source,
            COUNT(*) as total_properties,
            COUNT(*) FILTER (WHERE avg_adr IS NOT NULL) as with_pricing,
            ROUND(AVG(avg_adr)::numeric, 0) as avg_adr,
            ROUND(MIN(avg_adr)::numeric, 0) as min_adr,
            ROUND(MAX(avg_adr)::numeric, 0) as max_adr
        FROM external_listings
        WHERE is_active = true
        GROUP BY source
        ORDER BY total_properties DESC
    """)
    by_source = [dict(r) for r in cur.fetchall()]
    
    # Pricing quotes
    cur.execute("""
        SELECT 
            source,
            COUNT(*) as quote_count,
            ROUND(AVG(adr)::numeric, 0) as avg_adr
        FROM competitor_pricing
        GROUP BY source
    """)
    pricing = [dict(r) for r in cur.fetchall()]
    
    cur.close()
    conn.close()
    
    return {"by_source": by_source, "pricing": pricing}


# =============================================================================
# MAIN
# =============================================================================

async def main():
    parser = argparse.ArgumentParser(description="Scrape Escapia-based competitor pricing")
    parser.add_argument("--company", choices=list(ESCAPIA_COMPETITORS.keys()), help="Competitor to scrape")
    parser.add_argument("--limit", type=int, help="Limit number of properties")
    parser.add_argument("--save-db", action="store_true", help="Save to database")
    parser.add_argument("--output", help="Output JSON file")
    parser.add_argument("--summary", action="store_true", help="Show database summary")
    
    args = parser.parse_args()
    
    if args.summary:
        summary = get_summary()
        print("\n📊 COMPETITOR DATA SUMMARY")
        print(json.dumps(summary, indent=2, default=str))
        return
    
    if not args.company:
        parser.print_help()
        return
    
    scraper = EscapiaScraper(args.company)
    properties = await scraper.scrape_all(limit=args.limit)
    
    # Summary
    print(f"\n{'='*70}")
    print("📊 SCRAPE SUMMARY")
    print(f"{'='*70}")
    print(f"Properties scraped: {len(properties)}")
    
    with_pricing = [p for p in properties if p.pricing_quotes]
    print(f"With pricing data: {len(with_pricing)}")
    
    total_quotes = sum(len(p.pricing_quotes) for p in properties)
    print(f"Total pricing quotes: {total_quotes}")
    
    if with_pricing:
        avg_adrs = [float(p.avg_adr) for p in with_pricing if p.avg_adr]
        if avg_adrs:
            print(f"Average ADR: ${sum(avg_adrs)/len(avg_adrs):.0f}/night")
            print(f"ADR Range: ${min(avg_adrs):.0f} - ${max(avg_adrs):.0f}")
    
    # By submarket
    by_submarket = {}
    for p in properties:
        sm = p.submarket or 'unknown'
        if sm not in by_submarket:
            by_submarket[sm] = {'count': 0, 'with_pricing': 0, 'adrs': []}
        by_submarket[sm]['count'] += 1
        if p.avg_adr:
            by_submarket[sm]['with_pricing'] += 1
            by_submarket[sm]['adrs'].append(float(p.avg_adr))
    
    print(f"\nBy Submarket:")
    for sm, data in sorted(by_submarket.items(), key=lambda x: -x[1]['count']):
        avg = sum(data['adrs'])/len(data['adrs']) if data['adrs'] else 0
        print(f"  {sm}: {data['count']} properties, {data['with_pricing']} with pricing, avg ${avg:.0f}/night")
    
    # Save to database
    if args.save_db:
        results = save_to_database(properties)
        print(f"\n💾 Database: {results}")
    
    # Save to JSON
    if args.output:
        def serialize(obj):
            if isinstance(obj, (date, datetime)):
                return obj.isoformat()
            if isinstance(obj, Decimal):
                return float(obj)
            if hasattr(obj, '__dict__'):
                return {k: serialize(v) for k, v in obj.__dict__.items()}
            if isinstance(obj, list):
                return [serialize(i) for i in obj]
            return obj
        
        with open(args.output, 'w') as f:
            json.dump([serialize(p) for p in properties], f, indent=2)
        print(f"\n📄 Saved to {args.output}")


if __name__ == "__main__":
    asyncio.run(main())
