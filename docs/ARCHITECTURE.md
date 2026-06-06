# RentalRevenue.ai - System Architecture

## Overview

RentalRevenue.ai is a B2B SaaS platform for vacation rental property management companies that provides intelligent business development tools, AI-powered pricing optimization, and operational analytics.

---

## Core Architectural Principles

1. **Multi-Tenant Isolation** - Complete data separation between property management companies
2. **Event-Driven Processing** - Detectors and analyzers respond to data changes in real-time
3. **Agent-Based AI** - Specialized AI agents handle discrete tasks with orchestration
4. **Secure by Design** - Encryption at rest and in transit, tenant-isolated integrations
5. **Geographic Intelligence** - Geofencing for market focus and opportunity discovery
6. **Data Normalization** - Unified schema regardless of data source

---

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                                   CLIENT LAYER                                       │
├─────────────────────┬─────────────────────┬─────────────────────┬───────────────────┤
│   Web Dashboard     │    Mobile App       │    Voice AI         │   API Clients     │
│   (React/Next.js)   │    (React Native)   │    (Twilio/VAPI)    │   (REST/GraphQL)  │
└─────────────────────┴─────────────────────┴─────────────────────┴───────────────────┘
                                            │
                                            ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              API GATEWAY & SECURITY                                  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                │
│  │   Auth      │  │   Rate      │  │   Request   │  │   Tenant    │                │
│  │   (JWT)     │  │   Limiting  │  │   Routing   │  │   Isolation │                │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘                │
└─────────────────────────────────────────────────────────────────────────────────────┘
                                            │
        ┌───────────────────────────────────┼───────────────────────────────────┐
        ▼                                   ▼                                   ▼
┌───────────────────┐           ┌───────────────────────┐           ┌───────────────────┐
│  CORE SERVICES    │           │    INTELLIGENCE       │           │   INTEGRATION     │
│                   │           │    LAYER              │           │   LAYER           │
│ • Property Svc    │           │                       │           │                   │
│ • ProForma Svc    │           │ ┌───────────────────┐ │           │ • MLS Connectors  │
│ • Market Svc      │           │ │  DETECTOR ENGINE  │ │           │ • PMS Adapters    │
│ • Company Svc     │           │ │                   │ │           │ • OTA Sync        │
│ • User Svc        │           │ │ • New Listing     │ │           │ • Market Data     │
│ • Geofencing Svc  │           │ │ • Price Change    │ │           │ • Voice Platform  │
│                   │           │ │ • Occupancy Shift │ │           │                   │
│                   │           │ │ • Booking Pattern │ │           │ ┌───────────────┐ │
│                   │           │ │ • Market Anomaly  │ │           │ │ SECURE VAULT  │ │
│                   │           │ └───────────────────┘ │           │ │               │ │
│                   │           │          │            │           │ │ • Encrypted   │ │
│                   │           │          ▼            │           │ │   Storage     │ │
│                   │           │ ┌───────────────────┐ │           │ │ • Tenant      │ │
│                   │           │ │  ANALYZER ENGINE  │ │           │ │   Isolated    │ │
│                   │           │ │                   │ │           │ │ • Custom      │ │
│                   │           │ │ • Comp Analysis   │ │           │ │   Workflows   │ │
│                   │           │ │ • Trend Detection │ │           │ └───────────────┘ │
│                   │           │ │ • Revenue Predict │ │           │                   │
│                   │           │ │ • Demand Forecast │ │           │                   │
│                   │           │ └───────────────────┘ │           │                   │
└───────────────────┘           └───────────────────────┘           └───────────────────┘
        │                                   │                                   │
        └───────────────────────────────────┼───────────────────────────────────┘
                                            ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              AI AGENT ORCHESTRATION                                  │
