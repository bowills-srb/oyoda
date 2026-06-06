#!/usr/bin/env python3
"""Mimic the Beach Habitats approach - capture AJAX response after form interaction"""

import asyncio
import json
import re
from datetime import date, timedelta
from playwright.async_api import async_playwright


async def get_pricing():
    url = "https://www.benchmark30a.com/emerald-coast-vacation-rentals/best-both-worlds"
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()
        
        # Capture ALL responses
        pricing_responses = []
        
        async def capture_response(response):
            url_lower = response.url.lower()
            if 'pricing' in url_lower or 'quote' in url_lower or 'rescms' in url_lower:
                try:
                    body = await response.text()
                    pricing_responses.append({
                        'url': response.url,
                        'status': response.status,
                        'body': body
                    })
                    print(f"  📥 Captured: {response.url[:60]}...")
                except:
                    pass
        
        page.on('response', capture_response)
        
        print(f"Loading: {url}\n")
        await page.goto(url, wait_until='networkidle', timeout=60000)
        await asyncio.sleep(2)
        
        # Get available ranges and config
        html = await page.content()
        
        config = await page.evaluate("() => Drupal.settings.rcItemAvailForm[0]")
        min_stay = int(config.get('mns', 1))
        print(f"Min stay: {min_stay}")
        
        available_ranges = []
        avail_match = re.search(r'["\']avail["\']\s*:\s*\[([^\]]+)\]', html)
        if avail_match:
            for m in re.finditer(r'["\']b["\']\s*:\s*["\'](\d{4}-\d{2}-\d{2})["\'].*?["\']e["\']\s*:\s*["\'](\d{4}-\d{2}-\d{2})["\'].*?["\']a["\']\s*:\s*["\'](\d)["\']', avail_match.group(1)):
                if m.group(3) == '1':
                    start = date.fromisoformat(m.group(1))
                    end = date.fromisoformat(m.group(2))
                    available_ranges.append((start, end))
        
        today = date.today()
        target_arrival = target_departure = None
        
        for start, end in available_ranges:
            if start <= today:
                start = today + timedelta(days=1)
            if (end - start).days >= max(min_stay, 3):
                target_arrival = start
                target_departure = start + timedelta(days=max(min_stay, 3))
                break
        
        arrival_str = target_arrival.strftime('%m/%d/%Y')
        departure_str = target_departure.strftime('%m/%d/%Y')
        nights = (target_departure - target_arrival).days
        
        print(f"Using: {arrival_str} to {departure_str} ({nights} nights)")
        
        # Clear captured responses
        pricing_responses.clear()
        
        # TYPE the dates into the inputs (like a human would)
        print("\n=== Typing dates into form ===")
        
        # Click and clear arrival input, then type
        arrival_input = await page.query_selector('input.begin')
        await arrival_input.click()
        await asyncio.sleep(0.5)
        await arrival_input.fill('')  # Clear
        await arrival_input.type(arrival_str, delay=50)  # Type slowly
        await asyncio.sleep(0.5)
        
        # Press Tab or click elsewhere to trigger blur/change
        await page.keyboard.press('Tab')
        await asyncio.sleep(1)
        
        # Now departure
        departure_input = await page.query_selector('input.end')
        await departure_input.click()
        await asyncio.sleep(0.5)
        await departure_input.fill('')
        await departure_input.type(departure_str, delay=50)
        await asyncio.sleep(0.5)
        await page.keyboard.press('Tab')
        await asyncio.sleep(2)
        
        print(f"Captured {len(pricing_responses)} responses so far")
        
        # Click Search Availability
        print("\n=== Clicking SEARCH AVAILABILITY ===")
        search_btn = await page.query_selector('button:has-text("SEARCH AVAILABILITY")')
        if search_btn:
            await search_btn.click()
            await asyncio.sleep(3)
        
        print(f"\n=== CAPTURED {len(pricing_responses)} TOTAL RESPONSES ===")
        for resp in pricing_responses:
            print(f"\nURL: {resp['url']}")
            print(f"Status: {resp['status']}")
            body = resp['body']
            print(f"Body preview: {body[:500]}")
            
            # Try to parse as JSON
            try:
                data = json.loads(body)
                if 'content' in data:
                    content = data['content']
                    prices = re.findall(r'\$([\d,]+)', content)
                    if prices:
                        print(f"💰 Prices in content: {prices}")
            except:
                # Check for dollar amounts directly
                prices = re.findall(r'\$([\d,]+)', body)
                if prices:
                    print(f"💰 Prices found: {prices}")
        
        # Also check page content
        print("\n=== Checking page for price ===")
        body_text = await page.inner_text('body')
        match = re.search(r'\$\s*([\d,]+)\s*\+\s*tax', body_text)
        if match:
            print(f"💰 Page shows: ${match.group(1)} + tax")
        
        print("\nBrowser open 30s...")
        await asyncio.sleep(30)
        await browser.close()

asyncio.run(get_pricing())
