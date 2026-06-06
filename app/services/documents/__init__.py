"""
Documents Service.

Handles document upload, normalization, extraction, and evidence writing.

ARCHITECTURE:
    Upload (any format)
    → NormalizationPipeline (file detection, OCR, intermediate formats)
    → Document Classification
    → Appropriate Extractor
    → Normalized ExtractedFields
    → PropertyEvidence / MarketEvidence

Supported formats:
- PDF (text and scanned with OCR)
- CSV / Excel
- JSON
- DOCX
- PNG / JPG (OCR)
- Plain text

Supported document types:
- rent_roll: Financial history
- house_manual: Property info for concierge
- adr_history: Historical ADR data
- amenities: Property amenities list
- guest_qa: Historical Q&A (reference only)
"""

from .extractors import (
    DocumentExtractor,
    DocumentType,
    ExtractedField,
    ExtractionResult,
    FieldConfidence,
    RentRollExtractor,
    HouseManualExtractor,
    AdrHistoryExtractor,
    AmenityListExtractor,
    GuestQAExtractor,
    get_extractor,
    extract_document,
    EXTRACTOR_BY_CLASS,
)

from .normalization import (
    NormalizationPipeline,
    NormalizedDocument,
    NormalizedType,
    FileFormat,
    DocumentClass,
    detect_file_format,
    classify_document,
    get_pipeline,
)


__all__ = [
    # Types
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
    "get_extractor",
    "extract_document",
    "EXTRACTOR_BY_CLASS",
    
    # Normalization
    "NormalizationPipeline",
    "NormalizedDocument",
    "NormalizedType",
    "FileFormat",
    "DocumentClass",
    "detect_file_format",
    "classify_document",
    "get_pipeline",
]
