#!/usr/bin/env python3
"""
Debug script to analyze Oversee property page structure.
Captures all JavaScript, network requests, and embedded data.
"""

import asyncio
import json
import re
from playwright.async_api import async_playwright


async def analyze_oversee_page():
    print("=" * 70)
    print("OVERSEE PAGE ANALYSIS")
    print("=" * 70)
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        
        # Capture ALL network requests
        requests_log = []
        responses_log = []
        
        async def log_request(request):
            requests_log.append({
                'url': request.url,
                'method': request.method,
                'resource_type': request.resource_type,
            })
        
        async def log_response(response):
            url = response.url
            # Only log interesting responses
            if any(x in url.lower() for x in ['api', 'price', 'rate', 'avail', 'calendar', 'book', 'quote', 'track']):
                try:
                    body = await response.text()
                    responses_log.append({
                        'url': url,
                        'status': response.status,
                        'body_preview': body[:500] if body else None,
                    })
                except:
                    pass
        
        page.on('request', log_request)
        page.on('response', log_response)
        
        # Load a property page
        url = "https://oversee.us/vrp/unit/Happy_Oasis-373-15"
        print(f"\n📍 Loading: {url}")
        
        await page.goto(url, wait_until='networkidle', timeout=30000)
        await asyncio.sleep(3)
        
        html = await page.content()
        
        # 1. Find all script tags
        print("\n" + "=" * 70)
        print("📜 SCRIPT TAGS")
        print("=" * 70)
        scripts = re.findall(r'<script[^>]*src=["\']([^"\']+)["\']', html)
        for s in scripts[:20]:
            print(f"  {s}")
        
        # 2. Look for inline JavaScript with data
        print("\n" + "=" * 70)
        print("📊 EMBEDDED DATA PATTERNS")
        print("=" * 70)
        
        patterns = [
            (r'var\s+(\w+)\s*=\s*(\{[^;]{50,500})', 'JS Variables'),
            (r'window\.(\w+)\s*=\s*(\{[^;]{50,500})', 'Window Objects'),
            (r'"(?:price|rate|adr|nightly|total)":\s*["\']?(\d+)', 'Price Values'),
            (r'"(?:available|unavailable|blocked)":\s*\[([^\]]+)\]', 'Availability Arrays'),
            (r'trackhs\.com[^"\'>\s]+', 'Track PMS URLs'),
            (r'api[^"\'>\s]{10,100}', 'API Endpoints'),
            (r'calendar[^"\'>\s]{10,100}', 'Calendar URLs'),
        ]
        
        for pattern, name in patterns:
            matches = re.findall(pattern, html, re.IGNORECASE)
            if matches:
                print(f"\n  {name}:")
                for m in matches[:5]:
                    if isinstance(m, tuple):
                        print(f"    {m[0]}: {str(m[1])[:100]}...")
                    else:
                        print(f"    {str(m)[:100]}")
        
        # 3. Look for data attributes
        print("\n" + "=" * 70)
        print("🏷️ DATA ATTRIBUTES")
        print("=" * 70)
        data_attrs = re.findall(r'data-([a-z-]+)=["\']([^"\']+)["\']', html, re.IGNORECASE)
        unique_attrs = {}
        for name, val in data_attrs:
            if name not in unique_attrs:
                unique_attrs[name] = val
        for name, val in list(unique_attrs.items())[:20]:
            print(f"  data-{name}: {val[:80]}")
        
        # 4. Network requests
        print("\n" + "=" * 70)
        print("🌐 NETWORK REQUESTS (interesting)")
        print("=" * 70)
        for req in requests_log:
            url = req['url']
            if any(x in url.lower() for x in ['api', 'price', 'rate', 'avail', 'calendar', 'book', 'track']):
                print(f"  [{req['method']}] {url[:100]}")
        
        # 5. Captured responses
        print("\n" + "=" * 70)
        print("📥 CAPTURED RESPONSES")
        print("=" * 70)
        for resp in responses_log:
            print(f"\n  URL: {resp['url'][:100]}")
            print(f"  Status: {resp['status']}")
            if resp['body_preview']:
                print(f"  Body: {resp['body_preview'][:200]}...")
        
        # 6. Look for pricing/booking widget
        print("\n" + "=" * 70)
        print("🎯 BOOKING WIDGET SEARCH")
        print("=" * 70)
        
        # Common booking widget selectors
        selectors = [
            'input[type="date"]',
            'input[name*="check"]',
            'input[name*="date"]',
            '.datepicker',
            '.calendar',
            '[class*="booking"]',
            '[class*="price"]',
            '[class*="rate"]',
            'button[class*="book"]',
            '[data-price]',
            '[data-rate]',
        ]
        
        for sel in selectors:
            try:
                elements = await page.query_selector_all(sel)
                if elements:
                    print(f"\n  Found {len(elements)} elements for: {sel}")
                    for el in elements[:3]:
                        tag = await el.evaluate('el => el.tagName')
                        classes = await el.get_attribute('class') or ''
                        text = (await el.inner_text())[:50] if await el.inner_text() else ''
                        print(f"    <{tag}> class='{classes[:50]}' text='{text}'")
            except:
                pass
        
        # 7. Look for React/Vue data
        print("\n" + "=" * 70)
        print("⚛️ FRAMEWORK DATA")
        print("=" * 70)
        
        react_data = await page.evaluate("""
            () => {
                const results = {};
                // Check for React
                if (window.__REACT_DEVTOOLS_GLOBAL_HOOK__) {
                    results.react = true;
                }
                // Check for Vue
                if (window.__VUE__) {
                    results.vue = true;
                }
                // Check for common data stores
                if (window.__INITIAL_STATE__) {
                    results.initialState = JSON.stringify(window.__INITIAL_STATE__).substring(0, 500);
                }
                if (window.__PRELOADED_STATE__) {
                    results.preloadedState = JSON.stringify(window.__PRELOADED_STATE__).substring(0, 500);
                }
                // Look for any window properties with 'price', 'rate', 'booking'
                for (let key of Object.keys(window)) {
                    if (key.toLowerCase().includes('price') || 
                        key.toLowerCase().includes('rate') ||
                        key.toLowerCase().includes('booking') ||
                        key.toLowerCase().includes('calendar') ||
                        key.toLowerCase().includes('avail')) {
                        try {
                            results[key] = JSON.stringify(window[key]).substring(0, 200);
                        } catch (e) {}
                    }
                }
                return results;
            }
        """)
        
        for key, val in react_data.items():
            print(f"  {key}: {str(val)[:100]}")
        
        # 8. Find the actual price display on the page
        print("\n" + "=" * 70)
        print("💲 PRICE TEXT ON PAGE")
        print("=" * 70)
        
        text = await page.inner_text('body')
        price_matches = re.findall(r'\$[\d,]+(?:\.\d{2})?\s*(?:/\s*night|per\s*night|nightly)?', text, re.IGNORECASE)
        for match in price_matches[:10]:
            print(f"  {match}")
        
        # 9. Try clicking on calendar/date picker
        print("\n" + "=" * 70)
        print("🗓️ TRYING DATE INTERACTION")
        print("=" * 70)
        
        try:
            # Look for check-in field
            checkin = await page.query_selector('input[name*="checkin"], input[name*="check_in"], input[placeholder*="Check"], .checkin-date')
            if checkin:
                await checkin.click()
                await asyncio.sleep(2)
                
                # Check for new network requests
                new_requests = [r for r in requests_log if 'price' in r['url'].lower() or 'rate' in r['url'].lower()]
                print(f"  After click, found {len(new_requests)} price-related requests")
        except Exception as e:
            print(f"  Date interaction failed: {e}")
        
        await browser.close()
        
        # Save full HTML for manual inspection
        with open('/tmp/oversee_page.html', 'w') as f:
            f.write(html)
        print(f"\n📄 Full HTML saved to /tmp/oversee_page.html")


if __name__ == "__main__":
    asyncio.run(analyze_oversee_page())
