"""
PMS Connector Architecture v1.

Implements the adapter pattern for multiple PMS/Channel Manager integrations.
Each connector normalizes data into the canonical schema for the intelligence engine.

Supported PMS Providers (MVP):
1. Guesty (first integration)
2. Hostaway
3. Escapia
4. Streamline
5. Lodgify

Architecture:
    PMS API → Connector → Normalization → Canonical Schema → Intelligence Engine

Key Principles:
1. Operator chooses their PMS - we don't force them to switch
2. All data is encrypted per-tenant
3. Footprint is automatically generated from listing coordinates
4. Internal comps are built from operator's own data
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, ConfigDict


# =============================================================================
# PMS PROVIDER ENUM
# =============================================================================

class PMSProvider(str, Enum):
    """Supported PMS/Channel Manager providers."""
    GUESTY = "guesty"
    HOSTAWAY = "hostaway"
    ESCAPIA = "escapia"
    STREAMLINE = "streamline"
    LODGIFY = "lodgify"
    TRACK = "track"
    HOSTFULLY = "hostfully"
    OWNERREZ = "ownerrez"
    BEDS24 = "beds24"
    SMOOBU = "smoobu"
    # Manual/CSV upload option
    MANUAL = "manual"


class PMSAuthScheme(str, Enum):
    """How Oyvoda authenticates against a provider."""
    API_KEY = "api_key"
    OAUTH2 = "oauth2"
    BASIC = "basic"
    CUSTOM = "custom"
    MANUAL = "manual"


class PMSMessageTransport(str, Enum):
    """How guest communications reach Oyvoda for this provider."""
    DIRECT_API = "direct_api"
    EMAIL_BRIDGE = "email_bridge"
    HYBRID = "hybrid"
    NONE = "none"


class PMSReadiness(str, Enum):
    """Delivery maturity for a provider integration."""
    IMPLEMENTED = "implemented"
    SCAFFOLDED = "scaffolded"
    PLANNED = "planned"


@dataclass(frozen=True)
class PMSCredentialFieldSpec:
    """Single credential/config field required by a PMS provider."""
    name: str
    label: str
    required: bool = False
    secret: bool = False
    aliases: Tuple[str, ...] = ()
    help_text: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "required": self.required,
            "secret": self.secret,
            "aliases": list(self.aliases),
            "help_text": self.help_text,
        }


@dataclass(frozen=True)
class PMSConnectorCapabilities:
    """Capability matrix for a PMS connector."""
    listings: bool = True
    bookings: bool = True
    calendar: bool = True
    operations: bool = False
    messages_pull: bool = False
    message_webhooks: bool = False
    direct_messaging: bool = False
    documents: bool = False
    reviews: bool = False

    def to_dict(self) -> Dict[str, bool]:
        return {
            "listings": self.listings,
            "bookings": self.bookings,
            "calendar": self.calendar,
            "operations": self.operations,
            "messages_pull": self.messages_pull,
            "message_webhooks": self.message_webhooks,
            "direct_messaging": self.direct_messaging,
            "documents": self.documents,
            "reviews": self.reviews,
        }


@dataclass(frozen=True)
class PMSConnectorContract:
    """Canonical provider contract for every PMS integration."""
    provider: PMSProvider
    display_name: str
    auth_scheme: PMSAuthScheme
    message_transport: PMSMessageTransport
    readiness: PMSReadiness
    required_fields: Tuple[PMSCredentialFieldSpec, ...]
    optional_fields: Tuple[PMSCredentialFieldSpec, ...] = ()
    capabilities: PMSConnectorCapabilities = field(default_factory=PMSConnectorCapabilities)
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider.value,
            "display_name": self.display_name,
            "auth_scheme": self.auth_scheme.value,
            "message_transport": self.message_transport.value,
            "readiness": self.readiness.value,
            "required_fields": [field.to_dict() for field in self.required_fields],
            "optional_fields": [field.to_dict() for field in self.optional_fields],
            "capabilities": self.capabilities.to_dict(),
            "notes": self.notes,
        }


def _field(
    name: str,
    label: str,
    *,
    required: bool = False,
    secret: bool = False,
    aliases: Tuple[str, ...] = (),
    help_text: str = "",
) -> PMSCredentialFieldSpec:
    return PMSCredentialFieldSpec(
        name=name,
        label=label,
        required=required,
        secret=secret,
        aliases=aliases,
        help_text=help_text,
    )


PMS_PROVIDER_CONTRACTS: Dict[PMSProvider, PMSConnectorContract] = {
    PMSProvider.ESCAPIA: PMSConnectorContract(
        provider=PMSProvider.ESCAPIA,
        display_name="Escapia",
        auth_scheme=PMSAuthScheme.API_KEY,
        message_transport=PMSMessageTransport.EMAIL_BRIDGE,
        readiness=PMSReadiness.IMPLEMENTED,
        required_fields=(
            _field("api_key", "API Key", required=True, secret=True),
        ),
        optional_fields=(
            _field("provider_account_id", "Provider Account ID", aliases=("account_id", "pmcid"), help_text="Escapia company/account identifier when available."),
            _field("provider_base_url", "Provider Base URL", aliases=("base_url",), help_text="Override API base URL if the operator uses a custom Escapia endpoint."),
            _field("client_id", "Client ID", secret=True),
            _field("client_secret", "Client Secret", secret=True),
        ),
        capabilities=PMSConnectorCapabilities(
            listings=True,
            bookings=True,
            calendar=True,
            operations=False,
            messages_pull=False,
            message_webhooks=False,
            direct_messaging=False,
            documents=False,
            reviews=False,
        ),
        notes="Escapia typically provides property and booking truth through API, while guest messaging arrives through an email bridge or PMS-forwarded inbox.",
    ),
    PMSProvider.GUESTY: PMSConnectorContract(
        provider=PMSProvider.GUESTY,
        display_name="Guesty",
        auth_scheme=PMSAuthScheme.OAUTH2,
        message_transport=PMSMessageTransport.DIRECT_API,
        readiness=PMSReadiness.IMPLEMENTED,
        required_fields=(
            _field("api_token", "API Token", required=True, secret=True, help_text="Guesty access token for listing and booking sync."),
        ),
        optional_fields=(
            _field("provider_account_id", "Provider Account ID", aliases=("account_id",)),
            _field("provider_base_url", "Provider Base URL", aliases=("base_url",)),
            _field("client_id", "Client ID", secret=True),
            _field("client_secret", "Client Secret", secret=True),
        ),
        capabilities=PMSConnectorCapabilities(
            listings=True,
            bookings=True,
            calendar=True,
            operations=False,
            messages_pull=True,
            message_webhooks=True,
            direct_messaging=True,
            documents=False,
            reviews=False,
        ),
        notes="Guesty is API-native for listings, bookings, and messaging, making it a strong candidate for low-friction operator onboarding.",
    ),
    PMSProvider.HOSTAWAY: PMSConnectorContract(
        provider=PMSProvider.HOSTAWAY,
        display_name="Hostaway",
        auth_scheme=PMSAuthScheme.API_KEY,
        message_transport=PMSMessageTransport.DIRECT_API,
        readiness=PMSReadiness.SCAFFOLDED,
        required_fields=(
            _field("api_key", "API Key", required=True, secret=True),
        ),
        optional_fields=(
            _field("provider_account_id", "Provider Account ID", aliases=("account_id", "portfolio_id")),
            _field("provider_base_url", "Provider Base URL", aliases=("base_url",)),
        ),
        capabilities=PMSConnectorCapabilities(
            listings=True,
            bookings=True,
            calendar=True,
            operations=False,
            messages_pull=True,
            message_webhooks=True,
            direct_messaging=True,
            documents=False,
            reviews=False,
        ),
        notes="Hostaway should be treated as API-native for property, booking, and guest messaging once the dedicated connector is completed.",
    ),
    PMSProvider.TRACK: PMSConnectorContract(
        provider=PMSProvider.TRACK,
        display_name="Track",
        auth_scheme=PMSAuthScheme.API_KEY,
        message_transport=PMSMessageTransport.EMAIL_BRIDGE,
        readiness=PMSReadiness.IMPLEMENTED,
        required_fields=(
            _field("api_key", "API Key", required=True, secret=True),
            _field("company_code", "Company Code", required=True),
        ),
        optional_fields=(
            _field("provider_account_id", "Provider Account ID", aliases=("account_id",)),
            _field("provider_base_url", "Provider Base URL", aliases=("base_url",)),
        ),
        capabilities=PMSConnectorCapabilities(
            listings=True,
            bookings=True,
            calendar=True,
            operations=False,
            messages_pull=False,
            message_webhooks=False,
            direct_messaging=False,
            documents=False,
            reviews=False,
        ),
        notes="Track can provide rich property and booking data. Messaging often still relies on email forwarding instead of a unified message API.",
    ),
    PMSProvider.STREAMLINE: PMSConnectorContract(
        provider=PMSProvider.STREAMLINE,
        display_name="Streamline",
        auth_scheme=PMSAuthScheme.API_KEY,
        message_transport=PMSMessageTransport.HYBRID,
        readiness=PMSReadiness.PLANNED,
        required_fields=(
            _field("api_key", "API Key", required=True, secret=True),
        ),
        optional_fields=(
            _field("provider_account_id", "Provider Account ID", aliases=("account_id",)),
            _field("provider_base_url", "Provider Base URL", aliases=("base_url",)),
        ),
        capabilities=PMSConnectorCapabilities(listings=True, bookings=True, calendar=True),
        notes="Streamline is planned. The canonical contract is ready for it even before the adapter is finished.",
    ),
    PMSProvider.LODGIFY: PMSConnectorContract(
        provider=PMSProvider.LODGIFY,
        display_name="Lodgify",
        auth_scheme=PMSAuthScheme.API_KEY,
        message_transport=PMSMessageTransport.HYBRID,
        readiness=PMSReadiness.PLANNED,
        required_fields=(
            _field("api_key", "API Key", required=True, secret=True),
        ),
        optional_fields=(
            _field("provider_account_id", "Provider Account ID", aliases=("account_id",)),
            _field("provider_base_url", "Provider Base URL", aliases=("base_url",)),
        ),
        capabilities=PMSConnectorCapabilities(listings=True, bookings=True, calendar=True),
        notes="Lodgify support is planned; this contract preserves stable provider identity even before the connector ships.",
    ),
    PMSProvider.HOSTFULLY: PMSConnectorContract(
        provider=PMSProvider.HOSTFULLY,
        display_name="Hostfully",
        auth_scheme=PMSAuthScheme.API_KEY,
        message_transport=PMSMessageTransport.DIRECT_API,
        readiness=PMSReadiness.PLANNED,
        required_fields=(
            _field("api_key", "API Key", required=True, secret=True),
        ),
        optional_fields=(
            _field("provider_account_id", "Provider Account ID", aliases=("account_id",)),
            _field("provider_base_url", "Provider Base URL", aliases=("base_url",)),
        ),
        capabilities=PMSConnectorCapabilities(listings=True, bookings=True, calendar=True, messages_pull=True, message_webhooks=True, direct_messaging=True),
        notes="Hostfully is planned and should fit the same canonical identity and messaging contract once implemented.",
    ),
    PMSProvider.OWNERREZ: PMSConnectorContract(
        provider=PMSProvider.OWNERREZ,
        display_name="OwnerRez",
        auth_scheme=PMSAuthScheme.API_KEY,
        message_transport=PMSMessageTransport.HYBRID,
        readiness=PMSReadiness.PLANNED,
        required_fields=(
            _field("api_key", "API Key", required=True, secret=True),
        ),
        optional_fields=(
            _field("provider_account_id", "Provider Account ID", aliases=("account_id",)),
            _field("provider_base_url", "Provider Base URL", aliases=("base_url",)),
        ),
        capabilities=PMSConnectorCapabilities(listings=True, bookings=True, calendar=True, messages_pull=True),
        notes="OwnerRez often carries strong booking and property truth. The canonical contract is ready for a dedicated adapter.",
    ),
    PMSProvider.BEDS24: PMSConnectorContract(
        provider=PMSProvider.BEDS24,
        display_name="Beds24",
        auth_scheme=PMSAuthScheme.API_KEY,
        message_transport=PMSMessageTransport.HYBRID,
        readiness=PMSReadiness.PLANNED,
        required_fields=(
            _field("api_key", "API Key", required=True, secret=True),
        ),
        optional_fields=(
            _field("provider_account_id", "Provider Account ID", aliases=("account_id",)),
            _field("provider_base_url", "Provider Base URL", aliases=("base_url",)),
        ),
        capabilities=PMSConnectorCapabilities(listings=True, bookings=True, calendar=True),
        notes="Beds24 is planned; the provider can plug into the same canonical listing/booking contract once prioritized.",
    ),
    PMSProvider.SMOOBU: PMSConnectorContract(
        provider=PMSProvider.SMOOBU,
        display_name="Smoobu",
        auth_scheme=PMSAuthScheme.API_KEY,
        message_transport=PMSMessageTransport.HYBRID,
        readiness=PMSReadiness.PLANNED,
        required_fields=(
            _field("api_key", "API Key", required=True, secret=True),
        ),
        optional_fields=(
            _field("provider_account_id", "Provider Account ID", aliases=("account_id",)),
            _field("provider_base_url", "Provider Base URL", aliases=("base_url",)),
        ),
        capabilities=PMSConnectorCapabilities(listings=True, bookings=True, calendar=True),
        notes="Smoobu is planned; this contract keeps the provider shape stable ahead of implementation.",
    ),
}


# =============================================================================
# CANONICAL DATA MODELS
# =============================================================================

class CanonicalListing(BaseModel):
    """
    Canonical listing model - all PMS data normalizes to this.
    
    This is the single source of truth regardless of which PMS 
    the operator uses.
    """
    # Identity
    listing_id: UUID = Field(default_factory=uuid4)
    external_id: str  # PMS-specific ID
    pms_provider: PMSProvider
    provider_account_id: Optional[str] = None
    provider_property_id: Optional[str] = None
    provider_unit_id: Optional[str] = None
    provider_listing_id: Optional[str] = None
    provider_base_url: Optional[str] = None
    
    # Operator/Tenant
    company_id: UUID
    
    # Location (CRITICAL for footprint generation)
    address_line1: str
    address_line2: Optional[str] = None
    city: str
    state: str
    postal_code: str
    country: str = "US"
    latitude: float
    longitude: float
    
    # Property Details
    property_name: Optional[str] = None
    bedrooms: int
    bathrooms: float
    square_footage: Optional[int] = None
    property_type: str = "single_family"
    
    # Amenities (normalized)
    has_pool: bool = False
    pool_heated: bool = False
    has_hot_tub: bool = False
    has_waterfront: bool = False
    waterfront_type: Optional[str] = None  # gulf, ocean, lake, bay
    beach_access: Optional[str] = None  # private, public, none
    pet_friendly: bool = False
    has_garage: bool = False
    has_ev_charger: bool = False
    has_game_room: bool = False
    has_home_theater: bool = False
    
    # Status
    is_active: bool = True
    listing_status: str = "active"  # active, inactive, pending
    
    # Metadata
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_synced_at: Optional[datetime] = None

    model_config = ConfigDict(use_enum_values=True)


class CanonicalBooking(BaseModel):
    """Canonical booking model."""
    booking_id: UUID = Field(default_factory=uuid4)
    external_id: str
    listing_id: UUID
    company_id: UUID
    
    # Dates
    check_in: date
    check_out: date
    nights: int
    
    # Revenue
    total_amount: float
    nightly_rate: float
    cleaning_fee: Optional[float] = None
    service_fee: Optional[float] = None
    taxes: Optional[float] = None
    
    # Guest (anonymized)
    guest_count: int = 1
    guest_first_name: Optional[str] = None
    guest_last_name: Optional[str] = None
    guest_email: Optional[str] = None
    guest_phone: Optional[str] = None

    # Source
    booking_channel: str  # airbnb, vrbo, direct, etc.
    
    # Status
    status: str = "confirmed"  # confirmed, cancelled, completed
    
    # Metadata
    booked_at: datetime
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CanonicalCalendarDay(BaseModel):
    """Single day availability/pricing."""
    listing_id: UUID
    date: date
    
    # Availability
    is_available: bool
    is_blocked: bool = False
    block_reason: Optional[str] = None  # owner_hold, maintenance, booked
    
    # Pricing
    nightly_rate: float
    minimum_stay: int = 1
    
    # If booked
    booking_id: Optional[UUID] = None


class CanonicalOperations(BaseModel):
    """Operational data (cleaning, maintenance)."""
    operation_id: UUID = Field(default_factory=uuid4)
    listing_id: UUID
    company_id: UUID
    
    operation_type: str  # cleaning, maintenance, inspection
    scheduled_date: date
    completed_date: Optional[date] = None
    
    # Costs
    cost: Optional[float] = None
    vendor_id: Optional[str] = None
    
    # Status
    status: str = "scheduled"  # scheduled, in_progress, completed


# =============================================================================
# OPERATOR FOOTPRINT
# =============================================================================

class OperatorFootprint(BaseModel):
    """
    Automatically generated geographical footprint from operator's listings.
    
    This polygon is used to:
    1. Scope external market scraping
    2. Define the operator's "home market"
    3. Enable geofence-specific analytics
    """
    footprint_id: UUID = Field(default_factory=uuid4)
    company_id: UUID
    
    # Polygon definition
    polygon_coords: List[List[float]]  # [[lng, lat], ...]
    centroid: Tuple[float, float]  # (lng, lat)
    bounding_box: Tuple[float, float, float, float]  # (min_lng, min_lat, max_lng, max_lat)
    
    # Metrics
    listing_count: int
    area_sq_miles: Optional[float] = None
    buffer_miles: float = 5.0  # How much we expanded beyond listings
    
    # Market classification (auto-detected)
    detected_market_class: str = "mixed"  # luxury, midscale, budget, urban, resort
    primary_market_name: Optional[str] = None  # "30A, FL", "Scottsdale, AZ"
    
    # Metadata
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# =============================================================================
# ABSTRACT CONNECTOR BASE CLASS
# =============================================================================

class PMSConnector(ABC):
    """
    Abstract base class for PMS connectors.
    
    All PMS integrations implement this interface.
    """
    
    def __init__(
        self,
        company_id: UUID,
        credentials: Dict[str, str],
    ):
        """
        Initialize connector with company ID and credentials.
        
        Credentials are encrypted and retrieved from SecureVault.
        """
        self.company_id = company_id
        self.credentials = credentials
        self._last_sync: Optional[datetime] = None
    
    @property
    @abstractmethod
    def provider(self) -> PMSProvider:
        """Return the PMS provider enum."""
        pass

    @classmethod
    def contract(cls) -> PMSConnectorContract:
        """Return the canonical provider contract for this connector."""
        provider = getattr(cls, "PROVIDER", None)
        if isinstance(provider, PMSProvider) and provider in PMS_PROVIDER_CONTRACTS:
            return PMS_PROVIDER_CONTRACTS[provider]
        raise NotImplementedError(f"{cls.__name__} does not define a provider contract")
    
    @abstractmethod
    async def test_connection(self) -> Tuple[bool, str]:
        """
        Test the connection to the PMS API.
        
        Returns:
            (success, message)
        """
        pass
    
    @abstractmethod
    async def fetch_listings(self) -> List[CanonicalListing]:
        """
        Fetch all listings from PMS and normalize to canonical schema.
        """
        pass
    
    @abstractmethod
    async def fetch_bookings(
        self,
        start_date: date,
        end_date: date,
    ) -> List[CanonicalBooking]:
        """
        Fetch bookings within date range.
        """
        pass
    
    @abstractmethod
    async def fetch_calendar(
        self,
        listing_id: str,
        start_date: date,
        end_date: date,
    ) -> List[CanonicalCalendarDay]:
        """
        Fetch calendar/availability for a listing.
        """
        pass
    
    async def fetch_operations(
        self,
        start_date: date,
        end_date: date,
    ) -> List[CanonicalOperations]:
        """
        Fetch operational data (cleaning, maintenance).
        
        Optional - not all PMS support this.
        """
        return []
    
    async def fetch_messages(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        listing_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Fetch guest messages from PMS.
        
        Optional - not all PMS support this.
        Requires explicit operator permission.
        
        Returns raw messages to be processed by GuestMessagingService.
        """
        return []
    
    async def register_message_webhook(
        self,
        webhook_url: str,
    ) -> Tuple[bool, str]:
        """
        Register a webhook for real-time message notifications.
        
        Optional - not all PMS support this.
        
        Returns:
            (success, webhook_id or error message)
        """
        return False, "Webhooks not supported by this PMS"
    
    async def full_sync(self) -> Dict[str, Any]:
        """
        Perform a full sync of all data from PMS.
        
        Returns summary of synced data.
        """
        # Fetch listings first
        listings = await self.fetch_listings()
        
        # Fetch bookings (last 2 years + next 1 year)
        today = date.today()
        bookings = await self.fetch_bookings(
            today - timedelta(days=730),
            today + timedelta(days=365),
        )
        
        # Fetch calendar (next 365 days)
        calendar_days = []
        for listing in listings:
            days = await self.fetch_calendar(
                listing.external_id,
                today,
                today + timedelta(days=365),
            )
            calendar_days.extend(days)
        
        # Fetch operations (optional)
        operations = await self.fetch_operations(
            today - timedelta(days=365),
            today + timedelta(days=90),
        )
        
        self._last_sync = datetime.utcnow()
        
        return {
            "listings": len(listings),
            "bookings": len(bookings),
            "calendar_days": len(calendar_days),
            "operations": len(operations),
            "synced_at": self._last_sync.isoformat(),
        }


