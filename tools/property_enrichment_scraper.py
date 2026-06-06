#!/usr/bin/env python3
"""
Property Enrichment Scraper

Scrapes beachhabitats30a.com and Breezeway guidebooks to enrich
the properties table with detailed amenity and operational data.

USAGE:
    # Scrape all properties
    python tools/property_enrichment_scraper.py

    # Scrape specific property
    python tools/property_enrichment_scraper.py --property "134-mystic-cobalt"

    # Dry run (don't update DB)
    python tools/property_enrichment_scraper.py --dry-run

REQUIREMENTS:
    pip install httpx beautifulsoup4 lxml psycopg2-binary
"""

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set
from decimal import Decimal
from urllib.parse import quote

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
    from psycopg2.extras import Json
except ImportError:
    print("ERROR: psycopg2 not installed. Run: pip install psycopg2-binary")
    sys.exit(1)


# =============================================================================
# CONFIGURATION
# =============================================================================

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://rental:rental@localhost:5433/rental_revenue"
)

BASE_URL = "https://www.beachhabitats30a.com"

# Known property name to URL slug mappings (from website dropdown)
PROPERTY_SLUGS = [
    "100-s-spooky-lane-unit-2c",
    "100-s-spooky-lane-unit-2d",
    "103-compass-point-ii",
    "108-silver-laurel-way",
    "113-bartons-way-royal-blue",
    "116-w-summersweet-lane",
    "120-sunflower-st",
    "1312-western-lake-dr",
    "132-e-kingston-rd",
    "134-mystic-cobalt",
    "1680-e-county-hwy-30a-unit-303-watercolor",
    "17-lyonia-lane",
    "1735-e-county-hwy-30a-unit-303",
    "178-spartina-cir",
    "1785-e-county-hwy-30a-unit-102",
    "1785-e-county-hwy-30a-unit-104",
    "18-crossvine-circle",
    "202-28-watercolor-blvd",
    "245-w-lake-forest-dr",
    "288-western-lake-dr",
    "3-by-the-sea",
    "359-spartina-circle",
    "42-flatwood-st",
    "49-clipper-st",
    "61-w-cobia-run-102",
    "621-western-lake-dr",
    "860-western-lake-drive",
    "90-mystic-cobalt-st",
    "azalea-abbey",
    "casa-blanco",
    "close-enough",
    "emerald-bliss",
    "here-comes-the-sun",
    "hms-sunrise-sunset",
    "idle-hour",
    "main-st-getaway",
    "sea-la-vie",
    "southern-charm",
    "southern-grace",
    "sun-kissed-on-hickory",
    "sunset-on-seawalk-48-seawalk-circle",
    "sweet-liberty",
    "the-laurel-landing",
    "vermillion-sunsets",
    "vitamin-sea",
    "blissful-shores",
    "236-spartina-cir",
    "204-spartina-circle",
    "294-spartina-circle",
]

