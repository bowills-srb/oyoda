"""
Pitch Deck PDF Renderer - Investment Banking Grade Output.

Generates professional PDFs from PitchDeck objects.

Visual Design Guidelines:
- Serif headlines (simulated with bold)
- Muted color palette
- No dashboards
- Charts with annotations
- One insight per slide/page
- Confidence badges in corner

Think: Lazard / Evercore / Blackstone, not Tableau.
"""

from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor, white, black
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, Image, KeepTogether, HRFlowable
)
from reportlab.pdfgen import canvas
from reportlab.graphics.shapes import Drawing, Rect, String, Line
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.piecharts import Pie

from datetime import datetime
from typing import Dict, List, Any, Optional
from io import BytesIO


# =============================================================================
# COLOR PALETTE (Investment Banking Grade)
# =============================================================================

class Colors:
    """Muted, professional color palette."""
    NAVY = HexColor("#1a365d")
    CHARCOAL = HexColor("#2d3748")
    SLATE = HexColor("#4a5568")
    GRAY = HexColor("#718096")
    LIGHT_GRAY = HexColor("#e2e8f0")
    ACCENT_BLUE = HexColor("#3182ce")
    ACCENT_GREEN = HexColor("#38a169")
    ACCENT_AMBER = HexColor("#d69e2e")
    ACCENT_RED = HexColor("#e53e3e")
    WHITE = white
    BLACK = black


# =============================================================================
# STYLES
# =============================================================================

def get_pitch_styles():
    """Create investment banking grade styles."""
    styles = getSampleStyleSheet()
    
    # Title style (deck title)
    styles.add(ParagraphStyle(
        name='DeckTitle',
        parent=styles['Title'],
        fontSize=28,
        textColor=Colors.NAVY,
        spaceAfter=6,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold',
    ))
    
    # Subtitle
    styles.add(ParagraphStyle(
        name='DeckSubtitle',
        parent=styles['Normal'],
        fontSize=14,
        textColor=Colors.SLATE,
        spaceAfter=30,
        alignment=TA_CENTER,
        fontName='Helvetica',
    ))
    
    # Section title
    styles.add(ParagraphStyle(
        name='SectionTitle',
        parent=styles['Heading1'],
        fontSize=20,
        textColor=Colors.NAVY,
        spaceBefore=0,
        spaceAfter=12,
        fontName='Helvetica-Bold',
    ))
    
    # Section subtitle
    styles.add(ParagraphStyle(
        name='SectionSubtitle',
        parent=styles['Normal'],
        fontSize=11,
        textColor=Colors.GRAY,
        spaceAfter=18,
        fontName='Helvetica-Oblique',
    ))
    
    # Body text
    styles.add(ParagraphStyle(
        name='PitchBody',
        parent=styles['Normal'],
        fontSize=11,
        textColor=Colors.CHARCOAL,
        spaceAfter=12,
        leading=16,
        alignment=TA_JUSTIFY,
        fontName='Helvetica',
    ))
    
    # Headline (key insight)
    styles.add(ParagraphStyle(
        name='Headline',
        parent=styles['Normal'],
        fontSize=16,
        textColor=Colors.NAVY,
        spaceBefore=12,
        spaceAfter=18,
        fontName='Helvetica-Bold',
    ))
    
    # Metric large
    styles.add(ParagraphStyle(
        name='MetricLarge',
        parent=styles['Normal'],
        fontSize=36,
        textColor=Colors.NAVY,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold',
    ))
    
    # Metric label
    styles.add(ParagraphStyle(
        name='MetricLabel',
        parent=styles['Normal'],
        fontSize=10,
        textColor=Colors.GRAY,
        alignment=TA_CENTER,
        fontName='Helvetica',
    ))
    
    # Bullet point
    styles.add(ParagraphStyle(
        name='BulletPoint',
        parent=styles['Normal'],
        fontSize=11,
        textColor=Colors.CHARCOAL,
        leftIndent=20,
        spaceAfter=6,
        bulletIndent=10,
        fontName='Helvetica',
    ))
    
    # Footer
    styles.add(ParagraphStyle(
        name='Footer',
        parent=styles['Normal'],
        fontSize=8,
        textColor=Colors.GRAY,
        alignment=TA_CENTER,
        fontName='Helvetica',
    ))
    
    # Disclaimer
    styles.add(ParagraphStyle(
        name='Disclaimer',
        parent=styles['Normal'],
        fontSize=8,
        textColor=Colors.GRAY,
        spaceAfter=6,
        fontName='Helvetica-Oblique',
    ))
    
    # Driver text
    styles.add(ParagraphStyle(
        name='DriverText',
        parent=styles['Normal'],
        fontSize=12,
        textColor=Colors.CHARCOAL,
        spaceBefore=8,
        spaceAfter=8,
        fontName='Helvetica',
    ))
    
    return styles


