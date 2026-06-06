"""
Ingestion Workers - Data intake from external sources.

These workers handle:
- PMS synchronization
- Webhook processing
- Scheduled data pulls
- Manual uploads

Jobs:
- Fetch listings
- Fetch bookings
- Fetch guest messages
- Fetch pricing history

All data flows through normalization before hitting the canonical schema.
"""

import asyncio
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import Field

from app.core.db_connect import create_configured_async_engine
from workers.base import (
    BaseWorker,
    JobPayload,
    JobResult,
    WorkerCategory,
    register_worker,
)


# =============================================================================
# PAYLOADS
# =============================================================================

class PMSIngestPayload(JobPayload):
    """Payload for PMS data ingestion."""
    pms_provider: str  # guesty, hostaway, etc.
    credentials_vault_key: str  # Reference to encrypted credentials
    
    # Scope (what to fetch)
    fetch_listings: bool = True
    fetch_bookings: bool = True
    fetch_calendar: bool = True
    fetch_messages: bool = False
    
    # Date range for bookings/calendar
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    
    # Specific property (if not fetching all)
    property_id: Optional[UUID] = None


class ListingSyncPayload(JobPayload):
    """Payload for syncing a specific listing."""
    listing_id: UUID
    pms_provider: str
    external_id: str
    
    sync_calendar: bool = True
    sync_pricing: bool = True
    days_ahead: int = 365


class BookingIngestPayload(JobPayload):
    """Payload for fetching bookings."""
    pms_provider: str
    credentials_vault_key: str
    
    start_date: date
    end_date: date
    
    # Optional filters
    property_ids: Optional[List[UUID]] = None
    statuses: Optional[List[str]] = None


class MessageIngestPayload(JobPayload):
    """Payload for fetching messages."""
    pms_provider: str
    credentials_vault_key: str
    
    # Scope
    thread_ids: Optional[List[str]] = None
    since_timestamp: Optional[datetime] = None
    
    # Limits
    max_threads: int = 100
    max_messages_per_thread: int = 50


class WebhookPayload(JobPayload):
    """Payload for processing incoming webhooks."""
    pms_provider: str
    event_type: str  # booking_created, listing_updated, etc.
    event_data: Dict[str, Any]
    received_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Webhook metadata
    webhook_id: Optional[str] = None
    signature: Optional[str] = None


# =============================================================================
# WORKERS
# =============================================================================

