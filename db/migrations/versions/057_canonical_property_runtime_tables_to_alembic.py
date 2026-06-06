"""057_canonical_property_runtime_tables_to_alembic

Adopt runtime-created canonical property tables into Alembic.

These tables and indexes already exist in production today, but they
are currently created by runtime DDL inside
app/services/property_canonical_write_service.py. This migration is
intentionally adoptive and idempotent: it uses IF NOT EXISTS so it
succeeds against the current live schema while also making future
environments Alembic-managed rather than runtime-managed.

Objects adopted:

  - canonical_property_refs
  - canonical_property_profiles
  - canonical_property_link_reviews
  - idx_canonical_property_refs_lookup
  - idx_canonical_property_refs_code
  - idx_canonical_property_profiles_code
  - idx_canonical_property_link_reviews_status

Revision ID: 057_canonical_property_runtime_tables_to_alembic
Revises: 056_prebooking_runtime_columns_to_alembic
Create Date: 2026-05-07
"""

from alembic import op


revision = "057_canonical_property_runtime_tables_to_alembic"
down_revision = "056_prebooking_runtime_columns_to_alembic"
branch_labels = None
depends_on = None


UP_STATEMENTS = [
    "CREATE SEQUENCE IF NOT EXISTS canonical_property_refs_canonical_ref_id_seq",
    "CREATE SEQUENCE IF NOT EXISTS canonical_property_profiles_canonical_profile_id_seq",
    "CREATE SEQUENCE IF NOT EXISTS canonical_property_link_reviews_review_id_seq",
    """
    CREATE TABLE IF NOT EXISTS canonical_property_refs (
        canonical_ref_id BIGINT NOT NULL DEFAULT nextval('canonical_property_refs_canonical_ref_id_seq'::regclass),
        tenant_id UUID NOT NULL,
        canonical_property_code TEXT NOT NULL,
        provider TEXT NOT NULL DEFAULT 'internal'::text,
        ref_kind TEXT NOT NULL DEFAULT 'alias'::text,
        ref_value TEXT NOT NULL,
        normalized_ref_value TEXT NOT NULL,
        source TEXT NOT NULL DEFAULT 'system'::text,
        confidence NUMERIC(5,4) DEFAULT 1.0,
        metadata JSONB DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY (canonical_ref_id),
        UNIQUE (tenant_id, provider, ref_kind, normalized_ref_value)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS canonical_property_profiles (
        canonical_profile_id BIGINT NOT NULL DEFAULT nextval('canonical_property_profiles_canonical_profile_id_seq'::regclass),
        tenant_id UUID NOT NULL,
        canonical_property_code TEXT NOT NULL,
        display_name TEXT,
        marketing_name TEXT,
        preferred_address TEXT,
        source TEXT NOT NULL DEFAULT 'system'::text,
        metadata JSONB DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY (canonical_profile_id),
        UNIQUE (tenant_id, canonical_property_code)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS canonical_property_link_reviews (
        review_id BIGINT NOT NULL DEFAULT nextval('canonical_property_link_reviews_review_id_seq'::regclass),
        tenant_id UUID NOT NULL,
        canonical_property_code TEXT,
        provider TEXT NOT NULL DEFAULT 'internal'::text,
        ref_kind TEXT NOT NULL DEFAULT 'alias'::text,
        ref_value TEXT NOT NULL,
        normalized_ref_value TEXT NOT NULL,
        platform_listing_id TEXT,
        platform_unit_id TEXT,
        property_name TEXT,
        display_name TEXT,
        confidence NUMERIC(5,4) DEFAULT 0.0,
        status TEXT NOT NULL DEFAULT 'pending'::text,
        source TEXT NOT NULL DEFAULT 'system'::text,
        candidate_payload JSONB DEFAULT '[]'::jsonb,
        metadata JSONB DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY (review_id),
        UNIQUE (tenant_id, provider, ref_kind, normalized_ref_value, status)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_canonical_property_refs_lookup
        ON canonical_property_refs (tenant_id, normalized_ref_value)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_canonical_property_refs_code
        ON canonical_property_refs (tenant_id, canonical_property_code)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_canonical_property_profiles_code
        ON canonical_property_profiles (tenant_id, canonical_property_code)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_canonical_property_link_reviews_status
        ON canonical_property_link_reviews (tenant_id, status, created_at DESC)
    """,
]


DOWN_STATEMENTS = [
    "DROP INDEX IF EXISTS idx_canonical_property_link_reviews_status",
    "DROP INDEX IF EXISTS idx_canonical_property_profiles_code",
    "DROP INDEX IF EXISTS idx_canonical_property_refs_code",
    "DROP INDEX IF EXISTS idx_canonical_property_refs_lookup",
    "DROP TABLE IF EXISTS canonical_property_link_reviews CASCADE",
    "DROP TABLE IF EXISTS canonical_property_profiles CASCADE",
    "DROP TABLE IF EXISTS canonical_property_refs CASCADE",
    "DROP SEQUENCE IF EXISTS canonical_property_link_reviews_review_id_seq",
    "DROP SEQUENCE IF EXISTS canonical_property_profiles_canonical_profile_id_seq",
    "DROP SEQUENCE IF EXISTS canonical_property_refs_canonical_ref_id_seq",
]


def upgrade() -> None:
    # Railway re-runs `alembic upgrade head` during every deploy. Keep
    # adoptive migrations split into cheap idempotent statements so a
    # no-op re-run does not hit deploy-time statement timeouts.
    for statement in UP_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWN_STATEMENTS:
        op.execute(statement)
