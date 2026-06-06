"""inbound_classifications

Revision ID: 053_inbound_classifications
Revises: 052_rich_context_shadow_observations
Create Date: 2026-05-05
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "053_inbound_classifications"
down_revision = "052_rich_context_shadow_observations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inbound_classifications",
        sa.Column("decision_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("gmail_message_id", sa.Text(), nullable=True),
        sa.Column("source_message_id", sa.Text(), nullable=True),
        sa.Column("parser_source", sa.Text(), nullable=True),
        sa.Column("from_header", sa.Text(), nullable=True),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("classification", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("reasoning", sa.Text(), nullable=True),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("extracted_guest_text", sa.Text(), nullable=True),
        sa.Column("extracted_guest_name", sa.Text(), nullable=True),
        sa.Column("extracted_property_reference", sa.Text(), nullable=True),
        sa.Column("extracted_reply_path", sa.Text(), nullable=True),
        sa.Column("extracted_thread_id", sa.Text(), nullable=True),
        sa.Column("proceeded_as_guest", sa.Boolean(), nullable=False),
        sa.Column("routed_to_review", sa.Boolean(), nullable=False),
        sa.Column("gate_error", sa.Text(), nullable=True),
        sa.Column("raw_response", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.CheckConstraint(
            "classification IN ('guest_message', 'operational_notification', "
            "'marketing', 'bounce_or_system', 'unclear')",
            name="ck_inbound_classifications_classification",
        ),
        sa.CheckConstraint(
            "confidence >= 0.0 AND confidence <= 1.0",
            name="ck_inbound_classifications_confidence_range",
        ),
    )

    op.create_index(
        "ix_inbound_classifications_tenant_created",
        "inbound_classifications",
        ["tenant_id", "created_at"],
    )
    op.create_index(
        "ix_inbound_classifications_classification",
        "inbound_classifications",
        ["classification", "created_at"],
    )
    op.create_index(
        "ix_inbound_classifications_gmail_message_id",
        "inbound_classifications",
        ["gmail_message_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_inbound_classifications_gmail_message_id",
        table_name="inbound_classifications",
    )
    op.drop_index(
        "ix_inbound_classifications_classification",
        table_name="inbound_classifications",
    )
    op.drop_index(
        "ix_inbound_classifications_tenant_created",
        table_name="inbound_classifications",
    )
    op.drop_table("inbound_classifications")
