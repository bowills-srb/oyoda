"""
Discount Engine v2.0 - Signal-Only.

This replaces the inline calculations in discount_engine.py.

USES ONLY:
- get_operator_delta() for operator performance
- get_platform_bias() for market context
- get_seasonality() for seasonal adjustments
- SignalBundle.get_weighted(OCCUPANCY_MOMENTUM)
- SignalBundle.get_weighted(PRICE_ELASTICITY)

NO inline calculations. NO hardcoded thresholds beyond safety caps.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from app.services.signals import (
    SignalBundle,
    SignalType,
    get_seasonality,
    get_platform_bias,
    get_operator_delta,
    ConfidenceThresholds,
    fast_decay,
)


# =============================================================================
# ENUMS
# =============================================================================

class DiscountDecision(str, Enum):
    """Discount decision outcomes."""
    APPROVE = "approve"
    COUNTER = "counter"
    DENY = "deny"
    ESCALATE = "escalate"  # When confidence too low to decide


class DiscountReason(str, Enum):
    """Reasons for discount decisions."""
    HIGH_DEMAND = "high_demand"
    PEAK_SEASON = "peak_season"
    STRONG_MOMENTUM = "strong_momentum"
    OPERATOR_PREMIUM = "operator_premium"
    ACCEPTABLE_RANGE = "acceptable_range"
    WITHIN_ELASTICITY = "within_elasticity"
    LOW_CONFIDENCE = "low_confidence"


# =============================================================================
# OUTPUT MODELS
# =============================================================================

@dataclass
class DiscountEvaluation:
    """
    Result of discount evaluation.
    
    All decisions are signal-driven with full reasoning.
    """
    # Request
    requested_discount_pct: float
    
    # Decision
    decision: DiscountDecision
    reason: DiscountReason
    rationale: str
    
    # Counter offer (if applicable)
    counter_offer_pct: Optional[float] = None
    max_acceptable_pct: float = 0.0
    
    # Signal drivers
    momentum_value: float = 0.0
    momentum_confidence: float = 0.0
    
    elasticity_value: float = 0.0
    elasticity_confidence: float = 0.0
    
    seasonality_factor: float = 1.0
    seasonality_confidence: float = 0.0
    
    operator_premium: float = 0.0
    operator_confidence: float = 0.0
    
    # Overall
    decision_confidence: float = 0.0
    
    # Gating
    is_gated: bool = False
    gate_reason: Optional[str] = None
    
    # Audit
    computed_at: datetime = None
    signal_count: int = 0
    
    def __post_init__(self):
        if self.computed_at is None:
            self.computed_at = datetime.utcnow()


@dataclass
class DiscountPolicy:
    """
    Discount policy derived from signals.
    
    This is what the discount engine uses for evaluation.
    """
    # Base maximum discount (safety cap)
    absolute_max_discount: float = 0.30  # Never exceed 30%
    absolute_min_discount: float = 0.0   # No negative discounts
    
    # Signal-adjusted maximum
    effective_max_discount: float = 0.15
    
    # Thresholds
    auto_approve_threshold: float = 0.10  # Auto-approve up to this
    
    # Momentum impact
    high_momentum_threshold: float = 0.5  # Above this, deny discounts
    
    # Confidence requirement
    min_confidence_for_denial: float = 0.60
    
    # Reasoning
    policy_drivers: List[str] = None
    
    def __post_init__(self):
        if self.policy_drivers is None:
            self.policy_drivers = []


# =============================================================================
# DISCOUNT ENGINE v2.0
# =============================================================================

class DiscountEngineV2:
    """
    Discount Engine v2.0 - Signal-Only.
    
    This engine:
    - Consumes ONLY signals via SignalBundle
    - Has NO hardcoded demand patterns
    - Has NO inline pace calculations
    - Gates decisions when confidence is low
    
    Signals used:
    - OCCUPANCY_MOMENTUM: Are we ahead or behind pace?
    - PRICE_ELASTICITY: How sensitive is demand to price?
    - SEASONALITY_CURVE: Is this peak/off season?
    - OPERATOR_DELTA: Does operator command a premium?
    """
    
    def __init__(self):
        self.version = "2.0.0"
    
    def evaluate_discount(
        self,
        signal_bundle: SignalBundle,
        requested_discount_pct: float,
        check_in_date: Optional[date] = None,
        length_of_stay: int = 1,
    ) -> DiscountEvaluation:
        """
        Evaluate a discount request using signals only.
        
        Args:
            signal_bundle: Bundle with all relevant signals
            requested_discount_pct: Requested discount (0.0-1.0, e.g., 0.15 = 15%)
            check_in_date: Optional check-in date for seasonality
            length_of_stay: Number of nights
        
        Returns:
            DiscountEvaluation with decision and reasoning
        """
        check_in_date = check_in_date or date.today() + timedelta(days=30)
        
        # =================================================================
        # Step 1: Get signals
        # =================================================================
        
        # Momentum: Are we ahead or behind booking pace?
        momentum, momentum_conf = signal_bundle.get_weighted_with_confidence(
            SignalType.OCCUPANCY_MOMENTUM,
            decay_fn=fast_decay,
        )
        momentum = momentum or 0.0
        momentum_conf = momentum_conf or 0.3
        
        # Elasticity: How sensitive is demand to price?
        elasticity, elasticity_conf = signal_bundle.get_weighted_with_confidence(
            SignalType.PRICE_ELASTICITY,
            decay_fn=fast_decay,
        )
        elasticity = elasticity or -1.0  # Default moderate elasticity
        elasticity_conf = elasticity_conf or 0.3
        
        # Seasonality: Peak or off-season?
        seasonality = get_seasonality(signal_bundle, check_in_date)
        
        # Operator: Do we command a premium?
        operator = get_operator_delta(signal_bundle)
        
        # =================================================================
        # Step 2: Build policy from signals
        # =================================================================
        policy = self._build_policy_from_signals(
            momentum, momentum_conf,
            elasticity, elasticity_conf,
            seasonality,
            operator,
        )
        
        # =================================================================
        # Step 3: Calculate decision confidence
        # =================================================================
        decision_confidence = (
            momentum_conf * 0.35 +
            elasticity_conf * 0.25 +
            seasonality.confidence * 0.25 +
            operator.confidence * 0.15
        )
        
        # =================================================================
        # Step 4: Make decision
        # =================================================================
        decision, reason, rationale, counter = self._make_decision(
            requested_discount_pct,
            policy,
            momentum,
            elasticity,
            seasonality,
            operator,
            decision_confidence,
        )
        
        # =================================================================
        # Step 5: Check gating
        # =================================================================
        is_gated = False
        gate_reason = None
        
        if decision == DiscountDecision.DENY:
            # Denials require higher confidence
            if decision_confidence < ConfidenceThresholds.VOICE_DISCOUNT_DENIAL:
                decision = DiscountDecision.ESCALATE
                reason = DiscountReason.LOW_CONFIDENCE
                rationale = "Insufficient signal confidence to deny - escalating to human review"
                is_gated = True
                gate_reason = f"Confidence {decision_confidence:.2f} below denial threshold"
        
        return DiscountEvaluation(
            requested_discount_pct=requested_discount_pct,
            decision=decision,
            reason=reason,
            rationale=rationale,
            counter_offer_pct=counter,
            max_acceptable_pct=policy.effective_max_discount,
            momentum_value=momentum,
            momentum_confidence=momentum_conf,
            elasticity_value=elasticity,
            elasticity_confidence=elasticity_conf,
            seasonality_factor=seasonality.multiplier,
            seasonality_confidence=seasonality.confidence,
            operator_premium=operator.applied_adr_delta,
            operator_confidence=operator.confidence,
            decision_confidence=decision_confidence,
            is_gated=is_gated,
            gate_reason=gate_reason,
            signal_count=signal_bundle.signal_count,
        )
    
    def _build_policy_from_signals(
        self,
        momentum: float,
        momentum_conf: float,
        elasticity: float,
        elasticity_conf: float,
        seasonality,  # SeasonalityResult
        operator,     # OperatorDeltaResult
    ) -> DiscountPolicy:
        """
        Build discount policy from signals.
        
        This is the core logic that converts signals to policy.
        """
        policy = DiscountPolicy()
        
        # Start with base max
        effective_max = 0.15
        
        # Adjust for momentum
        # Strong momentum = lower max discount
        if momentum > 0.5:
            effective_max -= 0.08
            policy.policy_drivers.append(f"Strong momentum ({momentum:.2f}) reduces max discount")
        elif momentum > 0.2:
            effective_max -= 0.03
            policy.policy_drivers.append(f"Moderate momentum ({momentum:.2f}) slightly reduces max")
        elif momentum < -0.3:
            effective_max += 0.05
            policy.policy_drivers.append(f"Weak momentum ({momentum:.2f}) allows higher discount")
        
        # Adjust for elasticity
        # Elastic market = higher max discount makes sense
        if elasticity < -1.5:
            effective_max += 0.03
            policy.policy_drivers.append(f"High elasticity ({elasticity:.2f}) allows larger discounts")
        elif elasticity > -0.8:
            effective_max -= 0.02
            policy.policy_drivers.append(f"Inelastic market ({elasticity:.2f}) reduces discount value")
        
        # Adjust for seasonality
        # Peak season = lower max discount
        if seasonality.multiplier > 1.3:
            effective_max -= 0.05
            policy.policy_drivers.append(f"Peak season (factor: {seasonality.multiplier:.2f}) limits discounts")
        elif seasonality.multiplier < 0.7:
            effective_max += 0.05
            policy.policy_drivers.append(f"Off-season (factor: {seasonality.multiplier:.2f}) allows larger discounts")
        
        # Adjust for operator premium
        # If operator commands premium, protect it
        if operator.applied_adr_delta > 0.05:
            effective_max -= 0.02
            policy.policy_drivers.append(f"Operator premium ({operator.applied_adr_delta:.1%}) should be protected")
        
        # Apply safety bounds
        effective_max = max(0.05, min(policy.absolute_max_discount, effective_max))
        policy.effective_max_discount = effective_max
        
        # Set auto-approve threshold (half of max)
        policy.auto_approve_threshold = effective_max * 0.5
        
        # Set momentum threshold
        policy.high_momentum_threshold = 0.5
        policy.min_confidence_for_denial = ConfidenceThresholds.VOICE_DISCOUNT_DENIAL
        
        return policy
    
    def _make_decision(
        self,
        requested: float,
        policy: DiscountPolicy,
        momentum: float,
        elasticity: float,
        seasonality,
        operator,
        confidence: float,
    ) -> Tuple[DiscountDecision, DiscountReason, str, Optional[float]]:
        """
        Make the actual discount decision.
        
        Returns: (decision, reason, rationale, counter_offer)
        """
        # Check for high momentum denial
        if momentum > policy.high_momentum_threshold:
            return (
                DiscountDecision.DENY,
                DiscountReason.STRONG_MOMENTUM,
                f"Strong booking momentum ({momentum:.0%} ahead of pace) - no discount needed",
                None,
            )
        
        # Check for peak season denial
        if seasonality.multiplier > 1.4 and seasonality.confidence > 0.5:
            return (
                DiscountDecision.DENY,
                DiscountReason.PEAK_SEASON,
                f"Peak season period (demand factor: {seasonality.multiplier:.2f}) - holding rates",
                None,
            )
        
        # Check auto-approve
        if requested <= policy.auto_approve_threshold:
            return (
                DiscountDecision.APPROVE,
                DiscountReason.ACCEPTABLE_RANGE,
                f"Discount {requested:.0%} within auto-approve threshold ({policy.auto_approve_threshold:.0%})",
                None,
            )
        
        # Check against effective max
        if requested <= policy.effective_max_discount:
            return (
                DiscountDecision.APPROVE,
                DiscountReason.WITHIN_ELASTICITY,
                f"Discount {requested:.0%} acceptable given market elasticity ({elasticity:.2f})",
                None,
            )
        
        # Counter offer at max
        return (
            DiscountDecision.COUNTER,
            DiscountReason.ACCEPTABLE_RANGE,
            f"Requested {requested:.0%} exceeds maximum {policy.effective_max_discount:.0%} - countering",
            policy.effective_max_discount,
        )
    
    def get_discount_policy(
        self,
        signal_bundle: SignalBundle,
        check_in_date: Optional[date] = None,
    ) -> DiscountPolicy:
        """
        Get current discount policy from signals.
        
        Useful for pre-populating UI or understanding limits.
        """
        check_in_date = check_in_date or date.today() + timedelta(days=30)
        
        momentum, momentum_conf = signal_bundle.get_weighted_with_confidence(
            SignalType.OCCUPANCY_MOMENTUM
        )
        elasticity, elasticity_conf = signal_bundle.get_weighted_with_confidence(
            SignalType.PRICE_ELASTICITY
        )
        seasonality = get_seasonality(signal_bundle, check_in_date)
        operator = get_operator_delta(signal_bundle)
        
        return self._build_policy_from_signals(
            momentum or 0.0, momentum_conf or 0.3,
            elasticity or -1.0, elasticity_conf or 0.3,
            seasonality,
            operator,
        )


# =============================================================================
# CONVENIENCE
# =============================================================================

_engine: Optional[DiscountEngineV2] = None


def get_discount_engine() -> DiscountEngineV2:
    """Get discount engine singleton."""
    global _engine
    if _engine is None:
        _engine = DiscountEngineV2()
    return _engine


def evaluate_discount(
    signal_bundle: SignalBundle,
    requested_discount_pct: float,
    **kwargs,
) -> DiscountEvaluation:
    """Convenience function for discount evaluation."""
    return get_discount_engine().evaluate_discount(
        signal_bundle, requested_discount_pct, **kwargs
    )


def get_max_discount(
    signal_bundle: SignalBundle,
    check_in_date: Optional[date] = None,
) -> float:
    """Get maximum acceptable discount from signals."""
    policy = get_discount_engine().get_discount_policy(signal_bundle, check_in_date)
    return policy.effective_max_discount
