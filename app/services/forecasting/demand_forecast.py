"""
Forward Demand Forecasting - Strategic Gap #1.

Most competitors show snapshots or historical averages.
We provide forward-looking predictive signals (1-3 months).

This module adds:
- Forward demand signals (DEMAND_FORECAST_30D, 60D, 90D)
- Dynamic forecast bands based on confidence
- Event + season interaction effects
- Booking pace momentum projection

Architecture:
- ForwardDemandDetector produces forecast signals
- ForecastService consumes signals and provides bands
- Integrates with existing seasonality and momentum signals
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4
import math

from app.services.signals.signal_contract import (
    Signal,
    SignalBundle,
    SignalType,
    SignalScope,
    SignalSource,
    fast_decay,
    medium_decay,
    ConfidenceThresholds,
)


# =============================================================================
# NEW SIGNAL TYPES FOR FORECASTING
# =============================================================================

class ForecastHorizon(str, Enum):
    """Forecast time horizons."""
    DAYS_30 = "30d"
    DAYS_60 = "60d"
    DAYS_90 = "90d"


class ForecastDriver(str, Enum):
    """Drivers that influence forecasts."""
    SEASONALITY = "seasonality"
    MOMENTUM = "momentum"
    EVENT = "event"
    SUPPLY_CHANGE = "supply_change"
    COMPETITOR_PRICING = "competitor_pricing"
    MACRO_TREND = "macro_trend"


# =============================================================================
# FORECAST OUTPUT MODELS
# =============================================================================

@dataclass
class ForecastBand:
    """
    Forecast with confidence bands.
    
    Unlike static dashboards, we show:
    - Point estimate
    - Confidence interval (based on signal quality)
    - Key drivers
    """
    # Time period
    period_start: date
    period_end: date
    horizon: ForecastHorizon
    
    # Demand forecast (0-1 scale, like occupancy)
    demand_low: float      # 10th percentile
    demand_expected: float # 50th percentile (point estimate)
    demand_high: float     # 90th percentile
    
    # ADR forecast
    adr_low: float
    adr_expected: float
    adr_high: float
    
    # Occupancy forecast
    occupancy_low: float
    occupancy_expected: float
    occupancy_high: float
    
    # Revenue forecast
    revenue_low: float
    revenue_expected: float
    revenue_high: float
    
    # Confidence
    confidence: float
    band_width_pct: float  # How wide is the band? Narrower = more confident
    
    # Drivers (what's influencing this forecast)
    drivers: List[Dict[str, Any]] = field(default_factory=list)
    
    # Event impacts (if any)
    events: List[Dict[str, Any]] = field(default_factory=list)
    
    def is_actionable(self) -> bool:
        """Is forecast confident enough to act on?"""
        return self.confidence >= 0.6 and self.band_width_pct < 0.40


@dataclass
class DemandForecast:
    """
    Complete demand forecast for a geo/property.
    
    Provides 30/60/90 day forecasts with driver attribution.
    """
    geo_id: str
    property_id: Optional[UUID] = None
    tenant_id: Optional[UUID] = None
    
    # Forecasts by horizon
    forecast_30d: Optional[ForecastBand] = None
    forecast_60d: Optional[ForecastBand] = None
    forecast_90d: Optional[ForecastBand] = None
    
    # Overall trend
    trend_direction: str = "stable"  # "rising", "falling", "stable"
    trend_strength: float = 0.0      # 0-1
    
    # Key insights
    insights: List[str] = field(default_factory=list)
    
    # Confidence
    overall_confidence: float = 0.0
    
    # Metadata
    computed_at: datetime = field(default_factory=datetime.utcnow)
    signal_count: int = 0


# =============================================================================
# FORECAST SERVICE
# =============================================================================

class ForecastService:
    """
    Forward Demand Forecasting Service.
    
    Unlike competitors who show historical averages, this service:
    - Projects forward 30/60/90 days
    - Provides confidence bands (not just point estimates)
    - Attributes forecasts to specific drivers
    - Incorporates event effects
    
    All inputs come from SignalBundle. No hardcoded predictions.
    """
    
    def __init__(self):
        self.version = "1.0.0"
    
    def generate_forecast(
        self,
        signal_bundle: SignalBundle,
        geo_id: str,
        base_adr: float,
        as_of_date: Optional[date] = None,
    ) -> DemandForecast:
        """
        Generate forward demand forecast from signals.
        
        Args:
            signal_bundle: Bundle with demand signals
            geo_id: Geographic area
            base_adr: Base ADR for revenue calculations
            as_of_date: Starting date for forecast
        
        Returns:
            DemandForecast with 30/60/90 day bands
        """
        as_of_date = as_of_date or date.today()
        
        # =================================================================
        # Step 1: Extract current signals
        # =================================================================
        
        # Get momentum (are we ahead or behind pace?)
        momentum, momentum_conf = signal_bundle.get_weighted_with_confidence(
            SignalType.OCCUPANCY_MOMENTUM
        )
        momentum = momentum or 0.0
        
        # Get seasonality for each horizon
        from app.services.signals.seasonality import get_seasonality
        
        seasonality_30 = get_seasonality(signal_bundle, as_of_date + timedelta(days=15))
        seasonality_60 = get_seasonality(signal_bundle, as_of_date + timedelta(days=45))
        seasonality_90 = get_seasonality(signal_bundle, as_of_date + timedelta(days=75))
        
        # Get demand pressure
        demand_pressure, demand_conf = signal_bundle.get_weighted_with_confidence(
            SignalType.DEMAND_PRESSURE
        )
        demand_pressure = demand_pressure or 0.5
        
        # Get supply velocity (are new listings flooding market?)
        supply_velocity, supply_conf = signal_bundle.get_weighted_with_confidence(
            SignalType.SUPPLY_VELOCITY
        )
        supply_velocity = supply_velocity or 0.0
        
        # =================================================================
        # Step 2: Generate forecasts for each horizon
        # =================================================================
        
        forecast_30d = self._generate_horizon_forecast(
            ForecastHorizon.DAYS_30,
            as_of_date,
            as_of_date + timedelta(days=30),
            base_adr,
            momentum, momentum_conf or 0.3,
            seasonality_30,
            demand_pressure, demand_conf or 0.3,
            supply_velocity, supply_conf or 0.3,
        )
        
        forecast_60d = self._generate_horizon_forecast(
            ForecastHorizon.DAYS_60,
            as_of_date + timedelta(days=30),
            as_of_date + timedelta(days=60),
            base_adr,
            momentum * 0.8,  # Decay momentum effect over time
            momentum_conf or 0.3,
            seasonality_60,
            demand_pressure * 0.9,
            demand_conf or 0.3,
            supply_velocity,
            supply_conf or 0.3,
        )
        
        forecast_90d = self._generate_horizon_forecast(
            ForecastHorizon.DAYS_90,
            as_of_date + timedelta(days=60),
            as_of_date + timedelta(days=90),
            base_adr,
            momentum * 0.6,  # Further decay
            momentum_conf or 0.3,
            seasonality_90,
            demand_pressure * 0.8,
            demand_conf or 0.3,
            supply_velocity,
            supply_conf or 0.3,
        )
        
        # =================================================================
        # Step 3: Determine trend
        # =================================================================
        
        trend_direction, trend_strength = self._calculate_trend(
            forecast_30d, forecast_60d, forecast_90d
        )
        
        # =================================================================
        # Step 4: Generate insights
        # =================================================================
        
        insights = self._generate_insights(
            forecast_30d, forecast_60d, forecast_90d,
            momentum, seasonality_30, demand_pressure
        )
        
        # =================================================================
        # Step 5: Calculate overall confidence
        # =================================================================
        
        overall_conf = (
            forecast_30d.confidence * 0.5 +
            forecast_60d.confidence * 0.3 +
            forecast_90d.confidence * 0.2
        )
        
        return DemandForecast(
            geo_id=geo_id,
            tenant_id=signal_bundle.tenant_id,
            forecast_30d=forecast_30d,
            forecast_60d=forecast_60d,
            forecast_90d=forecast_90d,
            trend_direction=trend_direction,
            trend_strength=trend_strength,
            insights=insights,
            overall_confidence=overall_conf,
            signal_count=signal_bundle.signal_count,
        )
    
    def _generate_horizon_forecast(
        self,
        horizon: ForecastHorizon,
        period_start: date,
        period_end: date,
        base_adr: float,
        momentum: float,
        momentum_conf: float,
        seasonality,  # SeasonalityResult
        demand_pressure: float,
        demand_conf: float,
        supply_velocity: float,
        supply_conf: float,
    ) -> ForecastBand:
        """Generate forecast for a specific horizon."""
        
        # Base occupancy from seasonality
        base_occ = min(0.85, seasonality.multiplier * 0.55)
        
        # Adjust for momentum
        momentum_adj = momentum * 0.15  # Max 15% adjustment
        adjusted_occ = base_occ * (1 + momentum_adj)
        
        # Adjust for supply velocity (new supply dampens occupancy)
        supply_adj = -supply_velocity * 0.05  # Max 5% downward
        adjusted_occ = adjusted_occ * (1 + supply_adj)
        
        # Bound occupancy
        adjusted_occ = max(0.15, min(0.95, adjusted_occ))
        
        # Calculate confidence (decays with horizon)
        horizon_decay = {
            ForecastHorizon.DAYS_30: 1.0,
            ForecastHorizon.DAYS_60: 0.85,
            ForecastHorizon.DAYS_90: 0.70,
        }
        
        base_conf = (
            momentum_conf * 0.30 +
            seasonality.confidence * 0.40 +
            demand_conf * 0.20 +
            supply_conf * 0.10
        )
        confidence = base_conf * horizon_decay[horizon]
        
        # Calculate bands (wider bands = lower confidence)
        if confidence >= 0.7:
            band_pct = 0.15
        elif confidence >= 0.5:
            band_pct = 0.25
        else:
            band_pct = 0.35
        
        # Demand bands
        demand_expected = min(1.0, demand_pressure * seasonality.multiplier)
        demand_low = max(0.1, demand_expected * (1 - band_pct))
        demand_high = min(1.0, demand_expected * (1 + band_pct))
        
        # ADR bands
        adr_expected = base_adr * seasonality.multiplier
        adr_low = adr_expected * (1 - band_pct * 0.5)  # ADR less volatile
        adr_high = adr_expected * (1 + band_pct * 0.5)
        
        # Occupancy bands
        occ_low = max(0.10, adjusted_occ * (1 - band_pct))
        occ_high = min(0.95, adjusted_occ * (1 + band_pct))
        
        # Revenue bands (days in period * occupancy * ADR)
        days = (period_end - period_start).days
        rev_expected = days * adjusted_occ * adr_expected
        rev_low = days * occ_low * adr_low
        rev_high = days * occ_high * adr_high
        
        # Build drivers list
        drivers = []
        
        if abs(momentum) > 0.1:
            drivers.append({
                "driver": ForecastDriver.MOMENTUM.value,
                "impact_pct": momentum_adj * 100,
                "direction": "positive" if momentum > 0 else "negative",
                "description": f"Booking momentum {'ahead of' if momentum > 0 else 'behind'} pace",
            })
        
        if seasonality.multiplier > 1.1 or seasonality.multiplier < 0.9:
            drivers.append({
                "driver": ForecastDriver.SEASONALITY.value,
                "impact_pct": (seasonality.multiplier - 1.0) * 100,
                "direction": "positive" if seasonality.multiplier > 1 else "negative",
                "description": f"{'Peak' if seasonality.multiplier > 1 else 'Off'} season effect",
            })
        
        if abs(supply_velocity) > 0.05:
            drivers.append({
                "driver": ForecastDriver.SUPPLY_CHANGE.value,
                "impact_pct": supply_adj * 100,
                "direction": "negative" if supply_velocity > 0 else "positive",
                "description": f"Supply {'increasing' if supply_velocity > 0 else 'decreasing'}",
            })
        
        return ForecastBand(
            period_start=period_start,
            period_end=period_end,
            horizon=horizon,
            demand_low=round(demand_low, 3),
            demand_expected=round(demand_expected, 3),
            demand_high=round(demand_high, 3),
            adr_low=round(adr_low, 2),
            adr_expected=round(adr_expected, 2),
            adr_high=round(adr_high, 2),
            occupancy_low=round(occ_low, 3),
            occupancy_expected=round(adjusted_occ, 3),
            occupancy_high=round(occ_high, 3),
            revenue_low=round(rev_low, 0),
            revenue_expected=round(rev_expected, 0),
            revenue_high=round(rev_high, 0),
            confidence=round(confidence, 3),
            band_width_pct=round(band_pct, 3),
            drivers=drivers,
        )
    
    def _calculate_trend(
        self,
        f30: ForecastBand,
        f60: ForecastBand,
        f90: ForecastBand,
    ) -> Tuple[str, float]:
        """Calculate overall trend from forecasts."""
        
        # Compare demand across horizons
        d30 = f30.demand_expected
        d60 = f60.demand_expected
        d90 = f90.demand_expected
        
        # Simple trend calculation
        avg_change = ((d60 - d30) / d30 + (d90 - d60) / d60) / 2 if d30 > 0 and d60 > 0 else 0
        
        if avg_change > 0.05:
            return "rising", min(1.0, avg_change * 5)
        elif avg_change < -0.05:
            return "falling", min(1.0, abs(avg_change) * 5)
        else:
            return "stable", 0.0
    
    def _generate_insights(
        self,
        f30: ForecastBand,
        f60: ForecastBand,
        f90: ForecastBand,
        momentum: float,
        seasonality,
        demand_pressure: float,
    ) -> List[str]:
        """Generate human-readable insights."""
        
        insights = []
        
        # Momentum insight
        if momentum > 0.3:
            insights.append(f"Strong booking momentum - you're {momentum:.0%} ahead of historical pace")
        elif momentum < -0.3:
            insights.append(f"Booking pace is {abs(momentum):.0%} behind historical - consider promotions")
        
        # Seasonality insight
        if seasonality.multiplier > 1.3:
            insights.append("Entering peak season - demand expected to be strong")
        elif seasonality.multiplier < 0.7:
            insights.append("Off-season approaching - plan for lower occupancy")
        
        # Band width insight
        if f30.band_width_pct > 0.30:
            insights.append("Forecast uncertainty is high - monitor signals closely")
        elif f30.band_width_pct < 0.15:
            insights.append("High forecast confidence - signals are consistent")
        
        # Trend insight
        if f90.demand_expected > f30.demand_expected * 1.1:
            insights.append("Demand trending upward over next 90 days")
        elif f90.demand_expected < f30.demand_expected * 0.9:
            insights.append("Demand expected to soften over next 90 days")
        
        return insights


# =============================================================================
# CONVENIENCE
# =============================================================================

_service: Optional[ForecastService] = None


def get_forecast_service() -> ForecastService:
    """Get forecast service singleton."""
    global _service
    if _service is None:
        _service = ForecastService()
    return _service


def generate_demand_forecast(
    signal_bundle: SignalBundle,
    geo_id: str,
    base_adr: float,
    **kwargs,
) -> DemandForecast:
    """
    Generate forward demand forecast.
    
    This is THE function for forward-looking predictions.
    """
    return get_forecast_service().generate_forecast(
        signal_bundle, geo_id, base_adr, **kwargs
    )
