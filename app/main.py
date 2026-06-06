"""
RentalRevenue.ai API - Main Application Entry Point.

This is the intelligence layer for professional short-term rental operators.
"""

from contextlib import asynccontextmanager
import asyncio
import logging
import time
import os
from typing import AsyncGenerator

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from app.core.config import get_settings
from app.core.exceptions import RentalRevenueException


def _scrub_sentry_event(event, hint):
    """Strip PII from Sentry events before transmission to Sentry."""
    if "request" in event:
        event["request"].pop("data", None)
        event["request"].pop("cookies", None)
    _pii_keys = {"phone", "email", "guest_phone", "guest_email", "password",
                 "wifi_password", "card_number", "token", "access_token"}
    def _scrub(obj):
        if isinstance(obj, dict):
            return {k: "[Filtered]" if k in _pii_keys else _scrub(v)
                   for k, v in obj.items()}
        if isinstance(obj, list):
            return [_scrub(i) for i in obj]
        return obj
    event["extra"] = _scrub(event.get("extra", {}))
    return event


# ── Sentry — initialize after _scrub_sentry_event is defined ──
_sentry_dsn = os.getenv("SENTRY_DSN", "")
if _sentry_dsn:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
        from sentry_sdk.integrations.redis import RedisIntegration
        sentry_sdk.init(
            dsn=_sentry_dsn,
            integrations=[
                FastApiIntegration(transaction_style="endpoint"),
                SqlalchemyIntegration(),
                RedisIntegration(),
            ],
            traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
            environment=os.getenv("ENVIRONMENT", "development"),
            send_default_pii=False,
            before_send=_scrub_sentry_event,
        )
        logging.getLogger(__name__).info("[Sentry] Error tracking initialized")
    except Exception:
        logging.getLogger(__name__).warning("[Sentry] sentry-sdk not available")
from app.services.observability.watch_layer import init_watch_layer
from app.services.observability.startup_checks import run_startup_checks
from app.services.observability.slo_metrics import (
    get_slo_thresholds,
    observe_http_request,
    render_metrics,
)
from app.api.dependencies.ops_auth import require_metrics_access
from app.api.v1 import router as api_v1_router
from app.api.v1.endpoints.mobile_v2 import router as mobile_router  # DB-backed canonical guest interface
from app.api.v1.endpoints.operator_onboarding import router as onboarding_ui_router  # /onboarding-setup + /operators
from app.api.v1.endpoints.operator_dashboard import router as operator_dashboard_router  # /operator-dashboard HTML (legacy)
from app.api.v1.endpoints.operator_tour import router as operator_tour_router  # public operator product tour
from app.api.v1.endpoints.operator_app import router as operator_app_router    # authenticated operator application at /app
from app.api.v1.endpoints.operator_prebooking import router as operator_prebooking_router  # /app/api/inquiries
from app.api.v1.endpoints.operator_knowledge_proposals import router as operator_knowledge_proposals_router  # /app/api/knowledge-proposals
from app.api.v1.endpoints.operator_filtered_recovery import router as operator_filtered_recovery_router  # /app/api/filtered
from app.api.v1.endpoints.operator_dashboard_api import router as operator_dashboard_api_router
from app.api.v1.endpoints.operator_dashboard_v2_api import router as operator_dashboard_v2_api_router
from app.api.v1.endpoints.admin_llm_usage import router as admin_llm_usage_router  # /app/api/admin/llm-usage
from app.api.v1.endpoints.prebooking_page import router as prebooking_page_router  # /app/pre-booking
from app.api.v1.endpoints.landing import router as landing_router  # legacy demo chat endpoint only
from app.api.v1.endpoints.public_landing import router as public_landing_router  # new public marketing site at /
from app.api.v1.endpoints.group_join import router as group_join_router  # /c/join/{token} multi-guest
from app.api.v1.endpoints.operator_signup import router as operator_signup_router  # /signup + /onboarding + /app/gmail-callback
from app.api.v1.endpoints.admin_seed import router as admin_seed_router  # /app/api/admin/seed-beach-habitats
from app.api.v1.endpoints.engine import router as engine_router  # /engine — architecture page
from app.api.v1.endpoints.privacy import router as privacy_router  # /privacy + /security
from app.api.v1.endpoints.audit import router as audit_router      # /api/v1/audit/*
from app.api.v1.endpoints.market_intelligence import router as market_router  # /api/v1/market/*
# Stripe billing — optional, graceful degradation if not configured
try:
    from app.api.v1.endpoints.stripe_billing import router as billing_router
    _billing_enabled = True
