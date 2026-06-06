"""
Execution Layer: Market Executor.

Thin wrapper around market domain for MarketContext operations.
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Dict, List, Optional
from uuid import UUID

from app.domain.market import (
    MarketContext,
    MarketType,
    DemandTrend,
    SupplyDemandState,
    MarketEvent,
    EventCalendar,
    EventImpact,
    ExperienceDemand,
    DemandLevel,
    PricingSignals,
    PriceTrend,
    AvailabilityTrend,
    SeasonalityProfile,
    SeasonalityPattern,
    RegulatoryContext,
    ComparableMetrics,
    ComparableInsights,
    MarketSummary,
)


# =============================================================================
# PAYLOADS
# =============================================================================

@dataclass
class MarketContextPayload:
    """Input for building a MarketContext."""
    market_id: str
    market_name: str
    market_type: str = "coastal"
    state: Optional[str] = None
    region: Optional[str] = None
    
    # Demand signals
    demand_trend: str = "stable"
    yoy_growth_rate: float = 0.0
    supply_growth_rate: float = 0.0
    supply_demand_pressure: str = "balanced"
    
    # Seasonality
    seasonality_pattern: str = "summer_peak"
    peak_months: List[int] = None
    
    # Market medians
    median_adr_by_bedroom: Dict[int, float] = None
    median_occupancy_by_bedroom: Dict[int, float] = None
    
    # Experience demand
    golf_cart_demand: str = "medium"
    fishing_demand: str = "medium"
    dining_demand: str = "medium"
    water_sports_demand: str = "medium"
    family_activities_demand: str = "medium"
    
    # Regulatory
    str_permitted: Optional[bool] = None
    permit_required: bool = False
    min_stay_days: Optional[int] = None
    
    # Data quality
    data_confidence: float = 0.5
    active_listing_count: int = 0
    
    def __post_init__(self):
        if self.peak_months is None:
            self.peak_months = [6, 7, 8]
        if self.median_adr_by_bedroom is None:
            self.median_adr_by_bedroom = {}
        if self.median_occupancy_by_bedroom is None:
            self.median_occupancy_by_bedroom = {}


@dataclass
class MarketEventPayload:
    """Input for adding a market event."""
    event_id: str
    name: str
    start_date: date
    end_date: date
    impact: str = "medium"
    demand_multiplier: float = 1.0
    event_type: str = "festival"
    description: Optional[str] = None
    guest_appeal: Optional[str] = None
    family_friendly: bool = True


# =============================================================================
# EXECUTOR
# =============================================================================

class MarketExecutor:
    """
    Executor for market context operations.
    
    Handles:
    - Building MarketContext from various sources
    - Adding/updating events
    - Generating market summaries
    """
    
    def build_market_context(self, payload: MarketContextPayload) -> MarketContext:
        """
        Build a MarketContext from payload.
        
        This assembles all market intelligence into one object.
        """
        # Map enums
        type_map = {
            "coastal": MarketType.COASTAL,
            "mountain": MarketType.MOUNTAIN,
            "urban": MarketType.URBAN,
            "suburban": MarketType.SUBURBAN,
            "rural": MarketType.RURAL,
            "lake": MarketType.LAKE,
            "desert": MarketType.DESERT,
        }
        
        trend_map = {
            "growing": DemandTrend.GROWING,
            "stable": DemandTrend.STABLE,
            "declining": DemandTrend.DECLINING,
            "volatile": DemandTrend.VOLATILE,
        }
        
        pressure_map = {
            "loose": SupplyDemandState.LOOSE,
            "balanced": SupplyDemandState.BALANCED,
            "tight": SupplyDemandState.TIGHT,
        }
        
        pattern_map = {
            "summer_peak": SeasonalityPattern.SUMMER_PEAK,
            "winter_peak": SeasonalityPattern.WINTER_PEAK,
            "year_round": SeasonalityPattern.YEAR_ROUND,
            "shoulder_heavy": SeasonalityPattern.SHOULDER_HEAVY,
            "holiday_driven": SeasonalityPattern.HOLIDAY_DRIVEN,
        }
        
        demand_map = {
            "low": DemandLevel.LOW,
            "medium": DemandLevel.MEDIUM,
            "high": DemandLevel.HIGH,
            "very_high": DemandLevel.VERY_HIGH,
        }
        
        # Build experience demand
        experience_demand = ExperienceDemand(
            golf_cart=demand_map.get(payload.golf_cart_demand, DemandLevel.MEDIUM),
            fishing=demand_map.get(payload.fishing_demand, DemandLevel.MEDIUM),
            dining_reservations=demand_map.get(payload.dining_demand, DemandLevel.MEDIUM),
            water_sports=demand_map.get(payload.water_sports_demand, DemandLevel.MEDIUM),
            family_activities=demand_map.get(payload.family_activities_demand, DemandLevel.MEDIUM),
        )
        
        # Build seasonality
        seasonality = SeasonalityProfile(
            pattern=pattern_map.get(payload.seasonality_pattern, SeasonalityPattern.SUMMER_PEAK),
        )
        
        # Build regulatory
        regulatory = RegulatoryContext(
            str_permitted=payload.str_permitted,
            permit_required=payload.permit_required,
            min_stay_days=payload.min_stay_days,
        )
        
        # Build context
        context = MarketContext(
            market_id=payload.market_id,
            market_name=payload.market_name,
            market_type=type_map.get(payload.market_type, MarketType.COASTAL),
            state=payload.state,
            region=payload.region,
            demand_trend=trend_map.get(payload.demand_trend, DemandTrend.STABLE),
            yoy_growth_rate=payload.yoy_growth_rate,
            supply_growth_rate=payload.supply_growth_rate,
            supply_demand_pressure=pressure_map.get(payload.supply_demand_pressure, SupplyDemandState.BALANCED),
            seasonality=seasonality,
            peak_season_months=payload.peak_months,
            median_adr_by_bedroom=payload.median_adr_by_bedroom,
            median_occupancy_by_bedroom=payload.median_occupancy_by_bedroom,
            experience_demand=experience_demand,
            regulatory=regulatory,
            data_confidence=payload.data_confidence,
            active_listing_count=payload.active_listing_count,
        )
        
        return context
    
    def add_event(
        self,
        context: MarketContext,
        payload: MarketEventPayload,
    ) -> MarketContext:
        """Add an event to the market context."""
        impact_map = {
            "low": EventImpact.LOW,
            "medium": EventImpact.MEDIUM,
            "high": EventImpact.HIGH,
            "extreme": EventImpact.EXTREME,
        }
        
        event = MarketEvent(
            event_id=payload.event_id,
            name=payload.name,
            start_date=payload.start_date,
            end_date=payload.end_date,
            impact=impact_map.get(payload.impact, EventImpact.MEDIUM),
            demand_multiplier=payload.demand_multiplier,
            event_type=payload.event_type,
            description=payload.description,
            guest_appeal=payload.guest_appeal,
            family_friendly=payload.family_friendly,
        )
        
        context.event_calendar.events.append(event)
        return context
    
    def generate_summary(
        self,
        context: MarketContext,
        bedrooms: int = 3,
    ) -> MarketSummary:
        """Generate a market summary for BD/pitch books."""
        return MarketSummary.from_context(context, bedrooms=bedrooms)
    
    def get_events_for_stay(
        self,
        context: MarketContext,
        check_in: date,
        check_out: date,
    ) -> List[MarketEvent]:
        """Get events that overlap with a stay."""
        return context.get_events_for_stay(check_in, check_out)
    
    def get_high_demand_experiences(
        self,
        context: MarketContext,
    ) -> List[str]:
        """Get experiences with high demand."""
        return context.get_high_demand_experiences()
    
    def update_pricing_signals(
        self,
        context: MarketContext,
        adr_trend: str = "stable",
        availability_trend: str = "stable",
        is_compression_weekend: bool = False,
        compression_reason: Optional[str] = None,
    ) -> MarketContext:
        """Update real-time pricing signals."""
        trend_map = {
            "rising": PriceTrend.RISING,
            "stable": PriceTrend.STABLE,
            "falling": PriceTrend.FALLING,
        }
        
        avail_map = {
            "tightening": AvailabilityTrend.TIGHTENING,
            "stable": AvailabilityTrend.STABLE,
            "loosening": AvailabilityTrend.LOOSENING,
        }
        
        context.pricing_signals.adr_trend = trend_map.get(adr_trend, PriceTrend.STABLE)
        context.pricing_signals.availability_trend = avail_map.get(availability_trend, AvailabilityTrend.STABLE)
        context.pricing_signals.is_compression_weekend = is_compression_weekend
        context.pricing_signals.compression_reason = compression_reason
        
        return context
