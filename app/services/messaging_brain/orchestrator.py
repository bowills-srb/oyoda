"""
orchestrator.py — GuestMessageBrainOrchestrator.

The single conductor for every guest message and every proactive trigger.
Owns the pipeline shape; specialist agents and policy gate own the
decisions; modules own the work; existing services do the actual writes.

Pipeline (inbound) — see docs/PHASE_1_3_SEAM_MAP.md "Rule 1":

    InboundGuestMessage
      0. audit.persist_inbound()             → internal messages.message_id UUID
      1. IntakeAgent.classify()              → MessageClassification
      2. ContextBuilderAgent.build()         → GuestContextBundle
      3. AgentRouter.route()                 → list[agent_name]
      4. specialists run                     → AgentDecision[] (+ ModuleEvent[])
      5. ResponsePolicyAgent.evaluate()      → ResponsePolicyDecision
                                                (escalation enforced here
                                                via _detect_escalation risk
                                                flags; no escalation table)
      5.5. emit KB gaps from decisions       → canonical knowledge-gap recorder
                                                (fire-and-forget; brain-side
                                                entry into the canonical
                                                learning loop)
      6. compose_response()                  → GuestResponseDraft
                                                + optional ComposerMetadata on
                                                the audit record (Session 12).
      7. (if policy != ESCALATE)
         dispatch ModuleEvents to modules    → ModuleResponse[]
      8. audit.write(record, original_message=…)
                                             → message_normalizations row
                                                gets route_outcome + draft_source
                                                (+ composer fields when present)

Step 0 persists the inbound message and returns its internal UUID. It
no longer feeds policy (the autonomy_gate escalation-row lookup was
removed); escalation is enforced in ResponsePolicyAgent via risk flags.
Step 0 still runs first so the inbound message is durably recorded
before the pipeline can fail.

Step 5.5 emits a KB gap for each specialist whose decision both reported
non-empty missing_info AND did not recommend AUTO_SEND. The AUTO_SEND
guard keeps the signal aligned with the legacy path's "we couldn't
answer cleanly" semantics — advisory missing-info notes from confident
specialists are not gaps. Stub-specialist sentinel ('__stub_specialist__')
is filtered. Failure is logged at WARNING but never aborts the pipeline.
KB gap emission is intentionally inbound-only; proactive triggers do not
have "guest needed this fact" semantics.

Step 6 (Session 12 — see docs/SESSION_12_COMPOSER_DESIGN.md):
  - The brain concatenation fallback (Phase 1.3a's _compose_response) is
    ALWAYS computed first. It anchors the "we never regress below today"
    invariant.
  - If MESSAGING_BRAIN_LLM_COMPOSER is on for this tenant/property, the
    LLM composer ALSO runs. Its full result lands on
    record.composer_metadata regardless of which text reaches the
    operator.
  - If MESSAGING_BRAIN_LLM_COMPOSER_SHADOW is also on, the operator-
    facing draft stays as the brain concatenation fallback (compare
    mode). composer_metadata still records the LLM's text, which is
    the load-bearing signal for shadow validation.
  - If MESSAGING_BRAIN_LLM_COMPOSER is on and shadow is off, the
    composer's text replaces response_text on the operator-facing
    draft.
  - Both flag lookups fail-closed: composer-flag error → composer
    skipped; shadow-flag error → shadow=True (concatenation stays
    operator-facing). When in doubt, today's behavior wins.
  - Composer integration crash → record.composer_metadata gets a
    synthetic ComposerMetadata with composer_source='fallback_concatenation'
    and composer_notes containing 'composer_orchestrator_error:<ExcType>',
    so the audit row distinguishes "composer didn't run" (None) from
    "composer was attempted but broke" (synthetic fallback metadata).
  - Composer is intentionally inbound-only for now. handle_proactive_trigger
    does not invoke it; proactive composition stays on concatenation.

Step 7 is gated on policy approval. ESCALATE → no module dispatch (the
operator handles the issue out-of-band; the brain doesn't double-write
work orders for things being escalated). See seam-map Rule 5 — shadow
mode also lives here, suppressing module side effects only.

Pipeline (proactive) — Phase 2 build-out:
    OutboundIntent
      → ContextBuilderAgent.build_for_proactive()
      → ProactiveOutreachAgent.run()
      → ResponsePolicyAgent.evaluate()
      → compose_response()    (concatenation only — composer is inbound-only)
      → audit.write()

Audit:
  AgentAuditRecord captures the full pipeline trace (classification,
  decisions, module events, module responses, policy, final response,
  notes, composer_metadata). Phase 1.3a logs at INFO and shadow-writes
  key fields to message_normalizations via the existing
  message_event_store. Phase 5 adds a dedicated agent_audit_logs table
  without changing this contract.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable
from uuid import UUID

from app.services.observability.slo_metrics import observe_composer_outcome
from app.services.messaging_brain.knowledge.gap_recorder import schedule_gap_record
from app.services.messaging_brain.intake.intent_escalator import (
    load_prebooking_escalation_threshold,
    load_brain_router_threshold,
)
from app.services.messaging_brain.stages.fast_path_stage import FastPathStage
from app.services.messaging_brain.agents.agent_router import (
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
    legacy_intent_from_classification,
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
from app.services.messaging_brain.agents.knowledge_gap_agent import (
    KnowledgeGapAgent,
)
from app.services.messaging_brain.agents.late_checkout_agent import (
    LateCheckoutAgent,
)
from app.services.messaging_brain.agents.llm_composer_agent import (
    LLMComposerAgent,
)
from app.services.messaging_brain.agents.llm_intake_agent import (
    LLMIntakeAgent,
)
from app.services.messaging_brain.agents.maintenance_agent import (
    MaintenanceAgent,
)
from app.services.messaging_brain.agents.portfolio_matching_agent import (
    PortfolioMatchingAgent,
)
from app.services.messaging_brain.agents.proactive_outreach_agent import (
    ProactiveOutreachAgent,
)
from app.services.messaging_brain.agents.response_policy_agent import (
    ResponsePolicyAgent,
)
from app.services.feature_flags import (
    is_brain_composer_preferences_enabled,
    is_brain_intake_primary_enabled,
    is_messaging_brain_fast_path_stage_enabled,
    is_messaging_brain_llm_composer_enabled,
    is_messaging_brain_llm_composer_shadow_enabled,
    is_messaging_brain_llm_intake_enabled,
)
from app.services.messaging_brain.audit import MessageEventStoreAuditWriter
from app.services.messaging_brain.modules.base import ModuleRegistry
from app.services.messaging_brain.modules.maintenance_module import (
    MaintenanceModule,
)
from app.services.orchestration.messaging_brain_contracts import (
    AgentAuditRecord,
    AgentDecision,
    ClassifierMetadata,
    ComposerMetadata,
    GuestContextBundle,
    GuestResponseDraft,
    InboundGuestMessage,
    IntentType,
    MessageClassification,
    MessagingLifecycle,
    ModuleEvent,
    ModuleResponse,
    OutboundIntent,
    RecommendedAction,
    ResponsePolicyDecision,
    Urgency,
)

logger = logging.getLogger(__name__)


# Sentinel injected by _StubSpecialistAgent to mark unbuilt-specialist
# fallbacks. Filtered out of KB gap emission so stubs don't pollute the
# gap table.
_STUB_SPECIALIST_SENTINEL = "__stub_specialist__"


# ─────────────────────────────────────────────────────────────────────────────
# Specialist Agent protocol
# ─────────────────────────────────────────────────────────────────────────────


@runtime_checkable
class SpecialistAgent(Protocol):
    """Protocol every routed specialist must satisfy."""

    name: str
    handles_topics: tuple[str, ...]

    def eligible_for_identity(self, identity_state: str) -> bool:
        ...

    async def run(
        self,
        *,
        message: InboundGuestMessage,
        classification: MessageClassification,
        context: GuestContextBundle,
        db_session: Any = None,
    ) -> AgentDecision:
        ...


# ─────────────────────────────────────────────────────────────────────────────
# Stub specialist for unregistered routes
#
# Topics whose agents haven't been built yet (everything except
# MaintenanceAgent, HouseRulesAgent, AccessAgent, EscalationAgent,
# BookingInquiryAgent, LateCheckoutAgent, and GeneralAgent today) fall
# back to this catch-all so the pipeline can still complete with a
# draft_only response. Subsequent sessions replace any remaining stubs
# as additional agents land (for example ProactiveOutreachAgent).
# ─────────────────────────────────────────────────────────────────────────────


class _StubSpecialistAgent:
    """Catch-all for unregistered routes. Returns a polite draft_only."""

    def __init__(self, name: str, topic: str) -> None:
        self.name = name
        self.handles_topics = (topic,)
        self._topic = topic

    def eligible_for_identity(self, identity_state: str) -> bool:
        return True

    async def run(
        self,
        *,
        message: InboundGuestMessage,
        classification: MessageClassification,
        context: GuestContextBundle,
        db_session: Any = None,
    ) -> AgentDecision:
        return AgentDecision(
            agent_name=self.name,
            intent_topic=self._topic,
            confidence=0.10,
            answer_summary=(
                f"stub {self.name} — real implementation pending. "
                f"Topic={self._topic} classified at conf={classification.confidence:.2f}."
            ),
            evidence_used=[],
            missing_info=[_STUB_SPECIALIST_SENTINEL],
            recommended_action=RecommendedAction.DRAFT_ONLY,
            draft_text=(
                "Thanks for reaching out — a teammate will review this and "
                "follow up shortly."
            ),
        )


# ─────────────────────────────────────────────────────────────────────────────
# Orchestrator
# ─────────────────────────────────────────────────────────────────────────────


class GuestMessageBrainOrchestrator:
    """Single entry point for every guest message and proactive trigger.

    Default construction wires real agents (IntakeAgent, ContextBuilderAgent,
    MaintenanceAgent, HouseRulesAgent, AccessAgent, BookingInquiryAgent,
    EscalationAgent,
    ResponsePolicyAgent), the LLM composer (Session 12), plus the real
    audit writer (MessageEventStoreAuditWriter) and registers
    MaintenanceModule.

    Tests can inject mocks for any component via the constructor kwargs.

    Usage:
        orch = GuestMessageBrainOrchestrator()
        # MaintenanceAgent, HouseRulesAgent, AccessAgent,
        # BookingInquiryAgent, and EscalationAgent are already
        # registered by default. Add
        # more as they're built:
        # orch.register_specialist(LateCheckoutAgent())

        draft = await orch.handle_inbound_message(
            message=inbound, db_session=db,
        )

        # Or with shadow mode:
        draft = await orch.handle_inbound_message(
            message=inbound, db_session=db, shadow_mode=True,
        )

    Shadow mode contract (seam-map Rule 5): when shadow_mode=True, modules
    skip side-effecting writes (work order creation, vendor notification,
    etc.) but the pipeline still runs end-to-end and the audit row is
    still written. This is how operators validate the brain works before
    flipping the live switch.

    The Session 12 composer-shadow flag
    (MESSAGING_BRAIN_LLM_COMPOSER_SHADOW) is a SEPARATE concern from the
    module-shadow above. Composer-shadow controls whether the composer's
    candidate output reaches the operator-facing draft. Module-shadow
    controls module side-effect suppression. The two flags do not
    interact.
    """

    def __init__(
        self,
        *,
        router: Optional[AgentRouter] = None,
        intake: Optional[Any] = None,
        context_builder: Optional[Any] = None,
        policy: Optional[Any] = None,
        audit_writer: Optional[Any] = None,
        module_registry: Optional[ModuleRegistry] = None,
        composer: Optional[LLMComposerAgent] = None,
        fast_path_stage: Optional[FastPathStage] = None,
        knowledge_gap_agent: Optional[KnowledgeGapAgent] = None,
        shadow_mode: bool = False,
    ) -> None:
        self._router = router or AgentRouter()
        self._intake_injected = intake is not None
        self._intake_keyword = intake or IntakeAgent()
        self._intake_prefilter = DeterministicIntakePreFilter()
        self._intake_llm = (
            None
            if self._intake_injected
            else LLMIntakeAgent(keyword_fallback=self._intake_keyword)
        )
        self._intake_llm_prefilter = (
            None
            if self._intake_injected
            else LLMIntakeAgent(keyword_fallback=self._intake_prefilter)
        )
        self._context_builder = context_builder or ContextBuilderAgent()
        self._policy = policy or ResponsePolicyAgent()
        self._audit = audit_writer or MessageEventStoreAuditWriter()
        self._modules = module_registry or self._default_module_registry()
        self._fast_path_stage = fast_path_stage or FastPathStage()
        # Eager composer construction — mirrors _intake_llm. Composer is
        # stateless across calls; one instance per orchestrator is fine.
        # The composer makes no API calls at construction time.
        self._composer = composer or LLMComposerAgent()
        # Answerability gate — runs at step 5.6 to collect missing_topic_ids
        # so the LLM composer can hedge targeted gaps (hold-mode).
        self._knowledge_gap_agent = knowledge_gap_agent or KnowledgeGapAgent()
        self._specialists: Dict[str, SpecialistAgent] = {}
        self._shadow_mode = shadow_mode

        # Register default specialists. MaintenanceAgent (Phase 1.3a),
        # HouseRulesAgent (Phase 2 Session 2), AccessAgent (Phase 2
        # Session 3), EscalationAgent (Phase 2 Session 4), BookingInquiryAgent
        # (Phase 2 Session 6), LateCheckoutAgent and GeneralAgent
        # (Ship L) are wired by default. Any remaining topics fall
        # through to _StubSpecialistAgent until their real agents land.
        # Tests can override by registering different agents under the
        # same names.
        self.register_specialist(MaintenanceAgent())
        self.register_specialist(HouseRulesAgent())
        self.register_specialist(AccessAgent())
        self.register_specialist(BookingInquiryAgent())
        self.register_specialist(PortfolioMatchingAgent())
        self.register_specialist(EscalationAgent())
        self.register_specialist(LateCheckoutAgent())
        self.register_specialist(GeneralAgent())
        self.register_specialist(ProactiveOutreachAgent())

    @staticmethod
    def _default_module_registry() -> ModuleRegistry:
        """Build the default registry with all Phase 1.3a modules."""
        registry = ModuleRegistry()
        registry.register("maintenance", MaintenanceModule())
        return registry

    # ── Specialist registration ─────────────────────────────────────────────

    def register_specialist(self, agent: SpecialistAgent) -> None:
        """Register a specialist agent under its .name.

        Raises if the agent doesn't structurally match SpecialistAgent.
        Re-registering an existing name replaces the previous agent
        (logged at WARNING). Useful for tests.
        """
        if not isinstance(agent, SpecialistAgent):
            raise TypeError(
                f"agent {agent!r} does not satisfy the SpecialistAgent protocol "
                f"(needs .name, .handles_topics, async .run)"
            )
        if agent.name in self._specialists:
            logger.warning(
                "[MessagingBrain] re-registering specialist %s",
                agent.name,
            )
        new_topics = set(agent.handles_topics)
        for existing_name, existing in self._specialists.items():
            if existing_name == agent.name:
                continue
            overlap = new_topics & set(existing.handles_topics)
            if overlap:
                raise RuntimeError(
                    f"Specialist {agent.name!r} claims topics {sorted(overlap)} "
                    f"already owned by {existing_name!r}. One topic → one agent."
                )
        self._specialists[agent.name] = agent
        logger.info(
            "[MessagingBrain] registered specialist %s for topics %s",
            agent.name, agent.handles_topics,
        )

    def _resolve_specialist(self, name: str, topic: str) -> SpecialistAgent:
        agent = self._specialists.get(name)
        if agent is not None:
            return agent
        logger.info(
            "[MessagingBrain] no specialist registered for %s (topic=%s); using stub",
            name, topic,
        )
        return _StubSpecialistAgent(name=name, topic=topic)

    async def _select_intake(
        self,
        message: InboundGuestMessage,
        *,
        db_session: Any,
    ) -> Any:
        if self._intake_injected or self._intake_llm is None:
            return self._intake_keyword
        try:
            use_llm = await is_messaging_brain_llm_intake_enabled(
                db=db_session,
                tenant_id=message.tenant_id,
                property_code=message.property_code or None,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[MessagingBrain] LLM intake flag lookup failed; using keyword: %s",
                exc,
            )
            return self._intake_keyword
        return self._intake_llm if use_llm else self._intake_keyword

    async def _classify_inbound(
        self,
        intake: Any,
        message: InboundGuestMessage,
        *,
        db_session: Any,
    ) -> tuple[MessageClassification, ClassifierMetadata]:
        if hasattr(intake, "classify_with_metadata"):
            classification, metadata = await intake.classify_with_metadata(
                message,
                db_session=db_session,
            )
            return classification, metadata

        classification = await intake.classify(message, db_session=db_session)
        metadata = ClassifierMetadata(
            classifier_source="keyword_default",
            provider_used=None,
            latency_ms=0,
        )
        return classification, metadata

    async def classify_message(
        self,
        message: InboundGuestMessage,
        *,
        db_session: Any,
        force_brain_intake_primary: bool = False,
    ) -> tuple[MessageClassification, ClassifierMetadata]:
        if not self._intake_injected and (
            force_brain_intake_primary
            or await self._is_brain_intake_primary_enabled(
                message,
                db_session=db_session,
            )
        ):
            return await self._classify_with_prefilter_gate(
                message,
                db_session=db_session,
            )

        intake = await self._select_intake(message, db_session=db_session)
        return await self._classify_inbound(
            intake,
            message,
            db_session=db_session,
        )

    async def _is_brain_intake_primary_enabled(
        self,
        message: InboundGuestMessage,
        *,
        db_session: Any,
    ) -> bool:
        try:
            return await is_brain_intake_primary_enabled(
                db=db_session,
                tenant_id=message.tenant_id,
                property_code=message.property_code or None,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[MessagingBrain] brain intake primary flag lookup failed; using legacy intake: %s",
                exc,
            )
            return False

    async def _classify_with_prefilter_gate(
        self,
        message: InboundGuestMessage,
        *,
        db_session: Any,
    ) -> tuple[MessageClassification, ClassifierMetadata]:
        if self._intake_llm_prefilter is not None:
            llm_classification, llm_metadata = await self._intake_llm_prefilter.classify_with_metadata(
                message,
                db_session=db_session,
            )
            final_legacy_intent = legacy_intent_from_classification(
                llm_classification,
                message_text=message.text or "",
            )
            if llm_metadata.classifier_source != "keyword_fallback":
                metadata = llm_metadata.model_copy(
                    update={
                        "classifier_source": "llm_primary",
                        "escalated": False,
                        "legacy_intent": final_legacy_intent,
                        "escalated_topic": None,
                        "original_intent": None,
                        "original_confidence": None,
                        "contradictory_signals": False,
                        "escalation_provider": llm_metadata.provider_used,
                        "escalated_confidence": None,
                        "deterministic_gate_decision": "bypassed_llm_primary",
                        "deterministic_handoff_reason": None,
                    }
                )
                return llm_classification, metadata

        deterministic, deterministic_meta = await self._intake_prefilter.classify_with_metadata(
            message,
            db_session=db_session,
        )
        threshold = (
            deterministic_meta.threshold
            if deterministic_meta.threshold is not None
            else await load_prebooking_escalation_threshold(
                tenant_id=UUID(message.tenant_id),
                db=db_session,
            )
        )
        handoff_reason = self._deterministic_handoff_reason(
            confidence=deterministic.confidence,
            threshold=threshold,
            contradictory_signals=bool(deterministic_meta.contradictory_signals),
        )
        if (
            deterministic.confidence >= threshold
            and not deterministic_meta.contradictory_signals
        ):
            return deterministic, deterministic_meta.model_copy(
                update={
                    "deterministic_gate_decision": "accepted",
                    "deterministic_handoff_reason": None,
                }
            )

        if self._intake_llm_prefilter is None:
            return deterministic, deterministic_meta.model_copy(
                update={
                    "deterministic_gate_decision": "handoff_required_no_llm",
                    "deterministic_handoff_reason": handoff_reason,
                }
            )

        llm_classification, llm_metadata = await self._intake_llm_prefilter.classify_with_metadata(
            message,
            db_session=db_session,
        )
        final_legacy_intent = legacy_intent_from_classification(
            llm_classification,
            message_text=message.text or "",
        )
        if llm_metadata.classifier_source == "keyword_fallback":
            metadata = deterministic_meta.model_copy(
                update={
                    "classifier_source": "llm_failed_keyword_default",
                    "fallback_stage": "keyword_after_llm_chain",
                    "escalated": True,
                    "escalation_provider": None,
                    "escalated_confidence": None,
                    "escalated_topic": None,
                    "deterministic_gate_decision": "handoff_to_llm",
                    "deterministic_handoff_reason": handoff_reason,
                }
            )
            return deterministic, metadata

        metadata = llm_metadata.model_copy(
            update={
                "classifier_source": "llm_escalated",
                "threshold": threshold,
                "original_intent": deterministic_meta.original_intent,
                "original_confidence": deterministic_meta.original_confidence,
                "escalated": True,
                "contradictory_signals": deterministic_meta.contradictory_signals,
                "escalation_provider": llm_metadata.provider_used,
                "escalated_confidence": llm_classification.confidence,
                "escalated_topic": final_legacy_intent,
                "legacy_intent": final_legacy_intent,
                "deterministic_gate_decision": "handoff_to_llm",
                "deterministic_handoff_reason": handoff_reason,
            }
        )
        return llm_classification, metadata

    @staticmethod
    def _deterministic_handoff_reason(
        *,
        confidence: float,
        threshold: float,
        contradictory_signals: bool,
    ) -> str:
        reasons: list[str] = []
        if confidence < threshold:
            reasons.append("low_confidence")
        if contradictory_signals:
            reasons.append("contradictory_signals")
        return "+".join(reasons) or "deterministic_policy_handoff"

    async def _is_fast_path_stage_enabled(
        self,
        message: InboundGuestMessage,
        *,
        db_session: Any,
    ) -> bool:
        try:
            return await is_messaging_brain_fast_path_stage_enabled(
                db=db_session,
                tenant_id=message.tenant_id,
                property_code=message.property_code or None,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[MessagingBrain] fast-path flag lookup failed; continuing without fast-path: %s",
                exc,
            )
            return False

    # ── Inbound entry ───────────────────────────────────────────────────────

    async def handle_inbound_message(
        self,
        message: InboundGuestMessage,
        *,
        db_session: Any,
        shadow_mode: Optional[bool] = None,
    ) -> GuestResponseDraft:
        """Run an inbound guest message through the brain.

        The shadow_mode override takes precedence over the orchestrator's
        instance setting. Modules respect shadow_mode and skip side
        effects when true; the audit record is always written.
        """
        effective_shadow = (
            self._shadow_mode if shadow_mode is None else shadow_mode
        )

        record = AgentAuditRecord(
            message_id=message.message_id,
            tenant_id=message.tenant_id,
            channel=message.channel,
        )
        if effective_shadow:
            record.notes.append("shadow_mode=true")

        # ── 0. Persist inbound BEFORE the pipeline runs ─────────────────
        # Persists the canonical inbound message and returns the internal
        # messages.message_id UUID. This is the durable record of the
        # inbound message; the persist itself is the point. (The UUID was
        # historically also passed to autonomy_gate for an escalation-row
        # lookup; that lookup has been removed — escalation is enforced in
        # ResponsePolicyAgent._detect_escalation via risk flags — so the
        # UUID is no longer consumed at policy time.)
        triggered_by_uuid: Optional[UUID] = None
        try:
            triggered_by_uuid = await self._audit.persist_inbound(
                db_session, message,
            )
        except Exception as exc:  # noqa: BLE001 — fail-open
            logger.exception(
                "[MessagingBrain] persist_inbound raised (continuing): %s", exc,
            )
            record.notes.append(f"persist_inbound_error: {type(exc).__name__}")

        try:
            # ── 1. Intake ──────────────────────────────────────────────
            classification, classifier_metadata = await self.classify_message(
                message,
                db_session=db_session,
            )
            record.classification = classification
            record.classifier_metadata = classifier_metadata
            if classifier_metadata.classifier_source in {
                "deterministic",
                "llm_escalated",
                "llm_failed_keyword_default",
            }:
                record.agent_path.append(self._intake_prefilter.name)
                if classifier_metadata.classifier_source == "llm_escalated":
                    record.agent_path.append("LLMIntakeAgent")
            elif classifier_metadata.classifier_source in {"llm", "llm_primary"}:
                record.agent_path.append("LLMIntakeAgent")
            else:
                record.agent_path.append(getattr(self._intake_keyword, "name", "IntakeAgent"))

            if await self._is_fast_path_stage_enabled(
                message,
                db_session=db_session,
            ):
                fast_path = await self._fast_path_stage.run(
                    message=message,
                    classification=classification,
                    db_session=db_session,
                )
                record.agent_path.append(self._fast_path_stage.name)
                if fast_path is not None:
                    record.notes.extend(fast_path.notes)
                    draft = GuestResponseDraft(
                        response_text=fast_path.response_text,
                        confidence=fast_path.confidence,
                        confidence_source=fast_path.confidence_source,
                        final_action=fast_path.final_action,
                        escalation_required=fast_path.escalation_required,
                        reason_for_escalation=fast_path.reason_for_escalation,
                    )
                    record.final_response = draft
                    return draft

            # ── 2. Context ─────────────────────────────────────────────
            context = await self._context_builder.build(
                message, classification, db_session=db_session,
            )
            record.context_summary = self._summarize_context(context)
            record.agent_path.append(self._context_builder.name)

            # ── 3. Route ───────────────────────────────────────────────
            brain_router_threshold = await load_brain_router_threshold(
                tenant_id=message.tenant_id,
                db=db_session,
            )
            route: RouteOutcome = self._router.route(
                classification,
                confidence_threshold=brain_router_threshold,
                identity_state=str(
                    getattr(getattr(message, "identity", None), "state", "")
                    or "pseudonymous"
                ).lower(),
                specialist_lookup=self._specialists,
            )
            record.notes.append(f"router: {route.reason}")

            # ── 4. Specialists ─────────────────────────────────────────
            for agent_name in route.agent_names:
                specialist = self._resolve_specialist(
                    agent_name, classification.intent_topic,
                )
                decision = await specialist.run(
                    message=message,
                    classification=classification,
                    context=context,
                    db_session=db_session,
                )
                self._enforce_evidence_contract(
                    agent_name, decision, context, record,
                )
                record.decisions.append(decision)
                record.module_events.extend(decision.module_events)
                record.agent_path.append(agent_name)

            # ── 5. Policy ──────────────────────────────────────────────
            policy = await self._policy.evaluate(
                message=message,
                context=context,
                decisions=record.decisions,
                db_session=db_session,
            )
            record.policy = policy
            record.agent_path.append(self._policy.name)

            # ── 5.5. KB gap emission from specialist decisions ─────────
            # Brain-side entry into the cross-operator learning loop.
            # Fire-and-forget; never blocks the pipeline.
            await self._emit_kb_gaps_from_decisions(
                message=message,
                decisions=record.decisions,
                record=record,
            )

            # ── 5.6. Answerability gate ────────────────────────────────
            # Closed-world rules assess which requested topics have
            # sufficient grounded facts in the bundle.  Topics that lack
            # data become missing_topic_ids — the composer reads these as
            # a binding "hedge, don't invent" instruction (hold-mode).
            # If the gate finds gaps AND policy was AUTO_SEND, downgrade
            # to DRAFT_ONLY so a human reviews the hold response.
            try:
                gap_analysis = await self._knowledge_gap_agent.analyze(
                    message=message.text or "",
                    classification=classification,
                    context=context,
                )
                missing_topic_ids = gap_analysis.missing_topic_ids
                if missing_topic_ids and policy.final_action == RecommendedAction.AUTO_SEND:
                    policy = policy.model_copy(
                        update={"final_action": RecommendedAction.DRAFT_ONLY}
                    )
                    record.notes.append(
                        f"answerability_gate: AUTO_SEND downgraded to DRAFT_ONLY "
                        f"for gaps={missing_topic_ids}"
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "[MessagingBrain] answerability gate failed (non-fatal): %s", exc
                )
                missing_topic_ids = []

            # ── 6. Compose response ────────────────────────────────────
            # Always compute the brain concatenation fallback first.
            # This is the load-bearing invariant: we never regress below
            # today's behavior.
            concatenation_draft = self._compose_response(
                decisions=record.decisions, policy=policy,
            )

            # Resolve the composer flag. Fail-closed: if lookup raises,
            # treat as composer-off and use concatenation.
            composer_enabled = await self._is_composer_enabled(
                message=message,
                record=record,
                db_session=db_session,
            )

            if composer_enabled:
                # Composer flag is on. Resolve the shadow flag — also
                # fail-closed (shadow=True on error keeps concatenation
                # operator-facing, which is the safer default).
                composer_shadow = await self._is_composer_shadow_enabled(
                    message=message,
                    record=record,
                    db_session=db_session,
                )

                # Run the composer. _run_composer never raises; on
                # internal error it returns synthetic fallback metadata
                # so the audit row distinguishes "composer didn't run"
                # (None) from "composer was attempted" (fallback source).
                composer_metadata = await self._run_composer(
                    message=message,
                    decisions=record.decisions,
                    context=context,
                    concatenation_text=concatenation_draft.response_text,
                    db_session=db_session,
                    record=record,
                    missing_topic_ids=missing_topic_ids,
                )
                record.composer_metadata = composer_metadata

                if composer_shadow:
                    # Compare mode: operator sees concatenation;
                    # composer text recorded for side-by-side compare.
                    draft = concatenation_draft
                    record.notes.append(
                        "composer_shadow_mode: "
                        "operator_facing=concatenation, "
                        f"composer_source={composer_metadata.composer_source}"
                    )
                else:
                    # Live mode: composer text becomes operator-facing
                    # draft. Preserve all other fields from the
                    # concatenation_draft (confidence, final_action,
                    # evidence_references, contributing_agents, etc.).
                    draft = concatenation_draft.model_copy(update={
                        "response_text": composer_metadata.composer_response_text,
                    })
                    record.notes.append(
                        f"composer_live_mode: "
                        f"composer_source={composer_metadata.composer_source}"
                    )
            else:
                # Composer flag off. Concatenation only; no metadata.
                draft = concatenation_draft

            # ── 6b. Emit composer outcome metric ──────────────────────────
            # Runs for every inbound message that reaches step 6 — once, at
            # the natural convergence of all three branches (live, shadow,
            # flag-off). Fast-path early returns and pre-step-6 exceptions
            # never reach this point, so the metric is emission-clean.
            _meta = record.composer_metadata
            observe_composer_outcome(
                composer_source=_meta.composer_source if _meta is not None else "none",
                composer_notes=_meta.composer_notes if _meta is not None else [],
            )

            record.final_response = draft

            # ── 7. Module dispatch — only on policy approval ───────────
            if policy.final_action != RecommendedAction.ESCALATE:
                await self._dispatch_modules(
                    events=policy.module_events_to_dispatch,
                    record=record,
                    db_session=db_session,
                    shadow_mode=effective_shadow,
                )
            else:
                record.notes.append(
                    "module_dispatch_skipped: policy=ESCALATE"
                )

            return draft

        except Exception as exc:  # noqa: BLE001 — must not propagate
            logger.exception("[MessagingBrain] pipeline error: %s", exc)
            record.notes.append(f"pipeline-error: {exc}")
            fallback = GuestResponseDraft(
                response_text=(
                    "Thanks for the message — a teammate will follow up shortly."
                ),
                confidence=0.0,
                final_action=RecommendedAction.ESCALATE,
                escalation_required=True,
                reason_for_escalation=f"orchestrator error: {type(exc).__name__}",
            )
            record.final_response = fallback
            return fallback

        finally:
            # ── 8. Audit write — always runs ──────────────────────────
            record.completed_at = datetime.utcnow()
            try:
                await self._audit.write(
                    record,
                    db_session=db_session,
                    original_message=message,
                )
            except Exception as audit_exc:  # noqa: BLE001
                logger.exception(
                    "[MessagingBrain] audit write failed: %s", audit_exc,
                )

    # ── Proactive entry (Phase 2 build-out — skeleton kept) ─────────────────

    async def handle_proactive_trigger(
        self,
        intent: OutboundIntent,
        *,
        db_session: Any,
        shadow_mode: Optional[bool] = None,
    ) -> GuestResponseDraft:
        """Run a proactive outbound trigger through the brain.

        Phase 1.3a: skeleton kept from 1.2 with minor updates for module
        dispatch and shadow mode. Real proactive specialists land in
        Phase 2.

        Note: KB gap emission (step 5.5 in the inbound pipeline) is
        intentionally not run here. KB gaps are an inbound-quality
        signal — proactive triggers do not have "guest needed this fact"
        semantics.

        Note: the LLM composer (Session 12) is also intentionally not
        run on the proactive path. The composer's prompt is shaped for
        guest-reply composition; proactive triggers use shim text and
        don't have a guest utterance to reply to. Proactive composition
        stays on the Phase 1.3a string concatenation. Adding proactive
        composer support is a small follow-on once the inbound case is
        validated.
        """
        effective_shadow = (
            self._shadow_mode if shadow_mode is None else shadow_mode
        )

        record = AgentAuditRecord(
            message_id=intent.intent_id,
            tenant_id=intent.tenant_id,
            channel="proactive",
        )
        if effective_shadow:
            record.notes.append("shadow_mode=true")

        shim: Optional[InboundGuestMessage] = None
        try:
            classification = MessageClassification(
                intent_type=IntentType.SYSTEM_EVENT,
                intent_topic=intent.trigger_type,
                confidence=1.0,
                urgency=Urgency.LOW,
                reason=f"proactive trigger: {intent.trigger_type}",
            )
            record.classification = classification
            record.agent_path.append("ProactiveTrigger")

            context = await self._context_builder.build_for_proactive(
                intent, db_session=db_session,
            )
            record.context_summary = self._summarize_context(context)
            record.agent_path.append(self._context_builder.name)

            route = self._router.route(classification)
            record.notes.append(f"router: {route.reason}")

            for agent_name in route.agent_names:
                specialist = self._resolve_specialist(
                    agent_name, classification.intent_topic,
                )
                shim = InboundGuestMessage(
                    message_id=intent.intent_id,
                    tenant_id=intent.tenant_id,
                    channel="proactive",
                    text=f"[proactive:{intent.trigger_type}]",
                    guest_id=intent.guest_id,
                    guest_email=intent.guest_email,
                    guest_phone=intent.guest_phone,
                    guest_name=intent.guest_name,
                    reservation_id=intent.reservation_id,
                    property_id=intent.property_id,
                    property_code=intent.property_code,
                    lifecycle=intent.lifecycle or context.lifecycle,
                    session_token=intent.session_token,
                    metadata={
                        "proactive_payload": intent.payload,
                        "channel_preference": intent.channel_preference,
                    },
                )
                decision = await specialist.run(
                    message=shim,
                    classification=classification,
                    context=context,
                    db_session=db_session,
                )
                record.decisions.append(decision)
                record.module_events.extend(decision.module_events)
                record.agent_path.append(agent_name)

            policy = await self._policy.evaluate(
                message=shim,
                context=context,
                decisions=record.decisions,
                db_session=db_session,
            )
            record.policy = policy
            record.agent_path.append(self._policy.name)

            draft = self._compose_response(
                decisions=record.decisions, policy=policy,
            )
            record.final_response = draft

            if policy.final_action != RecommendedAction.ESCALATE:
                await self._dispatch_modules(
                    events=policy.module_events_to_dispatch,
                    record=record,
                    db_session=db_session,
                    shadow_mode=effective_shadow,
                )

            return draft

        except Exception as exc:  # noqa: BLE001
            logger.exception("[MessagingBrain.proactive] pipeline error: %s", exc)
            record.notes.append(f"pipeline-error: {exc}")
            fallback = GuestResponseDraft(
                response_text="",  # proactive errors should not auto-send
                confidence=0.0,
                final_action=RecommendedAction.DRAFT_ONLY,
                reason_for_escalation=f"proactive error: {type(exc).__name__}",
            )
            record.final_response = fallback
            return fallback

        finally:
            record.completed_at = datetime.utcnow()
            try:
                await self._audit.write(
                    record, db_session=db_session, original_message=shim,
                )
            except Exception as audit_exc:  # noqa: BLE001
                logger.exception(
                    "[MessagingBrain.proactive] audit write failed: %s",
                    audit_exc,
                )

    # ── Module dispatch ─────────────────────────────────────────────────────

    async def _dispatch_modules(
        self,
        *,
        events: List[ModuleEvent],
        record: AgentAuditRecord,
        db_session: Any,
        shadow_mode: bool,
    ) -> None:
        """Dispatch each ModuleEvent to its registered module.

        Called only after policy approves (final_action != ESCALATE).
        Module crashes are caught and surfaced in the audit record;
        they do NOT propagate up to fail the whole pipeline.
        """
        for event in events:
            module = self._modules.get(event.module)
            if module is None:
                logger.warning(
                    "[MessagingBrain] no module registered for %r",
                    event.module,
                )
                record.notes.append(
                    f"module-not-registered: {event.module}"
                )
                continue
            try:
                response = await module.handle_event(
                    event,
                    db_session=db_session,
                    shadow_mode=shadow_mode,
                )
                record.module_responses.append(response)
                if not response.success:
                    record.notes.append(
                        f"module-failed: {event.module} — {response.error}"
                    )
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "[MessagingBrain] module %s crashed: %s",
                    event.module, exc,
                )
                record.notes.append(
                    f"module-crash: {event.module} — {type(exc).__name__}: {exc}"
                )
                # Synthesize a failed response so the audit trail stays complete.
                record.module_responses.append(
                    ModuleResponse(
                        event_id=event.event_id,
                        module=event.module,
                        success=False,
                        error=f"crash: {type(exc).__name__}: {exc}",
                    )
                )

    # ── KB gap emission ─────────────────────────────────────────────────────

    async def _emit_kb_gaps_from_decisions(
        self,
        *,
        message: InboundGuestMessage,
        decisions: List[AgentDecision],
        record: AgentAuditRecord,
    ) -> None:
        """Emit KB gap rows for specialists that materially deflected.

        Called after policy evaluation, before compose_response. For each
        specialist decision:

          - If missing_info is empty after filtering the stub sentinel,
            skip — nothing to learn from.
          - If recommended_action is AUTO_SEND, skip — the specialist
            answered confidently, advisory missing-info notes are not
            a gap.
          - Otherwise emit one canonical gap-record scheduler call.
            The call is fire-and-forget; failure is logged at WARNING
            but never aborts the pipeline.

        The audit record's notes capture the count and topics emitted so
        operators reviewing drafts can see the brain participated in the
        learning loop.
        """
        if not decisions:
            return

        # Filter to decisions that warrant gap emission. The AUTO_SEND
        # guard keeps signal aligned with legacy "we couldn't answer
        # cleanly" semantics.
        emittable: List[AgentDecision] = []
        for d in decisions:
            filtered_missing = [
                m for m in (d.missing_info or [])
                if m != _STUB_SPECIALIST_SENTINEL
            ]
            if not filtered_missing:
                continue
            if d.recommended_action == RecommendedAction.AUTO_SEND:
                continue
            emittable.append(d)

        if not emittable:
            return

        emitted_topics: List[str] = []
        for d in emittable:
            filtered_missing = [
                m for m in (d.missing_info or [])
                if m != _STUB_SPECIALIST_SENTINEL
            ]
            try:
                schedule_gap_record(
                    tenant_id=message.tenant_id,
                    question=message.text or "",
                    answer_attempt=d.draft_text or "",
                    confidence_score=d.confidence,
                    used_kb_chunks=bool(d.evidence_used),
                    was_deflected=True,
                    property_code=message.property_code or None,
                    stage=(
                        message.lifecycle.value
                        if message.lifecycle is not None
                        else MessagingLifecycle.IN_STAY.value
                    ),
                    channel=message.channel or "text",
                    source="messaging_brain_orchestrator",
                    detected_intent=d.intent_topic,
                    metadata={
                        "agent_name": d.agent_name,
                        "source_provider": message.source_provider,
                        "evidence_used": list(d.evidence_used or []),
                        "missing_info": filtered_missing,
                    },
                )
                emitted_topics.append(d.intent_topic)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "[MessagingBrain] KB gap emission failed for "
                    "agent=%s topic=%s: %s",
                    d.agent_name, d.intent_topic, exc,
                )

        if emitted_topics:
            record.notes.append(
                f"kb_gaps_emitted: count={len(emitted_topics)} "
                f"topics={sorted(set(emitted_topics))}"
            )

    # ── Composer flag resolution ───────────────────────────────────────────

    async def _is_composer_enabled(
        self,
        *,
        message: InboundGuestMessage,
        record: AgentAuditRecord,
        db_session: Any,
    ) -> bool:
        """Resolve the MESSAGING_BRAIN_LLM_COMPOSER flag for this message.

        Fail-closed: any exception from the flag-lookup path returns
        False. When in doubt, today's behavior (concatenation) wins.
        Failure is logged at WARNING and recorded in the audit notes.
        """
        try:
            return await is_messaging_brain_llm_composer_enabled(
                db=db_session,
                tenant_id=message.tenant_id,
                property_code=message.property_code or None,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[MessagingBrain] composer flag lookup failed; "
                "treating as off: %s",
                exc,
            )
            record.notes.append(
                f"composer_flag_lookup_error:{type(exc).__name__}"
            )
            return False

    async def _is_composer_shadow_enabled(
        self,
        *,
        message: InboundGuestMessage,
        record: AgentAuditRecord,
        db_session: Any,
    ) -> bool:
        """Resolve the MESSAGING_BRAIN_LLM_COMPOSER_SHADOW flag for this
        message.

        Only called when the composer flag has already resolved to True.
        Fail-open to the composer: any exception returns False (live
        mode), keeping the operator-facing draft aligned with the LLM
        output rather than silently hiding it behind concatenation. The
        operator approval gate remains the safety net for bad drafts;
        shadow-mode fallback on flag-read errors is more harmful because
        it masks the artifact operators are meant to review.
        """
        try:
            return await is_messaging_brain_llm_composer_shadow_enabled(
                db=db_session,
                tenant_id=message.tenant_id,
                property_code=message.property_code or None,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[MessagingBrain] composer-shadow flag lookup failed; "
                "treating as shadow=False: %s",
                exc,
            )
            record.notes.append(
                f"composer_shadow_flag_lookup_error:{type(exc).__name__}"
            )
            return False

    async def _run_composer(
        self,
        *,
        message: InboundGuestMessage,
        decisions: List[AgentDecision],
        context: GuestContextBundle,
        concatenation_text: str,
        db_session: Any,
        record: AgentAuditRecord,
        missing_topic_ids: Optional[List[str]] = None,
    ) -> ComposerMetadata:
        """Invoke the composer and return ComposerMetadata.

        On any exception at the orchestrator-composer boundary, returns a
        synthetic ComposerMetadata with composer_source="fallback_concatenation"
        and a composer_orchestrator_error note. This preserves the
        distinction in audit data:

          - composer_metadata is None → composer didn't run (flag off).
          - composer_metadata.composer_source == "fallback_concatenation"
            with composer_orchestrator_error note → composer was
            attempted but the integration broke.
          - composer_metadata.composer_source == "fallback_concatenation"
            without the error note → composer ran cleanly and its own
            internal logic chose to fall back (all LLM providers failed
            or no keys configured).

        These are three distinct states; the audit row preserves them.
        """
        try:
            include_preferences = await self._is_composer_preferences_enabled(
                message=message,
                record=record,
                db_session=db_session,
            )
            return await self._composer.compose(
                message=message,
                decisions=decisions,
                context=context,
                include_learned_preferences=include_preferences,
                missing_topic_ids=missing_topic_ids or [],
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "[MessagingBrain] composer integration crashed: %s", exc,
            )
            return ComposerMetadata(
                composer_source="fallback_concatenation",
                composer_response_text=concatenation_text,
                composer_latency_ms=0,
                composer_input_tokens=None,
                composer_output_tokens=None,
                composer_notes=[
                    f"composer_orchestrator_error:{type(exc).__name__}",
                ],
            )

    async def _is_composer_preferences_enabled(
        self,
        *,
        message: InboundGuestMessage,
        record: AgentAuditRecord,
        db_session: Any,
    ) -> bool:
        """Resolve the BRAIN_COMPOSER_PREFERENCES flag for this message."""
        try:
            return await is_brain_composer_preferences_enabled(
                db=db_session,
                tenant_id=message.tenant_id,
                property_code=message.property_code or None,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[MessagingBrain] composer-preferences flag lookup failed; "
                "learned preferences disabled for this message: %s", exc,
            )
            record.notes.append(
                f"composer_preferences_flag_lookup_error:{type(exc).__name__}"
            )
            return False

    # ── Helpers ─────────────────────────────────────────────────────────────

    @staticmethod
    def _enforce_evidence_contract(
        agent_name: str,
        decision: AgentDecision,
        context: GuestContextBundle,
        record: AgentAuditRecord,
    ) -> None:
        """Log a violation if the agent cited evidence not in context.evidence_keys.

        Non-fatal — pipeline continues. The violation appears in the
        audit log and (via update_normalization_outcome) in the DB row's
        fallback_reason field, so misbehaving agents are visible to
        operators reviewing drafts.
        """
        violations = (
            set(decision.evidence_used) - set(context.evidence_keys)
        )
        if not violations:
            return
        msg = (
            f"agent {agent_name} cited evidence not in "
            f"context.evidence_keys: {sorted(violations)}"
        )
        logger.warning("[MessagingBrain] %s", msg)
        record.notes.append(f"evidence-violation: {msg}")

    @staticmethod
    def _compose_response(
        *,
        decisions: List[AgentDecision],
        policy: ResponsePolicyDecision,
    ) -> GuestResponseDraft:
        """Merge specialist drafts into one guest-facing response.

        Phase 1.3a strategy: concatenate non-empty draft_text in order
        with a blank line between. This is the "brain concatenation
        fallback" referenced throughout the Session 12 design — it is
        always computed first in step 6 of the inbound pipeline so the
        operator-facing draft has a meaningful baseline regardless of
        whether the LLM composer runs. When the composer flag is off,
        this is the operator-facing draft. When the composer runs in
        shadow mode, this is still the operator-facing draft. When the
        composer runs in live mode, response_text is overwritten with
        the composer's output but all other fields here are preserved.
        """
        parts = [d.draft_text.strip() for d in decisions if d.draft_text.strip()]
        text = "\n\n".join(parts) if parts else (
            "Thanks for the message — I'll get back to you shortly."
        )
        all_evidence: List[str] = []
        for d in decisions:
            for ev in d.evidence_used:
                if ev not in all_evidence:
                    all_evidence.append(ev)

        return GuestResponseDraft(
            response_text=text,
            confidence=policy.confidence,
            final_action=policy.final_action,
            auto_send_allowed=policy.final_action == RecommendedAction.AUTO_SEND,
            escalation_required=policy.final_action == RecommendedAction.ESCALATE,
            reason_for_escalation=(
                "; ".join(policy.reasons)
                if policy.final_action == RecommendedAction.ESCALATE
                else ""
            ),
            evidence_references=all_evidence,
            contributing_agents=[d.agent_name for d in decisions],
        )

    @staticmethod
    def _summarize_context(context: GuestContextBundle) -> Dict[str, Any]:
        """Compact summary of what context was loaded, for the audit log."""
        return {
            "evidence_keys": list(context.evidence_keys),
            "missing_context": list(context.missing_context),
            "lifecycle": (
                context.lifecycle.value
                if hasattr(context.lifecycle, "value")
                else str(context.lifecycle)
            ),
            "has_property_facts": bool(context.property_facts),
            "has_reservation_facts": bool(context.reservation_facts),
            "has_property_knowledge": bool(context.property_knowledge),
            "has_operator_guidance": bool(context.operator_guidance),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Singleton accessor
# ─────────────────────────────────────────────────────────────────────────────

_orchestrator: Optional[GuestMessageBrainOrchestrator] = None


def get_messaging_brain_orchestrator() -> GuestMessageBrainOrchestrator:
    """Get the process-wide orchestrator singleton.

    The orchestrator is stateless apart from its agent registry, so a
    singleton is appropriate. Tests should construct their own
    orchestrator instead of reusing this one.
    """
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = GuestMessageBrainOrchestrator()
    return _orchestrator