# Mapping from website property names/slugs to property_code in DB
PROPERTY_URL_MAP = {
    "100-s-spooky-lane-unit-2c": "100SL2C",
    "100-s-spooky-lane-unit-2d": "100SL2D",
    "103-compass-point-ii": "103CPW",
    "108-silver-laurel-way": "108SLW",
    "113-bartons-way-royal-blue": "113BW",
    "116-w-summersweet-lane": "116ss",
    "120-sunflower-st": "120SF",
    "1312-western-lake-dr": "1312WLD",
    "132-e-kingston-rd": "132EKR",
    "134-mystic-cobalt": "134MC",
    "1680-e-county-hwy-30a-unit-303-watercolor": "303-1680",
    "17-lyonia-lane": "17LL",
    "1735-e-county-hwy-30a-unit-303": "303-1735",
    "178-spartina-cir": "178SC",
    "1785-e-county-hwy-30a-unit-102": "102-1785",
    "1785-e-county-hwy-30a-unit-104": "104-1785",
    "18-crossvine-circle": "18CC",
    "202-28-watercolor-blvd": "203WW",
    "236-spartina-cir": "236SC",
    "204-spartina-circle": "204SC",
    "245-w-lake-forest-dr": "245Lake",
    "288-western-lake-dr": "294SC",
    "359-spartina-circle": "359SC",
    "42-flatwood-st": "42FWS",
    "sunset-on-seawalk-48-seawalk-circle": "48SWC",
    "49-clipper-st": "49CS",
    "61-w-cobia-run-102": "61CR",
    "621-western-lake-dr": "621WLD",
    "860-western-lake-drive": "860WLD",
    "90-mystic-cobalt-st": "90MC",
    "azalea-abbey": "65AS",
    "sun-kissed-on-hickory": "31Hickor",
    "hms-sunrise-sunset": "HMS",
    "117-silver-laurel-way": "117SLW",
    "119-vermillion-way": "119VW",
    
    # NEW MAPPINGS - Added 2026-02-15 from website/Excel cross-reference
    # Confirmed by name match in address:
    "sea-la-vie": "111VW",              # "Sea la Vie - 111 Village Way" in Excel
    "hms-sunrisesunset": "HMS",         # Alternate slug (no hyphen between sunrise/sunset)
    
    # Confirmed by address/attribute match:
    "vermillion-sunsets": "119VW",      # "119 Vermillion Way" in Excel
    "southern-charm": "134SC",          # Website mentions "134 Spartina Cir"
    "idle-hour": "42FWS",               # 2BR/2BA WaterColor match (42 Flatwood St)
    
    # NEW PROPERTIES - Added to database 2026-02-15 (were not in UNIT INFO.xlsx):
    "casa-blanco": "CASAB",           # 8BR/9.5BA Rosemary Beach - NEW
    "emerald-bliss": "EMERBLS",       # 4BR/3.5BA Naturewalk - NEW  
    "main-st-getaway": "MAINST",      # 2BR/2.5BA Rosemary Beach - NEW
    "vitamin-sea": "VITSEA",          # 5BR/5.5BA Inlet Beach - NEW
    
    # AMBIGUOUS - Need manual verification:
    # "close-enough" - 3BR/4BA Old Seagrove (possibly 31GARD?)
    # "southern-grace" - 4BR/4BA WaterColor (candidates: 303-1680, 303-1735, or 68RF)
    # "sweet-liberty" - 3BR/4BA WaterColor (candidates: 236SC, 621WLD, or 90MC)
}


