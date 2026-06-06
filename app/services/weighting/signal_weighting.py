"""
Time Decay & Geo Weighting - The Secret Sauce.

This is where RentalRevenue.ai leapfrogs AirDNA.

Time Decay:
- Signals decay by RELEVANCE, not just age
- Seasonal signals have different decay than persistent ones
- Forward-looking signals decay faster than historical patterns

Geo-Scoped Weighting:
- Signals are only comparable within polygon context
- Cross-market pollution is prevented
- Weights are LEARNED, not hardcoded

Data-Driven Weighting:
- Weights are adjusted by:
  - Signal confidence
  - Sample size
  - Platform consistency
  - Historical predictive accuracy
"""

from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID
import math

from pydantic import BaseModel, Field

from schemas.signals import (
    Signal,
    SignalBundle,
    SignalType,
    SignalScope,
    DecayProfile,
    GeoSensitivity,
    TimeWindow,
)


# =============================================================================
# DECAY CONFIGURATION
# =============================================================================

@dataclass
class DecayConfig:
    """
    Configuration for signal decay calculation.
    
    decay_factor = exp(-λ * months_since_detected / seasonal_relevance)
    """
    
    # Base decay rate (λ)
    lambda_param: float = 0.1
    
    # Seasonal relevance by decay profile (months)
    profile_relevance: Dict[DecayProfile, float] = field(default_factory=lambda: {
        DecayProfile.PERSISTENT: 24.0,    # 2 year relevance
        DecayProfile.STABLE: 6.0,         # 6 month relevance
        DecayProfile.VOLATILE: 1.0,       # 1 month relevance
        DecayProfile.SEASONAL: 12.0,      # Annual cycle
        DecayProfile.EPHEMERAL: 0.25,     # 1 week relevance
    })
    
    # Signal type overrides
    type_overrides: Dict[SignalType, float] = field(default_factory=lambda: {
        # Platform dominance is very stable
        SignalType.PLATFORM_DOMINANCE: 18.0,
        
        # Amenity lifts change slowly
        SignalType.AMENITY_LIFT: 12.0,
        
        # Seasonality is annual
        SignalType.SEASONALITY_CURVE: 12.0,
        
        # Momentum decays fast
        SignalType.OCCUPANCY_MOMENTUM: 0.5,
        
        # Price elasticity is moderately stable
        SignalType.PRICE_ELASTICITY: 6.0,
        
        # Operator delta is earned over time
        SignalType.OPERATOR_DELTA: 9.0,
        
        # Guest intents change with seasons
        SignalType.GUEST_INTENT_FREQUENCY: 3.0,
    })


