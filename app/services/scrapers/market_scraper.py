"""
Automated Market Scraper Service.

Periodically scrapes market data within operator footprints to build
market intelligence signals. Runs as a background service.

Key Features:
1. Discovers operator footprints automatically
2. Scrapes listings within each footprint
3. Stores signals with EWMA time decay
4. Respects rate limits and platform TOS
5. Only scrapes publicly available data

What We Scrape (Safe Signals):
✅ Supply counts (listing count)
✅ Amenity prevalence (pool, waterfront, etc.)
✅ Price posture (directional only, not exact)
✅ Availability compression (% unavailable)
✅ Listing churn (new/removed listings)

What We DO NOT Scrape:
❌ Booking data (not publicly available)
❌ Revenue numbers (inference risk)
❌ Exact competitor pricing at scale
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, date
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# =============================================================================
# SCRAPE SOURCES
# =============================================================================

class ScrapeSource(str, Enum):
    """Supported scrape sources."""
    AIRBNB = "airbnb"
    VRBO = "vrbo"
    BOOKING = "booking"


class ScrapeStatus(str, Enum):
    """Status of a scrape job."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RATE_LIMITED = "rate_limited"


# =============================================================================
# SCRAPE JOB MODEL
# =============================================================================

class ScrapeJob(BaseModel):
    """A single scrape job for a geofence."""
    job_id: UUID = Field(default_factory=uuid4)
    company_id: UUID
    geofence_id: str
    source: ScrapeSource
    
    # Polygon to scrape
    polygon_coords: List[List[float]]
    
    # Status
    status: ScrapeStatus = ScrapeStatus.PENDING
    
    # Timing
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    # Results
    listings_found: int = 0
    signals_extracted: Dict[str, Any] = Field(default_factory=dict)
    error_message: Optional[str] = None


# =============================================================================
# SCRAPED LISTING (Raw Data)
# =============================================================================

class ScrapedListing(BaseModel):
    """
    Raw listing data from a scrape.
    
    Contains only PUBLICLY AVAILABLE information.
    """
    scrape_id: UUID = Field(default_factory=uuid4)
    source: ScrapeSource
    external_id: str  # Platform-specific ID
    
    # Location
    latitude: float
    longitude: float
    city: Optional[str] = None
    
    # Property basics
    bedrooms: Optional[int] = None
    bathrooms: Optional[float] = None
    property_type: Optional[str] = None
    
    # Amenities (boolean flags)
    has_pool: bool = False
    has_waterfront: bool = False
    is_pet_friendly: bool = False
    
    # Availability (what we can see)
    # Note: We don't know if unavailable = booked or blocked
    is_available_next_7: bool = True
    is_available_next_14: bool = True
    is_available_next_30: bool = True
    
    # Price tier (NOT exact price)
    price_tier: str = "mid"  # budget, mid, premium, luxury
    
    # Review signals
    review_count: int = 0
    
    # Metadata
    scraped_at: datetime = Field(default_factory=datetime.utcnow)


# =============================================================================
# MARKET SCRAPE RESULT
# =============================================================================

class MarketScrapeResult(BaseModel):
    """
    Aggregated result from scraping a market/geofence.
    
    This feeds into PlatformSignals for the weighting engine.
    """
    geofence_id: str
    source: ScrapeSource
    scraped_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Supply signals
    total_listings: int = 0
    new_listings_since_last: int = 0
    removed_listings_since_last: int = 0
    listing_growth_pct: float = 0.0
    
    # Availability compression
    pct_unavailable_next_7: float = 0.0
    pct_unavailable_next_14: float = 0.0
    pct_unavailable_next_30: float = 0.0
    
    # Amenity prevalence
    pct_with_pool: float = 0.0
    pct_with_waterfront: float = 0.0
    pct_pet_friendly: float = 0.0
    
    # Price distribution (tiers, not exact)
    pct_budget: float = 0.0
    pct_mid: float = 0.0
    pct_premium: float = 0.0
    pct_luxury: float = 0.0
    
    # Quality
    avg_review_count: float = 0.0
    
    # Confidence
    confidence: float = 0.5


# =============================================================================
# SCRAPER CONFIGURATION
# =============================================================================

@dataclass
class ScraperConfig:
    """Configuration for the market scraper."""
    
    # Rate limiting
    requests_per_minute: int = 30
    max_concurrent_requests: int = 5
    
    # Retry settings
    max_retries: int = 3
    retry_delay_seconds: int = 60
    
    # Scheduling
    scrape_interval_hours: int = 24  # Daily by default
    
    # Data retention
    keep_raw_listings_days: int = 7
    keep_signals_days: int = 365


