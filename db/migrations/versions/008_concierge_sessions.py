"""
Add concierge guest session and journey tables.

Historical corrections:
- `property_id` references `properties.id`, which is the real key used by
  the canonical properties table
- production stores the guest/session identifier fields as `text`, not
  length-limited `varchar`, which is safer for long OTA/provider values
- `property_context` is non-null in production with a JSONB default, so
  fresh builds should match that contract

Revision ID: 008_concierge_sessions
Revises: 007_concierge_maintenance_events
Create Date: 2026-02-24
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = "008_concierge_sessions"
down_revision = "aebd7d1703e3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Guest Sessions
    op.create_table(
        "concierge_guest_sessions",
        sa.Column("session_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("token", sa.Text(), unique=True, nullable=False, index=True),
        sa.Column("property_id", postgresql.UUID(as_uuid=True), nullable=True, index=True),
        sa.Column("property_code", sa.Text(), nullable=False, index=True),
        sa.Column("property_name", sa.Text(), nullable=False),
        sa.Column("guest_name", sa.Text(), nullable=False),
        sa.Column("guest_phone", sa.Text(), nullable=True),
        sa.Column("guest_email", sa.Text(), nullable=True),
        sa.Column("num_guests", sa.Integer(), default=1),
        sa.Column("check_in", sa.Date(), nullable=False),
        sa.Column("check_out", sa.Date(), nullable=False),
        sa.Column("status", sa.Text(), default="active", nullable=False),
        sa.Column("phase", sa.Text(), default="pre_arrival", nullable=False),
        sa.Column("conversation_count", sa.Integer(), default=0),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("property_context", postgresql.JSONB(), default={}, server_default="{}", nullable=False),
        sa.Column("feedback_rating", sa.Integer(), nullable=True),
        sa.Column("feedback_text", sa.Text(), nullable=True),
        sa.Column("feedback_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        # Historical correction: the canonical properties table created in
        # 003_create_properties uses `properties.id` as its primary key.
        # The original reference to `properties.property_id` made fresh-db
        # round-trips fail even though later production environments evolved
        # past it. Keep the intended relationship, but point at the real key.
        sa.ForeignKeyConstraint(["property_id"], ["properties.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_concierge_session_tenant_status", "concierge_guest_sessions", ["tenant_id", "status"])
    op.create_index("ix_concierge_session_tenant_property", "concierge_guest_sessions", ["tenant_id", "property_code"])
    op.create_index("ix_concierge_session_checkin", "concierge_guest_sessions", ["check_in"])
    op.create_index("ix_concierge_session_checkout", "concierge_guest_sessions", ["check_out"])
    
    # Guest Journeys
    op.create_table(
        "concierge_guest_journeys",
        sa.Column("journey_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), unique=True, nullable=False),
        sa.Column("welcome_sent", sa.Boolean(), default=False),
        sa.Column("welcome_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("extend_offer_sent", sa.Boolean(), default=False),
        sa.Column("extend_offer_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("extend_offer_response", sa.String(20), nullable=True),
        sa.Column("pool_heat_offered", sa.Boolean(), default=False),
        sa.Column("pool_heat_accepted", sa.Boolean(), default=False),
        sa.Column("checkin_reminder_sent", sa.Boolean(), default=False),
        sa.Column("checkin_reminder_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("checkout_reminder_sent", sa.Boolean(), default=False),
        sa.Column("checkout_reminder_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["concierge_guest_sessions.session_id"], ondelete="CASCADE"),
    )
    op.create_index("ix_concierge_journey_tenant", "concierge_guest_journeys", ["tenant_id"])
    
    # Journey Activities
    op.create_table(
        "concierge_journey_activities",
        sa.Column("activity_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("journey_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("activity_type", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), default="not_discussed", nullable=False),
        sa.Column("discussed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["journey_id"], ["concierge_guest_journeys.journey_id"], ondelete="CASCADE"),
    )
    op.create_index("ix_concierge_activity_journey_type", "concierge_journey_activities", ["journey_id", "activity_type"])
    
    # Messages
    op.create_table(
        "concierge_messages",
        sa.Column("message_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("direction", sa.String(10), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_type", sa.String(20), default="text"),
        sa.Column("detected_intent", sa.String(100), nullable=True),
        sa.Column("was_quick_answer", sa.Boolean(), default=False),
        sa.Column("response_time_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["concierge_guest_sessions.session_id"], ondelete="CASCADE"),
    )
    op.create_index("ix_concierge_message_session_created", "concierge_messages", ["session_id", "created_at"])
    
    # Notifications
    op.create_table(
        "concierge_notifications",
        sa.Column("notification_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("notification_type", sa.String(50), nullable=False),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column("recipient", sa.String(255), nullable=False),
        sa.Column("subject", sa.String(255), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), default="pending", nullable=False),
        sa.Column("external_id", sa.String(255), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["concierge_guest_sessions.session_id"], ondelete="CASCADE"),
    )
    op.create_index("ix_concierge_notification_session_type", "concierge_notifications", ["session_id", "notification_type"])
    op.create_index("ix_concierge_notification_status", "concierge_notifications", ["status"])


def downgrade() -> None:
    op.drop_table("concierge_notifications")
    op.drop_table("concierge_messages")
    op.drop_table("concierge_journey_activities")
    op.drop_table("concierge_guest_journeys")
    op.drop_table("concierge_guest_sessions")
