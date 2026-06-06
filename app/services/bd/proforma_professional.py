"""
Rental Projections Pro Forma - Professional Edition.

Matches the Rentalz.com visual style with:
- Real bar charts (not text approximations)
- Proper occupancy visualization
- Professional typography
- Clean layout matching the reference

Uses ReportLab's graphics capabilities properly.
"""

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor, white, black, Color
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, Image, Flowable
)
from reportlab.graphics.shapes import Drawing, Rect, String, Line, Circle, Wedge
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.widgets.markers import makeMarker
from reportlab.pdfgen import canvas

from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
import math


# =============================================================================
# COLORS - Matching Rentalz/Beach Habitats
# =============================================================================

class Colors:
    TEAL = HexColor("#1a8a8a")
    TEAL_DARK = HexColor("#0d6666")
    TEAL_LIGHT = HexColor("#e8f5f5")
    GOLD = HexColor("#c9a227")
    NAVY = HexColor("#2c3e50")
    GRAY_DARK = HexColor("#4a5568")
    GRAY_MED = HexColor("#718096")
    GRAY_LIGHT = HexColor("#a0aec0")
    GRAY_LIGHTER = HexColor("#e2e8f0")
    WHITE = white
    BLACK = black
    
    # Chart colors
    BAR_TEAL = HexColor("#2d9a9a")
    BAR_GOLD = HexColor("#d4af37")
    OCCUPIED = HexColor("#2d9a9a")
    UNOCCUPIED = HexColor("#cbd5e0")
    OWNER_USE = HexColor("#d4af37")


# =============================================================================
# CUSTOM FLOWABLES FOR CHARTS
# =============================================================================

class MonthlyRevenueChart(Flowable):
    """Bar chart showing monthly revenue."""
    
    def __init__(self, data: Dict[str, float], width: float, height: float):
        Flowable.__init__(self)
        self.data = data
        self.width = width
        self.height = height
        self.months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 
                       'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    
    def draw(self):
        values = [self.data.get(m, 0) for m in self.months]
        max_val = max(values) if max(values) > 0 else 40000
        
        bar_width = (self.width - 40) / 12
        chart_height = self.height - 35
        
        # Draw bars
        for i, (month, val) in enumerate(zip(self.months, values)):
            x = 20 + i * bar_width
            
            if val > 0:
                bar_height = (val / max_val) * (chart_height - 20)
                
                # Bar
                self.canv.setFillColor(Colors.BAR_TEAL)
                self.canv.rect(x + 2, 25, bar_width - 4, bar_height, fill=1, stroke=0)
                
                # Value label above bar
                self.canv.setFillColor(Colors.GRAY_DARK)
                self.canv.setFont('Helvetica', 6)
                label = f"${val:,.0f}"
                self.canv.drawCentredString(x + bar_width/2, 25 + bar_height + 3, label)
            else:
                # Zero value
                self.canv.setFillColor(Colors.GRAY_LIGHT)
                self.canv.setFont('Helvetica', 6)
                self.canv.drawCentredString(x + bar_width/2, 28, "$0")
            
            # Month label
            self.canv.setFillColor(Colors.GRAY_DARK)
            self.canv.setFont('Helvetica', 7)
            self.canv.drawCentredString(x + bar_width/2, 10, month)


class OccupancyChart(Flowable):
    """Stacked bar chart showing occupancy by month."""
    
    def __init__(self, data: Dict[str, float], width: float, height: float):
        Flowable.__init__(self)
        self.data = data
        self.width = width
        self.height = height
        self.months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 
                       'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    
    def draw(self):
        bar_width = (self.width - 40) / 12
        chart_height = self.height - 35
        max_bar_height = chart_height - 25
        
        for i, month in enumerate(self.months):
            x = 20 + i * bar_width
            occ = self.data.get(month, 0)
            
            # Occupied portion (teal)
            occ_height = occ * max_bar_height
            if occ_height > 0:
                self.canv.setFillColor(Colors.OCCUPIED)
                self.canv.rect(x + 3, 25, bar_width - 6, occ_height, fill=1, stroke=0)
            
            # Unoccupied portion (gray)
            unocc_height = (1 - occ) * max_bar_height
            if unocc_height > 0:
                self.canv.setFillColor(Colors.UNOCCUPIED)
                self.canv.rect(x + 3, 25 + occ_height, bar_width - 6, unocc_height, fill=1, stroke=0)
            
            # Occupancy percentage label
            self.canv.setFillColor(Colors.TEAL_DARK)
            self.canv.setFont('Helvetica-Bold', 6)
            if occ > 0:
                self.canv.drawCentredString(x + bar_width/2, 25 + occ_height/2 - 3, f"{occ:.0%}")
            
            # Unoccupied percentage (if space)
            if unocc_height > 15 and occ < 0.9:
                self.canv.setFillColor(Colors.GRAY_MED)
                self.canv.setFont('Helvetica', 6)
                self.canv.drawCentredString(x + bar_width/2, 25 + occ_height + unocc_height/2 - 3, f"{1-occ:.0%}")
            
            # Month label
            self.canv.setFillColor(Colors.GRAY_DARK)
            self.canv.setFont('Helvetica', 7)
            self.canv.drawCentredString(x + bar_width/2, 10, month)


