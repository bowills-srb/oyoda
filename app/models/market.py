"""
Market model - represents geographic markets and submarkets.
"""

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, List, Optional
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import AuditMixin, BaseModel, TenantBaseModel

if TYPE_CHECKING:
    from app.models.company import Company
    from app.models.property import Property
    from app.models.pricing import SeasonDefinition, RateTable


class MarketType(str, Enum):
    """Types of markets."""
    BEACH = "beach"
    MOUNTAIN = "mountain"
    LAKE = "lake"
    URBAN = "urban"
    RURAL = "rural"
    DESERT = "desert"
    SKI = "ski"
    GOLF = "golf"
    THEME_PARK = "theme_park"
    OTHER = "other"


class Market(TenantBaseModel, AuditMixin):
    """
    Geographic market definition.
    
    Markets represent distinct geographic areas with their own
    pricing dynamics, seasonality, and demand patterns.
    Examples: "30A Florida", "Destin", "Panama City Beach"
    """
    
    __tablename__ = "markets"
    
    # Company relationship
    company: Mapped["Company"] = relationship("Company", back_populates="markets")
    
    # Basic Information
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    market_type: Mapped[MarketType] = mapped_column(
        String(50),
        default=MarketType.OTHER
    )
    
    # Geographic Definition
    state: Mapped[str] = mapped_column(String(2), nullable=False)  # US state code
    county: Mapped[Optional[str]] = mapped_column(String(100))
    cities: Mapped[list] = mapped_column(
        ARRAY(String(100)),
        default=list,
        server_default='{}'
    )
    zip_codes: Mapped[list] = mapped_column(
        ARRAY(String(10)),
        default=list,
        server_default='{}'
    )
    
    # Bounding Box (for geo queries)
    lat_min: Mapped[Optional[float]] = mapped_column(Numeric(10, 7))
    lat_max: Mapped[Optional[float]] = mapped_column(Numeric(10, 7))
    lng_min: Mapped[Optional[float]] = mapped_column(Numeric(10, 7))
    lng_max: Mapped[Optional[float]] = mapped_column(Numeric(10, 7))
    
    # GeoJSON polygon for precise boundary (optional)
    boundary_geojson: Mapped[Optional[dict]] = mapped_column(JSONB)
    
    # Parent Market (for submarkets)
    parent_market_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("markets.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )
    
    # Market Characteristics
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)  # Primary market for the company
    
    # Default Settings for this Market
    default_commission_rate: Mapped[Optional[float]] = mapped_column(Numeric(5, 4))
    default_min_stay: Mapped[int] = mapped_column(Integer, default=2)
    default_max_stay: Mapped[int] = mapped_column(Integer, default=30)
    
    # Market Statistics (updated periodically)
    avg_occupancy_rate: Mapped[Optional[float]] = mapped_column(Numeric(5, 4))
    avg_daily_rate: Mapped[Optional[float]] = mapped_column(Numeric(10, 2))
    avg_revenue_per_property: Mapped[Optional[float]] = mapped_column(Numeric(12, 2))
    total_properties: Mapped[int] = mapped_column(Integer, default=0)
    stats_updated_at: Mapped[Optional[datetime]] = mapped_column()
    
    # Metadata
    extra_data: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        server_default='{}'
    )
    
    # Relationships
    parent_market: Mapped[Optional["Market"]] = relationship(
        "Market",
        remote_side="Market.id",
        backref="submarkets"
    )
    
    properties: Mapped[List["Property"]] = relationship(
        "Property",
        back_populates="market"
    )
    
    season_definitions: Mapped[List["SeasonDefinition"]] = relationship(
        "SeasonDefinition",
        back_populates="market",
        cascade="all, delete-orphan"
    )
    
    rate_tables: Mapped[List["RateTable"]] = relationship(
        "RateTable",
        back_populates="market",
        cascade="all, delete-orphan"
    )
    
    def __repr__(self) -> str:
        return f"<Market(id={self.id}, name='{self.name}', state='{self.state}')>"
    
    @property
    def full_name(self) -> str:
        """Get full market name including state."""
        return f"{self.name}, {self.state}"
    
    def contains_coordinates(self, lat: float, lng: float) -> bool:
        """Check if coordinates fall within this market's bounding box."""
        if None in (self.lat_min, self.lat_max, self.lng_min, self.lng_max):
            return False
        return (
            self.lat_min <= lat <= self.lat_max and
            self.lng_min <= lng <= self.lng_max
        )


