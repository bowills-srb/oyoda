# Signal Intelligence Pipeline - Production Infrastructure

## The Problem You're Solving

Raw scraped data is **not** intelligence. To turn signals into verifiable intelligence, you need:

1. **Collection** - Reliable, scheduled, monitored data gathering
2. **Validation** - Schema enforcement, anomaly detection, quality gates
3. **Storage** - Immutable signal store with full audit trail
4. **Processing** - Aggregation, decay, confidence calculation
5. **Serving** - Fast retrieval for analytics engines
6. **Observability** - Know when something breaks before it affects outputs

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           SIGNAL INTELLIGENCE PIPELINE                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐  │
│  │  SCHEDULER  │───►│  COLLECTOR  │───►│  VALIDATOR  │───►│   STORE     │  │
│  │  (Cron/K8s) │    │  (Scrapers) │    │  (Pydantic) │    │  (Postgres) │  │
│  └─────────────┘    └─────────────┘    └─────────────┘    └──────┬──────┘  │
│                            │                  │                   │         │
│                            ▼                  ▼                   ▼         │
│                     ┌─────────────┐    ┌─────────────┐    ┌─────────────┐  │
│                     │  MONITOR    │    │  QUARANTINE │    │  PROCESSOR  │  │
│                     │  (Metrics)  │    │  (Bad Data) │    │  (Signals)  │  │
│                     └─────────────┘    └─────────────┘    └──────┬──────┘  │
│                                                                   │         │
│                                                                   ▼         │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐  │
│  │  DASHBOARDS │◄───│   CACHE     │◄───│  BUNDLES    │◄───│  DECAY      │  │
│  │  BD PDFs    │    │  (Redis)    │    │  (per geo)  │    │  (EWMA)     │  │
│  └─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Component Specifications

### 1. Scheduler (Job Orchestration)

**Purpose:** Ensure scrapes run reliably, handle failures, prevent duplicates

**Options:**
- **Simple:** Cron + supervisord
- **Better:** Celery Beat + Redis
- **Best:** Temporal.io or Prefect (workflow orchestration)

**Requirements:**
```yaml
scrape_jobs:
  airbnb_vrbo:
    schedule: "0 2 * * *"  # Daily at 2 AM
    timeout: 2h
    retry: 3
    markets: [30a, destin, gulf_shores, pcb]
    
  census_acs:
    schedule: "0 3 1 * *"  # Monthly, 1st at 3 AM
    timeout: 30m
    retry: 2
    
  federal_bts:
    schedule: "0 4 1 * *"  # Monthly
    timeout: 30m
```

### 2. Collector (Scraper Fleet)

**Purpose:** Gather data from all sources reliably

**Requirements:**
- Proxy rotation (for OTA scraping)
- Rate limiting (per domain)
- Retry with exponential backoff
- Dead letter queue for failed scrapes
- Checkpointing for long-running jobs

**Metrics to Track:**
```
collector_scrapes_total{source, market, status}
collector_scrape_duration_seconds{source, market}
collector_listings_found{source, market}
collector_rate_limit_hits{source}
collector_errors{source, error_type}
```

### 3. Validator (Quality Gates)

**Purpose:** Ensure data meets schema and quality standards before storage

**Validation Layers:**
1. **Schema Validation** - Pydantic models (already built)
2. **Range Validation** - Values within expected bounds
3. **Anomaly Detection** - Flag statistical outliers
4. **Freshness Validation** - Reject stale data
5. **Coverage Validation** - Minimum sample sizes

**Quality Gates:**
```python
class QualityGate:
    min_listings_per_market: int = 20
    max_price_zscore: float = 4.0  # Flag outliers
    max_staleness_hours: int = 48
    min_calendar_coverage: float = 0.3
    required_fields: List[str] = ["listing_id", "bedrooms", "latitude"]
```

### 4. Signal Store (Database)

**Purpose:** Immutable, queryable signal storage with full history

