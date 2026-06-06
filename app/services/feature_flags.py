"""
Oyvoda Canary / Feature Flag System

Controls which properties have AI co-host enabled.
Allows safe rollout: enable one property, verify, then expand.

Usage:
    flags = get_feature_flags(db)

    # Check before routing any guest message
    if not await flags.is_oyvoda_enabled(company_id, property_code):
        # Fall through to existing behavior (no AI response)
        return

    # Proceed with AI concierge pipeline

Canary workflow:
    1. Import all properties via Escapia sync (oyvoda_enabled = False by default)
    2. Enable for one property: flags.enable_property(company_id, "GULF_VIEW_204")
    3. Monitor dashboard for 2 weeks — KB gaps, CSAT, escalations
    4. Expand: flags.enable_all_for_operator(company_id)

Flag levels (most to least specific):
    property_code   — overrides operator and platform settings
    company_id      — all properties for this operator
    platform        — all operators on the platform (use with caution)

DB schema (operator_feature_flags table):
    id, company_id (nullable), property_code (nullable),
    flag_name, enabled (bool),
    enabled_at, enabled_by,
    notes (e.g. "Canary — Gulf View #204 only"),
    created_at
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


# =============================================================================
# FLAG NAMES
# =============================================================================

class FeatureFlag:
    OYVODA_ENABLED        = "oyvoda_enabled"         # AI co-host active for this property
    RCS_ENABLED           = "rcs_enabled"            # Use RCS for this operator
    PROACTIVE_BRIEFS      = "proactive_briefs"        # Send morning briefs
    PRE_BOOKING_AI        = "pre_booking_ai"          # AI draft pre-booking inquiries
    VENDOR_MARKETPLACE    = "vendor_marketplace"      # Vendor referral enabled
    GEO_OPT_IN            = "geo_opt_in"              # Offer location opt-in to guests
    EXTEND_STAY_OFFERS    = "extend_stay_offers"      # Offer extra nights
    KB_GAP_ALERTS         = "kb_gap_alerts"           # Alert operator on KB gaps
    EVENT_INTELLIGENCE    = "event_intelligence"      # Surface local events to guests
    STAY_WORKFLOW_MODULE  = "stay_workflow_module"
    WORK_ORDERS_MODULE    = "work_orders_module"
    PROPERTY_ASSETS_MODULE = "property_assets_module"
    VENDOR_INTELLIGENCE_MODULE = "vendor_intelligence_module"
    HANDOFFS_MODULE       = "handoffs_module"
    SAFETY_PROTOCOLS_MODULE = "safety_protocols_module"

    # Phase 1.3b — messaging brain runtime gates.
    # When MESSAGING_BRAIN_RUNTIME is on (and auto_track_maintenance is True),
    # /concierge/message routes through GuestMessageBrainOrchestrator instead
    # of the legacy ConciergeRunner. When MESSAGING_BRAIN_SHADOW_MODE is also
    # on, the brain runs end-to-end but module dispatch is suppressed (no
    # work order, no concierge event written) — only the audit trail lands.
    # Both flags default OFF. Both are independently scoped per
    # property/operator/platform via the standard three-tier resolution.
    MESSAGING_BRAIN_RUNTIME       = "messaging_brain_runtime"
    MESSAGING_BRAIN_SHADOW_MODE   = "messaging_brain_shadow_mode"
    MESSAGING_BRAIN_LLM_INTAKE    = "messaging_brain_llm_intake"
    BRAIN_INTAKE_PRIMARY         = "brain_intake_primary"
    BRAIN_INTAKE_SHADOW          = "brain_intake_shadow"
    BRAIN_POLICY_PRIMARY         = "brain_policy_primary"
    BRAIN_GAP_DETECTION_PRIMARY  = "brain_gap_detection_primary"
    BRAIN_PREBOOKING_LIFECYCLE_PRIMARY = "brain_prebooking_lifecycle_primary"
    SHIP_I_KB_RETRY_PRIMARY = "ship_i_kb_retry_primary"
    DASHBOARD_V2_PRIMARY = "dashboard_v2_primary"
    # Session 12 — LLM composer. When on, _compose_response in the
    # orchestrator routes through LLMComposerAgent instead of the
    # Phase 1.3a string-concatenation fallback. Independent of
    # MESSAGING_BRAIN_RUNTIME: brain-on/composer-off and brain-on/
    # composer-on are separately rolled-out states. Default OFF. See
    # docs/SESSION_12_COMPOSER_DESIGN.md for the full state matrix.
    MESSAGING_BRAIN_LLM_COMPOSER  = "messaging_brain_llm_composer"
    BRAIN_COMPOSER_PREFERENCES = "brain_composer_preferences"
    BRAIN_COMPOSER_PRIMARY = "brain_composer_primary"
    # Session 12 — composer compare mode. When on (and
    # MESSAGING_BRAIN_LLM_COMPOSER is also on), the composer runs and
    # its full result lands in ComposerMetadata, but the operator-facing
    # draft stays as the Phase 1.3a brain concatenation fallback. This
    # is the load-bearing setting for shadow validation: composer
    # candidate output is queryable next to the operator-facing draft
    # in the audit row, and we can compare quality before flipping
    # composer to "live."
    #
    # SCOPE NOTE: this flag is intentionally separate from
    # MESSAGING_BRAIN_SHADOW_MODE. That flag governs MODULE side-effect
    # suppression (work orders, concierge events). This flag governs
    # COMPOSER vs concatenation as the operator-facing draft source.
    # Conflating them would make one flag mean two unrelated things.
    #
    # GUARDRAIL: when MESSAGING_BRAIN_LLM_COMPOSER is OFF, this flag is
    # a no-op — the orchestrator skips the composer entirely. The
    # orchestrator enforces this; the flag service does not.
    MESSAGING_BRAIN_LLM_COMPOSER_SHADOW = "messaging_brain_llm_composer_shadow"
    MESSAGING_BRAIN_RICH_CONTEXT  = "messaging_brain_rich_context"
    MESSAGING_BRAIN_RICH_CONTEXT_SHADOW = "messaging_brain_rich_context_shadow"
    MESSAGING_BRAIN_CANONICAL_KB_READ = "messaging_brain_canonical_kb_read"
    MESSAGING_BRAIN_VECTOR_FALLBACK_ENABLED = "messaging_brain_vector_fallback_enabled"
    MESSAGING_BRAIN_VECTOR_FALLBACK_SHADOW_ENABLED = "messaging_brain_vector_fallback_shadow_enabled"
    MESSAGING_BRAIN_FAST_PATH_STAGE = "messaging_brain_fast_path_stage"
    MESSAGING_BRAIN_LAZY_CONTEXT_STAGE = "messaging_brain_lazy_context_stage"
    INBOUND_MESSAGE_GATE_ENABLED = "inbound_message_gate_enabled"
    INBOUND_MESSAGE_GATE_REVIEW_ALL = "inbound_message_gate_review_all"
    RESERVATION_AWARE_ROUTING_ENABLED = "reservation_aware_routing_enabled"


# =============================================================================
# IN-MEMORY CACHE (TTL: 5 minutes to avoid hammering DB)
# =============================================================================

class _FlagCache:
    TTL_SECONDS = 300  # 5 minutes

    def __init__(self):
        self._cache: Dict[str, Any] = {}
        self._timestamps: Dict[str, float] = {}

    def get(self, key: str) -> Optional[bool]:
        import time
        if key not in self._cache:
            return None
        if time.time() - self._timestamps.get(key, 0) > self.TTL_SECONDS:
            del self._cache[key]
            return None
        return self._cache[key]

    def set(self, key: str, value: bool) -> None:
        import time
        self._cache[key] = value
        self._timestamps[key] = time.time()

    def invalidate(self, key: str) -> None:
        self._cache.pop(key, None)
        self._timestamps.pop(key, None)

    def invalidate_prefix(self, prefix: str) -> None:
        keys = [k for k in self._cache if k.startswith(prefix)]
        for k in keys:
            self.invalidate(k)


_cache = _FlagCache()


# =============================================================================
# FEATURE FLAGS SERVICE
# =============================================================================

class FeatureFlagService:
    """
    Resolves feature flags for a given company + property combination.

    Resolution order (most specific wins):
        1. Property-level flag
        2. Operator (company) level flag
        3. Platform default (env var)
        4. Hard default (False = safe off)
    """

    def __init__(self, db=None):
        self.db = db

    # ── Core resolution ──────────────────────────────────────────────────────

    async def is_enabled(
        self,
        flag_name: str,
        company_id: Optional[str] = None,
        property_code: Optional[str] = None,
    ) -> bool:
        """
        Check if a feature flag is enabled for a given company + property.
        Checks property-level first, then operator-level, then platform default.
        """
        # Check property-level first
        if property_code:
            prop_key = f"prop:{property_code}:{flag_name}"
            cached = _cache.get(prop_key)
            if cached is not None:
                return cached
            prop_val = await self._get_from_db(flag_name, company_id, property_code)
            if prop_val is not None:
                _cache.set(prop_key, prop_val)
                return prop_val

        # Check operator-level
        if company_id:
            op_key = f"op:{company_id}:{flag_name}"
            cached = _cache.get(op_key)
            if cached is not None:
                return cached
            op_val = await self._get_from_db(flag_name, company_id, None)
            if op_val is not None:
                _cache.set(op_key, op_val)
                return op_val

        # Platform default from env
        return self._get_platform_default(flag_name)

    async def is_oyvoda_enabled(
        self,
        company_id: str,
        property_code: str,
    ) -> bool:
        """
        Check if the Oyvoda AI co-host is enabled for this specific property.
        This is the primary canary gate checked before every AI response.
        """
        return await self.is_enabled(
            FeatureFlag.OYVODA_ENABLED,
            company_id=company_id,
            property_code=property_code,
        )

    # ── Enable/disable operations ─────────────────────────────────────────────

    async def enable_property(
        self,
        company_id: str,
        property_code: str,
        enabled_by: str = "admin",
        notes: Optional[str] = None,
    ) -> bool:
        """
        Enable Oyvoda AI for a single property.
        This is the canary onboarding step.
        """
        return await self._set_flag(
            flag_name=FeatureFlag.OYVODA_ENABLED,
            enabled=True,
            company_id=company_id,
            property_code=property_code,
            enabled_by=enabled_by,
            notes=notes or f"Canary enable — {property_code}",
        )

    async def disable_property(
        self,
        company_id: str,
        property_code: str,
        reason: str = "manual disable",
    ) -> bool:
        """
        Disable Oyvoda AI for a specific property (e.g. during an incident).
        Takes effect within 5 minutes (cache TTL).
        """
        return await self._set_flag(
            flag_name=FeatureFlag.OYVODA_ENABLED,
            enabled=False,
            company_id=company_id,
            property_code=property_code,
            enabled_by="admin",
            notes=reason,
        )

    async def enable_all_for_operator(
        self,
        company_id: str,
        enabled_by: str = "admin",
    ) -> bool:
        """
        Enable Oyvoda AI for all properties under this operator.
        Called after successful canary validation.
        """
        return await self._set_flag(
            flag_name=FeatureFlag.OYVODA_ENABLED,
            enabled=True,
            company_id=company_id,
            property_code=None,  # Operator-level — covers all properties
            enabled_by=enabled_by,
            notes="Full rollout after canary validation",
        )

    async def disable_operator(
        self,
        company_id: str,
        reason: str = "manual disable",
    ) -> bool:
        """
        Emergency kill switch — disable all Oyvoda AI for an entire operator.
        Use during incidents or churn. Takes effect within 5 minutes.
        """
        result = await self._set_flag(
            flag_name=FeatureFlag.OYVODA_ENABLED,
            enabled=False,
            company_id=company_id,
            property_code=None,
            enabled_by="admin",
            notes=f"Emergency disable: {reason}",
        )
        # Immediately invalidate cache for this operator
        _cache.invalidate_prefix(f"op:{company_id}:")
        return result

    async def set_flag(
        self,
        flag_name: str,
        enabled: bool,
        *,
        company_id: Optional[str] = None,
        property_code: Optional[str] = None,
        enabled_by: str = "admin",
        notes: Optional[str] = None,
    ) -> bool:
        """
        Set an arbitrary flag for an operator/property/platform scope.

        For canonical canary flags (OYVODA_ENABLED), prefer the typed helpers
        like enable_property() / disable_property() — they have the right
        defaults and notes for that workflow. This generic method is for
        flags that don't yet have typed wrappers (e.g. the
        MESSAGING_BRAIN_RUNTIME / MESSAGING_BRAIN_SHADOW_MODE pair during
        Phase 1.3b rollout).

        Rollback recipe for messaging_brain_runtime:
            await get_feature_flags(db).set_flag(
                FeatureFlag.MESSAGING_BRAIN_RUNTIME, False,
                company_id=cid, property_code="GULF_VIEW_204",
                notes="rollback after live test",
            )
        """
        return await self._set_flag(
            flag_name=flag_name,
            enabled=enabled,
            company_id=company_id,
            property_code=property_code,
            enabled_by=enabled_by,
            notes=notes,
        )

    async def list_enabled_properties(
        self,
        company_id: str,
    ) -> List[str]:
        """
        List all property codes with Oyvoda enabled for an operator.
        Useful for the canary status view in the admin panel.
        """
        if not self.db:
            return []
        try:
            from sqlalchemy import text
            rows = await self.db.execute(
                text("""
                    SELECT property_code
                    FROM operator_feature_flags
                    WHERE company_id = :cid
                      AND flag_name = :flag
                      AND enabled = true
                      AND property_code IS NOT NULL
                    ORDER BY enabled_at DESC
                """),
                {"cid": str(company_id), "flag": FeatureFlag.OYVODA_ENABLED},
            )
            return [row.property_code for row in rows.fetchall()]
        except Exception as e:
            logger.error(f"[Flags] list_enabled_properties failed: {e}")
            return []

    async def get_operator_flag_summary(
        self,
        company_id: str,
    ) -> Dict[str, Any]:
        """
        Get a summary of all flags for an operator.
        Used in admin dashboard and canary status panel.
        """
        if not self.db:
            return {"error": "No DB session"}

        try:
            from sqlalchemy import text
            rows = await self.db.execute(
                text("""
                    SELECT flag_name, property_code, enabled, enabled_at, enabled_by, notes
                    FROM operator_feature_flags
                    WHERE company_id = :cid
                    ORDER BY flag_name, property_code
                """),
                {"cid": str(company_id)},
            )
            flags = {}
            for row in rows.fetchall():
                key = row.flag_name
                if key not in flags:
                    flags[key] = {"operator_level": None, "properties": {}}
                if row.property_code:
                    flags[key]["properties"][row.property_code] = {
                        "enabled": row.enabled,
                        "enabled_at": str(row.enabled_at),
                        "enabled_by": row.enabled_by,
                        "notes": row.notes,
                    }
                else:
                    flags[key]["operator_level"] = {
                        "enabled": row.enabled,
                        "enabled_at": str(row.enabled_at),
                        "enabled_by": row.enabled_by,
                        "notes": row.notes,
                    }
            return {"company_id": str(company_id), "flags": flags}
        except Exception as e:
            logger.error(f"[Flags] get_operator_flag_summary failed: {e}")
            return {"error": str(e)}

    # ── Internal DB operations ────────────────────────────────────────────────

    async def _get_from_db(
        self,
        flag_name: str,
        company_id: Optional[str],
        property_code: Optional[str],
    ) -> Optional[bool]:
        """Fetch flag value from DB. Returns None if not set."""
        if not self.db:
            return None
        try:
            from sqlalchemy import text
            params = {
                "flag": flag_name,
                "cid": str(company_id) if company_id else None,
            }
            if property_code is not None:
                result = await self.db.execute(
                    text("""
                        SELECT enabled
                        FROM operator_feature_flags
                        WHERE flag_name = :flag
                          AND company_id = :cid
                          AND property_code = :prop
                        LIMIT 1
                    """),
                    {
                        **params,
                        "prop": property_code,
                    },
                )
            else:
                result = await self.db.execute(
                    text("""
                        SELECT enabled
                        FROM operator_feature_flags
                        WHERE flag_name = :flag
                          AND company_id = :cid
                          AND property_code IS NULL
                        LIMIT 1
                    """),
                    params,
                )
            row = result.fetchone()
            return bool(row.enabled) if row else None
        except Exception as e:
            logger.warning(f"[Flags] DB get failed for {flag_name}: {e}")
            return None

    async def _set_flag(
        self,
        flag_name: str,
        enabled: bool,
        company_id: Optional[str] = None,
        property_code: Optional[str] = None,
        enabled_by: str = "system",
        notes: Optional[str] = None,
    ) -> bool:
        """Upsert a flag in the DB and invalidate cache."""
        if not self.db:
            logger.warning(f"[Flags] No DB session — cannot persist flag {flag_name}")
            return False
        try:
            from sqlalchemy import text
            import uuid as _uuid
            await self.db.execute(
                text("""
                    INSERT INTO operator_feature_flags
                        (id, company_id, property_code, flag_name, enabled,
                         enabled_at, enabled_by, notes, created_at)
                    VALUES
                        (:id, :cid, :prop, :flag, :enabled,
                         :now, :by, :notes, :now)
                    ON CONFLICT (company_id, property_code, flag_name)
                    DO UPDATE SET
                        enabled = EXCLUDED.enabled,
                        enabled_at = EXCLUDED.enabled_at,
                        enabled_by = EXCLUDED.enabled_by,
                        notes = EXCLUDED.notes
                """),
                {
                    "id": str(_uuid.uuid4()),
                    "cid": str(company_id) if company_id else None,
                    "prop": property_code,
                    "flag": flag_name,
                    "enabled": enabled,
                    "now": datetime.utcnow(),
                    "by": enabled_by,
                    "notes": notes,
                },
            )
            await self.db.commit()

            # Invalidate cache
            if property_code:
                _cache.invalidate(f"prop:{property_code}:{flag_name}")
            if company_id:
                _cache.invalidate(f"op:{company_id}:{flag_name}")

            action = "enabled" if enabled else "disabled"
            scope = f"property={property_code}" if property_code else f"operator={company_id}"
            logger.info(f"[Flags] {flag_name} {action} for {scope} by {enabled_by}")
            return True

        except Exception as e:
            logger.error(f"[Flags] _set_flag failed for {flag_name}: {e}")
            return False

    def _get_platform_default(self, flag_name: str) -> bool:
        """
        Platform-level defaults from environment variables.
        These are the last resort before returning False.
        """
        env_defaults = {
            FeatureFlag.OYVODA_ENABLED:     os.getenv("OYVODA_DEFAULT_ENABLED", "false").lower() == "true",
            FeatureFlag.RCS_ENABLED:        os.getenv("TWILIO_RCS_ENABLED", "false").lower() == "true",
            FeatureFlag.PROACTIVE_BRIEFS:   os.getenv("OYVODA_PROACTIVE_BRIEFS", "true").lower() == "true",
            FeatureFlag.PRE_BOOKING_AI:     os.getenv("OYVODA_PRE_BOOKING_AI", "true").lower() == "true",
            FeatureFlag.VENDOR_MARKETPLACE: os.getenv("OYVODA_VENDORS", "true").lower() == "true",
            FeatureFlag.EXTEND_STAY_OFFERS: os.getenv("OYVODA_EXTEND_STAY", "true").lower() == "true",
            FeatureFlag.KB_GAP_ALERTS:      os.getenv("OYVODA_KB_GAP_ALERTS", "true").lower() == "true",
            FeatureFlag.EVENT_INTELLIGENCE: os.getenv("OYVODA_EVENTS", "true").lower() == "true",
            FeatureFlag.GEO_OPT_IN:         os.getenv("OYVODA_GEO_OPT_IN", "false").lower() == "true",
            FeatureFlag.STAY_WORKFLOW_MODULE: os.getenv("OYVODA_STAY_WORKFLOW", "true").lower() == "true",
            FeatureFlag.WORK_ORDERS_MODULE: os.getenv("OYVODA_WORK_ORDERS", "true").lower() == "true",
            FeatureFlag.PROPERTY_ASSETS_MODULE: os.getenv("OYVODA_PROPERTY_ASSETS", "true").lower() == "true",
            FeatureFlag.VENDOR_INTELLIGENCE_MODULE: os.getenv("OYVODA_VENDOR_INTELLIGENCE", "true").lower() == "true",
            FeatureFlag.HANDOFFS_MODULE: os.getenv("OYVODA_HANDOFFS", "true").lower() == "true",
            FeatureFlag.SAFETY_PROTOCOLS_MODULE: os.getenv("OYVODA_SAFETY_PROTOCOLS", "true").lower() == "true",
            # Phase 1.3b — both default to safe-off. Set OYVODA_MESSAGING_BRAIN_RUNTIME=true
            # to flip on platform-wide, or use the per-property/per-operator
            # set_flag() helper for canary-style rollout.
            FeatureFlag.MESSAGING_BRAIN_RUNTIME:     os.getenv("OYVODA_MESSAGING_BRAIN_RUNTIME", "false").lower() == "true",
            FeatureFlag.MESSAGING_BRAIN_SHADOW_MODE: os.getenv("OYVODA_MESSAGING_BRAIN_SHADOW_MODE", "false").lower() == "true",
            FeatureFlag.MESSAGING_BRAIN_LLM_INTAKE:  os.getenv("OYVODA_MESSAGING_BRAIN_LLM_INTAKE", "false").lower() == "true",
            FeatureFlag.BRAIN_INTAKE_PRIMARY: os.getenv("OYVODA_BRAIN_INTAKE_PRIMARY", "false").lower() == "true",
            FeatureFlag.BRAIN_INTAKE_SHADOW: os.getenv("OYVODA_BRAIN_INTAKE_SHADOW", "false").lower() == "true",
            FeatureFlag.BRAIN_POLICY_PRIMARY: os.getenv("OYVODA_BRAIN_POLICY_PRIMARY", "false").lower() == "true",
            FeatureFlag.BRAIN_GAP_DETECTION_PRIMARY: os.getenv("OYVODA_BRAIN_GAP_DETECTION_PRIMARY", "false").lower() == "true",
            FeatureFlag.BRAIN_PREBOOKING_LIFECYCLE_PRIMARY: os.getenv("OYVODA_BRAIN_PREBOOKING_LIFECYCLE_PRIMARY", "false").lower() == "true",
            FeatureFlag.SHIP_I_KB_RETRY_PRIMARY: os.getenv("OYVODA_SHIP_I_KB_RETRY_PRIMARY", "false").lower() == "true",
            FeatureFlag.DASHBOARD_V2_PRIMARY: os.getenv("OYVODA_DASHBOARD_V2_PRIMARY", "false").lower() == "true",
            # Session 12 — default safe-off. Independent of MESSAGING_BRAIN_RUNTIME;
            # see docs/SESSION_12_COMPOSER_DESIGN.md state matrix.
            FeatureFlag.MESSAGING_BRAIN_LLM_COMPOSER: os.getenv("OYVODA_MESSAGING_BRAIN_LLM_COMPOSER", "false").lower() == "true",
            FeatureFlag.BRAIN_COMPOSER_PREFERENCES: os.getenv("OYVODA_BRAIN_COMPOSER_PREFERENCES", "false").lower() == "true",
            FeatureFlag.BRAIN_COMPOSER_PRIMARY: os.getenv("OYVODA_BRAIN_COMPOSER_PRIMARY", "false").lower() == "true",
            # Session 12 — composer compare mode. Default safe-off. No-op
            # unless MESSAGING_BRAIN_LLM_COMPOSER is also on; the
            # orchestrator enforces that guardrail.
            FeatureFlag.MESSAGING_BRAIN_LLM_COMPOSER_SHADOW: os.getenv("OYVODA_MESSAGING_BRAIN_LLM_COMPOSER_SHADOW", "false").lower() == "true",
            FeatureFlag.MESSAGING_BRAIN_RICH_CONTEXT: os.getenv("OYVODA_MESSAGING_BRAIN_RICH_CONTEXT", "false").lower() == "true",
            FeatureFlag.MESSAGING_BRAIN_RICH_CONTEXT_SHADOW: os.getenv("OYVODA_MESSAGING_BRAIN_RICH_CONTEXT_SHADOW", "false").lower() == "true",
            FeatureFlag.MESSAGING_BRAIN_CANONICAL_KB_READ: os.getenv("OYVODA_MESSAGING_BRAIN_CANONICAL_KB_READ", "false").lower() == "true",
            FeatureFlag.MESSAGING_BRAIN_VECTOR_FALLBACK_ENABLED: os.getenv("OYVODA_MESSAGING_BRAIN_VECTOR_FALLBACK_ENABLED", "false").lower() == "true",
            FeatureFlag.MESSAGING_BRAIN_VECTOR_FALLBACK_SHADOW_ENABLED: os.getenv("OYVODA_MESSAGING_BRAIN_VECTOR_FALLBACK_SHADOW_ENABLED", "false").lower() == "true",
            FeatureFlag.MESSAGING_BRAIN_FAST_PATH_STAGE: os.getenv("OYVODA_MESSAGING_BRAIN_FAST_PATH_STAGE", "false").lower() == "true",
            FeatureFlag.MESSAGING_BRAIN_LAZY_CONTEXT_STAGE: os.getenv("OYVODA_MESSAGING_BRAIN_LAZY_CONTEXT_STAGE", "false").lower() == "true",
            FeatureFlag.INBOUND_MESSAGE_GATE_ENABLED: os.getenv("OYVODA_INBOUND_MESSAGE_GATE", "false").lower() == "true",
            FeatureFlag.INBOUND_MESSAGE_GATE_REVIEW_ALL: os.getenv("OYVODA_INBOUND_MESSAGE_GATE_REVIEW_ALL", "false").lower() == "true",
        }
        return env_defaults.get(flag_name, False)


# =============================================================================
# DB MIGRATION (run once to create the flags table)
# =============================================================================

MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS operator_feature_flags (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id      UUID,
    property_code   TEXT,
    flag_name       TEXT NOT NULL,
    enabled         BOOLEAN NOT NULL DEFAULT FALSE,
    enabled_at      TIMESTAMPTZ,
    enabled_by      TEXT,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Unique constraint: one flag per (company, property, name) combination
    -- NULL values are treated as "all" for that dimension
    CONSTRAINT uq_operator_feature_flags
        UNIQUE NULLS NOT DISTINCT (company_id, property_code, flag_name)
);

CREATE INDEX IF NOT EXISTS idx_flags_company ON operator_feature_flags (company_id, flag_name);
CREATE INDEX IF NOT EXISTS idx_flags_property ON operator_feature_flags (property_code, flag_name);

-- Alert contacts table for OperatorAlertRouter
CREATE TABLE IF NOT EXISTS operator_alert_contacts (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id                  UUID NOT NULL,
    alert_type                  TEXT NOT NULL,
    property_code               TEXT,         -- NULL = applies to all properties
    contact_name                TEXT NOT NULL,
    contact_phone               TEXT,
    contact_email               TEXT,
    is_primary                  BOOLEAN DEFAULT TRUE,
    escalation_order            INT DEFAULT 1,
    escalation_timeout_minutes  INT DEFAULT 30,
    active_hours_start          TIME,         -- NULL = 24/7
    active_hours_end            TIME,         -- NULL = 24/7
    notes                       TEXT,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_alert_contacts_company
    ON operator_alert_contacts (company_id, alert_type);
CREATE INDEX IF NOT EXISTS idx_alert_contacts_property
    ON operator_alert_contacts (property_code, alert_type);
"""


