"""
Guest Messaging Intelligence Service.

Ingests guest messaging data from PMS to build property-specific
knowledge bases for the voice concierge.

CRITICAL PRIVACY REQUIREMENTS:
1. Permissioned access only (operator must authorize)
2. PII scrubbing (remove names, emails, phones, payment info)
3. Encryption at rest (tenant-isolated)
4. Access audit trails
5. Data minimization (store only what's needed)

What We Store:
✅ Message intent/topic
✅ Property reference
✅ Timestamp
✅ Answer templates
✅ Topic frequency

What We DO NOT Store:
❌ Guest personal data
❌ Payment info
❌ Email addresses
❌ Phone numbers
❌ Raw sensitive content
"""

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# =============================================================================
# MESSAGE TOPICS / INTENTS
# =============================================================================

class MessageTopic(str, Enum):
    """
    Base taxonomy of message topics.
    
    NOTE: This is a SEED taxonomy, not a hard-coded list.
    The system allows market-specific topic emergence via AdaptiveTopicEngine.
    
    Topics have:
    - Time decay (older topics matter less)
    - Geo-fence relevance (Aspen != Orlando)
    - Market class modifiers (luxury != budget)
    """
    # Access & Check-in
    CHECK_IN = "check_in"
    CHECK_OUT = "check_out"
    KEY_ACCESS = "key_access"
    DOOR_CODE = "door_code"
    EARLY_CHECK_IN = "early_check_in"
    LATE_CHECK_OUT = "late_check_out"
    
    # Property Features
    WIFI = "wifi"
    PARKING = "parking"
    POOL = "pool"
    HOT_TUB = "hot_tub"
    BEACH_ACCESS = "beach_access"
    GRILL = "grill"
    
    # Appliances & Amenities
    WASHER_DRYER = "washer_dryer"
    DISHWASHER = "dishwasher"
    COFFEE_MAKER = "coffee_maker"
    TV_ENTERTAINMENT = "tv_entertainment"
    AC_HEATING = "ac_heating"
    
    # Location & Directions
    DIRECTIONS = "directions"
    NEARBY_RESTAURANTS = "nearby_restaurants"
    NEARBY_ATTRACTIONS = "nearby_attractions"
    GROCERY_STORES = "grocery_stores"
    
    # Issues & Maintenance
    MAINTENANCE_REQUEST = "maintenance_request"
    CLEANING_ISSUE = "cleaning_issue"
    NOISE_COMPLAINT = "noise_complaint"
    BROKEN_ITEM = "broken_item"
    
    # Policies
    PET_POLICY = "pet_policy"
    SMOKING_POLICY = "smoking_policy"
    QUIET_HOURS = "quiet_hours"
    MAX_OCCUPANCY = "max_occupancy"
    CANCELLATION = "cancellation"
    
    # Billing & Payment
    PAYMENT_QUESTION = "payment_question"
    SECURITY_DEPOSIT = "security_deposit"
    DAMAGE_REPORT = "damage_report"
    
    # General
    THANK_YOU = "thank_you"
    COMPLAINT = "complaint"
    COMPLIMENT = "compliment"
    OTHER = "other"


class MessageSender(str, Enum):
    """Who sent the message."""
    GUEST = "guest"
    HOST = "host"
    SYSTEM = "system"


class MessagePriority(str, Enum):
    """Message priority for response."""
    URGENT = "urgent"  # Safety, access issues
    HIGH = "high"  # Check-in problems, maintenance
    NORMAL = "normal"  # General questions
    LOW = "low"  # Thank you, compliments


# =============================================================================
# PII PATTERNS FOR SCRUBBING
# =============================================================================

