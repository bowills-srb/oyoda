"""
Property Synopsis PDF Renderer.

Generates 1-2 page investment-grade PDFs for individual properties.

Design:
- Page 1: Investment Snapshot (What & How Much)
- Page 2: Context, Risk & Operator Insight (Why It's Defensible)

Think: IC memo, not marketing brochure.
"""

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor, white
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, HRFlowable, KeepTogether
)

from datetime import datetime
from typing import Dict, Any, Optional


# =============================================================================
# COLORS
# =============================================================================

class Colors:
    NAVY = HexColor("#1a365d")
    CHARCOAL = HexColor("#2d3748")
    SLATE = HexColor("#4a5568")
    GRAY = HexColor("#718096")
    LIGHT_GRAY = HexColor("#e2e8f0")
    VERY_LIGHT = HexColor("#f7fafc")
    ACCENT_GREEN = HexColor("#38a169")
    ACCENT_AMBER = HexColor("#d69e2e")
    ACCENT_BLUE = HexColor("#3182ce")
    WHITE = white


# =============================================================================
# STYLES
# =============================================================================

def get_synopsis_styles():
    """Create synopsis-specific styles."""
    styles = getSampleStyleSheet()
    
    styles.add(ParagraphStyle(
        name='SynopsisTitle',
        fontSize=22,
        textColor=Colors.NAVY,
        spaceAfter=4,
        fontName='Helvetica-Bold',
    ))
    
    styles.add(ParagraphStyle(
        name='PropertyAddress',
        fontSize=12,
        textColor=Colors.SLATE,
        spaceAfter=2,
        fontName='Helvetica',
    ))
    
    styles.add(ParagraphStyle(
        name='MarketName',
        fontSize=10,
        textColor=Colors.GRAY,
        spaceAfter=12,
        fontName='Helvetica-Oblique',
    ))
    
    styles.add(ParagraphStyle(
        name='SectionHead',
        fontSize=14,
        textColor=Colors.NAVY,
        spaceBefore=16,
        spaceAfter=8,
        fontName='Helvetica-Bold',
    ))
    
    styles.add(ParagraphStyle(
        name='SynopsisBody',
        fontSize=10,
        textColor=Colors.CHARCOAL,
        spaceAfter=8,
        leading=14,
        fontName='Helvetica',
    ))
    
    styles.add(ParagraphStyle(
        name='BulletItem',
        fontSize=10,
        textColor=Colors.CHARCOAL,
        leftIndent=15,
        spaceAfter=4,
        fontName='Helvetica',
    ))
    
    styles.add(ParagraphStyle(
        name='MetricValue',
        fontSize=24,
        textColor=Colors.NAVY,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold',
    ))
    
    styles.add(ParagraphStyle(
        name='MetricLabel',
        fontSize=9,
        textColor=Colors.GRAY,
        alignment=TA_CENTER,
        fontName='Helvetica',
    ))
    
    styles.add(ParagraphStyle(
        name='DriverName',
        fontSize=10,
        textColor=Colors.CHARCOAL,
        fontName='Helvetica-Bold',
    ))
    
    styles.add(ParagraphStyle(
        name='DriverDetail',
        fontSize=9,
        textColor=Colors.GRAY,
        fontName='Helvetica',
    ))
    
    styles.add(ParagraphStyle(
        name='Recommendation',
        fontSize=11,
        textColor=Colors.NAVY,
        spaceBefore=12,
        spaceAfter=12,
        fontName='Helvetica-Bold',
    ))
    
    styles.add(ParagraphStyle(
        name='TrustStatement',
        fontSize=8,
        textColor=Colors.GRAY,
        fontName='Helvetica-Oblique',
    ))
    
    styles.add(ParagraphStyle(
        name='FooterText',
        fontSize=7,
        textColor=Colors.GRAY,
        alignment=TA_CENTER,
        fontName='Helvetica',
    ))
    
    return styles


# =============================================================================
# RENDERER
# =============================================================================

