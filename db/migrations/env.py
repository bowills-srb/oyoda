"""
Alembic migrations environment.

Uses a synchronous psycopg2 connection so migrations can run
as an explicit pre-deploy step without async complexity.
"""

import os
import sys
from logging.config import fileConfig

from sqlalchemy import Column, MetaData, PrimaryKeyConstraint, String, Table
from sqlalchemy import engine_from_config, pool
from alembic import context
from alembic.ddl.impl import DefaultImpl

# Ensure project root is on path
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, _PROJECT_ROOT)

# Load local dotenv files so `alembic upgrade head` resolves DATABASE_URL /
# ALEMBIC_DATABASE_URL during local development without manual `export`s.
# Real environment variables still win (override=False); `.env` overrides
# `.env.local` to mirror the app's config precedence.
try:
    from dotenv import load_dotenv

    # Load `.env` before `.env.local` so that, with override=False, real
    # overrides in `.env` take precedence over committed `.env.local` defaults.
    for _dotenv_name in (".env", ".env.local"):
        load_dotenv(os.path.join(_PROJECT_ROOT, _dotenv_name), override=False)
except Exception:
    pass

from db.migrations.url_config import resolve_migration_url

# Alembic Config object
config = context.config

# Logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# We don't use autogenerate (no ORM metadata needed for raw SQL migrations)
target_metadata = None
VERSION_TABLE_COLUMN_LENGTH = 64


def _version_table_impl(
    self,
    *,
    version_table: str,
    version_table_schema: str | None,
    version_table_pk: bool,
    **kw,
):
    """Match production's wider alembic_version.version_num column.

    Alembic 1.18 still hardcodes String(32) in DefaultImpl.version_table_impl,
    but this repo uses revision identifiers longer than 32 characters. Fresh
    DB round-trips therefore fail even though production already runs with a
    wider version table column. Override the version-table factory here so
    new environments initialize the same contract production already has.
    """

    vt = Table(
        version_table,
        MetaData(),
        Column("version_num", String(VERSION_TABLE_COLUMN_LENGTH), nullable=False),
        schema=version_table_schema,
    )
    if version_table_pk:
        vt.append_constraint(
            PrimaryKeyConstraint("version_num", name=f"{version_table}_pkc")
        )
    return vt


DefaultImpl.version_table_impl = _version_table_impl


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a live connection."""
    url, _source = resolve_migration_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live database connection."""
    url, _source = resolve_migration_url()

    connectable = engine_from_config(
        {"sqlalchemy.url": url},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        # SSL mode is resolved into the migration URL itself. That keeps
        # production strict by default while still allowing local round-trip
        # harnesses to opt into `sslmode=disable` explicitly.
        connect_args={"connect_timeout": 30},
    )

    # Fresh-DB bootstrap: ensure alembic_version can hold this repo's long
    # revision identifiers (>32 chars). Alembic <1.18 hardcodes VARCHAR(32)
    # when it auto-creates the table, and the DefaultImpl.version_table_impl
    # override above is a no-op on those versions. Pre-create the table wide
    # in its own committed transaction so a clean-database `upgrade head`
    # doesn't truncate the version string mid-run.
    with connectable.connect() as bootstrap_connection:
        bootstrap_connection.exec_driver_sql(
            "CREATE TABLE IF NOT EXISTS alembic_version ("
            f"version_num VARCHAR({VERSION_TABLE_COLUMN_LENGTH}) NOT NULL, "
            "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
        )
        bootstrap_connection.commit()

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
