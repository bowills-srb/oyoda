#!/usr/bin/env python3
"""
Debug script to test pricing API with VALID available dates.
"""

from playwright.sync_api import sync_playwright
from datetime import date, timedelta
import re
import json

BASE_URL = "https://www.beachhabitats30a.com"

def main():
    print("=" * 70)
    print("PRICING API DEBUG - WITH VALID DATES")
    print("=" * 70)
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        
        # Load the property page
        property_url = f"{BASE_URL}/30a-vacation-rentals/134-mystic-cobalt"
        print(f"\n1. Loading property page...")
        page.goto(property_url, wait_until='networkidle')
        
        # Extract availability from page
        html = page.content()
        
        # Find available date ranges from the avail array
        print("\n2. Extracting available date ranges from page...")
        avail_ranges = []
        for m in re.finditer(r"\{'b':'([^']+)','e':'([^']+)','a':'1'", html):
            start = m.group(1)
            end = m.group(2)
            avail_ranges.append((start, end))
            print(f"   Available: {start} to {end}")
        
        if not avail_ranges:
            print("   No available ranges found!")
            browser.close()
            return
        
        # Pick a valid available range (first one that's in the future)
        today = date.today()
        valid_range = None
        for start_str, end_str in avail_ranges:
            start = date.fromisoformat(start_str)
            end = date.fromisoformat(end_str)
            if start > today and (end - start).days >= 3:
                valid_range = (start, end)
                break
        
        if not valid_range:
            print("   No valid future range found!")
            browser.close()
            return
        
        check_in = valid_range[0]
        check_out = min(check_in + timedelta(days=3), valid_range[1])
        
        print(f"\n3. Testing with valid dates: {check_in} to {check_out}")
        
        # Test the pricing endpoint with correct date format
        entity_id = 33
        
        # The website uses MM/DD/YYYY format
        begin_str = check_in.strftime('%m/%d/%Y')
        end_str = check_out.strftime('%m/%d/%Y')
        
        url = f"{BASE_URL}/rescms/ajax/item/pricing/simple?eid={entity_id}&begin={begin_str}&end={end_str}"
        print(f"\n   URL: {url}")
        
        response = page.request.get(url)
        print(f"   Status: {response.status}")
        
        body = response.text()
        print(f"\n   Response:")
        print(body)
        
        # Try to parse as JSON
        try:
            data = json.loads(body)
            print(f"\n   Parsed JSON:")
            print(json.dumps(data, indent=2))
            
            # If content field exists, it's HTML - let's see what's in it
            if 'content' in data:
                content = data['content']
                # Unescape HTML entities
                content = content.replace('\\u003C', '<').replace('\\u003E', '>').replace('\\u0022', '"')
                print(f"\n   Content HTML:")
                print(content)
                
                # Look for dollar amounts
                amounts = re.findall(r'\$[\d,]+(?:\.\d{2})?', content)
                if amounts:
                    print(f"\n   Found amounts: {amounts}")
        except json.JSONDecodeError:
            print("   (Not valid JSON)")
        
        # Also try interacting with the page calendar
        print("\n4. Testing by clicking calendar dates...")
        
        # Reload page fresh
        page.goto(property_url, wait_until='networkidle')
        
        # Set up response capture
        pricing_responses = []
        
        def capture(response):
            if 'pricing' in response.url:
                try:
                    pricing_responses.append({
                        'url': response.url,
                        'body': response.text()
                    })
                except:
                    pass
        
        page.on('response', capture)
        
        # Try to click on specific dates
        # First find the begin date input
        try:
            begin_input = page.locator('input.begin')
            if begin_input.count() > 0:
                print(f"   Found begin input, clicking...")
                begin_input.click()
                page.wait_for_timeout(500)
                
                # Now find an available date in the datepicker
                # Dates in datepicker have specific classes
                datepicker_available = page.locator('.ui-datepicker-calendar td:not(.ui-state-disabled) a')
                count = datepicker_available.count()
                print(f"   Found {count} clickable dates in datepicker")
                
                if count > 5:
                    # Click a date
                    datepicker_available.nth(5).click()
                    page.wait_for_timeout(1000)
                    
                    # Click end input
                    end_input = page.locator('input.end')
                    if end_input.count() > 0:
                        end_input.click()
                        page.wait_for_timeout(500)
                        
                        # Click another date
                        datepicker_available2 = page.locator('.ui-datepicker-calendar td:not(.ui-state-disabled) a')
                        if datepicker_available2.count() > 10:
                            datepicker_available2.nth(10).click()
                            page.wait_for_timeout(2000)
        except Exception as e:
            print(f"   Error: {e}")
        
        print(f"\n   Captured {len(pricing_responses)} pricing responses")
        for pr in pricing_responses:
            print(f"\n   URL: {pr['url'][:80]}")
            print(f"   Body: {pr['body'][:500]}")
        
        browser.close()


if __name__ == "__main__":
    main()
