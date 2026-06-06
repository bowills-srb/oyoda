"""
Rental Projections Pro Forma Renderer.

Matches the Rentalz.com style pro forma with:
- Summary page with charts
- Detail page with monthly breakdown
- Sensitivity analysis
- Operator branding

This is operational/BD focused - monthly breakdown, seasonal rates, 
occupancy projections.
"""

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor, white, black
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, HRFlowable, Image
)
from reportlab.graphics.shapes import Drawing, Rect, String, Line
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.legends import Legend
from reportlab.graphics.widgets.markers import makeMarker

from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from io import BytesIO


# =============================================================================
# COLORS (Matching Rentalz/Beach Habitats style)
# =============================================================================

class ProFormaColors:
    """Color palette matching the pro forma style."""
    TEAL = HexColor("#1a7f7f")
    TEAL_DARK = HexColor("#156666")
    TEAL_LIGHT = HexColor("#e6f3f3")
    GOLD = HexColor("#c9a227")
    NAVY = HexColor("#2c3e50")
    CHARCOAL = HexColor("#34495e")
    GRAY = HexColor("#7f8c8d")
    LIGHT_GRAY = HexColor("#ecf0f1")
    WHITE = white
    BLACK = black
    
    # Chart colors
    BAR_BLUE = HexColor("#3498db")
    BAR_TEAL = HexColor("#1abc9c")


# =============================================================================
# STYLES
# =============================================================================

def get_proforma_styles():
    """Create pro forma specific styles."""
    styles = getSampleStyleSheet()
    
    styles.add(ParagraphStyle(
        name='ProFormaTitle',
        fontSize=24,
        textColor=ProFormaColors.TEAL_DARK,
        alignment=TA_CENTER,
        spaceAfter=4,
        fontName='Helvetica-Bold',
    ))
    
    styles.add(ParagraphStyle(
        name='PropertyAddress',
        fontSize=14,
        textColor=ProFormaColors.CHARCOAL,
        alignment=TA_CENTER,
        spaceAfter=12,
        fontName='Helvetica',
    ))
    
    styles.add(ParagraphStyle(
        name='BigNumber',
        fontSize=28,
        textColor=ProFormaColors.TEAL_DARK,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold',
    ))
    
    styles.add(ParagraphStyle(
        name='BigNumberLabel',
        fontSize=10,
        textColor=ProFormaColors.CHARCOAL,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold',
    ))
    
    styles.add(ParagraphStyle(
        name='RangeText',
        fontSize=9,
        textColor=ProFormaColors.GRAY,
        alignment=TA_CENTER,
        fontName='Helvetica',
    ))
    
    styles.add(ParagraphStyle(
        name='MetricValue',
        fontSize=18,
        textColor=ProFormaColors.TEAL_DARK,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold',
    ))
    
    styles.add(ParagraphStyle(
        name='MetricLabel',
        fontSize=9,
        textColor=ProFormaColors.CHARCOAL,
        alignment=TA_CENTER,
        fontName='Helvetica',
    ))
    
    styles.add(ParagraphStyle(
        name='SectionTitle',
        fontSize=12,
        textColor=ProFormaColors.TEAL_DARK,
        spaceBefore=12,
        spaceAfter=8,
        fontName='Helvetica-Bold',
    ))
    
    styles.add(ParagraphStyle(
        name='PreparedBy',
        fontSize=10,
        textColor=ProFormaColors.CHARCOAL,
        fontName='Helvetica-Bold',
    ))
    
    styles.add(ParagraphStyle(
        name='ContactInfo',
        fontSize=9,
        textColor=ProFormaColors.GRAY,
        fontName='Helvetica',
    ))
    
    styles.add(ParagraphStyle(
        name='FooterText',
        fontSize=8,
        textColor=ProFormaColors.GRAY,
        alignment=TA_CENTER,
        fontName='Helvetica',
    ))
    
    styles.add(ParagraphStyle(
        name='PageTitle',
        fontSize=20,
        textColor=ProFormaColors.TEAL_DARK,
        alignment=TA_CENTER,
        spaceAfter=4,
        fontName='Helvetica-Bold',
    ))
    
    return styles


