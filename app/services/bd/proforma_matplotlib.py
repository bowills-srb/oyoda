"""
Rental Pro Forma - Matplotlib Edition.

Uses matplotlib for professional, publication-quality charts
combined with ReportLab for PDF assembly.

This produces visuals matching the Rentalz.com quality.
"""

import matplotlib
matplotlib.use('Agg')  # Non-interactive backend

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch
import numpy as np
from io import BytesIO
from datetime import datetime
from typing import Dict, Any, List, Optional

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor, white
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, Image as RLImage, KeepTogether
)


# =============================================================================
# COLORS - Matching Rentalz style
# =============================================================================

# Matplotlib colors (hex strings)
TEAL = '#0d7377'
TEAL_LIGHT = '#14a3a8'
TEAL_LIGHTER = '#e6f4f4'
GOLD = '#d4a72c'
GRAY = '#cbd5e0'
GRAY_DARK = '#4a5568'
GRAY_MED = '#718096'
WHITE = '#ffffff'

# ReportLab colors
class Colors:
    TEAL = HexColor('#0d7377')
    TEAL_LIGHT = HexColor('#e6f4f4')
    GRAY_DARK = HexColor('#4a5568')
    GRAY_MED = HexColor('#718096')
    GRAY_LIGHT = HexColor('#e2e8f0')
    WHITE = white


# =============================================================================
# MATPLOTLIB CHART GENERATORS
# =============================================================================

def create_revenue_chart(monthly_data: Dict[str, float], total: float) -> BytesIO:
    """Create the monthly revenue bar chart."""
    
    months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 
              'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    values = [monthly_data.get(m, 0) for m in months]
    
    fig, ax = plt.subplots(figsize=(7.5, 1.8))
    
    # Create gradient-like bars using a colormap
    bars = ax.bar(months, values, color=TEAL, edgecolor='none', width=0.7)
    
    # Add gradient effect by overlaying lighter color at top
    for bar, val in zip(bars, values):
        if val > 0:
            # Create gradient effect
            gradient = np.linspace(0, 1, 100)
            for i, g in enumerate(gradient):
                height = bar.get_height() * (i + 1) / 100
                color = plt.cm.colors.to_hex([
                    int(TEAL[1:3], 16)/255 * (1-g*0.3) + g*0.3 * int(TEAL_LIGHT[1:3], 16)/255,
                    int(TEAL[3:5], 16)/255 * (1-g*0.3) + g*0.3 * int(TEAL_LIGHT[3:5], 16)/255,
                    int(TEAL[5:7], 16)/255 * (1-g*0.3) + g*0.3 * int(TEAL_LIGHT[5:7], 16)/255,
                ])
    
    # Add value labels above bars
    for bar, val in zip(bars, values):
        if val > 0:
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + max(values)*0.02,
                   f'${val:,.0f}', ha='center', va='bottom', fontsize=7, color=GRAY_DARK)
        else:
            ax.text(bar.get_x() + bar.get_width()/2, max(values)*0.02,
                   '$0', ha='center', va='bottom', fontsize=7, color=GRAY_MED)
    
    # Style the chart
    ax.set_xlim(-0.5, 11.5)
    ax.set_ylim(0, max(values) * 1.15 if max(values) > 0 else 1000)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_visible(False)
    ax.spines['bottom'].set_color(GRAY)
    ax.tick_params(axis='x', colors=GRAY_DARK, labelsize=8)
    ax.tick_params(axis='y', left=False, labelleft=False)
    ax.set_facecolor(WHITE)
    fig.patch.set_facecolor(WHITE)
    
    plt.tight_layout(pad=0.5)
    
    # Save to BytesIO
    buf = BytesIO()
    plt.savefig(buf, format='png', dpi=150, bbox_inches='tight', 
                facecolor=WHITE, edgecolor='none')
    plt.close(fig)
    buf.seek(0)
    
    return buf


