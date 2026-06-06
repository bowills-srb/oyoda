"""
Canonical Contracts v1.0.0 - The Internal RFC.

This file defines THE contracts for all system boundaries.
If it's not in here, it's not part of the API.

Philosophy (Non-Negotiable):
1. Signals are immutable facts
2. Analytics are pure consumers
3. Outputs always carry confidence
4. Voice & BD never compute
5. Everything is geo-scoped + time-scoped
6. Every number has provenance

This is why competitors can't replicate us.
"""

from datetime import datetime, date, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Tuple, Union
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, ConfigDict, field_validator


# =============================================================================
# CONTRACT VERSION
# =============================================================================

CONTRACT_VERSION = "1.0.0"


# =============================================================================
# SIGNAL CONTRACT (Foundation - §2 of RFC)
# =============================================================================

class SignalType(str, Enum):
    """Canonical signal types."""
    SEASONALITY = "seasonality"
    PLATFORM_DOMINANCE = "platform_dominance"
    AMENITY_LIFT = "amenity_lift"
    OPERATOR_DELTA = "operator_delta"
    DEMAND_MOMENTUM = "demand_momentum"
    SUPPLY_PRESSURE = "supply_pressure"
    EVENT_IMPACT = "event_impact"
    PRICE_ELASTICITY = "price_elasticity"
    OCCUPANCY_MOMENTUM = "occupancy_momentum"
    RATE_POSITION = "rate_position"
    COMPETITOR_MOVEMENT = "competitor_movement"


class SignalSource(str, Enum):
    """Where signals come from."""
    SCRAPED = "scraped"
    INTERNAL = "internal"
    PARTNER = "partner"


class Signal(BaseModel):
    """
    Canonical Signal Schema (§2).
    
    Stored once, never recomputed downstream.
    """
    signal_id: UUID = Field(default_factory=uuid4)
    signal_type: SignalType
    geo_id: str = Field(..., description="User-defined polygon or system geo")
    source: SignalSource
    value: Union[float, Dict[str, Any]] = Field(..., description="Signal value or structured data")
    confidence: float = Field(..., ge=0.0, le=1.0, description="0.0-1.0")
    decay_half_life_days: int = Field(default=30)
    observed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    valid_from: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    valid_to: Optional[datetime] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(frozen=True)


# =============================================================================
# SIGNAL BUNDLE CONTRACT (Consumption Boundary - §3)
# =============================================================================

class SignalBundle(BaseModel):
    """
    SignalBundle Contract (§3).
    
    The consumption boundary for all downstream consumers:
    - Analytics engine
    - Discount engine
    - Concierge
    - BD projections
    """
    geo_id: str
    as_of: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    signals: List[Signal] = Field(default_factory=list)
    coverage_score: float = Field(default=0.0, description="% of expected signals present")
    confidence_score: float = Field(default=0.0, description="Weighted composite confidence")


# =============================================================================
# GATING CONTRACT (Safety Boundary)
# =============================================================================

class GatingDecision(str, Enum):
    """Gating decisions for outputs."""
    ALLOWED = "allowed"
    GATED_LOW_CONFIDENCE = "gated_low_confidence"
    GATED_MISSING_SIGNALS = "gated_missing_signals"
    GATED_POLICY = "gated_policy"
    ESCALATE = "escalate"


class GatingResult(BaseModel):
    """Result of gating check."""
    decision: GatingDecision
    reason: Optional[str] = None
    required_confidence: float = 0.0
    actual_confidence: float = 0.0
    missing_signals: List[SignalType] = Field(default_factory=list)


# =============================================================================
# ATTRIBUTION CONTRACT (Explainability - §4)
# =============================================================================

class AttributionDriver(BaseModel):
    """
    Attribution Driver (§4).
    
    Explains what drove a metric.
    """
    signal_type: SignalType
    label: str = Field(..., description="Human-readable: 'Pool', 'Seasonality', etc.")
    impact_pct: float = Field(..., description="Percentage impact on metric")
    impact_value: float = Field(..., description="Absolute value impact")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


# =============================================================================
# ANALYTICS OUTPUT CONTRACT (Universal - §4)
# =============================================================================

class MetricType(str, Enum):
    """Types of analytics metrics."""
    ADR = "adr"
    OCCUPANCY = "occupancy"
    REVPAR = "revpar"
    DEMAND = "demand"
    REVENUE = "revenue"


