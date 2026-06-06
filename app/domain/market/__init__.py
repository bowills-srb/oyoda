"""
Domain: Market - Pure Models.

Market context, events, and comparable insights.
No FastAPI. No DB sessions. No external API calls.

This layer represents:
- MarketContext for projections, BD, and concierge
- EventCalendar for proactive intelligence
- Experience demand signals
- Comparable performance data
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Dict, List, Optional
from uuid import UUID


# =============================================================================
# MARKET TYPES
# =============================================================================

class MarketType(str, Enum):
    """Type of rental market."""
    COASTAL = "coastal"
    MOUNTAIN = "mountain"
    URBAN = "urban"
    SUBURBAN = "suburban"
    RURAL = "rural"
    LAKE = "lake"
    DESERT = "desert"


class SeasonalityPattern(str, Enum):
    """Seasonality pattern type."""
    SUMMER_PEAK = "summer_peak"
    WINTER_PEAK = "winter_peak"
    YEAR_ROUND = "year_round"
    SHOULDER_HEAVY = "shoulder_heavy"
    HOLIDAY_DRIVEN = "holiday_driven"


class DemandTrend(str, Enum):
    """Current demand trend."""
    GROWING = "growing"
    STABLE = "stable"
    DECLINING = "declining"
    VOLATILE = "volatile"


class SupplyDemandState(str, Enum):
    """Supply/demand pressure state."""
    LOOSE = "loose"        # Plenty of availability
    BALANCED = "balanced"  # Normal conditions
    TIGHT = "tight"        # High demand, low supply


class DemandLevel(str, Enum):
    """Demand level for experiences/activities."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    VERY_HIGH = "very_high"


class EventImpact(str, Enum):
    """Impact level of a market event."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    EXTREME = "extreme"


# =============================================================================
# MARKET EVENTS (Drives Proactivity)
# =============================================================================

@dataclass
class MarketEvent:
    """
    A local event that impacts demand.
    
    Used by:
    - Concierge for proactive suggestions
    - BD for pricing narratives
    - Analytics for projection adjustments
    """
    event_id: str
    name: str
    start_date: date
    end_date: date
    
    # Impact
    impact: EventImpact = EventImpact.MEDIUM
    demand_multiplier: float = 1.0  # e.g., 1.3 = 30% demand increase
    impact_radius_miles: float = 10.0
    
    # Categorization
    event_type: str = "festival"  # festival, sports, conference, holiday, etc.
    family_friendly: bool = True
    
    # Description for concierge
    description: Optional[str] = None
    guest_appeal: Optional[str] = None  # "Great for wine lovers"
    
    @property
    def is_active(self) -> bool:
        """Check if event is currently active."""
        today = date.today()
        return self.start_date <= today <= self.end_date
    
    @property
    def days_until(self) -> int:
        """Days until event starts."""
        return (self.start_date - date.today()).days
    
    @property
    def date_range_str(self) -> str:
        """Format date range for display."""
        if self.start_date == self.end_date:
            return self.start_date.strftime("%b %d")
        return f"{self.start_date.strftime('%b %d')}-{self.end_date.strftime('%d')}"


@dataclass
class EventCalendar:
    """
    Collection of market events.
    
    Enables proactive concierge suggestions.
    """
    market_id: str
    events: List[MarketEvent] = field(default_factory=list)
    last_updated: datetime = field(default_factory=datetime.utcnow)
    
    def get_events_for_dates(self, start: date, end: date) -> List[MarketEvent]:
        """Get events that overlap with date range."""
        return [
            e for e in self.events
            if not (e.end_date < start or e.start_date > end)
        ]
    
    def get_upcoming_events(self, days: int = 30) -> List[MarketEvent]:
        """Get events in the next N days."""
        today = date.today()
        cutoff = date(today.year, today.month, today.day)
        from datetime import timedelta
        end = cutoff + timedelta(days=days)
        return self.get_events_for_dates(cutoff, end)
    
    def get_high_impact_events(self) -> List[MarketEvent]:
        """Get high/extreme impact events."""
        return [e for e in self.events if e.impact in [EventImpact.HIGH, EventImpact.EXTREME]]
    
    @property
    def has_upcoming_high_impact(self) -> bool:
        """Check if there's a high-impact event in next 30 days."""
        upcoming = self.get_upcoming_events(30)
        return any(e.impact in [EventImpact.HIGH, EventImpact.EXTREME] for e in upcoming)