class ADRChart(Flowable):
    """Bar chart showing ADR by month."""
    
    def __init__(self, data: Dict[str, float], width: float, height: float):
        Flowable.__init__(self)
        self.data = data
        self.width = width
        self.height = height
        self.months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 
                       'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    
    def draw(self):
        values = [self.data.get(m, 0) for m in self.months]
        max_val = max(values) if max(values) > 0 else 1500
        
        bar_width = (self.width - 40) / 12
        chart_height = self.height - 35
        
        for i, (month, val) in enumerate(zip(self.months, values)):
            x = 20 + i * bar_width
            
            if val > 0:
                bar_height = (val / max_val) * (chart_height - 25)
                
                # Bar with gradient effect (darker at bottom)
                self.canv.setFillColor(Colors.BAR_TEAL)
                self.canv.rect(x + 3, 25, bar_width - 6, bar_height, fill=1, stroke=0)
                
                # Value label
                self.canv.setFillColor(Colors.GRAY_DARK)
                self.canv.setFont('Helvetica', 6)
                self.canv.drawCentredString(x + bar_width/2, 25 + bar_height + 3, f"${val:,.0f}")
            else:
                self.canv.setFillColor(Colors.GRAY_LIGHT)
                self.canv.setFont('Helvetica', 6)
                self.canv.drawCentredString(x + bar_width/2, 28, "$0")
            
            # Month label
            self.canv.setFillColor(Colors.GRAY_DARK)
            self.canv.setFont('Helvetica', 7)
            self.canv.drawCentredString(x + bar_width/2, 10, month)


class OccupancyPieChart(Flowable):
    """Pie chart showing overall occupancy."""
    
    def __init__(self, occupancy: float, width: float, height: float):
        Flowable.__init__(self)
        self.occupancy = occupancy
        self.width = width
        self.height = height
    
    def draw(self):
        cx = self.width / 2
        cy = self.height / 2
        radius = min(self.width, self.height) / 2 - 5
        
        # Calculate angles (start from top, go clockwise)
        occ_angle = self.occupancy * 360
        
        # Draw occupied wedge (teal)
        self.canv.setFillColor(Colors.OCCUPIED)
        if occ_angle > 0:
            # Convert to reportlab's coordinate system (counter-clockwise from 3 o'clock)
            start = 90
            end = 90 - occ_angle
            self._draw_wedge(cx, cy, radius, end, start)
        
        # Draw unoccupied wedge (gray)
        self.canv.setFillColor(Colors.UNOCCUPIED)
        if occ_angle < 360:
            start = 90 - occ_angle
            end = 90 - 360
            self._draw_wedge(cx, cy, radius, end, start)
        
        # Center label
        self.canv.setFillColor(Colors.TEAL_DARK)
        self.canv.setFont('Helvetica-Bold', 14)
        self.canv.drawCentredString(cx, cy - 5, f"{self.occupancy:.0%}")
    
    def _draw_wedge(self, cx, cy, radius, start_angle, end_angle):
        """Draw a pie wedge."""
        path = self.canv.beginPath()
        path.moveTo(cx, cy)
        path.arcTo(cx - radius, cy - radius, cx + radius, cy + radius, start_angle, end_angle - start_angle)
        path.close()
        self.canv.drawPath(path, fill=1, stroke=0)