class PIIPatterns:
    """Regex patterns for detecting and scrubbing PII."""
    
    # Email addresses
    EMAIL = re.compile(
        r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
        re.IGNORECASE
    )
    
    # Phone numbers (various formats)
    PHONE = re.compile(
        r'''
        (?:
            (?:\+?1[-.\s]?)?  # Country code
            (?:\(?\d{3}\)?[-.\s]?)  # Area code
            \d{3}[-.\s]?\d{4}  # Number
        )|
        (?:\d{3}[-.\s]\d{3}[-.\s]\d{4})  # Simple format
        ''',
        re.VERBOSE
    )
    
    # Credit card numbers (basic)
    CREDIT_CARD = re.compile(
        r'\b(?:\d{4}[-\s]?){3}\d{4}\b'
    )
    
    # SSN
    SSN = re.compile(
        r'\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b'
    )
    
    # Common name patterns (Mr./Mrs./Ms. followed by name)
    TITLE_NAME = re.compile(
        r'\b(?:Mr\.|Mrs\.|Ms\.|Miss|Dr\.)\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?',
        re.IGNORECASE
    )
    
    # Addresses (basic street address pattern)
    STREET_ADDRESS = re.compile(
        r'\b\d+\s+(?:[A-Za-z]+\s+){1,3}(?:St|Street|Ave|Avenue|Rd|Road|Blvd|Boulevard|Dr|Drive|Ln|Lane|Way|Ct|Court)\b',
        re.IGNORECASE
    )


# =============================================================================
# RAW MESSAGE (Before Processing)
# =============================================================================

class RawGuestMessage(BaseModel):
    """
    Raw message from PMS before PII scrubbing.
    
    This is NEVER stored - only processed in memory.
    """
    message_id: str
    listing_id: str
    reservation_id: Optional[str] = None
    
    # Content
    content: str
    sender_type: MessageSender
    
    # Timing
    sent_at: datetime
    
    # Optional metadata from PMS
    thread_id: Optional[str] = None
    is_automated: bool = False


# =============================================================================
# PROCESSED MESSAGE (After PII Scrubbing)
# =============================================================================

class ProcessedMessage(BaseModel):
    """
    Message after PII scrubbing and topic extraction.
    
    This is what gets stored (encrypted).
    """
    message_id: UUID = Field(default_factory=uuid4)
    company_id: UUID
    listing_id: str
    
    # Extracted topic (not raw content)
    topic: MessageTopic
    subtopics: List[str] = Field(default_factory=list)
    
    # Sanitized content (PII removed)
    sanitized_content: str
    
    # Metadata
    sender_type: MessageSender
    sent_at: datetime
    priority: MessagePriority = MessagePriority.NORMAL
    
    # For FAQ building
    is_question: bool = False
    has_resolution: bool = False
    resolution_topic: Optional[str] = None
    
    # Processing metadata
    processed_at: datetime = Field(default_factory=datetime.utcnow)
    pii_removed: List[str] = Field(default_factory=list)  # Types of PII found


# =============================================================================
# PROPERTY FAQ ENTRY
# =============================================================================

class PropertyFAQEntry(BaseModel):
    """
    A FAQ entry for a specific property.
    
    Built from analyzing guest messages over time.
    """
    faq_id: UUID = Field(default_factory=uuid4)
    company_id: UUID
    listing_id: str
    
    # Question/Answer
    topic: MessageTopic
    question_template: str  # Generic version of common question
    answer_template: str  # Property-specific answer
    
    # Frequency/importance
    times_asked: int = 1
    last_asked: datetime = Field(default_factory=datetime.utcnow)
    
    # Quality
    confidence: float = 0.5  # How confident we are in this answer
    verified_by_host: bool = False
    
    # Voice agent can use this
    voice_enabled: bool = True


# =============================================================================
# PROPERTY KNOWLEDGE BASE
# =============================================================================

class PropertyKnowledgeBase(BaseModel):
    """
    Complete knowledge base for a property.
    
    Used by the voice concierge to answer property-specific questions.
    """
    company_id: UUID
    listing_id: str
    
    # FAQ entries by topic
    faqs: Dict[str, List[PropertyFAQEntry]] = Field(default_factory=dict)
    
    # Quick answers (high-confidence, frequently asked)
    quick_answers: Dict[str, str] = Field(default_factory=dict)
    
    # Topic statistics
    topic_frequency: Dict[str, int] = Field(default_factory=dict)
    
    # Metadata
    total_messages_analyzed: int = 0
    last_updated: datetime = Field(default_factory=datetime.utcnow)
    
    # Voice agent settings
    voice_enabled_topics: Set[str] = Field(default_factory=set)


