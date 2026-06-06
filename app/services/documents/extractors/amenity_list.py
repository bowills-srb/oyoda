"""
Amenity List Extractor.

Extracts amenity data from CSV/Excel/JSON uploads.
Normalizes to boolean amenity flags.
"""

import re
from typing import Any, Dict, List, Optional

from .base import (
    DocumentExtractor, DocumentType, ExtractionResult,
    ExtractedField, FieldConfidence
)


class AmenityListExtractor(DocumentExtractor):
    """
    Extract amenities from structured or unstructured data.
    
    Target fields:
    - amenities: Dict of amenity → bool
    - premium_amenities: Subset that affects ADR
    - amenity_count: Total count
    """
    
    document_type = DocumentType.MISC
    
    # Known amenity mappings (normalize variations)
    AMENITY_MAPPINGS = {
        # Pool
        'pool': 'pool',
        'swimming_pool': 'pool',
        'swimming pool': 'pool',
        
        # Heated pool
        'heated_pool': 'heated_pool',
        'heated pool': 'heated_pool',
        'pool_heated': 'heated_pool',
        
        # Hot tub
        'hot_tub': 'hot_tub',
        'hot tub': 'hot_tub',
        'hottub': 'hot_tub',
        'jacuzzi': 'hot_tub',
        'spa': 'hot_tub',
        
        # Golf cart
        'golf_cart': 'golf_cart',
        'golf cart': 'golf_cart',
        'golfcart': 'golf_cart',
        
        # Beach
        'beach_access': 'beach_access',
        'beach access': 'beach_access',
        'beach': 'beach_access',
        'private_beach': 'private_beach',
        'private beach': 'private_beach',
        
        # Waterfront
        'waterfront': 'waterfront',
        'water_front': 'waterfront',
        'lakefront': 'waterfront',
        'oceanfront': 'waterfront',
        'gulf_front': 'waterfront',
        
        # Outdoor
        'grill': 'grill',
        'bbq': 'grill',
        'barbecue': 'grill',
        'outdoor_shower': 'outdoor_shower',
        'outdoor shower': 'outdoor_shower',
        'firepit': 'firepit',
        'fire_pit': 'firepit',
        'fire pit': 'firepit',
        
        # Water activities
        'kayak': 'kayak',
        'kayaks': 'kayak',
        'canoe': 'canoe',
        'paddleboard': 'paddleboard',
        'paddle_board': 'paddleboard',
        'paddle board': 'paddleboard',
        'boat_dock': 'boat_dock',
        'boat dock': 'boat_dock',
        'dock': 'boat_dock',
        
        # Bikes
        'bikes': 'bikes',
        'bicycle': 'bikes',
        'bicycles': 'bikes',
        
        # Entertainment
        'game_room': 'game_room',
        'game room': 'game_room',
        'gameroom': 'game_room',
        'pool_table': 'pool_table',
        'pool table': 'pool_table',
        'ping_pong': 'ping_pong',
        'ping pong': 'ping_pong',
        'foosball': 'foosball',
        'arcade': 'arcade',
        
        # Kids
        'crib': 'crib',
        'high_chair': 'high_chair',
        'high chair': 'high_chair',
        'highchair': 'high_chair',
        'pack_n_play': 'pack_n_play',
        'pack and play': 'pack_n_play',
        
        # Appliances
        'washer': 'washer_dryer',
        'dryer': 'washer_dryer',
        'washer_dryer': 'washer_dryer',
        'washer/dryer': 'washer_dryer',
        'laundry': 'washer_dryer',
        'dishwasher': 'dishwasher',
        
        # Tech
        'wifi': 'wifi',
        'wi-fi': 'wifi',
        'internet': 'wifi',
        'smart_tv': 'smart_tv',
        'smart tv': 'smart_tv',
        'streaming': 'streaming',
        'netflix': 'streaming',
        
        # Parking
        'garage': 'garage',
        'parking': 'parking',
        'covered_parking': 'covered_parking',
        'covered parking': 'covered_parking',
        'ev_charger': 'ev_charger',
        'ev charger': 'ev_charger',
        'electric_vehicle': 'ev_charger',
        
        # Climate
        'fireplace': 'fireplace',
        'central_ac': 'central_ac',
        'ac': 'central_ac',
        'air_conditioning': 'central_ac',
        'heating': 'heating',
        
        # Pets
        'pet_friendly': 'pet_friendly',
        'pet friendly': 'pet_friendly',
        'pets_allowed': 'pet_friendly',
        'dogs_allowed': 'pet_friendly',
        
        # Accessibility
        'wheelchair': 'wheelchair_accessible',
        'wheelchair_accessible': 'wheelchair_accessible',
        'ada': 'wheelchair_accessible',
        'accessible': 'wheelchair_accessible',
        'elevator': 'elevator',
    }
    
    # Premium amenities that significantly affect ADR
    PREMIUM_AMENITIES = {
        'pool', 'heated_pool', 'hot_tub', 'golf_cart', 
        'private_beach', 'waterfront', 'boat_dock',
        'game_room', 'ev_charger'
    }
    
    def extract(self, text: str, metadata: Optional[Dict] = None) -> ExtractionResult:
        """Extract amenities from text or structured data."""
        fields = []
        errors = []
        warnings = []
        
        amenities = {}
        
        # Try structured rows first
        rows = metadata.get('structured_rows') if metadata else None
        if rows:
            amenities.update(self._extract_from_rows(rows))
        
        # Also scan text for amenity keywords
        if text:
            amenities.update(self._extract_from_text(text))
        
        if not amenities:
            return ExtractionResult(
                document_type=self.document_type,
                fields=[],
                warnings=["No amenities found in document"],
            )
        
        # Main amenities field
        fields.append(self._extract_field(
            name="amenities",
            value=amenities,
            confidence=FieldConfidence.HIGH if len(amenities) >= 3 else FieldConfidence.MEDIUM,
        ))
        
        # Premium amenities
        premium = {k: v for k, v in amenities.items() if k in self.PREMIUM_AMENITIES and v}
        if premium:
            fields.append(self._extract_field(
                name="premium_amenities",
                value=premium,
                confidence=FieldConfidence.HIGH,
            ))
        
        # Count
        fields.append(self._extract_field(
            name="amenity_count",
            value={
                "total": sum(1 for v in amenities.values() if v),
                "premium": sum(1 for k, v in amenities.items() if v and k in self.PREMIUM_AMENITIES),
            },
            confidence=FieldConfidence.HIGH,
        ))
        
        return ExtractionResult(
            document_type=self.document_type,
            fields=fields,
            errors=errors,
            warnings=warnings,
        )
    
    def _extract_from_rows(self, rows: List[Dict]) -> Dict[str, bool]:
        """Extract amenities from structured rows."""
        amenities = {}
        
        for row in rows:
            for key, value in row.items():
                # Normalize key
                normalized = self._normalize_amenity(key)
                if normalized:
                    # Determine if present
                    if self._is_truthy(value):
                        amenities[normalized] = True
                
                # Also check value as amenity name
                if isinstance(value, str):
                    normalized = self._normalize_amenity(value)
                    if normalized:
                        amenities[normalized] = True
        
        return amenities
    
    def _extract_from_text(self, text: str) -> Dict[str, bool]:
        """Extract amenities from unstructured text."""
        amenities = {}
        text_lower = text.lower()
        
        # Check for each known amenity
        for pattern, normalized in self.AMENITY_MAPPINGS.items():
            if pattern in text_lower:
                amenities[normalized] = True
        
        return amenities
    
    def _normalize_amenity(self, name: str) -> Optional[str]:
        """Normalize amenity name to standard key."""
        if not name:
            return None
        
        cleaned = name.lower().strip().replace('-', '_')
        
        # Direct mapping
        if cleaned in self.AMENITY_MAPPINGS:
            return self.AMENITY_MAPPINGS[cleaned]
        
        # Check if it starts with any known pattern
        for pattern, normalized in self.AMENITY_MAPPINGS.items():
            if pattern in cleaned:
                return normalized
        
        return None
    
    def _is_truthy(self, value: Any) -> bool:
        """Check if value indicates amenity is present."""
        if isinstance(value, bool):
            return value
        
        if isinstance(value, str):
            v = value.lower().strip()
            return v in ('true', 'yes', '1', 'x', '✓', '✔', 'available', 'included')
        
        if isinstance(value, (int, float)):
            return value > 0
        
        return bool(value)