│                                                                                      │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌───────────┐ │
│  │  Pricing    │  │  Market     │  │  Lead       │  │  Voice      │  │  Report   │ │
│  │  Agent      │  │  Intel      │  │  Qualifier  │  │  Assistant  │  │  Writer   │ │
│  │             │  │  Agent      │  │  Agent      │  │  Agent      │  │  Agent    │ │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘  └───────────┘ │
│         │                │                │                │               │        │
│         └────────────────┴────────────────┴────────────────┴───────────────┘        │
│                                           │                                          │
│                              ┌────────────▼────────────┐                            │
│                              │   AGENT ORCHESTRATOR    │                            │
│                              │   (Task Routing, State  │                            │
│                              │    Management, Memory)  │                            │
│                              └─────────────────────────┘                            │
└─────────────────────────────────────────────────────────────────────────────────────┘
                                            │
                                            ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                           DATA NORMALIZATION LAYER                                   │
│                                                                                      │
│  ┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐              │
│  │  INGESTION       │    │  TRANSFORMATION  │    │  VALIDATION      │              │
│  │                  │    │                  │    │                  │              │
│  │ • MLS Feeds      │───▶│ • Schema Mapping │───▶│ • Data Quality   │              │
│  │ • PMS Exports    │    │ • Unit Convert   │    │ • Deduplication  │              │
│  │ • API Responses  │    │ • Enrichment     │    │ • Completeness   │              │
│  │ • Manual Uploads │    │ • Geocoding      │    │ • Consistency    │              │
│  └──────────────────┘    └──────────────────┘    └──────────────────┘              │
│                                                            │                        │
│                                      ┌─────────────────────▼─────────────────────┐  │
│                                      │      UNIFIED CANONICAL SCHEMA            │  │
│                                      │  (Normalized Property, Market, Booking)  │  │
│                                      └───────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────────────┘
                                            │
                                            ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                                  DATA LAYER                                          │
│                                                                                      │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌───────────┐ │
│  │ PostgreSQL  │  │ TimescaleDB │  │    Redis    │  │  pgvector   │  │   S3      │ │
│  │ (Core Data) │  │ (Time Series│  │  (Cache +   │  │  (Embedding │  │  (Files   │ │
│  │             │  │  + Hypertab)│  │   Pub/Sub)  │  │   Search)   │  │   Vault)  │ │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘  └───────────┘ │
└─────────────────────────────────────────────────────────────────────────────────────┘
                                            │
                                            ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                          EVENT BUS & WORKFLOW ENGINE                                 │
│                                                                                      │
│  ┌─────────────────────────────────┐    ┌─────────────────────────────────┐        │
│  │         Apache Kafka            │    │         Temporal.io             │        │
│  │   (Event Streaming, CDC)        │    │   (Workflow Orchestration)      │        │
│  └─────────────────────────────────┘    └─────────────────────────────────┘        │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

---

## Component Deep Dives

### 1. Detector Engine

Detectors are event-driven components that monitor data changes and trigger appropriate actions.

```python
# Detector Types
DETECTORS = {
    "new_listing_detector": {
        "triggers": ["MLS feed update", "Manual entry", "PMS sync"],
        "actions": ["Qualify lead", "Generate pro forma", "Assign to BD rep"],
        "conditions": ["Within geofence", "Meets criteria"]
    },
    "price_change_detector": {
        "triggers": ["Competitor rate change", "Market benchmark update"],
        "actions": ["Alert pricing agent", "Recommend adjustment"],
        "conditions": ["Change > threshold", "Within monitoring period"]
    },
    "occupancy_shift_detector": {
        "triggers": ["Booking made", "Cancellation", "Block added"],
        "actions": ["Update availability", "Trigger gap-fill pricing"],
        "conditions": ["Significant change", "High-value period"]
    },
    "booking_pattern_detector": {
        "triggers": ["New booking", "Time elapsed"],
        "actions": ["Update demand forecast", "Adjust pricing strategy"],
        "conditions": ["Pattern deviation", "Seasonal comparison"]
    },
    "market_anomaly_detector": {
        "triggers": ["Benchmark update", "Competitive intelligence"],
        "actions": ["Alert market intel agent", "Generate report"],
        "conditions": ["Statistical outlier", "Trend reversal"]
    }
}
```

