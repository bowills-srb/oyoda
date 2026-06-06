"""
Signal Health Module - Freshness & Coverage Scoring.

Small primitive, huge impact.

This module provides:
- signal_freshness_score: How recent are signals?
- coverage_score: How complete is the bundle?
- health_grade: A/B/C/D/F rating

Exposed everywhere:
- APIs
- BD outputs
- Concierge responses
- Investment reports

Why this matters:
- Graceful degradation
- Trust protection
- "We don't know" intelligence

AirDNA cannot do this.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Set
from uuid import UUID

from app.services.signals.signal_contract import (
    Signal,
    SignalBundle,
    SignalType,
)


# =============================================================================
# HEALTH GRADES
# =============================================================================

class HealthGrade(str, Enum):
    """Signal health grades."""
    A = "A"  # Excellent - full confidence
    B = "B"  # Good - minor gaps
    C = "C"  # Acceptable - some uncertainty
    D = "D"  # Poor - significant gaps
    F = "F"  # Failing - unreliable


# =============================================================================
# REQUIRED SIGNALS BY USE CASE
# =============================================================================

class SignalRequirements:
    """
    Signal requirements by use case.
    
    Different outputs need different signals.
    """
    
    # Core signals needed for basic operations
    CORE = {
        SignalType.SEASONALITY_CURVE,
        SignalType.PLATFORM_DOMINANCE,
    }
    
    # Pricing decisions
    PRICING = CORE | {
        SignalType.OCCUPANCY_MOMENTUM,
        SignalType.PRICE_ELASTICITY,
        SignalType.AMENITY_LIFT,
    }
    
    # Discount evaluation
    DISCOUNT = CORE | {
        SignalType.OCCUPANCY_MOMENTUM,
        SignalType.PRICE_ELASTICITY,
        SignalType.OPERATOR_DELTA,
    }
    
    # Investment analysis
    INVESTMENT = CORE | {
        SignalType.AMENITY_LIFT,
        SignalType.OPERATOR_DELTA,
        SignalType.DEMAND_PRESSURE,
    }
    
    # Forecasting
    FORECAST = CORE | {
        SignalType.OCCUPANCY_MOMENTUM,
        SignalType.DEMAND_PRESSURE,
        SignalType.SUPPLY_VELOCITY,
    }
    
    # Concierge (minimal)
    CONCIERGE = {
        SignalType.SEASONALITY_CURVE,
    }
    
    # Full analysis
    FULL = PRICING | INVESTMENT | FORECAST


# =============================================================================
# FRESHNESS THRESHOLDS
# =============================================================================

class FreshnessThresholds:
    """
    How old is too old for each signal type?
    
    Signals decay at different rates.
    """
    
    # Very stable signals (6+ months ok)
    VERY_STABLE = {
        SignalType.PLATFORM_DOMINANCE: timedelta(days=180),
        SignalType.MARKET_SIMILARITY: timedelta(days=180),
    }
    
    # Stable signals (3 months ok)
    STABLE = {
        SignalType.SEASONALITY_CURVE: timedelta(days=90),
        SignalType.AMENITY_LIFT: timedelta(days=90),
        SignalType.OPERATOR_DELTA: timedelta(days=90),
    }
    
    # Moderate signals (1 month ok)
    MODERATE = {
        SignalType.DEMAND_PRESSURE: timedelta(days=30),
        SignalType.SUPPLY_VELOCITY: timedelta(days=30),
        SignalType.BOOKING_LEAD_TIME: timedelta(days=30),
    }
    
    # Volatile signals (1-2 weeks ok)
    VOLATILE = {
        SignalType.OCCUPANCY_MOMENTUM: timedelta(days=14),
        SignalType.PRICE_ELASTICITY: timedelta(days=14),
        SignalType.COMPETITOR_RATE_MOVEMENT: timedelta(days=7),
    }
    
    @classmethod
    def get_max_age(cls, signal_type: SignalType) -> timedelta:
        """Get maximum acceptable age for a signal type."""
        for category in [cls.VERY_STABLE, cls.STABLE, cls.MODERATE, cls.VOLATILE]:
            if signal_type in category:
                return category[signal_type]
        return timedelta(days=30)  # Default


# =============================================================================
# HEALTH SCORES
# =============================================================================

@dataclass
class SignalFreshness:
    """Freshness assessment for a single signal type."""
    signal_type: SignalType
    
    # Is it present?
    present: bool
    
    # Age info
    age_days: Optional[float] = None
    max_age_days: float = 30.0
    
    # Freshness score (0-1, 1 = fresh)
    freshness_score: float = 0.0
    
    # Status
    is_fresh: bool = False
    is_stale: bool = False
    is_missing: bool = False
    
    @property
    def status(self) -> str:
        if self.is_missing:
            return "missing"
        if self.is_stale:
            return "stale"
        if self.is_fresh:
            return "fresh"
        return "aging"


@dataclass
class SignalHealthReport:
    """
    Complete health report for a SignalBundle.
    
    This is THE object to expose everywhere.
    """
    # Overall scores (0-1)
    freshness_score: float
    coverage_score: float
    overall_score: float
    
    # Grade
    grade: HealthGrade
    
    # Per-signal breakdown
    signal_health: Dict[str, SignalFreshness] = field(default_factory=dict)
    
    # Lists for quick access
    fresh_signals: List[SignalType] = field(default_factory=list)
    stale_signals: List[SignalType] = field(default_factory=list)
    missing_signals: List[SignalType] = field(default_factory=list)
    
    # Recommendations
    recommendations: List[str] = field(default_factory=list)
    
    # Context
    use_case: str = "full"
    required_signals: int = 0
    present_signals: int = 0
    
    # Computed at
    computed_at: datetime = field(default_factory=datetime.utcnow)
    
    def is_sufficient_for(self, min_grade: HealthGrade = HealthGrade.C) -> bool:
        """Check if health is sufficient for operations."""
        grade_order = [HealthGrade.F, HealthGrade.D, HealthGrade.C, HealthGrade.B, HealthGrade.A]
        return grade_order.index(self.grade) >= grade_order.index(min_grade)
    
    def to_dict(self) -> Dict:
        """Convert to dict for API responses."""
        return {
            "freshness_score": round(self.freshness_score, 3),
            "coverage_score": round(self.coverage_score, 3),
            "overall_score": round(self.overall_score, 3),
            "grade": self.grade.value,
            "fresh_count": len(self.fresh_signals),
            "stale_count": len(self.stale_signals),
            "missing_count": len(self.missing_signals),
            "recommendations": self.recommendations[:3],  # Top 3
        }
    
    def to_badge(self) -> str:
        """Generate a badge string for UI."""
        return f"Signal Health: {self.grade.value} ({self.overall_score:.0%})"


# =============================================================================
# HEALTH SCORING SERVICE
# =============================================================================

class SignalHealthService:
    """
    Signal Health Scoring Service.
    
    Computes freshness, coverage, and overall health for SignalBundles.
    """
    
    def __init__(self):
        self.version = "1.0.0"
    
    def assess_health(
        self,
        signal_bundle: SignalBundle,
        use_case: str = "full",
        as_of: Optional[datetime] = None,
    ) -> SignalHealthReport:
        """
        Assess health of a signal bundle.
        
        Args:
            signal_bundle: Bundle to assess
            use_case: What the signals are needed for
            as_of: Point in time for freshness calculation
        
        Returns:
            SignalHealthReport with scores and recommendations
        """
        as_of = as_of or datetime.utcnow()
        
        # Get required signals for use case
        required = self._get_required_signals(use_case)
        
        # Assess each signal
        signal_health = {}
        fresh_signals = []
        stale_signals = []
        missing_signals = []
        
        freshness_scores = []
        
        for sig_type in required:
            assessment = self._assess_signal_freshness(
                signal_bundle, sig_type, as_of
            )
            signal_health[sig_type.value] = assessment
            
            if assessment.is_missing:
                missing_signals.append(sig_type)
                freshness_scores.append(0.0)
            elif assessment.is_stale:
                stale_signals.append(sig_type)
                freshness_scores.append(assessment.freshness_score)
            else:
                fresh_signals.append(sig_type)
                freshness_scores.append(assessment.freshness_score)
        
        # Calculate scores
        coverage_score = (len(required) - len(missing_signals)) / len(required) if required else 0
        freshness_score = sum(freshness_scores) / len(freshness_scores) if freshness_scores else 0
        
        # Overall score (weighted)
        overall_score = coverage_score * 0.6 + freshness_score * 0.4
        
        # Determine grade
        grade = self._calculate_grade(overall_score, coverage_score, len(missing_signals))
        
        # Generate recommendations
        recommendations = self._generate_recommendations(
            missing_signals, stale_signals, grade
        )
        
        return SignalHealthReport(
            freshness_score=freshness_score,
            coverage_score=coverage_score,
            overall_score=overall_score,
            grade=grade,
            signal_health=signal_health,
            fresh_signals=fresh_signals,
            stale_signals=stale_signals,
            missing_signals=missing_signals,
            recommendations=recommendations,
            use_case=use_case,
            required_signals=len(required),
            present_signals=len(required) - len(missing_signals),
        )
    
    def _get_required_signals(self, use_case: str) -> Set[SignalType]:
        """Get required signals for a use case."""
        use_case_map = {
            "core": SignalRequirements.CORE,
            "pricing": SignalRequirements.PRICING,
            "discount": SignalRequirements.DISCOUNT,
            "investment": SignalRequirements.INVESTMENT,
            "forecast": SignalRequirements.FORECAST,
            "concierge": SignalRequirements.CONCIERGE,
            "full": SignalRequirements.FULL,
        }
        return use_case_map.get(use_case, SignalRequirements.CORE)
    
    def _assess_signal_freshness(
        self,
        bundle: SignalBundle,
        signal_type: SignalType,
        as_of: datetime,
    ) -> SignalFreshness:
        """Assess freshness of a single signal type."""
        
        max_age = FreshnessThresholds.get_max_age(signal_type)
        max_age_days = max_age.total_seconds() / 86400
        
        if not bundle.has_signal(signal_type):
            return SignalFreshness(
                signal_type=signal_type,
                present=False,
                max_age_days=max_age_days,
                freshness_score=0.0,
                is_missing=True,
            )
        
        # Get latest signal
        latest = bundle.get_latest(signal_type)
        if not latest:
            return SignalFreshness(
                signal_type=signal_type,
                present=False,
                max_age_days=max_age_days,
                freshness_score=0.0,
                is_missing=True,
            )
        
        # Calculate age
        age = as_of - latest.detected_at
        age_days = age.total_seconds() / 86400
        
        # Calculate freshness score (1 = brand new, 0 = at max age)
        if age_days <= 0:
            freshness_score = 1.0
        elif age_days >= max_age_days:
            freshness_score = 0.0
        else:
            # Linear decay
            freshness_score = 1.0 - (age_days / max_age_days)
        
        # Determine status
        is_fresh = freshness_score >= 0.7
        is_stale = freshness_score < 0.3
        
        return SignalFreshness(
            signal_type=signal_type,
            present=True,
            age_days=age_days,
            max_age_days=max_age_days,
            freshness_score=freshness_score,
            is_fresh=is_fresh,
            is_stale=is_stale,
            is_missing=False,
        )
    
    def _calculate_grade(
        self,
        overall_score: float,
        coverage_score: float,
        missing_count: int,
    ) -> HealthGrade:
        """Calculate health grade."""
        
        # Critical missing signals = automatic downgrade
        if missing_count >= 3:
            return HealthGrade.F
        if missing_count >= 2:
            return HealthGrade.D
        
        # Score-based grading
        if overall_score >= 0.85 and coverage_score >= 0.90:
            return HealthGrade.A
        if overall_score >= 0.70 and coverage_score >= 0.75:
            return HealthGrade.B
        if overall_score >= 0.50 and coverage_score >= 0.60:
            return HealthGrade.C
        if overall_score >= 0.30:
            return HealthGrade.D
        
        return HealthGrade.F
    
    def _generate_recommendations(
        self,
        missing: List[SignalType],
        stale: List[SignalType],
        grade: HealthGrade,
    ) -> List[str]:
        """Generate actionable recommendations."""
        
        recommendations = []
        
        # Missing signals
        for sig_type in missing[:2]:  # Top 2
            readable = sig_type.value.replace("_", " ").title()
            recommendations.append(f"Run {readable} detector to improve coverage")
        
        # Stale signals
        for sig_type in stale[:2]:
            readable = sig_type.value.replace("_", " ").title()
            recommendations.append(f"Refresh {readable} signal (stale)")
        
        # Grade-specific
        if grade == HealthGrade.F:
            recommendations.insert(0, "CRITICAL: Signal coverage insufficient for reliable outputs")
        elif grade == HealthGrade.D:
            recommendations.insert(0, "WARNING: Outputs may be unreliable due to signal gaps")
        
        return recommendations


# =============================================================================
# SINGLETON & CONVENIENCE
# =============================================================================

_service: Optional[SignalHealthService] = None


def get_health_service() -> SignalHealthService:
    """Get health service singleton."""
    global _service
    if _service is None:
        _service = SignalHealthService()
    return _service


def assess_signal_health(
    signal_bundle: SignalBundle,
    use_case: str = "full",
) -> SignalHealthReport:
    """
    Assess signal health.
    
    This is THE function to call before any output.
    
    Example:
        health = assess_signal_health(bundle, use_case="pricing")
        if not health.is_sufficient_for(HealthGrade.C):
            return GatedResponse(reason="insufficient_signals")
    """
    return get_health_service().assess_health(signal_bundle, use_case)


def get_health_badge(signal_bundle: SignalBundle) -> str:
    """Get a quick health badge for display."""
    health = assess_signal_health(signal_bundle, use_case="core")
    return health.to_badge()


def is_healthy_for(
    signal_bundle: SignalBundle,
    use_case: str,
    min_grade: HealthGrade = HealthGrade.C,
) -> bool:
    """Quick check if bundle is healthy enough for use case."""
    health = assess_signal_health(signal_bundle, use_case)
    return health.is_sufficient_for(min_grade)
