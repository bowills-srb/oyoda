"""
Market Data Ingestion System.

Allows manual upload of market data via CSV/Excel while 
automated scraping infrastructure is being set up.

Supports:
- Listing data (from manual Airbnb/VRBO exports)
- Property data (from Zillow exports)
- Historical booking data (from PMS exports)
- Seasonality curves (from historical analysis)
"""

import csv
from dataclasses import dataclass, field
from datetime import datetime, date
from enum import Enum
from io import StringIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from uuid import uuid4

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False


class DataSourceType(str, Enum):
    LISTINGS = "listings"
    PROPERTIES = "properties"
    BOOKINGS = "bookings"
    SEASONALITY = "seasonality"


@dataclass
class IngestionResult:
    success: bool
    source_type: DataSourceType
    records_processed: int
    records_valid: int
    records_invalid: int
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    data: List[Dict] = field(default_factory=list)


# Column mappings
LISTING_COLUMNS = {
    'listing_id': ['listing_id', 'id', 'property_id', 'airbnb_id', 'vrbo_id'],
    'platform': ['platform', 'source', 'channel'],
    'title': ['title', 'name', 'listing_name', 'headline'],
    'latitude': ['latitude', 'lat'],
    'longitude': ['longitude', 'lng', 'lon'],
    'city': ['city', 'market', 'location'],
    'state': ['state', 'region'],
    'bedrooms': ['bedrooms', 'beds', 'br'],
    'bathrooms': ['bathrooms', 'baths', 'ba'],
    'sleeps': ['sleeps', 'guests', 'max_guests'],
    'property_type': ['property_type', 'type', 'home_type'],
    'has_pool': ['has_pool', 'pool', 'private_pool'],
    'has_hot_tub': ['has_hot_tub', 'hot_tub', 'jacuzzi'],
    'has_waterfront': ['has_waterfront', 'waterfront', 'beachfront'],
    'has_pet_friendly': ['has_pet_friendly', 'pet_friendly', 'pets_allowed'],
    'nightly_rate': ['nightly_rate', 'rate', 'price', 'adr'],
    'review_count': ['review_count', 'reviews'],
    'rating': ['rating', 'avg_rating'],
    'is_superhost': ['is_superhost', 'superhost'],
    'url': ['url', 'listing_url', 'link'],
}

SEASONALITY_COLUMNS = {
    'market_id': ['market_id', 'market', 'location'],
    'month': ['month', 'month_num'],
    'month_name': ['month_name', 'month_label'],
    'occupancy': ['occupancy', 'occ', 'occupancy_rate'],
    'adr': ['adr', 'avg_rate', 'average_daily_rate'],
    'revpar': ['revpar'],
    'demand_index': ['demand_index', 'demand'],
}


class DataParser:
    @staticmethod
    def find_column(df_columns: List[str], canonical: str, aliases: List[str]) -> Optional[str]:
        if canonical in df_columns:
            return canonical
        for alias in aliases:
            if alias in df_columns:
                return alias
            for col in df_columns:
                if col.lower() == alias.lower():
                    return col
        return None
    
    @staticmethod
    def parse_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            return value.lower() in ('true', 'yes', '1', 'y', 't')
        return False
    
    @staticmethod
    def parse_float(value: Any) -> Optional[float]:
        if value is None:
            return None
        if HAS_PANDAS and pd.isna(value):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            cleaned = value.replace('$', '').replace(',', '').strip()
            try:
                return float(cleaned)
            except:
                return None
        return None
    
    @staticmethod
    def parse_int(value: Any) -> Optional[int]:
        f = DataParser.parse_float(value)
        return int(f) if f is not None else None


