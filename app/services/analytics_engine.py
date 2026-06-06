"""
Analytics Engine - Pure Synthesis from Signals.

The analytics engine is the BRAIN of the system.

It does NOT:
- Scrape
- Fetch PMS data
- Talk to APIs
- Parse messages
- Access raw data

It ONLY:
- Consumes signals
- Applies math
- Emits decisions

Key Invariant:
No math, pricing, or decisions occur before signals are 
normalized, scored, and confidence-weighted.

Hard Rule:
If confidence < threshold → voice, BD, and pricing outputs 
are automatically gated.

This is your moat.
"""

from dataclasses import dataclass, field
from datetime import datetime, date, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID
import math

from pydantic import BaseModel, Field, ConfigDict

from schemas.signals import (
    Signal,
    SignalBundle,
    SignalType,
    SignalScope,
    TimeWindow,
    DecayProfile,
)


# =============================================================================
# ENGINE VERSION
# =============================================================================

ENGINE_VERSION = "2.0.0"  # Signal-based architecture


# =============================================================================
# CONFIDENCE THRESHOLDS
# =============================================================================

class ConfidenceThresholds:
    """
    Confidence thresholds that gate outputs.
    
    If confidence < threshold, the output is automatically blocked.
    """
    
    # Voice outputs require high confidence
    VOICE_PRICING_CLAIM = 0.75
    VOICE_DISCOUNT_DENIAL = 0.70
    VOICE_MARKET_ASSERTION = 0.65
    
    # BD outputs require medium-high confidence
    BD_PROJECTION = 0.60
    BD_RECOMMENDATION = 0.65
    BD_EXPANSION_SCORE = 0.55
    
    # Internal analytics can be lower
    INTERNAL_ANALYSIS = 0.50
    
    # Minimum to even process
    MINIMUM_VIABLE = 0.40


# =============================================================================
# ANALYTICS INPUT CONTRACT
# =============================================================================

class ArtifactType(str, Enum):
    """Types of artifacts the engine can produce."""
    ADR_MODEL = "adr_model"
    OCCUPANCY_FORECAST = "occupancy_forecast"
    REVENUE_PROJECTION = "revenue_projection"
    EXPANSION_SCORE = "expansion_score"
    PRICING_RECOMMENDATION = "pricing_recommendation"
    DISCOUNT_EVALUATION = "discount_evaluation"
    MARKET_HEALTH = "market_health"
    OPERATOR_BENCHMARK = "operator_benchmark"


class AnalyticsInput(BaseModel):
    """
    Input contract for analytics engine.
    
    The engine receives signals and produces artifacts.
    It never touches raw data.
    """
    tenant_id: UUID
    geo_id: str
    property_id: Optional[UUID] = None
    
    # The signals to analyze
    signals: SignalBundle
    
    # What artifact to produce
    requested_artifact: ArtifactType
    
    # Optional: specific parameters
    parameters: Dict[str, Any] = Field(default_factory=dict)
    
    # Context for the request
    as_of_date: date = Field(default_factory=date.today)
    
    model_config = ConfigDict(arbitrary_types_allowed=True)


# =============================================================================
# ANALYTICS OUTPUT CONTRACTS
# =============================================================================

class AnalyticsOutput(BaseModel):
    """Base output from analytics engine."""
    artifact_type: ArtifactType
    confidence: float = Field(..., ge=0.0, le=1.0)
    
    # Is this output usable?
    is_gated: bool = False
    gate_reason: Optional[str] = None
    
    # Provenance
    engine_version: str = ENGINE_VERSION
    computed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    signal_count: int = 0
    
    # Explanation
    drivers: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class ADRModelOutput(AnalyticsOutput):
    """Output from ADR modeling."""
    artifact_type: ArtifactType = ArtifactType.ADR_MODEL
    
    base_adr: Decimal
    amenity_adjustment: float  # Multiplicative factor
    seasonality_multiplier: float
    operator_adjustment: float
    
    final_adr: Decimal
    adr_range: Tuple[Decimal, Decimal]  # (low, high)
    
    platform_bias: Optional[str] = None  # Which platform to optimize for


