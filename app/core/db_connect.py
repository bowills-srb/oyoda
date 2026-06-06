"""
Shared helpers for async PostgreSQL connections.

Centralizes connection settings required when talking to Supabase/pgbouncer
from SQLAlchemy async engines and raw asyncpg pools.
"""

from __future__ import annotations

import inspect
import logging
import os
import socket
import ssl
from typing import Any, Dict
from uuid import uuid4

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings


logger = logging.getLogger(__name__)
_SQLALCHEMY_SUPPORTS_PREPARED_NAME_FUNC: bool | None = None
_LOGGED_RUNTIME_TARGETS: set[str] = set()


def _is_production_like_runtime() -> bool:
    """Return True when this process should never fall back to a local DB."""
    settings = get_settings()
    app_env = (settings.environment or "development").strip().lower()
    railway_env = (os.getenv("RAILWAY_ENVIRONMENT") or "").strip().lower()
    return (
        app_env in {"staging", "production"}
        or railway_env in {"staging", "production"}
        or bool(os.getenv("RAILWAY_STATIC_URL"))
        or bool(os.getenv("RAILWAY_PROJECT_ID"))
    )


def describe_database_target(database_url: str) -> str:
    """Return a credential-free summary of the configured database target."""
    try:
        parsed = make_url(database_url)
    except Exception:
        return "<unparseable-database-url>"

    host = parsed.host or "<unknown-host>"
    port = parsed.port or 5432
    database = parsed.database or "<unknown-db>"
    if host in {"localhost", "127.0.0.1", "db"}:
        flavor = "local"
    elif is_pgbouncer_url(database_url):
        flavor = "supabase-pooler"
    else:
        flavor = "remote"
    return f"{host}:{port}/{database} [{flavor}]"


def resolve_runtime_database_url(database_url: str) -> str:
    """
    Resolve the runtime DB URL, optionally falling back to local Postgres in dev.

    This keeps local development moving when the remote Supabase pooler is
    unreachable from the current environment or when a developer explicitly
    wants to use the docker-compose database instead.
    """
    settings = get_settings()
    production_like = _is_production_like_runtime()

    if settings.prefer_local_database:
        if production_like:
            raise RuntimeError(
                "prefer_local_database=true is not allowed in production-like runtimes."
            )
        logger.warning("Using local database because prefer_local_database=true")
        return settings.local_database_url

    try:
        parsed = make_url(database_url)
    except Exception:
        return database_url

    host = parsed.host
    port = parsed.port or 5432
    if production_like:
        if host in {"localhost", "127.0.0.1", "db"}:
            raise RuntimeError(
                f"Production-like runtime cannot use local database target {host}:{port}."
            )
        if host:
            try:
                socket.getaddrinfo(host, port)
            except socket.gaierror as exc:
                raise RuntimeError(
                    f"Primary database host {host} could not be resolved in a production-like runtime."
                ) from exc
        return database_url

    if not settings.auto_fallback_local_database or settings.environment != "development":
        return database_url

    if not host or host in {"localhost", "127.0.0.1", "db"}:
        return database_url

    try:
        socket.getaddrinfo(host, port)
        return database_url
    except socket.gaierror:
        logger.warning(
            "Primary database host %s could not be resolved; falling back to local database %s",
            host,
            settings.local_database_url,
        )
        return settings.local_database_url


def is_pgbouncer_url(database_url: str) -> bool:
    """Return True when the URL likely points at a pgbouncer-style pooler."""
    normalized = database_url.lower()
    try:
        parsed = make_url(database_url)
        host = (parsed.host or "").lower()
        port = parsed.port or 5432
    except Exception:
        host = ""
        port = 5432

    return (
        "pgbouncer" in normalized
        or "pooler.supabase" in host
        or port == 6543
    )


def normalize_asyncpg_dsn(database_url: str) -> str:
    """Convert SQLAlchemy asyncpg URLs into raw asyncpg DSNs."""
    if database_url.startswith("postgresql+asyncpg://"):
        return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    if database_url.startswith("postgres+asyncpg://"):
        return database_url.replace("postgres+asyncpg://", "postgres://", 1)
    return database_url


