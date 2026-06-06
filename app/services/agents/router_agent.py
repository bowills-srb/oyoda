"""
Router / Supervisor Agent

Sits in front of VoicePod and makes the first routing decision for every
guest message.  Rather than an implicit sequential chain of `if` checks
buried inside respond(), this is an explicit, named, logged policy gate.

Routing decisions (in priority order):
  1. ESCALATE_URGENT   — safety/emergency keywords → human NOW, no LLM
  2. ESCALATE_HIGH     — maintenance/complaint keywords → human soon, no LLM
  3. QUICK_ANSWER      — WiFi/door/times → templated answer, no LLM
  4. PMS_QUERY         — reservation/booking question → PMS MCP lookup
  5. KNOWLEDGE_LOOKUP  — property/local/rules question → Librarian RAG
  6. LLM_GENERAL       — everything else → Gemini generation
  7. EQ_CRISIS_GATE    — emotional-state crisis (no hard keyword) → human

Each route is logged to the Watch Layer so you can see exactly why every
message was routed where it was.  This is the audit trail that makes
escalation a metric rather than just a safety feature.

Usage:
    router = ConciergeRouter(context, eq_analyzer, watch)
    decision = await router.route(user_message, conversation_turns)
    # decision.route, decision.reason, decision.metadata
"""

