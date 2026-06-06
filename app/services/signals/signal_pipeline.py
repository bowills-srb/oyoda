"""
Signal Pipeline Core - Production Infrastructure

This module provides the core infrastructure for:
1. Signal Storage (PostgreSQL)
2. Signal Validation (Quality Gates)
3. Signal Processing (Decay, Aggregation)
4. Signal Retrieval (Caching, Bundles)

Run database migrations with:
    python -m signal_pipeline.migrations

Start the pipeline with:
    python -m signal_pipeline.runner
"""

import asyncio
import hashlib
import json
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Type
from uuid import UUID, uuid4
import math

# Database
try:
    import asyncpg
    HAS_ASYNCPG = True
except ImportError:
    HAS_ASYNCPG = False
    asyncpg = None

# Caching
try:
    import redis.asyncio as redis
    HAS_REDIS = True
except ImportError:
    HAS_REDIS = False
    redis = None

# Validation
from pydantic import BaseModel, Field, field_validator

from app.core.db_connect import asyncpg_connection_kwargs, normalize_asyncpg_dsn

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================

@dataclass
class PipelineConfig:
    """Pipeline configuration."""
    # Database
    database_url: str = field(
        default_factory=lambda: os.environ.get(
            "DATABASE_URL", 
            "postgresql://localhost:5432/signals"
        )
    )
    
    # Redis
    redis_url: str = field(
        default_factory=lambda: os.environ.get(
            "REDIS_URL",
            "redis://localhost:6379/0"
        )
    )
    
    # Processing
    batch_size: int = 100
    max_signal_age_days: int = 365
    cache_ttl_seconds: int = 3600
    
    # Quality gates
    min_confidence: float = 0.1
    min_sample_size: int = 5
    max_staleness_hours: int = 72
    
    # Alerting
    alert_on_high_quarantine_rate: float = 0.1
    alert_on_low_coverage: float = 0.5


# =============================================================================
# DATABASE SCHEMA
# =============================================================================

