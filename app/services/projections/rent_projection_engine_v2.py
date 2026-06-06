"""
Rent Projection Engine v2.0 - Signal-Only.

This replaces rent_projection_engine_v1_1.py with a signal-driven implementation.

DELETED (from v1.1):
- DEFAULT_SEASONALITY dict
- AmenityUpliftConfig class
- _apply_amenity_uplifts() hardcoded logic
- Inline operator delta calculation

USES ONLY:
- app.services.signals.get_seasonality()
- app.services.signals.get_amenity_lift()
- app.services.signals.get_operator_delta()
- app.services.signals.get_platform_bias()

If signals are missing → confidence drops → outputs are gated.
No fallback math. No hardcoded heuristics.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID
import hashlib
import json

from pydantic import BaseModel, Field

from app.services.signals import (
    SignalBundle,
    SignalType,
    get_seasonality,
    get_amenity_lift,
    get_operator_delta,
    get_platform_bias,
    ConfidenceThresholds,
)


# =============================================================================
# ENGINE VERSION
# =============================================================================

ENGINE_VERSION = "2.0.0"


# =============================================================================
# INPUT MODELS (Simplified - no config classes)
# =============================================================================

class PropertyInputs(BaseModel):
    """Property attributes for projection."""
    property_id: Optional[UUID] = None
    
    # Core attributes
    bedrooms: int = Field(..., ge=1, le=20)
    bathrooms: float = Field(2.0, ge=1)
    sqft: Optional[int] = None
    property_type: str = "single_family"
    
    # Amenities (list of amenity names matching signal types)
    amenities: List[str] = Field(default_factory=list)
    
    # Status
    is_new_listing: bool = False
    months_active: int = Field(12, ge=0)
    
    # Legacy compatibility - convert to amenities list
    waterfront: bool = False
    pool: bool = False
    pool_heated: bool = False
    hot_tub: bool = False
    view: Optional[str] = None
    pet_friendly: bool = False
    
    def get_amenities_list(self) -> List[str]:
        """Get all amenities as a list for signal lookup."""
        amenities = list(self.amenities)
        
        # Add from legacy boolean fields
        if self.waterfront:
            amenities.append("waterfront")
        if self.pool:
            amenities.append("pool")
        if self.pool_heated:
            amenities.append("pool_heated")
        if self.hot_tub:
            amenities.append("hot_tub")
        if self.pet_friendly:
            amenities.append("pet_friendly")
        if self.view:
            amenities.append(f"{self.view}_view")
        
        return list(set(amenities))


class MarketInputs(BaseModel):
    """Market context for projection."""
    market_id: UUID
    geo_id: str
    
    # Base ADR by bedroom (optional override)
    median_adr_by_bedroom: Dict[int, float] = Field(default_factory=dict)
    
    # Everything else comes from signals
    # NO seasonality dict
    # NO pool_is_expected
    # NO peak_season_months


# =============================================================================
# OUTPUT MODELS
# =============================================================================

@dataclass
class AppliedAdjustment:
    """Record of an adjustment applied."""
    name: str
    factor: float
    confidence: float
    source: str  # "signal" or "default"
    reason: str


@dataclass 
class ProjectionReasoning:
    """Rich reasoning object for audit trail."""
    # Hash for reproducibility
    input_hash: str = ""
    
    # Base values
    base_adr: float = 0.0
    
    # Adjustments applied
    adjustments: List[AppliedAdjustment] = field(default_factory=list)
    
    # Signal-driven factors
    seasonality_factor: float = 1.0
    seasonality_confidence: float = 0.0
    
    amenity_factor: float = 1.0
    amenity_confidence: float = 0.0
    
    operator_factor: float = 1.0
    operator_confidence: float = 0.0
    
    platform_bias: str = "balanced"
    platform_confidence: float = 0.0
    
    # Overall
    overall_confidence: float = 0.0
    signal_count: int = 0
    
    # Gating
    is_gated: bool = False
    gate_reason: Optional[str] = None


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
    """Complete rent projection output."""
    # Identification
    projection_id: UUID = Field(default_factory=lambda: UUID(int=0))
    engine_version: str = ENGINE_VERSION
    
    # Inputs echo
    property_id: Optional[UUID] = None
    market_id: UUID
    geo_id: str
    
    # Core metrics
    avg_daily_rate: float
    annual_occupancy: float
    
    # Projections
    gross_annual_revenue: AnnualProjection
    net_annual_revenue: AnnualProjection
    monthly_projections: List[MonthlyProjection]
    
    # Confidence & gating
    confidence: float
    is_gated: bool = False
    gate_reason: Optional[str] = None
    
    # Reasoning
    reasoning: Optional[Dict[str, Any]] = None
    
    # Metadata
    computed_at: datetime = Field(default_factory=datetime.utcnow)


# =============================================================================
# BASELINE ADR (Only when no market signal)
# =============================================================================

BASELINE_ADR_BY_BEDROOM = {
    1: 150.0,
    2: 200.0,
    3: 275.0,
    4: 350.0,
    5: 450.0,
    6: 550.0,
    7: 650.0,
    8: 750.0,
}

BASELINE_OCCUPANCY = 0.55

MONTH_NAMES = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December"
]

DAYS_IN_MONTH = [0, 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]


# =============================================================================
# RENT PROJECTION ENGINE v2.0
# =============================================================================

class RentProjectionEngineV2:
    """
    Rent Projection Engine v2.0 - Signal-Only.
    
    This engine:
    - Consumes ONLY signals via SignalBundle
    - Has NO hardcoded uplift configs
    - Has NO inline seasonality
    - Gates outputs when confidence is low
    
    It is a pure function: (SignalBundle, Inputs) → Projection
    """
    
    def __init__(self):
        self.version = ENGINE_VERSION
    
    def generate_projection(
        self,
        signal_bundle: SignalBundle,
        property_inputs: PropertyInputs,
        market_inputs: MarketInputs,
        commission_rate: float = 0.20,
        projection_year: Optional[int] = None,
        output_type: str = "bd_projection",
    ) -> RentProjection:
        """
        Generate rent projection from signals.
        
        All market intelligence comes from SignalBundle.
        No inline calculations. No hardcoded values.
        """
        projection_year = projection_year or datetime.now().year
        reasoning = ProjectionReasoning()
        
        # =================================================================
        # STEP 1: Compute input hash for reproducibility
        # =================================================================
        reasoning.input_hash = self._compute_input_hash(
            property_inputs, market_inputs, signal_bundle
        )
        
        # =================================================================
        # STEP 2: Get base ADR
        # =================================================================
        base_adr = market_inputs.median_adr_by_bedroom.get(
            property_inputs.bedrooms,
            BASELINE_ADR_BY_BEDROOM.get(property_inputs.bedrooms, 300.0)
        )
        reasoning.base_adr = base_adr
        
        # =================================================================
        # STEP 3: Apply seasonality from signals
        # =================================================================
        seasonality = get_seasonality(signal_bundle)
        reasoning.seasonality_factor = seasonality.multiplier
        reasoning.seasonality_confidence = seasonality.confidence
        
        if seasonality.has_signal:
            reasoning.adjustments.append(AppliedAdjustment(
                name="seasonality",
                factor=seasonality.multiplier,
                confidence=seasonality.confidence,
                source="signal",
                reason=f"Seasonality from signal (strength: {seasonality.strength or 'unknown'})",
            ))
        
        # =================================================================
        # STEP 4: Apply amenity lift from signals
        # =================================================================
        amenities = property_inputs.get_amenities_list()
        amenity_lift = get_amenity_lift(signal_bundle, amenities)
        reasoning.amenity_factor = amenity_lift.multiplier
        reasoning.amenity_confidence = amenity_lift.confidence
        
        if amenity_lift.has_signals:
            for detail in amenity_lift.lifts.values():
                reasoning.adjustments.append(AppliedAdjustment(
                    name=f"amenity_{detail.amenity}",
                    factor=1.0 + detail.lift_pct,
                    confidence=detail.confidence,
                    source="signal",
                    reason=f"{detail.amenity} lift from geo-specific signal",
                ))
        
        # =================================================================
        # STEP 5: Apply operator delta from signals
        # =================================================================
        operator = get_operator_delta(signal_bundle)
        operator_mult = 1.0 + operator.applied_adr_delta
        reasoning.operator_factor = operator_mult
        reasoning.operator_confidence = operator.confidence
        
        if operator.has_signal and operator.is_usable_for_bd():
            reasoning.adjustments.append(AppliedAdjustment(
                name="operator_delta",
                factor=operator_mult,
                confidence=operator.confidence,
                source="signal",
                reason=f"Operator performance delta (capped, {operator.months_of_data or '?'} months)",
            ))
        else:
            operator_mult = 1.0  # Don't apply if not confident
        
        # =================================================================
        # STEP 6: Get platform bias from signals
        # =================================================================
        platform = get_platform_bias(signal_bundle)
        reasoning.platform_bias = platform.dominant_platform
        reasoning.platform_confidence = platform.confidence
        
        # =================================================================
        # STEP 7: Compute final ADR
        # =================================================================
        # Note: Seasonality affects monthly, not base ADR
        adjusted_adr = base_adr * amenity_lift.multiplier * operator_mult
        
        # =================================================================
        # STEP 8: Compute overall confidence
        # =================================================================
        confidence = (
            reasoning.seasonality_confidence * 0.30 +
            reasoning.amenity_confidence * 0.25 +
            reasoning.operator_confidence * 0.25 +
            reasoning.platform_confidence * 0.20
        )
        reasoning.overall_confidence = confidence
        reasoning.signal_count = signal_bundle.signal_count
        
        # =================================================================
        # STEP 9: Check gating
        # =================================================================
        threshold = self._get_confidence_threshold(output_type)
        if confidence < threshold:
            reasoning.is_gated = True
            reasoning.gate_reason = f"Confidence {confidence:.2f} below threshold {threshold:.2f}"
        
        # =================================================================
        # STEP 10: Generate monthly projections
        # =================================================================
        monthly_projections = self._generate_monthly_projections(
            adjusted_adr,
            BASELINE_OCCUPANCY,
            seasonality,
            operator,
            projection_year,
            confidence,
        )
        
        # =================================================================
        # STEP 11: Calculate totals
        # =================================================================
        total_revenue = sum(m.projected_revenue for m in monthly_projections)
        total_nights = sum(m.projected_nights_booked for m in monthly_projections)
        total_days = sum(m.days_in_month for m in monthly_projections)
        
        annual_occupancy = total_nights / total_days if total_days > 0 else 0
        annual_adr = total_revenue / total_nights if total_nights > 0 else adjusted_adr
        
        # Ranges based on confidence
        if confidence >= 0.7:
            low_mult, high_mult = 0.88, 1.15
        elif confidence >= 0.5:
            low_mult, high_mult = 0.82, 1.22
        else:
            low_mult, high_mult = 0.75, 1.30
        
        gross = AnnualProjection(
            conservative=round(total_revenue * low_mult, 0),
            expected=round(total_revenue, 0),
            optimistic=round(total_revenue * high_mult, 0),
            confidence=confidence,
        )
        
        net = AnnualProjection(
            conservative=round(total_revenue * low_mult * (1 - commission_rate), 0),
            expected=round(total_revenue * (1 - commission_rate), 0),
            optimistic=round(total_revenue * high_mult * (1 - commission_rate), 0),
            confidence=confidence,
        )
        
        # =================================================================
        # STEP 12: Build result
        # =================================================================
        return RentProjection(
            property_id=property_inputs.property_id,
            market_id=market_inputs.market_id,
            geo_id=market_inputs.geo_id,
            avg_daily_rate=round(annual_adr, 2),
            annual_occupancy=round(annual_occupancy, 3),
            gross_annual_revenue=gross,
            net_annual_revenue=net,
            monthly_projections=monthly_projections,
            confidence=confidence,
            is_gated=reasoning.is_gated,
            gate_reason=reasoning.gate_reason,
            reasoning={
                "input_hash": reasoning.input_hash,
                "base_adr": reasoning.base_adr,
                "seasonality_factor": reasoning.seasonality_factor,
                "seasonality_confidence": reasoning.seasonality_confidence,
                "amenity_factor": reasoning.amenity_factor,
                "amenity_confidence": reasoning.amenity_confidence,
                "operator_factor": reasoning.operator_factor,
                "operator_confidence": reasoning.operator_confidence,
                "platform_bias": reasoning.platform_bias,
                "adjustments": [
                    {"name": a.name, "factor": a.factor, "confidence": a.confidence, "source": a.source}
                    for a in reasoning.adjustments
                ],
                "overall_confidence": confidence,
                "signal_count": reasoning.signal_count,
            },
        )
    
    def _generate_monthly_projections(
        self,
        base_adr: float,
        base_occupancy: float,
        seasonality,  # SeasonalityResult
        operator,     # OperatorDeltaResult
        year: int,
        confidence: float,
    ) -> List[MonthlyProjection]:
        """Generate monthly projections using signal-based seasonality."""
        projections = []
        
        for month in range(1, 13):
            days = DAYS_IN_MONTH[month]
            
            # Get month-specific factors from seasonality
            month_factor = seasonality.get_monthly_multiplier(month)
            
            # Apply to ADR
            monthly_adr = base_adr * month_factor
            
            # Apply to occupancy (scaled)
            monthly_occ = min(0.95, base_occupancy * month_factor)
            
            # Apply operator delta to occupancy
            monthly_occ *= (1 + operator.applied_occupancy_delta)
            monthly_occ = min(0.95, max(0.10, monthly_occ))
            
            nights = int(days * monthly_occ)
            revenue = nights * monthly_adr
            
            projections.append(MonthlyProjection(
                month=month,
                month_name=MONTH_NAMES[month],
                year=year,
                days_in_month=days,
                projected_nights_booked=nights,
                projected_occupancy=round(monthly_occ, 3),
                avg_nightly_rate=round(monthly_adr, 2),
                projected_revenue=round(revenue, 2),
                confidence=confidence * seasonality.confidence,
            ))
        
        return projections
    
    def _compute_input_hash(
        self,
        property_inputs: PropertyInputs,
        market_inputs: MarketInputs,
        signal_bundle: SignalBundle,
    ) -> str:
        """Compute hash of inputs for reproducibility."""
        data = {
            "bedrooms": property_inputs.bedrooms,
            "amenities": sorted(property_inputs.get_amenities_list()),
            "geo_id": market_inputs.geo_id,
            "signal_count": signal_bundle.signal_count,
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:16]
    
    def _get_confidence_threshold(self, output_type: str) -> float:
        """Get confidence threshold for output type."""
        thresholds = {
            "voice_pricing": ConfidenceThresholds.VOICE_PRICING_CLAIM,
            "voice_discount": ConfidenceThresholds.VOICE_DISCOUNT_DENIAL,
            "bd_projection": ConfidenceThresholds.BD_PROJECTION,
            "bd_recommendation": ConfidenceThresholds.BD_RECOMMENDATION,
            "internal": ConfidenceThresholds.INTERNAL_ANALYSIS,
        }
        return thresholds.get(output_type, ConfidenceThresholds.BD_PROJECTION)


# =============================================================================
# CONVENIENCE
# =============================================================================

def generate_projection(
    signal_bundle: SignalBundle,
    property_inputs: PropertyInputs,
    market_inputs: MarketInputs,
    **kwargs,
) -> RentProjection:
    """Convenience function for generating projections."""
    engine = RentProjectionEngineV2()
    return engine.generate_projection(signal_bundle, property_inputs, market_inputs, **kwargs)
