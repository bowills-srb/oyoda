"""
maintenance_agent.py — Decision-side handler for guest maintenance reports.

Responsibilities (decision only — work happens in MaintenanceModule):
  1. Classify the issue using stable private classifiers from
     concierge/maintenance_service (re-exported via
     messaging_brain/modules/maintenance_module). Produces (category,
     severity) — e.g. ("hvac", "medium").
  2. Cite evidence from the context — only keys actually present in
     context.evidence_keys are cited. Anything cited outside that set
     is a contract violation flagged in the audit trail.
  3. Emit a ModuleEvent with the payload MaintenanceModule needs to
     write the dual-table records (concierge event + work order).

This agent NEVER writes to a database. It NEVER calls work_order_service
or concierge/maintenance_service.auto_track_from_message. That's the
module's job. The agent's contract is decision in, AgentDecision out.

See seam-map "Rule 4": modules own the work, agents own the decision.
If you find yourself adding a service call that performs a write here,
extract that into a module instead.
"""

from __future__ import annotations

import logging
from typing import Any

# Stable classifiers — re-exported from maintenance_module so the
# "intentionally reusing private helpers" comment lives in one place.
from app.services.messaging_brain.modules.maintenance_module import (
    _category_for,
    _severity_for,
)
from app.services.orchestration.messaging_brain_contracts import (
    AgentDecision,
    GuestContextBundle,
    InboundGuestMessage,
    MessageClassification,
    ModuleEvent,
    RecommendedAction,
)

logger = logging.getLogger(__name__)


# Confidence floor when we successfully classify. Below this means the
# classifier landed on the "general" fallback, which should reduce
# certainty in the policy gate.
_CONFIDENT_CATEGORY_CONF = 0.85
_FALLBACK_CATEGORY_CONF = 0.55

# Per-category response copy. Phase 4 swaps this for LLM composition.
_CATEGORY_DRAFTS: dict[str, str] = {
    "hvac": (
        "Got it — sorry about the AC. I'm getting the team on it now and "
        "they'll text you with an ETA shortly."
    ),
    "plumbing": (
        "Sorry about that — I've flagged this for the team and they'll "
        "be in touch shortly with next steps."
    ),
    "appliance": (
        "Thanks for letting us know — I've passed this to the team so "
        "they can take a look."
    ),
    "internet": (
        "Sorry about the internet trouble — I'm getting the team on it "
        "and we'll follow up with next steps."
    ),
    "access": (
        "I want to get this sorted right away — the team will reach out "
        "shortly to help with access."
    ),
    "electronics": (
        "Thanks for letting us know — passing this to the team to take "
        "a look at."
    ),
    "bike": (
        "Thanks for the heads-up on the bike — the team will follow up "
        "shortly."
    ),
    "general": (
        "Thanks for letting us know — I've passed this to the team and "
        "they'll follow up shortly."
    ),
}

# Evidence keys MaintenanceAgent looks for in context, by category.
# These are the keys MaintenanceAgent will cite IF they're present in
# context.evidence_keys. Anything not in this map is ignored.
_EVIDENCE_KEYS_BY_CATEGORY: dict[str, tuple[str, ...]] = {
    "hvac": (
        "property_facts.hvac_info",
        "property_facts.hvac_type",  # not surfaced in 1.3 but may appear in 1.4
        "property_facts.thermostat_location",  # 1.4
    ),
    "plumbing": (
        "property_facts.water_shutoff",
        "property_facts.plumbing_notes",
    ),
    "internet": (
        "property_facts.wifi",
    ),
    "access": (
        "property_facts.check_in",
        "property_facts.check_out",
    ),
}


