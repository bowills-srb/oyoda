"""
Event Scraper.

Collects event data from various sources:
- Eventbrite
- City tourism calendars
- ICS feeds
- Manual CSV uploads

Writes to MarketEvidence - does NOT compute projections or make decisions.

USAGE:
    scraper = EventScraper(market_id="30a")
    evidence = await scraper.scrape()
    # → List[MarketEvidence] ready for persistence
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)


# =============================================================================
# EVENT DATA STRUCTURES
# =============================================================================

@dataclass
class RawEvent:
    """Raw event data from any source."""
    name: str
    start_date: date
    end_date: date
    
    # Location
    location: Optional[str] = None
    venue: Optional[str] = None
    
    # Impact estimation
    expected_attendance: Optional[int] = None
    category: str = "general"  # festival, conference, sports, holiday, concert
    
    # Source tracking
    source: str = "unknown"
    source_id: Optional[str] = None
    source_url: Optional[str] = None
    
    # Additional metadata
    description: Optional[str] = None
    is_recurring: bool = False


@dataclass
class MarketEvidence:
    """Evidence record for persistence."""
    evidence_id: str = field(default_factory=lambda: str(uuid4()))
    market_id: str = ""
    evidence_type: str = ""
    data: Dict[str, Any] = field(default_factory=dict)
    source: str = "event_scraper"
    confidence: float = 0.7
    observed_at: datetime = field(default_factory=datetime.utcnow)
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "market_id": self.market_id,
            "evidence_type": self.evidence_type,
            "data": self.data,
            "source": self.source,
            "confidence": self.confidence,
            "observed_at": self.observed_at.isoformat(),
            "valid_from": self.valid_from.isoformat() if self.valid_from else None,
            "valid_until": self.valid_until.isoformat() if self.valid_until else None,
        }


# =============================================================================
# KNOWN EVENTS DATABASE
# =============================================================================

# Pre-populated events for markets (in production, these would be scraped)
KNOWN_EVENTS = {
    "30a": [
        RawEvent(
            name="30A Songwriters Festival",
            start_date=date(2026, 1, 15),
            end_date=date(2026, 1, 18),
            location="30A",
            expected_attendance=15000,
            category="music",
            source="manual",
        ),
        RawEvent(
            name="Seaside School Half Marathon",
            start_date=date(2026, 2, 28),
            end_date=date(2026, 3, 1),
            location="Seaside",
            expected_attendance=3000,
            category="sports",
            source="manual",
        ),
        RawEvent(
            name="30A Wine Festival",
            start_date=date(2026, 3, 12),
            end_date=date(2026, 3, 15),
            location="Alys Beach",
            expected_attendance=8000,
            category="festival",
            source="manual",
        ),
        RawEvent(
            name="Digital Graffiti Festival",
            start_date=date(2026, 5, 15),
            end_date=date(2026, 5, 17),
            location="Alys Beach",
            expected_attendance=5000,
            category="festival",
            source="manual",
        ),
        RawEvent(
            name="Baytowne Wharf Beer Festival",
            start_date=date(2026, 4, 17),
            end_date=date(2026, 4, 18),
            location="Sandestin",
            expected_attendance=4000,
            category="festival",
            source="manual",
        ),
        RawEvent(
            name="Seeing Red Wine Festival",
            start_date=date(2026, 11, 6),
            end_date=date(2026, 11, 8),
            location="WaterColor",
            expected_attendance=2000,
            category="festival",
            source="manual",
        ),
        RawEvent(
            name="Rosemary Beach Uncorked",
            start_date=date(2026, 10, 23),
            end_date=date(2026, 10, 25),
            location="Rosemary Beach",
            expected_attendance=3000,
            category="festival",
            source="manual",
        ),
    ],
    "destin": [
        RawEvent(
            name="Destin Fishing Rodeo",
            start_date=date(2026, 10, 1),
            end_date=date(2026, 10, 31),
            location="Destin Harbor",
            expected_attendance=30000,
            category="sports",
            source="manual",
        ),
        RawEvent(
            name="Destin Seafood Festival",
            start_date=date(2026, 10, 2),
            end_date=date(2026, 10, 4),
            location="Destin Harbor",
            expected_attendance=15000,
            category="festival",
            source="manual",
        ),
        RawEvent(
            name="Sandestin Wine Festival",
            start_date=date(2026, 4, 10),
            end_date=date(2026, 4, 12),
            location="Sandestin",
            expected_attendance=5000,
            category="festival",
            source="manual",
        ),
    ],
    "panama_city_beach": [
        RawEvent(
            name="Gulf Coast Jam",
            start_date=date(2026, 6, 5),
            end_date=date(2026, 6, 7),
            location="Panama City Beach",
            expected_attendance=25000,
            category="music",
            source="manual",
        ),
        RawEvent(
            name="SandJam Music Festival",
            start_date=date(2026, 4, 24),
            end_date=date(2026, 4, 26),
            location="Panama City Beach",
            expected_attendance=10000,
            category="music",
            source="manual",
        ),
        RawEvent(
            name="Ironman Florida",
            start_date=date(2026, 11, 7),
            end_date=date(2026, 11, 7),
            location="Panama City Beach",
            expected_attendance=15000,
            category="sports",
            source="manual",
        ),
    ],
}

# US Federal Holidays
US_HOLIDAYS_2026 = [
    RawEvent("New Year's Day", date(2026, 1, 1), date(2026, 1, 1), "national", category="holiday"),
    RawEvent("MLK Day Weekend", date(2026, 1, 17), date(2026, 1, 19), "national", category="holiday"),
    RawEvent("Presidents Day Weekend", date(2026, 2, 14), date(2026, 2, 16), "national", category="holiday"),
    RawEvent("Memorial Day Weekend", date(2026, 5, 23), date(2026, 5, 25), "national", category="holiday"),
    RawEvent("Independence Day", date(2026, 7, 3), date(2026, 7, 5), "national", category="holiday"),
    RawEvent("Labor Day Weekend", date(2026, 9, 5), date(2026, 9, 7), "national", category="holiday"),
    RawEvent("Thanksgiving", date(2026, 11, 26), date(2026, 11, 29), "national", category="holiday"),
    RawEvent("Christmas/New Year", date(2026, 12, 23), date(2027, 1, 3), "national", category="holiday"),
]


# =============================================================================
# EVENT SCRAPER
# =============================================================================

class EventScraper:
    """
    Scrapes event data for a market.
    
    NOTE: This is a hybrid implementation that:
    - Uses pre-populated known events
    - Can be extended to scrape Eventbrite, tourism sites, etc.
    
    Production would add actual scraping of:
    - Eventbrite API
    - Local tourism bureau calendars
    - Venue ICS feeds
    """
    
    def __init__(
        self, 
        market_id: str,
        include_holidays: bool = True,
        lookahead_days: int = 365,
    ):
        self.market_id = market_id
        self.include_holidays = include_holidays
        self.lookahead_days = lookahead_days
    
    async def scrape(self) -> List[MarketEvidence]:
        """
        Scrape events and return evidence records.
        
        Returns:
            List of MarketEvidence ready for persistence
        """
        logger.info(f"Starting event scrape for market: {self.market_id}")
        
        events = []
        
        # 1. Get known events for this market
        market_events = KNOWN_EVENTS.get(self.market_id, [])
        events.extend(market_events)
        
        # 2. Add holidays if requested
        if self.include_holidays:
            events.extend(US_HOLIDAYS_2026)
        
        # 3. Filter to lookahead window
        today = date.today()
        cutoff = today + timedelta(days=self.lookahead_days)
        events = [e for e in events if e.start_date >= today and e.start_date <= cutoff]
        
        # 4. Convert to evidence
        evidence = []
        for event in events:
            evidence.append(self._event_to_evidence(event))
        
        # 5. Add summary evidence
        if events:
            evidence.append(self._create_summary_evidence(events))
        
        logger.info(f"Event scrape complete: {len(evidence)} evidence records")
        return evidence
    
    def _event_to_evidence(self, event: RawEvent) -> MarketEvidence:
        """Convert a single event to evidence."""
        # Estimate impact based on attendance
        if event.expected_attendance:
            if event.expected_attendance >= 10000:
                impact = "extreme"
            elif event.expected_attendance >= 5000:
                impact = "high"
            elif event.expected_attendance >= 2000:
                impact = "medium"
            else:
                impact = "low"
        elif event.category == "holiday":
            impact = "high"
        else:
            impact = "medium"
        
        # Calculate demand multiplier
        multipliers = {
            "extreme": 1.5,
            "high": 1.3,
            "medium": 1.15,
            "low": 1.05,
        }
        
        return MarketEvidence(
            market_id=self.market_id,
            evidence_type="event",
            data={
                "name": event.name,
                "start_date": event.start_date.isoformat(),
                "end_date": event.end_date.isoformat(),
                "location": event.location,
                "category": event.category,
                "expected_attendance": event.expected_attendance,
                "impact": impact,
                "demand_multiplier": multipliers.get(impact, 1.0),
            },
            source=f"event_scraper:{event.source}",
            confidence=0.8 if event.source == "manual" else 0.6,
            valid_from=datetime.combine(event.start_date, datetime.min.time()),
            valid_until=datetime.combine(event.end_date + timedelta(days=1), datetime.min.time()),
        )
    
    def _create_summary_evidence(self, events: List[RawEvent]) -> MarketEvidence:
        """Create summary evidence of upcoming events."""
        today = date.today()
        
        # Count events by time period
        next_30_days = [e for e in events if e.start_date <= today + timedelta(days=30)]
        next_90_days = [e for e in events if e.start_date <= today + timedelta(days=90)]
        
        # Find high-impact events
        high_impact = [
            e for e in events 
            if e.expected_attendance and e.expected_attendance >= 5000
        ]
        
        return MarketEvidence(
            market_id=self.market_id,
            evidence_type="event_summary",
            data={
                "total_upcoming": len(events),
                "next_30_days": len(next_30_days),
                "next_90_days": len(next_90_days),
                "high_impact_count": len(high_impact),
                "categories": list(set(e.category for e in events)),
                "next_event": {
                    "name": events[0].name,
                    "date": events[0].start_date.isoformat(),
                } if events else None,
            },
            source="event_scraper:summary",
            confidence=0.9,
            valid_from=datetime.utcnow(),
            valid_until=datetime.utcnow() + timedelta(days=1),
        )


# =============================================================================
# FACTORY FUNCTIONS
# =============================================================================

async def scrape_events(market_id: str) -> List[MarketEvidence]:
    """
    Convenience function to scrape events for a market.
    
    Usage:
        evidence = await scrape_events("30a")
        # Persist evidence...
    """
    scraper = EventScraper(market_id=market_id)
    return await scraper.scrape()