# =============================================================================
# EXPERIENCE DEMAND
# =============================================================================

@dataclass
class ExperienceDemand:
    """
    Demand levels for local experiences/activities.
    
    Used by concierge for proactive recommendations.
    """
    golf_cart: DemandLevel = DemandLevel.MEDIUM
    fishing: DemandLevel = DemandLevel.MEDIUM
    family_activities: DemandLevel = DemandLevel.MEDIUM
    water_sports: DemandLevel = DemandLevel.MEDIUM
    dining_reservations: DemandLevel = DemandLevel.MEDIUM
    spa_services: DemandLevel = DemandLevel.MEDIUM
    tours_excursions: DemandLevel = DemandLevel.MEDIUM
    
    # Custom experiences
    custom: Dict[str, DemandLevel] = field(default_factory=dict)
    
    def get_high_demand_experiences(self) -> List[str]:
        """Get experiences with high/very_high demand."""
        high = []
        if self.golf_cart in [DemandLevel.HIGH, DemandLevel.VERY_HIGH]:
            high.append("golf_cart")
        if self.fishing in [DemandLevel.HIGH, DemandLevel.VERY_HIGH]:
            high.append("fishing")
        if self.family_activities in [DemandLevel.HIGH, DemandLevel.VERY_HIGH]:
            high.append("family_activities")
        if self.water_sports in [DemandLevel.HIGH, DemandLevel.VERY_HIGH]:
            high.append("water_sports")
        if self.dining_reservations in [DemandLevel.HIGH, DemandLevel.VERY_HIGH]:
            high.append("dining_reservations")
        for name, level in self.custom.items():
            if level in [DemandLevel.HIGH, DemandLevel.VERY_HIGH]:
                high.append(name)
        return high


# =============================================================================
# PRICING SIGNALS
# =============================================================================

class PriceTrend(str, Enum):
    """ADR trend direction."""
    RISING = "rising"
    STABLE = "stable"
    FALLING = "falling"


class AvailabilityTrend(str, Enum):
    """Availability trend direction."""
    TIGHTENING = "tightening"
    STABLE = "stable"
    LOOSENING = "loosening"


@dataclass
class PricingSignals:
    """Real-time pricing signals."""
    adr_trend: PriceTrend = PriceTrend.STABLE
    availability_trend: AvailabilityTrend = AvailabilityTrend.STABLE
    
    # Specific metrics
    adr_7d_change_pct: float = 0.0
    availability_7d_change_pct: float = 0.0
    
    # Compression indicators
    is_compression_weekend: bool = False
    compression_reason: Optional[str] = None


# =============================================================================
# COMPARABLE DATA
# =============================================================================

@dataclass
class ComparableMetrics:
    """Aggregated metrics from comparable properties."""
    count: int = 0
    avg_adr: float = 0.0
    median_adr: float = 0.0
    avg_occupancy: float = 0.0
    median_occupancy: float = 0.0
    avg_annual_revenue: float = 0.0
    median_annual_revenue: float = 0.0
    adr_p25: float = 0.0
    adr_p75: float = 0.0
    occupancy_p25: float = 0.0
    occupancy_p75: float = 0.0
    data_months: int = 12
    confidence: float = 0.0


@dataclass
class ComparableInsights:
    """Insights from comparable properties."""
    metrics_by_bedroom: Dict[int, ComparableMetrics] = field(default_factory=dict)
    total_comparable_count: int = 0
    avg_similarity_score: float = 0.0
    top_performers: List[str] = field(default_factory=list)
    common_amenities: List[str] = field(default_factory=list)
    data_freshness_days: int = 0
    confidence: float = 0.0


# =============================================================================
# SEASONALITY
# =============================================================================