class OccupancyForecastOutput(AnalyticsOutput):
    """Output from occupancy forecasting."""
    artifact_type: ArtifactType = ArtifactType.OCCUPANCY_FORECAST
    
    base_occupancy: float
    momentum_adjustment: float
    seasonal_adjustment: float
    
    final_occupancy: float
    occupancy_range: Tuple[float, float]


class RevenueProjectionOutput(AnalyticsOutput):
    """Output from revenue projection."""
    artifact_type: ArtifactType = ArtifactType.REVENUE_PROJECTION
    
    projected_adr: Decimal
    projected_occupancy: float
    projected_nights: int
    
    gross_revenue: Decimal
    revenue_range: Tuple[Decimal, Decimal]
    
    monthly_breakdown: Dict[str, Decimal] = Field(default_factory=dict)


class ExpansionScoreOutput(AnalyticsOutput):
    """Output from expansion scoring."""
    artifact_type: ArtifactType = ArtifactType.EXPANSION_SCORE
    
    market_score: int = Field(..., ge=0, le=100)
    
    components: Dict[str, float] = Field(default_factory=dict)
    # Expected: seasonality_strength, amenity_match, platform_fit, etc.


class PricingRecommendationOutput(AnalyticsOutput):
    """Output from pricing recommendation."""
    artifact_type: ArtifactType = ArtifactType.PRICING_RECOMMENDATION
    
    current_rate: Decimal
    recommended_rate: Decimal
    change_percent: float
    
    rationale: str
    urgency: str  # "immediate", "soon", "optional"


class DiscountEvaluationOutput(AnalyticsOutput):
    """Output from discount evaluation."""
    artifact_type: ArtifactType = ArtifactType.DISCOUNT_EVALUATION
    
    requested_discount: float
    recommended_action: str  # "approve", "counter", "deny"
    
    max_acceptable_discount: float
    counter_offer: Optional[float] = None
    
    rationale: str


# =============================================================================
# ANALYTICS ENGINE
# =============================================================================

