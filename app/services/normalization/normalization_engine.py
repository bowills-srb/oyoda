"""
Data Normalization Engine - THE KEYSTONE.

This is the most critical component of the platform. Everything else
depends on clean, normalized data flowing through the system.

Principles:
1. Normalized entities are IMMUTABLE CONTRACTS
2. Schemas are VERSIONED explicitly
3. Raw feeds NEVER leak upstream
4. Every field has a canonical definition
5. Transformations are auditable and reversible

The normalization pipeline:
RAW DATA → INGESTION → MAPPING → TRANSFORMATION → ENRICHMENT → VALIDATION → CANONICAL STORE
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Callable, Dict, Generic, List, Optional, Tuple, Type, TypeVar, Union
from uuid import UUID, uuid4
import hashlib
import json
import logging
import re

from pydantic import BaseModel, Field, field_validator, model_validator

logger = logging.getLogger(__name__)


# =============================================================================
# SCHEMA VERSIONING
# =============================================================================

SCHEMA_VERSION = "1.0.0"


class SchemaVersion(BaseModel):
    """Tracks schema version for compatibility checking."""
    major: int = 1
    minor: int = 0
    patch: int = 0
    
    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"
    
    def is_compatible_with(self, other: "SchemaVersion") -> bool:
        """Check if this version is compatible with another."""
        # Major version must match for compatibility
        return self.major == other.major


# =============================================================================
# DATA SOURCE REGISTRY
# =============================================================================

class DataSource(str, Enum):
    """
    Canonical list of supported data sources.
    
    Each source has specific field mappings and transformation rules.
    """
    # MLS Systems
    MLS_FLEXMLS = "mls_flexmls"
    MLS_MATRIX = "mls_matrix"
    MLS_PARAGON = "mls_paragon"
    MLS_SPARK = "mls_spark"
    MLS_RAPATTONI = "mls_rapattoni"
    MLS_GENERIC_RESO = "mls_generic_reso"  # RESO standard
    
    # Property Management Systems
    PMS_GUESTY = "pms_guesty"
    PMS_HOSTAWAY = "pms_hostaway"
    PMS_LODGIFY = "pms_lodgify"
    PMS_STREAMLINE = "pms_streamline"
    PMS_ESCAPIA = "pms_escapia"
    PMS_TRACK = "pms_track"
    PMS_BAREFOOT = "pms_barefoot"
    
    # OTAs (Online Travel Agencies)
    OTA_AIRBNB = "ota_airbnb"
    OTA_VRBO = "ota_vrbo"
    OTA_BOOKING = "ota_booking"
    
    # Market Data Providers
    MARKET_AIRDNA = "market_airdna"
    MARKET_KEYDATA = "market_keydata"
    MARKET_TRANSPARENT = "market_transparent"
    MARKET_ALLTHEROOMS = "market_alltherooms"
    
    # Manual / Direct
    MANUAL_UPLOAD = "manual_upload"
    MANUAL_ENTRY = "manual_entry"
    API_DIRECT = "api_direct"


class NormalizationStatus(str, Enum):
    """Status of a normalization operation."""
    PENDING = "pending"
    VALIDATING = "validating"
    TRANSFORMING = "transforming"
    ENRICHING = "enriching"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"  # Completed with warnings


class DataQuality(str, Enum):
    """Quality classification of normalized data."""
    EXCELLENT = "excellent"  # 95%+ completeness, all validations pass
    GOOD = "good"           # 80%+ completeness, minor issues
    ACCEPTABLE = "acceptable"  # 60%+ completeness, some gaps
    POOR = "poor"           # Below 60% or significant issues
    UNUSABLE = "unusable"   # Critical data missing


# =============================================================================
# CANONICAL ADDRESS SCHEMA
# =============================================================================

class CanonicalAddress(BaseModel):
    """
    Immutable canonical address format.
    
    All addresses from all sources normalize to this structure.
    """
    # Full formatted address
    line1: str = Field(..., min_length=1, description="Street address line 1")
    line2: Optional[str] = Field(None, description="Unit, apt, suite")
    city: str = Field(..., min_length=1, description="City name")
    state: str = Field(..., min_length=2, max_length=2, description="2-letter state code")
    postal_code: str = Field(..., min_length=5, description="ZIP or postal code")
    country: str = Field(default="US", description="ISO 3166-1 alpha-2 country code")
    
    # Parsed components (for matching/deduplication)
    street_number: Optional[str] = None
    street_name: Optional[str] = None
    street_suffix: Optional[str] = None  # St, Ave, Blvd, etc.
    unit_type: Optional[str] = None  # Apt, Unit, Suite, etc.
    unit_number: Optional[str] = None
    
    # Geocoding
    latitude: Optional[float] = Field(None, ge=-90, le=90)
    longitude: Optional[float] = Field(None, ge=-180, le=180)
    geocode_accuracy: Optional[str] = None  # rooftop, range_interpolated, etc.
    geocode_source: Optional[str] = None  # google, mapbox, census, etc.
    
    # Standardized hash for deduplication
    address_hash: Optional[str] = None
    
    @field_validator("state")
    @classmethod
    def normalize_state(cls, v: str) -> str:
        return v.upper().strip()[:2]
    
    @field_validator("postal_code")
    @classmethod
    def normalize_postal(cls, v: str) -> str:
        # Remove non-alphanumeric, format ZIP+4 properly
        cleaned = re.sub(r'[^0-9]', '', v)
        if len(cleaned) == 9:
            return f"{cleaned[:5]}-{cleaned[5:]}"
        return cleaned[:5]
    
    @model_validator(mode='after')
    def compute_hash(self) -> "CanonicalAddress":
        """Compute address hash for deduplication."""
        components = [
            self.street_number or "",
            self.street_name or "",
            self.city,
            self.state,
            self.postal_code[:5]
        ]
        normalized = "".join(c.lower().replace(" ", "") for c in components)
        self.address_hash = hashlib.md5(normalized.encode()).hexdigest()
        return self
    
    @property
    def full_address(self) -> str:
        """Get formatted full address."""
        parts = [self.line1]
        if self.line2:
            parts.append(self.line2)
        parts.append(f"{self.city}, {self.state} {self.postal_code}")
        return ", ".join(parts)


# =============================================================================
# CANONICAL AMENITIES SCHEMA
# =============================================================================

class PoolType(str, Enum):
    PRIVATE = "private"
    SHARED = "shared"
    COMMUNITY = "community"
    NONE = "none"


class BeachAccessType(str, Enum):
    PRIVATE = "private"
    DEEDED = "deeded"
    PUBLIC_NEARBY = "public_nearby"
    NONE = "none"


class KitchenType(str, Enum):
    FULL = "full"
    KITCHENETTE = "kitchenette"
    NONE = "none"


class CanonicalAmenities(BaseModel):
    """
    Immutable canonical amenities structure.
    
    Standardizes amenity representation across all sources.
    """
    # Swimming
    pool_type: PoolType = PoolType.NONE
    pool_heated: bool = False
    hot_tub: bool = False
    
    # Water Access
    beach_access_type: BeachAccessType = BeachAccessType.NONE
    beach_distance_ft: Optional[int] = None
    lake_access: bool = False
    waterfront: bool = False
    dock: bool = False
    boat_slip: bool = False
    
    # Outdoor
    outdoor_space_sqft: Optional[int] = None
    deck: bool = False
    patio: bool = False
    balcony: bool = False
    yard: bool = False
    outdoor_grill: bool = False
    outdoor_shower: bool = False
    fire_pit: bool = False
    
    # Parking
    parking_spaces: int = 0
    garage: bool = False
    covered_parking: bool = False
    ev_charger: bool = False
    golf_cart_included: bool = False
    
    # Interior Comfort
    ac: bool = True
    heating: bool = True
    ceiling_fans: bool = False
    fireplace: bool = False
    
    # Kitchen
    kitchen_type: KitchenType = KitchenType.FULL
    dishwasher: bool = False
    
    # Laundry
    washer: bool = False
    dryer: bool = False
    washer_dryer_in_unit: bool = False
    
    # Entertainment
    wifi: bool = True
    tv_count: int = 0
    smart_tv: bool = False
    streaming_services: bool = False
    game_room: bool = False
    pool_table: bool = False
    arcade: bool = False
    home_theater: bool = False
    
    # Work
    workspace: bool = False
    
    # Accessibility
    elevator: bool = False
    wheelchair_accessible: bool = False
    single_level: bool = False
    
    # Views
    ocean_view: bool = False
    gulf_view: bool = False
    lake_view: bool = False
    mountain_view: bool = False
    pool_view: bool = False
    
    # Policies
    pet_friendly: bool = False
    pet_fee: Optional[float] = None
    smoking_allowed: bool = False
    events_allowed: bool = False
    
    # Special Features
    elevator_access: bool = False
    concierge: bool = False
    on_site_management: bool = False
    
    def to_feature_list(self) -> List[str]:
        """Convert to human-readable feature list."""
        features = []
        if self.pool_type != PoolType.NONE:
            features.append(f"{self.pool_type.value.title()} Pool")
            if self.pool_heated:
                features.append("Heated Pool")
        if self.hot_tub:
            features.append("Hot Tub")
        if self.beach_access_type != BeachAccessType.NONE:
            features.append(f"{self.beach_access_type.value.replace('_', ' ').title()} Beach Access")
        if self.waterfront:
            features.append("Waterfront")
        if self.pet_friendly:
            features.append("Pet Friendly")
        # ... extend as needed
        return features


# =============================================================================
# CANONICAL PROPERTY SCHEMA
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
    MULTI_UNIT = "multi_unit"
    MOBILE_HOME = "mobile_home"
    OTHER = "other"


class CanonicalProperty(BaseModel):
    """
    IMMUTABLE canonical property schema.
    
    This is the CONTRACT that all systems depend on.
    Changes require schema version bump.
    """
    # Schema metadata
    schema_version: str = SCHEMA_VERSION
    canonical_id: UUID = Field(default_factory=uuid4)
    
    # Source tracking (NEVER lose provenance)
    source_system: DataSource
    source_id: str
    source_url: Optional[str] = None
    source_updated_at: Optional[datetime] = None
    
    # Normalization metadata
    normalized_at: datetime = Field(default_factory=datetime.utcnow)
    normalized_by: str = "normalization_engine"
    
    # Core identity
    name: Optional[str] = None
    internal_code: Optional[str] = None
    
    # Property classification
    property_type: PropertyType = PropertyType.OTHER
    
    # Location (CRITICAL - immutable after geocoding)
    address: CanonicalAddress
    
    # Physical attributes
    bedrooms: int = Field(..., ge=0, le=50)
    bathrooms: float = Field(..., ge=0, le=50)  # Half baths = 0.5
    sleeps: Optional[int] = Field(None, ge=1, le=100)
    square_footage: Optional[int] = Field(None, ge=100, le=100000)
    lot_size_sqft: Optional[int] = None
    year_built: Optional[int] = Field(None, ge=1800, le=2100)
    floors: Optional[int] = Field(None, ge=1, le=100)
    
    # Amenities (structured)
    amenities: CanonicalAmenities = Field(default_factory=CanonicalAmenities)
    
    # Descriptive
    description: Optional[str] = None
    key_features: List[str] = Field(default_factory=list)
    
    # Media
    photo_urls: List[str] = Field(default_factory=list)
    primary_photo_url: Optional[str] = None
    virtual_tour_url: Optional[str] = None
    
    # Financial
    listed_price: Optional[Decimal] = None
    estimated_value: Optional[Decimal] = None
    
    # Owner information (if available)
    owner_name: Optional[str] = None
    owner_email: Optional[str] = None
    owner_phone: Optional[str] = None
    
    # Data quality tracking
    quality_score: float = Field(default=0.0, ge=0.0, le=1.0)
    quality_level: DataQuality = DataQuality.ACCEPTABLE
    completeness_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    validation_errors: List[str] = Field(default_factory=list)
    validation_warnings: List[str] = Field(default_factory=list)
    
    # Deduplication
    fingerprint: Optional[str] = None  # For matching across sources
    
    # Raw data preservation (for debugging/audit)
    raw_data_hash: Optional[str] = None
    
    @model_validator(mode='after')
    def compute_fingerprint(self) -> "CanonicalProperty":
        """Compute property fingerprint for deduplication."""
        components = [
            self.address.address_hash or "",
            str(self.bedrooms),
            str(self.bathrooms),
            str(self.square_footage or ""),
        ]
        self.fingerprint = hashlib.md5("".join(components).encode()).hexdigest()
        return self
    
    @property
    def bedroom_bath_summary(self) -> str:
        """Get BR/BA summary string."""
        bath_str = f"{self.bathrooms:.1f}".rstrip('0').rstrip('.')
        return f"{self.bedrooms}BR/{bath_str}BA"


# =============================================================================
# CANONICAL BOOKING SCHEMA
# =============================================================================

class BookingStatus(str, Enum):
    CONFIRMED = "confirmed"
    PENDING = "pending"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    NO_SHOW = "no_show"


class CanonicalBooking(BaseModel):
    """Immutable canonical booking schema."""
    schema_version: str = SCHEMA_VERSION
    canonical_id: UUID = Field(default_factory=uuid4)
    
    # Source tracking
    source_system: DataSource
    source_id: str
    source_property_id: str
    
    # Link to canonical property
    canonical_property_id: Optional[UUID] = None
    
    # Dates
    check_in: date
    check_out: date
    booked_at: datetime
    
    # Financial
    total_amount: Decimal
    nightly_rate: Decimal
    cleaning_fee: Decimal = Decimal("0")
    service_fee: Decimal = Decimal("0")
    taxes: Decimal = Decimal("0")
    owner_payout: Optional[Decimal] = None
    
    # Guest
    guest_name: Optional[str] = None
    guest_email: Optional[str] = None
    guest_count: int = 1
    
    # Status
    status: BookingStatus = BookingStatus.CONFIRMED
    
    # Calculated
    @property
    def nights(self) -> int:
        return (self.check_out - self.check_in).days
    
    @property
    def booking_window_days(self) -> int:
        """Days between booking and check-in."""
        return (self.check_in - self.booked_at.date()).days
    
    # Metadata
    normalized_at: datetime = Field(default_factory=datetime.utcnow)


# =============================================================================
# CANONICAL MARKET DATA SCHEMA
# =============================================================================

class CanonicalMarketData(BaseModel):
    """Immutable canonical market data schema."""
    schema_version: str = SCHEMA_VERSION
    canonical_id: UUID = Field(default_factory=uuid4)
    
    # Source
    source_system: DataSource
    market_identifier: str  # ZIP, city name, custom area
    
    # Time period
    period_start: date
    period_end: date
    period_type: str  # daily, weekly, monthly
    
    # Key metrics
    avg_daily_rate: Optional[Decimal] = None
    median_daily_rate: Optional[Decimal] = None
    avg_occupancy_rate: Optional[float] = None
    revpar: Optional[Decimal] = None  # Revenue per available room
    
    # Supply metrics
    total_listings: Optional[int] = None
    active_listings: Optional[int] = None
    new_listings: Optional[int] = None
    
    # Demand metrics
    total_bookings: Optional[int] = None
    avg_booking_window: Optional[float] = None  # Days
    avg_length_of_stay: Optional[float] = None
    
    # By bedroom breakdown
    metrics_by_bedroom: Dict[int, Dict[str, Any]] = Field(default_factory=dict)
    
    # Metadata
    normalized_at: datetime = Field(default_factory=datetime.utcnow)


# =============================================================================
# FIELD MAPPING SYSTEM
# =============================================================================

@dataclass
class FieldMapping:
    """
    Maps a source field to a canonical field with optional transformation.
    """
    source_path: str  # Dot notation path in source: "address.street"
    canonical_path: str  # Dot notation path in canonical: "address.line1"
    transformer: Optional[Callable[[Any], Any]] = None
    required: bool = False
    default: Any = None
    description: str = ""


class FieldMappingRegistry:
    """
    Central registry for all field mappings.
    
    Each data source has explicit mappings to canonical schema.
    This is the SINGLE SOURCE OF TRUTH for transformations.
    """
    
    def __init__(self):
        self._mappings: Dict[DataSource, List[FieldMapping]] = {}
        self._transformers: Dict[str, Callable] = {}
        self._initialize_transformers()
        self._initialize_mappings()
    
    def _initialize_transformers(self):
        """Register standard transformation functions."""
        
        self._transformers["to_int"] = lambda x: int(x) if x else None
        self._transformers["to_float"] = lambda x: float(x) if x else None
        self._transformers["to_decimal"] = lambda x: Decimal(str(x)) if x else None
        self._transformers["to_bool"] = self._to_bool
        self._transformers["to_date"] = self._to_date
        self._transformers["to_datetime"] = self._to_datetime
        self._transformers["normalize_state"] = self._normalize_state
        self._transformers["normalize_property_type"] = self._normalize_property_type
        self._transformers["normalize_postal"] = self._normalize_postal
        self._transformers["normalize_phone"] = self._normalize_phone
        self._transformers["extract_bedrooms"] = self._extract_bedrooms
        self._transformers["extract_bathrooms"] = self._extract_bathrooms
    
    @staticmethod
    def _to_bool(value: Any) -> bool:
        """Convert various boolean representations."""
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ('true', 'yes', 'y', '1', 't')
        if isinstance(value, (int, float)):
            return bool(value)
        return False
    
    @staticmethod
    def _to_date(value: Any) -> Optional[date]:
        """Parse various date formats."""
        if isinstance(value, date):
            return value
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, str):
            for fmt in ('%Y-%m-%d', '%m/%d/%Y', '%d/%m/%Y', '%Y%m%d'):
                try:
                    return datetime.strptime(value, fmt).date()
                except ValueError:
                    continue
        return None
    
    @staticmethod
    def _to_datetime(value: Any) -> Optional[datetime]:
        """Parse various datetime formats."""
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            for fmt in ('%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%SZ'):
                try:
                    return datetime.strptime(value, fmt)
                except ValueError:
                    continue
        return None
    
    @staticmethod
    def _normalize_state(value: Any) -> str:
        """Normalize state to 2-letter code."""
        if not value:
            return ""
        
        STATE_MAP = {
            "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
            "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
            "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
            "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
            "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
            "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
            "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
            "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
            "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
            "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
            "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
            "vermont": "VT", "virginia": "VA", "washington": "WA", "west virginia": "WV",
            "wisconsin": "WI", "wyoming": "WY"
        }
        
        value_lower = str(value).lower().strip()
        if value_lower in STATE_MAP:
            return STATE_MAP[value_lower]
        # Already a code
        return value.upper()[:2]
    
    @staticmethod
    def _normalize_property_type(value: Any) -> PropertyType:
        """Normalize property type string to enum."""
        if not value:
            return PropertyType.OTHER
        
        value_lower = str(value).lower()
        
        MAPPINGS = {
            PropertyType.SINGLE_FAMILY: [
                "single family", "single-family", "house", "home", "detached",
                "residential", "sfr", "entire home", "entire place"
            ],
            PropertyType.CONDO: [
                "condo", "condominium", "condo/co-op"
            ],
            PropertyType.TOWNHOUSE: [
                "townhouse", "townhome", "town house", "row house", "attached"
            ],
            PropertyType.VILLA: ["villa"],
            PropertyType.COTTAGE: ["cottage", "bungalow"],
            PropertyType.CABIN: ["cabin", "chalet", "lodge"],
            PropertyType.APARTMENT: ["apartment", "apt", "flat", "unit"],
            PropertyType.DUPLEX: ["duplex", "triplex", "multi-family"],
        }
        
        for prop_type, keywords in MAPPINGS.items():
            if any(kw in value_lower for kw in keywords):
                return prop_type
        
        return PropertyType.OTHER
    
    @staticmethod
    def _normalize_postal(value: Any) -> str:
        """Normalize postal code."""
        if not value:
            return ""
        cleaned = re.sub(r'[^0-9]', '', str(value))
        if len(cleaned) >= 9:
            return f"{cleaned[:5]}-{cleaned[5:9]}"
        return cleaned[:5]
    
    @staticmethod
    def _normalize_phone(value: Any) -> str:
        """Normalize phone number to E.164-ish format."""
        if not value:
            return ""
        digits = re.sub(r'[^0-9]', '', str(value))
        if len(digits) == 10:
            return f"+1{digits}"
        if len(digits) == 11 and digits.startswith('1'):
            return f"+{digits}"
        return digits
    
    @staticmethod
    def _extract_bedrooms(value: Any) -> int:
        """Extract bedroom count from various formats."""
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str):
            # Handle "3 BR", "3 Bedroom", etc.
            match = re.search(r'(\d+)', value)
            if match:
                return int(match.group(1))
        return 0
    
    @staticmethod
    def _extract_bathrooms(value: Any) -> float:
        """Extract bathroom count, handling half baths."""
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            # Handle "2.5", "2 1/2", "2 full 1 half"
            match = re.search(r'(\d+\.?\d*)', value)
            if match:
                return float(match.group(1))
        return 0.0
    
    def _initialize_mappings(self):
        """Initialize mappings for all supported sources."""
        
        # ===================
        # MLS FLEXMLS
        # ===================
        self._mappings[DataSource.MLS_FLEXMLS] = [
            FieldMapping("ListingId", "source_id", required=True),
            FieldMapping("StreetNumber", "address.street_number"),
            FieldMapping("StreetName", "address.street_name"),
            FieldMapping("StreetSuffix", "address.street_suffix"),
            FieldMapping("UnparsedAddress", "address.line1"),
            FieldMapping("UnitNumber", "address.unit_number"),
            FieldMapping("City", "address.city", required=True),
            FieldMapping("StateOrProvince", "address.state", self._transformers["normalize_state"], required=True),
            FieldMapping("PostalCode", "address.postal_code", self._transformers["normalize_postal"], required=True),
            FieldMapping("Latitude", "address.latitude", self._transformers["to_float"]),
            FieldMapping("Longitude", "address.longitude", self._transformers["to_float"]),
            FieldMapping("BedroomsTotal", "bedrooms", self._transformers["to_int"], required=True),
            FieldMapping("BathroomsTotalInteger", "bathrooms", self._transformers["to_float"]),
            FieldMapping("BathroomsFull", "_bathrooms_full", self._transformers["to_int"]),
            FieldMapping("BathroomsHalf", "_bathrooms_half", self._transformers["to_int"]),
            FieldMapping("LivingArea", "square_footage", self._transformers["to_int"]),
            FieldMapping("LotSizeSquareFeet", "lot_size_sqft", self._transformers["to_int"]),
            FieldMapping("YearBuilt", "year_built", self._transformers["to_int"]),
            FieldMapping("ListPrice", "listed_price", self._transformers["to_decimal"]),
            FieldMapping("PropertyType", "property_type", self._transformers["normalize_property_type"]),
            FieldMapping("PropertySubType", "_property_subtype"),
            FieldMapping("PublicRemarks", "description"),
            FieldMapping("PoolPrivateYN", "amenities.pool_type", lambda x: PoolType.PRIVATE if self._to_bool(x) else PoolType.NONE),
            FieldMapping("WaterfrontYN", "amenities.waterfront", self._transformers["to_bool"]),
            FieldMapping("View", "_view_raw"),
        ]
        
        # ===================
        # PMS GUESTY
        # ===================
        self._mappings[DataSource.PMS_GUESTY] = [
            FieldMapping("_id", "source_id", required=True),
            FieldMapping("title", "name"),
            FieldMapping("nickname", "internal_code"),
            FieldMapping("address.full", "address.line1"),
            FieldMapping("address.street", "address.street_name"),
            FieldMapping("address.city", "address.city", required=True),
            FieldMapping("address.state", "address.state", self._transformers["normalize_state"], required=True),
            FieldMapping("address.zipcode", "address.postal_code", self._transformers["normalize_postal"], required=True),
            FieldMapping("address.lat", "address.latitude", self._transformers["to_float"]),
            FieldMapping("address.lng", "address.longitude", self._transformers["to_float"]),
            FieldMapping("bedrooms", "bedrooms", self._transformers["to_int"], required=True),
            FieldMapping("bathrooms", "bathrooms", self._transformers["to_float"]),
            FieldMapping("accommodates", "sleeps", self._transformers["to_int"]),
            FieldMapping("propertyType", "property_type", self._transformers["normalize_property_type"]),
            FieldMapping("publicDescription.summary", "description"),
            FieldMapping("amenities", "_amenities_list"),
            FieldMapping("pictures", "_pictures_list"),
        ]
        
        # ===================
        # OTA AIRBNB
        # ===================
        self._mappings[DataSource.OTA_AIRBNB] = [
            FieldMapping("id", "source_id", str, required=True),
            FieldMapping("name", "name"),
            FieldMapping("address", "address.line1"),
            FieldMapping("city", "address.city", required=True),
            FieldMapping("state", "address.state", self._transformers["normalize_state"], required=True),
            FieldMapping("zipcode", "address.postal_code", self._transformers["normalize_postal"], required=True),
            FieldMapping("lat", "address.latitude", self._transformers["to_float"]),
            FieldMapping("lng", "address.longitude", self._transformers["to_float"]),
            FieldMapping("bedrooms", "bedrooms", self._transformers["to_int"], required=True),
            FieldMapping("bathrooms", "bathrooms", self._transformers["to_float"]),
            FieldMapping("person_capacity", "sleeps", self._transformers["to_int"]),
            FieldMapping("room_type", "property_type", self._transformers["normalize_property_type"]),
            FieldMapping("description", "description"),
            FieldMapping("amenities", "_amenities_list"),
            FieldMapping("photos", "_photos_list"),
        ]
        
        # ===================
        # MARKET DATA AIRDNA
        # ===================
        self._mappings[DataSource.MARKET_AIRDNA] = [
            FieldMapping("property_id", "source_id", str, required=True),
            FieldMapping("adr", "avg_daily_rate", self._transformers["to_decimal"]),
            FieldMapping("occupancy", "avg_occupancy_rate", lambda x: float(x) / 100 if x and float(x) > 1 else float(x) if x else None),
            FieldMapping("revenue", "revpar", self._transformers["to_decimal"]),
            FieldMapping("active_listings", "active_listings", self._transformers["to_int"]),
        ]
    
    def get_mappings(self, source: DataSource) -> List[FieldMapping]:
        """Get field mappings for a source."""
        return self._mappings.get(source, [])
    
    def get_transformer(self, name: str) -> Optional[Callable]:
        """Get a named transformer function."""
        return self._transformers.get(name)
    
    def register_mapping(self, source: DataSource, mappings: List[FieldMapping]):
        """Register or update mappings for a source."""
        self._mappings[source] = mappings


# =============================================================================
# NORMALIZATION RESULT
# =============================================================================

@dataclass
class NormalizationResult:
    """
    Result of a normalization operation.
    
    Contains the normalized entity plus complete audit trail.
    """
    success: bool
    status: NormalizationStatus
    
    # The normalized entity (if successful)
    entity: Optional[Union[CanonicalProperty, CanonicalBooking, CanonicalMarketData]] = None
    entity_type: str = "property"
    
    # Quality metrics
    quality_score: float = 0.0
    quality_level: DataQuality = DataQuality.ACCEPTABLE
    completeness_pct: float = 0.0
    
    # Validation results
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    
    # Transformation audit
    transformations_applied: List[str] = field(default_factory=list)
    fields_mapped: int = 0
    fields_missing: List[str] = field(default_factory=list)
    
    # Source tracking
    source: Optional[DataSource] = None
    source_id: Optional[str] = None
    raw_data_hash: Optional[str] = None
    
    # Timing
    started_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    duration_ms: Optional[int] = None


# =============================================================================
# NORMALIZATION ENGINE
# =============================================================================

class NormalizationEngine:
    """
    The KEYSTONE - Main normalization engine.
    
    Transforms raw data from any source into canonical format.
    
    Pipeline:
    1. INGESTION - Accept raw data, compute hash
    2. MAPPING - Apply field mappings from registry
    3. TRANSFORMATION - Apply transformers
    4. ENRICHMENT - Add derived/computed fields
    5. VALIDATION - Check required fields, ranges, consistency
    6. QUALITY SCORING - Compute quality metrics
    """
    
    def __init__(self):
        self.field_registry = FieldMappingRegistry()
        self._enrichers: List[Callable] = []
        self._validators: List[Callable] = []
        self._setup_default_validators()
    
    def _setup_default_validators(self):
        """Setup default validation functions."""
        self._validators.append(self._validate_required_fields)
        self._validators.append(self._validate_numeric_ranges)
        self._validators.append(self._validate_address)
    
    def normalize_property(
        self,
        raw_data: Dict[str, Any],
        source: DataSource,
        company_id: Optional[UUID] = None,
    ) -> NormalizationResult:
        """
        Normalize property data to canonical format.
        
        This is the main entry point for property normalization.
        """
        result = NormalizationResult(
            success=False,
            status=NormalizationStatus.PENDING,
            entity_type="property",
            source=source,
        )
        
        try:
            # Compute raw data hash for audit
            result.raw_data_hash = hashlib.sha256(
                json.dumps(raw_data, sort_keys=True, default=str).encode()
            ).hexdigest()[:16]
            
            # STEP 1: Get mappings
            result.status = NormalizationStatus.TRANSFORMING
            mappings = self.field_registry.get_mappings(source)
            
            if not mappings:
                result.warnings.append(f"No mappings configured for source: {source}")
            
            # STEP 2: Apply field mappings
            mapped_data, mapping_errors = self._apply_mappings(raw_data, mappings)
            result.errors.extend(mapping_errors)
            result.fields_mapped = len([m for m in mappings if self._get_nested(raw_data, m.source_path) is not None])
            
            # Track transformations
            for m in mappings:
                if m.transformer and self._get_nested(raw_data, m.source_path) is not None:
                    result.transformations_applied.append(f"{m.source_path} -> {m.canonical_path}")
            
            # STEP 3: Post-processing (combine fields, compute derived values)
            mapped_data = self._post_process_property(mapped_data, source)
            
            # STEP 4: Build address
            address_data = self._extract_address_data(mapped_data)
            try:
                address = CanonicalAddress(**address_data)
            except Exception as e:
                result.errors.append(f"Address construction failed: {e}")
                address = None
            
            # STEP 5: Build amenities
            amenities_data = self._extract_amenities_data(mapped_data)
            try:
                amenities = CanonicalAmenities(**amenities_data)
            except Exception as e:
                result.warnings.append(f"Amenities construction failed: {e}")
                amenities = CanonicalAmenities()
            
            # STEP 6: Validate
            result.status = NormalizationStatus.VALIDATING
            for validator in self._validators:
                validator_errors, validator_warnings = validator(mapped_data)
                result.errors.extend(validator_errors)
                result.warnings.extend(validator_warnings)
            
            # STEP 7: Build canonical property
            if address and not any("critical" in e.lower() for e in result.errors):
                try:
                    canonical = CanonicalProperty(
                        source_system=source,
                        source_id=mapped_data.get("source_id", "unknown"),
                        source_url=mapped_data.get("source_url"),
                        name=mapped_data.get("name"),
                        internal_code=mapped_data.get("internal_code"),
                        property_type=mapped_data.get("property_type", PropertyType.OTHER),
                        address=address,
                        bedrooms=mapped_data.get("bedrooms", 0),
                        bathrooms=mapped_data.get("bathrooms", 0.0),
                        sleeps=mapped_data.get("sleeps"),
                        square_footage=mapped_data.get("square_footage"),
                        lot_size_sqft=mapped_data.get("lot_size_sqft"),
                        year_built=mapped_data.get("year_built"),
                        amenities=amenities,
                        description=mapped_data.get("description"),
                        key_features=mapped_data.get("key_features", []),
                        photo_urls=mapped_data.get("photo_urls", []),
                        listed_price=mapped_data.get("listed_price"),
                        owner_name=mapped_data.get("owner_name"),
                        owner_email=mapped_data.get("owner_email"),
                        owner_phone=mapped_data.get("owner_phone"),
                        validation_errors=result.errors,
                        validation_warnings=result.warnings,
                        raw_data_hash=result.raw_data_hash,
                    )
                    
                    # STEP 8: Quality scoring
                    quality_score, quality_level, completeness = self._calculate_quality(canonical)
                    canonical.quality_score = quality_score
                    canonical.quality_level = quality_level
                    canonical.completeness_pct = completeness
                    
                    result.entity = canonical
                    result.success = True
                    result.status = NormalizationStatus.COMPLETED if not result.errors else NormalizationStatus.PARTIAL
                    result.quality_score = quality_score
                    result.quality_level = quality_level
                    result.completeness_pct = completeness
                    result.source_id = canonical.source_id
                    
                except Exception as e:
                    result.errors.append(f"Failed to construct canonical property: {e}")
                    result.status = NormalizationStatus.FAILED
            else:
                result.status = NormalizationStatus.FAILED
            
            result.completed_at = datetime.utcnow()
            result.duration_ms = int((result.completed_at - result.started_at).total_seconds() * 1000)
            
            return result
            
        except Exception as e:
            logger.exception(f"Normalization failed: {e}")
            result.errors.append(f"Unexpected error: {e}")
            result.status = NormalizationStatus.FAILED
            result.completed_at = datetime.utcnow()
            return result
    
    def _apply_mappings(
        self,
        raw_data: Dict[str, Any],
        mappings: List[FieldMapping]
    ) -> Tuple[Dict[str, Any], List[str]]:
        """Apply field mappings to raw data."""
        result = {}
        errors = []
        
        for mapping in mappings:
            # Get source value
            source_value = self._get_nested(raw_data, mapping.source_path)
            
            if source_value is None:
                if mapping.required:
                    errors.append(f"Required field missing: {mapping.source_path}")
                if mapping.default is not None:
                    source_value = mapping.default
                else:
                    continue
            
            # Apply transformer
            if mapping.transformer and source_value is not None:
                try:
                    source_value = mapping.transformer(source_value)
                except Exception as e:
                    errors.append(f"Transform failed for {mapping.source_path}: {e}")
                    continue
            
            # Set in result
            self._set_nested(result, mapping.canonical_path, source_value)
        
        return result, errors
    
    def _post_process_property(self, data: Dict[str, Any], source: DataSource) -> Dict[str, Any]:
        """Post-process mapped data for property-specific logic."""
        # Combine full + half bathrooms if separate
        if "_bathrooms_full" in data or "_bathrooms_half" in data:
            full = data.pop("_bathrooms_full", 0) or 0
            half = data.pop("_bathrooms_half", 0) or 0
            if "bathrooms" not in data or data["bathrooms"] is None:
                data["bathrooms"] = float(full) + (float(half) * 0.5)
        
        # Process amenities list (source-specific)
        if "_amenities_list" in data:
            amenities_list = data.pop("_amenities_list", [])
            if source == DataSource.OTA_AIRBNB:
                data.update(self._parse_airbnb_amenities(amenities_list))
            elif source == DataSource.PMS_GUESTY:
                data.update(self._parse_guesty_amenities(amenities_list))
        
        # Process photos
        if "_pictures_list" in data:
            pictures = data.pop("_pictures_list", [])
            data["photo_urls"] = self._extract_photo_urls(pictures, source)
        
        return data
    
    def _parse_airbnb_amenities(self, amenities: List[str]) -> Dict[str, Any]:
        """Parse Airbnb amenities list to canonical structure."""
        result = {}
        amenities_lower = [a.lower() for a in (amenities or [])]
        
        # Pool detection
        if any("private pool" in a for a in amenities_lower):
            result["amenities.pool_type"] = PoolType.PRIVATE
        elif any("shared pool" in a for a in amenities_lower):
            result["amenities.pool_type"] = PoolType.SHARED
        elif any("pool" in a for a in amenities_lower):
            result["amenities.pool_type"] = PoolType.COMMUNITY
        
        # Hot tub
        if any("hot tub" in a or "jacuzzi" in a for a in amenities_lower):
            result["amenities.hot_tub"] = True
        
        # Beach
        if any("beachfront" in a or "beach access" in a for a in amenities_lower):
            result["amenities.beach_access_type"] = BeachAccessType.PRIVATE if "private" in str(amenities_lower) else BeachAccessType.PUBLIC_NEARBY
        
        # Basics
        result["amenities.wifi"] = any("wifi" in a or "internet" in a for a in amenities_lower)
        result["amenities.ac"] = any("air conditioning" in a or "a/c" in a for a in amenities_lower)
        result["amenities.washer"] = any("washer" in a for a in amenities_lower)
        result["amenities.dryer"] = any("dryer" in a for a in amenities_lower)
        result["amenities.pet_friendly"] = any("pet" in a for a in amenities_lower)
        
        return result
    
    def _parse_guesty_amenities(self, amenities: List[Any]) -> Dict[str, Any]:
        """Parse Guesty amenities to canonical structure."""
        # Guesty uses structured amenities, handle accordingly
        result = {}
        # Implementation depends on Guesty's exact format
        return result
    
    def _extract_photo_urls(self, photos: List[Any], source: DataSource) -> List[str]:
        """Extract photo URLs from various formats."""
        urls = []
        for photo in (photos or []):
            if isinstance(photo, str):
                urls.append(photo)
            elif isinstance(photo, dict):
                url = photo.get("url") or photo.get("original") or photo.get("large") or photo.get("thumbnail")
                if url:
                    urls.append(url)
        return urls
    
    def _extract_address_data(self, mapped_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract address fields from mapped data."""
        address_fields = [
            "line1", "line2", "city", "state", "postal_code", "country",
            "street_number", "street_name", "street_suffix", "unit_number",
            "latitude", "longitude"
        ]
        
        result = {}
        for field in address_fields:
            key = f"address.{field}"
            if key in mapped_data:
                result[field] = mapped_data[key]
            elif f"address" in mapped_data and isinstance(mapped_data["address"], dict):
                if field in mapped_data["address"]:
                    result[field] = mapped_data["address"][field]
        
        # Build line1 from components if not present
        if "line1" not in result or not result["line1"]:
            parts = []
            if result.get("street_number"):
                parts.append(str(result["street_number"]))
            if result.get("street_name"):
                parts.append(result["street_name"])
            if result.get("street_suffix"):
                parts.append(result["street_suffix"])
            if parts:
                result["line1"] = " ".join(parts)
        
        return result
    
    def _extract_amenities_data(self, mapped_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract amenities fields from mapped data."""
        result = {}
        
        # Extract all amenities.* fields
        for key, value in mapped_data.items():
            if key.startswith("amenities."):
                field = key.replace("amenities.", "")
                result[field] = value
        
        return result
    
    def _validate_required_fields(self, data: Dict[str, Any]) -> Tuple[List[str], List[str]]:
        """Validate required fields are present."""
        errors = []
        warnings = []
        
        required = ["source_id", "bedrooms"]
        address_required = ["city", "state", "postal_code"]
        
        for field in required:
            if field not in data or data[field] is None:
                errors.append(f"Missing required field: {field}")
        
        for field in address_required:
            key = f"address.{field}"
            if key not in data or data[key] is None:
                errors.append(f"Missing required address field: {field}")
        
        return errors, warnings
    
    def _validate_numeric_ranges(self, data: Dict[str, Any]) -> Tuple[List[str], List[str]]:
        """Validate numeric fields are in reasonable ranges."""
        errors = []
        warnings = []
        
        bedrooms = data.get("bedrooms")
        if bedrooms is not None:
            if bedrooms < 0:
                errors.append(f"Invalid bedrooms: {bedrooms} (negative)")
            elif bedrooms > 20:
                warnings.append(f"Unusual bedroom count: {bedrooms}")
        
        bathrooms = data.get("bathrooms")
        if bathrooms is not None:
            if bathrooms < 0:
                errors.append(f"Invalid bathrooms: {bathrooms} (negative)")
            elif bathrooms > 20:
                warnings.append(f"Unusual bathroom count: {bathrooms}")
        
        sqft = data.get("square_footage")
        if sqft is not None:
            if sqft < 100:
                warnings.append(f"Very small square footage: {sqft}")
            elif sqft > 50000:
                warnings.append(f"Very large square footage: {sqft}")
        
        year = data.get("year_built")
        if year is not None:
            current_year = datetime.now().year
            if year < 1800 or year > current_year + 5:
                warnings.append(f"Suspicious year built: {year}")
        
        return errors, warnings
    
    def _validate_address(self, data: Dict[str, Any]) -> Tuple[List[str], List[str]]:
        """Validate address completeness and format."""
        errors = []
        warnings = []
        
        state = data.get("address.state", "")
        if state and len(state) != 2:
            warnings.append(f"State should be 2-letter code: {state}")
        
        postal = data.get("address.postal_code", "")
        if postal and not re.match(r'^\d{5}(-\d{4})?$', postal):
            warnings.append(f"Unusual postal code format: {postal}")
        
        return errors, warnings
    
    def _calculate_quality(self, entity: CanonicalProperty) -> Tuple[float, DataQuality, float]:
        """Calculate quality metrics for normalized entity."""
        # Count filled fields
        total_fields = 0
        filled_fields = 0
        
        # Core fields (weighted higher)
        core_fields = [
            ("source_id", 1.0),
            ("bedrooms", 1.0),
            ("bathrooms", 0.8),
            ("address", 1.0),
            ("square_footage", 0.5),
            ("property_type", 0.3),
        ]
        
        for field, weight in core_fields:
            total_fields += weight
            value = getattr(entity, field, None)
            if value is not None:
                if field == "address":
                    # Check address completeness
                    addr = value
                    if addr.line1 and addr.city and addr.state and addr.postal_code:
                        filled_fields += weight
                        if addr.latitude and addr.longitude:
                            filled_fields += 0.2  # Bonus for geocoding
                else:
                    filled_fields += weight
        
        # Optional but valuable fields
        optional_fields = [
            ("description", 0.3),
            ("photo_urls", 0.3),
            ("year_built", 0.2),
            ("sleeps", 0.2),
        ]
        
        for field, weight in optional_fields:
            total_fields += weight
            value = getattr(entity, field, None)
            if value:
                if isinstance(value, list) and len(value) > 0:
                    filled_fields += weight
                elif not isinstance(value, list):
                    filled_fields += weight
        
        completeness = (filled_fields / total_fields) * 100 if total_fields > 0 else 0
        
        # Penalize for errors
        error_penalty = len(entity.validation_errors) * 0.1
        warning_penalty = len(entity.validation_warnings) * 0.02
        
        quality_score = max(0, (filled_fields / total_fields) - error_penalty - warning_penalty)
        
        # Determine quality level
        if quality_score >= 0.9 and not entity.validation_errors:
            quality_level = DataQuality.EXCELLENT
        elif quality_score >= 0.7:
            quality_level = DataQuality.GOOD
        elif quality_score >= 0.5:
            quality_level = DataQuality.ACCEPTABLE
        elif quality_score >= 0.3:
            quality_level = DataQuality.POOR
        else:
            quality_level = DataQuality.UNUSABLE
        
        return round(quality_score, 3), quality_level, round(completeness, 1)
    
    @staticmethod
    def _get_nested(data: Dict[str, Any], path: str) -> Any:
        """Get nested value using dot notation."""
        keys = path.split(".")
        value = data
        for key in keys:
            if isinstance(value, dict):
                value = value.get(key)
            else:
                return None
            if value is None:
                return None
        return value
    
    @staticmethod
    def _set_nested(data: Dict[str, Any], path: str, value: Any):
        """Set nested value using dot notation."""
        keys = path.split(".")
        for key in keys[:-1]:
            if key not in data:
                data[key] = {}
            data = data[key]
        data[keys[-1]] = value


# =============================================================================
# NORMALIZATION SERVICE
# =============================================================================

class NormalizationService:
    """
    High-level service for batch normalization operations.
    """
    
    def __init__(self):
        self.engine = NormalizationEngine()
    
    async def normalize_batch(
        self,
        records: List[Dict[str, Any]],
        source: DataSource,
        company_id: UUID,
    ) -> List[NormalizationResult]:
        """Normalize a batch of records."""
        results = []
        for record in records:
            result = self.engine.normalize_property(record, source, company_id)
            results.append(result)
        
        # Log batch summary
        successful = sum(1 for r in results if r.success)
        logger.info(
            f"Batch normalization complete: {successful}/{len(records)} successful",
            extra={
                "source": source.value,
                "company_id": str(company_id),
                "total": len(records),
                "successful": successful,
            }
        )
        
        return results
    
    def get_supported_sources(self) -> List[DataSource]:
        """Get list of sources with configured mappings."""
        return [
            source for source in DataSource
            if self.engine.field_registry.get_mappings(source)
        ]
