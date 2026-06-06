"""
Phase 3A: create tenants and operator_users canonical identity tables.

Advances:
- A1: canonical tenant identity table established
- A2: tenant-leading indexes on canonical user table
- B3: indexes per Phase 3 design specification
- H1, H2: schema described by migration and round-trip verified

Verified:
- Beach Habitats data integrity preserved (no operational table touched)
- Round-trip passes from empty DB through new head
- required indexes present on canonical identity tables

Revision ID: 068_phase_3a_create_tenant_identity
Revises: 067_adopt_operator_policies_and_deprecate_legacy_setup_tables
Create Date: 2026-05-14
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

# Migration-only introspection note:
# - `_table_exists` / `_index_exists` are acceptable here for retry safety and
#   re-entrancy of one-time migration work
# - this pattern must not be copied into hot-path service code
# - post-Phase-8 runtime code should rely on canonical schema, not
#   information-schema probing


revision = "068_phase_3a_create_tenant_identity"
down_revision = "067_adopt_operator_policies_and_deprecate_legacy_setup_tables"
branch_labels = None
depends_on = None


def _table_exists(bind: sa.engine.Connection, table_name: str) -> bool:
    return inspect(bind).has_table(table_name)


def _index_exists(bind: sa.engine.Connection, table_name: str, index_name: str) -> bool:
    inspector = inspect(bind)
    return any(idx["name"] == index_name for idx in inspector.get_indexes(table_name))


def _create_tables(bind: sa.engine.Connection) -> None:
    if not _table_exists(bind, "tenants"):
        op.create_table(
            "tenants",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("source_operator_account_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("display_name", sa.Text(), nullable=False),
            sa.Column("legal_name", sa.Text(), nullable=True),
            sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'active'")),
            sa.Column("plan", sa.Text(), nullable=False, server_default=sa.text("'growth'")),
            sa.Column("primary_email", sa.Text(), nullable=True),
            sa.Column("primary_phone", sa.Text(), nullable=True),
            sa.Column("pms_provider", sa.Text(), nullable=True),
            sa.Column("branding_jsonb", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("settings_jsonb", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(
                ["source_operator_account_id"],
                ["operator_accounts.id"],
                name="fk_tenants_source_operator_account",
                ondelete="SET NULL",
            ),
        )

    if not _table_exists(bind, "operator_users"):
        op.create_table(
            "operator_users",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("source_operator_account_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("email", sa.Text(), nullable=False),
            sa.Column("password_hash", sa.Text(), nullable=False),
            sa.Column("name", sa.Text(), nullable=False),
            sa.Column("role", sa.Text(), nullable=False, server_default=sa.text("'owner'")),
            sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'active'")),
            sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(
                ["tenant_id"],
                ["tenants.id"],
                name="fk_operator_users_tenant",
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["source_operator_account_id"],
                ["operator_accounts.id"],
                name="fk_operator_users_source_operator_account",
                ondelete="SET NULL",
            ),
        )


def _backfill_data(bind: sa.engine.Connection) -> None:
    bind.execute(
        sa.text(
            """
            INSERT INTO tenants (
                id,
                source_operator_account_id,
                display_name,
                legal_name,
                status,
                plan,
                primary_email,
                primary_phone,
                pms_provider,
                branding_jsonb,
                settings_jsonb,
                created_at,
                updated_at
            )
            SELECT
                oa.tenant_id,
                oa.id,
                oa.company_name,
                oa.company_name,
                oa.status,
                oa.plan,
                oa.email,
                oa.phone,
                oa.pms,
                -- Seed only minimum branding context for the tenant record.
                -- Rich branding fields such as logo URLs, colors, and
                -- concierge persona belong to later operator-facing branding
                -- management work and are intentionally out of Phase 3 scope.
                jsonb_build_object(
                    'operator_name', oa.company_name,
                    'support_email', oa.email,
                    'support_phone', coalesce(oa.phone, '')
                ),
                '{}'::jsonb,
                oa.created_at,
                oa.updated_at
            FROM operator_accounts oa
            WHERE NOT EXISTS (
                SELECT 1
                FROM tenants t
                WHERE t.id = oa.tenant_id
            )
            """
        )
    )

    # Phase 3A is small enough for a simple `WHERE NOT EXISTS` backfill.
    # For Phase 3B+ large-table transitions, use checkpointed batched backfills
    # and conflict-safe patterns aligned with the Phase 3 design doc.
    bind.execute(
        sa.text(
            """
            INSERT INTO operator_users (
                tenant_id,
                source_operator_account_id,
                email,
                password_hash,
                name,
                role,
                status,
                created_at,
                updated_at
            )
            SELECT
                oa.tenant_id,
                oa.id,
                oa.email,
                oa.password_hash,
                oa.owner_name,
                'owner',
                oa.status,
                oa.created_at,
                oa.updated_at
            FROM operator_accounts oa
            WHERE NOT EXISTS (
                SELECT 1
                FROM operator_users ou
                WHERE ou.source_operator_account_id = oa.id
            )
            """
        )
    )


def _create_indexes(bind: sa.engine.Connection) -> None:
    # New canonical identity indexes use the modern ux_/ix_ naming convention.
    # Older production tables still contain legacy idx_ names; we are not
    # retroactively renaming those during this phase.
    context = op.get_context()
    with context.autocommit_block():
        if not _index_exists(bind, "tenants", "ux_tenants_source_operator_account_id"):
            op.create_index(
                "ux_tenants_source_operator_account_id",
                "tenants",
                ["source_operator_account_id"],
                unique=True,
                postgresql_concurrently=True,
            )

        if not _index_exists(bind, "operator_users", "ux_operator_users_tenant_email"):
            op.create_index(
                "ux_operator_users_tenant_email",
                "operator_users",
                ["tenant_id", "email"],
                unique=True,
                postgresql_concurrently=True,
            )

        if not _index_exists(bind, "operator_users", "ix_operator_users_tenant_role"):
            op.create_index(
                "ix_operator_users_tenant_role",
                "operator_users",
                ["tenant_id", "role"],
                postgresql_concurrently=True,
            )

        if not _index_exists(bind, "operator_users", "ix_operator_users_email"):
            op.create_index(
                "ix_operator_users_email",
                "operator_users",
                ["email"],
                postgresql_concurrently=True,
            )

        if not _index_exists(bind, "operator_users", "ux_operator_users_source_operator_account_id"):
            op.create_index(
                "ux_operator_users_source_operator_account_id",
                "operator_users",
                ["source_operator_account_id"],
                unique=True,
                postgresql_concurrently=True,
            )


def _verify_backfill(bind: sa.engine.Connection) -> None:
    account_count = bind.execute(
        sa.text("SELECT COUNT(*) FROM operator_accounts")
    ).scalar()
    tenant_count = bind.execute(
        sa.text("SELECT COUNT(*) FROM tenants WHERE source_operator_account_id IS NOT NULL")
    ).scalar()
    user_count = bind.execute(
        sa.text("SELECT COUNT(*) FROM operator_users WHERE source_operator_account_id IS NOT NULL")
    ).scalar()

    if tenant_count != account_count:
        raise RuntimeError(
            f"Backfill verification failed: operator_accounts={account_count}, tenants={tenant_count}"
        )
    if user_count != account_count:
        raise RuntimeError(
            f"Backfill verification failed: operator_accounts={account_count}, operator_users={user_count}"
        )

    null_tenant_users = bind.execute(
        sa.text("SELECT COUNT(*) FROM operator_users WHERE tenant_id IS NULL")
    ).scalar()
    if null_tenant_users > 0:
        raise RuntimeError(
            f"Backfill verification failed: {null_tenant_users} operator_users with null tenant_id"
        )

    orphan_tenants = bind.execute(
        sa.text(
            """
            SELECT COUNT(*)
            FROM operator_accounts oa
            LEFT JOIN tenants t ON t.id = oa.tenant_id
            WHERE t.id IS NULL
            """
        )
    ).scalar()
    if orphan_tenants > 0:
        raise RuntimeError(
            f"Backfill verification failed: {orphan_tenants} operator_accounts missing tenants rows"
        )

    bad_source_refs = bind.execute(
        sa.text(
            """
            SELECT COUNT(*)
            FROM operator_users ou
            LEFT JOIN operator_accounts oa ON oa.id = ou.source_operator_account_id
            WHERE ou.source_operator_account_id IS NOT NULL
              AND oa.id IS NULL
            """
        )
    ).scalar()
    if bad_source_refs > 0:
        raise RuntimeError(
            f"Backfill verification failed: {bad_source_refs} operator_users source references do not match operator_accounts"
        )


def upgrade() -> None:
    bind = op.get_bind()
    _create_tables(bind)
    _backfill_data(bind)
    _create_indexes(bind)
    _verify_backfill(bind)


def downgrade() -> None:
    bind = op.get_bind()
    context = op.get_context()

    with context.autocommit_block():
        if _table_exists(bind, "operator_users"):
            for index_name in [
                "ux_operator_users_source_operator_account_id",
                "ix_operator_users_email",
                "ix_operator_users_tenant_role",
                "ux_operator_users_tenant_email",
            ]:
                if _index_exists(bind, "operator_users", index_name):
                    op.drop_index(index_name, table_name="operator_users", postgresql_concurrently=True)

        if _table_exists(bind, "tenants"):
            if _index_exists(bind, "tenants", "ux_tenants_source_operator_account_id"):
                op.drop_index(
                    "ux_tenants_source_operator_account_id",
                    table_name="tenants",
                    postgresql_concurrently=True,
                )

    if _table_exists(bind, "operator_users"):
        op.drop_table("operator_users")
    if _table_exists(bind, "tenants"):
        op.drop_table("tenants")