class AnalyticsResult(BaseModel):
    """
    Analytics Result Contract (§4).
    
    Universal output for all analytics.
    """
    metric: MetricType
    expected: float
    low: float
    high: float
    confidence: float = Field(..., ge=0.0, le=1.0)
    drivers: List[AttributionDriver] = Field(default_factory=list)
    gating: GatingResult


# =============================================================================
# PROPERTY SCHEMA (Shared - §6)
# =============================================================================

class PropertyProfile(BaseModel):
    """
    Property Profile Contract (§6).
    
    Shared property representation.
    """
    property_id: Optional[UUID] = None
    bedrooms: int = Field(..., ge=1, le=20)
    bathrooms: float = Field(default=2.0, ge=1)
    max_guests: int = Field(default=6, ge=1)
    amenities: List[str] = Field(default_factory=list)
    is_luxury: bool = False
    allows_pets: bool = False
    sqft: Optional[int] = None
    property_type: str = "single_family"


class AmenityScore(BaseModel):
    """
    Amenity Score Contract (§6).
    
    Geo-specific amenity value.
    """
    amenity: str
    geo_id: str
    uplift_pct: float
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


# =============================================================================
# RENT PROJECTION CONTRACT (BD Core - §5)
# =============================================================================

class MonthlyProjection(BaseModel):
    """Monthly projection details."""
    month: int = Field(..., ge=1, le=12)
    month_name: str
    adr: float
    occupancy: float
    revenue: float
    confidence: float


class SensitivityScenario(BaseModel):
    """Sensitivity analysis scenario."""
    name: str
    adr_delta_pct: float
    occupancy_delta_pct: float
    revenue_impact: float


class SensitivityMatrix(BaseModel):
    """Sensitivity analysis matrix."""
    scenarios: List[SensitivityScenario] = Field(default_factory=list)


class ComparableProperty(BaseModel):
    """Comparable property used in analysis."""
    property_id: Optional[UUID] = None
    bedrooms: int
    adr: float
    occupancy: float
    distance_miles: Optional[float] = None
    similarity_score: float = Field(default=0.0, ge=0.0, le=1.0)


class RentProjection(BaseModel):
    """
    Rent Projection Contract (§5).
    
    BD core output.
    """
    geo_id: str
    property_profile: PropertyProfile
    annual: AnalyticsResult
    monthly: List[MonthlyProjection] = Field(default_factory=list)
    comps_used: List[ComparableProperty] = Field(default_factory=list)
    sensitivity: Optional[SensitivityMatrix] = None
    computed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# =============================================================================
# OPERATOR & EXPANSION CONTRACTS (§7)
# =============================================================================

class OperatorProfile(BaseModel):
    """
    Operator Profile Contract (§7).
    
    Operator characteristics for analysis.
    """
    operator_id: UUID
    portfolio_size: int = Field(default=1, ge=1)
    avg_adr: float = Field(default=0.0)
    amenity_mix: Dict[str, float] = Field(default_factory=dict)
    performance_index: float = Field(default=1.0, description="1.0 = market average")
    primary_platform: str = "balanced"
    typical_property_type: str = "single_family"


class ExpansionReadiness(BaseModel):
    """
    Expansion Readiness Contract (§7).
    
    Market entry decision support.
    """
    geo_id: str
    market_name: str
    score: int = Field(..., ge=0, le=100)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    strengths: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    recommendation: str = ""
    action_items: List[str] = Field(default_factory=list)


# =============================================================================
# CONCIERGE CONTRACTS (§8, §9)
# =============================================================================

class MessageSender(str, Enum):
    """Message sender type."""
    GUEST = "guest"
    HOST = "host"
    SYSTEM = "system"


class GuestMessage(BaseModel):
    """
    Guest Message Contract (§8).
    
    Normalized PMS message.
    """
    message_id: UUID = Field(default_factory=uuid4)
    property_id: UUID
    thread_id: UUID
    sender: MessageSender
    content: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    inferred_topics: List[str] = Field(default_factory=list)


class KnowledgeScope(str, Enum):
    """Scope of knowledge fact."""
    PROPERTY = "property"
    GEO = "geo"
    GLOBAL = "global"


class KnowledgeSource(str, Enum):
    """Source of knowledge fact."""
    PMS = "pms"
    SCRAPED = "scraped"
    CURATED = "curated"
    INFERRED = "inferred"


class KnowledgeFact(BaseModel):
    """
    Knowledge Fact Contract (§8).
    
    Concierge knowledge base entry.
    """
    fact_id: UUID = Field(default_factory=uuid4)
    scope: KnowledgeScope
    property_id: Optional[UUID] = None
    geo_id: Optional[str] = None
    topic: str
    content: str
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    source: KnowledgeSource


