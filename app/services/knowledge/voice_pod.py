"""
Voice Pod - Minimal context voice/chat session.

This replaces the heavy ConciergeRunner with a lightweight session
that gets just-in-time context from the Librarian Agent.

Key design principles:
- MINIMAL system prompt (WiFi, door code, check-in/out - that's it)
- Just-in-time retrieval (only fetch context when needed)
- Fast responses (target <500ms for simple queries)
- Low token cost (~$0.02 per interaction vs $0.50 for "god-like" agents)
- Explicit routing via ConciergeRouter (no implicit if-chains)

The Voice Pod is instantiated per session, not per operator.
It's a template that gets filled with specific context.

Routing flow (enforced by ConciergeRouter, in priority order):
  ESCALATE_URGENT  → hard human-handoff + escalation ticket, no LLM
  ESCALATE_HIGH    → maintenance/complaint handoff + ticket, no LLM
  ESCALATE_EQ      → EQ-detected crisis handoff + ticket, no LLM
  QUICK_ANSWER     → templated WiFi/door/times answer, no LLM
  PMS_QUERY        → PMS MCP lookup → LLM formatting
  KNOWLEDGE_LOOKUP → Librarian RAG → LLM formatting
  LLM_GENERAL      → Gemini generation with minimal context
"""

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.services.knowledge.librarian_agent import (
    LibrarianAgent,
    LibrarianQuery,
    LibrarianResponse,
    get_librarian_agent,
)
from app.services.concierge.guest_session import GuestSession, SessionPhase
from app.services.agents.emotional_intelligence.eq_analyzer import (
    EQAnalyzer,
    EmotionalContext,
    EmotionalState,
    UrgencyLevel,
    get_eq_analyzer,
)
from app.services.observability.watch_layer import WatchLayer, get_watch_layer
from app.services.agents.router_agent import (
    ConciergeRouter,
    Route,
    ESCALATION_HIGH,
    ESCALATION_URGENT,
    _first_matching_keyword,
    get_concierge_router,
)
from app.services.observability.llm_usage_tracker import LLMCallTimer, LLMUsageTracker

logger = logging.getLogger(__name__)


def _check_keyword_escalation(text: str) -> Optional[tuple[str, str]]:
    """Compatibility helper for non-pod callers that need hard escalation gates."""
    urgent = _first_matching_keyword(text, ESCALATION_URGENT)
    if urgent:
        return ("urgent", urgent)
    high = _first_matching_keyword(text, ESCALATION_HIGH)
    if high:
        return ("high", high)
    return None


def _build_escalation_response_text(
    priority: str,
    support_phone: Optional[str] = None,
    guest_name: Optional[str] = None,
) -> str:
    """Build a consistent human-handoff response for keyword escalations."""
    support = support_phone or "(850) 733-7433"
    name_prefix = f"{guest_name}, " if guest_name else ""
    apology = f"I'm so sorry about this issue, {guest_name}! " if guest_name else ""
    if priority == "urgent":
        return (
            f"{name_prefix}this needs immediate attention. "
            f"Please call our emergency line right now: {support}. "
            "Someone is available 24/7."
        )
    return (
        apology +
        "I'm immediately alerting our property team — they'll be in touch very shortly. "
        f"If it's urgent, please call us directly: **{support}**."
    )


@dataclass
class VoicePodConfig:
    """Configuration for a Voice Pod instance."""
    # LLM settings
    # Primary: Groq llama-3.1-70b-versatile (fast + cheap)
    # Fallback: gemini-2.0-flash-exp (if no groq key)
    # This field is used only for Gemini fallback path; Groq model set in config.groq_model
    model: str = "gemini-2.0-flash-exp"
    max_tokens: int = 150
    temperature: float = 0.7

    # Retrieval settings
    retrieval_top_k: int = 5
    retrieval_min_score: float = 0.35

    # Response settings
    max_response_sentences: int = 3
    include_phone_numbers: bool = True


@dataclass
class VoicePodContext:
    """Minimal context for the Voice Pod."""
    # Guest info
    guest_name: str
    property_name: str
    property_code: str
    tenant_id: UUID
    operator_id: str

    # Phase
    phase: SessionPhase
    days_until_checkin: int = 0
    days_remaining: int = 0

    # Quick facts (always in system prompt)
    wifi_network: Optional[str] = None
    wifi_password: Optional[str] = None
    door_code: Optional[str] = None
    check_in_time: str = "4:00 PM"
    check_out_time: str = "10:00 AM"

    # Persona
    concierge_name: str = "Coral"
    concierge_emoji: str = "🐚"

    # Support
    support_phone: Optional[str] = None


@dataclass
class VoicePodResponse:
    """Response from the Voice Pod."""
    text: str

    # For audio generation
    ssml: Optional[str] = None

    # Context used (for debugging)
    context_used: Optional[str] = None
    quick_answer_used: bool = False

    # Metrics
    total_time_ms: float = 0.0
    retrieval_time_ms: float = 0.0
    generation_time_ms: float = 0.0

    # Cost tracking
    estimated_cost_usd: float = 0.0


