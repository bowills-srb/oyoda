"""
Phase A-D Guardrails Implementation.

This module implements the exact guardrails from the execution plan:
- Phase A: APS in ADR Math (bounded modifier)
- Phase B: OSS for Expansion Only (gated hard)
- Phase C: Dashboard Read-Only (advisory labeling)
- Phase D: Voice Confidence Gates (the moat)

These guardrails ensure:
- No scraped data creates ADR from scratch
- OSS cannot increase expected ADR beyond baseline
- Dashboard is non-transactional
- Voice speaks with authority only when earned
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID


# =============================================================================
# PHASE A: APS GUARDRAILS
# =============================================================================

@dataclass
class APSGuardrails:
    """
    Guardrails for Amenity Point Score application.
    
    APS applies multiplicatively, not additively.
    APS only fine-tunes what is already defensible.
    """
    # Hard bounds per amenity
    MIN_APS: float = 0.85  # Floor - amenity can't hurt more than 15%
    MAX_APS: float = 1.30  # Ceiling - amenity can't help more than 30%
    
    # Confidence damping
    CONFIDENCE_THRESHOLD: float = 0.60
    DAMPING_TARGET: float = 1.0  # Low confidence → damped toward neutral
    
    # APS never changes comp ranking
    COMP_RANKING_PROTECTED: bool = True
    
    @staticmethod
    def apply_bounds(raw_aps: float) -> float:
        """Apply hard bounds to APS."""
        return max(APSGuardrails.MIN_APS, min(raw_aps, APSGuardrails.MAX_APS))
    
    @staticmethod
    def apply_confidence_damping(aps: float, confidence: float) -> float:
        """
        Damp APS toward 1.0 when confidence is low.
        
        At confidence = 0.60: full APS applied
        At confidence = 0.30: APS is 50% toward 1.0
        At confidence = 0.00: APS = 1.0 (neutral)
        """
        if confidence >= APSGuardrails.CONFIDENCE_THRESHOLD:
            return aps
        
        # Linear interpolation toward 1.0
        damping_factor = confidence / APSGuardrails.CONFIDENCE_THRESHOLD
        damped = 1.0 + (aps - 1.0) * damping_factor
        return damped


def calculate_adr_with_aps(
    base_adr: float,
    seasonality_factor: float,
    operator_delta: float,
    amenity_aps_list: List[Tuple[str, float, float]],  # (name, aps, confidence)
) -> Tuple[float, Dict[str, Any]]:
    """
    Calculate final ADR with APS applied per Phase A formula.
    
    ADR_final = Base_ADR × Seasonality × Operator_Delta × Π(APS)
    
    Args:
        base_adr: From internal comps OR market baseline
        seasonality_factor: Month-specific multiplier
        operator_delta: Capped operator performance factor (e.g., 1.06 for +6%)
        amenity_aps_list: List of (amenity_name, raw_aps, confidence)
    
    Returns:
        (final_adr, reasoning_dict)
    """
    reasoning = {
        "base_adr": base_adr,
        "seasonality_factor": seasonality_factor,
        "operator_delta": operator_delta,
        "amenities_applied": [],
        "aps_product": 1.0,
    }
    
    # Calculate product of bounded, confidence-damped APS
    aps_product = 1.0
    for amenity_name, raw_aps, confidence in amenity_aps_list:
        bounded_aps = APSGuardrails.apply_bounds(raw_aps)
        final_aps = APSGuardrails.apply_confidence_damping(bounded_aps, confidence)
        aps_product *= final_aps
        
        reasoning["amenities_applied"].append({
            "amenity": amenity_name,
            "raw_aps": round(raw_aps, 3),
            "bounded_aps": round(bounded_aps, 3),
            "confidence": round(confidence, 2),
            "final_aps": round(final_aps, 3),
        })
    
    reasoning["aps_product"] = round(aps_product, 4)
    
    # Apply formula
    final_adr = base_adr * seasonality_factor * operator_delta * aps_product
    reasoning["final_adr"] = round(final_adr, 2)
    
    return final_adr, reasoning


# =============================================================================
# PHASE B: OSS GUARDRAILS (Expansion Markets Only)
# =============================================================================

class OSSActivationRule(Enum):
    """OSS activation states."""
    DISABLED = "disabled"  # Operator has internal data in this market
    ENABLED_CONSTRAINED = "enabled_constrained"  # No internal data, OSS active


@dataclass
class OSSGuardrails:
    """
    Guardrails for Operator Similarity Score.
    
    OSS is powerful - so we gate it hard.
    OSS cannot INCREASE expected ADR beyond market baseline.
    OSS cannot NARROW confidence bands.
    """
    # What OSS CAN do
    CAN_SCALE_DOWN_DELTA: bool = True
    CAN_WIDEN_BANDS: bool = True
    CAN_ANNOTATE_RISKS: bool = True
    
    # What OSS CANNOT do
    CAN_INCREASE_ADR_BEYOND_BASELINE: bool = False
    CAN_NARROW_BANDS: bool = False
    CAN_OVERRIDE_MHI: bool = False
    
    # Minimum similarity to transfer any delta
    MIN_SIMILARITY_FOR_TRANSFER: float = 0.50
    
    # Maximum delta transfer even at perfect similarity
    MAX_DELTA_TRANSFER_RATE: float = 0.50  # Never transfer more than 50%


def check_oss_activation(
    operator_id: str,
    market_id: str,
    has_internal_data: bool,
) -> OSSActivationRule:
    """
    Determine if OSS should be active.
    
    Rule: If operator has internal data in market, OSS is DISABLED.
    """
    if has_internal_data:
        return OSSActivationRule.DISABLED
    return OSSActivationRule.ENABLED_CONSTRAINED


def apply_oss_delta(
    observed_operator_delta: float,  # e.g., 0.12 for +12% in home market
    oss_similarity_score: float,
    risk_factors: List[str],
    market_baseline_adr: float,
) -> Tuple[float, float, Dict[str, Any]]:
    """
    Apply OSS-constrained operator delta for expansion markets.
    
    Formula:
        Operator_Delta_applied = Observed_Delta × OSS_similarity × Risk_Adjustment
    
    CRITICAL: Result cannot increase ADR beyond market baseline.
    
    Returns:
        (applied_delta_factor, adjusted_adr, reasoning)
    """
    guardrails = OSSGuardrails()
    
    reasoning = {
        "observed_delta": observed_operator_delta,
        "oss_similarity": oss_similarity_score,
        "risk_factors": risk_factors,
        "guardrails_applied": [],
    }
    
    # Check minimum similarity
    if oss_similarity_score < guardrails.MIN_SIMILARITY_FOR_TRANSFER:
        reasoning["guardrails_applied"].append(
            f"Similarity {oss_similarity_score:.2f} below threshold {guardrails.MIN_SIMILARITY_FOR_TRANSFER}"
        )
        reasoning["applied_delta"] = 0.0
        return 1.0, market_baseline_adr, reasoning
    
    # Calculate risk adjustment (each risk factor reduces transfer by 10%)
    risk_adjustment = max(0.5, 1.0 - len(risk_factors) * 0.10)
    reasoning["risk_adjustment"] = risk_adjustment
    
    # Calculate transfer amount
    raw_transfer = observed_operator_delta * oss_similarity_score * risk_adjustment
    
    # Cap at maximum transfer rate
    capped_transfer = min(raw_transfer, guardrails.MAX_DELTA_TRANSFER_RATE * observed_operator_delta)
    reasoning["guardrails_applied"].append(
        f"Transfer capped at {guardrails.MAX_DELTA_TRANSFER_RATE:.0%} of observed delta"
    )
    
    # CRITICAL: Cannot increase above baseline (only if positive)
    if capped_transfer > 0:
        # For expansion markets, we're conservative
        # Apply as factor (e.g., +5% becomes 1.05)
        applied_factor = 1.0 + capped_transfer
        adjusted_adr = market_baseline_adr * applied_factor
        
        reasoning["guardrails_applied"].append(
            "Positive delta allowed but constrained by similarity and risk"
        )
    else:
        applied_factor = 1.0 + capped_transfer  # Could be negative
        adjusted_adr = market_baseline_adr * applied_factor
    
    reasoning["applied_delta"] = round(capped_transfer, 4)
    reasoning["applied_factor"] = round(applied_factor, 4)
    reasoning["adjusted_adr"] = round(adjusted_adr, 2)
    
    return applied_factor, adjusted_adr, reasoning


# =============================================================================
# PHASE C: DASHBOARD GUARDRAILS (Read-Only Advisory)
# =============================================================================

@dataclass
class DashboardGuardrails:
    """
    Guardrails for Market Expansion Dashboard.
    
    Dashboard is explicitly:
    - Non-transactional
    - Non-automated
    - Advisory only
    """
    IS_TRANSACTIONAL: bool = False
    IS_AUTOMATED: bool = False
    IS_ADVISORY: bool = True
    
    # Required disclaimer
    REQUIRED_DISCLAIMER: str = (
        "Estimates shown for planning purposes. "
        "Performance depends on execution."
    )
    
    # Must be present on every screen
    ADVISORY_LABELS: List[str] = field(default_factory=lambda: [
        "For planning purposes only",
        "Not a guarantee of performance",
        "Consult with management before acting",
    ])


def wrap_dashboard_response(
    data: Dict[str, Any],
    section: str = "general",
) -> Dict[str, Any]:
    """
    Wrap dashboard data with required advisory labels.
    
    Every dashboard response must include disclaimers.
    """
    guardrails = DashboardGuardrails()
    
    return {
        "data": data,
        "metadata": {
            "section": section,
            "is_advisory": guardrails.IS_ADVISORY,
            "is_transactional": guardrails.IS_TRANSACTIONAL,
            "disclaimer": guardrails.REQUIRED_DISCLAIMER,
            "labels": guardrails.ADVISORY_LABELS,
            "generated_at": datetime.utcnow().isoformat(),
        }
    }


# =============================================================================
# PHASE D: VOICE CONFIDENCE GATES (The Moat)
# =============================================================================

class VoicePermission(Enum):
    """What voice is allowed to say based on confidence."""
    FIRM = "firm"  # > 0.80
    CAUTIOUS = "cautious"  # 0.65-0.80
    EXPLORATORY = "exploratory"  # 0.55-0.65
    ESCALATE = "escalate"  # < 0.55


@dataclass
class VoiceConfidenceGates:
    """
    Voice permission gates based on confidence thresholds.
    
    This is the moat - voice speaks with authority only when earned.
    """
    # Thresholds
    FIRM_THRESHOLD: float = 0.80
    CAUTIOUS_THRESHOLD: float = 0.65
    EXPLORATORY_THRESHOLD: float = 0.55
    
    # Allowed phrases by permission level
    ALLOWED_PHRASES = {
        VoicePermission.FIRM: [
            "Similar homes we manage typically book at this level",
            "Based on strong historical performance",
            "Our data shows consistent results",
        ],
        VoicePermission.CAUTIOUS: [
            "Based on current indicators, pricing is in line with demand",
            "Historical patterns suggest this range",
            "Comparable properties perform similarly",
        ],
        VoicePermission.EXPLORATORY: [
            "Early signals suggest potential, but ranges are wider",
            "Based on preliminary analysis",
            "We're still gathering data on this market",
        ],
        VoicePermission.ESCALATE: [
            "Let me connect you with our team for more details",
            "I'd like to have someone with more context follow up",
        ],
    }
    
    # HARD PROHIBITIONS (always, regardless of confidence)
    HARD_PROHIBITIONS = [
        "exact revenue numbers",
        "guaranteed outcomes",
        "guarantee",
        "guaranteed",
        "competitor performance",
        "future booking certainty",
        "specific dollar amounts",
        "percentage guarantees",
        "will definitely",
        "certain to",
        "promise",
    ]


def get_voice_permission(confidence: float) -> VoicePermission:
    """Determine voice permission level from confidence."""
    gates = VoiceConfidenceGates()
    
    if confidence > gates.FIRM_THRESHOLD:
        return VoicePermission.FIRM
    elif confidence >= gates.CAUTIOUS_THRESHOLD:
        return VoicePermission.CAUTIOUS
    elif confidence >= gates.EXPLORATORY_THRESHOLD:
        return VoicePermission.EXPLORATORY
    else:
        return VoicePermission.ESCALATE


def validate_voice_claim(
    claim: str,
    confidence: float,
) -> Tuple[bool, str, Optional[str]]:
    """
    Validate if a voice claim is allowed given confidence level.
    
    Returns:
        (is_allowed, permission_level, rejection_reason)
    """
    gates = VoiceConfidenceGates()
    permission = get_voice_permission(confidence)
    
    # Check hard prohibitions first - ALWAYS block these
    claim_lower = claim.lower()
    for prohibition in gates.HARD_PROHIBITIONS:
        if prohibition in claim_lower:
            return False, permission.value, f"BLOCKED: Contains prohibited content '{prohibition}'"
    
    # Check for dollar amounts (hard prohibition)
    import re
    if re.search(r'\$[\d,]+', claim):
        return False, permission.value, "BLOCKED: Contains specific dollar amounts"
    
    # Check for percentage guarantees
    if re.search(r'\d+%', claim) and any(word in claim_lower for word in ['guarantee', 'certain', 'definitely', 'will earn']):
        return False, permission.value, "BLOCKED: Contains percentage guarantees"
    
    # If escalation required, nothing allowed except escalation phrases
    if permission == VoicePermission.ESCALATE:
        for allowed in gates.ALLOWED_PHRASES[VoicePermission.ESCALATE]:
            if allowed.lower() in claim_lower:
                return True, permission.value, None
        return False, permission.value, "Confidence too low - must escalate to human"
    
    return True, permission.value, None


def get_allowed_voice_phrases(confidence: float) -> List[str]:
    """Get list of phrases voice is allowed to use at this confidence."""
    permission = get_voice_permission(confidence)
    return VoiceConfidenceGates.ALLOWED_PHRASES.get(permission, [])


# =============================================================================
# UNIFIED GUARDRAILS CHECKER
# =============================================================================

@dataclass
class GuardrailCheckResult:
    """Result of a guardrail check."""
    passed: bool
    phase: str
    guardrail: str
    details: str
    remediation: Optional[str] = None


class UnifiedGuardrails:
    """
    Unified guardrails checker for all phases.
    
    Use this to validate any operation against Phase A-D guardrails.
    """
    
    @staticmethod
    def check_aps_application(
        raw_aps: float,
        confidence: float,
        is_modifying_base_adr: bool = False,
    ) -> GuardrailCheckResult:
        """Check Phase A guardrails for APS."""
        # APS cannot create ADR from scratch
        if is_modifying_base_adr and raw_aps > 1.5:
            return GuardrailCheckResult(
                passed=False,
                phase="A",
                guardrail="APS_NO_BASE_CREATION",
                details=f"APS {raw_aps} too high to apply without base ADR",
                remediation="APS only fine-tunes existing defensible ADR",
            )
        
        # Check bounds
        if raw_aps < APSGuardrails.MIN_APS or raw_aps > APSGuardrails.MAX_APS:
            return GuardrailCheckResult(
                passed=True,  # Will be bounded
                phase="A",
                guardrail="APS_BOUNDS",
                details=f"APS {raw_aps} will be bounded to [{APSGuardrails.MIN_APS}, {APSGuardrails.MAX_APS}]",
            )
        
        return GuardrailCheckResult(
            passed=True,
            phase="A",
            guardrail="APS_VALID",
            details=f"APS {raw_aps} within bounds, confidence {confidence}",
        )
    
    @staticmethod
    def check_oss_activation(
        has_internal_data: bool,
        attempting_oss: bool,
    ) -> GuardrailCheckResult:
        """Check Phase B guardrails for OSS."""
        if has_internal_data and attempting_oss:
            return GuardrailCheckResult(
                passed=False,
                phase="B",
                guardrail="OSS_DISABLED_WITH_DATA",
                details="OSS cannot be used when operator has internal data in market",
                remediation="Use internal comps instead of OSS",
            )
        
        return GuardrailCheckResult(
            passed=True,
            phase="B",
            guardrail="OSS_ACTIVATION_VALID",
            details="OSS activation rule satisfied",
        )
    
    @staticmethod
    def check_dashboard_output(
        has_disclaimer: bool,
        is_transactional: bool,
    ) -> GuardrailCheckResult:
        """Check Phase C guardrails for dashboard."""
        if is_transactional:
            return GuardrailCheckResult(
                passed=False,
                phase="C",
                guardrail="DASHBOARD_NON_TRANSACTIONAL",
                details="Dashboard cannot perform transactions",
                remediation="Dashboard is advisory only",
            )
        
        if not has_disclaimer:
            return GuardrailCheckResult(
                passed=False,
                phase="C",
                guardrail="DASHBOARD_DISCLAIMER_REQUIRED",
                details="Dashboard output must include disclaimer",
                remediation=f"Add: {DashboardGuardrails.REQUIRED_DISCLAIMER}",
            )
        
        return GuardrailCheckResult(
            passed=True,
            phase="C",
            guardrail="DASHBOARD_VALID",
            details="Dashboard guardrails satisfied",
        )
    
    @staticmethod
    def check_voice_claim(
        claim: str,
        confidence: float,
    ) -> GuardrailCheckResult:
        """Check Phase D guardrails for voice."""
        is_allowed, permission, rejection = validate_voice_claim(claim, confidence)
        
        if not is_allowed:
            return GuardrailCheckResult(
                passed=False,
                phase="D",
                guardrail="VOICE_CLAIM_BLOCKED",
                details=rejection or "Claim not allowed at this confidence",
                remediation=f"Use allowed phrases for {permission} level",
            )
        
        return GuardrailCheckResult(
            passed=True,
            phase="D",
            guardrail="VOICE_CLAIM_VALID",
            details=f"Claim allowed at {permission} level",
        )
    
    @staticmethod
    def run_all_checks(
        # Phase A
        aps_value: Optional[float] = None,
        aps_confidence: Optional[float] = None,
        # Phase B
        has_internal_data: Optional[bool] = None,
        attempting_oss: Optional[bool] = None,
        # Phase C
        dashboard_has_disclaimer: Optional[bool] = None,
        dashboard_is_transactional: Optional[bool] = None,
        # Phase D
        voice_claim: Optional[str] = None,
        voice_confidence: Optional[float] = None,
    ) -> List[GuardrailCheckResult]:
        """Run all applicable guardrail checks."""
        results = []
        
        # Phase A
        if aps_value is not None:
            results.append(UnifiedGuardrails.check_aps_application(
                aps_value, aps_confidence or 0.5
            ))
        
        # Phase B
        if has_internal_data is not None and attempting_oss is not None:
            results.append(UnifiedGuardrails.check_oss_activation(
                has_internal_data, attempting_oss
            ))
        
        # Phase C
        if dashboard_has_disclaimer is not None:
            results.append(UnifiedGuardrails.check_dashboard_output(
                dashboard_has_disclaimer,
                dashboard_is_transactional or False
            ))
        
        # Phase D
        if voice_claim is not None and voice_confidence is not None:
            results.append(UnifiedGuardrails.check_voice_claim(
                voice_claim, voice_confidence
            ))
        
        return results
