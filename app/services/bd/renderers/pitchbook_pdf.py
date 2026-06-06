"""
PitchBook PDF Renderer.

Transforms InvestmentSynopsis → Professional PDF.

This is a DUMB renderer:
- Page layout
- Typography
- Charts (simple)
- Section ordering

It MUST NOT:
- Call executors
- Infer data
- Make decisions
- Load context
"""

from datetime import datetime
from io import BytesIO
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, Image, HRFlowable
)
from reportlab.graphics.shapes import Drawing, Rect
from reportlab.graphics.charts.barcharts import VerticalBarChart

from app.domain.bd import InvestmentSynopsis, TightenedScenario


# =============================================================================
# STYLES
# =============================================================================

class PitchBookStyles:
    """Pre-defined styles for pitch book."""
    
    @staticmethod
    def get_styles():
        styles = getSampleStyleSheet()
        
        # Title
        styles.add(ParagraphStyle(
            name='PitchTitle',
            parent=styles['Heading1'],
            fontSize=24,
            spaceAfter=20,
            textColor=colors.HexColor('#1a365d'),
            alignment=1,  # Center
        ))
        
        # Section Header
        styles.add(ParagraphStyle(
            name='SectionHeader',
            parent=styles['Heading2'],
            fontSize=16,
            spaceBefore=20,
            spaceAfter=10,
            textColor=colors.HexColor('#2d3748'),
        ))
        
        # Subsection
        styles.add(ParagraphStyle(
            name='Subsection',
            parent=styles['Heading3'],
            fontSize=12,
            spaceBefore=10,
            spaceAfter=6,
            textColor=colors.HexColor('#4a5568'),
        ))
        
        # Body text
        styles.add(ParagraphStyle(
            name='BodyText',
            parent=styles['Normal'],
            fontSize=10,
            spaceAfter=8,
            textColor=colors.HexColor('#2d3748'),
            leading=14,
        ))
        
        # Key metric
        styles.add(ParagraphStyle(
            name='KeyMetric',
            parent=styles['Normal'],
            fontSize=18,
            textColor=colors.HexColor('#2b6cb0'),
            alignment=1,
        ))
        
        # Disclaimer
        styles.add(ParagraphStyle(
            name='Disclaimer',
            parent=styles['Normal'],
            fontSize=8,
            textColor=colors.HexColor('#718096'),
            spaceBefore=10,
        ))
        
        return styles


# =============================================================================
# RENDERER
# =============================================================================

