"""Phase 4.3-G: Track property_external_id source on pre_booking_inquiries."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "078_pre_booking_inquiries_property_source"
down_revision = "077_properties_phase_4_0_a_backfill_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pre_booking_inquiries",
        sa.Column(
            "property_external_id_source",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("pre_booking_inquiries", "property_external_id_source")
