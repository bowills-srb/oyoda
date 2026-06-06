"""
Platform Weighting Service v2.0 - Signal Consumer Only.

This replaces the calculation logic in platform_weighting.py.

DELETED:
- PlatformWeightingEngine.compute_platform_weights() calculation
- SeasonalityDetector class
- EWMACalculator class
- Inline dominance computation

RETAINED:
- Mapping/interpretation logic
- Signal consumption
- Voice context generation

All weights come from PlatformDominanceDetector via signals.
"""

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from app.services.signals import (
    SignalBundle,
    get_platform_bias,
    get_seasonality,
    PlatformDominanceResult,
    SeasonalityResult,
)


# =============================================================================
# MARKET CLASSIFICATION (Retained for mapping)
# =============================================================================

class MarketClass(str, Enum):
    """Market classification for context."""
    LUXURY = "luxury"
    MIDSCALE = "midscale"
    BUDGET = "budget"
    URBAN = "urban"
    RESORT = "resort"
    MIXED = "mixed"


# =============================================================================
# OUTPUT MODELS
# =============================================================================

@dataclass
class MarketIntelligence:
    """
    Aggregated market intelligence from signals.
    
    This is the output of the signal-based platform weighting service.
    """
    geo_id: str
    computed_at: datetime
    
    # Platform distribution (from PLATFORM_DOMINANCE signal)
    platform_weights: Dict[str, float]
    dominant_platform: str
    platform_confidence: float
    
    # Seasonality (from SEASONALITY_CURVE signal)
    seasonal_factor: float
    peak_months: List[int]
    trough_months: List[int]
    seasonality_confidence: float
    
    # Derived demand signal
    demand_pressure: float  # 0-1
    demand_seasonally_adjusted: float
    
    # Market health index (computed from signals)
    market_health_score: float
    
    # Overall confidence
    overall_confidence: float
    
    # Voice context
    voice_context: Dict[str, Any]


@dataclass
class VoiceContext:
    """Voice-safe context from market intelligence."""
    statements: List[str]
    market_context: str
    can_deny_discount: bool
    seasonal_premium_applies: bool


# =============================================================================
# PLATFORM WEIGHTING SERVICE v2.0
# =============================================================================

