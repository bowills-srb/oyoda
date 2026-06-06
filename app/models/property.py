"""
Property model - represents vacation rental properties.
"""

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, List, Optional
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import AuditMixin, SoftDeleteMixin, TenantBaseModel

if TYPE_CHECKING:
    from app.models.company import Company
    from app.models.market import Market
    from app.models.proforma import ProForma


class PropertyStatus(str, Enum):
    """Status of a property in the pipeline."""
    PROSPECT = "prospect"  # Potential listing being evaluated
    PENDING = "pending"  # Awaiting owner decision
    ONBOARDING = "onboarding"  # Signed, being set up
    ACTIVE = "active"  # Live and accepting bookings
    PAUSED = "paused"  # Temporarily not accepting bookings
    CHURNED = "churned"  # Left the management company
    LOST = "lost"  # Prospect that didn't sign


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


class Property(TenantBaseModel, SoftDeleteMixin, AuditMixin):
    """
    Vacation rental property.
    
    This is the core entity representing a property that is either
    being prospected for management or is actively managed.
    """
    
    __tablename__ = "properties"
    
    # Company relationship
    company: Mapped["Company"] = relationship("Company", back_populates="properties")
    
    # Market relationship
    market_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("markets.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )
    market: Mapped[Optional["Market"]] = relationship("Market", back_populates="properties")
    
    # Basic Information
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    internal_code: Mapped[Optional[str]] = mapped_column(String(50), index=True)  # Company's internal ID
    
    # Status & Pipeline
    status: Mapped[PropertyStatus] = mapped_column(
        String(50),
        default=PropertyStatus.PROSPECT,
        index=True
    )
    property_type: Mapped[PropertyType] = mapped_column(
        String(50),
        default=PropertyType.SINGLE_FAMILY
    )
    
    # Address
    address_line1: Mapped[str] = mapped_column(String(255), nullable=False)
    address_line2: Mapped[Optional[str]] = mapped_column(String(255))
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[str] = mapped_column(String(2), nullable=False)  # US state code
    postal_code: Mapped[str] = mapped_column(String(10), nullable=False)
    country: Mapped[str] = mapped_column(String(2), default="US")
    
    # Coordinates
    latitude: Mapped[Optional[float]] = mapped_column(Numeric(10, 7))
    longitude: Mapped[Optional[float]] = mapped_column(Numeric(10, 7))
    
    # Property Details
    bedrooms: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    bathrooms: Mapped[float] = mapped_column(
        Numeric(3, 1), nullable=False, default=0, server_default="0"
    )  # Allow half baths
    sleeps: Mapped[Optional[int]] = mapped_column(Integer)  # Max occupancy
    square_footage: Mapped[Optional[int]] = mapped_column(Integer)
    year_built: Mapped[Optional[int]] = mapped_column(Integer)
    lot_size_sqft: Mapped[Optional[int]] = mapped_column(Integer)
    
    # Value Information
    purchase_price: Mapped[Optional[float]] = mapped_column(Numeric(14, 2))
    current_value: Mapped[Optional[float]] = mapped_column(Numeric(14, 2))
    listed_price: Mapped[Optional[float]] = mapped_column(Numeric(14, 2))  # For prospects on market
    
    # Amenities (structured)
    amenities: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        server_default='{}'
    )
    # Example amenities structure:
    # {
    #     "pool": {"type": "private", "heated": true},
    #     "hot_tub": true,
    #     "beach_access": {"type": "private", "distance_ft": 100},
    #     "parking": {"spaces": 2, "type": "garage"},
    #     "wifi": true,
    #     "ac": true,
    #     "washer_dryer": true,
    #     "kitchen": {"type": "full"},
    #     "outdoor_space": {"type": "deck", "sqft": 500},
    #     "views": ["ocean", "pool"],
    #     "pet_friendly": false,
    #     "elevator": false,
    #     "ev_charger": false
    # }
    
    # Key Features (free text, searchable)
    key_features: Mapped[list] = mapped_column(
        ARRAY(String(100)),
        default=list,
        server_default='{}'
    )
    description: Mapped[Optional[str]] = mapped_column(Text)
    
    # Photos
    photos: Mapped[list] = mapped_column(
        JSONB,  # Array of {url, caption, is_primary, order}
        default=list,
        server_default='[]'
    )
    
    # Owner Information
    owner_name: Mapped[Optional[str]] = mapped_column(String(255))
    owner_email: Mapped[Optional[str]] = mapped_column(String(255))
    owner_phone: Mapped[Optional[str]] = mapped_column(String(50))
    owner_notes: Mapped[Optional[str]] = mapped_column(Text)
    
    # Management Terms
    commission_rate: Mapped[Optional[float]] = mapped_column(Numeric(5, 4))  # Override market default
    contract_start_date: Mapped[Optional[datetime]] = mapped_column()
    contract_end_date: Mapped[Optional[datetime]] = mapped_column()
    minimum_nightly_rate: Mapped[Optional[float]] = mapped_column(Numeric(10, 2))
    
    # Owner Restrictions
    owner_blocked_dates: Mapped[list] = mapped_column(
        JSONB,  # Array of {start, end, reason}
        default=list,
        server_default='[]'
    )
    max_owner_use_days: Mapped[Optional[int]] = mapped_column(Integer)
    
    # External IDs (for integrations)
    external_ids: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        server_default='{}'
    )
    # Example: {"airbnb": "12345", "vrbo": "67890", "pms": "ABC123"}
    
    # Listing URLs
    listing_urls: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        server_default='{}'
    )
    # Example: {"airbnb": "https://...", "vrbo": "https://...", "direct": "https://..."}
    
    # Lead Source (for prospects)
    lead_source: Mapped[Optional[str]] = mapped_column(String(100))  # MLS, referral, website, etc.
    lead_date: Mapped[Optional[datetime]] = mapped_column()
    assigned_to_user_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True
    )
    
    # Performance (for active properties, updated periodically)
    total_revenue_ytd: Mapped[Optional[float]] = mapped_column(Numeric(12, 2))
    total_nights_booked_ytd: Mapped[Optional[int]] = mapped_column(Integer)
    avg_nightly_rate_ytd: Mapped[Optional[float]] = mapped_column(Numeric(10, 2))
    occupancy_rate_ytd: Mapped[Optional[float]] = mapped_column(Numeric(5, 4))
    performance_updated_at: Mapped[Optional[datetime]] = mapped_column()
    
    # Metadata
    extra_data: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        server_default='{}'
    )

    # Property-level policy overrides. Flat-mirrors operator_policies
    # column names so build_profile can merge per-property exceptions
    # over tenant-wide defaults without a separate translation layer.
    property_policy_overrides: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        server_default='{}',
        nullable=False,
    )
    
    # Relationships
    proformas: Mapped[List["ProForma"]] = relationship(
        "ProForma",
        back_populates="property",
        cascade="all, delete-orphan"
    )
    
    historical_performance: Mapped[List["PropertyPerformance"]] = relationship(
        "PropertyPerformance",
        back_populates="property",
        cascade="all, delete-orphan"
    )
    
    def __repr__(self) -> str:
        return f"<Property(id={self.id}, name='{self.name}', bedrooms={self.bedrooms})>"
    
    @property
    def full_address(self) -> str:
        """Get the full formatted address."""
        parts = [self.address_line1]
        if self.address_line2:
            parts.append(self.address_line2)
        parts.append(f"{self.city}, {self.state} {self.postal_code}")
        return ", ".join(parts)
    
    @property
    def bedroom_bath_summary(self) -> str:
        """Get bedroom/bathroom summary string."""
        bath_str = f"{self.bathrooms:.1f}".rstrip('0').rstrip('.')
        return f"{self.bedrooms}BR/{bath_str}BA"
    
    @property
    def is_prospect(self) -> bool:
        """Check if property is in prospect stage."""
        return self.status in (PropertyStatus.PROSPECT, PropertyStatus.PENDING)
    
    @property
    def is_active(self) -> bool:
        """Check if property is actively managed."""
        return self.status == PropertyStatus.ACTIVE
    
    def has_amenity(self, amenity: str) -> bool:
        """Check if property has a specific amenity."""
        return bool(self.amenities.get(amenity))
    
    @property
    def has_pool(self) -> bool:
        return self.has_amenity("pool")
    
    @property
    def is_beachfront(self) -> bool:
        beach = self.amenities.get("beach_access", {})
        if isinstance(beach, dict):
            return beach.get("type") == "private" or beach.get("distance_ft", 1000) < 200
        return False


