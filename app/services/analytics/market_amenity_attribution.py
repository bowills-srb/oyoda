"""
Market-Wide Amenity Attribution Engine

PROBLEM WITH INTERNAL-ONLY DATA:
- Portfolio is self-selecting (mostly premium properties with pools)
- Can't isolate amenity effects without comparison group
- Small sample sizes make statistics unreliable

SOLUTION: Combine internal data with external market scrapes

DATA SOURCES:
1. Internal Portfolio (high confidence, verified ADR)
   - properties, property_pricing, property_bookings
   
2. External Market Data (broader coverage, estimated ADR)
   - OTA scrapers (Airbnb, VRBO listings in the area)
   - MLS data (for new listings)
   - Competitor analysis

KEY AMENITY FACTORS TO TRACK:

┌─────────────────────────────────────────────────────────────────────────────┐
│ CATEGORY          │ ATTRIBUTES                │ EXPECTED IMPACT             │
├───────────────────┼───────────────────────────┼─────────────────────────────┤
│ Pool              │ private vs shared         │ Private >> Shared >> None   │
│                   │ heated vs unheated        │ Heated adds winter value    │
│                   │ size/type                 │ Infinity edge premium       │
├───────────────────┼───────────────────────────┼─────────────────────────────┤
│ Location          │ distance_to_beach_ft      │ Continuous: closer = higher │
│                   │ beach_access_type         │ Private > Deeded > Public   │
│                   │ view_type                 │ Gulf > Partial > None       │
│                   │ floor_level (condos)      │ Higher = better view        │
├───────────────────┼───────────────────────────┼─────────────────────────────┤
│ Property Quality  │ year_built                │ Newer = premium             │
│                   │ last_renovated            │ Recent reno = premium       │
│                   │ interior_quality          │ Luxury > Standard           │
│                   │ brand/designer            │ Known designers = premium   │
├───────────────────┼───────────────────────────┼─────────────────────────────┤
│ Convenience       │ parking_type              │ Garage > Driveway > Street  │
│                   │ ev_charger                │ Growing importance          │
│                   │ pet_friendly              │ Market-dependent            │
│                   │ elevator                  │ Accessibility premium       │
├───────────────────┼───────────────────────────┼─────────────────────────────┤
│ Entertainment     │ hot_tub                   │ Seasonal value              │
│                   │ game_room                 │ Family appeal               │
│                   │ home_theater              │ Luxury segment              │
│                   │ outdoor_kitchen           │ Premium amenity             │
└─────────────────────────────────────────────────────────────────────────────┘

METHODOLOGY: Hedonic Pricing Model

ADR = β₀ + β₁(bedrooms) + β₂(bathrooms) + β₃(sleeps) 
    + β₄(distance_to_beach) + β₅(has_private_pool) + β₆(has_gulf_view)
    + β₇(year_built) + β₈(is_renovated) + ...
    + ε

Each β coefficient represents the MARGINAL VALUE of that attribute,
controlling for all other factors.

IMPLEMENTATION PHASES:

Phase 1: Schema Enhancement (Current)
- Add missing columns to properties table
- Enrich existing properties with location data

Phase 2: External Data Integration
- OTA scraper for competitor listings
- Geocoding for distance calculations
- View analysis from photos/descriptions

Phase 3: Statistical Model
- Hedonic regression on combined dataset
- Confidence intervals on each coefficient
- Market-specific models (30A vs other markets)

Phase 4: BD Integration
- Real-time amenity valuation for projections
- "This property's pool adds $X/night based on 150 comps"
- Voice-ready confidence statements
"""

import os
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, List, Optional, Any, Tuple
from enum import Enum

import psycopg2
from psycopg2.extras import RealDictCursor

from app.core.db_connect import resolve_runtime_sync_database_url

DATABASE_URL = resolve_runtime_sync_database_url(os.getenv("DATABASE_URL"))


# =============================================================================
# ENHANCED PROPERTY ATTRIBUTES
# =============================================================================

