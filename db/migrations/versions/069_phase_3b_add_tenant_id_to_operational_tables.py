"""
Phase 3B: add tenant_id to operational tables still using company_id.

Advances:
- A1: tenant_id introduced on active operational tables
- A2: tenant-leading indexes added for Phase 3 operational reads
- B3: pre-booking and operator operational index coverage improved
- H1, H2: schema change codified in migration and ready for round-trip verification

Draft only:
- do not apply until Phase 3A has been applied and verified clean
- this phase touches operational tables, so verification and rollout discipline matter

Revision ID: 069_phase_3b_add_tenant_id_to_operational_tables
Revises: 068_phase_3a_create_tenant_identity
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
# - post-Phase-8 runtime code should rely on canonical schema, not
#   information-schema probing


revision = "069_phase_3b_add_tenant_id_to_operational_tables"
down_revision = "068_phase_3a_create_tenant_identity"
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


def _add_columns(bind: sa.engine.Connection) -> None:
    tenant_uuid = postgresql.UUID(as_uuid=True)

    if _table_exists(bind, "pre_booking_inquiries") and not _column_exists(bind, "pre_booking_inquiries", "tenant_id"):
        op.add_column("pre_booking_inquiries", sa.Column("tenant_id", tenant_uuid, nullable=True))

    if _table_exists(bind, "operator_market_links") and not _column_exists(bind, "operator_market_links", "tenant_id"):
        op.add_column("operator_market_links", sa.Column("tenant_id", tenant_uuid, nullable=True))

    if _table_exists(bind, "property_incidents") and not _column_exists(bind, "property_incidents", "tenant_id"):
        op.add_column("property_incidents", sa.Column("tenant_id", tenant_uuid, nullable=True))


def _backfill_table_in_batches(
    bind: sa.engine.Connection,
    *,
    table_name: str,
    batch_size: int = 10000,
) -> None:
    # Phase 3B touches operational tables, so even though Beach Habitats is small
    # today, we use a resumable batch pattern now rather than a single full-table
    # UPDATE. For larger future datasets, the same pattern can be checkpointed and
    # resumed with external progress tracking per the Phase 3 design doc.
    #
    # Important scaling note:
    # - this pattern is batched but transactionally monolithic
    # - all batches commit together when upgrade() commits
    # - at Phase 3B's actual scale (~500 rows) this is correct
    # - for later sub-phases touching millions of rows, wrap the batch UPDATE in
    #   op.get_context().autocommit_block() so each batch commits independently
    #   and releases locks
    # - that requires restructuring the loop because autocommit_block cannot wrap
    #   a while loop directly; the batches need to be driven from outside the
    #   autocommit blocks
    iterations = 0
    max_iterations = 10000
    while True:
        iterations += 1
        if iterations > max_iterations:
            raise RuntimeError(
                f"Backfill loop exceeded {max_iterations} iterations on {table_name}; investigate before retrying"
            )
        result = bind.execute(
            sa.text(
                f"""
                WITH batch AS (
                    SELECT t.id, oa.tenant_id
                    FROM {table_name} t
                    JOIN operator_accounts oa
                      ON oa.tenant_id = t.company_id
                    WHERE t.company_id IS NOT NULL
                      AND t.tenant_id IS NULL
                    ORDER BY t.id
                    LIMIT :batch_size
                )
                UPDATE {table_name} target
                   SET tenant_id = batch.tenant_id
                  FROM batch
                 WHERE target.id = batch.id
                RETURNING target.id
                """
            ),
            {"batch_size": batch_size},
        )
        if result.rowcount == 0:
            break


def _backfill_data(bind: sa.engine.Connection) -> None:
    # Important production-shape note:
    # - pre_booking_inquiries.company_id currently stores the tenant UUID value
    #   already, not operator_accounts.id
    # - this backfill is therefore semantic normalization plus verification of
    #   the canonical tenant mapping, rather than a cross-entity rewrite
    for table_name in (
        "pre_booking_inquiries",
        "operator_market_links",
        "property_incidents",
    ):
        if not _table_exists(bind, table_name):
            continue
        if not _column_exists(bind, table_name, "company_id"):
            raise RuntimeError(
                f"Phase 3B backfill expects {table_name}.company_id; column not present, schema may have drifted"
            )
        _backfill_table_in_batches(bind, table_name=table_name)


def _create_indexes(bind: sa.engine.Connection) -> None:
    context = op.get_context()
    with context.autocommit_block():
        if _table_exists(bind, "pre_booking_inquiries"):
            if not _index_exists(bind, "pre_booking_inquiries", "ix_pre_booking_inquiries_tenant_status_created_at"):
                op.execute(
                    sa.text(
                        """
                        CREATE INDEX CONCURRENTLY ix_pre_booking_inquiries_tenant_status_created_at
                            ON pre_booking_inquiries (tenant_id, status, created_at DESC)
                        """
                    )
                )
            if not _index_exists(bind, "pre_booking_inquiries", "ix_pre_booking_inquiries_tenant_gmail_thread"):
                op.create_index(
                    "ix_pre_booking_inquiries_tenant_gmail_thread",
                    "pre_booking_inquiries",
                    ["tenant_id", "gmail_thread_id"],
                    postgresql_where=sa.text("reply_via_gmail = true"),
                    postgresql_concurrently=True,
                )

        if _table_exists(bind, "operator_market_links"):
            if not _index_exists(bind, "operator_market_links", "ix_operator_market_links_tenant_id"):
                op.create_index(
                    "ix_operator_market_links_tenant_id",
                    "operator_market_links",
                    ["tenant_id"],
                    postgresql_concurrently=True,
                )
            if not _index_exists(bind, "operator_market_links", "ux_operator_market_links_tenant_market_id"):
                op.create_index(
                    "ux_operator_market_links_tenant_market_id",
                    "operator_market_links",
                    ["tenant_id", "market_id"],
                    unique=True,
                    postgresql_concurrently=True,
                )

        if _table_exists(bind, "property_incidents"):
            if not _index_exists(bind, "property_incidents", "ix_property_incidents_tenant_status_active"):
                op.create_index(
                    "ix_property_incidents_tenant_status_active",
                    "property_incidents",
                    ["tenant_id", "status"],
                    postgresql_where=sa.text(
                        "status = ANY (ARRAY['open'::text, 'acknowledged'::text, 'in_progress'::text])"
                    ),
                    postgresql_concurrently=True,
                )
            if not _index_exists(bind, "property_incidents", "ix_property_incidents_tenant_property_reported_at"):
                op.execute(
                    sa.text(
                        """
                        CREATE INDEX CONCURRENTLY ix_property_incidents_tenant_property_reported_at
                            ON property_incidents (tenant_id, property_external_id, reported_at DESC)
                        """
                    )
                )


def _verify_backfill(bind: sa.engine.Connection) -> None:
    for table_name in ("pre_booking_inquiries", "operator_market_links", "property_incidents"):
        if not _table_exists(bind, table_name):
            continue

        unmapped_company_rows = bind.execute(
            sa.text(
                f"""
                SELECT COUNT(*)
                FROM {table_name} t
                LEFT JOIN operator_accounts oa
                  ON oa.tenant_id = t.company_id
                WHERE t.company_id IS NOT NULL
                  AND oa.id IS NULL
                """
            )
        ).scalar()
        if unmapped_company_rows > 0:
            raise RuntimeError(
                f"Backfill verification failed: {table_name} has {unmapped_company_rows} rows whose company_id does not map to operator_accounts.tenant_id"
            )

        missing_tenant_rows = bind.execute(
            sa.text(
                f"""
                SELECT COUNT(*)
                FROM {table_name}
                WHERE company_id IS NOT NULL
                  AND tenant_id IS NULL
                """
            )
        ).scalar()
        if missing_tenant_rows > 0:
            raise RuntimeError(
                f"Backfill verification failed: {table_name} has {missing_tenant_rows} rows with company_id but null tenant_id"
            )

        orphan_tenant_rows = bind.execute(
            sa.text(
                f"""
                SELECT COUNT(*)
                FROM {table_name} t
                LEFT JOIN tenants tt ON tt.id = t.tenant_id
                WHERE t.tenant_id IS NOT NULL
                  AND tt.id IS NULL
                """
            )
        ).scalar()
        if orphan_tenant_rows > 0:
            raise RuntimeError(
                f"Backfill verification failed: {table_name} has {orphan_tenant_rows} tenant_id values missing from tenants"
            )


def upgrade() -> None:
    bind = op.get_bind()
    _add_columns(bind)
    _backfill_data(bind)
    _verify_backfill(bind)
    _create_indexes(bind)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    with op.get_context().autocommit_block():
        for table_name, indexes in [
            (
                "property_incidents",
                [
                    "ix_property_incidents_tenant_property_reported_at",
                    "ix_property_incidents_tenant_status_active",
                ],
            ),
            (
                "operator_market_links",
                [
                    "ux_operator_market_links_tenant_market_id",
                    "ix_operator_market_links_tenant_id",
                ],
            ),
            (
                "pre_booking_inquiries",
                [
                    "ix_pre_booking_inquiries_tenant_gmail_thread",
                    "ix_pre_booking_inquiries_tenant_status_created_at",
                ],
            ),
        ]:
            if inspector.has_table(table_name):
                existing_indexes = {idx["name"] for idx in inspector.get_indexes(table_name)}
                for index_name in indexes:
                    if index_name in existing_indexes:
                        op.drop_index(index_name, table_name=table_name, postgresql_concurrently=True)

    if inspector.has_table("property_incidents") and _column_exists(bind, "property_incidents", "tenant_id"):
        op.drop_column("property_incidents", "tenant_id")
    if inspector.has_table("operator_market_links") and _column_exists(bind, "operator_market_links", "tenant_id"):
        op.drop_column("operator_market_links", "tenant_id")
    if inspector.has_table("pre_booking_inquiries") and _column_exists(bind, "pre_booking_inquiries", "tenant_id"):
        op.drop_column("pre_booking_inquiries", "tenant_id")
