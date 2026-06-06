"""
Canonical Signal Schema v1.0.0

This is the MOST IMPORTANT artifact in the system.
If this is right, everything scales.

A Signal is NOT raw data. It is INTERPRETED EVIDENCE.

Key Properties:
1. Detectors never talk to each other
2. Analytics engine never touches raw data
3. Everything is auditable
4. Time decay & geo logic become trivial

This is already beyond AirDNA's internal architecture.
"""

from datetime import datetime, date, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, ConfigDict, field_validator


# =============================================================================
# SCHEMA VERSION
# =============================================================================

SIGNAL_SCHEMA_VERSION = "1.0.0"


# =============================================================================
# ENUMS
# =============================================================================

class SignalType(str, Enum):
    """
    Types of signals that detectors can emit.
    
    Each signal type has specific semantics for its value field.
    """
    # Market Structure Signals
    PLATFORM_DOMINANCE = "platform_dominance"       # Airbnb vs VRBO share
    SUPPLY_VELOCITY = "supply_velocity"             # New listings rate
    DEMAND_PRESSURE = "demand_pressure"             # Booking velocity
    
    # Pricing Signals
    AMENITY_LIFT = "amenity_lift"                   # ADR uplift per amenity
    SEASONALITY_CURVE = "seasonality_curve"         # Monthly demand shape
    PRICE_ELASTICITY = "price_elasticity"           # Discount sensitivity
    RATE_POSITION = "rate_position"                 # Where property sits in market
    
    # Performance Signals
    OCCUPANCY_MOMENTUM = "occupancy_momentum"       # Forward vs trailing pace
    REVENUE_TRAJECTORY = "revenue_trajectory"       # YoY revenue trend
    BOOKING_LEAD_TIME = "booking_lead_time"         # How far out bookings come
    
    # Operator Signals
    OPERATOR_DELTA = "operator_delta"               # Internal vs market baseline
    PORTFOLIO_CONSISTENCY = "portfolio_consistency" # How stable is their performance
    
    # Guest Intelligence Signals
    GUEST_INTENT_FREQUENCY = "guest_intent_frequency"   # What guests ask most
    SENTIMENT_TREND = "sentiment_trend"                 # Message sentiment over time
    UNMET_DEMAND = "unmet_demand"                       # What guests want but can't get
    
    # Competitive Signals
    COMPETITOR_RATE_MOVEMENT = "competitor_rate_movement"  # Market price changes
    INVENTORY_PRESSURE = "inventory_pressure"              # Available nights in market
    
    # Expansion Signals
    MARKET_SIMILARITY = "market_similarity"         # How similar is target market
    EXPANSION_FIT = "expansion_fit"                 # Operator fit for new market


class SignalScope(str, Enum):
    """
    Scope at which a signal applies.
    
    Determines how the signal can be used and combined.
    """
    PROPERTY = "property"       # Single property
    GEO = "geo"                 # Geographic polygon
    MARKET = "market"           # Broader market (multiple geos)
    PLATFORM = "platform"       # Platform-specific (Airbnb, VRBO)
    TENANT = "tenant"           # Operator-wide


class SignalSource(str, Enum):
    """
    Source system that generated the signal data.
    """
    # External Scraping
    AIRBNB_SCRAPE = "airbnb_scrape"
    VRBO_SCRAPE = "vrbo_scrape"
    BOOKING_SCRAPE = "booking_scrape"
    
    # PMS Data
    PMS_GUESTY = "pms_guesty"
    PMS_HOSTAWAY = "pms_hostaway"
    PMS_ESCAPIA = "pms_escapia"
    PMS_GENERIC = "pms_generic"
    
    # Internal Analytics
    INTERNAL_ANALYTICS = "internal_analytics"
    INTERNAL_COMPS = "internal_comps"
    
    # Third Party Data
    THIRD_PARTY_AIRDNA = "third_party_airdna"
    THIRD_PARTY_STR = "third_party_str"
    
    # Concierge Intelligence
    GUEST_MESSAGES = "guest_messages"
    GUEST_REVIEWS = "guest_reviews"
    
    # Manual/Derived
    MANUAL_INPUT = "manual_input"
    DERIVED = "derived"


class TimeWindow(str, Enum):
    """
    Time window over which signal was computed.
    """
    LAST_7D = "last_7d"
    LAST_14D = "last_14d"
    LAST_30D = "last_30d"
    LAST_60D = "last_60d"
    LAST_90D = "last_90d"
    LAST_180D = "last_180d"
    LAST_365D = "last_365d"
    
    # Specific periods
    Q1 = "q1"
    Q2 = "q2"
    Q3 = "q3"
    Q4 = "q4"
    
    # Rolling windows
    TRAILING_12M = "trailing_12m"
    FORWARD_30D = "forward_30d"
    FORWARD_60D = "forward_60d"
    FORWARD_90D = "forward_90d"
    
    # Seasonal
    PEAK_SEASON = "peak_season"
    SHOULDER_SEASON = "shoulder_season"
    OFF_SEASON = "off_season"
    
    # Point in time
    SNAPSHOT = "snapshot"