class ConciergeResponse(BaseModel):
    """
    Concierge Response Contract (§9).
    
    Voice-safe output. Voice never sees raw signals.
    """
    text: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    allowed_claims: List[str] = Field(default_factory=list)
    escalation_required: bool = False
    sources_used: List[str] = Field(default_factory=list, description="SignalTypes or KnowledgeFact IDs")
    tone: str = "helpful"


# =============================================================================
# DISCOUNT CONTRACT (§10)
# =============================================================================

class DiscountDecision(str, Enum):
    """Discount decision outcomes."""
    APPROVE = "approve"
    COUNTER = "counter"
    DENY = "deny"
    ESCALATE = "escalate"


class DiscountEvaluation(BaseModel):
    """
    Discount Evaluation Contract (§10).
    """
    requested_pct: float = Field(..., ge=0.0, le=1.0)
    decision: DiscountDecision
    max_allowed_pct: float = Field(..., ge=0.0, le=1.0)
    counter_offer_pct: Optional[float] = None
    rationale: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    gating: GatingResult


# =============================================================================
# BNPL CONTRACT (Future-Ready - §11)
# =============================================================================

class BNPLEligibility(BaseModel):
    """
    BNPL Eligibility Contract (§11).
    
    Future-ready. Signal-gated, never unconditional.
    """
    eligible: bool
    max_installments: int = Field(default=0, ge=0, le=12)
    max_amount: Optional[float] = None
    rationale: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    required_signals: List[SignalType] = Field(default_factory=list)


# =============================================================================
# INVESTMENT CONTRACT
# =============================================================================

class InvestmentMetrics(BaseModel):
    """Investment analysis metrics."""
    cap_rate: float
    cash_on_cash: float
    gross_yield: float
    payback_years: float
    irr_5yr: Optional[float] = None


class InvestmentScore(BaseModel):
    """Investment scoring output."""
    score: int = Field(..., ge=0, le=100)
    grade: str  # A, B, C, D, F
    metrics: InvestmentMetrics
    strengths: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    recommendation: str
    confidence: float = Field(..., ge=0.0, le=1.0)


# =============================================================================
# NARRATIVE CONTRACT
# =============================================================================

class NarrativeAudience(str, Enum):
    """Target audience for narrative."""
    EXECUTIVE = "executive"
    INVESTOR = "investor"
    OPERATOR = "operator"
    GUEST = "guest"
    SALES = "sales"


