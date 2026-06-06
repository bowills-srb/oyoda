"""
Concierge MCP Server

The single MCP that drives everything Coral needs for a guest interaction.

What this replaces in terms of token cost:
  BEFORE: Property context injected as 800-1200 token system prompt block
  AFTER:  Coral calls get_property_basics() → 5-field struct, zero tokens

  BEFORE: Escalation detection logic re-explained in every system prompt
  AFTER:  Coral calls check_escalation(text) → {escalate: bool, priority: str}

  BEFORE: Journey state re-hydrated from DB on every message turn
  AFTER:  Coral calls get_journey_state(token) → compact dict

  BEFORE: Booking eligibility checked via SQL described to LLM
  AFTER:  Coral calls check_extend_eligible(token) → {eligible: bool}

  BEFORE: Activity provider info in system prompt
  AFTER:  Coral calls get_activity_info("beach_chairs") → formatted string

Tools exposed:
  get_property_basics(property_code)             → WiFi, code, times, amenities
  get_session_context(token)                     → phase, guest name, stay info
  check_escalation(text, conversation_turns)     → escalate decision
  get_journey_state(token)                       → what's been discussed
  get_activity_info(activity_type, check_in)     → provider list for activity
  check_extend_eligible(token)                   → extend stay offer gate
  get_faq_answer(question, property_code)        → direct FAQ match (no LLM)
  record_gap(question, session_token)            → log unanswered questions
"""

import logging
import re
from datetime import date
from typing import Any, Dict, List, Optional

from app.mcp.base import MCPResult, MCPServer, MCPTool

logger = logging.getLogger(__name__)


