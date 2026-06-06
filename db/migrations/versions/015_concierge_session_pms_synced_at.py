"""015_concierge_session_pms_synced_at

Add pms_synced_at to concierge_guest_sessions for reconciliation cadence.

Revision ID: 015
Revises: 014
"""

from alembic import op
import sqlalchemy as sa

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "concierge_guest_sessions",
        sa.Column("pms_synced_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_concierge_guest_sessions_pms_synced_at",
        "concierge_guest_sessions",
        ["pms_synced_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_concierge_guest_sessions_pms_synced_at",
        table_name="concierge_guest_sessions",
    )
    op.drop_column("concierge_guest_sessions", "pms_synced_at")