def create_occupancy_chart(monthly_occ: Dict[str, float], 
                           nights_rented: int, 
                           owner_days: int) -> BytesIO:
    """Create stacked occupancy bar chart."""
    
    months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 
              'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    occupied = [monthly_occ.get(m, 0) * 100 for m in months]
    unoccupied = [100 - occ for occ in occupied]
    
    fig, ax = plt.subplots(figsize=(7.5, 1.6))
    
    x = np.arange(len(months))
    width = 0.7
    
    # Stacked bars
    bars_occ = ax.bar(x, occupied, width, color=TEAL, label='Nights Rented')
    bars_unocc = ax.bar(x, unoccupied, width, bottom=occupied, color=GRAY, label='Unrented')
    
    # Add percentage labels inside bars
    for i, (occ, unocc) in enumerate(zip(occupied, unoccupied)):
        if occ > 0:
            ax.text(i, occ/2, f'{occ:.0f}%', ha='center', va='center', 
                   fontsize=6, color=WHITE, fontweight='bold')
        if unocc > 15 and occ < 85:
            ax.text(i, occ + unocc/2, f'{unocc:.0f}%', ha='center', va='center',
                   fontsize=6, color=GRAY_DARK)
    
    # Style
    ax.set_xticks(x)
    ax.set_xticklabels(months, fontsize=8, color=GRAY_DARK)
    ax.set_xlim(-0.5, 11.5)
    ax.set_ylim(0, 100)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_visible(False)
    ax.spines['bottom'].set_color(GRAY)
    ax.tick_params(axis='y', left=False, labelleft=False)
    ax.set_facecolor(WHITE)
    fig.patch.set_facecolor(WHITE)
    
    plt.tight_layout(pad=0.5)
    
    buf = BytesIO()
    plt.savefig(buf, format='png', dpi=150, bbox_inches='tight',
                facecolor=WHITE, edgecolor='none')
    plt.close(fig)
    buf.seek(0)
    
    return buf


def create_adr_chart(monthly_adr: Dict[str, float], avg_adr: float) -> BytesIO:
    """Create ADR bar chart."""
    
    months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 
              'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    values = [monthly_adr.get(m, 0) for m in months]
    max_val = max(v for v in values if v > 0) if any(v > 0 for v in values) else 1000
    
    fig, ax = plt.subplots(figsize=(7.5, 1.5))
    
    bars = ax.bar(months, values, color=TEAL, edgecolor='none', width=0.7)
    
    # Add value labels
    for bar, val in zip(bars, values):
        if val > 0:
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + max_val*0.02,
                   f'${val:,.0f}', ha='center', va='bottom', fontsize=7, color=GRAY_DARK)
        else:
            ax.text(bar.get_x() + bar.get_width()/2, max_val*0.02,
                   '$0', ha='center', va='bottom', fontsize=7, color=GRAY_MED)
    
    # Style
    ax.set_xlim(-0.5, 11.5)
    ax.set_ylim(0, max_val * 1.15)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_visible(False)
    ax.spines['bottom'].set_color(GRAY)
    ax.tick_params(axis='x', colors=GRAY_DARK, labelsize=8)
    ax.tick_params(axis='y', left=False, labelleft=False)
    ax.set_facecolor(WHITE)
    fig.patch.set_facecolor(WHITE)
    
    plt.tight_layout(pad=0.5)
    
    buf = BytesIO()
    plt.savefig(buf, format='png', dpi=150, bbox_inches='tight',
                facecolor=WHITE, edgecolor='none')
    plt.close(fig)
    buf.seek(0)
    
    return buf