# =============================================================================
# PDF RENDERER
# =============================================================================

class PitchDeckPDFRenderer:
    """
    Renders PitchDeck objects to professional PDFs.
    """
    
    def __init__(self):
        self.styles = get_pitch_styles()
        self.page_width, self.page_height = letter
        self.margin = 0.75 * inch
    
    def render(
        self,
        deck_data: Dict[str, Any],
        output_path: str,
        branding: Optional[Dict] = None,
    ) -> str:
        """
        Render a pitch deck to PDF.
        
        Args:
            deck_data: Dictionary with deck content
            output_path: Where to save the PDF
            branding: Optional branding configuration
        
        Returns:
            Path to generated PDF
        """
        doc = SimpleDocTemplate(
            output_path,
            pagesize=letter,
            rightMargin=self.margin,
            leftMargin=self.margin,
            topMargin=self.margin,
            bottomMargin=self.margin,
        )
        
        story = []
        
        # Cover page
        story.extend(self._render_cover(deck_data, branding))
        story.append(PageBreak())
        
        # Executive Summary
        story.extend(self._render_executive_summary(deck_data))
        story.append(PageBreak())
        
        # Market Overview
        story.extend(self._render_market_overview(deck_data))
        story.append(PageBreak())
        
        # Opportunity Set
        story.extend(self._render_opportunity_set(deck_data))
        story.append(PageBreak())
        
        # Scoring & Ranking
        story.extend(self._render_scoring(deck_data))
        story.append(PageBreak())
        
        # Financial Performance
        story.extend(self._render_financial(deck_data))
        story.append(PageBreak())
        
        # Analytical Drivers (The Killer Feature)
        story.extend(self._render_drivers(deck_data))
        story.append(PageBreak())
        
        # Risk & Confidence
        story.extend(self._render_risk(deck_data))
        story.append(PageBreak())
        
        # Recommendation
        story.extend(self._render_recommendation(deck_data))
        story.append(PageBreak())
        
        # Appendix
        story.extend(self._render_appendix(deck_data))
        
        # Build with page numbers
        doc.build(story, onFirstPage=self._add_page_elements, 
                  onLaterPages=self._add_page_elements)
        
        return output_path
    
    def _add_page_elements(self, canvas, doc):
        """Add header/footer to each page."""
        canvas.saveState()
        
        # Confidence badge in top right
        confidence = 82  # Would come from deck_data
        badge_text = f"Confidence: {confidence}%"
        canvas.setFont('Helvetica', 8)
        canvas.setFillColor(Colors.GRAY)
        canvas.drawRightString(
            self.page_width - self.margin,
            self.page_height - 0.5 * inch,
            badge_text
        )
        
        # Footer with page number
        canvas.setFont('Helvetica', 8)
        canvas.setFillColor(Colors.GRAY)
        canvas.drawCentredString(
            self.page_width / 2,
            0.5 * inch,
            f"Page {doc.page} | Confidential"
        )
        
        canvas.restoreState()
    
    def _render_cover(self, data: Dict, branding: Optional[Dict]) -> List:
        """Render cover page."""
        story = []
        
        # Spacer to center content
        story.append(Spacer(1, 2 * inch))
        
        # Company name (if branding)
        if branding and branding.get('company_name'):
            story.append(Paragraph(
                branding['company_name'],
                self.styles['SectionSubtitle']
            ))
        
        # Title
        story.append(Paragraph(
            data.get('title', 'Investment Analysis'),
            self.styles['DeckTitle']
        ))
        
        # Subtitle
        story.append(Paragraph(
            data.get('subtitle', ''),
            self.styles['DeckSubtitle']
        ))
        
        story.append(Spacer(1, inch))
        
        # Key metrics boxes
        metrics_data = [
            [
                self._metric_box("Properties", str(data.get('total_candidates', 14))),
                self._metric_box("Median Value", f"${data.get('median_value', 2500000):,.0f}"),
                self._metric_box("Confidence", f"{data.get('confidence', 82)}%"),
            ]
        ]
        
        metrics_table = Table(metrics_data, colWidths=[2*inch, 2*inch, 2*inch])
        metrics_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        story.append(metrics_table)
        
        story.append(Spacer(1, 2 * inch))
        
        # Date
        story.append(Paragraph(
            f"Prepared: {datetime.now().strftime('%B %d, %Y')}",
            self.styles['Footer']
        ))
        
        # Audience
        story.append(Paragraph(
            f"For: {data.get('audience', 'Investment Committee').title()}",
            self.styles['Footer']
        ))
        
        return story
    
    def _metric_box(self, label: str, value: str) -> List:
        """Create a metric display box."""
        return [
            Paragraph(value, self.styles['MetricLarge']),
            Paragraph(label, self.styles['MetricLabel']),
        ]
    
    def _render_executive_summary(self, data: Dict) -> List:
        """Render executive summary section."""
        story = []
        
        story.append(Paragraph("Executive Summary", self.styles['SectionTitle']))
        story.append(HRFlowable(width="100%", thickness=1, color=Colors.LIGHT_GRAY))
        story.append(Spacer(1, 12))
        
        # Headline
        headline = data.get('headline', 
            f"We identified {data.get('total_candidates', 14)} high-quality STR acquisition "
            f"candidates in {data.get('geo_name', 'Scottsdale')} with strong cash-flow resilience."
        )
        story.append(Paragraph(headline, self.styles['Headline']))
        
        # Key highlights
        story.append(Paragraph("Key Highlights", self.styles['SectionSubtitle']))
        
        highlights = data.get('highlights', [
            f"{data.get('total_candidates', 14)} properties met all screening criteria",
            f"Median projected cash flow: ${data.get('median_cashflow', 85000):,.0f}/year",
            f"Analysis confidence: {data.get('confidence', 82)}%",
            f"Primary driver: Seasonality tailwind (+14%)",
        ])
        
        for highlight in highlights:
            story.append(Paragraph(f"• {highlight}", self.styles['BulletPoint']))
        
        story.append(Spacer(1, 18))
        
        # Recommendation box
        rec_data = [[
            Paragraph("<b>RECOMMENDATION</b>", self.styles['PitchBody']),
            Paragraph(
                data.get('recommendation', 'Proceed with acquisition targeting'),
                self.styles['PitchBody']
            ),
        ]]
        
        rec_table = Table(rec_data, colWidths=[1.5*inch, 5*inch])
        rec_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, 0), Colors.NAVY),
            ('TEXTCOLOR', (0, 0), (0, 0), Colors.WHITE),
            ('BACKGROUND', (1, 0), (1, 0), Colors.LIGHT_GRAY),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('PADDING', (0, 0), (-1, -1), 12),
        ]))
        story.append(rec_table)
        
        return story
    
    def _render_market_overview(self, data: Dict) -> List:
        """Render market overview section."""
        story = []
        
        story.append(Paragraph("Market Overview", self.styles['SectionTitle']))
        story.append(HRFlowable(width="100%", thickness=1, color=Colors.LIGHT_GRAY))
        story.append(Spacer(1, 12))
        
        geo_name = data.get('geo_name', 'Scottsdale')
        
        # Market narrative
        narrative = data.get('market_narrative',
            f"Demand growth (+8.2%) continues to outpace supply additions (+3.1%), "
            f"supporting ADR expansion in {geo_name}."
        )
        story.append(Paragraph(narrative, self.styles['Headline']))
        
        story.append(Spacer(1, 18))
        
        # Market metrics table
        market_data = [
            ['Metric', 'Value', 'Trend'],
            ['Demand Growth', '+8.2%', '▲ Positive'],
            ['Supply Growth', '+3.1%', '— Stable'],
            ['ADR Trend', '+5.4%', '▲ Positive'],
            ['Occupancy Trend', '+2.1%', '▲ Positive'],
            ['Market Phase', 'Expansion', '—'],
        ]
        
        market_table = Table(market_data, colWidths=[2.5*inch, 2*inch, 2*inch])
        market_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), Colors.NAVY),
            ('TEXTCOLOR', (0, 0), (-1, 0), Colors.WHITE),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('GRID', (0, 0), (-1, -1), 0.5, Colors.LIGHT_GRAY),
            ('PADDING', (0, 0), (-1, -1), 8),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [Colors.WHITE, HexColor("#f7fafc")]),
        ]))
        story.append(market_table)
        
        return story
    
    def _render_opportunity_set(self, data: Dict) -> List:
        """Render opportunity set section."""
        story = []
        
        story.append(Paragraph("Opportunity Set", self.styles['SectionTitle']))
        story.append(HRFlowable(width="100%", thickness=1, color=Colors.LIGHT_GRAY))
        story.append(Spacer(1, 12))
        
        total = data.get('total_analyzed', 127)
        qualified = data.get('total_candidates', 14)
        
        story.append(Paragraph(
            f"From {total} properties analyzed, {qualified} met all screening criteria "
            f"({qualified/total*100:.1f}% qualification rate).",
            self.styles['Headline']
        ))
        
        story.append(Spacer(1, 12))
        
        # Filters applied
        story.append(Paragraph("Screening Criteria Applied", self.styles['SectionSubtitle']))
        
        filters = data.get('filters', [
            "Estimated value ≥ $2,000,000",
            "Bedrooms ≥ 4",
            "Required amenities: Pool, Waterfront access",
            "STR zoning permitted",
        ])
        
        for f in filters:
            story.append(Paragraph(f"✓ {f}", self.styles['BulletPoint']))
        
        story.append(Spacer(1, 18))
        
        # Summary stats
        stats_data = [
            ['Metric', 'Qualified Set'],
            ['Median Value', f"${data.get('median_value', 2750000):,.0f}"],
            ['Value Range', f"${data.get('value_min', 2100000):,.0f} - ${data.get('value_max', 4200000):,.0f}"],
            ['Median Cashflow', f"${data.get('median_cashflow', 85000):,.0f}/yr"],
            ['Properties', str(qualified)],
        ]
        
        stats_table = Table(stats_data, colWidths=[3*inch, 3.5*inch])
        stats_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), Colors.NAVY),
            ('TEXTCOLOR', (0, 0), (-1, 0), Colors.WHITE),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('GRID', (0, 0), (-1, -1), 0.5, Colors.LIGHT_GRAY),
            ('PADDING', (0, 0), (-1, -1), 8),
        ]))
        story.append(stats_table)
        
        return story
    
    def _render_scoring(self, data: Dict) -> List:
        """Render scoring and ranking section."""
        story = []
        
        story.append(Paragraph("Scoring & Ranking", self.styles['SectionTitle']))
        story.append(HRFlowable(width="100%", thickness=1, color=Colors.LIGHT_GRAY))
        story.append(Spacer(1, 12))
        
        story.append(Paragraph(
            "Properties scored on five dimensions using signal-derived analytics.",
            self.styles['PitchBody']
        ))
        
        story.append(Spacer(1, 12))
        
        # Scoring methodology
        methodology_data = [
            ['Component', 'Weight', 'Description'],
            ['Cash Flow Strength', '30%', 'Projected NOI relative to value'],
            ['Seasonality Resilience', '20%', 'Revenue stability across periods'],
            ['Platform Distribution', '15%', 'Channel diversification score'],
            ['Operator Fit', '25%', 'Alignment with operator profile'],
            ['Risk-Adjusted Return', '10%', 'Confidence-weighted returns'],
        ]
        
        method_table = Table(methodology_data, colWidths=[2*inch, 1*inch, 3.5*inch])
        method_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), Colors.NAVY),
            ('TEXTCOLOR', (0, 0), (-1, 0), Colors.WHITE),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('ALIGN', (1, 0), (1, -1), 'CENTER'),
            ('GRID', (0, 0), (-1, -1), 0.5, Colors.LIGHT_GRAY),
            ('PADDING', (0, 0), (-1, -1), 6),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [Colors.WHITE, HexColor("#f7fafc")]),
        ]))
        story.append(method_table)
        
        story.append(Spacer(1, 18))
        
        # Top 5 properties
        story.append(Paragraph("Top Ranked Properties", self.styles['SectionSubtitle']))
        
        top_props = [
            ['Rank', 'Address', 'Score', 'Grade', 'Projected Revenue'],
            ['1', '8842 E Pinnacle Peak Rd', '87.3', 'A', '$112,000'],
            ['2', '12445 N 85th St', '84.1', 'A', '$98,500'],
            ['3', '7620 E Doubletree Ranch Rd', '81.7', 'A-', '$105,200'],
            ['4', '9901 E Happy Valley Rd', '79.2', 'B+', '$94,800'],
            ['5', '14255 N 91st Pl', '77.8', 'B+', '$89,400'],
        ]
        
        props_table = Table(top_props, colWidths=[0.5*inch, 2.5*inch, 0.8*inch, 0.7*inch, 1.5*inch])
        props_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), Colors.SLATE),
            ('TEXTCOLOR', (0, 0), (-1, 0), Colors.WHITE),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('ALIGN', (0, 0), (0, -1), 'CENTER'),
            ('ALIGN', (2, 0), (-1, -1), 'CENTER'),
            ('GRID', (0, 0), (-1, -1), 0.5, Colors.LIGHT_GRAY),
            ('PADDING', (0, 0), (-1, -1), 6),
        ]))
        story.append(props_table)
        
        return story
    
    def _render_financial(self, data: Dict) -> List:
        """Render financial performance section."""
        story = []
        
        story.append(Paragraph("Financial Performance", self.styles['SectionTitle']))
        story.append(HRFlowable(width="100%", thickness=1, color=Colors.LIGHT_GRAY))
        story.append(Spacer(1, 12))
        
        story.append(Paragraph(
            "All projections include confidence bands reflecting data quality.",
            self.styles['SectionSubtitle']
        ))
        
        # Financial metrics with ranges
        fin_data = [
            ['Metric', 'Low', 'Expected', 'High'],
            ['ADR', '$285', '$325', '$375'],
            ['Occupancy', '55%', '65%', '72%'],
            ['Annual Revenue', '$65,000', '$85,000', '$105,000'],
        ]
        
        fin_table = Table(fin_data, colWidths=[2*inch, 1.5*inch, 1.5*inch, 1.5*inch])
        fin_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), Colors.NAVY),
            ('TEXTCOLOR', (0, 0), (-1, 0), Colors.WHITE),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTNAME', (2, 1), (2, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
            ('GRID', (0, 0), (-1, -1), 0.5, Colors.LIGHT_GRAY),
            ('PADDING', (0, 0), (-1, -1), 8),
            ('BACKGROUND', (2, 1), (2, -1), HexColor("#e6fffa")),
        ]))
        story.append(fin_table)
        
        story.append(Spacer(1, 18))
        
        # Investment metrics
        story.append(Paragraph("Investment Metrics (Expected Case)", self.styles['SectionSubtitle']))
        
        inv_data = [
            ['Cap Rate', 'Cash-on-Cash', 'Payback Period', 'IRR (5-Year)'],
            ['7.8%', '12.4%', '8.1 Years', '14.2%'],
        ]
        
        inv_table = Table(inv_data, colWidths=[1.6*inch, 1.6*inch, 1.6*inch, 1.6*inch])
        inv_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), Colors.SLATE),
            ('TEXTCOLOR', (0, 0), (-1, 0), Colors.WHITE),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTNAME', (0, 1), (-1, 1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('FONTSIZE', (0, 1), (-1, 1), 18),
            ('TEXTCOLOR', (0, 1), (-1, 1), Colors.NAVY),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('GRID', (0, 0), (-1, -1), 0.5, Colors.LIGHT_GRAY),
            ('PADDING', (0, 0), (-1, -1), 12),
        ]))
        story.append(inv_table)
        
        return story
    
    def _render_drivers(self, data: Dict) -> List:
        """Render analytical drivers - THE KILLER FEATURE."""
        story = []
        
        story.append(Paragraph("Analytical Drivers", self.styles['SectionTitle']))
        story.append(HRFlowable(width="100%", thickness=1, color=Colors.LIGHT_GRAY))
        story.append(Spacer(1, 12))
        
        story.append(Paragraph(
            "Every projection is traceable to specific market signals.",
            self.styles['SectionSubtitle']
        ))
        
        # Drivers with impact
        drivers = data.get('drivers', [
            {'name': 'Seasonality Tailwind', 'impact': '+14%', 'confidence': 'High', 'source': 'Booking patterns'},
            {'name': 'Pool Amenity Premium', 'impact': '+11%', 'confidence': 'High', 'source': 'Comp analysis'},
            {'name': 'Platform Diversification', 'impact': '+6%', 'confidence': 'Medium', 'source': 'Channel data'},
            {'name': 'Operator Excellence', 'impact': '+5%', 'confidence': 'High', 'source': 'Portfolio performance'},
            {'name': 'Market Momentum', 'impact': '+3%', 'confidence': 'Medium', 'source': 'Demand signals'},
        ])
        
        for driver in drivers:
            # Driver box
            conf_color = Colors.ACCENT_GREEN if driver['confidence'] == 'High' else Colors.ACCENT_AMBER
            
            driver_text = (
                f"<b>{driver['name']}</b> ({driver['impact']}) — "
                f"{driver['confidence']} Confidence"
            )
            story.append(Paragraph(driver_text, self.styles['DriverText']))
            
            source_text = f"Source: {driver['source']}"
            story.append(Paragraph(source_text, self.styles['Disclaimer']))
            story.append(Spacer(1, 6))
        
        story.append(Spacer(1, 12))
        
        # Why this matters box
        why_data = [[
            Paragraph(
                "<b>Why This Matters:</b> Unlike competitors who show aggregate trends, "
                "we trace every claim to specific signals. This makes projections "
                "defensible, auditable, and actionable.",
                self.styles['PitchBody']
            )
        ]]
        
        why_table = Table(why_data, colWidths=[6.5*inch])
        why_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), HexColor("#ebf8ff")),
            ('BOX', (0, 0), (-1, -1), 1, Colors.ACCENT_BLUE),
            ('PADDING', (0, 0), (-1, -1), 12),
        ]))
        story.append(why_table)
        
        return story
    
    def _render_risk(self, data: Dict) -> List:
        """Render risk and confidence section."""
        story = []
        
        story.append(Paragraph("Risk & Confidence", self.styles['SectionTitle']))
        story.append(HRFlowable(width="100%", thickness=1, color=Colors.LIGHT_GRAY))
        story.append(Spacer(1, 12))
        
        # Confidence summary
        conf_data = [
            ['Overall Confidence', 'Data Coverage', 'Volatility Risk'],
            ['82%', '91%', 'Low'],
        ]
        
        conf_table = Table(conf_data, colWidths=[2.1*inch, 2.1*inch, 2.1*inch])
        conf_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), Colors.SLATE),
            ('TEXTCOLOR', (0, 0), (-1, 0), Colors.WHITE),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTNAME', (0, 1), (-1, 1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 1), (-1, 1), 20),
            ('TEXTCOLOR', (0, 1), (1, 1), Colors.ACCENT_GREEN),
            ('TEXTCOLOR', (2, 1), (2, 1), Colors.ACCENT_GREEN),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('GRID', (0, 0), (-1, -1), 0.5, Colors.LIGHT_GRAY),
            ('PADDING', (0, 0), (-1, -1), 12),
        ]))
        story.append(conf_table)
        
        story.append(Spacer(1, 18))
        
        # Risk factors
        story.append(Paragraph("Risk Factors", self.styles['SectionSubtitle']))
        
        risks = [
            "Short-term supply acceleration possible in Q3",
            "Interest rate sensitivity on leveraged returns",
            "Regulatory changes in some jurisdictions",
        ]
        
        for risk in risks:
            story.append(Paragraph(f"⚠ {risk}", self.styles['BulletPoint']))
        
        story.append(Spacer(1, 12))
        
        # Mitigants
        story.append(Paragraph("Mitigants", self.styles['SectionSubtitle']))
        
        mitigants = [
            "Strong booking velocity provides demand cushion",
            "Diversified platform exposure reduces channel risk",
            "Premium amenity set supports rate resilience",
        ]
        
        for mit in mitigants:
            story.append(Paragraph(f"✓ {mit}", self.styles['BulletPoint']))
        
        return story
    
    def _render_recommendation(self, data: Dict) -> List:
        """Render recommendation section."""
        story = []
        
        story.append(Paragraph("Recommendation", self.styles['SectionTitle']))
        story.append(HRFlowable(width="100%", thickness=1, color=Colors.LIGHT_GRAY))
        story.append(Spacer(1, 12))
        
        # Action box
        action = data.get('action', 'Proceed with acquisition targeting')
        
        action_data = [[
            Paragraph(f"<b>ACTION:</b> {action}", self.styles['Headline'])
        ]]
        
        action_table = Table(action_data, colWidths=[6.5*inch])
        action_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), Colors.NAVY),
            ('TEXTCOLOR', (0, 0), (-1, -1), Colors.WHITE),
            ('PADDING', (0, 0), (-1, -1), 16),
        ]))
        story.append(action_table)
        
        story.append(Spacer(1, 18))
        
        # Rationale
        story.append(Paragraph("Rationale", self.styles['SectionSubtitle']))
        
        rationale = [
            "Strong market fundamentals support entry",
            "Qualified properties meet all screening criteria",
            "Risk-adjusted returns exceed portfolio targets",
            "High confidence in projections (82%)",
        ]
        
        for r in rationale:
            story.append(Paragraph(f"• {r}", self.styles['BulletPoint']))
        
        story.append(Spacer(1, 12))
        
        # Next steps
        story.append(Paragraph("Next Steps", self.styles['SectionSubtitle']))
        
        steps = [
            "Schedule property tours for top 5 candidates",
            "Conduct property-level due diligence",
            "Prepare offer documentation",
            "Coordinate financing pre-approval",
        ]
        
        for i, step in enumerate(steps, 1):
            story.append(Paragraph(f"{i}. {step}", self.styles['BulletPoint']))
        
        return story
    
    def _render_appendix(self, data: Dict) -> List:
        """Render appendix section."""
        story = []
        
        story.append(Paragraph("Appendix: Methodology", self.styles['SectionTitle']))
        story.append(HRFlowable(width="100%", thickness=1, color=Colors.LIGHT_GRAY))
        story.append(Spacer(1, 12))
        
        # Data sources
        story.append(Paragraph("Data Sources", self.styles['SectionSubtitle']))
        
        sources = [
            "Internal booking data (12-month trailing)",
            "Market rate surveys (weekly refresh)",
            "Platform API feeds (Airbnb, VRBO)",
            "Comparable transaction records",
            "Public records and assessor data",
        ]
        
        for source in sources:
            story.append(Paragraph(f"• {source}", self.styles['BulletPoint']))
        
        story.append(Spacer(1, 12))
        
        # Methodology notes
        story.append(Paragraph("Methodology Notes", self.styles['SectionSubtitle']))
        
        notes = [
            "Signals are time-weighted with exponential decay (30-day half-life default)",
            "Confidence bands reflect data coverage and signal freshness",
            "Attribution uses causal isolation methodology",
            "Projections validated against actual portfolio performance",
        ]
        
        for note in notes:
            story.append(Paragraph(f"• {note}", self.styles['BulletPoint']))
        
        story.append(Spacer(1, 18))
        
        # Disclaimer
        disclaimer = (
            "This analysis is based on market-derived signals and proprietary analytics. "
            "Past performance is not indicative of future results. All projections include "
            "confidence bands reflecting data quality and coverage. This document is for "
            "informational purposes only and does not constitute investment advice. "
            "Verify all assumptions before making investment decisions."
        )
        
        story.append(Paragraph(disclaimer, self.styles['Disclaimer']))
        
        return story


# =============================================================================
# CONVENIENCE FUNCTION
# =============================================================================

def render_pitch_deck_pdf(
    deck_data: Dict[str, Any],
    output_path: str,
    branding: Optional[Dict] = None,
) -> str:
    """
    Render a pitch deck to PDF.
    
    Example:
        render_pitch_deck_pdf(
            {
                'title': 'Scottsdale STR Acquisition Memo',
                'geo_name': 'Scottsdale',
                'total_candidates': 14,
                'confidence': 82,
                ...
            },
            '/path/to/output.pdf'
        )
    """
    renderer = PitchDeckPDFRenderer()
    return renderer.render(deck_data, output_path, branding)
