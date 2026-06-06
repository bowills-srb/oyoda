#!/usr/bin/env python3
"""
Deep HTML Analysis for Beach Habitats Calendar/Booking Data

Since the API discovery didn't find calendar endpoints, let's analyze
the HTML structure to understand how availability is displayed.
"""

import re
import json
from datetime import datetime
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("Playwright required. Run: pip install playwright && playwright install chromium")
    exit(1)

from bs4 import BeautifulSoup

BASE_URL = "https://www.beachhabitats30a.com"
TEST_PROPERTY = "134-mystic-cobalt"

def deep_analyze_property():
    """Deep analysis of property page HTML for calendar/booking elements."""
    
    url = f"{BASE_URL}/30a-vacation-rentals/{TEST_PROPERTY}"
    print(f"Analyzing: {url}\n")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        # Load page
        page.goto(url, wait_until='networkidle')
        
        # Get full HTML
        html = page.content()
        soup = BeautifulSoup(html, 'lxml')
        
        print("=" * 70)
        print("1. SEARCHING FOR CALENDAR/AVAILABILITY ELEMENTS")
        print("=" * 70)
        
        # Look for calendar-related elements
        calendar_patterns = [
            r'calendar',
            r'availability',
            r'datepicker',
            r'booking',
            r'reserve',
            r'check-in',
            r'checkin',
        ]
        
        for pattern in calendar_patterns:
            # Search in class names
            elements = soup.find_all(class_=re.compile(pattern, re.I))
            if elements:
                print(f"\n  Found {len(elements)} elements with class matching '{pattern}':")
                for el in elements[:3]:
                    print(f"    <{el.name} class='{' '.join(el.get('class', [])[:3])}'>")
                    # Show inner structure
                    inner = el.get_text(strip=True)[:100]
                    if inner:
                        print(f"      Text: {inner}...")
            
            # Search in IDs
            elements = soup.find_all(id=re.compile(pattern, re.I))
            if elements:
                print(f"\n  Found {len(elements)} elements with ID matching '{pattern}':")
                for el in elements[:3]:
                    print(f"    <{el.name} id='{el.get('id')}'>")
        
        print("\n" + "=" * 70)
        print("2. LOOKING FOR IFRAMES (THIRD-PARTY BOOKING WIDGETS)")
        print("=" * 70)
        
        iframes = soup.find_all('iframe')
        if iframes:
            for iframe in iframes:
                src = iframe.get('src', '')
                name = iframe.get('name', '')
                print(f"\n  <iframe src='{src[:80]}' name='{name}'>")
        else:
            print("\n  No iframes found")
        
        print("\n" + "=" * 70)
        print("3. ANALYZING SCRIPTS FOR CALENDAR DATA")
        print("=" * 70)
        
        scripts = soup.find_all('script')
        for i, script in enumerate(scripts):
            src = script.get('src', '')
            text = script.string or ''
            
            # Check external scripts
            if src:
                if any(kw in src.lower() for kw in ['calendar', 'booking', 'availability', 'lodgify', 'cloudbeds', 'guesty']):
                    print(f"\n  External script: {src}")
            
            # Check inline scripts for calendar data
            if text and len(text) > 100:
                # Look for date patterns
                date_patterns = [
                    (r'\d{4}-\d{2}-\d{2}', 'ISO dates'),
                    (r'"date":\s*"[^"]+"', 'date fields'),
                    (r'"start":\s*"[^"]+"', 'start dates'),
                    (r'"end":\s*"[^"]+"', 'end dates'),
                    (r'blocked|booked|unavailable', 'availability status'),
                    (r'minStay|min_stay|minimumStay', 'min stay'),
                    (r'\$\d+|\d+\.\d{2}', 'prices'),
                ]
                
                found = []
                for pattern, name in date_patterns:
                    matches = re.findall(pattern, text, re.I)
                    if matches:
                        found.append(f"{name}: {len(matches)} matches")
                
                if found:
                    print(f"\n  Script {i}: {', '.join(found)}")
                    
                    # If it looks like calendar data, show a sample
                    if 'date' in text.lower() or 'availability' in text.lower():
                        # Try to extract the relevant portion
                        for pattern in [r'availability\s*[=:]\s*\[[\s\S]{0,500}', 
                                       r'calendar\s*[=:]\s*\{[\s\S]{0,500}']:
                            match = re.search(pattern, text, re.I)
                            if match:
                                print(f"    Sample: {match.group()[:300]}...")
        
        print("\n" + "=" * 70)
        print("4. LOOKING FOR BOOKING FORM")
        print("=" * 70)
        
        forms = soup.find_all('form')
        for form in forms:
            action = form.get('action', '')
            form_id = form.get('id', '')
            form_class = ' '.join(form.get('class', []))
            
            if any(kw in (action + form_id + form_class).lower() for kw in ['book', 'reserve', 'inquiry', 'contact', 'availability']):
                print(f"\n  <form action='{action}' id='{form_id}' class='{form_class[:50]}'>")
                
                # Show input fields
                inputs = form.find_all(['input', 'select'])
                for inp in inputs[:10]:
                    inp_name = inp.get('name', '')
                    inp_type = inp.get('type', inp.name)
                    print(f"    <{inp.name} name='{inp_name}' type='{inp_type}'>")
        
        print("\n" + "=" * 70)
        print("5. SEARCHING FOR 'AVAILABILITY' TAB/SECTION")
        print("=" * 70)
        
        # Look for tabs
        tabs = soup.find_all(['a', 'button', 'li'], string=re.compile(r'availability|calendar', re.I))
        for tab in tabs:
            print(f"\n  Found tab: <{tab.name}>{tab.get_text(strip=True)}</{tab.name}>")
            href = tab.get('href', '')
            data_target = tab.get('data-target', '') or tab.get('data-toggle', '')
            if href:
                print(f"    href: {href}")
            if data_target:
                print(f"    data-target: {data_target}")
        
        # Try clicking Availability tab
        print("\n  Attempting to click Availability tab...")
        try:
            page.click('text=Availability', timeout=3000)
            page.wait_for_timeout(2000)
            
            # Get updated HTML
            html_after = page.content()
            soup_after = BeautifulSoup(html_after, 'lxml')
            
            # Look for newly visible calendar
            calendars = soup_after.find_all(class_=re.compile(r'calendar|datepicker', re.I))
            print(f"  After clicking: found {len(calendars)} calendar elements")
            
            for cal in calendars[:2]:
                print(f"\n  Calendar element: <{cal.name} class='{' '.join(cal.get('class', [])[:3])}'>")
                # Look for date cells
                date_cells = cal.find_all(attrs={'data-date': True})
                if date_cells:
                    print(f"    Found {len(date_cells)} date cells")
                    for cell in date_cells[:5]:
                        print(f"      {cell.get('data-date')}: class={cell.get('class', [])}")
                
        except Exception as e:
            print(f"  Could not click Availability tab: {e}")
        
        print("\n" + "=" * 70)
        print("6. EXTRACTING ALL DATA ATTRIBUTES")
        print("=" * 70)
        
        # Find all elements with data- attributes
        data_elements = soup.find_all(attrs=lambda x: x and any(k.startswith('data-') for k in x.keys()))
        
        interesting_data = {}
        for el in data_elements:
            for key, value in el.attrs.items():
                if key.startswith('data-') and value:
                    if any(kw in key.lower() for kw in ['date', 'calendar', 'book', 'price', 'rate', 'avail']):
                        if key not in interesting_data:
                            interesting_data[key] = []
                        interesting_data[key].append(str(value)[:50])
        
        for key, values in interesting_data.items():
            print(f"\n  {key}: {values[:5]}")
        
        browser.close()
        
        print("\n" + "=" * 70)
        print("ANALYSIS COMPLETE")
        print("=" * 70)


if __name__ == "__main__":
    deep_analyze_property()
