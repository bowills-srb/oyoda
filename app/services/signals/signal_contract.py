"""
Signal Contract v1.0.0 - The Canonical Interface.

Phase 0.2 of Master Refactor Plan:
- Signal model (locked)
- SignalBundle with get_weighted() (locked)
- Decay functions (centralized)

RULE: Every downstream consumer uses SignalBundle.get_weighted()
"""

from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Union
from uuid import UUID, uuid4
import math

from pydantic import BaseModel, Field, ConfigDict


# =============================================================================
# SIGNAL TYPES (Exhaustive Enum)
# =============================================================================

class SignalType(str, Enum):
    """
    All signal types in the system.
    
    Detectors produce these. Engines consume these.
    Nothing else creates market intelligence.
    """
    # Market Structure
    PLATFORM_DOMINANCE = "platform_dominance"
    SUPPLY_VELOCITY = "supply_velocity"
    DEMAND_PRESSURE = "demand_pressure"
    
    # Pricing
    SEASONALITY_CURVE = "seasonality_curve"
    AMENITY_LIFT = "amenity_lift"
    PRICE_ELASTICITY = "price_elasticity"
    RATE_POSITION = "rate_position"
    
    # Performance
    OCCUPANCY_MOMENTUM = "occupancy_momentum"
    REVENUE_TRAJECTORY = "revenue_trajectory"
    BOOKING_LEAD_TIME = "booking_lead_time"
    
    # Operator
    OPERATOR_DELTA = "operator_delta"
    PORTFOLIO_CONSISTENCY = "portfolio_consistency"
    
    # Guest Intelligence
    GUEST_INTENT_FREQUENCY = "guest_intent_frequency"
    SENTIMENT_TREND = "sentiment_trend"
    UNMET_DEMAND = "unmet_demand"
    
    # Competitive
    COMPETITOR_RATE_MOVEMENT = "competitor_rate_movement"
    INVENTORY_PRESSURE = "inventory_pressure"
    
    # Expansion
    MARKET_SIMILARITY = "market_similarity"
    EXPANSION_FIT = "expansion_fit"


class SignalScope(str, Enum):
    """Scope at which signal applies."""
    PROPERTY = "property"
    GEO = "geo"
    MARKET = "market"
    PLATFORM = "platform"
    TENANT = "tenant"


class SignalSource(str, Enum):
    """Source of signal data."""
    AIRBNB_SCRAPE = "airbnb_scrape"
    VRBO_SCRAPE = "vrbo_scrape"
    PMS_DATA = "pms_data"
    INTERNAL_ANALYTICS = "internal_analytics"
    GUEST_MESSAGES = "guest_messages"
    DERIVED = "derived"


# =============================================================================
# SIGNAL MODEL (Canonical - matches SQL exactly)
# =============================================================================

class Signal(BaseModel):
    """
    Canonical Signal model.
    
    This matches the SQL schema exactly.
    Detectors produce these. Nothing else.
    """
    id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    signal_type: SignalType
    scope: SignalScope
    
    geo_id: Optional[str] = None
    property_id: Optional[UUID] = None
    
    value: float
    confidence: float = Field(..., ge=0.0, le=1.0)
    weight_hint: Optional[float] = None
    
    source: SignalSource
    detected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    time_window: str
    
    metadata: Optional[Dict[str, Any]] = None
    version: str = "1.0.0"
    
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = ConfigDict(use_enum_values=True)


# =============================================================================
# DECAY FUNCTIONS (Phase 5 - Centralized)
# =============================================================================

def slow_decay(signal: Signal, as_of: Optional[datetime] = None) -> float:
    """
    Slow decay for stable signals (seasonality, platform dominance).
    Half-life: ~6 months
    """
    as_of = as_of or datetime.now(timezone.utc)
    days_old = (as_of - signal.detected_at).total_seconds() / 86400
    return math.exp(-days_old / 180)  # 180 day half-life


def very_slow_decay(signal: Signal, as_of: Optional[datetime] = None) -> float:
    """
    Very slow decay for structural signals (platform dominance).
    Half-life: ~12 months
    """
    as_of = as_of or datetime.now(timezone.utc)
    days_old = (as_of - signal.detected_at).total_seconds() / 86400
    return math.exp(-days_old / 365)  # 365 day half-life


def medium_decay(signal: Signal, as_of: Optional[datetime] = None) -> float:
    """
    Medium decay for moderately volatile signals (amenity lift, operator delta).
    Half-life: ~3 months
    """
    as_of = as_of or datetime.now(timezone.utc)
    days_old = (as_of - signal.detected_at).total_seconds() / 86400
    return math.exp(-days_old / 90)  # 90 day half-life


def fast_decay(signal: Signal, as_of: Optional[datetime] = None) -> float:
    """
    Fast decay for volatile signals (momentum, elasticity).
    Half-life: ~30 days
    """
    as_of = as_of or datetime.now(timezone.utc)
    days_old = (as_of - signal.detected_at).total_seconds() / 86400
    return math.exp(-days_old / 30)  # 30 day half-life


def very_fast_decay(signal: Signal, as_of: Optional[datetime] = None) -> float:
    """
    Very fast decay for real-time signals (competitor rate movement).
    Half-life: ~7 days
    """
    as_of = as_of or datetime.now(timezone.utc)
    days_old = (as_of - signal.detected_at).total_seconds() / 86400
    return math.exp(-days_old / 7)  # 7 day half-life


# Decay registry (Phase 5)
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
# SIGNAL BUNDLE (The Interface for All Consumers)
# =============================================================================