@dataclass
class ScrapedProperty:
    """Property data scraped from website."""
    url: str
    name: str
    slug: str = ""
    
    # Basic
    bedrooms: Optional[int] = None
    bathrooms: Optional[float] = None
    sleeps: Optional[int] = None
    
    # Beds
    beds_king: int = 0
    beds_queen: int = 0
    beds_full: int = 0
    beds_twin: int = 0
    beds_bunk: int = 0
    
    # Amenities
    has_pool: bool = False
    pool_type: Optional[str] = None  # 'private', 'shared', 'community'
    pool_heated: bool = False
    has_hot_tub: bool = False
    has_grill: bool = False
    grill_type: Optional[str] = None  # 'gas', 'charcoal'
    has_bikes: bool = False
    bike_count: Optional[int] = None
    has_golf_cart: bool = False
    golf_cart_seats: Optional[int] = None
    has_outdoor_shower: bool = False
    has_beach_gear: bool = False
    
    # Kitchen
    has_coffee_maker: bool = False
    coffee_maker_type: Optional[str] = None
    has_ice_maker: bool = False
    has_wine_fridge: bool = False
    has_blender: bool = False
    has_dishwasher: bool = False
    
    # Tech
    has_wifi: bool = True
    has_smart_tv: bool = False
    has_washer_dryer: bool = False
    
    # Access
    has_watercolor_access: bool = False
    wristband_count: Optional[int] = None
    
    # Raw amenities list
    amenities: List[str] = field(default_factory=list)
    
    # Description
    description: Optional[str] = None
    
    # Confidence
    scrape_timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class PropertyEnrichmentScraper:
    """Scrapes Beach Habitats website to enrich property data."""
    
    def __init__(self, delay_seconds: float = 2.0):
        self.delay = delay_seconds
        self.client = httpx.Client(
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
            timeout=30.0,
            follow_redirects=True,
        )
    
    def get_property_urls(self) -> List[str]:
        """Get all property URLs from the known list and by scraping the site."""
        urls = []
        
        # First, use our known property slugs
        for slug in PROPERTY_SLUGS:
            url = f"{BASE_URL}/30a-vacation-rentals/{slug}"
            urls.append(url)
        
        # Also try to get more from the website dropdown
        try:
            response = self.client.get(f"{BASE_URL}/30a-vacation-rentals")
            soup = BeautifulSoup(response.text, "lxml")
            
            # Find the property dropdown/select
            for select in soup.find_all("select"):
                for option in select.find_all("option"):
                    value = option.get("value", "")
                    text = option.get_text(strip=True)
                    if text and value and value != "":
                        # Convert name to slug
                        slug = text.lower()
                        slug = re.sub(r"[^\w\s-]", "", slug)
                        slug = re.sub(r"\s+", "-", slug)
                        slug = re.sub(r"-+", "-", slug).strip("-")
                        
                        url = f"{BASE_URL}/30a-vacation-rentals/{slug}"
                        if url not in urls:
                            urls.append(url)
            
        except Exception as e:
            print(f"Warning: Could not scrape additional URLs: {e}")
        
        print(f"Found {len(urls)} property URLs to scrape")
        return urls
    
    def scrape_property(self, url: str) -> Optional[ScrapedProperty]:
        """Scrape a single property page."""
        try:
            print(f"  Fetching: {url}")
            response = self.client.get(url)
            
            if response.status_code == 404:
                print(f"    ⚠ Not found (404)")
                return None
            
            if response.status_code != 200:
                print(f"    ⚠ Status {response.status_code}")
                return None
            
            soup = BeautifulSoup(response.text, "lxml")
            
            # Check if this is a listing page vs category page
            # Listing pages have capacity info, category pages don't
            capacity_text = soup.get_text()
            if "Bedroom" not in capacity_text and "Sleeps" not in capacity_text:
                print(f"    ⚠ Category page, skipping")
                return None
            
            # Extract property name
            name_elem = soup.find("h1")
            name = name_elem.get_text(strip=True) if name_elem else "Unknown"
            
            # Skip if this looks like a category page
            if name in ["30A Beach Vacation Rentals", "Watercolor Vacation Rentals", 
                       "Seagrove Beach Vacation Rentals", "Grayton Beach Vacation Rentals",
                       "Carillon", "Rosemary Beach", "Seacrest Beach"]:
                print(f"    ⚠ Category page: {name}")
                return None
            
            slug = url.split("/")[-1]
            prop = ScrapedProperty(url=url, name=name, slug=slug)
            
            # Extract capacity info from the page text
            page_text = soup.get_text()
            
            # Bedrooms
            bed_match = re.search(r"(\d+)\s*Bedroom", page_text, re.I)
            if bed_match:
                prop.bedrooms = int(bed_match.group(1))
            
            # Bathrooms
            bath_match = re.search(r"(\d+(?:\.\d+)?)\s*Bath", page_text, re.I)
            if bath_match:
                prop.bathrooms = float(bath_match.group(1))
            
            # Sleeps
            sleeps_match = re.search(r"Sleeps\s*(\d+)", page_text, re.I)
            if sleeps_match:
                prop.sleeps = int(sleeps_match.group(1))
            
            # Extract amenities list
            amenities = set()
            
            # Look for amenities section
            features_section = soup.find(id="listing-features")
            if features_section:
                for item in features_section.find_all("li"):
                    text = item.get_text(strip=True)
                    if text and len(text) < 100:
                        amenities.add(text.lower())
            
            # Also look for other amenity containers
            for container in soup.find_all(class_=re.compile(r"field.*amenity|amenity|feature", re.I)):
                for item in container.find_all(["li", "span"]):
                    text = item.get_text(strip=True)
                    if text and len(text) < 100:
                        amenities.add(text.lower())
            
            prop.amenities = list(amenities)
            
            # Parse amenities into structured fields
            self._parse_amenities(prop)
            
            # Extract description
            about_section = soup.find(id="listing-about")
            if about_section:
                prop.description = about_section.get_text(separator=" ", strip=True)[:5000]
            
            # Parse description for additional info
            if prop.description:
                self._parse_description(prop)
            
            return prop
            
        except Exception as e:
            print(f"    ✗ Error: {e}")
            return None
    
    def _parse_amenities(self, prop: ScrapedProperty):
        """Parse amenity list into structured fields."""
        amenities_text = " ".join(prop.amenities)
        
        # Pool
        if "pool" in amenities_text:
            prop.has_pool = True
            if "private pool" in amenities_text:
                prop.pool_type = "private"
            elif "communal pool" in amenities_text or "shared pool" in amenities_text:
                prop.pool_type = "shared"
            else:
                prop.pool_type = "community"
            if "heated" in amenities_text:
                prop.pool_heated = True
        
        # Hot tub
        if "hot tub" in amenities_text or "spa" in amenities_text:
            prop.has_hot_tub = True
        
        # Grill
        if "grill" in amenities_text or "bbq" in amenities_text:
            prop.has_grill = True
            if "gas grill" in amenities_text:
                prop.grill_type = "gas"
            elif "charcoal" in amenities_text:
                prop.grill_type = "charcoal"
            else:
                prop.grill_type = "gas"
        
        # Bikes
        if "bicycle" in amenities_text or "bike" in amenities_text:
            prop.has_bikes = True
        
        # Outdoor shower
        if "outdoor shower" in amenities_text:
            prop.has_outdoor_shower = True
        
        # Kitchen
        if "coffee" in amenities_text:
            prop.has_coffee_maker = True
        if "ice maker" in amenities_text:
            prop.has_ice_maker = True
        if "wine" in amenities_text:
            prop.has_wine_fridge = True
        if "blender" in amenities_text:
            prop.has_blender = True
        if "dishwasher" in amenities_text:
            prop.has_dishwasher = True
        
        # Laundry
        if "washer" in amenities_text or "dryer" in amenities_text or "laundry" in amenities_text:
            prop.has_washer_dryer = True
        
        # Beach gear
        if "beach" in amenities_text:
            prop.has_beach_gear = True
    
    def _parse_description(self, prop: ScrapedProperty):
        """Extract additional info from description text."""
        desc = prop.description.lower() if prop.description else ""
        
        # Bikes with count
        bike_match = re.search(r"(\d+)\s*(?:adult\s*)?(?:bikes?|bicycles?)", desc)
        if bike_match:
            prop.has_bikes = True
            prop.bike_count = int(bike_match.group(1))
        elif "bike" in desc or "bicycle" in desc:
            prop.has_bikes = True
        
        # Golf cart
        cart_match = re.search(r"(\d+)\s*seat(?:er)?\s*(?:golf\s*cart|lsv)", desc)
        if cart_match:
            prop.has_golf_cart = True
            prop.golf_cart_seats = int(cart_match.group(1))
        elif "golf cart" in desc or "lsv" in desc:
            prop.has_golf_cart = True
            # Try to find seat count elsewhere
            seat_match = re.search(r"(\d+)\s*seat", desc)
            if seat_match:
                prop.golf_cart_seats = int(seat_match.group(1))
        
        # Watercolor access/wristbands
        wristband_match = re.search(r"(\d+)\s*(?:watercolor\s*)?(?:amenity\s*)?wristbands?", desc)
        if wristband_match:
            prop.has_watercolor_access = True
            prop.wristband_count = int(wristband_match.group(1))
        elif "watercolor" in desc and ("access" in desc or "beach club" in desc):
            prop.has_watercolor_access = True
        
        # Bed counts
        king_matches = re.findall(r"king\s*bed", desc)
        prop.beds_king = len(king_matches) if king_matches else 0
        
        # Also try "X king beds" pattern
        king_count = re.search(r"(\d+)\s*king", desc)
        if king_count:
            prop.beds_king = max(prop.beds_king, int(king_count.group(1)))
        
        queen_matches = re.findall(r"queen\s*bed", desc)
        prop.beds_queen = len(queen_matches) if queen_matches else 0
        
        # Ice maker
        if "ice maker" in desc or "icemaker" in desc:
            prop.has_ice_maker = True
        
        # Wine fridge
        if "wine" in desc and ("fridge" in desc or "refrigerator" in desc or "cooler" in desc):
            prop.has_wine_fridge = True
    
    def scrape_all(self) -> List[ScrapedProperty]:
        """Scrape all properties."""
        urls = self.get_property_urls()
        properties = []
        
        for i, url in enumerate(urls):
            print(f"[{i+1}/{len(urls)}]", end="")
            prop = self.scrape_property(url)
            if prop:
                properties.append(prop)
                print(f"    ✓ {prop.name}: {prop.bedrooms}BR/{prop.bathrooms}BA, {len(prop.amenities)} amenities")
            
            time.sleep(self.delay)
        
        return properties
    
    def close(self):
        """Close the HTTP client."""
        self.client.close()


