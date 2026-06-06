# Booking & Availability Scraper Architecture

## Overview

This document describes the booking/availability data pipeline for Beach Habitats and the scalable architecture for onboarding additional property management companies.

## Data Sources

### 1. Website Calendar Widgets (JavaScript-rendered)
Most vacation rental websites use JavaScript calendar widgets that:
- Render availability visually (green=available, red=booked)
- Make AJAX calls to backend APIs for data
- May expose pricing per night

**Approach**: Use Playwright (headless browser) to:
1. Load property pages
2. Intercept network requests to discover API endpoints
3. Parse calendar HTML for availability data

### 2. iCal Feeds
Industry standard for availability sync. Most PMS systems expose iCal URLs that contain:
- Blocked/booked date ranges
- Booking source (Airbnb, VRBO, direct, owner block)
- Sometimes guest names or booking references

**Format**: `.ics` files with VEVENT entries for each booking

**Approach**: 
1. Discover iCal URLs from website or API
2. Parse with `icalendar` Python library
3. Extract booking records

### 3. Property Management System APIs
Different PMS platforms have different APIs:

| PMS | Common Endpoints | Auth |
|-----|-----------------|------|
| Escapia | `/api/v1/units/{id}/availability` | API Key |
| Streamline | `/api/calendar/{id}` | OAuth |
| TRACK | `/api/availability/{id}` | API Key |
| Guesty | `/api/v2/listings/{id}/calendar` | Bearer Token |
| Lodgify | `/ical/{id}.ics` | Public |
| Hostaway | `/api/v1/listings/{id}/calendar` | API Key |

## Database Schema

### property_availability
Stores daily availability and pricing:
```sql
CREATE TABLE property_availability (
    id SERIAL PRIMARY KEY,
    property_code VARCHAR(20) NOT NULL,
    date DATE NOT NULL,
    available BOOLEAN DEFAULT TRUE,
    price DECIMAL(10, 2),
    min_stay INTEGER,
    check_in_allowed BOOLEAN DEFAULT TRUE,
    check_out_allowed BOOLEAN DEFAULT TRUE,
    booking_id VARCHAR(50),
    source VARCHAR(50) DEFAULT 'website',
    scraped_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(property_code, date)
);
```

### property_bookings
Stores confirmed bookings:
```sql
CREATE TABLE property_bookings (
    id SERIAL PRIMARY KEY,
    booking_id VARCHAR(100) NOT NULL,
    property_code VARCHAR(20) NOT NULL,
    check_in DATE NOT NULL,
    check_out DATE NOT NULL,
    nights INTEGER,
    total_price DECIMAL(10, 2),
    nightly_rate DECIMAL(10, 2),
    guest_name VARCHAR(255),
    source VARCHAR(50),  -- airbnb, vrbo, direct, owner_block
    scraped_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(property_code, booking_id)
);
```

## Use Cases

### Guest Concierge
- Know when guests arrive/depart
- Calculate length of stay
- Personalize welcome messages based on booking source
- Plan housekeeping schedules

### Business Analytics
- **Occupancy Rate**: `booked_days / total_days`
- **ADR (Average Daily Rate)**: `total_revenue / booked_nights`
- **RevPAR**: `ADR × occupancy_rate`
- **Booking Lead Time**: `booking_date - check_in_date`
- **Channel Mix**: % from Airbnb vs VRBO vs direct
- **Seasonal Trends**: Pricing and occupancy by month

### Pricing Intelligence
- Compare rates to competitors
- Track rate changes over time
- Identify pricing opportunities (gaps in calendar)

## Scaling to Additional Companies

### Onboarding Process

1. **Discovery Phase**
   - Identify property management company website
   - Run `booking_scraper.py --discover` to find API endpoints
   - Document PMS platform and authentication method

2. **Scraper Development**
   - Create company-specific scraper class extending `BookingScraper`
   - Implement `scrape_property()` method
   - Add to property URL map

3. **Data Mapping**
   - Map company's property IDs to our `property_code` system
   - Normalize field names (beds/bedrooms, baths/bathrooms, etc.)

4. **Scheduling**
   - Set up cron job or Airflow DAG
   - Recommended frequency: daily for availability, hourly for active bookings

### Example: Adding a New Company

```python
class NewCompanyScraper(BookingScraper):
    """Scraper for newcompany.com"""
    
    def __init__(self, property_map: Dict[str, str]):
        super().__init__(use_playwright=True)
        self.property_map = property_map
        self.base_url = "https://www.newcompany.com"
    
    def scrape_property(self, slug: str, code: str) -> PropertyCalendar:
        # Company-specific scraping logic
        ...
```

## Current Status

### Beach Habitats (beachhabitats30a.com)
- **Properties**: 47 on website, 43 in database
- **PMS**: Unknown (need to discover)
- **Scraper**: `booking_scraper.py` (requires Playwright)
- **Status**: Framework built, needs testing on live site

### Next Steps
1. Run `--discover` mode to find API endpoints
2. Test iCal parsing if URLs found
3. Set up daily scraping schedule
4. Build analytics dashboard

## Dependencies

```bash
pip install httpx beautifulsoup4 lxml psycopg2-binary icalendar playwright
playwright install chromium
```

## Running the Scraper

```bash
# Discover API endpoints
python tools/booking_scraper.py --discover

# Scrape all properties (dry run)
python tools/booking_scraper.py --dry-run

# Scrape specific property
python tools/booking_scraper.py --property 134MC

# Full scrape with database update
python tools/booking_scraper.py
```
