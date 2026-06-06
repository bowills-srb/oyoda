"""
Domain: Concierge - Pure Models.

Guest context, decision engine, and experience recommendations.
No FastAPI. No DB sessions. No external API calls.

This layer represents:
- GuestContext (stay stage, lead time, sentiment)
- Decision rules (reactive, proactive, permission-based)
- Experience suggestions
- Response generation
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple
from uuid import UUID, uuid4


# =============================================================================
# ENUMS
# =============================================================================

class StayStage(str, Enum):
    """Guest's current stage in the journey."""
    PRE_BOOKING = "pre_booking"     # Inquiring, not booked yet
    BOOKED = "booked"               # Confirmed, before arrival
    IN_STAY = "in_stay"             # Currently at property
    POST_STAY = "post_stay"         # After checkout


class GuestType(str, Enum):
    """Type of guest party."""
    FAMILY = "family"
    COUPLE = "couple"
    GROUP = "group"               # Friends, bachelor/ette
    SOLO = "solo"
    BUSINESS = "business"
    UNKNOWN = "unknown"


class Sentiment(str, Enum):
    """Detected guest sentiment."""
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    FRUSTRATED = "frustrated"
    URGENT = "urgent"


class DecisionMode(str, Enum):
    """Type of decision being made."""
    REACTIVE = "reactive"           # Response to guest question
    PROACTIVE = "proactive"         # System-initiated outreach
    PERMISSION = "permission"       # Approval request (late checkout, etc.)


