"""
Restaurant & Reservation Integration

Integrates with OpenTable for restaurant discovery and reservations.
"""

import httpx
import logging
from typing import Optional, List
from dataclasses import dataclass
from datetime import datetime, date

logger = logging.getLogger(__name__)


@dataclass
class Restaurant:
    name: str
    cuisine: str
    price_range: str  # "$", "$$", "$$$", "$$$$"
    rating: float
    distance_miles: float
    opentable_id: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    notes: Optional[str] = None  # e.g., "Great sunset views", "Reservations recommended"
    tags: List[str] = None  # e.g., ["seafood", "romantic", "family-friendly", "live-music"]


@dataclass
class ReservationSlot:
    time: str
    party_size: int
    booking_url: str


class OpenTableIntegration:
    """
    OpenTable API integration for restaurant search and reservations.
    
    Note: OpenTable's official API requires partnership approval.
    Alternative approaches:
    1. Use Yelp Fusion API (easier access) for discovery
    2. Use Resy API for reservations
    3. Build curated local database + direct booking links
    """
    
    def __init__(self, api_key: str = None):
        self.api_key = api_key
        self.base_url = "https://platform.opentable.com/v2"
        
    async def search_restaurants(
        self,
        latitude: float,
        longitude: float,
        cuisine: str = None,
        price_range: str = None,
        party_size: int = 2,
        date_time: datetime = None
    ) -> List[Restaurant]:
        """Search for restaurants near a location."""
        
        # If no API key, return curated local data
        if not self.api_key:
            return self._get_curated_30a_restaurants(cuisine, price_range)
        
        # OpenTable API call would go here
        # For now, return curated data
        return self._get_curated_30a_restaurants(cuisine, price_range)
    
    async def get_availability(
        self,
        restaurant_id: str,
        party_size: int,
        date: date
    ) -> List[ReservationSlot]:
        """Get available reservation times."""
        # Would call OpenTable API
        # Return mock data for now
        return []
    
    async def make_reservation(
        self,
        restaurant_id: str,
        party_size: int,
        date_time: datetime,
        guest_name: str,
        guest_phone: str,
        guest_email: str
    ) -> dict:
        """Book a reservation."""
        # Would call OpenTable API
        return {"status": "pending", "confirmation": None}
    
    def _get_curated_30a_restaurants(
        self,
        cuisine: str = None,
        price_range: str = None
    ) -> List[Restaurant]:
        """Curated list of 30A restaurants with local knowledge."""
        
        restaurants = [
            Restaurant(
                name="Bud & Alley's",
                cuisine="American/Seafood",
                price_range="$$$",
                rating=4.5,
                distance_miles=2.1,
                phone="(850) 231-5900",
                address="2236 E County Hwy 30A, Seaside",
                notes="30A landmark! Rooftop bar has amazing sunsets. Reservations recommended for dinner.",
                tags=["seafood", "sunset", "romantic", "rooftop", "landmark"]
            ),
            Restaurant(
                name="Fish Out of Water",
                cuisine="Seafood",
                price_range="$$$$",
                rating=4.7,
                distance_miles=1.5,
                phone="(850) 534-5050",
                address="34 Goldenrod Circle, WaterColor",
                notes="Upscale dining with Gulf views. Best for special occasions. Reservations essential.",
                tags=["seafood", "upscale", "gulf-view", "special-occasion"]
            ),
            Restaurant(
                name="Scratch Biscuit Kitchen",
                cuisine="Breakfast/Southern",
                price_range="$$",
                rating=4.8,
                distance_miles=3.2,
                phone="(850) 231-1440",
                address="1777 E County Hwy 30A, Rosemary Beach",
                notes="Best breakfast on 30A! Expect a wait on weekends. Get the biscuits.",
                tags=["breakfast", "brunch", "southern", "family-friendly", "local-favorite"]
            ),
            Restaurant(
                name="Red Bar",
                cuisine="American",
                price_range="$$",
                rating=4.3,
                distance_miles=4.0,
                phone="(850) 231-1008",
                address="70 Hotz Ave, Grayton Beach",
                notes="Live music every night! Fun dive bar atmosphere. Great for a casual night out.",
                tags=["live-music", "bar", "casual", "nightlife", "local-favorite"]
            ),
            Restaurant(
                name="George's at Alys Beach",
                cuisine="American/Mediterranean",
                price_range="$$$",
                rating=4.6,
                distance_miles=5.0,
                phone="(850) 641-0017",
                address="30 Castle Harbour Dr, Alys Beach",
                notes="Beautiful setting in Alys Beach. Great cocktails and brunch.",
                tags=["brunch", "cocktails", "upscale", "scenic"]
            ),
            Restaurant(
                name="La Cocina",
                cuisine="Mexican",
                price_range="$$",
                rating=4.4,
                distance_miles=2.8,
                phone="(850) 231-2100",
                address="4952 E County Hwy 30A, Seagrove",
                notes="Authentic Mexican with great margaritas. Family-friendly, outdoor seating.",
                tags=["mexican", "margaritas", "family-friendly", "outdoor"]
            ),
            Restaurant(
                name="Cafe Thirty-A",
                cuisine="American/Seafood",
                price_range="$$$",
                rating=4.5,
                distance_miles=3.5,
                phone="(850) 231-2166",
                address="3899 E Scenic Hwy 30A, Seagrove",
                notes="Upscale but relaxed. Known for great seafood and Sunday brunch.",
                tags=["seafood", "brunch", "upscale", "romantic"]
            ),
            Restaurant(
                name="The Perfect Pig",
                cuisine="BBQ",
                price_range="$$",
                rating=4.6,
                distance_miles=6.0,
                phone="(850) 231-3005",
                address="4281 W County Hwy 30A, Santa Rosa Beach",
                notes="Best BBQ on 30A. Casual, family-friendly. Get the pulled pork.",
                tags=["bbq", "casual", "family-friendly", "outdoor"]
            ),
            Restaurant(
                name="Pizza by the Sea",
                cuisine="Pizza/Italian",
                price_range="$$",
                rating=4.2,
                distance_miles=2.0,
                phone="(850) 231-3030",
                address="14 Watercolor Blvd, WaterColor",
                notes="Great pizza, perfect for families. Delivers to WaterColor properties.",
                tags=["pizza", "italian", "family-friendly", "delivery"]
            ),
            Restaurant(
                name="Stinky's Fish Camp",
                cuisine="Seafood/Casual",
                price_range="$$",
                rating=4.4,
                distance_miles=7.0,
                phone="(850) 267-3053",
                address="5960 W County Hwy 30A, Santa Rosa Beach",
                notes="Fun, casual seafood shack. Great for lunch. Famous smoked fish dip.",
                tags=["seafood", "casual", "lunch", "outdoor", "local-favorite"]
            ),
        ]
        
        # Filter by cuisine if specified
        if cuisine:
            cuisine_lower = cuisine.lower()
            restaurants = [r for r in restaurants if 
                cuisine_lower in r.cuisine.lower() or 
                any(cuisine_lower in tag for tag in (r.tags or []))]
        
        # Filter by price if specified
        if price_range:
            restaurants = [r for r in restaurants if r.price_range == price_range]
        
        return restaurants
    
    def get_recommendation(
        self,
        query: str,
        party_size: int = 2
    ) -> str:
        """
        Natural language recommendation based on query.
        Returns a conversational response.
        """
        query_lower = query.lower()
        restaurants = self._get_curated_30a_restaurants()
        
        # Match based on query keywords
        if any(word in query_lower for word in ["breakfast", "brunch", "morning"]):
            matches = [r for r in restaurants if "breakfast" in (r.tags or []) or "brunch" in (r.tags or [])]
        elif any(word in query_lower for word in ["seafood", "fish", "shrimp", "oyster"]):
            matches = [r for r in restaurants if "seafood" in r.cuisine.lower()]
        elif any(word in query_lower for word in ["romantic", "date", "anniversary", "special"]):
            matches = [r for r in restaurants if "romantic" in (r.tags or []) or "upscale" in (r.tags or [])]
        elif any(word in query_lower for word in ["family", "kids", "children"]):
            matches = [r for r in restaurants if "family-friendly" in (r.tags or [])]
        elif any(word in query_lower for word in ["music", "nightlife", "bar", "drinks"]):
            matches = [r for r in restaurants if "live-music" in (r.tags or []) or "bar" in (r.tags or [])]
        elif any(word in query_lower for word in ["sunset", "view"]):
            matches = [r for r in restaurants if "sunset" in (r.tags or []) or "gulf-view" in (r.tags or [])]
        elif any(word in query_lower for word in ["bbq", "barbecue"]):
            matches = [r for r in restaurants if "bbq" in (r.tags or [])]
        elif any(word in query_lower for word in ["mexican", "tacos", "margarita"]):
            matches = [r for r in restaurants if "mexican" in (r.tags or [])]
        elif any(word in query_lower for word in ["pizza", "italian"]):
            matches = [r for r in restaurants if "pizza" in (r.tags or []) or "italian" in (r.tags or [])]
        elif any(word in query_lower for word in ["casual", "quick", "easy"]):
            matches = [r for r in restaurants if "casual" in (r.tags or [])]
        elif any(word in query_lower for word in ["nice", "upscale", "fancy"]):
            matches = [r for r in restaurants if "upscale" in (r.tags or [])]
        else:
            # Default to top-rated
            matches = sorted(restaurants, key=lambda r: r.rating, reverse=True)[:3]
        
        if not matches:
            matches = restaurants[:3]
        
        return matches[:3]  # Return top 3 matches


# Singleton instance
restaurant_service = OpenTableIntegration()
