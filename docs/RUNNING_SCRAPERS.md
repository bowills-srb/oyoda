# 🚀 Running the Market Intelligence Scrapers

## Quick Start (5 Minutes)

### Step 1: Install Dependencies

```bash
# On your Mac
pip install httpx beautifulsoup4 lxml

# Optional: For JavaScript-rendered pages (more reliable but slower)
pip install playwright
playwright install chromium
```

### Step 2: Navigate to Tools Directory

```bash
cd rental-revenue-platform/tools
```

### Step 3: Run Your First Scrape

```bash
# 30A Beaches market
python signal_scraper.py \
  --market "30A Beaches" \
  --lat 30.2833 \
  --lng -86.0167 \
  --radius 15

# You should see output like:
# 🔍 Starting scrape for 30A Beaches...
# 📊 Found 847 listings
# ✅ Signals saved to ./market_data/30a_beaches_signals_20260127.json
```

### Step 4: Check Your Results

```bash
# List generated files
ls -la ./market_data/

# View the signals
cat ./market_data/30a_beaches_signals_*.json | python -m json.tool
```

---

## What Each Scraper Does

### 1. `signal_scraper.py` - Platform Listings (Airbnb/VRBO)

**What it extracts:**
| Signal | Description | Confidence |
|--------|-------------|------------|
| Supply Density | Total listings in market | HIGH (if 100+) |
| Bedroom Distribution | 1BR, 2BR, 3BR, etc. breakdown | HIGH |
| Calendar Compression | % booked next 7/14/30 days | HIGH (if 70%+ coverage) |
| Platform Share | Airbnb vs VRBO ratio | HIGH |
| Amenity Prevalence | % with pool, hot tub, etc. | HIGH (if 50+ listings) |
| Rate Position | P25/P50/P75 nightly rates | HIGH (if 50+ prices) |

**Usage:**
```bash
python signal_scraper.py \
  --market "MARKET_NAME" \
  --lat LATITUDE \
  --lng LONGITUDE \
  --radius MILES
```

**Common Markets:**
```bash
# Florida Gulf Coast
python signal_scraper.py --market "30A Beaches" --lat 30.2833 --lng -86.0167 --radius 15
python signal_scraper.py --market "Destin" --lat 30.3935 --lng -86.4958 --radius 10
python signal_scraper.py --market "Panama City Beach" --lat 30.1766 --lng -85.8055 --radius 12

# Alabama Coast
python signal_scraper.py --market "Gulf Shores" --lat 30.2460 --lng -87.7008 --radius 12
python signal_scraper.py --market "Orange Beach" --lat 30.2941 --lng -87.5731 --radius 8

# Other Popular Markets
python signal_scraper.py --market "Gatlinburg" --lat 35.7143 --lng -83.5102 --radius 10
python signal_scraper.py --market "Myrtle Beach" --lat 33.6891 --lng -78.8867 --radius 15
python signal_scraper.py --market "Lake Tahoe" --lat 39.0968 --lng -120.0324 --radius 20
```

---

### 2. `federal_data_scraper.py` - Economic/Macro Signals

**What it extracts:**
| Signal | Source | Update Frequency |
|--------|--------|------------------|
| Tourism Spending | BEA | Quarterly |
| Employment (Leisure) | BLS | Monthly |
| Airport Passengers | FAA | Monthly |
| Population Growth | Census | Annual |
| Median Income | Census ACS | Annual |

**Usage:**
```bash
python federal_data_scraper.py \
  --market "30A Beaches" \
  --state FL \
  --county "Walton"
```

**Note:** Federal data requires free API keys:
- BLS: https://www.bls.gov/developers/
- Census: https://api.census.gov/data/key_signup.html

```bash
# Set environment variables
export BLS_API_KEY="your_key_here"
export CENSUS_API_KEY="your_key_here"

# Then run
python federal_data_scraper.py --market "30A Beaches" --state FL --county "Walton"
```

---

## Output File Structure

After running the scrapers, you'll have:

```
./market_data/
├── 30a_beaches_signals_20260127_143022.json    # Computed signals
├── 30a_beaches_listings_20260127_143022.json   # Raw listing data
├── 30a_beaches_federal_20260127.json           # Federal/macro data
└── cache/
    └── ... (cached responses to avoid re-fetching)
```

### Signal File Structure

