"""
Execution Layer.

Thin wrappers around domain logic.
Translate DTOs → domain inputs → domain outputs.

Executors do NOT:
- Make decisions about what to run
- Handle retries/fallbacks
- Manage async concerns
- Access databases directly

Use orchestration layer for coordination.
Use execution layer for calling domain functions.

Executors:
- SignalExecutor: Signal computation
- GovernanceExecutor: Policy evaluation
- PricingExecutor: Pricing computations
- ForecastingExecutor: Projection generation
- OpportunityExecutor: BD opportunity scoring
- ConciergeExecutor: Guest interactions
- BDExecutor: Pitch books and summaries
- MarketExecutor: Market context management
"""

from .pricing_executor import (
    # Payloads
    AmenityUpliftPayload,
    AmenityUpliftResult,
    OperatorDeltaPayload,
    DiscountPayload,
    SensitivityPayload,
    
    # Results
    SensitivityResult,
    
    # Executor
    PricingExecutor,
    get_pricing_executor,
)

from .forecasting_executor import (
    # Payloads
    PropertyPayload,
    MarketPayload,
    CompSetPayload,
    OperatorPayload,
    ProjectionPayload,
    
    # Executor
    ForecastingExecutor,
    get_forecasting_executor,
)

from .signal_executor import (
    # Payloads
    SignalPayload,
    SignalBundlePayload,
    WeightedValueResult,
    ConfidenceCheckResult,
    
    # Executor
    SignalExecutor,
    get_signal_executor,
)

from .governance_executor import (
    # Payloads
    PolicyEvaluationPayload,
    PolicyEvaluationResult,
    PolicySummary,
    
    # Executor
    GovernanceExecutor,
    get_governance_executor,
)

from .opportunity_executor import (
    OpportunityExecutor,
    OpportunityPayload,
    OpportunityResult,
)

from .concierge_executor import (
    ConciergeExecutor,
    GuestMessagePayload,
    LateCheckoutPayload,
    ConciergeResponse,
)

from .bd_executor import (
    BDExecutor,
    PitchBookPayload,
    BDSummaryPayload,
)

from .market_executor import (
    MarketExecutor,
    MarketContextPayload,
    MarketEventPayload,
)


__all__ = [
    # Pricing
    "AmenityUpliftPayload",
    "AmenityUpliftResult",
    "OperatorDeltaPayload",
    "DiscountPayload",
    "SensitivityPayload",
    "SensitivityResult",
    "PricingExecutor",
    "get_pricing_executor",
    
    # Forecasting
    "PropertyPayload",
    "MarketPayload",
    "CompSetPayload",
    "OperatorPayload",
    "ProjectionPayload",
    "ForecastingExecutor",
    "get_forecasting_executor",
    
    # Signals
    "SignalPayload",
    "SignalBundlePayload",
    "WeightedValueResult",
    "ConfidenceCheckResult",
    "SignalExecutor",
    "get_signal_executor",
    
    # Governance
    "PolicyEvaluationPayload",
    "PolicyEvaluationResult",
    "PolicySummary",
    "GovernanceExecutor",
    "get_governance_executor",
    
    # Opportunity (BD)
    "OpportunityExecutor",
    "OpportunityPayload",
    "OpportunityResult",
    
    # Concierge
    "ConciergeExecutor",
    "GuestMessagePayload",
    "LateCheckoutPayload",
    "ConciergeResponse",
    
    # BD
    "BDExecutor",
    "PitchBookPayload",
    "BDSummaryPayload",
    
    # Market
    "MarketExecutor",
    "MarketContextPayload",
    "MarketEventPayload",
]
