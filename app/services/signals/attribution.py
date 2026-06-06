"""
Signal Attribution for PDF Reports

Generates citation-ready attribution text for use in:
- Pro forma footnotes
- Investment synopsis reports
- BD pitch decks
- Regulatory disclosures

Every projection in our PDFs is traceable to specific signals
with source, date, confidence, and methodology.

Usage:
    generator = AttributionGenerator()
    
    # Get footnotes for a bundle
    footnotes = generator.generate_footnotes(signal_bundle)
    
    # Get methodology section
    methodology = generator.generate_methodology_section(signal_bundle)
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from enum import Enum


# =============================================================================
# SOURCE METADATA
# =============================================================================

class SourceReliability(str, Enum):
    """Reliability rating for data sources."""
    OFFICIAL = "official"      # Government, regulatory
    HIGH = "high"              # Established data providers
    MEDIUM = "medium"          # Public scraping, derived
    LOW = "low"                # Single source, unverified


# Source metadata for attribution
SOURCE_METADATA = {
    # Official sources
    "census_acs": {
        "name": "U.S. Census Bureau American Community Survey",
        "short_name": "Census ACS",
        "reliability": SourceReliability.OFFICIAL,
        "url": "https://data.census.gov",
        "update_frequency": "Annual",
        "methodology": "5-year estimates from household surveys",
    },
    "bts_dot": {
        "name": "Bureau of Transportation Statistics",
        "short_name": "BTS/DOT",
        "reliability": SourceReliability.OFFICIAL,
        "url": "https://www.bts.gov",
        "update_frequency": "Quarterly",
        "methodology": "Airport traffic reports from T-100 data",
    },
    "noaa_nws": {
        "name": "NOAA National Weather Service",
        "short_name": "NOAA",
        "reliability": SourceReliability.OFFICIAL,
        "url": "https://www.weather.gov",
        "update_frequency": "Continuous",
        "methodology": "Climate normals from 30-year observations",
    },
    "county_assessor": {
        "name": "County Tax Assessor",
        "short_name": "County Records",
        "reliability": SourceReliability.OFFICIAL,
        "update_frequency": "Annual",
        "methodology": "Property tax assessment records",
    },
    
    # High reliability
    "airbnb_public": {
        "name": "Airbnb Public Listings",
        "short_name": "Airbnb",
        "reliability": SourceReliability.HIGH,
        "url": "https://www.airbnb.com",
        "update_frequency": "Daily scraping",
        "methodology": "Public search results and listing pages",
    },
    "vrbo_public": {
        "name": "VRBO Public Listings",
        "short_name": "VRBO",
        "reliability": SourceReliability.HIGH,
        "url": "https://www.vrbo.com",
        "update_frequency": "Daily scraping",
        "methodology": "Public search results and listing pages",
    },
    
    # Medium reliability
    "derived": {
        "name": "Derived Analysis",
        "short_name": "Analysis",
        "reliability": SourceReliability.MEDIUM,
        "methodology": "Calculated from multiple primary sources",
    },
    "inferred": {
        "name": "Statistical Inference",
        "short_name": "Inferred",
        "reliability": SourceReliability.MEDIUM,
        "methodology": "Inferred from related signals",
    },
    "aggregated": {
        "name": "Multi-Source Aggregation",
        "short_name": "Aggregated",
        "reliability": SourceReliability.MEDIUM,
        "methodology": "Weighted aggregation of multiple sources",
    },
    
    # Operator data
    "operator_pms": {
        "name": "Operator Property Management System",
        "short_name": "Operator Data",
        "reliability": SourceReliability.HIGH,
        "methodology": "Direct integration with operator PMS",
        "disclosure": "Operator-provided data, not independently verified",
    },
}

# Signal type to human-readable description
SIGNAL_DESCRIPTIONS = {
    "supply_density": "Market supply and listing inventory",
    "bedroom_distribution": "Property size distribution",
    "calendar_compression": "Booking demand from calendar availability",
    "lead_time": "Booking lead time patterns",
    "rate_acceleration": "Rate trend momentum",
    "platform_dominance": "Platform market share (Airbnb vs VRBO)",
    "amenity_prevalence": "Amenity availability in market",
    "amenity_lift": "ADR impact of specific amenities",
    "rate_position": "Market rate distribution",
    "rate_by_bedroom": "Rates by bedroom count",
    "seasonality_curve": "Seasonal demand patterns",
    "housing_stock": "Local housing inventory and values",
    "travel_flow": "Regional travel demand",
    "event_impact": "Local event demand impact",
    "regulatory_risk": "STR regulatory environment",
    "operator_delta": "Operator performance adjustment",
}


# =============================================================================
# DATA MODELS
# =============================================================================

@dataclass
class Attribution:
    """Attribution for a single signal."""
    signal_type: str
    signal_description: str
    source: str
    source_name: str
    source_short: str
    reliability: SourceReliability
    observed_at: datetime
    confidence: float
    confidence_level: str
    sample_size: Optional[int] = None
    methodology: Optional[str] = None
    
    # Generated text
    footnote_text: str = ""
    citation_text: str = ""
    disclosure_text: Optional[str] = None


@dataclass
class AttributionBundle:
    """Complete attribution for a report."""
    geo_id: str
    market_name: str
    generated_at: datetime
    
    # Individual attributions
    attributions: List[Attribution] = field(default_factory=list)
    
    # Aggregated sections
    footnotes: List[str] = field(default_factory=list)
    citations: List[str] = field(default_factory=list)
    methodology_text: str = ""
    disclosure_text: str = ""
    
    # Summary
    source_count: int = 0
    official_source_count: int = 0
    avg_confidence: float = 0.0


# =============================================================================
# ATTRIBUTION GENERATOR
# =============================================================================

class AttributionGenerator:
    """
    Generates attribution text for signals.
    
    Produces:
    - Footnotes for pro forma PDFs
    - Citation section for reports
    - Methodology disclosure
    - Regulatory disclosure text
    """
    
    def __init__(self):
        self.source_metadata = SOURCE_METADATA
        self.signal_descriptions = SIGNAL_DESCRIPTIONS
    
    def generate_attribution(self, signal: Dict) -> Attribution:
        """Generate attribution for a single signal."""
        signal_type = signal.get("signal_type", "unknown")
        source = signal.get("source", "unknown")
        
        # Get metadata
        source_meta = self.source_metadata.get(source, {})
        signal_desc = self.signal_descriptions.get(signal_type, signal_type)
        
        # Parse observed_at
        observed = signal.get("observed_at")
        if isinstance(observed, str):
            observed = datetime.fromisoformat(observed.replace('Z', '+00:00'))
        observed = observed or datetime.utcnow()
        
        # Extract sample size from metadata
        metadata = signal.get("metadata", {})
        sample_size = (
            metadata.get("sample_size") or 
            metadata.get("total_listings") or
            metadata.get("total")
        )
        
        # Build attribution
        attr = Attribution(
            signal_type=signal_type,
            signal_description=signal_desc,
            source=source,
            source_name=source_meta.get("name", source),
            source_short=source_meta.get("short_name", source),
            reliability=source_meta.get("reliability", SourceReliability.MEDIUM),
            observed_at=observed,
            confidence=signal.get("confidence", 0),
            confidence_level=signal.get("confidence_level", "medium"),
            sample_size=sample_size,
            methodology=source_meta.get("methodology"),
        )
        
        # Generate text
        attr.footnote_text = self._generate_footnote(attr)
        attr.citation_text = self._generate_citation(attr)
        
        if source_meta.get("disclosure"):
            attr.disclosure_text = source_meta["disclosure"]
        
        return attr
    
    def generate_bundle(
        self,
        signals: List[Dict],
        geo_id: str,
        market_name: Optional[str] = None,
    ) -> AttributionBundle:
        """Generate complete attribution bundle for a set of signals."""
        market_name = market_name or geo_id.replace("_", " ").title()
        
        bundle = AttributionBundle(
            geo_id=geo_id,
            market_name=market_name,
            generated_at=datetime.utcnow(),
        )
        
        # Generate individual attributions
        sources_seen = set()
        confidences = []
        
        for i, signal in enumerate(signals):
            attr = self.generate_attribution(signal)
            attr.footnote_text = f"[{i+1}] {attr.footnote_text}"
            bundle.attributions.append(attr)
            bundle.footnotes.append(attr.footnote_text)
            bundle.citations.append(attr.citation_text)
            
            sources_seen.add(attr.source)
            confidences.append(attr.confidence)
            
            if attr.reliability == SourceReliability.OFFICIAL:
                bundle.official_source_count += 1
        
        bundle.source_count = len(sources_seen)
        bundle.avg_confidence = sum(confidences) / len(confidences) if confidences else 0
        
        # Generate methodology section
        bundle.methodology_text = self._generate_methodology(bundle)
        
        # Generate disclosure
        bundle.disclosure_text = self._generate_disclosure(bundle)
        
        return bundle
    
    def _generate_footnote(self, attr: Attribution) -> str:
        """Generate footnote text for a signal."""
        parts = [attr.signal_description]
        
        # Source
        parts.append(f"from {attr.source_short}")
        
        # Date
        date_str = attr.observed_at.strftime("%b %d, %Y")
        parts.append(f"({date_str})")
        
        # Sample size
        if attr.sample_size:
            parts.append(f"n={attr.sample_size:,}")
        
        # Confidence
        conf_pct = f"{attr.confidence:.0%}"
        parts.append(f"Confidence: {conf_pct}")
        
        return ". ".join(parts) + "."
    
    def _generate_citation(self, attr: Attribution) -> str:
        """Generate academic-style citation."""
        year = attr.observed_at.strftime("%Y")
        date = attr.observed_at.strftime("%Y-%m-%d")
        
        citation = f"{attr.source_name} ({year}). {attr.signal_description}"
        
        if attr.methodology:
            citation += f". {attr.methodology}"
        
        citation += f". Retrieved {date}."
        
        if attr.sample_size:
            citation += f" n={attr.sample_size:,}."
        
        return citation
    
    def _generate_methodology(self, bundle: AttributionBundle) -> str:
        """Generate methodology section for reports."""
        lines = [
            "## Data Sources and Methodology",
            "",
            f"This analysis incorporates data from {bundle.source_count} distinct sources "
            f"with an average confidence level of {bundle.avg_confidence:.0%}.",
            "",
        ]
        
        # Group by reliability
        official = [a for a in bundle.attributions if a.reliability == SourceReliability.OFFICIAL]
        high = [a for a in bundle.attributions if a.reliability == SourceReliability.HIGH]
        medium = [a for a in bundle.attributions if a.reliability == SourceReliability.MEDIUM]
        
        if official:
            lines.append("### Official Government Sources")
            for attr in official:
                lines.append(f"- **{attr.source_short}**: {attr.methodology or 'Official records'}")
            lines.append("")
        
        if high:
            lines.append("### Primary Market Data")
            for attr in high:
                lines.append(f"- **{attr.source_short}**: {attr.methodology or 'Direct observation'}")
            lines.append("")
        
        if medium:
            lines.append("### Derived Analysis")
            for attr in medium:
                lines.append(f"- **{attr.source_short}**: {attr.methodology or 'Statistical analysis'}")
            lines.append("")
        
        lines.extend([
            "### Confidence Methodology",
            "",
            "Confidence scores reflect:",
            "- Sample size relative to market",
            "- Data recency (time decay applied)",
            "- Source reliability rating",
            "- Cross-validation with other signals",
        ])
        
        return "\n".join(lines)
    
    def _generate_disclosure(self, bundle: AttributionBundle) -> str:
        """Generate disclosure text for regulatory compliance."""
        lines = [
            "## Important Disclosures",
            "",
            "**Data Sources**: This analysis is based on publicly available data from "
            "vacation rental platforms, government sources, and derived analysis. "
            "No proprietary or confidential data was used.",
            "",
            "**Projections**: All projections are estimates based on historical data "
            "and market signals. Actual results may vary materially from projections.",
            "",
            f"**Confidence**: Average signal confidence is {bundle.avg_confidence:.0%}. "
            "Projections include confidence bands reflecting data uncertainty.",
            "",
            "**Not Investment Advice**: This analysis is for informational purposes only "
            "and does not constitute investment, legal, or tax advice.",
        ]
        
        # Add any specific disclosures
        disclosures = [a.disclosure_text for a in bundle.attributions if a.disclosure_text]
        if disclosures:
            lines.extend([
                "",
                "**Additional Disclosures**:",
            ])
            for d in set(disclosures):
                lines.append(f"- {d}")
        
        return "\n".join(lines)
    
    def generate_footnotes_for_pdf(
        self,
        signals: List[Dict],
        format: str = "compact",
    ) -> List[str]:
        """
        Generate footnotes formatted for PDF rendering.
        
        Args:
            signals: List of signal dicts
            format: 'compact' for single line, 'full' for detailed
            
        Returns:
            List of footnote strings
        """
        footnotes = []
        
        for i, signal in enumerate(signals):
            attr = self.generate_attribution(signal)
            
            if format == "compact":
                # Single line format for PDF margins
                text = (
                    f"[{i+1}] {attr.source_short}, "
                    f"{attr.observed_at.strftime('%b %Y')}, "
                    f"{attr.confidence:.0%} conf."
                )
            else:
                # Full format
                text = f"[{i+1}] {attr.footnote_text}"
            
            footnotes.append(text)
        
        return footnotes
    
    def generate_attribution_badge(self, signal: Dict) -> Dict[str, Any]:
        """
        Generate attribution badge data for UI/PDF.
        
        Returns dict with badge styling information.
        """
        attr = self.generate_attribution(signal)
        
        # Determine badge color by reliability
        colors = {
            SourceReliability.OFFICIAL: "#27ae60",  # Green
            SourceReliability.HIGH: "#3498db",      # Blue
            SourceReliability.MEDIUM: "#f39c12",    # Orange
            SourceReliability.LOW: "#e74c3c",       # Red
        }
        
        return {
            "source": attr.source_short,
            "date": attr.observed_at.strftime("%b %Y"),
            "confidence": f"{attr.confidence:.0%}",
            "reliability": attr.reliability.value,
            "color": colors.get(attr.reliability, "#95a5a6"),
            "tooltip": attr.footnote_text,
        }


# =============================================================================
# PRO FORMA INTEGRATION
# =============================================================================

class ProFormaAttributionMixin:
    """
    Mixin for adding attribution to pro forma PDFs.
    
    Add this to your PDF generator class to get automatic attribution.
    """
    
    def __init__(self):
        self.attribution_generator = AttributionGenerator()
        self._attribution_bundle: Optional[AttributionBundle] = None
    
    def set_signal_bundle(self, signals: List[Dict], geo_id: str, market_name: str):
        """Set signals for attribution generation."""
        self._attribution_bundle = self.attribution_generator.generate_bundle(
            signals, geo_id, market_name
        )
    
    def get_footnotes(self) -> List[str]:
        """Get footnotes for the current bundle."""
        if not self._attribution_bundle:
            return []
        return self._attribution_bundle.footnotes
    
    def get_footnote_for_signal(self, signal_type: str) -> Optional[str]:
        """Get footnote for a specific signal type."""
        if not self._attribution_bundle:
            return None
        
        for attr in self._attribution_bundle.attributions:
            if attr.signal_type == signal_type:
                return attr.footnote_text
        return None
    
    def get_methodology_section(self) -> str:
        """Get methodology section text."""
        if not self._attribution_bundle:
            return ""
        return self._attribution_bundle.methodology_text
    
    def get_disclosure_section(self) -> str:
        """Get disclosure section text."""
        if not self._attribution_bundle:
            return ""
        return self._attribution_bundle.disclosure_text
    
    def render_attribution_footer(self) -> Dict[str, Any]:
        """Get attribution data for PDF footer."""
        if not self._attribution_bundle:
            return {}
        
        return {
            "source_count": self._attribution_bundle.source_count,
            "official_sources": self._attribution_bundle.official_source_count,
            "avg_confidence": f"{self._attribution_bundle.avg_confidence:.0%}",
            "generated_at": self._attribution_bundle.generated_at.strftime("%Y-%m-%d %H:%M UTC"),
            "text": (
                f"Based on {self._attribution_bundle.source_count} data sources "
                f"({self._attribution_bundle.official_source_count} official). "
                f"Avg confidence: {self._attribution_bundle.avg_confidence:.0%}. "
                f"See appendix for full methodology."
            ),
        }


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def generate_signal_footnotes(
    signals: List[Dict],
    format: str = "compact",
) -> List[str]:
    """Generate footnotes for signals (convenience function)."""
    generator = AttributionGenerator()
    return generator.generate_footnotes_for_pdf(signals, format)


def generate_attribution_bundle(
    signals: List[Dict],
    geo_id: str,
    market_name: Optional[str] = None,
) -> AttributionBundle:
    """Generate full attribution bundle (convenience function)."""
    generator = AttributionGenerator()
    return generator.generate_bundle(signals, geo_id, market_name)
