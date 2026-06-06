#!/usr/bin/env python3
"""
Watch all network requests when interacting with the booking calendar.
"""

from playwright.sync_api import sync_playwright
import json

BASE_URL = "https://www.beachhabitats30a.com"

def main():
    print("=" * 70)
    print("WATCHING CALENDAR INTERACTIONS")
    print("=" * 70)
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)  # Visible browser for debugging
        context = browser.new_context()
        page = context.new_page()
        
        # Capture ALL requests
        all_requests = []
        all_responses = []
        
        def on_request(request):
            if 'google' not in request.url and 'analytics' not in request.url:
                all_requests.append({
                    'url': request.url,
                    'method': request.method,
                })
        
        def on_response(response):
            url = response.url
            if ('ajax' in url or 'pricing' in url or 'avail' in url or 'quote' in url or 'rescms' in url):
                try:
                    body = response.text()
                    all_responses.append({
                        'url': url,
                        'status': response.status,
                        'body': body[:2000]
                    })
                    print(f"\n📡 AJAX Response: {url[:60]}...")
                    print(f"   Body: {body[:200]}")
                except:
                    pass
        
        page.on('request', on_request)
        page.on('response', on_response)
        
        # Load property page
        property_url = f"{BASE_URL}/30a-vacation-rentals/134-mystic-cobalt"
        print(f"\n1. Loading: {property_url}")
        page.goto(property_url, wait_until='networkidle')
        
        print("\n2. Looking for the availability calendar...")
        
        # Find the main calendar widget
        calendar = page.locator('.rcav-calendar')
        if calendar.count() > 0:
            print(f"   Found calendar widget")
        
        # Look at the availability tab
        avail_tab = page.locator('a[href="#listing-avail"]')
        if avail_tab.count() > 0:
            print("   Found availability tab, clicking...")
            avail_tab.click()
            page.wait_for_timeout(1000)
        
        # Now find available dates (green/available cells)
        print("\n3. Finding available dates in calendar...")
        
        # The calendar uses av-O for available, av-X for unavailable
        avail_cells = page.locator('td.day.av-O')
        count = avail_cells.count()
        print(f"   Found {count} available date cells")
        
        if count > 0:
            # Get info about first few available cells
            for i in range(min(5, count)):
                cell = avail_cells.nth(i)
                text = cell.text_content()
                classes = cell.get_attribute('class')
                print(f"   Cell {i}: day={text}, classes={classes}")
        
        print("\n4. Simulating date selection...")
        
        # Click on an available date (arrival)
        if count > 0:
            print("   Clicking first available date (arrival)...")
            avail_cells.first.click()
            page.wait_for_timeout(1500)
            
            # Now click on departure date
            if count > 3:
                print("   Clicking departure date...")
                avail_cells.nth(3).click()
                page.wait_for_timeout(2000)
        
        # Check for any pricing display
        print("\n5. Looking for pricing display...")
        
        price_elements = page.locator('[class*="price"], [class*="total"], [class*="rate"], [class*="quote"]')
        for i in range(min(price_elements.count(), 10)):
            elem = price_elements.nth(i)
            text = elem.text_content()
            if text and '$' in text:
                print(f"   Found: {text.strip()[:100]}")
        
        # Also check for any quote/pricing container
        quote_container = page.locator('.rc-quote, .quote-container, .pricing-container, .rc-pricing')
        if quote_container.count() > 0:
            print(f"\n   Quote container content:")
            print(quote_container.first.text_content()[:500])
        
        # Wait a moment to see if anything loads
        page.wait_for_timeout(2000)
        
        print("\n" + "=" * 70)
        print("CAPTURED AJAX RESPONSES")
        print("=" * 70)
        
        for r in all_responses:
            print(f"\nURL: {r['url']}")
            print(f"Status: {r['status']}")
            print(f"Body: {r['body'][:300]}")
        
        # Keep browser open for manual inspection
        print("\n\nBrowser will stay open for 30 seconds for manual inspection...")
        print("Look at the page and the pricing area.")
        page.wait_for_timeout(30000)
        
        browser.close()


if __name__ == "__main__":
    main()
