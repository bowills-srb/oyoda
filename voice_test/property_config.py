"""
Voice Concierge Data Models

This defines the property-specific data structure that powers accurate responses.
Each property can have different amenities, rules, and access levels.
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict
from enum import Enum


class PoolType(Enum):
    NONE = "none"
    UNHEATED = "unheated"
    HEATED = "heated"  # Typically $50/day extra


class BeachAccessType(Enum):
    NONE = "none"
    PUBLIC = "public"  # No amenities
    BEACH_CLUB = "beach_club"  # Access to club, chairs must be rented
    FULL_SERVICE = "full_service"  # Includes chairs/umbrellas


@dataclass
class PoolInfo:
    type: PoolType = PoolType.NONE
    heated_cost_per_day: float = 50.0
    heated_instructions: str = "Contact us 24 hours in advance to arrange pool heating."


@dataclass
class BeachAccess:
    type: BeachAccessType = BeachAccessType.NONE
    club_name: Optional[str] = None
    wristband_included: bool = False
    chairs_included: bool = False  # Important distinction!
    chair_rental_cost: Optional[str] = None  # e.g., "$40/day for 2 chairs + umbrella"
    chair_rental_location: Optional[str] = None
    notes: Optional[str] = None


@dataclass
class WiFiInfo:
    network_name: str = ""
    password: str = ""
    notes: Optional[str] = None  # e.g., "Router is in the living room closet"


@dataclass
class CheckInOut:
    check_in_time: str = "4:00 PM"
    check_out_time: str = "10:00 AM"
    early_check_in_available: bool = False
    late_check_out_available: bool = True
    late_check_out_discount: float = 0.20  # 20% off for extra night if not booked
    special_instructions: Optional[str] = None


@dataclass 
class Amenity:
    name: str
    quantity: Optional[int] = None
    location: Optional[str] = None
    instructions: Optional[str] = None


@dataclass
class EmergencyContact:
    name: str
    phone: str
    type: str  # "er", "urgent_care", "police", "property_manager"


@dataclass
class PropertyConfig:
    """Complete configuration for a single property."""
    
    # Basic info
    property_code: str
    property_name: str
    community: str
    address: str
    
    # Access & amenities
    wifi: WiFiInfo = field(default_factory=WiFiInfo)
    pool: PoolInfo = field(default_factory=PoolInfo)
    beach_access: BeachAccess = field(default_factory=BeachAccess)
    check_in_out: CheckInOut = field(default_factory=CheckInOut)
    
    # Lists
    amenities: List[Amenity] = field(default_factory=list)
    emergency_contacts: List[EmergencyContact] = field(default_factory=list)
    
    # Custom notes (anything property-specific)
    custom_notes: Dict[str, str] = field(default_factory=dict)
    
    def to_context_string(self) -> str:
        """Generate the context string for the LLM."""
        lines = [
            f"Property: {self.property_name} ({self.property_code})",
            f"Community: {self.community}",
            f"",
            f"WiFi: {self.wifi.network_name} / {self.wifi.password}",
            f"Check-in: {self.check_in_out.check_in_time} | Check-out: {self.check_in_out.check_out_time}",
        ]
        
        # Pool info
        if self.pool.type == PoolType.HEATED:
            lines.append(f"Pool: Heated available (${self.pool.heated_cost_per_day}/day). {self.pool.heated_instructions}")
        elif self.pool.type == PoolType.UNHEATED:
            lines.append(f"Pool: Yes (unheated)")
        
        # Beach access - BE SPECIFIC
        if self.beach_access.type == BeachAccessType.BEACH_CLUB:
            beach_line = f"Beach: {self.beach_access.club_name} access"
            if self.beach_access.wristband_included:
                beach_line += " with wristbands"
            if self.beach_access.chairs_included:
                beach_line += " - chairs/umbrellas INCLUDED"
            else:
                beach_line += f" - chairs NOT included, must rent ({self.beach_access.chair_rental_cost})"
            lines.append(beach_line)
        
        # Amenities
        if self.amenities:
            amenity_strs = []
            for a in self.amenities:
                s = a.name
                if a.quantity:
                    s = f"{a.quantity} {s}"
                amenity_strs.append(s)
            lines.append(f"Amenities: {', '.join(amenity_strs)}")
        
        # Late checkout deal
        if self.check_in_out.late_check_out_available:
            discount_pct = int(self.check_in_out.late_check_out_discount * 100)
            lines.append(f"Extended stay: If next day isn't booked, {discount_pct}% off for extra night")
        
        # Emergency
        if self.emergency_contacts:
            for ec in self.emergency_contacts:
                lines.append(f"Emergency ({ec.type}): {ec.name} {ec.phone}")
        
        return "\n".join(lines)


# Example: How to configure a property
EXAMPLE_PROPERTY = PropertyConfig(
    property_code="134MC",
    property_name="134 Mystic Cobalt",
    community="WaterColor",
    address="134 Mystic Cobalt St, Santa Rosa Beach, FL 32459",
    
    wifi=WiFiInfo(
        network_name="BH_134MC",
        password="Beach2024!"
    ),
    
    pool=PoolInfo(
        type=PoolType.HEATED,
        heated_cost_per_day=50.0,
        heated_instructions="Let us know 24 hours ahead to heat the pool."
    ),
    
    beach_access=BeachAccess(
        type=BeachAccessType.BEACH_CLUB,
        club_name="WaterColor Beach Club",
        wristband_included=True,
        chairs_included=False,  # THIS IS THE KEY DISTINCTION
        chair_rental_cost="$40/day for 2 chairs + umbrella",
        chair_rental_location="Beach Club attendant booth"
    ),
    
    check_in_out=CheckInOut(
        check_in_time="4:00 PM",
        check_out_time="10:00 AM",
        late_check_out_available=True,
        late_check_out_discount=0.20
    ),
    
    amenities=[
        Amenity(name="cruiser bikes", quantity=4, location="garage"),
        Amenity(name="beach wagon", quantity=1),
        Amenity(name="gas grill", location="back patio"),
        Amenity(name="Pack-n-Play crib", quantity=1),
    ],
    
    emergency_contacts=[
        EmergencyContact("Ascension Sacred Heart", "(850) 278-3955", "er"),
        EmergencyContact("30A Medical Clinic", "(850) 267-1544", "urgent_care"),
    ]
)


if __name__ == "__main__":
    # Test output
    print(EXAMPLE_PROPERTY.to_context_string())