# =============================================================================
# SINGLETON
# =============================================================================

def get_feature_flags(db=None) -> FeatureFlagService:
    """
    Get a FeatureFlagService instance.
    Pass db= for DB-backed persistence and cache write-through.
    Without db, read-only from env vars (useful in tests and background tasks).
    """
    return FeatureFlagService(db=db)


async def is_messaging_brain_llm_intake_enabled(
    *,
    db,
    tenant_id: str,
    property_code: Optional[str] = None,
) -> bool:
    """Resolve whether the LLM intake classifier should run for this message.

    Session 9 keeps this default-off and runtime-resolved so existing callers
    do not need to know about the classifier swap.
    """
    return await get_feature_flags(db=db).is_enabled(
        FeatureFlag.MESSAGING_BRAIN_LLM_INTAKE,
        company_id=tenant_id,
        property_code=property_code,
    )


async def is_brain_intake_primary_enabled(
    *,
    db,
    tenant_id: str,
    property_code: Optional[str] = None,
) -> bool:
    """Resolve whether deterministic-first brain intake owns classification."""
    return await get_feature_flags(db=db).is_enabled(
        FeatureFlag.BRAIN_INTAKE_PRIMARY,
        company_id=tenant_id,
        property_code=property_code,
    )


async def is_brain_intake_shadow_enabled(
    *,
    db,
    tenant_id: str,
    property_code: Optional[str] = None,
) -> bool:
    """Resolve whether legacy pre-booking should emit shadow brain intake audit."""
    return await get_feature_flags(db=db).is_enabled(
        FeatureFlag.BRAIN_INTAKE_SHADOW,
        company_id=tenant_id,
        property_code=property_code,
    )


