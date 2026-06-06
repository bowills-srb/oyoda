from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


logger = logging.getLogger(__name__)


class OperatorScopeService:
    async def _table_exists(self, session: AsyncSession, table_name: str) -> bool:
        try:
            exists = await session.scalar(
                text(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM information_schema.tables
                        WHERE table_schema = 'public'
                          AND table_name = :table_name
                    )
                    """
                ),
                {"table_name": table_name},
            )
            return bool(exists)
        except Exception:
            return False

    async def visible_property_codes(
        self,
        session: AsyncSession,
        tenant_id: str,
        user_id: str,
        role: str,
    ) -> Optional[set[str]]:
        profile = await self.get_scope_profile(session, tenant_id, user_id, role)
        return profile["visible_property_codes"]

    async def get_scope_profile(
        self,
        session: AsyncSession,
        tenant_id: str,
        user_id: str,
        role: str,
    ) -> dict:
        manager_defaults = role in {"manager", "owner", "super_admin"}
        profile = {
            "role": role,
            "has_scopes": False,
            "visible_property_codes": None,
            "can_assign": manager_defaults,
            "can_manage_vendors": manager_defaults,
            "can_manage_settings": manager_defaults,
        }
        if role in {"owner", "super_admin"}:
            return profile
        if not user_id or not await self._table_exists(session, "operator_member_scopes"):
            return profile
        try:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT scope_type, portfolio_id, property_external_id
                        FROM operator_member_scopes
                        WHERE tenant_id = CAST(:tid AS uuid)
                          AND member_user_id = CAST(:uid AS uuid)
                          AND can_view = TRUE
                        """
                    ),
                    {"tid": tenant_id, "uid": user_id},
                )
            ).mappings().all()
            if not rows:
                return profile

            profile["has_scopes"] = True
            profile["can_assign"] = any(bool(row.get("can_assign")) for row in rows)
            profile["can_manage_vendors"] = any(bool(row.get("can_manage_vendors")) for row in rows)
            profile["can_manage_settings"] = any(bool(row.get("can_manage_settings")) for row in rows)
            if any((row.get("scope_type") or "") == "tenant" and bool(row.get("can_view", True)) for row in rows):
                profile["visible_property_codes"] = None
                return profile

            property_codes = {
                str(row["property_external_id"])
                for row in rows
                if (row.get("scope_type") or "") == "property" and row.get("property_external_id")
            }
            portfolio_ids = [str(row["portfolio_id"]) for row in rows if (row.get("scope_type") or "") == "portfolio" and row.get("portfolio_id")]
            if portfolio_ids and await self._table_exists(session, "operator_portfolio_properties"):
                portfolio_rows = (
                    await session.execute(
                        text(
                            """
                            SELECT property_external_id
                            FROM operator_portfolio_properties
                            WHERE tenant_id = CAST(:tid AS uuid)
                              AND portfolio_id = ANY(CAST(:portfolio_ids AS uuid[]))
                            """
                        ),
                        {"tid": tenant_id, "portfolio_ids": portfolio_ids},
                    )
                ).fetchall()
                property_codes.update(str(row[0]) for row in portfolio_rows if row[0])
            profile["visible_property_codes"] = property_codes
            return profile
        except Exception as exc:
            logger.warning("[OperatorScopeService] get_scope_profile failed: %s", exc)
            try:
                await session.rollback()
            except Exception:
                pass
            return profile

    async def list_portfolios(self, session: AsyncSession, tenant_id: str) -> list[dict]:
        if not await self._table_exists(session, "operator_portfolios"):
            return []
        try:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT p.portfolio_id, p.portfolio_key, p.display_name, p.description, p.active,
                               COUNT(pp.property_external_id) AS property_count,
                               COALESCE(
                                   ARRAY_REMOVE(ARRAY_AGG(pp.property_external_id ORDER BY pp.property_external_id), NULL),
                                   ARRAY[]::text[]
                               ) AS property_external_ids
                        FROM operator_portfolios p
                        LEFT JOIN operator_portfolio_properties pp
                          ON pp.portfolio_id = p.portfolio_id
                        WHERE p.tenant_id = CAST(:tid AS uuid)
                        GROUP BY p.portfolio_id, p.portfolio_key, p.display_name, p.description, p.active
                        ORDER BY p.display_name
                        """
                    ),
                    {"tid": tenant_id},
                )
            ).mappings().all()
            return [
                {
                    "portfolio_id": str(row["portfolio_id"]),
                    "portfolio_key": row["portfolio_key"],
                    "display_name": row["display_name"],
                    "description": row["description"] or "",
                    "active": bool(row["active"]),
                    "property_count": int(row["property_count"] or 0),
                    "property_external_ids": list(row["property_external_ids"] or []),
                }
                for row in rows
            ]
        except Exception as exc:
            logger.warning("[OperatorScopeService] list_portfolios failed: %s", exc)
            try:
                await session.rollback()
            except Exception:
                pass
            return []

    async def create_portfolio(
        self,
        session: AsyncSession,
        tenant_id: str,
        operator_id: str,
        *,
        portfolio_key: str,
        display_name: str,
        description: str = "",
    ) -> Optional[str]:
        if not await self._table_exists(session, "operator_portfolios"):
            return None
        try:
            row = (
                await session.execute(
                    text(
                        """
                        INSERT INTO operator_portfolios
                            (tenant_id, operator_id, portfolio_key, display_name, description)
                        VALUES
                            (CAST(:tid AS uuid), CAST(:oid AS uuid), :portfolio_key, :display_name, :description)
                        ON CONFLICT (tenant_id, portfolio_key) DO UPDATE SET
                            display_name = EXCLUDED.display_name,
                            description = EXCLUDED.description,
                            updated_at = NOW()
                        RETURNING portfolio_id
                        """
                    ),
                    {
                        "tid": tenant_id,
                        "oid": operator_id,
                        "portfolio_key": portfolio_key,
                        "display_name": display_name,
                        "description": description,
                    },
                )
            ).fetchone()
            await session.commit()
            return str(row[0]) if row else None
        except Exception as exc:
            logger.warning("[OperatorScopeService] create_portfolio failed: %s", exc)
            try:
                await session.rollback()
            except Exception:
                pass
            return None

    async def replace_portfolio_properties(
        self,
        session: AsyncSession,
        tenant_id: str,
        portfolio_id: str,
        property_external_ids: list[str],
    ) -> bool:
        if not await self._table_exists(session, "operator_portfolio_properties"):
            return False
        try:
            await session.execute(
                text(
                    """
                    DELETE FROM operator_portfolio_properties
                    WHERE tenant_id = CAST(:tid AS uuid)
                      AND portfolio_id = CAST(:pid AS uuid)
                    """
                ),
                {"tid": tenant_id, "pid": portfolio_id},
            )
            for property_external_id in property_external_ids:
                if not property_external_id:
                    continue
                await session.execute(
                    text(
                        """
                        INSERT INTO operator_portfolio_properties
                            (tenant_id, portfolio_id, property_external_id)
                        VALUES
                            (CAST(:tid AS uuid), CAST(:pid AS uuid), :property_external_id)
                        ON CONFLICT (portfolio_id, property_external_id) DO NOTHING
                        """
                    ),
                    {"tid": tenant_id, "pid": portfolio_id, "property_external_id": property_external_id},
                )
            await session.commit()
            return True
        except Exception as exc:
            logger.warning("[OperatorScopeService] replace_portfolio_properties failed: %s", exc)
            try:
                await session.rollback()
            except Exception:
                pass
            return False

    async def list_member_scopes(
        self,
        session: AsyncSession,
        tenant_id: str,
        member_user_id: str,
    ) -> list[dict]:
        if not await self._table_exists(session, "operator_member_scopes"):
            return []
        try:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT scope_id, scope_type, portfolio_id, property_external_id,
                               can_view, can_assign, can_manage_vendors, can_manage_settings
                        FROM operator_member_scopes
                        WHERE tenant_id = CAST(:tid AS uuid)
                          AND member_user_id = CAST(:uid AS uuid)
                        ORDER BY created_at
                        """
                    ),
                    {"tid": tenant_id, "uid": member_user_id},
                )
            ).mappings().all()
            return [
                {
                    "scope_id": str(row["scope_id"]),
                    "scope_type": row["scope_type"],
                    "portfolio_id": str(row["portfolio_id"]) if row["portfolio_id"] else "",
                    "property_external_id": row["property_external_id"] or "",
                    "can_view": bool(row["can_view"]),
                    "can_assign": bool(row["can_assign"]),
                    "can_manage_vendors": bool(row["can_manage_vendors"]),
                    "can_manage_settings": bool(row["can_manage_settings"]),
                }
                for row in rows
            ]
        except Exception as exc:
            logger.warning("[OperatorScopeService] list_member_scopes failed: %s", exc)
            try:
                await session.rollback()
            except Exception:
                pass
            return []

    async def replace_member_scopes(
        self,
        session: AsyncSession,
        tenant_id: str,
        member_user_id: str,
        scopes: list[dict],
    ) -> bool:
        if not await self._table_exists(session, "operator_member_scopes"):
            return False
        try:
            await session.execute(
                text(
                    """
                    DELETE FROM operator_member_scopes
                    WHERE tenant_id = CAST(:tid AS uuid)
                      AND member_user_id = CAST(:uid AS uuid)
                    """
                ),
                {"tid": tenant_id, "uid": member_user_id},
            )
            for scope in scopes:
                await session.execute(
                    text(
                        """
                        INSERT INTO operator_member_scopes
                            (tenant_id, member_user_id, scope_type, portfolio_id, property_external_id,
                             can_view, can_assign, can_manage_vendors, can_manage_settings)
                        VALUES
                            (CAST(:tid AS uuid), CAST(:uid AS uuid), :scope_type,
                             CAST(NULLIF(:portfolio_id, '') AS uuid), NULLIF(:property_external_id, ''),
                             :can_view, :can_assign, :can_manage_vendors, :can_manage_settings)
                        """
                    ),
                    {
                        "tid": tenant_id,
                        "uid": member_user_id,
                        "scope_type": scope.get("scope_type") or "property",
                        "portfolio_id": scope.get("portfolio_id") or "",
                        "property_external_id": scope.get("property_external_id") or "",
                        "can_view": bool(scope.get("can_view", True)),
                        "can_assign": bool(scope.get("can_assign", False)),
                        "can_manage_vendors": bool(scope.get("can_manage_vendors", False)),
                        "can_manage_settings": bool(scope.get("can_manage_settings", False)),
                    },
                )
            await session.commit()
            return True
        except Exception as exc:
            logger.warning("[OperatorScopeService] replace_member_scopes failed: %s", exc)
            try:
                await session.rollback()
            except Exception:
                pass
            return False


_SERVICE = OperatorScopeService()


def get_operator_scope_service() -> OperatorScopeService:
    return _SERVICE
