"""
escapia_enet.py — Escapia ENET SOAP Connector

Built from the EVRNService Postman collection.

Endpoint: https://api.escapia.com/EVRNService.svc
Auth: Username + Password in every SOAP envelope body
      <ns:RequestorID ID="username" MessagePassword="password"/>

PropertyManagerCode: The operator's Escapia company code (e.g. "7090")
UnitCode: PropertyManagerCode-UnitID (e.g. "7090-173738")

Key operations:
  - UnitSearch          — list all properties for operator
  - UnitDescriptiveInfo — property details, amenities, policies
  - UnitCalendarAvail   — availability calendar
  - UnitStay            — pricing for specific dates
  - UnitRead            — read reservation/inquiry by ID
  - UnitInquiry         — submit/read guest inquiries (pre-booking messages)

Usage:
    connector = EscapiaENETConnector(
        username="YourUserName",
        password="YourPassword",
        property_manager_code="7090"
    )
    properties = await connector.get_all_properties()
    calendar   = await connector.get_calendar("7090-173738", "2026-04-01", "2026-06-30")
    inquiries  = await connector.get_recent_inquiries()
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional
from xml.etree import ElementTree as ET

import httpx

logger = logging.getLogger(__name__)

# ENET SOAP endpoints
ENET_ENDPOINT = "https://api.escapia.com/EVRNService.svc"          # Transactions
ENET_CONTENT_ENDPOINT = "https://api.escapia.com/EVRNContentService.svc"  # Bulk content
ENET_NS = "http://www.escapia.com/EVRN/2007/02"

# SOAP envelope template — auth embedded per-request
_ENVELOPE_TMPL = """<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
                  xmlns:ns="{ns}">
  <soapenv:Header/>
  <soapenv:Body>
    {body}
  </soapenv:Body>
</soapenv:Envelope>"""

_POS_TMPL = """<ns:POS>
  <ns:Source>
    <ns:RequestorID ID="{username}" MessagePassword="{password}"/>
  </ns:Source>
