"""
Market Intelligence Architecture

PROBLEM:
- Single operator data is self-selecting and too small
- Can't isolate amenity/location effects without comparison data
- Different markets have different value hierarchies

SOLUTION: Multi-source market intelligence with geographic hierarchy

=============================================================================
GEOGRAPHIC HIERARCHY MODEL
=============================================================================

Every market has a hierarchy of value drivers. The system must learn this
hierarchy from data, not assume it.

EXAMPLE: 30A Florida
├── Market: 30A Corridor
│   ├── Submarket: Alys Beach (Tier S - ultra luxury, limited rentals)
│   │   └── Factors: Architecture standards, beach club, restrictive HOA
│   ├── Submarket: Rosemary Beach (Tier 1)
│   │   └── Factors: Town center, walkability, consistent design
│   ├── Submarket: WaterColor (Tier 1)
│   │   └── Factors: Beach club, Western Lake, Camp WaterColor
│   ├── Submarket: Seaside (Tier 1-2)
│   │   └── Factors: Iconic, but older properties
│   ├── Submarket: Seagrove (Tier 2)
│   │   └── Factors: More affordable, beach access
│   └── Submarket: Inlet Beach (Tier 3)
│       └── Factors: Newer development, less walkable

EXAMPLE: Atlanta
├── Market: Metro Atlanta
│   ├── Submarket: Buckhead (Tier 1)
│   │   └── Factors: Luxury, walkable, restaurants
│   ├── Submarket: Midtown (Tier 1-2)
│   │   └── Factors: Arts district, transit
│   ├── Submarket: Virginia Highland (Tier 2)
│   │   └── Factors: Neighborhood feel, dining
│   └── Submarket: Airport Area (Tier 4)
│       └── Factors: Business travel, price-sensitive

EXAMPLE: Ski Resort
├── Market: Park City, UT
│   ├── Submarket: Ski-in/Ski-out (Tier S)
│   │   └── Factors: Slope access is THE driver
│   ├── Submarket: Old Town (Tier 1)
│   │   └── Factors: Walkable, historic, restaurants
│   ├── Submarket: Canyons Village (Tier 1-2)
│   │   └── Factors: Resort amenities, shuttle
│   └── Submarket: Kimball Junction (Tier 3)
│       └── Factors: Affordable, car required

=============================================================================
DATA SOURCES
=============================================================================

1. INTERNAL OPERATOR DATA (Highest Confidence)
   - Source: PMS integration (Guesty, Hostaway, etc.)
   - Data: Actual bookings, ADR, occupancy, guest reviews
   - Coverage: Operator's portfolio only
   - Use: Baseline performance, operator delta calculation

2. EXTERNAL OTA SCRAPES (Broad Coverage)
   - Source: Airbnb, VRBO, Booking.com scrapers
   - Data: Listing details, calendar, pricing, reviews
   - Coverage: Entire market (500-5000+ listings per market)
   - Use: Market-wide amenity attribution, comp identification

3. MLS/PROPERTY RECORDS (Property Details)
   - Source: MLS API, county records
   - Data: Year built, sqft, lot size, sales history
   - Coverage: All properties (not just rentals)
   - Use: Property quality scoring, BD lead identification

4. AGGREGATED OPERATOR DATA (Future - Multi-tenant)
   - Source: Multiple operators on the platform
   - Data: Anonymized, aggregated performance by segment
   - Coverage: Growing as platform scales
   - Use: Market benchmarks, operator ranking

=============================================================================
EXTERNAL LISTING SCRAPER REQUIREMENTS
=============================================================================

For each market, we need to scrape OTA listings with:

REQUIRED FIELDS:
- listing_id, source (airbnb/vrbo)
- lat, lng (for distance calculations)
- bedrooms, bathrooms, sleeps
- property_type (house, condo, etc.)
- pricing (nightly rate, or calendar data)

AMENITIES TO EXTRACT:
- Pool (private, shared, heated)
- Hot tub
- View type (ocean, lake, mountain, city)
- Beach/slope access
- Parking
- Pet policy
- EV charger

QUALITY SIGNALS:
- Review score
- Review count
- Superhost/Premier status
- Response rate

LOCATION PARSING:
- Community/neighborhood (from title or description)
- Distance to key attractions (beach, slopes, downtown)

=============================================================================
IMPLEMENTATION PLAN
=============================================================================

PHASE 1: External Listing Schema (This file)
- Define external_listings table
- Define market_geography table
- Define submarket hierarchy

PHASE 2: OTA Scraper
- Airbnb scraper for 30A market
- VRBO scraper for 30A market
- Geocoding integration
- Rate limiting and rotation

PHASE 3: Geographic Attribution
- Cluster listings by lat/lng
- Auto-detect submarkets
- Calculate submarket premiums

PHASE 4: Amenity Attribution (Market-Wide)
- Pool lift by submarket
- View premium by distance to water
- Property age/quality adjustment

PHASE 5: Multi-Operator Aggregation
- Anonymized performance sharing
- Market benchmarks
- Operator ranking by segment
"""

