"""
Execution: Signal Executor.

Thin wrapper around domain signal logic.
Translates DTOs/payloads → domain inputs → domain outputs.

Does NOT:
- Make decisions about what to run
- Handle retries/fallbacks
- Manage async concerns
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.domain.signals import (
    Signal,
    SignalType,
    SignalScope,
    SignalSource,
    SignalBundle,
    compute_weighted_average,
    compute_weighted_average_with_confidence,
    check_confidence_gate,
    classify_confidence,
    get_allowed_outputs,
    OutputType,
    ConfidenceTier,
    GatingDecision,
)


# =============================================================================
# PAYLOADS (DTOs for execution)
# =============================================================================

@dataclass
class SignalPayload:
    """Input signal data."""
    tenant_id: str
    signal_type: str  # SignalType value
    scope: str        # SignalScope value
    value: float
    confidence: float
    source: str       # SignalSource value
    time_window: str
    geo_id: Optional[str] = None
    property_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class SignalBundlePayload:
    """Input for signal bundle assembly."""
    geo_id: str
    signals: List[SignalPayload]
    property_id: Optional[str] = None
    tenant_id: Optional[str] = None


@dataclass
class WeightedValueResult:
    """Output from weighted value calculation."""
    value: Optional[float]
    confidence: float
    signal_count: int


@dataclass
class ConfidenceCheckResult:
    """Output from confidence check."""
    passed: bool
    confidence: float
    threshold: float
    output_type: str
    tier: str
    allowed_outputs: List[str]


# =============================================================================
# SIGNAL EXECUTOR
# =============================================================================

class SignalExecutor:
    """
    Executes signal domain logic.
    
    Thin wrapper - translates DTOs to domain calls.
    No branching logic. No scheduling. No async.
    """
    
    def create_signal(self, payload: SignalPayload) -> Signal:
        """Create a signal from payload."""
        return Signal.create(
            tenant_id=UUID(payload.tenant_id),
            signal_type=SignalType(payload.signal_type),
            scope=SignalScope(payload.scope),
            value=payload.value,
            confidence=payload.confidence,
            source=SignalSource(payload.source),
            time_window=payload.time_window,
            geo_id=payload.geo_id,
            property_id=UUID(payload.property_id) if payload.property_id else None,
            metadata=payload.metadata,
        )
    
    def assemble_bundle(self, payload: SignalBundlePayload) -> SignalBundle:
        """Assemble signals into a bundle."""
        signals = [self.create_signal(sp) for sp in payload.signals]
        
        return SignalBundle.from_signal_list(
            signals=signals,
            geo_id=payload.geo_id,
            property_id=UUID(payload.property_id) if payload.property_id else None,
            tenant_id=UUID(payload.tenant_id) if payload.tenant_id else None,
        )
    
    def get_weighted_value(
        self, 
        bundle: SignalBundle, 
        signal_type: str,
        as_of: Optional[datetime] = None,
    ) -> WeightedValueResult:
        """Get weighted value for a signal type."""
        st = SignalType(signal_type)
        signals = bundle.get_all(st)
        
        value, confidence = compute_weighted_average_with_confidence(signals, as_of)
        
        return WeightedValueResult(
            value=value,
            confidence=confidence,
            signal_count=len(signals),
        )
    
    def check_confidence(
        self, 
        confidence: float, 
        output_type: str,
    ) -> ConfidenceCheckResult:
        """Check if confidence meets threshold for output type."""
        ot = OutputType(output_type)
        gate = check_confidence_gate(confidence, ot)
        tier = classify_confidence(confidence)
        allowed = get_allowed_outputs(confidence)
        
        return ConfidenceCheckResult(
            passed=gate.passed,
            confidence=confidence,
            threshold=gate.threshold,
            output_type=output_type,
            tier=tier.value,
            allowed_outputs=[o.value for o in allowed],
        )
    
    def get_bundle_summary(self, bundle: SignalBundle) -> Dict[str, Any]:
        """Get summary of a signal bundle."""
        return {
            "geo_id": bundle.geo_id,
            "property_id": str(bundle.property_id) if bundle.property_id else None,
            "tenant_id": str(bundle.tenant_id) if bundle.tenant_id else None,
            "signal_count": bundle.signal_count,
            "overall_confidence": bundle.overall_confidence,
            "signal_types_present": [st.value for st in bundle.signal_types_present],
            "assembled_at": bundle.assembled_at.isoformat(),
        }


# =============================================================================
# SINGLETON
# =============================================================================

_executor: Optional[SignalExecutor] = None


def get_signal_executor() -> SignalExecutor:
    """Get signal executor singleton."""
    global _executor
    if _executor is None:
        _executor = SignalExecutor()
    return _executor


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Payloads
    "SignalPayload",
    "SignalBundlePayload",
    "WeightedValueResult",
    "ConfidenceCheckResult",
    
    # Executor
    "SignalExecutor",
    "get_signal_executor",
]
