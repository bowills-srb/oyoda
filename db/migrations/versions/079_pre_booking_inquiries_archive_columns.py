"""Phase 4.3-H: archive metadata for mis-routed pre-booking inquiries."""

from alembic import op
import sqlalchemy as sa


revision = "079_pre_booking_inquiries_archive_columns"
down_revision = "078_pre_booking_inquiries_property_source"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pre_booking_inquiries",
        sa.Column("archived_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.add_column(
        "pre_booking_inquiries",
        sa.Column("archive_reason", sa.String(length=100), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("pre_booking_inquiries", "archive_reason")
    op.drop_column("pre_booking_inquiries", "archived_at")
