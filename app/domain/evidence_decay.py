"""
Evidence Confidence Decay.

Time-aware trust for evidence records.

Rules:
- Fresh evidence (< 30 days): Full confidence
- Aging evidence (30-90 days): Linear decay
- Stale evidence (> 90 days): Minimum confidence
- Expired evidence (past expires_at): Zero confidence

This prevents:
- Stale WiFi passwords
- Outdated ADR bias
- Wrong concierge answers
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class FreshnessLevel(str, Enum):
    """Evidence freshness level."""
    FRESH = "fresh"          # < 30 days, full confidence
    AGING = "aging"          # 30-90 days, decaying
    STALE = "stale"          # > 90 days, minimum confidence
    EXPIRED = "expired"      # Past expires_at, zero confidence


@dataclass
class DecayConfig:
    """Configuration for confidence decay."""
    fresh_days: int = 30           # Days before decay starts
    stale_days: int = 90           # Days until minimum confidence
    minimum_confidence: float = 0.2  # Floor confidence for stale evidence
    
    # Field-specific overrides
    field_configs: Dict[str, "DecayConfig"] = None
    
    def __post_init__(self):
        if self.field_configs is None:
            self.field_configs = {}


# Default configs for different evidence types
DEFAULT_DECAY_CONFIGS = {
    # Property physical attributes - slow decay
    "beds": DecayConfig(fresh_days=365, stale_days=730, minimum_confidence=0.5),
    "baths": DecayConfig(fresh_days=365, stale_days=730, minimum_confidence=0.5),
    "sqft": DecayConfig(fresh_days=365, stale_days=730, minimum_confidence=0.5),
    
    # Access info - fast decay (security concern)
    "wifi_password": DecayConfig(fresh_days=30, stale_days=60, minimum_confidence=0.1),
    "lock_code": DecayConfig(fresh_days=30, stale_days=60, minimum_confidence=0.1),
    "entry_instructions": DecayConfig(fresh_days=30, stale_days=90, minimum_confidence=0.2),
    
    # Financial - medium decay
    "historical_rent": DecayConfig(fresh_days=90, stale_days=180, minimum_confidence=0.3),
    "adr": DecayConfig(fresh_days=30, stale_days=90, minimum_confidence=0.3),
    "occupancy": DecayConfig(fresh_days=30, stale_days=90, minimum_confidence=0.3),
    
    # Market signals - fast decay
    "market_event": DecayConfig(fresh_days=7, stale_days=30, minimum_confidence=0.1),
    "supply_demand": DecayConfig(fresh_days=7, stale_days=14, minimum_confidence=0.2),
    "pricing_signals": DecayConfig(fresh_days=3, stale_days=7, minimum_confidence=0.1),
    
    # Amenities - slow decay
    "amenities": DecayConfig(fresh_days=180, stale_days=365, minimum_confidence=0.4),
    "rules": DecayConfig(fresh_days=90, stale_days=180, minimum_confidence=0.3),
    
    # Default
    "default": DecayConfig(fresh_days=30, stale_days=90, minimum_confidence=0.2),
}


@dataclass
class EvidenceWithDecay:
    """Evidence record with decay-adjusted confidence."""
    field_name: str
    value: Any
    original_confidence: float
    adjusted_confidence: float
    freshness: FreshnessLevel
    age_days: int
    expires_at: Optional[datetime]
    is_usable: bool
    
    @property
    def confidence_loss(self) -> float:
        """How much confidence was lost to decay."""
        return self.original_confidence - self.adjusted_confidence


def compute_decayed_confidence(
    original_confidence: float,
    observed_at: datetime,
    field_name: str = "default",
    expires_at: Optional[datetime] = None,
    config: DecayConfig = None,
) -> tuple[float, FreshnessLevel]:
    """
    Compute decay-adjusted confidence for evidence.
    
    Args:
        original_confidence: Confidence when evidence was collected
        observed_at: When evidence was observed
        field_name: Field name for config lookup
        expires_at: Optional explicit expiration
        config: Override decay config
        
    Returns:
        (adjusted_confidence, freshness_level)
    """
    # Get current time (timezone-naive for comparison)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    
    # Make observed_at timezone-naive if it's aware
    if observed_at.tzinfo is not None:
        observed_at = observed_at.replace(tzinfo=None)
    
    # Check explicit expiration first
    if expires_at:
        if expires_at.tzinfo is not None:
            expires_at = expires_at.replace(tzinfo=None)
        if now > expires_at:
            return 0.0, FreshnessLevel.EXPIRED
    
    # Get config
    if config is None:
        config = DEFAULT_DECAY_CONFIGS.get(field_name, DEFAULT_DECAY_CONFIGS["default"])
    
    # Calculate age
    age = now - observed_at
    age_days = age.days
    
    # Fresh: no decay
    if age_days <= config.fresh_days:
        return original_confidence, FreshnessLevel.FRESH
    
    # Stale: minimum confidence
    if age_days >= config.stale_days:
        return config.minimum_confidence, FreshnessLevel.STALE
    
    # Aging: linear decay
    decay_range = config.stale_days - config.fresh_days
    days_into_decay = age_days - config.fresh_days
    decay_progress = days_into_decay / decay_range
    
    confidence_range = original_confidence - config.minimum_confidence
    adjusted = original_confidence - (confidence_range * decay_progress)
    
    return max(adjusted, config.minimum_confidence), FreshnessLevel.AGING


def apply_decay_to_evidence(
    evidence: Dict[str, Any],
) -> EvidenceWithDecay:
    """
    Apply decay to a single evidence record.
    
    Evidence dict format:
    {
        "field_name": "wifi_password",
        "value": "beach2026",
        "confidence": 0.9,
        "observed_at": "2026-01-01T00:00:00",
        "expires_at": "2026-06-01T00:00:00"  # optional
    }
    """
    field_name = evidence.get("field_name", "default")
    original_confidence = evidence.get("confidence", 0.5)
    observed_at = evidence.get("observed_at")
    expires_at = evidence.get("expires_at")
    
    # Parse dates
    if isinstance(observed_at, str):
        observed_at = datetime.fromisoformat(observed_at)
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at)
    
    if observed_at is None:
        observed_at = datetime.now(timezone.utc)  # Assume fresh if no date
    
    # Compute decay
    adjusted, freshness = compute_decayed_confidence(
        original_confidence=original_confidence,
        observed_at=observed_at,
        field_name=field_name,
        expires_at=expires_at,
    )
    
    # Calculate age
    age_days = (datetime.now(timezone.utc) - observed_at).days
    
    # Determine if usable (confidence > 0.1)
    is_usable = adjusted > 0.1
    
    return EvidenceWithDecay(
        field_name=field_name,
        value=evidence.get("value"),
        original_confidence=original_confidence,
        adjusted_confidence=adjusted,
        freshness=freshness,
        age_days=age_days,
        expires_at=expires_at,
        is_usable=is_usable,
    )


def filter_usable_evidence(
    evidence_list: List[Dict[str, Any]],
    min_confidence: float = 0.2,
) -> List[EvidenceWithDecay]:
    """
    Filter evidence to only usable records.
    
    Returns evidence with adjusted confidence >= min_confidence.
    """
    results = []
    
    for evidence in evidence_list:
        with_decay = apply_decay_to_evidence(evidence)
        if with_decay.adjusted_confidence >= min_confidence:
            results.append(with_decay)
    
    return results


def get_freshest_evidence(
    evidence_list: List[Dict[str, Any]],
    field_name: str,
) -> Optional[EvidenceWithDecay]:
    """
    Get the freshest usable evidence for a field.
    
    Returns the evidence with highest adjusted confidence.
    """
    candidates = []
    
    for evidence in evidence_list:
        if evidence.get("field_name") == field_name:
            with_decay = apply_decay_to_evidence(evidence)
            if with_decay.is_usable:
                candidates.append(with_decay)
    
    if not candidates:
        return None
    
    # Return highest confidence
    return max(candidates, key=lambda e: e.adjusted_confidence)


def compute_evidence_health(
    evidence_list: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Compute overall health metrics for evidence.
    
    Returns:
    {
        "total": 10,
        "fresh": 6,
        "aging": 2,
        "stale": 1,
        "expired": 1,
        "health_score": 0.75,
        "fields_needing_refresh": ["wifi_password", "lock_code"]
    }
    """
    counts = {
        FreshnessLevel.FRESH: 0,
        FreshnessLevel.AGING: 0,
        FreshnessLevel.STALE: 0,
        FreshnessLevel.EXPIRED: 0,
    }
    
    needs_refresh = []
    total_adjusted_confidence = 0.0
    
    for evidence in evidence_list:
        with_decay = apply_decay_to_evidence(evidence)
        counts[with_decay.freshness] += 1
        total_adjusted_confidence += with_decay.adjusted_confidence
        
        if with_decay.freshness in [FreshnessLevel.STALE, FreshnessLevel.EXPIRED]:
            needs_refresh.append(with_decay.field_name)
    
    total = len(evidence_list)
    
    return {
        "total": total,
        "fresh": counts[FreshnessLevel.FRESH],
        "aging": counts[FreshnessLevel.AGING],
        "stale": counts[FreshnessLevel.STALE],
        "expired": counts[FreshnessLevel.EXPIRED],
        "health_score": total_adjusted_confidence / total if total > 0 else 0.0,
        "fields_needing_refresh": list(set(needs_refresh)),
    }
