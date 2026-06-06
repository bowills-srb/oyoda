#!/usr/bin/env python3
"""Get pricing for 178SC using the far-future available dates."""

from playwright.sync_api import sync_playwright
from datetime import date, timedelta
from decimal import Decimal
import json
import re

def main():
    url = "https://www.beachhabitats30a.com/30a-vacation-rentals/178-spartina-cir"
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        
        pricing_responses = []
        
        def capture(response):
            if 'pricing' in response.url and 'quote' in response.url:
                try:
                    body = response.text()
                    if '$' in body:
                        pricing_responses.append(body)
                except:
                    pass
        
        page.on('response', capture)
        
        print(f"Loading: {url}")
        page.goto(url, wait_until='networkidle', timeout=30000)
        
        # Available from Oct 1, 2026 - try that date range
        check_in = date(2026, 10, 1)
        check_out = date(2026, 10, 4)
        
        begin_str = check_in.strftime('%m/%d/%Y')
        end_str = check_out.strftime('%m/%d/%Y')
        
        print(f"Getting quote for {check_in} to {check_out}...")
        
        page.evaluate(f"""
            () => {{
                const b = document.querySelector('input.begin');
                const e = document.querySelector('input.end');
                if (b && e) {{
                    b.value = '{begin_str}';
                    e.value = '{end_str}';
                    b.dispatchEvent(new Event('change', {{bubbles: true}}));
                    e.dispatchEvent(new Event('change', {{bubbles: true}}));
                }}
            }}
        """)
        
        page.wait_for_timeout(2500)
        
        if pricing_responses:
            for resp in pricing_responses:
                data = json.loads(resp)
                content = data.get('content', '')
                content = content.replace('\\u003C', '<').replace('\\u003E', '>')
                
                amounts = re.findall(r'\$([\d,]+(?:\.\d{2})?)', content)
                if amounts:
                    parsed = [float(a.replace(',', '')) for a in amounts]
                    total = max(parsed)
                    
                    # Find lodging
                    lodging = 0
                    m = re.search(r'Lodging[^$]*\$([\d,]+)', content)
                    if m:
                        lodging = float(m.group(1).replace(',', ''))
                    
                    nights = (check_out - check_in).days
                    adr = lodging / nights if lodging else total / nights * 0.85
                    
                    print(f"\n💰 178SC Pricing (Oct 2026):")
                    print(f"   Total: ${total:,.0f}")
                    print(f"   Lodging: ${lodging:,.0f}")
                    print(f"   ADR: ${adr:,.0f}/night")
                    
                    # Save to database
                    import psycopg2
                    conn = psycopg2.connect("postgresql://rental:rental@localhost:5433/rental_revenue")
                    cur = conn.cursor()
                    cur.execute("""
                        INSERT INTO property_pricing 
                        (property_code, check_in, check_out, nights, lodging, total, adr)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (property_code, check_in, check_out) DO UPDATE SET
                            lodging = EXCLUDED.lodging, total = EXCLUDED.total, 
                            adr = EXCLUDED.adr, scraped_at = NOW()
                    """, ('178SC', check_in, check_out, nights, lodging, total, adr))
                    conn.commit()
                    cur.close()
                    conn.close()
                    print("   ✓ Saved to database")
        else:
            print("No pricing returned")
        
        browser.close()

if __name__ == "__main__":
    main()