class TimeDecayCalculator:
    """
    Calculates time-based decay for signals.
    
    The key insight: signals decay by RELEVANCE, not just age.
    """
    
    def __init__(self, config: Optional[DecayConfig] = None):
        self.config = config or DecayConfig()
    
    def calculate_decay(
        self,
        signal: Signal,
        as_of: Optional[datetime] = None,
    ) -> float:
        """
        Calculate decay factor for a signal.
        
        Returns value between 0 and 1.
        - 1.0 = fully relevant
        - 0.0 = completely stale
        """
        as_of = as_of or datetime.utcnow()
        
        # Calculate months since detection
        time_delta = as_of - signal.detected_at
        months_since = time_delta.total_seconds() / (30 * 24 * 3600)
        
        # Get relevance window
        relevance = self._get_relevance_window(signal)
        
        # Apply decay formula
        decay = math.exp(-self.config.lambda_param * months_since / relevance)
        
        # Apply seasonal boost if applicable
        if signal.decay_profile == DecayProfile.SEASONAL:
            decay = self._apply_seasonal_boost(decay, signal, as_of)
        
        return max(0.0, min(1.0, decay))
    
    def _get_relevance_window(self, signal: Signal) -> float:
        """Get the relevance window in months for a signal."""
        # Check for signal type override first
        if signal.signal_type in self.config.type_overrides:
            return self.config.type_overrides[signal.signal_type]
        
        # Fall back to decay profile
        return self.config.profile_relevance.get(
            signal.decay_profile, 
            6.0  # Default
        )
    
    def _apply_seasonal_boost(
        self,
        base_decay: float,
        signal: Signal,
        as_of: datetime,
    ) -> float:
        """
        Boost seasonal signals when they're in-season.
        
        A signal about July behavior is more relevant in June/July
        than in January.
        """
        # Get the month the signal is about
        if signal.time_window in [TimeWindow.Q1, TimeWindow.Q2, TimeWindow.Q3, TimeWindow.Q4]:
            # Quarter-based signals
            quarter_months = {
                TimeWindow.Q1: [1, 2, 3],
                TimeWindow.Q2: [4, 5, 6],
                TimeWindow.Q3: [7, 8, 9],
                TimeWindow.Q4: [10, 11, 12],
            }
            signal_months = quarter_months.get(signal.time_window, [])
        elif signal.time_window == TimeWindow.PEAK_SEASON:
            signal_months = [6, 7, 8]  # Assume summer peak
        elif signal.time_window == TimeWindow.OFF_SEASON:
            signal_months = [1, 2, 11, 12]
        else:
            return base_decay
        
        current_month = as_of.month
        
        # Boost if we're approaching or in the signal's relevant months
        if current_month in signal_months:
            return min(1.0, base_decay * 1.5)  # 50% boost
        elif (current_month + 1) % 12 in signal_months:
            return min(1.0, base_decay * 1.25)  # 25% boost for approaching
        
        return base_decay
    
    def filter_stale_signals(
        self,
        signals: List[Signal],
        min_decay: float = 0.1,
        as_of: Optional[datetime] = None,
    ) -> List[Signal]:
        """Filter out signals that have decayed below threshold."""
        as_of = as_of or datetime.utcnow()
        return [
            s for s in signals
            if self.calculate_decay(s, as_of) >= min_decay
        ]
    
    def sort_by_relevance(
        self,
        signals: List[Signal],
        as_of: Optional[datetime] = None,
    ) -> List[Signal]:
        """Sort signals by relevance (decay * confidence)."""
        as_of = as_of or datetime.utcnow()
        return sorted(
            signals,
            key=lambda s: self.calculate_decay(s, as_of) * s.confidence,
            reverse=True,
        )


# =============================================================================
# GEO WEIGHTING
# =============================================================================

@dataclass
class GeoWeightConfig:
    """
    Configuration for geo-scoped signal weighting.
    
    Different signal types have different geographic sensitivity.
    """
    
    # How much to weight signals by geo sensitivity
    sensitivity_weights: Dict[GeoSensitivity, float] = field(default_factory=lambda: {
        GeoSensitivity.PROPERTY_ONLY: 1.0,    # Full weight for property signals
        GeoSensitivity.HYPERLOCAL: 0.95,      # Slight discount for neighborhood
        GeoSensitivity.LOCAL: 0.85,           # More discount for city
        GeoSensitivity.REGIONAL: 0.70,        # Significant discount for region
        GeoSensitivity.UNIVERSAL: 0.50,       # Heavy discount for universal
    })
    
    # Signal types that should NOT be aggregated across geos
    geo_isolated_types: List[SignalType] = field(default_factory=lambda: [
        SignalType.SEASONALITY_CURVE,      # Very geo-specific
        SignalType.PLATFORM_DOMINANCE,     # Varies by market
        SignalType.GUEST_INTENT_FREQUENCY, # Property-specific
    ])
    
    # Maximum distance (in conceptual "geo units") for signal applicability
    max_geo_distance: Dict[GeoSensitivity, int] = field(default_factory=lambda: {
        GeoSensitivity.PROPERTY_ONLY: 0,   # Same property only
        GeoSensitivity.HYPERLOCAL: 1,      # Immediate neighbors
        GeoSensitivity.LOCAL: 3,           # Same submarket
        GeoSensitivity.REGIONAL: 10,       # Same DMA
        GeoSensitivity.UNIVERSAL: 100,     # Anywhere
    })