async def is_brain_policy_primary_enabled(
    *,
    db,
    tenant_id: str,
    property_code: Optional[str] = None,
) -> bool:
    """Resolve whether the brain policy bridge owns pre-booking policy decisions."""
    return await get_feature_flags(db=db).is_enabled(
        FeatureFlag.BRAIN_POLICY_PRIMARY,
        company_id=tenant_id,
        property_code=property_code,
    )


async def is_brain_gap_detection_primary_enabled(
    *,
    db,
    tenant_id: str,
    property_code: Optional[str] = None,
) -> bool:
    """Whether legacy pre-booking knowledge-gap logic should bridge through brain-owned handlers."""
    return await get_feature_flags(db=db).is_enabled(
        FeatureFlag.BRAIN_GAP_DETECTION_PRIMARY,
        company_id=tenant_id,
        property_code=property_code,
    )


async def is_brain_prebooking_lifecycle_primary_enabled(
    *,
    db,
    tenant_id: str,
    property_code: Optional[str] = None,
) -> bool:
    """Whether brain-owned pre-booking lifecycle replaces the legacy persist/send wrapper."""
    return await get_feature_flags(db=db).is_enabled(
        FeatureFlag.BRAIN_PREBOOKING_LIFECYCLE_PRIMARY,
        company_id=tenant_id,
        property_code=property_code,
    )


