"""
Market Intelligence Agent Module

Monitors geo-specific events and conditions:
- Local events (festivals, concerts)
- Weather alerts (hurricanes, avalanche)
- Beach conditions
- Market trends
"""

from app.services.agents.market_intelligence.market_agent import (
    MarketIntelligenceAgent,
    MarketAlert,
    MarketEvent,
    get_market_agent,
)

__all__ = [
    "MarketIntelligenceAgent",
    "MarketAlert",
    "MarketEvent",
    "get_market_agent",
]
