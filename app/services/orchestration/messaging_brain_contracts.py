from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, Protocol, Sequence
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from app.services.connectors.pms_connectors import (
    PMSConnectorFactory,
    PMSConnectorContract,
    PMSProvider,
)
from app.services.messaging.identity_resolver import GuestIdentityResolution


class MessagingBrainStage(str, Enum):
    INTAKE = "intake"
    PARSE = "parse"
    ROUTE = "route"
    RETRIEVE = "retrieve"
    DRAFT = "draft"
    REVIEW = "review"
    ORCHESTRATE = "orchestrate"


class MessagingBrainDomain(str, Enum):
    MESSAGING = "messaging"
    PMS = "pms"
    MAINTENANCE = "maintenance"
    HOUSEKEEPING = "housekeeping"
    SCHEDULING = "scheduling"
    PRICING = "pricing"
    DOCUMENTS = "documents"
    PROPERTY_ASSETS = "property_assets"
    VENDOR_COORDINATION = "vendor_coordination"


class MessagingLifecycle(str, Enum):
    PRE_BOOKING = "pre_booking"
    PRE_ARRIVAL = "pre_arrival"
    IN_STAY = "in_stay"
    POST_STAY = "post_stay"
    OPS = "ops"
    SYSTEM = "system"


@dataclass(frozen=True)
class MessagingBrainContext:
    tenant_id: str
    source_channel: str
    source_provider: str
    lifecycle: MessagingLifecycle
    property_code: str = ""
    session_token: str = ""
    reservation_id: str = ""
    guest_email: str = ""
    guest_phone: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MessagingBrainResult:
    stage: MessagingBrainStage
    success: bool
    payload: Dict[str, Any] = field(default_factory=dict)
    requires_human_review: bool = False
    confidence: float = 1.0
    notes: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class MessagingModuleContract:
    module_key: str
    display_name: str
    domain: MessagingBrainDomain
    consumes_stages: Sequence[MessagingBrainStage]
    supports_lifecycles: Sequence[MessagingLifecycle]
    requires_property_binding: bool = False
    requires_session_context: bool = False
    produces: Sequence[str] = ()
    notes: str = ""


@dataclass(frozen=True)
class MessagingConnectionContract:
    connector_key: str
    display_name: str
    domain: MessagingBrainDomain
    auth_scheme: str
    message_transport: str
    readiness: str
    produces: Sequence[str]
    capabilities: Dict[str, bool] = field(default_factory=dict)
    notes: str = ""


class MessagingStageAgent(Protocol):
    stage: MessagingBrainStage

    async def run(
        self,
        context: MessagingBrainContext,
        payload: Dict[str, Any],
    ) -> MessagingBrainResult: ...


class MessagingModuleAgent(Protocol):
    contract: MessagingModuleContract

    async def handle(
        self,
        context: MessagingBrainContext,
        payload: Dict[str, Any],
    ) -> MessagingBrainResult: ...


class MessagingConnectionAgent(Protocol):
    contract: MessagingConnectionContract

    async def test_connection(
        self,
        tenant_id: str,
        credentials: Dict[str, Any],
    ) -> MessagingBrainResult: ...

    async def ingest(
        self,
        tenant_id: str,
        credentials: Dict[str, Any],
        *,
        scope: Dict[str, Any] | None = None,
    ) -> MessagingBrainResult: ...


def build_pms_connection_contract(provider: PMSProvider) -> MessagingConnectionContract:
    contract: PMSConnectorContract = PMSConnectorFactory.get_provider_contract(provider)
    produces: List[str] = [
        "provider_account_id",
        "provider_property_id",
        "provider_unit_id",
        "provider_listing_id",
        "listing_metadata",
        "booking_metadata",
    ]
    if contract.capabilities.documents:
        produces.append("documents")
    if contract.capabilities.reviews:
        produces.append("reviews")
    if contract.capabilities.operations:
        produces.append("operations")

    return MessagingConnectionContract(
        connector_key=contract.provider.value,
        display_name=contract.display_name,
        domain=MessagingBrainDomain.PMS,
        auth_scheme=contract.auth_scheme.value,
        message_transport=contract.message_transport.value,
        readiness=contract.readiness.value,
        produces=tuple(produces),
        capabilities=contract.capabilities.to_dict(),
        notes=contract.notes,
    )


