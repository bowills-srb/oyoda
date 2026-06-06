from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.db_connect import is_pgbouncer_url, sqlalchemy_connect_args


SNAPSHOT_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "production_schema_snapshots"
LIVE_DB_ENV_VARS = ("TEST_DATABASE_URL", "TEST_ALEMBIC_DATABASE_URL")


def _live_database_url() -> str | None:
    for env_var in LIVE_DB_ENV_VARS:
        value = os.getenv(env_var, "").strip()
        if value:
            return value
    return None


def _load_snapshot(table_name: str) -> dict:
    path = SNAPSHOT_DIR / f"{table_name}.json"
    if not path.exists():
        pytest.skip(f"No snapshot for {table_name}; run scripts/capture_production_schema_snapshot.py")
    return json.loads(path.read_text())


async def _query_live_schema(table_name: str) -> dict | None:
    database_url = _live_database_url()
    if not database_url:
        return None

    engine_kwargs = {
        "echo": False,
        "connect_args": sqlalchemy_connect_args(database_url),
    }
    if is_pgbouncer_url(database_url):
        engine_kwargs["poolclass"] = NullPool
    engine = create_async_engine(database_url, **engine_kwargs)
    try:
        async with engine.connect() as conn:
            columns = (
                await conn.execute(
                    text(
                        """
                        SELECT
                            column_name,
                            data_type,
                            udt_name,
                            (is_nullable = 'YES') AS is_nullable,
                            column_default
                        FROM information_schema.columns
                        WHERE table_schema = 'public'
                          AND table_name = :table_name
                        ORDER BY ordinal_position
                        """
                    ),
                    {"table_name": table_name},
                )
            ).mappings().all()
            indexes = (
                await conn.execute(
                    text(
                        """
                        SELECT
                            idx.relname AS indexname,
                            ix.indisunique AS is_unique,
                            COALESCE(
                                array_agg(att.attname ORDER BY key.ordinality)
                                    FILTER (WHERE att.attname IS NOT NULL),
                                ARRAY[]::text[]
                            ) AS columns,
                            pg_get_indexdef(ix.indexrelid) AS indexdef
                        FROM pg_class tbl
                        JOIN pg_namespace ns
                          ON ns.oid = tbl.relnamespace
                        JOIN pg_index ix
                          ON tbl.oid = ix.indrelid
                        JOIN pg_class idx
                          ON idx.oid = ix.indexrelid
                        LEFT JOIN LATERAL unnest(ix.indkey) WITH ORDINALITY AS key(attnum, ordinality)
                          ON TRUE
                        LEFT JOIN pg_attribute att
                          ON att.attrelid = tbl.oid
                         AND att.attnum = key.attnum
                        WHERE ns.nspname = 'public'
                          AND tbl.relname = :table_name
                        GROUP BY idx.relname, ix.indisunique, ix.indexrelid
                        ORDER BY idx.relname
                        """
                    ),
                    {"table_name": table_name},
                )
            ).mappings().all()
    finally:
        await engine.dispose()

    return {
        "table": table_name,
        "columns": [dict(row) for row in columns],
        "indexes": [dict(row) for row in indexes],
    }


def _schema_for(table_name: str) -> dict:
    live = asyncio.run(_query_live_schema(table_name))
    return live if live is not None else _load_snapshot(table_name)


def _columns_by_name(schema: dict) -> dict[str, dict]:
    return {column["column_name"]: column for column in schema["columns"]}


def _indexes_by_name(schema: dict) -> dict[str, dict]:
    return {index["indexname"]: index for index in schema["indexes"]}


def _normalized_type(column: dict) -> str:
    data_type = str(column.get("data_type") or "")
    if data_type.lower() == "user-defined":
        return str(column.get("udt_name") or "").lower()
    normalized = data_type.lower()
    aliases = {
        "character varying": "varchar",
        "timestamp with time zone": "timestamptz",
    }
    return aliases.get(normalized, normalized)


