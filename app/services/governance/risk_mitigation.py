"""
Risk Mitigation & Governance Module.

Addresses the three operational risks:
1. Overconfidence Drift - Hard caps, logging, auditing
2. Black Box Accusations - Transparency layers
3. Voice Tone Misalignment - Tenant-configurable tone

This is GOVERNANCE, not just code.
"""

from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Callable
from uuid import UUID, uuid4
import json
import hashlib

from pydantic import BaseModel, Field


# =============================================================================
# RISK 1: OVERCONFIDENCE DRIFT PREVENTION
# =============================================================================

class ConfidenceGovernance:
    """
    Hard caps and guardrails to prevent overconfidence drift.
    
    These are NON-NEGOTIABLE limits that cannot be overridden
    by configuration or pressure from operators.
    """
    
    # === HARD CAPS (Cannot be changed without code review) ===
    
    # Maximum operator uplift that can be applied (50% of observed)
    MAX_OPERATOR_UPLIFT_APPLICATION_RATE: float = 0.60
    
    # Minimum data required to use internal comps
    MIN_MONTHS_FOR_INTERNAL_COMPS: int = 6
    MIN_PROPERTIES_FOR_INTERNAL_COMPS: int = 3
    MIN_DATA_COVERAGE_PCT: float = 0.50
    
    # Maximum confidence score (never claim 100%)
    MAX_CONFIDENCE_SCORE: float = 0.95
    
    # Minimum confidence for voice claims
    MIN_CONFIDENCE_FOR_INTERNAL_VOICE_CLAIMS: float = 0.60
    MIN_CONFIDENCE_FOR_DISCOUNT_DENIAL: float = 0.65
    MIN_CONFIDENCE_FOR_STRONG_ASSERTIONS: float = 0.75
    
    # Rolling window requirements
    MIN_ROLLING_WINDOW_MONTHS: int = 12
    MAX_DATA_STALENESS_DAYS: int = 90
    
    @classmethod
    def validate_uplift_rate(cls, rate: float) -> float:
        """Enforce maximum uplift application rate."""
        if rate > cls.MAX_OPERATOR_UPLIFT_APPLICATION_RATE:
            return cls.MAX_OPERATOR_UPLIFT_APPLICATION_RATE
        return rate
    
    @classmethod
    def validate_confidence(cls, score: float) -> float:
        """Enforce maximum confidence score."""
        return min(score, cls.MAX_CONFIDENCE_SCORE)
    
    @classmethod
    def can_use_internal_comps(
        cls,
        months_of_data: int,
        property_count: int,
        data_coverage_pct: float,
    ) -> tuple[bool, str]:
        """Check if internal comps can be used."""
        if months_of_data < cls.MIN_MONTHS_FOR_INTERNAL_COMPS:
            return False, f"Insufficient data history ({months_of_data} months, need {cls.MIN_MONTHS_FOR_INTERNAL_COMPS})"
        
        if property_count < cls.MIN_PROPERTIES_FOR_INTERNAL_COMPS:
            return False, f"Insufficient comparable properties ({property_count}, need {cls.MIN_PROPERTIES_FOR_INTERNAL_COMPS})"
        
        if data_coverage_pct < cls.MIN_DATA_COVERAGE_PCT:
            return False, f"Insufficient data coverage ({data_coverage_pct:.0%}, need {cls.MIN_DATA_COVERAGE_PCT:.0%})"
        
        return True, "OK"
    
    @classmethod
    def can_make_voice_claim(
        cls,
        claim_type: str,
        confidence: float,
    ) -> tuple[bool, str]:
        """Check if a voice claim is allowed at this confidence level."""
        thresholds = {
            "internal_reference": cls.MIN_CONFIDENCE_FOR_INTERNAL_VOICE_CLAIMS,
            "discount_denial": cls.MIN_CONFIDENCE_FOR_DISCOUNT_DENIAL,
            "strong_assertion": cls.MIN_CONFIDENCE_FOR_STRONG_ASSERTIONS,
        }
        
        threshold = thresholds.get(claim_type, cls.MIN_CONFIDENCE_FOR_INTERNAL_VOICE_CLAIMS)
        
        if confidence < threshold:
            return False, f"Confidence {confidence:.0%} below threshold {threshold:.0%} for {claim_type}"
        
        return True, "OK"


