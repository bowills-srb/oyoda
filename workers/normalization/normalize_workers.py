"""
Normalization Workers - Transform raw data into clean primitives.

These workers convert messy PMS data into the canonical schema.

Jobs:
- Normalize listings across Airbnb/VRBO/etc
- Normalize message threads
- Normalize amenities
- Normalize guest profiles
- Normalize bookings

All normalized data can be safely consumed by:
- BD analytics
- Concierge intelligence
- Projections engine
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import Field

from workers.base import (
    BaseWorker,
    JobPayload,
    JobResult,
    WorkerCategory,
    register_worker,
)


# =============================================================================
# PAYLOADS
# =============================================================================

class NormalizeListingPayload(JobPayload):
    """Payload for normalizing a listing."""
    raw_listing: Dict[str, Any]
    pms_provider: str
    property_id: Optional[UUID] = None


class NormalizeBatchListingsPayload(JobPayload):
    """Payload for batch listing normalization."""
    raw_listings: List[Dict[str, Any]]
    pms_provider: str


class NormalizeBookingPayload(JobPayload):
    """Payload for normalizing a booking."""
    raw_booking: Dict[str, Any]
    pms_provider: str
    property_id: UUID
    listing_id: UUID


class NormalizeMessagePayload(JobPayload):
    """Payload for normalizing a message thread."""
    raw_thread: Dict[str, Any]
    raw_messages: List[Dict[str, Any]]
    pms_provider: str
    property_id: UUID


class NormalizeAmenitiesPayload(JobPayload):
    """Payload for amenity normalization."""
    property_id: UUID
    raw_amenities: List[str]
    pms_provider: str


class NormalizeGuestPayload(JobPayload):
    """Payload for guest profile normalization."""
    raw_guest: Dict[str, Any]
    pms_provider: str
    booking_id: Optional[UUID] = None


# =============================================================================
# WORKERS
# =============================================================================

@register_worker
class NormalizeListingWorker(BaseWorker[NormalizeListingPayload]):
    """
    Normalize a single listing to canonical schema.
    
    Handles field mapping like:
    - "num_beds" → bedrooms
    - "BedroomCount" → bedrooms  
    - "sqft" → square_footage
    - "living_area" → square_footage
    """
    
    name = "normalize_listing_worker"
    category = WorkerCategory.NORMALIZATION
    max_retries = 3
    timeout_seconds = 60
    
    # Field mappings per provider
    FIELD_MAPPINGS = {
        "guesty": {
            "bedrooms": ["bedrooms", "beds", "num_beds"],
            "bathrooms": ["bathrooms", "baths", "num_baths"],
            "square_footage": ["sqft", "square_feet", "living_area", "area"],
            "title": ["title", "name", "listing_name"],
            "latitude": ["lat", "latitude", "address.lat"],
            "longitude": ["lng", "lon", "longitude", "address.lng"],
        },
        "hostaway": {
            "bedrooms": ["bedrooms", "bedroomCount"],
            "bathrooms": ["bathrooms", "bathroomCount"],
            "square_footage": ["squareFeet", "size"],
            "title": ["name", "listingName"],
            "latitude": ["latitude", "lat"],
            "longitude": ["longitude", "lng"],
        },
        "airbnb": {
            "bedrooms": ["bedrooms", "bedroom_count"],
            "bathrooms": ["bathrooms", "bathroom_count"],
            "square_footage": ["square_feet"],
            "title": ["name"],
            "latitude": ["lat"],
            "longitude": ["lng"],
        },
        "vrbo": {
            "bedrooms": ["bedrooms", "numberOfBedrooms"],
            "bathrooms": ["bathrooms", "numberOfBathrooms"],
            "square_footage": ["squareFeet", "propertySize"],
            "title": ["headline", "name"],
            "latitude": ["geoCode.latitude", "latitude"],
            "longitude": ["geoCode.longitude", "longitude"],
        },
    }
    
    # Amenity normalization - maps raw strings to canonical names
    AMENITY_MAPPINGS = {
        "pool": ["pool", "swimming pool", "swimming_pool", "private pool", "shared pool"],
        "pool_heated": ["heated pool", "heated_pool", "pool heated", "warm pool"],
        "hot_tub": ["hot tub", "hot_tub", "jacuzzi", "spa", "whirlpool", "jetted tub"],
        "waterfront": ["waterfront", "water front", "beachfront", "beach front", "lakefront", "oceanfront"],
        "pet_friendly": ["pet friendly", "pets allowed", "dog friendly", "pets_allowed", "cats allowed"],
        "garage": ["garage", "covered parking", "carport", "enclosed parking"],
        "ev_charger": ["ev charger", "ev_charger", "electric vehicle", "tesla charger", "charging station"],
        "game_room": ["game room", "game_room", "arcade", "billiards", "pool table", "foosball"],
        "home_theater": ["home theater", "home_theater", "theater room", "media room", "cinema"],
    }
    
    async def process(self, payload: NormalizeListingPayload) -> JobResult:
        raw = payload.raw_listing
        provider = payload.pms_provider
        
        # Get field mappings for provider (fallback to guesty)
        mappings = self.FIELD_MAPPINGS.get(provider, self.FIELD_MAPPINGS["guesty"])
        
        # Start with base normalized structure
        normalized = {
            "tenant_id": str(payload.tenant_id),
            "pms_provider": provider,
            "external_id": self._extract_field(raw, ["id", "listing_id", "listingId", "_id"]),
            "normalized_at": datetime.utcnow().isoformat(),
        }
        
        # Map standard fields
        for target, sources in mappings.items():
            value = self._extract_field(raw, sources)
            if value is not None:
                normalized[target] = value
        
        # Extract address components
        normalized.update(self._normalize_address(raw, provider))
        
        # Normalize amenities
        raw_amenities = self._extract_amenities(raw)
        normalized["amenities"] = self._normalize_amenities(raw_amenities)
        
        # Set boolean flags based on normalized amenities
        normalized["has_pool"] = "pool" in normalized["amenities"]
        normalized["pool_heated"] = "pool_heated" in normalized["amenities"]
        normalized["has_hot_tub"] = "hot_tub" in normalized["amenities"]
        normalized["has_waterfront"] = "waterfront" in normalized["amenities"]
        normalized["pet_friendly"] = "pet_friendly" in normalized["amenities"]
        normalized["has_garage"] = "garage" in normalized["amenities"]
        normalized["has_ev_charger"] = "ev_charger" in normalized["amenities"]
        normalized["has_game_room"] = "game_room" in normalized["amenities"]
        normalized["has_home_theater"] = "home_theater" in normalized["amenities"]
        
        # Determine waterfront type if applicable
        if normalized["has_waterfront"]:
            normalized["waterfront_type"] = self._detect_waterfront_type(raw_amenities)
        
        # Detect beach access
        normalized["beach_access"] = self._detect_beach_access(raw_amenities)
        
        return JobResult(
            success=True,
            data={"normalized_listing": normalized},
            items_processed=1,
        )
    
    def _extract_field(self, data: Dict, keys: List[str]) -> Any:
        """Extract first matching field from data."""
        for key in keys:
            # Handle nested keys like "address.lat"
            if "." in key:
                parts = key.split(".")
                value = data
                for part in parts:
                    if isinstance(value, dict):
                        value = value.get(part)
                    else:
                        value = None
                        break
                if value is not None:
                    return value
            elif key in data and data[key] is not None:
                return data[key]
        return None
    
    def _normalize_address(self, raw: Dict, provider: str) -> Dict[str, Any]:
        """Extract and normalize address components."""
        address = {}
        
        # Try common address structures
        addr_obj = raw.get("address", {})
        if isinstance(addr_obj, dict):
            address["address_line1"] = addr_obj.get("street", addr_obj.get("line1", addr_obj.get("address1", "")))
            address["address_line2"] = addr_obj.get("apt", addr_obj.get("line2", addr_obj.get("address2")))
            address["city"] = addr_obj.get("city", "")
            address["state"] = addr_obj.get("state", addr_obj.get("region", addr_obj.get("province", "")))
            address["postal_code"] = addr_obj.get("zipcode", addr_obj.get("zip", addr_obj.get("postalCode", "")))
            address["country"] = addr_obj.get("country", addr_obj.get("countryCode", "US"))
        else:
            # Flat structure
            address["address_line1"] = raw.get("street", raw.get("address", ""))
            address["city"] = raw.get("city", "")
            address["state"] = raw.get("state", "")
            address["postal_code"] = raw.get("zipcode", raw.get("zip", ""))
            address["country"] = raw.get("country", "US")
        
        # Normalize state to 2-letter code
        if len(address.get("state", "")) > 2:
            address["state"] = self._state_to_code(address["state"])
        
        return address
    
    def _state_to_code(self, state: str) -> str:
        """Convert state name to 2-letter code."""
        states = {
            "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
            "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
            "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
            "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
            "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
            "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
            "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
            "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
            "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
            "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
            "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
            "vermont": "VT", "virginia": "VA", "washington": "WA", "west virginia": "WV",
            "wisconsin": "WI", "wyoming": "WY",
        }
        return states.get(state.lower(), state[:2].upper())
    
    def _extract_amenities(self, raw: Dict) -> List[str]:
        """Extract amenities from various structures."""
        amenities = []
        
        # Direct list
        if "amenities" in raw and isinstance(raw["amenities"], list):
            for item in raw["amenities"]:
                if isinstance(item, str):
                    amenities.append(item.lower())
                elif isinstance(item, dict):
                    name = item.get("name", item.get("title", item.get("amenity", "")))
                    if name:
                        amenities.append(name.lower())
        
        # Nested structure
        if "amenities" in raw and isinstance(raw["amenities"], dict):
            for category, items in raw["amenities"].items():
                if isinstance(items, list):
                    amenities.extend([str(i).lower() for i in items])
        
        # Features list
        if "features" in raw and isinstance(raw["features"], list):
            amenities.extend([str(f).lower() for f in raw["features"]])
        
        return amenities
    
    def _normalize_amenities(self, raw_amenities: List[str]) -> List[str]:
        """Map raw amenity strings to canonical names."""
        normalized = set()
        
        for raw in raw_amenities:
            raw_lower = raw.lower().strip()
            for canonical, variants in self.AMENITY_MAPPINGS.items():
                if any(v in raw_lower for v in variants):
                    normalized.add(canonical)
        
        return list(normalized)
    
    def _detect_waterfront_type(self, raw_amenities: List[str]) -> Optional[str]:
        """Detect specific waterfront type."""
        combined = " ".join(raw_amenities).lower()
        
        if "gulf" in combined:
            return "gulf"
        elif "ocean" in combined:
            return "ocean"
        elif "lake" in combined:
            return "lake"
        elif "bay" in combined:
            return "bay"
        elif "river" in combined:
            return "river"
        elif "beach" in combined:
            return "beach"
        return None
    
    def _detect_beach_access(self, raw_amenities: List[str]) -> Optional[str]:
        """Detect beach access type."""
        combined = " ".join(raw_amenities).lower()
        
        if "private beach" in combined:
            return "private"
        elif "deeded beach" in combined or "deeded access" in combined:
            return "deeded"
        elif "beach access" in combined or "beach nearby" in combined:
            return "public"
        return None


@register_worker
class NormalizeMessageWorker(BaseWorker[NormalizeMessagePayload]):
    """
    Normalize message threads and extract metadata.
    
    Also performs:
    - Intent extraction (question, complaint, request, etc.)
    - Sentiment analysis
    - Urgency scoring
    """
    
    name = "normalize_message_worker"
    category = WorkerCategory.NORMALIZATION
    max_retries = 3
    timeout_seconds = 120
    
    async def process(self, payload: NormalizeMessagePayload) -> JobResult:
        raw_thread = payload.raw_thread
        raw_messages = payload.raw_messages
        
        # Normalize thread
        normalized_thread = {
            "tenant_id": str(payload.tenant_id),
            "property_id": str(payload.property_id),
            "pms_provider": payload.pms_provider,
            "external_thread_id": raw_thread.get("id", raw_thread.get("thread_id")),
            "subject": raw_thread.get("subject"),
            "channel": self._detect_channel(raw_thread),
            "normalized_at": datetime.utcnow().isoformat(),
        }
        
        # Normalize messages
        normalized_messages = []
        for msg in raw_messages:
            normalized_msg = {
                "external_id": msg.get("id", msg.get("message_id")),
                "direction": self._detect_direction(msg),
                "content": msg.get("message", msg.get("content", msg.get("body", ""))),
                "sent_at": msg.get("sent_at", msg.get("created_at", msg.get("timestamp"))),
                "sender_type": self._detect_sender_type(msg),
            }
            
            # Basic intent extraction
            content = normalized_msg["content"].lower()
            normalized_msg["extracted_intent"] = self._extract_intent(content)
            normalized_msg["urgency_score"] = self._calculate_urgency(content)
            
            normalized_messages.append(normalized_msg)
        
        # Update thread metadata
        if normalized_messages:
            normalized_thread["message_count"] = len(normalized_messages)
            normalized_thread["last_message_at"] = normalized_messages[-1]["sent_at"]
            normalized_thread["last_message_direction"] = normalized_messages[-1]["direction"]
            
            # Extract intents from all messages
            all_intents = [m["extracted_intent"] for m in normalized_messages if m["extracted_intent"]]
            normalized_thread["extracted_intents"] = list(set(all_intents))
        
        return JobResult(
            success=True,
            data={
                "normalized_thread": normalized_thread,
                "normalized_messages": normalized_messages,
            },
            items_processed=len(normalized_messages) + 1,
        )
    
    def _detect_channel(self, thread: Dict) -> str:
        """Detect booking channel from thread data."""
        source = thread.get("source", thread.get("channel", "")).lower()
        if "airbnb" in source:
            return "airbnb"
        elif "vrbo" in source or "homeaway" in source:
            return "vrbo"
        elif "booking" in source:
            return "booking_com"
        return "direct"
    
    def _detect_direction(self, msg: Dict) -> str:
        """Detect if message is inbound or outbound."""
        # Check various indicators
        if msg.get("direction"):
            return msg["direction"]
        if msg.get("is_from_guest", msg.get("fromGuest")):
            return "inbound"
        if msg.get("is_from_host", msg.get("fromHost")):
            return "outbound"
        if msg.get("sender_type") == "guest":
            return "inbound"
        return "inbound"  # Default to inbound
    
    def _detect_sender_type(self, msg: Dict) -> str:
        """Detect who sent the message."""
        if msg.get("sender_type"):
            return msg["sender_type"]
        if msg.get("is_from_guest") or msg.get("fromGuest"):
            return "guest"
        if msg.get("is_from_host") or msg.get("fromHost"):
            return "host"
        if msg.get("is_automated") or msg.get("automated"):
            return "system"
        return "guest"
    
    def _extract_intent(self, content: str) -> Optional[str]:
        """Extract primary intent from message content."""
        content_lower = content.lower()
        
        # Question patterns
        if "?" in content or any(w in content_lower for w in ["how", "what", "where", "when", "can i", "do you"]):
            if any(w in content_lower for w in ["check-in", "checkin", "check in", "arrive", "arrival"]):
                return "check_in_question"
            if any(w in content_lower for w in ["check-out", "checkout", "check out", "leave", "departure"]):
                return "check_out_question"
            if any(w in content_lower for w in ["wifi", "password", "internet", "code"]):
                return "wifi_question"
            if any(w in content_lower for w in ["park", "parking", "garage"]):
                return "parking_question"
            if any(w in content_lower for w in ["pool", "hot tub", "jacuzzi"]):
                return "amenity_question"
            return "general_question"
        
        # Complaint patterns
        if any(w in content_lower for w in ["broken", "not working", "doesn't work", "issue", "problem", "dirty"]):
            return "complaint"
        
        # Request patterns
        if any(w in content_lower for w in ["please", "could you", "would you", "can you", "need"]):
            if any(w in content_lower for w in ["early", "late"]):
                return "schedule_request"
            if any(w in content_lower for w in ["clean", "towel", "supply"]):
                return "service_request"
            return "general_request"
        
        # Confirmation/thanks
        if any(w in content_lower for w in ["thank", "thanks", "great", "perfect", "awesome"]):
            return "positive_feedback"
        
        return None
    
    def _calculate_urgency(self, content: str) -> float:
        """Calculate urgency score from 0 to 1."""
        content_lower = content.lower()
        score = 0.3  # Base urgency
        
        # Urgent keywords
        urgent_words = ["urgent", "emergency", "asap", "immediately", "help", "stuck", "locked"]
        if any(w in content_lower for w in urgent_words):
            score += 0.4
        
        # Problem indicators
        problem_words = ["broken", "not working", "issue", "problem", "can't", "won't"]
        if any(w in content_lower for w in problem_words):
            score += 0.2
        
        # Multiple question marks or exclamation points
        if content.count("?") > 1 or content.count("!") > 1:
            score += 0.1
        
        # All caps (shouting)
        if content.isupper() and len(content) > 10:
            score += 0.2
        
        return min(score, 1.0)


@register_worker
class NormalizeGuestWorker(BaseWorker[NormalizeGuestPayload]):
    """
    Normalize guest profile data.
    
    Creates anonymized profiles for personalization.
    NO PII is stored - only behavioral signals.
    """
    
    name = "normalize_guest_worker"
    category = WorkerCategory.NORMALIZATION
    max_retries = 3
    timeout_seconds = 60
    
    async def process(self, payload: NormalizeGuestPayload) -> JobResult:
        raw = payload.raw_guest
        
        # Hash any identifiers for privacy
        import hashlib
        
        def hash_id(value: str) -> str:
            return hashlib.sha256(value.encode()).hexdigest()[:16]
        
        normalized = {
            "tenant_id": str(payload.tenant_id),
            "pms_provider": payload.pms_provider,
            "normalized_at": datetime.utcnow().isoformat(),
        }
        
        # Hash channel-specific guest ID
        guest_id = raw.get("id", raw.get("guest_id", raw.get("guestId")))
        if guest_id:
            normalized["channel_guest_ids"] = {
                payload.pms_provider: hash_id(str(guest_id))
            }
        
        # Extract behavioral signals (not PII)
        normalized["total_bookings"] = raw.get("booking_count", raw.get("total_bookings", 0))
        normalized["review_rate"] = raw.get("review_rate")
        
        # Detect guest type from booking patterns
        # This would typically come from analyzing their bookings
        normalized["guest_type"] = "unknown"
        
        return JobResult(
            success=True,
            data={"normalized_guest": normalized},
            items_processed=1,
        )
