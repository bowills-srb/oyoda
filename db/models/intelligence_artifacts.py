"""
Database Models: Intelligence Artifacts.

Persistence for:
- Evidence records (append-only)
- Operational snapshots
- Pitch books (optional caching)
- Concierge decision logs (audit/learning)

These models persist DATA, not COMPUTED DECISIONS.
Intelligence is always recomputable from evidence.
"""

from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID, uuid4

from sqlalchemy import (
    Column, String, Float, Integer, Boolean, DateTime, Text,
    ForeignKey, Index, JSON, Enum as SQLEnum
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID, JSONB
from sqlalchemy.orm import relationship

from db.models.base import Base


# =============================================================================
# EVIDENCE RECORDS (Append-Only)
# =============================================================================

class EvidenceRecordModel(Base):
    """
    Append-only evidence storage.
    
    This is the raw ingestion target for:
    - Scraped data (county, events, STR density)
    - Operator uploads (PMS exports, manuals)
    - API integrations
    
    Evidence is NEVER updated, only appended.
    """
    __tablename__ = "evidence_records"
    
    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    
    # What this evidence is about
    entity_type = Column(String(50), nullable=False)  # property, market, owner
    entity_id = Column(PGUUID(as_uuid=True), nullable=False, index=True)
    
    # Evidence classification
    evidence_type = Column(String(50), nullable=False)  # physical, usage, ownership, market, regulatory, financial, document
    source = Column(String(100), nullable=False)  # county_records, mls, pms_export, operator_upload
    source_id = Column(String(255), nullable=True)  # External reference ID
    
    # The actual evidence
    field_name = Column(String(100), nullable=True)  # beds, baths, owner_name, etc.
    value = Column(JSONB, nullable=True)  # Flexible value storage
    raw_data = Column(JSONB, nullable=True)  # Original unprocessed data
    
    # Quality
    confidence = Column(Float, default=0.5)
    
    # Timing
    observed_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Indexing
    __table_args__ = (
        Index('ix_evidence_entity', 'entity_type', 'entity_id'),
        Index('ix_evidence_type', 'evidence_type'),
        Index('ix_evidence_source', 'source'),
        Index('ix_evidence_observed', 'observed_at'),
    )


# =============================================================================
# OPERATIONAL SNAPSHOTS
# =============================================================================

class OperationalSnapshotModel(Base):
    """
    Point-in-time operational state snapshots.
    
    Used for:
    - Permission decisions (late checkout, early check-in)
    - Turnover feasibility
    - Staff capacity tracking
    
    Snapshots are immutable once created.
    """
    __tablename__ = "operational_snapshots"
    
    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    property_id = Column(PGUUID(as_uuid=True), nullable=False, index=True)
    
    # Calendar state
    next_checkin = Column(DateTime, nullable=True)
    next_checkout = Column(DateTime, nullable=True)
    current_reservation_id = Column(String(100), nullable=True)
    
    # Turnover
    turnover_status = Column(String(20), default="normal")  # tight, normal, flexible
    turnover_buffer_hours = Column(Float, default=5.0)
    
    # Cleaning
    cleaning_status = Column(String(20), default="not_scheduled")
    cleaning_scheduled_at = Column(DateTime, nullable=True)
    
    # Staff
    staff_capacity = Column(String(20), default="normal")  # strained, normal, flexible
    
    # Issues
    has_critical_issues = Column(Boolean, default=False)
    known_issues = Column(JSONB, default=list)
    
    # Timing
    snapshot_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        Index('ix_ops_snapshot_property', 'property_id'),
        Index('ix_ops_snapshot_time', 'snapshot_at'),
    )


# =============================================================================
# PITCH BOOKS (Optional Caching)
# =============================================================================

