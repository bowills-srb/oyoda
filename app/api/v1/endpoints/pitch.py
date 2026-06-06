"""
API Endpoint: BD Pitch (Enhanced).

POST /pitch → Investment Synopsis + Optional PDF

Features:
- Assumption overrides (operator tightening)
- Display toggles (section visibility)
- PDF rendering (optional)
- Multiple return formats
"""

import base64
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.domain.bd import (
    ProjectionScenario,
    ScenarioType,
    AssumptionOverrides,
    OccupancyMode,
    ADRCeiling,
    DisplayToggles,
    InvestmentSynopsis,
    build_investment_synopsis,
)


router = APIRouter(prefix="/pitch", tags=["BD Pitch"])


# =============================================================================
# REQUEST SCHEMAS
# =============================================================================

class AssumptionOverridesInput(BaseModel):
    """Operator-controlled assumption tightening."""
    occupancy_mode: str = Field("baseline", pattern="^(conservative|baseline|optimized)$")
    adr_ceiling: str = Field("baseline", pattern="^(conservative|baseline|optimized)$")
    
    include_event_uplift: bool = True
    include_premium_furnishing_uplift: bool = True
    include_dynamic_pricing_uplift: bool = True
    
    management_penalty_pct: float = Field(0.0, ge=0, le=20)
    confidence_floor: float = Field(0.4, ge=0, le=1)


class DisplayTogglesInput(BaseModel):
    """UI display toggles for sections."""
    show_conservative_scenario: bool = True
    show_baseline_scenario: bool = True
    show_optimized_scenario: bool = True
    
    show_upside_analysis: bool = True
    show_risk_factors: bool = True
    show_market_context: bool = True
    show_comparable_analysis: bool = True
    
    show_monthly_breakdown: bool = False
    show_sensitivity_drivers: bool = True
    show_assumptions_used: bool = True


class PitchRequest(BaseModel):
    """Request for investment pitch."""
    property_id: UUID
    
    # Property data
    beds: int = Field(..., ge=1, le=20)
    baths: float = Field(..., ge=1, le=15)
    sqft: Optional[int] = Field(None, ge=100, le=50000)
    property_type: str = "Single Family"
    address: Optional[str] = None
    
    # Market
    market_id: str = ""
    market_name: str = ""
    
    # Projections (if pre-computed)
    annual_revenue_conservative: float = Field(0.0, ge=0)
    annual_revenue_baseline: float = Field(0.0, ge=0)
    annual_revenue_optimized: float = Field(0.0, ge=0)
    
    adr_low: float = Field(0.0, ge=0)
    adr_mid: float = Field(0.0, ge=0)
    adr_high: float = Field(0.0, ge=0)
    
    occupancy_low: float = Field(0.0, ge=0, le=1)
    occupancy_mid: float = Field(0.0, ge=0, le=1)
    occupancy_high: float = Field(0.0, ge=0, le=1)
    
    # Comparable data
    comparable_count: int = Field(0, ge=0)
    comparable_avg_revenue: float = Field(0.0, ge=0)
    
    # Operator controls
    assumption_overrides: Optional[AssumptionOverridesInput] = None
    display_toggles: Optional[DisplayTogglesInput] = None
    
    # PDF options
    include_pdf: bool = False
    pdf_style: str = Field("standard", pattern="^(standard|realtor|homeowner)$")
    return_format: str = Field("json", pattern="^(json|pdf|both)$")
    
    # Audience
    audience: str = Field("homeowner", pattern="^(homeowner|realtor|investor)$")
    
    # Operator tracking
    operator_id: Optional[str] = None


# =============================================================================
# RESPONSE SCHEMAS
# =============================================================================

class TightenedScenarioResponse(BaseModel):
    """Tightened scenario after overrides."""
    revenue_range: str
    monthly_range: str
    constraints_applied: List[str]
    confidence: str


class SynopsisResponse(BaseModel):
    """Investment synopsis response."""
    synopsis_id: str
    property_id: str
    
    # Property
    property_description: str
    address: Optional[str]
    
    # Tightened scenario (primary display)
    tightened_scenario: Optional[TightenedScenarioResponse]
    
    # Analysis
    upside_drivers: List[str]
    risk_factors: List[str]
    
    # Assumptions
    original_assumptions: List[str]
    tightened_assumptions: List[str]
    
    # Metadata
    comparable_count: int
    confidence_level: str
    generated_at: str
    
    # Overrides applied (for audit)
    overrides_applied: Optional[Dict[str, Any]]


class PitchResponse(BaseModel):
    """Full pitch response."""
    synopsis: SynopsisResponse
    
    # PDF (if requested)
    pdf_base64: Optional[str] = None
    
    # For UI: raw scenarios if needed
    scenarios: Optional[Dict[str, Any]] = None


# =============================================================================
# PRESETS
# =============================================================================

OVERRIDE_PRESETS = {
    "conservative": AssumptionOverrides.conservative(),
    "realtor_safe": AssumptionOverrides.realtor_safe(),
    "homeowner_friendly": AssumptionOverrides.homeowner_friendly(),
}


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.post("", response_model=PitchResponse)
async def generate_pitch(request: PitchRequest):
    """
    Generate investment pitch with optional PDF.
    
    Features:
    - Assumption overrides for tightening projections
    - Display toggles for section visibility
    - PDF rendering in multiple styles
    - Multiple return formats (json, pdf, both)
    
    Presets:
    - Use assumption_overrides.occupancy_mode = "conservative" for realtor-safe
    - Use include_event_uplift = false to exclude event-driven upside
    """
    
    # Build scenarios
    conservative = ProjectionScenario.create(
        scenario_type=ScenarioType.CONSERVATIVE,
        annual_revenue_min=request.annual_revenue_conservative * 0.9,
        annual_revenue_max=request.annual_revenue_conservative * 1.1,
        adr_min=request.adr_low * 0.95,
        adr_max=request.adr_low * 1.05,
        occupancy_min=request.occupancy_low * 0.95,
        occupancy_max=request.occupancy_low * 1.05,
        confidence=0.8,
        assumptions=["Conservative occupancy", "Below-market ADR"],
        drivers=["Seasonality", "Competition"],
        comparable_count=request.comparable_count,
    )
    
    baseline = ProjectionScenario.create(
        scenario_type=ScenarioType.BASELINE,
        annual_revenue_min=request.annual_revenue_baseline * 0.9,
        annual_revenue_max=request.annual_revenue_baseline * 1.1,
        adr_min=request.adr_mid * 0.95,
        adr_max=request.adr_mid * 1.05,
        occupancy_min=request.occupancy_mid * 0.95,
        occupancy_max=request.occupancy_mid * 1.05,
        confidence=0.7,
        assumptions=["Professional management", "Average furnishing"],
        drivers=["Furnishing quality", "Management approach"],
        comparable_count=request.comparable_count,
    )
    
    optimized = ProjectionScenario.create(
        scenario_type=ScenarioType.OPTIMIZED,
        annual_revenue_min=request.annual_revenue_optimized * 0.9,
        annual_revenue_max=request.annual_revenue_optimized * 1.1,
        adr_min=request.adr_high * 0.95,
        adr_max=request.adr_high * 1.05,
        occupancy_min=request.occupancy_high * 0.95,
        occupancy_max=request.occupancy_high * 1.05,
        confidence=0.55,
        assumptions=["Premium furnishing", "Dynamic pricing", "Event optimization"],
        drivers=["Dynamic pricing", "Guest experience", "Event demand"],
        comparable_count=request.comparable_count,
    )
    
    # Build overrides
    if request.assumption_overrides:
        overrides = AssumptionOverrides(
            occupancy_mode=OccupancyMode(request.assumption_overrides.occupancy_mode),
            adr_ceiling=ADRCeiling(request.assumption_overrides.adr_ceiling),
            include_event_uplift=request.assumption_overrides.include_event_uplift,
            include_premium_furnishing_uplift=request.assumption_overrides.include_premium_furnishing_uplift,
            include_dynamic_pricing_uplift=request.assumption_overrides.include_dynamic_pricing_uplift,
            management_penalty_pct=request.assumption_overrides.management_penalty_pct,
            confidence_floor=request.assumption_overrides.confidence_floor,
        )
    else:
        overrides = AssumptionOverrides()
    
    # Build display toggles
    if request.display_toggles:
        toggles = DisplayToggles(
            show_conservative_scenario=request.display_toggles.show_conservative_scenario,
            show_baseline_scenario=request.display_toggles.show_baseline_scenario,
            show_optimized_scenario=request.display_toggles.show_optimized_scenario,
            show_upside_analysis=request.display_toggles.show_upside_analysis,
            show_risk_factors=request.display_toggles.show_risk_factors,
            show_market_context=request.display_toggles.show_market_context,
            show_comparable_analysis=request.display_toggles.show_comparable_analysis,
            show_monthly_breakdown=request.display_toggles.show_monthly_breakdown,
            show_sensitivity_drivers=request.display_toggles.show_sensitivity_drivers,
            show_assumptions_used=request.display_toggles.show_assumptions_used,
        )
    else:
        toggles = DisplayToggles()
    
    # Build property snapshot
    property_snapshot = {
        "property_id": str(request.property_id),
        "description": f"{request.beds}BR/{request.baths}BA {request.property_type}",
        "beds": request.beds,
        "baths": request.baths,
        "sqft": request.sqft,
        "property_type": request.property_type,
        "address": request.address,
    }
    
    # Build market context
    market_context = {
        "market_id": request.market_id,
        "market_name": request.market_name,
        "summary": f"Analysis for {request.market_name or 'local market'}",
    }
    
    # Build synopsis
    synopsis = build_investment_synopsis(
        property_snapshot=property_snapshot,
        market_context=market_context,
        conservative=conservative,
        baseline=baseline,
        optimized=optimized,
        overrides=overrides,
        toggles=toggles,
        operator_id=request.operator_id,
    )
    
    # Build response
    tightened_response = None
    if synopsis.tightened_scenario:
        tightened_response = TightenedScenarioResponse(
            revenue_range=synopsis.tightened_scenario.revenue_range_formatted,
            monthly_range=synopsis.tightened_scenario.monthly_range_formatted,
            constraints_applied=synopsis.tightened_scenario.constraints_applied,
            confidence=synopsis.tightened_scenario.confidence_band.value,
        )
    
    synopsis_response = SynopsisResponse(
        synopsis_id=str(synopsis.synopsis_id),
        property_id=str(synopsis.property_id),
        property_description=property_snapshot["description"],
        address=request.address,
        tightened_scenario=tightened_response,
        upside_drivers=synopsis.upside_drivers,
        risk_factors=synopsis.risk_factors,
        original_assumptions=synopsis.original_assumptions,
        tightened_assumptions=synopsis.tightened_assumptions,
        comparable_count=synopsis.comparable_count,
        confidence_level=synopsis.tightened_scenario.confidence_band.value if synopsis.tightened_scenario else "medium",
        generated_at=synopsis.generated_at.isoformat(),
        overrides_applied=overrides.to_dict(),
    )
    
    # Generate PDF if requested
    pdf_base64 = None
    if request.include_pdf or request.return_format in ["pdf", "both"]:
        try:
            from app.services.bd.renderers import render_pitchbook_pdf
            pdf_bytes = render_pitchbook_pdf(synopsis, style=request.pdf_style)
            pdf_base64 = base64.b64encode(pdf_bytes).decode()
        except ImportError:
            # ReportLab not installed
            pass
        except Exception as e:
            # Log error but don't fail the request
            pass
    
    # Return based on format
    if request.return_format == "pdf" and pdf_base64:
        return Response(
            content=base64.b64decode(pdf_base64),
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=pitchbook_{request.property_id}.pdf"}
        )
    
    return PitchResponse(
        synopsis=synopsis_response,
        pdf_base64=pdf_base64 if request.return_format == "both" else None,
    )


