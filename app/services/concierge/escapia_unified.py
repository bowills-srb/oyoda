"""
PRESERVATION STATUS (post-Phase-1, 2026-05-23):
This module is preserved for future product surface (pre-arrival,
in-stay, multi-guest, returning-guest personalization, BD-aware
messaging, etc.). It is not currently part of the active brain
runtime path. Do not delete in subsequent phases unless explicitly
retired by product decision.

When the relevant product surface is wired into the brain, this
module relocates to the appropriate messaging_brain/ subdirectory
and stops being marked as preserved.

Escapia Unified Message Pipeline

Handles the full lifecycle of messages flowing through Escapia:

PRE-BOOKING (no guest info):
  - Vrbo/Airbnb inquiry messages arrive via Escapia
  - We classify intent, generate AI draft, alert operator
  - Operator approves → reply pushed back to the ORIGINATING PLATFORM
    via Escapia's platform-specific reply endpoints

POST-BOOKING (full guest context):
  - Confirmed reservation data arrives with guest name, dates, property
  - We create a concierge session with rich context
  - AI has access to: guest profile, property amenities, market data,
    local events, beach conditions, vendor network
  - Gate codes handled with strict temporal safety (see GateCodeService)

GATE CODE SAFETY:
  Problem: If we store a gate code in the KB, a new guest could message
  before their stay and receive the PREVIOUS guest's code, or the code
  could be rotated between bookings.

  Solution: Gate codes are NEVER stored in the static KB.
  - Codes are fetched LIVE from Escapia on each request
  - Delivery is time-locked: only provided within [check_in - 2h, check_out]
  - Each delivery is logged with guest session + timestamp
  - On next booking, the previous code is considered revoked
  - If Escapia doesn't return a code, we tell the guest "your code will
    be sent closer to arrival" — never fabricate or guess
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

import httpx

logger = logging.getLogger(__name__)


# =============================================================================
# PLATFORM REPLY ROUTING
# =============================================================================
#
# Escapia surfaces messages from multiple platforms but each platform has its
# own reply endpoint. The source of the inquiry tells us which endpoint to use:
#
#   Platform      | Escapia reply endpoint
#   ------------- | -----------------------------------------------
#   Vrbo          | POST /v1/conversations/{thread_id}/messages
#   Airbnb        | POST /v1/conversations/{thread_id}/messages
#                 |   (Escapia proxies to Airbnb on our behalf)
#   HomeAway      | Same as Vrbo (same company)
#   Direct/Own    | POST /v1/messages/{thread_id}/reply  (Escapia native)
#
# Escapia normalizes this behind a single conversations API in their v2+.
# For v1, we use the reply endpoint with a platform hint.

class ReplyPlatform(str, Enum):
    VRBO     = "vrbo"
    AIRBNB   = "airbnb"
    HOMEAWAY = "homeaway"
    DIRECT   = "direct"
    UNKNOWN  = "unknown"


# =============================================================================
# GATE CODE SERVICE — temporal safety
# =============================================================================

@dataclass
class GateCodeDelivery:
    """Record of a gate code being delivered to a guest."""
    session_token: str
    property_external_id: str
    code_delivered: str
    delivered_at: datetime
    guest_name: str
    check_in: date
    check_out: date


class GateCodeService:
    """
    Time-locked gate code delivery. The core rule:

        A gate code is ONLY delivered when:
          1. The requesting session has a confirmed booking
          2. Current time >= check_in - 2 hours
          3. Current time <= check_out + 2 hours (grace for late checkouts)
          4. The code is fetched LIVE from Escapia — never from cache

    Why live fetch matters:
        - Operators rotate codes between stays
        - Escapia/smart lock systems generate the code only ~24h before check-in
        - A code issued for Guest A's stay is invalid for Guest B
        - We cannot assume a code stored yesterday is valid today

    What we do NOT do:
        - Store gate codes in the KB or property_context
        - Return a code from any static data source
        - Serve a code outside the delivery window
        - Log the full code in application logs (only last 2 chars for debugging)
    """

    DELIVERY_WINDOW_HOURS_BEFORE = 2    # Deliver code up to 2h before check-in
    DELIVERY_WINDOW_HOURS_AFTER  = 2    # Grace period after checkout

    def __init__(self, escapia_api_key: str, company_id: UUID):
        self.api_key = escapia_api_key
        self.company_id = company_id
        self.base_url = "https://api.escapia.com/v1"

    def is_within_delivery_window(
        self,
        check_in: date,
        check_out: date,
        now: Optional[datetime] = None,
    ) -> Tuple[bool, str]:
        """
        Returns (allowed, reason).

        reason explains why if not allowed — used to generate
        an appropriate guest-facing message.
        """
        now = now or datetime.utcnow()
        now_date = now.date()

        # Before window
        window_open = datetime.combine(check_in, datetime.min.time()) - timedelta(hours=self.DELIVERY_WINDOW_HOURS_BEFORE)
        if now < window_open:
            days_until = (check_in - now_date).days
            if days_until > 1:
                return False, f"too_early:{days_until}_days"
            elif days_until == 1:
                return False, "too_early:tomorrow"
            else:
                return False, "too_early:hours"

        # After window
        window_close = datetime.combine(check_out, datetime.min.time()) + timedelta(hours=self.DELIVERY_WINDOW_HOURS_AFTER)
        if now > window_close:
            return False, "stay_ended"

        return True, "within_window"

    async def get_code_for_session(
        self,
        session_token: str,
        property_external_id: str,
        check_in: date,
        check_out: date,
        guest_name: str,
        db=None,
    ) -> Dict[str, Any]:
        """
        Main entry point for gate code requests.

        Returns:
        {
            "code": str | None,          # The actual code, if deliverable
            "deliverable": bool,          # Whether we can share it now
            "reason": str,               # Human-readable explanation
            "guest_message": str,        # What to tell the guest
        }
        """
        # 1. Check temporal window
        allowed, reason = self.is_within_delivery_window(check_in, check_out)

        if not allowed:
            guest_message = self._window_closed_message(reason, check_in, guest_name)
            return {
                "code": None,
                "deliverable": False,
                "reason": reason,
                "guest_message": guest_message,
            }

        # 2. Fetch LIVE from Escapia — never from cache
        code = await self._fetch_live_code(property_external_id, check_in)

        if not code:
            # Escapia didn't return a code — could be not yet programmed
            return {
                "code": None,
                "deliverable": False,
                "reason": "code_not_available",
                "guest_message": (
                    f"Your gate code isn't showing in the system yet, {guest_name.split()[0]}. "
                    "This usually means it'll be ready within the next hour. "
                    "I'll send it to you as soon as it's available! 🔑"
                ),
            }

        # 3. Log delivery (audit trail, never log full code)
        logger.info(
            f"[GateCode] Delivering code **{code[-2:]} to {guest_name} "
            f"for {property_external_id} check_in={check_in}"
        )
        await self._log_delivery(
            db=db,
            session_token=session_token,
            property_external_id=property_external_id,
            code=code,
            guest_name=guest_name,
            check_in=check_in,
            check_out=check_out,
        )

        return {
            "code": code,
            "deliverable": True,
            "reason": "within_window",
            "guest_message": (
                f"Here's your gate/door code, {guest_name.split()[0]}! 🔑\n\n"
                f"**{code}**\n\n"
                f"This code is active for your stay ({check_in.strftime('%b %d')} – "
                f"{check_out.strftime('%b %d')}). Please don't share it with anyone not in your party."
            ),
        }

    async def _fetch_live_code(
        self,
        property_external_id: str,
        check_in: date,
    ) -> Optional[str]:
        """
        Fetch the current gate/door code from Escapia live.

        Escapia exposes access codes via:
          GET /v1/listings/{listing_id}/access-codes?check_in=YYYY-MM-DD

        The response includes the smart lock code that's been programmed
        for the upcoming stay. This is generated by the lock integration
        (Schlage, Yale, August, etc.) connected to Escapia.
        """
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(
                    f"{self.base_url}/listings/{property_external_id}/access-codes",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Accept": "application/json",
                    },
                    params={"check_in": check_in.isoformat()},
                )

                if response.status_code == 200:
                    data = response.json()
                    # Escapia may return the code under different keys
                    # depending on the lock integration
                    code = (
                        data.get("door_code")
                        or data.get("access_code")
                        or data.get("lock_code")
                        or data.get("gate_code")
                        or data.get("code")
                    )
                    # Handle nested structures
                    if not code and isinstance(data.get("codes"), list) and data["codes"]:
                        code = data["codes"][0].get("code")
                    if not code and isinstance(data.get("access_codes"), list) and data["access_codes"]:
                        code = data["access_codes"][0].get("code")
                    return str(code) if code else None

                elif response.status_code == 404:
                    logger.info(f"[GateCode] No access code endpoint for {property_external_id}")
                    return None
                else:
                    logger.warning(f"[GateCode] API error {response.status_code} for {property_external_id}")
                    return None

        except Exception as e:
            logger.error(f"[GateCode] Live fetch failed for {property_external_id}: {e}")
            return None

    def _window_closed_message(self, reason: str, check_in: date, guest_name: str) -> str:
        """Generate an appropriate guest-facing message when code can't be delivered."""
        first_name = guest_name.split()[0]

        if reason.startswith("too_early"):
            detail = reason.split(":")[-1] if ":" in reason else ""
            if "days" in detail:
                days = detail.split("_")[0]
                return (
                    f"You're all set, {first_name}! Your gate/door code will be sent to you "
                    f"closer to your arrival — typically within 2 hours of check-in on "
                    f"{check_in.strftime('%B %d')}. I'll make sure you have it before you need it! 🔑"
                )
            elif detail == "tomorrow":
                return (
                    f"Almost time, {first_name}! Your access code will come through tomorrow, "
                    f"within 2 hours of your {check_in.strftime('%I:%M %p')} check-in. "
                    f"We'll make sure it's ready for you! 🔑"
                )
            else:
                return (
                    f"You're so close, {first_name}! Your code will be ready for you "
                    f"within the next hour or two. I'll send it as soon as it's active. 🔑"
                )
        elif reason == "stay_ended":
            return (
                f"It looks like your stay has ended — I hope you had a wonderful time, {first_name}! "
                f"If you're having any trouble checking out, please call us directly."
            )
        else:
            return (
                f"Your access code will be sent closer to check-in on "
                f"{check_in.strftime('%B %d')}, {first_name}. I'll make sure you have "
                f"everything you need before arrival! 🔑"
            )

    async def _log_delivery(
        self,
        db,
        session_token: str,
        property_external_id: str,
        code: str,
        guest_name: str,
        check_in: date,
        check_out: date,
    ) -> None:
        """Log that a code was delivered — for audit and debugging."""
        if not db:
            return
        try:
            from sqlalchemy import text
            await db.execute(
                text("""
                    INSERT INTO gate_code_deliveries (
                        session_token, property_external_id,
                        code_suffix, guest_name,
                        check_in, check_out, delivered_at
                    ) VALUES (
                        :token, :prop_id,
                        :suffix, :guest,
                        :check_in, :check_out, NOW()
                    )
                """),
                {
                    "token": session_token,
                    "prop_id": property_external_id,
                    "suffix": code[-3:] if len(code) >= 3 else code,  # Only log last 3 chars
                    "guest": guest_name,
                    "check_in": check_in,
                    "check_out": check_out,
                },
            )
            await db.commit()
        except Exception as e:
            logger.warning(f"[GateCode] Delivery log failed (non-fatal): {e}")