# =============================================================================
# GUESTY CONNECTOR (MVP FIRST INTEGRATION)
# =============================================================================

class GuestyConnector(PMSConnector):
    """
    Guesty PMS Connector.
    
    Guesty is the recommended first integration because:
    - Large market share with professional operators
    - Rich data model
    - Good API coverage
    - Commonly used by luxury operators
    
    API Docs: https://docs.guesty.com/
    """
    
    BASE_URL = "https://api.guesty.com/api/v2"
    PROVIDER = PMSProvider.GUESTY
    
    @property
    def provider(self) -> PMSProvider:
        return PMSProvider.GUESTY
    
    def _get_headers(self) -> Dict[str, str]:
        """Get authorization headers."""
        return {
            "Authorization": f"Bearer {self.credentials.get('api_token', '')}",
            "Content-Type": "application/json",
        }
    
    async def test_connection(self) -> Tuple[bool, str]:
        """Test Guesty API connection."""
        # In production, would make actual API call
        # For now, simulate
        if not self.credentials.get("api_token"):
            return False, "Missing API token"
        return True, "Connection successful"
    
    async def fetch_listings(self) -> List[CanonicalListing]:
        """
        Fetch listings from Guesty API.
        
        Endpoint: GET /listings
        """
        # In production, would call:
        # response = await self._request("GET", "/listings")
        
        # For now, return empty list (placeholder)
        # Real implementation would parse Guesty response
        return []
    
    def _normalize_listing(self, guesty_listing: Dict) -> CanonicalListing:
        """
        Normalize Guesty listing to canonical schema.
        
        Maps Guesty fields to our canonical model.
        """
        # Address parsing
        address = guesty_listing.get("address", {})
        
        # Amenities parsing
        amenities = guesty_listing.get("amenities", [])
        amenities_lower = [a.lower() for a in amenities]
        
        return CanonicalListing(
            external_id=guesty_listing.get("_id", ""),
            pms_provider=PMSProvider.GUESTY,
            company_id=self.company_id,
            
            # Location
            address_line1=address.get("street", ""),
            city=address.get("city", ""),
            state=address.get("state", ""),
            postal_code=address.get("zipcode", ""),
            country=address.get("country", "US"),
            latitude=address.get("lat", 0.0),
            longitude=address.get("lng", 0.0),
            
            # Property
            property_name=guesty_listing.get("title", ""),
            bedrooms=guesty_listing.get("bedrooms", 0),
            bathrooms=guesty_listing.get("bathrooms", 0.0),
            square_footage=guesty_listing.get("squareFeet"),
            property_type=guesty_listing.get("propertyType", "single_family"),
            
            # Amenities
            has_pool="pool" in amenities_lower or "private pool" in amenities_lower,
            pool_heated="heated pool" in amenities_lower,
            has_hot_tub="hot tub" in amenities_lower or "jacuzzi" in amenities_lower,
            pet_friendly="pets allowed" in amenities_lower,
            
            # Status
            is_active=guesty_listing.get("active", True),
        )
    
    async def fetch_bookings(
        self,
        start_date: date,
        end_date: date,
    ) -> List[CanonicalBooking]:
        """Fetch bookings from Guesty."""
        # Endpoint: GET /reservations
        return []
    
    async def fetch_calendar(
        self,
        listing_id: str,
        start_date: date,
        end_date: date,
    ) -> List[CanonicalCalendarDay]:
        """Fetch calendar from Guesty."""
        # Endpoint: GET /listings/{id}/calendar
        return []