**Schema:**
```sql
-- Core signal table (append-only)
CREATE TABLE signals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    signal_type VARCHAR(50) NOT NULL,
    geo_id VARCHAR(100) NOT NULL,
    property_id UUID,
    source VARCHAR(50) NOT NULL,
    
    value JSONB NOT NULL,
    unit VARCHAR(20),
    
    confidence DECIMAL(3,2) NOT NULL,
    confidence_band DECIMAL(10,2)[] NOT NULL,
    
    decay_half_life_days INTEGER NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    valid_from TIMESTAMPTZ NOT NULL,
    valid_to TIMESTAMPTZ,
    
    metadata JSONB DEFAULT '{}',
    
    -- Audit
    created_at TIMESTAMPTZ DEFAULT NOW(),
    batch_id UUID,  -- Links to scrape batch
    
    -- Indexes
    CONSTRAINT valid_confidence CHECK (confidence >= 0 AND confidence <= 1)
);

-- Indexes for common queries
CREATE INDEX idx_signals_geo_type ON signals(geo_id, signal_type);
CREATE INDEX idx_signals_observed ON signals(observed_at DESC);
CREATE INDEX idx_signals_type_recent ON signals(signal_type, observed_at DESC);

-- Partitioning by month for scale
CREATE TABLE signals_2026_01 PARTITION OF signals
    FOR VALUES FROM ('2026-01-01') TO ('2026-02-01');

-- Materialized view for latest signals per geo
CREATE MATERIALIZED VIEW latest_signals AS
SELECT DISTINCT ON (geo_id, signal_type)
    *
FROM signals
WHERE valid_to IS NULL OR valid_to > NOW()
ORDER BY geo_id, signal_type, observed_at DESC;

-- Refresh periodically
CREATE INDEX idx_latest_signals_geo ON latest_signals(geo_id);
```

### 5. Signal Processor

**Purpose:** Transform raw signals into intelligence

**Processing Steps:**
1. **Decay Calculation** - Apply time-based confidence decay
2. **Aggregation** - Combine signals from multiple sources
3. **Conflict Resolution** - Handle contradictory signals
4. **Bundle Creation** - Package signals for a geo/time scope
5. **Coverage Scoring** - Calculate signal completeness

**Decay Formula:**
```python
def decayed_confidence(signal, as_of):
    days_elapsed = (as_of - signal.observed_at).days
    decay_factor = exp(-0.693 * days_elapsed / signal.decay_half_life_days)
    return signal.confidence * decay_factor
```

### 6. Signal Cache (Redis)

**Purpose:** Fast access to latest signals for real-time queries

**Cache Structure:**
```
signals:{geo_id}:latest → Hash of latest signals
signals:{geo_id}:bundle → Pre-computed SignalBundle
signals:{geo_id}:coverage → Coverage score
signals:refresh_needed → Set of geos needing refresh
```

**TTL Strategy:**
- Latest signals: 1 hour
- Bundles: 15 minutes
- Coverage: 1 hour

### 7. Observability Stack

**Purpose:** Know everything about pipeline health

**Components:**
- **Metrics:** Prometheus + Grafana
- **Logs:** Structured JSON → Loki or CloudWatch
- **Alerts:** PagerDuty/Slack integration
- **Traces:** OpenTelemetry for request tracing

**Key Dashboards:**
1. **Pipeline Health** - Job success rates, latencies
2. **Data Quality** - Validation failures, anomalies
3. **Signal Coverage** - Which markets have fresh data
4. **Confidence Trends** - Are confidence scores degrading?

---

## Data Quality Framework

### Validation Rules

```python
class SignalValidationRules:
    """Rules for validating incoming signals."""
    
    SUPPLY_DENSITY = {
        "min_listings": 1,
        "max_listings": 50000,
        "required_fields": ["listings", "by_platform"],
    }
    
    CALENDAR_COMPRESSION = {
        "min_blocked_pct": 0.0,
        "max_blocked_pct": 1.0,
        "min_sample_size": 10,
    }
    
    RATE_POSITION = {
        "min_rate": 25,
        "max_rate": 10000,
        "min_sample_size": 5,
    }
    
    AMENITY_PREVALENCE = {
        "min_prevalence": 0.0,
        "max_prevalence": 1.0,
        "valid_amenities": ["pool", "hot_tub", "waterfront", "pet_friendly", ...],
    }
```

### Anomaly Detection

