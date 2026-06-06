"""
Concierge Guest Session and Journey persistence models.

Tables:
- concierge_guest_sessions: Active guest chat sessions
- concierge_guest_journeys: Proactive journey tracking
- concierge_journey_activities: Activity status per journey
- concierge_messages: Conversation history
- concierge_notifications: SMS/email notifications sent
"""

from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.models.core import Base, TenantMixin, TimestampMixin


class ConciergeGuestSessionModel(Base, TenantMixin, TimestampMixin):
    """
    Guest chat session for the mobile concierge.
    
    Created when operator sends SMS link to guest.
    Token is used in URL: /c/{token}
    """
    
    __tablename__ = "concierge_guest_sessions"
    
    session_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    guest_thread_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("guest_threads.guest_thread_id", ondelete="SET NULL"),
        index=True,
    )
    
    # Session token for URL (gh_xxxx format)
    token: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    
    # Property link
    property_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("properties.property_id", ondelete="SET NULL"),
        index=True,
    )
    property_code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    property_name: Mapped[str] = mapped_column(String(255), nullable=False)
    
    # Guest info
    guest_name: Mapped[str] = mapped_column(String(255), nullable=False)
    guest_phone: Mapped[str | None] = mapped_column(String(50))
    guest_email: Mapped[str | None] = mapped_column(String(255))
    num_guests: Mapped[int] = mapped_column(Integer, default=1)
    
    # Stay dates
    check_in: Mapped[date] = mapped_column(Date, nullable=False)
    check_out: Mapped[date] = mapped_column(Date, nullable=False)
    
    # Session status
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    # active, feedback_pending, closed, expired
    
    phase: Mapped[str] = mapped_column(String(20), default="pre_arrival", nullable=False)
    # pre_arrival, arrival_day, in_stay, departure_day, post_stay, expired
    
    # Stats
    conversation_count: Mapped[int] = mapped_column(Integer, default=0)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pms_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        index=True,
    )
    
    # Property context (cached amenities, etc.)
    property_context: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    
    # Operator tracking
    operator_id: Mapped[str | None] = mapped_column(String(100), index=True)
    reservation_id: Mapped[str | None] = mapped_column(String(100), index=True)

    # Feedback
    feedback_rating: Mapped[int | None] = mapped_column(Integer)  # 1-5
    feedback_text: Mapped[str | None] = mapped_column(Text)
    feedback_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    
    # Relationships
    journey: Mapped["ConciergeGuestJourneyModel"] = relationship(
        back_populates="session",
        uselist=False,
    )
    messages: Mapped[list["ConciergeMessageModel"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
    )
    notifications: Mapped[list["ConciergeNotificationModel"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
    )
    
    __table_args__ = (
        Index("ix_concierge_session_tenant_status", "tenant_id", "status"),
        Index("ix_concierge_session_tenant_property", "tenant_id", "property_code"),
        Index("ix_concierge_session_checkin", "check_in"),
        Index("ix_concierge_session_checkout", "check_out"),
    )


class ConciergeGuestJourneyModel(Base, TenantMixin, TimestampMixin):
    """
    Proactive journey tracking for a guest.
    
    Tracks what activities have been discussed, booked, declined.
    """
    
    __tablename__ = "concierge_guest_journeys"
    
    journey_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    
    session_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("concierge_guest_sessions.session_id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    
    # Welcome message
    welcome_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    welcome_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    
    # Extend stay offer
    extend_offer_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    extend_offer_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    extend_offer_response: Mapped[str | None] = mapped_column(String(20))
    # accepted, declined, no_response
    
    # Pool heat
    pool_heat_offered: Mapped[bool] = mapped_column(Boolean, default=False)
    pool_heat_accepted: Mapped[bool] = mapped_column(Boolean, default=False)
    
    # Check-in reminder
    checkin_reminder_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    checkin_reminder_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    
    # Checkout reminder
    checkout_reminder_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    checkout_reminder_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    
    # Relationships
    session: Mapped["ConciergeGuestSessionModel"] = relationship(back_populates="journey")
    activities: Mapped[list["ConciergeJourneyActivityModel"]] = relationship(
        back_populates="journey",
        cascade="all, delete-orphan",
    )
    
    __table_args__ = (
        Index("ix_concierge_journey_tenant", "tenant_id"),
    )


class ConciergeJourneyActivityModel(Base, TimestampMixin):
    """
    Individual activity status within a journey.
    
    Tracks: beach_chairs, fishing, golf, bikes, pontoon, dolphin, spa, groceries, restaurants
    """
    
    __tablename__ = "concierge_journey_activities"
    
    activity_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    
    journey_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("concierge_guest_journeys.journey_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    
    activity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # beach_chairs, fishing, golf, bikes, pontoon, dolphin, spa, groceries, restaurants
    
    status: Mapped[str] = mapped_column(String(20), default="not_discussed", nullable=False)
    # not_discussed, info_provided, booked, not_interested, handled
    
    discussed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)
    
    # Relationships
    journey: Mapped["ConciergeGuestJourneyModel"] = relationship(back_populates="activities")
    
    __table_args__ = (
        Index("ix_concierge_activity_journey_type", "journey_id", "activity_type"),
    )


class ConciergeMessageModel(Base, TimestampMixin):
    """
    Individual message in a concierge conversation.
    """
    
    __tablename__ = "concierge_messages"
    
    message_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    
    session_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("concierge_guest_sessions.session_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    
    # Direction
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    # inbound (from guest), outbound (from concierge)
    
    # Content
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(String(20), default="text")
    # text, voice_transcript, system
    
    # Processing
    detected_intent: Mapped[str | None] = mapped_column(String(100))
    was_quick_answer: Mapped[bool] = mapped_column(Boolean, default=False)
    response_time_ms: Mapped[int | None] = mapped_column(Integer)
    
    # Relationships
    session: Mapped["ConciergeGuestSessionModel"] = relationship(back_populates="messages")
    
    __table_args__ = (
        Index("ix_concierge_message_session_created", "session_id", "created_at"),
    )


class ConciergeNotificationModel(Base, TimestampMixin):
    """
    SMS/Email notifications sent to guests.
    """
    
    __tablename__ = "concierge_notifications"
    
    notification_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    
    session_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("concierge_guest_sessions.session_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    
    # Type
    notification_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # welcome, extend_offer, checkin_reminder, checkout_reminder, custom
    
    # Channel
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    # sms, email
    
    # Recipient
    recipient: Mapped[str] = mapped_column(String(255), nullable=False)
    # Phone number or email
    
    # Content
    subject: Mapped[str | None] = mapped_column(String(255))  # For email
    body: Mapped[str] = mapped_column(Text, nullable=False)
    
    # Status
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    # pending, sent, delivered, failed
    
    # External tracking
    external_id: Mapped[str | None] = mapped_column(String(255))  # Twilio SID, etc.
    error_message: Mapped[str | None] = mapped_column(Text)
    
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    
    # Relationships
    session: Mapped["ConciergeGuestSessionModel"] = relationship(back_populates="notifications")
    
    __table_args__ = (
        Index("ix_concierge_notification_session_type", "session_id", "notification_type"),
        Index("ix_concierge_notification_status", "status"),
    )
