"""
House Manual Extractor.

Extracts property info for concierge from house manuals.
Deterministic pattern matching - no LLM.
"""

import re
from typing import Dict, List, Optional

from .base import (
    DocumentExtractor, DocumentType, ExtractionResult,
    ExtractedField, FieldConfidence
)


class HouseManualExtractor(DocumentExtractor):
    """
    Extract fields from house manuals.
    
    Target fields:
    - wifi_network, wifi_password
    - lock_code, entry_instructions
    - checkout_time, checkin_time
    - amenities
    - rules (pets, smoking, quiet hours)
    - emergency_contacts
    """
    
    document_type = DocumentType.HOUSE_MANUAL
    
    def extract(self, text: str, metadata: Optional[Dict] = None) -> ExtractionResult:
        """Extract house manual fields from text."""
        fields = []
        errors = []
        warnings = []
        
        text_lower = text.lower()
        
        # WiFi
        wifi = self._extract_wifi(text)
        if wifi.get("network"):
            fields.append(self._extract_field(
                name="wifi_network",
                value=wifi["network"],
                confidence=FieldConfidence.HIGH,
            ))
        if wifi.get("password"):
            fields.append(self._extract_field(
                name="wifi_password",
                value=wifi["password"],
                confidence=FieldConfidence.HIGH,
            ))
        
        # Lock/Entry
        lock = self._extract_lock_code(text)
        if lock:
            fields.append(self._extract_field(
                name="lock_code",
                value=lock,
                confidence=FieldConfidence.MEDIUM,
            ))
        
        # Check-in/out times
        times = self._extract_times(text)
        if times.get("checkin"):
            fields.append(self._extract_field(
                name="checkin_time",
                value=times["checkin"],
                confidence=FieldConfidence.HIGH,
            ))
        if times.get("checkout"):
            fields.append(self._extract_field(
                name="checkout_time",
                value=times["checkout"],
                confidence=FieldConfidence.HIGH,
            ))
        
        # Amenities
        amenities = self._extract_amenities(text_lower)
        if amenities:
            fields.append(self._extract_field(
                name="amenities",
                value=amenities,
                confidence=FieldConfidence.MEDIUM,
            ))
        
        # Rules
        rules = self._extract_rules(text_lower)
        if rules:
            for rule_name, rule_value in rules.items():
                fields.append(self._extract_field(
                    name=rule_name,
                    value=rule_value,
                    confidence=FieldConfidence.MEDIUM,
                ))
        
        # Emergency contacts
        contacts = self._extract_emergency_contacts(text)
        if contacts:
            fields.append(self._extract_field(
                name="emergency_contacts",
                value=contacts,
                confidence=FieldConfidence.MEDIUM,
            ))
        
        return ExtractionResult(
            document_type=self.document_type,
            fields=fields,
            errors=errors,
            warnings=warnings,
        )
    
    def _extract_wifi(self, text: str) -> Dict[str, Optional[str]]:
        """Extract WiFi credentials."""
        result = {"network": None, "password": None}
        
        # Network name patterns
        network_patterns = [
            r'wifi\s*(?:name|network|ssid)[:\s]*["\']?([^\n"\']+)',
            r'network\s*name[:\s]*["\']?([^\n"\']+)',
            r'ssid[:\s]*["\']?([^\n"\']+)',
        ]
        
        for pattern in network_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                result["network"] = match.group(1).strip()
                break
        
        # Password patterns
        password_patterns = [
            r'wifi\s*password[:\s]*["\']?([^\n"\']+)',
            r'password[:\s]*["\']?([^\n"\']+)',
            r'wifi[:\s]*["\']?([A-Za-z0-9!@#$%^&*]+)["\']?',
        ]
        
        for pattern in password_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                pwd = match.group(1).strip()
                # Filter out common non-password words
                if pwd.lower() not in ['is', 'the', 'your', 'password']:
                    result["password"] = pwd
                    break
        
        return result
    
    def _extract_lock_code(self, text: str) -> Optional[str]:
        """Extract door lock code."""
        patterns = [
            r'(?:door|lock|entry)\s*code[:\s]*(\d{4,6})',
            r'code[:\s]*(\d{4,6})',
            r'keypad[:\s]*(\d{4,6})',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1)
        
        return None
    
    def _extract_times(self, text: str) -> Dict[str, Optional[str]]:
        """Extract check-in/out times."""
        result = {"checkin": None, "checkout": None}
        
        # Check-in patterns
        checkin_patterns = [
            r'check[- ]?in[:\s]*(\d{1,2}[:\d]*\s*(?:am|pm|AM|PM)?)',
            r'arrival[:\s]*(\d{1,2}[:\d]*\s*(?:am|pm|AM|PM)?)',
        ]
        
        for pattern in checkin_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                result["checkin"] = match.group(1).strip()
                break
        
        # Check-out patterns
        checkout_patterns = [
            r'check[- ]?out[:\s]*(\d{1,2}[:\d]*\s*(?:am|pm|AM|PM)?)',
            r'departure[:\s]*(\d{1,2}[:\d]*\s*(?:am|pm|AM|PM)?)',
        ]
        
        for pattern in checkout_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                result["checkout"] = match.group(1).strip()
                break
        
        return result
    
    def _extract_amenities(self, text: str) -> List[str]:
        """Extract amenities from text."""
        amenity_keywords = {
            'pool': ['pool', 'swimming'],
            'hot_tub': ['hot tub', 'jacuzzi', 'spa'],
            'wifi': ['wifi', 'wi-fi', 'internet'],
            'grill': ['grill', 'bbq', 'barbecue'],
            'fireplace': ['fireplace', 'fire place'],
            'washer_dryer': ['washer', 'dryer', 'laundry'],
            'dishwasher': ['dishwasher'],
            'parking': ['parking', 'garage', 'driveway'],
            'beach_access': ['beach access', 'beach nearby'],
            'golf_cart': ['golf cart'],
            'bikes': ['bike', 'bicycle'],
            'kayak': ['kayak', 'canoe', 'paddleboard'],
            'game_room': ['game room', 'games', 'pool table', 'ping pong'],
        }
        
        found = []
        for amenity, keywords in amenity_keywords.items():
            if any(kw in text for kw in keywords):
                found.append(amenity)
        
        return found
    
    def _extract_rules(self, text: str) -> Dict[str, any]:
        """Extract property rules."""
        rules = {}
        
        # Pets
        if 'no pets' in text or 'pets not allowed' in text:
            rules['pets_allowed'] = False
        elif 'pets allowed' in text or 'pet friendly' in text or 'pets welcome' in text:
            rules['pets_allowed'] = True
        
        # Smoking
        if 'no smoking' in text or 'smoke free' in text:
            rules['smoking_allowed'] = False
        
        # Quiet hours
        quiet_match = re.search(r'quiet hours?[:\s]*(\d{1,2})\s*(?:pm|PM)', text)
        if quiet_match:
            rules['quiet_hours_start'] = int(quiet_match.group(1))
        
        # Max occupancy
        occ_match = re.search(r'(?:max|maximum)\s*(?:occupancy|guests?)[:\s]*(\d+)', text, re.IGNORECASE)
        if occ_match:
            rules['max_occupancy'] = int(occ_match.group(1))
        
        # Parties
        if 'no parties' in text or 'no events' in text:
            rules['parties_allowed'] = False
        
        return rules
    
    def _extract_emergency_contacts(self, text: str) -> List[Dict[str, str]]:
        """Extract emergency contact info."""
        contacts = []
        
        # Phone number pattern
        phone_pattern = r'(\d{3}[-.\s]?\d{3}[-.\s]?\d{4})'
        
        # Look for emergency/contact sections
        sections = re.split(r'\n(?=emergency|contact|manager|host)', text, flags=re.IGNORECASE)
        
        for section in sections:
            if any(word in section.lower() for word in ['emergency', 'contact', 'manager', 'host']):
                phones = re.findall(phone_pattern, section)
                for phone in phones[:3]:  # Limit to 3
                    contacts.append({"phone": phone})
        
        return contacts
