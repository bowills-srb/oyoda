"""
Normalization Pipeline.

Sits between file upload and extractors.
Converts any file format into a canonical intermediate form.

FLOW:
    Upload
    → FileType Detection
    → Text / Structure Extraction
    → Document Classification
    → Appropriate Extractor
    → Normalized ExtractedFields
    → Evidence

This is PLUMBING, not logic.
"""

import io
import logging
import mimetypes
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)


# =============================================================================
# INTERMEDIATE FORMATS
# =============================================================================

class NormalizedType(str, Enum):
    """Type of normalized content."""
    RAW_TEXT = "raw_text"
    STRUCTURED_ROWS = "structured_rows"
    IMAGE_TEXT = "image_text"
    JSON_PAYLOAD = "json_payload"


@dataclass
class NormalizedDocument:
    """
    Canonical intermediate form for any uploaded document.
    
    This is what extractors receive - regardless of original format.
    """
    # Content (at least one should be set)
    raw_text: Optional[str] = None
    structured_rows: Optional[List[Dict[str, Any]]] = None
    json_payload: Optional[Dict[str, Any]] = None
    
    # Type info
    normalized_type: NormalizedType = NormalizedType.RAW_TEXT
    original_format: str = "unknown"
    
    # Metadata
    filename: Optional[str] = None
    file_size: int = 0
    page_count: int = 1
    
    # Processing info
    ocr_used: bool = False
    ocr_confidence: float = 1.0
    
    @property
    def has_content(self) -> bool:
        return bool(self.raw_text or self.structured_rows or self.json_payload)
    
    @property
    def text_length(self) -> int:
        if self.raw_text:
            return len(self.raw_text)
        return 0


# =============================================================================
# FILE TYPE DETECTION
# =============================================================================

class FileFormat(str, Enum):
    """Detected file formats."""
    PDF = "pdf"
    CSV = "csv"
    XLSX = "xlsx"
    XLS = "xls"
    DOCX = "docx"
    DOC = "doc"
    TXT = "txt"
    JSON = "json"
    PNG = "png"
    JPG = "jpg"
    JPEG = "jpeg"
    TIFF = "tiff"
    UNKNOWN = "unknown"


def detect_file_format(
    filename: str,
    content: bytes = None,
    content_type: str = None,
) -> FileFormat:
    """
    Detect file format from filename, content, or content-type.
    
    Priority: extension > content-type > magic bytes
    """
    # Try extension first
    if filename:
        ext = Path(filename).suffix.lower().lstrip('.')
        format_map = {
            'pdf': FileFormat.PDF,
            'csv': FileFormat.CSV,
            'xlsx': FileFormat.XLSX,
            'xls': FileFormat.XLS,
            'docx': FileFormat.DOCX,
            'doc': FileFormat.DOC,
            'txt': FileFormat.TXT,
            'json': FileFormat.JSON,
            'png': FileFormat.PNG,
            'jpg': FileFormat.JPG,
            'jpeg': FileFormat.JPEG,
            'tiff': FileFormat.TIFF,
            'tif': FileFormat.TIFF,
        }
        if ext in format_map:
            return format_map[ext]
    
    # Try content-type
    if content_type:
        type_map = {
            'application/pdf': FileFormat.PDF,
            'text/csv': FileFormat.CSV,
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': FileFormat.XLSX,
            'application/vnd.ms-excel': FileFormat.XLS,
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document': FileFormat.DOCX,
            'application/msword': FileFormat.DOC,
            'text/plain': FileFormat.TXT,
            'application/json': FileFormat.JSON,
            'image/png': FileFormat.PNG,
            'image/jpeg': FileFormat.JPG,
        }
        if content_type in type_map:
            return type_map[content_type]
    
    # Try magic bytes
    if content and len(content) >= 8:
        if content[:4] == b'%PDF':
            return FileFormat.PDF
        if content[:2] == b'PK':  # ZIP-based (XLSX, DOCX)
            if b'xl/' in content[:2000]:
                return FileFormat.XLSX
            if b'word/' in content[:2000]:
                return FileFormat.DOCX
        if content[:8] == b'\x89PNG\r\n\x1a\n':
            return FileFormat.PNG
        if content[:2] == b'\xff\xd8':
            return FileFormat.JPG
    
    return FileFormat.UNKNOWN


