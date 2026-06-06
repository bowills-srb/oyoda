"""
Document Extractors.

Deterministic field extraction from documents.
No LLM inference - just pattern matching.

Each extractor:
- Takes document text (or structured rows)
- Returns ExtractedField objects
- Feeds into PropertyEvidence

Supported types:
- rent_roll: Financial history
- house_manual: Property info for concierge
- adr_history: Historical ADR data
- amenities: Property amenities list
- guest_qa: Historical Q&A (reference only)
"""

from .base import (
    DocumentExtractor,
    DocumentType,
    ExtractedField,
    ExtractionResult,
    FieldConfidence,
)

from .rent_roll import RentRollExtractor
from .house_manual import HouseManualExtractor
from .adr_history import AdrHistoryExtractor
from .amenity_list import AmenityListExtractor
from .guest_qa import GuestQAExtractor


# Extractor registry
EXTRACTORS = {
    DocumentType.RENT_ROLL: RentRollExtractor,
    DocumentType.HOUSE_MANUAL: HouseManualExtractor,
    # Additional extractors mapped by document class
}

# Extended registry (by document class string)
EXTRACTOR_BY_CLASS = {
    'rent_roll': RentRollExtractor,
    'house_manual': HouseManualExtractor,
    'adr_history': AdrHistoryExtractor,
    'amenities': AmenityListExtractor,
    'guest_qa': GuestQAExtractor,
}


def get_extractor(document_type: str) -> DocumentExtractor:
    """Get extractor for document type."""
    # Try extended registry first
    extractor_class = EXTRACTOR_BY_CLASS.get(document_type.lower())
    if extractor_class:
        return extractor_class()
    
    # Try enum-based registry
    try:
        doc_type = DocumentType(document_type)
        extractor_class = EXTRACTORS.get(doc_type)
        if extractor_class:
            return extractor_class()
    except ValueError:
        pass
    
    return None


def extract_document(
    text: str,
    document_type: str,
    metadata: dict = None,
) -> ExtractionResult:
    """
    Extract fields from document text.
    
    Args:
        text: Document text content
        document_type: Type of document
        metadata: Optional metadata (including structured_rows)
        
    Returns:
        ExtractionResult with extracted fields
    """
    extractor = get_extractor(document_type)
    
    if extractor is None:
        return ExtractionResult(
            document_type=DocumentType.MISC,
            fields=[],
            warnings=[f"No extractor for document type: {document_type}"],
        )
    
    return extractor.extract(text, metadata)


__all__ = [
    # Base
    "DocumentExtractor",
    "DocumentType",
    "ExtractedField",
    "ExtractionResult",
    "FieldConfidence",
    
    # Extractors
    "RentRollExtractor",
    "HouseManualExtractor",
    "AdrHistoryExtractor",
    "AmenityListExtractor",
    "GuestQAExtractor",
    
    # Registry
    "EXTRACTORS",
    "EXTRACTOR_BY_CLASS",
    "get_extractor",
    "extract_document",
]