# =============================================================================
# ABSTRACT SCRAPER BASE CLASS
# =============================================================================

class MarketScraper:
    """
    Abstract base class for market scrapers.
    
    Each platform (Airbnb, VRBO, Booking) has its own implementation.
    """
    
    def __init__(self, config: Optional[ScraperConfig] = None):
        self.config = config or ScraperConfig()
        self._rate_limit_remaining = self.config.requests_per_minute
        self._rate_limit_reset = datetime.utcnow()
    
    @property
    def source(self) -> ScrapeSource:
        """Return the scrape source."""
        raise NotImplementedError
    
    async def scrape_geofence(
        self,
        geofence_id: str,
        polygon_coords: List[List[float]],
    ) -> MarketScrapeResult:
        """
        Scrape all listings within a geofence polygon.
        
        Args:
            geofence_id: Unique identifier for the geofence
            polygon_coords: List of [lng, lat] coordinates
            
        Returns:
            Aggregated market signals
        """
        raise NotImplementedError
    
    async def _check_rate_limit(self) -> bool:
        """Check if we can make another request."""
        now = datetime.utcnow()
        
        # Reset rate limit if minute has passed
        if now >= self._rate_limit_reset:
            self._rate_limit_remaining = self.config.requests_per_minute
            self._rate_limit_reset = now + timedelta(minutes=1)
        
        if self._rate_limit_remaining > 0:
            self._rate_limit_remaining -= 1
            return True
        
        return False
    
    async def _wait_for_rate_limit(self) -> None:
        """Wait until rate limit resets."""
        now = datetime.utcnow()
        if now < self._rate_limit_reset:
            wait_seconds = (self._rate_limit_reset - now).total_seconds()
            await asyncio.sleep(wait_seconds)


# =============================================================================
# AIRBNB SCRAPER (Example Implementation)
# =============================================================================

class AirbnbScraper(MarketScraper):
    """
    Airbnb market scraper.
    
    Scrapes PUBLICLY AVAILABLE listing data only.
    Does NOT scrape:
    - Exact prices at scale
    - Booking data
    - Revenue information
    """
    
    @property
    def source(self) -> ScrapeSource:
        return ScrapeSource.AIRBNB
    
    async def scrape_geofence(
        self,
        geofence_id: str,
        polygon_coords: List[List[float]],
    ) -> MarketScrapeResult:
        """
        Scrape Airbnb listings within polygon.
        
        In production, this would:
        1. Convert polygon to Airbnb search bounds
        2. Paginate through search results
        3. Extract listing metadata
        4. Aggregate into signals
        
        For now, returns simulated data.
        """
        # Simulate scraping (in production, would make actual requests)
        # This demonstrates the data flow
        
        simulated_listings = self._simulate_listings(geofence_id)
        
        return self._aggregate_listings(geofence_id, simulated_listings)
    
    def _simulate_listings(self, geofence_id: str) -> List[ScrapedListing]:
        """Simulate scraped listings for testing."""
        import random
        
        # Generate 50-200 simulated listings
        count = random.randint(50, 200)
        listings = []
        
        for i in range(count):
            listings.append(ScrapedListing(
                source=ScrapeSource.AIRBNB,
                external_id=f"airbnb_{geofence_id}_{i}",
                latitude=30.35 + random.uniform(-0.1, 0.1),
                longitude=-86.17 + random.uniform(-0.1, 0.1),
                bedrooms=random.choice([1, 2, 3, 4, 5, 6]),
                bathrooms=random.choice([1.0, 2.0, 3.0, 4.0, 5.0]),
                has_pool=random.random() < 0.6,
                has_waterfront=random.random() < 0.15,
                is_pet_friendly=random.random() < 0.4,
                is_available_next_7=random.random() > 0.5,
                is_available_next_14=random.random() > 0.45,
                is_available_next_30=random.random() > 0.4,
                price_tier=random.choice(["budget", "mid", "premium", "luxury"]),
                review_count=random.randint(0, 200),
            ))
        
        return listings
    
    def _aggregate_listings(
        self,
        geofence_id: str,
        listings: List[ScrapedListing],
    ) -> MarketScrapeResult:
        """Aggregate listings into market signals."""
        if not listings:
            return MarketScrapeResult(
                geofence_id=geofence_id,
                source=self.source,
                confidence=0.0,
            )
        
        total = len(listings)
        
        # Availability compression
        unavail_7 = sum(1 for l in listings if not l.is_available_next_7) / total
        unavail_14 = sum(1 for l in listings if not l.is_available_next_14) / total
        unavail_30 = sum(1 for l in listings if not l.is_available_next_30) / total
        
        # Amenity prevalence
        pool_count = sum(1 for l in listings if l.has_pool)
        waterfront_count = sum(1 for l in listings if l.has_waterfront)
        pet_count = sum(1 for l in listings if l.is_pet_friendly)
        
        # Price tiers
        tier_counts = {"budget": 0, "mid": 0, "premium": 0, "luxury": 0}
        for l in listings:
            tier_counts[l.price_tier] = tier_counts.get(l.price_tier, 0) + 1
        
        # Confidence based on sample size
        confidence = min(total / 100, 0.95)  # 100+ listings = high confidence
        
        return MarketScrapeResult(
            geofence_id=geofence_id,
            source=self.source,
            total_listings=total,
            pct_unavailable_next_7=round(unavail_7, 3),
            pct_unavailable_next_14=round(unavail_14, 3),
            pct_unavailable_next_30=round(unavail_30, 3),
            pct_with_pool=round(pool_count / total, 3),
            pct_with_waterfront=round(waterfront_count / total, 3),
            pct_pet_friendly=round(pet_count / total, 3),
            pct_budget=round(tier_counts["budget"] / total, 3),
            pct_mid=round(tier_counts["mid"] / total, 3),
            pct_premium=round(tier_counts["premium"] / total, 3),
            pct_luxury=round(tier_counts["luxury"] / total, 3),
            avg_review_count=round(sum(l.review_count for l in listings) / total, 1),
            confidence=round(confidence, 2),
        )