class DecayProfile(str, Enum):
    """
    How quickly signal relevance decays over time.
    """
    PERSISTENT = "persistent"       # Low decay (platform dominance)
    STABLE = "stable"               # Medium decay (amenity lifts)
    VOLATILE = "volatile"           # High decay (pricing, occupancy)
    SEASONAL = "seasonal"           # Decays until same season next year
    EPHEMERAL = "ephemeral"         # Very fast decay (real-time signals)


class GeoSensitivity(str, Enum):
    """
    How sensitive a signal is to geographic context.
    """
    PROPERTY_ONLY = "property_only"     # Only applies to specific property
    HYPERLOCAL = "hyperlocal"           # Neighborhood level
    LOCAL = "local"                     # City/submarket
    REGIONAL = "regional"               # DMA or state
    UNIVERSAL = "universal"             # Applies broadly


# =============================================================================
# SIGNAL VALUE TYPES
# =============================================================================

class NormalizedValue(BaseModel):
    """
    A normalized value between -1.0 and +1.0.
    
    Used for relative signals (better/worse, up/down).
    """
    value: float = Field(..., ge=-1.0, le=1.0)
    
    @classmethod
    def from_percentile(cls, percentile: float) -> "NormalizedValue":
        """Convert 0-100 percentile to normalized value."""
        return cls(value=(percentile - 50) / 50)


class AbsoluteValue(BaseModel):
    """
    An absolute value (ADR, occupancy %, count).
    
    Used for concrete measurements.
    """
    value: float
    unit: str  # "dollars", "percent", "count", "days"


class CategoricalValue(BaseModel):
    """
    A categorical signal value with distribution.
    
    Used for things like platform dominance.
    """
    dominant: str
    distribution: Dict[str, float]  # {"airbnb": 0.78, "vrbo": 0.22}


class CurveValue(BaseModel):
    """
    A curve or time series value.
    
    Used for seasonality, trends.
    """
    points: Dict[str, float]  # {"jan": 0.6, "feb": 0.7, ...}
    curve_type: str  # "monthly", "weekly", "daily"


# =============================================================================
# CORE SIGNAL MODEL
# =============================================================================

class Signal(BaseModel):
    """
    Canonical Signal - Interpreted Evidence.
    
    This is NOT raw data. This is what detectors produce after
    analyzing raw data and determining what it means.
    
    Key invariant: No math, pricing, or decisions occur before
    signals are normalized, scored, and confidence-weighted.
    """
    
    # === Identity ===
    signal_id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    
    # === Classification ===
    signal_type: SignalType
    scope: SignalScope
    
    # === Scope References ===
    geo_id: Optional[str] = None          # Polygon hash
    property_id: Optional[UUID] = None    # Specific property
    platform: Optional[str] = None        # airbnb, vrbo, etc.
    
    # === The Signal Value ===
    # Normalized [-1.0 → +1.0] OR absolute depending on signal_type
    value: float
    
    # Structured value for complex signals
    structured_value: Optional[Dict[str, Any]] = None
    
    # === Confidence & Weighting ===
    confidence: float = Field(..., ge=0.0, le=1.0)
    weight_hint: float = Field(default=1.0, ge=0.0, le=2.0)  # Detector suggestion, NOT final
    
    # === Provenance ===
    source: SignalSource
    detector_name: str              # Which detector produced this
    detector_version: str           # Detector version for reproducibility
    
    # === Temporal Context ===
    detected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    time_window: TimeWindow
    valid_from: Optional[date] = None
    valid_until: Optional[date] = None
    
    # === Decay & Geo Properties ===
    decay_profile: DecayProfile = DecayProfile.STABLE
    geo_sensitivity: GeoSensitivity = GeoSensitivity.LOCAL
    
    # === Metadata ===
    metadata: Dict[str, Any] = Field(default_factory=dict)
    # Expected metadata:
    # - explanation: str (human-readable)
    # - sample_size: int
    # - samples: List[str] (example data points)
    # - methodology: str
    # - warnings: List[str]
    # - comparisons: Dict (vs market, vs last period)
    
    # === Schema Version ===
    schema_version: str = SIGNAL_SCHEMA_VERSION
    
    @field_validator('value')
    @classmethod
    def validate_value_range(cls, v, info):
        """Validate value is in expected range for signal type."""
        # For most signals, we expect normalized [-1, 1]
        # But some (like ADR) are absolute values
        # This is a soft validation - structured_value should be used for complex cases
        return v
    
    @property
    def is_stale(self) -> bool:
        """Check if signal has decayed past usefulness."""
        if self.valid_until and date.today() > self.valid_until:
            return True
        return False
    
    @property
    def age_days(self) -> int:
        """Days since signal was detected."""
        return (datetime.now(timezone.utc) - self.detected_at).days
    
    def calculate_decay_factor(
        self, 
        as_of: Optional[datetime] = None,
        lambda_param: float = 0.1
    ) -> float:
        """
        Calculate time decay factor for this signal.
        
        decay_factor = exp(-λ * months_since_detected / seasonal_relevance)
        
        Returns value between 0 and 1.
        """
        import math
        
        as_of = as_of or datetime.now(timezone.utc)
        months_since = (as_of - self.detected_at).days / 30.0
        
        # Seasonal relevance modifier
        seasonal_relevance = {
            DecayProfile.PERSISTENT: 24.0,    # 2 year relevance
            DecayProfile.STABLE: 6.0,         # 6 month relevance
            DecayProfile.VOLATILE: 1.0,       # 1 month relevance
            DecayProfile.SEASONAL: 12.0,      # Annual cycle
            DecayProfile.EPHEMERAL: 0.25,     # 1 week relevance
        }.get(self.decay_profile, 3.0)
        
        decay = math.exp(-lambda_param * months_since / seasonal_relevance)
        return max(0.0, min(1.0, decay))
    
    def to_weighted_value(
        self, 
        as_of: Optional[datetime] = None
    ) -> float:
        """
        Get the effective weighted value accounting for confidence and decay.
        """
        decay = self.calculate_decay_factor(as_of)
        return self.value * self.confidence * decay
    
    model_config = ConfigDict(use_enum_values=True)


