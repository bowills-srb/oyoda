#!/usr/bin/env python3
"""
Beach Habitats Scraper Scheduler

Schedules automated scraping jobs:
- Bookings/availability: Daily at 6 AM
- Pricing: Weekly on Sundays at 7 AM

USAGE:
    python tools/scheduler.py --install-launchd    # macOS LaunchAgent
    python tools/scheduler.py --install-cron       # Linux cron
    python tools/scheduler.py --run-bookings       # Run booking scraper now
    python tools/scheduler.py --run-pricing        # Run pricing scraper now
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path
from datetime import datetime

PROJECT_DIR = Path(__file__).parent.parent
TOOLS_DIR = PROJECT_DIR / "tools"
VENV_PYTHON = PROJECT_DIR / ".venv" / "bin" / "python"


def run_booking_scraper():
    """Run the booking/availability scraper."""
    print(f"[{datetime.now()}] Running booking scraper...")
    
    script = TOOLS_DIR / "bh_booking_scraper.py"
    result = subprocess.run(
        [str(VENV_PYTHON), str(script)],
        cwd=str(PROJECT_DIR),
        capture_output=True,
        text=True
    )
    
    print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    
    return result.returncode == 0


def run_pricing_scraper():
    """Run the pricing/ADR scraper."""
    print(f"[{datetime.now()}] Running pricing scraper...")
    
    script = TOOLS_DIR / "bh_pricing_scraper.py"
    result = subprocess.run(
        [str(VENV_PYTHON), str(script)],
        cwd=str(PROJECT_DIR),
        capture_output=True,
        text=True
    )
    
    print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    
    return result.returncode == 0


def install_launchd():
    """Install macOS LaunchAgent for scheduled scraping."""
    
    # Booking scraper - daily at 6 AM
    booking_plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.beachhabitats.booking-scraper</string>
    <key>ProgramArguments</key>
    <array>
        <string>{VENV_PYTHON}</string>
        <string>{TOOLS_DIR}/scheduler.py</string>
        <string>--run-bookings</string>
    </array>
    <key>WorkingDirectory</key>
    <string>{PROJECT_DIR}</string>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>6</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>{PROJECT_DIR}/logs/booking-scraper.log</string>
    <key>StandardErrorPath</key>
    <string>{PROJECT_DIR}/logs/booking-scraper.err</string>
</dict>
</plist>
"""
    
    # Pricing scraper - weekly on Sunday at 7 AM
    pricing_plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.beachhabitats.pricing-scraper</string>
    <key>ProgramArguments</key>
    <array>
        <string>{VENV_PYTHON}</string>
        <string>{TOOLS_DIR}/scheduler.py</string>
        <string>--run-pricing</string>
    </array>
    <key>WorkingDirectory</key>
    <string>{PROJECT_DIR}</string>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Weekday</key>
        <integer>0</integer>
        <key>Hour</key>
        <integer>7</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>{PROJECT_DIR}/logs/pricing-scraper.log</string>
    <key>StandardErrorPath</key>
    <string>{PROJECT_DIR}/logs/pricing-scraper.err</string>
</dict>
</plist>
"""
    
    # Create logs directory
    logs_dir = PROJECT_DIR / "logs"
    logs_dir.mkdir(exist_ok=True)
    
    # Write plist files
    launch_agents = Path.home() / "Library" / "LaunchAgents"
    launch_agents.mkdir(exist_ok=True)
    
    booking_path = launch_agents / "com.beachhabitats.booking-scraper.plist"
    pricing_path = launch_agents / "com.beachhabitats.pricing-scraper.plist"
    
    booking_path.write_text(booking_plist)
    pricing_path.write_text(pricing_plist)
    
    print(f"✓ Created {booking_path}")
    print(f"✓ Created {pricing_path}")
    
    # Load the agents
    subprocess.run(["launchctl", "load", str(booking_path)])
    subprocess.run(["launchctl", "load", str(pricing_path)])
    
    print("\n✓ LaunchAgents installed and loaded!")
    print("\nSchedule:")
    print("  - Bookings: Daily at 6:00 AM")
    print("  - Pricing: Sundays at 7:00 AM")
    print("\nTo uninstall:")
    print(f"  launchctl unload {booking_path}")
    print(f"  launchctl unload {pricing_path}")


def install_cron():
    """Install Linux cron jobs for scheduled scraping."""
    
    cron_jobs = f"""
# Beach Habitats Scrapers
# Booking scraper - daily at 6 AM
0 6 * * * cd {PROJECT_DIR} && {VENV_PYTHON} {TOOLS_DIR}/scheduler.py --run-bookings >> {PROJECT_DIR}/logs/booking-scraper.log 2>&1

# Pricing scraper - weekly on Sunday at 7 AM
0 7 * * 0 cd {PROJECT_DIR} && {VENV_PYTHON} {TOOLS_DIR}/scheduler.py --run-pricing >> {PROJECT_DIR}/logs/pricing-scraper.log 2>&1
"""
    
    # Create logs directory
    logs_dir = PROJECT_DIR / "logs"
    logs_dir.mkdir(exist_ok=True)
    
    print("Add these lines to your crontab (run 'crontab -e'):")
    print(cron_jobs)
    print("\nOr run:")
    print(f"  (crontab -l 2>/dev/null; echo '{cron_jobs.strip()}') | crontab -")


def main():
    parser = argparse.ArgumentParser(description="Beach Habitats Scraper Scheduler")
    parser.add_argument("--install-launchd", action="store_true", help="Install macOS LaunchAgent")
    parser.add_argument("--install-cron", action="store_true", help="Show cron installation")
    parser.add_argument("--run-bookings", action="store_true", help="Run booking scraper now")
    parser.add_argument("--run-pricing", action="store_true", help="Run pricing scraper now")
    args = parser.parse_args()
    
    if args.install_launchd:
        install_launchd()
    elif args.install_cron:
        install_cron()
    elif args.run_bookings:
        success = run_booking_scraper()
        sys.exit(0 if success else 1)
    elif args.run_pricing:
        success = run_pricing_scraper()
        sys.exit(0 if success else 1)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
