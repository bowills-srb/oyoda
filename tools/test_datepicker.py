#!/usr/bin/env python3
"""
Try using the date picker inputs directly instead of clicking calendar cells.
"""

from playwright.sync_api import sync_playwright
import json
import re

BASE_URL = "https://www.beachhabitats30a.com"

def main():
    print("=" * 70)
    print("TESTING DATE PICKER INPUTS")
    print("=" * 70)
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        
        # Capture AJAX responses
        ajax_responses = []
        
        def on_response(response):
            url = response.url
            if 'ajax' in url or 'pricing' in url or 'rescms' in url:
                try:
                    body = response.text()
                    ajax_responses.append({
                        'url': url,
                        'status': response.status,
                        'body': body
                    })
                    print(f"\n📡 Response: {url[:70]}...")
                    # Check for dollar amounts
                    if '$' in body or 'total' in body.lower():
                        print(f"   💰 PRICING DATA: {body[:300]}")
                except:
                    pass
        
        page.on('response', on_response)
        
        # Load property page
        property_url = f"{BASE_URL}/30a-vacation-rentals/134-mystic-cobalt"
        print(f"\n1. Loading: {property_url}")
        page.goto(property_url, wait_until='networkidle')
        
        # Find form inputs
        print("\n2. Looking for date inputs...")
        
        # Look for the booking form inputs
        inputs = page.locator('input')
        print(f"   Found {inputs.count()} inputs")
        
        for i in range(inputs.count()):
            inp = inputs.nth(i)
            input_type = inp.get_attribute('type')
            input_class = inp.get_attribute('class') or ''
            input_name = inp.get_attribute('name') or ''
            input_id = inp.get_attribute('id') or ''
            
            if 'date' in input_class.lower() or 'date' in input_name.lower() or 'begin' in input_class.lower() or 'end' in input_class.lower():
                print(f"   Input: type={input_type}, class={input_class}, name={input_name}, id={input_id}")
        
        # Try filling in the date inputs using JavaScript
        print("\n3. Trying to set dates via JavaScript...")
        
        # Set arrival date
        page.evaluate("""
            () => {
                // Find the begin date input
                const beginInput = document.querySelector('input.begin');
                if (beginInput) {
                    beginInput.value = '03/01/2026';
                    beginInput.dispatchEvent(new Event('change', { bubbles: true }));
                    console.log('Set begin date');
                }
                
                // Find the end date input  
                const endInput = document.querySelector('input.end');
                if (endInput) {
                    endInput.value = '03/04/2026';
                    endInput.dispatchEvent(new Event('change', { bubbles: true }));
                    console.log('Set end date');
                }
            }
        """)
        
        page.wait_for_timeout(2000)
        
        # Check if a quote button exists
        print("\n4. Looking for quote/booking buttons...")
        
        buttons = page.locator('button, input[type="submit"], a.btn, .book-btn, .quote-btn')
        for i in range(min(buttons.count(), 10)):
            btn = buttons.nth(i)
            text = btn.text_content() or ''
            btn_class = btn.get_attribute('class') or ''
            if any(word in text.lower() or word in btn_class.lower() for word in ['book', 'quote', 'check', 'price', 'avail']):
                print(f"   Button: '{text.strip()}' class={btn_class}")
        
        # Try clicking the Book Now or Check Availability button
        book_btn = page.locator('a:has-text("Book"), button:has-text("Book"), a:has-text("Check Availability")')
        if book_btn.count() > 0:
            print(f"\n5. Found booking button, clicking...")
            book_btn.first.click()
            page.wait_for_timeout(3000)
        
        # Look at the page HTML for pricing sections
        print("\n6. Searching page for pricing HTML patterns...")
        
        html = page.content()
        
        # Look for price patterns
        price_patterns = [
            r'class="[^"]*(?:price|rate|total|cost)[^"]*"[^>]*>[^<]*\$[\d,]+',
            r'\$[\d,]+(?:\.\d{2})?(?:/night|per night|nightly)?',
            r'(?:total|rate|price|cost)["\s:]+\$?[\d,]+',
        ]
        
        for pattern in price_patterns:
            matches = re.findall(pattern, html, re.I)
            if matches:
                print(f"\n   Pattern '{pattern[:30]}...':")
                for m in matches[:5]:
                    print(f"      {m[:100]}")
        
        # Check the rcItemAvailForm for any pricing config
        print("\n7. Checking for pricing in page config...")
        
        # Look for the Drupal settings with any pricing info
        pricing_match = re.search(r"'(?:price|rate|pricing|cost)'[^}]+}", html)
        if pricing_match:
            print(f"   Found pricing config: {pricing_match.group(0)[:200]}")
        
        # Summary of AJAX responses
        print("\n" + "=" * 70)
        print(f"CAPTURED {len(ajax_responses)} AJAX RESPONSES")
        print("=" * 70)
        
        for r in ajax_responses:
            print(f"\nURL: {r['url'][:80]}")
            print(f"Body: {r['body'][:400]}")
            
            # Look for pricing in response
            if '$' in r['body']:
                amounts = re.findall(r'\$[\d,]+(?:\.\d{2})?', r['body'])
                if amounts:
                    print(f"💰 Amounts found: {amounts}")
        
        browser.close()


if __name__ == "__main__":
    main()
