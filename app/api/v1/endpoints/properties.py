"""
Properties API Endpoints.

Core property management operations:
- CRUD operations
- Property search
- Status management
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel, Field

router = APIRouter()


# =============================================================================
# SCHEMAS
# =============================================================================

class PropertyCreate(BaseModel):
    """Create a new property."""
    name: Optional[str] = None
    address_line1: str
    address_line2: Optional[str] = None
    city: str
    state: str
    postal_code: str
    
    bedrooms: int
    bathrooms: float
    square_footage: Optional[int] = None
    property_type: str = "single_family"
    
    # Amenities
    amenities: Dict[str, Any] = Field(default_factory=dict)
    
    # Optional
    listed_price: Optional[float] = None
    owner_name: Optional[str] = None
    owner_email: Optional[str] = None
    owner_phone: Optional[str] = None


class PropertyResponse(BaseModel):
    """Property response."""
    id: UUID
    company_id: UUID
    
    name: Optional[str]
    internal_code: Optional[str]
    
    address: str
    city: str
    state: str
    postal_code: str
    
    bedrooms: int
    bathrooms: float
    square_footage: Optional[int]
    property_type: str
    
    status: str
    
    # Performance (if active)
    total_revenue_ytd: Optional[float] = None
    occupancy_ytd: Optional[float] = None
    
    created_at: datetime
    updated_at: datetime


class PropertyListResponse(BaseModel):
    """Paginated property list."""
    items: List[PropertyResponse]
    total: int
    page: int
    page_size: int
    pages: int


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get(
    "",
    response_model=PropertyListResponse,
    summary="List Properties",
    description="List properties with filtering and pagination."
)
async def list_properties(
    status: Optional[str] = Query(None, description="Filter by status"),
    market_id: Optional[UUID] = Query(None, description="Filter by market"),
    min_bedrooms: Optional[int] = Query(None, ge=1),
    max_bedrooms: Optional[int] = Query(None, le=20),
    search: Optional[str] = Query(None, description="Search by address or name"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> PropertyListResponse:
    """List properties."""
    # TODO: Integrate with database
    return PropertyListResponse(
        items=[],
        total=0,
        page=page,
        page_size=page_size,
        pages=0
    )


@router.post(
    "",
    response_model=PropertyResponse,
    summary="Create Property",
    description="Create a new property."
)
async def create_property(
    property_data: PropertyCreate,
) -> PropertyResponse:
    """Create a property."""
    from uuid import uuid4
    
    return PropertyResponse(
        id=uuid4(),
        company_id=uuid4(),
        name=property_data.name,
        internal_code=None,
        address=property_data.address_line1,
        city=property_data.city,
        state=property_data.state,
        postal_code=property_data.postal_code,
        bedrooms=property_data.bedrooms,
        bathrooms=property_data.bathrooms,
        square_footage=property_data.square_footage,
        property_type=property_data.property_type,
        status="prospect",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )


@router.get(
    "/{property_id}",
    response_model=PropertyResponse,
    summary="Get Property",
    description="Get a property by ID."
)
async def get_property(
    property_id: UUID,
) -> PropertyResponse:
    """Get a property."""
    raise HTTPException(status_code=404, detail="Property not found")


@router.put(
    "/{property_id}",
    response_model=PropertyResponse,
    summary="Update Property",
    description="Update a property."
)
async def update_property(
    property_id: UUID,
    property_data: PropertyCreate,
) -> PropertyResponse:
    """Update a property."""
    raise HTTPException(status_code=404, detail="Property not found")


@router.delete(
    "/{property_id}",
    summary="Delete Property",
    description="Soft delete a property."
)
async def delete_property(
    property_id: UUID,
):
    """Delete a property."""
    raise HTTPException(status_code=404, detail="Property not found")


@router.post(
    "/{property_id}/status",
    summary="Update Property Status",
    description="Update property status in the pipeline."
)
async def update_status(
    property_id: UUID,
    new_status: str = Query(..., description="New status"),
):
    """Update property status."""
    valid_statuses = ["prospect", "pending", "onboarding", "active", "paused", "churned", "lost"]
    if new_status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {valid_statuses}")
    
    return {"property_id": str(property_id), "status": new_status, "updated_at": datetime.utcnow()}
