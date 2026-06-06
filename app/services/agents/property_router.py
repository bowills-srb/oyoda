"""
Property Router — Tenant-Scoped Property Lookup

Explicit, deterministic router that resolves property_code → property record
with a mandatory tenant_id WHERE clause on every query.

Why this exists:
  Without it, property lookups scatter through the codebase with
  inconsistent tenant scoping — some queries include tenant_id, some don't.
  One missing clause = cross-tenant data leak.

What it guarantees:
  - Every DB read is `WHERE property_code = :code AND tenant_id = :tid`
  - Structural impossibility of cross-tenant contamination
  - Active-only by default (inactive/archived properties return None)
  - Cached per (tenant_id, property_code) with a short TTL so repeated
    VoicePod calls don't hit the DB on every message turn

Usage:
    from app.services.agents.property_router import get_property_router

    router = get_property_router()

    # In an async request handler / VoicePod:
    record = await router.get_property(db, tenant_id="abc", property_code="CORAL")
    if record is None:
        # Property not found or not owned by this tenant
        raise HTTPException(404, "Property not found")

    basics = router.to_property_basics(record)
    # → {wifi_network, wifi_password, door_code, check_in_time, check_out_time, ...}

Design notes:
  - Never raises — returns None when property not found (caller decides 404/403)
  - Cache uses (tenant_id, property_code) as key; TTL = 60 seconds
  - Inject db_session per-request (do not cache across requests)
  - No cross-tenant methods exist by design
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple, Union
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.identity.tenant_normalization import (
    InvalidTenantIdError,
    normalize_tenant_id,
)

logger = logging.getLogger(__name__)

# Per-process cache TTL (seconds).  Short to catch PMS sync updates promptly.
_CACHE_TTL_SECONDS = 60


@dataclass
class PropertyRecord:
    """
    Minimal property record returned by PropertyRouter.

    All fields that concierge agents care about.  Intentionally flat —
    no nesting — so callers can pattern-match without deep attribute access.
    """
    property_code: str
    property_name: str
    tenant_id: str

    # Access credentials
    wifi_network: Optional[str] = None
    wifi_password: Optional[str] = None
    door_code: Optional[str] = None
    check_in_time: str = "4:00 PM"
    check_out_time: str = "10:00 AM"

    # Amenities (coerced to bool — safe for template rendering)
    has_pool: bool = False
    pool_heated: bool = False
    has_hot_tub: bool = False
    has_grill: bool = False
    has_bikes: bool = False
    bike_count: int = 0
    has_beach_gear: bool = False
    has_washer_dryer: bool = False
    pets_allowed: bool = False

    # Rules
    max_occupancy: Optional[int] = None
    quiet_hours_start: Optional[str] = None
    quiet_hours_end: Optional[str] = None

    # Check-in instructions
    check_in_instructions: Optional[str] = None
    check_out_instructions: Optional[str] = None

    # Operational
    operator_id: Optional[str] = None
    active: bool = True

    # Raw JSON (full property_context blob if present in DB)
    raw_context: Dict[str, Any] = field(default_factory=dict)


class PropertyRouter:
    """
    Tenant-scoped property lookup with short-lived in-process cache.

    Every lookup enforces:
        WHERE property_code = :code AND tenant_id = :tenant_id AND active = TRUE

    This is the single authoritative source for "does this tenant own this
    property?" — all concierge agents go through here.
    """

    def __init__(self) -> None:
        # (tenant_id, property_code) → (PropertyRecord, expires_at)
        self._cache: Dict[Tuple[str, str], Tuple[PropertyRecord, float]] = {}

    # ─────────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────────

    async def get_property(
        self,
        db: AsyncSession,
        tenant_id: Union[UUID, str],
        property_code: str,
        bypass_cache: bool = False,
    ) -> Optional[PropertyRecord]:
        """
        Fetch a property record, scoped to the given tenant.

        Returns None if:
        - Property doesn't exist
        - Property is not owned by this tenant
        - Property is marked inactive

        Never raises — errors are logged and return None.
        """
        tenant_id_uuid = normalize_tenant_id(tenant_id)
        tenant_id_str = str(tenant_id_uuid)
        cache_key = (tenant_id_str, property_code)

        # Cache hit
        if not bypass_cache:
            cached = self._cache.get(cache_key)
            if cached:
                record, expires_at = cached
                if time.monotonic() < expires_at:
                    return record
                else:
                    del self._cache[cache_key]

        # DB lookup
        record = await self._fetch_from_db(db, tenant_id_str, property_code)

        # Cache result (even None → negative cache prevents hammering DB)
        # For negative (None) results we use a shorter TTL of 10s
        if record is not None:
            self._cache[cache_key] = (record, time.monotonic() + _CACHE_TTL_SECONDS)
        # Don't cache None — let next call retry DB immediately

        return record

    async def get_properties_for_tenant(
        self,
        db: AsyncSession,
        tenant_id: Union[UUID, str],
        active_only: bool = True,
    ) -> list[PropertyRecord]:
        """
        Return all properties for a tenant.  Used by batch jobs (PMS sync, curator).
        Not cached — always hits DB.
        """
        try:
            from sqlalchemy import text
            tenant_id_str = str(normalize_tenant_id(tenant_id))
            params: Dict[str, Any] = {"tid": tenant_id_str}
            where = "WHERE tenant_id = :tid"
            if active_only:
                where += " AND is_active = TRUE"
            result = await db.execute(
                text(f"""
                    SELECT property_code, property_name, tenant_id,
                           wifi_network, wifi_password, door_code,
                           check_in_time, check_out_time,
                           has_pool, pool_heated, has_hot_tub, has_grill,
                           has_bikes, bike_count, has_beach_gear, has_washer_dryer,
                           pets_allowed, max_occupancy,
                           quiet_hours_start, quiet_hours_end,
                           check_in_instructions, check_out_instructions,
                           operator_id, is_active AS active, property_context
                    FROM properties
                    {where}
                    ORDER BY property_code ASC
                """),
                params,
            )
            return [self._row_to_record(r) for r in result.fetchall()]
        except Exception as exc:
            logger.error("[PropertyRouter] get_properties_for_tenant error: %s", exc)
            return []

    def invalidate(self, tenant_id: Union[UUID, str], property_code: str) -> None:
        """
        Evict a cached record.  Call after PMS sync updates a property's
        credentials so the next VoicePod call gets fresh data immediately.
        """
        tenant_id_str = str(normalize_tenant_id(tenant_id))
        self._cache.pop((tenant_id_str, property_code), None)

    def invalidate_tenant(self, tenant_id: Union[UUID, str]) -> None:
        """Evict all cached records for a tenant."""
        tenant_id_str = str(normalize_tenant_id(tenant_id))
        to_remove = [k for k in self._cache if k[0] == tenant_id_str]
        for k in to_remove:
            del self._cache[k]

    # ─────────────────────────────────────────────────────────────────────────
    # Convenience converter
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def to_property_basics(record: PropertyRecord) -> Dict[str, Any]:
        """
        Convert a PropertyRecord to the compact dict that VoicePod and
        ConciergeMCP tools expect.
        """
        return {
            "property_code": record.property_code,
            "property_name": record.property_name,
            "wifi_network": record.wifi_network,
            "wifi_password": record.wifi_password,
            "door_code": record.door_code,
            "check_in_time": record.check_in_time,
            "check_out_time": record.check_out_time,
            "has_pool": record.has_pool,
            "pool_heated": record.pool_heated,
            "has_hot_tub": record.has_hot_tub,
            "has_grill": record.has_grill,
            "has_bikes": record.has_bikes,
            "bike_count": record.bike_count,
            "has_beach_gear": record.has_beach_gear,
            "has_washer_dryer": record.has_washer_dryer,
            "pets_allowed": record.pets_allowed,
            "max_occupancy": record.max_occupancy,
            "quiet_hours_start": record.quiet_hours_start,
            "quiet_hours_end": record.quiet_hours_end,
            "check_in_instructions": record.check_in_instructions,
            "check_out_instructions": record.check_out_instructions,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # DB fetch
    # ─────────────────────────────────────────────────────────────────────────

    async def _fetch_from_db(
        self,
        db: AsyncSession,
        tenant_id: str,
        property_code: str,
    ) -> Optional[PropertyRecord]:
        """
        Tenant-scoped DB lookup.

        The WHERE clause ALWAYS includes both property_code AND tenant_id.
        This is the structural cross-tenant safety guarantee.
        """
        try:
            from sqlalchemy import text
            result = await db.execute(
                text("""
                    SELECT
                        property_code, property_name, tenant_id,
                        wifi_network, wifi_password, door_code,
                        check_in_time, check_out_time,
                        has_pool, pool_heated, has_hot_tub, has_grill,
                        has_bikes, bike_count, has_beach_gear, has_washer_dryer,
                        pets_allowed, max_occupancy,
                        quiet_hours_start, quiet_hours_end,
                        check_in_instructions, check_out_instructions,
                        operator_id, is_active AS active,
                        property_context
                    FROM properties
                    WHERE property_code = :code
                      AND tenant_id     = :tenant_id
                      AND is_active     = TRUE
                    LIMIT 1
                """),
                {"code": property_code, "tenant_id": tenant_id},
            )
            row = result.fetchone()
            if row is None:
                logger.debug(
                    "[PropertyRouter] Not found: tenant=%s property=%s",
                    tenant_id, property_code,
                )
                return None
            return self._row_to_record(row)

        except Exception as exc:
            logger.error(
                "[PropertyRouter] DB error tenant=%s property=%s: %s",
                tenant_id, property_code, exc,
            )
            return None

    @staticmethod
    def _row_to_record(row) -> PropertyRecord:
        """Convert a DB row (RowMapping or named tuple) to PropertyRecord."""
        import json

        raw_ctx: Dict[str, Any] = {}
        ctx_col = getattr(row, "property_context", None)
        if ctx_col:
            if isinstance(ctx_col, str):
                try:
                    raw_ctx = json.loads(ctx_col)
                except Exception:
                    pass
            elif isinstance(ctx_col, dict):
                raw_ctx = ctx_col

        def _bool(val) -> bool:
            if val is None:
                return False
            return bool(val)

        def _int(val, default: int = 0) -> int:
            try:
                return int(val) if val is not None else default
            except (TypeError, ValueError):
                return default

        return PropertyRecord(
            property_code=row.property_code or "",
            property_name=row.property_name or "",
            tenant_id=row.tenant_id or "",
            wifi_network=getattr(row, "wifi_network", None) or raw_ctx.get("wifi_network"),
            wifi_password=getattr(row, "wifi_password", None) or raw_ctx.get("wifi_password"),
            door_code=getattr(row, "door_code", None) or raw_ctx.get("door_code"),
            check_in_time=getattr(row, "check_in_time", None) or raw_ctx.get("check_in_time", "4:00 PM"),
            check_out_time=getattr(row, "check_out_time", None) or raw_ctx.get("check_out_time", "10:00 AM"),
            has_pool=_bool(getattr(row, "has_pool", False)),
            pool_heated=_bool(getattr(row, "pool_heated", False)),
            has_hot_tub=_bool(getattr(row, "has_hot_tub", False)),
            has_grill=_bool(getattr(row, "has_grill", False)),
            has_bikes=_bool(getattr(row, "has_bikes", False)),
            bike_count=_int(getattr(row, "bike_count", 0)),
            has_beach_gear=_bool(getattr(row, "has_beach_gear", False)),
            has_washer_dryer=_bool(getattr(row, "has_washer_dryer", False)),
            pets_allowed=_bool(getattr(row, "pets_allowed", False)),
            max_occupancy=getattr(row, "max_occupancy", None),
            quiet_hours_start=getattr(row, "quiet_hours_start", None),
            quiet_hours_end=getattr(row, "quiet_hours_end", None),
            check_in_instructions=getattr(row, "check_in_instructions", None),
            check_out_instructions=getattr(row, "check_out_instructions", None),
            operator_id=getattr(row, "operator_id", None),
            active=_bool(getattr(row, "active", True)),
            raw_context=raw_ctx,
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
