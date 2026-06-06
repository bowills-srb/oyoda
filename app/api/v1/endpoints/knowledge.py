"""
Knowledge API Endpoints

Provides endpoints for:
- Indexing local area data
- Indexing property data
- Testing retrieval
- Stats and monitoring
"""

import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.ops_auth import require_ops_access
from app.api.dependencies.request_tenant import resolve_request_tenant_id
from app.db.session import get_async_session
from app.services.knowledge import (
    LibrarianQuery,
    create_voice_pod,
    get_librarian_agent,
)
from app.services.concierge.guest_session import get_session_manager
from app.services.observability.slo_metrics import observe_knowledge_retrieval

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


def _require_tenant(request: Request) -> UUID:
    """Require canonical tenant scope from the caller's auth context."""
    tenant_id = resolve_request_tenant_id(request)
    if tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required: no tenant in token or cookie.",
        )
    return tenant_id


# =============================================================================
# Request/Response Models
# =============================================================================

class IndexLocalAreaRequest(BaseModel):
    """Request to index local area data."""
    communities: Optional[List[str]] = Field(None, description="Optional community filter")


class IndexPropertyRequest(BaseModel):
    """Request to index a property."""
    property_code: str
    property_data: Dict[str, Any]


class IndexAllPropertiesRequest(BaseModel):
    """Request to index multiple properties."""
    properties: List[Dict[str, Any]]


class RetrievalTestRequest(BaseModel):
    """Request to test retrieval."""
    query: str
    property_code: Optional[str] = None
    top_k: int = Field(default=5, ge=1, le=20)


class VoicePodTestRequest(BaseModel):
    """Request to test the Voice Pod."""
    message: str
    guest_token: str


class RetrievalResponse(BaseModel):
    """Response from retrieval test."""
    query: str
    context_text: str
    quick_answer: Optional[str]
    documents_retrieved: int
    retrieval_time_ms: float
    sources: List[Dict[str, Any]]


class VoicePodTestResponse(BaseModel):
    """Response from Voice Pod test."""
    response_text: str
    quick_answer_used: bool
    retrieval_time_ms: float
    generation_time_ms: float
    total_time_ms: float
    estimated_cost_usd: float
    context_used: Optional[str]


# =============================================================================
# Indexing Endpoints
# =============================================================================

@router.post("/index/local-area", dependencies=[Depends(require_ops_access)])
async def index_local_area(
    payload: IndexLocalAreaRequest,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
):
    """
    Index local area data (dining, activities, beach access) for an operator.
    
    This populates the vector store with 30A local knowledge.
    Should be run once per operator, then updated as needed.
    """
    tenant_id = _require_tenant(request)
    logger.warning(
        "[knowledge] deprecated index_local_area called tenant=%s payload_keys=%s",
        tenant_id,
        sorted(payload.model_dump(exclude_none=True).keys()),
    )
    return JSONResponse(
        status_code=410,
        content={
            "success": False,
            "message": (
                "This endpoint is deprecated as of Phase 3. "
                "Use POST /api/v1/operator/properties/reconcile to ingest "
                "guidebooks for an operator portfolio."
            ),
        },
    )


@router.post("/index/property", dependencies=[Depends(require_ops_access)])
async def index_property(
    payload: IndexPropertyRequest,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
):
    """
    Index a single property's knowledge.
    
    Property data should include:
    - name: Property name
    - wifi_network, wifi_password: WiFi credentials
    - door_code: Access code
    - check_in_time, check_out_time: Times
    - amenities: List of amenities
    - house_rules: Rules
    - faq: FAQ items
    """
    tenant_id = _require_tenant(request)
    logger.warning(
        "[knowledge] deprecated index_property called tenant=%s payload_keys=%s",
        tenant_id,
        sorted(payload.model_dump(exclude_none=True).keys()),
    )
    return JSONResponse(
        status_code=410,
        content={
            "success": False,
            "message": (
                "This endpoint is deprecated as of Phase 3. "
                "Use POST /api/v1/operator/properties/reconcile to ingest "
                "guidebooks for an operator portfolio."
            ),
        },
    )


@router.post("/index/properties", dependencies=[Depends(require_ops_access)])
async def index_all_properties(
    payload: IndexAllPropertiesRequest,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
):
    """Index multiple properties at once."""
    tenant_id = _require_tenant(request)
    logger.warning(
        "[knowledge] deprecated index_all_properties called tenant=%s payload_keys=%s",
        tenant_id,
        sorted(payload.model_dump(exclude_none=True).keys()),
    )
    return JSONResponse(
        status_code=410,
        content={
            "success": False,
            "message": (
                "This endpoint is deprecated as of Phase 3. "
                "Use POST /api/v1/operator/properties/reconcile to ingest "
                "guidebooks for an operator portfolio."
            ),
        },
    )