def match_property_code(scraped: ScrapedProperty, db_properties: Dict[str, dict]) -> Optional[str]:
    """Match scraped property to database property_code."""
    # Try URL-based mapping first
    slug = scraped.slug.lower()
    if slug in PROPERTY_URL_MAP:
        return PROPERTY_URL_MAP[slug]
    
    # Try matching by address similarity
    name_lower = scraped.name.lower()
    for code, db_prop in db_properties.items():
        address = (db_prop.get("address_street") or "").lower()
        
        if not address:
            continue
        
        # Extract key numbers and words
        name_nums = set(re.findall(r"\d+", name_lower))
        addr_nums = set(re.findall(r"\d+", address))
        
        # Check for number matches
        if name_nums and addr_nums:
            overlap = name_nums & addr_nums
            if overlap:
                # Check if main number matches
                name_main = re.search(r"^(\d+)", name_lower)
                addr_main = re.search(r"^(\d+)", address)
                if name_main and addr_main and name_main.group(1) == addr_main.group(1):
                    return code
    
    return None


def update_database(properties: List[ScrapedProperty], dry_run: bool = False):
    """Update database with scraped property data."""
    print("\n" + "=" * 60)
    print("UPDATING DATABASE")
    print("=" * 60)
    
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    
    try:
        # Get existing properties
        cur.execute("""
            SELECT property_code, address_street, bedrooms, bathrooms 
            FROM properties
        """)
        db_properties = {
            row[0]: {
                "address_street": row[1],
                "bedrooms": row[2],
                "bathrooms": row[3],
            }
            for row in cur.fetchall()
        }
        print(f"Found {len(db_properties)} properties in database")
        
        updated = 0
        not_matched = []
        
        for prop in properties:
            code = match_property_code(prop, db_properties)
            
            if not code:
                not_matched.append((prop.name, prop.slug))
                continue
            
            # Build beds_config
            beds_config = {}
            if prop.beds_king:
                beds_config["king"] = prop.beds_king
            if prop.beds_queen:
                beds_config["queen"] = prop.beds_queen
            if prop.beds_full:
                beds_config["full"] = prop.beds_full
            if prop.beds_twin:
                beds_config["twin"] = prop.beds_twin
            if prop.beds_bunk:
                beds_config["bunk"] = prop.beds_bunk
            
            # Build amenities JSON
            amenities = {
                "kitchen": {
                    "coffee_maker": prop.has_coffee_maker,
                    "ice_maker": prop.has_ice_maker,
                    "wine_fridge": prop.has_wine_fridge,
                    "blender": prop.has_blender,
                    "dishwasher": prop.has_dishwasher,
                },
                "outdoor": {
                    "grill": prop.has_grill,
                    "grill_type": prop.grill_type,
                    "outdoor_shower": prop.has_outdoor_shower,
                    "pool": prop.has_pool,
                    "pool_type": prop.pool_type,
                    "pool_heated": prop.pool_heated,
                    "hot_tub": prop.has_hot_tub,
                },
                "recreation": {
                    "bikes": prop.has_bikes,
                    "bike_count": prop.bike_count,
                    "golf_cart": prop.has_golf_cart,
                    "golf_cart_seats": prop.golf_cart_seats,
                    "beach_gear": prop.has_beach_gear,
                },
                "community": {
                    "watercolor_access": prop.has_watercolor_access,
                    "wristband_count": prop.wristband_count,
                },
                "raw_list": prop.amenities[:50],  # Limit raw list
            }
            
            if dry_run:
                print(f"  [DRY RUN] Would update {code}: sleeps={prop.sleeps}, pool={prop.has_pool}, bikes={prop.bike_count}")
            else:
                cur.execute("""
                    UPDATE properties SET
                        sleeps = COALESCE(%s, sleeps),
                        has_pool = %s,
                        pool_heated = %s,
                        has_hot_tub = %s,
                        has_grill = %s,
                        has_bikes = %s,
                        bike_count = %s,
                        has_beach_gear = %s,
                        has_washer_dryer = %s,
                        beds_config = COALESCE(%s, beds_config),
                        amenities = %s,
                        confidence_score = 0.90,
                        data_source = 'inspection',
                        updated_at = NOW()
                    WHERE property_code = %s
                """, (
                    prop.sleeps,
                    prop.has_pool,
                    prop.pool_heated,
                    prop.has_hot_tub,
                    prop.has_grill,
                    prop.has_bikes,
                    prop.bike_count,
                    prop.has_beach_gear,
                    prop.has_washer_dryer,
                    Json(beds_config) if beds_config else None,
                    Json(amenities),
                    code,
                ))
                if cur.rowcount > 0:
                    print(f"  ✓ Updated {code}")
                    updated += 1
                else:
                    print(f"  ⚠ No rows updated for {code}")
        
        if not dry_run:
            conn.commit()
        
        print()
        print(f"✅ Updated: {updated}")
        print(f"⚠ Not matched: {len(not_matched)}")
        if not_matched:
            print("\n  Properties not matched (add to PROPERTY_URL_MAP):")
            for name, slug in not_matched[:15]:
                print(f'    "{slug}": "???",  # {name}')
            if len(not_matched) > 15:
                print(f"    ... and {len(not_matched) - 15} more")
        
    except Exception as e:
        conn.rollback()
        print(f"❌ Database error: {e}")
        raise
    finally:
        cur.close()
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Scrape Beach Habitats website to enrich property data")
    parser.add_argument("--property", "-p", help="Scrape specific property slug")
    parser.add_argument("--dry-run", "-n", action="store_true", help="Don't update database")
    parser.add_argument("--delay", "-d", type=float, default=1.5, help="Delay between requests (seconds)")
    parser.add_argument("--output", "-o", help="Save scraped data to JSON file")
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("BEACH HABITATS PROPERTY ENRICHMENT SCRAPER")
    print("=" * 60)
    print()
    
    scraper = PropertyEnrichmentScraper(delay_seconds=args.delay)
    
    try:
        if args.property:
            # Scrape single property
            url = f"{BASE_URL}/30a-vacation-rentals/{args.property}"
            prop = scraper.scrape_property(url)
            if prop:
                print(f"\n✅ Scraped: {prop.name}")
                print(f"  Bedrooms: {prop.bedrooms}")
                print(f"  Bathrooms: {prop.bathrooms}")
                print(f"  Sleeps: {prop.sleeps}")
                print(f"  Amenities: {len(prop.amenities)}")
                print(f"  Pool: {prop.has_pool} ({prop.pool_type})")
                print(f"  Hot Tub: {prop.has_hot_tub}")
                print(f"  Grill: {prop.has_grill} ({prop.grill_type})")
                print(f"  Bikes: {prop.has_bikes} ({prop.bike_count})")
                print(f"  Golf Cart: {prop.has_golf_cart} ({prop.golf_cart_seats} seats)")
                print(f"  Watercolor Access: {prop.has_watercolor_access} ({prop.wristband_count} wristbands)")
                
                if not args.dry_run:
                    update_database([prop], dry_run=False)
        else:
            # Scrape all properties
            properties = scraper.scrape_all()
            
            print(f"\n✅ Scraped {len(properties)} properties total")
            
            if args.output:
                with open(args.output, "w") as f:
                    json.dump([asdict(p) for p in properties], f, indent=2)
                print(f"💾 Saved to {args.output}")
            
            update_database(properties, dry_run=args.dry_run)
    
    finally:
        scraper.close()


if __name__ == "__main__":
    main()
