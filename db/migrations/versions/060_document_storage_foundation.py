"""060_document_storage_foundation

First durable source-document storage tables for operator uploads and extraction.
"""

from alembic import op


revision = "060_document_storage_foundation"
down_revision = "059_concierge_scoped_knowledge"
branch_labels = None
depends_on = None


UP_SQL = """
CREATE TABLE IF NOT EXISTS documents (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL,
    property_id         UUID,
    document_group_id   UUID NOT NULL DEFAULT gen_random_uuid(),
    scope_type          TEXT NOT NULL DEFAULT 'property',
    version_number      INTEGER NOT NULL DEFAULT 1,
    document_type       TEXT NOT NULL,
    filename            TEXT NOT NULL,
    file_path           TEXT NOT NULL,
    storage_backend     TEXT NOT NULL DEFAULT 'r2',
    file_size           INTEGER,
    mime_type           TEXT,
    content_hash        TEXT,
    upload_method       TEXT NOT NULL DEFAULT 'operator_upload',
    extraction_status   TEXT NOT NULL DEFAULT 'pending',
    extraction_error    TEXT,
    extracted_fields    JSONB NOT NULL DEFAULT '{}'::jsonb,
    uploaded_by         TEXT,
    uploaded_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at        TIMESTAMPTZ,
    CONSTRAINT uq_documents_group_version UNIQUE (document_group_id, version_number)
);

CREATE INDEX IF NOT EXISTS idx_documents_tenant ON documents (tenant_id);
CREATE INDEX IF NOT EXISTS idx_documents_property ON documents (property_id);
CREATE INDEX IF NOT EXISTS idx_documents_group ON documents (document_group_id, version_number DESC);
CREATE INDEX IF NOT EXISTS idx_documents_hash ON documents (tenant_id, content_hash);

CREATE TABLE IF NOT EXISTS extracted_fields (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id     UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    tenant_id       UUID NOT NULL,
    property_id     UUID,
    field_name      TEXT NOT NULL,
    field_value     JSONB,
    confidence      TEXT NOT NULL DEFAULT 'medium',
    source_page     INTEGER,
    source_text     TEXT,
    verified        TEXT NOT NULL DEFAULT 'unverified',
    verified_by     TEXT,
    extracted_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_extracted_fields_document ON extracted_fields (document_id);
CREATE INDEX IF NOT EXISTS idx_extracted_fields_tenant ON extracted_fields (tenant_id);
CREATE INDEX IF NOT EXISTS idx_extracted_fields_property ON extracted_fields (property_id);
"""


DOWN_SQL = """
DROP TABLE IF EXISTS extracted_fields CASCADE;
DROP TABLE IF EXISTS documents CASCADE;
"""


def upgrade() -> None:
    op.execute(UP_SQL)


def downgrade() -> None:
    op.execute(DOWN_SQL)