except Exception as _e:
    billing_router = None
    _billing_enabled = False
    logging.getLogger(__name__).warning(f"[Billing] Stripe billing disabled: {_e}")

# MFA — optional, graceful degradation if pyotp not installed
try:
    from app.core.totp_mfa import mfa_router
    _mfa_enabled = True
except Exception as _e:
    mfa_router = None
    _mfa_enabled = False
    logging.getLogger(__name__).warning(f"[MFA] TOTP MFA disabled: {_e}")

settings = get_settings()
logger = logging.getLogger(__name__)


def _try_acquire_singleton_lock(path: str) -> bool:
    """Acquire a simple PID lock, reclaiming stale lockfiles when safe."""
    import os as _os
    pid = str(_os.getpid())
    try:
        _fd = _os.open(path, _os.O_CREAT | _os.O_EXCL | _os.O_WRONLY)
        with _os.fdopen(_fd, "w") as _fh:
            _fh.write(pid)
        return True
    except FileExistsError:
        try:
            with open(path, "r", encoding="utf-8") as _fh:
                existing = (_fh.read() or "").strip()
            if existing:
                try:
                    _os.kill(int(existing), 0)
                    return False
                except OSError:
                    pass
            _os.unlink(path)
            _fd = _os.open(path, _os.O_CREAT | _os.O_EXCL | _os.O_WRONLY)
            with _os.fdopen(_fd, "w") as _fh:
                _fh.write(pid)
            logger.info("Reclaimed stale worker lock at %s", path)
            return True
        except Exception:
            return False
    except Exception:
        return False


async def _run_startup_step(name: str, coro, timeout_seconds: float = 15.0):
    """Run a startup step with timeout and fail-open logging."""
    started = time.time()
    logger.info("[Startup] begin %s", name)
    try:
        result = await asyncio.wait_for(coro, timeout=timeout_seconds)
        logger.info("[Startup] done %s in %.2fs", name, time.time() - started)
        return result
    except asyncio.TimeoutError:
        logger.warning("[Startup] timeout %s after %.2fs; continuing", name, timeout_seconds)
    except Exception as exc:
        logger.exception("[Startup] failed %s: %s", name, exc)
    return None


