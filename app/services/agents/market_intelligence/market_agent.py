"""
Market Intelligence Agent

Monitors geo-specific events and conditions for each market:
- Local events (festivals, concerts, sports)
- Weather alerts (hurricanes, avalanches, heat waves)
- Beach conditions (flags, rip currents)
- Market trends (occupancy, ADR)

The agent runs continuously in the background, updating
the knowledge base with relevant information that the
Voice Pod can use to inform guests.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class AlertSeverity(str, Enum):
    """Alert severity levels."""
    INFO = "info"
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    SEVERE = "severe"
    EXTREME = "extreme"


class AlertType(str, Enum):
    """Types of alerts by market."""
    # Beach markets
    BEACH_FLAG = "beach_flag"
    RIP_CURRENT = "rip_current"
    HURRICANE_WATCH = "hurricane_watch"
    HURRICANE_WARNING = "hurricane_warning"
    JELLYFISH = "jellyfish"
    
    # Mountain markets
    AVALANCHE_WARNING = "avalanche_warning"
    ROAD_CLOSURE = "road_closure"
    LIFT_CLOSURE = "lift_closure"
    SNOW_REPORT = "snow_report"
    
    # General
    HEAT_ADVISORY = "heat_advisory"
    SEVERE_THUNDERSTORM = "severe_thunderstorm"
    TORNADO_WATCH = "tornado_watch"
    FLOOD_WARNING = "flood_warning"
    
    # Events
    MAJOR_EVENT = "major_event"
    TRAFFIC_ADVISORY = "traffic_advisory"


class EventType(str, Enum):
    """Types of events."""
    FESTIVAL = "festival"
    CONCERT = "concert"
    SPORTS = "sports"
    HOLIDAY = "holiday"
    CONFERENCE = "conference"
    COMMUNITY = "community"
    MARKET = "market"  # Farmers market, etc.


@dataclass
class MarketAlert:
    """An active alert for a market."""
    alert_id: str
    market_id: str
    alert_type: AlertType
    severity: AlertSeverity
    title: str
    description: str
    instructions: Optional[str] = None
    
    # For beach flags
    flag_color: Optional[str] = None
    
    # Timing
    issued_at: datetime = field(default_factory=datetime.utcnow)
    effective_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    
    # Display
    icon_emoji: str = "⚠️"
    show_on_mobile: bool = True
    
    # Source
    source: str = "manual"
    source_url: Optional[str] = None
    
    def to_guest_message(self) -> str:
        """Format alert for guest display."""
        lines = [f"{self.icon_emoji} **{self.title}**"]
        lines.append(self.description)
        if self.instructions:
            lines.append(f"\n*{self.instructions}*")
        return "\n".join(lines)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "alert_id": self.alert_id,
            "market_id": self.market_id,
            "alert_type": self.alert_type.value,
            "severity": self.severity.value,
            "title": self.title,
            "description": self.description,
            "instructions": self.instructions,
            "flag_color": self.flag_color,
            "issued_at": self.issued_at.isoformat(),
            "effective_at": self.effective_at.isoformat() if self.effective_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "icon_emoji": self.icon_emoji,
            "show_on_mobile": self.show_on_mobile,
            "source": self.source,
            "source_url": self.source_url,
        }


@dataclass
class MarketEvent:
    """An event in a market."""
    event_id: str
    market_id: str
    name: str
    event_type: EventType
    
    # When
    start_date: date
    end_date: Optional[date] = None
    start_time: Optional[str] = None
    all_day: bool = False
    
    # Where
    venue_name: Optional[str] = None
    venue_address: Optional[str] = None
    
    # Details
    description: Optional[str] = None
    expected_attendance: Optional[int] = None
    
    # Impact
    affects_pricing: bool = False
    pricing_impact_percent: float = 0.0
    traffic_impact: str = "none"  # none, light, moderate, heavy
    
    # For concierge
    guest_relevance: str = "informational"  # informational, recommended, warning
    guest_message: Optional[str] = None
    
    # Source
    source: str = "manual"
    source_url: Optional[str] = None
    
    def to_guest_message(self) -> str:
        """Format event for guest display."""
        date_str = self.start_date.strftime("%A, %B %d")
        if self.start_time:
            date_str += f" at {self.start_time}"
        
        lines = [f"🎉 **{self.name}**"]
        lines.append(f"📅 {date_str}")
        
        if self.venue_name:
            lines.append(f"📍 {self.venue_name}")
        
        if self.description:
            lines.append(self.description)
        
        if self.traffic_impact in ["moderate", "heavy"]:
            lines.append(f"\n⚠️ Expect {self.traffic_impact} traffic")
        
        return "\n".join(lines)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "market_id": self.market_id,
            "name": self.name,
            "event_type": self.event_type.value,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "start_time": self.start_time,
            "all_day": self.all_day,
            "venue_name": self.venue_name,
            "venue_address": self.venue_address,
            "description": self.description,
            "expected_attendance": self.expected_attendance,
            "affects_pricing": self.affects_pricing,
            "pricing_impact_percent": self.pricing_impact_percent,
            "traffic_impact": self.traffic_impact,
            "guest_relevance": self.guest_relevance,
            "guest_message": self.guest_message,
            "source": self.source,
            "source_url": self.source_url,
        }


class MarketIntelligenceAgent:
    """
    Monitors markets for events and conditions.
    
    The agent:
    1. Periodically scrapes event sources
    2. Monitors weather APIs for alerts
    3. Checks market-specific conditions (beach flags, etc.)
    4. Updates the knowledge base
    5. Notifies operators of important changes
    
    Usage:
        agent = MarketIntelligenceAgent(db_session)
        
        # Get current alerts for a market
        alerts = await agent.get_active_alerts("MARKET_30A")
        
        # Get upcoming events
        events = await agent.get_upcoming_events("MARKET_30A", days=14)
        
        # Start background monitoring
        await agent.start_monitoring()
    """
    
    # Market configurations
    MARKET_CONFIGS = {
        "MARKET_30A": {
            "name": "30A Florida",
            "type": "beach",
            "timezone": "America/Chicago",
            "alert_types": [
                AlertType.BEACH_FLAG,
                AlertType.RIP_CURRENT,
                AlertType.HURRICANE_WATCH,
                AlertType.HURRICANE_WARNING,
                AlertType.SEVERE_THUNDERSTORM,
            ],
            "weather_station": "KBKV",  # Brooksville
            "beach_flag_source": "https://www.swfd.org/beach-flag-status",
            "event_sources": ["eventbrite", "local_calendar"],
        },
        "MARKET_PARK_CITY": {
            "name": "Park City Utah",
            "type": "mountain",
            "timezone": "America/Denver",
            "alert_types": [
                AlertType.AVALANCHE_WARNING,
                AlertType.ROAD_CLOSURE,
                AlertType.LIFT_CLOSURE,
                AlertType.SNOW_REPORT,
            ],
            "avalanche_center": "https://utahavalanchecenter.org",
            "resort_api": "park_city_mountain",
            "event_sources": ["eventbrite", "ski_resort_calendar"],
        },
    }
    
    # Beach flag configurations
    BEACH_FLAG_CONFIG = {
        "green": {
            "emoji": "🟢",
            "title": "Green Flag - Calm Conditions",
            "description": "Low hazard. Calm conditions, exercise normal caution.",
            "severity": AlertSeverity.INFO,
        },
        "yellow": {
            "emoji": "🟡",
            "title": "Yellow Flag - Moderate Surf",
            "description": "Medium hazard. Moderate surf and/or currents.",
            "severity": AlertSeverity.LOW,
        },
        "red": {
            "emoji": "🔴",
            "title": "Red Flag - High Hazard",
            "description": "High hazard. High surf and/or strong currents.",
            "instructions": "Weak swimmers should stay out of the water.",
            "severity": AlertSeverity.MODERATE,
        },
        "double_red": {
            "emoji": "🚩🚩",
            "title": "Double Red Flag - Water Closed",
            "description": "Water is closed to the public.",
            "instructions": "Stay out of the water. Violators subject to citation.",
            "severity": AlertSeverity.SEVERE,
        },
        "purple": {
            "emoji": "🟣",
            "title": "Purple Flag - Dangerous Marine Life",
            "description": "Dangerous marine life (jellyfish, stingrays, etc.)",
            "instructions": "Swim with caution. Shuffle feet in shallow water.",
            "severity": AlertSeverity.MODERATE,
        },
    }
    
    def __init__(self, db_session: AsyncSession):
        self.db = db_session
        self._active_alerts: Dict[str, List[MarketAlert]] = {}
        self._events_cache: Dict[str, List[MarketEvent]] = {}
        self._monitoring_task: Optional[asyncio.Task] = None
    
    async def get_active_alerts(self, market_id: str) -> List[MarketAlert]:
        """Get active alerts for a market."""
        # Check cache first
        if market_id in self._active_alerts:
            # Filter expired alerts
            now = datetime.utcnow()
            self._active_alerts[market_id] = [
                a for a in self._active_alerts[market_id]
                if not a.expires_at or a.expires_at > now
            ]
            return self._active_alerts[market_id]
        
        # TODO: Load from database
        return []
    
    async def get_current_beach_flag(self, market_id: str) -> Optional[MarketAlert]:
        """Get current beach flag for a beach market."""
        alerts = await self.get_active_alerts(market_id)
        for alert in alerts:
            if alert.alert_type == AlertType.BEACH_FLAG:
                return alert
        return None
    
    async def get_upcoming_events(
        self,
        market_id: str,
        days: int = 14,
        event_types: Optional[List[EventType]] = None,
    ) -> List[MarketEvent]:
        """Get upcoming events for a market."""
        # Check cache
        if market_id in self._events_cache:
            events = self._events_cache[market_id]
        else:
            # TODO: Load from database
            events = []
        
        # Filter by date range
        today = date.today()
        end_date = today + timedelta(days=days)
        
        filtered = [
            e for e in events
            if today <= e.start_date <= end_date
        ]
        
        # Filter by type if specified
        if event_types:
            filtered = [e for e in filtered if e.event_type in event_types]
        
        # Sort by date
        filtered.sort(key=lambda e: e.start_date)
        
        return filtered
    
    async def update_beach_flag(
        self,
        market_id: str,
        flag_color: str,
        source: str = "manual",
    ) -> MarketAlert:
        """Update beach flag for a market."""
        config = self.BEACH_FLAG_CONFIG.get(flag_color, self.BEACH_FLAG_CONFIG["yellow"])
        
        alert = MarketAlert(
            alert_id=f"beach_flag_{market_id}_{datetime.utcnow().strftime('%Y%m%d')}",
            market_id=market_id,
            alert_type=AlertType.BEACH_FLAG,
            severity=config["severity"],
            title=config["title"],
            description=config["description"],
            instructions=config.get("instructions"),
            flag_color=flag_color,
            icon_emoji=config["emoji"],
            source=source,
            expires_at=datetime.utcnow() + timedelta(hours=24),  # Refresh daily
        )
        
        # Update cache
        if market_id not in self._active_alerts:
            self._active_alerts[market_id] = []
        
        # Remove old beach flag alerts
        self._active_alerts[market_id] = [
            a for a in self._active_alerts[market_id]
            if a.alert_type != AlertType.BEACH_FLAG
        ]
        
        self._active_alerts[market_id].append(alert)
        
        # TODO: Persist to database
        
        logger.info(f"Updated beach flag for {market_id}: {flag_color}")
        return alert
    
    async def add_event(self, event: MarketEvent) -> MarketEvent:
        """Add an event to a market."""
        if event.market_id not in self._events_cache:
            self._events_cache[event.market_id] = []
        
        self._events_cache[event.market_id].append(event)
        
        # TODO: Persist to database
        
        logger.info(f"Added event to {event.market_id}: {event.name}")
        return event
    
    async def add_alert(self, alert: MarketAlert) -> MarketAlert:
        """Add an alert to a market."""
        if alert.market_id not in self._active_alerts:
            self._active_alerts[alert.market_id] = []
        
        self._active_alerts[alert.market_id].append(alert)
        
        # TODO: Persist to database
        
        logger.info(f"Added alert to {alert.market_id}: {alert.title}")
        return alert
    
    async def start_monitoring(self, interval_minutes: int = 30):
        """Start background monitoring of all markets."""
        if self._monitoring_task and not self._monitoring_task.done():
            logger.warning("Monitoring already running")
            return
        
        self._monitoring_task = asyncio.create_task(
            self._monitoring_loop(interval_minutes)
        )
        logger.info(f"Started market monitoring (interval: {interval_minutes}min)")
    
    async def stop_monitoring(self):
        """Stop background monitoring."""
        if self._monitoring_task:
            self._monitoring_task.cancel()
            try:
                await self._monitoring_task
            except asyncio.CancelledError:
                pass
            self._monitoring_task = None
            logger.info("Stopped market monitoring")
    
    async def _monitoring_loop(self, interval_minutes: int):
        """Background monitoring loop."""
        while True:
            try:
                for market_id, config in self.MARKET_CONFIGS.items():
                    await self._update_market(market_id, config)
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
            
            await asyncio.sleep(interval_minutes * 60)
    
    async def _update_market(self, market_id: str, config: dict):
        """Update a single market's data."""
        market_type = config.get("type")
        
        if market_type == "beach":
            # Update beach flag
            try:
                flag_color = await self._scrape_beach_flag(config.get("beach_flag_source"))
                if flag_color:
                    await self.update_beach_flag(market_id, flag_color, source="scraper")
            except Exception as e:
                logger.error(f"Error updating beach flag for {market_id}: {e}")
        
        elif market_type == "mountain":
            # Update avalanche conditions
            try:
                await self._update_avalanche_conditions(market_id, config)
            except Exception as e:
                logger.error(f"Error updating avalanche for {market_id}: {e}")
        
        # Update events (all market types)
        try:
            await self._scrape_events(market_id, config.get("event_sources", []))
        except Exception as e:
            logger.error(f"Error updating events for {market_id}: {e}")
    
    async def _scrape_beach_flag(self, source_url: Optional[str]) -> Optional[str]:
        """Scrape beach flag from source."""
        if not source_url:
            return None
        
        # TODO: Implement actual scraping
        # For now, return default
        return "yellow"
    
    async def _update_avalanche_conditions(self, market_id: str, config: dict):
        """Update avalanche conditions for a mountain market."""
        # TODO: Implement avalanche API integration
        pass
    
    async def _scrape_events(self, market_id: str, sources: List[str]):
        """Scrape events from configured sources."""
        # TODO: Implement event scraping
        pass
    
    def get_context_for_guest(
        self,
        market_id: str,
        property_code: Optional[str] = None,
    ) -> str:
        """
        Get market context formatted for Voice Pod.
        
        This is called by the Librarian Agent to include
        relevant market conditions in the guest context.
        """
        lines = []
        
        # Active alerts
        alerts = self._active_alerts.get(market_id, [])
        if alerts:
            lines.append("CURRENT CONDITIONS:")
            for alert in alerts:
                lines.append(f"• {alert.icon_emoji} {alert.title}: {alert.description}")
        
        # Upcoming events (next 7 days)
        events = self._events_cache.get(market_id, [])
        today = date.today()
        upcoming = [
            e for e in events
            if today <= e.start_date <= today + timedelta(days=7)
        ]
        
        if upcoming:
            lines.append("\nUPCOMING EVENTS:")
            for event in upcoming[:3]:
                date_str = event.start_date.strftime("%A")
                lines.append(f"• {event.name} - {date_str}")
        
        return "\n".join(lines) if lines else ""


# Singleton
_market_agent: Optional[MarketIntelligenceAgent] = None


async def get_market_agent(db_session: AsyncSession) -> MarketIntelligenceAgent:
    """Get or create market intelligence agent."""
    global _market_agent
    if _market_agent is None:
        _market_agent = MarketIntelligenceAgent(db_session)
    return _market_agent
