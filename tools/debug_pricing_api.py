#!/usr/bin/env python3
"""
Debug script to see what the pricing API actually returns.
"""

from playwright.sync_api import sync_playwright
from urllib.parse import urlencode
from datetime import date, timedelta

BASE_URL = "https://www.beachhabitats30a.com"

def main():
    print("=" * 70)
    print("PRICING API DEBUG")
    print("=" * 70)
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        
        # First load the property page to establish session
        property_url = f"{BASE_URL}/30a-vacation-rentals/134-mystic-cobalt"
        print(f"\n1. Loading property page: {property_url}")
        page.goto(property_url, wait_until='networkidle')
        
        # Capture all network requests
        responses = []
        
        def capture_response(response):
            if 'pricing' in response.url.lower() or 'ajax' in response.url.lower():
                try:
                    body = response.text()
                    responses.append({
                        'url': response.url,
                        'status': response.status,
                        'body': body[:2000]
                    })
                except:
                    pass
        
        page.on('response', capture_response)
        
        # Try clicking on calendar dates to trigger pricing
        print("\n2. Trying to interact with calendar...")
        
        try:
            # Find available dates in calendar
            available = page.locator('td.day.av-O')
            count = available.count()
            print(f"   Found {count} available dates")
            
            if count > 0:
                # Click first available (arrival)
                print("   Clicking first available date...")
                available.first.click()
                page.wait_for_timeout(1500)
                
                # Click another available (departure)
                if count > 3:
                    print("   Clicking departure date...")
                    available.nth(3).click()
                    page.wait_for_timeout(2000)
        except Exception as e:
            print(f"   Calendar interaction error: {e}")
        
        # Also try direct API call
        print("\n3. Testing direct API endpoints...")
        
        entity_id = 33  # 134 Mystic Cobalt
        check_in = date.today() + timedelta(days=30)
        check_out = check_in + timedelta(days=3)
        
        # Try different endpoint formats
        endpoints = [
            f"/rescms/ajax/item/pricing/simple?eid={entity_id}&begin={check_in.strftime('%m/%d/%Y')}&end={check_out.strftime('%m/%d/%Y')}",
            f"/rescms/ajax/item/pricing/simple?eid={entity_id}&begin={check_in.isoformat()}&end={check_out.isoformat()}",
            f"/rescms/ajax/item/pricing?eid={entity_id}&begin={check_in.strftime('%m/%d/%Y')}&end={check_out.strftime('%m/%d/%Y')}",
            f"/ngt/ajax/pricing/{entity_id}?begin={check_in.strftime('%m/%d/%Y')}&end={check_out.strftime('%m/%d/%Y')}",
        ]
        
        for endpoint in endpoints:
            url = f"{BASE_URL}{endpoint}"
            print(f"\n   Testing: {endpoint[:60]}...")
            
            try:
                response = page.request.get(url)
                print(f"   Status: {response.status}")
                
                body = response.text()
                print(f"   Response ({len(body)} chars):")
                print(f"   {body[:500]}")
                
                if body:
                    responses.append({
                        'url': url,
                        'status': response.status,
                        'body': body[:2000]
                    })
            except Exception as e:
                print(f"   Error: {e}")
        
        # Check what we captured
        print("\n" + "=" * 70)
        print("CAPTURED RESPONSES")
        print("=" * 70)
        
        for r in responses:
            print(f"\nURL: {r['url'][:80]}")
            print(f"Status: {r['status']}")
            print(f"Body: {r['body'][:500]}")
        
        # Also look at the page for pricing display elements
        print("\n" + "=" * 70)
        print("PRICING DISPLAY ELEMENTS ON PAGE")
        print("=" * 70)
        
        # Look for pricing-related elements
        selectors = [
            '.rc-pricing',
            '.pricing',
            '.quote',
            '.total',
            '.rate',
            '[class*="price"]',
            '[class*="cost"]',
            '[class*="total"]',
        ]
        
        for sel in selectors:
            try:
                elements = page.locator(sel)
                count = elements.count()
                if count > 0:
                    print(f"\n{sel}: {count} elements")
                    for i in range(min(count, 3)):
                        text = elements.nth(i).text_content()
                        if text:
                            print(f"  {i}: {text[:100]}")
            except:
                pass
        
        browser.close()


if __name__ == "__main__":
    main()
