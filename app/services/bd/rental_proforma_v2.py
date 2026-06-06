"""
Rental Projections Pro Forma Renderer v2.

Generates professional rental pro forma PDFs with:
- Clean, non-overlapping layout
- Signal-driven projections
- Market analysis integration
- Operator branding with logo support
- Monthly ADR & occupancy estimates
- Sensitivity analysis

Data sources:
- Property listings (MLS, scraped)
- Market signals (seasonality, demand)
- Operator performance data
- Amenity lift calculations
"""

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor, white, black
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, Image, KeepTogether
)
from reportlab.graphics.shapes import Drawing, Rect, String

from datetime import datetime
from typing import Dict, Any, List, Optional
from pathlib import Path
import os


# =============================================================================
# COLORS
# =============================================================================

class Colors:
    """Professional color palette."""
    PRIMARY = HexColor("#1a7f7f")      # Teal
    PRIMARY_DARK = HexColor("#156666")
    PRIMARY_LIGHT = HexColor("#e8f4f4")
    SECONDARY = HexColor("#2c3e50")    # Dark blue
    ACCENT = HexColor("#c9a227")       # Gold
    TEXT_DARK = HexColor("#2c3e50")
    TEXT_MEDIUM = HexColor("#5a6c7d")
    TEXT_LIGHT = HexColor("#8fa4b8")
    BORDER = HexColor("#d1dce5")
    ROW_ALT = HexColor("#f8fafb")
    WHITE = white
    SUCCESS = HexColor("#27ae60")
    WARNING = HexColor("#f39c12")


# =============================================================================
# STYLES
# =============================================================================

def create_styles():
    """Create document styles."""
    styles = getSampleStyleSheet()
    
    styles.add(ParagraphStyle(
        name='DocTitle',
        fontSize=22,
        textColor=Colors.PRIMARY_DARK,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold',
        spaceAfter=2,
    ))
    
    styles.add(ParagraphStyle(
        name='DocSubtitle',
        fontSize=13,
        textColor=Colors.TEXT_MEDIUM,
        alignment=TA_CENTER,
        fontName='Helvetica',
        spaceAfter=16,
    ))
    
    styles.add(ParagraphStyle(
        name='SectionHeader',
        fontSize=12,
        textColor=Colors.PRIMARY_DARK,
        fontName='Helvetica-Bold',
        spaceBefore=14,
        spaceAfter=8,
    ))
    
    styles.add(ParagraphStyle(
        name='LargeMetric',
        fontSize=26,
        textColor=Colors.PRIMARY_DARK,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold',
    ))
    
    styles.add(ParagraphStyle(
        name='MetricLabel',
        fontSize=9,
        textColor=Colors.TEXT_MEDIUM,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold',
        spaceAfter=2,
    ))
    
    styles.add(ParagraphStyle(
        name='MetricSubtext',
        fontSize=8,
        textColor=Colors.TEXT_LIGHT,
        alignment=TA_CENTER,
        fontName='Helvetica',
    ))
    
    styles.add(ParagraphStyle(
        name='SmallMetric',
        fontSize=16,
        textColor=Colors.PRIMARY_DARK,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold',
    ))
    
    styles.add(ParagraphStyle(
        name='ProFormaBody',
        fontSize=9,
        textColor=Colors.TEXT_DARK,
        fontName='Helvetica',
        leading=12,
    ))
    
    styles.add(ParagraphStyle(
        name='PreparedByName',
        fontSize=11,
        textColor=Colors.TEXT_DARK,
        fontName='Helvetica-Bold',
    ))
    
    styles.add(ParagraphStyle(
        name='ContactInfo',
        fontSize=9,
        textColor=Colors.TEXT_MEDIUM,
        fontName='Helvetica',
        spaceAfter=2,
    ))
    
    styles.add(ParagraphStyle(
        name='Disclaimer',
        fontSize=7,
        textColor=Colors.TEXT_LIGHT,
        fontName='Helvetica-Oblique',
        alignment=TA_CENTER,
    ))
    
    styles.add(ParagraphStyle(
        name='PageHeader',
        fontSize=18,
        textColor=Colors.PRIMARY_DARK,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold',
        spaceAfter=4,
    ))
    
    return styles


# =============================================================================
# PRO FORMA DATA MODEL
# =============================================================================

