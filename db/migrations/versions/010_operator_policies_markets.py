"""
Migration: Operator Policies, Integrations, and Markets

Creates tables for:
- operator_policies: Operator-specific policies for concierge
- operator_integrations: PMS and data integration config
- operator_onboarding: Onboarding progress tracking

Historical correction:
- the original version of this migration also created `markets`,
  `market_events`, and `market_alerts`
- the authoritative market schema later settled in
  `017_market_events_registry.py`, which defines `market_registry`
  and the canonical `market_events` contract used in production
- keeping the deprecated market tables here causes fresh-db
  round-trips to fail before the chain reaches the authoritative
  market migration
- this migration now owns only the operator-scoped tables

Run with:
    alembic upgrade head

Or manually:
    python db/migrations/versions/010_operator_policies_markets.py
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# Revision identifiers
revision = '010_operator_policies_markets'
down_revision = '009_knowledge_embeddings'
branch_labels = None
depends_on = None


def upgrade():
    """Create operator policy tables."""
    
    # Operator Policies
    op.create_table(
        'operator_policies',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, 
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('operator_id', sa.String(100), nullable=False, unique=True),
        
        # Check-in/out
        sa.Column('check_in_time', sa.String(20), default='4:00 PM'),
        sa.Column('check_out_time', sa.String(20), default='10:00 AM'),
        
        # Late checkout
        sa.Column('late_checkout_available', sa.Boolean, default=True),
        sa.Column('late_checkout_max_time', sa.String(20), default='2:00 PM'),
        sa.Column('late_checkout_fee', sa.Float, default=50.0),
        sa.Column('late_checkout_requires_approval', sa.Boolean, default=False),
        
        # Early check-in
        sa.Column('early_checkin_available', sa.Boolean, default=True),
        sa.Column('early_checkin_earliest', sa.String(20), default='1:00 PM'),
        sa.Column('early_checkin_fee', sa.Float, default=0.0),
        sa.Column('early_checkin_subject_to_availability', sa.Boolean, default=True),
        
        # Cancellation
        sa.Column('cancellation_full_refund_days', sa.Integer, default=30),
        sa.Column('cancellation_partial_refund_days', sa.Integer, default=14),
        sa.Column('cancellation_partial_refund_percent', sa.Integer, default=50),
        
        # Pets
        sa.Column('pets_allowed', sa.String(50), default='no'),
        sa.Column('pet_fee', sa.Float, default=0.0),
        sa.Column('pet_max_weight', sa.Integer, nullable=True),
        sa.Column('pet_restricted_breeds', postgresql.JSONB, server_default='[]'),
        sa.Column('pet_notes', sa.Text, nullable=True),
        
        # Pool heat
        sa.Column('pool_heat_available', sa.Boolean, default=False),
        sa.Column('pool_heat_daily_fee', sa.Float, default=50.0),
        sa.Column('pool_heat_advance_notice_hours', sa.Integer, default=48),
        
        # Beach chairs
        sa.Column('beach_chairs_included', sa.Boolean, default=False),
        sa.Column('beach_chair_rental_partners', postgresql.JSONB, server_default='[]'),
        
        # Flexible policies
        sa.Column('discount_policies', postgresql.JSONB, server_default='{}'),
        sa.Column('additional_policies', postgresql.JSONB, server_default='{}'),
        
        # Support
        sa.Column('support_phone', sa.String(50), nullable=True),
        sa.Column('support_email', sa.String(255), nullable=True),
        sa.Column('emergency_phone', sa.String(50), nullable=True),
        
        # Timestamps
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('idx_operator_policies_operator', 'operator_policies', ['operator_id'])
    
    # Operator Integrations
    op.create_table(
        'operator_integrations',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('operator_id', sa.String(100), nullable=False),
        
        # Integration type
        sa.Column('integration_type', sa.String(50), nullable=False),
        
        # PMS
        sa.Column('pms_provider', sa.String(50), nullable=True),
        sa.Column('pms_api_base_url', sa.String(500), nullable=True),
        sa.Column('pms_credentials_vault_key', sa.String(255), nullable=True),
        
        # Scraper
        sa.Column('scraper_target_url', sa.String(500), nullable=True),
        sa.Column('scraper_config', postgresql.JSONB, server_default='{}'),
        
        # Sync
        sa.Column('sync_enabled', sa.Boolean, default=True),
        sa.Column('sync_frequency_minutes', sa.Integer, default=60),
        sa.Column('last_sync_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_sync_status', sa.String(50), nullable=True),
        sa.Column('last_sync_error', sa.Text, nullable=True),
        sa.Column('last_sync_stats', postgresql.JSONB, server_default='{}'),
        
        # Timestamps
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('idx_operator_integrations_operator', 'operator_integrations', ['operator_id'])
    
    # Operator Onboarding
    op.create_table(
        'operator_onboarding',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('operator_id', sa.String(100), nullable=False, unique=True),
        
        # Status
        sa.Column('status', sa.String(50), default='pending'),
        sa.Column('completed_steps', postgresql.JSONB, server_default='[]'),
        sa.Column('current_step', sa.String(50), nullable=True),
        sa.Column('conversation_state', postgresql.JSONB, server_default='{}'),
        
        # Timestamps
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_activity_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('agent_session_id', sa.String(100), nullable=True),
        
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('idx_operator_onboarding_operator', 'operator_onboarding', ['operator_id'])
    
def downgrade():
    """Drop operator policy tables."""
    op.drop_table('operator_onboarding')
    op.drop_table('operator_integrations')
    op.drop_table('operator_policies')


# Allow running as standalone script
if __name__ == "__main__":
    import os
    import psycopg2
    
    DATABASE_URL = os.getenv(
        "DATABASE_URL",
        "postgresql://rental:rental@localhost:5433/rental_revenue"
    )
    
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    cur = conn.cursor()
    
    print("Running migration: 010_operator_policies_markets")
    
    try:
        # Create tables manually
        cur.execute("""
            CREATE TABLE IF NOT EXISTS operator_policies (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                operator_id VARCHAR(100) NOT NULL UNIQUE,
                check_in_time VARCHAR(20) DEFAULT '4:00 PM',
                check_out_time VARCHAR(20) DEFAULT '10:00 AM',
                late_checkout_available BOOLEAN DEFAULT TRUE,
                late_checkout_max_time VARCHAR(20) DEFAULT '2:00 PM',
                late_checkout_fee FLOAT DEFAULT 50.0,
                late_checkout_requires_approval BOOLEAN DEFAULT FALSE,
                early_checkin_available BOOLEAN DEFAULT TRUE,
                early_checkin_earliest VARCHAR(20) DEFAULT '1:00 PM',
                early_checkin_fee FLOAT DEFAULT 0.0,
                early_checkin_subject_to_availability BOOLEAN DEFAULT TRUE,
                cancellation_full_refund_days INTEGER DEFAULT 30,
                cancellation_partial_refund_days INTEGER DEFAULT 14,
                cancellation_partial_refund_percent INTEGER DEFAULT 50,
                pets_allowed VARCHAR(50) DEFAULT 'no',
                pet_fee FLOAT DEFAULT 0.0,
                pet_max_weight INTEGER,
                pet_restricted_breeds JSONB DEFAULT '[]',
                pet_notes TEXT,
                pool_heat_available BOOLEAN DEFAULT FALSE,
                pool_heat_daily_fee FLOAT DEFAULT 50.0,
                pool_heat_advance_notice_hours INTEGER DEFAULT 48,
                beach_chairs_included BOOLEAN DEFAULT FALSE,
                beach_chair_rental_partners JSONB DEFAULT '[]',
                discount_policies JSONB DEFAULT '{}',
                additional_policies JSONB DEFAULT '{}',
                support_phone VARCHAR(50),
                support_email VARCHAR(255),
                emergency_phone VARCHAR(50),
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            );
        """)
        print("✓ operator_policies table created")
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS operator_integrations (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                operator_id VARCHAR(100) NOT NULL,
                integration_type VARCHAR(50) NOT NULL,
                pms_provider VARCHAR(50),
                pms_api_base_url VARCHAR(500),
                pms_credentials_vault_key VARCHAR(255),
                scraper_target_url VARCHAR(500),
                scraper_config JSONB DEFAULT '{}',
                sync_enabled BOOLEAN DEFAULT TRUE,
                sync_frequency_minutes INTEGER DEFAULT 60,
                last_sync_at TIMESTAMPTZ,
                last_sync_status VARCHAR(50),
                last_sync_error TEXT,
                last_sync_stats JSONB DEFAULT '{}',
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            );
        """)
        print("✓ operator_integrations table created")
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS operator_onboarding (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                operator_id VARCHAR(100) NOT NULL UNIQUE,
                status VARCHAR(50) DEFAULT 'pending',
                completed_steps JSONB DEFAULT '[]',
                current_step VARCHAR(50),
                conversation_state JSONB DEFAULT '{}',
                started_at TIMESTAMPTZ,
                completed_at TIMESTAMPTZ,
                last_activity_at TIMESTAMPTZ DEFAULT NOW(),
                agent_session_id VARCHAR(100),
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            );
        """)
        print("✓ operator_onboarding table created")
        
        # Create indexes
        cur.execute("CREATE INDEX IF NOT EXISTS idx_operator_policies_operator ON operator_policies(operator_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_operator_integrations_operator ON operator_integrations(operator_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_operator_onboarding_operator ON operator_onboarding(operator_id);")
        print("✓ Indexes created")
        
        print("\n✓ Migration complete!")
        
    except Exception as e:
        print(f"✗ Error: {e}")
        raise
    finally:
        cur.close()
        conn.close()
