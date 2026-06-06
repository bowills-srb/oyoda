"""
Phase 3: build canonical tenant_id-keyed knowledge_embeddings schema.

Discovery against production revealed that knowledge_embeddings is
essentially an empty placeholder (id, content, created_at only).
The original migration 009 schema either never fully applied to
this environment or was rebuilt downstream. Row count is 0.

This migration treats production as a clean slate and builds the
canonical tenant_id-keyed schema directly — no operator_id column,
no dual-write transition, no backfill.

Beach Habitats data will be ingested through the new server-side
guidebook_ingest_service against this canonical schema.

The pgvector ivfflat similarity index is intentionally deferred to
a follow-up migration. ivfflat centroids are computed from existing
rows at build time, so creating it against an empty table produces
a degenerate index that requires rebuild after first ingest. The
btree indexes added here are sufficient for the cutover; ivfflat
will be added once real data exists.

Advances:
- A1: knowledge_embeddings has canonical tenant_id from day one
- A2: tenant-leading indexes for vector retrieval filters
- B3: tenant/property and tenant/doc_type index coverage
- H1, H2: schema codified in migration and round-trip verifiable

Revision ID: 071_phase_3_knowledge_embeddings_tenant_id
Revises: 070_properties_is_active
Create Date: 2026-05-14
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

# Migration-only introspection note:
# - `_table_exists` / `_column_exists` / `_index_exists` are acceptable here for
#   retry safety and re-entrancy of one-time migration work
# - this pattern must not be copied into hot-path service code
# - runtime vector retrieval should rely on canonical schema, not
#   information-schema probing


revision = "071_phase_3_knowledge_embeddings_tenant_id"
down_revision = "070_properties_is_active"
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


def _constraint_exists(bind: sa.engine.Connection, table_name: str, constraint_name: str) -> bool:
    inspector = inspect(bind)
    uniques = inspector.get_unique_constraints(table_name)
    return any(item["name"] == constraint_name for item in uniques)


def _verify_starting_state(bind: sa.engine.Connection) -> None:
    if not _table_exists(bind, "knowledge_embeddings"):
        raise RuntimeError("Phase 071 expects knowledge_embeddings table to exist")

    for required_column in ("id", "content", "created_at"):
        if not _column_exists(bind, "knowledge_embeddings", required_column):
            raise RuntimeError(
                f"Phase 071 expects knowledge_embeddings.{required_column} to exist in the placeholder table"
            )

    row_count = bind.execute(
        sa.text("SELECT COUNT(*) FROM knowledge_embeddings")
    ).scalar()
    if row_count != 0:
        raise RuntimeError(
            f"Phase 071 expected an empty knowledge_embeddings table, found {row_count} rows"
        )


def _ensure_vector_extension() -> None:
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))


def _add_columns(bind: sa.engine.Connection) -> None:
    if not _column_exists(bind, "knowledge_embeddings", "tenant_id"):
        op.add_column(
            "knowledge_embeddings",
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        )

    if not _column_exists(bind, "knowledge_embeddings", "doc_id"):
        op.add_column(
            "knowledge_embeddings",
            sa.Column("doc_id", sa.String(length=64), nullable=False),
        )

    if not _column_exists(bind, "knowledge_embeddings", "property_code"):
        op.add_column(
            "knowledge_embeddings",
            sa.Column("property_code", sa.String(length=100), nullable=True),
        )

    if not _column_exists(bind, "knowledge_embeddings", "doc_type"):
        op.add_column(
            "knowledge_embeddings",
            sa.Column(
                "doc_type",
                sa.String(length=100),
                nullable=False,
            ),
        )

    if not _column_exists(bind, "knowledge_embeddings", "metadata"):
        op.add_column(
            "knowledge_embeddings",
            sa.Column(
                "metadata",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
        )

    if not _column_exists(bind, "knowledge_embeddings", "embedding"):
        op.execute(
            sa.text(
                """
                ALTER TABLE knowledge_embeddings
                ADD COLUMN embedding vector(384)
                """
            )
        )

    if not _column_exists(bind, "knowledge_embeddings", "updated_at"):
        op.add_column(
            "knowledge_embeddings",
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("NOW()"),
            ),
        )


def _add_constraints(bind: sa.engine.Connection) -> None:
    if not _constraint_exists(bind, "knowledge_embeddings", "uq_knowledge_embeddings_doc_id"):
        op.create_unique_constraint(
            "uq_knowledge_embeddings_doc_id",
            "knowledge_embeddings",
            ["doc_id"],
        )


def _create_indexes(bind: sa.engine.Connection) -> None:
    context = op.get_context()
    with context.autocommit_block():
        if not _index_exists(bind, "knowledge_embeddings", "idx_knowledge_tenant"):
            op.create_index(
                "idx_knowledge_tenant",
                "knowledge_embeddings",
                ["tenant_id"],
                postgresql_concurrently=True,
            )

        if not _index_exists(bind, "knowledge_embeddings", "idx_knowledge_tenant_property"):
            op.create_index(
                "idx_knowledge_tenant_property",
                "knowledge_embeddings",
                ["tenant_id", "property_code"],
                postgresql_concurrently=True,
            )

        if not _index_exists(bind, "knowledge_embeddings", "idx_knowledge_tenant_type"):
            op.create_index(
                "idx_knowledge_tenant_type",
                "knowledge_embeddings",
                ["tenant_id", "doc_type"],
                postgresql_concurrently=True,
            )


def _verify_columns(bind: sa.engine.Connection) -> None:
    for required_column in (
        "tenant_id",
        "doc_id",
        "property_code",
        "doc_type",
        "metadata",
        "embedding",
        "updated_at",
    ):
        if not _column_exists(bind, "knowledge_embeddings", required_column):
            raise RuntimeError(
                f"Phase 071 verification failed: missing knowledge_embeddings.{required_column}"
            )


def _verify_constraints(bind: sa.engine.Connection) -> None:
    if not _constraint_exists(bind, "knowledge_embeddings", "uq_knowledge_embeddings_doc_id"):
        raise RuntimeError("Phase 071 verification failed: missing doc_id unique constraint")


def _verify_indexes(bind: sa.engine.Connection) -> None:
    for index_name in (
        "idx_knowledge_tenant",
        "idx_knowledge_tenant_property",
        "idx_knowledge_tenant_type",
    ):
        if not _index_exists(bind, "knowledge_embeddings", index_name):
            raise RuntimeError(f"Phase 071 verification failed: missing index {index_name}")


def upgrade() -> None:
    bind = op.get_bind()
    _verify_starting_state(bind)
    _ensure_vector_extension()
    _add_columns(bind)
    _add_constraints(bind)
    _create_indexes(bind)
    _verify_columns(bind)
    _verify_constraints(bind)
    _verify_indexes(bind)


def downgrade() -> None:
    bind = op.get_bind()

    with op.get_context().autocommit_block():
        for index_name in (
            "idx_knowledge_tenant_type",
            "idx_knowledge_tenant_property",
            "idx_knowledge_tenant",
        ):
            if _table_exists(bind, "knowledge_embeddings") and _index_exists(bind, "knowledge_embeddings", index_name):
                op.drop_index(
                    index_name,
                    table_name="knowledge_embeddings",
                    postgresql_concurrently=True,
                )

    if _table_exists(bind, "knowledge_embeddings") and _constraint_exists(bind, "knowledge_embeddings", "uq_knowledge_embeddings_doc_id"):
        op.drop_constraint(
            "uq_knowledge_embeddings_doc_id",
            "knowledge_embeddings",
            type_="unique",
        )

    if _table_exists(bind, "knowledge_embeddings"):
        for column_name in (
            "updated_at",
            "embedding",
            "metadata",
            "doc_type",
            "property_code",
            "doc_id",
            "tenant_id",
        ):
            if _column_exists(bind, "knowledge_embeddings", column_name):
                op.drop_column("knowledge_embeddings", column_name)