```json
{
  "market_id": "30a_beaches",
  "market_name": "30A Beaches",
  "scraped_at": "2026-01-27T14:30:22Z",
  "center_lat": 30.2833,
  "center_lng": -86.0167,
  "radius_miles": 15,
  
  "supply": {
    "total_listings": 847,
    "by_platform": {"airbnb": 523, "vrbo": 324},
    "by_bedrooms": {"1": 45, "2": 156, "3": 234, "4": 198, "5": 145, "6": 69},
    "confidence": 0.92
  },
  
  "demand": {
    "calendar_compression_7d": 0.673,
    "calendar_compression_14d": 0.582,
    "calendar_compression_30d": 0.451,
    "sample_size": 523,
    "confidence": 0.88
  },
  
  "platform": {
    "airbnb_share": 0.617,
    "vrbo_share": 0.383,
    "dominance": "leaning_airbnb",
    "confidence": 0.95
  },
  
  "amenities": {
    "pool": 0.582,
    "hot_tub": 0.124,
    "waterfront": 0.087,
    "beach_access": 0.453,
    "pet_friendly": 0.341,
    "gulf_view": 0.312,
    "confidence": 0.85
  },
  
  "rates": {
    "p25": 285,
    "p50": 425,
    "p75": 695,
    "by_bedrooms": {
      "2": {"p25": 185, "p50": 245, "p75": 320},
      "3": {"p25": 285, "p50": 385, "p75": 495},
      "4": {"p25": 395, "p50": 525, "p75": 695},
      "5": {"p25": 550, "p50": 750, "p75": 950}
    },
    "sample_size": 412,
    "confidence": 0.87
  }
}
```

---

## Feeding Signals Into the Platform

### Option A: Manual Import (Development)

```python
import json
from pathlib import Path

# Load scraped signals
signals_file = Path("./market_data/30a_beaches_signals_20260127.json")
with open(signals_file) as f:
    raw_signals = json.load(f)

# Convert to canonical format
from tools.signal_converter import SignalConverter

converter = SignalConverter()
canonical_signals = converter.convert(raw_signals)

# Now you have signals ready for the pipeline
print(f"Converted {len(canonical_signals)} signals")
```

### Option B: Database Storage (Production)

```python
from app.services.signals import SignalPipeline
from tools.signal_converter import SignalConverter

# Load and convert
with open("./market_data/30a_beaches_signals_20260127.json") as f:
    raw = json.load(f)

converter = SignalConverter()
signals = converter.convert(raw)

# Store via pipeline
pipeline = SignalPipeline(db_session)
for signal in signals:
    pipeline.ingest(signal)

print(f"Stored {len(signals)} signals in database")
```

### Option C: Scheduled Automation (Production)

```python
# In your scheduler (e.g., Celery beat, cron)
from app.services.signals.scheduler import SignalScheduler

scheduler = SignalScheduler()

# Register markets to scrape
scheduler.register_market("30a_beaches", lat=30.2833, lng=-86.0167, radius=15)
scheduler.register_market("destin", lat=30.3935, lng=-86.4958, radius=10)

# Run nightly
scheduler.run_all()  # Scrapes all registered markets
```

---

## Troubleshooting

### 403 Forbidden Errors

The scraper is designed to be respectful, but you may still get blocked.

**Solution 1: Increase delays**
```python
# Edit signal_scraper.py line 63-64
min_delay_seconds: float = 5.0   # Was 2.0
max_delay_seconds: float = 10.0  # Was 5.0
```

**Solution 2: Use ScraperAPI (paid)**
```bash
export SCRAPER_API_KEY="your_key"
# $49/month for 100K requests
```

**Solution 3: Use Playwright (slower but more reliable)**
```bash
pip install playwright
playwright install chromium

# The scraper will auto-detect and use Playwright for JS-rendered pages
```

### Empty Results

If you get 0 listings:
1. Check your lat/lng coordinates are correct
2. Try increasing the radius
3. Check if the platform is blocking your IP (try later)

### Rate Limit Exceeded

If you see "Too many requests":
1. Wait 10 minutes
2. Increase delays in config
3. Consider using a proxy service

---

## Automation with Cron

Run scrapers automatically every night:

```bash
# Edit crontab
crontab -e

# Add these lines (runs at 2 AM daily)
0 2 * * * cd /path/to/rental-revenue-platform/tools && python signal_scraper.py --market "30A Beaches" --lat 30.2833 --lng -86.0167 --radius 15 >> /var/log/scraper.log 2>&1
0 2 * * * cd /path/to/rental-revenue-platform/tools && python signal_scraper.py --market "Destin" --lat 30.3935 --lng -86.4958 --radius 10 >> /var/log/scraper.log 2>&1

# Federal data weekly (Sundays at 3 AM)
0 3 * * 0 cd /path/to/rental-revenue-platform/tools && python federal_data_scraper.py --market "30A Beaches" --state FL --county "Walton" >> /var/log/federal_scraper.log 2>&1
```

---

## Verification Checklist

After your first scrape, verify:

- [ ] `./market_data/` directory was created
- [ ] `*_signals_*.json` file exists and has data
- [ ] `total_listings` > 0
- [ ] `calendar_compression_7d` is between 0 and 1
- [ ] `rates.p50` looks reasonable for the market

---

## Next Steps After Scraping

1. **Run for your target markets** (2-3 markets to start)
2. **Review the data quality** - does it look reasonable?
3. **Set up the database** - store signals for historical tracking
4. **Wire to dashboard** - see live data in the UI
5. **Automate** - cron jobs for nightly updates

---

## Questions?

The scrapers are designed to be self-contained and runnable on your Mac. They don't require the full platform to be running - they just output JSON files that can be imported later.

Start simple: run one market, check the output, then expand.
