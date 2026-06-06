#!/usr/bin/env python3
"""
Test Beach Habitats Pricing API

The site has a pricing endpoint at /rescms/ajax/item/pricing/simple
Let's see if we can extract ADR (Average Daily Rate) data.
"""

import json
import re
from datetime import datetime, date, timedelta
from pathlib import Path

from bs4 import BeautifulSoup
import httpx
import pytest

BASE_URL = "https://www.beachhabitats30a.com"

def test_pricing_api():
    """Test the pricing API endpoint."""
    playwright = pytest.importorskip("playwright.sync_api")
    sync_playwright = playwright.sync_playwright
    
    print("=" * 70)
    print("TESTING BEACH HABITATS PRICING API")
    print("=" * 70)
    
    # First, let's look at the pricing endpoint from the saved script
    script_file = Path(__file__).parent.parent / "data" / "calendar_script_134-mystic-cobalt.js"
    
    if script_file.exists():
        with open(script_file) as f:
            content = f.read()
        
        # Look for pricing-related config
        print("\n1. Analyzing pricing config from saved script...")
        
        # Find the ajax URL
        ajax_match = re.search(r"'url'\s*:\s*'([^']*pricing[^']*)'", content)
        if ajax_match:
            print(f"   Found pricing API: {ajax_match.group(1)}")
        
        # Look for rate/price data
        rate_matches = re.findall(r"'(rate|price|adr|nightly)'\s*:\s*['\"]?([^'\"}\s,]+)", content, re.I)
        if rate_matches:
            print(f"   Found {len(rate_matches)} rate references")
            for key, val in rate_matches[:5]:
                print(f"     {key}: {val}")
    
    # Now let's try the actual pricing endpoint with Playwright
    print("\n2. Testing pricing API with browser...")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        # Capture API responses
        pricing_data = []
        
        def capture_response(response):
            if 'pricing' in response.url.lower():
                try:
                    data = response.json()
                    pricing_data.append({
                        'url': response.url,
                        'data': data
                    })
                    print(f"   Captured pricing response: {response.url[:60]}...")
                except:
                    pass
        
        page.on('response', capture_response)
        
        # Load a property page
        url = f"{BASE_URL}/30a-vacation-rentals/134-mystic-cobalt"
        print(f"\n   Loading: {url}")
        page.goto(url, wait_until='networkidle')
        
        # Try to trigger pricing by selecting dates
        print("\n   Attempting to trigger pricing request...")
        
        try:
            # Click on a date in the calendar to trigger pricing
            # Look for an available date
            available_dates = page.locator('td.day.av-O')
            if available_dates.count() > 0:
                print(f"   Found {available_dates.count()} available dates")
                
                # Click first available date (arrival)
                available_dates.first.click()
                page.wait_for_timeout(1000)
                
                # Click another date (departure)
                if available_dates.count() > 3:
                    available_dates.nth(3).click()
                    page.wait_for_timeout(2000)
        except Exception as e:
            print(f"   Could not interact with calendar: {e}")
        
        # Also try the direct AJAX endpoint
        print("\n3. Testing direct pricing endpoint...")
        
        # The endpoint format from the script
        # /rescms/ajax/item/pricing/simple
        
        # Try with entity ID 33 (134 Mystic Cobalt)
        entity_id = 33
        check_in = (date.today() + timedelta(days=30)).strftime('%Y-%m-%d')
        check_out = (date.today() + timedelta(days=33)).strftime('%Y-%m-%d')
        
        pricing_url = f"{BASE_URL}/rescms/ajax/item/pricing/simple?eid={entity_id}&begin={check_in}&end={check_out}"
        
        print(f"   Trying: {pricing_url}")
        
        # Use page to fetch (to maintain session/cookies)
        try:
            response = page.request.get(pricing_url)
            print(f"   Status: {response.status}")
            
            if response.status == 200:
                try:
                    data = response.json()
                    print(f"   Response: {json.dumps(data, indent=2)[:500]}")
                    pricing_data.append({
                        'url': pricing_url,
                        'data': data
                    })
                except:
                    print(f"   Response (text): {response.text()[:500]}")
        except Exception as e:
            print(f"   Error: {e}")
        
        browser.close()
        
        # Analyze captured pricing data
        if pricing_data:
            print("\n" + "=" * 70)
            print("PRICING DATA CAPTURED")
            print("=" * 70)
            
            for item in pricing_data:
                print(f"\nURL: {item['url']}")
                print(f"Data: {json.dumps(item['data'], indent=2)[:1000]}")
            
            # Save for analysis
            output_file = Path(__file__).parent.parent / "data" / "pricing_api_test.json"
            with open(output_file, 'w') as f:
                json.dump(pricing_data, f, indent=2)
            print(f"\nSaved to: {output_file}")
        else:
            print("\n⚠ No pricing data captured")
            print("The site may require specific session state or form submission")


if __name__ == "__main__":
    test_pricing_api()
