"""063_llm_usage_events

Track every production LLM provider call with tenant/service attribution,
token counts, estimated cost, and fallback position so cost diagnostics can
be done from the application database instead of by log archaeology.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "063_llm_usage_events"
down_revision = "062_gmail_processed_message_statuses"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_usage_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("service_name", sa.Text(), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("request_type", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model_id", sa.Text(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("estimated_cost_usd", sa.Numeric(10, 6), nullable=False, server_default="0"),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("error_type", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fallback_position", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )

    op.create_index("idx_llm_usage_events_created_at_desc", "llm_usage_events", ["created_at"])
    op.create_index(
        "idx_llm_usage_events_tenant_created_at_desc",
        "llm_usage_events",
        ["tenant_id", "created_at"],
    )
    op.create_index(
        "idx_llm_usage_events_service_created_at_desc",
        "llm_usage_events",
        ["service_name", "created_at"],
    )
    op.create_index(
        "idx_llm_usage_events_provider_created_at_desc",
        "llm_usage_events",
        ["provider", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_llm_usage_events_provider_created_at_desc", table_name="llm_usage_events")
    op.drop_index("idx_llm_usage_events_service_created_at_desc", table_name="llm_usage_events")
    op.drop_index("idx_llm_usage_events_tenant_created_at_desc", table_name="llm_usage_events")
    op.drop_index("idx_llm_usage_events_created_at_desc", table_name="llm_usage_events")
    op.drop_table("llm_usage_events")