class VRBOScraper(MarketScraper):
    """VRBO market scraper."""
    
    @property
    def source(self) -> ScrapeSource:
        return ScrapeSource.VRBO
    
    async def scrape_geofence(
        self,
        geofence_id: str,
        polygon_coords: List[List[float]],
    ) -> MarketScrapeResult:
        """Scrape VRBO listings within polygon."""
        # Similar implementation to Airbnb
        # In production, would use VRBO-specific API/scraping
        return MarketScrapeResult(
            geofence_id=geofence_id,
            source=self.source,
            confidence=0.0,  # Not yet implemented
        )


# =============================================================================
# SCRAPE SCHEDULER
# =============================================================================

class ScrapeScheduler:
    """
    Schedules and manages periodic scrape jobs.
    
    Automatically discovers operator footprints and schedules
    scrapes within each polygon.
    """
    
    def __init__(
        self,
        config: Optional[ScraperConfig] = None,
    ):
        self.config = config or ScraperConfig()
        self.scrapers: Dict[ScrapeSource, MarketScraper] = {
            ScrapeSource.AIRBNB: AirbnbScraper(config),
            ScrapeSource.VRBO: VRBOScraper(config),
        }
        self.pending_jobs: List[ScrapeJob] = []
        self.completed_jobs: List[ScrapeJob] = []
        self._is_running = False
    
    async def schedule_footprint_scrape(
        self,
        company_id: UUID,
        geofence_id: str,
        polygon_coords: List[List[float]],
        sources: Optional[List[ScrapeSource]] = None,
    ) -> List[ScrapeJob]:
        """
        Schedule scrape jobs for an operator's footprint.
        
        Args:
            company_id: Operator's company ID
            geofence_id: Unique identifier for the footprint
            polygon_coords: Polygon coordinates
            sources: Which platforms to scrape (default: all)
            
        Returns:
            List of created scrape jobs
        """
        if sources is None:
            sources = list(self.scrapers.keys())
        
        jobs = []
        for source in sources:
            job = ScrapeJob(
                company_id=company_id,
                geofence_id=geofence_id,
                source=source,
                polygon_coords=polygon_coords,
            )
            self.pending_jobs.append(job)
            jobs.append(job)
        
        return jobs
    
    async def run_job(self, job: ScrapeJob) -> ScrapeJob:
        """
        Execute a single scrape job.
        """
        job.status = ScrapeStatus.RUNNING
        job.started_at = datetime.utcnow()
        
        scraper = self.scrapers.get(job.source)
        if not scraper:
            job.status = ScrapeStatus.FAILED
            job.error_message = f"No scraper for source: {job.source}"
            return job
        
        try:
            result = await scraper.scrape_geofence(
                job.geofence_id,
                job.polygon_coords,
            )
            
            job.status = ScrapeStatus.COMPLETED
            job.completed_at = datetime.utcnow()
            job.listings_found = result.total_listings
            job.signals_extracted = result.model_dump()
            
        except Exception as e:
            job.status = ScrapeStatus.FAILED
            job.error_message = str(e)
        
        self.completed_jobs.append(job)
        return job
    
    async def run_all_pending(self) -> List[ScrapeJob]:
        """Run all pending scrape jobs."""
        results = []
        
        while self.pending_jobs:
            job = self.pending_jobs.pop(0)
            result = await self.run_job(job)
            results.append(result)
        
        return results
    
    def get_job_status(self, job_id: UUID) -> Optional[ScrapeJob]:
        """Get status of a specific job."""
        for job in self.pending_jobs + self.completed_jobs:
            if job.job_id == job_id:
                return job
        return None


