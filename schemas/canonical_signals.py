"""
Canonical Signal Schemas - The Single Source of Truth

NON-NEGOTIABLE RULE:
➡️ No downstream system may compute truth outside this schema.

Every signal in the platform MUST:
1. Conform to the base Signal schema
2. Include confidence bands (not just point estimates)
3. Have explicit decay semantics
4. Carry attribution metadata for explainability

This file defines:
- Core Signal base class
- All signal type enums
- Type-specific signal schemas
- Validation rules
- Serialization contracts
"""

from datetime import datetime, date
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Tuple, Union
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator, model_validator


# =============================================================================
# ENUMS
# =============================================================================

class SignalType(str, Enum):
    """
    Canonical signal types.
    
    Each type has specific semantics for its value field
    and distinct decay/confidence characteristics.
    """
    # Supply Signals
    SUPPLY_DENSITY = "supply_density"
    BEDROOM_DISTRIBUTION = "bedroom_distribution"
    PROPERTY_TYPE_MIX = "property_type_mix"
    
    # Demand Signals
    CALENDAR_COMPRESSION = "calendar_compression"
    LEAD_TIME = "lead_time"
    RATE_ACCELERATION = "rate_acceleration"
    
    # Platform Signals
    PLATFORM_DOMINANCE = "platform_dominance"
    PLATFORM_PERFORMANCE_BIAS = "platform_performance_bias"
    
    # Amenity Signals
    AMENITY_PREVALENCE = "amenity_prevalence"
    AMENITY_LIFT = "amenity_lift"
    
    # Seasonality Signals
    SEASONALITY = "seasonality"
    SEASONALITY_CURVE = "seasonality_curve"
    
    # Operator Signals (Opt-In)
    OPERATOR_DELTA = "operator_delta"
    OPERATIONAL_STABILITY = "operational_stability"
    
    # Regulatory Signals
    REGULATORY_RISK = "regulatory_risk"
    STR_RESTRICTION = "str_restriction"
    
    # Macro/Peripheral Signals
    TRAVEL_FLOW = "travel_flow"
    EVENT_IMPACT = "event_impact"
    WEATHER_PATTERN = "weather_pattern"
    TRANSACTION_VELOCITY = "transaction_velocity"
    HOUSING_STOCK = "housing_stock"
    
    # Rate Signals
    RATE_POSITION = "rate_position"
    RATE_BY_BEDROOM = "rate_by_bedroom"


class SignalSource(str, Enum):
    """
    Where the signal data originated.
    
    Used for:
    - Confidence weighting
    - Attribution in outputs
    - Audit trails
    """
    # 🟡 Passive Observation (Public OTA)
    AIRBNB_PUBLIC = "airbnb_public"
    VRBO_PUBLIC = "vrbo_public"
    BOOKING_PUBLIC = "booking_public"
    
    # 🟢 Open/Public (No auth, no risk)
    CENSUS_ACS = "census_acs"
    BTS_DOT = "bts_dot"
    NOAA_NWS = "noaa_nws"
    COUNTY_ASSESSOR = "county_assessor"
    COUNTY_RECORDER = "county_recorder"
    STATE_TOURISM = "state_tourism"
    LOCAL_CVB = "local_cvb"
    FAA_STATS = "faa_stats"
    
    # 🔵 Opt-In/Operator (Encrypted, isolated)
    OPERATOR_PMS = "operator_pms"
    OPERATOR_MANUAL = "operator_manual"
    
    # 🟣 Derived/Inferred (No raw dependency)
    DERIVED = "derived"
    INFERRED = "inferred"
    AGGREGATED = "aggregated"
    
    # Historical/Cached
    HISTORICAL_CACHE = "historical_cache"


class ConfidenceLevel(str, Enum):
    """Human-readable confidence levels."""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INSUFFICIENT = "insufficient"


# =============================================================================
# BASE SIGNAL SCHEMA
# =============================================================================