# =============================================================================
# POST-BOOKING SESSION ENRICHMENT
# =============================================================================

@dataclass
class BookingSessionContext:
    """
    Rich context assembled when a booking is confirmed.
    Feeds the concierge AI with everything it needs for in-stay conversations.
    """
    # Guest identity
    guest_name: str
    guest_first_name: str
    guest_phone: Optional[str]
    guest_email: Optional[str]

    # Booking
    booking_id: str
    external_booking_id: str
    check_in: date
    check_out: date
    nights: int
    guest_count: int
    booking_channel: str        # vrbo / airbnb / direct

    # Property
    property_external_id: str
    property_name: str
    address: str
    city: str
    state: str
    bedrooms: int
    bathrooms: float
    max_guests: int
    has_pool: bool
    pool_heated: bool
    has_hot_tub: bool
    has_waterfront: bool
    waterfront_type: Optional[str]
    beach_access: Optional[str]
    pet_friendly: bool
    latitude: Optional[float]
    longitude: Optional[float]

    # Operator
    company_id: UUID
    operator_name: str
    concierge_name: str = "Coral"
    support_phone: Optional[str] = None

    # Market context (populated async after session creation)
    market_name: Optional[str] = None
    beach_flag_status: Optional[str] = None
    local_events_this_week: List[str] = field(default_factory=list)
    vendor_highlights: List[str] = field(default_factory=list)

    # Gate code (NEVER pre-loaded — fetched on demand)
    # gate_code is intentionally NOT a field here

    @property
    def days_until_checkin(self) -> int:
        return max(0, (self.check_in - date.today()).days)

    @property
    def is_active_stay(self) -> bool:
        today = date.today()
        return self.check_in <= today <= self.check_out

    def to_concierge_context(self) -> Dict[str, Any]:
        """Compact dict for injecting into concierge session."""
        return {
            # Guest
            "guest_name": self.guest_name,
            "guest_first_name": self.guest_first_name,
            "guest_phone": self.guest_phone,
            "guest_email": self.guest_email,
            "guest_count": self.guest_count,
            "booking_channel": self.booking_channel,
            # Property
            "property_name": self.property_name,
            "property_external_id": self.property_external_id,
            "address": self.address,
            "city": self.city,
            "state": self.state,
            "bedrooms": self.bedrooms,
            "bathrooms": self.bathrooms,
            "max_guests": self.max_guests,
            "has_pool": self.has_pool,
            "pool_heated": self.pool_heated,
            "has_hot_tub": self.has_hot_tub,
            "has_waterfront": self.has_waterfront,
            "waterfront_type": self.waterfront_type,
            "beach_access": self.beach_access,
            "pet_friendly": self.pet_friendly,
            "latitude": self.latitude,
            "longitude": self.longitude,
            # Stay
            "check_in": self.check_in.isoformat(),
            "check_out": self.check_out.isoformat(),
            "nights": self.nights,
            # Market
            "market_name": self.market_name,
            "beach_flag_status": self.beach_flag_status,
            "local_events": self.local_events_this_week,
            # Operator
            "operator_name": self.operator_name,
            "concierge_name": self.concierge_name,
            "support_phone": self.support_phone,
            # Gate code — intentionally absent. Fetched on-demand by GateCodeService.
        }


