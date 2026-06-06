"""
Domain: Pricing - Pure Computations.

No FastAPI. No DB sessions. No external API calls.
Pure inputs → outputs.

All pricing math lives here.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Dict, List, Optional, Tuple
from uuid import UUID, uuid4
import math


# =============================================================================
# AMENITY UPLIFT COMPUTATIONS
# =============================================================================

class AmenityType(str, Enum):
    """Amenity types that affect pricing."""
    POOL = "pool"
    POOL_HEATED = "pool_heated"
    HOT_TUB = "hot_tub"
    WATERFRONT = "waterfront"
    GULF_VIEW = "gulf_view"
    OCEAN_VIEW = "ocean_view"
    BAY_VIEW = "bay_view"
    LAKE_VIEW = "lake_view"
    BEACH_ACCESS_PRIVATE = "beach_access_private"
    BEACH_ACCESS_PUBLIC = "beach_access_public"
    DOCK = "dock"
    ELEVATOR = "elevator"
    GAME_ROOM = "game_room"
    HOME_THEATER = "home_theater"
    PET_FRIENDLY = "pet_friendly"


@dataclass
class AmenityUplift:
    """Uplift value for an amenity."""
    amenity_type: AmenityType
    base_uplift: float  # Base multiplier (e.g., 1.15 = +15%)
    confidence: float
    market_specific: bool = False  # Is this market-specific or generic?
    
    @property
    def percentage(self) -> float:
        """Get uplift as percentage."""
        return (self.base_uplift - 1.0) * 100


# Default amenity uplifts (market-agnostic)
DEFAULT_AMENITY_UPLIFTS: Dict[AmenityType, float] = {
    AmenityType.POOL: 1.08,               # +8%
    AmenityType.POOL_HEATED: 1.12,        # +12%
    AmenityType.HOT_TUB: 1.06,            # +6%
    AmenityType.WATERFRONT: 1.25,         # +25%
    AmenityType.GULF_VIEW: 1.20,          # +20%
    AmenityType.OCEAN_VIEW: 1.18,         # +18%
    AmenityType.BAY_VIEW: 1.12,           # +12%
    AmenityType.LAKE_VIEW: 1.10,          # +10%
    AmenityType.BEACH_ACCESS_PRIVATE: 1.15,  # +15%
    AmenityType.BEACH_ACCESS_PUBLIC: 1.05,   # +5%
    AmenityType.DOCK: 1.10,               # +10%
    AmenityType.ELEVATOR: 1.04,           # +4%
    AmenityType.GAME_ROOM: 1.05,          # +5%
    AmenityType.HOME_THEATER: 1.04,       # +4%
    AmenityType.PET_FRIENDLY: 1.08,       # +8%
}


def get_amenity_uplift(
    amenity_type: AmenityType,
    market_uplifts: Optional[Dict[AmenityType, float]] = None,
) -> AmenityUplift:
    """
    Get uplift for an amenity.
    
    Uses market-specific values if available, falls back to defaults.
    """
    if market_uplifts and amenity_type in market_uplifts:
        return AmenityUplift(
            amenity_type=amenity_type,
            base_uplift=market_uplifts[amenity_type],
            confidence=0.85,
            market_specific=True,
        )
    
    return AmenityUplift(
        amenity_type=amenity_type,
        base_uplift=DEFAULT_AMENITY_UPLIFTS.get(amenity_type, 1.0),
        confidence=0.70,
        market_specific=False,
    )


def compute_combined_amenity_uplift(
    amenities: List[AmenityType],
    market_uplifts: Optional[Dict[AmenityType, float]] = None,
) -> Tuple[float, float, List[AmenityUplift]]:
    """
    Compute combined uplift for multiple amenities.
    
    Amenities are multiplicative, not additive.
    
    Returns: (combined_uplift, confidence, list_of_uplifts)
    """
    if not amenities:
        return 1.0, 1.0, []
    
    combined = 1.0
    uplifts = []
    confidences = []
    
    for amenity_type in amenities:
        uplift = get_amenity_uplift(amenity_type, market_uplifts)
        combined *= uplift.base_uplift
        uplifts.append(uplift)
        confidences.append(uplift.confidence)
    
    avg_confidence = sum(confidences) / len(confidences)
    
    return combined, avg_confidence, uplifts


# =============================================================================
# SEASONALITY
# =============================================================================

@dataclass
class SeasonalityProfile:
    """Monthly seasonality multipliers."""
    monthly_multipliers: Dict[int, float]  # month (1-12) -> multiplier
    confidence: float
    source: str  # "market_historical", "operator_historical", "default"
    
    def get_multiplier(self, month: int) -> float:
        """Get multiplier for a month (1-12)."""
        return self.monthly_multipliers.get(month, 1.0)
    
    @property
    def peak_months(self) -> List[int]:
        """Get months with above-average rates."""
        avg = sum(self.monthly_multipliers.values()) / 12
        return [m for m, mult in self.monthly_multipliers.items() if mult > avg]


# Default seasonality for vacation markets (coastal)
DEFAULT_COASTAL_SEASONALITY: Dict[int, float] = {
    1: 0.70,   # January
    2: 0.75,   # February
    3: 0.95,   # March (spring break)
    4: 0.90,   # April
    5: 1.00,   # May
    6: 1.25,   # June (summer starts)
    7: 1.35,   # July (peak)
    8: 1.20,   # August
    9: 0.85,   # September
    10: 0.80,  # October
    11: 0.85,  # November (Thanksgiving)
    12: 0.90,  # December (holidays)
}

# Default seasonality for urban markets
DEFAULT_URBAN_SEASONALITY: Dict[int, float] = {
    1: 0.85,
    2: 0.90,
    3: 0.95,
    4: 1.00,
    5: 1.05,
    6: 1.10,
    7: 1.05,
    8: 0.95,
    9: 1.00,
    10: 1.05,
    11: 0.95,
    12: 0.85,
}


def get_default_seasonality(market_type: str = "coastal") -> SeasonalityProfile:
    """Get default seasonality profile."""
    if market_type == "urban":
        return SeasonalityProfile(
            monthly_multipliers=DEFAULT_URBAN_SEASONALITY,
            confidence=0.60,
            source="default",
        )
    return SeasonalityProfile(
        monthly_multipliers=DEFAULT_COASTAL_SEASONALITY,
        confidence=0.60,
        source="default",
    )


# =============================================================================
# OPERATOR PERFORMANCE DELTA
# =============================================================================

@dataclass
class OperatorDelta:
    """
    Operator's historical performance vs market.
    
    This is the key differentiator for operator-specific projections.
    """
    adr_delta_pct: float       # e.g., 0.12 = +12% vs market
    occupancy_delta_pct: float  # e.g., 0.07 = +7% vs market
    months_of_data: int
    property_count: int
    confidence: float
    
    @property
    def adr_multiplier(self) -> float:
        """Get ADR as multiplier (1.12 for +12%)."""
        return 1.0 + self.adr_delta_pct
    
    @property
    def occupancy_multiplier(self) -> float:
        """Get occupancy as multiplier."""
        return 1.0 + self.occupancy_delta_pct


def compute_operator_delta(
    portfolio_avg_adr: float,
    market_avg_adr: float,
    portfolio_avg_occupancy: float,
    market_avg_occupancy: float,
    months_of_data: int,
    property_count: int,
) -> OperatorDelta:
    """
    Compute operator performance delta.
    
    Pure calculation from portfolio vs market averages.
    """
    adr_delta = (portfolio_avg_adr - market_avg_adr) / market_avg_adr if market_avg_adr > 0 else 0
    occ_delta = (portfolio_avg_occupancy - market_avg_occupancy) / market_avg_occupancy if market_avg_occupancy > 0 else 0
    
    # Confidence based on data depth
    base_confidence = 0.40
    month_factor = min(months_of_data / 24, 1.0) * 0.30  # Up to +30% for 24+ months
    property_factor = min(property_count / 20, 1.0) * 0.30  # Up to +30% for 20+ properties
    confidence = min(base_confidence + month_factor + property_factor, 1.0)
    
    return OperatorDelta(
        adr_delta_pct=adr_delta,
        occupancy_delta_pct=occ_delta,
        months_of_data=months_of_data,
        property_count=property_count,
        confidence=confidence,
    )


def apply_operator_delta_conservatively(
    delta: OperatorDelta,
    application_rate: float = 0.5,  # Apply 50% of observed delta
) -> Tuple[float, float]:
    """
    Apply operator delta conservatively.
    
    We don't apply 100% of observed delta - that would be overconfident.
    
    Returns: (adr_delta_to_apply, occupancy_delta_to_apply)
    """
    adr_apply = delta.adr_delta_pct * application_rate * delta.confidence
    occ_apply = delta.occupancy_delta_pct * application_rate * delta.confidence
    
    return adr_apply, occ_apply


# =============================================================================
# NEW LISTING ADJUSTMENT
# =============================================================================

def compute_new_listing_penalty(
    months_active: int,
    ramp_months: int = 6,
) -> float:
    """
    Compute occupancy penalty for new listings.
    
    New listings typically underperform established ones.
    
    Returns multiplier (e.g., 0.85 = 15% penalty).
    """
    if months_active >= ramp_months:
        return 1.0
    
    # Linear ramp from 70% to 100% over ramp_months
    progress = months_active / ramp_months
    return 0.70 + (0.30 * progress)


# =============================================================================
# DISCOUNT CALCULATION
# =============================================================================

@dataclass
class DiscountResult:
    """Result of discount calculation."""
    recommended_discount: float
    max_allowed_discount: float
    reasoning: str
    confidence: float


def compute_recommended_discount(
    days_until_arrival: int,
    current_occupancy: float,
    target_occupancy: float = 0.65,
    elasticity: float = 1.2,
    max_discount: float = 0.30,
) -> DiscountResult:
    """
    Compute recommended discount based on booking window and occupancy.
    
    Pure calculation - no side effects.
    """
    # Urgency factor (closer = more urgent)
    if days_until_arrival <= 0:
        urgency = 1.0
    elif days_until_arrival <= 7:
        urgency = 0.9
    elif days_until_arrival <= 14:
        urgency = 0.7
    elif days_until_arrival <= 30:
        urgency = 0.5
    else:
        urgency = 0.3
    
    # Occupancy gap
    gap = max(0, target_occupancy - current_occupancy)
    
    # Base discount from gap and urgency
    base_discount = gap * urgency * elasticity
    
    # Cap at max
    recommended = min(base_discount, max_discount)
    
    # Reasoning
    if gap <= 0:
        reasoning = "At or above target occupancy - no discount needed"
    elif urgency >= 0.8:
        reasoning = f"High urgency ({days_until_arrival} days out) with {gap:.1%} occupancy gap"
    else:
        reasoning = f"Moderate urgency with {gap:.1%} occupancy gap"
    
    return DiscountResult(
        recommended_discount=recommended,
        max_allowed_discount=max_discount,
        reasoning=reasoning,
        confidence=0.75 if days_until_arrival > 7 else 0.85,
    )


# =============================================================================
# PRICING SENSITIVITY ANALYSIS
# =============================================================================

@dataclass
class PricingScenario:
    """A single pricing scenario result."""
    rate_adjustment: float      # e.g., -0.10 = -10%
    adjusted_adr: float
    projected_occupancy: float
    nights_booked: int
    projected_revenue: float


@dataclass
class SensitivityResult:
    """Result of pricing sensitivity analysis."""
    base_adr: float
    base_occupancy: float
    elasticity: float
    scenarios: List[PricingScenario]
    optimal_adjustment: float
    optimal_revenue: float
    analysis_days: int
    
    def get_optimal_scenario(self) -> PricingScenario:
        """Get the revenue-maximizing scenario."""
        return max(self.scenarios, key=lambda s: s.projected_revenue)


def compute_pricing_sensitivity(
    base_adr: float,
    base_occupancy: float,
    analysis_days: int,
    rate_adjustments: Optional[List[float]] = None,
    elasticity: float = -1.5,
) -> SensitivityResult:
    """
    Compute pricing sensitivity analysis.
    
    Pure function - no IO.
    
    Args:
        base_adr: Starting average daily rate
        base_occupancy: Starting occupancy rate (0-1)
        analysis_days: Number of days in analysis period
        rate_adjustments: Rate adjustment factors (e.g., [-0.20, -0.10, 0, 0.10, 0.20])
        elasticity: Price elasticity of demand (negative, e.g., -1.5)
        
    Returns:
        SensitivityResult with scenarios and optimal point
    """
    if rate_adjustments is None:
        rate_adjustments = [-0.20, -0.10, -0.05, 0, 0.05, 0.10, 0.20]
    
    scenarios = []
    
    for adjustment in rate_adjustments:
        # Adjust ADR
        adjusted_adr = base_adr * (1 + adjustment)
        
        # Calculate occupancy change based on elasticity
        # elasticity = % change in demand / % change in price
        occupancy_change = adjustment * elasticity
        adjusted_occupancy = base_occupancy * (1 + occupancy_change)
        
        # Clamp occupancy to valid range
        adjusted_occupancy = max(0.10, min(0.98, adjusted_occupancy))
        
        # Calculate bookings and revenue
        nights_booked = int(analysis_days * adjusted_occupancy)
        projected_revenue = adjusted_adr * nights_booked
        
        scenarios.append(PricingScenario(
            rate_adjustment=adjustment,
            adjusted_adr=adjusted_adr,
            projected_occupancy=adjusted_occupancy,
            nights_booked=nights_booked,
            projected_revenue=projected_revenue,
        ))
    
    # Find optimal
    optimal = max(scenarios, key=lambda s: s.projected_revenue)
    
    return SensitivityResult(
        base_adr=base_adr,
        base_occupancy=base_occupancy,
        elasticity=elasticity,
        scenarios=scenarios,
        optimal_adjustment=optimal.rate_adjustment,
        optimal_revenue=optimal.projected_revenue,
        analysis_days=analysis_days,
    )


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Amenities
    "AmenityType",
    "AmenityUplift",
    "DEFAULT_AMENITY_UPLIFTS",
    "get_amenity_uplift",
    "compute_combined_amenity_uplift",
    
    # Seasonality
    "SeasonalityProfile",
    "DEFAULT_COASTAL_SEASONALITY",
    "DEFAULT_URBAN_SEASONALITY",
    "get_default_seasonality",
    
    # Operator delta
    "OperatorDelta",
    "compute_operator_delta",
    "apply_operator_delta_conservatively",
    
    # New listing
    "compute_new_listing_penalty",
    
    # Discount
    "DiscountResult",
    "compute_recommended_discount",
    
    # Sensitivity
    "PricingScenario",
    "SensitivityResult",
    "compute_pricing_sensitivity",
]
