"""
Execution Layer: Concierge Executor.

Thin wrapper around concierge and operations domain for guest interactions.
"""

from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.domain.concierge import (
    GuestContext,
    StayStage,
    GuestType,
    Sentiment,
    GuestIntent,
    DetectedIntent,
    ExperienceSuggestion,
    DecisionOutcome,
    DecisionMode,
    ProactiveTrigger,
    generate_experience_suggestions,
    evaluate_proactive_triggers,
    generate_response,
    DEFAULT_RESPONSE_TEMPLATES,
)

from app.domain.operations import (
    OperationalState,
    OperationalConstraints,
    can_approve_late_checkout,
    can_approve_early_checkin,
    should_escalate_to_manager,
)

from app.domain.market import (
    MarketContext,
    MarketEvent,
)


# =============================================================================
# PAYLOADS
# =============================================================================

@dataclass
class GuestMessagePayload:
    """Input for processing a guest message."""
    property_id: UUID
    guest_id: Optional[UUID] = None
    reservation_id: Optional[str] = None
    
    # Message
    message_text: str = ""
    detected_intent: Optional[GuestIntent] = None
    
    # Guest context
    stage: str = "booked"
    lead_time_days: Optional[int] = None
    guest_type: str = "unknown"
    party_size: int = 1
    has_children: bool = False
    
    # Dates
    check_in_date: Optional[date] = None
    check_out_date: Optional[date] = None


@dataclass
class LateCheckoutPayload:
    """Input for late checkout request."""
    property_id: UUID
    requested_time: time
    
    # Operational state
    next_checkin: Optional[datetime] = None
    staff_capacity: str = "normal"
    turnover_buffer_hours: float = 5.0
    
    # Constraints
    late_checkout_available: bool = True
    late_checkout_latest: Optional[time] = None
    minimum_turnover_hours: float = 4.0


@dataclass
class ConciergeResponse:
    """Response from concierge executor."""
    response_text: str
    intent: Optional[GuestIntent] = None
    decision_outcome: Optional[DecisionOutcome] = None
    suggestions: List[ExperienceSuggestion] = None
    requires_escalation: bool = False
    escalation_reason: Optional[str] = None
    
    def __post_init__(self):
        if self.suggestions is None:
            self.suggestions = []


# =============================================================================
# EXECUTOR
# =============================================================================

