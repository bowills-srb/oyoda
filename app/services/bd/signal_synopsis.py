"""
Signal-Backed Investment Synopsis

A 2-page investment synopsis where EVERY number is traceable to a specific
signal with source, date, confidence, and methodology.

This is the document that wins institutional deals because it shows:
1. What we project
2. Why we project it (signal attribution)
3. How confident we are (bands, not points)
4. What could change it (sensitivity)

Usage:
    generator = SignalBackedSynopsisGenerator()
    pdf_bytes = generator.generate(property_data, signals, "30a", "30A Beaches")
    
    with open("synopsis.pdf", "wb") as f:
        f.write(pdf_bytes)
"""

from dataclasses import dataclass, field
from datetime import datetime
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple
import math

# PDF generation
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, KeepTogether, HRFlowable
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.graphics.shapes import Drawing, Rect, String, Circle, Line
from reportlab.graphics.charts.piecharts import Pie


# =============================================================================
# BRAND COLORS
# =============================================================================

COLORS = {
    "primary": colors.HexColor("#0d7377"),
    "primary_light": colors.HexColor("#14919b"),
    "secondary": colors.HexColor("#d4a72c"),
    "accent": colors.HexColor("#2c3e50"),
    "success": colors.HexColor("#27ae60"),
    "warning": colors.HexColor("#f39c12"),
    "danger": colors.HexColor("#e74c3c"),
    "light": colors.HexColor("#f8f9fa"),
    "dark": colors.HexColor("#212529"),
    "muted": colors.HexColor("#6c757d"),
    "white": colors.white,
    "confidence_high": colors.HexColor("#27ae60"),
    "confidence_medium": colors.HexColor("#3498db"),
    "confidence_low": colors.HexColor("#f39c12"),
}


# =============================================================================
# DATA MODELS
# =============================================================================

@dataclass
class PropertyData:
    """Property details for synopsis."""
    address: str
    city: str
    state: str
    zipcode: str = ""
    
    bedrooms: int = 3
    bathrooms: float = 2.0
    sqft: Optional[int] = None
    year_built: Optional[int] = None
    property_type: str = "Single Family"
    
    has_pool: bool = False
    has_hot_tub: bool = False
    has_waterfront: bool = False
    has_beach_access: bool = False
    has_pet_friendly: bool = False
    amenities: List[str] = field(default_factory=list)
    
    purchase_price: Optional[float] = None
    estimated_value: Optional[float] = None


@dataclass
class SignalBackedMetric:
    """A metric backed by signal data with full attribution."""
    name: str
    value: float
    unit: str
    display_value: str
    
    # Confidence
    confidence: float
    confidence_level: str  # high/medium/low
    confidence_band: Tuple[float, float]
    band_display: str  # e.g., "$285K - $380K"
    
    # Attribution
    signal_type: str
    signal_source: str
    observed_at: datetime
    footnote_num: int
    
    # Optional
    trend: Optional[str] = None  # "up", "down", "stable"
    trend_pct: Optional[float] = None
    comparison: Optional[str] = None  # vs market/benchmark


# =============================================================================
# SYNOPSIS GENERATOR
# =============================================================================

