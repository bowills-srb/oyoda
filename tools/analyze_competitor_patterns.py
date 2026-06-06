#!/usr/bin/env python3
"""
Competitor Rate/Availability Pattern Analysis

Tests which competitor sites expose scrapeable booking/pricing data
using the same rcItemAvailForm pattern as Beach Habitats.

USAGE:
    python analyze_competitor_patterns.py
"""

import asyncio
import json
import re
from datetime import datetime
from playwright.async_api import async_playwright


COMPETITORS = {
    "beach_habitats": {
        "name": "Beach Habitats (CONTROL)",
        "url": "https://www.beachhabitats30a.com/30a-vacation-rentals/134-mystic-cobalt",
        "expected_pms": "Escapia/Drupal",
    },
    "benchmark": {
        "name": "Benchmark Management", 
        "url": "https://www.benchmark30a.com/emerald-coast-vacation-rentals/best-both-worlds",
        "expected_pms": "Escapia/Rezfusion",
    },
    "oversee": {
        "name": "Oversee",
        "url": "https://oversee.us/vrp/unit/Southern_Tide-2-15",
        "expected_pms": "Track PMS",
    },
    "30a_escapes": {
        "name": "30A Escapes",
        "url": "https://www.30aescapes.com/vacation-rentals/florida/watercolor/4-br/the-lookout-on-30a/",
        "expected_pms": "Unknown",
    },
    "exclusive_30a": {
        "name": "Exclusive 30A",
        "url": "https://www.exclusive30a.com/vacation-rentals/watercolor/happy-go-lucky/",
        "expected_pms": "Unknown",
    },
}


async def analyze_site(page, key: str, config: dict) -> dict:
    """Analyze a single site for scrapeable patterns."""
    
    result = {
        "name": config["name"],
        "url": config["url"],
        "expected_pms": config["expected_pms"],
        "has_rcItemAvailForm": False,
        "avail_data_count": 0,
        "has_pricing_endpoint": False,
        "pricing_endpoint": None,
        "detected_pms": None,
        "can_scrape_availability": False,
        "can_scrape_pricing": False,
        "raw_avail_sample": None,
        "error": None,
    }
    
    print(f"\n{'='*70}")
    print(f"🔍 Analyzing: {config['name']}")
    print(f"   URL: {config['url']}")
    print(f"   Expected PMS: {config['expected_pms']}")
    print(f"{'='*70}")
    
    try:
        # Navigate with longer timeout
        await page.goto(config["url"], wait_until='domcontentloaded', timeout=45000)
        await asyncio.sleep(3)  # Let JS execute
        
        # Get full page HTML
        html = await page.content()
        
        # =================================================================
        # CHECK 1: rcItemAvailForm pattern (Escapia/Drupal)
        # =================================================================
        # Check if rcItemAvailForm exists (single or double quotes)
        has_rc = bool(re.search(r'rcItemAvailForm', html, re.IGNORECASE))
        
        if has_rc:
            result["has_rcItemAvailForm"] = True
            result["detected_pms"] = "Escapia/Drupal"
            print(f"   ✅ Found: rcItemAvailForm pattern!")
            
            # Extract avail array - handle both quote styles
            # Look for "avail":[...] or 'avail':[...]
            avail_match = re.search(r'["\']avail["\']\s*:\s*\[([^\]]+)\]', html, re.DOTALL)
            
            if avail_match:
                avail_content = avail_match.group(1)
                # Count date ranges - look for "b":"2026-02-17" or 'b':'2026-02-17'
                date_ranges = re.findall(r'["\']b["\']\s*:\s*["\'](\d{4}-\d{2}-\d{2})["\']', avail_content)
                
                if date_ranges:
                    result["avail_data_count"] = len(date_ranges)
                    result["can_scrape_availability"] = True
                    print(f"   ✅ Found: {len(date_ranges)} availability date ranges")
                    print(f"      Sample dates: {date_ranges[:3]}...")
                    result["raw_avail_sample"] = avail_content[:300]
                else:
                    print(f"   ⚠️ Found avail array but no date ranges parsed")
            else:
                print(f"   ⚠️ rcItemAvailForm found but no 'avail' array detected")
            
            # Check for pricing AJAX endpoint
            # Look for "ajx":{"url":"/rescms/..."} or 'ajx':{'url':'/rescms/...'}
            ajax_match = re.search(r'["\']ajx["\']\s*:\s*\{[^}]*["\']url["\']\s*:\s*["\']([^"\']+)["\']', html)
            
            if ajax_match:
                endpoint = ajax_match.group(1)
                result["has_pricing_endpoint"] = True
                result["pricing_endpoint"] = endpoint
                result["can_scrape_pricing"] = True
                print(f"   ✅ Found: Pricing endpoint: {endpoint}")
            else:
                print(f"   ⚠️ No pricing endpoint found")
        
        # =================================================================
        # CHECK 2: Rezfusion pattern
        # =================================================================
        if 'rezfusion' in html.lower() or 'images.rezfusion.com' in html:
            if not result["detected_pms"]:
                result["detected_pms"] = "Rezfusion"
            print(f"   🔶 Found: Rezfusion framework")
        
        # =================================================================
        # CHECK 3: Track PMS pattern  
        # =================================================================
        if 'trackhs.com' in html or 'trackPaymentIframe' in html:
            if not result["detected_pms"]:
                result["detected_pms"] = "Track PMS"
            print(f"   🔶 Found: Track PMS (iframe-based)")
            print(f"   ❌ Track PMS uses iframe - not directly scrapeable")
        
        # =================================================================
        # SUMMARY
        # =================================================================
        print(f"\n   📊 RESULT:")
        print(f"      Detected PMS: {result['detected_pms'] or 'Unknown'}")
        print(f"      Can scrape availability: {'✅ YES' if result['can_scrape_availability'] else '❌ NO'}")
        print(f"      Can scrape pricing: {'✅ YES' if result['can_scrape_pricing'] else '❌ NO'}")
        
    except Exception as e:
        result["error"] = str(e)[:100]
        print(f"   ⚠️ Error: {result['error']}")
    
    return result


