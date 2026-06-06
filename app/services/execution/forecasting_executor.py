"""
Execution: Forecasting Executor.

Thin wrapper around domain forecasting logic.
Translates DTOs/payloads → domain inputs → domain outputs.

Does NOT:
- Make decisions about what to run
- Handle retries/fallbacks
- Manage async concerns
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from uuid import UUID

from app.domain.pricing import AmenityType, SeasonalityProfile
from app.domain.forecasting import (
    PropertyInputs,
    MarketInputs,
    CompSet,
    OperatorInputs,
    AnnualProjection,
    MonthlyProjection,
    generate_projection,
    ENGINE_VERSION,
)


# =============================================================================
# PAYLOADS (DTOs for execution)
# =============================================================================

@dataclass
class PropertyPayload:
    """Input property data."""
    bedrooms: int
    bathrooms: float
    property_type: str = "single_family"
    sqft: Optional[int] = None
    amenities: List[str] = field(default_factory=list)  # Amenity type values
    is_new_listing: bool = False
    months_active: int = 12


@dataclass
class MarketPayload:
    """Input market data."""
    market_id: str
    market_name: str = ""
    market_type: str = "coastal"
    median_adr_by_bedroom: Dict[int, float] = field(default_factory=dict)
    median_occupancy_by_bedroom: Dict[int, float] = field(default_factory=dict)
    pool_is_expected: bool = False
    amenity_uplifts: Optional[Dict[str, float]] = None


@dataclass
class CompSetPayload:
    """Input comparable set data."""
    source: str  # "internal" or "external"
    comp_count: int
    avg_adr: float
    avg_occupancy: float
    avg_similarity_score: float
    data_coverage_pct: float
    months_of_data: int = 12
    avg_annual_revenue: Optional[float] = None


@dataclass
class OperatorPayload:
    """Input operator data."""
    company_id: str
    portfolio_avg_adr: float
    portfolio_avg_occupancy: float
    market_avg_adr: float
    market_avg_occupancy: float
    property_count: int
    months_of_data: int


@dataclass
class ProjectionPayload:
    """Complete projection request."""
    property: PropertyPayload
    market: MarketPayload
    internal_comps: Optional[CompSetPayload] = None
    external_comps: Optional[CompSetPayload] = None
    operator: Optional[OperatorPayload] = None
    commission_rate: float = 0.20


# =============================================================================
# FORECASTING EXECUTOR
# =============================================================================

class ForecastingExecutor:
    """
    Executes forecasting domain logic.
    
    Thin wrapper - translates DTOs to domain calls.
    No branching logic. No scheduling. No async.
    """
    
    @property
    def engine_version(self) -> str:
        """Get the projection engine version."""
        return ENGINE_VERSION
    
    def generate_projection(self, payload: ProjectionPayload) -> AnnualProjection:
        """Generate annual revenue projection."""
        # Translate property payload
        property_inputs = self._translate_property(payload.property)
        
        # Translate market payload
        market_inputs = self._translate_market(payload.market)
        
        # Translate optional comp sets
        internal_comps = self._translate_compset(payload.internal_comps) if payload.internal_comps else None
        external_comps = self._translate_compset(payload.external_comps) if payload.external_comps else None
        
        # Translate optional operator
        operator_inputs = self._translate_operator(payload.operator) if payload.operator else None
        
        # Call domain function
        return generate_projection(
            property_inputs=property_inputs,
            market_inputs=market_inputs,
            internal_comps=internal_comps,
            external_comps=external_comps,
            operator_inputs=operator_inputs,
            commission_rate=payload.commission_rate,
        )
    
    def _translate_property(self, payload: PropertyPayload) -> PropertyInputs:
        """Translate property payload to domain input."""
        amenities = [
            AmenityType(a) for a in payload.amenities 
            if a in [e.value for e in AmenityType]
        ]
        
        return PropertyInputs(
            bedrooms=payload.bedrooms,
            bathrooms=payload.bathrooms,
            property_type=payload.property_type,
            sqft=payload.sqft,
            amenities=amenities,
            is_new_listing=payload.is_new_listing,
            months_active=payload.months_active,
        )
    
    def _translate_market(self, payload: MarketPayload) -> MarketInputs:
        """Translate market payload to domain input."""
        amenity_uplifts = None
        if payload.amenity_uplifts:
            amenity_uplifts = {
                AmenityType(k): v 
                for k, v in payload.amenity_uplifts.items()
                if k in [e.value for e in AmenityType]
            }
        
        # Handle market_id - could be UUID string or arbitrary string
        try:
            market_uuid = UUID(payload.market_id)
        except (ValueError, AttributeError):
            # Generate deterministic UUID from string
            import hashlib
            market_uuid = UUID(hashlib.md5(payload.market_id.encode()).hexdigest())
        
        return MarketInputs(
            market_id=market_uuid,
            market_name=payload.market_name,
            market_type=payload.market_type,
            median_adr_by_bedroom=payload.median_adr_by_bedroom,
            median_occupancy_by_bedroom=payload.median_occupancy_by_bedroom,
            pool_is_expected=payload.pool_is_expected,
            amenity_uplifts=amenity_uplifts,
        )
    
    def _translate_compset(self, payload: CompSetPayload) -> CompSet:
        """Translate comp set payload to domain input."""
        return CompSet(
            source=payload.source,
            comp_count=payload.comp_count,
            avg_adr=payload.avg_adr,
            avg_occupancy=payload.avg_occupancy,
            avg_similarity_score=payload.avg_similarity_score,
            data_coverage_pct=payload.data_coverage_pct,
            months_of_data=payload.months_of_data,
            avg_annual_revenue=payload.avg_annual_revenue,
        )
    
    def _translate_operator(self, payload: OperatorPayload) -> OperatorInputs:
        """Translate operator payload to domain input."""
        # Handle company_id - could be UUID string or arbitrary string
        try:
            company_uuid = UUID(payload.company_id)
        except (ValueError, AttributeError):
            import hashlib
            company_uuid = UUID(hashlib.md5(payload.company_id.encode()).hexdigest())
        
        return OperatorInputs(
            company_id=company_uuid,
            portfolio_avg_adr=payload.portfolio_avg_adr,
            portfolio_avg_occupancy=payload.portfolio_avg_occupancy,
            market_avg_adr=payload.market_avg_adr,
            market_avg_occupancy=payload.market_avg_occupancy,
            property_count=payload.property_count,
            months_of_data=payload.months_of_data,
        )


# =============================================================================
# SINGLETON
# =============================================================================

_executor: Optional[ForecastingExecutor] = None


def get_forecasting_executor() -> ForecastingExecutor:
    """Get forecasting executor singleton."""
    global _executor
    if _executor is None:
        _executor = ForecastingExecutor()
    return _executor


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Payloads
    "PropertyPayload",
    "MarketPayload",
    "CompSetPayload",
    "OperatorPayload",
    "ProjectionPayload",
    
    # Executor
    "ForecastingExecutor",
    "get_forecasting_executor",
]
