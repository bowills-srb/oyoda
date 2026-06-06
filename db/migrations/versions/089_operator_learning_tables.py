"""089_operator_learning_tables: stand up the four operator-learning tables.

WHAT THIS MIGRATION DOES:

  Creates four tables that back app/services/concierge/operator_learning.py:

    operator_draft_events       — raw edit/approve/reject audit log
    operator_learned_preferences — distilled per-operator/per-property preferences
    platform_learning_events    — anonymized cross-operator signal (no operator IDs)
    platform_intelligence       — nightly aggregation output, read by draft generator

  Also adds platform_learning_opt_in to operator_pre_booking_policies so
  operators can opt out of contributing to the platform-level signal.

WIRING STATE — READ BEFORE TOUCHING THE RELATED SERVICE:

  The learning engine (app/services/concierge/operator_learning.py) is NOT yet
  wired into the brain pathway (messaging_brain/). It currently lives in
  concierge/ — the old tree — and nothing in messaging_brain/ imports it.
  This migration creates the tables; the tables are inert until the engine
  is wired. That wiring has two parts:

    1. RELOCATION: move operator_learning.py from
           app/services/concierge/operator_learning.py
       to the appropriate messaging_brain/ subdirectory (per the module's
       own header, which instructs this move "when the relevant product
       surface is wired into the brain").

    2. BRAIN IMPORT: add OperatorLearningService to whichever brain agent
       or orchestrator is responsible for draft generation — likely
       ContextBuilderAgent or the orchestrator's draft-approval path.

  Do not skip step 1 and only do step 2. The file in concierge/ is legacy
  placement; leaving it there while importing it from the brain creates a
  dependency in the wrong direction.

TENANT_ID:

  tenant_id is added to the three operator-scoped tables per Phase-3
  multi-tenant discipline. platform_learning_events and platform_intelligence
  are intentionally tenant-free — they are anonymized cross-operator aggregates.

CONFLICT SEMANTICS (matched to operator_learning.py SQL):

  operator_draft_events:
    record_approval uses ON CONFLICT DO NOTHING — no unique constraint
    needed; the guard is "don't crash if somehow duplicate" not "enforce
    uniqueness." No conflict index created.

  operator_learned_preferences:
    _upsert_preference uses SELECT + UPDATE/INSERT, not ON CONFLICT.
    _maybe_promote_to_operator_scope uses:
        ON CONFLICT (company_id, intent, edit_type, scope)
        WHERE property_external_id IS NULL
    A partial unique index is created to back this.

  platform_intelligence:
    rebuild_platform_intelligence uses ON CONFLICT (intent, edit_type, market).
    Backed by UNIQUE (intent, edit_type, market) on the table.

DOWNGRADE:

  Drops the four tables and removes the opt-in column. Safe to re-run
  upgrade after a downgrade — all CREATE statements are IF NOT EXISTS.
"""

from __future__ import annotations

from alembic import op


revision = "089_operator_learning_tables"
down_revision = "088_drop_legacy_concierge_knowledge"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── operator_draft_events ─────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS operator_draft_events (
            id                      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               UUID        NOT NULL,
            company_id              UUID        NOT NULL,
            draft_id                TEXT        NOT NULL,
            intent                  TEXT        NOT NULL,
            property_external_id    TEXT,

            event_type              TEXT        NOT NULL,
            original_draft          TEXT,
            edited_text             TEXT,

            edit_type               TEXT,
            similarity_score        NUMERIC(5,4),
            added_phrases           JSONB       NOT NULL DEFAULT '[]',
            price_signals           JSONB       NOT NULL DEFAULT '[]',
            policy_signals          JSONB       NOT NULL DEFAULT '[]',
            property_facts          JSONB       NOT NULL DEFAULT '[]',

            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_draft_events_company
            ON operator_draft_events (company_id, intent, created_at DESC)
        """
    )

    # ── operator_learned_preferences ──────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS operator_learned_preferences (
            id                      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               UUID        NOT NULL,
            company_id              UUID        NOT NULL,
            property_external_id    TEXT,

            intent                  TEXT        NOT NULL,
            edit_type               TEXT        NOT NULL,
            scope                   TEXT        NOT NULL DEFAULT 'property',

            instruction             TEXT        NOT NULL,
            example_edit            TEXT,

            observation_count       INTEGER     NOT NULL DEFAULT 1,
            confidence              NUMERIC(5,4) NOT NULL DEFAULT 0.0,
            is_active               BOOLEAN     NOT NULL DEFAULT TRUE,

            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_seen_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_preferences_lookup
            ON operator_learned_preferences (company_id, intent, is_active)
            WHERE is_active = TRUE
        """
    )
    # Backs _maybe_promote_to_operator_scope's ON CONFLICT target:
    #   ON CONFLICT (company_id, intent, edit_type, scope)
    #   WHERE property_external_id IS NULL
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_preferences_operator_scope_unique
            ON operator_learned_preferences (company_id, intent, edit_type, scope)
            WHERE property_external_id IS NULL
        """
    )

    # ── platform_learning_opt_in on operator_pre_booking_policies ─────────────
    op.execute(
        """
        ALTER TABLE operator_pre_booking_policies
            ADD COLUMN IF NOT EXISTS platform_learning_opt_in BOOLEAN DEFAULT TRUE
        """
    )

    # ── platform_learning_events (anonymized — no tenant_id by design) ────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS platform_learning_events (
            id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            intent              TEXT        NOT NULL,
            edit_type           TEXT        NOT NULL,
            has_price_signal    BOOLEAN     NOT NULL DEFAULT FALSE,
            has_policy_signal   BOOLEAN     NOT NULL DEFAULT FALSE,
            has_property_fact   BOOLEAN     NOT NULL DEFAULT FALSE,
            market              TEXT,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_platform_events_intent
            ON platform_learning_events (intent, edit_type, created_at DESC)
        """
    )

    # ── platform_intelligence (nightly aggregation output) ────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS platform_intelligence (
            id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            intent              TEXT        NOT NULL,
            edit_type           TEXT        NOT NULL,
            market              TEXT,
            intelligence_text   TEXT        NOT NULL,
            sample_count        INTEGER     NOT NULL DEFAULT 0,
            is_active           BOOLEAN     NOT NULL DEFAULT TRUE,
            last_updated        TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            UNIQUE (intent, edit_type, market)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS platform_intelligence CASCADE")
    op.execute("DROP TABLE IF EXISTS platform_learning_events CASCADE")
    op.execute(
        """
        ALTER TABLE operator_pre_booking_policies
            DROP COLUMN IF EXISTS platform_learning_opt_in
        """
    )
    op.execute("DROP TABLE IF EXISTS operator_learned_preferences CASCADE")
    op.execute("DROP TABLE IF EXISTS operator_draft_events CASCADE")
