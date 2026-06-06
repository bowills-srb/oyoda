"""
Domain: Signals - Pure Computations.

No FastAPI. No DB sessions. No external API calls.
Pure inputs → outputs.

All signal math lives here.
"""

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Tuple
from uuid import UUID

from .models import Signal, SignalType


# =============================================================================
# DECAY FUNCTIONS
# =============================================================================

def slow_decay(signal: Signal, as_of: Optional[datetime] = None) -> float:
    """
    Slow decay for stable signals (seasonality, platform dominance).
    Half-life: ~6 months
    """
    as_of = as_of or datetime.now(timezone.utc)
    days_old = (as_of - signal.detected_at).total_seconds() / 86400
    return math.exp(-days_old / 180)


def very_slow_decay(signal: Signal, as_of: Optional[datetime] = None) -> float:
    """
    Very slow decay for structural signals (platform dominance).
    Half-life: ~12 months
    """
    as_of = as_of or datetime.now(timezone.utc)
    days_old = (as_of - signal.detected_at).total_seconds() / 86400
    return math.exp(-days_old / 365)


def medium_decay(signal: Signal, as_of: Optional[datetime] = None) -> float:
    """
    Medium decay for moderately volatile signals (amenity lift, operator delta).
    Half-life: ~3 months
    """
    as_of = as_of or datetime.now(timezone.utc)
    days_old = (as_of - signal.detected_at).total_seconds() / 86400
    return math.exp(-days_old / 90)


def fast_decay(signal: Signal, as_of: Optional[datetime] = None) -> float:
    """
    Fast decay for volatile signals (momentum, elasticity).
    Half-life: ~30 days
    """
    as_of = as_of or datetime.now(timezone.utc)
    days_old = (as_of - signal.detected_at).total_seconds() / 86400
    return math.exp(-days_old / 30)


def very_fast_decay(signal: Signal, as_of: Optional[datetime] = None) -> float:
    """
    Very fast decay for real-time signals (competitor rate movement).
    Half-life: ~7 days
    """
    as_of = as_of or datetime.now(timezone.utc)
    days_old = (as_of - signal.detected_at).total_seconds() / 86400
    return math.exp(-days_old / 7)


# Decay registry
DECAY_PROFILES: Dict[SignalType, Callable[[Signal, Optional[datetime]], float]] = {
    SignalType.SEASONALITY_CURVE: slow_decay,
    SignalType.PLATFORM_DOMINANCE: very_slow_decay,
    SignalType.AMENITY_LIFT: medium_decay,
    SignalType.PRICE_ELASTICITY: fast_decay,
    SignalType.OCCUPANCY_MOMENTUM: fast_decay,
    SignalType.OPERATOR_DELTA: medium_decay,
    SignalType.GUEST_INTENT_FREQUENCY: medium_decay,
    SignalType.COMPETITOR_RATE_MOVEMENT: very_fast_decay,
    SignalType.INVENTORY_PRESSURE: fast_decay,
    SignalType.DEMAND_PRESSURE: fast_decay,
    SignalType.SUPPLY_VELOCITY: medium_decay,
    SignalType.BOOKING_LEAD_TIME: medium_decay,
    SignalType.REVENUE_TRAJECTORY: medium_decay,
    SignalType.SENTIMENT_TREND: medium_decay,
    SignalType.UNMET_DEMAND: medium_decay,
    SignalType.MARKET_SIMILARITY: slow_decay,
    SignalType.EXPANSION_FIT: slow_decay,
    SignalType.RATE_POSITION: fast_decay,
    SignalType.PORTFOLIO_CONSISTENCY: slow_decay,
}


def get_decay_fn(signal_type: SignalType) -> Callable[[Signal, Optional[datetime]], float]:
    """Get the appropriate decay function for a signal type."""
    return DECAY_PROFILES.get(signal_type, medium_decay)


# =============================================================================
# SIGNAL WEIGHTING
# =============================================================================

@dataclass
class WeightedSignalResult:
    """Result of weighting a signal."""
    original_value: float
    weighted_value: float
    decay_factor: float
    confidence_factor: float
    effective_weight: float


def compute_weighted_value(
    signal: Signal,
    as_of: Optional[datetime] = None,
    decay_fn: Optional[Callable[[Signal, Optional[datetime]], float]] = None,
) -> WeightedSignalResult:
    """
    Compute weighted value for a single signal.
    
    Weight = confidence * decay
    """
    if decay_fn is None:
        decay_fn = get_decay_fn(signal.signal_type)
    
    decay = decay_fn(signal, as_of)
    weight = signal.confidence * decay
    
    return WeightedSignalResult(
        original_value=signal.value,
        weighted_value=signal.value * weight,
        decay_factor=decay,
        confidence_factor=signal.confidence,
        effective_weight=weight,
    )


def compute_weighted_average(
    signals: List[Signal],
    as_of: Optional[datetime] = None,
    decay_fn: Optional[Callable[[Signal, Optional[datetime]], float]] = None,
) -> Optional[float]:
    """
    Compute weighted average across multiple signals.
    
    Returns None if no signals or total weight is zero.
    """
    if not signals:
        return None
    
    total_weight = 0.0
    weighted_sum = 0.0
    
    for s in signals:
        result = compute_weighted_value(s, as_of, decay_fn)
        weighted_sum += s.value * result.effective_weight
        total_weight += result.effective_weight
    
    if total_weight == 0:
        return None
    
    return weighted_sum / total_weight


