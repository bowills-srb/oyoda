"""
Execution: Pricing Executor.

Thin wrapper around domain pricing logic.
Translates DTOs/payloads → domain inputs → domain outputs.

Does NOT:
- Make decisions about what to run
- Handle retries/fallbacks
- Manage async concerns
"""

from dataclasses import dataclass
from typing import Dict, List, Optional
from uuid import UUID

from app.domain.pricing import (
    AmenityType,
    AmenityUplift,
    SeasonalityProfile,
    OperatorDelta,
    DiscountResult,
    compute_combined_amenity_uplift,
    compute_operator_delta,
    apply_operator_delta_conservatively,
    compute_new_listing_penalty,
    compute_recommended_discount,
    get_default_seasonality,
)


# =============================================================================
# PAYLOADS (DTOs for execution)
# =============================================================================

@dataclass
class AmenityUpliftPayload:
    """Input for amenity uplift calculation."""
    amenities: List[str]  # Amenity type values
    market_uplifts: Optional[Dict[str, float]] = None


@dataclass
class AmenityUpliftResult:
    """Output from amenity uplift calculation."""
    combined_multiplier: float
    confidence: float
    uplifts: List[AmenityUplift]


@dataclass
class OperatorDeltaPayload:
    """Input for operator delta calculation."""
    portfolio_avg_adr: float
    market_avg_adr: float
    portfolio_avg_occupancy: float
    market_avg_occupancy: float
    months_of_data: int
    property_count: int


@dataclass
class DiscountPayload:
    """Input for discount calculation."""
    days_until_arrival: int
    current_occupancy: float
    target_occupancy: float = 0.65
    elasticity: float = 1.2
    max_discount: float = 0.30


# =============================================================================
# PRICING EXECUTOR
# =============================================================================

class PricingExecutor:
    """
    Executes pricing domain logic.
    
    Thin wrapper - translates DTOs to domain calls.
    No branching logic. No scheduling. No async.
    """
    
    def calculate_amenity_uplift(self, payload: AmenityUpliftPayload) -> AmenityUpliftResult:
        """Calculate combined amenity uplift."""
        # Translate string amenities to enum
        amenities = [AmenityType(a) for a in payload.amenities if a in [e.value for e in AmenityType]]
        
        # Translate market uplifts if provided
        market_uplifts = None
        if payload.market_uplifts:
            market_uplifts = {
                AmenityType(k): v 
                for k, v in payload.market_uplifts.items() 
                if k in [e.value for e in AmenityType]
            }
        
        # Call domain function
        combined, confidence, uplifts = compute_combined_amenity_uplift(amenities, market_uplifts)
        
        return AmenityUpliftResult(
            combined_multiplier=combined,
            confidence=confidence,
            uplifts=uplifts,
        )
    
    def calculate_operator_delta(self, payload: OperatorDeltaPayload) -> OperatorDelta:
        """Calculate operator performance delta."""
        return compute_operator_delta(
            portfolio_avg_adr=payload.portfolio_avg_adr,
            market_avg_adr=payload.market_avg_adr,
            portfolio_avg_occupancy=payload.portfolio_avg_occupancy,
            market_avg_occupancy=payload.market_avg_occupancy,
            months_of_data=payload.months_of_data,
            property_count=payload.property_count,
        )
    
    def apply_operator_delta(
        self, 
        delta: OperatorDelta, 
        application_rate: float = 0.5
    ) -> tuple[float, float]:
        """Apply operator delta conservatively."""
        return apply_operator_delta_conservatively(delta, application_rate)
    
    def calculate_new_listing_penalty(
        self, 
        months_active: int, 
        ramp_months: int = 6
    ) -> float:
        """Calculate occupancy penalty for new listings."""
        return compute_new_listing_penalty(months_active, ramp_months)
    
    def calculate_discount(self, payload: DiscountPayload) -> DiscountResult:
        """Calculate recommended discount."""
        return compute_recommended_discount(
            days_until_arrival=payload.days_until_arrival,
            current_occupancy=payload.current_occupancy,
            target_occupancy=payload.target_occupancy,
            elasticity=payload.elasticity,
            max_discount=payload.max_discount,
        )
    
    def get_seasonality(self, market_type: str = "coastal") -> SeasonalityProfile:
        """Get default seasonality profile."""
        return get_default_seasonality(market_type)
    
    def calculate_sensitivity(self, payload: "SensitivityPayload") -> "SensitivityResult":
        """Calculate pricing sensitivity analysis."""
        from app.domain.pricing import compute_pricing_sensitivity
        
        return compute_pricing_sensitivity(
            base_adr=payload.base_adr,
            base_occupancy=payload.base_occupancy,
            analysis_days=payload.analysis_days,
            rate_adjustments=payload.rate_adjustments,
            elasticity=payload.elasticity,
        )


# =============================================================================
# SENSITIVITY PAYLOAD
# =============================================================================

@dataclass
class SensitivityPayload:
    """Input for pricing sensitivity analysis."""
    base_adr: float
    base_occupancy: float
    analysis_days: int
    rate_adjustments: Optional[List[float]] = None
    elasticity: float = -1.5


# Import SensitivityResult from domain for re-export
from app.domain.pricing import SensitivityResult


# =============================================================================
# SINGLETON
# =============================================================================

_executor: Optional[PricingExecutor] = None


def get_pricing_executor() -> PricingExecutor:
    """Get pricing executor singleton."""
    global _executor
    if _executor is None:
        _executor = PricingExecutor()
    return _executor


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Payloads
    "AmenityUpliftPayload",
    "AmenityUpliftResult",
    "OperatorDeltaPayload",
    "DiscountPayload",
    "SensitivityPayload",
    
    # Results (re-exported from domain)
    "SensitivityResult",
    
    # Executor
    "PricingExecutor",
    "get_pricing_executor",
]
