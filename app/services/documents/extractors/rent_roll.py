"""
Rent Roll Extractor.

Extracts financial history from rent roll documents.
Deterministic pattern matching - no LLM.
"""

import re
from typing import Dict, List, Optional

from .base import (
    DocumentExtractor, DocumentType, ExtractionResult,
    ExtractedField, FieldConfidence
)


class RentRollExtractor(DocumentExtractor):
    """
    Extract fields from rent roll documents.
    
    Target fields:
    - historical_rent: Monthly rent amounts
    - occupancy_dates: Date ranges
    - tenant_info: Basic tenant data
    """
    
    document_type = DocumentType.RENT_ROLL
    
    # Common rent patterns
    RENT_PATTERNS = [
        r'\$\s*([\d,]+(?:\.\d{2})?)\s*(?:per|\/)\s*month',
        r'monthly\s*rent[:\s]*\$?\s*([\d,]+(?:\.\d{2})?)',
        r'rent[:\s]*\$\s*([\d,]+(?:\.\d{2})?)',
        r'\$\s*([\d,]+(?:\.\d{2})?)\s*\/\s*mo',
    ]
    
    # Date patterns
    DATE_PATTERNS = [
        r'(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',
        r'(\d{4}[/-]\d{1,2}[/-]\d{1,2})',
        r'((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4})',
    ]
    
    def extract(self, text: str, metadata: Optional[Dict] = None) -> ExtractionResult:
        """Extract rent roll fields from text."""
        fields = []
        errors = []
        warnings = []
        
        text_lower = text.lower()
        
        # Extract rent amounts
        rent_amounts = self._extract_rent_amounts(text)
        if rent_amounts:
            # Use the most common or most recent
            primary_rent = max(rent_amounts, key=rent_amounts.count)
            fields.append(self._extract_field(
                name="historical_rent",
                value=primary_rent,
                confidence=FieldConfidence.HIGH if len(rent_amounts) >= 2 else FieldConfidence.MEDIUM,
                source_text=f"Found {len(rent_amounts)} rent amount(s)",
            ))
            
            # All rent history
            fields.append(self._extract_field(
                name="rent_history",
                value=list(set(rent_amounts)),
                confidence=FieldConfidence.MEDIUM,
            ))
        else:
            warnings.append("No rent amounts found")
        
        # Extract dates
        dates = self._extract_dates(text)
        if dates:
            fields.append(self._extract_field(
                name="occupancy_dates",
                value=dates,
                confidence=FieldConfidence.MEDIUM,
            ))
        
        # Extract occupancy indicators
        occupancy = self._extract_occupancy_status(text_lower)
        if occupancy:
            fields.append(self._extract_field(
                name="occupancy_status",
                value=occupancy,
                confidence=FieldConfidence.MEDIUM,
            ))
        
        # Extract total revenue if present
        total = self._extract_total_revenue(text)
        if total:
            fields.append(self._extract_field(
                name="total_revenue",
                value=total,
                confidence=FieldConfidence.HIGH,
            ))
        
        return ExtractionResult(
            document_type=self.document_type,
            fields=fields,
            errors=errors,
            warnings=warnings,
        )
    
    def _extract_rent_amounts(self, text: str) -> List[float]:
        """Extract all rent amounts from text."""
        amounts = []
        
        for pattern in self.RENT_PATTERNS:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                try:
                    # Remove commas and convert
                    amount = float(match.replace(',', ''))
                    # Filter reasonable rent amounts ($500 - $50,000/month)
                    if 500 <= amount <= 50000:
                        amounts.append(amount)
                except ValueError:
                    continue
        
        return amounts
    
    def _extract_dates(self, text: str) -> List[str]:
        """Extract dates from text."""
        dates = []
        
        for pattern in self.DATE_PATTERNS:
            matches = re.findall(pattern, text, re.IGNORECASE)
            dates.extend(matches)
        
        return list(set(dates))[:10]  # Limit to 10
    
    def _extract_occupancy_status(self, text: str) -> Optional[str]:
        """Determine occupancy status from text."""
        if any(word in text for word in ['vacant', 'unoccupied', 'available']):
            return "vacant"
        elif any(word in text for word in ['occupied', 'leased', 'rented', 'tenant']):
            return "occupied"
        return None
    
    def _extract_total_revenue(self, text: str) -> Optional[float]:
        """Extract total revenue if present."""
        patterns = [
            r'total[:\s]*\$\s*([\d,]+(?:\.\d{2})?)',
            r'annual[:\s]*\$\s*([\d,]+(?:\.\d{2})?)',
            r'gross[:\s]*\$\s*([\d,]+(?:\.\d{2})?)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    amount = float(match.group(1).replace(',', ''))
                    if amount > 5000:  # Reasonable annual amount
                        return amount
                except ValueError:
                    continue
        
        return None