class SuggestionUrgency(str, Enum):
    """Urgency level for suggestions."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    TIME_SENSITIVE = "time_sensitive"


# =============================================================================
# GUEST CONTEXT
# =============================================================================

@dataclass
class GuestContext:
    """
    Context about the guest for decision-making.
    
    This is the primary input to the decision engine.
    """
    guest_id: Optional[UUID] = None
    reservation_id: Optional[str] = None
    property_id: Optional[UUID] = None
    
    # Journey stage
    stage: StayStage = StayStage.PRE_BOOKING
    
    # Timing
    lead_time_days: Optional[int] = None  # Days until check-in
    stay_duration_nights: Optional[int] = None
    days_into_stay: Optional[int] = None  # If in-stay
    
    # Guest profile
    guest_type: GuestType = GuestType.UNKNOWN
    party_size: int = 1
    has_children: bool = False
    has_pets: bool = False
    
    # Communication
    sentiment: Sentiment = Sentiment.NEUTRAL
    previous_interactions: int = 0
    
    # Dates
    check_in_date: Optional[date] = None
    check_out_date: Optional[date] = None
    
    # Preferences (if known)
    stated_interests: List[str] = field(default_factory=list)
    
    @property
    def is_pre_arrival(self) -> bool:
        return self.stage in [StayStage.PRE_BOOKING, StayStage.BOOKED]
    
    @property
    def is_long_lead(self) -> bool:
        """Check if booking is far in advance (21+ days)."""
        return self.lead_time_days is not None and self.lead_time_days >= 21
    
    @property
    def is_short_lead(self) -> bool:
        """Check if booking is soon (< 7 days)."""
        return self.lead_time_days is not None and self.lead_time_days < 7
    
    @property
    def is_family_stay(self) -> bool:
        return self.guest_type == GuestType.FAMILY or self.has_children


# =============================================================================
# EXPERIENCE SUGGESTIONS
# =============================================================================

@dataclass
class ExperienceSuggestion:
    """
    A suggested activity or experience.
    
    Generated based on:
    - MarketContext.experience_demand
    - GuestContext (kids? group size?)
    - Seasonality
    """
    suggestion_id: str = field(default_factory=lambda: str(uuid4())[:8])
    
    # What
    experience_type: str = ""  # golf_cart, fishing, dining, etc.
    title: str = ""
    description: str = ""
    
    # Why
    rationale: str = ""  # "Golf cart rentals tend to book out early during peak weeks"
    
    # Urgency
    urgency: SuggestionUrgency = SuggestionUrgency.MEDIUM
    urgency_reason: Optional[str] = None  # "High demand expected this week"
    
    # Personalization
    relevance_score: float = 0.0  # 0-1, how relevant to this guest
    relevance_factors: List[str] = field(default_factory=list)
    
    # Action
    has_booking_link: bool = False
    booking_url: Optional[str] = None
    estimated_cost: Optional[str] = None
    
    def to_message(self) -> str:
        """Generate guest-facing message."""
        msg = self.rationale
        if self.urgency == SuggestionUrgency.TIME_SENSITIVE:
            msg += " Would you like me to share options?"
        elif self.urgency == SuggestionUrgency.HIGH:
            msg += " I can help arrange this if you're interested."
        return msg


def generate_experience_suggestions(
    guest_context: GuestContext,
    experience_demand: Dict[str, str],  # experience -> demand level
    limit: int = 3,
) -> List[ExperienceSuggestion]:
    """
    Generate personalized experience suggestions.
    
    Pure function - no IO.
    """
    suggestions = []
    
    # Map demand levels to urgency
    demand_to_urgency = {
        "very_high": SuggestionUrgency.TIME_SENSITIVE,
        "high": SuggestionUrgency.HIGH,
        "medium": SuggestionUrgency.MEDIUM,
        "low": SuggestionUrgency.LOW,
    }
    
    # Experience templates
    templates = {
        "golf_cart": {
            "title": "Golf Cart Rental",
            "description": "Explore the area at your own pace",
            "rationale": "Golf cart rentals tend to book out early during peak weeks.",
            "family_relevant": True,
            "group_relevant": True,
        },
        "fishing": {
            "title": "Fishing Charter",
            "description": "Deep sea or inshore fishing excursions",
            "rationale": "Local fishing charters are popular and book up quickly.",
            "family_relevant": True,
            "group_relevant": True,
        },
        "dining_reservations": {
            "title": "Restaurant Reservations",
            "description": "Popular local dining spots",
            "rationale": "Top restaurants in the area often require advance reservations.",
            "family_relevant": True,
            "group_relevant": True,
        },
        "water_sports": {
            "title": "Water Sports",
            "description": "Kayaking, paddleboarding, jet skis",
            "rationale": "Water sports equipment rentals are in high demand during your stay dates.",
            "family_relevant": True,
            "group_relevant": True,
        },
        "family_activities": {
            "title": "Family Activities",
            "description": "Kid-friendly attractions and activities",
            "rationale": "Family-friendly activities book up during peak season.",
            "family_relevant": True,
            "group_relevant": False,
        },
    }
    
    for exp_type, demand_level in experience_demand.items():
        if exp_type not in templates:
            continue
        
        template = templates[exp_type]
        urgency = demand_to_urgency.get(demand_level, SuggestionUrgency.MEDIUM)
        
        # Calculate relevance
        relevance = 0.5
        relevance_factors = []
        
        if demand_level in ["high", "very_high"]:
            relevance += 0.2
            relevance_factors.append("High local demand")
        
        if guest_context.is_family_stay and template.get("family_relevant"):
            relevance += 0.2
            relevance_factors.append("Great for families")
        
        if guest_context.guest_type == GuestType.GROUP and template.get("group_relevant"):
            relevance += 0.1
            relevance_factors.append("Good for groups")
        
        if exp_type in guest_context.stated_interests:
            relevance += 0.3
            relevance_factors.append("Matches your interests")
        
        suggestions.append(ExperienceSuggestion(
            experience_type=exp_type,
            title=template["title"],
            description=template["description"],
            rationale=template["rationale"],
            urgency=urgency,
            urgency_reason=f"{demand_level.replace('_', ' ').title()} demand expected" if demand_level in ["high", "very_high"] else None,
            relevance_score=min(1.0, relevance),
            relevance_factors=relevance_factors,
        ))
    
    # Sort by relevance and urgency
    suggestions.sort(key=lambda s: (s.relevance_score, s.urgency.value), reverse=True)
    
    return suggestions[:limit]


# =============================================================================
# PROACTIVE TRIGGERS
# =============================================================================

@dataclass
class ProactiveTrigger:
    """
    A condition that triggers proactive outreach.
    
    Evaluated continuously against guest + market context.
    """
    trigger_id: str
    name: str
    description: str
    
    # Conditions (all must be true)
    required_stage: Optional[StayStage] = None
    min_lead_time_days: Optional[int] = None
    max_lead_time_days: Optional[int] = None
    required_market_condition: Optional[str] = None  # "tight", "event_upcoming"
    
    # Output
    message_template: str = ""
    suggestion_type: Optional[str] = None
    
    # Control
    max_sends_per_guest: int = 1
    cooldown_hours: int = 24
    priority: int = 1  # Higher = more important


# Default proactive triggers
DEFAULT_PROACTIVE_TRIGGERS = [
    ProactiveTrigger(
        trigger_id="tight_market_prebooking",
        name="Tight Market - Pre-booking",
        description="Alert pre-booking guests when market is tight",
        required_stage=StayStage.PRE_BOOKING,
        min_lead_time_days=7,
        required_market_condition="tight",
        message_template="Just a heads-up — availability is tightening for your dates. Let me know if you'd like help securing a booking.",
        priority=2,
    ),
    ProactiveTrigger(
        trigger_id="event_upcoming",
        name="Event Upcoming",
        description="Alert guests about upcoming events",
        required_stage=StayStage.BOOKED,
        min_lead_time_days=14,
        max_lead_time_days=45,
        required_market_condition="event_upcoming",
        message_template="Your stay coincides with {event_name}, which tends to increase demand in the area.",
        priority=1,
    ),
    ProactiveTrigger(
        trigger_id="experience_high_demand",
        name="Experience High Demand",
        description="Suggest booking experiences early",
        required_stage=StayStage.BOOKED,
        min_lead_time_days=7,
        max_lead_time_days=30,
        required_market_condition="high_experience_demand",
        message_template="Golf cart rentals and fishing charters tend to book out quickly for your dates. Would you like recommendations?",
        suggestion_type="experiences",
        priority=1,
    ),
]


def evaluate_proactive_triggers(
    guest_context: GuestContext,
    market_condition: str,
    triggers: List[ProactiveTrigger] = None,
) -> List[ProactiveTrigger]:
    """
    Evaluate which proactive triggers should fire.
    
    Pure function - no IO.
    """
    if triggers is None:
        triggers = DEFAULT_PROACTIVE_TRIGGERS
    
    fired = []
    
    for trigger in triggers:
        # Check stage
        if trigger.required_stage and guest_context.stage != trigger.required_stage:
            continue
        
        # Check lead time
        if trigger.min_lead_time_days and (
            guest_context.lead_time_days is None or 
            guest_context.lead_time_days < trigger.min_lead_time_days
        ):
            continue
        
        if trigger.max_lead_time_days and (
            guest_context.lead_time_days is None or 
            guest_context.lead_time_days > trigger.max_lead_time_days
        ):
            continue
        
        # Check market condition
        if trigger.required_market_condition and market_condition != trigger.required_market_condition:
            continue
        
        fired.append(trigger)
    
    # Sort by priority
    fired.sort(key=lambda t: t.priority, reverse=True)
    
    return fired


# =============================================================================
# DECISION OUTCOMES
# =============================================================================

@dataclass
class DecisionOutcome:
    """
    Result of a decision evaluation.
    
    Used by concierge to formulate response.
    """
    decision_id: str = field(default_factory=lambda: str(uuid4())[:8])
    
    # What was decided
    decision_type: str = ""  # late_checkout, early_checkin, question, suggestion
    mode: DecisionMode = DecisionMode.REACTIVE
    
    # Result
    approved: bool = False
    requires_escalation: bool = False
    
    # Response
    response_text: str = ""
    response_tone: str = "friendly"  # friendly, apologetic, enthusiastic
    
    # Suggestions
    suggestions: List[ExperienceSuggestion] = field(default_factory=list)
    
    # Metadata
    confidence: float = 1.0
    reasoning: List[str] = field(default_factory=list)


# =============================================================================
# INTENT DETECTION
# =============================================================================

class GuestIntent(str, Enum):
    """Detected guest intent."""
    # Questions
    QUESTION_CHECKIN = "question_checkin"
    QUESTION_CHECKOUT = "question_checkout"
    QUESTION_AMENITIES = "question_amenities"
    QUESTION_WIFI = "question_wifi"
    QUESTION_PARKING = "question_parking"
    QUESTION_LOCAL_INFO = "question_local_info"
    QUESTION_EVENTS = "question_events"
    QUESTION_DINING = "question_dining"
    
    # Requests
    REQUEST_LATE_CHECKOUT = "request_late_checkout"
    REQUEST_EARLY_CHECKIN = "request_early_checkin"
    REQUEST_EXTRA_SUPPLIES = "request_extra_supplies"
    REQUEST_MAINTENANCE = "request_maintenance"
    
    # Feedback
    FEEDBACK_POSITIVE = "feedback_positive"
    FEEDBACK_NEGATIVE = "feedback_negative"
    FEEDBACK_COMPLAINT = "feedback_complaint"
    
    # Booking
    BOOKING_INQUIRY = "booking_inquiry"
    BOOKING_MODIFY = "booking_modify"
    BOOKING_CANCEL = "booking_cancel"
    
    # Other
    GREETING = "greeting"
    THANKS = "thanks"
    UNKNOWN = "unknown"


@dataclass
class DetectedIntent:
    """Result of intent detection."""
    intent: GuestIntent
    confidence: float
    entities: Dict[str, Any] = field(default_factory=dict)  # e.g., {"time": "2pm"}


# =============================================================================
# RESPONSE TEMPLATES
# =============================================================================

@dataclass
class ResponseTemplate:
    """Template for generating responses."""
    template_id: str
    intent: GuestIntent
    template: str
    requires_data: List[str] = field(default_factory=list)  # e.g., ["check_in_time"]
    tone: str = "friendly"


DEFAULT_RESPONSE_TEMPLATES = {
    GuestIntent.QUESTION_CHECKIN: ResponseTemplate(
        template_id="checkin_time",
        intent=GuestIntent.QUESTION_CHECKIN,
        template="Check-in is at {check_in_time}. If you need to adjust your arrival time, just let me know and I'll see what we can do.",
        requires_data=["check_in_time"],
    ),
    GuestIntent.QUESTION_CHECKOUT: ResponseTemplate(
        template_id="checkout_time",
        intent=GuestIntent.QUESTION_CHECKOUT,
        template="Check-out is at {check_out_time}. If you'd like a late checkout, I can check availability for you.",
        requires_data=["check_out_time"],
    ),
    GuestIntent.QUESTION_WIFI: ResponseTemplate(
        template_id="wifi_info",
        intent=GuestIntent.QUESTION_WIFI,
        template="The WiFi network is '{wifi_network}' and the password is '{wifi_password}'.",
        requires_data=["wifi_network", "wifi_password"],
    ),
    GuestIntent.QUESTION_EVENTS: ResponseTemplate(
        template_id="local_events",
        intent=GuestIntent.QUESTION_EVENTS,
        template="{events_response}",
        requires_data=["events_response"],
    ),
    GuestIntent.REQUEST_LATE_CHECKOUT: ResponseTemplate(
        template_id="late_checkout_approved",
        intent=GuestIntent.REQUEST_LATE_CHECKOUT,
        template="You're all set for a late checkout until {approved_time}. Enjoy the extra time!",
        requires_data=["approved_time"],
    ),
    GuestIntent.GREETING: ResponseTemplate(
        template_id="greeting",
        intent=GuestIntent.GREETING,
        template="Hi! I'm here to help with anything you need during your stay. What can I assist you with?",
        requires_data=[],
    ),
}


def generate_response(
    intent: GuestIntent,
    data: Dict[str, Any],
    templates: Dict[GuestIntent, ResponseTemplate] = None,
) -> str:
    """
    Generate response from template.
    
    Pure function - no IO.
    """
    if templates is None:
        templates = DEFAULT_RESPONSE_TEMPLATES
    
    template = templates.get(intent)
    if not template:
        return "I'm not sure how to help with that. Let me connect you with our team."
    
    try:
        return template.template.format(**data)
    except KeyError as e:
        return f"I'd be happy to help with that. Let me get the details for you."


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Enums
    "StayStage",
    "GuestType",
    "Sentiment",
    "DecisionMode",
    "SuggestionUrgency",
    "GuestIntent",
    
    # Guest context
    "GuestContext",
    
    # Experience suggestions
    "ExperienceSuggestion",
    "generate_experience_suggestions",
    
    # Proactive triggers
    "ProactiveTrigger",
    "DEFAULT_PROACTIVE_TRIGGERS",
    "evaluate_proactive_triggers",
    
    # Decision outcomes
    "DecisionOutcome",
    
    # Intent detection
    "DetectedIntent",
    
    # Response generation
    "ResponseTemplate",
    "DEFAULT_RESPONSE_TEMPLATES",
    "generate_response",
]