async def _run_sync_startup_step(name: str, fn, timeout_seconds: float = 15.0):
    """Run a sync startup step in a thread with timeout and fail-open logging."""
    return await _run_startup_step(name, asyncio.to_thread(fn), timeout_seconds=timeout_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """Application lifespan - startup and shutdown."""
    # ── Critical path: only what's needed before serving requests ──
    # Everything else deferred to background tasks after yield.

    # Initialize database connection pool — required before any request
    from app.core.database import init_database
    started = time.time()
    logger.info("[Startup] begin database")
    try:
        await init_database(
            startup_deadline_seconds=75.0,
            connect_timeout_seconds=12.0,
            retry_interval_seconds=3.0,
        )
        logger.info("[Startup] done database in %.2fs", time.time() - started)
    except Exception as exc:
        logger.exception("[Startup] failed database: %s", exc)
        raise

    # Initialize session manager (Redis if available, DB fallback)
    from app.services.concierge.guest_session import init_session_manager
    await _run_startup_step("session_manager", init_session_manager(), timeout_seconds=8.0)

    # Start background workers
    _bg_tasks = set()

    async def _deferred_startup():
        """Run non-critical startup tasks after uvicorn begins serving traffic."""
        import logging as _log
        _logger = _log.getLogger("deferred_startup")
        await asyncio.sleep(2)  # Let uvicorn bind and pass healthcheck first

        # Observability
        await _run_startup_step("watch_layer", init_watch_layer(), timeout_seconds=8.0)

        # Restore market source configs
        try:
            from tools.market_scraper_builder import restore_all_catalogue_sources
            restore_all_catalogue_sources()
        except Exception as _e:
            _logger.debug(f"Market source restore skipped: {_e}")

        # MCP Registry
        from app.mcp.registry import get_mcp_registry
        registry = await _run_sync_startup_step("mcp_registry", get_mcp_registry, timeout_seconds=20.0)
        if registry is not None:
            _logger.info(f"MCP Registry initialized: {[s['name'] for s in registry.list_servers()]}")

        # Startup checks
        startup_report = await _run_startup_step(
            "startup_checks", run_startup_checks(settings), timeout_seconds=15.0
        )
        if startup_report is not None:
            for warning in startup_report.warnings:
                _logger.warning("Startup warning: %s", warning)
            if startup_report.failures:
                _logger.error("Startup failures: %s", startup_report.failures)

        # Escalation preload
        from app.services.concierge.escalation_service import get_escalation_service
        esc_svc = get_escalation_service()
        esc_loaded = await _run_startup_step(
            "escalation_preload", esc_svc.load_pending_from_db(), timeout_seconds=12.0
        )
        _logger.info(f"Escalation service: loaded {0 if esc_loaded is None else esc_loaded} pending tickets")

    _bg_tasks.add(asyncio.create_task(_deferred_startup()))

    async def _phase_update_worker():
        """Nightly: recalculate session phases based on today's date."""
        import logging as _log
        _logger = _log.getLogger("phase_worker")
        while True:
            try:
                await asyncio.sleep(3600)  # run every hour
                from app.services.concierge.db_session_service import (
                    DatabaseSessionService, DEFAULT_TENANT_ID
                )
                from app.core.database import get_db_session
                from sqlalchemy import select
                from db.models.concierge_sessions import ConciergeGuestSessionModel
                svc = DatabaseSessionService(DEFAULT_TENANT_ID)
                async with get_db_session() as db:
                    rows = list((await db.execute(
                        select(ConciergeGuestSessionModel).where(
                            ConciergeGuestSessionModel.tenant_id == DEFAULT_TENANT_ID,
                            ConciergeGuestSessionModel.status == "active",
                        )
                    )).scalars())
                    for row in rows:
                        await svc.update_session_phase(db, row.session_id)
                _logger.info(f"Phase worker: updated {len(rows)} sessions")
            except asyncio.CancelledError:
                break
            except Exception as e:
                _logger.warning(f"Phase worker error: {e}")

    # ── Daily data retention worker (SOC 2 A1, GDPR Article 5) ───────────────
    async def _retention_worker():
        """Daily: enforce data retention policies (3am UTC)."""
        import logging as _log
        from datetime import datetime, timedelta
        _logger = _log.getLogger("retention_worker")
        while True:
            try:
                # Sleep until next 3am UTC
                now = datetime.utcnow()
                next_run = now.replace(hour=3, minute=0, second=0, microsecond=0)
                if next_run <= now:
                    next_run += timedelta(days=1)
                sleep_secs = (next_run - now).total_seconds()
                _logger.info(f"[Retention] Next run in {sleep_secs/3600:.1f} hours")
                await asyncio.sleep(sleep_secs)
                try:
                    from app.core.data_retention import run_retention
                    results = await run_retention()
                except Exception as _re:
                    _logger.error(f"[Retention] Import/run failed: {_re}")
                    results = {"errors": [str(_re)]}
                _logger.info(f"[Retention] Complete: {results}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                _logger.error(f"[Retention] Worker error: {e}")
                await asyncio.sleep(3600)  # Retry in 1 hour on error

    # ── Market intelligence + event monitoring ───────────────────────────
    async def _market_intelligence_worker():
        """Continuous: monitors all operator markets for events, alerts, conditions."""
        import logging as _log
        _logger = _log.getLogger("market_intel_worker")
        await asyncio.sleep(30)  # Let the app fully start first

        async def _properties_has_market_columns(db) -> bool:
            from sqlalchemy import text as _text

            result = await db.execute(_text("""
                SELECT COUNT(*) FROM information_schema.columns
                WHERE table_name = 'properties'
                  AND column_name IN ('market_id', 'market_type')
            """))
            return (result.scalar() or 0) >= 2

        while True:
            try:
                from app.core.database import get_db_session
                from app.services.agents.market_intelligence.market_agent import get_market_agent
                async with get_db_session() as db:
                    agent = await get_market_agent(db)
                    has_market_columns = await _properties_has_market_columns(db)
                    if has_market_columns:
                        # Build dynamic MARKET_CONFIGS from all active operators in DB
                        from sqlalchemy import text as _text
                        rows = await db.execute(_text("""
                            SELECT DISTINCT market_id, market_type
                            FROM properties
                            WHERE market_id IS NOT NULL AND deleted_at IS NULL
                        """))
                        for row in rows.mappings().all():
                            mid = row["market_id"]
                            if mid and mid not in agent.MARKET_CONFIGS:
                                agent.MARKET_CONFIGS[mid] = {
                                    "name": mid.replace("MARKET_", "").replace("_", " ").title(),
                                    "type": row.get("market_type", "city"),
                                    "event_sources": ["eventbrite"],
                                }
                    else:
                        _logger.info("[MarketIntel] Skipping property market scan until properties.market_id and market_type exist")
                    await agent.start_monitoring(interval_minutes=60)
                    # Inject DB session into neighborhood_intel MCP
                    from app.mcp.registry import get_mcp_registry
                    registry = get_mcp_registry()
                    ni_server = registry._servers.get("neighborhood_intel")
                    if ni_server:
                        ni_server.set_db_session(db)
                _logger.info("[MarketIntel] Monitoring started for %d markets",
                             len(agent.MARKET_CONFIGS))
                # Weekly: refresh Places API + event data for all operators
                while True:
                    await asyncio.sleep(7 * 24 * 3600)  # 7 days
                    try:
                        from app.core.database import get_db_session as _gds
                        from app.services.knowledge.places_pipeline import run_weekly_places_refresh
                        from app.services.scrapers.event_scraper import run_weekly_event_refresh
                        async with _gds() as db2:
                            await run_weekly_places_refresh(db2)
                            await run_weekly_event_refresh(db2)
                            # Refresh neighborhood events from all cached sources
                            from app.mcp.registry import get_mcp_registry as _reg
                            _registry = _reg()
                            _ni = _registry._servers.get("neighborhood_intel")
                            if _ni:
                                _ni.set_db_session(db2)
                                from app.mcp.servers.neighborhood_intel_mcp import get_source_cache
                                cache = get_source_cache()
                                await cache.load_from_db(db2)
                                if await _properties_has_market_columns(db2):
                                    # Re-scrape events from all valid cached sources
                                    from sqlalchemy import text as _t2
                                    _ops = await db2.execute(_t2("""
                                        SELECT DISTINCT tenant_id, market_id
                                        FROM properties WHERE deleted_at IS NULL
                                    """))
                                    for _op_row in _ops.mappings().all():
                                        _sources = cache.get_for_market(_op_row["market_id"] or "")
                                        _slugs = {s.neighborhood_slug for s in _sources if s.is_valid}
                                        for _slug in _slugs:
                                            await _registry.call(
                                                "neighborhood_intel",
                                                "get_neighborhood_events",
                                                _op_row["tenant_id"],
                                                {
                                                    "neighborhood_slug": _slug,
                                                    "market_id": _op_row["market_id"],
                                                    "operator_id": _op_row["tenant_id"],
                                                    "days_ahead": 90,
                                                },
                                            )
                                else:
                                    _logger.info("[MarketIntel] Skipping weekly property market refresh until market columns exist")
                        _logger.info("[MarketIntel] Weekly refresh complete")
                    except Exception as _e:
                        _logger.warning("[MarketIntel] Weekly refresh error: %s", _e)
            except asyncio.CancelledError:
                break
            except Exception as e:
                _logger.warning("[MarketIntel] Worker error: %s", e)
                await asyncio.sleep(300)  # Back off 5 min on error

    # ── Daily event scraper worker ───────────────────────────────────
    async def _event_scraper_worker():
        """Daily at 2am UTC: scrape all active markets in market_registry."""
        import logging as _log
        from datetime import datetime, timedelta
        _logger = _log.getLogger("event_scraper_worker")
        await asyncio.sleep(60)  # Let app fully start first

        async def _run_scrape():
            """Run the event scrape for all active markets from market_registry."""
            try:
                from tools.event_scraper import EventScrapeOrchestrator
                async with EventScrapeOrchestrator(days_ahead=90) as orc:
                    # scrape_all_markets() reads market_registry for all enabled markets
                    # and derives geography/sources from each row — no hardcoding
                    results = await orc.scrape_all_markets()
                total = sum(v for v in results.values() if v >= 0)
                failed = sum(1 for v in results.values() if v < 0)
                _logger.info(
                    f"[EventScraper] Run complete — {total} events across "
                    f"{len(results)} markets ({failed} failed)"
                )
                return results
            except Exception as e:
                _logger.error(f"[EventScraper] Run failed: {e}")
                return {}

        # Run once on startup to catch up from any gap since last scrape
        # Disabled on startup to avoid delaying healthcheck — daily cron handles it
        # try:
        #     await _run_scrape()
        # except Exception as _e:
        #     _logger.warning(f"[EventScraper] Startup scrape failed: {_e}")

        # Then run daily at 2am UTC
        while True:
            try:
                now = datetime.utcnow()
                next_run = now.replace(hour=2, minute=0, second=0, microsecond=0)
                if next_run <= now:
                    next_run += timedelta(days=1)
                sleep_secs = (next_run - now).total_seconds()
                _logger.info(
                    f"[EventScraper] Next run in {sleep_secs/3600:.1f}h "
                    f"at {next_run.strftime('%Y-%m-%d %H:%M')} UTC"
                )
                await asyncio.sleep(sleep_secs)
                await _run_scrape()
            except asyncio.CancelledError:
                break
            except Exception as e:
                _logger.error(f"[EventScraper] Worker error: {e}")
                await asyncio.sleep(3600)  # Retry in 1 hour on error

    # ── Operational insights worker ──────────────────────────────────
    async def _insights_worker():
        """Daily: generate operational insights per active operator tenant.
        
        Joins knowledge_gaps × sessions × market_events to surface actionable
        recommendations. Results consumed by /app/api/insights → Overview card.
        Never surfaces raw market data — only derived operator-actionable signals.
        """
        import logging as _log
        from datetime import datetime, timedelta
        _logger = _log.getLogger("insights_worker")
        await asyncio.sleep(90)  # Let app and event scraper fully start first

        while True:
            try:
                from app.core.database import get_db_session
                from sqlalchemy import text as _text
                from app.services.intelligence.insight_engine import get_insight_engine

                engine = get_insight_engine()

                # Get all active tenants with market assignments
                async with get_db_session() as db:
                    rows = (await db.execute(_text("""
                        SELECT DISTINCT p.tenant_id::text,
                               COALESCE(mr.market_id, '30a_fl') as market_id
                        FROM properties p
                        LEFT JOIN market_registry mr
                            ON mr.operator_ids @> CAST(('"' || p.tenant_id::text || '"') AS jsonb)
                        WHERE p.tenant_id IS NOT NULL
                        LIMIT 50
                    """))).fetchall()

                total_insights = 0
                for tenant_id, market_id in rows:
                    try:
                        insights = await engine.run_for_tenant(tenant_id, market_id)
                        total_insights += len(insights)
                    except Exception as _te:
                        _logger.debug(f"[Insights] Tenant {tenant_id[:8]} failed: {_te}")

                _logger.info(
                    f"[Insights] Daily run complete — {total_insights} insights "
                    f"across {len(rows)} tenants"
                )

            except asyncio.CancelledError:
                break
            except Exception as e:
                _logger.warning(f"[Insights] Worker error: {e}")

            # Run daily at 4am UTC (after event scraper at 2am)
            now = datetime.utcnow()
            next_run = now.replace(hour=4, minute=0, second=0, microsecond=0)
            if next_run <= now:
                next_run += timedelta(days=1)
            sleep_secs = (next_run - now).total_seconds()
            _logger.info(f"[Insights] Next run in {sleep_secs/3600:.1f}h")
            await asyncio.sleep(sleep_secs)

    # ── Gmail inbox polling worker ──────────────────────────────────
    async def _gmail_polling_worker():
        """Every 5 min: poll operator Gmail inboxes for guest messages."""
        import logging as _log
        _logger = _log.getLogger("gmail_poller")
        await asyncio.sleep(60)  # Let app fully start

        async def _poll_with_recent_fallback(poller):
            result = await poller.poll()
            if result.messages_found == 0 and not result.errors:
                result = await poller.poll_with_mode(query_mode="recent_inbox")
            return result

        while True:
            try:
                from app.services.integrations.gmail_inbox_poller import build_gmail_poller
                from app.core.database import get_db_session
                from app.services.concierge.db_session_service import DEFAULT_TENANT_ID

                # Poll all operators — DB-backed first, then env var fallback
                async with get_db_session() as db:

                    # ── DB-backed operators (self-service signups) ──────────
                    try:
                        from app.services.auth.operator_auth_service import get_operator_auth_service as _gas
                        import uuid as _uuid
                        from app.services.messaging.inbox_adapters import InboxAdapterConfig, build_inbox_adapter
                        all_creds = await _gas().get_all_gmail_creds(db)
                        for creds in all_creds:
                            try:
                                poller = build_inbox_adapter(
                                    InboxAdapterConfig(
                                        operator_id=creds["operator_id"],
                                        company_id=_uuid.UUID(creds["tenant_id"]),
                                        watched_email=creds["watched_email"],
                                        refresh_token=creds["refresh_token"],
                                        provider=creds.get("email_provider") or "gmail",
                                    ),
                                    db=db,
                                )
                                if not poller:
                                    continue
                                result = await _poll_with_recent_fallback(poller)
                                if result.messages_processed > 0:
                                    _logger.info(
                                        "[InboxPoller] %s (%s): processed=%d pre=%d in_stay=%d",
                                        creds["company_name"],
                                        getattr(poller, "provider", "gmail"),
                                        result.messages_processed,
                                        result.pre_booking_routed,
                                        result.in_stay_routed,
                                    )
                            except Exception as _pe:
                                _logger.warning("[GmailPoller] Operator %s poll error: %s",
                                                creds.get("company_name"), _pe)
                    except Exception as _dbe:
                        _logger.warning("[GmailPoller] DB creds load failed: %s", _dbe)

                    # ── Legacy env var operators (GMAIL_REFRESH_TOKEN env var) ─
                    poller = build_gmail_poller(
                        operator_id=str(DEFAULT_TENANT_ID),
                        company_id=DEFAULT_TENANT_ID,
                        db=db,
                        env_suffix="",
                    )
                    if poller:
                        result = await _poll_with_recent_fallback(poller)
                        if result.messages_processed > 0:
                            _logger.info(
                                "[GmailPoller] Legacy env poller: processed=%d",
                                result.messages_processed,
                            )

                    # Additional env var operators GMAIL_REFRESH_TOKEN_*
                    import os as _os
                    for key, val in _os.environ.items():
                        if key.startswith("GMAIL_REFRESH_TOKEN_") and val:
                            suffix = "_" + key[len("GMAIL_REFRESH_TOKEN_"):]
                            op_id  = key[len("GMAIL_REFRESH_TOKEN_"):].lower()
                            extra_poller = build_gmail_poller(
                                operator_id=op_id,
                                company_id=DEFAULT_TENANT_ID,
                                db=db,
                                env_suffix=suffix,
                            )
                            if extra_poller:
                                await _poll_with_recent_fallback(extra_poller)

            except asyncio.CancelledError:
                break
            except Exception as e:
                _logger.warning("[GmailPoller] Worker error: %s", e)
            await asyncio.sleep(300)  # Poll every 5 minutes

    if settings.run_gmail_polling_worker:
        _gmail_lock_path = "/tmp/.oyvoda_gmail_worker_started"
        _gmail_primary = _try_acquire_singleton_lock(_gmail_lock_path)

        if _gmail_primary:
            logger.info("Gmail polling worker enabled for this process")
            task_gmail = asyncio.create_task(_gmail_polling_worker())
            _bg_tasks.add(task_gmail)
        else:
            logger.info("Gmail polling worker skipped (secondary worker process)")
    else:
        logger.info("Gmail polling worker disabled for this web process")

    embedded_workers_enabled = settings.run_embedded_background_workers
    if (
        embedded_workers_enabled
        and os.getenv("RAILWAY_SERVICE_NAME", "").strip() == "oyvoda"
        and os.getenv("RAILWAY_PROJECT_ID")
    ):
        logger.warning(
            "Embedded background workers are disabled on the Railway API service; "
            "use the dedicated oyvoda-worker service instead."
        )
        embedded_workers_enabled = False

    if embedded_workers_enabled:
        # Only start background workers in a single process.
        # With --workers 2, each uvicorn process runs lifespan independently.
        # Use an atomic lock file so only one process wins reliably.
        _lock_path = "/tmp/.oyvoda_workers_started"
        _is_primary = _try_acquire_singleton_lock(_lock_path)

        if _is_primary:
            logger.info("Embedded background workers enabled for this process (primary worker)")
            task1 = asyncio.create_task(_phase_update_worker())
            task3 = asyncio.create_task(_retention_worker())
            task4 = asyncio.create_task(_market_intelligence_worker())
            task6 = asyncio.create_task(_event_scraper_worker())
            task7 = asyncio.create_task(_insights_worker())
            _bg_tasks.update({task1, task3, task4, task6, task7})
        else:
            logger.info("Embedded background workers skipped (secondary worker process)")
    else:
        logger.info("Embedded background workers disabled for this web process")

    yield

    # Cancel background workers on shutdown
    for t in _bg_tasks:
        t.cancel()
        try:
            await t
        except asyncio.CancelledError:
            pass
    # Shutdown
    from app.core.database import close_database
    await close_database()


# Hide API docs in production (SOC 2 CC6 — minimize attack surface)
_is_production = os.getenv("ENVIRONMENT", "development") == "production"
_docs_url = None if _is_production else "/docs"
_redoc_url = None if _is_production else "/redoc"
_openapi_url = None if _is_production else "/openapi.json"

app = FastAPI(
    title="Oyvoda API",
    description="""
    AI-powered, RCS-first guest experience platform for STR operators and boutique hotels.
    
    ## Core Capabilities
    
    - **Guest Concierge**: AI-powered guest messaging via RCS/SMS
    - **Pre-Booking Pipeline**: AI-drafted inquiry responses for Vrbo/Escapia
    - **Knowledge Base**: Property-specific RAG with gap detection
    - **Operator Dashboard**: Live sessions, escalations, SLO metrics
    
    ## Architecture
    
    Five-layer engine: SENSE → THINK → ACT → WATCH → LEARN
    """,
    version=settings.app_version,
    lifespan=lifespan,
    docs_url=_docs_url,
    redoc_url=_redoc_url,
    openapi_url=_openapi_url,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Rate limiting middleware (SOC 2 CC9 — risk mitigation) ──
# Uses slowapi if available, otherwise lightweight in-process fallback
try:
    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.util import get_remote_address
    from slowapi.errors import RateLimitExceeded
    from slowapi.middleware import SlowAPIMiddleware
    # Use in-memory storage to avoid Redis ConnectionError crashing the app
    # When Redis is available, switch storage_uri to settings.redis_url
    limiter = Limiter(
        key_func=get_remote_address,
        default_limits=[f"{settings.rate_limit_per_minute}/minute"],
        storage_uri="memory://",  # Safe fallback — no Redis dependency
    )
    app.state.limiter = limiter

    # Custom handler that handles ConnectionError safely
    def _safe_rate_limit_handler(request: Request, exc):
        return JSONResponse(
            status_code=429,
            content={"error": {"code": "RATE_LIMIT_EXCEEDED", "message": "Too many requests"}},
            headers={"Retry-After": "60"},
        )

    app.add_exception_handler(RateLimitExceeded, _safe_rate_limit_handler)
    app.add_middleware(SlowAPIMiddleware)
    logger.info("[RateLimit] slowapi initialized (memory storage)")
except ImportError:
    # Fallback: simple in-process rate limiter
    import collections
    import threading
    _rate_store: dict = collections.defaultdict(list)
    _rate_lock = threading.Lock()

    @app.middleware("http")
    async def _simple_rate_limiter(request: Request, call_next):
        if request.url.path.startswith("/static/") or request.url.path == "/favicon.ico":
            return await call_next(request)
        ip = request.client.host if request.client else "unknown"
        now = time.time()
        window = 60  # 1 minute
        limit = settings.rate_limit_per_minute
        # Stricter limit for login
        if "/auth/login" in request.url.path:
            limit = settings.rate_limit_login_per_minute
        with _rate_lock:
            _rate_store[ip] = [t for t in _rate_store[ip] if now - t < window]
            if len(_rate_store[ip]) >= limit:
                return JSONResponse(
                    status_code=429,
                    content={"error": {"code": "RATE_LIMIT_EXCEEDED",
                                       "message": "Too many requests"}},
                    headers={"Retry-After": "60"},
                )
            _rate_store[ip].append(now)
        return await call_next(request)
    logger.info("[RateLimit] Using in-process fallback (install slowapi for Redis-backed limiting)")


@app.middleware("http")
async def slo_metrics_middleware(request: Request, call_next):
    start = time.perf_counter()
    try:
        response = await call_next(request)
        status_code = response.status_code
    except Exception:
        observe_http_request(
            path=request.url.path,
            method=request.method,
            status_code=500,
            duration_s=time.perf_counter() - start,
        )
        raise

    observe_http_request(
        path=request.url.path,
        method=request.method,
        status_code=status_code,
        duration_s=time.perf_counter() - start,
    )

    if request.url.path.startswith("/static/dashboard-v2/dist/assets/"):
        if request.url.path.endswith(".js"):
            response.headers["Content-Type"] = "text/javascript; charset=utf-8"
        elif request.url.path.endswith(".css"):
            response.headers["Content-Type"] = "text/css; charset=utf-8"

    # Force revalidation for both dashboard shells' JS/CSS so operators always
    # get the latest deployed code. Browsers + Cloudflare will still cache the
    # response body but must check back with origin before each use.
    # Prevents stale chunk-graph windows after each JS deploy.
    # Using explicit max-age=0 because Railway's Fastly edge will otherwise
    # append its own max-age=14400 to any response that lacks one.
    if request.url.path.startswith("/static/dashboard/js/") \
            or request.url.path.startswith("/static/dashboard/styles/") \
            or request.url.path.startswith("/static/dashboard-v2/dist/assets/"):
        response.headers["Cache-Control"] = "no-cache, no-store, max-age=0, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"

    return response


# Exception handlers
@app.exception_handler(RentalRevenueException)
async def rental_revenue_exception_handler(
    request: Request,
    exc: RentalRevenueException
) -> JSONResponse:
    """Handle custom platform exceptions."""
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.to_dict()
    )


@app.exception_handler(Exception)
async def general_exception_handler(
    request: Request,
    exc: Exception
) -> JSONResponse:
    """Handle unexpected exceptions."""
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "An unexpected error occurred",
                "details": {} if not settings.debug else {"exception": str(exc)}
            }
        }
    )