SCHEMA_SQL = """
-- Signal Types Enum
DO $$ BEGIN
    CREATE TYPE signal_type AS ENUM (
        'supply_density', 'bedroom_distribution', 'property_type_mix',
        'calendar_compression', 'lead_time', 'rate_acceleration',
        'platform_dominance', 'platform_performance_bias',
        'amenity_prevalence', 'amenity_lift',
        'seasonality', 'seasonality_curve',
        'operator_delta', 'operational_stability',
        'regulatory_risk', 'str_restriction',
        'travel_flow', 'event_impact', 'weather_pattern',
        'transaction_velocity', 'housing_stock',
        'rate_position', 'rate_by_bedroom'
    );
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- Signal Sources Enum
DO $$ BEGIN
    CREATE TYPE signal_source AS ENUM (
        'airbnb_public', 'vrbo_public', 'booking_public',
        'census_acs', 'bts_dot', 'noaa_nws',
        'county_assessor', 'county_recorder',
        'state_tourism', 'local_cvb', 'faa_stats',
        'operator_pms', 'operator_manual',
        'derived', 'inferred', 'aggregated',
        'historical_cache'
    );
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- Main signals table (append-only)
CREATE TABLE IF NOT EXISTS signals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    signal_type signal_type NOT NULL,
    geo_id VARCHAR(100) NOT NULL,
    property_id UUID,
    source signal_source NOT NULL,
    source_detail VARCHAR(255),
    
    -- Value (JSONB for flexibility)
    value JSONB NOT NULL,
    unit VARCHAR(50),
    
    -- Confidence
    confidence DECIMAL(5,4) NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    confidence_low DECIMAL(20,4),
    confidence_high DECIMAL(20,4),
    confidence_level VARCHAR(20) DEFAULT 'medium',
    
    -- Temporal
    decay_half_life_days INTEGER NOT NULL DEFAULT 30,
    observed_at TIMESTAMPTZ NOT NULL,
    valid_from TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    valid_to TIMESTAMPTZ,
    
    -- Metadata
    metadata JSONB DEFAULT '{}',
    
    -- Audit
    created_at TIMESTAMPTZ DEFAULT NOW(),
    batch_id UUID,
    scrape_job_id UUID
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_signals_geo_type 
    ON signals(geo_id, signal_type);
CREATE INDEX IF NOT EXISTS idx_signals_observed 
    ON signals(observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_signals_type_recent 
    ON signals(signal_type, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_signals_geo_observed 
    ON signals(geo_id, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_signals_batch 
    ON signals(batch_id);

-- Quarantine table for failed validations
CREATE TABLE IF NOT EXISTS signal_quarantine (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    original_signal JSONB NOT NULL,
    reason VARCHAR(255) NOT NULL,
    error_details JSONB,
    quarantined_at TIMESTAMPTZ DEFAULT NOW(),
    status VARCHAR(50) DEFAULT 'pending',
    reviewed_at TIMESTAMPTZ,
    reviewed_by VARCHAR(100)
);

-- Scrape jobs tracking
CREATE TABLE IF NOT EXISTS scrape_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_type VARCHAR(50) NOT NULL,
    market_id VARCHAR(100),
    source signal_source NOT NULL,
    status VARCHAR(50) DEFAULT 'pending',
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    records_scraped INTEGER DEFAULT 0,
    records_valid INTEGER DEFAULT 0,
    records_quarantined INTEGER DEFAULT 0,
    error_message TEXT,
    metadata JSONB DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_scrape_jobs_status 
    ON scrape_jobs(status, started_at DESC);

-- Signal coverage view
CREATE OR REPLACE VIEW signal_coverage AS
SELECT 
    geo_id,
    COUNT(DISTINCT signal_type) as signal_types_present,
    COUNT(*) as total_signals,
    MAX(observed_at) as latest_signal,
    AVG(confidence) as avg_confidence,
    ARRAY_AGG(DISTINCT signal_type) as types_present
FROM signals
WHERE observed_at > NOW() - INTERVAL '7 days'
GROUP BY geo_id;

-- Latest signals materialized view
CREATE MATERIALIZED VIEW IF NOT EXISTS latest_signals AS
SELECT DISTINCT ON (geo_id, signal_type)
    id, signal_type, geo_id, source, value, unit,
    confidence, confidence_level,
    decay_half_life_days, observed_at, metadata
FROM signals
WHERE (valid_to IS NULL OR valid_to > NOW())
ORDER BY geo_id, signal_type, observed_at DESC;

CREATE UNIQUE INDEX IF NOT EXISTS idx_latest_signals_pk 
    ON latest_signals(geo_id, signal_type);

-- Refresh function
CREATE OR REPLACE FUNCTION refresh_latest_signals()
RETURNS void AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY latest_signals;
END;
$$ LANGUAGE plpgsql;
"""


# =============================================================================
# VALIDATION RULES
# =============================================================================

class ValidationRule(ABC):
    """Base class for validation rules."""
    
    @abstractmethod
    def validate(self, signal: Dict) -> Tuple[bool, Optional[str]]:
        """Validate a signal. Returns (is_valid, error_message)."""
        pass


class SchemaValidation(ValidationRule):
    """Validate signal matches expected schema."""
    
    REQUIRED_FIELDS = [
        "signal_type", "geo_id", "source", "value", 
        "confidence", "observed_at"
    ]
    
    def validate(self, signal: Dict) -> Tuple[bool, Optional[str]]:
        for field in self.REQUIRED_FIELDS:
            if field not in signal:
                return False, f"Missing required field: {field}"
        return True, None


class ConfidenceValidation(ValidationRule):
    """Validate confidence is within bounds."""
    
    def __init__(self, min_confidence: float = 0.0, max_confidence: float = 1.0):
        self.min_confidence = min_confidence
        self.max_confidence = max_confidence
    
    def validate(self, signal: Dict) -> Tuple[bool, Optional[str]]:
        conf = signal.get("confidence")
        if conf is None:
            return False, "Missing confidence"
        if not self.min_confidence <= conf <= self.max_confidence:
            return False, f"Confidence {conf} out of bounds [{self.min_confidence}, {self.max_confidence}]"
        return True, None


