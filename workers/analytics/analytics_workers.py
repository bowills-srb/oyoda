"""
Analytics Workers - Heavy computation for BD intelligence.

These workers perform expensive analytics that should NEVER be synchronous:
- Market snapshots per polygon
- Discount scenario modeling
- Demand elasticity curves
- Operator benchmarking
- Pricing sensitivity analysis

All results are stored and consumed by BD agents/dashboards.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import Field

from workers.base import (
    BaseWorker,
    JobPayload,
    JobResult,
    WorkerCategory,
    register_worker,
)


# =============================================================================
# PAYLOADS
# =============================================================================

class MarketSnapshotPayload(JobPayload):
    """Payload for generating market snapshot."""
    polygon_id: UUID
    snapshot_date: date = Field(default_factory=date.today)
    period_type: str = "daily"  # daily, weekly, monthly
    
    # Options
    include_trends: bool = True
    include_composition: bool = True


class PricingSensitivityPayload(JobPayload):
    """Payload for pricing sensitivity analysis."""
    property_id: UUID
    
    # Date range to analyze
    start_date: date
    end_date: date
    
    # Scenarios to model
    rate_adjustments: List[float] = Field(
        default=[-0.20, -0.10, 0, 0.10, 0.20]  # -20% to +20%
    )


class DemandForecastPayload(JobPayload):
    """Payload for demand forecasting."""
    polygon_id: UUID
    
    # Forecast period
    forecast_start: date
    forecast_days: int = 90
    
    # Model options
    include_events: bool = True
    include_seasonality: bool = True


class OperatorBenchmarkPayload(JobPayload):
    """Payload for operator benchmarking."""
    operator_id: UUID
    
    # Comparison scope
    polygon_ids: Optional[List[UUID]] = None
    
    # Time period
    start_date: date
    end_date: date
    
    # Metrics to benchmark
    metrics: List[str] = Field(
        default=["adr", "occupancy", "revpar", "booking_lead_time"]
    )


class CompAnalysisPayload(JobPayload):
    """Payload for comparable property analysis."""
    property_id: UUID
    
    # Search criteria
    max_distance_miles: float = 5.0
    bedroom_range: tuple = (-1, 1)  # +/- 1 bedroom
    
    # Filters
    require_same_amenities: List[str] = Field(default_factory=list)
    min_data_months: int = 6


# =============================================================================
# WORKERS
# =============================================================================

@register_worker
class MarketSnapshotWorker(BaseWorker[MarketSnapshotPayload]):
    """
    Generate point-in-time market analytics for a polygon.
    
    Produces:
    - Supply metrics (listings, new, delisted)
    - Demand metrics (bookings, occupancy)
    - Pricing metrics (ADR, RevPAR, percentiles)
    - Composition (property types, bedrooms, channels)
    - YoY trends
    """
    
    name = "market_snapshot_worker"
    category = WorkerCategory.ANALYTICS
    max_retries = 3
    timeout_seconds = 300
    
    async def process(self, payload: MarketSnapshotPayload) -> JobResult:
        polygon_id = payload.polygon_id
        snapshot_date = payload.snapshot_date
        
        # In production, this would query the database
        # Here we build the structure
        
        snapshot = {
            "polygon_id": str(polygon_id),
            "tenant_id": str(payload.tenant_id),
            "snapshot_date": snapshot_date.isoformat(),
            "period_type": payload.period_type,
            "computed_at": datetime.utcnow().isoformat(),
            
            # Supply metrics
            "supply": {
                "total_listings": 0,
                "active_listings": 0,
                "new_listings_period": 0,
                "delisted_period": 0,
            },
            
            # Demand metrics
            "demand": {
                "total_bookings_period": 0,
                "total_nights_booked": 0,
                "avg_occupancy": 0.0,
            },
            
            # Pricing metrics
            "pricing": {
                "avg_adr": Decimal("0"),
                "median_adr": Decimal("0"),
                "adr_25th_percentile": Decimal("0"),
                "adr_75th_percentile": Decimal("0"),
                "avg_revpar": Decimal("0"),
            },
            
            # Composition
            "composition": {
                "property_type_breakdown": {},
                "bedroom_breakdown": {},
                "channel_breakdown": {},
            },
            
            # Trends (if requested)
            "trends": None,
            
            # Data quality
            "data_completeness": 1.0,
            "source_count": 1,
        }
        
        if payload.include_trends:
            snapshot["trends"] = {
                "adr_change_yoy": None,
                "occupancy_change_yoy": None,
                "supply_change_yoy": None,
            }
        
        return JobResult(
            success=True,
            data={"snapshot": snapshot},
            items_processed=1,
        )


@register_worker  
class PricingSensitivityWorker(BaseWorker[PricingSensitivityPayload]):
    """
    Model pricing sensitivity for a property.
    
    REFACTORED: Now uses domain layer via execution layer.
    Same code path as API endpoints.
    
    Produces:
    - Demand elasticity curve
    - Revenue optimization point
    - Scenario comparisons (what-if at different rate levels)
    """
    
    name = "pricing_sensitivity_worker"
    category = WorkerCategory.ANALYTICS
    max_retries = 3
    timeout_seconds = 300
    
    async def process(self, payload: PricingSensitivityPayload) -> JobResult:
        from app.services.execution import get_pricing_executor, SensitivityPayload
        
        property_id = payload.property_id
        
        # In production, base_adr and base_occupancy would come from database
        # For now, use reasonable defaults
        base_adr = 250.0  # Would query property data
        base_occupancy = 0.65
        
        # Calculate analysis period
        analysis_days = (payload.end_date - payload.start_date).days
        
        # === USE EXECUTION LAYER (SAME AS API) ===
        executor = get_pricing_executor()
        
        sensitivity_payload = SensitivityPayload(
            base_adr=base_adr,
            base_occupancy=base_occupancy,
            analysis_days=analysis_days,
            rate_adjustments=payload.rate_adjustments,
            elasticity=-1.5,  # Default elasticity
        )
        
        result = executor.calculate_sensitivity(sensitivity_payload)
        
        # Convert domain result to worker output format
        scenarios = [
            {
                "rate_adjustment": s.rate_adjustment,
                "adjusted_adr": s.adjusted_adr,
                "projected_occupancy": s.projected_occupancy,
                "nights_booked": s.nights_booked,
                "projected_revenue": s.projected_revenue,
            }
            for s in result.scenarios
        ]
        
        return JobResult(
            success=True,
            data={
                "property_id": str(property_id),
                "analysis_period": {
                    "start": payload.start_date.isoformat(),
                    "end": payload.end_date.isoformat(),
                },
                "base_adr": result.base_adr,
                "base_occupancy": result.base_occupancy,
                "scenarios": scenarios,
                "optimal_adjustment": result.optimal_adjustment,
                "optimal_revenue": result.optimal_revenue,
                "elasticity_estimate": result.elasticity,
            },
            items_processed=len(scenarios),
        )


@register_worker
class DemandForecastWorker(BaseWorker[DemandForecastPayload]):
    """
    Forecast demand for a market polygon.
    
    Produces:
    - Daily demand forecast
    - Confidence intervals
    - Event impacts
    - Seasonality patterns
    """
    
    name = "demand_forecast_worker"
    category = WorkerCategory.ANALYTICS
    max_retries = 3
    timeout_seconds = 300
    
    async def process(self, payload: DemandForecastPayload) -> JobResult:
        polygon_id = payload.polygon_id
        
        # Generate daily forecasts
        forecasts = []
        current_date = payload.forecast_start
        
        for day_offset in range(payload.forecast_days):
            forecast_date = current_date + timedelta(days=day_offset)
            
            # Base demand (would come from ML model)
            base_demand = 0.60
            
            # Seasonality adjustment
            if payload.include_seasonality:
                month = forecast_date.month
                # Simple seasonality curve
                seasonality = {
                    1: 0.7, 2: 0.7, 3: 0.9, 4: 0.85, 5: 0.9, 6: 1.2,
                    7: 1.3, 8: 1.2, 9: 0.8, 10: 0.75, 11: 0.8, 12: 0.9
                }
                base_demand *= seasonality.get(month, 1.0)
            
            # Weekend boost
            if forecast_date.weekday() >= 4:  # Fri, Sat, Sun
                base_demand *= 1.15
            
            forecasts.append({
                "date": forecast_date.isoformat(),
                "predicted_occupancy": min(0.95, base_demand),
                "confidence_low": min(0.95, base_demand * 0.85),
                "confidence_high": min(0.98, base_demand * 1.15),
                "events": [],  # Would include local events
            })
        
        return JobResult(
            success=True,
            data={
                "polygon_id": str(polygon_id),
                "forecast_start": payload.forecast_start.isoformat(),
                "forecast_days": payload.forecast_days,
                "daily_forecasts": forecasts,
                "model_version": "1.0",
            },
            items_processed=len(forecasts),
        )


@register_worker
class OperatorBenchmarkWorker(BaseWorker[OperatorBenchmarkPayload]):
    """
    Benchmark operator performance against market.
    
    Produces:
    - ADR delta vs market
    - Occupancy delta vs market
    - RevPAR comparison
    - Performance by property segment
    """
    
    name = "operator_benchmark_worker"
    category = WorkerCategory.ANALYTICS
    max_retries = 3
    timeout_seconds = 300
    
    async def process(self, payload: OperatorBenchmarkPayload) -> JobResult:
        operator_id = payload.operator_id
        
        # In production, this queries actual data
        # Here we build the benchmark structure
        
        benchmark = {
            "operator_id": str(operator_id),
            "tenant_id": str(payload.tenant_id),
            "period": {
                "start": payload.start_date.isoformat(),
                "end": payload.end_date.isoformat(),
            },
            "computed_at": datetime.utcnow().isoformat(),
            
            # Overall performance
            "overall": {
                "operator_adr": 285.0,
                "market_adr": 250.0,
                "adr_delta_pct": 0.14,  # +14%
                
                "operator_occupancy": 0.72,
                "market_occupancy": 0.65,
                "occupancy_delta_pct": 0.107,  # +10.7%
                
                "operator_revpar": 205.2,
                "market_revpar": 162.5,
                "revpar_delta_pct": 0.263,  # +26.3%
            },
            
            # By bedroom count
            "by_bedrooms": {
                "2": {"adr_delta": 0.10, "occupancy_delta": 0.08},
                "3": {"adr_delta": 0.12, "occupancy_delta": 0.09},
                "4": {"adr_delta": 0.15, "occupancy_delta": 0.11},
                "5+": {"adr_delta": 0.18, "occupancy_delta": 0.12},
            },
            
            # By property type
            "by_property_type": {
                "single_family": {"adr_delta": 0.14, "occupancy_delta": 0.10},
                "condo": {"adr_delta": 0.08, "occupancy_delta": 0.07},
            },
            
            # Confidence
            "confidence": {
                "data_months": 12,
                "property_count": 45,
                "score": 0.85,
            },
        }
        
        return JobResult(
            success=True,
            data={"benchmark": benchmark},
            items_processed=1,
        )


@register_worker
class CompAnalysisWorker(BaseWorker[CompAnalysisPayload]):
    """
    Find and analyze comparable properties.
    
    Produces:
    - Ranked list of comps with similarity scores
    - Performance data for each comp
    - Aggregate statistics
    """
    
    name = "comp_analysis_worker"
    category = WorkerCategory.ANALYTICS
    max_retries = 3
    timeout_seconds = 180
    
    async def process(self, payload: CompAnalysisPayload) -> JobResult:
        property_id = payload.property_id
        
        # In production, this performs geo queries and similarity scoring
        # Here we build the structure
        
        analysis = {
            "subject_property_id": str(property_id),
            "search_criteria": {
                "max_distance_miles": payload.max_distance_miles,
                "bedroom_range": payload.bedroom_range,
                "required_amenities": payload.require_same_amenities,
            },
            "computed_at": datetime.utcnow().isoformat(),
            
            # Comparable properties
            "comps": [
                {
                    "property_id": "comp-1",
                    "similarity_score": 0.92,
                    "distance_miles": 0.8,
                    "bedrooms": 4,
                    "bathrooms": 3.5,
                    "amenities_match": ["pool", "hot_tub", "waterfront"],
                    "performance": {
                        "avg_adr": 310.0,
                        "avg_occupancy": 0.68,
                        "annual_revenue": 76900.0,
                    },
                },
                {
                    "property_id": "comp-2", 
                    "similarity_score": 0.88,
                    "distance_miles": 1.2,
                    "bedrooms": 4,
                    "bathrooms": 4.0,
                    "amenities_match": ["pool", "waterfront"],
                    "performance": {
                        "avg_adr": 295.0,
                        "avg_occupancy": 0.71,
                        "annual_revenue": 76500.0,
                    },
                },
            ],
            
            # Aggregate statistics
            "aggregates": {
                "comp_count": 2,
                "avg_similarity": 0.90,
                "avg_adr": 302.5,
                "avg_occupancy": 0.695,
                "avg_annual_revenue": 76700.0,
            },
        }
        
        return JobResult(
            success=True,
            data={"analysis": analysis},
            items_processed=len(analysis["comps"]),
        )
