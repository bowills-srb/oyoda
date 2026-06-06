"""
Shared session cleanup helpers.

These helpers are used in fail-soft code paths that intentionally catch
database exceptions and return defaults. In async SQLAlchemy contexts,
swallowing the Python exception is not enough; the session must be rolled
back or every later query on the same session can fail with
InFailedSQLTransactionError.
"""

from __future__ import annotations

from typing import Any


async def safe_rollback(db: Any) -> None:
    """Best-effort rollback for session-like objects.

    Supports both async SQLAlchemy sessions and lightweight test doubles that
    expose a `rollback()` method. Cleanup failures are intentionally swallowed
    so the caller can keep its existing fail-soft behavior.
    """
    if db is None:
        return

    rollback = getattr(db, "rollback", None)
    if rollback is None:
        return

    try:
        result = rollback()
        if result is not None and hasattr(result, "__await__"):
            await result
    except Exception:
        pass