class ConciergeMCPServer(MCPServer):
    """
    The primary MCP for Coral (the guest concierge AI).

    Coral calls this instead of injecting everything into her system prompt.
    Zero tokens per call. Zero external API calls. Pure in-process.
    """

    server_name = "concierge"
    server_description = "Guest concierge data — property info, session state, escalation, journey, FAQs"

    def get_tools(self) -> List[MCPTool]:
        return [
            MCPTool(
                name="get_property_basics",
                description="Get WiFi, door code, check-in/out times, and amenity flags for a property. Call this instead of injecting property context into the system prompt.",
                parameters={
                    "type": "object",
                    "properties": {
                        "property_code": {"type": "string"},
                    },
                    "required": ["property_code"],
                },
                returns="Dict: {wifi_network, wifi_password, door_code, check_in_time, check_out_time, has_pool, pool_heated, has_bikes, bike_count, has_hot_tub, has_grill, has_beach_gear, pets_allowed, quiet_hours_start, quiet_hours_end, check_in_instructions}",
                category="concierge",
            ),
            MCPTool(
                name="get_session_context",
                description="Get guest session state — phase, name, days remaining, whether feedback should be requested. Use this to adapt Coral's tone without injecting session data into the prompt.",
                parameters={
                    "type": "object",
                    "properties": {
                        "token": {"type": "string"},
                    },
                    "required": ["token"],
                },
                returns="Dict: {guest_first_name, property_name, phase, days_until_checkin, days_remaining, is_arrival_day, is_departure_day, should_request_feedback, concierge_name, operator_name}",
                category="concierge",
            ),
            MCPTool(
                name="check_escalation",
                description="Should this message be escalated to a human? Run every inbound message through this before generating a response. Returns escalation decision with priority and reason — no LLM needed.",
                parameters={
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "conversation_turns": {"type": "integer", "default": 0, "description": "Total number of turns so far. If >= 6 without resolution, auto-escalate."},
                    },
                    "required": ["text"],
                },
                returns="Dict: {escalate: bool, priority: str (urgent/high/medium), reason: str, esc_reason_code: str}",
                category="concierge",
            ),
            MCPTool(
                name="get_journey_state",
                description="Get what activities have been discussed with this guest — beach chairs, golf, fishing, etc. Lets Coral know what to proactively mention without re-injecting the full journey.",
                parameters={
                    "type": "object",
                    "properties": {
                        "token": {"type": "string"},
                    },
                    "required": ["token"],
                },
                returns="Dict: {not_discussed: [str], info_provided: [str], booked: [str], declined: [str], welcome_sent: bool, days_until_checkin: int}",
                category="concierge",
            ),
            MCPTool(
                name="get_activity_info",
                description="Get local provider info for a 30A activity — beach chairs, golf, fishing, bikes, pontoon, dolphin tours, spa, groceries. Returns formatted string ready to send to guest.",
                parameters={
                    "type": "object",
                    "properties": {
                        "activity_type": {
                            "type": "string",
                            "enum": ["beach_chairs", "fishing", "golf", "bikes", "pontoon", "dolphin", "spa", "groceries", "restaurants"],
                        },
                        "check_in": {"type": "string", "description": "ISO date YYYY-MM-DD, used for booking urgency warnings"},
                    },
                    "required": ["activity_type"],
                },
                returns="Formatted string with provider names, phones, websites, booking lead time warnings",
                category="concierge",
            ),
            MCPTool(
                name="search_restaurants",
                description="Search 30A-area restaurants and return options with area, cuisine, and booking contact details.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "area": {"type": "string"},
                        "date": {"type": "string", "description": "YYYY-MM-DD"},
                        "time": {"type": "string", "description": "HH:MM"},
                        "party_size": {"type": "integer", "default": 2},
                    },
                    "required": ["query"],
                },
                returns="List[Dict]: {name, area, cuisine, phone, booking_url}",
                category="concierge",
            ),
            MCPTool(
                name="check_dining_availability",
                description="Check restaurant availability for a given date/time/party size.",
                parameters={
                    "type": "object",
                    "properties": {
                        "restaurant_name": {"type": "string"},
                        "date": {"type": "string", "description": "YYYY-MM-DD"},
                        "time": {"type": "string", "description": "HH:MM"},
                        "party_size": {"type": "integer", "default": 2},
                        "area": {"type": "string"},
                    },
                    "required": ["restaurant_name", "date", "party_size"],
                },
                returns="Dict: {restaurant, date, party_size, available_times, booking_url, source}",
                category="concierge",
            ),
            MCPTool(
                name="create_dining_reservation",
                description="Create a dining reservation request for the guest.",
                parameters={
                    "type": "object",
                    "properties": {
                        "restaurant_name": {"type": "string"},
                        "date": {"type": "string", "description": "YYYY-MM-DD"},
                        "time": {"type": "string", "description": "HH:MM"},
                        "party_size": {"type": "integer"},
                        "guest_name": {"type": "string"},
                        "guest_phone": {"type": "string"},
                        "guest_email": {"type": "string"},
                        "special_requests": {"type": "string"},
                        "session_token": {"type": "string"},
                    },
                    "required": ["restaurant_name", "date", "time", "party_size", "guest_name"],
                },
                returns="Dict: {success, status, message, confirmation_id, booking_url, source}",
                category="concierge",
            ),
            MCPTool(
                name="check_extend_eligible",
                description="Is this guest eligible for an extend-stay offer? Checks if next guest is arriving and if offer was already sent. Call this before generating the offer message.",
                parameters={
                    "type": "object",
                    "properties": {
                        "token": {"type": "string"},
                    },
                    "required": ["token"],
                },
                returns="Dict: {eligible: bool, reason: str, extra_night_date: str}",
                category="concierge",
            ),
            MCPTool(
                name="get_faq_answer",
                description="Check if the guest's question matches a known FAQ — pure keyword matching, zero LLM tokens. Returns direct answer if match found, null if not (then use LLM fallback).",
                parameters={
                    "type": "object",
                    "properties": {
                        "question": {"type": "string"},
                        "property_code": {"type": "string"},
                        "tenant_id": {"type": "string"},
                    },
                    "required": ["question"],
                },
                returns="Dict: {answer: str|null, match_type: str, confidence: float}",
                category="concierge",
            ),
            MCPTool(
                name="record_gap",
                description="Log a question Coral couldn't answer confidently. Feeds the operator dashboard so they can add FAQ answers. Call this when returning a generic or uncertain response.",
                parameters={
                    "type": "object",
                    "properties": {
                        "question": {"type": "string"},
                        "session_token": {"type": "string"},
                        "property_code": {"type": "string"},
                        "detected_intent": {"type": "string"},
                    },
                    "required": ["question"],
                },
                returns="Dict: {gap_id: str, deduped: bool}",
                category="concierge",
            ),
            MCPTool(
                name="find_nearby_available",
                description="Find other properties in this operator's portfolio that are available for a given date range, near the current guest's property. Use when a guest mentions friends or family who want to stay close by at the same time.",
                parameters={
                    "type": "object",
                    "properties": {
                        "reference_property_code": {"type": "string", "description": "The current guest's property code — used as the proximity anchor"},
                        "check_in": {"type": "string", "description": "YYYY-MM-DD"},
                        "check_out": {"type": "string", "description": "YYYY-MM-DD"},
                        "tenant_id": {"type": "string"},
                        "min_bedrooms": {"type": "integer", "description": "Minimum bedrooms needed (optional)"},
                        "min_sleeps": {"type": "integer", "description": "Minimum guests the property needs to sleep (optional)"},
                        "require_pet_friendly": {"type": "boolean", "default": False},
                        "require_pool": {"type": "boolean", "default": False},
                    },
                    "required": ["reference_property_code", "check_in", "check_out"],
                },
                returns="Dict: {available: [{name, community, bedrooms, sleeps, has_pool, pet_friendly, distance_km, listing_url, address_display}], check_in, check_out, nights, total_portfolio_checked}",
                category="concierge",
            ),
            MCPTool(
                name="get_proactive_message",
                description="Get the next proactive message to send this guest — welcome, check-in reminder, activity nudge, or extend offer. Returns null if nothing is due yet.",
                parameters={
                    "type": "object",
                    "properties": {
                        "token": {"type": "string"},
                    },
                    "required": ["token"],
                },
                returns="Dict: {message_type: str, message: str} or null",
                category="concierge",
            ),
        ]

    async def call(
        self,
        tool_name: str,
        operator_id: str,
        params: Dict[str, Any],
    ) -> MCPResult:
        if tool_name == "get_property_basics":
            return await self._get_property_basics(operator_id, params)
        elif tool_name == "get_session_context":
            return await self._get_session_context(operator_id, params)
        elif tool_name == "check_escalation":
            return self._check_escalation(operator_id, params)
        elif tool_name == "get_journey_state":
            return await self._get_journey_state(operator_id, params)
        elif tool_name == "get_activity_info":
            return self._get_activity_info(operator_id, params)
        elif tool_name == "search_restaurants":
            return await self._search_restaurants(operator_id, params)
        elif tool_name == "check_dining_availability":
            return await self._check_dining_availability(operator_id, params)
        elif tool_name == "create_dining_reservation":
            return await self._create_dining_reservation(operator_id, params)
        elif tool_name == "check_extend_eligible":
            return await self._check_extend_eligible(operator_id, params)
        elif tool_name == "get_faq_answer":
            return await self._get_faq_answer(operator_id, params)
        elif tool_name == "record_gap":
            return await self._record_gap(operator_id, params)
        elif tool_name == "find_nearby_available":
            return await self._find_nearby_available(operator_id, params)
        elif tool_name == "get_proactive_message":
            return await self._get_proactive_message(operator_id, params)
        return MCPResult(success=False, message=f"Unknown tool: {tool_name}")

    # ─────────────────────────────────────────────────────────────
    # Tool Implementations
    # ─────────────────────────────────────────────────────────────

    async def _get_property_basics(self, operator_id: str, params: Dict) -> MCPResult:
        property_code = params["property_code"]

        try:
            from app.services.concierge.property_context import get_property_context
            prop = get_property_context(property_code)

            if not prop:
                return MCPResult(
                    success=False,
                    message=f"Property {property_code} not found",
                )

            return MCPResult(
                success=True,
                data={
                    "property_code": prop.property_code,
                    "property_name": prop.property_name,
                    "community": prop.community,
                    "bedrooms": prop.bedrooms,
                    "bathrooms": prop.bathrooms,
                    "sleeps": prop.sleeps,
                    # Access
                    "wifi_network": prop.wifi_network,
                    "wifi_password": prop.wifi_password,
                    "door_code": None,  # Loaded separately for security; use get_door_code()
                    "lock_type": prop.lock_type,
                    "check_in_time": prop.check_in_time,
                    "check_out_time": prop.check_out_time,
                    "check_in_instructions": prop.check_in_instructions,
                    "check_out_instructions": prop.check_out_instructions,
                    "property_guide_url": prop.property_guide_url,
                    # Amenities
                    "has_pool": prop.has_pool,
                    "pool_heated": prop.pool_heated,
                    "has_hot_tub": prop.has_hot_tub,
                    "has_grill": prop.has_grill,
                    "has_bikes": prop.has_bikes,
                    "bike_count": prop.bike_count,
                    "has_beach_gear": prop.has_beach_gear,
                    "has_washer_dryer": prop.has_washer_dryer,
                    # Rules
                    "pets_allowed": prop.pets_allowed,
                    "max_occupancy": prop.max_occupancy,
                    "quiet_hours_start": prop.quiet_hours_start,
                    "quiet_hours_end": prop.quiet_hours_end,
                },
                message=f"Property loaded: {prop.property_name}",
            )

        except Exception as e:
            logger.error(f"get_property_basics error: {e}")
            return MCPResult(success=False, message=str(e))

    async def _get_session_context(self, operator_id: str, params: Dict) -> MCPResult:
        token = params["token"]

        try:
            from app.core.database import get_db_session
            from app.services.concierge.db_session_service import (
                DatabaseSessionService,
                DEFAULT_TENANT_ID,
            )
            from app.services.messaging.booking_context_adapters import (
                BookingContextAdapterConfig,
                BookingContextLookup,
                build_booking_context_adapter,
            )

            async with get_db_session() as db:
                lookup_svc = DatabaseSessionService(DEFAULT_TENANT_ID)
                session = await lookup_svc.get_session_by_token(db, token, tenant_agnostic=True)

                if not session:
                    return MCPResult(success=False, message=f"Session {token} not found")

                svc = DatabaseSessionService(session.tenant_id)
                journey = await svc.get_journey(db, session.session_id)

                booking_context = {}
                try:
                    adapter = build_booking_context_adapter(
                        BookingContextAdapterConfig(company_id=session.tenant_id)
                    )
                    booking_context = await adapter.lookup(
                        db,
                        BookingContextLookup(session_id=str(session.session_id)),
                    )
                except Exception as exc:
                    logger.debug("get_session_context booking context skipped: %s", exc)

            activity_lists = {
                "not_discussed": [],
                "info_provided": [],
                "booked": [],
                "declined": [],
            }
            if journey:
                for activity in journey.activities or []:
                    status = (activity.status or "not_discussed").lower()
                    activity_type = activity.activity_type
                    if status == "not_discussed":
                        activity_lists["not_discussed"].append(activity_type)
                    elif status == "info_provided":
                        activity_lists["info_provided"].append(activity_type)
                    elif status in {"booked", "handled"}:
                        activity_lists["booked"].append(activity_type)
                    elif status == "not_interested":
                        activity_lists["declined"].append(activity_type)

            phase = session.phase or "pre_arrival"
            today = date.today()
            days_until_checkin = max(0, (session.check_in - today).days) if session.check_in else 0
            days_remaining = max(0, (session.check_out - today).days) if session.check_out else 0
            property_context = session.property_context or {}
            booking_snapshot = booking_context.get("booking") or {}
            property_snapshot = booking_context.get("property") or {}
            guest_first_name = (session.guest_name or "Guest").split(" ", 1)[0]

            return MCPResult(
                success=True,
                data={
                    "guest_first_name": guest_first_name,
                    "guest_name": session.guest_name,
                    "guest_phone": session.guest_phone,
                    "guest_email": session.guest_email,
                    "property_name": session.property_name,
                    "property_code": session.property_code,
                    "reservation_id": session.reservation_id,
                    "operator_name": property_context.get("operator_name"),
                    "concierge_name": property_context.get("concierge_name", "Coral"),
                    "concierge_emoji": property_context.get("concierge_emoji", "🐚"),
                    "phase": phase,
                    "check_in": session.check_in.isoformat() if session.check_in else None,
                    "check_out": session.check_out.isoformat() if session.check_out else None,
                    "nights": (session.check_out - session.check_in).days if session.check_in and session.check_out else booking_snapshot.get("nights", 0),
                    "num_guests": session.num_guests,
                    "days_until_checkin": days_until_checkin,
                    "days_remaining": days_remaining,
                    "is_arrival_day": phase == "arrival_day",
                    "is_departure_day": phase == "departure_day",
                    "should_request_feedback": phase in {"departure_day", "post_stay"},
                    "conversation_count": session.conversation_count,
                    "support_phone": property_context.get("support_phone"),
                    "is_expired": session.status == "expired",
                    "property_context": property_context,
                    "booking_context": booking_context,
                    "booking_channel": booking_snapshot.get("booking_channel"),
                    "nightly_rate": booking_snapshot.get("nightly_rate"),
                    "total_amount": booking_snapshot.get("total_amount"),
                    "pms_provider": booking_context.get("provider") or property_snapshot.get("provider"),
                    "journey": {
                        "welcome_sent": bool(getattr(journey, "welcome_sent", False)),
                        "welcome_sent_at": journey.welcome_sent_at.isoformat() if journey and journey.welcome_sent_at else None,
                        "extend_offer_sent": bool(getattr(journey, "extend_offer_sent", False)),
                        "extend_offer_sent_at": journey.extend_offer_sent_at.isoformat() if journey and journey.extend_offer_sent_at else None,
                        "extend_offer_response": getattr(journey, "extend_offer_response", None),
                        "checkin_reminder_sent": bool(getattr(journey, "checkin_reminder_sent", False)),
                        "checkout_reminder_sent": bool(getattr(journey, "checkout_reminder_sent", False)),
                        **activity_lists,
                    },
                },
                message=f"Session: {guest_first_name} @ {session.property_name} ({phase})",
            )

        except Exception as e:
            logger.error(f"get_session_context error: {e}")
            return MCPResult(success=False, message=str(e))

    def _check_escalation(self, operator_id: str, params: Dict) -> MCPResult:
        """
        Pure Python escalation detection — zero LLM tokens.
        Mirrors the logic in EscalationDetector but returns a compact struct.
        """
        text = params.get("text", "")
        turns = params.get("conversation_turns", 0)
        text_lower = text.lower()

        URGENT = [
            "emergency", "911", "fire", "flood", "gas leak", "gas smell",
            "hurt", "injured", "ambulance", "locked out", "no power",
            "no water", "water everywhere", "someone broke in",
        ]
        HIGH = [
            "broken", "not working", "doesn't work", "stopped working",
            "leak", "leaking", "water damage", "mold", "sewage",
            "ac not working", "no air conditioning", "no heat",
            "too hot", "too cold", "pest", "bugs", "roaches", "ants",
            "dirty", "filthy", "disgusting", "unacceptable",
            "refund", "compensation", "money back",
        ]
        MEDIUM = [
            "manager", "supervisor", "human", "real person",
            "speak to someone", "talk to someone", "call me",
            "maintenance", "issue", "problem", "complaint",
            "late checkout", "extend stay", "early checkin",
        ]

        for trigger in URGENT:
            if trigger in text_lower:
                return MCPResult(
                    success=True,
                    data={
                        "escalate": True,
                        "priority": "urgent",
                        "reason": f"Urgent keyword detected: '{trigger}'",
                        "esc_reason_code": "safety",
                    },
                    message="ESCALATE: Urgent",
                )

        for trigger in HIGH:
            if trigger in text_lower:
                reason_code = "maintenance" if any(w in text_lower for w in ["broken", "not working", "leak", "ac", "heat"]) else "complaint"
                return MCPResult(
                    success=True,
                    data={
                        "escalate": True,
                        "priority": "high",
                        "reason": f"Property issue: '{trigger}'",
                        "esc_reason_code": reason_code,
                    },
                    message="ESCALATE: High priority",
                )

        for trigger in MEDIUM:
            if trigger in text_lower:
                return MCPResult(
                    success=True,
                    data={
                        "escalate": True,
                        "priority": "medium",
                        "reason": f"Guest request: '{trigger}'",
                        "esc_reason_code": "guest_requested" if "human" in text_lower or "manager" in text_lower else "property_issue",
                    },
                    message="ESCALATE: Medium priority",
                )

        # Long conversation without resolution
        if turns >= 6:
            return MCPResult(
                success=True,
                data={
                    "escalate": True,
                    "priority": "medium",
                    "reason": f"Long conversation ({turns} turns) — guest may need human help",
                    "esc_reason_code": "repeated_failures",
                },
                message="ESCALATE: Conversation length",
            )

        return MCPResult(
            success=True,
            data={
                "escalate": False,
                "priority": None,
                "reason": None,
                "esc_reason_code": None,
            },
            message="No escalation needed",
        )

    async def _get_journey_state(self, operator_id: str, params: Dict) -> MCPResult:
        token = params["token"]

        try:
            from app.core.database import get_db_session
            from app.services.operator.stay_journey_service import get_journey_summary_by_token

            async with get_db_session() as db:
                summary = await get_journey_summary_by_token(db, token)

            if not summary:
                return MCPResult(
                    success=True,
                    data={"not_discussed": [], "info_provided": [], "booked": [], "declined": [], "welcome_sent": False, "days_until_checkin": 0},
                    message="Journey not found — returning empty state",
                )

            return MCPResult(
                success=True,
                data={
                    "not_discussed": summary.get("not_discussed") or [],
                    "info_provided": summary.get("discussed") or [],
                    "booked": summary.get("booked_or_handled") or [],
                    "declined": summary.get("declined") or [],
                    "welcome_sent": bool(summary.get("welcome_sent")),
                    "days_until_checkin": int(summary.get("days_until_checkin") or 0),
                    "check_in": summary.get("check_in"),
                },
                message=(
                    f"Journey: {len(summary.get('booked_or_handled') or [])} booked, "
                    f"{len(summary.get('not_discussed') or [])} not discussed"
                ),
            )

        except Exception as e:
            logger.error(f"get_journey_state error: {e}")
            return MCPResult(success=False, message=str(e))

    def _get_activity_info(self, operator_id: str, params: Dict) -> MCPResult:
        activity_type = params["activity_type"]
        check_in_str = params.get("check_in")

        try:
            check_in_date = date.fromisoformat(check_in_str) if check_in_str else date.today()
        except ValueError:
            check_in_date = date.today()

        try:
            from app.services.operator.stay_journey_service import get_activity_info_text

            info = get_activity_info_text(activity_type, check_in_date)

            return MCPResult(
                success=True,
                data={"activity_type": activity_type, "info": info},
                message=f"Activity info: {activity_type}",
            )

        except Exception as e:
            return MCPResult(success=False, message=str(e))

    async def _search_restaurants(self, operator_id: str, params: Dict) -> MCPResult:
        query = params.get("query", "").strip()
        if not query:
            return MCPResult(success=False, message="query is required")

        area = params.get("area")
        date_str = params.get("date")
        time_str = params.get("time")
        party_size = int(params.get("party_size") or 2)

        try:
            from app.services.concierge.dining_service import get_dining_service

            service = get_dining_service()
            results = await service.search_restaurants(
                operator_id=operator_id,
                query=query,
                area=area,
                date=date_str,
                time=time_str,
                party_size=party_size,
            )
            return MCPResult(
                success=True,
                data={
                    "results": results,
                    "query": query,
                    "area": area,
                    "party_size": party_size,
                },
                message=f"Found {len(results)} dining option(s)",
            )
        except Exception as e:
            logger.error(f"search_restaurants error: {e}")
            return MCPResult(success=False, message=str(e))

    async def _check_dining_availability(self, operator_id: str, params: Dict) -> MCPResult:
        restaurant_name = params.get("restaurant_name", "").strip()
        date_str = params.get("date", "").strip()
        if not restaurant_name or not date_str:
            return MCPResult(success=False, message="restaurant_name and date are required")

        party_size = int(params.get("party_size") or 2)
        time_str = params.get("time")
        area = params.get("area")

        try:
            from app.services.concierge.dining_service import get_dining_service

            service = get_dining_service()
            availability = await service.check_availability(
                operator_id=operator_id,
                restaurant_name=restaurant_name,
                date=date_str,
                party_size=party_size,
                time=time_str,
                area=area,
            )
            return MCPResult(
                success=True,
                data={
                    "restaurant": availability.restaurant,
                    "date": availability.date,
                    "party_size": availability.party_size,
                    "available_times": availability.available_times,
                    "booking_url": availability.booking_url,
                    "source": availability.source,
                },
                message=f"Availability checked for {availability.restaurant}",
            )
        except Exception as e:
            logger.error(f"check_dining_availability error: {e}")
            return MCPResult(success=False, message=str(e))

    async def _create_dining_reservation(self, operator_id: str, params: Dict) -> MCPResult:
        required = ["restaurant_name", "date", "time", "party_size", "guest_name"]
        missing = [k for k in required if not params.get(k)]
        if missing:
            return MCPResult(success=False, message=f"Missing required fields: {', '.join(missing)}")

        try:
            from app.services.concierge.dining_service import get_dining_service

            service = get_dining_service()
            result = await service.create_reservation(
                operator_id=operator_id,
                restaurant_name=str(params["restaurant_name"]).strip(),
                date=str(params["date"]).strip(),
                time=str(params["time"]).strip(),
                party_size=int(params["party_size"]),
                guest_name=str(params["guest_name"]).strip(),
                guest_phone=params.get("guest_phone"),
                guest_email=params.get("guest_email"),
                special_requests=params.get("special_requests"),
                session_token=params.get("session_token"),
                db_session=params.get("_db_session"),
            )
            return MCPResult(
                success=True,
                data={
                    "success": result.success,
                    "status": result.status,
                    "message": result.message,
                    "restaurant": result.restaurant,
                    "date": result.date,
                    "time": result.time,
                    "party_size": result.party_size,
                    "confirmation_id": result.confirmation_id,
                    "booking_url": result.booking_url,
                    "source": result.source,
                },
                message=result.message,
            )
        except Exception as e:
            logger.error(f"create_dining_reservation error: {e}")
            return MCPResult(success=False, message=str(e))

    async def _check_extend_eligible(self, operator_id: str, params: Dict) -> MCPResult:
        token = params["token"]

        try:
            from app.services.concierge.guest_session import get_session_manager
            manager = get_session_manager()
            session = await manager.get_session(token)

            if not session:
                return MCPResult(success=True, data={"eligible": False, "reason": "Session not found"})

            # Check phase — only eligible near checkout
            from app.services.concierge.guest_session import SessionPhase
            if session.phase not in (SessionPhase.IN_STAY, SessionPhase.DEPARTURE_DAY):
                return MCPResult(
                    success=True,
                    data={"eligible": False, "reason": f"Wrong phase: {session.phase.value}"},
                )

            # Query DB to see if next guest arriving on checkout date
            try:
                from app.core.database import get_db_session
                from app.services.concierge.db_session_service import (
                    DatabaseSessionService,
                    DEFAULT_TENANT_ID,
                )
                svc = DatabaseSessionService(DEFAULT_TENANT_ID)
                async with get_db_session() as db:
                    eligibility = await svc.check_extend_stay_eligible(db, None)
                    # Use session_id if we have it from DB lookup
                    from sqlalchemy import select, and_
                    from db.models.concierge_sessions import ConciergeGuestSessionModel
                    row = (await db.execute(
                        select(ConciergeGuestSessionModel).where(
                            ConciergeGuestSessionModel.token == token
                        )
                    )).scalar_one_or_none()
                    if row:
                        eligibility = await svc.check_extend_stay_eligible(db, row.session_id)
                    else:
                        eligibility = {"eligible": True, "reason": "Session not in DB yet"}
            except Exception as db_err:
                logger.warning(f"Extend eligibility DB check failed: {db_err} — assuming eligible")
                eligibility = {"eligible": True, "reason": "DB check unavailable"}

            if not eligibility.get("eligible", False):
                return MCPResult(
                    success=True,
                    data={"eligible": False, "reason": eligibility.get("reason", "Not eligible")},
                )

            extra_night = session.check_out.strftime("%A, %B %d") if session.check_out else "the next day"
            return MCPResult(
                success=True,
                data={
                    "eligible": True,
                    "reason": eligibility.get("reason", "No next guest"),
                    "extra_night_date": extra_night,
                    "checkout_date": session.check_out.isoformat() if session.check_out else None,
                },
                message=f"Extend eligible: {extra_night}",
            )

        except Exception as e:
            return MCPResult(success=False, message=str(e))

    async def _get_faq_answer(self, operator_id: str, params: Dict) -> MCPResult:
        question = params["question"]
        property_code = params.get("property_code")
        tenant_id_str = params.get("tenant_id")

        # ── Fast path: property facts (zero DB, zero LLM) ────────────────────
        q = question.lower()
        prop_context: Dict[str, Any] = {}

        if property_code:
            try:
                from app.services.concierge.property_context import get_property_context
                prop = get_property_context(property_code)
                if prop:
                    prop_context = {
                        "wifi_network": prop.wifi_network,
                        "wifi_password": prop.wifi_password,
                        "check_in_time": prop.check_in_time,
                        "check_out_time": prop.check_out_time,
                    }
            except Exception:
                pass

        # Direct property fact hits (confidence >= 0.95 → bypass LLM)
        if any(w in q for w in ["wifi", "wi-fi", "internet", "network", "password"]):
            net = prop_context.get("wifi_network")
            pw = prop_context.get("wifi_password")
            if net and pw:
                return MCPResult(
                    success=True,
                    data={"answer": f"The WiFi network is **{net}** and the password is **{pw}**.", "match_type": "property_fact", "confidence": 0.98},
                    message="FAQ hit: property_fact (wifi)",
                )
        if "check" in q and any(w in q for w in ["in", "arrive", "arrival"]):
            t = prop_context.get("check_in_time", "4:00 PM")
            return MCPResult(
                success=True,
                data={"answer": f"Check-in time is **{t}**.", "match_type": "property_fact", "confidence": 0.95},
                message="FAQ hit: property_fact (check-in)",
            )
        if "check" in q and any(w in q for w in ["out", "leave", "depart", "checkout"]):
            t = prop_context.get("check_out_time", "10:00 AM")
            return MCPResult(
                success=True,
                data={"answer": f"Check-out time is **{t}**.", "match_type": "property_fact", "confidence": 0.95},
                message="FAQ hit: property_fact (check-out)",
            )

        # ── DB path: tenant FAQ + cross-property similarity search ────────────
        try:
            from uuid import UUID
            from app.core.database import get_db_session
            from app.services.messaging_brain.knowledge.property_faq import (
                best_faq_answer_with_global,
                load_property_knowledge_bundle,
                resolve_property_id_by_code,
            )

            tenant_id = UUID(tenant_id_str) if tenant_id_str else None
            if not tenant_id:
                # Fall through — no tenant context, can't do DB lookup
                return MCPResult(
                    success=True,
                    data={"answer": None, "match_type": None, "confidence": 0.0},
                    message="FAQ miss: no tenant_id",
                )

            async with get_db_session() as session:
                concierge_knowledge = {}
                if property_code:
                    property_id = await resolve_property_id_by_code(
                        session=session,
                        tenant_id=tenant_id,
                        property_code=property_code,
                    )
                    if property_id:
                        bundle = await load_property_knowledge_bundle(
                            session=session,
                            tenant_id=tenant_id,
                            property_id=property_id,
                        )
                        concierge_knowledge = bundle.concierge_knowledge

                result = await best_faq_answer_with_global(
                    session=session,
                    tenant_id=tenant_id,
                    message_text=question,
                    concierge_knowledge=concierge_knowledge,
                )

            answer = result.get("answer")
            match_type = result.get("match_type")
            score = result.get("score", 0.0)

            return MCPResult(
                success=True,
                data={"answer": answer, "match_type": match_type, "confidence": score},
                message=f"FAQ {'hit' if answer else 'miss'}: {match_type or 'none'} ({score:.2f})",
            )

        except Exception as e:
            logger.warning(f"FAQ DB lookup failed: {e} — returning miss")
            return MCPResult(
                success=True,
                data={"answer": None, "match_type": None, "confidence": 0.0},
                message=f"FAQ lookup error: {e}",
            )

    async def _record_gap(self, operator_id: str, params: Dict) -> MCPResult:
        question = params["question"]
        property_code = params.get("property_code", "")
        tenant_id_str = params.get("tenant_id")
        detected_intent = params.get("detected_intent")
        session_token = params.get("session_token", "")

        logger.info(f"[GAP] operator={operator_id} property={property_code} question={question[:100]}")

        try:
            from uuid import UUID
            from app.core.database import get_db_session
            from app.services.messaging_brain.knowledge.gap_recorder import record_gap

            tenant_id = UUID(tenant_id_str) if tenant_id_str else None
            if not tenant_id:
                # No tenant context — log locally only
                import hashlib
                gap_id = "gap_" + hashlib.md5(f"{property_code}:{question}".encode()).hexdigest()[:8]
                return MCPResult(
                    success=True,
                    data={"gap_id": gap_id, "deduped": False},
                    message=f"Gap logged (no tenant): {gap_id}",
                )

            async with get_db_session() as session:
                result = await record_gap(
                    session=session,
                    tenant_id=tenant_id,
                    question_text=question,
                    property_external_id=property_code or None,
                    stage=None,
                    channel="text",
                    source="concierge_mcp",
                    detected_intent=detected_intent,
                    metadata={"session_token": session_token, "operator_id": operator_id},
                    dedupe_window_hours=72,
                )

            return MCPResult(
                success=True,
                data={"gap_id": result["gap_id"], "deduped": result["deduped"]},
                message=f"Gap {'deduped' if result['deduped'] else 'recorded'}: {result['gap_id']}",
            )

        except Exception as e:
            logger.warning(f"Gap DB write failed: {e} — logging locally")
            import hashlib
            gap_id = "gap_" + hashlib.md5(f"{property_code}:{question}".encode()).hexdigest()[:8]
            return MCPResult(
                success=True,
                data={"gap_id": gap_id, "deduped": False},
                message=f"Gap logged (fallback): {gap_id}",
            )

    async def _find_nearby_available(self, operator_id: str, params: Dict) -> MCPResult:
        """
        Find available properties in the operator's portfolio for a date window.

        Queries canonical pms_listings / pms_bookings tables via a single
        set-based anti-join.  Supersedes the retired PortfolioAvailabilityService
        which queried the legacy properties / bookings tables with a per-property
        availability loop (O(N) queries).

        Proximity: if reference_property_code resolves to a listing with
        lat/lon in pms_listings, results are sorted by haversine distance.
        """
        check_in_str  = params.get("check_in", "")
        check_out_str = params.get("check_out", "")
        tenant_id_str = params.get("tenant_id", "")
        ref_code      = params.get("reference_property_code", "")

        if not (check_in_str and check_out_str):
            return MCPResult(
                success=False,
                message="check_in and check_out are required",
            )

        try:
            from datetime import date as _date
            check_in  = _date.fromisoformat(check_in_str)
            check_out = _date.fromisoformat(check_out_str)
        except ValueError as exc:
            return MCPResult(success=False, message=f"Invalid date format: {exc}")

        if check_out <= check_in:
            return MCPResult(success=False, message="check_out must be after check_in")

        try:
            import math as _math
            from uuid import UUID
            from sqlalchemy import text as _text
            from app.core.database import get_sync_db

            tenant_id = UUID(tenant_id_str) if tenant_id_str else None
            if not tenant_id:
                try:
                    from app.services.concierge.db_session_service import DEFAULT_TENANT_ID
                    tenant_id = DEFAULT_TENANT_ID
                except Exception:
                    return MCPResult(
                        success=False,
                        message="tenant_id required for portfolio lookup",
                    )

            cid           = str(tenant_id)
            min_bedrooms  = params.get("min_bedrooms")
            require_pool  = bool(params.get("require_pool", False))
            require_pet   = bool(params.get("require_pet_friendly", False))
            result_limit  = min(int(params.get("result_limit", 8)), 8)

            ref_lat: float = 0.0
            ref_lon: float = 0.0

            with get_sync_db() as db:
                # ── Optional: resolve reference property coords for proximity sort ─
                if ref_code:
                    ref_row = db.execute(
                        _text("""
                            SELECT latitude, longitude
                            FROM pms_listings
                            WHERE company_id = :cid
                              AND (external_id = :code OR property_name = :code)
                              AND is_active = true
                            LIMIT 1
                        """),
                        {"cid": cid, "code": ref_code},
                    ).mappings().first()
                    if ref_row:
                        ref_lat = float(ref_row.get("latitude") or 0)
                        ref_lon = float(ref_row.get("longitude") or 0)

                # ── Fail-safe: check portfolio presence ───────────────────────────
                sync_row = db.execute(
                    _text("""
                        SELECT COUNT(*) AS cnt
                        FROM pms_listings
                        WHERE company_id = :cid AND is_active = true
                    """),
                    {"cid": cid},
                ).mappings().first()

                if int((sync_row or {}).get("cnt") or 0) == 0:
                    return MCPResult(
                        success=True,
                        data={
                            "available": [],
                            "no_portfolio_data": True,
                            "check_in": check_in_str,
                            "check_out": check_out_str,
                        },
                        message=(
                            "No portfolio data — PMS not yet connected for this operator"
                        ),
                    )

                # ── Single set-based anti-join (replaces per-property loop) ───────
                rows = db.execute(
                    _text("""
                        SELECT l.id,
                               l.external_id,
                               l.property_name,
                               l.city,
                               l.state,
                               l.bedrooms,
                               l.bathrooms,
                               l.has_pool,
                               l.pet_friendly,
                               l.has_waterfront,
                               l.beach_access,
                               l.latitude,
                               l.longitude
                        FROM pms_listings l
                        WHERE l.company_id     = :cid
                          AND l.is_active      = true
                          AND l.listing_status = 'active'
                          AND (:min_bedrooms IS NULL OR l.bedrooms >= :min_bedrooms)
                          AND (:require_pool  = false  OR l.has_pool     = true)
                          AND (:require_pet   = false  OR l.pet_friendly = true)
                          AND NOT EXISTS (
                              SELECT 1
                              FROM pms_bookings b
                              WHERE b.listing_id  = l.id
                                AND b.company_id  = l.company_id
                                AND b.status      IN ('confirmed', 'pending')
                                AND b.check_in    < :check_out
                                AND b.check_out   > :check_in
                          )
                        ORDER BY l.property_name
                        LIMIT :result_limit
                    """),
                    {
                        "cid":          cid,
                        "min_bedrooms": min_bedrooms,
                        "require_pool": require_pool,
                        "require_pet":  require_pet,
                        "check_in":     check_in.isoformat(),
                        "check_out":    check_out.isoformat(),
                        "result_limit": result_limit,
                    },
                ).mappings().all()

            candidates = [dict(r) for r in rows]

            # ── Optional: proximity re-sort on the capped candidate set ───────────
            has_ref_coords = bool(ref_lat and ref_lon)
            if has_ref_coords and candidates:
                def _dist(c: Dict) -> float:
                    lat = float(c.get("latitude") or 0)
                    lon = float(c.get("longitude") or 0)
                    if not (lat and lon):
                        return 9999.0
                    dlat = _math.radians(lat - ref_lat)
                    dlon = _math.radians(lon - ref_lon)
                    a = (
                        _math.sin(dlat / 2) ** 2
                        + _math.cos(_math.radians(ref_lat))
                        * _math.cos(_math.radians(lat))
                        * _math.sin(dlon / 2) ** 2
                    )
                    return 6371.0 * 2 * _math.atan2(_math.sqrt(a), _math.sqrt(1 - a))

                for c in candidates:
                    d = _dist(c)
                    c["distance_km"] = round(d, 1) if d < 9000 else None
                candidates.sort(key=lambda c: c.get("distance_km") or 9999)

            available_list = [
                {
                    "name":          c.get("property_name", ""),
                    "external_id":   c.get("external_id", ""),
                    "city":          c.get("city", ""),
                    "state":         c.get("state", ""),
                    "bedrooms":      c.get("bedrooms"),
                    "bathrooms":     c.get("bathrooms"),
                    "has_pool":      c.get("has_pool"),
                    "pet_friendly":  c.get("pet_friendly"),
                    "beach_access":  c.get("beach_access"),
                    "has_waterfront": c.get("has_waterfront"),
                    "distance_km":   c.get("distance_km"),
                }
                for c in candidates
            ]

            logger.info(
                "[find_nearby_available] ref=%s dates=%s/%s found=%d",
                ref_code, check_in_str, check_out_str, len(available_list),
            )

            return MCPResult(
                success=True,
                data={
                    "available":    available_list,
                    "check_in":     check_in_str,
                    "check_out":    check_out_str,
                    "nights":       (check_out - check_in).days,
                    "total_candidates": len(available_list),
                },
                message=(
                    f"Found {len(available_list)} available "
                    f"propert{'y' if len(available_list) == 1 else 'ies'}"
                    + (f" near {ref_code}" if ref_code else "")
                ),
            )

        except Exception as exc:
            logger.error("find_nearby_available error: %s", exc)
            return MCPResult(success=False, message=str(exc))

    async def _get_proactive_message(self, operator_id: str, params: Dict) -> MCPResult:
        token = params["token"]

        try:
            from app.core.database import get_db_session
            from app.services.operator.stay_journey_service import get_canonical_proactive_preview_by_token

            async with get_db_session() as db:
                preview = await get_canonical_proactive_preview_by_token(
                    db,
                    token,
                    allowed_touch_types={
                        "pre_arrival_welcome",
                        "arrival_day_checkin",
                        "arrival_info",
                        "extend_offer",
                        "service_update_reassurance",
                    },
                )
            if preview:
                touch_type = str(preview.get("touch_type") or "")
                message_type_map = {
                    "pre_arrival_welcome": "welcome",
                    "arrival_day_checkin": "welcome",
                    "arrival_info": "welcome",
                    "extend_offer": "extend_offer",
                    "service_update_reassurance": "service_update",
                }
                return MCPResult(
                    success=True,
                    data={"message_type": message_type_map.get(touch_type, touch_type), "message": preview.get("message")},
                    message=f"Proactive: {touch_type or 'preview'}",
                )

            return MCPResult(success=True, data=None, message="No proactive message due")

        except Exception as e:
            logger.error(f"get_proactive_message error: {e}")
            return MCPResult(success=True, data=None, message=f"Error: {e}")
