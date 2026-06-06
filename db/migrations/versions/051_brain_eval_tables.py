"""brain_eval_tables

Adds the three tables that back Session 10's brain eval infrastructure.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "051_brain_eval_tables"
down_revision: Union[str, None] = "050_prebooking_queue_guest_thread"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "brain_eval_cases",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("case_key", sa.Text(), nullable=False, unique=True),
        sa.Column("message_text", sa.Text(), nullable=False),
        sa.Column("market_tag", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("expected_intent_topic", sa.Text(), nullable=False),
        sa.Column(
            "expected_secondary_topics",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column(
            "expected_sub_intents",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column(
            "expected_constraint_keys",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column("expected_review", sa.Boolean(), nullable=False),
        sa.Column("expected_urgency", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("TRUE"),
        ),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index(
        "idx_brain_eval_cases_market",
        "brain_eval_cases",
        ["market_tag", "is_active"],
    )
    op.create_index(
        "idx_brain_eval_cases_source",
        "brain_eval_cases",
        ["source", "is_active"],
    )

    op.create_table(
        "brain_eval_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("invocation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "run_started_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "run_completed_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=True,
        ),
        sa.Column("classifier_source", sa.Text(), nullable=False),
        sa.Column("market_filter", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'in_progress'"),
        ),
        sa.Column(
            "cases_evaluated",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "cases_passed",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "cases_failed",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("accuracy_overall", sa.Numeric(5, 4), nullable=True),
        sa.Column(
            "accuracy_by_market",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("notes", sa.Text(), nullable=True),
    )
    op.create_index(
        "idx_brain_eval_runs_invocation",
        "brain_eval_runs",
        ["invocation_id"],
    )
    op.create_index(
        "idx_brain_eval_runs_started",
        "brain_eval_runs",
        [sa.text("run_started_at DESC")],
    )
    op.create_index(
        "idx_brain_eval_runs_status",
        "brain_eval_runs",
        ["status"],
    )
    op.create_check_constraint(
        "ck_brain_eval_runs_status",
        "brain_eval_runs",
        "status IN ('in_progress', 'completed', 'failed')",
    )

    op.create_table(
        "brain_eval_run_cases",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("brain_eval_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "case_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("brain_eval_cases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column(
            "failure_reasons",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column("urgency_note", sa.Text(), nullable=True),
        sa.Column("actual_intent_topic", sa.Text(), nullable=False),
        sa.Column(
            "actual_secondary_topics",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column(
            "actual_sub_intents",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column("actual_review", sa.Boolean(), nullable=False),
        sa.Column("actual_urgency", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("classifier_provider", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index(
        "idx_brain_eval_run_cases_case_time",
        "brain_eval_run_cases",
        ["case_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "idx_brain_eval_run_cases_run",
        "brain_eval_run_cases",
        ["run_id"],
    )
    op.create_unique_constraint(
        "uq_brain_eval_run_cases_run_case",
        "brain_eval_run_cases",
        ["run_id", "case_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_brain_eval_run_cases_run_case",
        "brain_eval_run_cases",
        type_="unique",
    )
    op.drop_index("idx_brain_eval_run_cases_run", table_name="brain_eval_run_cases")
    op.drop_index(
        "idx_brain_eval_run_cases_case_time",
        table_name="brain_eval_run_cases",
    )
    op.drop_table("brain_eval_run_cases")

    op.drop_constraint("ck_brain_eval_runs_status", "brain_eval_runs", type_="check")
    op.drop_index("idx_brain_eval_runs_status", table_name="brain_eval_runs")
    op.drop_index("idx_brain_eval_runs_started", table_name="brain_eval_runs")
    op.drop_index("idx_brain_eval_runs_invocation", table_name="brain_eval_runs")
    op.drop_table("brain_eval_runs")

    op.drop_index("idx_brain_eval_cases_source", table_name="brain_eval_cases")
    op.drop_index("idx_brain_eval_cases_market", table_name="brain_eval_cases")
    op.drop_table("brain_eval_cases")
