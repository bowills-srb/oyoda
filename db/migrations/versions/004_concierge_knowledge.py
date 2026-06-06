"""
004_concierge_knowledge

Adds tenant-scoped concierge knowledge table for guidebook-derived FAQ and sections.

Revision ID: 004_concierge_knowledge
Revises: 003_operator_integrations
Create Date: 2026-02-09
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "004_concierge_knowledge"
down_revision = "003_operator_integrations"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "concierge_knowledge",
        sa.Column("concierge_knowledge_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("property_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("property_external_id", sa.String(255), nullable=True),
        sa.Column("source", sa.String(100), nullable=False, server_default="guidebook_import"),
        sa.Column("guidebook_url", sa.String(1000), nullable=True),
        sa.Column("property_context", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("facts", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("sections", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("faq", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("raw_text_length", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "property_id", name="uq_concierge_knowledge_tenant_property_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "property_external_id",
            name="uq_concierge_knowledge_tenant_property_external_id",
        ),
    )
    op.create_index(
        "ix_concierge_knowledge_tenant_source",
        "concierge_knowledge",
        ["tenant_id", "source"],
    )
    op.create_index(
        "ix_concierge_knowledge_property_id",
        "concierge_knowledge",
        ["property_id"],
    )
    op.create_index(
        "ix_concierge_knowledge_property_external_id",
        "concierge_knowledge",
        ["property_external_id"],
    )


def downgrade():
    op.drop_index("ix_concierge_knowledge_property_external_id", table_name="concierge_knowledge")
    op.drop_index("ix_concierge_knowledge_property_id", table_name="concierge_knowledge")
    op.drop_index("ix_concierge_knowledge_tenant_source", table_name="concierge_knowledge")
    op.drop_table("concierge_knowledge")
