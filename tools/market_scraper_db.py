#!/usr/bin/env python3
"""
Market Scraper DB Integration

Saves scraped listings to the external_listings table and tracks
booking velocity over time for dynamic pricing signals.

USAGE:
    python market_scraper_db.py --market 30a_fl --save-to-db
    
    # Or import and use programmatically
    from tools.market_scraper_db import run_market_scrape
    await run_market_scrape("30a_fl", save_to_db=True)
"""

import asyncio
import argparse
import json
import os
import sys
from dataclasses import asdict
from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional, Tuple

import psycopg2
from psycopg2.extras import RealDictCursor, execute_values

# Import the existing scraper
from signal_scraper import (
    MarketIntelligenceScraper,
    ScraperConfig,
    ScrapedListing,
    MarketSignals,
)


DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://rental:rental@localhost:5433/rental_revenue"
)


# =============================================================================
# MARKET CONFIGURATIONS
# =============================================================================

MARKETS = {
    "30a_fl": {
        "name": "30A Corridor",
        "lat": 30.2833,
        "lng": -86.0167,
        "radius_miles": 15,
        "submarkets": {
            "alys_beach": {"lat": 30.2945, "lng": -86.0298, "radius": 1},
            "rosemary_beach": {"lat": 30.2796, "lng": -86.0165, "radius": 1.5},
            "watercolor": {"lat": 30.2891, "lng": -86.0444, "radius": 2},
            "seaside": {"lat": 30.3210, "lng": -86.1438, "radius": 1},
            "seagrove": {"lat": 30.3186, "lng": -86.1067, "radius": 2},
            "watersound": {"lat": 30.2874, "lng": -86.0081, "radius": 2},
            "seacrest": {"lat": 30.2982, "lng": -86.0523, "radius": 1.5},
        }
    },
    "destin_fl": {
        "name": "Destin",
        "lat": 30.3935,
        "lng": -86.4958,
        "radius_miles": 10,
    },
    "gulf_shores_al": {
        "name": "Gulf Shores",
        "lat": 30.2460,
        "lng": -87.7008,
        "radius_miles": 12,
    },
}


# =============================================================================
# DATABASE INTEGRATION
# =============================================================================

