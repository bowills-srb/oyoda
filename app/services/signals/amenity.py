"""
Amenity Lift Service - Signal Consumer Only.

Phase 3 of Master Refactor Plan:
- AmenityLiftDetector is AUTHORITATIVE
- This service CONSUMES signals only
- NO hardcoded multipliers (* 1.10)
- NO AmenityUpliftConfig

DELETED FROM CODEBASE:
- AmenityUpliftConfig class
- Hardcoded pool: 1.10, waterfront: 1.15, etc.
- Inline amenity multiplier math

Usage:
    from app.services.signals.amenity import get_amenity_lift
    
    lift = get_amenity_lift(signal_bundle)
    adjusted_adr = base_adr * (1 + lift.total_lift)
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from uuid import UUID

from app.services.signals.signal_contract import (
    Signal,
    SignalBundle,
    SignalType,
    medium_decay,
    ConfidenceThresholds,
)


# =============================================================================
# AMENITY LIFT RESULT
# =============================================================================

@dataclass
class AmenityLiftDetail:
    """Detail for a single amenity's lift."""
    amenity: str
    lift_pct: float  # e.g., 0.15 = +15%
    confidence: float
    sample_size: Optional[int] = None
    signal_age_days: Optional[int] = None


@dataclass
class AmenityLiftResult:
    """
    Result of amenity lift lookup.
    
    Contains per-amenity lifts and total calculated lift.
    """
    # Per-amenity breakdown
    lifts: Dict[str, AmenityLiftDetail] = field(default_factory=dict)
    
    # Total lift to apply (multiplicative product - 1)
    # e.g., 0.25 means apply * 1.25
    total_lift: float = 0.0
    
    # Effective multiplier (1 + total_lift)
    multiplier: float = 1.0
    
    # Average confidence across amenities
    confidence: float = 0.0
    
    # Has any signals?
    has_signals: bool = False
    
    def is_usable_for_voice(self) -> bool:
        """Can this be used for voice claims?"""
        return self.confidence >= ConfidenceThresholds.VOICE_MARKET_ASSERTION
    
    def is_usable_for_bd(self) -> bool:
        """Can this be used for BD projections?"""
        return self.confidence >= ConfidenceThresholds.BD_PROJECTION
    
    def get_lift_for_amenity(self, amenity: str) -> Optional[float]:
        """Get lift for specific amenity."""
        detail = self.lifts.get(amenity)
        return detail.lift_pct if detail else None
    
    def get_top_amenities(self, n: int = 3) -> List[AmenityLiftDetail]:
        """Get top N amenities by lift value."""
        sorted_lifts = sorted(
            self.lifts.values(),
            key=lambda x: x.lift_pct,
            reverse=True
        )
        return sorted_lifts[:n]


# =============================================================================
# AMENITY LIFT SERVICE
# =============================================================================

