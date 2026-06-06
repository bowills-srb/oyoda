"""
Competitive Position Signal - Lightweight Detector.

Not scraping full comps — just:
- Relative positioning percentile
- "You're priced above 72% of comparable listings"
- Confidence-weighted

Small detector with huge UX value.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from app.services.signals.signal_contract import (
    Signal,
    SignalBundle,
    SignalType,
    SignalScope,
    SignalSource,
    fast_decay,
)


# =============================================================================
# POSITION MODELS
# =============================================================================

class PositionBand(str, Enum):
    """Competitive position bands."""
    PREMIUM = "premium"        # Top 10%
    ABOVE_MARKET = "above"     # 60-90%
    AT_MARKET = "at_market"    # 40-60%
    BELOW_MARKET = "below"     # 10-40%
    BUDGET = "budget"          # Bottom 10%


@dataclass
class CompetitivePosition:
    """
    Competitive positioning analysis.
    
    Tells operators exactly where they stand.
    """
    # Core metric
    percentile: float  # 0-100, where 100 = highest priced
    
    # Band classification
    band: PositionBand
    
    # Price comparison
    your_adr: float
    market_median_adr: float
    market_avg_adr: float
    
    # Delta
    delta_vs_median: float       # +$25 or -$15
    delta_vs_median_pct: float   # +12% or -8%
    
    # Comp set summary (no individual listings)
    comp_count: int
    comp_adr_range: Tuple[float, float]  # (low, high)
    
    # Confidence
    confidence: float
    
    # Human-readable
    headline: str
    explanation: str
    
    # Recommendations
    recommendations: List[str] = field(default_factory=list)
    
    # Metadata
    computed_at: datetime = field(default_factory=datetime.utcnow)
    
    def is_premium_positioned(self) -> bool:
        """Is listing in premium band?"""
        return self.band in [PositionBand.PREMIUM, PositionBand.ABOVE_MARKET]
    
    def is_underpriced(self) -> bool:
        """Might listing be underpriced?"""
        return self.band in [PositionBand.BELOW_MARKET, PositionBand.BUDGET]


# =============================================================================
# COMPETITIVE POSITION SERVICE
# =============================================================================

class CompetitivePositionService:
    """
    Competitive Position Service.
    
    Calculates relative positioning without exposing individual comps.
    
    This is privacy-safe competitor intelligence.
    """
    
    def __init__(self):
        self.version = "1.0.0"
    
    def calculate_position(
        self,
        your_adr: float,
        signal_bundle: SignalBundle,
        bedrooms: int,
        amenities: Optional[List[str]] = None,
    ) -> CompetitivePosition:
        """
        Calculate competitive position from signals.
        
        Uses RATE_POSITION signal if available,
        otherwise estimates from market signals.
        """
        
        # Try to get rate position signal
        rate_position, confidence = signal_bundle.get_weighted_with_confidence(
            SignalType.RATE_POSITION,
            decay_fn=fast_decay,
        )
        
        # Get market context
        from app.services.signals.platform import get_platform_bias
        from app.services.signals.amenity import get_amenity_lift
        
        platform = get_platform_bias(signal_bundle)
        amenity_lift = get_amenity_lift(signal_bundle, amenities or [])
        
        if rate_position is not None:
            # We have explicit rate position signal
            return self._build_from_signal(
                your_adr, rate_position, confidence, signal_bundle
            )
        else:
            # Estimate from market signals
            return self._estimate_position(
                your_adr, bedrooms, amenity_lift, platform, signal_bundle
            )
    
    def _build_from_signal(
        self,
        your_adr: float,
        rate_position: float,  # Percentile from signal
        confidence: float,
        signal_bundle: SignalBundle,
    ) -> CompetitivePosition:
        """Build position from explicit rate position signal."""
        
        percentile = rate_position * 100  # Convert to 0-100
        
        # Get market stats from signal metadata
        latest = signal_bundle.get_latest(SignalType.RATE_POSITION)
        
        if latest and latest.metadata:
            market_median = latest.metadata.get("market_median", your_adr)
            market_avg = latest.metadata.get("market_avg", your_adr)
            comp_count = latest.metadata.get("comp_count", 10)
            comp_low = latest.metadata.get("comp_adr_low", your_adr * 0.7)
            comp_high = latest.metadata.get("comp_adr_high", your_adr * 1.3)
        else:
            # Estimate from percentile
            market_median = your_adr / (1 + (percentile - 50) / 200)
            market_avg = market_median * 1.05
            comp_count = 15
            comp_low = market_median * 0.6
            comp_high = market_median * 1.5
        
        return self._build_result(
            your_adr, percentile, market_median, market_avg,
            comp_count, (comp_low, comp_high), confidence
        )
    
    def _estimate_position(
        self,
        your_adr: float,
        bedrooms: int,
        amenity_lift,
        platform,
        signal_bundle: SignalBundle,
    ) -> CompetitivePosition:
        """Estimate position from market signals (no explicit rate signal)."""
        
        # Base market ADR by bedroom (simplified)
        base_adr_by_bedroom = {
            1: 150, 2: 200, 3: 275, 4: 350, 5: 450, 6: 550,
        }
        base_adr = base_adr_by_bedroom.get(bedrooms, 300)
        
        # Adjust for amenity lift
        market_median = base_adr * amenity_lift.multiplier
        market_avg = market_median * 1.05
        
        # Calculate where your ADR falls
        delta = your_adr - market_median
        delta_pct = delta / market_median if market_median > 0 else 0
        
        # Estimate percentile from delta
        # Roughly: +20% = 75th percentile, -20% = 25th percentile
        percentile = 50 + (delta_pct * 125)
        percentile = max(5, min(95, percentile))
        
        # Confidence is lower for estimates
        confidence = min(0.6, amenity_lift.confidence * 0.8)
        
        # Estimate comp range
        comp_low = market_median * 0.6
        comp_high = market_median * 1.5
        
        return self._build_result(
            your_adr, percentile, market_median, market_avg,
            10, (comp_low, comp_high), confidence  # Lower comp count for estimate
        )
    
    def _build_result(
        self,
        your_adr: float,
        percentile: float,
        market_median: float,
        market_avg: float,
        comp_count: int,
        comp_range: Tuple[float, float],
        confidence: float,
    ) -> CompetitivePosition:
        """Build final result with recommendations."""
        
        # Determine band
        if percentile >= 90:
            band = PositionBand.PREMIUM
        elif percentile >= 60:
            band = PositionBand.ABOVE_MARKET
        elif percentile >= 40:
            band = PositionBand.AT_MARKET
        elif percentile >= 10:
            band = PositionBand.BELOW_MARKET
        else:
            band = PositionBand.BUDGET
        
        # Calculate deltas
        delta = your_adr - market_median
        delta_pct = delta / market_median if market_median > 0 else 0
        
        # Generate headline
        if percentile >= 60:
            headline = f"You're priced above {percentile:.0f}% of comparable listings"
        elif percentile <= 40:
            headline = f"You're priced below {100 - percentile:.0f}% of comparable listings"
        else:
            headline = f"You're priced at market (percentile {percentile:.0f})"
        
        # Generate explanation
        if delta >= 0:
            explanation = f"Your rate of ${your_adr:.0f} is ${delta:.0f} ({delta_pct:+.0%}) above the market median of ${market_median:.0f}"
        else:
            explanation = f"Your rate of ${your_adr:.0f} is ${abs(delta):.0f} ({delta_pct:+.0%}) below the market median of ${market_median:.0f}"
        
        # Generate recommendations
        recommendations = []
        
        if band == PositionBand.BUDGET:
            recommendations.append("Consider raising rates - you may be leaving money on the table")
            recommendations.append("Review amenities to ensure they support current pricing")
        elif band == PositionBand.BELOW_MARKET:
            recommendations.append("Rate increase may be possible with minimal demand impact")
        elif band == PositionBand.PREMIUM:
            recommendations.append("Premium positioning is working - monitor occupancy closely")
            if confidence < 0.6:
                recommendations.append("Low signal confidence - validate with booking data")
        
        return CompetitivePosition(
            percentile=percentile,
            band=band,
            your_adr=your_adr,
            market_median_adr=market_median,
            market_avg_adr=market_avg,
            delta_vs_median=delta,
            delta_vs_median_pct=delta_pct,
            comp_count=comp_count,
            comp_adr_range=comp_range,
            confidence=confidence,
            headline=headline,
            explanation=explanation,
            recommendations=recommendations,
        )


# =============================================================================
# SINGLETON & CONVENIENCE
# =============================================================================

_service: Optional[CompetitivePositionService] = None


def get_position_service() -> CompetitivePositionService:
    """Get competitive position service singleton."""
    global _service
    if _service is None:
        _service = CompetitivePositionService()
    return _service


def get_competitive_position(
    your_adr: float,
    signal_bundle: SignalBundle,
    bedrooms: int,
    amenities: Optional[List[str]] = None,
) -> CompetitivePosition:
    """
    Get competitive position.
    
    Example:
        position = get_competitive_position(
            your_adr=325,
            signal_bundle=bundle,
            bedrooms=4,
            amenities=["pool", "waterfront"]
        )
        
        print(position.headline)
        # "You're priced above 72% of comparable listings"
    """
    return get_position_service().calculate_position(
        your_adr, signal_bundle, bedrooms, amenities
    )