### 2. Analyzer Engine

Analyzers perform complex analytical computations triggered by detectors or on-demand.

| Analyzer | Purpose | Inputs | Outputs |
|----------|---------|--------|---------|
| **Comp Analyzer** | Find and score comparable properties | Property attributes, location | Ranked comp list with similarity scores |
| **Trend Analyzer** | Identify market trends | Historical data, benchmarks | Trend direction, magnitude, confidence |
| **Revenue Predictor** | Forecast property revenue | Property, market, seasonality | Monthly/annual projections with ranges |
| **Demand Forecaster** | Predict booking demand | Historical bookings, events, weather | Demand curve by date |
| **Discount Optimizer** | Calculate optimal discounts | Current price, demand, history | Recommended discount with rationale |

### 3. Secure Integration Vault

Tenant-isolated secure storage for sensitive business data and custom workflows.

```yaml
Secure Vault Features:
  Encryption:
    - At-rest: AES-256 encryption per tenant
    - In-transit: TLS 1.3
    - Key management: AWS KMS with tenant-specific keys
  
  Isolation:
    - Logical: Row-level security in PostgreSQL
    - Physical: Separate S3 buckets per enterprise tenant
    - Network: VPC isolation for enterprise tier
  
  Data Types Supported:
    - Custom rate tables (proprietary pricing)
    - Owner contracts (PDF, sensitive terms)
    - Business workflows (JSON workflow definitions)
    - Historical performance (competitive advantage)
    - Custom integrations (API keys, credentials)
  
  Access Control:
    - Role-based access within tenant
    - Audit logging for all access
    - Time-limited access tokens for integrations
```

### 4. AI Agent Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                      AGENT ORCHESTRATOR                              │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │                    Task Router                               │    │
│  │  • Analyzes incoming request                                 │    │
│  │  • Determines required agents                                │    │
│  │  • Manages agent collaboration                               │    │
│  │  • Aggregates results                                        │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                              │                                       │
│         ┌────────────────────┼────────────────────┐                 │
│         ▼                    ▼                    ▼                 │
│  ┌─────────────┐      ┌─────────────┐      ┌─────────────┐         │
│  │  PRICING    │      │  MARKET     │      │   LEAD      │         │
│  │  AGENT      │      │  INTEL      │      │  QUALIFIER  │         │
│  │             │      │  AGENT      │      │  AGENT      │         │
│  │ Capabilities│      │ Capabilities│      │ Capabilities│         │
│  │ • Rate calc │      │ • Trend ID  │      │ • Score     │         │
│  │ • Discount  │      │ • Comp find │      │ • Prioritize│         │
│  │ • Optimize  │      │ • Benchmark │      │ • Qualify   │         │
│  │ • Forecast  │      │ • Report    │      │ • Route     │         │
│  └─────────────┘      └─────────────┘      └─────────────┘         │
│         │                    │                    │                 │
│         ▼                    ▼                    ▼                 │
│  ┌─────────────┐      ┌─────────────┐      ┌─────────────┐         │
│  │   VOICE     │      │  REPORT     │      │  OPERATIONS │         │
│  │  ASSISTANT  │      │  WRITER     │      │  ADVISOR    │         │
│  │  AGENT      │      │  AGENT      │      │  AGENT      │         │
│  │             │      │             │      │             │         │
│  │ Capabilities│      │ Capabilities│      │ Capabilities│         │
│  │ • Guest Q&A │      │ • Pro forma │      │ • Schedule  │         │
│  │ • Owner Q&A │      │ • Analysis  │      │ • Resource  │         │
│  │ • Booking   │      │ • Summary   │      │ • Workflow  │         │
│  │ • Support   │      │ • Narrative │      │ • Optimize  │         │
│  └─────────────┘      └─────────────┘      └─────────────┘         │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                    Shared Context Store                      │   │
│  │  • Conversation history    • User preferences               │   │
│  │  • Property context        • Market context                 │   │
│  │  • Decision rationale      • Audit trail                    │   │
│  └─────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