class MarketDataSource(BaseModel):
    """
    External market data source configuration.
    
    Tracks data sources used for market intelligence
    (e.g., AirDNA, Key Data, Transparent).
    """
    
    __tablename__ = "market_data_sources"
    
    # Source identification
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)  # airdna, keydata, etc.
    
    # API Configuration
    api_endpoint: Mapped[Optional[str]] = mapped_column(String(500))
    api_key_encrypted: Mapped[Optional[str]] = mapped_column(String(500))  # Encrypted API key
    
    # Data Coverage
    coverage_markets: Mapped[list] = mapped_column(
        ARRAY(String(100)),
        default=list,
        server_default='{}'
    )
    data_types: Mapped[list] = mapped_column(
        ARRAY(String(50)),
        default=list,  # ['occupancy', 'adr', 'revpar', 'listings']
        server_default='{}'
    )
    
    # Sync Configuration
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sync_frequency_hours: Mapped[int] = mapped_column(Integer, default=24)
    last_sync_at: Mapped[Optional[datetime]] = mapped_column()
    last_sync_status: Mapped[Optional[str]] = mapped_column(String(50))
    last_sync_error: Mapped[Optional[str]] = mapped_column(Text)
    
    # Rate Limiting
    rate_limit_per_hour: Mapped[int] = mapped_column(Integer, default=1000)
    requests_this_hour: Mapped[int] = mapped_column(Integer, default=0)
    rate_limit_reset_at: Mapped[Optional[datetime]] = mapped_column()
    
    def __repr__(self) -> str:
        return f"<MarketDataSource(name='{self.name}', provider='{self.provider}')>"


class MarketBenchmark(TenantBaseModel):
    """
    Market benchmark data point.
    
    Stores periodic snapshots of market performance metrics
    for historical analysis and trend detection.
    """
    
    __tablename__ = "market_benchmarks"
    
    # Market reference
    market_id: Mapped[UUID] = mapped_column(
        ForeignKey("markets.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    
    # Time period
    period_start: Mapped[datetime] = mapped_column(nullable=False, index=True)
    period_end: Mapped[datetime] = mapped_column(nullable=False)
    period_type: Mapped[str] = mapped_column(String(20), nullable=False)  # daily, weekly, monthly
    
    # Performance Metrics
    avg_occupancy_rate: Mapped[Optional[float]] = mapped_column(Numeric(5, 4))
    avg_daily_rate: Mapped[Optional[float]] = mapped_column(Numeric(10, 2))
    avg_revpar: Mapped[Optional[float]] = mapped_column(Numeric(10, 2))  # Revenue per available room
    
    # Inventory Metrics
    total_listings: Mapped[Optional[int]] = mapped_column(Integer)
    active_listings: Mapped[Optional[int]] = mapped_column(Integer)
    new_listings: Mapped[Optional[int]] = mapped_column(Integer)
    
    # Booking Metrics
    total_bookings: Mapped[Optional[int]] = mapped_column(Integer)
    avg_booking_window: Mapped[Optional[float]] = mapped_column(Numeric(5, 1))  # Days in advance
    avg_length_of_stay: Mapped[Optional[float]] = mapped_column(Numeric(5, 2))
    
    # Segmentation by Property Type
    metrics_by_bedroom: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        server_default='{}'
    )
    
    # Data source tracking
    source: Mapped[Optional[str]] = mapped_column(String(50))  # Where this data came from
    
    def __repr__(self) -> str:
        return f"<MarketBenchmark(market_id={self.market_id}, period='{self.period_type}', start='{self.period_start}')>"