class PropertyPerformance(TenantBaseModel):
    """
    Historical performance data for a property.
    
    Stores periodic snapshots of actual rental performance
    for comparison against projections and trend analysis.
    """
    
    __tablename__ = "property_performance"
    
    # Property reference
    property_id: Mapped[UUID] = mapped_column(
        ForeignKey("properties.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    parent_property: Mapped["Property"] = relationship("Property", back_populates="historical_performance")
    
    # Time period
    period_start: Mapped[datetime] = mapped_column(nullable=False, index=True)
    period_end: Mapped[datetime] = mapped_column(nullable=False)
    period_type: Mapped[str] = mapped_column(String(20), nullable=False)  # daily, weekly, monthly
    
    # Revenue Metrics
    gross_revenue: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    net_revenue: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    cleaning_fees: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    other_fees: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    
    # Occupancy Metrics
    available_nights: Mapped[int] = mapped_column(Integer, default=0)
    nights_booked: Mapped[int] = mapped_column(Integer, default=0)
    owner_use_nights: Mapped[int] = mapped_column(Integer, default=0)
    blocked_nights: Mapped[int] = mapped_column(Integer, default=0)
    
    # Rate Metrics
    avg_nightly_rate: Mapped[Optional[float]] = mapped_column(Numeric(10, 2))
    min_nightly_rate: Mapped[Optional[float]] = mapped_column(Numeric(10, 2))
    max_nightly_rate: Mapped[Optional[float]] = mapped_column(Numeric(10, 2))
    
    # Booking Metrics
    total_bookings: Mapped[int] = mapped_column(Integer, default=0)
    cancellations: Mapped[int] = mapped_column(Integer, default=0)
    avg_booking_window: Mapped[Optional[float]] = mapped_column(Numeric(5, 1))  # Days in advance
    avg_length_of_stay: Mapped[Optional[float]] = mapped_column(Numeric(5, 2))
    
    # Source tracking
    source: Mapped[Optional[str]] = mapped_column(String(50))  # pms, manual, import
    
    @property
    def occupancy_rate(self) -> float:
        """Calculate occupancy rate for the period."""
        if self.available_nights == 0:
            return 0.0
        return self.nights_booked / self.available_nights
    
    @property
    def revpar(self) -> float:
        """Calculate RevPAR (Revenue Per Available Room/Night)."""
        if self.available_nights == 0:
            return 0.0
        return self.gross_revenue / self.available_nights
    
    def __repr__(self) -> str:
        return f"<PropertyPerformance(property_id={self.property_id}, period='{self.period_type}', start='{self.period_start}')>"
