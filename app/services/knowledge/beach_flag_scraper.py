"""
Beach Flag Scraper

Scrapes current beach flag status from South Walton Fire District (swfd.org).
Only used for IN-STAY guests - pre-arrival guests don't need beach conditions.

Data source: https://www.swfd.org/beach-safety/surf-conditions
"""

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Tuple
from enum import Enum
import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class BeachFlag(str, Enum):
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"
    DOUBLE_RED = "double_red"
    PURPLE = "purple"


@dataclass
class BeachConditions:
    """Current beach conditions"""
    primary_flag: BeachFlag
    has_purple: bool  # Purple can be combined with other flags
    raw_text: str
    source: str
    fetched_at: datetime
    
    @property
    def display_flag(self) -> str:
        """Human readable flag status"""
        flag_names = {
            BeachFlag.GREEN: "Green Flag",
            BeachFlag.YELLOW: "Yellow Flag",
            BeachFlag.RED: "Red Flag",
            BeachFlag.DOUBLE_RED: "Double Red Flag",
        }
        text = flag_names.get(self.primary_flag, "Unknown")
        if self.has_purple:
            text += " + Purple (Marine Life)"
        return text
    
    @property
    def swimming_allowed(self) -> bool:
        return self.primary_flag != BeachFlag.DOUBLE_RED
    
    @property
    def swimming_recommended(self) -> bool:
        return self.primary_flag in (BeachFlag.GREEN, BeachFlag.YELLOW)


class BeachFlagScraper:
    """
    Scrapes beach flag status from official sources.
    
    Primary: swfd.org (South Walton Fire District)
    Backup: 30a.com/beachflag/
    
    Caches results for 15 minutes to avoid hammering the server.
    """
    
    SWFD_URL = "https://www.swfd.org/beach-safety/surf-conditions"
    BACKUP_URL = "https://30a.com/beachflag/"
    CACHE_DURATION = timedelta(minutes=15)
    
    def __init__(self):
        self._cache: Optional[BeachConditions] = None
        self._cache_time: Optional[datetime] = None
        
    async def get_current_conditions(self, force_refresh: bool = False) -> BeachConditions:
        """
        Get current beach conditions.
        
        Uses cached value if available and fresh.
        """
        now = datetime.utcnow()
        
        # Check cache
        if not force_refresh and self._cache and self._cache_time:
            if now - self._cache_time < self.CACHE_DURATION:
                logger.debug("Returning cached beach conditions")
                return self._cache
        
        # Try primary source (SWFD)
        try:
            conditions = await self._scrape_swfd()
            self._cache = conditions
            self._cache_time = now
            return conditions
        except Exception as e:
            logger.warning(f"SWFD scrape failed: {e}, trying backup")
        
        # Try backup source (30a.com)
        try:
            conditions = await self._scrape_30a()
            self._cache = conditions
            self._cache_time = now
            return conditions
        except Exception as e:
            logger.error(f"Backup scrape also failed: {e}")
        
        # Return cached value even if stale, or default to yellow
        if self._cache:
            logger.warning("Returning stale cached conditions")
            return self._cache
        
        # Ultimate fallback
        return BeachConditions(
            primary_flag=BeachFlag.YELLOW,
            has_purple=False,
            raw_text="Unable to fetch current conditions",
            source="fallback",
            fetched_at=now,
        )
    
    async def _scrape_swfd(self) -> BeachConditions:
        """Scrape South Walton Fire District website"""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                self.SWFD_URL,
                timeout=10.0,
                headers={"User-Agent": "BeachHabitats/1.0 (Guest Safety Service)"}
            )
            response.raise_for_status()
            html = response.text
        
        soup = BeautifulSoup(html, "html.parser")
        
        # Look for the flag status banner
        # Example: "Current surf conditions are yellow and purple."
        banner = soup.find("a", href="/beach-safety/surf-conditions")
        if banner:
            banner_text = banner.get_text().lower()
        else:
            # Try finding in page content
            banner_text = soup.get_text().lower()
        
        # Parse flags from text
        primary_flag, has_purple = self._parse_flag_text(banner_text)
        
        return BeachConditions(
            primary_flag=primary_flag,
            has_purple=has_purple,
            raw_text=banner_text[:200] if banner_text else "",
            source="swfd.org",
            fetched_at=datetime.utcnow(),
        )
    
    async def _scrape_30a(self) -> BeachConditions:
        """Scrape 30a.com beach flag page"""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                self.BACKUP_URL,
                timeout=10.0,
                headers={"User-Agent": "BeachHabitats/1.0 (Guest Safety Service)"}
            )
            response.raise_for_status()
            html = response.text
        
        soup = BeautifulSoup(html, "html.parser")
        page_text = soup.get_text().lower()
        
        primary_flag, has_purple = self._parse_flag_text(page_text)
        
        return BeachConditions(
            primary_flag=primary_flag,
            has_purple=has_purple,
            raw_text=page_text[:200],
            source="30a.com",
            fetched_at=datetime.utcnow(),
        )
    
    def _parse_flag_text(self, text: str) -> Tuple[BeachFlag, bool]:
        """Parse flag status from text"""
        text = text.lower()
        
        # Check for purple (can be combined with any flag)
        has_purple = "purple" in text
        
        # Determine primary flag (in order of severity)
        if "double red" in text or "water closed" in text:
            return BeachFlag.DOUBLE_RED, has_purple
        elif "red flag" in text or ("red" in text and "high hazard" in text):
            # Make sure it's not "double red"
            if "double" not in text:
                return BeachFlag.RED, has_purple
        elif "yellow" in text or "moderate" in text:
            return BeachFlag.YELLOW, has_purple
        elif "green" in text or ("low hazard" in text or "calm" in text):
            return BeachFlag.GREEN, has_purple
        
        # Look for patterns like "conditions are yellow"
        match = re.search(r"conditions?\s+(?:are\s+)?(\w+)", text)
        if match:
            flag_word = match.group(1).lower()
            if flag_word == "green":
                return BeachFlag.GREEN, has_purple
            elif flag_word == "yellow":
                return BeachFlag.YELLOW, has_purple
            elif flag_word == "red":
                return BeachFlag.RED, has_purple
        
        # Default to yellow (safe assumption for unknown)
        return BeachFlag.YELLOW, has_purple


