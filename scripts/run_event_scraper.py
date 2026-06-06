#!/usr/bin/env python3
"""
run_event_scraper.py — Railway Cron Job Entry Point

Runs the event scraper for all enabled markets.
Railway cron: schedule this to run every Monday at 6am CT.

Railway.toml cron config:
  [[services]]
  name = "event-scraper"
  [services.cron]
  schedule = "0 12 * * 1"   # Monday 6am CT = 12:00 UTC

Usage (manual):
  python scripts/run_event_scraper.py
  python scripts/run_event_scraper.py --market 30a_fl
  python scripts/run_event_scraper.py --all
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("event_scraper_cron")


async def main():
    import argparse
    from dotenv import load_dotenv
    load_dotenv()  # Load .env so DATABASE_URL is available

    parser = argparse.ArgumentParser()
    parser.add_argument("--market", default=None, help="Specific market ID to scrape")
    parser.add_argument("--all", action="store_true", help="Scrape all enabled markets")
    parser.add_argument("--days-ahead", type=int, default=90)
    args = parser.parse_args()

    from tools.event_scraper import EventScrapeOrchestrator, KNOWN_MARKETS

    async with EventScrapeOrchestrator(days_ahead=args.days_ahead) as orc:
        if args.market:
            logger.info(f"Scraping market: {args.market}")
            events = await orc.scrape_market(args.market)
            logger.info(f"Done: {len(events)} events for {args.market}")

        elif args.all:
            logger.info("Scraping all due markets...")
            results = await orc.scrape_all_markets()
            total = sum(v for v in results.values() if v > 0)
            logger.info(f"Done: {total} total events across {len(results)} markets")
            for mid, count in results.items():
                status = f"{count} events" if count >= 0 else "FAILED"
                logger.info(f"  {mid}: {status}")

        else:
            # Default: scrape 30A (the primary market at launch)
            logger.info("Scraping 30a_fl (default)...")
            events = await orc.scrape_market("30a_fl")
            logger.info(f"Done: {len(events)} events for 30a_fl")

            # Also scrape Destin since it's nearby and guests travel between
            logger.info("Scraping destin_fl...")
            events = await orc.scrape_market("destin_fl")
            logger.info(f"Done: {len(events)} events for destin_fl")


if __name__ == "__main__":
    asyncio.run(main())
