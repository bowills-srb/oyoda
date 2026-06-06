"""
SQLAlchemy ORM Models - Database persistence for core schemas.

These models map directly to the Pydantic schemas in schemas/core.py.
Every schema change requires a migration.

Design Rules:
1. tenant_id on EVERY table (enforced via mixin)
2. Row-level security enabled
3. Soft deletes where appropriate
4. Audit timestamps on everything
"""

from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.orm import declared_attr


# =============================================================================
# BASE CLASSES
# =============================================================================

class Base(DeclarativeBase):
    """Base class for all ORM models."""
    pass


class TenantMixin:
    """Mixin that adds tenant_id to every model for isolation."""
    
    @declared_attr
    def tenant_id(cls) -> Mapped[UUID]:
        return mapped_column(
            PGUUID(as_uuid=True),
            nullable=False,
            index=True,
        )


class TimestampMixin:
    """Mixin for audit timestamps."""
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SoftDeleteMixin:
    """Mixin for soft deletes."""
    
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


# =============================================================================
# TENANT
# =============================================================================

class TenantModel(Base, TimestampMixin):
    """Tenant (property management company)."""
    
    __tablename__ = "tenants"
    
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    
    primary_email: Mapped[str] = mapped_column(String(255), nullable=False)
    primary_phone: Mapped[Optional[str]] = mapped_column(String(50))
    
    timezone: Mapped[str] = mapped_column(String(50), default="America/Chicago")
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    subscription_tier: Mapped[str] = mapped_column(String(20), default="starter")
    
    features_enabled: Mapped[List[str]] = mapped_column(ARRAY(String), default=[])
    
    # Relationships
    operators: Mapped[List["OperatorModel"]] = relationship(back_populates="tenant")
    properties: Mapped[List["PropertyModel"]] = relationship(back_populates="tenant")


# =============================================================================
# OPERATOR
# =============================================================================

class OperatorModel(Base, TimestampMixin):
    """Operator within a tenant."""
    
    __tablename__ = "operators"
    
    operator_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    
    email: Mapped[Optional[str]] = mapped_column(String(255))
    phone: Mapped[Optional[str]] = mapped_column(String(50))
    
    markets_active: Mapped[List[str]] = mapped_column(ARRAY(String), default=[])
    property_count: Mapped[int] = mapped_column(Integer, default=0)
    
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    
    # Relationships
    tenant: Mapped["TenantModel"] = relationship(back_populates="operators")
    properties: Mapped[List["PropertyModel"]] = relationship(back_populates="operator")
    
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_operator_tenant_code"),
        Index("ix_operator_tenant_active", "tenant_id", "is_active"),
    )


# =============================================================================
# PROPERTY
# =============================================================================

