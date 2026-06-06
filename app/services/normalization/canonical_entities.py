"""
Normalized Canonical Entities - THE FOUNDATION OF EVERYTHING.

This module defines the immutable, source-agnostic normalized entities
that ALL other systems depend on:
- Detectors fire on normalized deltas
- Pricing engine reads availability + market
- Voice agent explains decisions using confidence + comps
- BD agent uses first_seen + price changes

Design Principles (Non-Negotiable):
1. SOURCE-AGNOSTIC - MLS, PMS, OTA, scrapers all map here
2. OPINIONATED - Don't mirror raw feeds
3. IMMUTABLE - Raw → Normalized → Derived
4. EXPLICIT CONFIDENCE & PROVENANCE - Voice agents need to explain why
"""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator, computed_field


# =============================================================================
# ENUMS
# =============================================================================

class PropertyType(str, Enum):
    """Standardized property types."""
    SINGLE_FAMILY = "single_family"
    CONDO = "condo"
    TOWNHOUSE = "townhouse"
    VILLA = "villa"
    COTTAGE = "cottage"
    CABIN = "cabin"
    APARTMENT = "apartment"
    DUPLEX = "duplex"
    OTHER = "other"


class ViewType(str, Enum):
    """View classifications."""
    GULF = "gulf"
    OCEAN = "ocean"
    BAY = "bay"
    LAKE = "lake"
    RIVER = "river"
    MOUNTAIN = "mountain"
    POOL = "pool"
    GOLF = "golf"
    CITY = "city"
    NONE = "none"


class AvailabilityStatus(str, Enum):
    """Availability status for a date."""
    AVAILABLE = "available"
    BOOKED = "booked"
    BLOCKED = "blocked"
    OWNER_HOLD = "owner_hold"
    MAINTENANCE = "maintenance"


class DataSource(str, Enum):
    """Source of normalized data."""
    MLS = "mls"
    PMS = "pms"
    OTA = "ota"
    MANUAL = "manual"
    SCRAPER = "scraper"
    API = "api"


# =============================================================================
# NORMALIZED PROPERTY
# =============================================================================

class SourceIds(BaseModel):
    """Source identifiers for cross-system matching."""
    mls: Optional[str] = None
    pms: Optional[str] = None
    ota: List[str] = Field(default_factory=list)
    internal: Optional[str] = None


class Location(BaseModel):
    """Normalized location data."""
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)
    
    # Market classification
    market_id: Optional[UUID] = None
    submarket_id: Optional[UUID] = None
    
    # Address components
    address: str
    city: str
    state: str = Field(..., min_length=2, max_length=2)
    postal_code: str
    
    # Computed distances (populated by enrichment)
    beach_distance_ft: Optional[int] = None
    airport_distance_miles: Optional[float] = None


class PhysicalAttributes(BaseModel):
    """Physical property attributes."""
    bedrooms: int = Field(..., ge=0, le=50)
    bathrooms: float = Field(..., ge=0, le=50)
    sqft: Optional[int] = Field(None, ge=100, le=100000)
    property_type: PropertyType = PropertyType.OTHER
    
    # Additional physical
    floors: Optional[int] = Field(None, ge=1, le=100)
    year_built: Optional[int] = Field(None, ge=1800, le=2100)
    lot_sqft: Optional[int] = None
    sleeps: Optional[int] = Field(None, ge=1, le=100)


class Amenities(BaseModel):
    """
    Normalized amenities.
    
    These are the amenities that MATTER for pricing and matching.
    Not an exhaustive list - an OPINIONATED list.
    """
    # Premium amenities (major pricing impact)
    waterfront: bool = False
    pool: bool = False
    pool_heated: bool = False
    hot_tub: bool = False
    dock: bool = False
    boat_slip: bool = False
    
    # View (significant pricing impact)
    view: ViewType = ViewType.NONE
    
    # Beach access
    beach_access: bool = False
    beach_access_private: bool = False
    
    # Outdoor
    outdoor_kitchen: bool = False
    fire_pit: bool = False
    
    # Convenience
    elevator: bool = False
    garage: bool = False
    ev_charger: bool = False
    
    # Pet policy (impacts bookability)
    pet_friendly: bool = False
    
    # Entertainment
    game_room: bool = False
    home_theater: bool = False