class PitchBookPDFRenderer:
    """
    Renders InvestmentSynopsis to PDF.
    
    Supported styles:
    - standard: Full professional layout
    - realtor: Clean, conservative focus
    - homeowner: Friendly, upside focus
    """
    
    def __init__(self, style: str = "standard"):
        self.style = style
        self.styles = PitchBookStyles.get_styles()
    
    def render(self, synopsis: InvestmentSynopsis) -> bytes:
        """
        Render synopsis to PDF bytes.
        
        Input: InvestmentSynopsis (structured data)
        Output: PDF bytes
        """
        buffer = BytesIO()
        
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            rightMargin=0.75*inch,
            leftMargin=0.75*inch,
            topMargin=0.75*inch,
            bottomMargin=0.75*inch,
        )
        
        # Build story (list of flowables)
        story = []
        
        # Cover / Title
        story.extend(self._build_cover(synopsis))
        
        # Property Overview
        story.extend(self._build_property_section(synopsis))
        
        # Market Context
        if synopsis.market_context:
            story.extend(self._build_market_section(synopsis))
        
        # Revenue Projections
        story.extend(self._build_projection_section(synopsis))
        
        # Upside Analysis (if shown)
        if synopsis.upside_drivers:
            story.extend(self._build_upside_section(synopsis))
        
        # Risk Factors (if shown)
        if synopsis.risk_factors:
            story.extend(self._build_risk_section(synopsis))
        
        # Assumptions
        if synopsis.tightened_assumptions or synopsis.original_assumptions:
            story.extend(self._build_assumptions_section(synopsis))
        
        # Disclaimer (always)
        story.extend(self._build_disclaimer(synopsis))
        
        # Build PDF
        doc.build(story)
        
        return buffer.getvalue()
    
    def _build_cover(self, synopsis: InvestmentSynopsis) -> list:
        """Build cover/title section."""
        story = []
        
        # Title
        prop = synopsis.property_snapshot
        title = prop.get("description", "Investment Analysis")
        story.append(Paragraph(title, self.styles['PitchTitle']))
        
        # Address
        if prop.get("address"):
            story.append(Paragraph(prop["address"], self.styles['BodyText']))
        
        story.append(Spacer(1, 20))
        
        # Key metric highlight
        if synopsis.tightened_scenario:
            story.append(Paragraph(
                f"Projected Annual Revenue",
                self.styles['Subsection']
            ))
            story.append(Paragraph(
                synopsis.tightened_scenario.revenue_range_formatted,
                self.styles['KeyMetric']
            ))
            story.append(Spacer(1, 10))
            story.append(Paragraph(
                f"Monthly: {synopsis.tightened_scenario.monthly_range_formatted}",
                self.styles['BodyText']
            ))
        
        story.append(Spacer(1, 30))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#e2e8f0')))
        
        return story
    
    def _build_property_section(self, synopsis: InvestmentSynopsis) -> list:
        """Build property overview section."""
        story = []
        
        story.append(Paragraph("Property Overview", self.styles['SectionHeader']))
        
        prop = synopsis.property_snapshot
        
        # Property details table
        data = []
        if prop.get("beds"):
            data.append(["Bedrooms", str(prop["beds"])])
        if prop.get("baths"):
            data.append(["Bathrooms", str(prop["baths"])])
        if prop.get("sqft"):
            data.append(["Square Feet", f"{prop['sqft']:,}"])
        if prop.get("property_type"):
            data.append(["Property Type", prop["property_type"]])
        
        if data:
            table = Table(data, colWidths=[2*inch, 3*inch])
            table.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 0), (-1, -1), 10),
                ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#4a5568')),
                ('TEXTCOLOR', (1, 0), (1, -1), colors.HexColor('#2d3748')),
                ('ALIGN', (0, 0), (0, -1), 'LEFT'),
                ('ALIGN', (1, 0), (1, -1), 'LEFT'),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ]))
            story.append(table)
        
        story.append(Spacer(1, 15))
        
        return story
    
    def _build_market_section(self, synopsis: InvestmentSynopsis) -> list:
        """Build market context section."""
        story = []
        
        story.append(Paragraph("Market Context", self.styles['SectionHeader']))
        
        market = synopsis.market_context
        
        if market.get("summary"):
            story.append(Paragraph(market["summary"], self.styles['BodyText']))
        
        if market.get("market_name"):
            story.append(Paragraph(
                f"Market: {market['market_name']}",
                self.styles['BodyText']
            ))
        
        if synopsis.comparable_count:
            story.append(Paragraph(
                f"Analysis based on {synopsis.comparable_count} comparable properties.",
                self.styles['BodyText']
            ))
        
        story.append(Spacer(1, 15))
        
        return story
    
    def _build_projection_section(self, synopsis: InvestmentSynopsis) -> list:
        """Build revenue projection section."""
        story = []
        
        story.append(Paragraph("Revenue Projections", self.styles['SectionHeader']))
        
        # Tightened scenario (primary display)
        if synopsis.tightened_scenario:
            ts = synopsis.tightened_scenario
            
            story.append(Paragraph("Adjusted Projection", self.styles['Subsection']))
            
            data = [
                ["Annual Revenue", ts.revenue_range_formatted],
                ["Monthly Revenue", ts.monthly_range_formatted],
                ["Confidence", ts.confidence_band.value.title()],
            ]
            
            table = Table(data, colWidths=[2.5*inch, 3*inch])
            table.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 0), (-1, -1), 11),
                ('FONTNAME', (1, 0), (1, -1), 'Helvetica-Bold'),
                ('TEXTCOLOR', (1, 0), (1, 0), colors.HexColor('#2b6cb0')),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
                ('TOPPADDING', (0, 0), (-1, -1), 10),
                ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f7fafc')),
            ]))
            story.append(table)
            
            # Constraints applied
            if ts.constraints_applied:
                story.append(Spacer(1, 10))
                story.append(Paragraph("Adjustments Applied:", self.styles['Subsection']))
                for constraint in ts.constraints_applied:
                    story.append(Paragraph(f"• {constraint}", self.styles['BodyText']))
        
        # Scenario comparison (if multiple shown)
        scenarios_to_show = []
        if synopsis.conservative_scenario:
            scenarios_to_show.append(("Conservative", synopsis.conservative_scenario))
        if synopsis.baseline_scenario:
            scenarios_to_show.append(("Baseline", synopsis.baseline_scenario))
        if synopsis.optimized_scenario:
            scenarios_to_show.append(("Optimized", synopsis.optimized_scenario))
        
        if len(scenarios_to_show) > 1:
            story.append(Spacer(1, 15))
            story.append(Paragraph("Scenario Comparison", self.styles['Subsection']))
            
            data = [["Scenario", "Annual Revenue", "Confidence"]]
            for name, scenario in scenarios_to_show:
                if scenario.annual_revenue:
                    data.append([
                        name,
                        scenario.annual_revenue.format_currency(),
                        scenario.confidence_band.value.title()
                    ])
            
            if len(data) > 1:
                table = Table(data, colWidths=[1.5*inch, 2.5*inch, 1.5*inch])
                table.setStyle(TableStyle([
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, -1), 10),
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#edf2f7')),
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                    ('TOPPADDING', (0, 0), (-1, -1), 8),
                ]))
                story.append(table)
        
        story.append(Spacer(1, 15))
        
        return story
    
    def _build_upside_section(self, synopsis: InvestmentSynopsis) -> list:
        """Build upside analysis section."""
        story = []
        
        story.append(Paragraph("Upside Opportunities", self.styles['SectionHeader']))
        
        for driver in synopsis.upside_drivers:
            story.append(Paragraph(f"• {driver}", self.styles['BodyText']))
        
        story.append(Spacer(1, 15))
        
        return story
    
    def _build_risk_section(self, synopsis: InvestmentSynopsis) -> list:
        """Build risk factors section."""
        story = []
        
        story.append(Paragraph("Risk Considerations", self.styles['SectionHeader']))
        
        for risk in synopsis.risk_factors:
            story.append(Paragraph(f"• {risk}", self.styles['BodyText']))
        
        story.append(Spacer(1, 15))
        
        return story
    
    def _build_assumptions_section(self, synopsis: InvestmentSynopsis) -> list:
        """Build assumptions section."""
        story = []
        
        story.append(Paragraph("Assumptions", self.styles['SectionHeader']))
        
        if synopsis.tightened_assumptions:
            story.append(Paragraph("Applied Constraints:", self.styles['Subsection']))
            for assumption in synopsis.tightened_assumptions:
                story.append(Paragraph(f"• {assumption}", self.styles['BodyText']))
        
        if synopsis.original_assumptions:
            story.append(Paragraph("Base Assumptions:", self.styles['Subsection']))
            for assumption in synopsis.original_assumptions[:5]:  # Limit to 5
                story.append(Paragraph(f"• {assumption}", self.styles['BodyText']))
        
        story.append(Spacer(1, 15))
        
        return story
    
    def _build_disclaimer(self, synopsis: InvestmentSynopsis) -> list:
        """Build disclaimer section (always included)."""
        story = []
        
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#e2e8f0')))
        story.append(Spacer(1, 10))
        
        disclaimers = [
            "This analysis is provided for informational purposes only and does not constitute a guarantee of rental income.",
            "Projections are based on comparable properties and market data. Actual results may vary based on property condition, management, and market conditions.",
            f"Generated on {synopsis.generated_at.strftime('%B %d, %Y')}.",
        ]
        
        for disclaimer in disclaimers:
            story.append(Paragraph(disclaimer, self.styles['Disclaimer']))
        
        return story


# =============================================================================
# FACTORY
# =============================================================================

def render_pitchbook_pdf(
    synopsis: InvestmentSynopsis,
    style: str = "standard",
) -> bytes:
    """
    Render investment synopsis to PDF.
    
    Args:
        synopsis: InvestmentSynopsis object
        style: "standard", "realtor", or "homeowner"
        
    Returns:
        PDF bytes
    """
    renderer = PitchBookPDFRenderer(style=style)
    return renderer.render(synopsis)
