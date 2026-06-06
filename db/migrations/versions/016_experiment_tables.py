"""016_experiment_tables

Create experiment_assignments and experiment_variant_events tables
for the A/B testing / experiment registry.

Revision ID: 016
Revises: 015
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── experiment_assignments ──────────────────────────────────────────────
    # One row per session × experiment: which variant was assigned.
    op.create_table(
        "experiment_assignments",
        sa.Column(
            "assignment_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("session_token", sa.String(120), nullable=False),
        sa.Column("operator_id", sa.String(100), nullable=True),
        sa.Column("property_code", sa.String(100), nullable=True),
        sa.Column("variant_id", sa.String(80), nullable=False),
        sa.Column("is_control", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("assignment_id"),
    )
    op.create_index(
        "ix_experiment_assignments_session_token",
        "experiment_assignments",
        ["session_token"],
    )
    op.create_index(
        "ix_experiment_assignments_variant_id",
        "experiment_assignments",
        ["variant_id"],
    )
    op.create_index(
        "ix_experiment_assignments_operator_id",
        "experiment_assignments",
        ["operator_id"],
    )

    # ── experiment_variant_events ───────────────────────────────────────────
    # One row per VoicePod interaction: latency, cost, escalated, fallback.
    op.create_table(
        "experiment_variant_events",
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("variant_id", sa.String(80), nullable=False),
        sa.Column("session_token", sa.String(120), nullable=True),
        sa.Column("operator_id", sa.String(100), nullable=True),
        sa.Column("property_code", sa.String(100), nullable=True),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("escalated", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("fallback_used", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index(
        "ix_experiment_variant_events_variant_id",
        "experiment_variant_events",
        ["variant_id"],
    )
    op.create_index(
        "ix_experiment_variant_events_operator_id",
        "experiment_variant_events",
        ["operator_id"],
    )
    op.create_index(
        "ix_experiment_variant_events_recorded_at",
        "experiment_variant_events",
        ["recorded_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_experiment_variant_events_recorded_at", "experiment_variant_events")
    op.drop_index("ix_experiment_variant_events_operator_id", "experiment_variant_events")
    op.drop_index("ix_experiment_variant_events_variant_id", "experiment_variant_events")
    op.drop_table("experiment_variant_events")

    op.drop_index("ix_experiment_assignments_operator_id", "experiment_assignments")
    op.drop_index("ix_experiment_assignments_variant_id", "experiment_assignments")
    op.drop_index("ix_experiment_assignments_session_token", "experiment_assignments")
    op.drop_table("experiment_assignments")
