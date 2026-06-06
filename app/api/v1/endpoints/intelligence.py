"""
Signal Intelligence API - Strategic Gap #3.

Competitors lock data in dashboards.
We provide API-first access to real-time signals.

This module provides:
- RESTful endpoints for signal queries
- GraphQL-ready schema patterns
- Direct export to BI systems
- Real-time signal streaming (future)

Makes our intelligence a PLATFORM LAYER, not just a SaaS screen.
"""

from datetime import date, datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.signals import (
    SignalBundle,
    SignalType,
    get_seasonality,
    get_platform_bias,
    get_amenity_lift,
    get_operator_delta,
)
from app.services.analytics.engine import (
    AnalyticsEngine,
    PropertyConfig,
    get_analytics_engine,
)
from app.services.forecasting.demand_forecast import (
    generate_demand_forecast,
    DemandForecast,
)
from app.services.attribution.attribution_service import (
    explain_adr,
    what_if_add_amenity,
    AttributionReport,
    ScenarioResult,
)


router = APIRouter(prefix="/intelligence", tags=["intelligence"])


# =============================================================================
# REQUEST/RESPONSE MODELS
# =============================================================================

class SignalQueryRequest(BaseModel):
    """Request for signal query."""
    tenant_id: UUID
    geo_id: str
    property_id: Optional[UUID] = None
    signal_types: Optional[List[str]] = None
    as_of_date: Optional[date] = None


class SignalResponse(BaseModel):
    """Individual signal response."""
    signal_type: str
    value: float
    confidence: float
    detected_at: datetime
    metadata: Optional[Dict[str, Any]] = None


class SignalBundleResponse(BaseModel):
    """Response with multiple signals."""
    geo_id: str
    property_id: Optional[UUID]
    signals: Dict[str, List[SignalResponse]]
    signal_count: int
    overall_confidence: float
    retrieved_at: datetime


class ForecastRequest(BaseModel):
    """Request for demand forecast."""
    tenant_id: UUID
    geo_id: str
    base_adr: float
    as_of_date: Optional[date] = None


class ForecastResponse(BaseModel):
    """Demand forecast response."""
    geo_id: str
    
    # 30-day forecast
    forecast_30d: Dict[str, Any]
    
    # 60-day forecast
    forecast_60d: Dict[str, Any]
    
    # 90-day forecast
    forecast_90d: Dict[str, Any]
    
    # Trend
    trend_direction: str
    trend_strength: float
    
    # Insights
    insights: List[str]
    
    # Confidence
    overall_confidence: float
    computed_at: datetime


class AttributionRequest(BaseModel):
    """Request for ADR attribution."""
    tenant_id: UUID
    geo_id: str
    base_adr: float
    current_adr: float
    property_amenities: List[str]


class AttributionResponse(BaseModel):
    """Attribution report response."""
    metric_name: str
    base_value: float
    current_value: float
    change_pct: float
    
    # Drivers
    drivers: List[Dict[str, Any]]
    
    # Badges for UI
    badges: List[str]
    
    # Summary
    summary: str
    
    # Confidence
    overall_confidence: float


class WhatIfRequest(BaseModel):
    """Request for what-if scenario."""
    tenant_id: UUID
    geo_id: str
    current_adr: float
    current_amenities: List[str]
    add_amenity: str


class WhatIfResponse(BaseModel):
    """What-if scenario response."""
    scenario_name: str
    base_metric: float
    projected_metric: float
    delta: float
    delta_pct: float
    
    impact_drivers: List[Dict[str, Any]]
    confidence: float
    caveats: List[str]


class HealthResponse(BaseModel):
    """Signal health check response."""
    status: str
    signal_coverage: Dict[str, float]
    stale_signals: List[str]
    recommendations: List[str]


# =============================================================================
# MOCK SIGNAL BUNDLE LOADER
# In production, this would load from database
# =============================================================================

