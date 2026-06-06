"""064_reconcile_concierge_guest_sessions_relational_contract

Reconcile the live concierge_guest_sessions relational contract with the
actual properties primary-key shape and the additive columns/indexes the
operator workflow now depends on.

Why this migration exists:

- The original 008_concierge_sessions migration referenced
  `properties.property_id`, but the canonical properties table created in
  003_create_properties uses `properties.id`.
- Production currently has the concierge_guest_sessions table and its later
  additive columns, but it does not consistently expose the relational
  contract and secondary indexes implied by the migration lineage.

This migration is intentionally idempotent and safe to run against:

1. existing production databases already at head
2. fresh databases created from the corrected migration chain

It does not rewrite tenant identity or property semantics. It only restores
the current intended contract so Phase 2 can establish a trustworthy
migration round-trip baseline.
"""

from alembic import op


revision = "064_reconcile_concierge_guest_sessions_relational_contract"
down_revision = "063_llm_usage_events"
branch_labels = None
depends_on = None


UP_STATEMENTS = [
    """
    DO $$
    BEGIN
        IF EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'concierge_guest_sessions'
              AND column_name = 'property_id'
        ) THEN
            ALTER TABLE concierge_guest_sessions
                DROP CONSTRAINT IF EXISTS concierge_guest_sessions_property_id_fkey;

            ALTER TABLE concierge_guest_sessions
                DROP CONSTRAINT IF EXISTS fk_concierge_guest_sessions_property;

            ALTER TABLE concierge_guest_sessions
                ADD CONSTRAINT fk_concierge_guest_sessions_property
                FOREIGN KEY (property_id) REFERENCES properties(id) ON DELETE SET NULL;
        END IF;
    END $$;
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_concierge_session_tenant_property
        ON concierge_guest_sessions (tenant_id, property_code)
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_concierge_session_checkin
        ON concierge_guest_sessions (check_in)
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_concierge_session_checkout
        ON concierge_guest_sessions (check_out)
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_concierge_session_operator
        ON concierge_guest_sessions (operator_id)
        WHERE operator_id IS NOT NULL
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_concierge_session_reservation
        ON concierge_guest_sessions (reservation_id)
        WHERE reservation_id IS NOT NULL
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_concierge_guest_sessions_pms_synced_at
        ON concierge_guest_sessions (pms_synced_at)
        WHERE pms_synced_at IS NOT NULL
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_sessions_company_external
        ON concierge_guest_sessions (company_id, property_external_id)
        WHERE company_id IS NOT NULL
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_sessions_join_token
        ON concierge_guest_sessions (group_join_token)
        WHERE group_join_token IS NOT NULL
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_concierge_sessions_guest_thread
        ON concierge_guest_sessions (tenant_id, guest_thread_id)
        WHERE guest_thread_id IS NOT NULL
    """,
]


DOWN_STATEMENTS = [
    "DROP INDEX IF EXISTS idx_concierge_sessions_guest_thread",
    "DROP INDEX IF EXISTS idx_sessions_join_token",
    # idx_sessions_company_external existed in the earlier lineage; keep it on downgrade
    "DROP INDEX IF EXISTS ix_concierge_guest_sessions_pms_synced_at",
    "DROP INDEX IF EXISTS ix_concierge_session_reservation",
    "DROP INDEX IF EXISTS ix_concierge_session_operator",
    "DROP INDEX IF EXISTS ix_concierge_session_checkout",
    "DROP INDEX IF EXISTS ix_concierge_session_checkin",
    "DROP INDEX IF EXISTS ix_concierge_session_tenant_property",
    """
    ALTER TABLE concierge_guest_sessions
        DROP CONSTRAINT IF EXISTS fk_concierge_guest_sessions_property
    """,
]


def upgrade() -> None:
    for statement in UP_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWN_STATEMENTS:
        op.execute(statement)
