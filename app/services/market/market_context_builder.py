"""
Market Context Builder.

Populates MarketContext with real signals:
- Events (festivals, holidays, conferences)
- Supply/demand pressure
- Experience demand

This is the HYDRATION layer that makes concierge smart.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.domain.market import (
    MarketContext,
    MarketEvent,
    EventImpact,
    EventCalendar,
    ExperienceDemand,
    DemandLevel,
    SupplyDemandState,
    PricingSignals,
    PriceTrend,
    AvailabilityTrend,
    SeasonalityPattern,
)


# =============================================================================
# EVENT SOURCES (Extensible)
# =============================================================================

@dataclass
class EventSource:
    """An event data source."""
    name: str
    source_type: str  # api, scrape, manual
    
    
@dataclass
class RawEvent:
    """Raw event data before normalization."""
    name: str
    start_date: date
    end_date: date
    location: str
    expected_attendance: Optional[int] = None
    category: str = "general"
    source: str = "manual"


# Built-in holiday calendar (US)
US_HOLIDAYS_2026 = [
    RawEvent("New Year's Day", date(2026, 1, 1), date(2026, 1, 1), "national", category="holiday"),
    RawEvent("MLK Day Weekend", date(2026, 1, 17), date(2026, 1, 19), "national", category="holiday"),
    RawEvent("Presidents Day Weekend", date(2026, 2, 14), date(2026, 2, 16), "national", category="holiday"),
    RawEvent("Memorial Day Weekend", date(2026, 5, 23), date(2026, 5, 25), "national", category="holiday"),
    RawEvent("Independence Day", date(2026, 7, 3), date(2026, 7, 5), "national", category="holiday"),
    RawEvent("Labor Day Weekend", date(2026, 9, 5), date(2026, 9, 7), "national", category="holiday"),
    RawEvent("Thanksgiving", date(2026, 11, 26), date(2026, 11, 29), "national", category="holiday"),
    RawEvent("Christmas/New Year", date(2026, 12, 23), date(2027, 1, 3), "national", category="holiday"),
]

# Example market-specific events (30A Florida)
SAMPLE_30A_EVENTS = [
    RawEvent("30A Wine Festival", date(2026, 3, 12), date(2026, 3, 15), "Alys Beach", 8000, "festival"),
    RawEvent("Seaside School Half Marathon", date(2026, 2, 28), date(2026, 3, 1), "Seaside", 3000, "sports"),
    RawEvent("Digital Graffiti Festival", date(2026, 5, 15), date(2026, 5, 17), "Alys Beach", 5000, "festival"),
    RawEvent("30A Songwriters Festival", date(2026, 1, 15), date(2026, 1, 18), "30A", 15000, "music"),
    RawEvent("Seeing Red Wine Festival", date(2026, 11, 6), date(2026, 11, 8), "WaterColor", 2000, "festival"),
]


# =============================================================================
# MARKET CONTEXT BUILDER
# =============================================================================

class MarketContextBuilder:
    """
    Builds and populates MarketContext with real signals.
    
    Usage:
        builder = MarketContextBuilder(market_id="30a", market_name="30A Beaches")
        
        # Add events
        builder.add_events(SAMPLE_30A_EVENTS)
        builder.add_holidays(US_HOLIDAYS_2026)
        
        # Set demand signals
        builder.set_experience_demand({
            "golf_cart": DemandLevel.HIGH,
            "fishing": DemandLevel.MEDIUM,
        })
        
        # Set supply pressure
        builder.set_supply_demand(SupplyDemandState.TIGHT)
        
        # Build
        context = builder.build()
    """
    
    def __init__(self, market_id: str, market_name: str):
        self.market_id = market_id
        self.market_name = market_name
        
        # Initialize with defaults
        self._events: List[MarketEvent] = []
        self._experience_demand = ExperienceDemand()
        self._supply_demand = SupplyDemandState.BALANCED
        self._pricing_signals = PricingSignals()
        self._seasonality = SeasonalityPattern.YEAR_ROUND
        
        # Metadata
        self._regulatory_status = "unknown"
        self._avg_daily_rate = 0.0
        self._avg_occupancy = 0.0
        self._active_listings = 0
    
    def add_event(self, event: RawEvent) -> "MarketContextBuilder":
        """Add a single event."""
        market_event = self._normalize_event(event)
        self._events.append(market_event)
        return self
    
    def add_events(self, events: List[RawEvent]) -> "MarketContextBuilder":
        """Add multiple events."""
        for event in events:
            self.add_event(event)
        return self
    
    def add_holidays(self, holidays: List[RawEvent] = None) -> "MarketContextBuilder":
        """Add holiday events."""
        if holidays is None:
            holidays = US_HOLIDAYS_2026
        return self.add_events(holidays)
    
    def set_experience_demand(
        self, 
        demand: Dict[str, DemandLevel]
    ) -> "MarketContextBuilder":
        """Set experience demand levels."""
        self._experience_demand = ExperienceDemand(
            golf_cart=demand.get("golf_cart", DemandLevel.MEDIUM),
            fishing=demand.get("fishing", DemandLevel.MEDIUM),
            family_activities=demand.get("family_activities", DemandLevel.MEDIUM),
            water_sports=demand.get("water_sports", DemandLevel.MEDIUM),
            dining_reservations=demand.get("dining_reservations", DemandLevel.MEDIUM),
            spa_services=demand.get("spa_services", DemandLevel.LOW),
            tours_excursions=demand.get("tours_excursions", DemandLevel.MEDIUM),
            custom=demand.get("custom", {}),
        )
        return self
    
    def set_supply_demand(
        self, 
        state: SupplyDemandState
    ) -> "MarketContextBuilder":
        """Set supply/demand pressure."""
        self._supply_demand = state
        return self
    
    def set_pricing_signals(
        self,
        adr_trend: PriceTrend = PriceTrend.STABLE,
        availability_trend: AvailabilityTrend = AvailabilityTrend.STABLE,
        is_compression: bool = False,
    ) -> "MarketContextBuilder":
        """Set pricing signals."""
        self._pricing_signals = PricingSignals(
            adr_trend=adr_trend,
            availability_trend=availability_trend,
            is_compression_weekend=is_compression,
        )
        return self
    
    def set_seasonality(self, state: SeasonalityPattern) -> "MarketContextBuilder":
        """Set current seasonality state."""
        self._seasonality = state
        return self
    
    def set_market_stats(
        self,
        avg_daily_rate: float = 0.0,
        avg_occupancy: float = 0.0,
        active_listings: int = 0,
    ) -> "MarketContextBuilder":
        """Set market statistics."""
        self._avg_daily_rate = avg_daily_rate
        self._avg_occupancy = avg_occupancy
        self._active_listings = active_listings
        return self
    
    def set_regulatory_status(self, status: str) -> "MarketContextBuilder":
        """Set regulatory status."""
        self._regulatory_status = status
        return self
    
    def build(self) -> MarketContext:
        """Build the MarketContext."""
        # Build event calendar
        calendar = EventCalendar(market_id=self.market_id)
        calendar.events = self._events
        
        # Build context
        return MarketContext(
            market_id=self.market_id,
            market_name=self.market_name,
            event_calendar=calendar,
            experience_demand=self._experience_demand,
            supply_demand_pressure=self._supply_demand,
            pricing_signals=self._pricing_signals,
            active_listing_count=self._active_listings,
        )
    
    def _normalize_event(self, raw: RawEvent) -> MarketEvent:
        """Normalize raw event to MarketEvent."""
        # Determine impact based on attendance
        if raw.expected_attendance:
            if raw.expected_attendance >= 10000:
                impact = EventImpact.EXTREME
            elif raw.expected_attendance >= 5000:
                impact = EventImpact.HIGH
            elif raw.expected_attendance >= 2000:
                impact = EventImpact.MEDIUM
            else:
                impact = EventImpact.LOW
        elif raw.category == "holiday":
            impact = EventImpact.HIGH
        else:
            impact = EventImpact.MEDIUM
        
        # Compute demand multiplier
        multipliers = {
            EventImpact.EXTREME: 1.5,
            EventImpact.HIGH: 1.3,
            EventImpact.MEDIUM: 1.15,
            EventImpact.LOW: 1.05,
        }
        
        return MarketEvent(
            event_id=f"{self.market_id}-{raw.name.lower().replace(' ', '-')}",
            name=raw.name,
            start_date=raw.start_date,
            end_date=raw.end_date,
            impact=impact,
            demand_multiplier=multipliers.get(impact, 1.0),
            impact_radius_miles=25.0 if raw.category == "holiday" else 15.0,
        )


# =============================================================================
# FACTORY FUNCTIONS
# =============================================================================

def build_30a_market_context() -> MarketContext:
    """
    Build a fully populated MarketContext for 30A Florida.
    
    This is your "golden market" for testing.
    """
    builder = MarketContextBuilder(market_id="30a", market_name="30A Beaches, FL")
    
    # Add events
    builder.add_events(SAMPLE_30A_EVENTS)
    builder.add_holidays()
    
    # Set demand (coastal vacation market)
    builder.set_experience_demand({
        "golf_cart": DemandLevel.VERY_HIGH,  # Very popular in 30A
        "fishing": DemandLevel.HIGH,
        "family_activities": DemandLevel.HIGH,
        "water_sports": DemandLevel.HIGH,
        "dining_reservations": DemandLevel.VERY_HIGH,  # Restaurants book up
        "spa_services": DemandLevel.MEDIUM,
        "tours_excursions": DemandLevel.MEDIUM,
    })
    
    # Set supply pressure (tight in summer)
    today = date.today()
    if today.month in [6, 7, 8]:
        builder.set_supply_demand(SupplyDemandState.TIGHT)
        builder.set_seasonality(SeasonalityPattern.SUMMER_PEAK)
    elif today.month in [3, 4, 5, 9, 10]:
        builder.set_supply_demand(SupplyDemandState.BALANCED)
        builder.set_seasonality(SeasonalityPattern.SHOULDER_HEAVY)
    else:
        builder.set_supply_demand(SupplyDemandState.LOOSE)
        builder.set_seasonality(SeasonalityPattern.YEAR_ROUND)
    
    # Set market stats
    builder.set_market_stats(
        avg_daily_rate=450.0,
        avg_occupancy=0.62,
        active_listings=2500,
    )
    
    builder.set_regulatory_status("allowed_with_registration")
    
    return builder.build()


def build_market_context_from_evidence(
    market_id: str,
    market_name: str,
    evidence: List[Dict[str, Any]],
) -> MarketContext:
    """
    Build MarketContext from evidence records.
    
    Evidence format:
    {
        "evidence_type": "event" | "experience_demand" | "supply_demand",
        "data": {...}
    }
    """
    builder = MarketContextBuilder(market_id=market_id, market_name=market_name)
    
    # Add holidays by default
    builder.add_holidays()
    
    for record in evidence:
        etype = record.get("evidence_type")
        data = record.get("data", {})
        
        if etype == "event":
            event = RawEvent(
                name=data.get("name", "Unknown Event"),
                start_date=date.fromisoformat(data["start_date"]),
                end_date=date.fromisoformat(data["end_date"]),
                location=data.get("location", ""),
                expected_attendance=data.get("attendance"),
                category=data.get("category", "general"),
            )
            builder.add_event(event)
            
        elif etype == "experience_demand":
            demand = {}
            for key, value in data.items():
                if hasattr(DemandLevel, value.upper()):
                    demand[key] = DemandLevel(value)
            builder.set_experience_demand(demand)
            
        elif etype == "supply_demand":
            pressure = data.get("pressure", "balanced")
            if hasattr(SupplyDemandState, pressure.upper()):
                builder.set_supply_demand(SupplyDemandState(pressure))
    
    return builder.build()
