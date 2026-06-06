#!/usr/bin/env python3
"""
Beach Habitats Booking & Availability Scraper

Extracts booking/availability data from beachhabitats30a.com property pages.
The site uses a Drupal-based system with rcItemAvailForm configuration containing:
- avail: Date ranges with availability status
- restr: Minimum stay restrictions by date
- turn: Check-in/check-out/blocked day markers

USAGE:
    python tools/bh_booking_scraper.py                    # Scrape all properties
    python tools/bh_booking_scraper.py --property 134MC   # Scrape specific property
    python tools/bh_booking_scraper.py --dry-run          # Don't update database
    python tools/bh_booking_scraper.py --output json      # Output to JSON file

REQUIREMENTS:
    pip install playwright httpx beautifulsoup4 lxml psycopg2-binary
    playwright install chromium
"""

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, date, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("ERROR: Playwright required. Run: pip install playwright && playwright install chromium")
    sys.exit(1)

from bs4 import BeautifulSoup

try:
    import psycopg2
    from psycopg2.extras import execute_values
    HAS_POSTGRES = True
except ImportError:
    HAS_POSTGRES = False
    print("WARNING: psycopg2 not installed. Database operations disabled.")


# =============================================================================
# CONFIGURATION
# =============================================================================

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://rental:rental@localhost:5433/rental_revenue"
)

BASE_URL = "https://www.beachhabitats30a.com"

# Property URL map: website slug → database property_code
# Import from property_enrichment_scraper or define here
PROPERTY_URL_MAP = {
    # WaterColor properties
    "134-mystic-cobalt": "134MC",
    "108-silver-laurel-way": "108SLW",
    "17-lyonia-lane": "17LL",
    "359-spartina-circle": "359SC",
    "48-seawalk-circle": "48SWC",
    "49-clipper-st": "49CS",
    "61-w-cobia-run-102": "61WCR",
    "68-red-fern": "68RF",
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
    "1777-e-county-hwy-30a-unit-102": "102-1785",
    "1785-e-county-hwy-30a-unit-104": "104-1785",
    "42-flatwood-st": "42FWS",
    "18-crossvine-circle": "18CC",
    "113-bartons-way-royal-blue": "113BW",
    
    # Seagrove properties  
    "100-s-spooky-lane-unit-2c": "100SSL2C",
    "100-s-spooky-lane-unit-2d": "100SSL2D",
    "103-compass-point-ii": "103CP2",
    "hms-sunrisesunset": "HMS",
    
    # Carillon Beach
    "sea-la-vie": "111VW",
    
    # Confirmed mappings from cross-reference
    "vermillion-sunsets": "119VW",
    "southern-charm": "134SC",
    "idle-hour": "42FWS",
    
    # New properties (not in original Excel)
    "casa-blanco": "CASAB",
    "emerald-bliss": "EMERBLS",
    "main-st-getaway": "MAINST",
    "vitamin-sea": "VITSEA",
    
    # Ambiguous - need manual verification
    "close-enough": "CLOSENUF",
    "southern-grace": "STHGRACE",
    "sweet-liberty": "SWTLIB",
    
    # Additional properties found in form dropdown
    "azalea-abbey": "AZALEA",
    "3-by-the-sea": "3BTSEA",
    "sun-kissed-on-hickory": "SUNKISS",
    "the-laurel-landing": "LAUREL",
    "here-comes-the-sun": "HERECOME",
}


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class DateAvailability:
    """Single date availability record."""
    date: date
    available: bool
    min_stay: Optional[int] = None
    check_in_allowed: bool = True
    check_out_allowed: bool = True
    status: str = "available"  # available, booked, blocked, check_in, check_out


@dataclass
class BookingPeriod:
    """A booking/blocked period."""
    check_in: date
    check_out: date
    nights: int
    source: str = "website"  # website scrape


