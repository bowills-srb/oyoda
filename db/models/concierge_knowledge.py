"""
Canonical concierge knowledge persistence.
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Index, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from db.models.core import Base, TenantMixin, TimestampMixin
class ConciergeKnowledgeGapModel(Base, TenantMixin):
    """Guest questions that were missing/weak in property knowledge."""

    __tablename__ = "concierge_knowledge_gaps"

    gap_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    property_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), index=True)
    property_external_id: Mapped[str | None] = mapped_column(String(255), index=True)

    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    stage: Mapped[str | None] = mapped_column(String(30))
    channel: Mapped[str] = mapped_column(String(30), default="text", nullable=False)
    source: Mapped[str] = mapped_column(String(50), default="concierge", nullable=False)

    detected_intent: Mapped[str | None] = mapped_column(String(100))
    confidence_score: Mapped[float | None] = mapped_column()
    resolved: Mapped[bool] = mapped_column(default=False, nullable=False)
    resolution_notes: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, server_default="{}")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_concierge_knowledge_gaps_tenant_created", "tenant_id", "created_at"),
        Index("ix_concierge_knowledge_gaps_tenant_resolved", "tenant_id", "resolved"),
        Index(
            "ix_concierge_knowledge_gaps_tenant_property_external",
            "tenant_id",
            "property_external_id",
        ),
    )


class ConciergeGlobalFAQModel(Base, TenantMixin, TimestampMixin):
    """Tenant-wide FAQ entries shared across all properties."""

    __tablename__ = "concierge_global_faq"

    faq_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    question_key: Mapped[str] = mapped_column(String(500), nullable=False)
    answer_text: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(50), default="manual", nullable=False)
    tags: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, server_default="{}")

    __table_args__ = (
        UniqueConstraint("tenant_id", "question_key", name="uq_concierge_global_faq_tenant_question_key"),
        Index("ix_concierge_global_faq_tenant_source", "tenant_id", "source"),
    )


class ConciergeMaintenanceEventModel(Base, TenantMixin, TimestampMixin):
    """Tenant-scoped maintenance events extracted from concierge traffic."""

    __tablename__ = "concierge_maintenance_events"

    event_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    property_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), index=True)
    property_external_id: Mapped[str | None] = mapped_column(String(255), index=True)

    issue_text: Mapped[str] = mapped_column(Text, nullable=False)
    issue_key: Mapped[str] = mapped_column(String(500), nullable=False)
    category: Mapped[str] = mapped_column(String(60), default="general", nullable=False)
    severity: Mapped[str] = mapped_column(String(20), default="medium", nullable=False)
    source: Mapped[str] = mapped_column(String(50), default="concierge_auto", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)
    escalation_status: Mapped[str] = mapped_column(String(20), default="none", nullable=False)
    assigned_to: Mapped[str | None] = mapped_column(String(255))
    reservation_id: Mapped[str | None] = mapped_column(String(120))
    notes: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, server_default="{}")
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_concierge_maintenance_tenant_status", "tenant_id", "status"),
        Index("ix_concierge_maintenance_tenant_property", "tenant_id", "property_external_id"),
        Index("ix_concierge_maintenance_tenant_category", "tenant_id", "category"),
        Index("ix_concierge_maintenance_tenant_updated", "tenant_id", "updated_at"),
        UniqueConstraint(
            "tenant_id",
            "property_external_id",
            "issue_key",
            "status",
            name="uq_concierge_maintenance_active_key",
        ),
    )