class FreshnessValidation(ValidationRule):
    """Validate signal is not too old."""
    
    def __init__(self, max_age_hours: int = 72):
        self.max_age_hours = max_age_hours
    
    def validate(self, signal: Dict) -> Tuple[bool, Optional[str]]:
        observed = signal.get("observed_at")
        if not observed:
            return False, "Missing observed_at"
        
        if isinstance(observed, str):
            observed = datetime.fromisoformat(observed.replace('Z', '+00:00'))
        
        age = datetime.utcnow() - observed.replace(tzinfo=None)
        if age > timedelta(hours=self.max_age_hours):
            return False, f"Signal too old: {age.total_seconds() / 3600:.1f} hours"
        return True, None


class RangeValidation(ValidationRule):
    """Validate numeric values are within expected ranges."""
    
    RANGES = {
        "supply_density": {"listings": (1, 50000)},
        "calendar_compression": {"blocked_pct_30d": (0, 1)},
        "rate_position": {"p50": (25, 10000)},
        "amenity_prevalence": {"prevalence_pct": (0, 1)},
        "platform_dominance": {"airbnb_share": (0, 1), "vrbo_share": (0, 1)},
    }
    
    def validate(self, signal: Dict) -> Tuple[bool, Optional[str]]:
        signal_type = signal.get("signal_type")
        value = signal.get("value", {})
        
        if signal_type not in self.RANGES:
            return True, None  # No range defined
        
        for field, (min_val, max_val) in self.RANGES[signal_type].items():
            if field in value:
                v = value[field]
                if v is not None and not min_val <= v <= max_val:
                    return False, f"{field}={v} out of range [{min_val}, {max_val}]"
        
        return True, None


class SignalValidator:
    """Validates signals against all rules."""
    
    def __init__(self, config: PipelineConfig):
        self.config = config
        self.rules: List[ValidationRule] = [
            SchemaValidation(),
            ConfidenceValidation(min_confidence=config.min_confidence),
            FreshnessValidation(max_age_hours=config.max_staleness_hours),
            RangeValidation(),
        ]
    
    def validate(self, signal: Dict) -> Tuple[bool, List[str]]:
        """Validate signal against all rules."""
        errors = []
        
        for rule in self.rules:
            is_valid, error = rule.validate(signal)
            if not is_valid:
                errors.append(f"{rule.__class__.__name__}: {error}")
        
        return len(errors) == 0, errors
    
    def add_rule(self, rule: ValidationRule):
        """Add a custom validation rule."""
        self.rules.append(rule)


# =============================================================================
# SIGNAL STORE
# =============================================================================