@dataclass
class PropertyCalendar:
    """Full calendar data for a property."""
    property_code: str
    property_slug: str
    property_name: str
    entity_id: int  # Drupal entity ID
    
    # Raw data from website
    avail_ranges: List[Dict] = field(default_factory=list)
    restrictions: List[Dict] = field(default_factory=list)
    turnovers: List[Dict] = field(default_factory=list)
    
    # Processed data
    dates: List[DateAvailability] = field(default_factory=list)
    bookings: List[BookingPeriod] = field(default_factory=list)
    
    # Metadata
    scraped_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    min_stay_default: int = 3
    max_stay_default: int = 365


# =============================================================================
# SCRAPER
# =============================================================================

class BeachHabitsBookingScraper:
    """Scraper for Beach Habitats booking/availability data."""
    
    def __init__(self):
        self.browser = None
        self.playwright = None
    
    def __enter__(self):
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(headless=True)
        return self
    
    def __exit__(self, *args):
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()
    
    def extract_calendar_config(self, html: str) -> Optional[Dict]:
        """Extract rcItemAvailForm configuration from page HTML."""
        
        # Look for the Drupal settings with availability data
        pattern = r"'rcItemAvailForm'\s*:\s*\[(\{[\s\S]*?\})\]"
        match = re.search(pattern, html)
        
        if not match:
            # Try alternative pattern
            pattern = r'"rcItemAvailForm"\s*:\s*\[(\{[\s\S]*?\})\]'
            match = re.search(pattern, html)
        
        if not match:
            return None
        
        config_str = match.group(1)
        
        # Parse the JavaScript object
        # Convert JS notation to JSON
        config_str = re.sub(r'!0', 'true', config_str)
        config_str = re.sub(r'!1', 'false', config_str)
        config_str = re.sub(r"'", '"', config_str)
        
        # Handle unquoted keys
        config_str = re.sub(r'(\w+):', r'"\1":', config_str)
        
        # Fix null values
        config_str = re.sub(r':null', ':null', config_str)
        
        try:
            config = json.loads(config_str)
            return config
        except json.JSONDecodeError:
            # Fall back to regex extraction
            return self._extract_arrays_regex(html)
    
    def _extract_arrays_regex(self, html: str) -> Dict:
        """Extract availability arrays using regex (fallback)."""
        result = {}
        
        # Extract avail array
        avail_match = re.search(r"'avail'\s*:\s*\[([\s\S]*?)\]", html)
        if avail_match:
            avail_str = '[' + avail_match.group(1) + ']'
            avail_str = avail_str.replace("'", '"')
            try:
                result['avail'] = json.loads(avail_str)
            except:
                result['avail'] = self._parse_avail_items(avail_match.group(1))
        
        # Extract restr array
        restr_match = re.search(r"'restr'\s*:\s*\[([\s\S]*?)\]", html)
        if restr_match:
            restr_str = '[' + restr_match.group(1) + ']'
            restr_str = restr_str.replace("'", '"').replace('null', 'null')
            try:
                result['restr'] = json.loads(restr_str)
            except:
                result['restr'] = []
        
        # Extract turn array
        turn_match = re.search(r"'turn'\s*:\s*\[([\s\S]*?)\]", html)
        if turn_match:
            turn_str = '[' + turn_match.group(1) + ']'
            turn_str = turn_str.replace("'", '"')
            try:
                result['turn'] = json.loads(turn_str)
            except:
                result['turn'] = []
        
        # Extract entity ID
        eid_match = re.search(r"'eid'\s*:\s*'(\d+)'", html)
        if eid_match:
            result['eid'] = int(eid_match.group(1))
        
        # Extract min stay default
        mns_match = re.search(r"'mns'\s*:\s*'(\d+)'", html)
        if mns_match:
            result['mns'] = int(mns_match.group(1))
        
        return result
    
    def _parse_avail_items(self, avail_str: str) -> List[Dict]:
        """Parse availability items from string."""
        items = []
        pattern = r"\{'b':'([^']+)','e':'([^']+)','a':'([^']+)'"
        for match in re.finditer(pattern, avail_str):
            items.append({
                'b': match.group(1),
                'e': match.group(2),
                'a': match.group(3),
            })
        return items
    
    def process_availability(self, config: Dict) -> Tuple[List[DateAvailability], List[BookingPeriod]]:
        """Process raw availability config into structured data."""
        dates = []
        bookings = []
        
        avail_ranges = config.get('avail', [])
        restrictions = config.get('restr', [])
        turnovers = config.get('turn', [])
        
        # Build restriction lookup (date → min_stay)
        restriction_map = {}
        for r in restrictions:
            try:
                start = datetime.strptime(r['b'], '%Y-%m-%d').date()
                end = datetime.strptime(r['e'], '%Y-%m-%d').date()
                min_stay = r.get('mn', 3)
                
                current = start
                while current <= end:
                    restriction_map[current] = min_stay
                    current += timedelta(days=1)
            except:
                continue
        
        # Build turnover lookup (date → type)
        turnover_map = {}
        for t in turnovers:
            try:
                start = datetime.strptime(t['b'], '%Y-%m-%d').date()
                end = datetime.strptime(t['e'], '%Y-%m-%d').date()
                turn_type = t.get('t', '')
                
                current = start
                while current <= end:
                    turnover_map[current] = turn_type
                    current += timedelta(days=1)
            except:
                continue
        
        # Process availability ranges
        for av in avail_ranges:
            try:
                start = datetime.strptime(av['b'], '%Y-%m-%d').date()
                end = datetime.strptime(av['e'], '%Y-%m-%d').date()
                available = av.get('a', '1') == '1'
                
                # If not available, it's a booking
                if not available:
                    bookings.append(BookingPeriod(
                        check_in=start,
                        check_out=end,
                        nights=(end - start).days,
                    ))
                
                # Generate daily records
                current = start
                while current <= end:
                    turn_type = turnover_map.get(current, '')
                    
                    status = "available"
                    if not available:
                        if turn_type == 'X':
                            status = "booked"
                        elif turn_type == 'I':
                            status = "check_in"
                        elif turn_type == 'O':
                            status = "check_out"
                        else:
                            status = "blocked"
                    
                    dates.append(DateAvailability(
                        date=current,
                        available=available,
                        min_stay=restriction_map.get(current, 3),
                        check_in_allowed=(turn_type != 'X' and turn_type != 'O'),
                        check_out_allowed=(turn_type != 'X' and turn_type != 'I'),
                        status=status,
                    ))
                    
                    current += timedelta(days=1)
            except Exception as e:
                print(f"    Error processing range: {e}")
                continue
        
        # Sort by date
        dates.sort(key=lambda x: x.date)
        bookings.sort(key=lambda x: x.check_in)
        
        return dates, bookings
    
    def scrape_property(self, slug: str, property_code: str) -> Optional[PropertyCalendar]:
        """Scrape calendar data for a single property."""
        url = f"{BASE_URL}/30a-vacation-rentals/{slug}"
        print(f"\n  Scraping: {slug} → {property_code}")
        
        try:
            page = self.browser.new_page()
            page.goto(url, wait_until='networkidle', timeout=30000)
            html = page.content()
            
            # Get property name
            soup = BeautifulSoup(html, 'lxml')
            title = soup.find('h1')
            property_name = title.get_text(strip=True) if title else slug
            
            # Extract calendar config
            config = self._extract_arrays_regex(html)
            
            if not config.get('avail'):
                print(f"    ⚠ No availability data found")
                page.close()
                return None
            
            # Process into structured data
            dates, bookings = self.process_availability(config)
            
            calendar = PropertyCalendar(
                property_code=property_code,
                property_slug=slug,
                property_name=property_name,
                entity_id=config.get('eid', 0),
                avail_ranges=config.get('avail', []),
                restrictions=config.get('restr', []),
                turnovers=config.get('turn', []),
                dates=dates,
                bookings=bookings,
                min_stay_default=config.get('mns', 3),
            )
            
            print(f"    ✓ {property_name}")
            print(f"      Entity ID: {calendar.entity_id}")
            print(f"      Date records: {len(dates)}")
            print(f"      Bookings found: {len(bookings)}")
            
            # Show upcoming bookings
            today = date.today()
            upcoming = [b for b in bookings if b.check_in >= today][:3]
            if upcoming:
                print(f"      Upcoming bookings:")
                for b in upcoming:
                    print(f"        {b.check_in} → {b.check_out} ({b.nights} nights)")
            
            page.close()
            return calendar
            
        except Exception as e:
            print(f"    ✗ Error: {e}")
            return None
    
    def scrape_all(self, property_map: Dict[str, str]) -> List[PropertyCalendar]:
        """Scrape all properties in the map."""
        calendars = []
        
        for slug, code in property_map.items():
            try:
                calendar = self.scrape_property(slug, code)
                if calendar:
                    calendars.append(calendar)
            except Exception as e:
                print(f"    ✗ Error scraping {slug}: {e}")
        
        return calendars