def default_messaging_module_contracts() -> List[MessagingModuleContract]:
    return [
        MessagingModuleContract(
            module_key="messaging_core",
            display_name="Messaging Core",
            domain=MessagingBrainDomain.MESSAGING,
            consumes_stages=(
                MessagingBrainStage.INTAKE,
                MessagingBrainStage.PARSE,
                MessagingBrainStage.ROUTE,
                MessagingBrainStage.RETRIEVE,
                MessagingBrainStage.DRAFT,
                MessagingBrainStage.REVIEW,
                MessagingBrainStage.ORCHESTRATE,
            ),
            supports_lifecycles=tuple(MessagingLifecycle),
            produces=("draft_reply", "review_decision", "route_decision"),
            notes="Primary guest messaging brain for pre-booking and guest sessions.",
        ),
        MessagingModuleContract(
            module_key="maintenance",
            display_name="Maintenance Workflows",
            domain=MessagingBrainDomain.MAINTENANCE,
            consumes_stages=(MessagingBrainStage.ROUTE, MessagingBrainStage.ORCHESTRATE),
            supports_lifecycles=(
                MessagingLifecycle.IN_STAY,
                MessagingLifecycle.POST_STAY,
                MessagingLifecycle.OPS,
            ),
            requires_property_binding=True,
            requires_session_context=True,
            produces=("work_order_request", "vendor_handoff"),
            notes="Handles HVAC, appliance, pool, and repair-related operational tasks.",
        ),
        MessagingModuleContract(
            module_key="housekeeping",
            display_name="Housekeeping Workflows",
            domain=MessagingBrainDomain.HOUSEKEEPING,
            consumes_stages=(MessagingBrainStage.ROUTE, MessagingBrainStage.ORCHESTRATE),
            supports_lifecycles=(
                MessagingLifecycle.PRE_ARRIVAL,
                MessagingLifecycle.POST_STAY,
                MessagingLifecycle.OPS,
            ),
            requires_property_binding=True,
            produces=("turnover_task", "cleaning_followup"),
        ),
        MessagingModuleContract(
            module_key="scheduling",
            display_name="Scheduling Workflows",
            domain=MessagingBrainDomain.SCHEDULING,
            consumes_stages=(MessagingBrainStage.RETRIEVE, MessagingBrainStage.ORCHESTRATE),
            supports_lifecycles=tuple(MessagingLifecycle),
            produces=("calendar_hold", "appointment_request"),
        ),
        MessagingModuleContract(
            module_key="documents",
            display_name="Document Intelligence",
            domain=MessagingBrainDomain.DOCUMENTS,
            consumes_stages=(MessagingBrainStage.RETRIEVE,),
            supports_lifecycles=tuple(MessagingLifecycle),
            requires_property_binding=False,
            produces=("document_context", "agreement_terms", "warranty_context"),
        ),
    ]


class MessagingBrainRegistry:
    def __init__(self) -> None:
        self._module_contracts: Dict[str, MessagingModuleContract] = {}
        self._connection_contracts: Dict[str, MessagingConnectionContract] = {}

    def register_module_contract(self, contract: MessagingModuleContract) -> None:
        self._module_contracts[contract.module_key] = contract

    def register_connection_contract(self, contract: MessagingConnectionContract) -> None:
        self._connection_contracts[contract.connector_key] = contract

    def get_module_contract(self, module_key: str) -> MessagingModuleContract:
        return self._module_contracts[module_key]

    def get_connection_contract(self, connector_key: str) -> MessagingConnectionContract:
        return self._connection_contracts[connector_key]

    def list_module_contracts(
        self,
        *,
        domain: MessagingBrainDomain | None = None,
        lifecycle: MessagingLifecycle | None = None,
    ) -> List[MessagingModuleContract]:
        contracts = list(self._module_contracts.values())
        if domain is not None:
            contracts = [c for c in contracts if c.domain == domain]
        if lifecycle is not None:
            contracts = [c for c in contracts if lifecycle in c.supports_lifecycles]
        return contracts

    def list_connection_contracts(
        self,
        *,
        domain: MessagingBrainDomain | None = None,
        readiness: str | None = None,
    ) -> List[MessagingConnectionContract]:
        contracts = list(self._connection_contracts.values())
        if domain is not None:
            contracts = [c for c in contracts if c.domain == domain]
        if readiness is not None:
            contracts = [c for c in contracts if c.readiness == readiness]
        return contracts

    @classmethod
    def with_defaults(cls) -> "MessagingBrainRegistry":
        registry = cls()
        for contract in default_messaging_module_contracts():
            registry.register_module_contract(contract)
        for provider in PMSConnectorFactory.get_supported_providers(implemented_only=False):
            registry.register_connection_contract(build_pms_connection_contract(provider))
        return registry


