"""
Platform Weighting Engine v1.

Implements data-driven platform weighting for multi-source market intelligence:
- EWMA (Exponentially Weighted Moving Average) for time decay
- Platform dominance detection (Airbnb vs VRBO vs Booking)
- Geofence-specific signal aggregation
- Seasonal curve detection (monthly, weekly, holiday)

Key Principles:
1. Weights are DATA-DRIVEN, not static
2. VRBO data is a PERIPHERAL SIGNAL, not primary truth
3. Platform weights adjust based on relevance + coverage + reliability
4. Seasonal trends are detected and factored separately from platform dominance

What VRBO/External Data CAN Be Used For:
- Supply counts
- Amenity prevalence  
- Price posture (directional only)
- Availability compression
- Listing churn

What VRBO/External Data CANNOT Be Used For:
- Booking data (not publicly available)
- Revenue numbers (not publicly available)
- Occupancy claims (inference risk)
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4
import math

from pydantic import BaseModel, Field, ConfigDict


# =============================================================================
# PLATFORM DEFINITIONS
# =============================================================================

class Platform(str, Enum):
    """Supported OTA platforms."""
    AIRBNB = "airbnb"
    VRBO = "vrbo"
    BOOKING = "booking"
    MLS = "mls"  # Not an OTA but a data source
    INTERNAL = "internal"  # Operator's own data


class MarketClass(str, Enum):
    """Market classification for baseline weights."""
    LUXURY = "luxury"
    MIDSCALE = "midscale"
    BUDGET = "budget"
    URBAN = "urban"
    RESORT = "resort"
    MIXED = "mixed"


# Baseline platform weights by market class
# These are starting points - actual weights are computed dynamically
BASELINE_PLATFORM_WEIGHTS = {
    MarketClass.LUXURY: {
        Platform.AIRBNB: 0.35,
        Platform.VRBO: 0.55,
        Platform.BOOKING: 0.10,
    },
    MarketClass.MIDSCALE: {
        Platform.AIRBNB: 0.50,
        Platform.VRBO: 0.35,
        Platform.BOOKING: 0.15,
    },
    MarketClass.BUDGET: {
        Platform.AIRBNB: 0.60,
        Platform.VRBO: 0.20,
        Platform.BOOKING: 0.20,
    },
    MarketClass.URBAN: {
        Platform.AIRBNB: 0.70,
        Platform.VRBO: 0.15,
        Platform.BOOKING: 0.15,
    },
    MarketClass.RESORT: {
        Platform.AIRBNB: 0.40,
        Platform.VRBO: 0.50,
        Platform.BOOKING: 0.10,
    },
    MarketClass.MIXED: {
        Platform.AIRBNB: 0.50,
        Platform.VRBO: 0.30,
        Platform.BOOKING: 0.20,
    },
}


# Signal quality modifiers - not all signals are equally reliable
SIGNAL_QUALITY_MODIFIERS = {
    "supply_count": 1.25,  # High quality
    "amenity_prevalence": 1.15,
    "availability_pressure": 1.20,
    "price_posture": 1.10,
    "listing_growth": 1.15,
    "review_velocity": 1.05,
    "calendar_inference": 0.80,  # Lower quality - inference risk
}


# =============================================================================
# EWMA (EXPONENTIALLY WEIGHTED MOVING AVERAGE)
# =============================================================================

@dataclass
class EWMAState:
    """
    State for Exponentially Weighted Moving Average.
    
    EWMA provides time decay: older signals matter less.
    Formula: health_t = α * current_signal + (1 - α) * health_{t-1}
    
    Why EWMA:
    - Stable markets stay stable
    - Shocks cause appropriate weight shifts
    - No arbitrary cutoff dates
    """
    value: float = 0.0
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    sample_count: int = 0
    
    # Decay factor: higher = more responsive to new data
    # 0.1 = very stable, 0.3 = moderate, 0.5 = responsive
    alpha: float = 0.2


class EWMACalculator:
    """
    Calculate Exponentially Weighted Moving Averages.
    
    Use Cases:
    - Platform health scores
    - Demand pressure signals
    - Price posture trends
    """
    
    @staticmethod
    def update(state: EWMAState, new_value: float) -> EWMAState:
        """
        Update EWMA with a new observation.
        
        If this is the first observation, use it directly.
        Otherwise, blend with existing state.
        """
        if state.sample_count == 0:
            return EWMAState(
                value=new_value,
                last_updated=datetime.now(timezone.utc),
                sample_count=1,
                alpha=state.alpha,
            )
        
        # EWMA formula
        new_ewma = state.alpha * new_value + (1 - state.alpha) * state.value
        
        return EWMAState(
            value=new_ewma,
            last_updated=datetime.now(timezone.utc),
            sample_count=state.sample_count + 1,
            alpha=state.alpha,
        )
    
    @staticmethod
    def apply_time_decay(state: EWMAState, decay_days: int = 7) -> float:
        """
        Apply additional time decay to EWMA value.
        
        If data is stale, reduce confidence in the value.
        """
        if state.sample_count == 0:
            return 0.0
        
        days_old = (datetime.now(timezone.utc) - state.last_updated).days
        
        if days_old <= 0:
            return state.value
        
        # Exponential decay based on staleness
        decay_factor = math.exp(-days_old / decay_days)
        
        return state.value * decay_factor


# =============================================================================
# PLATFORM SIGNAL AGGREGATION
# =============================================================================

class PlatformSignals(BaseModel):
    """
    Signals collected from a single platform in a geofence.
    
    These are the SAFE signals we can use from external platforms.
    """
    platform: Platform
    geofence_id: str
    
    # Supply signals (SAFE)
    listing_count: int = 0
    listing_growth_30d_pct: float = 0.0  # % change in listings
    new_listings_30d: int = 0
    removed_listings_30d: int = 0
    
    # Amenity signals (SAFE)
    pct_with_pool: float = 0.0
    pct_with_waterfront: float = 0.0
    pct_with_pet_friendly: float = 0.0
    pct_luxury: float = 0.0  # Inferred from price tier
    
    # Availability signals (SAFE - directional only)
    pct_unavailable_next_7: float = 0.0
    pct_unavailable_next_14: float = 0.0
    pct_unavailable_next_30: float = 0.0
    
    # Price posture (SAFE - directional only)
    price_trend: str = "stable"  # "rising", "falling", "stable"
    price_change_30d_pct: float = 0.0
    
    # Review signals (SAFE)
    avg_review_count: float = 0.0
    review_velocity_30d: float = 0.0  # New reviews per listing
    
    # Metadata
    snapshot_date: date = Field(default_factory=date.today)
    confidence: float = 0.5  # How much data we have
    
    model_config = ConfigDict(use_enum_values=True)


class PlatformHealthScore(BaseModel):
    """
    Computed health score for a platform in a geofence.
    
    Higher score = platform is more dominant/active in this market.
    """
    platform: Platform
    geofence_id: str
    
    # Raw health score (0-1)
    health_score: float
    
    # Component scores
    supply_score: float
    demand_score: float
    activity_score: float
    
    # EWMA state (for time decay)
    ewma_health: float
    samples: int
    
    # Computed weight (after normalization)
    normalized_weight: float = 0.0
    
    # Metadata
    computed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = ConfigDict(use_enum_values=True)


# =============================================================================
# PLATFORM WEIGHTING ENGINE
# =============================================================================

class PlatformWeightingEngine:
    """
    Compute data-driven platform weights for a geofence.
    
    The engine:
    1. Collects signals from each platform
    2. Computes health scores using EWMA
    3. Normalizes into weights
    4. Adjusts for signal quality and coverage
    
    Key Properties:
    - Weights are dynamic, not static
    - Time decay ensures responsiveness to change
    - Coverage gaps reduce weight automatically
    """
    
    def __init__(self, market_class: MarketClass = MarketClass.MIXED):
        self.market_class = market_class
        self.baseline_weights = BASELINE_PLATFORM_WEIGHTS[market_class]
        
        # EWMA states per platform per geofence
        self._ewma_states: Dict[str, Dict[Platform, EWMAState]] = {}
    
    def _get_ewma_state(
        self, 
        geofence_id: str, 
        platform: Platform,
    ) -> EWMAState:
        """Get or create EWMA state for a platform in a geofence."""
        if geofence_id not in self._ewma_states:
            self._ewma_states[geofence_id] = {}
        
        if platform not in self._ewma_states[geofence_id]:
            self._ewma_states[geofence_id][platform] = EWMAState(
                alpha=0.2  # Moderate responsiveness
            )
        
        return self._ewma_states[geofence_id][platform]
    
    def compute_health_score(
        self,
        signals: PlatformSignals,
    ) -> PlatformHealthScore:
        """
        Compute platform health score from signals.
        
        Formula: Weight = f(Relevance, Coverage, Reliability)
        
        Health = (supply_score × quality_mod + demand_score × quality_mod + activity_score × quality_mod)
                 × coverage_factor
        
        This implements:
        - More weight where data is richer (coverage)
        - More weight where market fits platform (baseline relevance)
        - Less weight where data is thin/noisy (quality modifiers)
        """
        # Get signal quality modifiers
        supply_quality = SIGNAL_QUALITY_MODIFIERS.get("supply_count", 1.0)
        availability_quality = SIGNAL_QUALITY_MODIFIERS.get("availability_pressure", 1.0)
        price_quality = SIGNAL_QUALITY_MODIFIERS.get("price_posture", 1.0)
        review_quality = SIGNAL_QUALITY_MODIFIERS.get("review_velocity", 1.0)
        
        # Supply score (listing count + growth) × quality modifier
        supply_raw = min(signals.listing_count / 500, 1.0)  # Normalize to 500 listings
        growth_bonus = max(0, signals.listing_growth_30d_pct) * 0.5
        supply_score = min(supply_raw + growth_bonus, 1.0) * supply_quality
        
        # Demand score (availability compression) × quality modifier
        # Higher unavailability = higher demand
        demand_score = (
            signals.pct_unavailable_next_7 * 0.4 +
            signals.pct_unavailable_next_14 * 0.35 +
            signals.pct_unavailable_next_30 * 0.25
        ) * availability_quality
        
        # Activity score (review velocity + price movement) × quality modifiers
        review_activity = min(signals.review_velocity_30d / 2.0, 1.0) * review_quality
        price_activity = abs(signals.price_change_30d_pct) * 2 * price_quality
        activity_score = (review_activity * 0.6 + min(price_activity, 1.0) * 0.4)
        
        # Combined health score (weighted by signal type)
        health_score = (
            supply_score * 0.40 +
            demand_score * 0.40 +
            activity_score * 0.20
        )
        
        # Apply coverage factor (less data = lower score)
        # coverage_factor = min(1, listings_found / expected_listings)
        # signals.confidence already encapsulates this
        coverage_factor = signals.confidence
        health_score *= coverage_factor
        
        # Update EWMA (time decay)
        ewma_state = self._get_ewma_state(signals.geofence_id, signals.platform)
        new_ewma_state = EWMACalculator.update(ewma_state, health_score)
        self._ewma_states[signals.geofence_id][signals.platform] = new_ewma_state
        
        return PlatformHealthScore(
            platform=signals.platform,
            geofence_id=signals.geofence_id,
            health_score=round(health_score, 3),
            supply_score=round(supply_score / supply_quality, 3),  # Store raw for transparency
            demand_score=round(demand_score / availability_quality, 3),
            activity_score=round(activity_score, 3),
            ewma_health=round(new_ewma_state.value, 3),
            samples=new_ewma_state.sample_count,
        )
    
    def compute_platform_weights(
        self,
        geofence_id: str,
        platform_signals: List[PlatformSignals],
    ) -> Dict[Platform, float]:
        """
        Compute normalized platform weights for a geofence.
        
        Returns weights that sum to 1.0.
        """
        # Compute health scores for each platform
        health_scores: Dict[Platform, float] = {}
        
        for signals in platform_signals:
            health = self.compute_health_score(signals)
            health_scores[signals.platform] = health.ewma_health
        
        # Get baseline weights
        total_health = sum(health_scores.values())
        
        if total_health == 0:
            # No data - use baseline weights
            return dict(self.baseline_weights)
        
        # Compute data-driven weights
        weights = {}
        for platform, health in health_scores.items():
            # Blend baseline with computed
            baseline = self.baseline_weights.get(platform, 0.33)
            computed = health / total_health
            
            # 60% data-driven, 40% baseline (for stability)
            weights[platform] = 0.6 * computed + 0.4 * baseline
        
        # Normalize to sum to 1.0
        total = sum(weights.values())
        if total > 0:
            weights = {p: w / total for p, w in weights.items()}
        
        return weights


# =============================================================================
# SEASONAL CURVE DETECTION
# =============================================================================

class SeasonalCurve(BaseModel):
    """
    Detected seasonal pattern for a geofence.
    
    Seasonality affects demand signals, NOT platform dominance.
    """
    geofence_id: str
    
    # Monthly factors (1.0 = baseline)
    monthly_factors: Dict[int, float] = Field(
        default_factory=lambda: {m: 1.0 for m in range(1, 13)}
    )
    
    # Weekly factors
    weekday_factor: float = 1.0
    weekend_factor: float = 1.0
    
    # Holiday factors
    holiday_factors: Dict[str, float] = Field(default_factory=dict)
    
    # Peak/trough identification
    peak_months: List[int] = Field(default_factory=list)
    trough_months: List[int] = Field(default_factory=list)
    
    # Confidence
    confidence: float = 0.5
    samples: int = 0


class SeasonalityDetector:
    """
    Detect seasonal patterns from historical signals.
    
    Uses availability compression and price posture over time
    to identify seasonal curves.
    """
    
    # Default seasonal curves by market type
    DEFAULT_CURVES = {
        MarketClass.LUXURY: {
            1: 0.70, 2: 0.75, 3: 1.10, 4: 0.90, 5: 1.00, 6: 1.35,
            7: 1.45, 8: 1.15, 9: 0.80, 10: 0.85, 11: 0.75, 12: 0.90
        },
        MarketClass.RESORT: {
            1: 0.60, 2: 0.65, 3: 1.15, 4: 0.85, 5: 0.95, 6: 1.40,
            7: 1.50, 8: 1.20, 9: 0.75, 10: 0.80, 11: 0.70, 12: 0.85
        },
        MarketClass.URBAN: {
            1: 0.85, 2: 0.90, 3: 0.95, 4: 1.00, 5: 1.05, 6: 1.10,
            7: 1.05, 8: 1.00, 9: 1.05, 10: 1.10, 11: 1.00, 12: 0.95
        },
        MarketClass.MIXED: {
            1: 0.80, 2: 0.85, 3: 1.00, 4: 0.95, 5: 1.00, 6: 1.20,
            7: 1.25, 8: 1.10, 9: 0.90, 10: 0.95, 11: 0.85, 12: 0.90
        },
    }
    
    # US Holiday factors
    HOLIDAY_FACTORS = {
        "new_years": 1.30,
        "mlk_day": 1.05,
        "presidents_day": 1.10,
        "memorial_day": 1.25,
        "july_4th": 1.40,
        "labor_day": 1.20,
        "columbus_day": 1.05,
        "thanksgiving": 1.35,
        "christmas": 1.45,
    }
    
    def __init__(self, market_class: MarketClass = MarketClass.MIXED):
        self.market_class = market_class
        self._historical_signals: Dict[str, List[Tuple[date, float]]] = {}
    
    def add_signal(
        self,
        geofence_id: str,
        signal_date: date,
        demand_signal: float,  # 0-1, from availability compression
    ) -> None:
        """Add a historical demand signal for seasonal detection."""
        if geofence_id not in self._historical_signals:
            self._historical_signals[geofence_id] = []
        
        self._historical_signals[geofence_id].append((signal_date, demand_signal))
    
    def detect_seasonal_curve(
        self,
        geofence_id: str,
    ) -> SeasonalCurve:
        """
        Detect seasonal curve from historical signals.
        
        If not enough data, return default curve for market type.
        """
        signals = self._historical_signals.get(geofence_id, [])
        
        # Need at least 6 months of data for detection
        if len(signals) < 180:
            # Use default curve
            default = self.DEFAULT_CURVES.get(
                self.market_class, 
                self.DEFAULT_CURVES[MarketClass.MIXED]
            )
            
            peak_months = [m for m, f in default.items() if f >= 1.2]
            trough_months = [m for m, f in default.items() if f <= 0.75]
            
            return SeasonalCurve(
                geofence_id=geofence_id,
                monthly_factors=default,
                weekday_factor=0.95,
                weekend_factor=1.10,
                holiday_factors=self.HOLIDAY_FACTORS,
                peak_months=peak_months,
                trough_months=trough_months,
                confidence=0.5,  # Low confidence - using defaults
                samples=len(signals),
            )
        
        # Group signals by month
        monthly_signals: Dict[int, List[float]] = {m: [] for m in range(1, 13)}
        
        for signal_date, demand in signals:
            monthly_signals[signal_date.month].append(demand)
        
        # Compute monthly averages
        monthly_averages = {}
        for month, values in monthly_signals.items():
            if values:
                monthly_averages[month] = sum(values) / len(values)
            else:
                monthly_averages[month] = 0.5  # Default
        
        # Normalize to factors (1.0 = average)
        overall_avg = sum(monthly_averages.values()) / 12
        if overall_avg > 0:
            monthly_factors = {
                m: round(v / overall_avg, 2) 
                for m, v in monthly_averages.items()
            }
        else:
            monthly_factors = {m: 1.0 for m in range(1, 13)}
        
        # Identify peaks and troughs
        peak_months = [m for m, f in monthly_factors.items() if f >= 1.2]
        trough_months = [m for m, f in monthly_factors.items() if f <= 0.75]
        
        return SeasonalCurve(
            geofence_id=geofence_id,
            monthly_factors=monthly_factors,
            weekday_factor=0.95,
            weekend_factor=1.10,
            holiday_factors=self.HOLIDAY_FACTORS,
            peak_months=peak_months,
            trough_months=trough_months,
            confidence=min(len(signals) / 365, 0.95),
            samples=len(signals),
        )
    
    def get_seasonal_factor(
        self,
        curve: SeasonalCurve,
        target_date: date,
    ) -> float:
        """
        Get the seasonal factor for a specific date.
        
        Combines monthly + weekly + holiday effects.
        """
        # Monthly factor
        monthly = curve.monthly_factors.get(target_date.month, 1.0)
        
        # Weekly factor (weekday = 0-4, weekend = 5-6)
        if target_date.weekday() >= 5:
            weekly = curve.weekend_factor
        else:
            weekly = curve.weekday_factor
        
        # Holiday factor (simplified - would need holiday calendar)
        holiday = 1.0
        # Could check against holiday calendar here
        
        return monthly * weekly * holiday


# =============================================================================
# GEOFENCE SIGNAL AGGREGATOR
# =============================================================================

class GeofenceSignalAggregator:
    """
    Aggregate signals across platforms for a user-defined polygon.
    
    This is the main interface for the market intelligence system.
    """
    
    def __init__(self, market_class: MarketClass = MarketClass.MIXED):
        self.weighting_engine = PlatformWeightingEngine(market_class)
        self.seasonality_detector = SeasonalityDetector(market_class)
        self.market_class = market_class
    
    def aggregate_market_signals(
        self,
        geofence_id: str,
        platform_signals: List[PlatformSignals],
        target_date: date = None,
    ) -> Dict[str, Any]:
        """
        Aggregate all platform signals into unified market intelligence.
        
        Returns:
        - Platform weights
        - Weighted demand signal
        - Seasonal factors
        - Market health indicators
        """
        target_date = target_date or date.today()
        
        # Compute platform weights
        platform_weights = self.weighting_engine.compute_platform_weights(
            geofence_id, platform_signals
        )
        
        # Compute weighted signals
        weighted_supply = 0.0
        weighted_demand = 0.0
        weighted_amenity_pool = 0.0
        weighted_amenity_waterfront = 0.0
        
        for signals in platform_signals:
            weight = platform_weights.get(signals.platform, 0.0)
            
            # Weighted supply
            weighted_supply += signals.listing_count * weight
            
            # Weighted demand (from availability compression)
            demand = (
                signals.pct_unavailable_next_7 * 0.4 +
                signals.pct_unavailable_next_14 * 0.35 +
                signals.pct_unavailable_next_30 * 0.25
            )
            weighted_demand += demand * weight
            
            # Weighted amenities
            weighted_amenity_pool += signals.pct_with_pool * weight
            weighted_amenity_waterfront += signals.pct_with_waterfront * weight
            
            # Add to seasonal detector
            self.seasonality_detector.add_signal(
                geofence_id, signals.snapshot_date, demand
            )
        
        # Get seasonal curve
        seasonal_curve = self.seasonality_detector.detect_seasonal_curve(geofence_id)
        seasonal_factor = self.seasonality_detector.get_seasonal_factor(
            seasonal_curve, target_date
        )
        
        # Apply seasonal adjustment to demand
        seasonally_adjusted_demand = weighted_demand * seasonal_factor
        
        # Compute market health index
        market_health = min(100, (
            seasonally_adjusted_demand * 50 +
            (weighted_supply / 500) * 30 +
            (1 - abs(platform_weights.get(Platform.AIRBNB, 0.5) - 0.5)) * 20
        ))
        
        return {
            "geofence_id": geofence_id,
            "computed_at": datetime.now(timezone.utc).isoformat(),
            
            # Platform weights (data-driven)
            "platform_weights": {
                k.value if hasattr(k, 'value') else k: round(v, 3) 
                for k, v in platform_weights.items()
            },
            
            # Market signals
            "total_supply": int(weighted_supply),
            "demand_pressure": round(weighted_demand, 3),
            "demand_pressure_seasonally_adjusted": round(seasonally_adjusted_demand, 3),
            
            # Amenity saturation (weighted)
            "amenity_saturation": {
                "pool": round(weighted_amenity_pool, 3),
                "waterfront": round(weighted_amenity_waterfront, 3),
            },
            
            # Seasonality
            "seasonal_factor": round(seasonal_factor, 2),
            "peak_months": seasonal_curve.peak_months,
            "trough_months": seasonal_curve.trough_months,
            
            # Market health
            "market_health_score": round(market_health, 1),
            
            # Confidence
            "confidence": round(
                sum(s.confidence for s in platform_signals) / max(len(platform_signals), 1),
                2
            ),
            
            # Voice context (for concierge engine)
            "voice_context": self._build_voice_context(
                weighted_demand, seasonally_adjusted_demand, seasonal_factor, platform_weights
            ),
        }
    
    def _build_voice_context(
        self,
        demand: float,
        seasonally_adjusted_demand: float,
        seasonal_factor: float,
        platform_weights: Dict[Platform, float],
    ) -> Dict[str, Any]:
        """Build voice-safe context for concierge engine."""
        statements = []
        
        # Platform dominance
        if platform_weights:
            max_weight = max(platform_weights.values())
            if max_weight > 0.5:
                statements.append("This market has a concentrated platform distribution")
            else:
                statements.append("This market has a balanced platform distribution")
        
        # Demand pressure
        if seasonally_adjusted_demand > 0.7:
            statements.append("Demand is currently high for these dates")
        elif seasonally_adjusted_demand > 0.5:
            statements.append("Demand is moderate for these dates")
        else:
            statements.append("Demand is currently lower for these dates")
        
        # Seasonal context
        if seasonal_factor > 1.2:
            statements.append("We are in a peak season period")
        elif seasonal_factor < 0.8:
            statements.append("We are in a shoulder season period")
        
        return {
            "statements": statements,
            "market_context": "; ".join(statements),
            "can_deny_discount": seasonally_adjusted_demand > 0.6,
            "seasonal_premium_applies": seasonal_factor > 1.1,
        }
    
    def get_voice_market_context(
        self,
        aggregated: Dict[str, Any],
    ) -> Dict[str, str]:
        """
        Generate voice-safe market context statements.
        
        These statements can be used by the concierge voice engine
        WITHOUT making prohibited claims.
        """
        statements = []
        
        # Platform dominance
        weights = aggregated.get("platform_weights", {})
        dominant = max(weights.items(), key=lambda x: x[1]) if weights else None
        
        if dominant and dominant[1] > 0.5:
            # Don't name competitors - just note market structure
            statements.append(
                "This market has a concentrated platform distribution"
            )
        else:
            statements.append(
                "This market has a balanced platform distribution"
            )
        
        # Demand pressure
        demand = aggregated.get("demand_pressure_seasonally_adjusted", 0.5)
        if demand > 0.7:
            statements.append("Demand is currently high for these dates")
        elif demand > 0.5:
            statements.append("Demand is moderate for these dates")
        else:
            statements.append("Demand is currently lower for these dates")
        
        # Seasonal context
        seasonal = aggregated.get("seasonal_factor", 1.0)
        if seasonal > 1.2:
            statements.append("We are in a peak season period")
        elif seasonal < 0.8:
            statements.append("We are in a shoulder season period")
        
        return {
            "market_context": "; ".join(statements),
            "can_deny_discount": demand > 0.6,
            "seasonal_premium_applies": seasonal > 1.1,
        }