def _assert_column(
    schema: dict,
    *,
    column_name: str,
    expected_type: str,
    required_for: str,
    migration_hint: str,
    nullable: bool | None = None,
) -> None:
    columns = _columns_by_name(schema)
    assert column_name in columns, (
        f"{schema['table']}.{column_name} is missing. "
        f"{required_for} depends on it. "
        f"Expected shape should come from {migration_hint}."
    )
    actual = columns[column_name]
    actual_type = _normalized_type(actual)
    assert actual_type == expected_type.lower(), (
        f"{schema['table']}.{column_name} has type {actual_type!r}, "
        f"expected {expected_type!r}. {required_for} depends on this shape. "
        f"Verify {migration_hint} or refresh the production snapshot if the "
        f"schema intentionally changed."
    )
    if nullable is not None:
        assert bool(actual.get("is_nullable")) is nullable, (
            f"{schema['table']}.{column_name} nullable={actual.get('is_nullable')!r}, "
            f"expected {nullable!r}. {required_for} depends on this contract."
        )


def _assert_index(
    schema: dict,
    *,
    index_name: str,
    required_for: str,
    migration_hint: str,
    columns: list[str] | None = None,
    unique: bool | None = None,
    indexdef_contains: list[str] | None = None,
) -> None:
    indexes = _indexes_by_name(schema)
    assert index_name in indexes, (
        f"{schema['table']} index {index_name!r} is missing. "
        f"{required_for} depends on it. Expected shape should come from "
        f"{migration_hint}."
    )
    actual = indexes[index_name]
    if columns is not None:
        assert list(actual.get("columns") or []) == columns, (
            f"{schema['table']} index {index_name!r} columns={actual.get('columns')!r}, "
            f"expected {columns!r}. {required_for} depends on this shape."
        )
    if unique is not None:
        assert bool(actual.get("is_unique")) is unique, (
            f"{schema['table']} index {index_name!r} unique={actual.get('is_unique')!r}, "
            f"expected {unique!r}. {required_for} depends on this shape."
        )
    if indexdef_contains:
        indexdef = str(actual.get("indexdef") or "")
        missing = [fragment for fragment in indexdef_contains if fragment not in indexdef]
        assert not missing, (
            f"{schema['table']} index {index_name!r} definition did not include "
            f"{missing!r}. Actual definition: {indexdef!r}. "
            f"{required_for} depends on this contract."
        )


def test_operator_policies_shape_phase_4_3_l_1() -> None:
    schema = _schema_for("operator_policies")

    _assert_column(
        schema,
        column_name="tenant_id",
        expected_type="uuid",
        nullable=True,
        required_for="Phase 4.3-L.1 canonical operator_policies identity",
        migration_hint="074_operator_policies_tenant_id_canonical.py",
    )
    _assert_column(
        schema,
        column_name="market_id",
        expected_type="varchar",
        nullable=True,
        required_for="Phase 4.3-L.1 market lookup and operator policy reconciliation",
        migration_hint="080_operator_policies_market_id_corrective.py",
    )
    _assert_column(
        schema,
        column_name="upsell_rates",
        expected_type="jsonb",
        required_for="Phase 4.3-L.1 canonical upsell-rate reads and writes",
        migration_hint="existing operator_policies schema plus 074/080 reconciliation",
    )
    _assert_column(
        schema,
        column_name="upsell_rates_configured",
        expected_type="boolean",
        required_for="Phase 4.3-L.1 explicit upsell default-vs-configured behavior",
        migration_hint="existing operator_policies schema plus 074/080 reconciliation",
    )
    _assert_index(
        schema,
        index_name="ux_operator_policies_tenant_id",
        unique=True,
        required_for="Phase 4.3-L.1 ON CONFLICT (tenant_id) policy upserts",
        migration_hint="074_operator_policies_tenant_id_canonical.py",
        indexdef_contains=["tenant_id", "WHERE (tenant_id IS NOT NULL)"],
    )
    _assert_index(
        schema,
        index_name="ix_operator_policies_market_id",
        unique=False,
        columns=["market_id"],
        required_for="Phase 4.3-L.1 market_id reads from operator_policies",
        migration_hint="080_operator_policies_market_id_corrective.py",
    )