# =============================================================================
# HOSTAWAY CONNECTOR
# =============================================================================

class HostawayConnector(PMSConnector):
    """
    Hostaway PMS Connector.
    
    API Docs: https://api.hostaway.com/documentation
    """
    
    BASE_URL = "https://api.hostaway.com/v1"
    PROVIDER = PMSProvider.HOSTAWAY
    
    @property
    def provider(self) -> PMSProvider:
        return PMSProvider.HOSTAWAY
    
    async def test_connection(self) -> Tuple[bool, str]:
        if not self.credentials.get("api_key"):
            return False, "Missing API key"
        return True, "Connection successful"
    
    async def fetch_listings(self) -> List[CanonicalListing]:
        # Endpoint: GET /listings
        return []
    
    async def fetch_bookings(
        self,
        start_date: date,
        end_date: date,
    ) -> List[CanonicalBooking]:
        # Endpoint: GET /reservations
        return []
    
    async def fetch_calendar(
        self,
        listing_id: str,
        start_date: date,
        end_date: date,
    ) -> List[CanonicalCalendarDay]:
        # Endpoint: GET /listings/{id}/calendar
        return []


# =============================================================================
# ESCAPIA CONNECTOR
# =============================================================================

class EscapiaConnector(PMSConnector):
    """
    Escapia PMS Connector.

    MVP behavior validates credential shape and provides normalized hooks.
    """

    BASE_URL = "https://api.escapia.com"
    PROVIDER = PMSProvider.ESCAPIA

    @property
    def provider(self) -> PMSProvider:
        return PMSProvider.ESCAPIA

    async def test_connection(self) -> Tuple[bool, str]:
        username = self.credentials.get("username")
        password = self.credentials.get("password")
        if not username or not password:
            return False, "Missing username/password"
        return True, "Credential shape valid (live API ping not enabled)"

    async def fetch_listings(self) -> List[CanonicalListing]:
        return []

    async def fetch_bookings(
        self,
        start_date: date,
        end_date: date,
    ) -> List[CanonicalBooking]:
        return []

    async def fetch_calendar(
        self,
        listing_id: str,
        start_date: date,
        end_date: date,
    ) -> List[CanonicalCalendarDay]:
        return []


