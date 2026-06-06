"""
Market and Event Models

For tracking geo-specific market data and events that the concierge
and market intelligence agent need to know about.
"""

from datetime import datetime, date
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import relationship

from app.models.base import Base


class Market(Base):
    """
    Geographic market definition.
    
    Markets have specific characteristics:
    - Geographic bounds
    - Alert types (beach flags, avalanche, etc.)
    - Event sources
    - Weather patterns
    """
    __tablename__ = "markets"
    
    id = Column(String(100), primary_key=True)  # e.g., "MARKET_30A"
    name = Column(String(255), nullable=False)  # e.g., "30A Florida"
    
    # Market type
    market_type = Column(String(50), default="beach")  # beach, mountain, city, lake
    
    # Geographic bounds (for geo queries)
    geo_bounds = Column(JSONB, default=dict)
    # {
    #     "north": 30.5,
    #     "south": 30.2,
    #     "east": -85.8,
    #     "west": -86.5,
    #     "center": {"lat": 30.35, "lng": -86.15}
    # }
    
    # Timezone
    timezone = Column(String(100), default="America/Chicago")
    
    # Alert types relevant to this market
    alert_types = Column(JSONB, default=list)
    # Beach: ["beach_flag", "rip_current", "hurricane", "jellyfish"]
    # Mountain: ["avalanche", "road_closure", "lift_status", "snow_report"]
    # City: ["traffic", "event", "weather"]
    
    # Weather config
    weather_station_id = Column(String(100), nullable=True)
    weather_api_config = Column(JSONB, default=dict)
    
    # Event sources
    event_sources = Column(JSONB, default=list)
    # ["eventbrite", "ticketmaster", "local_calendar", "custom_scraper"]
    
    # Local knowledge (static info about the market)
    local_knowledge = Column(JSONB, default=dict)
    # {
    #     "emergency_numbers": {"fire": "911", "non_emergency": "850-892-8186"},
    #     "hospitals": [...],
    #     "airports": [{"name": "ECP", "distance_miles": 25}],
    # }
    
    # Seasonality
    peak_season_months = Column(JSONB, default=[6, 7])  # June, July
    shoulder_season_months = Column(JSONB, default=[3, 4, 5, 8, 9, 10])
    off_season_months = Column(JSONB, default=[1, 2, 11, 12])
    
    # Status
    is_active = Column(Boolean, default=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Relationships
    events = relationship("MarketEvent", back_populates="market", lazy="dynamic")
    alerts = relationship("MarketAlert", back_populates="market", lazy="dynamic")


class MarketEvent(Base):
    """
    Events happening in a market.
    
    Used by the concierge to inform guests about local happenings,
    and by pricing to understand demand drivers.
    """
    __tablename__ = "market_events"
    
    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    market_id = Column(String(100), ForeignKey("markets.id"), nullable=False, index=True)
    
    # Event details
    name = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    
    # Event type
    event_type = Column(String(100), nullable=False)
    # festival, concert, sports, holiday, conference, community, weather
    
    # When
    start_date = Column(Date, nullable=False, index=True)
    end_date = Column(Date, nullable=True)
    start_time = Column(String(20), nullable=True)  # "7:00 PM"
    end_time = Column(String(20), nullable=True)
    is_all_day = Column(Boolean, default=False)
    
    # Where
    venue_name = Column(String(255), nullable=True)
    venue_address = Column(String(500), nullable=True)
    geo = Column(JSONB, nullable=True)  # {lat, lng}
    
    # Impact
    impact_level = Column(String(50), default="medium")  # low, medium, high, major
    expected_attendance = Column(Integer, nullable=True)
    affects_pricing = Column(Boolean, default=False)
    pricing_impact_percent = Column(Float, default=0.0)  # e.g., 0.15 for 15% increase
    
    # Source
    source = Column(String(100), nullable=True)  # eventbrite, manual, scraper
    source_id = Column(String(255), nullable=True)  # External ID
    source_url = Column(String(500), nullable=True)
    
    # For concierge
    guest_relevance = Column(String(50), default="informational")
    # informational, recommended, warning, avoid_traffic
    guest_message = Column(Text, nullable=True)
    # "The Seaside Farmers Market is every Saturday morning - great for fresh produce!"
    
    # Status
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Relationship
    market = relationship("Market", back_populates="events")
    
    __table_args__ = (
        Index("idx_market_events_date", "market_id", "start_date"),
    )


class MarketAlert(Base):
    """
    Active alerts for a market (beach flags, weather warnings, etc.)
    
    These are time-sensitive and shown to guests during their stay.
    """
    __tablename__ = "market_alerts"
    
    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    market_id = Column(String(100), ForeignKey("markets.id"), nullable=False, index=True)
    
    # Alert type
    alert_type = Column(String(100), nullable=False)
    # beach_flag, rip_current, hurricane_watch, hurricane_warning,
    # avalanche_warning, road_closure, lift_closure, heat_advisory,
    # severe_thunderstorm, tornado_watch, etc.
    
    # Severity
    severity = Column(String(50), default="moderate")
    # info, low, moderate, high, severe, extreme
    
    # Alert details
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    instructions = Column(Text, nullable=True)  # What guests should do
    
    # For beach flags specifically
    flag_color = Column(String(50), nullable=True)  # green, yellow, red, double_red, purple
    
    # Timing
    issued_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    effective_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    
    # Source
    source = Column(String(100), nullable=True)  # nws, noaa, county, manual
    source_id = Column(String(255), nullable=True)
    
    # Display
    show_on_mobile = Column(Boolean, default=True)
    show_on_dashboard = Column(Boolean, default=True)
    icon_emoji = Column(String(10), nullable=True)  # 🟡, 🌊, ⚠️, etc.
    
    # Status
    is_active = Column(Boolean, default=True)
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Relationship
    market = relationship("Market", back_populates="alerts")
    
    __table_args__ = (
        Index("idx_market_alerts_active", "market_id", "is_active", "alert_type"),
    )
    
    def to_guest_display(self) -> Dict[str, Any]:
        """Format for guest mobile display."""
        return {
            "type": self.alert_type,
            "severity": self.severity,
            "title": self.title,
            "description": self.description,
            "instructions": self.instructions,
            "icon": self.icon_emoji,
            "flag_color": self.flag_color,
            "issued_at": self.issued_at.isoformat() if self.issued_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }
