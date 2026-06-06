"""
Projection Workers - Refactored to use Orchestration Layer.

This worker demonstrates the new architecture:
- Worker receives job payload
- Worker calls ONE orchestrator (same as API)
- Orchestrator coordinates the pipeline
- Domain layer computes
- Worker stores/returns result

SAME CODE PATH as API. No duplication. No divergence.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import Field

from workers.base import (
    BaseWorker,
    JobPayload,
    JobResult,
    WorkerCategory,
    register_worker,
)

# Import from orchestration layer (same import as API endpoint)
from app.services.orchestration import (
    IntelligenceOrchestrator,
    IntelligenceContext,
    IntelligenceType,
    get_orchestrator,
    # Payloads (re-exported from execution)
    PropertyPayload,
    MarketPayload,
    CompSetPayload,
    OperatorPayload,
)


# =============================================================================
# PAYLOADS
# =============================================================================

class ProjectionJobPayload(JobPayload):
    """
    Payload for projection job.
    
    Mirrors the API request but in worker format.
    """
    # Property details
    bedrooms: int
    bathrooms: float
    property_type: str = "single_family"
    sqft: Optional[int] = None
    amenities: List[str] = Field(default_factory=list)
    is_new_listing: bool = False
    months_active: int = 12
    
    # Market context
    market_id: str
    market_name: Optional[str] = None
    market_type: str = "coastal"
    median_adr_by_bedroom: Dict[int, float] = Field(default_factory=dict)
    median_occupancy_by_bedroom: Dict[int, float] = Field(default_factory=dict)
    
    # Optional: Comparable data
    internal_comps: Optional[Dict[str, Any]] = None
    external_comps: Optional[Dict[str, Any]] = None
    
    # Optional: Operator data
    operator_data: Optional[Dict[str, Any]] = None
    
    # Commission and policy
    commission_rate: float = 0.20
    policy_name: str = "high_confidence_pricing"
    
    # Storage options
    store_result: bool = True
    result_key: Optional[str] = None


class BatchProjectionPayload(JobPayload):
    """
    Payload for batch projection job.
    
    Run projections for multiple properties at once.
    """
    properties: List[Dict[str, Any]]
    
    # Shared market context
    market_id: str
    market_name: Optional[str] = None
    market_type: str = "coastal"
    median_adr_by_bedroom: Dict[int, float] = Field(default_factory=dict)
    median_occupancy_by_bedroom: Dict[int, float] = Field(default_factory=dict)
    
    # Options
    commission_rate: float = 0.20
    policy_name: str = "high_confidence_pricing"
    continue_on_error: bool = True


# =============================================================================
# WORKERS
# =============================================================================

@register_worker
class ProjectionWorker(BaseWorker[ProjectionJobPayload]):
    """
    Generate revenue projection for a single property.
    
    Uses the SAME orchestration layer as the API endpoint.
    This guarantees:
    - Identical computation logic
    - Identical policy enforcement
    - Identical confidence gating
    
    No sync vs async divergence. No duplicated business logic.
    """
    
    name = "projection_worker"
    category = WorkerCategory.ANALYTICS
    max_retries = 3
    timeout_seconds = 60
    
    async def process(self, payload: ProjectionJobPayload) -> JobResult:
        """Process projection job using orchestration layer."""
        
        # Get the orchestrator (same as API endpoint does)
        orchestrator = get_orchestrator()
        
        # Build context
        context = IntelligenceContext(
            request_id=payload.result_key or str(uuid4()),
            tenant_id=payload.tenant_id,
            intelligence_type=IntelligenceType.PROJECTION,
            geo_id=payload.market_id,
            policy_name=payload.policy_name,
        )
        
        # Build property payload
        property_payload = PropertyPayload(
            bedrooms=payload.bedrooms,
            bathrooms=payload.bathrooms,
            property_type=payload.property_type,
            sqft=payload.sqft,
            amenities=payload.amenities,
            is_new_listing=payload.is_new_listing,
            months_active=payload.months_active,
        )
        
        # Build market payload
        market_payload = MarketPayload(
            market_id=payload.market_id,
            market_name=payload.market_name or payload.market_id,
            market_type=payload.market_type,
            median_adr_by_bedroom=payload.median_adr_by_bedroom,
            median_occupancy_by_bedroom=payload.median_occupancy_by_bedroom,
        )
        
        # Build optional comp set payload
        internal_comps = None
        if payload.internal_comps:
            internal_comps = CompSetPayload(
                source="internal",
                comp_count=payload.internal_comps.get("comp_count", 5),
                avg_adr=payload.internal_comps.get("avg_adr", 500),
                avg_occupancy=payload.internal_comps.get("avg_occupancy", 0.50),
                avg_similarity_score=payload.internal_comps.get("similarity", 0.80),
                data_coverage_pct=payload.internal_comps.get("coverage", 0.80),
            )
        
        # Build optional operator payload
        operator_payload = None
        if payload.operator_data:
            operator_payload = OperatorPayload(
                company_id=str(payload.tenant_id),
                portfolio_avg_adr=payload.operator_data.get("portfolio_adr", 500),
                portfolio_avg_occupancy=payload.operator_data.get("portfolio_occupancy", 0.50),
                market_avg_adr=payload.operator_data.get("market_adr", 450),
                market_avg_occupancy=payload.operator_data.get("market_occupancy", 0.48),
                property_count=payload.operator_data.get("property_count", 10),
                months_of_data=payload.operator_data.get("months_of_data", 12),
            )
        
        # === THIS IS THE KEY: SAME CALL AS API ===
        result = orchestrator.run_full_intelligence(
            context=context,
            property_payload=property_payload,
            market_payload=market_payload,
            internal_comps=internal_comps,
            operator_payload=operator_payload,
            commission_rate=payload.commission_rate,
            policy_name=payload.policy_name,
        )
        
        if not result.success:
            return JobResult(
                success=False,
                error=f"Projection failed: {result.context.errors}",
            )
        
        # Extract projection
        projection = result.output
        
        # Build result data
        # Calculate total nights from monthly projections
        total_nights = sum(
            int(mp.projected_occupancy * 30)  # Approx days per month
            for mp in projection.monthly_projections
        )
        
        # Calculate revenue range
        revenue_low = projection.projected_annual_revenue * 0.85
        revenue_high = projection.projected_annual_revenue * 1.15
        
        projection_data = {
            "projection_id": context.request_id,
            "generated_at": datetime.utcnow().isoformat(),
            
            # Annual totals
            "projected_annual_revenue": projection.projected_annual_revenue,
            "projected_net_revenue": projection.projected_net_to_owner,
            "revenue_low": revenue_low,
            "revenue_high": revenue_high,
            
            # Key metrics
            "average_adr": projection.avg_adr,
            "average_occupancy": projection.avg_occupancy,
            "projected_nights_booked": total_nights,
            
            # Confidence
            "confidence": result.confidence,
            "confidence_tier": result.confidence_tier.value,
            
            # Gating
            "is_gated": result.is_gated,
            "gate_reason": result.gate_reason,
            "allowed_outputs": [o.value for o in result.allowed_outputs],
            
            # Policy
            "policy_applied": payload.policy_name,
            "policy_decision": "allowed" if result.context.policy_decision and result.context.policy_decision.is_allowed() else "denied",
            
            # Monthly breakdown
            "monthly_projections": [
                {
                    "month": mp.month,
                    "adr": mp.avg_nightly_rate,
                    "occupancy": mp.projected_occupancy,
                    "nights_booked": int(mp.projected_occupancy * 30),
                    "gross_revenue": mp.projected_revenue,
                    "net_revenue": mp.projected_revenue * (1 - projection.commission_rate),
                }
                for mp in projection.monthly_projections
            ],
            
            # Reasoning
            "reasoning": {
                "base_adr_source": projection.reasoning.base_adr_source,
                "base_occupancy_source": projection.reasoning.seasonality_source,
                "amenity_uplifts": {u.name: u.factor for u in projection.reasoning.uplifts_applied},
                "seasonality_applied": projection.reasoning.seasonality_profile is not None,
                "operator_delta_applied": projection.reasoning.operator_delta is not None,
                "new_listing_penalty_applied": projection.reasoning.new_listing_adjustment is not None,
                "confidence_factors": projection.reasoning.confidence_factors,
            },
            
            # Metadata
            "execution_time_ms": result.context.duration_ms,
            "engine_version": projection.reasoning.engine_version,
        }
        
        return JobResult(
            success=True,
            data={"projection": projection_data},
            items_processed=1,
        )


@register_worker
class BatchProjectionWorker(BaseWorker[BatchProjectionPayload]):
    """
    Generate projections for multiple properties.
    
    Uses the same orchestration layer, just loops over properties.
    Useful for:
    - Portfolio analysis
    - Market studies
    - BD lead scoring
    """
    
    name = "batch_projection_worker"
    category = WorkerCategory.ANALYTICS
    max_retries = 2
    timeout_seconds = 600  # 10 minutes for large batches
    
    async def process(self, payload: BatchProjectionPayload) -> JobResult:
        """Process batch of projections."""
        
        orchestrator = get_orchestrator()
        
        results = []
        errors = []
        
        for i, prop in enumerate(payload.properties):
            try:
                # Build context for this property
                context = IntelligenceContext(
                    request_id=f"batch-{payload.tenant_id}-{i}",
                    tenant_id=payload.tenant_id,
                    intelligence_type=IntelligenceType.PROJECTION,
                    geo_id=payload.market_id,
                    policy_name=payload.policy_name,
                )
                
                # Build payloads from property dict
                property_payload = PropertyPayload(
                    bedrooms=prop.get("bedrooms", 3),
                    bathrooms=prop.get("bathrooms", 2.0),
                    property_type=prop.get("property_type", "single_family"),
                    sqft=prop.get("sqft"),
                    amenities=prop.get("amenities", []),
                    is_new_listing=prop.get("is_new_listing", False),
                    months_active=prop.get("months_active", 12),
                )
                
                market_payload = MarketPayload(
                    market_id=payload.market_id,
                    market_name=payload.market_name or payload.market_id,
                    market_type=payload.market_type,
                    median_adr_by_bedroom=payload.median_adr_by_bedroom,
                    median_occupancy_by_bedroom=payload.median_occupancy_by_bedroom,
                )
                
                # Run projection
                result = orchestrator.run_full_intelligence(
                    context=context,
                    property_payload=property_payload,
                    market_payload=market_payload,
                    commission_rate=payload.commission_rate,
                    policy_name=payload.policy_name,
                )
                
                if result.success:
                    projection = result.output
                    results.append({
                        "property_index": i,
                        "property_id": prop.get("property_id", f"prop-{i}"),
                        "bedrooms": property_payload.bedrooms,
                        "projected_annual_revenue": projection.projected_annual_revenue,
                        "projected_net_revenue": projection.projected_net_revenue,
                        "confidence": result.confidence,
                        "confidence_tier": result.confidence_tier.value,
                        "is_gated": result.is_gated,
                    })
                else:
                    errors.append({
                        "property_index": i,
                        "property_id": prop.get("property_id", f"prop-{i}"),
                        "error": str(result.context.errors),
                    })
                    if not payload.continue_on_error:
                        break
                        
            except Exception as e:
                errors.append({
                    "property_index": i,
                    "property_id": prop.get("property_id", f"prop-{i}"),
                    "error": str(e),
                })
                if not payload.continue_on_error:
                    break
        
        # Calculate summary stats
        if results:
            total_revenue = sum(r["projected_annual_revenue"] for r in results)
            avg_confidence = sum(r["confidence"] for r in results) / len(results)
            gated_count = sum(1 for r in results if r["is_gated"])
        else:
            total_revenue = 0
            avg_confidence = 0
            gated_count = 0
        
        return JobResult(
            success=len(errors) == 0 or payload.continue_on_error,
            data={
                "projections": results,
                "errors": errors,
                "summary": {
                    "total_properties": len(payload.properties),
                    "successful": len(results),
                    "failed": len(errors),
                    "total_projected_revenue": total_revenue,
                    "average_confidence": avg_confidence,
                    "gated_count": gated_count,
                }
            },
            items_processed=len(results),
            error=f"{len(errors)} properties failed" if errors else None,
        )
