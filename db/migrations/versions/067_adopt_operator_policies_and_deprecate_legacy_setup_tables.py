"""
Adopt operator_policies and formally deprecate legacy setup tables.

Historical reconciliation:
- `operator_policies` is an active product surface used by operator endpoints
  and pricing/rules logic
- the production table is missing even though the concept is live in code
- the original `010_operator_policies_markets` migration bundled three
  operator-scoped tables together, but only `operator_policies` remains a
  canonical concept today
- `operator_onboarding` was superseded by `operator_signup.py` plus
  `operator_auth_service`
- `operator_integrations` was superseded by `integration_gateway.py`; future
  DB-backed tenant integration config belongs in the canonical Phase 3/4
  schema work, not in this legacy table shape
- current code also expects `upsell_rates` and `upsell_rates_configured`,
  which were never present in the original migration

Revision ID: 067_adopt_operator_policies_and_deprecate_legacy_setup_tables
Revises: 066_adopt_active_production_only_tables
Create Date: 2026-05-14
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


revision = "067_adopt_operator_policies_and_deprecate_legacy_setup_tables"
down_revision = "066_adopt_active_production_only_tables"
branch_labels = None
depends_on = None


def _index_exists(bind: sa.engine.Connection, table_name: str, index_name: str) -> bool:
    inspector = inspect(bind)
    return any(idx["name"] == index_name for idx in inspector.get_indexes(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if not inspector.has_table("operator_policies"):
        table = sa.Table(
            "operator_policies",
            sa.MetaData(),
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("operator_id", sa.String(100), nullable=False, unique=True),
            sa.Column("check_in_time", sa.String(20), nullable=True, server_default=sa.text("'4:00 PM'")),
            sa.Column("check_out_time", sa.String(20), nullable=True, server_default=sa.text("'10:00 AM'")),
            sa.Column("late_checkout_available", sa.Boolean(), nullable=True, server_default=sa.text("true")),
            sa.Column("late_checkout_max_time", sa.String(20), nullable=True, server_default=sa.text("'2:00 PM'")),
            sa.Column("late_checkout_fee", sa.Float(), nullable=True, server_default=sa.text("50.0")),
            sa.Column("late_checkout_requires_approval", sa.Boolean(), nullable=True, server_default=sa.text("false")),
            sa.Column("early_checkin_available", sa.Boolean(), nullable=True, server_default=sa.text("true")),
            sa.Column("early_checkin_earliest", sa.String(20), nullable=True, server_default=sa.text("'1:00 PM'")),
            sa.Column("early_checkin_fee", sa.Float(), nullable=True, server_default=sa.text("0.0")),
            sa.Column("early_checkin_subject_to_availability", sa.Boolean(), nullable=True, server_default=sa.text("true")),
            sa.Column("cancellation_full_refund_days", sa.Integer(), nullable=True, server_default=sa.text("30")),
            sa.Column("cancellation_partial_refund_days", sa.Integer(), nullable=True, server_default=sa.text("14")),
            sa.Column("cancellation_partial_refund_percent", sa.Integer(), nullable=True, server_default=sa.text("50")),
            sa.Column("pets_allowed", sa.String(50), nullable=True, server_default=sa.text("'no'")),
            sa.Column("pet_fee", sa.Float(), nullable=True, server_default=sa.text("0.0")),
            sa.Column("pet_max_weight", sa.Integer(), nullable=True),
            sa.Column("pet_restricted_breeds", postgresql.JSONB(), nullable=True, server_default=sa.text("'[]'::jsonb")),
            sa.Column("pet_notes", sa.Text(), nullable=True),
            sa.Column("pool_heat_available", sa.Boolean(), nullable=True, server_default=sa.text("false")),
            sa.Column("pool_heat_daily_fee", sa.Float(), nullable=True, server_default=sa.text("50.0")),
            sa.Column("pool_heat_advance_notice_hours", sa.Integer(), nullable=True, server_default=sa.text("48")),
            sa.Column("beach_chairs_included", sa.Boolean(), nullable=True, server_default=sa.text("false")),
            sa.Column("beach_chair_rental_partners", postgresql.JSONB(), nullable=True, server_default=sa.text("'[]'::jsonb")),
            sa.Column("discount_policies", postgresql.JSONB(), nullable=True, server_default=sa.text("'{}'::jsonb")),
            sa.Column("additional_policies", postgresql.JSONB(), nullable=True, server_default=sa.text("'{}'::jsonb")),
            sa.Column("support_phone", sa.String(50), nullable=True),
            sa.Column("support_email", sa.String(255), nullable=True),
            sa.Column("emergency_phone", sa.String(50), nullable=True),
            sa.Column("upsell_rates", postgresql.JSONB(), nullable=True, server_default=sa.text("'{}'::jsonb")),
            sa.Column("upsell_rates_configured", sa.Boolean(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        table.create(bind, checkfirst=True)

    if not _index_exists(bind, "operator_policies", "idx_operator_policies_operator"):
        op.create_index("idx_operator_policies_operator", "operator_policies", ["operator_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if inspector.has_table("operator_policies"):
        existing_indexes = {idx["name"] for idx in inspector.get_indexes("operator_policies")}
        if "idx_operator_policies_operator" in existing_indexes:
            op.drop_index("idx_operator_policies_operator", table_name="operator_policies")
        op.drop_table("operator_policies")