# =============================================================================
# PII SCRUBBER
# =============================================================================

class PIIScrubber:
    """
    Scrubs PII from guest messages.
    
    Replaces sensitive data with placeholders.
    """
    
    REPLACEMENTS = {
        "email": "[EMAIL]",
        "phone": "[PHONE]",
        "credit_card": "[CARD]",
        "ssn": "[SSN]",
        "name": "[NAME]",
        "address": "[ADDRESS]",
    }
    
    @classmethod
    def scrub(cls, text: str) -> Tuple[str, List[str]]:
        """
        Scrub PII from text.
        
        Returns:
            (scrubbed_text, list_of_pii_types_found)
        """
        pii_found = []
        result = text
        
        # Email
        if PIIPatterns.EMAIL.search(result):
            result = PIIPatterns.EMAIL.sub(cls.REPLACEMENTS["email"], result)
            pii_found.append("email")
        
        # Phone
        if PIIPatterns.PHONE.search(result):
            result = PIIPatterns.PHONE.sub(cls.REPLACEMENTS["phone"], result)
            pii_found.append("phone")
        
        # Credit card
        if PIIPatterns.CREDIT_CARD.search(result):
            result = PIIPatterns.CREDIT_CARD.sub(cls.REPLACEMENTS["credit_card"], result)
            pii_found.append("credit_card")
        
        # SSN
        if PIIPatterns.SSN.search(result):
            result = PIIPatterns.SSN.sub(cls.REPLACEMENTS["ssn"], result)
            pii_found.append("ssn")
        
        # Names with titles
        if PIIPatterns.TITLE_NAME.search(result):
            result = PIIPatterns.TITLE_NAME.sub(cls.REPLACEMENTS["name"], result)
            pii_found.append("name")
        
        # Street addresses
        if PIIPatterns.STREET_ADDRESS.search(result):
            result = PIIPatterns.STREET_ADDRESS.sub(cls.REPLACEMENTS["address"], result)
            pii_found.append("address")
        
        return result, pii_found


# =============================================================================
# TOPIC EXTRACTOR
# =============================================================================