async def main():
    print("=" * 70)
    print("🔍 COMPETITOR RATE/AVAILABILITY PATTERN ANALYSIS")
    print("=" * 70)
    print("\nGoal: Find which competitors use the same rcItemAvailForm pattern")
    print("      as Beach Habitats for scrapeable booking/pricing data\n")
    
    results = {}
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        )
        page = await context.new_page()
        
        for key, config in COMPETITORS.items():
            results[key] = await analyze_site(page, key, config)
            await asyncio.sleep(2)  # Be respectful
        
        await browser.close()
    
    # =================================================================
    # FINAL SUMMARY
    # =================================================================
    print("\n" + "=" * 70)
    print("📊 FINAL SUMMARY: CAN WE SCRAPE RATES & AVAILABILITY?")
    print("=" * 70)
    
    can_scrape = []
    cannot_scrape = []
    
    for key, r in results.items():
        status_avail = "✅ YES" if r["can_scrape_availability"] else "❌ NO"
        status_price = "✅ YES" if r["can_scrape_pricing"] else "❌ NO"
        
        print(f"\n{r['name']}:")
        print(f"   PMS Detected:  {r['detected_pms'] or 'Unknown'}")
        print(f"   Availability:  {status_avail}")
        print(f"   Pricing:       {status_price}")
        if r["avail_data_count"]:
            print(f"   Date ranges:   {r['avail_data_count']}")
        if r["pricing_endpoint"]:
            print(f"   Price endpoint: {r['pricing_endpoint']}")
        
        if r["can_scrape_availability"] or r["can_scrape_pricing"]:
            can_scrape.append(r["name"])
        else:
            cannot_scrape.append(r["name"])
    
    print("\n" + "=" * 70)
    print("💡 RECOMMENDATIONS")
    print("=" * 70)
    
    if can_scrape:
        print(f"\n✅ CAN SCRAPE (rcItemAvailForm pattern works):")
        for name in can_scrape:
            print(f"   - {name}")
    
    if cannot_scrape:
        print(f"\n❌ CANNOT EASILY SCRAPE (different architecture):")
        for name in cannot_scrape:
            print(f"   - {name}")
    
    # Save detailed results
    output_file = "/tmp/competitor_rate_analysis.json"
    with open(output_file, 'w') as f:
        # Remove raw samples for cleaner output
        clean_results = {k: {kk: vv for kk, vv in v.items() if kk != 'raw_avail_sample'} 
                        for k, v in results.items()}
        json.dump(clean_results, f, indent=2, default=str)
    
    print(f"\n📄 Detailed results saved to {output_file}")
    
    return results


if __name__ == "__main__":
    asyncio.run(main())
