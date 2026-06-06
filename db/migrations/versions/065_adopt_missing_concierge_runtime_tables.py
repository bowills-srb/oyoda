"""
Adopt missing concierge runtime tables into production.

Historical reconciliation:
- these tables already exist in the migration tree, but they are absent in
  production despite their ancestor migrations being in the applied lineage
- current service code compensates with `_table_exists` / `_table_columns`
  guards, which masks the gap instead of making the schema authoritative
- this migration creates the missing runtime tables and indexes without
  disturbing environments where they already exist

Revision ID: 065_adopt_missing_concierge_runtime_tables
Revises: 064_reconcile_concierge_guest_sessions_relational_contract
Create Date: 2026-05-14
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


revision = "065_adopt_missing_concierge_runtime_tables"
down_revision = "064_reconcile_concierge_guest_sessions_relational_contract"
branch_labels = None
depends_on = None


def _index_exists(bind: sa.engine.Connection, table_name: str, index_name: str) -> bool:
    inspector = inspect(bind)
    return any(idx["name"] == index_name for idx in inspector.get_indexes(table_name))


def _create_operational_snapshots(bind: sa.engine.Connection) -> None:
    inspector = inspect(bind)
    if not inspector.has_table("operational_snapshots"):
        table = sa.Table(
            "operational_snapshots",
            sa.MetaData(),
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("property_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("next_checkin", sa.DateTime(), nullable=True),
            sa.Column("next_checkout", sa.DateTime(), nullable=True),
            sa.Column("current_reservation_id", sa.String(100), nullable=True),
            sa.Column("turnover_status", sa.String(20), nullable=True, server_default=sa.text("'normal'")),
            sa.Column("turnover_buffer_hours", sa.Float(), nullable=True, server_default=sa.text("5.0")),
            sa.Column("cleaning_status", sa.String(20), nullable=True, server_default=sa.text("'not_scheduled'")),
            sa.Column("cleaning_scheduled_at", sa.DateTime(), nullable=True),
            sa.Column("staff_capacity", sa.String(20), nullable=True, server_default=sa.text("'normal'")),
            sa.Column("has_critical_issues", sa.Boolean(), nullable=True, server_default=sa.text("false")),
            sa.Column("known_issues", postgresql.JSONB(), nullable=True),
            sa.Column("snapshot_at", sa.DateTime(), nullable=True, server_default=sa.func.now()),
            sa.Column("created_at", sa.DateTime(), nullable=True, server_default=sa.func.now()),
        )
        table.create(bind, checkfirst=True)

    if not _index_exists(bind, "operational_snapshots", "ix_ops_snapshot_property"):
        op.create_index("ix_ops_snapshot_property", "operational_snapshots", ["property_id"])
    if not _index_exists(bind, "operational_snapshots", "ix_ops_snapshot_time"):
        op.create_index("ix_ops_snapshot_time", "operational_snapshots", ["snapshot_at"])


def _create_concierge_journey_tables(bind: sa.engine.Connection) -> None:
    inspector = inspect(bind)
    metadata = sa.MetaData()
    sa.Table(
        "concierge_guest_sessions",
        metadata,
        sa.Column("session_id", postgresql.UUID(as_uuid=True)),
        extend_existing=True,
    )

    if not inspector.has_table("concierge_guest_journeys"):
        table = sa.Table(
            "concierge_guest_journeys",
            metadata,
            sa.Column("journey_id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
            sa.Column("welcome_sent", sa.Boolean(), nullable=True),
            sa.Column("welcome_sent_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("extend_offer_sent", sa.Boolean(), nullable=True),
            sa.Column("extend_offer_sent_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("extend_offer_response", sa.String(20), nullable=True),
            sa.Column("pool_heat_offered", sa.Boolean(), nullable=True),
            sa.Column("pool_heat_accepted", sa.Boolean(), nullable=True),
            sa.Column("checkin_reminder_sent", sa.Boolean(), nullable=True),
            sa.Column("checkin_reminder_sent_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("checkout_reminder_sent", sa.Boolean(), nullable=True),
            sa.Column("checkout_reminder_sent_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["session_id"], ["concierge_guest_sessions.session_id"], ondelete="CASCADE"),
        )
        table.create(bind, checkfirst=True)

    if not _index_exists(bind, "concierge_guest_journeys", "ix_concierge_journey_tenant"):
        op.create_index("ix_concierge_journey_tenant", "concierge_guest_journeys", ["tenant_id"])

    if not inspector.has_table("concierge_journey_activities"):
        table = sa.Table(
            "concierge_journey_activities",
            metadata,
            sa.Column("activity_id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("journey_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("activity_type", sa.String(50), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'not_discussed'")),
            sa.Column("discussed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["journey_id"], ["concierge_guest_journeys.journey_id"], ondelete="CASCADE"),
        )
        table.create(bind, checkfirst=True)

    if not _index_exists(bind, "concierge_journey_activities", "ix_concierge_activity_journey_type"):
        op.create_index(
            "ix_concierge_activity_journey_type",
            "concierge_journey_activities",
            ["journey_id", "activity_type"],
        )

    if not inspector.has_table("concierge_messages"):
        table = sa.Table(
            "concierge_messages",
            metadata,
            sa.Column("message_id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("direction", sa.String(10), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("content_type", sa.String(20), nullable=True, server_default=sa.text("'text'")),
            sa.Column("detected_intent", sa.String(100), nullable=True),
            sa.Column("was_quick_answer", sa.Boolean(), nullable=True, server_default=sa.text("false")),
            sa.Column("response_time_ms", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["session_id"], ["concierge_guest_sessions.session_id"], ondelete="CASCADE"),
        )
        table.create(bind, checkfirst=True)

    if not _index_exists(bind, "concierge_messages", "ix_concierge_message_session_created"):
        op.create_index("ix_concierge_message_session_created", "concierge_messages", ["session_id", "created_at"])

    if not inspector.has_table("concierge_notifications"):
        table = sa.Table(
            "concierge_notifications",
            metadata,
            sa.Column("notification_id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("notification_type", sa.String(50), nullable=False),
            sa.Column("channel", sa.String(20), nullable=False),
            sa.Column("recipient", sa.String(255), nullable=False),
            sa.Column("subject", sa.String(255), nullable=True),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'pending'")),
            sa.Column("external_id", sa.String(255), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["session_id"], ["concierge_guest_sessions.session_id"], ondelete="CASCADE"),
        )
        table.create(bind, checkfirst=True)

    if not _index_exists(bind, "concierge_notifications", "ix_concierge_notification_session_type"):
        op.create_index(
            "ix_concierge_notification_session_type",
            "concierge_notifications",
            ["session_id", "notification_type"],
        )
    if not _index_exists(bind, "concierge_notifications", "ix_concierge_notification_session_created"):
        op.create_index(
            "ix_concierge_notification_session_created",
            "concierge_notifications",
            ["session_id", "created_at"],
        )
    if not _index_exists(bind, "concierge_notifications", "ix_concierge_notification_status"):
        op.create_index("ix_concierge_notification_status", "concierge_notifications", ["status"])


def _create_concierge_onboarding_sessions(bind: sa.engine.Connection) -> None:
    inspector = inspect(bind)
    if not inspector.has_table("concierge_onboarding_sessions"):
        table = sa.Table(
            "concierge_onboarding_sessions",
            sa.MetaData(),
            sa.Column("session_id", sa.String(50), primary_key=True),
            sa.Column("session_data", postgresql.JSONB(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        )
        table.create(bind, checkfirst=True)

    if not _index_exists(bind, "concierge_onboarding_sessions", "ix_onboarding_sessions_updated"):
        op.create_index("ix_onboarding_sessions_updated", "concierge_onboarding_sessions", ["updated_at"])


def _create_concierge_dining_reservations(bind: sa.engine.Connection) -> None:
    inspector = inspect(bind)
    if not inspector.has_table("concierge_dining_reservations"):
        table = sa.Table(
            "concierge_dining_reservations",
            sa.MetaData(),
            sa.Column("dining_reservation_id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("operator_id", sa.String(100), nullable=False),
            sa.Column("session_token", sa.String(120), nullable=True),
            sa.Column("guest_name", sa.String(255), nullable=False),
            sa.Column("guest_phone", sa.String(50), nullable=True),
            sa.Column("guest_email", sa.String(255), nullable=True),
            sa.Column("restaurant_name", sa.String(255), nullable=False),
            sa.Column("reservation_date", sa.String(32), nullable=False),
            sa.Column("reservation_time", sa.String(32), nullable=False),
            sa.Column("party_size", sa.Integer(), nullable=False),
            sa.Column("special_requests", sa.Text(), nullable=True),
            sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("status", sa.String(50), nullable=False),
            sa.Column("message", sa.Text(), nullable=False),
            sa.Column("source", sa.String(50), nullable=False),
            sa.Column("confirmation_id", sa.String(120), nullable=True),
            sa.Column("booking_url", sa.Text(), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("request_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("response_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        table.create(bind, checkfirst=True)

    for index_name, cols in [
        ("ix_concierge_dining_reservations_operator_id", ["operator_id"]),
        ("ix_concierge_dining_reservations_session_token", ["session_token"]),
        ("ix_concierge_dining_reservations_restaurant_name", ["restaurant_name"]),
        ("ix_concierge_dining_reservations_reservation_date", ["reservation_date"]),
        ("ix_concierge_dining_reservations_status", ["status"]),
        ("ix_concierge_dining_reservations_confirmation_id", ["confirmation_id"]),
        ("ix_concierge_dining_operator_created", ["operator_id", "created_at"]),
        ("ix_concierge_dining_session_created", ["session_token", "created_at"]),
    ]:
        if not _index_exists(bind, "concierge_dining_reservations", index_name):
            op.create_index(index_name, "concierge_dining_reservations", cols)


def upgrade() -> None:
    bind = op.get_bind()
    _create_operational_snapshots(bind)
    _create_concierge_journey_tables(bind)
    _create_concierge_onboarding_sessions(bind)
    _create_concierge_dining_reservations(bind)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    for table_name, indexes in [
        ("concierge_dining_reservations", [
            "ix_concierge_dining_session_created",
            "ix_concierge_dining_operator_created",
            "ix_concierge_dining_reservations_confirmation_id",
            "ix_concierge_dining_reservations_status",
            "ix_concierge_dining_reservations_reservation_date",
            "ix_concierge_dining_reservations_restaurant_name",
            "ix_concierge_dining_reservations_session_token",
            "ix_concierge_dining_reservations_operator_id",
        ]),
        ("concierge_onboarding_sessions", ["ix_onboarding_sessions_updated"]),
        ("concierge_notifications", [
            "ix_concierge_notification_status",
            "ix_concierge_notification_session_created",
            "ix_concierge_notification_session_type",
        ]),
        ("concierge_messages", ["ix_concierge_message_session_created"]),
        ("concierge_journey_activities", ["ix_concierge_activity_journey_type"]),
        ("concierge_guest_journeys", ["ix_concierge_journey_tenant"]),
        ("operational_snapshots", ["ix_ops_snapshot_time", "ix_ops_snapshot_property"]),
    ]:
        if inspector.has_table(table_name):
            existing_indexes = {idx["name"] for idx in inspector.get_indexes(table_name)}
            for index_name in indexes:
                if index_name in existing_indexes:
                    op.drop_index(index_name, table_name=table_name)
            op.drop_table(table_name)
