# Schema Migration Policy

**Status:** Active. Adopted 2026-05-06.
**Scope:** All schema changes (tables, columns, indexes, constraints, enums) on the Oyvoda Postgres database.

## TL;DR

> **Every schema change goes through Alembic. Period.**
>
> Path: `db/migrations/versions/NNN_short_name.py`. Numbered sequentially. Each migration has a real `upgrade()` and `downgrade()` (or a documented reason it can't be reversed).

If you're about to write `CREATE TABLE`, `ALTER TABLE`, `CREATE INDEX`, or `DROP …` anywhere outside of `db/migrations/versions/`, stop. That work belongs in a new Alembic migration.

## Why this policy exists

Oyvoda has accumulated a hybrid pattern: most of the schema lives in proper Alembic migrations under `db/migrations/versions/` (50+ files, sequenced 001 through 054 plus a merge), but several service modules also carry inline `MIGRATION_SQL` constants and `run_migration(db)` helpers that mutate schema at runtime via `IF NOT EXISTS` guards. Examples found at the time of writing:

- `app/services/integrations/gmail_inbox_poller.py` — `MIGRATION_SQL` constant and `run_gmail_migration(db)` for `gmail_processed_messages` and `pre_booking_inquiries` columns; runtime `ALTER TABLE` calls in `_record_poll_heartbeat`.
- `app/services/concierge/pre_booking_handler.py` — its own `MIGRATION_SQL` constant.
- Likely other modules following the same pattern.

The hybrid is the problem, not Alembic. Alembic is the system of record. The inline migration helpers are the deviation, and they cause:

- **No single answer to "what's the schema?"** — you have to grep service code to find columns and indexes.
- **No ordering or dependency graph** — a runtime helper that adds column X has no way to encode "must run after migration Y."
- **Idempotent `IF NOT EXISTS` everywhere** — defensive code papering over the lack of authoritative schema.
- **Runtime introspection** (e.g. `_table_columns()` in `operator_prebooking.py`) — service code adapting queries to whatever columns happen to exist, because the schema isn't known.
- **Schema drift between environments goes invisible** — until something breaks at the wrong time.

This policy stops the bleeding. It does not require a giant retroactive cleanup.

## Going forward (mandatory)

For **all new schema changes**:

1. Create a new file under `db/migrations/versions/` named `NNN_short_name.py` where `NNN` is the next sequential number after the current head.
2. The file follows the existing Alembic format (see `054_message_normalizations_composer_metadata.py` for a clean example):

   ```python
   """NNN_short_name

   One-line description. Optional longer description.
   """

   from alembic import op


   revision = "NNN_short_name"
   down_revision = "<previous_revision_id>"
   branch_labels = None
   depends_on = None


   UP_SQL = """
   -- your forward migration here
   """

   DOWN_SQL = """
   -- your reverse migration here, or a documented reason it's irreversible
   """


   def upgrade() -> None:
       op.execute(UP_SQL)


   def downgrade() -> None:
       op.execute(DOWN_SQL)
   ```

   For column adds you can also use `op.add_column(...)` directly instead of raw SQL — see `054_message_normalizations_composer_metadata.py`. Either style is fine; consistency within a single migration matters more than which style.

3. Run the migration locally (`alembic upgrade head`) and on each environment as a deploy step. Alembic's `alembic_version` table tracks which migrations have run, so re-running is a no-op.

4. Service code stops doing inline `CREATE TABLE`/`ALTER TABLE`/`CREATE INDEX`. Those go into the migration file.

5. Service code stops doing runtime schema introspection (`_table_columns()`, `COALESCE` over possibly-missing columns) for **new** features. The schema is known; the code can rely on it.

## What about existing inline migrations?

**Don't touch them right now.** They've already run in production. Rewriting how they were authored doesn't help anyone — only changes for new work matter. The existing `MIGRATION_SQL` constants in `gmail_inbox_poller.py`, `pre_booking_handler.py`, etc. continue to work as they always have. Their idempotent `IF NOT EXISTS` guards make re-running safe.

Over time, as you naturally touch each module for other work, you can pull its inline migration into a properly-numbered Alembic file as a dedicated cleanup commit. Not blocking; just on the list. A focused multi-session "consolidate inline migrations" project is a reasonable separate effort whenever someone has appetite for it.

## Alembic configuration in this repo

- Config: `alembic.ini` at the repo root.
- Script location: `db/migrations/` (not `alembic/versions/` — that path was abandoned and the single file there is a leftover artifact).
- Migration env: `db/migrations/env.py` (synchronous psycopg2 connection, no autogenerate).
- DB URL: resolved via `db/migrations/url_config.resolve_migration_url()` from environment variables, not hardcoded.

The `migrations/` directory at the repo root (with `002_add_location_tier.sql`, `014_agent_architecture.sql`, `015_experiment_assignments.sql`) is also legacy — those are not the active migration system. Do not add files there.

## Edge cases

- **Hot fixes in production** that need a column right now and can't wait for a deploy: still write the Alembic migration. Run it manually against production via `alembic upgrade head` from a console session pointed at the prod URL. Do not run inline `ALTER TABLE` from service code as a workaround.
- **Backfills that take a long time** (rewriting millions of rows): the schema change goes in Alembic. The data backfill can be a separate migration or a one-time job. Don't conflate them.
- **Tenant-scoped or feature-flagged schema** is a smell — Postgres schemas should be the same across tenants. If you find yourself wanting per-tenant columns, the right answer is usually a JSONB column (`extra`, `settings`, `metadata`) that Alembic creates once.
- **Auto-generated tables from ORM frameworks** (e.g. SQLAlchemy `metadata.create_all()`): not used in this repo. If you're tempted to introduce it, write an Alembic migration instead.

## Why this is worth the discipline

For a codebase aiming at 1000-unit operators and beyond, the schema is the contract between every part of the system. When the contract is fragmented across service modules, every new feature becomes harder, every audit takes longer, and every operator question about data takes a grep instead of a glance at one directory.

Alembic is already 95% of the way there. This policy closes the last 5%.
