"""
Signal Converter - Transforms Raw Scraped Data to Canonical Signals

This module converts the output of signal_scraper.py and federal_data_scraper.py
into the canonical Signal schemas defined in schemas/canonical_signals.py.

Every signal produced by this converter:
1. Conforms to the canonical schema
2. Has proper confidence bands (not just point estimates)
3. Includes attribution metadata
4. Has explicit decay semantics
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

# Import canonical schemas (when running in platform)
# from schemas.canonical_signals import *

# For standalone use, define minimal versions
from dataclasses import dataclass, field, asdict
from enum import Enum


class SignalType(str, Enum):
    SUPPLY_DENSITY = "supply_density"
    BEDROOM_DISTRIBUTION = "bedroom_distribution"
    CALENDAR_COMPRESSION = "calendar_compression"
    PLATFORM_DOMINANCE = "platform_dominance"
    AMENITY_PREVALENCE = "amenity_prevalence"
    AMENITY_LIFT = "amenity_lift"
    RATE_POSITION = "rate_position"
    RATE_BY_BEDROOM = "rate_by_bedroom"
    HOUSING_STOCK = "housing_stock"
    SEASONALITY_CURVE = "seasonality_curve"


class SignalSource(str, Enum):
    AIRBNB_PUBLIC = "airbnb_public"
    VRBO_PUBLIC = "vrbo_public"
    CENSUS_ACS = "census_acs"
    DERIVED = "derived"


@dataclass
class CanonicalSignal:
    """Canonical signal format."""
    signal_id: str
    signal_type: str
    geo_id: str
    property_id: Optional[str]
    source: str
    value: Dict[str, Any]
    unit: str
    confidence: float
    confidence_band: tuple
    confidence_level: str
    decay_half_life_days: int
    observed_at: str
    valid_from: str
    valid_to: Optional[str]
    metadata: Dict[str, Any]


class ScrapedDataToSignalConverter:
    """
    Converts raw scraped market data to canonical signals.
    
    Usage:
        converter = ScrapedDataToSignalConverter()
        signals = converter.convert_market_snapshot(scraped_data)
    """
    
    def convert_market_snapshot(
        self,
        market_id: str,
        scraped_data: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        Convert a full market snapshot to canonical signals.
        
        Args:
            market_id: Market identifier (used as geo_id)
            scraped_data: Output from signal_scraper.py
            
        Returns:
            List of canonical signal dicts
        """
        signals = []
        now = datetime.utcnow()
        
        # 1️⃣ SUPPLY DENSITY
        if scraped_data.get("total_listings"):
            signals.append(self._create_supply_density_signal(market_id, scraped_data, now))
        
        # 2️⃣ BEDROOM DISTRIBUTION
        if scraped_data.get("listings_by_bedrooms"):
            signals.append(self._create_bedroom_distribution_signal(market_id, scraped_data, now))
        
        # 3️⃣ CALENDAR COMPRESSION
        if scraped_data.get("calendar_compression_7d") is not None:
            signals.append(self._create_calendar_compression_signal(market_id, scraped_data, now))
        
        # 4️⃣ PLATFORM DOMINANCE
        if scraped_data.get("airbnb_share") is not None:
            signals.append(self._create_platform_dominance_signal(market_id, scraped_data, now))
        
        # 5️⃣ AMENITY PREVALENCE (one per amenity)
        if scraped_data.get("amenity_prevalence"):
            for amenity, prevalence in scraped_data["amenity_prevalence"].items():
                signals.append(self._create_amenity_prevalence_signal(
                    market_id, amenity, prevalence, scraped_data, now
                ))
        
        # 6️⃣ RATE POSITION
        if scraped_data.get("rate_p50"):
            signals.append(self._create_rate_position_signal(market_id, scraped_data, now))
        
        # 7️⃣ RATE BY BEDROOM
        if scraped_data.get("rate_by_bedrooms"):
            signals.append(self._create_rate_by_bedroom_signal(market_id, scraped_data, now))
        
        return signals
    
    def _create_supply_density_signal(
        self,
        market_id: str,
        data: Dict,
        now: datetime,
    ) -> Dict[str, Any]:
        """Create supply density signal."""
        total = data["total_listings"]
        
        # Confidence based on sample size
        confidence = self._sample_size_confidence(total, thresholds=[30, 100, 200])
        
        # Confidence band: ±10% for high confidence, ±20% for low
        band_pct = 0.10 if confidence >= 0.75 else 0.15 if confidence >= 0.5 else 0.20
        
        return {
            "signal_id": str(uuid4()),
            "signal_type": SignalType.SUPPLY_DENSITY.value,
            "geo_id": market_id,
            "property_id": None,
            "source": SignalSource.DERIVED.value,
            "source_detail": "airbnb_public + vrbo_public aggregation",
            "value": {
                "listings": total,
                "listings_per_sq_mile": None,  # Would need geo area
                "listings_per_1000_homes": None,  # Would need Census data
                "by_platform": data.get("listings_by_platform", {}),
            },
            "unit": "listings",
            "confidence": confidence,
            "confidence_band": (
                int(total * (1 - band_pct)),
                int(total * (1 + band_pct)),
            ),
            "confidence_level": self._confidence_level(confidence),
            "decay_half_life_days": 14,
            "observed_at": now.isoformat(),
            "valid_from": now.isoformat(),
            "valid_to": None,
            "metadata": {
                "airbnb_count": data.get("listing_count_airbnb", 0),
                "vrbo_count": data.get("listing_count_vrbo", 0),
                "scrape_confidence": data.get("supply_confidence", "unknown"),
            },
        }
    
    def _create_bedroom_distribution_signal(
        self,
        market_id: str,
        data: Dict,
        now: datetime,
    ) -> Dict[str, Any]:
        """Create bedroom distribution signal."""
        dist = data["listings_by_bedrooms"]
        total = sum(dist.values())
        
        # Calculate percentages
        dist_pct = {k: v / total for k, v in dist.items()} if total else {}
        
        # Median
        sorted_br = sorted(dist.items())
        cumsum = 0
        median_br = 0
        for br, count in sorted_br:
            cumsum += count
            if cumsum >= total / 2:
                median_br = br
                break
        
        confidence = self._sample_size_confidence(total, [30, 100, 200])
        
        return {
            "signal_id": str(uuid4()),
            "signal_type": SignalType.BEDROOM_DISTRIBUTION.value,
            "geo_id": market_id,
            "property_id": None,
            "source": SignalSource.DERIVED.value,
            "value": {
                "distribution": dist,
                "distribution_pct": dist_pct,
                "median_bedrooms": median_br,
            },
            "unit": "count",
            "confidence": confidence,
            "confidence_band": (median_br - 1, median_br + 1),
            "confidence_level": self._confidence_level(confidence),
            "decay_half_life_days": 30,
            "observed_at": now.isoformat(),
            "valid_from": now.isoformat(),
            "valid_to": None,
            "metadata": {"sample_size": total},
        }
    
    def _create_calendar_compression_signal(
        self,
        market_id: str,
        data: Dict,
        now: datetime,
    ) -> Dict[str, Any]:
        """Create calendar compression (demand) signal."""
        blocked_7d = data.get("calendar_compression_7d", 0)
        blocked_14d = data.get("calendar_compression_14d", 0)
        blocked_30d = data.get("calendar_compression_30d", 0)
        
        # Confidence based on demand confidence from scraper
        conf_map = {"high": 0.85, "medium": 0.65, "low": 0.45}
        confidence = conf_map.get(data.get("demand_confidence", "low"), 0.45)
        
        # Band: wider for lower confidence
        band_pct = 0.05 if confidence >= 0.75 else 0.10 if confidence >= 0.5 else 0.15
        
        return {
            "signal_id": str(uuid4()),
            "signal_type": SignalType.CALENDAR_COMPRESSION.value,
            "geo_id": market_id,
            "property_id": None,
            "source": SignalSource.DERIVED.value,
            "source_detail": "Public calendar availability analysis",
            "value": {
                "blocked_pct_7d": blocked_7d,
                "blocked_pct_14d": blocked_14d,
                "blocked_pct_30d": blocked_30d,
                "blocked_pct_60d": data.get("calendar_compression_60d"),
                "blocked_pct_90d": data.get("calendar_compression_90d"),
                "sample_size": data.get("total_listings", 0),
            },
            "unit": "percent_blocked",
            "confidence": confidence,
            "confidence_band": (
                max(0, blocked_30d - band_pct),
                min(1, blocked_30d + band_pct),
            ),
            "confidence_level": self._confidence_level(confidence),
            "decay_half_life_days": 7,  # Demand signals decay quickly
            "observed_at": now.isoformat(),
            "valid_from": now.isoformat(),
            "valid_to": None,
            "metadata": {
                "demand_confidence": data.get("demand_confidence"),
                "interpretation": self._interpret_demand(blocked_30d),
            },
        }
    
    def _create_platform_dominance_signal(
        self,
        market_id: str,
        data: Dict,
        now: datetime,
    ) -> Dict[str, Any]:
        """Create platform dominance signal."""
        airbnb = data.get("airbnb_share", 0)
        vrbo = data.get("vrbo_share", 0)
        
        # Determine dominance
        if airbnb > 0.75:
            dominant = "airbnb"
            ratio = airbnb / vrbo if vrbo > 0 else 10
        elif vrbo > 0.75:
            dominant = "vrbo"
            ratio = vrbo / airbnb if airbnb > 0 else 10
        else:
            dominant = "balanced"
            ratio = max(airbnb, vrbo) / min(airbnb, vrbo) if min(airbnb, vrbo) > 0 else 1
        
        conf_map = {"high": 0.85, "medium": 0.65, "low": 0.45}
        confidence = conf_map.get(data.get("platform_confidence", "low"), 0.45)
        
        return {
            "signal_id": str(uuid4()),
            "signal_type": SignalType.PLATFORM_DOMINANCE.value,
            "geo_id": market_id,
            "property_id": None,
            "source": SignalSource.DERIVED.value,
            "value": {
                "airbnb_share": airbnb,
                "vrbo_share": vrbo,
                "other_share": 1 - airbnb - vrbo,
                "dominant_platform": dominant,
                "dominance_ratio": round(ratio, 2),
            },
            "unit": "share",
            "confidence": confidence,
            "confidence_band": (
                max(0, airbnb - 0.05),
                min(1, airbnb + 0.05),
            ),
            "confidence_level": self._confidence_level(confidence),
            "decay_half_life_days": 30,
            "observed_at": now.isoformat(),
            "valid_from": now.isoformat(),
            "valid_to": None,
            "metadata": {
                "platform_dominance_label": data.get("platform_dominance"),
            },
        }
    
    def _create_amenity_prevalence_signal(
        self,
        market_id: str,
        amenity: str,
        prevalence: float,
        data: Dict,
        now: datetime,
    ) -> Dict[str, Any]:
        """Create amenity prevalence signal."""
        total = data.get("total_listings", 0)
        count = int(prevalence * total)
        
        confidence = self._sample_size_confidence(total, [20, 50, 100])
        
        # Wider bands for rare amenities
        band_pct = 0.03 if prevalence > 0.3 else 0.05 if prevalence > 0.1 else 0.08
        
        return {
            "signal_id": str(uuid4()),
            "signal_type": SignalType.AMENITY_PREVALENCE.value,
            "geo_id": market_id,
            "property_id": None,
            "source": SignalSource.DERIVED.value,
            "value": {
                "amenity": amenity,
                "prevalence_pct": prevalence,
                "count": count,
                "total_listings": total,
            },
            "unit": "percent",
            "confidence": confidence,
            "confidence_band": (
                max(0, prevalence - band_pct),
                min(1, prevalence + band_pct),
            ),
            "confidence_level": self._confidence_level(confidence),
            "decay_half_life_days": 30,
            "observed_at": now.isoformat(),
            "valid_from": now.isoformat(),
            "valid_to": None,
            "metadata": {
                "scarcity_score": 1 - prevalence,  # Higher = more rare = more valuable
                "is_differentiator": prevalence < 0.3,
            },
        }
    
    def _create_rate_position_signal(
        self,
        market_id: str,
        data: Dict,
        now: datetime,
    ) -> Dict[str, Any]:
        """Create rate position signal."""
        p25 = data.get("rate_p25", 0)
        p50 = data.get("rate_p50", 0)
        p75 = data.get("rate_p75", 0)
        
        conf_map = {"high": 0.85, "medium": 0.65, "low": 0.45}
        confidence = conf_map.get(data.get("rate_confidence", "low"), 0.45)
        
        return {
            "signal_id": str(uuid4()),
            "signal_type": SignalType.RATE_POSITION.value,
            "geo_id": market_id,
            "property_id": None,
            "source": SignalSource.DERIVED.value,
            "source_detail": "Displayed nightly rates from search results",
            "value": {
                "p10": data.get("rate_p10"),
                "p25": p25,
                "p50": p50,
                "p75": p75,
                "p90": data.get("rate_p90"),
                "sample_size": data.get("total_listings", 0),
            },
            "unit": "dollars",
            "confidence": confidence,
            "confidence_band": (p25, p75),  # IQR as confidence band
            "confidence_level": self._confidence_level(confidence),
            "decay_half_life_days": 14,
            "observed_at": now.isoformat(),
            "valid_from": now.isoformat(),
            "valid_to": None,
            "metadata": {
                "rate_confidence": data.get("rate_confidence"),
                "avg_rating": data.get("avg_rating"),
                "avg_reviews": data.get("avg_reviews"),
            },
        }
    
    def _create_rate_by_bedroom_signal(
        self,
        market_id: str,
        data: Dict,
        now: datetime,
    ) -> Dict[str, Any]:
        """Create rate by bedroom signal."""
        rates = data.get("rate_by_bedrooms", {})
        
        conf_map = {"high": 0.85, "medium": 0.65, "low": 0.45}
        confidence = conf_map.get(data.get("rate_confidence", "low"), 0.45)
        
        return {
            "signal_id": str(uuid4()),
            "signal_type": SignalType.RATE_BY_BEDROOM.value,
            "geo_id": market_id,
            "property_id": None,
            "source": SignalSource.DERIVED.value,
            "value": {
                "rates": rates,
                "sample_sizes": {},  # Would need per-BR sample sizes
            },
            "unit": "dollars",
            "confidence": confidence,
            "confidence_band": (
                min(rates.values()) * 0.85 if rates else 0,
                max(rates.values()) * 1.15 if rates else 0,
            ),
            "confidence_level": self._confidence_level(confidence),
            "decay_half_life_days": 14,
            "observed_at": now.isoformat(),
            "valid_from": now.isoformat(),
            "valid_to": None,
            "metadata": {},
        }
    
    def convert_census_data(
        self,
        market_id: str,
        census_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Convert Census ACS data to housing stock signal."""
        now = datetime.utcnow()
        
        return {
            "signal_id": str(uuid4()),
            "signal_type": SignalType.HOUSING_STOCK.value,
            "geo_id": market_id,
            "property_id": None,
            "source": SignalSource.CENSUS_ACS.value,
            "source_detail": f"ACS 5-Year {census_data.get('year', 2022)}",
            "value": {
                "total_housing_units": census_data.get("total_housing_units"),
                "vacancy_rate": census_data.get("vacancy_rate"),
                "seasonal_vacant_pct": census_data.get("seasonal_vacant_pct"),
                "median_home_value": census_data.get("median_home_value"),
                "median_rent": census_data.get("median_rent"),
                "second_home_pct": census_data.get("seasonal_vacant_pct"),  # Proxy
            },
            "unit": "units",
            "confidence": 0.95,  # Census data is high confidence
            "confidence_band": (
                census_data.get("total_housing_units", 0) * 0.98,
                census_data.get("total_housing_units", 0) * 1.02,
            ),
            "confidence_level": "high",
            "decay_half_life_days": 365,  # Census data is annual
            "observed_at": now.isoformat(),
            "valid_from": now.isoformat(),
            "valid_to": None,
            "metadata": {
                "geo_name": census_data.get("geo_name"),
                "year": census_data.get("year"),
                "source_table": "B25001, B25002, B25004, B25077",
            },
        }
    
    # Helper methods
    
    def _sample_size_confidence(
        self,
        n: int,
        thresholds: List[int],
    ) -> float:
        """Calculate confidence based on sample size."""
        if n >= thresholds[2]:
            return 0.90
        elif n >= thresholds[1]:
            return 0.75
        elif n >= thresholds[0]:
            return 0.55
        else:
            return 0.35
    
    def _confidence_level(self, confidence: float) -> str:
        """Convert numeric confidence to level."""
        if confidence >= 0.75:
            return "high"
        elif confidence >= 0.5:
            return "medium"
        elif confidence >= 0.25:
            return "low"
        else:
            return "insufficient"
    
    def _interpret_demand(self, blocked_pct: float) -> str:
        """Interpret demand level from calendar compression."""
        if blocked_pct >= 0.7:
            return "Very High Demand - calendars heavily booked"
        elif blocked_pct >= 0.5:
            return "High Demand - strong booking activity"
        elif blocked_pct >= 0.3:
            return "Moderate Demand - typical booking levels"
        else:
            return "Low Demand - significant availability"


# =============================================================================
# CLI USAGE
# =============================================================================

def convert_scraped_file(input_file: str, output_file: str):
    """Convert a scraped JSON file to canonical signals."""
    import json
    from pathlib import Path
    
    with open(input_file) as f:
        scraped_data = json.load(f)
    
    converter = ScrapedDataToSignalConverter()
    
    market_id = scraped_data.get("market_id", "unknown")
    signals = converter.convert_market_snapshot(market_id, scraped_data)
    
    output = {
        "market_id": market_id,
        "converted_at": datetime.utcnow().isoformat(),
        "signal_count": len(signals),
        "signals": signals,
    }
    
    with open(output_file, 'w') as f:
        json.dump(output, f, indent=2, default=str)
    
    print(f"✅ Converted {len(signals)} signals")
    print(f"💾 Saved to: {output_file}")
    
    return signals


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 3:
        print("Usage: python signal_converter.py <input.json> <output.json>")
        sys.exit(1)
    
    convert_scraped_file(sys.argv[1], sys.argv[2])
