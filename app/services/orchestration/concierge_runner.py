"""
Orchestration: Concierge Runner.

Coordinates guest interactions across domain, execution, and voice layers.
This is where the interface layer (chat/voice) calls in.

Pipeline:
1. STT (Deepgram) → text
2. Intent detection → GuestIntent
3. Load context (PropertyProfile, MarketContext, OperationalState)
4. Decision engine → DecisionOutcome
5. Response generation → text
6. TTS (ElevenLabs) → audio (optional)
"""

from dataclasses import dataclass
from datetime import date, time
import re
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.domain.concierge import (
    GuestContext,
    StayStage,
    GuestType,
    Sentiment,
    GuestIntent,
    DecisionOutcome,
    DecisionMode,
    ExperienceSuggestion,
    ProactiveTrigger,
    evaluate_proactive_triggers,
    generate_experience_suggestions,
    generate_response,
)

from app.domain.operations import (
    OperationalState,
    can_approve_late_checkout,
    can_approve_early_checkin,
    should_escalate_to_manager,
)

from app.domain.market import MarketContext

from app.services.execution import (
    ConciergeExecutor,
    GuestMessagePayload,
    LateCheckoutPayload,
    ConciergeResponse,
)


# =============================================================================
# REQUEST/RESPONSE MODELS
# =============================================================================

@dataclass
class ConciergeRequest:
    """Incoming request to concierge."""
    property_id: UUID
    
    # Guest context
    guest_id: Optional[UUID] = None
    reservation_id: Optional[str] = None
    stage: str = "booked"  # pre_booking, booked, in_stay, post_stay
    
    # Message
    message_text: Optional[str] = None
    intent: Optional[str] = None  # Pre-detected intent (optional)
    
    # Voice (optional)
    audio_data: Optional[bytes] = None
    
    # Context
    check_in_date: Optional[date] = None
    check_out_date: Optional[date] = None


@dataclass
class ConciergeReply:
    """Response from concierge."""
    text: str
    audio_data: Optional[bytes] = None
    
    intent: Optional[str] = None
    approved: Optional[bool] = None
    requires_escalation: bool = False
    
    suggestions: List[ExperienceSuggestion] = None
    proactive_messages: List[str] = None
    
    def __post_init__(self):
        if self.suggestions is None:
            self.suggestions = []
        if self.proactive_messages is None:
            self.proactive_messages = []


# =============================================================================
# INTENT CLASSIFIER (Simple rule-based for now)
# =============================================================================

def classify_intent(text: str) -> GuestIntent:
    """
    Simple rule-based intent classification.
    
    In production, replace with ML classifier or LLM.
    """
    text_lower = text.lower()
    
    # Check-in/out
    if any(w in text_lower for w in ["late checkout", "late check-out", "stay longer", "extend checkout"]):
        return GuestIntent.REQUEST_LATE_CHECKOUT
    if any(w in text_lower for w in ["early check", "early arrive", "come early", "early checkin"]):
        return GuestIntent.REQUEST_EARLY_CHECKIN
    if any(w in text_lower for w in ["check in", "check-in", "checkin", "arrive", "arrival"]):
        return GuestIntent.QUESTION_CHECKIN
    if any(w in text_lower for w in ["check out", "check-out", "checkout", "leave", "departure"]):
        return GuestIntent.QUESTION_CHECKOUT
    
    # WiFi
    if any(w in text_lower for w in ["wifi", "wi-fi", "internet", "password"]):
        return GuestIntent.QUESTION_WIFI
    
    # Parking
    if any(w in text_lower for w in ["parking", "park", "car", "driveway", "garage"]):
        return GuestIntent.QUESTION_PARKING
    
    # Amenities
    if any(w in text_lower for w in ["pool", "hot tub", "grill", "amenities"]):
        return GuestIntent.QUESTION_AMENITIES
    
    # Local info
    if any(w in text_lower for w in ["restaurant", "eat", "food", "dining"]):
        return GuestIntent.QUESTION_DINING
    if any(w in text_lower for w in ["event", "festival", "going on", "happening"]):
        return GuestIntent.QUESTION_EVENTS
    if any(w in text_lower for w in ["near", "nearby", "around", "local", "recommend"]):
        return GuestIntent.QUESTION_LOCAL_INFO
    
    # Maintenance
    if any(w in text_lower for w in ["broken", "not working", "fix", "maintenance", "issue", "problem"]):
        return GuestIntent.REQUEST_MAINTENANCE
    
    # Greetings (word boundaries to avoid false positives like "this" -> "hi")
    greeting_tokens = ["hi", "hello", "hey"]
    if any(re.search(rf"\b{re.escape(token)}\b", text_lower) for token in greeting_tokens) or any(
        phrase in text_lower for phrase in ["good morning", "good afternoon"]
    ):
        return GuestIntent.GREETING
    if any(re.search(rf"\b{re.escape(token)}\b", text_lower) for token in ["thank", "thanks", "appreciate"]):
        return GuestIntent.THANKS
    
    return GuestIntent.UNKNOWN


# =============================================================================
# CONCIERGE RUNNER
# =============================================================================