class GeoWeightCalculator:
    """
    Calculates geographic weights for signals.
    
    Key principle: Signals are only comparable within polygon context.
    Cross-market pollution is prevented.
    """
    
    def __init__(self, config: Optional[GeoWeightConfig] = None):
        self.config = config or GeoWeightConfig()
    
    def calculate_geo_weight(
        self,
        signal: Signal,
        target_geo_id: str,
    ) -> float:
        """
        Calculate geographic relevance weight for a signal.
        
        Returns value between 0 and 1.
        """
        # Exact geo match
        if signal.geo_id == target_geo_id:
            return 1.0
        
        # Property-only signals don't apply to other contexts
        if signal.geo_sensitivity == GeoSensitivity.PROPERTY_ONLY:
            return 0.0
        
        # Check if signal type is geo-isolated
        if signal.signal_type in self.config.geo_isolated_types:
            # These types don't transfer between geos
            return 0.0
        
        # For other signals, apply sensitivity-based weight
        return self.config.sensitivity_weights.get(
            signal.geo_sensitivity,
            0.5,
        )
    
    def filter_for_geo(
        self,
        signals: List[Signal],
        target_geo_id: str,
        min_weight: float = 0.1,
    ) -> List[Signal]:
        """Filter signals to those relevant for a geo."""
        return [
            s for s in signals
            if self.calculate_geo_weight(s, target_geo_id) >= min_weight
        ]
    
    def can_aggregate(
        self,
        signal_type: SignalType,
        geo_sensitivity: GeoSensitivity,
    ) -> bool:
        """Check if a signal type can be aggregated across geos."""
        if signal_type in self.config.geo_isolated_types:
            return False
        if geo_sensitivity == GeoSensitivity.PROPERTY_ONLY:
            return False
        return True


# =============================================================================
# SIGNAL WEIGHTING ENGINE
# =============================================================================

@dataclass 
class WeightLearningData:
    """Data for learning signal weights."""
    signal_type: SignalType
    geo_id: str
    
    # Historical accuracy
    prediction_count: int = 0
    correct_predictions: int = 0
    
    # Sample quality
    avg_sample_size: float = 0.0
    
    # Platform consistency
    platform_variance: float = 0.0
    
    # Computed weight
    learned_weight: float = 1.0


