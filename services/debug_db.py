#!/usr/bin/env python3
"""
Guest Concierge Data Service - Debug Version

Run this to test database connectivity and see what data is available.
"""

import os
import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://rental:rental@localhost:5433/rental_revenue"
)

def main():
    print("=" * 70)
    print("DATABASE DEBUG")
    print("=" * 70)
    
    try:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
        cur = conn.cursor()
        print("✓ Connected to database")
        
        # Check what tables exist
        print("\n1. Available tables:")
        cur.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
            ORDER BY table_name
        """)
        for row in cur.fetchall():
            print(f"   - {row['table_name']}")
        
        # Check properties table schema
        print("\n2. Properties table columns:")
        cur.execute("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'properties'
            ORDER BY ordinal_position
        """)
        columns = cur.fetchall()
        if columns:
            for row in columns:
                print(f"   - {row['column_name']} ({row['data_type']})")
        else:
            print("   ⚠ Table 'properties' not found!")
        
        # Check property_bookings table
        print("\n3. Property_bookings table columns:")
        cur.execute("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'property_bookings'
            ORDER BY ordinal_position
        """)
        columns = cur.fetchall()
        if columns:
            for row in columns:
                print(f"   - {row['column_name']} ({row['data_type']})")
        else:
            print("   ⚠ Table 'property_bookings' not found!")
        
        # Check property_availability table
        print("\n4. Property_availability table columns:")
        cur.execute("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'property_availability'
            ORDER BY ordinal_position
        """)
        columns = cur.fetchall()
        if columns:
            for row in columns:
                print(f"   - {row['column_name']} ({row['data_type']})")
        
        # Sample data from properties
        print("\n5. Sample properties data:")
        cur.execute("SELECT * FROM properties LIMIT 3")
        rows = cur.fetchall()
        if rows:
            for row in rows:
                print(f"\n   Property: {row.get('property_code', 'N/A')}")
                for key, value in row.items():
                    if value is not None:
                        print(f"      {key}: {str(value)[:50]}")
        else:
            print("   No properties in table")
        
        # Sample bookings
        print("\n6. Sample bookings (current/upcoming):")
        cur.execute("""
            SELECT property_code, check_in, check_out, nights 
            FROM property_bookings 
            WHERE check_in >= CURRENT_DATE - INTERVAL '7 days'
            ORDER BY check_in 
            LIMIT 5
        """)
        for row in cur.fetchall():
            print(f"   {row['property_code']}: {row['check_in']} → {row['check_out']} ({row['nights']} nights)")
        
        cur.close()
        conn.close()
        print("\n✓ Debug complete")
        
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
