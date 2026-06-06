"""
Rental Pro Forma - HTML to PDF Renderer.

Uses HTML/CSS to match the Rentalz.com visual style exactly,
then converts to PDF using WeasyPrint.

This approach gives us:
- Pixel-perfect typography
- Real CSS-based charts
- Professional layout matching the reference
"""

from weasyprint import HTML, CSS
from datetime import datetime
from typing import Dict, Any, List, Optional
import base64
import os


def generate_proforma_html(data: Dict[str, Any], branding: Optional[Dict] = None) -> str:
    """Generate the HTML for the pro forma."""
    
    branding = branding or {}
    
    # Extract data
    address = data.get('address', '')
    gross = data.get('gross_revenue', 0)
    gross_low = data.get('gross_revenue_low', gross * 0.8)
    gross_high = data.get('gross_revenue_high', gross * 1.2)
    net = data.get('net_revenue', gross * 0.8)
    net_low = data.get('net_revenue_low', net * 0.8)
    net_high = data.get('net_revenue_high', net * 1.2)
    commission = data.get('commission_pct', 20)
    
    nights = data.get('nights_rented', 0)
    owner_days = data.get('owner_days', 0)
    occupancy = data.get('occupancy', 0)
    adr = data.get('adr', 0)
    
    monthly_rev = data.get('monthly_revenue', {})
    monthly_occ = data.get('monthly_occupancy', {})
    monthly_adr = data.get('monthly_adr', {})
    
    months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    
    # Calculate max values for scaling
    max_rev = max(monthly_rev.values()) if monthly_rev else 40000
    max_adr = max(v for v in monthly_adr.values() if v > 0) if monthly_adr else 1500
    
    # Build revenue bars HTML
    rev_bars = ""
    for m in months:
        val = monthly_rev.get(m, 0)
        height_pct = (val / max_rev * 100) if max_rev > 0 else 0
        label = f"${val:,.0f}" if val > 0 else "$0"
        rev_bars += f'''
        <div class="bar-col">
            <div class="bar-label">{label}</div>
            <div class="bar-container">
                <div class="bar" style="height: {height_pct}%;"></div>
            </div>
            <div class="bar-month">{m}</div>
        </div>
        '''
    
    # Build occupancy bars HTML
    occ_bars = ""
    for m in months:
        occ_val = monthly_occ.get(m, 0)
        occ_pct = occ_val * 100
        unocc_pct = (1 - occ_val) * 100
        occ_label = f"{occ_val:.0%}" if occ_val > 0 else "0%"
        unocc_label = f"{1-occ_val:.0%}" if occ_val < 1 and occ_val > 0 else ""
        occ_bars += f'''
        <div class="occ-col">
            <div class="occ-stack">
                <div class="occ-unocc" style="height: {unocc_pct}%;">
                    <span class="occ-label-inside">{unocc_label}</span>
                </div>
                <div class="occ-filled" style="height: {occ_pct}%;">
                    <span class="occ-label-inside">{occ_label}</span>
                </div>
            </div>
            <div class="bar-month">{m}</div>
        </div>
        '''
    
    # Build ADR bars HTML
    adr_bars = ""
    for m in months:
        val = monthly_adr.get(m, 0)
        height_pct = (val / max_adr * 100) if max_adr > 0 and val > 0 else 0
        label = f"${val:,.0f}" if val > 0 else "$0"
        adr_bars += f'''
        <div class="bar-col">
            <div class="bar-label">{label}</div>
            <div class="bar-container">
                <div class="bar adr-bar" style="height: {height_pct}%;"></div>
            </div>
            <div class="bar-month">{m}</div>
        </div>
        '''
    
    # Build sensitivity matrix
    sens_rows = ""
    pcts = [0.8, 0.9, 1.0, 1.1, 1.2]
    labels = ['80%', '90%', '100%', '110%', '120%']
    for i, (mult, label) in enumerate(zip(pcts, labels)):
        cells = f'<td class="sens-row-header">{label}</td>'
        for j, nights_mult in enumerate(pcts):
            val = gross * mult * nights_mult
            cell_class = "sens-center" if i == 2 and j == 2 else ""
            cells += f'<td class="{cell_class}">${val:,.0f}</td>'
        sens_rows += f'<tr>{cells}</tr>'
    
    # Build seasons table for page 2
    seasons = data.get('seasons', [])
    seasons_rows = ""
    totals = {'days': 0, 'owner': 0, 'avail': 0, 'rented': 0, 'vacant': 0, 'revenue': 0}
    
    for i, s in enumerate(seasons):
        row_class = "alt-row" if i % 2 == 1 else ""
        seasons_rows += f'''
        <tr class="{row_class}">
            <td class="left">{s.get('month', '')}</td>
            <td class="left">{s.get('season', '')}</td>
            <td>{s.get('days', 0)}</td>
            <td>{s.get('owner_use', 0)}</td>
            <td>{s.get('available', s.get('days', 0))}</td>
            <td>{s.get('rented', 0)}</td>
            <td>{s.get('unrented', 0)}</td>
            <td>${s.get('rate', 0):,.0f}</td>
            <td>{s.get('discount', 0)}%</td>
            <td>${s.get('lowest_rate', s.get('rate', 0)):,.0f}</td>
            <td>{s.get('occupancy', 0):.0%}</td>
            <td>${s.get('revenue', 0):,.0f}</td>
        </tr>
        '''
        totals['days'] += s.get('days', 0)
        totals['owner'] += s.get('owner_use', 0)
        totals['avail'] += s.get('available', s.get('days', 0))
        totals['rented'] += s.get('rented', 0)
        totals['vacant'] += s.get('unrented', 0)
        totals['revenue'] += s.get('revenue', 0)
    
    # Branding
    company_name = branding.get('company_name', '')
    prepared_by = branding.get('prepared_by', '')
    email = branding.get('email', '')
    phone = branding.get('phone', '')
    website = branding.get('website', '')
    today = datetime.now().strftime("%B %d, %Y")
    
    # Property details
    beds = data.get('bedrooms', 0)
    baths = data.get('bathrooms', 0)
    sqft = data.get('sqft', 0)
    prop_value = data.get('property_value', 0)
    key_attrs = data.get('key_attributes', '')
    
    html = f'''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        @page {{
            size: letter;
            margin: 0.4in 0.5in;
        }}
        
        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}
        
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            font-size: 10px;
            color: #2d3748;
            line-height: 1.4;
        }}
        
        .page {{
            page-break-after: always;
            min-height: 100%;
        }}
        
        .page:last-child {{
            page-break-after: avoid;
        }}
        
        /* Header */
        .header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
        }}
        
        .logo {{
            font-size: 14px;
            font-weight: bold;
            color: #0d7377;
        }}
        
        .title-section {{
            text-align: center;
            flex-grow: 1;
        }}
        
        .main-title {{
            font-size: 18px;
            font-weight: bold;
            color: #0d7377;
            margin-bottom: 2px;
        }}
        
        .address {{
            font-size: 12px;
            color: #4a5568;
        }}
        
        /* Revenue Summary */
        .revenue-row {{
            display: flex;
            justify-content: space-between;
            margin-bottom: 12px;
        }}
        
        .revenue-box {{
            width: 48%;
        }}
        
        .revenue-label {{
            font-size: 9px;
            font-weight: bold;
            color: #4a5568;
        }}
        
        .revenue-value {{
            font-size: 24px;
            font-weight: bold;
            color: #0d7377;
        }}
        
        .revenue-range {{
            font-size: 8px;
            color: #718096;
        }}
        
        /* Key Metrics Strip */
        .metrics-strip {{
            display: flex;
            border: 1px solid #0d7377;
            background: #e6f4f4;
            margin-bottom: 12px;
        }}
        
        .metric-box {{
            flex: 1;
            text-align: center;
            padding: 8px 4px;
            border-right: 1px solid #c8e6e6;
        }}
        
        .metric-box:last-child {{
            border-right: none;
        }}
        
        .metric-value {{
            font-size: 16px;
            font-weight: bold;
            color: #0d7377;
        }}
        
        .metric-label {{
            font-size: 7px;
            color: #4a5568;
        }}
        
        /* Section Headers */
        .section-title {{
            font-size: 11px;
            font-weight: bold;
            color: #0d7377;
            margin: 10px 0 6px 0;
        }}
        
        /* Bar Charts */
        .chart-container {{
            display: flex;
            justify-content: space-between;
            height: 80px;
            margin-bottom: 8px;
        }}
        
        .bar-col {{
            flex: 1;
            display: flex;
            flex-direction: column;
            align-items: center;
            font-size: 7px;
        }}
        
        .bar-label {{
            font-size: 6px;
            color: #4a5568;
            height: 12px;
            display: flex;
            align-items: flex-end;
        }}
        
        .bar-container {{
            flex: 1;
            width: 80%;
            display: flex;
            align-items: flex-end;
        }}
        
        .bar {{
            width: 100%;
            background: linear-gradient(to top, #0d7377, #14a3a8);
            border-radius: 2px 2px 0 0;
            min-height: 2px;
        }}
        
        .adr-bar {{
            background: linear-gradient(to top, #0d7377, #14a3a8);
        }}
        
        .bar-month {{
            font-size: 7px;
            color: #4a5568;
            height: 12px;
        }}
        
        /* Occupancy Chart */
        .occ-chart {{
            display: flex;
            justify-content: space-between;
            height: 70px;
            margin-bottom: 8px;
        }}
        
        .occ-col {{
            flex: 1;
            display: flex;
            flex-direction: column;
            align-items: center;
        }}
        
        .occ-stack {{
            flex: 1;
            width: 80%;
            display: flex;
            flex-direction: column;
        }}
        
        .occ-filled {{
            background: linear-gradient(to top, #0d7377, #14a3a8);
            display: flex;
            align-items: center;
            justify-content: center;
        }}
        
        .occ-unocc {{
            background: #cbd5e0;
            display: flex;
            align-items: center;
            justify-content: center;
        }}
        
        .occ-label-inside {{
            font-size: 6px;
            color: white;
            font-weight: bold;
        }}
        
        .occ-unocc .occ-label-inside {{
            color: #4a5568;
        }}
        
        /* Occupancy Header */
        .occ-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 4px;
        }}
        
        .occ-title {{
            display: flex;
            align-items: baseline;
            gap: 8px;
        }}
        
        .occ-pct {{
            font-size: 16px;
            font-weight: bold;
            color: #0d7377;
        }}
        
        .legend {{
            font-size: 7px;
            color: #4a5568;
        }}
        
        .legend-item {{
            display: inline-flex;
            align-items: center;
            margin-left: 8px;
        }}
        
        .legend-box {{
            width: 10px;
            height: 10px;
            margin-right: 3px;
        }}
        
        .legend-teal {{ background: #0d7377; }}
        .legend-gold {{ background: #d4a72c; }}
        .legend-gray {{ background: #cbd5e0; }}
        
        /* Bottom Section */
        .bottom-section {{
            display: flex;
            justify-content: space-between;
            margin-top: 10px;
        }}
        
        .prepared-by {{
            width: 30%;
        }}
        
        .prepared-label {{
            font-size: 8px;
            font-weight: bold;
            color: #4a5568;
            margin-bottom: 4px;
        }}
        
        .prepared-name {{
            font-size: 10px;
            font-weight: bold;
            color: #2d3748;
        }}
        
        .contact-info {{
            font-size: 8px;
            color: #718096;
        }}
        
        /* Sensitivity Matrix */
        .sensitivity {{
            width: 65%;
        }}
        
        .sens-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 7px;
        }}
        
        .sens-table th {{
            background: #0d7377;
            color: white;
            padding: 3px 4px;
            font-weight: bold;
        }}
        
        .sens-table td {{
            padding: 2px 4px;
            text-align: center;
            border: 1px solid #e2e8f0;
        }}
        
        .sens-row-header {{
            background: #0d7377;
            color: white;
            font-weight: bold;
        }}
        
        .sens-center {{
            background: #e6f4f4;
            font-weight: bold;
        }}
        
        .sens-header-cell {{
            text-align: center;
        }}
        
        /* Page 2 */
        .page-title {{
            font-size: 16px;
            font-weight: bold;
            color: #0d7377;
            text-align: center;
            margin-bottom: 4px;
        }}
        
        .page-address {{
            font-size: 11px;
            color: #4a5568;
            text-align: center;
            margin-bottom: 10px;
        }}
        
        /* Property Details Box */
        .prop-box {{
            border: 1px solid #0d7377;
            padding: 8px;
            margin-bottom: 12px;
            background: #f7fafa;
        }}
        
        .prop-row {{
            display: flex;
            margin-bottom: 4px;
        }}
        
        .prop-item {{
            margin-right: 20px;
            font-size: 9px;
        }}
        
        .prop-label {{
            font-weight: bold;
        }}
        
        /* Detail Table */
        .detail-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 7px;
        }}
        
        .detail-table th {{
            background: #0d7377;
            color: white;
            padding: 4px 3px;
            font-weight: bold;
            text-align: center;
        }}
        
        .detail-table td {{
            padding: 3px;
            text-align: center;
            border: 1px solid #e2e8f0;
        }}
        
        .detail-table td.left {{
            text-align: left;
        }}
        
        .detail-table .alt-row {{
            background: #f8fafb;
        }}
        
        .detail-table .totals-row {{
            background: #0d7377;
            color: white;
            font-weight: bold;
        }}
        
        .detail-table .totals-row td {{
            border-color: #0d7377;
        }}
        
        /* Footer */
        .footer {{
            font-size: 7px;
            color: #a0aec0;
            text-align: center;
            margin-top: 10px;
        }}
    </style>
</head>
<body>
    <!-- Page 1: Summary -->
    <div class="page">
        <div class="header">
            <div class="logo">{company_name}</div>
            <div class="title-section">
                <div class="main-title">Rental Projections Pro Forma Summary</div>
                <div class="address">{address}</div>
            </div>
            <div></div>
        </div>
        
        <div class="revenue-row">
            <div class="revenue-box">
                <div class="revenue-label">Total Projected Gross Revenue:</div>
                <div class="revenue-value">${gross:,.0f}</div>
                <div class="revenue-range">(From ${gross_low:,.0f} to ${gross_high:,.0f} based on market conditions and pricing)</div>
            </div>
            <div class="revenue-box">
                <div class="revenue-label">Total Projected NET proceeds:</div>
                <div class="revenue-value">${net:,.0f}</div>
                <div class="revenue-range">(From ${net_low:,.0f} to ${net_high:,.0f} based on market conditions, pricing, and net of {commission}% commission)</div>
            </div>
        </div>
        
        <div class="metrics-strip">
            <div class="metric-box">
                <div class="metric-value">{nights}</div>
                <div class="metric-label">Total Projected Nights Rented</div>
            </div>
            <div class="metric-box">
                <div class="metric-value">{owner_days}</div>
                <div class="metric-label">Total Days Owner Enjoyment</div>
            </div>
            <div class="metric-box">
                <div class="metric-value">{occupancy:.0%}</div>
                <div class="metric-label">Occupancy</div>
            </div>
            <div class="metric-box">
                <div class="metric-value">${adr:,.0f}</div>
                <div class="metric-label">Average Nightly Rate</div>
            </div>
        </div>
        
        <div class="section-title">Total Projected Gross Revenue: ${gross:,.0f}</div>
        <div class="chart-container">
            {rev_bars}
        </div>
        
        <div class="occ-header">
            <div class="occ-title">
                <span class="section-title" style="margin: 0;">Occupancy</span>
                <span class="occ-pct">{occupancy:.0%}</span>
            </div>
            <div class="legend">
                <span class="legend-item"><span class="legend-box legend-teal"></span>Nights Rented</span>
                <span class="legend-item"><span class="legend-box legend-gold"></span>Owner Use</span>
                <span class="legend-item"><span class="legend-box legend-gray"></span>Unrented Nights</span>
            </div>
        </div>
        <div class="occ-chart">
            {occ_bars}
        </div>
        
        <div class="section-title">Average Nightly Rate: ${adr:,.0f}</div>
        <div class="chart-container">
            {adr_bars}
        </div>
        
        <div class="bottom-section">
            <div class="prepared-by">
                <div class="prepared-label">Rental Projections Prepared By</div>
                <div class="prepared-name">{prepared_by}</div>
                <div class="contact-info">{email}</div>
                <div class="contact-info">{phone}</div>
                <div class="contact-info">{website}</div>
                <div class="contact-info" style="margin-top: 6px;">{today}</div>
            </div>
            <div class="sensitivity">
                <div class="prepared-label">Sensitivity Analysis</div>
                <table class="sens-table">
                    <tr>
                        <th></th>
                        <th></th>
                        <th colspan="5" class="sens-header-cell">Nights Rented</th>
                    </tr>
                    <tr>
                        <th></th>
                        <th></th>
                        <th>80%</th>
                        <th>90%</th>
                        <th>100%</th>
                        <th>110%</th>
                        <th>120%</th>
                    </tr>
                    {sens_rows}
                </table>
            </div>
        </div>
    </div>
    
    <!-- Page 2: Details -->
    <div class="page">
        <div class="page-title">Rental Projections Pro Forma Details</div>
        <div class="page-address">{address}</div>
        
        <div class="prop-box">
            <div class="prop-row">
                <div class="prop-item"><span class="prop-label">Bedrooms</span> {beds}</div>
                <div class="prop-item"><span class="prop-label">Bathrooms</span> {baths}</div>
                <div class="prop-item"><span class="prop-label">Square Footage</span> {sqft:,}</div>
            </div>
            <div class="prop-row">
                <div class="prop-item"><span class="prop-label">Property Value / Listed Price</span> ${prop_value:,.0f}</div>
            </div>
            <div class="prop-row">
                <div class="prop-item"><span class="prop-label">Key Attributes</span> {key_attrs}</div>
            </div>
        </div>
        
        <table class="detail-table">
            <tr>
                <th>Month</th>
                <th>Season</th>
                <th>Number<br>of Days</th>
                <th>Owner<br>Use</th>
                <th>Available<br>Nights</th>
                <th>Nights<br>Rented</th>
                <th>Unrented<br>Nights</th>
                <th>Target<br>Rates</th>
                <th>Acceptable<br>Discount</th>
                <th>Lowest<br>Target Rate</th>
                <th>Occupancy<br>%</th>
                <th>Gross<br>Revenue</th>
            </tr>
            {seasons_rows}
            <tr class="totals-row">
                <td></td>
                <td class="left">Totals</td>
                <td>{totals['days']}</td>
                <td>{totals['owner']}</td>
                <td>{totals['avail']}</td>
                <td>{totals['rented']}</td>
                <td>{totals['vacant']}</td>
                <td></td>
                <td></td>
                <td>${adr:,.0f}</td>
                <td>{occupancy:.0%}</td>
                <td>${totals['revenue']:,.0f}</td>
            </tr>
        </table>
        
        <div class="footer">
            Projections are estimates based on market analysis and comparable properties. Actual results may vary.
        </div>
    </div>
</body>
</html>
'''
    
    return html


def render_proforma_html_to_pdf(
    data: Dict[str, Any],
    output_path: str,
    branding: Optional[Dict] = None,
) -> str:
    """
    Render a professional rental pro forma PDF using HTML/CSS.
    
    This approach matches the Rentalz.com visual style exactly.
    
    Args:
        data: Pro forma data
        output_path: Where to save the PDF
        branding: Optional branding info
    
    Returns:
        Path to generated PDF
    """
    html_content = generate_proforma_html(data, branding)
    
    # Convert HTML to PDF
    HTML(string=html_content).write_pdf(output_path)
    
    return output_path
