#!/usr/bin/env python3
"""Check for suspicious booking data."""

import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = "postgresql://rental:rental@localhost:5433/rental_revenue"

conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
cur = conn.cursor()

print("=" * 70)
print("SUSPICIOUS BOOKING CHECK")
print("=" * 70)

# Check 108SLW specifically
print("\n📋 108SLW Bookings:")
cur.execute("""
    SELECT check_in, check_out, nights 
    FROM property_bookings 
    WHERE property_code = '108SLW'
    ORDER BY nights DESC
""")
for row in cur.fetchall():
    flag = "⚠️ SUSPICIOUS" if row['nights'] > 30 else ""
    print(f"   {row['check_in']} → {row['check_out']}: {row['nights']} nights {flag}")

# All bookings > 30 nights
print("\n\n⚠️ ALL BOOKINGS > 30 NIGHTS (likely owner blocks):")
cur.execute("""
    SELECT property_code, check_in, check_out, nights
    FROM property_bookings
    WHERE nights > 30
    ORDER BY nights DESC
""")
long_stays = cur.fetchall()
total_suspicious_nights = 0
for row in long_stays:
    print(f"   {row['property_code']}: {row['check_in']} → {row['check_out']} ({row['nights']} nights)")
    total_suspicious_nights += row['nights']

print(f"\n   Total suspicious nights: {total_suspicious_nights:,}")

# Booking distribution
print("\n\n📊 BOOKING LENGTH DISTRIBUTION:")
cur.execute("""
    SELECT 
        CASE 
            WHEN nights = 0 THEN '0 nights (error)'
            WHEN nights <= 3 THEN '1-3 nights'
            WHEN nights <= 7 THEN '4-7 nights'
            WHEN nights <= 14 THEN '8-14 nights'
            WHEN nights <= 30 THEN '15-30 nights'
            WHEN nights <= 90 THEN '31-90 nights'
            ELSE '90+ nights (owner blocks?)'
        END as bucket,
        COUNT(*) as count,
        SUM(nights) as total_nights
    FROM property_bookings
    GROUP BY 1
    ORDER BY MIN(nights)
""")
for row in cur.fetchall():
    print(f"   {row['bucket']}: {row['count']} bookings, {row['total_nights']} nights")

# Recalculate revenue excluding long stays
print("\n\n💵 REVENUE (excluding stays > 30 nights):")
cur.execute("""
    SELECT 
        b.property_code,
        SUM(b.nights) as booked_nights,
        ROUND(AVG(p.adr)) as avg_adr,
        ROUND(SUM(b.nights) * AVG(p.adr)) as est_revenue
    FROM property_bookings b
    JOIN property_pricing p ON b.property_code = p.property_code
    WHERE b.nights > 0 AND b.nights <= 30 AND p.adr > 0
    GROUP BY b.property_code
    ORDER BY SUM(b.nights) * AVG(p.adr) DESC
    LIMIT 10
""")
for row in cur.fetchall():
    print(f"   {row['property_code']}: ${row['est_revenue']:,.0f} ({row['booked_nights']} nights × ${row['avg_adr']}/night)")

cur.close()
conn.close()