import os
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, List, Optional, Any, Tuple
from enum import Enum
from decimal import Decimal

import psycopg2
from psycopg2.extras import RealDictCursor

from app.core.db_connect import resolve_runtime_sync_database_url

DATABASE_URL = resolve_runtime_sync_database_url(os.getenv("DATABASE_URL"))


# =============================================================================
# GEOGRAPHIC HIERARCHY
# =============================================================================

@dataclass
class Submarket:
    """A submarket within a larger market."""
    submarket_id: str
    market_id: str
    name: str
    tier: int  # 1 = premium, 4 = budget, 0 = ultra-premium (S-tier)
    
    # Geographic bounds
    polygon_coords: Optional[List[List[float]]] = None  # [[lng, lat], ...]
    centroid_lat: Optional[float] = None
    centroid_lng: Optional[float] = None
    
    # Characteristics
    primary_value_driver: Optional[str] = None  # "beach_access", "walkability", "ski_access"
    rental_restrictions: Optional[str] = None  # "none", "30_day_min", "no_str"
    avg_property_age: Optional[int] = None
    
    # Derived metrics (from data)
    avg_adr: Optional[float] = None
    listing_count: Optional[int] = None
    premium_vs_market: Optional[float] = None  # e.g., 0.25 = 25% above market avg


@dataclass
class Market:
    """A market (metro area, resort region, etc.)."""
    market_id: str
    name: str
    market_type: str  # "beach", "ski", "urban", "lake", "mountain"
    
    # Geography
    state: str
    country: str = "US"
    timezone: str = "America/New_York"
    
    # Market characteristics
    seasonality_type: str = "summer"  # "summer", "winter", "year_round", "event_driven"
    peak_months: List[int] = field(default_factory=lambda: [6, 7, 8])
    
    # Submarkets
    submarkets: List[Submarket] = field(default_factory=list)
    
    # Primary value drivers (ordered by importance)
    value_hierarchy: List[str] = field(default_factory=list)
    # e.g., ["beach_distance", "view_type", "pool", "bedrooms"]


# =============================================================================
# PRE-CONFIGURED MARKETS
# =============================================================================

