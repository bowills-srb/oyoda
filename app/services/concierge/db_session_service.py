"""
Database-backed Guest Session Service.

Replaces the in-memory session management with PostgreSQL persistence.
"""

from datetime import date, datetime, timedelta
from typing import Optional, List, Dict, Any
from uuid import UUID, uuid4
import secrets
import logging

from sqlalchemy import select, and_, or_, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db.models.concierge_sessions import (
    ConciergeGuestSessionModel,
    ConciergeGuestJourneyModel,
    ConciergeJourneyActivityModel,
    ConciergeMessageModel,
)
from app.services.concierge.guest_thread_service import get_guest_thread_service
from app.services.events.event_triggers import EventSeverity, EventType, emit_event

logger = logging.getLogger(__name__)


def generate_token() -> str:
    """Generate a unique session token."""
    return f"gh_{secrets.token_urlsafe(16)}"


class DatabaseSessionService:
    """
    Database-backed session management for guest concierge.
    """
    
    def __init__(self, tenant_id: UUID):
        self.tenant_id = tenant_id
    
    # =========================================================================
    # Session CRUD
    # =========================================================================
    
    async def create_session(
        self,
        db: AsyncSession,
        property_id: Optional[UUID],
        property_code: str,
        property_name: str,
        guest_name: str,
        guest_phone: Optional[str],
        guest_email: Optional[str],
        check_in: date,
        check_out: date,
        num_guests: int = 1,
        reservation_id: Optional[str] = None,
        property_context: Optional[Dict] = None,
    ) -> ConciergeGuestSessionModel:
        """
        Create a new guest session.
        
        Also creates the associated journey with all activity types.
        """
        token = generate_token()
        session_id = uuid4()
        guest_thread_id = await get_guest_thread_service().ensure_session_thread(
            db,
            tenant_id=str(self.tenant_id),
            property_code=property_code,
            guest_name=guest_name,
            session_token=token,
        )
        
        # Determine initial phase
        today = date.today()
        if check_in > today:
            phase = "pre_arrival"
        elif check_in == today:
            phase = "arrival_day"
        elif check_out > today:
            phase = "in_stay"
        elif check_out == today:
            phase = "departure_day"
        else:
            phase = "post_stay"
        
        # Create session
        session = ConciergeGuestSessionModel(
            session_id=session_id,
            guest_thread_id=UUID(guest_thread_id),
            tenant_id=self.tenant_id,
            token=token,
            property_id=property_id,
            reservation_id=reservation_id,
            property_code=property_code,
            property_name=property_name,
            guest_name=guest_name,
            guest_phone=guest_phone,
            guest_email=guest_email,
            check_in=check_in,
            check_out=check_out,
            num_guests=num_guests,
            status="active",
            phase=phase,
            property_context=property_context or {},
        )
        db.add(session)
        
        # Create journey
        journey = ConciergeGuestJourneyModel(
            journey_id=uuid4(),
            tenant_id=self.tenant_id,
            session_id=session_id,
        )
        db.add(journey)
        
        # Create activity entries for all types
        activity_types = [
            "beach_chairs", "fishing", "golf", "bikes", 
            "pontoon", "dolphin", "spa", "groceries", "restaurants"
        ]
        for act_type in activity_types:
            activity = ConciergeJourneyActivityModel(
                activity_id=uuid4(),
                journey_id=journey.journey_id,
                activity_type=act_type,
                status="not_discussed",
            )
            db.add(activity)
        
        await db.commit()
        await db.refresh(session)

        emit_event(
            EventType.SESSION_CREATED,
            f"Guest session created for {guest_name} at {property_name}",
            severity=EventSeverity.MEDIUM,
            tenant_id=self.tenant_id,
            data={
                "session_id": str(session.session_id),
                "guest_thread_id": str(session.guest_thread_id) if session.guest_thread_id else guest_thread_id,
                "session_token": token,
                "property_code": property_code,
                "reservation_id": reservation_id,
            },
        )
        
        logger.info(f"Created session {token} for {guest_name} at {property_name}")
        return session
    
    async def get_session_by_token(
        self,
        db: AsyncSession,
        token: str,
        tenant_agnostic: bool = False,
    ) -> Optional[ConciergeGuestSessionModel]:
        """
        Get a session by its token.

        Parameters
        ----------
        tenant_agnostic : bool
            When True the query omits the tenant_id filter.  Use this for the
            *initial* token lookup where the caller does not yet know which
            tenant owns the token.  After the row is returned, callers MUST
            re-scope any further DB operations to ``session.tenant_id``.

            When False (default) the query is scoped to ``self.tenant_id``,
            which is the correct mode for all non-initial lookups.
        """
        filters = [ConciergeGuestSessionModel.token == token]
        if not tenant_agnostic:
            filters.append(ConciergeGuestSessionModel.tenant_id == self.tenant_id)

        result = await db.execute(
            select(ConciergeGuestSessionModel)
            .options(selectinload(ConciergeGuestSessionModel.journey))
            .where(and_(*filters))
        )
        return result.scalar_one_or_none()
    
    async def get_session_by_id(
        self,
        db: AsyncSession,
        session_id: UUID,
    ) -> Optional[ConciergeGuestSessionModel]:
        """Get a session by its ID."""
        result = await db.execute(
            select(ConciergeGuestSessionModel)
            .options(selectinload(ConciergeGuestSessionModel.journey))
            .where(
                and_(
                    ConciergeGuestSessionModel.session_id == session_id,
                    ConciergeGuestSessionModel.tenant_id == self.tenant_id,
                )
            )
        )
        return result.scalar_one_or_none()
    
    async def list_sessions(
        self,
        db: AsyncSession,
        property_code: Optional[str] = None,
        status: Optional[str] = None,
        phase: Optional[str] = None,
        check_in_after: Optional[date] = None,
        check_in_before: Optional[date] = None,
        limit: int = 100,
        tenant_id=None,  # Override self.tenant_id for multi-operator scoping
    ) -> List[ConciergeGuestSessionModel]:
        """List sessions with filters."""
        effective_tenant = tenant_id if tenant_id is not None else self.tenant_id
        query = select(ConciergeGuestSessionModel).where(
            ConciergeGuestSessionModel.tenant_id == effective_tenant
        )
        
        if property_code:
            query = query.where(ConciergeGuestSessionModel.property_code == property_code)
        if status:
            query = query.where(ConciergeGuestSessionModel.status == status)
        if phase:
            query = query.where(ConciergeGuestSessionModel.phase == phase)
        if check_in_after:
            query = query.where(ConciergeGuestSessionModel.check_in >= check_in_after)
        if check_in_before:
            query = query.where(ConciergeGuestSessionModel.check_in <= check_in_before)
        
        query = query.order_by(ConciergeGuestSessionModel.check_in.desc()).limit(limit)
        
        result = await db.execute(query)
        return list(result.scalars().all())
    
    async def update_session_phase(
        self,
        db: AsyncSession,
        session_id: UUID,
    ) -> Optional[str]:
        """
        Update session phase based on current date.
        Returns the new phase.
        """
        session = await self.get_session_by_id(db, session_id)
        if not session:
            return None
        
        today = date.today()
        
        if session.check_in > today:
            new_phase = "pre_arrival"
        elif session.check_in == today:
            new_phase = "arrival_day"
        elif session.check_out > today:
            new_phase = "in_stay"
        elif session.check_out == today:
            new_phase = "departure_day"
        else:
            new_phase = "post_stay"
            # Also mark as expired if past checkout + 24h
            if today > session.check_out + timedelta(days=1):
                session.status = "expired"
        
        if session.phase != new_phase:
            session.phase = new_phase
            await db.commit()
            logger.info(f"Session {session.token} phase updated to {new_phase}")
        
        return new_phase
    
    # =========================================================================
    # Message Handling
    # =========================================================================
    
    async def add_message(
        self,
        db: AsyncSession,
        session_id: UUID,
        direction: str,  # "inbound" or "outbound"
        content: str,
        content_type: str = "text",
        detected_intent: Optional[str] = None,
        was_quick_answer: bool = False,
        response_time_ms: Optional[int] = None,
    ) -> ConciergeMessageModel:
        """Add a message to the conversation."""
        message = ConciergeMessageModel(
            message_id=uuid4(),
            session_id=session_id,
            direction=direction,
            content=content,
            content_type=content_type,
            detected_intent=detected_intent,
            was_quick_answer=was_quick_answer,
            response_time_ms=response_time_ms,
        )
        db.add(message)
        
        # Update session stats
        await db.execute(
            update(ConciergeGuestSessionModel)
            .where(ConciergeGuestSessionModel.session_id == session_id)
            .values(
                conversation_count=ConciergeGuestSessionModel.conversation_count + 1,
                last_message_at=datetime.utcnow(),
            )
        )
        
        await db.commit()
        return message
    
    async def get_conversation_history(
        self,
        db: AsyncSession,
        session_id: UUID,
        limit: int = 50,
    ) -> List[ConciergeMessageModel]:
        """Get conversation history for a session."""
        result = await db.execute(
            select(ConciergeMessageModel)
            .where(ConciergeMessageModel.session_id == session_id)
            .order_by(ConciergeMessageModel.created_at.desc())
            .limit(limit)
        )
        messages = list(result.scalars().all())
        messages.reverse()  # Return in chronological order
        return messages
    
    # =========================================================================
    # Journey Management
    # =========================================================================
    
    async def get_journey(
        self,
        db: AsyncSession,
        session_id: UUID,
    ) -> Optional[ConciergeGuestJourneyModel]:
        """Get journey for a session."""
        result = await db.execute(
            select(ConciergeGuestJourneyModel)
            .options(selectinload(ConciergeGuestJourneyModel.activities))
            .where(ConciergeGuestJourneyModel.session_id == session_id)
        )
        return result.scalar_one_or_none()
    
    async def update_activity_status(
        self,
        db: AsyncSession,
        journey_id: UUID,
        activity_type: str,
        status: str,
        notes: Optional[str] = None,
    ) -> bool:
        """Update the status of an activity."""
        result = await db.execute(
            update(ConciergeJourneyActivityModel)
            .where(
                and_(
                    ConciergeJourneyActivityModel.journey_id == journey_id,
                    ConciergeJourneyActivityModel.activity_type == activity_type,
                )
            )
            .values(
                status=status,
                discussed_at=datetime.utcnow(),
                notes=notes,
            )
        )
        await db.commit()
        return result.rowcount > 0
    
    async def mark_welcome_sent(
        self,
        db: AsyncSession,
        journey_id: UUID,
    ) -> bool:
        """Mark welcome message as sent."""
        result = await db.execute(
            update(ConciergeGuestJourneyModel)
            .where(ConciergeGuestJourneyModel.journey_id == journey_id)
            .values(
                welcome_sent=True,
                welcome_sent_at=datetime.utcnow(),
            )
        )
        await db.commit()
        return result.rowcount > 0
    
    async def mark_extend_offer_sent(
        self,
        db: AsyncSession,
        journey_id: UUID,
    ) -> bool:
        """Mark extend stay offer as sent."""
        result = await db.execute(
            update(ConciergeGuestJourneyModel)
            .where(ConciergeGuestJourneyModel.journey_id == journey_id)
            .values(
                extend_offer_sent=True,
                extend_offer_sent_at=datetime.utcnow(),
            )
        )
        await db.commit()
        return result.rowcount > 0
    
    async def record_extend_offer_response(
        self,
        db: AsyncSession,
        journey_id: UUID,
        response: str,  # "accepted", "declined", "no_response"
    ) -> bool:
        """Record guest response to extend offer."""
        result = await db.execute(
            update(ConciergeGuestJourneyModel)
            .where(ConciergeGuestJourneyModel.journey_id == journey_id)
            .values(extend_offer_response=response)
        )
        await db.commit()
        return result.rowcount > 0
    
    # =========================================================================
    # Extend Stay Check
    # =========================================================================
    
    async def check_extend_stay_eligible(
        self,
        db: AsyncSession,
        session_id: UUID,
    ) -> Dict[str, Any]:
        """
        Check if a session is eligible for extend stay offer.
        
        Queries the bookings table to see if there's a next guest.
        """
        from db.models.core import BookingModel
        
        session = await self.get_session_by_id(db, session_id)
        if not session:
            return {"eligible": False, "reason": "Session not found"}
        
        if not session.property_id:
            return {"eligible": False, "reason": "No property linked"}
        
        # Check for next booking starting on checkout date
        result = await db.execute(
            select(BookingModel)
            .where(
                and_(
                    BookingModel.property_id == session.property_id,
                    BookingModel.start_date == session.check_out,
                    BookingModel.status.in_(["confirmed", "pending"]),
                )
            )
            .limit(1)
        )
        next_booking = result.scalar_one_or_none()
        
        if next_booking:
            return {
                "eligible": False,
                "reason": "Next guest arriving",
                "next_booking_date": session.check_out.isoformat(),
            }
        
        # Check if offer already sent
        journey = await self.get_journey(db, session_id)
        if journey and journey.extend_offer_sent:
            return {
                "eligible": False,
                "reason": "Offer already sent",
                "sent_at": journey.extend_offer_sent_at.isoformat() if journey.extend_offer_sent_at else None,
            }
        
        return {
            "eligible": True,
            "checkout_date": session.check_out.isoformat(),
            "extra_night_date": session.check_out.strftime("%A, %B %d"),
        }
    
    # =========================================================================
    # Feedback
    # =========================================================================
    
    async def record_feedback(
        self,
        db: AsyncSession,
        session_id: UUID,
        rating: int,
        text: Optional[str] = None,
    ) -> bool:
        """Record guest feedback."""
        result = await db.execute(
            update(ConciergeGuestSessionModel)
            .where(ConciergeGuestSessionModel.session_id == session_id)
            .values(
                feedback_rating=rating,
                feedback_text=text,
                feedback_at=datetime.utcnow(),
                status="closed",
            )
        )
        await db.commit()
        if result.rowcount:
            emit_event(
                EventType.SESSION_CLOSED,
                f"Guest session {session_id} closed after feedback submission",
                severity=EventSeverity.MEDIUM,
                tenant_id=self.tenant_id,
                data={"session_id": str(session_id), "rating": rating},
            )
        return result.rowcount > 0


    async def upsert_from_guest_session(
        self,
        db: AsyncSession,
        session,  # GuestSession (avoid circular import)
    ) -> None:
        """
        Upsert an in-memory GuestSession into the DB.
        Called from GuestSessionManager._save_session().
        """
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        values = {
            "token": session.token,
            "tenant_id": self.tenant_id,
            "property_code": session.property_code,
            "property_name": session.property_name,
            "guest_name": session.guest_name,
            "guest_phone": session.guest_phone,
            "guest_email": session.guest_email,
            "check_in": session.check_in,
            "check_out": session.check_out,
            "num_guests": session.num_guests,
            "status": session.status.value if hasattr(session.status, "value") else str(session.status),
            "phase": session.phase.value if hasattr(session.phase, "value") else str(session.phase),
            "conversation_count": session.conversation_count,
            "last_message_at": session.last_activity,
            "property_context": session.property_context or {},
            "feedback_rating": session.feedback.rating if session.feedback else None,
            "feedback_text": session.feedback.comments if session.feedback else None,
            "operator_id": session.operator_id,
            "reservation_id": session.reservation_id,
        }

        stmt = (
            pg_insert(ConciergeGuestSessionModel)
            .values(**values)
            .on_conflict_do_update(
                index_elements=["token"],
                set_={
                    "status": values["status"],
                    "phase": values["phase"],
                    "conversation_count": values["conversation_count"],
                    "last_message_at": values["last_message_at"],
                    "property_context": values["property_context"],
                    "feedback_rating": values["feedback_rating"],
                    "feedback_text": values["feedback_text"],
                    "operator_id": values["operator_id"],
                    "reservation_id": values["reservation_id"],
                },
            )
        )
        await db.execute(stmt)
        await db.commit()


# Default tenant ID for Beach Habitats (can be configured)
DEFAULT_TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")


def get_db_session_service(tenant_id: UUID = DEFAULT_TENANT_ID) -> DatabaseSessionService:
    """Get a database session service instance."""
    return DatabaseSessionService(tenant_id)
