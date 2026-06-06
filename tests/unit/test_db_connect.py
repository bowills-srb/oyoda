from __future__ import annotations

from app.core import db_connect
from app.core.db_connect import (
    asyncpg_connection_kwargs,
    create_configured_async_engine,
    is_pgbouncer_url,
)
from sqlalchemy.pool import NullPool


def test_asyncpg_connection_kwargs_harden_pgbouncer_urls(monkeypatch):
    url = "postgresql+asyncpg://user:pass@aws-1-us-east-1.pooler.supabase.com:6543/postgres"
    monkeypatch.setattr(db_connect, "_SQLALCHEMY_SUPPORTS_PREPARED_NAME_FUNC", True)

    kwargs = asyncpg_connection_kwargs(url)

    assert is_pgbouncer_url(url) is True
    assert kwargs["statement_cache_size"] == 0
    assert callable(kwargs["prepared_statement_name_func"])
    first = kwargs["prepared_statement_name_func"]()
    second = kwargs["prepared_statement_name_func"]()
    assert first != second

def test_asyncpg_connection_kwargs_omits_prepared_name_func_when_sqlalchemy_unsupported(monkeypatch):
    monkeypatch.setattr(db_connect, "_SQLALCHEMY_SUPPORTS_PREPARED_NAME_FUNC", False)
    kwargs = asyncpg_connection_kwargs("postgresql+asyncpg://user:pass@aws-1-us-east-1.pooler.supabase.com:6543/postgres")
    assert "prepared_statement_name_func" not in kwargs


def test_asyncpg_connection_kwargs_includes_prepared_name_func_when_sqlalchemy_supported(monkeypatch):
    monkeypatch.setattr(db_connect, "_SQLALCHEMY_SUPPORTS_PREPARED_NAME_FUNC", True)
    kwargs = asyncpg_connection_kwargs("postgresql+asyncpg://user:pass@aws-1-us-east-1.pooler.supabase.com:6543/postgres")
    assert callable(kwargs["prepared_statement_name_func"])


def test_asyncpg_connection_kwargs_omits_for_non_pgbouncer(monkeypatch):
    monkeypatch.setattr(db_connect, "_SQLALCHEMY_SUPPORTS_PREPARED_NAME_FUNC", True)
    kwargs = asyncpg_connection_kwargs("postgresql+asyncpg://user:pass@localhost:5432/postgres")
    assert "prepared_statement_name_func" not in kwargs


def test_create_configured_async_engine_uses_nullpool_for_pgbouncer(monkeypatch):
    url = "postgresql+asyncpg://user:pass@aws-1-us-east-1.pooler.supabase.com:6543/postgres"
    monkeypatch.setattr(db_connect, "resolve_runtime_database_url", lambda database_url: database_url)

    engine = create_configured_async_engine(url)
    try:
        assert isinstance(engine.sync_engine.pool, NullPool)
    finally:
        engine.sync_engine.dispose()
