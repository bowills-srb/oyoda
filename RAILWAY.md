# Railway Deployment Guide
# ========================
#
# This project deploys as THREE Railway services:
#
# 1. API (this repo, railway.toml)
#    - Dockerfile: docker/Dockerfile.api
#    - Start: uvicorn app.main:app
#    - Port: $PORT (Railway sets this automatically)
#
# 2. Worker (this repo, railway-worker.toml)
#    - Dockerfile: docker/Dockerfile.worker
#    - Start: celery worker
#    - No public port needed
#
# 3. Redis (Railway template)
#    - Add from Railway dashboard: New Service → Redis
#    - Copy REDIS_URL into API and Worker env vars
#
# Environment Variables (set in Railway dashboard for each service):
# ------------------------------------------------------------------
# DATABASE_URL      = (from .env — Supabase pooler URL)
# REDIS_URL         = (from Railway Redis service)
# GROQ_API_KEY      = (from .env)
# ENVIRONMENT       = production
# FOCUS_CONCIERGE_ONLY = true
# ENABLE_CONCIERGE_MARKET_SIGNALS = true
# ENABLE_CONCIERGE_HEALTH_CHECKS  = false
# STRICT_STARTUP_CHECKS           = false
# REQUIRED_CONCIERGE_TABLES       = concierge_guest_sessions
# ENABLE_MARKET_INTEL_API         = false
# ENABLE_WATCH_API                = false
# BASE_URL          = https://app.oyvoda.com (after domain is set up)
#
# Deployment / Secret propagation note:
# -------------------------------------
# Set one non-secret revision marker on every Railway service, for example:
# OYVODA_CONFIG_REVISION = 2026-05-29-1
#
# Bump that value whenever you rotate API keys or change env-backed secrets,
# and make sure API, Worker, and Beat all redeploy/restart onto the new value.
# The ops infra summary endpoint now exposes:
# - `deployment_runtime`: the local process snapshot for the API container
# - `deployment_runtime_signals`: the Redis-backed boot payloads for
#   `oyvoda`, `oyvoda-worker`, and `oyvoda-beat`
# This gives us a deterministic way to verify which revision each live service
# actually booted with, even when Railway deploy logs do not surface the
# bootstrap print line reliably.
#
# Railway startup is now guarded by `scripts/railway_bootstrap.py`:
# - boot fails if no config revision marker is set in Railway
# - boot fails if critical secret fingerprints changed but the revision marker did not
# - successful boots write the active revision/fingerprint snapshot to Redis
# This turns secret propagation into an explicit deployment contract instead of
# a silent best-effort assumption.
