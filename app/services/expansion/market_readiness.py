"""
Market Entry Readiness Score.

A single composite score per market that tells operators:
"Should I expand here, and how confident are we?"

Components:
- Signal coverage (do we have data?)
- Seasonality volatility (how risky?)
- Platform dominance (channel strategy)
- Operator similarity score (will your playbook work?)
- Data confidence (can we trust projections?)

This is what AirDNA cannot do:
- They show opportunity
- We show READINESS
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from app.services.signals import (
    SignalBundle,
    SignalType,
    get_seasonality,
    get_platform_bias,
    get_amenity_lift,
)
from app.services.health.signal_health import (
    assess_signal_health,
    HealthGrade,
    SignalHealthReport,
)


# =============================================================================
# READINESS MODELS
# =============================================================================

class ReadinessLevel(str, Enum):
    """Market readiness levels."""
    HIGHLY_READY = "highly_ready"      # 80-100: Go with confidence
    READY = "ready"                     # 65-79: Proceed with monitoring
    CAUTIOUS = "cautious"               # 50-64: More research needed
    NOT_READY = "not_ready"             # 30-49: Significant gaps
    AVOID = "avoid"                     # 0-29: Do not enter


class RiskLevel(str, Enum):
    """Risk classification."""
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    VERY_HIGH = "very_high"


@dataclass
class ReadinessComponent:
    """
    A single component of the readiness score.
    
    Each component contributes to the overall score with its own weight.
    """
    name: str
    score: float  # 0-100
    weight: float  # 0-1, weights sum to 1
    
    # Details
    status: str  # "strong", "moderate", "weak", "critical"
    explanation: str
    
    # Flags
    is_blocker: bool = False  # If true, can cap overall score
    
    @property
    def weighted_score(self) -> float:
        return self.score * self.weight


@dataclass
class MarketReadinessScore:
    """
    Complete market readiness assessment.
    
    This is THE output for expansion decisions.
    """
    # Market identification
    geo_id: str
    market_name: str
    
    # Overall score
    score: int  # 0-100
    level: ReadinessLevel
    
    # Component breakdown
    components: List[ReadinessComponent] = field(default_factory=list)
    
    # Risk assessment
    risk_level: RiskLevel = RiskLevel.MODERATE
    risk_factors: List[str] = field(default_factory=list)
    
    # Opportunity indicators
    opportunity_factors: List[str] = field(default_factory=list)
    
    # Recommendation
    recommendation: str = ""
    action_items: List[str] = field(default_factory=list)
    
    # Confidence in this assessment
    confidence: float = 0.0
    
    # Summary for executives
    executive_summary: str = ""
    
    # Metadata
    computed_at: datetime = field(default_factory=datetime.utcnow)
    
    def is_expansion_candidate(self) -> bool:
        """Is this market worth pursuing?"""
        return self.level in [ReadinessLevel.HIGHLY_READY, ReadinessLevel.READY]
    
    def to_badge(self) -> str:
        """Generate badge for UI."""
        return f"{self.market_name} — Readiness: {self.score}/100"


# =============================================================================
# READINESS SERVICE
# =============================================================================

class MarketReadinessService:
    """
    Market Entry Readiness Service.
    
    Produces a single composite score that answers:
    "Should I expand into this market?"
    
    Unlike AirDNA which shows opportunity,
    we show READINESS - which includes:
    - Do we have enough data?
    - Will the operator's playbook transfer?
    - What are the specific risks?
    """
    
    # Component weights (must sum to 1.0)
    WEIGHTS = {
        "signal_coverage": 0.25,
        "seasonality_fit": 0.20,
        "platform_alignment": 0.15,
        "operator_fit": 0.20,
        "data_confidence": 0.20,
    }
    
    def __init__(self):
        self.version = "1.0.0"
    
    def assess_market(
        self,
        target_bundle: SignalBundle,
        market_name: str,
        operator_profile: Optional[Dict[str, Any]] = None,
        home_market_bundle: Optional[SignalBundle] = None,
    ) -> MarketReadinessScore:
        """
        Assess market readiness for expansion.
        
        Args:
            target_bundle: SignalBundle for target market
            market_name: Human-readable market name
            operator_profile: Operator's characteristics (amenities, style, etc.)
            home_market_bundle: Operator's current market for comparison
        
        Returns:
            MarketReadinessScore with complete assessment
        """
        components = []
        risk_factors = []
        opportunity_factors = []
        
        # =================================================================
        # Component 1: Signal Coverage
        # =================================================================
        coverage = self._assess_signal_coverage(target_bundle)
        components.append(coverage)
        
        if coverage.is_blocker:
            risk_factors.append("Insufficient market data")
        elif coverage.score >= 80:
            opportunity_factors.append("Strong data coverage")
        
        # =================================================================
        # Component 2: Seasonality Fit
        # =================================================================
        seasonality = self._assess_seasonality_fit(target_bundle, operator_profile)
        components.append(seasonality)
        
        if seasonality.score < 50:
            risk_factors.append("High seasonality volatility")
        elif seasonality.score >= 75:
            opportunity_factors.append("Favorable demand patterns")
        
        # =================================================================
        # Component 3: Platform Alignment
        # =================================================================
        platform = self._assess_platform_alignment(target_bundle, operator_profile)
        components.append(platform)
        
        if platform.score < 50:
            risk_factors.append("Platform distribution mismatch")
        elif platform.score >= 75:
            opportunity_factors.append("Strong platform fit")
        
        # =================================================================
        # Component 4: Operator Fit
        # =================================================================
        operator_fit = self._assess_operator_fit(
            target_bundle, operator_profile, home_market_bundle
        )
        components.append(operator_fit)
        
        if operator_fit.score < 50:
            risk_factors.append("Operator playbook may not transfer")
        elif operator_fit.score >= 75:
            opportunity_factors.append("High operator-market alignment")
        
        # =================================================================
        # Component 5: Data Confidence
        # =================================================================
        confidence = self._assess_data_confidence(target_bundle)
        components.append(confidence)
        
        if confidence.score < 50:
            risk_factors.append("Low projection confidence")
        
        # =================================================================
        # Calculate overall score
        # =================================================================
        
        # Base score from weighted components
        raw_score = sum(c.weighted_score for c in components)
        
        # Apply blocker penalties
        blockers = [c for c in components if c.is_blocker]
        if blockers:
            # Cap score at 40 if any blockers
            raw_score = min(40, raw_score)
        
        score = int(round(raw_score))
        
        # =================================================================
        # Determine level and risk
        # =================================================================
        level = self._determine_level(score)
        risk_level = self._determine_risk(score, risk_factors)
        
        # =================================================================
        # Generate recommendation
        # =================================================================
        recommendation, action_items = self._generate_recommendation(
            score, level, risk_factors, opportunity_factors, components
        )
        
        # =================================================================
        # Generate executive summary
        # =================================================================
        executive_summary = self._generate_executive_summary(
            market_name, score, level, risk_factors, opportunity_factors
        )
        
        # Overall confidence (average of component confidences)
        overall_confidence = sum(c.score for c in components) / len(components) / 100
        
        return MarketReadinessScore(
            geo_id=target_bundle.geo_id,
            market_name=market_name,
            score=score,
            level=level,
            components=components,
            risk_level=risk_level,
            risk_factors=risk_factors,
            opportunity_factors=opportunity_factors,
            recommendation=recommendation,
            action_items=action_items,
            confidence=overall_confidence,
            executive_summary=executive_summary,
        )
    
    def _assess_signal_coverage(self, bundle: SignalBundle) -> ReadinessComponent:
        """Assess signal coverage for the market."""
        health = assess_signal_health(bundle, use_case="investment")
        
        # Map health grade to score
        grade_scores = {
            HealthGrade.A: 95,
            HealthGrade.B: 80,
            HealthGrade.C: 65,
            HealthGrade.D: 40,
            HealthGrade.F: 15,
        }
        
        score = grade_scores.get(health.grade, 50)
        
        # Determine status
        if score >= 80:
            status = "strong"
            explanation = f"Excellent signal coverage ({health.present_signals}/{health.required_signals} signals)"
        elif score >= 60:
            status = "moderate"
            explanation = f"Adequate coverage with some gaps ({health.present_signals}/{health.required_signals} signals)"
        elif score >= 40:
            status = "weak"
            explanation = f"Limited data available ({health.present_signals}/{health.required_signals} signals)"
        else:
            status = "critical"
            explanation = f"Insufficient data for reliable analysis ({health.present_signals}/{health.required_signals} signals)"
        
        return ReadinessComponent(
            name="Signal Coverage",
            score=score,
            weight=self.WEIGHTS["signal_coverage"],
            status=status,
            explanation=explanation,
            is_blocker=score < 30,
        )
    
    def _assess_seasonality_fit(
        self,
        bundle: SignalBundle,
        operator_profile: Optional[Dict] = None,
    ) -> ReadinessComponent:
        """Assess seasonality patterns for operator fit."""
        seasonality = get_seasonality(bundle)
        
        # Get seasonality strength (volatility)
        strength = seasonality.strength or 1.5
        multiplier = seasonality.multiplier
        
        # Higher volatility = lower score (more risk)
        # But some operators prefer high seasonality
        
        operator_prefers_seasonal = (
            operator_profile.get("prefers_seasonal", False) 
            if operator_profile else False
        )
        
        if strength < 1.3:
            # Low seasonality - stable market
            score = 85 if not operator_prefers_seasonal else 70
            status = "strong"
            explanation = "Stable year-round demand with low volatility"
        elif strength < 2.0:
            # Moderate seasonality
            score = 75
            status = "moderate"
            explanation = f"Moderate seasonality (peak factor: {multiplier:.2f}x)"
        elif strength < 3.0:
            # High seasonality
            score = 55 if operator_prefers_seasonal else 45
            status = "weak"
            explanation = f"High seasonality - revenue concentrated in peak periods"
        else:
            # Extreme seasonality
            score = 35
            status = "critical"
            explanation = "Extreme seasonality creates significant cash flow risk"
        
        return ReadinessComponent(
            name="Seasonality Fit",
            score=score,
            weight=self.WEIGHTS["seasonality_fit"],
            status=status,
            explanation=explanation,
            is_blocker=False,
        )
    
    def _assess_platform_alignment(
        self,
        bundle: SignalBundle,
        operator_profile: Optional[Dict] = None,
    ) -> ReadinessComponent:
        """Assess platform distribution alignment."""
        platform = get_platform_bias(bundle)
        
        # Get operator's preferred platform
        preferred = (
            operator_profile.get("primary_platform", "balanced")
            if operator_profile else "balanced"
        )
        
        # Calculate alignment
        if preferred == "airbnb":
            alignment = platform.airbnb_share
        elif preferred == "vrbo":
            alignment = platform.vrbo_share
        else:
            # Prefer balanced markets
            alignment = 1 - abs(platform.airbnb_share - 0.5) * 2
        
        score = int(alignment * 100)
        
        if platform.is_balanced():
            status = "strong"
            explanation = "Balanced platform distribution reduces channel risk"
        elif platform.is_airbnb_dominant():
            status = "moderate" if preferred == "airbnb" else "weak"
            explanation = f"Airbnb-dominant market ({platform.airbnb_share:.0%})"
        else:
            status = "moderate" if preferred == "vrbo" else "weak"
            explanation = f"VRBO-dominant market ({platform.vrbo_share:.0%})"
        
        return ReadinessComponent(
            name="Platform Alignment",
            score=score,
            weight=self.WEIGHTS["platform_alignment"],
            status=status,
            explanation=explanation,
            is_blocker=False,
        )
    
    def _assess_operator_fit(
        self,
        target_bundle: SignalBundle,
        operator_profile: Optional[Dict] = None,
        home_bundle: Optional[SignalBundle] = None,
    ) -> ReadinessComponent:
        """Assess how well operator's playbook transfers."""
        
        if not operator_profile:
            # No profile - neutral score
            return ReadinessComponent(
                name="Operator Fit",
                score=60,
                weight=self.WEIGHTS["operator_fit"],
                status="moderate",
                explanation="No operator profile provided - using market defaults",
                is_blocker=False,
            )
        
        fit_score = 70  # Base score
        factors = []
        
        # Check amenity alignment
        operator_amenities = set(operator_profile.get("amenities", []))
        if operator_amenities:
            amenity_lift = get_amenity_lift(target_bundle, list(operator_amenities))
            if amenity_lift.multiplier > 1.05:
                fit_score += 15
                factors.append("Amenity portfolio valued in this market")
            elif amenity_lift.multiplier < 0.98:
                fit_score -= 10
                factors.append("Amenity portfolio less valued here")
        
        # Check property type fit
        property_type = operator_profile.get("property_type", "single_family")
        # (In real implementation, would check against market signals)
        
        # Check price point alignment
        operator_adr = operator_profile.get("typical_adr", 0)
        if operator_adr > 0:
            seasonality = get_seasonality(target_bundle)
            # (Would compare to market ADR signals)
            fit_score += 5  # Placeholder
        
        # Compare to home market if available
        if home_bundle:
            home_season = get_seasonality(home_bundle)
            target_season = get_seasonality(target_bundle)
            
            # Similar seasonality patterns = better fit
            pattern_diff = abs(
                (home_season.multiplier or 1) - (target_season.multiplier or 1)
            )
            if pattern_diff < 0.2:
                fit_score += 10
                factors.append("Similar seasonality to home market")
            elif pattern_diff > 0.5:
                fit_score -= 10
                factors.append("Different seasonality pattern than home market")
        
        score = max(20, min(95, fit_score))
        
        if score >= 75:
            status = "strong"
        elif score >= 55:
            status = "moderate"
        else:
            status = "weak"
        
        explanation = "; ".join(factors) if factors else "Moderate operator-market alignment"
        
        return ReadinessComponent(
            name="Operator Fit",
            score=score,
            weight=self.WEIGHTS["operator_fit"],
            status=status,
            explanation=explanation,
            is_blocker=False,
        )
    
    def _assess_data_confidence(self, bundle: SignalBundle) -> ReadinessComponent:
        """Assess overall data confidence."""
        health = assess_signal_health(bundle, use_case="investment")
        
        # Use freshness score directly
        score = int(health.freshness_score * 100)
        
        if score >= 80:
            status = "strong"
            explanation = "Fresh, high-quality signals available"
        elif score >= 60:
            status = "moderate"
            explanation = "Adequate data freshness"
        elif score >= 40:
            status = "weak"
            explanation = "Some signals are stale - verify before acting"
        else:
            status = "critical"
            explanation = "Data freshness is poor - projections unreliable"
        
        return ReadinessComponent(
            name="Data Confidence",
            score=score,
            weight=self.WEIGHTS["data_confidence"],
            status=status,
            explanation=explanation,
            is_blocker=score < 25,
        )
    
    def _determine_level(self, score: int) -> ReadinessLevel:
        """Determine readiness level from score."""
        if score >= 80:
            return ReadinessLevel.HIGHLY_READY
        elif score >= 65:
            return ReadinessLevel.READY
        elif score >= 50:
            return ReadinessLevel.CAUTIOUS
        elif score >= 30:
            return ReadinessLevel.NOT_READY
        else:
            return ReadinessLevel.AVOID
    
    def _determine_risk(
        self,
        score: int,
        risk_factors: List[str],
    ) -> RiskLevel:
        """Determine overall risk level."""
        risk_count = len(risk_factors)
        
        if score >= 80 and risk_count == 0:
            return RiskLevel.LOW
        elif score >= 60 and risk_count <= 1:
            return RiskLevel.MODERATE
        elif score >= 40 or risk_count <= 2:
            return RiskLevel.HIGH
        else:
            return RiskLevel.VERY_HIGH
    
    def _generate_recommendation(
        self,
        score: int,
        level: ReadinessLevel,
        risks: List[str],
        opportunities: List[str],
        components: List[ReadinessComponent],
    ) -> Tuple[str, List[str]]:
        """Generate recommendation and action items."""
        
        if level == ReadinessLevel.HIGHLY_READY:
            recommendation = (
                "This market is highly ready for expansion. "
                "Strong signals support confident entry with standard playbook."
            )
            actions = [
                "Proceed with property sourcing",
                "Apply standard pricing strategy",
                "Monitor first 90 days closely",
            ]
        
        elif level == ReadinessLevel.READY:
            recommendation = (
                "This market is ready for expansion with monitoring. "
                "Some factors require attention but overall profile is positive."
            )
            actions = [
                "Proceed with property sourcing",
                "Address identified risk factors",
                "Set conservative initial pricing",
                "Review performance at 60-day mark",
            ]
        
        elif level == ReadinessLevel.CAUTIOUS:
            recommendation = (
                "Additional research recommended before expansion. "
                "Signal gaps or risk factors create uncertainty."
            )
            actions = [
                "Gather additional market data",
                f"Address: {risks[0]}" if risks else "Review weak components",
                "Consider pilot property before full expansion",
            ]
        
        elif level == ReadinessLevel.NOT_READY:
            recommendation = (
                "Market not ready for expansion. "
                "Significant gaps in data or operator-market fit."
            )
            weak = [c for c in components if c.status in ["weak", "critical"]]
            actions = [
                f"Improve: {weak[0].name}" if weak else "Address data gaps",
                "Reassess in 3-6 months",
                "Consider alternative markets",
            ]
        
        else:  # AVOID
            recommendation = (
                "Avoid this market. "
                "Critical gaps make reliable projections impossible."
            )
            actions = [
                "Do not proceed with expansion",
                "Focus on markets with better signal coverage",
            ]
        
        return recommendation, actions
    
    def _generate_executive_summary(
        self,
        market_name: str,
        score: int,
        level: ReadinessLevel,
        risks: List[str],
        opportunities: List[str],
    ) -> str:
        """Generate 1-paragraph executive summary."""
        
        level_text = {
            ReadinessLevel.HIGHLY_READY: "highly favorable",
            ReadinessLevel.READY: "favorable with caveats",
            ReadinessLevel.CAUTIOUS: "uncertain",
            ReadinessLevel.NOT_READY: "unfavorable",
            ReadinessLevel.AVOID: "strongly unfavorable",
        }
        
        summary = f"{market_name} scores {score}/100 for expansion readiness, indicating {level_text[level]} conditions. "
        
        if opportunities:
            summary += f"Key strengths include {opportunities[0].lower()}. "
        
        if risks:
            summary += f"Primary risk is {risks[0].lower()}. "
        
        if level in [ReadinessLevel.HIGHLY_READY, ReadinessLevel.READY]:
            summary += "Recommend proceeding with standard expansion protocol."
        elif level == ReadinessLevel.CAUTIOUS:
            summary += "Recommend gathering additional data before committing."
        else:
            summary += "Recommend focusing on alternative markets."
        
        return summary


# =============================================================================
# CONVENIENCE
# =============================================================================

_service: Optional[MarketReadinessService] = None


def get_readiness_service() -> MarketReadinessService:
    """Get market readiness service singleton."""
    global _service
    if _service is None:
        _service = MarketReadinessService()
    return _service


def assess_market_readiness(
    target_bundle: SignalBundle,
    market_name: str,
    operator_profile: Optional[Dict[str, Any]] = None,
    home_market_bundle: Optional[SignalBundle] = None,
) -> MarketReadinessScore:
    """
    Assess market readiness for expansion.
    
    Example:
        readiness = assess_market_readiness(
            destin_bundle,
            "Destin, FL",
            operator_profile={
                "amenities": ["pool", "waterfront"],
                "primary_platform": "airbnb",
                "typical_adr": 350,
            }
        )
        
        print(readiness.executive_summary)
        # "Destin, FL scores 82/100 for expansion readiness..."
        
        if readiness.is_expansion_candidate():
            proceed_with_sourcing()
    """
    return get_readiness_service().assess_market(
        target_bundle, market_name, operator_profile, home_market_bundle
    )
