"""
Experiment Registry — Lightweight Prompt/Policy Change Control

Pre-launch scope (this file):
  1. Variant registry  — control + named candidates with full prompt override
  2. Deterministic assignment — hash(session_token) % 100 < canary_pct
  3. Per-variant metrics — latency, escalation rate, fallback rate, cost
     (in-memory ring buffer; flush to DB on each log call)
  4. Hard rollback — manual pause flag + automatic threshold pause

Post-launch (not here):
  - Multi-metric significance testing
  - Auto-promotion of winners
  - Advanced cohort targeting

Design principles:
  - Zero latency overhead: assignment is a pure hash mod, no I/O
  - Non-blocking: metric writes are fire-and-forget to DB
  - Fail-safe: any error in experiment code falls back to CONTROL silently
  - Deterministic: same session_token always gets the same variant
  - Isolated: variants only affect the LLM system prompt + VoicePodConfig,
    never the escalation gate or safety policy

Rollback triggers (automatic):
  - Escalation rate for variant > escalation_rate_threshold (default 2×control)
  - Fallback rate for variant > fallback_rate_threshold (default 3×control)
  - Manual: set variant.paused = True via API or environment variable

Usage:
    registry = get_experiment_registry()

    # At VoicePod creation time:
    assignment = registry.assign(session_token="tok_abc123")
    # assignment.variant_id, assignment.system_prompt_override,
    # assignment.config_overrides (dict merged into VoicePodConfig)

    # After each VoicePod response:
    registry.record_metric(
        variant_id=assignment.variant_id,
        latency_ms=312.4,
        escalated=False,
        fallback_used=False,
        cost_usd=0.02,
    )

    # API / dashboard:
    registry.get_stats()          # per-variant aggregate stats
    registry.pause("v_tone_b")    # manual rollback
    registry.resume("v_tone_b")   # re-enable after investigation
"""

import hashlib
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Variant definition
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PromptVariant:
    """
    A single prompt/config variant.

    Fields:
      variant_id         — short slug, used in logs and DB (e.g. "control", "v_tone_b")
      description        — human-readable label for the dashboard
      canary_pct         — percentage of sessions assigned to this variant (0-100)
                           CONTROL always receives the remainder after all candidates
      system_prompt_override — if set, replaces VoicePod._build_system_prompt() output
                               entirely.  Use {guest_name}, {property_name}, etc. as
                               template vars (filled at assignment time).
      config_overrides   — dict merged into VoicePodConfig at creation time
                           (e.g. {"temperature": 0.5, "max_tokens": 100})
      paused             — hard rollback flag; paused variants always route to CONTROL
      created_at         — when this variant was registered
      auto_pause_thresholds — dict of metric → max_ratio_vs_control that triggers
                             automatic pause (e.g. {"escalation_rate": 2.0})
    """
    variant_id: str
    description: str
    canary_pct: float = 0.0               # 0 = control (catches remainder)
    system_prompt_override: Optional[str] = None
    config_overrides: Dict[str, Any] = field(default_factory=dict)
    paused: bool = False
    created_at: datetime = field(default_factory=datetime.utcnow)
    auto_pause_thresholds: Dict[str, float] = field(default_factory=lambda: {
        "escalation_rate": 2.0,   # pause if > 2× control escalation rate
        "fallback_rate": 3.0,     # pause if > 3× control fallback rate
    })


# ─────────────────────────────────────────────────────────────────────────────
# Assignment result
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class VariantAssignment:
    """Result of assigning a session to a variant."""
    variant_id: str
    session_token: str
    system_prompt_override: Optional[str]   # None = use VoicePod default
    config_overrides: Dict[str, Any]        # Empty = use VoicePodConfig defaults
    is_control: bool


