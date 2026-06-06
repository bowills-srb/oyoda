"""
Voice-Safe Translation Layer.

Translates engine reasoning → natural language for voice agents.

CRITICAL PRINCIPLES:
1. Voice layer NEVER computes - it only consumes engine output
2. Expose REASONING, not raw numbers
3. Policy constraints live in CONFIG, not code
4. Fall back to market-only if confidence < threshold

This is what separates:
- A voice bot that talks
- A voice agent that speaks with the authority of the operator's actual performance
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID


# =============================================================================
# VOICE POLICY CONFIGURATION
# =============================================================================

@dataclass
class VoicePolicyConfig:
    """
    Voice guardrails as configuration, not code.
    
    NON-NEGOTIABLE RULES:
    - Never reference exact revenue numbers
    - Never claim guarantees
    - Never compare against named competitors
    - Always phrase as historical patterns, not promises
    - Fall back to market-only if confidence < threshold
    """
    
    # Confidence thresholds
    min_confidence_for_internal_reference: float = 0.6
    min_confidence_for_discount_denial: float = 0.7
    min_confidence_for_strong_claims: float = 0.8
    
    # Comp thresholds
    min_internal_comps_to_reference: int = 3
    min_months_data_to_reference: int = 6
    
    # What we can say
    allow_internal_comp_references: bool = True
    allow_performance_claims: bool = True
    allow_scarcity_statements: bool = True
    
    # What we NEVER say
    never_mention_exact_revenue: bool = True
    never_mention_exact_adr: bool = True
    never_guarantee_bookings: bool = True
    never_name_competitors: bool = True
    
    # Fallback behavior
    fallback_to_market_on_low_confidence: bool = True
    
    # Operator branding
    operator_name: str = "we"  # "Beach Habitats", "our team", etc.
    property_term: str = "homes"  # "properties", "vacation rentals", etc.


# =============================================================================
# VOICE CONTEXT (Simplified for Voice Consumption)
# =============================================================================

class ConfidenceLevel(str, Enum):
    """Voice-friendly confidence levels."""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class PricingPosture(str, Enum):
    """Pricing negotiation posture."""
    FIRM = "firm"  # High demand, don't discount
    FLEXIBLE = "flexible"  # Can negotiate
    EAGER = "eager"  # Want to fill, will discount


class DiscountDecision(str, Enum):
    """Discount recommendation."""
    DENY = "deny"
    DENY_WITH_ALTERNATIVE = "deny_with_alternative"
    APPROVE_SMALL = "approve_small"  # Up to 10%
    APPROVE_MODERATE = "approve_moderate"  # 10-20%
    ESCALATE = "escalate"  # Needs human review


@dataclass
class VoicePricingContext:
    """
    Simplified pricing context for voice agent consumption.
    
    The voice agent receives THIS, not raw engine output.
    All numbers are pre-translated to voice-safe statements.
    """
    # Property context
    property_id: Optional[UUID] = None
    property_summary: str = ""
    
    # Dates
    check_in: Optional[date] = None
    check_out: Optional[date] = None
    nights: int = 0
    days_until_checkin: int = 0
    
    # Current ask
    current_rate: float = 0.0
    total_price: float = 0.0
    
    # Posture (what the agent should project)
    pricing_posture: PricingPosture = PricingPosture.FIRM
    confidence_level: ConfidenceLevel = ConfidenceLevel.MEDIUM
    
    # Pre-translated statements (voice-safe)
    rate_justification: str = ""
    demand_statement: str = ""
    comp_statement: str = ""
    
    # Discount handling
    discount_decision: DiscountDecision = DiscountDecision.DENY
    discount_reason: str = ""
    alternative_offer: Optional[str] = None
    
    # What the agent CAN say
    approved_claims: List[str] = field(default_factory=list)
    
    # What the agent must NOT say
    prohibited_topics: List[str] = field(default_factory=list)
    
    # Escalation
    should_escalate: bool = False
    escalation_reason: Optional[str] = None


@dataclass  
class VoiceDiscountRequest:
    """A guest's discount request for evaluation."""
    property_id: UUID
    check_in: date
    check_out: date
    current_rate: float
    requested_discount_pct: float  # e.g., 0.10 for 10%
    guest_reason: Optional[str] = None  # "It's our anniversary", etc.


@dataclass
class VoiceDiscountResponse:
    """Engine's discount decision with voice-safe explanation."""
    decision: DiscountDecision
    
    # Voice-safe response components
    opening_statement: str
    reason_statement: str
    alternative_statement: Optional[str]
    closing_statement: str
    
    # Full suggested response
    suggested_response: str
    
    # Internal data (for logging, not for voice)
    internal_reasoning: Dict[str, Any] = field(default_factory=dict)


