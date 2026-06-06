"""Ship S: add autonomy_decision to pre_booking_inquiries.

Adds:
- pre_booking_inquiries.autonomy_decision (enum)

Backfill strategy:
- Existing rows default to routed_to_action_auto_off, which is the most
  accurate historical statement for pre-Ship-S inquiries.

Notes:
- Uses a Postgres ENUM so the database enforces the Ship S decision vocabulary.
- Intentionally does not add an index yet; Ship S reads the value per row, but
  no production query path filters heavily on autonomy_decision today.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text
from sqlalchemy.dialects import postgresql


revision = "084_ship_s_autonomy_decision"
down_revision = "083_ship_i_kb_retry_fields"
branch_labels = None
depends_on = None


AUTONOMY_DECISION_ENUM = postgresql.ENUM(
    "auto_sent",
    "routed_to_action_below_threshold",
    "routed_to_action_auto_off",
    "routed_to_action_kb_gap",
    "routed_to_action_policy_review",
    name="autonomy_decision",
    create_type=False,
)


def _column_names(bind, table_name: str) -> set[str]:
    inspector = inspect(bind)
    try:
        return {col["name"] for col in inspector.get_columns(table_name)}
    except Exception:
        return set()


def _enum_exists(bind, enum_name: str) -> bool:
    result = bind.execute(
        text(
            """
            SELECT 1
            FROM pg_type
            WHERE typname = :enum_name
            LIMIT 1
            """
        ),
        {"enum_name": enum_name},
    ).scalar()
    return bool(result)


def upgrade() -> None:
    bind = op.get_bind()

    if not _enum_exists(bind, "autonomy_decision"):
        AUTONOMY_DECISION_ENUM.create(bind, checkfirst=True)

    pbi_cols = _column_names(bind, "pre_booking_inquiries")
    if "autonomy_decision" not in pbi_cols:
        op.add_column(
            "pre_booking_inquiries",
            sa.Column(
                "autonomy_decision",
                AUTONOMY_DECISION_ENUM,
                nullable=False,
                server_default=sa.text("'routed_to_action_auto_off'::autonomy_decision"),
            ),
        )

    bind.execute(
        text(
            """
            UPDATE pre_booking_inquiries
            SET autonomy_decision = 'routed_to_action_auto_off'
            WHERE autonomy_decision IS NULL
            """
        )
    )

    # Historical rows need the temporary default for the add-column path, but
    # future writes should set the real autonomy decision explicitly.
    op.alter_column(
        "pre_booking_inquiries",
        "autonomy_decision",
        server_default=None,
        existing_type=AUTONOMY_DECISION_ENUM,
    )


def downgrade() -> None:
    bind = op.get_bind()
    pbi_cols = _column_names(bind, "pre_booking_inquiries")
    if "autonomy_decision" in pbi_cols:
        op.drop_column("pre_booking_inquiries", "autonomy_decision")

    if _enum_exists(bind, "autonomy_decision"):
        AUTONOMY_DECISION_ENUM.drop(bind, checkfirst=True)
