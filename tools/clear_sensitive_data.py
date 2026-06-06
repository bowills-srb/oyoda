#!/usr/bin/env python3
"""
Clear internal notes and staff contact info from properties table.
These shouldn't be exposed to guests via the concierge.
"""

import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = "postgresql://rental:rental@localhost:5433/rental_revenue"

def main():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    cur = conn.cursor()
    
    print("=" * 70)
    print("CLEARING INTERNAL/SENSITIVE DATA FROM PROPERTIES")
    print("=" * 70)
    
    # First, show what we're about to clear
    print("\n📋 Current data that will be cleared:")
    cur.execute("""
        SELECT 
            property_code,
            rep_name,
            housekeeper_name,
            housekeeper_phone,
            emergency_contact,
            general_notes,
            internal_notes
        FROM properties
        WHERE rep_name IS NOT NULL 
           OR housekeeper_name IS NOT NULL
           OR general_notes IS NOT NULL
           OR internal_notes IS NOT NULL
        LIMIT 10
    """)
    
    for row in cur.fetchall():
        print(f"\n  {row['property_code']}:")
        if row['rep_name']:
            print(f"    rep_name: {row['rep_name']}")
        if row['housekeeper_name']:
            print(f"    housekeeper: {row['housekeeper_name']} ({row['housekeeper_phone']})")
        if row['general_notes']:
            print(f"    notes: {row['general_notes'][:60]}...")
        if row['internal_notes']:
            print(f"    internal: {row['internal_notes'][:60]}...")
    
    # Ask for confirmation
    print("\n" + "=" * 70)
    response = input("Clear this data from ALL properties? (yes/no): ")
    
    if response.lower() != 'yes':
        print("Cancelled.")
        return
    
    # Clear the sensitive fields
    cur.execute("""
        UPDATE properties
        SET 
            rep_name = NULL,
            housekeeper_name = NULL,
            housekeeper_phone = NULL,
            emergency_contact = NULL,
            general_notes = NULL,
            internal_notes = NULL,
            updated_at = NOW()
    """)
    
    rows_updated = cur.rowcount
    conn.commit()
    
    print(f"\n✓ Cleared sensitive data from {rows_updated} properties")
    
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
