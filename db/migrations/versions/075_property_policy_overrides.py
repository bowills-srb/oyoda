"""Phase 4.3-A.1: property-level policy overrides.

Adds property_policy_overrides JSONB column to properties table.
Flat-mirrors operator_policies column names for override merging.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "075_property_policy_overrides"
down_revision = "074_operator_policies_tenant_id_canonical"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "properties",
        sa.Column(
            "property_policy_overrides",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("properties", "property_policy_overrides")
