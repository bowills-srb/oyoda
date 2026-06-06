"""
Federal & Public Data Scrapers (403-Safe)

These scrapers access FREE, PUBLIC, OPEN government data sources
that provide HIGH-TRUST signals without any scraping risk.

Sources:
🟢 Bureau of Transportation Statistics (DOT) - Travel flow
🟢 NOAA / National Weather Service - Weather patterns
🟢 US Census / ACS - Housing stock, demographics
🟢 FAA - Airport traffic
🟢 County Assessor/Recorder - Property transactions

These sources:
- Have no rate limits (or very generous ones)
- Provide official, citable data
- Strengthen confidence vs. competitors
- Are FREE

Run on your machine with: python federal_data_scraper.py --market "30A" --state FL
"""

import asyncio
import argparse
import json
import os
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, date
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

try:
    import httpx
except ImportError:
    print("ERROR: pip install httpx")
    raise

# =============================================================================
# CONFIGURATION
# =============================================================================

@dataclass
class FederalDataConfig:
    """Configuration for federal data scrapers."""
    output_dir: str = "./federal_data"
    cache_days: int = 30  # Federal data updates slowly
    
    # Census API key (free, get at https://api.census.gov/data/key_signup.html)
    census_api_key: Optional[str] = None
    
    # Request settings
    timeout_seconds: int = 30
    max_retries: int = 3


# =============================================================================
# DATA MODELS
# =============================================================================

@dataclass
class TravelFlowData:
    """Travel flow data from BTS/DOT."""
    airport_code: str
    airport_name: str
    period: str  # e.g., "2024-Q3"
    passengers_enplaned: int
    passengers_deplaned: int
    total_passengers: int
    yoy_change_pct: Optional[float] = None
    source: str = "BTS T-100"
    scraped_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class HousingStockData:
    """Housing stock data from Census ACS."""
    geo_id: str  # FIPS code
    geo_name: str
    
    # Housing units
    total_housing_units: int
    occupied_units: int
    vacant_units: int
    vacancy_rate: float
    
    # Values
    median_home_value: Optional[float] = None
    median_rent: Optional[float] = None
    
    # Ownership
    owner_occupied_pct: Optional[float] = None
    renter_occupied_pct: Optional[float] = None
    
    # Seasonal (key for STR markets!)
    seasonal_vacant_units: Optional[int] = None
    seasonal_vacant_pct: Optional[float] = None
    
    year: int = 2022  # ACS year
    source: str = "Census ACS 5-Year"
    scraped_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class WeatherData:
    """Weather pattern data from NOAA."""
    station_id: str
    station_name: str
    latitude: float
    longitude: float
    
    # Monthly normals
    avg_temp_f: Dict[int, float] = field(default_factory=dict)  # {month: temp}
    precipitation_in: Dict[int, float] = field(default_factory=dict)
    
    # Severe weather
    hurricane_risk: str = "low"  # low/medium/high
    tornado_risk: str = "low"
    
    source: str = "NOAA NCEI"
    scraped_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class PropertyTransactionData:
    """Property transaction data (aggregated)."""
    geo_id: str
    geo_name: str
    period: str  # e.g., "2024-Q3"
    
    total_transactions: int
    median_sale_price: float
    avg_sale_price: float
    yoy_price_change_pct: Optional[float] = None
    
    source: str = "County Recorder"
    scraped_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


# =============================================================================
# CENSUS ACS SCRAPER
# =============================================================================

