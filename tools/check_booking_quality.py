#!/usr/bin/env python3
"""Check for suspicious booking data."""

import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = "postgresql://rental:rental@localhost:5433/rental_revenue"

conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
cur = conn.cursor()

print("=" * 70)
print("BOOKING DATA QUALITY CHECK")
print("=" * 70)

# Check for unusually long bookings (likely owner blocks)
print("\n📅 Bookings > 30 nights (potential owner blocks):")
cur.execute("""
    SELECT 
        property_code,
        check_in,
        check_out,
        nights,
        source
    FROM property_bookings
    WHERE nights > 30
    ORDER BY nights DESC
    LIMIT 20
""")
for row in cur.fetchall():
    print(f"   {row['property_code']}: {row['check_in']} → {row['check_out']} ({row['nights']} nights)")

# Check for 0-night bookings
print("\n⚠️  Zero-night bookings (data issues):")
cur.execute("""
    SELECT 
        property_code,
        check_in,
        check_out,
        nights
    FROM property_bookings
    WHERE nights = 0 OR nights IS NULL
    ORDER BY check_in
""")
rows = cur.fetchall()
for row in rows:
    print(f"   {row['property_code']}: {row['check_in']} → {row['check_out']}")
print(f"   Total: {len(rows)} zero-night bookings")

# Booking distribution
print("\n📊 Booking length distribution:")
cur.execute("""
    SELECT 
        CASE 
            WHEN nights <= 3 THEN '1-3 nights'
            WHEN nights <= 7 THEN '4-7 nights'
            WHEN nights <= 14 THEN '8-14 nights'
            WHEN nights <= 30 THEN '15-30 nights'
            WHEN nights <= 90 THEN '31-90 nights'
            ELSE '90+ nights'
        END as duration_bucket,
        COUNT(*) as count
    FROM property_bookings
    WHERE nights > 0
    GROUP BY 1
    ORDER BY 
        CASE 
            WHEN nights <= 3 THEN 1
            WHEN nights <= 7 THEN 2
            WHEN nights <= 14 THEN 3
            WHEN nights <= 30 THEN 4
            WHEN nights <= 90 THEN 5
            ELSE 6
        END
""")
for row in cur.fetchall():
    print(f"   {row['duration_bucket']}: {row['count']} bookings")

cur.close()
conn.close()
