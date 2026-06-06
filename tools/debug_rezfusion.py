#!/usr/bin/env python3
"""
Debug Rezfusion calendar pattern - used by Beach Habitats AND Benchmark.
Find where availability/pricing data comes from.
"""

import asyncio
import json
import re
from playwright.async_api import async_playwright

async def debug_rezfusion():
    print("=" * 70)
    print("🔍 REZFUSION CALENDAR DEBUG")
    print("=" * 70)
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        
        # Capture ALL network requests
        api_calls = []
        
        async def capture_request(request):
            url = request.url.lower()
            if any(x in url for x in ['avail', 'calendar', 'rate', 'price', 'book', 'quote', 'api']):
                api_calls.append({
                    'method': request.method,
                    'url': request.url,
                })
        
        async def capture_response(response):
            url = response.url.lower()
            if any(x in url for x in ['avail', 'calendar', 'rate', 'price', 'book', 'quote']):
                try:
                    body = await response.text()
                    if len(body) > 50:
                        api_calls.append({
                            'type': 'response',
                            'url': response.url,
                            'status': response.status,
                            'body_preview': body[:500],
                        })
                except:
                    pass
        
        page.on('request', capture_request)
        page.on('response', capture_response)
        
        # Test Beach Habitats
        print("\n" + "=" * 70)
        print("🏠 Beach Habitats (Rezfusion)")
        print("=" * 70)
        
        url = "https://www.beachhabitats30a.com/30a-vacation-rentals/359-spartina-circle"
        await page.goto(url, wait_until='networkidle', timeout=60000)
        await asyncio.sleep(3)
        
        html = await page.content()
        
        # Look for Rezfusion-specific patterns
        rezfusion_patterns = [
            (r'Rezfusion\.config\s*=\s*(\{[^;]+\})', 'Rezfusion.config'),
            (r'"availability"\s*:\s*(\[[^\]]+\])', 'availability array'),
            (r'"unavailable"\s*:\s*(\[[^\]]+\])', 'unavailable array'),
            (r'"rates"\s*:\s*(\{[^}]+\})', 'rates object'),
            (r'"calendar"\s*:\s*(\{[^}]+\})', 'calendar object'),
            (r'data-item-id="([^"]+)"', 'item ID'),
            (r'data-property-id="([^"]+)"', 'property ID'),
            (r'"propertyId"\s*:\s*"?(\d+)"?', 'propertyId'),
            (r'"unitId"\s*:\s*"?(\d+)"?', 'unitId'),
        ]
        
        print("\n📍 Pattern search in HTML:")
        for pattern, name in rezfusion_patterns:
            match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
            if match:
                value = match.group(1)[:100] if match.lastindex else match.group(0)[:100]
                print(f"   ✅ {name}: {value}...")
        
        # Check window objects
        print("\n📍 Window objects:")
        try:
            window_data = await page.evaluate("""
                () => {
                    const found = {};
                    const keywords = ['rezfusion', 'calendar', 'avail', 'rate', 'price', 'book', 'property', 'unit'];
                    
                    for (let key of Object.keys(window)) {
                        for (let kw of keywords) {
                            if (key.toLowerCase().includes(kw)) {
                                try {
                                    const val = window[key];
                                    if (val && typeof val === 'object') {
                                        found[key] = JSON.stringify(val).substring(0, 300);
                                    } else if (val) {
                                        found[key] = String(val).substring(0, 100);
                                    }
                                } catch (e) {}
                            }
                        }
                    }
                    
                    // Also check for Rezfusion namespace
                    if (typeof Rezfusion !== 'undefined') {
                        found['Rezfusion'] = JSON.stringify(Rezfusion).substring(0, 500);
                    }
                    
                    return found;
                }
            """)
            
            for key, val in window_data.items():
                print(f"   🔧 window.{key}: {val[:80]}...")
        except Exception as e:
            print(f"   ⚠️ Error: {e}")
        
        # Look for API endpoints in HTML
        print("\n📍 API endpoints found in HTML:")
        api_patterns = [
            r'https?://[^"\s]+/api/[^"\s]+',
            r'https?://[^"\s]+avail[^"\s]*',
            r'https?://[^"\s]+calendar[^"\s]*',
            r'https?://[^"\s]+quote[^"\s]*',
        ]
        
        found_apis = set()
        for pattern in api_patterns:
            for match in re.finditer(pattern, html, re.IGNORECASE):
                found_apis.add(match.group(0)[:100])
        
        for api in list(found_apis)[:10]:
            print(f"   🌐 {api}")
        
        # Show captured network requests
        print(f"\n📍 Captured API calls ({len(api_calls)}):")
        for call in api_calls[:15]:
            if 'body_preview' in call:
                print(f"   📥 [{call['status']}] {call['url'][:60]}...")
                print(f"       Body: {call['body_preview'][:100]}...")
            else:
                print(f"   📤 [{call.get('method', '?')}] {call['url'][:80]}...")
        
        # Try clicking on calendar/date picker
        print("\n📍 Trying to interact with date picker...")
        try:
            # Look for date inputs
            date_inputs = await page.query_selector_all('input[type="date"], input.date, input[name*="date"], input[placeholder*="date"]')
            print(f"   Found {len(date_inputs)} date inputs")
            
            # Look for calendar buttons
            cal_buttons = await page.query_selector_all('button[class*="calendar"], button[class*="date"], .calendar-trigger')
            print(f"   Found {len(cal_buttons)} calendar buttons")
            
            # Try to find and click availability check button
            check_btns = await page.query_selector_all('button:has-text("Check"), button:has-text("Search"), button:has-text("Availability")')
            print(f"   Found {len(check_btns)} availability check buttons")
            
        except Exception as e:
            print(f"   ⚠️ Error: {e}")
        
        await browser.close()
        
    print("\n" + "=" * 70)
    print("📊 CONCLUSION")
    print("=" * 70)
    print("""
Rezfusion sites load calendar data differently:
1. May use lazy-loading via API calls when dates are selected
2. May use server-side rendering with no client-side JS data
3. API endpoints might require authentication or session tokens

Next steps to investigate:
1. Check if there's a public Rezfusion/Escapia API
2. Look for iCal feed URLs (often available for calendar sync)
3. Consider AirDNA/Transparent for pricing data
""")


if __name__ == "__main__":
    asyncio.run(debug_rezfusion())