# =============================================================================
# PRO FORMA RENDERER
# =============================================================================

class RentalProFormaRenderer:
    """
    Renders Rental Projections Pro Forma PDFs.
    
    Matches the Rentalz.com/Beach Habitats style:
    - Page 1: Summary with charts
    - Page 2: Detailed monthly breakdown
    """
    
    def __init__(self):
        self.styles = get_proforma_styles()
        self.page_width, self.page_height = letter
        self.margin = 0.5 * inch
    
    def render(
        self,
        data: Dict[str, Any],
        output_path: str,
        branding: Optional[Dict] = None,
    ) -> str:
        """
        Render a rental pro forma to PDF.
        
        Args:
            data: Pro forma data
            output_path: Where to save PDF
            branding: Operator branding info
        
        Returns:
            Path to generated PDF
        """
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
        story.extend(self._render_summary_page(data, branding))
        
        story.append(PageBreak())
        
        # === PAGE 2: Details ===
        story.extend(self._render_details_page(data, branding))
        
        doc.build(story)
        
        return output_path
    
    def _render_summary_page(self, data: Dict, branding: Optional[Dict]) -> list:
        """Render the summary page."""
        story = []
        
        # Header with logo placeholder and title
        story.extend(self._render_header(data, branding))
        
        # Revenue summary boxes
        story.extend(self._render_revenue_summary(data))
        
        # Key metrics row
        story.extend(self._render_key_metrics(data))
        
        # Monthly revenue chart (as table representation)
        story.extend(self._render_monthly_revenue_chart(data))
        
        # Occupancy section
        story.extend(self._render_occupancy_section(data))
        
        # ADR section
        story.extend(self._render_adr_section(data))
        
        # Bottom section: Prepared by + Sensitivity
        story.extend(self._render_bottom_section(data, branding))
        
        # Footer
        story.extend(self._render_footer())
        
        return story
    
    def _render_header(self, data: Dict, branding: Optional[Dict]) -> list:
        """Render header with branding and title."""
        story = []
        
        # Company name/logo area
        company = branding.get('company_name', 'RENTAL COMPANY') if branding else 'RENTAL COMPANY'
        
        header_data = [[
            Paragraph(f"<b>{company}</b>", self.styles['PreparedBy']),
            Paragraph("Rental Projections Pro Forma Summary", self.styles['ProFormaTitle']),
            "",  # Placeholder for right side
        ]]
        
        header_table = Table(header_data, colWidths=[1.8*inch, 4.4*inch, 1.3*inch])
        header_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (0, 0), 'LEFT'),
            ('ALIGN', (1, 0), (1, 0), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        story.append(header_table)
        
        # Property address
        address = data.get('address', '123 Property Address')
        story.append(Paragraph(address, self.styles['PropertyAddress']))
        
        story.append(Spacer(1, 8))
        
        return story
    
    def _render_revenue_summary(self, data: Dict) -> list:
        """Render the main revenue summary boxes."""
        story = []
        
        gross = data.get('gross_revenue', 161367)
        gross_low = data.get('gross_revenue_low', 131000)
        gross_high = data.get('gross_revenue_high', 195000)
        
        net = data.get('net_revenue', 129094)
        net_low = data.get('net_revenue_low', 105000)
        net_high = data.get('net_revenue_high', 156000)
        commission = data.get('commission_pct', 20)
        
        # Two column layout for gross and net
        revenue_data = [[
            # Gross Revenue
            [
                Paragraph("Total Projected Gross Revenue:", self.styles['BigNumberLabel']),
                Paragraph(f"${gross:,.0f}", self.styles['BigNumber']),
                Paragraph(f"(From ${gross_low:,.0f} to ${gross_high:,.0f} based on market conditions and pricing)", self.styles['RangeText']),
            ],
            # Net Revenue
            [
                Paragraph("Total Projected NET proceeds:", self.styles['BigNumberLabel']),
                Paragraph(f"${net:,.0f}", self.styles['BigNumber']),
                Paragraph(f"(From ${net_low:,.0f} to ${net_high:,.0f} based on market conditions, pricing, and net of {commission}% commission)", self.styles['RangeText']),
            ],
        ]]
        
        rev_table = Table(revenue_data, colWidths=[3.75*inch, 3.75*inch])
        rev_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ]))
        story.append(rev_table)
        
        story.append(Spacer(1, 12))
        
        return story
    
    def _render_key_metrics(self, data: Dict) -> list:
        """Render the key metrics row."""
        story = []
        
        nights = data.get('nights_rented', 174)
        owner_days = data.get('owner_days', 0)
        occupancy = data.get('occupancy', 0.48)
        adr = data.get('adr', 927)
        
        metrics_data = [[
            [
                Paragraph(f"{nights}", self.styles['MetricValue']),
                Paragraph("Total Projected Nights Rented", self.styles['MetricLabel']),
            ],
            [
                Paragraph(f"{owner_days}", self.styles['MetricValue']),
                Paragraph("Total Days Owner Enjoyment", self.styles['MetricLabel']),
            ],
            [
                Paragraph(f"{occupancy:.0%}", self.styles['MetricValue']),
                Paragraph("Occupancy", self.styles['MetricLabel']),
            ],
            [
                Paragraph(f"${adr:,.0f}", self.styles['MetricValue']),
                Paragraph("Average Nightly Rate", self.styles['MetricLabel']),
            ],
        ]]
        
        metrics_table = Table(metrics_data, colWidths=[1.875*inch, 1.875*inch, 1.875*inch, 1.875*inch])
        metrics_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('BOX', (0, 0), (-1, -1), 1, ProFormaColors.LIGHT_GRAY),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, ProFormaColors.LIGHT_GRAY),
            ('BACKGROUND', (0, 0), (-1, -1), ProFormaColors.TEAL_LIGHT),
            ('PADDING', (0, 0), (-1, -1), 8),
        ]))
        story.append(metrics_table)
        
        story.append(Spacer(1, 8))
        
        return story
    
    def _render_monthly_revenue_chart(self, data: Dict) -> list:
        """Render monthly revenue as a table-based chart representation."""
        story = []
        
        gross = data.get('gross_revenue', 161367)
        story.append(Paragraph(
            f"Total Projected Gross Revenue: ${gross:,.0f}",
            self.styles['SectionTitle']
        ))
        
        # Monthly data
        monthly = data.get('monthly_revenue', {
            'Jan': 0, 'Feb': 0, 'Mar': 24444, 'Apr': 6770,
            'May': 17250, 'Jun': 34500, 'Jul': 39700, 'Aug': 13718,
            'Sep': 7700, 'Oct': 8250, 'Nov': 6185, 'Dec': 2850
        })
        
        months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
        values = [monthly.get(m, 0) for m in months]
        max_val = max(values) if max(values) > 0 else 40000
        
        # Create bar representation as colored cells
        chart_rows = []
        
        # Value labels row
        value_row = [f"${v:,.0f}" if v > 0 else "$0" for v in values]
        chart_rows.append(value_row)
        
        # Bar representation (using background shading)
        bar_heights = [int((v / max_val) * 5) for v in values]  # 0-5 scale
        for level in range(5, 0, -1):
            row = []
            for h in bar_heights:
                if h >= level:
                    row.append("█")  # Filled
                else:
                    row.append("")
            chart_rows.append(row)
        
        # Month labels
        chart_rows.append(months)
        
        col_width = 0.58 * inch
        chart_table = Table(chart_rows, colWidths=[col_width] * 12)
        chart_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTSIZE', (0, 0), (-1, 0), 7),  # Value labels
            ('FONTSIZE', (0, -1), (-1, -1), 8),  # Month labels
            ('TEXTCOLOR', (0, 1), (-1, -2), ProFormaColors.BAR_TEAL),  # Bars
            ('FONTNAME', (0, 1), (-1, -2), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 1), (-1, -2), 14),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
            ('TOPPADDING', (0, 0), (-1, -1), 1),
        ]))
        story.append(chart_table)
        
        story.append(Spacer(1, 8))
        
        return story
    
    def _render_occupancy_section(self, data: Dict) -> list:
        """Render occupancy visualization."""
        story = []
        
        occupancy = data.get('occupancy', 0.48)
        nights = data.get('nights_rented', 174)
        total_nights = 365 - data.get('owner_days', 0)
        unrented = total_nights - nights
        
        # Occupancy header with pie representation
        occ_header = [[
            Paragraph(f"<b>Occupancy</b>", self.styles['SectionTitle']),
            Paragraph(f"<font size='16' color='#1a7f7f'><b>{occupancy:.0%}</b></font>", self.styles['SectionTitle']),
        ]]
        occ_table = Table(occ_header, colWidths=[1.5*inch, 1*inch])
        story.append(occ_table)
        
        # Legend
        legend_data = [[
            "█ Nights Rented", "█ Owner Use", "█ Unrented Nights"
        ]]
        legend_table = Table(legend_data, colWidths=[1.5*inch, 1.2*inch, 1.5*inch])
        legend_table.setStyle(TableStyle([
            ('TEXTCOLOR', (0, 0), (0, 0), ProFormaColors.TEAL),
            ('TEXTCOLOR', (1, 0), (1, 0), ProFormaColors.GOLD),
            ('TEXTCOLOR', (2, 0), (2, 0), ProFormaColors.GRAY),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
        ]))
        story.append(legend_table)
        
        # Monthly occupancy
        monthly_occ = data.get('monthly_occupancy', {
            'Jan': 0, 'Feb': 0, 'Mar': 1.0, 'Apr': 0.33,
            'May': 0.61, 'Jun': 1.0, 'Jul': 1.0, 'Aug': 0.43,
            'Sep': 0.47, 'Oct': 0.48, 'Nov': 0.29, 'Dec': 0.09
        })
        
        months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
        
        occ_row = [f"{monthly_occ.get(m, 0):.0%}" for m in months]
        unrented_row = [f"{1-monthly_occ.get(m, 0):.0%}" if monthly_occ.get(m, 0) < 1 else "" for m in months]
        
        occ_data = [
            occ_row,
            unrented_row,
            months,
        ]
        
        col_width = 0.58 * inch
        occ_table = Table(occ_data, colWidths=[col_width] * 12)
        occ_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTSIZE', (0, 0), (-1, -1), 7),
            ('TEXTCOLOR', (0, 0), (-1, 0), ProFormaColors.TEAL),
            ('TEXTCOLOR', (0, 1), (-1, 1), ProFormaColors.GRAY),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ]))
        story.append(occ_table)
        
        story.append(Spacer(1, 8))
        
        return story
    
    def _render_adr_section(self, data: Dict) -> list:
        """Render ADR section."""
        story = []
        
        adr = data.get('adr', 927)
        story.append(Paragraph(f"Average Nightly Rate: ${adr:,.0f}", self.styles['SectionTitle']))
        
        # Monthly ADR
        monthly_adr = data.get('monthly_adr', {
            'Jan': 0, 'Feb': 0, 'Mar': 873, 'Apr': 677,
            'May': 908, 'Jun': 1150, 'Jul': 1203, 'Aug': 1055,
            'Sep': 550, 'Oct': 550, 'Nov': 687, 'Dec': 950
        })
        
        months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
        adr_row = [f"${monthly_adr.get(m, 0):,.0f}" if monthly_adr.get(m, 0) > 0 else "$0" for m in months]
        
        adr_data = [
            adr_row,
            months,
        ]
        
        col_width = 0.58 * inch
        adr_table = Table(adr_data, colWidths=[col_width] * 12)
        adr_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTSIZE', (0, 0), (-1, -1), 7),
            ('TEXTCOLOR', (0, 0), (-1, 0), ProFormaColors.TEAL_DARK),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ]))
        story.append(adr_table)
        
        story.append(Spacer(1, 8))
        
        return story
    
    def _render_bottom_section(self, data: Dict, branding: Optional[Dict]) -> list:
        """Render bottom section with contact info and sensitivity analysis."""
        story = []
        
        # Two columns: Prepared By + Sensitivity Analysis
        prep_name = branding.get('prepared_by', 'Agent Name') if branding else 'Agent Name'
        prep_email = branding.get('email', 'agent@company.com') if branding else 'agent@company.com'
        prep_phone = branding.get('phone', '555-555-5555') if branding else '555-555-5555'
        prep_website = branding.get('website', 'www.company.com') if branding else 'www.company.com'
        
        # Prepared By section
        prep_content = [
            Paragraph("<b>Rental Projections Prepared By</b>", self.styles['PreparedBy']),
            Spacer(1, 4),
            Paragraph(f"<b>{prep_name}</b>", self.styles['PreparedBy']),
            Paragraph(prep_email, self.styles['ContactInfo']),
            Paragraph(prep_phone, self.styles['ContactInfo']),
            Paragraph(prep_website, self.styles['ContactInfo']),
            Spacer(1, 4),
            Paragraph(datetime.now().strftime("%B %d, %Y"), self.styles['ContactInfo']),
        ]
        
        # Sensitivity Analysis
        sensitivity = self._build_sensitivity_table(data)
        
        bottom_data = [[
            prep_content,
            [
                Paragraph("<b>Sensitivity Analysis</b>", self.styles['SectionTitle']),
                sensitivity,
            ],
        ]]
        
        bottom_table = Table(bottom_data, colWidths=[2.5*inch, 5*inch])
        bottom_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))
        story.append(bottom_table)
        
        return story
    
    def _build_sensitivity_table(self, data: Dict) -> Table:
        """Build the sensitivity analysis matrix."""
        base_revenue = data.get('gross_revenue', 161367)
        
        # Sensitivity matrix: Nights Rented vs ADR variations
        variations = [0.8, 0.9, 1.0, 1.1, 1.2]
        
        # Header row
        header = ['', 'Nights Rented'] + [''] * 4
        subheader = ['', '80%', '90%', '100%', '110%', '120%']
        
        rows = [subheader]
        
        labels = ['80%', '90%', '100%', '110%', '120%']
        for i, adr_mult in enumerate(variations):
            row = [labels[i]]
            for nights_mult in variations:
                val = base_revenue * adr_mult * nights_mult
                row.append(f"${val:,.0f}")
            rows.append(row)
        
        # Add row label for first column
        sens_data = [
            ['', '', 'Nights Rented', '', '', ''],
            subheader,
        ] + rows
        
        sens_table = Table(sens_data, colWidths=[0.6*inch, 0.75*inch, 0.75*inch, 0.75*inch, 0.75*inch, 0.75*inch])
        sens_table.setStyle(TableStyle([
            ('SPAN', (2, 0), (5, 0)),  # Span "Nights Rented" header
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTSIZE', (0, 0), (-1, -1), 7),
            ('BACKGROUND', (1, 1), (-1, 1), ProFormaColors.TEAL),  # Header row
            ('TEXTCOLOR', (1, 1), (-1, 1), ProFormaColors.WHITE),
            ('BACKGROUND', (0, 2), (0, -1), ProFormaColors.TEAL),  # Left column
            ('TEXTCOLOR', (0, 2), (0, -1), ProFormaColors.WHITE),
            ('GRID', (1, 1), (-1, -1), 0.5, ProFormaColors.LIGHT_GRAY),
            ('FONTNAME', (1, 1), (-1, 1), 'Helvetica-Bold'),
            ('FONTNAME', (0, 2), (0, -1), 'Helvetica-Bold'),
            # Highlight center cell (100%/100%)
            ('BACKGROUND', (3, 4), (3, 4), ProFormaColors.TEAL_LIGHT),
            ('FONTNAME', (3, 4), (3, 4), 'Helvetica-Bold'),
        ]))
        
        return sens_table
    
    def _render_footer(self) -> list:
        """Render page footer."""
        story = []
        story.append(Spacer(1, 8))
        story.append(Paragraph("© Rentalz.com", self.styles['FooterText']))
        return story
    
    def _render_details_page(self, data: Dict, branding: Optional[Dict]) -> list:
        """Render the detailed monthly breakdown page."""
        story = []
        
        # Header
        company = branding.get('company_name', 'RENTAL COMPANY') if branding else 'RENTAL COMPANY'
        
        story.append(Paragraph("Rental Projections Pro Forma Details", self.styles['PageTitle']))
        story.append(Paragraph(data.get('address', '123 Property Address'), self.styles['PropertyAddress']))
        
        # Property details box
        story.extend(self._render_property_details(data))
        
        # Monthly breakdown table
        story.extend(self._render_monthly_breakdown(data))
        
        # Footer
        story.extend(self._render_footer())
        
        return story
    
    def _render_property_details(self, data: Dict) -> list:
        """Render property details box."""
        story = []
        
        beds = data.get('bedrooms', 5)
        baths = data.get('bathrooms', 5)
        sqft = data.get('sqft', 3338)
        value = data.get('property_value', 3395000)
        attributes = data.get('key_attributes', 'Private Pool, Carriage House!')
        link = data.get('property_link', 'n/a')
        
        details_data = [
            [f"Bedrooms: {beds}", f"Bathrooms: {baths}", f"Square Footage: {sqft:,}"],
            [f"Property Value / Listed Price: ${value:,.0f}", "", ""],
            [f"Key Attributes: {attributes}", "", ""],
            [f"Property Link: {link}", "", ""],
        ]
        
        details_table = Table(details_data, colWidths=[2.5*inch, 2.5*inch, 2.5*inch])
        details_table.setStyle(TableStyle([
            ('BOX', (0, 0), (-1, -1), 1, ProFormaColors.TEAL),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('PADDING', (0, 0), (-1, -1), 4),
            ('SPAN', (0, 1), (-1, 1)),
            ('SPAN', (0, 2), (-1, 2)),
            ('SPAN', (0, 3), (-1, 3)),
        ]))
        story.append(details_table)
        
        story.append(Spacer(1, 12))
        
        return story
    
    def _render_monthly_breakdown(self, data: Dict) -> list:
        """Render the detailed monthly breakdown table."""
        story = []
        
        # Get monthly data
        seasons = data.get('seasons', self._default_seasons())
        
        # Header row
        headers = [
            'Month', 'Season', 'Number\nof Days', 'Owner\nUse', 'Available\nNights',
            'Nights\nRented', 'Unrented\nNights', 'Target\nRates', 'Acceptable\nDiscount',
            'Lowest\nTarget Rate', 'Occupancy\n%', 'Gross\nRevenue'
        ]
        
        rows = [headers]
        
        totals = {'days': 0, 'owner': 0, 'available': 0, 'rented': 0, 'unrented': 0, 'revenue': 0}
        
        for season in seasons:
            row = [
                season['month'],
                season['season'],
                str(season['days']),
                str(season['owner_use']),
                str(season['available']),
                str(season['rented']),
                str(season['unrented']),
                f"${season['rate']:,.0f}",
                f"{season['discount']}%",
                f"${season['lowest_rate']:,.0f}",
                f"{season['occupancy']:.0%}",
                f"${season['revenue']:,.0f}",
            ]
            rows.append(row)
            
            totals['days'] += season['days']
            totals['owner'] += season['owner_use']
            totals['available'] += season['available']
            totals['rented'] += season['rented']
            totals['unrented'] += season['unrented']
            totals['revenue'] += season['revenue']
        
        # Totals row
        adr = data.get('adr', 927)
        occupancy = data.get('occupancy', 0.48)
        totals_row = [
            '', 'Totals', str(totals['days']), str(totals['owner']), 
            str(totals['available']), str(totals['rented']), str(totals['unrented']),
            '', '', f"${adr:,.0f}", f"{occupancy:.0%}", f"${totals['revenue']:,.0f}"
        ]
        rows.append(totals_row)
        
        col_widths = [0.55*inch, 0.9*inch, 0.45*inch, 0.4*inch, 0.5*inch, 
                      0.45*inch, 0.5*inch, 0.5*inch, 0.55*inch, 0.55*inch, 0.55*inch, 0.6*inch]
        
        breakdown_table = Table(rows, colWidths=col_widths)
        breakdown_table.setStyle(TableStyle([
            # Header
            ('BACKGROUND', (0, 0), (-1, 0), ProFormaColors.TEAL),
            ('TEXTCOLOR', (0, 0), (-1, 0), ProFormaColors.WHITE),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 7),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('ALIGN', (0, 1), (1, -1), 'LEFT'),
            # Grid
            ('GRID', (0, 0), (-1, -1), 0.5, ProFormaColors.LIGHT_GRAY),
            # Alternating rows
            ('ROWBACKGROUNDS', (0, 1), (-1, -2), [ProFormaColors.WHITE, HexColor("#f8f9fa")]),
            # Totals row
            ('BACKGROUND', (0, -1), (-1, -1), ProFormaColors.TEAL),
            ('TEXTCOLOR', (0, -1), (-1, -1), ProFormaColors.WHITE),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            # Padding
            ('PADDING', (0, 0), (-1, -1), 2),
        ]))
        story.append(breakdown_table)
        
        return story
    
    def _default_seasons(self) -> list:
        """Return default seasonal breakdown matching the example."""
        return [
            {'month': 'January', 'season': 'Winter', 'days': 31, 'owner_use': 0, 'available': 31, 'rented': 0, 'unrented': 31, 'rate': 500, 'discount': 0, 'lowest_rate': 500, 'occupancy': 0, 'revenue': 0},
            {'month': 'February', 'season': 'Winter', 'days': 28, 'owner_use': 0, 'available': 28, 'rented': 0, 'unrented': 28, 'rate': 500, 'discount': 0, 'lowest_rate': 500, 'occupancy': 0, 'revenue': 0},
            {'month': 'March', 'season': 'Spring Break', 'days': 7, 'owner_use': 0, 'available': 7, 'rented': 7, 'unrented': 0, 'rate': 864, 'discount': 0, 'lowest_rate': 864, 'occupancy': 1.0, 'revenue': 6048},
            {'month': 'March', 'season': 'Peak Spring Break', 'days': 21, 'owner_use': 0, 'available': 21, 'rented': 21, 'unrented': 0, 'rate': 876, 'discount': 0, 'lowest_rate': 876, 'occupancy': 1.0, 'revenue': 18396},
            {'month': 'April', 'season': 'Spring', 'days': 30, 'owner_use': 0, 'available': 30, 'rented': 10, 'unrented': 20, 'rate': 677, 'discount': 0, 'lowest_rate': 677, 'occupancy': 0.33, 'revenue': 6770},
            {'month': 'May', 'season': 'Spring', 'days': 24, 'owner_use': 0, 'available': 24, 'rented': 12, 'unrented': 12, 'rate': 650, 'discount': 0, 'lowest_rate': 650, 'occupancy': 0.50, 'revenue': 7800},
            {'month': 'May', 'season': 'Memorial Day', 'days': 7, 'owner_use': 0, 'available': 7, 'rented': 7, 'unrented': 0, 'rate': 1350, 'discount': 0, 'lowest_rate': 1350, 'occupancy': 1.0, 'revenue': 9450},
            {'month': 'June', 'season': 'Summer (June)', 'days': 30, 'owner_use': 0, 'available': 30, 'rented': 30, 'unrented': 0, 'rate': 1150, 'discount': 0, 'lowest_rate': 1150, 'occupancy': 1.0, 'revenue': 34500},
            {'month': 'July', 'season': '4th of July', 'days': 7, 'owner_use': 0, 'available': 7, 'rented': 7, 'unrented': 0, 'rate': 1400, 'discount': 0, 'lowest_rate': 1400, 'occupancy': 1.0, 'revenue': 9800},
            {'month': 'July', 'season': 'Summer (July)', 'days': 26, 'owner_use': 0, 'available': 26, 'rented': 26, 'unrented': 0, 'rate': 1150, 'discount': 0, 'lowest_rate': 1150, 'occupancy': 1.0, 'revenue': 29900},
            {'month': 'August', 'season': 'Summer (August)', 'days': 10, 'owner_use': 0, 'available': 10, 'rented': 8, 'unrented': 2, 'rate': 1121, 'discount': 0, 'lowest_rate': 1121, 'occupancy': 0.80, 'revenue': 8968},
            {'month': 'August', 'season': 'Late Summer', 'days': 20, 'owner_use': 0, 'available': 20, 'rented': 5, 'unrented': 15, 'rate': 950, 'discount': 0, 'lowest_rate': 950, 'occupancy': 0.25, 'revenue': 4750},
            {'month': 'September', 'season': 'Labor Day', 'days': 4, 'owner_use': 0, 'available': 4, 'rented': 4, 'unrented': 0, 'rate': 550, 'discount': 0, 'lowest_rate': 550, 'occupancy': 1.0, 'revenue': 2200},
            {'month': 'September', 'season': 'Fall (September)', 'days': 26, 'owner_use': 0, 'available': 26, 'rented': 10, 'unrented': 16, 'rate': 550, 'discount': 0, 'lowest_rate': 550, 'occupancy': 0.38, 'revenue': 5500},
            {'month': 'October', 'season': 'Fall (October)', 'days': 31, 'owner_use': 0, 'available': 31, 'rented': 15, 'unrented': 16, 'rate': 550, 'discount': 0, 'lowest_rate': 550, 'occupancy': 0.48, 'revenue': 8250},
            {'month': 'November', 'season': 'Late Fall (November)', 'days': 26, 'owner_use': 0, 'available': 26, 'rented': 4, 'unrented': 22, 'rate': 500, 'discount': 0, 'lowest_rate': 500, 'occupancy': 0.15, 'revenue': 2000},
            {'month': 'November', 'season': 'Thanksgiving', 'days': 5, 'owner_use': 0, 'available': 5, 'rented': 5, 'unrented': 0, 'rate': 837, 'discount': 0, 'lowest_rate': 837, 'occupancy': 1.0, 'revenue': 4185},
            {'month': 'December', 'season': 'Winter (December)', 'days': 29, 'owner_use': 0, 'available': 29, 'rented': 0, 'unrented': 29, 'rate': 500, 'discount': 0, 'lowest_rate': 500, 'occupancy': 0, 'revenue': 0},
            {'month': 'December', 'season': 'New Years', 'days': 3, 'owner_use': 0, 'available': 3, 'rented': 3, 'unrented': 0, 'rate': 950, 'discount': 0, 'lowest_rate': 950, 'occupancy': 1.0, 'revenue': 2850},
        ]


# =============================================================================
# CONVENIENCE
# =============================================================================

def render_rental_proforma_pdf(
    data: Dict[str, Any],
    output_path: str,
    branding: Optional[Dict] = None,
) -> str:
    """
    Render a rental pro forma to PDF.
    
    Example:
        render_rental_proforma_pdf(
            {
                'address': '313 E Royal Fern Way',
                'gross_revenue': 161367,
                'net_revenue': 129094,
                'nights_rented': 174,
                'occupancy': 0.48,
                'adr': 927,
                'bedrooms': 5,
                'bathrooms': 5,
                ...
            },
            '/path/to/output.pdf',
            branding={
                'company_name': 'BEACH HABITATS',
                'prepared_by': 'Nick Smith',
                'email': 'Nick@beachhabitats30A.com',
                'phone': '850-585-1860',
                'website': 'www.beachhabitats30a.com',
            }
        )
    """
    renderer = RentalProFormaRenderer()
    return renderer.render(data, output_path, branding)