class TopicExtractor:
    """
    Extracts topic/intent from guest messages.
    
    Uses keyword matching (could be upgraded to ML later).
    """
    
    # Keyword -> Topic mapping
    TOPIC_KEYWORDS: Dict[MessageTopic, List[str]] = {
        MessageTopic.CHECK_IN: [
            "check in", "check-in", "checkin", "arrive", "arrival",
            "what time", "when can", "early arrival"
        ],
        MessageTopic.CHECK_OUT: [
            "check out", "check-out", "checkout", "leave", "leaving",
            "departure", "late checkout"
        ],
        MessageTopic.KEY_ACCESS: [
            "key", "keys", "lockbox", "lock box", "keypad", "access code",
            "door code", "entry", "get in", "unlock"
        ],
        MessageTopic.WIFI: [
            "wifi", "wi-fi", "internet", "password", "network", "connect"
        ],
        MessageTopic.PARKING: [
            "park", "parking", "car", "garage", "driveway", "street parking"
        ],
        MessageTopic.POOL: [
            "pool", "swimming", "swim", "heated pool", "pool hours"
        ],
        MessageTopic.HOT_TUB: [
            "hot tub", "jacuzzi", "spa", "whirlpool"
        ],
        MessageTopic.BEACH_ACCESS: [
            "beach", "ocean", "sand", "beach access", "beach chairs", "towels"
        ],
        MessageTopic.WASHER_DRYER: [
            "washer", "dryer", "laundry", "wash clothes", "washing machine"
        ],
        MessageTopic.AC_HEATING: [
            "air conditioning", "ac", "a/c", "heat", "heating", "thermostat",
            "temperature", "cold", "hot", "warm"
        ],
        MessageTopic.TV_ENTERTAINMENT: [
            "tv", "television", "netflix", "streaming", "cable", "remote"
        ],
        MessageTopic.DIRECTIONS: [
            "directions", "how to get", "address", "gps", "navigate"
        ],
        MessageTopic.NEARBY_RESTAURANTS: [
            "restaurant", "food", "eat", "dining", "breakfast", "dinner"
        ],
        MessageTopic.GROCERY_STORES: [
            "grocery", "groceries", "store", "supermarket", "publix", "walmart"
        ],
        MessageTopic.MAINTENANCE_REQUEST: [
            "broken", "not working", "fix", "repair", "maintenance", "issue"
        ],
        MessageTopic.CLEANING_ISSUE: [
            "clean", "dirty", "stain", "trash", "garbage", "housekeeping"
        ],
        MessageTopic.PET_POLICY: [
            "pet", "dog", "cat", "animal", "pets allowed"
        ],
        MessageTopic.SMOKING_POLICY: [
            "smoke", "smoking", "cigarette", "vape"
        ],
        MessageTopic.QUIET_HOURS: [
            "quiet", "noise", "loud", "party", "neighbors"
        ],
        MessageTopic.THANK_YOU: [
            "thank", "thanks", "appreciate", "great stay", "wonderful"
        ],
        MessageTopic.COMPLAINT: [
            "complaint", "disappointed", "unhappy", "problem", "terrible"
        ],
    }
    
    # Priority keywords
    URGENT_KEYWORDS = [
        "emergency", "urgent", "locked out", "can't get in", "no power",
        "flooding", "fire", "safety", "help"
    ]
    
    HIGH_PRIORITY_KEYWORDS = [
        "broken", "not working", "problem", "issue", "check-in",
        "can't", "won't", "doesn't work"
    ]
    
    @classmethod
    def extract_topic(cls, text: str) -> Tuple[MessageTopic, List[str], MessagePriority]:
        """
        Extract topic, subtopics, and priority from message text.
        
        Returns:
            (primary_topic, subtopics, priority)
        """
        text_lower = text.lower()
        
        # Check priority first
        priority = MessagePriority.NORMAL
        if any(kw in text_lower for kw in cls.URGENT_KEYWORDS):
            priority = MessagePriority.URGENT
        elif any(kw in text_lower for kw in cls.HIGH_PRIORITY_KEYWORDS):
            priority = MessagePriority.HIGH
        
        # Find matching topics
        matched_topics = []
        for topic, keywords in cls.TOPIC_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
                matched_topics.append(topic)
        
        if not matched_topics:
            return MessageTopic.OTHER, [], priority
        
        # Primary topic is first match, rest are subtopics
        primary = matched_topics[0]
        subtopics = [t.value for t in matched_topics[1:]]
        
        return primary, subtopics, priority
    
    @classmethod
    def is_question(cls, text: str) -> bool:
        """Check if message is a question."""
        question_indicators = [
            "?", "where", "what", "when", "how", "can i", "can we",
            "is there", "are there", "do you", "does", "could"
        ]
        text_lower = text.lower()
        return any(ind in text_lower for ind in question_indicators)


# =============================================================================
# GUEST MESSAGING SERVICE
# =============================================================================

