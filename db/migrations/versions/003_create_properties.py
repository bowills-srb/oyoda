"""Create properties table with PropertyCanonical schema.

Revision ID: 003_create_properties
Revises: 002_intelligence_artifacts
Create Date: 2025-02-14

This migration creates the core properties table that stores
the canonical truth about each rental property. This is the
foundation for the guest concierge.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY
from sqlalchemy.dialects import postgresql
from sqlalchemy import text


# revision identifiers
revision = '003_create_properties'
down_revision = '002_intelligence_artifacts'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create enum types
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE property_type AS ENUM (
                'house', 'condo', 'townhouse', 'villa', 'cottage', 
                'cabin', 'apartment', 'duplex', 'other'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE community_type AS ENUM (
                'watercolor', 'rosemary_beach', 'alys_beach', 'seaside',
                'grayton_beach', 'blue_mountain', 'seagrove', 'watersound',
                'seacrest', 'inlet_beach', 'other'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE lock_type AS ENUM (
                'smart', 'keypad', 'lockbox', 'key', 'other'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE data_source AS ENUM (
                'manual', 'pms', 'import', 'guest_feedback', 'inspection', 'owner'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)

    property_type_enum = postgresql.ENUM(
        name='property_type',
        create_type=False,
    )
    community_type_enum = postgresql.ENUM(
        name='community_type',
        create_type=False,
    )
    lock_type_enum = postgresql.ENUM(
        name='lock_type',
        create_type=False,
    )
    data_source_enum = postgresql.ENUM(
        name='data_source',
        create_type=False,
    )

    # Create properties table
    op.create_table(
        'properties',
        # Identity
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', UUID(as_uuid=True), nullable=False, index=True),
        sa.Column('property_code', sa.String(50), nullable=False),  # UNIT CODE from spreadsheet
        sa.Column('external_id', sa.String(255), nullable=True),  # PMS external ID
        
        # Address
        sa.Column('address_street', sa.String(500), nullable=False),
        sa.Column('address_city', sa.String(100), nullable=False, server_default='Santa Rosa Beach'),
        sa.Column('address_state', sa.String(2), nullable=False, server_default='FL'),
        sa.Column('address_zip', sa.String(10), nullable=False, server_default='32459'),
        sa.Column('community', community_type_enum, nullable=True),
        sa.Column('latitude', sa.Numeric(10, 7), nullable=True),
        sa.Column('longitude', sa.Numeric(10, 7), nullable=True),
        
        # Physical attributes
        sa.Column('bedrooms', sa.Integer, nullable=False, server_default='0'),
        sa.Column('bathrooms', sa.Numeric(3, 1), nullable=False, server_default='0'),
        sa.Column('sleeps', sa.Integer, nullable=True),
        sa.Column('square_feet', sa.Integer, nullable=True),
        sa.Column('floors', sa.Integer, nullable=True),
        sa.Column('property_type', property_type_enum, nullable=False, server_default='house'),
        sa.Column('year_built', sa.Integer, nullable=True),
        sa.Column('beds_config', JSONB, nullable=True),  # {"king": 2, "queen": 1, ...}
        
        # WiFi - critical for concierge
        sa.Column('wifi_network', sa.String(100), nullable=True),
        sa.Column('wifi_password', sa.String(100), nullable=True),
        sa.Column('wifi_router_location', sa.String(255), nullable=True),
        
        # Access
        sa.Column('check_in_time', sa.String(20), nullable=False, server_default='4:00 PM'),
        sa.Column('check_out_time', sa.String(20), nullable=False, server_default='10:00 AM'),
        sa.Column('lock_type', lock_type_enum, nullable=False, server_default='keypad'),
        sa.Column('property_guide_url', sa.String(1000), nullable=True),
        sa.Column('check_in_instructions', sa.Text, nullable=True),
        sa.Column('check_out_instructions', sa.Text, nullable=True),
        
        # Parking
        sa.Column('parking_spaces', sa.Integer, nullable=True),
        sa.Column('parking_instructions', sa.Text, nullable=True),
        
        # Contacts
        sa.Column('rep_name', sa.String(100), nullable=True),
        sa.Column('housekeeper_name', sa.String(100), nullable=True),
        sa.Column('housekeeper_phone', sa.String(20), nullable=True),
        sa.Column('emergency_contact', sa.String(255), nullable=True),
        
        # Systems
        sa.Column('breaker_box_location', sa.String(255), nullable=True),
        sa.Column('thermostat_type', sa.String(50), nullable=True),
        sa.Column('hvac_instructions', sa.Text, nullable=True),
        
        # Amenities (commonly asked about) - store as booleans for quick filtering
        sa.Column('has_pool', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('pool_heated', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('has_hot_tub', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('has_grill', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('has_bikes', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('bike_count', sa.Integer, nullable=True),
        sa.Column('has_beach_gear', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('has_washer_dryer', sa.Boolean, nullable=False, server_default='true'),
        
        # Extended amenities - JSONB for flexibility
        sa.Column('amenities', JSONB, nullable=False, server_default='{}'),
        # Example: {"kitchen": {"coffee_maker": "keurig", ...}, "outdoor": {...}}
        
        # Rules
        sa.Column('pets_allowed', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('smoking_allowed', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('events_allowed', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('max_occupancy', sa.Integer, nullable=True),
        sa.Column('quiet_hours_start', sa.String(20), nullable=True, server_default='10:00 PM'),
        sa.Column('quiet_hours_end', sa.String(20), nullable=True, server_default='8:00 AM'),
        sa.Column('rules', JSONB, nullable=False, server_default='{}'),
        
        # Notes & Issues
        sa.Column('general_notes', sa.Text, nullable=True),
        sa.Column('known_issues', JSONB, nullable=False, server_default='[]'),
        sa.Column('warranty_items', JSONB, nullable=False, server_default='[]'),
        sa.Column('internal_notes', sa.Text, nullable=True),  # Staff only
        
        # Data quality
        sa.Column('data_source', data_source_enum, nullable=False, server_default='import'),
        sa.Column('confidence_score', sa.Numeric(3, 2), nullable=False, server_default='0.80'),
        # Historical correction: production stores this as text[] rather than
        # varchar[] so arbitrary missing-field names are never truncated.
        sa.Column('missing_fields', ARRAY(sa.Text), nullable=False, server_default='{}'),
        sa.Column('last_verified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('verified_by', sa.String(100), nullable=True),
        
        # Timestamps
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        
        # Constraints
        sa.UniqueConstraint('tenant_id', 'property_code', name='uq_properties_tenant_code'),
    )
    
    # Create indexes
    op.create_index('ix_properties_community', 'properties', ['community'])
    op.create_index('ix_properties_bedrooms', 'properties', ['bedrooms'])
    
    # Create updated_at trigger
    op.execute("""
        CREATE OR REPLACE FUNCTION update_updated_at_column()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ language 'plpgsql';
    """)
    
    op.execute("""
        CREATE TRIGGER update_properties_updated_at
            BEFORE UPDATE ON properties
            FOR EACH ROW
            EXECUTE FUNCTION update_updated_at_column();
    """)
    
    # Add foreign key from concierge_knowledge to properties
    # First, add the column if it doesn't reference properties properly
    op.execute("""
        ALTER TABLE concierge_knowledge 
        ADD COLUMN IF NOT EXISTS canonical_property_id UUID REFERENCES properties(id);
    """)
    
    op.create_index('ix_concierge_knowledge_canonical_property', 
                    'concierge_knowledge', ['canonical_property_id'])


def downgrade() -> None:
    # Remove foreign key and column
    op.execute("ALTER TABLE concierge_knowledge DROP COLUMN IF EXISTS canonical_property_id;")
    
    # Drop trigger
    op.execute("DROP TRIGGER IF EXISTS update_properties_updated_at ON properties;")
    op.execute("DROP FUNCTION IF EXISTS update_updated_at_column();")
    
    # Drop table
    op.drop_table('properties')
    
    # Drop enum types
    op.execute("DROP TYPE IF EXISTS data_source;")
    op.execute("DROP TYPE IF EXISTS lock_type;")
    op.execute("DROP TYPE IF EXISTS community_type;")
    op.execute("DROP TYPE IF EXISTS property_type;")
