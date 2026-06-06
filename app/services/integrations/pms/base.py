"""
Base PMS Connector Interface

All PMS connectors implement this interface, providing a unified way
to access property data regardless of the underlying system.

Key design decisions:
1. Async-first for non-blocking operations
2. Standardized data models (PMSProperty, PMSBooking, etc.)
3. Deduplication built into sync operations
4. Incremental sync support (only fetch changes)
5. Webhook support for real-time updates
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, date
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID


class PMSProvider(str, Enum):
    """Supported PMS providers."""
    ESCAPIA = "escapia"
    GUESTY = "guesty"
    HOSTAWAY = "hostaway"
    TRACK = "track"
    STREAMLINE = "streamline"
    LODGIFY = "lodgify"
    OWNERREZ = "ownerrez"
    HOSTFULLY = "hostfully"
    HOSPITABLE = "hospitable"
    BEDS24 = "beds24"


@dataclass
class PMSCredentials:
    """Credentials for PMS API access."""
    provider: PMSProvider
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    account_id: Optional[str] = None
    # OAuth fields
    oauth_client_id: Optional[str] = None
    oauth_client_secret: Optional[str] = None
    oauth_redirect_uri: Optional[str] = None
    # Additional provider-specific fields
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PMSProperty:
    """
    Standardized property data from any PMS.
    
    This is the canonical representation - each connector maps
    their property data to this format.
    """
    # Identity
    external_id: str  # ID in the PMS
    name: str
    code: Optional[str] = None  # Internal code (e.g., "SEALAVIE")
    
    # Location
    address: Optional[str] = None
    address_line_2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    country: str = "US"
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    
    # Details
    bedrooms: Optional[int] = None
    bathrooms: Optional[float] = None
    sleeps: Optional[int] = None
    sqft: Optional[int] = None
    property_type: Optional[str] = None  # house, condo, apartment
    
    # Access
    wifi_network: Optional[str] = None
    wifi_password: Optional[str] = None
    door_code: Optional[str] = None
    gate_code: Optional[str] = None
    lockbox_code: Optional[str] = None
    parking_instructions: Optional[str] = None
    
    # Times
    check_in_time: str = "4:00 PM"
    check_out_time: str = "10:00 AM"
    
    # Amenities (standardized list)
    amenities: List[str] = field(default_factory=list)
    
    # Policies
    house_rules: Optional[str] = None
    pet_policy: Optional[str] = None
    smoking_policy: Optional[str] = None
    
    # Media
    photos: List[Dict[str, str]] = field(default_factory=list)  # [{url, caption}]
    description: Optional[str] = None
    headline: Optional[str] = None
    
    # Pricing
    base_rate: Optional[float] = None
    cleaning_fee: Optional[float] = None
    min_nights: int = 1
    
    # Status
    is_active: bool = True
    
    # Raw data from PMS (for debugging/extension)
    raw_data: Dict[str, Any] = field(default_factory=dict)
    
    # Sync metadata
    last_synced_at: Optional[datetime] = None
    pms_updated_at: Optional[datetime] = None


@dataclass
class PMSBooking:
    """Standardized booking data from any PMS."""
    # Identity
    external_id: str
    property_external_id: str
    
    # Guest
    guest_name: str
    guest_email: Optional[str] = None
    guest_phone: Optional[str] = None
    num_adults: int = 1
    num_children: int = 0
    num_pets: int = 0
    
    # Dates
    check_in: date = None
    check_out: date = None
    booked_at: Optional[datetime] = None
    
    # Financial
    total_price: Optional[float] = None
    cleaning_fee: Optional[float] = None
    taxes: Optional[float] = None
    
    # Status
    status: str = "confirmed"  # confirmed, cancelled, pending
    source: Optional[str] = None  # airbnb, vrbo, direct, etc.
    
    # Notes
    guest_notes: Optional[str] = None
    internal_notes: Optional[str] = None
    
    # Raw data
    raw_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PMSGuest:
    """Guest profile from PMS."""
    external_id: str
    first_name: str
    last_name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    
    # History
    total_stays: int = 0
    total_revenue: float = 0.0
    first_stay: Optional[date] = None
    last_stay: Optional[date] = None
    
    # Notes
    notes: Optional[str] = None
    preferences: Dict[str, Any] = field(default_factory=dict)
    
    raw_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PMSRate:
    """Rate/pricing data from PMS."""
    property_external_id: str
    date: date
    nightly_rate: float
    min_nights: int = 1
    is_available: bool = True
    
    # Modifiers
    weekend_rate: Optional[float] = None
    weekly_discount_percent: Optional[float] = None
    monthly_discount_percent: Optional[float] = None


@dataclass
class SyncResult:
    """Result of a sync operation."""
    success: bool
    provider: PMSProvider
    operator_id: str
    
    # Counts
    properties_synced: int = 0
    properties_created: int = 0
    properties_updated: int = 0
    properties_deactivated: int = 0
    
    bookings_synced: int = 0
    bookings_created: int = 0
    bookings_updated: int = 0
    
    # Deduplication
    duplicates_found: int = 0
    duplicates_merged: int = 0
    
    # Errors
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    
    # Timing
    started_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    
    @property
    def duration_seconds(self) -> Optional[float]:
        if self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None


class PMSConnector(ABC):
    """
    Abstract base class for PMS connectors.
    
    Each PMS provider implements this interface to provide
    standardized access to property and booking data.
    
    Example implementation:
        class EscapiaConnector(PMSConnector):
            async def test_connection(self) -> bool:
                # Call Escapia API to verify credentials
                ...
            
            async def get_properties(self) -> List[PMSProperty]:
                # Fetch and transform Escapia properties
                ...
    """
    
    provider: PMSProvider
    credentials: PMSCredentials
    
    def __init__(self, credentials: PMSCredentials):
        self.credentials = credentials
    
    # =========================================================================
    # Connection Management
    # =========================================================================
    
    @abstractmethod
    async def test_connection(self) -> bool:
        """Test if credentials are valid and API is accessible."""
        pass
    
    @abstractmethod
    async def get_account_info(self) -> Dict[str, Any]:
        """Get account information (company name, plan, etc.)."""
        pass
    
    # =========================================================================
    # Property Operations
    # =========================================================================
    
    @abstractmethod
    async def get_properties(
        self,
        include_inactive: bool = False,
    ) -> List[PMSProperty]:
        """
        Get all properties from the PMS.
        
        This should handle pagination internally and return
        a complete list of properties.
        """
        pass
    
    @abstractmethod
    async def get_property(self, external_id: str) -> Optional[PMSProperty]:
        """Get a single property by its PMS ID."""
        pass
    
    async def get_property_by_code(self, code: str) -> Optional[PMSProperty]:
        """Get a property by internal code (if supported)."""
        # Default implementation searches all properties
        properties = await self.get_properties()
        for prop in properties:
            if prop.code and prop.code.lower() == code.lower():
                return prop
        return None
    
    # =========================================================================
    # Booking Operations
    # =========================================================================
    
    @abstractmethod
    async def get_bookings(
        self,
        property_external_id: Optional[str] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        include_cancelled: bool = False,
    ) -> List[PMSBooking]:
        """
        Get bookings from the PMS.
        
        Args:
            property_external_id: Filter by property
            start_date: Bookings with check-in >= this date
            end_date: Bookings with check-in <= this date
            include_cancelled: Include cancelled bookings
        """
        pass
    
    @abstractmethod
    async def get_booking(self, external_id: str) -> Optional[PMSBooking]:
        """Get a single booking by its PMS ID."""
        pass
    
    async def get_current_guest(
        self,
        property_external_id: str,
    ) -> Optional[PMSBooking]:
        """Get the current/active booking for a property."""
        today = date.today()
        bookings = await self.get_bookings(
            property_external_id=property_external_id,
            start_date=today,
            end_date=today,
        )
        
        for booking in bookings:
            if booking.check_in <= today <= booking.check_out:
                return booking
        return None
    
    async def get_upcoming_bookings(
        self,
        property_external_id: str,
        days_ahead: int = 30,
    ) -> List[PMSBooking]:
        """Get upcoming bookings for a property."""
        today = date.today()
        end = date(today.year, today.month, today.day)
        from datetime import timedelta
        end = today + timedelta(days=days_ahead)
        
        return await self.get_bookings(
            property_external_id=property_external_id,
            start_date=today,
            end_date=end,
        )
    
    # =========================================================================
    # Rate/Availability Operations
    # =========================================================================
    
    async def get_rates(
        self,
        property_external_id: str,
        start_date: date,
        end_date: date,
    ) -> List[PMSRate]:
        """Get nightly rates for a property (if supported)."""
        # Default: not implemented
        return []
    
    async def get_availability(
        self,
        property_external_id: str,
        start_date: date,
        end_date: date,
    ) -> Dict[date, bool]:
        """Get availability calendar for a property."""
        # Default implementation based on bookings
        bookings = await self.get_bookings(
            property_external_id=property_external_id,
            start_date=start_date,
            end_date=end_date,
        )
        
        availability = {}
        current = start_date
        while current <= end_date:
            availability[current] = True
            for booking in bookings:
                if booking.check_in <= current < booking.check_out:
                    availability[current] = False
                    break
            from datetime import timedelta
            current += timedelta(days=1)
        
        return availability
    
    # =========================================================================
    # Sync Operations
    # =========================================================================
    
    async def sync_all(
        self,
        operator_id: str,
        include_bookings: bool = True,
    ) -> SyncResult:
        """
        Perform a full sync of all data from the PMS.
        
        This is the main entry point for syncing data.
        Handles deduplication and incremental updates.
        """
        result = SyncResult(
            success=True,
            provider=self.provider,
            operator_id=operator_id,
        )
        
        try:
            # Sync properties
            properties = await self.get_properties()
            result.properties_synced = len(properties)
            
            # TODO: Save to database with deduplication
            # This will be implemented in the sync service
            
            # Sync bookings if requested
            if include_bookings:
                bookings = await self.get_bookings()
                result.bookings_synced = len(bookings)
            
            result.completed_at = datetime.utcnow()
            
        except Exception as e:
            result.success = False
            result.errors.append(str(e))
        
        return result
    
    # =========================================================================
    # Webhook Support
    # =========================================================================
    
    def supports_webhooks(self) -> bool:
        """Check if this PMS supports webhooks for real-time updates."""
        return False
    
    async def register_webhook(
        self,
        callback_url: str,
        events: List[str],
    ) -> Dict[str, Any]:
        """Register a webhook for real-time updates (if supported)."""
        raise NotImplementedError(f"{self.provider} does not support webhooks")
    
    def parse_webhook_payload(
        self,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ) -> Dict[str, Any]:
        """Parse and validate an incoming webhook payload."""
        raise NotImplementedError(f"{self.provider} does not support webhooks")
