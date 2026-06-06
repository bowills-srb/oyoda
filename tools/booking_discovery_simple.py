#!/usr/bin/env python3
"""
Simple Booking Discovery (No Playwright Required)

This is a lightweight version that uses httpx only.
For full JavaScript rendering, use booking_discovery.py with Playwright.

USAGE:
    cd ~/Downloads/STR-Beach_Habitats
    pip install httpx beautifulsoup4 lxml
    python tools/booking_discovery_simple.py
"""

import httpx
import json
import re
from datetime import datetime
from pathlib import Path
from bs4 import BeautifulSoup

BASE_URL = "https://www.beachhabitats30a.com"

TEST_PROPERTIES = [
    "134-mystic-cobalt",
    "sea-la-vie", 
    "108-silver-laurel-way",
]

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'none',
    'Sec-Fetch-User': '?1',
    'Upgrade-Insecure-Requests': '1',
}

discovered = {
    "api_endpoints": [],
    "ical_urls": [],
    "calendar_data": [],
    "html_analysis": [],
}


def analyze_property_page(client: httpx.Client, slug: str):
    """Analyze a property page for booking/calendar data."""
    
    url = f"{BASE_URL}/30a-vacation-rentals/{slug}"
    print(f"\n{'='*60}")
    print(f"Analyzing: {slug}")
    print(f"URL: {url}")
    
    try:
        response = client.get(url)
        print(f"Status: {response.status_code}")
        
        if response.status_code != 200:
            print(f"  ✗ Failed to fetch page")
            return
        
        html = response.text
        soup = BeautifulSoup(html, 'lxml')
        
        analysis = {
            "property": slug,
            "url": url,
            "findings": [],
        }
        
        # 1. Look for iframes (booking widgets)
        iframes = soup.find_all('iframe')
        for iframe in iframes:
            src = iframe.get('src', '')
            if src:
                analysis["findings"].append(f"iframe: {src[:100]}")
                print(f"  📦 iframe found: {src[:60]}...")
                
                # Common booking widget providers
                if any(provider in src.lower() for provider in [
                    'lodgify', 'guesty', 'hostaway', 'streamline', 
                    'escapia', 'track', 'bookingpal', 'vrbo', 'airbnb'
                ]):
                    print(f"     ⭐ Booking widget detected!")
                    discovered["api_endpoints"].append({
                        "type": "iframe_widget",
                        "url": src,
                        "property": slug,
                    })
        
        # 2. Look for calendar containers
        calendar_selectors = [
            '[class*="calendar"]',
            '[class*="availability"]',
            '[class*="datepicker"]',
            '[data-calendar]',
            '[data-availability]',
        ]
        
        for selector in calendar_selectors:
            elements = soup.select(selector)
            if elements:
                print(f"  📅 Found {len(elements)} elements matching: {selector}")
                for el in elements[:2]:
                    classes = el.get('class', [])
                    el_id = el.get('id', '')
                    analysis["findings"].append(f"calendar_element: {el.name} class={classes} id={el_id}")
        
        # 3. Analyze scripts for embedded data
        scripts = soup.find_all('script')
        for i, script in enumerate(scripts):
            text = script.string or ''
            if len(text) < 50:
                continue
            
            # Look for calendar/booking data patterns
            patterns = [
                (r'availability', 'availability data'),
                (r'calendar\s*[:=]', 'calendar config'),
                (r'blocked[Dd]ates', 'blocked dates'),
                (r'booked[Dd]ates', 'booked dates'),
                (r'pricing|rates', 'pricing data'),
                (r'ical|\.ics', 'iCal reference'),
                (r'/api/', 'API endpoint'),
                (r'lodgify|guesty|hostaway|streamline|escapia', 'PMS provider'),
            ]
            
            found_patterns = []
            for pattern, name in patterns:
                if re.search(pattern, text, re.IGNORECASE):
                    found_patterns.append(name)
            
            if found_patterns:
                print(f"  📜 Script {i}: contains {', '.join(found_patterns)}")
                analysis["findings"].append(f"script_{i}: {', '.join(found_patterns)}")
                
                # Try to extract specific data
                # Look for API URLs
                api_matches = re.findall(r'["\']([^"\']*(?:api|calendar|availability|ical)[^"\']*)["\']', text, re.IGNORECASE)
                for api_url in api_matches[:3]:
                    if api_url.startswith('/') or api_url.startswith('http'):
                        print(f"     API URL: {api_url[:60]}")
                        discovered["api_endpoints"].append({
                            "type": "script_reference",
                            "url": api_url,
                            "property": slug,
                        })
                
                # Look for iCal URLs
                ical_matches = re.findall(r'["\']([^"\']*\.ics[^"\']*)["\']', text)
                for ical_url in ical_matches:
                    print(f"     iCal URL: {ical_url}")
                    discovered["ical_urls"].append({
                        "url": ical_url,
                        "property": slug,
                    })
        
        # 4. Look for booking-related links
        links = soup.find_all('a', href=True)
        for link in links:
            href = link.get('href', '')
            text = link.get_text(strip=True).lower()
            
            if any(kw in href.lower() or kw in text for kw in ['book', 'reserve', 'availability', 'calendar', 'ical']):
                print(f"  🔗 Link: '{link.get_text(strip=True)[:30]}' → {href[:50]}")
                analysis["findings"].append(f"link: {href}")
        
        # 5. Check for common PMS meta tags
        meta_tags = soup.find_all('meta')
        for meta in meta_tags:
            name = meta.get('name', '') + meta.get('property', '')
            content = meta.get('content', '')
            if any(kw in name.lower() + content.lower() for kw in ['booking', 'reservation', 'lodgify', 'guesty']):
                print(f"  🏷️ Meta: {name}={content[:50]}")
                analysis["findings"].append(f"meta: {name}={content}")
        
        discovered["html_analysis"].append(analysis)
        
    except Exception as e:
        print(f"  ✗ Error: {e}")


