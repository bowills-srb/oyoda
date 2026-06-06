"""
Signals Service Package - Signal Consumption Layer.

This package provides the ONLY interface for consuming signals.
All market intelligence flows through here.

NEW in v2.0:
- SignalPipeline for production storage/retrieval
- CoverageScore for BD intelligence grading
- Attribution for PDF footnotes
- Scheduler for automated collection

NEW in v2.1:
- DynamicDecay for adaptive signal half-lives
- MarketDynamics for price velocity and calendar delta tracking
- RegimeDetection for cross-signal consistency
- ScarcityAmenity for prevalence-weighted amenity uplift

MIGRATION NOTE:
- Old code uses signal_contract.py (still works)
- New code should use schemas/canonical_signals.py
"""

# =============================================================================
# CANONICAL SIGNALS (v2.0 - Use for new code)
# =============================================================================

from schemas.canonical_signals import (
    SignalType as CanonicalSignalType,
    SignalSource as CanonicalSignalSource,
    ConfidenceLevel,
    Signal as CanonicalSignal,
    SignalBundle as CanonicalSignalBundle,
)

# =============================================================================
# SIGNAL PIPELINE (Production infrastructure)
# =============================================================================

from app.services.signals.signal_pipeline import (
    PipelineConfig,
    SignalStore,
    SignalProcessor,
    SignalCache,
    SignalPipeline,
    SignalValidator,
    PipelineMetrics,
)

# =============================================================================
# COVERAGE SCORING (BD intelligence grading)
# =============================================================================

from app.services.signals.coverage_score import (
    CoverageScore,
    CoverageScoreCalculator,
    CoverageSlideGenerator,
    SignalCategory,
    calculate_coverage_score,
    generate_bd_slide_content,
)

# =============================================================================
# ATTRIBUTION (PDF footnotes & citations)
# =============================================================================

from app.services.signals.attribution import (
    Attribution,
    AttributionBundle,
    AttributionGenerator,
    ProFormaAttributionMixin,
    SourceReliability,
    generate_signal_footnotes,
    generate_attribution_bundle,
)

# =============================================================================
# SCHEDULER (Job orchestration)
# =============================================================================

from app.services.signals.scheduler import (
    MarketConfig,
    SchedulerConfig,
    JobRunner,
    SignalScheduler,
    Job,
    MARKETS,
)

# =============================================================================
# DYNAMIC DECAY (v2.1 - Adaptive half-lives)
# =============================================================================

from app.services.signals.dynamic_decay import (
    DynamicDecayEngine,
    MarketContextBuilder,
    MarketContext,
    DecayCalculation,
    SeasonPhase,
    MarketRegime as DecayMarketRegime,
    calculate_dynamic_decay,
    get_decay_engine,
)

# =============================================================================
# MARKET DYNAMICS (v2.1 - Price velocity, calendar delta)
# =============================================================================

from app.services.signals.market_dynamics import (
    PriceVelocityEngine,
    CalendarDeltaEngine,
    PriceVelocityResult,
    CalendarDeltaResult,
    PriceObservation,
    CalendarObservation,
    PriceDirection,
    DemandDirection,
    MomentumStrength,
    calculate_price_velocity,
    calculate_calendar_delta,
)

# =============================================================================
# REGIME DETECTION (v2.1 - Cross-signal consistency)
# =============================================================================

from app.services.signals.regime_detection import (
    RegimeDetectionEngine,
    CrossSignalConsistencyEngine,
    RegimeResult,
    ConsistencyResult,
    MarketRegime,
    SignalAgreement,
    ConfidenceAdjustment,
    detect_market_regime,
    check_signal_consistency,
    get_adjusted_confidence,
)

# =============================================================================
# SCARCITY-WEIGHTED AMENITY (v2.1 - Prevalence-adjusted uplift)
# =============================================================================

from app.services.signals.scarcity_amenity import (
    ScarcityWeightedAmenityEngine,
    ScarcityAdjustedLift,
    AmenityScarcityAnalysis,
    AmenityCategory,
    calculate_scarcity_adjusted_lift,
    analyze_market_amenity_scarcity,
)