class ProFormaData:
    """
    Data model for rental pro forma.
    
    Can be populated from:
    - Property listing data
    - Market signals
    - Operator performance
    """
    
    def __init__(self, data: Dict[str, Any]):
        # Property info
        self.address = data.get('address', '')
        self.bedrooms = data.get('bedrooms', 0)
        self.bathrooms = data.get('bathrooms', 0)
        self.sqft = data.get('sqft', 0)
        self.property_value = data.get('property_value', 0)
        self.key_attributes = data.get('key_attributes', '')
        self.property_link = data.get('property_link', '')
        
        # Revenue projections
        self.gross_revenue = data.get('gross_revenue', 0)
        self.gross_low = data.get('gross_revenue_low', self.gross_revenue * 0.8)
        self.gross_high = data.get('gross_revenue_high', self.gross_revenue * 1.2)
        
        self.net_revenue = data.get('net_revenue', self.gross_revenue * 0.8)
        self.net_low = data.get('net_revenue_low', self.net_revenue * 0.8)
        self.net_high = data.get('net_revenue_high', self.net_revenue * 1.2)
        
        self.commission_pct = data.get('commission_pct', 20)
        
        # Key metrics
        self.nights_rented = data.get('nights_rented', 0)
        self.owner_days = data.get('owner_days', 0)
        self.occupancy = data.get('occupancy', 0)
        self.adr = data.get('adr', 0)
        
        # Monthly data
        self.monthly_revenue = data.get('monthly_revenue', {})
        self.monthly_occupancy = data.get('monthly_occupancy', {})
        self.monthly_adr = data.get('monthly_adr', {})
        
        # Seasonal breakdown
        self.seasons = data.get('seasons', [])
        
        # Market analysis
        self.market_name = data.get('market_name', '')
        self.market_phase = data.get('market_phase', '')
        self.confidence = data.get('confidence', 0.75)
        
        # Signal attribution
        self.drivers = data.get('drivers', [])


# =============================================================================
# PDF RENDERER
# =============================================================================