def get_default_messaging_brain_registry() -> MessagingBrainRegistry:
    return MessagingBrainRegistry.with_defaults()


# =============================================================================
# PER-MESSAGE RUNTIME CONTRACTS (Phase 1 — added 2026-04-29)
#
# These Pydantic models are the typed contracts that flow through the
# GuestMessageBrainOrchestrator on every inbound message and proactive
# outbound trigger.
#
# Design notes:
#   * Channel-agnostic: SMS, email, voice, web chat, RCS, ABM all map to the
#     same shape via the existing CanonicalInboundMessage normalizer.
#   * Two-axis intent classification: (IntentType x intent_topic) so routing
#     can express "this is a maintenance problem" vs "this is a maintenance
#     question" without exploding the keyword sets.
#   * RecommendedAction is the ONLY normalized send-decision vocabulary.
#     {auto_send, draft_only, escalate}. Module work (create_task, schedule,
#     log_only) is expressed as ModuleEvent objects emitted alongside.
#   * AgentDecision.evidence_used must reference keys present in the
#     associated GuestContextBundle.evidence_keys — that's the audit
#     contract that lets us prove a decision was grounded.
#   * AgentAuditRecord is in-memory in Phase 1. Phase 5 adds a dedicated
#     agent_audit_logs table; for now we shadow-write the most important
#     fields into the existing message_normalizations row via
#     message_event_store.update_normalization_outcome().
#
# These contracts are ADDITIVE. Nothing above this line was changed.
# =============================================================================


class IntentType(str, Enum):
    """The shape of what the guest is doing.

    QUESTION  — guest wants information ("what's the wifi?", "where's the beach?")
    PROBLEM   — something is wrong ("the AC isn't working", "toilet is clogged")
    REQUEST   — guest wants an action ("can we check out late?", "extra towels?")
    SYSTEM_EVENT — non-guest-initiated trigger (booking confirmed, checkout time,
                  proactive welcome, etc.)
    """

    QUESTION = "question"
    PROBLEM = "problem"
    REQUEST = "request"
    SYSTEM_EVENT = "system_event"


# Topic strings are kept as free-form for extensibility. These are the
# canonical topics the orchestrator's AgentRouter knows how to route to.
# Adding a new specialist agent means adding a topic here AND wiring it
# in agent_router.py — that's deliberate.
KNOWN_INTENT_TOPICS: frozenset[str] = frozenset({
    "access",                  # door codes, parking, check-in, wifi password
    "maintenance",             # AC, plumbing, appliances, pests, cleanliness
    "house_rules",             # pets, smoking, quiet hours, occupancy
    "local_recommendation",    # restaurants, activities, kids, beach, events
    "late_checkout",           # late checkout, early check-in, extend stay
    "booking_inquiry",         # pre-booking availability, pricing, dates
    "complaint",               # angry guest, refund request, damage claim
    "emergency",               # safety, injury, fire, gas leak, locked out
    "general",                 # everything else — falls through to LLM general
    # System-event topics
    "system_welcome",          # proactive welcome on booking
    "system_pre_arrival",      # T-3 reminder
    "system_morning_brief",    # weather/event status on stay days
    "system_extend_stay",      # departure-day extend-stay offer
    "system_checkout_reminder",
    "system_post_stay",
})


class RecommendedAction(str, Enum):
    """Normalized send-decision vocabulary.

    AUTO_SEND   — ship the draft to the guest now
    CLARIFY     — ask the guest a follow-up question to unblock an answer
    DRAFT_ONLY  — hold for operator review (default for un-opted-in properties)
    ESCALATE    — hold AND notify operator/on-call (emergency, refund, etc.)

    Module work (creating tickets, scheduling, etc.) is NOT expressed here.
    That goes in ModuleEvent objects emitted by specialist agents.
    """

    AUTO_SEND = "auto_send"
    CLARIFY = "clarify"
    DRAFT_ONLY = "draft_only"
    ESCALATE = "escalate"


