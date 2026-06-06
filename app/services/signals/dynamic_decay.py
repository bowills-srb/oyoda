"""
Dynamic Decay Optimization Engine

Static decay is acceptable for v1 systems.
Dynamic decay is what turns this platform into a living market intelligence engine.

This module implements:
1. Base half-lives by signal type (anchor)
2. Dynamic modifiers based on market conditions
3. Bounded, explainable adjustments
4. Full audit trail

Principle: Decay Is a Function, Not a Constant

    half_life_days = f(
        signal_type,
        market_volatility,
        seasonality_phase,
        signal_stability,
        sample_size
    )

Usage:
    from app.services.signals.dynamic_decay import DynamicDecayEngine
    
    engine = DynamicDecayEngine()
    half_life = engine.calculate_half_life(signal, market_context)
"""

from dataclasses import dataclass, field
from datetime import datetime, date
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
import math

from pydantic import BaseModel, Field


# =============================================================================
# CONFIGURATION
# =============================================================================

class SignalCategory(str, Enum):
    """Signal categories for decay grouping."""
    DEMAND = "demand"           # Fast decay (calendar, bookings)
    PRICING = "pricing"         # Medium decay (rates, ADR)
    SUPPLY = "supply"           # Slow decay (listings, inventory)
    STRUCTURAL = "structural"   # Very slow decay (seasonality, amenities)
    OPERATOR = "operator"       # Medium decay (performance)


class SeasonPhase(str, Enum):
    """Season phases that affect decay."""
    PRE_PEAK = "pre_peak"       # Approaching peak - decay faster
    PEAK = "peak"               # In peak - decay faster
    SHOULDER = "shoulder"       # Transition - normal decay
    OFF = "off"                 # Off season - decay slower


class MarketRegime(str, Enum):
    """Market regimes that affect decay."""
    STABLE = "stable"           # Normal decay
    RISING = "rising"           # Faster decay (changing fast)
    VOLATILE = "volatile"       # Fastest decay
    DECLINING = "declining"     # Faster decay


# =============================================================================
# BASE HALF-LIVES (Anchors)
# =============================================================================

# Base half-lives in days - these anchor the system
BASE_HALF_LIVES = {
    # Demand signals - decay quickly
    "calendar_compression": 10,
    "lead_time": 14,
    "rate_acceleration": 14,
    
    # Pricing signals - medium decay
    "rate_position": 21,
    "rate_by_bedroom": 21,
    
    # Supply signals - slower decay
    "supply_density": 30,
    "bedroom_distribution": 45,
    
    # Platform signals - slow decay
    "platform_dominance": 60,
    
    # Structural signals - very slow decay
    "seasonality_curve": 365,
    "amenity_prevalence": 365,
    "amenity_lift": 180,
    "housing_stock": 730,
    
    # Operator signals - medium decay
    "operator_delta": 90,
    
    # Regulatory - slow decay
    "regulatory_risk": 180,
    
    # Macro - varies
    "travel_flow": 90,
    "event_impact": 7,  # Events are ephemeral
}

# Signal type to category mapping
SIGNAL_CATEGORIES = {
    "calendar_compression": SignalCategory.DEMAND,
    "lead_time": SignalCategory.DEMAND,
    "rate_acceleration": SignalCategory.DEMAND,
    "rate_position": SignalCategory.PRICING,
    "rate_by_bedroom": SignalCategory.PRICING,
    "supply_density": SignalCategory.SUPPLY,
    "bedroom_distribution": SignalCategory.SUPPLY,
    "platform_dominance": SignalCategory.STRUCTURAL,
    "seasonality_curve": SignalCategory.STRUCTURAL,
    "amenity_prevalence": SignalCategory.STRUCTURAL,
    "amenity_lift": SignalCategory.STRUCTURAL,
    "housing_stock": SignalCategory.STRUCTURAL,
    "operator_delta": SignalCategory.OPERATOR,
    "regulatory_risk": SignalCategory.STRUCTURAL,
    "travel_flow": SignalCategory.DEMAND,
    "event_impact": SignalCategory.DEMAND,
}


# =============================================================================
# MARKET CONTEXT
# =============================================================================

@dataclass
class MarketContext:
    """
    Market context for dynamic decay calculation.
    
    This is computed from recent signal history.
    """
    geo_id: str
    as_of: datetime
    
    # Volatility (0-1, higher = more volatile)
    price_volatility: float = 0.5
    demand_volatility: float = 0.5
    
    # Season phase
    season_phase: SeasonPhase = SeasonPhase.SHOULDER
    days_to_peak: Optional[int] = None
    
    # Market regime
    regime: MarketRegime = MarketRegime.STABLE
    
    # Signal stability (0-1, higher = more stable)
    signal_stability: float = 0.5
    
    # Sample size context
    typical_sample_size: int = 100