class GuestMessagingService:
    """
    Main service for guest messaging intelligence.
    
    Handles:
    1. Message ingestion from PMS
    2. PII scrubbing
    3. Topic extraction
    4. Knowledge base building
    5. FAQ generation
    """
    
    def __init__(self, company_id: UUID):
        self.company_id = company_id
        self._processed_messages: List[ProcessedMessage] = []
        self._knowledge_bases: Dict[str, PropertyKnowledgeBase] = {}
    
    def process_message(
        self,
        raw_message: RawGuestMessage,
    ) -> ProcessedMessage:
        """
        Process a raw message: scrub PII, extract topic, store.
        """
        # Step 1: Scrub PII
        sanitized, pii_found = PIIScrubber.scrub(raw_message.content)
        
        # Step 2: Extract topic
        topic, subtopics, priority = TopicExtractor.extract_topic(sanitized)
        
        # Step 3: Check if question
        is_question = TopicExtractor.is_question(sanitized)
        
        # Step 4: Create processed message
        processed = ProcessedMessage(
            company_id=self.company_id,
            listing_id=raw_message.listing_id,
            topic=topic,
            subtopics=subtopics,
            sanitized_content=sanitized,
            sender_type=raw_message.sender_type,
            sent_at=raw_message.sent_at,
            priority=priority,
            is_question=is_question,
            pii_removed=pii_found,
        )
        
        self._processed_messages.append(processed)
        
        # Step 5: Update knowledge base
        self._update_knowledge_base(processed)
        
        return processed
    
    def process_messages_batch(
        self,
        raw_messages: List[RawGuestMessage],
    ) -> List[ProcessedMessage]:
        """Process a batch of messages."""
        return [self.process_message(m) for m in raw_messages]
    
    def _update_knowledge_base(self, message: ProcessedMessage) -> None:
        """Update property knowledge base with new message."""
        listing_id = message.listing_id
        
        # Get or create knowledge base
        if listing_id not in self._knowledge_bases:
            self._knowledge_bases[listing_id] = PropertyKnowledgeBase(
                company_id=self.company_id,
                listing_id=listing_id,
            )
        
        kb = self._knowledge_bases[listing_id]
        
        # Update topic frequency
        topic_key = message.topic.value
        kb.topic_frequency[topic_key] = kb.topic_frequency.get(topic_key, 0) + 1
        
        # Update total
        kb.total_messages_analyzed += 1
        kb.last_updated = datetime.utcnow()
    
    def get_knowledge_base(self, listing_id: str) -> Optional[PropertyKnowledgeBase]:
        """Get knowledge base for a property."""
        return self._knowledge_bases.get(listing_id)
    
    def build_faq(
        self,
        listing_id: str,
        min_frequency: int = 2,
    ) -> List[PropertyFAQEntry]:
        """
        Build FAQ entries for a property based on message history.
        
        Args:
            listing_id: Property to build FAQ for
            min_frequency: Minimum times a topic must appear
            
        Returns:
            List of FAQ entries
        """
        kb = self._knowledge_bases.get(listing_id)
        if not kb:
            return []
        
        faqs = []
        
        # Get questions for this listing
        questions = [
            m for m in self._processed_messages
            if m.listing_id == listing_id and m.is_question
        ]
        
        # Group by topic
        by_topic: Dict[str, List[ProcessedMessage]] = {}
        for q in questions:
            topic_key = q.topic.value
            if topic_key not in by_topic:
                by_topic[topic_key] = []
            by_topic[topic_key].append(q)
        
        # Create FAQ entries for frequent topics
        for topic_key, messages in by_topic.items():
            if len(messages) >= min_frequency:
                # Create generic question template
                question_template = self._generate_question_template(
                    MessageTopic(topic_key)
                )
                
                faqs.append(PropertyFAQEntry(
                    company_id=self.company_id,
                    listing_id=listing_id,
                    topic=MessageTopic(topic_key),
                    question_template=question_template,
                    answer_template="",  # Host needs to provide
                    times_asked=len(messages),
                    confidence=0.3,  # Low until host verifies
                ))
        
        return faqs
    
    def _generate_question_template(self, topic: MessageTopic) -> str:
        """Generate a generic question template for a topic."""
        templates = {
            MessageTopic.WIFI: "What is the WiFi password?",
            MessageTopic.PARKING: "Where can I park?",
            MessageTopic.POOL: "What are the pool hours?",
            MessageTopic.CHECK_IN: "What time is check-in?",
            MessageTopic.CHECK_OUT: "What time is check-out?",
            MessageTopic.KEY_ACCESS: "How do I access the property?",
            MessageTopic.BEACH_ACCESS: "How do I get to the beach?",
            MessageTopic.WASHER_DRYER: "Is there a washer and dryer?",
            MessageTopic.AC_HEATING: "How do I adjust the thermostat?",
            MessageTopic.GRILL: "Is there a grill I can use?",
        }
        return templates.get(topic, f"Question about {topic.value}")
    
    def get_voice_context(
        self,
        listing_id: str,
        topic: Optional[MessageTopic] = None,
    ) -> Dict[str, Any]:
        """
        Get voice-ready context for a property.
        
        This is what the voice concierge uses to answer questions.
        """
        kb = self._knowledge_bases.get(listing_id)
        if not kb:
            return {
                "has_knowledge": False,
                "listing_id": listing_id,
            }
        
        context = {
            "has_knowledge": True,
            "listing_id": listing_id,
            "total_messages_analyzed": kb.total_messages_analyzed,
            "top_topics": sorted(
                kb.topic_frequency.items(),
                key=lambda x: x[1],
                reverse=True
            )[:5],
        }
        
        # Add quick answers if available
        if topic and topic.value in kb.quick_answers:
            context["quick_answer"] = kb.quick_answers[topic.value]
        
        # Add relevant FAQs
        if topic and topic.value in kb.faqs:
            context["relevant_faqs"] = [
                {
                    "question": faq.question_template,
                    "answer": faq.answer_template,
                    "confidence": faq.confidence,
                }
                for faq in kb.faqs[topic.value]
                if faq.voice_enabled
            ]
        
        return context


