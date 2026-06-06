"""
Market Service.

Provides market context building and management.
"""

from .market_context_builder import (
    MarketContextBuilder,
    RawEvent,
    EventSource,
    US_HOLIDAYS_2026,
    SAMPLE_30A_EVENTS,
    build_30a_market_context,
    build_market_context_from_evidence,
)


__all__ = [
    "MarketContextBuilder",
    "RawEvent",
    "EventSource",
    "US_HOLIDAYS_2026",
    "SAMPLE_30A_EVENTS",
    "build_30a_market_context",
    "build_market_context_from_evidence",
]
