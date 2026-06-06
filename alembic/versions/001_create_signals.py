"""
Alembic Migration: Create Signal Intelligence Tables

Revision ID: 001_create_signals
Create Date: 2026-01-26

This migration creates the complete signal storage infrastructure:
- signals: Core immutable signal store
- signal_quarantine: Failed validation holding
- scrape_jobs: Job tracking
- signal_bundles: Pre-computed bundles
- Views and indexes for performance
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Revision identifiers
revision = '001_create_signals'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # ==========================================================================
    # ENUMS
    # ==========================================================================
    
    signal_type_enum = postgresql.ENUM(
        'supply_density', 'bedroom_distribution', 'property_type_mix',
        'calendar_compression', 'lead_time', 'rate_acceleration',
        'platform_dominance', 'platform_performance_bias',
        'amenity_prevalence', 'amenity_lift',
        'seasonality', 'seasonality_curve',
        'operator_delta', 'operational_stability',
        'regulatory_risk', 'str_restriction',
        'travel_flow', 'event_impact', 'weather_pattern',
        'transaction_velocity', 'housing_stock',
        'rate_position', 'rate_by_bedroom',
        name='signal_type',
        create_type=True
    )
    
    signal_source_enum = postgresql.ENUM(
        'airbnb_public', 'vrbo_public', 'booking_public',
        'census_acs', 'bts_dot', 'noaa_nws',
        'county_assessor', 'county_recorder',
        'state_tourism', 'local_cvb', 'faa_stats',
        'operator_pms', 'operator_manual',
        'derived', 'inferred', 'aggregated',
        'historical_cache',
        name='signal_source',
        create_type=True
    )
    
    confidence_level_enum = postgresql.ENUM(
        'high', 'medium', 'low', 'insufficient',
        name='confidence_level',
        create_type=True
    )
    
    job_status_enum = postgresql.ENUM(
        'pending', 'running', 'completed', 'failed', 'cancelled',
        name='job_status',
        create_type=True
    )
    
    # ==========================================================================
    # SIGNALS TABLE (Core - Append Only)
    # ==========================================================================
    
    op.create_table(
        'signals',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, 
                  server_default=sa.text('gen_random_uuid()')),
        
        # Classification
        sa.Column('signal_type', signal_type_enum, nullable=False),
        sa.Column('geo_id', sa.String(100), nullable=False, index=True),
        sa.Column('property_id', postgresql.UUID(as_uuid=True), nullable=True),
        
        # Source attribution
        sa.Column('source', signal_source_enum, nullable=False),
        sa.Column('source_detail', sa.String(255), nullable=True),
        
        # Value (JSONB for flexibility)
        sa.Column('value', postgresql.JSONB, nullable=False),
        sa.Column('unit', sa.String(50), nullable=True),
        
        # Confidence
        sa.Column('confidence', sa.Numeric(5, 4), nullable=False),
        sa.Column('confidence_low', sa.Numeric(20, 4), nullable=True),
        sa.Column('confidence_high', sa.Numeric(20, 4), nullable=True),
        sa.Column('confidence_level', confidence_level_enum, 
                  server_default='medium'),
        
        # Temporal
        sa.Column('decay_half_life_days', sa.Integer, nullable=False, 
                  server_default='30'),
        sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('valid_from', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('NOW()')),
        sa.Column('valid_to', sa.DateTime(timezone=True), nullable=True),
        
        # Metadata
        sa.Column('metadata', postgresql.JSONB, server_default='{}'),
        
        # Audit
        sa.Column('created_at', sa.DateTime(timezone=True), 
                  server_default=sa.text('NOW()')),
        sa.Column('batch_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('scrape_job_id', postgresql.UUID(as_uuid=True), nullable=True),
        
        # Constraints
        sa.CheckConstraint('confidence >= 0 AND confidence <= 1', 
                          name='valid_confidence'),
    )
    
    # Indexes for common query patterns
    op.create_index('idx_signals_geo_type', 'signals', ['geo_id', 'signal_type'])
    op.create_index('idx_signals_observed', 'signals', ['observed_at'],
                    postgresql_using='btree', postgresql_ops={'observed_at': 'DESC'})
    op.create_index('idx_signals_type_recent', 'signals', 
                    ['signal_type', 'observed_at'],
                    postgresql_ops={'observed_at': 'DESC'})
    op.create_index('idx_signals_geo_observed', 'signals',
                    ['geo_id', 'observed_at'],
                    postgresql_ops={'observed_at': 'DESC'})
    op.create_index('idx_signals_batch', 'signals', ['batch_id'])
    op.create_index('idx_signals_property', 'signals', ['property_id'],
                    postgresql_where=sa.text('property_id IS NOT NULL'))
    
    # ==========================================================================
    # SIGNAL QUARANTINE (Failed Validations)
    # ==========================================================================
    
    op.create_table(
        'signal_quarantine',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('original_signal', postgresql.JSONB, nullable=False),
        sa.Column('reason', sa.String(255), nullable=False),
        sa.Column('error_details', postgresql.JSONB, nullable=True),
        sa.Column('quarantined_at', sa.DateTime(timezone=True),
                  server_default=sa.text('NOW()')),
        sa.Column('status', sa.String(50), server_default='pending'),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('reviewed_by', sa.String(100), nullable=True),
        sa.Column('resolution', sa.String(50), nullable=True),
        sa.Column('resolution_notes', sa.Text, nullable=True),
    )
    
    op.create_index('idx_quarantine_status', 'signal_quarantine', 
                    ['status', 'quarantined_at'])
    
    # ==========================================================================
    # SCRAPE JOBS (Job Tracking)
    # ==========================================================================
    
    op.create_table(
        'scrape_jobs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('job_type', sa.String(50), nullable=False),
        sa.Column('market_id', sa.String(100), nullable=True),
        sa.Column('source', signal_source_enum, nullable=False),
        sa.Column('status', job_status_enum, server_default='pending'),
        sa.Column('priority', sa.Integer, server_default='0'),
        
        # Timing
        sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        
        # Results
        sa.Column('records_scraped', sa.Integer, server_default='0'),
        sa.Column('records_valid', sa.Integer, server_default='0'),
        sa.Column('records_quarantined', sa.Integer, server_default='0'),
        sa.Column('signals_created', sa.Integer, server_default='0'),
        
        # Error handling
        sa.Column('error_message', sa.Text, nullable=True),
        sa.Column('retry_count', sa.Integer, server_default='0'),
        sa.Column('max_retries', sa.Integer, server_default='3'),
        
        # Metadata
        sa.Column('metadata', postgresql.JSONB, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('NOW()')),
    )
    
    op.create_index('idx_scrape_jobs_status', 'scrape_jobs',
                    ['status', 'started_at'],
                    postgresql_ops={'started_at': 'DESC'})
    op.create_index('idx_scrape_jobs_market', 'scrape_jobs',
                    ['market_id', 'created_at'],
                    postgresql_ops={'created_at': 'DESC'})
    
    # ==========================================================================
    # SIGNAL BUNDLES (Pre-computed)
    # ==========================================================================
    
    op.create_table(
        'signal_bundles',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('geo_id', sa.String(100), nullable=False),
        sa.Column('property_id', postgresql.UUID(as_uuid=True), nullable=True),
        
        # Bundle content
        sa.Column('signal_ids', postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
                  nullable=False),
        sa.Column('signal_types', postgresql.ARRAY(sa.String(50)), nullable=False),
        
        # Coverage metrics
        sa.Column('coverage_score', sa.Numeric(5, 4), nullable=False),
        sa.Column('core_signals_present', sa.Integer, nullable=False),
        sa.Column('core_signals_total', sa.Integer, nullable=False),
        
        # Confidence
        sa.Column('overall_confidence', sa.Numeric(5, 4), nullable=False),
        sa.Column('confidence_level', confidence_level_enum, nullable=False),
        
        # Temporal
        sa.Column('as_of', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('NOW()')),
        
        # Computed data
        sa.Column('bundle_data', postgresql.JSONB, nullable=False),
    )
    
    op.create_index('idx_bundles_geo', 'signal_bundles', ['geo_id', 'as_of'],
                    postgresql_ops={'as_of': 'DESC'})
    op.create_index('idx_bundles_expires', 'signal_bundles', ['expires_at'])
    
    # ==========================================================================
    # MARKETS (Reference)
    # ==========================================================================
    
    op.create_table(
        'markets',
        sa.Column('id', sa.String(100), primary_key=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('latitude', sa.Numeric(10, 6), nullable=False),
        sa.Column('longitude', sa.Numeric(10, 6), nullable=False),
        sa.Column('radius_miles', sa.Numeric(6, 2), nullable=False),
        sa.Column('state_fips', sa.String(2), nullable=True),
        sa.Column('county_fips', sa.String(3), nullable=True),
        sa.Column('timezone', sa.String(50), server_default='America/Chicago'),
        sa.Column('enabled', sa.Boolean, server_default='true'),
        sa.Column('scrape_priority', sa.Integer, server_default='0'),
        sa.Column('metadata', postgresql.JSONB, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.text('NOW()')),
    )
    
    # ==========================================================================
    # VIEWS
    # ==========================================================================
    
    # Signal coverage by market
    op.execute("""
        CREATE OR REPLACE VIEW signal_coverage AS
        SELECT 
            geo_id,
            COUNT(DISTINCT signal_type) as signal_types_present,
            COUNT(*) as total_signals,
            MAX(observed_at) as latest_signal,
            AVG(confidence) as avg_confidence,
            MIN(observed_at) as oldest_signal,
            ARRAY_AGG(DISTINCT signal_type::text) as types_present
        FROM signals
        WHERE observed_at > NOW() - INTERVAL '7 days'
          AND (valid_to IS NULL OR valid_to > NOW())
        GROUP BY geo_id
    """)
    
    # Latest signal per geo/type
    op.execute("""
        CREATE MATERIALIZED VIEW latest_signals AS
        SELECT DISTINCT ON (geo_id, signal_type)
            id,
            signal_type,
            geo_id,
            property_id,
            source,
            source_detail,
            value,
            unit,
            confidence,
            confidence_low,
            confidence_high,
            confidence_level,
            decay_half_life_days,
            observed_at,
            valid_from,
            valid_to,
            metadata,
            created_at,
            batch_id
        FROM signals
        WHERE (valid_to IS NULL OR valid_to > NOW())
        ORDER BY geo_id, signal_type, observed_at DESC
    """)
    
    op.create_index('idx_latest_signals_pk', 'latest_signals',
                    ['geo_id', 'signal_type'], unique=True)
    op.create_index('idx_latest_signals_type', 'latest_signals', ['signal_type'])
    
    # Refresh function
    op.execute("""
        CREATE OR REPLACE FUNCTION refresh_latest_signals()
        RETURNS void AS $$
        BEGIN
            REFRESH MATERIALIZED VIEW CONCURRENTLY latest_signals;
        END;
        $$ LANGUAGE plpgsql
    """)
    
    # Job stats view
    op.execute("""
        CREATE OR REPLACE VIEW scrape_job_stats AS
        SELECT 
            date_trunc('day', started_at) as day,
            market_id,
            source::text,
            COUNT(*) as job_count,
            COUNT(*) FILTER (WHERE status = 'completed') as completed,
            COUNT(*) FILTER (WHERE status = 'failed') as failed,
            AVG(EXTRACT(EPOCH FROM (completed_at - started_at))) as avg_duration_seconds,
            SUM(records_valid) as total_records,
            SUM(signals_created) as total_signals
        FROM scrape_jobs
        WHERE started_at > NOW() - INTERVAL '30 days'
        GROUP BY date_trunc('day', started_at), market_id, source
        ORDER BY day DESC, market_id
    """)
    
    # ==========================================================================
    # TRIGGERS
    # ==========================================================================
    
    # Auto-update updated_at on markets
    op.execute("""
        CREATE OR REPLACE FUNCTION update_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    
    op.execute("""
        CREATE TRIGGER markets_updated_at
        BEFORE UPDATE ON markets
        FOR EACH ROW EXECUTE FUNCTION update_updated_at()
    """)
    
    # ==========================================================================
    # SEED DATA: Default Markets
    # ==========================================================================
    
    op.execute("""
        INSERT INTO markets (id, name, latitude, longitude, radius_miles, state_fips, county_fips)
        VALUES 
            ('30a', '30A Beaches', 30.2833, -86.0167, 15, '12', '131'),
            ('destin', 'Destin', 30.3935, -86.4958, 10, '12', '091'),
            ('panama_city_beach', 'Panama City Beach', 30.1766, -85.8055, 12, '12', '005'),
            ('gulf_shores', 'Gulf Shores', 30.2460, -87.7008, 12, '01', '003'),
            ('orange_beach', 'Orange Beach', 30.2944, -87.5731, 8, '01', '003')
        ON CONFLICT (id) DO NOTHING
    """)


def downgrade():
    # Drop views
    op.execute("DROP MATERIALIZED VIEW IF EXISTS latest_signals")
    op.execute("DROP VIEW IF EXISTS signal_coverage")
    op.execute("DROP VIEW IF EXISTS scrape_job_stats")
    
    # Drop triggers
    op.execute("DROP TRIGGER IF EXISTS markets_updated_at ON markets")
    op.execute("DROP FUNCTION IF EXISTS update_updated_at()")
    op.execute("DROP FUNCTION IF EXISTS refresh_latest_signals()")
    
    # Drop tables
    op.drop_table('signal_bundles')
    op.drop_table('scrape_jobs')
    op.drop_table('signal_quarantine')
    op.drop_table('signals')
    op.drop_table('markets')
    
    # Drop enums
    op.execute("DROP TYPE IF EXISTS job_status")
    op.execute("DROP TYPE IF EXISTS confidence_level")
    op.execute("DROP TYPE IF EXISTS signal_source")
    op.execute("DROP TYPE IF EXISTS signal_type")
