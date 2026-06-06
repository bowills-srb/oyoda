"""
Multi-Tenant Data Architecture for Beach Habitats

This module provides tenant-scoped data access for the BD engine.
All scraped data is partitioned by operator_id to support multiple
property management companies using the same platform.

ARCHITECTURE:
┌─────────────────────────────────────────────────────────────────┐
│                      Beach Habitats Platform                     │
├─────────────────────────────────────────────────────────────────┤
│  Operator A (Beach Habitats 30A)                                │
│    └── properties, bookings, pricing, availability              │
├─────────────────────────────────────────────────────────────────┤
│  Operator B (Coastal Rentals LLC)                               │
│    └── properties, bookings, pricing, availability              │
├─────────────────────────────────────────────────────────────────┤
│  Operator C (Gulf Views PM)                                     │
│    └── properties, bookings, pricing, availability              │
└─────────────────────────────────────────────────────────────────┘

IMPLEMENTATION:
1. Add operator_id column to all data tables
2. All queries filter by operator_id
3. API endpoints receive operator_id from auth context
4. Scrapers tag data with operator_id at ingestion

MIGRATION PATH:
- Phase 1: Add operator_id column with default 'beach_habitats_30a'
- Phase 2: Update all queries to filter by operator_id
- Phase 3: Add operator onboarding flow
- Phase 4: Implement PMS connectors per operator
"""

import os
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

import psycopg2
from psycopg2.extras import RealDictCursor

from app.core.db_connect import resolve_runtime_sync_database_url

DATABASE_URL = resolve_runtime_sync_database_url(os.getenv("DATABASE_URL"))

# Default operator for backward compatibility
DEFAULT_OPERATOR_ID = "beach_habitats_30a"


# =============================================================================
# OPERATOR MODEL
# =============================================================================

@dataclass
class Operator:
    """An STR operator/property management company."""
    operator_id: str
    name: str
    market_id: str  # Primary market (e.g., "30a_fl")
    
    # Contact
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    
    # Settings
    commission_rate: float = 0.20
    timezone: str = "America/Chicago"
    
    # Scraping config
    website_url: Optional[str] = None
    pms_provider: Optional[str] = None  # guesty, hostaway, etc.
    
    # Status
    is_active: bool = True
    onboarded_at: Optional[datetime] = None


# =============================================================================
# TENANT-SCOPED DATA CLASSES
# =============================================================================

@dataclass
class TenantPortfolioMetrics:
    """Portfolio metrics for a specific operator."""
    operator_id: str
    property_count: int
    total_bookings: int
    total_booked_nights: int
    avg_adr: float
    min_adr: float
    max_adr: float
    avg_stay_length: float
    avg_occupancy: float
    
    adr_by_bedrooms: Dict[int, float]
    occupancy_by_bedrooms: Dict[int, float]
    property_count_by_bedrooms: Dict[int, int]
    
    pct_with_pool: float
    pct_with_hot_tub: float
    pct_waterfront: float
    
    top_revenue_properties: List[Dict[str, Any]]


@dataclass
class TenantMarketSignals:
    """Market signals for a specific operator's portfolio."""
    operator_id: str
    market_id: str
    
    total_properties: int
    properties_with_availability: int
    
    avg_occupancy_next_30: float
    avg_occupancy_next_90: float
    
    avg_adr: float
    adr_trend_30d: float
    
    current_season: str
    seasonal_factor: float


# =============================================================================
# TENANT-SCOPED DATA ACCESS
# =============================================================================

def get_operator(operator_id: str) -> Optional[Operator]:
    """
    Get operator by ID.
    
    In production, this would query an operators table.
    For now, returns hardcoded Beach Habitats.
    """
    if operator_id == DEFAULT_OPERATOR_ID:
        return Operator(
            operator_id=DEFAULT_OPERATOR_ID,
            name="Beach Habitats 30A",
            market_id="30a_fl",
            contact_email="info@beachhabitats30a.com",
            website_url="https://www.beachhabitats30a.com",
            commission_rate=0.20,
            is_active=True,
            onboarded_at=datetime(2024, 1, 1),
        )
    return None


