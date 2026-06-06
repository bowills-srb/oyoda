"""
Orchestration: Intelligence Runner.

This is the COORDINATOR layer - it decides WHEN and HOW to run intelligence.
It does NOT compute - it delegates to execution layer (which calls domain).

Responsibilities:
- Coordinate signal collection → processing → output
- Manage the intelligence pipeline
- Handle batch vs real-time execution
- Route to appropriate executors

Non-responsibilities:
- Actual signal math (domain layer via executors)
- Database access (repository layer)
- HTTP calls (adapter layer)
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Callable
from uuid import UUID

# Domain imports (for types only)
from app.domain.signals import (
    Signal,
    SignalType,
    SignalBundle,
    check_confidence_gate,
    OutputType,
    classify_confidence,
    ConfidenceTier,
)
from app.domain.governance import (
    PolicyDecision,
    HealthGrade,
)
from app.domain.forecasting import (
    AnnualProjection,
)

# Execution imports (thin wrappers that call domain)
from app.services.execution import (
    # Forecasting
    PropertyPayload,
    MarketPayload,
    CompSetPayload,
    OperatorPayload,
    ProjectionPayload,
    get_forecasting_executor,
    
    # Governance
    PolicyEvaluationPayload,
    get_governance_executor,
    
    # Signals
    get_signal_executor,
)


# =============================================================================
# EXECUTION MODES
# =============================================================================

class ExecutionMode(str, Enum):
    """How intelligence should be executed."""
    REALTIME = "realtime"      # Sync, immediate response
    BATCH = "batch"            # Async, queued
    STREAMING = "streaming"    # Incremental updates


class IntelligenceType(str, Enum):
    """Types of intelligence operations."""
    SIGNAL_ASSEMBLY = "signal_assembly"
    PROJECTION = "projection"
    PRICING_RECOMMENDATION = "pricing_recommendation"
    DISCOUNT_EVALUATION = "discount_evaluation"
    MARKET_ANALYSIS = "market_analysis"
    EXPANSION_SCORE = "expansion_score"


# =============================================================================
# INTELLIGENCE CONTEXT
# =============================================================================

@dataclass
class IntelligenceContext:
    """
    Context for an intelligence operation.
    
    Passed through the pipeline to track state and provide audit trail.
    """
    request_id: str
    tenant_id: UUID
    intelligence_type: IntelligenceType
    execution_mode: ExecutionMode = ExecutionMode.REALTIME
    
    # Scoping
    geo_id: Optional[str] = None
    property_id: Optional[UUID] = None
    
    # Timing
    started_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    
    # Policy
    policy_name: Optional[str] = None
    
    # Results tracking
    signals_used: int = 0
    confidence: float = 0.0
    policy_decision: Optional[PolicyDecision] = None
    
    # Errors
    errors: List[str] = field(default_factory=list)
    
    def mark_complete(self):
        """Mark the operation as complete."""
        self.completed_at = datetime.utcnow()
    
    @property
    def duration_ms(self) -> Optional[float]:
        """Get duration in milliseconds."""
        if not self.completed_at:
            return None
        return (self.completed_at - self.started_at).total_seconds() * 1000
    
    def to_audit_dict(self) -> Dict[str, Any]:
        """Export for audit logging."""
        return {
            "request_id": self.request_id,
            "tenant_id": str(self.tenant_id),
            "intelligence_type": self.intelligence_type.value,
            "execution_mode": self.execution_mode.value,
            "geo_id": self.geo_id,
            "property_id": str(self.property_id) if self.property_id else None,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_ms": self.duration_ms,
            "signals_used": self.signals_used,
            "confidence": self.confidence,
            "policy_decision": self.policy_decision.to_audit_record() if self.policy_decision else None,
            "errors": self.errors,
        }


# =============================================================================
# INTELLIGENCE RESULT
# =============================================================================

@dataclass
class IntelligenceResult:
    """
    Result of an intelligence operation.
    
    Wraps the actual output with metadata.
    """
    success: bool
    context: IntelligenceContext
    
    # The actual output
    output: Any = None
    
    # Quality indicators
    confidence: float = 0.0
    confidence_tier: ConfidenceTier = ConfidenceTier.INSUFFICIENT
    
    # Gating
    is_gated: bool = False
    gate_reason: Optional[str] = None
    
    # Allowed output types at this confidence
    allowed_outputs: List[OutputType] = field(default_factory=list)


# =============================================================================
# SIGNAL PROVIDER PROTOCOL
# =============================================================================

class SignalProvider:
    """
    Protocol for signal data sources.
    
    Implementations provide signals from different sources:
    - Database
    - Cache
    - Real-time scrapers
    - etc.
    
    The orchestrator doesn't care WHERE signals come from.
    """
    
    def get_signals(
        self,
        tenant_id: UUID,
        geo_id: Optional[str] = None,
        property_id: Optional[UUID] = None,
        signal_types: Optional[List[SignalType]] = None,
    ) -> List[Signal]:
        """Get signals matching criteria."""
        raise NotImplementedError


# =============================================================================
# INTELLIGENCE ORCHESTRATOR
# =============================================================================

class IntelligenceOrchestrator:
    """
    Central orchestrator for all intelligence operations.
    
    This is the COORDINATION layer that:
    - Accepts requests
    - Gathers signals
    - Applies policies
    - Delegates to domain functions
    - Returns results
    
    It does NOT:
    - Compute signal math (domain layer does this)
    - Access databases directly (providers do this)
    - Make HTTP calls (adapters do this)
    """
    
    def __init__(
        self,
        signal_provider: Optional[SignalProvider] = None,
        default_policy: str = "high_confidence_pricing",
    ):
        self.signal_provider = signal_provider
        self.default_policy = default_policy
        self._audit_log: List[Dict[str, Any]] = []
    
    # -------------------------------------------------------------------------
    # SIGNAL ASSEMBLY
    # -------------------------------------------------------------------------
    
    def assemble_signals(
        self,
        context: IntelligenceContext,
        signal_types: Optional[List[SignalType]] = None,
    ) -> SignalBundle:
        """
        Assemble signals into a bundle for downstream use.
        
        This is the entry point for any intelligence that needs signals.
        """
        if not self.signal_provider:
            # Return empty bundle if no provider
            return SignalBundle(
                geo_id=context.geo_id or "unknown",
                property_id=context.property_id,
                tenant_id=context.tenant_id,
            )
        
        signals = self.signal_provider.get_signals(
            tenant_id=context.tenant_id,
            geo_id=context.geo_id,
            property_id=context.property_id,
            signal_types=signal_types,
        )
        
        bundle = SignalBundle.from_signal_list(
            signals=signals,
            geo_id=context.geo_id or "unknown",
            property_id=context.property_id,
            tenant_id=context.tenant_id,
        )
        
        context.signals_used = bundle.signal_count
        context.confidence = bundle.overall_confidence
        
        return bundle
    
    # -------------------------------------------------------------------------
    # PROJECTION
    # -------------------------------------------------------------------------
    
    def run_projection(
        self,
        context: IntelligenceContext,
        property_payload: PropertyPayload,
        market_payload: MarketPayload,
        internal_comps: Optional[CompSetPayload] = None,
        external_comps: Optional[CompSetPayload] = None,
        operator_payload: Optional[OperatorPayload] = None,
        commission_rate: float = 0.20,
    ) -> IntelligenceResult:
        """
        Run a revenue projection.
        
        Delegates computation to execution layer.
        """
        context.intelligence_type = IntelligenceType.PROJECTION
        
        try:
            # Build projection payload
            payload = ProjectionPayload(
                property=property_payload,
                market=market_payload,
                internal_comps=internal_comps,
                external_comps=external_comps,
                operator=operator_payload,
                commission_rate=commission_rate,
            )
            
            # Use executor (which calls domain)
            executor = get_forecasting_executor()
            projection = executor.generate_projection(payload)
            
            context.confidence = projection.confidence
            context.mark_complete()
            
            # Check confidence gating
            gate = check_confidence_gate(projection.confidence, OutputType.BD_PROJECTION)
            tier = classify_confidence(projection.confidence)
            
            result = IntelligenceResult(
                success=True,
                context=context,
                output=projection,
                confidence=projection.confidence,
                confidence_tier=tier,
                is_gated=not gate.passed,
                gate_reason=gate.message if not gate.passed else None,
                allowed_outputs=[ot for ot in OutputType if check_confidence_gate(projection.confidence, ot).passed],
            )
            
            self._log_operation(context)
            return result
            
        except Exception as e:
            context.errors.append(str(e))
            context.mark_complete()
            return IntelligenceResult(
                success=False,
                context=context,
                confidence=0.0,
                confidence_tier=ConfidenceTier.INSUFFICIENT,
            )
    
    # -------------------------------------------------------------------------
    # POLICY EVALUATION
    # -------------------------------------------------------------------------
    
    def evaluate_policy(
        self,
        context: IntelligenceContext,
        policy_name: Optional[str] = None,
        confidence: Optional[float] = None,
        health_grade: str = "C",  # HealthGrade value
        value: Optional[float] = None,
        **extra_context,
    ) -> PolicyDecision:
        """
        Evaluate a decision against policy.
        
        Uses execution layer for policy evaluation.
        """
        policy_name = policy_name or context.policy_name or self.default_policy
        confidence = confidence if confidence is not None else context.confidence
        
        # Use executor (which calls domain)
        executor = get_governance_executor()
        
        payload = PolicyEvaluationPayload(
            policy_name=policy_name,
            confidence=confidence,
            health_grade=health_grade,
            value=value,
            extra_context=extra_context,
        )
        
        result = executor.evaluate_policy(payload)
        
        # Convert result back to domain PolicyDecision for context storage
        from app.domain.governance import PolicyAction, EscalationLevel
        decision = PolicyDecision(
            policy_id=UUID(int=0),  # Not tracked at this level
            policy_name=policy_name,
            action=PolicyAction(result.action),
            reason=result.reason,
            matched_rule=result.matched_rule,
            escalation=EscalationLevel(result.escalation),
            requires_audit=result.requires_audit,
            audit_reason=result.audit_reason,
        )
        
        context.policy_decision = decision
        return decision
    
    # -------------------------------------------------------------------------
    # FULL INTELLIGENCE PIPELINE
    # -------------------------------------------------------------------------
    
    def run_full_intelligence(
        self,
        context: IntelligenceContext,
        property_payload: PropertyPayload,
        market_payload: MarketPayload,
        internal_comps: Optional[CompSetPayload] = None,
        external_comps: Optional[CompSetPayload] = None,
        operator_payload: Optional[OperatorPayload] = None,
        commission_rate: float = 0.20,
        policy_name: Optional[str] = None,
    ) -> IntelligenceResult:
        """
        Run complete intelligence pipeline:
        1. Assemble signals
        2. Run projection
        3. Evaluate policy
        4. Return gated result
        """
        # 1. Assemble signals (if provider available)
        bundle = self.assemble_signals(context)
        
        # 2. Run projection (using payloads now)
        result = self.run_projection(
            context=context,
            property_payload=property_payload,
            market_payload=market_payload,
            internal_comps=internal_comps,
            external_comps=external_comps,
            operator_payload=operator_payload,
            commission_rate=commission_rate,
        )
        
        if not result.success:
            return result
        
        # 3. Evaluate policy
        decision = self.evaluate_policy(
            context=context,
            policy_name=policy_name,
            confidence=result.confidence,
        )
        
        # 4. Apply policy decision
        if decision.is_gated():
            result.is_gated = True
            result.gate_reason = decision.reason
        
        return result
    
    # -------------------------------------------------------------------------
    # AUDIT
    # -------------------------------------------------------------------------
    
    def _log_operation(self, context: IntelligenceContext):
        """Log operation for audit."""
        self._audit_log.append(context.to_audit_dict())
    
    def get_audit_log(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent audit entries."""
        return self._audit_log[-limit:]


# =============================================================================
# CONVENIENCE FACTORY
# =============================================================================

_orchestrator: Optional[IntelligenceOrchestrator] = None


def get_orchestrator() -> IntelligenceOrchestrator:
    """Get the singleton orchestrator."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = IntelligenceOrchestrator()
    return _orchestrator


def set_signal_provider(provider: SignalProvider):
    """Set the signal provider for the orchestrator."""
    get_orchestrator().signal_provider = provider


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Enums
    "ExecutionMode",
    "IntelligenceType",
    
    # Context & Result
    "IntelligenceContext",
    "IntelligenceResult",
    
    # Protocol
    "SignalProvider",
    
    # Orchestrator
    "IntelligenceOrchestrator",
    "get_orchestrator",
    "set_signal_provider",
]