class Signal(BaseModel):
    """
    Base signal schema - ALL signals must conform to this.
    
    This is the canonical contract for signal data throughout
    the entire platform. No exceptions.
    """
    # Identity
    signal_id: UUID = Field(default_factory=uuid4)
    signal_type: SignalType
    
    # Scope
    geo_id: str = Field(..., description="Polygon hash or market identifier")
    property_id: Optional[UUID] = Field(None, description="If property-specific")
    
    # Source attribution
    source: SignalSource
    source_detail: Optional[str] = Field(None, description="Specific endpoint/file")
    
    # Value - can be scalar or structured
    value: Union[float, int, Dict[str, Any]]
    unit: Optional[str] = Field(None, description="e.g., 'percent', 'dollars', 'count'")
    
    # Confidence - REQUIRED, not optional
    confidence: float = Field(..., ge=0.0, le=1.0)
    confidence_band: Tuple[float, float] = Field(
        ..., 
        description="(low, high) bounds for the value"
    )
    confidence_level: ConfidenceLevel = Field(default=ConfidenceLevel.MEDIUM)
    
    # Temporal semantics
    decay_half_life_days: int = Field(
        default=30,
        description="How quickly this signal loses relevance"
    )
    observed_at: datetime = Field(default_factory=datetime.utcnow)
    valid_from: datetime = Field(default_factory=datetime.utcnow)
    valid_to: Optional[datetime] = Field(None, description="Explicit expiration")
    
    # Explainability payload
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Attribution, sample sizes, methodology notes"
    )
    
    @field_validator('confidence_band')
    @classmethod
    def validate_confidence_band(cls, v):
        low, high = v
        if low > high:
            raise ValueError("confidence_band low must be <= high")
        return v
    
    @model_validator(mode='after')
    def set_confidence_level(self):
        """Auto-set confidence level from numeric confidence."""
        if self.confidence >= 0.75:
            self.confidence_level = ConfidenceLevel.HIGH
        elif self.confidence >= 0.5:
            self.confidence_level = ConfidenceLevel.MEDIUM
        elif self.confidence >= 0.25:
            self.confidence_level = ConfidenceLevel.LOW
        else:
            self.confidence_level = ConfidenceLevel.INSUFFICIENT
        return self
    
    def decayed_confidence(self, as_of: Optional[datetime] = None) -> float:
        """Calculate confidence with time decay applied."""
        as_of = as_of or datetime.utcnow()
        days_elapsed = (as_of - self.observed_at).days
        
        if days_elapsed <= 0:
            return self.confidence
        
        # Exponential decay
        import math
        decay_factor = math.exp(-0.693 * days_elapsed / self.decay_half_life_days)
        return self.confidence * decay_factor
    
    def is_valid(self, as_of: Optional[datetime] = None) -> bool:
        """Check if signal is still valid."""
        as_of = as_of or datetime.utcnow()
        
        if self.valid_to and as_of > self.valid_to:
            return False
        
        if as_of < self.valid_from:
            return False
        
        # Consider signal invalid if decayed below threshold
        if self.decayed_confidence(as_of) < 0.1:
            return False
        
        return True
    
    def attribution_text(self) -> str:
        """Generate human-readable attribution for PDFs/reports."""
        source_names = {
            SignalSource.AIRBNB_PUBLIC: "Airbnb public listings",
            SignalSource.VRBO_PUBLIC: "VRBO public listings",
            SignalSource.CENSUS_ACS: "US Census American Community Survey",
            SignalSource.BTS_DOT: "Bureau of Transportation Statistics",
            SignalSource.NOAA_NWS: "NOAA National Weather Service",
            SignalSource.COUNTY_ASSESSOR: "County Tax Assessor records",
            SignalSource.OPERATOR_PMS: "Operator property management data",
            SignalSource.DERIVED: "Derived analysis",
        }
        
        source_text = source_names.get(self.source, self.source.value)
        date_text = self.observed_at.strftime("%b %Y")
        conf_text = f"{self.confidence:.0%} confidence"
        
        return f"Source: {source_text} ({date_text}, {conf_text})"


# =============================================================================
# SUPPLY SIGNALS
# =============================================================================

class SupplyDensityValue(BaseModel):
    """Value schema for supply density signal."""
    listings: int
    listings_per_sq_mile: float
    listings_per_1000_homes: Optional[float] = None


class SupplyDensitySignal(Signal):
    """
    Active listing density in a market.
    
    Feeds into:
    - Market saturation score
    - ADR ceiling constraint
    - Discount denial logic
    """
    signal_type: Literal[SignalType.SUPPLY_DENSITY] = SignalType.SUPPLY_DENSITY
    value: SupplyDensityValue
    unit: str = "listings"
    decay_half_life_days: int = 14  # Supply changes relatively quickly


