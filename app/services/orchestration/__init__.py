"""
Orchestration Layer.

Thin workflow orchestrators that:
- Load context (property, market, ops)
- Call executors
- Assemble response DTOs

Orchestrators do NOT:
- Contain business logic
- Make decisions
- Compute intelligence

Think of them as conductor baton strokes, not musicians.

Runners:
- IntelligenceOrchestrator: Signal processing workflows
- SignalScheduler: Signal refresh scheduling
- BDRunner: BD pitch and opportunity workflows
- OpportunityRunner: Opportunity scoring workflows
- ConciergeRunner: Guest interaction workflows
"""

from .intelligence_runner import (
    # Enums
    ExecutionMode,
    IntelligenceType,
    
    # Context & Result
    IntelligenceContext,
    IntelligenceResult,
    
    # Protocol
    SignalProvider,
    
    # Orchestrator
    IntelligenceOrchestrator,
    get_orchestrator,
    set_signal_provider,
)

from .signal_scheduler import (
    # Enums
    RefreshPolicy,
    JobPriority,
    
    # Models
    SignalFreshness,
    CollectionJob,
    
    # Default policies
    DEFAULT_REFRESH_POLICIES,
    get_refresh_interval,
    
    # Scheduler
    SignalScheduler,
    get_scheduler,
)

from .bd_runner import (
    BDRunner,
    PitchRequest,
    PitchResponse,
    OpportunityRequest as BDOpportunityRequest,
    OpportunityResponse as BDOpportunityResponse,
    LeadListRequest,
    LeadListResponse,
    get_bd_runner,
)

from .opportunity_runner import (
    OpportunityRunner,
    PropertyData,
    OwnerData,
    MarketData,
    ScoredOpportunity,
    BatchScoreRequest,
    BatchScoreResponse,
    get_opportunity_runner,
)

from .concierge_runner import (
    ConciergeRunner,
    ConciergeRequest,
    ConciergeReply,
    classify_intent,
    get_concierge_runner,
)
from .messaging_brain_contracts import (
    # Existing module/connection registry contracts (unchanged)
    MessagingBrainStage,
    MessagingBrainDomain,
    MessagingLifecycle,
    MessagingBrainContext,
    MessagingBrainResult,
    MessagingModuleContract,
    MessagingConnectionContract,
    MessagingBrainRegistry,
    build_pms_connection_contract,
    default_messaging_module_contracts,
    get_default_messaging_brain_registry,
    # NEW per-message runtime contracts (Phase 1)
    IntentType,
    RecommendedAction,
    Urgency,
    KNOWN_INTENT_TOPICS,
    InboundGuestMessage,
    OutboundIntent,
    MessageClassification,
    GuestContextBundle,
    AgentDecision,
    ModuleEvent,
    ModuleResponse,
    ResponsePolicyDecision,
    GuestResponseDraft,
    AgentAuditRecord,
)

# Re-export execution payloads for convenience
from app.services.execution import (
    PropertyPayload,
    MarketPayload,
    CompSetPayload,
    OperatorPayload,
    ProjectionPayload,
    PolicyEvaluationPayload,
)


__all__ = [
    # Intelligence Runner
    "ExecutionMode",
    "IntelligenceType",
    "IntelligenceContext",
    "IntelligenceResult",
    "SignalProvider",
    "IntelligenceOrchestrator",
    "get_orchestrator",
    "set_signal_provider",
    
    # Signal Scheduler
    "RefreshPolicy",
    "JobPriority",
    "SignalFreshness",
    "CollectionJob",
    "DEFAULT_REFRESH_POLICIES",
    "get_refresh_interval",
    "SignalScheduler",
    "get_scheduler",
    
    # BD Runner
    "BDRunner",
    "PitchRequest",
    "PitchResponse",
    "BDOpportunityRequest",
    "BDOpportunityResponse",
    "LeadListRequest",
    "LeadListResponse",
    "get_bd_runner",
    
    # Opportunity Runner
    "OpportunityRunner",
    "PropertyData",
    "OwnerData",
    "MarketData",
    "ScoredOpportunity",
    "BatchScoreRequest",
    "BatchScoreResponse",
    "get_opportunity_runner",
    
    # Concierge Runner
    "ConciergeRunner",
    "ConciergeRequest",
    "ConciergeReply",
    "classify_intent",
    "get_concierge_runner",

    # Messaging Brain — module/connection registry (existing)
    "MessagingBrainStage",
    "MessagingBrainDomain",
    "MessagingLifecycle",
    "MessagingBrainContext",
    "MessagingBrainResult",
    "MessagingModuleContract",
    "MessagingConnectionContract",
    "MessagingBrainRegistry",
    "build_pms_connection_contract",
    "default_messaging_module_contracts",
    "get_default_messaging_brain_registry",

    # Messaging Brain — per-message runtime contracts (Phase 1)
    "IntentType",
    "RecommendedAction",
    "Urgency",
    "KNOWN_INTENT_TOPICS",
    "InboundGuestMessage",
    "OutboundIntent",
    "MessageClassification",
    "GuestContextBundle",
    "AgentDecision",
    "ModuleEvent",
    "ModuleResponse",
    "ResponsePolicyDecision",
    "GuestResponseDraft",
    "AgentAuditRecord",

    # Execution payloads (re-exported)
    "PropertyPayload",
    "MarketPayload",
    "CompSetPayload",
    "OperatorPayload",
    "ProjectionPayload",
    "PolicyEvaluationPayload",
]
