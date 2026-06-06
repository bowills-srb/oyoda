#!/usr/bin/env python3
"""Quick check of a specific property's availability."""

from playwright.sync_api import sync_playwright
import re

def check_property(slug):
    url = f"https://www.beachhabitats30a.com/30a-vacation-rentals/{slug}"
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        print(f"Checking: {url}")
        page.goto(url, wait_until='networkidle', timeout=30000)
        
        html = page.content()
        
        # Check for availability ranges
        avail_ranges = []
        for m in re.finditer(r"\{'b':'([^']+)','e':'([^']+)','a':'(\d)'", html):
            avail_ranges.append({
                'start': m.group(1),
                'end': m.group(2),
                'available': m.group(3) == '1'
            })
        
        print(f"\nAvailability ranges: {len(avail_ranges)}")
        for r in avail_ranges[:10]:
            status = "✓ Available" if r['available'] else "✗ Booked"
            print(f"  {r['start']} to {r['end']}: {status}")
        
        # Check quotable
        quotable = []
        for m in re.finditer(r"\{'b':'([^']+)','e':'([^']+)','a':'1','q':'1'", html):
            quotable.append((m.group(1), m.group(2)))
        
        print(f"\nQuotable ranges (a=1, q=1): {len(quotable)}")
        for start, end in quotable[:5]:
            print(f"  {start} to {end}")
        
        browser.close()

if __name__ == "__main__":
    check_property("178-spartina-cir")
