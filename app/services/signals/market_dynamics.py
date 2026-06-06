"""
Price Velocity & Calendar Delta Tracking

This module tracks changes over time, not just snapshots:
- Price velocity (EWMA of rate changes)
- Calendar delta (booking velocity, compression speed)
- Direction detection
- Momentum scoring

These are the "market pulse" signals that improve:
- Forward-looking accuracy
- Discount logic
- Concierge posture

Usage:
    from app.services.signals.market_dynamics import (
        PriceVelocityEngine,
        CalendarDeltaEngine,
    )
    
    # Track price changes
    velocity = price_engine.calculate_velocity(price_history)
    
    # Track calendar changes
    delta = calendar_engine.calculate_compression_delta(calendar_history)
"""

from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
import math

from pydantic import BaseModel, Field


# =============================================================================
# ENUMS
# =============================================================================

class PriceDirection(str, Enum):
    """Price movement direction."""
    RISING = "rising"
    FALLING = "falling"
    STABLE = "stable"


class DemandDirection(str, Enum):
    """Demand movement direction."""
    ACCELERATING = "accelerating"
    DECELERATING = "decelerating"
    STABLE = "stable"


class MomentumStrength(str, Enum):
    """Momentum strength classification."""
    STRONG = "strong"
    MODERATE = "moderate"
    WEAK = "weak"
    NONE = "none"


# =============================================================================
# DATA MODELS
# =============================================================================

@dataclass
class PriceObservation:
    """Single price observation."""
    observed_at: datetime
    median_price: float
    p25_price: Optional[float] = None
    p75_price: Optional[float] = None
    sample_size: int = 0
    
    # Optional segmentation
    bedroom_count: Optional[int] = None
    property_type: Optional[str] = None


@dataclass
class CalendarObservation:
    """Single calendar observation."""
    observed_at: datetime
    blocked_pct_7d: float
    blocked_pct_30d: float
    blocked_pct_60d: Optional[float] = None
    total_listings: int = 0


@dataclass
class PriceVelocityResult:
    """Result of price velocity calculation."""
    geo_id: str
    calculated_at: datetime
    
    # Velocity metrics
    velocity_7d: float  # % change over 7 days
    velocity_14d: float  # % change over 14 days
    velocity_30d: float  # % change over 30 days
    
    # EWMA (exponentially weighted moving average)
    ewma_velocity: float
    ewma_span: int  # Days used for EWMA
    
    # Direction
    direction: PriceDirection
    direction_confidence: float
    
    # Momentum
    momentum: float  # -1 to +1
    momentum_strength: MomentumStrength
    
    # Reversal detection
    days_since_reversal: Optional[int] = None
    reversal_magnitude: Optional[float] = None
    
    # Confidence
    confidence: float = 0.5
    sample_count: int = 0
    
    def to_signal_value(self) -> Dict[str, Any]:
        """Convert to signal value format."""
        return {
            "velocity_7d": round(self.velocity_7d, 4),
            "velocity_14d": round(self.velocity_14d, 4),
            "velocity_30d": round(self.velocity_30d, 4),
            "ewma_velocity": round(self.ewma_velocity, 4),
            "direction": self.direction.value,
            "momentum": round(self.momentum, 3),
            "momentum_strength": self.momentum_strength.value,
        }


@dataclass
class CalendarDeltaResult:
    """Result of calendar delta calculation."""
    geo_id: str
    calculated_at: datetime
    
    # Compression change
    compression_delta_7d: float  # Change in 7d blocked %
    compression_delta_30d: float  # Change in 30d blocked %
    
    # Compression speed (how fast is inventory disappearing)
    compression_speed: float  # % per day
    compression_acceleration: float  # Change in speed
    
    # Direction
    direction: DemandDirection
    direction_confidence: float
    
    # Booking velocity proxy
    estimated_booking_velocity: float  # Bookings per day (inferred)
    
    # Lead time shift
    lead_time_shift_pct: Optional[float] = None
    
    # Confidence
    confidence: float = 0.5
    sample_count: int = 0
    
    def to_signal_value(self) -> Dict[str, Any]:
        """Convert to signal value format."""
        return {
            "compression_delta_7d": round(self.compression_delta_7d, 4),
            "compression_delta_30d": round(self.compression_delta_30d, 4),
            "compression_speed": round(self.compression_speed, 4),
            "compression_acceleration": round(self.compression_acceleration, 4),
            "direction": self.direction.value,
            "estimated_booking_velocity": round(self.estimated_booking_velocity, 2),
        }