# =============================================================================
# FORMAT-SPECIFIC NORMALIZERS
# =============================================================================

def normalize_pdf(content: bytes, filename: str = None) -> NormalizedDocument:
    """
    Normalize PDF to text.
    
    Uses PyMuPDF (fitz) if available, falls back to basic extraction.
    """
    text = ""
    page_count = 1
    
    try:
        import fitz  # PyMuPDF
        
        doc = fitz.open(stream=content, filetype="pdf")
        page_count = len(doc)
        
        for page in doc:
            text += page.get_text()
        
        doc.close()
        
    except ImportError:
        # Fallback: try to extract readable text
        try:
            text = content.decode('utf-8', errors='ignore')
            # Clean up PDF artifacts
            text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)
        except:
            text = ""
    
    return NormalizedDocument(
        raw_text=text.strip() if text else None,
        normalized_type=NormalizedType.RAW_TEXT,
        original_format="pdf",
        filename=filename,
        file_size=len(content),
        page_count=page_count,
    )


def normalize_csv(content: bytes, filename: str = None) -> NormalizedDocument:
    """Normalize CSV to structured rows."""
    import csv
    from io import StringIO
    
    try:
        text = content.decode('utf-8')
    except UnicodeDecodeError:
        text = content.decode('latin-1')
    
    rows = []
    reader = csv.DictReader(StringIO(text))
    for row in reader:
        rows.append(dict(row))
    
    return NormalizedDocument(
        raw_text=text,
        structured_rows=rows,
        normalized_type=NormalizedType.STRUCTURED_ROWS,
        original_format="csv",
        filename=filename,
        file_size=len(content),
    )


def normalize_xlsx(content: bytes, filename: str = None) -> NormalizedDocument:
    """Normalize Excel to structured rows."""
    rows = []
    text_parts = []
    
    try:
        import openpyxl
        
        wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
        ws = wb.active
        
        # Get headers from first row
        headers = []
        for cell in ws[1]:
            headers.append(str(cell.value) if cell.value else f"col_{cell.column}")
        
        # Get data rows
        for row in ws.iter_rows(min_row=2, values_only=True):
            row_dict = {}
            for i, value in enumerate(row):
                if i < len(headers):
                    row_dict[headers[i]] = value
                    if value:
                        text_parts.append(str(value))
            if any(row_dict.values()):
                rows.append(row_dict)
        
        wb.close()
        
    except ImportError:
        logger.warning("openpyxl not installed - cannot parse XLSX")
    
    return NormalizedDocument(
        raw_text=" ".join(text_parts) if text_parts else None,
        structured_rows=rows if rows else None,
        normalized_type=NormalizedType.STRUCTURED_ROWS,
        original_format="xlsx",
        filename=filename,
        file_size=len(content),
    )


def normalize_json(content: bytes, filename: str = None) -> NormalizedDocument:
    """Normalize JSON to payload."""
    import json
    
    try:
        text = content.decode('utf-8')
        payload = json.loads(text)
    except:
        payload = None
        text = ""
    
    return NormalizedDocument(
        raw_text=text,
        json_payload=payload,
        normalized_type=NormalizedType.JSON_PAYLOAD,
        original_format="json",
        filename=filename,
        file_size=len(content),
    )


def normalize_text(content: bytes, filename: str = None) -> NormalizedDocument:
    """Normalize plain text."""
    try:
        text = content.decode('utf-8')
    except UnicodeDecodeError:
        text = content.decode('latin-1')
    
    return NormalizedDocument(
        raw_text=text,
        normalized_type=NormalizedType.RAW_TEXT,
        original_format="txt",
        filename=filename,
        file_size=len(content),
    )


def normalize_image(content: bytes, filename: str = None) -> NormalizedDocument:
    """
    Normalize image to text via OCR.
    
    Uses Tesseract if available, otherwise returns empty.
    """
    text = ""
    ocr_confidence = 0.0
    ocr_used = False
    
    try:
        from PIL import Image
        import pytesseract
        
        image = Image.open(io.BytesIO(content))
        text = pytesseract.image_to_string(image)
        ocr_used = True
        ocr_confidence = 0.7  # Default OCR confidence
        
    except ImportError:
        logger.warning("PIL/pytesseract not installed - cannot OCR image")
    except Exception as e:
        logger.error(f"OCR failed: {e}")
    
    return NormalizedDocument(
        raw_text=text.strip() if text else None,
        normalized_type=NormalizedType.IMAGE_TEXT,
        original_format=Path(filename).suffix.lower().lstrip('.') if filename else "image",
        filename=filename,
        file_size=len(content),
        ocr_used=ocr_used,
        ocr_confidence=ocr_confidence,
    )