async def load_signal_bundle(
    tenant_id: UUID,
    geo_id: str,
    property_id: Optional[UUID] = None,
) -> SignalBundle:
    """
    Load signal bundle for a geo/property.
    
    In production, this queries the signals table.
    """
    # TODO: Replace with actual database query
    # For now, return empty bundle (will use defaults)
    return SignalBundle(
        geo_id=geo_id,
        property_id=property_id,
        tenant_id=tenant_id,
        signals={},
    )


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get("/health")
async def check_signal_health(
    tenant_id: UUID = Query(...),
    geo_id: str = Query(...),
) -> HealthResponse:
    """
    Check signal health for a geo.
    
    Returns:
    - Signal coverage by type
    - Stale signal warnings
    - Recommendations
    """
    bundle = await load_signal_bundle(tenant_id, geo_id)
    
    # Check coverage
    required_signals = [
        SignalType.SEASONALITY_CURVE,
        SignalType.PLATFORM_DOMINANCE,
        SignalType.AMENITY_LIFT,
        SignalType.OCCUPANCY_MOMENTUM,
    ]
    
    coverage = {}
    stale = []
    recommendations = []
    
    for sig_type in required_signals:
        if bundle.has_signal(sig_type):
            coverage[sig_type.value] = bundle.get_confidence(sig_type)
            # Check staleness (in production, check signal age)
        else:
            coverage[sig_type.value] = 0.0
            recommendations.append(f"Missing {sig_type.value} signal - run detector")
    
    status = "healthy" if all(v > 0.5 for v in coverage.values()) else "degraded"
    
    return HealthResponse(
        status=status,
        signal_coverage=coverage,
        stale_signals=stale,
        recommendations=recommendations,
    )


@router.post("/signals/query")
async def query_signals(request: SignalQueryRequest) -> SignalBundleResponse:
    """
    Query signals for a geo/property.
    
    Returns all relevant signals with confidence scores.
    
    Use this to:
    - Power custom dashboards
    - Feed BI tools
    - Build custom analytics
    """
    bundle = await load_signal_bundle(
        request.tenant_id,
        request.geo_id,
        request.property_id,
    )
    
    # Convert to response format
    signals_response = {}
    for sig_type, signals in bundle.signals.items():
        signals_response[sig_type.value if hasattr(sig_type, 'value') else sig_type] = [
            SignalResponse(
                signal_type=str(sig_type),
                value=s.value,
                confidence=s.confidence,
                detected_at=s.detected_at,
                metadata=s.metadata,
            )
            for s in signals
        ]
    
    return SignalBundleResponse(
        geo_id=request.geo_id,
        property_id=request.property_id,
        signals=signals_response,
        signal_count=bundle.signal_count,
        overall_confidence=bundle.overall_confidence,
        retrieved_at=datetime.utcnow(),
    )


@router.post("/forecast")
async def get_demand_forecast(request: ForecastRequest) -> ForecastResponse:
    """
    Get forward-looking demand forecast.
    
    Unlike competitors who show historical averages,
    this provides:
    - 30/60/90 day forecasts
    - Confidence bands
    - Driver attribution
    - Actionable insights
    """
    bundle = await load_signal_bundle(request.tenant_id, request.geo_id)
    
    forecast = generate_demand_forecast(
        bundle,
        request.geo_id,
        request.base_adr,
        as_of_date=request.as_of_date,
    )
    
    def band_to_dict(band) -> Dict[str, Any]:
        if not band:
            return {}
        return {
            "period_start": str(band.period_start),
            "period_end": str(band.period_end),
            "demand": {
                "low": band.demand_low,
                "expected": band.demand_expected,
                "high": band.demand_high,
            },
            "adr": {
                "low": band.adr_low,
                "expected": band.adr_expected,
                "high": band.adr_high,
            },
            "occupancy": {
                "low": band.occupancy_low,
                "expected": band.occupancy_expected,
                "high": band.occupancy_high,
            },
            "revenue": {
                "low": band.revenue_low,
                "expected": band.revenue_expected,
                "high": band.revenue_high,
            },
            "confidence": band.confidence,
            "drivers": band.drivers,
            "is_actionable": band.is_actionable(),
        }
    
    return ForecastResponse(
        geo_id=request.geo_id,
        forecast_30d=band_to_dict(forecast.forecast_30d),
        forecast_60d=band_to_dict(forecast.forecast_60d),
        forecast_90d=band_to_dict(forecast.forecast_90d),
        trend_direction=forecast.trend_direction,
        trend_strength=forecast.trend_strength,
        insights=forecast.insights,
        overall_confidence=forecast.overall_confidence,
        computed_at=forecast.computed_at,
    )