@register_worker
class PMSIngestWorker(BaseWorker[PMSIngestPayload]):
    """
    Main PMS ingestion worker.
    
    Orchestrates full sync from a PMS provider:
    1. Connect to PMS
    2. Fetch listings (creates/updates properties)
    3. Fetch bookings for date range
    4. Fetch calendar/pricing
    5. Queue normalization jobs
    """
    
    name = "pms_ingest_worker"
    category = WorkerCategory.INGESTION
    max_retries = 3
    timeout_seconds = 600  # 10 minutes for full sync
    
    async def process(self, payload: PMSIngestPayload) -> JobResult:
        from app.services.connectors.pms_connectors import PMSConnectorFactory, PMSProvider
        
        items_processed = 0
        warnings = []
        
        try:
            # Get connector
            provider = PMSProvider(payload.pms_provider)
            connector = PMSConnectorFactory.create_connector(
                provider=provider,
                tenant_id=payload.tenant_id,
                credentials_key=payload.credentials_vault_key,
            )
            
            # Test connection
            if not await connector.test_connection():
                return JobResult(
                    success=False,
                    error="Failed to connect to PMS"
                )
            
            results = {
                "listings": [],
                "bookings": [],
                "calendar_days": [],
            }
            
            # Fetch listings
            if payload.fetch_listings:
                listings = await connector.fetch_listings()
                results["listings"] = [l.dict() for l in listings]
                items_processed += len(listings)
                self.logger.info(f"Fetched {len(listings)} listings")

                # ── Write to canonical properties table + vector store ─────────
                # PropertyImportService upserts DB rows (no duplicates on re-run)
                # and re-indexes vectors so the concierge reads from a single
                # source of truth rather than ephemeral in-memory structures.
                if listings:
                    try:
                        from app.services.property_import_service import PropertyImportService
                        from sqlalchemy.ext.asyncio import (
                            AsyncSession as _AS,
                        )
                        from app.core.config import get_settings as _cfg
                        _settings = _cfg()
                        _engine = create_configured_async_engine(_settings.database_url, echo=False)
                        async with _AS(_engine) as _import_db:
                            _svc = PropertyImportService(_import_db)
                            _import_res = await _svc.import_from_pms_listings(
                                operator_id=str(payload.tenant_id),
                                company_id=str(payload.tenant_id),
                                market_id=None,  # resolved by OperatorMarketDetectWorker below
                                listings=listings,
                            )
                        await _engine.dispose()
                        self.logger.info(
                            "PMSIngest: DB write done — inserted=%d updated=%d "
                            "vector=%d errors=%d",
                            _import_res.inserted, _import_res.updated,
                            _import_res.vector_indexed, len(_import_res.errors),
                        )
                        results["property_import"] = {
                            "inserted":       _import_res.inserted,
                            "updated":        _import_res.updated,
                            "vector_indexed": _import_res.vector_indexed,
                            "errors":         _import_res.errors,
                        }
                    except Exception as _imp_exc:
                        warnings.append(f"property_import failed (non-fatal): {_imp_exc}")
                        self.logger.warning(
                            "PMSIngest: property import failed (non-fatal): %s", _imp_exc
                        )

                # ── Market detection: fire after first property import ────────
                # Pull addresses from the freshly fetched listings and queue
                # OperatorMarketDetectWorker to resolve the market and kick off
                # an event scrape so concierge has local data from day one.
                if listings:
                    addresses = [
                        " ".join(filter(None, [
                            getattr(l, "address_line1", None),
                            getattr(l, "city", None),
                            getattr(l, "state", None),
                        ]))
                        for l in listings
                        if getattr(l, "city", None)
                    ]
                    if addresses:
                        from workers.ingestion.event_workers import (
                            OperatorMarketDetectWorker,
                            OperatorMarketDetectPayload,
                        )
                        detect_worker = OperatorMarketDetectWorker()
                        asyncio.ensure_future(
                            detect_worker.process(
                                OperatorMarketDetectPayload(
                                    tenant_id         = payload.tenant_id,
                                    operator_id       = str(payload.tenant_id),
                                    operator_name     = str(payload.tenant_id),
                                    property_addresses= addresses[:10],
                                )
                            )
                        )
            
            # Fetch bookings
            if payload.fetch_bookings:
                start = payload.start_date or date.today() - timedelta(days=90)
                end = payload.end_date or date.today() + timedelta(days=365)
                
                bookings = await connector.fetch_bookings(start, end)
                results["bookings"] = [b.dict() for b in bookings]
                items_processed += len(bookings)
                self.logger.info(f"Fetched {len(bookings)} bookings")
            
            # Fetch calendar
            if payload.fetch_calendar and results["listings"]:
                for listing_data in results["listings"][:10]:  # Limit for now
                    try:
                        calendar = await connector.fetch_calendar(
                            listing_data["external_id"],
                            date.today(),
                            date.today() + timedelta(days=365)
                        )
                        results["calendar_days"].extend([c.dict() for c in calendar])
                        items_processed += len(calendar)
                    except Exception as e:
                        warnings.append(f"Calendar fetch failed for {listing_data['external_id']}: {e}")
            
            return JobResult(
                success=True,
                data=results,
                items_processed=items_processed,
                warnings=warnings,
            )
            
        except Exception as e:
            return JobResult(success=False, error=str(e))


