"""
Librarian Agent - Retrieves relevant context for guest interactions.

This is the core of the Orchestrated RAG architecture:
- NEVER talks to customers directly
- Retrieves only the 3-5 most relevant documents for a query
- Dramatically reduces token costs by providing minimal, targeted context

The Voice Pod sends a query, the Librarian retrieves relevant context,
and the Voice Pod uses that context to generate a response.

Cost: ~$0.01 per query (vector search + optional re-ranking)
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.knowledge.vector_store import (
    Document,
    RetrievalResult,
    VectorStore,
    get_vector_store,
)
from app.services.knowledge.knowledge_indexer import DocType

logger = logging.getLogger(__name__)


@dataclass
class LibrarianQuery:
    """Query parameters for the Librarian."""
    query: str
    tenant_id: UUID
    property_code: Optional[str] = None
    top_k: int = 5
    min_score: float = 0.2
    # Optional filters
    include_local: bool = True
    include_property: bool = True
    doc_types: Optional[List[str]] = None


@dataclass
class LibrarianResponse:
    """Response from the Librarian Agent."""
    # Context to include in the Voice Pod's prompt
    context_text: str
    
    # Structured data for quick answers
    quick_answer: Optional[str] = None
    quick_answer_type: Optional[str] = None
    
    # Source documents (for debugging/logging)
    sources: List[Document] = field(default_factory=list)
    
    # Metrics
    retrieval_time_ms: float = 0.0
    documents_retrieved: int = 0
    
    # Cost tracking
    estimated_cost_usd: float = 0.0


class LibrarianAgent:
    """
    Retrieves relevant knowledge for guest interactions.
    
    Key principle: Return MINIMAL, TARGETED context.
    
    The Librarian doesn't try to be comprehensive - it finds the
    3-5 most relevant pieces of information for a specific query.
    
    Example usage:
        librarian = LibrarianAgent(session)
        
        response = await librarian.retrieve(LibrarianQuery(
            query="Where can I get good seafood?",
            tenant_id=UUID("e07980b2-a990-4b24-91d1-c8cb71ab70e1"),
            property_code="SEALAVIE",
        ))
        
        # response.context_text contains formatted context for the LLM
        # response.quick_answer may contain a direct answer if one was found
    """
    
    # Document types that should be retrieved for local recommendations
    LOCAL_DOC_TYPES = [
        DocType.DINING,
        DocType.ACTIVITY,
        DocType.GROCERY,
        DocType.BEACH_ACCESS,
        DocType.EMERGENCY,
        DocType.LOCAL_TIP,
    ]
    
    # Document types for property-specific queries
    PROPERTY_DOC_TYPES = [
        DocType.PROPERTY_INFO,
        DocType.PROPERTY_FAQ,
        DocType.PROPERTY_RULES,
        DocType.PROPERTY_AMENITY,
    ]
    
    # Keywords that indicate property-specific queries (not local recs)
    PROPERTY_KEYWORDS = [
        "wifi", "password", "code", "door", "check-in", "check-out",
        "checkout", "checkin", "parking", "trash", "towel", "pool",
        "hot tub", "grill", "key", "lock", "alarm", "thermostat",
        "hvac", "air conditioning", "heat", "rule", "pet", "smoke",
    ]
    
    # Keywords that indicate local/dining queries
    LOCAL_KEYWORDS = [
        "restaurant", "eat", "food", "dining", "breakfast", "lunch",
        "dinner", "coffee", "bar", "drink", "seafood", "pizza",
        "activity", "activities", "do", "beach", "chair", "umbrella",
        "kayak", "paddleboard", "bike", "rental", "grocery", "store",
        "shop", "pharmacy", "hospital", "urgent care", "emergency",
    ]
    
    def __init__(self, session: AsyncSession):
        self.session = session
        self._vector_store: Optional[VectorStore] = None
    
    async def _get_store(self) -> VectorStore:
        """Get vector store instance."""
        if not self._vector_store:
            self._vector_store = await get_vector_store(self.session)
        return self._vector_store
    
    async def retrieve(self, query: LibrarianQuery) -> LibrarianResponse:
        """
        Retrieve relevant context for a query.
        
        This is the main entry point for the Voice Pod.
        """
        start_time = time.time()
        
        # Determine query type to filter appropriately
        query_type = self._classify_query(query.query)
        
        # Build document type filters
        if query.doc_types:
            doc_types = query.doc_types
        elif query_type == "property":
            doc_types = self.PROPERTY_DOC_TYPES if query.include_property else None
        elif query_type == "local":
            doc_types = self.LOCAL_DOC_TYPES if query.include_local else None
        else:
            # Mixed - search all
            doc_types = None
        
        # Search vector store
        store = await self._get_store()
        result = await store.similarity_search(
            query=query.query,
            tenant_id=query.tenant_id,
            property_code=query.property_code,
            doc_types=doc_types,
            top_k=query.top_k,
            min_score=query.min_score,
        )
        
        # Check for quick answers (exact property info)
        quick_answer, quick_answer_type = self._extract_quick_answer(
            query.query, result.documents
        )
        
        # Format context for the Voice Pod
        context_text = self._format_context(result.documents, query_type)
        
        elapsed_ms = (time.time() - start_time) * 1000
        
        # Estimate cost (vector search is essentially free, main cost is embedding)
        estimated_cost = 0.001  # ~$0.001 per query for embedding
        
        return LibrarianResponse(
            context_text=context_text,
            quick_answer=quick_answer,
            quick_answer_type=quick_answer_type,
            sources=result.documents,
            retrieval_time_ms=elapsed_ms,
            documents_retrieved=len(result.documents),
            estimated_cost_usd=estimated_cost,
        )
    
    async def retrieve_property_basics(
        self,
        tenant_id: UUID,
        property_code: str,
    ) -> Dict[str, Any]:
        """
        Retrieve basic property info (WiFi, codes, times).
        
        This is for the "quick context" that goes in the system prompt.
        Returns structured data, not formatted text.
        """
        store = await self._get_store()
        
        # Get property info document
        result = await store.similarity_search(
            query="WiFi password door code check-in check-out time",
            tenant_id=tenant_id,
            property_code=property_code,
            doc_types=[DocType.PROPERTY_INFO],
            top_k=1,
            min_score=0.2,
        )
        
        if not result.documents:
            return {}
        
        # Extract structured data from metadata
        doc = result.documents[0]
        return {
            "wifi_network": doc.metadata.get("wifi_network"),
            "wifi_password": doc.metadata.get("wifi_password"),
            "door_code": doc.metadata.get("door_code"),
            "check_in_time": doc.metadata.get("check_in_time"),
            "check_out_time": doc.metadata.get("check_out_time"),
        }
    
    def _classify_query(self, query: str) -> str:
        """
        Classify query as 'property', 'local', or 'mixed'.
        
        This helps filter documents appropriately.
        """
        query_lower = query.lower()
        
        property_score = sum(1 for kw in self.PROPERTY_KEYWORDS if kw in query_lower)
        local_score = sum(1 for kw in self.LOCAL_KEYWORDS if kw in query_lower)
        
        if property_score > local_score:
            return "property"
        elif local_score > property_score:
            return "local"
        else:
            return "mixed"
    
    def _extract_quick_answer(
        self,
        query: str,
        documents: List[Document],
    ) -> tuple[Optional[str], Optional[str]]:
        """
        Extract quick answer for common property questions.
        
        For questions like "What's the WiFi password?", we can
        return a direct answer without LLM generation.
        """
        query_lower = query.lower()
        
        for doc in documents:
            metadata = doc.metadata
            
            # WiFi queries
            if any(kw in query_lower for kw in ["wifi", "wi-fi", "internet", "password"]):
                network = metadata.get("wifi_network")
                password = metadata.get("wifi_password")
                if network and password:
                    return f"Network: {network}, Password: {password}", "wifi"
            
            # Door code queries
            if any(kw in query_lower for kw in ["door", "code", "access", "lock"]):
                code = metadata.get("door_code")
                if code:
                    return f"Door code: {code}", "door_code"
            
            # Check-in/out time queries
            if "check" in query_lower and any(kw in query_lower for kw in ["in", "out", "time"]):
                check_in = metadata.get("check_in_time")
                check_out = metadata.get("check_out_time")
                if "out" in query_lower and check_out:
                    return f"Check-out: {check_out}", "check_out"
                elif check_in:
                    return f"Check-in: {check_in}", "check_in"
        
        return None, None
    
    def _format_context(self, documents: List[Document], query_type: str) -> str:
        """
        Format documents as context text for the Voice Pod.
        
        Key principle: Keep it SHORT. The Voice Pod gets this in its prompt,
        so shorter = fewer tokens = lower cost.
        """
        if not documents:
            return "No relevant information found in knowledge base."
        
        lines = []
        
        if query_type == "local":
            lines.append("LOCAL RECOMMENDATIONS:")
            for doc in documents[:5]:
                name = doc.metadata.get("name", "")
                if name:
                    # Short format: Name - first 100 chars of content
                    snippet = doc.content[:150].split(". ")[0]
                    phone = doc.metadata.get("phone", "")
                    if phone:
                        lines.append(f"• {name}: {snippet}. Phone: {phone}")
                    else:
                        lines.append(f"• {name}: {snippet}")
                else:
                    lines.append(f"• {doc.content[:150]}")
        
        elif query_type == "property":
            lines.append("PROPERTY INFO:")
            for doc in documents[:3]:
                lines.append(f"• {doc.content[:200]}")
        
        else:
            # Mixed - just include content
            for doc in documents[:5]:
                lines.append(f"• {doc.content[:150]}")
        
        return "\n".join(lines)
    
    async def get_stats(self, tenant_id: UUID) -> Dict[str, Any]:
        """Get statistics for a tenant's knowledge base."""
        store = await self._get_store()
        counts = await store.count(tenant_id)
        return {
            "tenant_id": str(tenant_id),
            "total_documents": counts.get("total", 0),
            "by_type": {k: v for k, v in counts.items() if k != "total"},
        }


