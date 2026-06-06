#!/usr/bin/env python3
"""Final summary of Beach Habitats data coverage."""

import psycopg2
from psycopg2.extras import RealDictCursor
from decimal import Decimal

DATABASE_URL = "postgresql://rental:rental@localhost:5433/rental_revenue"

conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
cur = conn.cursor()

print("=" * 70)
print("BEACH HABITATS DATA COVERAGE SUMMARY")
print("=" * 70)

# Overall counts
cur.execute("SELECT COUNT(*) as cnt FROM properties")
total_properties = cur.fetchone()['cnt']

cur.execute("SELECT COUNT(DISTINCT property_code) as cnt FROM property_bookings")
properties_with_bookings = cur.fetchone()['cnt']

cur.execute("SELECT COUNT(DISTINCT property_code) as cnt FROM property_pricing")
properties_with_pricing = cur.fetchone()['cnt']

cur.execute("SELECT COUNT(*) as cnt FROM property_availability")
avail_records = cur.fetchone()['cnt']

cur.execute("SELECT COUNT(*) as cnt FROM property_bookings")
booking_records = cur.fetchone()['cnt']

cur.execute("SELECT COUNT(*) as cnt FROM property_pricing")
pricing_records = cur.fetchone()['cnt']

print(f"\n📊 DATABASE TOTALS")
print(f"   Properties in DB:        {total_properties}")
print(f"   Properties with bookings: {properties_with_bookings}")
print(f"   Properties with pricing:  {properties_with_pricing}")
print(f"   Availability records:     {avail_records:,}")
print(f"   Booking records:          {booking_records}")
print(f"   Pricing quotes:           {pricing_records}")

# Properties with full data (both bookings and pricing)
cur.execute("""
    SELECT DISTINCT p.property_code
    FROM properties p
    WHERE EXISTS (SELECT 1 FROM property_bookings b WHERE b.property_code = p.property_code)
    AND EXISTS (SELECT 1 FROM property_pricing pr WHERE pr.property_code = p.property_code)
""")
full_data = [r['property_code'] for r in cur.fetchall()]

print(f"\n✅ PROPERTIES WITH FULL DATA ({len(full_data)}):")
print(f"   {', '.join(sorted(full_data)[:10])}...")

# ADR Summary
cur.execute("""
    SELECT 
        property_code,
        ROUND(AVG(adr)) as avg_adr,
        COUNT(*) as quotes
    FROM property_pricing
    WHERE adr > 0
    GROUP BY property_code
    ORDER BY AVG(adr) DESC
""")
pricing_summary = cur.fetchall()

print(f"\n💰 ADR BY PROPERTY (Top 10):")
for row in pricing_summary[:10]:
    print(f"   {row['property_code']}: ${row['avg_adr']:,.0f}/night ({row['quotes']} quotes)")

# Calculate portfolio metrics
cur.execute("""
    SELECT 
        ROUND(AVG(adr)) as portfolio_avg_adr,
        ROUND(MIN(adr)) as min_adr,
        ROUND(MAX(adr)) as max_adr
    FROM property_pricing
    WHERE adr > 0
""")
portfolio = cur.fetchone()

print(f"\n📈 PORTFOLIO METRICS:")
print(f"   Average ADR: ${portfolio['portfolio_avg_adr']:,.0f}/night")
print(f"   ADR Range:   ${portfolio['min_adr']:,.0f} - ${portfolio['max_adr']:,.0f}")

# Booking summary
cur.execute("""
    SELECT 
        SUM(nights) as total_nights,
        COUNT(*) as total_bookings,
        ROUND(AVG(nights), 1) as avg_stay
    FROM property_bookings
    WHERE nights > 0
""")
bookings = cur.fetchone()

print(f"\n📅 BOOKING METRICS:")
print(f"   Total bookings: {bookings['total_bookings']}")
print(f"   Total nights:   {bookings['total_nights']:,}")
print(f"   Avg stay:       {bookings['avg_stay']} nights")

# Estimated revenue potential
cur.execute("""
    SELECT 
        b.property_code,
        SUM(b.nights) as booked_nights,
        ROUND(AVG(p.adr)) as avg_adr,
        ROUND(SUM(b.nights) * AVG(p.adr)) as est_revenue
    FROM property_bookings b
    JOIN property_pricing p ON b.property_code = p.property_code
    WHERE b.nights > 0 AND p.adr > 0
    GROUP BY b.property_code
    ORDER BY SUM(b.nights) * AVG(p.adr) DESC
    LIMIT 10
""")
revenue = cur.fetchall()

print(f"\n💵 TOP REVENUE PROPERTIES (Est. from scraped data):")
for row in revenue:
    print(f"   {row['property_code']}: ${row['est_revenue']:,.0f} ({row['booked_nights']} nights × ${row['avg_adr']}/night)")

# Missing data
cur.execute("""
    SELECT property_code, address_street 
    FROM properties 
    WHERE property_code NOT IN (SELECT DISTINCT property_code FROM property_bookings)
    AND property_code NOT IN (SELECT DISTINCT property_code FROM property_pricing)
""")
no_data = cur.fetchall()

print(f"\n❓ PROPERTIES WITH NO SCRAPED DATA ({len(no_data)}):")
for row in no_data[:5]:
    print(f"   {row['property_code']}: {row['address_street'][:40]}")
if len(no_data) > 5:
    print(f"   ... and {len(no_data) - 5} more")

cur.close()
conn.close()

print("\n" + "=" * 70)
print("COMPLETE")
print("=" * 70)