async def is_ship_i_kb_retry_primary_enabled(
    *,
    db,
    tenant_id: str,
    property_code: Optional[str] = None,
) -> bool:
    """Whether Ship I KB retry behavior is active for this tenant/property."""
    return await get_feature_flags(db=db).is_enabled(
        FeatureFlag.SHIP_I_KB_RETRY_PRIMARY,
        company_id=tenant_id,
        property_code=property_code,
    )


async def is_dashboard_v2_primary_enabled(
    *,
    db,
    tenant_id: str,
    property_code: Optional[str] = None,
) -> bool:
    """Whether the React dashboard v2 should be the primary operator surface."""
    return await get_feature_flags(db=db).is_enabled(
        FeatureFlag.DASHBOARD_V2_PRIMARY,
        company_id=tenant_id,
        property_code=property_code,
    )


async def is_messaging_brain_llm_composer_enabled(
    *,
    db,
    tenant_id: str,
    property_code: Optional[str] = None,
) -> bool:
    """Resolve whether the LLM composer should produce the candidate output
    for this message.

    Session 12 keeps this default-off and runtime-resolved so existing
    callers do not need to know about the composer swap. Independent of
    MESSAGING_BRAIN_RUNTIME — when runtime is on but composer is off, the
    brain runs end-to-end and falls through to the Phase 1.3a string
    concatenation in _compose_response. See
    docs/SESSION_12_COMPOSER_DESIGN.md for the full state matrix.
    """
    return await get_feature_flags(db=db).is_enabled(
        FeatureFlag.MESSAGING_BRAIN_LLM_COMPOSER,
        company_id=tenant_id,
        property_code=property_code,
    )


