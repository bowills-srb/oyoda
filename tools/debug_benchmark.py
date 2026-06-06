#!/usr/bin/env python3
"""Quick debug to see what's in Benchmark's rcItemAvailForm"""

import asyncio
import re
from playwright.async_api import async_playwright

async def debug_benchmark():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        url = "https://www.benchmark30a.com/emerald-coast-vacation-rentals/best-both-worlds"
        print(f"Fetching: {url}\n")
        
        await page.goto(url, wait_until='domcontentloaded', timeout=45000)
        await asyncio.sleep(3)
        
        html = await page.content()
        
        # Find rcItemAvailForm
        rc_match = re.search(r"'rcItemAvailForm'\s*:\s*\[([^\]]*)\]", html, re.DOTALL)
        
        if rc_match:
            content = rc_match.group(1)
            print("=" * 60)
            print("rcItemAvailForm content (first 2000 chars):")
            print("=" * 60)
            print(content[:2000])
            print("\n" + "=" * 60)
            
            # Check what keys exist
            keys_found = re.findall(r"'(\w+)':", content)
            print(f"\nKeys found: {set(keys_found)}")
            
            # Check for avail specifically
            avail_match = re.search(r"'avail'\s*:\s*\[", content)
            print(f"\n'avail' array present: {bool(avail_match)}")
            
            # Check for ajx/pricing
            ajx_match = re.search(r"'ajx'\s*:", content)
            print(f"'ajx' (pricing) present: {bool(ajx_match)}")
        else:
            print("rcItemAvailForm NOT FOUND")
            
            # Try to find any calendar/availability data
            print("\nSearching for alternative patterns...")
            
            patterns = [
                (r"availability", "availability keyword"),
                (r"calendar", "calendar keyword"),
                (r"blocked", "blocked keyword"),
                (r"'avail'", "avail key"),
            ]
            
            for pattern, name in patterns:
                matches = re.findall(pattern, html, re.IGNORECASE)
                if matches:
                    print(f"  Found {len(matches)} occurrences of '{name}'")
        
        await browser.close()

asyncio.run(debug_benchmark())