class BedroomDistributionValue(BaseModel):
    """Value schema for bedroom distribution."""
    distribution: Dict[int, int]  # {bedrooms: count}
    distribution_pct: Dict[int, float]  # {bedrooms: percentage}
    median_bedrooms: float


class BedroomDistributionSignal(Signal):
    """Bedroom mix in a market."""
    signal_type: Literal[SignalType.BEDROOM_DISTRIBUTION] = SignalType.BEDROOM_DISTRIBUTION
    value: BedroomDistributionValue
    unit: str = "count"
    decay_half_life_days: int = 30


# =============================================================================
# DEMAND SIGNALS
# =============================================================================

class CalendarCompressionValue(BaseModel):
    """Value schema for calendar compression."""
    blocked_pct_7d: float = Field(ge=0, le=1)
    blocked_pct_14d: float = Field(ge=0, le=1)
    blocked_pct_30d: float = Field(ge=0, le=1)
    blocked_pct_60d: Optional[float] = Field(None, ge=0, le=1)
    blocked_pct_90d: Optional[float] = Field(None, ge=0, le=1)
    sample_size: int


class CalendarCompressionSignal(Signal):
    """
    Demand pressure inferred from calendar availability.
    
    Feeds into:
    - Demand momentum
    - Discount approvals
    - Voice demand posture ("strong interest")
    """
    signal_type: Literal[SignalType.CALENDAR_COMPRESSION] = SignalType.CALENDAR_COMPRESSION
    value: CalendarCompressionValue
    unit: str = "percent_blocked"
    decay_half_life_days: int = 7  # Demand signals decay quickly


class LeadTimeValue(BaseModel):
    """Value schema for lead time signal."""
    median_days_to_booking: int
    mean_days_to_booking: Optional[float] = None
    trend_delta_pct: float  # Positive = lengthening, negative = shortening
    sample_size: int


class LeadTimeSignal(Signal):
    """
    Booking lead time trends.
    
    Feeds into:
    - Urgency language
    - Short-lead discount logic
    """
    signal_type: Literal[SignalType.LEAD_TIME] = SignalType.LEAD_TIME
    value: LeadTimeValue
    unit: str = "days"
    decay_half_life_days: int = 14


class RateAccelerationValue(BaseModel):
    """Value schema for rate acceleration."""
    rate_change_pct_7d: float
    rate_change_pct_30d: float
    ewma_slope: float  # Exponentially weighted moving average slope
    sample_size: int


class RateAccelerationSignal(Signal):
    """
    Price pressure / rate trends.
    
    Feeds into:
    - Dynamic pricing signals
    - Rate positioning
    """
    signal_type: Literal[SignalType.RATE_ACCELERATION] = SignalType.RATE_ACCELERATION
    value: RateAccelerationValue
    unit: str = "percent_change"
    decay_half_life_days: int = 7


# =============================================================================
# PLATFORM SIGNALS
# =============================================================================

class PlatformDominanceValue(BaseModel):
    """Value schema for platform dominance."""
    airbnb_share: float = Field(ge=0, le=1)
    vrbo_share: float = Field(ge=0, le=1)
    other_share: float = Field(default=0, ge=0, le=1)
    dominant_platform: Literal["airbnb", "vrbo", "balanced"]
    dominance_ratio: float  # Higher = more lopsided


class PlatformDominanceSignal(Signal):
    """
    Channel distribution in a market.
    
    Feeds into:
    - ADR weighting by platform
    - Channel-specific confidence
    - Expansion market similarity scoring
    """
    signal_type: Literal[SignalType.PLATFORM_DOMINANCE] = SignalType.PLATFORM_DOMINANCE
    value: PlatformDominanceValue
    unit: str = "share"
    decay_half_life_days: int = 30


# =============================================================================
# AMENITY SIGNALS
# =============================================================================

class AmenityPrevalenceValue(BaseModel):
    """Value schema for amenity prevalence."""
    amenity: str
    prevalence_pct: float = Field(ge=0, le=1)
    count: int
    total_listings: int


class AmenityPrevalenceSignal(Signal):
    """
    How common an amenity is in the market.
    
    Used for:
    - Scarcity premium calculation
    - Feature differentiation
    """
    signal_type: Literal[SignalType.AMENITY_PREVALENCE] = SignalType.AMENITY_PREVALENCE
    value: AmenityPrevalenceValue
    unit: str = "percent"
    decay_half_life_days: int = 30


