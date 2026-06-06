"""Add richer event-intelligence fields to market_events.

Revision ID: 025_event_intel_fields
Revises: 024
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "025_event_intel_fields"
down_revision = "024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("market_events", sa.Column("guest_relevance_score", sa.Float(), nullable=True))
    op.add_column("market_events", sa.Column("booking_urgency_score", sa.Float(), nullable=True))
    op.add_column("market_events", sa.Column("event_confidence_score", sa.Float(), nullable=True))
    op.add_column("market_events", sa.Column("event_class", sa.String(length=50), nullable=True))
    op.add_column("market_events", sa.Column("actionability", sa.String(length=50), nullable=True))
    op.add_column("market_events", sa.Column("source_type", sa.String(length=50), nullable=True))
    op.add_column("market_events", sa.Column("source_count", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("market_events", sa.Column("source_types", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.add_column("market_events", sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("market_events", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("market_events", sa.Column("stale_after", sa.DateTime(timezone=True), nullable=True))

    op.execute(
        """
        UPDATE market_events
        SET
            guest_relevance_score = COALESCE(guest_relevance_score, demand_impact_score, 0.35),
            booking_urgency_score = COALESCE(booking_urgency_score, CASE WHEN ticket_url IS NOT NULL THEN 0.55 ELSE 0.20 END),
            event_confidence_score = COALESCE(event_confidence_score, CASE WHEN source_id IS NOT NULL THEN 0.70 ELSE 0.50 END),
            event_class = COALESCE(
                event_class,
                CASE
                    WHEN category = 'holiday' THEN 'seasonal_anchor'
                    WHEN COALESCE(demand_impact_score, 0) >= 0.60 THEN 'demand_driver'
                    ELSE 'operational'
                END
            ),
            actionability = COALESCE(
                actionability,
                CASE
                    WHEN ticket_url IS NOT NULL THEN 'book_now'
                    WHEN COALESCE(demand_impact_score, 0) >= 0.45 THEN 'plan_ahead'
                    ELSE 'informational'
                END
            ),
            source_type = COALESCE(source_type, 'calendar'),
            source_count = COALESCE(source_count, 1),
            source_types = CASE
                WHEN source_types IS NULL OR source_types = '[]'::jsonb THEN jsonb_build_array(COALESCE(source_type, 'calendar'))
                ELSE source_types
            END,
            first_seen_at = COALESCE(first_seen_at, scraped_at, created_at),
            last_seen_at = COALESCE(last_seen_at, scraped_at, updated_at, created_at),
            stale_after = COALESCE(stale_after, (end_date::timestamp with time zone + interval '2 day'))
        """
    )

    op.alter_column("market_events", "source_count", server_default=None)


def downgrade() -> None:
    op.drop_column("market_events", "stale_after")
    op.drop_column("market_events", "last_seen_at")
    op.drop_column("market_events", "first_seen_at")
    op.drop_column("market_events", "source_types")
    op.drop_column("market_events", "source_count")
    op.drop_column("market_events", "source_type")
    op.drop_column("market_events", "actionability")
    op.drop_column("market_events", "event_class")
    op.drop_column("market_events", "event_confidence_score")
    op.drop_column("market_events", "booking_urgency_score")
    op.drop_column("market_events", "guest_relevance_score")