def normalize_docx(content: bytes, filename: str = None) -> NormalizedDocument:
    """Normalize Word document to text."""
    text = ""
    
    try:
        from docx import Document
        
        doc = Document(io.BytesIO(content))
        paragraphs = [p.text for p in doc.paragraphs]
        text = "\n".join(paragraphs)
        
    except ImportError:
        logger.warning("python-docx not installed - cannot parse DOCX")
    
    return NormalizedDocument(
        raw_text=text.strip() if text else None,
        normalized_type=NormalizedType.RAW_TEXT,
        original_format="docx",
        filename=filename,
        file_size=len(content),
    )


# =============================================================================
# DOCUMENT CLASSIFICATION
# =============================================================================

class DocumentClass(str, Enum):
    """Document classification for extractor dispatch."""
    RENT_ROLL = "rent_roll"
    HOUSE_MANUAL = "house_manual"
    ADR_HISTORY = "adr_history"
    AMENITIES = "amenities"
    LEASE = "lease"
    APPRAISAL = "appraisal"
    TAX_RECORD = "tax_record"
    GUEST_QA = "guest_qa"
    UNKNOWN = "unknown"


def classify_document(
    normalized: NormalizedDocument,
    hint: Optional[str] = None,
) -> Tuple[DocumentClass, float]:
    """
    Classify document type from content.
    
    Uses keyword frequency for lightweight classification.
    Returns (document_class, confidence).
    """
    # If hint provided, trust it
    if hint:
        hint_map = {
            'rent_roll': DocumentClass.RENT_ROLL,
            'house_manual': DocumentClass.HOUSE_MANUAL,
            'adr_history': DocumentClass.ADR_HISTORY,
            'amenities': DocumentClass.AMENITIES,
            'lease': DocumentClass.LEASE,
            'appraisal': DocumentClass.APPRAISAL,
            'tax_record': DocumentClass.TAX_RECORD,
            'guest_qa': DocumentClass.GUEST_QA,
        }
        if hint.lower() in hint_map:
            return hint_map[hint.lower()], 0.95
    
    # Classify from content
    text = (normalized.raw_text or "").lower()
    
    # Keyword patterns for each class
    patterns = {
        DocumentClass.RENT_ROLL: [
            'rent', 'tenant', 'lease amount', 'monthly rent', 'occupancy',
            'rental income', 'unit', 'rental history'
        ],
        DocumentClass.HOUSE_MANUAL: [
            'wifi', 'password', 'check-in', 'checkout', 'amenities',
            'house rules', 'emergency', 'welcome', 'guest'
        ],
        DocumentClass.ADR_HISTORY: [
            'adr', 'daily rate', 'nightly rate', 'revenue', 'booking',
            'occupied', 'available', 'date,adr', 'rate history'
        ],
        DocumentClass.AMENITIES: [
            'amenity', 'amenities', 'pool', 'hot tub', 'grill', 'kayak',
            'golf cart', 'beach', 'equipment', 'feature'
        ],
        DocumentClass.LEASE: [
            'lease agreement', 'landlord', 'tenant', 'term of lease',
            'security deposit', 'rental agreement', 'hereby agrees'
        ],
        DocumentClass.APPRAISAL: [
            'appraisal', 'appraised value', 'market value', 'comparable sales',
            'property valuation', 'assessment'
        ],
        DocumentClass.GUEST_QA: [
            'question', 'answer', 'q&a', 'faq', 'guest asked', 'response',
            'inquiry', 'message history'
        ],
    }
    
    # Check structured data (CSV/JSON)
    if normalized.structured_rows:
        headers = set()
        for row in normalized.structured_rows[:5]:
            headers.update(k.lower() for k in row.keys())
        
        if 'adr' in headers or ('date' in headers and 'rate' in headers):
            return DocumentClass.ADR_HISTORY, 0.85
        if 'amenity' in headers or 'feature' in headers:
            return DocumentClass.AMENITIES, 0.85
        if 'question' in headers and 'answer' in headers:
            return DocumentClass.GUEST_QA, 0.85
    
    # Score by keyword frequency
    scores = {}
    for doc_class, keywords in patterns.items():
        score = sum(1 for kw in keywords if kw in text)
        if score > 0:
            scores[doc_class] = score
    
    if scores:
        best = max(scores, key=scores.get)
        confidence = min(0.9, 0.4 + (scores[best] * 0.1))
        return best, confidence
    
    return DocumentClass.UNKNOWN, 0.0


