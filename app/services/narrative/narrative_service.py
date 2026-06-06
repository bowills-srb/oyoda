"""
Narrative Output Layer - Multi-Audience Summaries.

Same signals. Different audiences.

This module generates:
- Executive summary (1 paragraph)
- Investor summary (1 paragraph)
- Guest-facing explanation (1 paragraph)
- Sales/BD talking points

Makes your platform feel 10× more polished.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.services.signals import SignalBundle, get_seasonality, get_platform_bias
from app.services.health.signal_health import assess_signal_health, HealthGrade


# =============================================================================
# AUDIENCE TYPES
# =============================================================================

class Audience(str, Enum):
    """Target audiences for narratives."""
    EXECUTIVE = "executive"
    INVESTOR = "investor"
    OPERATOR = "operator"
    GUEST = "guest"
    SALES = "sales"
    TECHNICAL = "technical"


class NarrativeTone(str, Enum):
    """Tone for narrative generation."""
    CONFIDENT = "confident"
    CAUTIOUS = "cautious"
    NEUTRAL = "neutral"


# =============================================================================
# NARRATIVE MODELS
# =============================================================================

@dataclass
class NarrativeBlock:
    """
    A single narrative block.
    
    One paragraph, audience-specific.
    """
    audience: Audience
    headline: str
    body: str
    
    # Tone used
    tone: NarrativeTone
    
    # Key points (bullet-able)
    key_points: List[str] = field(default_factory=list)
    
    # Call to action (if applicable)
    cta: Optional[str] = None
    
    # Confidence in narrative
    confidence: float = 0.0


@dataclass
class NarrativePackage:
    """
    Complete narrative package for all audiences.
    
    One analysis, many presentations.
    """
    # Subject
    subject: str  # "30A-Beaches 4BR Analysis" etc.
    
    # Narratives by audience
    executive: NarrativeBlock = None
    investor: NarrativeBlock = None
    operator: NarrativeBlock = None
    guest: NarrativeBlock = None
    sales: NarrativeBlock = None
    
    # Common data
    key_metrics: Dict[str, Any] = field(default_factory=dict)
    
    # Signal health
    health_grade: HealthGrade = HealthGrade.C
    
    # Generated
    generated_at: datetime = field(default_factory=datetime.utcnow)


# =============================================================================
# NARRATIVE TEMPLATES
# =============================================================================

class NarrativeTemplates:
    """
    Narrative templates by audience and context.
    
    These are starting points - can be customized.
    """
    
    @staticmethod
    def executive_strong(metrics: Dict) -> NarrativeBlock:
        """Executive narrative when signals are strong."""
        return NarrativeBlock(
            audience=Audience.EXECUTIVE,
            headline=f"Strong Revenue Potential: ${metrics.get('revenue_expected', 0):,.0f}/year",
            body=(
                f"This {metrics.get('bedrooms', 'N/A')}BR property in {metrics.get('geo', 'the market')} "
                f"shows strong revenue fundamentals with projected gross revenue of "
                f"${metrics.get('revenue_expected', 0):,.0f} annually. "
                f"Market signals indicate {metrics.get('market_context', 'stable conditions')} "
                f"with {metrics.get('confidence', 0):.0%} confidence in our projections. "
                f"{metrics.get('key_driver', 'Seasonal demand patterns')} is the primary revenue driver."
            ),
            tone=NarrativeTone.CONFIDENT,
            key_points=[
                f"Projected revenue: ${metrics.get('revenue_low', 0):,.0f} - ${metrics.get('revenue_high', 0):,.0f}",
                f"Signal confidence: {metrics.get('confidence', 0):.0%}",
                f"Primary driver: {metrics.get('key_driver', 'Seasonality')}",
            ],
            cta="Review full analysis for investment decision",
            confidence=metrics.get('confidence', 0.5),
        )
    
    @staticmethod
    def executive_cautious(metrics: Dict) -> NarrativeBlock:
        """Executive narrative when signals are weak."""
        return NarrativeBlock(
            audience=Audience.EXECUTIVE,
            headline=f"Revenue Estimate: ${metrics.get('revenue_expected', 0):,.0f}/year (Preliminary)",
            body=(
                f"This {metrics.get('bedrooms', 'N/A')}BR property shows estimated revenue potential of "
                f"${metrics.get('revenue_expected', 0):,.0f} annually, though signal coverage is limited. "
                f"We recommend gathering additional market data before finalizing projections. "
                f"Current estimates carry wider uncertainty bands than typical."
            ),
            tone=NarrativeTone.CAUTIOUS,
            key_points=[
                f"Preliminary estimate: ${metrics.get('revenue_expected', 0):,.0f}",
                f"Signal coverage: {metrics.get('health_grade', 'Limited')}",
                "Additional data collection recommended",
            ],
            cta="Request enhanced market analysis",
            confidence=metrics.get('confidence', 0.3),
        )
    
    @staticmethod
    def investor_summary(metrics: Dict) -> NarrativeBlock:
        """Investor-focused narrative."""
        return NarrativeBlock(
            audience=Audience.INVESTOR,
            headline=f"{metrics.get('cap_rate', 0):.1%} Cap Rate | {metrics.get('coc', 0):.1%} Cash-on-Cash",
            body=(
                f"Investment analysis indicates a {metrics.get('cap_rate', 0):.1%} cap rate "
                f"with {metrics.get('coc', 0):.1%} cash-on-cash return at current market rates. "
                f"The {metrics.get('geo', 'market')} shows {metrics.get('market_strength', 'moderate')} fundamentals "
                f"with {metrics.get('seasonality_type', 'typical')} seasonality patterns. "
                f"Payback period estimated at {metrics.get('payback', 0):.1f} years "
                f"under base case assumptions."
            ),
            tone=NarrativeTone.NEUTRAL,
            key_points=[
                f"Cap rate: {metrics.get('cap_rate', 0):.1%}",
                f"Cash-on-cash: {metrics.get('coc', 0):.1%}",
                f"Payback: {metrics.get('payback', 0):.1f} years",
                f"Risk level: {metrics.get('risk_level', 'Moderate')}",
            ],
            cta="View detailed proforma",
            confidence=metrics.get('confidence', 0.5),
        )
    
    @staticmethod
    def operator_summary(metrics: Dict) -> NarrativeBlock:
        """Operator-focused narrative."""
        return NarrativeBlock(
            audience=Audience.OPERATOR,
            headline=f"Target ADR: ${metrics.get('adr', 0):.0f} | Occupancy: {metrics.get('occupancy', 0):.0%}",
            body=(
                f"Your {metrics.get('bedrooms', 'N/A')}BR should target ${metrics.get('adr', 0):.0f}/night ADR "
                f"with {metrics.get('occupancy', 0):.0%} expected occupancy. "
                f"{metrics.get('amenity_impact', 'Your amenities')} contribute "
                f"{metrics.get('amenity_lift', '+0%')} to rate positioning. "
                f"You're currently priced {metrics.get('position_vs_market', 'at market')}. "
                f"{metrics.get('seasonal_note', '')}"
            ),
            tone=NarrativeTone.CONFIDENT if metrics.get('confidence', 0) > 0.6 else NarrativeTone.NEUTRAL,
            key_points=[
                f"Target ADR: ${metrics.get('adr', 0):.0f}",
                f"Expected occupancy: {metrics.get('occupancy', 0):.0%}",
                f"Amenity lift: {metrics.get('amenity_lift', 'N/A')}",
                f"Position: {metrics.get('percentile', 50):.0f}th percentile",
            ],
            cta="View pricing recommendations",
            confidence=metrics.get('confidence', 0.5),
        )
    
    @staticmethod
    def guest_explanation(metrics: Dict) -> NarrativeBlock:
        """Guest-facing explanation (for concierge)."""
        return NarrativeBlock(
            audience=Audience.GUEST,
            headline=f"Your Stay in {metrics.get('geo', 'the Area')}",
            body=(
                f"You've chosen a wonderful time to visit! "
                f"{metrics.get('season_description', 'This period offers')} "
                f"{'great weather and plenty of activities' if metrics.get('is_peak') else 'a more relaxed atmosphere'}. "
                f"Your {metrics.get('bedrooms', '')}BR home features {metrics.get('amenity_highlights', 'great amenities')} "
                f"{'perfect for your family' if metrics.get('is_family') else ''}. "
                f"Let me know if you'd like recommendations for {metrics.get('activity_type', 'local activities')}!"
            ),
            tone=NarrativeTone.CONFIDENT,
            key_points=[],  # No bullet points for guests
            cta=None,
            confidence=0.9,  # Guest narratives don't need signal confidence
        )
    
    @staticmethod
    def sales_talking_points(metrics: Dict) -> NarrativeBlock:
        """Sales/BD talking points."""
        return NarrativeBlock(
            audience=Audience.SALES,
            headline="Key Selling Points",
            body=(
                f"Lead with the {metrics.get('cap_rate', 0):.1%} cap rate and "
                f"{metrics.get('confidence', 0):.0%} signal confidence - our competitors can't match this. "
                f"The {metrics.get('geo', 'market')} has {metrics.get('platform_mix', 'balanced platform distribution')} "
                f"which means diversified booking channels. "
                f"Highlight the {metrics.get('key_driver', 'strong seasonality')} as the primary value driver."
            ),
            tone=NarrativeTone.CONFIDENT,
            key_points=[
                f"Cap rate: {metrics.get('cap_rate', 0):.1%} (top quartile)",
                f"Signal confidence: {metrics.get('confidence', 0):.0%} (our differentiator)",
                f"Key driver: {metrics.get('key_driver', 'Seasonality')}",
                "Emphasize explainability - we can show WHY",
            ],
            cta="Close with: 'Let me show you exactly how we calculated this'",
            confidence=metrics.get('confidence', 0.5),
        )


# =============================================================================
# NARRATIVE SERVICE
# =============================================================================

class NarrativeService:
    """
    Narrative Generation Service.
    
    Transforms signals into audience-appropriate narratives.
    """
    
    def __init__(self):
        self.version = "1.0.0"
    
    def generate_package(
        self,
        signal_bundle: SignalBundle,
        metrics: Dict[str, Any],
        geo_name: str,
        bedrooms: int,
    ) -> NarrativePackage:
        """
        Generate complete narrative package.
        
        Args:
            signal_bundle: Source signals
            metrics: Pre-computed metrics (ADR, revenue, etc.)
            geo_name: Human-readable geo name
            bedrooms: Property bedroom count
        
        Returns:
            NarrativePackage with all audience narratives
        """
        # Assess health
        health = assess_signal_health(signal_bundle, use_case="full")
        
        # Get seasonality context
        seasonality = get_seasonality(signal_bundle)
        
        # Get platform context
        platform = get_platform_bias(signal_bundle)
        
        # Enrich metrics with context
        enriched = {
            **metrics,
            "geo": geo_name,
            "bedrooms": bedrooms,
            "health_grade": health.grade.value,
            "confidence": health.overall_score,
            "market_context": self._describe_market(seasonality, platform),
            "key_driver": self._identify_key_driver(signal_bundle),
            "seasonality_type": self._describe_seasonality(seasonality),
            "platform_mix": self._describe_platform(platform),
            "is_peak": seasonality.multiplier > 1.2 if seasonality else False,
            "season_description": self._season_description(seasonality),
        }
        
        # Generate narratives
        if health.grade in [HealthGrade.A, HealthGrade.B]:
            executive = NarrativeTemplates.executive_strong(enriched)
        else:
            executive = NarrativeTemplates.executive_cautious(enriched)
        
        return NarrativePackage(
            subject=f"{geo_name} {bedrooms}BR Analysis",
            executive=executive,
            investor=NarrativeTemplates.investor_summary(enriched),
            operator=NarrativeTemplates.operator_summary(enriched),
            guest=NarrativeTemplates.guest_explanation(enriched),
            sales=NarrativeTemplates.sales_talking_points(enriched),
            key_metrics=enriched,
            health_grade=health.grade,
        )
    
    def generate_for_audience(
        self,
        signal_bundle: SignalBundle,
        metrics: Dict[str, Any],
        audience: Audience,
        geo_name: str = "",
        bedrooms: int = 3,
    ) -> NarrativeBlock:
        """Generate narrative for specific audience."""
        package = self.generate_package(signal_bundle, metrics, geo_name, bedrooms)
        
        audience_map = {
            Audience.EXECUTIVE: package.executive,
            Audience.INVESTOR: package.investor,
            Audience.OPERATOR: package.operator,
            Audience.GUEST: package.guest,
            Audience.SALES: package.sales,
        }
        
        return audience_map.get(audience, package.executive)
    
    def _describe_market(self, seasonality, platform) -> str:
        """Generate market description."""
        parts = []
        
        if seasonality.multiplier > 1.2:
            parts.append("strong seasonal demand")
        elif seasonality.multiplier < 0.8:
            parts.append("off-peak conditions")
        else:
            parts.append("stable demand")
        
        if platform.is_airbnb_dominant():
            parts.append("Airbnb-dominant distribution")
        elif platform.is_balanced():
            parts.append("balanced platform mix")
        
        return " with ".join(parts) if parts else "typical conditions"
    
    def _identify_key_driver(self, signal_bundle: SignalBundle) -> str:
        """Identify the key revenue driver."""
        seasonality = get_seasonality(signal_bundle)
        
        if seasonality.multiplier > 1.3:
            return "Strong seasonal demand"
        elif seasonality.multiplier < 0.7:
            return "Off-season opportunity"
        else:
            return "Year-round rental appeal"
    
    def _describe_seasonality(self, seasonality) -> str:
        """Describe seasonality pattern."""
        if seasonality.strength and seasonality.strength > 2.0:
            return "highly seasonal"
        elif seasonality.strength and seasonality.strength > 1.5:
            return "moderately seasonal"
        else:
            return "relatively stable year-round"
    
    def _describe_platform(self, platform) -> str:
        """Describe platform distribution."""
        if platform.is_airbnb_dominant():
            return f"Airbnb-dominant ({platform.airbnb_share:.0%})"
        elif platform.is_vrbo_dominant():
            return f"VRBO-dominant ({platform.vrbo_share:.0%})"
        else:
            return "balanced platform distribution"
    
    def _season_description(self, seasonality) -> str:
        """Generate season description for guests."""
        if seasonality.multiplier > 1.3:
            return "This is peak season - expect perfect weather and vibrant activity."
        elif seasonality.multiplier > 1.1:
            return "You're visiting during a popular time."
        elif seasonality.multiplier < 0.8:
            return "The shoulder season offers a more relaxed pace."
        else:
            return "This is a lovely time to visit."


# =============================================================================
# SINGLETON & CONVENIENCE
# =============================================================================

_service: Optional[NarrativeService] = None


def get_narrative_service() -> NarrativeService:
    """Get narrative service singleton."""
    global _service
    if _service is None:
        _service = NarrativeService()
    return _service


def generate_narratives(
    signal_bundle: SignalBundle,
    metrics: Dict[str, Any],
    geo_name: str,
    bedrooms: int,
) -> NarrativePackage:
    """
    Generate narrative package.
    
    Example:
        narratives = generate_narratives(
            bundle,
            {"adr": 325, "revenue_expected": 85000, "cap_rate": 0.078},
            "30A Beaches",
            4
        )
        
        print(narratives.executive.headline)
        # "Strong Revenue Potential: $85,000/year"
        
        print(narratives.investor.body)
        # "Investment analysis indicates a 7.8% cap rate..."
    """
    return get_narrative_service().generate_package(
        signal_bundle, metrics, geo_name, bedrooms
    )


def generate_for_audience(
    signal_bundle: SignalBundle,
    metrics: Dict[str, Any],
    audience: Audience,
    **kwargs,
) -> NarrativeBlock:
    """Generate narrative for specific audience."""
    return get_narrative_service().generate_for_audience(
        signal_bundle, metrics, audience, **kwargs
    )
