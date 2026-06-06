#!/usr/bin/env python3
"""
Benchmark Pricing Scraper - Uses calendar UI interaction

Extracts pricing by clicking through the date picker calendar,
then reading the price that appears in the booking widget.
"""

import argparse
import asyncio
import json
import os
import re
import random
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta, timezone
from decimal import Decimal
from typing import List, Optional

try:
    from playwright.async_api import async_playwright
except ImportError:
    print("ERROR: Playwright required")
    exit(1)

try:
    import psycopg2
    HAS_POSTGRES = True
except ImportError:
    HAS_POSTGRES = False

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://rental:rental@localhost:5433/rental_revenue")
BASE_URL = "https://www.benchmark30a.com"


@dataclass
class PricingQuote:
    check_in: date
    check_out: date
    nights: int
    total_before_tax: Decimal
    adr: Decimal


@dataclass
class PropertyData:
    listing_id: str
    name: str
    url: str
    bedrooms: Optional[int] = None
    bathrooms: Optional[float] = None
    sleeps: Optional[int] = None
    submarket: Optional[str] = None
    has_pool: bool = False
    pool_type: str = "none"
    quotes: List[PricingQuote] = field(default_factory=list)
    avg_adr: Optional[Decimal] = None


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


class BenchmarkScraper:
    
    def __init__(self, headless: bool = True):
        self.headless = headless
        self.browser = None
    
    async def setup(self):
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=self.headless)
        self.context = await self.browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        )
    
    async def cleanup(self):
        if self.browser:
            await self.browser.close()
        if hasattr(self, 'playwright'):
            await self.playwright.stop()
    
    async def get_listing_urls(self) -> List[str]:
        urls = set()
        page = await self.context.new_page()
        
        search_url = f"{BASE_URL}/emerald-coast-vacation-rentals/30a"
        print(f"   Scanning: {search_url}")
        
        try:
            await page.goto(search_url, wait_until='domcontentloaded', timeout=30000)
            await asyncio.sleep(2)
            
            for _ in range(5):
                await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                await asyncio.sleep(1)
            
            skip_slugs = ['30a', 'destin', 'panama-city-beach', 'large-group', 
                         'pet-friendly', 'pool', 'beachfront', 'gulf-view', 'luxury',
                         'condominium', 'private-home', 'golf-cart', 'new-listings', 'specials']
            
            links = await page.query_selector_all('a[href*="/emerald-coast-vacation-rentals/"]')
            for link in links:
                href = await link.get_attribute('href')
                if href:
                    if not href.startswith('http'):
                        href = BASE_URL + href
                    href = href.split('?')[0].split('#')[0].rstrip('/')
                    slug = href.split('/')[-1]
                    if slug not in skip_slugs and len(slug) > 3:
                        urls.add(href)
            
            print(f"   Found {len(urls)} listings")
        except Exception as e:
            print(f"   Error: {e}")
        
        await page.close()
        return list(urls)
    
    def _detect_submarket(self, text: str) -> Optional[str]:
        text = text.lower()
        for submarket, patterns in SUBMARKET_PATTERNS.items():
            for pattern in patterns:
                if pattern in text:
                    return submarket
        return None
    
    async def _click_calendar_date(self, page, target_date: date) -> bool:
        """Click a specific date in the jQuery UI datepicker."""
        target_month = target_date.strftime('%B')
        target_year = str(target_date.year)
        target_day = str(target_date.day)
        
        # Navigate to correct month (try up to 12 months ahead)
        for _ in range(12):
            try:
                header = await page.query_selector('.ui-datepicker-title')
                if header:
                    header_text = await header.inner_text()
                    if target_month in header_text and target_year in header_text:
                        break
                
                # Click next month button
                next_btn = await page.query_selector('.ui-datepicker-next:not(.ui-state-disabled)')
                if next_btn:
                    await next_btn.click()
                    await asyncio.sleep(0.3)
                else:
                    break
            except:
                break
        
        # Find and click the day
        try:
            # Get all selectable days
            days = await page.query_selector_all('.ui-datepicker-calendar td:not(.ui-datepicker-unselectable):not(.ui-datepicker-other-month) a')
            for day_elem in days:
                day_text = await day_elem.inner_text()
                if day_text.strip() == target_day:
                    await day_elem.click()
                    return True
        except:
            pass
        
        return False
    
    async def _extract_price(self, page) -> Optional[Decimal]:
        """Extract price from the booking widget after dates are set."""
        await asyncio.sleep(1)
        
        try:
            # Look for the price that appears after date selection
            # Pattern from screenshot: "$1,842 + tax" below the date range
            
            # Get text from booking widget area
            booking_area = await page.query_selector('.rc-item-avail-form, [class*="avail-form"], .booking-widget, aside, .sidebar')
            
            if booking_area:
                text = await booking_area.inner_text()
                
                # Look for "$X,XXX + tax" pattern (the main price display)
                match = re.search(r'\$\s*([\d,]+)\s*\+\s*tax', text)
                if match:
                    price = float(match.group(1).replace(',', ''))
                    if 200 < price < 50000:
                        print(f"      💰 Found price: ${price:.0f} + tax")
                        return Decimal(str(price))
                
                # Also try just "$X,XXX" near "BOOK NOW"
                if 'BOOK NOW' in text or 'Book Now' in text:
                    matches = re.findall(r'\$\s*([\d,]+)', text)
                    for m in matches:
                        price = float(m.replace(',', ''))
                        if 200 < price < 50000:
                            print(f"      💰 Found price: ${price:.0f}")
                            return Decimal(str(price))
            
            # Fallback: search entire page for "$X,XXX + tax"
            body_text = await page.inner_text('body')
            match = re.search(r'\$\s*([\d,]+)\s*\+\s*tax', body_text)
            if match:
                price = float(match.group(1).replace(',', ''))
                if 200 < price < 50000:
                    print(f"      💰 Found price (fallback): ${price:.0f} + tax")
                    return Decimal(str(price))
                    
        except Exception as e:
            print(f"      Price extraction error: {e}")
        
        print(f"      ⚠️ No price found")
        return None
    
    async def _dismiss_popups(self, page):
        """Dismiss any modal popups (email signup, etc)."""
        try:
            # Try clicking "No thanks" first (most specific)
            no_thanks_selectors = [
                'text="No thanks"',
                'text="No Thanks"', 
                'text="NO THANKS"',
                'a:has-text("No thanks")',
                'button:has-text("No thanks")',
                'span:has-text("No thanks")',
            ]
            
            for selector in no_thanks_selectors:
                try:
                    elem = await page.query_selector(selector)
                    if elem and await elem.is_visible():
                        await elem.click()
                        await asyncio.sleep(0.5)
                        return True
                except:
                    continue
            
            # Try X button selectors
            close_selectors = [
                'button[aria-label="Close"]',
                'button[aria-label="close"]',
                '.close-button',
                'button.close',
                '.modal-close',
                '.popup-close', 
                '.reveal-modal-close',  # Zurb Foundation
                'a.close-reveal-modal',
                '.close-reveal-modal',
                '[class*="close-modal"]',
                '[class*="modal-close"]',
                '[class*="popup-close"]',
                'button:has-text("×")',
                'a:has-text("×")',
                'span:has-text("×")',
                '.mc-closeModal',
                '.mc-modal-close',
                '[data-dismiss="modal"]',
            ]
            
            for selector in close_selectors:
                try:
                    btn = await page.query_selector(selector)
                    if btn and await btn.is_visible():
                        await btn.click()
                        await asyncio.sleep(0.5)
                        return True
                except:
                    continue
            
            # Try pressing Escape key as last resort
            await page.keyboard.press('Escape')
            await asyncio.sleep(0.3)
            
        except:
            pass
        return False
    
    async def scrape_property(self, url: str) -> Optional[PropertyData]:
        """Scrape a single property for pricing using calendar clicks."""
        
        page = await self.context.new_page()
        
        try:
            await page.goto(url, wait_until='networkidle', timeout=45000)
            await asyncio.sleep(2)
            
            # Dismiss any initial popups
            await self._dismiss_popups(page)
            
            html = await page.content()
            body_text = await page.inner_text('body')
            
            listing_id = url.rstrip('/').split('/')[-1]
            
            # Extract name
            name = listing_id.replace('-', ' ').title()
            try:
                h1 = await page.query_selector('h1')
                if h1:
                    name = (await h1.inner_text()).strip()
            except:
                pass
            
            # Extract property details
            bedrooms = bathrooms = sleeps = None
            details_match = re.search(r'(\d+)\s*BR\s*[•·]\s*([\d.]+)\s*BA\s*[•·]\s*(\d+)\s*Guests?', body_text, re.I)
            if details_match:
                bedrooms = int(details_match.group(1))
                bathrooms = float(details_match.group(2))
                sleeps = int(details_match.group(3))
            
            submarket = self._detect_submarket(name + ' ' + body_text[:1000])
            
            # Pool detection
            text_lower = body_text.lower()
            has_private = any(x in text_lower for x in ['private pool', 'heated pool', 'plunge pool'])
            has_community = any(x in text_lower for x in ['community pool', 'shared pool', 'pool access'])
            
            pool_type = 'private' if has_private else ('community' if has_community else 'none')
            has_pool = pool_type == 'private'
            
            prop = PropertyData(
                listing_id=listing_id,
                name=name[:50],
                url=url,
                bedrooms=bedrooms,
                bathrooms=bathrooms,
                sleeps=sleeps,
                submarket=submarket,
                has_pool=has_pool,
                pool_type=pool_type,
            )
            
            # Get available ranges
            available_ranges = []
            avail_match = re.search(r'["\']avail["\']\s*:\s*\[([^\]]+)\]', html)
            if avail_match:
                for m in re.finditer(r'["\']b["\']\s*:\s*["\'](\d{4}-\d{2}-\d{2})["\'].*?["\']e["\']\s*:\s*["\'](\d{4}-\d{2}-\d{2})["\'].*?["\']a["\']\s*:\s*["\'](\d)["\']', avail_match.group(1)):
                    if m.group(3) == '1':
                        start = date.fromisoformat(m.group(1))
                        end = date.fromisoformat(m.group(2))
                        available_ranges.append((start, end))
            
            if not available_ranges:
                await page.close()
                return prop
            
            # Try to get pricing
            today = date.today()
            
            for start, end in available_ranges[:3]:
                if start <= today:
                    start = today + timedelta(days=1)
                
                if (end - start).days < 4:
                    continue
                
                arrival = start
                departure = min(start + timedelta(days=4), end)
                nights = (departure - arrival).days
                
                if nights < 3:
                    continue
                
                try:
                    # Dismiss any popups first
                    await self._dismiss_popups(page)
                    
                    # === ARRIVAL DATE ===
                    arrival_input = await page.query_selector('input.begin, input[placeholder*="Arrival"]')
                    if not arrival_input:
                        print(f"      No arrival input found")
                        continue
                    
                    await arrival_input.click()
                    await asyncio.sleep(0.8)
                    await self._dismiss_popups(page)
                    
                    # Click arrival date in calendar
                    arrival_clicked = await self._click_calendar_date(page, arrival)
                    if not arrival_clicked:
                        print(f"      Could not click arrival date {arrival}")
                        continue
                    
                    print(f"      ✓ Arrival: {arrival}")
                    await asyncio.sleep(1)
                    await self._dismiss_popups(page)
                    
                    # === DEPARTURE DATE ===
                    # After clicking arrival, the departure calendar may auto-open
                    # or we need to click the departure input
                    
                    # Check if calendar is still open (for departure)
                    datepicker = await page.query_selector('.ui-datepicker:visible')
                    if not datepicker:
                        # Need to click departure input to open calendar
                        departure_input = await page.query_selector('input.end, input[placeholder*="Departure"]')
                        if departure_input:
                            await departure_input.click()
                            await asyncio.sleep(0.8)
                            await self._dismiss_popups(page)
                    
                    # Click departure date
                    departure_clicked = await self._click_calendar_date(page, departure)
                    if not departure_clicked:
                        print(f"      Could not click departure date {departure}")
                        continue
                    
                    print(f"      ✓ Departure: {departure}")
                    await asyncio.sleep(1.5)
                    await self._dismiss_popups(page)
                    
                    # === SEARCH AVAILABILITY ===
                    search_btn = await page.query_selector('button:has-text("SEARCH AVAILABILITY"), button:has-text("SEARCH"), input[value*="SEARCH"]')
                    if search_btn and await search_btn.is_visible():
                        print(f"      ✓ Clicking Search Availability")
                        await search_btn.click()
                        await asyncio.sleep(2.5)
                        await self._dismiss_popups(page)
                    
                    # === EXTRACT PRICE ===
                    price = await self._extract_price(page)
                    
                    if price:
                        adr = price / nights
                        quote = PricingQuote(
                            check_in=arrival,
                            check_out=departure,
                            nights=nights,
                            total_before_tax=price,
                            adr=adr,
                        )
                        prop.quotes.append(quote)
                        break  # Got a quote, move on
                
                except Exception as e:
                    continue
            
            # Calculate average ADR
            if prop.quotes:
                prop.avg_adr = sum(q.adr for q in prop.quotes) / len(prop.quotes)
            
            await page.close()
            return prop
            
        except Exception as e:
            await page.close()
            return None
    
    async def scrape_all(self, limit: Optional[int] = None) -> List[PropertyData]:
        print(f"\n{'='*70}")
        print(f"🏠 BENCHMARK PRICING SCRAPER")
        print(f"{'='*70}")
        
        await self.setup()
        
        try:
            print("\n📄 Finding listings...")
            urls = await self.get_listing_urls()
            
            if limit:
                urls = urls[:limit]
                print(f"   Limited to {limit}")
            
            properties = []
            
            for i, url in enumerate(urls):
                slug = url.split('/')[-1][:35]
                print(f"\n📍 [{i+1}/{len(urls)}] {slug}...")
                
                prop = await self.scrape_property(url)
                
                if prop:
                    properties.append(prop)
                    
                    pricing_str = f"${float(prop.avg_adr):.0f}/night" if prop.avg_adr else "no pricing"
                    pool_str = f"🏊{prop.pool_type}" if prop.pool_type != 'none' else ""
                    
                    print(f"   ✅ {prop.name[:30]} | {prop.bedrooms or '?'}BR | {prop.submarket or '?'} | {pool_str}")
                    print(f"      💰 {len(prop.quotes)} quotes, {pricing_str}")
                else:
                    print(f"   ❌ Failed")
                
                await asyncio.sleep(random.uniform(2, 4))
                if (i + 1) % 15 == 0:
                    print(f"\n   ⏸️  Pause...")
                    await asyncio.sleep(10)
            
            return properties
            
        finally:
            await self.cleanup()