class SignalStore:
    """
    PostgreSQL-backed signal storage.
    
    Features:
    - Append-only signal storage
    - Batch inserts for efficiency
    - Quarantine for invalid signals
    - Materialized view for latest signals
    """
    
    def __init__(self, config: PipelineConfig):
        self.config = config
        self.pool: Optional[asyncpg.Pool] = None
        self.validator = SignalValidator(config)
    
    async def connect(self):
        """Connect to database."""
        if not HAS_ASYNCPG:
            raise RuntimeError("asyncpg not installed: pip install asyncpg")
        
        self.pool = await asyncpg.create_pool(
            dsn=normalize_asyncpg_dsn(self.config.database_url),
            min_size=2,
            max_size=10,
            **asyncpg_connection_kwargs(self.config.database_url),
        )
        logger.info("Connected to PostgreSQL")
    
    async def close(self):
        """Close database connection."""
        if self.pool:
            await self.pool.close()
    
    async def initialize_schema(self):
        """Create database schema."""
        async with self.pool.acquire() as conn:
            await conn.execute(SCHEMA_SQL)
        logger.info("Database schema initialized")
    
    async def store_signal(self, signal: Dict) -> Optional[UUID]:
        """
        Store a single signal.
        
        Returns signal ID if valid, None if quarantined.
        """
        # Validate
        is_valid, errors = self.validator.validate(signal)
        
        if not is_valid:
            await self._quarantine_signal(signal, errors)
            return None
        
        # Insert
        signal_id = uuid4()
        
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO signals (
                    id, signal_type, geo_id, property_id, source, source_detail,
                    value, unit, confidence, confidence_low, confidence_high,
                    confidence_level, decay_half_life_days, observed_at,
                    valid_from, valid_to, metadata, batch_id
                ) VALUES (
                    $1, $2::signal_type, $3, $4, $5::signal_source, $6,
                    $7, $8, $9, $10, $11,
                    $12, $13, $14,
                    $15, $16, $17, $18
                )
            """,
                signal_id,
                signal["signal_type"],
                signal["geo_id"],
                signal.get("property_id"),
                signal["source"],
                signal.get("source_detail"),
                json.dumps(signal["value"]),
                signal.get("unit"),
                signal["confidence"],
                signal.get("confidence_band", [None, None])[0],
                signal.get("confidence_band", [None, None])[1],
                signal.get("confidence_level", "medium"),
                signal.get("decay_half_life_days", 30),
                datetime.fromisoformat(signal["observed_at"].replace('Z', '+00:00')),
                datetime.fromisoformat(signal.get("valid_from", signal["observed_at"]).replace('Z', '+00:00')),
                datetime.fromisoformat(signal["valid_to"].replace('Z', '+00:00')) if signal.get("valid_to") else None,
                json.dumps(signal.get("metadata", {})),
                signal.get("batch_id"),
            )
        
        return signal_id
    
    async def store_signals_batch(
        self, 
        signals: List[Dict],
        batch_id: Optional[UUID] = None,
    ) -> Tuple[int, int]:
        """
        Store multiple signals in a batch.
        
        Returns (valid_count, quarantined_count)
        """
        batch_id = batch_id or uuid4()
        valid_count = 0
        quarantine_count = 0
        
        for signal in signals:
            signal["batch_id"] = str(batch_id)
            result = await self.store_signal(signal)
            if result:
                valid_count += 1
            else:
                quarantine_count += 1
        
        logger.info(f"Batch {batch_id}: {valid_count} valid, {quarantine_count} quarantined")
        return valid_count, quarantine_count
    
    async def _quarantine_signal(self, signal: Dict, errors: List[str]):
        """Store invalid signal in quarantine."""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO signal_quarantine (original_signal, reason, error_details)
                VALUES ($1, $2, $3)
            """,
                json.dumps(signal),
                "; ".join(errors),
                json.dumps({"errors": errors}),
            )
        logger.warning(f"Quarantined signal: {errors[0]}")
    
    async def get_latest_signals(
        self, 
        geo_id: str,
        signal_types: Optional[List[str]] = None,
    ) -> List[Dict]:
        """Get latest signals for a geo."""
        async with self.pool.acquire() as conn:
            if signal_types:
                rows = await conn.fetch("""
                    SELECT * FROM latest_signals
                    WHERE geo_id = $1 AND signal_type = ANY($2)
                """, geo_id, signal_types)
            else:
                rows = await conn.fetch("""
                    SELECT * FROM latest_signals
                    WHERE geo_id = $1
                """, geo_id)
        
        return [dict(row) for row in rows]
    
    async def get_signal_history(
        self,
        geo_id: str,
        signal_type: str,
        days: int = 30,
    ) -> List[Dict]:
        """Get signal history for trend analysis."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM signals
                WHERE geo_id = $1 
                  AND signal_type = $2::signal_type
                  AND observed_at > NOW() - INTERVAL '%s days'
                ORDER BY observed_at DESC
            """ % days, geo_id, signal_type)
        
        return [dict(row) for row in rows]
    
    async def get_coverage(self, geo_id: str) -> Dict:
        """Get signal coverage for a geo."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT * FROM signal_coverage WHERE geo_id = $1
            """, geo_id)
        
        if not row:
            return {"geo_id": geo_id, "coverage_score": 0, "signal_types": []}
        
        return dict(row)
    
    async def refresh_materialized_views(self):
        """Refresh materialized views."""
        async with self.pool.acquire() as conn:
            await conn.execute("SELECT refresh_latest_signals()")
        logger.info("Materialized views refreshed")


# =============================================================================
# SIGNAL PROCESSOR
# =============================================================================