async def is_brain_composer_preferences_enabled(
    *,
    db,
    tenant_id: str,
    property_code: Optional[str] = None,
) -> bool:
    """Whether the brain LLM composer should inject learned preferences."""
    return await get_feature_flags(db=db).is_enabled(
        FeatureFlag.BRAIN_COMPOSER_PREFERENCES,
        company_id=tenant_id,
        property_code=property_code,
    )


async def is_brain_composer_primary_enabled(
    *,
    db,
    tenant_id: str,
    property_code: Optional[str] = None,
) -> bool:
    """Whether legacy pre-booking draft generation should bridge through brain-owned handlers."""
    return await get_feature_flags(db=db).is_enabled(
        FeatureFlag.BRAIN_COMPOSER_PRIMARY,
        company_id=tenant_id,
        property_code=property_code,
    )


async def is_messaging_brain_llm_composer_shadow_enabled(
    *,
    db,
    tenant_id: str,
    property_code: Optional[str] = None,
) -> bool:
    """Resolve whether the composer should run in compare-only mode for
    this message.

    Session 12 — when on (and is_messaging_brain_llm_composer_enabled
    is also on), the composer runs and its full result is recorded in
    ComposerMetadata, but the operator-facing draft stays as the brain
    concatenation fallback so quality can be validated side-by-side
    before the composer becomes live for this tenant.

    This flag is intentionally distinct from MESSAGING_BRAIN_SHADOW_MODE,
    which governs MODULE side-effect suppression. Composer-shadow and
    module-shadow are separate concerns.

    Default OFF. No-op unless MESSAGING_BRAIN_LLM_COMPOSER is also on
    — the orchestrator enforces that guardrail; this helper just
    resolves the underlying flag value.
    """
    return await get_feature_flags(db=db).is_enabled(
        FeatureFlag.MESSAGING_BRAIN_LLM_COMPOSER_SHADOW,
        company_id=tenant_id,
        property_code=property_code,
    )