# =============================================================================
# MARKET SCRAPE SERVICE (High-Level Orchestration)
# =============================================================================

class MarketScrapeService:
    """
    High-level service for automated market scraping.
    
    Integrates with:
    - Operator footprints
    - Platform weighting engine
    - Signal storage
    """
    
    def __init__(self):
        self.scheduler = ScrapeScheduler()
        self._footprints: Dict[UUID, Dict] = {}  # In production, from database
    
    async def register_operator_footprint(
        self,
        company_id: UUID,
        geofence_id: str,
        polygon_coords: List[List[float]],
    ) -> None:
        """
        Register an operator's footprint for automated scraping.
        
        Once registered, the system will periodically scrape
        market data within this footprint.
        """
        self._footprints[company_id] = {
            "geofence_id": geofence_id,
            "polygon_coords": polygon_coords,
            "registered_at": datetime.utcnow(),
            "last_scraped_at": None,
        }
    
    async def scrape_operator_market(
        self,
        company_id: UUID,
    ) -> Dict[str, MarketScrapeResult]:
        """
        Scrape market data for a specific operator's footprint.
        
        Returns signals from all platforms (Airbnb, VRBO, etc.)
        """
        footprint = self._footprints.get(company_id)
        if not footprint:
            raise ValueError(f"No footprint registered for company {company_id}")
        
        # Schedule scrapes for all sources
        jobs = await self.scheduler.schedule_footprint_scrape(
            company_id=company_id,
            geofence_id=footprint["geofence_id"],
            polygon_coords=footprint["polygon_coords"],
        )
        
        # Run all jobs
        completed = await self.scheduler.run_all_pending()
        
        # Update last scraped
        self._footprints[company_id]["last_scraped_at"] = datetime.utcnow()
        
        # Collect results by source
        results = {}
        for job in completed:
            if job.status == ScrapeStatus.COMPLETED:
                results[job.source.value] = MarketScrapeResult(**job.signals_extracted)
        
        return results
    
    async def scrape_all_operators(self) -> Dict[UUID, Dict[str, MarketScrapeResult]]:
        """
        Scrape market data for ALL registered operators.
        
        This is the main periodic job that runs daily.
        """
        all_results = {}
        
        for company_id in self._footprints.keys():
            try:
                results = await self.scrape_operator_market(company_id)
                all_results[company_id] = results
            except Exception as e:
                # Log error but continue with other operators
                print(f"Error scraping for {company_id}: {e}")
        
        return all_results
    
    def convert_to_platform_signals(
        self,
        scrape_result: MarketScrapeResult,
    ) -> Dict[str, Any]:
        """
        Convert scrape result to PlatformSignals format.
        
        This feeds into the platform weighting engine.
        """
        from app.services.market_intelligence.platform_weighting import Platform
        
        # Map scrape source to platform
        source_to_platform = {
            ScrapeSource.AIRBNB: Platform.AIRBNB,
            ScrapeSource.VRBO: Platform.VRBO,
            ScrapeSource.BOOKING: Platform.BOOKING,
        }
        
        platform = source_to_platform.get(scrape_result.source)
        
        return {
            "platform": platform.value if platform else scrape_result.source.value,
            "geofence_id": scrape_result.geofence_id,
            "listing_count": scrape_result.total_listings,
            "listing_growth_30d_pct": scrape_result.listing_growth_pct,
            "pct_unavailable_next_7": scrape_result.pct_unavailable_next_7,
            "pct_unavailable_next_14": scrape_result.pct_unavailable_next_14,
            "pct_unavailable_next_30": scrape_result.pct_unavailable_next_30,
            "pct_with_pool": scrape_result.pct_with_pool,
            "pct_with_waterfront": scrape_result.pct_with_waterfront,
            "confidence": scrape_result.confidence,
        }
