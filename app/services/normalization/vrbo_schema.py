"""
VRBO Normalization Schema.

Defines the exact schema for ingesting VRBO data as a PERIPHERAL SIGNAL.

IMPORTANT: VRBO is NOT the "truth" - it's a signal with:
- Different host behavior
- Different booking patterns  
- Different guest expectations

We use VRBO data for:
✅ Supply counts
✅ Amenity prevalence
✅ Price posture (directional only)
✅ Availability compression
✅ Listing churn

We DO NOT use VRBO for:
❌ Booking data (not publicly available)
❌ Revenue numbers (not publicly available)
❌ Occupancy claims (inference risk)

This schema ensures VRBO data is normalized without polluting internal performance signals.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# =============================================================================
# VRBO LISTING MODEL (Raw → Normalized)
# =============================================================================

class VRBORawListing(BaseModel):
    """
    Raw VRBO listing data as scraped.
    
    This is the input format before normalization.
    """
    # VRBO identifiers
    vrbo_id: str  # e.g., "1234567"
    vrbo_url: Optional[str] = None
    
    # Location (as scraped)
    address_text: Optional[str] = None  # May be partial/obscured
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    
    # Property details
    headline: Optional[str] = None
    description: Optional[str] = None
    bedrooms: Optional[int] = None
    bathrooms: Optional[float] = None
    sleeps: Optional[int] = None
    property_type: Optional[str] = None  # "House", "Condo", etc.
    
    # Amenities (raw list from VRBO)
    amenities_raw: List[str] = Field(default_factory=list)
    
    # Pricing (current/displayed)
    price_per_night: Optional[float] = None
    price_currency: str = "USD"
    cleaning_fee: Optional[float] = None
    
    # Reviews
    review_count: Optional[int] = None
    review_rating: Optional[float] = None
    
    # Status
    is_active: bool = True
    
    # Scrape metadata
    scraped_at: datetime = Field(default_factory=datetime.utcnow)


class VRBONormalizedListing(BaseModel):
    """
    Normalized VRBO listing for market intelligence.
    
    This is what flows into the platform weighting engine.
    Note: We intentionally exclude revenue/occupancy fields.
    """
    # Identity
    listing_id: UUID = Field(default_factory=uuid4)
    vrbo_id: str
    source: str = "vrbo"
    
    # Geolocation (REQUIRED for geofence matching)
    latitude: float
    longitude: float
    city: str
    state: str
    country: str = "US"
    
    # Property characteristics
    bedrooms: int
    bathrooms: float
    sleeps: int
    property_type: str  # Normalized: single_family, condo, townhouse, etc.
    
    # Normalized amenities (boolean flags)
    has_pool: bool = False
    has_pool_heated: bool = False
    has_hot_tub: bool = False
    has_waterfront: bool = False
    waterfront_type: Optional[str] = None  # gulf, ocean, lake, bay, river
    has_beach_access: bool = False
    beach_access_type: Optional[str] = None  # private, public
    is_pet_friendly: bool = False
    has_ac: bool = False
    has_wifi: bool = False
    has_parking: bool = False
    has_ev_charger: bool = False
    has_game_room: bool = False
    has_home_theater: bool = False
    has_outdoor_grill: bool = False
    
    # Price tier (NOT exact price - directional only)
    price_tier: str = "mid"  # budget, mid, premium, luxury
    
    # Quality signals
    review_count: int = 0
    review_rating: Optional[float] = None
    
    # Status
    is_active: bool = True
    
    # Metadata
    normalized_at: datetime = Field(default_factory=datetime.utcnow)
    confidence_score: float = 0.5  # How confident we are in this data


# =============================================================================
# VRBO AVAILABILITY MODEL (Calendar Signals)
# =============================================================================

class VRBOAvailabilitySignal(BaseModel):
    """
    Availability signal for a VRBO listing.
    
    We use this for AVAILABILITY COMPRESSION only.
    We DO NOT infer bookings or revenue from this.
    """
    listing_id: UUID
    vrbo_id: str
    
    # Date range checked
    check_date: date
    days_forward: int  # How many days ahead we checked
    
    # Availability counts (NOT booking counts)
    days_available: int
    days_unavailable: int  # Could be blocked OR booked - we don't know
    
    # Compression metrics
    availability_rate: float  # days_available / total_days
    compression_signal: float  # 1 - availability_rate (higher = more compressed)
    
    # Metadata
    observed_at: datetime = Field(default_factory=datetime.utcnow)
    
    # IMPORTANT: We explicitly DO NOT include:
    # - booked_nights (we can't know this)
    # - estimated_revenue (inference risk)
    # - occupancy_rate (inference risk)


class VRBOMarketAvailability(BaseModel):
    """
    Aggregated availability signals for a market/geofence.
    
    This flows into platform weighting as availability compression.
    """
    geofence_id: str
    
    # Sample size
    listings_sampled: int
    
    # Compression metrics (safe signals)
    pct_unavailable_next_7: float
    pct_unavailable_next_14: float
    pct_unavailable_next_30: float
    pct_unavailable_next_60: float
    pct_unavailable_next_90: float
    
    # Trend (directional)
    compression_trend: str = "stable"  # increasing, decreasing, stable
    compression_change_7d: float = 0.0  # Change vs 7 days ago
    
    # Metadata
    computed_at: datetime = Field(default_factory=datetime.utcnow)
    confidence: float = 0.5


# =============================================================================
# VRBO PRICING POSTURE MODEL (Directional Only)
# =============================================================================

class PriceTrend(str, Enum):
    """Price movement direction."""
    RISING = "rising"
    FALLING = "falling"
    STABLE = "stable"
    VOLATILE = "volatile"


class VRBOPricingPosture(BaseModel):
    """
    Pricing posture signal for VRBO listings.
    
    IMPORTANT: This is DIRECTIONAL ONLY.
    We DO NOT claim exact ADR or revenue from VRBO.
    """
    geofence_id: str
    
    # Sample size
    listings_sampled: int
    
    # Price tier distribution (NOT exact prices)
    pct_budget: float  # < $150/night
    pct_mid: float  # $150-300/night
    pct_premium: float  # $300-500/night
    pct_luxury: float  # > $500/night
    
    # Directional signals only
    price_trend: PriceTrend
    price_change_7d_pct: float  # Percentage change, not absolute
    price_change_30d_pct: float
    
    # Relative positioning (vs prior period)
    prices_above_prior_month: bool
    prices_above_prior_year: bool
    
    # Metadata
    computed_at: datetime = Field(default_factory=datetime.utcnow)
    confidence: float = 0.5
    
    # EXPLICITLY NOT INCLUDED:
    # - avg_adr (inference risk)
    # - revenue_estimate (not available)
    # - exact_prices (competitive risk)


# =============================================================================
# VRBO AMENITY MODEL (Prevalence Signals)
# =============================================================================

class VRBOAmenityPrevalence(BaseModel):
    """
    Amenity prevalence for a market from VRBO data.
    
    This feeds into APS (Amenity Point Score) calculation.
    """
    geofence_id: str
    
    # Sample size
    listings_sampled: int
    
    # Core amenity saturation rates (0-1)
    pool_saturation: float = 0.0
    pool_heated_saturation: float = 0.0
    hot_tub_saturation: float = 0.0
    waterfront_saturation: float = 0.0
    beach_access_saturation: float = 0.0
    pet_friendly_saturation: float = 0.0
    ev_charger_saturation: float = 0.0
    game_room_saturation: float = 0.0
    
    # Computed metrics
    luxury_amenity_index: float = 0.0  # Weighted combination
    
    # Metadata
    computed_at: datetime = Field(default_factory=datetime.utcnow)
    confidence: float = 0.5


# =============================================================================
# VRBO SUPPLY MODEL (Listing Counts & Churn)
# =============================================================================

class VRBOSupplySignal(BaseModel):
    """
    Supply signals from VRBO for a market.
    """
    geofence_id: str
    
    # Current supply
    total_listings: int
    active_listings: int
    
    # By property type
    listings_by_type: Dict[str, int] = Field(default_factory=dict)
    
    # By bedroom count
    listings_by_bedrooms: Dict[int, int] = Field(default_factory=dict)
    
    # Churn metrics
    new_listings_7d: int = 0
    new_listings_30d: int = 0
    removed_listings_7d: int = 0
    removed_listings_30d: int = 0
    
    # Growth rates
    listing_growth_7d_pct: float = 0.0
    listing_growth_30d_pct: float = 0.0
    
    # Metadata
    computed_at: datetime = Field(default_factory=datetime.utcnow)
    confidence: float = 0.5


# =============================================================================
# VRBO CONFIDENCE SCORING
# =============================================================================

class VRBODataConfidence(BaseModel):
    """
    Confidence scoring for VRBO data.
    
    This determines how much weight we give to VRBO signals.
    """
    geofence_id: str
    
    # Coverage metrics
    listings_coverage: float  # % of estimated total market captured
    data_freshness_days: int  # How old is the newest data
    
    # Quality metrics
    geocode_accuracy: float  # % of listings with accurate geocodes
    amenity_completeness: float  # % of listings with full amenity data
    price_data_completeness: float  # % with valid pricing
    
    # Consistency metrics
    data_consistency: float  # How consistent across scrapes
    
    # Overall confidence (weighted)
    overall_confidence: float
    
    # Confidence by signal type
    supply_confidence: float
    availability_confidence: float
    pricing_confidence: float
    amenity_confidence: float
    
    # Metadata
    computed_at: datetime = Field(default_factory=datetime.utcnow)


# =============================================================================
# VRBO NORMALIZER
# =============================================================================

class VRBONormalizer:
    """
    Normalizes raw VRBO data into signals for the intelligence engine.
    
    Key principle: VRBO is a signal, not the truth.
    """
    
    # Amenity keyword mapping
    AMENITY_KEYWORDS = {
        "pool": ["pool", "swimming pool", "private pool", "shared pool"],
        "pool_heated": ["heated pool", "pool heater", "warm pool"],
        "hot_tub": ["hot tub", "jacuzzi", "spa", "whirlpool"],
        "waterfront": ["waterfront", "oceanfront", "beachfront", "lakefront", "bayfront"],
        "beach_access": ["beach access", "beach", "private beach", "beach nearby"],
        "pet_friendly": ["pet friendly", "pets allowed", "dogs allowed", "pet-friendly"],
        "ev_charger": ["ev charger", "electric vehicle", "ev charging", "tesla charger"],
        "game_room": ["game room", "arcade", "games", "pool table", "foosball"],
    }
    
    # Price tier thresholds
    PRICE_TIERS = {
        "budget": (0, 150),
        "mid": (150, 300),
        "premium": (300, 500),
        "luxury": (500, float("inf")),
    }
    
    def normalize_listing(
        self,
        raw: VRBORawListing,
    ) -> VRBONormalizedListing:
        """
        Normalize a raw VRBO listing.
        """
        # Parse amenities
        amenities_lower = [a.lower() for a in raw.amenities_raw]
        
        has_pool = any(
            kw in " ".join(amenities_lower) 
            for kw in self.AMENITY_KEYWORDS["pool"]
        )
        has_pool_heated = any(
            kw in " ".join(amenities_lower) 
            for kw in self.AMENITY_KEYWORDS["pool_heated"]
        )
        has_hot_tub = any(
            kw in " ".join(amenities_lower) 
            for kw in self.AMENITY_KEYWORDS["hot_tub"]
        )
        has_waterfront = any(
            kw in " ".join(amenities_lower) 
            for kw in self.AMENITY_KEYWORDS["waterfront"]
        )
        has_beach_access = any(
            kw in " ".join(amenities_lower) 
            for kw in self.AMENITY_KEYWORDS["beach_access"]
        )
        is_pet_friendly = any(
            kw in " ".join(amenities_lower) 
            for kw in self.AMENITY_KEYWORDS["pet_friendly"]
        )
        
        # Determine price tier
        price_tier = "mid"
        if raw.price_per_night:
            for tier, (low, high) in self.PRICE_TIERS.items():
                if low <= raw.price_per_night < high:
                    price_tier = tier
                    break
        
        # Calculate confidence
        confidence = self._calculate_confidence(raw)
        
        return VRBONormalizedListing(
            vrbo_id=raw.vrbo_id,
            latitude=raw.latitude or 0.0,
            longitude=raw.longitude or 0.0,
            city=raw.city or "Unknown",
            state=raw.state or "XX",
            bedrooms=raw.bedrooms or 0,
            bathrooms=raw.bathrooms or 0.0,
            sleeps=raw.sleeps or 0,
            property_type=self._normalize_property_type(raw.property_type),
            has_pool=has_pool,
            has_pool_heated=has_pool_heated,
            has_hot_tub=has_hot_tub,
            has_waterfront=has_waterfront,
            has_beach_access=has_beach_access,
            is_pet_friendly=is_pet_friendly,
            price_tier=price_tier,
            review_count=raw.review_count or 0,
            review_rating=raw.review_rating,
            is_active=raw.is_active,
            confidence_score=confidence,
        )
    
    def _normalize_property_type(self, raw_type: Optional[str]) -> str:
        """Normalize property type to canonical values."""
        if not raw_type:
            return "unknown"
        
        raw_lower = raw_type.lower()
        
        if "house" in raw_lower or "home" in raw_lower:
            return "single_family"
        elif "condo" in raw_lower or "apartment" in raw_lower:
            return "condo"
        elif "townhouse" in raw_lower or "townhome" in raw_lower:
            return "townhouse"
        elif "cabin" in raw_lower:
            return "cabin"
        elif "villa" in raw_lower:
            return "villa"
        else:
            return "other"
    
    def _calculate_confidence(self, raw: VRBORawListing) -> float:
        """Calculate confidence score for listing data."""
        score = 0.5  # Base
        
        # Geocoding
        if raw.latitude and raw.longitude:
            score += 0.15
        
        # Property details
        if raw.bedrooms and raw.bathrooms:
            score += 0.10
        
        # Amenities
        if len(raw.amenities_raw) >= 5:
            score += 0.10
        
        # Reviews
        if raw.review_count and raw.review_count >= 5:
            score += 0.10
        
        # Price
        if raw.price_per_night:
            score += 0.05
        
        return min(score, 1.0)
    
    def aggregate_for_geofence(
        self,
        listings: List[VRBONormalizedListing],
        geofence_id: str,
    ) -> Dict[str, Any]:
        """
        Aggregate normalized listings into market signals.
        
        Returns data compatible with PlatformSignals.
        """
        if not listings:
            return {
                "geofence_id": geofence_id,
                "listing_count": 0,
                "confidence": 0.0,
            }
        
        active = [l for l in listings if l.is_active]
        total = len(active)
        
        if total == 0:
            return {
                "geofence_id": geofence_id,
                "listing_count": 0,
                "confidence": 0.0,
            }
        
        # Amenity saturation
        pool_count = sum(1 for l in active if l.has_pool)
        waterfront_count = sum(1 for l in active if l.has_waterfront)
        pet_count = sum(1 for l in active if l.is_pet_friendly)
        
        # Average confidence
        avg_confidence = sum(l.confidence_score for l in active) / total
        
        return {
            "geofence_id": geofence_id,
            "source": "vrbo",
            "listing_count": total,
            "pct_with_pool": pool_count / total,
            "pct_with_waterfront": waterfront_count / total,
            "pct_with_pet_friendly": pet_count / total,
            "confidence": avg_confidence,
            "computed_at": datetime.utcnow().isoformat(),
        }
