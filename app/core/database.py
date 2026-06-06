"""
Database Session Factory

Provides async SQLAlchemy sessions for the MCP layer.

MCPs are stateless servers — they don't hold a db connection open.
Instead, callers (API endpoints, background workers) pass a session in
via params, or MCPs use this factory to create a short-lived session
for the duration of a single call.

Usage in MCP server:
    async with get_db_session() as session:
        result = await some_service.query(session, ...)

Usage from API endpoint (preferred — reuses the request's session):
    # Pass session_id or inject session via dependency
    await registry.call("concierge", "get_faq_answer", op_id, {
        "question": q,
        "property_code": code,
        "_db_session": session,   # injected by API layer
    })
"""

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)

from app.core.config import get_settings
from app.core.db_connect import create_configured_async_engine, describe_database_target

settings = get_settings()
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Engine (created once, shared across all sessions)
# ─────────────────────────────────────────────────────────────────────────────

_engine: Optional[AsyncEngine] = None
_session_factory: Optional[async_sessionmaker] = None


def _get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_configured_async_engine(
            settings.database_url,
            pool_size=settings.database_pool_size,
            max_overflow=settings.database_max_overflow,
            echo=settings.database_echo,
            pool_pre_ping=True,
            pool_recycle=3600,
        )
    return _engine


def _get_session_factory() -> async_sessionmaker:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=_get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,    # Don't expire objects after commit (MCP pattern)
            autocommit=False,
            autoflush=False,
        )
    return _session_factory


# ─────────────────────────────────────────────────────────────────────────────
# Session context manager — use in MCPs that need their own session
# ─────────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Async context manager for a DB session.

    Usage:
        async with get_db_session() as session:
            result = await service.query(session, ...)
    """
    factory = _get_session_factory()
    session: AsyncSession = factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


# ─────────────────────────────────────────────────────────────────────────────
# FastAPI dependency — reuse in API endpoints
# ─────────────────────────────────────────────────────────────────────────────

async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency for DB session injection.

    Usage:
        @router.get("/")
        async def endpoint(db: AsyncSession = Depends(get_async_session)):
            ...
    """
    factory = _get_session_factory()
    session: AsyncSession = factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


# ─────────────────────────────────────────────────────────────────────────────
# Lifecycle — call at app startup / shutdown
# ─────────────────────────────────────────────────────────────────────────────

async def init_database(
    startup_deadline_seconds: float = 75.0,
    connect_timeout_seconds: float = 12.0,
    retry_interval_seconds: float = 3.0,
) -> None:
    """
    Initialize the database engine and verify the primary DB is reachable.

    Railway deploys should not fail because a single pooled DB handshake was
    momentarily slow. Retry within a bounded startup window before giving up.
    """
    engine = _get_engine()
    target = describe_database_target(str(engine.url))
    deadline = time.monotonic() + max(startup_deadline_seconds, connect_timeout_seconds)
    attempt = 0
    last_error: Exception | None = None

    while time.monotonic() < deadline:
        attempt += 1
        try:
            async with asyncio.timeout(connect_timeout_seconds):
                async with engine.connect() as conn:
                    await conn.execute(text("SELECT 1"))
            logger.info(
                "Database connectivity verified at startup after %s attempt(s): target=%s",
                attempt,
                target,
            )
            return
        except Exception as exc:
            last_error = exc
            remaining = max(0.0, deadline - time.monotonic())
            logger.warning(
                "Database startup attempt %s failed for %s: %s (%.1fs remaining)",
                attempt,
                target,
                exc,
                remaining,
            )
            if remaining <= retry_interval_seconds:
                break
            await asyncio.sleep(retry_interval_seconds)

    raise RuntimeError(
        f"Database did not become reachable within {startup_deadline_seconds:.0f}s for {target}"
    ) from last_error


async def close_database() -> None:
    """Dispose the engine connection pool. Call at shutdown."""
    global _engine
    if _engine:
        await _engine.dispose()
        _engine = None