MARKET_30A = Market(
    market_id="30a_fl",
    name="30A Corridor",
    market_type="beach",
    state="FL",
    timezone="America/Chicago",
    seasonality_type="summer",
    peak_months=[6, 7, 8],
    value_hierarchy=[
        "submarket_tier",      # Alys > Rosemary > WaterColor > Seagrove
        "beach_distance",      # Gulf front > Deeded > Community access
        "view_type",           # Gulf view > Lake view > Pool view > None
        "pool_type",           # Private > Shared community
        "bedrooms",            # More = higher ADR (but not linear)
        "property_quality",    # Renovated > Original
    ],
    submarkets=[
        Submarket(
            submarket_id="alys_beach",
            market_id="30a_fl",
            name="Alys Beach",
            tier=0,  # S-tier
            primary_value_driver="architecture",
            rental_restrictions="30_day_min",
        ),
        Submarket(
            submarket_id="rosemary_beach",
            market_id="30a_fl",
            name="Rosemary Beach",
            tier=1,
            primary_value_driver="walkability",
        ),
        Submarket(
            submarket_id="watercolor",
            market_id="30a_fl",
            name="WaterColor",
            tier=1,
            primary_value_driver="beach_club",
        ),
        Submarket(
            submarket_id="seaside",
            market_id="30a_fl",
            name="Seaside",
            tier=1,
            primary_value_driver="iconic_location",
        ),
        Submarket(
            submarket_id="seagrove",
            market_id="30a_fl",
            name="Seagrove Beach",
            tier=2,
            primary_value_driver="affordability",
        ),
        Submarket(
            submarket_id="watersound",
            market_id="30a_fl",
            name="WaterSound",
            tier=2,
            primary_value_driver="beach_club",
        ),
        Submarket(
            submarket_id="seacrest",
            market_id="30a_fl",
            name="Seacrest Beach",
            tier=2,
            primary_value_driver="community_pool",
        ),
        Submarket(
            submarket_id="inlet_beach",
            market_id="30a_fl",
            name="Inlet Beach",
            tier=3,
            primary_value_driver="new_development",
        ),
    ],
)

MARKET_ATLANTA = Market(
    market_id="atlanta_ga",
    name="Metro Atlanta",
    market_type="urban",
    state="GA",
    timezone="America/New_York",
    seasonality_type="year_round",
    peak_months=[3, 4, 5, 9, 10],  # Spring/Fall events
    value_hierarchy=[
        "submarket_tier",      # Buckhead > Midtown > etc.
        "walkability",         # Walk score matters in urban
        "transit_access",      # MARTA proximity
        "parking",             # Critical in Atlanta
        "bedrooms",
        "amenities",
    ],
    submarkets=[
        Submarket(
            submarket_id="buckhead",
            market_id="atlanta_ga",
            name="Buckhead",
            tier=1,
            primary_value_driver="luxury_dining",
        ),
        Submarket(
            submarket_id="midtown",
            market_id="atlanta_ga",
            name="Midtown",
            tier=1,
            primary_value_driver="arts_transit",
        ),
        Submarket(
            submarket_id="virginia_highland",
            market_id="atlanta_ga",
            name="Virginia Highland",
            tier=2,
            primary_value_driver="neighborhood_charm",
        ),
        Submarket(
            submarket_id="downtown",
            market_id="atlanta_ga",
            name="Downtown",
            tier=2,
            primary_value_driver="convention_center",
        ),
    ],
)


# =============================================================================
# EXTERNAL LISTING MODEL
# =============================================================================

@dataclass 
class ExternalListing:
    """A listing scraped from OTAs (Airbnb, VRBO)."""
    listing_id: str
    source: str  # "airbnb", "vrbo", "booking"
    market_id: str
    
    # Location
    latitude: float
    longitude: float
    submarket_id: Optional[str] = None  # Derived from lat/lng
    address_approx: Optional[str] = None
    
    # Property basics
    bedrooms: int = 0
    bathrooms: float = 0
    sleeps: int = 0
    property_type: str = "house"
    
    # Pricing (scraped or calculated)
    avg_adr: Optional[float] = None
    min_nightly: Optional[float] = None
    max_nightly: Optional[float] = None
    
    # Amenities
    has_pool: bool = False
    pool_type: str = "none"  # "private", "shared", "none"
    pool_heated: bool = False
    has_hot_tub: bool = False
    has_view: bool = False
    view_type: str = "none"  # "gulf", "ocean", "lake", "mountain", "city"
    beach_distance_ft: Optional[int] = None
    beach_access_type: str = "none"  # "private", "deeded", "community", "public"
    pet_friendly: bool = False
    parking_type: str = "none"  # "garage", "driveway", "street", "none"
    
    # Quality signals
    review_score: Optional[float] = None
    review_count: Optional[int] = None
    is_superhost: bool = False
    year_built: Optional[int] = None
    
    # Metadata
    listing_url: Optional[str] = None
    title: Optional[str] = None
    scraped_at: datetime = field(default_factory=datetime.utcnow)
    is_active: bool = True