# Mount API routers
app.include_router(api_v1_router, prefix=settings.api_v1_prefix)

# Mobile guest interface at root level (for SMS links: /c/{token})
app.include_router(mobile_router)

# Operator onboarding wizard + operators CRUD at root level
# /onboarding-setup  → conversational setup wizard (HTML)
# /api/v1/operators  → also registered here for the dashboard switcher
app.include_router(onboarding_ui_router)

# Authenticated operator app at /app
app.include_router(operator_app_router)
# Pre-booking inquiry queue at /app/api/inquiries
app.include_router(operator_prebooking_router)
# Knowledge proposals review queue at /app/api/knowledge-proposals
# (brain learning loop: operator draft edits -> proposed scoped knowledge)
app.include_router(operator_knowledge_proposals_router)
# Filtered messages reassurance + recovery at /app/api/filtered
app.include_router(operator_filtered_recovery_router)
# Dashboard section APIs (KB, sessions, escalations, vendors, settings, notifications)
app.include_router(operator_dashboard_api_router)
# Dashboard v2 APIs (bootstrap, autonomy, realtime SSE)
app.include_router(operator_dashboard_v2_api_router)
# Admin dashboard LLM usage APIs at /app/api/admin/llm-usage/*
app.include_router(admin_llm_usage_router)
# Pre-booking inbox page at /app/pre-booking
app.include_router(prebooking_page_router)
# Operator product tour (public marketing)
app.include_router(operator_tour_router)
# Legacy dashboard (kept for static JS assets at /static)
app.include_router(operator_dashboard_router)