def resolve_runtime_sync_database_url(database_url: str | None = None) -> str:
    """
    Resolve a psycopg2-compatible runtime DSN using the same fallback rules as the app.

    Older sync-only services still need the production pooler/direct split and the
    development localhost fallback behavior to come from one place.
    """
    settings = get_settings()
    resolved = resolve_runtime_database_url(database_url or settings.database_url)
    return normalize_asyncpg_dsn(resolved)


def _sqlalchemy_asyncpg_supports_prepared_statement_name_func() -> bool:
    """Return True when installed SQLAlchemy asyncpg adapter supports custom statement names."""
    global _SQLALCHEMY_SUPPORTS_PREPARED_NAME_FUNC
    if _SQLALCHEMY_SUPPORTS_PREPARED_NAME_FUNC is not None:
        return _SQLALCHEMY_SUPPORTS_PREPARED_NAME_FUNC
    try:
        from sqlalchemy.dialects.postgresql.asyncpg import AsyncAdapt_asyncpg_connection

        sig = inspect.signature(AsyncAdapt_asyncpg_connection.__init__)
        _SQLALCHEMY_SUPPORTS_PREPARED_NAME_FUNC = "prepared_statement_name_func" in sig.parameters
    except Exception:
        _SQLALCHEMY_SUPPORTS_PREPARED_NAME_FUNC = False
    return _SQLALCHEMY_SUPPORTS_PREPARED_NAME_FUNC


def asyncpg_connection_kwargs(database_url: str) -> Dict[str, Any]:
    """
    Build raw asyncpg kwargs that are safe with pgbouncer transaction pooling.

    statement_cache_size=0 is always set — Supabase uses pgbouncer in
    transaction pooling mode which doesn't support prepared statements.
    Setting this to 0 has no downside for correctness or performance.
    """
    kwargs: Dict[str, Any] = {}

    if "supabase" in database_url.lower() or "amazonaws" in database_url.lower():
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
        kwargs["ssl"] = ssl_ctx

    # Always disable prepared statement cache — safe for all pooled connections
    kwargs["statement_cache_size"] = 0

    if is_pgbouncer_url(database_url):
        if _sqlalchemy_asyncpg_supports_prepared_statement_name_func():
            # PgBouncer transaction pooling can hand us a different backend
            # connection between transactions, so asyncpg must not reuse stable
            # prepared statement names across logical connections.
            kwargs["prepared_statement_name_func"] = lambda: f"__asyncpg_{uuid4().hex}__"
        else:
            logger.warning(
                "Installed SQLAlchemy asyncpg adapter does not support prepared_statement_name_func; "
                "pgbouncer compatibility may degrade until the driver stack is upgraded."
            )

    return kwargs


def sqlalchemy_connect_args(database_url: str) -> Dict[str, Any]:
    """Build SQLAlchemy asyncpg connect_args from the raw asyncpg settings."""
    kwargs = asyncpg_connection_kwargs(database_url)
    kwargs["prepared_statement_cache_size"] = 0
    return kwargs


def create_configured_async_engine(database_url: str, **kwargs: Any) -> AsyncEngine:
    """Create an async SQLAlchemy engine with shared asyncpg-safe settings."""
    database_url = resolve_runtime_database_url(database_url)
    target = describe_database_target(database_url)
    if target not in _LOGGED_RUNTIME_TARGETS:
        settings = get_settings()
        logger.info(
            "Database runtime target resolved: env=%s railway_env=%s target=%s",
            settings.environment,
            os.getenv("RAILWAY_ENVIRONMENT", ""),
            target,
        )
        _LOGGED_RUNTIME_TARGETS.add(target)
    connect_args = dict(kwargs.pop("connect_args", {}) or {})
    for key, value in sqlalchemy_connect_args(database_url).items():
        connect_args.setdefault(key, value)
    if is_pgbouncer_url(database_url):
        # When PgBouncer is in transaction mode, reusing SQLAlchemy-side pooled
        # connections can still collide with backend prepared statement state.
        kwargs.setdefault("poolclass", NullPool)
    if kwargs.get("poolclass") is NullPool:
        kwargs.pop("pool_size", None)
        kwargs.pop("max_overflow", None)
    return create_async_engine(database_url, connect_args=connect_args, **kwargs)
