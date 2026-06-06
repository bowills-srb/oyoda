#!/usr/bin/env python3
"""
Beach Habitats Pricing/ADR Scraper

Extracts nightly rates by setting dates via JavaScript and capturing the AJAX response.

USAGE:
    python tools/bh_pricing_scraper.py --limit 5
    python tools/bh_pricing_scraper.py --property 134MC
"""

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("ERROR: Playwright required. Run: pip install playwright && playwright install chromium")
    sys.exit(1)

try:
    import psycopg2
    from psycopg2.extras import execute_values
    HAS_POSTGRES = True
except ImportError:
    HAS_POSTGRES = False


DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://rental:rental@localhost:5433/rental_revenue")
BASE_URL = "https://www.beachhabitats30a.com"

PROPERTY_URL_MAP = {
    "134-mystic-cobalt": "134MC",
    "108-silver-laurel-way": "108SLW",
    "17-lyonia-lane": "17LL",
    "359-spartina-circle": "359SC",
    "48-seawalk-circle": "48SWC",
    "49-clipper-st": "49CS",
    "61-w-cobia-run-102": "61WCR",
    "90-mystic-cobalt-st": "90MC",
    "116-w-summersweet-lane": "116WSL",
    "120-sunflower-st": "120SF",
    "178-spartina-cir": "178SC",
    "202-28-watercolor-blvd": "202-28WB",
    "245-w-lake-forest-dr": "245WLF",
    "288-western-lake-dr": "288WLD",
    "621-western-lake-dr": "621WLD",
    "860-western-lake-drive": "860WLD",
    "1312-western-lake-dr": "1312WLD",
    "1680-e-county-hwy-30a-unit-303-watercolor": "303-1680",
    "1735-e-county-hwy-30a-unit-303": "303-1735",
    "1785-e-county-hwy-30a-unit-104": "104-1785",
    "42-flatwood-st": "42FWS",
    "18-crossvine-circle": "18CC",
    "113-bartons-way-royal-blue": "113BW",
    "100-s-spooky-lane-unit-2c": "100SSL2C",
    "100-s-spooky-lane-unit-2d": "100SSL2D",
    "103-compass-point-ii": "103CP2",
    "132-e-kingston-rd": "132EKR",
    "hms-sunrisesunset": "HMS",
    "sea-la-vie": "111VW",
    "vermillion-sunsets": "119VW",
    "southern-charm": "134SC",
    "azalea-abbey": "AZALEA",
}


@dataclass
class PricingQuote:
    property_code: str
    check_in: date
    check_out: date
    nights: int
    lodging: Decimal = Decimal("0")
    cleaning_fee: Decimal = Decimal("0")
    taxes: Decimal = Decimal("0")
    total: Decimal = Decimal("0")
    adr: Decimal = Decimal("0")
    scraped_at: datetime = field(default_factory=datetime.now)


@dataclass 
class PropertyPricing:
    property_code: str
    property_slug: str
    quotes: List[PricingQuote] = field(default_factory=list)
    avg_adr: Decimal = Decimal("0")
    min_adr: Decimal = Decimal("0")
    max_adr: Decimal = Decimal("0")


