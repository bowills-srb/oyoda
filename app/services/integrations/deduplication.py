"""
Data Source Strategy for STR Operators

HIERARCHY OF DATA SOURCES:
==========================

1. PMS API (Primary - Source of Truth)
   - Bookings, availability, pricing
   - Property core details
   - Guest information
   - Usually has webhooks for real-time updates

2. Website Widget/Embed Integration (Authorized Access)
   - Operator adds our JS snippet to their site
   - We can read their booking widget data
   - Marketing descriptions, photos
   - No scraping needed - explicit permission

3. Channel Manager APIs
   - Many operators use channel managers (Lodgify, Guesty)
   - Single API gives access to all their channels
   - Airbnb, VRBO, Booking.com data in one place

4. Direct OTA APIs (with operator OAuth)
   - Operator authorizes us to access their Airbnb/VRBO
   - We pull listings directly from the source
   - Most accurate marketing content

5. Google Business Profile API
   - Operator links their Google Business
   - Reviews, photos, hours, contact info
   - High-quality verified data

6. Local Files (Supplementary)
   - House manuals, operational docs
   - Things NOT in any system
   - WiFi passwords, door codes, local tips

DEDUPLICATION:
==============
- Primary key: PMS external_id
- Fuzzy match: address + name + bedrooms
- Conflict resolution: PMS wins, others supplement nulls
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set
import hashlib
import re


class DataSource(str, Enum):
    """Priority-ordered data sources."""
    PMS = "pms"                      # Highest priority
    CHANNEL_MANAGER = "channel_mgr"
    AIRBNB_API = "airbnb_api"
    VRBO_API = "vrbo_api"
    WEBSITE_WIDGET = "website_widget"
    GOOGLE_BUSINESS = "google_business"
    LOCAL_FILES = "local_files"
    MANUAL = "manual"                 # Lowest priority


# Source priority (lower = higher priority)
SOURCE_PRIORITY = {
    DataSource.PMS: 1,
    DataSource.CHANNEL_MANAGER: 2,
    DataSource.AIRBNB_API: 3,
    DataSource.VRBO_API: 3,
    DataSource.WEBSITE_WIDGET: 4,
    DataSource.GOOGLE_BUSINESS: 5,
    DataSource.LOCAL_FILES: 6,
    DataSource.MANUAL: 7,
}


@dataclass
class PropertyMatch:
    """Result of property matching/deduplication."""
    is_duplicate: bool
    confidence: float  # 0.0 to 1.0
    matched_property_id: Optional[str] = None
    match_reasons: List[str] = field(default_factory=list)


@dataclass 
class SourcedField:
    """A field value with its source tracking."""
    value: Any
    source: DataSource
    confidence: float = 1.0
    last_updated: datetime = field(default_factory=datetime.utcnow)
    
    def should_replace(self, other: "SourcedField") -> bool:
        """Determine if this field should replace another."""
        if other.value is None:
            return True
        if self.value is None:
            return False
        # Higher priority source wins
        return SOURCE_PRIORITY.get(self.source, 99) < SOURCE_PRIORITY.get(other.source, 99)


class PropertyDeduplicator:
    """
    Handles property deduplication across multiple data sources.
    
    Strategy:
    1. Exact match on PMS external_id (same PMS)
    2. Exact match on address (normalized)
    3. Fuzzy match on name + location + bedrooms
    """
    
    def __init__(self):
        self._address_index: Dict[str, str] = {}  # normalized_address -> property_id
        self._pms_index: Dict[str, str] = {}  # pms_provider:external_id -> property_id
        self._name_index: Dict[str, Set[str]] = {}  # normalized_name -> set of property_ids
    
    def generate_property_hash(
        self,
        address: Optional[str],
        name: Optional[str],
        bedrooms: Optional[int],
        city: Optional[str] = None,
    ) -> str:
        """Generate a hash for fuzzy matching."""
        components = [
            self._normalize_address(address) if address else "",
            self._normalize_name(name) if name else "",
            str(bedrooms) if bedrooms else "",
            self._normalize_city(city) if city else "",
        ]
        combined = "|".join(components)
        return hashlib.md5(combined.encode()).hexdigest()[:16]
    
    def _normalize_address(self, address: str) -> str:
        """Normalize address for matching."""
        if not address:
            return ""
        
        # Lowercase
        addr = address.lower()
        
        # Remove unit/apt numbers
        addr = re.sub(r'\b(apt|unit|suite|ste|#)\s*\w+', '', addr)
        
        # Standardize street types
        replacements = {
            r'\bstreet\b': 'st',
            r'\bavenue\b': 'ave',
            r'\bboulevard\b': 'blvd',
            r'\broad\b': 'rd',
            r'\bdrive\b': 'dr',
            r'\blane\b': 'ln',
            r'\bcourt\b': 'ct',
            r'\bcircle\b': 'cir',
        }
        for pattern, replacement in replacements.items():
            addr = re.sub(pattern, replacement, addr)
        
        # Remove extra whitespace
        addr = ' '.join(addr.split())
        
        # Remove punctuation
        addr = re.sub(r'[^\w\s]', '', addr)
        
        return addr.strip()
    
    def _normalize_name(self, name: str) -> str:
        """Normalize property name for matching."""
        if not name:
            return ""
        
        # Lowercase
        name = name.lower()
        
        # Remove common suffixes
        suffixes = ['vacation rental', 'beach house', 'condo', 'cottage', 
                    'villa', 'home', 'retreat', 'getaway', 'escape']
        for suffix in suffixes:
            name = name.replace(suffix, '')
        
        # Remove punctuation and extra spaces
        name = re.sub(r'[^\w\s]', '', name)
        name = ' '.join(name.split())
        
        return name.strip()
    
    def _normalize_city(self, city: str) -> str:
        """Normalize city name."""
        if not city:
            return ""
        return city.lower().strip()
    
    def find_match(
        self,
        address: Optional[str] = None,
        name: Optional[str] = None,
        bedrooms: Optional[int] = None,
        city: Optional[str] = None,
        pms_provider: Optional[str] = None,
        pms_external_id: Optional[str] = None,
    ) -> PropertyMatch:
        """
        Find if a property already exists in our system.
        
        Returns match result with confidence score.
        """
        # 1. Exact PMS match (highest confidence)
        if pms_provider and pms_external_id:
            pms_key = f"{pms_provider}:{pms_external_id}"
            if pms_key in self._pms_index:
                return PropertyMatch(
                    is_duplicate=True,
                    confidence=1.0,
                    matched_property_id=self._pms_index[pms_key],
                    match_reasons=["Exact PMS ID match"],
                )
        
        # 2. Exact address match (high confidence)
        if address:
            norm_addr = self._normalize_address(address)
            if norm_addr in self._address_index:
                return PropertyMatch(
                    is_duplicate=True,
                    confidence=0.95,
                    matched_property_id=self._address_index[norm_addr],
                    match_reasons=["Exact address match"],
                )
        
        # 3. Fuzzy name + location match
        if name:
            norm_name = self._normalize_name(name)
            if norm_name in self._name_index:
                candidates = self._name_index[norm_name]
                
                # If only one candidate, likely match
                if len(candidates) == 1:
                    return PropertyMatch(
                        is_duplicate=True,
                        confidence=0.7,
                        matched_property_id=list(candidates)[0],
                        match_reasons=["Name match (single candidate)"],
                    )
                
                # Multiple candidates - need more signals
                # TODO: Add bedroom/city matching for disambiguation
        
        # No match found
        return PropertyMatch(
            is_duplicate=False,
            confidence=0.0,
        )
    
    def register_property(
        self,
        property_id: str,
        address: Optional[str] = None,
        name: Optional[str] = None,
        pms_provider: Optional[str] = None,
        pms_external_id: Optional[str] = None,
    ):
        """Register a property in the deduplication indexes."""
        # PMS index
        if pms_provider and pms_external_id:
            pms_key = f"{pms_provider}:{pms_external_id}"
            self._pms_index[pms_key] = property_id
        
        # Address index
        if address:
            norm_addr = self._normalize_address(address)
            if norm_addr:
                self._address_index[norm_addr] = property_id
        
        # Name index
        if name:
            norm_name = self._normalize_name(name)
            if norm_name:
                if norm_name not in self._name_index:
                    self._name_index[norm_name] = set()
                self._name_index[norm_name].add(property_id)


class DataMerger:
    """
    Merges property data from multiple sources.
    
    Rules:
    1. PMS data is always authoritative for core fields
    2. Other sources can fill in missing data
    3. Track source for each field for auditing
    """
    
    # Fields where PMS is always authoritative
    PMS_AUTHORITATIVE_FIELDS = {
        'address', 'city', 'state', 'postal_code',
        'bedrooms', 'bathrooms', 'sleeps',
        'check_in_time', 'check_out_time',
        'base_rate', 'cleaning_fee', 'min_nights',
    }
    
    # Fields that can be supplemented by other sources
    SUPPLEMENTABLE_FIELDS = {
        'wifi_network', 'wifi_password',
        'door_code', 'gate_code', 'lockbox_code',
        'parking_instructions',
        'description', 'headline',
        'house_rules', 'pet_policy',
        'amenities', 'photos',
    }
    
    def merge_property(
        self,
        existing: Dict[str, SourcedField],
        new_data: Dict[str, Any],
        source: DataSource,
    ) -> Dict[str, SourcedField]:
        """
        Merge new property data into existing.
        
        Args:
            existing: Current property data with source tracking
            new_data: New data to merge
            source: Source of the new data
        
        Returns:
            Updated property data
        """
        result = existing.copy()
        
        for field_name, value in new_data.items():
            if value is None:
                continue
            
            new_field = SourcedField(
                value=value,
                source=source,
            )
            
            # Check if we should update
            if field_name not in result:
                # New field - add it
                result[field_name] = new_field
            elif new_field.should_replace(result[field_name]):
                # Higher priority source - replace
                result[field_name] = new_field
            # else: keep existing (lower priority source)
        
        return result
    
    def to_flat_dict(
        self,
        sourced_data: Dict[str, SourcedField],
    ) -> Dict[str, Any]:
        """Convert sourced data to flat dictionary."""
        return {k: v.value for k, v in sourced_data.items()}
    
    def get_source_summary(
        self,
        sourced_data: Dict[str, SourcedField],
    ) -> Dict[DataSource, List[str]]:
        """Get summary of which fields came from which source."""
        summary: Dict[DataSource, List[str]] = {}
        
        for field_name, sourced_field in sourced_data.items():
            source = sourced_field.source
            if source not in summary:
                summary[source] = []
            summary[source].append(field_name)
        
        return summary
