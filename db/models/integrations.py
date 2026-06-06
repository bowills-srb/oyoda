"""
Integration persistence models.

Stores provider connection metadata and sync telemetry per tenant.
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from db.models.core import Base, TenantMixin, TimestampMixin


class IntegrationConnectionModel(Base, TenantMixin, TimestampMixin):
    """Configured external provider connection."""

    __tablename__ = "integration_connections"

    integration_connection_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="connected", nullable=False)
    credential_ref: Mapped[str] = mapped_column(String(255), nullable=False)

    settings: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_successful_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("tenant_id", "provider", name="uq_integration_tenant_provider"),
        Index("ix_integration_tenant_provider", "tenant_id", "provider"),
        Index("ix_integration_tenant_active", "tenant_id", "is_active"),
    )


class IntegrationSyncJobModel(Base, TenantMixin):
    """Audit record for each provider sync execution."""

    __tablename__ = "integration_sync_jobs"

    sync_job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    integration_connection_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("integration_connections.integration_connection_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    trigger: Mapped[str] = mapped_column(String(30), default="manual", nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="running", nullable=False)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    records_pulled: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    listings_pulled: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    bookings_pulled: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    calendar_days_pulled: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    errors_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)

    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")

    __table_args__ = (
        Index("ix_sync_jobs_tenant_started", "tenant_id", "started_at"),
        Index("ix_sync_jobs_tenant_provider", "tenant_id", "provider"),
        Index("ix_sync_jobs_status", "status"),
    )


class IntegrationRawRecordModel(Base, TenantMixin):
    """Raw payload record captured from provider APIs."""

    __tablename__ = "integration_raw_records"

    raw_record_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    integration_connection_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("integration_connections.integration_connection_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    record_type: Mapped[str] = mapped_column(String(50), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(255), index=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_raw_records_tenant_provider", "tenant_id", "provider", "record_type"),
        Index("ix_raw_records_observed", "observed_at"),
    )