class PoolType(str, Enum):
    """Pool classification."""
    PRIVATE = "private"           # Dedicated to property
    SHARED_SMALL = "shared_small" # Community pool, <20 units
    SHARED_LARGE = "shared_large" # Resort pool, 20+ units
    NONE = "none"


class ViewType(str, Enum):
    """View classification for coastal properties."""
    GULF_FRONT = "gulf_front"     # Direct gulf view
    GULF_VIEW = "gulf_view"       # Partial/angled gulf view  
    LAKE_VIEW = "lake_view"       # Coastal dune lake
    POOL_VIEW = "pool_view"       # Overlooks pool area
    NATURE_VIEW = "nature_view"   # Trees, preserve
    NO_VIEW = "no_view"           # Interior/parking view


class BeachAccessType(str, Enum):
    """Beach access classification."""
    PRIVATE = "private"           # Private beach, deeded
    DEEDED = "deeded"             # Deeded access point
    COMMUNITY = "community"       # Community walkover
    PUBLIC_ADJACENT = "public_adjacent"  # Public beach nearby
    NONE = "none"


@dataclass
class EnhancedPropertyAttributes:
    """
    Enhanced attributes for accurate amenity attribution.
    
    These should be added to the properties table or a related table.
    """
    property_code: str
    
    # Pool details
    pool_type: PoolType = PoolType.NONE
    pool_heated: bool = False
    pool_size_sqft: Optional[int] = None
    
    # Location details
    distance_to_beach_ft: Optional[int] = None  # Walking distance
    beach_access_type: BeachAccessType = BeachAccessType.NONE
    view_type: ViewType = ViewType.NO_VIEW
    floor_level: Optional[int] = None  # For condos
    
    # Property quality
    year_built: Optional[int] = None
    year_renovated: Optional[int] = None
    interior_quality: str = "standard"  # luxury, upscale, standard, budget
    
    # Geo coordinates (for distance calculations)
    latitude: Optional[float] = None
    longitude: Optional[float] = None


# =============================================================================
# EXTERNAL LISTING MODEL
# =============================================================================

@dataclass
class ExternalListing:
    """
    A listing from external sources (OTA scrape, MLS).
    
    Used for market-wide amenity attribution.
    """
    listing_id: str
    source: str  # airbnb, vrbo, mls
    
    # Basic info
    bedrooms: int
    bathrooms: float
    sleeps: int
    
    # Pricing
    avg_adr: float
    adr_source: str  # scraped, estimated, listed
    
    # Location
    latitude: float
    longitude: float
    distance_to_beach_ft: Optional[int] = None
    community: Optional[str] = None
    
    # Amenities (normalized)
    has_pool: bool = False
    pool_type: PoolType = PoolType.NONE
    pool_heated: bool = False
    
    has_hot_tub: bool = False
    has_gulf_view: bool = False
    has_beach_access: bool = False
    beach_access_type: BeachAccessType = BeachAccessType.NONE
    
    pet_friendly: bool = False
    has_elevator: bool = False
    has_ev_charger: bool = False
    
    # Quality indicators
    year_built: Optional[int] = None
    review_score: Optional[float] = None
    review_count: Optional[int] = None
    
    # Timestamps
    scraped_at: datetime = field(default_factory=datetime.utcnow)
    listing_url: Optional[str] = None


# =============================================================================
# SCHEMA MIGRATION
# =============================================================================