# =============================================================================
# Quick Retrieval Helpers (for common patterns)
# =============================================================================

async def get_dining_recommendations(
    session: AsyncSession,
    tenant_id: UUID,
    query: str = "restaurant recommendation",
    top_k: int = 3,
) -> List[Dict[str, Any]]:
    """Quick helper to get dining recommendations."""
    librarian = LibrarianAgent(session)
    response = await librarian.retrieve(LibrarianQuery(
        query=query,
        tenant_id=tenant_id,
        top_k=top_k,
        doc_types=[DocType.DINING],
    ))
    
    return [
        {
            "name": doc.metadata.get("name"),
            "description": doc.content[:200],
            "phone": doc.metadata.get("phone"),
            "price_level": doc.metadata.get("price_level"),
            "tags": doc.metadata.get("tags", []),
            "score": doc.score,
        }
        for doc in response.sources
    ]


async def get_activity_recommendations(
    session: AsyncSession,
    tenant_id: UUID,
    query: str = "things to do activities",
    top_k: int = 3,
) -> List[Dict[str, Any]]:
    """Quick helper to get activity recommendations."""
    librarian = LibrarianAgent(session)
    response = await librarian.retrieve(LibrarianQuery(
        query=query,
        tenant_id=tenant_id,
        top_k=top_k,
        doc_types=[DocType.ACTIVITY],
    ))
    
    return [
        {
            "name": doc.metadata.get("name"),
            "description": doc.content[:200],
            "phone": doc.metadata.get("phone"),
            "tags": doc.metadata.get("tags", []),
            "score": doc.score,
        }
        for doc in response.sources
    ]


# Factory function
async def get_librarian_agent(session: AsyncSession) -> LibrarianAgent:
    """Get librarian agent instance."""
    return LibrarianAgent(session)