#### Agent Definitions

**Pricing Agent**
```python
PricingAgent:
  role: "Dynamic pricing optimization specialist"
  capabilities:
    - Calculate optimal nightly rates
    - Determine context-aware discounts
    - Forecast revenue impact of pricing changes
    - Detect pricing opportunities (gaps, last-minute, length-of-stay)
  
  tools:
    - rate_calculator
    - demand_forecaster
    - competitor_analyzer
    - historical_pattern_matcher
  
  constraints:
    - Never discount below owner minimum
    - Consider historical demand patterns (e.g., 4th of July)
    - Factor in booking velocity and lead time
    - Account for market supply/demand dynamics
```

**Voice Assistant Agent**
```python
VoiceAssistantAgent:
  role: "Conversational interface for guests, owners, and staff"
  capabilities:
    - Answer property questions
    - Provide availability and pricing
    - Handle booking inquiries
    - Route complex requests to humans
  
  integrations:
    - Twilio Voice
    - VAPI
    - ElevenLabs (voice synthesis)
  
  context_awareness:
    - Property details and amenities
    - Current availability calendar
    - Pricing rules and restrictions
    - Guest/owner history
```

### 5. Geofencing Engine

```python
GeofencingEngine:
  purpose: "Define and monitor geographic boundaries for market focus"
  
  features:
    boundary_definition:
      - Polygon drawing (GeoJSON)
      - Radius from point
      - ZIP code aggregation
      - County/city selection
      - Custom MLS area codes
    
    monitoring:
      - New listing alerts within fence
      - Competitor activity tracking
      - Market metric changes
      - Price movement detection
    
    filtering:
      - Property search within bounds
      - Comp selection by geography
      - Market data aggregation
      - Lead prioritization by location
  
  data_structure:
    Geofence:
      id: UUID
      company_id: UUID
      name: string
      geometry: GeoJSON Polygon
      buffer_miles: float (optional expansion)
      monitoring_enabled: boolean
      alert_preferences: JSON
```

### 6. Data Normalization Layer

The normalization layer ensures all data from disparate sources is transformed into a unified canonical schema.