def generate_enhanced_schema_migration() -> str:
    """
    Generate SQL to add enhanced attributes for amenity attribution.
    """
    return """
-- Migration: Enhanced property attributes for amenity attribution
-- This enables proper hedonic pricing analysis

-- 1. Add location columns to properties
ALTER TABLE properties ADD COLUMN IF NOT EXISTS latitude DECIMAL(10, 7);
ALTER TABLE properties ADD COLUMN IF NOT EXISTS longitude DECIMAL(10, 7);
ALTER TABLE properties ADD COLUMN IF NOT EXISTS distance_to_beach_ft INTEGER;
ALTER TABLE properties ADD COLUMN IF NOT EXISTS beach_access_type VARCHAR(50) DEFAULT 'community';
ALTER TABLE properties ADD COLUMN IF NOT EXISTS view_type VARCHAR(50) DEFAULT 'no_view';
ALTER TABLE properties ADD COLUMN IF NOT EXISTS floor_level INTEGER;

-- 2. Enhance pool information
ALTER TABLE properties ADD COLUMN IF NOT EXISTS pool_type VARCHAR(50) DEFAULT 'none';
-- Update existing: if has_pool = true, set pool_type = 'private'
UPDATE properties SET pool_type = 'private' WHERE has_pool = true AND pool_type = 'none';

-- 3. Add quality indicators
ALTER TABLE properties ADD COLUMN IF NOT EXISTS year_built INTEGER;
ALTER TABLE properties ADD COLUMN IF NOT EXISTS year_renovated INTEGER;
ALTER TABLE properties ADD COLUMN IF NOT EXISTS interior_quality VARCHAR(50) DEFAULT 'standard';

-- 4. Create external listings table for market comps
CREATE TABLE IF NOT EXISTS external_listings (
    id SERIAL PRIMARY KEY,
    listing_id VARCHAR(100) UNIQUE NOT NULL,
    source VARCHAR(50) NOT NULL,  -- airbnb, vrbo, mls
    
    -- Basic info
    bedrooms INTEGER NOT NULL,
    bathrooms DECIMAL(3,1),
    sleeps INTEGER,
    property_type VARCHAR(50),
    
    -- Location
    latitude DECIMAL(10, 7),
    longitude DECIMAL(10, 7),
    address_approx VARCHAR(500),
    community VARCHAR(100),
    distance_to_beach_ft INTEGER,
    
    -- Pricing
    avg_adr DECIMAL(10, 2),
    min_adr DECIMAL(10, 2),
    max_adr DECIMAL(10, 2),
    adr_source VARCHAR(50),  -- scraped, calculated
    
    -- Amenities
    has_pool BOOLEAN DEFAULT false,
    pool_type VARCHAR(50) DEFAULT 'none',
    pool_heated BOOLEAN DEFAULT false,
    has_hot_tub BOOLEAN DEFAULT false,
    has_gulf_view BOOLEAN DEFAULT false,
    view_type VARCHAR(50),
    has_beach_access BOOLEAN DEFAULT false,
    beach_access_type VARCHAR(50),
    pet_friendly BOOLEAN DEFAULT false,
    
    -- Quality
    year_built INTEGER,
    review_score DECIMAL(3, 2),
    review_count INTEGER,
    
    -- Metadata
    listing_url VARCHAR(1000),
    scraped_at TIMESTAMP DEFAULT NOW(),
    last_updated TIMESTAMP DEFAULT NOW(),
    is_active BOOLEAN DEFAULT true,
    
    -- Indexes
    CONSTRAINT external_listings_source_id UNIQUE (source, listing_id)
);

CREATE INDEX IF NOT EXISTS idx_external_listings_geo 
ON external_listings(latitude, longitude);

CREATE INDEX IF NOT EXISTS idx_external_listings_bedrooms 
ON external_listings(bedrooms);

CREATE INDEX IF NOT EXISTS idx_external_listings_community 
ON external_listings(community);

-- 5. Create amenity attribution results table (cache)
CREATE TABLE IF NOT EXISTS amenity_attribution_cache (
    id SERIAL PRIMARY KEY,
    market_id VARCHAR(100) NOT NULL,
    amenity VARCHAR(100) NOT NULL,
    
    -- Attribution results
    lift_pct DECIMAL(6, 4),
    lift_dollars DECIMAL(10, 2),
    confidence DECIMAL(4, 3),
    
    -- Sample info
    sample_with INTEGER,
    sample_without INTEGER,
    
    -- Methodology
    model_type VARCHAR(50),  -- simple_comparison, hedonic_regression
    controlled_for TEXT[],   -- ['bedrooms', 'distance_to_beach']
    
    -- Timestamps
    calculated_at TIMESTAMP DEFAULT NOW(),
    valid_until TIMESTAMP,
    
    CONSTRAINT amenity_attribution_market_amenity UNIQUE (market_id, amenity)
);

-- Done!
-- Next steps:
-- 1. Run property enrichment scraper to populate lat/lng
-- 2. Run OTA scraper to populate external_listings
-- 3. Run amenity attribution with combined dataset
"""