# =============================================================================
# PRICE VELOCITY ENGINE
# =============================================================================

class PriceVelocityEngine:
    """
    Tracks price movement over time.
    
    Instead of static snapshots, this tracks:
    - Weekly price deltas
    - Direction (up/down)
    - Magnitude
    - Time to reversal
    
    Key insight: Owners raise prices when demand is strong,
    drop them when bookings lag. We're observing behavior.
    """
    
    # EWMA configuration
    DEFAULT_EWMA_SPAN = 14  # Days
    
    # Direction thresholds
    RISING_THRESHOLD = 0.02  # 2% up
    FALLING_THRESHOLD = -0.02  # 2% down
    
    # Momentum thresholds
    STRONG_MOMENTUM = 0.05  # 5%
    MODERATE_MOMENTUM = 0.02  # 2%
    
    def __init__(self, ewma_span: int = DEFAULT_EWMA_SPAN):
        self.ewma_span = ewma_span
    
    def calculate_velocity(
        self,
        observations: List[PriceObservation],
        geo_id: str = "",
    ) -> PriceVelocityResult:
        """
        Calculate price velocity from observations.
        
        Args:
            observations: List of price observations (oldest first)
            geo_id: Market identifier
            
        Returns:
            PriceVelocityResult with velocity metrics
        """
        now = datetime.utcnow()
        
        # Sort by date
        obs = sorted(observations, key=lambda x: x.observed_at)
        
        if len(obs) < 2:
            return self._empty_result(geo_id, now)
        
        # Calculate velocities for different windows
        velocity_7d = self._calculate_window_velocity(obs, 7)
        velocity_14d = self._calculate_window_velocity(obs, 14)
        velocity_30d = self._calculate_window_velocity(obs, 30)
        
        # Calculate EWMA velocity
        ewma_velocity = self._calculate_ewma_velocity(obs)
        
        # Determine direction
        direction, direction_conf = self._determine_direction(
            velocity_7d, velocity_14d, velocity_30d
        )
        
        # Calculate momentum
        momentum = self._calculate_momentum(obs)
        momentum_strength = self._classify_momentum(momentum)
        
        # Detect reversals
        days_since_reversal, reversal_magnitude = self._detect_reversal(obs)
        
        # Calculate confidence
        confidence = self._calculate_confidence(obs)
        
        return PriceVelocityResult(
            geo_id=geo_id,
            calculated_at=now,
            velocity_7d=velocity_7d,
            velocity_14d=velocity_14d,
            velocity_30d=velocity_30d,
            ewma_velocity=ewma_velocity,
            ewma_span=self.ewma_span,
            direction=direction,
            direction_confidence=direction_conf,
            momentum=momentum,
            momentum_strength=momentum_strength,
            days_since_reversal=days_since_reversal,
            reversal_magnitude=reversal_magnitude,
            confidence=confidence,
            sample_count=len(obs),
        )
    
    def _calculate_window_velocity(
        self,
        obs: List[PriceObservation],
        window_days: int,
    ) -> float:
        """Calculate velocity over a specific window."""
        if len(obs) < 2:
            return 0.0
        
        # Find observations within window
        latest = obs[-1]
        cutoff = latest.observed_at - timedelta(days=window_days)
        
        window_obs = [o for o in obs if o.observed_at >= cutoff]
        
        if len(window_obs) < 2:
            return 0.0
        
        # Calculate % change from earliest to latest
        earliest = window_obs[0]
        
        if earliest.median_price == 0:
            return 0.0
        
        return (latest.median_price - earliest.median_price) / earliest.median_price
    
    def _calculate_ewma_velocity(self, obs: List[PriceObservation]) -> float:
        """Calculate EWMA of price changes."""
        if len(obs) < 2:
            return 0.0
        
        # Calculate daily changes
        changes = []
        for i in range(1, len(obs)):
            prev = obs[i-1]
            curr = obs[i]
            
            if prev.median_price == 0:
                continue
            
            pct_change = (curr.median_price - prev.median_price) / prev.median_price
            days = (curr.observed_at - prev.observed_at).days
            
            if days > 0:
                daily_change = pct_change / days
                changes.append(daily_change)
        
        if not changes:
            return 0.0
        
        # Calculate EWMA
        alpha = 2 / (self.ewma_span + 1)
        ewma = changes[0]
        
        for change in changes[1:]:
            ewma = alpha * change + (1 - alpha) * ewma
        
        return ewma * 30  # Normalize to 30-day rate
    
    def _determine_direction(
        self,
        v7: float,
        v14: float,
        v30: float,
    ) -> Tuple[PriceDirection, float]:
        """Determine price direction and confidence."""
        # Weighted average with more weight on recent
        weighted = v7 * 0.5 + v14 * 0.3 + v30 * 0.2
        
        if weighted > self.RISING_THRESHOLD:
            direction = PriceDirection.RISING
        elif weighted < self.FALLING_THRESHOLD:
            direction = PriceDirection.FALLING
        else:
            direction = PriceDirection.STABLE
        
        # Confidence based on agreement
        signs = [
            1 if v > self.RISING_THRESHOLD else (-1 if v < self.FALLING_THRESHOLD else 0)
            for v in [v7, v14, v30]
        ]
        
        agreement = abs(sum(signs)) / 3
        confidence = 0.5 + agreement * 0.5
        
        return direction, confidence
    
    def _calculate_momentum(self, obs: List[PriceObservation]) -> float:
        """Calculate price momentum (-1 to +1)."""
        if len(obs) < 3:
            return 0.0
        
        # Recent velocity vs older velocity
        mid = len(obs) // 2
        
        recent = obs[mid:]
        older = obs[:mid]
        
        if len(recent) < 2 or len(older) < 2:
            return 0.0
        
        recent_velocity = self._calculate_window_velocity(recent, 30)
        older_velocity = self._calculate_window_velocity(older, 30)
        
        # Momentum is acceleration of velocity
        momentum = recent_velocity - older_velocity
        
        # Clamp to -1 to +1
        return max(-1.0, min(1.0, momentum * 10))
    
    def _classify_momentum(self, momentum: float) -> MomentumStrength:
        """Classify momentum strength."""
        abs_momentum = abs(momentum)
        
        if abs_momentum >= self.STRONG_MOMENTUM * 10:
            return MomentumStrength.STRONG
        elif abs_momentum >= self.MODERATE_MOMENTUM * 10:
            return MomentumStrength.MODERATE
        elif abs_momentum > 0:
            return MomentumStrength.WEAK
        else:
            return MomentumStrength.NONE
    
    def _detect_reversal(
        self,
        obs: List[PriceObservation],
    ) -> Tuple[Optional[int], Optional[float]]:
        """Detect price reversals."""
        if len(obs) < 5:
            return None, None
        
        # Look for sign change in velocity
        velocities = []
        for i in range(1, len(obs)):
            if obs[i-1].median_price == 0:
                continue
            v = (obs[i].median_price - obs[i-1].median_price) / obs[i-1].median_price
            velocities.append((obs[i].observed_at, v))
        
        if len(velocities) < 3:
            return None, None
        
        # Find most recent sign change
        for i in range(len(velocities) - 1, 1, -1):
            curr_sign = 1 if velocities[i][1] > 0 else -1
            prev_sign = 1 if velocities[i-1][1] > 0 else -1
            
            if curr_sign != prev_sign:
                days = (datetime.utcnow() - velocities[i][0]).days
                magnitude = abs(velocities[i][1])
                return days, magnitude
        
        return None, None
    
    def _calculate_confidence(self, obs: List[PriceObservation]) -> float:
        """Calculate confidence based on data quality."""
        if not obs:
            return 0.0
        
        # Factors: sample count, recency, consistency
        count_factor = min(len(obs) / 30, 1.0)  # More observations = better
        
        # Recency
        latest = obs[-1]
        days_old = (datetime.utcnow() - latest.observed_at).days
        recency_factor = max(0, 1.0 - days_old / 14)  # Decay over 14 days
        
        # Sample size
        avg_sample = sum(o.sample_size for o in obs) / len(obs)
        sample_factor = min(avg_sample / 50, 1.0)
        
        return (count_factor * 0.3 + recency_factor * 0.4 + sample_factor * 0.3)
    
    def _empty_result(self, geo_id: str, now: datetime) -> PriceVelocityResult:
        """Return empty result."""
        return PriceVelocityResult(
            geo_id=geo_id,
            calculated_at=now,
            velocity_7d=0.0,
            velocity_14d=0.0,
            velocity_30d=0.0,
            ewma_velocity=0.0,
            ewma_span=self.ewma_span,
            direction=PriceDirection.STABLE,
            direction_confidence=0.0,
            momentum=0.0,
            momentum_strength=MomentumStrength.NONE,
            confidence=0.0,
            sample_count=0,
        )


