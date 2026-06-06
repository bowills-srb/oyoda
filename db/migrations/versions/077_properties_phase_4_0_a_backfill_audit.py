"""Phase 4.0-A: add properties backfill audit column."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "077_properties_phase_4_0_a_backfill_audit"
down_revision = "076_property_groups"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "properties",
        sa.Column(
            "phase_4_0_a_backfill_audit",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("properties", "phase_4_0_a_backfill_audit")
