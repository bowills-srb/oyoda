"""Phase 4.4 Session 1: add healer_proposals review queue.

Creates the operator-reviewable proposal queue used by the Healer Agent.
The table is additive and safe to deploy before any runner is wired.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


revision = "081_healer_proposals"
down_revision = "080_operator_policies_market_id_corrective"
branch_labels = None
depends_on = None


def _table_exists(bind: sa.engine.Connection, table_name: str) -> bool:
    return inspect(bind).has_table(table_name)


def _index_exists(bind: sa.engine.Connection, table_name: str, index_name: str) -> bool:
    inspector = inspect(bind)
    return any(idx["name"] == index_name for idx in inspector.get_indexes(table_name))


def upgrade() -> None:
    bind = op.get_bind()

    if _table_exists(bind, "healer_proposals"):
        bind.execute(sa.text("SELECT COUNT(*) FROM healer_proposals")).scalar()
    else:
        op.create_table(
            "healer_proposals",
            sa.Column(
                "proposal_id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("proposal_kind", sa.Text(), nullable=False),
            sa.Column("signal_source", sa.Text(), nullable=False),
            sa.Column("dedup_key", sa.Text(), nullable=False),
            sa.Column("summary", sa.Text(), nullable=False),
            sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
            sa.Column(
                "proposed_change",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'pending'")),
            sa.Column("confidence", sa.Float(), nullable=False, server_default=sa.text("0")),
            sa.Column("cluster_size", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
            sa.Column("reviewed_at", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("reviewed_by", sa.Text(), nullable=True),
            sa.Column("review_notes", sa.Text(), nullable=True),
        )

    if not _index_exists(bind, "healer_proposals", "ix_healer_proposals_tenant_status"):
        op.create_index(
            "ix_healer_proposals_tenant_status",
            "healer_proposals",
            ["tenant_id", "status", "created_at"],
            unique=False,
        )

    if not _index_exists(bind, "healer_proposals", "ux_healer_proposals_pending_dedup"):
        op.execute(
            sa.text(
                """
                CREATE UNIQUE INDEX ux_healer_proposals_pending_dedup
                ON healer_proposals (tenant_id, proposal_kind, dedup_key)
                WHERE status = 'pending'
                """
            )
        )


def downgrade() -> None:
    bind = op.get_bind()

    if _table_exists(bind, "healer_proposals"):
        if _index_exists(bind, "healer_proposals", "ux_healer_proposals_pending_dedup"):
            op.drop_index("ux_healer_proposals_pending_dedup", table_name="healer_proposals")
        if _index_exists(bind, "healer_proposals", "ix_healer_proposals_tenant_status"):
            op.drop_index("ix_healer_proposals_tenant_status", table_name="healer_proposals")
        op.drop_table("healer_proposals")