class SignalWeightingEngine:
    """
    Comprehensive signal weighting engine.
    
    Combines:
    - Time decay
    - Geo weighting
    - Confidence
    - Sample size
    - Platform stability
    - Historical accuracy (learned)
    
    final_weight = (
        base_weight
        * confidence
        * decay_factor
        * geo_weight
        * platform_stability
        * learned_adjustment
    )
    """
    
    def __init__(
        self,
        decay_config: Optional[DecayConfig] = None,
        geo_config: Optional[GeoWeightConfig] = None,
    ):
        self.decay_calc = TimeDecayCalculator(decay_config)
        self.geo_calc = GeoWeightCalculator(geo_config)
        
        # Base weights by signal type
        self.base_weights: Dict[SignalType, float] = {
            SignalType.PLATFORM_DOMINANCE: 1.2,
            SignalType.AMENITY_LIFT: 1.0,
            SignalType.SEASONALITY_CURVE: 1.3,
            SignalType.OCCUPANCY_MOMENTUM: 0.9,
            SignalType.PRICE_ELASTICITY: 1.0,
            SignalType.OPERATOR_DELTA: 1.1,
            SignalType.GUEST_INTENT_FREQUENCY: 0.8,
        }
        
        # Learned adjustments (would be loaded from database)
        self.learned_weights: Dict[Tuple[SignalType, str], float] = {}
    
    def calculate_weight(
        self,
        signal: Signal,
        target_geo_id: str,
        as_of: Optional[datetime] = None,
    ) -> float:
        """
        Calculate comprehensive weight for a signal.
        
        This is the core weighting function that everything uses.
        """
        as_of = as_of or datetime.utcnow()
        
        # Base weight
        base = self.base_weights.get(signal.signal_type, 1.0)
        
        # Confidence factor
        confidence = signal.confidence
        
        # Time decay
        decay = self.decay_calc.calculate_decay(signal, as_of)
        
        # Geo weight
        geo = self.geo_calc.calculate_geo_weight(signal, target_geo_id)
        
        # Platform stability (from metadata if available)
        platform_stability = self._get_platform_stability(signal)
        
        # Learned adjustment
        learned = self._get_learned_weight(signal.signal_type, target_geo_id)
        
        # Combine all factors
        final_weight = (
            base
            * confidence
            * decay
            * geo
            * platform_stability
            * learned
        )
        
        return max(0.0, min(2.0, final_weight))
    
    def _get_platform_stability(self, signal: Signal) -> float:
        """
        Get platform stability factor from signal metadata.
        
        Signals from consistent platforms get higher weight.
        """
        metadata = signal.metadata or {}
        
        # Check if metadata has platform variance
        variance = metadata.get("platform_variance")
        if variance is not None:
            # Lower variance = higher stability
            return max(0.5, 1.0 - variance)
        
        # Check if sample size is good
        sample_size = metadata.get("sample_size", 0)
        if sample_size > 200:
            return 1.1  # Bonus for large samples
        elif sample_size > 100:
            return 1.0
        elif sample_size > 50:
            return 0.9
        else:
            return 0.7  # Penalty for small samples
    
    def _get_learned_weight(
        self, 
        signal_type: SignalType, 
        geo_id: str,
    ) -> float:
        """
        Get learned weight adjustment for signal type in geo.
        
        This is where historical accuracy influences weighting.
        """
        key = (signal_type, geo_id)
        
        if key in self.learned_weights:
            return self.learned_weights[key]
        
        # Fall back to signal type average
        type_weights = [
            w for (t, g), w in self.learned_weights.items()
            if t == signal_type
        ]
        
        if type_weights:
            return sum(type_weights) / len(type_weights)
        
        return 1.0  # Default
    
    def update_learned_weight(
        self,
        signal_type: SignalType,
        geo_id: str,
        prediction_accuracy: float,
        sample_count: int = 1,
    ):
        """
        Update learned weight based on prediction accuracy.
        
        Called after we verify a prediction against actual outcomes.
        """
        key = (signal_type, geo_id)
        
        current = self.learned_weights.get(key, 1.0)
        
        # Exponential moving average
        alpha = min(0.3, sample_count / 100)  # Learning rate
        new_weight = current * (1 - alpha) + prediction_accuracy * alpha
        
        # Keep in reasonable bounds
        self.learned_weights[key] = max(0.5, min(1.5, new_weight))
    
    def weight_signals(
        self,
        signals: List[Signal],
        target_geo_id: str,
        as_of: Optional[datetime] = None,
    ) -> List[Tuple[Signal, float]]:
        """
        Weight a list of signals and return with weights.
        """
        as_of = as_of or datetime.utcnow()
        
        return [
            (s, self.calculate_weight(s, target_geo_id, as_of))
            for s in signals
        ]
    
    def weighted_aggregate(
        self,
        signals: List[Signal],
        target_geo_id: str,
        as_of: Optional[datetime] = None,
    ) -> Optional[float]:
        """
        Compute weighted aggregate of signal values.
        """
        weighted = self.weight_signals(signals, target_geo_id, as_of)
        
        if not weighted:
            return None
        
        total_weight = sum(w for _, w in weighted)
        if total_weight == 0:
            return None
        
        weighted_sum = sum(s.value * w for s, w in weighted)
        return weighted_sum / total_weight
    
    def prepare_bundle_for_analytics(
        self,
        signals: List[Signal],
        target_geo_id: str,
        target_property_id: Optional[UUID] = None,
        min_weight: float = 0.05,
        as_of: Optional[datetime] = None,
    ) -> SignalBundle:
        """
        Prepare a weighted, filtered signal bundle for analytics engine.
        
        This is the handoff point between raw signals and analytics.
        """
        as_of = as_of or datetime.utcnow()
        
        # Weight all signals
        weighted = self.weight_signals(signals, target_geo_id, as_of)
        
        # Filter by minimum weight
        valid_signals = [s for s, w in weighted if w >= min_weight]
        
        # Update weight hints in signals
        for signal in valid_signals:
            # Find the calculated weight
            for s, w in weighted:
                if s.signal_id == signal.signal_id:
                    signal.weight_hint = w
                    break
        
        return SignalBundle(
            tenant_id=signals[0].tenant_id if signals else UUID(int=0),
            geo_id=target_geo_id,
            property_id=target_property_id,
            signals=valid_signals,
            collected_at=as_of,
        )


