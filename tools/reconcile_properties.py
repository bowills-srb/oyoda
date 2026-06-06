#!/usr/bin/env python3
"""
Reconcile database property codes with website URLs.
Some properties have different codes in DB vs what we scraped.
"""

import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = "postgresql://rental:rental@localhost:5433/rental_revenue"

# These are the mappings we discovered - DB code → Website slug
# Based on matching addresses
PROPERTY_RECONCILIATION = {
    # DB Code: (Website Slug, Correct Code to use)
    "100SL2C": ("100-s-spooky-lane-unit-2c", "100SSL2C"),  # Duplicate of 100SSL2C
    "100SL2D": ("100-s-spooky-lane-unit-2d", "100SSL2D"),  # Duplicate of 100SSL2D
    "103CPW": ("103-compass-point-ii", "103CP2"),  # Duplicate of 103CP2
    "116ss": ("116-w-summersweet-lane", "116WSL"),  # Duplicate of 116WSL
    "28WC": ("202-28-watercolor-blvd", "202-28WB"),  # Duplicate of 202-28WB
    "245Lake": ("245-w-lake-forest-dr", "245WLF"),  # Duplicate of 245WLF
    "61CR": ("61-w-cobia-run-102", "61WCR"),  # Duplicate of 61WCR
}

# Properties that exist in DB but may not be on website yet
POSSIBLY_NOT_ON_WEBSITE = [
    "102-1785",   # 1785 E County Hwy 30A Unit 102 (different unit)
    "1151SG",     # 1151 Sandgrass Blvd
    "117SLW",     # 117 Silver Laurel Way
    "203WW",      # 203 Wisteria Way
    "204SC",      # 204 Spartina Cir
    "236SC",      # 236 Spartina Cir
    "294SC",      # 294 Spartina Cir
    "310FST",     # 310 Forest Street
    "31GARD",     # 31 Gardenia (3 by the sea)
    "31Hickor",   # 31 HICKORY
    "65AS",       # 65 Azelea St
    "68RF",       # 68 E Royal Fern
    "75ECRAB",    # 75 E Crabbing Hole Lane
]

def main():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    cur = conn.cursor()
    
    print("=" * 70)
    print("PROPERTY CODE RECONCILIATION")
    print("=" * 70)
    
    # 1. Check for duplicate entries that should be merged
    print("\n🔄 DUPLICATE CODES (same property, different codes):")
    print("-" * 70)
    
    for old_code, (slug, new_code) in PROPERTY_RECONCILIATION.items():
        cur.execute("SELECT address_street FROM properties WHERE property_code = %s", (old_code,))
        old_row = cur.fetchone()
        
        cur.execute("SELECT address_street FROM properties WHERE property_code = %s", (new_code,))
        new_row = cur.fetchone()
        
        old_addr = old_row['address_street'] if old_row else "(not in DB)"
        new_addr = new_row['address_street'] if new_row else "(not in DB)"
        
        print(f"\n  {old_code} → {new_code}")
        print(f"    Old: {old_addr[:50]}")
        print(f"    New: {new_addr[:50]}")
        
        if old_row and new_row:
            print(f"    ⚠️  BOTH exist - consider merging")
        elif old_row and not new_row:
            print(f"    📝 Should rename {old_code} → {new_code}")
        elif new_row and not old_row:
            print(f"    ✓ Already using correct code {new_code}")
    
    # 2. Properties not on website
    print("\n\n❓ PROPERTIES POSSIBLY NOT ON WEBSITE:")
    print("-" * 70)
    
    for code in POSSIBLY_NOT_ON_WEBSITE:
        cur.execute("SELECT address_street FROM properties WHERE property_code = %s", (code,))
        row = cur.fetchone()
        if row:
            print(f"  {code}: {row['address_street'][:50]}")
    
    # 3. Generate SQL to fix duplicates
    print("\n\n📝 SQL TO FIX DUPLICATES:")
    print("-" * 70)
    print("""
-- Option 1: Delete the duplicate entries with old codes
-- (if the new codes already have all the data)

DELETE FROM properties WHERE property_code IN (
    '100SL2C', '100SL2D', '103CPW', '116ss', '28WC', '245Lake', '61CR'
);

-- Option 2: Rename old codes to new codes
-- (if old entries have data that new ones don't)

-- First check which have data:
-- SELECT property_code, address_street FROM properties 
-- WHERE property_code IN ('100SL2C', '100SL2D', '103CPW', '116ss', '28WC', '245Lake', '61CR');
""")
    
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
