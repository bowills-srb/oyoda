"""
017_market_events_registry

Creates:
  - market_registry    — registry of all geographic markets the platform serves
  - market_events      — local events scraped per market
  - operator_policies.market_id column (if not already present)

Revision ID: 017
Revises: 016_experiment_tables
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade():
    # ── market_registry ───────────────────────────────────────────────────────
    op.create_table(
        "market_registry",
        sa.Column("market_id",               sa.String(100),  nullable=False),
        sa.Column("market_name",             sa.String(200),  nullable=False),
        sa.Column("state_code",              sa.String(2),    nullable=False),
        sa.Column("center_lat",              sa.Float(),      nullable=False),
        sa.Column("center_lng",              sa.Float(),      nullable=False),
        sa.Column("radius_miles",            sa.Float(),      nullable=False, server_default="15.0"),
        sa.Column("scrape_enabled",          sa.Boolean(),    nullable=False, server_default="true"),
        sa.Column("scrape_interval_hours",   sa.Integer(),    nullable=False, server_default="24"),
        sa.Column("last_scraped_at",         sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_scrape_status",      sa.String(50),  nullable=True),
        sa.Column("last_scrape_event_count", sa.Integer(),    nullable=False, server_default="0"),
        sa.Column("sources_config",          postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("operator_ids",            postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("timezone",                sa.String(50),   nullable=False, server_default="'America/Chicago'"),
        sa.Column("notes",                   sa.Text(),       nullable=True),
        sa.Column("created_at",              sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at",              sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("market_id"),
    )

    # ── market_events ─────────────────────────────────────────────────────────
    op.create_table(
        "market_events",
        sa.Column("event_id",              postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("market_id",             sa.String(100),  nullable=False),
        sa.Column("market_name",           sa.String(200),  nullable=False),
        sa.Column("title",                 sa.String(500),  nullable=False),
        sa.Column("description",           sa.Text(),       nullable=True),
        sa.Column("category",              sa.String(100),  nullable=True),
        sa.Column("tags",                  postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("start_date",            sa.Date(),       nullable=False),
        sa.Column("end_date",              sa.Date(),       nullable=False),
        sa.Column("start_time",            sa.String(20),   nullable=True),
        sa.Column("end_time",              sa.String(20),   nullable=True),
        sa.Column("is_multi_day",          sa.Boolean(),    nullable=False, server_default="false"),
        sa.Column("is_recurring",          sa.Boolean(),    nullable=False, server_default="false"),
        sa.Column("recurrence_rule",       sa.String(200),  nullable=True),
        sa.Column("venue_name",            sa.String(300),  nullable=True),
        sa.Column("venue_address",         sa.String(500),  nullable=True),
        sa.Column("venue_lat",             sa.Float(),      nullable=True),
        sa.Column("venue_lng",             sa.Float(),      nullable=True),
        sa.Column("estimated_attendance",  sa.Integer(),    nullable=True),
        sa.Column("demand_radius_miles",   sa.Float(),      nullable=False, server_default="15.0"),
        sa.Column("demand_impact_score",   sa.Float(),      nullable=True),
        sa.Column("source",                sa.String(50),   nullable=False),
        sa.Column("source_id",             sa.String(200),  nullable=True),
        sa.Column("source_url",            sa.String(1000), nullable=True),
        sa.Column("ticket_url",            sa.String(1000), nullable=True),
        sa.Column("ticket_price_range",    sa.String(100),  nullable=True),
        sa.Column("is_free",               sa.Boolean(),    nullable=False, server_default="false"),
        sa.Column("rag_indexed_at",        sa.DateTime(timezone=True), nullable=True),
        sa.Column("rag_knowledge_id",      sa.String(100),  nullable=True),
        sa.Column("is_active",             sa.Boolean(),    nullable=False, server_default="true"),
        sa.Column("is_verified",           sa.Boolean(),    nullable=False, server_default="false"),
        sa.Column("scraped_at",            sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at",            sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at",            sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("event_id"),
    )

    # Dedup index: one record per (market, source, source_id)
    op.create_index(
        "ix_market_events_source_dedup",
        "market_events",
        ["market_id", "source", "source_id"],
        unique=True,
        postgresql_where=sa.text("source_id IS NOT NULL"),
    )
    # Concierge date-range query
    op.create_index(
        "ix_market_events_market_dates",
        "market_events",
        ["market_id", "start_date", "end_date"],
    )
    # Upcoming events
    op.create_index(
        "ix_market_events_upcoming",
        "market_events",
        ["start_date", "is_active"],
    )
    # RAG pending indexing
    op.create_index(
        "ix_market_events_rag_pending",
        "market_events",
        ["rag_indexed_at", "is_active"],
    )
    # market_id foreign key helper
    op.create_index(
        "ix_market_events_market_id",
        "market_events",
        ["market_id"],
    )

    # ── operator_policies: add market_id column ───────────────────────────────
    op.add_column(
        "operator_policies",
        sa.Column("market_id", sa.String(100), nullable=True),
    )
    op.create_index(
        "ix_operator_policies_market_id",
        "operator_policies",
        ["market_id"],
    )

    # ── Seed known markets ────────────────────────────────────────────────────
    op.execute("""
        INSERT INTO market_registry
            (market_id, market_name, state_code, center_lat, center_lng,
             radius_miles, timezone, sources_config)
        VALUES
            ('30a_fl',              '30A Beaches, FL',                  'FL',  30.2833, -86.0167, 15, 'America/Chicago',
             jsonb_build_object(
                 'eventbrite', jsonb_build_object('enabled', true),
                 'visitwaltoncounty', jsonb_build_object('enabled', true),
                 '30a_com', jsonb_build_object('enabled', true)
             )),
            ('destin_fl',           'Destin, FL',                       'FL',  30.3935, -86.4958, 12, 'America/Chicago',
             jsonb_build_object(
                 'eventbrite', jsonb_build_object('enabled', true),
                 'visitflorida', jsonb_build_object('enabled', true),
                 'visitdestin', jsonb_build_object('enabled', true)
             )),
            ('gulf_shores_al',      'Gulf Shores / Orange Beach, AL',   'AL',  30.2460, -87.7008, 15, 'America/Chicago',
             jsonb_build_object(
                 'eventbrite', jsonb_build_object('enabled', true),
                 'gulfshores_com', jsonb_build_object('enabled', true)
             )),
            ('pensacola_fl',        'Pensacola Beach, FL',              'FL',  30.3324, -87.1384, 15, 'America/Chicago',
             jsonb_build_object(
                 'eventbrite', jsonb_build_object('enabled', true),
                 'visitpensacola', jsonb_build_object('enabled', true)
             )),
            ('panama_city_beach_fl','Panama City Beach, FL',            'FL',  30.1766, -85.8055, 15, 'America/Chicago',
             jsonb_build_object(
                 'eventbrite', jsonb_build_object('enabled', true),
                 'visitpcb', jsonb_build_object('enabled', true)
             )),
            ('myrtle_beach_sc',     'Myrtle Beach, SC',                 'SC',  33.6891, -78.8867, 20, 'America/New_York',
             jsonb_build_object(
                 'eventbrite', jsonb_build_object('enabled', true),
                 'visitmyrtlebeach', jsonb_build_object('enabled', true)
             )),
            ('outer_banks_nc',      'Outer Banks, NC',                  'NC',  35.9135, -75.6765, 25, 'America/New_York',
             jsonb_build_object(
                 'eventbrite', jsonb_build_object('enabled', true),
                 'outerbanks', jsonb_build_object('enabled', true)
             ))
        ON CONFLICT (market_id) DO NOTHING;
    """)


def downgrade():
    op.drop_index("ix_operator_policies_market_id", table_name="operator_policies")
    op.drop_column("operator_policies", "market_id")

    op.drop_index("ix_market_events_market_id",    table_name="market_events")
    op.drop_index("ix_market_events_rag_pending",  table_name="market_events")
    op.drop_index("ix_market_events_upcoming",     table_name="market_events")
    op.drop_index("ix_market_events_market_dates", table_name="market_events")
    op.drop_index("ix_market_events_source_dedup", table_name="market_events")
    op.drop_table("market_events")
    op.drop_table("market_registry")
