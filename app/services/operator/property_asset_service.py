from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class OperatorPropertyAssetService:
    async def upsert_asset(
        self,
        session: AsyncSession,
        tenant_id: str,
        *,
        property_code: str,
        asset_type: str,
        asset_name: str,
        manufacturer: str | None = None,
        model_number: str | None = None,
        serial_number: str | None = None,
        install_vendor_id: str | None = None,
        install_vendor_name: str | None = None,
        install_date: str | None = None,
        warranty_scope: str = "none",
        warranty_provider: str | None = None,
        warranty_start_date: str | None = None,
        warranty_end_date: str | None = None,
        parts_warranty_end_date: str | None = None,
        labor_warranty_end_date: str | None = None,
        status: str = "active",
        condition_state: str = "good",
        useful_life_years: int | None = None,
        last_service_at: str | None = None,
        last_work_order_id: str | None = None,
        notes: str = "",
        metadata: dict[str, Any] | None = None,
        asset_id: str | None = None,
    ) -> dict[str, Any]:
        if not property_code or not asset_type or not asset_name or not await self._table_exists(session, "operator_property_assets"):
            return {}
        metadata = metadata if isinstance(metadata, dict) else {}

        if asset_id:
            await session.execute(
                text(
                    """
                    UPDATE operator_property_assets
                    SET asset_type = :asset_type,
                        asset_name = :asset_name,
                        manufacturer = :manufacturer,
                        model_number = :model_number,
                        serial_number = :serial_number,
                        install_vendor_id = CASE WHEN :install_vendor_id = '' THEN install_vendor_id ELSE CAST(:install_vendor_id AS uuid) END,
                        install_vendor_name = :install_vendor_name,
                        install_date = CAST(:install_date AS date),
                        warranty_scope = :warranty_scope,
                        warranty_provider = :warranty_provider,
                        warranty_start_date = CAST(:warranty_start_date AS date),
                        warranty_end_date = CAST(:warranty_end_date AS date),
                        parts_warranty_end_date = CAST(:parts_warranty_end_date AS date),
                        labor_warranty_end_date = CAST(:labor_warranty_end_date AS date),
                        status = :status,
                        condition_state = :condition_state,
                        useful_life_years = :useful_life_years,
                        last_service_at = CAST(:last_service_at AS timestamptz),
                        last_work_order_id = CASE WHEN :last_work_order_id = '' THEN last_work_order_id ELSE CAST(:last_work_order_id AS uuid) END,
                        notes = :notes,
                        metadata_json = CAST(:metadata_json AS jsonb),
                        updated_at = NOW()
                    WHERE tenant_id = CAST(:tid AS uuid)
                      AND asset_id = CAST(:asset_id AS uuid)
                    """
                ),
                {
                    "tid": tenant_id,
                    "asset_id": asset_id,
                    "asset_type": asset_type,
                    "asset_name": asset_name,
                    "manufacturer": manufacturer,
                    "model_number": model_number,
                    "serial_number": serial_number,
                    "install_vendor_id": install_vendor_id or "",
                    "install_vendor_name": install_vendor_name,
                    "install_date": install_date,
                    "warranty_scope": warranty_scope,
                    "warranty_provider": warranty_provider,
                    "warranty_start_date": warranty_start_date,
                    "warranty_end_date": warranty_end_date,
                    "parts_warranty_end_date": parts_warranty_end_date,
                    "labor_warranty_end_date": labor_warranty_end_date,
                    "status": status,
                    "condition_state": condition_state,
                    "useful_life_years": useful_life_years,
                    "last_service_at": last_service_at,
                    "last_work_order_id": last_work_order_id or "",
                    "notes": notes,
                    "metadata_json": json.dumps(metadata),
                },
            )
            return {"asset_id": asset_id}

        existing = None
        if serial_number:
            existing = (
                await session.execute(
                    text(
                        """
                        SELECT CAST(asset_id AS text) AS asset_id
                        FROM operator_property_assets
                        WHERE tenant_id = CAST(:tid AS uuid)
                          AND property_code = :property_code
                          AND serial_number = :serial_number
                        LIMIT 1
                        """
                    ),
                    {"tid": tenant_id, "property_code": property_code, "serial_number": serial_number},
                )
            ).mappings().first()
        if existing:
            return await self.upsert_asset(
                session,
                tenant_id,
                property_code=property_code,
                asset_type=asset_type,
                asset_name=asset_name,
                manufacturer=manufacturer,
                model_number=model_number,
                serial_number=serial_number,
                install_vendor_id=install_vendor_id,
                install_vendor_name=install_vendor_name,
                install_date=install_date,
                warranty_scope=warranty_scope,
                warranty_provider=warranty_provider,
                warranty_start_date=warranty_start_date,
                warranty_end_date=warranty_end_date,
                parts_warranty_end_date=parts_warranty_end_date,
                labor_warranty_end_date=labor_warranty_end_date,
                status=status,
                condition_state=condition_state,
                useful_life_years=useful_life_years,
                last_service_at=last_service_at,
                last_work_order_id=last_work_order_id,
                notes=notes,
                metadata=metadata,
                asset_id=str(existing["asset_id"]),
            )

        created = (
            await session.execute(
                text(
                    """
                    INSERT INTO operator_property_assets
                        (tenant_id, property_code, asset_type, asset_name, manufacturer, model_number, serial_number,
                         install_vendor_id, install_vendor_name, install_date, warranty_scope, warranty_provider,
                         warranty_start_date, warranty_end_date, parts_warranty_end_date, labor_warranty_end_date,
                         status, condition_state, useful_life_years, last_service_at, last_work_order_id,
                         notes, metadata_json)
                    VALUES
                        (CAST(:tid AS uuid), :property_code, :asset_type, :asset_name, :manufacturer, :model_number, :serial_number,
                         CASE WHEN :install_vendor_id = '' THEN NULL ELSE CAST(:install_vendor_id AS uuid) END, :install_vendor_name, CAST(:install_date AS date), :warranty_scope, :warranty_provider,
                         CAST(:warranty_start_date AS date), CAST(:warranty_end_date AS date), CAST(:parts_warranty_end_date AS date), CAST(:labor_warranty_end_date AS date),
                         :status, :condition_state, :useful_life_years, CAST(:last_service_at AS timestamptz), CASE WHEN :last_work_order_id = '' THEN NULL ELSE CAST(:last_work_order_id AS uuid) END,
                         :notes, CAST(:metadata_json AS jsonb))
                    RETURNING CAST(asset_id AS text) AS asset_id
                    """
                ),
                {
                    "tid": tenant_id,
                    "property_code": property_code,
                    "asset_type": asset_type,
                    "asset_name": asset_name,
                    "manufacturer": manufacturer,
                    "model_number": model_number,
                    "serial_number": serial_number,
                    "install_vendor_id": install_vendor_id or "",
                    "install_vendor_name": install_vendor_name,
                    "install_date": install_date,
                    "warranty_scope": warranty_scope,
                    "warranty_provider": warranty_provider,
                    "warranty_start_date": warranty_start_date,
                    "warranty_end_date": warranty_end_date,
                    "parts_warranty_end_date": parts_warranty_end_date,
                    "labor_warranty_end_date": labor_warranty_end_date,
                    "status": status,
                    "condition_state": condition_state,
                    "useful_life_years": useful_life_years,
                    "last_service_at": last_service_at,
                    "last_work_order_id": last_work_order_id or "",
                    "notes": notes,
                    "metadata_json": json.dumps(metadata),
                },
            )
        ).mappings().first()
        return {"asset_id": str(created["asset_id"]) if created else ""}

    async def list_assets(self, session: AsyncSession, tenant_id: str, property_code: str) -> list[dict[str, Any]]:
        if not property_code or not await self._table_exists(session, "operator_property_assets"):
            return []
        rows = (
            await session.execute(
                text(
                    """
                    SELECT CAST(asset_id AS text) AS asset_id,
                           property_code, asset_type, asset_name, manufacturer, model_number, serial_number,
                           install_vendor_id, install_vendor_name, install_date, warranty_scope, warranty_provider,
                           warranty_start_date, warranty_end_date, parts_warranty_end_date, labor_warranty_end_date,
                           status, condition_state, useful_life_years, last_service_at, last_work_order_id,
                           notes, metadata_json, created_at, updated_at
                    FROM operator_property_assets
                    WHERE tenant_id = CAST(:tid AS uuid)
                      AND property_code = :property_code
                    ORDER BY asset_type ASC, updated_at DESC
                    """
                ),
                {"tid": tenant_id, "property_code": property_code},
            )
        ).mappings().all()
        items: list[dict[str, Any]] = []
        for row in rows:
            metadata = row.get("metadata_json")
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except Exception:
                    metadata = {}
            items.append(
                {
                    "asset_id": str(row["asset_id"]),
                    "property_code": row.get("property_code"),
                    "asset_type": row.get("asset_type"),
                    "asset_name": row.get("asset_name"),
                    "manufacturer": row.get("manufacturer"),
                    "model_number": row.get("model_number"),
                    "serial_number": row.get("serial_number"),
                    "install_vendor_id": str(row["install_vendor_id"]) if row.get("install_vendor_id") else None,
                    "install_vendor_name": row.get("install_vendor_name"),
                    "install_date": row["install_date"].isoformat() if row.get("install_date") else None,
                    "warranty_scope": row.get("warranty_scope"),
                    "warranty_provider": row.get("warranty_provider"),
                    "warranty_start_date": row["warranty_start_date"].isoformat() if row.get("warranty_start_date") else None,
                    "warranty_end_date": row["warranty_end_date"].isoformat() if row.get("warranty_end_date") else None,
                    "parts_warranty_end_date": row["parts_warranty_end_date"].isoformat() if row.get("parts_warranty_end_date") else None,
                    "labor_warranty_end_date": row["labor_warranty_end_date"].isoformat() if row.get("labor_warranty_end_date") else None,
                    "status": row.get("status"),
                    "condition_state": row.get("condition_state"),
                    "useful_life_years": row.get("useful_life_years"),
                    "last_service_at": row["last_service_at"].isoformat() if row.get("last_service_at") else None,
                    "last_work_order_id": str(row["last_work_order_id"]) if row.get("last_work_order_id") else None,
                    "notes": row.get("notes"),
                    "metadata": metadata if isinstance(metadata, dict) else {},
                    "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
                    "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
                }
            )
        return items

    async def summarize_assets(self, session: AsyncSession, tenant_id: str, property_code: str) -> dict[str, Any]:
        items = await self.list_assets(session, tenant_id, property_code)
        return {
            "count": len(items),
            "types": sorted({str(item.get("asset_type") or "") for item in items if item.get("asset_type")}),
            "items": items[:10],
        }

    async def _table_exists(self, session: AsyncSession, table_name: str) -> bool:
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


_SERVICE = OperatorPropertyAssetService()


def get_operator_property_asset_service() -> OperatorPropertyAssetService:
    return _SERVICE
