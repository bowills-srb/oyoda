"""
Cross-Signal Regime Detection & Consistency Engine

This is advanced — and powerful.

Instead of treating signals independently, this module:
1. Detects market regimes from signal patterns
2. Checks cross-signal consistency
3. Adjusts confidence bands based on agreement
4. Feeds into discount posture and pricing confidence

Example:
    Price up + Demand up + Calendar filling → HIGH confidence
    Price down + Demand flat + Calendar empty → LOW confidence, widen bands

You already have the signals — this is logic, not data.

Usage:
    from app.services.signals.regime_detection import (
        RegimeDetectionEngine,
        CrossSignalConsistencyEngine,
    )
    
    regime = regime_engine.detect_regime(signals)
    consistency = consistency_engine.check_consistency(signals)
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
import math


# =============================================================================
# ENUMS
# =============================================================================

class MarketRegime(str, Enum):
    """Market regime classifications."""
    BULL = "bull"               # Strong demand, rising prices
    BEAR = "bear"               # Weak demand, falling prices
    STABLE = "stable"           # Balanced market
    VOLATILE = "volatile"       # Unpredictable swings
    TRANSITIONING = "transitioning"  # Changing regime


class SignalAgreement(str, Enum):
    """Level of agreement between signals."""
    STRONG = "strong"           # All signals agree
    MODERATE = "moderate"       # Most signals agree
    WEAK = "weak"               # Mixed signals
    CONFLICTING = "conflicting" # Signals contradict


class ConfidenceAdjustment(str, Enum):
    """How to adjust confidence based on consistency."""
    BOOST = "boost"             # Increase confidence
    MAINTAIN = "maintain"       # Keep as-is
    WIDEN = "widen"             # Widen confidence bands
    DISCOUNT = "discount"       # Reduce confidence significantly


# =============================================================================
# DATA MODELS
# =============================================================================

@dataclass
class SignalSnapshot:
    """Normalized snapshot of a signal for analysis."""
    signal_type: str
    direction: int  # -1, 0, +1
    magnitude: float  # 0-1
    confidence: float  # Original confidence
    observed_at: datetime


@dataclass
class RegimeResult:
    """Result of regime detection."""
    regime: MarketRegime
    regime_confidence: float
    
    # Supporting evidence
    demand_direction: int  # -1, 0, +1
    price_direction: int
    supply_direction: int
    
    # Trend strength
    trend_strength: float  # 0-1
    
    # Volatility
    volatility_score: float  # 0-1
    
    # Time in regime
    estimated_days_in_regime: Optional[int] = None
    
    # Regime transition probability
    transition_probability: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "regime": self.regime.value,
            "confidence": round(self.regime_confidence, 3),
            "demand_direction": self.demand_direction,
            "price_direction": self.price_direction,
            "supply_direction": self.supply_direction,
            "trend_strength": round(self.trend_strength, 3),
            "volatility_score": round(self.volatility_score, 3),
            "transition_probability": round(self.transition_probability, 3),
        }


@dataclass
class ConsistencyResult:
    """Result of cross-signal consistency check."""
    agreement: SignalAgreement
    agreement_score: float  # 0-1
    
    # Confidence adjustment
    adjustment: ConfidenceAdjustment
    adjustment_factor: float  # Multiply confidence by this
    
    # Band adjustment
    band_multiplier: float  # Multiply band width by this
    
    # Conflicts detected
    conflicts: List[Tuple[str, str, str]] = field(default_factory=list)
    
    # Aligned signals
    aligned_signals: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "agreement": self.agreement.value,
            "agreement_score": round(self.agreement_score, 3),
            "adjustment": self.adjustment.value,
            "adjustment_factor": round(self.adjustment_factor, 3),
            "band_multiplier": round(self.band_multiplier, 3),
            "conflicts": self.conflicts,
            "aligned_signals": self.aligned_signals,
        }


# =============================================================================
# SIGNAL CATEGORIZATION
# =============================================================================

# Demand indicators
DEMAND_SIGNALS = [
    "calendar_compression",
    "lead_time",
    "rate_acceleration",
    "travel_flow",
]

# Price indicators
PRICE_SIGNALS = [
    "rate_position",
    "rate_by_bedroom",
]

# Supply indicators
SUPPLY_SIGNALS = [
    "supply_density",
    "bedroom_distribution",
]

# What each signal direction means for market health
# Positive direction = bullish signal
SIGNAL_POLARITY = {
    "calendar_compression": +1,  # High compression = bullish
    "lead_time": -1,  # Shorter lead time = bullish (inverted)
    "rate_acceleration": +1,  # Rising rates = bullish
    "rate_position": +1,  # Higher rates = bullish
    "supply_density": -1,  # More supply = bearish
    "travel_flow": +1,  # More travel = bullish
}


# =============================================================================
# REGIME DETECTION ENGINE
# =============================================================================

class RegimeDetectionEngine:
    """
    Detects market regime from signal patterns.
    
    Classifies markets as:
    - BULL: Strong demand, rising prices
    - BEAR: Weak demand, falling prices
    - STABLE: Balanced
    - VOLATILE: Unpredictable
    - TRANSITIONING: Changing regime
    """
    
    # Thresholds
    BULL_THRESHOLD = 0.3
    BEAR_THRESHOLD = -0.3
    VOLATILITY_THRESHOLD = 0.6
    
    def __init__(self):
        pass
    
    def detect_regime(
        self,
        signals: List[Dict],
        historical_signals: Optional[List[Dict]] = None,
    ) -> RegimeResult:
        """
        Detect current market regime.
        
        Args:
            signals: Current signals
            historical_signals: Previous signals for trend analysis
            
        Returns:
            RegimeResult with regime classification
        """
        # Extract directions
        demand_dir = self._calculate_direction(signals, DEMAND_SIGNALS)
        price_dir = self._calculate_direction(signals, PRICE_SIGNALS)
        supply_dir = self._calculate_direction(signals, SUPPLY_SIGNALS)
        
        # Calculate overall trend
        trend_score = (demand_dir + price_dir - supply_dir) / 3
        
        # Calculate volatility
        volatility = self._calculate_volatility(signals)
        
        # Determine regime
        regime = self._classify_regime(trend_score, volatility)
        
        # Calculate confidence
        confidence = self._calculate_regime_confidence(signals, regime)
        
        # Calculate trend strength
        trend_strength = abs(trend_score)
        
        # Transition probability (if historical data available)
        transition_prob = 0.0
        if historical_signals:
            transition_prob = self._calculate_transition_probability(
                signals, historical_signals
            )
        
        return RegimeResult(
            regime=regime,
            regime_confidence=confidence,
            demand_direction=int(round(demand_dir)),
            price_direction=int(round(price_dir)),
            supply_direction=int(round(supply_dir)),
            trend_strength=trend_strength,
            volatility_score=volatility,
            transition_probability=transition_prob,
        )
    
    def _calculate_direction(
        self,
        signals: List[Dict],
        signal_types: List[str],
    ) -> float:
        """Calculate aggregate direction for signal types."""
        directions = []
        
        for signal in signals:
            st = signal.get("signal_type")
            if st not in signal_types:
                continue
            
            # Get signal value
            value = signal.get("value", {})
            direction = self._extract_direction(st, value)
            
            # Apply polarity
            polarity = SIGNAL_POLARITY.get(st, 1)
            direction *= polarity
            
            # Weight by confidence
            conf = signal.get("confidence", 0.5)
            directions.append(direction * conf)
        
        if not directions:
            return 0.0
        
        return sum(directions) / len(directions)
    
    def _extract_direction(self, signal_type: str, value: Dict) -> float:
        """Extract direction from signal value."""
        if signal_type == "calendar_compression":
            # High blocked % = positive direction
            blocked = value.get("blocked_pct_30d", 0.5)
            return (blocked - 0.5) * 2  # Normalize to -1 to +1
        
        elif signal_type == "rate_acceleration":
            change = value.get("rate_change_pct_30d", 0)
            return max(-1, min(1, change * 5))  # Scale and clamp
        
        elif signal_type == "supply_density":
            # Compare to expected (would need baseline)
            return 0.0  # Neutral without baseline
        
        elif signal_type == "rate_position":
            # Would need baseline comparison
            return 0.0
        
        elif signal_type == "lead_time":
            # Shorter lead time = bullish
            days = value.get("median_days_to_booking", 30)
            return (30 - days) / 30  # Normalize
        
        return 0.0
    
    def _calculate_volatility(self, signals: List[Dict]) -> float:
        """Calculate market volatility from signals."""
        # Look for conflicting signals
        directions = []
        
        for signal in signals:
            st = signal.get("signal_type")
            value = signal.get("value", {})
            
            direction = self._extract_direction(st, value)
            polarity = SIGNAL_POLARITY.get(st, 1)
            
            directions.append(direction * polarity)
        
        if len(directions) < 2:
            return 0.0
        
        # Volatility = variance in directions
        mean = sum(directions) / len(directions)
        variance = sum((d - mean) ** 2 for d in directions) / len(directions)
        
        return min(math.sqrt(variance), 1.0)
    
    def _classify_regime(
        self,
        trend_score: float,
        volatility: float,
    ) -> MarketRegime:
        """Classify regime from trend and volatility."""
        if volatility > self.VOLATILITY_THRESHOLD:
            return MarketRegime.VOLATILE
        
        if trend_score > self.BULL_THRESHOLD:
            return MarketRegime.BULL
        elif trend_score < self.BEAR_THRESHOLD:
            return MarketRegime.BEAR
        else:
            return MarketRegime.STABLE
    
    def _calculate_regime_confidence(
        self,
        signals: List[Dict],
        regime: MarketRegime,
    ) -> float:
        """Calculate confidence in regime classification."""
        # Base on signal coverage and agreement
        if not signals:
            return 0.0
        
        avg_conf = sum(s.get("confidence", 0.5) for s in signals) / len(signals)
        
        # Reduce confidence for volatile/transitioning regimes
        if regime in [MarketRegime.VOLATILE, MarketRegime.TRANSITIONING]:
            avg_conf *= 0.7
        
        return avg_conf
    
    def _calculate_transition_probability(
        self,
        current: List[Dict],
        historical: List[Dict],
    ) -> float:
        """Calculate probability of regime transition."""
        # Compare current direction to historical
        current_trend = self._calculate_direction(current, DEMAND_SIGNALS + PRICE_SIGNALS)
        historical_trend = self._calculate_direction(historical, DEMAND_SIGNALS + PRICE_SIGNALS)
        
        # Large direction change = higher transition probability
        change = abs(current_trend - historical_trend)
        
        return min(change, 1.0)


# =============================================================================
# CROSS-SIGNAL CONSISTENCY ENGINE
# =============================================================================

class CrossSignalConsistencyEngine:
    """
    Checks consistency between signals.
    
    Key insight: If signals agree, confidence is higher.
    If they conflict, widen bands and reduce confidence.
    """
    
    # Consistency rules (signal pairs and expected relationship)
    CONSISTENCY_RULES = [
        # (signal_a, signal_b, expected_relationship)
        # relationship: "same" = same direction, "opposite" = opposite
        ("calendar_compression", "rate_acceleration", "same"),
        ("calendar_compression", "lead_time", "opposite"),  # High demand = short lead time
        ("rate_acceleration", "supply_density", "opposite"),  # Rising prices = tight supply
        ("platform_dominance", "rate_position", "neutral"),
    ]
    
    def __init__(self):
        pass
    
    def check_consistency(
        self,
        signals: List[Dict],
    ) -> ConsistencyResult:
        """
        Check cross-signal consistency.
        
        Args:
            signals: List of signals
            
        Returns:
            ConsistencyResult with agreement level and adjustments
        """
        if len(signals) < 2:
            return ConsistencyResult(
                agreement=SignalAgreement.WEAK,
                agreement_score=0.5,
                adjustment=ConfidenceAdjustment.MAINTAIN,
                adjustment_factor=1.0,
                band_multiplier=1.0,
            )
        
        # Build signal lookup
        signal_map = {s.get("signal_type"): s for s in signals}
        
        # Check consistency rules
        consistent = 0
        conflicting = 0
        conflicts = []
        
        for signal_a, signal_b, expected in self.CONSISTENCY_RULES:
            if signal_a not in signal_map or signal_b not in signal_map:
                continue
            
            is_consistent = self._check_pair_consistency(
                signal_map[signal_a],
                signal_map[signal_b],
                expected,
            )
            
            if is_consistent:
                consistent += 1
            else:
                conflicting += 1
                conflicts.append((signal_a, signal_b, expected))
        
        # Calculate agreement score
        total_checks = consistent + conflicting
        if total_checks == 0:
            agreement_score = 0.5
        else:
            agreement_score = consistent / total_checks
        
        # Classify agreement
        agreement = self._classify_agreement(agreement_score)
        
        # Determine adjustment
        adjustment, factor, band_mult = self._determine_adjustment(agreement_score)
        
        # Find aligned signals
        aligned = self._find_aligned_signals(signals)
        
        return ConsistencyResult(
            agreement=agreement,
            agreement_score=agreement_score,
            adjustment=adjustment,
            adjustment_factor=factor,
            band_multiplier=band_mult,
            conflicts=conflicts,
            aligned_signals=aligned,
        )
    
    def _check_pair_consistency(
        self,
        signal_a: Dict,
        signal_b: Dict,
        expected: str,
    ) -> bool:
        """Check if two signals are consistent."""
        if expected == "neutral":
            return True
        
        dir_a = self._get_signal_direction(signal_a)
        dir_b = self._get_signal_direction(signal_b)
        
        if expected == "same":
            return (dir_a * dir_b) >= 0  # Same sign or one is zero
        elif expected == "opposite":
            return (dir_a * dir_b) <= 0  # Opposite sign or one is zero
        
        return True
    
    def _get_signal_direction(self, signal: Dict) -> int:
        """Get direction of a signal (-1, 0, +1)."""
        st = signal.get("signal_type")
        value = signal.get("value", {})
        
        if st == "calendar_compression":
            blocked = value.get("blocked_pct_30d", 0.5)
            if blocked > 0.6:
                return 1
            elif blocked < 0.4:
                return -1
            return 0
        
        elif st == "rate_acceleration":
            change = value.get("rate_change_pct_30d", 0)
            if change > 0.02:
                return 1
            elif change < -0.02:
                return -1
            return 0
        
        elif st == "lead_time":
            trend = value.get("trend_delta_pct", 0)
            if trend > 0.05:
                return 1  # Lengthening
            elif trend < -0.05:
                return -1  # Shortening
            return 0
        
        elif st == "supply_density":
            # Would need historical comparison
            return 0
        
        return 0
    
    def _classify_agreement(self, score: float) -> SignalAgreement:
        """Classify agreement level."""
        if score >= 0.8:
            return SignalAgreement.STRONG
        elif score >= 0.6:
            return SignalAgreement.MODERATE
        elif score >= 0.4:
            return SignalAgreement.WEAK
        else:
            return SignalAgreement.CONFLICTING
    
    def _determine_adjustment(
        self,
        score: float,
    ) -> Tuple[ConfidenceAdjustment, float, float]:
        """Determine confidence adjustment."""
        if score >= 0.8:
            return ConfidenceAdjustment.BOOST, 1.1, 0.9
        elif score >= 0.6:
            return ConfidenceAdjustment.MAINTAIN, 1.0, 1.0
        elif score >= 0.4:
            return ConfidenceAdjustment.WIDEN, 0.9, 1.2
        else:
            return ConfidenceAdjustment.DISCOUNT, 0.7, 1.5
    
    def _find_aligned_signals(self, signals: List[Dict]) -> List[str]:
        """Find signals that align directionally."""
        aligned = []
        
        directions = {}
        for signal in signals:
            st = signal.get("signal_type")
            direction = self._get_signal_direction(signal)
            
            # Apply polarity
            polarity = SIGNAL_POLARITY.get(st, 1)
            normalized = direction * polarity
            
            directions[st] = normalized
        
        # Find majority direction
        if not directions:
            return []
        
        positive = sum(1 for d in directions.values() if d > 0)
        negative = sum(1 for d in directions.values() if d < 0)
        
        majority = 1 if positive >= negative else -1
        
        for st, direction in directions.items():
            if direction * majority > 0:
                aligned.append(st)
        
        return aligned


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def detect_market_regime(signals: List[Dict]) -> RegimeResult:
    """Detect market regime (convenience function)."""
    engine = RegimeDetectionEngine()
    return engine.detect_regime(signals)


def check_signal_consistency(signals: List[Dict]) -> ConsistencyResult:
    """Check signal consistency (convenience function)."""
    engine = CrossSignalConsistencyEngine()
    return engine.check_consistency(signals)


def get_adjusted_confidence(
    base_confidence: float,
    signals: List[Dict],
) -> Tuple[float, float]:
    """
    Get adjusted confidence and band multiplier.
    
    Returns:
        Tuple of (adjusted_confidence, band_multiplier)
    """
    consistency = check_signal_consistency(signals)
    
    adjusted = base_confidence * consistency.adjustment_factor
    adjusted = max(0.1, min(1.0, adjusted))
    
    return adjusted, consistency.band_multiplier
