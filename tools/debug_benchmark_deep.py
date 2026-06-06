#!/usr/bin/env python3
"""Deep debug to find where Benchmark stores availability/pricing data"""

import asyncio
import re
import json
from playwright.async_api import async_playwright

async def debug_benchmark_deep():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        
        # Capture network requests
        api_calls = []
        
        async def capture_request(request):
            url = request.url
            if any(x in url.lower() for x in ['avail', 'calendar', 'rate', 'price', 'book', 'quote', 'api', 'item']):
                api_calls.append({
                    'method': request.method,
                    'url': url,
                })
        
        page.on('request', capture_request)
        
        url = "https://www.benchmark30a.com/emerald-coast-vacation-rentals/best-both-worlds"
        print(f"Fetching: {url}\n")
        
        await page.goto(url, wait_until='networkidle', timeout=60000)
        await asyncio.sleep(5)
        
        html = await page.content()
        
        print("=" * 70)
        print("1. NETWORK API CALLS CAPTURED")
        print("=" * 70)
        for call in api_calls[:20]:
            print(f"  [{call['method']}] {call['url'][:100]}")
        
        print("\n" + "=" * 70)
        print("2. SEARCHING FOR DATA PATTERNS IN HTML")
        print("=" * 70)
        
        # Look for various patterns
        patterns = [
            (r"'avail'\s*:\s*\[([^\]]{0,500})", "'avail' array"),
            (r'"avail"\s*:\s*\[([^\]]{0,500})', '"avail" array'),
            (r"availability['\"]?\s*[=:]\s*['\"]?([^'\";\n]{0,200})", "availability assignment"),
            (r"unavailable['\"]?\s*[=:]\s*\[([^\]]{0,500})", "unavailable array"),
            (r"blocked['\"]?\s*[=:]\s*\[([^\]]{0,500})", "blocked array"),
            (r"calendar['\"]?\s*[=:]\s*\{([^\}]{0,500})", "calendar object"),
            (r"Rezfusion\.([a-zA-Z]+)", "Rezfusion namespace"),
            (r"window\.([a-zA-Z_]+)\s*=\s*\{", "window objects"),
            (r"data-item-id=['\"]([^'\"]+)", "data-item-id"),
            (r"data-property-id=['\"]([^'\"]+)", "data-property-id"),
            (r"propertyId['\"]?\s*[=:]\s*['\"]?(\d+)", "propertyId"),
            (r"/api/[^'\">\s]+", "API endpoints"),
        ]
        
        for pattern, name in patterns:
            matches = re.findall(pattern, html, re.IGNORECASE)
            if matches:
                print(f"\n  ✅ {name}:")
                for m in matches[:3]:
                    preview = m[:100] if isinstance(m, str) else str(m)[:100]
                    print(f"     {preview}...")
        
        print("\n" + "=" * 70)
        print("3. CHECKING WINDOW/JS OBJECTS")
        print("=" * 70)
        
        try:
            js_data = await page.evaluate("""
                () => {
                    const found = {};
                    
                    // Check for Drupal.settings
                    if (typeof Drupal !== 'undefined' && Drupal.settings) {
                        found['Drupal.settings keys'] = Object.keys(Drupal.settings);
                        if (Drupal.settings.rcItemAvailForm) {
                            found['rcItemAvailForm'] = JSON.stringify(Drupal.settings.rcItemAvailForm).substring(0, 500);
                        }
                    }
                    
                    // Check for Rezfusion
                    if (typeof Rezfusion !== 'undefined') {
                        found['Rezfusion'] = Object.keys(Rezfusion);
                    }
                    
                    // Check common window objects
                    const checkKeys = ['availability', 'calendar', 'propertyData', 'itemData', 'bookingData', 'rates'];
                    for (let key of checkKeys) {
                        if (window[key]) {
                            found[key] = JSON.stringify(window[key]).substring(0, 300);
                        }
                    }
                    
                    // Find any window keys with 'avail', 'calendar', 'rate', 'book'
                    for (let key of Object.keys(window)) {
                        if (/avail|calendar|rate|book|property/i.test(key)) {
                            try {
                                const val = window[key];
                                if (val && typeof val === 'object') {
                                    found['window.' + key] = Object.keys(val).slice(0, 10);
                                }
                            } catch(e) {}
                        }
                    }
                    
                    return found;
                }
            """)
            
            for key, val in js_data.items():
                print(f"\n  {key}:")
                print(f"     {str(val)[:200]}")
                
        except Exception as e:
            print(f"  Error: {e}")
        
        print("\n" + "=" * 70)
        print("4. LOOKING FOR IFRAME BOOKING WIDGETS")
        print("=" * 70)
        
        iframes = await page.query_selector_all('iframe')
        print(f"  Found {len(iframes)} iframes")
        for i, iframe in enumerate(iframes[:5]):
            src = await iframe.get_attribute('src')
            if src:
                print(f"  [{i}] {src[:100]}")
        
        print("\n" + "=" * 70)
        print("5. SEARCHING FOR ESCAPIA/REZFUSION API PATTERNS")
        print("=" * 70)
        
        # Look for Rezfusion API patterns
        rezfusion_patterns = [
            r"bch\.pro\.rezfusion\.com[^'\">\s]*",
            r"api\.rezfusion\.com[^'\">\s]*",
            r"escapia[^'\">\s]*api[^'\">\s]*",
        ]
        
        for pattern in rezfusion_patterns:
            matches = re.findall(pattern, html, re.IGNORECASE)
            if matches:
                print(f"\n  Pattern: {pattern}")
                for m in set(matches):
                    print(f"     {m[:100]}")
        
        await browser.close()
        
        print("\n" + "=" * 70)
        print("CONCLUSION")
        print("=" * 70)

asyncio.run(debug_benchmark_deep())