# =============================================================================
# MESSAGING PERMISSION MODEL
# =============================================================================

class MessagingPermission(BaseModel):
    """
    Tracks operator permission for messaging access.
    
    Operators must explicitly authorize messaging access.
    """
    company_id: UUID
    
    # Permission granted
    messaging_access_granted: bool = False
    granted_at: Optional[datetime] = None
    granted_by: Optional[str] = None  # User who granted
    
    # Scope
    historical_access: bool = False  # Can we backfill?
    ongoing_access: bool = False  # Can we receive webhooks?
    
    # Data retention
    retention_days: int = 90  # How long to keep processed messages
    
    # Audit
    last_access: Optional[datetime] = None
    access_count: int = 0


# =============================================================================
# MESSAGING AUDIT LOG
# =============================================================================

class MessagingAuditEntry(BaseModel):
    """
    Audit log entry for messaging data access.
    
    Required for compliance.
    """
    audit_id: UUID = Field(default_factory=uuid4)
    company_id: UUID
    
    # What happened
    action: str  # ingest, process, query, export
    resource: str  # messages, knowledge_base, faq
    
    # Who/What
    actor: str  # system, user_id, api_key
    
    # When
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    
    # Details
    details: Dict[str, Any] = Field(default_factory=dict)
    
    # Result
    success: bool = True
    error_message: Optional[str] = None


# =============================================================================
# ADAPTIVE TOPIC ENGINE
# =============================================================================

class MarketTopicSignal(BaseModel):
    """
    Market-specific topic signal with time decay and geo-relevance.
    
    This is a DERIVED signal, not raw content.
    Messages are behavioral market signals:
    - Repeated "Is there parking?" → amenity ambiguity
    - Frequent late checkout requests → pricing/turnover pressure
    - Discount asks before arrival → price elasticity signal
    """
    topic: str
    market_id: str
    geofence_id: Optional[str] = None
    
    # Frequency metrics
    total_occurrences: int = 0
    occurrences_last_7d: int = 0
    occurrences_last_30d: int = 0
    occurrences_last_90d: int = 0
    
    # Trend
    trend_slope: float = 0.0  # Positive = increasing, negative = decreasing
    
    # Seasonality
    seasonality_index: float = 1.0  # >1 = seasonal peak, <1 = seasonal trough
    
    # Time decay score (EWMA)
    ewma_score: float = 0.5
    
    # Last updated
    last_seen: datetime = Field(default_factory=datetime.utcnow)


