"""
Phase 3 cleanup: align properties bedroom/bathroom defaults with production.

Migration 003 originally created properties.bedrooms and properties.bathrooms
without defaults, while production has long relied on zero defaults for both
columns. This follow-up codifies the deployed behavior so fresh environments,
ORM metadata, and Alembic all agree on the same schema contract.

Revision ID: 073_properties_bedrooms_bathrooms_defaults
Revises: 072_phase_3_knowledge_embeddings_ivfflat
Create Date: 2026-05-15
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "073_properties_bedrooms_bathrooms_defaults"
down_revision = "072_phase_3_knowledge_embeddings_ivfflat"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("properties", "bedrooms", existing_type=sa.Integer(), server_default="0")
    op.alter_column(
        "properties",
        "bathrooms",
        existing_type=sa.Numeric(3, 1),
        server_default="0",
    )


def downgrade() -> None:
    op.alter_column("properties", "bathrooms", existing_type=sa.Numeric(3, 1), server_default=None)
    op.alter_column("properties", "bedrooms", existing_type=sa.Integer(), server_default=None)