@register_worker
class ListingSyncWorker(BaseWorker[ListingSyncPayload]):
    """
    Sync a single listing's calendar and pricing.

    Used for:
    - Real-time availability updates
    - Price change detection
    - Gap identification
    """

    name = "listing_sync_worker"
    category = WorkerCategory.INGESTION
    max_retries = 3
    timeout_seconds = 120

    async def process(self, payload: ListingSyncPayload) -> JobResult:
        from app.services.connectors.pms_connectors import PMSConnectorFactory, PMSProvider

        try:
            provider = PMSProvider(payload.pms_provider)
            connector = PMSConnectorFactory.create_connector(
                provider=provider,
                tenant_id=payload.tenant_id,
                credentials_key=payload.credentials_vault_key if hasattr(payload, "credentials_vault_key") else "",
            )

            calendar_days = 0
            if payload.sync_calendar:
                start = date.today()
                end = date.today() + timedelta(days=payload.days_ahead)
                cal = await connector.fetch_calendar(payload.external_id, start, end)
                calendar_days = len(cal)
                self.logger.info(
                    "ListingSyncWorker: fetched %d calendar days for %s",
                    calendar_days, payload.external_id,
                )

            return JobResult(
                success=True,
                data={
                    "listing_id": str(payload.listing_id),
                    "external_id": payload.external_id,
                    "calendar_days_synced": calendar_days,
                    "synced_at": datetime.utcnow().isoformat(),
                },
                items_processed=calendar_days,
            )
        except Exception as exc:
            self.logger.error("ListingSyncWorker error for %s: %s", payload.external_id, exc)
            return JobResult(success=False, error=str(exc))


@register_worker
class BookingIngestWorker(BaseWorker[BookingIngestPayload]):
    """
    Fetch bookings for a date range.

    Used for:
    - Initial historical import
    - Periodic catch-up syncs
    - Gap filling after outages
    """

    name = "booking_ingest_worker"
    category = WorkerCategory.INGESTION
    max_retries = 3
    timeout_seconds = 300

    async def process(self, payload: BookingIngestPayload) -> JobResult:
        from app.services.connectors.pms_connectors import PMSConnectorFactory, PMSProvider

        try:
            provider = PMSProvider(payload.pms_provider)
            connector = PMSConnectorFactory.create_connector(
                provider=provider,
                tenant_id=payload.tenant_id,
                credentials_key=payload.credentials_vault_key,
            )

            bookings = await connector.fetch_bookings(
                payload.start_date,
                payload.end_date,
            )

            # Optional: filter by property_ids if provided
            if payload.property_ids:
                property_id_strs = {str(pid) for pid in payload.property_ids}
                bookings = [
                    b for b in bookings
                    if str(getattr(b, "external_id", "")) in property_id_strs
                       or str(getattr(b, "property_id", "")) in property_id_strs
                ]

            # Optional: filter by status
            if payload.statuses:
                bookings = [
                    b for b in bookings
                    if getattr(b, "status", None) in payload.statuses
                ]

            self.logger.info(
                "BookingIngestWorker: fetched %d bookings (%s → %s) for tenant %s",
                len(bookings), payload.start_date, payload.end_date, payload.tenant_id,
            )

            return JobResult(
                success=True,
                data={
                    "start_date": payload.start_date.isoformat(),
                    "end_date": payload.end_date.isoformat(),
                    "bookings": [b.dict() if hasattr(b, "dict") else vars(b) for b in bookings],
                },
                items_processed=len(bookings),
            )
        except Exception as exc:
            self.logger.error("BookingIngestWorker error: %s", exc)
            return JobResult(success=False, error=str(exc))