import asyncio
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _normalize_text(text: str) -> str:
    """Lowercase text and collapse punctuation/whitespace for safe matching."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text.lower())).strip()


def _keyword_matches_text(keyword: str, text: str) -> bool:
    """
    Match a keyword against free text without substring false positives.

    Single words require word boundaries so `ants` does not match
    `restaurants`. Multi-word phrases use normalized boundary-aware
    matching so punctuation variations still match.
    """
    normalized_keyword = _normalize_text(keyword)
    normalized_text = _normalize_text(text)
    if not normalized_keyword or not normalized_text:
        return False
    if " " in normalized_keyword:
        pattern = r"\b" + r"\s+".join(
            rf"{re.escape(part)}[a-z0-9]*" for part in normalized_keyword.split()
        ) + r"\b"
        return bool(re.search(pattern, normalized_text))
    return bool(re.search(rf"\b{re.escape(normalized_keyword)}[a-z0-9]*\b", normalized_text))


def _first_matching_keyword(text: str, keywords: frozenset[str]) -> Optional[str]:
    """Return the first keyword that matches text, preferring longer phrases."""
    for keyword in sorted(keywords, key=lambda value: (-len(value), value)):
        if _keyword_matches_text(keyword, text):
            return keyword
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Route enum
# ─────────────────────────────────────────────────────────────────────────────

class Route(str, Enum):
    ESCALATE_URGENT   = "escalate_urgent"    # emergency — human NOW
    ESCALATE_HIGH     = "escalate_high"      # maintenance/complaint — human soon
    ESCALATE_EQ       = "escalate_eq"        # EQ-detected crisis — human soon
    QUICK_ANSWER      = "quick_answer"       # templated, zero LLM
    PMS_QUERY         = "pms_query"          # booking/reservation lookup
    KNOWLEDGE_LOOKUP  = "knowledge_lookup"   # Librarian RAG
    LLM_GENERAL       = "llm_general"        # Gemini generation


# ─────────────────────────────────────────────────────────────────────────────
# Routing decision
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class RoutingDecision:
    route: Route
    reason: str                             # human-readable, logged to Watch
    trigger: Optional[str] = None           # matched keyword or intent
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_escalation(self) -> bool:
        return self.route in (Route.ESCALATE_URGENT, Route.ESCALATE_HIGH, Route.ESCALATE_EQ)

    @property
    def priority(self) -> Optional[str]:
        if self.route == Route.ESCALATE_URGENT:
            return "urgent"
        if self.route in (Route.ESCALATE_HIGH, Route.ESCALATE_EQ):
            return "high"
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Keyword sets (single source of truth — referenced by tests too)
# ─────────────────────────────────────────────────────────────────────────────

ESCALATION_URGENT: frozenset = frozenset({
    "emergency", "911", "fire", "flood", "gas leak", "gas smell",
    # Keep injury triggers phrase-based so polite idioms like
    # "it doesn't hurt to ask" do not escalate to life-safety.
    "i am hurt", "i'm hurt", "got hurt", "is hurt", "injured",
    "ambulance", "locked out", "no power", "no water",
    "water everywhere", "someone broke in",
})

ESCALATION_HIGH: frozenset = frozenset({
    "broken", "not working", "doesn't work", "stopped working",
    "leak", "leaking", "water damage", "mold", "sewage",
    "ac not working", "no air conditioning", "no heat",
    "too hot", "too cold", "pest", "bugs", "roaches", "ants",
    "dirty", "filthy", "disgusting", "unacceptable",
    "refund", "compensation", "money back",
})

PMS_KEYWORDS: frozenset = frozenset({
    "booking", "reservation", "confirmation", "check-in date", "check-out date",
    "how long", "how many nights", "my booking", "my reservation",
    "arrival date", "departure date", "extend my stay", "extra night",
    "late checkout", "early check-in",
})

KNOWLEDGE_KEYWORDS: frozenset = frozenset({
    "restaurant", "eat", "food", "dining", "breakfast", "lunch", "dinner",
    "coffee", "bar", "seafood", "pizza", "recommend", "where to",
    "activity", "activities", "things to do", "fun", "beach chair",
    "umbrella", "kayak", "paddleboard", "bike", "rental",
    "near", "nearby", "around", "local", "grocery", "store", "pharmacy",
    "hospital", "urgent care",
    "pool", "hot tub", "grill", "parking", "trash", "towel",
    "rule", "pet", "smoke", "amenity", "amenities", "house rules",
    "can i", "is there", "do you have",
})

QUICK_ANSWER_KEYWORDS: frozenset = frozenset({
    "wifi", "wi-fi", "internet", "password", "network",
    "door", "door code", "code", "access", "get in", "key",
    "check-in time", "check-out time", "checkout time", "checkin time",
    "what time", "when do i",
})


# ─────────────────────────────────────────────────────────────────────────────
# Router
# ─────────────────────────────────────────────────────────────────────────────

class ConciergeRouter:
    """
    Explicit routing policy for every guest message.

    All routing decisions are logged to the Watch Layer so escalation rates,
    quick-answer hit rates, and retrieval rates are observable SLOs.
    """

    def __init__(
        self,
        context,                   # VoicePodContext (or any object with property_code/guest_name)
        eq_analyzer=None,          # EQAnalyzer — optional; skip EQ gate if not provided
        watch=None,                # WatchLayer — optional; decisions still work without it
        session_id: str = "unknown",
    ) -> None:
        self._ctx = context
        self._eq = eq_analyzer
        self._watch = watch
        self._session_id = session_id

    async def route(
        self,
        message: str,
        conversation_turns: int = 0,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> RoutingDecision:
        """
        Determine the routing policy for this message.

        Steps (in strict priority order):
          0. Keyword escalation gate (urgent)
          1. Keyword escalation gate (high)
          2. Quick-answer detection
          3. PMS intent detection
          4. Knowledge / Librarian intent detection
          5. Long-conversation escalation (>= 6 turns)
          6. LLM general fallback
          7. [Async] EQ-crisis second pass (fires in parallel with steps 3-6)
        """
        # 0. Urgent escalation — runs synchronously, no I/O
        kw = _first_matching_keyword(message, ESCALATION_URGENT)
        if kw:
            decision = RoutingDecision(
                route=Route.ESCALATE_URGENT,
                reason=f"Urgent keyword matched: '{kw}'",
                trigger=kw,
                metadata={"priority": "urgent"},
            )
            logger.info(
                "[router] escalation route=%s trigger=%r priority=%s preview=%r",
                decision.route.value,
                decision.trigger,
                decision.priority,
                message[:160],
            )
            await self._log(message, decision)
            return decision

        # 1. High escalation — synchronous
        kw = _first_matching_keyword(message, ESCALATION_HIGH)
        if kw:
            decision = RoutingDecision(
                route=Route.ESCALATE_HIGH,
                reason=f"High-priority keyword matched: '{kw}'",
                trigger=kw,
                metadata={"priority": "high"},
            )
            logger.info(
                "[router] escalation route=%s trigger=%r priority=%s preview=%r",
                decision.route.value,
                decision.trigger,
                decision.priority,
                message[:160],
            )
            await self._log(message, decision)
            return decision

        # 2. Quick answer — synchronous
        kw = _first_matching_keyword(message, QUICK_ANSWER_KEYWORDS)
        if kw:
            decision = RoutingDecision(
                route=Route.QUICK_ANSWER,
                reason=f"Quick-answer keyword matched: '{kw}'",
                trigger=kw,
            )
            await self._log(message, decision)
            return decision

        # 3. PMS query — synchronous keyword check
        kw = _first_matching_keyword(message, PMS_KEYWORDS)
        if kw:
            decision = RoutingDecision(
                route=Route.PMS_QUERY,
                reason=f"PMS/booking keyword matched: '{kw}'",
                trigger=kw,
            )
            await self._log(message, decision)
            return decision

        # 4. Knowledge/Librarian query — synchronous keyword check
        kw = _first_matching_keyword(message, KNOWLEDGE_KEYWORDS)
        if kw:
            decision = RoutingDecision(
                route=Route.KNOWLEDGE_LOOKUP,
                reason=f"Knowledge keyword matched: '{kw}'",
                trigger=kw,
            )
            await self._log(message, decision)
            return decision

        # 5. Long-conversation escalation
        if conversation_turns >= 6:
            decision = RoutingDecision(
                route=Route.ESCALATE_HIGH,
                reason=f"Conversation length ({conversation_turns} turns) — guest may need human",
                trigger="conversation_length",
                metadata={"priority": "high", "turns": conversation_turns},
            )
            await self._log(message, decision)
            return decision

        # 6. EQ-crisis check (async, only if EQ analyzer is available)
        if self._eq is not None:
            try:
                previous = [e["content"] for e in (history or []) if e.get("role") == "user"]
                eq_ctx = await self._eq.analyze_text(
                    text=message,
                    conversation_id=self._session_id,
                    previous_messages=previous,
                )
                if eq_ctx is not None:
                    from app.services.agents.emotional_intelligence.eq_analyzer import UrgencyLevel
                    if getattr(eq_ctx, "urgency_level", None) == UrgencyLevel.CRISIS:
                        decision = RoutingDecision(
                            route=Route.ESCALATE_EQ,
                            reason="EQ-detected crisis — no hard keyword match",
                            trigger="eq_crisis",
                            metadata={
                                "priority": "high",
                                "emotional_state": getattr(eq_ctx, "emotional_state", {}).value
                                if hasattr(getattr(eq_ctx, "emotional_state", None), "value")
                                else str(getattr(eq_ctx, "emotional_state", "unknown")),
                            },
                        )
                        logger.info(
                            "[router] escalation route=%s trigger=%r priority=%s preview=%r",
                            decision.route.value,
                            decision.trigger,
                            decision.priority,
                            message[:160],
                        )
                        await self._log(message, decision)
                        return decision
            except Exception as exc:
                logger.warning("[router] EQ analysis failed (non-fatal): %s", exc)

        # 7. General LLM fallback
        decision = RoutingDecision(
            route=Route.LLM_GENERAL,
            reason="No specific intent matched — LLM general response",
        )
        await self._log(message, decision)
        return decision

    async def _log(self, message: str, decision: RoutingDecision) -> None:
        """Fire-and-forget Watch Layer log of the routing decision."""
        if self._watch is None:
            return
        try:
            asyncio.ensure_future(
                self._watch.log_routing_decision(
                    session_id=self._session_id,
                    operator_id=getattr(self._ctx, "operator_id", "unknown"),
                    property_code=getattr(self._ctx, "property_code", "unknown"),
                    message_preview=message[:80],
                    route=decision.route.value,
                    reason=decision.reason,
                    trigger=decision.trigger,
                    metadata=decision.metadata,
                )
            )
        except Exception as exc:
            logger.debug("[router] Watch log failed (non-fatal): %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# Factory
# ─────────────────────────────────────────────────────────────────────────────

def get_concierge_router(
    context,
    eq_analyzer=None,
    watch=None,
    session_id: str = "unknown",
) -> ConciergeRouter:
    return ConciergeRouter(
        context=context,
        eq_analyzer=eq_analyzer,
        watch=watch,
        session_id=session_id,
    )