async def is_messaging_brain_rich_context_enabled(
    *,
    db,
    tenant_id: str,
    property_code: Optional[str] = None,
) -> bool:
    return await get_feature_flags(db=db).is_enabled(
        FeatureFlag.MESSAGING_BRAIN_RICH_CONTEXT,
        company_id=tenant_id,
        property_code=property_code,
    )


async def is_messaging_brain_rich_context_shadow_enabled(
    *,
    db,
    tenant_id: str,
    property_code: Optional[str] = None,
) -> bool:
    """Whether rich-context shadow observation logging is enabled."""
    return await get_feature_flags(db=db).is_enabled(
        FeatureFlag.MESSAGING_BRAIN_RICH_CONTEXT_SHADOW,
        company_id=str(tenant_id),
        property_code=property_code,
    )


async def is_messaging_brain_canonical_kb_read_enabled(
    *,
    db,
    tenant_id: str,
    property_code: Optional[str] = None,
) -> bool:
    return await get_feature_flags(db=db).is_enabled(
        FeatureFlag.MESSAGING_BRAIN_CANONICAL_KB_READ,
        company_id=str(tenant_id),
        property_code=property_code,
    )


async def is_messaging_brain_vector_fallback_enabled(
    *,
    db,
    tenant_id: str,
    property_code: Optional[str] = None,
) -> bool:
    return await get_feature_flags(db=db).is_enabled(
        FeatureFlag.MESSAGING_BRAIN_VECTOR_FALLBACK_ENABLED,
        company_id=str(tenant_id),
        property_code=property_code,
    )


async def is_messaging_brain_vector_fallback_shadow_enabled(
    *,
    db,
    tenant_id: str,
    property_code: Optional[str] = None,
) -> bool:
    return await get_feature_flags(db=db).is_enabled(
        FeatureFlag.MESSAGING_BRAIN_VECTOR_FALLBACK_SHADOW_ENABLED,
        company_id=str(tenant_id),
        property_code=property_code,
    )


async def is_messaging_brain_fast_path_stage_enabled(
    *,
    db,
    tenant_id: str,
    property_code: Optional[str] = None,
) -> bool:
    """Whether the brain should try deterministic fast-path exits first."""
    return await get_feature_flags(db=db).is_enabled(
        FeatureFlag.MESSAGING_BRAIN_FAST_PATH_STAGE,
        company_id=str(tenant_id),
        property_code=property_code,
    )


async def is_messaging_brain_lazy_context_stage_enabled(
    *,
    db,
    tenant_id: str,
    property_code: Optional[str] = None,
) -> bool:
    """Whether context loading should be gated instead of eager."""
    return await get_feature_flags(db=db).is_enabled(
        FeatureFlag.MESSAGING_BRAIN_LAZY_CONTEXT_STAGE,
        company_id=str(tenant_id),
        property_code=property_code,
    )
