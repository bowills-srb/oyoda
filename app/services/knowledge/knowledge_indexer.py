"""
Knowledge Indexer - Converts property and local data into vector documents.

This module handles the "Data Agent" role in the agentic architecture:
- Indexes property details (WiFi, codes, amenities, rules)
- Indexes local area data (restaurants, activities, beach access)
- Indexes FAQs and house manuals
- Supports incremental updates

The indexed data is stored in the vector store and retrieved
by the Librarian Agent for guest interactions.
"""

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.knowledge.vector_store import Document, VectorStore, get_vector_store

# Import local area data
from services.local_area_data import (
    DINING,
    ACTIVITIES,
    GROCERIES,
    BEACH_ACCESS,
    EMERGENCY,
    Place,
    BeachAccess,
)

logger = logging.getLogger(__name__)


# Document types for filtering
class DocType:
    PROPERTY_INFO = "property_info"
    PROPERTY_FAQ = "property_faq"
    PROPERTY_RULES = "property_rules"
    PROPERTY_AMENITY = "property_amenity"
    DINING = "dining"
    ACTIVITY = "activity"
    GROCERY = "grocery"
    BEACH_ACCESS = "beach_access"
    EMERGENCY = "emergency"
    LOCAL_TIP = "local_tip"


@dataclass
class IndexingResult:
    """Result of an indexing operation."""
    tenant_id: UUID
    documents_indexed: int
    documents_updated: int
    by_type: Dict[str, int]
    errors: List[str]


