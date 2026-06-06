#!/usr/bin/env python3
"""
Booking & Availability Scraper for Beach Habitats

Scrapes booking calendars, availability, and pricing from vacation rental websites.
Designed to be extensible for multiple property management companies.

DATA SOURCES:
1. Website calendar widgets (JavaScript-rendered)
2. iCal feeds (if exposed)
3. Direct API calls (if discovered)

SCRAPED DATA:
- Availability calendar (booked vs available dates)
- Nightly/weekly rates by date
- Minimum stay requirements
- Check-in/check-out rules
- Seasonal pricing tiers

USAGE:
    python tools/booking_scraper.py                    # Scrape all properties
    python tools/booking_scraper.py --property 134MC  # Scrape specific property
    python tools/booking_scraper.py --discover        # Discover API endpoints
    python tools/booking_scraper.py --dry-run         # Don't update DB

REQUIREMENTS:
    pip install httpx beautifulsoup4 lxml playwright psycopg2-binary icalendar
"""

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, date, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
from decimal import Decimal
import hashlib

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

try:
    import psycopg2
    from psycopg2.extras import Json, execute_values
except ImportError:
    print("ERROR: psycopg2 not installed. Run: pip install psycopg2-binary")
    sys.exit(1)

# Optional: for JavaScript-heavy sites
try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False
    print("WARNING: playwright not installed. JavaScript rendering disabled.")
    print("         Run: pip install playwright && playwright install chromium")

# Optional: for iCal parsing
try:
    from icalendar import Calendar as ICalendar
    HAS_ICAL = True
except ImportError:
    HAS_ICAL = False
    print("WARNING: icalendar not installed. iCal parsing disabled.")
    print("         Run: pip install icalendar")


# =============================================================================
# CONFIGURATION
# =============================================================================

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://rental:rental@localhost:5433/rental_revenue"
)

# Beach Habitats website
BEACH_HABITATS_BASE = "https://www.beachhabitats30a.com"

# Common Property Management System API patterns
PMS_API_PATTERNS = {
    "escapia": {
        "calendar": "/api/v1/units/{unit_id}/availability",
        "rates": "/api/v1/units/{unit_id}/rates",
    },
    "streamline": {
        "calendar": "/api/calendar/{property_id}",
        "rates": "/api/rates/{property_id}",
    },
    "track": {
        "calendar": "/api/availability/{property_id}",
    },
    "guesty": {
        "calendar": "/api/v2/listings/{listing_id}/calendar",
    },
    "lodgify": {
        "ical": "/ical/{property_id}.ics",
    },
}


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class DateAvailability:
    """Single date availability record."""
    date: date
    available: bool
    price: Optional[Decimal] = None
    min_stay: Optional[int] = None
    check_in_allowed: bool = True
    check_out_allowed: bool = True
    booking_id: Optional[str] = None  # If booked, reference to booking


@dataclass 
class BookingRecord:
    """A confirmed booking."""
    booking_id: str
    property_code: str
    check_in: date
    check_out: date
    nights: int
    total_price: Optional[Decimal] = None
    nightly_rate: Optional[Decimal] = None
    guest_name: Optional[str] = None  # If available
    source: str = "website"  # website, airbnb, vrbo, direct, etc.
    scraped_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class PropertyCalendar:
    """Full calendar data for a property."""
    property_code: str
    property_name: str
    dates: List[DateAvailability] = field(default_factory=list)
    bookings: List[BookingRecord] = field(default_factory=list)
    
    # Pricing tiers
    base_rate: Optional[Decimal] = None
    peak_rate: Optional[Decimal] = None
    off_peak_rate: Optional[Decimal] = None
    
    # Rules
    default_min_stay: int = 1
    check_in_days: List[int] = field(default_factory=list)  # 0=Mon, 6=Sun
    check_out_days: List[int] = field(default_factory=list)
    
    # Metadata
    scraped_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source_url: Optional[str] = None
    ical_url: Optional[str] = None


# =============================================================================
# SCRAPER BASE CLASS
# =============================================================================

