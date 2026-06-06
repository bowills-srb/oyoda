"""Phase 4.4.A: add knowledge_gap_drafts review queue.

KnowledgeCuratorAgent and its operator endpoints already exist, but the
review-queue table they target was never migrated. This migration creates the
missing table and indexes so the daily curator task can persist drafts.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


revision = "082_knowledge_gap_drafts"
down_revision = "081_healer_proposals"
branch_labels = None
depends_on = None


def _table_exists(bind: sa.engine.Connection, table_name: str) -> bool:
    return inspect(bind).has_table(table_name)


def _index_exists(bind: sa.engine.Connection, table_name: str, index_name: str) -> bool:
    inspector = inspect(bind)
    return any(idx["name"] == index_name for idx in inspector.get_indexes(table_name))


def upgrade() -> None:
    bind = op.get_bind()

    if _table_exists(bind, "knowledge_gap_drafts"):
        bind.execute(sa.text("SELECT COUNT(*) FROM knowledge_gap_drafts")).scalar()
    else:
        op.create_table(
            "knowledge_gap_drafts",
            sa.Column("draft_id", sa.Text(), primary_key=True),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("property_code", sa.Text(), nullable=True),
            sa.Column("operator_id", sa.Text(), nullable=True),
            sa.Column("question", sa.Text(), nullable=False),
            sa.Column("answer_hint", sa.Text(), nullable=True),
            sa.Column(
                "gap_ids",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
            sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default=sa.text("1")),
            sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'pending_review'")),
            sa.Column("indexed_doc_id", sa.Text(), nullable=True),
            sa.Column("reviewed_by", sa.Text(), nullable=True),
            sa.Column("reviewed_at", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("rejection_reason", sa.Text(), nullable=True),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        )

    if not _index_exists(bind, "knowledge_gap_drafts", "ix_knowledge_gap_drafts_tenant_status"):
        op.create_index(
            "ix_knowledge_gap_drafts_tenant_status",
            "knowledge_gap_drafts",
            ["tenant_id", "status", "occurrence_count"],
            unique=False,
        )

    if not _index_exists(bind, "knowledge_gap_drafts", "ix_knowledge_gap_drafts_property_status"):
        op.execute(
            sa.text(
                """
                CREATE INDEX ix_knowledge_gap_drafts_property_status
                ON knowledge_gap_drafts (property_code, status)
                WHERE status = 'pending_review'
                """
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    if _table_exists(bind, "knowledge_gap_drafts"):
        if _index_exists(bind, "knowledge_gap_drafts", "ix_knowledge_gap_drafts_property_status"):
            op.drop_index("ix_knowledge_gap_drafts_property_status", table_name="knowledge_gap_drafts")
        if _index_exists(bind, "knowledge_gap_drafts", "ix_knowledge_gap_drafts_tenant_status"):
            op.drop_index("ix_knowledge_gap_drafts_tenant_status", table_name="knowledge_gap_drafts")
        op.drop_table("knowledge_gap_drafts")
