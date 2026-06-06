#!/usr/bin/env python3
"""
Quick test of guest concierge service.
Run: python services/test_concierge.py
"""

import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.guest_concierge_service import GuestConciergeService

def main():
    service = GuestConciergeService()
    
    # Test properties
    test_properties = ["134MC", "111VW", "HMS", "90MC"]
    
    print("=" * 70)
    print("GUEST CONCIERGE SERVICE TEST")
    print("=" * 70)
    
    for prop_code in test_properties:
        print(f"\n{'='*70}")
        print(f"Property: {prop_code}")
        print("=" * 70)
        
        context = service.get_guest_context(prop_code)
        
        print(f"\n📍 {context.property_name}")
        print(f"   {context.bedrooms}BR / {context.bathrooms}BA" + 
              (f" / Sleeps {context.sleeps}" if context.sleeps else ""))
        
        if context.has_active_booking:
            print(f"\n📅 Active Booking:")
            print(f"   Check-in:  {context.check_in_date} at {context.check_in_time}")
            print(f"   Check-out: {context.check_out_date} at {context.check_out_time}")
            print(f"   Nights:    {context.nights_total}")
            print(f"   Progress:  Day {context.nights_elapsed + 1} of {context.nights_total}")
            
            if context.is_arrival_day:
                print("   🎉 ARRIVAL DAY!")
            elif context.is_departure_day:
                print("   👋 DEPARTURE DAY!")
        else:
            print("\n   No active booking")
        
        print(f"\n🏠 Amenities:")
        if context.has_pool:
            pool_desc = "heated pool" if context.pool_heated else "pool"
            print(f"   ✓ {pool_desc.capitalize()}")
        if context.has_hot_tub:
            print(f"   ✓ Hot tub")
        if context.has_bikes:
            print(f"   ✓ {context.bike_count} bikes")
        if context.has_beach_gear:
            print(f"   ✓ Beach gear")
        if context.has_grill:
            print(f"   ✓ Grill")
        if context.has_washer_dryer:
            print(f"   ✓ Washer/dryer")
        if context.pets_allowed:
            print(f"   ✓ Pet-friendly")
        
        if not any([context.has_pool, context.has_hot_tub, context.has_bikes, 
                    context.has_beach_gear, context.has_grill]):
            print("   (standard amenities)")
        
        if context.wifi_network:
            print(f"\n📶 WiFi:")
            print(f"   Network: {context.wifi_network}")
            print(f"   Password: {context.wifi_password}")
        
        if context.property_guide_url:
            print(f"\n📖 Guide: {context.property_guide_url}")
        
        print(f"\n📝 LLM Context Prompt:")
        print("-" * 40)
        llm_prompt = service.format_context_for_llm(context)
        print(llm_prompt)
    
    # Show today's arrivals
    print(f"\n{'='*70}")
    print("TODAY'S ARRIVALS")
    print("=" * 70)
    
    arrivals = service.get_arrivals()
    if arrivals:
        for arr in arrivals[:10]:
            name = arr.get('property_name', 'Unknown')
            if ' - ' in str(name):
                name = name.split(' - ')[0]
            print(f"   {arr['property_code']}: {name} ({arr['nights']} nights)")
    else:
        print("   No arrivals today")
    
    print(f"\n{'='*70}")
    print("TODAY'S DEPARTURES")
    print("=" * 70)
    
    departures = service.get_departures()
    if departures:
        for dep in departures[:10]:
            name = dep.get('property_name', 'Unknown')
            if ' - ' in str(name):
                name = name.split(' - ')[0]
            print(f"   {dep['property_code']}: {name}")
    else:
        print("   No departures today")


if __name__ == "__main__":
    main()
