"""
Operator Delta Service - Signal Consumer Only.

Phase 4 of Master Refactor Plan:
- OperatorDeltaDetector is AUTHORITATIVE
- This service CONSUMES signals only
- Delta is CAPPED (conservative application)
- Delta is GATED (confidence thresholds)

IMPORTANT:
- Voice policy CANNOT expose operator delta explicitly
- This is internal-only intelligence
- Strong legal implications require conservative application

Usage:
    from app.services.signals.operator import get_operator_delta
    
    delta = get_operator_delta(signal_bundle)
    if delta.is_usable_for_bd():
        adjusted_adr = base_adr * (1 + delta.applied_adr_delta)
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Tuple
from uuid import UUID

from app.services.signals.signal_contract import (
    Signal,
    SignalBundle,
    SignalType,
    medium_decay,
    ConfidenceThresholds,
)


# =============================================================================
# OPERATOR DELTA RESULT
# =============================================================================

@dataclass
class OperatorDeltaResult:
    """
    Result of operator delta lookup.
    
    Contains raw delta, applied delta (after cap), and confidence.
    """
    # Raw delta from signal (may be large)
    raw_adr_delta: float  # e.g., 0.18 = +18%
    raw_occupancy_delta: float
    
    # Applied delta (after conservative cap)
    applied_adr_delta: float
    applied_occupancy_delta: float
    
    # Confidence
    confidence: float
    
    # Supporting data
    months_of_data: Optional[int] = None
    property_count: Optional[int] = None
    
    # Signal metadata
    has_signal: bool = False
    signal_id: Optional[UUID] = None
    signal_age_days: Optional[int] = None
    
    # Was delta capped?
    was_capped: bool = False
    
    def is_usable_for_bd(self) -> bool:
        """
        Can this be used for BD projections?
        
        Note: Higher threshold than other signals due to legal sensitivity.
        """
        return self.confidence >= ConfidenceThresholds.BD_RECOMMENDATION
    
    def is_positive(self) -> bool:
        """Does operator outperform market?"""
        return self.applied_adr_delta > 0 or self.applied_occupancy_delta > 0
    
    def get_combined_delta(self) -> float:
        """Get weighted combination of ADR and occupancy delta."""
        # ADR weighted slightly higher
        return (self.applied_adr_delta * 0.6) + (self.applied_occupancy_delta * 0.4)
    
    def get_voice_safe_statement(self) -> Optional[str]:
        """
        Get a voice-safe statement about operator performance.
        
        CRITICAL: Never expose actual numbers in voice.
        """
        if not self.has_signal or self.confidence < 0.5:
            return None
        
        if self.is_positive():
            return "Your portfolio has historically performed above market average"
        else:
            return "Your portfolio performance is in line with market averages"


# =============================================================================
# OPERATOR DELTA SERVICE
# =============================================================================

class OperatorDeltaService:
    """
    Operator delta service - CONSUMES signals only.
    
    RULES:
    1. Only reads from SignalBundle
    2. Delta is CAPPED to prevent overconfidence
    3. Requires higher confidence threshold
    4. Voice CANNOT expose specific numbers
    
    The OperatorDeltaDetector is the ONLY source of truth.
    """
    
    # Conservative caps on applied delta
    MAX_ADR_DELTA = 0.15       # Cap at +/- 15%
    MAX_OCCUPANCY_DELTA = 0.10 # Cap at +/- 10%
    
    # Application rate (we only apply portion of observed delta)
    ADR_APPLICATION_RATE = 0.50       # Apply 50% of observed
    OCCUPANCY_APPLICATION_RATE = 0.40 # Apply 40% of observed
    
    # Neutral fallback
    NEUTRAL_DELTA = 0.0
    NEUTRAL_CONFIDENCE = 0.25  # Very low - will gate outputs
    
    def get_operator_delta(
        self,
        signal_bundle: SignalBundle,
    ) -> OperatorDeltaResult:
        """
        Get operator performance delta from signals.
        
        The delta is:
        1. Decayed based on signal age
        2. Scaled by application rate (conservative)
        3. Capped at maximum values
        
        Args:
            signal_bundle: Bundle containing OPERATOR_DELTA signals
        
        Returns:
            OperatorDeltaResult with raw and applied deltas
        """
        # Get weighted value
        value, confidence = signal_bundle.get_weighted_with_confidence(
            SignalType.OPERATOR_DELTA,
            decay_fn=medium_decay,
        )
        
        if value is None:
            return OperatorDeltaResult(
                raw_adr_delta=self.NEUTRAL_DELTA,
                raw_occupancy_delta=self.NEUTRAL_DELTA,
                applied_adr_delta=self.NEUTRAL_DELTA,
                applied_occupancy_delta=self.NEUTRAL_DELTA,
                confidence=self.NEUTRAL_CONFIDENCE,
                has_signal=False,
            )
        
        # Get latest signal for detailed breakdown
        latest_signal = signal_bundle.get_latest(SignalType.OPERATOR_DELTA)
        
        # Extract raw deltas
        raw_adr_delta = value  # Signal value is the combined delta
        raw_occ_delta = 0.0
        months_of_data = None
        property_count = None
        
        if latest_signal and latest_signal.metadata:
            raw_adr_delta = latest_signal.metadata.get("adr_delta_pct", value)
            raw_occ_delta = latest_signal.metadata.get("occupancy_delta_pct", 0.0)
            months_of_data = latest_signal.metadata.get("months_of_data")
            property_count = latest_signal.metadata.get("property_count")
        
        # Apply conservative rates
        applied_adr = raw_adr_delta * self.ADR_APPLICATION_RATE
        applied_occ = raw_occ_delta * self.OCCUPANCY_APPLICATION_RATE
        
        # Apply caps
        was_capped = False
        if abs(applied_adr) > self.MAX_ADR_DELTA:
            applied_adr = self.MAX_ADR_DELTA if applied_adr > 0 else -self.MAX_ADR_DELTA
            was_capped = True
        
        if abs(applied_occ) > self.MAX_OCCUPANCY_DELTA:
            applied_occ = self.MAX_OCCUPANCY_DELTA if applied_occ > 0 else -self.MAX_OCCUPANCY_DELTA
            was_capped = True
        
        # Signal age
        signal_age_days = None
        if latest_signal:
            signal_age_days = (datetime.utcnow() - latest_signal.detected_at).days
        
        return OperatorDeltaResult(
            raw_adr_delta=raw_adr_delta,
            raw_occupancy_delta=raw_occ_delta,
            applied_adr_delta=applied_adr,
            applied_occupancy_delta=applied_occ,
            confidence=confidence,
            months_of_data=months_of_data,
            property_count=property_count,
            has_signal=True,
            signal_id=latest_signal.id if latest_signal else None,
            signal_age_days=signal_age_days,
            was_capped=was_capped,
        )
    
    def apply_operator_delta(
        self,
        signal_bundle: SignalBundle,
        base_adr: float,
        base_occupancy: float,
    ) -> Tuple[float, float, float, OperatorDeltaResult]:
        """
        Apply operator delta to base metrics.
        
        Returns:
            (adjusted_adr, adjusted_occupancy, confidence, delta_result)
        """
        delta = self.get_operator_delta(signal_bundle)
        
        if not delta.is_usable_for_bd():
            # Don't apply - return unchanged
            return base_adr, base_occupancy, delta.confidence, delta
        
        adjusted_adr = base_adr * (1 + delta.applied_adr_delta)
        adjusted_occ = base_occupancy * (1 + delta.applied_occupancy_delta)
        
        # Cap occupancy at 95%
        adjusted_occ = min(0.95, adjusted_occ)
        
        return adjusted_adr, adjusted_occ, delta.confidence, delta


# =============================================================================
# SINGLETON & CONVENIENCE
# =============================================================================

_service: Optional[OperatorDeltaService] = None


def get_operator_service() -> OperatorDeltaService:
    """Get operator delta service singleton."""
    global _service
    if _service is None:
        _service = OperatorDeltaService()
    return _service


def get_operator_delta(
    signal_bundle: SignalBundle,
) -> OperatorDeltaResult:
    """
    Get operator performance delta from signals.
    
    This is THE function to call for operator adjustments.
    
    Example:
        delta = get_operator_delta(bundle)
        if delta.is_usable_for_bd():
            adjusted_adr = base_adr * (1 + delta.applied_adr_delta)
    """
    return get_operator_service().get_operator_delta(signal_bundle)


def apply_operator_delta(
    signal_bundle: SignalBundle,
    base_adr: float,
    base_occupancy: float,
) -> Tuple[float, float, float]:
    """
    Apply operator delta to base metrics.
    
    Returns:
        (adjusted_adr, adjusted_occupancy, confidence)
    """
    adr, occ, conf, _ = get_operator_service().apply_operator_delta(
        signal_bundle, base_adr, base_occupancy
    )
    return adr, occ, conf
