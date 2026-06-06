"""
Knowledge Indexer

Indexes data into the vector store for retrieval.
Converts existing data sources into searchable documents.

Sources:
- local_area_data.py (restaurants, activities, beaches)
- property_context.py (property details)
- Database tables (properties, amenities)

Usage:
    indexer = KnowledgeIndexer()
    
    # Index all local area data for an operator
    indexer.index_local_area_data("op_beach_habitats")
    
    # Index a specific property
    indexer.index_property("op_beach_habitats", "SEALAVY")
"""

import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from .vector_store import VectorStore, Document, get_vector_store

# Import local area data
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))

logger = logging.getLogger(__name__)


@dataclass
class IndexingResult:
    """Result of an indexing operation."""
    documents_indexed: int
    operator_id: str
    source: str
    errors: List[str] = None
    
    def __post_init__(self):
        if self.errors is None:
            self.errors = []


class KnowledgeIndexer:
    """
    Indexes knowledge into the vector store.
    
    Responsible for:
    - Converting raw data to searchable documents
    - Chunking large content appropriately
    - Adding proper metadata for filtering
    """
    
    def __init__(self, vector_store: VectorStore = None):
        self.vector_store = vector_store or get_vector_store()
    
    def index_local_area_data(self, operator_id: str) -> IndexingResult:
        """
        Index all local area data (restaurants, activities, etc).
        
        This pulls from services/local_area_data.py
        """
        documents = []
        
        try:
            # Import local area data
            from services.local_area_data import (
                DINING, ACTIVITIES, GROCERIES, EMERGENCY, BEACH_ACCESS
            )
            
            # Index restaurants
            for place in DINING:
                doc = Document(
                    content=self._format_restaurant(place),
                    metadata={
                        "operator_id": operator_id,
                        "doc_type": "restaurant",
                        "name": place.name,
                        "community": place.community,
                        "price_level": place.price_level,
                        "tags": place.tags,
                    }
                )
                documents.append(doc)
            
            # Index activities
            for place in ACTIVITIES:
                doc = Document(
                    content=self._format_activity(place),
                    metadata={
                        "operator_id": operator_id,
                        "doc_type": "activity",
                        "name": place.name,
                        "community": place.community,
                        "tags": place.tags,
                    }
                )
                documents.append(doc)
            
            # Index groceries
            for place in GROCERIES:
                doc = Document(
                    content=self._format_grocery(place),
                    metadata={
                        "operator_id": operator_id,
                        "doc_type": "grocery",
                        "name": place.name,
                        "community": place.community,
                    }
                )
                documents.append(doc)
            
            # Index emergency services
            for place in EMERGENCY:
                doc = Document(
                    content=self._format_emergency(place),
                    metadata={
                        "operator_id": operator_id,
                        "doc_type": "emergency",
                        "name": place.name,
                    }
                )
                documents.append(doc)
            
            # Index beach access
            for beach in BEACH_ACCESS:
                doc = Document(
                    content=self._format_beach_access(beach),
                    metadata={
                        "operator_id": operator_id,
                        "doc_type": "beach_access",
                        "name": beach.name,
                        "community": beach.community,
                    }
                )
                documents.append(doc)
            
            # Add to vector store
            count = self.vector_store.add_documents(documents)
            
            logger.info(f"Indexed {count} local area documents for {operator_id}")
            
            return IndexingResult(
                documents_indexed=count,
                operator_id=operator_id,
                source="local_area_data"
            )
            
        except Exception as e:
            logger.error(f"Error indexing local area data: {e}")
            return IndexingResult(
                documents_indexed=0,
                operator_id=operator_id,
                source="local_area_data",
                errors=[str(e)]
            )
    
    def index_property(
        self,
        operator_id: str,
        property_code: str,
        property_data: Dict[str, Any] = None,
    ) -> IndexingResult:
        """
        Index a single property's details.
        
        Can accept property_data dict or will load from database.
        """
        documents = []
        
        try:
            # Load property data if not provided
            if property_data is None:
                from app.services.concierge.property_context import get_property_context
                ctx = get_property_context(property_code)
                if ctx is None:
                    return IndexingResult(
                        documents_indexed=0,
                        operator_id=operator_id,
                        source=f"property:{property_code}",
                        errors=[f"Property {property_code} not found"]
                    )
                property_data = self._context_to_dict(ctx)
            
            # Property overview
            documents.append(Document(
                content=self._format_property_overview(property_data),
                metadata={
                    "operator_id": operator_id,
                    "property_code": property_code,
                    "doc_type": "property",
                }
            ))
            
            # WiFi info
            if property_data.get("wifi_network"):
                documents.append(Document(
                    content=f"WiFi network name: {property_data['wifi_network']}. WiFi password: {property_data.get('wifi_password', 'See property guide')}.",
                    metadata={
                        "operator_id": operator_id,
                        "property_code": property_code,
                        "doc_type": "wifi",
                    }
                ))
            
            # Check-in info
            documents.append(Document(
                content=f"Check-in time is {property_data.get('check_in_time', '4:00 PM')}. {property_data.get('check_in_instructions', '')}",
                metadata={
                    "operator_id": operator_id,
                    "property_code": property_code,
                    "doc_type": "checkin",
                }
            ))
            
            # Check-out info
            documents.append(Document(
                content=f"Check-out time is {property_data.get('check_out_time', '10:00 AM')}. {property_data.get('check_out_instructions', '')}",
                metadata={
                    "operator_id": operator_id,
                    "property_code": property_code,
                    "doc_type": "checkout",
                }
            ))
            
            # Amenities
            amenities = self._format_amenities(property_data)
            if amenities:
                documents.append(Document(
                    content=amenities,
                    metadata={
                        "operator_id": operator_id,
                        "property_code": property_code,
                        "doc_type": "amenity",
                    }
                ))
            
            # Add to vector store
            count = self.vector_store.add_documents(documents)
            
            logger.info(f"Indexed {count} documents for property {property_code}")
            
            return IndexingResult(
                documents_indexed=count,
                operator_id=operator_id,
                source=f"property:{property_code}"
            )
            
        except Exception as e:
            logger.error(f"Error indexing property {property_code}: {e}")
            return IndexingResult(
                documents_indexed=0,
                operator_id=operator_id,
                source=f"property:{property_code}",
                errors=[str(e)]
            )
    
    def index_all_properties(self, operator_id: str) -> IndexingResult:
        """Index all properties for an operator."""
        try:
            from app.services.concierge.property_context import DATABASE_URL
            import psycopg2
            from psycopg2.extras import RealDictCursor
            
            conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
            cur = conn.cursor()
            
            cur.execute("SELECT property_code FROM properties WHERE property_code IS NOT NULL")
            rows = cur.fetchall()
            
            cur.close()
            conn.close()
            
            total_indexed = 0
            errors = []
            
            for row in rows:
                property_code = row["property_code"]
                result = self.index_property(operator_id, property_code)
                total_indexed += result.documents_indexed
                errors.extend(result.errors)
            
            logger.info(f"Indexed {total_indexed} documents for {len(rows)} properties")
            
            return IndexingResult(
                documents_indexed=total_indexed,
                operator_id=operator_id,
                source="all_properties",
                errors=errors if errors else None
            )
            
        except Exception as e:
            logger.error(f"Error indexing all properties: {e}")
            return IndexingResult(
                documents_indexed=0,
                operator_id=operator_id,
                source="all_properties",
                errors=[str(e)]
            )
    
    def index_faq(
        self,
        operator_id: str,
        faqs: List[Dict[str, str]],
        property_code: Optional[str] = None,
    ) -> IndexingResult:
        """
        Index FAQ entries.
        
        Args:
            faqs: List of {"question": "...", "answer": "..."} dicts
        """
        documents = []
        
        for faq in faqs:
            # Index both Q and A together for better retrieval
            content = f"Q: {faq['question']} A: {faq['answer']}"
            
            documents.append(Document(
                content=content,
                metadata={
                    "operator_id": operator_id,
                    "property_code": property_code,
                    "doc_type": "faq",
                    "question": faq["question"],
                }
            ))
        
        count = self.vector_store.add_documents(documents)
        
        return IndexingResult(
            documents_indexed=count,
            operator_id=operator_id,
            source="faq"
        )
    
    # =========================================================================
    # Formatting helpers
    # =========================================================================
    
    def _format_restaurant(self, place) -> str:
        """Format a restaurant for indexing."""
        parts = [
            f"{place.name} is a restaurant in {place.community.replace('_', ' ').title()}.",
            place.description,
        ]
        if place.price_level:
            parts.append(f"Price: {place.price_level}.")
        if place.phone:
            parts.append(f"Phone: {place.phone}.")
        if place.hours:
            parts.append(f"Hours: {place.hours}.")
        if place.reservations:
            parts.append("Reservations recommended.")
        if place.tags:
            parts.append(f"Known for: {', '.join(place.tags)}.")
        
        return " ".join(parts)
    
    def _format_activity(self, place) -> str:
        """Format an activity for indexing."""
        parts = [
            f"{place.name} is an activity/attraction in {place.community.replace('_', ' ').title()}.",
            place.description,
        ]
        if place.phone:
            parts.append(f"Phone: {place.phone}.")
        if place.hours:
            parts.append(f"Hours: {place.hours}.")
        if place.tags:
            parts.append(f"Good for: {', '.join(place.tags)}.")
        
        return " ".join(parts)
    
    def _format_grocery(self, place) -> str:
        """Format a grocery store for indexing."""
        parts = [
            f"{place.name} is a grocery/market.",
            place.description,
            f"Address: {place.address}.",
        ]
        if place.phone:
            parts.append(f"Phone: {place.phone}.")
        if place.hours:
            parts.append(f"Hours: {place.hours}.")
        
        return " ".join(parts)
    
    def _format_emergency(self, place) -> str:
        """Format emergency service for indexing."""
        parts = [
            f"{place.name} - {place.category}.",
            place.description,
            f"Address: {place.address}.",
        ]
        if place.phone:
            parts.append(f"Phone: {place.phone}.")
        if place.hours:
            parts.append(f"Hours: {place.hours}.")
        
        return " ".join(parts)
    
    def _format_beach_access(self, beach) -> str:
        """Format beach access for indexing."""
        parts = [
            f"{beach.name} beach access in {beach.community.replace('_', ' ').title()}.",
            beach.description,
            f"Parking: {beach.parking}.",
        ]
        if beach.amenities:
            parts.append(f"Amenities: {', '.join(beach.amenities)}.")
        
        return " ".join(parts)
    
    def _format_property_overview(self, data: Dict[str, Any]) -> str:
        """Format property overview for indexing."""
        parts = [
            f"{data.get('property_name', 'This property')} is located in {data.get('community', 'the area')}.",
            f"It has {data.get('bedrooms', 0)} bedrooms and {data.get('bathrooms', 0)} bathrooms.",
            f"Sleeps {data.get('sleeps', 0)} guests.",
        ]
        return " ".join(parts)
    
    def _format_amenities(self, data: Dict[str, Any]) -> str:
        """Format amenities for indexing."""
        amenities = []
        
        if data.get("has_pool"):
            heated = " (can be heated)" if data.get("pool_heated") else ""
            amenities.append(f"private pool{heated}")
        if data.get("has_hot_tub"):
            amenities.append("hot tub")
        if data.get("has_grill"):
            amenities.append("grill/BBQ")
        if data.get("has_bikes"):
            count = data.get("bike_count", "")
            amenities.append(f"{count} bikes" if count else "bikes")
        if data.get("has_beach_gear"):
            amenities.append("beach gear provided")
        if data.get("has_washer_dryer"):
            amenities.append("washer and dryer")
        
        if not amenities:
            return ""
        
        return f"This property has: {', '.join(amenities)}."
    
    def _context_to_dict(self, ctx) -> Dict[str, Any]:
        """Convert PropertyContext dataclass to dict."""
        return {
            "property_code": ctx.property_code,
            "property_name": ctx.property_name,
            "community": ctx.community,
            "bedrooms": ctx.bedrooms,
            "bathrooms": ctx.bathrooms,
            "sleeps": ctx.sleeps,
            "wifi_network": ctx.wifi_network,
            "wifi_password": ctx.wifi_password,
            "check_in_time": ctx.check_in_time,
            "check_out_time": ctx.check_out_time,
            "check_in_instructions": ctx.check_in_instructions,
            "check_out_instructions": ctx.check_out_instructions,
            "has_pool": ctx.has_pool,
            "pool_heated": ctx.pool_heated,
            "has_hot_tub": ctx.has_hot_tub,
            "has_grill": ctx.has_grill,
            "has_bikes": ctx.has_bikes,
            "bike_count": ctx.bike_count,
            "has_beach_gear": ctx.has_beach_gear,
            "has_washer_dryer": ctx.has_washer_dryer,
        }


# Convenience function
def index_operator_knowledge(operator_id: str) -> Dict[str, IndexingResult]:
    """
    Index all knowledge for an operator.
    
    This is the main entry point for setting up a new operator.
    """
    indexer = KnowledgeIndexer()
    
    results = {}
    
    # Index local area data
    results["local_area"] = indexer.index_local_area_data(operator_id)
    
    # Index all properties
    results["properties"] = indexer.index_all_properties(operator_id)
    
    total = sum(r.documents_indexed for r in results.values())
    logger.info(f"Total indexed for {operator_id}: {total} documents")
    
    return results
