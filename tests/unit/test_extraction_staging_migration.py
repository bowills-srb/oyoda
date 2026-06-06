from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
import types

if "alembic" not in sys.modules:
    fake_alembic = types.ModuleType("alembic")
    fake_alembic.op = object()
    sys.modules["alembic"] = fake_alembic

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "db"
    / "migrations"
    / "versions"
    / "061_extraction_staging.py"
)
_SPEC = spec_from_file_location("migration_061_extraction_staging", _MIGRATION_PATH)
assert _SPEC and _SPEC.loader
shim = module_from_spec(_SPEC)
_SPEC.loader.exec_module(shim)


def test_extraction_staging_migration_has_expected_revision_chain():
    assert shim.revision == "061_extraction_staging"
    assert shim.down_revision == "060_document_storage_foundation"


def test_extraction_staging_migration_defines_expected_sql_shape():
    create_stmt = shim.UP_STATEMENTS[0]
    assert "CREATE TABLE IF NOT EXISTS extraction_candidates" in create_stmt
    assert "source_document_id UUID REFERENCES documents(id) ON DELETE SET NULL" in create_stmt
    assert "candidate_type TEXT NOT NULL" in create_stmt
    assert "confidence NUMERIC(4,3) NOT NULL DEFAULT 0.0" in create_stmt
    assert "review_status TEXT NOT NULL DEFAULT 'pending'" in create_stmt
    assert "proposed_tags JSONB NOT NULL DEFAULT '[]'::jsonb" in create_stmt
    assert "proposed_metadata JSONB NOT NULL DEFAULT '{}'::jsonb" in create_stmt


def test_extraction_staging_migration_indexes_cover_review_queries():
    joined = "\n".join(shim.UP_STATEMENTS)
    assert "idx_extraction_candidates_tenant_review_status" in joined
    assert "idx_extraction_candidates_tenant_scope_target" in joined
    assert "idx_extraction_candidates_tenant_source_document" in joined
    assert "idx_extraction_candidates_tenant_type_status" in joined
    assert "idx_extraction_candidates_question_key_scope_target" in joined
