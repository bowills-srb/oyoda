#!/usr/bin/env python3
"""Try direct API call for 178SC with entity ID."""

from playwright.sync_api import sync_playwright
import json
import re

url = "https://www.beachhabitats30a.com/30a-vacation-rentals/178-spartina-cir"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()
    
    print(f"Loading page first to get session...")
    page.goto(url, wait_until='networkidle', timeout=30000)
    
    # Entity ID is 90 for this property
    entity_id = 90
    
    # Try the direct quote endpoint with various formats
    endpoints = [
        f"/rescms/ajax/item/pricing/quote?rcav%5Bbegin%5D=10%2F01%2F2026&rcav%5Bend%5D=10%2F04%2F2026&rcav%5Beid%5D={entity_id}",
        f"/rescms/ajax/item/pricing/quote?rcav[begin]=10/01/2026&rcav[end]=10/04/2026&rcav[eid]={entity_id}",
        f"/rescms/ajax/item/pricing/simple?eid={entity_id}&begin=10/01/2026&end=10/04/2026",
    ]
    
    for endpoint in endpoints:
        full_url = f"https://www.beachhabitats30a.com{endpoint}"
        print(f"\nTrying: {endpoint[:60]}...")
        
        try:
            response = page.request.get(full_url)
            body = response.text()
            print(f"  Status: {response.status}")
            print(f"  Response: {body[:300]}")
            
            if '$' in body:
                amounts = re.findall(r'\$([\d,]+(?:\.\d{2})?)', body)
                if amounts:
                    print(f"  💰 Found: {amounts}")
        except Exception as e:
            print(f"  Error: {e}")
    
    # Also try triggering via JavaScript with explicit form submission
    print("\n\nTrying JavaScript trigger...")
    
    # Capture any responses
    responses = []
    def capture(r):
        if 'pricing' in r.url:
            try:
                responses.append({'url': r.url, 'body': r.text()})
            except:
                pass
    
    page.on('response', capture)
    
    # Use jQuery to trigger the form like the page does
    result = page.evaluate("""
        () => {
            // Check if jQuery and the form plugin exist
            if (typeof jQuery !== 'undefined') {
                const $begin = jQuery('input.begin');
                const $end = jQuery('input.end');
                
                if ($begin.length && $end.length) {
                    $begin.val('10/01/2026').trigger('change');
                    $end.val('10/04/2026').trigger('change');
                    
                    // Try to find and trigger the availability form
                    const $form = jQuery('.rcav-form, .rc-avail-form, form[class*="avail"]');
                    if ($form.length) {
                        $form.trigger('submit');
                    }
                    
                    return {
                        begin: $begin.val(),
                        end: $end.val(),
                        formFound: $form.length
                    };
                }
                return { error: 'inputs not found' };
            }
            return { error: 'no jQuery' };
        }
    """)
    print(f"  JS result: {result}")
    
    page.wait_for_timeout(3000)
    
    print(f"  Captured {len(responses)} responses")
    for r in responses:
        print(f"    URL: {r['url'][:60]}")
        if '$' in r['body']:
            print(f"    💰 Has pricing!")
            print(f"    Body: {r['body'][:200]}")
    
    browser.close()