def compute_weighted_average_with_confidence(
    signals: List[Signal],
    as_of: Optional[datetime] = None,
    decay_fn: Optional[Callable[[Signal, Optional[datetime]], float]] = None,
) -> Tuple[Optional[float], float]:
    """
    Compute weighted average AND effective confidence.
    
    Returns (weighted_value, effective_confidence).
    """
    if not signals:
        return None, 0.0
    
    total_weight = 0.0
    weighted_sum = 0.0
    confidence_sum = 0.0
    
    for s in signals:
        result = compute_weighted_value(s, as_of, decay_fn)
        weighted_sum += s.value * result.effective_weight
        total_weight += result.effective_weight
        confidence_sum += result.effective_weight
    
    if total_weight == 0:
        return None, 0.0
    
    value = weighted_sum / total_weight
    effective_confidence = confidence_sum / len(signals)
    
    return value, effective_confidence


# =============================================================================
# SIGNAL BUNDLE (Collection Interface)
# =============================================================================

@dataclass
class SignalBundle:
    """
    Collection of signals for analytics engine consumption.
    
    This is the ONLY interface downstream consumers should use.
    Pure domain object - no IO.
    """
    geo_id: str
    property_id: Optional[UUID] = None
    tenant_id: Optional[UUID] = None
    signals: Dict[SignalType, List[Signal]] = field(default_factory=dict)
    assembled_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    def get_weighted(
        self,
        signal_type: SignalType,
        decay_fn: Optional[Callable[[Signal, Optional[datetime]], float]] = None,
        as_of: Optional[datetime] = None,
    ) -> Optional[float]:
        """
        Get weighted average value for a signal type.
        
        This is THE method for consuming signals.
        """
        signals = self.signals.get(signal_type, [])
        if not signals:
            return None
        
        if decay_fn is None:
            decay_fn = get_decay_fn(signal_type)
        
        return compute_weighted_average(signals, as_of, decay_fn)
    
    def get_weighted_with_confidence(
        self,
        signal_type: SignalType,
        decay_fn: Optional[Callable[[Signal, Optional[datetime]], float]] = None,
        as_of: Optional[datetime] = None,
    ) -> Tuple[Optional[float], float]:
        """Get weighted value AND effective confidence."""
        signals = self.signals.get(signal_type, [])
        if not signals:
            return None, 0.0
        
        if decay_fn is None:
            decay_fn = get_decay_fn(signal_type)
        
        return compute_weighted_average_with_confidence(signals, as_of, decay_fn)
    
    def get_all(self, signal_type: SignalType) -> List[Signal]:
        """Get all signals of a type (unweighted)."""
        return self.signals.get(signal_type, [])
    
    def get_latest(self, signal_type: SignalType) -> Optional[Signal]:
        """Get most recent signal of a type."""
        signals = self.signals.get(signal_type, [])
        if not signals:
            return None
        return max(signals, key=lambda s: s.detected_at)
    
    def has_signal(self, signal_type: SignalType) -> bool:
        """Check if bundle has any signals of a type."""
        return bool(self.signals.get(signal_type))
    
    def get_confidence(self, signal_type: SignalType) -> float:
        """Get average confidence for a signal type."""
        signals = self.signals.get(signal_type, [])
        if not signals:
            return 0.0
        return sum(s.confidence for s in signals) / len(signals)
    
    @property
    def overall_confidence(self) -> float:
        """Average confidence across all signals."""
        all_signals = [s for signals in self.signals.values() for s in signals]
        if not all_signals:
            return 0.0
        return sum(s.confidence for s in all_signals) / len(all_signals)
    
    @property
    def signal_count(self) -> int:
        """Total number of signals in bundle."""
        return sum(len(signals) for signals in self.signals.values())
    
    @property
    def signal_types_present(self) -> List[SignalType]:
        """List of signal types present in bundle."""
        return [st for st, signals in self.signals.items() if signals]
    
    def add_signal(self, signal: Signal) -> None:
        """Add a signal to the bundle."""
        signal_type = signal.signal_type
        if signal_type not in self.signals:
            self.signals[signal_type] = []
        self.signals[signal_type].append(signal)
    
    @classmethod
    def from_signal_list(
        cls,
        signals: List[Signal],
        geo_id: str,
        property_id: Optional[UUID] = None,
        tenant_id: Optional[UUID] = None,
    ) -> "SignalBundle":
        """Create bundle from flat list of signals."""
        grouped: Dict[SignalType, List[Signal]] = {}
        
        for signal in signals:
            signal_type = signal.signal_type
            if signal_type not in grouped:
                grouped[signal_type] = []
            grouped[signal_type].append(signal)
        
        return cls(
            geo_id=geo_id,
            property_id=property_id,
            tenant_id=tenant_id,
            signals=grouped,
        )


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Decay functions
    "slow_decay",
    "very_slow_decay",
    "medium_decay",
    "fast_decay",
    "very_fast_decay",
    "DECAY_PROFILES",
    "get_decay_fn",
    
    # Weighting
    "WeightedSignalResult",
    "compute_weighted_value",
    "compute_weighted_average",
    "compute_weighted_average_with_confidence",
    
    # Bundle
    "SignalBundle",
]
