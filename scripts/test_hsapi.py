#!/usr/bin/env python3
"""
test_hsapi.py — Test HSAPI credentials and discover your COID.

Usage:
  python3 scripts/test_hsapi.py

Will prompt for HSAPI client_id and client_secret.
Step 1: Gets a bearer token
Step 2: Calls listPmcs to find your COID
Step 3: Lists your properties using that COID
"""
import asyncio
import base64
import os
import sys
import json

import httpx

HSAPI_BASE    = "https://hsapi.escapia.com/dragomanadapter/hsapi"
TOKEN_ENDPOINT = f"{HSAPI_BASE}/auth/token"
LIST_PMCS      = f"{HSAPI_BASE}/ListPmcs"
LIST_UNITS     = f"{HSAPI_BASE}/ListUnits"


async def get_token(client_id: str, client_secret: str) -> str:
    """Exchange client_id + client_secret for a bearer token."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            TOKEN_ENDPOINT,
            headers={
                "Accept": "application/json",
                "x-homeaway-hasp-api-version": "10",
            },
            auth=(client_id, client_secret),  # standard HTTP Basic Auth
        )

    print(f"  Token request: HTTP {resp.status_code}")
    if resp.status_code != 200:
        print(f"  Response: {resp.text[:500]}")
        raise Exception(f"Token request failed: {resp.status_code}")

    data = resp.json()
    # HSAPI returns {"authorizationHeaderValue": "Bearer MzYy..."}
    # The full header value is ready to use — extract just the token part
    auth_val = data.get("authorizationHeaderValue", "")
    if auth_val.startswith("Bearer "):
        token = auth_val[len("Bearer "):]
        print(f"  ✅ Token acquired: {auth_val[:60]}...")
        return token
    # Fallbacks
    token = data.get("encodedId") or data.get("token") or data.get("access_token")
    if not token:
        print(f"  Token response: {json.dumps(data, indent=2)[:500]}")
        raise Exception("Could not find token in response")
    return token


async def list_pmcs(token: str) -> list:
    """List all PMCs this partner has access to — returns COID."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            LIST_PMCS,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "x-homeaway-hasp-api-version": "10",
                "x-homeaway-hasp-api-endsystem": "EscapiaVRS",
            },
        )

    print(f"  listPmcs: HTTP {resp.status_code}")
    if resp.status_code != 200:
        print(f"  Response: {resp.text[:500]}")
        return []

    try:
        data = resp.json()
        print(f"  Raw response: {json.dumps(data, indent=2)[:1000]}")
        # pmcs may be nested — try common shapes
        pmcs = data if isinstance(data, list) else data.get("pmcs", data.get("results", [data]))
        return pmcs
    except Exception:
        print(f"  Raw text: {resp.text[:500]}")
        return []


async def list_units(token: str, coid: str) -> list:
    """List all units for a given COID."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            LIST_UNITS,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "x-homeaway-hasp-api-version": "10",
                "x-homeaway-hasp-api-endsystem": "EscapiaVRS",
                "x-homeaway-hasp-api-pmcid": str(coid),
            },
        )

    print(f"  listUnits (pmcid={coid}): HTTP {resp.status_code}")
    if resp.status_code != 200:
        print(f"  Response: {resp.text[:500]}")
        return []

    try:
        data = resp.json()
        units = data if isinstance(data, list) else data.get("units", data.get("results", []))
        return units
    except Exception:
        print(f"  Raw text: {resp.text[:500]}")
        return []


async def main():
    print("\n=== Escapia HSAPI Connection Test ===\n")

    client_id     = os.getenv("ESCAPIA_CLIENT_ID")     or input("HSAPI Client ID: ").strip()
    client_secret = os.getenv("ESCAPIA_CLIENT_SECRET") or input("HSAPI Client Secret: ").strip()

    # ── Step 1: Get token ──────────────────────────────────────────────────────
    print("\nStep 1: Getting bearer token...")
    try:
        token = await get_token(client_id, client_secret)
        print(f"  ✅ Token acquired: {token[:40]}...")
    except Exception as e:
        print(f"  ❌ Failed: {e}")
        return

    # ── Step 2: List PMCs → get COID ──────────────────────────────────────────
    print("\nStep 2: Listing PMCs (to find your COID)...")
    pmcs = await list_pmcs(token)
    if pmcs:
        print(f"\n  Found {len(pmcs)} PMC(s):")
        coid = None
        for pmc in pmcs:
            # pmcid is the numeric COID used in x-homeaway-hasp-api-pmcid header
            pmc_id   = pmc.get("pmcid") or pmc.get("pmcId") or pmc.get("id") or "?"
            pmc_name = pmc.get("name") or pmc.get("pmcName") or ""
            end_sys  = pmc.get("endSystem", "")
            print(f"    pmcid: {pmc_id}  endSystem: {end_sys}  name: {pmc_name}")
            if coid is None:
                coid = str(pmc_id)  # use first PMC's numeric pmcid
    else:
        print("  No PMCs returned — may need operator to enable HSAPI access")
        coid = input("\nEnter COID manually if you have it (or press Enter to skip): ").strip() or None

    # ── Step 3: List units ─────────────────────────────────────────────────────
    if coid:
        print(f"\nStep 3: Listing units for pmcid={coid}...")
        units = await list_units(token, coid)
        if units:
            print(f"  ✅ {len(units)} units found")
            for u in units[:5]:
                uid  = u.get("unitId") or u.get("id") or "?"
                name = u.get("name") or u.get("unitName") or ""
                print(f"    {uid} — {name}")
            if len(units) > 5:
                print(f"    ... and {len(units) - 5} more")
        else:
            print("  No units returned")

    print("\n=== Done ===")
    if coid:
        print(f"\nAdd to .env and Railway:")
        print(f"  ESCAPIA_CLIENT_ID     = {client_id}")
        print(f"  ESCAPIA_CLIENT_SECRET = {client_secret}")
        print(f"  ESCAPIA_COID          = {coid}")


if __name__ == "__main__":
    asyncio.run(main())
