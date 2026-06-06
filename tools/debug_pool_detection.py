#!/usr/bin/env python3
"""Quick debug to see pool mentions on Oversee pages."""

import asyncio
import re
from playwright.async_api import async_playwright

async def debug_pool_detection():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        # Test a few Oversee properties
        test_urls = [
            "https://oversee.us/vrp/unit/163_Pond_Cypress_Way-223-15",
            "https://oversee.us/vrp/unit/82_Mystic_Cobalt-338-15",
        ]
        
        for url in test_urls:
            print(f"\n{'='*60}")
            print(f"URL: {url}")
            print(f"{'='*60}")
            
            await page.goto(url, wait_until='domcontentloaded', timeout=30000)
            await asyncio.sleep(2)
            
            text = await page.inner_text('body')
            text_lower = text.lower()
            
            # Find all pool mentions
            pool_mentions = []
            for match in re.finditer(r'.{0,50}pool.{0,50}', text_lower):
                pool_mentions.append(match.group())
            
            print(f"\n📍 Pool mentions found ({len(pool_mentions)}):")
            for mention in pool_mentions[:10]:  # First 10
                mention_clean = mention.replace('\n', ' ').strip()
                print(f"   - \"{mention_clean}\"")
            
            # Check specific patterns
            private_indicators = ['private pool', 'pvt pool', 'heated pool', 'pool heated', 'plunge pool']
            community_indicators = ['community pool', 'camp watercolor', 'watercolor pool', 'beach club pool', 'dragonfly pool', 'frog pool', 'access to pool']
            
            print(f"\n🏊 Private pool indicators:")
            for ind in private_indicators:
                if ind in text_lower:
                    print(f"   ✅ Found: '{ind}'")
            
            print(f"\n🏊 Community pool indicators:")
            for ind in community_indicators:
                if ind in text_lower:
                    print(f"   ✅ Found: '{ind}'")
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(debug_pool_detection())
