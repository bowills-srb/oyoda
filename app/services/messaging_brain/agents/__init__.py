"""
Specialist agents for the messaging brain.

Each agent implements either:
  - SpecialistAgent protocol (run-style agents like MaintenanceAgent)
  - Or a service-specific protocol (IntakeAgent.classify,
    ContextBuilderAgent.build, ResponsePolicyAgent.evaluate)

Phase 1.3a agents (all real, no stubs):
  - IntakeAgent           — wraps ConciergeRouter, two-axis intent typing
  - ContextBuilderAgent   — wraps ConciergeKnowledgeService, FAQ scan
  - MaintenanceAgent      — emits ModuleEvent for MaintenanceModule
  - ResponsePolicyAgent   — wraps autonomy_gate, type translations

Phase 2 agents:
  - HouseRulesAgent       — FAQ-grounded house-rules answers, biases
                            toward DRAFT_ONLY on pet/smoking edge cases
                            (Session 2)
  - AccessAgent           — wifi / check-in / check-out from
                            property_facts; door codes / parking /
                            pool / hot tub / grill via FAQ; flags
                            access_credential_answer on door-code
                            questions (Session 3)
  - EscalationAgent       — handles BOTH complaint and emergency
                            topics; emergency → ESCALATE with
                            escalation_emergency flag, complaint →
                            DRAFT_ONLY with escalation_complaint
                            flag; no FAQ grounding, no ModuleEvents
                            (Session 4)
  - BookingInquiryAgent   — availability / occupancy questions using
                            Session 5's pre-booking seam + canonical
                            booking-context lookup; always DRAFT_ONLY
                            (Session 6)

Ship L agents:
  - LateCheckoutAgent    — early check-in / late checkout requests,
                            always DRAFT_ONLY
  - GeneralAgent         — greetings / thanks / local-info fallback,
                            always DRAFT_ONLY

Phase 1.4+ / 2+ pending:
  - none for proactive routing in Ship N
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
from app.services.messaging_brain.agents.knowledge_gap_agent import (
    KnowledgeGapAgent,
)
from app.services.messaging_brain.agents.llm_intake_agent import (
    LLMIntakeAgent,
)
from app.services.messaging_brain.agents.maintenance_agent import MaintenanceAgent
from app.services.messaging_brain.agents.proactive_outreach_agent import (
    ProactiveOutreachAgent,
)
from app.services.messaging_brain.agents.response_policy_agent import (
    ResponsePolicyAgent,
)

__all__ = [
    "AgentRouter",
    "RouteOutcome",
    "DEFAULT_TOPIC_TO_AGENTS",
    "FALLBACK_AGENTS",
    "IntakeAgent",
    "KnowledgeGapAgent",
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
    "ProactiveOutreachAgent",
    "ResponsePolicyAgent",
]