class AmenityLiftValue(BaseModel):
    """Value schema for amenity ADR lift."""
    amenity: str
    adr_lift_pct: float  # Can be negative
    adr_lift_dollars: Optional[float] = None
    sample_size: int
    control_sample_size: int


class AmenityLiftSignal(Signal):
    """
    ADR premium/discount for an amenity.
    
    Feeds into:
    - Rent projection math
    - What-if scenarios
    - Attribution badges in PDF
    """
    signal_type: Literal[SignalType.AMENITY_LIFT] = SignalType.AMENITY_LIFT
    value: AmenityLiftValue
    unit: str = "percent_lift"
    decay_half_life_days: int = 60  # Amenity value is relatively stable


# =============================================================================
# SEASONALITY SIGNALS
# =============================================================================

class SeasonalityValue(BaseModel):
    """Value schema for single-month seasonality."""
    month: int = Field(ge=1, le=12)
    month_name: str
    seasonality_index: float  # 1.0 = average, >1 = above, <1 = below
    occupancy_expected: Optional[float] = None
    adr_expected: Optional[float] = None


class SeasonalitySignal(Signal):
    """
    Single-month seasonality index.
    
    Feeds into:
    - Monthly revenue tables
    - Demand posture
    - Expansion market comparability
    """
    signal_type: Literal[SignalType.SEASONALITY] = SignalType.SEASONALITY
    value: SeasonalityValue
    unit: str = "index"
    decay_half_life_days: int = 365  # Seasonal patterns are stable


class SeasonalityCurveValue(BaseModel):
    """Full 12-month seasonality curve."""
    curve: Dict[int, float]  # {month: index}
    peak_month: int
    trough_month: int
    amplitude: float  # peak - trough
    curve_type: Literal["beach", "ski", "urban", "flat", "custom"]


class SeasonalityCurveSignal(Signal):
    """Full seasonality curve for a market."""
    signal_type: Literal[SignalType.SEASONALITY_CURVE] = SignalType.SEASONALITY_CURVE
    value: SeasonalityCurveValue
    unit: str = "curve"
    decay_half_life_days: int = 365


# =============================================================================
# OPERATOR SIGNALS (OPT-IN)
# =============================================================================

class OperatorDeltaValue(BaseModel):
    """Value schema for operator performance delta."""
    delta_pct: float = Field(ge=-0.20, le=0.20)  # Hard capped at ±20%
    confidence_cap: float = Field(default=0.06, le=0.06)  # Max 6% in projections
    sample_months: int
    
    @field_validator('delta_pct')
    @classmethod
    def cap_delta(cls, v):
        """Enforce hard cap on operator delta."""
        return max(-0.06, min(0.06, v))  # Cap at ±6% for projections


class OperatorDeltaSignal(Signal):
    """
    Operator performance vs market baseline.
    
    RULES:
    - Hard capped (±6% in projections)
    - Never disclosed numerically to guests
    - Allowed in BD decks
    """
    signal_type: Literal[SignalType.OPERATOR_DELTA] = SignalType.OPERATOR_DELTA
    value: OperatorDeltaValue
    unit: str = "percent_delta"
    decay_half_life_days: int = 90
    source: SignalSource = SignalSource.OPERATOR_PMS


# =============================================================================
# REGULATORY SIGNALS
# =============================================================================

class RegulatoryRiskValue(BaseModel):
    """Value schema for regulatory risk."""
    risk_level: Literal["low", "medium", "high"]
    restriction_type: Optional[str] = None  # e.g., "cap", "zone", "permit"
    description: Optional[str] = None
    effective_date: Optional[date] = None
    source_url: Optional[str] = None


class RegulatoryRiskSignal(Signal):
    """
    STR regulatory environment assessment.
    
    Feeds into:
    - Confidence bands
    - Investment risk notes
    """
    signal_type: Literal[SignalType.REGULATORY_RISK] = SignalType.REGULATORY_RISK
    value: RegulatoryRiskValue
    unit: str = "risk_level"
    decay_half_life_days: int = 180  # Regulatory changes are infrequent


# =============================================================================
# MACRO / PERIPHERAL SIGNALS
# =============================================================================

class TravelFlowValue(BaseModel):
    """Value schema for travel flow signal."""
    airport_code: Optional[str] = None
    passenger_count: Optional[int] = None
    yoy_change_pct: float
    seasonal_index: float
    period: str  # e.g., "2024-Q3"