# =============================================================================
# NORMALIZATION PIPELINE
# =============================================================================

class NormalizationPipeline:
    """
    Main pipeline for normalizing uploaded files.
    
    USAGE:
        pipeline = NormalizationPipeline()
        
        # Normalize file
        normalized = pipeline.normalize(content, filename)
        
        # Classify document
        doc_class, confidence = pipeline.classify(normalized)
        
        # Or do it all at once
        result = pipeline.process(content, filename, document_type_hint)
    """
    
    # Format to normalizer mapping
    NORMALIZERS = {
        FileFormat.PDF: normalize_pdf,
        FileFormat.CSV: normalize_csv,
        FileFormat.XLSX: normalize_xlsx,
        FileFormat.XLS: normalize_xlsx,
        FileFormat.JSON: normalize_json,
        FileFormat.TXT: normalize_text,
        FileFormat.DOCX: normalize_docx,
        FileFormat.DOC: normalize_docx,
        FileFormat.PNG: normalize_image,
        FileFormat.JPG: normalize_image,
        FileFormat.JPEG: normalize_image,
        FileFormat.TIFF: normalize_image,
    }
    
    def __init__(self, min_classification_confidence: float = 0.5):
        self.min_classification_confidence = min_classification_confidence
    
    def normalize(
        self,
        content: bytes,
        filename: str = None,
        content_type: str = None,
    ) -> NormalizedDocument:
        """
        Normalize file content to canonical intermediate form.
        
        Args:
            content: Raw file bytes
            filename: Optional filename for format detection
            content_type: Optional MIME type
            
        Returns:
            NormalizedDocument with extracted content
        """
        # Detect format
        file_format = detect_file_format(filename, content, content_type)
        
        # Get normalizer
        normalizer = self.NORMALIZERS.get(file_format)
        
        if normalizer:
            return normalizer(content, filename)
        
        # Fallback: try as text
        return normalize_text(content, filename)
    
    def classify(
        self,
        normalized: NormalizedDocument,
        hint: Optional[str] = None,
    ) -> Tuple[DocumentClass, float]:
        """
        Classify normalized document.
        
        Args:
            normalized: NormalizedDocument from normalize()
            hint: Optional document type hint from uploader
            
        Returns:
            (DocumentClass, confidence)
        """
        return classify_document(normalized, hint)
    
    def process(
        self,
        content: bytes,
        filename: str = None,
        document_type_hint: str = None,
        content_type: str = None,
    ) -> Dict[str, Any]:
        """
        Full pipeline: normalize → classify → return result.
        
        Args:
            content: Raw file bytes
            filename: Optional filename
            document_type_hint: Optional hint from uploader
            content_type: Optional MIME type
            
        Returns:
            {
                "normalized": NormalizedDocument,
                "document_class": DocumentClass,
                "classification_confidence": float,
                "should_extract": bool,
            }
        """
        # Normalize
        normalized = self.normalize(content, filename, content_type)
        
        # Classify
        doc_class, confidence = self.classify(normalized, document_type_hint)
        
        # Decide if we should extract
        should_extract = (
            normalized.has_content and
            doc_class != DocumentClass.UNKNOWN and
            confidence >= self.min_classification_confidence
        )
        
        return {
            "normalized": normalized,
            "document_class": doc_class,
            "classification_confidence": confidence,
            "should_extract": should_extract,
        }


# =============================================================================
# FACTORY
# =============================================================================

def get_pipeline() -> NormalizationPipeline:
    """Get default normalization pipeline."""
    return NormalizationPipeline()
