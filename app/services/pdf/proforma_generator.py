"""
Pro Forma PDF Generator - Matches Beach Habitats Format Exactly.

This generates professional rent projection PDFs that:
1. Look human-made, not machine-made
2. Tell a story, not just numbers
3. Are defensible under scrutiny
4. Match Beach Habitats' aesthetic

The PDF has 2 pages:
- Page 1: Summary with charts (Monthly Revenue, Occupancy, ADR)
- Page 2: Detailed breakdown table by season/month

CRITICAL: PDFs must always trace back to /bd/rent-projection
Never let sales teams manually edit numbers.
"""

import io
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, Image, HRFlowable
)
from reportlab.pdfgen import canvas
from reportlab.graphics.shapes import Drawing, Rect, String, Line
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.linecharts import HorizontalLineChart
from reportlab.graphics.widgets.markers import makeMarker


# =============================================================================
# BEACH HABITATS BRAND COLORS
# =============================================================================

class BrandColors:
    """Beach Habitats brand color palette."""
    TEAL = colors.HexColor("#1B7F79")  # Primary teal/seafoam
    TEAL_DARK = colors.HexColor("#156661")
    TEAL_LIGHT = colors.HexColor("#E8F4F3")
    GOLD = colors.HexColor("#C4A35A")  # Accent gold
    NAVY = colors.HexColor("#2C3E50")  # Text
    GRAY_DARK = colors.HexColor("#4A4A4A")
    GRAY_MED = colors.HexColor("#7F8C8D")
    GRAY_LIGHT = colors.HexColor("#ECF0F1")
    WHITE = colors.white
    BLACK = colors.black


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class MonthlyData:
    """Monthly projection data for the PDF."""
    month: str
    season: str
    days: int
    owner_use: int
    available_nights: int
    nights_rented: int
    unrented_nights: int
    target_rate: float
    acceptable_discount: float
    lowest_target_rate: float
    occupancy_pct: float
    gross_revenue: float


@dataclass
class ProFormaData:
    """Complete data for Pro Forma PDF generation."""
    # Property info
    property_address: str
    bedrooms: int
    bathrooms: float
    square_footage: Optional[int]
    property_value: Optional[float]
    key_attributes: str  # e.g., "Private Pool, Carriage House!"
    property_link: Optional[str]
    
    # Summary metrics
    total_gross_revenue: float
    gross_revenue_low: float
    gross_revenue_high: float
    total_net_revenue: float
    net_revenue_low: float
    net_revenue_high: float
    commission_rate: float
    
    total_nights_rented: int
    total_owner_days: int
    occupancy_pct: float
    average_nightly_rate: float
    
    # Monthly breakdown
    monthly_data: List[MonthlyData]
    
    # Sensitivity matrix (rate % x occupancy %)
    sensitivity_matrix: List[List[float]]
    
    # Prepared by
    agent_name: str
    agent_email: str
    agent_phone: str
    company_website: str
    prepared_date: date
    
    # Branding
    logo_path: Optional[str] = None


# =============================================================================
# PDF GENERATOR
# =============================================================================

