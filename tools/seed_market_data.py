#!/usr/bin/env python3
"""
Sample Market Data Seeder

Seeds the external_listings table with realistic sample data for testing
the market intelligence system.

In production, this data would come from:
1. OTA scrapers with proper proxy rotation
2. Third-party data providers (AirDNA, Transparent, etc.)
3. MLS feeds

USAGE:
    python seed_market_data.py --market 30a_fl --count 200
"""

import argparse
import random
import string
from datetime import datetime, date, timedelta
from typing import List, Dict

import psycopg2
from psycopg2.extras import execute_values


DATABASE_URL = "postgresql://rental:rental@localhost:5433/rental_revenue"


# =============================================================================
# 30A MARKET CONFIGURATION
# =============================================================================

SUBMARKETS_30A = {
    "alys_beach": {
        "tier": 0,
        "base_adr": 1800,
        "pool_pct": 0.3,  # Fewer pools in Alys (community pools)
        "hot_tub_pct": 0.2,
        "view_pct": 0.4,
        "lat_range": (30.290, 30.300),
        "lng_range": (-86.040, -86.020),
    },
    "rosemary_beach": {
        "tier": 1,
        "base_adr": 1400,
        "pool_pct": 0.5,
        "hot_tub_pct": 0.3,
        "view_pct": 0.35,
        "lat_range": (30.275, 30.285),
        "lng_range": (-86.025, -86.005),
    },
    "watercolor": {
        "tier": 1,
        "base_adr": 1300,
        "pool_pct": 0.7,
        "hot_tub_pct": 0.25,
        "view_pct": 0.3,
        "lat_range": (30.285, 30.295),
        "lng_range": (-86.055, -86.035),
    },
    "seaside": {
        "tier": 1,
        "base_adr": 1200,
        "pool_pct": 0.4,
        "hot_tub_pct": 0.2,
        "view_pct": 0.5,
        "lat_range": (30.318, 30.328),
        "lng_range": (-86.150, -86.135),
    },
    "seagrove": {
        "tier": 2,
        "base_adr": 900,
        "pool_pct": 0.6,
        "hot_tub_pct": 0.35,
        "view_pct": 0.25,
        "lat_range": (30.315, 30.325),
        "lng_range": (-86.115, -86.095),
    },
    "watersound": {
        "tier": 2,
        "base_adr": 950,
        "pool_pct": 0.65,
        "hot_tub_pct": 0.3,
        "view_pct": 0.2,
        "lat_range": (30.283, 30.293),
        "lng_range": (-86.020, -85.995),
    },
    "seacrest": {
        "tier": 2,
        "base_adr": 850,
        "pool_pct": 0.75,  # Community pools common
        "hot_tub_pct": 0.4,
        "view_pct": 0.15,
        "lat_range": (30.295, 30.305),
        "lng_range": (-86.060, -86.045),
    },
    "inlet_beach": {
        "tier": 3,
        "base_adr": 700,
        "pool_pct": 0.55,
        "hot_tub_pct": 0.25,
        "view_pct": 0.1,
        "lat_range": (30.265, 30.280),
        "lng_range": (-85.960, -85.940),
    },
}

# ADR adjustments by bedroom count
BEDROOM_MULTIPLIERS = {
    1: 0.5,
    2: 0.75,
    3: 1.0,
    4: 1.25,
    5: 1.5,
    6: 1.75,
    7: 2.0,
    8: 2.25,
}

# Amenity ADR lifts (what we're trying to measure)
AMENITY_LIFTS = {
    "pool": 0.18,      # 18% lift
    "hot_tub": 0.08,   # 8% lift  
    "view": 0.25,      # 25% lift
    "pet_friendly": 0.05,  # 5% lift
}


def generate_listing_id(source: str) -> str:
    """Generate realistic listing ID."""
    if source == "airbnb":
        return str(random.randint(10000000, 99999999))
    else:
        return str(random.randint(1000000, 9999999))