@dataclass
class ConfidenceAuditLog:
    """
    Audit log entry for confidence-related decisions.
    
    Every time internal comps influence a decision, it's logged.
    """
    log_id: str = field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = field(default_factory=datetime.utcnow)
    
    # Context
    company_id: Optional[UUID] = None
    property_id: Optional[UUID] = None
    action_type: str = ""  # "projection", "voice_claim", "discount_decision"
    
    # What was used
    used_internal_comps: bool = False
    internal_comp_count: int = 0
    internal_data_months: int = 0
    
    # What was applied
    operator_delta_observed: float = 0.0
    operator_delta_applied: float = 0.0
    application_rate: float = 0.0
    
    # Confidence
    raw_confidence: float = 0.0
    capped_confidence: float = 0.0
    
    # Governance checks
    governance_checks_passed: List[str] = field(default_factory=list)
    governance_checks_failed: List[str] = field(default_factory=list)
    
    # Outcome
    decision_made: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "log_id": self.log_id,
            "timestamp": self.timestamp.isoformat(),
            "company_id": str(self.company_id) if self.company_id else None,
            "property_id": str(self.property_id) if self.property_id else None,
            "action_type": self.action_type,
            "used_internal_comps": self.used_internal_comps,
            "internal_comp_count": self.internal_comp_count,
            "operator_delta_observed": self.operator_delta_observed,
            "operator_delta_applied": self.operator_delta_applied,
            "raw_confidence": self.raw_confidence,
            "capped_confidence": self.capped_confidence,
            "governance_passed": self.governance_checks_passed,
            "governance_failed": self.governance_checks_failed,
            "decision": self.decision_made,
        }


# =============================================================================
# RISK 2: BLACK BOX PREVENTION - TRANSPARENCY LAYERS
# =============================================================================

class ExplanationLevel(str, Enum):
    """Level of detail for explanations."""
    SIMPLE = "simple"  # For owners/guests
    DETAILED = "detailed"  # For operators
    TECHNICAL = "technical"  # For audits


@dataclass
class TransparentExplanation:
    """
    Human-readable explanation of how something was calculated.
    
    Every projection, every decision, every recommendation
    should be able to produce this.
    """
    summary: str  # One sentence
    
    # Step-by-step breakdown
    steps: List[Dict[str, str]] = field(default_factory=list)
    
    # Key factors
    key_factors: List[str] = field(default_factory=list)
    
    # Confidence explanation
    confidence_explanation: str = ""
    
    # What could change this
    sensitivity_notes: List[str] = field(default_factory=list)
    
    # Data sources
    data_sources: List[str] = field(default_factory=list)
    
    # Caveats
    caveats: List[str] = field(default_factory=list)


