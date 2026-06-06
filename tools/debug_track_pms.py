#!/usr/bin/env python3
"""
Debug script to analyze Oversee/Track PMS page structure for availability data.
Looks for embedded calendar data, API endpoints, and booking widget patterns.
"""

import asyncio
import json
import re
from playwright.async_api import async_playwright


async def analyze_track_pms():
    print("=" * 70)
    print("TRACK PMS AVAILABILITY ANALYSIS")
    print("=" * 70)
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        )
        page = await context.new_page()
        
        # Capture network requests
        api_requests = []
        
        async def capture_request(request):
            url = request.url
            if any(x in url.lower() for x in ['api', 'avail', 'calendar', 'book', 'rate', 'price', 'track']):
                api_requests.append({
                    'url': url,
                    'method': request.method,
                })
        
        page.on('request', capture_request)
        
        # Load property page
        url = "https://oversee.us/vrp/unit/Happy_Oasis-373-15"
        print(f"\n📍 Loading: {url}")
        
        try:
            await page.goto(url, wait_until='networkidle', timeout=60000)
        except:
            print("   Timeout - continuing with partial load...")
        
        await asyncio.sleep(3)
        html = await page.content()
        
        # 1. Look for Track PMS specific patterns
        print("\n" + "=" * 70)
        print("🔍 TRACK PMS PATTERNS")
        print("=" * 70)
        
        track_patterns = [
            (r'trackhs\.com[^"\'>\s]*', 'Track URLs'),
            (r'track[A-Z]\w+', 'Track Variables'),
            (r'"unitId"\s*:\s*"?(\d+)"?', 'Unit IDs'),
            (r'"propertyId"\s*:\s*"?(\d+)"?', 'Property IDs'),
            (r'data-unit[^=]*=["\']([^"\']+)["\']', 'Data-unit attributes'),
        ]
        
        for pattern, name in track_patterns:
            matches = re.findall(pattern, html)
            if matches:
                print(f"\n  {name}:")
                for m in list(set(matches))[:5]:
                    print(f"    {m}")
        
        # 2. Look for calendar/availability data structures
        print("\n" + "=" * 70)
        print("📅 CALENDAR DATA STRUCTURES")
        print("=" * 70)
        
        calendar_patterns = [
            (r'"(?:unavailable|blocked|booked)"\s*:\s*\[([^\]]+)\]', 'Blocked dates array'),
            (r'"(?:available)"\s*:\s*\[([^\]]+)\]', 'Available dates array'),
            (r'"dates"\s*:\s*\[([^\]]+)\]', 'Dates array'),
            (r'"calendar"\s*:\s*(\{[^}]+\})', 'Calendar object'),
            (r'availabilityData\s*=\s*(\{[^;]+)', 'Availability data'),
            (r'calendarData\s*=\s*(\{[^;]+)', 'Calendar data'),
            (r'"minStay"\s*:\s*(\d+)', 'Min stay'),
            (r'"checkIn"\s*:\s*"([^"]+)"', 'Check-in dates'),
        ]
        
        for pattern, name in calendar_patterns:
            matches = re.findall(pattern, html, re.IGNORECASE | re.DOTALL)
            if matches:
                print(f"\n  {name}:")
                for m in matches[:3]:
                    print(f"    {str(m)[:150]}...")
        
        # 3. Look for embedded JSON data
        print("\n" + "=" * 70)
        print("📦 EMBEDDED JSON")
        print("=" * 70)
        
        # Find script tags with JSON
        json_scripts = re.findall(r'<script[^>]*type=["\']application/(?:ld\+)?json["\'][^>]*>(.*?)</script>', html, re.DOTALL)
        for i, script in enumerate(json_scripts[:3]):
            try:
                data = json.loads(script)
                print(f"\n  JSON Block {i+1}:")
                print(f"    Keys: {list(data.keys()) if isinstance(data, dict) else type(data)}")
            except:
                print(f"\n  JSON Block {i+1}: (parse error)")
                print(f"    Preview: {script[:100]}...")
        
        # 4. Look for inline scripts with data
        print("\n" + "=" * 70)
        print("📜 INLINE SCRIPT DATA")
        print("=" * 70)
        
        # Find var declarations with objects
        var_patterns = [
            r'var\s+(calendar\w*)\s*=\s*(\{[^;]{20,500})',
            r'var\s+(avail\w*)\s*=\s*(\{[^;]{20,500})',
            r'var\s+(unit\w*)\s*=\s*(\{[^;]{20,500})',
            r'var\s+(property\w*)\s*=\s*(\{[^;]{20,500})',
            r'window\.(\w+)\s*=\s*(\{[^;]{20,500})',
        ]
        
        for pattern in var_patterns:
            matches = re.findall(pattern, html, re.IGNORECASE)
            for name, value in matches[:3]:
                print(f"\n  {name}:")
                print(f"    {value[:200]}...")
        
        # 5. Network requests
        print("\n" + "=" * 70)
        print("🌐 API REQUESTS CAPTURED")
        print("=" * 70)
        
        for req in api_requests[:20]:
            print(f"  [{req['method']}] {req['url'][:100]}")
        
        # 6. Look for datepicker elements
        print("\n" + "=" * 70)
        print("🗓️ DATEPICKER ELEMENTS")
        print("=" * 70)
        
        selectors = [
            '.datepicker',
            '[class*="calendar"]',
            '[class*="date"]',
            'input[type="date"]',
            '[data-toggle="datepicker"]',
            '.flatpickr',
            '.pikaday',
        ]
        
        for sel in selectors:
            try:
                elements = await page.query_selector_all(sel)
                if elements:
                    print(f"\n  {sel}: {len(elements)} found")
                    for el in elements[:2]:
                        classes = await el.get_attribute('class') or ''
                        el_id = await el.get_attribute('id') or ''
                        print(f"    class='{classes[:50]}' id='{el_id}'")
            except:
                pass
        
        # 7. Look for availability calendar widget
        print("\n" + "=" * 70)
        print("📊 AVAILABILITY WIDGET")
        print("=" * 70)
        
        # Find calendar container
        calendar_containers = await page.query_selector_all('[class*="calendar"], [class*="avail"], [id*="calendar"]')
        print(f"  Found {len(calendar_containers)} calendar containers")
        
        for container in calendar_containers[:3]:
            inner_html = await container.inner_html()
            # Look for date cells
            booked_cells = len(re.findall(r'class="[^"]*(?:booked|unavailable|blocked)[^"]*"', inner_html))
            available_cells = len(re.findall(r'class="[^"]*(?:available|open)[^"]*"', inner_html))
            print(f"    Booked cells: {booked_cells}, Available cells: {available_cells}")
        
        # 8. Try to find the actual availability API
        print("\n" + "=" * 70)
        print("🔌 POTENTIAL API ENDPOINTS")
        print("=" * 70)
        
        api_patterns = [
            r'https?://[^"\'>\s]*(?:api|availability|calendar|rates)[^"\'>\s]*',
        ]
        
        for pattern in api_patterns:
            matches = re.findall(pattern, html)
            unique_matches = list(set(matches))[:10]
            for m in unique_matches:
                print(f"  {m}")
        
        # 9. Execute JS to find window objects
        print("\n" + "=" * 70)
        print("⚙️ WINDOW OBJECTS")
        print("=" * 70)
        
        try:
            window_data = await page.evaluate("""
                () => {
                    const results = {};
                    const keywords = ['calendar', 'avail', 'book', 'rate', 'unit', 'property', 'track'];
                    
                    for (let key of Object.keys(window)) {
                        for (let kw of keywords) {
                            if (key.toLowerCase().includes(kw)) {
                                try {
                                    const val = window[key];
                                    if (val && typeof val === 'object') {
                                        results[key] = JSON.stringify(val).substring(0, 300);
                                    } else if (val) {
                                        results[key] = String(val).substring(0, 100);
                                    }
                                } catch (e) {}
                            }
                        }
                    }
                    return results;
                }
            """)
            
            for key, val in window_data.items():
                print(f"\n  window.{key}:")
                print(f"    {val[:200]}...")
        except Exception as e:
            print(f"  Error: {e}")
        
        # Save HTML for manual inspection
        with open('/tmp/oversee_track_debug.html', 'w') as f:
            f.write(html)
        print(f"\n\n📄 Full HTML saved to /tmp/oversee_track_debug.html")
        
        await browser.close()


if __name__ == "__main__":
    asyncio.run(analyze_track_pms())
