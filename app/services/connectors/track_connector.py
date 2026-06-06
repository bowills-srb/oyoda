"""
Track PMS Connector (TrackHS)

Track is very popular with 30A and Gulf Coast operators.
Known for strong owner portal and trust accounting.

API Documentation: https://www.trackhs.com/api-documentation
Authentication: API Key
"""

import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

import httpx

from app.services.connectors.pms_connectors import (
    PMSConnector,
    PMSProvider,
    CanonicalListing,
    CanonicalBooking,
    CanonicalCalendarDay,
)

logger = logging.getLogger(__name__)


class TrackConnector(PMSConnector):
    """
    Track PMS connector.
    
    Track is particularly popular in:
    - 30A, Florida
    - Gulf Shores, Alabama
    - Destin, Florida
    - Orange Beach, Alabama
    
    Usage:
        connector = TrackConnector(
            company_id=uuid,
            credentials={
                "api_key": "...",
                "company_code": "...",  # Track company identifier
            }
        )
    """
    
    BASE_URL = "https://api.trackhs.com/v1"
    
    @property
    def provider(self) -> PMSProvider:
        return PMSProvider.TRACK
    
    async def _get_auth_headers(self) -> Dict[str, str]:
        """Get authentication headers."""
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-API-Key": self.credentials.get("api_key", ""),
            "X-Company-Code": self.credentials.get("company_code", ""),
        }
    
    async def test_connection(self) -> Tuple[bool, str]:
        """Test the API connection."""
        try:
            headers = await self._get_auth_headers()
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{self.BASE_URL}/properties",
                    headers=headers,
                    params={"limit": 1},
                )
                
                if response.status_code == 200:
                    return True, "Connection successful"
                elif response.status_code == 401:
                    return False, "Authentication failed - check API key"
                elif response.status_code == 403:
                    return False, "Access denied - check company code"
                else:
                    return False, f"API error: {response.status_code}"
                    
        except Exception as e:
            return False, f"Connection error: {str(e)}"
    
    async def fetch_listings(self) -> List[CanonicalListing]:
        """Fetch all properties from Track."""
        listings = []
        headers = await self._get_auth_headers()
        page = 1
        limit = 50
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            while True:
                try:
                    response = await client.get(
                        f"{self.BASE_URL}/properties",
                        headers=headers,
                        params={
                            "page": page,
                            "per_page": limit,
                            "include": "amenities,address,rates",
                        },
                    )
                    
                    if response.status_code != 200:
                        logger.error(f"Track listings error: {response.status_code}")
                        break
                    
                    data = response.json()
                    items = data.get("data", data.get("properties", []))
                    
                    if not items:
                        break
                    
                    for item in items:
                        try:
                            listing = self._normalize_listing(item)
                            listings.append(listing)
                        except Exception as e:
                            logger.error(f"Error normalizing Track listing: {e}")
                    
                    # Check pagination
                    meta = data.get("meta", {})
                    if page >= meta.get("total_pages", 1):
                        break
                    
                    page += 1
                    
                except Exception as e:
                    logger.error(f"Error fetching Track listings: {e}")
                    break
        
        logger.info(f"Fetched {len(listings)} listings from Track")
        return listings
    
    def _normalize_listing(self, data: Dict[str, Any]) -> CanonicalListing:
        """Normalize Track property to canonical schema."""
        # Track has a flat address structure
        address = data.get("address", {})
        if isinstance(address, str):
            address = {"street": address}
        
        # Track stores amenities as an array of objects
        amenities_raw = data.get("amenities", [])
        amenities = []
        for a in amenities_raw:
            if isinstance(a, dict):
                amenities.append(a.get("name", "").lower())
            else:
                amenities.append(str(a).lower())
        
        # Get coordinates
        lat = data.get("latitude", data.get("lat", 0.0))
        lng = data.get("longitude", data.get("lng", data.get("lon", 0.0)))
        
        return CanonicalListing(
            external_id=str(data.get("id", data.get("property_id", ""))),
            pms_provider=PMSProvider.TRACK,
            company_id=self.company_id,
            
            # Location
            address_line1=address.get("street", address.get("address1", "")),
            address_line2=address.get("unit", address.get("address2", "")),
            city=address.get("city", data.get("city", "")),
            state=address.get("state", data.get("state", "")),
            postal_code=address.get("zip", address.get("postal_code", data.get("zip", ""))),
            country=address.get("country", "US"),
            latitude=float(lat) if lat else 0.0,
            longitude=float(lng) if lng else 0.0,
            
            # Property - Track uses "name" for property name
            property_name=data.get("name", data.get("property_name", "")),
            bedrooms=int(data.get("bedrooms", data.get("num_bedrooms", 0))),
            bathrooms=float(data.get("bathrooms", data.get("num_bathrooms", 0))),
            square_footage=data.get("square_feet", data.get("sqft")),
            property_type=self._map_property_type(data.get("property_type", "")),
            
            # Amenities
            has_pool=any(x in amenities for x in ["pool", "private pool", "swimming pool", "community pool"]),
            pool_heated=any(x in amenities for x in ["heated pool", "pool heat"]),
            has_hot_tub=any(x in amenities for x in ["hot tub", "jacuzzi", "spa"]),
            has_waterfront=any(x in amenities for x in ["gulf front", "beach front", "waterfront", "oceanfront"]),
            waterfront_type=self._detect_waterfront_type(amenities),
            beach_access=self._detect_beach_access(amenities),
            pet_friendly=any(x in amenities for x in ["pet friendly", "pets allowed", "dogs allowed"]),
            has_garage=any(x in amenities for x in ["garage", "carport"]),
            has_ev_charger=any(x in amenities for x in ["ev charger", "electric vehicle charging"]),
            has_game_room=any(x in amenities for x in ["game room", "games"]),
            has_home_theater=any(x in amenities for x in ["home theater", "media room", "theatre"]),
            
            # Status
            is_active=data.get("active", data.get("status") == "active"),
            listing_status=data.get("status", "active"),
            
            last_synced_at=datetime.utcnow(),
        )
    
    def _map_property_type(self, ptype: str) -> str:
        """Map Track property type."""
        ptype_lower = ptype.lower()
        mapping = {
            "house": "single_family",
            "condo": "condo",
            "townhouse": "townhouse",
            "cottage": "cottage",
        }
        for key, value in mapping.items():
            if key in ptype_lower:
                return value
        return "single_family"
    
    def _detect_waterfront_type(self, amenities: List[str]) -> Optional[str]:
        """Detect waterfront type."""
        if any("gulf" in a for a in amenities):
            return "gulf"
        if any("ocean" in a for a in amenities):
            return "ocean"
        if any("bay" in a for a in amenities):
            return "bay"
        if any("lake" in a for a in amenities):
            return "lake"
        return None
    
    def _detect_beach_access(self, amenities: List[str]) -> Optional[str]:
        """Detect beach access."""
        if any("private beach" in a for a in amenities):
            return "private"
        if any("beach" in a for a in amenities):
            return "public"
        return None
    
    async def fetch_bookings(
        self,
        start_date: date,
        end_date: date,
    ) -> List[CanonicalBooking]:
        """Fetch reservations from Track."""
        bookings = []
        headers = await self._get_auth_headers()
        page = 1
        limit = 50
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            while True:
                try:
                    response = await client.get(
                        f"{self.BASE_URL}/reservations",
                        headers=headers,
                        params={
                            "page": page,
                            "per_page": limit,
                            "arrival_from": start_date.isoformat(),
                            "arrival_to": end_date.isoformat(),
                        },
                    )
                    
                    if response.status_code != 200:
                        break
                    
                    data = response.json()
                    items = data.get("data", data.get("reservations", []))
                    
                    if not items:
                        break
                    
                    for item in items:
                        try:
                            booking = self._normalize_booking(item)
                            bookings.append(booking)
                        except Exception as e:
                            logger.error(f"Error normalizing Track booking: {e}")
                    
                    meta = data.get("meta", {})
                    if page >= meta.get("total_pages", 1):
                        break
                    
                    page += 1
                    
                except Exception as e:
                    logger.error(f"Error fetching Track bookings: {e}")
                    break
        
        return bookings
    
    def _normalize_booking(self, data: Dict[str, Any]) -> CanonicalBooking:
        """Normalize Track reservation."""
        from uuid import uuid4
        
        arrival = data.get("arrival_date", data.get("check_in", ""))
        departure = data.get("departure_date", data.get("check_out", ""))
        
        if isinstance(arrival, str):
            arrival = date.fromisoformat(arrival[:10])
        if isinstance(departure, str):
            departure = date.fromisoformat(departure[:10])
        
        nights = (departure - arrival).days if arrival and departure else 0
        
        # Track has detailed financial breakdown
        financials = data.get("financials", {})
        total = float(financials.get("total", data.get("total_amount", 0)))
        guest = data.get("guest", data.get("primary_guest", {}))
        if not isinstance(guest, dict):
            guest = {}

        return CanonicalBooking(
            external_id=str(data.get("id", data.get("reservation_id", ""))),
            listing_id=uuid4(),
            company_id=self.company_id,
            
            check_in=arrival,
            check_out=departure,
            nights=nights,
            
            total_amount=total,
            nightly_rate=total / nights if nights > 0 else 0,
            cleaning_fee=financials.get("cleaning_fee", data.get("cleaning_fee")),
            taxes=financials.get("taxes", data.get("taxes")),

            guest_count=data.get("num_guests", data.get("adults", 1)),
            guest_first_name=guest.get("first_name", data.get("guest_first_name")),
            guest_last_name=guest.get("last_name", data.get("guest_last_name")),
            guest_email=guest.get("email", data.get("guest_email")),
            guest_phone=guest.get("phone", data.get("guest_phone")),
            booking_channel=data.get("source", data.get("booking_source", "direct")),
            status=data.get("status", "confirmed"),

            booked_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.utcnow(),
        )
    
    async def fetch_calendar(
        self,
        listing_id: str,
        start_date: date,
        end_date: date,
    ) -> List[CanonicalCalendarDay]:
        """Fetch availability from Track."""
        calendar_days = []
        headers = await self._get_auth_headers()
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.get(
                    f"{self.BASE_URL}/properties/{listing_id}/availability",
                    headers=headers,
                    params={
                        "start_date": start_date.isoformat(),
                        "end_date": end_date.isoformat(),
                    },
                )
                
                if response.status_code == 200:
                    data = response.json()
                    for day_data in data.get("availability", data.get("days", [])):
                        day = self._normalize_calendar_day(listing_id, day_data)
                        calendar_days.append(day)
                        
            except Exception as e:
                logger.error(f"Error fetching Track calendar: {e}")
        
        return calendar_days
    
    def _normalize_calendar_day(
        self,
        listing_id: str,
        data: Dict[str, Any],
    ) -> CanonicalCalendarDay:
        """Normalize Track calendar day."""
        from uuid import uuid4
        
        day_date = data.get("date")
        if isinstance(day_date, str):
            day_date = date.fromisoformat(day_date[:10])
        
        return CanonicalCalendarDay(
            listing_id=uuid4(),
            date=day_date,
            is_available=data.get("available", not data.get("booked", False)),
            is_blocked=data.get("blocked", False),
            block_reason=data.get("block_reason"),
            nightly_rate=float(data.get("rate", data.get("nightly_rate", 0))),
            minimum_stay=int(data.get("min_stay", data.get("minimum_nights", 1))),
        )
    
    def supports_webhooks(self) -> bool:
        """Track supports webhooks."""
        return True
    
    async def register_webhook(
        self,
        callback_url: str,
        events: List[str],
    ) -> Dict[str, Any]:
        """Register webhook."""
        headers = await self._get_auth_headers()
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self.BASE_URL}/webhooks",
                headers=headers,
                json={
                    "url": callback_url,
                    "events": events,
                },
            )
            
            if response.status_code in (200, 201):
                return response.json()
            else:
                raise Exception(f"Failed to register webhook: {response.text}")