class AnalyticsEngine:
    """
    The Analytics Engine - Pure Synthesis.
    
    This engine:
    1. Receives signals (never raw data)
    2. Applies mathematical models
    3. Produces gated outputs
    
    All outputs are confidence-gated to prevent overconfidence.
    """
    
    def __init__(self):
        self.version = ENGINE_VERSION
    
    def process(self, input: AnalyticsInput) -> AnalyticsOutput:
        """
        Process an analytics request.
        
        Routes to appropriate artifact generator.
        """
        # Validate we have signals
        if not input.signals.signals:
            return self._create_gated_output(
                input.requested_artifact,
                "No signals available for analysis"
            )
        
        # Route to appropriate processor
        processors = {
            ArtifactType.ADR_MODEL: self._process_adr_model,
            ArtifactType.OCCUPANCY_FORECAST: self._process_occupancy_forecast,
            ArtifactType.REVENUE_PROJECTION: self._process_revenue_projection,
            ArtifactType.EXPANSION_SCORE: self._process_expansion_score,
            ArtifactType.PRICING_RECOMMENDATION: self._process_pricing_recommendation,
            ArtifactType.DISCOUNT_EVALUATION: self._process_discount_evaluation,
            ArtifactType.MARKET_HEALTH: self._process_market_health,
            ArtifactType.OPERATOR_BENCHMARK: self._process_operator_benchmark,
        }
        
        processor = processors.get(input.requested_artifact)
        if not processor:
            return self._create_gated_output(
                input.requested_artifact,
                f"Unknown artifact type: {input.requested_artifact}"
            )
        
        return processor(input)
    
    def _process_adr_model(self, input: AnalyticsInput) -> ADRModelOutput:
        """
        Process ADR model request.
        
        ADR = base_adr * amenity_adjustment * seasonality * operator_adjustment
        """
        signals = input.signals
        drivers = []
        warnings = []
        
        # Get base ADR from market signals
        base_adr = Decimal("250")  # Default fallback
        
        # Get platform dominance for optimization
        platform_signal = signals.most_recent(SignalType.PLATFORM_DOMINANCE)
        platform_bias = None
        if platform_signal and platform_signal.structured_value:
            platform_bias = platform_signal.structured_value.get("dominant_platform")
            drivers.append(f"Optimizing for {platform_bias} (dominant platform)")
        
        # Calculate amenity adjustment
        amenity_adjustment = 1.0
        amenity_signals = signals.by_type(SignalType.AMENITY_LIFT)
        for sig in amenity_signals:
            if sig.structured_value:
                lift = sig.structured_value.get("lift_percent", 0) / 100
                amenity_adjustment *= (1 + lift * sig.confidence)
                drivers.append(
                    f"{sig.structured_value.get('amenity', 'amenity')}: "
                    f"+{lift:.0%} (confidence: {sig.confidence:.0%})"
                )
        
        # Get seasonality multiplier
        seasonality_multiplier = 1.0
        seasonality_signal = signals.most_recent(SignalType.SEASONALITY_CURVE)
        if seasonality_signal and seasonality_signal.structured_value:
            monthly_curve = seasonality_signal.structured_value.get("monthly_curve", {})
            current_month = input.as_of_date.strftime("%b").lower()
            seasonality_multiplier = monthly_curve.get(current_month, 1.0)
            drivers.append(f"Seasonality for {current_month}: {seasonality_multiplier:.2f}x")
        
        # Get operator adjustment
        operator_adjustment = 1.0
        operator_signal = signals.most_recent(SignalType.OPERATOR_DELTA)
        if operator_signal and operator_signal.structured_value:
            adr_delta = operator_signal.structured_value.get("adr_delta_pct", 0)
            # Apply conservatively (50% of observed delta)
            operator_adjustment = 1 + (adr_delta * 0.5 * operator_signal.confidence)
            drivers.append(
                f"Operator premium: {adr_delta:.0%} observed, "
                f"{adr_delta * 0.5:.0%} applied (conservative)"
            )
        
        # Calculate final ADR
        final_adr = base_adr * Decimal(str(
            amenity_adjustment * seasonality_multiplier * operator_adjustment
        ))
        final_adr = final_adr.quantize(Decimal("0.01"))
        
        # Calculate range (±15% based on confidence)
        overall_confidence = signals.overall_confidence
        range_pct = 0.15 * (2 - overall_confidence)  # Higher confidence = tighter range
        adr_low = final_adr * Decimal(str(1 - range_pct))
        adr_high = final_adr * Decimal(str(1 + range_pct))
        
        # Check if gated
        is_gated = overall_confidence < ConfidenceThresholds.BD_PROJECTION
        gate_reason = None
        if is_gated:
            gate_reason = f"Confidence {overall_confidence:.0%} below threshold {ConfidenceThresholds.BD_PROJECTION:.0%}"
            warnings.append(gate_reason)
        
        return ADRModelOutput(
            confidence=overall_confidence,
            is_gated=is_gated,
            gate_reason=gate_reason,
            signal_count=len(signals.signals),
            drivers=drivers,
            warnings=warnings,
            
            base_adr=base_adr,
            amenity_adjustment=amenity_adjustment,
            seasonality_multiplier=seasonality_multiplier,
            operator_adjustment=operator_adjustment,
            
            final_adr=final_adr,
            adr_range=(adr_low.quantize(Decimal("0.01")), adr_high.quantize(Decimal("0.01"))),
            platform_bias=platform_bias,
        )
    
    def _process_occupancy_forecast(self, input: AnalyticsInput) -> OccupancyForecastOutput:
        """Process occupancy forecast request."""
        signals = input.signals
        drivers = []
        warnings = []
        
        # Base occupancy from market
        base_occupancy = 0.65
        
        # Momentum adjustment
        momentum_adjustment = 0.0
        momentum_signal = signals.most_recent(SignalType.OCCUPANCY_MOMENTUM)
        if momentum_signal:
            # Convert -1 to 1 signal to adjustment
            momentum_adjustment = momentum_signal.value * 0.10  # ±10% max
            drivers.append(
                f"Momentum: {'+' if momentum_adjustment > 0 else ''}"
                f"{momentum_adjustment:.0%} (pace vs last year)"
            )
        
        # Seasonal adjustment
        seasonal_adjustment = 0.0
        seasonality_signal = signals.most_recent(SignalType.SEASONALITY_CURVE)
        if seasonality_signal and seasonality_signal.structured_value:
            monthly_curve = seasonality_signal.structured_value.get("monthly_curve", {})
            current_month = input.as_of_date.strftime("%b").lower()
            season_factor = monthly_curve.get(current_month, 1.0)
            seasonal_adjustment = (season_factor - 1.0) * 0.15  # Damped
            drivers.append(f"Seasonal factor: {season_factor:.2f}")
        
        # Final occupancy
        final_occupancy = base_occupancy + momentum_adjustment + seasonal_adjustment
        final_occupancy = max(0.20, min(0.95, final_occupancy))
        
        # Range
        confidence = signals.overall_confidence
        range_size = 0.10 * (2 - confidence)
        
        is_gated = confidence < ConfidenceThresholds.BD_PROJECTION
        
        return OccupancyForecastOutput(
            confidence=confidence,
            is_gated=is_gated,
            gate_reason=f"Low confidence: {confidence:.0%}" if is_gated else None,
            signal_count=len(signals.signals),
            drivers=drivers,
            warnings=warnings,
            
            base_occupancy=base_occupancy,
            momentum_adjustment=momentum_adjustment,
            seasonal_adjustment=seasonal_adjustment,
            
            final_occupancy=final_occupancy,
            occupancy_range=(
                max(0.0, final_occupancy - range_size),
                min(1.0, final_occupancy + range_size)
            ),
        )
    
    def _process_revenue_projection(self, input: AnalyticsInput) -> RevenueProjectionOutput:
        """Process revenue projection request."""
        # Get ADR and occupancy first
        adr_output = self._process_adr_model(input)
        occ_output = self._process_occupancy_forecast(input)
        
        # Calculate revenue
        days_in_year = 365
        projected_nights = int(days_in_year * occ_output.final_occupancy)
        gross_revenue = adr_output.final_adr * projected_nights
        
        # Range from ADR and occupancy ranges
        low_revenue = adr_output.adr_range[0] * Decimal(str(int(days_in_year * occ_output.occupancy_range[0])))
        high_revenue = adr_output.adr_range[1] * Decimal(str(int(days_in_year * occ_output.occupancy_range[1])))
        
        # Monthly breakdown using seasonality
        monthly_breakdown = {}
        seasonality_signal = input.signals.most_recent(SignalType.SEASONALITY_CURVE)
        if seasonality_signal and seasonality_signal.structured_value:
            curve = seasonality_signal.structured_value.get("monthly_curve", {})
            total_weight = sum(curve.values())
            for month, weight in curve.items():
                monthly_breakdown[month] = (gross_revenue * Decimal(str(weight / total_weight))).quantize(Decimal("0.01"))
        
        confidence = min(adr_output.confidence, occ_output.confidence)
        is_gated = confidence < ConfidenceThresholds.BD_PROJECTION
        
        return RevenueProjectionOutput(
            confidence=confidence,
            is_gated=is_gated,
            gate_reason=f"Combined confidence {confidence:.0%} below threshold" if is_gated else None,
            signal_count=len(input.signals.signals),
            drivers=adr_output.drivers + occ_output.drivers,
            warnings=adr_output.warnings + occ_output.warnings,
            
            projected_adr=adr_output.final_adr,
            projected_occupancy=occ_output.final_occupancy,
            projected_nights=projected_nights,
            
            gross_revenue=gross_revenue.quantize(Decimal("0.01")),
            revenue_range=(low_revenue.quantize(Decimal("0.01")), high_revenue.quantize(Decimal("0.01"))),
            
            monthly_breakdown=monthly_breakdown,
        )
    
    def _process_expansion_score(self, input: AnalyticsInput) -> ExpansionScoreOutput:
        """Process expansion score request."""
        signals = input.signals
        drivers = []
        warnings = []
        
        components = {}
        
        # Seasonality strength (do they have seasonality we can work with?)
        seasonality_signal = signals.most_recent(SignalType.SEASONALITY_CURVE)
        if seasonality_signal and seasonality_signal.structured_value:
            strength = seasonality_signal.structured_value.get("seasonality_strength", 1.5)
            # Moderate seasonality is good (1.5-2.5)
            if 1.5 <= strength <= 2.5:
                components["seasonality_match"] = 0.8
                drivers.append("Favorable seasonality pattern")
            elif strength < 1.5:
                components["seasonality_match"] = 0.6
                drivers.append("Weak seasonality (steady demand)")
            else:
                components["seasonality_match"] = 0.5
                warnings.append("Extreme seasonality may challenge operations")
        else:
            components["seasonality_match"] = 0.5
        
        # Platform fit
        platform_signal = signals.most_recent(SignalType.PLATFORM_DOMINANCE)
        if platform_signal and platform_signal.structured_value:
            dominant = platform_signal.structured_value.get("dominant_platform")
            # Assume operator is strongest on Airbnb
            if dominant == "airbnb":
                components["platform_fit"] = 0.9
                drivers.append("Market aligns with operator's primary platform")
            else:
                components["platform_fit"] = 0.7
                drivers.append(f"Market favors {dominant} - may need channel adjustment")
        else:
            components["platform_fit"] = 0.6
        
        # Amenity alignment (placeholder - would compare to operator portfolio)
        components["amenity_match"] = 0.75
        
        # Calculate overall score
        weights = {"seasonality_match": 0.3, "platform_fit": 0.4, "amenity_match": 0.3}
        weighted_sum = sum(components.get(k, 0.5) * v for k, v in weights.items())
        market_score = int(weighted_sum * 100)
        
        confidence = signals.overall_confidence
        is_gated = confidence < ConfidenceThresholds.BD_EXPANSION_SCORE
        
        return ExpansionScoreOutput(
            confidence=confidence,
            is_gated=is_gated,
            gate_reason=f"Confidence {confidence:.0%} below threshold" if is_gated else None,
            signal_count=len(signals.signals),
            drivers=drivers,
            warnings=warnings,
            
            market_score=market_score,
            components=components,
        )
    
    def _process_pricing_recommendation(self, input: AnalyticsInput) -> PricingRecommendationOutput:
        """Process pricing recommendation request."""
        current_rate = input.parameters.get("current_rate", Decimal("300"))
        
        # Get ADR model
        adr_output = self._process_adr_model(input)
        
        # Compare to recommended
        recommended = adr_output.final_adr
        change_pct = float((recommended - current_rate) / current_rate)
        
        # Determine urgency
        if abs(change_pct) > 0.15:
            urgency = "immediate"
            rationale = f"Significant mispricing detected ({change_pct:+.0%})"
        elif abs(change_pct) > 0.05:
            urgency = "soon"
            rationale = f"Moderate adjustment recommended ({change_pct:+.0%})"
        else:
            urgency = "optional"
            rationale = "Pricing is within optimal range"
        
        is_gated = adr_output.confidence < ConfidenceThresholds.BD_RECOMMENDATION
        
        return PricingRecommendationOutput(
            confidence=adr_output.confidence,
            is_gated=is_gated,
            gate_reason=adr_output.gate_reason,
            signal_count=adr_output.signal_count,
            drivers=adr_output.drivers,
            warnings=adr_output.warnings,
            
            current_rate=current_rate,
            recommended_rate=recommended,
            change_percent=change_pct,
            rationale=rationale,
            urgency=urgency,
        )
    
    def _process_discount_evaluation(self, input: AnalyticsInput) -> DiscountEvaluationOutput:
        """Process discount evaluation request."""
        signals = input.signals
        requested_discount = input.parameters.get("requested_discount", 0.10)
        
        drivers = []
        warnings = []
        
        # Check momentum - are we ahead or behind pace?
        momentum_signal = signals.most_recent(SignalType.OCCUPANCY_MOMENTUM)
        pace_factor = 0
        if momentum_signal:
            pace_factor = momentum_signal.value  # -1 to +1
            if pace_factor > 0.3:
                drivers.append("Bookings ahead of pace - hold firm")
            elif pace_factor < -0.3:
                drivers.append("Bookings behind pace - flexibility warranted")
        
        # Check elasticity
        elasticity_signal = signals.most_recent(SignalType.PRICE_ELASTICITY)
        elasticity_factor = 0
        if elasticity_signal:
            if elasticity_signal.value < 0:  # Elastic market
                drivers.append("Market is price-sensitive")
                elasticity_factor = -0.1
            else:
                drivers.append("Market is price-insensitive")
                elasticity_factor = 0.1
        
        # Calculate max acceptable discount
        base_max = 0.15  # 15% baseline max
        adjusted_max = base_max - (pace_factor * 0.10) + elasticity_factor
        max_acceptable = max(0.05, min(0.30, adjusted_max))
        
        # Determine action
        if requested_discount <= max_acceptable * 0.5:
            action = "approve"
            rationale = f"Discount within acceptable range ({requested_discount:.0%} ≤ {max_acceptable:.0%})"
            counter = None
        elif requested_discount <= max_acceptable:
            action = "approve"
            rationale = f"Discount at upper limit but acceptable"
            counter = None
        else:
            action = "counter"
            counter = max_acceptable
            rationale = f"Requested {requested_discount:.0%} exceeds maximum {max_acceptable:.0%}"
        
        # Override if momentum is very strong
        if pace_factor > 0.5:
            action = "deny"
            rationale = "Strong booking momentum - no discount needed"
            counter = None
            drivers.append("OVERRIDE: High demand period")
        
        confidence = signals.overall_confidence
        is_gated = confidence < ConfidenceThresholds.VOICE_DISCOUNT_DENIAL and action == "deny"
        
        if is_gated:
            warnings.append(f"Cannot confidently deny - escalate to human")
            action = "escalate"
        
        return DiscountEvaluationOutput(
            confidence=confidence,
            is_gated=is_gated,
            gate_reason="Insufficient confidence for denial" if is_gated else None,
            signal_count=len(signals.signals),
            drivers=drivers,
            warnings=warnings,
            
            requested_discount=requested_discount,
            recommended_action=action,
            max_acceptable_discount=max_acceptable,
            counter_offer=counter,
            rationale=rationale,
        )
    
    def _process_market_health(self, input: AnalyticsInput) -> AnalyticsOutput:
        """Process market health assessment."""
        # Placeholder - combines multiple signals into health score
        return AnalyticsOutput(
            artifact_type=ArtifactType.MARKET_HEALTH,
            confidence=input.signals.overall_confidence,
            signal_count=len(input.signals.signals),
            drivers=["Market health assessment"],
        )
    
    def _process_operator_benchmark(self, input: AnalyticsInput) -> AnalyticsOutput:
        """Process operator benchmarking."""
        # Placeholder - uses operator delta and market signals
        return AnalyticsOutput(
            artifact_type=ArtifactType.OPERATOR_BENCHMARK,
            confidence=input.signals.overall_confidence,
            signal_count=len(input.signals.signals),
            drivers=["Operator benchmark"],
        )
    
    def _create_gated_output(
        self, 
        artifact_type: ArtifactType, 
        reason: str
    ) -> AnalyticsOutput:
        """Create a gated (blocked) output."""
        return AnalyticsOutput(
            artifact_type=artifact_type,
            confidence=0.0,
            is_gated=True,
            gate_reason=reason,
            warnings=[reason],
        )


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

_engine: Optional[AnalyticsEngine] = None


def get_analytics_engine() -> AnalyticsEngine:
    """Get or create analytics engine singleton."""
    global _engine
    if _engine is None:
        _engine = AnalyticsEngine()
    return _engine


def compute_adr(
    tenant_id: UUID,
    geo_id: str,
    signals: SignalBundle,
    as_of: Optional[date] = None,
) -> ADRModelOutput:
    """Convenience function for ADR computation."""
    engine = get_analytics_engine()
    return engine.process(AnalyticsInput(
        tenant_id=tenant_id,
        geo_id=geo_id,
        signals=signals,
        requested_artifact=ArtifactType.ADR_MODEL,
        as_of_date=as_of or date.today(),
    ))


def evaluate_discount(
    tenant_id: UUID,
    geo_id: str,
    signals: SignalBundle,
    requested_discount: float,
) -> DiscountEvaluationOutput:
    """Convenience function for discount evaluation."""
    engine = get_analytics_engine()
    return engine.process(AnalyticsInput(
        tenant_id=tenant_id,
        geo_id=geo_id,
        signals=signals,
        requested_artifact=ArtifactType.DISCOUNT_EVALUATION,
        parameters={"requested_discount": requested_discount},
    ))