def save_to_database(properties: List[PropertyData]) -> dict:
    if not HAS_POSTGRES:
        return {"error": "psycopg2 not installed"}
    
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    results = {"properties": 0, "pricing": 0, "errors": 0}
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS competitor_pricing (
            id SERIAL PRIMARY KEY,
            source VARCHAR(50) NOT NULL,
            listing_id VARCHAR(200) NOT NULL,
            check_in DATE,
            check_out DATE,
            nights INTEGER,
            total_before_tax DECIMAL(10,2),
            adr DECIMAL(10,2),
            scraped_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE (source, listing_id, check_in, check_out)
        )
    """)
    conn.commit()
    
    for prop in properties:
        try:
            cur.execute("""
                INSERT INTO external_listings (
                    listing_id, source, market_id, submarket_id,
                    bedrooms, bathrooms, sleeps, property_type,
                    has_pool, pool_type, listing_url, title, 
                    avg_adr, scraped_at, is_active
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (source, listing_id) DO UPDATE SET
                    bedrooms = COALESCE(EXCLUDED.bedrooms, external_listings.bedrooms),
                    bathrooms = COALESCE(EXCLUDED.bathrooms, external_listings.bathrooms),
                    submarket_id = COALESCE(EXCLUDED.submarket_id, external_listings.submarket_id),
                    has_pool = EXCLUDED.has_pool,
                    pool_type = EXCLUDED.pool_type,
                    avg_adr = COALESCE(EXCLUDED.avg_adr, external_listings.avg_adr),
                    last_updated = NOW()
            """, (
                prop.listing_id, 'benchmark', '30a_fl', prop.submarket,
                prop.bedrooms, prop.bathrooms, prop.sleeps, 'house',
                prop.has_pool, prop.pool_type, prop.url, prop.name,
                float(prop.avg_adr) if prop.avg_adr else None,
                datetime.now(timezone.utc), True,
            ))
            conn.commit()
            results["properties"] += 1
            
            for quote in prop.quotes:
                try:
                    cur.execute("""
                        INSERT INTO competitor_pricing (source, listing_id, check_in, check_out, nights, total_before_tax, adr)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (source, listing_id, check_in, check_out) DO UPDATE SET
                            total_before_tax = EXCLUDED.total_before_tax, adr = EXCLUDED.adr, scraped_at = NOW()
                    """, ('benchmark', prop.listing_id, quote.check_in, quote.check_out,
                          quote.nights, float(quote.total_before_tax), float(quote.adr)))
                    conn.commit()
                    results["pricing"] += 1
                except:
                    conn.rollback()
        except:
            conn.rollback()
            results["errors"] += 1
    
    cur.close()
    conn.close()
    return results


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int)
    parser.add_argument("--save-db", action="store_true")
    parser.add_argument("--output")
    parser.add_argument("--visible", action="store_true", help="Show browser")
    args = parser.parse_args()
    
    scraper = BenchmarkScraper(headless=not args.visible)
    properties = await scraper.scrape_all(limit=args.limit)
    
    print(f"\n{'='*70}")
    print("📊 SUMMARY")
    print(f"{'='*70}")
    
    with_pricing = [p for p in properties if p.quotes]
    print(f"Properties: {len(properties)}")
    print(f"With pricing: {len(with_pricing)}")
    print(f"Quotes: {sum(len(p.quotes) for p in properties)}")
    
    if with_pricing:
        adrs = [float(p.avg_adr) for p in with_pricing]
        print(f"Avg ADR: ${sum(adrs)/len(adrs):.0f}/night")
        print(f"Range: ${min(adrs):.0f} - ${max(adrs):.0f}")
    
    if args.save_db:
        print(f"\n💾 DB: {save_to_database(properties)}")
    
    if args.output:
        def ser(o):
            if isinstance(o, (date, datetime)): return o.isoformat()
            if isinstance(o, Decimal): return float(o)
            if hasattr(o, '__dict__'): return {k: ser(v) for k,v in o.__dict__.items()}
            if isinstance(o, list): return [ser(i) for i in o]
            return o
        with open(args.output, 'w') as f:
            json.dump([ser(p) for p in properties], f, indent=2)
        print(f"📄 Saved: {args.output}")


if __name__ == "__main__":
    asyncio.run(main())
