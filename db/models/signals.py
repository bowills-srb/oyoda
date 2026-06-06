"""
Signal Store - Database Schema and Repository.

This is the persistence layer for the signal system.
All signals flow through here before reaching the analytics engine.

Key Properties:
- Tenant isolated
- Time-series optimized (TimescaleDB hypertable)
- Indexed for common query patterns
- Supports signal replay and backfill
"""

from datetime import datetime, date
from typing import List, Optional, Dict, Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    func,
    select,
    and_,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from db.models import Base, TimestampMixin


# =============================================================================
# SIGNAL TABLE MODEL
# =============================================================================

class SignalModel(Base, TimestampMixin):
    """
    Persistent storage for signals.
    
    This table is designed to be a TimescaleDB hypertable for
    efficient time-series queries.
    """
    
    __tablename__ = "signals"
    
    # === Identity ===
    signal_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    
    # === Classification ===
    signal_type: Mapped[str] = mapped_column(String(50), nullable=False)
    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    
    # === Scope References ===
    geo_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    property_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), index=True)
    platform: Mapped[Optional[str]] = mapped_column(String(20))
    
    # === The Signal Value ===
    value: Mapped[float] = mapped_column(Float, nullable=False)
    structured_value: Mapped[Optional[dict]] = mapped_column(JSONB)
    
    # === Confidence & Weighting ===
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    weight_hint: Mapped[float] = mapped_column(Float, default=1.0)
    
    # === Provenance ===
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    detector_name: Mapped[str] = mapped_column(String(100), nullable=False)
    detector_version: Mapped[str] = mapped_column(String(20), nullable=False)
    
    # === Temporal Context ===
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    time_window: Mapped[str] = mapped_column(String(30), nullable=False)
    valid_from: Mapped[Optional[date]] = mapped_column(Date)
    valid_until: Mapped[Optional[date]] = mapped_column(Date)
    
    # === Decay & Geo Properties ===
    decay_profile: Mapped[str] = mapped_column(String(20), default="stable")
    geo_sensitivity: Mapped[str] = mapped_column(String(20), default="local")
    
    # === Metadata ===
    metadata: Mapped[dict] = mapped_column(JSONB, default={})
    
    # === Schema Version ===
    schema_version: Mapped[str] = mapped_column(String(20), default="1.0.0")
    
    # === Composite Indexes for Common Queries ===
    __table_args__ = (
        # Query pattern: Get all signals for a geo in time range
        Index(
            "ix_signals_geo_time",
            "tenant_id", "geo_id", "detected_at",
        ),
        
        # Query pattern: Get signals by type for analytics
        Index(
            "ix_signals_type_time",
            "tenant_id", "signal_type", "detected_at",
        ),
        
        # Query pattern: Get property signals
        Index(
            "ix_signals_property",
            "tenant_id", "property_id", "signal_type", "detected_at",
        ),
        
        # Query pattern: Get recent signals by scope
        Index(
            "ix_signals_scope_recent",
            "tenant_id", "scope", "detected_at",
        ),
        
        # Query pattern: Validity window queries
        Index(
            "ix_signals_validity",
            "valid_from", "valid_until",
        ),
    )


# =============================================================================
# SQL MIGRATION FOR TIMESCALEDB
# =============================================================================