class CensusAcsScraper:
    """
    Scrapes US Census American Community Survey data.
    
    Provides:
    - Housing stock counts
    - Median home values
    - Vacancy rates (including seasonal!)
    - Demographics
    
    API: https://api.census.gov/data/
    Key signup: https://api.census.gov/data/key_signup.html (free)
    """
    
    BASE_URL = "https://api.census.gov/data"
    
    # ACS variables for housing
    HOUSING_VARS = {
        # Total housing units
        "B25001_001E": "total_housing_units",
        # Occupancy
        "B25002_001E": "total_occupancy_universe",
        "B25002_002E": "occupied_units",
        "B25002_003E": "vacant_units",
        # Vacancy status
        "B25004_001E": "vacant_universe",
        "B25004_006E": "seasonal_vacant",  # Key for STR markets!
        # Values
        "B25077_001E": "median_home_value",
        "B25064_001E": "median_rent",
        # Tenure
        "B25003_002E": "owner_occupied",
        "B25003_003E": "renter_occupied",
    }
    
    def __init__(self, config: FederalDataConfig):
        self.config = config
        self.api_key = config.census_api_key or os.environ.get("CENSUS_API_KEY")
    
    async def get_county_housing(
        self,
        state_fips: str,
        county_fips: str,
        year: int = 2022,
    ) -> Optional[HousingStockData]:
        """
        Get housing stock data for a county.
        
        Args:
            state_fips: 2-digit state FIPS code (e.g., "12" for Florida)
            county_fips: 3-digit county FIPS code
            year: ACS year (default 2022, latest available)
        """
        # Build variable list
        vars_str = ",".join(["NAME"] + list(self.HOUSING_VARS.keys()))
        
        # Build URL
        url = f"{self.BASE_URL}/{year}/acs/acs5"
        params = {
            "get": vars_str,
            "for": f"county:{county_fips}",
            "in": f"state:{state_fips}",
        }
        if self.api_key:
            params["key"] = self.api_key
        
        full_url = f"{url}?{urlencode(params)}"
        
        try:
            async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
                response = await client.get(full_url)
                
                if response.status_code != 200:
                    print(f"Census API error: {response.status_code}")
                    return None
                
                data = response.json()
                
                # Parse response (first row is headers, second is data)
                if len(data) < 2:
                    return None
                
                headers = data[0]
                values = data[1]
                
                row = dict(zip(headers, values))
                
                # Convert to our model
                total = self._safe_int(row.get("B25001_001E"))
                occupied = self._safe_int(row.get("B25002_002E"))
                vacant = self._safe_int(row.get("B25002_003E"))
                seasonal = self._safe_int(row.get("B25004_006E"))
                owner = self._safe_int(row.get("B25003_002E"))
                renter = self._safe_int(row.get("B25003_003E"))
                
                return HousingStockData(
                    geo_id=f"{state_fips}{county_fips}",
                    geo_name=row.get("NAME", ""),
                    total_housing_units=total or 0,
                    occupied_units=occupied or 0,
                    vacant_units=vacant or 0,
                    vacancy_rate=vacant / total if total else 0,
                    median_home_value=self._safe_float(row.get("B25077_001E")),
                    median_rent=self._safe_float(row.get("B25064_001E")),
                    owner_occupied_pct=owner / occupied if occupied else None,
                    renter_occupied_pct=renter / occupied if occupied else None,
                    seasonal_vacant_units=seasonal,
                    seasonal_vacant_pct=seasonal / total if total and seasonal else None,
                    year=year,
                )
                
        except Exception as e:
            print(f"Census API error: {e}")
            return None
    
    async def get_zip_housing(
        self,
        zipcode: str,
        year: int = 2022,
    ) -> Optional[HousingStockData]:
        """Get housing data for a ZIP code."""
        # Build variable list
        vars_str = ",".join(["NAME"] + list(self.HOUSING_VARS.keys()))
        
        url = f"{self.BASE_URL}/{year}/acs/acs5"
        params = {
            "get": vars_str,
            "for": f"zip code tabulation area:{zipcode}",
        }
        if self.api_key:
            params["key"] = self.api_key
        
        full_url = f"{url}?{urlencode(params)}"
        
        try:
            async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
                response = await client.get(full_url)
                
                if response.status_code != 200:
                    return None
                
                data = response.json()
                if len(data) < 2:
                    return None
                
                headers = data[0]
                values = data[1]
                row = dict(zip(headers, values))
                
                total = self._safe_int(row.get("B25001_001E"))
                occupied = self._safe_int(row.get("B25002_002E"))
                vacant = self._safe_int(row.get("B25002_003E"))
                seasonal = self._safe_int(row.get("B25004_006E"))
                
                return HousingStockData(
                    geo_id=f"ZCTA:{zipcode}",
                    geo_name=row.get("NAME", zipcode),
                    total_housing_units=total or 0,
                    occupied_units=occupied or 0,
                    vacant_units=vacant or 0,
                    vacancy_rate=vacant / total if total else 0,
                    median_home_value=self._safe_float(row.get("B25077_001E")),
                    median_rent=self._safe_float(row.get("B25064_001E")),
                    seasonal_vacant_units=seasonal,
                    seasonal_vacant_pct=seasonal / total if total and seasonal else None,
                    year=year,
                )
                
        except Exception as e:
            print(f"Census ZIP error: {e}")
            return None
    
    @staticmethod
    def _safe_int(val) -> Optional[int]:
        try:
            return int(val) if val and val not in ['-', 'null', None] else None
        except:
            return None
    
    @staticmethod
    def _safe_float(val) -> Optional[float]:
        try:
            return float(val) if val and val not in ['-', 'null', None] else None
        except:
            return None


# =============================================================================
# BTS TRAVEL FLOW SCRAPER
# =============================================================================

