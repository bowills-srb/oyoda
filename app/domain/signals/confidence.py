"""
Domain: Signals - Confidence Thresholds & Gating.

No FastAPI. No DB sessions. No external API calls.
Pure business rules for signal confidence.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional


# =============================================================================
# CONFIDENCE THRESHOLDS
# =============================================================================

class OutputType(str, Enum):
    """Types of outputs that require confidence gating."""
    # Voice outputs require high confidence
    VOICE_PRICING_CLAIM = "voice_pricing_claim"
    VOICE_DISCOUNT_DENIAL = "voice_discount_denial"
    VOICE_MARKET_ASSERTION = "voice_market_assertion"
    
    # BD outputs require medium-high confidence
    BD_PROJECTION = "bd_projection"
    BD_RECOMMENDATION = "bd_recommendation"
    BD_EXPANSION_SCORE = "bd_expansion_score"
    
    # Internal analytics can be lower
    INTERNAL_ANALYSIS = "internal_analysis"
    
    # Minimum to process at all
    MINIMUM_VIABLE = "minimum_viable"


@dataclass(frozen=True)
class ConfidenceThresholds:
    """
    Confidence thresholds that gate outputs.
    
    If confidence < threshold, output is restricted.
    These are immutable business rules.
    """
    # Voice outputs require high confidence
    VOICE_PRICING_CLAIM: float = 0.75
    VOICE_DISCOUNT_DENIAL: float = 0.70
    VOICE_MARKET_ASSERTION: float = 0.65
    
    # BD outputs require medium-high confidence
    BD_PROJECTION: float = 0.60
    BD_RECOMMENDATION: float = 0.65
    BD_EXPANSION_SCORE: float = 0.55
    
    # Internal analytics can be lower
    INTERNAL_ANALYSIS: float = 0.50
    
    # Minimum to process at all
    MINIMUM_VIABLE: float = 0.40


# Singleton instance
THRESHOLDS = ConfidenceThresholds()


# Lookup table for output types
_THRESHOLD_MAP: Dict[OutputType, float] = {
    OutputType.VOICE_PRICING_CLAIM: THRESHOLDS.VOICE_PRICING_CLAIM,
    OutputType.VOICE_DISCOUNT_DENIAL: THRESHOLDS.VOICE_DISCOUNT_DENIAL,
    OutputType.VOICE_MARKET_ASSERTION: THRESHOLDS.VOICE_MARKET_ASSERTION,
    OutputType.BD_PROJECTION: THRESHOLDS.BD_PROJECTION,
    OutputType.BD_RECOMMENDATION: THRESHOLDS.BD_RECOMMENDATION,
    OutputType.BD_EXPANSION_SCORE: THRESHOLDS.BD_EXPANSION_SCORE,
    OutputType.INTERNAL_ANALYSIS: THRESHOLDS.INTERNAL_ANALYSIS,
    OutputType.MINIMUM_VIABLE: THRESHOLDS.MINIMUM_VIABLE,
}


def get_threshold(output_type: OutputType) -> float:
    """Get threshold for an output type."""
    return _THRESHOLD_MAP.get(output_type, THRESHOLDS.MINIMUM_VIABLE)


def is_confidence_sufficient(confidence: float, output_type: OutputType) -> bool:
    """Check if confidence meets threshold for output type."""
    threshold = get_threshold(output_type)
    return confidence >= threshold


# =============================================================================
# GATING DECISIONS
# =============================================================================

@dataclass
class GatingDecision:
    """Result of a confidence gate check."""
    passed: bool
    confidence: float
    threshold: float
    output_type: OutputType
    shortfall: float  # How much below threshold (0 if passed)
    
    @property
    def message(self) -> str:
        """Human-readable explanation."""
        if self.passed:
            return f"Confidence {self.confidence:.2f} meets {self.output_type.value} threshold ({self.threshold:.2f})"
        return f"Confidence {self.confidence:.2f} below {self.output_type.value} threshold ({self.threshold:.2f}) by {self.shortfall:.2f}"


def check_confidence_gate(confidence: float, output_type: OutputType) -> GatingDecision:
    """
    Check confidence against gate threshold.
    
    Returns full decision object with explanation.
    """
    threshold = get_threshold(output_type)
    passed = confidence >= threshold
    shortfall = max(0.0, threshold - confidence)
    
    return GatingDecision(
        passed=passed,
        confidence=confidence,
        threshold=threshold,
        output_type=output_type,
        shortfall=shortfall,
    )


def check_multiple_gates(
    confidence: float,
    output_types: list[OutputType],
) -> Dict[OutputType, GatingDecision]:
    """Check confidence against multiple gates at once."""
    return {
        output_type: check_confidence_gate(confidence, output_type)
        for output_type in output_types
    }


# =============================================================================
# CONFIDENCE TIER CLASSIFICATION
# =============================================================================

class ConfidenceTier(str, Enum):
    """Confidence tier for quick classification."""
    HIGH = "high"         # >= 0.75 - Voice-ready
    MEDIUM_HIGH = "medium_high"  # >= 0.65 - BD-ready
    MEDIUM = "medium"     # >= 0.50 - Internal analytics
    LOW = "low"           # >= 0.40 - Minimum viable
    INSUFFICIENT = "insufficient"  # < 0.40 - Cannot use


def classify_confidence(confidence: float) -> ConfidenceTier:
    """Classify confidence into a tier."""
    if confidence >= 0.75:
        return ConfidenceTier.HIGH
    elif confidence >= 0.65:
        return ConfidenceTier.MEDIUM_HIGH
    elif confidence >= 0.50:
        return ConfidenceTier.MEDIUM
    elif confidence >= 0.40:
        return ConfidenceTier.LOW
    else:
        return ConfidenceTier.INSUFFICIENT


def get_allowed_outputs(confidence: float) -> list[OutputType]:
    """Get list of output types allowed at a confidence level."""
    allowed = []
    for output_type in OutputType:
        if is_confidence_sufficient(confidence, output_type):
            allowed.append(output_type)
    return allowed


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Types
    "OutputType",
    "ConfidenceTier",
    
    # Thresholds
    "ConfidenceThresholds",
    "THRESHOLDS",
    "get_threshold",
    "is_confidence_sufficient",
    
    # Gating
    "GatingDecision",
    "check_confidence_gate",
    "check_multiple_gates",
    
    # Classification
    "classify_confidence",
    "get_allowed_outputs",
]