class Urgency(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    EMERGENCY = "emergency"


# -- Inbound -----------------------------------------------------------------


class InboundGuestMessage(BaseModel):
    """Channel-agnostic representation of one guest message entering the brain.

    Built by adapters that wrap each transport:
      * email_pipeline → CanonicalInboundMessage → InboundGuestMessage
      * sms webhook → InboundGuestMessage directly
      * voice transcript → InboundGuestMessage with channel='voice'
      * /concierge/message HTTP → InboundGuestMessage from request body

    The orchestrator only ever sees this shape, never raw transport payloads.
    """

    message_id: str = Field(..., description="Stable per-message ID. For HTTP, the request UUID; for email, message_id; for SMS, Twilio MessageSid.")
    tenant_id: str = Field(..., description="Operator UUID — required for autonomy gate, knowledge lookup, audit.")
    channel: str = Field(..., description="sms | email | voice | web_chat | rcs | apple_messages | http_api")
    source_provider: str = Field("", description="Sub-classifier within channel: gmail / microsoft / twilio / vrbo_email / airbnb_email / etc.")

    text: str = Field(..., min_length=1, description="The latest guest turn. NOT the full thread.")
    full_thread_text: str = Field("", description="Optional — full thread context if the channel provides one.")

    received_at: datetime = Field(default_factory=datetime.utcnow)

    # Identity binding (any combination may be present)
    guest_id: Optional[str] = None
    guest_email: str = ""
    guest_phone: str = ""
    guest_name: str = ""
    identity: Optional[GuestIdentityResolution] = None

    reservation_id: str = ""
    property_id: Optional[str] = None
    property_code: str = ""
    lifecycle: Optional[MessagingLifecycle] = None

    thread_id: str = ""           # email thread, SMS conversation, etc.
    session_token: str = ""       # concierge session token if guest is in-stay

    raw_subject: str = ""
    raw_payload_ref: str = ""     # pointer to raw payload in object store, if archived

    # Pre-extracted hints from the normalizer (optional; agents should not
    # depend on these — they're convenience for the IntakeAgent).
    structured_asks: List[str] = Field(default_factory=list)
    parser_used: str = ""
    parser_confidence: float = 0.0

    # Free-form metadata from the transport adapter.
    metadata: Dict[str, Any] = Field(default_factory=dict)


class OutboundIntent(BaseModel):
    """Non-guest-initiated trigger that enters the brain (proactive outreach).

    Examples: booking_confirmed, pre_arrival_reminder, morning_brief,
    extend_stay_offer, maintenance_eta_update.

    The orchestrator handles these through the same agent path so they
    get the same context, policy gate, and audit trail.
    """

    intent_id: str = Field(default_factory=lambda: str(uuid4()))
    tenant_id: str
    trigger_type: str = Field(..., description="system_welcome | system_pre_arrival | system_morning_brief | system_extend_stay | system_checkout_reminder | etc.")
    triggered_at: datetime = Field(default_factory=datetime.utcnow)

    guest_id: Optional[str] = None
    guest_email: str = ""
    guest_phone: str = ""
    guest_name: str = ""

    reservation_id: str = ""
    property_id: Optional[str] = None
    property_code: str = ""
    session_token: str = ""
    lifecycle: Optional[MessagingLifecycle] = None
    channel_preference: str = ""

    payload: Dict[str, Any] = Field(default_factory=dict, description="Trigger-specific data: weather, event, vendor ETA, etc.")


# -- Classification ----------------------------------------------------------


class MessageClassification(BaseModel):
    """The IntakeAgent's structured read of an InboundGuestMessage."""

    intent_type: IntentType
    intent_topic: str = Field(..., description="One of KNOWN_INTENT_TOPICS, or a new topic (warns at classify time).")
    secondary_topics: List[str] = Field(default_factory=list, description="Mixed-intent messages: 'late checkout AND seafood place' → primary=late_checkout, secondary=[local_recommendation].")
    sub_intents: List[str] = Field(
        default_factory=list,
        description=(
            "Advisory open-vocabulary signals for downstream composition. "
            "NOT used for routing. Examples: pricing, availability, amenities, "
            "portfolio_search, sleeping_arrangement, early_check_in, "
            "payment_coordination, road_access, local_services. May contain "
            "operator/market-specific signals not in any enum. Populated by "
            "LLMIntakeAgent (Session 9); empty when the keyword IntakeAgent ran."
        ),
    )
    extracted_constraints: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Loose-schema bag of structured facts extracted from the guest "
            "message — dates, party_size, budget, bedroom_count, community, "
            "pricing_concern, amenity_asks, sleeping_concern, other. Optional "
            "fields, omitted when not stated. Populated by LLMIntakeAgent "
            "(Session 9); empty when the keyword IntakeAgent ran."
        ),
    )

    confidence: float = Field(..., ge=0.0, le=1.0)
    urgency: Urgency = Urgency.MEDIUM

    # When True, even high-confidence drafts go to review.
    requires_human_review: bool = False

    # Free-form trace of HOW the classification was reached. The router
    # writes this for the audit log: matched keywords, EQ signals, etc.
    reason: str = ""
    matched_keyword: Optional[str] = None
    matched_route: Optional[str] = None  # e.g. existing ConciergeRouter.Route value