def get_tenant_portfolio_metrics(operator_id: str) -> Optional[TenantPortfolioMetrics]:
    """
    Get portfolio metrics for a specific operator.
    
    This is the tenant-scoped version of get_portfolio_metrics().
    All queries filter by operator_id.
    """
    try:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
        cur = conn.cursor()
        
        # NOTE: Currently the schema doesn't have operator_id
        # When you add it, uncomment the WHERE clauses
        
        # Overall portfolio stats
        cur.execute("""
            SELECT 
                COUNT(DISTINCT p.property_code) as property_count,
                COUNT(b.id) as total_bookings,
                COALESCE(SUM(b.nights), 0) as total_booked_nights,
                COALESCE(AVG(b.nights), 0) as avg_stay_length
            FROM properties p
            LEFT JOIN property_bookings b ON p.property_code = b.property_code
            WHERE b.nights > 0 AND b.nights <= 30
            -- AND p.operator_id = %s  -- Uncomment after migration
        """)  # Add (operator_id,) as param after migration
        overall = cur.fetchone()
        
        # ADR stats
        cur.execute("""
            SELECT 
                COALESCE(AVG(adr), 0) as avg_adr,
                COALESCE(MIN(adr), 0) as min_adr,
                COALESCE(MAX(adr), 0) as max_adr
            FROM property_pricing
            WHERE adr > 0
            -- AND operator_id = %s  -- Uncomment after migration
        """)
        adr_stats = cur.fetchone()
        
        # By bedroom count
        cur.execute("""
            SELECT 
                p.bedrooms,
                COUNT(DISTINCT p.property_code) as property_count,
                COALESCE(AVG(pr.adr), 0) as avg_adr,
                COALESCE(SUM(b.nights)::float / NULLIF(COUNT(DISTINCT p.property_code) * 365, 0), 0) as occupancy
            FROM properties p
            LEFT JOIN property_pricing pr ON p.property_code = pr.property_code
            LEFT JOIN property_bookings b ON p.property_code = b.property_code 
                AND b.nights > 0 AND b.nights <= 30
            WHERE p.bedrooms > 0
            -- AND p.operator_id = %s  -- Uncomment after migration
            GROUP BY p.bedrooms
            ORDER BY p.bedrooms
        """)
        by_bedrooms = cur.fetchall()
        
        adr_by_bedrooms = {}
        occupancy_by_bedrooms = {}
        property_count_by_bedrooms = {}
        for row in by_bedrooms:
            beds = row['bedrooms']
            adr_by_bedrooms[beds] = float(row['avg_adr'] or 0)
            occupancy_by_bedrooms[beds] = float(row['occupancy'] or 0)
            property_count_by_bedrooms[beds] = row['property_count']
        
        # Amenity breakdown
        cur.execute("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN has_pool THEN 1 ELSE 0 END) as with_pool,
                SUM(CASE WHEN has_hot_tub THEN 1 ELSE 0 END) as with_hot_tub,
                SUM(CASE WHEN community ILIKE '%%water%%' OR community ILIKE '%%beach%%' THEN 1 ELSE 0 END) as waterfront
            FROM properties
            -- WHERE operator_id = %s  -- Uncomment after migration
        """)
        amenities = cur.fetchone()
        total = amenities['total'] or 1
        
        # Top revenue properties
        cur.execute("""
            SELECT 
                b.property_code,
                p.address_street,
                p.bedrooms,
                SUM(b.nights) as booked_nights,
                AVG(pr.adr) as avg_adr,
                SUM(b.nights) * AVG(pr.adr) as est_revenue
            FROM property_bookings b
            JOIN properties p ON b.property_code = p.property_code
            LEFT JOIN property_pricing pr ON b.property_code = pr.property_code
            WHERE b.nights > 0 AND b.nights <= 30 AND pr.adr > 0
            -- AND p.operator_id = %s  -- Uncomment after migration
            GROUP BY b.property_code, p.address_street, p.bedrooms
            ORDER BY est_revenue DESC
            LIMIT 10
        """)
        top_properties = [dict(row) for row in cur.fetchall()]
        
        cur.close()
        conn.close()
        
        # Calculate overall occupancy
        property_count = overall['property_count'] or 1
        total_available_nights = property_count * 365
        avg_occupancy = (overall['total_booked_nights'] or 0) / total_available_nights if total_available_nights > 0 else 0
        
        return TenantPortfolioMetrics(
            operator_id=operator_id,
            property_count=overall['property_count'] or 0,
            total_bookings=overall['total_bookings'] or 0,
            total_booked_nights=overall['total_booked_nights'] or 0,
            avg_adr=float(adr_stats['avg_adr'] or 0),
            min_adr=float(adr_stats['min_adr'] or 0),
            max_adr=float(adr_stats['max_adr'] or 0),
            avg_stay_length=float(overall['avg_stay_length'] or 0),
            avg_occupancy=avg_occupancy,
            adr_by_bedrooms=adr_by_bedrooms,
            occupancy_by_bedrooms=occupancy_by_bedrooms,
            property_count_by_bedrooms=property_count_by_bedrooms,
            pct_with_pool=(amenities['with_pool'] or 0) / total,
            pct_with_hot_tub=(amenities['with_hot_tub'] or 0) / total,
            pct_waterfront=(amenities['waterfront'] or 0) / total,
            top_revenue_properties=top_properties,
        )
        
    except Exception as e:
        print(f"Error loading tenant portfolio metrics: {e}")
        import traceback
        traceback.print_exc()
        return None


def get_tenant_market_signals(operator_id: str) -> Optional[TenantMarketSignals]:
    """
    Get market signals for a specific operator.
    """
    try:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
        cur = conn.cursor()
        
        today = date.today()
        next_30 = today + timedelta(days=30)
        next_90 = today + timedelta(days=90)
        
        # Get operator's market
        operator = get_operator(operator_id)
        market_id = operator.market_id if operator else "unknown"
        
        # Supply signals
        cur.execute("""
            SELECT COUNT(*) as cnt FROM properties
            -- WHERE operator_id = %s
        """)
        total_properties = cur.fetchone()['cnt']
        
        cur.execute("""
            SELECT COUNT(DISTINCT property_code) as cnt 
            FROM property_availability 
            WHERE date >= %s AND date <= %s
        """, (today, next_30))
        properties_with_avail = cur.fetchone()['cnt']
        
        # Demand signals
        cur.execute("""
            SELECT 
                COALESCE(SUM(CASE WHEN available = false THEN 1 ELSE 0 END)::float / 
                NULLIF(COUNT(*), 0), 0) as occupancy
            FROM property_availability
            WHERE date >= %s AND date <= %s
        """, (today, next_30))
        occ_30 = cur.fetchone()['occupancy'] or 0
        
        cur.execute("""
            SELECT 
                COALESCE(SUM(CASE WHEN available = false THEN 1 ELSE 0 END)::float / 
                NULLIF(COUNT(*), 0), 0) as occupancy
            FROM property_availability
            WHERE date >= %s AND date <= %s
        """, (today, next_90))
        occ_90 = cur.fetchone()['occupancy'] or 0
        
        # Pricing
        cur.execute("""
            SELECT COALESCE(AVG(adr), 0) as avg_adr 
            FROM property_pricing 
            WHERE adr > 0
        """)
        avg_adr = float(cur.fetchone()['avg_adr'] or 0)
        
        cur.close()
        conn.close()
        
        # Determine season
        month = today.month
        if month in [6, 7, 8]:
            season = "peak"
            seasonal_factor = 1.3
        elif month in [3, 4, 5, 9, 10]:
            season = "shoulder"
            seasonal_factor = 1.0
        else:
            season = "off"
            seasonal_factor = 0.7
        
        return TenantMarketSignals(
            operator_id=operator_id,
            market_id=market_id,
            total_properties=total_properties,
            properties_with_availability=properties_with_avail,
            avg_occupancy_next_30=occ_30,
            avg_occupancy_next_90=occ_90,
            avg_adr=avg_adr,
            adr_trend_30d=0,
            current_season=season,
            seasonal_factor=seasonal_factor,
        )
        
    except Exception as e:
        print(f"Error loading tenant market signals: {e}")
        import traceback
        traceback.print_exc()
        return None


def get_tenant_comparable_properties(
    operator_id: str,
    bedrooms: int,
    has_pool: bool = False,
    community: str = None,
    limit: int = 10
) -> List[Dict[str, Any]]:
    """
    Get comparable properties for a specific operator.
    """
    try:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
        cur = conn.cursor()
        
        conditions = ["p.bedrooms = %s"]
        params = [bedrooms]
        
        if has_pool:
            conditions.append("p.has_pool = true")
        
        if community:
            conditions.append("p.community ILIKE %s")
            params.append(f"%{community}%")
        
        # Add operator filter after migration
        # conditions.append("p.operator_id = %s")
        # params.append(operator_id)
        
        where_clause = " AND ".join(conditions)
        
        cur.execute(f"""
            SELECT 
                p.property_code,
                p.address_street as address,
                p.bedrooms,
                p.bathrooms,
                p.community,
                p.has_pool,
                COALESCE(AVG(pr.adr), 0) as actual_adr,
                COALESCE(SUM(b.nights)::float / 365, 0) as actual_occupancy,
                COALESCE(SUM(b.nights) * AVG(pr.adr), 0) as actual_revenue
            FROM properties p
            LEFT JOIN property_pricing pr ON p.property_code = pr.property_code
            LEFT JOIN property_bookings b ON p.property_code = b.property_code
                AND b.nights > 0 AND b.nights <= 30
            WHERE {where_clause}
            GROUP BY p.property_code, p.address_street, p.bedrooms, 
                     p.bathrooms, p.community, p.has_pool
            HAVING AVG(pr.adr) > 0
            ORDER BY actual_revenue DESC NULLS LAST
            LIMIT %s
        """, params + [limit])
        
        comps = []
        for row in cur.fetchall():
            comps.append({
                "property_code": row['property_code'],
                "address": row['address'],
                "bedrooms": row['bedrooms'],
                "bathrooms": float(row['bathrooms'] or 0),
                "community": row['community'],
                "has_pool": row['has_pool'],
                "actual_adr": float(row['actual_adr'] or 0),
                "actual_occupancy": float(row['actual_occupancy'] or 0),
                "actual_revenue": float(row['actual_revenue'] or 0),
                "similarity_score": 0.9 if row['has_pool'] == has_pool else 0.75,
            })
        
        cur.close()
        conn.close()
        
        return comps
        
    except Exception as e:
        print(f"Error loading tenant comps: {e}")
        return []


def get_tenant_bd_context(operator_id: str) -> Dict[str, Any]:
    """
    Get complete BD context for a specific operator.
    """
    metrics = get_tenant_portfolio_metrics(operator_id)
    signals = get_tenant_market_signals(operator_id)
    operator = get_operator(operator_id)
    
    return {
        "operator": {
            "operator_id": operator_id,
            "name": operator.name if operator else "Unknown",
            "market_id": operator.market_id if operator else "unknown",
        },
        "portfolio": {
            "property_count": metrics.property_count if metrics else 0,
            "avg_adr": round(metrics.avg_adr, 2) if metrics else 0,
            "avg_occupancy": round(metrics.avg_occupancy, 3) if metrics else 0,
            "adr_by_bedrooms": {k: round(v, 2) for k, v in (metrics.adr_by_bedrooms if metrics else {}).items()},
            "top_properties": (metrics.top_revenue_properties[:5] if metrics else []),
        },
        "market_signals": {
            "total_supply": signals.total_properties if signals else 0,
            "occupancy_next_30": round(signals.avg_occupancy_next_30, 3) if signals else 0,
            "avg_adr": round(signals.avg_adr, 2) if signals else 0,
            "season": signals.current_season if signals else "unknown",
            "seasonal_factor": signals.seasonal_factor if signals else 1.0,
        },
    }


# =============================================================================
# MIGRATION HELPERS
# =============================================================================

def generate_add_operator_id_migration() -> str:
    """
    Generate SQL migration to add operator_id to all tables.
    
    Run this when ready to support multiple operators.
    """
    return """
-- Migration: Add operator_id for multi-tenant support
-- Run with: psql $DATABASE_URL -f migration.sql

-- 1. Create operators table
CREATE TABLE IF NOT EXISTS operators (
    operator_id VARCHAR(50) PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    market_id VARCHAR(50) NOT NULL,
    contact_email VARCHAR(200),
    contact_phone VARCHAR(50),
    commission_rate DECIMAL(5,4) DEFAULT 0.20,
    timezone VARCHAR(50) DEFAULT 'America/Chicago',
    website_url VARCHAR(500),
    pms_provider VARCHAR(50),
    is_active BOOLEAN DEFAULT true,
    onboarded_at TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 2. Insert default operator (Beach Habitats)
INSERT INTO operators (operator_id, name, market_id, website_url)
VALUES ('beach_habitats_30a', 'Beach Habitats 30A', '30a_fl', 'https://www.beachhabitats30a.com')
ON CONFLICT (operator_id) DO NOTHING;

-- 3. Add operator_id to properties
ALTER TABLE properties 
ADD COLUMN IF NOT EXISTS operator_id VARCHAR(50) DEFAULT 'beach_habitats_30a';

CREATE INDEX IF NOT EXISTS idx_properties_operator 
ON properties(operator_id);

-- 4. Add operator_id to property_bookings
ALTER TABLE property_bookings 
ADD COLUMN IF NOT EXISTS operator_id VARCHAR(50) DEFAULT 'beach_habitats_30a';

CREATE INDEX IF NOT EXISTS idx_bookings_operator 
ON property_bookings(operator_id);

-- 5. Add operator_id to property_pricing
ALTER TABLE property_pricing 
ADD COLUMN IF NOT EXISTS operator_id VARCHAR(50) DEFAULT 'beach_habitats_30a';

CREATE INDEX IF NOT EXISTS idx_pricing_operator 
ON property_pricing(operator_id);

-- 6. Add operator_id to property_availability
ALTER TABLE property_availability 
ADD COLUMN IF NOT EXISTS operator_id VARCHAR(50) DEFAULT 'beach_habitats_30a';

CREATE INDEX IF NOT EXISTS idx_availability_operator 
ON property_availability(operator_id);

-- 7. Add foreign keys (optional, for referential integrity)
-- ALTER TABLE properties ADD CONSTRAINT fk_properties_operator 
--   FOREIGN KEY (operator_id) REFERENCES operators(operator_id);

-- Done! All existing data now belongs to 'beach_habitats_30a'
"""