@router.get("/presets")
async def get_presets():
    """Get available assumption override presets."""
    return {
        "presets": [
            {
                "name": "conservative",
                "description": "Extra conservative - for skeptical realtors",
                "overrides": OVERRIDE_PRESETS["conservative"].to_dict(),
            },
            {
                "name": "realtor_safe",
                "description": "Safe for realtor presentations",
                "overrides": OVERRIDE_PRESETS["realtor_safe"].to_dict(),
            },
            {
                "name": "homeowner_friendly",
                "description": "Shows upside potential for homeowners",
                "overrides": OVERRIDE_PRESETS["homeowner_friendly"].to_dict(),
            },
        ]
    }


@router.post("/preview")
async def preview_tightening(
    base_revenue_low: float,
    base_revenue_mid: float,
    base_revenue_high: float,
    occupancy_mode: str = "baseline",
    adr_ceiling: str = "baseline",
    include_event_uplift: bool = True,
    include_premium_furnishing_uplift: bool = True,
    management_penalty_pct: float = 0.0,
):
    """
    Preview how assumption overrides affect projections.
    
    Useful for UI sliders to show real-time impact.
    """
    # Build minimal scenarios
    conservative = ProjectionScenario.create(
        scenario_type=ScenarioType.CONSERVATIVE,
        annual_revenue_min=base_revenue_low * 0.9,
        annual_revenue_max=base_revenue_low * 1.1,
        adr_min=200, adr_max=250,
        occupancy_min=0.50, occupancy_max=0.55,
        confidence=0.8,
        assumptions=["Conservative"],
        drivers=["Seasonality"],
    )
    
    baseline = ProjectionScenario.create(
        scenario_type=ScenarioType.BASELINE,
        annual_revenue_min=base_revenue_mid * 0.9,
        annual_revenue_max=base_revenue_mid * 1.1,
        adr_min=250, adr_max=300,
        occupancy_min=0.60, occupancy_max=0.65,
        confidence=0.7,
        assumptions=["Baseline"],
        drivers=["Management"],
    )
    
    optimized = ProjectionScenario.create(
        scenario_type=ScenarioType.OPTIMIZED,
        annual_revenue_min=base_revenue_high * 0.9,
        annual_revenue_max=base_revenue_high * 1.1,
        adr_min=300, adr_max=400,
        occupancy_min=0.70, occupancy_max=0.75,
        confidence=0.55,
        assumptions=["Optimized"],
        drivers=["Dynamic pricing"],
    )
    
    # Apply overrides
    overrides = AssumptionOverrides(
        occupancy_mode=OccupancyMode(occupancy_mode),
        adr_ceiling=ADRCeiling(adr_ceiling),
        include_event_uplift=include_event_uplift,
        include_premium_furnishing_uplift=include_premium_furnishing_uplift,
        management_penalty_pct=management_penalty_pct,
    )
    
    # Build synopsis
    synopsis = build_investment_synopsis(
        property_snapshot={"description": "Preview"},
        market_context={},
        conservative=conservative,
        baseline=baseline,
        optimized=optimized,
        overrides=overrides,
    )
    
    return {
        "base_scenarios": {
            "conservative": f"${base_revenue_low:,.0f}",
            "baseline": f"${base_revenue_mid:,.0f}",
            "optimized": f"${base_revenue_high:,.0f}",
        },
        "tightened": {
            "revenue_range": synopsis.tightened_scenario.revenue_range_formatted if synopsis.tightened_scenario else None,
            "monthly_range": synopsis.tightened_scenario.monthly_range_formatted if synopsis.tightened_scenario else None,
            "constraints_applied": synopsis.tightened_scenario.constraints_applied if synopsis.tightened_scenario else [],
            "confidence": synopsis.tightened_scenario.confidence_band.value if synopsis.tightened_scenario else None,
        },
        "overrides_applied": overrides.to_dict(),
    }
