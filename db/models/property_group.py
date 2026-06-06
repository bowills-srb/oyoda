"""Property group / condo complex scope tables."""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID

from app.models.base import Base


class PropertyGroup(Base):
    """Named grouping of properties such as a condo complex or HOA zone."""

    __tablename__ = "property_groups"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(PGUUID(as_uuid=True), nullable=False, index=True)
    name = Column(Text, nullable=False)
    group_type = Column(String(50), nullable=False, default="condo_complex")
    description = Column(Text, nullable=True)
    metadata = Column(JSONB, nullable=False, default=dict)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class PropertyGroupMembership(Base):
    """Many-to-many between properties and property groups."""

    __tablename__ = "property_group_memberships"

    property_id = Column(PGUUID(as_uuid=True), primary_key=True)
    property_group_id = Column(
        PGUUID(as_uuid=True),
        ForeignKey("property_groups.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tenant_id = Column(PGUUID(as_uuid=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