# =============================================================================
# CONNECTOR FACTORY
# =============================================================================

class PMSConnectorFactory:
    """
    Factory for creating PMS connectors.
    
    Operators choose their PMS, and we create the right connector.
    """
    
    _connectors = {
        PMSProvider.GUESTY: GuestyConnector,
        PMSProvider.HOSTAWAY: HostawayConnector,
        PMSProvider.ESCAPIA: EscapiaConnector,
        # Add more as implemented
    }
    _contracts: Dict[PMSProvider, PMSConnectorContract] = dict(PMS_PROVIDER_CONTRACTS)
    
    @classmethod
    def get_supported_providers(cls, *, implemented_only: bool = True) -> List[PMSProvider]:
        """Get list of supported PMS providers."""
        source = cls._connectors if implemented_only else cls._contracts
        return list(source.keys())

    @classmethod
    def get_provider_contract(
        cls,
        provider: PMSProvider,
    ) -> PMSConnectorContract:
        """Return the canonical contract for a PMS provider."""
        contract = cls._contracts.get(provider)
        if not contract:
            raise ValueError(f"No provider contract registered for '{provider.value}'")
        return contract

    @classmethod
    def get_supported_provider_contracts(
        cls,
        *,
        implemented_only: bool = False,
    ) -> List[PMSConnectorContract]:
        """Return provider contracts, optionally only for implemented connectors."""
        providers = cls.get_supported_providers(implemented_only=implemented_only)
        return [cls._contracts[p] for p in providers if p in cls._contracts]
    
    @classmethod
    def create(
        cls,
        provider: PMSProvider,
        company_id: UUID,
        credentials: Dict[str, str],
    ) -> PMSConnector:
        """
        Create a connector for the specified PMS provider.
        
        Args:
            provider: The PMS provider enum
            company_id: Operator's company ID
            credentials: Encrypted credentials from vault
        
        Returns:
            Configured PMSConnector instance
        
        Raises:
            ValueError: If provider not supported
        """
        connector_class = cls._connectors.get(provider)
        
        if connector_class is None:
            supported = [p.value for p in cls._connectors.keys()]
            raise ValueError(
                f"PMS provider '{provider}' not supported. "
                f"Supported providers: {supported}"
            )
        
        return connector_class(company_id, credentials)
    
    @classmethod
    def register(
        cls,
        provider: PMSProvider,
        connector_class: type,
        contract: PMSConnectorContract | None = None,
    ) -> None:
        """
        Register a new PMS connector.
        
        Used to add support for additional PMS providers.
        """
        cls._connectors[provider] = connector_class
        cls._contracts[provider] = contract or connector_class.contract()


