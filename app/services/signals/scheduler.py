"""
Signal Collection Scheduler

Orchestrates automated data collection across all sources:
- OTA scrapers (Airbnb, VRBO)
- Federal data (Census, BTS)
- Processes signals into the pipeline

Run with:
    python -m app.services.signals.scheduler

Or with specific jobs:
    python -m app.services.signals.scheduler --job scrape_30a
    python -m app.services.signals.scheduler --job census_all
"""

import asyncio
import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================

@dataclass
class MarketConfig:
    """Configuration for a market to scrape."""
    market_id: str
    market_name: str
    latitude: float
    longitude: float
    radius_miles: float
    state_fips: str
    county_fips: str
    zipcodes: List[str] = field(default_factory=list)
    enabled: bool = True


# Pre-configured markets
MARKETS = {
    "30a": MarketConfig(
        market_id="30a",
        market_name="30A Beaches",
        latitude=30.2833,
        longitude=-86.0167,
        radius_miles=15,
        state_fips="12",
        county_fips="131",
        zipcodes=["32459", "32461", "32550"],
    ),
    "destin": MarketConfig(
        market_id="destin",
        market_name="Destin",
        latitude=30.3935,
        longitude=-86.4958,
        radius_miles=10,
        state_fips="12",
        county_fips="091",
        zipcodes=["32541", "32550"],
    ),
    "panama_city_beach": MarketConfig(
        market_id="panama_city_beach",
        market_name="Panama City Beach",
        latitude=30.1766,
        longitude=-85.8055,
        radius_miles=12,
        state_fips="12",
        county_fips="005",
        zipcodes=["32407", "32408", "32413"],
    ),
    "gulf_shores": MarketConfig(
        market_id="gulf_shores",
        market_name="Gulf Shores",
        latitude=30.2460,
        longitude=-87.7008,
        radius_miles=12,
        state_fips="01",
        county_fips="003",
        zipcodes=["36542", "36561"],
    ),
    "orange_beach": MarketConfig(
        market_id="orange_beach",
        market_name="Orange Beach",
        latitude=30.2944,
        longitude=-87.5731,
        radius_miles=8,
        state_fips="01",
        county_fips="003",
        zipcodes=["36561"],
    ),
}


@dataclass
class SchedulerConfig:
    """Scheduler configuration."""
    # Paths
    data_dir: str = "./signal_data"
    log_dir: str = "./logs"
    
    # Scheduling
    scrape_interval_hours: int = 24
    census_interval_days: int = 30
    
    # Parallelism
    max_concurrent_scrapes: int = 2
    
    # Retry
    max_retries: int = 3
    retry_delay_seconds: int = 300


# =============================================================================
# JOB DEFINITIONS
# =============================================================================

@dataclass
class Job:
    """A scheduled job."""
    job_id: str
    job_type: str
    market_id: Optional[str]
    status: str = "pending"
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result: Optional[Dict] = None
    error: Optional[str] = None
    retries: int = 0


