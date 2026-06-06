"""
Oyvoda Staged Rollout System

Replaces the binary canary on/off with a structured progression through
testable phases. Each phase has clear entry criteria, observable success
metrics, and a specific advancement trigger.

ROLLOUT PHASES (in order):

  Phase 0: inactive
    → Properties synced from Escapia, no AI active yet
    → Entry: Escapia API key stored, first sync complete

  Phase 1: pre_booking_single
    → AI handles ONE pre-booking inquiry, with operator observing
    → Auto-send enabled, operator reviews in the activity log
    → Entry: Operator manually advances via dashboard
    → Advance criteria: 1 inquiry auto-handled, no errors, operator satisfied
    → What this tests: Escapia API connection, intent classifier, AI draft quality,
                       reply routing back to Vrbo/Airbnb

  Phase 2: pre_booking_full
    → All pre-booking inquiries handled automatically for one property
    → Entry: Pass from phase 1
    → Advance criteria: 5+ inquiries handled, >80% good (no manual overrides)
    → What this tests: Volume handling, edge cases, policy guardrails, all intent types

  Phase 3: post_booking_single
    → First confirmed booking gets full concierge session
    → Guest receives welcome message, can message in for help
    → Entry: Pass from phase 2 + first booking confirmed in Escapia
    → Advance criteria: 1 complete stay handled end-to-end (check-in → check-out)
    → What this tests: Session creation, guest journey, proactive messaging,
                       gate code delivery, escalation routing

  Phase 4: post_booking_full
    → All bookings for the canary property get full AI concierge
    → Entry: Pass from phase 3
    → Advance criteria: 3+ complete stays, >80% AI resolution, 0 critical escalations
    → What this tests: Reliability at volume, KB gap patterns, edge cases

  Phase 5: full_property
    → Property is fully live: pre-booking + post-booking + proactive briefs
    → Entry: Pass from phase 4
    → Advance criteria: 14+ days live, >75% resolution, <3 operator interventions
    → What this tests: Full production load

  Phase 6: full_operator
    → All properties for the operator are live
    → Entry: Pass from phase 5 on canary property
    → Advance: Manual operator decision

Each phase tracks:
  - entered_at
  - criteria_met_at (when the advance criteria were satisfied)
  - advanced_at (when operator actually advanced)
  - metrics snapshot at time of advancement

This gives a complete audit trail of how each operator moved through rollout.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

logger = logging.getLogger(__name__)


# =============================================================================
# PHASE DEFINITIONS
# =============================================================================

class RolloutPhase(str, Enum):
    INACTIVE               = "inactive"
    PRE_BOOKING_SINGLE     = "pre_booking_single"
    PRE_BOOKING_FULL       = "pre_booking_full"
    POST_BOOKING_SINGLE    = "post_booking_single"
    POST_BOOKING_FULL      = "post_booking_full"
    FULL_PROPERTY          = "full_property"
    FULL_OPERATOR          = "full_operator"


class ApprovalMode(str, Enum):
    """
    Controls whether the operator must approve each AI response before it
    goes out, or whether it sends automatically.

    REQUIRED  — Every AI draft is held. Operator receives an SMS/dashboard
                alert with the draft and must APPROVE, EDIT, or REJECT.
                Nothing sends without explicit action. No timeout auto-send.
                This is the default when entering any new phase.

    AUTO      — AI sends immediately when confidence >= threshold and no
                policy warnings. Low-confidence or flagged items still
                go to review. Operator can flip back to REQUIRED anytime.

    Both modes log every draft and every decision — the activity log is
    always complete regardless of mode.
    """
    REQUIRED = "required"   # Must approve before sending — default for new phases
    AUTO     = "auto"       # Send automatically when policy allows


PHASE_ORDER = [
    RolloutPhase.INACTIVE,
    RolloutPhase.PRE_BOOKING_SINGLE,
    RolloutPhase.PRE_BOOKING_FULL,
    RolloutPhase.POST_BOOKING_SINGLE,
    RolloutPhase.POST_BOOKING_FULL,
    RolloutPhase.FULL_PROPERTY,
    RolloutPhase.FULL_OPERATOR,
]

PHASE_METADATA = {
    RolloutPhase.INACTIVE: {
        "label": "Inactive",
        "description": "Properties synced. Ready to begin canary testing.",
        "what_is_live": [],
        "advance_label": "Start Pre-Booking Test",
        "default_approval_mode": None,
    },
    RolloutPhase.PRE_BOOKING_SINGLE: {
        "label": "Pre-Booking: First Inquiry",
        "description": (
            "AI drafts a response to the next pre-booking inquiry and holds it for your review. "
            "You’ll see the guest’s message and the AI draft — approve it as-is, edit it, or reject it. "
            "Once you’re comfortable, you can flip to auto-send."
        ),
        "what_is_live": ["pre_booking_ai (approval required)"],
        "advance_criteria": "1 inquiry handled (approved or auto-sent), no errors",
        "advance_label": "Advance to Full Pre-Booking",
        "min_to_advance": {"inquiries_handled": 1, "error_rate": 0.0},
        "default_approval_mode": ApprovalMode.REQUIRED,
    },
    RolloutPhase.PRE_BOOKING_FULL: {
        "label": "Pre-Booking: All Inquiries",
        "description": (
            "All pre-booking inquiries for this property go through the AI. "
            "Approval mode carries over from the previous phase — you can switch to auto anytime."
        ),
        "what_is_live": ["pre_booking_ai"],
        "advance_criteria": "5+ inquiries handled, <20% manual override rate",
        "advance_label": "Advance to Post-Booking Test",
        "min_to_advance": {"inquiries_handled": 5, "override_rate_max": 0.20},
        "default_approval_mode": ApprovalMode.REQUIRED,  # Stays required until operator flips
    },
    RolloutPhase.POST_BOOKING_SINGLE: {
        "label": "Post-Booking: First Stay",
        "description": (
            "The next confirmed booking gets a full AI concierge session. "
            "All guest messages are drafted first and held for your approval before sending. "
            "Gate codes are delivered live from Escapia on a timed window."
        ),
        "what_is_live": ["pre_booking_ai", "post_booking_ai (approval required)", "gate_codes"],
        "advance_criteria": "1 complete stay handled end-to-end (check-in to check-out)",
        "advance_label": "Advance to Full Post-Booking",
        "min_to_advance": {"complete_stays": 1, "critical_escalations": 0},
        "default_approval_mode": ApprovalMode.REQUIRED,
    },
    RolloutPhase.POST_BOOKING_FULL: {
        "label": "Post-Booking: All Stays",
        "description": "All bookings for this property have full AI concierge. Approval mode per your setting.",
        "what_is_live": ["pre_booking_ai", "post_booking_ai", "proactive_briefs", "gate_codes"],
        "advance_criteria": "3+ complete stays, >80% AI resolution, 0 critical escalations",
        "advance_label": "Advance to Full Property",
        "min_to_advance": {"complete_stays": 3, "ai_resolution_min": 0.80, "critical_escalations": 0},
        "default_approval_mode": ApprovalMode.REQUIRED,
    },
    RolloutPhase.FULL_PROPERTY: {
        "label": "Full Property Live",
        "description": "Property fully live: pre-booking + post-booking + proactive briefs + events.",
        "what_is_live": ["pre_booking_ai", "post_booking_ai", "proactive_briefs", "gate_codes", "event_intelligence"],
        "advance_criteria": "14+ days live, >75% resolution, <3 operator interventions",
        "advance_label": "Expand to All Properties",
        "min_to_advance": {"days_live": 14, "ai_resolution_min": 0.75, "operator_interventions_max": 3},
        "default_approval_mode": ApprovalMode.AUTO,  # Earned auto at this point
    },
    RolloutPhase.FULL_OPERATOR: {
        "label": "All Properties Live",
        "description": "All properties running full AI concierge.",
        "what_is_live": ["everything"],
        "advance_label": None,
        "default_approval_mode": ApprovalMode.AUTO,
    },
}


# =============================================================================
# PHASE → FEATURE FLAG MAPPING
# =============================================================================

def get_active_features(phase: RolloutPhase) -> Dict[str, bool]:
    """
    Returns the feature flags that should be active at each phase.
    This drives the feature flag service — when a property enters a phase,
    these flags are set accordingly.
    """
    flags = {
        "pre_booking_ai":      False,
        "pre_booking_single":  False,  # Single-shot mode (handled flag resets after use)
        "post_booking_ai":     False,
        "post_booking_single": False,  # Single-shot mode
        "proactive_briefs":    False,
        "gate_codes":          False,
        "event_intelligence":  False,
        "extend_stay_offers":  False,
        "vendor_marketplace":  False,
        "oyvoda_enabled":      False,
    }

    if phase == RolloutPhase.INACTIVE:
        pass  # All off

    elif phase == RolloutPhase.PRE_BOOKING_SINGLE:
        flags["oyvoda_enabled"]     = True
        flags["pre_booking_ai"]     = True
        flags["pre_booking_single"] = True  # Only handle ONE, then pause

    elif phase == RolloutPhase.PRE_BOOKING_FULL:
        flags["oyvoda_enabled"] = True
        flags["pre_booking_ai"] = True

    elif phase == RolloutPhase.POST_BOOKING_SINGLE:
        flags["oyvoda_enabled"]      = True
        flags["pre_booking_ai"]      = True
        flags["post_booking_ai"]     = True
        flags["post_booking_single"] = True  # Only the NEXT booking
        flags["gate_codes"]          = True

    elif phase == RolloutPhase.POST_BOOKING_FULL:
        flags["oyvoda_enabled"]   = True
        flags["pre_booking_ai"]   = True
        flags["post_booking_ai"]  = True
        flags["gate_codes"]       = True
        flags["proactive_briefs"] = True

    elif phase in (RolloutPhase.FULL_PROPERTY, RolloutPhase.FULL_OPERATOR):
        # Everything on
        for key in flags:
            flags[key] = True

    return flags


# =============================================================================
# ADVANCE CRITERIA EVALUATOR
# =============================================================================

class CriteriaEvaluator:
    """
    Evaluates whether a property has met the criteria to advance to the next phase.
    Reads live metrics from the DB.
    """

    async def evaluate(
        self,
        db,
        company_id: str,
        property_id: str,
        current_phase: RolloutPhase,
        phase_entered_at: datetime,
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Returns (criteria_met, metrics_dict).
        metrics_dict explains what was measured and whether each criterion passed.
        """
        since = phase_entered_at

        if current_phase == RolloutPhase.PRE_BOOKING_SINGLE:
            return await self._check_pre_booking_single(db, company_id, property_id, since)

        elif current_phase == RolloutPhase.PRE_BOOKING_FULL:
            return await self._check_pre_booking_full(db, company_id, property_id, since)

        elif current_phase == RolloutPhase.POST_BOOKING_SINGLE:
            return await self._check_post_booking_single(db, company_id, property_id, since)

        elif current_phase == RolloutPhase.POST_BOOKING_FULL:
            return await self._check_post_booking_full(db, company_id, property_id, since)

        elif current_phase == RolloutPhase.FULL_PROPERTY:
            return await self._check_full_property(db, company_id, property_id, since)

        return False, {}

    async def _check_pre_booking_single(self, db, company_id, property_id, since):
        from sqlalchemy import text
        row = await db.execute(
            text("""
                SELECT
                    COUNT(*) FILTER (WHERE status = 'replied')  AS handled,
                    COUNT(*) FILTER (WHERE status = 'error')    AS errors
                FROM pre_booking_inquiries
                WHERE company_id = :cid::uuid
                  AND property_external_id = :prop
                  AND created_at >= :since
            """),
            {"cid": company_id, "prop": property_id, "since": since},
        )
        r = row.fetchone()
        handled = r.handled or 0
        errors = r.errors or 0
        met = handled >= 1 and errors == 0
        return met, {
            "inquiries_handled": {"value": handled, "required": 1, "pass": handled >= 1},
            "errors": {"value": errors, "required": 0, "pass": errors == 0},
        }

    async def _check_pre_booking_full(self, db, company_id, property_id, since):
        from sqlalchemy import text
        row = await db.execute(
            text("""
                SELECT
                    COUNT(*) FILTER (WHERE status = 'replied')          AS auto_handled,
                    COUNT(*) FILTER (WHERE status = 'rejected'
                                       OR  status = 'edited')           AS manual_overrides,
                    COUNT(*)                                             AS total
                FROM pre_booking_inquiries
                WHERE company_id = :cid::uuid
                  AND property_external_id = :prop
                  AND created_at >= :since
            """),
            {"cid": company_id, "prop": property_id, "since": since},
        )
        r = row.fetchone()
        total = r.total or 0
        auto = r.auto_handled or 0
        overrides = r.manual_overrides or 0
        override_rate = (overrides / total) if total > 0 else 0.0
        met = auto >= 5 and override_rate <= 0.20
        return met, {
            "inquiries_handled": {"value": auto, "required": 5, "pass": auto >= 5},
            "override_rate": {"value": round(override_rate, 2), "required_max": 0.20, "pass": override_rate <= 0.20},
        }

    async def _check_post_booking_single(self, db, company_id, property_id, since):
        from sqlalchemy import text
        row = await db.execute(
            text("""
                SELECT
                    COUNT(*) FILTER (
                        WHERE check_out < CURRENT_DATE
                          AND status IN ('active', 'expired', 'closed')
                    ) AS complete_stays,
                    COUNT(*) FILTER (
                        WHERE EXISTS (
                            SELECT 1 FROM concierge_escalations e
                            WHERE e.session_token = concierge_guest_sessions.token
                              AND e.priority = 'urgent'
                        )
                    ) AS critical_escalations
                FROM concierge_guest_sessions
                WHERE company_id = :cid::uuid
                  AND property_code = :prop
                  AND created_at >= :since
            """),
            {"cid": company_id, "prop": property_id, "since": since},
        )
        r = row.fetchone()
        complete = r.complete_stays or 0
        critical = r.critical_escalations or 0
        met = complete >= 1 and critical == 0
        return met, {
            "complete_stays": {"value": complete, "required": 1, "pass": complete >= 1},
            "critical_escalations": {"value": critical, "required": 0, "pass": critical == 0},
        }

    async def _check_post_booking_full(self, db, company_id, property_id, since):
        from sqlalchemy import text
        stays_row = await db.execute(
            text("""
                SELECT COUNT(*) AS complete
                FROM concierge_guest_sessions
                WHERE company_id = :cid::uuid
                  AND property_code = :prop
                  AND check_out < CURRENT_DATE
                  AND created_at >= :since
            """),
            {"cid": company_id, "prop": property_id, "since": since},
        )
        complete = stays_row.fetchone().complete or 0

        res_row = await db.execute(
            text("""
                SELECT
                    COUNT(*) FILTER (WHERE direction='outbound')            AS total_out,
                    COUNT(*) FILTER (WHERE was_quick_answer AND direction='outbound') AS faq_hits
                FROM concierge_messages m
                JOIN concierge_guest_sessions s ON s.id = m.session_id
                WHERE s.company_id = :cid::uuid
                  AND s.property_code = :prop
                  AND m.created_at >= :since
            """),
            {"cid": company_id, "prop": property_id, "since": since},
        )
        rr = res_row.fetchone()
        total_out = rr.total_out or 0
        faq = rr.faq_hits or 0
        resolution_rate = (faq / total_out) if total_out > 0 else None

        crit_row = await db.execute(
            text("""
                SELECT COUNT(*) AS count
                FROM concierge_escalations
                WHERE property_code = :prop AND priority = 'urgent' AND created_at >= :since
            """),
            {"prop": property_id, "since": since},
        )
        critical = crit_row.fetchone().count or 0

        res_pass = resolution_rate is None or resolution_rate >= 0.80
        met = complete >= 3 and res_pass and critical == 0
        return met, {
            "complete_stays": {"value": complete, "required": 3, "pass": complete >= 3},
            "ai_resolution_rate": {
                "value": round(resolution_rate, 2) if resolution_rate else None,
                "required_min": 0.80,
                "pass": res_pass,
                "note": "Not enough data yet" if resolution_rate is None else None,
            },
            "critical_escalations": {"value": critical, "required": 0, "pass": critical == 0},
        }

    async def _check_full_property(self, db, company_id, property_id, since):
        from sqlalchemy import text
        days_live = (datetime.utcnow() - since).days

        res_row = await db.execute(
            text("""
                SELECT
                    COUNT(*) FILTER (WHERE direction='outbound')            AS total_out,
                    COUNT(*) FILTER (WHERE was_quick_answer AND direction='outbound') AS faq_hits
                FROM concierge_messages m
                JOIN concierge_guest_sessions s ON s.id = m.session_id
                WHERE s.company_id = :cid::uuid AND s.property_code = :prop AND m.created_at >= :since
            """),
            {"cid": company_id, "prop": property_id, "since": since},
        )
        rr = res_row.fetchone()
        total_out = rr.total_out or 0
        resolution_rate = (rr.faq_hits / total_out) if total_out > 0 else None

        # Operator interventions = rejected drafts + manual escalation acks
        int_row = await db.execute(
            text("""
                SELECT
                    (SELECT COUNT(*) FROM pre_booking_inquiries
                     WHERE company_id = :cid::uuid AND property_external_id = :prop
                       AND status IN ('rejected', 'edited') AND created_at >= :since)
                    +
                    (SELECT COUNT(*) FROM concierge_escalations
                     WHERE property_code = :prop AND status IN ('acknowledged', 'resolved')
                       AND created_at >= :since)
                AS interventions
            """),
            {"cid": company_id, "prop": property_id, "since": since},
        )
        interventions = int_row.fetchone().interventions or 0

        res_pass = resolution_rate is None or resolution_rate >= 0.75
        met = days_live >= 14 and res_pass and interventions <= 3
        return met, {
            "days_live": {"value": days_live, "required": 14, "pass": days_live >= 14},
            "ai_resolution_rate": {
                "value": round(resolution_rate, 2) if resolution_rate else None,
                "required_min": 0.75, "pass": res_pass,
            },
            "operator_interventions": {"value": interventions, "required_max": 3, "pass": interventions <= 3},
        }