class NormalizedProperty(BaseModel):
    """
    THE canonical property entity.
    
    All property data from all sources normalizes to this structure.
    This survives new data sources without rewrites.
    """
    # Identity
    property_id: UUID = Field(default_factory=uuid4)
    source_ids: SourceIds = Field(default_factory=SourceIds)
    
    # Core data
    location: Location
    physical: PhysicalAttributes
    amenities: Amenities = Field(default_factory=Amenities)
    
    # Quality signals
    quality_score: float = Field(0.0, ge=0.0, le=1.0, description="Property quality rating")
    confidence: float = Field(0.0, ge=0.0, le=1.0, description="Data confidence score")
    
    # Provenance
    first_seen: datetime = Field(default_factory=datetime.utcnow)
    last_updated: datetime = Field(default_factory=datetime.utcnow)
    primary_source: DataSource = DataSource.MANUAL
    
    # Optional enrichment
    description: Optional[str] = None
    photos: List[str] = Field(default_factory=list)
    listing_url: Optional[str] = None
    
    # Financial (if known)
    listed_price: Optional[Decimal] = None
    estimated_value: Optional[Decimal] = None
    
    @computed_field
    @property
    def bedroom_bath_summary(self) -> str:
        """Human-readable BR/BA summary."""
        bath_str = f"{self.physical.bathrooms:.1f}".rstrip('0').rstrip('.')
        return f"{self.physical.bedrooms}BR/{bath_str}BA"
    
    @computed_field
    @property
    def has_premium_amenities(self) -> bool:
        """Check if property has premium amenities."""
        return (
            self.amenities.waterfront or
            self.amenities.pool or
            self.amenities.hot_tub or
            self.amenities.view != ViewType.NONE
        )


# =============================================================================
# NORMALIZED AVAILABILITY
# =============================================================================

class NormalizedAvailability(BaseModel):
    """
    Single date availability record.
    
    This is the atomic unit of inventory.
    Pricing engine reads this + market to make decisions.
    """
    property_id: UUID
    date: date
    
    status: AvailabilityStatus = AvailabilityStatus.AVAILABLE
    
    # Pricing
    rate: Optional[Decimal] = Field(None, ge=0, description="Nightly rate")
    minimum_stay: int = Field(1, ge=1, description="Minimum stay requirement")
    
    # For booked dates
    booking_id: Optional[str] = None
    
    # Provenance
    source: DataSource = DataSource.PMS
    confidence: float = Field(1.0, ge=0.0, le=1.0)
    last_updated: datetime = Field(default_factory=datetime.utcnow)


# =============================================================================
# NORMALIZED BOOKING PERFORMANCE
# =============================================================================

class NormalizedBookingPerformance(BaseModel):
    """
    Aggregated booking performance for a property over a period.
    
    This is what drives:
    - Comparable analysis
    - Rent projections
    - Historical pattern detection
    """
    property_id: UUID
    period: str = Field(..., pattern=r"^\d{4}-\d{2}$", description="YYYY-MM format")
    
    # Core metrics
    occupancy_rate: float = Field(..., ge=0.0, le=1.0)
    adr: Decimal = Field(..., ge=0, description="Average Daily Rate")
    revpar: Decimal = Field(..., ge=0, description="Revenue Per Available Room")
    
    # Booking behavior
    lead_time_avg_days: float = Field(0, ge=0, description="Average days booked in advance")
    booking_velocity: float = Field(1.0, description="Pace vs historical (1.0 = on pace)")
    
    # Volume
    nights_available: int = Field(0, ge=0)
    nights_booked: int = Field(0, ge=0)
    total_revenue: Decimal = Field(Decimal("0"), ge=0)
    
    # Provenance
    source: DataSource = DataSource.PMS
    confidence: float = Field(1.0, ge=0.0, le=1.0)
    
    @field_validator("revpar", mode="before")
    @classmethod
    def compute_revpar(cls, v, info):
        """Compute RevPAR if not provided."""
        if v is not None:
            return v
        data = info.data
        if data.get("adr") and data.get("occupancy_rate"):
            return Decimal(str(float(data["adr"]) * data["occupancy_rate"]))
        return Decimal("0")


