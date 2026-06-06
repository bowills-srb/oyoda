#!/usr/bin/env python3
"""
Clean up booking data:
1. Remove bookings > 60 nights (likely owner blocks)
2. Remove 0-night bookings (data errors)
3. Flag long-term rentals (30-60 nights) for review
"""

import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = "postgresql://rental:rental@localhost:5433/rental_revenue"

def main():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    cur = conn.cursor()
    
    print("=" * 70)
    print("CLEANING BOOKING DATA")
    print("=" * 70)
    
    # Count before
    cur.execute("SELECT COUNT(*) as cnt, SUM(nights) as nights FROM property_bookings")
    before = cur.fetchone()
    print(f"\nBefore cleanup:")
    print(f"   Bookings: {before['cnt']}")
    print(f"   Total nights: {before['nights']:,}")
    
    # Remove 0-night bookings (data errors)
    cur.execute("DELETE FROM property_bookings WHERE nights = 0 OR nights IS NULL")
    zero_deleted = cur.rowcount
    print(f"\n🗑️  Deleted {zero_deleted} zero-night bookings (data errors)")
    
    # Remove bookings > 60 nights (owner blocks)
    cur.execute("""
        DELETE FROM property_bookings 
        WHERE nights > 60
        RETURNING property_code, check_in, check_out, nights
    """)
    owner_blocks = cur.fetchall()
    print(f"🗑️  Deleted {len(owner_blocks)} owner blocks (>60 nights):")
    for row in owner_blocks:
        print(f"      {row['property_code']}: {row['check_in']} → {row['check_out']} ({row['nights']} nights)")
    
    conn.commit()
    
    # Count after
    cur.execute("SELECT COUNT(*) as cnt, SUM(nights) as nights FROM property_bookings")
    after = cur.fetchone()
    print(f"\nAfter cleanup:")
    print(f"   Bookings: {after['cnt']}")
    print(f"   Total nights: {after['nights']:,}")
    
    # Show remaining long stays (30-60 nights) for review
    print("\n⚠️  Remaining long stays (30-60 nights) - may be valid:")
    cur.execute("""
        SELECT property_code, check_in, check_out, nights
        FROM property_bookings
        WHERE nights > 30
        ORDER BY nights DESC
    """)
    for row in cur.fetchall():
        print(f"      {row['property_code']}: {row['check_in']} → {row['check_out']} ({row['nights']} nights)")
    
    # Recalculate metrics
    print("\n" + "=" * 70)
    print("CORRECTED METRICS")
    print("=" * 70)
    
    cur.execute("""
        SELECT 
            COUNT(*) as bookings,
            SUM(nights) as total_nights,
            ROUND(AVG(nights), 1) as avg_stay
        FROM property_bookings
    """)
    metrics = cur.fetchone()
    print(f"\n📅 Booking Metrics:")
    print(f"   Total bookings: {metrics['bookings']}")
    print(f"   Total nights:   {metrics['total_nights']:,}")
    print(f"   Avg stay:       {metrics['avg_stay']} nights")
    
    cur.execute("""
        SELECT 
            b.property_code,
            SUM(b.nights) as booked_nights,
            ROUND(AVG(p.adr)) as avg_adr,
            ROUND(SUM(b.nights) * AVG(p.adr)) as est_revenue
        FROM property_bookings b
        JOIN property_pricing p ON b.property_code = p.property_code
        WHERE p.adr > 0
        GROUP BY b.property_code
        ORDER BY SUM(b.nights) * AVG(p.adr) DESC
        LIMIT 10
    """)
    print(f"\n💵 Top Revenue Properties:")
    for row in cur.fetchall():
        print(f"   {row['property_code']}: ${row['est_revenue']:,.0f} ({row['booked_nights']} nights × ${row['avg_adr']}/night)")
    
    cur.close()
    conn.close()
    
    print("\n✓ Cleanup complete!")


if __name__ == "__main__":
    main()