# =============================================================================
# GEO SENSITIVITY REFERENCE TABLE
# =============================================================================

"""
Signal Type to Geo Sensitivity Mapping:

Signal Type              | Geo Sensitivity | Notes
-------------------------|-----------------|----------------------------------
Platform Dominance       | HIGH            | Very market-specific
Amenity Lift             | MEDIUM          | Varies by market but some universal
Seasonality Curve        | VERY HIGH       | Extremely market-specific
Occupancy Momentum       | HIGH            | Market conditions vary
Price Elasticity         | MEDIUM          | Some patterns transfer
Guest Intent Frequency   | PROPERTY ONLY   | Specific to property/listing
Operator Delta           | LOCAL           | Operator performance is contextual
Competitor Rate Movement | HIGH            | Market-specific
Expansion Fit            | LOW             | More universal patterns
"""

GEO_SENSITIVITY_BY_TYPE: Dict[SignalType, GeoSensitivity] = {
    SignalType.PLATFORM_DOMINANCE: GeoSensitivity.LOCAL,
    SignalType.AMENITY_LIFT: GeoSensitivity.LOCAL,
    SignalType.SEASONALITY_CURVE: GeoSensitivity.HYPERLOCAL,
    SignalType.OCCUPANCY_MOMENTUM: GeoSensitivity.LOCAL,
    SignalType.PRICE_ELASTICITY: GeoSensitivity.LOCAL,
    SignalType.OPERATOR_DELTA: GeoSensitivity.LOCAL,
    SignalType.GUEST_INTENT_FREQUENCY: GeoSensitivity.PROPERTY_ONLY,
    SignalType.RATE_POSITION: GeoSensitivity.HYPERLOCAL,
    SignalType.BOOKING_LEAD_TIME: GeoSensitivity.LOCAL,
    SignalType.REVENUE_TRAJECTORY: GeoSensitivity.LOCAL,
    SignalType.SENTIMENT_TREND: GeoSensitivity.PROPERTY_ONLY,
    SignalType.UNMET_DEMAND: GeoSensitivity.LOCAL,
    SignalType.COMPETITOR_RATE_MOVEMENT: GeoSensitivity.HYPERLOCAL,
    SignalType.INVENTORY_PRESSURE: GeoSensitivity.LOCAL,
    SignalType.MARKET_SIMILARITY: GeoSensitivity.REGIONAL,
    SignalType.EXPANSION_FIT: GeoSensitivity.REGIONAL,
}


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

_weighting_engine: Optional[SignalWeightingEngine] = None


def get_weighting_engine() -> SignalWeightingEngine:
    """Get or create weighting engine singleton."""
    global _weighting_engine
    if _weighting_engine is None:
        _weighting_engine = SignalWeightingEngine()
    return _weighting_engine


def calculate_signal_weight(
    signal: Signal,
    target_geo_id: str,
    as_of: Optional[datetime] = None,
) -> float:
    """Convenience function to calculate a signal's weight."""
    return get_weighting_engine().calculate_weight(signal, target_geo_id, as_of)


def prepare_signals_for_analytics(
    signals: List[Signal],
    target_geo_id: str,
    target_property_id: Optional[UUID] = None,
) -> SignalBundle:
    """Convenience function to prepare signals for analytics."""
    return get_weighting_engine().prepare_bundle_for_analytics(
        signals, target_geo_id, target_property_id
    )