class AmenityLiftService:
    """
    Amenity lift service - CONSUMES signals only.
    
    RULES:
    1. Only reads from SignalBundle
    2. NO hardcoded multipliers
    3. Lifts are GEO-SPECIFIC (from detector)
    4. Missing signal = no lift with LOW confidence
    
    The AmenityLiftDetector is the ONLY source of truth.
    """
    
    # No lift with low confidence (will gate outputs)
    NEUTRAL_LIFT = 0.0
    NEUTRAL_CONFIDENCE = 0.3
    
    def get_amenity_lifts(
        self,
        signal_bundle: SignalBundle,
        property_amenities: Optional[List[str]] = None,
    ) -> AmenityLiftResult:
        """
        Get amenity lifts from signals.
        
        Args:
            signal_bundle: Bundle containing AMENITY_LIFT signals
            property_amenities: Optional list of amenities the property has
                              If provided, only those amenities contribute to total
        
        Returns:
            AmenityLiftResult with per-amenity lifts and total
        """
        # Get all amenity lift signals
        signals = signal_bundle.get_all(SignalType.AMENITY_LIFT)
        
        if not signals:
            return AmenityLiftResult(
                lifts={},
                total_lift=self.NEUTRAL_LIFT,
                multiplier=1.0,
                confidence=self.NEUTRAL_CONFIDENCE,
                has_signals=False,
            )
        
        # Build per-amenity lifts
        lifts: Dict[str, AmenityLiftDetail] = {}
        
        for signal in signals:
            amenity = None
            lift_pct = signal.value
            
            # Get amenity name from metadata
            if signal.metadata:
                amenity = signal.metadata.get("amenity")
                # Prefer explicit lift_percent if available
                if "lift_percent" in signal.metadata:
                    lift_pct = signal.metadata["lift_percent"] / 100
            
            if not amenity:
                continue
            
            # Apply decay
            decay = medium_decay(signal)
            effective_confidence = signal.confidence * decay
            
            # Store (or update if we have multiple signals for same amenity)
            if amenity not in lifts or lifts[amenity].confidence < effective_confidence:
                lifts[amenity] = AmenityLiftDetail(
                    amenity=amenity,
                    lift_pct=lift_pct,
                    confidence=effective_confidence,
                    sample_size=signal.metadata.get("sample_size") if signal.metadata else None,
                    signal_age_days=(datetime.utcnow() - signal.detected_at).days,
                )
        
        if not lifts:
            return AmenityLiftResult(
                lifts={},
                total_lift=self.NEUTRAL_LIFT,
                multiplier=1.0,
                confidence=self.NEUTRAL_CONFIDENCE,
                has_signals=False,
            )
        
        # Calculate total lift for property's amenities
        total_multiplier = 1.0
        total_confidence = 0.0
        count = 0
        
        if property_amenities:
            # Only include amenities the property has
            for amenity in property_amenities:
                if amenity in lifts:
                    detail = lifts[amenity]
                    # Multiplicative lift
                    total_multiplier *= (1 + detail.lift_pct * detail.confidence)
                    total_confidence += detail.confidence
                    count += 1
        else:
            # No property amenities specified - return all lifts
            # but don't calculate total (property-specific)
            total_confidence = sum(d.confidence for d in lifts.values()) / len(lifts)
            count = len(lifts)
        
        avg_confidence = total_confidence / count if count > 0 else self.NEUTRAL_CONFIDENCE
        total_lift = total_multiplier - 1.0
        
        return AmenityLiftResult(
            lifts=lifts,
            total_lift=total_lift,
            multiplier=total_multiplier,
            confidence=avg_confidence,
            has_signals=True,
        )
    
    def calculate_adjusted_adr(
        self,
        signal_bundle: SignalBundle,
        base_adr: float,
        property_amenities: List[str],
    ) -> Tuple[float, float, List[AmenityLiftDetail]]:
        """
        Calculate ADR with amenity lifts applied.
        
        This is the ONLY way ADR should be adjusted for amenities.
        
        Args:
            signal_bundle: Bundle with AMENITY_LIFT signals
            base_adr: Base ADR before amenity adjustments
            property_amenities: Amenities the property has
        
        Returns:
            (adjusted_adr, confidence, applied_lifts)
        """
        result = self.get_amenity_lifts(signal_bundle, property_amenities)
        
        adjusted_adr = base_adr * result.multiplier
        
        # Get which lifts were actually applied
        applied = [
            result.lifts[a] for a in property_amenities
            if a in result.lifts
        ]
        
        return adjusted_adr, result.confidence, applied


# =============================================================================
# SINGLETON & CONVENIENCE
# =============================================================================

_service: Optional[AmenityLiftService] = None


def get_amenity_service() -> AmenityLiftService:
    """Get amenity lift service singleton."""
    global _service
    if _service is None:
        _service = AmenityLiftService()
    return _service


def get_amenity_lift(
    signal_bundle: SignalBundle,
    property_amenities: Optional[List[str]] = None,
) -> AmenityLiftResult:
    """
    Get amenity lifts from signals.
    
    This is THE function to call for amenity adjustments.
    
    Example:
        lift = get_amenity_lift(bundle, ["pool", "waterfront"])
        adjusted_adr = base_adr * lift.multiplier
    """
    return get_amenity_service().get_amenity_lifts(signal_bundle, property_amenities)


def apply_amenity_lift(
    signal_bundle: SignalBundle,
    base_adr: float,
    property_amenities: List[str],
) -> Tuple[float, float]:
    """
    Apply amenity lifts to base ADR.
    
    Returns:
        (adjusted_adr, confidence)
    """
    adr, confidence, _ = get_amenity_service().calculate_adjusted_adr(
        signal_bundle, base_adr, property_amenities
    )
    return adr, confidence