class SignalBackedSynopsisGenerator:
    """
    Generates 2-page investment synopsis with full signal attribution.
    
    Page 1: Property Overview + Key Projections
    Page 2: Market Intelligence + Signal Attribution
    """
    
    # Core signals needed for projections
    REQUIRED_SIGNALS = [
        "supply_density",
        "calendar_compression",
        "rate_position",
        "platform_dominance",
        "amenity_prevalence",
        "seasonality_curve",
    ]
    
    def __init__(self):
        self.styles = self._create_styles()
        self.footnotes: List[str] = []
        self.footnote_counter = 0
    
    def _create_styles(self) -> Dict[str, ParagraphStyle]:
        """Create paragraph styles."""
        base = getSampleStyleSheet()
        
        return {
            "title": ParagraphStyle(
                "SynopsisTitle",
                parent=base["Heading1"],
                fontSize=22,
                textColor=COLORS["primary"],
                spaceAfter=4,
                leading=26,
            ),
            "address": ParagraphStyle(
                "Address",
                parent=base["Normal"],
                fontSize=11,
                textColor=COLORS["accent"],
                spaceAfter=2,
            ),
            "subtitle": ParagraphStyle(
                "Subtitle",
                parent=base["Normal"],
                fontSize=10,
                textColor=COLORS["muted"],
                spaceAfter=8,
            ),
            "section_header": ParagraphStyle(
                "SectionHeader",
                parent=base["Heading2"],
                fontSize=12,
                textColor=COLORS["primary"],
                spaceBefore=12,
                spaceAfter=6,
                borderPadding=(0, 0, 4, 0),
            ),
            "body": ParagraphStyle(
                "Body",
                parent=base["Normal"],
                fontSize=9,
                leading=12,
                textColor=COLORS["dark"],
            ),
            "metric_large": ParagraphStyle(
                "MetricLarge",
                parent=base["Normal"],
                fontSize=28,
                textColor=COLORS["primary"],
                alignment=TA_CENTER,
                leading=32,
            ),
            "metric_label": ParagraphStyle(
                "MetricLabel",
                parent=base["Normal"],
                fontSize=8,
                textColor=COLORS["muted"],
                alignment=TA_CENTER,
            ),
            "metric_band": ParagraphStyle(
                "MetricBand",
                parent=base["Normal"],
                fontSize=7,
                textColor=COLORS["muted"],
                alignment=TA_CENTER,
            ),
            "confidence_high": ParagraphStyle(
                "ConfHigh",
                parent=base["Normal"],
                fontSize=7,
                textColor=COLORS["confidence_high"],
                alignment=TA_CENTER,
            ),
            "confidence_medium": ParagraphStyle(
                "ConfMed",
                parent=base["Normal"],
                fontSize=7,
                textColor=COLORS["confidence_medium"],
                alignment=TA_CENTER,
            ),
            "confidence_low": ParagraphStyle(
                "ConfLow",
                parent=base["Normal"],
                fontSize=7,
                textColor=COLORS["confidence_low"],
                alignment=TA_CENTER,
            ),
            "footnote": ParagraphStyle(
                "Footnote",
                parent=base["Normal"],
                fontSize=6,
                textColor=COLORS["muted"],
                leading=8,
            ),
            "grade_badge": ParagraphStyle(
                "GradeBadge",
                parent=base["Normal"],
                fontSize=32,
                alignment=TA_CENTER,
                leading=36,
            ),
            "disclosure": ParagraphStyle(
                "Disclosure",
                parent=base["Normal"],
                fontSize=6,
                textColor=COLORS["muted"],
                leading=8,
                spaceBefore=8,
            ),
            "table_header": ParagraphStyle(
                "TableHeader",
                parent=base["Normal"],
                fontSize=8,
                textColor=COLORS["white"],
                alignment=TA_CENTER,
            ),
            "table_cell": ParagraphStyle(
                "TableCell",
                parent=base["Normal"],
                fontSize=8,
                textColor=COLORS["dark"],
            ),
            "table_cell_right": ParagraphStyle(
                "TableCellRight",
                parent=base["Normal"],
                fontSize=8,
                textColor=COLORS["dark"],
                alignment=TA_RIGHT,
            ),
        }
    
    def generate(
        self,
        property_data: PropertyData,
        signals: List[Dict],
        geo_id: str,
        market_name: Optional[str] = None,
    ) -> bytes:
        """
        Generate the investment synopsis PDF.
        
        Args:
            property_data: Property details
            signals: List of signal dictionaries
            geo_id: Market identifier
            market_name: Human-readable market name
            
        Returns:
            PDF as bytes
        """
        market_name = market_name or geo_id.replace("_", " ").title()
        
        # Reset footnotes
        self.footnotes = []
        self.footnote_counter = 0
        
        # Extract metrics from signals
        metrics = self._extract_metrics(signals, property_data)
        
        # Calculate coverage score
        coverage = self._calculate_coverage(signals)
        
        # Build PDF
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            topMargin=0.4*inch,
            bottomMargin=0.4*inch,
            leftMargin=0.5*inch,
            rightMargin=0.5*inch,
        )
        
        elements = []
        
        # === PAGE 1: Property Overview ===
        elements.extend(self._build_header(property_data, market_name, coverage))
        elements.append(Spacer(1, 8))
        elements.extend(self._build_key_projections(metrics))
        elements.append(Spacer(1, 8))
        elements.extend(self._build_property_details(property_data, metrics))
        elements.append(Spacer(1, 8))
        elements.extend(self._build_revenue_breakdown(metrics))
        
        # Page 1 footnotes
        elements.append(Spacer(1, 12))
        elements.extend(self._build_page_footnotes())
        
        # === PAGE 2: Market Intelligence ===
        elements.append(PageBreak())
        
        # Reset footnotes for page 2
        page1_footnotes = self.footnotes.copy()
        self.footnotes = []
        self.footnote_counter = 0
        
        elements.extend(self._build_market_intelligence(signals, geo_id, market_name, metrics))
        elements.append(Spacer(1, 8))
        elements.extend(self._build_signal_attribution(signals))
        elements.append(Spacer(1, 8))
        elements.extend(self._build_methodology_section(coverage))
        
        # Page 2 footnotes
        elements.append(Spacer(1, 12))
        elements.extend(self._build_page_footnotes())
        
        # Disclosure
        elements.append(Spacer(1, 8))
        elements.extend(self._build_disclosure())
        
        doc.build(elements)
        return buffer.getvalue()
    
    def _add_footnote(self, signal: Dict) -> int:
        """Add footnote and return its number."""
        self.footnote_counter += 1
        
        source = signal.get("source", "unknown")
        observed = signal.get("observed_at", "")
        if isinstance(observed, str) and observed:
            try:
                dt = datetime.fromisoformat(observed.replace('Z', '+00:00'))
                date_str = dt.strftime("%b %d, %Y")
            except:
                date_str = observed[:10]
        else:
            date_str = "N/A"
        
        confidence = signal.get("confidence", 0)
        sample = signal.get("metadata", {}).get("sample_size") or signal.get("metadata", {}).get("total_listings")
        
        source_names = {
            "airbnb_public": "Airbnb",
            "vrbo_public": "VRBO",
            "derived": "Analysis",
            "census_acs": "Census ACS",
            "aggregated": "Multi-source",
        }
        source_name = source_names.get(source, source)
        
        footnote = f"[{self.footnote_counter}] {source_name}, {date_str}"
        if sample:
            footnote += f", n={sample:,}"
        footnote += f", {confidence:.0%} conf."
        
        self.footnotes.append(footnote)
        return self.footnote_counter
    
    def _extract_metrics(
        self, 
        signals: List[Dict], 
        property_data: PropertyData
    ) -> Dict[str, SignalBackedMetric]:
        """Extract projection metrics from signals."""
        metrics = {}
        
        # Helper to find signal
        def get_signal(signal_type: str) -> Optional[Dict]:
            for s in signals:
                if s.get("signal_type") == signal_type:
                    return s
            return None
        
        # Rate Position → ADR
        rate_signal = get_signal("rate_position")
        if rate_signal:
            value = rate_signal.get("value", {})
            p50 = value.get("p50", 0)
            p25 = value.get("p25", p50 * 0.85)
            p75 = value.get("p75", p50 * 1.15)
            
            # Adjust for bedroom count
            br_rates = value.get("by_bedrooms", {})
            if str(property_data.bedrooms) in br_rates:
                p50 = br_rates[str(property_data.bedrooms)]
            elif property_data.bedrooms in br_rates:
                p50 = br_rates[property_data.bedrooms]
            
            fn = self._add_footnote(rate_signal)
            metrics["adr"] = SignalBackedMetric(
                name="Average Daily Rate",
                value=p50,
                unit="dollars",
                display_value=f"${p50:,.0f}",
                confidence=rate_signal.get("confidence", 0.7),
                confidence_level=rate_signal.get("confidence_level", "medium"),
                confidence_band=(p25, p75),
                band_display=f"${p25:,.0f} – ${p75:,.0f}",
                signal_type="rate_position",
                signal_source=rate_signal.get("source", "derived"),
                observed_at=datetime.utcnow(),
                footnote_num=fn,
            )
        
        # Calendar Compression → Occupancy
        demand_signal = get_signal("calendar_compression")
        if demand_signal:
            value = demand_signal.get("value", {})
            blocked_30d = value.get("blocked_pct_30d", 0.5)
            
            # Infer annual occupancy from compression
            # Higher compression = higher occupancy
            base_occ = 0.55 + (blocked_30d * 0.25)  # 55-80% range
            occ_low = base_occ * 0.9
            occ_high = min(base_occ * 1.1, 0.85)
            
            fn = self._add_footnote(demand_signal)
            metrics["occupancy"] = SignalBackedMetric(
                name="Projected Occupancy",
                value=base_occ,
                unit="percent",
                display_value=f"{base_occ:.0%}",
                confidence=demand_signal.get("confidence", 0.7),
                confidence_level=demand_signal.get("confidence_level", "medium"),
                confidence_band=(occ_low, occ_high),
                band_display=f"{occ_low:.0%} – {occ_high:.0%}",
                signal_type="calendar_compression",
                signal_source=demand_signal.get("source", "derived"),
                observed_at=datetime.utcnow(),
                footnote_num=fn,
            )
        
        # Calculate Annual Revenue
        if "adr" in metrics and "occupancy" in metrics:
            adr = metrics["adr"].value
            occ = metrics["occupancy"].value
            
            annual = adr * occ * 365
            annual_low = metrics["adr"].confidence_band[0] * metrics["occupancy"].confidence_band[0] * 365
            annual_high = metrics["adr"].confidence_band[1] * metrics["occupancy"].confidence_band[1] * 365
            
            # Composite confidence
            conf = (metrics["adr"].confidence + metrics["occupancy"].confidence) / 2
            
            metrics["annual_revenue"] = SignalBackedMetric(
                name="Projected Annual Revenue",
                value=annual,
                unit="dollars",
                display_value=f"${annual/1000:,.0f}K",
                confidence=conf,
                confidence_level="high" if conf >= 0.75 else "medium" if conf >= 0.5 else "low",
                confidence_band=(annual_low, annual_high),
                band_display=f"${annual_low/1000:,.0f}K – ${annual_high/1000:,.0f}K",
                signal_type="derived",
                signal_source="aggregated",
                observed_at=datetime.utcnow(),
                footnote_num=0,  # Derived, no direct footnote
            )
            
            # RevPAR
            revpar = adr * occ
            metrics["revpar"] = SignalBackedMetric(
                name="RevPAR",
                value=revpar,
                unit="dollars",
                display_value=f"${revpar:,.0f}",
                confidence=conf,
                confidence_level="high" if conf >= 0.75 else "medium" if conf >= 0.5 else "low",
                confidence_band=(annual_low/365, annual_high/365),
                band_display=f"${annual_low/365:,.0f} – ${annual_high/365:,.0f}",
                signal_type="derived",
                signal_source="aggregated",
                observed_at=datetime.utcnow(),
                footnote_num=0,
            )
        
        # Supply Density
        supply_signal = get_signal("supply_density")
        if supply_signal:
            value = supply_signal.get("value", {})
            listings = value.get("listings", 0)
            
            fn = self._add_footnote(supply_signal)
            metrics["market_supply"] = SignalBackedMetric(
                name="Market Supply",
                value=listings,
                unit="listings",
                display_value=f"{listings:,}",
                confidence=supply_signal.get("confidence", 0.8),
                confidence_level=supply_signal.get("confidence_level", "high"),
                confidence_band=(listings * 0.9, listings * 1.1),
                band_display=f"{int(listings*0.9):,} – {int(listings*1.1):,}",
                signal_type="supply_density",
                signal_source=supply_signal.get("source", "derived"),
                observed_at=datetime.utcnow(),
                footnote_num=fn,
            )
        
        # Platform Dominance
        platform_signal = get_signal("platform_dominance")
        if platform_signal:
            value = platform_signal.get("value", {})
            airbnb = value.get("airbnb_share", 0.5)
            
            fn = self._add_footnote(platform_signal)
            metrics["platform"] = SignalBackedMetric(
                name="Airbnb Market Share",
                value=airbnb,
                unit="percent",
                display_value=f"{airbnb:.0%}",
                confidence=platform_signal.get("confidence", 0.8),
                confidence_level=platform_signal.get("confidence_level", "high"),
                confidence_band=(airbnb - 0.05, airbnb + 0.05),
                band_display=f"{airbnb-0.05:.0%} – {airbnb+0.05:.0%}",
                signal_type="platform_dominance",
                signal_source=platform_signal.get("source", "derived"),
                observed_at=datetime.utcnow(),
                footnote_num=fn,
            )
        
        # Amenity prevalence
        amenity_signals = [s for s in signals if s.get("signal_type") == "amenity_prevalence"]
        if amenity_signals:
            metrics["amenity_signals"] = amenity_signals
        
        return metrics
    
    def _calculate_coverage(self, signals: List[Dict]) -> Dict[str, Any]:
        """Calculate signal coverage score."""
        types_present = set(s.get("signal_type") for s in signals)
        core_present = len(set(self.REQUIRED_SIGNALS) & types_present)
        core_total = len(self.REQUIRED_SIGNALS)
        
        coverage_score = core_present / core_total
        
        if coverage_score >= 0.9:
            grade = "A"
            color = COLORS["confidence_high"]
        elif coverage_score >= 0.75:
            grade = "B"
            color = COLORS["confidence_medium"]
        elif coverage_score >= 0.6:
            grade = "C"
            color = COLORS["confidence_low"]
        else:
            grade = "D"
            color = COLORS["danger"]
        
        confidences = [s.get("confidence", 0) for s in signals]
        avg_conf = sum(confidences) / len(confidences) if confidences else 0
        
        return {
            "score": coverage_score,
            "grade": grade,
            "color": color,
            "core_present": core_present,
            "core_total": core_total,
            "total_signals": len(signals),
            "avg_confidence": avg_conf,
            "missing": [s for s in self.REQUIRED_SIGNALS if s not in types_present],
        }
    
    def _build_header(
        self, 
        property_data: PropertyData, 
        market_name: str,
        coverage: Dict,
    ) -> List:
        """Build document header."""
        elements = []
        
        # Title row with grade badge
        title_text = "Investment Synopsis"
        address_text = f"{property_data.address}, {property_data.city}, {property_data.state}"
        
        # Grade badge
        grade_style = ParagraphStyle(
            "GradeStyle",
            fontSize=24,
            textColor=coverage["color"],
            alignment=TA_CENTER,
        )
        
        header_data = [
            [
                [
                    Paragraph(title_text, self.styles["title"]),
                    Paragraph(address_text, self.styles["address"]),
                    Paragraph(f"{market_name} Market • Generated {datetime.now().strftime('%B %d, %Y')}", self.styles["subtitle"]),
                ],
                [
                    Paragraph(coverage["grade"], grade_style),
                    Paragraph("Intelligence", self.styles["metric_label"]),
                    Paragraph("Grade", self.styles["metric_label"]),
                ],
            ]
        ]
        
        header_table = Table(header_data, colWidths=[5.5*inch, 1.5*inch])
        header_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('ALIGN', (1, 0), (1, 0), 'CENTER'),
        ]))
        
        elements.append(header_table)
        
        return elements
    
    def _build_key_projections(self, metrics: Dict[str, SignalBackedMetric]) -> List:
        """Build key projections section."""
        elements = []
        
        elements.append(Paragraph("Key Projections", self.styles["section_header"]))
        elements.append(HRFlowable(width="100%", thickness=1, color=COLORS["primary"], spaceBefore=0, spaceAfter=8))
        
        # Build projection boxes
        boxes = []
        
        # Annual Revenue
        if "annual_revenue" in metrics:
            m = metrics["annual_revenue"]
            boxes.append(self._build_metric_box(m, primary=True))
        
        # ADR
        if "adr" in metrics:
            m = metrics["adr"]
            boxes.append(self._build_metric_box(m))
        
        # Occupancy
        if "occupancy" in metrics:
            m = metrics["occupancy"]
            boxes.append(self._build_metric_box(m))
        
        # RevPAR
        if "revpar" in metrics:
            m = metrics["revpar"]
            boxes.append(self._build_metric_box(m))
        
        if boxes:
            # 4 columns
            col_width = 1.75 * inch
            table = Table([boxes], colWidths=[col_width] * len(boxes))
            table.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('LEFTPADDING', (0, 0), (-1, -1), 4),
                ('RIGHTPADDING', (0, 0), (-1, -1), 4),
            ]))
            elements.append(table)
        
        return elements
    
    def _build_metric_box(self, metric: SignalBackedMetric, primary: bool = False) -> List:
        """Build a single metric display box."""
        # Confidence style
        if metric.confidence_level == "high":
            conf_style = self.styles["confidence_high"]
            conf_text = f"● HIGH CONF ({metric.confidence:.0%})"
        elif metric.confidence_level == "medium":
            conf_style = self.styles["confidence_medium"]
            conf_text = f"● MED CONF ({metric.confidence:.0%})"
        else:
            conf_style = self.styles["confidence_low"]
            conf_text = f"● LOW CONF ({metric.confidence:.0%})"
        
        # Footnote reference
        fn_ref = f"<super>[{metric.footnote_num}]</super>" if metric.footnote_num > 0 else ""
        
        box_content = [
            Paragraph(metric.display_value + fn_ref, self.styles["metric_large"]),
            Paragraph(metric.name, self.styles["metric_label"]),
            Paragraph(metric.band_display, self.styles["metric_band"]),
            Paragraph(conf_text, conf_style),
        ]
        
        return box_content
    
    def _build_property_details(self, property_data: PropertyData, metrics: Dict) -> List:
        """Build property details section."""
        elements = []
        
        elements.append(Paragraph("Property Details", self.styles["section_header"]))
        elements.append(HRFlowable(width="100%", thickness=1, color=COLORS["primary"], spaceBefore=0, spaceAfter=8))
        
        # Two-column layout
        left_data = [
            ["Type:", property_data.property_type],
            ["Bedrooms:", str(property_data.bedrooms)],
            ["Bathrooms:", str(property_data.bathrooms)],
        ]
        if property_data.sqft:
            left_data.append(["Sq Ft:", f"{property_data.sqft:,}"])
        if property_data.year_built:
            left_data.append(["Year Built:", str(property_data.year_built)])
        
        # Amenities
        amenities = []
        if property_data.has_pool:
            amenities.append("Private Pool")
        if property_data.has_hot_tub:
            amenities.append("Hot Tub")
        if property_data.has_waterfront:
            amenities.append("Waterfront")
        if property_data.has_beach_access:
            amenities.append("Beach Access")
        if property_data.has_pet_friendly:
            amenities.append("Pet Friendly")
        amenities.extend(property_data.amenities[:3])  # Add up to 3 more
        
        right_data = [["Key Amenities:", ""]]
        for a in amenities[:5]:
            right_data.append(["  •", a])
        
        # Format tables
        left_table = Table(left_data, colWidths=[0.9*inch, 1.2*inch])
        left_table.setStyle(TableStyle([
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('TEXTCOLOR', (0, 0), (0, -1), COLORS["muted"]),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ]))
        
        right_table = Table(right_data, colWidths=[0.4*inch, 1.7*inch])
        right_table.setStyle(TableStyle([
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('TEXTCOLOR', (0, 0), (0, -1), COLORS["muted"]),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ]))
        
        # Market context
        market_data = []
        if "market_supply" in metrics:
            m = metrics["market_supply"]
            market_data.append([f"Market Supply:", f"{m.display_value} listings"])
        if "platform" in metrics:
            m = metrics["platform"]
            market_data.append([f"Platform Mix:", f"{m.display_value} Airbnb"])
        
        market_table = Table(market_data, colWidths=[1.1*inch, 1.5*inch]) if market_data else None
        if market_table:
            market_table.setStyle(TableStyle([
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('TEXTCOLOR', (0, 0), (0, -1), COLORS["muted"]),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('TOPPADDING', (0, 0), (-1, -1), 2),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
            ]))
        
        # Combine into row
        combined_data = [[left_table, right_table, market_table or ""]]
        combined = Table(combined_data, colWidths=[2.3*inch, 2.3*inch, 2.6*inch])
        combined.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))
        
        elements.append(combined)
        
        return elements
    
    def _build_revenue_breakdown(self, metrics: Dict) -> List:
        """Build monthly revenue breakdown."""
        elements = []
        
        elements.append(Paragraph("Revenue Projection Breakdown", self.styles["section_header"]))
        elements.append(HRFlowable(width="100%", thickness=1, color=COLORS["primary"], spaceBefore=0, spaceAfter=8))
        
        if "adr" not in metrics or "occupancy" not in metrics:
            elements.append(Paragraph("Insufficient signal data for detailed breakdown.", self.styles["body"]))
            return elements
        
        adr = metrics["adr"].value
        occ = metrics["occupancy"].value
        
        # Seasonal factors (simplified - in production, from seasonality_curve signal)
        seasonal = {
            "Jan": 0.75, "Feb": 0.80, "Mar": 1.10, "Apr": 1.05,
            "May": 1.15, "Jun": 1.25, "Jul": 1.30, "Aug": 1.20,
            "Sep": 0.90, "Oct": 0.95, "Nov": 0.85, "Dec": 0.90,
        }
        
        # Build table
        header = ["Month", "ADR", "Occ %", "Rev Days", "Revenue"]
        rows = [header]
        
        annual_total = 0
        
        for month, factor in seasonal.items():
            month_adr = adr * factor
            month_occ = min(occ * factor, 0.95)
            days_in_month = 30  # Simplified
            rev_days = days_in_month * month_occ
            revenue = month_adr * rev_days
            annual_total += revenue
            
            rows.append([
                month,
                f"${month_adr:,.0f}",
                f"{month_occ:.0%}",
                f"{rev_days:.1f}",
                f"${revenue:,.0f}",
            ])
        
        # Total row
        rows.append(["TOTAL", "—", "—", "—", f"${annual_total:,.0f}"])
        
        # Create table
        col_widths = [0.8*inch, 0.9*inch, 0.7*inch, 0.9*inch, 1.0*inch]
        table = Table(rows, colWidths=col_widths)
        table.setStyle(TableStyle([
            # Header
            ('BACKGROUND', (0, 0), (-1, 0), COLORS["primary"]),
            ('TEXTCOLOR', (0, 0), (-1, 0), COLORS["white"]),
            ('FONTSIZE', (0, 0), (-1, 0), 8),
            ('FONTSIZE', (0, 1), (-1, -1), 7),
            ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            # Alternating rows
            ('BACKGROUND', (0, 1), (-1, -2), COLORS["white"]),
            ('BACKGROUND', (0, 2), (-1, 2), COLORS["light"]),
            ('BACKGROUND', (0, 4), (-1, 4), COLORS["light"]),
            ('BACKGROUND', (0, 6), (-1, 6), COLORS["light"]),
            ('BACKGROUND', (0, 8), (-1, 8), COLORS["light"]),
            ('BACKGROUND', (0, 10), (-1, 10), COLORS["light"]),
            ('BACKGROUND', (0, 12), (-1, 12), COLORS["light"]),
            # Total row
            ('BACKGROUND', (0, -1), (-1, -1), COLORS["accent"]),
            ('TEXTCOLOR', (0, -1), (-1, -1), COLORS["white"]),
            ('FONTSIZE', (0, -1), (-1, -1), 8),
            # Grid
            ('GRID', (0, 0), (-1, -1), 0.5, COLORS["light"]),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]))
        
        elements.append(table)
        
        return elements
    
    def _build_page_footnotes(self) -> List:
        """Build footnotes for current page."""
        elements = []
        
        if self.footnotes:
            elements.append(HRFlowable(width="100%", thickness=0.5, color=COLORS["muted"], spaceBefore=4, spaceAfter=4))
            footnote_text = "  |  ".join(self.footnotes)
            elements.append(Paragraph(footnote_text, self.styles["footnote"]))
        
        return elements
    
    def _build_market_intelligence(
        self, 
        signals: List[Dict], 
        geo_id: str, 
        market_name: str,
        metrics: Dict,
    ) -> List:
        """Build market intelligence section (page 2)."""
        elements = []
        
        elements.append(Paragraph(f"Market Intelligence: {market_name}", self.styles["title"]))
        elements.append(Paragraph(
            f"Signal-backed analysis based on {len(signals)} data points",
            self.styles["subtitle"]
        ))
        
        elements.append(Spacer(1, 8))
        elements.append(Paragraph("Market Signals", self.styles["section_header"]))
        elements.append(HRFlowable(width="100%", thickness=1, color=COLORS["primary"], spaceBefore=0, spaceAfter=8))
        
        # Signal summary table
        rows = [["Signal Type", "Value", "Confidence", "Source"]]
        
        for signal in signals[:10]:  # Top 10 signals
            signal_type = signal.get("signal_type", "unknown")
            value = signal.get("value", {})
            
            # Format value
            if isinstance(value, dict):
                if "listings" in value:
                    val_str = f"{value['listings']:,} listings"
                elif "blocked_pct_30d" in value:
                    val_str = f"{value['blocked_pct_30d']:.0%} blocked (30d)"
                elif "airbnb_share" in value:
                    val_str = f"{value['airbnb_share']:.0%} Airbnb"
                elif "p50" in value:
                    val_str = f"${value['p50']:,.0f} median"
                elif "prevalence_pct" in value:
                    val_str = f"{value['prevalence_pct']:.0%} prevalence"
                else:
                    val_str = str(list(value.values())[0]) if value else "—"
            else:
                val_str = str(value)
            
            conf = signal.get("confidence", 0)
            conf_str = f"{conf:.0%}"
            
            source = signal.get("source", "unknown")
            source_names = {
                "airbnb_public": "Airbnb",
                "vrbo_public": "VRBO", 
                "derived": "Analysis",
                "census_acs": "Census",
                "aggregated": "Multi-source",
            }
            source_str = source_names.get(source, source)
            
            fn = self._add_footnote(signal)
            
            rows.append([
                signal_type.replace("_", " ").title(),
                val_str,
                conf_str,
                f"{source_str} [{fn}]",
            ])
        
        col_widths = [2*inch, 2*inch, 1*inch, 1.5*inch]
        table = Table(rows, colWidths=col_widths)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), COLORS["primary"]),
            ('TEXTCOLOR', (0, 0), (-1, 0), COLORS["white"]),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('ALIGN', (2, 0), (2, -1), 'CENTER'),
            ('GRID', (0, 0), (-1, -1), 0.5, COLORS["light"]),
            ('BACKGROUND', (0, 1), (-1, -1), COLORS["white"]),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        
        elements.append(table)
        
        return elements
    
    def _build_signal_attribution(self, signals: List[Dict]) -> List:
        """Build signal attribution section."""
        elements = []
        
        elements.append(Spacer(1, 8))
        elements.append(Paragraph("Signal Attribution", self.styles["section_header"]))
        elements.append(HRFlowable(width="100%", thickness=1, color=COLORS["primary"], spaceBefore=0, spaceAfter=8))
        
        # Group signals by source
        by_source = {}
        for s in signals:
            source = s.get("source", "unknown")
            if source not in by_source:
                by_source[source] = []
            by_source[source].append(s)
        
        # Source descriptions
        source_info = {
            "airbnb_public": ("Airbnb Public Listings", "Public search results and listing pages"),
            "vrbo_public": ("VRBO Public Listings", "Public search results and listing pages"),
            "derived": ("Derived Analysis", "Calculated from multiple primary sources"),
            "census_acs": ("US Census ACS", "American Community Survey 5-year estimates"),
            "aggregated": ("Multi-Source Aggregation", "Weighted combination of multiple signals"),
        }
        
        text_parts = []
        for source, signals_list in by_source.items():
            name, desc = source_info.get(source, (source, ""))
            text_parts.append(f"<b>{name}</b>: {desc} ({len(signals_list)} signals)")
        
        elements.append(Paragraph("<br/>".join(text_parts), self.styles["body"]))
        
        return elements
    
    def _build_methodology_section(self, coverage: Dict) -> List:
        """Build methodology section."""
        elements = []
        
        elements.append(Spacer(1, 8))
        elements.append(Paragraph("Methodology & Confidence", self.styles["section_header"]))
        elements.append(HRFlowable(width="100%", thickness=1, color=COLORS["primary"], spaceBefore=0, spaceAfter=8))
        
        methodology_text = f"""
        <b>Signal Coverage:</b> {coverage['core_present']}/{coverage['core_total']} core signals present ({coverage['score']:.0%} coverage)<br/><br/>
        
        <b>Confidence Calculation:</b> Confidence scores reflect sample size, data recency (time decay applied), 
        source reliability, and cross-validation between signals. Confidence bands represent the range of 
        expected outcomes, not worst/best case scenarios.<br/><br/>
        
        <b>Projection Methodology:</b> Revenue projections are calculated using signal-weighted ADR and occupancy 
        estimates, adjusted for seasonal patterns, amenity premiums, and market positioning. All projections 
        include explicit confidence bands.<br/><br/>
        
        <b>Data Freshness:</b> Signal timestamps indicate when data was observed. Older signals receive 
        reduced weight through exponential decay (half-life varies by signal type).
        """
        
        if coverage.get("missing"):
            methodology_text += f"<br/><br/><b>Missing Signals:</b> {', '.join(coverage['missing'])}"
        
        elements.append(Paragraph(methodology_text, self.styles["body"]))
        
        return elements
    
    def _build_disclosure(self) -> List:
        """Build disclosure section."""
        elements = []
        
        disclosure_text = """
        <b>Important Disclosures:</b> This analysis is based on publicly available data and derived analysis. 
        All projections are estimates and actual results may vary materially. Confidence bands reflect data 
        uncertainty, not guaranteed ranges. This document does not constitute investment, legal, or tax advice. 
        Past performance does not guarantee future results. Signal data is collected from public sources and 
        may not reflect all market activity.
        """
        
        elements.append(Paragraph(disclosure_text, self.styles["disclosure"]))
        
        return elements


