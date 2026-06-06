"""088_drop_legacy_concierge_knowledge: retire the legacy concierge_knowledge table.

This is the schema-side half of Phase 1 closeout in the Brain-Only Unified
Migration Plan. The data-side half is `scripts/retire_concierge_knowledge.py`,
which migrates and archives the legacy rows.

ORDER OF OPERATIONS (do not deviate):

  1. All runtime callers of `knowledge_service.py::ConciergeKnowledgeService`
     have been rewired (Codex commits 99b55ad, 984181d, 19bfa4b, 375be87,
     b8213d6, plus the gmail-poller and concierge-mcp rewires in Codex's
     follow-up).
  2. `app/services/concierge/scoped_knowledge_service.py` no longer reads
     from `concierge_knowledge` (commit b8213d6).
  3. `scripts/retire_concierge_knowledge.py --execute` has been run and
     printed "PRE-DROP GATE CLEAR" to stderr. Its JSON report is in
     `scripts/output/` and is referenced in this migration's commit
     message.
  4. The archive table `concierge_knowledge_archive_2026_05_23` exists
     and its row count matches the source table's row count at the
     time the script ran.
  5. `db/models/concierge_knowledge.py::ConciergeKnowledgeModel` is
     deleted in the same commit as this migration. The other models in
     that file (`ConciergeKnowledgeGapModel`, `ConciergeGlobalFAQModel`,
     `ConciergeMaintenanceEventModel`) stay.
  6. `app/services/concierge/__init__.py::_EXPORTS` removes the
     `ConciergeKnowledgeService` and `get_concierge_knowledge_service`
     entries in the same commit as this migration.
  7. `app/services/concierge/knowledge_service.py` is deleted in the
     same commit as this migration.

WHAT THIS MIGRATION DOES:

  * Re-verifies the archive table exists with a matching row count.
    Refuses to drop otherwise. This is the safety net for the rare
    case where someone runs this migration directly without first
    running the retire script.
  * Drops the indexes on `concierge_knowledge`.
  * Drops the `concierge_knowledge` table itself.

WHAT THIS MIGRATION DOES NOT DO:

  * It does not drop the archive table. The archive persists
    indefinitely; if it ever needs to go, do it explicitly in a future
    migration with a one-line statement, not bundled with anything else.
  * It does not touch `concierge_knowledge_gaps`, `concierge_global_faq`,
    or `concierge_maintenance_events`. Those are canonical brain tables.

DOWNGRADE BEHAVIOR:

  The downgrade re-creates an empty `concierge_knowledge` table in the
  legacy Q&A shape (the shape production was actually in, not the JSONB
  shape migration 004 declared). It does NOT repopulate from the
  archive. If you need the legacy data restored, run:

      INSERT INTO concierge_knowledge
      SELECT [columns minus archived_at]
      FROM concierge_knowledge_archive_2026_05_23;

  manually, after the downgrade.

  The downgrade is for "the migration shouldn't have run yet" scenarios,
  not "we need legacy KB back in active use." If the brain-only rule is
  ever reversed, the right fix is a forward migration that wires legacy
  back in, not a downgrade that pretends this never happened.
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import inspect, text


revision = "088_drop_legacy_concierge_knowledge"
down_revision = "087_queue_read_model_confidence_split"
branch_labels = None
depends_on = None


ARCHIVE_TABLE = "concierge_knowledge_archive_2026_05_23"


def _table_exists(bind, table_name: str) -> bool:
    inspector = inspect(bind)
    try:
        return table_name in inspector.get_table_names()
    except Exception:
        return False


def _row_count(bind, table_name: str) -> int:
    if not _table_exists(bind, table_name):
        return -1
    result = bind.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
    row = result.fetchone()
    return int(row[0]) if row else 0


def upgrade() -> None:
    bind = op.get_bind()

    if not _table_exists(bind, "concierge_knowledge"):
        # Nothing to drop. Either this migration has already run, or the
        # environment never had the legacy table. Either way the upgrade
        # is a no-op.
        return

    # Re-verify the archive exists before dropping. The retire script is
    # the canonical place this check happens, but we re-check here for
    # the "operator ran alembic upgrade head without first running the
    # script" case. We refuse to drop without a snapshot.
    if not _table_exists(bind, ARCHIVE_TABLE):
        raise RuntimeError(
            f"Refusing to drop concierge_knowledge: archive table "
            f"{ARCHIVE_TABLE!r} does not exist. Run "
            "`python scripts/retire_concierge_knowledge.py --execute` first."
        )

    legacy_count = _row_count(bind, "concierge_knowledge")
    archive_count = _row_count(bind, ARCHIVE_TABLE)
    if archive_count < legacy_count:
        raise RuntimeError(
            f"Refusing to drop concierge_knowledge: archive table has "
            f"{archive_count} rows but source table has {legacy_count} rows. "
            "The snapshot is incomplete. Re-run "
            "`python scripts/retire_concierge_knowledge.py --execute`."
        )

    # Drop indexes first. The names here come from migration 004
    # (the original CREATE), not from production drift. If a name is
    # missing in production we IF EXISTS-guard so the drop is tolerant.
    for index_name in (
        "ix_concierge_knowledge_property_external_id",
        "ix_concierge_knowledge_property_id",
        "ix_concierge_knowledge_tenant_source",
    ):
        op.execute(f"DROP INDEX IF EXISTS {index_name}")

    # Drop the table itself.
    op.execute("DROP TABLE IF EXISTS concierge_knowledge CASCADE")


def downgrade() -> None:
    """Re-create the legacy table in its production Q&A shape.

    Does not repopulate. If legacy data needs to come back, copy from
    `concierge_knowledge_archive_2026_05_23` manually after this runs.
    """
    bind = op.get_bind()
    if _table_exists(bind, "concierge_knowledge"):
        return

    op.execute(
        """
        CREATE TABLE concierge_knowledge (
            knowledge_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL,
            property_external_id VARCHAR(255),
            canonical_property_id UUID,
            category VARCHAR(100),
            question TEXT,
            answer TEXT,
            confidence NUMERIC(4, 3),
            source VARCHAR(100) NOT NULL DEFAULT 'guidebook_import',
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            valid_from TIMESTAMPTZ,
            valid_until TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_concierge_knowledge_tenant_source
            ON concierge_knowledge (tenant_id, source)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_concierge_knowledge_property_id
            ON concierge_knowledge (canonical_property_id)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_concierge_knowledge_property_external_id
            ON concierge_knowledge (property_external_id)
        """
    )
