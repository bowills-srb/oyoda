"""
Analytics Engine v3.0.0 - Pure Signal Consumer.

Phase 6 of Master Refactor Plan:
The analytics engine is a DETERMINISTIC FUNCTION of (SignalBundle → Decision)

This engine:
- Does ZERO detection
- Does ZERO scraping
- Does ZERO inference outside signals
- Is a pure function: SignalBundle → AnalyticsResult

This is where AirDNA cannot follow you.

Usage:
    from app.services.analytics.engine import AnalyticsEngine
    
    engine = AnalyticsEngine()
    result = engine.compute_adr(signal_bundle, property_config)
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from app.services.signals.signal_contract import (
    SignalBundle,
    SignalType,
    ConfidenceThresholds,
    is_confidence_sufficient,
)
from app.services.signals.seasonality import get_seasonality, SeasonalityResult
from app.services.signals.platform import get_platform_bias, PlatformDominanceResult
from app.services.signals.amenity import get_amenity_lift, AmenityLiftResult
from app.services.signals.operator import get_operator_delta, OperatorDeltaResult


# =============================================================================
# ENGINE VERSION
# =============================================================================

ENGINE_VERSION = "3.0.0"  # Pure signal consumer


# =============================================================================
# OUTPUT MODELS
# =============================================================================

class OutputGateStatus(str, Enum):
    """Status of output gating."""
    ALLOWED = "allowed"
    GATED_LOW_CONFIDENCE = "gated_low_confidence"
    GATED_MISSING_SIGNALS = "gated_missing_signals"
    GATED_POLICY = "gated_policy"


@dataclass
class GatingInfo:
    """Information about output gating."""
    status: OutputGateStatus
    reason: Optional[str] = None
    required_confidence: float = 0.0
    actual_confidence: float = 0.0
    missing_signals: List[SignalType] = field(default_factory=list)


@dataclass
class ADRResult:
    """Result of ADR computation."""
    # Core output
    base_adr: float
    adjusted_adr: float
    final_adr: float
    
    # Range (based on confidence)
    low_adr: float
    high_adr: float
    
    # Breakdown
    seasonality_multiplier: float
    amenity_multiplier: float
    operator_multiplier: float
    platform_bias: str
    
    # Confidence
    confidence: float
    
    # Gating
    gating: GatingInfo = None
    
    # Component confidences
    seasonality_confidence: float = 0.0
    amenity_confidence: float = 0.0
    operator_confidence: float = 0.0
    platform_confidence: float = 0.0
    
    # Audit trail
    engine_version: str = ENGINE_VERSION
    computed_at: datetime = field(default_factory=datetime.utcnow)
    signal_count: int = 0


@dataclass
class OccupancyResult:
    """Result of occupancy computation."""
    base_occupancy: float
    adjusted_occupancy: float
    final_occupancy: float
    
    low_occupancy: float
    high_occupancy: float
    
    seasonality_factor: float
    momentum_factor: float
    operator_factor: float
    
    confidence: float
    gating: GatingInfo = None
    
    engine_version: str = ENGINE_VERSION
    computed_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class RevenueProjectionResult:
    """Result of revenue projection."""
    adr_result: ADRResult
    occupancy_result: OccupancyResult
    
    # Annual projections
    gross_revenue_low: float
    gross_revenue_expected: float
    gross_revenue_high: float
    
    # Monthly breakdown
    monthly_projections: List[Dict[str, Any]] = field(default_factory=list)
    
    # Confidence
    confidence: float = 0.0
    gating: GatingInfo = None
    
    engine_version: str = ENGINE_VERSION
    computed_at: datetime = field(default_factory=datetime.utcnow)


@dataclass 
class DiscountEvaluationResult:
    """Result of discount evaluation."""
    requested_discount: float
    max_acceptable: float
    recommendation: str  # "approve", "counter", "deny"
    counter_offer: Optional[float] = None
    
    rationale: str = ""
    
    # Signal drivers
    momentum_factor: float = 0.0
    elasticity_factor: float = 0.0
    seasonality_factor: float = 0.0
    
    confidence: float = 0.0
    gating: GatingInfo = None
    
    engine_version: str = ENGINE_VERSION


# =============================================================================
# PROPERTY CONFIGURATION
# =============================================================================

@dataclass
class PropertyConfig:
    """Property configuration for analytics."""
    bedrooms: int
    bathrooms: float = 2.0
    sleeps: int = 6
    
    # Amenities (list of amenity names)
    amenities: List[str] = field(default_factory=list)
    
    # Location
    geo_id: str = ""
    
    # Base ADR (market baseline by bedroom)
    base_adr_override: Optional[float] = None


# =============================================================================
# MARKET BASELINES
# =============================================================================

# Base ADR by bedroom count (fallback when no market signal)
# These are ONLY used when signals are missing
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


# =============================================================================
# ANALYTICS ENGINE
# =============================================================================

class AnalyticsEngine:
    """
    Analytics Engine v3 - Pure Signal Consumer.
    
    This engine is a DETERMINISTIC FUNCTION:
    
        f(SignalBundle, PropertyConfig) → AnalyticsResult
    
    It does NOT:
    - Scrape
    - Fetch PMS data
    - Talk to APIs
    - Compute market signals
    
    It ONLY:
    - Consumes signals from SignalBundle
    - Applies math
    - Returns gated results
    
    All detection happens in DETECTORS.
    All math happens HERE.
    """
    
    def __init__(self):
        self.version = ENGINE_VERSION
    
    def compute_adr(
        self,
        signal_bundle: SignalBundle,
        property_config: PropertyConfig,
        target_date: Optional[date] = None,
        output_type: str = "bd_projection",
    ) -> ADRResult:
        """
        Compute ADR from signals.
        
        This is THE function for ADR calculation.
        All inputs come from SignalBundle. No inline computation.
        
        Args:
            signal_bundle: Bundle containing all relevant signals
            property_config: Property attributes
            target_date: Date for seasonality lookup
            output_type: Type of output (for gating threshold)
        
        Returns:
            ADRResult with computed ADR and confidence
        """
        target_date = target_date or date.today()
        
        # =================================================================
        # Step 1: Get base ADR
        # =================================================================
        base_adr = (
            property_config.base_adr_override or
            BASELINE_ADR_BY_BEDROOM.get(property_config.bedrooms, 300.0)
        )
        
        # =================================================================
        # Step 2: Get seasonality from signals
        # =================================================================
        seasonality = get_seasonality(signal_bundle, target_date)
        seasonality_mult = seasonality.multiplier
        seasonality_conf = seasonality.confidence
        
        # =================================================================
        # Step 3: Get amenity lift from signals
        # =================================================================
        amenity_lift = get_amenity_lift(signal_bundle, property_config.amenities)
        amenity_mult = amenity_lift.multiplier
        amenity_conf = amenity_lift.confidence
        
        # =================================================================
        # Step 4: Get operator delta from signals
        # =================================================================
        operator_delta = get_operator_delta(signal_bundle)
        operator_mult = 1.0 + operator_delta.applied_adr_delta
        operator_conf = operator_delta.confidence
        
        # =================================================================
        # Step 5: Get platform bias from signals
        # =================================================================
        platform = get_platform_bias(signal_bundle)
        platform_bias = platform.dominant_platform
        platform_conf = platform.confidence
        
        # =================================================================
        # Step 6: Compute final ADR
        # =================================================================
        adjusted_adr = base_adr * seasonality_mult
        adjusted_adr *= amenity_mult
        final_adr = adjusted_adr * operator_mult
        
        # =================================================================
        # Step 7: Compute confidence and range
        # =================================================================
        # Weighted average confidence
        confidence = (
            seasonality_conf * 0.30 +
            amenity_conf * 0.25 +
            operator_conf * 0.25 +
            platform_conf * 0.20
        )
        
        # Range based on confidence
        if confidence >= 0.7:
            range_pct = 0.12
        elif confidence >= 0.5:
            range_pct = 0.18
        else:
            range_pct = 0.25
        
        low_adr = final_adr * (1 - range_pct)
        high_adr = final_adr * (1 + range_pct)
        
        # =================================================================
        # Step 8: Check gating
        # =================================================================
        gating = self._check_gating(confidence, output_type, signal_bundle)
        
        return ADRResult(
            base_adr=base_adr,
            adjusted_adr=adjusted_adr,
            final_adr=final_adr,
            low_adr=low_adr,
            high_adr=high_adr,
            seasonality_multiplier=seasonality_mult,
            amenity_multiplier=amenity_mult,
            operator_multiplier=operator_mult,
            platform_bias=platform_bias,
            confidence=confidence,
            gating=gating,
            seasonality_confidence=seasonality_conf,
            amenity_confidence=amenity_conf,
            operator_confidence=operator_conf,
            platform_confidence=platform_conf,
            signal_count=signal_bundle.signal_count,
        )
    
    def compute_occupancy(
        self,
        signal_bundle: SignalBundle,
        property_config: PropertyConfig,
        target_date: Optional[date] = None,
        output_type: str = "bd_projection",
    ) -> OccupancyResult:
        """
        Compute occupancy from signals.
        """
        target_date = target_date or date.today()
        
        # Base occupancy
        base_occ = BASELINE_OCCUPANCY
        
        # Seasonality
        seasonality = get_seasonality(signal_bundle, target_date)
        season_factor = seasonality.multiplier * 0.55  # Scale to occupancy range
        season_factor = min(0.95, max(0.15, season_factor))
        
        # Momentum
        momentum, momentum_conf = signal_bundle.get_weighted_with_confidence(
            SignalType.OCCUPANCY_MOMENTUM
        )
        momentum_factor = 1.0 + (momentum * 0.10 if momentum else 0.0)
        
        # Operator delta
        operator = get_operator_delta(signal_bundle)
        operator_factor = 1.0 + operator.applied_occupancy_delta
        
        # Final occupancy
        adjusted_occ = base_occ * (season_factor / 0.55)  # Adjust for seasonality
        final_occ = min(0.95, adjusted_occ * momentum_factor * operator_factor)
        
        # Confidence
        confidence = (
            seasonality.confidence * 0.40 +
            (momentum_conf or 0.3) * 0.30 +
            operator.confidence * 0.30
        )
        
        # Range
        range_pct = 0.15 if confidence >= 0.6 else 0.25
        
        gating = self._check_gating(confidence, output_type, signal_bundle)
        
        return OccupancyResult(
            base_occupancy=base_occ,
            adjusted_occupancy=adjusted_occ,
            final_occupancy=final_occ,
            low_occupancy=max(0.1, final_occ - range_pct),
            high_occupancy=min(0.95, final_occ + range_pct),
            seasonality_factor=season_factor,
            momentum_factor=momentum_factor,
            operator_factor=operator_factor,
            confidence=confidence,
            gating=gating,
        )
    
    def compute_revenue_projection(
        self,
        signal_bundle: SignalBundle,
        property_config: PropertyConfig,
        projection_year: Optional[int] = None,
        output_type: str = "bd_projection",
    ) -> RevenueProjectionResult:
        """
        Compute full revenue projection from signals.
        """
        projection_year = projection_year or date.today().year
        
        # Get ADR and occupancy
        adr_result = self.compute_adr(signal_bundle, property_config, output_type=output_type)
        occ_result = self.compute_occupancy(signal_bundle, property_config, output_type=output_type)
        
        # Get monthly seasonality curve
        seasonality = get_seasonality(signal_bundle)
        monthly_curve = seasonality.monthly_curve or {}
        
        # Generate monthly projections
        days_in_month = [0, 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
        month_names = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
                       "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        
        monthly = []
        total_revenue = 0.0
        
        for month in range(1, 13):
            # Get month-specific multiplier
            month_key = month_names[month].lower()
            month_mult = monthly_curve.get(month_key, 1.0)
            
            days = days_in_month[month]
            month_adr = adr_result.final_adr * month_mult
            month_occ = min(0.95, occ_result.final_occupancy * month_mult)
            nights = int(days * month_occ)
            revenue = nights * month_adr
            
            monthly.append({
                "month": month,
                "month_name": month_names[month],
                "days": days,
                "adr": round(month_adr, 2),
                "occupancy": round(month_occ, 3),
                "nights_booked": nights,
                "revenue": round(revenue, 2),
            })
            
            total_revenue += revenue
        
        # Overall confidence
        confidence = min(adr_result.confidence, occ_result.confidence)
        
        # Revenue ranges
        if confidence >= 0.7:
            low_mult, high_mult = 0.88, 1.15
        elif confidence >= 0.5:
            low_mult, high_mult = 0.82, 1.22
        else:
            low_mult, high_mult = 0.75, 1.30
        
        gating = self._check_gating(confidence, output_type, signal_bundle)
        
        return RevenueProjectionResult(
            adr_result=adr_result,
            occupancy_result=occ_result,
            gross_revenue_low=round(total_revenue * low_mult, 0),
            gross_revenue_expected=round(total_revenue, 0),
            gross_revenue_high=round(total_revenue * high_mult, 0),
            monthly_projections=monthly,
            confidence=confidence,
            gating=gating,
        )
    
    def evaluate_discount(
        self,
        signal_bundle: SignalBundle,
        requested_discount: float,
        output_type: str = "voice_discount",
    ) -> DiscountEvaluationResult:
        """
        Evaluate a discount request using signals.
        """
        # Get momentum
        momentum, momentum_conf = signal_bundle.get_weighted_with_confidence(
            SignalType.OCCUPANCY_MOMENTUM
        )
        momentum = momentum or 0.0
        
        # Get elasticity
        elasticity, elasticity_conf = signal_bundle.get_weighted_with_confidence(
            SignalType.PRICE_ELASTICITY
        )
        elasticity = elasticity or -1.0
        
        # Get seasonality
        seasonality = get_seasonality(signal_bundle)
        
        # Calculate max acceptable discount
        base_max = 0.15
        
        # Adjust for momentum (strong momentum = lower max discount)
        momentum_adj = -momentum * 0.10  # Strong momentum reduces max discount
        
        # Adjust for elasticity (elastic market = higher max discount)
        elasticity_adj = -0.05 if elasticity < -1.2 else 0.0
        
        # Adjust for seasonality (peak season = lower max discount)
        season_adj = -0.05 if seasonality.multiplier > 1.2 else 0.0
        
        max_acceptable = max(0.05, min(0.30, base_max + momentum_adj + elasticity_adj + season_adj))
        
        # Determine recommendation
        if momentum > 0.5:
            recommendation = "deny"
            rationale = "Strong booking momentum - no discount needed"
            counter = None
        elif requested_discount <= max_acceptable:
            recommendation = "approve"
            rationale = f"Discount within acceptable range"
            counter = None
        else:
            recommendation = "counter"
            rationale = f"Requested discount exceeds maximum"
            counter = max_acceptable
        
        # Confidence
        confidence = (
            (momentum_conf or 0.3) * 0.40 +
            (elasticity_conf or 0.3) * 0.30 +
            seasonality.confidence * 0.30
        )
        
        gating = self._check_gating(confidence, output_type, signal_bundle)
        
        # Gate denials if confidence too low
        if recommendation == "deny" and gating.status != OutputGateStatus.ALLOWED:
            recommendation = "escalate"
            rationale = "Insufficient confidence to deny - escalate to human"
        
        return DiscountEvaluationResult(
            requested_discount=requested_discount,
            max_acceptable=max_acceptable,
            recommendation=recommendation,
            counter_offer=counter,
            rationale=rationale,
            momentum_factor=momentum,
            elasticity_factor=elasticity or -1.0,
            seasonality_factor=seasonality.multiplier,
            confidence=confidence,
            gating=gating,
        )
    
    def _check_gating(
        self,
        confidence: float,
        output_type: str,
        signal_bundle: SignalBundle,
    ) -> GatingInfo:
        """Check if output should be gated."""
        threshold = {
            "voice_pricing": ConfidenceThresholds.VOICE_PRICING_CLAIM,
            "voice_discount": ConfidenceThresholds.VOICE_DISCOUNT_DENIAL,
            "voice_market": ConfidenceThresholds.VOICE_MARKET_ASSERTION,
            "bd_projection": ConfidenceThresholds.BD_PROJECTION,
            "bd_recommendation": ConfidenceThresholds.BD_RECOMMENDATION,
            "internal": ConfidenceThresholds.INTERNAL_ANALYSIS,
        }.get(output_type, ConfidenceThresholds.BD_PROJECTION)
        
        if confidence >= threshold:
            return GatingInfo(
                status=OutputGateStatus.ALLOWED,
                required_confidence=threshold,
                actual_confidence=confidence,
            )
        
        # Check for missing critical signals
        critical_signals = [
            SignalType.SEASONALITY_CURVE,
            SignalType.PLATFORM_DOMINANCE,
        ]
        missing = [s for s in critical_signals if not signal_bundle.has_signal(s)]
        
        if missing:
            return GatingInfo(
                status=OutputGateStatus.GATED_MISSING_SIGNALS,
                reason=f"Missing signals: {[s.value for s in missing]}",
                required_confidence=threshold,
                actual_confidence=confidence,
                missing_signals=missing,
            )
        
        return GatingInfo(
            status=OutputGateStatus.GATED_LOW_CONFIDENCE,
            reason=f"Confidence {confidence:.2f} below threshold {threshold:.2f}",
            required_confidence=threshold,
            actual_confidence=confidence,
        )


# =============================================================================
# SINGLETON & CONVENIENCE
# =============================================================================

_engine: Optional[AnalyticsEngine] = None


def get_analytics_engine() -> AnalyticsEngine:
    """Get analytics engine singleton."""
    global _engine
    if _engine is None:
        _engine = AnalyticsEngine()
    return _engine


def compute_adr(
    signal_bundle: SignalBundle,
    property_config: PropertyConfig,
    **kwargs
) -> ADRResult:
    """Convenience function for ADR computation."""
    return get_analytics_engine().compute_adr(signal_bundle, property_config, **kwargs)


def compute_revenue(
    signal_bundle: SignalBundle,
    property_config: PropertyConfig,
    **kwargs
) -> RevenueProjectionResult:
    """Convenience function for revenue projection."""
    return get_analytics_engine().compute_revenue_projection(
        signal_bundle, property_config, **kwargs
    )
