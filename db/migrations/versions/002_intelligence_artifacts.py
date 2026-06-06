"""
002_intelligence_artifacts

Create tables for intelligence artifact persistence:
- evidence_records (append-only)
- operational_snapshots
- pitch_books
- concierge_decision_logs
- market_evidence

Revision ID: 002_intelligence_artifacts
Revises: 001_signals_table
Create Date: 2026-01-28
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = '002_intelligence_artifacts'
down_revision = '001_signals_table'
branch_labels = None
depends_on = None


def upgrade():
    # Evidence Records (append-only)
    op.create_table(
        'evidence_records',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('entity_type', sa.String(50), nullable=False),
        sa.Column('entity_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('evidence_type', sa.String(50), nullable=False),
        sa.Column('source', sa.String(100), nullable=False),
        sa.Column('source_id', sa.String(255), nullable=True),
        sa.Column('field_name', sa.String(100), nullable=True),
        sa.Column('value', postgresql.JSONB, nullable=True),
        sa.Column('raw_data', postgresql.JSONB, nullable=True),
        sa.Column('confidence', sa.Float, default=0.5),
        sa.Column('observed_at', sa.DateTime, nullable=True),
        sa.Column('expires_at', sa.DateTime, nullable=True),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
    )
    
    op.create_index('ix_evidence_entity', 'evidence_records', ['entity_type', 'entity_id'])
    op.create_index('ix_evidence_type', 'evidence_records', ['evidence_type'])
    op.create_index('ix_evidence_source', 'evidence_records', ['source'])
    op.create_index('ix_evidence_observed', 'evidence_records', ['observed_at'])
    
    # Operational Snapshots
    op.create_table(
        'operational_snapshots',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('property_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('next_checkin', sa.DateTime, nullable=True),
        sa.Column('next_checkout', sa.DateTime, nullable=True),
        sa.Column('current_reservation_id', sa.String(100), nullable=True),
        sa.Column('turnover_status', sa.String(20), default='normal'),
        sa.Column('turnover_buffer_hours', sa.Float, default=5.0),
        sa.Column('cleaning_status', sa.String(20), default='not_scheduled'),
        sa.Column('cleaning_scheduled_at', sa.DateTime, nullable=True),
        sa.Column('staff_capacity', sa.String(20), default='normal'),
        sa.Column('has_critical_issues', sa.Boolean, default=False),
        sa.Column('known_issues', postgresql.JSONB, default=list),
        sa.Column('snapshot_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
    )
    
    op.create_index('ix_ops_snapshot_property', 'operational_snapshots', ['property_id'])
    op.create_index('ix_ops_snapshot_time', 'operational_snapshots', ['snapshot_at'])
    
    # Pitch Books
    op.create_table(
        'pitch_books',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('property_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('audience', sa.String(20), default='homeowner'),
        sa.Column('content', postgresql.JSONB, nullable=False),
        sa.Column('annual_revenue_low', sa.Float, nullable=True),
        sa.Column('annual_revenue_expected', sa.Float, nullable=True),
        sa.Column('annual_revenue_high', sa.Float, nullable=True),
        sa.Column('market_id', sa.String(50), nullable=True),
        sa.Column('market_snapshot', postgresql.JSONB, nullable=True),
        sa.Column('pdf_url', sa.String(500), nullable=True),
        sa.Column('html_content', sa.Text, nullable=True),
        sa.Column('generated_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('expires_at', sa.DateTime, nullable=True),
    )
    
    op.create_index('ix_pitchbook_property', 'pitch_books', ['property_id'])
    op.create_index('ix_pitchbook_generated', 'pitch_books', ['generated_at'])
    
    # Concierge Decision Logs
    op.create_table(
        'concierge_decision_logs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('property_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('guest_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('reservation_id', sa.String(100), nullable=True),
        sa.Column('decision_type', sa.String(50), nullable=False),
        sa.Column('request_intent', sa.String(50), nullable=True),
        sa.Column('request_text', sa.Text, nullable=True),
        sa.Column('decision_mode', sa.String(20), nullable=False),
        sa.Column('approved', sa.Boolean, nullable=True),
        sa.Column('response_text', sa.Text, nullable=True),
        sa.Column('required_escalation', sa.Boolean, default=False),
        sa.Column('escalation_reason', sa.String(255), nullable=True),
        sa.Column('guest_context', postgresql.JSONB, nullable=True),
        sa.Column('ops_state_snapshot', postgresql.JSONB, nullable=True),
        sa.Column('market_context_snapshot', postgresql.JSONB, nullable=True),
        sa.Column('outcome_recorded', sa.Boolean, default=False),
        sa.Column('outcome_positive', sa.Boolean, nullable=True),
        sa.Column('outcome_notes', sa.Text, nullable=True),
        sa.Column('decided_at', sa.DateTime, server_default=sa.func.now()),
    )
    
    op.create_index('ix_decision_log_property', 'concierge_decision_logs', ['property_id'])
    op.create_index('ix_decision_log_type', 'concierge_decision_logs', ['decision_type'])
    op.create_index('ix_decision_log_time', 'concierge_decision_logs', ['decided_at'])
    
    # Market Evidence
    op.create_table(
        'market_evidence',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('market_id', sa.String(50), nullable=False),
        sa.Column('evidence_type', sa.String(50), nullable=False),
        sa.Column('data', postgresql.JSONB, nullable=False),
        sa.Column('valid_from', sa.DateTime, nullable=True),
        sa.Column('valid_until', sa.DateTime, nullable=True),
        sa.Column('source', sa.String(100), nullable=False),
        sa.Column('confidence', sa.Float, default=0.5),
        sa.Column('observed_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
    )
    
    op.create_index('ix_market_evidence_market', 'market_evidence', ['market_id'])
    op.create_index('ix_market_evidence_type', 'market_evidence', ['evidence_type'])
    op.create_index('ix_market_evidence_valid', 'market_evidence', ['valid_from', 'valid_until'])


def downgrade():
    op.drop_table('market_evidence')
    op.drop_table('concierge_decision_logs')
    op.drop_table('pitch_books')
    op.drop_table('operational_snapshots')
    op.drop_table('evidence_records')
