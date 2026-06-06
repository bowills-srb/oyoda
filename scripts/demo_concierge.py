#!/usr/bin/env python3
"""
Beach Habitats Concierge Demo Script

This script demonstrates the guest concierge system for the property owner.
Run this to see how guests will experience the concierge.

Usage:
    python scripts/demo_concierge.py

Prerequisites:
    1. Database running: docker-compose up -d postgres redis
    2. Run migrations: alembic upgrade head
    3. Set environment variables in .env (or export them):
       - TWILIO_ACCOUNT_SID
       - TWILIO_AUTH_TOKEN
       - TWILIO_PHONE_NUMBER
"""

import asyncio
import sys
from datetime import date, timedelta
from uuid import uuid4

# Add project root to path
sys.path.insert(0, ".")

from app.db.session import SessionLocal
from app.services.concierge.db_session_service import get_db_session_service, DEFAULT_TENANT_ID
from app.services.operator.stay_journey_service import (
    ACTIVITY_PROVIDERS,
    get_activity_info_text,
    get_extend_stay_offer_text,
    get_pool_heat_info_text,
    get_welcome_message_text,
)


async def demo_welcome_messages():
    """Show welcome messages for different scenarios."""
    print("\n" + "="*60)
    print("DEMO: Welcome Messages")
    print("="*60)
    
    # Peak season booking 60 days out
    print("\n📅 Scenario 1: Peak season (July), 60 days out")
    print("-" * 40)
    msg = get_welcome_message_text(
        guest_name="Sarah",
        property_name="Sea La Vie",
        check_in=date.today() + timedelta(days=60),
        check_out=date.today() + timedelta(days=67),
    )
    print(msg)
    
    # Off-season booking
    print("\n\n📅 Scenario 2: Off season (February), 14 days out")
    print("-" * 40)
    msg = get_welcome_message_text(
        guest_name="Mike",
        property_name="Coastal Dreams",
        check_in=date(2026, 2, 15),
        check_out=date(2026, 2, 22),
    )
    print(msg)


async def demo_activity_info():
    """Show activity provider recommendations."""
    print("\n" + "="*60)
    print("DEMO: Activity Recommendations")
    print("="*60)
    
    activities_to_demo = ["beach_chairs", "fishing", "golf"]
    
    for activity in activities_to_demo:
        print(f"\n🏖️ Activity: {activity.upper()}")
        print("-" * 40)
        info = get_activity_info_text(activity, date(2026, 7, 15))  # Peak season
        print(info)


async def demo_extend_stay():
    """Show extend stay offer."""
    print("\n" + "="*60)
    print("DEMO: Extend Stay Offer")
    print("="*60)
    
    msg = get_extend_stay_offer_text(
        guest_name="Jennifer",
        property_name="Sunset Paradise",
        check_out=date.today() + timedelta(days=1),
    )
    print("\n📨 Extend Stay Offer (sent day before checkout if no next guest):")
    print("-" * 40)
    print(msg)


async def demo_pool_heat():
    """Show pool heat info."""
    print("\n" + "="*60)
    print("DEMO: Pool Heat Info")
    print("="*60)
    
    info = get_pool_heat_info_text()
    print("\n🏊 Pool Heat ($50/day):")
    print("-" * 40)
    print(info)


async def demo_db_session():
    """Demo database session creation."""
    print("\n" + "="*60)
    print("DEMO: Database Session Management")
    print("="*60)
    
    try:
        async with SessionLocal() as db:
            service = get_db_session_service(DEFAULT_TENANT_ID)
            
            # Create a test session
            print("\n📝 Creating test session...")
            session = await service.create_session(
                db=db,
                property_id=None,  # Would be real UUID in production
                property_code="sea-la-vie",
                property_name="Sea La Vie",
                guest_name="Demo Guest",
                guest_phone="+15551234567",
                guest_email="demo@example.com",
                check_in=date.today() + timedelta(days=7),
                check_out=date.today() + timedelta(days=14),
                num_guests=4,
                property_context={
                    "has_pool": True,
                    "pool_heated": True,
                    "beach_access": "Community beach with wristbands",
                    "wifi_network": "SeaLaVie-Guest",
                    "wifi_password": "beach2026",
                },
            )
            
            print(f"✅ Session created!")
            print(f"   Token: {session.token}")
            print(f"   Guest: {session.guest_name}")
            print(f"   Property: {session.property_name}")
            print(f"   Check-in: {session.check_in}")
            print(f"   Check-out: {session.check_out}")
            print(f"   Phase: {session.phase}")
            print(f"\n🔗 Concierge URL: http://localhost:8000/c/{session.token}")
            
            # Get journey
            journey = await service.get_journey(db, session.session_id)
            if journey:
                print(f"\n📊 Journey created with {len(journey.activities)} activities to track")
                for act in journey.activities:
                    print(f"   - {act.activity_type}: {act.status}")
            
            # Check extend stay eligibility
            eligibility = await service.check_extend_stay_eligible(db, session.session_id)
            print(f"\n🎁 Extend stay eligible: {eligibility.get('eligible', False)}")
            
    except Exception as e:
        print(f"\n⚠️  Database not available: {e}")
        print("   Run: docker-compose up -d postgres")
        print("   Then: alembic upgrade head")


async def show_provider_list():
    """Show all local providers."""
    print("\n" + "="*60)
    print("LOCAL PROVIDER DATABASE")
    print("="*60)
    
    for activity_type, providers in ACTIVITY_PROVIDERS.items():
        print(f"\n📍 {activity_type.upper().replace('_', ' ')}")
        print("-" * 40)
        for p in providers:
            print(f"   {p['name']}")
            print(f"      {p['desc'][:60]}...")
            if p.get('phone'):
                print(f"      📞 {p['phone']}")
            print(f"      Book {p.get('booking_lead_days', 'N/A')} days ahead")
            print()


async def main():
    """Run all demos."""
    print("\n" + "🏖️"*30)
    print("\n   BEACH HABITATS GUEST CONCIERGE DEMO")
    print("   ===================================")
    print("\n   This shows what guests will experience")
    print("\n" + "🏖️"*30)
    
    await demo_welcome_messages()
    await demo_activity_info()
    await demo_extend_stay()
    await demo_pool_heat()
    await show_provider_list()
    await demo_db_session()
    
    print("\n" + "="*60)
    print("NEXT STEPS")
    print("="*60)
    print("""
1. Run the server:
   uvicorn app.main:app --reload

2. Create a test session via API:
   POST http://localhost:8000/api/v1/operator/sessions
   
3. Open the guest concierge:
   http://localhost:8000/c/{token}

4. Try asking:
   - "What's the WiFi password?"
   - "I need beach chairs"
   - "Restaurant recommendations"
   - "Can I heat the pool?"
   - "What are beach conditions?"

5. To send real SMS, configure .env:
   TWILIO_ACCOUNT_SID=your_sid
   TWILIO_AUTH_TOKEN=your_token
   TWILIO_PHONE_NUMBER=+15551234567
""")


if __name__ == "__main__":
    asyncio.run(main())