SIGNAL_TABLE_SQL = """
-- Create signals table (if not using SQLAlchemy migrations)
CREATE TABLE IF NOT EXISTS signals (
    signal_id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    
    -- Classification
    signal_type VARCHAR(50) NOT NULL,
    scope VARCHAR(20) NOT NULL,
    
    -- Scope References
    geo_id VARCHAR(64),
    property_id UUID,
    platform VARCHAR(20),
    
    -- Value
    value DOUBLE PRECISION NOT NULL,
    structured_value JSONB,
    
    -- Confidence
    confidence DOUBLE PRECISION NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    weight_hint DOUBLE PRECISION DEFAULT 1.0,
    
    -- Provenance
    source VARCHAR(50) NOT NULL,
    detector_name VARCHAR(100) NOT NULL,
    detector_version VARCHAR(20) NOT NULL,
    
    -- Temporal
    detected_at TIMESTAMPTZ NOT NULL,
    time_window VARCHAR(30) NOT NULL,
    valid_from DATE,
    valid_until DATE,
    
    -- Decay/Geo
    decay_profile VARCHAR(20) DEFAULT 'stable',
    geo_sensitivity VARCHAR(20) DEFAULT 'local',
    
    -- Metadata
    metadata JSONB DEFAULT '{}',
    schema_version VARCHAR(20) DEFAULT '1.0.0',
    
    -- Audit
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Convert to TimescaleDB hypertable for time-series optimization
SELECT create_hypertable(
    'signals',
    'detected_at',
    chunk_time_interval => INTERVAL '1 month',
    if_not_exists => TRUE
);

-- Create indexes
CREATE INDEX IF NOT EXISTS ix_signals_tenant ON signals(tenant_id);
CREATE INDEX IF NOT EXISTS ix_signals_geo_time ON signals(tenant_id, geo_id, detected_at DESC);
CREATE INDEX IF NOT EXISTS ix_signals_type_time ON signals(tenant_id, signal_type, detected_at DESC);
CREATE INDEX IF NOT EXISTS ix_signals_property ON signals(tenant_id, property_id, signal_type, detected_at DESC);
CREATE INDEX IF NOT EXISTS ix_signals_scope_recent ON signals(tenant_id, scope, detected_at DESC);
CREATE INDEX IF NOT EXISTS ix_signals_validity ON signals(valid_from, valid_until);

-- GIN index for metadata queries
CREATE INDEX IF NOT EXISTS ix_signals_metadata ON signals USING GIN (metadata);

-- Compression policy (compress chunks older than 7 days)
SELECT add_compression_policy('signals', INTERVAL '7 days', if_not_exists => TRUE);

-- Retention policy (keep 2 years of data)
SELECT add_retention_policy('signals', INTERVAL '2 years', if_not_exists => TRUE);

-- Continuous aggregate for hourly signal summaries
CREATE MATERIALIZED VIEW IF NOT EXISTS signals_hourly
WITH (timescaledb.continuous) AS
SELECT
    tenant_id,
    geo_id,
    signal_type,
    time_bucket('1 hour', detected_at) AS bucket,
    COUNT(*) AS signal_count,
    AVG(value) AS avg_value,
    AVG(confidence) AS avg_confidence,
    MAX(detected_at) AS latest_at
FROM signals
GROUP BY tenant_id, geo_id, signal_type, bucket
WITH NO DATA;

-- Refresh policy for continuous aggregate
SELECT add_continuous_aggregate_policy('signals_hourly',
    start_offset => INTERVAL '3 hours',
    end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists => TRUE
);
"""


# =============================================================================
# SIGNAL REPOSITORY
# =============================================================================

