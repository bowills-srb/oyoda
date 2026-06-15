"""
autonomy_gate.py — Per-property AI autonomy decision layer.

This sits between the draft generator and the send-or-review decision. It
answers one question: "should this AI draft auto-send, or go to review?"

Inputs:
  - property_id (may be None for unresolved pre-booking inquiries)
  - tenant_id
  - draft confidence score
  - list of policy warnings
  - whether the inbound message triggered an escalation

Output:
  - AutonomyDecision.AUTO_SEND — ship it
  - AutonomyDecision.REVIEW    — queue for operator review
  - AutonomyDecision.BLOCKED_BY_ESCALATION — queue, and mark why

Design notes:
  1. Reads property_ai_autonomy from migration 027. Falls back to the
     safest default (REVIEW) if no row exists — operators opt INTO auto
     mode, never opt out.

  2. Escalations override everything. If the inbound message triggered an
     escalation (damage claim, refund request, AI uncertainty, playbook
     flag, whatever), the draft is held regardless of confidence. The
     operator handles it through the escalation workflow.

  3. Policy warnings still block auto-send. They did before and they do
     now; the new thing is the property-level toggle that gates even
     "clean" drafts.

  4. This gate is the autonomy decision layer for the messaging-brain
     pathway (migration 027 unified messaging). The old
     pre_booking_auto_send.py has been REMOVED (only orphan .pyc cache
     remains); do not reference it.

     ESCALATION OVERRIDE — where it lives: the brain's authoritative
     "escalations override everything" rule is enforced in
     ResponsePolicyAgent.evaluate (see _detect_escalation), which forces
     ESCALATE from the specialist AgentDecision risk_flags
     (escalation_emergency is an absolute hard-stop) BEFORE this gate is
     consulted. That is the sole binding mechanism on the brain path. This
     gate does NOT look up any escalation table. (The former
     check_blocking_escalation row-lookup against conversation_escalations
     was removed: nothing populated that table on the brain path, and the
     live concierge escalation writer in concierge/escalation_service.py is
     a separate session-path system that writes concierge_escalations with
     no shared message-id key — so the lookup bridged nothing.)

  5. Playbook evaluation happens BEFORE autonomy gating. If a playbook
     triggered (e.g. "unbooked checkout — offer extension discount"),
     the playbook sets draft.playbook_triggered and its context carries
     a recommendation. Autonomy still has the final say — a playbook
     suggesting an offer can still be gated to REVIEW if the property
     isn't on auto mode.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class AutonomyDecision(str, Enum):
    AUTO_SEND              = "auto_send"
    REVIEW                 = "review"
    BLOCKED_BY_ESCALATION  = "blocked_by_escalation"


@dataclass
class AutonomySettings:
    """Resolved per-property autonomy settings. Source: property_ai_autonomy."""
    approval_mode: str                    # "required" or "auto"
    min_confidence_for_auto: float        # threshold when approval_mode is "auto"
    stage: str                            # which stage this setting applies to
    source: str                           # "property_row" | "default"

    @classmethod
    def safe_default(cls) -> "AutonomySettings":
        """Used when no property row exists. Always REVIEW."""
        return cls(
            approval_mode="required",
            min_confidence_for_auto=0.95,
            stage="all",
            source="default",
        )


@dataclass
class GateResult:
    decision: AutonomyDecision
    reason: str                                   # human-readable, shown to operator
    approval_mode_at_decision: str                # captured for draft.approval_mode audit
    blocking_escalation_id: Optional[UUID] = None


async def resolve_autonomy_settings(
    db: AsyncSession,
    property_id: Optional[UUID],
    stage: str,
) -> AutonomySettings:
    """
    Look up the operative autonomy settings for (property_id, stage).

    Preference order:
      1. Exact row for (property_id, stage)
      2. Fallback to (property_id, stage='all') — the MVP shape
      3. Safe default (REVIEW) if neither exists

    property_id=None (pre-booking inquiry with no resolved property) always
    returns the safe default — operators should never auto-send for
    unresolved properties.
    """
    if property_id is None:
        return AutonomySettings.safe_default()

    # Try exact stage match first
    row = (await db.execute(
        text("""
            SELECT approval_mode, min_confidence_for_auto, stage
            FROM property_ai_autonomy
            WHERE property_id = :pid AND stage = :stage
            LIMIT 1
        """),
        {"pid": str(property_id), "stage": stage},
    )).fetchone()

    if row:
        return AutonomySettings(
            approval_mode=row[0],
            min_confidence_for_auto=float(row[1]),
            stage=row[2],
            source="property_row",
        )

    # Fall back to the 'all' stage row (MVP shape: one row per property)
    row = (await db.execute(
        text("""
            SELECT approval_mode, min_confidence_for_auto, stage
            FROM property_ai_autonomy
            WHERE property_id = :pid AND stage = 'all'
            LIMIT 1
        """),
        {"pid": str(property_id)},
    )).fetchone()

    if row:
        return AutonomySettings(
            approval_mode=row[0],
            min_confidence_for_auto=float(row[1]),
            stage="all",
            source="property_row",
        )

    return AutonomySettings.safe_default()


# Readiness bands (from operator_property_autonomy_snapshots.inquiry_band, computed
# by autonomy_score_service) that are mature enough to allow auto-send. Anything
# below this — "Emerging" / "Insufficient Signal" — caps a property to REVIEW even
# when the operator has toggled auto mode on. This is how knowledge readiness
# gates autonomy: a property graduates to auto-send only once its documented
# coverage is good enough. Absence of any snapshot is NOT treated as a failure
# (no cap), so this can only ever make auto-send more conservative, never less.
_AUTO_READINESS_BANDS = {"developing", "autonomous"}


async def _latest_property_readiness_band(
    db: AsyncSession,
    property_id: Optional[UUID],
) -> Optional[str]:
    """Most recent computed inquiry-readiness band for a property, or None.

    Reads the latest operator_property_autonomy_snapshots row. Defensive: any
    error (missing table, bad row) returns None so the gate never crashes and
    simply skips the cap.
    """
    if property_id is None:
        return None
    try:
        row = (await db.execute(
            text("""
                SELECT inquiry_band
                FROM operator_property_autonomy_snapshots
                WHERE property_id = :pid
                ORDER BY snapshot_date DESC
                LIMIT 1
            """),
            {"pid": str(property_id)},
        )).fetchone()
        # Only treat a genuine string as a band — guards against mocked DB
        # sessions in unit tests and any non-text row value.
        return row[0] if (row and isinstance(row[0], str)) else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("[AutonomyGate] readiness-band lookup failed (skipping cap): %s", exc)
        try:
            await db.rollback()
        except Exception:
            pass
        return None


async def evaluate(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    property_id: Optional[UUID],
    stage: str,
    confidence: float,
    policy_warnings: list,
) -> GateResult:
    """
    The main entry point. Decides whether this draft auto-sends or waits.

    Call this after the draft generator produces draft_text + confidence.

    Returns a GateResult that tells the caller:
      - What to set draft.status to (auto_sent | pending_review)
      - What to set draft.approval_mode to (required | auto) — captured at
        decision time for audit
      - Why the decision was made (for operator UI + logs)

    NOTE: escalation override is NOT enforced here. The brain's
    authoritative "escalations override everything" rule lives in
    ResponsePolicyAgent._detect_escalation, which forces ESCALATE from the
    specialist AgentDecision risk_flags BEFORE this gate is consulted. The
    old conversation_escalations row-lookup was removed: nothing populated
    that table on the brain path, and the live concierge escalation writer
    (concierge/escalation_service.py) is a separate session-path system
    with no shared message-id key. See note 4 in the module docstring.
    """

    # --- Step 1: look up per-property autonomy ---
    settings = await resolve_autonomy_settings(db, property_id, stage)

    # --- Step 2: policy warnings block auto-send regardless of mode ---
    if policy_warnings:
        return GateResult(
            decision=AutonomyDecision.REVIEW,
            reason=(
                f"Policy check flagged {len(policy_warnings)} warning(s) — review draft."
            ),
            approval_mode_at_decision=settings.approval_mode,
        )

    # --- Step 3: if operator hasn't opted in, always review ---
    if settings.approval_mode != "auto":
        reason = (
            "Review mode (default)"
            if settings.source == "default"
            else f"Review mode (property setting, stage={settings.stage})"
        )
        return GateResult(
            decision=AutonomyDecision.REVIEW,
            reason=reason,
            approval_mode_at_decision=settings.approval_mode,
        )

    # --- Step 4: confidence check for auto mode ---
    if confidence < settings.min_confidence_for_auto:
        return GateResult(
            decision=AutonomyDecision.REVIEW,
            reason=(
                f"Auto mode on, but confidence {confidence:.2f} is below "
                f"threshold {settings.min_confidence_for_auto:.2f}."
            ),
            approval_mode_at_decision="auto",
        )

    # --- Step 4.5: knowledge-readiness cap ---
    # Even on auto mode with sufficient confidence, a property only auto-sends
    # once its documented coverage is mature. If the latest computed readiness
    # band is below "Developing", hold for review. No snapshot → no cap.
    band = await _latest_property_readiness_band(db, property_id)
    if band is not None and band.strip().lower() not in _AUTO_READINESS_BANDS:
        return GateResult(
            decision=AutonomyDecision.REVIEW,
            reason=(
                f"Property readiness is '{band}' (below Developing) — auto-send "
                f"paused until knowledge coverage improves."
            ),
            approval_mode_at_decision="auto",
        )

    # --- Step 5: green light ---
    return GateResult(
        decision=AutonomyDecision.AUTO_SEND,
        reason=(
            f"Auto mode, confidence {confidence:.2f} ≥ "
            f"{settings.min_confidence_for_auto:.2f}, no policy warnings, "
            f"no escalation."
        ),
        approval_mode_at_decision="auto",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Convenience — CRUD for the autonomy setting itself (operator toggle)
# ─────────────────────────────────────────────────────────────────────────────

async def set_property_autonomy(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    property_id: UUID,
    approval_mode: str,
    stage: str = "all",
    min_confidence_for_auto: float = 0.95,
    changed_by: Optional[str] = None,
) -> None:
    """
    Upsert a property_ai_autonomy row. Called from the Properties page
    when an operator flips a toggle.

    approval_mode: "required" or "auto"
    stage:         "all" (MVP) | future: pre_booking, in_stay, etc.
    """
    if approval_mode not in ("required", "auto"):
        raise ValueError(f"Invalid approval_mode: {approval_mode}")
    if stage not in ("all", "pre_booking", "booked_pre_arrival", "in_stay", "post_stay"):
        raise ValueError(f"Invalid stage: {stage}")
    if not (0 <= min_confidence_for_auto <= 1):
        raise ValueError("min_confidence_for_auto must be between 0 and 1")

    await db.execute(
        text("""
            INSERT INTO property_ai_autonomy
                (property_id, tenant_id, stage, approval_mode,
                 min_confidence_for_auto, auto_enabled_at, auto_enabled_by)
            VALUES
                (:pid, :tid, :stage, :mode, :conf,
                 CASE WHEN :mode = 'auto' THEN NOW() ELSE NULL END,
                 CASE WHEN :mode = 'auto' THEN :by ELSE NULL END)
            ON CONFLICT (property_id, stage) DO UPDATE SET
                approval_mode          = EXCLUDED.approval_mode,
                min_confidence_for_auto = EXCLUDED.min_confidence_for_auto,
                auto_enabled_at        = CASE
                    WHEN EXCLUDED.approval_mode = 'auto' AND property_ai_autonomy.approval_mode != 'auto'
                        THEN NOW()
                    WHEN EXCLUDED.approval_mode = 'required'
                        THEN NULL
                    ELSE property_ai_autonomy.auto_enabled_at
                END,
                auto_enabled_by        = CASE
                    WHEN EXCLUDED.approval_mode = 'auto' AND property_ai_autonomy.approval_mode != 'auto'
                        THEN :by
                    WHEN EXCLUDED.approval_mode = 'required'
                        THEN NULL
                    ELSE property_ai_autonomy.auto_enabled_by
                END,
                updated_at             = NOW()
        """),
        {
            "pid": str(property_id),
            "tid": str(tenant_id),
            "stage": stage,
            "mode": approval_mode,
            "conf": min_confidence_for_auto,
            "by": changed_by or "",
        },
    )
    await db.commit()

    logger.info(
        "[AutonomyGate] Property %s autonomy set to %s (stage=%s) by %s",
        property_id, approval_mode, stage, changed_by or "(anonymous)"
    )


async def get_property_autonomy(
    db: AsyncSession,
    *,
    property_id: UUID,
    stage: str = "all",
) -> AutonomySettings:
    """Read-only convenience for the Properties page toggle UI."""
    return await resolve_autonomy_settings(db, property_id, stage)
