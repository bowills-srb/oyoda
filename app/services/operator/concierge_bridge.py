"""
Thin bridge from operator services into concierge services.

This keeps direct concierge imports out of deeper operator workflow modules and
gives us one seam to replace with eventing/contracts over time.
"""

from app.services.concierge.db_session_service import (
    DEFAULT_TENANT_ID,
    get_db_session_service,
)

__all__ = [
    "DEFAULT_TENANT_ID",
    "get_db_session_service",
]