class NarrativeBlock(BaseModel):
    """Audience-specific narrative."""
    audience: NarrativeAudience
    headline: str
    body: str
    key_points: List[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


# =============================================================================
# API RESPONSE CONTRACTS (§12)
# =============================================================================

class APIResponse(BaseModel):
    """
    Base API Response Contract.
    
    Endpoints return contracts — never raw math.
    """
    success: bool = True
    version: str = CONTRACT_VERSION
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    gating: Optional[GatingResult] = None


class RentProjectionResponse(APIResponse):
    """POST /bd/rent-projection → RentProjection"""
    data: RentProjection


class AnalyticsResponse(APIResponse):
    """POST /analytics/adr → AnalyticsResult"""
    data: AnalyticsResult


class ConciergeResponseAPI(APIResponse):
    """POST /concierge/respond → ConciergeResponse"""
    data: ConciergeResponse


class DiscountResponse(APIResponse):
    """POST /discount/evaluate → DiscountEvaluation"""
    data: DiscountEvaluation


class ExpansionResponse(APIResponse):
    """GET /expansion/readiness → ExpansionReadiness"""
    data: ExpansionReadiness


class InvestmentResponse(APIResponse):
    """POST /investment/analyze → InvestmentScore"""
    data: InvestmentScore


# =============================================================================
# BD SCENARIO CONTRACTS
# =============================================================================

class BDAudience(str, Enum):
    """Target audience for BD scenario."""
    REALTOR = "realtor"
    OWNER = "owner"
    INVESTOR = "investor"
    INSTITUTIONAL = "institutional"


class BDPurpose(str, Enum):
    """Purpose of BD scenario."""
    ACQUISITION = "acquisition"
    EXPANSION = "expansion"
    PRICING_REVIEW = "pricing_review"
    PORTFOLIO_ANALYSIS = "portfolio_analysis"


class AssetConstraints(BaseModel):
    """
    Asset Constraints Contract.
    
    Pure filtering, no math recomputation.
    """
    min_estimated_value: Optional[int] = None
    max_estimated_value: Optional[int] = None
    min_bedrooms: Optional[int] = None
    max_bedrooms: Optional[int] = None
    property_types: Optional[List[str]] = None
    required_amenities: Optional[List[str]] = None
    min_rent_potential_score: Optional[float] = Field(None, ge=0, le=100)


class ScoringProfile(BaseModel):
    """
    Scoring Profile Contract.
    
    Weights for ranking. NOT overrides.
    Presentation emphasis, not model tampering.
    """
    weight_cashflow: float = Field(default=0.30, ge=0, le=1)
    weight_appreciation: float = Field(default=0.20, ge=0, le=1)
    weight_seasonality_fit: float = Field(default=0.15, ge=0, le=1)
    weight_operator_fit: float = Field(default=0.25, ge=0, le=1)
    weight_risk_adjusted: float = Field(default=0.10, ge=0, le=1)


class BDScenario(BaseModel):
    """
    BD Scenario Contract.
    
    Named, persisted scoping object.
    Operators scope intelligence, not change intelligence.
    """
    scenario_id: UUID = Field(default_factory=uuid4)
    operator_id: UUID
    name: str
    description: Optional[str] = None
    audience: BDAudience = BDAudience.REALTOR
    purpose: BDPurpose = BDPurpose.ACQUISITION
    asset_constraints: AssetConstraints = Field(default_factory=AssetConstraints)
    scoring_profile: ScoringProfile = Field(default_factory=ScoringProfile)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RankedProperty(BaseModel):
    """Ranked property in scenario results."""
    property_id: UUID
    address: str
    rank: int
    composite_score: float
    projected_adr: float
    projected_occupancy: float
    projected_annual_revenue: float
    confidence: float
    score_breakdown: Dict[str, float] = Field(default_factory=dict)


class BDScenarioDisclaimers(BaseModel):
    """
    Disclaimers for scenario results.
    
    TRUST RULE: Every result includes this.
    """
    confidence_level: float
    data_coverage_notes: List[str] = Field(default_factory=list)
    standard_disclaimer: str = Field(
        default=(
            "Analytics are market-derived and unchanged by scenario filters. "
            "This view reflects a scoped subset for evaluation purposes only."
        )
    )


class BDScenarioResult(BaseModel):
    """
    BD Scenario Result Contract.
    
    Shareable, auditable output for:
    - PDF export
    - Realtor presentation
    - Owner review
    """
    scenario_id: UUID
    scenario_name: str
    properties: List[RankedProperty] = Field(default_factory=list)
    total_candidates: int
    median_adr: float
    expected_revenue_range: Tuple[float, float]
    disclaimers: BDScenarioDisclaimers
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class BDScenarioResponse(APIResponse):
    """POST /bd/scenario/execute → BDScenarioResult"""
    data: BDScenarioResult


# =============================================================================
# EXPORT ALL CONTRACTS
# =============================================================================

__all__ = [
    # Version
    "CONTRACT_VERSION",
    
    # Signal
    "SignalType",
    "SignalSource", 
    "Signal",
    "SignalBundle",
    
    # Gating
    "GatingDecision",
    "GatingResult",
    
    # Attribution
    "AttributionDriver",
    
    # Analytics
    "MetricType",
    "AnalyticsResult",
    
    # Property
    "PropertyProfile",
    "AmenityScore",
    
    # Projection
    "MonthlyProjection",
    "SensitivityScenario",
    "SensitivityMatrix",
    "ComparableProperty",
    "RentProjection",
    
    # Operator & Expansion
    "OperatorProfile",
    "ExpansionReadiness",
    
    # Concierge
    "MessageSender",
    "GuestMessage",
    "KnowledgeScope",
    "KnowledgeSource",
    "KnowledgeFact",
    "ConciergeResponse",
    
    # Discount
    "DiscountDecision",
    "DiscountEvaluation",
    
    # BNPL
    "BNPLEligibility",
    
    # Investment
    "InvestmentMetrics",
    "InvestmentScore",
    
    # Narrative
    "NarrativeAudience",
    "NarrativeBlock",
    
    # BD Scenario
    "BDAudience",
    "BDPurpose",
    "AssetConstraints",
    "ScoringProfile",
    "BDScenario",
    "RankedProperty",
    "BDScenarioDisclaimers",
    "BDScenarioResult",
    "BDScenarioResponse",
    
    # API Responses
    "APIResponse",
    "RentProjectionResponse",
    "AnalyticsResponse",
    "ConciergeResponseAPI",
    "DiscountResponse",
    "ExpansionResponse",
    "InvestmentResponse",
]
