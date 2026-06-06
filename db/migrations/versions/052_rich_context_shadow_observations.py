"""rich context shadow observations table

Revision ID: 052_rich_context_shadow_observations
Revises: 051_brain_eval_tables
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "052_rich_context_shadow_observations"
down_revision = "051_brain_eval_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rich_context_shadow_observations",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String, nullable=False),
        sa.Column("property_code", sa.String, nullable=True),
        sa.Column("message_id", sa.String, nullable=False),
        sa.Column("intent", sa.String, nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "richness_shadow",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "evidence_shadow",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "preferences_block_shadow",
            sa.Text,
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "shadow_exceptions",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_index(
        "ix_rich_context_shadow_obs_tenant_recorded",
        "rich_context_shadow_observations",
        ["tenant_id", "recorded_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_rich_context_shadow_obs_tenant_recorded",
        table_name="rich_context_shadow_observations",
    )
    op.drop_table("rich_context_shadow_observations")
