#!/usr/bin/env python3
"""
Test Beach Habitats Internal API and Analyze Discovery Results

Based on discovery, we found:
- /ngt/ajax/map-bubble/{property_id} - Internal API for property data

Let's test these endpoints and look for calendar/availability data.
"""

import httpx
import json
from pathlib import Path

BASE_URL = "https://www.beachhabitats30a.com"

# Property IDs discovered from the map-bubble calls
# 134-mystic-cobalt → 67
# sea-la-vie → 216  
# 108-silver-laurel-way → 222
PROPERTY_IDS = {
    "134-mystic-cobalt": 67,
    "sea-la-vie": 216,
    "108-silver-laurel-way": 222,
}

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
    'Accept': 'application/json, text/html, */*',
    'Accept-Language': 'en-US,en;q=0.9',
    'X-Requested-With': 'XMLHttpRequest',  # Indicate AJAX request
}

def analyze_discovery_results():
    """Analyze the discovery JSON file."""
    discovery_file = Path(__file__).parent.parent / "data" / "booking_discovery_20260215_131531.json"
    
    if not discovery_file.exists():
        print("Discovery file not found")
        return
    
    with open(discovery_file) as f:
        data = json.load(f)
    
    print("=" * 70)
    print("CALENDAR DATA CAPTURED")
    print("=" * 70)
    
    for i, cal in enumerate(data.get('calendar_data', [])):
        print(f"\n--- Entry {i+1}: {cal.get('property', 'unknown')} ---")
        if 'url' in cal:
            print(f"URL: {cal['url'][:80]}...")
        if 'data' in cal:
            d = cal['data']
            print(f"Data: {json.dumps(d, indent=2)[:500]}...")


def test_internal_api():
    """Test the Beach Habitats internal API endpoints."""
    
    print("\n" + "=" * 70)
    print("TESTING BEACH HABITATS INTERNAL API")
    print("=" * 70)
    
    with httpx.Client(headers=HEADERS, timeout=30.0, follow_redirects=True) as client:
        
        # Test map-bubble endpoint
        for slug, prop_id in PROPERTY_IDS.items():
            url = f"{BASE_URL}/ngt/ajax/map-bubble/{prop_id}"
            print(f"\n--- {slug} (ID: {prop_id}) ---")
            print(f"URL: {url}")
            
            try:
                response = client.get(url)
                print(f"Status: {response.status_code}")
                print(f"Content-Type: {response.headers.get('content-type', 'unknown')}")
                
                if response.status_code == 200:
                    content = response.text
                    print(f"Response length: {len(content)} chars")
                    print(f"Preview: {content[:500]}...")
                    
                    # Try to parse as JSON
                    try:
                        data = response.json()
                        print(f"JSON keys: {list(data.keys()) if isinstance(data, dict) else 'list'}")
                    except:
                        print("(Not JSON - likely HTML)")
            except Exception as e:
                print(f"Error: {e}")
        
        # Try other potential API endpoints
        print("\n" + "=" * 70)
        print("TESTING OTHER POTENTIAL ENDPOINTS")
        print("=" * 70)
        
        test_endpoints = [
            "/ngt/ajax/calendar/67",
            "/ngt/ajax/availability/67",
            "/ngt/ajax/rates/67",
            "/api/properties",
            "/api/availability",
            "/api/calendar",
            "/sites/default/files/ical/67.ics",
            "/ical/67.ics",
            "/calendar.ics",
            "/feed/ical",
        ]
        
        for endpoint in test_endpoints:
            url = BASE_URL + endpoint
            try:
                response = client.get(url)
                if response.status_code == 200:
                    print(f"✓ {endpoint}")
                    print(f"  Content-Type: {response.headers.get('content-type', 'unknown')}")
                    print(f"  Size: {len(response.content)} bytes")
                    print(f"  Preview: {response.text[:200]}...")
                elif response.status_code not in [404, 403]:
                    print(f"? {endpoint} → {response.status_code}")
            except:
                pass


def main():
    print("=" * 70)
    print("BEACH HABITATS API TESTING")
    print("=" * 70)
    
    # First analyze discovery results
    analyze_discovery_results()
    
    # Then test internal APIs
    test_internal_api()


if __name__ == "__main__":
    main()