class TransparencyEngine:
    """
    Generates human-readable explanations for all calculations.
    
    This prevents "black box" accusations by making
    the reasoning visible and understandable.
    """
    
    @staticmethod
    def explain_projection(
        reasoning: Dict[str, Any],
        level: ExplanationLevel = ExplanationLevel.SIMPLE,
    ) -> TransparentExplanation:
        """Generate explanation for a rent projection."""
        
        # Build summary
        source = reasoning.get("base_adr_source", "market data")
        confidence = reasoning.get("overall_confidence", 0.5)
        
        if source == "blended":
            summary = "This projection blends your portfolio's actual performance with market data."
        elif source == "internal_comps":
            summary = "This projection is based on similar properties you already manage."
        else:
            summary = "This projection is based on comparable properties in the market."
        
        # Build steps
        steps = []
        
        # Step 1: Base rate
        base_adr = reasoning.get("base_adr", 0)
        internal_weight = reasoning.get("final_comp_weight_internal", 0)
        
        if internal_weight > 0:
            steps.append({
                "step": "1. Determine base rate",
                "explanation": f"We looked at {int(internal_weight*100)}% your portfolio and {int((1-internal_weight)*100)}% market data",
            })
        else:
            steps.append({
                "step": "1. Determine base rate",
                "explanation": "Based on comparable properties in the market",
            })
        
        # Step 2: Operator performance
        delta = reasoning.get("operator_delta")
        if delta:
            observed = delta.get("adr_delta_pct", 0)
            applied = delta.get("adr_delta_applied", 0)
            steps.append({
                "step": "2. Adjust for your track record",
                "explanation": f"Your properties perform {observed*100:.0f}% above market. We conservatively applied {applied*100:.0f}%.",
            })
        
        # Step 3: Amenity adjustments
        uplifts = reasoning.get("uplifts_applied", [])
        if uplifts:
            uplift_summary = ", ".join([u.get("reason", u.get("name", "")) for u in uplifts[:3]])
            steps.append({
                "step": "3. Adjust for amenities",
                "explanation": f"Adjustments for: {uplift_summary}",
            })
        
        # Step 4: Seasonality
        steps.append({
            "step": "4. Apply seasonal patterns",
            "explanation": "Rates vary by month based on historical demand patterns",
        })
        
        # Key factors
        key_factors = []
        if delta and delta.get("adr_delta_pct", 0) > 0.05:
            key_factors.append("Your portfolio outperforms the market")
        for uplift in uplifts:
            key_factors.append(uplift.get("reason", ""))
        
        # Confidence explanation
        if confidence >= 0.8:
            conf_exp = "High confidence based on strong data coverage and comparable properties."
        elif confidence >= 0.6:
            conf_exp = "Medium confidence. More data from your portfolio would improve accuracy."
        else:
            conf_exp = "Lower confidence due to limited comparable data. Consider this a rough estimate."
        
        # Caveats
        caveats = [
            "Actual performance depends on pricing strategy, marketing, and guest experience.",
            "Projections assume consistent market conditions.",
            "New listings typically take 2-3 months to reach projected performance.",
        ]
        
        # Safely get comp counts
        internal_analysis = reasoning.get('internal_comp_analysis') or {}
        external_analysis = reasoning.get('external_comp_analysis') or {}
        
        return TransparentExplanation(
            summary=summary,
            steps=steps,
            key_factors=key_factors[:5],
            confidence_explanation=conf_exp,
            sensitivity_notes=[
                "±10% occupancy changes revenue by roughly the same percentage",
                "Rate changes have similar impact",
            ],
            data_sources=[
                f"Internal portfolio: {internal_analysis.get('comp_count', 0)} properties",
                f"Market data: {external_analysis.get('comp_count', 0)} comparables",
            ],
            caveats=caveats,
        )
    
    @staticmethod
    def explain_discount_decision(
        decision: str,
        reason: str,
        internal_occupancy: float,
        confidence: float,
    ) -> TransparentExplanation:
        """Generate explanation for a discount decision."""
        
        if decision == "deny":
            summary = "We recommend holding the current rate based on strong demand."
        elif decision == "deny_with_alternative":
            summary = "Rate adjustment not recommended, but alternatives available."
        elif decision == "approve_small":
            summary = "A small discount may help secure this booking."
        else:
            summary = "This decision requires human review."
        
        steps = [
            {
                "step": "1. Check portfolio occupancy",
                "explanation": f"Similar properties are at {internal_occupancy*100:.0f}% occupancy for this period",
            },
            {
                "step": "2. Evaluate confidence",
                "explanation": f"Data confidence is {confidence*100:.0f}%",
            },
            {
                "step": "3. Apply policy",
                "explanation": f"Reason: {reason}",
            },
        ]
        
        return TransparentExplanation(
            summary=summary,
            steps=steps,
            key_factors=[f"Portfolio occupancy: {internal_occupancy*100:.0f}%"],
            confidence_explanation=f"Based on {confidence*100:.0f}% confidence in current data",
            caveats=["Final decision should consider guest relationship and booking value"],
        )