class PitchBookModel(Base):
    """
    Cached pitch book artifacts.
    
    Optional - pitch books can always be regenerated from evidence.
    Useful for:
    - Audit trail
    - PDF caching
    - Performance (avoid regeneration)
    """
    __tablename__ = "pitch_books"
    
    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    property_id = Column(PGUUID(as_uuid=True), nullable=False, index=True)
    
    # Content
    audience = Column(String(20), default="homeowner")  # homeowner, realtor, investor
    content = Column(JSONB, nullable=False)  # Serialized PitchBook
    
    # Projections at generation time
    annual_revenue_low = Column(Float, nullable=True)
    annual_revenue_expected = Column(Float, nullable=True)
    annual_revenue_high = Column(Float, nullable=True)
    
    # Market context at generation time
    market_id = Column(String(50), nullable=True)
    market_snapshot = Column(JSONB, nullable=True)
    
    # Rendered artifacts
    pdf_url = Column(String(500), nullable=True)
    html_content = Column(Text, nullable=True)
    
    # Metadata
    generated_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)
    
    __table_args__ = (
        Index('ix_pitchbook_property', 'property_id'),
        Index('ix_pitchbook_generated', 'generated_at'),
    )


# =============================================================================
# CONCIERGE DECISION LOGS
# =============================================================================

class ConciergeDecisionLogModel(Base):
    """
    Audit log of concierge decisions.
    
    Used for:
    - Monitoring decision quality
    - Learning from outcomes
    - Compliance audit
    
    This logs WHAT was decided, not the intelligence itself.
    """
    __tablename__ = "concierge_decision_logs"
    
    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    
    # Context
    property_id = Column(PGUUID(as_uuid=True), nullable=False, index=True)
    guest_id = Column(PGUUID(as_uuid=True), nullable=True)
    reservation_id = Column(String(100), nullable=True)
    
    # Request
    decision_type = Column(String(50), nullable=False)  # late_checkout, early_checkin, question, proactive
    request_intent = Column(String(50), nullable=True)
    request_text = Column(Text, nullable=True)
    
    # Decision
    decision_mode = Column(String(20), nullable=False)  # reactive, proactive, permission
    approved = Column(Boolean, nullable=True)
    response_text = Column(Text, nullable=True)
    
    # Escalation
    required_escalation = Column(Boolean, default=False)
    escalation_reason = Column(String(255), nullable=True)
    
    # Context snapshot (for debugging/learning)
    guest_context = Column(JSONB, nullable=True)
    ops_state_snapshot = Column(JSONB, nullable=True)
    market_context_snapshot = Column(JSONB, nullable=True)
    
    # Outcome (filled in later if tracked)
    outcome_recorded = Column(Boolean, default=False)
    outcome_positive = Column(Boolean, nullable=True)
    outcome_notes = Column(Text, nullable=True)
    
    # Timing
    decided_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        Index('ix_decision_log_property', 'property_id'),
        Index('ix_decision_log_type', 'decision_type'),
        Index('ix_decision_log_time', 'decided_at'),
    )


# =============================================================================
# MARKET EVIDENCE (Events, Demand)
# =============================================================================

class MarketEvidenceModel(Base):
    """
    Market-level evidence storage.
    
    Separate from property evidence for:
    - Events
    - Experience demand signals
    - Supply/demand pressure
    - Pricing signals
    """
    __tablename__ = "market_evidence"
    
    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    market_id = Column(String(50), nullable=False, index=True)
    
    # Evidence type
    evidence_type = Column(String(50), nullable=False)  # event, experience_demand, supply_demand, pricing_signal
    
    # Content
    data = Column(JSONB, nullable=False)
    
    # Validity
    valid_from = Column(DateTime, nullable=True)
    valid_until = Column(DateTime, nullable=True)
    
    # Source
    source = Column(String(100), nullable=False)
    confidence = Column(Float, default=0.5)
    
    # Timing
    observed_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        Index('ix_market_evidence_market', 'market_id'),
        Index('ix_market_evidence_type', 'evidence_type'),
        Index('ix_market_evidence_valid', 'valid_from', 'valid_until'),
    )