def generate_listing(
    submarket_id: str,
    submarket_config: Dict,
    source: str,
) -> Dict:
    """Generate a single realistic listing."""
    
    # Random bedroom count (weighted toward 3-4)
    bedrooms = random.choices(
        [1, 2, 3, 4, 5, 6, 7, 8],
        weights=[5, 15, 25, 30, 15, 7, 2, 1],
        k=1
    )[0]
    
    # Calculate base ADR
    base_adr = submarket_config["base_adr"]
    adr = base_adr * BEDROOM_MULTIPLIERS.get(bedrooms, 1.0)
    
    # Determine amenities
    has_pool = random.random() < submarket_config["pool_pct"]
    has_hot_tub = random.random() < submarket_config["hot_tub_pct"]
    has_view = random.random() < submarket_config["view_pct"]
    pet_friendly = random.random() < 0.35  # 35% pet friendly overall
    
    # Apply amenity lifts
    if has_pool:
        adr *= (1 + AMENITY_LIFTS["pool"])
    if has_hot_tub:
        adr *= (1 + AMENITY_LIFTS["hot_tub"])
    if has_view:
        adr *= (1 + AMENITY_LIFTS["view"])
    if pet_friendly:
        adr *= (1 + AMENITY_LIFTS["pet_friendly"])
    
    # Add random variance (+/- 15%)
    adr *= random.uniform(0.85, 1.15)
    
    # Generate location
    lat = random.uniform(*submarket_config["lat_range"])
    lng = random.uniform(*submarket_config["lng_range"])
    
    # Generate review data
    review_score = round(random.uniform(4.2, 5.0), 2) if random.random() > 0.1 else None
    review_count = random.randint(5, 200) if review_score else None
    
    return {
        "listing_id": generate_listing_id(source),
        "source": source,
        "market_id": "30a_fl",
        "submarket_id": submarket_id,
        "latitude": round(lat, 6),
        "longitude": round(lng, 6),
        "bedrooms": bedrooms,
        "bathrooms": bedrooms + random.choice([0, 0.5, 1]),
        "sleeps": bedrooms * 2 + random.randint(0, 2),
        "property_type": random.choice(["house", "house", "house", "condo", "townhouse"]),
        "avg_adr": round(adr, 2),
        "has_pool": has_pool,
        "pool_type": "private" if has_pool and random.random() > 0.3 else "shared" if has_pool else "none",
        "pool_heated": has_pool and random.random() < 0.3,
        "has_hot_tub": has_hot_tub,
        "has_view": has_view,
        "view_type": random.choice(["gulf", "lake", "pool"]) if has_view else "none",
        "beach_access_type": random.choice(["community", "deeded", "public"]),
        "pet_friendly": pet_friendly,
        "parking_type": random.choice(["driveway", "garage", "street"]),
        "review_score": review_score,
        "review_count": review_count,
        "is_superhost": random.random() < 0.3,
        "scraped_at": datetime.utcnow(),
        "is_active": True,
    }


def seed_market_data(market_id: str, count: int = 200) -> Dict:
    """Seed market with sample data."""
    
    if market_id != "30a_fl":
        return {"error": f"Market {market_id} not configured. Only 30a_fl available."}
    
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    
    listings = []
    
    # Distribute listings across submarkets (weighted by typical market share)
    submarket_weights = {
        "alys_beach": 3,
        "rosemary_beach": 10,
        "watercolor": 20,
        "seaside": 12,
        "seagrove": 25,
        "watersound": 15,
        "seacrest": 10,
        "inlet_beach": 5,
    }
    
    total_weight = sum(submarket_weights.values())
    
    for submarket_id, weight in submarket_weights.items():
        submarket_count = int(count * weight / total_weight)
        config = SUBMARKETS_30A[submarket_id]
        
        for _ in range(submarket_count):
            # Alternate sources
            source = random.choice(["airbnb", "airbnb", "vrbo"])  # 2:1 Airbnb:VRBO
            listing = generate_listing(submarket_id, config, source)
            listings.append(listing)
    
    # Insert listings
    insert_sql = """
        INSERT INTO external_listings (
            listing_id, source, market_id, submarket_id,
            latitude, longitude,
            bedrooms, bathrooms, sleeps, property_type,
            avg_adr,
            has_pool, pool_type, pool_heated,
            has_hot_tub, has_view, view_type,
            beach_access_type, pet_friendly, parking_type,
            review_score, review_count, is_superhost,
            scraped_at, is_active
        ) VALUES %s
        ON CONFLICT (source, listing_id) DO UPDATE SET
            avg_adr = EXCLUDED.avg_adr,
            last_updated = NOW()
    """
    
    values = [
        (
            l["listing_id"], l["source"], l["market_id"], l["submarket_id"],
            l["latitude"], l["longitude"],
            l["bedrooms"], l["bathrooms"], l["sleeps"], l["property_type"],
            l["avg_adr"],
            l["has_pool"], l["pool_type"], l["pool_heated"],
            l["has_hot_tub"], l["has_view"], l["view_type"],
            l["beach_access_type"], l["pet_friendly"], l["parking_type"],
            l["review_score"], l["review_count"], l["is_superhost"],
            l["scraped_at"], l["is_active"],
        )
        for l in listings
    ]
    
    execute_values(cur, insert_sql, values)
    conn.commit()
    
    # Get summary
    cur.execute("""
        SELECT 
            submarket_id,
            COUNT(*) as count,
            ROUND(AVG(avg_adr)::numeric, 0) as avg_adr,
            ROUND(AVG(avg_adr) FILTER (WHERE has_pool)::numeric, 0) as adr_with_pool,
            ROUND(AVG(avg_adr) FILTER (WHERE NOT has_pool)::numeric, 0) as adr_without_pool
        FROM external_listings
        WHERE market_id = %s
        GROUP BY submarket_id
        ORDER BY avg_adr DESC
    """, (market_id,))
    
    by_submarket = [dict(zip(['submarket', 'count', 'avg_adr', 'adr_with_pool', 'adr_without_pool'], r)) for r in cur.fetchall()]
    
    cur.close()
    conn.close()
    
    return {
        "status": "success",
        "market_id": market_id,
        "listings_seeded": len(listings),
        "by_submarket": by_submarket,
        "note": "This is SAMPLE DATA for testing. Replace with real scrapes for production.",
        "built_in_lifts": AMENITY_LIFTS,
    }


