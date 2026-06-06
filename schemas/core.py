"""
Core Shared Schemas - The Data Spine.

These are the CANONICAL entities that everything else consumes.
BD and Concierge NEVER own their own data models - they consume and enrich these.

Design Rules:
1. Every entity has tenant_id for isolation
2. Versioned and immutable once released
3. No feature-specific fields - those go in enrichment layers
4. All dates in UTC
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, ConfigDict, field_validator


# =============================================================================
# SCHEMA VERSION
# =============================================================================

SCHEMA_VERSION = "1.0.0"


# =============================================================================
# ENUMS (Shared across all schemas)
# =============================================================================

class BookingChannel(str, Enum):
    """Source channel for bookings."""
    AIRBNB = "airbnb"
    VRBO = "vrbo"
    BOOKING_COM = "booking_com"
    DIRECT = "direct"
    EXPEDIA = "expedia"
    GOOGLE = "google"
    OTHER = "other"


class PropertyType(str, Enum):
    """Type of vacation rental property."""
    SINGLE_FAMILY = "single_family"
    CONDO = "condo"
    TOWNHOUSE = "townhouse"
    VILLA = "villa"
    COTTAGE = "cottage"
    CABIN = "cabin"
    APARTMENT = "apartment"
    MULTI_UNIT = "multi_unit"
    OTHER = "other"


class ListingStatus(str, Enum):
    """Status of a listing."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    PENDING = "pending"
    BLOCKED = "blocked"
    UNLISTED = "unlisted"


class BookingStatus(str, Enum):
    """Status of a booking."""
    INQUIRY = "inquiry"
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CHECKED_IN = "checked_in"
    CHECKED_OUT = "checked_out"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"


class MessageDirection(str, Enum):
    """Direction of a message in a thread."""
    INBOUND = "inbound"   # From guest
    OUTBOUND = "outbound"  # To guest


class GuestType(str, Enum):
    """Type of guest for segmentation."""
    FAMILY = "family"
    COUPLE = "couple"
    SOLO = "solo"
    GROUP = "group"
    BUSINESS = "business"
    UNKNOWN = "unknown"


# =============================================================================
# BASE MODELS
# =============================================================================

class TenantScopedModel(BaseModel):
    """Base for all tenant-scoped entities."""
    tenant_id: UUID = Field(..., description="Tenant isolation key")

    model_config = ConfigDict(from_attributes=True)


class TimestampedModel(BaseModel):
    """Base for models with audit timestamps."""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# =============================================================================
# CORE ENTITIES
# =============================================================================

class Tenant(TimestampedModel):
    """
    Top-level tenant (the property management company).
    
    All data is scoped under a tenant for complete isolation.
    """
    tenant_id: UUID = Field(default_factory=uuid4)
    
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9-]+$")
    
    # Contact
    primary_email: str
    primary_phone: Optional[str] = None
    
    # Settings
    timezone: str = "America/Chicago"
    currency: str = "USD"
    
    # Status
    is_active: bool = True
    subscription_tier: Literal["starter", "growth", "enterprise"] = "starter"
    
    # Feature flags
    features_enabled: List[str] = Field(default_factory=list)


class Operator(TenantScopedModel, TimestampedModel):
    """
    An operator within a tenant (could be same as tenant for single-operator).
    
    Supports multi-operator scenarios (e.g., franchise model).
    """
    operator_id: UUID = Field(default_factory=uuid4)
    
    name: str
    code: str = Field(..., max_length=20)  # Internal code like "OPS-001"
    
    # Contact
    email: Optional[str] = None
    phone: Optional[str] = None
    
    # Operational details
    markets_active: List[str] = Field(default_factory=list)  # Market IDs
    property_count: int = 0
    
    is_active: bool = True


class Property(TenantScopedModel, TimestampedModel):
    """
    A physical property (the real estate).
    
    Distinct from Listing - a property can have multiple listings
    (e.g., whole home + individual rooms).
    """
    property_id: UUID = Field(default_factory=uuid4)
    operator_id: UUID
    
    # Location
    address_line1: str
    address_line2: Optional[str] = None
    city: str
    state: str = Field(..., min_length=2, max_length=2)
    postal_code: str
    country: str = "US"
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    
    # Property details
    name: str
    property_type: PropertyType = PropertyType.SINGLE_FAMILY
    
    bedrooms: int = Field(..., ge=0, le=50)
    bathrooms: float = Field(..., ge=0, le=50)
    sleeps: int = Field(..., ge=1, le=100)
    square_footage: Optional[int] = Field(None, ge=0)
    
    # Amenities (normalized booleans)
    has_pool: bool = False
    pool_heated: bool = False
    has_hot_tub: bool = False
    has_waterfront: bool = False
    waterfront_type: Optional[str] = None  # gulf, ocean, lake, bay, river
    beach_access: Optional[str] = None  # private, deeded, public, none
    pet_friendly: bool = False
    has_garage: bool = False
    has_ev_charger: bool = False
    has_game_room: bool = False
    has_home_theater: bool = False
    
    # Extended amenities (flexible)
    amenities: List[str] = Field(default_factory=list)
    
    # Owner info (anonymized)
    owner_id: Optional[UUID] = None
    
    is_active: bool = True


