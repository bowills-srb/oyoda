"""
Tenant-scoped healer proposal persistence.
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Float, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from db.models.core import Base, TenantMixin


class HealerProposalModel(Base, TenantMixin):
    """Operator-reviewable deterministic-healing proposal."""

    __tablename__ = "healer_proposals"

    proposal_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    proposal_kind: Mapped[str] = mapped_column(String(100), nullable=False)
    signal_source: Mapped[str] = mapped_column(String(100), nullable=False)
    dedup_key: Mapped[str] = mapped_column(String(64), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]", nullable=False)
    proposed_change: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending", nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, server_default="0", nullable=False)
    cluster_size: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("NOW()"),
        nullable=False,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[str | None] = mapped_column(String(255))
    review_notes: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("ix_healer_proposals_tenant_status", "tenant_id", "status", "created_at"),
        Index(
            "ux_healer_proposals_pending_dedup",
            "tenant_id",
            "proposal_kind",
            "dedup_key",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
    )
