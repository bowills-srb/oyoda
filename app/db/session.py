"""
Async database session utilities for API handlers.
"""

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)

from app.core.config import get_settings
from app.core.db_connect import create_configured_async_engine


settings = get_settings()

engine: AsyncEngine = create_configured_async_engine(
    settings.database_url,
    echo=settings.database_echo,
    pool_pre_ping=True,
)

SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)

# Backward-compatible alias for legacy callers that still import
# AsyncSessionLocal as the async session factory.
AsyncSessionLocal = SessionLocal


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an async DB session."""
    async with SessionLocal() as session:
        yield session
