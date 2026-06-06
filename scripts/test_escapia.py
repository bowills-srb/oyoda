#!/usr/bin/env python3
"""
test_escapia.py — Test ENET credentials and dump response structure.

Usage:
  python3 scripts/test_escapia.py

Picks up ESCAPIA_USERNAME, ESCAPIA_PASSWORD, ESCAPIA_PMC from environment/.env
"""
import asyncio
import sys
import os
import importlib.util
from xml.etree import ElementTree as ET

import httpx

# Direct import — bypasses connectors/__init__ to avoid ORM dependencies
_enet_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "app", "services", "connectors", "escapia_enet.py")
_spec = importlib.util.spec_from_file_location("escapia_enet", _enet_path)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
EscapiaENETConnector = _mod.EscapiaENETConnector

ENET_NS = "http://www.escapia.com/EVRN/2007/02"
CONTENT_ENDPOINT = "https://api.escapia.com/EVRNContentService.svc"


def show_tree(el, indent=0, max_depth=3):
    """Print XML tree structure to find the right element names."""
    if indent > max_depth:
        return
    tag = el.tag.split('}')[-1] if '}' in el.tag else el.tag
    attrs = dict(list(el.items())[:5])
    print("  " + "  " * indent + f"<{tag}> {attrs}")
    children = list(el)
    for child in children[:6]:
        show_tree(child, indent + 1, max_depth)
    if len(children) > 6:
        print("  " + "  " * (indent + 1) + f"... ({len(children) - 6} more children)")


async def main():
    print("\n=== Escapia ENET Connection Test ===\n")

    username = os.getenv("ESCAPIA_USERNAME") or input("ENET Username (ID): ").strip()
    password = os.getenv("ESCAPIA_PASSWORD") or input("ENET Password: ").strip()
    pmc      = os.getenv("ESCAPIA_PMC")      or input("PropertyManagerCode (e.g. BHTTHA): ").strip()

    connector = EscapiaENETConnector(username, password, pmc)

    print(f"Connecting to Escapia ENET...")
    print(f"  Username: {username}")
    print(f"  PMC:      {pmc}\n")

    # ── Test 1: Raw response dump ──────────────────────────────────────────────
    print("Test 1: Raw XML structure from EVRNContentService (UnitDescriptiveInfo)...")

    from datetime import date, timedelta
    start = (date.today() + timedelta(days=1)).strftime("%m/%d/%Y")
    end   = (date.today() + timedelta(days=8)).strftime("%m/%d/%Y")

    body = f"""<ns:EVRN_UnitSearchRQ xmlns:ns="{ENET_NS}"
    EchoToken="list" Target="Production" Version="1.0"
    MaxResponses="500" SortOrder="G" ResponseType="PropertyList">
  <ns:POS>
    <ns:Source>
      <ns:RequestorID ID="{username}" MessagePassword="{password}"/>
    </ns:Source>
  </ns:POS>
  <ns:Criteria AvailableOnlyIndicator="false">
    <ns:Criterion>
      <ns:Region><ns:CountryCode>US</ns:CountryCode></ns:Region>
      <ns:UnitStayCandidate>
        <ns:GuestCounts><ns:GuestCount Count="1"/></ns:GuestCounts>
      </ns:UnitStayCandidate>
      <ns:StayDateRange Start="{start}" End="{end}"/>
    </ns:Criterion>
  </ns:Criteria>
</ns:EVRN_UnitSearchRQ>"""

    envelope = f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
                  xmlns:ns="{ENET_NS}">
  <soapenv:Header/>
  <soapenv:Body>{body}</soapenv:Body>
</soapenv:Envelope>"""

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://api.escapia.com/EVRNService.svc",
                content=envelope.encode("utf-8"),
                headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": "UnitSearch"},
                auth=(username, password),
            )

        print(f"  HTTP {resp.status_code}")
        root = ET.fromstring(resp.content)

        print("\n  Response XML tree:")
        body_el = root.find("{http://schemas.xmlsoap.org/soap/envelope/}Body")
        show_tree(body_el or root)

        # Count how many of each EVRN element exist
        print("\n  Element counts in response:")
        counts = {}
        for el in root.iter():
            tag = el.tag.split('}')[-1] if '}' in el.tag else el.tag
            counts[tag] = counts.get(tag, 0) + 1
        for tag, count in sorted(counts.items(), key=lambda x: -x[1])[:15]:
            print(f"    {tag}: {count}")

    except Exception as e:
        import traceback
        print(f"  ❌ Raw request failed: {e}")
        traceback.print_exc()

    # ── Test 2: get_all_properties() ──────────────────────────────────────────
    print("\nTest 2: get_all_properties() via connector...")
    try:
        props = await connector.get_all_properties()
        print(f"  ✅ {len(props)} properties returned")
        for p in props[:5]:
            print(f"     {p.get('unit_code', '?')} — {p.get('name', 'unnamed')} "
                  f"({p.get('bedrooms', '?')}BR, {p.get('city', '')})")
        if len(props) > 5:
            print(f"     ... and {len(props) - 5} more")
    except Exception as e:
        print(f"  ❌ Failed: {e}")
        props = []

    # ── Test 3: Calendar for first property ───────────────────────────────────
    if props:
        unit_code = props[0].get("unit_code", "")
        if unit_code:
            from datetime import date, timedelta
            print(f"\nTest 3: Calendar for {unit_code} (next 30 days)...")
            try:
                today = date.today()
                cal = await connector.get_calendar(
                    unit_code,
                    today.strftime("%Y-%m-%d"),
                    (today + timedelta(days=30)).strftime("%Y-%m-%d"),
                )
                avail = sum(1 for d in cal if d["available"])
                print(f"  ✅ {avail}/{len(cal)} days available")
            except Exception as e:
                print(f"  ❌ Failed: {e}")

    print("\n=== Done ===\n")
    if props:
        print("SUCCESS — set these in Railway and .env:")
        print(f"  ESCAPIA_USERNAME = {username}")
        print(f"  ESCAPIA_PMC      = {pmc}")
    elif 'resp' in dir() and resp.status_code == 200:
        print("NOTE: Auth succeeded (HTTP 200) but 0 properties parsed.")
        print("The XML tree above shows the actual element structure — share it here to fix the parser.")


if __name__ == "__main__":
    asyncio.run(main())
