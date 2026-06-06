"""013_session_operator_reservation

Add operator_id and reservation_id columns to concierge_guest_sessions.

Revision ID: 013
Revises: 012
"""

from alembic import op
import sqlalchemy as sa

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Historical correction: production stores these provider/operator
    # identifiers as text rather than varchar-limited fields.
    op.add_column(
        "concierge_guest_sessions",
        sa.Column("operator_id", sa.Text(), nullable=True),
    )
    op.add_column(
        "concierge_guest_sessions",
        sa.Column("reservation_id", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_concierge_session_operator",
        "concierge_guest_sessions",
        ["operator_id"],
    )
    op.create_index(
        "ix_concierge_session_reservation",
        "concierge_guest_sessions",
        ["reservation_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_concierge_session_reservation", "concierge_guest_sessions")
    op.drop_index("ix_concierge_session_operator", "concierge_guest_sessions")
    op.drop_column("concierge_guest_sessions", "reservation_id")
    op.drop_column("concierge_guest_sessions", "operator_id")