class JobRunner:
    """
    Runs data collection jobs.
    
    Supports:
    - OTA scraping (Airbnb/VRBO)
    - Census data collection
    - Signal processing
    """
    
    def __init__(self, config: SchedulerConfig):
        self.config = config
        self.jobs: Dict[str, Job] = {}
        
        # Ensure directories exist
        Path(config.data_dir).mkdir(parents=True, exist_ok=True)
        Path(config.log_dir).mkdir(parents=True, exist_ok=True)
    
    async def run_ota_scrape(self, market: MarketConfig) -> Dict:
        """
        Run OTA scraping for a market.
        
        This calls the signal_scraper module.
        """
        logger.info(f"Starting OTA scrape for {market.market_name}")
        
        # Import scraper (lazy import to avoid circular deps)
        try:
            # In production, import from tools/signal_scraper.py
            # For now, simulate the process
            
            result = {
                "market_id": market.market_id,
                "source": "ota_scrape",
                "started_at": datetime.utcnow().isoformat(),
                "status": "simulated",
                "message": "In production, this calls signal_scraper.py",
            }
            
            # Simulate scrape time
            await asyncio.sleep(2)
            
            result["completed_at"] = datetime.utcnow().isoformat()
            
            logger.info(f"OTA scrape complete for {market.market_name}")
            return result
            
        except Exception as e:
            logger.error(f"OTA scrape failed for {market.market_name}: {e}")
            raise
    
    async def run_census_collection(self, market: MarketConfig) -> Dict:
        """
        Collect Census ACS data for a market.
        """
        logger.info(f"Starting Census collection for {market.market_name}")
        
        try:
            # In production, this calls federal_data_scraper.py
            result = {
                "market_id": market.market_id,
                "source": "census_acs",
                "state_fips": market.state_fips,
                "county_fips": market.county_fips,
                "started_at": datetime.utcnow().isoformat(),
                "status": "simulated",
            }
            
            await asyncio.sleep(1)
            
            result["completed_at"] = datetime.utcnow().isoformat()
            
            logger.info(f"Census collection complete for {market.market_name}")
            return result
            
        except Exception as e:
            logger.error(f"Census collection failed for {market.market_name}: {e}")
            raise
    
    async def run_signal_processing(self, market_id: str) -> Dict:
        """
        Process raw data into canonical signals.
        """
        logger.info(f"Processing signals for {market_id}")
        
        try:
            # In production, this:
            # 1. Loads scraped data from files
            # 2. Runs signal_converter.py
            # 3. Stores in signal_pipeline
            
            result = {
                "market_id": market_id,
                "process": "signal_conversion",
                "started_at": datetime.utcnow().isoformat(),
                "status": "simulated",
            }
            
            await asyncio.sleep(1)
            
            result["completed_at"] = datetime.utcnow().isoformat()
            
            logger.info(f"Signal processing complete for {market_id}")
            return result
            
        except Exception as e:
            logger.error(f"Signal processing failed for {market_id}: {e}")
            raise
    
    async def run_full_collection(self, market: MarketConfig) -> Dict:
        """
        Run full data collection pipeline for a market:
        1. OTA scrape
        2. Census data
        3. Signal processing
        """
        logger.info(f"Starting full collection for {market.market_name}")
        
        results = {
            "market_id": market.market_id,
            "started_at": datetime.utcnow().isoformat(),
            "steps": {},
        }
        
        try:
            # Step 1: OTA Scrape
            results["steps"]["ota_scrape"] = await self.run_ota_scrape(market)
            
            # Step 2: Census (less frequent, but include in full run)
            results["steps"]["census"] = await self.run_census_collection(market)
            
            # Step 3: Process signals
            results["steps"]["processing"] = await self.run_signal_processing(market.market_id)
            
            results["status"] = "completed"
            results["completed_at"] = datetime.utcnow().isoformat()
            
        except Exception as e:
            results["status"] = "failed"
            results["error"] = str(e)
            raise
        
        return results
    
    async def run_job(self, job: Job) -> Job:
        """Execute a job."""
        job.status = "running"
        job.started_at = datetime.utcnow()
        
        try:
            if job.job_type == "ota_scrape" and job.market_id:
                market = MARKETS.get(job.market_id)
                if market:
                    job.result = await self.run_ota_scrape(market)
                else:
                    raise ValueError(f"Unknown market: {job.market_id}")
            
            elif job.job_type == "census" and job.market_id:
                market = MARKETS.get(job.market_id)
                if market:
                    job.result = await self.run_census_collection(market)
                else:
                    raise ValueError(f"Unknown market: {job.market_id}")
            
            elif job.job_type == "full_collection" and job.market_id:
                market = MARKETS.get(job.market_id)
                if market:
                    job.result = await self.run_full_collection(market)
                else:
                    raise ValueError(f"Unknown market: {job.market_id}")
            
            elif job.job_type == "scrape_all":
                job.result = await self.run_all_markets()
            
            else:
                raise ValueError(f"Unknown job type: {job.job_type}")
            
            job.status = "completed"
            
        except Exception as e:
            job.status = "failed"
            job.error = str(e)
            logger.error(f"Job {job.job_id} failed: {e}")
        
        job.completed_at = datetime.utcnow()
        return job
    
    async def run_all_markets(self) -> Dict:
        """Run collection for all enabled markets."""
        results = {
            "started_at": datetime.utcnow().isoformat(),
            "markets": {},
        }
        
        enabled_markets = [m for m in MARKETS.values() if m.enabled]
        
        # Run in batches to respect rate limits
        batch_size = self.config.max_concurrent_scrapes
        
        for i in range(0, len(enabled_markets), batch_size):
            batch = enabled_markets[i:i + batch_size]
            
            tasks = [self.run_full_collection(m) for m in batch]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for market, result in zip(batch, batch_results):
                if isinstance(result, Exception):
                    results["markets"][market.market_id] = {
                        "status": "failed",
                        "error": str(result),
                    }
                else:
                    results["markets"][market.market_id] = result
            
            # Delay between batches
            if i + batch_size < len(enabled_markets):
                await asyncio.sleep(60)  # 1 minute between batches
        
        results["completed_at"] = datetime.utcnow().isoformat()
        return results