class BookingSessionBuilder:
    """
    Assembles a BookingSessionContext from a confirmed Escapia booking.
    Called from the PMS ingest worker after a booking is confirmed.
    """

    def __init__(self, api_key: str, company_id: UUID):
        self.api_key = api_key
        self.company_id = company_id
        self.base_url = "https://api.escapia.com/v1"

    async def build_from_booking(
        self,
        booking: Any,          # CanonicalBooking from pms_connectors
        listing: Any,          # CanonicalListing from pms_connectors
        company_context: Dict[str, Any],
        db=None,
    ) -> BookingSessionContext:
        """
        Build a rich session context from a confirmed booking.
        Fetches guest details from Escapia reservation endpoint.
        """
        # Fetch full guest details from Escapia
        guest_data = await self._fetch_guest_details(booking.external_id)

        guest_name = guest_data.get("guest_name", "Guest")
        first_name = guest_name.split()[0] if guest_name else "Guest"

        ctx = BookingSessionContext(
            # Guest identity
            guest_name=guest_name,
            guest_first_name=first_name,
            guest_phone=guest_data.get("guest_phone"),
            guest_email=guest_data.get("guest_email"),

            # Booking
            booking_id=str(getattr(booking, "id", "")),
            external_booking_id=booking.external_id,
            check_in=booking.check_in,
            check_out=booking.check_out,
            nights=booking.nights,
            guest_count=booking.guest_count or 1,
            booking_channel=booking.booking_channel or "direct",

            # Property
            property_external_id=listing.external_id,
            property_name=listing.property_name or "",
            address=listing.address_line1 or "",
            city=listing.city or "",
            state=listing.state or "",
            bedrooms=listing.bedrooms or 0,
            bathrooms=listing.bathrooms or 0,
            max_guests=getattr(listing, "max_guests", listing.bedrooms * 2) if listing.bedrooms else 4,
            has_pool=listing.has_pool,
            pool_heated=listing.pool_heated,
            has_hot_tub=listing.has_hot_tub,
            has_waterfront=listing.has_waterfront,
            waterfront_type=listing.waterfront_type,
            beach_access=listing.beach_access,
            pet_friendly=listing.pet_friendly,
            latitude=listing.latitude,
            longitude=listing.longitude,

            # Operator
            company_id=self.company_id,
            operator_name=company_context.get("name", "Your Host"),
            concierge_name=company_context.get("concierge_name", "Coral"),
            support_phone=company_context.get("support_phone"),
        )

        # Enrich with market context (best-effort, non-blocking)
        await self._enrich_market_context(ctx)

        return ctx

    async def _fetch_guest_details(self, reservation_id: str) -> Dict[str, Any]:
        """
        Fetch full reservation details from Escapia including guest contact info.
        This is available post-booking — not during inquiry phase.
        """
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(
                    f"{self.base_url}/reservations/{reservation_id}",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Accept": "application/json",
                    },
                )
                if response.status_code == 200:
                    data = response.json()
                    # Escapia nests guest info under "guest" or "traveler"
                    guest = data.get("guest", data.get("traveler", data))
                    return {
                        "guest_name": (
                            guest.get("name")
                            or f"{guest.get('first_name', '')} {guest.get('last_name', '')}".strip()
                            or "Guest"
                        ),
                        "guest_phone": guest.get("phone") or guest.get("mobile"),
                        "guest_email": guest.get("email"),
                    }
        except Exception as e:
            logger.warning(f"[BookingSession] Could not fetch guest details for {reservation_id}: {e}")
        return {"guest_name": "Guest", "guest_phone": None, "guest_email": None}

    async def _enrich_market_context(self, ctx: BookingSessionContext) -> None:
        """
        Add market/local context to the session — beach conditions, events, etc.
        Non-blocking: failures don't prevent session creation.
        """
        try:
            from app.services.local.local_intelligence import get_local_intelligence
            local = get_local_intelligence()
            intel = await local.get_conditions_summary(ctx.property_name)
            ctx.beach_flag_status = intel.get("status_label")
        except Exception:
            pass

        try:
            from app.services.local.event_service import get_event_service
            events = get_event_service()
            upcoming = await events.get_events_this_week(ctx.city or ctx.state)
            ctx.local_events_this_week = [e.get("name", "") for e in (upcoming or [])[:3]]
        except Exception:
            pass