class BookingScraper:
    """Base class for booking/availability scrapers."""
    
    def __init__(self, use_playwright: bool = False):
        self.use_playwright = use_playwright and HAS_PLAYWRIGHT
        self.client = None
        self.browser = None
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
        }
    
    def __enter__(self):
        self.client = httpx.Client(headers=self.headers, timeout=30.0, follow_redirects=True)
        if self.use_playwright:
            self.playwright = sync_playwright().start()
            self.browser = self.playwright.chromium.launch(headless=True)
        return self
    
    def __exit__(self, *args):
        if self.client:
            self.client.close()
        if self.browser:
            self.browser.close()
            self.playwright.stop()
    
    def fetch_page(self, url: str) -> Optional[str]:
        """Fetch page content, using Playwright if needed."""
        try:
            if self.use_playwright:
                page = self.browser.new_page()
                page.goto(url, wait_until='networkidle')
                content = page.content()
                page.close()
                return content
            else:
                response = self.client.get(url)
                if response.status_code == 200:
                    return response.text
                print(f"  HTTP {response.status_code} for {url}")
                return None
        except Exception as e:
            print(f"  Error fetching {url}: {e}")
            return None
    
    def fetch_json(self, url: str) -> Optional[Dict]:
        """Fetch JSON from an API endpoint."""
        try:
            response = self.client.get(url)
            if response.status_code == 200:
                return response.json()
            return None
        except Exception as e:
            print(f"  Error fetching JSON {url}: {e}")
            return None
    
    def parse_ical(self, ical_content: str) -> List[BookingRecord]:
        """Parse iCal content into booking records."""
        if not HAS_ICAL:
            print("  iCal parsing not available")
            return []
        
        bookings = []
        try:
            cal = ICalendar.from_ical(ical_content)
            for component in cal.walk():
                if component.name == "VEVENT":
                    summary = str(component.get('summary', ''))
                    dtstart = component.get('dtstart')
                    dtend = component.get('dtend')
                    uid = str(component.get('uid', ''))
                    
                    if dtstart and dtend:
                        check_in = dtstart.dt if isinstance(dtstart.dt, date) else dtstart.dt.date()
                        check_out = dtend.dt if isinstance(dtend.dt, date) else dtend.dt.date()
                        
                        # Determine source from summary
                        source = "unknown"
                        summary_lower = summary.lower()
                        if "airbnb" in summary_lower:
                            source = "airbnb"
                        elif "vrbo" in summary_lower or "homeaway" in summary_lower:
                            source = "vrbo"
                        elif "booking.com" in summary_lower:
                            source = "booking.com"
                        elif "blocked" in summary_lower or "owner" in summary_lower:
                            source = "owner_block"
                        else:
                            source = "direct"

                        # ── Owner block filter (applied at scrape time) ──────────
                        # Owner blocks longer than 60 nights are structural holds
                        # (annual maintenance windows, long-term owner occupancy,
                        # calendar placeholders).  They skew occupancy metrics,
                        # corrupt availability signals, and inflate gap-pricing
                        # pressure.  Filter them out here so they never reach the
                        # DB.  Stays in the 30-60 night window are flagged for
                        # manual review rather than silently dropped.
                        nights = (check_out - check_in).days
                        if source == "owner_block":
                            if nights > 60:
                                print(
                                    f"  [filter] Skipping owner block >60 nights "
                                    f"({check_in} – {check_out}, {nights}n) — "
                                    f"uid={uid[:16] if uid else '?'}"
                                )
                                continue  # Drop entirely — do not add to bookings list
                            elif nights > 30:
                                print(
                                    f"  [review] Owner block 30-60 nights "
                                    f"({check_in} – {check_out}, {nights}n) — "
                                    f"flagged for manual review"
                                )
                                # Still include but tag for operator review
                                source = "owner_block_review"
                        # ─────────────────────────────────────────────────────────

                        bookings.append(BookingRecord(
                            booking_id=uid or hashlib.md5(f"{check_in}{check_out}".encode()).hexdigest()[:12],
                            property_code="",  # Set by caller
                            check_in=check_in,
                            check_out=check_out,
                            nights=nights,
                            guest_name=summary if "reserved" not in summary_lower else None,
                            source=source,
                        ))
        except Exception as e:
            print(f"  Error parsing iCal: {e}")
        
        return bookings


# =============================================================================
# BEACH HABITATS SCRAPER
# =============================================================================

