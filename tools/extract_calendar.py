#!/usr/bin/env python3
"""
Extract Calendar/Availability Data from Beach Habitats

Based on deep analysis, we found:
- Calendar widget: <div class='rcav-calendar'>
- Script 26 contains 205 ISO dates - this is the availability data!

This script extracts the actual availability data.
"""

import re
import json
from datetime import datetime, date
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import List, Optional, Dict

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("Playwright required. Run: pip install playwright && playwright install chromium")
    exit(1)

from bs4 import BeautifulSoup

BASE_URL = "https://www.beachhabitats30a.com"

@dataclass
class DateAvailability:
    date: str
    available: bool
    price: Optional[float] = None
    min_stay: Optional[int] = None
    check_in_allowed: bool = True
    check_out_allowed: bool = True

@dataclass
class PropertyCalendar:
    property_slug: str
    property_name: str
    dates: List[DateAvailability]
    scraped_at: str


def extract_calendar_data(property_slug: str) -> Optional[PropertyCalendar]:
    """Extract calendar/availability data from a property page."""
    
    url = f"{BASE_URL}/30a-vacation-rentals/{property_slug}"
    print(f"\n{'='*70}")
    print(f"Extracting: {property_slug}")
    print(f"URL: {url}")
    print("="*70)
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        # Load page
        page.goto(url, wait_until='networkidle')
        
        # Get HTML
        html = page.content()
        soup = BeautifulSoup(html, 'lxml')
        
        # Get property name
        title = soup.find('h1')
        property_name = title.get_text(strip=True) if title else property_slug
        print(f"Property: {property_name}")
        
        # Find the calendar container
        calendar_div = soup.find('div', class_=re.compile(r'rcav-calendar'))
        if calendar_div:
            print(f"\n✓ Found calendar widget")
            
            # Extract calendar HTML structure
            tables = calendar_div.find_all('table', class_='rc-calendar')
            print(f"  Found {len(tables)} month tables")
            
            # Look at the first table structure
            if tables:
                first_table = tables[0]
                caption = first_table.find('caption')
                if caption:
                    print(f"  First month: {caption.get_text(strip=True)}")
                
                # Get all date cells
                cells = first_table.find_all('td')
                print(f"  Date cells in first month: {len(cells)}")
                
                # Sample cells to understand structure
                print(f"\n  Sample cells:")
                for cell in cells[:7]:
                    classes = ' '.join(cell.get('class', []))
                    text = cell.get_text(strip=True)
                    data_attrs = {k: v for k, v in cell.attrs.items() if k.startswith('data-')}
                    print(f"    Day {text}: class='{classes}' data={data_attrs}")
        
        # Now find and parse the script with ISO dates
        print(f"\n{'='*70}")
        print("EXTRACTING AVAILABILITY DATA FROM SCRIPTS")
        print("="*70)
        
        scripts = soup.find_all('script')
        availability_data = []
        
        for i, script in enumerate(scripts):
            text = script.string or ''
            if not text:
                continue
            
            # Look for the script with lots of ISO dates
            iso_dates = re.findall(r'\d{4}-\d{2}-\d{2}', text)
            if len(iso_dates) > 50:  # This is likely our availability script
                print(f"\n✓ Found availability script (index {i}) with {len(iso_dates)} dates")
                
                # Try to find the data structure
                # Look for common patterns
                
                # Pattern 1: Array of date objects
                date_objects = re.findall(
                    r'\{[^{}]*"date"\s*:\s*"(\d{4}-\d{2}-\d{2})"[^{}]*\}',
                    text
                )
                if date_objects:
                    print(f"  Found {len(date_objects)} date objects")
                
                # Pattern 2: Drupal/NGT calendar format
                # Look for availability arrays
                avail_match = re.search(
                    r'(availability|blocked|booked|reserved)\s*[=:]\s*(\[[^\]]+\])',
                    text, re.I
                )
                if avail_match:
                    print(f"  Found {avail_match.group(1)} array")
                    try:
                        dates_array = json.loads(avail_match.group(2))
                        print(f"    Contains {len(dates_array)} entries")
                        print(f"    Sample: {dates_array[:3]}")
                    except:
                        pass
                
                # Pattern 3: Look for the actual data structure
                # Extract a larger chunk around the dates
                for match in re.finditer(r'.{0,50}\d{4}-\d{2}-\d{2}.{0,50}', text):
                    sample = match.group()
                    if 'avail' in sample.lower() or 'block' in sample.lower() or 'book' in sample.lower():
                        print(f"\n  Context sample: ...{sample}...")
                        break
                
                # Try to extract the full calendar config
                calendar_config = re.search(
                    r'(rcCalendar|calendar|availability)\s*[=:]\s*(\{[\s\S]{0,2000}?\})\s*[,;]',
                    text, re.I
                )
                if calendar_config:
                    print(f"\n  Found calendar config:")
                    config_str = calendar_config.group(2)
                    print(f"    {config_str[:500]}...")
                
                # Extract all unique dates and their context
                print(f"\n  Unique dates found:")
                unique_dates = sorted(set(iso_dates))
                print(f"    Range: {unique_dates[0]} to {unique_dates[-1]}")
                print(f"    Total unique: {len(unique_dates)}")
                
                # Try to find which dates are blocked/booked
                blocked_pattern = re.search(
                    r'blocked["\']?\s*[=:]\s*\[([^\]]+)\]',
                    text, re.I
                )
                if blocked_pattern:
                    blocked_str = blocked_pattern.group(1)
                    blocked_dates = re.findall(r'\d{4}-\d{2}-\d{2}', blocked_str)
                    print(f"\n  Blocked dates: {len(blocked_dates)}")
                    print(f"    Sample: {blocked_dates[:5]}")
                    
                    # Create availability records
                    for d in unique_dates:
                        availability_data.append(DateAvailability(
                            date=d,
                            available=(d not in blocked_dates),
                        ))
                
                # Look for price data
                price_pattern = re.search(
                    r'(rates?|prices?|pricing)\s*[=:]\s*(\{[^}]+\}|\[[^\]]+\])',
                    text, re.I
                )
                if price_pattern:
                    print(f"\n  Found pricing data: {price_pattern.group(1)}")
                    print(f"    {price_pattern.group(2)[:200]}...")
                
                # Save the raw script for analysis
                script_file = Path(__file__).parent.parent / "data" / f"calendar_script_{property_slug}.js"
                script_file.parent.mkdir(exist_ok=True)
                with open(script_file, 'w') as f:
                    f.write(text)
                print(f"\n  Raw script saved to: {script_file}")
        
        # Also try to get calendar data from the actual calendar cells
        print(f"\n{'='*70}")
        print("PARSING CALENDAR CELLS")
        print("="*70)
        
        if calendar_div:
            all_cells = calendar_div.find_all('td')
            
            # Analyze cell classes to understand availability markers
            class_counts = {}
            for cell in all_cells:
                for cls in cell.get('class', []):
                    class_counts[cls] = class_counts.get(cls, 0) + 1
            
            print(f"\nCell class frequency:")
            for cls, count in sorted(class_counts.items(), key=lambda x: -x[1])[:15]:
                print(f"  {cls}: {count}")
            
            # Look for patterns that indicate booked/available
            # Common patterns: 'booked', 'blocked', 'unavailable', 'available', 'open'
            booked_classes = ['booked', 'blocked', 'unavailable', 'reserved', 'occupied']
            available_classes = ['available', 'open', 'free']
            
            booked_count = 0
            available_count = 0
            
            for cell in all_cells:
                classes = ' '.join(cell.get('class', [])).lower()
                if any(bc in classes for bc in booked_classes):
                    booked_count += 1
                elif any(ac in classes for ac in available_classes):
                    available_count += 1
            
            print(f"\nAvailability from cell classes:")
            print(f"  Booked cells: {booked_count}")
            print(f"  Available cells: {available_count}")
        
        browser.close()
        
        # Create result
        if availability_data:
            return PropertyCalendar(
                property_slug=property_slug,
                property_name=property_name,
                dates=availability_data,
                scraped_at=datetime.now().isoformat()
            )
        
        return None


def main():
    # Test properties
    test_properties = [
        "134-mystic-cobalt",
    ]
    
    print("=" * 70)
    print("BEACH HABITATS CALENDAR EXTRACTION")
    print("=" * 70)
    
    results = []
    
    for prop in test_properties:
        try:
            calendar = extract_calendar_data(prop)
            if calendar:
                results.append(calendar)
                print(f"\n✓ Extracted {len(calendar.dates)} dates for {prop}")
        except Exception as e:
            print(f"\n✗ Error extracting {prop}: {e}")
            import traceback
            traceback.print_exc()
    
    # Save results
    if results:
        output_file = Path(__file__).parent.parent / "data" / "calendar_extraction_results.json"
        with open(output_file, 'w') as f:
            json.dump([asdict(r) for r in results], f, indent=2)
        print(f"\n\nResults saved to: {output_file}")
    
    print("\n" + "=" * 70)
    print("EXTRACTION COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