# =============================================================================
# Retrieval Endpoints
# =============================================================================

@router.post("/retrieve", response_model=RetrievalResponse, dependencies=[Depends(require_ops_access)])
async def test_retrieval(
    payload: RetrievalTestRequest,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
):
    """
    Test the Librarian Agent's retrieval.
    
    Use this to verify that the knowledge base is working correctly.
    """
    tenant_id = _require_tenant(request)
    librarian = await get_librarian_agent(session)
    
    query = LibrarianQuery(
        query=payload.query,
        tenant_id=tenant_id,
        property_code=payload.property_code,
        top_k=payload.top_k,
    )
    
    response = await librarian.retrieve(query)
    observe_knowledge_retrieval(
        documents_retrieved=response.documents_retrieved,
        retrieval_time_ms=response.retrieval_time_ms,
    )
    
    return RetrievalResponse(
        query=payload.query,
        context_text=response.context_text,
        quick_answer=response.quick_answer,
        documents_retrieved=response.documents_retrieved,
        retrieval_time_ms=response.retrieval_time_ms,
        sources=[
            {
                "content": doc.content[:200] + "..." if len(doc.content) > 200 else doc.content,
                "doc_type": doc.metadata.get("doc_type"),
                "name": doc.metadata.get("name"),
                "score": doc.score,
            }
            for doc in response.sources
        ],
    )

@router.get("/debug", dependencies=[Depends(require_ops_access)])
async def debug_retrieval(
    request: Request,
    session: AsyncSession = Depends(get_async_session),
):
    """Debug: raw SQL query against knowledge_embeddings."""
    tenant_id = _require_tenant(request)
    result = await session.execute(
        text(
            "SELECT doc_id, property_code FROM knowledge_embeddings "
            "WHERE tenant_id = CAST(:tenant_id AS uuid) LIMIT 3"
        ),
        {"tenant_id": str(tenant_id)},
    )
    rows = result.fetchall()
    return {"tenant_id": str(tenant_id), "rows": [dict(r._mapping) for r in rows], "count": len(rows)}


@router.get("/stats", dependencies=[Depends(require_ops_access)])
async def get_knowledge_stats(
    request: Request,
    session: AsyncSession = Depends(get_async_session),
):
    """Get statistics for the caller's knowledge base."""
    tenant_id = _require_tenant(request)
    librarian = await get_librarian_agent(session)
    return await librarian.get_stats(tenant_id)


# =============================================================================
# Voice Pod Test Endpoint
# =============================================================================

@router.post("/voice-pod/test", response_model=VoicePodTestResponse)
async def test_voice_pod(
    request: VoicePodTestRequest,
    session: AsyncSession = Depends(get_async_session),
):
    """
    Test the Voice Pod with a guest session.
    
    Requires a valid guest token (gh_xxx).
    """
    # Get guest session
    session_manager = get_session_manager()
    guest_session = await session_manager.get_session(request.guest_token)
    
    if not guest_session:
        raise HTTPException(status_code=404, detail="Guest session not found")
    
    # Create Voice Pod
    pod = await create_voice_pod(guest_session, session)
    
    # Get response
    response = await pod.respond(request.message)
    
    return VoicePodTestResponse(
        response_text=response.text,
        quick_answer_used=response.quick_answer_used,
        retrieval_time_ms=response.retrieval_time_ms,
        generation_time_ms=response.generation_time_ms,
        total_time_ms=response.total_time_ms,
        estimated_cost_usd=response.estimated_cost_usd,
        context_used=response.context_used,
    )


# =============================================================================
# Quick Retrieval Helpers
# =============================================================================

@router.get("/dining", dependencies=[Depends(require_ops_access)])
async def get_dining_recommendations(
    request: Request,
    query: str = Query(default="good restaurant", description="Search query"),
    top_k: int = Query(default=5, ge=1, le=10),
    session: AsyncSession = Depends(get_async_session),
):
    """Get dining recommendations for the caller's tenant."""
    tenant_id = _require_tenant(request)
    from app.services.knowledge.librarian_agent import get_dining_recommendations as _get_dining
    
    return await _get_dining(session, tenant_id, query, top_k)


@router.get("/activities", dependencies=[Depends(require_ops_access)])
async def get_activity_recommendations(
    request: Request,
    query: str = Query(default="things to do", description="Search query"),
    top_k: int = Query(default=5, ge=1, le=10),
    session: AsyncSession = Depends(get_async_session),
):
    """Get activity recommendations for the caller's tenant."""
    tenant_id = _require_tenant(request)
    from app.services.knowledge.librarian_agent import get_activity_recommendations as _get_activities
    
    return await _get_activities(session, tenant_id, query, top_k)
