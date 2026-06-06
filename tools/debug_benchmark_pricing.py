#!/usr/bin/env python3
"""Debug Benchmark pricing - select both arrival and departure dates."""

import asyncio
import re
from datetime import date, timedelta
from playwright.async_api import async_playwright


async def debug_pricing():
    url = "https://www.benchmark30a.com/emerald-coast-vacation-rentals/best-both-worlds"
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()
        
        print(f"Loading: {url}\n")
        await page.goto(url, wait_until='networkidle', timeout=60000)
        await asyncio.sleep(2)
        
        html = await page.content()
        
        # =================================================================
        # 1. Find available dates from rcItemAvailForm
        # =================================================================
        print("=" * 70)
        print("1. FINDING AVAILABLE DATES")
        print("=" * 70)
        
        available_ranges = []
        avail_match = re.search(r'["\']avail["\']\s*:\s*\[([^\]]+)\]', html)
        if avail_match:
            avail_content = avail_match.group(1)
            for m in re.finditer(r'["\']b["\']\s*:\s*["\'](\d{4}-\d{2}-\d{2})["\'].*?["\']e["\']\s*:\s*["\'](\d{4}-\d{2}-\d{2})["\'].*?["\']a["\']\s*:\s*["\'](\d)["\']', avail_content):
                if m.group(3) == '1':  # a=1 means available
                    start = date.fromisoformat(m.group(1))
                    end = date.fromisoformat(m.group(2))
                    available_ranges.append((start, end))
        
        print(f"Found {len(available_ranges)} available ranges")
        today = date.today()
        
        # Find a good date range (at least 4 nights available)
        arrival_date = None
        departure_date = None
        
        for start, end in available_ranges:
            if start <= today:
                start = today + timedelta(days=1)
            if (end - start).days >= 4:
                arrival_date = start
                departure_date = start + timedelta(days=4)
                break
        
        if not arrival_date:
            print("No suitable date range found!")
            await browser.close()
            return
        
        print(f"Arrival: {arrival_date}")
        print(f"Departure: {departure_date}")
        
        # =================================================================
        # 2. Select ARRIVAL date
        # =================================================================
        print("\n" + "=" * 70)
        print("2. SELECTING ARRIVAL DATE")
        print("=" * 70)
        
        # Click on arrival input to open calendar
        arrival_input = await page.query_selector('input.begin')
        if not arrival_input:
            arrival_input = await page.query_selector('input[name*="begin"], input[placeholder*="Arrival"], input[placeholder*="Check-in"]')
        
        if arrival_input:
            await arrival_input.click()
            await asyncio.sleep(1)
            print("Clicked arrival input")
            
            # Navigate to correct month
            target_month = arrival_date.strftime('%B')
            target_year = str(arrival_date.year)
            
            for _ in range(12):
                header = await page.query_selector('.ui-datepicker-title')
                if header:
                    header_text = await header.inner_text()
                    if target_month in header_text and target_year in header_text:
                        print(f"Found correct month: {header_text}")
                        break
                    # Click next
                    next_btn = await page.query_selector('.ui-datepicker-next')
                    if next_btn:
                        await next_btn.click()
                        await asyncio.sleep(0.3)
            
            # Click the day
            day_num = str(arrival_date.day)
            # Find clickable days
            all_days = await page.query_selector_all('.ui-datepicker-calendar td:not(.ui-datepicker-unselectable) a')
            for day_elem in all_days:
                text = await day_elem.inner_text()
                if text.strip() == day_num:
                    print(f"Clicking arrival day: {day_num}")
                    await day_elem.click()
                    await asyncio.sleep(1)
                    break
        
        # =================================================================
        # 3. Select DEPARTURE date
        # =================================================================
        print("\n" + "=" * 70)
        print("3. SELECTING DEPARTURE DATE")
        print("=" * 70)
        
        await asyncio.sleep(1)
        
        # Click on departure input
        departure_input = await page.query_selector('input.end')
        if not departure_input:
            departure_input = await page.query_selector('input[name*="end"], input[placeholder*="Departure"], input[placeholder*="Check-out"]')
        
        if departure_input:
            await departure_input.click()
            await asyncio.sleep(1)
            print("Clicked departure input")
            
            # Navigate to correct month
            target_month = departure_date.strftime('%B')
            target_year = str(departure_date.year)
            
            for _ in range(12):
                header = await page.query_selector('.ui-datepicker-title')
                if header:
                    header_text = await header.inner_text()
                    if target_month in header_text and target_year in header_text:
                        print(f"Found correct month: {header_text}")
                        break
                    next_btn = await page.query_selector('.ui-datepicker-next')
                    if next_btn:
                        await next_btn.click()
                        await asyncio.sleep(0.3)
            
            # Click the day
            day_num = str(departure_date.day)
            all_days = await page.query_selector_all('.ui-datepicker-calendar td:not(.ui-datepicker-unselectable) a')
            for day_elem in all_days:
                text = await day_elem.inner_text()
                if text.strip() == day_num:
                    print(f"Clicking departure day: {day_num}")
                    await day_elem.click()
                    await asyncio.sleep(2)
                    break
        
        # =================================================================
        # 4. Extract pricing from page
        # =================================================================
        print("\n" + "=" * 70)
        print("4. EXTRACTING PRICING")
        print("=" * 70)
        
        await asyncio.sleep(2)
        
        # Get page content
        page_text = await page.inner_text('body')
        html = await page.content()
        
        # Look for the pricing area - usually near the booking form
        pricing_selectors = [
            '.rc-item-pricing',
            '.rc-pricing',
            '.booking-pricing',
            '.price-breakdown',
            '.quote-details',
            '[class*="pricing"]',
            '[class*="total"]',
            '.rc-avail-pricing',
        ]
        
        for selector in pricing_selectors:
            try:
                elems = await page.query_selector_all(selector)
                for elem in elems:
                    text = await elem.inner_text()
                    if '$' in text:
                        print(f"\n✅ Found pricing ({selector}):")
                        print(f"   {text[:300]}")
            except:
                continue
        
        # Look for specific price patterns
        print("\n\nSearching for price patterns in page:")
        
        patterns = [
            (r'Lodging[:\s]*\$([\d,]+(?:\.\d{2})?)', 'Lodging'),
            (r'Total[:\s]*\$([\d,]+(?:\.\d{2})?)', 'Total'),
            (r'Rent[:\s]*\$([\d,]+(?:\.\d{2})?)', 'Rent'),
            (r'\$([\d,]+(?:\.\d{2})?)\s*/\s*night', 'Per night'),
            (r'Cleaning[:\s]*\$([\d,]+(?:\.\d{2})?)', 'Cleaning'),
            (r'Tax(?:es)?[:\s]*\$([\d,]+(?:\.\d{2})?)', 'Taxes'),
        ]
        
        for pattern, name in patterns:
            matches = re.findall(pattern, page_text, re.IGNORECASE)
            if matches:
                print(f"  {name}: ${matches[0]}")
        
        # Get the booking form area specifically
        print("\n\nBooking form area content:")
        form_area = await page.query_selector('.rc-item-avail-form, .booking-form, [class*="avail-form"]')
        if form_area:
            form_text = await form_area.inner_text()
            print(form_text[:500])
        
        # =================================================================
        # 5. Keep browser open to verify
        # =================================================================
        print("\n" + "=" * 70)
        print("BROWSER OPEN - Verify the pricing you see matches what was extracted")
        print("=" * 70)
        
        await asyncio.sleep(60)
        await browser.close()


asyncio.run(debug_pricing())
