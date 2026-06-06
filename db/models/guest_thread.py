from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import Index, Text, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from db.models.core import Base, TimestampMixin


class GuestThreadModel(Base, TimestampMixin):
    """Minimal ORM mapping for the unified guest thread spine."""

    __tablename__ = "guest_threads"

    guest_thread_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    tenant_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=True,
        index=True,
    )
    property_code: Mapped[str | None] = mapped_column(Text)
    guest_name: Mapped[str | None] = mapped_column(Text)
    guest_name_norm: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default=text("''"),
    )
    inquiry_thread_id: Mapped[str | None] = mapped_column(Text)
    session_token: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index(
            "idx_guest_threads_inquiry_thread",
            "tenant_id",
            "inquiry_thread_id",
            unique=True,
            postgresql_where=text("inquiry_thread_id IS NOT NULL"),
        ),
        Index(
            "idx_guest_threads_session_token",
            "tenant_id",
            "session_token",
            unique=True,
            postgresql_where=text("session_token IS NOT NULL"),
        ),
        Index(
            "idx_guest_threads_guest_lookup",
            "tenant_id",
            "property_code",
            "guest_name_norm",
            text("updated_at DESC"),
        ),
    )