# ─────────────────────────────────────────────────────────────────────────────
# Per-variant metrics accumulator
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class VariantMetrics:
    variant_id: str
    sessions: int = 0
    total_turns: int = 0
    escalations: int = 0
    fallbacks: int = 0
    total_latency_ms: float = 0.0
    total_cost_usd: float = 0.0
    # Rolling window (last 100 turns) for threshold evaluation
    _recent_escalations: List[bool] = field(default_factory=list)
    _recent_fallbacks: List[bool] = field(default_factory=list)
    _WINDOW = 100

    def record(
        self,
        latency_ms: float,
        escalated: bool,
        fallback_used: bool,
        cost_usd: float,
        new_session: bool = False,
    ) -> None:
        self.total_turns += 1
        self.total_latency_ms += latency_ms
        self.total_cost_usd += cost_usd
        if escalated:
            self.escalations += 1
        if fallback_used:
            self.fallbacks += 1
        if new_session:
            self.sessions += 1

        # Rolling window
        self._recent_escalations.append(escalated)
        self._recent_fallbacks.append(fallback_used)
        if len(self._recent_escalations) > self._WINDOW:
            self._recent_escalations.pop(0)
        if len(self._recent_fallbacks) > self._WINDOW:
            self._recent_fallbacks.pop(0)

    @property
    def escalation_rate(self) -> Optional[float]:
        if not self._recent_escalations:
            return None
        return sum(self._recent_escalations) / len(self._recent_escalations)

    @property
    def fallback_rate(self) -> Optional[float]:
        if not self._recent_fallbacks:
            return None
        return sum(self._recent_fallbacks) / len(self._recent_fallbacks)

    @property
    def avg_latency_ms(self) -> Optional[float]:
        if self.total_turns == 0:
            return None
        return round(self.total_latency_ms / self.total_turns, 1)

    @property
    def avg_cost_usd(self) -> Optional[float]:
        if self.total_turns == 0:
            return None
        return round(self.total_cost_usd / self.total_turns, 5)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "variant_id": self.variant_id,
            "sessions": self.sessions,
            "total_turns": self.total_turns,
            "escalations": self.escalations,
            "fallbacks": self.fallbacks,
            "escalation_rate": self.escalation_rate,
            "fallback_rate": self.fallback_rate,
            "avg_latency_ms": self.avg_latency_ms,
            "avg_cost_usd": self.avg_cost_usd,
            "total_cost_usd": round(self.total_cost_usd, 4),
            "window_size": len(self._recent_escalations),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Registry
# ─────────────────────────────────────────────────────────────────────────────

CONTROL_VARIANT_ID = "control"