class TravelFlowSignal(Signal):
    """
    Regional travel demand from DOT/FAA data.
    
    Feeds into:
    - Macro demand context
    - Market comparison
    """
    signal_type: Literal[SignalType.TRAVEL_FLOW] = SignalType.TRAVEL_FLOW
    value: TravelFlowValue
    unit: str = "passengers"
    source: SignalSource = SignalSource.BTS_DOT
    decay_half_life_days: int = 90


class EventImpactValue(BaseModel):
    """Value schema for event impact."""
    event_name: str
    event_type: str  # "conference", "festival", "sports", etc.
    expected_visitors: Optional[int] = None
    duration_days: int
    impact_radius_miles: float
    start_date: date
    end_date: date
    impact_multiplier: float  # Expected demand lift


class EventImpactSignal(Signal):
    """
    Local event demand impact.
    
    Feeds into:
    - Short-term demand spikes
    - Pricing recommendations
    """
    signal_type: Literal[SignalType.EVENT_IMPACT] = SignalType.EVENT_IMPACT
    value: EventImpactValue
    unit: str = "multiplier"
    source: SignalSource = SignalSource.LOCAL_CVB
    decay_half_life_days: int = 7  # Very short-lived


class TransactionVelocityValue(BaseModel):
    """Value schema for real estate transaction velocity."""
    sales_per_month: float
    avg_sale_price: float
    median_sale_price: float
    yoy_change_pct: float
    trend: Literal["accelerating", "stable", "decelerating"]


class TransactionVelocitySignal(Signal):
    """
    Real estate transaction activity.
    
    Feeds into:
    - Investment market timing
    - Supply forecasting
    """
    signal_type: Literal[SignalType.TRANSACTION_VELOCITY] = SignalType.TRANSACTION_VELOCITY
    value: TransactionVelocityValue
    unit: str = "transactions"
    source: SignalSource = SignalSource.COUNTY_RECORDER
    decay_half_life_days: int = 60


class HousingStockValue(BaseModel):
    """Value schema for housing stock data."""
    total_housing_units: int
    vacancy_rate: float
    median_home_value: float
    median_rent: Optional[float] = None
    second_home_pct: Optional[float] = None


class HousingStockSignal(Signal):
    """
    Census housing stock data.
    
    Critical for:
    - Supply normalization
    - Luxury segmentation
    """
    signal_type: Literal[SignalType.HOUSING_STOCK] = SignalType.HOUSING_STOCK
    value: HousingStockValue
    unit: str = "units"
    source: SignalSource = SignalSource.CENSUS_ACS
    decay_half_life_days: int = 365  # Census data is annual


# =============================================================================
# RATE SIGNALS
# =============================================================================

class RatePositionValue(BaseModel):
    """Value schema for rate position."""
    p10: float
    p25: float
    p50: float  # Median
    p75: float
    p90: float
    sample_size: int


class RatePositionSignal(Signal):
    """
    Market rate distribution.
    
    Feeds into:
    - Property positioning
    - Competitive analysis
    """
    signal_type: Literal[SignalType.RATE_POSITION] = SignalType.RATE_POSITION
    value: RatePositionValue
    unit: str = "dollars"
    decay_half_life_days: int = 14


class RateByBedroomValue(BaseModel):
    """Value schema for rate by bedroom."""
    rates: Dict[int, float]  # {bedrooms: median_rate}
    sample_sizes: Dict[int, int]  # {bedrooms: count}


class RateByBedroomSignal(Signal):
    """Rate distribution by bedroom count."""
    signal_type: Literal[SignalType.RATE_BY_BEDROOM] = SignalType.RATE_BY_BEDROOM
    value: RateByBedroomValue
    unit: str = "dollars"
    decay_half_life_days: int = 14


# =============================================================================
# SIGNAL BUNDLE
# =============================================================================