# =============================================================================
# DATABASE OPERATIONS
# =============================================================================

def save_to_database(calendars: List[PropertyCalendar], dry_run: bool = False):
    """Save scraped data to PostgreSQL."""
    
    if not HAS_POSTGRES:
        print("\n⚠ PostgreSQL not available, skipping database save")
        return
    
    if dry_run:
        print("\n[DRY RUN] Would save to database:")
        for cal in calendars:
            print(f"  {cal.property_code}: {len(cal.dates)} dates, {len(cal.bookings)} bookings")
        return
    
    create_tables_sql = """
    -- Daily availability
    CREATE TABLE IF NOT EXISTS property_availability (
        id SERIAL PRIMARY KEY,
        property_code VARCHAR(20) NOT NULL,
        date DATE NOT NULL,
        available BOOLEAN DEFAULT TRUE,
        min_stay INTEGER,
        check_in_allowed BOOLEAN DEFAULT TRUE,
        check_out_allowed BOOLEAN DEFAULT TRUE,
        status VARCHAR(20) DEFAULT 'available',
        scraped_at TIMESTAMPTZ DEFAULT NOW(),
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW(),
        UNIQUE(property_code, date)
    );
    
    CREATE INDEX IF NOT EXISTS idx_avail_property_date 
    ON property_availability(property_code, date);
    
    CREATE INDEX IF NOT EXISTS idx_avail_date_available
    ON property_availability(date, available);
    
    -- Booking periods
    CREATE TABLE IF NOT EXISTS property_bookings (
        id SERIAL PRIMARY KEY,
        property_code VARCHAR(20) NOT NULL,
        check_in DATE NOT NULL,
        check_out DATE NOT NULL,
        nights INTEGER,
        source VARCHAR(50) DEFAULT 'website',
        scraped_at TIMESTAMPTZ DEFAULT NOW(),
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW(),
        UNIQUE(property_code, check_in, check_out)
    );
    
    CREATE INDEX IF NOT EXISTS idx_bookings_property_dates 
    ON property_bookings(property_code, check_in, check_out);
    
    CREATE INDEX IF NOT EXISTS idx_bookings_checkin
    ON property_bookings(check_in);
    """
    
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        
        # Create tables
        cur.execute(create_tables_sql)
        
        for cal in calendars:
            print(f"\n  Saving {cal.property_code}...")
            
            # Upsert availability
            if cal.dates:
                avail_data = [
                    (
                        cal.property_code,
                        d.date,
                        d.available,
                        d.min_stay,
                        d.check_in_allowed,
                        d.check_out_allowed,
                        d.status,
                    )
                    for d in cal.dates
                ]
                
                execute_values(cur, """
                    INSERT INTO property_availability 
                    (property_code, date, available, min_stay, 
                     check_in_allowed, check_out_allowed, status)
                    VALUES %s
                    ON CONFLICT (property_code, date) DO UPDATE SET
                        available = EXCLUDED.available,
                        min_stay = EXCLUDED.min_stay,
                        check_in_allowed = EXCLUDED.check_in_allowed,
                        check_out_allowed = EXCLUDED.check_out_allowed,
                        status = EXCLUDED.status,
                        scraped_at = NOW(),
                        updated_at = NOW()
                """, avail_data)
                print(f"    ✓ {len(avail_data)} availability records")
            
            # Upsert bookings
            if cal.bookings:
                booking_data = [
                    (
                        cal.property_code,
                        b.check_in,
                        b.check_out,
                        b.nights,
                        b.source,
                    )
                    for b in cal.bookings
                ]
                
                execute_values(cur, """
                    INSERT INTO property_bookings
                    (property_code, check_in, check_out, nights, source)
                    VALUES %s
                    ON CONFLICT (property_code, check_in, check_out) DO UPDATE SET
                        nights = EXCLUDED.nights,
                        source = EXCLUDED.source,
                        scraped_at = NOW(),
                        updated_at = NOW()
                """, booking_data)
                print(f"    ✓ {len(booking_data)} booking records")
        
        conn.commit()
        cur.close()
        conn.close()
        print("\n✓ Database updated successfully")
        
    except Exception as e:
        print(f"\n✗ Database error: {e}")
        raise


