"""046_vendor_operational_metadata

Adds operational metadata to vendors for warranty, emergency capability,
manufacturer tags, and SLA-aware routing.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "046_vendor_operational_metadata"
down_revision = "045_operator_stay_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "vendors",
        sa.Column(
            "operational_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("vendors", "operational_metadata")