class AdaptiveTopicEngine:
    """
    Adaptive topic engine that learns market-specific patterns.
    
    Key principles:
    1. Seed with base taxonomy (WiFi, Parking, Checkout, etc.)
    2. Allow market-specific topic emergence
    3. Time-decay topic importance
    4. Geo-fence topic relevance
    
    Why adaptive?
    - Aspen ≠ Orlando
    - NYC ≠ Gulf Shores
    - Luxury ≠ budget
    """
    
    # EWMA decay factor
    ALPHA = 0.2
    
    def __init__(self, market_id: str, geofence_id: Optional[str] = None):
        self.market_id = market_id
        self.geofence_id = geofence_id
        self._topic_signals: Dict[str, MarketTopicSignal] = {}
        self._custom_topics: Set[str] = set()  # Emerged topics not in base taxonomy
    
    def record_topic(
        self,
        topic: str,
        timestamp: Optional[datetime] = None,
    ) -> MarketTopicSignal:
        """
        Record a topic occurrence and update signals.
        
        This is called after TopicExtractor identifies a topic.
        """
        now = timestamp or datetime.utcnow()
        
        if topic not in self._topic_signals:
            self._topic_signals[topic] = MarketTopicSignal(
                topic=topic,
                market_id=self.market_id,
                geofence_id=self.geofence_id,
            )
        
        signal = self._topic_signals[topic]
        
        # Update counts
        signal.total_occurrences += 1
        signal.occurrences_last_7d += 1
        signal.occurrences_last_30d += 1
        signal.occurrences_last_90d += 1
        
        # Update EWMA
        signal.ewma_score = self.ALPHA * 1.0 + (1 - self.ALPHA) * signal.ewma_score
        
        signal.last_seen = now
        
        # Track custom topics
        if not self._is_base_topic(topic):
            self._custom_topics.add(topic)
        
        return signal
    
    def _is_base_topic(self, topic: str) -> bool:
        """Check if topic is in base taxonomy."""
        try:
            MessageTopic(topic)
            return True
        except ValueError:
            return False
    
    def decay_all(self, days_passed: int = 1) -> None:
        """
        Apply time decay to all topics.
        
        Call this daily to decay importance of old topics.
        """
        decay_factor = (1 - self.ALPHA) ** days_passed
        
        for signal in self._topic_signals.values():
            signal.ewma_score *= decay_factor
    
    def get_top_topics(self, limit: int = 10) -> List[MarketTopicSignal]:
        """
        Get top topics by EWMA score (time-decayed relevance).
        """
        sorted_topics = sorted(
            self._topic_signals.values(),
            key=lambda x: x.ewma_score,
            reverse=True,
        )
        return sorted_topics[:limit]
    
    def get_emerged_topics(self) -> List[str]:
        """
        Get topics that emerged in this market but aren't in base taxonomy.
        """
        return list(self._custom_topics)
    
    def compute_seasonality(
        self,
        topic: str,
        historical_counts: Dict[int, int],  # month -> count
    ) -> float:
        """
        Compute seasonality index for a topic.
        
        Returns >1 if current month is above average, <1 if below.
        """
        if not historical_counts:
            return 1.0
        
        avg = sum(historical_counts.values()) / len(historical_counts)
        current_month = datetime.utcnow().month
        current_count = historical_counts.get(current_month, avg)
        
        return current_count / avg if avg > 0 else 1.0
    
    def get_market_intelligence(self) -> Dict[str, Any]:
        """
        Get market intelligence derived from messaging patterns.
        
        This feeds into BD and expansion analysis.
        """
        top_topics = self.get_top_topics(5)
        emerged = self.get_emerged_topics()
        
        # Analyze patterns
        has_pricing_questions = any(
            t.topic in ["discount", "price", "deal", "payment"]
            for t in top_topics
        )
        
        has_amenity_confusion = any(
            t.topic in ["parking", "pool", "wifi", "beach_access"]
            and t.ewma_score > 0.7
            for t in top_topics
        )
        
        return {
            "market_id": self.market_id,
            "geofence_id": self.geofence_id,
            "top_topics": [
                {"topic": t.topic, "score": round(t.ewma_score, 3)}
                for t in top_topics
            ],
            "emerged_topics": emerged,
            "signals": {
                "price_sensitivity": has_pricing_questions,
                "amenity_ambiguity": has_amenity_confusion,
                "market_maturity": len(emerged) < 3,  # Few emerged = mature
            },
        }