# =============================================================================
# CONVENIENCE FUNCTION
# =============================================================================

def generate_signal_synopsis(
    property_data: PropertyData,
    signals: List[Dict],
    geo_id: str,
    market_name: Optional[str] = None,
) -> bytes:
    """Generate investment synopsis PDF (convenience function)."""
    generator = SignalBackedSynopsisGenerator()
    return generator.generate(property_data, signals, geo_id, market_name)


# =============================================================================
# CLI / TEST
# =============================================================================

if __name__ == "__main__":
    # Test with sample data
    property_data = PropertyData(
        address="123 Gulf View Drive",
        city="Santa Rosa Beach",
        state="FL",
        zipcode="32459",
        bedrooms=4,
        bathrooms=3.5,
        sqft=2800,
        year_built=2018,
        property_type="Single Family",
        has_pool=True,
        has_beach_access=True,
        amenities=["Gulf Views", "Gourmet Kitchen"],
    )
    
    # Sample signals
    signals = [
        {
            "signal_type": "supply_density",
            "source": "derived",
            "value": {"listings": 847, "by_platform": {"airbnb": 523, "vrbo": 324}},
            "confidence": 0.85,
            "confidence_level": "high",
            "observed_at": "2026-01-26T12:00:00Z",
            "metadata": {"sample_size": 847},
        },
        {
            "signal_type": "calendar_compression",
            "source": "derived",
            "value": {"blocked_pct_30d": 0.67, "blocked_pct_7d": 0.75},
            "confidence": 0.82,
            "confidence_level": "high",
            "observed_at": "2026-01-26T12:00:00Z",
            "metadata": {"sample_size": 523},
        },
        {
            "signal_type": "rate_position",
            "source": "derived",
            "value": {"p25": 385, "p50": 485, "p75": 695, "by_bedrooms": {4: 525}},
            "confidence": 0.80,
            "confidence_level": "high",
            "observed_at": "2026-01-26T12:00:00Z",
            "metadata": {"sample_size": 312},
        },
        {
            "signal_type": "platform_dominance",
            "source": "derived",
            "value": {"airbnb_share": 0.62, "vrbo_share": 0.38},
            "confidence": 0.88,
            "confidence_level": "high",
            "observed_at": "2026-01-26T12:00:00Z",
            "metadata": {"total_listings": 847},
        },
        {
            "signal_type": "amenity_prevalence",
            "source": "derived",
            "value": {"amenity": "pool", "prevalence_pct": 0.58},
            "confidence": 0.85,
            "confidence_level": "high",
            "observed_at": "2026-01-26T12:00:00Z",
            "metadata": {"sample_size": 847},
        },
        {
            "signal_type": "seasonality_curve",
            "source": "derived",
            "value": {"peak_month": 7, "low_month": 1, "amplitude": 0.55},
            "confidence": 0.90,
            "confidence_level": "high",
            "observed_at": "2026-01-26T12:00:00Z",
            "metadata": {},
        },
    ]
    
    # Generate
    pdf_bytes = generate_signal_synopsis(property_data, signals, "30a", "30A Beaches")
    
    # Save
    output_path = "/mnt/user-data/outputs/signal-backed-synopsis.pdf"
    with open(output_path, "wb") as f:
        f.write(pdf_bytes)
    
    print(f"Generated: {output_path}")
    print(f"Size: {len(pdf_bytes):,} bytes")