class SignalRepository:
    """
    Repository for signal persistence and retrieval.
    
    All signal storage and queries go through this class.
    """
    
    def __init__(self, session):
        self.session = session
    
    async def store(self, signal: "Signal") -> SignalModel:
        """Store a single signal."""
        from schemas.signals import Signal
        
        model = SignalModel(
            signal_id=signal.signal_id,
            tenant_id=signal.tenant_id,
            signal_type=signal.signal_type,
            scope=signal.scope,
            geo_id=signal.geo_id,
            property_id=signal.property_id,
            platform=signal.platform,
            value=signal.value,
            structured_value=signal.structured_value,
            confidence=signal.confidence,
            weight_hint=signal.weight_hint,
            source=signal.source,
            detector_name=signal.detector_name,
            detector_version=signal.detector_version,
            detected_at=signal.detected_at,
            time_window=signal.time_window,
            valid_from=signal.valid_from,
            valid_until=signal.valid_until,
            decay_profile=signal.decay_profile,
            geo_sensitivity=signal.geo_sensitivity,
            metadata=signal.metadata,
            schema_version=signal.schema_version,
        )
        
        self.session.add(model)
        await self.session.commit()
        return model
    
    async def store_batch(self, signals: List["Signal"]) -> int:
        """Store multiple signals efficiently."""
        from schemas.signals import Signal
        
        models = [
            SignalModel(
                signal_id=s.signal_id,
                tenant_id=s.tenant_id,
                signal_type=s.signal_type,
                scope=s.scope,
                geo_id=s.geo_id,
                property_id=s.property_id,
                platform=s.platform,
                value=s.value,
                structured_value=s.structured_value,
                confidence=s.confidence,
                weight_hint=s.weight_hint,
                source=s.source,
                detector_name=s.detector_name,
                detector_version=s.detector_version,
                detected_at=s.detected_at,
                time_window=s.time_window,
                valid_from=s.valid_from,
                valid_until=s.valid_until,
                decay_profile=s.decay_profile,
                geo_sensitivity=s.geo_sensitivity,
                metadata=s.metadata,
                schema_version=s.schema_version,
            )
            for s in signals
        ]
        
        self.session.add_all(models)
        await self.session.commit()
        return len(models)
    
    async def get_for_geo(
        self,
        tenant_id: UUID,
        geo_id: str,
        signal_types: Optional[List[str]] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        limit: int = 1000,
    ) -> List[SignalModel]:
        """Get signals for a geographic area."""
        query = select(SignalModel).where(
            and_(
                SignalModel.tenant_id == tenant_id,
                SignalModel.geo_id == geo_id,
            )
        )
        
        if signal_types:
            query = query.where(SignalModel.signal_type.in_(signal_types))
        
        if since:
            query = query.where(SignalModel.detected_at >= since)
        
        if until:
            query = query.where(SignalModel.detected_at <= until)
        
        query = query.order_by(SignalModel.detected_at.desc()).limit(limit)
        
        result = await self.session.execute(query)
        return result.scalars().all()
    
    async def get_for_property(
        self,
        tenant_id: UUID,
        property_id: UUID,
        signal_types: Optional[List[str]] = None,
        since: Optional[datetime] = None,
        limit: int = 500,
    ) -> List[SignalModel]:
        """Get signals for a specific property."""
        query = select(SignalModel).where(
            and_(
                SignalModel.tenant_id == tenant_id,
                SignalModel.property_id == property_id,
            )
        )
        
        if signal_types:
            query = query.where(SignalModel.signal_type.in_(signal_types))
        
        if since:
            query = query.where(SignalModel.detected_at >= since)
        
        query = query.order_by(SignalModel.detected_at.desc()).limit(limit)
        
        result = await self.session.execute(query)
        return result.scalars().all()
    
    async def get_latest_by_type(
        self,
        tenant_id: UUID,
        geo_id: str,
        signal_type: str,
    ) -> Optional[SignalModel]:
        """Get the most recent signal of a type for a geo."""
        query = select(SignalModel).where(
            and_(
                SignalModel.tenant_id == tenant_id,
                SignalModel.geo_id == geo_id,
                SignalModel.signal_type == signal_type,
            )
        ).order_by(SignalModel.detected_at.desc()).limit(1)
        
        result = await self.session.execute(query)
        return result.scalar_one_or_none()
    
    async def get_valid_signals(
        self,
        tenant_id: UUID,
        geo_id: str,
        as_of: Optional[date] = None,
    ) -> List[SignalModel]:
        """Get all currently valid signals for a geo."""
        as_of = as_of or date.today()
        
        query = select(SignalModel).where(
            and_(
                SignalModel.tenant_id == tenant_id,
                SignalModel.geo_id == geo_id,
                (SignalModel.valid_from.is_(None) | (SignalModel.valid_from <= as_of)),
                (SignalModel.valid_until.is_(None) | (SignalModel.valid_until >= as_of)),
            )
        ).order_by(SignalModel.detected_at.desc())
        
        result = await self.session.execute(query)
        return result.scalars().all()
    
    async def delete_stale(
        self,
        tenant_id: UUID,
        before: datetime,
    ) -> int:
        """Delete signals older than a threshold."""
        # Note: With TimescaleDB retention policy, this is usually automatic
        # This is for manual cleanup if needed
        from sqlalchemy import delete
        
        stmt = delete(SignalModel).where(
            and_(
                SignalModel.tenant_id == tenant_id,
                SignalModel.detected_at < before,
            )
        )
        
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.rowcount


# =============================================================================
# SIGNAL AGGREGATION QUERIES
# =============================================================================

SIGNAL_AGGREGATION_QUERIES = {
    # Get average confidence by signal type
    "avg_confidence_by_type": """
        SELECT 
            signal_type,
            AVG(confidence) as avg_confidence,
            COUNT(*) as signal_count
        FROM signals
        WHERE tenant_id = :tenant_id
          AND geo_id = :geo_id
          AND detected_at > NOW() - INTERVAL '30 days'
        GROUP BY signal_type
        ORDER BY avg_confidence DESC
    """,
    
    # Get signal coverage (how many types do we have?)
    "signal_coverage": """
        SELECT 
            geo_id,
            COUNT(DISTINCT signal_type) as type_count,
            COUNT(*) as total_signals,
            MIN(detected_at) as earliest,
            MAX(detected_at) as latest
        FROM signals
        WHERE tenant_id = :tenant_id
          AND detected_at > NOW() - INTERVAL '30 days'
        GROUP BY geo_id
        ORDER BY type_count DESC
    """,
    
    # Get signal freshness
    "signal_freshness": """
        SELECT 
            signal_type,
            MAX(detected_at) as latest,
            EXTRACT(EPOCH FROM (NOW() - MAX(detected_at))) / 3600 as hours_stale
        FROM signals
        WHERE tenant_id = :tenant_id
          AND geo_id = :geo_id
        GROUP BY signal_type
        ORDER BY hours_stale DESC
    """,
    
    # Get weighted signal summary
    "weighted_summary": """
        SELECT 
            signal_type,
            SUM(value * confidence * weight_hint) / NULLIF(SUM(confidence * weight_hint), 0) as weighted_value,
            AVG(confidence) as avg_confidence,
            COUNT(*) as signal_count
        FROM signals
        WHERE tenant_id = :tenant_id
          AND geo_id = :geo_id
          AND detected_at > NOW() - INTERVAL '30 days'
        GROUP BY signal_type
    """,
}