</ns:POS>"""


def _envelope(body: str, username: str, password: str) -> str:
    """Wrap a SOAP body in the standard envelope."""
    return _ENVELOPE_TMPL.format(ns=ENET_NS, body=body)


def _pos(username: str, password: str) -> str:
    return _POS_TMPL.format(username=username, password=password)


def _find(el: ET.Element, tag: str, ns: str = ENET_NS) -> Optional[ET.Element]:
    return el.find(f"{{{ns}}}{tag}")


def _findall(el: ET.Element, tag: str, ns: str = ENET_NS) -> List[ET.Element]:
    return el.findall(f"{{{ns}}}{tag}")


def _attr(el: Optional[ET.Element], attr: str, default: str = "") -> str:
    if el is None:
        return default
    return el.get(attr, default)


def _text(el: Optional[ET.Element], default: str = "") -> str:
    if el is None:
        return default
    return (el.text or "").strip() or default


class EscapiaENETError(Exception):
    pass


class EscapiaENETConnector:
    """
    Escapia ENET SOAP connector.

    All methods are async and return Python dicts/lists.
    No ORM dependencies — can be used standalone.
    """

    def __init__(
        self,
        username: str,
        password: str,
        property_manager_code: str,
        timeout: float = 30.0,
    ):
        self.username = username
        self.password = password
        self.pmc = property_manager_code  # PropertyManagerCode e.g. "7090"
        self.timeout = timeout

    # ──────────────────────────────────────────────────────────────────────────
    # Low-level SOAP call
    # ──────────────────────────────────────────────────────────────────────────

    async def _call(
        self,
        soap_action: str,
        body_xml: str,
        endpoint: str = ENET_ENDPOINT,
    ) -> ET.Element:
        """
        Make a SOAP call to the ENET endpoint.
        Returns the parsed XML root element.
        Raises EscapiaENETError on HTTP or SOAP fault.
        """
        envelope = _ENVELOPE_TMPL.format(ns=ENET_NS, body=body_xml)
        headers = {
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": soap_action,
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                endpoint,
                content=envelope.encode("utf-8"),
                headers=headers,
                auth=(self.username, self.password),
            )

        if resp.status_code != 200:
            raise EscapiaENETError(
                f"ENET HTTP {resp.status_code}: {resp.text[:500]}"
            )

        root = ET.fromstring(resp.content)

        # Check for SOAP fault
        fault = root.find(".//{http://schemas.xmlsoap.org/soap/envelope/}Fault")
        if fault is not None:
            faultstring = fault.findtext("faultstring") or "Unknown SOAP fault"
            raise EscapiaENETError(f"SOAP fault: {faultstring}")

        return root

    def _pos_xml(self) -> str:
        return f"""<ns:POS>
    <ns:Source>
      <ns:RequestorID ID="{self.username}" MessagePassword="{self.password}"/>
    </ns:Source>
  </ns:POS>"""

    # ──────────────────────────────────────────────────────────────────────────
    # UnitSearch — get all properties for this operator
    # ──────────────────────────────────────────────────────────────────────────

    async def get_all_properties(self) -> List[Dict[str, Any]]:
        """
        Fetch all active property listings for this operator using
        EVRN_UnitSearchRQ (EVRNService) with ResponseType=PropertyList.
        This returns all units under the authenticated PMC without needing
        individual UnitCodes. No date filtering — returns the full inventory.
        """
        from datetime import date, timedelta
        # UnitSearch requires a StayDateRange — use a near-future window
        # just to satisfy the schema; we only use the PropertyList response.
        start = (date.today() + timedelta(days=1)).strftime("%m/%d/%Y")
        end   = (date.today() + timedelta(days=8)).strftime("%m/%d/%Y")

        body = f"""<ns:EVRN_UnitSearchRQ xmlns:ns="{ENET_NS}"
    EchoToken="list" Target="Production" Version="1.0"
    MaxResponses="500" SortOrder="G" ResponseType="PropertyList">
  {self._pos_xml()}
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

        root = await self._call("UnitSearch", body, endpoint=ENET_ENDPOINT)
        properties = []

        # Escapia response wraps each property in UnitDescriptiveInfo with
        # a nested UnitInfo child. Try UnitInfo first, fall back to scanning
        # for any element that carries a UnitCode attribute.
        unit_els = root.findall(f".//{{{ENET_NS}}}UnitInfo")
        if not unit_els:
            # Some response shapes use UnitDescriptiveInfo directly
            unit_els = root.findall(f".//{{{ENET_NS}}}UnitDescriptiveInfo")

        for unit in unit_els:
            # UnitCode may live on the parent UnitDescriptiveInfo, not UnitInfo
            unit_code = unit.get("UnitCode", "")
            if not unit_code:
                parent = root.find(
                    f".//{{{ENET_NS}}}UnitDescriptiveInfo[@UnitCode]")
                if parent is not None:
                    unit_code = parent.get("UnitCode", "")

            prop = {
                "unit_code": unit_code,
                "property_manager_code": unit.get("PropertyManagerCode", self.pmc),
                "name": unit.get("UnitName", "") or unit.get("UnitHeadline", ""),
                "bedrooms": _safe_int(unit.get("Bedrooms")),
                "bathrooms": _safe_float(unit.get("Bathrooms")),
                "max_occupancy": _safe_int(unit.get("MaxOccupancy")),
                "unit_class": unit.get("UnitClassCode", ""),
                "rating": _safe_float(unit.get("Rating")),
                "is_active": unit.get("Active", "true").lower() == "true",
            }

            if not prop["unit_code"]:
                continue  # skip malformed entries

            # Address
            addr_el = unit.find(f"{{{ENET_NS}}}Address")
            if addr_el is not None:
                prop["address"] = _text(addr_el.find(f"{{{ENET_NS}}}AddressLine"))
                prop["city"] = _text(addr_el.find(f"{{{ENET_NS}}}CityName"))
                prop["state"] = addr_el.findtext(f"{{{ENET_NS}}}StateProv") or ""
                prop["postal_code"] = _text(addr_el.find(f"{{{ENET_NS}}}PostalCode"))

            # Position (lat/lng)
            pos_el = unit.find(f"{{{ENET_NS}}}Position")
            if pos_el is not None:
                prop["latitude"] = _safe_float(pos_el.get("Latitude"))
                prop["longitude"] = _safe_float(pos_el.get("Longitude"))

            properties.append(prop)

        logger.info(f"[ENET] UnitSearch: {len(properties)} properties")
        return properties

    # ──────────────────────────────────────────────────────────────────────────
    # UnitDescriptiveInfo — full property details
    # ──────────────────────────────────────────────────────────────────────────

    async def get_property_details(self, unit_code: str) -> Dict[str, Any]:
        """
        Get full property details: amenities, policies, description, photos.
        unit_code: e.g. "7090-173738"
        """
        body = f"""<ns:EVRN_UnitDescriptiveInfoRQ xmlns:ns="{ENET_NS}"
    Target="Production" Version="1.0">
  {self._pos_xml()}
  <ns:UnitDescriptiveInfos>
    <ns:UnitDescriptiveInfo
        PropertyManagerCode="{self.pmc}"
        UnitCode="{unit_code}">
      <ns:UnitInfo SendData="true"/>
      <ns:Policies SendPolicies="true"/>
      <ns:UnitReviews SendReviews="true"/>
    </ns:UnitDescriptiveInfo>
  </ns:UnitDescriptiveInfos>
</ns:EVRN_UnitDescriptiveInfoRQ>"""

        root = await self._call("UnitDescriptiveInfo", body)
        result: Dict[str, Any] = {"unit_code": unit_code}

        # Unit info
        unit_el = root.find(f".//{{{ENET_NS}}}UnitDescriptiveInfo")
        if unit_el is not None:
            info_el = unit_el.find(f"{{{ENET_NS}}}UnitInfo")
            if info_el is not None:
                result["name"] = info_el.get("UnitName", "")
                result["headline"] = info_el.get("UnitHeadline", "")
                result["bedrooms"] = _safe_int(info_el.get("Bedrooms"))
                result["bathrooms"] = _safe_float(info_el.get("Bathrooms"))
                result["max_occupancy"] = _safe_int(info_el.get("MaxOccupancy"))
                result["sqft"] = _safe_int(info_el.get("SquareFeet"))

                # Amenities
                amenities = []
                for am in info_el.findall(f"{{{ENET_NS}}}UnitAmenity"):
                    code = am.get("Code", "")
                    desc = am.get("Description", "")
                    if desc:
                        amenities.append(desc)
                    elif code:
                        amenities.append(code)
                result["amenities"] = amenities

                # Description text
                for vm in info_el.findall(f".//{{{ENET_NS}}}VendorMessage"):
                    for para in vm.findall(f".//{{{ENET_NS}}}Paragraph"):
                        text_el = para.find(f"{{{ENET_NS}}}Text")
                        if text_el is not None and text_el.text:
                            result.setdefault("description", "")
                            result["description"] += text_el.text.strip() + " "

            # Policies
            pol_el = unit_el.find(f"{{{ENET_NS}}}Policies")
            if pol_el is not None:
                checkin = pol_el.find(f".//{{{ENET_NS}}}CheckInTime")
                checkout = pol_el.find(f".//{{{ENET_NS}}}CheckOutTime")
                if checkin is not None:
                    result["check_in_time"] = checkin.get("Time", "")
                if checkout is not None:
                    result["check_out_time"] = checkout.get("Time", "")

            # Reviews summary
            reviews_el = unit_el.find(f"{{{ENET_NS}}}UnitReviews")
            if reviews_el is not None:
                result["review_count"] = _safe_int(reviews_el.get("Count"))
                result["review_rating"] = _safe_float(reviews_el.get("AverageRating"))

        logger.info(f"[ENET] UnitDescriptiveInfo: {unit_code} → {result.get('name')}")
        return result

    # ──────────────────────────────────────────────────────────────────────────
    # UnitCalendarAvail — availability calendar
    # ──────────────────────────────────────────────────────────────────────────

    async def get_calendar(
        self,
        unit_code: str,
        start: str,  # MM/DD/YYYY or YYYY-MM-DD
        end: str,
    ) -> List[Dict[str, Any]]:
        """
        Get availability calendar for a unit.
        Returns list of {date, available, status} dicts.
        """
        # Normalize date format to MM/DD/YYYY for ENET
        start = _fmt_date_for_enet(start)
        end = _fmt_date_for_enet(end)

        body = f"""<ns:EVRN_UnitCalendarAvailRQ xmlns:ns="{ENET_NS}"
    EchoToken="cal" Target="Production" Version="1.0">
  {self._pos_xml()}
  <ns:UnitRef PropertyManagerCode="{self.pmc}" UnitCode="{unit_code}"/>
  <ns:CalendarDateRange Start="{start}" End="{end}"/>
  <ns:ShowHolds>true</ns:ShowHolds>
</ns:EVRN_UnitCalendarAvailRQ>"""

        root = await self._call("UnitCalendarAvail", body)
        days = []

        for day_el in root.iter(f"{{{ENET_NS}}}CalendarDay"):
            days.append({
                "date": day_el.get("Date", ""),
                "available": day_el.get("AvailabilityStatus", "") == "AvailableForSale",
                "status": day_el.get("AvailabilityStatus", ""),
                "min_stay": _safe_int(day_el.get("MinStay")),
                "rate": _safe_float(day_el.get("Rate")),
                "hold": day_el.get("HoldType", ""),
            })

        logger.info(f"[ENET] Calendar {unit_code}: {len(days)} days")
        return days

    # ──────────────────────────────────────────────────────────────────────────
    # UnitCalendarAvailBatch — fetch availability for ALL units at once
    # ──────────────────────────────────────────────────────────────────────────

    async def get_all_calendars_batch(
        self,
        updated_after: Optional[str] = None,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Fetch availability calendar for ALL units in one SOAP call via
        EVRNContentService (batch endpoint — much faster than 50 serial calls).

        updated_after: ISO timestamp e.g. "2024-01-01T00:00:00" — only returns
                       units with changes since that date. Omit for full refresh.

        Returns dict of {unit_code: [calendar_day, ...]}
        """
        updated_after_str = updated_after or "2020-01-01T00:00:00"

        body = f"""<tns0:EVRN_UnitCalendarAvailBatchRQ xmlns:tns0="{ENET_NS}" Version="1">
  <tns0:POS>
    <tns0:Source>
      <tns0:RequestorID ID="{self.username}" MessagePassword="{self.password}"/>
    </tns0:Source>
  </tns0:POS>
  <tns0:CalenadAvails>
    <tns0:CalendarAvail PropertyManagerCode="{self.pmc}" UpdatedAfter="{updated_after_str}"/>
  </tns0:CalenadAvails>
</tns0:EVRN_UnitCalendarAvailBatchRQ>"""

        root = await self._call(
            "UnitCalendarAvailBatch", body, endpoint=ENET_CONTENT_ENDPOINT
        )

        results: Dict[str, List[Dict[str, Any]]] = {}

        for unit_avail in root.iter(f"{{{ENET_NS}}}UnitCalendarAvail"):
            unit_code = unit_avail.get("UnitCode", "")
            if not unit_code:
                continue
            days = []
            for day_el in unit_avail.iter(f"{{{ENET_NS}}}CalendarDay"):
                days.append({
                    "date": day_el.get("Date", ""),
                    "available": day_el.get("AvailabilityStatus", "") == "AvailableForSale",
                    "status": day_el.get("AvailabilityStatus", ""),
                    "min_stay": _safe_int(day_el.get("MinStay")),
                    "rate": _safe_float(day_el.get("Rate")),
                })
            results[unit_code] = days

        logger.info(f"[ENET] CalendarAvailBatch: {len(results)} units returned")
        return results

    # ──────────────────────────────────────────────────────────────────────────
    # UnitRead — read inquiries/reservations
    # ──────────────────────────────────────────────────────────────────────────

    async def get_inquiry(self, inquiry_id: str) -> Dict[str, Any]:
        """
        Read a specific inquiry/reservation by ID.
        Type 14 = reservation, Type 6 = inquiry
        """
        body = f"""<ns:EVRN_UnitReadRQ xmlns:ns="{ENET_NS}"
    EchoToken="read" Target="Production" Version="1.0">
  {self._pos_xml()}
  <ns:ReadRequests>
    <ns:ReadRequest>
      <ns:UniqueID ID="{inquiry_id}" Type="6"/>
    </ns:ReadRequest>
  </ns:ReadRequests>
</ns:EVRN_UnitReadRQ>"""

        root = await self._call("UnitRead", body)
        return self._parse_inquiry(root)

    # ──────────────────────────────────────────────────────────────────────────
    # UnitInquiry — submit a response to an inquiry
    # ──────────────────────────────────────────────────────────────────────────

    async def submit_inquiry_response(
        self,
        unit_code: str,
        guest_name_first: str,
        guest_name_last: str,
        guest_email: str,
        guest_phone: str,
        message: str,
        check_in: str,
        check_out: str,
        adults: int = 2,
        children: int = 0,
        transaction_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Submit an inquiry response back through Escapia.
        This is used by the pre-booking pipeline to send AI-drafted responses.
        transaction_id: unique string per request (use UUID)
        """
        import uuid as _uuid
        txn_id = transaction_id or str(_uuid.uuid4())
        ts = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
        ci = _fmt_date_for_enet(check_in)
        co = _fmt_date_for_enet(check_out)

        body = f"""<ns:EVRN_UnitInquiryRQ xmlns:ns="{ENET_NS}"
    EchoToken="inquiry" TimeStamp="{ts}"
    Target="Production" Version="1.0"
    TransactionIdentifier="{txn_id}">
  {self._pos_xml()}
  <ns:InquiryRequests>
    <ns:InquiryRequest
        TransactionIdentifier="{txn_id}"
        InquiryDate="{ts}"
        InquiryType="0">
      <ns:UnitRef UnitCode="{unit_code}"/>
      <ns:Contact>
        <ns:Name>
          <ns:GivenName>{guest_name_first}</ns:GivenName>
          <ns:Surname>{guest_name_last}</ns:Surname>
        </ns:Name>
        <ns:Email>{guest_email}</ns:Email>
        <ns:Telephone PhoneNumber="{guest_phone}" FormattedInd="false" DefaultInd="true"/>
      </ns:Contact>
      <ns:Message>{message}</ns:Message>
      <ns:StayDateRange Start="{ci}" End="{co}"/>
      <ns:GuestCounts>
        <ns:GuestCount AgeQualifyingCode="10" Count="{adults}"/>
        <ns:GuestCount AgeQualifyingCode="8" Count="{children}"/>
      </ns:GuestCounts>
    </ns:InquiryRequest>
  </ns:InquiryRequests>
</ns:EVRN_UnitInquiryRQ>"""

        root = await self._call("UnitInquiry", body)
        result: Dict[str, Any] = {"transaction_id": txn_id, "success": False}

        # Parse response
        rs_el = root.find(f".//{{{ENET_NS}}}EVRN_UnitInquiryRS")
        if rs_el is not None:
            success_el = rs_el.find(f"{{{ENET_NS}}}Success")
            result["success"] = success_el is not None
            warn_el = rs_el.find(f".//{{{ENET_NS}}}Warning")
            if warn_el is not None:
                result["warning"] = warn_el.get("ShortText", "")
            err_el = rs_el.find(f".//{{{ENET_NS}}}Error")
            if err_el is not None:
                result["error"] = err_el.get("ShortText", "")
                result["success"] = False

        logger.info(f"[ENET] UnitInquiry: {unit_code} → success={result['success']}")
        return result

    # ──────────────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _parse_inquiry(self, root: ET.Element) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        inq_el = root.find(f".//{{{ENET_NS}}}InquiryRequest")
        if inq_el is None:
            return result

        result["inquiry_id"] = inq_el.get("TransactionIdentifier", "")
        result["inquiry_date"] = inq_el.get("InquiryDate", "")
        result["inquiry_type"] = inq_el.get("InquiryType", "")

        unit_el = inq_el.find(f"{{{ENET_NS}}}UnitRef")
        if unit_el is not None:
            result["unit_code"] = unit_el.get("UnitCode", "")

        contact_el = inq_el.find(f"{{{ENET_NS}}}Contact")
        if contact_el is not None:
            name_el = contact_el.find(f"{{{ENET_NS}}}Name")
            if name_el is not None:
                first = _text(name_el.find(f"{{{ENET_NS}}}GivenName"))
                last = _text(name_el.find(f"{{{ENET_NS}}}Surname"))
                result["guest_name"] = f"{first} {last}".strip()
            email_el = contact_el.find(f"{{{ENET_NS}}}Email")
            result["guest_email"] = _text(email_el)
            phone_el = contact_el.find(f"{{{ENET_NS}}}Telephone")
            if phone_el is not None:
                result["guest_phone"] = phone_el.get("PhoneNumber", "")

        msg_el = inq_el.find(f"{{{ENET_NS}}}Message")
        result["message"] = _text(msg_el)

        stay_el = inq_el.find(f"{{{ENET_NS}}}StayDateRange")
        if stay_el is not None:
            result["check_in"] = stay_el.get("Start", "")
            result["check_out"] = stay_el.get("End", "")

        return result

    # ──────────────────────────────────────────────────────────────────────────
    # Connection test
    # ──────────────────────────────────────────────────────────────────────────

    async def test_connection(self) -> tuple[bool, str]:
        """Test credentials by fetching a minimal unit search."""
        try:
            props = await self.get_all_properties()
            return True, f"Connected — {len(props)} properties found"
        except EscapiaENETError as e:
            return False, str(e)
        except Exception as e:
            return False, f"Connection error: {e}"


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _safe_int(val: Any, default: int = 0) -> int:
    try:
        return int(val) if val is not None else default
    except (ValueError, TypeError):
        return default


def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        return float(val) if val is not None else default
    except (ValueError, TypeError):
        return default


def _fmt_date_for_enet(d: str) -> str:
    """Convert YYYY-MM-DD to MM/DD/YYYY for ENET API."""
    if not d:
        return d
    # Already MM/DD/YYYY
    if re.match(r"\d{2}/\d{2}/\d{4}", d):
        return d
    # Convert from YYYY-MM-DD
    try:
        dt = date.fromisoformat(d[:10])
        return dt.strftime("%m/%d/%Y")
    except ValueError:
        return d


# ──────────────────────────────────────────────────────────────────────────────
# Standalone test script
# ──────────────────────────────────────────────────────────────────────────────

async def _test():
    import os
    username = os.getenv("ESCAPIA_USERNAME") or input("Escapia username: ")
    password = os.getenv("ESCAPIA_PASSWORD") or input("Escapia password: ")
    pmc = os.getenv("ESCAPIA_PMC") or input("PropertyManagerCode (e.g. 7090): ")

    connector = EscapiaENETConnector(username, password, pmc)

    print("\nTesting connection...")
    ok, msg = await connector.test_connection()
    print(f"  {'✅' if ok else '❌'} {msg}")

    if ok:
        print("\nFetching first 3 properties...")
        props = await connector.get_all_properties()
        for p in props[:3]:
            print(f"  {p['unit_code']} — {p['name']} ({p.get('bedrooms', '?')}BR)")

        if props:
            unit_code = props[0]["unit_code"]
            print(f"\nFetching details for {unit_code}...")
            details = await connector.get_property_details(unit_code)
            print(f"  Name: {details.get('name')}")
            print(f"  Amenities ({len(details.get('amenities', []))}): "
                  f"{', '.join(details.get('amenities', [])[:5])}")
            print(f"  Check-in: {details.get('check_in_time')} "
                  f"Check-out: {details.get('check_out_time')}")

            print(f"\nFetching calendar for {unit_code} (next 30 days)...")
            today = date.today()
            cal = await connector.get_calendar(
                unit_code,
                today.strftime("%Y-%m-%d"),
                (today + timedelta(days=30)).strftime("%Y-%m-%d"),
            )
            avail = sum(1 for d in cal if d["available"])
            print(f"  {avail}/{len(cal)} days available in next 30 days")


if __name__ == "__main__":
    asyncio.run(_test())
