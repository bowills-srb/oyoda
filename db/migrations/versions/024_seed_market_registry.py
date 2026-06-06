"""
024_seed_market_registry

Seeds market_registry with the initial set of known STR markets.
After this migration, market_registry is the source of truth.
New markets are added via operator onboarding (resolve_operator_market)
or direct DB insert — never by editing application code.

Revision ID: 024
Revises: 023_normalize_concierge_escalations
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
import json

revision = "024"
down_revision = "023_normalize_concierge_escalations"
branch_labels = None
depends_on = None

# ---------------------------------------------------------------------------
# Initial market seed data.
#
# This is a one-time bootstrap.  Once inserted, all market management happens
# in the DB (via operator onboarding geocoding or manual inserts).
# To add a new market: INSERT INTO market_registry (...) — no code change needed.
# ---------------------------------------------------------------------------

SEED_MARKETS = [
    {   # Sources: VisitSouthWalton + 30a.com are the primary scrapers.
        # Eventbrite disabled until EVENTBRITE_API_KEY is provisioned.
        "market_id":             "30a_fl",
        "market_name":           "30A Beaches, FL",
        "state_code":            "FL",
        "center_lat":            30.2833,
        "center_lng":            -86.0167,
        "radius_miles":          15.0,
        "timezone":              "America/Chicago",
        "scrape_enabled":        True,
        "scrape_interval_hours": 24,
        "sources_config": {
            "eventbrite":        {"enabled": False, "note": "requires EVENTBRITE_API_KEY"},
            "visitwaltoncounty": {"enabled": True},
            "30a_com":           {"enabled": True},
            "visitflorida":      {"enabled": True},
        },
    },
    {
        "market_id":             "destin_fl",
        "market_name":           "Destin, FL",
        "state_code":            "FL",
        "center_lat":            30.3935,
        "center_lng":            -86.4958,
        "radius_miles":          12.0,
        "timezone":              "America/Chicago",
        "scrape_enabled":        True,
        "scrape_interval_hours": 24,
        "sources_config": {
            "eventbrite":   {"enabled": False, "note": "requires EVENTBRITE_API_KEY"},
            "visitflorida": {"enabled": True},
            "visitdestin":  {"enabled": True},
        },
    },
    {
        "market_id":             "gulf_shores_al",
        "market_name":           "Gulf Shores / Orange Beach, AL",
        "state_code":            "AL",
        "center_lat":            30.2460,
        "center_lng":            -87.7008,
        "radius_miles":          15.0,
        "timezone":              "America/Chicago",
        "scrape_enabled":        True,
        "scrape_interval_hours": 24,
        "sources_config": {
            "eventbrite":     {"enabled": False, "note": "requires EVENTBRITE_API_KEY"},
            "gulfshores_com": {"enabled": True},
        },
    },
    {
        "market_id":             "pensacola_fl",
        "market_name":           "Pensacola Beach, FL",
        "state_code":            "FL",
        "center_lat":            30.3324,
        "center_lng":            -87.1384,
        "radius_miles":          15.0,
        "timezone":              "America/Chicago",
        "scrape_enabled":        True,
        "scrape_interval_hours": 24,
        "sources_config": {
            "eventbrite":     {"enabled": False, "note": "requires EVENTBRITE_API_KEY"},
            "visitpensacola": {"enabled": True},
        },
    },
    {
        "market_id":             "panama_city_beach_fl",
        "market_name":           "Panama City Beach, FL",
        "state_code":            "FL",
        "center_lat":            30.1766,
        "center_lng":            -85.8055,
        "radius_miles":          15.0,
        "timezone":              "America/Chicago",
        "scrape_enabled":        True,
        "scrape_interval_hours": 24,
        "sources_config": {
            "eventbrite": {"enabled": False, "note": "requires EVENTBRITE_API_KEY"},
            "visitpcb":   {"enabled": True},
        },
    },
    {
        "market_id":             "myrtle_beach_sc",
        "market_name":           "Myrtle Beach, SC",
        "state_code":            "SC",
        "center_lat":            33.6891,
        "center_lng":            -78.8867,
        "radius_miles":          20.0,
        "timezone":              "America/New_York",
        "scrape_enabled":        True,
        "scrape_interval_hours": 24,
        "sources_config": {
            "eventbrite":       {"enabled": False, "note": "requires EVENTBRITE_API_KEY"},
            "visitmyrtlebeach": {"enabled": True},
        },
    },
    {
        "market_id":             "outer_banks_nc",
        "market_name":           "Outer Banks, NC",
        "state_code":            "NC",
        "center_lat":            35.9135,
        "center_lng":            -75.6765,
        "radius_miles":          25.0,
        "timezone":              "America/New_York",
        "scrape_enabled":        True,
        "scrape_interval_hours": 24,
        "sources_config": {
            "eventbrite": {"enabled": False, "note": "requires EVENTBRITE_API_KEY"},
            "outerbanks": {"enabled": True},
        },
    },
]


def upgrade():
    conn = op.get_bind()
    for market in SEED_MARKETS:
        conn.execute(
            sa.text("""
                INSERT INTO market_registry (
                    market_id, market_name, state_code,
                    center_lat, center_lng, radius_miles, timezone,
                    scrape_enabled, scrape_interval_hours,
                    sources_config, operator_ids,
                    last_scrape_event_count
                ) VALUES (
                    :market_id, :market_name, :state_code,
                    :center_lat, :center_lng, :radius_miles, :timezone,
                    :scrape_enabled, :scrape_interval_hours,
                    CAST(:sources_config AS JSONB), '[]'::JSONB,
                    0
                )
                ON CONFLICT (market_id) DO NOTHING
            """),
            {
                **{k: v for k, v in market.items() if k != "sources_config"},
                "sources_config": json.dumps(market["sources_config"]),
            }
        )


def downgrade():
    conn = op.get_bind()
    market_ids = [m["market_id"] for m in SEED_MARKETS]
    conn.execute(
        sa.text("DELETE FROM market_registry WHERE market_id = ANY(:ids)"),
        {"ids": market_ids}
    )
