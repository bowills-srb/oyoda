#!/usr/bin/env python3
"""
Booking Discovery & Test Script

Run this script locally to discover API endpoints and test booking data extraction.
This uses Playwright to intercept network requests and find hidden APIs.

USAGE:
    cd ~/Downloads/STR-Beach_Habitats
    pip install playwright httpx beautifulsoup4 lxml icalendar
    playwright install chromium
    python tools/booking_discovery.py

OUTPUT:
    - Discovered API endpoints
    - Sample calendar/availability data
    - iCal URLs if found
"""

import json
import re
import time
from datetime import datetime
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("ERROR: Playwright not installed.")
    print("Run: pip install playwright && playwright install chromium")
    exit(1)

try:
    import httpx
except ImportError:
    print("ERROR: httpx not installed. Run: pip install httpx")
    exit(1)

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("ERROR: beautifulsoup4 not installed. Run: pip install beautifulsoup4 lxml")
    exit(1)


BASE_URL = "https://www.beachhabitats30a.com"
TEST_PROPERTIES = [
    "134-mystic-cobalt",
    "sea-la-vie",
    "108-silver-laurel-way",
]

# Store discovered data
discovered = {
    "api_endpoints": [],
    "ical_urls": [],
    "calendar_data": [],
    "pricing_data": [],
}