@register_worker
class MessageIngestWorker(BaseWorker[MessageIngestPayload]):
    """
    Fetch guest messages from PMS.

    Used for:
    - Concierge context building
    - Intent extraction
    - Response suggestions
    """

    name = "message_ingest_worker"
    category = WorkerCategory.INGESTION
    max_retries = 3
    timeout_seconds = 300

    async def process(self, payload: MessageIngestPayload) -> JobResult:
        from app.services.connectors.pms_connectors import PMSConnectorFactory, PMSProvider

        try:
            provider = PMSProvider(payload.pms_provider)
            connector = PMSConnectorFactory.create_connector(
                provider=provider,
                tenant_id=payload.tenant_id,
                credentials_key=payload.credentials_vault_key,
            )

            # fetch_messages is not on the base PMSConnector ABC —
            # check if the specific connector implements it.
            fetch_fn = getattr(connector, "fetch_messages", None)
            if fetch_fn is None:
                return JobResult(
                    success=True,
                    data={"skipped": True, "reason": f"{payload.pms_provider} connector does not implement fetch_messages yet"},
                    items_processed=0,
                )

            threads = await fetch_fn(
                thread_ids=payload.thread_ids,
                since_timestamp=payload.since_timestamp,
                max_threads=payload.max_threads,
                max_messages_per_thread=payload.max_messages_per_thread,
            )

            total_messages = sum(
                len(t.get("messages", [])) if isinstance(t, dict) else getattr(t, "message_count", 1)
                for t in threads
            )

            self.logger.info(
                "MessageIngestWorker: fetched %d threads / %d messages for tenant %s",
                len(threads), total_messages, payload.tenant_id,
            )

            return JobResult(
                success=True,
                data={
                    "threads_fetched": len(threads),
                    "messages_fetched": total_messages,
                    "threads": [t if isinstance(t, dict) else vars(t) for t in threads],
                },
                items_processed=total_messages,
            )
        except Exception as exc:
            self.logger.error("MessageIngestWorker error: %s", exc)
            return JobResult(success=False, error=str(exc))


