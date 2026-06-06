# Concierge Scaling Runbook

## What was added

- PgBouncer in front of Postgres (`pgbouncer:6432`) with transaction pooling.
- Multi-worker API process model (`API_WORKERS`, default 4).
- Queue-isolated Celery workers:
  - `concierge` queue worker (`CELERY_CONCIERGE_CONCURRENCY`, default 16)
  - `ingestion` queue worker (`CELERY_INGESTION_CONCURRENCY`, default 6)
  - `operations` queue worker (`CELERY_OPERATIONS_CONCURRENCY`, default 4)
  - dedicated `celery-beat`
- Observability stack:
  - Prometheus (`:9090`) scraping `/metrics`
  - Grafana (`:3000`) with auto-provisioned concierge SLO dashboard
  - PgBouncer exporter (`:9127`)

## Startup

```bash
docker compose up -d db pgbouncer redis api celery-worker-concierge celery-worker-ingestion celery-worker-operations celery-beat prometheus grafana pgbouncer-exporter
```

## API scale-out

For horizontal scale of API containers:

```bash
docker compose up -d --scale api=3
```

## Operator dashboard metrics

The operator dashboard now reads `/api/v1/agents/slo/summary` and displays:

- API error rate vs threshold
- Empty retrieval rate vs threshold
- Open escalations vs threshold
- Active sessions
- SLO breach count
- Runtime 5xx count

The operator dashboard now also reads `/api/v1/agents/infra/summary` and displays:

- PgBouncer up/down + version
- PgBouncer waiting/active client pressure
- Redis/Celery queue depth (concierge/ingestion/operations)
- Celery workers online
- PgBouncer exporter up/down

## Threshold controls

Tune in `.env`:

- `SLO_API_LATENCY_MS_THRESHOLD`
- `SLO_KNOWLEDGE_LATENCY_MS_THRESHOLD`
- `SLO_VOICE_LATENCY_MS_THRESHOLD`
- `SLO_EMPTY_RETRIEVAL_RATE_THRESHOLD`
- `SLO_ERROR_RATE_THRESHOLD`
- `SLO_ESCALATION_BACKLOG_THRESHOLD`

## Alert rules

Prometheus loads alert rules from:

- `docs/concierge_alert_rules.yml`
