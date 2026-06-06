"""
Platform Dominance Service - Signal Consumer Only.

Phase 2 of Master Refactor Plan:
- PlatformDominanceDetector is AUTHORITATIVE  
- This service CONSUMES signals only
- NO inline dominance calculation
- NO EWMA logic (that's in the detector)

DELETED FROM CODEBASE:
- PlatformWeightingEngine dominance calculation
- EWMA calculator (moved to central decay)
- Inline platform weight computation

Usage:
    from app.services.signals.platform import get_platform_bias
    
    bias = get_platform_bias(signal_bundle)
    # bias.dominant_platform = "airbnb"
    # bias.airbnb_weight = 0.65
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from uuid import UUID

from app.services.signals.signal_contract import (
    Signal,
    SignalBundle,
    SignalType,
    very_slow_decay,
    ConfidenceThresholds,
)


# =============================================================================
# PLATFORM DOMINANCE RESULT
# =============================================================================

@dataclass
class PlatformDominanceResult:
    """
    Result of platform dominance lookup.
    
    Contains platform distribution and bias information.
    """
    # Dominant platform
    dominant_platform: str
    
    # Distribution (should sum to ~1.0)
    airbnb_share: float
    vrbo_share: float
    other_share: float
    
    # Confidence
    confidence: float
    
    # Signal metadata
    has_signal: bool = False
    signal_id: Optional[UUID] = None
    signal_age_days: Optional[int] = None
    
    def is_usable_for_voice(self) -> bool:
        """Can this be used for voice claims?"""
        return self.confidence >= ConfidenceThresholds.VOICE_MARKET_ASSERTION
    
    def is_usable_for_bd(self) -> bool:
        """Can this be used for BD projections?"""
        return self.confidence >= ConfidenceThresholds.BD_PROJECTION
    
    def is_airbnb_dominant(self) -> bool:
        """Is Airbnb the dominant platform?"""
        return self.dominant_platform == "airbnb"
    
    def is_vrbo_dominant(self) -> bool:
        """Is VRBO the dominant platform?"""
        return self.dominant_platform == "vrbo"
    
    def is_balanced(self) -> bool:
        """Is market relatively balanced between platforms?"""
        return abs(self.airbnb_share - self.vrbo_share) < 0.15
    
    def get_weight_for_platform(self, platform: str) -> float:
        """Get weight to apply for a specific platform."""
        weights = {
            "airbnb": self.airbnb_share,
            "vrbo": self.vrbo_share,
            "other": self.other_share,
            "booking": self.other_share * 0.5,  # Rough split
        }
        return weights.get(platform.lower(), 0.0)


# =============================================================================
# PLATFORM DOMINANCE SERVICE
# =============================================================================

class PlatformDominanceService:
    """
    Platform dominance service - CONSUMES signals only.
    
    RULES:
    1. Only reads from SignalBundle
    2. NO inline dominance calculation
    3. NO EWMA (decay is centralized)
    4. Missing signal = balanced assumption with LOW confidence
    
    The PlatformDominanceDetector is the ONLY source of truth.
    """
    
    # Neutral fallback (balanced market assumption)
    NEUTRAL_AIRBNB = 0.50
    NEUTRAL_VRBO = 0.35
    NEUTRAL_OTHER = 0.15
    NEUTRAL_CONFIDENCE = 0.3  # Low - will gate outputs
    
    def get_platform_dominance(
        self,
        signal_bundle: SignalBundle,
    ) -> PlatformDominanceResult:
        """
        Get platform dominance from signals.
        
        The signal value represents: airbnb_share - vrbo_share
        Positive = Airbnb dominant, Negative = VRBO dominant
        
        Args:
            signal_bundle: Bundle containing PLATFORM_DOMINANCE signals
        
        Returns:
            PlatformDominanceResult with distribution and confidence
        """
        # Get weighted value
        value, confidence = signal_bundle.get_weighted_with_confidence(
            SignalType.PLATFORM_DOMINANCE,
            decay_fn=very_slow_decay,
        )
        
        if value is None:
            # No signal - return balanced with low confidence
            return PlatformDominanceResult(
                dominant_platform="airbnb",  # Slight default
                airbnb_share=self.NEUTRAL_AIRBNB,
                vrbo_share=self.NEUTRAL_VRBO,
                other_share=self.NEUTRAL_OTHER,
                confidence=self.NEUTRAL_CONFIDENCE,
                has_signal=False,
            )
        
        # Get latest signal for detailed distribution
        latest_signal = signal_bundle.get_latest(SignalType.PLATFORM_DOMINANCE)
        
        # Try to get explicit distribution from metadata
        airbnb_share = self.NEUTRAL_AIRBNB
        vrbo_share = self.NEUTRAL_VRBO
        other_share = self.NEUTRAL_OTHER
        
        if latest_signal and latest_signal.metadata:
            distribution = latest_signal.metadata.get("distribution", {})
            if distribution:
                airbnb_share = distribution.get("airbnb", airbnb_share)
                vrbo_share = distribution.get("vrbo", vrbo_share)
                other_share = distribution.get("other", 
                    distribution.get("booking", 0) + 
                    distribution.get("direct", 0) +
                    other_share
                )
        else:
            # Infer from value (airbnb_share - vrbo_share)
            # value = 0.62 means airbnb has 62% more than vrbo
            # Approximate: if value > 0, airbnb dominant
            total_major = 0.85  # airbnb + vrbo
            if value >= 0:
                # Airbnb dominant
                airbnb_share = min(0.80, 0.50 + value * 0.3)
                vrbo_share = total_major - airbnb_share
            else:
                # VRBO dominant
                vrbo_share = min(0.70, 0.35 + abs(value) * 0.3)
                airbnb_share = total_major - vrbo_share
            other_share = 1.0 - airbnb_share - vrbo_share
        
        # Determine dominant
        if airbnb_share > vrbo_share:
            dominant = "airbnb"
        elif vrbo_share > airbnb_share:
            dominant = "vrbo"
        else:
            dominant = "balanced"
        
        # Signal age
        signal_age_days = None
        if latest_signal:
            signal_age_days = (datetime.utcnow() - latest_signal.detected_at).days
        
        return PlatformDominanceResult(
            dominant_platform=dominant,
            airbnb_share=airbnb_share,
            vrbo_share=vrbo_share,
            other_share=other_share,
            confidence=confidence,
            has_signal=True,
            signal_id=latest_signal.id if latest_signal else None,
            signal_age_days=signal_age_days,
        )
    
    def get_platform_weights(
        self,
        signal_bundle: SignalBundle,
    ) -> Tuple[Dict[str, float], float]:
        """
        Get platform weights for weighting data sources.
        
        Returns:
            ({"airbnb": 0.65, "vrbo": 0.25, ...}, confidence)
        """
        result = self.get_platform_dominance(signal_bundle)
        
        weights = {
            "airbnb": result.airbnb_share,
            "vrbo": result.vrbo_share,
            "booking": result.other_share * 0.5,
            "direct": result.other_share * 0.3,
            "other": result.other_share * 0.2,
        }
        
        return weights, result.confidence


# =============================================================================
# SINGLETON & CONVENIENCE
# =============================================================================

_service: Optional[PlatformDominanceService] = None


def get_platform_service() -> PlatformDominanceService:
    """Get platform dominance service singleton."""
    global _service
    if _service is None:
        _service = PlatformDominanceService()
    return _service


def get_platform_bias(
    signal_bundle: SignalBundle,
) -> PlatformDominanceResult:
    """
    Get platform dominance/bias from signals.
    
    This is THE function to call for platform weighting.
    
    Example:
        bias = get_platform_bias(bundle)
        if bias.is_airbnb_dominant():
            optimize_for = "airbnb"
    """
    return get_platform_service().get_platform_dominance(signal_bundle)


def get_platform_weights(
    signal_bundle: SignalBundle,
) -> Tuple[Dict[str, float], float]:
    """
    Get platform weights for data source weighting.
    
    Returns:
        (weights_dict, confidence)
    """
    return get_platform_service().get_platform_weights(signal_bundle)