# =============================================================================
# HEDONIC PRICING MODEL (Future Implementation)
# =============================================================================

class HedonicPricingModel:
    """
    Hedonic regression model for amenity attribution.
    
    This will be implemented when we have sufficient external data.
    Uses statsmodels or scikit-learn for regression.
    """
    
    def __init__(self):
        self.coefficients: Dict[str, float] = {}
        self.confidence_intervals: Dict[str, Tuple[float, float]] = {}
        self.r_squared: float = 0.0
        self.sample_size: int = 0
    
    def fit(self, listings: List[Dict]) -> None:
        """
        Fit hedonic model to listing data.
        
        ADR = β₀ + Σ(βᵢ × Xᵢ) + ε
        
        Where Xᵢ are property attributes.
        """
        # TODO: Implement with statsmodels
        # import statsmodels.api as sm
        # 
        # X = prepare_features(listings)
        # y = [l['avg_adr'] for l in listings]
        # 
        # model = sm.OLS(y, sm.add_constant(X))
        # results = model.fit()
        # 
        # self.coefficients = dict(zip(feature_names, results.params))
        # self.confidence_intervals = results.conf_int()
        # self.r_squared = results.rsquared
        pass
    
    def get_amenity_value(self, amenity: str) -> Tuple[float, float, float]:
        """
        Get the marginal value of an amenity.
        
        Returns (value, ci_low, ci_high)
        """
        value = self.coefficients.get(amenity, 0)
        ci = self.confidence_intervals.get(amenity, (0, 0))
        return value, ci[0], ci[1]
    
    def predict_adr(self, attributes: Dict) -> float:
        """
        Predict ADR for a property based on its attributes.
        """
        adr = self.coefficients.get('intercept', 0)
        for attr, value in attributes.items():
            if attr in self.coefficients:
                adr += self.coefficients[attr] * value
        return adr


# =============================================================================
# NEAR-TERM: PAIRED COMPARISON ANALYSIS
# =============================================================================