class PricingScraper:
    
    def __init__(self):
        self.playwright = None
        self.browser = None
        self.captured_pricing = []
    
    def __enter__(self):
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(headless=True)
        return self
    
    def __exit__(self, *args):
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()
    
    def parse_pricing_content(self, content: str) -> Dict:
        """Parse dollar amounts from pricing HTML content."""
        result = {'lodging': 0, 'taxes': 0, 'total': 0, 'cleaning': 0}
        
        # Unescape
        content = content.replace('\\u003C', '<').replace('\\u003E', '>')
        content = content.replace('\\u0022', '"').replace('\\/', '/')
        
        # Find lodging
        m = re.search(r'Lodging[^$]*\$([\d,]+(?:\.\d{2})?)', content)
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
        
        # Find all dollar amounts, total is usually the largest
        amounts = re.findall(r'\$([\d,]+(?:\.\d{2})?)', content)
        if amounts:
            parsed = [float(a.replace(',', '')) for a in amounts]
            result['total'] = max(parsed)
        
        return result
    
    def scrape_property(self, slug: str, property_code: str) -> Optional[PropertyPricing]:
        """Scrape pricing for a single property."""
        
        url = f"{BASE_URL}/30a-vacation-rentals/{slug}"
        print(f"\n  {property_code}: {slug}")
        
        context = self.browser.new_context()
        page = context.new_page()
        
        # Capture pricing responses
        pricing_responses = []
        
        def capture_response(response):
            if 'pricing' in response.url and 'quote' in response.url:
                try:
                    body = response.text()
                    if '$' in body:
                        pricing_responses.append(body)
                except:
                    pass
        
        page.on('response', capture_response)
        
        try:
            page.goto(url, wait_until='networkidle', timeout=30000)
            
            # Get available ranges
            html = page.content()
            avail_ranges = []
            for m in re.finditer(r"\{'b':'([^']+)','e':'([^']+)','a':'1','q':'1'", html):
                avail_ranges.append((m.group(1), m.group(2)))
            
            if not avail_ranges:
                print(f"    No available ranges")
                context.close()
                return None
            
            pricing = PropertyPricing(property_code=property_code, property_slug=slug)
            today = date.today()
            quotes_collected = 0
            max_quotes = 3
            
            for start_str, end_str in avail_ranges:
                if quotes_collected >= max_quotes:
                    break
                
                try:
                    start = date.fromisoformat(start_str)
                    end = date.fromisoformat(end_str)
                    
                    if end <= today or (end - start).days < 3:
                        continue
                    
                    check_in = max(start, today + timedelta(days=1))
                    check_out = min(check_in + timedelta(days=3), end)
                    nights = (check_out - check_in).days
                    
                    if nights < 3:
                        continue
                    
                    # Set dates via JavaScript
                    begin_str = check_in.strftime('%m/%d/%Y')
                    end_fmt = check_out.strftime('%m/%d/%Y')
                    
                    pricing_responses.clear()
                    
                    page.evaluate(f"""
                        () => {{
                            const b = document.querySelector('input.begin');
                            const e = document.querySelector('input.end');
                            if (b && e) {{
                                b.value = '{begin_str}';
                                e.value = '{end_fmt}';
                                b.dispatchEvent(new Event('change', {{bubbles: true}}));
                                e.dispatchEvent(new Event('change', {{bubbles: true}}));
                            }}
                        }}
                    """)
                    
                    # Wait for AJAX
                    page.wait_for_timeout(2000)
                    
                    # Check for captured pricing
                    if pricing_responses:
                        for resp in pricing_responses:
                            try:
                                data = json.loads(resp)
                                content = data.get('content', '')
                                parsed = self.parse_pricing_content(content)
                                
                                if parsed['total'] > 0:
                                    lodging = Decimal(str(parsed['lodging']))
                                    adr = lodging / nights if lodging > 0 else Decimal(str(parsed['total'])) / nights * Decimal("0.85")
                                    
                                    quote = PricingQuote(
                                        property_code=property_code,
                                        check_in=check_in,
                                        check_out=check_out,
                                        nights=nights,
                                        lodging=lodging,
                                        cleaning_fee=Decimal(str(parsed['cleaning'])),
                                        taxes=Decimal(str(parsed['taxes'])),
                                        total=Decimal(str(parsed['total'])),
                                        adr=adr,
                                    )
                                    pricing.quotes.append(quote)
                                    quotes_collected += 1
                                    print(f"    💰 {check_in} - {check_out}: ${parsed['total']:.0f} total, ${float(adr):.0f}/night ADR")
                                    break
                            except:
                                pass
                
                except Exception as e:
                    continue
            
            # Calculate aggregates
            if pricing.quotes:
                adrs = [q.adr for q in pricing.quotes if q.adr > 0]
                if adrs:
                    pricing.avg_adr = sum(adrs) / len(adrs)
                    pricing.min_adr = min(adrs)
                    pricing.max_adr = max(adrs)
            
            context.close()
            return pricing if pricing.quotes else None
            
        except Exception as e:
            print(f"    Error: {e}")
            context.close()
            return None
    
    def scrape_all(self, property_map: Dict[str, str]) -> List[PropertyPricing]:
        results = []
        for slug, code in property_map.items():
            pricing = self.scrape_property(slug, code)
            if pricing:
                results.append(pricing)
        return results


def save_to_database(data: List[PropertyPricing]):
    if not HAS_POSTGRES or not data:
        return
    
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS property_pricing (
                id SERIAL PRIMARY KEY,
                property_code VARCHAR(20) NOT NULL,
                check_in DATE NOT NULL,
                check_out DATE NOT NULL,
                nights INTEGER NOT NULL,
                lodging NUMERIC(10,2),
                cleaning_fee NUMERIC(10,2),
                taxes NUMERIC(10,2),
                total NUMERIC(10,2),
                adr NUMERIC(10,2),
                scraped_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(property_code, check_in, check_out)
            )
        """)
        
        for p in data:
            for q in p.quotes:
                cur.execute("""
                    INSERT INTO property_pricing 
                    (property_code, check_in, check_out, nights, lodging, cleaning_fee, taxes, total, adr)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (property_code, check_in, check_out) DO UPDATE SET
                        lodging = EXCLUDED.lodging, taxes = EXCLUDED.taxes,
                        total = EXCLUDED.total, adr = EXCLUDED.adr, scraped_at = NOW()
                """, (q.property_code, q.check_in, q.check_out, q.nights,
                      float(q.lodging), float(q.cleaning_fee), float(q.taxes),
                      float(q.total), float(q.adr)))
        
        conn.commit()
        cur.close()
        conn.close()
        print("\n✓ Saved to database")
    except Exception as e:
        print(f"\n✗ Database error: {e}")


def save_to_json(data: List[PropertyPricing], path: Path):
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
    
    with open(path, 'w') as f:
        json.dump([serialize(p) for p in data], f, indent=2)
    print(f"\n✓ Saved to {path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--property", help="Single property code")
    parser.add_argument("--limit", type=int, help="Limit properties")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    
    print("=" * 60)
    print("BEACH HABITATS PRICING SCRAPER")
    print("=" * 60)
    
    if args.property:
        code_to_slug = {v: k for k, v in PROPERTY_URL_MAP.items()}
        if args.property not in code_to_slug:
            print(f"Unknown: {args.property}")
            return
        prop_map = {code_to_slug[args.property]: args.property}
    else:
        prop_map = PROPERTY_URL_MAP
        if args.limit:
            prop_map = dict(list(prop_map.items())[:args.limit])
    
    print(f"\nScraping {len(prop_map)} properties...")
    
    with PricingScraper() as scraper:
        results = scraper.scrape_all(prop_map)
    
    if not args.dry_run:
        save_to_database(results)
    
    out_file = Path(__file__).parent.parent / "data" / f"pricing_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out_file.parent.mkdir(exist_ok=True)
    save_to_json(results, out_file)
    
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Properties with pricing: {len(results)}/{len(prop_map)}")
    print(f"Total quotes: {sum(len(p.quotes) for p in results)}")
    
    if results:
        print("\nADR by Property:")
        for p in sorted(results, key=lambda x: x.avg_adr, reverse=True):
            print(f"  {p.property_code}: ${p.avg_adr:.0f}/night")


if __name__ == "__main__":
    main()
