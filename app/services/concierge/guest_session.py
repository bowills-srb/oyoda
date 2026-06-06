"""
Guest Session Manager

Handles:
- Generating unique guest tokens for concierge links
- Session state management with operator branding
- Session expiration after checkout
- Guest feedback collection
- Token validation

Each guest gets a unique token (e.g., gh_a8f3k2x9) that:
- Identifies their specific reservation
- Provides full property context
- Includes operator branding (logo, colors)
- Expires 24 hours after checkout
"""

import secrets
import logging
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta, timezone
from typing import Optional, Dict, Any, List
from enum import Enum
from uuid import UUID
import json

logger = logging.getLogger(__name__)


class SessionPhase(str, Enum):
    """Guest journey phase affects concierge behavior"""
    PRE_ARRIVAL = "pre_arrival"      # Before check-in date
    ARRIVAL_DAY = "arrival_day"       # Day of check-in
    IN_STAY = "in_stay"               # During stay
    DEPARTURE_DAY = "departure_day"   # Day of check-out
    POST_STAY = "post_stay"           # After check-out (feedback window)
    EXPIRED = "expired"               # Session closed


class SessionStatus(str, Enum):
    """Session status"""
    ACTIVE = "active"
    FEEDBACK_PENDING = "feedback_pending"  # Post-checkout, awaiting feedback
    CLOSED = "closed"                       # Feedback received or expired


@dataclass
class GuestFeedback:
    """Guest feedback at end of stay"""
    rating: int  # 1-5 stars
    would_recommend: bool
    comments: Optional[str] = None
    submitted_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    # Specific feedback areas
    property_rating: Optional[int] = None
    concierge_rating: Optional[int] = None
    cleanliness_rating: Optional[int] = None
    
    def to_dict(self) -> dict:
        return {
            "rating": self.rating,
            "would_recommend": self.would_recommend,
            "comments": self.comments,
            "submitted_at": self.submitted_at.isoformat(),
            "property_rating": self.property_rating,
            "concierge_rating": self.concierge_rating,
            "cleanliness_rating": self.cleanliness_rating,
        }