@dataclass
class DecayCalculation:
    """
    Result of decay calculation with full explainability.
    """
    signal_type: str
    base_half_life: int
    dynamic_half_life: float
    
    # Modifiers applied
    volatility_modifier: float
    season_modifier: float
    stability_modifier: float
    sample_modifier: float
    
    # Bounds
    min_half_life: float
    max_half_life: float
    
    # Audit
    calculation_time: datetime = field(default_factory=datetime.utcnow)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for logging/storage."""
        return {
            "signal_type": self.signal_type,
            "base_half_life": self.base_half_life,
            "dynamic_half_life": round(self.dynamic_half_life, 1),
            "modifiers": {
                "volatility": round(self.volatility_modifier, 3),
                "season": round(self.season_modifier, 3),
                "stability": round(self.stability_modifier, 3),
                "sample": round(self.sample_modifier, 3),
            },
            "bounds": {
                "min": self.min_half_life,
                "max": self.max_half_life,
            },
        }


# =============================================================================
# DYNAMIC DECAY ENGINE
# =============================================================================

class DynamicDecayEngine:
    """
    Calculates dynamic half-lives for signals.
    
    The engine applies bounded modifiers to base half-lives,
    ensuring the system remains stable while adapting to
    market conditions.
    
    Key principles:
    1. Base half-lives anchor behavior
    2. Modifiers are bounded (no chaos)
    3. No recursive learning loops
    4. Full explainability
    """
    
    # Modifier bounds
    VOLATILITY_MIN = 0.5
    VOLATILITY_MAX = 1.5
    SEASON_MIN = 0.6
    SEASON_MAX = 1.4
    STABILITY_MIN = 0.7
    STABILITY_MAX = 1.3
    SAMPLE_MIN = 0.6
    SAMPLE_MAX = 1.4
    
    # Overall bounds (% of base)
    OVERALL_MIN_FACTOR = 0.3
    OVERALL_MAX_FACTOR = 2.0
    
    def __init__(self):
        self.base_half_lives = BASE_HALF_LIVES.copy()
        self.signal_categories = SIGNAL_CATEGORIES.copy()
        
        # Season phase modifiers
        self.season_modifiers = {
            SeasonPhase.PRE_PEAK: 0.7,
            SeasonPhase.PEAK: 0.8,
            SeasonPhase.SHOULDER: 1.0,
            SeasonPhase.OFF: 1.3,
        }
        
        # Regime modifiers
        self.regime_modifiers = {
            MarketRegime.STABLE: 1.0,
            MarketRegime.RISING: 0.8,
            MarketRegime.VOLATILE: 0.6,
            MarketRegime.DECLINING: 0.85,
        }
    
    def calculate_half_life(
        self,
        signal_type: str,
        context: MarketContext,
        sample_size: Optional[int] = None,
    ) -> DecayCalculation:
        """
        Calculate dynamic half-life for a signal.
        
        Args:
            signal_type: Type of signal
            context: Market context
            sample_size: Sample size for this signal
            
        Returns:
            DecayCalculation with full breakdown
        """
        # Get base half-life
        base = self.base_half_lives.get(signal_type, 30)
        
        # Calculate modifiers
        volatility_mod = self._volatility_modifier(signal_type, context)
        season_mod = self._season_modifier(signal_type, context)
        stability_mod = self._stability_modifier(signal_type, context)
        sample_mod = self._sample_modifier(signal_type, sample_size, context)
        
        # Apply modifiers
        dynamic = base * volatility_mod * season_mod * stability_mod * sample_mod
        
        # Apply regime modifier
        regime_mod = self.regime_modifiers.get(context.regime, 1.0)
        dynamic *= regime_mod
        
        # Calculate bounds
        min_half_life = base * self.OVERALL_MIN_FACTOR
        max_half_life = base * self.OVERALL_MAX_FACTOR
        
        # Clamp to bounds
        dynamic = max(min_half_life, min(max_half_life, dynamic))
        
        return DecayCalculation(
            signal_type=signal_type,
            base_half_life=base,
            dynamic_half_life=dynamic,
            volatility_modifier=volatility_mod,
            season_modifier=season_mod,
            stability_modifier=stability_mod,
            sample_modifier=sample_mod,
            min_half_life=min_half_life,
            max_half_life=max_half_life,
        )
    
    def _volatility_modifier(
        self,
        signal_type: str,
        context: MarketContext,
    ) -> float:
        """
        Calculate volatility modifier.
        
        Higher volatility → shorter decay (things change fast).
        """
        category = self.signal_categories.get(signal_type, SignalCategory.STRUCTURAL)
        
        # Use appropriate volatility measure
        if category in [SignalCategory.DEMAND]:
            volatility = context.demand_volatility
        elif category in [SignalCategory.PRICING]:
            volatility = context.price_volatility
        else:
            volatility = (context.price_volatility + context.demand_volatility) / 2
        
        # Higher volatility → lower modifier (faster decay)
        modifier = 1.0 - (volatility * 0.5)
        
        return self._clamp(modifier, self.VOLATILITY_MIN, self.VOLATILITY_MAX)
    
    def _season_modifier(
        self,
        signal_type: str,
        context: MarketContext,
    ) -> float:
        """
        Calculate season phase modifier.
        
        Approaching peak → shorter decay (things change fast).
        Off season → longer decay (things are stable).
        """
        category = self.signal_categories.get(signal_type, SignalCategory.STRUCTURAL)
        
        # Structural signals don't change with seasons
        if category == SignalCategory.STRUCTURAL:
            return 1.0
        
        base_modifier = self.season_modifiers.get(context.season_phase, 1.0)
        
        # Adjust based on days to peak
        if context.days_to_peak is not None and context.days_to_peak < 30:
            # Within 30 days of peak - decay faster
            peak_factor = 1.0 - (context.days_to_peak / 30) * 0.2
            base_modifier *= peak_factor
        
        return self._clamp(base_modifier, self.SEASON_MIN, self.SEASON_MAX)
    
    def _stability_modifier(
        self,
        signal_type: str,
        context: MarketContext,
    ) -> float:
        """
        Calculate stability modifier.
        
        If signal direction keeps flipping → decay faster.
        Stable signals → decay slower.
        """
        # Higher stability → higher modifier (slower decay)
        modifier = 0.7 + (context.signal_stability * 0.6)
        
        return self._clamp(modifier, self.STABILITY_MIN, self.STABILITY_MAX)
    
    def _sample_modifier(
        self,
        signal_type: str,
        sample_size: Optional[int],
        context: MarketContext,
    ) -> float:
        """
        Calculate sample size modifier.
        
        More observations → slower decay (more confident).
        Fewer observations → faster decay.
        """
        if sample_size is None:
            return 1.0
        
        target = context.typical_sample_size
        if target <= 0:
            target = 100
        
        # sqrt scaling to avoid extreme values
        ratio = math.sqrt(sample_size / target)
        modifier = ratio
        
        return self._clamp(modifier, self.SAMPLE_MIN, self.SAMPLE_MAX)
    
    def _clamp(self, value: float, min_val: float, max_val: float) -> float:
        """Clamp value to range."""
        return max(min_val, min(max_val, value))
    
    def get_decay_factor(
        self,
        signal_type: str,
        days_elapsed: int,
        context: MarketContext,
        sample_size: Optional[int] = None,
    ) -> float:
        """
        Get decay factor for a signal.
        
        Returns value between 0 and 1.
        """
        if days_elapsed <= 0:
            return 1.0
        
        calc = self.calculate_half_life(signal_type, context, sample_size)
        
        # Exponential decay
        factor = math.exp(-0.693 * days_elapsed / calc.dynamic_half_life)
        
        return factor
    
    def get_decayed_confidence(
        self,
        signal_type: str,
        original_confidence: float,
        days_elapsed: int,
        context: MarketContext,
        sample_size: Optional[int] = None,
    ) -> float:
        """
        Get decayed confidence for a signal.
        """
        decay_factor = self.get_decay_factor(
            signal_type, days_elapsed, context, sample_size
        )
        
        return original_confidence * decay_factor


# =============================================================================
# MARKET CONTEXT BUILDER
# =============================================================================

class MarketContextBuilder:
    """
    Builds market context from signal history.
    
    This analyzes recent signals to determine:
    - Volatility levels
    - Season phase
    - Market regime
    - Signal stability
    """
    
    def __init__(self):
        pass
    
    def build_context(
        self,
        geo_id: str,
        signals: List[Dict],
        as_of: Optional[datetime] = None,
    ) -> MarketContext:
        """
        Build market context from signal history.
        
        Args:
            geo_id: Market identifier
            signals: List of recent signals
            as_of: Point in time for context
            
        Returns:
            MarketContext for decay calculations
        """
        as_of = as_of or datetime.utcnow()
        
        context = MarketContext(
            geo_id=geo_id,
            as_of=as_of,
        )
        
        if not signals:
            return context
        
        # Calculate volatility from price signals
        price_signals = [
            s for s in signals 
            if s.get("signal_type") in ["rate_position", "rate_by_bedroom"]
        ]
        if price_signals:
            context.price_volatility = self._calculate_volatility(price_signals)
        
        # Calculate volatility from demand signals
        demand_signals = [
            s for s in signals
            if s.get("signal_type") in ["calendar_compression", "lead_time"]
        ]
        if demand_signals:
            context.demand_volatility = self._calculate_volatility(demand_signals)
        
        # Determine season phase
        context.season_phase = self._determine_season_phase(as_of)
        context.days_to_peak = self._days_to_peak(as_of)
        
        # Determine market regime
        context.regime = self._determine_regime(signals)
        
        # Calculate signal stability
        context.signal_stability = self._calculate_stability(signals)
        
        # Calculate typical sample size
        sample_sizes = [
            s.get("metadata", {}).get("sample_size", 0)
            for s in signals
            if s.get("metadata", {}).get("sample_size")
        ]
        if sample_sizes:
            context.typical_sample_size = int(sum(sample_sizes) / len(sample_sizes))
        
        return context
    
    def _calculate_volatility(self, signals: List[Dict]) -> float:
        """Calculate volatility from signal values."""
        if len(signals) < 2:
            return 0.5
        
        # Extract numeric values
        values = []
        for s in signals:
            value = s.get("value", {})
            if isinstance(value, dict):
                # Get first numeric value
                for v in value.values():
                    if isinstance(v, (int, float)):
                        values.append(v)
                        break
            elif isinstance(value, (int, float)):
                values.append(value)
        
        if len(values) < 2:
            return 0.5
        
        # Calculate coefficient of variation
        mean = sum(values) / len(values)
        if mean == 0:
            return 0.5
        
        variance = sum((v - mean) ** 2 for v in values) / len(values)
        std = math.sqrt(variance)
        cv = std / abs(mean)
        
        # Normalize to 0-1
        return min(cv, 1.0)
    
    def _determine_season_phase(self, as_of: datetime) -> SeasonPhase:
        """Determine current season phase."""
        month = as_of.month
        
        # Gulf Coast seasonality
        if month in [5, 6]:
            return SeasonPhase.PRE_PEAK
        elif month in [7, 8]:
            return SeasonPhase.PEAK
        elif month in [3, 4, 9, 10]:
            return SeasonPhase.SHOULDER
        else:
            return SeasonPhase.OFF
    
    def _days_to_peak(self, as_of: datetime) -> int:
        """Calculate days to peak season."""
        month = as_of.month
        day = as_of.day
        
        # Peak is July 1
        if month < 7:
            target = datetime(as_of.year, 7, 1)
        else:
            target = datetime(as_of.year + 1, 7, 1)
        
        return (target - as_of).days
    
    def _determine_regime(self, signals: List[Dict]) -> MarketRegime:
        """Determine market regime from signals."""
        if not signals:
            return MarketRegime.STABLE
        
        # Look for rate acceleration signal
        accel_signals = [
            s for s in signals
            if s.get("signal_type") == "rate_acceleration"
        ]
        
        if accel_signals:
            latest = accel_signals[-1]
            value = latest.get("value", {})
            change = value.get("rate_change_pct_30d", 0)
            
            if change > 0.1:
                return MarketRegime.RISING
            elif change < -0.1:
                return MarketRegime.DECLINING
        
        # Check calendar compression volatility
        demand_vol = self._calculate_volatility([
            s for s in signals
            if s.get("signal_type") == "calendar_compression"
        ])
        
        if demand_vol > 0.7:
            return MarketRegime.VOLATILE
        
        return MarketRegime.STABLE
    
    def _calculate_stability(self, signals: List[Dict]) -> float:
        """Calculate overall signal stability."""
        if not signals:
            return 0.5
        
        # Group by type and check directional consistency
        by_type = {}
        for s in signals:
            st = s.get("signal_type")
            if st not in by_type:
                by_type[st] = []
            by_type[st].append(s)
        
        stabilities = []
        for signal_type, type_signals in by_type.items():
            if len(type_signals) < 2:
                continue
            
            vol = self._calculate_volatility(type_signals)
            stabilities.append(1.0 - vol)
        
        if not stabilities:
            return 0.5
        
        return sum(stabilities) / len(stabilities)


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

_engine = None
_context_builder = None


def get_decay_engine() -> DynamicDecayEngine:
    """Get singleton decay engine."""
    global _engine
    if _engine is None:
        _engine = DynamicDecayEngine()
    return _engine


def get_context_builder() -> MarketContextBuilder:
    """Get singleton context builder."""
    global _context_builder
    if _context_builder is None:
        _context_builder = MarketContextBuilder()
    return _context_builder


def calculate_dynamic_decay(
    signal_type: str,
    geo_id: str,
    signals: List[Dict],
    sample_size: Optional[int] = None,
) -> DecayCalculation:
    """
    Calculate dynamic decay for a signal (convenience function).
    
    Args:
        signal_type: Type of signal
        geo_id: Market identifier
        signals: Recent signal history
        sample_size: Sample size for this signal
        
    Returns:
        DecayCalculation with full breakdown
    """
    engine = get_decay_engine()
    builder = get_context_builder()
    
    context = builder.build_context(geo_id, signals)
    return engine.calculate_half_life(signal_type, context, sample_size)
