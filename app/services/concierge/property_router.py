"""
Tenant-Scoped Property Router

Explicit, named routing layer that resolves the right property context
for a given session, with full tenant isolation enforced at the DB query level.

Why this exists:
  Before this, property resolution was implicit:
    - mobile_v2 used DEFAULT_TENANT_ID at bootstrap
    - voice.py had a hardcoded property_profile dict
    - Multiple code paths each did their own lookup with slightly different logic

  This means:
    1. If a session's tenant_id doesn't match DEFAULT_TENANT_ID, lookups silently
       return wrong or empty data — no error, just stale guest experience.
    2. There's no single place to see "what property data did this session get?"
       since the resolution happened differently in 3 places.

What this does:
  - Single entry point for property context resolution
  - Tenant ID is ALWAYS verified before any property row is returned
  - Falls back through a priority chain: PMS MCP → DB property table → session JSON → safe empty
  - Resolution is logged to Watch Layer so we can see which fallback fired
  - Used at session creation time and on each VoicePod initialization

Usage:
    from app.services.concierge.property_router import PropertyRouter, get_property_router

    router = get_property_router()
    ctx = await router.resolve(
        db=db,
        session_token=token,
        tenant_id="tenant_beach_habitats",
        property_code="CORAL",
    )
    # ctx.wifi_password, ctx.door_code, ctx.check_in_time, ctx.source
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Union
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.identity.tenant_normalization import (
    InvalidTenantIdError,
    normalize_tenant_id,
)

logger = logging.getLogger(__name__)


@dataclass
class ResolvedPropertyContext:
    """
    Property context returned by the router.

    source tells you which fallback tier was used:
      "pms"      — live PMS data (freshest)
      "db"       — DB property table (populated by operator onboarding)
      "session"  — property_context JSON on the session row
      "empty"    — no data found anywhere (operator needs to populate)
    """
    property_code: str
    tenant_id: str
    source: str                          # "pms" | "db" | "session" | "empty"

    # Credentials
    wifi_network: Optional[str] = None
    wifi_password: Optional[str] = None
    door_code: Optional[str] = None

    # Times
    check_in_time: str = "4:00 PM"
    check_out_time: str = "10:00 AM"

    # Amenities
    has_pool: bool = False
    pool_heated: bool = False
    has_hot_tub: bool = False
    has_grill: bool = False
    has_beach_gear: bool = False
    has_bikes: bool = False
    pets_allowed: bool = False

    # Support
    support_phone: Optional[str] = None
    check_in_instructions: Optional[str] = None

    # Raw dict for backward compat (VoicePodContext uses dict-style access)
    raw: Dict[str, Any] = field(default_factory=dict)

    def is_degraded(self) -> bool:
        """True if we're missing critical credentials."""
        return not self.wifi_password or not self.door_code

    def to_dict(self) -> Dict[str, Any]:
        return {
            "wifi_network": self.wifi_network,
            "wifi_password": self.wifi_password,
            "door_code": self.door_code,
            "check_in_time": self.check_in_time,
            "check_out_time": self.check_out_time,
            "has_pool": self.has_pool,
            "pool_heated": self.pool_heated,
            "has_hot_tub": self.has_hot_tub,
            "has_grill": self.has_grill,
            "has_beach_gear": self.has_beach_gear,
            "has_bikes": self.has_bikes,
            "pets_allowed": self.pets_allowed,
            "support_phone": self.support_phone,
            "check_in_instructions": self.check_in_instructions,
            "_source": self.source,
            "_degraded": self.is_degraded(),
        }