# =============================================================================
# STAGED ROLLOUT SERVICE
# =============================================================================

class StagedRolloutService:
    """
    Manages the phased rollout for a property.

    Usage:
        svc = StagedRolloutService(db)

        # Get current phase
        phase, status = await svc.get_phase(company_id, property_id)

        # Check if criteria are met to advance
        ready, metrics = await svc.check_advance_ready(company_id, property_id)

        # Advance to the next phase
        new_phase = await svc.advance(company_id, property_id, advanced_by="operator")

        # What features are active right now?
        features = await svc.get_active_features(company_id, property_id)
    """

    def __init__(self, db):
        self.db = db
        self._evaluator = CriteriaEvaluator()

    async def get_phase(
        self,
        company_id: str,
        property_id: str,
    ) -> Tuple[RolloutPhase, Dict[str, Any]]:
        """Get current phase and its status for a property."""
        from sqlalchemy import text
        row = await self.db.execute(
            text("""
                SELECT phase, entered_at, criteria_met_at, advanced_at, metrics_snapshot
                FROM property_rollout_phases
                WHERE company_id = :cid::uuid AND property_id = :prop
                ORDER BY entered_at DESC LIMIT 1
            """),
            {"cid": company_id, "prop": property_id},
        )
        r = row.fetchone()
        if not r:
            return RolloutPhase.INACTIVE, {"entered_at": None}

        phase = RolloutPhase(r.phase)
        return phase, {
            "phase": phase.value,
            "entered_at": r.entered_at.isoformat() if r.entered_at else None,
            "criteria_met_at": r.criteria_met_at.isoformat() if r.criteria_met_at else None,
            "advanced_at": r.advanced_at.isoformat() if r.advanced_at else None,
            "metrics_at_entry": r.metrics_snapshot,
            **PHASE_METADATA.get(phase, {}),
        }

    async def check_advance_ready(
        self,
        company_id: str,
        property_id: str,
    ) -> Tuple[bool, Dict[str, Any]]:
        """Check if the current phase criteria are met and advancement is possible."""
        phase, status = await self.get_phase(company_id, property_id)
        entered_at = datetime.fromisoformat(status["entered_at"]) if status.get("entered_at") else datetime.utcnow()

        met, metrics = await self._evaluator.evaluate(
            self.db, company_id, property_id, phase, entered_at
        )

        # If just became met, record criteria_met_at
        if met and not status.get("criteria_met_at"):
            await self._mark_criteria_met(company_id, property_id)

        return met, {
            "current_phase": phase.value,
            "criteria_met": met,
            "next_phase": self._next_phase(phase).value if self._next_phase(phase) else None,
            "metrics": metrics,
        }

    async def advance(
        self,
        company_id: str,
        property_id: str,
        advanced_by: str = "operator",
        force: bool = False,
    ) -> Tuple[RolloutPhase, Dict[str, Any]]:
        """
        Advance to the next rollout phase.

        By default, requires criteria to be met first.
        set force=True to skip criteria check (admin use only).
        """
        phase, status = await self.get_phase(company_id, property_id)
        entered_at = datetime.fromisoformat(status["entered_at"]) if status.get("entered_at") else datetime.utcnow()

        if not force:
            met, metrics = await self._evaluator.evaluate(
                self.db, company_id, property_id, phase, entered_at
            )
            if not met:
                return phase, {"error": "Criteria not yet met", "metrics": metrics}

        next_phase = self._next_phase(phase)
        if not next_phase:
            return phase, {"error": "Already at final phase"}

        # Record advancement
        await self._record_phase_entry(company_id, property_id, phase, next_phase, advanced_by)

        # Apply feature flags for new phase
        await self._apply_phase_flags(company_id, property_id, next_phase)

        # Reset approval mode to the new phase's default
        # (REQUIRED for all early phases — operator flips to AUTO when ready)
        new_phase_default = PHASE_METADATA.get(next_phase, {}).get(
            "default_approval_mode", ApprovalMode.REQUIRED
        )
        if new_phase_default:
            await self.set_approval_mode(
                company_id, property_id, new_phase_default, set_by="phase_transition"
            )

        logger.info(
            f"[Rollout] {property_id} advanced: {phase.value} → {next_phase.value} by {advanced_by} "
            f"| approval_mode={new_phase_default.value if new_phase_default else 'unchanged'}"
        )

        return next_phase, {
            "previous_phase": phase.value,
            "new_phase": next_phase.value,
            "features_activated": [k for k, v in get_active_features(next_phase).items() if v],
            "advanced_by": advanced_by,
            "advanced_at": datetime.utcnow().isoformat(),
            "approval_mode": new_phase_default.value if new_phase_default else "required",
            "approval_mode_note": (
                "Approval required by default — flip to auto when you’re comfortable with the AI responses."
                if new_phase_default == ApprovalMode.REQUIRED
                else "Auto-send active."
            ),
        }

    async def initialize_property(
        self,
        company_id: str,
        property_id: str,
    ) -> None:
        """
        Initialize a property's rollout state to INACTIVE.
        Called when a new property is synced from Escapia.
        """
        from sqlalchemy import text
        try:
            await self.db.execute(
                text("""
                    INSERT INTO property_rollout_phases
                        (company_id, property_id, phase, entered_at, created_at)
                    VALUES
                        (:cid::uuid, :prop, 'inactive', NOW(), NOW())
                    ON CONFLICT (company_id, property_id) DO NOTHING
                """),
                {"cid": company_id, "prop": property_id},
            )
            await self.db.commit()
        except Exception as e:
            logger.warning(f"[Rollout] init_property failed for {property_id}: {e}")

    async def get_approval_mode(
        self,
        company_id: str,
        property_id: str,
    ) -> ApprovalMode:
        """
        Get the current approval mode for a property.
        Checks property-level setting first, falls back to phase default.
        """
        from sqlalchemy import text
        try:
            row = await self.db.execute(
                text("""
                    SELECT approval_mode
                    FROM property_rollout_phases
                    WHERE company_id = :cid::uuid AND property_id = :prop
                    LIMIT 1
                """),
                {"cid": company_id, "prop": property_id},
            )
            r = row.fetchone()
            if r and r.approval_mode:
                return ApprovalMode(r.approval_mode)
        except Exception:
            pass
        # Fall back to phase default
        phase, _ = await self.get_phase(company_id, property_id)
        default = PHASE_METADATA.get(phase, {}).get("default_approval_mode")
        return default or ApprovalMode.REQUIRED

    async def set_approval_mode(
        self,
        company_id: str,
        property_id: str,
        mode: ApprovalMode,
        set_by: str = "operator",
    ) -> bool:
        """
        Set the approval mode for a property.
        Called when the operator flips the toggle in the dashboard.

        REQUIRED → every draft is held for review
        AUTO     → send when confidence + policy clear, review the rest
        """
        from sqlalchemy import text
        try:
            await self.db.execute(
                text("""
                    UPDATE property_rollout_phases
                    SET approval_mode = :mode,
                        approval_mode_set_by = :by,
                        approval_mode_set_at = NOW()
                    WHERE company_id = :cid::uuid AND property_id = :prop
                """),
                {"mode": mode.value, "by": set_by, "cid": company_id, "prop": property_id},
            )
            await self.db.commit()
            logger.info(f"[Rollout] Approval mode set to {mode.value} for {property_id} by {set_by}")
            return True
        except Exception as e:
            logger.error(f"[Rollout] set_approval_mode failed: {e}")
            return False

    async def get_active_feature_flags(
        self,
        company_id: str,
        property_id: str,
    ) -> Dict[str, bool]:
        """Get the feature flags currently active for a property based on its phase."""
        phase, _ = await self.get_phase(company_id, property_id)
        return get_active_features(phase)

    async def get_operator_rollout_summary(
        self,
        company_id: str,
    ) -> Dict[str, Any]:
        """
        Get rollout status for all properties under an operator.
        Used in the operator dashboard Rollout tab.
        """
        from sqlalchemy import text
        rows = await self.db.execute(
            text("""
                SELECT
                    p.property_id,
                    l.property_name,
                    l.city,
                    l.bedrooms,
                    p.phase,
                    p.entered_at,
                    p.criteria_met_at,
                    p.advanced_at
                FROM property_rollout_phases p
                JOIN pms_listings l
                    ON l.external_id = p.property_id
                    AND l.company_id = p.company_id
                WHERE p.company_id = :cid::uuid
                ORDER BY
                    CASE p.phase
                        WHEN 'full_operator'       THEN 7
                        WHEN 'full_property'       THEN 6
                        WHEN 'post_booking_full'   THEN 5
                        WHEN 'post_booking_single' THEN 4
                        WHEN 'pre_booking_full'    THEN 3
                        WHEN 'pre_booking_single'  THEN 2
                        WHEN 'inactive'            THEN 1
                        ELSE 0
                    END DESC,
                    l.property_name
            """),
            {"cid": company_id},
        )
        all_rows = rows.fetchall()
        phase_counts = {}
        for r in all_rows:
            phase_counts[r.phase] = phase_counts.get(r.phase, 0) + 1

        return {
            "company_id": company_id,
            "total_properties": len(all_rows),
            "phase_distribution": phase_counts,
            "properties": [
                {
                    "property_id": r.property_id,
                    "property_name": r.property_name,
                    "city": r.city,
                    "bedrooms": r.bedrooms,
                    "phase": r.phase,
                    "phase_label": PHASE_METADATA.get(RolloutPhase(r.phase), {}).get("label", r.phase),
                    "what_is_live": PHASE_METADATA.get(RolloutPhase(r.phase), {}).get("what_is_live", []),
                    "entered_at": r.entered_at.isoformat() if r.entered_at else None,
                    "criteria_met": r.criteria_met_at is not None,
                    "advance_label": PHASE_METADATA.get(RolloutPhase(r.phase), {}).get("advance_label"),
                }
                for r in all_rows
            ],
        }

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _next_phase(self, current: RolloutPhase) -> Optional[RolloutPhase]:
        idx = PHASE_ORDER.index(current)
        if idx + 1 < len(PHASE_ORDER):
            return PHASE_ORDER[idx + 1]
        return None

    async def _record_phase_entry(
        self,
        company_id: str,
        property_id: str,
        from_phase: RolloutPhase,
        to_phase: RolloutPhase,
        advanced_by: str,
    ) -> None:
        from sqlalchemy import text
        now = datetime.utcnow()
        # Mark previous phase as advanced
        await self.db.execute(
            text("""
                UPDATE property_rollout_phases
                SET advanced_at = :now, advanced_by = :by
                WHERE company_id = :cid::uuid AND property_id = :prop AND phase = :from_phase
            """),
            {"now": now, "by": advanced_by, "cid": company_id, "prop": property_id, "from_phase": from_phase.value},
        )
        # Insert new phase record
        await self.db.execute(
            text("""
                INSERT INTO property_rollout_phases
                    (company_id, property_id, phase, entered_at, created_at)
                VALUES (:cid::uuid, :prop, :phase, :now, :now)
                ON CONFLICT (company_id, property_id)
                DO UPDATE SET phase = EXCLUDED.phase, entered_at = EXCLUDED.entered_at
            """),
            {"cid": company_id, "prop": property_id, "phase": to_phase.value, "now": now},
        )
        await self.db.commit()

    async def _apply_phase_flags(
        self,
        company_id: str,
        property_id: str,
        phase: RolloutPhase,
    ) -> None:
        """Apply the feature flags corresponding to the new phase."""
        from sqlalchemy import text
        flags = get_active_features(phase)
        now = datetime.utcnow()
        for flag_name, enabled in flags.items():
            await self.db.execute(
                text("""
                    INSERT INTO operator_feature_flags
                        (id, company_id, property_code, flag_name, enabled, enabled_at, enabled_by, notes, created_at)
                    VALUES
                        (gen_random_uuid(), :cid::uuid, :prop, :flag, :enabled, :now,
                         'rollout_system', :notes, :now)
                    ON CONFLICT (company_id, property_code, flag_name)
                    DO UPDATE SET enabled = EXCLUDED.enabled, enabled_at = EXCLUDED.enabled_at,
                                  notes = EXCLUDED.notes
                """),
                {
                    "cid": company_id, "prop": property_id, "flag": flag_name,
                    "enabled": enabled, "now": now,
                    "notes": f"Phase: {phase.value}",
                },
            )
        await self.db.commit()
        logger.info(f"[Rollout] Applied {len(flags)} flags for {property_id} at phase {phase.value}")

    async def _mark_criteria_met(self, company_id: str, property_id: str) -> None:
        from sqlalchemy import text
        await self.db.execute(
            text("""
                UPDATE property_rollout_phases
                SET criteria_met_at = NOW()
                WHERE company_id = :cid::uuid AND property_id = :prop
                  AND criteria_met_at IS NULL
            """),
            {"cid": company_id, "prop": property_id},
        )
        await self.db.commit()


