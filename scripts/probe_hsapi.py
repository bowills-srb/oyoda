#!/usr/bin/env python3
"""
probe_hsapi.py — Discover correct HSAPI method names for Beach Habitats pmcid=2403.

The ListUnits endpoint returned 404 — this script tries every known
HSAPI method name variant to find what actually works.
"""
import asyncio
import json
import os
import httpx

# Try multiple base URLs — the token/listPmcs base may differ from data endpoints
BASE_VARIANTS = [
    "https://hsapi.escapia.com/dragomanadapter/hsapi",
    "https://hsapi.escapia.com/hsapi",
    "https://hsapi.escapia.com/api",
    "https://hsapi.escapia.com/dragomanadapter",
    "https://hsapi.escapia.com",
    "https://api.escapia.com/hsapi",
    "https://api.escapia.com/dragomanadapter/hsapi",
]

TOKEN_BASE     = "https://hsapi.escapia.com/dragomanadapter/hsapi"
TOKEN_ENDPOINT = f"{TOKEN_BASE}/auth/token"
API_VERSION    = "10"
END_SYSTEM     = "EscapiaVRS"
BEACH_PMCID    = "2403"  # Beach Habitats 30A — confirmed from listPmcs


def headers(token: str, pmcid: str = BEACH_PMCID) -> dict:
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
            headers={"Accept": "application/json",
                     "x-homeaway-hasp-api-version": API_VERSION},
            auth=(client_id, client_secret),
        )
    data = resp.json()
    auth_val = data.get("authorizationHeaderValue", "")
    if auth_val.startswith("Bearer "):
        return auth_val[len("Bearer "):]
    raise Exception(f"Token failed: {resp.status_code}")


async def probe(client: httpx.AsyncClient, token: str, method: str,
                pmcid: str = BEACH_PMCID, params: dict = None) -> tuple:
    url = f"{HSAPI_BASE}/{method}"
    resp = await client.get(url, headers=headers(token, pmcid), params=params or {})
    try:
        body = resp.json()
        preview = json.dumps(body)[:120] if isinstance(body, (dict, list)) else str(body)[:120]
    except Exception:
        preview = resp.text[:120]
    return resp.status_code, preview


async def main():
    client_id     = os.getenv("ESCAPIA_CLIENT_ID") or input("Client ID: ").strip()
    client_secret = os.getenv("ESCAPIA_CLIENT_SECRET") or input("Client Secret: ").strip()

    print(f"\n=== HSAPI Endpoint Probe — Beach Habitats pmcid={BEACH_PMCID} ===\n")
    token = await get_token(client_id, client_secret)
    print(f"Token: {token[:40]}...\n")

    # Key methods to test
    methods = [
        ("ListUnits",        {}),
        ("listUnits",        {}),
        ("units",            {}),
        ("GetUnits",         {}),
        ("ListPmcs",         {}),   # we know this works — confirms base URL
        ("listPmcs",         {}),
        ("ListReservations", {"startDate": "2026-04-01", "endDate": "2026-07-01"}),
        ("reservations",     {"startDate": "2026-04-01", "endDate": "2026-07-01"}),
        ("",                 {}),
    ]

    async with httpx.AsyncClient(timeout=20.0) as client:
        for base in BASE_VARIANTS:
            print(f"\n--- Base: {base} ---")
            for method, params in methods:
                url = f"{base}/{method}" if method else base
                try:
                    resp = await client.get(
                        url,
                        headers=headers(token, BEACH_PMCID),
                        params=params,
                    )
                    try:
                        body = resp.json()
                        preview = json.dumps(body)[:100]
                    except Exception:
                        preview = resp.text[:100]
                    indicator = "✅" if resp.status_code == 200 else "❌" if resp.status_code == 404 else f"⚠️ {resp.status_code}"
                    print(f"  {indicator}  {method or '(root)':<25} {preview[:90]}")
                except Exception as e:
                    print(f"  ❌  {method or '(root)':<25} ERROR: {e}")

    print("\n=== Done ===")
    print("Look for ✅ lines — those base URLs + methods are working")
    print("The base URL where ListPmcs returns ✅ is the correct one to use for all methods")


if __name__ == "__main__":
    asyncio.run(main())