class PropertySynopsisPDFRenderer:
    """Renders Property Investment Synopsis to PDF."""
    
    def __init__(self):
        self.styles = get_synopsis_styles()
        self.page_width, self.page_height = letter
        self.margin = 0.6 * inch
    
    def render(
        self,
        synopsis_data: Dict[str, Any],
        output_path: str,
        branding: Optional[Dict] = None,
    ) -> str:
        """
        Render a property synopsis to PDF.
        
        Args:
            synopsis_data: Synopsis data dictionary
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
        
        # === PAGE 1: Investment Snapshot ===
        story.extend(self._render_page1_header(synopsis_data, branding))
        story.extend(self._render_executive_takeaway(synopsis_data))
        story.extend(self._render_revenue_outlook(synopsis_data))
        story.extend(self._render_drivers(synopsis_data))
        
        story.append(PageBreak())
        
        # === PAGE 2: Context & Risk ===
        story.extend(self._render_page2_header(synopsis_data))
        story.extend(self._render_operator_context(synopsis_data))
        story.extend(self._render_comparable_context(synopsis_data))
        story.extend(self._render_risks(synopsis_data))
        story.extend(self._render_recommendation(synopsis_data))
        
        # Build
        doc.build(story, onFirstPage=self._add_footer, onLaterPages=self._add_footer)
        
        return output_path
    
    def _add_footer(self, canvas, doc):
        """Add footer to each page."""
        canvas.saveState()
        
        # Confidence badge
        confidence = 84  # Would come from data
        canvas.setFont('Helvetica', 7)
        canvas.setFillColor(Colors.GRAY)
        canvas.drawRightString(
            self.page_width - self.margin,
            self.margin - 0.2 * inch,
            f"Confidence: {confidence}% | Generated: {datetime.now().strftime('%b %d, %Y')}"
        )
        
        # Confidential marker
        canvas.drawString(
            self.margin,
            self.margin - 0.2 * inch,
            "CONFIDENTIAL"
        )
        
        canvas.restoreState()
    
    def _render_page1_header(self, data: Dict, branding: Optional[Dict]) -> list:
        """Render Page 1 header with property details."""
        story = []
        
        # Title strip
        story.append(Paragraph("PROPERTY INVESTMENT SYNOPSIS", self.styles['SynopsisTitle']))
        
        # Property address
        address = data.get('address', '123 Example Street')
        story.append(Paragraph(address, self.styles['PropertyAddress']))
        
        # Market and property specs
        market = data.get('market_name', 'Market')
        beds = data.get('bedrooms', 4)
        baths = data.get('bathrooms', 3)
        sleeps = data.get('sleeps', 10)
        
        specs = f"{market} | {beds} BD / {baths} BA | Sleeps {sleeps}"
        story.append(Paragraph(specs, self.styles['MarketName']))
        
        # Key amenities as badges
        amenities = data.get('key_amenities', ['Pool', 'Gulf View', 'Hot Tub'])
        if amenities:
            amenity_text = " • ".join(amenities[:5])
            story.append(Paragraph(f"<i>{amenity_text}</i>", self.styles['MarketName']))
        
        story.append(HRFlowable(width="100%", thickness=1, color=Colors.LIGHT_GRAY))
        
        return story
    
    def _render_executive_takeaway(self, data: Dict) -> list:
        """Render executive summary bullets."""
        story = []
        
        story.append(Paragraph("Investment Summary", self.styles['SectionHead']))
        
        summary_points = data.get('executive_summary', [
            "Strong STR candidate in a demand-constrained coastal submarket",
            "Above-market performance driven by amenity mix and operator execution",
            "Revenue outlook supported by stable seasonality and platform demand",
        ])
        
        for point in summary_points:
            story.append(Paragraph(f"• {point}", self.styles['BulletItem']))
        
        return story
    
    def _render_revenue_outlook(self, data: Dict) -> list:
        """Render revenue outlook with bands."""
        story = []
        
        story.append(Paragraph("Revenue Outlook", self.styles['SectionHead']))
        
        # Get revenue data
        revenue = data.get('revenue_outlook', {})
        rev_low = revenue.get('low', 165000)
        rev_base = revenue.get('base', 185000)
        rev_high = revenue.get('high', 210000)
        confidence = revenue.get('confidence', 0.84)
        
        adr = data.get('adr_band', {})
        adr_low = adr.get('low', 375)
        adr_base = adr.get('base', 425)
        adr_high = adr.get('high', 475)
        
        occ = data.get('occupancy_band', {})
        occ_low = occ.get('low', 0.55)
        occ_base = occ.get('base', 0.65)
        occ_high = occ.get('high', 0.72)
        
        # Create metrics table
        metrics_data = [
            ['', 'Low', 'Expected', 'High'],
            ['Annual Revenue', f'${rev_low:,.0f}', f'${rev_base:,.0f}', f'${rev_high:,.0f}'],
            ['ADR', f'${adr_low:,.0f}', f'${adr_base:,.0f}', f'${adr_high:,.0f}'],
            ['Occupancy', f'{occ_low:.0%}', f'{occ_base:.0%}', f'{occ_high:.0%}'],
        ]
        
        metrics_table = Table(metrics_data, colWidths=[1.5*inch, 1.3*inch, 1.3*inch, 1.3*inch])
        metrics_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), Colors.NAVY),
            ('TEXTCOLOR', (0, 0), (-1, 0), Colors.WHITE),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
            ('ALIGN', (0, 1), (0, -1), 'LEFT'),
            ('FONTNAME', (0, 1), (0, -1), 'Helvetica-Bold'),
            ('FONTNAME', (2, 1), (2, -1), 'Helvetica-Bold'),
            ('TEXTCOLOR', (2, 1), (2, -1), Colors.NAVY),
            ('BACKGROUND', (2, 1), (2, -1), HexColor("#e6fffa")),
            ('GRID', (0, 0), (-1, -1), 0.5, Colors.LIGHT_GRAY),
            ('PADDING', (0, 0), (-1, -1), 6),
        ]))
        story.append(metrics_table)
        
        # Confidence badge
        conf_text = f"Confidence: {confidence:.0%} ({'High' if confidence >= 0.75 else 'Medium'})"
        story.append(Spacer(1, 4))
        story.append(Paragraph(conf_text, self.styles['TrustStatement']))
        
        return story
    
    def _render_drivers(self, data: Dict) -> list:
        """Render performance drivers."""
        story = []
        
        story.append(Paragraph("What's Driving Performance", self.styles['SectionHead']))
        
        drivers = data.get('drivers', [
            {'name': 'Seasonality Tailwind', 'impact': '+12%', 'confidence': 'High', 'source': 'Market'},
            {'name': 'Pool Amenity Premium', 'impact': '+10%', 'confidence': 'Medium', 'source': 'Market'},
            {'name': 'Operator Performance Delta', 'impact': '+6%', 'confidence': 'High', 'source': 'Internal'},
            {'name': 'Platform Demand Bias', 'impact': '+4%', 'confidence': 'Medium', 'source': 'Market'},
        ])
        
        driver_data = [['Driver', 'Impact', 'Confidence', 'Source']]
        for d in drivers:
            driver_data.append([
                d['name'],
                d['impact'],
                d['confidence'],
                d['source'],
            ])
        
        driver_table = Table(driver_data, colWidths=[2.2*inch, 0.8*inch, 1*inch, 0.9*inch])
        driver_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), Colors.SLATE),
            ('TEXTCOLOR', (0, 0), (-1, 0), Colors.WHITE),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
            ('ALIGN', (0, 1), (0, -1), 'LEFT'),
            ('GRID', (0, 0), (-1, -1), 0.5, Colors.LIGHT_GRAY),
            ('PADDING', (0, 0), (-1, -1), 5),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [Colors.WHITE, Colors.VERY_LIGHT]),
        ]))
        story.append(driver_table)
        
        return story
    
    def _render_page2_header(self, data: Dict) -> list:
        """Render Page 2 header."""
        story = []
        
        address = data.get('address', '123 Example Street')
        story.append(Paragraph(f"<b>{address}</b> — Context & Analysis", self.styles['PropertyAddress']))
        story.append(HRFlowable(width="100%", thickness=1, color=Colors.LIGHT_GRAY))
        story.append(Spacer(1, 8))
        
        return story
    
    def _render_operator_context(self, data: Dict) -> list:
        """Render operator performance context."""
        story = []
        
        story.append(Paragraph("Operator Performance Snapshot", self.styles['SectionHead']))
        
        op = data.get('operator_context', {})
        portfolio = op.get('portfolio_size_in_market', 18)
        adr_delta = op.get('adr_vs_market_pct', 0.12)
        occ_delta = op.get('occupancy_vs_market_pct', 0.06)
        similarity = op.get('amenity_mix_similarity', 0.81)
        
        op_data = [
            ['Metric', 'Value'],
            ['Portfolio in market', f'{portfolio} homes'],
            ['Observed ADR vs market', f'+{adr_delta:.0%}'],
            ['Observed occupancy vs market', f'+{occ_delta:.0%}'],
            ['Amenity mix similarity', f'{similarity:.0%}'],
        ]
        
        op_table = Table(op_data, colWidths=[2.5*inch, 2*inch])
        op_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), Colors.NAVY),
            ('TEXTCOLOR', (0, 0), (-1, 0), Colors.WHITE),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('ALIGN', (1, 1), (1, -1), 'RIGHT'),
            ('GRID', (0, 0), (-1, -1), 0.5, Colors.LIGHT_GRAY),
            ('PADDING', (0, 0), (-1, -1), 5),
        ]))
        story.append(op_table)
        
        # Trust statement
        trust = op.get('trust_statement', 
            "Projections reflect current operator performance in comparable properties they manage locally."
        )
        story.append(Spacer(1, 4))
        story.append(Paragraph(f"<i>{trust}</i>", self.styles['TrustStatement']))
        
        return story
    
    def _render_comparable_context(self, data: Dict) -> list:
        """Render comparable property context."""
        story = []
        
        story.append(Paragraph("Comparable Context", self.styles['SectionHead']))
        
        comp = data.get('comparable_context', {})
        
        comp_data = [
            ['Source', 'Count', 'ADR Range', 'Notes'],
            [
                'Internal (portfolio)',
                str(comp.get('internal_comp_count', 5)),
                '$280 – $350',
                'Same operator',
            ],
            [
                'External (market)',
                str(comp.get('external_comp_count', 12)),
                '$260 – $380',
                'Similar properties',
            ],
        ]
        
        comp_table = Table(comp_data, colWidths=[1.5*inch, 0.8*inch, 1.2*inch, 1.4*inch])
        comp_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), Colors.SLATE),
            ('TEXTCOLOR', (0, 0), (-1, 0), Colors.WHITE),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('ALIGN', (1, 0), (2, -1), 'CENTER'),
            ('GRID', (0, 0), (-1, -1), 0.5, Colors.LIGHT_GRAY),
            ('PADDING', (0, 0), (-1, -1), 5),
        ]))
        story.append(comp_table)
        
        # Booking pace
        pace = comp.get('booking_pace_vs_market', 'ahead')
        story.append(Spacer(1, 4))
        story.append(Paragraph(f"<i>Booking pace: {pace} of market average</i>", self.styles['TrustStatement']))
        
        return story
    
    def _render_risks(self, data: Dict) -> list:
        """Render risk factors."""
        story = []
        
        story.append(Paragraph("Primary Sensitivities", self.styles['SectionHead']))
        
        risks = data.get('risks', [
            {'description': 'ADR sensitivity to demand slowdown', 'impact': 'Medium', 'confidence': 'High'},
            {'description': 'Occupancy sensitivity in shoulder season', 'impact': 'Low', 'confidence': 'Medium'},
        ])
        
        risk_data = [['Risk Factor', 'Impact', 'Confidence']]
        for r in risks:
            risk_data.append([
                r['description'],
                r['impact'],
                r['confidence'],
            ])
        
        risk_table = Table(risk_data, colWidths=[3.5*inch, 0.8*inch, 0.9*inch])
        risk_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), Colors.SLATE),
            ('TEXTCOLOR', (0, 0), (-1, 0), Colors.WHITE),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
            ('GRID', (0, 0), (-1, -1), 0.5, Colors.LIGHT_GRAY),
            ('PADDING', (0, 0), (-1, -1), 5),
        ]))
        story.append(risk_table)
        
        return story
    
    def _render_recommendation(self, data: Dict) -> list:
        """Render bottom-line recommendation."""
        story = []
        
        story.append(Spacer(1, 12))
        
        rec = data.get('recommendation',
            "This property is a strong STR candidate under current market conditions "
            "and aligns well with the operator's demonstrated execution capabilities."
        )
        
        # Recommendation box
        rec_data = [[
            Paragraph(f"<b>RECOMMENDATION:</b> {rec}", self.styles['SynopsisBody'])
        ]]
        
        rec_table = Table(rec_data, colWidths=[6.3*inch])
        rec_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), Colors.NAVY),
            ('TEXTCOLOR', (0, 0), (-1, -1), Colors.WHITE),
            ('PADDING', (0, 0), (-1, -1), 12),
        ]))
        story.append(rec_table)
        
        # Disclaimer
        story.append(Spacer(1, 12))
        disclaimer = (
            "This synopsis is based on market-derived signals and observed operator performance. "
            "Projections include confidence bands reflecting data quality. Verify assumptions before investing."
        )
        story.append(Paragraph(disclaimer, self.styles['TrustStatement']))
        
        return story


# =============================================================================
# CONVENIENCE
# =============================================================================

def render_property_synopsis_pdf(
    synopsis_data: Dict[str, Any],
    output_path: str,
    branding: Optional[Dict] = None,
) -> str:
    """
    Render a property synopsis to PDF.
    
    Example:
        render_property_synopsis_pdf(
            {
                'address': '842 Gulf Shore Dr',
                'market_name': '30A Beaches',
                'bedrooms': 4,
                'bathrooms': 3.5,
                'sleeps': 10,
                'key_amenities': ['Pool', 'Gulf View', 'Hot Tub'],
                'revenue_outlook': {'low': 165000, 'base': 185000, 'high': 210000},
                ...
            },
            '/path/to/output.pdf'
        )
    """
    renderer = PropertySynopsisPDFRenderer()
    return renderer.render(synopsis_data, output_path, branding)
