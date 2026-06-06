"""
Add is_active to properties for Beach Habitats portfolio reconciliation.

Advances:
- A1: active/inactive property state is explicit at the schema layer
- A2: tenant-leading active-property index added for hot-path property reads
- B3: property filtering can scope to active portfolio rows efficiently
- H1, H2: schema change codified in migration and ready for round-trip verification

Revision ID: 070_properties_is_active
Revises: 069_phase_3b_add_tenant_id_to_operational_tables
Create Date: 2026-05-14
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# Migration-only introspection note:
# - `_table_exists` / `_column_exists` / `_index_exists` are acceptable here for
#   retry safety and re-entrancy of one-time migration work
# - this pattern must not be copied into hot-path service code
# - runtime property loading should rely on canonical schema, not
#   information-schema probing


revision = "070_properties_is_active"
down_revision = "069_phase_3b_add_tenant_id_to_operational_tables"
branch_labels = None
depends_on = None


def _table_exists(bind: sa.engine.Connection, table_name: str) -> bool:
    return inspect(bind).has_table(table_name)


def _column_exists(bind: sa.engine.Connection, table_name: str, column_name: str) -> bool:
    inspector = inspect(bind)
    return any(col["name"] == column_name for col in inspector.get_columns(table_name))


def _index_exists(bind: sa.engine.Connection, table_name: str, index_name: str) -> bool:
    inspector = inspect(bind)
    return any(idx["name"] == index_name for idx in inspector.get_indexes(table_name))


def _add_column(bind: sa.engine.Connection) -> None:
    if not _table_exists(bind, "properties"):
        raise RuntimeError("Phase 070 expects properties table to exist")

    if not _column_exists(bind, "properties", "is_active"):
        op.add_column(
            "properties",
            sa.Column(
                "is_active",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            ),
        )


def _create_indexes(bind: sa.engine.Connection) -> None:
    context = op.get_context()
    with context.autocommit_block():
        if not _index_exists(bind, "properties", "ix_properties_tenant_is_active"):
            op.create_index(
                "ix_properties_tenant_is_active",
                "properties",
                ["tenant_id", "is_active"],
                postgresql_concurrently=True,
            )


def _verify_backfill(bind: sa.engine.Connection) -> None:
    if not _column_exists(bind, "properties", "is_active"):
        raise RuntimeError("Phase 070 verification failed: properties.is_active was not created")

    inactive_or_null = bind.execute(
        sa.text(
            """
            SELECT COUNT(*)
            FROM properties
            WHERE is_active IS NOT TRUE
            """
        )
    ).scalar()
    if inactive_or_null > 0:
        raise RuntimeError(
            f"Phase 070 verification failed: {inactive_or_null} existing properties rows are not active after backfill"
        )


def upgrade() -> None:
    bind = op.get_bind()
    _add_column(bind)
    _verify_backfill(bind)
    _create_indexes(bind)


def downgrade() -> None:
    bind = op.get_bind()

    with op.get_context().autocommit_block():
        if _table_exists(bind, "properties") and _index_exists(bind, "properties", "ix_properties_tenant_is_active"):
            op.drop_index(
                "ix_properties_tenant_is_active",
                table_name="properties",
                postgresql_concurrently=True,
            )

    if _table_exists(bind, "properties") and _column_exists(bind, "properties", "is_active"):
        op.drop_column("properties", "is_active")
