# 🚀 Quick Start: Market Intelligence Scraper

## Run on Your Mac in 2 Minutes

### 1. Install Dependencies
```bash
pip install httpx beautifulsoup4 lxml
```

### 2. Run the Scraper
```bash
cd rental-revenue-platform/tools

# 30A Beaches
python signal_scraper.py --market "30A Beaches" --lat 30.2833 --lng -86.0167 --radius 15

# Destin
python signal_scraper.py --market "Destin" --lat 30.3935 --lng -86.4958 --radius 10

# Gulf Shores
python signal_scraper.py --market "Gulf Shores" --lat 30.2460 --lng -87.7008 --radius 12

# Panama City Beach
python signal_scraper.py --market "PCB" --lat 30.1766 --lng -85.8055 --radius 12
```

### 3. Check Results
```bash
ls -la ./market_data/
```

Output files:
- `{market}_signals_{timestamp}.json` - Computed signals
- `{market}_listings_{timestamp}.json` - Raw listing data

---

## What It Extracts (403-Safe)

| Signal | Source | Confidence |
|--------|--------|------------|
| **Supply Density** | Listing counts | High if 100+ listings |
| **Bedroom Distribution** | Listing metadata | High |
| **Calendar Compression** | Public availability | High if 70%+ coverage |
| **Platform Share** | Airbnb vs VRBO counts | High if ratio >3:1 |
| **Amenity Prevalence** | Listing amenities | High if 50+ listings |
| **Rate Position** | Displayed prices | High if 50+ prices |

---

## Sample Output

```
📊 SIGNAL REPORT: 30A Beaches
============================================================

1️⃣  SUPPLY SIGNALS
    Total Listings: 847
    By Platform: {'airbnb': 523, 'vrbo': 324}
    By Bedrooms: {1: 45, 2: 156, 3: 234, 4: 198, 5: 145, 6: 69}
    Confidence: HIGH

2️⃣  DEMAND SIGNALS (Calendar Compression)
    Next 7 days:  67.3% unavailable
    Next 14 days: 58.2% unavailable
    Next 30 days: 45.1% unavailable
    Confidence: HIGH

3️⃣  PLATFORM DOMINANCE
    Airbnb: 61.7%
    VRBO: 38.3%
    Status: leaning_airbnb
    Confidence: MEDIUM

4️⃣  AMENITY PREVALENCE
    pool: 58.2%
    hot_tub: 12.4%
    waterfront: 8.7%
    beach_access: 45.3%
    pet_friendly: 34.1%
    Confidence: HIGH

5️⃣  RATE SIGNALS
    P25: $285
    P50 (Median): $425
    P75: $695
    By Bedrooms: {2: 245, 3: 385, 4: 525, 5: 750, 6: 1100}
    Confidence: HIGH
```

---

## If You Get 403 Errors

The scraper is designed to be respectful, but some sites may still block. Options:

### Option A: Add Delays
Edit `signal_scraper.py`:
```python
min_delay_seconds: float = 5.0  # Increase from 2
max_delay_seconds: float = 10.0  # Increase from 5
```

### Option B: Use ScraperAPI ($49/mo for 100K requests)
```bash
export SCRAPER_API_KEY="your_key"
```
Then modify the `fetch()` method to route through their proxy.

### Option C: Use Residential Proxy
Services like BrightData provide residential IPs that are harder to block.

---

## Automate with Cron

Run nightly scrapes:
```bash
# Edit crontab
crontab -e

# Add (runs at 2am daily):
0 2 * * * cd /path/to/rental-revenue-platform/tools && python signal_scraper.py --market "30A Beaches" --lat 30.2833 --lng -86.0167 --radius 15 >> /var/log/scraper.log 2>&1
```

---

## Feed Into Platform

```python
import json
from pathlib import Path

# Load scraped signals
signals_file = Path("./market_data/30a_beaches_signals_20260126.json")
with open(signals_file) as f:
    signals = json.load(f)

# Use in your platform
print(f"Market: {signals['market_name']}")
print(f"Listings: {signals['total_listings']}")
print(f"Median Rate: ${signals['rate_p50']}")
print(f"Pool Prevalence: {signals['amenity_prevalence']['pool']:.1%}")
```
