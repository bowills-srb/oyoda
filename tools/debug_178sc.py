#!/usr/bin/env python3
"""Debug 178SC pricing - try different stay lengths."""

from playwright.sync_api import sync_playwright
from datetime import date
import json
import re

url = "https://www.beachhabitats30a.com/30a-vacation-rentals/178-spartina-cir"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    
    responses = []
    def capture(r):
        if 'pricing' in r.url or 'quote' in r.url:
            try:
                body = r.text()
                responses.append(body)
                print(f"📡 Captured: {r.url[:60]}...")
            except:
                pass
    
    page.on('response', capture)
    
    print(f"Loading: {url}\n")
    page.goto(url, wait_until='networkidle', timeout=30000)
    
    # Check minimum stay requirements from the page
    html = page.content()
    
    print("Checking minimum stay requirements...")
    for m in re.finditer(r"\{'b':'([^']+)','e':'([^']+)'[^}]*'mn':(\d+)", html):
        print(f"  {m.group(1)} to {m.group(2)}: min {m.group(3)} nights")
    
    # Try different stay lengths
    test_stays = [
        ("10/01/2026", "10/04/2026", 3),
        ("10/01/2026", "10/08/2026", 7),
        ("10/04/2026", "10/11/2026", 7),
    ]
    
    for begin, end, nights in test_stays:
        print(f"\nTrying {begin} to {end} ({nights} nights)...")
        responses.clear()
        
        page.evaluate(f"""
            () => {{
                const b = document.querySelector('input.begin');
                const e = document.querySelector('input.end');
                if (b && e) {{
                    b.value = '{begin}';
                    e.value = '{end}';
                    b.dispatchEvent(new Event('change', {{bubbles: true}}));
                    e.dispatchEvent(new Event('change', {{bubbles: true}}));
                }}
            }}
        """)
        
        page.wait_for_timeout(2000)
        
        for r in responses:
            if '$' in r:
                # Parse amounts
                data = json.loads(r)
                content = data.get('content', '').replace('\\u003C', '<').replace('\\u003E', '>')
                amounts = re.findall(r'\$([\d,]+(?:\.\d{2})?)', content)
                if amounts:
                    parsed = [float(a.replace(',', '')) for a in amounts]
                    print(f"  💰 Found amounts: {amounts}")
                    print(f"  💰 Total: ${max(parsed):,.0f}")
                break
        else:
            # Check if we got "not available" response
            for r in responses:
                if 'Not Available' in r or 'not available' in r.lower():
                    print(f"  ❌ Not Available")
                    break
            else:
                print(f"  ⚠️ No response")
    
    browser.close()