# -- Context -----------------------------------------------------------------


class GuestContextBundle(BaseModel):
    """Everything the specialist agents need to make a grounded decision.

    Built by ContextBuilderAgent from existing services
    (concierge/context_builder.py + knowledge_service + property_router + etc.).

    evidence_keys is the registry of what's loaded. Specialist agents
    reference these keys in AgentDecision.evidence_used to prove
    grounding — that's the audit contract.
    """

    tenant_id: str
    property_id: Optional[str] = None
    property_code: str = ""
    reservation_id: str = ""
    guest_id: Optional[str] = None

    lifecycle: MessagingLifecycle = MessagingLifecycle.PRE_BOOKING

    # Loaded context blobs. Empty dict means "we tried and there was nothing".
    # Missing key means "we did not look up this kind of context".
    property_facts: Dict[str, Any] = Field(default_factory=dict)
    property_knowledge: Dict[str, Any] = Field(default_factory=dict)  # FAQ + sections
    guidebook_knowledge: Dict[str, Any] = Field(default_factory=dict)
    # Full retained facts/sections/faq from the upstream knowledge service.
    # Source for guidebook richness scoring, evidence retrieval, and the
    # legacy-shape adapter (Session 11+). property_knowledge above remains
    # the trimmed/derived view consumed by other agents; this field is the
    # raw retained material. Empty dict means "no upstream knowledge
    # available".
    guidebook_richness: Dict[str, Any] = Field(default_factory=dict)
    # Output of assess_prebooking_knowledge_richness against guidebook_knowledge.
    # Shape: {"score": float, "label": str, "summary": str}. Empty dict means
    # rich context was off, db_session was None, or the helper failed. Label
    # values are "rich" | "medium" | "sparse" | "none"; consumers should not
    # distinguish between "label=none" and empty dict for routing decisions.
    guidebook_evidence: List[Dict[str, Any]] = Field(default_factory=list)
    # Output of retrieve_prebooking_property_evidence against the message text
    # and guidebook_knowledge. Shape: [{"source": str, "label": str, "text":
    # str, "score": int}, ...]. Empty list means no relevant hits, rich
    # context was off, the helper failed, or the message was empty (the
    # proactive path always produces an empty list since it has no guest
    # utterance to retrieve evidence for).
    learned_preferences_block: str = ""
    # Output of build_preference_context — a rendered string block of operator
    # preferences relevant to this intent and property. String-shaped because
    # the upstream helper currently only exposes a string contract; tracked
    # for future structured replacement (Session 11 follow-up).
    operator_policies: Dict[str, Any] = Field(default_factory=dict)
    # Structured operator policy block surfaced from CanonicalPropertyService.
    # Kept top-level so downstream agents can cite policy values directly
    # instead of reverse-engineering them from house_rules prose.
    operator_guidance: str = ""
    # Free-form operator-authored policy text from Settings → AI Guidance.
    # Shared with the legacy drafting path so both systems consume the same
    # human-authored House Rules / policy layer.
    reservation_facts: Dict[str, Any] = Field(default_factory=dict)
    house_rules: Dict[str, Any] = Field(default_factory=dict)
    access_info: Dict[str, Any] = Field(default_factory=dict)
    maintenance_status: Dict[str, Any] = Field(default_factory=dict)
    local_guidebook_facts: Dict[str, Any] = Field(default_factory=dict)
    market_signals: Dict[str, Any] = Field(default_factory=dict)
    prior_guest_messages: List[Dict[str, Any]] = Field(default_factory=list)
    operator_commitments: List[str] = Field(default_factory=list)

    # The keys that are populated above. Specialists' evidence_used must
    # be a subset of this set (the audit writer enforces this).
    evidence_keys: List[str] = Field(default_factory=list)

    # Things the context builder tried to load and could not. Useful for
    # downstream agents (e.g. "missing access_info → cannot auto-answer
    # door code question").
    missing_context: List[str] = Field(default_factory=list)


