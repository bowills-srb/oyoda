"""
PMS Integration Module

Provides unified interface to various Property Management Systems:
- Escapia (Vrbo)
- Guesty
- Hostaway
- Track/TrackHS
- Streamline
- Lodgify
- OwnerRez
- Hostfully

Each PMS connector implements the same interface, allowing the
onboarding agent to work with any supported system.
"""

from app.services.integrations.pms.base import (
    PMSConnector,
    PMSProperty,
    PMSBooking,
    PMSGuest,
    PMSRate,
    SyncResult,
)
from app.services.integrations.pms.registry import (
    get_pms_connector,
    list_supported_pms,
    PMSRegistry,
)

__all__ = [
    "PMSConnector",
    "PMSProperty",
    "PMSBooking",
    "PMSGuest",
    "PMSRate",
    "SyncResult",
    "get_pms_connector",
    "list_supported_pms",
    "PMSRegistry",
]