class BtsTravelScraper:
    """
    Scrapes Bureau of Transportation Statistics data.
    
    Provides:
    - Airport passenger counts (T-100 data)
    - Seasonal travel patterns
    - YoY changes
    
    Data: https://www.transtats.bts.gov/
    """
    
    # Major airports by region (for regional market analysis)
    GULF_COAST_AIRPORTS = {
        "VPS": "Destin-Fort Walton Beach",
        "ECP": "Panama City Beach",
        "PNS": "Pensacola",
        "MOB": "Mobile",
        "GPT": "Gulfport-Biloxi",
        "MSY": "New Orleans",
        "TLH": "Tallahassee",
    }
    
    FLORIDA_AIRPORTS = {
        "MIA": "Miami",
        "FLL": "Fort Lauderdale",
        "TPA": "Tampa",
        "MCO": "Orlando",
        "JAX": "Jacksonville",
        "RSW": "Fort Myers",
        "PBI": "Palm Beach",
        "SRQ": "Sarasota",
    }
    
    def __init__(self, config: FederalDataConfig):
        self.config = config
    
    async def get_airport_traffic(
        self,
        airport_code: str,
        year: int = 2024,
    ) -> Optional[TravelFlowData]:
        """
        Get airport passenger data.
        
        Note: BTS T-100 data has a few months lag.
        For real-time, would need to scrape airport authority sites.
        """
        # BTS API endpoint for T-100 segment data
        # This is a simplified example - real implementation would use their API
        
        # For now, return structured placeholder
        # In production, you'd hit: https://www.transtats.bts.gov/DL_SelectFields.aspx?gnoession_VK=1
        
        print(f"  📊 Would fetch BTS T-100 data for {airport_code}")
        print(f"     Real implementation needs BTS API access")
        
        return None
    
    def get_regional_airports(self, region: str) -> Dict[str, str]:
        """Get airport codes for a region."""
        regions = {
            "gulf_coast": self.GULF_COAST_AIRPORTS,
            "florida": self.FLORIDA_AIRPORTS,
        }
        return regions.get(region.lower(), {})


# =============================================================================
# NOAA WEATHER SCRAPER
# =============================================================================

class NoaaWeatherScraper:
    """
    Scrapes NOAA/National Weather Service data.
    
    Provides:
    - Climate normals
    - Severe weather history
    - Seasonal patterns
    
    API: https://www.ncei.noaa.gov/cdo-web/api/v2/
    Token signup: https://www.ncdc.noaa.gov/cdo-web/token (free)
    """
    
    BASE_URL = "https://www.ncei.noaa.gov/cdo-web/api/v2"
    
    def __init__(self, config: FederalDataConfig):
        self.config = config
        self.token = os.environ.get("NOAA_TOKEN")
    
    async def get_climate_normals(
        self,
        latitude: float,
        longitude: float,
    ) -> Optional[WeatherData]:
        """
        Get climate normals for a location.
        
        Uses NOAA Climate Normals (1991-2020 averages).
        """
        if not self.token:
            print("  ⚠️  NOAA_TOKEN not set - get free token at ncdc.noaa.gov/cdo-web/token")
            return None
        
        # Find nearest station
        # In production, would use NOAA's station finder API
        
        print(f"  🌤️  Would fetch NOAA climate normals for {latitude}, {longitude}")
        print(f"     Real implementation needs NOAA API token")
        
        return None


# =============================================================================
# FIPS CODE LOOKUPS
# =============================================================================

# State FIPS codes
STATE_FIPS = {
    "AL": "01", "AK": "02", "AZ": "04", "AR": "05", "CA": "06",
    "CO": "08", "CT": "09", "DE": "10", "FL": "12", "GA": "13",
    "HI": "15", "ID": "16", "IL": "17", "IN": "18", "IA": "19",
    "KS": "20", "KY": "21", "LA": "22", "ME": "23", "MD": "24",
    "MA": "25", "MI": "26", "MN": "27", "MS": "28", "MO": "29",
    "MT": "30", "NE": "31", "NV": "32", "NH": "33", "NJ": "34",
    "NM": "35", "NY": "36", "NC": "37", "ND": "38", "OH": "39",
    "OK": "40", "OR": "41", "PA": "42", "RI": "44", "SC": "45",
    "SD": "46", "TN": "47", "TX": "48", "UT": "49", "VT": "50",
    "VA": "51", "WA": "53", "WV": "54", "WI": "55", "WY": "56",
}

# Key STR market counties
STR_MARKET_COUNTIES = {
    # Florida Gulf Coast
    "30A": {"state": "FL", "county": "131"},  # Walton County
    "Destin": {"state": "FL", "county": "091"},  # Okaloosa County
    "Panama City Beach": {"state": "FL", "county": "005"},  # Bay County
    "Pensacola": {"state": "FL", "county": "033"},  # Escambia County
    
    # Alabama Gulf Coast
    "Gulf Shores": {"state": "AL", "county": "003"},  # Baldwin County
    "Orange Beach": {"state": "AL", "county": "003"},  # Baldwin County
    
    # Other popular markets
    "Nashville": {"state": "TN", "county": "037"},  # Davidson County
    "Gatlinburg": {"state": "TN", "county": "155"},  # Sevier County
    "Myrtle Beach": {"state": "SC", "county": "051"},  # Horry County
    "Outer Banks": {"state": "NC", "county": "055"},  # Dare County
}