class SignalProcessor:
    """
    Processes signals into intelligence.
    
    Features:
    - Confidence decay calculation
    - Signal aggregation
    - Bundle creation
    - Coverage scoring
    """
    
    CORE_SIGNAL_TYPES = [
        "supply_density",
        "calendar_compression", 
        "platform_dominance",
        "amenity_prevalence",
        "rate_position",
        "seasonality_curve",
    ]
    
    def __init__(self, store: SignalStore):
        self.store = store
    
    def calculate_decayed_confidence(
        self, 
        signal: Dict, 
        as_of: Optional[datetime] = None
    ) -> float:
        """Calculate confidence with time decay applied."""
        as_of = as_of or datetime.utcnow()
        
        observed = signal.get("observed_at")
        if isinstance(observed, str):
            observed = datetime.fromisoformat(observed.replace('Z', '+00:00'))
        observed = observed.replace(tzinfo=None)
        
        days_elapsed = (as_of - observed).days
        if days_elapsed <= 0:
            return signal["confidence"]
        
        half_life = signal.get("decay_half_life_days", 30)
        decay_factor = math.exp(-0.693 * days_elapsed / half_life)
        
        return signal["confidence"] * decay_factor
    
    async def create_signal_bundle(
        self,
        geo_id: str,
        as_of: Optional[datetime] = None,
    ) -> Dict:
        """
        Create a signal bundle for a geo.
        
        A bundle contains all latest signals with:
        - Decayed confidence
        - Coverage score
        - Overall confidence
        """
        as_of = as_of or datetime.utcnow()
        
        # Get latest signals
        signals = await self.store.get_latest_signals(geo_id)
        
        # Apply decay
        for signal in signals:
            signal["decayed_confidence"] = self.calculate_decayed_confidence(signal, as_of)
        
        # Calculate coverage
        types_present = set(s["signal_type"] for s in signals)
        core_coverage = len(types_present & set(self.CORE_SIGNAL_TYPES)) / len(self.CORE_SIGNAL_TYPES)
        
        # Calculate overall confidence
        if signals:
            weights = [s["decayed_confidence"] for s in signals]
            total_weight = sum(weights)
            if total_weight > 0:
                overall_confidence = sum(
                    s["confidence"] * s["decayed_confidence"] 
                    for s in signals
                ) / total_weight
            else:
                overall_confidence = 0
        else:
            overall_confidence = 0
        
        # Determine confidence level
        if overall_confidence >= 0.75 and core_coverage >= 0.8:
            confidence_level = "high"
        elif overall_confidence >= 0.5 and core_coverage >= 0.5:
            confidence_level = "medium"
        elif overall_confidence >= 0.25:
            confidence_level = "low"
        else:
            confidence_level = "insufficient"
        
        return {
            "bundle_id": str(uuid4()),
            "geo_id": geo_id,
            "as_of": as_of.isoformat(),
            "signals": signals,
            "signal_count": len(signals),
            "types_present": list(types_present),
            "coverage_score": core_coverage,
            "overall_confidence": overall_confidence,
            "confidence_level": confidence_level,
        }
    
    def detect_anomaly(
        self,
        signal: Dict,
        historical: List[Dict],
        zscore_threshold: float = 3.0,
    ) -> Tuple[bool, Optional[float]]:
        """
        Detect if a signal value is anomalous.
        
        Returns (is_anomaly, zscore)
        """
        if len(historical) < 5:
            return False, None
        
        # Extract comparable values
        def extract_value(s):
            v = s.get("value", {})
            if isinstance(v, dict):
                # Get the primary numeric value
                for key in ["listings", "blocked_pct_30d", "p50", "airbnb_share"]:
                    if key in v and v[key] is not None:
                        return v[key]
            elif isinstance(v, (int, float)):
                return v
            return None
        
        current = extract_value(signal)
        if current is None:
            return False, None
        
        historical_values = [extract_value(s) for s in historical]
        historical_values = [v for v in historical_values if v is not None]
        
        if len(historical_values) < 5:
            return False, None
        
        mean = sum(historical_values) / len(historical_values)
        variance = sum((v - mean) ** 2 for v in historical_values) / len(historical_values)
        std = variance ** 0.5
        
        if std == 0:
            return False, 0
        
        zscore = abs(current - mean) / std
        return zscore > zscore_threshold, zscore


# =============================================================================
# SIGNAL CACHE
# =============================================================================

