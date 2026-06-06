# RentalRevenue.ai Platform

A B2B SaaS backend platform for vacation rental property management companies that provides:

- **Automated Pro Forma Generation** - Generate rental revenue projections for prospective listings
- **AI-Powered Pricing Intelligence** - Dynamic rate recommendations based on market data
- **Operational Analytics** - Insights to streamline property management operations
- **Business Development Automation** - Workflows to accelerate listing acquisition

## Architecture Overview

```
rental-revenue-platform/
├── app/
│   ├── api/                    # API routes and endpoints
│   │   ├── v1/
│   │   │   ├── properties.py
│   │   │   ├── proformas.py
│   │   │   ├── markets.py
│   │   │   ├── companies.py
│   │   │   └── ai_advisor.py
│   │   └── dependencies.py
│   │
│   ├── core/                   # Core configuration and utilities
│   │   ├── config.py
│   │   ├── security.py
│   │   └── exceptions.py
│   │
│   ├── models/                 # SQLAlchemy ORM models
│   │   ├── base.py
│   │   ├── company.py
│   │   ├── property.py
│   │   ├── market.py
│   │   ├── proforma.py
│   │   └── pricing.py
│   │
│   ├── schemas/                # Pydantic schemas for validation
│   │   ├── property.py
│   │   ├── proforma.py
│   │   ├── market.py
│   │   └── common.py
│   │
│   ├── services/               # Business logic services
│   │   ├── property_service.py
│   │   ├── proforma_engine.py
│   │   ├── pricing_engine.py
│   │   ├── market_data_service.py
│   │   ├── comp_matcher.py
│   │   └── ai_advisor.py
│   │
│   ├── integrations/           # External service integrations
│   │   ├── mls/
│   │   ├── pms/
│   │   └── market_data/
│   │
│   ├── workers/                # Background job processors
│   │   ├── proforma_generator.py
│   │   ├── market_data_sync.py
│   │   └── listing_monitor.py
│   │
│   └── main.py                 # FastAPI application entry point
│
├── alembic/                    # Database migrations
├── tests/                      # Test suite
├── docker/                     # Docker configurations
├── docs/                       # API documentation
├── requirements.txt
├── docker-compose.yml
└── .env.example
```

## Tech Stack

- **Framework**: FastAPI (Python 3.11+)
- **Database**: PostgreSQL 15+ with TimescaleDB extension
- **Cache**: Redis
- **Task Queue**: Celery with Redis broker
- **AI/ML**: OpenAI API, scikit-learn, custom models
- **Vector Store**: pgvector (PostgreSQL extension)
- **Containerization**: Docker & Docker Compose

## Domain Model

### Core Entities

1. **Company** - Property management company (tenant)
2. **Market** - Geographic market/submarket definitions
3. **Property** - Individual rental properties
4. **ProForma** - Revenue projection documents
5. **Season** - Seasonal pricing periods
6. **RateTable** - Pricing matrices by property type/season
7. **HistoricalPerformance** - Actual rental performance data
8. **Comparable** - Property comparison records

## Quick Start

```bash
# Clone and setup
git clone <repo>
cd rental-revenue-platform

# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Setup environment
cp .env.example .env
# Edit .env with your configuration

# Run database migrations before starting the app
alembic -c alembic.ini upgrade head

# Start the development server
uvicorn app.main:app --reload

# Start Celery worker (separate terminal)
celery -A app.workers worker --loglevel=info
```

## Schema Management

Database schema is owned by Alembic under `db/migrations/`.
Do not rely on application startup to create or alter tables.

For local dev and deploys, run:

```bash
alembic -c alembic.ini upgrade head
```

Recommended production setup:
- `DATABASE_URL`: application runtime connection
- `ALEMBIC_DATABASE_URL`: dedicated migration connection
- `ALEMBIC_USE_DIRECT_URL=true`: only if you explicitly want Alembic to rewrite a
  Supabase-style pooler URL from port `6543` to direct Postgres on `5432`

## API Documentation

Once running, access the API docs at:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## License

Proprietary - All Rights Reserved
