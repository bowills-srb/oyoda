"""
Document Extractors - Base.

Deterministic field extraction from documents.
No LLM inference. Just pattern matching and parsing.

Extractors:
- Pull structured data from documents
- Return ExtractedField objects
- Feed into PropertyEvidence
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4


class FieldConfidence(str, Enum):
    """Confidence level for extracted fields."""
    HIGH = "high"      # Exact match, structured data
    MEDIUM = "medium"  # Pattern match, reasonable certainty
    LOW = "low"        # Fuzzy match, needs verification


class DocumentType(str, Enum):
    """Supported document types."""
    LEASE = "lease"
    RENT_ROLL = "rent_roll"
    APPRAISAL = "appraisal"
    HOUSE_MANUAL = "house_manual"
    TAX_RECORD = "tax_record"
    INSURANCE = "insurance"
    MISC = "misc"


@dataclass
class ExtractedField:
    """
    A single extracted field from a document.
    
    This becomes PropertyEvidence.
    """
    field_name: str
    value: Any
    confidence: FieldConfidence = FieldConfidence.MEDIUM
    
    # Source tracking
    source_document_type: Optional[str] = None
    source_page: Optional[int] = None
    source_text: Optional[str] = None
    
    # Metadata
    field_id: UUID = field(default_factory=uuid4)
    extracted_at: datetime = field(default_factory=datetime.utcnow)
    
    def to_evidence_dict(self) -> Dict[str, Any]:
        """Convert to PropertyEvidence format."""
        return {
            "evidence_type": "document",
            "field": self.field_name,
            "value": self.value,
            "confidence": 0.9 if self.confidence == FieldConfidence.HIGH else 0.7 if self.confidence == FieldConfidence.MEDIUM else 0.5,
            "source": f"document_upload:{self.source_document_type}",
            "observed_at": self.extracted_at.isoformat(),
        }


@dataclass
class ExtractionResult:
    """Result from document extraction."""
    document_type: DocumentType
    fields: List[ExtractedField] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    
    @property
    def success(self) -> bool:
        return len(self.fields) > 0 and len(self.errors) == 0
    
    @property
    def field_count(self) -> int:
        return len(self.fields)
    
    def get_field(self, name: str) -> Optional[ExtractedField]:
        """Get field by name."""
        for f in self.fields:
            if f.field_name == name:
                return f
        return None


class DocumentExtractor(ABC):
    """
    Base class for document extractors.
    
    Extractors are deterministic:
    - Pattern matching
    - Regex extraction
    - Table parsing
    
    No LLM inference.
    """
    
    document_type: DocumentType
    
    @abstractmethod
    def extract(self, text: str, metadata: Optional[Dict] = None) -> ExtractionResult:
        """
        Extract fields from document text.
        
        Args:
            text: Document text content
            metadata: Optional metadata (filename, pages, etc.)
            
        Returns:
            ExtractionResult with extracted fields
        """
        pass
    
    def _extract_field(
        self,
        name: str,
        value: Any,
        confidence: FieldConfidence = FieldConfidence.MEDIUM,
        source_text: Optional[str] = None,
        page: Optional[int] = None,
    ) -> ExtractedField:
        """Helper to create extracted field."""
        return ExtractedField(
            field_name=name,
            value=value,
            confidence=confidence,
            source_document_type=self.document_type.value,
            source_text=source_text,
            source_page=page,
        )
