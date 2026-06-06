"""
Database-backed integration connection registry.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.integrations import (
    IntegrationConnectionModel,
    IntegrationRawRecordModel,
    IntegrationSyncJobModel,
)


class IntegrationRegistryService:
    """Persists integration metadata and sync telemetry."""

    async def merge_connection_settings(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        provider: str,
        settings_patch: Optional[Dict[str, Any]] = None,
    ) -> Optional[IntegrationConnectionModel]:
        if not settings_patch:
            return await self.get_connection(session, tenant_id, provider)
        stmt = select(IntegrationConnectionModel).where(
            IntegrationConnectionModel.tenant_id == tenant_id,
            IntegrationConnectionModel.provider == provider,
            IntegrationConnectionModel.is_active.is_(True),
        )
        existing = (await session.execute(stmt)).scalar_one_or_none()
        if not existing:
            return None
        merged = dict(existing.settings or {})
        for key, value in (settings_patch or {}).items():
            if value in (None, "", [], {}):
                continue
            merged[key] = value
        existing.settings = merged
        await session.commit()
        await session.refresh(existing)
        return existing

    async def ensure_connection(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        provider: str,
        display_name: str,
        credential_ref: str,
        settings: Optional[Dict[str, Any]] = None,
    ) -> IntegrationConnectionModel:
        stmt = select(IntegrationConnectionModel).where(
            IntegrationConnectionModel.tenant_id == tenant_id,
            IntegrationConnectionModel.provider == provider,
        )
        existing = (await session.execute(stmt)).scalar_one_or_none()

        if existing:
            existing.display_name = display_name
            existing.credential_ref = credential_ref
            existing.is_active = True
            if settings:
                existing.settings = settings
            await session.commit()
            await session.refresh(existing)
            return existing

        conn = IntegrationConnectionModel(
            tenant_id=tenant_id,
            provider=provider,
            display_name=display_name,
            credential_ref=credential_ref,
            settings=settings or {},
            status="connected",
            is_active=True,
        )
        session.add(conn)
        await session.commit()
        await session.refresh(conn)
        return conn

    async def get_connection(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        provider: str,
    ) -> Optional[IntegrationConnectionModel]:
        stmt = select(IntegrationConnectionModel).where(
            IntegrationConnectionModel.tenant_id == tenant_id,
            IntegrationConnectionModel.provider == provider,
            IntegrationConnectionModel.is_active.is_(True),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def start_sync_job(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        connection_id: UUID,
        provider: str,
        trigger: str = "manual",
        metadata_json: Optional[Dict[str, Any]] = None,
    ) -> IntegrationSyncJobModel:
        job = IntegrationSyncJobModel(
            tenant_id=tenant_id,
            integration_connection_id=connection_id,
            provider=provider,
            trigger=trigger,
            status="running",
            metadata_json=metadata_json or {},
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)
        return job

    async def finish_sync_job(
        self,
        session: AsyncSession,
        job: IntegrationSyncJobModel,
        *,
        status: str,
        records_pulled: int,
        listings_pulled: int,
        bookings_pulled: int,
        calendar_days_pulled: int,
        errors_count: int,
        error_message: Optional[str] = None,
    ) -> IntegrationSyncJobModel:
        job.status = status
        job.completed_at = datetime.utcnow()
        job.records_pulled = records_pulled
        job.listings_pulled = listings_pulled
        job.bookings_pulled = bookings_pulled
        job.calendar_days_pulled = calendar_days_pulled
        job.errors_count = errors_count
        job.error_message = error_message
        await session.commit()
        await session.refresh(job)
        return job

    async def update_connection_sync_state(
        self,
        session: AsyncSession,
        connection: IntegrationConnectionModel,
        *,
        success: bool,
        error_message: Optional[str] = None,
    ) -> None:
        now = datetime.utcnow()
        connection.last_sync_at = now
        if success:
            connection.last_successful_sync_at = now
            connection.last_error = None
            connection.status = "connected"
        else:
            connection.status = "degraded"
            connection.last_error = error_message
        await session.commit()

    async def store_raw_records(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        connection_id: UUID,
        provider: str,
        record_type: str,
        records: List[Dict[str, Any]],
        external_id_field: Optional[str] = None,
    ) -> int:
        if not records:
            return 0

        to_add: List[IntegrationRawRecordModel] = []
        for rec in records:
            external_id = None
            if external_id_field:
                external_id = rec.get(external_id_field)
            to_add.append(
                IntegrationRawRecordModel(
                    tenant_id=tenant_id,
                    integration_connection_id=connection_id,
                    provider=provider,
                    record_type=record_type,
                    external_id=str(external_id) if external_id is not None else None,
                    payload=rec,
                )
            )

        session.add_all(to_add)
        await session.commit()
        return len(to_add)

    async def list_recent_jobs(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        provider: Optional[str] = None,
        limit: int = 20,
    ) -> List[IntegrationSyncJobModel]:
        stmt = select(IntegrationSyncJobModel).where(
            IntegrationSyncJobModel.tenant_id == tenant_id
        )
        if provider:
            stmt = stmt.where(IntegrationSyncJobModel.provider == provider)
        stmt = stmt.order_by(desc(IntegrationSyncJobModel.started_at)).limit(limit)
        return list((await session.execute(stmt)).scalars().all())


_registry: IntegrationRegistryService | None = None


def get_integration_registry_service() -> IntegrationRegistryService:
    global _registry
    if _registry is None:
        _registry = IntegrationRegistryService()
    return _registry