# =============================================================================
# UNIFIED ESCAPIA MESSAGE HANDLER
# =============================================================================

class EscapiaUnifiedMessageHandler:
    """
    Single entry point for all Escapia-sourced messages.

    Routes by message type:
      - inquiry (pre-booking) → InquiryPipeline → operator approval → platform reply
      - in_stay (post-booking) → concierge session → AI response → guest channel (RCS/SMS)
    """

    def __init__(self, api_key: str, company_id: UUID):
        self.api_key = api_key
        self.company_id = company_id
        self.base_url = "https://api.escapia.com/v1"
        self._gate_code_svc = GateCodeService(api_key, company_id)
        self._session_builder = BookingSessionBuilder(api_key, company_id)

    def _auth_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def send_platform_reply(
        self,
        thread_id: str,
        platform: str,
        reply_text: str,
        draft_id: str,
        db=None,
    ) -> bool:
        """
        Push an approved reply back to the originating platform via Escapia.

        Escapia handles the platform routing — we send to one endpoint and
        Escapia proxies the reply to Vrbo or Airbnb on our behalf.

        Both v1 and v2 Escapia API patterns are attempted.
        """
        # Try conversations endpoint first (v2 pattern)
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Primary: conversations API (works for all platforms)
                response = await client.post(
                    f"{self.base_url}/conversations/{thread_id}/messages",
                    headers=self._auth_headers(),
                    json={
                        "body": reply_text,
                        "type": "host_reply",
                    },
                )

                if response.status_code in (200, 201):
                    logger.info(f"[EscapiaReply] ✓ Reply sent to {platform} via conversations API, thread={thread_id}")
                    await self._update_draft_status(db, draft_id, "replied", reply_text)
                    return True

                # Fallback: messages reply endpoint (v1 pattern)
                if response.status_code == 404:
                    response = await client.post(
                        f"{self.base_url}/messages/{thread_id}/reply",
                        headers=self._auth_headers(),
                        json={"message": reply_text},
                    )
                    if response.status_code in (200, 201):
                        logger.info(f"[EscapiaReply] ✓ Reply sent via messages API, thread={thread_id}")
                        await self._update_draft_status(db, draft_id, "replied", reply_text)
                        return True

                logger.error(f"[EscapiaReply] Failed: {response.status_code} {response.text[:200]}")
                return False

        except Exception as e:
            logger.error(f"[EscapiaReply] Exception sending reply: {e}")
            return False

    async def _update_draft_status(
        self,
        db,
        draft_id: str,
        status: str,
        final_reply: str,
    ) -> None:
        if not db:
            return
        try:
            from sqlalchemy import text
            await db.execute(
                text("""
                    UPDATE pre_booking_inquiries
                    SET status = :status,
                        final_reply = :reply,
                        replied_at = NOW()
                    WHERE draft_id = :draft_id
                """),
                {"status": status, "reply": final_reply, "draft_id": draft_id},
            )
            await db.commit()
        except Exception as e:
            logger.warning(f"[EscapiaReply] DB update failed: {e}")

    async def handle_guest_gate_code_request(
        self,
        message: str,
        session_token: str,
        property_external_id: str,
        check_in: date,
        check_out: date,
        guest_name: str,
        db=None,
    ) -> Optional[str]:
        """
        Intercept gate/door code requests from in-stay guests.
        Returns the appropriate response, or None if not a code request.

        Called from the main AI pipeline BEFORE the LLM — if we return
        a string here, the LLM never sees the request (saves tokens + latency).
        """
        msg_lower = message.lower()
        is_code_request = any(
            phrase in msg_lower for phrase in [
                "gate code", "door code", "lock code", "access code",
                "entry code", "code to get in", "code for the door",
                "code for the gate", "keypad code", "front door code",
                "what's the code", "what is the code", "the code",
                "key code", "pin code",
            ]
        )

        if not is_code_request:
            return None

        result = await self._gate_code_svc.get_code_for_session(
            session_token=session_token,
            property_external_id=property_external_id,
            check_in=check_in,
            check_out=check_out,
            guest_name=guest_name,
            db=db,
        )

        return result["guest_message"]

    async def create_session_from_confirmed_booking(
        self,
        booking: Any,
        listing: Any,
        company_context: Dict[str, Any],
        db=None,
    ) -> Optional[str]:
        """
        Called when a booking transitions to confirmed status.
        Creates a rich concierge session with full guest and property context.
        Returns the session token.
        """
        try:
            # Build rich context
            ctx = await self._session_builder.build_from_booking(
                booking=booking,
                listing=listing,
                company_context=company_context,
                db=db,
            )

            # Only create sessions for bookings with guest phone
            # (otherwise we can't reach the guest via RCS/SMS)
            if not ctx.guest_phone:
                logger.info(
                    f"[BookingSession] No guest phone for booking {booking.external_id} "
                    "— session created but messaging unavailable until guest initiates"
                )

            # Create the DB session
            from app.services.concierge.db_session_service import DatabaseSessionService
            svc = DatabaseSessionService(self.company_id)

            if db:
                session = await svc.create_session(
                    db=db,
                    property_id=None,
                    reservation_id=booking.external_id,
                    property_code=listing.external_id,
                    property_name=ctx.property_name,
                    guest_name=ctx.guest_name,
                    guest_phone=ctx.guest_phone,
                    guest_email=ctx.guest_email,
                    check_in=ctx.check_in,
                    check_out=ctx.check_out,
                    num_guests=ctx.guest_count,
                    property_context=ctx.to_concierge_context(),
                )
                token = session.token
                logger.info(
                    f"[BookingSession] Created session {token} for "
                    f"{ctx.guest_name} @ {ctx.property_name} "
                    f"({ctx.check_in} – {ctx.check_out})"
                )
                return token

        except Exception as e:
            logger.error(f"[BookingSession] Failed to create session: {e}")

        return None


