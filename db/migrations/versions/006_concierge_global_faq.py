"""
006_concierge_global_faq

Adds tenant-scoped global FAQ table shared across all properties.

Revision ID: 006_concierge_global_faq
Revises: 005_concierge_knowledge_gaps
Create Date: 2026-02-10
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "006_concierge_global_faq"
down_revision = "005_concierge_knowledge_gaps"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "concierge_global_faq",
        sa.Column("faq_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("question_key", sa.String(length=500), nullable=False),
        sa.Column("answer_text", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False, server_default="manual"),
        sa.Column("tags", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "question_key", name="uq_concierge_global_faq_tenant_question_key"),
    )

    op.create_index(
        "ix_concierge_global_faq_tenant_id",
        "concierge_global_faq",
        ["tenant_id"],
    )
    op.create_index(
        "ix_concierge_global_faq_tenant_source",
        "concierge_global_faq",
        ["tenant_id", "source"],
    )


def downgrade():
    op.drop_index("ix_concierge_global_faq_tenant_source", table_name="concierge_global_faq")
    op.drop_index("ix_concierge_global_faq_tenant_id", table_name="concierge_global_faq")
    op.drop_table("concierge_global_faq")