# -- Per-Agent Decisions -----------------------------------------------------


class AgentDecision(BaseModel):
    """One specialist's contribution to handling the message.

    A single message may produce multiple AgentDecisions (e.g. mixed
    "late checkout AND restaurant rec" → LateCheckoutAgent + LocalRecAgent).
    The orchestrator composes them into a single GuestResponseDraft.
    """

    agent_name: str
    intent_topic: str
    confidence: float = Field(..., ge=0.0, le=1.0)

    answer_summary: str = Field("", description="Short human-readable summary of what the agent decided. Goes into the audit log.")

    # MUST be a subset of GuestContextBundle.evidence_keys. The audit
    # writer asserts this — undocumented evidence is a red flag.
    evidence_used: List[str] = Field(default_factory=list)
    missing_info: List[str] = Field(default_factory=list)
    clarification_questions: List[str] = Field(default_factory=list)
    risk_flags: List[str] = Field(default_factory=list)

    # The agent's recommendation. The ResponsePolicyAgent has the final
    # say — an agent recommending AUTO_SEND can still be downgraded to
    # DRAFT_ONLY by a property in review mode.
    recommended_action: RecommendedAction = RecommendedAction.DRAFT_ONLY

    # If the agent dispatched module work (e.g. created a work order),
    # the events are listed here. The orchestrator collects them into
    # the audit log and may use them to enrich the guest response.
    module_events: List["ModuleEvent"] = Field(default_factory=list)
    module_responses: List["ModuleResponse"] = Field(default_factory=list)

    # Optional draft text fragment. The orchestrator composes the final
    # draft from one or more agents. Single-agent flows usually return
    # the full draft here.
    draft_text: str = ""


# -- Module Events -----------------------------------------------------------


class ModuleEvent(BaseModel):
    """Work the brain dispatches to a module (maintenance, housekeeping, etc.).

    A specialist agent emits a ModuleEvent when handling the message
    requires action outside the conversation: "create work order",
    "schedule housekeeper", "notify operator", "issue refund".
    """

    event_id: str = Field(default_factory=lambda: str(uuid4()))
    module: str = Field(..., description="Module key from MessagingBrainDomain (maintenance / housekeeping / scheduling / pricing / etc.)")
    event_type: str = Field(..., description="Module-specific: 'hvac_issue' / 'turnover_request' / 'schedule_check' / etc.")

    tenant_id: str
    property_id: Optional[str] = None
    reservation_id: str = ""
    guest_id: Optional[str] = None

    payload: Dict[str, Any] = Field(default_factory=dict)
    requested_at: datetime = Field(default_factory=datetime.utcnow)


class ModuleResponse(BaseModel):
    """A module's response to a ModuleEvent."""

    event_id: str
    module: str
    success: bool
    result: Dict[str, Any] = Field(default_factory=dict)
    evidence_used: List[str] = Field(default_factory=list)
    error: str = ""
    completed_at: datetime = Field(default_factory=datetime.utcnow)


# -- Policy Decision ---------------------------------------------------------


class ResponsePolicyDecision(BaseModel):
    """The ResponsePolicyAgent's final ruling on whether a draft ships.

    This is the brain-level mirror of autonomy_gate.GateResult. Mapping:
        AutonomyDecision.AUTO_SEND              → RecommendedAction.AUTO_SEND
        AutonomyDecision.REVIEW                 → RecommendedAction.DRAFT_ONLY
        AutonomyDecision.BLOCKED_BY_ESCALATION  → RecommendedAction.ESCALATE
    """

    final_action: RecommendedAction
    confidence: float = Field(..., ge=0.0, le=1.0)
    reasons: List[str] = Field(default_factory=list)

    # Captured at decision time for audit. Mirrors autonomy_gate's
    # approval_mode_at_decision so we can correlate.
    approval_mode_at_decision: str = "required"
    blocking_escalation_id: Optional[str] = None

    # If any specialist agent emitted module events, surface them here
    # so callers can fire them post-decision (or roll them back if the
    # final action becomes ESCALATE).
    module_events_to_dispatch: List[ModuleEvent] = Field(default_factory=list)