class ConciergeExecutor:
    """
    Executor for concierge interactions.
    
    Handles:
    - Reactive: Answer guest questions
    - Proactive: Generate suggestions
    - Permission: Approve/deny requests
    """
    
    def process_message(
        self,
        payload: GuestMessagePayload,
        property_profile: Dict[str, Any],
        market_context: Optional[MarketContext] = None,
    ) -> ConciergeResponse:
        """
        Process a guest message and generate response.
        
        This is the main entry point for reactive interactions.
        """
        # Build guest context
        stage_map = {
            "pre_booking": StayStage.PRE_BOOKING,
            "booked": StayStage.BOOKED,
            "in_stay": StayStage.IN_STAY,
            "post_stay": StayStage.POST_STAY,
        }
        
        type_map = {
            "family": GuestType.FAMILY,
            "couple": GuestType.COUPLE,
            "group": GuestType.GROUP,
            "solo": GuestType.SOLO,
            "business": GuestType.BUSINESS,
            "unknown": GuestType.UNKNOWN,
        }
        
        guest_context = GuestContext(
            guest_id=payload.guest_id,
            property_id=payload.property_id,
            reservation_id=payload.reservation_id,
            stage=stage_map.get(payload.stage, StayStage.BOOKED),
            lead_time_days=payload.lead_time_days,
            guest_type=type_map.get(payload.guest_type, GuestType.UNKNOWN),
            party_size=payload.party_size,
            has_children=payload.has_children,
            check_in_date=payload.check_in_date,
            check_out_date=payload.check_out_date,
        )
        
        # Use detected intent or default to unknown
        intent = payload.detected_intent or GuestIntent.UNKNOWN
        
        # Generate response based on intent
        response_data = self._extract_response_data(intent, property_profile, market_context, guest_context)
        response_text = generate_response(intent, response_data)
        
        # Check if we should add suggestions
        suggestions = []
        if market_context and intent in [GuestIntent.QUESTION_LOCAL_INFO, GuestIntent.QUESTION_EVENTS]:
            exp_demand = {
                "golf_cart": market_context.experience_demand.golf_cart.value,
                "fishing": market_context.experience_demand.fishing.value,
                "dining_reservations": market_context.experience_demand.dining_reservations.value,
            }
            suggestions = generate_experience_suggestions(guest_context, exp_demand, limit=2)
        
        return ConciergeResponse(
            response_text=response_text,
            intent=intent,
            suggestions=suggestions,
        )
    
    def _extract_response_data(
        self,
        intent: GuestIntent,
        property_profile: Dict[str, Any],
        market_context: Optional[MarketContext],
        guest_context: GuestContext,
    ) -> Dict[str, Any]:
        """Extract data needed for response template."""
        data = {}
        
        # Property data
        ops = property_profile.get("operational_constraints", {})
        access = property_profile.get("access", {})
        
        data["check_in_time"] = ops.get("check_in_time", "4:00 PM")
        data["check_out_time"] = ops.get("check_out_time", "11:00 AM")
        data["wifi_network"] = access.get("wifi_network", "See property guide")
        data["wifi_password"] = access.get("wifi_password", "See property guide")
        
        # Event data
        if market_context and guest_context.check_in_date and guest_context.check_out_date:
            events = market_context.get_events_for_stay(
                guest_context.check_in_date, 
                guest_context.check_out_date
            )
            if events:
                event_text = f"Your stay coincides with the {events[0].name}"
                if events[0].guest_appeal:
                    event_text += f". {events[0].guest_appeal}"
                data["events_response"] = event_text
            else:
                data["events_response"] = "I don't see any major events during your stay dates."
        else:
            data["events_response"] = "Let me check on local events for you."
        
        return data
    
    def evaluate_late_checkout(self, payload: LateCheckoutPayload) -> ConciergeResponse:
        """
        Evaluate a late checkout request.
        
        Permission-based decision.
        """
        from app.domain.operations import (
            OperationalState, 
            OperationalConstraints as OpsConstraints,
            StaffCapacity,
            TurnoverStatus,
        )
        
        # Build operational state
        staff_map = {
            "strained": StaffCapacity.STRAINED,
            "normal": StaffCapacity.NORMAL,
            "flexible": StaffCapacity.FLEXIBLE,
        }
        
        ops_state = OperationalState(
            property_id=payload.property_id,
            staff_capacity=staff_map.get(payload.staff_capacity, StaffCapacity.NORMAL),
            turnover_buffer_hours=payload.turnover_buffer_hours,
            next_checkin=payload.next_checkin,
        )
        
        # Build constraints
        constraints = OpsConstraints(
            late_checkout_available=payload.late_checkout_available,
            late_checkout_latest=payload.late_checkout_latest,
            minimum_turnover_hours=payload.minimum_turnover_hours,
        )
        
        # Evaluate
        approved, reason = can_approve_late_checkout(
            ops_state, 
            payload.requested_time, 
            constraints
        )
        
        # Check escalation
        should_escalate, escalation_reason = should_escalate_to_manager(ops_state, "late_checkout")
        
        # Build response
        if approved:
            response_text = f"You're all set for a late checkout until {payload.requested_time.strftime('%I:%M %p')}. Enjoy the extra time!"
        else:
            response_text = f"I apologize, but I'm unable to approve a late checkout for that time. {reason}"
        
        outcome = DecisionOutcome(
            decision_type="late_checkout",
            mode=DecisionMode.PERMISSION,
            approved=approved,
            requires_escalation=should_escalate,
            response_text=response_text,
            reasoning=[reason],
        )
        
        return ConciergeResponse(
            response_text=response_text,
            decision_outcome=outcome,
            requires_escalation=should_escalate,
            escalation_reason=escalation_reason if should_escalate else None,
        )
    
    def generate_proactive_suggestions(
        self,
        guest_context: GuestContext,
        market_context: MarketContext,
    ) -> List[ExperienceSuggestion]:
        """
        Generate proactive experience suggestions.
        
        Called periodically or on booking confirmation.
        """
        exp_demand = {
            "golf_cart": market_context.experience_demand.golf_cart.value,
            "fishing": market_context.experience_demand.fishing.value,
            "dining_reservations": market_context.experience_demand.dining_reservations.value,
            "water_sports": market_context.experience_demand.water_sports.value,
            "family_activities": market_context.experience_demand.family_activities.value,
        }
        
        return generate_experience_suggestions(guest_context, exp_demand, limit=3)
    
    def evaluate_proactive_triggers(
        self,
        guest_context: GuestContext,
        market_context: MarketContext,
    ) -> List[ProactiveTrigger]:
        """
        Evaluate which proactive triggers should fire.
        
        Returns list of triggered proactive messages.
        """
        # Determine market condition
        if market_context.is_tight_market:
            condition = "tight"
        elif market_context.event_calendar.has_upcoming_high_impact:
            condition = "event_upcoming"
        elif market_context.experience_demand.get_high_demand_experiences():
            condition = "high_experience_demand"
        else:
            condition = "normal"
        
        return evaluate_proactive_triggers(guest_context, condition)
