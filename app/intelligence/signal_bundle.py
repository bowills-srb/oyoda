from dataclasses import dataclass
from datetime import datetime
from typing import List, Dict, Optional
import math

# =============================================================================
# Canonical Signal Bundle (Read Contract v1.0.0)
# =============================================================================


# -----------------------------------------------------------------------------
# Raw signal (read-only, DB-derived)
# -----------------------------------------------------------------------------
@dataclass(frozen=True)
class Signal:
    signal_type: str
    scope: str
    geo_id: Optional[str]
    property_id: Optional[str]
    value: float
    confidence: float
    weight_hint: Optional[float]
    detected_at: datetime
    time_window: str
    source: str
    version: str


# -----------------------------------------------------------------------------
# Resolved signal (post-processing)
# -----------------------------------------------------------------------------
@dataclass(frozen=True)
class ResolvedSignal:
    signal_type: str
    resolved_value: float
    confidence_weighted_value: float
    effective_confidence: float
    contributing_signals: int


# -----------------------------------------------------------------------------
# Signal bundle (deterministic snapshot)
# -----------------------------------------------------------------------------
@dataclass(frozen=True)
class SignalBundle:
    tenant_id: str
    scope: str
    as_of: datetime
    signals: Dict[str, ResolvedSignal]
    version: str = "v1.0.0"


# =============================================================================
# Resolution logic
# =============================================================================

def decay_factor(
    detected_at: datetime,
    as_of: datetime,
    half_life_days: int = 30
) -> float:
    """
    Exponential decay based on signal age.
    Half-life semantics: value halves every `half_life_days`.
    """
    age_days = (as_of - detected_at).days
    if age_days <= 0:
        return 1.0

    return math.exp(-math.log(2) * age_days / half_life_days)


def resolve_signal_group(
    signals: List[Signal],
    as_of: datetime
) -> ResolvedSignal:
    """
    Resolve a group of same-type signals into a single deterministic value.
    """
    if not signals:
        raise ValueError("No signals to resolve")

    weighted_sum = 0.0
    confidence_sum = 0.0

    for s in signals:
        decay = decay_factor(s.detected_at, as_of)
        weight = s.confidence * decay * (s.weight_hint or 1.0)

        weighted_sum += s.value * weight
        confidence_sum += weight

    resolved_value = (
        weighted_sum / confidence_sum
        if confidence_sum > 0
        else 0.0
    )

    return ResolvedSignal(
        signal_type=signals[0].signal_type,
        resolved_value=resolved_value,
        confidence_weighted_value=weighted_sum,
        effective_confidence=min(1.0, confidence_sum / len(signals)),
        contributing_signals=len(signals),
    )