# =============================================================================
# SIGNAL COLLECTIONS
# =============================================================================

class SignalBundle(BaseModel):
    """
    Collection of signals for analytics engine consumption.
    
    Signals are pre-grouped by relevance.
    """
    tenant_id: UUID
    geo_id: Optional[str] = None
    property_id: Optional[UUID] = None
    
    signals: List[Signal] = Field(default_factory=list)
    
    collected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    
    def by_type(self, signal_type: SignalType) -> List[Signal]:
        """Get signals of a specific type."""
        return [s for s in self.signals if s.signal_type == signal_type]
    
    def by_scope(self, scope: SignalScope) -> List[Signal]:
        """Get signals with a specific scope."""
        return [s for s in self.signals if s.scope == scope]
    
    def most_recent(self, signal_type: SignalType) -> Optional[Signal]:
        """Get most recent signal of a type."""
        matching = self.by_type(signal_type)
        if not matching:
            return None
        return max(matching, key=lambda s: s.detected_at)
    
    def weighted_average(
        self, 
        signal_type: SignalType,
        as_of: Optional[datetime] = None
    ) -> Optional[float]:
        """
        Compute weighted average of signals accounting for confidence and decay.
        """
        signals = self.by_type(signal_type)
        if not signals:
            return None
        
        total_weight = 0.0
        weighted_sum = 0.0
        
        for s in signals:
            decay = s.calculate_decay_factor(as_of)
            weight = s.confidence * decay * s.weight_hint
            weighted_sum += s.value * weight
            total_weight += weight
        
        if total_weight == 0:
            return None
        
        return weighted_sum / total_weight
    
    @property
    def overall_confidence(self) -> float:
        """Average confidence across all signals."""
        if not self.signals:
            return 0.0
        return sum(s.confidence for s in self.signals) / len(self.signals)
    
    def filter_stale(self) -> "SignalBundle":
        """Return new bundle with stale signals removed."""
        return SignalBundle(
            tenant_id=self.tenant_id,
            geo_id=self.geo_id,
            property_id=self.property_id,
            signals=[s for s in self.signals if not s.is_stale],
            collected_at=datetime.now(timezone.utc),
        )


# =============================================================================
# SIGNAL METADATA HELPERS
# =============================================================================

def create_signal_metadata(
    explanation: str,
    sample_size: int,
    methodology: Optional[str] = None,
    samples: Optional[List[str]] = None,
    warnings: Optional[List[str]] = None,
    comparisons: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Create properly structured signal metadata.
    """
    meta = {
        "explanation": explanation,
        "sample_size": sample_size,
    }
    
    if methodology:
        meta["methodology"] = methodology
    if samples:
        meta["samples"] = samples
    if warnings:
        meta["warnings"] = warnings
    if comparisons:
        meta["comparisons"] = comparisons
    
    return meta


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Version
    "SIGNAL_SCHEMA_VERSION",
    
    # Enums
    "SignalType",
    "SignalScope",
    "SignalSource",
    "TimeWindow",
    "DecayProfile",
    "GeoSensitivity",
    
    # Value types
    "NormalizedValue",
    "AbsoluteValue",
    "CategoricalValue",
    "CurveValue",
    
    # Core
    "Signal",
    "SignalBundle",
    
    # Helpers
    "create_signal_metadata",
]