class Listing(TenantScopedModel, TimestampedModel):
    """
    A bookable listing on a channel.
    
    A property can have multiple listings (whole home, rooms, etc.)
    Each listing is channel-specific.
    """
    listing_id: UUID = Field(default_factory=uuid4)
    property_id: UUID
    
    # Channel info
    channel: BookingChannel
    external_id: str  # Channel's ID for this listing
    external_url: Optional[str] = None
    
    # Listing details
    title: str
    description: Optional[str] = None
    
    # Configuration
    min_nights: int = 1
    max_nights: int = 365
    max_guests: int = 1
    
    # Status
    status: ListingStatus = ListingStatus.ACTIVE
    
    # Sync metadata
    last_synced_at: Optional[datetime] = None
    sync_enabled: bool = True


class Booking(TenantScopedModel, TimestampedModel):
    """
    A reservation/booking.
    
    This single object:
    - Powers concierge personalization
    - Feeds demand analytics
    - Informs discount sensitivity
    - Enables family-specific insights
    """
    booking_id: UUID = Field(default_factory=uuid4)
    property_id: UUID
    listing_id: UUID
    
    # Guest
    guest_profile_id: Optional[UUID] = None
    
    # Dates
    start_date: date
    end_date: date
    nights: int = Field(..., ge=1)
    
    # Guest composition
    adults: int = Field(1, ge=0)
    children: int = Field(0, ge=0)
    infants: int = Field(0, ge=0)
    pets: bool = False
    
    # Channel & source
    channel: BookingChannel
    external_id: str  # Channel's booking ID
    
    # Financials
    total_amount: Decimal = Field(..., ge=0)
    nightly_rate: Decimal = Field(..., ge=0)
    cleaning_fee: Decimal = Field(Decimal("0"), ge=0)
    service_fee: Decimal = Field(Decimal("0"), ge=0)
    taxes: Decimal = Field(Decimal("0"), ge=0)
    host_payout: Optional[Decimal] = None
    
    # Status
    status: BookingStatus = BookingStatus.CONFIRMED
    
    # Timestamps
    booked_at: datetime
    cancelled_at: Optional[datetime] = None
    
    @field_validator('nights', mode='before')
    @classmethod
    def calculate_nights(cls, v, info):
        if v is None and 'start_date' in info.data and 'end_date' in info.data:
            return (info.data['end_date'] - info.data['start_date']).days
        return v


class GuestProfile(TenantScopedModel, TimestampedModel):
    """
    Anonymized guest profile for personalization.
    
    NO PII stored - only behavioral and preference signals.
    """
    guest_profile_id: UUID = Field(default_factory=uuid4)
    
    # Channel identifiers (hashed)
    channel_guest_ids: Dict[str, str] = Field(default_factory=dict)  # {"airbnb": "hash123"}
    
    # Derived attributes (from booking history)
    guest_type: GuestType = GuestType.UNKNOWN
    typical_party_size: Optional[int] = None
    travels_with_children: Optional[bool] = None
    travels_with_pets: Optional[bool] = None
    
    # Booking patterns
    total_bookings: int = 0
    total_nights: int = 0
    avg_booking_value: Optional[Decimal] = None
    preferred_channels: List[str] = Field(default_factory=list)
    
    # Engagement signals
    response_rate: Optional[float] = None  # How often they respond to messages
    review_rate: Optional[float] = None    # How often they leave reviews
    
    # Preferences (learned over time)
    preferences: Dict[str, Any] = Field(default_factory=dict)
    
    # Risk signals
    cancellation_rate: Optional[float] = None
    is_flagged: bool = False
    flag_reason: Optional[str] = None


class MessageThread(TenantScopedModel, TimestampedModel):
    """
    A conversation thread with a guest.
    
    Used by concierge for context and by analytics for intent extraction.
    """
    thread_id: UUID = Field(default_factory=uuid4)
    
    # Context
    booking_id: Optional[UUID] = None
    property_id: UUID
    guest_profile_id: Optional[UUID] = None
    
    # Channel
    channel: BookingChannel
    external_thread_id: Optional[str] = None
    
    # Thread metadata
    subject: Optional[str] = None
    message_count: int = 0
    
    # Status
    is_open: bool = True
    requires_response: bool = False
    last_message_at: Optional[datetime] = None
    last_message_direction: Optional[MessageDirection] = None
    
    # AI processing
    last_processed_at: Optional[datetime] = None
    extracted_intents: List[str] = Field(default_factory=list)