# =============================================================================
# STYLES
# =============================================================================

def create_styles():
    """Create document styles."""
    styles = getSampleStyleSheet()
    
    styles.add(ParagraphStyle(
        name='PFTitle',
        fontSize=20,
        textColor=Colors.TEAL_DARK,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold',
        spaceAfter=2,
    ))
    
    styles.add(ParagraphStyle(
        name='PFAddress',
        fontSize=12,
        textColor=Colors.GRAY_DARK,
        alignment=TA_CENTER,
        fontName='Helvetica',
        spaceAfter=10,
    ))
    
    styles.add(ParagraphStyle(
        name='PFSectionTitle',
        fontSize=11,
        textColor=Colors.TEAL_DARK,
        fontName='Helvetica-Bold',
        spaceBefore=10,
        spaceAfter=6,
    ))
    
    styles.add(ParagraphStyle(
        name='PFLargeNumber',
        fontSize=24,
        textColor=Colors.TEAL_DARK,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold',
    ))
    
    styles.add(ParagraphStyle(
        name='PFLabel',
        fontSize=9,
        textColor=Colors.GRAY_DARK,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold',
    ))
    
    styles.add(ParagraphStyle(
        name='PFSubtext',
        fontSize=8,
        textColor=Colors.GRAY_MED,
        alignment=TA_CENTER,
        fontName='Helvetica',
    ))
    
    styles.add(ParagraphStyle(
        name='PFMetricValue',
        fontSize=16,
        textColor=Colors.TEAL_DARK,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold',
    ))
    
    styles.add(ParagraphStyle(
        name='PFMetricLabel',
        fontSize=8,
        textColor=Colors.GRAY_DARK,
        alignment=TA_CENTER,
        fontName='Helvetica',
    ))
    
    styles.add(ParagraphStyle(
        name='PFPreparedBy',
        fontSize=10,
        textColor=Colors.GRAY_DARK,
        fontName='Helvetica-Bold',
    ))
    
    styles.add(ParagraphStyle(
        name='PFContact',
        fontSize=9,
        textColor=Colors.GRAY_MED,
        fontName='Helvetica',
    ))
    
    styles.add(ParagraphStyle(
        name='PFDisclaimer',
        fontSize=7,
        textColor=Colors.GRAY_LIGHT,
        alignment=TA_CENTER,
        fontName='Helvetica-Oblique',
    ))
    
    styles.add(ParagraphStyle(
        name='PFBody',
        fontSize=9,
        textColor=Colors.GRAY_DARK,
        fontName='Helvetica',
    ))
    
    return styles


# =============================================================================
# MAIN RENDERER
# =============================================================================

