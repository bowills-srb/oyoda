#!/usr/bin/env python3
"""Quick database verification for booking data."""

import psycopg2
from datetime import date

DATABASE_URL = "postgresql://rental:rental@localhost:5433/rental_revenue"

conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()

print("=" * 70)
print("DATABASE VERIFICATION - BOOKING DATA")
print("=" * 70)

# Check availability table
cur.execute("""
    SELECT 
        COUNT(*) as total,
        COUNT(DISTINCT property_code) as properties,
        MIN(date) as min_date,
        MAX(date) as max_date,
        SUM(CASE WHEN available THEN 1 ELSE 0 END) as available_days,
        SUM(CASE WHEN NOT available THEN 1 ELSE 0 END) as booked_days
    FROM property_availability
""")
row = cur.fetchone()
print(f"\n📊 property_availability:")
print(f"   Total records: {row[0]:,}")
print(f"   Properties: {row[1]}")
print(f"   Date range: {row[2]} to {row[3]}")
print(f"   Available days: {row[4]:,}")
print(f"   Booked days: {row[5]:,}")

# Check bookings table
cur.execute("""
    SELECT 
        COUNT(*) as total,
        COUNT(DISTINCT property_code) as properties,
        MIN(check_in) as first_checkin,
        MAX(check_out) as last_checkout,
        SUM(nights) as total_nights
    FROM property_bookings
""")
row = cur.fetchone()
print(f"\n📅 property_bookings:")
print(f"   Total bookings: {row[0]}")
print(f"   Properties with bookings: {row[1]}")
print(f"   Date range: {row[2]} to {row[3]}")
print(f"   Total booked nights: {row[4]}")

# Upcoming bookings
print(f"\n📆 Upcoming Bookings (next 30 days):")
cur.execute("""
    SELECT 
        property_code,
        check_in,
        check_out,
        nights
    FROM property_bookings
    WHERE check_in >= CURRENT_DATE 
    AND check_in <= CURRENT_DATE + INTERVAL '30 days'
    ORDER BY check_in
    LIMIT 15
""")
for row in cur.fetchall():
    print(f"   {row[0]}: {row[1]} → {row[2]} ({row[3]} nights)")

# Occupancy by property
print(f"\n📈 Occupancy Summary (next 90 days):")
cur.execute("""
    SELECT 
        property_code,
        COUNT(*) as total_days,
        SUM(CASE WHEN NOT available THEN 1 ELSE 0 END) as booked_days,
        ROUND(100.0 * SUM(CASE WHEN NOT available THEN 1 ELSE 0 END) / COUNT(*), 1) as occupancy_pct
    FROM property_availability
    WHERE date >= CURRENT_DATE 
    AND date < CURRENT_DATE + INTERVAL '90 days'
    GROUP BY property_code
    ORDER BY occupancy_pct DESC
    LIMIT 10
""")
print(f"   {'Property':<12} {'Days':<6} {'Booked':<8} {'Occupancy'}")
print(f"   {'-'*12} {'-'*6} {'-'*8} {'-'*10}")
for row in cur.fetchall():
    print(f"   {row[0]:<12} {row[1]:<6} {row[2]:<8} {row[3]}%")

cur.close()
conn.close()

print("\n" + "=" * 70)
print("✓ Verification complete")
print("=" * 70)