class SignalCache:
    """
    Redis-backed signal cache for fast retrieval.
    """
    
    def __init__(self, config: PipelineConfig):
        self.config = config
        self.client: Optional[redis.Redis] = None
    
    async def connect(self):
        """Connect to Redis."""
        if not HAS_REDIS:
            logger.warning("Redis not available, caching disabled")
            return
        
        self.client = redis.from_url(self.config.redis_url)
        logger.info("Connected to Redis")
    
    async def close(self):
        """Close Redis connection."""
        if self.client:
            await self.client.close()
    
    async def get_bundle(self, geo_id: str) -> Optional[Dict]:
        """Get cached signal bundle."""
        if not self.client:
            return None
        
        data = await self.client.get(f"signals:{geo_id}:bundle")
        if data:
            return json.loads(data)
        return None
    
    async def set_bundle(self, geo_id: str, bundle: Dict):
        """Cache signal bundle."""
        if not self.client:
            return
        
        await self.client.setex(
            f"signals:{geo_id}:bundle",
            self.config.cache_ttl_seconds,
            json.dumps(bundle, default=str),
        )
    
    async def invalidate(self, geo_id: str):
        """Invalidate cache for a geo."""
        if not self.client:
            return
        
        await self.client.delete(
            f"signals:{geo_id}:bundle",
            f"signals:{geo_id}:latest",
        )


# =============================================================================
# METRICS
# =============================================================================

class PipelineMetrics:
    """
    Pipeline metrics for observability.
    
    In production, these would be exported to Prometheus.
    """
    
    def __init__(self):
        self.counters: Dict[str, int] = {}
        self.gauges: Dict[str, float] = {}
        self.histograms: Dict[str, List[float]] = {}
    
    def inc(self, name: str, labels: Dict[str, str] = None, value: int = 1):
        """Increment a counter."""
        key = self._make_key(name, labels)
        self.counters[key] = self.counters.get(key, 0) + value
    
    def set(self, name: str, value: float, labels: Dict[str, str] = None):
        """Set a gauge value."""
        key = self._make_key(name, labels)
        self.gauges[key] = value
    
    def observe(self, name: str, value: float, labels: Dict[str, str] = None):
        """Record a histogram observation."""
        key = self._make_key(name, labels)
        if key not in self.histograms:
            self.histograms[key] = []
        self.histograms[key].append(value)
    
    def _make_key(self, name: str, labels: Dict[str, str] = None) -> str:
        if not labels:
            return name
        label_str = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}"
    
    def get_summary(self) -> Dict:
        """Get metrics summary."""
        return {
            "counters": self.counters,
            "gauges": self.gauges,
            "histograms": {
                k: {
                    "count": len(v),
                    "mean": sum(v) / len(v) if v else 0,
                    "min": min(v) if v else 0,
                    "max": max(v) if v else 0,
                }
                for k, v in self.histograms.items()
            },
        }


# =============================================================================
# PIPELINE ORCHESTRATOR
# =============================================================================

