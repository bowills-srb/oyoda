"""092_scoped_knowledge_provenance_columns: confidence / verified-date columns on concierge_scoped_knowledge.

Promotes provenance signals from the metadata JSONB blob to first-class queryable
columns. This makes "show me facts no human has checked" and "show me low-confidence
facts" trivially queryable rather than requiring a JSONB cast.

WRITE SEMANTICS (the honesty discipline, enforced by the service layer):
  confidence         — set on every promotion; NULL for operator-authored entries
                       (human wrote it = verified, not merely confident).
  last_verified_at   — set ONLY when a HUMAN approves/authors/edits.
                       NULL means "auto-promoted or staged, never human-checked."
  verified_by_user_id — the human who verified it; NULL if unverified.

Auto-promoted high-confidence facts get confidence set but verified_* = NULL.
They are "system-confident, unverified" — honest about what happened.

Revision ID: 092_scoped_knowledge_provenance_columns
Revises:     091_operator_property_autonomy_snapshots
"""
from typing import Union

from alembic import op


revision: str = "092_scoped_knowledge_provenance_columns"
down_revision: Union[str, None] = "091_operator_property_autonomy_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE concierge_scoped_knowledge
            ADD COLUMN IF NOT EXISTS confidence          NUMERIC(4,3),
            ADD COLUMN IF NOT EXISTS last_verified_at   TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS verified_by_user_id UUID
        """
    )
    # Backfill confidence from metadata JSONB where it exists and is numeric.
    # Guard the cast — non-numeric values (strings, booleans) are silently skipped.
    # Do NOT backfill last_verified_at / verified_by from metadata: there is no
    # reliable human-verification signal in the existing metadata. NULL is honest.
    op.execute(
        """
        UPDATE concierge_scoped_knowledge
        SET confidence = (metadata->>'confidence')::numeric
        WHERE metadata ? 'confidence'
          AND confidence IS NULL
          AND (metadata->>'confidence') ~ '^[0-9]+(\.[0-9]+)?$'
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_scoped_knowledge_unverified
            ON concierge_scoped_knowledge (tenant_id)
            WHERE last_verified_at IS NULL
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_scoped_knowledge_confidence
            ON concierge_scoped_knowledge (tenant_id, confidence)
            WHERE confidence IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_scoped_knowledge_confidence")
    op.execute("DROP INDEX IF EXISTS idx_scoped_knowledge_unverified")
    op.execute(
        """
        ALTER TABLE concierge_scoped_knowledge
            DROP COLUMN IF EXISTS verified_by_user_id,
            DROP COLUMN IF EXISTS last_verified_at,
            DROP COLUMN IF EXISTS confidence
        """
    )