def get_flag_guidance(conditions: BeachConditions) -> dict:
    """
    Get guest-friendly guidance based on current conditions.
    Only called for IN-STAY guests.
    """
    guidance = {
        BeachFlag.GREEN: {
            "emoji": "🟢",
            "status": "Great Beach Day!",
            "headline": "Calm conditions - perfect for swimming",
            "swimming": "✅ Swimming is great today",
            "message": (
                "Green flag means calm conditions with low hazard. "
                "Perfect day for swimming, paddleboarding, and water activities!"
            ),
            "tips": [
                "Still swim near a lifeguard when possible",
                "Stay hydrated in the sun",
            ],
            "activities": ["Swimming", "Paddleboarding", "Kayaking", "Snorkeling"],
        },
        BeachFlag.YELLOW: {
            "emoji": "🟡",
            "status": "Moderate Conditions",
            "headline": "Swim with caution",
            "swimming": "⚠️ Swimming OK, use caution",
            "message": (
                "Yellow flag means moderate surf and/or currents. "
                "Swimming is fine but be aware of conditions."
            ),
            "tips": [
                "Weak swimmers should stay close to shore",
                "Watch children carefully",
                "Be aware of currents",
            ],
            "activities": ["Beach activities", "Wading", "Swimming (with caution)"],
        },
        BeachFlag.RED: {
            "emoji": "🔴",
            "status": "High Hazard",
            "headline": "Strong currents - swimming not recommended",
            "swimming": "❌ Swimming not recommended",
            "message": (
                "Red flag means high surf and/or strong currents. "
                "Water is technically open, but swimming is dangerous."
            ),
            "tips": [
                "Stay out of the water if possible",
                "If you must enter, stay knee-deep or less",
                "Strong rip currents are likely",
            ],
            "alternatives": [
                "Beach walking",
                "Biking the 30A path",
                "Paddleboarding on Western Lake (calm water)",
                "Exploring Seaside or Rosemary shops",
            ],
        },
        BeachFlag.DOUBLE_RED: {
            "emoji": "🚩",
            "status": "Beach Closed",
            "headline": "Water closed to public",
            "swimming": "🚫 NO SWIMMING - Water closed",
            "message": (
                "Double red flag means the water is CLOSED. "
                "Entering the water can result in a $500 fine."
            ),
            "tips": [
                "Do NOT enter the water",
                "$500+ fines for violations",
                "Check back tomorrow",
            ],
            "alternatives": [
                "Bike the 30A path (19 scenic miles)",
                "Paddleboard/kayak on Western Lake",
                "Explore Grayton Beach State Park trails",
                "Shopping in Rosemary Beach or Seaside",
            ],
        },
    }
    
    base = guidance.get(conditions.primary_flag, guidance[BeachFlag.YELLOW])
    
    # Add purple flag info if present
    if conditions.has_purple:
        base["purple_warning"] = True
        base["purple_message"] = (
            "🟣 Purple flag also flying - jellyfish spotted. "
            "Shuffle your feet when entering water."
        )
    
    return base


# Singleton
_scraper: Optional[BeachFlagScraper] = None

def get_beach_flag_scraper() -> BeachFlagScraper:
    global _scraper
    if _scraper is None:
        _scraper = BeachFlagScraper()
    return _scraper


async def get_current_beach_flag() -> BeachConditions:
    """Convenience function to get current conditions"""
    scraper = get_beach_flag_scraper()
    return await scraper.get_current_conditions()
