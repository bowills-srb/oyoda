#!/usr/bin/env python3
"""
Quick test script to demo the concierge.

Run this after starting the server:
    uvicorn app.main:app --reload --port 8000

Then run:
    python test_concierge.py
"""

import httpx
import asyncio
from datetime import date, timedelta


BASE_URL = "http://localhost:8000"


async def main():
    async with httpx.AsyncClient(timeout=30.0) as client:
        
        # 1. Create a test session
        print("\n" + "="*60)
        print("Creating test guest session...")
        print("="*60)
        
        check_in = date.today() + timedelta(days=3)
        check_out = date.today() + timedelta(days=7)
        
        response = await client.post(
            f"{BASE_URL}/api/v1/operator/sessions",
            json={
                "reservation_id": "TEST-001",
                "property_code": "SEALAVIE",
                "property_name": "Sea La Vie",
                "guest_first_name": "John",
                "guest_last_name": "Demo",
                "guest_phone": "+15551234567",
                "guest_email": "john@example.com",
                "check_in": check_in.isoformat(),
                "check_out": check_out.isoformat(),
                "num_guests": 4,
                # Property context
                "wifi_network": "SeaLaVie_Guest",
                "wifi_password": "Beach2024!",
                "door_code": "1234",
                "check_in_time": "4:00 PM",
                "check_out_time": "10:00 AM",
                "parking_info": "2 spots in driveway, golf cart in garage",
                "pool_heated": True,
                "beach_access": "WaterColor Beach Club - wristbands in welcome basket",
            }
        )
        
        if response.status_code != 200:
            print(f"Error: {response.status_code}")
            print(response.text)
            return
        
        data = response.json()
        token = data["token"]
        concierge_url = data["concierge_url"]
        
        print(f"\n✅ Session created!")
        print(f"   Token: {token}")
        print(f"   Guest: {data['guest_name']}")
        print(f"   Property: {data['property_name']}")
        print(f"   Check-in: {data['check_in']}")
        print(f"   Check-out: {data['check_out']}")
        print(f"\n🔗 Guest URL: {concierge_url}")
        print(f"\n   Or locally: http://localhost:8000/c/{token}")
        
        # 2. Test the chat endpoint
        print("\n" + "="*60)
        print("Testing chat endpoint...")
        print("="*60)
        
        test_messages = [
            "What's the WiFi password?",
            "Any restaurant recommendations?",
            "Is the pool heated?",
            "Beach chair rentals?",
        ]
        
        for msg in test_messages:
            print(f"\n👤 Guest: {msg}")
            
            response = await client.post(
                f"{BASE_URL}/api/v1/mobile/{token}/chat",
                json={"message": msg, "channel": "mobile"}
            )
            
            if response.status_code == 200:
                data = response.json()
                # Truncate long responses for display
                resp_text = data["response"]
                if len(resp_text) > 200:
                    resp_text = resp_text[:200] + "..."
                print(f"🐚 Coral: {resp_text}")
            else:
                print(f"   Error: {response.status_code}")
        
        # 3. Get journey status
        print("\n" + "="*60)
        print("Journey Status...")
        print("="*60)
        
        response = await client.get(f"{BASE_URL}/api/v1/operator/sessions/{token}/journey")
        if response.status_code == 200:
            data = response.json()
            print(f"\n   Guest: {data.get('guest_name')}")
            print(f"   Days until check-in: {data.get('days_until_checkin')}")
            print(f"   Welcome sent: {data.get('welcome_sent')}")
            print(f"   Discussed: {data.get('discussed', [])}")
            print(f"   Not discussed: {data.get('not_discussed', [])}")
        
        print("\n" + "="*60)
        print("Demo complete!")
        print("="*60)
        print(f"\nOpen this URL in a browser to see the guest interface:")
        print(f"   http://localhost:8000/c/{token}")
        print()


if __name__ == "__main__":
    asyncio.run(main())