# =============================================================================
# RISK 3: VOICE TONE ALIGNMENT
# =============================================================================

class VoiceTone(str, Enum):
    """Voice tone presets."""
    LUXURY_CONCIERGE = "luxury_concierge"  # Warm, accommodating, premium feel
    PROFESSIONAL = "professional"  # Clear, confident, businesslike
    FRIENDLY = "friendly"  # Casual, approachable
    FIRM = "firm"  # Direct, confident, boundary-setting


@dataclass
class TenantVoiceConfig:
    """
    Tenant-specific voice configuration.
    
    Allows operators to customize HOW things are said
    while the engine controls WHAT is said.
    """
    tenant_id: UUID
    
    # Tone
    default_tone: VoiceTone = VoiceTone.PROFESSIONAL
    discount_denial_tone: VoiceTone = VoiceTone.PROFESSIONAL
    
    # Branding
    brand_name: str = "we"
    property_term: str = "homes"
    team_reference: str = "our team"
    
    # Phrase preferences
    greeting_style: str = "warm"  # "warm", "formal", "casual"
    use_guest_name: bool = True
    
    # Custom phrases (override defaults)
    custom_phrases: Dict[str, str] = field(default_factory=dict)
    
    # Version for tracking changes
    version: str = "1.0"
    updated_at: datetime = field(default_factory=datetime.utcnow)


class TonePhraseLibrary:
    """
    Phrase library organized by tone.
    
    Same meaning, different delivery based on operator preference.
    """
    
    DISCOUNT_DENIAL = {
        VoiceTone.LUXURY_CONCIERGE: {
            "opening": "Thank you so much for reaching out about this.",
            "denial": "For these dates, our similar properties are seeing wonderful demand at the current rate.",
            "alternative": "While we're unable to adjust the rate, I'd love to offer you",
            "closing": "Would that enhance your stay with us?",
        },
        VoiceTone.PROFESSIONAL: {
            "opening": "Thank you for your inquiry.",
            "denial": "For these dates, similar properties we manage are booking at the current rate.",
            "alternative": "While we can't adjust the price, I can offer",
            "closing": "Would that work for you?",
        },
        VoiceTone.FRIENDLY: {
            "opening": "Hey, thanks for asking!",
            "denial": "For those dates, our similar places are filling up at this rate.",
            "alternative": "I can't budge on price, but how about",
            "closing": "Sound good?",
        },
        VoiceTone.FIRM: {
            "opening": "Thank you for your interest.",
            "denial": "This rate reflects current demand and the value of the property.",
            "alternative": "The rate is firm, however I can offer",
            "closing": "Let me know if you'd like to proceed.",
        },
    }
    
    RATE_JUSTIFICATION = {
        VoiceTone.LUXURY_CONCIERGE: {
            "high_demand": "This is our most sought-after season, and this home offers an exceptional experience.",
            "premium_amenities": "This rate reflects the premium amenities and attention to detail you'll enjoy.",
            "track_record": "Our homes consistently deliver experiences that our guests treasure.",
        },
        VoiceTone.PROFESSIONAL: {
            "high_demand": "This is our peak season with strong demand.",
            "premium_amenities": "This rate reflects the home's premium amenities.",
            "track_record": "Similar homes we manage book at comparable rates.",
        },
        VoiceTone.FRIENDLY: {
            "high_demand": "These dates are super popular!",
            "premium_amenities": "You're getting a lot of great stuff with this place.",
            "track_record": "Our similar places go for about the same.",
        },
        VoiceTone.FIRM: {
            "high_demand": "This is a high-demand period.",
            "premium_amenities": "The rate reflects the property's features.",
            "track_record": "This is consistent with our portfolio pricing.",
        },
    }
    
    @classmethod
    def get_phrase(
        cls,
        category: str,
        key: str,
        tone: VoiceTone,
        custom_override: Optional[str] = None,
    ) -> str:
        """Get phrase for category/key with specified tone."""
        if custom_override:
            return custom_override
        
        library = getattr(cls, category.upper(), {})
        tone_phrases = library.get(tone, library.get(VoiceTone.PROFESSIONAL, {}))
        return tone_phrases.get(key, "")