class SignalBundle(BaseModel):
    """
    Collection of signals for a specific scope (geo + time).
    
    This is what gets passed to analytics engines.
    """
    bundle_id: UUID = Field(default_factory=uuid4)
    geo_id: str
    property_id: Optional[UUID] = None
    
    # Temporal scope
    as_of: datetime = Field(default_factory=datetime.utcnow)
    
    # Signals by type
    signals: List[Signal] = Field(default_factory=list)
    
    # Coverage metrics
    signal_coverage: Dict[str, bool] = Field(default_factory=dict)
    coverage_score: float = Field(default=0.0, ge=0.0, le=1.0)
    
    # Aggregated confidence
    overall_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    confidence_level: ConfidenceLevel = Field(default=ConfidenceLevel.MEDIUM)
    
    def add_signal(self, signal: Signal):
        """Add a signal to the bundle."""
        self.signals.append(signal)
        self.signal_coverage[signal.signal_type.value] = True
        self._recalculate_metrics()
    
    def get_signal(self, signal_type: SignalType) -> Optional[Signal]:
        """Get most recent signal of a type."""
        matching = [s for s in self.signals if s.signal_type == signal_type]
        if not matching:
            return None
        return max(matching, key=lambda s: s.observed_at)
    
    def get_signals(self, signal_type: SignalType) -> List[Signal]:
        """Get all signals of a type."""
        return [s for s in self.signals if s.signal_type == signal_type]
    
    def _recalculate_metrics(self):
        """Recalculate coverage and confidence metrics."""
        # Coverage: what % of core signal types do we have?
        core_types = [
            SignalType.SUPPLY_DENSITY,
            SignalType.CALENDAR_COMPRESSION,
            SignalType.PLATFORM_DOMINANCE,
            SignalType.AMENITY_PREVALENCE,
            SignalType.RATE_POSITION,
            SignalType.SEASONALITY_CURVE,
        ]
        
        covered = sum(1 for t in core_types if t.value in self.signal_coverage)
        self.coverage_score = covered / len(core_types)
        
        # Overall confidence: weighted average of signal confidences
        if self.signals:
            valid_signals = [s for s in self.signals if s.is_valid(self.as_of)]
            if valid_signals:
                weights = [s.decayed_confidence(self.as_of) for s in valid_signals]
                total_weight = sum(weights)
                if total_weight > 0:
                    self.overall_confidence = sum(
                        s.confidence * w for s, w in zip(valid_signals, weights)
                    ) / total_weight
        
        # Set confidence level
        if self.overall_confidence >= 0.75 and self.coverage_score >= 0.8:
            self.confidence_level = ConfidenceLevel.HIGH
        elif self.overall_confidence >= 0.5 and self.coverage_score >= 0.5:
            self.confidence_level = ConfidenceLevel.MEDIUM
        elif self.overall_confidence >= 0.25:
            self.confidence_level = ConfidenceLevel.LOW
        else:
            self.confidence_level = ConfidenceLevel.INSUFFICIENT
    
    def attribution_summary(self) -> List[str]:
        """Generate attribution text for all signals."""
        return [s.attribution_text() for s in self.signals if s.is_valid(self.as_of)]


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Enums
    "SignalType",
    "SignalSource",
    "ConfidenceLevel",
    
    # Base
    "Signal",
    "SignalBundle",
    
    # Supply
    "SupplyDensitySignal",
    "SupplyDensityValue",
    "BedroomDistributionSignal",
    "BedroomDistributionValue",
    
    # Demand
    "CalendarCompressionSignal",
    "CalendarCompressionValue",
    "LeadTimeSignal",
    "LeadTimeValue",
    "RateAccelerationSignal",
    "RateAccelerationValue",
    
    # Platform
    "PlatformDominanceSignal",
    "PlatformDominanceValue",
    
    # Amenity
    "AmenityPrevalenceSignal",
    "AmenityPrevalenceValue",
    "AmenityLiftSignal",
    "AmenityLiftValue",
    
    # Seasonality
    "SeasonalitySignal",
    "SeasonalityValue",
    "SeasonalityCurveSignal",
    "SeasonalityCurveValue",
    
    # Operator
    "OperatorDeltaSignal",
    "OperatorDeltaValue",
    
    # Regulatory
    "RegulatoryRiskSignal",
    "RegulatoryRiskValue",
    
    # Macro
    "TravelFlowSignal",
    "TravelFlowValue",
    "EventImpactSignal",
    "EventImpactValue",
    "TransactionVelocitySignal",
    "TransactionVelocityValue",
    "HousingStockSignal",
    "HousingStockValue",
    
    # Rate
    "RatePositionSignal",
    "RatePositionValue",
    "RateByBedroomSignal",
    "RateByBedroomValue",
]
