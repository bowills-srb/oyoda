"""012_onboarding_sessions

Simple JSONB store for operator onboarding session state.

Revision ID: 012
Revises: 011_concierge_escalations
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "concierge_onboarding_sessions",
        sa.Column("session_id", sa.String(50), primary_key=True),
        sa.Column("session_data", postgresql.JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_onboarding_sessions_updated",
        "concierge_onboarding_sessions",
        ["updated_at"],
    )


def downgrade() -> None:
    op.drop_table("concierge_onboarding_sessions")