class Message(TenantScopedModel, TimestampedModel):
    """
    Individual message within a thread.
    """
    message_id: UUID = Field(default_factory=uuid4)
    thread_id: UUID
    
    # Content
    direction: MessageDirection
    content: str
    content_type: Literal["text", "html", "image", "attachment"] = "text"
    
    # Sender (anonymized)
    sender_type: Literal["guest", "host", "system", "ai"] = "guest"
    
    # Channel metadata
    external_id: Optional[str] = None
    sent_at: datetime
    
    # AI processing
    processed: bool = False
    extracted_intent: Optional[str] = None
    sentiment: Optional[float] = None  # -1 to 1
    urgency_score: Optional[float] = None  # 0 to 1


class GeoPolygon(TenantScopedModel, TimestampedModel):
    """
    Geographic boundary for market definition.
    
    Used for:
    - Market analytics
    - Geofencing
    - Competitor analysis
    """
    polygon_id: UUID = Field(default_factory=uuid4)
    
    name: str
    description: Optional[str] = None
    
    # Geometry (GeoJSON)
    geometry_type: Literal["Polygon", "MultiPolygon"] = "Polygon"
    coordinates: List[Any]  # GeoJSON coordinates
    
    # Centroid
    center_lat: float
    center_lng: float
    
    # Bounds
    bounds_north: float
    bounds_south: float
    bounds_east: float
    bounds_west: float
    
    # Classification
    polygon_type: Literal["market", "submarket", "neighborhood", "custom"] = "market"
    parent_polygon_id: Optional[UUID] = None
    
    # Metadata
    property_count: int = 0
    is_active: bool = True


class MarketSnapshot(TenantScopedModel, TimestampedModel):
    """
    Point-in-time market analytics.
    
    Generated by analytics workers, consumed by BD agents.
    """
    snapshot_id: UUID = Field(default_factory=uuid4)
    polygon_id: UUID
    
    # Time period
    snapshot_date: date
    period_type: Literal["daily", "weekly", "monthly"] = "daily"
    
    # Supply metrics
    total_listings: int
    active_listings: int
    new_listings_period: int = 0
    delisted_period: int = 0
    
    # Demand metrics
    total_bookings_period: int = 0
    total_nights_booked: int = 0
    avg_occupancy: float = Field(..., ge=0, le=1)
    
    # Pricing metrics
    avg_adr: Decimal
    median_adr: Decimal
    adr_25th_percentile: Decimal
    adr_75th_percentile: Decimal
    
    # Revenue metrics
    total_revenue_period: Decimal
    avg_revpar: Decimal  # Revenue per available room
    
    # Composition
    property_type_breakdown: Dict[str, int] = Field(default_factory=dict)
    bedroom_breakdown: Dict[str, int] = Field(default_factory=dict)
    channel_breakdown: Dict[str, float] = Field(default_factory=dict)
    
    # Trends
    adr_change_yoy: Optional[float] = None
    occupancy_change_yoy: Optional[float] = None
    supply_change_yoy: Optional[float] = None
    
    # Confidence
    data_completeness: float = Field(1.0, ge=0, le=1)
    source_count: int = 1


class AnalyticsResult(TenantScopedModel, TimestampedModel):
    """
    Generic analytics computation result.
    
    Flexible schema for various analytics outputs.
    """
    result_id: UUID = Field(default_factory=uuid4)
    
    # What was computed
    analytics_type: str  # "pricing_sensitivity", "demand_forecast", etc.
    version: str = "1.0"
    
    # Scope
    property_id: Optional[UUID] = None
    polygon_id: Optional[UUID] = None
    
    # Time context
    computed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    valid_from: date
    valid_until: date
    
    # Results (flexible JSON)
    results: Dict[str, Any] = Field(default_factory=dict)
    
    # Metadata
    confidence: float = Field(0.5, ge=0, le=1)
    computation_time_ms: Optional[int] = None
    inputs_hash: Optional[str] = None  # For reproducibility


# =============================================================================
# SCHEMA REGISTRY
# =============================================================================

CORE_SCHEMAS = {
    "Tenant": Tenant,
    "Operator": Operator,
    "Property": Property,
    "Listing": Listing,
    "Booking": Booking,
    "GuestProfile": GuestProfile,
    "MessageThread": MessageThread,
    "Message": Message,
    "GeoPolygon": GeoPolygon,
    "MarketSnapshot": MarketSnapshot,
    "AnalyticsResult": AnalyticsResult,
}


def get_schema_version() -> str:
    """Get current schema version."""
    return SCHEMA_VERSION


def get_all_schemas() -> Dict[str, type]:
    """Get all core schemas."""
    return CORE_SCHEMAS.copy()
