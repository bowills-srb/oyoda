"""
Domain: Forecasting - Pure Projections.

No FastAPI. No DB sessions. No external API calls.
Pure inputs → outputs.

All projection math lives here.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4
import hashlib
import json

from ..pricing.computations import (
    AmenityType,
    SeasonalityProfile,
    OperatorDelta,
    compute_combined_amenity_uplift,
    get_default_seasonality,
    apply_operator_delta_conservatively,
    compute_new_listing_penalty,
)


ENGINE_VERSION = "1.1.0"


# =============================================================================
# REASONING OBJECT (Critical for Trust & Auditability)
# =============================================================================

@dataclass
class AppliedUplift:
    """Record of an uplift applied to the projection."""
    name: str
    factor: float  # e.g., 1.10 for +10%
    reason: str
    confidence: float


@dataclass
class CompAnalysis:
    """Analysis of comparable properties used."""
    source: str  # "internal" or "external"
    comp_count: int
    avg_similarity: float
    avg_adr: float
    avg_occupancy: float
    avg_annual_revenue: Optional[float]
    data_coverage_pct: float
    weight_applied: float


@dataclass
class ProjectionReasoning:
    """
    Rich reasoning object that explains HOW we got the numbers.
    
    This feeds:
    - PDFs (assumptions section)
    - Voice agent explanations
    - Internal debugging
    - Audit trails
    - Legal defensibility
    """
    engine_version: str = ENGINE_VERSION
    projection_id: str = field(default_factory=lambda: str(uuid4()))
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    # Input hash for reproducibility
    input_hash: str = ""
    
    # Base ADR derivation
    base_adr: float = 0.0
    base_adr_source: str = ""  # "internal_comps", "external_comps", "blended"
    
    # Comp analysis
    internal_comp_analysis: Optional[CompAnalysis] = None
    external_comp_analysis: Optional[CompAnalysis] = None
    final_comp_weight_internal: float = 0.0  # e.g., 0.6 = 60% internal
    
    # Operator performance delta
    operator_delta: Optional[OperatorDelta] = None
    operator_delta_applied: Tuple[float, float] = (0.0, 0.0)  # (adr, occ)
    
    # All uplifts applied (ordered)
    uplifts_applied: List[AppliedUplift] = field(default_factory=list)
    
    # Seasonality
    seasonality_source: str = ""
    seasonality_profile: Optional[SeasonalityProfile] = None
    peak_months: List[int] = field(default_factory=list)
    
    # Final adjustments
    new_listing_adjustment: Optional[float] = None
    
    # Confidence breakdown
    confidence_factors: Dict[str, float] = field(default_factory=dict)
    overall_confidence: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "engine_version": self.engine_version,
            "projection_id": self.projection_id,
            "generated_at": self.generated_at.isoformat(),
            "input_hash": self.input_hash,
            "base_adr": self.base_adr,
            "base_adr_source": self.base_adr_source,
            "final_comp_weight_internal": self.final_comp_weight_internal,
            "uplifts_applied": [
                {"name": u.name, "factor": u.factor, "reason": u.reason, "confidence": u.confidence}
                for u in self.uplifts_applied
            ],
            "seasonality_source": self.seasonality_source,
            "peak_months": self.peak_months,
            "new_listing_adjustment": self.new_listing_adjustment,
            "confidence_factors": self.confidence_factors,
            "overall_confidence": self.overall_confidence,
        }


# =============================================================================
# INPUT MODELS
# =============================================================================

@dataclass
class PropertyInputs:
    """Property inputs for projection."""
    bedrooms: int
    bathrooms: float
    property_type: str = "single_family"
    sqft: Optional[int] = None
    
    # Amenities
    amenities: List[AmenityType] = field(default_factory=list)
    
    # Status
    is_new_listing: bool = False
    months_active: int = 12


@dataclass
class MarketInputs:
    """Market-level inputs."""
    market_id: UUID
    market_name: str = ""
    market_type: str = "coastal"  # "coastal", "urban", "mountain", etc.
    
    # Median rates by bedroom count
    median_adr_by_bedroom: Dict[int, float] = field(default_factory=dict)
    median_occupancy_by_bedroom: Dict[int, float] = field(default_factory=dict)
    
    # Amenity expectations
    pool_is_expected: bool = False
    amenity_uplifts: Optional[Dict[AmenityType, float]] = None
    
    # Seasonality
    seasonality_profile: Optional[SeasonalityProfile] = None


@dataclass
class CompSet:
    """Comparable property set."""
    source: str  # "internal" or "external"
    comp_count: int
    avg_adr: float
    avg_occupancy: float
    avg_similarity_score: float
    data_coverage_pct: float
    months_of_data: int = 12
    avg_annual_revenue: Optional[float] = None


@dataclass
class OperatorInputs:
    """Operator-specific inputs."""
    company_id: UUID
    
    # Portfolio performance
    portfolio_avg_adr: float
    portfolio_avg_occupancy: float
    market_avg_adr: float
    market_avg_occupancy: float
    
    # Data depth
    property_count: int
    months_of_data: int


# =============================================================================
# OUTPUT MODELS
# =============================================================================

@dataclass
class MonthlyProjection:
    """Single month projection."""
    month: int  # 1-12
    projected_occupancy: float
    avg_nightly_rate: float
    projected_revenue: float
    confidence: float


@dataclass
class AnnualProjection:
    """Complete annual projection."""
    property_summary: str
    comp_summary: str
    
    # Annual totals
    projected_annual_revenue: float
    projected_net_to_owner: float
    commission_rate: float
    
    # Averages
    avg_adr: float
    avg_occupancy: float
    
    # Monthly breakdown
    monthly_projections: List[MonthlyProjection]
    
    # Confidence
    confidence: float
    
    # Key assumptions (human-readable)
    key_assumptions: List[str]
    
    # Full reasoning
    reasoning: ProjectionReasoning


# =============================================================================
# PROJECTION ENGINE
# =============================================================================

def compute_base_adr(
    property_inputs: PropertyInputs,
    market_inputs: MarketInputs,
    internal_comps: Optional[CompSet],
    external_comps: Optional[CompSet],
    reasoning: ProjectionReasoning,
) -> float:
    """
    Compute base ADR from comp sets.
    
    Blends internal (operator) and external (market) data.
    """
    has_internal = internal_comps and internal_comps.comp_count >= 3
    has_external = external_comps and external_comps.comp_count >= 3
    
    if has_internal and has_external:
        # Blend based on data quality
        internal_weight = min(
            internal_comps.comp_count / 10,
            internal_comps.data_coverage_pct,
            internal_comps.avg_similarity_score,
        )
        external_weight = min(
            external_comps.comp_count / 15,
            external_comps.data_coverage_pct,
        ) * 0.7  # Discount external slightly
        
        total_weight = internal_weight + external_weight
        int_pct = internal_weight / total_weight if total_weight > 0 else 0.5
        
        base = (internal_comps.avg_adr * int_pct) + (external_comps.avg_adr * (1 - int_pct))
        
        reasoning.base_adr_source = "blended"
        reasoning.final_comp_weight_internal = int_pct
        reasoning.internal_comp_analysis = CompAnalysis(
            source="internal",
            comp_count=internal_comps.comp_count,
            avg_similarity=internal_comps.avg_similarity_score,
            avg_adr=internal_comps.avg_adr,
            avg_occupancy=internal_comps.avg_occupancy,
            avg_annual_revenue=internal_comps.avg_annual_revenue,
            data_coverage_pct=internal_comps.data_coverage_pct,
            weight_applied=int_pct,
        )
        reasoning.external_comp_analysis = CompAnalysis(
            source="external",
            comp_count=external_comps.comp_count,
            avg_similarity=external_comps.avg_similarity_score,
            avg_adr=external_comps.avg_adr,
            avg_occupancy=external_comps.avg_occupancy,
            avg_annual_revenue=external_comps.avg_annual_revenue,
            data_coverage_pct=external_comps.data_coverage_pct,
            weight_applied=1 - int_pct,
        )
        
    elif has_internal:
        base = internal_comps.avg_adr
        reasoning.base_adr_source = "internal_comps"
        reasoning.final_comp_weight_internal = 1.0
        
    elif has_external:
        base = external_comps.avg_adr
        reasoning.base_adr_source = "external_comps"
        reasoning.final_comp_weight_internal = 0.0
        
    else:
        # Fallback to market medians
        base = market_inputs.median_adr_by_bedroom.get(property_inputs.bedrooms, 500)
        reasoning.base_adr_source = "market_median"
        reasoning.final_comp_weight_internal = 0.0
    
    reasoning.base_adr = base
    return base


def apply_amenity_uplifts(
    base_adr: float,
    property_inputs: PropertyInputs,
    market_inputs: MarketInputs,
    reasoning: ProjectionReasoning,
) -> float:
    """Apply amenity uplifts to base ADR."""
    if not property_inputs.amenities:
        return base_adr
    
    combined_uplift, confidence, uplifts = compute_combined_amenity_uplift(
        property_inputs.amenities,
        market_inputs.amenity_uplifts,
    )
    
    for uplift in uplifts:
        reasoning.uplifts_applied.append(AppliedUplift(
            name=uplift.amenity_type.value,
            factor=uplift.base_uplift,
            reason=f"{uplift.amenity_type.value.replace('_', ' ').title()} premium",
            confidence=uplift.confidence,
        ))
    
    return base_adr * combined_uplift


def apply_operator_delta(
    adr: float,
    base_occupancy: float,
    operator_inputs: Optional[OperatorInputs],
    reasoning: ProjectionReasoning,
) -> Tuple[float, float]:
    """Apply operator performance delta."""
    if not operator_inputs:
        return adr, base_occupancy
    
    from ..pricing.computations import compute_operator_delta
    
    delta = compute_operator_delta(
        portfolio_avg_adr=operator_inputs.portfolio_avg_adr,
        market_avg_adr=operator_inputs.market_avg_adr,
        portfolio_avg_occupancy=operator_inputs.portfolio_avg_occupancy,
        market_avg_occupancy=operator_inputs.market_avg_occupancy,
        months_of_data=operator_inputs.months_of_data,
        property_count=operator_inputs.property_count,
    )
    
    adr_apply, occ_apply = apply_operator_delta_conservatively(delta)
    
    reasoning.operator_delta = delta
    reasoning.operator_delta_applied = (adr_apply, occ_apply)
    reasoning.uplifts_applied.append(AppliedUplift(
        name="operator_performance",
        factor=1.0 + adr_apply,
        reason=f"Operator performance delta (+{delta.adr_delta_pct:.1%} observed, {adr_apply:.1%} applied)",
        confidence=delta.confidence,
    ))
    
    return adr * (1 + adr_apply), base_occupancy * (1 + occ_apply)


def generate_monthly_projections(
    avg_adr: float,
    avg_occupancy: float,
    seasonality: SeasonalityProfile,
    property_inputs: PropertyInputs,
    reasoning: ProjectionReasoning,
) -> List[MonthlyProjection]:
    """Generate monthly projections with seasonality."""
    projections = []
    
    # New listing penalty
    new_listing_mult = 1.0
    if property_inputs.is_new_listing:
        new_listing_mult = compute_new_listing_penalty(property_inputs.months_active)
        reasoning.new_listing_adjustment = new_listing_mult
    
    for month in range(1, 13):
        seasonal_mult = seasonality.get_multiplier(month)
        
        monthly_rate = avg_adr * seasonal_mult
        monthly_occ = min(avg_occupancy * seasonal_mult * new_listing_mult, 0.95)
        
        # Days in month (simplified)
        days = 30 if month in [4, 6, 9, 11] else (28 if month == 2 else 31)
        booked_nights = days * monthly_occ
        revenue = booked_nights * monthly_rate
        
        # Confidence decays for months further out
        month_confidence = reasoning.overall_confidence * (1 - (month - 1) * 0.02)
        
        projections.append(MonthlyProjection(
            month=month,
            projected_occupancy=round(monthly_occ, 3),
            avg_nightly_rate=round(monthly_rate, 0),
            projected_revenue=round(revenue, 0),
            confidence=round(month_confidence, 3),
        ))
    
    return projections


def compute_confidence(
    property_inputs: PropertyInputs,
    internal_comps: Optional[CompSet],
    external_comps: Optional[CompSet],
    operator_inputs: Optional[OperatorInputs],
    reasoning: ProjectionReasoning,
) -> float:
    """Compute overall projection confidence."""
    score = 0.40  # Base
    
    # Internal comp contribution
    if internal_comps and internal_comps.comp_count >= 3:
        contrib = min(internal_comps.comp_count / 10, 1.0) * 0.15
        contrib += internal_comps.data_coverage_pct * 0.10
        score += contrib
        reasoning.confidence_factors["internal_comps"] = contrib
    
    # External comp contribution
    if external_comps and external_comps.comp_count >= 3:
        contrib = min(external_comps.comp_count / 15, 1.0) * 0.10
        contrib += external_comps.data_coverage_pct * 0.05
        score += contrib
        reasoning.confidence_factors["external_comps"] = contrib
    
    # Operator delta contribution
    if operator_inputs:
        delta_contrib = 0.15 * min(operator_inputs.months_of_data / 24, 1.0)
        score += delta_contrib
        reasoning.confidence_factors["operator_data"] = delta_contrib
    
    return min(score, 1.0)


def generate_projection(
    property_inputs: PropertyInputs,
    market_inputs: MarketInputs,
    internal_comps: Optional[CompSet] = None,
    external_comps: Optional[CompSet] = None,
    operator_inputs: Optional[OperatorInputs] = None,
    commission_rate: float = 0.20,
) -> AnnualProjection:
    """
    Generate complete annual projection.
    
    This is the main entry point for projections.
    Pure function - all inputs provided, output returned.
    """
    reasoning = ProjectionReasoning()
    
    # 1. Compute base ADR
    base_adr = compute_base_adr(
        property_inputs, market_inputs, internal_comps, external_comps, reasoning
    )
    
    # 2. Apply amenity uplifts
    adjusted_adr = apply_amenity_uplifts(
        base_adr, property_inputs, market_inputs, reasoning
    )
    
    # 3. Get base occupancy
    base_occupancy = market_inputs.median_occupancy_by_bedroom.get(
        property_inputs.bedrooms, 0.50
    )
    
    # 4. Apply operator delta
    final_adr, final_occupancy = apply_operator_delta(
        adjusted_adr, base_occupancy, operator_inputs, reasoning
    )
    
    # 5. Compute confidence
    reasoning.overall_confidence = compute_confidence(
        property_inputs, internal_comps, external_comps, operator_inputs, reasoning
    )
    
    # 6. Get seasonality
    seasonality = market_inputs.seasonality_profile or get_default_seasonality(market_inputs.market_type)
    reasoning.seasonality_source = seasonality.source
    reasoning.seasonality_profile = seasonality
    reasoning.peak_months = seasonality.peak_months
    
    # 7. Generate monthly projections
    monthly = generate_monthly_projections(
        final_adr, final_occupancy, seasonality, property_inputs, reasoning
    )
    
    # 8. Compute totals
    total_revenue = sum(m.projected_revenue for m in monthly)
    net_to_owner = total_revenue * (1 - commission_rate)
    avg_occ = sum(m.projected_occupancy for m in monthly) / 12
    
    # 9. Build summaries
    property_summary = _build_property_summary(property_inputs)
    comp_summary = _build_comp_summary(reasoning)
    key_assumptions = _build_key_assumptions(reasoning)
    
    return AnnualProjection(
        property_summary=property_summary,
        comp_summary=comp_summary,
        projected_annual_revenue=round(total_revenue, 0),
        projected_net_to_owner=round(net_to_owner, 0),
        commission_rate=commission_rate,
        avg_adr=round(final_adr, 0),
        avg_occupancy=round(avg_occ, 3),
        monthly_projections=monthly,
        confidence=reasoning.overall_confidence,
        key_assumptions=key_assumptions,
        reasoning=reasoning,
    )


def _build_property_summary(inputs: PropertyInputs) -> str:
    """Build human-readable property summary."""
    bath_str = f"{inputs.bathrooms:.1f}".rstrip('0').rstrip('.')
    parts = [f"{inputs.bedrooms}BR/{bath_str}BA"]
    parts.append(inputs.property_type.replace("_", " ").title())
    
    if inputs.amenities:
        amenity_names = [a.value.replace("_", " ").title() for a in inputs.amenities[:3]]
        parts.append("with " + ", ".join(amenity_names))
    
    return " ".join(parts)


def _build_comp_summary(reasoning: ProjectionReasoning) -> str:
    """Build comp summary string."""
    parts = []
    
    if reasoning.internal_comp_analysis:
        parts.append(f"{reasoning.internal_comp_analysis.comp_count} properties from operator portfolio")
    
    if reasoning.external_comp_analysis:
        parts.append(f"{reasoning.external_comp_analysis.comp_count} market comparables")
    
    if not parts:
        return "Based on market median estimates"
    
    return "Based on " + " and ".join(parts)


def _build_key_assumptions(reasoning: ProjectionReasoning) -> List[str]:
    """Build human-readable list of key assumptions."""
    assumptions = []
    
    # Base ADR source
    if reasoning.base_adr_source == "blended":
        assumptions.append(
            f"Base rate from blended internal ({reasoning.final_comp_weight_internal:.0%}) "
            f"and external ({1-reasoning.final_comp_weight_internal:.0%}) comps"
        )
    elif reasoning.base_adr_source == "internal_comps":
        assumptions.append("Base rate from operator's portfolio comparables")
    elif reasoning.base_adr_source == "external_comps":
        assumptions.append("Base rate from market comparables")
    else:
        assumptions.append("Base rate from market median (limited comp data)")
    
    # Operator delta
    if reasoning.operator_delta:
        delta = reasoning.operator_delta
        adr_applied, _ = reasoning.operator_delta_applied
        assumptions.append(
            f"Operator performance adjustment: +{adr_applied:.1%} ADR "
            f"(based on {delta.months_of_data} months of data from {delta.property_count} properties)"
        )
    
    # Uplifts
    for uplift in reasoning.uplifts_applied:
        if "operator" not in uplift.name.lower():  # Already covered
            pct = (uplift.factor - 1) * 100
            sign = "+" if pct >= 0 else ""
            assumptions.append(f"{uplift.reason}: {sign}{pct:.0f}% to rate")
    
    # New listing
    if reasoning.new_listing_adjustment:
        assumptions.append(
            f"New listing adjustment: {(1-reasoning.new_listing_adjustment):.0%} occupancy reduction initially"
        )
    
    return assumptions


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Reasoning
    "AppliedUplift",
    "CompAnalysis",
    "ProjectionReasoning",
    
    # Inputs
    "PropertyInputs",
    "MarketInputs",
    "CompSet",
    "OperatorInputs",
    
    # Outputs
    "MonthlyProjection",
    "AnnualProjection",
    
    # Engine
    "generate_projection",
    "ENGINE_VERSION",
]
