#!/usr/bin/env python3
"""Deep debug of 178SC page structure."""

from playwright.sync_api import sync_playwright
import re

url = "https://www.beachhabitats30a.com/30a-vacation-rentals/178-spartina-cir"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    
    print(f"Loading: {url}\n")
    page.goto(url, wait_until='networkidle', timeout=30000)
    
    # Check for date inputs
    print("Looking for date inputs...")
    
    begin_input = page.locator('input.begin')
    end_input = page.locator('input.end')
    
    print(f"  input.begin count: {begin_input.count()}")
    print(f"  input.end count: {end_input.count()}")
    
    if begin_input.count() > 0:
        print(f"  begin input visible: {begin_input.first.is_visible()}")
        print(f"  begin input enabled: {begin_input.first.is_enabled()}")
    
    # Check for any pricing-related elements
    print("\nLooking for pricing elements...")
    
    selectors = [
        '.rc-pricing',
        '.rc-item-quote', 
        '.rcav-calendar',
        '[class*="avail"]',
        '[class*="price"]',
        '[class*="quote"]',
    ]
    
    for sel in selectors:
        count = page.locator(sel).count()
        if count > 0:
            print(f"  {sel}: {count} elements")
    
    # Check page title to make sure we're on the right page
    title = page.title()
    print(f"\nPage title: {title}")
    
    # Look for any error messages
    html = page.content()
    if 'not found' in html.lower() or '404' in html:
        print("\n⚠️ Page might be 404 or not found!")
    
    # Check if there's a booking widget at all
    if 'rcItemAvailForm' in html:
        print("\n✓ rcItemAvailForm config found")
        
        # Extract entity ID
        eid_match = re.search(r"'eid'\s*:\s*'(\d+)'", html)
        if eid_match:
            print(f"  Entity ID: {eid_match.group(1)}")
    else:
        print("\n❌ No rcItemAvailForm config found - this property may not have online booking")
    
    # Try clicking on the availability tab if it exists
    avail_tab = page.locator('a[href="#listing-avail"]')
    if avail_tab.count() > 0:
        print("\nClicking availability tab...")
        avail_tab.click()
        page.wait_for_timeout(1000)
        
        # Re-check inputs
        begin_input = page.locator('input.begin')
        print(f"  input.begin count after tab click: {begin_input.count()}")
    
    browser.close()