def discover_property_apis(property_slug: str):
    """Use Playwright to discover API endpoints for a property."""
    
    url = f"{BASE_URL}/30a-vacation-rentals/{property_slug}"
    print(f"\n{'='*70}")
    print(f"DISCOVERING: {property_slug}")
    print(f"URL: {url}")
    print("="*70)
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        )
        page = context.new_page()
        
        # Intercept all network requests
        api_calls = []
        
        def handle_request(request):
            url_lower = request.url.lower()
            # Look for API/data endpoints
            if any(kw in url_lower for kw in [
                'api', 'calendar', 'availability', 'rates', 'pricing',
                'booking', 'ical', '.ics', 'json', 'ajax', 'widget'
            ]):
                api_calls.append({
                    'url': request.url,
                    'method': request.method,
                    'resource_type': request.resource_type,
                })
        
        def handle_response(response):
            url_lower = response.url.lower()
            content_type = response.headers.get('content-type', '')
            
            # Capture JSON responses
            if 'json' in content_type or any(kw in url_lower for kw in ['api', 'calendar', 'availability']):
                try:
                    body = response.json()
                    if body:
                        discovered["calendar_data"].append({
                            "url": response.url,
                            "property": property_slug,
                            "data": body,
                        })
                        print(f"  📦 Captured JSON from: {response.url[:60]}...")
                except:
                    pass
            
            # Capture iCal responses
            if '.ics' in url_lower or 'text/calendar' in content_type:
                try:
                    body = response.text()
                    discovered["ical_urls"].append({
                        "url": response.url,
                        "property": property_slug,
                        "content": body[:500],
                    })
                    print(f"  📅 Found iCal: {response.url}")
                except:
                    pass
        
        page.on('request', handle_request)
        page.on('response', handle_response)
        
        # Load the page
        print("\n1. Loading page...")
        try:
            page.goto(url, wait_until='networkidle', timeout=30000)
            print("   ✓ Page loaded")
        except Exception as e:
            print(f"   ✗ Error loading page: {e}")
            browser.close()
            return
        
        # Wait for any lazy-loaded content
        time.sleep(2)
        
        # Look for and click on Availability tab/section
        print("\n2. Looking for availability section...")
        availability_selectors = [
            'text=Availability',
            'text=Calendar',
            'text=Check Availability',
            '[data-tab="availability"]',
            '#availability-tab',
            'a[href*="availability"]',
        ]
        
        for selector in availability_selectors:
            try:
                element = page.locator(selector).first
                if element.is_visible():
                    print(f"   Found: {selector}")
                    element.click()
                    time.sleep(2)
                    break
            except:
                pass
        
        # Try clicking calendar navigation to trigger more API calls
        print("\n3. Interacting with calendar...")
        calendar_nav_selectors = [
            '.calendar-next',
            '.next-month',
            '[data-action="next"]',
            '.fc-next-button',
            'button:has-text("Next")',
            '.datepicker-next',
        ]
        
        for selector in calendar_nav_selectors:
            try:
                element = page.locator(selector).first
                if element.is_visible():
                    print(f"   Clicking: {selector}")
                    element.click()
                    time.sleep(1)
                    element.click()  # Click again to trigger another month
                    time.sleep(1)
                    break
            except:
                pass
        
        # Extract any calendar data from the page HTML
        print("\n4. Parsing page for embedded data...")
        html = page.content()
        soup = BeautifulSoup(html, 'lxml')
        
        # Look for inline calendar data
        scripts = soup.find_all('script')
        for script in scripts:
            text = script.string or ''
            
            # Look for JSON data
            json_patterns = [
                (r'availability\s*[=:]\s*(\[[\s\S]*?\]);', 'availability'),
                (r'calendarData\s*[=:]\s*(\{[\s\S]*?\});', 'calendarData'),
                (r'rates\s*[=:]\s*(\[[\s\S]*?\]);', 'rates'),
                (r'"availability"\s*:\s*(\[[\s\S]*?\])', 'availability_json'),
                (r'"blocked"\s*:\s*(\[[\s\S]*?\])', 'blocked_dates'),
                (r'"booked"\s*:\s*(\[[\s\S]*?\])', 'booked_dates'),
            ]
            
            for pattern, name in json_patterns:
                matches = re.findall(pattern, text)
                if matches:
                    print(f"   Found embedded {name} data")
                    try:
                        data = json.loads(matches[0])
                        discovered["calendar_data"].append({
                            "source": "embedded_script",
                            "type": name,
                            "property": property_slug,
                            "data": data,
                        })
                    except:
                        discovered["calendar_data"].append({
                            "source": "embedded_script",
                            "type": name,
                            "property": property_slug,
                            "raw": matches[0][:500],
                        })
        
        # Look for calendar elements with date data
        calendar_elements = soup.select('[data-date], .calendar-day[data-day], .fc-day')
        if calendar_elements:
            print(f"   Found {len(calendar_elements)} calendar day elements")
            dates_data = []
            for el in calendar_elements[:10]:  # Sample first 10
                date_val = el.get('data-date') or el.get('data-day')
                classes = ' '.join(el.get('class', []))
                available = 'available' in classes.lower() or 'booked' not in classes.lower()
                dates_data.append({
                    'date': date_val,
                    'available': available,
                    'classes': classes,
                })
            if dates_data:
                discovered["calendar_data"].append({
                    "source": "html_calendar",
                    "property": property_slug,
                    "dates": dates_data,
                })
        
        # Report discovered API calls
        print(f"\n5. Network requests captured: {len(api_calls)}")
        for call in api_calls:
            print(f"   {call['method']} {call['url'][:70]}...")
            discovered["api_endpoints"].append(call)
        
        browser.close()


def test_common_endpoints():
    """Test common API endpoint patterns."""
    
    print("\n" + "="*70)
    print("TESTING COMMON API ENDPOINTS")
    print("="*70)
    
    endpoints_to_test = [
        "/api/availability",
        "/api/calendar",
        "/api/v1/properties",
        "/api/v1/availability",
        "/wp-json/wp/v2/properties",
        "/wp-json/api/availability",
        "/ical/feed.ics",
        "/calendar/feed.ics",
    ]
    
    with httpx.Client(
        headers={'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'},
        timeout=10.0,
        follow_redirects=True
    ) as client:
        for endpoint in endpoints_to_test:
            url = BASE_URL + endpoint
            try:
                response = client.get(url)
                if response.status_code == 200:
                    print(f"  ✓ {endpoint}")
                    print(f"    Content-Type: {response.headers.get('content-type', 'unknown')}")
                    print(f"    Size: {len(response.content)} bytes")
                    discovered["api_endpoints"].append({
                        "url": url,
                        "status": 200,
                        "content_type": response.headers.get('content-type'),
                    })
                elif response.status_code != 404:
                    print(f"  ? {endpoint} → {response.status_code}")
            except Exception as e:
                print(f"  ✗ {endpoint} → Error: {e}")