def test_operator_settings_shape_phase_4_3_m_and_n() -> None:
    schema = _schema_for("operator_settings")

    _assert_column(
        schema,
        column_name="tenant_id",
        expected_type="uuid",
        nullable=False,
        required_for="Phase 4.3-M and 4.3-N tenant-scoped runtime settings",
        migration_hint="026_dashboard_tables.py",
    )
    _assert_column(
        schema,
        column_name="extra",
        expected_type="jsonb",
        nullable=False,
        required_for="Phase 4.3-M thresholds and Phase 4.3-N reservation-routing windows",
        migration_hint="026_dashboard_tables.py",
    )
    _assert_index(
        schema,
        index_name="operator_settings_pkey",
        unique=True,
        columns=["tenant_id"],
        required_for="tenant-scoped operator_settings reads for Phase 4.3-M and 4.3-N",
        migration_hint="026_dashboard_tables.py",
    )


def test_message_normalizations_shape_phase_4_3_i_m_n() -> None:
    schema = _schema_for("message_normalizations")

    for column_name, expected_type, migration_hint, required_for in [
        ("source_channel", "text", "036_message_normalizations.py", "canonical inbound normalization identity"),
        ("source_message_id", "text", "036_message_normalizations.py", "canonical inbound normalization identity"),
        ("parser_notes", "jsonb", "036_message_normalizations.py", "Phase 4.3-M and 4.3-N parser-note audit payloads"),
        ("route_outcome", "text", "036_message_normalizations.py", "Phase 4.3-I/4.3-M/4.3-N route outcome persistence"),
        ("draft_source", "text", "036_message_normalizations.py", "Phase 4.3-I/4.3-M/4.3-N draft-source persistence"),
        ("composer_source", "text", "054_message_normalizations_composer_metadata.py", "composer metadata audit persistence"),
        ("composer_response_text", "text", "054_message_normalizations_composer_metadata.py", "composer metadata audit persistence"),
        ("composer_notes", "jsonb", "054_message_normalizations_composer_metadata.py", "composer metadata audit persistence"),
    ]:
        _assert_column(
            schema,
            column_name=column_name,
            expected_type=expected_type,
            required_for=required_for,
            migration_hint=migration_hint,
        )

    _assert_index(
        schema,
        index_name="uq_message_norm_source",
        unique=True,
        required_for="Phase 4.3-I normalization invariant and audit row upserts",
        migration_hint="036_message_normalizations.py",
        indexdef_contains=["tenant_id", "source_channel", "source_message_id"],
    )
    _assert_index(
        schema,
        index_name="idx_msg_norm_tenant_route",
        required_for="route outcome coverage and recent-phase audit reads",
        migration_hint="036_message_normalizations.py",
        indexdef_contains=["tenant_id", "route_outcome"],
    )


def test_canonical_property_link_reviews_shape_phase_4_4_c() -> None:
    schema = _schema_for("canonical_property_link_reviews")

    for column_name, expected_type, nullable in [
        ("review_id", "bigint", False),
        ("tenant_id", "uuid", False),
        ("canonical_property_code", "text", True),
        ("provider", "text", False),
        ("ref_kind", "text", False),
        ("ref_value", "text", False),
        ("normalized_ref_value", "text", False),
        ("confidence", "numeric", True),
        ("status", "text", False),
        ("candidate_payload", "jsonb", True),
        ("metadata", "jsonb", True),
        ("created_at", "timestamptz", False),
        ("updated_at", "timestamptz", False),
    ]:
        _assert_column(
            schema,
            column_name=column_name,
            expected_type=expected_type,
            nullable=nullable,
            required_for="Phase 4.4.C unified property-alias review queue",
            migration_hint="057_canonical_property_runtime_tables_to_alembic.py",
        )

    _assert_index(
        schema,
        index_name="idx_canonical_property_link_reviews_status",
        required_for="pending canonical property alias review queue reads",
        migration_hint="057_canonical_property_runtime_tables_to_alembic.py",
        indexdef_contains=["tenant_id", "status", "created_at"],
    )