def create_occupancy_pie(occupancy: float, nights: int, owner: int, total: int) -> BytesIO:
    """Create occupancy pie chart."""
    
    unrented = total - nights - owner
    
    fig, ax = plt.subplots(figsize=(1.2, 1.2))
    
    sizes = [nights, owner, unrented] if owner > 0 else [nights, unrented]
    colors_list = [TEAL, GOLD, GRAY] if owner > 0 else [TEAL, GRAY]
    
    # Remove zero values
    filtered = [(s, c) for s, c in zip(sizes, colors_list) if s > 0]
    if filtered:
        sizes, colors_list = zip(*filtered)
    else:
        sizes, colors_list = [1], [GRAY]
    
    wedges, _ = ax.pie(sizes, colors=colors_list, startangle=90,
                       wedgeprops=dict(width=0.4, edgecolor=WHITE))
    
    # Center text
    ax.text(0, 0, f'{occupancy:.0%}', ha='center', va='center',
           fontsize=14, fontweight='bold', color=TEAL)
    
    ax.set_facecolor(WHITE)
    fig.patch.set_facecolor(WHITE)
    
    buf = BytesIO()
    plt.savefig(buf, format='png', dpi=150, bbox_inches='tight',
                facecolor=WHITE, edgecolor='none')
    plt.close(fig)
    buf.seek(0)
    
    return buf


# =============================================================================
# REPORTLAB STYLES
# =============================================================================

def get_styles():
    """Create document styles."""
    styles = getSampleStyleSheet()
    
    styles.add(ParagraphStyle(
        name='PFMainTitle',
        fontSize=16,
        textColor=Colors.TEAL,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold',
        spaceAfter=6,
        leading=18,
    ))
    
    styles.add(ParagraphStyle(
        name='PFAddress',
        fontSize=10,
        textColor=Colors.GRAY_DARK,
        alignment=TA_CENTER,
        fontName='Helvetica',
        spaceAfter=10,
        leading=12,
    ))
    
    styles.add(ParagraphStyle(
        name='PFSectionTitle',
        fontSize=10,
        textColor=Colors.TEAL,
        fontName='Helvetica-Bold',
        spaceBefore=8,
        spaceAfter=4,
    ))
    
    styles.add(ParagraphStyle(
        name='PFLargeNum',
        fontSize=20,
        textColor=Colors.TEAL,
        fontName='Helvetica-Bold',
        leading=24,
    ))
    
    styles.add(ParagraphStyle(
        name='PFLabel',
        fontSize=9,
        textColor=Colors.GRAY_DARK,
        fontName='Helvetica-Bold',
        leading=11,
    ))
    
    styles.add(ParagraphStyle(
        name='PFSubtext',
        fontSize=7,
        textColor=Colors.GRAY_MED,
        fontName='Helvetica',
        leading=9,
    ))
    
    styles.add(ParagraphStyle(
        name='PFMetricVal',
        fontSize=14,
        textColor=Colors.TEAL,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold',
    ))
    
    styles.add(ParagraphStyle(
        name='PFMetricLbl',
        fontSize=7,
        textColor=Colors.GRAY_DARK,
        alignment=TA_CENTER,
        fontName='Helvetica',
    ))
    
    styles.add(ParagraphStyle(
        name='PFPrepBy',
        fontSize=9,
        textColor=Colors.GRAY_DARK,
        fontName='Helvetica-Bold',
    ))
    
    styles.add(ParagraphStyle(
        name='PFContact',
        fontSize=8,
        textColor=Colors.GRAY_MED,
        fontName='Helvetica',
    ))
    
    styles.add(ParagraphStyle(
        name='PFPageTitle',
        fontSize=16,
        textColor=Colors.TEAL,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold',
        spaceAfter=2,
    ))
    
    styles.add(ParagraphStyle(
        name='PFBody',
        fontSize=8,
        textColor=Colors.GRAY_DARK,
        fontName='Helvetica',
    ))
    
    styles.add(ParagraphStyle(
        name='PFDisclaimer',
        fontSize=7,
        textColor=Colors.GRAY_MED,
        alignment=TA_CENTER,
        fontName='Helvetica-Oblique',
    ))
    
    return styles


# =============================================================================
# PDF RENDERER
# =============================================================================