# =============================================================================
# SINGLETON
# =============================================================================

def get_rollout_service(db) -> StagedRolloutService:
    return StagedRolloutService(db)


# =============================================================================
# DB MIGRATION
# =============================================================================

MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS property_rollout_phases (
    id              UUID DEFAULT gen_random_uuid(),
    company_id      UUID NOT NULL,
    property_id     TEXT NOT NULL,
    phase           TEXT NOT NULL DEFAULT 'inactive',

    -- Approval mode: 'required' (hold all drafts) | 'auto' (send when policy clears)
    -- Defaults to 'required' on each new phase — operator explicitly flips to 'auto'
    approval_mode           TEXT NOT NULL DEFAULT 'required',
    approval_mode_set_by    TEXT,
    approval_mode_set_at    TIMESTAMPTZ,

    entered_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    criteria_met_at TIMESTAMPTZ,           -- When criteria were first satisfied
    advanced_at     TIMESTAMPTZ,           -- When operator actually advanced
    advanced_by     TEXT,                  -- 'operator' | 'admin' | 'auto'
    metrics_snapshot JSONB,                -- Snapshot of metrics at entry

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- One active phase record per property
    CONSTRAINT uq_property_rollout UNIQUE (company_id, property_id)
);

CREATE INDEX IF NOT EXISTS idx_rollout_company
    ON property_rollout_phases (company_id, phase);

-- If table already exists, add columns
ALTER TABLE property_rollout_phases
    ADD COLUMN IF NOT EXISTS approval_mode        TEXT NOT NULL DEFAULT 'required',
    ADD COLUMN IF NOT EXISTS approval_mode_set_by TEXT,
    ADD COLUMN IF NOT EXISTS approval_mode_set_at TIMESTAMPTZ;

-- Phase history log (full audit trail)
CREATE TABLE IF NOT EXISTS property_rollout_history (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id      UUID NOT NULL,
    property_id     TEXT NOT NULL,
    from_phase      TEXT,
    to_phase        TEXT NOT NULL,
    advanced_by     TEXT,
    approval_mode   TEXT,
    metrics_at_time JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""
