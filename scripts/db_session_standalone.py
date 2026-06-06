#!/usr/bin/env python3
"""
db_session_standalone.py — Direct asyncpg session for standalone scripts.

The app's get_async_session is an async generator designed for FastAPI
dependency injection. Standalone scripts (cron jobs, CLI tools) need a
simpler direct connection approach.

Usage:
    from scripts.db_session_standalone import get_standalone_session
    async with get_standalone_session() as db:
        await db.execute(text("SELECT 1"))
"""

import os
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
)

from app.core.db_connect import create_configured_async_engine

_engine = None
_factory = None


def _get_engine():
    global _engine, _factory
    if _engine is None:
        db_url = os.getenv("DATABASE_URL", "")
        if not db_url:
            # Try loading from .env
            try:
                from dotenv import load_dotenv
                load_dotenv()
                db_url = os.getenv("DATABASE_URL", "")
            except ImportError:
                pass

        if not db_url:
            raise RuntimeError(
                "DATABASE_URL not set. Add it to your .env or set it as an env var."
            )

        # Ensure asyncpg driver
        if db_url.startswith("postgresql://"):
            db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
        elif db_url.startswith("postgres://"):
            db_url = db_url.replace("postgres://", "postgresql+asyncpg://", 1)

        _engine = create_configured_async_engine(
            db_url,
            pool_size=3,
            max_overflow=2,
            pool_pre_ping=True,
        )
        _factory = async_sessionmaker(
            _engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _engine, _factory


@asynccontextmanager
async def get_standalone_session():
    """
    Async context manager that yields a SQLAlchemy AsyncSession.
    Commits on success, rolls back on error.

    Usage:
        async with get_standalone_session() as db:
            result = await db.execute(text("SELECT 1"))
    """
    _, factory = _get_engine()
    session: AsyncSession = factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def dispose():
    """Call at end of script to close the connection pool cleanly."""
    global _engine
    if _engine:
        await _engine.dispose()
        _engine = None
