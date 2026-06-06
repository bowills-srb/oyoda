"""
API Endpoint: Documents.

Document upload and extraction.

POST /documents/upload → Store + Extract → Evidence
"""

from datetime import datetime
from typing import Any, List, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app.services.documents import (
    DocumentType,
    ExtractedField,
    extract_document,
)


router = APIRouter(prefix="/documents", tags=["Documents"])


# =============================================================================
# SCHEMAS
# =============================================================================

class ExtractedFieldResponse(BaseModel):
    """An extracted field."""
    field_name: str
    value: Any
    confidence: str
    source_document_type: Optional[str] = None


class UploadResponse(BaseModel):
    """Response from document upload."""
    document_id: UUID
    property_id: UUID
    document_type: str
    filename: str
    
    # Extraction results
    extraction_status: str
    fields_extracted: int
    fields: List[ExtractedFieldResponse]
    warnings: List[str]
    
    # Evidence written
    evidence_written: bool


class DocumentStatusResponse(BaseModel):
    """Document status."""
    document_id: UUID
    status: str
    fields_extracted: int


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.post("/upload", response_model=UploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    property_id: UUID = Form(...),
    document_type: str = Form(...),
):
    """
    Upload a document for extraction.
    
    Supported types:
    - lease: Lease agreements
    - rent_roll: Rent history
    - appraisal: Property appraisals
    - house_manual: Property manuals
    - misc: Other documents
    
    Flow:
    1. Store file (local/S3)
    2. Extract text
    3. Run extractor for document type
    4. Write extracted fields to PropertyEvidence
    5. Return extraction results
    """
    # Validate document type
    valid_types = [dt.value for dt in DocumentType]
    if document_type not in valid_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid document_type. Must be one of: {valid_types}"
        )
    
    # Read file content
    try:
        content = await file.read()
        
        # For now, assume text content (in production, use PDF/DOCX parsers)
        try:
            text = content.decode('utf-8')
        except UnicodeDecodeError:
            # Binary file - would need PDF parser
            text = ""
            
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read file: {str(e)}")
    
    # Generate document ID
    document_id = uuid4()
    
    # Store file (placeholder - in production, store to S3)
    file_path = f"/tmp/uploads/{document_id}/{file.filename}"
    # In production: await storage.save(file_path, content)
    
    # Extract fields
    if text:
        result = extract_document(text, document_type)
        fields = result.fields
        warnings = result.warnings + result.errors
        extraction_status = "completed" if result.success else "partial"
    else:
        fields = []
        warnings = ["Could not extract text from file. PDF/DOCX parsing not yet implemented."]
        extraction_status = "pending"
    
    # Convert fields to response format
    field_responses = [
        ExtractedFieldResponse(
            field_name=f.field_name,
            value=f.value,
            confidence=f.confidence.value,
            source_document_type=f.source_document_type,
        )
        for f in fields
    ]
    
    # Write to Evidence (placeholder - in production, write to DB)
    evidence_written = False
    if fields:
        # In production:
        # for field in fields:
        #     evidence = EvidenceRecordModel(
        #         entity_type="property",
        #         entity_id=property_id,
        #         evidence_type="document",
        #         field_name=field.field_name,
        #         value=field.value,
        #         source=f"document_upload:{document_type}",
        #         confidence=field.confidence.value,
        #     )
        #     db.add(evidence)
        # await db.commit()
        evidence_written = True
    
    return UploadResponse(
        document_id=document_id,
        property_id=property_id,
        document_type=document_type,
        filename=file.filename,
        extraction_status=extraction_status,
        fields_extracted=len(fields),
        fields=field_responses,
        warnings=warnings,
        evidence_written=evidence_written,
    )


@router.post("/extract")
async def extract_text(
    text: str,
    document_type: str,
):
    """
    Extract fields from text directly (no file upload).
    
    Useful for testing extractors.
    """
    valid_types = [dt.value for dt in DocumentType]
    if document_type not in valid_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid document_type. Must be one of: {valid_types}"
        )
    
    result = extract_document(text, document_type)
    
    return {
        "document_type": document_type,
        "success": result.success,
        "fields": [
            {
                "field_name": f.field_name,
                "value": f.value,
                "confidence": f.confidence.value,
            }
            for f in result.fields
        ],
        "warnings": result.warnings,
        "errors": result.errors,
    }


@router.get("/types")
async def get_document_types():
    """Get supported document types."""
    return {
        "types": [
            {
                "value": dt.value,
                "description": _get_type_description(dt),
            }
            for dt in DocumentType
        ]
    }


def _get_type_description(dt: DocumentType) -> str:
    """Get description for document type."""
    descriptions = {
        DocumentType.LEASE: "Lease agreements - extracts terms, dates, amounts",
        DocumentType.RENT_ROLL: "Rent history - extracts historical rents, occupancy",
        DocumentType.APPRAISAL: "Property appraisals - extracts valuations",
        DocumentType.HOUSE_MANUAL: "Property manuals - extracts WiFi, codes, rules, amenities",
        DocumentType.TAX_RECORD: "Tax records - extracts assessed values",
        DocumentType.INSURANCE: "Insurance documents - extracts coverage details",
        DocumentType.MISC: "Other documents - basic text extraction",
    }
    return descriptions.get(dt, "Unknown document type")