# =============================================================================
# SCHEDULER
# =============================================================================

class SignalScheduler:
    """
    Schedules and manages signal collection jobs.
    
    In production, this would be replaced with:
    - Celery Beat for task scheduling
    - Or Temporal.io for workflow orchestration
    - Or Kubernetes CronJobs
    """
    
    def __init__(self, config: Optional[SchedulerConfig] = None):
        self.config = config or SchedulerConfig()
        self.runner = JobRunner(self.config)
        self.running = False
    
    async def schedule_job(
        self,
        job_type: str,
        market_id: Optional[str] = None,
    ) -> Job:
        """Schedule a new job."""
        job = Job(
            job_id=str(uuid4()),
            job_type=job_type,
            market_id=market_id,
        )
        
        self.runner.jobs[job.job_id] = job
        logger.info(f"Scheduled job {job.job_id}: {job_type} for {market_id or 'all'}")
        
        return job
    
    async def run_scheduled_job(self, job: Job) -> Job:
        """Run a scheduled job."""
        return await self.runner.run_job(job)
    
    async def run_daily_collection(self):
        """Run daily data collection for all markets."""
        logger.info("Starting daily collection run")
        
        job = await self.schedule_job("scrape_all")
        result = await self.run_scheduled_job(job)
        
        # Log results
        if result.status == "completed":
            logger.info("Daily collection completed successfully")
        else:
            logger.error(f"Daily collection failed: {result.error}")
        
        return result
    
    async def run_loop(self):
        """
        Run the scheduler loop.
        
        In production, use Celery Beat or cron instead.
        """
        self.running = True
        logger.info("Scheduler started")
        
        while self.running:
            try:
                # Run daily collection
                await self.run_daily_collection()
                
                # Wait for next run
                logger.info(f"Next run in {self.config.scrape_interval_hours} hours")
                await asyncio.sleep(self.config.scrape_interval_hours * 3600)
                
            except asyncio.CancelledError:
                logger.info("Scheduler cancelled")
                break
            except Exception as e:
                logger.error(f"Scheduler error: {e}")
                await asyncio.sleep(300)  # Wait 5 minutes on error
    
    def stop(self):
        """Stop the scheduler."""
        self.running = False


# =============================================================================
# CLI
# =============================================================================

async def run_cli(args):
    """Run CLI commands."""
    scheduler = SignalScheduler()
    
    if args.job == "list_markets":
        print("\nConfigured Markets:")
        print("-" * 60)
        for market_id, market in MARKETS.items():
            status = "✅" if market.enabled else "❌"
            print(f"{status} {market_id}: {market.market_name}")
            print(f"   Location: {market.latitude}, {market.longitude}")
            print(f"   Radius: {market.radius_miles} miles")
            print()
    
    elif args.job == "scrape_all":
        print("\nRunning collection for all markets...")
        job = await scheduler.schedule_job("scrape_all")
        result = await scheduler.run_scheduled_job(job)
        print(json.dumps(result.result, indent=2, default=str))
    
    elif args.job.startswith("scrape_"):
        market_id = args.job.replace("scrape_", "")
        if market_id not in MARKETS:
            print(f"Unknown market: {market_id}")
            print(f"Available: {', '.join(MARKETS.keys())}")
            return
        
        print(f"\nRunning collection for {market_id}...")
        job = await scheduler.schedule_job("full_collection", market_id)
        result = await scheduler.run_scheduled_job(job)
        print(json.dumps(result.result, indent=2, default=str))
    
    elif args.job == "daemon":
        print("\nStarting scheduler daemon...")
        print("Press Ctrl+C to stop")
        try:
            await scheduler.run_loop()
        except KeyboardInterrupt:
            scheduler.stop()
            print("\nScheduler stopped")
    
    else:
        print(f"Unknown job: {args.job}")
        print("Available jobs: list_markets, scrape_all, scrape_<market_id>, daemon")


def main():
    parser = argparse.ArgumentParser(description="Signal Collection Scheduler")
    parser.add_argument(
        '--job',
        default='list_markets',
        help='Job to run: list_markets, scrape_all, scrape_<market_id>, daemon'
    )
    
    args = parser.parse_args()
    asyncio.run(run_cli(args))


if __name__ == "__main__":
    main()