class ProFormaPDFGenerator:
    """
    Generates Pro Forma PDFs matching Beach Habitats format.
    
    The PDF is a derived artifact from the projection engine.
    It should NEVER contain manually edited numbers.
    """
    
    def __init__(self):
        self.page_width, self.page_height = letter
        self.margin = 0.5 * inch
        self.content_width = self.page_width - (2 * self.margin)
    
    def generate(self, data: ProFormaData, output_path: str) -> str:
        """
        Generate the Pro Forma PDF.
        
        Args:
            data: ProFormaData with all projection info
            output_path: Where to save the PDF
            
        Returns:
            Path to generated PDF
        """
        # Create PDF with custom canvas for header/footer
        doc = SimpleDocTemplate(
            output_path,
            pagesize=letter,
            leftMargin=self.margin,
            rightMargin=self.margin,
            topMargin=0.75 * inch,
            bottomMargin=0.5 * inch
        )
        
        story = []
        
        # Page 1: Summary
        story.extend(self._build_page1_summary(data))
        
        # Page break
        story.append(PageBreak())
        
        # Page 2: Details
        story.extend(self._build_page2_details(data))
        
        # Build with custom page template
        doc.build(
            story,
            onFirstPage=lambda c, d: self._draw_header_footer(c, d, data, 1),
            onLaterPages=lambda c, d: self._draw_header_footer(c, d, data, 2)
        )
        
        return output_path
    
    def _draw_header_footer(self, canvas: canvas.Canvas, doc, data: ProFormaData, page_num: int):
        """Draw header and footer on each page."""
        canvas.saveState()
        
        # Header - Logo area (left) and Title (center)
        # Logo placeholder - in production, use actual logo
        canvas.setFillColor(BrandColors.TEAL)
        canvas.setFont("Helvetica-Bold", 14)
        canvas.drawString(self.margin, self.page_height - 0.5 * inch, "BEACH HABITATS")
        
        canvas.setFillColor(BrandColors.GRAY_MED)
        canvas.setFont("Helvetica", 8)
        canvas.drawString(self.margin, self.page_height - 0.65 * inch, "LUXURY VACATION RENTALS")
        
        # Title - centered
        canvas.setFillColor(BrandColors.NAVY)
        canvas.setFont("Helvetica-Bold", 16)
        title = "Rental Projections Pro Forma Summary" if page_num == 1 else "Rental Projections Pro Forma Details"
        title_width = canvas.stringWidth(title, "Helvetica-Bold", 16)
        canvas.drawString((self.page_width - title_width) / 2, self.page_height - 0.5 * inch, title)
        
        # Property address - centered below title
        canvas.setFont("Helvetica", 11)
        addr_width = canvas.stringWidth(data.property_address, "Helvetica", 11)
        canvas.drawString((self.page_width - addr_width) / 2, self.page_height - 0.7 * inch, data.property_address)
        
        # Footer
        canvas.setFillColor(BrandColors.GRAY_MED)
        canvas.setFont("Helvetica", 8)
        canvas.drawString(self.margin, 0.35 * inch, f"© Rentalz.com")
        
        canvas.restoreState()
    
    def _build_page1_summary(self, data: ProFormaData) -> List:
        """Build Page 1: Summary with metrics and charts."""
        elements = []
        
        # Spacer for header
        elements.append(Spacer(1, 0.3 * inch))
        
        # === TOP METRICS BOX ===
        elements.append(self._build_top_metrics(data))
        elements.append(Spacer(1, 0.15 * inch))
        
        # === KEY STATS ROW ===
        elements.append(self._build_key_stats_row(data))
        elements.append(Spacer(1, 0.2 * inch))
        
        # === MONTHLY REVENUE CHART ===
        elements.append(self._build_section_header("Total Projected Gross Revenue: ${:,.0f}".format(data.total_gross_revenue)))
        elements.append(Spacer(1, 0.1 * inch))
        elements.append(self._build_revenue_chart(data))
        elements.append(Spacer(1, 0.15 * inch))
        
        # === OCCUPANCY CHART ===
        elements.append(self._build_occupancy_chart(data))
        elements.append(Spacer(1, 0.15 * inch))
        
        # === ADR CHART ===
        elements.append(self._build_section_header("Average Nightly Rate: ${:,.0f}".format(data.average_nightly_rate)))
        elements.append(Spacer(1, 0.1 * inch))
        elements.append(self._build_adr_chart(data))
        elements.append(Spacer(1, 0.2 * inch))
        
        # === BOTTOM ROW: Agent Info + Sensitivity Matrix ===
        elements.append(self._build_bottom_row(data))
        
        return elements
    
    def _build_top_metrics(self, data: ProFormaData) -> Table:
        """Build the top metrics summary box."""
        # Two columns: Gross Revenue | Net Revenue
        col1 = [
            [Paragraph("<b>Total Projected Gross Revenue:</b>", self._get_style("metric_label"))],
            [Paragraph("<font size='18'><b>${:,.0f}</b></font>".format(data.total_gross_revenue), 
                      self._get_style("metric_value", color=BrandColors.TEAL))],
            [Paragraph("(From ${:,.0f} to ${:,.0f} based on market conditions and pricing)".format(
                data.gross_revenue_low, data.gross_revenue_high), 
                self._get_style("metric_note"))],
        ]
        
        col2 = [
            [Paragraph("<b>Total Projected NET proceeds:</b>", self._get_style("metric_label"))],
            [Paragraph("<font size='18'><b>${:,.0f}</b></font>".format(data.total_net_revenue),
                      self._get_style("metric_value", color=BrandColors.TEAL))],
            [Paragraph("(From ${:,.0f} to ${:,.0f} based on market conditions, pricing, and net of {:.0%} commission)".format(
                data.net_revenue_low, data.net_revenue_high, data.commission_rate),
                self._get_style("metric_note"))],
        ]
        
        # Combine into single row table
        table_data = [[
            Table(col1, colWidths=[3.5 * inch]),
            Table(col2, colWidths=[3.5 * inch])
        ]]
        
        table = Table(table_data, colWidths=[3.75 * inch, 3.75 * inch])
        table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ]))
        
        return table
    
    def _build_key_stats_row(self, data: ProFormaData) -> Table:
        """Build the row of 4 key statistics."""
        stats = [
            ("Total Projected Nights Rented", str(data.total_nights_rented)),
            ("Total Days Owner Enjoyment", str(data.total_owner_days)),
            ("Occupancy", "{:.0%}".format(data.occupancy_pct)),
            ("Average Nightly Rate", "${:,.0f}".format(data.average_nightly_rate)),
        ]
        
        cells = []
        for label, value in stats:
            cell_content = [
                [Paragraph("<b>{}</b>".format(label), self._get_style("stat_label"))],
                [Paragraph("<font size='16' color='#1B7F79'><b>{}</b></font>".format(value),
                          self._get_style("stat_value"))],
            ]
            cells.append(Table(cell_content, colWidths=[1.7 * inch]))
        
        table = Table([cells], colWidths=[1.875 * inch] * 4)
        table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('BOX', (0, 0), (-1, -1), 0.5, BrandColors.GRAY_LIGHT),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, BrandColors.GRAY_LIGHT),
            ('BACKGROUND', (0, 0), (-1, -1), BrandColors.WHITE),
        ]))
        
        return table
    
    def _build_revenue_chart(self, data: ProFormaData) -> Drawing:
        """Build the monthly revenue bar chart."""
        drawing = Drawing(self.content_width, 120)
        
        # Extract monthly revenues
        revenues = [m.gross_revenue for m in data.monthly_data[:12]]
        months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
        
        # Create bar chart
        chart = VerticalBarChart()
        chart.x = 40
        chart.y = 20
        chart.width = self.content_width - 80
        chart.height = 85
        chart.data = [revenues]
        chart.categoryAxis.categoryNames = months
        chart.categoryAxis.labels.fontName = 'Helvetica'
        chart.categoryAxis.labels.fontSize = 7
        chart.valueAxis.valueMin = 0
        chart.valueAxis.valueMax = max(revenues) * 1.1 if revenues else 50000
        chart.valueAxis.labels.fontName = 'Helvetica'
        chart.valueAxis.labels.fontSize = 7
        chart.bars[0].fillColor = BrandColors.TEAL
        chart.bars[0].strokeColor = BrandColors.TEAL_DARK
        chart.barWidth = 20
        
        drawing.add(chart)
        
        # Add value labels on top of bars
        bar_width = chart.width / len(months)
        for i, rev in enumerate(revenues):
            if rev > 0:
                x = chart.x + (i * bar_width) + (bar_width / 2)
                y = chart.y + (rev / chart.valueAxis.valueMax) * chart.height + 5
                label = String(x, y, "${:,.0f}".format(rev))
                label.fontName = 'Helvetica'
                label.fontSize = 6
                label.textAnchor = 'middle'
                drawing.add(label)
        
        return drawing
    
    def _build_occupancy_chart(self, data: ProFormaData) -> Table:
        """Build the occupancy visualization (stacked bar style like Beach Habitats)."""
        # Create a simple table showing occupancy breakdown
        months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
        
        # Header with occupancy label
        header_style = self._get_style("chart_title")
        header = Paragraph("<b>Occupancy: {:.0%}</b>".format(data.occupancy_pct), header_style)
        
        # Legend
        legend_data = [
            [
                self._color_box(BrandColors.TEAL_DARK, "Nights Rented"),
                self._color_box(BrandColors.TEAL, "Owner Use"),
                self._color_box(BrandColors.GRAY_LIGHT, "Unrented Nights"),
            ]
        ]
        legend = Table(legend_data, colWidths=[2 * inch] * 3)
        legend.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ]))
        
        # Occupancy percentages row
        occ_data = []
        for m in data.monthly_data[:12]:
            if m.occupancy_pct > 0:
                occ_data.append("{:.0%}".format(m.occupancy_pct))
            else:
                occ_data.append("")
        
        occ_row = [[Paragraph("<font size='8'>{}</font>".format(o), self._get_style("center")) for o in occ_data]]
        month_row = [[Paragraph("<font size='8'>{}</font>".format(m), self._get_style("center")) for m in months]]
        
        occ_table = Table(occ_row + month_row, colWidths=[self.content_width / 12] * 12)
        occ_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
        ]))
        
        # Combine
        combined = Table([[header], [legend], [occ_table]], colWidths=[self.content_width])
        combined.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]))
        
        return combined
    
    def _build_adr_chart(self, data: ProFormaData) -> Drawing:
        """Build the ADR line/bar chart."""
        drawing = Drawing(self.content_width, 100)
        
        # Extract ADRs (use target rate as ADR proxy)
        adrs = [m.target_rate for m in data.monthly_data[:12]]
        months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
        
        chart = VerticalBarChart()
        chart.x = 40
        chart.y = 15
        chart.width = self.content_width - 80
        chart.height = 70
        chart.data = [adrs]
        chart.categoryAxis.categoryNames = months
        chart.categoryAxis.labels.fontName = 'Helvetica'
        chart.categoryAxis.labels.fontSize = 7
        chart.valueAxis.valueMin = 0
        chart.valueAxis.valueMax = max(adrs) * 1.2 if adrs and max(adrs) > 0 else 1500
        chart.valueAxis.labels.fontName = 'Helvetica'
        chart.valueAxis.labels.fontSize = 7
        chart.bars[0].fillColor = BrandColors.TEAL_LIGHT
        chart.bars[0].strokeColor = BrandColors.TEAL
        chart.barWidth = 18
        
        drawing.add(chart)
        
        # Add value labels
        bar_width = chart.width / len(months)
        for i, adr in enumerate(adrs):
            if adr > 0:
                x = chart.x + (i * bar_width) + (bar_width / 2)
                y = chart.y + (adr / chart.valueAxis.valueMax) * chart.height + 3
                label = String(x, y, "${:,.0f}".format(adr))
                label.fontName = 'Helvetica'
                label.fontSize = 6
                label.textAnchor = 'middle'
                drawing.add(label)
        
        return drawing
    
    def _build_bottom_row(self, data: ProFormaData) -> Table:
        """Build bottom row: Agent info (left) + Sensitivity matrix (right)."""
        # Agent info
        agent_info = [
            [Paragraph("<b>Rental Projections Prepared By</b>", self._get_style("section_header"))],
            [Spacer(1, 6)],
            [Paragraph("<b>{}</b>".format(data.agent_name), self._get_style("agent_name"))],
            [Paragraph(data.agent_email, self._get_style("agent_detail"))],
            [Paragraph(data.agent_phone, self._get_style("agent_detail"))],
            [Paragraph(data.company_website, self._get_style("agent_detail"))],
            [Spacer(1, 6)],
            [Paragraph(data.prepared_date.strftime("%B %d, %Y"), self._get_style("agent_detail"))],
        ]
        agent_table = Table(agent_info, colWidths=[2.5 * inch])
        
        # Sensitivity matrix
        sensitivity = self._build_sensitivity_matrix(data)
        
        # Combine
        combined = Table([[agent_table, sensitivity]], colWidths=[3 * inch, 4.5 * inch])
        combined.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))
        
        return combined
    
    def _build_sensitivity_matrix(self, data: ProFormaData) -> Table:
        """Build the sensitivity analysis matrix."""
        header = Paragraph("<b>Sensitivity Analysis</b>", self._get_style("section_header"))
        
        # Column headers (Nights Rented %)
        col_headers = ["", "80%", "90%", "100%", "110%", "120%"]
        
        # Row headers (Average Nightly Rate %)
        row_labels = ["80%", "90%", "100%", "110%", "120%"]
        
        # Build matrix data
        table_data = [
            [Paragraph("<b>Nights Rented</b>", self._get_style("matrix_header"))] +
            [Paragraph("<b>{}</b>".format(h), self._get_style("matrix_header")) for h in col_headers[1:]]
        ]
        
        for i, row_label in enumerate(row_labels):
            row = [Paragraph("<b>{}</b>".format(row_label), self._get_style("matrix_row_header"))]
            for j in range(5):
                if i < len(data.sensitivity_matrix) and j < len(data.sensitivity_matrix[i]):
                    val = data.sensitivity_matrix[i][j]
                    # Highlight 100%/100% cell
                    if i == 2 and j == 2:
                        row.append(Paragraph("<b>${:,.0f}</b>".format(val), self._get_style("matrix_cell_highlight")))
                    else:
                        row.append(Paragraph("${:,.0f}".format(val), self._get_style("matrix_cell")))
                else:
                    row.append("")
            table_data.append(row)
        
        # Add "Average Nightly Rate" label on left
        matrix_table = Table(table_data, colWidths=[0.6 * inch] + [0.7 * inch] * 5)
        matrix_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('FONTSIZE', (0, 0), (-1, -1), 7),
            ('GRID', (0, 0), (-1, -1), 0.5, BrandColors.GRAY_LIGHT),
            ('BACKGROUND', (0, 0), (-1, 0), BrandColors.TEAL),
            ('TEXTCOLOR', (0, 0), (-1, 0), BrandColors.WHITE),
            ('BACKGROUND', (0, 1), (0, -1), BrandColors.TEAL_LIGHT),
            ('BACKGROUND', (3, 3), (3, 3), BrandColors.GOLD),  # 100%/100% highlight
        ]))
        
        # Combine with header
        combined = Table([[header], [matrix_table]], colWidths=[4.3 * inch])
        return combined
    
    def _build_page2_details(self, data: ProFormaData) -> List:
        """Build Page 2: Detailed monthly breakdown table."""
        elements = []
        
        # Spacer for header
        elements.append(Spacer(1, 0.3 * inch))
        
        # Property info box
        elements.append(self._build_property_info_box(data))
        elements.append(Spacer(1, 0.15 * inch))
        
        # Detailed table
        elements.append(self._build_details_table(data))
        
        return elements
    
    def _build_property_info_box(self, data: ProFormaData) -> Table:
        """Build property info box for page 2."""
        info_data = [
            ["Bedrooms", str(data.bedrooms), "Bathrooms", str(int(data.bathrooms)) if data.bathrooms == int(data.bathrooms) else str(data.bathrooms), "Square Footage", "{:,}".format(data.square_footage) if data.square_footage else "N/A"],
            ["Property Value / Listed Price", "${:,.0f}".format(data.property_value) if data.property_value else "N/A", "", "", "", ""],
            ["Key Attributes", data.key_attributes, "", "", "", ""],
            ["Property Link", data.property_link or "n/a", "", "", "", ""],
        ]
        
        table = Table(info_data, colWidths=[1.3 * inch, 1.2 * inch, 1 * inch, 0.8 * inch, 1.2 * inch, 1 * inch])
        table.setStyle(TableStyle([
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('BOX', (0, 0), (-1, -1), 1, BrandColors.GRAY_MED),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, BrandColors.GRAY_LIGHT),
            ('BACKGROUND', (0, 0), (-1, -1), BrandColors.WHITE),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        
        return table
    
    def _build_details_table(self, data: ProFormaData) -> Table:
        """Build the detailed monthly breakdown table."""
        # Headers
        headers = [
            "Month", "Season", "Number\nof Days", "Owner\nUse", "Available\nNights",
            "Nights\nRented", "Unrented\nNights", "Target\nRates", "Acceptable\nDiscount",
            "Lowest\nTarget Rate", "Occupancy\n%", "Gross\nRevenue"
        ]
        
        header_row = [Paragraph("<b>{}</b>".format(h), self._get_style("table_header")) for h in headers]
        
        table_data = [header_row]
        
        # Data rows
        for m in data.monthly_data:
            row = [
                Paragraph("<font color='#1B7F79'><b>{}</b></font>".format(m.month), self._get_style("table_cell")),
                Paragraph(m.season, self._get_style("table_cell")),
                Paragraph(str(m.days), self._get_style("table_cell_center")),
                Paragraph(str(m.owner_use), self._get_style("table_cell_center")),
                Paragraph(str(m.available_nights), self._get_style("table_cell_center")),
                Paragraph(str(m.nights_rented), self._get_style("table_cell_center")),
                Paragraph(str(m.unrented_nights), self._get_style("table_cell_center")),
                Paragraph("${:,.0f}".format(m.target_rate), self._get_style("table_cell_right")),
                Paragraph("{:.0%}".format(m.acceptable_discount), self._get_style("table_cell_center")),
                Paragraph("${:,.0f}".format(m.lowest_target_rate), self._get_style("table_cell_right")),
                Paragraph("{:.0%}".format(m.occupancy_pct), self._get_style("table_cell_center")),
                Paragraph("${:,.0f}".format(m.gross_revenue), self._get_style("table_cell_right")),
            ]
            table_data.append(row)
        
        # Totals row
        totals_row = [
            Paragraph("<font color='#1B7F79'><b>Totals</b></font>", self._get_style("table_cell")),
            "",
            Paragraph("<b>365</b>", self._get_style("table_cell_center")),
            Paragraph("<b>{}</b>".format(data.total_owner_days), self._get_style("table_cell_center")),
            Paragraph("<b>365</b>", self._get_style("table_cell_center")),
            Paragraph("<b>{}</b>".format(data.total_nights_rented), self._get_style("table_cell_center")),
            Paragraph("<b>{}</b>".format(365 - data.total_nights_rented - data.total_owner_days), self._get_style("table_cell_center")),
            "",
            "",
            Paragraph("<font color='#1B7F79'><b>${:,.0f}</b></font>".format(data.average_nightly_rate), self._get_style("table_cell_right")),
            Paragraph("<font color='#1B7F79'><b>{:.0%}</b></font>".format(data.occupancy_pct), self._get_style("table_cell_center")),
            Paragraph("<font color='#1B7F79'><b>${:,.0f}</b></font>".format(data.total_gross_revenue), self._get_style("table_cell_right")),
        ]
        table_data.append(totals_row)
        
        # Column widths
        col_widths = [0.6 * inch, 1.0 * inch, 0.5 * inch, 0.45 * inch, 0.55 * inch,
                      0.5 * inch, 0.55 * inch, 0.55 * inch, 0.6 * inch, 0.6 * inch, 0.55 * inch, 0.65 * inch]
        
        table = Table(table_data, colWidths=col_widths)
        table.setStyle(TableStyle([
            # Header styling
            ('BACKGROUND', (0, 0), (-1, 0), BrandColors.TEAL),
            ('TEXTCOLOR', (0, 0), (-1, 0), BrandColors.WHITE),
            ('FONTSIZE', (0, 0), (-1, 0), 7),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            
            # Data rows
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('ALIGN', (0, 1), (1, -1), 'LEFT'),
            ('ALIGN', (2, 1), (-1, -1), 'CENTER'),
            
            # Alternating row colors
            ('ROWBACKGROUNDS', (0, 1), (-1, -2), [BrandColors.WHITE, BrandColors.GRAY_LIGHT]),
            
            # Totals row
            ('BACKGROUND', (0, -1), (-1, -1), BrandColors.TEAL_LIGHT),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            
            # Grid
            ('GRID', (0, 0), (-1, -1), 0.5, BrandColors.GRAY_MED),
            
            # Padding
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ('LEFTPADDING', (0, 0), (-1, -1), 3),
            ('RIGHTPADDING', (0, 0), (-1, -1), 3),
        ]))
        
        return table
    
    def _build_section_header(self, text: str) -> Paragraph:
        """Build a section header."""
        return Paragraph("<b>{}</b>".format(text), self._get_style("section_header"))
    
    def _color_box(self, color, label: str) -> Table:
        """Create a color box with label for legends."""
        box = Table([[""]], colWidths=[12], rowHeights=[12])
        box.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, 0), color),
            ('BOX', (0, 0), (0, 0), 0.5, BrandColors.GRAY_MED),
        ]))
        
        combined = Table([[box, Paragraph("<font size='8'>{}</font>".format(label), self._get_style("legend"))]], 
                        colWidths=[15, 1.5 * inch])
        combined.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        return combined
    
    def _get_style(self, style_name: str, color=None) -> ParagraphStyle:
        """Get a paragraph style by name."""
        styles = {
            "metric_label": ParagraphStyle(
                'metric_label', fontName='Helvetica', fontSize=10, 
                textColor=BrandColors.NAVY, alignment=TA_LEFT
            ),
            "metric_value": ParagraphStyle(
                'metric_value', fontName='Helvetica-Bold', fontSize=18,
                textColor=color or BrandColors.TEAL, alignment=TA_LEFT
            ),
            "metric_note": ParagraphStyle(
                'metric_note', fontName='Helvetica', fontSize=8,
                textColor=BrandColors.GRAY_MED, alignment=TA_LEFT
            ),
            "stat_label": ParagraphStyle(
                'stat_label', fontName='Helvetica', fontSize=9,
                textColor=BrandColors.NAVY, alignment=TA_CENTER
            ),
            "stat_value": ParagraphStyle(
                'stat_value', fontName='Helvetica-Bold', fontSize=16,
                textColor=BrandColors.TEAL, alignment=TA_CENTER
            ),
            "section_header": ParagraphStyle(
                'section_header', fontName='Helvetica-Bold', fontSize=10,
                textColor=BrandColors.NAVY, alignment=TA_CENTER
            ),
            "chart_title": ParagraphStyle(
                'chart_title', fontName='Helvetica-Bold', fontSize=10,
                textColor=BrandColors.NAVY, alignment=TA_CENTER
            ),
            "center": ParagraphStyle(
                'center', fontName='Helvetica', fontSize=8,
                textColor=BrandColors.NAVY, alignment=TA_CENTER
            ),
            "legend": ParagraphStyle(
                'legend', fontName='Helvetica', fontSize=8,
                textColor=BrandColors.GRAY_DARK, alignment=TA_LEFT
            ),
            "agent_name": ParagraphStyle(
                'agent_name', fontName='Helvetica-Bold', fontSize=10,
                textColor=BrandColors.NAVY, alignment=TA_LEFT
            ),
            "agent_detail": ParagraphStyle(
                'agent_detail', fontName='Helvetica', fontSize=9,
                textColor=BrandColors.GRAY_DARK, alignment=TA_LEFT
            ),
            "matrix_header": ParagraphStyle(
                'matrix_header', fontName='Helvetica-Bold', fontSize=7,
                textColor=BrandColors.WHITE, alignment=TA_CENTER
            ),
            "matrix_row_header": ParagraphStyle(
                'matrix_row_header', fontName='Helvetica-Bold', fontSize=7,
                textColor=BrandColors.NAVY, alignment=TA_CENTER
            ),
            "matrix_cell": ParagraphStyle(
                'matrix_cell', fontName='Helvetica', fontSize=7,
                textColor=BrandColors.NAVY, alignment=TA_CENTER
            ),
            "matrix_cell_highlight": ParagraphStyle(
                'matrix_cell_highlight', fontName='Helvetica-Bold', fontSize=7,
                textColor=BrandColors.NAVY, alignment=TA_CENTER
            ),
            "table_header": ParagraphStyle(
                'table_header', fontName='Helvetica-Bold', fontSize=7,
                textColor=BrandColors.WHITE, alignment=TA_CENTER
            ),
            "table_cell": ParagraphStyle(
                'table_cell', fontName='Helvetica', fontSize=8,
                textColor=BrandColors.NAVY, alignment=TA_LEFT
            ),
            "table_cell_center": ParagraphStyle(
                'table_cell_center', fontName='Helvetica', fontSize=8,
                textColor=BrandColors.NAVY, alignment=TA_CENTER
            ),
            "table_cell_right": ParagraphStyle(
                'table_cell_right', fontName='Helvetica', fontSize=8,
                textColor=BrandColors.NAVY, alignment=TA_RIGHT
            ),
        }
        return styles.get(style_name, getSampleStyleSheet()['Normal'])


