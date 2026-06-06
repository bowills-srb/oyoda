#!/usr/bin/env python3
"""Try triggering the AJAX pricing call directly"""

import asyncio
import re
from datetime import date, timedelta
from playwright.async_api import async_playwright


async def debug_calendar():
    url = "https://www.benchmark30a.com/emerald-coast-vacation-rentals/best-both-worlds"
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()
        
        # Capture AJAX responses
        pricing_responses = []
        
        async def capture_response(response):
            if 'pricing' in response.url.lower() or 'ajax' in response.url.lower():
                try:
                    body = await response.text()
                    pricing_responses.append({'url': response.url, 'body': body[:500]})
                except:
                    pass
        
        page.on('response', capture_response)
        
        print(f"Loading: {url}\n")
        await page.goto(url, wait_until='networkidle', timeout=60000)
        await asyncio.sleep(3)
        
        # Get available dates
        html = await page.content()
        available_ranges = []
        avail_match = re.search(r'["\']avail["\']\s*:\s*\[([^\]]+)\]', html)
        if avail_match:
            for m in re.finditer(r'["\']b["\']\s*:\s*["\'](\d{4}-\d{2}-\d{2})["\'].*?["\']e["\']\s*:\s*["\'](\d{4}-\d{2}-\d{2})["\'].*?["\']a["\']\s*:\s*["\'](\d)["\']', avail_match.group(1)):
                if m.group(3) == '1':
                    start = date.fromisoformat(m.group(1))
                    end = date.fromisoformat(m.group(2))
                    available_ranges.append((start, end))
        
        today = date.today()
        target_arrival = None
        for start, end in available_ranges:
            if start <= today:
                start = today + timedelta(days=1)
            if (end - start).days >= 4:
                target_arrival = start
                break
        
        target_departure = target_arrival + timedelta(days=4)
        arrival_str = target_arrival.strftime('%m/%d/%Y')
        departure_str = target_departure.strftime('%m/%d/%Y')
        
        print(f"Target dates: {arrival_str} to {departure_str}")
        
        # Get the ajax config and make direct call
        print("\n=== Getting AJAX config and making direct call ===")
        result = await page.evaluate(f"""
            async () => {{
                const results = [];
                const $ = jQuery;
                
                try {{
                    const config = Drupal.settings.rcItemAvailForm[0];
                    results.push('Ajax URL: ' + config.ajx.url);
                    results.push('Entity ID: ' + config.eid);
                    
                    // Set dates via datepicker
                    $('input.begin').datepicker('setDate', '{arrival_str}');
                    $('input.end').datepicker('setDate', '{departure_str}');
                    
                    // Build the AJAX data like the form would
                    const ajaxData = {{
                        eid: config.eid,
                        beg: '{arrival_str}',
                        end: '{departure_str}',
                        adu: 1,
                        chi: 0
                    }};
                    
                    results.push('AJAX data: ' + JSON.stringify(ajaxData));
                    
                    // Make the AJAX call
                    const response = await $.ajax({{
                        url: config.ajx.url,
                        type: 'POST',
                        data: ajaxData,
                        dataType: 'json'
                    }});
                    
                    results.push('AJAX response received');
                    results.push('Response keys: ' + Object.keys(response).join(', '));
                    
                    if (response.content) {{
                        results.push('Content preview: ' + response.content.substring(0, 300));
                    }}
                    
                    // Also try to find total in response
                    const responseStr = JSON.stringify(response);
                    const priceMatch = responseStr.match(/\\$([\\d,]+)/);
                    if (priceMatch) {{
                        results.push('Price found: $' + priceMatch[1]);
                    }}
                    
                }} catch(e) {{
                    results.push('Error: ' + e.message);
                }}
                
                return results;
            }}
        """)
        
        for r in result:
            print(f"  {r}")
        
        # Check captured responses
        print(f"\n=== Captured {len(pricing_responses)} AJAX responses ===")
        for resp in pricing_responses:
            print(f"URL: {resp['url']}")
            print(f"Body: {resp['body'][:300]}")
        
        print("\nBrowser open 30s...")
        await asyncio.sleep(30)
        await browser.close()

asyncio.run(debug_calendar())