# =============================================================================
# VOICE PHRASE TEMPLATES
# =============================================================================

class VoicePhrases:
    """
    Pre-approved voice phrases mapped to engine facts.
    
    Engine Fact → Voice Expression
    
    These are the ONLY phrases the voice agent should use
    when referencing internal data.
    """
    
    # === INTERNAL COMP REFERENCES ===
    
    @staticmethod
    def internal_comp_count(count: int, min_threshold: int = 3) -> str:
        """Translate comp count to voice-safe statement."""
        if count >= 10:
            return "many similar homes we manage in this area"
        elif count >= 5:
            return "several similar homes we manage nearby"
        elif count >= min_threshold:
            return "similar homes we manage in the area"
        else:
            return "homes in this market"  # Fall back to generic
    
    @staticmethod
    def internal_performance(outperformance_pct: float) -> str:
        """Translate performance delta to voice-safe statement."""
        if outperformance_pct >= 0.15:
            return "consistently perform well above the local average"
        elif outperformance_pct >= 0.08:
            return "typically perform above the local average"
        elif outperformance_pct >= 0.03:
            return "perform competitively in this market"
        else:
            return "are priced in line with the local market"
    
    # === DEMAND / SCARCITY ===
    
    @staticmethod
    def demand_level(occupancy_rate: float, booking_pace: float) -> str:
        """Translate demand metrics to voice-safe statement."""
        if occupancy_rate >= 0.90 or booking_pace >= 1.2:
            return "These dates are in very high demand"
        elif occupancy_rate >= 0.75 or booking_pace >= 1.0:
            return "We're seeing strong interest for these dates"
        elif occupancy_rate >= 0.50:
            return "These dates are booking steadily"
        else:
            return "We have good availability for these dates"
    
    @staticmethod
    def scarcity_statement(days_until: int, occupancy: float) -> Optional[str]:
        """Generate scarcity statement if appropriate."""
        if days_until <= 14 and occupancy >= 0.85:
            return "Similar homes for these dates are filling quickly"
        elif days_until <= 30 and occupancy >= 0.90:
            return "Availability is limited for this period"
        return None
    
    # === RATE JUSTIFICATION ===
    
    @staticmethod
    def rate_justification(
        has_internal_comps: bool,
        is_peak_season: bool,
        has_premium_amenities: bool,
        confidence: float
    ) -> str:
        """Generate rate justification statement."""
        parts = []
        
        if is_peak_season:
            parts.append("this is our peak season")
        
        if has_premium_amenities:
            parts.append("this home has premium amenities")
        
        if has_internal_comps and confidence >= 0.7:
            parts.append("similar homes we manage book at comparable rates")
        
        if not parts:
            return "This rate reflects current market conditions"
        
        return "This rate reflects that " + ", and ".join(parts)
    
    # === DISCOUNT RESPONSES ===
    
    @staticmethod
    def discount_denial_firm(alternative: Optional[str] = None) -> str:
        """Firm but professional discount denial."""
        base = "For these dates, similar homes we manage are booking at the current rate."
        if alternative:
            return f"{base} While we can't adjust the price, {alternative}."
        return f"{base} We're confident this rate reflects the value of the home."
    
    @staticmethod
    def discount_denial_with_context(reason: str, alternative: Optional[str] = None) -> str:
        """Denial with specific context."""
        if alternative:
            return f"{reason} While we can't reduce the rate, {alternative}."
        return reason
    
    @staticmethod  
    def discount_approval(pct: float, reason: str) -> str:
        """Approved discount response."""
        pct_str = f"{int(pct * 100)}%"
        return f"I can offer a {pct_str} discount on this booking. {reason}"
    
    # === ALTERNATIVES ===
    
    ALTERNATIVES = {
        "late_checkout": "I can offer a complimentary late checkout",
        "early_checkin": "I can arrange an early check-in if available",
        "welcome_basket": "I can include a welcome basket",
        "future_discount": "I can note your interest for a future stay discount",
        "longer_stay": "I can offer a better rate if you extend your stay",
        "flexible_dates": "I might have better rates if your dates are flexible",
    }
    
    # === CONFIDENCE-BASED HEDGING ===
    
    @staticmethod
    def confidence_hedge(confidence: float) -> str:
        """Add appropriate hedging based on confidence."""
        if confidence >= 0.85:
            return ""  # No hedge needed
        elif confidence >= 0.70:
            return "Based on our experience, "
        elif confidence >= 0.50:
            return "Typically, "
        else:
            return "Generally speaking, "