class SignalPipeline:
    """
    Main pipeline orchestrator.
    
    Usage:
        pipeline = SignalPipeline()
        await pipeline.initialize()
        
        # Store signals
        await pipeline.ingest_signals(signals)
        
        # Get intelligence
        bundle = await pipeline.get_signal_bundle("30a")
    """
    
    def __init__(self, config: Optional[PipelineConfig] = None):
        self.config = config or PipelineConfig()
        self.store = SignalStore(self.config)
        self.processor = SignalProcessor(self.store)
        self.cache = SignalCache(self.config)
        self.metrics = PipelineMetrics()
    
    async def initialize(self):
        """Initialize all components."""
        await self.store.connect()
        await self.store.initialize_schema()
        await self.cache.connect()
        logger.info("Signal pipeline initialized")
    
    async def close(self):
        """Close all connections."""
        await self.store.close()
        await self.cache.close()
    
    async def ingest_signals(
        self,
        signals: List[Dict],
        source: str = "unknown",
        market_id: Optional[str] = None,
    ) -> Dict:
        """
        Ingest signals into the pipeline.
        
        Returns ingestion stats.
        """
        batch_id = uuid4()
        start_time = datetime.utcnow()
        
        # Record job
        async with self.store.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO scrape_jobs (id, job_type, market_id, source, status, started_at)
                VALUES ($1, 'ingest', $2, $3::signal_source, 'running', $4)
            """, batch_id, market_id, source, start_time)
        
        # Ingest
        valid_count, quarantine_count = await self.store.store_signals_batch(
            signals, batch_id
        )
        
        # Update job
        end_time = datetime.utcnow()
        async with self.store.pool.acquire() as conn:
            await conn.execute("""
                UPDATE scrape_jobs SET
                    status = 'completed',
                    completed_at = $2,
                    records_scraped = $3,
                    records_valid = $4,
                    records_quarantined = $5
                WHERE id = $1
            """, batch_id, end_time, len(signals), valid_count, quarantine_count)
        
        # Invalidate cache for affected geos
        geos = set(s.get("geo_id") for s in signals if s.get("geo_id"))
        for geo_id in geos:
            await self.cache.invalidate(geo_id)
        
        # Metrics
        self.metrics.inc("signals_ingested", {"source": source}, valid_count)
        self.metrics.inc("signals_quarantined", {"source": source}, quarantine_count)
        self.metrics.observe(
            "ingest_duration_seconds",
            (end_time - start_time).total_seconds(),
            {"source": source},
        )
        
        # Check alert threshold
        if len(signals) > 0:
            quarantine_rate = quarantine_count / len(signals)
            if quarantine_rate > self.config.alert_on_high_quarantine_rate:
                logger.warning(
                    f"High quarantine rate: {quarantine_rate:.1%} for {source}"
                )
        
        return {
            "batch_id": str(batch_id),
            "total": len(signals),
            "valid": valid_count,
            "quarantined": quarantine_count,
            "duration_seconds": (end_time - start_time).total_seconds(),
        }
    
    async def get_signal_bundle(
        self,
        geo_id: str,
        use_cache: bool = True,
    ) -> Dict:
        """
        Get signal bundle for a geo.
        
        Returns cached bundle if available and fresh.
        """
        # Try cache first
        if use_cache:
            cached = await self.cache.get_bundle(geo_id)
            if cached:
                self.metrics.inc("cache_hits")
                return cached
        
        self.metrics.inc("cache_misses")
        
        # Create bundle
        bundle = await self.processor.create_signal_bundle(geo_id)
        
        # Cache it
        await self.cache.set_bundle(geo_id, bundle)
        
        return bundle
    
    async def get_pipeline_health(self) -> Dict:
        """Get pipeline health status."""
        # Check database
        try:
            async with self.store.pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            db_healthy = True
        except:
            db_healthy = False
        
        # Check cache
        try:
            if self.cache.client:
                await self.cache.client.ping()
            cache_healthy = True
        except:
            cache_healthy = False
        
        # Get recent stats
        async with self.store.pool.acquire() as conn:
            recent_jobs = await conn.fetch("""
                SELECT status, COUNT(*) as count
                FROM scrape_jobs
                WHERE started_at > NOW() - INTERVAL '24 hours'
                GROUP BY status
            """)
            
            quarantine_count = await conn.fetchval("""
                SELECT COUNT(*) FROM signal_quarantine
                WHERE quarantined_at > NOW() - INTERVAL '24 hours'
            """)
        
        jobs_by_status = {row["status"]: row["count"] for row in recent_jobs}
        
        return {
            "healthy": db_healthy and cache_healthy,
            "database": "healthy" if db_healthy else "unhealthy",
            "cache": "healthy" if cache_healthy else "unhealthy",
            "jobs_24h": jobs_by_status,
            "quarantined_24h": quarantine_count,
            "metrics": self.metrics.get_summary(),
        }


# =============================================================================
# CLI
# =============================================================================

async def main():
    """Run pipeline initialization and health check."""
    config = PipelineConfig()
    pipeline = SignalPipeline(config)
    
    try:
        print("Initializing signal pipeline...")
        await pipeline.initialize()
        
        print("\nPipeline health:")
        health = await pipeline.get_pipeline_health()
        print(json.dumps(health, indent=2, default=str))
        
    finally:
        await pipeline.close()


if __name__ == "__main__":
    asyncio.run(main())