# =============================================================================
# SCHEMA MIGRATION
# =============================================================================

def generate_market_intelligence_schema() -> str:
    """Generate SQL for market intelligence tables."""
    return """
-- =============================================================================
-- MARKET INTELLIGENCE SCHEMA
-- =============================================================================

-- Markets table
CREATE TABLE IF NOT EXISTS markets (
    market_id VARCHAR(50) PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    market_type VARCHAR(50) NOT NULL,  -- beach, ski, urban, lake
    state VARCHAR(2) NOT NULL,
    country VARCHAR(2) DEFAULT 'US',
    timezone VARCHAR(50) DEFAULT 'America/New_York',
    seasonality_type VARCHAR(50) DEFAULT 'summer',
    peak_months INTEGER[] DEFAULT '{6,7,8}',
    value_hierarchy TEXT[],  -- Ordered list of value drivers
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Submarkets table
CREATE TABLE IF NOT EXISTS submarkets (
    submarket_id VARCHAR(100) PRIMARY KEY,
    market_id VARCHAR(50) REFERENCES markets(market_id),
    name VARCHAR(200) NOT NULL,
    tier INTEGER NOT NULL,  -- 0=S-tier, 1-4 standard
    
    -- Geography
    polygon_coords JSONB,  -- [[lng, lat], ...]
    centroid_lat DECIMAL(10, 7),
    centroid_lng DECIMAL(10, 7),
    
    -- Characteristics
    primary_value_driver VARCHAR(100),
    rental_restrictions VARCHAR(100),
    
    -- Derived metrics
    avg_adr DECIMAL(10, 2),
    listing_count INTEGER,
    premium_vs_market DECIMAL(5, 4),
    
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_submarkets_market ON submarkets(market_id);
CREATE INDEX IF NOT EXISTS idx_submarkets_tier ON submarkets(tier);

-- External listings table (OTA scrapes)
CREATE TABLE IF NOT EXISTS external_listings (
    id SERIAL PRIMARY KEY,
    listing_id VARCHAR(100) NOT NULL,
    source VARCHAR(50) NOT NULL,  -- airbnb, vrbo, booking
    market_id VARCHAR(50) REFERENCES markets(market_id),
    submarket_id VARCHAR(100) REFERENCES submarkets(submarket_id),
    
    -- Location
    latitude DECIMAL(10, 7) NOT NULL,
    longitude DECIMAL(10, 7) NOT NULL,
    address_approx VARCHAR(500),
    
    -- Property basics
    bedrooms INTEGER,
    bathrooms DECIMAL(3, 1),
    sleeps INTEGER,
    property_type VARCHAR(50),
    
    -- Pricing
    avg_adr DECIMAL(10, 2),
    min_nightly DECIMAL(10, 2),
    max_nightly DECIMAL(10, 2),
    
    -- Amenities
    has_pool BOOLEAN DEFAULT false,
    pool_type VARCHAR(50) DEFAULT 'none',
    pool_heated BOOLEAN DEFAULT false,
    has_hot_tub BOOLEAN DEFAULT false,
    has_view BOOLEAN DEFAULT false,
    view_type VARCHAR(50) DEFAULT 'none',
    beach_distance_ft INTEGER,
    beach_access_type VARCHAR(50) DEFAULT 'none',
    pet_friendly BOOLEAN DEFAULT false,
    parking_type VARCHAR(50) DEFAULT 'none',
    
    -- Quality
    review_score DECIMAL(3, 2),
    review_count INTEGER,
    is_superhost BOOLEAN DEFAULT false,
    year_built INTEGER,
    
    -- Metadata
    listing_url VARCHAR(1000),
    title VARCHAR(500),
    scraped_at TIMESTAMP DEFAULT NOW(),
    last_updated TIMESTAMP DEFAULT NOW(),
    is_active BOOLEAN DEFAULT true,
    
    CONSTRAINT external_listings_unique UNIQUE (source, listing_id)
);

CREATE INDEX IF NOT EXISTS idx_external_listings_market ON external_listings(market_id);
CREATE INDEX IF NOT EXISTS idx_external_listings_submarket ON external_listings(submarket_id);
CREATE INDEX IF NOT EXISTS idx_external_listings_geo ON external_listings(latitude, longitude);
CREATE INDEX IF NOT EXISTS idx_external_listings_beds ON external_listings(bedrooms);
CREATE INDEX IF NOT EXISTS idx_external_listings_pool ON external_listings(has_pool);

-- Amenity attribution cache (per market/submarket)
CREATE TABLE IF NOT EXISTS amenity_attribution (
    id SERIAL PRIMARY KEY,
    market_id VARCHAR(50) REFERENCES markets(market_id),
    submarket_id VARCHAR(100) REFERENCES submarkets(submarket_id),
    amenity VARCHAR(100) NOT NULL,
    
    -- Attribution results
    lift_pct DECIMAL(6, 4),
    lift_dollars DECIMAL(10, 2),
    confidence DECIMAL(4, 3),
    
    -- Sample info
    sample_with INTEGER,
    sample_without INTEGER,
    
    -- Methodology
    controlled_for TEXT[],  -- ['bedrooms', 'submarket']
    data_sources TEXT[],    -- ['internal', 'airbnb', 'vrbo']
    
    calculated_at TIMESTAMP DEFAULT NOW(),
    valid_until TIMESTAMP,
    
    CONSTRAINT amenity_attribution_unique UNIQUE (market_id, submarket_id, amenity)
);

-- Insert 30A market
INSERT INTO markets (market_id, name, market_type, state, timezone, seasonality_type, peak_months, value_hierarchy)
VALUES (
    '30a_fl', 
    '30A Corridor', 
    'beach', 
    'FL', 
    'America/Chicago',
    'summer',
    '{6,7,8}',
    '{"submarket_tier", "beach_distance", "view_type", "pool_type", "bedrooms", "property_quality"}'
)
ON CONFLICT (market_id) DO UPDATE SET
    value_hierarchy = EXCLUDED.value_hierarchy,
    updated_at = NOW();

-- Insert 30A submarkets
INSERT INTO submarkets (submarket_id, market_id, name, tier, primary_value_driver, rental_restrictions)
VALUES 
    ('alys_beach', '30a_fl', 'Alys Beach', 0, 'architecture', '30_day_min'),
    ('rosemary_beach', '30a_fl', 'Rosemary Beach', 1, 'walkability', NULL),
    ('watercolor', '30a_fl', 'WaterColor', 1, 'beach_club', NULL),
    ('seaside', '30a_fl', 'Seaside', 1, 'iconic_location', NULL),
    ('seagrove', '30a_fl', 'Seagrove Beach', 2, 'affordability', NULL),
    ('watersound', '30a_fl', 'WaterSound', 2, 'beach_club', NULL),
    ('seacrest', '30a_fl', 'Seacrest Beach', 2, 'community_pool', NULL),
    ('inlet_beach', '30a_fl', 'Inlet Beach', 3, 'new_development', NULL)
ON CONFLICT (submarket_id) DO UPDATE SET
    tier = EXCLUDED.tier,
    primary_value_driver = EXCLUDED.primary_value_driver,
    updated_at = NOW();

-- Done!
"""