def test_api_endpoints(client: httpx.Client):
    """Test common API endpoint patterns."""
    
    print("\n" + "="*60)
    print("Testing common API endpoints...")
    print("="*60)
    
    endpoints = [
        "/api/availability",
        "/api/calendar", 
        "/api/v1/properties",
        "/api/v1/availability",
        "/wp-json/wp/v2/posts?categories=properties",
        "/ical/calendar.ics",
        "/feeds/availability.json",
        "/.well-known/availability",
    ]
    
    for endpoint in endpoints:
        url = BASE_URL + endpoint
        try:
            response = client.get(url, follow_redirects=True)
            if response.status_code == 200:
                content_type = response.headers.get('content-type', '')
                print(f"  ✓ {endpoint}")
                print(f"    Content-Type: {content_type}")
                print(f"    Size: {len(response.content)} bytes")
                discovered["api_endpoints"].append({
                    "type": "direct_endpoint",
                    "url": url,
                    "status": 200,
                    "content_type": content_type,
                })
            elif response.status_code not in [404, 403]:
                print(f"  ? {endpoint} → {response.status_code}")
        except Exception as e:
            pass


def main():
    print("="*60)
    print("BEACH HABITATS BOOKING DISCOVERY (Simple Version)")
    print(f"Time: {datetime.now().isoformat()}")
    print("="*60)
    
    with httpx.Client(headers=HEADERS, timeout=30.0, follow_redirects=True) as client:
        
        # Test API endpoints
        test_api_endpoints(client)
        
        # Analyze property pages
        for slug in TEST_PROPERTIES:
            analyze_property_page(client, slug)
    
    # Save results
    output_dir = Path(__file__).parent.parent / "data"
    output_dir.mkdir(exist_ok=True)
    output_file = output_dir / f"booking_discovery_simple_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    
    with open(output_file, 'w') as f:
        json.dump(discovered, f, indent=2)
    
    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    print(f"API Endpoints: {len(discovered['api_endpoints'])}")
    print(f"iCal URLs: {len(discovered['ical_urls'])}")
    print(f"Pages Analyzed: {len(discovered['html_analysis'])}")
    print(f"\nResults saved to: {output_file}")
    
    if discovered["api_endpoints"]:
        print("\nDiscovered endpoints:")
        for ep in discovered["api_endpoints"]:
            print(f"  • [{ep.get('type', 'unknown')}] {ep.get('url', '')[:60]}")
    
    if not discovered["api_endpoints"] and not discovered["ical_urls"]:
        print("\n⚠️  No booking APIs found with simple scraping.")
        print("   The site likely uses JavaScript-rendered calendars.")
        print("   Run booking_discovery.py with Playwright for full analysis.")


if __name__ == "__main__":
    main()