def save_results():
    """Save discovered data to files."""
    
    output_dir = Path(__file__).parent.parent / "data"
    output_dir.mkdir(exist_ok=True)
    
    output_file = output_dir / f"booking_discovery_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    
    with open(output_file, 'w') as f:
        json.dump(discovered, f, indent=2, default=str)
    
    print(f"\n✓ Results saved to: {output_file}")
    return output_file


def print_summary():
    """Print summary of discovered data."""
    
    print("\n" + "="*70)
    print("DISCOVERY SUMMARY")
    print("="*70)
    
    print(f"\nAPI Endpoints Found: {len(discovered['api_endpoints'])}")
    unique_endpoints = set()
    for ep in discovered['api_endpoints']:
        url = ep.get('url', '')
        # Normalize URL
        base = re.sub(r'/[a-z0-9-]+$', '/{property}', url)
        unique_endpoints.add(base)
    
    for ep in sorted(unique_endpoints):
        print(f"  • {ep}")
    
    print(f"\niCal URLs Found: {len(discovered['ical_urls'])}")
    for ical in discovered['ical_urls']:
        print(f"  • {ical['url']}")
    
    print(f"\nCalendar Data Captured: {len(discovered['calendar_data'])}")
    for cal in discovered['calendar_data']:
        source = cal.get('source', 'api')
        prop = cal.get('property', 'unknown')
        print(f"  • {source} for {prop}")
    
    # Recommendations
    print("\n" + "-"*70)
    print("RECOMMENDATIONS")
    print("-"*70)
    
    if discovered['ical_urls']:
        print("\n✓ iCal URLs found! Update booking_scraper.py to use these:")
        for ical in discovered['ical_urls']:
            print(f"  ICAL_URLS['{ical['property']}'] = '{ical['url']}'")
    
    if discovered['api_endpoints']:
        api_urls = [ep['url'] for ep in discovered['api_endpoints'] if 'api' in ep.get('url', '').lower()]
        if api_urls:
            print("\n✓ API endpoints found! Add to booking_scraper.py:")
            for url in set(api_urls):
                print(f"  • {url}")
    
    if discovered['calendar_data']:
        print("\n✓ Calendar data structure discovered. Review the JSON output file for format details.")
    
    if not any([discovered['ical_urls'], discovered['api_endpoints'], discovered['calendar_data']]):
        print("\n⚠ No booking APIs discovered. The site may:")
        print("  • Use a third-party booking widget (iframe)")
        print("  • Require authentication for calendar data")
        print("  • Load calendar data only after user interaction")
        print("\nTry manually inspecting the site with browser DevTools.")


def main():
    print("="*70)
    print("BEACH HABITATS BOOKING API DISCOVERY")
    print(f"Started: {datetime.now().isoformat()}")
    print("="*70)
    
    # Test common endpoints first
    test_common_endpoints()
    
    # Discover APIs for test properties
    for prop in TEST_PROPERTIES:
        try:
            discover_property_apis(prop)
        except Exception as e:
            print(f"Error discovering {prop}: {e}")
        time.sleep(2)  # Be polite between requests
    
    # Save results
    output_file = save_results()
    
    # Print summary
    print_summary()
    
    print(f"\n{'='*70}")
    print(f"DISCOVERY COMPLETE")
    print(f"Results: {output_file}")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