class PairedComparisonAnalyzer:
    """
    Find similar properties that differ only in one amenity.
    
    This is the most defensible approach with limited data:
    - Find pairs of properties that are similar (same beds, nearby)
    - One has the amenity, one doesn't
    - Compare their ADRs
    
    Example: "48 Seawalk (no pool, $2,536) vs 42 Flatwood (pool, $2,351)"
    These are both 2BR in similar areas - the difference might be 
    other factors (view, location), not pool.
    """
    
    def __init__(self, database_url: str = None):
        self.database_url = database_url or DATABASE_URL
    
    def find_comparable_pairs(
        self,
        amenity: str,
        max_distance_miles: float = 1.0,
        same_bedrooms: bool = True,
    ) -> List[Dict]:
        """
        Find pairs of properties that are comparable except for one amenity.
        """
        conn = psycopg2.connect(self.database_url, cursor_factory=RealDictCursor)
        cur = conn.cursor()
        
        # Get all properties with pricing
        cur.execute("""
            SELECT 
                p.property_code,
                p.bedrooms,
                p.bathrooms,
                p.community,
                p.has_pool,
                p.has_hot_tub,
                p.has_grill,
                p.latitude,
                p.longitude,
                AVG(pr.adr) as avg_adr
            FROM properties p
            JOIN property_pricing pr ON p.property_code = pr.property_code
            WHERE pr.adr > 0 AND p.bedrooms > 0
            GROUP BY p.property_code, p.bedrooms, p.bathrooms, p.community,
                     p.has_pool, p.has_hot_tub, p.has_grill, p.latitude, p.longitude
        """)
        properties = list(cur.fetchall())
        
        cur.close()
        conn.close()
        
        # Find pairs
        pairs = []
        amenity_col = amenity if amenity.startswith('has_') else f'has_{amenity}'
        
        for i, p1 in enumerate(properties):
            for p2 in properties[i+1:]:
                # Must differ on the amenity
                if p1.get(amenity_col) == p2.get(amenity_col):
                    continue
                
                # Check bedroom match
                if same_bedrooms and p1['bedrooms'] != p2['bedrooms']:
                    continue
                
                # Check same community (proxy for location)
                if p1['community'] != p2['community']:
                    continue
                
                # Identify which has the amenity
                if p1.get(amenity_col):
                    with_amenity = p1
                    without_amenity = p2
                else:
                    with_amenity = p2
                    without_amenity = p1
                
                pairs.append({
                    "with_amenity": {
                        "code": with_amenity['property_code'],
                        "bedrooms": with_amenity['bedrooms'],
                        "community": with_amenity['community'],
                        "adr": float(with_amenity['avg_adr']),
                    },
                    "without_amenity": {
                        "code": without_amenity['property_code'],
                        "bedrooms": without_amenity['bedrooms'],
                        "community": without_amenity['community'],
                        "adr": float(without_amenity['avg_adr']),
                    },
                    "adr_difference": float(with_amenity['avg_adr']) - float(without_amenity['avg_adr']),
                    "pct_difference": (float(with_amenity['avg_adr']) - float(without_amenity['avg_adr'])) / float(without_amenity['avg_adr']) if without_amenity['avg_adr'] > 0 else 0,
                })
        
        return pairs
    
    def get_paired_attribution(self, amenity: str) -> Dict[str, Any]:
        """
        Get amenity attribution based on paired comparisons.
        """
        pairs = self.find_comparable_pairs(amenity)
        
        if not pairs:
            return {
                "amenity": amenity,
                "pair_count": 0,
                "avg_lift_dollars": None,
                "avg_lift_pct": None,
                "confidence": 0,
                "pairs": [],
                "insight": f"No comparable pairs found for {amenity}",
            }
        
        avg_lift_dollars = sum(p['adr_difference'] for p in pairs) / len(pairs)
        avg_lift_pct = sum(p['pct_difference'] for p in pairs) / len(pairs)
        
        # Confidence based on pair count and consistency
        confidence = min(0.9, 0.3 + (len(pairs) / 10) * 0.6)
        
        # Check consistency (all pairs should show same direction)
        positive_count = sum(1 for p in pairs if p['adr_difference'] > 0)
        if positive_count == len(pairs) or positive_count == 0:
            confidence *= 1.2  # More confident if consistent
        
        confidence = min(0.95, confidence)
        
        return {
            "amenity": amenity,
            "pair_count": len(pairs),
            "avg_lift_dollars": round(avg_lift_dollars, 2),
            "avg_lift_pct": round(avg_lift_pct, 4),
            "confidence": round(confidence, 3),
            "pairs": pairs,
            "insight": f"Based on {len(pairs)} comparable pairs, {amenity} {'adds' if avg_lift_dollars > 0 else 'reduces'} ${abs(avg_lift_dollars):.0f}/night ({avg_lift_pct:.1%})",
        }


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def get_paired_amenity_attribution(amenity: str = "pool") -> Dict[str, Any]:
    """Get amenity attribution using paired comparison."""
    analyzer = PairedComparisonAnalyzer()
    return analyzer.get_paired_attribution(amenity)


def print_schema_migration():
    """Print the schema migration SQL."""
    print(generate_enhanced_schema_migration())
