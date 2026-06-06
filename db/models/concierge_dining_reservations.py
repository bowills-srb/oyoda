"""
Concierge dining reservation audit model.

Persists every booking attempt/outcome so operators can review:
- what was requested
- whether it was confirmed
- provider/source and confirmation IDs
- fallback/manual handoff scenarios
"""

from uuid import UUID, uuid4

from sqlalchemy import Boolean, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from db.models.core import Base, TimestampMixin


class ConciergeDiningReservationModel(Base, TimestampMixin):
    """
    Audit row for each dining reservation attempt.

    This is append-only in practice. Rows should not be deleted so we keep
    a full trail of guest booking outcomes.
    """

    __tablename__ = "concierge_dining_reservations"

    dining_reservation_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    # Session/operator context
    operator_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    session_token: Mapped[str | None] = mapped_column(String(120), index=True)

    # Guest context
    guest_name: Mapped[str] = mapped_column(String(255), nullable=False)
    guest_phone: Mapped[str | None] = mapped_column(String(50))
    guest_email: Mapped[str | None] = mapped_column(String(255))

    # Reservation request
    restaurant_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    reservation_date: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    reservation_time: Mapped[str] = mapped_column(String(32), nullable=False)
    party_size: Mapped[int] = mapped_column(Integer, nullable=False)
    special_requests: Mapped[str | None] = mapped_column(Text)

    # Result
    success: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    confirmation_id: Mapped[str | None] = mapped_column(String(120), index=True)
    booking_url: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)

    # Full request/response envelopes for debugging + replay analysis
    request_payload: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    response_payload: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")

    __table_args__ = (
        Index(
            "ix_concierge_dining_operator_created",
            "operator_id",
            "created_at",
        ),
        Index(
            "ix_concierge_dining_session_created",
            "session_token",
            "created_at",
        ),
    )