# =============================================================================
# CONVERSION FROM PROJECTION TO PDF DATA
# =============================================================================

def projection_to_pdf_data(
    projection,  # RentProjection from rent_projection_engine
    property_address: str,
    bedrooms: int,
    bathrooms: float,
    square_footage: Optional[int] = None,
    property_value: Optional[float] = None,
    key_attributes: str = "",
    agent_name: str = "Agent Name",
    agent_email: str = "agent@example.com",
    agent_phone: str = "555-555-5555",
    company_website: str = "www.example.com",
) -> ProFormaData:
    """
    Convert a RentProjection to ProFormaData for PDF generation.
    
    This ensures the PDF always traces back to the projection engine.
    """
    # Build monthly data from projection
    monthly_data = []
    
    # Season mapping based on month
    season_map = {
        1: "Winter", 2: "Winter", 3: "Spring Break",
        4: "Spring", 5: "Spring", 6: "Summer (June)",
        7: "Summer (July)", 8: "Summer (August)", 9: "Fall (September)",
        10: "Fall (October)", 11: "Late Fall", 12: "Winter (December)"
    }
    
    for mp in projection.monthly_projections:
        monthly_data.append(MonthlyData(
            month=mp.month_name[:3] if hasattr(mp, 'month_name') else f"Month {mp.month}",
            season=season_map.get(mp.month, ""),
            days=mp.days_in_month,
            owner_use=0,
            available_nights=mp.days_in_month,
            nights_rented=mp.projected_nights_booked,
            unrented_nights=mp.days_in_month - mp.projected_nights_booked,
            target_rate=mp.avg_nightly_rate,
            acceptable_discount=0.0,
            lowest_target_rate=mp.avg_nightly_rate,
            occupancy_pct=mp.projected_occupancy,
            gross_revenue=mp.projected_revenue
        ))
    
    # Build sensitivity matrix
    base_net = projection.annual_net_revenue.expected
    sensitivity = []
    factors = [0.80, 0.90, 1.00, 1.10, 1.20]
    for rate_factor in factors:
        row = []
        for occ_factor in factors:
            row.append(base_net * rate_factor * occ_factor)
        sensitivity.append(row)
    
    return ProFormaData(
        property_address=property_address,
        bedrooms=bedrooms,
        bathrooms=bathrooms,
        square_footage=square_footage,
        property_value=property_value,
        key_attributes=key_attributes,
        property_link=None,
        total_gross_revenue=projection.annual_gross_revenue.expected,
        gross_revenue_low=projection.annual_gross_revenue.conservative,
        gross_revenue_high=projection.annual_gross_revenue.optimistic,
        total_net_revenue=projection.annual_net_revenue.expected,
        net_revenue_low=projection.annual_net_revenue.conservative,
        net_revenue_high=projection.annual_net_revenue.optimistic,
        commission_rate=projection.commission_rate,
        total_nights_rented=projection.projected_nights_booked,
        total_owner_days=0,
        occupancy_pct=projection.projected_occupancy,
        average_nightly_rate=projection.average_nightly_rate,
        monthly_data=monthly_data,
        sensitivity_matrix=sensitivity,
        agent_name=agent_name,
        agent_email=agent_email,
        agent_phone=agent_phone,
        company_website=company_website,
        prepared_date=date.today()
    )