```python
class AnomalyDetector:
    """Detect statistical anomalies in signals."""
    
    def __init__(self, lookback_days: int = 30):
        self.lookback_days = lookback_days
    
    def is_anomaly(self, signal: Signal, historical: List[Signal]) -> bool:
        """Check if signal value is anomalous vs history."""
        if len(historical) < 5:
            return False  # Not enough history
        
        values = [s.value for s in historical]
        mean = sum(values) / len(values)
        std = (sum((v - mean) ** 2 for v in values) / len(values)) ** 0.5
        
        if std == 0:
            return False
        
        zscore = abs(signal.value - mean) / std
        return zscore > 3.0  # Flag if > 3 standard deviations
```

### Quarantine Process

```python
class SignalQuarantine:
    """Handle signals that fail validation."""
    
    def quarantine(self, signal: Signal, reason: str):
        """Move signal to quarantine for review."""
        QuarantinedSignal.create(
            signal=signal,
            reason=reason,
            quarantined_at=datetime.utcnow(),
            status="pending_review",
        )
        
        # Alert if too many quarantined
        if self.get_quarantine_rate() > 0.1:  # >10% quarantine rate
            alert("High quarantine rate", severity="warning")
```

---

## Deployment Options

### Option A: Simple (Start Here)
- **Scheduler:** Cron on a single server
- **Database:** PostgreSQL on same server
- **Cache:** Redis on same server
- **Monitoring:** Basic logging + email alerts

**Cost:** ~$50/mo (DigitalOcean droplet)

### Option B: Scalable
- **Scheduler:** Celery + Redis
- **Database:** PostgreSQL (managed, e.g., Supabase)
- **Cache:** Redis (managed)
- **Monitoring:** Grafana Cloud free tier

**Cost:** ~$100-200/mo

### Option C: Enterprise
- **Scheduler:** Temporal.io or Prefect Cloud
- **Database:** PostgreSQL with read replicas
- **Cache:** Redis Cluster
- **Monitoring:** Full Datadog/New Relic

**Cost:** ~$500+/mo

---

## Implementation Priority

### Phase 1: Foundation (Week 1-2)
- [ ] PostgreSQL signal store with schema
- [ ] Basic scheduler (cron)
- [ ] Signal validation pipeline
- [ ] Simple monitoring (logs + alerts)

### Phase 2: Reliability (Week 3-4)
- [ ] Retry logic and dead letter queue
- [ ] Anomaly detection
- [ ] Coverage scoring
- [ ] Grafana dashboards

### Phase 3: Scale (Week 5-8)
- [ ] Celery for job orchestration
- [ ] Redis caching layer
- [ ] Table partitioning
- [ ] Multi-market parallel scraping

### Phase 4: Intelligence (Week 9-12)
- [ ] Signal aggregation engine
- [ ] Confidence decay processing
- [ ] Automated bundle generation
- [ ] API for signal retrieval

---

## Success Metrics

### Pipeline Health
| Metric | Target | Alert Threshold |
|--------|--------|-----------------|
| Scrape success rate | >95% | <90% |
| Validation pass rate | >90% | <80% |
| Signal freshness | <24h | >48h |
| End-to-end latency | <4h | >8h |

### Data Quality
| Metric | Target | Alert Threshold |
|--------|--------|-----------------|
| Coverage score (per market) | >0.8 | <0.6 |
| Confidence score (avg) | >0.7 | <0.5 |
| Anomaly rate | <5% | >10% |
| Quarantine rate | <2% | >5% |

### Business Value
| Metric | Target |
|--------|--------|
| Markets with fresh data | 100% |
| Signal types per market | 10+ |
| Projection confidence | HIGH for 80%+ of requests |

---

## What This Enables

With this infrastructure, you can say:

> "This projection is based on **847 listings** scraped **6 hours ago**, 
> validated against **14 quality rules**, with **92% confidence** 
> based on **signal coverage of 11/12 core signals**. 
> 
> The calendar compression signal shows **67% unavailability** 
> in the next 30 days, which is **+12% vs. the same period last year**.
> 
> All signals are stored immutably with full audit trail."

**That's verifiable intelligence. That's what AirDNA can't do.**