class BeachHabitatsScraper(BookingScraper):
    """Scraper for beachhabitats30a.com booking data."""
    
    def __init__(self, property_url_map: Dict[str, str]):
        super().__init__(use_playwright=True)  # Site uses JS rendering
        self.property_url_map = property_url_map
        self.base_url = BEACH_HABITATS_BASE
    
    def discover_api_endpoints(self, property_slug: str) -> Dict[str, str]:
        """
        Use browser dev tools approach to discover API endpoints.
        This requires Playwright to intercept network requests.
        """
        endpoints = {}
        
        if not self.use_playwright:
            print("  Playwright required for API discovery")
            return endpoints
        
        url = f"{self.base_url}/30a-vacation-rentals/{property_slug}"
        
        try:
            page = self.browser.new_page()
            
            # Intercept network requests
            api_calls = []
            def handle_request(request):
                if any(kw in request.url.lower() for kw in ['calendar', 'availability', 'rates', 'booking', 'ical', 'api']):
                    api_calls.append({
                        'url': request.url,
                        'method': request.method,
                    })
            
            page.on('request', handle_request)
            page.goto(url, wait_until='networkidle')
            
            # Click on calendar/availability tab if exists
            try:
                page.click('text=Availability', timeout=3000)
                time.sleep(2)
            except:
                pass
            
            # Try clicking calendar navigation
            try:
                page.click('.calendar-next, .next-month, [data-action="next"]', timeout=2000)
                time.sleep(1)
            except:
                pass
            
            page.close()
            
            for call in api_calls:
                print(f"    Discovered: {call['method']} {call['url']}")
                if 'calendar' in call['url'].lower():
                    endpoints['calendar'] = call['url']
                elif 'rate' in call['url'].lower():
                    endpoints['rates'] = call['url']
                elif 'ical' in call['url'].lower() or '.ics' in call['url'].lower():
                    endpoints['ical'] = call['url']
            
        except Exception as e:
            print(f"  Discovery error: {e}")
        
        return endpoints
    
    def scrape_calendar_from_html(self, html: str) -> List[DateAvailability]:
        """
        Parse calendar availability from HTML.
        This looks for common calendar widget patterns.
        """
        dates = []
        soup = BeautifulSoup(html, 'lxml')
        
        # Look for calendar containers
        calendar_selectors = [
            '.availability-calendar',
            '.booking-calendar', 
            '.datepicker',
            '[data-calendar]',
            '.calendar-container',
            '#availability-calendar',
        ]
        
        for selector in calendar_selectors:
            calendar = soup.select_one(selector)
            if calendar:
                # Look for date cells
                date_cells = calendar.select('[data-date], .calendar-day, .day-cell')
                for cell in date_cells:
                    date_str = cell.get('data-date') or cell.get('data-day')
                    if date_str:
                        try:
                            # Parse various date formats
                            for fmt in ['%Y-%m-%d', '%m/%d/%Y', '%d-%m-%Y']:
                                try:
                                    d = datetime.strptime(date_str, fmt).date()
                                    break
                                except:
                                    continue
                            else:
                                continue
                            
                            # Determine availability from classes
                            classes = cell.get('class', [])
                            available = not any(c in ' '.join(classes).lower() 
                                               for c in ['booked', 'unavailable', 'blocked', 'reserved'])
                            
                            # Look for price
                            price = None
                            price_elem = cell.select_one('.price, .rate, [data-price]')
                            if price_elem:
                                price_text = price_elem.get('data-price') or price_elem.get_text()
                                price_match = re.search(r'[\d,]+(?:\.\d{2})?', price_text.replace(',', ''))
                                if price_match:
                                    price = Decimal(price_match.group())
                            
                            dates.append(DateAvailability(
                                date=d,
                                available=available,
                                price=price,
                            ))
                        except Exception as e:
                            continue
                break
        
        return dates
    
    def scrape_property(self, property_slug: str, property_code: str) -> Optional[PropertyCalendar]:
        """Scrape calendar data for a single property."""
        url = f"{self.base_url}/30a-vacation-rentals/{property_slug}"
        print(f"\n  Scraping: {property_slug} → {property_code}")
        print(f"  URL: {url}")
        
        calendar = PropertyCalendar(
            property_code=property_code,
            property_name=property_slug,
            source_url=url,
        )
        
        # First, try to discover API endpoints
        print("  Discovering API endpoints...")
        endpoints = self.discover_api_endpoints(property_slug)
        
        # If we found an iCal URL, use that
        if 'ical' in endpoints:
            print(f"  Found iCal: {endpoints['ical']}")
            ical_content = self.client.get(endpoints['ical']).text
            bookings = self.parse_ical(ical_content)
            for b in bookings:
                b.property_code = property_code
            calendar.bookings = bookings
            calendar.ical_url = endpoints['ical']
        
        # If we found a calendar API, use that
        if 'calendar' in endpoints:
            print(f"  Found Calendar API: {endpoints['calendar']}")
            data = self.fetch_json(endpoints['calendar'])
            if data:
                # Parse based on common API response formats
                # This would need to be customized per PMS
                pass
        
        # Fall back to HTML scraping
        if not calendar.dates and not calendar.bookings:
            print("  Falling back to HTML scraping...")
            html = self.fetch_page(url)
            if html:
                calendar.dates = self.scrape_calendar_from_html(html)
                print(f"  Found {len(calendar.dates)} date records from HTML")
        
        return calendar
    
    def scrape_all(self) -> List[PropertyCalendar]:
        """Scrape all mapped properties."""
        calendars = []
        
        for slug, code in self.property_url_map.items():
            try:
                cal = self.scrape_property(slug, code)
                if cal:
                    calendars.append(cal)
                time.sleep(2)  # Be polite
            except Exception as e:
                print(f"  Error scraping {slug}: {e}")
        
        return calendars