@dataclass
class SeasonalityProfile:
    """Monthly seasonality factors."""
    monthly_factors: Dict[int, float] = field(default_factory=lambda: {
        1: 0.70, 2: 0.75, 3: 0.90, 4: 0.95,
        5: 1.10, 6: 1.30, 7: 1.35, 8: 1.30,
        9: 1.00, 10: 0.85, 11: 0.75, 12: 0.80
    })
    pattern: SeasonalityPattern = SeasonalityPattern.SUMMER_PEAK
    
    def get_factor(self, month: int) -> float:
        return self.monthly_factors.get(month, 1.0)
    
    @property
    def current_state(self) -> str:
        """Get current seasonality state."""
        factor = self.get_factor(datetime.now().month)
        if factor >= 1.2:
            return "peak"
        elif factor >= 0.9:
            return "shoulder"
        else:
            return "low"


# =============================================================================
# REGULATORY CONTEXT
# =============================================================================

@dataclass
class RegulatoryContext:
    """Regulatory environment for STR."""
    str_permitted: Optional[bool] = None
    permit_required: bool = False
    min_stay_days: Optional[int] = None
    occupancy_limits: Optional[int] = None
    restrictions_summary: Optional[str] = None
    confidence: float = 0.0


# =============================================================================
# MARKET CONTEXT (MASTER - Unified for BD + Concierge + Analytics)
# =============================================================================

@dataclass
class MarketContext:
    """
    Market-level context for projections, BD, and concierge.
    
    This is the SINGLE SOURCE OF TRUTH for market intelligence.
    
    Used by:
    - Concierge: proactive recommendations, urgency framing
    - BD: pricing narratives, pitch books
    - Analytics: projection adjustments, sensitivity analysis
    """
    market_id: str
    market_name: str
    market_type: MarketType = MarketType.COASTAL
    
    # Location
    state: Optional[str] = None
    region: Optional[str] = None
    
    # === SEASONALITY STATE ===
    seasonality: SeasonalityProfile = field(default_factory=SeasonalityProfile)
    peak_season_months: List[int] = field(default_factory=lambda: [6, 7, 8])
    
    # === SUPPLY/DEMAND PRESSURE (Critical for concierge) ===
    supply_demand_pressure: SupplyDemandState = SupplyDemandState.BALANCED
    
    # === DEMAND TRENDS ===
    demand_trend: DemandTrend = DemandTrend.STABLE
    yoy_growth_rate: float = 0.0
    supply_growth_rate: float = 0.0
    
    # === EVENTS (Critical for proactive concierge) ===
    event_calendar: EventCalendar = None
    
    # === EXPERIENCE DEMAND (Critical for concierge recommendations) ===
    experience_demand: ExperienceDemand = field(default_factory=ExperienceDemand)
    
    # === PRICING SIGNALS ===
    pricing_signals: PricingSignals = field(default_factory=PricingSignals)
    
    # === MARKET MEDIANS ===
    median_adr_by_bedroom: Dict[int, float] = field(default_factory=dict)
    median_occupancy_by_bedroom: Dict[int, float] = field(default_factory=dict)
    median_revenue_by_bedroom: Dict[int, float] = field(default_factory=dict)
    
    # === COMPARABLE INSIGHTS ===
    comparable_insights: Optional[ComparableInsights] = None
    
    # === REGULATORY ===
    regulatory: RegulatoryContext = field(default_factory=RegulatoryContext)
    
    # === DATA QUALITY ===
    last_updated: datetime = field(default_factory=datetime.utcnow)
    data_confidence: float = 0.0
    active_listing_count: int = 0
    
    def __post_init__(self):
        if self.event_calendar is None:
            self.event_calendar = EventCalendar(market_id=self.market_id)
    
    # === CONVENIENCE METHODS ===
    
    def get_median_adr(self, bedrooms: int) -> Optional[float]:
        return self.median_adr_by_bedroom.get(bedrooms)
    
    def get_median_occupancy(self, bedrooms: int) -> Optional[float]:
        return self.median_occupancy_by_bedroom.get(bedrooms)
    
    def get_seasonality_factor(self, month: int) -> float:
        return self.seasonality.get_factor(month)
    
    def get_events_for_stay(self, checkin: date, checkout: date) -> List[MarketEvent]:
        """Get events that overlap with a stay."""
        return self.event_calendar.get_events_for_dates(checkin, checkout)
    
    def get_high_demand_experiences(self) -> List[str]:
        """Get experiences with high demand."""
        return self.experience_demand.get_high_demand_experiences()
    
    @property
    def is_high_growth(self) -> bool:
        return self.yoy_growth_rate > 0.10
    
    @property
    def is_regulated(self) -> bool:
        return self.regulatory.permit_required or self.regulatory.min_stay_days is not None
    
    @property
    def is_tight_market(self) -> bool:
        return self.supply_demand_pressure == SupplyDemandState.TIGHT
    
    @property
    def current_seasonality_state(self) -> str:
        return self.seasonality.current_state