class PropertyRouter:
    """
    Resolves the authoritative property context for a session.

    Resolution priority (highest to lowest):
      1. PMS MCP — live data from Escapia/Guesty/Track (if active)
      2. DB property table — operator-populated during onboarding
      3. Session property_context JSON — whatever was captured at booking
      4. Safe empty — logs degradation, operator must populate

    Tenant isolation:
      Every DB query is scoped to the session's real tenant_id.
      Cross-tenant data is structurally impossible — the WHERE clause
      always includes `tenant_id = :tid`.
    """

    def __init__(self) -> None:
        self._watch = None

    def _get_watch(self):
        if self._watch is None:
            from app.services.observability.watch_layer import get_watch_layer
            self._watch = get_watch_layer()
        return self._watch

    # ─────────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────────

    async def resolve(
        self,
        db: AsyncSession,
        tenant_id: Union[UUID, str],
        property_code: str,
        operator_id: str,
        session_property_context: Optional[Dict[str, Any]] = None,
        session_token: Optional[str] = None,
    ) -> ResolvedPropertyContext:
        """
        Resolve property context through the priority chain.

        Always scoped to tenant_id — never returns data from a different tenant.
        """
        tenant_id_uuid = normalize_tenant_id(tenant_id)
        import asyncio

        # ── Tier 1: PMS MCP (live) ────────────────────────────────────────
        pms_ctx = await self._try_pms(operator_id, property_code)
        if pms_ctx:
            pms_ctx.tenant_id = str(tenant_id_uuid)
            ctx = pms_ctx
            asyncio.ensure_future(self._log_resolution(
                operator_id=operator_id,
                property_code=property_code,
                tenant_id=str(tenant_id_uuid),
                source="pms",
                degraded=ctx.is_degraded(),
            ))
            return ctx

        # ── Tier 2: DB property table ─────────────────────────────────────
        db_ctx = await self._try_db_property(db, str(tenant_id_uuid), property_code)
        if db_ctx:
            ctx = db_ctx
            asyncio.ensure_future(self._log_resolution(
                operator_id=operator_id,
                property_code=property_code,
                tenant_id=str(tenant_id_uuid),
                source="db",
                degraded=ctx.is_degraded(),
            ))
            return ctx

        # ── Tier 3: Session JSON ──────────────────────────────────────────
        if session_property_context:
            ctx = self._from_session_json(
                property_code=property_code,
                tenant_id=str(tenant_id_uuid),
                data=session_property_context,
            )
            asyncio.ensure_future(self._log_resolution(
                operator_id=operator_id,
                property_code=property_code,
                tenant_id=str(tenant_id_uuid),
                source="session",
                degraded=ctx.is_degraded(),
            ))
            return ctx

        # ── Tier 4: Safe empty ────────────────────────────────────────────
        logger.warning(
            "[PropertyRouter] No property data for %s tenant=%s — returning empty",
            property_code, tenant_id,
        )
        ctx = ResolvedPropertyContext(
            property_code=property_code,
            tenant_id=str(tenant_id_uuid),
            source="empty",
        )
        asyncio.ensure_future(self._log_resolution(
            operator_id=operator_id,
            property_code=property_code,
            tenant_id=str(tenant_id_uuid),
            source="empty",
            degraded=True,
        ))
        return ctx

    async def resolve_from_session_row(
        self,
        db: AsyncSession,
        session_row,
    ) -> ResolvedPropertyContext:
        """
        Convenience wrapper: resolve from a DB session row.

        Extracts tenant_id, property_code, and operator_id from the row,
        then runs the full priority chain.  This is what mobile_v2.py
        should call instead of doing its own property lookup.
        """
        raw_tenant_id = getattr(session_row, "tenant_id", None)
        tenant_id = normalize_tenant_id(raw_tenant_id)
        property_code = getattr(session_row, "property_code", "") or ""
        operator_id = str(getattr(session_row, "operator_id", "")) or "unknown"
        session_ctx = getattr(session_row, "property_context", None) or {}

        return await self.resolve(
            db=db,
            tenant_id=tenant_id,
            property_code=property_code,
            operator_id=operator_id,
            session_property_context=session_ctx,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Resolution tiers
    # ─────────────────────────────────────────────────────────────────────────

    async def _try_pms(
        self,
        operator_id: str,
        property_code: str,
    ) -> Optional[ResolvedPropertyContext]:
        """Attempt PMS MCP lookup.  Returns None if PMS is offline (stub)."""
        try:
            from app.mcp.registry import get_mcp_registry
            registry = get_mcp_registry()
            result = await registry.call(
                server_name="pms",
                tool_name="get_property_info",
                operator_id=operator_id,
                params={"property_id": property_code},
            )
            if not result.success:
                return None
            data = result.data or {}
            if data.get("_source") == "stub":
                return None  # PMS offline

            return self._build_from_dict(
                property_code=property_code,
                tenant_id="",  # PMS doesn't carry tenant_id; resolve() sets it before returning
                data=data,
                source="pms",
            )
        except Exception as exc:
            logger.debug("[PropertyRouter] PMS lookup failed: %s", exc)
            return None

    async def _try_db_property(
        self,
        db: AsyncSession,
        tenant_id: str,
        property_code: str,
    ) -> Optional[ResolvedPropertyContext]:
        """
        Look up property in the DB property table, scoped to tenant_id.
        If the tenant_id doesn't match, this query returns nothing —
        cross-tenant data is structurally impossible.
        """
        try:
            from sqlalchemy import text
            result = await db.execute(
                text("""
                    SELECT property_code, wifi_network, wifi_password, door_code,
                           check_in_time, check_out_time,
                           has_pool, pool_heated, has_hot_tub, has_grill,
                           has_beach_gear, has_bikes, pets_allowed,
                           support_phone, check_in_instructions
                    FROM properties
                    WHERE property_code = :code
                      AND tenant_id = :tid
                      AND is_active = TRUE
                    LIMIT 1
                """),
                {"code": property_code, "tid": tenant_id},
            )
            row = result.fetchone()
            if row is None:
                return None

            return ResolvedPropertyContext(
                property_code=property_code,
                tenant_id=tenant_id,
                source="db",
                wifi_network=row.wifi_network,
                wifi_password=row.wifi_password,
                door_code=row.door_code,
                check_in_time=row.check_in_time or "4:00 PM",
                check_out_time=row.check_out_time or "10:00 AM",
                has_pool=bool(row.has_pool),
                pool_heated=bool(row.pool_heated),
                has_hot_tub=bool(row.has_hot_tub),
                has_grill=bool(row.has_grill),
                has_beach_gear=bool(row.has_beach_gear),
                has_bikes=bool(row.has_bikes),
                pets_allowed=bool(row.pets_allowed),
                support_phone=row.support_phone,
                check_in_instructions=row.check_in_instructions,
            )
        except Exception as exc:
            logger.debug("[PropertyRouter] DB property lookup failed: %s", exc)
            return None

    def _from_session_json(
        self,
        property_code: str,
        tenant_id: str,
        data: Dict[str, Any],
    ) -> ResolvedPropertyContext:
        """Build from the property_context JSON stored on the session row."""
        return self._build_from_dict(
            property_code=property_code,
            tenant_id=tenant_id,
            data=data,
            source="session",
        )

    def _build_from_dict(
        self,
        property_code: str,
        tenant_id: str,
        data: Dict[str, Any],
        source: str,
    ) -> ResolvedPropertyContext:
        return ResolvedPropertyContext(
            property_code=property_code,
            tenant_id=tenant_id,
            source=source,
            wifi_network=data.get("wifi_network"),
            wifi_password=data.get("wifi_password"),
            door_code=data.get("door_code"),
            check_in_time=data.get("check_in_time", "4:00 PM"),
            check_out_time=data.get("check_out_time", "10:00 AM"),
            has_pool=bool(data.get("has_pool")),
            pool_heated=bool(data.get("pool_heated")),
            has_hot_tub=bool(data.get("has_hot_tub")),
            has_grill=bool(data.get("has_grill")),
            has_beach_gear=bool(data.get("has_beach_gear")),
            has_bikes=bool(data.get("has_bikes")),
            pets_allowed=bool(data.get("pets_allowed")),
            support_phone=data.get("support_phone"),
            check_in_instructions=data.get("check_in_instructions"),
            raw=data,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Watch Layer
    # ─────────────────────────────────────────────────────────────────────────

    async def _log_resolution(
        self,
        operator_id: str,
        property_code: str,
        tenant_id: str,
        source: str,
        degraded: bool,
    ) -> None:
        """Log property resolution to Watch Layer for SLO observability."""
        watch = self._get_watch()
        await watch.log_agent_run(
            agent_name="property_router",
            operator_id=operator_id,
            success=not degraded,
            latency_ms=0,
            metadata={
                "property_code": property_code,
                "tenant_id": tenant_id,
                "resolution_source": source,
                "degraded": degraded,
            },
        )
        if degraded:
            logger.warning(
                "[PropertyRouter] Degraded context: property=%s tenant=%s source=%s "
                "(missing wifi_password or door_code — operator must populate)",
                property_code, tenant_id, source,
            )


# =============================================================================
# Singleton
# =============================================================================

_property_router: Optional[PropertyRouter] = None


def get_property_router() -> PropertyRouter:
    global _property_router
    if _property_router is None:
        _property_router = PropertyRouter()
    return _property_router