```
┌─────────────────────────────────────────────────────────────────────┐
│                    DATA NORMALIZATION PIPELINE                       │
│                                                                      │
│  ┌────────────┐                                                     │
│  │   SOURCE   │                                                     │
│  │   DATA     │                                                     │
│  │            │                                                     │
│  │ • MLS Feed │     ┌──────────────────────────────────────────┐   │
│  │ • PMS API  │────▶│            SOURCE ADAPTERS               │   │
│  │ • OTA Sync │     │                                          │   │
│  │ • CSV      │     │  ┌──────────┐ ┌──────────┐ ┌──────────┐ │   │
│  │ • Manual   │     │  │ MLS      │ │ Guesty   │ │ Airbnb   │ │   │
│  └────────────┘     │  │ Adapter  │ │ Adapter  │ │ Adapter  │ │   │
│                     │  └──────────┘ └──────────┘ └──────────┘ │   │
│                     └──────────────────────────────────────────┘   │
│                                        │                            │
│                                        ▼                            │
│                     ┌──────────────────────────────────────────┐   │
│                     │         FIELD MAPPING ENGINE             │   │
│                     │                                          │   │
│                     │  Source Field      →    Canonical Field  │   │
│                     │  ─────────────────────────────────────── │   │
│                     │  "num_beds"        →    bedrooms         │   │
│                     │  "bedrooms"        →    bedrooms         │   │
│                     │  "BedroomCount"    →    bedrooms         │   │
│                     │  "sqft"            →    square_footage   │   │
│                     │  "living_area"     →    square_footage   │   │
│                     └──────────────────────────────────────────┘   │
│                                        │                            │
│                                        ▼                            │
│                     ┌──────────────────────────────────────────┐   │
│                     │         TRANSFORMATION ENGINE            │   │
│                     │                                          │   │
│                     │  • Unit conversion (sqm → sqft)          │   │
│                     │  • Currency normalization                │   │
│                     │  • Date/time standardization (UTC)       │   │
│                     │  • Address parsing & standardization     │   │
│                     │  • Amenity taxonomy mapping              │   │
│                     │  • Geocoding (address → lat/lng)         │   │
│                     └──────────────────────────────────────────┘   │
│                                        │                            │
│                                        ▼                            │
│                     ┌──────────────────────────────────────────┐   │
│                     │          ENRICHMENT ENGINE               │   │
│                     │                                          │   │
│                     │  • Walk score lookup                     │   │
│                     │  • Beach/ski distance calculation        │   │
│                     │  • School district mapping               │   │
│                     │  • POI proximity (restaurants, shops)    │   │
│                     │  • Flood zone / hazard data              │   │
│                     └──────────────────────────────────────────┘   │
│                                        │                            │
│                                        ▼                            │
│                     ┌──────────────────────────────────────────┐   │
│                     │         VALIDATION & QA ENGINE           │   │
│                     │                                          │   │
│                     │  • Required field checks                 │   │
│                     │  • Data type validation                  │   │
│                     │  • Range checks (e.g., bedrooms 1-20)    │   │
│                     │  • Duplicate detection                   │   │
│                     │  • Anomaly flagging                      │   │
│                     │  • Confidence scoring                    │   │
│                     └──────────────────────────────────────────┘   │
│                                        │                            │
│                                        ▼                            │
│                     ┌──────────────────────────────────────────┐   │
│                     │       CANONICAL DATA STORE               │   │
│                     │                                          │   │
│                     │  Unified schema with:                    │   │
│                     │  • source_id (original ID)               │   │
│                     │  • source_system (where it came from)    │   │
│                     │  • normalized_at (timestamp)             │   │
│                     │  • confidence_score (data quality)       │   │
│                     │  • raw_data (original JSON preserved)    │   │
│                     └──────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

### 7. Dynamic Discount Engine

The discount engine considers multiple factors to provide intelligent, context-aware pricing recommendations.

```python
DiscountEngine:
  inputs:
    - current_rate: float
    - property: Property
    - target_date: date
    - booking_window: int  # days until check-in
    - current_occupancy: float  # market occupancy
    - historical_data: HistoricalDemand
  
  decision_factors:
    historical_patterns:
      weight: 0.30
      description: "What happened this time last year?"
      examples:
        - "4th of July historically 95% booked 6 months out → NO DISCOUNT"
        - "Random Tuesday in October historically 20% booked → CONSIDER DISCOUNT"
    
    booking_velocity:
      weight: 0.25
      description: "How fast are bookings coming in for this period?"
      examples:
        - "Bookings ahead of pace vs last year → HOLD PRICE"
        - "Bookings behind pace → GRADUATED DISCOUNT"
    
    market_supply:
      weight: 0.20
      description: "What's the competitive landscape?"
      examples:
        - "Low inventory in market → HOLD/INCREASE PRICE"
        - "High inventory, low demand → DISCOUNT TO COMPETE"
    
    days_until_checkin:
      weight: 0.15
      description: "Last-minute discounting curve"
      examples:
        - "> 90 days: No discount"
        - "30-90 days: Up to 10% if below pace"
        - "7-30 days: Up to 20% for gaps"
        - "< 7 days: Up to 30% for true last-minute"
    
    length_of_stay:
      weight: 0.10
      description: "Incentivize longer bookings"
      examples:
        - "7+ nights: 10% discount"
        - "14+ nights: 15% discount"
        - "30+ nights: 20% discount"
  
  constraints:
    - never_below_owner_minimum: true
    - never_discount_peak_season_early: true
    - require_human_approval_above: 0.25  # 25% discount needs approval
    - blackout_dates: [holidays, events]
  
  output:
    recommended_discount: float
    confidence: float
    rationale: string
    comparable_rates: list[CompRate]
    historical_context: string