# =============================================================================
# MARKET INTELLIGENCE SERVICE
# =============================================================================

class MarketIntelligenceService:
    """
    Service for market-wide intelligence combining internal and external data.
    """
    
    def __init__(self, database_url: str = None):
        self.database_url = database_url or DATABASE_URL
    
    def _get_connection(self):
        return psycopg2.connect(self.database_url, cursor_factory=RealDictCursor)
    
    def get_market_summary(self, market_id: str) -> Dict[str, Any]:
        """Get summary of a market with submarket breakdown."""
        conn = self._get_connection()
        cur = conn.cursor()
        
        # Get market info
        cur.execute("SELECT * FROM markets WHERE market_id = %s", (market_id,))
        market = cur.fetchone()
        
        if not market:
            return {"error": f"Market {market_id} not found"}
        
        # Get submarkets
        cur.execute("""
            SELECT * FROM submarkets 
            WHERE market_id = %s 
            ORDER BY tier, name
        """, (market_id,))
        submarkets = [dict(r) for r in cur.fetchall()]
        
        # Get external listing counts
        cur.execute("""
            SELECT submarket_id, COUNT(*) as count, AVG(avg_adr) as avg_adr
            FROM external_listings
            WHERE market_id = %s AND is_active = true
            GROUP BY submarket_id
        """, (market_id,))
        listing_stats = {r['submarket_id']: r for r in cur.fetchall()}
        
        cur.close()
        conn.close()
        
        # Enrich submarkets with listing stats
        for sm in submarkets:
            stats = listing_stats.get(sm['submarket_id'], {})
            sm['external_listing_count'] = stats.get('count', 0)
            sm['external_avg_adr'] = float(stats.get('avg_adr', 0)) if stats.get('avg_adr') else None
        
        return {
            "market": dict(market),
            "submarkets": submarkets,
            "total_external_listings": sum(s['external_listing_count'] for s in submarkets),
        }
    
    def calculate_submarket_premiums(self, market_id: str) -> Dict[str, Any]:
        """Calculate ADR premiums for each submarket vs market average."""
        conn = self._get_connection()
        cur = conn.cursor()
        
        # Get market average from external listings
        cur.execute("""
            SELECT AVG(avg_adr) as market_avg
            FROM external_listings
            WHERE market_id = %s AND is_active = true AND avg_adr > 0
        """, (market_id,))
        market_avg = float(cur.fetchone()['market_avg'] or 0)
        
        # Get submarket averages
        cur.execute("""
            SELECT 
                s.submarket_id,
                s.name,
                s.tier,
                COUNT(e.id) as listing_count,
                AVG(e.avg_adr) as avg_adr
            FROM submarkets s
            LEFT JOIN external_listings e ON s.submarket_id = e.submarket_id AND e.is_active = true
            WHERE s.market_id = %s
            GROUP BY s.submarket_id, s.name, s.tier
            ORDER BY s.tier, AVG(e.avg_adr) DESC NULLS LAST
        """, (market_id,))
        submarkets = [dict(r) for r in cur.fetchall()]
        
        cur.close()
        conn.close()
        
        # Calculate premiums
        for sm in submarkets:
            if sm['avg_adr'] and market_avg > 0:
                sm['premium_vs_market'] = round((float(sm['avg_adr']) - market_avg) / market_avg, 4)
                sm['premium_dollars'] = round(float(sm['avg_adr']) - market_avg, 2)
            else:
                sm['premium_vs_market'] = None
                sm['premium_dollars'] = None
        
        return {
            "market_id": market_id,
            "market_avg_adr": round(market_avg, 2),
            "submarkets": submarkets,
        }
    
    def calculate_amenity_lift_market_wide(
        self, 
        market_id: str, 
        amenity: str,
        control_for_submarket: bool = True,
    ) -> Dict[str, Any]:
        """
        Calculate amenity lift using ALL listings in the market.
        
        This is the key function - uses external data to get statistically
        valid amenity attribution.
        """
        conn = self._get_connection()
        cur = conn.cursor()
        
        # Get listings with the amenity flag
        amenity_col = f"has_{amenity}" if not amenity.startswith("has_") else amenity
        
        cur.execute(f"""
            SELECT 
                e.submarket_id,
                e.bedrooms,
                e.{amenity_col} as has_amenity,
                e.avg_adr
            FROM external_listings e
            WHERE e.market_id = %s 
              AND e.is_active = true 
              AND e.avg_adr > 0
              AND e.bedrooms > 0
        """, (market_id,))
        listings = [dict(r) for r in cur.fetchall()]
        
        cur.close()
        conn.close()
        
        if not listings:
            return {"error": "No external listings found for this market"}
        
        # Calculate lift
        if control_for_submarket:
            # Group by submarket and bedrooms, then aggregate
            return self._calculate_controlled_lift(listings, "has_amenity")
        else:
            # Simple with/without comparison
            with_amenity = [l for l in listings if l['has_amenity']]
            without_amenity = [l for l in listings if not l['has_amenity']]
            
            avg_with = sum(float(l['avg_adr']) for l in with_amenity) / len(with_amenity) if with_amenity else 0
            avg_without = sum(float(l['avg_adr']) for l in without_amenity) / len(without_amenity) if without_amenity else 0
            
            return {
                "amenity": amenity,
                "market_id": market_id,
                "controlled": False,
                "sample_with": len(with_amenity),
                "sample_without": len(without_amenity),
                "avg_adr_with": round(avg_with, 2),
                "avg_adr_without": round(avg_without, 2),
                "lift_dollars": round(avg_with - avg_without, 2),
                "lift_pct": round((avg_with - avg_without) / avg_without, 4) if avg_without else 0,
            }
    
    def _calculate_controlled_lift(self, listings: List[Dict], amenity_field: str) -> Dict[str, Any]:
        """Calculate lift controlling for submarket and bedrooms."""
        from collections import defaultdict
        
        # Group by (submarket, bedrooms)
        groups = defaultdict(lambda: {"with": [], "without": []})
        
        for listing in listings:
            key = (listing['submarket_id'], listing['bedrooms'])
            if listing[amenity_field]:
                groups[key]["with"].append(listing)
            else:
                groups[key]["without"].append(listing)
        
        # Calculate weighted lift
        weighted_lift_sum = 0.0
        total_weight = 0
        valid_groups = 0
        
        group_details = []
        
        for (submarket, beds), group in groups.items():
            with_list = group["with"]
            without_list = group["without"]
            
            # Need at least 2 in each group
            if len(with_list) >= 2 and len(without_list) >= 2:
                avg_with = sum(float(l['avg_adr']) for l in with_list) / len(with_list)
                avg_without = sum(float(l['avg_adr']) for l in without_list) / len(without_list)
                lift = (avg_with - avg_without) / avg_without if avg_without else 0
                
                weight = min(len(with_list), len(without_list))
                weighted_lift_sum += lift * weight
                total_weight += weight
                valid_groups += 1
                
                group_details.append({
                    "submarket": submarket,
                    "bedrooms": beds,
                    "sample_with": len(with_list),
                    "sample_without": len(without_list),
                    "lift_pct": round(lift, 4),
                })
        
        avg_lift = weighted_lift_sum / total_weight if total_weight > 0 else 0
        
        return {
            "controlled": True,
            "controlled_for": ["submarket", "bedrooms"],
            "valid_comparison_groups": valid_groups,
            "total_weight": total_weight,
            "weighted_avg_lift_pct": round(avg_lift, 4),
            "confidence": min(0.95, 0.3 + (valid_groups / 20) * 0.65),
            "group_details": sorted(group_details, key=lambda x: x['lift_pct'], reverse=True)[:10],
        }


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def setup_market_intelligence_schema():
    """Run the schema migration."""
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    
    sql = generate_market_intelligence_schema()
    cur.execute(sql)
    
    conn.commit()
    cur.close()
    conn.close()
    
    return {"status": "success", "message": "Market intelligence schema created"}