def save_to_json(calendars: List[PropertyCalendar], output_file: Path):
    """Save scraped data to JSON file."""
    
    def serialize(obj):
        if isinstance(obj, (date, datetime)):
            return obj.isoformat()
        if hasattr(obj, '__dict__'):
            return {k: serialize(v) for k, v in obj.__dict__.items()}
        if isinstance(obj, list):
            return [serialize(i) for i in obj]
        if isinstance(obj, dict):
            return {k: serialize(v) for k, v in obj.items()}
        return obj
    
    data = [serialize(asdict(cal)) for cal in calendars]
    
    with open(output_file, 'w') as f:
        json.dump(data, f, indent=2, default=str)
    
    print(f"\n✓ Saved to {output_file}")


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Scrape Beach Habitats booking data")
    parser.add_argument("--property", help="Scrape specific property code")
    parser.add_argument("--dry-run", action="store_true", help="Don't update database")
    parser.add_argument("--output", choices=["db", "json", "both"], default="db",
                       help="Output format (default: db)")
    parser.add_argument("--limit", type=int, help="Limit number of properties to scrape")
    args = parser.parse_args()
    
    print("=" * 70)
    print("BEACH HABITATS BOOKING SCRAPER")
    print(f"Started: {datetime.now().isoformat()}")
    print("=" * 70)
    
    # Determine which properties to scrape
    if args.property:
        # Find slug for this property code
        code_to_slug = {v: k for k, v in PROPERTY_URL_MAP.items()}
        if args.property not in code_to_slug:
            print(f"Unknown property code: {args.property}")
            print(f"Available codes: {', '.join(sorted(code_to_slug.keys()))}")
            sys.exit(1)
        slug = code_to_slug[args.property]
        property_map = {slug: args.property}
    else:
        property_map = PROPERTY_URL_MAP
        if args.limit:
            property_map = dict(list(property_map.items())[:args.limit])
    
    print(f"\nScraping {len(property_map)} properties...")
    
    # Scrape
    with BeachHabitsBookingScraper() as scraper:
        calendars = scraper.scrape_all(property_map)
    
    # Output
    if args.output in ["db", "both"]:
        save_to_database(calendars, dry_run=args.dry_run)
    
    if args.output in ["json", "both"]:
        output_file = Path(__file__).parent.parent / "data" / f"bookings_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        output_file.parent.mkdir(exist_ok=True)
        save_to_json(calendars, output_file)
    
    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    
    total_dates = sum(len(c.dates) for c in calendars)
    total_bookings = sum(len(c.bookings) for c in calendars)
    
    print(f"Properties scraped: {len(calendars)}/{len(property_map)}")
    print(f"Total date records: {total_dates}")
    print(f"Total bookings: {total_bookings}")
    
    # Show properties with most bookings
    if calendars:
        print("\nProperties by booking count:")
        sorted_cals = sorted(calendars, key=lambda x: len(x.bookings), reverse=True)
        for cal in sorted_cals[:5]:
            print(f"  {cal.property_code}: {len(cal.bookings)} bookings")
    
    print("\n" + "=" * 70)
    print("COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
