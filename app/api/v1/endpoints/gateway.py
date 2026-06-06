"""
Integration Gateway API.

Manages operator credential onboarding for external systems:
- Breezeway
- Escapia
- Wheelhouse
"""

from datetime import date
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import TenantContext, get_tenant_context
from app.db.session import get_async_session
from app.services.connectors import (
    IntegrationProvider,
    get_escapia_sync_service,
    get_integration_credential_store,
    get_integration_registry_service,
)


router = APIRouter(prefix="/gateway", tags=["Integration Gateway"])


def _provider_connection_settings(provider: str, credentials: Dict[str, str]) -> Dict[str, Any]:
    provider_account_id = (
        credentials.get("provider_account_id")
        or credentials.get("account_id")
        or credentials.get("pmcid")
        or credentials.get("portfolio_id")
        or ""
    )
    provider_base_url = credentials.get("provider_base_url") or credentials.get("base_url") or ""
    settings: Dict[str, Any] = {
        "provider": provider,
        "provider_account_id": provider_account_id,
        "provider_base_url": provider_base_url,
    }
    if credentials.get("account_id") or credentials.get("pmcid"):
        settings["account_id"] = credentials.get("account_id") or credentials.get("pmcid") or ""
    if credentials.get("pmcid"):
        settings["pmcid"] = credentials.get("pmcid") or ""
    if credentials.get("portfolio_id"):
        settings["portfolio_id"] = credentials.get("portfolio_id") or ""
    if credentials.get("base_url"):
        settings["base_url"] = credentials.get("base_url") or ""
    return settings


class UpsertCredentialRequest(BaseModel):
    provider: IntegrationProvider
    credentials: Dict[str, str] = Field(default_factory=dict)
    label: Optional[str] = None
    test_after_save: bool = True


class TestCredentialRequest(BaseModel):
    provider: IntegrationProvider
    credentials: Optional[Dict[str, str]] = None
    use_stored_credentials: bool = True


class EscapiaSyncRequest(BaseModel):
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    trigger: str = Field(default="manual")


@router.get("/providers")
async def list_gateway_providers() -> Dict[str, Any]:
    """List supported provider schemas."""
    store = get_integration_credential_store()
    return {"providers": store.get_supported_providers()}


@router.get("/credentials")
async def list_company_credentials(
    tenant: TenantContext = Depends(get_tenant_context),
) -> Dict[str, Any]:
    """List configured providers for the authenticated tenant (masked)."""
    store = get_integration_credential_store()
    return {
        "company_id": str(tenant.company_id),
        "configured_integrations": store.list_configured(tenant.company_id),
    }