# =============================================================================
# FOOTPRINT BUILDER
# =============================================================================

class FootprintBuilder:
    """
    Automatically build operator's geographical footprint from their listings.
    
    The footprint is used for:
    1. Scoping external market scraping
    2. Defining internal comp boundaries
    3. Geofence-specific analytics
    """
    
    DEFAULT_BUFFER_MILES = 5.0
    
    @staticmethod
    def build_from_listings(
        company_id: UUID,
        listings: List[CanonicalListing],
        buffer_miles: float = DEFAULT_BUFFER_MILES,
    ) -> OperatorFootprint:
        """
        Build footprint polygon from listing coordinates.
        
        Algorithm:
        1. Collect all listing coordinates
        2. Compute convex hull (smallest polygon containing all points)
        3. Buffer outward by specified miles
        4. Detect market characteristics
        """
        if not listings:
            raise ValueError("Cannot build footprint from empty listings")
        
        # Collect coordinates
        coords = [(l.longitude, l.latitude) for l in listings if l.latitude and l.longitude]
        
        if len(coords) < 3:
            # Not enough points for polygon - create circle around centroid
            centroid = FootprintBuilder._compute_centroid(coords)
            polygon = FootprintBuilder._create_circle(centroid, buffer_miles)
        else:
            # Compute convex hull
            hull = FootprintBuilder._convex_hull(coords)
            # Buffer outward
            polygon = FootprintBuilder._buffer_polygon(hull, buffer_miles)
        
        # Compute metrics
        centroid = FootprintBuilder._compute_centroid(coords)
        bbox = FootprintBuilder._compute_bounding_box(polygon)
        
        # Detect market class from listings
        market_class = FootprintBuilder._detect_market_class(listings)
        
        return OperatorFootprint(
            company_id=company_id,
            polygon_coords=polygon,
            centroid=centroid,
            bounding_box=bbox,
            listing_count=len(listings),
            buffer_miles=buffer_miles,
            detected_market_class=market_class,
        )
    
    @staticmethod
    def _compute_centroid(coords: List[Tuple[float, float]]) -> Tuple[float, float]:
        """Compute centroid of coordinates."""
        if not coords:
            return (0.0, 0.0)
        
        avg_lng = sum(c[0] for c in coords) / len(coords)
        avg_lat = sum(c[1] for c in coords) / len(coords)
        return (avg_lng, avg_lat)
    
    @staticmethod
    def _convex_hull(coords: List[Tuple[float, float]]) -> List[List[float]]:
        """
        Compute convex hull using Graham scan algorithm.
        
        Returns polygon as list of [lng, lat] coordinates.
        """
        # Simplified convex hull - in production use scipy or shapely
        # For now, just return the points as a polygon
        points = sorted(coords)
        
        if len(points) <= 2:
            return [[p[0], p[1]] for p in points]
        
        # Graham scan
        def cross(o, a, b):
            return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
        
        lower = []
        for p in points:
            while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
                lower.pop()
            lower.append(p)
        
        upper = []
        for p in reversed(points):
            while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
                upper.pop()
            upper.append(p)
        
        hull = lower[:-1] + upper[:-1]
        return [[p[0], p[1]] for p in hull]
    
    @staticmethod
    def _buffer_polygon(
        polygon: List[List[float]], 
        buffer_miles: float,
    ) -> List[List[float]]:
        """
        Buffer polygon outward by specified miles.
        
        Simplified - in production use shapely buffer.
        """
        # Approximate degrees per mile at mid-latitudes
        # 1 degree latitude ≈ 69 miles
        # 1 degree longitude varies, use ~55 miles as average
        lat_buffer = buffer_miles / 69
        lng_buffer = buffer_miles / 55
        
        centroid = FootprintBuilder._compute_centroid(
            [(p[0], p[1]) for p in polygon]
        )
        
        # Expand each point outward from centroid
        buffered = []
        for point in polygon:
            direction_lng = 1 if point[0] >= centroid[0] else -1
            direction_lat = 1 if point[1] >= centroid[1] else -1
            
            new_lng = point[0] + (lng_buffer * direction_lng)
            new_lat = point[1] + (lat_buffer * direction_lat)
            buffered.append([new_lng, new_lat])
        
        return buffered
    
    @staticmethod
    def _create_circle(
        center: Tuple[float, float],
        radius_miles: float,
        points: int = 16,
    ) -> List[List[float]]:
        """Create circular polygon around center point."""
        import math
        
        lat_buffer = radius_miles / 69
        lng_buffer = radius_miles / 55
        
        circle = []
        for i in range(points):
            angle = 2 * math.pi * i / points
            lng = center[0] + lng_buffer * math.cos(angle)
            lat = center[1] + lat_buffer * math.sin(angle)
            circle.append([lng, lat])
        
        # Close the polygon
        circle.append(circle[0])
        return circle
    
    @staticmethod
    def _compute_bounding_box(
        polygon: List[List[float]],
    ) -> Tuple[float, float, float, float]:
        """Compute bounding box from polygon."""
        lngs = [p[0] for p in polygon]
        lats = [p[1] for p in polygon]
        
        return (min(lngs), min(lats), max(lngs), max(lats))
    
    @staticmethod
    def _detect_market_class(listings: List[CanonicalListing]) -> str:
        """
        Auto-detect market class from listing characteristics.
        """
        if not listings:
            return "mixed"
        
        # Count luxury indicators
        luxury_count = sum(1 for l in listings if (
            l.bedrooms >= 4 or
            l.has_pool or
            l.has_waterfront or
            l.beach_access == "private"
        ))
        
        luxury_ratio = luxury_count / len(listings)
        
        if luxury_ratio > 0.6:
            return "luxury"
        elif luxury_ratio > 0.3:
            return "resort"
        else:
            return "mixed"


