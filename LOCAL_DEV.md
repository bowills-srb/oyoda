# Local Development (V1.0 prototype)

Run Oyvoda fully locally against PostgreSQL with seeded mock data — **no Twilio,
no Escapia, no Railway, and no external API keys required**.

## Prerequisites

- Python 3.11
- PostgreSQL 14+ with the **pgvector** extension
  (Debian/Ubuntu: `apt-get install postgresql-16-pgvector`)
- *(Optional)* Redis — only needed for the **activity feed** SSE stream
  (`/app/api/v2/realtime`). The operator queue works without it.

## Quick start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. (first time) create the local role + database — needs a postgres superuser
sudo -u postgres psql -c "CREATE ROLE oyvoda WITH LOGIN SUPERUSER PASSWORD 'oyvoda';"
sudo -u postgres psql -c "CREATE DATABASE oyvoda OWNER oyvoda;"

# 3. Migrate schema + seed mock data (idempotent; safe to re-run)
./scripts/setup_local_db.sh

# 4. Run the API
uvicorn app.main:app --reload
# → http://localhost:8000/health   http://localhost:8000/docs
```

`.env.local` (committed, stub values only) is loaded automatically by both the
app and Alembic. Put any **real** secrets in `.env` (gitignored), which
overrides `.env.local`.

## What the seed creates

`scripts/seed_local_dev.py` loads one Gulf Coast (30A) property —
**Sea Glass Cottage** `[BH-SEAGLASS-30A]` — under the default local tenant
`00000000-0000-0000-0000-000000000001`, with:

- structured house rules, check-in instructions, parking, quiet hours, pet/smoking policy
- 11 concierge knowledge Q&A entries (house rules, FAQs, check-in) in `concierge_scoped_knowledge`
- 4 conversations at different lifecycle stages:
  1. **Pre-booking inquiry** (AI-drafted, pending review) — `pre_booking_inquiries`
  2. **Booked / pre-arrival** session — `concierge_guest_sessions`
  3. **Active stay + maintenance issue** (AC) — session + messages
  4. **Escalated complaint** (no hot water) — session + `concierge_escalations` ticket (priority=high)

Re-run any time: `python scripts/seed_local_dev.py` (wipes + recreates only this
demo property). `--wipe` removes it.

## The two endpoints the frontend needs first

| Purpose | Method + path | Notes |
|---|---|---|
| **Operator queue** | `GET /app/api/messages` | Unified queue: pre-booking inquiries + guest sessions + escalations. `stage` = `all\|pre_booking\|booked\|in_stay\|post_stay\|escalations`; `status` = `all\|pending_review\|replied\|rejected`. |
| **Activity feed** | `GET /app/api/v2/realtime` | Server-Sent Events stream (`summary.updated`, `inquiry.sent`, …). **Requires Redis.** |

Both authenticate via an `oyvoda_access` JWT cookie (operator session).

## Notes / gotchas

- Migrations target `db/migrations` (`alembic -c alembic.ini upgrade head`). A few
  migrations carry production data-guards that don't fit an empty database
  (072 wants embeddings; 088 wants a legacy-table archive). `setup_local_db.sh`
  satisfies those automatically — don't bypass it for a fresh DB.
- The app's runtime URL uses the **asyncpg** driver (no `sslmode`); Alembic uses
  the **psycopg2** driver with `sslmode=disable` for local Postgres. Both are
  preconfigured in `.env.local`.