@dataclass
class GuestSession:
    """
    Guest concierge session with operator branding.
    
    Each guest gets a unique token that identifies their reservation,
    provides personalized property context, and displays operator branding.
    """
    token: str
    reservation_id: str
    property_id: str
    property_code: str
    property_name: str
    
    # Guest info
    guest_first_name: str
    guest_last_name: str
    guest_email: Optional[str] = None
    guest_phone: Optional[str] = None
    
    # Stay details
    check_in: date = None
    check_out: date = None
    num_guests: int = 1
    special_requests: Optional[str] = None
    
    # Property context (WiFi, codes, amenities, etc.)
    property_context: Dict[str, Any] = field(default_factory=dict)

    # Canonical tenant scope
    tenant_id: Optional[UUID] = None
    
    # Operator/Branding
    operator_id: str = "op_beach_habitats"
    operator_name: str = "Beach Habitats"
    operator_logo_url: Optional[str] = None
    operator_logo_dark_url: Optional[str] = None
    operator_primary_color: str = "#0ea5e9"
    operator_support_phone: Optional[str] = None
    operator_support_email: Optional[str] = None
    
    # Concierge persona
    concierge_name: str = "Oyvo"
    concierge_emoji: str = "🐚"
    
    # Session state
    status: SessionStatus = SessionStatus.ACTIVE
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_activity: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    conversation_count: int = 0
    
    # Feedback
    feedback: Optional[GuestFeedback] = None
    feedback_requested_at: Optional[datetime] = None
    
    # Expiration (hours after checkout)
    expires_hours_after_checkout: int = 24

    def __post_init__(self) -> None:
        """Normalize tenant_id to UUID for legacy constructor call sites."""
        if self.tenant_id is not None and not isinstance(self.tenant_id, UUID):
            try:
                self.tenant_id = UUID(str(self.tenant_id))
            except (ValueError, TypeError) as exc:
                raise ValueError(
                    "GuestSession.tenant_id must be a valid UUID or UUID-parseable "
                    f"string, got {self.tenant_id!r}: {exc}"
                ) from exc
    
    @property
    def guest_name(self) -> str:
        return f"{self.guest_first_name} {self.guest_last_name}"
    
    @property
    def nights(self) -> int:
        if self.check_in and self.check_out:
            return (self.check_out - self.check_in).days
        return 0
    
    @property
    def phase(self) -> SessionPhase:
        """Determine current phase of guest journey"""
        # Check if expired first
        if self.status == SessionStatus.CLOSED:
            return SessionPhase.EXPIRED
        
        if self.is_expired:
            return SessionPhase.EXPIRED
            
        today = date.today()
        
        if not self.check_in or not self.check_out:
            return SessionPhase.PRE_ARRIVAL
            
        if today < self.check_in:
            return SessionPhase.PRE_ARRIVAL
        elif today == self.check_in:
            return SessionPhase.ARRIVAL_DAY
        elif today == self.check_out:
            return SessionPhase.DEPARTURE_DAY
        elif self.check_in < today < self.check_out:
            return SessionPhase.IN_STAY
        else:
            return SessionPhase.POST_STAY
    
    @property
    def is_in_stay(self) -> bool:
        """Check if guest is currently in-stay (for beach flag display)"""
        return self.phase in (SessionPhase.ARRIVAL_DAY, SessionPhase.IN_STAY, SessionPhase.DEPARTURE_DAY)
    
    @property
    def is_expired(self) -> bool:
        """Check if session has expired (24 hours after checkout)"""
        if not self.check_out:
            return False
        
        expiration_time = datetime.combine(
            self.check_out, 
            datetime.min.time()
        ) + timedelta(hours=self.expires_hours_after_checkout)
        
        return datetime.now(timezone.utc).replace(tzinfo=None) > expiration_time
    
    @property
    def should_request_feedback(self) -> bool:
        """Check if we should ask for feedback"""
        return (
            self.phase in (SessionPhase.DEPARTURE_DAY, SessionPhase.POST_STAY) and
            self.feedback is None and
            self.status == SessionStatus.ACTIVE
        )
    
    @property
    def days_until_checkin(self) -> int:
        if not self.check_in:
            return 0
        return max(0, (self.check_in - date.today()).days)
    
    @property
    def days_remaining(self) -> int:
        if not self.check_out:
            return 0
        return max(0, (self.check_out - date.today()).days)
    
    @property
    def hours_until_expiration(self) -> int:
        """Hours until session expires"""
        if not self.check_out:
            return 999
        
        expiration_time = datetime.combine(
            self.check_out, 
            datetime.min.time()
        ) + timedelta(hours=self.expires_hours_after_checkout)
        
        remaining = expiration_time - datetime.now(timezone.utc).replace(tzinfo=None)
        return max(0, int(remaining.total_seconds() / 3600))
    
    def to_dict(self) -> dict:
        """Serialize for storage"""
        return {
            "token": self.token,
            "reservation_id": self.reservation_id,
            "property_id": self.property_id,
            "property_code": self.property_code,
            "property_name": self.property_name,
            "guest_first_name": self.guest_first_name,
            "guest_last_name": self.guest_last_name,
            "guest_email": self.guest_email,
            "guest_phone": self.guest_phone,
            "check_in": self.check_in.isoformat() if self.check_in else None,
            "check_out": self.check_out.isoformat() if self.check_out else None,
            "num_guests": self.num_guests,
            "special_requests": self.special_requests,
            "property_context": self.property_context,
            "tenant_id": str(self.tenant_id) if self.tenant_id else None,
            # Operator
            "operator_id": self.operator_id,
            "operator_name": self.operator_name,
            "operator_logo_url": self.operator_logo_url,
            "operator_logo_dark_url": self.operator_logo_dark_url,
            "operator_primary_color": self.operator_primary_color,
            "operator_support_phone": self.operator_support_phone,
            "operator_support_email": self.operator_support_email,
            # Concierge
            "concierge_name": self.concierge_name,
            "concierge_emoji": self.concierge_emoji,
            # State
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "last_activity": self.last_activity.isoformat(),
            "conversation_count": self.conversation_count,
            # Feedback
            "feedback": self.feedback.to_dict() if self.feedback else None,
            "feedback_requested_at": self.feedback_requested_at.isoformat() if self.feedback_requested_at else None,
            "expires_hours_after_checkout": self.expires_hours_after_checkout,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "GuestSession":
        """Deserialize from storage"""
        feedback = None
        tenant_id_raw = data.get("tenant_id")
        tenant_id = UUID(tenant_id_raw) if tenant_id_raw else None
        if data.get("feedback"):
            fb = data["feedback"]
            feedback = GuestFeedback(
                rating=fb["rating"],
                would_recommend=fb["would_recommend"],
                comments=fb.get("comments"),
                submitted_at=datetime.fromisoformat(fb["submitted_at"]) if fb.get("submitted_at") else datetime.now(timezone.utc),
            )
        
        return cls(
            token=data["token"],
            reservation_id=data["reservation_id"],
            property_id=data["property_id"],
            property_code=data["property_code"],
            property_name=data["property_name"],
            guest_first_name=data["guest_first_name"],
            guest_last_name=data["guest_last_name"],
            guest_email=data.get("guest_email"),
            guest_phone=data.get("guest_phone"),
            check_in=date.fromisoformat(data["check_in"]) if data.get("check_in") else None,
            check_out=date.fromisoformat(data["check_out"]) if data.get("check_out") else None,
            num_guests=data.get("num_guests", 1),
            special_requests=data.get("special_requests"),
            property_context=data.get("property_context", {}),
            tenant_id=tenant_id,
            # Operator
            operator_id=data.get("operator_id", "op_beach_habitats"),
            operator_name=data.get("operator_name", "Beach Habitats"),
            operator_logo_url=data.get("operator_logo_url"),
            operator_logo_dark_url=data.get("operator_logo_dark_url"),
            operator_primary_color=data.get("operator_primary_color", "#0ea5e9"),
            operator_support_phone=data.get("operator_support_phone"),
            operator_support_email=data.get("operator_support_email"),
            # Concierge
            concierge_name=data.get("concierge_name", "Oyvo"),
            concierge_emoji=data.get("concierge_emoji", "🐚"),
            # State
            status=SessionStatus(data.get("status", "active")),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(timezone.utc),
            last_activity=datetime.fromisoformat(data["last_activity"]) if data.get("last_activity") else datetime.now(timezone.utc),
            conversation_count=data.get("conversation_count", 0),
            # Feedback
            feedback=feedback,
            feedback_requested_at=datetime.fromisoformat(data["feedback_requested_at"]) if data.get("feedback_requested_at") else None,
            expires_hours_after_checkout=data.get("expires_hours_after_checkout", 24),
        )


class GuestSessionManager:
    """
    Manages guest concierge sessions with operator support.
    """
    
    def __init__(self, redis_client=None, db_session=None):
        self.redis = redis_client
        self.db = db_session
        self._sessions: Dict[str, GuestSession] = {}
        
    def _generate_token(self, reservation_id: str) -> str:
        """Generate unique guest token: gh_{random_8_chars}"""
        random_part = secrets.token_urlsafe(6)[:8]
        return f"gh_{random_part}"
    
    async def create_session(
        self,
        reservation_id: str,
        property_id: str,
        property_code: str,
        property_name: str,
        guest_first_name: str,
        guest_last_name: str,
        check_in: date,
        check_out: date,
        guest_email: Optional[str] = None,
        guest_phone: Optional[str] = None,
        num_guests: int = 1,
        special_requests: Optional[str] = None,
        property_context: Optional[dict] = None,
        tenant_id: Optional[UUID] = None,
        # Operator branding
        operator_id: str = "op_beach_habitats",
        operator_name: str = "Beach Habitats",
        operator_logo_url: Optional[str] = None,
        operator_primary_color: str = "#0ea5e9",
        operator_support_phone: Optional[str] = None,
        concierge_name: str = "Oyvo",
        concierge_emoji: str = "🐚",
    ) -> GuestSession:
        """Create a new guest session for a reservation with operator branding"""
        # Check for existing session
        existing = await self.get_session_by_reservation(reservation_id)
        if existing:
            logger.info(f"Returning existing session for reservation {reservation_id}")
            return existing
        
        # Generate unique token
        token = self._generate_token(reservation_id)
        while await self.get_session(token):
            token = self._generate_token(reservation_id)
        
        session = GuestSession(
            token=token,
            reservation_id=reservation_id,
            property_id=property_id,
            property_code=property_code,
            property_name=property_name,
            guest_first_name=guest_first_name,
            guest_last_name=guest_last_name,
            guest_email=guest_email,
            guest_phone=guest_phone,
            check_in=check_in,
            check_out=check_out,
            num_guests=num_guests,
            special_requests=special_requests,
            property_context=property_context or {},
            tenant_id=tenant_id,
            # Operator
            operator_id=operator_id,
            operator_name=operator_name,
            operator_logo_url=operator_logo_url,
            operator_primary_color=operator_primary_color,
            operator_support_phone=operator_support_phone,
            concierge_name=concierge_name,
            concierge_emoji=concierge_emoji,
        )
        
        await self._save_session(session)
        logger.info(f"Created session {token} for {guest_first_name} at {property_name} ({operator_name})")
        
        return session
    
    async def create_session_with_operator(
        self,
        reservation_id: str,
        property_id: str,
        property_code: str,
        property_name: str,
        guest_first_name: str,
        guest_last_name: str,
        check_in: date,
        check_out: date,
        operator,  # Operator object
        guest_email: Optional[str] = None,
        guest_phone: Optional[str] = None,
        num_guests: int = 1,
        property_context: Optional[dict] = None,
        tenant_id: Optional[UUID] = None,
    ) -> GuestSession:
        """Create session using an Operator object for branding"""
        return await self.create_session(
            reservation_id=reservation_id,
            property_id=property_id,
            property_code=property_code,
            property_name=property_name,
            guest_first_name=guest_first_name,
            guest_last_name=guest_last_name,
            check_in=check_in,
            check_out=check_out,
            guest_email=guest_email,
            guest_phone=guest_phone,
            num_guests=num_guests,
            property_context=property_context,
            tenant_id=tenant_id,
            operator_id=operator.id,
            operator_name=operator.name,
            operator_logo_url=operator.branding.logo_url,
            operator_primary_color=operator.branding.primary_color,
            operator_support_phone=operator.branding.support_phone,
            concierge_name=operator.branding.concierge_name,
            concierge_emoji=operator.branding.concierge_emoji,
        )
    
    async def get_session(self, token: str) -> Optional[GuestSession]:
        """Get session by token — checks memory, then Redis, then DB."""
        session = self._sessions.get(token)

        # Try Redis if not in memory
        if not session and self.redis:
            try:
                raw = await self.redis.get(f"guest_session:{token}")
                if raw:
                    import json as _json
                    session = GuestSession.from_dict(_json.loads(raw))
                    self._sessions[token] = session
            except Exception as e:
                logger.warning(f"Redis get failed: {e}")

        # Fall back to DB
        if not session:
            try:
                from app.core.database import get_db_session
                from app.services.concierge.db_session_service import (
                    DatabaseSessionService,
                    DEFAULT_TENANT_ID,
                )
                # Bootstrap a service instance for tenant-agnostic lookup. The
                # tenant_id passed here is unused because tenant_agnostic=True;
                # the row's real tenant_id is preserved via _db_model_to_guest_session.
                svc = DatabaseSessionService(DEFAULT_TENANT_ID)
                async with get_db_session() as db:
                    db_session = await svc.get_session_by_token(
                        db,
                        token,
                        tenant_agnostic=True,
                    )
                if db_session:
                    session = _db_model_to_guest_session(db_session)
                    self._sessions[token] = session
            except Exception as e:
                logger.warning(f"DB session lookup failed: {e}")

        if session and session.is_expired and session.status != SessionStatus.CLOSED:
            session.status = SessionStatus.CLOSED
            await self._save_session(session)

        return session
    
    async def get_session_by_reservation(self, reservation_id: str) -> Optional[GuestSession]:
        """Get session by reservation ID"""
        for session in self._sessions.values():
            if session.reservation_id == reservation_id:
                return session
        return None
    
    async def submit_feedback(
        self,
        token: str,
        rating: int,
        would_recommend: bool,
        comments: Optional[str] = None,
    ) -> Optional[GuestSession]:
        """Submit guest feedback and close session"""
        session = await self.get_session(token)
        if not session:
            return None
        
        session.feedback = GuestFeedback(
            rating=rating,
            would_recommend=would_recommend,
            comments=comments,
        )
        session.status = SessionStatus.CLOSED
        
        await self._save_session(session)
        logger.info(f"Feedback submitted for session {token}: {rating} stars")
        
        return session
    
    async def close_session(self, token: str) -> Optional[GuestSession]:
        """Close a session (no more messages allowed)"""
        session = await self.get_session(token)
        if not session:
            return None
        
        session.status = SessionStatus.CLOSED
        await self._save_session(session)
        logger.info(f"Session {token} closed")
        
        return session
    
    async def update_session(self, session: GuestSession) -> None:
        """Update session (e.g., after conversation)"""
        session.last_activity = datetime.now(timezone.utc)
        await self._save_session(session)
    
    async def _save_session(self, session: GuestSession) -> None:
        """Persist session to memory, Redis (if available), and DB."""
        self._sessions[session.token] = session

        # Redis with 30-day TTL
        if self.redis:
            try:
                ttl = 60 * 60 * 24 * 30
                await self.redis.setex(
                    f"guest_session:{session.token}",
                    ttl,
                    json.dumps(session.to_dict()),
                )
            except Exception as e:
                logger.warning(f"Redis save failed: {e}")

        # Always persist to DB (upsert)
        try:
            from app.core.database import get_db_session
            from app.services.concierge.db_session_service import (
                DatabaseSessionService,
                DEFAULT_TENANT_ID,
            )
            tenant_for_save = session.tenant_id or DEFAULT_TENANT_ID
            if not session.tenant_id:
                logger.warning(
                    "_save_session called with session.tenant_id=None for token=%s "
                    "using DEFAULT_TENANT_ID. This is transitional debt; creation "
                    "paths should supply tenant_id.",
                    session.token,
                )
            svc = DatabaseSessionService(tenant_for_save)
            async with get_db_session() as db:
                await svc.upsert_from_guest_session(db, session)
        except Exception as e:
            logger.warning(f"DB save failed (session still in memory): {e}")
    
    async def increment_conversation_count(self, token: str) -> None:
        """Track conversation count for session"""
        session = await self.get_session(token)
        if session:
            session.conversation_count += 1
            session.last_activity = datetime.now(timezone.utc)
            await self._save_session(session)
    
    async def get_sessions_needing_feedback(self) -> List[GuestSession]:
        """Get sessions that should be prompted for feedback"""
        return [
            s for s in self._sessions.values()
            if s.should_request_feedback
        ]
    
    async def cleanup_expired_sessions(self) -> int:
        """Clean up expired sessions (call periodically)"""
        count = 0
        for session in list(self._sessions.values()):
            if session.is_expired and session.status != SessionStatus.CLOSED:
                session.status = SessionStatus.CLOSED
                await self._save_session(session)
                count += 1
        return count


def _db_model_to_guest_session(model) -> "GuestSession":
    """
    Convert a ConciergeGuestSessionModel DB row back into an in-memory GuestSession.
    Called when loading sessions from DB on cache miss.
    """
    first, *rest = (model.guest_name or "Guest").split(" ", 1)
    last = rest[0] if rest else ""
    return GuestSession(
        token=model.token,
        reservation_id=model.reservation_id or str(model.session_id),
        property_id=str(model.property_id) if model.property_id else model.property_code,
        property_code=model.property_code,
        property_name=model.property_name,
        guest_first_name=first,
        guest_last_name=last,
        guest_email=model.guest_email,
        guest_phone=model.guest_phone,
        check_in=model.check_in,
        check_out=model.check_out,
        num_guests=model.num_guests or 1,
        property_context=model.property_context or {},
        tenant_id=model.tenant_id,
        operator_id=model.operator_id or "op_beach_habitats",
        status=SessionStatus(model.status) if model.status in [s.value for s in SessionStatus] else SessionStatus.ACTIVE,
        created_at=model.created_at,
        last_activity=model.last_message_at or model.created_at,
        conversation_count=model.conversation_count or 0,
    )


def build_concierge_context(session: GuestSession) -> dict:
    """Build full context for the AI concierge"""
    phase = session.phase
    
    phase_guidance = {
        SessionPhase.PRE_ARRIVAL: f"Guest arrives in {session.days_until_checkin} days. Focus on: trip planning, restaurant reservations, activity recommendations.",
        SessionPhase.ARRIVAL_DAY: "Today is check-in day! Focus on: check-in instructions, door codes, WiFi, immediate needs.",
        SessionPhase.IN_STAY: f"Guest has {session.days_remaining} days remaining. Focus on: local recommendations, dining, activities, property questions.",
        SessionPhase.DEPARTURE_DAY: "Today is check-out day. Focus on: check-out procedures, feedback request.",
        SessionPhase.POST_STAY: "Guest has checked out. Thank them and ask for feedback.",
        SessionPhase.EXPIRED: "Session has expired.",
    }
    
    return {
        "concierge_name": session.concierge_name,
        "concierge_emoji": session.concierge_emoji,
        "guest_name": session.guest_first_name,
        "guest_full_name": session.guest_name,
        "property_name": session.property_name,
        "property_code": session.property_code,
        "operator_name": session.operator_name,
        "check_in": session.check_in.isoformat() if session.check_in else None,
        "check_out": session.check_out.isoformat() if session.check_out else None,
        "nights": session.nights,
        "num_guests": session.num_guests,
        "phase": phase.value,
        "phase_guidance": phase_guidance.get(phase, ""),
        "is_in_stay": session.is_in_stay,
        "is_expired": session.is_expired,
        "should_request_feedback": session.should_request_feedback,
        "days_until_checkin": session.days_until_checkin,
        "days_remaining": session.days_remaining,
        "special_requests": session.special_requests,
        "property": session.property_context,
        "conversation_count": session.conversation_count,
        "support_phone": session.operator_support_phone,
    }


def build_system_prompt(context: dict) -> str:
    """Build system prompt for AI concierge"""
    property_info = context.get("property", {})
    
    # Add feedback prompt if needed
    feedback_instruction = ""
    if context.get("should_request_feedback"):
        feedback_instruction = """
IMPORTANT: Guest is checking out today or has checked out. After helping with any questions, 
gently ask how their stay was and if they'd be willing to share feedback. Be warm and grateful."""
    
    prompt = f"""You are {context['concierge_name']}, the personal beach concierge for {context['guest_name']} staying at {context['property_name']}.

GUEST CONTEXT:
- Name: {context['guest_name']}
- Property: {context['property_name']} (managed by {context.get('operator_name', 'Beach Habitats')})
- Check-in: {context.get('check_in', 'TBD')}
- Check-out: {context.get('check_out', 'TBD')}
- Party size: {context.get('num_guests', 1)} guests
- Current phase: {context.get('phase_guidance', '')}

PROPERTY DETAILS:
- WiFi: {property_info.get('wifi_network', 'See welcome book')} / {property_info.get('wifi_password', 'See welcome book')}
- Door code: {property_info.get('door_code', 'Provided at check-in')}
- Check-in time: {property_info.get('check_in_time', '4:00 PM')}
- Check-out time: {property_info.get('check_out_time', '10:00 AM')}
- Parking: {property_info.get('parking_info', 'See property details')}
- Pool: {property_info.get('pool_heated', 'Check property details')}
- Beach access: {property_info.get('beach_access', 'See welcome book')}

YOUR PERSONALITY:
- Warm, friendly, knowledgeable about 30A
- Speak naturally, like a helpful local friend
- MAX 2 sentences unless detailed info requested
- Get to the point quickly
{feedback_instruction}

If guest needs human help, provide support number: {context.get('support_phone', '(850) 555-0123')}"""

    return prompt


# Singleton
_session_manager: Optional[GuestSessionManager] = None

def get_session_manager() -> GuestSessionManager:
    global _session_manager
    if _session_manager is None:
        _session_manager = GuestSessionManager()
    return _session_manager


async def init_session_manager() -> GuestSessionManager:
    """
    Initialize session manager with Redis (if REDIS_URL set) or DB-only mode.
    Call this from application lifespan instead of get_session_manager().
    """
    global _session_manager
    import os

    redis_client = None
    redis_url = os.getenv("REDIS_URL")
    if redis_url:
        try:
            import redis.asyncio as aioredis  # type: ignore
            redis_client = aioredis.from_url(redis_url, encoding="utf-8", decode_responses=True)
            await redis_client.ping()
            logger.info("Session manager: Redis connected")
        except Exception as e:
            logger.warning(f"Redis unavailable ({e}), using DB-only session persistence")
            redis_client = None
    else:
        logger.info("Session manager: No REDIS_URL set, using DB-only persistence")

    _session_manager = GuestSessionManager(redis_client=redis_client)
    return _session_manager