# =============================================================================
# NORMALIZED MARKET SNAPSHOT
# =============================================================================

class MarketSupply(BaseModel):
    """Market supply metrics."""
    active_listings: int = Field(0, ge=0)
    new_listings_7d: int = Field(0, ge=0)
    new_listings_30d: int = Field(0, ge=0)
    removed_listings_30d: int = Field(0, ge=0)


class MarketDemand(BaseModel):
    """Market demand metrics."""
    search_volume_index: float = Field(1.0, description="Relative to baseline (1.0 = normal)")
    booking_requests: Optional[int] = None
    inquiry_volume: Optional[int] = None


class MarketPricing(BaseModel):
    """Market pricing metrics."""
    median_adr: Decimal = Field(..., ge=0)
    p25_adr: Optional[Decimal] = Field(None, ge=0, description="25th percentile ADR")
    p75_adr: Optional[Decimal] = Field(None, ge=0, description="75th percentile ADR")
    p90_adr: Optional[Decimal] = Field(None, ge=0, description="90th percentile ADR")
    
    median_occupancy: float = Field(0.5, ge=0.0, le=1.0)
    median_revpar: Optional[Decimal] = None


class NormalizedMarketSnapshot(BaseModel):
    """
    Point-in-time market data.
    
    Pricing engine uses this for:
    - Rate recommendations
    - Demand forecasting
    - Competitive positioning
    """
    market_id: UUID
    date: date
    
    supply: MarketSupply = Field(default_factory=MarketSupply)
    demand: MarketDemand = Field(default_factory=MarketDemand)
    pricing: MarketPricing
    
    # Segmentation (metrics by bedroom count)
    by_bedroom: Dict[int, Dict[str, Any]] = Field(default_factory=dict)
    
    # Provenance
    confidence: float = Field(0.8, ge=0.0, le=1.0)
    sources: List[DataSource] = Field(default_factory=list)


# =============================================================================
# NORMALIZED COMPARABLE SET
# =============================================================================

class CompSelectionLogic(BaseModel):
    """Logic used to select comparables."""
    bedroom_delta: int = Field(1, ge=0, description="Max bedroom difference from subject")
    bathroom_delta: float = Field(1.0, ge=0, description="Max bathroom difference")
    sqft_pct_delta: float = Field(0.25, ge=0, le=1, description="Max sqft difference %")
    amenities_match: List[str] = Field(default_factory=list, description="Required amenity matches")
    radius_miles: float = Field(5.0, ge=0.5, le=50)


class CompProperty(BaseModel):
    """A comparable property with similarity scoring."""
    property_id: UUID
    similarity_score: float = Field(..., ge=0.0, le=1.0)
    
    # What matched
    matching_attributes: List[str] = Field(default_factory=list)
    differing_attributes: List[str] = Field(default_factory=list)
    
    # Performance (if available)
    annual_revenue: Optional[Decimal] = None
    avg_occupancy: Optional[float] = None
    avg_adr: Optional[Decimal] = None
    
    # Distance
    distance_miles: Optional[float] = None


