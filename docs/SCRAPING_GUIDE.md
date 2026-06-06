# Public Data Scraping System

## What's Built

### Scraper Classes

| Scraper | File | Status |
|---------|------|--------|
| `AirbnbScraper` | `public_data_scraper.py` | ✅ Built, needs proxy |
| `VRBOScraper` | `public_data_scraper.py` | ✅ Built, needs proxy |
| `ZillowScraper` | `public_data_scraper.py` | ✅ Built, needs proxy |
| `MarketDataAggregator` | `public_data_scraper.py` | ✅ Built |
| `SignalConverter` | `public_data_scraper.py` | ✅ Built |

### Data Models

```python
ScrapedListing      # Vacation rental listing (Airbnb/VRBO)
ScrapedProperty     # Real estate property (Zillow)
MarketSnapshot      # Aggregated market data
```

### Signal Mapping

| Scraped Data | → Signal Type |
|--------------|---------------|
| Listing counts by platform | `PLATFORM_DOMINANCE` |
| New listings over time | `SUPPLY_VELOCITY` |
| Calendar availability | `DEMAND_PRESSURE` |
| Amenity prevalence | `AMENITY_LIFT` |
| Rate distribution | `RATE_POSITION` |
| Availability by month | `SEASONALITY_CURVE` |

---

## What You Need for Production

### 1. Proxy Service (Required)

Airbnb, VRBO, and Zillow all block direct scraping. You need:

**Option A: Managed Proxy API**
- [ScraperAPI](https://www.scraperapi.com/) - $49/mo for 100K requests
- [BrightData](https://brightdata.com/) - Pay per GB
- [Oxylabs](https://oxylabs.io/) - Residential proxies

**Option B: Self-Hosted Proxies**
- Rotating residential proxy pool
- More work but lower cost at scale

### 2. JavaScript Rendering

Airbnb and Zillow render content via JavaScript. Options:

**Option A: Playwright/Puppeteer**
```python
# Already supported in the architecture
pip install playwright
playwright install chromium
```

**Option B: ScraperAPI with JS rendering**
```
?render=true parameter
```

### 3. Anti-Bot Bypasses

| Site | Protection | Solution |
|------|------------|----------|
| Airbnb | Cloudflare | Residential proxies + browser fingerprinting |
| VRBO | DataDome | Similar to Airbnb |
| Zillow | Incapsula | Slower request rate + headers |

### 4. Rate Limiting

Built into the scraper:
- Airbnb: 1 req/2 seconds
- VRBO: 1 req/2 seconds  
- Zillow: 1 req/3 seconds

For production, reduce further or use multiple proxies.

---

## Quick Start (with ScraperAPI)

```python
import os
os.environ['SCRAPER_API_KEY'] = 'your_key_here'

# Modify the _fetch method to use ScraperAPI
async def _fetch(self, url: str) -> Optional[str]:
    api_key = os.environ.get('SCRAPER_API_KEY')
    proxy_url = f"http://api.scraperapi.com?api_key={api_key}&url={url}"
    
    response = await self._client.get(proxy_url)
    return response.text
```

---

## Alternative: Official APIs

Some data is available through official (paid) APIs:

| Provider | Data Available | Cost |
|----------|----------------|------|
| [AirDNA](https://www.airdna.co/) | Rental analytics, comps | $19-299/mo |
| [Mashvisor](https://www.mashvisor.com/) | Rental estimates | $49-299/mo |
| [Zillow API](https://www.zillow.com/howto/api/APIOverview.htm) | Zestimates (deprecated, limited) | Free but restricted |
| [Realtor.com API](https://www.realtor.com/api) | Property data | Contact for pricing |

---

## Recommended Approach

### Phase 1: Manual Data Upload (Now)
- Build CSV upload endpoint for market data
- Manually collect initial data for target markets
- Get the signal engine working end-to-end

### Phase 2: Scraping Infrastructure (2-4 weeks)
- Set up ScraperAPI or proxy service
- Deploy scrapers on a server (not sandbox)
- Run nightly scrapes for registered markets

### Phase 3: Scale (Ongoing)
- Add more markets
- Optimize scrape frequency based on data freshness needs
- Consider AirDNA API for historical data

---

## Files Created

```
app/services/scrapers/
├── __init__.py
├── market_scraper.py          # Original (simulated) scraper
└── public_data_scraper.py     # NEW: Real scraper architecture
    ├── AirbnbScraper
    ├── VRBOScraper
    ├── ZillowScraper
    ├── MarketDataAggregator
    ├── SignalConverter
    └── PublicDataScrapeService
```

---

## Usage (When Proxies Configured)

```python
from app.services.scrapers.public_data_scraper import PublicDataScrapeService

async def scrape_30a_market():
    service = PublicDataScrapeService()
    
    # Scrape the market
    snapshot = await service.scrape_market(
        market_id="30a-beaches",
        market_name="30A Beaches", 
        latitude=30.2833,
        longitude=-86.0167,
        radius_miles=15,
    )
    
    print(f"Found {snapshot.total_listings} listings")
    print(f"Pool prevalence: {snapshot.pct_with_pool:.0%}")
    print(f"Median rate (3BR): ${snapshot.median_rate_by_bedrooms.get(3, 0):,.0f}")
    
    # Convert to signals for the platform
    signals = service.convert_to_signals(snapshot)
    
    for signal in signals:
        print(f"{signal['signal_type']}: {signal['value']}")
    
    await service.close()
```
