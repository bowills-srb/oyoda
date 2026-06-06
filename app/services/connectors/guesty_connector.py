"""
Guesty PMS Connector - Full Implementation

Guesty is popular with professional property managers and has 
excellent API coverage.

API Documentation: https://docs.guesty.com/
Authentication: API Token or OAuth 2.0
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


class GuestyConnectorV2(PMSConnector):
    """
    Enhanced Guesty connector with full API implementation.
    
    Guesty has one of the best APIs in the industry:
    - Rich data model
    - Real-time webhooks
    - Good documentation
    - Supports unified inbox
    
    Usage:
        connector = GuestyConnectorV2(
            company_id=uuid,
            credentials={
                "api_token": "...",
                # Or OAuth:
                "client_id": "...",
                "client_secret": "...",
            }
        )
    """
    
    BASE_URL = "https://api.guesty.com/api/v2"
    OPEN_API_URL = "https://open-api.guesty.com/v1"
    
    @property
    def provider(self) -> PMSProvider:
        return PMSProvider.GUESTY
    
    def __init__(self, company_id: UUID, credentials: Dict[str, str]):
        super().__init__(company_id, credentials)
        self._access_token: Optional[str] = None
        self._token_expires_at: Optional[datetime] = None
    
    async def _get_auth_headers(self) -> Dict[str, str]:
        """Get authentication headers."""
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        
        # Check for direct API token
        if self.credentials.get("api_token"):
            headers["Authorization"] = f"Bearer {self.credentials['api_token']}"
        
        # Check for OAuth
        elif self.credentials.get("client_id") and self.credentials.get("client_secret"):
            token = await self._get_oauth_token()
            headers["Authorization"] = f"Bearer {token}"
        
        return headers
    
    async def _get_oauth_token(self) -> str:
        """Get or refresh OAuth token."""
        if self._access_token and self._token_expires_at:
            if datetime.utcnow() < self._token_expires_at - timedelta(minutes=5):
                return self._access_token
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self.OPEN_API_URL}/oauth2/token",
                data={
                    "grant_type": "client_credentials",
                    "scope": "open-api",
                    "client_id": self.credentials["client_id"],
                    "client_secret": self.credentials["client_secret"],
                },
            )
            
            if response.status_code != 200:
                raise Exception(f"Guesty OAuth failed: {response.text}")
            
            data = response.json()
            self._access_token = data["access_token"]
            self._token_expires_at = datetime.utcnow() + timedelta(
                seconds=data.get("expires_in", 86400)
            )
            
            return self._access_token
    
    async def test_connection(self) -> Tuple[bool, str]:
        """Test the API connection."""
        try:
            headers = await self._get_auth_headers()
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{self.BASE_URL}/listings",
                    headers=headers,
                    params={"limit": 1},
                )
                
                if response.status_code == 200:
                    return True, "Connection successful"
                elif response.status_code == 401:
                    return False, "Authentication failed"
                else:
                    return False, f"API error: {response.status_code}"
                    
        except Exception as e:
            return False, f"Connection error: {str(e)}"
    
    async def fetch_listings(self) -> List[CanonicalListing]:
        """Fetch all listings from Guesty."""
        listings = []
        headers = await self._get_auth_headers()
        skip = 0
        limit = 100
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            while True:
                try:
                    response = await client.get(
                        f"{self.BASE_URL}/listings",
                        headers=headers,
                        params={
                            "skip": skip,
                            "limit": limit,
                            "fields": "address amenities prices bedrooms bathrooms propertyType title nickname active publicDescription",
                        },
                    )
                    
                    if response.status_code != 200:
                        logger.error(f"Guesty listings error: {response.status_code}")
                        break
                    
                    data = response.json()
                    items = data.get("results", [])
                    
                    if not items:
                        break
                    
                    for item in items:
                        try:
                            listing = self._normalize_listing(item)
                            listings.append(listing)
                        except Exception as e:
                            logger.error(f"Error normalizing Guesty listing: {e}")
                    
                    if len(items) < limit:
                        break
                    
                    skip += limit
                    
                except Exception as e:
                    logger.error(f"Error fetching Guesty listings: {e}")
                    break
        
        logger.info(f"Fetched {len(listings)} listings from Guesty")
        return listings
    
    def _normalize_listing(self, data: Dict[str, Any]) -> CanonicalListing:
        """Normalize Guesty listing to canonical schema."""
        address = data.get("address", {})
        amenities = data.get("amenities", [])
        amenities_lower = [str(a).lower() for a in amenities]
        
        # Guesty uses nested structure for coordinates
        lat = address.get("lat", 0.0)
        lng = address.get("lng", 0.0)
        
        return CanonicalListing(
            external_id=data.get("_id", ""),
            pms_provider=PMSProvider.GUESTY,
            company_id=self.company_id,
            
            # Location
            address_line1=address.get("street", ""),
            city=address.get("city", ""),
            state=address.get("state", ""),
            postal_code=address.get("zipcode", ""),
            country=address.get("country", "US"),
            latitude=float(lat) if lat else 0.0,
            longitude=float(lng) if lng else 0.0,
            
            # Property
            property_name=data.get("title", data.get("nickname", "")),
            bedrooms=int(data.get("bedrooms", 0)),
            bathrooms=float(data.get("bathrooms", 0)),
            square_footage=data.get("squareFeet"),
            property_type=data.get("propertyType", "single_family"),
            
            # Amenities
            has_pool="pool" in amenities_lower or "private pool" in amenities_lower,
            pool_heated="heated pool" in amenities_lower,
            has_hot_tub="hot tub" in amenities_lower or "jacuzzi" in amenities_lower,
            pet_friendly="pets allowed" in amenities_lower,
            
            # Status
            is_active=data.get("active", True),
            
            last_synced_at=datetime.utcnow(),
        )
    
    async def fetch_bookings(
        self,
        start_date: date,
        end_date: date,
    ) -> List[CanonicalBooking]:
        """Fetch bookings from Guesty."""
        bookings = []
        headers = await self._get_auth_headers()
        skip = 0
        limit = 100
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            while True:
                try:
                    response = await client.get(
                        f"{self.BASE_URL}/reservations",
                        headers=headers,
                        params={
                            "skip": skip,
                            "limit": limit,
                            "checkIn": {"$gte": start_date.isoformat()},
                            "checkOut": {"$lte": end_date.isoformat()},
                        },
                    )
                    
                    if response.status_code != 200:
                        break
                    
                    data = response.json()
                    items = data.get("results", [])
                    
                    if not items:
                        break
                    
                    for item in items:
                        try:
                            booking = self._normalize_booking(item)
                            bookings.append(booking)
                        except Exception as e:
                            logger.error(f"Error normalizing Guesty booking: {e}")
                    
                    if len(items) < limit:
                        break
                    
                    skip += limit
                    
                except Exception as e:
                    logger.error(f"Error fetching Guesty bookings: {e}")
                    break
        
        return bookings
    
    def _normalize_booking(self, data: Dict[str, Any]) -> CanonicalBooking:
        """Normalize Guesty booking."""
        from uuid import uuid4
        
        check_in = data.get("checkIn", "")
        check_out = data.get("checkOut", "")
        
        if isinstance(check_in, str):
            check_in = date.fromisoformat(check_in[:10])
        if isinstance(check_out, str):
            check_out = date.fromisoformat(check_out[:10])
        
        nights = (check_out - check_in).days if check_in and check_out else 0

        money = data.get("money", {})
        total = float(money.get("totalPaid", money.get("totalPrice", 0)))
        guest = data.get("guest", data.get("primaryGuest", {}))
        if not isinstance(guest, dict):
            guest = {}

        return CanonicalBooking(
            external_id=data.get("_id", ""),
            listing_id=uuid4(),
            company_id=self.company_id,
            
            check_in=check_in,
            check_out=check_out,
            nights=nights,
            
            total_amount=total,
            nightly_rate=total / nights if nights > 0 else 0,
            cleaning_fee=money.get("cleaningFee"),

            guest_count=data.get("guestsCount", 1),
            guest_first_name=guest.get("firstName", data.get("guestFirstName")),
            guest_last_name=guest.get("lastName", data.get("guestLastName")),
            guest_email=guest.get("email", data.get("guestEmail")),
            guest_phone=guest.get("phone", data.get("guestPhone")),
            booking_channel=data.get("source", "direct"),
            status=data.get("status", "confirmed"),

            booked_at=datetime.fromisoformat(data["createdAt"]) if data.get("createdAt") else datetime.utcnow(),
        )
    
    async def fetch_calendar(
        self,
        listing_id: str,
        start_date: date,
        end_date: date,
    ) -> List[CanonicalCalendarDay]:
        """Fetch calendar from Guesty."""
        calendar_days = []
        headers = await self._get_auth_headers()
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.get(
                    f"{self.BASE_URL}/listings/{listing_id}/calendar",
                    headers=headers,
                    params={
                        "from": start_date.isoformat(),
                        "to": end_date.isoformat(),
                    },
                )
                
                if response.status_code == 200:
                    data = response.json()
                    for day_data in data.get("days", []):
                        day = self._normalize_calendar_day(listing_id, day_data)
                        calendar_days.append(day)
                        
            except Exception as e:
                logger.error(f"Error fetching Guesty calendar: {e}")
        
        return calendar_days
    
    def _normalize_calendar_day(
        self,
        listing_id: str,
        data: Dict[str, Any],
    ) -> CanonicalCalendarDay:
        """Normalize Guesty calendar day."""
        from uuid import uuid4
        
        return CanonicalCalendarDay(
            listing_id=uuid4(),
            date=date.fromisoformat(data["date"][:10]),
            is_available=data.get("status") == "available",
            is_blocked=data.get("status") == "blocked",
            nightly_rate=float(data.get("price", 0)),
            minimum_stay=int(data.get("minNights", 1)),
        )
    
    def supports_webhooks(self) -> bool:
        return True
    
    async def register_webhook(
        self,
        callback_url: str,
        events: List[str],
    ) -> Dict[str, Any]:
        """Register webhook for real-time updates."""
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
    
    # =========================================================================
    # Guesty-Specific: Unified Inbox
    # =========================================================================
    
    async def fetch_messages(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        listing_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Fetch guest messages from Guesty's unified inbox.
        
        This is a Guesty-specific feature - they aggregate messages
        from all channels (Airbnb, VRBO, direct, etc.)
        """
        headers = await self._get_auth_headers()
        messages = []
        skip = 0
        limit = 100
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            while True:
                params = {
                    "skip": skip,
                    "limit": limit,
                }
                
                if listing_id:
                    params["listingId"] = listing_id
                
                try:
                    response = await client.get(
                        f"{self.BASE_URL}/inbox",
                        headers=headers,
                        params=params,
                    )
                    
                    if response.status_code != 200:
                        break
                    
                    data = response.json()
                    items = data.get("results", [])
                    
                    if not items:
                        break
                    
                    messages.extend(items)
                    
                    if len(items) < limit:
                        break
                    
                    skip += limit
                    
                except Exception as e:
                    logger.error(f"Error fetching Guesty messages: {e}")
                    break
        
        return messages