class NormalizedComparableSet(BaseModel):
    """
    A set of comparables for a subject property.
    
    This is critical for:
    - Rent projections (base ADR comes from weighted comps)
    - Owner conversations ("here's what similar properties earn")
    - Voice agent explanations
    """
    subject_property_id: UUID
    comp_property_ids: List[UUID] = Field(default_factory=list)
    
    # How we selected them
    selection_logic: CompSelectionLogic = Field(default_factory=CompSelectionLogic)
    
    # Detailed comp data
    comparables: List[CompProperty] = Field(default_factory=list)
    
    # Aggregate metrics
    avg_annual_revenue: Optional[Decimal] = None
    median_annual_revenue: Optional[Decimal] = None
    avg_adr: Optional[Decimal] = None
    avg_occupancy: Optional[float] = None
    
    # Quality
    data_coverage_pct: float = Field(0.0, ge=0.0, le=1.0, description="% of comps with performance data")
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    
    # Metadata
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    
    @computed_field
    @property
    def comp_count(self) -> int:
        return len(self.comp_property_ids)


# =============================================================================
# SEASONALITY CURVE
# =============================================================================

class MonthlySeasonality(BaseModel):
    """Seasonality factors for a single month."""
    month: int = Field(..., ge=1, le=12)
    
    # Relative to annual average (1.0 = average)
    occupancy_factor: float = Field(1.0, description="Occupancy relative to annual avg")
    rate_factor: float = Field(1.0, description="ADR relative to annual avg")
    
    # Absolute expectations
    expected_occupancy: float = Field(0.5, ge=0.0, le=1.0)
    expected_adr: Optional[Decimal] = None


class MarketSeasonality(BaseModel):
    """
    Full seasonality curve for a market.
    
    This is essential for:
    - Monthly rent projections
    - Dynamic pricing
    - Discount engine (knowing when NOT to discount)
    """
    market_id: UUID
    
    # Monthly data
    monthly: List[MonthlySeasonality] = Field(default_factory=list)
    
    # Special periods (holidays, events)
    peak_periods: List[Dict[str, Any]] = Field(default_factory=list)
    # Example: {"name": "4th of July", "start": "07-01", "end": "07-07", "rate_factor": 1.5}
    
    # Metadata
    based_on_years: int = Field(1, ge=1, description="Years of historical data")
    confidence: float = Field(0.8, ge=0.0, le=1.0)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def calculate_similarity_score(
    subject: NormalizedProperty,
    candidate: NormalizedProperty,
    logic: CompSelectionLogic
) -> float:
    """
    Calculate similarity score between two properties.
    
    Returns 0.0 to 1.0 where 1.0 is identical.
    """
    score = 1.0
    
    # Bedroom match (most important)
    bedroom_diff = abs(subject.physical.bedrooms - candidate.physical.bedrooms)
    if bedroom_diff > logic.bedroom_delta:
        return 0.0  # Disqualified
    score -= bedroom_diff * 0.1
    
    # Bathroom match
    bath_diff = abs(subject.physical.bathrooms - candidate.physical.bathrooms)
    if bath_diff > logic.bathroom_delta:
        return 0.0
    score -= bath_diff * 0.05
    
    # Property type
    if subject.physical.property_type != candidate.physical.property_type:
        score -= 0.1
    
    # Amenity matching
    amenity_score = 0.0
    amenity_count = 0
    
    if subject.amenities.waterfront == candidate.amenities.waterfront:
        amenity_score += 0.15
    amenity_count += 1
    
    if subject.amenities.pool == candidate.amenities.pool:
        amenity_score += 0.10
    amenity_count += 1
    
    if subject.amenities.view == candidate.amenities.view:
        amenity_score += 0.08
    amenity_count += 1
    
    if subject.amenities.hot_tub == candidate.amenities.hot_tub:
        amenity_score += 0.05
    amenity_count += 1
    
    score = (score * 0.6) + (amenity_score / 0.38 * 0.4)  # Weight amenities 40%
    
    return max(0.0, min(1.0, score))
