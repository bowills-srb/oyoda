"""
Adopt active production-only operational tables into the migration tree.

Historical reconciliation:
- these tables exist in production and are referenced by active service code
- they were created outside the Alembic tree via standalone SQL/script paths
- production is the canonical source for their schema shape, indexes, and
  operational role

Revision ID: 066_adopt_active_production_only_tables
Revises: 065_adopt_missing_concierge_runtime_tables
Create Date: 2026-05-14
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


revision = "066_adopt_active_production_only_tables"
down_revision = "065_adopt_missing_concierge_runtime_tables"
branch_labels = None
depends_on = None


def _index_exists(bind: sa.engine.Connection, table_name: str, index_name: str) -> bool:
    inspector = inspect(bind)
    return any(idx["name"] == index_name for idx in inspector.get_indexes(table_name))


def _create_operator_market_links(bind: sa.engine.Connection) -> None:
    inspector = inspect(bind)
    if not inspector.has_table("operator_market_links"):
        table = sa.Table(
            "operator_market_links",
            sa.MetaData(),
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("market_id", sa.Text(), nullable=False),
            sa.Column("linked_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("company_id", "market_id", name="operator_market_links_company_id_market_id_key"),
        )
        table.create(bind, checkfirst=True)

    if not _index_exists(bind, "operator_market_links", "idx_oml_company"):
        op.create_index("idx_oml_company", "operator_market_links", ["company_id"])


def _create_property_incidents(bind: sa.engine.Connection) -> None:
    inspector = inspect(bind)
    if not inspector.has_table("property_incidents"):
        table = sa.Table(
            "property_incidents",
            sa.MetaData(),
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("property_external_id", sa.Text(), nullable=False),
            sa.Column("session_token", sa.Text(), nullable=True),
            sa.Column("escalation_ticket_id", sa.Text(), nullable=True),
            sa.Column("incident_type", sa.Text(), nullable=False),
            sa.Column("priority", sa.Text(), nullable=False),
            sa.Column("title", sa.Text(), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("guest_name", sa.Text(), nullable=True),
            sa.Column("guest_phone", sa.Text(), nullable=True),
            sa.Column("compensation_requested", sa.Boolean(), nullable=True),
            sa.Column("compensation_amount", sa.Numeric(), nullable=True),
            sa.Column("compensation_type", sa.Text(), nullable=True),
            sa.Column("compensation_notes", sa.Text(), nullable=True),
            sa.Column("compensation_approved_by", sa.Text(), nullable=True),
            sa.Column("compensation_approved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("status", sa.Text(), nullable=False),
            sa.Column("vendor_name", sa.Text(), nullable=True),
            sa.Column("vendor_eta_minutes", sa.Integer(), nullable=True),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("resolution_summary", sa.Text(), nullable=True),
            sa.Column("operator_notes", sa.Text(), nullable=True),
            sa.Column("reported_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        table.create(bind, checkfirst=True)

    if not _index_exists(bind, "property_incidents", "idx_incidents_property"):
        op.create_index(
            "idx_incidents_property",
            "property_incidents",
            ["property_external_id", "reported_at"],
        )
    if not _index_exists(bind, "property_incidents", "idx_incidents_company_status"):
        op.create_index(
            "idx_incidents_company_status",
            "property_incidents",
            ["company_id", "status"],
            postgresql_where=sa.text("status = ANY (ARRAY['open'::text, 'acknowledged'::text, 'in_progress'::text])"),
        )


def _create_security_audit_log(bind: sa.engine.Connection) -> None:
    inspector = inspect(bind)
    if not inspector.has_table("security_audit_log"):
        table = sa.Table(
            "security_audit_log",
            sa.MetaData(),
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("event_id", sa.Text(), nullable=False),
            sa.Column("event_type", sa.Text(), nullable=False),
            sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
            sa.Column("actor_id", sa.Text(), nullable=False),
            sa.Column("actor_type", sa.Text(), nullable=False),
            sa.Column("action", sa.Text(), nullable=False),
            sa.Column("resource_type", sa.Text(), nullable=False),
            sa.Column("resource_id", sa.Text(), nullable=False),
            sa.Column("success", sa.Boolean(), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("ip_address", sa.Text(), nullable=True),
            sa.Column("metadata", postgresql.JSONB(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        table.create(bind, checkfirst=True)

    if not _index_exists(bind, "security_audit_log", "idx_audit_actor"):
        op.create_index("idx_audit_actor", "security_audit_log", ["actor_id", "timestamp"])
    if not _index_exists(bind, "security_audit_log", "idx_audit_event_type"):
        op.create_index("idx_audit_event_type", "security_audit_log", ["event_type", "timestamp"])
    if not _index_exists(bind, "security_audit_log", "idx_audit_timestamp"):
        op.create_index("idx_audit_timestamp", "security_audit_log", ["timestamp"])
    if not _index_exists(bind, "security_audit_log", "idx_audit_success"):
        op.create_index(
            "idx_audit_success",
            "security_audit_log",
            ["success", "timestamp"],
            postgresql_where=sa.text("success = false"),
        )


def upgrade() -> None:
    bind = op.get_bind()
    _create_operator_market_links(bind)
    _create_property_incidents(bind)
    _create_security_audit_log(bind)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    for table_name, indexes in [
        ("security_audit_log", [
            "idx_audit_success",
            "idx_audit_timestamp",
            "idx_audit_event_type",
            "idx_audit_actor",
        ]),
        ("property_incidents", [
            "idx_incidents_company_status",
            "idx_incidents_property",
        ]),
        ("operator_market_links", ["idx_oml_company"]),
    ]:
        if inspector.has_table(table_name):
            existing_indexes = {idx["name"] for idx in inspector.get_indexes(table_name)}
            for index_name in indexes:
                if index_name in existing_indexes:
                    op.drop_index(index_name, table_name=table_name)
            op.drop_table(table_name)
