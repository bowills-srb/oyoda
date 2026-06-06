"""
Domain: Signals

Pure domain layer for signal intelligence.

No FastAPI. No DB sessions. No external API calls.
"""

from .models import (
    Signal,
    SignalType,
    SignalScope,
    SignalSource,
    SignalStage,
    SignalLifecycleEvent,
    SignalAttribution,
)

from .computations import (
    # Decay functions
    slow_decay,
    very_slow_decay,
    medium_decay,
    fast_decay,
    very_fast_decay,
    DECAY_PROFILES,
    get_decay_fn,
    
    # Weighting
    WeightedSignalResult,
    compute_weighted_value,
    compute_weighted_average,
    compute_weighted_average_with_confidence,
    
    # Bundle
    SignalBundle,
)

from .confidence import (
    # Types
    OutputType,
    ConfidenceTier,
    
    # Thresholds
    ConfidenceThresholds,
    THRESHOLDS,
    get_threshold,
    is_confidence_sufficient,
    
    # Gating
    GatingDecision,
    check_confidence_gate,
    check_multiple_gates,
    
    # Classification
    classify_confidence,
    get_allowed_outputs,
)


__all__ = [
    # Models
    "Signal",
    "SignalType",
    "SignalScope",
    "SignalSource",
    "SignalStage",
    "SignalLifecycleEvent",
    "SignalAttribution",
    
    # Decay
    "slow_decay",
    "very_slow_decay",
    "medium_decay",
    "fast_decay",
    "very_fast_decay",
    "DECAY_PROFILES",
    "get_decay_fn",
    
    # Weighting
    "WeightedSignalResult",
    "compute_weighted_value",
    "compute_weighted_average",
    "compute_weighted_average_with_confidence",
    
    # Bundle
    "SignalBundle",
    
    # Confidence
    "OutputType",
    "ConfidenceTier",
    "ConfidenceThresholds",
    "THRESHOLDS",
    "get_threshold",
    "is_confidence_sufficient",
    "GatingDecision",
    "check_confidence_gate",
    "check_multiple_gates",
    "classify_confidence",
    "get_allowed_outputs",
]