class VoicePod:
    """
    A voice/chat session with minimal context.

    The Voice Pod:
    1. Has a tiny system prompt (just quick facts)
    2. Routes every message through ConciergeRouter (explicit, logged policy)
    3. Calls the Librarian only when needed
    4. Generates short, friendly responses
    """

    def __init__(
        self,
        context: VoicePodContext,
        db_session: AsyncSession,
        config: Optional[VoicePodConfig] = None,
    ):
        self.context = context
        self.db_session = db_session
        self.config = config or VoicePodConfig()

        # Librarian for retrieval
        self._librarian: Optional[LibrarianAgent] = None

        # EQ Analyzer for emotional intelligence
        self._eq_analyzer: EQAnalyzer = get_eq_analyzer()
        self._last_eq_context: Optional[EmotionalContext] = None

        # LLM client (lazy loaded)
        self._llm = None

        # Build system prompt
        self._system_prompt = self._build_system_prompt()

        # Conversation history (kept minimal)
        self._history: List[Dict[str, str]] = []
        self._max_history = 6  # Keep last 3 exchanges

        # Session ID for EQ tracking
        self._session_id: str = f"{self.context.operator_id}:{self.context.property_code}:{id(self)}"

        # Watch layer for observability
        self._watch: WatchLayer = get_watch_layer()

        # Router/Supervisor agent — lazy-initialized
        self._router: Optional[ConciergeRouter] = None

        # Experiment variant assigned to this session
        self._variant_id: str = "control"
        self._system_prompt_override: Optional[str] = None

        # Feature flags
        self._dining_enabled: bool = get_settings().concierge_dining_enabled

    # ─────────────────────────────────────────────────────────────────────────
    # Constructor helpers
    # ─────────────────────────────────────────────────────────────────────────

    @classmethod
    async def from_session(
        cls,
        session: GuestSession,
        db_session: AsyncSession,
        config: Optional[VoicePodConfig] = None,
    ) -> "VoicePod":
        """
        Create a VoicePod from a GuestSession.

        Context resolution order (highest-wins):
          1. PropertyRouter (tenant-scoped DB lookup) — always attempted
          2. session.property_context JSON (in-memory fallback)
          3. Librarian retrieval (if both above are empty)

        KnowledgeMCP also gets the db_session injected here so every
        retrieval within this VoicePod instance has a live DB connection.
        """
        prop_ctx = session.property_context or {}

        # ── Tier 1: Tenant-scoped PropertyRouter lookup ──────────────────────
        prop_record = None
        tenant_id = getattr(session, "tenant_id", None)
        if tenant_id and db_session:
            try:
                from app.services.agents.property_router import get_property_router
                prop_record = await get_property_router().get_property(
                    db=db_session,
                    tenant_id=str(tenant_id),
                    property_code=session.property_code,
                )
                if prop_record:
                    logger.debug(
                        "[VoicePod] PropertyRouter resolved %s for tenant %s",
                        session.property_code, tenant_id,
                    )
            except Exception as exc:
                logger.warning("[VoicePod] PropertyRouter lookup failed (non-fatal): %s", exc)

        # Merge: PropertyRouter data takes precedence over session.property_context
        if prop_record:
            wifi_network = prop_record.wifi_network or prop_ctx.get("wifi_network")
            wifi_password = prop_record.wifi_password or prop_ctx.get("wifi_password")
            door_code = prop_record.door_code or prop_ctx.get("door_code")
            check_in_time = prop_record.check_in_time or prop_ctx.get("check_in_time", "4:00 PM")
            check_out_time = prop_record.check_out_time or prop_ctx.get("check_out_time", "10:00 AM")
        else:
            wifi_network = prop_ctx.get("wifi_network")
            wifi_password = prop_ctx.get("wifi_password")
            door_code = prop_ctx.get("door_code")
            check_in_time = prop_ctx.get("check_in_time", "4:00 PM")
            check_out_time = prop_ctx.get("check_out_time", "10:00 AM")

        if not session.tenant_id:
            raise ValueError(
                f"VoicePod.from_session received session token={session.token} "
                f"without canonical tenant_id. Cannot construct VoicePod — the "
                f"brain requires tenant_id to query knowledge_embeddings. "
                f"This indicates a session creation path that bypassed canonical "
                f"tenant resolution (see _save_session warning logs)."
            )

        context = VoicePodContext(
            guest_name=session.guest_first_name,
            property_name=session.property_name,
            property_code=session.property_code,
            tenant_id=session.tenant_id,
            operator_id=session.operator_id,
            phase=session.phase,
            days_until_checkin=session.days_until_checkin,
            days_remaining=session.days_remaining,
            wifi_network=wifi_network,
            wifi_password=wifi_password,
            door_code=door_code,
            check_in_time=check_in_time,
            check_out_time=check_out_time,
            concierge_name=session.concierge_name,
            concierge_emoji=session.concierge_emoji,
            support_phone=session.operator_support_phone,
        )

        pod = cls(context, db_session, config)

        # ── Experiment variant assignment ────────────────────────────────────
        # Done once per session at creation time.  A paused variant always
        # falls back to control — safe to do before KnowledgeMCP injection.
        try:
            from app.services.agents.experiment_registry import get_experiment_registry
            registry = get_experiment_registry()
            template_vars = {
                "guest_name": context.guest_name,
                "property_name": context.property_name,
                "concierge_name": context.concierge_name,
                "wifi_network": context.wifi_network or "Ask host",
                "wifi_password": context.wifi_password or "Ask host",
                "door_code": context.door_code or "Provided separately",
                "check_in_time": context.check_in_time,
                "check_out_time": context.check_out_time,
            }
            assignment = registry.assign(
                session_token=session.session_token,
                template_vars=template_vars,
            )
            pod._variant_id = assignment.variant_id
            pod._system_prompt_override = assignment.system_prompt_override
            # Merge config overrides (e.g. temperature, max_tokens, model)
            if assignment.config_overrides:
                for k, v in assignment.config_overrides.items():
                    if hasattr(pod.config, k):
                        setattr(pod.config, k, v)
            # Rebuild system prompt if override provided
            if pod._system_prompt_override:
                pod._system_prompt = pod._system_prompt_override
            if not assignment.is_control:
                logger.info(
                    "[VoicePod] session=%s assigned variant=%s",
                    session.session_token[:12], assignment.variant_id,
                )
            # Persist assignment to DB (fire-and-forget, non-blocking)
            if db_session:
                from app.services.agents.experiment_registry import persist_assignment as _persist_asgn
                asyncio.ensure_future(_persist_asgn(
                    session_token=session.session_token,
                    assignment=assignment,
                    variant=registry.get_variant(assignment.variant_id),
                    operator_id=getattr(session, "operator_id", None),
                    property_code=session.property_code,
                    db=db_session,
                ))
        except Exception as exc:
            logger.warning("[VoicePod] Experiment assignment failed (non-fatal): %s", exc)

        # ── Inject db_session into KnowledgeMCP so retrieval has DB access ──
        if db_session:
            try:
                from app.mcp.servers.knowledge_mcp import init_knowledge_mcp
                init_knowledge_mcp(db_session)
            except Exception as exc:
                logger.warning("[VoicePod] KnowledgeMCP session injection failed (non-fatal): %s", exc)

        # ── Tier 3: Librarian fallback if quick facts still missing ──────────
        if not context.wifi_password or not context.door_code:
            await pod._load_property_basics()

        return pod

    # ─────────────────────────────────────────────────────────────────────────
    # Router accessor
    # ─────────────────────────────────────────────────────────────────────────

    def _get_router(self) -> ConciergeRouter:
        """Lazy-initialize the router with EQ analyzer and watch layer."""
        if self._router is None:
            self._router = get_concierge_router(
                context=self.context,
                eq_analyzer=self._eq_analyzer,
                watch=self._watch,
                session_id=self._session_id,
            )
        return self._router

    # ─────────────────────────────────────────────────────────────────────────
    # Main entry point
    # ─────────────────────────────────────────────────────────────────────────

    async def respond(self, user_message: str) -> VoicePodResponse:
        """
        Generate a response to a user message.

        All routing decisions are made by ConciergeRouter — an explicit,
        named, logged policy gate.  Every decision is written to the Watch
        Layer so escalation rates, quick-answer hit rates, retrieval hit rates,
        and PMS lookup rates are observable SLOs.
        """
        start_time = time.time()
        retrieval_time = 0.0
        generation_time = 0.0
        context_used: Optional[str] = None
        librarian_response: Optional[LibrarianResponse] = None

        # ── Ask the router what to do ─────────────────────────────────────
        turns = len(self._history) // 2
        decision = await self._get_router().route(
            message=user_message,
            conversation_turns=turns,
            history=self._history,
        )

        # ── Escalation paths (urgent / high / EQ-crisis) ─────────────────
        if decision.is_escalation:
            priority = decision.priority or "high"
            logger.warning(
                "[VoicePod] %s session=%s trigger=%s",
                decision.route.value, self._session_id, decision.trigger,
            )
            # Create escalation ticket (fire-and-forget)
            asyncio.ensure_future(self._create_escalation_ticket(
                user_message=user_message,
                priority=priority,
                reason=decision.reason,
            ))
            asyncio.ensure_future(self._watch.log_voice_interaction(
                session_id=self._session_id,
                operator_id=self.context.operator_id,
                user_message=user_message,
                response=f"[{decision.route.value.upper()}]",
                latency_ms=(time.time() - start_time) * 1000,
                cost_usd=0.0,
                eq_state=decision.metadata.get("emotional_state", "urgent"),
                eq_urgency=priority,
                retrieval_used=False,
                quick_answer=False,
                property_code=self.context.property_code,
            ))
            # Record escalation metric for this variant
            try:
                from app.services.agents.experiment_registry import get_experiment_registry
                get_experiment_registry().record_metric(
                    variant_id=self._variant_id,
                    latency_ms=(time.time() - start_time) * 1000,
                    escalated=True,
                    fallback_used=False,
                    cost_usd=0.0,
                )
            except Exception:
                pass
            return VoicePodResponse(
                text=self._build_escalation_response(priority),
                quick_answer_used=False,
                total_time_ms=(time.time() - start_time) * 1000,
                estimated_cost_usd=0.0,
            )

        # ── Dining reservation intent (tool-driven, no LLM for booking flow) ─
        if self._dining_enabled:
            dining_text = await self._handle_dining_reservation(user_message)
            if dining_text:
                total_time = (time.time() - start_time) * 1000
                asyncio.ensure_future(self._watch.log_voice_interaction(
                    session_id=self._session_id,
                    operator_id=self.context.operator_id,
                    user_message=user_message,
                    response=dining_text,
                    latency_ms=total_time,
                    cost_usd=0.001,
                    eq_state="neutral",
                    eq_urgency="normal",
                    retrieval_used=False,
                    quick_answer=False,
                    property_code=self.context.property_code,
                ))
                return VoicePodResponse(
                    text=dining_text,
                    quick_answer_used=False,
                    total_time_ms=total_time,
                    estimated_cost_usd=0.001,
                )

        # ── Quick answer ──────────────────────────────────────────────────
        if decision.route == Route.QUICK_ANSWER:
            quick_text = self._check_quick_answer(user_message)
            if quick_text:
                asyncio.ensure_future(self._watch.log_voice_interaction(
                    session_id=self._session_id,
                    operator_id=self.context.operator_id,
                    user_message=user_message,
                    response=quick_text,
                    latency_ms=(time.time() - start_time) * 1000,
                    cost_usd=0.0,
                    eq_state="neutral",
                    eq_urgency="normal",
                    retrieval_used=False,
                    quick_answer=True,
                    property_code=self.context.property_code,
                ))
                return VoicePodResponse(
                    text=quick_text,
                    quick_answer_used=True,
                    total_time_ms=(time.time() - start_time) * 1000,
                    estimated_cost_usd=0.0,
                )
            # QUICK_ANSWER routed but no template matched — fall through to
            # knowledge lookup so the guest still gets a useful answer.

        # ── PMS query ─────────────────────────────────────────────────────
        if decision.route == Route.PMS_QUERY:
            pms_context = await self._lookup_pms(user_message)
            if pms_context:
                context_used = pms_context

        # ── Knowledge / Librarian RAG ─────────────────────────────────────
        if decision.route in (Route.KNOWLEDGE_LOOKUP,) or (
            decision.route in (Route.QUICK_ANSWER, Route.LLM_GENERAL)
            and context_used is None
            and self._needs_retrieval(user_message)
        ):
            retrieval_start = time.time()
            librarian_response = await self._retrieve_context(user_message)
            retrieval_time = (time.time() - retrieval_start) * 1000

            # Track retrieval hit/miss — feeds Knowledge MCP degradation SLO
            hit = bool(
                librarian_response
                and getattr(librarian_response, "chunks", None)
            )
            asyncio.ensure_future(self._watch.log_retrieval_result(
                session_id=self._session_id,
                operator_id=self.context.operator_id,
                property_code=self.context.property_code,
                query=user_message,
                hit=hit,
                chunk_count=len(getattr(librarian_response, "chunks", []) or []),
                latency_ms=retrieval_time,
            ))

            if librarian_response:
                context_used = getattr(librarian_response, "context_text", None)

                # Librarian found a direct quick answer — return without LLM
                if getattr(librarian_response, "quick_answer", None):
                    qa_text = self._format_quick_answer(
                        user_message,
                        librarian_response.quick_answer,
                        getattr(librarian_response, "quick_answer_type", None),
                    )
                    asyncio.ensure_future(self._watch.log_voice_interaction(
                        session_id=self._session_id,
                        operator_id=self.context.operator_id,
                        user_message=user_message,
                        response=qa_text,
                        latency_ms=(time.time() - start_time) * 1000,
                        cost_usd=getattr(librarian_response, "estimated_cost_usd", 0.0),
                        eq_state="neutral",
                        eq_urgency="normal",
                        retrieval_used=True,
                        quick_answer=True,
                        property_code=self.context.property_code,
                    ))
                    return VoicePodResponse(
                        text=qa_text,
                        context_used=context_used,
                        quick_answer_used=True,
                        total_time_ms=(time.time() - start_time) * 1000,
                        retrieval_time_ms=retrieval_time,
                        estimated_cost_usd=getattr(librarian_response, "estimated_cost_usd", 0.0),
                    )

        # ── EQ analysis for tone adaptation (non-blocking) ────────────────
        eq_context = await self._run_eq_analysis(user_message)

        # ── LLM generation ────────────────────────────────────────────────
        generation_start = time.time()
        response_text = await self._generate_response(user_message, context_used)
        generation_time = (time.time() - generation_start) * 1000

        total_time = (time.time() - start_time) * 1000
        estimated_cost = 0.02  # Gemini Flash conservative estimate
        if librarian_response:
            estimated_cost += getattr(librarian_response, "estimated_cost_usd", 0.0)

        self._add_to_history("user", user_message)
        self._add_to_history("assistant", response_text)

        asyncio.ensure_future(self._watch.log_voice_interaction(
            session_id=self._session_id,
            operator_id=self.context.operator_id,
            user_message=user_message,
            response=response_text,
            latency_ms=total_time,
            cost_usd=estimated_cost,
            eq_state=eq_context.emotional_state.value if eq_context else "neutral",
            eq_urgency=eq_context.urgency_level.value if eq_context else "normal",
            retrieval_used=context_used is not None,
            quick_answer=False,
            property_code=self.context.property_code,
        ))

        # ── Record per-variant metrics for experiment registry ───────────────
        try:
            from app.services.agents.experiment_registry import get_experiment_registry
            get_experiment_registry().record_metric(
                variant_id=self._variant_id,
                latency_ms=total_time,
                escalated=False,
                fallback_used=(response_text == "I'd be happy to help! Could you tell me a bit more about what you're looking for?"),
                cost_usd=estimated_cost,
            )
        except Exception as exc:
            logger.debug("[VoicePod] Experiment metric record failed (non-fatal): %s", exc)

        return VoicePodResponse(
            text=response_text,
            context_used=context_used,
            quick_answer_used=False,
            total_time_ms=total_time,
            retrieval_time_ms=retrieval_time,
            generation_time_ms=generation_time,
            estimated_cost_usd=estimated_cost,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # PMS lookup
    # ─────────────────────────────────────────────────────────────────────────

    async def _lookup_pms(self, message: str) -> Optional[str]:
        """
        Query the PMS MCP for reservation/booking context.

        Returns a compact text block for injection into the LLM prompt, or
        None if PMS is offline (stub mode) — in which case LLM proceeds with
        session-level property_context from DB.
        """
        try:
            from app.mcp.registry import get_mcp_registry
            registry = get_mcp_registry()
            result = await registry.call(
                server_name="pms",
                tool_name="get_property_info",
                operator_id=self.context.operator_id,
                params={"property_id": self.context.property_code},
            )
            if result.success and result.data and result.data.get("_source") != "stub":
                info = result.data
                lines = [f"Property: {self.context.property_name}"]
                if info.get("check_in_time"):
                    lines.append(f"Check-in: {info['check_in_time']}")
                if info.get("check_out_time"):
                    lines.append(f"Check-out: {info['check_out_time']}")
                if info.get("amenities"):
                    lines.append(f"Amenities: {', '.join(info['amenities'][:5])}")
                return "\n".join(lines)
        except Exception as exc:
            logger.debug("[VoicePod] PMS lookup failed (non-fatal): %s", exc)
        return None

    # ─────────────────────────────────────────────────────────────────────────
    # Escalation ticket creation
    # ─────────────────────────────────────────────────────────────────────────

    async def _create_escalation_ticket(
        self,
        user_message: str,
        priority: str,
        reason: str,
    ) -> None:
        """
        Create a persisted escalation ticket via EscalationService.

        Fire-and-forget — called from ensure_future so it never blocks response.
        """
        try:
            from app.services.concierge.escalation_service import get_escalation_service, EscalationPriority
            svc = get_escalation_service()
            prio = EscalationPriority.URGENT if priority == "urgent" else EscalationPriority.HIGH
            session_info = {
                "guest_name": self.context.guest_name,
                "property_name": self.context.property_name,
                "property_code": self.context.property_code,
                "support_phone": self.context.support_phone,
            }
            await svc.create_manual_escalation(
                session_token=self._session_id,
                reason=reason,
                session_info=session_info,
                conversation_history=list(self._history),
            )
        except Exception as exc:
            logger.warning("[VoicePod] Escalation ticket creation failed (non-fatal): %s", exc)

    # ─────────────────────────────────────────────────────────────────────────
    # System prompt
    # ─────────────────────────────────────────────────────────────────────────

    def _build_system_prompt(self) -> str:
        ctx = self.context

        phase_guidance = {
            SessionPhase.PRE_ARRIVAL: f"Guest arrives in {ctx.days_until_checkin} days.",
            SessionPhase.ARRIVAL_DAY: "Today is check-in day!",
            SessionPhase.IN_STAY: f"Guest has {ctx.days_remaining} days left.",
            SessionPhase.DEPARTURE_DAY: "Today is checkout day.",
            SessionPhase.POST_STAY: "Guest has checked out.",
            SessionPhase.EXPIRED: "Session ended.",
        }

        return (
            f"You are {ctx.concierge_name}, the concierge for {ctx.guest_name} "
            f"at {ctx.property_name}.\n\n"
            f"QUICK FACTS:\n"
            f"• WiFi: {ctx.wifi_network or 'Ask host'} / {ctx.wifi_password or 'Ask host'}\n"
            f"• Door: {ctx.door_code or 'Provided separately'}\n"
            f"• Check-in: {ctx.check_in_time} | Check-out: {ctx.check_out_time}\n\n"
            f"{phase_guidance.get(ctx.phase, '')}\n\n"
            f"STYLE: Warm, brief (1-2 sentences), helpful local friend."
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Quick-answer templates
    # ─────────────────────────────────────────────────────────────────────────

    def _check_quick_answer(self, message: str) -> Optional[str]:
        msg = message.lower()
        ctx = self.context

        if any(kw in msg for kw in ["wifi", "wi-fi", "internet", "password", "network"]):
            if ctx.wifi_network and ctx.wifi_password:
                return f"📶 WiFi: {ctx.wifi_network} / Password: {ctx.wifi_password}"

        if any(kw in msg for kw in ["door", "code", "access", "get in", "key"]):
            if ctx.door_code:
                return f"🔑 Door code: {ctx.door_code}"

        if "check" in msg and "out" in msg:
            return f"⏰ Check-out is at {ctx.check_out_time}. Safe travels!"

        if "check" in msg and "in" in msg:
            return f"⏰ Check-in is at {ctx.check_in_time}. See you soon!"

        if any(msg.strip() == g for g in ["hi", "hello", "hey"]):
            return f"Hi {ctx.guest_name}! {ctx.concierge_emoji} How can I help you today?"

        return None

    def _needs_retrieval(self, message: str) -> bool:
        retrieval_keywords = [
            "restaurant", "eat", "food", "dining", "breakfast", "lunch",
            "dinner", "coffee", "bar", "seafood", "pizza", "recommend",
            "activity", "activities", "do", "fun", "beach chair",
            "umbrella", "kayak", "paddleboard", "bike", "rental",
            "near", "nearby", "around", "local", "grocery", "store",
            "pharmacy", "hospital", "emergency", "urgent",
            "pool", "hot tub", "grill", "parking", "trash", "towel",
            "rule", "pet", "smoke", "amenity", "amenities",
        ]
        msg = message.lower()
        return any(kw in msg for kw in retrieval_keywords)

    def _is_dining_intent(self, message: str) -> bool:
        msg = message.lower()
        has_food = any(
            kw in msg for kw in ["restaurant", "dinner", "lunch", "breakfast", "eat", "dining"]
        )
        has_booking = any(
            kw in msg for kw in ["book", "reserve", "reservation", "table", "make a booking"]
        )
        return has_food and has_booking

    def _extract_dining_slots(self, message: str) -> Dict[str, Any]:
        msg = message.strip()
        lower = msg.lower()
        out: Dict[str, Any] = {}

        # Party size
        party_patterns = [
            r"\bfor\s+(\d{1,2})\b",
            r"\bparty\s+of\s+(\d{1,2})\b",
            r"\b(\d{1,2})\s+people\b",
        ]
        for pattern in party_patterns:
            m = re.search(pattern, lower)
            if m:
                out["party_size"] = int(m.group(1))
                break

        # Date
        iso = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", lower)
        if iso:
            out["date"] = iso.group(1)
        elif "tomorrow" in lower:
            out["date"] = (date.today() + timedelta(days=1)).isoformat()
        elif "tonight" in lower or "today" in lower:
            out["date"] = date.today().isoformat()

        # Time
        t1 = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", lower)
        if t1:
            out["time"] = f"{int(t1.group(1)):02d}:{t1.group(2)}"
        else:
            t2 = re.search(r"\b(1[0-2]|0?[1-9])(?::([0-5]\d))?\s?(am|pm)\b", lower)
            if t2:
                hour = int(t2.group(1))
                minute = int(t2.group(2) or 0)
                meridiem = t2.group(3)
                if meridiem == "pm" and hour != 12:
                    hour += 12
                if meridiem == "am" and hour == 12:
                    hour = 0
                out["time"] = f"{hour:02d}:{minute:02d}"

        # Restaurant name (lightweight extraction)
        rn = re.search(r"\b(?:at|for|to)\s+([A-Za-z0-9&' .-]{3,60})$", msg)
        if rn:
            candidate = rn.group(1).strip(" .")
            if candidate and candidate.lower() not in {"dinner", "lunch", "breakfast"}:
                out["restaurant_name"] = candidate
        else:
            book_pat = re.search(
                r"\b(?:book|reserve|reservation)\s+(?:a\s+table\s+)?(?:at\s+)?([A-Za-z0-9&' .-]{3,60})",
                msg,
                flags=re.IGNORECASE,
            )
            if book_pat:
                candidate = book_pat.group(1).strip(" .")
                out["restaurant_name"] = candidate

        return out

    async def _handle_dining_reservation(self, message: str) -> Optional[str]:
        if not self._is_dining_intent(message):
            return None

        slots = self._extract_dining_slots(message)
        required = ["restaurant_name", "date", "time", "party_size"]
        missing = [k for k in required if not slots.get(k)]
        if missing:
            human_missing = {
                "restaurant_name": "restaurant name",
                "date": "date (YYYY-MM-DD, today, or tomorrow)",
                "time": "time (like 7:00 PM)",
                "party_size": "party size",
            }
            missing_text = ", ".join(human_missing[m] for m in missing)
            return (
                f"I can handle that reservation for you. I just need the {missing_text}. "
                "Please send those details and I will place it."
            )

        try:
            from app.mcp.registry import get_mcp_registry

            registry = get_mcp_registry()
            availability = await registry.call(
                server_name="concierge",
                tool_name="check_dining_availability",
                operator_id=self.context.operator_id,
                params={
                    "restaurant_name": slots["restaurant_name"],
                    "date": slots["date"],
                    "time": slots["time"],
                    "party_size": int(slots["party_size"]),
                    "area": "30A",
                },
            )
            if not availability.success:
                return (
                    "I couldn't check live availability right now. "
                    "I can still send you direct booking options if you'd like."
                )

            available_times = (
                (availability.data or {}).get("available_times") or []
            )
            if available_times:
                # If requested time isn't available, nudge alternatives first.
                requested_label = slots["time"]
                if requested_label not in available_times and f"{int(slots['time'][:2])%12 or 12}:{slots['time'][3:]} {'PM' if int(slots['time'][:2])>=12 else 'AM'}" not in available_times:
                    top = ", ".join(available_times[:3])
                    return (
                        f"I checked {slots['restaurant_name']} and the closest available times are {top}. "
                        "Reply with your preferred time and I'll book it."
                    )

            created = await registry.call(
                server_name="concierge",
                tool_name="create_dining_reservation",
                operator_id=self.context.operator_id,
                params={
                    "restaurant_name": slots["restaurant_name"],
                    "date": slots["date"],
                    "time": slots["time"],
                    "party_size": int(slots["party_size"]),
                    "guest_name": self.context.guest_name,
                    "session_token": self._session_id,
                },
            )
            if not created.success:
                return "I couldn't create that reservation yet. I can give you a direct booking link instead."

            data = created.data or {}
            if data.get("success"):
                conf = data.get("confirmation_id")
                conf_text = f" Confirmation code: {conf}." if conf else ""
                return (
                    f"You're all set at {data.get('restaurant', slots['restaurant_name'])} on "
                    f"{data.get('date', slots['date'])} at {data.get('time', slots['time'])} for "
                    f"{data.get('party_size', slots['party_size'])}.{conf_text}"
                )

            if data.get("status") == "approval_required":
                return str(data.get("message") or "Reservation request received and pending confirmation.")

            booking_url = data.get("booking_url")
            if booking_url:
                return f"I couldn't auto-confirm yet, but you can book instantly here: {booking_url}"

            return str(data.get("message") or "I couldn't complete the reservation right now.")
        except Exception as exc:
            logger.warning("[VoicePod] dining flow failed (non-fatal): %s", exc)
            return "I ran into a booking issue. I can still help with recommendations or share direct booking options."

    # ─────────────────────────────────────────────────────────────────────────
    # Librarian retrieval
    # ─────────────────────────────────────────────────────────────────────────

    async def _retrieve_context(self, message: str) -> Optional[LibrarianResponse]:
        try:
            if not self._librarian:
                self._librarian = await get_librarian_agent(self.db_session)

            query = LibrarianQuery(
                query=message,
                tenant_id=self.context.tenant_id,
                property_code=self.context.property_code,
                top_k=self.config.retrieval_top_k,
                min_score=self.config.retrieval_min_score,
            )
            return await self._librarian.retrieve(query)
        except Exception as exc:
            logger.warning("[VoicePod] Librarian retrieval failed (non-fatal): %s", exc)
            return None

    async def _load_property_basics(self):
        """Load basic property info from Librarian."""
        try:
            if not self._librarian:
                self._librarian = await get_librarian_agent(self.db_session)

            basics = await self._librarian.retrieve_property_basics(
                self.context.tenant_id,
                self.context.property_code,
            )

            if basics:
                self.context.wifi_network = basics.get("wifi_network") or self.context.wifi_network
                self.context.wifi_password = basics.get("wifi_password") or self.context.wifi_password
                self.context.door_code = basics.get("door_code") or self.context.door_code
                self.context.check_in_time = basics.get("check_in_time") or self.context.check_in_time
                self.context.check_out_time = basics.get("check_out_time") or self.context.check_out_time
                self._system_prompt = self._build_system_prompt()
        except Exception as exc:
            logger.warning("[VoicePod] _load_property_basics failed (non-fatal): %s", exc)

    # ─────────────────────────────────────────────────────────────────────────
    # Quick-answer formatting
    # ─────────────────────────────────────────────────────────────────────────

    def _format_quick_answer(
        self,
        message: str,
        answer: str,
        answer_type: Optional[str],
    ) -> str:
        if answer_type == "wifi":
            return f"📶 Here's the WiFi info: {answer}"
        elif answer_type == "door_code":
            return f"🔑 {answer}. Let me know if you have any trouble!"
        elif answer_type == "check_in":
            return f"⏰ {answer}. Can't wait to have you!"
        elif answer_type == "check_out":
            return f"⏰ {answer}. Safe travels!"
        return answer

    # ─────────────────────────────────────────────────────────────────────────
    # Escalation response
    # ─────────────────────────────────────────────────────────────────────────

    def _build_escalation_response(self, priority: str) -> str:
        support = self.context.support_phone or "(850) 733-7433"
        name = self.context.guest_name
        if priority == "urgent":
            return (
                f"I'm so sorry you're dealing with this, {name}. "
                f"This needs immediate attention — please call our emergency line right now: **{support}**. "
                f"Someone is available 24/7 and will help you right away. 🆘"
            )
        return (
            f"I'm so sorry about this issue, {name}! "
            f"I'm immediately alerting our property team — they'll be in touch very shortly. "
            f"If it's urgent, please call us directly: **{support}**."
        )

    # ─────────────────────────────────────────────────────────────────────────
    # EQ analysis
    # ─────────────────────────────────────────────────────────────────────────

    async def _run_eq_analysis(
        self,
        message: str,
        acoustic_data: Optional[Dict[str, Any]] = None,
    ) -> Optional[EmotionalContext]:
        """
        Run EQ analysis on the incoming message for tone adaptation.
        Hard escalation (CRISIS urgency) is already handled by the Router;
        this path is for subtle frustration/anger detection that shapes LLM tone.
        """
        try:
            previous_messages = [
                e["content"] for e in self._history if e["role"] == "user"
            ]
            if acoustic_data:
                eq_context = await self._eq_analyzer.analyze_combined(
                    text=message,
                    acoustic_data=acoustic_data,
                    conversation_id=self._session_id,
                )
            else:
                eq_context = await self._eq_analyzer.analyze_text(
                    text=message,
                    conversation_id=self._session_id,
                    previous_messages=previous_messages,
                )
            self._last_eq_context = eq_context

            if eq_context and eq_context.urgency_level == UrgencyLevel.CRISIS:
                logger.warning(
                    "[VoicePod] EQ-CRISIS (post-route, tone-only) session=%s state=%s",
                    self._session_id,
                    eq_context.emotional_state.value if eq_context.emotional_state else "unknown",
                )
            elif eq_context and eq_context.emotional_state in (
                EmotionalState.FRUSTRATED, EmotionalState.ANGRY
            ):
                logger.info(
                    "[VoicePod] Elevated emotion session=%s: %s",
                    self._session_id,
                    eq_context.emotional_state.value,
                )

            return eq_context
        except Exception as exc:
            logger.warning("[VoicePod] EQ analysis failed (non-fatal): %s", exc)
            return None

    # ─────────────────────────────────────────────────────────────────────────
    # LLM generation
    # ─────────────────────────────────────────────────────────────────────────

    async def _generate_response(
        self,
        user_message: str,
        context: Optional[str],
    ) -> str:
        system_content = self._system_prompt
        if self._last_eq_context:
            eq_guidance = self._last_eq_context.to_prompt_context()
            if eq_guidance:
                system_content = f"{self._system_prompt}\n\nEQ GUIDANCE:\n{eq_guidance}"

        messages = [{"role": "system", "content": system_content}]
        messages.extend(self._history[-self._max_history:])

        user_content = (
            f"CONTEXT:\n{context}\n\nGUEST: {user_message}"
            if context
            else f"GUEST: {user_message}"
        )
        messages.append({"role": "user", "content": user_content})

        return await self._call_llm(messages)

    async def _call_llm(self, messages: List[Dict[str, str]]) -> str:
        """Call LLM with Groq as primary (fast/cheap) and Gemini as fallback."""
        settings = get_settings()

        # ── Primary: Groq (llama-3.1-70b-versatile ~200ms, ~$0.0009/1k tokens) ──
        if settings.groq_api_key:
            groq_timer = LLMCallTimer()
            try:
                return await self._call_groq(messages, settings)
            except Exception as exc:
                await self._record_llm_usage(
                    provider="groq",
                    model_id=getattr(settings, "groq_model", "llama-3.1-70b-versatile"),
                    input_tokens=0,
                    output_tokens=0,
                    success=False,
                    latency_ms=groq_timer.elapsed_ms(),
                    fallback_position=1,
                    error_type=type(exc).__name__,
                )
                logger.warning("[VoicePod] Groq failed, trying Gemini: %s", exc)

        # ── Fallback: Gemini Flash ──
        if settings.gemini_api_key:
            gemini_timer = LLMCallTimer()
            try:
                return await self._call_gemini(messages, settings)
            except Exception as exc:
                model_id = self.config.model if "gemini" in self.config.model else "gemini-2.0-flash-exp"
                await self._record_llm_usage(
                    provider="gemini",
                    model_id=model_id,
                    input_tokens=0,
                    output_tokens=0,
                    success=False,
                    latency_ms=gemini_timer.elapsed_ms(),
                    fallback_position=2,
                    error_type=type(exc).__name__,
                )
                logger.warning("[VoicePod] Gemini failed: %s", exc)

        logger.error("[VoicePod] All LLM providers failed — no API keys or all errors")
        return "I'd be happy to help! Could you tell me a bit more about what you're looking for?"

    async def _call_groq(self, messages: List[Dict[str, str]], settings) -> str:
        """Groq inference — llama-3.1-70b at ~200ms P50 latency."""
        import httpx

        # Convert our internal message format (system/user/assistant) directly
        # to OpenAI-compatible format which Groq's API accepts.
        groq_messages = []
        for msg in messages:
            role = msg["role"]
            if role == "system":
                groq_messages.append({"role": "system", "content": msg["content"]})
            elif role == "user":
                groq_messages.append({"role": "user", "content": msg["content"]})
            elif role == "assistant":
                groq_messages.append({"role": "assistant", "content": msg["content"]})

        model = getattr(settings, "groq_model", "llama-3.1-70b-versatile")
        timer = LLMCallTimer()

        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.groq_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": groq_messages,
                    "max_tokens": self.config.max_tokens,
                    "temperature": self.config.temperature,
                    "stream": False,
                },
            )
        resp.raise_for_status()
        data = resp.json()
        usage = data.get("usage") or {}
        await self._record_llm_usage(
            provider="groq",
            model_id=model,
            input_tokens=int(usage.get("prompt_tokens") or 0),
            output_tokens=int(usage.get("completion_tokens") or 0),
            success=True,
            latency_ms=timer.elapsed_ms(),
            fallback_position=1,
            error_type=None,
        )
        return data["choices"][0]["message"]["content"].strip()

    async def _call_gemini(self, messages: List[Dict[str, str]], settings=None) -> str:
        """Gemini Flash fallback."""
        import google.generativeai as genai

        if settings is None:
            settings = get_settings()
        if not settings.gemini_api_key:
            raise ValueError("Gemini API key not configured")

        genai.configure(api_key=settings.gemini_api_key)
        model_name = self.config.model if "gemini" in self.config.model else "gemini-2.0-flash-exp"
        model = genai.GenerativeModel(model_name)
        timer = LLMCallTimer()

        prompt_parts = []
        for msg in messages:
            role = msg["role"]
            content = msg["content"]
            if role == "system":
                prompt_parts.append(f"INSTRUCTIONS:\n{content}\n")
            elif role == "user":
                prompt_parts.append(f"User: {content}\n")
            elif role == "assistant":
                prompt_parts.append(f"Assistant: {content}\n")
        prompt_parts.append("Assistant:")

        response = await model.generate_content_async(
            "\n".join(prompt_parts),
            generation_config={
                "max_output_tokens": self.config.max_tokens,
                "temperature": self.config.temperature,
            },
        )
        usage_metadata = getattr(response, "usage_metadata", None)
        await self._record_llm_usage(
            provider="gemini",
            model_id=model_name,
            input_tokens=int(getattr(usage_metadata, "prompt_token_count", 0) or 0),
            output_tokens=int(getattr(usage_metadata, "candidates_token_count", 0) or 0),
            success=True,
            latency_ms=timer.elapsed_ms(),
            fallback_position=2,
            error_type=None,
        )
        return response.text.strip()

    async def _record_llm_usage(
        self,
        *,
        provider: str,
        model_id: str,
        input_tokens: int,
        output_tokens: int,
        success: bool,
        latency_ms: int,
        fallback_position: int,
        error_type: Optional[str],
    ) -> None:
        await LLMUsageTracker.record(
            service_name="voice_pod",
            tenant_id=self.context.tenant_id,
            request_type="guest_session_response_generation",
            provider=provider,
            model_id=model_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            success=success,
            latency_ms=latency_ms,
            fallback_position=fallback_position,
            error_type=error_type,
            metadata={
                "property_code": self.context.property_code,
                "phase": self.context.phase.value,
                "operator_id": self.context.operator_id,
                "session_id": self._session_id,
            },
        )

    def _add_to_history(self, role: str, content: str):
        self._history.append({"role": role, "content": content})
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

    # ─────────────────────────────────────────────────────────────────────────
    # Public accessors
    # ─────────────────────────────────────────────────────────────────────────

    @property
    def emotional_context(self) -> Optional[EmotionalContext]:
        """Current EQ state — useful for analytics/dashboard."""
        return self._last_eq_context


# =============================================================================
# Factory
# =============================================================================

async def create_voice_pod(
    session: GuestSession,
    db_session: AsyncSession,
    config: Optional[VoicePodConfig] = None,
) -> VoicePod:
    """Create a Voice Pod from a guest session."""
    return await VoicePod.from_session(session, db_session, config)
