"""
Messaging Brain — runtime decision plane for guest interactions.

Tier 3 of the messaging architecture (decision plane).

Responsibility: Decide what to do with already-normalized guest messages.
This package owns intent classification, fast-paths, specialist routing,
response composition, grounding, review, and lifecycle persistence.

What lives in OTHER tiers (do not duplicate here):
  - Inbound transport, parsers, LLM extractor:  app/services/integrations/
  - Identity, channel router, canonical contracts, alert routing platform:
        app/services/messaging/
  - Healers and other cross-cutting workers:    app/services/agents/

Dependency rule: messaging_brain/ may import from messaging/ (Tier 2) but
must NOT import from integrations/ (Tier 1) for behavior. Contract types
from integrations/ may be imported for type purposes only.

See docs/architecture/MESSAGING_TIER_MAP.md for the full tier map and the
decision tree for where new code belongs.

Public surface:
  GuestMessageBrainOrchestrator — single entry point for inbound + proactive
  AgentRouter — topic→specialist dispatch
  ModuleRegistry — work-handler lookup by module key

Pipeline (inbound, see orchestrator.py for full details):
  InboundGuestMessage
    → audit.persist_inbound() → internal UUID
    → IntakeAgent.classify()
    → FastPathStage (escalation / gate code / FAQ short-circuit)
    → ContextBuilderAgent.build()  (lazy, gated by intent keywords)
    → AgentRouter.route()  (identity-eligibility gated)
    → SpecialistAgent[s].run()  (emit ModuleEvents)
    → ResponsePolicyAgent.evaluate(triggered_by_message_id=…)
    → compose_response() → GuestResponseDraft
    → if not ESCALATE: dispatch ModuleEvents to modules
    → audit.write() → message_normalizations row updated
"""

from app.services.messaging_brain.agents.agent_router import (
    DEFAULT_TOPIC_TO_AGENTS,
    FALLBACK_AGENTS,
    AgentRouter,
    RouteOutcome,
)
from app.services.messaging_brain.agents.access_agent import (
    AccessAgent,
)
from app.services.messaging_brain.agents.booking_inquiry_agent import (
    BookingInquiryAgent,
)
from app.services.messaging_brain.agents.context_builder_agent import (
    ContextBuilderAgent,
)
from app.services.messaging_brain.agents.deterministic_intake_prefilter import (
    DeterministicIntakePreFilter,
)
from app.services.messaging_brain.agents.escalation_agent import (
    EscalationAgent,
)
from app.services.messaging_brain.agents.general_agent import (
    GeneralAgent,
)
from app.services.messaging_brain.agents.house_rules_agent import (
    HouseRulesAgent,
)
from app.services.messaging_brain.agents.intake_agent import IntakeAgent
from app.services.messaging_brain.agents.late_checkout_agent import (
    LateCheckoutAgent,
)
from app.services.messaging_brain.agents.llm_intake_agent import (
    LLMIntakeAgent,
)
from app.services.messaging_brain.agents.maintenance_agent import MaintenanceAgent
from app.services.messaging_brain.agents.portfolio_matching_agent import (
    PortfolioMatchingAgent,
)
from app.services.messaging_brain.agents.proactive_outreach_agent import (
    ProactiveOutreachAgent,
)
from app.services.messaging_brain.agents.response_policy_agent import (
    ResponsePolicyAgent,
)
from app.services.messaging_brain.audit import MessageEventStoreAuditWriter
from app.services.messaging_brain.modules.base import (
    BaseOyvodaModule,
    ModuleRegistry,
)
from app.services.messaging_brain.modules.maintenance_module import (
    MaintenanceModule,
)
from app.services.messaging_brain.orchestrator import (
    GuestMessageBrainOrchestrator,
    SpecialistAgent,
    get_messaging_brain_orchestrator,
)
from app.services.messaging_brain.pre_booking import (
    ContextAdapter,
    EmailTransportAdapter,
    EscapiaContextAdapter,
    EscapiaContextPayload,
    PreBookingBrainOrchestrator,
    PreBookingContextEnvelope,
    PreBookingDraftResult,
    PreBookingInquiry,
    PreBookingProviderBinding,
    TransportAdapter,
)

__all__ = [
    # Orchestrator
    "GuestMessageBrainOrchestrator",
    "get_messaging_brain_orchestrator",
    "SpecialistAgent",
    "PreBookingBrainOrchestrator",
    "PreBookingInquiry",
    "PreBookingDraftResult",
    "PreBookingContextEnvelope",
    "PreBookingProviderBinding",
    "TransportAdapter",
    "ContextAdapter",
    "EmailTransportAdapter",
    "EscapiaContextAdapter",
    "EscapiaContextPayload",
    # Router
    "AgentRouter",
    "RouteOutcome",
    "DEFAULT_TOPIC_TO_AGENTS",
    "FALLBACK_AGENTS",
    # Agents
    "IntakeAgent",
    "LLMIntakeAgent",
    "DeterministicIntakePreFilter",
    "ContextBuilderAgent",
    "AccessAgent",
    "BookingInquiryAgent",
    "EscalationAgent",
    "GeneralAgent",
    "HouseRulesAgent",
    "LateCheckoutAgent",
    "MaintenanceAgent",
    "PortfolioMatchingAgent",
    "ProactiveOutreachAgent",
    "ResponsePolicyAgent",
    # Modules
    "BaseOyvodaModule",
    "ModuleRegistry",
    "MaintenanceModule",
    # Audit
    "MessageEventStoreAuditWriter",
]