@router.post("/attribution/adr")
async def get_adr_attribution(request: AttributionRequest) -> AttributionResponse:
    """
    Explain ADR with driver attribution.
    
    Answers: "Why is ADR what it is?"
    
    Returns:
    - Driver breakdown (seasonality, amenities, operator, etc.)
    - Impact percentages
    - UI-ready badges ("Pool +10%")
    - Human-readable summary
    """
    bundle = await load_signal_bundle(request.tenant_id, request.geo_id)
    
    report = explain_adr(
        bundle,
        request.base_adr,
        request.current_adr,
        request.property_amenities,
    )
    
    return AttributionResponse(
        metric_name=report.metric_name,
        base_value=report.base_value,
        current_value=report.current_value,
        change_pct=report.change_pct,
        drivers=[
            {
                "category": d.category.value,
                "name": d.name,
                "contribution_pct": d.contribution_pct,
                "absolute_impact": d.absolute_impact,
                "direction": d.direction,
                "confidence": d.confidence,
                "badge_text": d.badge_text,
                "explanation": d.explanation,
            }
            for d in report.drivers
        ],
        badges=report.badges,
        summary=report.summary,
        overall_confidence=report.overall_confidence,
    )


@router.post("/whatif/amenity")
async def run_amenity_whatif(request: WhatIfRequest) -> WhatIfResponse:
    """
    What-if scenario: Add an amenity.
    
    Answers: "What if we added a pool?"
    
    Returns projected ADR change with confidence.
    """
    bundle = await load_signal_bundle(request.tenant_id, request.geo_id)
    
    result = what_if_add_amenity(
        bundle,
        request.current_adr,
        request.current_amenities,
        request.add_amenity,
    )
    
    return WhatIfResponse(
        scenario_name=result.scenario_name,
        base_metric=result.base_metric,
        projected_metric=result.projected_metric,
        delta=result.delta,
        delta_pct=result.delta_pct,
        impact_drivers=[
            {
                "category": d.category.value,
                "name": d.name,
                "absolute_impact": d.absolute_impact,
                "badge_text": d.badge_text,
                "confidence": d.confidence,
            }
            for d in result.impact_drivers
        ],
        confidence=result.confidence,
        caveats=result.caveats,
    )


@router.get("/export/csv")
async def export_signals_csv(
    tenant_id: UUID = Query(...),
    geo_id: str = Query(...),
    signal_types: Optional[List[str]] = Query(None),
):
    """
    Export signals as CSV for BI tools.
    
    Enables direct integration with:
    - Tableau
    - Power BI
    - Looker
    - Custom dashboards
    """
    from fastapi.responses import StreamingResponse
    import io
    import csv
    
    bundle = await load_signal_bundle(tenant_id, geo_id)
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Header
    writer.writerow([
        "signal_type", "value", "confidence", "detected_at", 
        "geo_id", "source"
    ])
    
    # Rows
    for sig_type, signals in bundle.signals.items():
        type_str = sig_type.value if hasattr(sig_type, 'value') else str(sig_type)
        if signal_types and type_str not in signal_types:
            continue
        
        for s in signals:
            writer.writerow([
                type_str,
                s.value,
                s.confidence,
                s.detected_at.isoformat(),
                geo_id,
                s.source.value if hasattr(s.source, 'value') else str(s.source),
            ])
    
    output.seek(0)
    
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=signals_{geo_id}_{date.today()}.csv"
        }
    )


# =============================================================================
# GRAPHQL-READY SCHEMA (Future)
# =============================================================================

"""
GraphQL Schema (for future implementation):

type Signal {
    signalType: String!
    value: Float!
    confidence: Float!
    detectedAt: DateTime!
    metadata: JSON
}

type ForecastBand {
    periodStart: Date!
    periodEnd: Date!
    demand: RangeBand!
    adr: RangeBand!
    occupancy: RangeBand!
    revenue: RangeBand!
    confidence: Float!
    drivers: [Driver!]!
}

type RangeBand {
    low: Float!
    expected: Float!
    high: Float!
}

type Driver {
    category: String!
    name: String!
    contributionPct: Float!
    absoluteImpact: Float!
    direction: String!
    confidence: Float!
    badgeText: String!
}

type Query {
    signals(tenantId: ID!, geoId: String!, propertyId: ID): SignalBundle!
    forecast(tenantId: ID!, geoId: String!, baseAdr: Float!): DemandForecast!
    attribution(tenantId: ID!, geoId: String!, baseAdr: Float!, currentAdr: Float!, amenities: [String!]!): AttributionReport!
}

type Mutation {
    runWhatIf(scenario: WhatIfInput!): ScenarioResult!
}
"""