class MatplotlibProFormaRenderer:
    """Render pro forma using matplotlib charts."""
    
    def __init__(self):
        self.styles = get_styles()
        self.page_width, self.page_height = letter
        self.margin = 0.5 * inch
        self.content_width = self.page_width - (2 * self.margin)
    
    def render(self, data: Dict[str, Any], output_path: str, 
               branding: Optional[Dict] = None) -> str:
        """Render the pro forma to PDF."""
        
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
        
        # Page 1
        story.extend(self._build_page1(data, branding))
        story.append(PageBreak())
        
        # Page 2
        story.extend(self._build_page2(data, branding))
        
        doc.build(story)
        return output_path
    
    def _build_page1(self, data: Dict, branding: Dict) -> list:
        """Build page 1 with charts."""
        story = []
        
        # Header
        company = branding.get('company_name', '')
        address = data.get('address', '')
        
        # Build header with proper spacing
        story.append(Spacer(1, 4))
        
        header_data = [[
            Paragraph(f"<font color='#0d7377'><b>{company}</b></font>", self.styles['PFPrepBy']),
            Paragraph("Rental Projections Pro Forma Summary", self.styles['PFMainTitle']),
            "",
        ]]
        header_table = Table(header_data, colWidths=[1.5*inch, 4.8*inch, 1*inch])
        header_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ALIGN', (1, 0), (1, 0), 'CENTER'),
        ]))
        story.append(header_table)
        
        # Address on separate line
        story.append(Paragraph(address, self.styles['PFAddress']))
        
        # Revenue summary
        story.extend(self._build_revenue_summary(data))
        
        # Metrics strip
        story.extend(self._build_metrics_strip(data))
        
        # Revenue chart
        gross = data.get('gross_revenue', 0)
        story.append(Paragraph(
            f"Total Projected Gross Revenue: ${gross:,.0f}",
            self.styles['PFSectionTitle']
        ))
        
        rev_chart = create_revenue_chart(
            data.get('monthly_revenue', {}),
            gross
        )
        story.append(RLImage(rev_chart, width=self.content_width, height=1.3*inch))
        
        # Occupancy section
        story.extend(self._build_occupancy_header(data))
        
        occ_chart = create_occupancy_chart(
            data.get('monthly_occupancy', {}),
            data.get('nights_rented', 0),
            data.get('owner_days', 0)
        )
        story.append(RLImage(occ_chart, width=self.content_width, height=1.2*inch))
        
        # ADR section
        adr = data.get('adr', 0)
        story.append(Paragraph(
            f"Average Nightly Rate: ${adr:,.0f}",
            self.styles['PFSectionTitle']
        ))
        
        adr_chart = create_adr_chart(data.get('monthly_adr', {}), adr)
        story.append(RLImage(adr_chart, width=self.content_width, height=1.1*inch))
        
        # Bottom section
        story.extend(self._build_bottom_section(data, branding))
        
        return story
    
    def _build_revenue_summary(self, data: Dict) -> list:
        """Build revenue summary boxes."""
        story = []
        
        gross = data.get('gross_revenue', 0)
        gross_low = data.get('gross_revenue_low', gross * 0.8)
        gross_high = data.get('gross_revenue_high', gross * 1.2)
        net = data.get('net_revenue', gross * 0.8)
        net_low = data.get('net_revenue_low', net * 0.8)
        net_high = data.get('net_revenue_high', net * 1.2)
        commission = data.get('commission_pct', 20)
        
        # Create properly spaced content for each box with explicit row heights
        gross_cell = Table([
            [Paragraph("Total Projected Gross Revenue:", self.styles['PFLabel'])],
            [Paragraph(f"${gross:,.0f}", self.styles['PFLargeNum'])],
            [Paragraph(
                f"(From ${gross_low:,.0f} to ${gross_high:,.0f} based on market conditions)",
                self.styles['PFSubtext']
            )],
        ], colWidths=[3.5*inch], rowHeights=[14, 28, 12])
        gross_cell.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ]))
        
        net_cell = Table([
            [Paragraph("Total Projected NET proceeds:", self.styles['PFLabel'])],
            [Paragraph(f"${net:,.0f}", self.styles['PFLargeNum'])],
            [Paragraph(
                f"(From ${net_low:,.0f} to ${net_high:,.0f} net of {commission}% commission)",
                self.styles['PFSubtext']
            )],
        ], colWidths=[3.5*inch], rowHeights=[14, 28, 12])
        net_cell.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ]))
        
        rev_table = Table([[gross_cell, net_cell]], colWidths=[3.65*inch, 3.65*inch])
        rev_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('PADDING', (0, 0), (-1, -1), 4),
        ]))
        story.append(rev_table)
        story.append(Spacer(1, 8))
        
        return story
    
    def _build_metrics_strip(self, data: Dict) -> list:
        """Build key metrics strip."""
        story = []
        
        metrics = [
            (f"{data.get('nights_rented', 0)}", "Total Projected Nights Rented"),
            (f"{data.get('owner_days', 0)}", "Total Days Owner Enjoyment"),
            (f"{data.get('occupancy', 0):.0%}", "Occupancy"),
            (f"${data.get('adr', 0):,.0f}", "Average Nightly Rate"),
        ]
        
        cells = []
        for val, lbl in metrics:
            cells.append([
                Paragraph(val, self.styles['PFMetricVal']),
                Paragraph(lbl, self.styles['PFMetricLbl']),
            ])
        
        metrics_table = Table([cells], colWidths=[1.825*inch] * 4)
        metrics_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('BOX', (0, 0), (-1, -1), 0.5, Colors.TEAL),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, Colors.GRAY_LIGHT),
            ('BACKGROUND', (0, 0), (-1, -1), Colors.TEAL_LIGHT),
            ('PADDING', (0, 0), (-1, -1), 6),
        ]))
        story.append(metrics_table)
        story.append(Spacer(1, 6))
        
        return story
    
    def _build_occupancy_header(self, data: Dict) -> list:
        """Build occupancy section header with legend."""
        story = []
        
        occ = data.get('occupancy', 0)
        nights = data.get('nights_rented', 0)
        owner = data.get('owner_days', 0)
        total = 365
        unrented = total - nights - owner
        
        header_data = [[
            [
                Paragraph("Occupancy", self.styles['PFSectionTitle']),
            ],
            Paragraph(f"{occ:.0%}", self.styles['PFMetricVal']),
            Paragraph(
                f"<font color='#0d7377'>■</font> Nights Rented ({nights})   "
                f"<font color='#d4a72c'>■</font> Owner Use ({owner})   "
                f"<font color='#cbd5e0'>■</font> Unrented ({unrented})",
                self.styles['PFSubtext']
            ),
        ]]
        
        header_table = Table(header_data, colWidths=[1*inch, 0.6*inch, 5.7*inch])
        header_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ALIGN', (2, 0), (2, 0), 'RIGHT'),
        ]))
        story.append(header_table)
        
        return story
    
    def _build_bottom_section(self, data: Dict, branding: Dict) -> list:
        """Build bottom section with contact and sensitivity."""
        story = []
        
        # Prepared by
        prep_content = []
        prep_content.append(Paragraph("<b>Rental Projections Prepared By</b>", self.styles['PFLabel']))
        prep_content.append(Spacer(1, 4))
        
        if branding.get('prepared_by'):
            prep_content.append(Paragraph(branding['prepared_by'], self.styles['PFPrepBy']))
        if branding.get('email'):
            prep_content.append(Paragraph(branding['email'], self.styles['PFContact']))
        if branding.get('phone'):
            prep_content.append(Paragraph(branding['phone'], self.styles['PFContact']))
        if branding.get('website'):
            prep_content.append(Paragraph(branding['website'], self.styles['PFContact']))
        prep_content.append(Spacer(1, 4))
        prep_content.append(Paragraph(datetime.now().strftime("%B %d, %Y"), self.styles['PFContact']))
        
        # Sensitivity matrix
        sens_content = []
        sens_content.append(Paragraph("<b>Sensitivity Analysis</b>", self.styles['PFLabel']))
        sens_content.append(Spacer(1, 4))
        sens_content.append(self._build_sensitivity_table(data))
        
        bottom_table = Table([[prep_content, sens_content]], colWidths=[2.1*inch, 5.2*inch])
        bottom_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))
        story.append(bottom_table)
        
        return story
    
    def _build_sensitivity_table(self, data: Dict) -> Table:
        """Build sensitivity analysis table."""
        base = data.get('gross_revenue', 161367)
        
        rows = [
            ['', '', '', 'Nights Rented', '', ''],
            ['', '', '80%', '90%', '100%', '110%', '120%'],
        ]
        
        pcts = [0.8, 0.9, 1.0, 1.1, 1.2]
        labels = ['80%', '90%', '100%', '110%', '120%']
        
        for i, (mult, lbl) in enumerate(zip(pcts, labels)):
            row = ['ADR' if i == 2 else '', lbl]
            for nmult in pcts:
                row.append(f"${base * mult * nmult:,.0f}")
            rows.append(row)
        
        col_widths = [0.3*inch, 0.4*inch, 0.7*inch, 0.7*inch, 0.7*inch, 0.7*inch, 0.7*inch]
        
        sens_table = Table(rows, colWidths=col_widths)
        sens_table.setStyle(TableStyle([
            ('SPAN', (3, 0), (6, 0)),
            ('ALIGN', (3, 0), (6, 0), 'CENTER'),
            ('FONTSIZE', (0, 0), (-1, -1), 7),
            ('BACKGROUND', (2, 1), (-1, 1), Colors.TEAL),
            ('TEXTCOLOR', (2, 1), (-1, 1), Colors.WHITE),
            ('FONTNAME', (2, 1), (-1, 1), 'Helvetica-Bold'),
            ('BACKGROUND', (1, 2), (1, -1), Colors.TEAL),
            ('TEXTCOLOR', (1, 2), (1, -1), Colors.WHITE),
            ('FONTNAME', (1, 2), (1, -1), 'Helvetica-Bold'),
            ('GRID', (1, 1), (-1, -1), 0.5, Colors.GRAY_LIGHT),
            ('BACKGROUND', (4, 4), (4, 4), Colors.TEAL_LIGHT),
            ('FONTNAME', (4, 4), (4, 4), 'Helvetica-Bold'),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('PADDING', (0, 0), (-1, -1), 2),
        ]))
        
        return sens_table
    
    def _build_page2(self, data: Dict, branding: Dict) -> list:
        """Build page 2 with details table."""
        story = []
        
        # Header matching page 1 style
        company = branding.get('company_name', '')
        address = data.get('address', '')
        
        story.append(Spacer(1, 4))
        
        header_data = [[
            Paragraph(f"<font color='#0d7377'><b>{company}</b></font>", self.styles['PFPrepBy']),
            Paragraph("Rental Projections Pro Forma Details", self.styles['PFMainTitle']),
            "",
        ]]
        header_table = Table(header_data, colWidths=[1.5*inch, 4.8*inch, 1*inch])
        header_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ALIGN', (1, 0), (1, 0), 'CENTER'),
        ]))
        story.append(header_table)
        
        # Address on separate line
        story.append(Paragraph(address, self.styles['PFAddress']))
        
        # Property box
        story.extend(self._build_property_box(data))
        
        # Detail table
        story.extend(self._build_detail_table(data))
        
        # Disclaimer
        story.append(Spacer(1, 8))
        story.append(Paragraph(
            "Projections are estimates based on market analysis and comparable properties. Actual results may vary.",
            self.styles['PFDisclaimer']
        ))
        
        return story
    
    def _build_property_box(self, data: Dict) -> list:
        """Build property details box."""
        story = []
        
        beds = data.get('bedrooms', 0)
        baths = data.get('bathrooms', 0)
        sqft = data.get('sqft', 0)
        value = data.get('property_value', 0)
        attrs = data.get('key_attributes', '')
        
        box_data = [
            [
                Paragraph(f"<b>Bedrooms</b> {beds}", self.styles['PFBody']),
                Paragraph(f"<b>Bathrooms</b> {baths}", self.styles['PFBody']),
                Paragraph(f"<b>Square Footage</b> {sqft:,}", self.styles['PFBody']),
            ],
            [
                Paragraph(f"<b>Property Value / Listed Price</b> ${value:,.0f}", self.styles['PFBody']),
                "", "",
            ],
            [
                Paragraph(f"<b>Key Attributes</b> {attrs}", self.styles['PFBody']),
                "", "",
            ],
        ]
        
        box_table = Table(box_data, colWidths=[2.4*inch, 2.4*inch, 2.4*inch])
        box_table.setStyle(TableStyle([
            ('BOX', (0, 0), (-1, -1), 1, Colors.TEAL),
            ('PADDING', (0, 0), (-1, -1), 6),
            ('BACKGROUND', (0, 0), (-1, -1), Colors.TEAL_LIGHT),
            ('SPAN', (0, 1), (2, 1)),
            ('SPAN', (0, 2), (2, 2)),
        ]))
        story.append(box_table)
        story.append(Spacer(1, 8))
        
        return story
    
    def _build_detail_table(self, data: Dict) -> list:
        """Build monthly detail table."""
        story = []
        
        headers = ['Month', 'Season', 'Days', 'Owner', 'Avail', 'Rented',
                   'Vacant', 'Rate', 'Disc', 'Min Rate', 'Occ %', 'Revenue']
        
        rows = [headers]
        
        seasons = data.get('seasons', [])
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
                f"{s.get('occupancy', 0):.0%}",
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
        rows.append([
            '', 'Totals', str(totals['days']), str(totals['owner']), str(totals['avail']),
            str(totals['rented']), str(totals['vacant']), '', '', f"${adr:,.0f}",
            f"{occ:.0%}", f"${totals['revenue']:,.0f}"
        ])
        
        col_widths = [0.5*inch, 0.8*inch, 0.33*inch, 0.35*inch, 0.35*inch,
                      0.4*inch, 0.4*inch, 0.45*inch, 0.35*inch, 0.5*inch, 0.4*inch, 0.55*inch]
        
        detail_table = Table(rows, colWidths=col_widths)
        detail_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), Colors.TEAL),
            ('TEXTCOLOR', (0, 0), (-1, 0), Colors.WHITE),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 6),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('ALIGN', (0, 1), (1, -1), 'LEFT'),
            ('GRID', (0, 0), (-1, -1), 0.5, Colors.GRAY_LIGHT),
            ('ROWBACKGROUNDS', (0, 1), (-1, -2), [Colors.WHITE, HexColor("#f8fafb")]),
            ('BACKGROUND', (0, -1), (-1, -1), Colors.TEAL),
            ('TEXTCOLOR', (0, -1), (-1, -1), Colors.WHITE),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('PADDING', (0, 0), (-1, -1), 2),
        ]))
        story.append(detail_table)
        
        return story


# =============================================================================
# PUBLIC API
# =============================================================================

def render_proforma_matplotlib(
    data: Dict[str, Any],
    output_path: str,
    branding: Optional[Dict] = None,
) -> str:
    """
    Render a professional rental pro forma PDF using matplotlib charts.
    
    Args:
        data: Pro forma data
        output_path: Where to save the PDF
        branding: Optional branding info
    
    Returns:
        Path to generated PDF
    """
    renderer = MatplotlibProFormaRenderer()
    return renderer.render(data, output_path, branding)