```

---

## Database Schema Overview

### Core Tables
- `companies` - Tenant organizations
- `users` - User accounts (per tenant)
- `properties` - Rental properties
- `markets` - Geographic market definitions
- `geofences` - Custom geographic boundaries

### Pricing Tables
- `season_definitions` - Seasonal periods per market
- `rate_tables` - Base rates by property type/season
- `pricing_rules` - Dynamic pricing rules
- `discount_history` - Audit trail of discounts applied

### Analytics Tables
- `property_performance` - Historical performance data
- `market_benchmarks` - Market-level metrics over time
- `detector_events` - Events triggered by detectors
- `analyzer_results` - Cached analysis results

### Integration Tables
- `integration_configs` - External system configurations
- `sync_logs` - Integration sync history
- `normalized_imports` - Staging for normalized data
- `secure_vault_items` - Encrypted tenant data

### AI Tables
- `agent_sessions` - AI agent conversation history
- `agent_decisions` - Logged agent decisions with rationale
- `embeddings` - Vector embeddings for semantic search

---

## Security Model

### Multi-Tenant Isolation

```sql
-- Row Level Security Example
CREATE POLICY tenant_isolation ON properties
  USING (company_id = current_setting('app.current_company_id')::uuid);

-- All queries automatically filtered by tenant
SET app.current_company_id = 'tenant-uuid-here';
SELECT * FROM properties;  -- Only returns tenant's properties
```

### Encryption Strategy

| Data Type | At Rest | In Transit | Key Management |
|-----------|---------|------------|----------------|
| Standard data | AES-256 (DB) | TLS 1.3 | Shared key |
| Sensitive (vault) | AES-256 (per-tenant) | TLS 1.3 | Tenant-specific KMS |
| API credentials | AES-256 + envelope | TLS 1.3 | Tenant-specific KMS |
| PII | AES-256 + tokenization | TLS 1.3 | Dedicated PII key |

---

## Deployment Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         AWS / GCP / Azure                            │
│                                                                      │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐     │
│  │   Load          │  │   CDN           │  │   WAF           │     │
│  │   Balancer      │  │   (CloudFront)  │  │   (Shield)      │     │
│  └────────┬────────┘  └─────────────────┘  └─────────────────┘     │
│           │                                                         │
│           ▼                                                         │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                    Kubernetes Cluster                        │   │
│  │                                                              │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       │   │
│  │  │ API Pods │ │ Worker   │ │ Agent    │ │ Voice    │       │   │
│  │  │ (FastAPI)│ │ Pods     │ │ Pods     │ │ Pods     │       │   │
│  │  │ HPA: 2-20│ │ HPA: 2-10│ │ HPA: 2-5 │ │ HPA: 2-10│       │   │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘       │   │
│  └─────────────────────────────────────────────────────────────┘   │
│           │                                                         │
│           ▼                                                         │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                    Managed Services                          │   │
│  │                                                              │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       │   │
│  │  │ RDS      │ │ Elastic- │ │ Redis    │ │ S3       │       │   │
│  │  │ Postgres │ │ Cache    │ │ Cluster  │ │ Buckets  │       │   │
│  │  │ +Timescl │ │          │ │          │ │          │       │   │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘       │   │
│  │                                                              │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐                    │   │
│  │  │ MSK      │ │ Secrets  │ │ KMS      │                    │   │
│  │  │ (Kafka)  │ │ Manager  │ │          │                    │   │
│  │  └──────────┘ └──────────┘ └──────────┘                    │   │
│  └─────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Next Steps

1. **Phase 1**: Core platform (Properties, Markets, Pro Forma generation)
2. **Phase 2**: Integration layer (MLS, PMS connectors) + Normalization
3. **Phase 3**: Geofencing + Detector engine
4. **Phase 4**: AI Agent framework + Voice assistant
5. **Phase 5**: Advanced analytics + Dynamic discount engine
