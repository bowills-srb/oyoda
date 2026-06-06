#!/usr/bin/env python3
"""
Investigate Track PMS API for availability data.
Track PMS uses: oversee.trackhs.com
"""

import asyncio
import json
import re
from playwright.async_api import async_playwright


async def investigate_track_api():
    print("=" * 70)
    print("TRACK PMS API INVESTIGATION")
    print("=" * 70)
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)  # Non-headless to see what's happening
        context = await browser.new_context()
        page = await context.new_page()
        
        # Capture ALL network traffic
        all_requests = []
        
        async def capture_all(request):
            all_requests.append({
                'url': request.url,
                'method': request.method,
            })
        
        page.on('request', capture_all)
        
        # Try accessing Track PMS directly
        print("\n📍 Testing Track PMS endpoints...")
        
        # Test 1: Direct booking widget URL pattern
        # Often: https://{company}.trackhs.com/booking/unit/{unit_id}
        test_urls = [
            "https://oversee.trackhs.com/",
            "https://oversee.trackhs.com/guest/",
            "https://oversee.trackhs.com/api/",
            "https://oversee.trackhs.com/booking/",
        ]
        
        for url in test_urls:
            print(f"\n  Testing: {url}")
            try:
                response = await page.goto(url, wait_until='domcontentloaded', timeout=10000)
                print(f"    Status: {response.status if response else 'No response'}")
                
                if response and response.status == 200:
                    content = await page.content()
                    print(f"    Content length: {len(content)}")
                    
                    # Look for API patterns
                    if 'api' in content.lower() or 'availability' in content.lower():
                        print(f"    Found API references!")
            except Exception as e:
                print(f"    Error: {str(e)[:50]}")
        
        # Test 2: Load Oversee property page and wait for iframe
        print("\n\n📍 Loading property page and watching for iframe...")
        
        all_requests.clear()
        
        try:
            await page.goto("https://oversee.us/vrp/unit/Happy_Oasis-373-15", timeout=30000)
            await asyncio.sleep(5)  # Wait for dynamic content
            
            # Look for iframes
            iframes = await page.query_selector_all('iframe')
            print(f"\n  Found {len(iframes)} iframes")
            
            for i, iframe in enumerate(iframes):
                src = await iframe.get_attribute('src')
                name = await iframe.get_attribute('name') or ''
                iframe_id = await iframe.get_attribute('id') or ''
                print(f"\n  Iframe {i+1}:")
                print(f"    id: {iframe_id}")
                print(f"    name: {name}")
                print(f"    src: {src}")
                
                # If this is the Track iframe, try to access its content
                if 'track' in (src or '').lower() or 'track' in iframe_id.lower():
                    print(f"    *** TRACK IFRAME FOUND ***")
                    
                    # Try to get iframe content
                    try:
                        frame = iframe.content_frame()
                        if frame:
                            frame_content = await frame.content()
                            print(f"    Frame content length: {len(frame_content)}")
                            
                            # Look for availability data
                            if 'avail' in frame_content.lower() or 'calendar' in frame_content.lower():
                                print(f"    Contains availability/calendar data!")
                                
                                # Save for analysis
                                with open('/tmp/track_iframe_content.html', 'w') as f:
                                    f.write(frame_content)
                                print(f"    Saved to /tmp/track_iframe_content.html")
                    except Exception as e:
                        print(f"    Cannot access frame content: {e}")
            
            # Check captured requests for Track API calls
            print("\n\n📍 Track-related network requests:")
            track_requests = [r for r in all_requests if 'track' in r['url'].lower()]
            for req in track_requests[:20]:
                print(f"  [{req['method']}] {req['url'][:100]}")
            
            # Look for any API/JSON requests
            print("\n\n📍 API/JSON requests:")
            api_requests = [r for r in all_requests if any(x in r['url'].lower() for x in ['api', 'json', 'avail', 'calendar', 'rate'])]
            for req in api_requests[:20]:
                print(f"  [{req['method']}] {req['url'][:100]}")
                
        except Exception as e:
            print(f"  Error loading page: {e}")
        
        print("\n\n📍 Waiting 10 seconds for any lazy-loaded content...")
        await asyncio.sleep(10)
        
        # Final check for Track requests
        print("\n📍 Final Track-related requests:")
        track_requests = [r for r in all_requests if 'track' in r['url'].lower()]
        for req in track_requests:
            print(f"  [{req['method']}] {req['url']}")
        
        await browser.close()


if __name__ == "__main__":
    asyncio.run(investigate_track_api())