# =============================================================================
# GOVERNANCE DASHBOARD DATA
# =============================================================================

@dataclass
class GovernanceMetrics:
    """
    Metrics for governance dashboard.
    
    Shows how the system is behaving and whether
    any limits are being approached.
    """
    period_start: date
    period_end: date
    
    # Usage
    total_projections: int = 0
    projections_using_internal_comps: int = 0
    voice_claims_made: int = 0
    discount_decisions: int = 0
    
    # Governance interventions
    uplift_caps_applied: int = 0  # Times we capped operator uplift
    confidence_caps_applied: int = 0  # Times we capped confidence
    claims_blocked_low_confidence: int = 0  # Voice claims blocked
    
    # Data quality
    avg_internal_comp_count: float = 0.0
    avg_data_coverage: float = 0.0
    avg_confidence_score: float = 0.0
    
    # By outcome
    discount_denials: int = 0
    discount_approvals: int = 0
    discount_escalations: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "period": f"{self.period_start} to {self.period_end}",
            "usage": {
                "total_projections": self.total_projections,
                "using_internal_comps": self.projections_using_internal_comps,
                "pct_using_internal": f"{self.projections_using_internal_comps/max(self.total_projections,1)*100:.1f}%",
            },
            "governance_interventions": {
                "uplift_caps": self.uplift_caps_applied,
                "confidence_caps": self.confidence_caps_applied,
                "claims_blocked": self.claims_blocked_low_confidence,
            },
            "data_quality": {
                "avg_comp_count": f"{self.avg_internal_comp_count:.1f}",
                "avg_coverage": f"{self.avg_data_coverage*100:.0f}%",
                "avg_confidence": f"{self.avg_confidence_score*100:.0f}%",
            },
            "discount_outcomes": {
                "denials": self.discount_denials,
                "approvals": self.discount_approvals,
                "escalations": self.discount_escalations,
            },
        }


# =============================================================================
# PDF "HOW THIS WAS CALCULATED" SECTION
# =============================================================================

def generate_pdf_methodology_section(
    reasoning: Dict[str, Any],
    transparency: TransparentExplanation,
) -> Dict[str, Any]:
    """
    Generate the "How This Was Calculated" section for PDFs.
    
    This is REQUIRED on every Pro Forma to prevent
    "black box" accusations.
    """
    # Safely get nested values
    internal_analysis = reasoning.get("internal_comp_analysis") or {}
    external_analysis = reasoning.get("external_comp_analysis") or {}
    operator_delta = reasoning.get("operator_delta") or {}
    
    return {
        "title": "How This Projection Was Calculated",
        "summary": transparency.summary,
        "methodology_steps": transparency.steps,
        "data_sources": {
            "internal_portfolio": internal_analysis.get("comp_count", 0),
            "market_comparables": external_analysis.get("comp_count", 0),
            "months_of_data": operator_delta.get("months_of_data", 0),
        },
        "confidence": {
            "score": f"{reasoning.get('overall_confidence', 0.5)*100:.0f}%",
            "explanation": transparency.confidence_explanation,
        },
        "key_assumptions": transparency.key_factors,
        "important_notes": transparency.caveats,
        "version": {
            "engine": reasoning.get("engine_version", "1.0.0"),
            "generated": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
            "input_hash": reasoning.get("input_hash", ""),
        },
    }