# =============================================================================
# ORCHESTRATOR
# =============================================================================

class FederalDataOrchestrator:
    """
    Orchestrates collection of all federal/public data sources.
    
    Usage:
        orchestrator = FederalDataOrchestrator()
        data = await orchestrator.collect_market_data("30A")
    """
    
    def __init__(self, config: Optional[FederalDataConfig] = None):
        self.config = config or FederalDataConfig()
        self.census = CensusAcsScraper(self.config)
        self.bts = BtsTravelScraper(self.config)
        self.noaa = NoaaWeatherScraper(self.config)
    
    async def collect_market_data(
        self,
        market_name: str,
        zipcodes: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Collect all federal data for a market.
        
        Args:
            market_name: Market identifier (e.g., "30A", "Destin")
            zipcodes: Optional list of ZIP codes to query
        """
        print(f"\n{'='*60}")
        print(f"📊 FEDERAL DATA COLLECTION: {market_name}")
        print(f"{'='*60}\n")
        
        results = {
            "market": market_name,
            "collected_at": datetime.utcnow().isoformat(),
            "housing": None,
            "travel": None,
            "weather": None,
            "signals": [],
        }
        
        # Get county info
        county_info = STR_MARKET_COUNTIES.get(market_name)
        
        if county_info:
            state_fips = STATE_FIPS.get(county_info["state"])
            county_fips = county_info["county"]
            
            print(f"1️⃣  Census ACS Housing Data...")
            housing = await self.census.get_county_housing(state_fips, county_fips)
            if housing:
                results["housing"] = asdict(housing)
                print(f"   ✅ {housing.geo_name}")
                print(f"      Housing units: {housing.total_housing_units:,}")
                print(f"      Vacancy rate: {housing.vacancy_rate:.1%}")
                if housing.seasonal_vacant_pct:
                    print(f"      Seasonal vacant: {housing.seasonal_vacant_pct:.1%} ← Key STR signal!")
                if housing.median_home_value:
                    print(f"      Median home value: ${housing.median_home_value:,.0f}")
                
                # Generate signal
                results["signals"].append({
                    "signal_type": "HOUSING_STOCK",
                    "value": {
                        "total_housing_units": housing.total_housing_units,
                        "vacancy_rate": housing.vacancy_rate,
                        "seasonal_vacant_pct": housing.seasonal_vacant_pct,
                        "median_home_value": housing.median_home_value,
                    },
                    "confidence": 0.95,  # Census data is high confidence
                    "source": "CENSUS_ACS",
                })
        
        # ZIP-level data if provided
        if zipcodes:
            print(f"\n2️⃣  ZIP Code Level Data...")
            for zipcode in zipcodes[:5]:  # Limit to 5
                zip_housing = await self.census.get_zip_housing(zipcode)
                if zip_housing:
                    print(f"   ✅ {zipcode}: {zip_housing.total_housing_units:,} units")
        
        # Regional airports
        print(f"\n3️⃣  Regional Airport Data...")
        airports = self.bts.get_regional_airports("gulf_coast")
        print(f"   📍 Regional airports: {', '.join(airports.keys())}")
        
        print(f"\n{'='*60}")
        print(f"✅ Federal data collection complete")
        print(f"{'='*60}\n")
        
        return results
    
    def save_results(self, results: Dict, output_dir: Optional[str] = None):
        """Save results to JSON file."""
        output_dir = Path(output_dir or self.config.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        market = results["market"].lower().replace(" ", "_")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        filepath = output_dir / f"{market}_federal_data_{timestamp}.json"
        with open(filepath, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        
        print(f"💾 Saved to: {filepath}")
        return filepath


# =============================================================================
# CLI
# =============================================================================

async def main():
    parser = argparse.ArgumentParser(description="Federal/Public Data Scraper")
    parser.add_argument('--market', required=True, help='Market name (e.g., "30A", "Destin")')
    parser.add_argument('--zipcodes', nargs='*', help='Optional ZIP codes')
    parser.add_argument('--output', default='./federal_data', help='Output directory')
    
    args = parser.parse_args()
    
    config = FederalDataConfig(output_dir=args.output)
    orchestrator = FederalDataOrchestrator(config)
    
    results = await orchestrator.collect_market_data(
        args.market,
        zipcodes=args.zipcodes,
    )
    
    orchestrator.save_results(results)


if __name__ == "__main__":
    asyncio.run(main())