class PlatformWeightingServiceV2:
    """
    Platform Weighting Service v2.0 - Signal Consumer Only.
    
    This service:
    - Reads PLATFORM_DOMINANCE signals
    - Reads SEASONALITY_CURVE signals
    - Maps to market intelligence
    - Generates voice context
    
    It does NOT:
    - Calculate platform weights
    - Detect seasonality
    - Apply EWMA
    """
    
    def __init__(self, market_class: MarketClass = MarketClass.MIXED):
        self.market_class = market_class
    
    def get_market_intelligence(
        self,
        signal_bundle: SignalBundle,
        geo_id: str,
        target_date: Optional[date] = None,
    ) -> MarketIntelligence:
        """
        Get market intelligence from signals.
        
        All intelligence comes from signals. No calculation.
        """
        target_date = target_date or date.today()
        
        # =================================================================
        # Get platform bias from signals
        # =================================================================
        platform = get_platform_bias(signal_bundle)
        
        platform_weights = {
            "airbnb": platform.airbnb_share,
            "vrbo": platform.vrbo_share,
            "other": platform.other_share,
        }
        
        # =================================================================
        # Get seasonality from signals
        # =================================================================
        seasonality = get_seasonality(signal_bundle, target_date)
        
        # =================================================================
        # Compute derived metrics (mapping, not detection)
        # =================================================================
        
        # Demand pressure based on seasonality
        demand_pressure = min(1.0, seasonality.multiplier / 1.5)
        demand_adjusted = demand_pressure * seasonality.multiplier
        
        # Market health index (simple mapping)
        market_health = self._compute_health_index(
            platform, seasonality, demand_adjusted
        )
        
        # Overall confidence
        confidence = (
            platform.confidence * 0.4 +
            seasonality.confidence * 0.6
        )
        
        # Voice context
        voice_context = self._build_voice_context(
            platform, seasonality, demand_adjusted
        )
        
        return MarketIntelligence(
            geo_id=geo_id,
            computed_at=datetime.utcnow(),
            platform_weights=platform_weights,
            dominant_platform=platform.dominant_platform,
            platform_confidence=platform.confidence,
            seasonal_factor=seasonality.multiplier,
            peak_months=seasonality.peak_months or [],
            trough_months=seasonality.trough_months or [],
            seasonality_confidence=seasonality.confidence,
            demand_pressure=demand_pressure,
            demand_seasonally_adjusted=demand_adjusted,
            market_health_score=market_health,
            overall_confidence=confidence,
            voice_context=voice_context,
        )
    
    def get_platform_weights(
        self,
        signal_bundle: SignalBundle,
    ) -> Tuple[Dict[str, float], float]:
        """
        Get platform weights from signals.
        
        Returns: (weights_dict, confidence)
        """
        platform = get_platform_bias(signal_bundle)
        
        return {
            "airbnb": platform.airbnb_share,
            "vrbo": platform.vrbo_share,
            "booking": platform.other_share * 0.5,
            "other": platform.other_share * 0.5,
        }, platform.confidence
    
    def get_voice_context(
        self,
        signal_bundle: SignalBundle,
        target_date: Optional[date] = None,
    ) -> VoiceContext:
        """
        Get voice-safe context from signals.
        
        These statements can be used by concierge without making prohibited claims.
        """
        platform = get_platform_bias(signal_bundle)
        seasonality = get_seasonality(signal_bundle, target_date)
        demand = min(1.0, seasonality.multiplier / 1.5) * seasonality.multiplier
        
        return self._build_voice_context(platform, seasonality, demand)
    
    def _compute_health_index(
        self,
        platform: PlatformDominanceResult,
        seasonality: SeasonalityResult,
        demand: float,
    ) -> float:
        """
        Compute market health index from signals.
        
        This is a simple mapping, not detection.
        """
        # Health components
        platform_balance = 1 - abs(platform.airbnb_share - 0.5) * 2
        seasonal_strength = min(1.0, (seasonality.strength or 1.5) / 2.0) if seasonality.strength else 0.5
        demand_health = min(1.0, demand)
        
        # Weighted health score
        health = (
            platform_balance * 0.30 +
            seasonal_strength * 0.30 +
            demand_health * 0.40
        ) * 100
        
        return round(health, 1)
    
    def _build_voice_context(
        self,
        platform: PlatformDominanceResult,
        seasonality: SeasonalityResult,
        demand: float,
    ) -> VoiceContext:
        """Build voice-safe context statements."""
        statements = []
        
        # Platform structure (don't name competitors)
        if platform.is_balanced():
            statements.append("This market has a balanced platform distribution")
        else:
            statements.append("This market has a concentrated platform distribution")
        
        # Demand pressure
        if demand > 0.7:
            statements.append("Demand is currently high for these dates")
        elif demand > 0.5:
            statements.append("Demand is moderate for these dates")
        else:
            statements.append("Demand is currently lower for these dates")
        
        # Seasonal context
        if seasonality.multiplier > 1.2:
            statements.append("We are in a peak season period")
        elif seasonality.multiplier < 0.8:
            statements.append("We are in a shoulder season period")
        
        return VoiceContext(
            statements=statements,
            market_context="; ".join(statements),
            can_deny_discount=demand > 0.6 and seasonality.confidence > 0.5,
            seasonal_premium_applies=seasonality.multiplier > 1.1,
        )


# =============================================================================
# CONVENIENCE
# =============================================================================

_service: Optional[PlatformWeightingServiceV2] = None


def get_platform_weighting_service(
    market_class: MarketClass = MarketClass.MIXED
) -> PlatformWeightingServiceV2:
    """Get platform weighting service."""
    global _service
    if _service is None:
        _service = PlatformWeightingServiceV2(market_class)
    return _service


def get_market_intelligence(
    signal_bundle: SignalBundle,
    geo_id: str,
    target_date: Optional[date] = None,
) -> MarketIntelligence:
    """Convenience function for market intelligence."""
    return get_platform_weighting_service().get_market_intelligence(
        signal_bundle, geo_id, target_date
    )
