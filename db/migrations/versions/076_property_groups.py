"""Phase 4.3-A.2: property groups and memberships.

Adds property_groups and property_group_memberships tables to support
condo-complex / portfolio-segment scope between property and tenant
levels. Both tables are tenant-scoped on tenant_id from creation.
"""

from alembic import op


revision = "076_property_groups"
down_revision = "075_property_policy_overrides"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS property_groups (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL,
            name TEXT NOT NULL,
            group_type TEXT NOT NULL DEFAULT 'condo_complex',
            description TEXT,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_property_groups_tenant_id
        ON property_groups (tenant_id) WHERE is_active = TRUE
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ux_property_groups_tenant_name
        ON property_groups (tenant_id, LOWER(name)) WHERE is_active = TRUE
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS property_group_memberships (
            property_id UUID NOT NULL,
            property_group_id UUID NOT NULL REFERENCES property_groups(id) ON DELETE CASCADE,
            tenant_id UUID NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (property_id, property_group_id)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_property_group_memberships_property
        ON property_group_memberships (property_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_property_group_memberships_group
        ON property_group_memberships (property_group_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_property_group_memberships_tenant
        ON property_group_memberships (tenant_id)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_property_group_memberships_tenant")
    op.execute("DROP INDEX IF EXISTS ix_property_group_memberships_group")
    op.execute("DROP INDEX IF EXISTS ix_property_group_memberships_property")
    op.execute("DROP TABLE IF EXISTS property_group_memberships CASCADE")
    op.execute("DROP INDEX IF EXISTS ux_property_groups_tenant_name")
    op.execute("DROP INDEX IF EXISTS ix_property_groups_tenant_id")
    op.execute("DROP TABLE IF EXISTS property_groups CASCADE")
