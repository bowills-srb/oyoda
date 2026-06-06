#!/usr/bin/env python3
"""
Fix property codes to match website URLs.
Renames old codes to standardized codes used by scrapers.
"""

import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = "postgresql://rental:rental@localhost:5433/rental_revenue"

# Old code → New code (to match website slugs)
CODE_RENAMES = {
    "100SL2C": "100SSL2C",
    "100SL2D": "100SSL2D", 
    "103CPW": "103CP2",
    "116ss": "116WSL",
    "28WC": "202-28WB",
    "245Lake": "245WLF",
    "61CR": "61WCR",
}

def main():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    cur = conn.cursor()
    
    print("=" * 70)
    print("RENAMING PROPERTY CODES")
    print("=" * 70)
    
    for old_code, new_code in CODE_RENAMES.items():
        print(f"\n  {old_code} → {new_code}")
        
        # Check if old code exists
        cur.execute("SELECT id FROM properties WHERE property_code = %s", (old_code,))
        if not cur.fetchone():
            print(f"    ⚠️  Old code {old_code} not found, skipping")
            continue
        
        # Check if new code already exists
        cur.execute("SELECT id FROM properties WHERE property_code = %s", (new_code,))
        if cur.fetchone():
            print(f"    ⚠️  New code {new_code} already exists, skipping")
            continue
        
        # Rename in properties table
        cur.execute(
            "UPDATE properties SET property_code = %s WHERE property_code = %s",
            (new_code, old_code)
        )
        print(f"    ✓ Updated properties table")
        
        # Also update related tables if they exist
        for table in ['property_availability', 'property_bookings', 'property_pricing']:
            try:
                cur.execute(
                    f"UPDATE {table} SET property_code = %s WHERE property_code = %s",
                    (new_code, old_code)
                )
                count = cur.rowcount
                if count > 0:
                    print(f"    ✓ Updated {count} rows in {table}")
            except Exception as e:
                pass  # Table might not exist
    
    conn.commit()
    print("\n" + "=" * 70)
    print("✓ COMPLETE - Property codes renamed")
    print("=" * 70)
    
    # Show current state
    print("\nCurrent property count:")
    cur.execute("SELECT COUNT(*) FROM properties")
    print(f"  Properties: {cur.fetchone()['count']}")
    
    cur.execute("SELECT COUNT(DISTINCT property_code) FROM property_pricing")
    print(f"  With pricing: {cur.fetchone()['count']}")
    
    cur.execute("SELECT COUNT(DISTINCT property_code) FROM property_bookings")
    print(f"  With bookings: {cur.fetchone()['count']}")
    
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
