"""
Domain: Opportunity - Production-Grade Models.

HomeownerOpportunityScore and AssumptionProfile for BD targeting.
No FastAPI. No DB sessions. No external API calls.

This is the backbone of BD:
- HomeownerOpportunityScore: The atomic BD targeting unit
- AssumptionProfile: The honesty engine for incomplete data
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Tuple
from uuid import UUID


# =============================================================================
# ENUMS
# =============================================================================

class OpportunityType(str, Enum):
    """Type of opportunity for this owner-property pair."""
    STR_CONVERSION = "str_conversion"      # Convert to short-term rental
    MTR_CONVERSION = "mtr_conversion"      # Convert to mid-term rental
    OPTIMIZATION = "optimization"          # Already renting, can do better
    HYBRID = "hybrid"                      # Mix of rental strategies


class FurnishingLevel(str, Enum):
    """Assumed furnishing quality."""
    UNKNOWN = "unknown"
    BASIC = "basic"
    AVERAGE = "average"
    PREMIUM = "premium"


class FinishQuality(str, Enum):
    """Inferred property finish quality."""
    INFERRED_LOW = "inferred_low"
    INFERRED_AVG = "inferred_avg"
    INFERRED_HIGH = "inferred_high"
    KNOWN = "known"


class ManagementStyle(str, Enum):
    """Property management approach."""
    SELF_MANAGED = "self_managed"
    PROFESSIONAL = "professional"


class UsageModel(str, Enum):
    """Rental usage model."""
    STR = "str"      # Short-term rental
    MTR = "mtr"      # Mid-term rental (30+ days)
    LTR = "ltr"      # Long-term rental


class OccupancyBias(str, Enum):
    """Occupancy assumption bias."""
    CONSERVATIVE = "conservative"
    MARKET_AVERAGE = "market_average"
    AGGRESSIVE = "aggressive"


class ComplianceAssumption(str, Enum):
    """STR compliance/zoning assumption."""
    UNKNOWN = "unknown"
    LIKELY_ALLOWED = "likely_allowed"
    LIKELY_RESTRICTED = "likely_restricted"
    KNOWN_ALLOWED = "known_allowed"
    KNOWN_RESTRICTED = "known_restricted"


class OwnerType(str, Enum):
    """Type of property owner."""
    INDIVIDUAL = "individual"
    LLC = "llc"
    TRUST = "trust"
    CORPORATION = "corporation"
    UNKNOWN = "unknown"


# =============================================================================
# ASSUMPTION PROFILE (The Honesty Engine)
# =============================================================================

@dataclass
class AssumptionProfile:
    """
    Named bundle of explicit assumptions for incomplete data.
    
    This turns "we guessed" into:
    "We assumed X, Y, and Z — here's what that implies."
    
    Every inference adds a confidence penalty.
    No silent assumptions.
    """
    name: str
    
    # Property assumptions
    furnishing_level: FurnishingLevel = FurnishingLevel.AVERAGE
    finish_quality: FinishQuality = FinishQuality.INFERRED_AVG
    
    # Management assumptions
    management_style: ManagementStyle = ManagementStyle.PROFESSIONAL
    
    # Usage assumptions
    usage_model: UsageModel = UsageModel.STR
    
    # Revenue assumptions
    occupancy_bias: OccupancyBias = OccupancyBias.MARKET_AVERAGE
    
    # Compliance assumptions
    compliance_assumption: ComplianceAssumption = ComplianceAssumption.UNKNOWN
    
    # Confidence impact (0-1, subtracted from base confidence)
    confidence_penalty: float = 0.0
    
    @classmethod
    def conservative(cls) -> "AssumptionProfile":
        """
        Conservative assumptions - floor estimate.
        Use when you want to under-promise.
        """
        return cls(
            name="conservative",
            furnishing_level=FurnishingLevel.BASIC,
            finish_quality=FinishQuality.INFERRED_LOW,
            management_style=ManagementStyle.SELF_MANAGED,
            usage_model=UsageModel.STR,
            occupancy_bias=OccupancyBias.CONSERVATIVE,
            compliance_assumption=ComplianceAssumption.UNKNOWN,
            confidence_penalty=0.05,
        )
    
    @classmethod
    def typical(cls) -> "AssumptionProfile":
        """
        Typical assumptions - expected estimate.
        Use for base case projections.
        """
        return cls(
            name="typical",
            furnishing_level=FurnishingLevel.AVERAGE,
            finish_quality=FinishQuality.INFERRED_AVG,
            management_style=ManagementStyle.PROFESSIONAL,
            usage_model=UsageModel.STR,
            occupancy_bias=OccupancyBias.MARKET_AVERAGE,
            compliance_assumption=ComplianceAssumption.UNKNOWN,
            confidence_penalty=0.10,
        )
    
    @classmethod
    def upside(cls) -> "AssumptionProfile":
        """
        Upside assumptions - ceiling estimate.
        Use when showing potential.
        """
        return cls(
            name="upside",
            furnishing_level=FurnishingLevel.PREMIUM,
            finish_quality=FinishQuality.INFERRED_HIGH,
            management_style=ManagementStyle.PROFESSIONAL,
            usage_model=UsageModel.STR,
            occupancy_bias=OccupancyBias.AGGRESSIVE,
            compliance_assumption=ComplianceAssumption.LIKELY_ALLOWED,
            confidence_penalty=0.15,
        )
    
    def to_assumptions_list(self) -> List[str]:
        """Convert to human-readable assumptions list."""
        assumptions = []
        
        if self.furnishing_level != FurnishingLevel.UNKNOWN:
            assumptions.append(f"{self.furnishing_level.value.title()} furnishing level")
        
        if self.finish_quality.value.startswith("inferred"):
            assumptions.append(f"Property quality inferred as {self.finish_quality.value.replace('inferred_', '')}")
        
        assumptions.append(f"{self.management_style.value.replace('_', ' ').title()} management")
        assumptions.append(f"{self.usage_model.value.upper()} rental model")
        
        if self.occupancy_bias == OccupancyBias.CONSERVATIVE:
            assumptions.append("Conservative occupancy estimates")
        elif self.occupancy_bias == OccupancyBias.AGGRESSIVE:
            assumptions.append("Optimistic occupancy estimates")
        
        return assumptions


# =============================================================================
# PROJECTION COMPONENT (within HOS)
# =============================================================================

@dataclass
class OpportunityProjection:
    """
    Projection component of HomeownerOpportunityScore.
    
    Always a range, never a single number.
    """
    conservative_annual: float
    expected_annual: float
    upside_annual: float
    
    # Confidence (0-1)
    confidence: float
    
    # Basis
    comparable_count: int
    assumptions_used: List[str] = field(default_factory=list)
    
    @property
    def range_formatted(self) -> str:
        """Format as range string."""
        return f"${self.conservative_annual:,.0f} - ${self.upside_annual:,.0f}"
    
    @property
    def spread_pct(self) -> float:
        """Calculate spread as percentage of expected."""
        if self.expected_annual == 0:
            return 0
        return (self.upside_annual - self.conservative_annual) / self.expected_annual


@dataclass
class UnrealizedValue:
    """Unrealized rental value for this property."""
    absolute: float  # Dollar amount
    percentile_vs_market: float  # 0-100, where does this rank


# =============================================================================
# SIGNAL COMPONENTS (within HOS)
# =============================================================================

@dataclass
class OwnerSignals:
    """Owner-related signals for opportunity scoring."""
    owner_type: OwnerType = OwnerType.UNKNOWN
    absentee_owner: bool = False
    portfolio_size: int = 1
    tenure_years: Optional[float] = None


@dataclass
class PropertySignals:
    """Property-related signals for opportunity scoring."""
    beds: int = 0
    baths: float = 0.0
    sqft: Optional[int] = None
    inferred_quality: FinishQuality = FinishQuality.INFERRED_AVG
    zoning_risk: ComplianceAssumption = ComplianceAssumption.UNKNOWN


@dataclass
class Contactability:
    """Contact information quality."""
    has_email: bool = False
    has_phone: bool = False
    do_not_contact: bool = False
    confidence: float = 0.0
    
    @property
    def is_contactable(self) -> bool:
        """Check if owner can be contacted."""
        return (self.has_email or self.has_phone) and not self.do_not_contact


@dataclass
class Explainability:
    """
    Explainability component for transparency.
    
    Every HOS must explain itself.
    """
    top_drivers: List[str] = field(default_factory=list)
    key_assumptions: List[str] = field(default_factory=list)
    data_gaps: List[str] = field(default_factory=list)


# =============================================================================
# HOMEOWNER OPPORTUNITY SCORE (The Atomic BD Targeting Unit)
# =============================================================================

@dataclass
class HomeownerOpportunityScore:
    """
    The atomic BD targeting unit.
    
    Everything downstream (email, voice, sales queues) consumes this.
    
    This represents:
    - A screening score (not a guarantee)
    - A prioritization signal (not a recommendation)
    - A projection envelope (not a valuation)
    
    This is the contract between intelligence and BD.
    BD never touches raw signals or domain internals.
    """
    # Identity
    owner_id: UUID
    property_id: UUID
    market_id: str
    
    # Opportunity type
    opportunity_type: OpportunityType = OpportunityType.STR_CONVERSION
    
    # Projection (always a range)
    projection: OpportunityProjection = None
    
    # Unrealized value
    unrealized_value: UnrealizedValue = None
    
    # Signals
    owner_signals: OwnerSignals = field(default_factory=OwnerSignals)
    property_signals: PropertySignals = field(default_factory=PropertySignals)
    
    # Contactability
    contactability: Contactability = field(default_factory=Contactability)
    
    # Overall score (0-100)
    overall_score: float = 0.0
    
    # Explainability (REQUIRED)
    explainability: Explainability = field(default_factory=Explainability)
    
    # Metadata
    generated_at: datetime = field(default_factory=datetime.utcnow)
    
    @property
    def is_high_value(self) -> bool:
        """Check if this is a high-value opportunity."""
        return (
            self.overall_score >= 70 and
            self.contactability.is_contactable
        )
    
    @property
    def priority_tier(self) -> str:
        """Get priority tier for BD."""
        if self.overall_score >= 70:
            return "high"
        elif self.overall_score >= 40:
            return "medium"
        else:
            return "low"


# =============================================================================
# SCORING FUNCTIONS (Pure)
# =============================================================================

def compute_overall_score(
    unrealized_value: float,
    projection_confidence: float,
    contactability_confidence: float,
    compliance_modifier: float,
) -> float:
    """
    Compute overall opportunity score.
    
    Pure function - no IO.
    
    Formula:
        overall_score = unrealized_value_weighted
                       × projection_confidence
                       × contactability_confidence
                       × compliance_modifier
    
    This avoids:
    - Chasing huge but illegal opportunities
    - Wasting time on unreachable owners
    """
    # Value component (0-50 points)
    # $50k+ = max points, scales from there
    value_score = min(50, (unrealized_value / 50000) * 50)
    
    # Confidence component (0-30 points)
    confidence_score = projection_confidence * 30
    
    # Contactability component (0-15 points)
    contact_score = contactability_confidence * 15
    
    # Compliance modifier (0.5-1.0)
    # Reduces score for risky/restricted areas
    
    raw_score = (value_score + confidence_score + contact_score) * compliance_modifier
    
    return max(0, min(100, raw_score))


def get_compliance_modifier(compliance: ComplianceAssumption) -> float:
    """
    Get compliance modifier for scoring.
    
    Pure function - no IO.
    """
    return {
        ComplianceAssumption.KNOWN_ALLOWED: 1.0,
        ComplianceAssumption.LIKELY_ALLOWED: 0.95,
        ComplianceAssumption.UNKNOWN: 0.85,
        ComplianceAssumption.LIKELY_RESTRICTED: 0.60,
        ComplianceAssumption.KNOWN_RESTRICTED: 0.30,
    }.get(compliance, 0.85)


def infer_assumptions_from_signals(
    owner_signals: OwnerSignals,
    property_signals: PropertySignals,
    has_hoa_docs: bool = False,
    nearby_listings_quality: Optional[str] = None,
) -> Tuple[AssumptionProfile, List[str]]:
    """
    Infer assumption profile from available signals.
    
    Pure function - no IO.
    
    Returns:
        Tuple of (inferred profile, data gaps list)
    """
    data_gaps = []
    
    # Start with typical
    profile = AssumptionProfile.typical()
    
    # Infer compliance from HOA docs
    if has_hoa_docs:
        profile.compliance_assumption = ComplianceAssumption.KNOWN_ALLOWED
    else:
        data_gaps.append("No HOA documentation - compliance unknown")
    
    # Infer quality from nearby listings
    if nearby_listings_quality == "premium":
        profile.finish_quality = FinishQuality.INFERRED_HIGH
    elif nearby_listings_quality == "budget":
        profile.finish_quality = FinishQuality.INFERRED_LOW
    else:
        data_gaps.append("Property quality inferred from market average")
    
    # Infer management from owner type
    if owner_signals.absentee_owner and owner_signals.owner_type == OwnerType.LLC:
        profile.management_style = ManagementStyle.PROFESSIONAL
    elif owner_signals.portfolio_size > 3:
        profile.management_style = ManagementStyle.PROFESSIONAL
    else:
        data_gaps.append("Management style assumed")
    
    # No furnishing data
    data_gaps.append("Furnishing level assumed as average")
    
    # Adjust confidence penalty based on data gaps
    profile.confidence_penalty = min(0.30, len(data_gaps) * 0.05)
    
    return profile, data_gaps


def generate_three_scenario_projections(
    base_revenue: float,
    base_confidence: float,
    comparable_count: int,
) -> Tuple[OpportunityProjection, OpportunityProjection, OpportunityProjection]:
    """
    Generate conservative/typical/upside projections.
    
    Pure function - no IO.
    
    Returns:
        Tuple of (conservative, typical, upside) projections
    """
    conservative = OpportunityProjection(
        conservative_annual=base_revenue * 0.75,
        expected_annual=base_revenue * 0.85,
        upside_annual=base_revenue * 0.95,
        confidence=min(1.0, base_confidence + 0.10),  # Higher confidence for conservative
        comparable_count=comparable_count,
        assumptions_used=AssumptionProfile.conservative().to_assumptions_list(),
    )
    
    typical = OpportunityProjection(
        conservative_annual=base_revenue * 0.85,
        expected_annual=base_revenue,
        upside_annual=base_revenue * 1.15,
        confidence=base_confidence,
        comparable_count=comparable_count,
        assumptions_used=AssumptionProfile.typical().to_assumptions_list(),
    )
    
    upside = OpportunityProjection(
        conservative_annual=base_revenue * 0.95,
        expected_annual=base_revenue * 1.15,
        upside_annual=base_revenue * 1.35,
        confidence=max(0.0, base_confidence - 0.15),  # Lower confidence for upside
        comparable_count=comparable_count,
        assumptions_used=AssumptionProfile.upside().to_assumptions_list(),
    )
    
    return conservative, typical, upside


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Enums
    "OpportunityType",
    "FurnishingLevel",
    "FinishQuality",
    "ManagementStyle",
    "UsageModel",
    "OccupancyBias",
    "ComplianceAssumption",
    "OwnerType",
    
    # Core models
    "AssumptionProfile",
    "OpportunityProjection",
    "UnrealizedValue",
    "OwnerSignals",
    "PropertySignals",
    "Contactability",
    "Explainability",
    "HomeownerOpportunityScore",
    
    # Functions
    "compute_overall_score",
    "get_compliance_modifier",
    "infer_assumptions_from_signals",
    "generate_three_scenario_projections",
]