class MarketDataIngestor:
    def __init__(self):
        self.parser = DataParser()
    
    def ingest_listings(self, filepath: Union[str, Path]) -> IngestionResult:
        filepath = Path(filepath)
        if not filepath.exists():
            return IngestionResult(False, DataSourceType.LISTINGS, 0, 0, 0, [f"File not found: {filepath}"])
        
        if HAS_PANDAS:
            df = pd.read_excel(filepath) if filepath.suffix in ['.xlsx', '.xls'] else pd.read_csv(filepath)
            return self._process_listings(df.to_dict('records'), list(df.columns))
        else:
            with open(filepath, 'r') as f:
                reader = csv.DictReader(f)
                return self._process_listings(list(reader), reader.fieldnames or [])
    
    def _process_listings(self, records: List[Dict], columns: List[str]) -> IngestionResult:
        result = IngestionResult(True, DataSourceType.LISTINGS, len(records), 0, 0)
        
        col_map = {}
        for canonical, aliases in LISTING_COLUMNS.items():
            found = self.parser.find_column(columns, canonical, aliases)
            if found:
                col_map[canonical] = found
        
        for i, record in enumerate(records):
            try:
                listing = self._parse_listing(record, col_map)
                if listing:
                    result.data.append(listing)
                    result.records_valid += 1
                else:
                    result.records_invalid += 1
            except Exception as e:
                result.records_invalid += 1
                result.errors.append(f"Row {i+2}: {str(e)}")
        
        return result
    
    def _parse_listing(self, record: Dict, col_map: Dict) -> Optional[Dict]:
        def get(key):
            col = col_map.get(key)
            return record.get(col) if col else None
        
        listing_id = get('listing_id')
        if not listing_id:
            return None
        
        return {
            'listing_id': str(listing_id),
            'platform': get('platform') or 'unknown',
            'title': get('title'),
            'latitude': self.parser.parse_float(get('latitude')),
            'longitude': self.parser.parse_float(get('longitude')),
            'city': get('city'),
            'state': get('state'),
            'bedrooms': self.parser.parse_int(get('bedrooms')),
            'bathrooms': self.parser.parse_float(get('bathrooms')),
            'sleeps': self.parser.parse_int(get('sleeps')),
            'property_type': get('property_type'),
            'has_pool': self.parser.parse_bool(get('has_pool')),
            'has_hot_tub': self.parser.parse_bool(get('has_hot_tub')),
            'has_waterfront': self.parser.parse_bool(get('has_waterfront')),
            'has_pet_friendly': self.parser.parse_bool(get('has_pet_friendly')),
            'nightly_rate': self.parser.parse_float(get('nightly_rate')),
            'review_count': self.parser.parse_int(get('review_count')),
            'rating': self.parser.parse_float(get('rating')),
            'is_superhost': self.parser.parse_bool(get('is_superhost')),
            'url': get('url'),
            'ingested_at': datetime.utcnow().isoformat(),
        }
    
    def ingest_seasonality(self, filepath: Union[str, Path]) -> IngestionResult:
        filepath = Path(filepath)
        if not filepath.exists():
            return IngestionResult(False, DataSourceType.SEASONALITY, 0, 0, 0, [f"File not found: {filepath}"])
        
        if HAS_PANDAS:
            df = pd.read_excel(filepath) if filepath.suffix in ['.xlsx', '.xls'] else pd.read_csv(filepath)
            return self._process_seasonality(df.to_dict('records'), list(df.columns))
        else:
            with open(filepath, 'r') as f:
                reader = csv.DictReader(f)
                return self._process_seasonality(list(reader), reader.fieldnames or [])
    
    def _process_seasonality(self, records: List[Dict], columns: List[str]) -> IngestionResult:
        result = IngestionResult(True, DataSourceType.SEASONALITY, len(records), 0, 0)
        
        col_map = {}
        for canonical, aliases in SEASONALITY_COLUMNS.items():
            found = self.parser.find_column(columns, canonical, aliases)
            if found:
                col_map[canonical] = found
        
        for i, record in enumerate(records):
            try:
                season = self._parse_seasonality(record, col_map)
                if season:
                    result.data.append(season)
                    result.records_valid += 1
                else:
                    result.records_invalid += 1
            except Exception as e:
                result.records_invalid += 1
                result.errors.append(f"Row {i+2}: {str(e)}")
        
        return result
    
    def _parse_seasonality(self, record: Dict, col_map: Dict) -> Optional[Dict]:
        def get(key):
            col = col_map.get(key)
            return record.get(col) if col else None
        
        market_id = get('market_id')
        month = self.parser.parse_int(get('month'))
        if not market_id or not month:
            return None
        
        month_names = ['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
        
        return {
            'market_id': str(market_id),
            'month': month,
            'month_name': get('month_name') or month_names[month] if 1 <= month <= 12 else '',
            'occupancy': self.parser.parse_float(get('occupancy')),
            'adr': self.parser.parse_float(get('adr')),
            'revpar': self.parser.parse_float(get('revpar')),
            'demand_index': self.parser.parse_float(get('demand_index')),
            'ingested_at': datetime.utcnow().isoformat(),
        }


class IngestedDataSignalGenerator:
    """Generate signals from ingested data."""
    
    def generate_signals_from_listings(self, listings: List[Dict], market_id: str) -> List[Dict]:
        if not listings:
            return []
        
        signals = []
        now = datetime.utcnow()
        total = len(listings)
        
        # Platform dominance
        platform_counts = {}
        for l in listings:
            p = l.get('platform', 'unknown')
            platform_counts[p] = platform_counts.get(p, 0) + 1
        
        airbnb_share = platform_counts.get('airbnb', 0) / total if total else 0
        signals.append({
            'signal_type': 'platform_dominance',
            'market_id': market_id,
            'value': airbnb_share,
            'confidence': min(total / 50, 0.95),
            'detected_at': now.isoformat(),
            'metadata': {'platform_counts': platform_counts, 'total': total},
        })
        
        # Supply
        signals.append({
            'signal_type': 'supply_velocity',
            'market_id': market_id,
            'value': total,
            'confidence': 0.9,
            'detected_at': now.isoformat(),
            'metadata': {'total_listings': total},
        })
        
        # Amenity prevalence
        pool_count = sum(1 for l in listings if l.get('has_pool'))
        waterfront_count = sum(1 for l in listings if l.get('has_waterfront'))
        
        for amenity, count in [('pool', pool_count), ('waterfront', waterfront_count)]:
            prevalence = count / total if total else 0
            signals.append({
                'signal_type': 'amenity_lift',
                'market_id': market_id,
                'value': 1 - prevalence,
                'confidence': 0.7,
                'detected_at': now.isoformat(),
                'metadata': {'amenity': amenity, 'prevalence': prevalence},
            })
        
        # Rate position
        rates = [l.get('nightly_rate') for l in listings if l.get('nightly_rate')]
        if rates:
            rates.sort()
            n = len(rates)
            signals.append({
                'signal_type': 'rate_position',
                'market_id': market_id,
                'value': rates[n // 2],
                'confidence': 0.8,
                'detected_at': now.isoformat(),
                'metadata': {
                    'p25': rates[int(n * 0.25)],
                    'p50': rates[n // 2],
                    'p75': rates[int(n * 0.75)],
                },
            })
        
        return signals
    
    def generate_signals_from_seasonality(self, data: List[Dict], market_id: str) -> List[Dict]:
        if not data:
            return []
        
        now = datetime.utcnow()
        occupancy_curve = {}
        adr_curve = {}
        
        for record in data:
            if record.get('market_id') == market_id:
                month_name = record.get('month_name', '')
                if record.get('occupancy'):
                    occupancy_curve[month_name] = record['occupancy']
                if record.get('adr'):
                    adr_curve[month_name] = record['adr']
        
        if not occupancy_curve:
            return []
        
        return [{
            'signal_type': 'seasonality_curve',
            'market_id': market_id,
            'value': max(occupancy_curve.values()) - min(occupancy_curve.values()),
            'confidence': 0.85,
            'detected_at': now.isoformat(),
            'metadata': {
                'occupancy_by_month': occupancy_curve,
                'adr_by_month': adr_curve,
                'peak_month': max(occupancy_curve, key=occupancy_curve.get),
                'low_month': min(occupancy_curve, key=occupancy_curve.get),
            },
        }]