# =============================================================================
# DATABASE OPERATIONS
# =============================================================================

def save_availability_to_db(calendars: List[PropertyCalendar], dry_run: bool = False):
    """Save scraped availability data to database."""
    
    if dry_run:
        print("\n[DRY RUN] Would save to database:")
        for cal in calendars:
            print(f"  {cal.property_code}: {len(cal.dates)} dates, {len(cal.bookings)} bookings")
        return
    
    # Create availability table if not exists
    create_table_sql = """
    CREATE TABLE IF NOT EXISTS property_availability (
        id SERIAL PRIMARY KEY,
        property_code VARCHAR(20) NOT NULL,
        date DATE NOT NULL,
        available BOOLEAN DEFAULT TRUE,
        price DECIMAL(10, 2),
        min_stay INTEGER,
        check_in_allowed BOOLEAN DEFAULT TRUE,
        check_out_allowed BOOLEAN DEFAULT TRUE,
        booking_id VARCHAR(50),
        source VARCHAR(50) DEFAULT 'website',
        scraped_at TIMESTAMPTZ DEFAULT NOW(),
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW(),
        UNIQUE(property_code, date)
    );
    
    CREATE INDEX IF NOT EXISTS idx_availability_property_date 
    ON property_availability(property_code, date);
    
    CREATE TABLE IF NOT EXISTS property_bookings (
        id SERIAL PRIMARY KEY,
        booking_id VARCHAR(100) NOT NULL,
        property_code VARCHAR(20) NOT NULL,
        check_in DATE NOT NULL,
        check_out DATE NOT NULL,
        nights INTEGER,
        total_price DECIMAL(10, 2),
        nightly_rate DECIMAL(10, 2),
        guest_name VARCHAR(255),
        source VARCHAR(50) DEFAULT 'website',
        scraped_at TIMESTAMPTZ DEFAULT NOW(),
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW(),
        UNIQUE(property_code, booking_id)
    );
    
    CREATE INDEX IF NOT EXISTS idx_bookings_property_dates 
    ON property_bookings(property_code, check_in, check_out);
    """
    
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        
        # Create tables
        cur.execute(create_table_sql)
        
        # Insert availability records
        for cal in calendars:
            print(f"\nSaving {cal.property_code}...")
            
            # Upsert availability
            if cal.dates:
                availability_data = [
                    (
                        cal.property_code,
                        d.date,
                        d.available,
                        float(d.price) if d.price else None,
                        d.min_stay,
                        d.check_in_allowed,
                        d.check_out_allowed,
                        d.booking_id,
                        'website',
                    )
                    for d in cal.dates
                ]
                
                execute_values(cur, """
                    INSERT INTO property_availability 
                    (property_code, date, available, price, min_stay, 
                     check_in_allowed, check_out_allowed, booking_id, source)
                    VALUES %s
                    ON CONFLICT (property_code, date) DO UPDATE SET
                        available = EXCLUDED.available,
                        price = EXCLUDED.price,
                        min_stay = EXCLUDED.min_stay,
                        check_in_allowed = EXCLUDED.check_in_allowed,
                        check_out_allowed = EXCLUDED.check_out_allowed,
                        booking_id = EXCLUDED.booking_id,
                        source = EXCLUDED.source,
                        scraped_at = NOW(),
                        updated_at = NOW()
                """, availability_data)
                print(f"  Saved {len(availability_data)} availability records")
            
            # Upsert bookings
            # Second safety net: strip any owner_block >60n that somehow
            # slipped through the parse_ical filter (e.g. from HTML scraping).
            valid_bookings = [
                b for b in cal.bookings
                if not (b.source == "owner_block" and b.nights > 60)
            ]
            if cal.bookings:
                booking_data = [
                    (
                        b.booking_id,
                        b.property_code,
                        b.check_in,
                        b.check_out,
                        b.nights,
                        float(b.total_price) if b.total_price else None,
                        float(b.nightly_rate) if b.nightly_rate else None,
                        b.guest_name,
                        b.source,
                    )
                    for b in valid_bookings
                ]
                
                execute_values(cur, """
                    INSERT INTO property_bookings
                    (booking_id, property_code, check_in, check_out, nights,
                     total_price, nightly_rate, guest_name, source)
                    VALUES %s
                    ON CONFLICT (property_code, booking_id) DO UPDATE SET
                        check_in = EXCLUDED.check_in,
                        check_out = EXCLUDED.check_out,
                        nights = EXCLUDED.nights,
                        total_price = EXCLUDED.total_price,
                        nightly_rate = EXCLUDED.nightly_rate,
                        guest_name = EXCLUDED.guest_name,
                        source = EXCLUDED.source,
                        scraped_at = NOW(),
                        updated_at = NOW()
                """, booking_data)
                print(f"  Saved {len(booking_data)} booking records")
        
        conn.commit()
        cur.close()
        conn.close()
        print("\n✓ Database updated successfully")
        
    except Exception as e:
        print(f"\n✗ Database error: {e}")
        raise


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Scrape booking/availability data")
    parser.add_argument("--property", help="Scrape specific property code")
    parser.add_argument("--discover", action="store_true", help="Discover API endpoints only")
    parser.add_argument("--dry-run", action="store_true", help="Don't update database")
    args = parser.parse_args()
    
    # Import property URL map from enrichment scraper
    # In production, this would be shared config
    from property_enrichment_scraper import PROPERTY_URL_MAP
    
    # Reverse map: code → slug
    code_to_slug = {v: k for k, v in PROPERTY_URL_MAP.items()}
    
    print("=" * 70)
    print("BOOKING & AVAILABILITY SCRAPER")
    print("=" * 70)
    
    if args.discover:
        # Discovery mode: find API endpoints
        print("\nDiscovering API endpoints...")
        with BeachHabitatsScraper(PROPERTY_URL_MAP) as scraper:
            test_slug = list(PROPERTY_URL_MAP.keys())[0]
            endpoints = scraper.discover_api_endpoints(test_slug)
            print(f"\nDiscovered endpoints for {test_slug}:")
            for name, url in endpoints.items():
                print(f"  {name}: {url}")
    else:
        # Scraping mode
        if args.property:
            # Single property
            if args.property not in code_to_slug:
                print(f"Unknown property code: {args.property}")
                sys.exit(1)
            slug = code_to_slug[args.property]
            url_map = {slug: args.property}
        else:
            url_map = PROPERTY_URL_MAP
        
        print(f"\nScraping {len(url_map)} properties...")
        
        with BeachHabitatsScraper(url_map) as scraper:
            calendars = scraper.scrape_all()
        
        # Save to database
        save_availability_to_db(calendars, dry_run=args.dry_run)
        
        # Summary
        print("\n" + "=" * 70)
        print("SUMMARY")
        print("=" * 70)
        total_dates = sum(len(c.dates) for c in calendars)
        total_bookings = sum(len(c.bookings) for c in calendars)
        print(f"Properties scraped: {len(calendars)}")
        print(f"Total date records: {total_dates}")
        print(f"Total bookings found: {total_bookings}")


if __name__ == "__main__":
    main()
