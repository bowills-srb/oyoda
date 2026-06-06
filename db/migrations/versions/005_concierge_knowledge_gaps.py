"""
005_concierge_knowledge_gaps

Adds tenant-scoped table for capturing concierge knowledge gaps.

Revision ID: 005_concierge_knowledge_gaps
Revises: 004_concierge_knowledge
Create Date: 2026-02-09
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "005_concierge_knowledge_gaps"
down_revision = "004_concierge_knowledge"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "concierge_knowledge_gaps",
        sa.Column("gap_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("property_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("property_external_id", sa.String(255), nullable=True),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("stage", sa.String(30), nullable=True),
        sa.Column("channel", sa.String(30), nullable=False, server_default="text"),
        sa.Column("source", sa.String(50), nullable=False, server_default="concierge"),
        sa.Column("detected_intent", sa.String(100), nullable=True),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("resolved", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("resolution_notes", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_index(
        "ix_concierge_knowledge_gaps_property_id",
        "concierge_knowledge_gaps",
        ["property_id"],
    )
    op.create_index(
        "ix_concierge_knowledge_gaps_property_external_id",
        "concierge_knowledge_gaps",
        ["property_external_id"],
    )
    op.create_index(
        "ix_concierge_knowledge_gaps_tenant_id",
        "concierge_knowledge_gaps",
        ["tenant_id"],
    )
    op.create_index(
        "ix_concierge_knowledge_gaps_tenant_created",
        "concierge_knowledge_gaps",
        ["tenant_id", "created_at"],
    )
    op.create_index(
        "ix_concierge_knowledge_gaps_tenant_resolved",
        "concierge_knowledge_gaps",
        ["tenant_id", "resolved"],
    )
    op.create_index(
        "ix_concierge_knowledge_gaps_tenant_property_external",
        "concierge_knowledge_gaps",
        ["tenant_id", "property_external_id"],
    )


def downgrade():
    op.drop_index("ix_concierge_knowledge_gaps_tenant_property_external", table_name="concierge_knowledge_gaps")
    op.drop_index("ix_concierge_knowledge_gaps_tenant_resolved", table_name="concierge_knowledge_gaps")
    op.drop_index("ix_concierge_knowledge_gaps_tenant_created", table_name="concierge_knowledge_gaps")
    op.drop_index("ix_concierge_knowledge_gaps_tenant_id", table_name="concierge_knowledge_gaps")
    op.drop_index("ix_concierge_knowledge_gaps_property_external_id", table_name="concierge_knowledge_gaps")
    op.drop_index("ix_concierge_knowledge_gaps_property_id", table_name="concierge_knowledge_gaps")
    op.drop_table("concierge_knowledge_gaps")