def seed_calendar_snapshots(market_id: str, days_back: int = 7) -> Dict:
    """
    Seed calendar compression snapshots to enable velocity calculation.
    
    Creates historical snapshots showing gradual increase in bookings.
    """
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    
    # Create table if not exists
    cur.execute("""
        CREATE TABLE IF NOT EXISTS market_calendar_snapshots (
            id SERIAL PRIMARY KEY,
            market_id VARCHAR(50) NOT NULL,
            snapshot_date DATE NOT NULL,
            compression_7d DECIMAL(5, 4),
            compression_14d DECIMAL(5, 4),
            compression_30d DECIMAL(5, 4),
            compression_90d DECIMAL(5, 4),
            listings_sampled INTEGER,
            compression_by_bedrooms JSONB,
            created_at TIMESTAMP DEFAULT NOW(),
            CONSTRAINT market_calendar_unique UNIQUE (market_id, snapshot_date)
        )
    """)
    
    # Seed snapshots for past N days
    today = date.today()
    
    for days_ago in range(days_back, -1, -1):
        snapshot_date = today - timedelta(days=days_ago)
        
        # Simulate increasing compression as we get closer to today
        # (more bookings happening over time)
        base_compression = 0.45 + (days_back - days_ago) * 0.02  # Increases ~2% per day
        
        compression_7d = min(0.95, base_compression + random.uniform(-0.03, 0.05))
        compression_14d = min(0.90, base_compression - 0.05 + random.uniform(-0.03, 0.05))
        compression_30d = min(0.85, base_compression - 0.10 + random.uniform(-0.03, 0.05))
        compression_90d = min(0.70, base_compression - 0.20 + random.uniform(-0.03, 0.05))
        
        by_bedrooms = {
            "2": round(compression_30d + random.uniform(-0.05, 0.05), 4),
            "3": round(compression_30d + random.uniform(-0.05, 0.05), 4),
            "4": round(compression_30d + 0.05 + random.uniform(-0.03, 0.03), 4),  # 4BR books faster
            "5": round(compression_30d + 0.03 + random.uniform(-0.03, 0.03), 4),
        }
        
        cur.execute("""
            INSERT INTO market_calendar_snapshots (
                market_id, snapshot_date,
                compression_7d, compression_14d, compression_30d, compression_90d,
                listings_sampled, compression_by_bedrooms
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (market_id, snapshot_date) DO UPDATE SET
                compression_7d = EXCLUDED.compression_7d,
                compression_14d = EXCLUDED.compression_14d,
                compression_30d = EXCLUDED.compression_30d,
                compression_90d = EXCLUDED.compression_90d
        """, (
            market_id,
            snapshot_date,
            round(compression_7d, 4),
            round(compression_14d, 4),
            round(compression_30d, 4),
            round(compression_90d, 4),
            random.randint(150, 200),
            str(by_bedrooms).replace("'", '"'),
        ))
    
    conn.commit()
    cur.close()
    conn.close()
    
    return {
        "status": "success",
        "market_id": market_id,
        "snapshots_seeded": days_back + 1,
        "date_range": f"{(today - timedelta(days=days_back)).isoformat()} to {today.isoformat()}",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed market data for testing")
    parser.add_argument("--market", default="30a_fl", help="Market ID")
    parser.add_argument("--count", type=int, default=200, help="Number of listings to seed")
    parser.add_argument("--with-velocity", action="store_true", help="Also seed calendar snapshots")
    
    args = parser.parse_args()
    
    print(f"\n🌱 Seeding {args.count} listings for {args.market}...")
    result = seed_market_data(args.market, args.count)
    
    print(f"\n✅ Seeded {result.get('listings_seeded', 0)} listings")
    print("\nBy Submarket:")
    for sm in result.get("by_submarket", []):
        pool_lift = ""
        if sm.get('adr_with_pool') and sm.get('adr_without_pool'):
            lift = (sm['adr_with_pool'] - sm['adr_without_pool']) / sm['adr_without_pool']
            pool_lift = f" (pool lift: {lift:.1%})"
        print(f"  {sm['submarket']}: {sm['count']} listings, ${sm['avg_adr']} avg ADR{pool_lift}")
    
    print(f"\n📊 Built-in amenity lifts: {result.get('built_in_lifts', {})}")
    
    if args.with_velocity:
        print("\n📈 Seeding calendar snapshots for velocity...")
        vel_result = seed_calendar_snapshots(args.market)
        print(f"✅ Seeded {vel_result['snapshots_seeded']} snapshots")
    
    print("\n🔗 Test endpoints:")
    print(f"   curl http://localhost:8080/api/v1/market-intel/markets/{args.market}/summary | python -m json.tool")
    print(f"   curl 'http://localhost:8080/api/v1/market-intel/markets/{args.market}/amenity-attribution?amenity=pool' | python -m json.tool")
    if args.with_velocity:
        print(f"   curl http://localhost:8080/api/v1/market-intel/markets/{args.market}/booking-velocity | python -m json.tool")