# -- Final Draft -------------------------------------------------------------


class GuestResponseDraft(BaseModel):
    """The composed reply, post-policy, ready to send or queue."""

    response_text: str
    tone: str = "professional_friendly"
    confidence: float = Field(..., ge=0.0, le=1.0)
    confidence_source: Optional[str] = None

    final_action: RecommendedAction
    auto_send_allowed: bool = False
    escalation_required: bool = False
    reason_for_escalation: str = ""

    # For audit / operator UI
    evidence_references: List[str] = Field(default_factory=list)
    contributing_agents: List[str] = Field(default_factory=list)


# -- Audit -------------------------------------------------------------------


class ClassifierMetadata(BaseModel):
    """How the classification was produced. Audit/observability only —
    not consumed by routing or specialists.

    Populated per-call by the orchestrator after IntakeAgent.classify()
    returns. The keyword IntakeAgent path produces a minimal metadata
    record (classifier_source='keyword_default'); the LLMIntakeAgent path
    populates the full provider/latency/token detail.

    Added in Session 9 — see docs/PHASE_2_SEAM_MAP.md.
    """

    classifier_source: str = Field(
        ...,
        description="'llm' | 'keyword_fallback' | 'keyword_default'",
    )
    provider_used: Optional[str] = Field(
        None,
        description="'anthropic' | 'groq' | None (when keyword path).",
    )
    fallback_stage: Optional[str] = Field(
        None,
        description="Which step the classifier ended on if there was failover.",
    )
    latency_ms: int = 0
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    coercion_notes: List[str] = Field(
        default_factory=list,
        description=(
            "Audit notes from coercion (llm_invalid_json, "
            "llm_topic_coerced:..., etc.). Queryable for debugging "
            "classifier quality issues."
        ),
    )
    threshold: Optional[float] = Field(
        None,
        description="Configured deterministic threshold when applicable.",
    )
    original_intent: Optional[str] = Field(
        None,
        description="Legacy/pre-filter intent prior to LLM escalation.",
    )
    original_confidence: Optional[float] = Field(
        None,
        description="Confidence from the deterministic pre-filter before escalation.",
    )
    escalated: bool = False
    contradictory_signals: bool = False
    escalation_provider: Optional[str] = None
    escalated_confidence: Optional[float] = None
    escalated_topic: Optional[str] = None
    legacy_intent: Optional[str] = Field(
        None,
        description="Legacy/pre-booking intent adapter for downstream parity checks.",
    )
    matched_terms: List[str] = Field(
        default_factory=list,
        description="Deterministic patterns that matched on the selected legacy intent.",
    )
    matched_override_keywords: List[str] = Field(
        default_factory=list,
        description=(
            "Approved tenant override keywords that matched on the selected intent. "
            "This is the evidence seam for per-override quality scoring."
        ),
    )
    resolved_via_override: bool = Field(
        False,
        description=(
            "True when the selected deterministic intent included at least one "
            "tenant-approved override keyword match."
        ),
    )
    deterministic_gate_decision: Optional[str] = Field(
        None,
        description=(
            "Audit decision for deterministic-first intake gating, such as "
            "'accepted', 'handoff_to_llm', or 'handoff_required_no_llm'."
        ),
    )
    deterministic_handoff_reason: Optional[str] = Field(
        None,
        description=(
            "Why deterministic handed off or would have handed off, e.g. "
            "'low_confidence', 'contradictory_signals', or a combined reason."
        ),
    )