@register_worker
class WebhookProcessorWorker(BaseWorker[WebhookPayload]):
    """
    Process incoming webhooks from PMS providers.
    
    Handles:
    - booking_created
    - booking_updated
    - booking_cancelled
    - listing_updated
    - message_received
    """
    
    name = "webhook_processor_worker"
    category = WorkerCategory.INGESTION
    max_retries = 5  # More retries for webhooks
    timeout_seconds = 60
    
    async def process(self, payload: WebhookPayload) -> JobResult:
        event_type = payload.event_type
        event_data = payload.event_data
        
        self.logger.info(
            f"Processing webhook: {event_type} from {payload.pms_provider}"
        )
        
        # Route to appropriate handler
        handlers = {
            "booking_created": self._handle_booking_created,
            "booking_updated": self._handle_booking_updated,
            "booking_cancelled": self._handle_booking_cancelled,
            "listing_updated": self._handle_listing_updated,
            "message_received": self._handle_message_received,
        }
        
        handler = handlers.get(event_type)
        if not handler:
            return JobResult(
                success=True,
                data={"skipped": True, "reason": f"Unknown event type: {event_type}"}
            )
        
        return await handler(payload.tenant_id, event_data)
    
    async def _handle_booking_created(
        self,
        tenant_id: UUID,
        data: Dict[str, Any],
    ) -> JobResult:
        """Persist new booking to concierge_guest_sessions + journey tables."""
        from sqlalchemy.ext.asyncio import AsyncSession
        from app.core.config import get_settings

        booking_id   = data.get("booking_id") or data.get("id")
        property_code = data.get("unit_code") or data.get("property_code") or data.get("listing_id")
        guest_email  = data.get("guest_email") or data.get("primary_guest", {}).get("email")
        guest_name   = (
            data.get("guest_name")
            or f"{data.get('primary_guest', {}).get('first_name', '')} "
               f"{data.get('primary_guest', {}).get('last_name', '')}".strip()
        )
        check_in     = data.get("check_in") or data.get("arrival")
        check_out    = data.get("check_out") or data.get("departure")

        if not booking_id:
            return JobResult(success=True, data={"skipped": True, "reason": "no booking_id in payload"})

        try:
            from sqlalchemy import text as _t
            settings = get_settings()
            engine = create_configured_async_engine(settings.database_url, echo=False)
            async with AsyncSession(engine) as db:
                await db.execute(
                    _t("""
                        INSERT INTO concierge_guest_sessions
                            (id, tenant_id, booking_id, property_code,
                             guest_email, guest_name, check_in, check_out,
                             status, created_at, updated_at)
                        VALUES
                            (gen_random_uuid(), :tid, :bid, :pcode,
                             :email, :name, :ci, :co,
                             'upcoming', NOW(), NOW())
                        ON CONFLICT (booking_id) DO UPDATE SET
                            property_code = EXCLUDED.property_code,
                            guest_email   = COALESCE(EXCLUDED.guest_email, concierge_guest_sessions.guest_email),
                            guest_name    = COALESCE(EXCLUDED.guest_name,  concierge_guest_sessions.guest_name),
                            check_in      = COALESCE(EXCLUDED.check_in,    concierge_guest_sessions.check_in),
                            check_out     = COALESCE(EXCLUDED.check_out,   concierge_guest_sessions.check_out),
                            updated_at    = NOW()
                    """),
                    {"tid": str(tenant_id), "bid": booking_id, "pcode": property_code,
                     "email": guest_email, "name": guest_name, "ci": check_in, "co": check_out},
                )
                await db.commit()
            await engine.dispose()
        except Exception as exc:
            self.logger.warning("booking_created DB write failed (non-fatal): %s", exc)

        return JobResult(
            success=True,
            data={"action": "booking_created", "booking_id": booking_id},
            items_processed=1,
        )

    async def _handle_booking_updated(
        self,
        tenant_id: UUID,
        data: Dict[str, Any],
    ) -> JobResult:
        """Update existing guest session row on PMS booking change."""
        booking_id = data.get("booking_id") or data.get("id")
        if not booking_id:
            return JobResult(success=True, data={"skipped": True, "reason": "no booking_id"})

        try:
            from sqlalchemy.ext.asyncio import AsyncSession
            from sqlalchemy import text as _t
            from app.core.config import get_settings
            settings = get_settings()
            engine = create_configured_async_engine(settings.database_url, echo=False)
            async with AsyncSession(engine) as db:
                await db.execute(
                    _t("""
                        UPDATE concierge_guest_sessions
                        SET
                            check_in   = COALESCE(:ci,    check_in),
                            check_out  = COALESCE(:co,    check_out),
                            guest_name = COALESCE(:name,  guest_name),
                            updated_at = NOW()
                        WHERE booking_id = :bid AND tenant_id = :tid
                    """),
                    {
                        "bid": booking_id,
                        "tid": str(tenant_id),
                        "ci":   data.get("check_in")  or data.get("arrival"),
                        "co":   data.get("check_out") or data.get("departure"),
                        "name": data.get("guest_name"),
                    },
                )
                await db.commit()
            await engine.dispose()
        except Exception as exc:
            self.logger.warning("booking_updated DB write failed (non-fatal): %s", exc)

        return JobResult(
            success=True,
            data={"action": "booking_updated", "booking_id": booking_id},
            items_processed=1,
        )

    async def _handle_booking_cancelled(
        self,
        tenant_id: UUID,
        data: Dict[str, Any],
    ) -> JobResult:
        """Mark guest session as cancelled; emit gap signal for pricing."""
        booking_id = data.get("booking_id") or data.get("id")
        if not booking_id:
            return JobResult(success=True, data={"skipped": True, "reason": "no booking_id"})

        try:
            from sqlalchemy.ext.asyncio import AsyncSession
            from sqlalchemy import text as _t
            from app.core.config import get_settings
            settings = get_settings()
            engine = create_configured_async_engine(settings.database_url, echo=False)
            async with AsyncSession(engine) as db:
                await db.execute(
                    _t("""
                        UPDATE concierge_guest_sessions
                        SET status = 'cancelled', updated_at = NOW()
                        WHERE booking_id = :bid AND tenant_id = :tid
                    """),
                    {"bid": booking_id, "tid": str(tenant_id)},
                )
                await db.commit()
            await engine.dispose()
        except Exception as exc:
            self.logger.warning("booking_cancelled DB write failed (non-fatal): %s", exc)

        # Emit GAP_OPPORTUNITY signal so pricing engine can re-evaluate the window
        try:
            from app.mcp.registry import get_mcp_registry
            registry = get_mcp_registry()
            await registry.call("signal", "emit_signal", str(tenant_id), {
                "signal_type": "GAP_OPPORTUNITY",
                "property_code": data.get("unit_code") or data.get("property_code"),
                "context": {"booking_id": booking_id, "trigger": "cancellation"},
            })
        except Exception as exc:
            self.logger.debug("gap signal emission skipped: %s", exc)

        return JobResult(
            success=True,
            data={"action": "booking_cancelled", "booking_id": booking_id, "gap_signal_emitted": True},
            items_processed=1,
        )

    async def _handle_listing_updated(
        self,
        tenant_id: UUID,
        data: Dict[str, Any],
    ) -> JobResult:
        """Re-sync listing from PMS into properties table and re-index vectors."""
        listing_id = data.get("listing_id") or data.get("external_id")
        if not listing_id:
            return JobResult(success=True, data={"skipped": True, "reason": "no listing_id"})

        try:
            from app.services.connectors.pms_connectors import PMSConnectorFactory, PMSProvider
            from app.services.property_import_service import PropertyImportService
            from sqlalchemy.ext.asyncio import AsyncSession
            from app.core.config import get_settings

            pms_provider = data.get("pms_provider", "escapia")
            settings = get_settings()
            engine = create_configured_async_engine(settings.database_url, echo=False)
            async with AsyncSession(engine) as db:
                connector = PMSConnectorFactory.create_connector(
                    provider=PMSProvider(pms_provider),
                    tenant_id=tenant_id,
                    credentials_key=data.get("credentials_key", ""),
                )
                listings = await connector.fetch_listings()
                target = [l for l in listings if str(getattr(l, "external_id", "")) == str(listing_id)]
                if target:
                    svc = PropertyImportService(db)
                    await svc.import_from_pms_listings(
                        operator_id=str(tenant_id),
                        company_id=str(tenant_id),
                        market_id=None,
                        listings=target,
                    )
            await engine.dispose()
        except Exception as exc:
            self.logger.warning("listing_updated re-sync failed (non-fatal): %s", exc)

        return JobResult(
            success=True,
            data={"action": "listing_updated", "listing_id": listing_id},
            items_processed=1,
        )

    async def _handle_message_received(
        self,
        tenant_id: UUID,
        data: Dict[str, Any],
    ) -> JobResult:
        """Route incoming PMS message to concierge message processor."""
        booking_id = data.get("booking_id") or data.get("reservation_id")
        message_text = data.get("message") or data.get("body") or data.get("text", "")

        if not message_text:
            return JobResult(success=True, data={"skipped": True, "reason": "empty message body"})

        try:
            from app.mcp.registry import get_mcp_registry
            registry = get_mcp_registry()
            await registry.call("concierge", "handle_guest_message", str(tenant_id), {
                "booking_id":   booking_id,
                "message":      message_text,
                "channel":      "pms_webhook",
                "guest_name":   data.get("guest_name"),
                "property_code": data.get("unit_code") or data.get("property_code"),
            })
        except Exception as exc:
            self.logger.warning("concierge message routing failed (non-fatal): %s", exc)

        return JobResult(
            success=True,
            data={
                "action": "message_received",
                "booking_id": booking_id,
                "queued_for_concierge": True,
                "message_length": len(message_text),
            },
            items_processed=1,
        )
