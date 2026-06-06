"""
Seasonality Service - Signal Consumer Only.

Phase 1 of Master Refactor Plan:
- SeasonalityCurveDetector is AUTHORITATIVE
- This service CONSUMES signals only
- NO inline seasonality calculation
- NO fallback math (if missing → confidence drops → gated)

DELETED FROM CODEBASE:
- DEFAULT_SEASONALITY dict in rent_projection_engine
- SeasonalityDetector class in platform_weighting.py
- Any month-based multipliers elsewhere

Usage:
    from app.services.signals.seasonality import get_seasonality
    
    seasonality = get_seasonality(signal_bundle)
    adjusted_adr = base_adr * seasonality
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple
from uuid import UUID

from app.services.signals.signal_contract import (
    Signal,
    SignalBundle,
    SignalType,
    slow_decay,
    ConfidenceThresholds,
)


# =============================================================================
# SEASONALITY DATA (Output of this service)
# =============================================================================

@dataclass
class SeasonalityResult:
    """
    Result of seasonality lookup.
    
    If confidence is too low, consumers MUST gate their outputs.
    No fallback math. Missing signals = low confidence = restricted outputs.
    """
    # The seasonality multiplier (1.0 = average, >1 = high demand)
    multiplier: float
    
    # Confidence in this value
    confidence: float
    
    # Monthly breakdown (if available)
    monthly_curve: Optional[Dict[str, float]] = None
    
    # Peak/trough info
    peak_months: Optional[List[int]] = None
    trough_months: Optional[List[int]] = None
    
    # Seasonality strength (peak/trough ratio)
    strength: Optional[float] = None
    
    # Was this from a signal or is it a neutral fallback?
    has_signal: bool = False
    signal_id: Optional[UUID] = None
    signal_age_days: Optional[int] = None
    
    def is_usable_for_voice(self) -> bool:
        """Can this be used for voice claims?"""
        return self.confidence >= ConfidenceThresholds.VOICE_MARKET_ASSERTION
    
    def is_usable_for_bd(self) -> bool:
        """Can this be used for BD projections?"""
        return self.confidence >= ConfidenceThresholds.BD_PROJECTION
    
    def is_peak_season(self, month: int) -> bool:
        """Check if month is peak season."""
        if not self.peak_months:
            return False
        return month in self.peak_months
    
    def is_trough_season(self, month: int) -> bool:
        """Check if month is off-season."""
        if not self.trough_months:
            return False
        return month in self.trough_months
    
    def get_monthly_multiplier(self, month: int) -> float:
        """Get multiplier for specific month."""
        if not self.monthly_curve:
            return self.multiplier
        
        month_names = ["", "jan", "feb", "mar", "apr", "may", "jun",
                       "jul", "aug", "sep", "oct", "nov", "dec"]
        month_key = month_names[month] if 1 <= month <= 12 else None
        
        if month_key and month_key in self.monthly_curve:
            return self.monthly_curve[month_key]
        
        return self.multiplier


# =============================================================================
# SEASONALITY SERVICE (Signal Consumer Only)
# =============================================================================

class SeasonalityService:
    """
    Seasonality service - CONSUMES signals only.
    
    RULES:
    1. Only reads from SignalBundle
    2. NO inline calculation
    3. NO fallback math
    4. Missing signal = neutral (1.0) with LOW confidence
    
    The SeasonalityCurveDetector is the ONLY source of truth.
    """
    
    # Neutral fallback (used ONLY when no signal exists)
    # This has LOW confidence so outputs will be gated
    NEUTRAL_MULTIPLIER = 1.0
    NEUTRAL_CONFIDENCE = 0.3  # Below all thresholds
    
    def get_seasonality(
        self,
        signal_bundle: SignalBundle,
        target_date: Optional[date] = None,
    ) -> SeasonalityResult:
        """
        Get seasonality from signals.
        
        If no signal exists, returns neutral with LOW confidence.
        This will cause downstream gating - which is correct behavior.
        
        Args:
            signal_bundle: Bundle containing signals
            target_date: Date to get seasonality for (for monthly lookup)
        
        Returns:
            SeasonalityResult with multiplier and confidence
        """
        target_date = target_date or date.today()
        
        # Get weighted seasonality value
        value, confidence = signal_bundle.get_weighted_with_confidence(
            SignalType.SEASONALITY_CURVE,
            decay_fn=slow_decay,
        )
        
        if value is None:
            # No signal - return neutral with low confidence
            # This will gate downstream outputs
            return SeasonalityResult(
                multiplier=self.NEUTRAL_MULTIPLIER,
                confidence=self.NEUTRAL_CONFIDENCE,
                has_signal=False,
            )
        
        # Get the latest signal for detailed info
        latest_signal = signal_bundle.get_latest(SignalType.SEASONALITY_CURVE)
        
        # Extract curve and metadata
        monthly_curve = None
        peak_months = None
        trough_months = None
        strength = None
        signal_age_days = None
        
        if latest_signal and latest_signal.metadata:
            sv = latest_signal.metadata
            monthly_curve = sv.get("monthly_curve")
            peak_months = sv.get("peak_months")
            trough_months = sv.get("trough_months")
            strength = sv.get("seasonality_strength")
            signal_age_days = (datetime.utcnow() - latest_signal.detected_at).days
        
        # Get month-specific multiplier if available
        multiplier = value
        if monthly_curve:
            month_names = ["", "jan", "feb", "mar", "apr", "may", "jun",
                           "jul", "aug", "sep", "oct", "nov", "dec"]
            month_key = month_names[target_date.month]
            if month_key in monthly_curve:
                multiplier = monthly_curve[month_key]
        
        return SeasonalityResult(
            multiplier=multiplier,
            confidence=confidence,
            monthly_curve=monthly_curve,
            peak_months=peak_months,
            trough_months=trough_months,
            strength=strength,
            has_signal=True,
            signal_id=latest_signal.id if latest_signal else None,
            signal_age_days=signal_age_days,
        )
    
    def get_monthly_curve(
        self,
        signal_bundle: SignalBundle,
    ) -> Tuple[Dict[int, float], float]:
        """
        Get full monthly curve from signals.
        
        Returns:
            (monthly_dict, confidence) where monthly_dict is {1: 0.7, 2: 0.72, ...}
        """
        result = self.get_seasonality(signal_bundle)
        
        if not result.monthly_curve:
            # Return neutral curve with low confidence
            return {m: 1.0 for m in range(1, 13)}, self.NEUTRAL_CONFIDENCE
        
        # Convert from {"jan": 0.7} to {1: 0.7}
        month_map = {
            "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
            "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
        }
        
        monthly_dict = {}
        for name, value in result.monthly_curve.items():
            month_num = month_map.get(name.lower())
            if month_num:
                monthly_dict[month_num] = value
        
        # Fill missing months with average
        if monthly_dict:
            avg = sum(monthly_dict.values()) / len(monthly_dict)
            for m in range(1, 13):
                if m not in monthly_dict:
                    monthly_dict[m] = avg
        else:
            monthly_dict = {m: 1.0 for m in range(1, 13)}
        
        return monthly_dict, result.confidence
    
    def to_legacy_format(
        self,
        signal_bundle: SignalBundle,
    ) -> Tuple[Dict[int, Dict[str, float]], float]:
        """
        Convert to legacy format for backward compatibility.
        
        Returns:
            ({month: {"occupancy": x, "rate": y}}, confidence)
        
        DEPRECATED: Use get_seasonality() directly.
        """
        monthly_curve, confidence = self.get_monthly_curve(signal_bundle)
        
        legacy = {}
        for month, rate_mult in monthly_curve.items():
            # Estimate occupancy from rate multiplier
            # This is approximate - the detector should provide both
            occupancy = min(0.95, rate_mult * 0.55)
            legacy[month] = {
                "occupancy": occupancy,
                "rate": rate_mult,
            }
        
        return legacy, confidence


# =============================================================================
# SINGLETON & CONVENIENCE
# =============================================================================

_service: Optional[SeasonalityService] = None


def get_seasonality_service() -> SeasonalityService:
    """Get seasonality service singleton."""
    global _service
    if _service is None:
        _service = SeasonalityService()
    return _service


def get_seasonality(
    signal_bundle: SignalBundle,
    target_date: Optional[date] = None,
) -> SeasonalityResult:
    """
    Get seasonality from signals.
    
    This is THE function to call for seasonality.
    
    Args:
        signal_bundle: Bundle containing SEASONALITY_CURVE signals
        target_date: Optional date for month-specific lookup
    
    Returns:
        SeasonalityResult with multiplier and confidence
    
    Example:
        seasonality = get_seasonality(bundle)
        if seasonality.is_usable_for_bd():
            adjusted_adr = base_adr * seasonality.multiplier
        else:
            # Gate the output - confidence too low
            return GatedResponse(reason="insufficient_seasonality_data")
    """
    return get_seasonality_service().get_seasonality(signal_bundle, target_date)
