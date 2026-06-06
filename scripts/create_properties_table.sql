-- create_properties_table.sql
-- Run this in Supabase SQL editor to create the properties table
-- before running load_properties_from_xlsx.py

-- Enum types
DO $$ BEGIN
    CREATE TYPE property_type AS ENUM (
        'house', 'condo', 'townhouse', 'villa', 'cottage',
        'cabin', 'apartment', 'duplex', 'other'
    );
EXCEPTION WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE community_type AS ENUM (
        'watercolor', 'rosemary_beach', 'alys_beach', 'seaside',
        'grayton_beach', 'blue_mountain', 'seagrove', 'watersound',
        'seacrest', 'inlet_beach', 'other'
    );
EXCEPTION WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE lock_type AS ENUM (
        'smart', 'keypad', 'lockbox', 'key', 'other'
    );
EXCEPTION WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE data_source AS ENUM (
        'manual', 'pms', 'import', 'guest_feedback', 'inspection', 'owner'
    );
EXCEPTION WHEN duplicate_object THEN null;
END $$;

-- Properties table
CREATE TABLE IF NOT EXISTS properties (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL,
    property_code       VARCHAR(50) NOT NULL,
    external_id         VARCHAR(255),

    -- Address
    address_street      VARCHAR(500) NOT NULL,
    address_city        VARCHAR(100) NOT NULL DEFAULT 'Santa Rosa Beach',
    address_state       VARCHAR(2) NOT NULL DEFAULT 'FL',
    address_zip         VARCHAR(10) NOT NULL DEFAULT '32459',
    community           community_type,
    latitude            NUMERIC(10, 7),
    longitude           NUMERIC(10, 7),

    -- Physical
    bedrooms            INTEGER NOT NULL DEFAULT 0,
    bathrooms           NUMERIC(3, 1) NOT NULL DEFAULT 0,
    sleeps              INTEGER,
    square_feet         INTEGER,
    floors              INTEGER,
    property_type       property_type NOT NULL DEFAULT 'house',
    year_built          INTEGER,
    beds_config         JSONB,

    -- WiFi
    wifi_network        VARCHAR(100),
    wifi_password       VARCHAR(100),
    wifi_router_location VARCHAR(255),

    -- Access
    check_in_time       VARCHAR(20) NOT NULL DEFAULT '4:00 PM',
    check_out_time      VARCHAR(20) NOT NULL DEFAULT '10:00 AM',
    lock_type           lock_type NOT NULL DEFAULT 'keypad',
    property_guide_url  VARCHAR(1000),
    check_in_instructions TEXT,
    check_out_instructions TEXT,

    -- Parking
    parking_spaces      INTEGER,
    parking_instructions TEXT,

    -- Contacts
    rep_name            VARCHAR(100),
    housekeeper_name    VARCHAR(100),
    housekeeper_phone   VARCHAR(20),
    emergency_contact   VARCHAR(255),

    -- Systems
    breaker_box_location VARCHAR(255),
    thermostat_type     VARCHAR(50),
    hvac_instructions   TEXT,

    -- Amenities
    has_pool            BOOLEAN NOT NULL DEFAULT false,
    pool_heated         BOOLEAN NOT NULL DEFAULT false,
    has_hot_tub         BOOLEAN NOT NULL DEFAULT false,
    has_grill           BOOLEAN NOT NULL DEFAULT false,
    has_bikes           BOOLEAN NOT NULL DEFAULT false,
    bike_count          INTEGER,
    has_beach_gear      BOOLEAN NOT NULL DEFAULT false,
    has_washer_dryer    BOOLEAN NOT NULL DEFAULT true,
    amenities           JSONB NOT NULL DEFAULT '{}',

    -- Rules
    pets_allowed        BOOLEAN NOT NULL DEFAULT false,
    smoking_allowed     BOOLEAN NOT NULL DEFAULT false,
    events_allowed      BOOLEAN NOT NULL DEFAULT false,
    max_occupancy       INTEGER,
    quiet_hours_start   VARCHAR(20) DEFAULT '10:00 PM',
    quiet_hours_end     VARCHAR(20) DEFAULT '8:00 AM',
    rules               JSONB NOT NULL DEFAULT '{}',

    -- Notes
    general_notes       TEXT,
    known_issues        JSONB NOT NULL DEFAULT '[]',
    warranty_items      JSONB NOT NULL DEFAULT '[]',
    internal_notes      TEXT,

    -- Data quality
    data_source         data_source NOT NULL DEFAULT 'import',
    confidence_score    NUMERIC(3, 2) NOT NULL DEFAULT 0.80,
    missing_fields      TEXT[] NOT NULL DEFAULT '{}',
    last_verified_at    TIMESTAMPTZ,
    verified_by         VARCHAR(100),

    -- Timestamps
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_properties_tenant_code UNIQUE (tenant_id, property_code)
);

-- Indexes
CREATE INDEX IF NOT EXISTS ix_properties_tenant_id  ON properties (tenant_id);
CREATE INDEX IF NOT EXISTS ix_properties_community  ON properties (community);
CREATE INDEX IF NOT EXISTS ix_properties_bedrooms   ON properties (bedrooms);

-- updated_at trigger
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

DROP TRIGGER IF EXISTS update_properties_updated_at ON properties;
CREATE TRIGGER update_properties_updated_at
    BEFORE UPDATE ON properties
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Link concierge_knowledge to properties
ALTER TABLE concierge_knowledge
    ADD COLUMN IF NOT EXISTS canonical_property_id UUID REFERENCES properties(id);

CREATE INDEX IF NOT EXISTS ix_concierge_knowledge_canonical_property
    ON concierge_knowledge (canonical_property_id);
