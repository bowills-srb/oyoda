"""
Integrations — inbound transport, parsers, and external-system adapters.

Tier 1 of the messaging architecture (shaped by outside systems).

Responsibility: Get messages into and out of Oyvoda. Every module here
is named after, or shaped by, an external system Oyvoda doesn't control:
Gmail, Microsoft 365, Vrbo, Airbnb, Booking.com, HomeAway, Stripe, Twilio,
Escapia ENET, etc.

Key modules:
  gmail_inbox_poller.py, microsoft_inbox_poller.py  — inbound pollers
  email_parser_router.py    — deterministic drop + parser selection
  ota_email_parsers.py      — OTA deterministic parsers (Vrbo, Airbnb, ...)
  direct_email_parsers.py   — non-OTA guest email parsers
  vendor_email_parsers.py   — vendor / operational mail parsers
  llm_email_extractor.py    — LLM-based fallback when deterministic fails
  email_dispatch.py         — outbound dispatch routing
  non_guest_patterns.py     — patterns that should never reach the brain
  property_mention_surfaces.py — surface-audit notes (healer signal source)
  pms/                      — PMS-specific connectors

What lives in OTHER tiers (do not duplicate here):
  - Identity, channel router, canonical contracts, alert routing platform:
        app/services/messaging/
  - Decision logic (classify, route, compose):  app/services/messaging_brain/
  - Healers and cross-cutting workers:          app/services/agents/

Dependency rule: integrations/ may import from messaging/ (Tier 2) and
from shared infrastructure. It must NOT import from messaging_brain/
(Tier 3). Transport shouldn't depend on decision.

Defining test: if an external system changed its format tomorrow, would
the fix live in this module? If yes, it belongs here.

See docs/architecture/MESSAGING_TIER_MAP.md for the full tier map and the
decision tree for where new code belongs.

Integration services package.

Exports are loaded lazily so lighter integrations can be used without forcing
 heavyweight sync-service dependencies at import time.
"""

from importlib import import_module
from typing import Any

__all__ = [
    "DataSource",
    "PropertyDeduplicator",
    "DataMerger",
    "SourcedField",
    "PropertyMatch",
    "SOURCE_PRIORITY",
    "PropertySyncService",
    "UnifiedProperty",
    "SyncStats",
    "WebsiteWidget",
    "WidgetConfig",
    "WidgetPropertyData",
    "BookingWidgetType",
    "OAuthIntegration",
]


_EXPORT_MAP = {
    "DataSource": ("app.services.integrations.deduplication", "DataSource"),
    "PropertyDeduplicator": ("app.services.integrations.deduplication", "PropertyDeduplicator"),
    "DataMerger": ("app.services.integrations.deduplication", "DataMerger"),
    "SourcedField": ("app.services.integrations.deduplication", "SourcedField"),
    "PropertyMatch": ("app.services.integrations.deduplication", "PropertyMatch"),
    "SOURCE_PRIORITY": ("app.services.integrations.deduplication", "SOURCE_PRIORITY"),
    "PropertySyncService": ("app.services.integrations.sync_service", "PropertySyncService"),
    "UnifiedProperty": ("app.services.integrations.sync_service", "UnifiedProperty"),
    "SyncStats": ("app.services.integrations.sync_service", "SyncStats"),
    "WebsiteWidget": ("app.services.integrations.website_widget", "WebsiteWidget"),
    "WidgetConfig": ("app.services.integrations.website_widget", "WidgetConfig"),
    "WidgetPropertyData": ("app.services.integrations.website_widget", "WidgetPropertyData"),
    "BookingWidgetType": ("app.services.integrations.website_widget", "BookingWidgetType"),
    "OAuthIntegration": ("app.services.integrations.website_widget", "OAuthIntegration"),
}


def __getattr__(name: str) -> Any:
    module_name, attr_name = _EXPORT_MAP.get(name, (None, None))
    if not module_name:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value
