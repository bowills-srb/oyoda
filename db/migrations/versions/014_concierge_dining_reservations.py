"""014_concierge_dining_reservations

Create audit table for concierge dining booking attempts/results.

Revision ID: 014
Revises: 013
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "concierge_dining_reservations",
        sa.Column(
            "dining_reservation_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("operator_id", sa.String(length=100), nullable=False),
        sa.Column("session_token", sa.String(length=120), nullable=True),
        sa.Column("guest_name", sa.String(length=255), nullable=False),
        sa.Column("guest_phone", sa.String(length=50), nullable=True),
        sa.Column("guest_email", sa.String(length=255), nullable=True),
        sa.Column("restaurant_name", sa.String(length=255), nullable=False),
        sa.Column("reservation_date", sa.String(length=32), nullable=False),
        sa.Column("reservation_time", sa.String(length=32), nullable=False),
        sa.Column("party_size", sa.Integer(), nullable=False),
        sa.Column("special_requests", sa.Text(), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("confirmation_id", sa.String(length=120), nullable=True),
        sa.Column("booking_url", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "request_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "response_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("dining_reservation_id"),
    )
    op.create_index(
        "ix_concierge_dining_reservations_operator_id",
        "concierge_dining_reservations",
        ["operator_id"],
        unique=False,
    )
    op.create_index(
        "ix_concierge_dining_reservations_session_token",
        "concierge_dining_reservations",
        ["session_token"],
        unique=False,
    )
    op.create_index(
        "ix_concierge_dining_reservations_restaurant_name",
        "concierge_dining_reservations",
        ["restaurant_name"],
        unique=False,
    )
    op.create_index(
        "ix_concierge_dining_reservations_reservation_date",
        "concierge_dining_reservations",
        ["reservation_date"],
        unique=False,
    )
    op.create_index(
        "ix_concierge_dining_reservations_status",
        "concierge_dining_reservations",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_concierge_dining_reservations_confirmation_id",
        "concierge_dining_reservations",
        ["confirmation_id"],
        unique=False,
    )
    op.create_index(
        "ix_concierge_dining_operator_created",
        "concierge_dining_reservations",
        ["operator_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_concierge_dining_session_created",
        "concierge_dining_reservations",
        ["session_token", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_concierge_dining_session_created",
        table_name="concierge_dining_reservations",
    )
    op.drop_index(
        "ix_concierge_dining_operator_created",
        table_name="concierge_dining_reservations",
    )
    op.drop_index(
        "ix_concierge_dining_reservations_confirmation_id",
        table_name="concierge_dining_reservations",
    )
    op.drop_index(
        "ix_concierge_dining_reservations_status",
        table_name="concierge_dining_reservations",
    )
    op.drop_index(
        "ix_concierge_dining_reservations_reservation_date",
        table_name="concierge_dining_reservations",
    )
    op.drop_index(
        "ix_concierge_dining_reservations_restaurant_name",
        table_name="concierge_dining_reservations",
    )
    op.drop_index(
        "ix_concierge_dining_reservations_session_token",
        table_name="concierge_dining_reservations",
    )
    op.drop_index(
        "ix_concierge_dining_reservations_operator_id",
        table_name="concierge_dining_reservations",
    )
    op.drop_table("concierge_dining_reservations")
