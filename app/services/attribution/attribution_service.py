"""
Causal Attribution Models - Strategic Gap #2.

Competitors aggregate trends — we EXPLAIN them.

This module adds:
- Signal attribution reports (what signals moved ADR most)
- Driver analysis badges ("Pool + Waterfront drove +12%")
- What-if scenario analysis

Key differentiator: We don't just show numbers, we show WHY.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from app.services.signals.signal_contract import (
    SignalBundle,
    SignalType,
)
from app.services.signals import (
    get_seasonality,
    get_platform_bias,
    get_amenity_lift,
    get_operator_delta,
)


# =============================================================================
# ATTRIBUTION MODELS
# =============================================================================

class AttributionCategory(str, Enum):
    """Categories of attribution drivers."""
    SEASONALITY = "seasonality"
    AMENITY = "amenity"
    OPERATOR = "operator"
    PLATFORM = "platform"
    MARKET = "market"
    MOMENTUM = "momentum"


@dataclass
class AttributionDriver:
    """
    A single driver contributing to a metric.
    
    This is the core of "why did this happen" explanations.
    """
    category: AttributionCategory
    name: str
    
    # Impact
    contribution_pct: float  # e.g., 0.12 = contributed 12% of total change
    absolute_impact: float   # Dollar or percentage impact
    direction: str           # "positive" or "negative"
    
    # Confidence
    confidence: float
    
    # Human-readable
    badge_text: str          # e.g., "Pool +10%"
    explanation: str
    
    # Source signal
    signal_type: Optional[SignalType] = None
    signal_value: Optional[float] = None


@dataclass
class AttributionReport:
    """
    Complete attribution report for a metric change.
    
    Answers: "Why did ADR change from X to Y?"
    """
    # What we're explaining
    metric_name: str
    base_value: float
    current_value: float
    change_pct: float
    
    # Drivers (sorted by impact)
    drivers: List[AttributionDriver] = field(default_factory=list)
    
    # Top 3 badges for UI display
    badges: List[str] = field(default_factory=list)
    
    # Summary
    summary: str = ""
    
    # Unexplained variance (what we can't attribute)
    unexplained_pct: float = 0.0
    
    # Confidence
    overall_confidence: float = 0.0
    
    # Metadata
    computed_at: datetime = field(default_factory=datetime.utcnow)
    
    def get_top_drivers(self, n: int = 3) -> List[AttributionDriver]:
        """Get top N drivers by absolute impact."""
        return sorted(
            self.drivers,
            key=lambda d: abs(d.absolute_impact),
            reverse=True
        )[:n]


@dataclass
class ScenarioResult:
    """
    Result of a what-if scenario analysis.
    
    Answers: "What if we added a pool?"
    """
    scenario_name: str
    
    # Changes made
    changes: Dict[str, Any]
    
    # Impact
    base_metric: float
    projected_metric: float
    delta: float
    delta_pct: float
    
    # Breakdown
    impact_drivers: List[AttributionDriver] = field(default_factory=list)
    
    # Confidence
    confidence: float = 0.0
    
    # Caveats
    caveats: List[str] = field(default_factory=list)


# =============================================================================
# ATTRIBUTION SERVICE
# =============================================================================

class AttributionService:
    """
    Causal Attribution Service.
    
    This service explains WHY metrics are what they are.
    
    Capabilities:
    1. Attribution reports - decompose a metric into driver contributions
    2. Driver badges - concise impact statements for UI
    3. What-if scenarios - project impact of changes
    
    All attributions are signal-driven with confidence.
    """
    
    def __init__(self):
        self.version = "1.0.0"
    
    def explain_adr(
        self,
        signal_bundle: SignalBundle,
        base_adr: float,
        current_adr: float,
        property_amenities: List[str],
    ) -> AttributionReport:
        """
        Explain why ADR is what it is.
        
        Decomposes current ADR into contributions from:
        - Seasonality
        - Amenities
        - Operator performance
        - Platform dynamics
        - Market conditions
        """
        change = current_adr - base_adr
        change_pct = change / base_adr if base_adr > 0 else 0
        
        drivers = []
        total_attributed = 0.0
        
        # =================================================================
        # 1. Seasonality Attribution
        # =================================================================
        seasonality = get_seasonality(signal_bundle)
        season_impact = base_adr * (seasonality.multiplier - 1.0)
        
        if abs(season_impact) > 0.01:
            drivers.append(AttributionDriver(
                category=AttributionCategory.SEASONALITY,
                name="Seasonal Demand",
                contribution_pct=season_impact / change if change != 0 else 0,
                absolute_impact=season_impact,
                direction="positive" if season_impact > 0 else "negative",
                confidence=seasonality.confidence,
                badge_text=f"Season {'+' if season_impact > 0 else ''}{(seasonality.multiplier - 1) * 100:.0f}%",
                explanation=f"{'Peak' if seasonality.multiplier > 1 else 'Off'} season adjusts ADR by {(seasonality.multiplier - 1) * 100:.1f}%",
                signal_type=SignalType.SEASONALITY_CURVE,
                signal_value=seasonality.multiplier,
            ))
            total_attributed += season_impact
        
        # =================================================================
        # 2. Amenity Attribution
        # =================================================================
        amenity_lift = get_amenity_lift(signal_bundle, property_amenities)
        
        for amenity, detail in amenity_lift.lifts.items():
            if amenity in property_amenities:
                impact = base_adr * detail.lift_pct
                
                if abs(impact) > 0.01:
                    # Create readable name
                    readable_name = amenity.replace("_", " ").title()
                    
                    drivers.append(AttributionDriver(
                        category=AttributionCategory.AMENITY,
                        name=readable_name,
                        contribution_pct=impact / change if change != 0 else 0,
                        absolute_impact=impact,
                        direction="positive" if impact > 0 else "negative",
                        confidence=detail.confidence,
                        badge_text=f"{readable_name} +{detail.lift_pct * 100:.0f}%",
                        explanation=f"{readable_name} adds {detail.lift_pct * 100:.1f}% premium in this market",
                        signal_type=SignalType.AMENITY_LIFT,
                        signal_value=detail.lift_pct,
                    ))
                    total_attributed += impact
        
        # =================================================================
        # 3. Operator Attribution
        # =================================================================
        operator = get_operator_delta(signal_bundle)
        
        if operator.has_signal and operator.applied_adr_delta != 0:
            impact = base_adr * operator.applied_adr_delta
            
            drivers.append(AttributionDriver(
                category=AttributionCategory.OPERATOR,
                name="Operator Performance",
                contribution_pct=impact / change if change != 0 else 0,
                absolute_impact=impact,
                direction="positive" if impact > 0 else "negative",
                confidence=operator.confidence,
                badge_text=f"Operator {'+' if impact > 0 else ''}{operator.applied_adr_delta * 100:.0f}%",
                explanation=f"Historical operator performance {'above' if impact > 0 else 'below'} market average",
                signal_type=SignalType.OPERATOR_DELTA,
                signal_value=operator.applied_adr_delta,
            ))
            total_attributed += impact
        
        # =================================================================
        # 4. Platform Attribution
        # =================================================================
        platform = get_platform_bias(signal_bundle)
        
        # Platform mix affects pricing power
        if platform.is_vrbo_dominant():
            # VRBO-heavy markets tend to have higher rates
            platform_impact = base_adr * 0.03  # ~3% VRBO premium
            
            drivers.append(AttributionDriver(
                category=AttributionCategory.PLATFORM,
                name="Platform Mix",
                contribution_pct=platform_impact / change if change != 0 else 0,
                absolute_impact=platform_impact,
                direction="positive",
                confidence=platform.confidence,
                badge_text="VRBO Market +3%",
                explanation="VRBO-dominant market supports premium rates",
                signal_type=SignalType.PLATFORM_DOMINANCE,
                signal_value=platform.vrbo_share,
            ))
            total_attributed += platform_impact
        
        # =================================================================
        # 5. Calculate unexplained variance
        # =================================================================
        unexplained = change - total_attributed
        unexplained_pct = unexplained / change if change != 0 else 0
        
        # =================================================================
        # 6. Build badges (top 3)
        # =================================================================
        sorted_drivers = sorted(drivers, key=lambda d: abs(d.absolute_impact), reverse=True)
        badges = [d.badge_text for d in sorted_drivers[:3]]
        
        # =================================================================
        # 7. Build summary
        # =================================================================
        if sorted_drivers:
            top = sorted_drivers[0]
            summary = f"ADR primarily driven by {top.name.lower()} ({top.badge_text})"
            if len(sorted_drivers) > 1:
                summary += f", with additional impact from {sorted_drivers[1].name.lower()}"
        else:
            summary = "ADR reflects market baseline"
        
        # =================================================================
        # 8. Calculate confidence
        # =================================================================
        if drivers:
            conf = sum(d.confidence * abs(d.contribution_pct) for d in drivers)
            conf = min(1.0, conf)
        else:
            conf = 0.5
        
        return AttributionReport(
            metric_name="ADR",
            base_value=base_adr,
            current_value=current_adr,
            change_pct=change_pct,
            drivers=sorted_drivers,
            badges=badges,
            summary=summary,
            unexplained_pct=abs(unexplained_pct),
            overall_confidence=conf,
        )
    
    def what_if_amenity(
        self,
        signal_bundle: SignalBundle,
        current_adr: float,
        current_amenities: List[str],
        add_amenity: str,
    ) -> ScenarioResult:
        """
        What-if scenario: What if we added this amenity?
        
        Projects impact of adding an amenity based on signals.
        """
        # Get lift for the new amenity
        full_amenities = current_amenities + [add_amenity]
        new_lift = get_amenity_lift(signal_bundle, full_amenities)
        current_lift = get_amenity_lift(signal_bundle, current_amenities)
        
        # Calculate marginal impact
        delta_multiplier = new_lift.multiplier / current_lift.multiplier if current_lift.multiplier > 0 else new_lift.multiplier
        delta_pct = delta_multiplier - 1.0
        
        projected_adr = current_adr * delta_multiplier
        
        # Get the specific lift for this amenity
        amenity_detail = new_lift.lifts.get(add_amenity)
        
        drivers = []
        if amenity_detail:
            drivers.append(AttributionDriver(
                category=AttributionCategory.AMENITY,
                name=add_amenity.replace("_", " ").title(),
                contribution_pct=1.0,  # 100% of this scenario's impact
                absolute_impact=projected_adr - current_adr,
                direction="positive" if delta_pct > 0 else "negative",
                confidence=amenity_detail.confidence,
                badge_text=f"+{amenity_detail.lift_pct * 100:.0f}% ADR",
                explanation=f"Adding {add_amenity.replace('_', ' ')} projects {amenity_detail.lift_pct * 100:.1f}% ADR increase",
                signal_type=SignalType.AMENITY_LIFT,
                signal_value=amenity_detail.lift_pct,
            ))
        
        caveats = []
        if amenity_detail and amenity_detail.confidence < 0.6:
            caveats.append("Low signal confidence - projection may vary")
        if add_amenity == "pool":
            caveats.append("Pool impact varies significantly by season")
        
        return ScenarioResult(
            scenario_name=f"Add {add_amenity.replace('_', ' ').title()}",
            changes={"add_amenity": add_amenity},
            base_metric=current_adr,
            projected_metric=round(projected_adr, 2),
            delta=round(projected_adr - current_adr, 2),
            delta_pct=round(delta_pct, 4),
            impact_drivers=drivers,
            confidence=amenity_detail.confidence if amenity_detail else 0.3,
            caveats=caveats,
        )
    
    def what_if_season(
        self,
        signal_bundle: SignalBundle,
        current_adr: float,
        target_month: int,
    ) -> ScenarioResult:
        """
        What-if scenario: What will ADR be in a different month?
        
        Projects seasonal impact.
        """
        from datetime import date
        
        # Get seasonality for target month
        target_date = date(date.today().year, target_month, 15)
        seasonality = get_seasonality(signal_bundle, target_date)
        
        # Current month baseline (assume multiplier 1.0)
        current_seasonality = get_seasonality(signal_bundle)
        
        # Calculate relative change
        relative_mult = seasonality.multiplier / current_seasonality.multiplier if current_seasonality.multiplier > 0 else seasonality.multiplier
        
        projected_adr = current_adr * relative_mult
        
        month_name = [
            "", "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December"
        ][target_month]
        
        drivers = [
            AttributionDriver(
                category=AttributionCategory.SEASONALITY,
                name=f"{month_name} Seasonality",
                contribution_pct=1.0,
                absolute_impact=projected_adr - current_adr,
                direction="positive" if relative_mult > 1 else "negative",
                confidence=seasonality.confidence,
                badge_text=f"{month_name} {'+' if relative_mult > 1 else ''}{(relative_mult - 1) * 100:.0f}%",
                explanation=f"{month_name} demand is {relative_mult:.2f}x current period",
                signal_type=SignalType.SEASONALITY_CURVE,
                signal_value=seasonality.multiplier,
            )
        ]
        
        caveats = []
        if seasonality.confidence < 0.6:
            caveats.append("Seasonality signal confidence is moderate")
        if seasonality.is_peak_season(target_month):
            caveats.append("Peak season - actual rates may exceed projection")
        
        return ScenarioResult(
            scenario_name=f"ADR in {month_name}",
            changes={"target_month": target_month},
            base_metric=current_adr,
            projected_metric=round(projected_adr, 2),
            delta=round(projected_adr - current_adr, 2),
            delta_pct=round(relative_mult - 1, 4),
            impact_drivers=drivers,
            confidence=seasonality.confidence,
            caveats=caveats,
        )


# =============================================================================
# CONVENIENCE
# =============================================================================

_service: Optional[AttributionService] = None


def get_attribution_service() -> AttributionService:
    """Get attribution service singleton."""
    global _service
    if _service is None:
        _service = AttributionService()
    return _service


def explain_adr(
    signal_bundle: SignalBundle,
    base_adr: float,
    current_adr: float,
    property_amenities: List[str],
) -> AttributionReport:
    """
    Explain why ADR is what it is.
    
    Returns detailed attribution with driver badges.
    """
    return get_attribution_service().explain_adr(
        signal_bundle, base_adr, current_adr, property_amenities
    )


def what_if_add_amenity(
    signal_bundle: SignalBundle,
    current_adr: float,
    current_amenities: List[str],
    add_amenity: str,
) -> ScenarioResult:
    """What-if: Add an amenity."""
    return get_attribution_service().what_if_amenity(
        signal_bundle, current_adr, current_amenities, add_amenity
    )