# =============================================================================
# INTEGRATION WITH AI CONCIERGE PIPELINE
# =============================================================================

async def intercept_gate_code_request(
    message: str,
    session_data: Dict[str, Any],
    property_external_id: str,
    session_token: str,
    company_id: UUID,
    api_key: str,
    db=None,
) -> Optional[str]:
    """
    Drop-in interceptor for the AI concierge pipeline.

    Call this BEFORE get_ai_response(). If it returns a string,
    return that directly — no LLM call needed.

    Usage in ai_concierge.py (Step 1.5):
        gate_response = await intercept_gate_code_request(...)
        if gate_response:
            return gate_response
        # ... continue to escalation check, FAQ, LLM, etc.
    """
    check_in_str = session_data.get("check_in")
    check_out_str = session_data.get("check_out")

    if not check_in_str or not check_out_str:
        return None

    try:
        check_in = date.fromisoformat(check_in_str[:10])
        check_out = date.fromisoformat(check_out_str[:10])
    except (ValueError, TypeError):
        return None

    handler = EscapiaUnifiedMessageHandler(
        api_key=api_key,
        company_id=company_id,
    )

    return await handler.handle_guest_gate_code_request(
        message=message,
        session_token=session_token,
        property_external_id=property_external_id,
        check_in=check_in,
        check_out=check_out,
        guest_name=session_data.get("guest_name", "Guest"),
        db=db,
    )


