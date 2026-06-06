#!/usr/bin/env python3
"""
test_hsapi_sync.py — Full HSAPI sync pipeline test against demo PMC 1020.

Tests the complete data flow:
  1. Auth → bearer token
  2. ListUnits → property inventory
  3. GetUnitAvailability → calendar for first 5 units
  4. ListReservations → upcoming bookings
  5. GetUnit → full detail for first unit

No DB writes — read-only validation only.

Usage:
  python3 scripts/test_hsapi_sync.py
"""
import asyncio
import base64
import json
import os
from datetime import date, timedelta

import httpx

HSAPI_BASE     = "https://hsapi.escapia.com/dragomanadapter/hsapi"
TOKEN_ENDPOINT = f"{HSAPI_BASE}/auth/token"
END_SYSTEM     = "EscapiaVRS"
API_VERSION    = "10"

# Demo PMC — Hawaii Homes (Escapia test account, safe to query)
DEMO_PMCID     = "1020"


def base_headers(token: str, pmcid: str = DEMO_PMCID) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "x-homeaway-hasp-api-version": API_VERSION,
        "x-homeaway-hasp-api-endsystem": END_SYSTEM,
        "x-homeaway-hasp-api-pmcid": pmcid,
    }


async def get_token(client_id: str, client_secret: str) -> str:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            TOKEN_ENDPOINT,
            headers={"Accept": "application/json", "x-homeaway-hasp-api-version": API_VERSION},
            auth=(client_id, client_secret),
        )
    if resp.status_code != 200:
        raise Exception(f"Token failed: {resp.status_code} {resp.text[:300]}")
    data = resp.json()
    auth_val = data.get("authorizationHeaderValue", "")
    if auth_val.startswith("Bearer "):
        return auth_val[len("Bearer "):]
    raise Exception(f"No token in response: {list(data.keys())}")


async def call(client: httpx.AsyncClient, method: str, token: str, pmcid: str = DEMO_PMCID, **kwargs) -> tuple:
    """Make an HSAPI call, return (status_code, data_or_text)."""
    url = f"{HSAPI_BASE}/{method}"
    resp = await client.get(url, headers=base_headers(token, pmcid), **kwargs)
    try:
        return resp.status_code, resp.json()
    except Exception:
        return resp.status_code, resp.text[:500]


def pp(data, max_items=3):
    """Pretty-print truncated JSON."""
    if isinstance(data, list):
        print(f"    [{len(data)} items]")
        for item in data[:max_items]:
            print(f"      {json.dumps(item, default=str)[:200]}")
        if len(data) > max_items:
            print(f"      ... and {len(data) - max_items} more")
    elif isinstance(data, dict):
        print(f"    {json.dumps(data, default=str)[:400]}")
    else:
        print(f"    {str(data)[:300]}")


async def main():
    print("\n=== HSAPI Full Sync Pipeline Test (Demo PMC 1020) ===\n")

    client_id     = os.getenv("ESCAPIA_CLIENT_ID")     or input("HSAPI Client ID: ").strip()
    client_secret = os.getenv("ESCAPIA_CLIENT_SECRET") or input("HSAPI Client Secret: ").strip()
    pmcid         = os.getenv("ESCAPIA_COID", DEMO_PMCID)

    print(f"\nUsing pmcid: {pmcid} (demo)\n")

    # ── Step 1: Token ──────────────────────────────────────────────────────────
    print("Step 1: Auth...")
    token = await get_token(client_id, client_secret)
    print(f"  ✅ Token: {token[:40]}...\n")

    today = date.today()
    end   = today + timedelta(days=180)

    async with httpx.AsyncClient(timeout=60.0) as client:

        # ── Step 2: ListUnits ──────────────────────────────────────────────────
        print("Step 2: ListUnits...")
        status, data = await call(client, "ListUnits", token, pmcid)
        print(f"  HTTP {status}")
        if status == 200:
            units = data if isinstance(data, list) else data.get("units", data.get("results", []))
            print(f"  ✅ {len(units)} units found")
            pp(units)
            unit_ids = [
                u.get("unitId") or u.get("id") or u.get("nativeUnitID")
                for u in units[:5]
                if u.get("unitId") or u.get("id") or u.get("nativeUnitID")
            ]
        else:
            print(f"  ❌ {data}")
            unit_ids = []

        # ── Step 3: GetUnit (full detail for first unit) ───────────────────────
        if unit_ids:
            uid = unit_ids[0]
            print(f"\nStep 3: GetUnit (nativePMSID={uid})...")
            status, data = await call(
                client, "GetUnit", token, pmcid,
                params={"unitNativePMSID": uid}
            )
            print(f"  HTTP {status}")
            if status == 200:
                name = (data or {}).get("name") or (data or {}).get("unitName") or "?"
                beds = (data or {}).get("bedrooms") or "?"
                city = (data or {}).get("city") or (data or {}).get("address", {}).get("city") or "?"
                print(f"  ✅ {name} — {beds}BR — {city}")
                # Show amenities if present
                amenities = (data or {}).get("amenities") or []
                if amenities:
                    print(f"     Amenities ({len(amenities)}): {', '.join(str(a) for a in amenities[:6])}")
            else:
                print(f"  ❌ {data}")

        # ── Step 4: GetUnitAvailability ────────────────────────────────────────
        if unit_ids:
            uid = unit_ids[0]
            print(f"\nStep 4: GetUnitAvailability (nativePMSID={uid}, next 30 days)...")
            status, data = await call(
                client, "GetUnitAvailability", token, pmcid,
                params={
                    "unitNativePMSID": uid,
                    "startDate": today.strftime("%Y-%m-%d"),
                    "endDate": (today + timedelta(days=30)).strftime("%Y-%m-%d"),
                }
            )
            print(f"  HTTP {status}")
            if status == 200:
                days = data if isinstance(data, list) else data.get("days", data.get("availability", [data]))
                avail = sum(1 for d in days if isinstance(d, dict) and d.get("available", d.get("isAvailable", False)))
                print(f"  ✅ {avail}/{len(days)} days available")
                pp(days, max_items=2)
            else:
                print(f"  ❌ {data}")

        # ── Step 5: ListReservations ───────────────────────────────────────────
        print(f"\nStep 5: ListReservations ({today} → {end})...")
        status, data = await call(
            client, "ListReservations", token, pmcid,
            params={
                "startDate": today.strftime("%Y-%m-%d"),
                "endDate":   end.strftime("%Y-%m-%d"),
            }
        )
        print(f"  HTTP {status}")
        if status == 200:
            reservations = data if isinstance(data, list) else data.get("reservations", data.get("results", []))
            print(f"  ✅ {len(reservations)} reservations found")
            pp(reservations, max_items=3)
        else:
            print(f"  ❌ {data}")

        # ── Step 6: Raw endpoint discovery (if any calls failed) ──────────────
        print(f"\nStep 6: Checking available HSAPI methods...")
        status, data = await call(client, "", token, pmcid)
        print(f"  HTTP {status}")
        if status == 200:
            pp(data, max_items=5)
        else:
            # Try the docs/swagger endpoint
            resp = await client.get(
                "https://hsapi.escapia.com/dragomanadapter/docs",
                headers={"Accept": "text/html"},
            )
            print(f"  Docs page: HTTP {resp.status_code}")

    print("\n=== Done ===\n")
    print("If all steps show ✅ — HSAPI is fully working and ready to wire into EscapiaConnectorV2.")
    print("Next step: update EscapiaConnectorV2 to use HSAPI endpoints + store ESCAPIA_CLIENT_ID/SECRET/COID in Railway.")


if __name__ == "__main__":
    asyncio.run(main())
