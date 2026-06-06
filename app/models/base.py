"""
Base model class with common fields and utilities.
"""

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import Column, DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""
    
    # Generate __tablename__ automatically from class name
    @declared_attr.directive
    def __tablename__(cls) -> str:
        """Convert CamelCase class name to snake_case table name."""
        name = cls.__name__
        return ''.join(
            ['_' + c.lower() if c.isupper() else c for c in name]
        ).lstrip('_')
    
    def to_dict(self) -> dict[str, Any]:
        """Convert model instance to dictionary."""
        return {
            column.name: getattr(self, column.name)
            for column in self.__table__.columns
        }


class TimestampMixin:
    """Mixin that adds created_at and updated_at timestamps."""
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
    
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )


class SoftDeleteMixin:
    """Mixin that adds soft delete functionality."""
    
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None
    )
    
    @property
    def is_deleted(self) -> bool:
        """Check if the record is soft deleted."""
        return self.deleted_at is not None
    
    def soft_delete(self) -> None:
        """Mark the record as deleted."""
        self.deleted_at = datetime.utcnow()
    
    def restore(self) -> None:
        """Restore a soft-deleted record."""
        self.deleted_at = None


class TenantMixin:
    """Mixin for multi-tenant models that belong to a company."""
    
    @declared_attr
    def company_id(cls) -> Mapped[UUID]:
        """Foreign key to the company/tenant."""
        return mapped_column(
            UUID(as_uuid=True),
            nullable=False,
            index=True
        )


class UUIDPrimaryKeyMixin:
    """Mixin that adds UUID primary key."""
    
    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4
    )


class BaseModel(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Abstract base model with UUID primary key and timestamps.
    Use this as the base for most models.
    """
    __abstract__ = True


class TenantBaseModel(BaseModel, TenantMixin):
    """
    Abstract base model for tenant-scoped entities.
    Includes UUID, timestamps, and company_id.
    """
    __abstract__ = True


class AuditMixin:
    """Mixin for tracking who created and modified records."""
    
    @declared_attr
    def created_by_id(cls) -> Mapped[UUID | None]:
        """User who created the record."""
        return mapped_column(
            UUID(as_uuid=True),
            nullable=True
        )
    
    @declared_attr
    def updated_by_id(cls) -> Mapped[UUID | None]:
        """User who last updated the record."""
        return mapped_column(
            UUID(as_uuid=True),
            nullable=True
        )
