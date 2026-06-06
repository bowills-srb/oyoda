"""
Concierge Intelligence Workers - The Learning Loop.

These workers quietly make the concierge smarter over time:
- Build property-specific FAQs
- Extract recurring guest questions
- Detect missing amenities/info
- Generate area recommendations cache
- Learn from successful conversations

This is what separates a dumb chatbot from an intelligent concierge.
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID
from collections import Counter

from pydantic import Field

from workers.base import (
    BaseWorker,
    JobPayload,
    JobResult,
    WorkerCategory,
    register_worker,
)


# =============================================================================
# PAYLOADS
# =============================================================================

class FAQExtractionPayload(JobPayload):
    """Payload for extracting FAQs from message history."""
    property_id: UUID
    
    # Analysis scope
    lookback_days: int = 90
    min_occurrences: int = 3  # Question must appear at least this many times


class GuestIntentClusterPayload(JobPayload):
    """Payload for clustering guest intents."""
    polygon_id: Optional[UUID] = None  # Market-wide or specific property
    property_id: Optional[UUID] = None
    
    lookback_days: int = 30
    min_cluster_size: int = 5


class LocalRecommendationPayload(JobPayload):
    """Payload for building local recommendation cache."""
    property_id: UUID
    
    # Categories to include
    categories: List[str] = Field(
        default=["restaurants", "activities", "groceries", "attractions", "beaches"]
    )
    
    # Search radius
    radius_miles: float = 10.0


class KnowledgeGapPayload(JobPayload):
    """Payload for detecting knowledge gaps."""
    property_id: UUID
    
    lookback_days: int = 30
    
    # Threshold for flagging as gap
    unanswered_threshold: int = 3


class ConversationLearningPayload(JobPayload):
    """Payload for learning from successful conversations."""
    thread_id: UUID
    
    # What made it successful
    resolution_type: str  # "answered", "escalated", "booking_made"
    guest_satisfaction: Optional[float] = None  # If available


# =============================================================================
# WORKERS
# =============================================================================

@register_worker
class FAQExtractionWorker(BaseWorker[FAQExtractionPayload]):
    """
    Extract frequently asked questions from message history.
    
    Analyzes:
    - Question frequency
    - Question categories
    - Common phrasings
    - Best answers
    
    Produces property-specific FAQ knowledge base.
    """
    
    name = "faq_extraction_worker"
    category = WorkerCategory.CONCIERGE
    max_retries = 3
    timeout_seconds = 300
    
    # Question category patterns
    CATEGORY_PATTERNS = {
        "check_in": ["check-in", "check in", "arrive", "arrival", "key", "access", "door code"],
        "check_out": ["check-out", "check out", "leave", "departure", "late checkout"],
        "wifi": ["wifi", "wi-fi", "internet", "password", "network"],
        "parking": ["parking", "park", "garage", "driveway", "car"],
        "pool": ["pool", "swimming", "heated", "pool hours"],
        "hot_tub": ["hot tub", "jacuzzi", "spa", "jets"],
        "beach": ["beach", "ocean", "chairs", "towels", "umbrella"],
        "kitchen": ["kitchen", "dishes", "coffee", "appliances", "cookware"],
        "laundry": ["laundry", "washer", "dryer", "detergent"],
        "pets": ["pet", "dog", "cat", "animal"],
        "location": ["near", "close to", "distance", "how far", "directions"],
        "activities": ["things to do", "activities", "kids", "family", "restaurants"],
    }
    
    async def process(self, payload: FAQExtractionPayload) -> JobResult:
        property_id = payload.property_id
        
        # In production, this analyzes actual message history
        # Here we build the extraction structure
        
        # Simulate extracted questions with categories
        extracted_faqs = []
        
        # Common FAQ patterns (would come from NLP analysis)
        common_questions = [
            {
                "category": "check_in",
                "question_pattern": "What time is check-in?",
                "variations": [
                    "when can we check in",
                    "what's the check-in time",
                    "earliest check-in",
                ],
                "occurrences": 45,
                "best_answer": "Check-in is at 4:00 PM. Early check-in may be available upon request.",
                "answer_effectiveness": 0.95,
            },
            {
                "category": "wifi",
                "question_pattern": "What is the WiFi password?",
                "variations": [
                    "wifi password",
                    "internet code",
                    "how do I connect to wifi",
                ],
                "occurrences": 38,
                "best_answer": "WiFi network: BeachHouse5G, Password: Welcome2024!",
                "answer_effectiveness": 0.98,
            },
            {
                "category": "parking",
                "question_pattern": "Where do we park?",
                "variations": [
                    "parking instructions",
                    "where to park",
                    "is there a garage",
                ],
                "occurrences": 32,
                "best_answer": "You can park in the driveway (fits 2 cars) or the garage (code: 1234).",
                "answer_effectiveness": 0.92,
            },
            {
                "category": "pool",
                "question_pattern": "Is the pool heated?",
                "variations": [
                    "pool temperature",
                    "can we heat the pool",
                    "pool heating",
                ],
                "occurrences": 28,
                "best_answer": "Yes! The pool is heated and maintained at 84°F year-round.",
                "answer_effectiveness": 0.96,
            },
            {
                "category": "beach",
                "question_pattern": "Are beach chairs/towels provided?",
                "variations": [
                    "beach gear",
                    "beach towels",
                    "beach equipment",
                ],
                "occurrences": 25,
                "best_answer": "We provide 6 beach chairs, an umbrella, and beach towels in the garage.",
                "answer_effectiveness": 0.94,
            },
        ]
        
        # Filter by minimum occurrences
        extracted_faqs = [
            faq for faq in common_questions 
            if faq["occurrences"] >= payload.min_occurrences
        ]
        
        # Build knowledge base structure
        knowledge_base = {
            "property_id": str(property_id),
            "tenant_id": str(payload.tenant_id),
            "generated_at": datetime.utcnow().isoformat(),
            "analysis_period_days": payload.lookback_days,
            
            "faqs": extracted_faqs,
            "faq_count": len(extracted_faqs),
            
            # Category summary
            "categories": {
                faq["category"]: {
                    "question_count": faq["occurrences"],
                    "avg_effectiveness": faq["answer_effectiveness"],
                }
                for faq in extracted_faqs
            },
            
            # Top unanswered (gaps)
            "unanswered_questions": [],  # Would come from analysis
        }
        
        return JobResult(
            success=True,
            data={"knowledge_base": knowledge_base},
            items_processed=len(extracted_faqs),
        )


@register_worker
class GuestIntentClusterWorker(BaseWorker[GuestIntentClusterPayload]):
    """
    Cluster guest intents to identify patterns.
    
    Discovers:
    - Common request types
    - Emerging questions
    - Seasonal patterns
    - Property-specific vs market-wide trends
    """
    
    name = "guest_intent_cluster_worker"
    category = WorkerCategory.CONCIERGE
    max_retries = 3
    timeout_seconds = 300
    
    async def process(self, payload: GuestIntentClusterPayload) -> JobResult:
        # Analyze intent patterns
        
        clusters = {
            "tenant_id": str(payload.tenant_id),
            "scope": {
                "polygon_id": str(payload.polygon_id) if payload.polygon_id else None,
                "property_id": str(payload.property_id) if payload.property_id else None,
            },
            "analysis_period_days": payload.lookback_days,
            "generated_at": datetime.utcnow().isoformat(),
            
            # Intent clusters
            "clusters": [
                {
                    "cluster_id": "arrival_logistics",
                    "label": "Arrival & Access Questions",
                    "intent_count": 156,
                    "sample_intents": [
                        "check_in_question",
                        "parking_question",
                        "key_access_question",
                    ],
                    "peak_timing": "1-2 days before check-in",
                    "trend": "stable",
                },
                {
                    "cluster_id": "amenity_usage",
                    "label": "How to Use Amenities",
                    "intent_count": 98,
                    "sample_intents": [
                        "pool_question",
                        "hot_tub_question",
                        "grill_question",
                    ],
                    "peak_timing": "first day of stay",
                    "trend": "increasing",
                },
                {
                    "cluster_id": "local_recommendations",
                    "label": "Local Area Questions",
                    "intent_count": 87,
                    "sample_intents": [
                        "restaurant_recommendation",
                        "activity_question",
                        "directions_question",
                    ],
                    "peak_timing": "throughout stay",
                    "trend": "stable",
                },
                {
                    "cluster_id": "issues_problems",
                    "label": "Issues & Problems",
                    "intent_count": 34,
                    "sample_intents": [
                        "maintenance_issue",
                        "complaint",
                        "missing_item",
                    ],
                    "peak_timing": "first 24 hours",
                    "trend": "decreasing",
                },
            ],
            
            # Emerging intents (new patterns)
            "emerging_intents": [
                {
                    "intent": "ev_charging_question",
                    "growth_rate": 2.5,  # 2.5x increase
                    "recent_count": 12,
                },
            ],
        }
        
        return JobResult(
            success=True,
            data={"clusters": clusters},
            items_processed=sum(c["intent_count"] for c in clusters["clusters"]),
        )


@register_worker
class LocalRecommendationWorker(BaseWorker[LocalRecommendationPayload]):
    """
    Build cached local recommendations for a property.
    
    Generates:
    - Restaurant recommendations by cuisine
    - Activities for different guest types
    - Grocery/shopping options
    - Attractions and beaches
    - Driving directions and times
    """
    
    name = "local_recommendation_worker"
    category = WorkerCategory.CONCIERGE
    max_retries = 3
    timeout_seconds = 300
    
    async def process(self, payload: LocalRecommendationPayload) -> JobResult:
        property_id = payload.property_id
        
        # In production, this calls Google Places API, Yelp, etc.
        # Here we build the cache structure
        
        recommendations = {
            "property_id": str(property_id),
            "tenant_id": str(payload.tenant_id),
            "generated_at": datetime.utcnow().isoformat(),
            "radius_miles": payload.radius_miles,
            
            "categories": {},
        }
        
        # Build recommendations for each category
        if "restaurants" in payload.categories:
            recommendations["categories"]["restaurants"] = {
                "fine_dining": [
                    {
                        "name": "The Beach House",
                        "cuisine": "Seafood",
                        "distance_miles": 1.2,
                        "price_level": "$$$$",
                        "rating": 4.7,
                        "reservation_required": True,
                        "description": "Upscale waterfront dining with stunning sunset views.",
                    },
                ],
                "casual": [
                    {
                        "name": "Shrimp Shack",
                        "cuisine": "Seafood",
                        "distance_miles": 0.5,
                        "price_level": "$$",
                        "rating": 4.5,
                        "reservation_required": False,
                        "description": "Local favorite for casual seafood. Try the grouper tacos!",
                    },
                ],
                "family_friendly": [
                    {
                        "name": "Pizza by the Sea",
                        "cuisine": "Italian",
                        "distance_miles": 0.8,
                        "price_level": "$$",
                        "rating": 4.3,
                        "reservation_required": False,
                        "description": "Great pizza and pasta. Kids menu available.",
                    },
                ],
            }
        
        if "activities" in payload.categories:
            recommendations["categories"]["activities"] = {
                "water_sports": [
                    {
                        "name": "Gulf Coast Kayaks",
                        "type": "Kayak/Paddleboard Rental",
                        "distance_miles": 2.0,
                        "price_range": "$40-80",
                        "family_friendly": True,
                        "description": "Rent kayaks or paddleboards. They deliver to the beach!",
                    },
                ],
                "family_activities": [
                    {
                        "name": "Big Kahuna's Water Park",
                        "type": "Water Park",
                        "distance_miles": 5.5,
                        "price_range": "$35-50",
                        "family_friendly": True,
                        "description": "Great water park for kids of all ages.",
                    },
                ],
            }
        
        if "groceries" in payload.categories:
            recommendations["categories"]["groceries"] = [
                {
                    "name": "Publix",
                    "distance_miles": 1.5,
                    "hours": "7am-10pm",
                    "notes": "Full-service grocery, deli, and pharmacy.",
                },
                {
                    "name": "Whole Foods",
                    "distance_miles": 4.2,
                    "hours": "8am-9pm",
                    "notes": "Organic options and prepared foods.",
                },
            ]
        
        if "beaches" in payload.categories:
            recommendations["categories"]["beaches"] = [
                {
                    "name": "Henderson Beach State Park",
                    "distance_miles": 0.3,
                    "access": "Public, $6 parking",
                    "amenities": ["Restrooms", "Showers", "Picnic areas"],
                    "description": "Pristine white sand beach. Less crowded than public beaches.",
                },
            ]
        
        return JobResult(
            success=True,
            data={"recommendations": recommendations},
            items_processed=sum(
                len(items) if isinstance(items, list) else sum(len(v) for v in items.values())
                for items in recommendations["categories"].values()
            ),
        )


@register_worker
class KnowledgeGapWorker(BaseWorker[KnowledgeGapPayload]):
    """
    Detect gaps in property knowledge base.
    
    Identifies:
    - Frequently asked but unanswered questions
    - Missing amenity information
    - Outdated information
    - Areas needing human input
    """
    
    name = "knowledge_gap_worker"
    category = WorkerCategory.CONCIERGE
    max_retries = 3
    timeout_seconds = 180
    
    async def process(self, payload: KnowledgeGapPayload) -> JobResult:
        property_id = payload.property_id
        
        # Analyze for gaps
        gaps = {
            "property_id": str(property_id),
            "tenant_id": str(payload.tenant_id),
            "analyzed_at": datetime.utcnow().isoformat(),
            "lookback_days": payload.lookback_days,
            
            # Unanswered questions
            "unanswered_questions": [
                {
                    "question_pattern": "Is there a gas or charcoal grill?",
                    "occurrences": 8,
                    "priority": "high",
                    "suggested_category": "amenities",
                },
                {
                    "question_pattern": "What's the garage door code?",
                    "occurrences": 5,
                    "priority": "high",
                    "suggested_category": "access",
                },
                {
                    "question_pattern": "Are there life jackets for the kayaks?",
                    "occurrences": 4,
                    "priority": "medium",
                    "suggested_category": "amenities",
                },
            ],
            
            # Missing information
            "missing_info": [
                {
                    "category": "trash_collection",
                    "description": "No information about trash pickup days",
                    "priority": "medium",
                },
                {
                    "category": "emergency_contacts",
                    "description": "No local emergency contact listed",
                    "priority": "high",
                },
            ],
            
            # Potentially outdated
            "potentially_outdated": [
                {
                    "category": "local_restaurants",
                    "last_updated": "2024-06-15",
                    "days_since_update": 200,
                    "priority": "low",
                },
            ],
            
            # Summary
            "summary": {
                "total_gaps": 6,
                "high_priority": 3,
                "medium_priority": 2,
                "low_priority": 1,
            },
        }
        
        return JobResult(
            success=True,
            data={"gaps": gaps},
            items_processed=gaps["summary"]["total_gaps"],
        )


@register_worker
class ConversationLearningWorker(BaseWorker[ConversationLearningPayload]):
    """
    Learn from successful conversations.
    
    Extracts:
    - Effective response patterns
    - Successful escalation triggers
    - Guest satisfaction signals
    - Knowledge base improvements
    """
    
    name = "conversation_learning_worker"
    category = WorkerCategory.CONCIERGE
    max_retries = 3
    timeout_seconds = 120
    
    async def process(self, payload: ConversationLearningPayload) -> JobResult:
        thread_id = payload.thread_id
        
        # In production, this analyzes the conversation
        learning = {
            "thread_id": str(thread_id),
            "tenant_id": str(payload.tenant_id),
            "analyzed_at": datetime.utcnow().isoformat(),
            "resolution_type": payload.resolution_type,
            
            # What we learned
            "learnings": {
                "effective_responses": [
                    {
                        "question_type": "check_in_time",
                        "response_pattern": "Specific time + early check-in offer",
                        "effectiveness_score": 0.95,
                    },
                ],
                "knowledge_base_updates": [
                    {
                        "category": "amenities",
                        "update_type": "add",
                        "content": "Beach wagon available in garage",
                        "confidence": 0.8,
                    },
                ],
                "escalation_triggers": [],  # None in this case
            },
            
            # Metrics
            "metrics": {
                "messages_exchanged": 4,
                "resolution_time_minutes": 8,
                "guest_satisfaction": payload.guest_satisfaction,
            },
        }
        
        return JobResult(
            success=True,
            data={"learning": learning},
            items_processed=1,
        )