class ProFormaRenderer:
    """
    Professional rental pro forma PDF renderer.
    
    Generates PDFs matching the Rentalz.com visual style.
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
        """Render pro forma to PDF."""
        branding = branding or {}
        
        doc = SimpleDocTemplate(
            output_path,
            pagesize=letter,
            rightMargin=self.margin,
            leftMargin=self.margin,
            topMargin=0.4 * inch,
            bottomMargin=0.3 * inch,
        )
        
        story = []
        
        # Page 1: Summary
        story.extend(self._build_page1(data, branding))
        story.append(PageBreak())
        
        # Page 2: Details
        story.extend(self._build_page2(data, branding))
        
        doc.build(story)
        return output_path
    
    # =========================================================================
    # PAGE 1
    # =========================================================================
    
    def _build_page1(self, data: Dict, branding: Dict) -> list:
        """Build summary page."""
        story = []
        
        # Header
        story.extend(self._build_header(data, branding))
        
        # Revenue summary
        story.extend(self._build_revenue_boxes(data))
        
        # Key metrics strip
        story.extend(self._build_metrics_strip(data))
        
        # Monthly revenue chart
        story.extend(self._build_revenue_chart(data))
        
        # Occupancy section
        story.extend(self._build_occupancy_section(data))
        
        # ADR section
        story.extend(self._build_adr_section(data))
        
        # Bottom section
        story.extend(self._build_bottom_section(data, branding))
        
        return story
    
    def _build_header(self, data: Dict, branding: Dict) -> list:
        """Build header with logo and title."""
        story = []
        
        # Logo or company name
        logo_content = ""
        if branding.get('logo_path'):
            try:
                logo_content = Image(branding['logo_path'], width=1.4*inch, height=0.5*inch)
            except:
                pass
        
        if not logo_content and branding.get('company_name'):
            logo_content = Paragraph(
                f"<font color='#0d6666'><b>{branding['company_name']}</b></font>",
                self.styles['PFPreparedBy']
            )
        
        # Title row
        header_data = [[
            logo_content,
            [
                Paragraph("Rental Projections Pro Forma Summary", self.styles['PFTitle']),
                Paragraph(data.get('address', ''), self.styles['PFAddress']),
            ],
            "",
        ]]
        
        header_table = Table(header_data, colWidths=[1.6*inch, 4.6*inch, 1.1*inch])
        header_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ALIGN', (1, 0), (1, 0), 'CENTER'),
        ]))
        story.append(header_table)
        
        return story
    
    def _build_revenue_boxes(self, data: Dict) -> list:
        """Build main revenue summary boxes."""
        story = []
        
        gross = data.get('gross_revenue', 0)
        gross_low = data.get('gross_revenue_low', gross * 0.8)
        gross_high = data.get('gross_revenue_high', gross * 1.2)
        
        net = data.get('net_revenue', gross * 0.8)
        net_low = data.get('net_revenue_low', net * 0.8)
        net_high = data.get('net_revenue_high', net * 1.2)
        commission = data.get('commission_pct', 20)
        
        # Gross revenue box
        gross_cell = [
            Paragraph("Total Projected Gross Revenue:", self.styles['PFLabel']),
            Paragraph(f"${gross:,.0f}", self.styles['PFLargeNumber']),
            Paragraph(
                f"(From ${gross_low:,.0f} to ${gross_high:,.0f} based on market conditions and pricing)",
                self.styles['PFSubtext']
            ),
        ]
        
        # Net revenue box
        net_cell = [
            Paragraph("Total Projected NET proceeds:", self.styles['PFLabel']),
            Paragraph(f"${net:,.0f}", self.styles['PFLargeNumber']),
            Paragraph(
                f"(From ${net_low:,.0f} to ${net_high:,.0f} based on market conditions, pricing, and net of {commission}% commission)",
                self.styles['PFSubtext']
            ),
        ]
        
        rev_table = Table([[gross_cell, net_cell]], colWidths=[3.65*inch, 3.65*inch])
        rev_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('PADDING', (0, 0), (-1, -1), 8),
        ]))
        story.append(rev_table)
        story.append(Spacer(1, 8))
        
        return story
    
    def _build_metrics_strip(self, data: Dict) -> list:
        """Build key metrics horizontal strip."""
        story = []
        
        metrics = [
            (f"{data.get('nights_rented', 0)}", "Total Projected Nights Rented"),
            (f"{data.get('owner_days', 0)}", "Total Days Owner Enjoyment"),
            (f"{data.get('occupancy', 0):.0%}", "Occupancy"),
            (f"${data.get('adr', 0):,.0f}", "Average Nightly Rate"),
        ]
        
        cells = []
        for value, label in metrics:
            cells.append([
                Paragraph(value, self.styles['PFMetricValue']),
                Paragraph(label, self.styles['PFMetricLabel']),
            ])
        
        metrics_table = Table([cells], colWidths=[1.825*inch] * 4)
        metrics_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('BOX', (0, 0), (-1, -1), 0.5, Colors.TEAL),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, Colors.GRAY_LIGHTER),
            ('BACKGROUND', (0, 0), (-1, -1), Colors.TEAL_LIGHT),
            ('PADDING', (0, 0), (-1, -1), 6),
        ]))
        story.append(metrics_table)
        story.append(Spacer(1, 8))
        
        return story
    
    def _build_revenue_chart(self, data: Dict) -> list:
        """Build monthly revenue bar chart."""
        story = []
        
        gross = data.get('gross_revenue', 0)
        story.append(Paragraph(
            f"Total Projected Gross Revenue: ${gross:,.0f}",
            self.styles['PFSectionTitle']
        ))
        
        monthly = data.get('monthly_revenue', {})
        chart = MonthlyRevenueChart(monthly, self.content_width, 85)
        story.append(chart)
        story.append(Spacer(1, 6))
        
        return story
    
    def _build_occupancy_section(self, data: Dict) -> list:
        """Build occupancy visualization section."""
        story = []
        
        occ = data.get('occupancy', 0)
        nights = data.get('nights_rented', 0)
        total = 365 - data.get('owner_days', 0)
        
        # Header with pie chart and legend
        header_data = [[
            [
                Paragraph("Occupancy", self.styles['PFSectionTitle']),
                Paragraph(f"{occ:.0%}", self.styles['PFMetricValue']),
            ],
            [
                Paragraph(
                    f"<font color='#2d9a9a'>■</font> Nights Rented ({nights})   "
                    f"<font color='#d4af37'>■</font> Owner Use ({data.get('owner_days', 0)})   "
                    f"<font color='#cbd5e0'>■</font> Unrented Nights ({total - nights})",
                    self.styles['PFSubtext']
                ),
            ],
        ]]
        header_table = Table(header_data, colWidths=[1.5*inch, 5.8*inch])
        header_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
        ]))
        story.append(header_table)
        
        # Stacked bar chart
        monthly_occ = data.get('monthly_occupancy', {})
        chart = OccupancyChart(monthly_occ, self.content_width, 75)
        story.append(chart)
        story.append(Spacer(1, 6))
        
        return story
    
    def _build_adr_section(self, data: Dict) -> list:
        """Build ADR chart section."""
        story = []
        
        adr = data.get('adr', 0)
        story.append(Paragraph(
            f"Average Nightly Rate: ${adr:,.0f}",
            self.styles['PFSectionTitle']
        ))
        
        monthly_adr = data.get('monthly_adr', {})
        chart = ADRChart(monthly_adr, self.content_width, 70)
        story.append(chart)
        story.append(Spacer(1, 6))
        
        return story
    
    def _build_bottom_section(self, data: Dict, branding: Dict) -> list:
        """Build bottom section with contact info and sensitivity matrix."""
        story = []
        
        # Left: Prepared by
        prep_content = []
        prep_content.append(Paragraph("<b>Rental Projections Prepared By</b>", self.styles['PFLabel']))
        prep_content.append(Spacer(1, 4))
        
        if branding.get('prepared_by'):
            prep_content.append(Paragraph(f"<b>{branding['prepared_by']}</b>", self.styles['PFPreparedBy']))
        if branding.get('email'):
            prep_content.append(Paragraph(branding['email'], self.styles['PFContact']))
        if branding.get('phone'):
            prep_content.append(Paragraph(branding['phone'], self.styles['PFContact']))
        if branding.get('website'):
            prep_content.append(Paragraph(branding['website'], self.styles['PFContact']))
        prep_content.append(Spacer(1, 4))
        prep_content.append(Paragraph(datetime.now().strftime("%B %d, %Y"), self.styles['PFContact']))
        
        # Right: Sensitivity matrix
        sens_content = []
        sens_content.append(Paragraph("<b>Sensitivity Analysis</b>", self.styles['PFLabel']))
        sens_content.append(Spacer(1, 4))
        sens_content.append(self._build_sensitivity_matrix(data))
        
        bottom_table = Table([[prep_content, sens_content]], colWidths=[2.2*inch, 5.1*inch])
        bottom_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))
        story.append(bottom_table)
        
        return story
    
    def _build_sensitivity_matrix(self, data: Dict) -> Table:
        """Build sensitivity analysis matrix."""
        base = data.get('gross_revenue', 161367)
        
        # Header
        rows = [
            ['', '', '', 'Nights Rented', '', ''],
            ['', '', '80%', '90%', '100%', '110%', '120%'],
        ]
        
        # Data rows
        pcts = [0.8, 0.9, 1.0, 1.1, 1.2]
        labels = ['80%', '90%', '100%', '110%', '120%']
        
        for i, (mult, label) in enumerate(zip(pcts, labels)):
            row = ['ADR' if i == 2 else '', label]
            for nights_mult in pcts:
                val = base * mult * nights_mult
                row.append(f"${val:,.0f}")
            rows.append(row)
        
        col_widths = [0.3*inch, 0.4*inch, 0.7*inch, 0.7*inch, 0.7*inch, 0.7*inch, 0.7*inch]
        
        sens_table = Table(rows, colWidths=col_widths)
        sens_table.setStyle(TableStyle([
            # Header row
            ('SPAN', (3, 0), (6, 0)),
            ('ALIGN', (3, 0), (6, 0), 'CENTER'),
            ('FONTSIZE', (0, 0), (-1, -1), 7),
            
            # Column headers
            ('BACKGROUND', (2, 1), (-1, 1), Colors.TEAL),
            ('TEXTCOLOR', (2, 1), (-1, 1), Colors.WHITE),
            ('FONTNAME', (2, 1), (-1, 1), 'Helvetica-Bold'),
            
            # Row headers
            ('BACKGROUND', (1, 2), (1, -1), Colors.TEAL),
            ('TEXTCOLOR', (1, 2), (1, -1), Colors.WHITE),
            ('FONTNAME', (1, 2), (1, -1), 'Helvetica-Bold'),
            
            # Grid
            ('GRID', (1, 1), (-1, -1), 0.5, Colors.GRAY_LIGHTER),
            
            # Center cell (100%/100%)
            ('BACKGROUND', (4, 4), (4, 4), Colors.TEAL_LIGHT),
            ('FONTNAME', (4, 4), (4, 4), 'Helvetica-Bold'),
            
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('PADDING', (0, 0), (-1, -1), 2),
        ]))
        
        return sens_table
    
    # =========================================================================
    # PAGE 2
    # =========================================================================
    
    def _build_page2(self, data: Dict, branding: Dict) -> list:
        """Build details page."""
        story = []
        
        # Header
        story.append(Paragraph("Rental Projections Pro Forma Details", self.styles['PFTitle']))
        story.append(Paragraph(data.get('address', ''), self.styles['PFAddress']))
        
        # Property details box
        story.extend(self._build_property_box(data))
        
        # Monthly breakdown table
        story.extend(self._build_monthly_table(data))
        
        # Footer
        story.append(Spacer(1, 8))
        story.append(Paragraph(
            "Projections are estimates based on market analysis and comparable properties. Actual results may vary.",
            self.styles['PFDisclaimer']
        ))
        
        return story
    
    def _build_property_box(self, data: Dict) -> list:
        """Build property details box."""
        story = []
        
        details = [
            [
                f"Bedrooms: {data.get('bedrooms', 0)}",
                f"Bathrooms: {data.get('bathrooms', 0)}",
                f"Square Footage: {data.get('sqft', 0):,}" if data.get('sqft') else "",
            ]
        ]
        
        if data.get('property_value'):
            details.append([f"Property Value / Listed Price: ${data['property_value']:,.0f}", "", ""])
        
        if data.get('key_attributes'):
            details.append([f"Key Attributes: {data['key_attributes']}", "", ""])
        
        box_data = []
        for row in details:
            box_data.append([Paragraph(f"<b>{c.split(':')[0]}:</b>{c.split(':')[1] if ':' in c else ''}" if c else "", self.styles['PFBody']) for c in row])
        
        box_table = Table(box_data, colWidths=[2.4*inch, 2.4*inch, 2.4*inch])
        box_table.setStyle(TableStyle([
            ('BOX', (0, 0), (-1, -1), 1, Colors.TEAL),
            ('PADDING', (0, 0), (-1, -1), 6),
            ('BACKGROUND', (0, 0), (-1, -1), Colors.TEAL_LIGHT),
            ('SPAN', (0, 1), (-1, 1)) if len(details) > 1 else (),
            ('SPAN', (0, 2), (-1, 2)) if len(details) > 2 else (),
        ]))
        story.append(box_table)
        story.append(Spacer(1, 10))
        
        return story
    
    def _build_monthly_table(self, data: Dict) -> list:
        """Build monthly breakdown table."""
        story = []
        
        # Headers
        headers = ['Month', 'Season', 'Days', 'Owner', 'Avail', 'Rented', 
                   'Vacant', 'Rate', 'Discount', 'Min Rate', 'Occ %', 'Revenue']
        
        rows = [headers]
        
        seasons = data.get('seasons', [])
        if not seasons:
            seasons = self._generate_default_seasons(data)
        
        totals = {'days': 0, 'owner': 0, 'avail': 0, 'rented': 0, 'vacant': 0, 'revenue': 0}
        
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
                f"{s.get('occupancy', 0):.0%}" if s.get('occupancy', 0) > 0 else "0%",
                f"${s.get('revenue', 0):,.0f}",
            ]
            rows.append(row)
            
            totals['days'] += s.get('days', 0)
            totals['owner'] += s.get('owner_use', 0)
            totals['avail'] += s.get('available', s.get('days', 0))
            totals['rented'] += s.get('rented', 0)
            totals['vacant'] += s.get('unrented', 0)
            totals['revenue'] += s.get('revenue', 0)
        
        # Totals row
        adr = data.get('adr', 927)
        occ = data.get('occupancy', 0.48)
        total_row = ['', 'Totals', str(totals['days']), str(totals['owner']), str(totals['avail']),
                     str(totals['rented']), str(totals['vacant']), '', '', f"${adr:,.0f}", 
                     f"{occ:.0%}", f"${totals['revenue']:,.0f}"]
        rows.append(total_row)
        
        col_widths = [0.55*inch, 0.8*inch, 0.35*inch, 0.35*inch, 0.35*inch,
                      0.4*inch, 0.4*inch, 0.5*inch, 0.45*inch, 0.5*inch, 0.4*inch, 0.6*inch]
        
        detail_table = Table(rows, colWidths=col_widths)
        detail_table.setStyle(TableStyle([
            # Header
            ('BACKGROUND', (0, 0), (-1, 0), Colors.TEAL),
            ('TEXTCOLOR', (0, 0), (-1, 0), Colors.WHITE),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 7),
            
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('ALIGN', (0, 1), (1, -1), 'LEFT'),
            
            ('GRID', (0, 0), (-1, -1), 0.5, Colors.GRAY_LIGHTER),
            
            # Alternating rows
            ('ROWBACKGROUNDS', (0, 1), (-1, -2), [Colors.WHITE, HexColor("#f8fafb")]),
            
            # Totals
            ('BACKGROUND', (0, -1), (-1, -1), Colors.TEAL),
            ('TEXTCOLOR', (0, -1), (-1, -1), Colors.WHITE),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            
            ('PADDING', (0, 0), (-1, -1), 2),
        ]))
        story.append(detail_table)
        
        return story
    
    def _generate_default_seasons(self, data: Dict) -> list:
        """Generate default seasonal data from monthly data."""
        monthly_rev = data.get('monthly_revenue', {})
        monthly_occ = data.get('monthly_occupancy', {})
        monthly_adr = data.get('monthly_adr', {})
        
        seasons = []
        month_days = {'January': 31, 'February': 28, 'March': 31, 'April': 30, 
                      'May': 31, 'June': 30, 'July': 31, 'August': 31,
                      'September': 30, 'October': 31, 'November': 30, 'December': 31}
        month_short = {'January': 'Jan', 'February': 'Feb', 'March': 'Mar', 'April': 'Apr',
                       'May': 'May', 'June': 'Jun', 'July': 'Jul', 'August': 'Aug',
                       'September': 'Sep', 'October': 'Oct', 'November': 'Nov', 'December': 'Dec'}
        season_map = {'January': 'Winter', 'February': 'Winter', 'March': 'Spring',
                      'April': 'Spring', 'May': 'Spring', 'June': 'Summer',
                      'July': 'Summer', 'August': 'Summer', 'September': 'Fall',
                      'October': 'Fall', 'November': 'Fall', 'December': 'Winter'}
        
        for month, days in month_days.items():
            short = month_short[month]
            occ = monthly_occ.get(short, 0)
            adr = monthly_adr.get(short, 500)
            rev = monthly_rev.get(short, 0)
            rented = int(days * occ)
            
            seasons.append({
                'month': month,
                'season': season_map[month],
                'days': days,
                'owner_use': 0,
                'available': days,
                'rented': rented,
                'unrented': days - rented,
                'rate': adr,
                'discount': 0,
                'lowest_rate': adr,
                'occupancy': occ,
                'revenue': rev,
            })
        
        return seasons


# =============================================================================
# PUBLIC API
# =============================================================================

def render_proforma(
    data: Dict[str, Any],
    output_path: str,
    branding: Optional[Dict] = None,
) -> str:
    """
    Render a professional rental pro forma PDF.
    
    Args:
        data: Pro forma data
        output_path: Where to save PDF
        branding: Optional branding dict
    
    Returns:
        Path to generated PDF
    """
    renderer = ProFormaRenderer()
    return renderer.render(data, output_path, branding)