# =============================================================================
# MARKET SUMMARY (for pitch books)
# =============================================================================

@dataclass
class MarketSummary:
    """Condensed market summary for BD artifacts."""
    market_name: str
    market_type: str
    avg_adr_range: str
    avg_occupancy_range: str
    avg_revenue_range: str
    demand_trend: str
    growth_rate: str
    peak_season: str
    seasonality_impact: str
    regulatory_summary: str
    comparable_count: int
    confidence_level: str
    
    # Event summary for BD
    upcoming_events: List[str] = field(default_factory=list)
    supply_demand_state: str = "balanced"
    
    @classmethod
    def from_context(cls, ctx: MarketContext, bedrooms: int = 3) -> "MarketSummary":
        """Generate summary from MarketContext."""
        adr = ctx.get_median_adr(bedrooms)
        occ = ctx.get_median_occupancy(bedrooms)
        
        adr_range = f"${adr * 0.85:,.0f}-${adr * 1.15:,.0f}" if adr else "N/A"
        occ_range = f"{(occ or 0.5) * 0.9:.0%}-{(occ or 0.5) * 1.1:.0%}"
        
        rev = (adr or 0) * (occ or 0) * 365
        rev_range = f"${rev * 0.8:,.0f}-${rev * 1.2:,.0f}" if rev > 0 else "N/A"
        
        peak_months = ctx.peak_season_months
        month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", 
                      "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        peak = f"{month_names[peak_months[0]-1]}-{month_names[peak_months[-1]-1]}" if peak_months else "N/A"
        
        # Get upcoming events
        upcoming = ctx.event_calendar.get_upcoming_events(60) if ctx.event_calendar else []
        event_names = [e.name for e in upcoming[:3]]
        
        return cls(
            market_name=ctx.market_name,
            market_type=ctx.market_type.value.title(),
            avg_adr_range=adr_range,
            avg_occupancy_range=occ_range,
            avg_revenue_range=rev_range,
            demand_trend=ctx.demand_trend.value.title(),
            growth_rate=f"{ctx.yoy_growth_rate:+.0%} YoY",
            peak_season=peak,
            seasonality_impact="High" if ctx.seasonality.pattern in [SeasonalityPattern.SUMMER_PEAK, SeasonalityPattern.WINTER_PEAK] else "Moderate",
            regulatory_summary=ctx.regulatory.restrictions_summary or "No major restrictions identified",
            comparable_count=ctx.active_listing_count,
            confidence_level="High" if ctx.data_confidence >= 0.7 else "Medium" if ctx.data_confidence >= 0.4 else "Low",
            upcoming_events=event_names,
            supply_demand_state=ctx.supply_demand_pressure.value,
        )


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Enums
    "MarketType",
    "SeasonalityPattern",
    "DemandTrend",
    "SupplyDemandState",
    "DemandLevel",
    "EventImpact",
    "PriceTrend",
    "AvailabilityTrend",
    
    # Events
    "MarketEvent",
    "EventCalendar",
    
    # Experience demand
    "ExperienceDemand",
    
    # Pricing signals
    "PricingSignals",
    
    # Comparable data
    "ComparableMetrics",
    "ComparableInsights",
    
    # Seasonality & Regulatory
    "SeasonalityProfile",
    "RegulatoryContext",
    
    # Market context (MASTER)
    "MarketContext",
    
    # Summary
    "MarketSummary",
]