def test_concierge_knowledge_gaps_shape() -> None:
    schema = _schema_for("concierge_knowledge_gaps")

    for column_name, expected_type in [
        ("tenant_id", "uuid"),
        ("gap_id", "uuid"),
        ("property_external_id", "varchar"),
        ("question_text", "text"),
        ("channel", "varchar"),
        ("source", "varchar"),
        ("detected_intent", "varchar"),
        ("confidence_score", "double precision"),
        ("resolved", "boolean"),
        ("resolution_notes", "text"),
        ("metadata", "jsonb"),
        ("created_at", "timestamptz"),
    ]:
        _assert_column(
            schema,
            column_name=column_name,
            expected_type=expected_type,
            required_for="knowledge-gap persistence and operator dashboard reads",
            migration_hint="005_concierge_knowledge_gaps.py",
        )

    for index_name in (
        "ix_concierge_knowledge_gaps_tenant_created",
        "ix_concierge_knowledge_gaps_tenant_resolved",
        "ix_concierge_knowledge_gaps_tenant_property_external",
    ):
        _assert_index(
            schema,
            index_name=index_name,
            required_for="knowledge-gap dashboard and triage queries",
            migration_hint="005_concierge_knowledge_gaps.py",
        )


def test_knowledge_gap_drafts_shape_phase_4_4_a() -> None:
    schema = _schema_for("knowledge_gap_drafts")

    for column_name, expected_type, nullable in [
        ("draft_id", "text", False),
        ("tenant_id", "uuid", False),
        ("property_code", "text", True),
        ("operator_id", "text", True),
        ("question", "text", False),
        ("answer_hint", "text", True),
        ("gap_ids", "jsonb", False),
        ("occurrence_count", "integer", False),
        ("status", "text", False),
        ("indexed_doc_id", "text", True),
        ("reviewed_by", "text", True),
        ("reviewed_at", "timestamptz", True),
        ("rejection_reason", "text", True),
        ("created_at", "timestamptz", False),
    ]:
        _assert_column(
            schema,
            column_name=column_name,
            expected_type=expected_type,
            nullable=nullable,
            required_for="Phase 4.4.A knowledge curator review queue persistence",
            migration_hint="082_knowledge_gap_drafts.py",
        )

    _assert_index(
        schema,
        index_name="ix_knowledge_gap_drafts_tenant_status",
        required_for="tenant-scoped knowledge curator draft queue reads",
        migration_hint="082_knowledge_gap_drafts.py",
        indexdef_contains=["tenant_id", "status", "occurrence_count"],
    )
    _assert_index(
        schema,
        index_name="ix_knowledge_gap_drafts_property_status",
        required_for="property-specific pending-review draft filtering",
        migration_hint="082_knowledge_gap_drafts.py",
        indexdef_contains=["property_code", "status", "WHERE (status = 'pending_review'::text)"],
    )


def test_pre_booking_inquiries_shape_recent_phases() -> None:
    schema = _schema_for("pre_booking_inquiries")

    for column_name, expected_type, migration_hint in [
        ("company_id", "uuid", "018_pre_booking_pipeline.py"),
        ("tenant_id", "uuid", "069_phase_3b_add_tenant_id_to_operational_tables.py"),
        ("draft_id", "text", "018_pre_booking_pipeline.py"),
        ("property_external_id", "text", "018_pre_booking_pipeline.py"),
        ("property_external_id_source", "jsonb", "078_pre_booking_inquiries_property_source.py"),
        ("intent", "text", "018_pre_booking_pipeline.py"),
        ("confidence", "numeric", "018_pre_booking_pipeline.py"),
        ("message_text", "text", "018_pre_booking_pipeline.py"),
        ("gmail_thread_id", "text", "056_prebooking_runtime_columns_to_alembic.py"),
        ("gmail_message_id", "text", "056_prebooking_runtime_columns_to_alembic.py"),
        ("guest_thread_id", "uuid", "049_guest_threads_and_module_flags.py"),
        ("archived_at", "timestamptz", "079_pre_booking_inquiries_archive_columns.py"),
        ("archive_reason", "varchar", "079_pre_booking_inquiries_archive_columns.py"),
    ]:
        _assert_column(
            schema,
            column_name=column_name,
            expected_type=expected_type,
            required_for="recent pre-booking persistence and archival paths",
            migration_hint=migration_hint,
        )

    for index_name in (
        "ix_pre_booking_inquiries_tenant_status_created_at",
        "ix_pre_booking_inquiries_tenant_gmail_thread",
        "idx_inquiries_company_status",
        "idx_inquiries_property",
        "idx_inquiries_platform",
        "idx_pre_booking_inquiries_guest_thread",
    ):
        _assert_index(
            schema,
            index_name=index_name,
            required_for="pre-booking queue, Gmail thread, and archival reads",
            migration_hint="018/049/069/078/079 pre_booking_inquiries migration chain",
        )


