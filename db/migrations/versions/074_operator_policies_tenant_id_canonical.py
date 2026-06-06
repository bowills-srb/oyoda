"""Phase 4.3-A: make operator_policies canonical on tenant_id.

Production verification before authoring this migration found the table empty,
so the Phase 3-style multi-step dual-write sequence is unnecessary here.

Revision ID: 074_operator_policies_tenant_id_canonical
Revises: 073_properties_bedrooms_bathrooms_defaults
Create Date: 2026-05-16
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


revision = "074_operator_policies_tenant_id_canonical"
down_revision = "073_properties_bedrooms_bathrooms_defaults"
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


def upgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, "operator_policies"):
        raise RuntimeError("Migration 073 expects operator_policies to exist")

    if not _column_exists(bind, "operator_policies", "tenant_id"):
        op.add_column(
            "operator_policies",
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        )

    op.alter_column(
        "operator_policies",
        "operator_id",
        existing_type=sa.String(length=100),
        nullable=True,
    )

    if _index_exists(bind, "operator_policies", "idx_operator_policies_operator"):
        op.drop_index("idx_operator_policies_operator", table_name="operator_policies")
    if _index_exists(bind, "operator_policies", "ix_operator_policies_operator_id"):
        op.drop_index("ix_operator_policies_operator_id", table_name="operator_policies")

    if not _index_exists(bind, "operator_policies", "ix_operator_policies_operator_id"):
        op.create_index("ix_operator_policies_operator_id", "operator_policies", ["operator_id"], unique=False)

    if not _index_exists(bind, "operator_policies", "ux_operator_policies_tenant_id"):
        op.create_index(
            "ux_operator_policies_tenant_id",
            "operator_policies",
            ["tenant_id"],
            unique=True,
            postgresql_where=sa.text("tenant_id IS NOT NULL"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    if _table_exists(bind, "operator_policies") and _index_exists(bind, "operator_policies", "ux_operator_policies_tenant_id"):
        op.drop_index("ux_operator_policies_tenant_id", table_name="operator_policies")

    if _table_exists(bind, "operator_policies") and _index_exists(bind, "operator_policies", "ix_operator_policies_operator_id"):
        op.drop_index("ix_operator_policies_operator_id", table_name="operator_policies")

    if _table_exists(bind, "operator_policies") and not _index_exists(bind, "operator_policies", "idx_operator_policies_operator"):
        op.create_index("idx_operator_policies_operator", "operator_policies", ["operator_id"], unique=False)

    op.alter_column(
        "operator_policies",
        "operator_id",
        existing_type=sa.String(length=100),
        nullable=False,
    )

    if _column_exists(bind, "operator_policies", "tenant_id"):
        op.drop_column("operator_policies", "tenant_id")