class RentalProFormaRenderer:
    """
    Renders professional rental pro forma PDFs.
    
    Features:
    - Clean, non-overlapping layout
    - Logo support
    - Signal-driven data integration
    - Sensitivity analysis
    """
    
    def __init__(self):
        self.styles = create_styles()
        self.page_width, self.page_height = letter
        self.margin = 0.5 * inch
        self.content_width = self.page_width - (2 * self.margin)
    
    def render(
        self,
        data: Dict[str, Any],
        output_path: str,
        branding: Optional[Dict] = None,
    ) -> str:
        """
        Render a rental pro forma to PDF.
        
        Args:
            data: Pro forma data dictionary
            output_path: Where to save the PDF
            branding: Operator branding (logo_path, company_name, etc.)
        
        Returns:
            Path to generated PDF
        """
        pf = ProFormaData(data)
        branding = branding or {}
        
        doc = SimpleDocTemplate(
            output_path,
            pagesize=letter,
            rightMargin=self.margin,
            leftMargin=self.margin,
            topMargin=0.4 * inch,
            bottomMargin=0.4 * inch,
        )
        
        story = []
        
        # === PAGE 1: Summary ===
        story.extend(self._render_page1(pf, branding))
        
        story.append(PageBreak())
        
        # === PAGE 2: Details ===
        story.extend(self._render_page2(pf, branding))
        
        doc.build(story)
        
        return output_path
    
    # =========================================================================
    # PAGE 1: SUMMARY
    # =========================================================================
    
    def _render_page1(self, pf: ProFormaData, branding: Dict) -> list:
        """Render summary page."""
        story = []
        
        # Header with logo
        story.extend(self._render_header(pf, branding))
        
        # Main revenue boxes
        story.extend(self._render_revenue_summary(pf))
        
        # Key metrics strip
        story.extend(self._render_metrics_strip(pf))
        
        # Monthly revenue section
        story.extend(self._render_monthly_revenue(pf))
        
        # Occupancy section  
        story.extend(self._render_occupancy_section(pf))
        
        # ADR section
        story.extend(self._render_adr_section(pf))
        
        # Bottom: Contact + Sensitivity
        story.extend(self._render_page1_bottom(pf, branding))
        
        return story
    
    def _render_header(self, pf: ProFormaData, branding: Dict) -> list:
        """Render header with optional logo."""
        story = []
        
        # Build header row
        logo_cell = ""
        if branding.get('logo_path') and os.path.exists(branding['logo_path']):
            try:
                logo_cell = Image(branding['logo_path'], width=1.5*inch, height=0.6*inch)
            except:
                logo_cell = Paragraph(
                    f"<b>{branding.get('company_name', '')}</b>",
                    self.styles['PreparedByName']
                )
        elif branding.get('company_name'):
            logo_cell = Paragraph(
                f"<b>{branding['company_name']}</b>",
                self.styles['PreparedByName']
            )
        
        # Title
        title_cell = [
            Paragraph("Rental Projections Pro Forma", self.styles['DocTitle']),
            Paragraph(pf.address, self.styles['DocSubtitle']),
        ]
        
        header_data = [[logo_cell, title_cell, ""]]
        header_table = Table(header_data, colWidths=[1.8*inch, 4.4*inch, 1.3*inch])
        header_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ALIGN', (0, 0), (0, 0), 'LEFT'),
            ('ALIGN', (1, 0), (1, 0), 'CENTER'),
        ]))
        story.append(header_table)
        
        story.append(Spacer(1, 8))
        
        return story
    
    def _render_revenue_summary(self, pf: ProFormaData) -> list:
        """Render main revenue boxes."""
        story = []
        
        # Gross Revenue Box
        gross_content = [
            Paragraph("Total Projected Gross Revenue", self.styles['MetricLabel']),
            Spacer(1, 4),
            Paragraph(f"${pf.gross_revenue:,.0f}", self.styles['LargeMetric']),
            Spacer(1, 4),
            Paragraph(
                f"Range: ${pf.gross_low:,.0f} – ${pf.gross_high:,.0f}",
                self.styles['MetricSubtext']
            ),
            Paragraph(
                "Based on market conditions and pricing strategy",
                self.styles['MetricSubtext']
            ),
        ]
        
        # Net Revenue Box
        net_content = [
            Paragraph("Total Projected Net Proceeds", self.styles['MetricLabel']),
            Spacer(1, 4),
            Paragraph(f"${pf.net_revenue:,.0f}", self.styles['LargeMetric']),
            Spacer(1, 4),
            Paragraph(
                f"Range: ${pf.net_low:,.0f} – ${pf.net_high:,.0f}",
                self.styles['MetricSubtext']
            ),
            Paragraph(
                f"Net of {pf.commission_pct}% management commission",
                self.styles['MetricSubtext']
            ),
        ]
        
        revenue_data = [[gross_content, net_content]]
        revenue_table = Table(revenue_data, colWidths=[3.65*inch, 3.65*inch])
        revenue_table.setStyle(TableStyle([
            ('BOX', (0, 0), (0, 0), 1, Colors.BORDER),
            ('BOX', (1, 0), (1, 0), 1, Colors.BORDER),
            ('BACKGROUND', (0, 0), (0, 0), Colors.PRIMARY_LIGHT),
            ('BACKGROUND', (1, 0), (1, 0), Colors.PRIMARY_LIGHT),
            ('PADDING', (0, 0), (-1, -1), 12),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))
        story.append(revenue_table)
        
        story.append(Spacer(1, 10))
        
        return story
    
    def _render_metrics_strip(self, pf: ProFormaData) -> list:
        """Render key metrics in a horizontal strip."""
        story = []
        
        metrics = [
            (f"{pf.nights_rented}", "Projected Nights"),
            (f"{pf.owner_days}", "Owner Days"),
            (f"{pf.occupancy:.0%}", "Occupancy"),
            (f"${pf.adr:,.0f}", "Avg Nightly Rate"),
        ]
        
        cells = []
        for value, label in metrics:
            cells.append([
                Paragraph(value, self.styles['SmallMetric']),
                Paragraph(label, self.styles['MetricLabel']),
            ])
        
        metrics_table = Table([cells], colWidths=[1.825*inch] * 4)
        metrics_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('BOX', (0, 0), (-1, -1), 1, Colors.BORDER),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, Colors.BORDER),
            ('BACKGROUND', (0, 0), (-1, -1), Colors.WHITE),
            ('PADDING', (0, 0), (-1, -1), 8),
        ]))
        story.append(metrics_table)
        
        story.append(Spacer(1, 12))
        
        return story
    
    def _render_monthly_revenue(self, pf: ProFormaData) -> list:
        """Render monthly revenue chart as table."""
        story = []
        
        story.append(Paragraph(
            f"Monthly Gross Revenue: ${pf.gross_revenue:,.0f}",
            self.styles['SectionHeader']
        ))
        
        months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 
                  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
        
        # Get monthly values
        values = [pf.monthly_revenue.get(m, 0) for m in months]
        max_val = max(values) if max(values) > 0 else 40000
        
        # Format values
        value_row = []
        for v in values:
            if v > 0:
                value_row.append(Paragraph(
                    f"<font size='7'>${v:,.0f}</font>",
                    self.styles['ProFormaBody']
                ))
            else:
                value_row.append(Paragraph(
                    "<font size='7' color='#8fa4b8'>$0</font>",
                    self.styles['ProFormaBody']
                ))
        
        # Visual bar representation (simplified)
        bar_row = []
        for v in values:
            height = int((v / max_val) * 4) if max_val > 0 else 0
            bar = "█" * height if height > 0 else "·"
            bar_row.append(Paragraph(
                f"<font size='10' color='#1a7f7f'>{bar}</font>",
                self.styles['ProFormaBody']
            ))
        
        month_row = [Paragraph(f"<font size='7'>{m}</font>", self.styles['ProFormaBody']) for m in months]
        
        chart_data = [value_row, bar_row, month_row]
        
        col_width = self.content_width / 12
        chart_table = Table(chart_data, colWidths=[col_width] * 12)
        chart_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
            ('VALIGN', (0, 2), (-1, 2), 'TOP'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
            ('TOPPADDING', (0, 0), (-1, -1), 2),
        ]))
        story.append(chart_table)
        
        story.append(Spacer(1, 8))
        
        return story
    
    def _render_occupancy_section(self, pf: ProFormaData) -> list:
        """Render occupancy section."""
        story = []
        
        # Header with overall occupancy
        header_data = [[
            Paragraph(f"Occupancy: {pf.occupancy:.0%}", self.styles['SectionHeader']),
            Paragraph(
                "<font size='7' color='#1a7f7f'>■</font> Rented  "
                "<font size='7' color='#8fa4b8'>■</font> Available",
                self.styles['ProFormaBody']
            ),
        ]]
        header_table = Table(header_data, colWidths=[2*inch, 5.3*inch])
        header_table.setStyle(TableStyle([
            ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        story.append(header_table)
        
        months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 
                  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
        
        # Occupancy percentages
        occ_row = []
        avail_row = []
        for m in months:
            occ = pf.monthly_occupancy.get(m, 0)
            occ_row.append(Paragraph(
                f"<font size='7' color='#1a7f7f'><b>{occ:.0%}</b></font>",
                self.styles['ProFormaBody']
            ))
            avail = 1 - occ
            if avail > 0:
                avail_row.append(Paragraph(
                    f"<font size='7' color='#8fa4b8'>{avail:.0%}</font>",
                    self.styles['ProFormaBody']
                ))
            else:
                avail_row.append("")
        
        month_row = [Paragraph(f"<font size='7'>{m}</font>", self.styles['ProFormaBody']) for m in months]
        
        occ_data = [occ_row, avail_row, month_row]
        
        col_width = self.content_width / 12
        occ_table = Table(occ_data, colWidths=[col_width] * 12)
        occ_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
            ('TOPPADDING', (0, 0), (-1, -1), 1),
        ]))
        story.append(occ_table)
        
        story.append(Spacer(1, 8))
        
        return story
    
    def _render_adr_section(self, pf: ProFormaData) -> list:
        """Render ADR section."""
        story = []
        
        story.append(Paragraph(
            f"Average Daily Rate: ${pf.adr:,.0f}",
            self.styles['SectionHeader']
        ))
        
        months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 
                  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
        
        adr_row = []
        for m in months:
            adr = pf.monthly_adr.get(m, 0)
            if adr > 0:
                adr_row.append(Paragraph(
                    f"<font size='7'><b>${adr:,.0f}</b></font>",
                    self.styles['ProFormaBody']
                ))
            else:
                adr_row.append(Paragraph(
                    "<font size='7' color='#8fa4b8'>—</font>",
                    self.styles['ProFormaBody']
                ))
        
        month_row = [Paragraph(f"<font size='7'>{m}</font>", self.styles['ProFormaBody']) for m in months]
        
        adr_data = [adr_row, month_row]
        
        col_width = self.content_width / 12
        adr_table = Table(adr_data, colWidths=[col_width] * 12)
        adr_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
            ('TOPPADDING', (0, 0), (-1, -1), 1),
        ]))
        story.append(adr_table)
        
        story.append(Spacer(1, 10))
        
        return story
    
    def _render_page1_bottom(self, pf: ProFormaData, branding: Dict) -> list:
        """Render bottom section with contact and sensitivity."""
        story = []
        
        # Left: Prepared By
        prepared_content = []
        prepared_content.append(Paragraph(
            "<b>Rental Projections Prepared By</b>",
            self.styles['MetricLabel']
        ))
        prepared_content.append(Spacer(1, 6))
        
        if branding.get('prepared_by'):
            prepared_content.append(Paragraph(
                branding['prepared_by'],
                self.styles['PreparedByName']
            ))
        if branding.get('email'):
            prepared_content.append(Paragraph(
                branding['email'],
                self.styles['ContactInfo']
            ))
        if branding.get('phone'):
            prepared_content.append(Paragraph(
                branding['phone'],
                self.styles['ContactInfo']
            ))
        if branding.get('website'):
            prepared_content.append(Paragraph(
                branding['website'],
                self.styles['ContactInfo']
            ))
        
        prepared_content.append(Spacer(1, 6))
        prepared_content.append(Paragraph(
            datetime.now().strftime("%B %d, %Y"),
            self.styles['ContactInfo']
        ))
        
        # Right: Sensitivity Analysis
        sensitivity_content = []
        sensitivity_content.append(Paragraph(
            "<b>Sensitivity Analysis</b>",
            self.styles['MetricLabel']
        ))
        sensitivity_content.append(Spacer(1, 4))
        sensitivity_content.append(self._build_sensitivity_matrix(pf))
        
        bottom_data = [[prepared_content, sensitivity_content]]
        bottom_table = Table(bottom_data, colWidths=[2.3*inch, 5*inch])
        bottom_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
        ]))
        story.append(bottom_table)
        
        # Disclaimer
        story.append(Spacer(1, 12))
        if branding.get('disclaimer'):
            story.append(Paragraph(branding['disclaimer'], self.styles['Disclaimer']))
        else:
            story.append(Paragraph(
                "Projections are estimates based on market analysis and comparable properties. "
                "Actual results may vary based on market conditions, property management, and other factors.",
                self.styles['Disclaimer']
            ))
        
        return story
    
    def _build_sensitivity_matrix(self, pf: ProFormaData) -> Table:
        """Build sensitivity analysis matrix."""
        base = pf.gross_revenue
        variations = [0.8, 0.9, 1.0, 1.1, 1.2]
        pct_labels = ['80%', '90%', '100%', '110%', '120%']
        
        # Build matrix
        rows = []
        
        # Header row
        header = ['', ''] + pct_labels
        rows.append(header)
        
        # Sub-header
        sub_header = ['', ''] + ['Nights Rented →' if i == 2 else '' for i in range(5)]
        rows.append(sub_header)
        
        # Data rows
        for i, rate_mult in enumerate(variations):
            row = ['ADR ↓' if i == 2 else '', pct_labels[i]]
            for nights_mult in variations:
                val = base * rate_mult * nights_mult
                row.append(f"${val:,.0f}")
            rows.append(row)
        
        col_widths = [0.35*inch, 0.45*inch] + [0.7*inch] * 5
        
        sens_table = Table(rows, colWidths=col_widths)
        sens_table.setStyle(TableStyle([
            # Header styling
            ('SPAN', (2, 1), (6, 1)),
            ('ALIGN', (2, 1), (6, 1), 'CENTER'),
            ('FONTSIZE', (0, 0), (-1, -1), 7),
            
            # Column headers
            ('BACKGROUND', (2, 0), (-1, 0), Colors.PRIMARY),
            ('TEXTCOLOR', (2, 0), (-1, 0), Colors.WHITE),
            ('FONTNAME', (2, 0), (-1, 0), 'Helvetica-Bold'),
            
            # Row headers
            ('BACKGROUND', (1, 2), (1, -1), Colors.PRIMARY),
            ('TEXTCOLOR', (1, 2), (1, -1), Colors.WHITE),
            ('FONTNAME', (1, 2), (1, -1), 'Helvetica-Bold'),
            
            # Grid
            ('GRID', (1, 0), (-1, -1), 0.5, Colors.BORDER),
            
            # Center cell highlight (100%/100%)
            ('BACKGROUND', (4, 4), (4, 4), Colors.PRIMARY_LIGHT),
            ('FONTNAME', (4, 4), (4, 4), 'Helvetica-Bold'),
            
            # Alignment
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            
            # Padding
            ('PADDING', (0, 0), (-1, -1), 3),
        ]))
        
        return sens_table
    
    # =========================================================================
    # PAGE 2: DETAILS
    # =========================================================================
    
    def _render_page2(self, pf: ProFormaData, branding: Dict) -> list:
        """Render details page."""
        story = []
        
        # Header
        story.append(Paragraph("Rental Projections Pro Forma Details", self.styles['PageHeader']))
        story.append(Paragraph(pf.address, self.styles['DocSubtitle']))
        
        # Property details box
        story.extend(self._render_property_box(pf))
        
        # Monthly breakdown table
        story.extend(self._render_monthly_table(pf))
        
        # Market analysis (if available)
        if pf.market_name or pf.drivers:
            story.extend(self._render_market_analysis(pf))
        
        # Disclaimer
        story.append(Spacer(1, 12))
        story.append(Paragraph(
            "Projections are estimates based on market analysis, comparable properties, and seasonal patterns. "
            "Actual results may vary. Consult with a licensed professional before making investment decisions.",
            self.styles['Disclaimer']
        ))
        
        return story
    
    def _render_property_box(self, pf: ProFormaData) -> list:
        """Render property details box."""
        story = []
        
        props = [
            f"<b>Bedrooms:</b> {pf.bedrooms}",
            f"<b>Bathrooms:</b> {pf.bathrooms}",
            f"<b>Square Footage:</b> {pf.sqft:,}" if pf.sqft else "",
        ]
        props = [p for p in props if p]
        
        row1 = "    |    ".join(props)
        
        details_data = [
            [Paragraph(row1, self.styles['ProFormaBody'])],
        ]
        
        if pf.property_value:
            details_data.append([Paragraph(
                f"<b>Property Value / Listed Price:</b> ${pf.property_value:,.0f}",
                self.styles['ProFormaBody']
            )])
        
        if pf.key_attributes:
            details_data.append([Paragraph(
                f"<b>Key Attributes:</b> {pf.key_attributes}",
                self.styles['ProFormaBody']
            )])
        
        if pf.property_link and pf.property_link != 'n/a':
            details_data.append([Paragraph(
                f"<b>Property Link:</b> {pf.property_link}",
                self.styles['ProFormaBody']
            )])
        
        details_table = Table(details_data, colWidths=[self.content_width])
        details_table.setStyle(TableStyle([
            ('BOX', (0, 0), (-1, -1), 1, Colors.PRIMARY),
            ('PADDING', (0, 0), (-1, -1), 8),
            ('BACKGROUND', (0, 0), (-1, -1), Colors.PRIMARY_LIGHT),
        ]))
        story.append(details_table)
        
        story.append(Spacer(1, 12))
        
        return story
    
    def _render_monthly_table(self, pf: ProFormaData) -> list:
        """Render detailed monthly breakdown table."""
        story = []
        
        # Headers
        headers = [
            'Month', 'Season', 'Days', 'Owner', 'Avail', 'Rented', 
            'Vacant', 'Rate', 'Discount', 'Min Rate', 'Occ %', 'Revenue'
        ]
        
        rows = [headers]
        
        # Use seasons data or generate from monthly data
        seasons = pf.seasons if pf.seasons else self._generate_seasons(pf)
        
        totals = {
            'days': 0, 'owner': 0, 'available': 0, 
            'rented': 0, 'unrented': 0, 'revenue': 0
        }
        
        for s in seasons:
            row = [
                s.get('month', ''),
                s.get('season', ''),
                str(s.get('days', 0)),
                str(s.get('owner_use', 0)),
                str(s.get('available', s.get('days', 0))),
                str(s.get('rented', 0)),
                str(s.get('unrented', 0)),
                f"${s.get('rate', 0):,.0f}",
                f"{s.get('discount', 0)}%",
                f"${s.get('lowest_rate', s.get('rate', 0)):,.0f}",
                f"{s.get('occupancy', 0):.0%}",
                f"${s.get('revenue', 0):,.0f}",
            ]
            rows.append(row)
            
            totals['days'] += s.get('days', 0)
            totals['owner'] += s.get('owner_use', 0)
            totals['available'] += s.get('available', s.get('days', 0))
            totals['rented'] += s.get('rented', 0)
            totals['unrented'] += s.get('unrented', 0)
            totals['revenue'] += s.get('revenue', 0)
        
        # Totals row
        total_row = [
            '', 'TOTALS', 
            str(totals['days']), str(totals['owner']), str(totals['available']),
            str(totals['rented']), str(totals['unrented']),
            '', '', f"${pf.adr:,.0f}", f"{pf.occupancy:.0%}", f"${totals['revenue']:,.0f}"
        ]
        rows.append(total_row)
        
        # Column widths
        col_widths = [
            0.55*inch, 0.85*inch, 0.35*inch, 0.35*inch, 0.35*inch,
            0.4*inch, 0.4*inch, 0.5*inch, 0.5*inch, 0.5*inch, 0.4*inch, 0.6*inch
        ]
        
        detail_table = Table(rows, colWidths=col_widths)
        detail_table.setStyle(TableStyle([
            # Header
            ('BACKGROUND', (0, 0), (-1, 0), Colors.PRIMARY),
            ('TEXTCOLOR', (0, 0), (-1, 0), Colors.WHITE),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 7),
            
            # Alignment
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('ALIGN', (0, 1), (1, -1), 'LEFT'),
            
            # Grid
            ('GRID', (0, 0), (-1, -1), 0.5, Colors.BORDER),
            
            # Alternating rows
            ('ROWBACKGROUNDS', (0, 1), (-1, -2), [Colors.WHITE, Colors.ROW_ALT]),
            
            # Totals row
            ('BACKGROUND', (0, -1), (-1, -1), Colors.PRIMARY),
            ('TEXTCOLOR', (0, -1), (-1, -1), Colors.WHITE),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            
            # Padding
            ('PADDING', (0, 0), (-1, -1), 3),
        ]))
        story.append(detail_table)
        
        return story
    
    def _render_market_analysis(self, pf: ProFormaData) -> list:
        """Render market analysis section if data available."""
        story = []
        
        story.append(Spacer(1, 12))
        story.append(Paragraph("Market Analysis", self.styles['SectionHeader']))
        
        if pf.market_name:
            story.append(Paragraph(
                f"<b>Market:</b> {pf.market_name}",
                self.styles['ProFormaBody']
            ))
        
        if pf.market_phase:
            story.append(Paragraph(
                f"<b>Market Phase:</b> {pf.market_phase}",
                self.styles['ProFormaBody']
            ))
        
        if pf.confidence:
            story.append(Paragraph(
                f"<b>Projection Confidence:</b> {pf.confidence:.0%}",
                self.styles['ProFormaBody']
            ))
        
        # Drivers
        if pf.drivers:
            story.append(Spacer(1, 6))
            story.append(Paragraph("<b>Key Performance Drivers:</b>", self.styles['ProFormaBody']))
            
            for d in pf.drivers[:5]:
                name = d.get('name', '')
                impact = d.get('impact', d.get('impact_pct', 0))
                if isinstance(impact, float) and impact < 1:
                    impact_str = f"{impact:+.0%}"
                else:
                    impact_str = str(impact)
                conf = d.get('confidence', 'Medium')
                
                story.append(Paragraph(
                    f"• {name}: {impact_str} ({conf} confidence)",
                    self.styles['ProFormaBody']
                ))
        
        return story
    
    def _generate_seasons(self, pf: ProFormaData) -> list:
        """Generate basic seasonal breakdown from monthly data."""
        # Default seasonal template for 30A-style market
        return [
            {'month': 'January', 'season': 'Winter', 'days': 31, 'owner_use': 0, 'available': 31, 'rented': 0, 'unrented': 31, 'rate': 500, 'discount': 0, 'lowest_rate': 500, 'occupancy': 0, 'revenue': 0},
            {'month': 'February', 'season': 'Winter', 'days': 28, 'owner_use': 0, 'available': 28, 'rented': 0, 'unrented': 28, 'rate': 500, 'discount': 0, 'lowest_rate': 500, 'occupancy': 0, 'revenue': 0},
            {'month': 'March', 'season': 'Spring Break', 'days': 28, 'owner_use': 0, 'available': 28, 'rented': 28, 'unrented': 0, 'rate': 875, 'discount': 0, 'lowest_rate': 875, 'occupancy': 1.0, 'revenue': pf.monthly_revenue.get('Mar', 24444)},
            {'month': 'April', 'season': 'Spring', 'days': 30, 'owner_use': 0, 'available': 30, 'rented': 10, 'unrented': 20, 'rate': 677, 'discount': 0, 'lowest_rate': 677, 'occupancy': 0.33, 'revenue': pf.monthly_revenue.get('Apr', 6770)},
            {'month': 'May', 'season': 'Late Spring', 'days': 31, 'owner_use': 0, 'available': 31, 'rented': 19, 'unrented': 12, 'rate': 908, 'discount': 0, 'lowest_rate': 650, 'occupancy': 0.61, 'revenue': pf.monthly_revenue.get('May', 17250)},
            {'month': 'June', 'season': 'Summer', 'days': 30, 'owner_use': 0, 'available': 30, 'rented': 30, 'unrented': 0, 'rate': 1150, 'discount': 0, 'lowest_rate': 1150, 'occupancy': 1.0, 'revenue': pf.monthly_revenue.get('Jun', 34500)},
            {'month': 'July', 'season': 'Peak Summer', 'days': 31, 'owner_use': 0, 'available': 31, 'rented': 31, 'unrented': 0, 'rate': 1203, 'discount': 0, 'lowest_rate': 1150, 'occupancy': 1.0, 'revenue': pf.monthly_revenue.get('Jul', 39700)},
            {'month': 'August', 'season': 'Late Summer', 'days': 31, 'owner_use': 0, 'available': 31, 'rented': 13, 'unrented': 18, 'rate': 1055, 'discount': 0, 'lowest_rate': 950, 'occupancy': 0.42, 'revenue': pf.monthly_revenue.get('Aug', 13718)},
            {'month': 'September', 'season': 'Fall', 'days': 30, 'owner_use': 0, 'available': 30, 'rented': 14, 'unrented': 16, 'rate': 550, 'discount': 0, 'lowest_rate': 550, 'occupancy': 0.47, 'revenue': pf.monthly_revenue.get('Sep', 7700)},
            {'month': 'October', 'season': 'Fall', 'days': 31, 'owner_use': 0, 'available': 31, 'rented': 15, 'unrented': 16, 'rate': 550, 'discount': 0, 'lowest_rate': 550, 'occupancy': 0.48, 'revenue': pf.monthly_revenue.get('Oct', 8250)},
            {'month': 'November', 'season': 'Late Fall', 'days': 30, 'owner_use': 0, 'available': 30, 'rented': 9, 'unrented': 21, 'rate': 600, 'discount': 0, 'lowest_rate': 500, 'occupancy': 0.30, 'revenue': pf.monthly_revenue.get('Nov', 6185)},
            {'month': 'December', 'season': 'Winter', 'days': 31, 'owner_use': 0, 'available': 31, 'rented': 3, 'unrented': 28, 'rate': 800, 'discount': 0, 'lowest_rate': 500, 'occupancy': 0.10, 'revenue': pf.monthly_revenue.get('Dec', 2850)},
        ]