def test_pms_bookings_shape_phase_4_3_n() -> None:
    schema = _schema_for("pms_bookings")

    for column_name, expected_type, migration_hint in [
        ("company_id", "uuid", "018_pre_booking_pipeline.py"),
        ("external_id", "text", "018_pre_booking_pipeline.py"),
        ("status", "text", "018_pre_booking_pipeline.py"),
        ("guest_email", "text", "037_pms_booking_guest_identity.py"),
        ("guest_first_name", "text", "037_pms_booking_guest_identity.py"),
        ("guest_last_name", "text", "037_pms_booking_guest_identity.py"),
        ("check_in", "date", "018_pre_booking_pipeline.py"),
        ("check_out", "date", "018_pre_booking_pipeline.py"),
    ]:
        _assert_column(
            schema,
            column_name=column_name,
            expected_type=expected_type,
            required_for="Phase 4.3-N reservation-aware routing fallback lookups",
            migration_hint=migration_hint,
        )

    for index_name in (
        "idx_bookings_checkin",
        "idx_pms_bookings_guest_email",
        "idx_pms_bookings_guest_phone",
        "pms_bookings_company_id_external_id_key",
    ):
        _assert_index(
            schema,
            index_name=index_name,
            required_for="Phase 4.3-N reservation-aware routing local-cache lookups",
            migration_hint="018_pre_booking_pipeline.py and 037_pms_booking_guest_identity.py",
        )


def test_healer_proposals_shape_phase_4_4_session_1() -> None:
    schema = _schema_for("healer_proposals")

    for column_name, expected_type, nullable in [
        ("proposal_id", "uuid", False),
        ("tenant_id", "uuid", False),
        ("proposal_kind", "text", False),
        ("signal_source", "text", False),
        ("dedup_key", "text", False),
        ("summary", "text", False),
        ("evidence", "jsonb", False),
        ("proposed_change", "jsonb", False),
        ("status", "text", False),
        ("confidence", "double precision", False),
        ("cluster_size", "integer", False),
        ("created_at", "timestamptz", False),
        ("reviewed_at", "timestamptz", True),
        ("reviewed_by", "text", True),
        ("review_notes", "text", True),
    ]:
        _assert_column(
            schema,
            column_name=column_name,
            expected_type=expected_type,
            nullable=nullable,
            required_for="Phase 4.4 Healer Agent Session 1 review queue and audit persistence",
            migration_hint="081_healer_proposals.py",
        )

    _assert_index(
        schema,
        index_name="ix_healer_proposals_tenant_status",
        required_for="tenant-scoped healer review queue reads",
        migration_hint="081_healer_proposals.py",
        indexdef_contains=["tenant_id", "status", "created_at"],
    )
    _assert_index(
        schema,
        index_name="ux_healer_proposals_pending_dedup",
        unique=True,
        required_for="deduplicated healer proposal upserts while pending",
        migration_hint="081_healer_proposals.py",
        indexdef_contains=["tenant_id", "proposal_kind", "dedup_key", "WHERE (status = 'pending'::text)"],
    )