class KnowledgeIndexer:
    """
    Indexes knowledge into the vector store.
    
    Two main indexing operations:
    1. index_local_area() - Index dining, activities, beach access for a tenant
    2. index_property() - Index specific property details
    
    Example usage:
        indexer = KnowledgeIndexer(session)
        
        # Index all 30A local data for Beach Habitats
        result = await indexer.index_local_area(
            UUID("e07980b2-a990-4b24-91d1-c8cb71ab70e1")
        )
        
        # Index a specific property
        result = await indexer.index_property(
            tenant_id=UUID("e07980b2-a990-4b24-91d1-c8cb71ab70e1"),
            property_code="SEALAVIE",
            property_data={...}
        )
    """
    
    def __init__(self, session: AsyncSession):
        self.session = session
        self._vector_store: Optional[VectorStore] = None
    
    async def _get_store(self) -> VectorStore:
        """Get vector store instance."""
        if not self._vector_store:
            self._vector_store = await get_vector_store(self.session)
        return self._vector_store
    
    async def index_local_area(
        self,
        tenant_id: UUID,
        communities: Optional[List[str]] = None,
    ) -> IndexingResult:
        """
        Index local area data (dining, activities, etc.) for a tenant.
        
        This creates the knowledge base for local recommendations.
        
        Args:
            tenant_id: The tenant to index for
            communities: Optional list of communities to filter by
        
        Returns:
            IndexingResult with counts
        """
        store = await self._get_store()
        documents = []
        by_type = {}
        
        # Index dining
        dining_docs = self._dining_to_documents(tenant_id, communities)
        documents.extend(dining_docs)
        by_type[DocType.DINING] = len(dining_docs)
        
        # Index activities
        activity_docs = self._activities_to_documents(tenant_id, communities)
        documents.extend(activity_docs)
        by_type[DocType.ACTIVITY] = len(activity_docs)
        
        # Index groceries
        grocery_docs = self._groceries_to_documents(tenant_id, communities)
        documents.extend(grocery_docs)
        by_type[DocType.GROCERY] = len(grocery_docs)
        
        # Index beach access
        beach_docs = self._beach_access_to_documents(tenant_id, communities)
        documents.extend(beach_docs)
        by_type[DocType.BEACH_ACCESS] = len(beach_docs)
        
        # Index emergency info
        emergency_docs = self._emergency_to_documents(tenant_id)
        documents.extend(emergency_docs)
        by_type[DocType.EMERGENCY] = len(emergency_docs)
        
        # Add to vector store
        result = await store.add_documents(documents)
        
        logger.info(
            f"Indexed local area for {tenant_id}: "
            f"{result['inserted']} new, {result['updated']} updated"
        )
        
        return IndexingResult(
            tenant_id=tenant_id,
            documents_indexed=result["inserted"],
            documents_updated=result["updated"],
            by_type=by_type,
            errors=[],
        )
    
    async def index_property(
        self,
        tenant_id: UUID,
        property_code: str,
        property_data: Dict[str, Any],
    ) -> IndexingResult:
        """
        Index a specific property's knowledge.
        
        Args:
            tenant_id: The tenant
            property_code: Property identifier (e.g., "SEALAVIE")
            property_data: Property details including:
                - name: Property name
                - wifi_network, wifi_password: WiFi credentials
                - door_code: Access code
                - check_in_time, check_out_time: Times
                - amenities: List of amenities
                - house_rules: Rules text or list
                - faq: List of FAQ items
                - community: Location community
        
        Returns:
            IndexingResult
        """
        store = await self._get_store()
        documents = []
        by_type = {}
        
        property_name = property_data.get("name", property_code)
        community = property_data.get("community", "")
        
        # Property info document (WiFi, codes, times)
        info_doc = self._property_info_to_document(
            tenant_id, property_code, property_name, property_data
        )
        if info_doc:
            documents.append(info_doc)
            by_type[DocType.PROPERTY_INFO] = 1
        
        # Amenities
        amenity_docs = self._amenities_to_documents(
            tenant_id, property_code, property_name, property_data
        )
        documents.extend(amenity_docs)
        by_type[DocType.PROPERTY_AMENITY] = len(amenity_docs)
        
        # House rules
        rules_docs = self._rules_to_documents(
            tenant_id, property_code, property_name, property_data
        )
        documents.extend(rules_docs)
        by_type[DocType.PROPERTY_RULES] = len(rules_docs)
        
        # FAQs
        faq_docs = self._faq_to_documents(
            tenant_id, property_code, property_name, property_data
        )
        documents.extend(faq_docs)
        by_type[DocType.PROPERTY_FAQ] = len(faq_docs)
        
        # Add to vector store
        result = await store.add_documents(documents)
        
        logger.info(
            f"Indexed property {property_code} for {tenant_id}: "
            f"{result['inserted']} new, {result['updated']} updated"
        )
        
        return IndexingResult(
            tenant_id=tenant_id,
            documents_indexed=result["inserted"],
            documents_updated=result["updated"],
            by_type=by_type,
            errors=[],
        )
    
    async def index_all_properties(
        self,
        tenant_id: UUID,
        properties: List[Dict[str, Any]],
    ) -> IndexingResult:
        """Index all properties for a tenant."""
        total_indexed = 0
        total_updated = 0
        all_by_type = {}
        errors = []
        
        for prop in properties:
            property_code = prop.get("code") or prop.get("property_code") or prop.get("id")
            if not property_code:
                errors.append(f"Property missing code: {prop.get('name', 'unknown')}")
                continue
            
            try:
                result = await self.index_property(tenant_id, property_code, prop)
                total_indexed += result.documents_indexed
                total_updated += result.documents_updated
                for doc_type, count in result.by_type.items():
                    all_by_type[doc_type] = all_by_type.get(doc_type, 0) + count
            except Exception as e:
                errors.append(f"Error indexing {property_code}: {str(e)}")
                logger.error(f"Error indexing property {property_code}: {e}")
        
        return IndexingResult(
            tenant_id=tenant_id,
            documents_indexed=total_indexed,
            documents_updated=total_updated,
            by_type=all_by_type,
            errors=errors,
        )
    
    # =========================================================================
    # Document conversion helpers
    # =========================================================================
    
    def _dining_to_documents(
        self,
        tenant_id: UUID,
        communities: Optional[List[str]] = None,
    ) -> List[Document]:
        """Convert dining places to documents."""
        documents = []
        
        for place in DINING:
            if communities and place.community not in communities:
                continue
            
            # Create rich text content
            content = self._place_to_content(place, "restaurant")
            
            documents.append(Document(
                content=content,
                metadata={
                    "tenant_id": str(tenant_id),
                    "doc_type": DocType.DINING,
                    "name": place.name,
                    "community": place.community,
                    "price_level": place.price_level,
                    "tags": place.tags,
                    "phone": place.phone,
                    "reservations": place.reservations,
                }
            ))
        
        return documents
    
    def _activities_to_documents(
        self,
        tenant_id: UUID,
        communities: Optional[List[str]] = None,
    ) -> List[Document]:
        """Convert activities to documents."""
        documents = []
        
        for place in ACTIVITIES:
            if communities and place.community not in communities:
                continue
            
            content = self._place_to_content(place, "activity")
            
            documents.append(Document(
                content=content,
                metadata={
                    "tenant_id": str(tenant_id),
                    "doc_type": DocType.ACTIVITY,
                    "name": place.name,
                    "community": place.community,
                    "tags": place.tags,
                    "phone": place.phone,
                }
            ))
        
        return documents
    
    def _groceries_to_documents(
        self,
        tenant_id: UUID,
        communities: Optional[List[str]] = None,
    ) -> List[Document]:
        """Convert grocery stores to documents."""
        documents = []
        
        for place in GROCERIES:
            if communities and place.community not in communities:
                continue
            
            content = self._place_to_content(place, "grocery store")
            
            documents.append(Document(
                content=content,
                metadata={
                    "tenant_id": str(tenant_id),
                    "doc_type": DocType.GROCERY,
                    "name": place.name,
                    "community": place.community,
                    "tags": place.tags,
                    "phone": place.phone,
                }
            ))
        
        return documents
    
    def _beach_access_to_documents(
        self,
        tenant_id: UUID,
        communities: Optional[List[str]] = None,
    ) -> List[Document]:
        """Convert beach access points to documents."""
        documents = []
        
        for beach in BEACH_ACCESS:
            if communities and beach.community not in communities:
                continue
            
            amenities_str = ", ".join(beach.amenities) if beach.amenities else "none listed"
            content = (
                f"Beach access: {beach.name} in {beach.community.replace('_', ' ').title()}. "
                f"{beach.description} "
                f"Amenities: {amenities_str}. "
                f"Parking: {beach.parking}"
            )
            
            documents.append(Document(
                content=content,
                metadata={
                    "tenant_id": str(tenant_id),
                    "doc_type": DocType.BEACH_ACCESS,
                    "name": beach.name,
                    "community": beach.community,
                    "amenities": beach.amenities,
                    "parking": beach.parking,
                }
            ))
        
        return documents
    
    def _emergency_to_documents(self, tenant_id: UUID) -> List[Document]:
        """Convert emergency services to documents."""
        documents = []
        
        for place in EMERGENCY:
            content = (
                f"Emergency/Medical: {place.name}. "
                f"{place.description} "
                f"Address: {place.address}. "
                f"Phone: {place.phone}. "
                f"Hours: {place.hours}."
            )
            
            documents.append(Document(
                content=content,
                metadata={
                    "tenant_id": str(tenant_id),
                    "doc_type": DocType.EMERGENCY,
                    "name": place.name,
                    "phone": place.phone,
                    "tags": place.tags,
                }
            ))
        
        return documents
    
    def _place_to_content(self, place: Place, place_type: str) -> str:
        """Convert a Place to searchable content string."""
        parts = [f"{place_type.title()}: {place.name}"]
        
        if place.community:
            parts.append(f"in {place.community.replace('_', ' ').title()}")
        
        if place.price_level:
            parts.append(f"({place.price_level})")
        
        parts.append(f". {place.description}")
        
        if place.phone:
            parts.append(f" Phone: {place.phone}.")
        
        if place.hours:
            parts.append(f" Hours: {place.hours}.")
        
        if place.tags:
            parts.append(f" Tags: {', '.join(place.tags)}.")
        
        if place.walkable_from:
            parts.append(f" Walkable from: {', '.join(place.walkable_from)}.")
        
        if place.reservations:
            parts.append(" Reservations recommended.")
        
        return " ".join(parts)
    
    def _property_info_to_document(
        self,
        tenant_id: UUID,
        property_code: str,
        property_name: str,
        data: Dict[str, Any],
    ) -> Optional[Document]:
        """Create property info document."""
        parts = [f"Property information for {property_name}:"]
        
        # WiFi
        wifi_network = data.get("wifi_network") or data.get("wifi", {}).get("network")
        wifi_password = data.get("wifi_password") or data.get("wifi", {}).get("password")
        if wifi_network:
            parts.append(f"WiFi network name is {wifi_network}.")
        if wifi_password:
            parts.append(f"WiFi password is {wifi_password}.")
        
        # Door code
        door_code = data.get("door_code") or data.get("access_code")
        if door_code:
            parts.append(f"Door code is {door_code}.")
        
        # Check-in/out times
        check_in = data.get("check_in_time", "4:00 PM")
        check_out = data.get("check_out_time", "10:00 AM")
        parts.append(f"Check-in time is {check_in}. Check-out time is {check_out}.")
        
        # Parking
        parking = data.get("parking") or data.get("parking_info")
        if parking:
            parts.append(f"Parking: {parking}.")
        
        # Address
        address = data.get("address")
        if address:
            parts.append(f"Address: {address}.")
        
        content = " ".join(parts)
        
        return Document(
            content=content,
            metadata={
                "tenant_id": str(tenant_id),
                "property_code": property_code,
                "doc_type": DocType.PROPERTY_INFO,
                "property_name": property_name,
                "wifi_network": wifi_network,
                "wifi_password": wifi_password,
                "door_code": door_code,
                "check_in_time": check_in,
                "check_out_time": check_out,
            }
        )
    
    def _amenities_to_documents(
        self,
        tenant_id: UUID,
        property_code: str,
        property_name: str,
        data: Dict[str, Any],
    ) -> List[Document]:
        """Create amenity documents."""
        documents = []
        amenities = data.get("amenities", [])
        
        if isinstance(amenities, list):
            for amenity in amenities:
                if isinstance(amenity, str):
                    content = f"{property_name} has this amenity: {amenity}."
                elif isinstance(amenity, dict):
                    name = amenity.get("name", "")
                    desc = amenity.get("description", "")
                    content = f"{property_name} amenity: {name}. {desc}"
                else:
                    continue
                
                documents.append(Document(
                    content=content,
                    metadata={
                        "tenant_id": str(tenant_id),
                        "property_code": property_code,
                        "doc_type": DocType.PROPERTY_AMENITY,
                        "property_name": property_name,
                    }
                ))
        
        # Also check for specific amenity flags
        amenity_flags = {
            "has_pool": "private pool",
            "has_hot_tub": "hot tub",
            "pool_heated": "heated pool (additional fee may apply)",
            "has_grill": "outdoor grill",
            "pet_friendly": "pet friendly (restrictions may apply)",
            "beach_gear": "beach gear provided",
            "bikes": "bicycles provided",
        }
        
        for key, amenity_name in amenity_flags.items():
            if data.get(key):
                content = f"{property_name} has: {amenity_name}."
                documents.append(Document(
                    content=content,
                    metadata={
                        "tenant_id": str(tenant_id),
                        "property_code": property_code,
                        "doc_type": DocType.PROPERTY_AMENITY,
                        "property_name": property_name,
                    }
                ))
        
        return documents
    
    def _rules_to_documents(
        self,
        tenant_id: UUID,
        property_code: str,
        property_name: str,
        data: Dict[str, Any],
    ) -> List[Document]:
        """Create house rules documents."""
        documents = []
        
        rules = data.get("house_rules") or data.get("rules")
        if not rules:
            return documents
        
        if isinstance(rules, str):
            content = f"House rules for {property_name}: {rules}"
            documents.append(Document(
                content=content,
                metadata={
                    "tenant_id": str(tenant_id),
                    "property_code": property_code,
                    "doc_type": DocType.PROPERTY_RULES,
                    "property_name": property_name,
                }
            ))
        elif isinstance(rules, list):
            for rule in rules:
                content = f"House rule for {property_name}: {rule}"
                documents.append(Document(
                    content=content,
                    metadata={
                        "tenant_id": str(tenant_id),
                        "property_code": property_code,
                        "doc_type": DocType.PROPERTY_RULES,
                        "property_name": property_name,
                    }
                ))
        
        return documents
    
    def _faq_to_documents(
        self,
        tenant_id: UUID,
        property_code: str,
        property_name: str,
        data: Dict[str, Any],
    ) -> List[Document]:
        """Create FAQ documents."""
        documents = []
        
        faq = data.get("faq", [])
        if not faq:
            return documents
        
        for item in faq:
            if isinstance(item, dict):
                question = item.get("question", item.get("q", ""))
                answer = item.get("answer", item.get("a", ""))
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                question, answer = item[0], item[1]
            else:
                continue
            
            if question and answer:
                content = f"FAQ for {property_name}: Q: {question} A: {answer}"
                documents.append(Document(
                    content=content,
                    metadata={
                        "tenant_id": str(tenant_id),
                        "property_code": property_code,
                        "doc_type": DocType.PROPERTY_FAQ,
                        "property_name": property_name,
                        "question": question,
                        "answer": answer,
                    }
                ))
        
        return documents


# Factory function
async def get_knowledge_indexer(session: AsyncSession) -> KnowledgeIndexer:
    """Get knowledge indexer instance."""
    return KnowledgeIndexer(session)
