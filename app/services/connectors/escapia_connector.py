"""
Escapia PMS Connector - Full Implementation

Escapia (owned by Vrbo/Expedia) is the most common PMS for 30A operators.

API Documentation: https://developer.vrbo.com/
Authentication: OAuth 2.0 or API Key

This connector:
1. Fetches all property data
2. Maps to canonical schema
3. Handles pagination
4. Supports webhooks for real-time updates
"""

import asyncio
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


class EscapiaConnectorV2(PMSConnector):
    """
    Enhanced Escapia connector with full API implementation.
    
    Supports both:
    - Escapia Classic API (username/password)
    - Vrbo Connectivity Partner API (OAuth)
    
    Usage:
        connector = EscapiaConnectorV2(
            company_id=uuid,
            credentials={
                "api_key": "...",  # Or username/password
                "account_id": "..."
            }
        )
        
        # Test connection
        success, msg = await connector.test_connection()
        
        # Fetch properties
        listings = await connector.fetch_listings()
    """
    
    # API endpoints
    BASE_URL = "https://api.escapia.com/v1"
    OAUTH_URL = "https://api.vrbo.com/oauth/token"
    
    # Vrbo Partner API (newer)
    PARTNER_BASE_URL = "https://api.vrbo.com/v1"
    
    @property
    def provider(self) -> PMSProvider:
        return PMSProvider.ESCAPIA
    
    def __init__(self, company_id: UUID, credentials: Dict[str, str]):
        super().__init__(company_id, credentials)
        self._access_token: Optional[str] = None
        self._token_expires_at: Optional[datetime] = None
    
    async def _get_auth_headers(self) -> Dict[str, str]:
        """Get authentication headers, refreshing token if needed."""
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        
        # Check for OAuth credentials
        if self.credentials.get("client_id") and self.credentials.get("client_secret"):
            token = await self._get_oauth_token()
            headers["Authorization"] = f"Bearer {token}"
        
        # Check for API key
        elif self.credentials.get("api_key"):
            headers["Authorization"] = f"Bearer {self.credentials['api_key']}"
        
        # Fall back to basic auth
        elif self.credentials.get("username") and self.credentials.get("password"):
            import base64
            auth = base64.b64encode(
                f"{self.credentials['username']}:{self.credentials['password']}".encode()
            ).decode()
            headers["Authorization"] = f"Basic {auth}"
        
        return headers
    
    async def _get_oauth_token(self) -> str:
        """Get or refresh OAuth token."""
        # Check if we have a valid token
        if self._access_token and self._token_expires_at:
            if datetime.utcnow() < self._token_expires_at - timedelta(minutes=5):
                return self._access_token
        
        # Request new token
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                self.OAUTH_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.credentials["client_id"],
                    "client_secret": self.credentials["client_secret"],
                },
            )
            
            if response.status_code != 200:
                raise Exception(f"OAuth token request failed: {response.text}")
            
            data = response.json()
            self._access_token = data["access_token"]
            self._token_expires_at = datetime.utcnow() + timedelta(
                seconds=data.get("expires_in", 3600)
            )
            
            return self._access_token
    
    async def test_connection(self) -> Tuple[bool, str]:
        """Test the API connection."""
        try:
            headers = await self._get_auth_headers()
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Try to fetch account info or first page of listings
                response = await client.get(
                    f"{self.BASE_URL}/listings",
                    headers=headers,
                    params={"limit": 1},
                )
                
                if response.status_code == 200:
                    return True, "Connection successful"
                elif response.status_code == 401:
                    return False, "Authentication failed - check credentials"
                elif response.status_code == 403:
                    return False, "Access denied - check API permissions"
                else:
                    return False, f"API error: {response.status_code} - {response.text[:200]}"
                    
        except httpx.TimeoutException:
            return False, "Connection timeout - check network"
        except Exception as e:
            return False, f"Connection error: {str(e)}"
    
    async def fetch_listings(self) -> List[CanonicalListing]:
        """
        Fetch all listings from Escapia.
        
        Handles pagination automatically.
        """
        listings = []
        headers = await self._get_auth_headers()
        offset = 0
        limit = 50
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            while True:
                try:
                    response = await client.get(
                        f"{self.BASE_URL}/listings",
                        headers=headers,
                        params={
                            "offset": offset,
                            "limit": limit,
                            "include": "address,amenities,photos,rates",
                        },
                    )
                    
                    if response.status_code != 200:
                        logger.error(f"Escapia listings error: {response.status_code}")
                        break
                    
                    data = response.json()
                    items = data.get("results", data.get("listings", data.get("data", [])))
                    
                    if not items:
                        break
                    
                    for item in items:
                        try:
                            listing = self._normalize_listing(item)
                            listings.append(listing)
                        except Exception as e:
                            logger.error(f"Error normalizing listing {item.get('id')}: {e}")
                    
                    # Check for more pages
                    if len(items) < limit:
                        break
                    
                    offset += limit
                    
                except Exception as e:
                    logger.error(f"Error fetching listings: {e}")
                    break
        
        logger.info(f"Fetched {len(listings)} listings from Escapia")
        return listings
    
    def _normalize_listing(self, data: Dict[str, Any]) -> CanonicalListing:
        """Normalize Escapia listing to canonical schema."""
        # Extract address
        address = data.get("address", {})
        if isinstance(address, str):
            # Sometimes address is just a string
            address = {"street": address}
        
        # Extract coordinates
        location = data.get("location", data.get("geo", {}))
        lat = location.get("latitude", location.get("lat", 0.0))
        lng = location.get("longitude", location.get("lng", location.get("lon", 0.0)))
        
        # Extract amenities
        amenities = data.get("amenities", [])
        if isinstance(amenities, dict):
            # Sometimes amenities is a dict of {name: bool}
            amenities = [k for k, v in amenities.items() if v]
        amenities_lower = [str(a).lower() for a in amenities]
        
        # Extract photos
        photos = data.get("photos", data.get("images", []))
        if isinstance(photos, list) and photos:
            if isinstance(photos[0], str):
                photos = [{"url": p} for p in photos]
        
        # Build canonical listing
        return CanonicalListing(
            external_id=str(data.get("id", data.get("listing_id", ""))),
            pms_provider=PMSProvider.ESCAPIA,
            company_id=self.company_id,
            provider_account_id=str(
                self.credentials.get("provider_account_id")
                or self.credentials.get("account_id")
                or self.credentials.get("pmcid")
                or ""
            ) or None,
            provider_property_id=str(data.get("id", data.get("listing_id", "")) or "") or None,
            provider_unit_id=str(
                data.get("unit_code")
                or data.get("property_code")
                or data.get("unit_id")
                or data.get("code")
                or ""
            ) or None,
            provider_listing_id=str(data.get("listing_id", data.get("id", "")) or "") or None,
            provider_base_url=str(
                self.credentials.get("provider_base_url")
                or self.credentials.get("base_url")
                or self.BASE_URL
            ) or None,
            
            # Location
            address_line1=address.get("street", address.get("line1", "")),
            address_line2=address.get("line2", address.get("unit", "")),
            city=address.get("city", ""),
            state=address.get("state", address.get("region", "")),
            postal_code=address.get("postal_code", address.get("zip", "")),
            country=address.get("country", "US"),
            latitude=float(lat) if lat else 0.0,
            longitude=float(lng) if lng else 0.0,
            
            # Property details
            property_name=data.get("name", data.get("title", "")),
            bedrooms=int(data.get("bedrooms", 0)),
            bathrooms=float(data.get("bathrooms", 0)),
            square_footage=data.get("square_feet", data.get("sqft")),
            property_type=self._map_property_type(data.get("property_type", "")),
            
            # Amenities
            has_pool=any(x in amenities_lower for x in ["pool", "private pool", "swimming pool"]),
            pool_heated=any(x in amenities_lower for x in ["heated pool", "pool heating"]),
            has_hot_tub=any(x in amenities_lower for x in ["hot tub", "jacuzzi", "spa"]),
            has_waterfront=any(x in amenities_lower for x in ["waterfront", "beachfront", "oceanfront", "gulf front"]),
            waterfront_type=self._detect_waterfront_type(amenities_lower),
            beach_access=self._detect_beach_access(amenities_lower),
            pet_friendly=any(x in amenities_lower for x in ["pets", "pet friendly", "pets allowed", "dog friendly"]),
            has_garage=any(x in amenities_lower for x in ["garage", "covered parking"]),
            has_ev_charger=any(x in amenities_lower for x in ["ev charger", "electric vehicle", "tesla charger"]),
            has_game_room=any(x in amenities_lower for x in ["game room", "games", "arcade"]),
            has_home_theater=any(x in amenities_lower for x in ["home theater", "theatre", "media room"]),
            
            # Status
            is_active=data.get("active", data.get("status") == "active"),
            listing_status=data.get("status", "active"),
            
            # Timestamps
            last_synced_at=datetime.utcnow(),
        )
    
    def _map_property_type(self, ptype: str) -> str:
        """Map Escapia property type to canonical."""
        ptype_lower = ptype.lower()
        
        mapping = {
            "house": "single_family",
            "home": "single_family",
            "single family": "single_family",
            "condo": "condo",
            "condominium": "condo",
            "apartment": "apartment",
            "townhouse": "townhouse",
            "townhome": "townhouse",
            "cottage": "cottage",
            "cabin": "cabin",
            "villa": "villa",
        }
        
        for key, value in mapping.items():
            if key in ptype_lower:
                return value
        
        return "single_family"
    
    def _detect_waterfront_type(self, amenities: List[str]) -> Optional[str]:
        """Detect waterfront type from amenities."""
        if any("gulf" in a for a in amenities):
            return "gulf"
        if any("ocean" in a for a in amenities):
            return "ocean"
        if any("lake" in a for a in amenities):
            return "lake"
        if any("bay" in a for a in amenities):
            return "bay"
        if any("river" in a for a in amenities):
            return "river"
        return None
    
    def _detect_beach_access(self, amenities: List[str]) -> Optional[str]:
        """Detect beach access type."""
        if any("private beach" in a for a in amenities):
            return "private"
        if any("beach access" in a or "beach" in a for a in amenities):
            return "public"
        return None
    
    async def fetch_bookings(
        self,
        start_date: date,
        end_date: date,
    ) -> List[CanonicalBooking]:
        """Fetch bookings within date range."""
        bookings = []
        headers = await self._get_auth_headers()
        offset = 0
        limit = 50
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            while True:
                try:
                    response = await client.get(
                        f"{self.BASE_URL}/reservations",
                        headers=headers,
                        params={
                            "offset": offset,
                            "limit": limit,
                            "start_date": start_date.isoformat(),
                            "end_date": end_date.isoformat(),
                        },
                    )
                    
                    if response.status_code != 200:
                        logger.error(f"Escapia bookings error: {response.status_code}")
                        break
                    
                    data = response.json()
                    items = data.get("results", data.get("reservations", data.get("data", [])))
                    
                    if not items:
                        break
                    
                    for item in items:
                        try:
                            booking = self._normalize_booking(item)
                            bookings.append(booking)
                        except Exception as e:
                            logger.error(f"Error normalizing booking {item.get('id')}: {e}")
                    
                    if len(items) < limit:
                        break
                    
                    offset += limit
                    
                except Exception as e:
                    logger.error(f"Error fetching bookings: {e}")
                    break
        
        logger.info(f"Fetched {len(bookings)} bookings from Escapia")
        return bookings
    
    def _normalize_booking(self, data: Dict[str, Any]) -> CanonicalBooking:
        """Normalize Escapia booking to canonical schema."""
        from uuid import uuid4
        
        check_in = data.get("check_in", data.get("arrival_date", ""))
        check_out = data.get("check_out", data.get("departure_date", ""))
        
        if isinstance(check_in, str):
            check_in = date.fromisoformat(check_in[:10])
        if isinstance(check_out, str):
            check_out = date.fromisoformat(check_out[:10])
        
        nights = (check_out - check_in).days if check_in and check_out else 0

        total = float(data.get("total", data.get("total_amount", 0)))
        nightly_rate = total / nights if nights > 0 else 0
        guest = data.get("guest", data.get("primary_guest", {}))
        if not isinstance(guest, dict):
            guest = {}

        return CanonicalBooking(
            external_id=str(data.get("id", data.get("reservation_id", ""))),
            listing_id=uuid4(),  # Will be mapped later
            company_id=self.company_id,
            
            check_in=check_in,
            check_out=check_out,
            nights=nights,
            
            total_amount=total,
            nightly_rate=nightly_rate,
            cleaning_fee=data.get("cleaning_fee"),
            taxes=data.get("taxes", data.get("tax_amount")),

            guest_count=data.get("guests", data.get("num_guests", 1)),
            guest_first_name=guest.get("first_name", data.get("guest_first_name")),
            guest_last_name=guest.get("last_name", data.get("guest_last_name")),
            guest_email=guest.get("email", data.get("guest_email")),
            guest_phone=guest.get("phone", data.get("guest_phone")),
            booking_channel=data.get("source", data.get("channel", "direct")),
            status=data.get("status", "confirmed"),

            booked_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.utcnow(),
        )
    
    async def fetch_calendar(
        self,
        listing_id: str,
        start_date: date,
        end_date: date,
    ) -> List[CanonicalCalendarDay]:
        """Fetch calendar/availability for a listing."""
        calendar_days = []
        headers = await self._get_auth_headers()
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.get(
                    f"{self.BASE_URL}/listings/{listing_id}/calendar",
                    headers=headers,
                    params={
                        "start_date": start_date.isoformat(),
                        "end_date": end_date.isoformat(),
                    },
                )
                
                if response.status_code != 200:
                    logger.error(f"Escapia calendar error for {listing_id}: {response.status_code}")
                    return []
                
                data = response.json()
                days = data.get("calendar", data.get("days", data.get("data", [])))
                
                for day_data in days:
                    try:
                        day = self._normalize_calendar_day(listing_id, day_data)
                        calendar_days.append(day)
                    except Exception as e:
                        logger.error(f"Error normalizing calendar day: {e}")
                        
            except Exception as e:
                logger.error(f"Error fetching calendar for {listing_id}: {e}")
        
        return calendar_days
    
    def _normalize_calendar_day(
        self,
        listing_id: str,
        data: Dict[str, Any],
    ) -> CanonicalCalendarDay:
        """Normalize calendar day."""
        from uuid import uuid4
        
        day_date = data.get("date")
        if isinstance(day_date, str):
            day_date = date.fromisoformat(day_date[:10])
        
        return CanonicalCalendarDay(
            listing_id=uuid4(),  # Will be mapped
            date=day_date,
            is_available=data.get("available", not data.get("booked", False)),
            is_blocked=data.get("blocked", False),
            block_reason=data.get("block_reason"),
            nightly_rate=float(data.get("rate", data.get("price", 0))),
            minimum_stay=int(data.get("min_stay", data.get("minimum_nights", 1))),
        )
    
    # =========================================================================
    # Webhook Support
    # =========================================================================
    
    def supports_webhooks(self) -> bool:
        """Escapia supports webhooks."""
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
                    "events": events,  # ["reservation.created", "reservation.updated", etc.]
                },
            )
            
            if response.status_code in (200, 201):
                return response.json()
            else:
                raise Exception(f"Failed to register webhook: {response.text}")