class SignalBundle(BaseModel):
    """
    Collection of signals for analytics engine consumption.
    
    This is the ONLY interface downstream consumers should use.
    
    Usage:
        bundle = SignalBundle(geo_id="30a-beaches", signals={...})
        seasonality = bundle.get_weighted(SignalType.SEASONALITY_CURVE)
        platform_bias = bundle.get_weighted(SignalType.PLATFORM_DOMINANCE)
    """
    geo_id: str
    property_id: Optional[UUID] = None
    tenant_id: Optional[UUID] = None
    
    # Signals grouped by type for efficient access
    signals: Dict[SignalType, List[Signal]] = Field(default_factory=dict)
    
    # When this bundle was assembled
    assembled_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = ConfigDict(use_enum_values=True)
    
    def get_weighted(
        self,
        signal_type: SignalType,
        decay_fn: Optional[Callable[[Signal, Optional[datetime]], float]] = None,
        as_of: Optional[datetime] = None,
    ) -> Optional[float]:
        """
        Get weighted average value for a signal type.
        
        This is THE method for consuming signals.
        
        Args:
            signal_type: Type of signal to retrieve
            decay_fn: Custom decay function (defaults to type-specific)
            as_of: Point in time for decay calculation
        
        Returns:
            Weighted average value, or None if no signals
        """
        signals = self.signals.get(signal_type, [])
        if not signals:
            return None
        
        # Use type-specific decay if not provided
        if decay_fn is None:
            decay_fn = get_decay_fn(signal_type)
        
        as_of = as_of or datetime.now(timezone.utc)
        
        # Calculate weighted average
        # weight = confidence * decay
        total_weight = 0.0
        weighted_sum = 0.0
        
        for s in signals:
            decay = decay_fn(s, as_of)
            weight = s.confidence * decay
            weighted_sum += s.value * weight
            total_weight += weight
        
        if total_weight == 0:
            return None
        
        return weighted_sum / total_weight
    
    def get_weighted_with_confidence(
        self,
        signal_type: SignalType,
        decay_fn: Optional[Callable[[Signal, Optional[datetime]], float]] = None,
        as_of: Optional[datetime] = None,
    ) -> tuple[Optional[float], float]:
        """
        Get weighted value AND effective confidence.
        
        Returns:
            (weighted_value, effective_confidence)
        """
        signals = self.signals.get(signal_type, [])
        if not signals:
            return None, 0.0
        
        if decay_fn is None:
            decay_fn = get_decay_fn(signal_type)
        
        as_of = as_of or datetime.now(timezone.utc)
        
        total_weight = 0.0
        weighted_sum = 0.0
        confidence_sum = 0.0
        
        for s in signals:
            decay = decay_fn(s, as_of)
            weight = s.confidence * decay
            weighted_sum += s.value * weight
            total_weight += weight
            confidence_sum += s.confidence * decay
        
        if total_weight == 0:
            return None, 0.0
        
        value = weighted_sum / total_weight
        effective_confidence = confidence_sum / len(signals)
        
        return value, effective_confidence
    
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
        signal_type = SignalType(signal.signal_type) if isinstance(signal.signal_type, str) else signal.signal_type
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
            signal_type = SignalType(signal.signal_type) if isinstance(signal.signal_type, str) else signal.signal_type
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
# CONFIDENCE THRESHOLDS (For Gating)
# =============================================================================

class ConfidenceThresholds:
    """
    Confidence thresholds that gate outputs.
    
    Phase 7.2: If confidence < threshold, output is restricted.
    """
    # Voice outputs require high confidence
    VOICE_PRICING_CLAIM = 0.75
    VOICE_DISCOUNT_DENIAL = 0.70
    VOICE_MARKET_ASSERTION = 0.65
    
    # BD outputs require medium-high confidence  
    BD_PROJECTION = 0.60
    BD_RECOMMENDATION = 0.65
    BD_EXPANSION_SCORE = 0.55
    
    # Internal analytics can be lower
    INTERNAL_ANALYSIS = 0.50
    
    # Minimum to process at all
    MINIMUM_VIABLE = 0.40


def is_confidence_sufficient(
    confidence: float,
    output_type: str,
) -> bool:
    """Check if confidence meets threshold for output type."""
    thresholds = {
        "voice_pricing": ConfidenceThresholds.VOICE_PRICING_CLAIM,
        "voice_discount": ConfidenceThresholds.VOICE_DISCOUNT_DENIAL,
        "voice_market": ConfidenceThresholds.VOICE_MARKET_ASSERTION,
        "bd_projection": ConfidenceThresholds.BD_PROJECTION,
        "bd_recommendation": ConfidenceThresholds.BD_RECOMMENDATION,
        "bd_expansion": ConfidenceThresholds.BD_EXPANSION_SCORE,
        "internal": ConfidenceThresholds.INTERNAL_ANALYSIS,
    }
    
    threshold = thresholds.get(output_type, ConfidenceThresholds.MINIMUM_VIABLE)
    return confidence >= threshold


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Types
    "SignalType",
    "SignalScope", 
    "SignalSource",
    
    # Models
    "Signal",
    "SignalBundle",
    
    # Decay
    "slow_decay",
    "very_slow_decay",
    "medium_decay",
    "fast_decay",
    "very_fast_decay",
    "DECAY_PROFILES",
    "get_decay_fn",
    
    # Confidence
    "ConfidenceThresholds",
    "is_confidence_sufficient",
]