# =============================================================================
# MESSAGING AS BEHAVIORAL MARKET SIGNAL
# =============================================================================

class MessagingMarketSignal(BaseModel):
    """
    Messaging data as a market signal (same treatment as ADR, occupancy, etc.)
    
    Examples of behavioral signals:
    - Repeated "Is there parking?" → amenity ambiguity
    - Frequent late checkout requests → pricing/turnover pressure
    - Discount asks before arrival → price elasticity signal
    - Complaints clustered by week → operational or seasonal issue
    """
    market_id: str
    signal_type: str
    
    # Signal value
    value: float
    confidence: float
    
    # Derived from
    message_count: int = 0
    time_period_days: int = 30
    
    # For intelligence layer
    feeds_into: List[str] = Field(default_factory=list)  # voice, discount, bd, expansion


class MessagingSignalExtractor:
    """
    Extracts market signals from messaging patterns.
    
    This treats messages the same way as:
    - ADR signals
    - Occupancy signals
    - Amenity signals
    - Platform dominance signals
    """
    
    @staticmethod
    def extract_price_elasticity(
        discount_request_count: int,
        total_messages: int,
    ) -> MessagingMarketSignal:
        """
        Extract price elasticity signal from discount requests.
        
        High discount requests = price sensitive market.
        """
        if total_messages == 0:
            return MessagingMarketSignal(
                market_id="unknown",
                signal_type="price_elasticity",
                value=0.5,
                confidence=0.0,
            )
        
        ratio = discount_request_count / total_messages
        
        # High ratio = high elasticity (price sensitive)
        # Scale to 0-1
        elasticity = min(ratio * 10, 1.0)
        
        return MessagingMarketSignal(
            market_id="unknown",
            signal_type="price_elasticity",
            value=elasticity,
            confidence=min(total_messages / 100, 0.95),
            message_count=total_messages,
            feeds_into=["discount_logic", "pricing_engine", "voice_agent"],
        )
    
    @staticmethod
    def extract_amenity_ambiguity(
        amenity_questions: Dict[str, int],
        total_messages: int,
    ) -> Dict[str, MessagingMarketSignal]:
        """
        Extract amenity ambiguity signals.
        
        High questions about an amenity = unclear listing/documentation.
        """
        signals = {}
        
        for amenity, count in amenity_questions.items():
            if total_messages == 0:
                continue
            
            ratio = count / total_messages
            ambiguity = min(ratio * 20, 1.0)  # High ratio = high ambiguity
            
            signals[amenity] = MessagingMarketSignal(
                market_id="unknown",
                signal_type=f"amenity_ambiguity_{amenity}",
                value=ambiguity,
                confidence=min(total_messages / 50, 0.9),
                message_count=count,
                feeds_into=["listing_optimization", "voice_agent", "bd_insights"],
            )
        
        return signals
    
    @staticmethod
    def extract_operational_pressure(
        late_checkout_requests: int,
        early_checkin_requests: int,
        total_bookings: int,
    ) -> MessagingMarketSignal:
        """
        Extract operational/turnover pressure signal.
        
        High requests = turnover stress.
        """
        if total_bookings == 0:
            return MessagingMarketSignal(
                market_id="unknown",
                signal_type="operational_pressure",
                value=0.5,
                confidence=0.0,
            )
        
        request_ratio = (late_checkout_requests + early_checkin_requests) / total_bookings
        pressure = min(request_ratio * 5, 1.0)
        
        return MessagingMarketSignal(
            market_id="unknown",
            signal_type="operational_pressure",
            value=pressure,
            confidence=min(total_bookings / 50, 0.9),
            message_count=late_checkout_requests + early_checkin_requests,
            feeds_into=["pricing_engine", "operations_planning", "voice_agent"],
        )