# =============================================================================
# DB MIGRATION
# =============================================================================

MIGRATION_SQL = """
-- Gate code delivery audit log
-- We NEVER store the full code — only the last 3 chars for debugging
CREATE TABLE IF NOT EXISTS gate_code_deliveries (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_token        TEXT NOT NULL,
    property_external_id TEXT NOT NULL,
    code_suffix          TEXT NOT NULL,         -- Last 3 chars only
    guest_name           TEXT NOT NULL,
    check_in             DATE NOT NULL,
    check_out            DATE NOT NULL,
    delivered_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gate_code_property
    ON gate_code_deliveries (property_external_id, check_in DESC);

-- Add property_external_id to concierge sessions (links session to PMS listing)
ALTER TABLE concierge_guest_sessions
    ADD COLUMN IF NOT EXISTS property_external_id TEXT,
    ADD COLUMN IF NOT EXISTS booking_channel       TEXT DEFAULT 'direct',
    ADD COLUMN IF NOT EXISTS guest_count           INTEGER DEFAULT 1;

-- Add gate_code_requested_at so we can track if a guest has asked
ALTER TABLE concierge_guest_sessions
    ADD COLUMN IF NOT EXISTS gate_code_last_requested TIMESTAMPTZ;
"""


# =============================================================================
# FACTORY
# =============================================================================

def get_escapia_unified_handler(company_id: UUID) -> EscapiaUnifiedMessageHandler:
    """Get a unified handler for one operator."""
    from app.services.connectors.integration_gateway import (
        get_integration_credential_store, IntegrationProvider,
    )
    store = get_integration_credential_store()
    creds = store.get_credentials(company_id, IntegrationProvider.ESCAPIA)
    api_key = creds.get("api_key", "")
    return EscapiaUnifiedMessageHandler(api_key=api_key, company_id=company_id)


def get_gate_code_service(company_id: UUID) -> GateCodeService:
    """Get a gate code service for one operator."""
    from app.services.connectors.integration_gateway import (
        get_integration_credential_store, IntegrationProvider,
    )
    store = get_integration_credential_store()
    creds = store.get_credentials(company_id, IntegrationProvider.ESCAPIA)
    api_key = creds.get("api_key", "")
    return GateCodeService(api_key=api_key, company_id=company_id)