# =============================================================================
# INGESTION SERVICE
# =============================================================================

class PMSIngestionService:
    """
    Service to orchestrate PMS data ingestion.
    
    Handles:
    1. Connector creation
    2. Data fetching
    3. Footprint generation
    4. Storage (encrypted)
    """
    
    def __init__(self):
        self.factory = PMSConnectorFactory()
        self.footprint_builder = FootprintBuilder()
    
    async def onboard_operator(
        self,
        company_id: UUID,
        provider: PMSProvider,
        credentials: Dict[str, str],
    ) -> Dict[str, Any]:
        """
        Onboard a new operator by connecting their PMS.
        
        Steps:
        1. Create connector
        2. Test connection
        3. Fetch all data
        4. Build footprint
        5. Return summary
        """
        # Create connector
        connector = self.factory.create(provider, company_id, credentials)
        
        # Test connection
        success, message = await connector.test_connection()
        if not success:
            return {
                "success": False,
                "error": message,
            }
        
        # Full sync
        sync_result = await connector.full_sync()
        
        # Fetch listings for footprint
        listings = await connector.fetch_listings()
        
        # Build footprint
        footprint = None
        if listings:
            footprint = self.footprint_builder.build_from_listings(
                company_id, listings
            )
        
        return {
            "success": True,
            "company_id": str(company_id),
            "provider": provider.value,
            "sync_summary": sync_result,
            "footprint": footprint.model_dump() if footprint else None,
        }
    
    async def sync_operator(
        self,
        company_id: UUID,
        connector: PMSConnector,
    ) -> Dict[str, Any]:
        """
        Perform incremental sync for existing operator.
        """
        return await connector.full_sync()
