"""
Rent Projection Engine v1.1 - With Operator-Specific Intelligence.

ENHANCEMENTS OVER v1.0:
1. Two-layer comp system: Internal (operator portfolio) + External (market)
2. Operator performance delta calculation
3. Conservative uplift application (40-60% of observed delta)
4. Rich reasoning object for PDFs and voice agents
5. Pure & deterministic (no DB/HTTP calls - input → output only)

This is NOT "AirDNA-lite" - this is institutional-grade BD intelligence.

The math is EXPLAINABLE and DEFENSIBLE:
- Base ADR from weighted comp set (internal + external)
- Operator performance multiplier (conservative application)
- Amenity uplift (multiplicative, not additive)
- Seasonality curves with confidence bands
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4
import hashlib
import json

from pydantic import BaseModel, Field


# =============================================================================
# ENGINE VERSION
# =============================================================================

ENGINE_VERSION = "1.1.0"


# =============================================================================
# REASONING OBJECT (Critical for Trust & Auditability)
# =============================================================================

class CompSource(str, Enum):
    """Source of comparable data."""
    INTERNAL = "internal"  # Operator's own portfolio
    EXTERNAL = "external"  # Market data


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
    source: CompSource
    comp_count: int
    avg_similarity: float
    avg_adr: float
    avg_occupancy: float
    avg_annual_revenue: Optional[float]
    data_coverage_pct: float
    weight_applied: float  # How much this source influenced final


@dataclass
class OperatorPerformanceDelta:
    """
    Operator's historical performance vs market.
    
    This is the key differentiator for operator-specific projections.
    """
    adr_delta_pct: float  # e.g., 0.12 = +12% vs market
    occupancy_delta_pct: float  # e.g., 0.07 = +7% vs market
    
    # How much we apply (conservative)
    adr_delta_applied: float  # After tapering (40-60% of observed)
    occupancy_delta_applied: float
    
    # Confidence factors
    months_of_data: int
    property_count: int
    confidence: float
    
    # Reasoning
    reason: str


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
    # Engine metadata
    engine_version: str = ENGINE_VERSION
    projection_id: str = field(default_factory=lambda: str(uuid4()))
    generated_at: datetime = field(default_factory=datetime.utcnow)
    
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
    operator_delta: Optional[OperatorPerformanceDelta] = None
    
    # All uplifts applied (ordered)
    uplifts_applied: List[AppliedUplift] = field(default_factory=list)
    
    # Seasonality
    seasonality_source: str = ""  # "market_default", "operator_historical"
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
            "internal_comp_analysis": self._comp_to_dict(self.internal_comp_analysis),
            "external_comp_analysis": self._comp_to_dict(self.external_comp_analysis),
            "final_comp_weight_internal": self.final_comp_weight_internal,
            "operator_delta": self._delta_to_dict(self.operator_delta),
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
    
    def _comp_to_dict(self, comp: Optional[CompAnalysis]) -> Optional[Dict]:
        if not comp:
            return None
        return {
            "source": comp.source.value,
            "comp_count": comp.comp_count,
            "avg_similarity": comp.avg_similarity,
            "avg_adr": comp.avg_adr,
            "avg_occupancy": comp.avg_occupancy,
            "avg_annual_revenue": comp.avg_annual_revenue,
            "data_coverage_pct": comp.data_coverage_pct,
            "weight_applied": comp.weight_applied,
        }
    
    def _delta_to_dict(self, delta: Optional[OperatorPerformanceDelta]) -> Optional[Dict]:
        if not delta:
            return None
        return {
            "adr_delta_pct": delta.adr_delta_pct,
            "occupancy_delta_pct": delta.occupancy_delta_pct,
            "adr_delta_applied": delta.adr_delta_applied,
            "occupancy_delta_applied": delta.occupancy_delta_applied,
            "months_of_data": delta.months_of_data,
            "property_count": delta.property_count,
            "confidence": delta.confidence,
            "reason": delta.reason,
        }


# =============================================================================
# INPUT MODELS
# =============================================================================

class PropertyInputs(BaseModel):
    """Property inputs for projection."""
    bedrooms: int
    bathrooms: float
    sqft: Optional[int] = None
    property_type: str = "single_family"
    
    # Amenities that matter
    waterfront: bool = False
    pool: bool = False
    pool_heated: bool = False
    hot_tub: bool = False
    view: Optional[str] = None  # gulf, ocean, bay, lake
    beach_access: Optional[str] = None  # private, public
    dock: bool = False
    elevator: bool = False
    game_room: bool = False
    home_theater: bool = False
    pet_friendly: bool = False
    
    # Status
    is_new_listing: bool = False
    months_active: int = Field(12, ge=0)


class InternalCompSet(BaseModel):
    """
    Comparable properties from operator's own portfolio.
    
    This is the PRIMARY signal for BD projections.
    """
    company_id: UUID
    
    # Comp properties
    comp_property_ids: List[UUID] = Field(default_factory=list)
    comp_count: int = 0
    
    # Aggregate performance (from normalized booking data)
    avg_adr: float = 0.0
    avg_occupancy: float = 0.0
    avg_annual_revenue: Optional[float] = None
    
    # Quality metrics
    avg_similarity_score: float = 0.0
    data_coverage_pct: float = 0.0  # % with sufficient data
    months_of_data: int = 0  # Minimum across comps


class ExternalCompSet(BaseModel):
    """
    Comparable properties from market data (external).
    
    This is the ANCHOR that prevents internal bias.
    """
    market_id: UUID
    
    # Comp properties
    comp_count: int = 0
    
    # Aggregate performance
    avg_adr: float = 0.0
    avg_occupancy: float = 0.0
    avg_annual_revenue: Optional[float] = None
    
    # Quality metrics
    avg_similarity_score: float = 0.0
    data_coverage_pct: float = 0.0


class OperatorPortfolio(BaseModel):
    """
    Operator's overall portfolio performance vs market.
    
    Used to calculate the performance delta.
    """
    company_id: UUID
    
    # Portfolio vs market performance
    portfolio_avg_adr: float
    market_avg_adr: float
    
    portfolio_avg_occupancy: float
    market_avg_occupancy: float
    
    # RevPAR (Revenue Per Available Room) = ADR × Occupancy
    portfolio_revpar: Optional[float] = None  # Computed if not provided
    market_revpar: Optional[float] = None
    
    # Discount sensitivity (0-1, higher = more sensitive to discounts)
    # Based on historical booking patterns: how much do discounts increase bookings?
    discount_sensitivity: float = 0.5
    
    # Data quality
    property_count: int
    months_of_data: int
    
    # Optional: breakdown by bedroom count
    performance_by_bedroom: Dict[int, Dict[str, float]] = Field(default_factory=dict)
    
    def model_post_init(self, __context):
        """Compute RevPAR if not provided."""
        if self.portfolio_revpar is None:
            self.portfolio_revpar = self.portfolio_avg_adr * self.portfolio_avg_occupancy
        if self.market_revpar is None:
            self.market_revpar = self.market_avg_adr * self.market_avg_occupancy


class MarketInputs(BaseModel):
    """Market inputs for projection."""
    market_id: UUID
    
    # Seasonality (monthly factors)
    seasonality: Dict[int, Dict[str, float]] = Field(default_factory=dict)
    
    # Market baseline by bedroom
    median_adr_by_bedroom: Dict[int, float] = Field(default_factory=dict)
    median_occupancy_by_bedroom: Dict[int, float] = Field(default_factory=dict)
    
    # Market characteristics
    pool_is_expected: bool = True
    peak_season_months: List[int] = Field(default_factory=lambda: [6, 7])


# =============================================================================
# OUTPUT MODELS
# =============================================================================

class MonthlyProjection(BaseModel):
    """Projection for a single month."""
    month: int
    month_name: str
    year: int
    
    days_in_month: int
    projected_nights_booked: int
    projected_occupancy: float
    
    avg_nightly_rate: float
    projected_revenue: float
    
    confidence: float


class AnnualProjection(BaseModel):
    """Annual projection with ranges."""
    conservative: float
    expected: float
    optimistic: float
    confidence: float


class RentProjection(BaseModel):
    """
    Complete rent projection output.
    
    Now includes full reasoning object for transparency.
    """
    # Identification
    projection_id: UUID = Field(default_factory=uuid4)
    engine_version: str = ENGINE_VERSION
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Subject property summary
    property_summary: str
    property_address: Optional[str] = None
    
    # Annual projections
    annual_gross_revenue: AnnualProjection
    annual_net_revenue: AnnualProjection
    commission_rate: float
    
    # Key metrics
    projected_nights_booked: int
    projected_occupancy: float
    average_nightly_rate: float
    
    # Monthly breakdown
    monthly_projections: List[MonthlyProjection]
    
    # Comparables summary
    comp_count: int
    comp_summary: str
    internal_comp_count: int = 0
    external_comp_count: int = 0
    
    # REASONING OBJECT (Critical for trust)
    reasoning: Dict[str, Any] = Field(default_factory=dict)
    
    # Key assumptions (human-readable)
    key_assumptions: List[str] = Field(default_factory=list)
    
    # Confidence
    confidence_score: float = Field(..., ge=0, le=1)
    confidence_level: str
    
    # Data quality
    data_coverage_pct: float
    market_data_as_of: date


# =============================================================================
# UPLIFT CONFIGURATION
# =============================================================================

@dataclass
class AmenityUpliftConfig:
    """Amenity uplift factors (MULTIPLIERS, not additive)."""
    waterfront: float = 1.20
    waterfront_premium: float = 1.25  # Gulf-front specifically
    
    pool: float = 1.10
    pool_heated: float = 1.03
    
    hot_tub: float = 1.05
    
    gulf_view: float = 1.12
    ocean_view: float = 1.10
    bay_view: float = 1.06
    lake_view: float = 1.05
    
    beach_access_private: float = 1.08
    beach_access_public: float = 1.03
    
    dock: float = 1.05
    elevator: float = 1.03
    game_room: float = 1.02
    home_theater: float = 1.02
    pet_friendly: float = 1.02
    
    no_pool_in_pool_market: float = 0.92


@dataclass
class OperatorDeltaConfig:
    """Configuration for applying operator performance delta."""
    # How much of observed delta to apply (conservative)
    adr_delta_application_rate: float = 0.50  # Apply 50% of observed ADR delta
    occupancy_delta_application_rate: float = 0.40  # Apply 40% of occupancy delta
    
    # Minimum requirements
    min_months_of_data: int = 12
    min_property_count: int = 3
    min_confidence: float = 0.6
    
    # Tapering for new listings
    new_listing_taper: float = 0.5  # Reduce delta by 50% for new listings


# =============================================================================
# RENT PROJECTION ENGINE v1.1
# =============================================================================

class RentProjectionEngineV1_1:
    """
    Rent Projection Engine v1.1 with Operator-Specific Intelligence.
    
    KEY PRINCIPLES:
    1. PURE & DETERMINISTIC - No DB/HTTP calls, Input → Output only
    2. TWO-LAYER COMPS - Internal (operator) + External (market)
    3. CONSERVATIVE DELTA APPLICATION - Never apply 100% of observed uplift
    4. RICH REASONING - Every number is explainable
    5. REPRODUCIBLE - Hash inputs for audit trail
    
    This engine is the DEFENSIBLE CORE of the platform.
    """
    
    # Default seasonality for beach markets
    DEFAULT_SEASONALITY = {
        1: {"occupancy": 0.15, "rate": 0.70},
        2: {"occupancy": 0.20, "rate": 0.72},
        3: {"occupancy": 0.85, "rate": 1.10},
        4: {"occupancy": 0.45, "rate": 0.85},
        5: {"occupancy": 0.55, "rate": 0.95},
        6: {"occupancy": 0.92, "rate": 1.35},
        7: {"occupancy": 0.95, "rate": 1.45},
        8: {"occupancy": 0.75, "rate": 1.15},
        9: {"occupancy": 0.40, "rate": 0.78},
        10: {"occupancy": 0.45, "rate": 0.80},
        11: {"occupancy": 0.30, "rate": 0.72},
        12: {"occupancy": 0.25, "rate": 0.85},
    }
    
    MONTH_NAMES = [
        "", "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December"
    ]
    
    DAYS_IN_MONTH = [0, 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    
    def __init__(
        self,
        amenity_config: AmenityUpliftConfig = None,
        delta_config: OperatorDeltaConfig = None,
    ):
        self.amenity_config = amenity_config or AmenityUpliftConfig()
        self.delta_config = delta_config or OperatorDeltaConfig()
    
    def generate_projection(
        self,
        property_inputs: PropertyInputs,
        market_inputs: MarketInputs,
        internal_comps: Optional[InternalCompSet] = None,
        external_comps: Optional[ExternalCompSet] = None,
        operator_portfolio: Optional[OperatorPortfolio] = None,
        commission_rate: float = 0.20,
        projection_year: int = None,
        property_address: Optional[str] = None,
    ) -> RentProjection:
        """
        Generate a complete rent projection with operator-specific intelligence.
        
        This is the main entry point. The engine:
        1. Computes input hash for reproducibility
        2. Blends internal + external comps
        3. Calculates operator performance delta
        4. Applies amenity uplifts
        5. Generates monthly projections
        6. Produces rich reasoning object
        """
        projection_year = projection_year or datetime.now().year
        reasoning = ProjectionReasoning()
        
        # =================================================================
        # STEP 0: Compute input hash for reproducibility
        # =================================================================
        reasoning.input_hash = self._compute_input_hash(
            property_inputs, market_inputs, internal_comps, external_comps
        )
        
        # =================================================================
        # STEP 1: Blend internal + external comps to get base ADR
        # =================================================================
        base_adr, base_occupancy, reasoning = self._blend_comp_sets(
            property_inputs, market_inputs, internal_comps, external_comps, reasoning
        )
        
        # =================================================================
        # STEP 2: Calculate and apply operator performance delta
        # =================================================================
        adjusted_adr, adjusted_occupancy, reasoning = self._apply_operator_delta(
            base_adr, base_occupancy, operator_portfolio, property_inputs, reasoning
        )
        
        # =================================================================
        # STEP 3: Apply amenity uplifts
        # =================================================================
        final_adr, reasoning = self._apply_amenity_uplifts(
            adjusted_adr, property_inputs, market_inputs, reasoning
        )
        
        # =================================================================
        # STEP 4: Generate monthly projections
        # =================================================================
        monthly_projections = self._generate_monthly_projections(
            final_adr, adjusted_occupancy, property_inputs, market_inputs, projection_year
        )
        
        # Update reasoning with seasonality info
        reasoning.seasonality_source = "market_default" if not market_inputs.seasonality else "market_provided"
        reasoning.peak_months = market_inputs.peak_season_months
        
        # =================================================================
        # STEP 5: Calculate totals and ranges
        # =================================================================
        total_revenue = sum(m.projected_revenue for m in monthly_projections)
        total_nights = sum(m.projected_nights_booked for m in monthly_projections)
        total_available = sum(m.days_in_month for m in monthly_projections)
        
        overall_occupancy = total_nights / total_available if total_available > 0 else 0
        overall_adr = total_revenue / total_nights if total_nights > 0 else final_adr
        
        # Calculate confidence
        confidence_score = self._calculate_confidence(
            internal_comps, external_comps, operator_portfolio, reasoning
        )
        reasoning.overall_confidence = confidence_score
        
        # Ranges based on confidence
        if confidence_score >= 0.8:
            low_factor, high_factor = 0.88, 1.15
            confidence_level = "high"
        elif confidence_score >= 0.6:
            low_factor, high_factor = 0.82, 1.22
            confidence_level = "medium"
        else:
            low_factor, high_factor = 0.75, 1.30
            confidence_level = "low"
        
        gross_annual = AnnualProjection(
            conservative=round(total_revenue * low_factor, 0),
            expected=round(total_revenue, 0),
            optimistic=round(total_revenue * high_factor, 0),
            confidence=confidence_score
        )
        
        net_annual = AnnualProjection(
            conservative=round(total_revenue * low_factor * (1 - commission_rate), 0),
            expected=round(total_revenue * (1 - commission_rate), 0),
            optimistic=round(total_revenue * high_factor * (1 - commission_rate), 0),
            confidence=confidence_score
        )
        
        # =================================================================
        # STEP 6: Build property summary and comp summary
        # =================================================================
        property_summary = self._build_property_summary(property_inputs)
        comp_summary = self._build_comp_summary(internal_comps, external_comps, reasoning)
        
        # Build human-readable assumptions
        key_assumptions = self._build_key_assumptions(reasoning)
        
        return RentProjection(
            projection_id=uuid4(),
            engine_version=ENGINE_VERSION,
            property_summary=property_summary,
            property_address=property_address,
            annual_gross_revenue=gross_annual,
            annual_net_revenue=net_annual,
            commission_rate=commission_rate,
            projected_nights_booked=total_nights,
            projected_occupancy=round(overall_occupancy, 3),
            average_nightly_rate=round(overall_adr, 0),
            monthly_projections=monthly_projections,
            comp_count=(internal_comps.comp_count if internal_comps else 0) + 
                       (external_comps.comp_count if external_comps else 0),
            comp_summary=comp_summary,
            internal_comp_count=internal_comps.comp_count if internal_comps else 0,
            external_comp_count=external_comps.comp_count if external_comps else 0,
            reasoning=reasoning.to_dict(),
            key_assumptions=key_assumptions,
            confidence_score=round(confidence_score, 2),
            confidence_level=confidence_level,
            data_coverage_pct=reasoning.confidence_factors.get("data_coverage", 0.5),
            market_data_as_of=date.today()
        )
    
    def _compute_input_hash(
        self,
        property_inputs: PropertyInputs,
        market_inputs: MarketInputs,
        internal_comps: Optional[InternalCompSet],
        external_comps: Optional[ExternalCompSet],
    ) -> str:
        """Compute deterministic hash of inputs for reproducibility."""
        data = {
            "property": property_inputs.model_dump(),
            "market_id": str(market_inputs.market_id),
            "internal_comp_count": internal_comps.comp_count if internal_comps else 0,
            "external_comp_count": external_comps.comp_count if external_comps else 0,
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:16]
    
    def _blend_comp_sets(
        self,
        property_inputs: PropertyInputs,
        market_inputs: MarketInputs,
        internal_comps: Optional[InternalCompSet],
        external_comps: Optional[ExternalCompSet],
        reasoning: ProjectionReasoning,
    ) -> Tuple[float, float, ProjectionReasoning]:
        """
        Blend internal and external comp sets to determine base ADR and occupancy.
        
        Internal comps are PRIMARY (operator's actual performance).
        External comps are ANCHOR (prevents bias).
        """
        has_internal = internal_comps and internal_comps.comp_count >= 3 and internal_comps.data_coverage_pct >= 0.5
        has_external = external_comps and external_comps.comp_count >= 3 and external_comps.data_coverage_pct >= 0.5
        
        # Determine weights
        if has_internal and has_external:
            # Both available - blend with internal weighted higher
            internal_weight = 0.65  # Internal gets 65%
            external_weight = 0.35
            reasoning.base_adr_source = "blended"
        elif has_internal:
            internal_weight = 1.0
            external_weight = 0.0
            reasoning.base_adr_source = "internal_comps"
        elif has_external:
            internal_weight = 0.0
            external_weight = 1.0
            reasoning.base_adr_source = "external_comps"
        else:
            # Fallback to market median
            bedrooms = property_inputs.bedrooms
            base_adr = market_inputs.median_adr_by_bedroom.get(bedrooms, 500 + bedrooms * 100)
            base_occ = market_inputs.median_occupancy_by_bedroom.get(bedrooms, 0.48)
            reasoning.base_adr = base_adr
            reasoning.base_adr_source = "market_median_fallback"
            return base_adr, base_occ, reasoning
        
        # Calculate blended values
        base_adr = 0.0
        base_occ = 0.0
        
        if internal_weight > 0 and internal_comps:
            base_adr += internal_comps.avg_adr * internal_weight
            base_occ += internal_comps.avg_occupancy * internal_weight
            
            reasoning.internal_comp_analysis = CompAnalysis(
                source=CompSource.INTERNAL,
                comp_count=internal_comps.comp_count,
                avg_similarity=internal_comps.avg_similarity_score,
                avg_adr=internal_comps.avg_adr,
                avg_occupancy=internal_comps.avg_occupancy,
                avg_annual_revenue=internal_comps.avg_annual_revenue,
                data_coverage_pct=internal_comps.data_coverage_pct,
                weight_applied=internal_weight
            )
        
        if external_weight > 0 and external_comps:
            base_adr += external_comps.avg_adr * external_weight
            base_occ += external_comps.avg_occupancy * external_weight
            
            reasoning.external_comp_analysis = CompAnalysis(
                source=CompSource.EXTERNAL,
                comp_count=external_comps.comp_count,
                avg_similarity=external_comps.avg_similarity_score,
                avg_adr=external_comps.avg_adr,
                avg_occupancy=external_comps.avg_occupancy,
                avg_annual_revenue=external_comps.avg_annual_revenue,
                data_coverage_pct=external_comps.data_coverage_pct,
                weight_applied=external_weight
            )
        
        reasoning.base_adr = base_adr
        reasoning.final_comp_weight_internal = internal_weight
        
        return base_adr, base_occ, reasoning
    
    def _apply_operator_delta(
        self,
        base_adr: float,
        base_occupancy: float,
        operator_portfolio: Optional[OperatorPortfolio],
        property_inputs: PropertyInputs,
        reasoning: ProjectionReasoning,
    ) -> Tuple[float, float, ProjectionReasoning]:
        """
        Calculate and apply operator performance delta.
        
        CRITICAL: Never apply 100% of observed delta.
        Use conservative application rate (40-60%).
        """
        if not operator_portfolio:
            return base_adr, base_occupancy, reasoning
        
        # Check minimum requirements
        if (operator_portfolio.months_of_data < self.delta_config.min_months_of_data or
            operator_portfolio.property_count < self.delta_config.min_property_count):
            return base_adr, base_occupancy, reasoning
        
        # Calculate raw deltas
        adr_delta = (operator_portfolio.portfolio_avg_adr - operator_portfolio.market_avg_adr) / operator_portfolio.market_avg_adr
        occ_delta = (operator_portfolio.portfolio_avg_occupancy - operator_portfolio.market_avg_occupancy) / operator_portfolio.market_avg_occupancy
        
        # Apply conservative rate
        adr_delta_applied = adr_delta * self.delta_config.adr_delta_application_rate
        occ_delta_applied = occ_delta * self.delta_config.occupancy_delta_application_rate
        
        # Taper for new listings
        if property_inputs.is_new_listing:
            adr_delta_applied *= self.delta_config.new_listing_taper
            occ_delta_applied *= self.delta_config.new_listing_taper
        
        # Calculate confidence
        delta_confidence = min(
            operator_portfolio.months_of_data / 24,  # Full confidence at 24 months
            operator_portfolio.property_count / 10,   # Full confidence at 10 properties
            1.0
        )
        
        if delta_confidence < self.delta_config.min_confidence:
            return base_adr, base_occupancy, reasoning
        
        # Apply deltas
        adjusted_adr = base_adr * (1 + adr_delta_applied)
        adjusted_occ = base_occupancy * (1 + occ_delta_applied)
        adjusted_occ = min(adjusted_occ, 0.95)  # Cap at 95%
        
        # Record reasoning
        reason_parts = []
        if adr_delta > 0:
            reason_parts.append(f"Portfolio ADR is {adr_delta:.1%} above market")
        if occ_delta > 0:
            reason_parts.append(f"Portfolio occupancy is {occ_delta:.1%} above market")
        reason_parts.append(f"Applied {self.delta_config.adr_delta_application_rate:.0%} of ADR delta, {self.delta_config.occupancy_delta_application_rate:.0%} of occupancy delta (conservative)")
        
        reasoning.operator_delta = OperatorPerformanceDelta(
            adr_delta_pct=adr_delta,
            occupancy_delta_pct=occ_delta,
            adr_delta_applied=adr_delta_applied,
            occupancy_delta_applied=occ_delta_applied,
            months_of_data=operator_portfolio.months_of_data,
            property_count=operator_portfolio.property_count,
            confidence=delta_confidence,
            reason="; ".join(reason_parts)
        )
        
        return adjusted_adr, adjusted_occ, reasoning
    
    def _apply_amenity_uplifts(
        self,
        base_adr: float,
        property_inputs: PropertyInputs,
        market_inputs: MarketInputs,
        reasoning: ProjectionReasoning,
    ) -> Tuple[float, ProjectionReasoning]:
        """
        Apply amenity uplift factors (multiplicative).
        
        PHASE A GUARDRAILS:
        - All uplift factors are bounded [0.85, 1.30]
        - Uplifts are multiplicative, not additive
        - Low confidence uplifts are damped toward 1.0
        """
        from app.services.guardrails.phase_guardrails import APSGuardrails
        
        adjusted_adr = base_adr
        cfg = self.amenity_config
        
        def apply_bounded_uplift(factor: float, confidence: float = 0.85) -> float:
            """Apply Phase A guardrails: bound and damp."""
            bounded = APSGuardrails.apply_bounds(factor)
            damped = APSGuardrails.apply_confidence_damping(bounded, confidence)
            return damped
        
        # Waterfront
        if property_inputs.waterfront:
            if property_inputs.view in ["gulf", "ocean"]:
                raw_factor = cfg.waterfront_premium
                reason = "Gulf/Ocean waterfront premium"
            else:
                raw_factor = cfg.waterfront
                reason = "Waterfront premium"
            factor = apply_bounded_uplift(raw_factor, 0.9)
            adjusted_adr *= factor
            reasoning.uplifts_applied.append(AppliedUplift(
                name="waterfront", factor=factor, reason=f"{reason} (bounded)", confidence=0.9
            ))
        
        # Pool
        if property_inputs.pool:
            factor = apply_bounded_uplift(cfg.pool, 0.9)
            adjusted_adr *= factor
            reasoning.uplifts_applied.append(AppliedUplift(
                name="pool", factor=factor, reason="Private pool premium (bounded)", confidence=0.9
            ))
            if property_inputs.pool_heated:
                factor = apply_bounded_uplift(cfg.pool_heated, 0.85)
                adjusted_adr *= factor
                reasoning.uplifts_applied.append(AppliedUplift(
                    name="pool_heated", factor=factor, reason="Heated pool (bounded)", confidence=0.85
                ))
        elif market_inputs.pool_is_expected:
            factor = apply_bounded_uplift(cfg.no_pool_in_pool_market, 0.8)
            adjusted_adr *= factor
            reasoning.uplifts_applied.append(AppliedUplift(
                name="no_pool_penalty", factor=factor, 
                reason="No pool (expected in market, bounded)", confidence=0.8
            ))
        
        # Hot tub
        if property_inputs.hot_tub:
            factor = apply_bounded_uplift(cfg.hot_tub, 0.85)
            adjusted_adr *= factor
            reasoning.uplifts_applied.append(AppliedUplift(
                name="hot_tub", factor=factor, reason="Hot tub premium (bounded)", confidence=0.85
            ))
        
        # View (if not waterfront)
        if property_inputs.view and not property_inputs.waterfront:
            view_factors = {
                "gulf": (cfg.gulf_view, "Gulf view"),
                "ocean": (cfg.ocean_view, "Ocean view"),
                "bay": (cfg.bay_view, "Bay view"),
                "lake": (cfg.lake_view, "Lake view"),
            }
            if property_inputs.view in view_factors:
                raw_factor, reason = view_factors[property_inputs.view]
                factor = apply_bounded_uplift(raw_factor, 0.8)
                adjusted_adr *= factor
                reasoning.uplifts_applied.append(AppliedUplift(
                    name=f"{property_inputs.view}_view", factor=factor, reason=f"{reason} (bounded)", confidence=0.8
                ))
        
        # Beach access
        if property_inputs.beach_access:
            if property_inputs.beach_access == "private":
                raw_factor = cfg.beach_access_private
                reason = "Private beach access"
            else:
                raw_factor = cfg.beach_access_public
                reason = "Public beach access nearby"
            factor = apply_bounded_uplift(raw_factor, 0.85)
            adjusted_adr *= factor
            reasoning.uplifts_applied.append(AppliedUplift(
                name="beach_access", factor=factor, reason=f"{reason} (bounded)", confidence=0.85
            ))
        
        return adjusted_adr, reasoning
    
    def _generate_monthly_projections(
        self,
        final_adr: float,
        base_occupancy: float,
        property_inputs: PropertyInputs,
        market_inputs: MarketInputs,
        year: int,
    ) -> List[MonthlyProjection]:
        """Generate monthly projections with seasonality."""
        projections = []
        
        # Get seasonality
        seasonality = market_inputs.seasonality or self.DEFAULT_SEASONALITY
        
        for month in range(1, 13):
            days = self.DAYS_IN_MONTH[month]
            season = seasonality.get(month, self.DEFAULT_SEASONALITY[month])
            
            monthly_rate = final_adr * season.get("rate", 1.0)
            monthly_occ = base_occupancy * (season.get("occupancy", 0.5) / 0.5)
            monthly_occ = min(monthly_occ, 0.98)
            
            # New listing adjustment
            if property_inputs.is_new_listing and property_inputs.months_active < 4:
                taper_factors = [0.65, 0.80, 0.92, 0.97]
                taper = taper_factors[min(property_inputs.months_active, 3)]
                monthly_occ *= taper
            
            nights_booked = round(days * monthly_occ)
            revenue = nights_booked * monthly_rate
            
            confidence = 0.90 if month in market_inputs.peak_season_months else 0.80
            
            projections.append(MonthlyProjection(
                month=month,
                month_name=self.MONTH_NAMES[month],
                year=year,
                days_in_month=days,
                projected_nights_booked=nights_booked,
                projected_occupancy=round(monthly_occ, 3),
                avg_nightly_rate=round(monthly_rate, 0),
                projected_revenue=round(revenue, 0),
                confidence=confidence
            ))
        
        return projections
    
    def _calculate_confidence(
        self,
        internal_comps: Optional[InternalCompSet],
        external_comps: Optional[ExternalCompSet],
        operator_portfolio: Optional[OperatorPortfolio],
        reasoning: ProjectionReasoning,
    ) -> float:
        """Calculate overall confidence score."""
        score = 0.4  # Base
        
        # Internal comp contribution (up to 0.25)
        if internal_comps and internal_comps.comp_count >= 3:
            internal_contrib = min(internal_comps.comp_count / 10, 1.0) * 0.15
            internal_contrib += internal_comps.data_coverage_pct * 0.10
            score += internal_contrib
            reasoning.confidence_factors["internal_comps"] = internal_contrib
        
        # External comp contribution (up to 0.15)
        if external_comps and external_comps.comp_count >= 3:
            external_contrib = min(external_comps.comp_count / 15, 1.0) * 0.10
            external_contrib += external_comps.data_coverage_pct * 0.05
            score += external_contrib
            reasoning.confidence_factors["external_comps"] = external_contrib
        
        # Operator delta contribution (up to 0.15)
        if reasoning.operator_delta:
            delta_contrib = reasoning.operator_delta.confidence * 0.15
            score += delta_contrib
            reasoning.confidence_factors["operator_delta"] = delta_contrib
        
        # Data coverage
        total_coverage = 0.5
        if internal_comps:
            total_coverage = max(total_coverage, internal_comps.data_coverage_pct)
        if external_comps:
            total_coverage = max(total_coverage, external_comps.data_coverage_pct)
        reasoning.confidence_factors["data_coverage"] = total_coverage
        
        return min(score, 1.0)
    
    def _build_property_summary(self, inputs: PropertyInputs) -> str:
        """Build human-readable property summary."""
        bath_str = f"{inputs.bathrooms:.1f}".rstrip('0').rstrip('.')
        parts = [f"{inputs.bedrooms}BR/{bath_str}BA"]
        parts.append(inputs.property_type.replace("_", " ").title())
        
        amenities = []
        if inputs.waterfront:
            amenities.append("Waterfront")
        if inputs.pool:
            amenities.append("Pool")
        if inputs.hot_tub:
            amenities.append("Hot Tub")
        if inputs.view:
            amenities.append(f"{inputs.view.title()} View")
        if inputs.beach_access:
            amenities.append("Beach Access")
        
        if amenities:
            parts.append("with " + ", ".join(amenities))
        
        return " ".join(parts)
    
    def _build_comp_summary(
        self,
        internal_comps: Optional[InternalCompSet],
        external_comps: Optional[ExternalCompSet],
        reasoning: ProjectionReasoning,
    ) -> str:
        """Build comp summary string."""
        parts = []
        
        if internal_comps and internal_comps.comp_count > 0:
            parts.append(f"{internal_comps.comp_count} properties from operator portfolio")
        
        if external_comps and external_comps.comp_count > 0:
            parts.append(f"{external_comps.comp_count} market comparables")
        
        if not parts:
            return "Based on market median estimates"
        
        return "Based on " + " and ".join(parts)
    
    def _build_key_assumptions(self, reasoning: ProjectionReasoning) -> List[str]:
        """Build human-readable list of key assumptions."""
        assumptions = []
        
        # Base ADR source
        if reasoning.base_adr_source == "blended":
            assumptions.append(f"Base rate from blended internal ({reasoning.final_comp_weight_internal:.0%}) and external ({1-reasoning.final_comp_weight_internal:.0%}) comps")
        elif reasoning.base_adr_source == "internal_comps":
            assumptions.append("Base rate from operator's portfolio comparables")
        elif reasoning.base_adr_source == "external_comps":
            assumptions.append("Base rate from market comparables")
        else:
            assumptions.append("Base rate from market median (limited comp data)")
        
        # Operator delta
        if reasoning.operator_delta:
            delta = reasoning.operator_delta
            assumptions.append(
                f"Operator performance adjustment: +{delta.adr_delta_applied:.1%} ADR "
                f"(based on {delta.months_of_data} months of data from {delta.property_count} properties)"
            )
        
        # Uplifts
        for uplift in reasoning.uplifts_applied:
            pct = (uplift.factor - 1) * 100
            sign = "+" if pct >= 0 else ""
            assumptions.append(f"{uplift.reason}: {sign}{pct:.0f}% to rate")
        
        # New listing
        if reasoning.new_listing_adjustment:
            assumptions.append(f"New listing adjustment: {reasoning.new_listing_adjustment:.0%} occupancy reduction initially")
        
        return assumptions


# =============================================================================
# CONVENIENCE FUNCTION
# =============================================================================

def generate_operator_aware_projection(
    bedrooms: int,
    bathrooms: float,
    has_pool: bool = False,
    waterfront: bool = False,
    view: Optional[str] = None,
    beach_access: Optional[str] = None,
    commission_rate: float = 0.20,
    # Operator-specific (optional)
    internal_avg_adr: Optional[float] = None,
    internal_avg_occupancy: Optional[float] = None,
    internal_comp_count: int = 0,
    operator_adr_vs_market: Optional[float] = None,  # e.g., 1.12 = +12%
    operator_occupancy_vs_market: Optional[float] = None,
) -> RentProjection:
    """
    Quick projection with optional operator-specific intelligence.
    
    For full control, use RentProjectionEngineV1_1 directly.
    """
    engine = RentProjectionEngineV1_1()
    
    property_inputs = PropertyInputs(
        bedrooms=bedrooms,
        bathrooms=bathrooms,
        pool=has_pool,
        waterfront=waterfront,
        view=view,
        beach_access=beach_access,
    )
    
    market_inputs = MarketInputs(
        market_id=uuid4(),
        median_adr_by_bedroom={
            1: 250, 2: 350, 3: 500, 4: 700, 5: 900, 6: 1100, 7: 1300, 8: 1500
        },
        median_occupancy_by_bedroom={
            1: 0.55, 2: 0.52, 3: 0.50, 4: 0.48, 5: 0.46, 6: 0.44, 7: 0.42, 8: 0.40
        },
        pool_is_expected=True,
    )
    
    # Build internal comps if provided
    internal_comps = None
    if internal_avg_adr and internal_comp_count >= 3:
        internal_comps = InternalCompSet(
            company_id=uuid4(),
            comp_count=internal_comp_count,
            avg_adr=internal_avg_adr,
            avg_occupancy=internal_avg_occupancy or 0.50,
            avg_similarity_score=0.85,
            data_coverage_pct=0.80,
            months_of_data=18,
        )
    
    # Build external comps (market baseline)
    external_comps = ExternalCompSet(
        market_id=market_inputs.market_id,
        comp_count=10,
        avg_adr=market_inputs.median_adr_by_bedroom.get(bedrooms, 700),
        avg_occupancy=market_inputs.median_occupancy_by_bedroom.get(bedrooms, 0.48),
        avg_similarity_score=0.75,
        data_coverage_pct=0.70,
    )
    
    # Build operator portfolio if deltas provided
    operator_portfolio = None
    if operator_adr_vs_market:
        market_adr = market_inputs.median_adr_by_bedroom.get(bedrooms, 700)
        market_occ = market_inputs.median_occupancy_by_bedroom.get(bedrooms, 0.48)
        
        operator_portfolio = OperatorPortfolio(
            company_id=uuid4(),
            portfolio_avg_adr=market_adr * operator_adr_vs_market,
            market_avg_adr=market_adr,
            portfolio_avg_occupancy=market_occ * (operator_occupancy_vs_market or 1.0),
            market_avg_occupancy=market_occ,
            property_count=15,
            months_of_data=24,
        )
    
    return engine.generate_projection(
        property_inputs=property_inputs,
        market_inputs=market_inputs,
        internal_comps=internal_comps,
        external_comps=external_comps,
        operator_portfolio=operator_portfolio,
        commission_rate=commission_rate,
    )