@router.post("/credentials")
async def upsert_company_credentials(
    request: UpsertCredentialRequest,
    tenant: TenantContext = Depends(get_tenant_context),
    session: AsyncSession = Depends(get_async_session),
) -> Dict[str, Any]:
    """Create or update encrypted credentials for a provider."""
    store = get_integration_credential_store()
    registry = get_integration_registry_service()
    try:
        saved = store.upsert_credentials(
            company_id=tenant.company_id,
            provider=request.provider,
            credentials=request.credentials,
            label=request.label,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    await registry.ensure_connection(
        session=session,
        tenant_id=tenant.company_id,
        provider=request.provider.value,
        display_name=request.label or request.provider.value.title(),
        credential_ref=f"gateway:{request.provider.value}:{tenant.company_id}",
        settings=_provider_connection_settings(request.provider.value, request.credentials),
    )

    test_result = None
    if request.test_after_save:
        test_result = store.test_connection(request.provider, request.credentials)

    return {
        "saved": saved,
        "test_result": test_result,
    }


@router.post("/credentials/test")
async def test_company_credentials(
    request: TestCredentialRequest,
    tenant: TenantContext = Depends(get_tenant_context),
) -> Dict[str, Any]:
    """Validate stored or provided credentials for a provider."""
    store = get_integration_credential_store()
    creds = request.credentials or {}

    if request.use_stored_credentials:
        try:
            creds = store.get_credentials(tenant.company_id, request.provider)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    if not creds:
        raise HTTPException(
            status_code=400,
            detail="No credentials provided. Pass credentials or set use_stored_credentials=true with existing provider credentials.",
        )

    result = store.test_connection(request.provider, creds)
    return {
        "company_id": str(tenant.company_id),
        "provider": request.provider.value,
        "result": result,
    }


@router.post("/sync/escapia")
async def sync_escapia(
    request: EscapiaSyncRequest,
    tenant: TenantContext = Depends(get_tenant_context),
    session: AsyncSession = Depends(get_async_session),
) -> Dict[str, Any]:
    """
    Trigger Escapia pull for the authenticated tenant.

    Stores raw records per tenant for downstream normalization/analytics.
    """
    store = get_integration_credential_store()
    registry = get_integration_registry_service()
    sync_service = get_escapia_sync_service()

    try:
        credentials = store.get_credentials(tenant.company_id, IntegrationProvider.ESCAPIA)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    connection = await registry.ensure_connection(
        session=session,
        tenant_id=tenant.company_id,
        provider=IntegrationProvider.ESCAPIA.value,
        display_name="Escapia",
        credential_ref=f"gateway:escapia:{tenant.company_id}",
        settings=_provider_connection_settings("escapia", credentials),
    )
    job = await registry.start_sync_job(
        session=session,
        tenant_id=tenant.company_id,
        connection_id=connection.integration_connection_id,
        provider=IntegrationProvider.ESCAPIA.value,
        trigger=request.trigger,
        metadata_json={
            "start_date": request.start_date.isoformat() if request.start_date else None,
            "end_date": request.end_date.isoformat() if request.end_date else None,
        },
    )

    result = await sync_service.sync(
        credentials=credentials,
        start_date=request.start_date,
        end_date=request.end_date,
    )

    await registry.store_raw_records(
        session=session,
        tenant_id=tenant.company_id,
        connection_id=connection.integration_connection_id,
        provider="escapia",
        record_type="listing",
        records=result.listings,
        external_id_field="id",
    )
    await registry.store_raw_records(
        session=session,
        tenant_id=tenant.company_id,
        connection_id=connection.integration_connection_id,
        provider="escapia",
        record_type="booking",
        records=result.bookings,
        external_id_field="id",
    )
    await registry.store_raw_records(
        session=session,
        tenant_id=tenant.company_id,
        connection_id=connection.integration_connection_id,
        provider="escapia",
        record_type="calendar_day",
        records=result.calendar_days,
        external_id_field="date",
    )

    success = len(result.errors) == 0
    await registry.finish_sync_job(
        session=session,
        job=job,
        status="completed" if success else "failed",
        records_pulled=result.records_pulled,
        listings_pulled=len(result.listings),
        bookings_pulled=len(result.bookings),
        calendar_days_pulled=len(result.calendar_days),
        errors_count=len(result.errors),
        error_message="; ".join(result.errors[:3]) if result.errors else None,
    )
    await registry.update_connection_sync_state(
        session=session,
        connection=connection,
        success=success,
        error_message="; ".join(result.errors[:3]) if result.errors else None,
    )

    return {
        "company_id": str(tenant.company_id),
        "provider": "escapia",
        "sync_job_id": str(job.sync_job_id),
        "records_pulled": result.records_pulled,
        "listings_pulled": len(result.listings),
        "bookings_pulled": len(result.bookings),
        "calendar_days_pulled": len(result.calendar_days),
        "errors": result.errors,
    }


@router.get("/sync/jobs")
async def list_sync_jobs(
    provider: Optional[str] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=200),
    tenant: TenantContext = Depends(get_tenant_context),
    session: AsyncSession = Depends(get_async_session),
) -> Dict[str, Any]:
    """List recent sync jobs for the authenticated tenant."""
    registry = get_integration_registry_service()
    jobs = await registry.list_recent_jobs(
        session=session,
        tenant_id=tenant.company_id,
        provider=provider,
        limit=limit,
    )
    return {
        "company_id": str(tenant.company_id),
        "jobs": [
            {
                "sync_job_id": str(j.sync_job_id),
                "provider": j.provider,
                "status": j.status,
                "trigger": j.trigger,
                "started_at": j.started_at,
                "completed_at": j.completed_at,
                "records_pulled": j.records_pulled,
                "errors_count": j.errors_count,
                "error_message": j.error_message,
            }
            for j in jobs
        ],
    }
