"""
Rent Projection Engine - BD's Core Weapon.

This is NOT "AirDNA-lite".
This must survive scrutiny from realtors and owners.

The math is EXPLAINABLE:
1. Base ADR from weighted comp set
2. Amenity uplift (multiplicative, not additive)
3. Occupancy curve with seasonality + new listing adjustment
4. Confidence bands based on data coverage

Voice agent can say:
"This estimate is based on 14 comparable properties with strong data coverage."
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4
import statistics

from pydantic import BaseModel, Field

from app.services.normalization.canonical_entities import (
    NormalizedProperty,
    NormalizedComparableSet,
    CompProperty,
    MarketSeasonality,
    MonthlySeasonality,
    NormalizedBookingPerformance,
)


# =============================================================================
# PROJECTION CONFIGURATION
# =============================================================================

class ProjectionScenario(str, Enum):
    """Projection scenarios."""
    CONSERVATIVE = "conservative"
    EXPECTED = "expected"
    OPTIMISTIC = "optimistic"


@dataclass
class AmenityUplift:
    """
    Amenity uplift factors.
    
    These are MULTIPLIERS, not additive.
    Based on market research and comp analysis.
    """
    # Premium amenities
    waterfront: float = 1.20  # +15-25%
    waterfront_premium: float = 1.25  # Gulf-front specifically
    
    pool: float = 1.10  # +8-12%
    pool_heated: float = 1.03  # Additional for heated
    
    hot_tub: float = 1.05  # +3-7%
    
    # View premiums
    gulf_view: float = 1.12  # +10-15%
    ocean_view: float = 1.10
    bay_view: float = 1.06
    lake_view: float = 1.05
    
    # Beach access
    beach_access_private: float = 1.08
    beach_access_public: float = 1.03
    
    # Other
    dock: float = 1.05
    elevator: float = 1.03
    game_room: float = 1.02
    home_theater: float = 1.02
    pet_friendly: float = 1.02  # Can also reduce - market dependent
    
    # Negative adjustments
    no_pool_in_pool_market: float = 0.92  # Penalty in markets where pools are expected


@dataclass
class NewListingAdjustment:
    """
    Adjustment factors for new listings.
    
    New listings typically:
    - Underperform first 60-90 days (building reviews)
    - Then normalize or exceed (fresh inventory appeal)
    """
    # First 60 days: significant underperformance
    month_1_factor: float = 0.65
    month_2_factor: float = 0.80
    
    # Months 3-4: approaching normal
    month_3_factor: float = 0.92
    month_4_factor: float = 0.97
    
    # Month 5+: normalized
    month_5_plus_factor: float = 1.00


# =============================================================================
# PROJECTION INPUTS
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


class MarketInputs(BaseModel):
    """Market inputs for projection."""
    market_id: UUID
    
    # Seasonality (monthly factors)
    seasonality: List[MonthlySeasonality] = Field(default_factory=list)
    
    # Market baseline
    median_adr_by_bedroom: Dict[int, float] = Field(default_factory=dict)
    median_occupancy_by_bedroom: Dict[int, float] = Field(default_factory=dict)
    
    # Market characteristics
    pool_is_expected: bool = True  # In 30A, yes
    peak_season_months: List[int] = Field(default_factory=lambda: [6, 7])


class CompInputs(BaseModel):
    """Comparable property inputs."""
    comparables: List[CompProperty] = Field(default_factory=list)
    
    # Aggregate metrics
    weighted_avg_adr: Optional[float] = None
    weighted_avg_occupancy: Optional[float] = None
    weighted_avg_revenue: Optional[float] = None
    
    # Quality
    comp_count: int = 0
    data_coverage_pct: float = 0.0
    avg_similarity_score: float = 0.0


# =============================================================================
# PROJECTION OUTPUTS
# =============================================================================

class MonthlyProjection(BaseModel):
    """Projection for a single month."""
    month: int
    month_name: str
    year: int
    
    # Days
    days_in_month: int
    projected_nights_booked: int
    projected_occupancy: float
    
    # Rates
    avg_nightly_rate: float
    
    # Revenue
    projected_revenue: float
    
    # Confidence
    confidence: float


class AnnualProjection(BaseModel):
    """Annual projection with ranges."""
    conservative: float
    expected: float
    optimistic: float
    
    # Confidence in these ranges
    confidence: float


class ProjectionAssumption(BaseModel):
    """A documented assumption in the projection."""
    category: str  # comp, amenity, seasonality, market
    assumption: str
    impact: str  # e.g., "+12% to base rate"
    confidence: float


class RentProjection(BaseModel):
    """
    Complete rent projection output.
    
    This is the BD deliverable that closes deals.
    """
    # Identification
    projection_id: UUID = Field(default_factory=uuid4)
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Subject property summary
    property_summary: str
    property_address: Optional[str] = None
    
    # Annual projections (THE KEY OUTPUT)
    annual_gross_revenue: AnnualProjection
    annual_net_revenue: AnnualProjection  # After commission
    commission_rate: float
    
    # Key metrics
    projected_nights_booked: int
    projected_occupancy: float
    average_nightly_rate: float
    
    # Monthly breakdown
    monthly_projections: List[MonthlyProjection]
    
    # Comparables used
    comp_count: int
    comp_summary: str  # "Based on 14 comparable properties within 2 miles"
    top_comps: List[Dict[str, Any]] = Field(default_factory=list)
    
    # Assumptions (CRITICAL FOR TRUST)
    key_assumptions: List[ProjectionAssumption]
    
    # Confidence
    confidence_score: float = Field(..., ge=0, le=1)
    confidence_level: str  # high, medium, low
    confidence_factors: Dict[str, float] = Field(default_factory=dict)
    
    # Data quality
    data_coverage_pct: float
    market_data_as_of: date


# =============================================================================
# RENT PROJECTION ENGINE
# =============================================================================

class RentProjectionEngine:
    """
    The engine that generates defensible rent projections.
    
    Math is explainable:
    1. Base ADR = median ADR of weighted comp set
    2. Amenity uplift = multiplicative factors
    3. Occupancy = market curve × property quality × new listing adjustment
    4. Revenue = Σ (rate × nights)
    5. Ranges = statistical bands around expected
    """
    
    # Default seasonality for 30A-style beach markets
    DEFAULT_SEASONALITY = {
        1: {"occupancy": 0.15, "rate": 0.70},   # January - very low
        2: {"occupancy": 0.20, "rate": 0.72},   # February - slightly better
        3: {"occupancy": 0.85, "rate": 1.10},   # March - Spring Break PEAK
        4: {"occupancy": 0.45, "rate": 0.85},   # April - shoulder
        5: {"occupancy": 0.55, "rate": 0.95},   # May - warming up
        6: {"occupancy": 0.92, "rate": 1.35},   # June - PEAK
        7: {"occupancy": 0.95, "rate": 1.45},   # July - PEAK (4th of July)
        8: {"occupancy": 0.75, "rate": 1.15},   # August - late summer
        9: {"occupancy": 0.40, "rate": 0.78},   # September - shoulder
        10: {"occupancy": 0.45, "rate": 0.80},  # October - fall
        11: {"occupancy": 0.30, "rate": 0.72},  # November - low
        12: {"occupancy": 0.25, "rate": 0.85},  # December - holidays bump
    }
    
    MONTH_NAMES = [
        "", "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December"
    ]
    
    DAYS_IN_MONTH = [0, 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    
    def __init__(
        self,
        amenity_uplift: AmenityUplift = None,
        new_listing_adj: NewListingAdjustment = None,
    ):
        self.amenity_uplift = amenity_uplift or AmenityUplift()
        self.new_listing_adj = new_listing_adj or NewListingAdjustment()
    
    def generate_projection(
        self,
        property_inputs: PropertyInputs,
        market_inputs: MarketInputs,
        comp_inputs: CompInputs,
        commission_rate: float = 0.20,
        projection_year: int = None,
        property_address: Optional[str] = None,
    ) -> RentProjection:
        """
        Generate a complete rent projection.
        
        This is the main entry point.
        """
        projection_year = projection_year or datetime.now().year
        assumptions = []
        
        # =================================================================
        # STEP 1: Determine Base ADR
        # =================================================================
        base_adr, adr_assumptions = self._calculate_base_adr(
            property_inputs, market_inputs, comp_inputs
        )
        assumptions.extend(adr_assumptions)
        
        # =================================================================
        # STEP 2: Apply Amenity Uplift
        # =================================================================
        adjusted_adr, amenity_assumptions = self._apply_amenity_uplift(
            base_adr, property_inputs, market_inputs
        )
        assumptions.extend(amenity_assumptions)
        
        # =================================================================
        # STEP 3: Determine Base Occupancy
        # =================================================================
        base_occupancy, occ_assumptions = self._calculate_base_occupancy(
            property_inputs, market_inputs, comp_inputs
        )
        assumptions.extend(occ_assumptions)
        
        # =================================================================
        # STEP 4: Generate Monthly Projections
        # =================================================================
        monthly_projections = self._generate_monthly_projections(
            adjusted_adr,
            base_occupancy,
            property_inputs,
            market_inputs,
            projection_year
        )
        
        # =================================================================
        # STEP 5: Calculate Annual Totals
        # =================================================================
        total_revenue = sum(m.projected_revenue for m in monthly_projections)
        total_nights = sum(m.projected_nights_booked for m in monthly_projections)
        total_available = sum(m.days_in_month for m in monthly_projections)
        
        overall_occupancy = total_nights / total_available if total_available > 0 else 0
        overall_adr = total_revenue / total_nights if total_nights > 0 else adjusted_adr
        
        # =================================================================
        # STEP 6: Calculate Ranges
        # =================================================================
        confidence_score = self._calculate_confidence(comp_inputs, market_inputs)
        
        # Ranges based on confidence
        if confidence_score >= 0.8:
            low_factor, high_factor = 0.88, 1.15
        elif confidence_score >= 0.6:
            low_factor, high_factor = 0.82, 1.22
        else:
            low_factor, high_factor = 0.75, 1.30
        
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
        # STEP 7: Build Property Summary
        # =================================================================
        property_summary = self._build_property_summary(property_inputs)
        
        # Comp summary
        comp_summary = f"Based on {comp_inputs.comp_count} comparable properties"
        if comp_inputs.avg_similarity_score > 0:
            comp_summary += f" (avg similarity: {comp_inputs.avg_similarity_score:.0%})"
        
        # Confidence level
        if confidence_score >= 0.8:
            confidence_level = "high"
        elif confidence_score >= 0.6:
            confidence_level = "medium"
        else:
            confidence_level = "low"
        
        return RentProjection(
            property_summary=property_summary,
            property_address=property_address,
            annual_gross_revenue=gross_annual,
            annual_net_revenue=net_annual,
            commission_rate=commission_rate,
            projected_nights_booked=total_nights,
            projected_occupancy=round(overall_occupancy, 3),
            average_nightly_rate=round(overall_adr, 0),
            monthly_projections=monthly_projections,
            comp_count=comp_inputs.comp_count,
            comp_summary=comp_summary,
            key_assumptions=assumptions,
            confidence_score=round(confidence_score, 2),
            confidence_level=confidence_level,
            confidence_factors={
                "comp_data_coverage": comp_inputs.data_coverage_pct,
                "comp_count": min(comp_inputs.comp_count / 10, 1.0),
                "similarity_score": comp_inputs.avg_similarity_score,
            },
            data_coverage_pct=comp_inputs.data_coverage_pct,
            market_data_as_of=date.today()
        )
    
    def _calculate_base_adr(
        self,
        property_inputs: PropertyInputs,
        market_inputs: MarketInputs,
        comp_inputs: CompInputs,
    ) -> Tuple[float, List[ProjectionAssumption]]:
        """
        Step 1: Calculate base ADR from comps or market data.
        
        Priority:
        1. Weighted average from comps (if sufficient data)
        2. Market median by bedroom count
        3. Fallback to estimation
        """
        assumptions = []
        
        # Try comp-based ADR first
        if comp_inputs.weighted_avg_adr and comp_inputs.data_coverage_pct >= 0.5:
            base_adr = comp_inputs.weighted_avg_adr
            assumptions.append(ProjectionAssumption(
                category="comp",
                assumption=f"Base ADR from {comp_inputs.comp_count} comparable properties",
                impact=f"${base_adr:.0f}/night baseline",
                confidence=comp_inputs.data_coverage_pct
            ))
        
        # Fall back to market median
        elif property_inputs.bedrooms in market_inputs.median_adr_by_bedroom:
            base_adr = market_inputs.median_adr_by_bedroom[property_inputs.bedrooms]
            assumptions.append(ProjectionAssumption(
                category="market",
                assumption=f"Base ADR from market median for {property_inputs.bedrooms}BR",
                impact=f"${base_adr:.0f}/night baseline",
                confidence=0.7
            ))
        
        # Estimation based on bedroom count
        else:
            # Rough heuristic: $150 base + $75 per bedroom
            base_adr = 150 + (property_inputs.bedrooms * 100)
            assumptions.append(ProjectionAssumption(
                category="estimate",
                assumption="Base ADR estimated (limited comp data)",
                impact=f"${base_adr:.0f}/night baseline",
                confidence=0.5
            ))
        
        return base_adr, assumptions
    
    def _apply_amenity_uplift(
        self,
        base_adr: float,
        property_inputs: PropertyInputs,
        market_inputs: MarketInputs,
    ) -> Tuple[float, List[ProjectionAssumption]]:
        """
        Step 2: Apply amenity uplift factors.
        
        These are MULTIPLIERS, applied sequentially.
        """
        assumptions = []
        adjusted_adr = base_adr
        
        # Waterfront premium
        if property_inputs.waterfront:
            if property_inputs.view in ["gulf", "ocean"]:
                factor = self.amenity_uplift.waterfront_premium
                adjusted_adr *= factor
                assumptions.append(ProjectionAssumption(
                    category="amenity",
                    assumption="Gulf/Ocean waterfront premium",
                    impact=f"+{(factor - 1) * 100:.0f}% to rate",
                    confidence=0.9
                ))
            else:
                factor = self.amenity_uplift.waterfront
                adjusted_adr *= factor
                assumptions.append(ProjectionAssumption(
                    category="amenity",
                    assumption="Waterfront premium",
                    impact=f"+{(factor - 1) * 100:.0f}% to rate",
                    confidence=0.85
                ))
        
        # Pool
        if property_inputs.pool:
            factor = self.amenity_uplift.pool
            adjusted_adr *= factor
            assumptions.append(ProjectionAssumption(
                category="amenity",
                assumption="Private pool premium",
                impact=f"+{(factor - 1) * 100:.0f}% to rate",
                confidence=0.9
            ))
            
            if property_inputs.pool_heated:
                factor = self.amenity_uplift.pool_heated
                adjusted_adr *= factor
                assumptions.append(ProjectionAssumption(
                    category="amenity",
                    assumption="Heated pool premium",
                    impact=f"+{(factor - 1) * 100:.0f}% additional",
                    confidence=0.85
                ))
        
        elif market_inputs.pool_is_expected:
            # Penalty for no pool in a pool market
            factor = self.amenity_uplift.no_pool_in_pool_market
            adjusted_adr *= factor
            assumptions.append(ProjectionAssumption(
                category="amenity",
                assumption="No pool adjustment (pool expected in market)",
                impact=f"{(factor - 1) * 100:.0f}% to rate",
                confidence=0.8
            ))
        
        # Hot tub
        if property_inputs.hot_tub:
            factor = self.amenity_uplift.hot_tub
            adjusted_adr *= factor
            assumptions.append(ProjectionAssumption(
                category="amenity",
                assumption="Hot tub premium",
                impact=f"+{(factor - 1) * 100:.0f}% to rate",
                confidence=0.85
            ))
        
        # View (if not already counted in waterfront)
        if property_inputs.view and not property_inputs.waterfront:
            view_factors = {
                "gulf": self.amenity_uplift.gulf_view,
                "ocean": self.amenity_uplift.ocean_view,
                "bay": self.amenity_uplift.bay_view,
                "lake": self.amenity_uplift.lake_view,
            }
            if property_inputs.view in view_factors:
                factor = view_factors[property_inputs.view]
                adjusted_adr *= factor
                assumptions.append(ProjectionAssumption(
                    category="amenity",
                    assumption=f"{property_inputs.view.title()} view premium",
                    impact=f"+{(factor - 1) * 100:.0f}% to rate",
                    confidence=0.8
                ))
        
        # Beach access
        if property_inputs.beach_access:
            if property_inputs.beach_access == "private":
                factor = self.amenity_uplift.beach_access_private
            else:
                factor = self.amenity_uplift.beach_access_public
            adjusted_adr *= factor
            assumptions.append(ProjectionAssumption(
                category="amenity",
                assumption=f"{property_inputs.beach_access.title()} beach access",
                impact=f"+{(factor - 1) * 100:.0f}% to rate",
                confidence=0.85
            ))
        
        return adjusted_adr, assumptions
    
    def _calculate_base_occupancy(
        self,
        property_inputs: PropertyInputs,
        market_inputs: MarketInputs,
        comp_inputs: CompInputs,
    ) -> Tuple[float, List[ProjectionAssumption]]:
        """
        Step 3: Calculate base occupancy expectation.
        """
        assumptions = []
        
        # Try comp-based occupancy
        if comp_inputs.weighted_avg_occupancy and comp_inputs.data_coverage_pct >= 0.5:
            base_occ = comp_inputs.weighted_avg_occupancy
            assumptions.append(ProjectionAssumption(
                category="comp",
                assumption=f"Base occupancy from {comp_inputs.comp_count} comps",
                impact=f"{base_occ:.0%} annual baseline",
                confidence=comp_inputs.data_coverage_pct
            ))
        
        # Market median
        elif property_inputs.bedrooms in market_inputs.median_occupancy_by_bedroom:
            base_occ = market_inputs.median_occupancy_by_bedroom[property_inputs.bedrooms]
            assumptions.append(ProjectionAssumption(
                category="market",
                assumption=f"Base occupancy from market median for {property_inputs.bedrooms}BR",
                impact=f"{base_occ:.0%} annual baseline",
                confidence=0.7
            ))
        
        # Default
        else:
            base_occ = 0.50
            assumptions.append(ProjectionAssumption(
                category="estimate",
                assumption="Base occupancy estimated (market avg)",
                impact=f"{base_occ:.0%} annual baseline",
                confidence=0.5
            ))
        
        return base_occ, assumptions
    
    def _generate_monthly_projections(
        self,
        adjusted_adr: float,
        base_occupancy: float,
        property_inputs: PropertyInputs,
        market_inputs: MarketInputs,
        year: int,
    ) -> List[MonthlyProjection]:
        """
        Step 4: Generate monthly projections applying seasonality.
        """
        projections = []
        
        # Get seasonality (use market-provided or default)
        seasonality = {}
        if market_inputs.seasonality:
            for ms in market_inputs.seasonality:
                seasonality[ms.month] = {
                    "occupancy": ms.expected_occupancy,
                    "rate": ms.rate_factor
                }
        
        # Fall back to defaults
        for month in range(1, 13):
            if month not in seasonality:
                seasonality[month] = self.DEFAULT_SEASONALITY[month]
        
        for month in range(1, 13):
            days = self.DAYS_IN_MONTH[month]
            
            # Get seasonal factors
            season = seasonality[month]
            
            # Calculate monthly rate (base × seasonal factor)
            monthly_rate = adjusted_adr * season["rate"]
            
            # Calculate monthly occupancy
            monthly_occ = base_occupancy * (season["occupancy"] / 0.50)  # Normalize to base
            monthly_occ = min(monthly_occ, 0.98)  # Cap at 98%
            
            # Apply new listing adjustment
            if property_inputs.is_new_listing:
                active_months = property_inputs.months_active
                if active_months < 1:
                    monthly_occ *= self.new_listing_adj.month_1_factor
                elif active_months < 2:
                    monthly_occ *= self.new_listing_adj.month_2_factor
                elif active_months < 3:
                    monthly_occ *= self.new_listing_adj.month_3_factor
                elif active_months < 4:
                    monthly_occ *= self.new_listing_adj.month_4_factor
                # else: no adjustment
            
            # Calculate nights booked
            nights_booked = round(days * monthly_occ)
            
            # Calculate revenue
            monthly_revenue = nights_booked * monthly_rate
            
            # Confidence (higher for peak seasons with more data)
            if month in [6, 7]:
                confidence = 0.90
            elif month in [3, 5, 8]:
                confidence = 0.85
            else:
                confidence = 0.75
            
            projections.append(MonthlyProjection(
                month=month,
                month_name=self.MONTH_NAMES[month],
                year=year,
                days_in_month=days,
                projected_nights_booked=nights_booked,
                projected_occupancy=round(monthly_occ, 3),
                avg_nightly_rate=round(monthly_rate, 0),
                projected_revenue=round(monthly_revenue, 0),
                confidence=confidence
            ))
        
        return projections
    
    def _calculate_confidence(
        self,
        comp_inputs: CompInputs,
        market_inputs: MarketInputs,
    ) -> float:
        """
        Calculate overall confidence score.
        
        Factors:
        - Data coverage (% of comps with performance data)
        - Comp count (more = better)
        - Comp similarity scores
        - Market data availability
        """
        score = 0.5  # Base
        
        # Comp count contribution (up to 0.2)
        comp_contribution = min(comp_inputs.comp_count / 15, 1.0) * 0.2
        score += comp_contribution
        
        # Data coverage contribution (up to 0.15)
        coverage_contribution = comp_inputs.data_coverage_pct * 0.15
        score += coverage_contribution
        
        # Similarity score contribution (up to 0.10)
        similarity_contribution = comp_inputs.avg_similarity_score * 0.10
        score += similarity_contribution
        
        # Market data contribution (up to 0.05)
        if market_inputs.seasonality:
            score += 0.05
        
        return min(score, 1.0)
    
    def _build_property_summary(self, inputs: PropertyInputs) -> str:
        """Build human-readable property summary."""
        bath_str = f"{inputs.bathrooms:.1f}".rstrip('0').rstrip('.')
        
        parts = [f"{inputs.bedrooms}BR/{bath_str}BA"]
        
        # Property type
        prop_type = inputs.property_type.replace("_", " ").title()
        parts.append(prop_type)
        
        # Key amenities
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


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def generate_quick_projection(
    bedrooms: int,
    bathrooms: float,
    has_pool: bool = False,
    waterfront: bool = False,
    view: Optional[str] = None,
    beach_access: Optional[str] = None,
    market_id: Optional[UUID] = None,
    commission_rate: float = 0.20,
) -> RentProjection:
    """
    Quick projection with minimal inputs.
    
    Uses market defaults and estimated comps.
    """
    engine = RentProjectionEngine()
    
    property_inputs = PropertyInputs(
        bedrooms=bedrooms,
        bathrooms=bathrooms,
        pool=has_pool,
        waterfront=waterfront,
        view=view,
        beach_access=beach_access,
    )
    
    # Default market inputs for 30A-style market
    market_inputs = MarketInputs(
        market_id=market_id or uuid4(),
        median_adr_by_bedroom={
            1: 250, 2: 350, 3: 500, 4: 700, 5: 900, 6: 1100, 7: 1300, 8: 1500
        },
        median_occupancy_by_bedroom={
            1: 0.55, 2: 0.52, 3: 0.50, 4: 0.48, 5: 0.46, 6: 0.44, 7: 0.42, 8: 0.40
        },
        pool_is_expected=True,
    )
    
    # Estimated comp inputs
    comp_inputs = CompInputs(
        comp_count=8,
        data_coverage_pct=0.75,
        avg_similarity_score=0.80,
        weighted_avg_adr=market_inputs.median_adr_by_bedroom.get(bedrooms, 500),
        weighted_avg_occupancy=market_inputs.median_occupancy_by_bedroom.get(bedrooms, 0.48),
    )
    
    return engine.generate_projection(
        property_inputs=property_inputs,
        market_inputs=market_inputs,
        comp_inputs=comp_inputs,
        commission_rate=commission_rate,
    )