# =============================================================================
# CONVENIENCE FUNCTION
# =============================================================================

def render_rental_proforma(
    data: Dict[str, Any],
    output_path: str,
    branding: Optional[Dict] = None,
) -> str:
    """
    Render a rental pro forma PDF.
    
    Args:
        data: Pro forma data including:
            - address: Property address
            - bedrooms, bathrooms, sqft: Property specs
            - property_value: Listed price
            - gross_revenue: Projected gross revenue
            - net_revenue: Projected net revenue
            - nights_rented: Projected nights
            - occupancy: Overall occupancy rate
            - adr: Average daily rate
            - monthly_revenue: Dict of month -> revenue
            - monthly_occupancy: Dict of month -> occupancy
            - monthly_adr: Dict of month -> ADR
            - seasons: List of seasonal breakdown dicts (optional)
            - market_name: Market name (optional)
            - drivers: Performance drivers (optional)
        
        output_path: Where to save the PDF
        
        branding: Optional branding dict:
            - logo_path: Path to logo image
            - company_name: Company name
            - prepared_by: Agent/analyst name
            - email, phone, website: Contact info
            - disclaimer: Custom disclaimer text
    
    Returns:
        Path to generated PDF
    
    Example:
        render_rental_proforma(
            {
                'address': '313 E Royal Fern Way',
                'bedrooms': 5,
                'bathrooms': 5,
                'gross_revenue': 161367,
                'occupancy': 0.48,
                'adr': 927,
                'monthly_revenue': {'Jan': 0, 'Feb': 0, ...},
                'monthly_occupancy': {'Jan': 0, 'Feb': 0, ...},
                'monthly_adr': {'Jan': 0, 'Feb': 0, ...},
            },
            'output.pdf',
            branding={
                'company_name': 'Beach Habitats',
                'prepared_by': 'Nick Smith',
                'email': 'nick@beachhabitats30a.com',
            }
        )
    """
    renderer = RentalProFormaRenderer()
    return renderer.render(data, output_path, branding)