class MaintenanceAgent:
    """Decision-side maintenance handler. Emits ModuleEvents."""

    name = "MaintenanceAgent"
    handles_topics = ("maintenance",)

    def eligible_for_identity(self, identity_state: str) -> bool:
        # notify-only: maintenance runs regardless of identity state — the
        # operator is notified on every issue regardless. No autonomous vendor
        # dispatch means there is no gate that needs the guest verified first.
        #
        # FUTURE: when autonomous vendor dispatch is added, the identity check
        # returns as a dispatch-level decision INSIDE MaintenanceModule, not
        # here. Routing should never silently swallow maintenance messages.
        return True

    async def run(
        self,
        *,
        message: InboundGuestMessage,
        classification: MessageClassification,
        context: GuestContextBundle,
        db_session: Any = None,  # unused for v1 — pure decision agent
    ) -> AgentDecision:
        """Classify the maintenance issue and emit a ModuleEvent."""
        text = message.text or ""

        category = _category_for(text)  # "hvac"|"plumbing"|...|"general"
        severity = _severity_for(text)  # "high"|"medium"|"low"

        evidence_used = self._cite_evidence(category, context)
        missing_info = self._note_missing(category, context, evidence_used)

        confidence = (
            _CONFIDENT_CATEGORY_CONF if category != "general"
            else _FALLBACK_CATEGORY_CONF
        )

        module_event = self._build_module_event(
            message=message, category=category, severity=severity,
        )

        risk_flags: list[str] = []
        if severity == "high":
            risk_flags.append("high_severity")

        return AgentDecision(
            agent_name="MaintenanceAgent",
            intent_topic="maintenance",
            confidence=confidence,
            answer_summary=(
                f"Guest reports {category} issue (severity={severity}); "
                f"emitting maintenance module event for dispatch"
            ),
            evidence_used=evidence_used,
            missing_info=missing_info,
            risk_flags=risk_flags,
            recommended_action=RecommendedAction.DRAFT_ONLY,  # operator reviews
            module_events=[module_event],
            draft_text=_CATEGORY_DRAFTS.get(category, _CATEGORY_DRAFTS["general"]),
        )

    # ── Helpers ─────────────────────────────────────────────────────────────

    @staticmethod
    def _cite_evidence(
        category: str, context: GuestContextBundle,
    ) -> list[str]:
        """Return evidence keys that are both relevant to `category` AND
        present in context.evidence_keys.

        Strict subset enforcement: only cite keys that exist in context.
        This is what prevents the "hallucinated evidence" failure mode.
        """
        relevant = _EVIDENCE_KEYS_BY_CATEGORY.get(category, ())
        available = set(context.evidence_keys or [])
        return [k for k in relevant if k in available]

    @staticmethod
    def _note_missing(
        category: str,
        context: GuestContextBundle,
        evidence_used: list[str],
    ) -> list[str]:
        """Note evidence keys we'd have liked but didn't have.

        Captures the gap for the audit trail and for downstream
        knowledge-gap learning loops. This is what makes "we should
        have known the HVAC type but didn't" surface to operators
        instead of silently degrading.
        """
        relevant = _EVIDENCE_KEYS_BY_CATEGORY.get(category, ())
        used = set(evidence_used)
        return [k for k in relevant if k not in used]

    @staticmethod
    def _build_module_event(
        message: InboundGuestMessage,
        category: str,
        severity: str,
    ) -> ModuleEvent:
        """Assemble the ModuleEvent for MaintenanceModule.

        Payload keys are stable contract — do not rename without updating
        MaintenanceModule._write_concierge_event and _write_work_order
        which read them by name.
        """
        # Cap issue_summary at 200 chars for downstream display. Full
        # text still flows via inbound persistence.
        issue_summary = (message.text or "")[:200]

        return ModuleEvent(
            module="maintenance",
            event_type=f"{category}_issue",  # matches MaintenanceModule.handles_event_types
            tenant_id=message.tenant_id,
            property_id=message.property_id,
            reservation_id=message.reservation_id,
            guest_id=message.guest_id,
            payload={
                "issue_summary": issue_summary,
                "severity": severity,
                "category": category,
                "guest_phone": message.guest_phone,
                "guest_name": message.guest_name,
                "source_channel": message.channel,
                "source_message_id": message.message_id,
                "property_code": message.property_code,
            },
        )
