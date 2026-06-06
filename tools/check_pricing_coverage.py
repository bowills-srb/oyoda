#!/usr/bin/env python3
"""Check which properties are missing pricing data."""

import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = "postgresql://rental:rental@localhost:5433/rental_revenue"

conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
cur = conn.cursor()

print("=" * 70)
print("PROPERTY PRICING COVERAGE CHECK")
print("=" * 70)

# Get all properties from database
cur.execute("SELECT property_code FROM properties ORDER BY property_code")
all_properties = [row['property_code'] for row in cur.fetchall()]

# Get properties with pricing
cur.execute("SELECT DISTINCT property_code FROM property_pricing")
priced_properties = [row['property_code'] for row in cur.fetchall()]

# Get properties with bookings (from scraper)
cur.execute("SELECT DISTINCT property_code FROM property_bookings")
booked_properties = [row['property_code'] for row in cur.fetchall()]

print(f"\n📊 Database Properties: {len(all_properties)}")
print(f"📊 Properties with Pricing: {len(priced_properties)}")
print(f"📊 Properties with Bookings: {len(booked_properties)}")

# Find gaps
missing_pricing = set(all_properties) - set(priced_properties)
missing_bookings = set(all_properties) - set(booked_properties)

print(f"\n❌ Properties WITHOUT pricing ({len(missing_pricing)}):")
for code in sorted(missing_pricing):
    cur.execute("SELECT address_street FROM properties WHERE property_code = %s", (code,))
    row = cur.fetchone()
    name = row['address_street'] if row else 'Unknown'
    in_bookings = "✓ has bookings" if code in booked_properties else "✗ no bookings"
    print(f"   {code}: {name[:40]} ({in_bookings})")

print(f"\n❌ Properties WITHOUT bookings ({len(missing_bookings)}):")
for code in sorted(missing_bookings):
    cur.execute("SELECT address_street FROM properties WHERE property_code = %s", (code,))
    row = cur.fetchone()
    name = row['address_street'] if row else 'Unknown'
    in_pricing = "✓ has pricing" if code in priced_properties else "✗ no pricing"
    print(f"   {code}: {name[:40]} ({in_pricing})")

# Check what's in the pricing scraper map vs database
print("\n" + "=" * 70)
print("SCRAPER URL MAP CHECK")
print("=" * 70)

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

scraper_codes = set(PROPERTY_URL_MAP.values())
db_codes = set(all_properties)

in_db_not_scraper = db_codes - scraper_codes
in_scraper_not_db = scraper_codes - db_codes

print(f"\nIn database but NOT in scraper URL map ({len(in_db_not_scraper)}):")
for code in sorted(in_db_not_scraper):
    cur.execute("SELECT address_street FROM properties WHERE property_code = %s", (code,))
    row = cur.fetchone()
    name = row['address_street'] if row else 'Unknown'
    print(f"   {code}: {name[:50]}")

if in_scraper_not_db:
    print(f"\nIn scraper but NOT in database ({len(in_scraper_not_db)}):")
    for code in sorted(in_scraper_not_db):
        print(f"   {code}")

cur.close()
conn.close()