# Public marketing site at / (new)
app.include_router(public_landing_router)
# Legacy landing (demo chat endpoint still needed)
app.include_router(landing_router)
# Group join — /c/join/{token} for multi-guest share links
app.include_router(group_join_router)
# Operator signup + onboarding + Gmail OAuth callback
app.include_router(operator_signup_router)
# Admin seed endpoints (master key protected)
app.include_router(admin_seed_router)
app.include_router(engine_router)
app.include_router(privacy_router)
app.include_router(audit_router)
app.include_router(market_router)
if billing_router:
    app.include_router(billing_router)
if mfa_router:
    app.include_router(mfa_router)

# Static files — dashboard assets served from app/static/
import os as _os
_static_dir = _os.path.join(_os.path.dirname(__file__), "static")
_os.makedirs(_os.path.join(_static_dir, "dashboard"), exist_ok=True)
app.mount("/static", StaticFiles(directory=_static_dir), name="static")


# Health check — minimal response in production (SOC 2 CC6 — don't leak config)
@app.get("/health", tags=["System"])
async def health_check():
    """Health check endpoint. Returns minimal info in production."""
    if _is_production:
        return {"status": "healthy", "version": settings.app_version}
    # Development: full detail for debugging
    return {
        "status": "healthy",
        "version": settings.app_version,
        "environment": settings.environment,
        "focus_concierge_only": settings.focus_concierge_only,
        "concierge_market_signals": settings.enable_concierge_market_signals,
        "market_intel_api": settings.enable_market_intel_api,
        "watch_api": settings.enable_watch_api,
        "strict_startup_checks": settings.strict_startup_checks,
        "slo_thresholds": get_slo_thresholds(),
    }


@app.get("/metrics", tags=["System"], dependencies=[Depends(require_metrics_access)])
async def metrics():
    payload, content_type = render_metrics()
    return Response(content=payload, media_type=content_type)


@app.get("/api", tags=["System"])
async def api_root():
    """Service information endpoint."""
    return {
        "service": "Oyvoda API",
        "version": settings.app_version,
        "docs": "/docs",
        "health": "/health"
    }
