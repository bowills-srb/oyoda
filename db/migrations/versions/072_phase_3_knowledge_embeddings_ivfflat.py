"""
Phase 3 follow-up: pgvector ivfflat index on knowledge_embeddings.embedding

Migration 071 built canonical knowledge_embeddings schema against an empty
table and deliberately deferred the ivfflat index because ivfflat centroids
are computed from existing rows at build time. With Phase 3 Pass 2 ingest
now complete, real embeddings exist and the index can be built meaningfully.

Index: idx_knowledge_embedding_ivfflat
  - column: embedding (vector(384))
  - opclass: vector_cosine_ops (matches the <=> cosine-distance query in
    VectorStore.similarity_search)
  - lists: 100 (over-segmented for a small growing table; pairs with
    probes=10 runtime setting)
  - built CONCURRENTLY so the migration does not block reads/writes

Advances:
- A2: vector retrieval scales beyond linear scan
- H1, H2: index is codified in migration and round-trip verifiable

Revision ID: 072_phase_3_knowledge_embeddings_ivfflat
Revises: 071_phase_3_knowledge_embeddings_tenant_id
Create Date: 2026-05-15
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "072_phase_3_knowledge_embeddings_ivfflat"
down_revision = "071_phase_3_knowledge_embeddings_tenant_id"
branch_labels = None
depends_on = None


def _table_exists(bind: sa.engine.Connection, table_name: str) -> bool:
    return inspect(bind).has_table(table_name)


def _index_exists(bind: sa.engine.Connection, table_name: str, index_name: str) -> bool:
    inspector = inspect(bind)
    return any(idx["name"] == index_name for idx in inspector.get_indexes(table_name))


def _verify_starting_state(bind: sa.engine.Connection) -> None:
    if not _table_exists(bind, "knowledge_embeddings"):
        raise RuntimeError("Migration 072 expects knowledge_embeddings table to exist")

    row_count = bind.execute(sa.text("SELECT COUNT(*) FROM knowledge_embeddings")).scalar()
    if not row_count:
        raise RuntimeError(
            "Migration 072 requires non-empty knowledge_embeddings. "
            "Run POST /api/v1/operator/properties/reconcile with operator JWT "
            "to populate embeddings before applying this migration."
        )


def _ensure_vector_extension() -> None:
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))


def _create_index(bind: sa.engine.Connection) -> None:
    with op.get_context().autocommit_block():
        if not _index_exists(bind, "knowledge_embeddings", "idx_knowledge_embedding_ivfflat"):
            op.execute(
                sa.text(
                    """
                    CREATE INDEX CONCURRENTLY idx_knowledge_embedding_ivfflat
                    ON knowledge_embeddings
                    USING ivfflat (embedding vector_cosine_ops)
                    WITH (lists = 100)
                    """
                )
            )


def _verify_index(bind: sa.engine.Connection) -> None:
    if not _index_exists(bind, "knowledge_embeddings", "idx_knowledge_embedding_ivfflat"):
        raise RuntimeError("Migration 072 verification failed: ivfflat index not present after build")


def _analyze_table() -> None:
    op.execute(sa.text("ANALYZE knowledge_embeddings"))


def upgrade() -> None:
    bind = op.get_bind()
    _verify_starting_state(bind)
    _ensure_vector_extension()
    _create_index(bind)
    _verify_index(bind)
    _analyze_table()


def downgrade() -> None:
    bind = op.get_bind()
    with op.get_context().autocommit_block():
        if _table_exists(bind, "knowledge_embeddings") and _index_exists(
            bind, "knowledge_embeddings", "idx_knowledge_embedding_ivfflat"
        ):
            op.drop_index(
                "idx_knowledge_embedding_ivfflat",
                table_name="knowledge_embeddings",
                postgresql_concurrently=True,
            )