class ComposerMetadata(BaseModel):
    """How the response text was composed. Audit/observability only —
    not consumed by orchestration logic.

    Populated per-call by the orchestrator after the LLM composer runs
    (or after the brain concatenation fallback runs in its place). The
    composer_response_text field is recorded even in shadow mode where
    the operator-facing draft came from the concatenation fallback —
    that's what makes side-by-side compare semantically real.

    When composer_metadata is None on an AgentAuditRecord, the composer
    did not run (composer flag off, or pipeline error before the compose
    step). When composer_metadata is populated with
    composer_source='fallback_*', the composer ran but did not use an
    LLM. Those two states are distinct and both meaningful — the None
    state lives only at the AgentAuditRecord.composer_metadata level,
    not scattered inside this object.

    Added in Session 12 — see docs/SESSION_12_COMPOSER_DESIGN.md.
    """

    composer_source: str = Field(
        ...,
        description=(
            "'llm_anthropic' | 'llm_groq' | 'llm_gemini' | "
            "'fallback_concatenation' | 'fallback_empty'. "
            "Distinct from AgentAuditRecord/draft_source — that field "
            "stays at coarse path granularity ('messaging_brain'); "
            "composer_source is the refined view of which composer or "
            "fallback produced the candidate output."
        ),
    )
    composer_response_text: str = Field(
        ...,
        description=(
            "The composer candidate output. Recorded even when shadow "
            "mode means the operator-facing draft comes from the brain "
            "concatenation fallback — this is the load-bearing field "
            "for shadow-mode compare."
        ),
    )
    composer_latency_ms: int = 0
    composer_input_tokens: Optional[int] = None
    composer_output_tokens: Optional[int] = None
    composer_notes: List[str] = Field(
        default_factory=list,
        description=(
            "Audit notes from composer execution: per-provider failure "
            "reasons, coercion notes, evidence-violation warnings."
        ),
    )
    clarification_chosen: bool = Field(
        False,
        description=(
            "Best-effort flag that the composer output is a clarifying "
            "reply rather than a substantive answer. Heuristic-based and "
            "used for audit/analysis only."
        ),
    )


class AgentAuditRecord(BaseModel):
    """In-memory audit trail for one orchestrator invocation.

    Phase 1: orchestrator builds this and shadow-writes the most important
    fields into message_normalizations via the existing message_event_store.

    Phase 5: a dedicated agent_audit_logs table will store this directly,
    one row per AgentDecision, with the schema you specified
    (input/output contract version, per-agent evidence, etc.).
    """

    record_id: str = Field(default_factory=lambda: str(uuid4()))
    message_id: str
    tenant_id: str
    channel: str
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None

    # The pipeline trace
    classification: Optional[MessageClassification] = None
    context_summary: Dict[str, Any] = Field(default_factory=dict)
    agent_path: List[str] = Field(default_factory=list)
    decisions: List[AgentDecision] = Field(default_factory=list)
    module_events: List[ModuleEvent] = Field(default_factory=list)
    module_responses: List[ModuleResponse] = Field(default_factory=list)
    policy: Optional[ResponsePolicyDecision] = None
    final_response: Optional[GuestResponseDraft] = None
    classifier_metadata: Optional[ClassifierMetadata] = Field(
        default=None,
        description=(
            "How the classification was produced (provider, latency, "
            "tokens, coercion trail). Added in Session 9. None on records "
            "created before this field landed."
        ),
    )
    composer_metadata: Optional[ComposerMetadata] = Field(
        default=None,
        description=(
            "How the response text was composed (provider, latency, "
            "tokens, candidate output, notes). Added in Session 12. "
            "None when the composer did not run (composer flag off, "
            "or pipeline error before the compose step). Populated "
            "with composer_source='fallback_*' when the composer ran "
            "but did not use an LLM. None on records created before "
            "this field landed."
        ),
    )

    # Free-form notes (errors, fallbacks, retry counts).
    notes: List[str] = Field(default_factory=list)


# Pydantic v2 needs explicit forward-ref resolution for self-referencing
# fields like AgentDecision.module_events.
AgentDecision.model_rebuild()


__all_per_message_contracts__ = [
    # Enums
    "IntentType",
    "RecommendedAction",
    "Urgency",
    "KNOWN_INTENT_TOPICS",
    # Inbound
    "InboundGuestMessage",
    "OutboundIntent",
    # Classification
    "MessageClassification",
    # Context
    "GuestContextBundle",
    # Per-agent
    "AgentDecision",
    "ModuleEvent",
    "ModuleResponse",
    # Policy & response
    "ResponsePolicyDecision",
    "GuestResponseDraft",
    # Audit
    "ClassifierMetadata",
    "ComposerMetadata",
    "AgentAuditRecord",
]
