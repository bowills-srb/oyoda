"""
Data Normalization API Endpoints.

Provides access to the normalization pipeline:
- Normalize property data from various sources
- Batch normalization
- Schema information
- Source compatibility
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel, Field

from app.services.normalization.normalization_engine import (
    NormalizationEngine,
    NormalizationService,
    DataSource,
    DataQuality,
    NormalizationStatus,
    SCHEMA_VERSION,
)

router = APIRouter()

# Initialize services
normalization_engine = NormalizationEngine()
normalization_service = NormalizationService()


# =============================================================================
# SCHEMAS
# =============================================================================

class NormalizePropertyRequest(BaseModel):
    """Request to normalize a property."""
    source: str = Field(..., description="Data source (e.g., 'mls_flexmls', 'pms_guesty')")
    data: Dict[str, Any] = Field(..., description="Raw property data from source")
    
    class Config:
        json_schema_extra = {
            "example": {
                "source": "mls_flexmls",
                "data": {
                    "ListingId": "123456",
                    "StreetNumber": "313",
                    "StreetName": "E Royal Fern Way",
                    "City": "Santa Rosa Beach",
                    "StateOrProvince": "FL",
                    "PostalCode": "32459",
                    "BedroomsTotal": 5,
                    "BathroomsTotalInteger": 5,
                    "LivingArea": 3338,
                    "ListPrice": 3395000,
                    "PropertyType": "Single Family",
                    "PoolPrivateYN": True
                }
            }
        }


class NormalizedPropertyResponse(BaseModel):
    """Normalized property response."""
    success: bool
    status: str
    
    # The normalized property (if successful)
    canonical_id: Optional[UUID] = None
    source_id: Optional[str] = None
    
    # Quality metrics
    quality_score: float
    quality_level: str
    completeness_pct: float
    
    # Validation
    errors: List[str]
    warnings: List[str]
    
    # Audit
    transformations_applied: List[str]
    fields_mapped: int
    
    # The full normalized data
    normalized_data: Optional[Dict[str, Any]] = None
    
    # Timing
    duration_ms: int


class BatchNormalizeRequest(BaseModel):
    """Request to normalize a batch of properties."""
    source: str
    records: List[Dict[str, Any]]


class BatchNormalizeResponse(BaseModel):
    """Batch normalization response."""
    total: int
    successful: int
    failed: int
    
    results: List[NormalizedPropertyResponse]
    
    # Summary
    avg_quality_score: float
    processing_time_ms: int


class SourceInfo(BaseModel):
    """Information about a data source."""
    source_id: str
    source_name: str
    supported: bool
    field_count: int
    required_fields: List[str]
    sample_mapping: Dict[str, str]


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.post(
    "/property",
    response_model=NormalizedPropertyResponse,
    summary="Normalize Property Data",
    description="""
    Normalize raw property data from any supported source to canonical format.
    
    The normalization pipeline:
    1. Validates the source is supported
    2. Applies field mappings
    3. Transforms data types
    4. Enriches with computed fields
    5. Validates completeness and consistency
    6. Returns normalized canonical property
    
    Quality scoring provides transparency into data completeness.
    """
)
async def normalize_property(
    request: NormalizePropertyRequest,
) -> NormalizedPropertyResponse:
    """Normalize a property."""
    
    # Validate source
    try:
        source = DataSource(request.source)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported source: {request.source}. "
                   f"Supported sources: {[s.value for s in DataSource]}"
        )
    
    # Normalize
    result = normalization_engine.normalize_property(
        raw_data=request.data,
        source=source,
    )
    
    # Build response
    normalized_data = None
    if result.entity:
        normalized_data = result.entity.model_dump(mode='json')
    
    return NormalizedPropertyResponse(
        success=result.success,
        status=result.status.value,
        canonical_id=result.entity.canonical_id if result.entity else None,
        source_id=result.source_id,
        quality_score=result.quality_score,
        quality_level=result.quality_level.value,
        completeness_pct=result.completeness_pct,
        errors=result.errors,
        warnings=result.warnings,
        transformations_applied=result.transformations_applied,
        fields_mapped=result.fields_mapped,
        normalized_data=normalized_data,
        duration_ms=result.duration_ms or 0
    )


@router.post(
    "/batch",
    response_model=BatchNormalizeResponse,
    summary="Batch Normalize Properties",
    description="Normalize multiple properties in a single request."
)
async def batch_normalize(
    request: BatchNormalizeRequest,
) -> BatchNormalizeResponse:
    """Batch normalize properties."""
    import time
    start = time.time()
    
    # Validate source
    try:
        source = DataSource(request.source)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unsupported source: {request.source}")
    
    # Process batch
    results = []
    for record in request.records:
        result = normalization_engine.normalize_property(record, source)
        
        normalized_data = None
        if result.entity:
            normalized_data = result.entity.model_dump(mode='json')
        
        results.append(NormalizedPropertyResponse(
            success=result.success,
            status=result.status.value,
            canonical_id=result.entity.canonical_id if result.entity else None,
            source_id=result.source_id,
            quality_score=result.quality_score,
            quality_level=result.quality_level.value,
            completeness_pct=result.completeness_pct,
            errors=result.errors,
            warnings=result.warnings,
            transformations_applied=result.transformations_applied,
            fields_mapped=result.fields_mapped,
            normalized_data=normalized_data,
            duration_ms=result.duration_ms or 0
        ))
    
    successful = sum(1 for r in results if r.success)
    duration = int((time.time() - start) * 1000)
    
    return BatchNormalizeResponse(
        total=len(results),
        successful=successful,
        failed=len(results) - successful,
        results=results,
        avg_quality_score=sum(r.quality_score for r in results) / len(results) if results else 0,
        processing_time_ms=duration
    )


@router.get(
    "/sources",
    response_model=List[SourceInfo],
    summary="List Supported Sources",
    description="Get list of supported data sources with field mappings."
)
async def list_sources() -> List[SourceInfo]:
    """List supported data sources."""
    sources = []
    
    for source in DataSource:
        mappings = normalization_engine.field_registry.get_mappings(source)
        
        required = [m.source_path for m in mappings if m.required]
        sample = {m.source_path: m.canonical_path for m in mappings[:5]}
        
        sources.append(SourceInfo(
            source_id=source.value,
            source_name=source.name.replace("_", " ").title(),
            supported=len(mappings) > 0,
            field_count=len(mappings),
            required_fields=required,
            sample_mapping=sample
        ))
    
    return sources


@router.get(
    "/sources/{source_id}",
    response_model=SourceInfo,
    summary="Get Source Details",
    description="Get detailed field mappings for a specific source."
)
async def get_source_details(
    source_id: str,
) -> SourceInfo:
    """Get source details."""
    try:
        source = DataSource(source_id)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Source not found: {source_id}")
    
    mappings = normalization_engine.field_registry.get_mappings(source)
    required = [m.source_path for m in mappings if m.required]
    sample = {m.source_path: m.canonical_path for m in mappings}
    
    return SourceInfo(
        source_id=source.value,
        source_name=source.name.replace("_", " ").title(),
        supported=len(mappings) > 0,
        field_count=len(mappings),
        required_fields=required,
        sample_mapping=sample
    )


@router.get(
    "/schema",
    summary="Get Canonical Schema",
    description="Get the canonical schema definition and version."
)
async def get_schema():
    """Get canonical schema."""
    return {
        "schema_version": SCHEMA_VERSION,
        "entities": {
            "property": {
                "description": "Canonical property schema",
                "required_fields": ["source_system", "source_id", "bedrooms", "address"],
                "address_fields": ["line1", "city", "state", "postal_code"],
                "amenity_categories": ["pool", "beach", "outdoor", "parking", "interior", "entertainment"]
            },
            "booking": {
                "description": "Canonical booking schema",
                "required_fields": ["source_system", "source_id", "check_in", "check_out", "total_amount"]
            },
            "market_data": {
                "description": "Canonical market data schema",
                "required_fields": ["source_system", "market_identifier", "period_start", "period_end"]
            }
        },
        "quality_levels": [q.value for q in DataQuality],
        "normalization_statuses": [s.value for s in NormalizationStatus]
    }


@router.get(
    "/health",
    summary="Normalization Health Check",
    description="Check normalization service health."
)
async def health_check():
    """Health check for normalization service."""
    return {
        "status": "healthy",
        "schema_version": SCHEMA_VERSION,
        "supported_sources": len([s for s in DataSource if normalization_engine.field_registry.get_mappings(s)]),
        "total_sources": len(DataSource)
    }