class MarketScraperDB:
    """
    Database integration for market scraper.
    
    Saves listings to external_listings table and tracks
    calendar compression over time for booking velocity signals.
    """
    
    def __init__(self, database_url: str = None):
        self.database_url = database_url or DATABASE_URL
    
    def _get_connection(self):
        return psycopg2.connect(self.database_url)
    
    def assign_submarket(
        self,
        lat: float,
        lng: float,
        market_id: str,
    ) -> Optional[str]:
        """
        Assign a listing to a submarket based on lat/lng.
        
        Simple distance-based assignment for now.
        """
        if market_id not in MARKETS:
            return None
        
        market = MARKETS[market_id]
        submarkets = market.get("submarkets", {})
        
        if not submarkets:
            return None
        
        import math
        
        def haversine_miles(lat1, lng1, lat2, lng2):
            R = 3959  # Earth radius in miles
            dlat = math.radians(lat2 - lat1)
            dlng = math.radians(lng2 - lng1)
            a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng/2)**2
            return 2 * R * math.asin(math.sqrt(a))
        
        best_match = None
        best_distance = float('inf')
        
        for submarket_id, sm_data in submarkets.items():
            dist = haversine_miles(lat, lng, sm_data["lat"], sm_data["lng"])
            if dist < sm_data.get("radius", 2) and dist < best_distance:
                best_match = submarket_id
                best_distance = dist
        
        return best_match
    
    def get_operator_listing_ids(self) -> set:
        """
        Get listing IDs from operator properties to exclude from external data.
        
        This ensures market intelligence is based on EXTERNAL data only,
        not contaminated by operator's own properties.
        """
        conn = self._get_connection()
        cur = conn.cursor()
        
        # Get any external listing IDs that might be linked to operator properties
        # This would be populated if we ever link external listings to internal properties
        cur.execute("""
            SELECT DISTINCT listing_url 
            FROM properties 
            WHERE listing_url IS NOT NULL
        """)
        urls = [r[0] for r in cur.fetchall() if r[0]]
        
        # Extract listing IDs from URLs
        operator_ids = set()
        import re
        for url in urls:
            # Airbnb: /rooms/12345
            match = re.search(r'/rooms/(\d+)', url)
            if match:
                operator_ids.add(match.group(1))
            # VRBO: /12345
            match = re.search(r'vrbo\.com/(\d+)', url)
            if match:
                operator_ids.add(match.group(1))
        
        cur.close()
        conn.close()
        
        return operator_ids
    
    def save_listings(
        self,
        listings: List[ScrapedListing],
        market_id: str,
        exclude_operator: bool = True,
    ) -> Dict[str, int]:
        """
        Save scraped listings to external_listings table.
        
        Args:
            listings: Scraped listings
            market_id: Market identifier
            exclude_operator: If True, skip listings that match operator properties
        
        Returns count of inserted/updated records.
        """
        if not listings:
            return {"inserted": 0, "updated": 0, "skipped_operator": 0}
        
        # Get operator listing IDs to exclude
        operator_ids = self.get_operator_listing_ids() if exclude_operator else set()
        
        conn = self._get_connection()
        cur = conn.cursor()
        
        inserted = 0
        updated = 0
        skipped_operator = 0
        
        for listing in listings:
            # Skip operator-owned listings
            if listing.listing_id in operator_ids:
                skipped_operator += 1
                continue
            # Assign submarket
            submarket_id = None
            if listing.latitude and listing.longitude:
                submarket_id = self.assign_submarket(
                    listing.latitude,
                    listing.longitude,
                    market_id,
                )
            
            try:
                cur.execute("""
                    INSERT INTO external_listings (
                        listing_id, source, market_id, submarket_id,
                        latitude, longitude,
                        bedrooms, bathrooms, sleeps, property_type,
                        avg_adr,
                        has_pool, has_hot_tub, has_view,
                        beach_access_type, pet_friendly,
                        review_score, review_count, is_superhost,
                        scraped_at, last_updated, is_active
                    ) VALUES (
                        %s, %s, %s, %s,
                        %s, %s,
                        %s, %s, %s, %s,
                        %s,
                        %s, %s, %s,
                        %s, %s,
                        %s, %s, %s,
                        %s, %s, %s
                    )
                    ON CONFLICT (source, listing_id) DO UPDATE SET
                        submarket_id = EXCLUDED.submarket_id,
                        bedrooms = COALESCE(EXCLUDED.bedrooms, external_listings.bedrooms),
                        bathrooms = COALESCE(EXCLUDED.bathrooms, external_listings.bathrooms),
                        sleeps = COALESCE(EXCLUDED.sleeps, external_listings.sleeps),
                        avg_adr = EXCLUDED.avg_adr,
                        has_pool = EXCLUDED.has_pool,
                        has_hot_tub = EXCLUDED.has_hot_tub,
                        review_score = COALESCE(EXCLUDED.review_score, external_listings.review_score),
                        review_count = COALESCE(EXCLUDED.review_count, external_listings.review_count),
                        last_updated = NOW(),
                        is_active = true
                    RETURNING (xmax = 0) as is_insert
                """, (
                    listing.listing_id,
                    listing.platform,
                    market_id,
                    submarket_id,
                    listing.latitude,
                    listing.longitude,
                    listing.bedrooms,
                    listing.bathrooms,
                    listing.sleeps,
                    listing.property_type,
                    listing.displayed_rate,
                    listing.has_pool,
                    listing.has_hot_tub,
                    listing.has_waterfront or listing.has_beach_access,
                    'beach' if listing.has_beach_access else 'none',
                    listing.has_pet_friendly,
                    listing.rating,
                    listing.review_count,
                    False,  # is_superhost - not extracted yet
                    datetime.utcnow(),
                    datetime.utcnow(),
                    True,
                ))
                
                result = cur.fetchone()
                if result and result[0]:
                    inserted += 1
                else:
                    updated += 1
                    
            except Exception as e:
                print(f"  ⚠️ Error saving listing {listing.listing_id}: {e}")
                continue
        
        conn.commit()
        cur.close()
        conn.close()
        
        return {"inserted": inserted, "updated": updated, "skipped_operator": skipped_operator}
    
    def save_calendar_snapshot(
        self,
        listings: List[ScrapedListing],
        market_id: str,
    ) -> int:
        """
        Save calendar compression snapshot for booking velocity tracking.
        
        This allows us to track how fast bookings are happening over time.
        """
        conn = self._get_connection()
        cur = conn.cursor()
        
        # Create table if not exists
        cur.execute("""
            CREATE TABLE IF NOT EXISTS market_calendar_snapshots (
                id SERIAL PRIMARY KEY,
                market_id VARCHAR(50) NOT NULL,
                snapshot_date DATE NOT NULL,
                
                -- Compression metrics
                compression_7d DECIMAL(5, 4),
                compression_14d DECIMAL(5, 4),
                compression_30d DECIMAL(5, 4),
                compression_90d DECIMAL(5, 4),
                
                -- Sample info
                listings_sampled INTEGER,
                
                -- By bedroom
                compression_by_bedrooms JSONB,
                
                created_at TIMESTAMP DEFAULT NOW(),
                
                CONSTRAINT market_calendar_unique UNIQUE (market_id, snapshot_date)
            )
        """)
        
        # Calculate compression metrics
        today = date.today()
        listings_with_cal = [l for l in listings if l.calendar]
        
        if not listings_with_cal:
            conn.commit()
            cur.close()
            conn.close()
            return 0
        
        def calc_compression(days: int) -> float:
            unavail = 0
            total = 0
            for l in listings_with_cal:
                for i in range(days):
                    check_date = (today + timedelta(days=i)).isoformat()
                    if check_date in l.calendar:
                        total += 1
                        if not l.calendar[check_date]:
                            unavail += 1
            return unavail / total if total > 0 else 0
        
        compression_7d = calc_compression(7)
        compression_14d = calc_compression(14)
        compression_30d = calc_compression(30)
        compression_90d = calc_compression(90)
        
        # By bedroom
        compression_by_br = {}
        for br in [1, 2, 3, 4, 5, 6]:
            br_listings = [l for l in listings_with_cal if l.bedrooms == br]
            if br_listings:
                unavail = 0
                total = 0
                for l in br_listings:
                    for i in range(30):
                        check_date = (today + timedelta(days=i)).isoformat()
                        if check_date in l.calendar:
                            total += 1
                            if not l.calendar[check_date]:
                                unavail += 1
                if total > 0:
                    compression_by_br[str(br)] = round(unavail / total, 4)
        
        # Insert snapshot
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
                compression_90d = EXCLUDED.compression_90d,
                listings_sampled = EXCLUDED.listings_sampled,
                compression_by_bedrooms = EXCLUDED.compression_by_bedrooms
        """, (
            market_id,
            today,
            compression_7d,
            compression_14d,
            compression_30d,
            compression_90d,
            len(listings_with_cal),
            json.dumps(compression_by_br),
        ))
        
        conn.commit()
        cur.close()
        conn.close()
        
        return len(listings_with_cal)
    
    def get_booking_velocity(self, market_id: str, days: int = 7) -> Dict[str, Any]:
        """
        Calculate booking velocity from calendar snapshots.
        
        Compares compression today vs N days ago to see how fast
        bookings are happening.
        """
        conn = self._get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Get latest and N-days-ago snapshots
        cur.execute("""
            SELECT *
            FROM market_calendar_snapshots
            WHERE market_id = %s
            ORDER BY snapshot_date DESC
            LIMIT 2
        """, (market_id,))
        
        snapshots = cur.fetchall()
        cur.close()
        conn.close()
        
        if len(snapshots) < 2:
            return {
                "market_id": market_id,
                "velocity": None,
                "message": "Need at least 2 snapshots to calculate velocity",
            }
        
        latest = snapshots[0]
        previous = snapshots[1]
        
        # Calculate velocity (change in compression)
        velocity_7d = (latest['compression_7d'] or 0) - (previous['compression_7d'] or 0)
        velocity_30d = (latest['compression_30d'] or 0) - (previous['compression_30d'] or 0)
        
        days_between = (latest['snapshot_date'] - previous['snapshot_date']).days
        
        return {
            "market_id": market_id,
            "latest_date": latest['snapshot_date'].isoformat(),
            "previous_date": previous['snapshot_date'].isoformat(),
            "days_between": days_between,
            "compression_now": {
                "7d": float(latest['compression_7d'] or 0),
                "30d": float(latest['compression_30d'] or 0),
            },
            "compression_previous": {
                "7d": float(previous['compression_7d'] or 0),
                "30d": float(previous['compression_30d'] or 0),
            },
            "velocity": {
                "7d_change": round(velocity_7d, 4),
                "30d_change": round(velocity_30d, 4),
            },
            "interpretation": self._interpret_velocity(velocity_30d),
        }
    
    def _interpret_velocity(self, velocity: float) -> str:
        """Interpret booking velocity for dynamic pricing."""
        if velocity > 0.15:
            return "🔥 VERY HIGH - Bookings accelerating fast. Increase ADR 15-25%"
        elif velocity > 0.08:
            return "📈 HIGH - Strong booking pace. Increase ADR 10-15%"
        elif velocity > 0.03:
            return "➡️ MODERATE - Normal booking pace. Hold ADR"
        elif velocity > -0.03:
            return "➡️ STABLE - Steady market. Hold ADR"
        elif velocity > -0.08:
            return "📉 SLOW - Bookings slowing. Consider 5-10% discount"
        else:
            return "⚠️ VERY SLOW - Weak demand. Consider 10-20% discount"
    
    def get_market_summary(self, market_id: str) -> Dict[str, Any]:
        """Get summary of scraped market data."""
        conn = self._get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Count listings
        cur.execute("""
            SELECT 
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE source = 'airbnb') as airbnb,
                COUNT(*) FILTER (WHERE source = 'vrbo') as vrbo,
                AVG(avg_adr) as avg_adr,
                AVG(avg_adr) FILTER (WHERE bedrooms = 2) as avg_adr_2br,
                AVG(avg_adr) FILTER (WHERE bedrooms = 3) as avg_adr_3br,
                AVG(avg_adr) FILTER (WHERE bedrooms = 4) as avg_adr_4br,
                AVG(avg_adr) FILTER (WHERE bedrooms = 5) as avg_adr_5br,
                COUNT(*) FILTER (WHERE has_pool) as with_pool,
                AVG(avg_adr) FILTER (WHERE has_pool) as avg_adr_with_pool,
                AVG(avg_adr) FILTER (WHERE NOT has_pool) as avg_adr_without_pool,
                MAX(last_updated) as last_scraped
            FROM external_listings
            WHERE market_id = %s AND is_active = true
        """, (market_id,))
        
        stats = dict(cur.fetchone())
        
        # By submarket
        cur.execute("""
            SELECT 
                submarket_id,
                COUNT(*) as count,
                AVG(avg_adr) as avg_adr
            FROM external_listings
            WHERE market_id = %s AND is_active = true AND submarket_id IS NOT NULL
            GROUP BY submarket_id
            ORDER BY avg_adr DESC NULLS LAST
        """, (market_id,))
        
        by_submarket = [dict(r) for r in cur.fetchall()]
        
        cur.close()
        conn.close()
        
        # Calculate pool lift from external data
        pool_lift = None
        if stats.get('avg_adr_with_pool') and stats.get('avg_adr_without_pool'):
            pool_lift = {
                "with_pool": round(float(stats['avg_adr_with_pool']), 0),
                "without_pool": round(float(stats['avg_adr_without_pool']), 0),
                "lift_dollars": round(float(stats['avg_adr_with_pool']) - float(stats['avg_adr_without_pool']), 0),
                "lift_pct": round((float(stats['avg_adr_with_pool']) - float(stats['avg_adr_without_pool'])) / float(stats['avg_adr_without_pool']), 4),
            }
        
        return {
            "market_id": market_id,
            "total_listings": stats['total'],
            "by_platform": {
                "airbnb": stats['airbnb'],
                "vrbo": stats['vrbo'],
            },
            "avg_adr": round(float(stats['avg_adr']), 0) if stats['avg_adr'] else None,
            "adr_by_bedrooms": {
                "2br": round(float(stats['avg_adr_2br']), 0) if stats['avg_adr_2br'] else None,
                "3br": round(float(stats['avg_adr_3br']), 0) if stats['avg_adr_3br'] else None,
                "4br": round(float(stats['avg_adr_4br']), 0) if stats['avg_adr_4br'] else None,
                "5br": round(float(stats['avg_adr_5br']), 0) if stats['avg_adr_5br'] else None,
            },
            "pool_prevalence": round(stats['with_pool'] / stats['total'], 3) if stats['total'] else 0,
            "pool_lift": pool_lift,
            "by_submarket": by_submarket,
            "last_scraped": stats['last_scraped'].isoformat() if stats['last_scraped'] else None,
        }


# =============================================================================
# MAIN RUNNER
# =============================================================================

async def run_market_scrape(
    market_id: str,
    save_to_db: bool = True,
    save_to_file: bool = True,
) -> Tuple[MarketSignals, Dict[str, Any]]:
    """
    Run market scrape and optionally save to database.
    
    Args:
        market_id: Market identifier (e.g., "30a_fl")
        save_to_db: Save listings to external_listings table
        save_to_file: Save JSON files to market_data/
    
    Returns:
        Tuple of (signals, db_stats)
    """
    if market_id not in MARKETS:
        print(f"❌ Unknown market: {market_id}")
        print(f"   Available: {list(MARKETS.keys())}")
        return None, {}
    
    market = MARKETS[market_id]
    
    # Run scraper
    config = ScraperConfig(
        output_dir="./market_data",
        max_listings_per_platform=300,
    )
    scraper = MarketIntelligenceScraper(config)
    
    try:
        signals, listings = await scraper.scrape_market(
            market_id=market_id,
            market_name=market["name"],
            lat=market["lat"],
            lng=market["lng"],
            radius_miles=market["radius_miles"],
        )
        
        # Print report
        scraper.print_signal_report(signals)
        
        db_stats = {}
        
        if save_to_db:
            print("\n💾 Saving to database...")
            db = MarketScraperDB()
            
            # Save listings
            save_result = db.save_listings(listings, market_id)
            print(f"   ✅ Inserted: {save_result['inserted']}, Updated: {save_result['updated']}")
            
            # Save calendar snapshot
            cal_count = db.save_calendar_snapshot(listings, market_id)
            print(f"   ✅ Calendar snapshot: {cal_count} listings")
            
            # Get summary
            summary = db.get_market_summary(market_id)
            print(f"\n📊 Market Summary:")
            print(f"   Total listings: {summary['total_listings']}")
            print(f"   Avg ADR: ${summary['avg_adr']}")
            if summary['pool_lift']:
                print(f"   Pool lift: +${summary['pool_lift']['lift_dollars']} ({summary['pool_lift']['lift_pct']:.1%})")
            
            db_stats = {
                "saved": save_result,
                "calendar_snapshot": cal_count,
                "summary": summary,
            }
        
        if save_to_file:
            scraper.save_results(signals, listings)
        
        return signals, db_stats
        
    finally:
        await scraper.close()


async def main():
    parser = argparse.ArgumentParser(description="Market Scraper with DB Integration")
    
    parser.add_argument(
        '--market',
        required=True,
        choices=list(MARKETS.keys()),
        help='Market to scrape'
    )
    parser.add_argument(
        '--save-to-db',
        action='store_true',
        help='Save results to database'
    )
    parser.add_argument(
        '--no-file',
        action='store_true',
        help='Skip saving JSON files'
    )
    parser.add_argument(
        '--velocity',
        action='store_true',
        help='Show booking velocity (requires previous scrape data)'
    )
    parser.add_argument(
        '--summary',
        action='store_true',
        help='Show market summary from database'
    )
    
    args = parser.parse_args()
    
    db = MarketScraperDB()
    
    if args.velocity:
        velocity = db.get_booking_velocity(args.market)
        print(f"\n📈 BOOKING VELOCITY: {args.market}")
        print(json.dumps(velocity, indent=2))
        return
    
    if args.summary:
        summary = db.get_market_summary(args.market)
        print(f"\n📊 MARKET SUMMARY: {args.market}")
        print(json.dumps(summary, indent=2, default=str))
        return
    
    await run_market_scrape(
        market_id=args.market,
        save_to_db=args.save_to_db,
        save_to_file=not args.no_file,
    )


if __name__ == "__main__":
    asyncio.run(main())
