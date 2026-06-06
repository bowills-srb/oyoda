"""
agent_router.py — Topic-to-specialist dispatch for the messaging brain.

This is intentionally a small, explicit file even though the logic is tiny.
The router decides which specialist agents handle a classified message.
Putting it in its own file means:

  * Routing rules are reviewable in isolation.
  * Adding a new specialist agent requires touching exactly two places:
    (1) KNOWN_INTENT_TOPICS in messaging_brain_contracts.py
    (2) DEFAULT_TOPIC_TO_AGENTS in this file
  * The orchestrator stays focused on pipeline shape, not routing policy.

Mixed-intent handling:
  A MessageClassification can carry secondary_topics. The router fans
  out to all relevant specialists; the orchestrator runs them in order
  and lets the response composer merge their drafts.

Unknown topics:
  Topics outside KNOWN_INTENT_TOPICS resolve to ["GeneralAgent"] — the
  catch-all that defers to LLM general response. We do NOT fail closed
  here because IntakeAgent may legitimately invent a new topic before
  the router learns it (Phase 5 will add learning loops).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Sequence, Tuple

from app.services.orchestration.messaging_brain_contracts import (
    KNOWN_INTENT_TOPICS,
    MessageClassification,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Default routing table
#
# Maps intent_topic → ordered list of specialist agent names.
# Agent names are STRINGS, not classes — the orchestrator looks up
# instances from its agent registry by name. This decouples the router
# from agent construction.
#
# When adding a new specialist:
#   1. Add the topic to KNOWN_INTENT_TOPICS in messaging_brain_contracts.py
#   2. Add the topic→agent mapping here
#   3. Implement the agent class and register it on the orchestrator
#
# Phase 1 only declares the slots. Real agent classes land starting
# with MaintenanceAgent in step 1.3.
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_TOPIC_TO_AGENTS: Dict[str, Tuple[str, ...]] = {
    # Guest-initiated topics
    "access":               ("AccessAgent",),
    "maintenance":          ("MaintenanceAgent",),
    "house_rules":          ("HouseRulesAgent",),
    "local_recommendation": ("GeneralAgent",),
    "late_checkout":        ("LateCheckoutAgent",),
    "booking_inquiry":      ("BookingInquiryAgent", "PortfolioMatchingAgent"),
    "complaint":            ("EscalationAgent",),
    "emergency":            ("EscalationAgent",),
    "general":              ("GeneralAgent",),
    # System-event topics (proactive triggers)
    "system_welcome":           ("ProactiveOutreachAgent",),
    "system_pre_arrival":       ("ProactiveOutreachAgent",),
    "system_morning_brief":     ("ProactiveOutreachAgent",),
    "system_extend_stay":       ("ProactiveOutreachAgent",),
    "system_checkout_reminder": ("ProactiveOutreachAgent",),
    "system_post_stay":         ("ProactiveOutreachAgent",),
}

# Sanity check: every key in the table must be in KNOWN_INTENT_TOPICS.
# This runs at import time so a typo or drift fails loudly during tests
# instead of silently routing nothing.
_unknown_keys = set(DEFAULT_TOPIC_TO_AGENTS.keys()) - set(KNOWN_INTENT_TOPICS)
if _unknown_keys:
    raise RuntimeError(
        f"DEFAULT_TOPIC_TO_AGENTS contains topics not in KNOWN_INTENT_TOPICS: "
        f"{sorted(_unknown_keys)}. Add them to messaging_brain_contracts.py."
    )

# And the converse: every known topic should have a route, otherwise we
# can classify into a topic with no handler. We log a warning rather
# than raise — it's a soft contract during build-out.
_unrouted_topics = set(KNOWN_INTENT_TOPICS) - set(DEFAULT_TOPIC_TO_AGENTS.keys())
if _unrouted_topics:
    logger.warning(
        "[AgentRouter] Topics in KNOWN_INTENT_TOPICS lack a route in "
        "DEFAULT_TOPIC_TO_AGENTS: %s",
        sorted(_unrouted_topics),
    )


# Catch-all when classification produces an unknown topic.
FALLBACK_AGENTS: Tuple[str, ...] = ("GeneralAgent",)

_IDENTITY_FILTER_FALLBACKS: Dict[str, Tuple[str, ...]] = {
    # NOTE: "maintenance" was removed here when maintenance became notify-only
    # (operator notified on every issue; no autonomous vendor dispatch).
    # MaintenanceAgent.eligible_for_identity returns True unconditionally so
    # the identity filter never fires and this fallback is never consulted.
    #
    # FUTURE — IDENTITY PRECONDITION (deferred):
    # When autonomous vendor dispatch is built, the identity gate MUST
    # return — NOT as a routing fallback here, but as a gate INSIDE the
    # dispatch decision in MaintenanceModule: do NOT auto-dispatch a vendor
    # for a non-identity-resolved (unverified) guest. Adding it back here
    # would silently suppress MaintenanceAgent for pseudonymous guests, which
    # is the wrong behavior (we still want the operator notification and the
    # work order; we just don't auto-send a vendor without identity).
    "access": FALLBACK_AGENTS,
    "late_checkout": FALLBACK_AGENTS,
}


@dataclass
class RouteOutcome:
    """The router's decision for one classified message.

    agent_names is the ordered list of specialists the orchestrator
    will run. reason is a short audit string that ends up in
    AgentAuditRecord.notes.
    """

    agent_names: List[str]
    primary_topic: str
    secondary_topics: List[str]
    reason: str


class AgentRouter:
    """Dispatch classified messages to specialist agents.

    Stateless. Construct once and reuse.
    """

    def __init__(
        self,
        topic_to_agents: Dict[str, Tuple[str, ...]] | None = None,
        fallback: Sequence[str] = FALLBACK_AGENTS,
        confidence_threshold: float = 0.30,
    ) -> None:
        self._table = dict(topic_to_agents or DEFAULT_TOPIC_TO_AGENTS)
        self._fallback = tuple(fallback)
        self._confidence_threshold = min(max(confidence_threshold, 0.0), 1.0)

    def route(
        self,
        classification: MessageClassification,
        *,
        confidence_threshold: float | None = None,
        identity_state: str = "pseudonymous",
        specialist_lookup: Mapping[str, Any] | None = None,
    ) -> RouteOutcome:
        """Resolve a classification to an ordered list of agent names.

        Primary topic is always processed first. Secondary topics fan
        out after, with deduplication so the same agent never runs twice
        for one message.
        """
        primary = classification.intent_topic
        secondaries = list(classification.secondary_topics or [])
        threshold = (
            self._confidence_threshold
            if confidence_threshold is None
            else min(max(confidence_threshold, 0.0), 1.0)
        )

        if classification.confidence < threshold:
            ordered = list(self._fallback)
            reason = (
                f"routed via fallback {self._fallback} due to low confidence "
                f"{classification.confidence:.2f} < threshold {threshold:.2f}; "
                f"primary topic was {classification.intent_topic!r}"
            )
            return RouteOutcome(
                agent_names=ordered,
                primary_topic=primary,
                secondary_topics=secondaries,
                reason=reason,
            )

        ordered: List[str] = []
        seen: set[str] = set()
        filtered_topics: List[str] = []

        def _add_for_topic(topic: str) -> Tuple[str, ...]:
            agents = self._table.get(topic)
            if agents is None:
                logger.info(
                    "[AgentRouter] Unknown topic %r — using fallback %s",
                    topic, self._fallback,
                )
                return self._fallback
            return agents

        def _eligible(agent_name: str) -> bool:
            if specialist_lookup is None:
                return True
            agent = specialist_lookup.get(agent_name)
            if agent is None:
                return True
            checker = getattr(agent, "eligible_for_identity", None)
            if checker is None:
                return True
            try:
                return bool(checker(identity_state))
            except Exception:  # noqa: BLE001
                logger.warning(
                    "[AgentRouter] eligible_for_identity failed for %s; keeping route",
                    agent_name,
                )
                return True

        for topic in [primary, *secondaries]:
            added_for_topic = False
            for agent_name in _add_for_topic(topic):
                if not _eligible(agent_name):
                    continue
                if agent_name not in seen:
                    seen.add(agent_name)
                    ordered.append(agent_name)
                    added_for_topic = True
            if not added_for_topic:
                filtered_topics.append(topic)

        if primary in filtered_topics:
            for agent_name in _IDENTITY_FILTER_FALLBACKS.get(primary, self._fallback):
                if agent_name not in seen:
                    seen.add(agent_name)
                    ordered.append(agent_name)

        # If everything resolved to nothing (shouldn't happen given
        # fallback, but defend anyway), use the fallback chain.
        if not ordered:
            ordered = list(self._fallback)
            reason = f"no agents resolved for topic {primary!r}; using fallback"
        elif filtered_topics:
            reason = (
                f"routed primary={primary!r} with identity={identity_state!r}; "
                f"filtered topics={filtered_topics}; agents={ordered}"
            )
        elif primary in self._table:
            reason = (
                f"routed primary={primary!r} → {self._table[primary]}; "
                f"secondary={secondaries}"
            )
        else:
            reason = (
                f"primary topic {primary!r} unknown; routed via fallback "
                f"{self._fallback}; secondary={secondaries}"
            )

        return RouteOutcome(
            agent_names=ordered,
            primary_topic=primary,
            secondary_topics=secondaries,
            reason=reason,
        )

    def known_agents(self) -> List[str]:
        """All agent names referenced by the routing table.

        Useful for the orchestrator to validate at startup that every
        routed agent has been registered.
        """
        names: set[str] = set()
        for agents in self._table.values():
            names.update(agents)
        names.update(self._fallback)
        return sorted(names)
