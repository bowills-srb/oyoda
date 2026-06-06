"""
30A Local Area Data

Curated recommendations for guest concierge.
Organized by community for proximity-based suggestions.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional
from enum import Enum


class Community(str, Enum):
    WATERCOLOR = "watercolor"
    SEASIDE = "seaside"
    SEAGROVE = "seagrove"
    ROSEMARY_BEACH = "rosemary_beach"
    ALYS_BEACH = "alys_beach"
    WATERSOUND = "watersound"
    SEACREST = "seacrest"
    INLET_BEACH = "inlet_beach"
    GRAYTON_BEACH = "grayton_beach"
    SANTA_ROSA = "santa_rosa"


@dataclass
class Place:
    name: str
    category: str
    address: str
    community: str
    description: str
    phone: str = ""
    hours: str = ""
    price_level: str = ""  # $, $$, $$$, $$$$
    reservations: bool = False
    walkable_from: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)


# =============================================================================
# DINING
# =============================================================================

DINING = [
    # WaterColor
    Place(
        name="Fish Out of Water",
        category="dining",
        address="34 Goldenrod Circle, Santa Rosa Beach",
        community="watercolor",
        description="Upscale coastal cuisine with Gulf views. Known for fresh seafood and craft cocktails. Rooftop bar is perfect for sunset.",
        phone="(850) 534-5050",
        hours="Breakfast 7-11am, Dinner 5-10pm",
        price_level="$$$$",
        reservations=True,
        walkable_from=["watercolor"],
        tags=["fine dining", "seafood", "sunset views", "rooftop bar", "date night"]
    ),
    Place(
        name="Scratch Biscuit Kitchen",
        category="dining",
        address="1777 E County Hwy 30A, Santa Rosa Beach",
        community="watercolor",
        description="Southern breakfast and brunch. Famous for scratch-made biscuits and creative breakfast dishes.",
        phone="(850) 231-6550",
        hours="7am-2pm daily",
        price_level="$$",
        reservations=False,
        walkable_from=["watercolor"],
        tags=["breakfast", "brunch", "family friendly", "biscuits", "southern"]
    ),
    Place(
        name="Pizza by the Sea",
        category="dining",
        address="WaterColor Town Center",
        community="watercolor",
        description="Casual pizza spot perfect for families. Good pizza, salads, and kids menu. Outdoor seating available.",
        phone="(850) 231-3030",
        hours="11am-9pm daily",
        price_level="$$",
        reservations=False,
        walkable_from=["watercolor"],
        tags=["pizza", "family friendly", "casual", "kids menu", "quick"]
    ),
    
    # Seaside
    Place(
        name="Bud & Alley's",
        category="dining",
        address="2236 E County Hwy 30A, Seaside",
        community="seaside",
        description="30A institution since 1986. Rooftop bar has the best sunset views on 30A. Fresh Gulf seafood, great cocktails.",
        phone="(850) 231-5900",
        hours="11am-10pm daily",
        price_level="$$$",
        reservations=True,
        walkable_from=["seaside", "watercolor", "seagrove"],
        tags=["seafood", "sunset views", "rooftop bar", "landmark", "cocktails"]
    ),
    Place(
        name="Great Southern Cafe",
        category="dining",
        address="83 Central Square, Seaside",
        community="seaside",
        description="Southern comfort food in the heart of Seaside. Famous for Grits a Ya Ya and fried green tomatoes.",
        phone="(850) 231-7327",
        hours="8am-9pm daily",
        price_level="$$",
        reservations=True,
        walkable_from=["seaside", "watercolor", "seagrove"],
        tags=["southern", "comfort food", "breakfast", "family friendly"]
    ),
    Place(
        name="Pickles Beachside Grill",
        category="dining",
        address="50 Central Square, Seaside",
        community="seaside",
        description="Casual burgers and sandwiches. Great for a quick lunch. Known for burgers and pickle chips.",
        phone="(850) 231-1009",
        hours="11am-8pm daily",
        price_level="$",
        reservations=False,
        walkable_from=["seaside", "watercolor", "seagrove"],
        tags=["burgers", "casual", "quick", "family friendly", "lunch"]
    ),
    
    # Rosemary Beach
    Place(
        name="Edward's Fine Food & Wine",
        category="dining",
        address="66 Main Street, Rosemary Beach",
        community="rosemary_beach",
        description="Fine dining with global influences. Excellent wine list and creative seasonal menu. Special occasion worthy.",
        phone="(850) 231-0550",
        hours="5pm-10pm, closed Tuesdays",
        price_level="$$$$",
        reservations=True,
        walkable_from=["rosemary_beach"],
        tags=["fine dining", "wine", "date night", "special occasion"]
    ),
    Place(
        name="Cowgirl Kitchen",
        category="dining",
        address="78 Main Street, Rosemary Beach",
        community="rosemary_beach",
        description="Casual breakfast and lunch with Tex-Mex flair. Great breakfast tacos and coffee.",
        phone="(850) 213-4444",
        hours="7:30am-3pm daily",
        price_level="$$",
        reservations=False,
        walkable_from=["rosemary_beach", "inlet_beach"],
        tags=["breakfast", "lunch", "tex-mex", "coffee", "casual"]
    ),
    
    # Alys Beach
    Place(
        name="Caliza Restaurant",
        category="dining",
        address="8022 E County Hwy 30A, Alys Beach",
        community="alys_beach",
        description="Mediterranean fine dining at Alys Beach. Beautiful poolside setting. Excellent cocktails and fresh seafood.",
        phone="(850) 213-5700",
        hours="11am-10pm daily",
        price_level="$$$$",
        reservations=True,
        walkable_from=["alys_beach"],
        tags=["mediterranean", "fine dining", "poolside", "cocktails", "upscale"]
    ),
    
    # Grayton Beach
    Place(
        name="Red Bar",
        category="dining",
        address="70 Hotz Avenue, Grayton Beach",
        community="grayton_beach",
        description="Legendary 30A dive bar and restaurant. Live music nightly, eclectic decor, great atmosphere. Gets crowded.",
        phone="(850) 231-1008",
        hours="11am-late daily",
        price_level="$$",
        reservations=False,
        walkable_from=["grayton_beach"],
        tags=["live music", "bar", "casual", "nightlife", "landmark", "fun"]
    ),
    Place(
        name="Chiringo",
        category="dining",
        address="63 Hotz Avenue, Grayton Beach",
        community="grayton_beach",
        description="Beach shack serving tacos, ceviche, and craft cocktails. Super casual, great vibe, feet in the sand dining.",
        phone="(850) 213-4320",
        hours="11am-9pm daily",
        price_level="$$",
        reservations=False,
        walkable_from=["grayton_beach"],
        tags=["tacos", "beach", "casual", "cocktails", "ceviche"]
    ),
]


# =============================================================================
# BEACH ACCESS
# =============================================================================

@dataclass
class BeachAccess:
    name: str
    community: str
    walkover_number: str
    amenities: List[str]
    parking: str
    description: str


BEACH_ACCESS = [
    BeachAccess(
        name="WaterColor Beach Club",
        community="watercolor",
        walkover_number="WaterColor",
        amenities=["restrooms", "showers", "food service", "towels"],
        parking="WaterColor residents/guests only",
        description="Private beach club for WaterColor guests. Wristbands provide ACCESS to club and pools. Beach chairs are NOT included - must be rented separately ($60-100/day)."
    ),
    BeachAccess(
        name="Seaside Beach Access",
        community="seaside",
        walkover_number="Central",
        amenities=["restrooms", "showers", "chair/umbrella rentals"],
        parking="Public parking in Seaside (metered)",
        description="Main beach access in Seaside. Chair and umbrella rentals available."
    ),
    BeachAccess(
        name="Ed Walline Park",
        community="seagrove",
        walkover_number="Regional Access",
        amenities=["restrooms", "showers", "parking", "wheelchair_access", "lifeguard"],
        parking="Free public parking (fills early in summer)",
        description="Large regional beach access with free parking. Lifeguards in summer."
    ),
    BeachAccess(
        name="Grayton Beach State Park",
        community="grayton_beach",
        walkover_number="State Park",
        amenities=["restrooms", "showers", "parking", "nature trails", "pavilions"],
        parking="$6 per vehicle entry fee",
        description="Beautiful state park beach. Less crowded, natural dunes, nature trails."
    ),
]


# =============================================================================
# ACTIVITIES
# =============================================================================

ACTIVITIES = [
    Place(
        name="YOLO Board & Bike",
        category="activity",
        address="WaterColor Town Center",
        community="watercolor",
        description="Paddleboard and kayak rentals. Also rent bikes. Great for exploring Western Lake or the Gulf.",
        phone="(850) 534-0059",
        hours="9am-5pm daily",
        price_level="$$",
        reservations=False,
        walkable_from=["watercolor"],
        tags=["paddleboarding", "kayaking", "bike rentals", "outdoor", "water sports"]
    ),
    Place(
        name="30A Bike Rentals",
        category="activity",
        address="Multiple locations",
        community="seaside",
        description="Bike rentals delivered to your door. Beach cruisers, kids bikes, tandems available.",
        phone="(850) 231-0606",
        hours="9am-5pm daily",
        price_level="$$",
        reservations=True,
        walkable_from=[],
        tags=["bike rentals", "delivery", "family friendly"]
    ),
    Place(
        name="Grayton Beach State Park",
        category="activity",
        address="357 Main Park Road, Santa Rosa Beach",
        community="grayton_beach",
        description="Hiking trails, kayaking on Western Lake, pristine beach. One of Florida's most scenic state parks.",
        phone="(850) 267-8300",
        hours="8am-sunset daily",
        price_level="$",
        reservations=False,
        walkable_from=["grayton_beach"],
        tags=["nature", "hiking", "kayaking", "state park", "wildlife"]
    ),
    Place(
        name="WaterColor Boathouse",
        category="activity",
        address="WaterColor",
        community="watercolor",
        description="Kayak and paddleboard rentals for Western Lake. Beautiful calm water paddling.",
        phone="(850) 534-5000",
        hours="9am-5pm daily",
        price_level="$$",
        reservations=False,
        walkable_from=["watercolor"],
        tags=["kayaking", "paddleboarding", "western lake", "water sports"]
    ),
]


# =============================================================================
# GROCERIES & ESSENTIALS
# =============================================================================

GROCERIES = [
    Place(
        name="Publix at WaterColor Crossings",
        category="grocery",
        address="12805 US-98, Inlet Beach",
        community="inlet_beach",
        description="Full-service grocery store. Deli, bakery, pharmacy. Closest Publix to WaterColor/Seaside.",
        phone="(850) 909-0243",
        hours="7am-10pm daily",
        price_level="$$",
        reservations=False,
        walkable_from=[],
        tags=["grocery", "pharmacy", "deli", "bakery"]
    ),
    Place(
        name="Modica Market",
        category="grocery",
        address="109 Central Square, Seaside",
        community="seaside",
        description="Gourmet market in Seaside. Fresh produce, deli, wine, specialty items. Great for provisions but pricey.",
        phone="(850) 231-1214",
        hours="8am-8pm daily",
        price_level="$$$",
        reservations=False,
        walkable_from=["seaside", "watercolor", "seagrove"],
        tags=["gourmet", "wine", "deli", "provisions", "specialty"]
    ),
    Place(
        name="The Wine World",
        category="grocery",
        address="12273 US-98, Inlet Beach",
        community="inlet_beach",
        description="Great wine and liquor selection. Beer, mixers, and bar supplies. Helpful staff.",
        phone="(850) 909-0009",
        hours="10am-9pm daily",
        price_level="$$",
        reservations=False,
        walkable_from=[],
        tags=["wine", "liquor", "beer", "bar supplies"]
    ),
]


# =============================================================================
# EMERGENCY
# =============================================================================

EMERGENCY = [
    Place(
        name="Sacred Heart Hospital",
        category="emergency",
        address="7800 US-98, Miramar Beach",
        community="santa_rosa",
        description="Full-service hospital with emergency room. About 25 minutes west of Seaside.",
        phone="(850) 278-3000",
        hours="24/7 ER",
        price_level="",
        reservations=False,
        walkable_from=[],
        tags=["hospital", "emergency room", "24/7"]
    ),
    Place(
        name="Ascension Sacred Heart ER - Inlet Beach",
        category="emergency",
        address="12889 US-98, Inlet Beach",
        community="inlet_beach",
        description="Free-standing emergency room. Closer than the main hospital for emergencies.",
        phone="(850) 278-3955",
        hours="24/7",
        price_level="",
        reservations=False,
        walkable_from=[],
        tags=["emergency room", "24/7", "urgent"]
    ),
    Place(
        name="30A Medical Clinic",
        category="emergency",
        address="4641 US-98, Santa Rosa Beach",
        community="santa_rosa",
        description="Urgent care clinic for non-emergencies. Walk-ins welcome.",
        phone="(850) 267-1544",
        hours="8am-4pm Mon-Fri",
        price_level="$$",
        reservations=False,
        walkable_from=[],
        tags=["urgent care", "clinic", "walk-in"]
    ),
]


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_nearby_dining(community: str, max_results: int = 5) -> List[Place]:
    """Get dining recommendations near a community, prioritizing walkable options."""
    walkable = [p for p in DINING if community in p.walkable_from]
    same_community = [p for p in DINING if p.community == community and p not in walkable]
    result = walkable + same_community
    return result[:max_results]


def get_dining_by_tag(tag: str) -> List[Place]:
    """Get dining by tag (e.g., 'seafood', 'family friendly')."""
    return [p for p in DINING if tag.lower() in [t.lower() for t in p.tags]]


def get_beach_access(community: str) -> List[BeachAccess]:
    """Get beach access points for a community."""
    return [b for b in BEACH_ACCESS if b.community == community or b.community in ['seagrove', 'grayton_beach']]


def get_activities(community: str) -> List[Place]:
    """Get activities near a community."""
    return [a for a in ACTIVITIES if community in a.walkable_from or a.community == community]


def get_groceries_and_essentials(community: str) -> List[Place]:
    """Get grocery stores and essentials."""
    walkable = [g for g in GROCERIES if community in g.walkable_from]
    all_stores = walkable + [g for g in GROCERIES if g not in walkable]
    return all_stores


def get_emergency_info() -> List[Place]:
    """Get emergency/medical information."""
    return EMERGENCY


def get_local_context_for_community(community: str) -> str:
    """Generate full local area context for a community."""
    lines = []
    
    lines.append(f"\n## Local Area Guide - {community.replace('_', ' ').title()}")
    
    # Dining
    dining = get_nearby_dining(community, max_results=6)
    if dining:
        lines.append("\n### Nearby Dining")
        for p in dining:
            walkable = "(walkable)" if community in p.walkable_from else ""
            lines.append(f"- {p.name} ({p.price_level}) - {p.description[:60]}... {walkable}")
    
    # Beach Access
    beaches = get_beach_access(community)
    if beaches:
        lines.append("\n### Beach Access")
        for b in beaches:
            lines.append(f"- {b.name}: {b.description}")
    
    # Activities
    activities = get_activities(community)
    if activities:
        lines.append("\n### Activities Nearby")
        for a in activities[:4]:
            lines.append(f"- {a.name} - {a.description[:50]}...")
    
    # Emergency
    lines.append("\n### Emergency Services")
    lines.append("- 24/7 ER: Ascension Sacred Heart ER, Inlet Beach (850) 278-3955")
    lines.append("- Urgent Care: 30A Medical Clinic (850) 267-1544")
    
    return "\n".join(lines)
