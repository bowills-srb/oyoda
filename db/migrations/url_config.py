"""
Helpers for resolving the database URL used by Alembic migrations.

Long-term rule:
- Runtime app traffic uses `DATABASE_URL`
- Alembic can use a dedicated `ALEMBIC_DATABASE_URL`
- Direct-vs-pooler switching is explicit, never guessed implicitly
"""

from __future__ import annotations

import os
import re
from typing import Mapping, Tuple


def _is_truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _normalize_driver(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://", 1)


def _ensure_sslmode(url: str) -> str:
    if "sslmode=" in url:
        return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}sslmode=require"


def _rewrite_pooler_to_direct(url: str) -> str:
    return re.sub(r":6543/", ":5432/", url)


def resolve_migration_url(env: Mapping[str, str] | None = None) -> Tuple[str, str]:
    """
    Resolve the sync DB URL Alembic should use.

    Precedence:
    1. `ALEMBIC_DATABASE_URL` - explicit migration connection, preferred
    2. `DATABASE_URL` - runtime connection, acceptable if it also works for migrations

    Optional behavior:
    - `ALEMBIC_USE_DIRECT_URL=true` rewrites Supabase-style pooler port 6543 to 5432.
      This is opt-in because not every environment uses the same credentials on both.

    Returns `(url, source_name)`.
    """
    env = env or os.environ

    source_name = ""
    raw_url = env.get("ALEMBIC_DATABASE_URL", "").strip()
    if raw_url:
        source_name = "ALEMBIC_DATABASE_URL"
    else:
        raw_url = env.get("DATABASE_URL", "").strip()
        if raw_url:
            source_name = "DATABASE_URL"

    if not raw_url:
        raise RuntimeError(
            "No database URL configured for migrations. "
            "Set ALEMBIC_DATABASE_URL or DATABASE_URL before running "
            "alembic upgrade head."
        )

    url = _normalize_driver(raw_url)
    if _is_truthy(env.get("ALEMBIC_USE_DIRECT_URL")):
        url = _rewrite_pooler_to_direct(url)
    url = _ensure_sslmode(url)
    return url, source_name