# =============================================================================
# VOICE TRANSLATION ENGINE
# =============================================================================

class VoiceTranslationEngine:
    """
    Translates engine output to voice-safe context.
    
    The voice agent calls this to get:
    1. What it CAN say
    2. What it must NOT say
    3. Pre-approved phrases
    4. Discount decisions with scripts
    """
    
    def __init__(self, policy: VoicePolicyConfig = None):
        self.policy = policy or VoicePolicyConfig()
        self.phrases = VoicePhrases()
    
    def create_pricing_context(
        self,
        engine_reasoning: Dict[str, Any],
        property_summary: str,
        check_in: date,
        check_out: date,
        current_rate: float,
    ) -> VoicePricingContext:
        """
        Create voice-safe pricing context from engine reasoning.
        
        This is the main translation function.
        """
        nights = (check_out - check_in).days
        days_until = (check_in - date.today()).days
        
        # Extract from engine reasoning
        confidence = engine_reasoning.get("overall_confidence", 0.5)
        internal_analysis = engine_reasoning.get("internal_comp_analysis")
        operator_delta = engine_reasoning.get("operator_delta")
        uplifts = engine_reasoning.get("uplifts_applied", [])
        
        # Determine confidence level
        if confidence >= 0.8:
            confidence_level = ConfidenceLevel.HIGH
        elif confidence >= 0.6:
            confidence_level = ConfidenceLevel.MEDIUM
        else:
            confidence_level = ConfidenceLevel.LOW
        
        # Determine pricing posture
        pricing_posture = self._determine_posture(
            confidence, days_until, internal_analysis, operator_delta
        )
        
        # Build voice-safe statements
        comp_statement = self._build_comp_statement(internal_analysis, confidence)
        demand_statement = self._build_demand_statement(internal_analysis, days_until)
        rate_justification = self._build_rate_justification(
            internal_analysis, uplifts, confidence
        )
        
        # Determine discount handling
        discount_decision, discount_reason, alternative = self._determine_discount_posture(
            pricing_posture, confidence, days_until
        )
        
        # Build approved claims (Phase D: only at appropriate confidence)
        approved_claims = self._build_approved_claims(
            internal_analysis, operator_delta, confidence
        )
        
        # Build prohibited topics (Phase D: hard prohibitions)
        # These are ALWAYS prohibited regardless of confidence
        prohibited_topics = [
            "exact revenue numbers",
            "specific ADR amounts", 
            "competitor names",
            "competitor performance",
            "guaranteed bookings",
            "guarantee",
            "promise",
            "guaranteed outcomes",
            "percentage guarantees",
            "specific dollar amounts",
            "future booking certainty",
        ]
        
        return VoicePricingContext(
            property_summary=property_summary,
            check_in=check_in,
            check_out=check_out,
            nights=nights,
            days_until_checkin=days_until,
            current_rate=current_rate,
            total_price=current_rate * nights,
            pricing_posture=pricing_posture,
            confidence_level=confidence_level,
            rate_justification=rate_justification,
            demand_statement=demand_statement,
            comp_statement=comp_statement,
            discount_decision=discount_decision,
            discount_reason=discount_reason,
            alternative_offer=alternative,
            approved_claims=approved_claims,
            prohibited_topics=prohibited_topics,
        )
    
    def evaluate_discount_request(
        self,
        request: VoiceDiscountRequest,
        engine_reasoning: Dict[str, Any],
        internal_occupancy: float = 0.5,
        booking_pace: float = 1.0,
    ) -> VoiceDiscountResponse:
        """
        Evaluate a discount request and return voice-safe response.
        
        This is where internal comps drive negotiation decisions.
        """
        confidence = engine_reasoning.get("overall_confidence", 0.5)
        internal_analysis = engine_reasoning.get("internal_comp_analysis")
        operator_delta = engine_reasoning.get("operator_delta")
        
        days_until = (request.check_in - date.today()).days
        
        # Decision logic using internal comps
        decision, reason, alternative = self._make_discount_decision(
            request=request,
            internal_analysis=internal_analysis,
            internal_occupancy=internal_occupancy,
            booking_pace=booking_pace,
            days_until=days_until,
            confidence=confidence,
        )
        
        # Build voice response
        response = self._build_discount_response(
            decision=decision,
            reason=reason,
            alternative=alternative,
            request=request,
            confidence=confidence,
        )
        
        return response
    
    def _determine_posture(
        self,
        confidence: float,
        days_until: int,
        internal_analysis: Optional[Dict],
        operator_delta: Optional[Dict],
    ) -> PricingPosture:
        """Determine pricing posture based on data."""
        # High confidence + short lead time + good performance = FIRM
        if confidence >= 0.8 and days_until <= 60:
            if operator_delta and operator_delta.get("adr_delta_pct", 0) > 0.05:
                return PricingPosture.FIRM
        
        # Low confidence or long lead time = more flexible
        if confidence < 0.6 or days_until > 90:
            return PricingPosture.FLEXIBLE
        
        # Default to firm for medium confidence
        return PricingPosture.FIRM
    
    def _build_comp_statement(
        self,
        internal_analysis: Optional[Dict],
        confidence: float,
    ) -> str:
        """Build voice-safe comp statement."""
        if not internal_analysis:
            return ""
        
        if confidence < self.policy.min_confidence_for_internal_reference:
            return ""
        
        comp_count = internal_analysis.get("comp_count", 0)
        if comp_count < self.policy.min_internal_comps_to_reference:
            return ""
        
        return self.phrases.internal_comp_count(comp_count)
    
    def _build_demand_statement(
        self,
        internal_analysis: Optional[Dict],
        days_until: int,
    ) -> str:
        """Build voice-safe demand statement."""
        if not internal_analysis:
            return "We have availability for these dates"
        
        occupancy = internal_analysis.get("avg_occupancy", 0.5)
        
        # Check for scarcity
        scarcity = self.phrases.scarcity_statement(days_until, occupancy)
        if scarcity:
            return scarcity
        
        return self.phrases.demand_level(occupancy, 1.0)
    
    def _build_rate_justification(
        self,
        internal_analysis: Optional[Dict],
        uplifts: List[Dict],
        confidence: float,
    ) -> str:
        """Build voice-safe rate justification."""
        has_internal = internal_analysis and internal_analysis.get("comp_count", 0) >= 3
        has_premium = any(u.get("name") in ["pool", "waterfront", "gulf_view", "ocean_view"] for u in uplifts)
        
        # Check if peak season (simplified)
        is_peak = False  # Would check against seasonality
        
        justification = self.phrases.rate_justification(
            has_internal_comps=has_internal,
            is_peak_season=is_peak,
            has_premium_amenities=has_premium,
            confidence=confidence,
        )
        
        hedge = self.phrases.confidence_hedge(confidence)
        return hedge + justification
    
    def _determine_discount_posture(
        self,
        posture: PricingPosture,
        confidence: float,
        days_until: int,
    ) -> Tuple[DiscountDecision, str, Optional[str]]:
        """Determine default discount posture."""
        if posture == PricingPosture.FIRM:
            return (
                DiscountDecision.DENY_WITH_ALTERNATIVE,
                "High demand period",
                self.phrases.ALTERNATIVES["late_checkout"]
            )
        elif posture == PricingPosture.EAGER:
            return (
                DiscountDecision.APPROVE_SMALL,
                "Flexible dates",
                None
            )
        else:
            return (
                DiscountDecision.DENY_WITH_ALTERNATIVE,
                "Standard pricing",
                self.phrases.ALTERNATIVES["flexible_dates"]
            )
    
    def _build_approved_claims(
        self,
        internal_analysis: Optional[Dict],
        operator_delta: Optional[Dict],
        confidence: float,
    ) -> List[str]:
        """
        Build list of claims the agent is approved to make.
        
        PHASE D GUARDRAILS:
        > 0.80 confidence: FIRM claims allowed
        0.65-0.80: CAUTIOUS claims only
        0.55-0.65: EXPLORATORY claims only
        < 0.55: Must ESCALATE to human
        """
        from app.services.guardrails.phase_guardrails import (
            get_voice_permission, 
            VoicePermission,
            VoiceConfidenceGates,
        )
        
        permission = get_voice_permission(confidence)
        claims = []
        
        # FIRM (>0.80): Can make strong claims
        if permission == VoicePermission.FIRM:
            if internal_analysis and internal_analysis.get("comp_count", 0) >= 3:
                claims.append("Reference similar homes we manage")
                claims.append("Make confident statements about pricing")
            
            if operator_delta and operator_delta.get("adr_delta_pct", 0) > 0.05:
                claims.append("Mention our homes perform above market average")
            
            claims.append("Reference booking patterns")
        
        # CAUTIOUS (0.65-0.80): Moderate claims only
        elif permission == VoicePermission.CAUTIOUS:
            if internal_analysis and internal_analysis.get("comp_count", 0) >= 3:
                claims.append("Reference current market indicators")
                claims.append("Mention comparable properties")
        
        # EXPLORATORY (0.55-0.65): Very limited claims
        elif permission == VoicePermission.EXPLORATORY:
            claims.append("Share preliminary analysis")
            claims.append("Note that ranges are wider")
        
        # ESCALATE (<0.55): No claims, must escalate
        else:
            claims.append("MUST ESCALATE TO HUMAN - confidence too low")
        
        return claims
    
    def _make_discount_decision(
        self,
        request: VoiceDiscountRequest,
        internal_analysis: Optional[Dict],
        internal_occupancy: float,
        booking_pace: float,
        days_until: int,
        confidence: float,
    ) -> Tuple[DiscountDecision, str, Optional[str]]:
        """
        Make discount decision using internal comps.
        
        This is the core negotiation logic.
        """
        # Protected period (high demand) - always deny
        if internal_occupancy >= 0.90 and booking_pace >= 1.1:
            return (
                DiscountDecision.DENY,
                "internal_comps_filling",
                self.phrases.ALTERNATIVES["late_checkout"]
            )
        
        # Short lead time + good occupancy - deny with alternative
        if days_until <= 14 and internal_occupancy >= 0.75:
            return (
                DiscountDecision.DENY_WITH_ALTERNATIVE,
                "short_lead_high_demand",
                self.phrases.ALTERNATIVES["early_checkin"]
            )
        
        # Long lead time + low confidence - escalate
        if days_until > 90 and confidence < 0.6:
            return (
                DiscountDecision.ESCALATE,
                "low_confidence_long_lead",
                None
            )
        
        # Moderate discount request + moderate demand - small approval
        if request.requested_discount_pct <= 0.10 and internal_occupancy < 0.60:
            return (
                DiscountDecision.APPROVE_SMALL,
                "fill_opportunity",
                None
            )
        
        # Default: deny with alternative
        return (
            DiscountDecision.DENY_WITH_ALTERNATIVE,
            "standard_policy",
            self.phrases.ALTERNATIVES["longer_stay"]
        )
    
    def _build_discount_response(
        self,
        decision: DiscountDecision,
        reason: str,
        alternative: Optional[str],
        request: VoiceDiscountRequest,
        confidence: float,
    ) -> VoiceDiscountResponse:
        """Build complete voice response for discount request."""
        
        if decision == DiscountDecision.DENY:
            opening = "Thank you for asking."
            reason_stmt = self.phrases.discount_denial_firm(alternative)
            alt_stmt = None
            closing = "Is there anything else I can help with for your stay?"
            
        elif decision == DiscountDecision.DENY_WITH_ALTERNATIVE:
            opening = "I appreciate you reaching out about the rate."
            
            if reason == "internal_comps_filling":
                reason_stmt = "For these dates, similar homes we manage are booking at the current rate."
            elif reason == "short_lead_high_demand":
                reason_stmt = "With your check-in date approaching, we're seeing strong demand for this period."
            else:
                reason_stmt = "This rate reflects the value of the home and current market conditions."
            
            alt_stmt = f"While we can't adjust the price, {alternative}." if alternative else None
            closing = "Would that work for you?"
            
        elif decision == DiscountDecision.APPROVE_SMALL:
            pct = min(request.requested_discount_pct, 0.10)
            opening = "I'd be happy to help with that."
            reason_stmt = self.phrases.discount_approval(pct, "for your upcoming stay")
            alt_stmt = None
            closing = "Shall I apply that to your booking?"
            
        elif decision == DiscountDecision.APPROVE_MODERATE:
            pct = min(request.requested_discount_pct, 0.15)
            opening = "Let me see what I can do."
            reason_stmt = self.phrases.discount_approval(pct, "given the timing of your stay")
            alt_stmt = None
            closing = "Would you like me to proceed with that rate?"
            
        else:  # ESCALATE
            opening = "That's a great question."
            reason_stmt = "Let me connect you with our team to discuss the best options for your stay."
            alt_stmt = None
            closing = "They'll be able to review your specific situation."
        
        # Build full response
        parts = [opening, reason_stmt]
        if alt_stmt:
            parts.append(alt_stmt)
        parts.append(closing)
        
        suggested_response = " ".join(parts)
        
        return VoiceDiscountResponse(
            decision=decision,
            opening_statement=opening,
            reason_statement=reason_stmt,
            alternative_statement=alt_stmt,
            closing_statement=closing,
            suggested_response=suggested_response,
            internal_reasoning={
                "reason_code": reason,
                "confidence": confidence,
                "requested_discount": request.requested_discount_pct,
            }
        )