class PropertyModel(Base, TimestampMixin, SoftDeleteMixin):
    """Physical property."""
    
    __tablename__ = "properties"
    
    property_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    operator_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("operators.operator_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    
    # Location
    address_line1: Mapped[str] = mapped_column(String(255), nullable=False)
    address_line2: Mapped[Optional[str]] = mapped_column(String(255))
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[str] = mapped_column(String(2), nullable=False)
    postal_code: Mapped[str] = mapped_column(String(20), nullable=False)
    country: Mapped[str] = mapped_column(String(2), default="US")
    latitude: Mapped[float] = mapped_column(Numeric(10, 7), nullable=False)
    longitude: Mapped[float] = mapped_column(Numeric(10, 7), nullable=False)
    
    # Property details
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    property_type: Mapped[str] = mapped_column(String(50), default="single_family")
    
    bedrooms: Mapped[int] = mapped_column(Integer, nullable=False)
    bathrooms: Mapped[float] = mapped_column(Numeric(3, 1), nullable=False)
    sleeps: Mapped[int] = mapped_column(Integer, nullable=False)
    square_footage: Mapped[Optional[int]] = mapped_column(Integer)
    
    # Amenities
    has_pool: Mapped[bool] = mapped_column(Boolean, default=False)
    pool_heated: Mapped[bool] = mapped_column(Boolean, default=False)
    has_hot_tub: Mapped[bool] = mapped_column(Boolean, default=False)
    has_waterfront: Mapped[bool] = mapped_column(Boolean, default=False)
    waterfront_type: Mapped[Optional[str]] = mapped_column(String(50))
    beach_access: Mapped[Optional[str]] = mapped_column(String(50))
    pet_friendly: Mapped[bool] = mapped_column(Boolean, default=False)
    has_garage: Mapped[bool] = mapped_column(Boolean, default=False)
    has_ev_charger: Mapped[bool] = mapped_column(Boolean, default=False)
    has_game_room: Mapped[bool] = mapped_column(Boolean, default=False)
    has_home_theater: Mapped[bool] = mapped_column(Boolean, default=False)
    
    amenities: Mapped[List[str]] = mapped_column(ARRAY(String), default=[])
    
    owner_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    
    # Relationships
    tenant: Mapped["TenantModel"] = relationship(back_populates="properties")
    operator: Mapped[Optional["OperatorModel"]] = relationship(back_populates="properties")
    listings: Mapped[List["ListingModel"]] = relationship(back_populates="property")
    bookings: Mapped[List["BookingModel"]] = relationship(back_populates="property")
    
    __table_args__ = (
        Index("ix_property_location", "latitude", "longitude"),
        Index("ix_property_tenant_active", "tenant_id", "is_active"),
        Index("ix_property_city_state", "city", "state"),
    )


# =============================================================================
# LISTING
# =============================================================================

class ListingModel(Base, TimestampMixin):
    """Bookable listing on a channel."""
    
    __tablename__ = "listings"
    
    listing_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    property_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("properties.property_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    
    channel: Mapped[str] = mapped_column(String(50), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    external_url: Mapped[Optional[str]] = mapped_column(Text)
    
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    
    min_nights: Mapped[int] = mapped_column(Integer, default=1)
    max_nights: Mapped[int] = mapped_column(Integer, default=365)
    max_guests: Mapped[int] = mapped_column(Integer, default=1)
    
    status: Mapped[str] = mapped_column(String(20), default="active")
    
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    sync_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    
    # Relationships
    property: Mapped["PropertyModel"] = relationship(back_populates="listings")
    bookings: Mapped[List["BookingModel"]] = relationship(back_populates="listing")
    
    __table_args__ = (
        UniqueConstraint("channel", "external_id", name="uq_listing_channel_external"),
        Index("ix_listing_tenant_status", "tenant_id", "status"),
    )


# =============================================================================
# BOOKING
# =============================================================================

class BookingModel(Base, TimestampMixin):
    """Reservation/booking."""
    
    __tablename__ = "bookings"
    
    booking_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    property_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("properties.property_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    listing_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("listings.listing_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    guest_profile_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("guest_profiles.guest_profile_id", ondelete="SET NULL"),
        index=True,
    )
    
    # Dates
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    nights: Mapped[int] = mapped_column(Integer, nullable=False)
    
    # Guest composition
    adults: Mapped[int] = mapped_column(Integer, default=1)
    children: Mapped[int] = mapped_column(Integer, default=0)
    infants: Mapped[int] = mapped_column(Integer, default=0)
    pets: Mapped[bool] = mapped_column(Boolean, default=False)
    
    # Channel
    channel: Mapped[str] = mapped_column(String(50), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    
    # Financials
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    nightly_rate: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    cleaning_fee: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    service_fee: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    taxes: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    host_payout: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    
    # Status
    status: Mapped[str] = mapped_column(String(20), default="confirmed")
    
    # Timestamps
    booked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    
    # Relationships
    property: Mapped["PropertyModel"] = relationship(back_populates="bookings")
    listing: Mapped["ListingModel"] = relationship(back_populates="bookings")
    guest_profile: Mapped[Optional["GuestProfileModel"]] = relationship(back_populates="bookings")
    
    __table_args__ = (
        UniqueConstraint("channel", "external_id", name="uq_booking_channel_external"),
        Index("ix_booking_dates", "start_date", "end_date"),
        Index("ix_booking_tenant_status", "tenant_id", "status"),
        Index("ix_booking_property_dates", "property_id", "start_date", "end_date"),
    )


# =============================================================================
# GUEST PROFILE
# =============================================================================

class GuestProfileModel(Base, TimestampMixin):
    """Anonymized guest profile."""
    
    __tablename__ = "guest_profiles"
    
    guest_profile_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    
    # Channel identifiers (hashed)
    channel_guest_ids: Mapped[dict] = mapped_column(JSONB, default={})
    
    # Derived attributes
    guest_type: Mapped[str] = mapped_column(String(20), default="unknown")
    typical_party_size: Mapped[Optional[int]] = mapped_column(Integer)
    travels_with_children: Mapped[Optional[bool]] = mapped_column(Boolean)
    travels_with_pets: Mapped[Optional[bool]] = mapped_column(Boolean)
    
    # Booking patterns
    total_bookings: Mapped[int] = mapped_column(Integer, default=0)
    total_nights: Mapped[int] = mapped_column(Integer, default=0)
    avg_booking_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    preferred_channels: Mapped[List[str]] = mapped_column(ARRAY(String), default=[])
    
    # Engagement signals
    response_rate: Mapped[Optional[float]] = mapped_column(Numeric(5, 4))
    review_rate: Mapped[Optional[float]] = mapped_column(Numeric(5, 4))
    
    # Preferences
    preferences: Mapped[dict] = mapped_column(JSONB, default={})
    
    # Risk signals
    cancellation_rate: Mapped[Optional[float]] = mapped_column(Numeric(5, 4))
    is_flagged: Mapped[bool] = mapped_column(Boolean, default=False)
    flag_reason: Mapped[Optional[str]] = mapped_column(Text)
    
    # Relationships
    bookings: Mapped[List["BookingModel"]] = relationship(back_populates="guest_profile")
    message_threads: Mapped[List["MessageThreadModel"]] = relationship(back_populates="guest_profile")


# =============================================================================
# MESSAGE THREAD
# =============================================================================

class MessageThreadModel(Base, TimestampMixin):
    """Conversation thread with a guest."""
    
    __tablename__ = "message_threads"
    
    thread_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    property_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("properties.property_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    booking_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("bookings.booking_id", ondelete="SET NULL"),
        index=True,
    )
    guest_profile_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("guest_profiles.guest_profile_id", ondelete="SET NULL"),
        index=True,
    )
    
    channel: Mapped[str] = mapped_column(String(50), nullable=False)
    external_thread_id: Mapped[Optional[str]] = mapped_column(String(255))
    
    subject: Mapped[Optional[str]] = mapped_column(String(500))
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    
    is_open: Mapped[bool] = mapped_column(Boolean, default=True)
    requires_response: Mapped[bool] = mapped_column(Boolean, default=False)
    last_message_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_message_direction: Mapped[Optional[str]] = mapped_column(String(20))
    
    last_processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    extracted_intents: Mapped[List[str]] = mapped_column(ARRAY(String), default=[])
    
    # Relationships
    guest_profile: Mapped[Optional["GuestProfileModel"]] = relationship(back_populates="message_threads")
    messages: Mapped[List["MessageModel"]] = relationship(back_populates="thread")
    
    __table_args__ = (
        Index("ix_thread_tenant_open", "tenant_id", "is_open"),
        Index("ix_thread_requires_response", "tenant_id", "requires_response"),
    )


# =============================================================================
# MESSAGE
# =============================================================================

class MessageModel(Base, TimestampMixin):
    """Individual message within a thread."""
    
    __tablename__ = "messages"
    
    message_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    thread_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("message_threads.thread_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    
    direction: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(String(20), default="text")
    
    sender_type: Mapped[str] = mapped_column(String(20), default="guest")
    
    external_id: Mapped[Optional[str]] = mapped_column(String(255))
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    
    processed: Mapped[bool] = mapped_column(Boolean, default=False)
    extracted_intent: Mapped[Optional[str]] = mapped_column(String(100))
    sentiment: Mapped[Optional[float]] = mapped_column(Numeric(5, 4))
    urgency_score: Mapped[Optional[float]] = mapped_column(Numeric(5, 4))
    
    # Relationships
    thread: Mapped["MessageThreadModel"] = relationship(back_populates="messages")
    
    __table_args__ = (
        Index("ix_message_thread_sent", "thread_id", "sent_at"),
    )


# =============================================================================
# GEO POLYGON
# =============================================================================

class GeoPolygonModel(Base, TimestampMixin):
    """Geographic boundary."""
    
    __tablename__ = "geo_polygons"
    
    polygon_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    
    geometry_type: Mapped[str] = mapped_column(String(20), default="Polygon")
    coordinates: Mapped[list] = mapped_column(JSONB, nullable=False)
    
    center_lat: Mapped[float] = mapped_column(Numeric(10, 7), nullable=False)
    center_lng: Mapped[float] = mapped_column(Numeric(10, 7), nullable=False)
    
    bounds_north: Mapped[float] = mapped_column(Numeric(10, 7), nullable=False)
    bounds_south: Mapped[float] = mapped_column(Numeric(10, 7), nullable=False)
    bounds_east: Mapped[float] = mapped_column(Numeric(10, 7), nullable=False)
    bounds_west: Mapped[float] = mapped_column(Numeric(10, 7), nullable=False)
    
    polygon_type: Mapped[str] = mapped_column(String(20), default="market")
    parent_polygon_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True))
    
    property_count: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    
    # Relationships
    market_snapshots: Mapped[List["MarketSnapshotModel"]] = relationship(back_populates="polygon")
    
    __table_args__ = (
        Index("ix_polygon_bounds", "bounds_north", "bounds_south", "bounds_east", "bounds_west"),
    )


# =============================================================================
# MARKET SNAPSHOT
# =============================================================================

class MarketSnapshotModel(Base, TimestampMixin):
    """Point-in-time market analytics."""
    
    __tablename__ = "market_snapshots"
    
    snapshot_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    polygon_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("geo_polygons.polygon_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    period_type: Mapped[str] = mapped_column(String(20), default="daily")
    
    # Supply metrics
    total_listings: Mapped[int] = mapped_column(Integer, default=0)
    active_listings: Mapped[int] = mapped_column(Integer, default=0)
    new_listings_period: Mapped[int] = mapped_column(Integer, default=0)
    delisted_period: Mapped[int] = mapped_column(Integer, default=0)
    
    # Demand metrics
    total_bookings_period: Mapped[int] = mapped_column(Integer, default=0)
    total_nights_booked: Mapped[int] = mapped_column(Integer, default=0)
    avg_occupancy: Mapped[float] = mapped_column(Numeric(5, 4), default=0)
    
    # Pricing metrics
    avg_adr: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    median_adr: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    adr_25th_percentile: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    adr_75th_percentile: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    
    # Revenue metrics
    total_revenue_period: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    avg_revpar: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    
    # Composition
    property_type_breakdown: Mapped[dict] = mapped_column(JSONB, default={})
    bedroom_breakdown: Mapped[dict] = mapped_column(JSONB, default={})
    channel_breakdown: Mapped[dict] = mapped_column(JSONB, default={})
    
    # Trends
    adr_change_yoy: Mapped[Optional[float]] = mapped_column(Numeric(5, 4))
    occupancy_change_yoy: Mapped[Optional[float]] = mapped_column(Numeric(5, 4))
    supply_change_yoy: Mapped[Optional[float]] = mapped_column(Numeric(5, 4))
    
    # Confidence
    data_completeness: Mapped[float] = mapped_column(Numeric(5, 4), default=1.0)
    source_count: Mapped[int] = mapped_column(Integer, default=1)
    
    # Relationships
    polygon: Mapped["GeoPolygonModel"] = relationship(back_populates="market_snapshots")
    
    __table_args__ = (
        UniqueConstraint("polygon_id", "snapshot_date", "period_type", name="uq_snapshot_polygon_date"),
        Index("ix_snapshot_date", "snapshot_date"),
    )


# =============================================================================
# ANALYTICS RESULT
# =============================================================================

class AnalyticsResultModel(Base, TimestampMixin):
    """Generic analytics computation result."""
    
    __tablename__ = "analytics_results"
    
    result_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    
    analytics_type: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[str] = mapped_column(String(20), default="1.0")
    
    property_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), index=True)
    polygon_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), index=True)
    
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_until: Mapped[date] = mapped_column(Date, nullable=False)
    
    results: Mapped[dict] = mapped_column(JSONB, nullable=False)
    
    confidence: Mapped[float] = mapped_column(Numeric(5, 4), default=0.5)
    computation_time_ms: Mapped[Optional[int]] = mapped_column(Integer)
    inputs_hash: Mapped[Optional[str]] = mapped_column(String(64))
    
    __table_args__ = (
        Index("ix_analytics_type_valid", "analytics_type", "valid_from", "valid_until"),
        Index("ix_analytics_property", "property_id", "analytics_type"),
    )


# =============================================================================
# DECLARED ATTR IMPORT (needed for mixins)
# =============================================================================

from sqlalchemy.orm import declared_attr