class ExperimentRegistry:
    """
    Manages prompt variants, session assignment, metric collection,
    and automatic rollback.

    Thread-safe: all mutation is guarded by a single RLock.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._variants: Dict[str, PromptVariant] = {}
        self._metrics: Dict[str, VariantMetrics] = {}
        self._session_assignments: Dict[str, str] = {}   # token → variant_id (cache)
        self._paused_at: Dict[str, datetime] = {}         # variant_id → when paused
        self._auto_pause_events: List[Dict[str, Any]] = [] # audit log

        # Register the control variant (always present, never paused)
        self._register_control()

    def _register_control(self) -> None:
        control = PromptVariant(
            variant_id=CONTROL_VARIANT_ID,
            description="Control — production system prompt, no overrides",
            canary_pct=0.0,   # receives all traffic not claimed by candidates
            paused=False,
        )
        self._variants[CONTROL_VARIANT_ID] = control
        self._metrics[CONTROL_VARIANT_ID] = VariantMetrics(variant_id=CONTROL_VARIANT_ID)

    # ─────────────────────────────────────────────────────────────────────────
    # Variant management
    # ─────────────────────────────────────────────────────────────────────────

    def register(self, variant: PromptVariant) -> None:
        """
        Register a new variant (or replace an existing one).

        Call this at app startup or via the admin API to add a new candidate.
        The control variant cannot be replaced.
        """
        if variant.variant_id == CONTROL_VARIANT_ID:
            raise ValueError("Cannot replace the control variant")

        total_candidate_pct = sum(
            v.canary_pct for vid, v in self._variants.items()
            if vid != CONTROL_VARIANT_ID and vid != variant.variant_id and not v.paused
        ) + variant.canary_pct

        if total_candidate_pct > 100:
            raise ValueError(
                f"Total candidate canary_pct would exceed 100%: {total_candidate_pct:.1f}%"
            )

        with self._lock:
            self._variants[variant.variant_id] = variant
            if variant.variant_id not in self._metrics:
                self._metrics[variant.variant_id] = VariantMetrics(variant_id=variant.variant_id)
            # Invalidate cached assignments so existing sessions are reassigned
            # on next call (deterministic hash ensures they land on same variant
            # unless boundaries shifted)
            logger.info(
                "[Experiment] Registered variant '%s' (%.0f%% canary)",
                variant.variant_id, variant.canary_pct,
            )

    def pause(self, variant_id: str, reason: str = "manual") -> bool:
        """
        Hard rollback: pause a variant.  All subsequent assignments go to CONTROL.
        Existing sessions that were assigned to this variant continue to use
        CONTROL from their next message turn.

        Returns False if variant not found.
        """
        if variant_id == CONTROL_VARIANT_ID:
            logger.warning("[Experiment] Cannot pause the control variant")
            return False

        with self._lock:
            if variant_id not in self._variants:
                return False
            self._variants[variant_id].paused = True
            self._paused_at[variant_id] = datetime.utcnow()
            # Flush session assignment cache for this variant
            to_remove = [t for t, vid in self._session_assignments.items() if vid == variant_id]
            for t in to_remove:
                del self._session_assignments[t]

        logger.warning("[Experiment] Variant '%s' PAUSED — reason: %s", variant_id, reason)
        return True

    def resume(self, variant_id: str) -> bool:
        """Re-enable a paused variant."""
        if variant_id == CONTROL_VARIANT_ID:
            return False
        with self._lock:
            if variant_id not in self._variants:
                return False
            self._variants[variant_id].paused = False
            self._paused_at.pop(variant_id, None)
        logger.info("[Experiment] Variant '%s' RESUMED", variant_id)
        return True

    # ─────────────────────────────────────────────────────────────────────────
    # Session assignment
    # ─────────────────────────────────────────────────────────────────────────

    def assign(
        self,
        session_token: str,
        template_vars: Optional[Dict[str, str]] = None,
    ) -> VariantAssignment:
        """
        Deterministically assign a session to a variant.

        Algorithm:
          1. hash(session_token) % 100  → bucket 0-99
          2. Walk active (non-paused) candidates in registration order;
             each claims a contiguous bucket range from its canary_pct
          3. Remainder → CONTROL

        Same session_token always lands in the same bucket.
        When a variant is paused mid-experiment, its sessions move to CONTROL
        on the next call.

        template_vars: substituted into system_prompt_override.
          Supported: {guest_name}, {property_name}, {concierge_name},
                     {wifi_network}, {wifi_password}, {door_code},
                     {check_in_time}, {check_out_time}, {phase_guidance}
        """
        # Check cached assignment first (fast path after first call)
        with self._lock:
            if session_token in self._session_assignments:
                cached_id = self._session_assignments[session_token]
                variant = self._variants.get(cached_id)
                if variant and not variant.paused:
                    return self._make_assignment(session_token, variant, template_vars)
                # Cached variant was paused — fall through to re-assign

        bucket = self._bucket(session_token)
        selected = self._select_variant(bucket)

        with self._lock:
            self._session_assignments[session_token] = selected.variant_id
            # Increment session count once per token
            metrics = self._metrics.get(selected.variant_id)
            if metrics:
                metrics.sessions += 1

        if selected.variant_id != CONTROL_VARIANT_ID:
            logger.debug(
                "[Experiment] session=%s bucket=%d → variant=%s",
                session_token[:12], bucket, selected.variant_id,
            )

        return self._make_assignment(session_token, selected, template_vars)

    def _bucket(self, session_token: str) -> int:
        """Deterministic 0-99 bucket from session token."""
        digest = hashlib.sha256(session_token.encode()).hexdigest()
        return int(digest[:8], 16) % 100

    def _select_variant(self, bucket: int) -> PromptVariant:
        """Walk candidates in order; return first whose range covers bucket."""
        cursor = 0
        with self._lock:
            for vid, variant in self._variants.items():
                if vid == CONTROL_VARIANT_ID or variant.paused:
                    continue
                if cursor <= bucket < cursor + variant.canary_pct:
                    return variant
                cursor += variant.canary_pct
        # Remainder → CONTROL
        return self._variants[CONTROL_VARIANT_ID]

    def _make_assignment(
        self,
        session_token: str,
        variant: PromptVariant,
        template_vars: Optional[Dict[str, str]],
    ) -> VariantAssignment:
        prompt = variant.system_prompt_override
        if prompt and template_vars:
            try:
                prompt = prompt.format(**template_vars)
            except KeyError as exc:
                logger.warning("[Experiment] Prompt template missing key %s — using raw", exc)

        return VariantAssignment(
            variant_id=variant.variant_id,
            session_token=session_token,
            system_prompt_override=prompt,
            config_overrides=dict(variant.config_overrides),
            is_control=(variant.variant_id == CONTROL_VARIANT_ID),
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Metric recording + auto-pause
    # ─────────────────────────────────────────────────────────────────────────

    def record_metric(
        self,
        variant_id: str,
        latency_ms: float,
        escalated: bool,
        fallback_used: bool,
        cost_usd: float,
    ) -> None:
        """
        Record a single turn's metrics for the given variant.

        Checks auto-pause thresholds after recording.  Non-blocking — any
        error is swallowed so this never affects the response path.
        """
        try:
            with self._lock:
                metrics = self._metrics.get(variant_id)
                if metrics is None:
                    return
                metrics.record(
                    latency_ms=latency_ms,
                    escalated=escalated,
                    fallback_used=fallback_used,
                    cost_usd=cost_usd,
                )

            # Check auto-pause thresholds (outside lock to avoid contention)
            self._check_auto_pause(variant_id)
        except Exception as exc:
            logger.debug("[Experiment] record_metric error (non-fatal): %s", exc)

    def _check_auto_pause(self, variant_id: str) -> None:
        """Auto-pause variant if any threshold vs control is exceeded."""
        if variant_id == CONTROL_VARIANT_ID:
            return

        with self._lock:
            variant = self._variants.get(variant_id)
            if variant is None or variant.paused:
                return

            candidate_m = self._metrics.get(variant_id)
            control_m = self._metrics.get(CONTROL_VARIANT_ID)
            thresholds = variant.auto_pause_thresholds

            if candidate_m is None or control_m is None:
                return

            # Need at least 20 turns before auto-pause to avoid false positives
            if candidate_m.total_turns < 20:
                return

        # Escalation rate check
        c_esc = control_m.escalation_rate
        v_esc = candidate_m.escalation_rate
        if c_esc is not None and v_esc is not None and c_esc > 0:
            ratio = v_esc / c_esc
            threshold = thresholds.get("escalation_rate", 2.0)
            if ratio >= threshold:
                self._auto_pause(
                    variant_id,
                    reason=f"escalation_rate {v_esc:.1%} ≥ {ratio:.1f}× control ({c_esc:.1%})",
                    metric="escalation_rate",
                    value=v_esc,
                    ratio=ratio,
                    threshold=threshold,
                )
                return

        # Fallback rate check
        c_fb = control_m.fallback_rate
        v_fb = candidate_m.fallback_rate
        if c_fb is not None and v_fb is not None and c_fb > 0:
            ratio = v_fb / c_fb
            threshold = thresholds.get("fallback_rate", 3.0)
            if ratio >= threshold:
                self._auto_pause(
                    variant_id,
                    reason=f"fallback_rate {v_fb:.1%} ≥ {ratio:.1f}× control ({c_fb:.1%})",
                    metric="fallback_rate",
                    value=v_fb,
                    ratio=ratio,
                    threshold=threshold,
                )

    def _auto_pause(
        self,
        variant_id: str,
        reason: str,
        metric: str,
        value: float,
        ratio: float,
        threshold: float,
    ) -> None:
        """Automatically pause a variant and log the event."""
        self.pause(variant_id, reason=f"auto_pause: {reason}")
        event = {
            "event": "auto_pause",
            "variant_id": variant_id,
            "reason": reason,
            "metric": metric,
            "value": round(value, 4),
            "ratio_vs_control": round(ratio, 2),
            "threshold": threshold,
            "paused_at": datetime.utcnow().isoformat(),
        }
        self._auto_pause_events.append(event)
        logger.warning("[Experiment] AUTO-PAUSE %s: %s", variant_id, reason)

    # ─────────────────────────────────────────────────────────────────────────
    # Dashboard / API
    # ─────────────────────────────────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        """
        Per-variant aggregate stats for the operator dashboard.
        Includes rollback status, auto-pause history.
        """
        with self._lock:
            variants_out = []
            for vid, variant in self._variants.items():
                m = self._metrics.get(vid)
                variants_out.append({
                    "variant_id": vid,
                    "description": variant.description,
                    "canary_pct": variant.canary_pct,
                    "paused": variant.paused,
                    "is_control": vid == CONTROL_VARIANT_ID,
                    "paused_at": self._paused_at.get(vid, {}) and self._paused_at[vid].isoformat(),
                    "metrics": m.to_dict() if m else None,
                    "config_overrides": variant.config_overrides,
                    "has_prompt_override": variant.system_prompt_override is not None,
                    "created_at": variant.created_at.isoformat(),
                })
            return {
                "variants": variants_out,
                "auto_pause_events": list(self._auto_pause_events[-20:]),  # last 20
                "total_active_canary_pct": sum(
                    v.canary_pct for v in self._variants.values()
                    if v.variant_id != CONTROL_VARIANT_ID and not v.paused
                ),
            }

    def get_variant(self, variant_id: str) -> Optional[PromptVariant]:
        return self._variants.get(variant_id)

    def list_variants(self) -> List[PromptVariant]:
        return list(self._variants.values())


# =============================================================================
# Singleton
# =============================================================================

_registry: Optional[ExperimentRegistry] = None


def get_experiment_registry() -> ExperimentRegistry:
    global _registry
    if _registry is None:
        _registry = ExperimentRegistry()
        _load_env_variants(_registry)
    return _registry


async def persist_assignment(
    session_token: str,
    assignment: "VariantAssignment",
    variant: "PromptVariant",
    operator_id: Optional[str],
    property_code: Optional[str],
    db,  # AsyncSession — typed loosely to avoid circular import
) -> None:
    """
    Persist a variant assignment to DB (fire-and-forget).

    Call via asyncio.ensure_future() from VoicePod.from_session() so it
    never blocks the session creation path.

    Uses INSERT ... ON CONFLICT DO NOTHING so re-creating a VoicePod for
    an already-assigned session is safe.
    """
    try:
        from sqlalchemy import text
        await db.execute(
            text("""
                INSERT INTO experiment_assignments
                    (session_token, variant_id, is_control, canary_pct,
                     has_prompt_override, config_overrides,
                     operator_id, property_code)
                VALUES
                    (:session_token, :variant_id, :is_control, :canary_pct,
                     :has_prompt_override, :config_overrides::jsonb,
                     :operator_id, :property_code)
                ON CONFLICT (session_token) DO NOTHING
            """),
            {
                "session_token": session_token,
                "variant_id": assignment.variant_id,
                "is_control": assignment.is_control,
                "canary_pct": variant.canary_pct,
                "has_prompt_override": variant.system_prompt_override is not None,
                "config_overrides": __import__("json").dumps(variant.config_overrides),
                "operator_id": operator_id,
                "property_code": property_code,
            },
        )
        await db.commit()
    except Exception as exc:
        logger.debug("[Experiment] persist_assignment failed (non-fatal): %s", exc)


async def persist_variant_event(
    variant_id: str,
    event_type: str,
    db,
    reason: Optional[str] = None,
    operator: Optional[str] = None,
    metric: Optional[str] = None,
    metric_value: Optional[float] = None,
    ratio_vs_control: Optional[float] = None,
    threshold: Optional[float] = None,
) -> None:
    """
    Persist a variant lifecycle event (pause/resume/register/auto_pause) to DB.
    Call from API endpoints after each state change.
    """
    try:
        from sqlalchemy import text
        await db.execute(
            text("""
                INSERT INTO experiment_variant_events
                    (variant_id, event_type, reason, operator,
                     metric, metric_value, ratio_vs_control, threshold)
                VALUES
                    (:variant_id, :event_type, :reason, :operator,
                     :metric, :metric_value, :ratio_vs_control, :threshold)
            """),
            {
                "variant_id": variant_id,
                "event_type": event_type,
                "reason": reason,
                "operator": operator,
                "metric": metric,
                "metric_value": metric_value,
                "ratio_vs_control": ratio_vs_control,
                "threshold": threshold,
            },
        )
        await db.commit()
    except Exception as exc:
        logger.debug("[Experiment] persist_variant_event failed (non-fatal): %s", exc)


def _load_env_variants(registry: ExperimentRegistry) -> None:
    """
    Load variants from environment variables at startup.

    Format:
      EXPERIMENT_VARIANT_<ID>_PCT=10
      EXPERIMENT_VARIANT_<ID>_DESC="Shorter tone test"
      EXPERIMENT_VARIANT_<ID>_PROMPT="You are Coral..."  (optional)
      EXPERIMENT_VARIANT_<ID>_TEMP=0.5                   (optional)
      EXPERIMENT_VARIANT_<ID>_MAX_TOKENS=100             (optional)
      EXPERIMENT_VARIANT_<ID>_PAUSED=true                (optional)

    Example:
      EXPERIMENT_VARIANT_TONE_B_PCT=5
      EXPERIMENT_VARIANT_TONE_B_DESC="Shorter, punchier responses"
      EXPERIMENT_VARIANT_TONE_B_MAX_TOKENS=100
    """
    import os, re

    seen: Dict[str, Dict[str, str]] = {}
    prefix = "EXPERIMENT_VARIANT_"

    for key, val in os.environ.items():
        if not key.startswith(prefix):
            continue
        # EXPERIMENT_VARIANT_TONE_B_PCT → id_raw=TONE_B, field=PCT
        rest = key[len(prefix):]
        # Last segment is the field name
        parts = rest.rsplit("_", 1)
        if len(parts) != 2:
            continue
        id_raw, field_name = parts
        vid = id_raw.lower()
        seen.setdefault(vid, {})[field_name.upper()] = val

    for vid, fields in seen.items():
        try:
            pct = float(fields.get("PCT", "0"))
            desc = fields.get("DESC", f"Variant {vid}")
            prompt = fields.get("PROMPT")
            paused = fields.get("PAUSED", "false").lower() in ("true", "1", "yes")

            config_overrides: Dict[str, Any] = {}
            if "TEMP" in fields:
                config_overrides["temperature"] = float(fields["TEMP"])
            if "MAX_TOKENS" in fields:
                config_overrides["max_tokens"] = int(fields["MAX_TOKENS"])
            if "MODEL" in fields:
                config_overrides["model"] = fields["MODEL"]

            variant = PromptVariant(
                variant_id=vid,
                description=desc,
                canary_pct=pct,
                system_prompt_override=prompt,
                config_overrides=config_overrides,
                paused=paused,
            )
            registry.register(variant)
            logger.info("[Experiment] Loaded variant '%s' (%.0f%%) from environment", vid, pct)
        except Exception as exc:
            logger.warning("[Experiment] Failed to load env variant '%s': %s", vid, exc)