# =============================================================================
# CALENDAR DELTA ENGINE
# =============================================================================

class CalendarDeltaEngine:
    """
    Tracks calendar changes over time.
    
    Instead of "is a date blocked?", we track:
    - When it became blocked
    - How many days ahead
    - Whether price changed beforehand
    
    This allows inference of:
    - Booking lead times
    - Urgency
    - Price elasticity
    """
    
    def __init__(self):
        pass
    
    def calculate_compression_delta(
        self,
        observations: List[CalendarObservation],
        geo_id: str = "",
    ) -> CalendarDeltaResult:
        """
        Calculate calendar compression delta.
        
        Args:
            observations: List of calendar observations (oldest first)
            geo_id: Market identifier
            
        Returns:
            CalendarDeltaResult with delta metrics
        """
        now = datetime.utcnow()
        
        # Sort by date
        obs = sorted(observations, key=lambda x: x.observed_at)
        
        if len(obs) < 2:
            return self._empty_result(geo_id, now)
        
        # Calculate deltas
        delta_7d = self._calculate_compression_delta(obs, "blocked_pct_7d")
        delta_30d = self._calculate_compression_delta(obs, "blocked_pct_30d")
        
        # Calculate compression speed
        speed = self._calculate_compression_speed(obs)
        
        # Calculate acceleration
        acceleration = self._calculate_acceleration(obs)
        
        # Determine direction
        direction, direction_conf = self._determine_direction(delta_7d, delta_30d)
        
        # Estimate booking velocity
        booking_velocity = self._estimate_booking_velocity(obs)
        
        # Calculate lead time shift
        lead_time_shift = self._calculate_lead_time_shift(obs)
        
        # Calculate confidence
        confidence = self._calculate_confidence(obs)
        
        return CalendarDeltaResult(
            geo_id=geo_id,
            calculated_at=now,
            compression_delta_7d=delta_7d,
            compression_delta_30d=delta_30d,
            compression_speed=speed,
            compression_acceleration=acceleration,
            direction=direction,
            direction_confidence=direction_conf,
            estimated_booking_velocity=booking_velocity,
            lead_time_shift_pct=lead_time_shift,
            confidence=confidence,
            sample_count=len(obs),
        )
    
    def _calculate_compression_delta(
        self,
        obs: List[CalendarObservation],
        field: str,
    ) -> float:
        """Calculate delta for a compression field."""
        if len(obs) < 2:
            return 0.0
        
        latest = getattr(obs[-1], field, 0)
        earliest = getattr(obs[0], field, 0)
        
        return latest - earliest
    
    def _calculate_compression_speed(
        self,
        obs: List[CalendarObservation],
    ) -> float:
        """Calculate how fast inventory is disappearing (% per day)."""
        if len(obs) < 2:
            return 0.0
        
        latest = obs[-1]
        earliest = obs[0]
        
        days = (latest.observed_at - earliest.observed_at).days
        if days == 0:
            return 0.0
        
        delta = latest.blocked_pct_30d - earliest.blocked_pct_30d
        
        return delta / days
    
    def _calculate_acceleration(
        self,
        obs: List[CalendarObservation],
    ) -> float:
        """Calculate change in compression speed."""
        if len(obs) < 4:
            return 0.0
        
        mid = len(obs) // 2
        
        recent = obs[mid:]
        older = obs[:mid]
        
        recent_speed = self._calculate_compression_speed(recent)
        older_speed = self._calculate_compression_speed(older)
        
        return recent_speed - older_speed
    
    def _determine_direction(
        self,
        delta_7d: float,
        delta_30d: float,
    ) -> Tuple[DemandDirection, float]:
        """Determine demand direction."""
        # Positive delta = more blocked = higher demand
        avg_delta = (delta_7d + delta_30d) / 2
        
        if avg_delta > 0.05:
            direction = DemandDirection.ACCELERATING
        elif avg_delta < -0.05:
            direction = DemandDirection.DECELERATING
        else:
            direction = DemandDirection.STABLE
        
        # Confidence based on agreement
        same_sign = (delta_7d * delta_30d) > 0
        confidence = 0.8 if same_sign else 0.5
        
        return direction, confidence
    
    def _estimate_booking_velocity(
        self,
        obs: List[CalendarObservation],
    ) -> float:
        """Estimate bookings per day from compression changes."""
        if len(obs) < 2:
            return 0.0
        
        latest = obs[-1]
        earliest = obs[0]
        
        days = (latest.observed_at - earliest.observed_at).days
        if days == 0:
            return 0.0
        
        # Estimate: blocked nights gained
        blocked_gained = (latest.blocked_pct_30d - earliest.blocked_pct_30d) * 30
        
        if blocked_gained < 0:
            return 0.0
        
        # Assume average stay of 4 nights
        estimated_bookings = blocked_gained / 4
        
        return estimated_bookings / days
    
    def _calculate_lead_time_shift(
        self,
        obs: List[CalendarObservation],
    ) -> Optional[float]:
        """Calculate shift in booking lead times."""
        if len(obs) < 4:
            return None
        
        # Compare 7d vs 30d compression ratio over time
        recent = obs[-2:]
        older = obs[:2]
        
        def compression_ratio(o: CalendarObservation) -> float:
            if o.blocked_pct_30d == 0:
                return 0
            return o.blocked_pct_7d / o.blocked_pct_30d
        
        recent_ratio = sum(compression_ratio(o) for o in recent) / len(recent)
        older_ratio = sum(compression_ratio(o) for o in older) / len(older)
        
        if older_ratio == 0:
            return None
        
        # Higher ratio = more near-term bookings = shorter lead time
        shift = (recent_ratio - older_ratio) / older_ratio
        
        return shift
    
    def _calculate_confidence(self, obs: List[CalendarObservation]) -> float:
        """Calculate confidence."""
        if not obs:
            return 0.0
        
        count_factor = min(len(obs) / 14, 1.0)
        
        latest = obs[-1]
        days_old = (datetime.utcnow() - latest.observed_at).days
        recency_factor = max(0, 1.0 - days_old / 7)
        
        avg_listings = sum(o.total_listings for o in obs) / len(obs)
        sample_factor = min(avg_listings / 100, 1.0)
        
        return (count_factor * 0.3 + recency_factor * 0.4 + sample_factor * 0.3)
    
    def _empty_result(self, geo_id: str, now: datetime) -> CalendarDeltaResult:
        """Return empty result."""
        return CalendarDeltaResult(
            geo_id=geo_id,
            calculated_at=now,
            compression_delta_7d=0.0,
            compression_delta_30d=0.0,
            compression_speed=0.0,
            compression_acceleration=0.0,
            direction=DemandDirection.STABLE,
            direction_confidence=0.0,
            estimated_booking_velocity=0.0,
            confidence=0.0,
            sample_count=0,
        )


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def calculate_price_velocity(
    price_history: List[Dict],
    geo_id: str = "",
) -> PriceVelocityResult:
    """
    Calculate price velocity from price history (convenience function).
    
    Args:
        price_history: List of dicts with observed_at, median_price
        geo_id: Market identifier
        
    Returns:
        PriceVelocityResult
    """
    # Convert to observations
    observations = []
    for item in price_history:
        observed = item.get("observed_at")
        if isinstance(observed, str):
            observed = datetime.fromisoformat(observed.replace('Z', '+00:00'))
        
        observations.append(PriceObservation(
            observed_at=observed,
            median_price=item.get("median_price") or item.get("p50", 0),
            p25_price=item.get("p25"),
            p75_price=item.get("p75"),
            sample_size=item.get("sample_size", 0),
        ))
    
    engine = PriceVelocityEngine()
    return engine.calculate_velocity(observations, geo_id)


def calculate_calendar_delta(
    calendar_history: List[Dict],
    geo_id: str = "",
) -> CalendarDeltaResult:
    """
    Calculate calendar delta from history (convenience function).
    
    Args:
        calendar_history: List of dicts with observed_at, blocked_pct_*
        geo_id: Market identifier
        
    Returns:
        CalendarDeltaResult
    """
    observations = []
    for item in calendar_history:
        observed = item.get("observed_at")
        if isinstance(observed, str):
            observed = datetime.fromisoformat(observed.replace('Z', '+00:00'))
        
        observations.append(CalendarObservation(
            observed_at=observed,
            blocked_pct_7d=item.get("blocked_pct_7d", 0),
            blocked_pct_30d=item.get("blocked_pct_30d", 0),
            blocked_pct_60d=item.get("blocked_pct_60d"),
            total_listings=item.get("total_listings", 0),
        ))
    
    engine = CalendarDeltaEngine()
    return engine.calculate_compression_delta(observations, geo_id)