class ConciergeRunner:
    """
    Orchestrates guest interactions.
    
    This is the main entry point for:
    - Chat messages
    - Voice interactions
    - Proactive outreach
    
    Usage:
        runner = ConciergeRunner()
        
        # Handle a message
        reply = await runner.handle_message(request, property_profile, market_context, ops_state)
        
        # Get proactive messages
        messages = runner.get_proactive_messages(guest_context, market_context)
    """
    
    def __init__(self):
        self.executor = ConciergeExecutor()
        self._stt = None
        self._tts = None
    
    def set_voice_providers(self, stt=None, tts=None):
        """Set voice providers for audio I/O."""
        self._stt = stt
        self._tts = tts
    
    async def handle_message(
        self,
        request: ConciergeRequest,
        property_profile: Dict[str, Any],
        market_context: Optional[MarketContext] = None,
        ops_state: Optional[OperationalState] = None,
    ) -> ConciergeReply:
        """
        Handle an incoming guest message.
        
        This is the main REACTIVE handler.
        """
        # 1. Get text (from audio if needed)
        text = request.message_text
        if request.audio_data and self._stt:
            result = await self._stt.transcribe(request.audio_data)
            text = result.text
        
        if not text:
            return ConciergeReply(text="I didn't catch that. Could you please repeat?")
        
        # 2. Classify intent
        intent = GuestIntent(request.intent) if request.intent else classify_intent(text)
        
        # 3. Handle based on intent
        if intent == GuestIntent.REQUEST_LATE_CHECKOUT:
            return await self._handle_late_checkout(request, property_profile, ops_state)
        
        if intent == GuestIntent.REQUEST_EARLY_CHECKIN:
            return await self._handle_early_checkin(request, property_profile, ops_state)
        
        # 4. Standard message handling
        payload = GuestMessagePayload(
            property_id=request.property_id,
            guest_id=request.guest_id,
            reservation_id=request.reservation_id,
            message_text=text,
            detected_intent=intent,
            stage=request.stage,
            check_in_date=request.check_in_date,
            check_out_date=request.check_out_date,
        )
        
        response = self.executor.process_message(payload, property_profile, market_context)
        
        # 5. Generate audio if TTS available
        audio = None
        if self._tts:
            result = await self._tts.synthesize(response.response_text)
            audio = result.audio_data
        
        return ConciergeReply(
            text=response.response_text,
            audio_data=audio,
            intent=intent.value,
            suggestions=response.suggestions,
        )
    
    async def _handle_late_checkout(
        self,
        request: ConciergeRequest,
        property_profile: Dict[str, Any],
        ops_state: Optional[OperationalState],
    ) -> ConciergeReply:
        """Handle late checkout request."""
        # Default to noon if not specified
        requested_time = time(12, 0)
        
        # Get constraints from profile
        ops_constraints = property_profile.get("operational_constraints", {})
        
        payload = LateCheckoutPayload(
            property_id=request.property_id,
            requested_time=requested_time,
            next_checkin=ops_state.next_checkin if ops_state else None,
            staff_capacity=ops_state.staff_capacity.value if ops_state else "normal",
            late_checkout_available=ops_constraints.get("late_checkout_available", True),
            late_checkout_latest=time(14, 0),  # Default 2pm
            minimum_turnover_hours=ops_constraints.get("minimum_turnover_hours", 4.0),
        )
        
        response = self.executor.evaluate_late_checkout(payload)
        
        # Generate audio
        audio = None
        if self._tts:
            result = await self._tts.synthesize(response.response_text)
            audio = result.audio_data
        
        return ConciergeReply(
            text=response.response_text,
            audio_data=audio,
            intent="request_late_checkout",
            approved=response.decision_outcome.approved if response.decision_outcome else None,
            requires_escalation=response.requires_escalation,
        )
    
    async def _handle_early_checkin(
        self,
        request: ConciergeRequest,
        property_profile: Dict[str, Any],
        ops_state: Optional[OperationalState],
    ) -> ConciergeReply:
        """Handle early check-in request."""
        # For now, return a standard response
        text = "I'd be happy to check on early check-in availability. Let me look into that for you."
        
        if ops_state and ops_state.is_ready_for_guest:
            text = "Great news! The property is ready, so an early check-in should be possible. I'll confirm the details."
        
        audio = None
        if self._tts:
            result = await self._tts.synthesize(text)
            audio = result.audio_data
        
        return ConciergeReply(
            text=text,
            audio_data=audio,
            intent="request_early_checkin",
        )
    
    def get_proactive_messages(
        self,
        guest_context: GuestContext,
        market_context: MarketContext,
    ) -> List[str]:
        """
        Get proactive messages for a guest.
        
        Call this on booking confirmation or periodically.
        """
        messages = []
        
        # Evaluate triggers
        triggers = self.executor.evaluate_proactive_triggers(guest_context, market_context)
        
        for trigger in triggers:
            # Format message template
            msg = trigger.message_template
            
            # Substitute event name if needed
            if "{event_name}" in msg and market_context.event_calendar.events:
                events = market_context.event_calendar.get_upcoming_events(60)
                if events:
                    msg = msg.replace("{event_name}", events[0].name)
            
            messages.append(msg)
        
        return messages
    
    def get_experience_suggestions(
        self,
        guest_context: GuestContext,
        market_context: MarketContext,
        limit: int = 3,
    ) -> List[ExperienceSuggestion]:
        """
        Get experience suggestions for a guest.
        
        Call this to generate proactive recommendations.
        """
        return self.executor.generate_proactive_suggestions(guest_context, market_context)[:limit]


# =============================================================================
# FACTORY
# =============================================================================

def get_concierge_runner() -> ConciergeRunner:
    """Create a ConciergeRunner instance."""
    return ConciergeRunner()