# =============================================================================
# LEGACY CONTRACT (v1.0 - Still works, but use canonical for new code)
# =============================================================================

from app.services.signals.signal_contract import (
    SignalType,
    SignalScope,
    SignalSource,
    Signal,
    SignalBundle,
    slow_decay,
    very_slow_decay,
    medium_decay,
    fast_decay,
    very_fast_decay,
    DECAY_PROFILES,
    get_decay_fn,
    ConfidenceThresholds,
    is_confidence_sufficient,
)

# =============================================================================
# SPECIALIZED SIGNAL LOGIC
# =============================================================================

# Seasonality
from app.services.signals.seasonality import (
    SeasonalityResult,
    get_seasonality,
)

# Platform
from app.services.signals.platform import (
    PlatformDominanceResult,
    get_platform_bias,
    get_platform_weights,
)

# Amenity
from app.services.signals.amenity import (
    AmenityLiftResult,
    AmenityLiftDetail,
    get_amenity_lift,
    apply_amenity_lift,
)

# Operator
from app.services.signals.operator import (
    OperatorDeltaResult,
    get_operator_delta,
    apply_operator_delta,
)

__all__ = [
    # === Canonical (v2.0) ===
    "CanonicalSignalType", "CanonicalSignalSource", "ConfidenceLevel",
    "CanonicalSignal", "CanonicalSignalBundle",
    
    # === Pipeline ===
    "PipelineConfig", "SignalStore", "SignalProcessor", "SignalCache",
    "SignalPipeline", "SignalValidator", "PipelineMetrics",
    
    # === Coverage ===
    "CoverageScore", "CoverageScoreCalculator", "CoverageSlideGenerator",
    "SignalCategory", "calculate_coverage_score", "generate_bd_slide_content",
    
    # === Attribution ===
    "Attribution", "AttributionBundle", "AttributionGenerator",
    "ProFormaAttributionMixin", "SourceReliability",
    "generate_signal_footnotes", "generate_attribution_bundle",
    
    # === Scheduler ===
    "MarketConfig", "SchedulerConfig", "JobRunner", "SignalScheduler",
    "Job", "MARKETS",
    
    # === Dynamic Decay (v2.1) ===
    "DynamicDecayEngine", "MarketContextBuilder", "MarketContext",
    "DecayCalculation", "SeasonPhase", "DecayMarketRegime",
    "calculate_dynamic_decay", "get_decay_engine",
    
    # === Market Dynamics (v2.1) ===
    "PriceVelocityEngine", "CalendarDeltaEngine",
    "PriceVelocityResult", "CalendarDeltaResult",
    "PriceObservation", "CalendarObservation",
    "PriceDirection", "DemandDirection", "MomentumStrength",
    "calculate_price_velocity", "calculate_calendar_delta",
    
    # === Regime Detection (v2.1) ===
    "RegimeDetectionEngine", "CrossSignalConsistencyEngine",
    "RegimeResult", "ConsistencyResult",
    "MarketRegime", "SignalAgreement", "ConfidenceAdjustment",
    "detect_market_regime", "check_signal_consistency", "get_adjusted_confidence",
    
    # === Scarcity Amenity (v2.1) ===
    "ScarcityWeightedAmenityEngine", "ScarcityAdjustedLift",
    "AmenityScarcityAnalysis", "AmenityCategory",
    "calculate_scarcity_adjusted_lift", "analyze_market_amenity_scarcity",
    
    # === Legacy (v1.0) ===
    "SignalType", "SignalScope", "SignalSource", "Signal", "SignalBundle",
    "slow_decay", "very_slow_decay", "medium_decay", "fast_decay", "very_fast_decay",
    "DECAY_PROFILES", "get_decay_fn", "ConfidenceThresholds", "is_confidence_sufficient",
    
    # === Specialized ===
    "SeasonalityResult", "get_seasonality",
    "PlatformDominanceResult", "get_platform_bias", "get_platform_weights",
    "AmenityLiftResult", "AmenityLiftDetail", "get_amenity_lift", "apply_amenity_lift",
    "OperatorDeltaResult", "get_operator_delta", "apply_operator_delta",
]
