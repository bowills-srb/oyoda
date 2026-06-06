"""
Celery Tasks.

Background tasks that reduce operator toil:
- OTA market scraping (Airbnb, VRBO)
- Market event ingestion
- Experience demand refresh
- Operational snapshot refresh
- Proactive trigger evaluation
"""

import asyncio
import logging
from collections import Counter
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID

from .celery_app import celery_app

logger = logging.getLogger(__name__)


def _get_runtime_flags() -> dict:
    """Read runtime feature flags with safe defaults for worker contexts."""
    try:
        from app.core.config import get_settings

        s = get_settings()
        return {
            "focus_concierge_only": bool(getattr(s, "focus_concierge_only", False)),
            "enable_concierge_market_signals": bool(
                getattr(s, "enable_concierge_market_signals", True)
            ),
            "enable_concierge_health_checks": bool(
                getattr(s, "enable_concierge_health_checks", True)
            ),
        }
    except Exception:
        return {
            "focus_concierge_only": False,
            "enable_concierge_market_signals": True,
            "enable_concierge_health_checks": True,
        }


def _market_signals_enabled() -> bool:
    flags = _get_runtime_flags()
    if flags["focus_concierge_only"] and not flags["enable_concierge_market_signals"]:
        return False
    return True


def _run_async(coro):
    """Run a coroutine from sync Celery tasks with an isolated event loop."""
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        loop.close()
        asyncio.set_event_loop(None)


_REPLAY_DEFAULT_STATES = (
    "processed",
    "non_guest",
    "failed_retryable",
    "quarantined",
)

_REPLAY_GUEST_PARSER_PREFIXES = (
    "llm_email_extractor_",
    "ota_parser_",
)

_REPLAY_GUEST_PARSER_NAMES = {
    "generic_gmail_parser",
    "generic_microsoft_parser",
    "fallback_gmail_poller",
    "direct_website_form_parser",
    "pre_booking_transport_adapter",
}

_REPLAY_EVENT_PARSER_PREFIXES = (
    "ota_reservation_event_",
    "ota_review_event_",
    "ota_resolution_event_",
)


class _DryRunLLMExtractor:
    """Route-only extractor used by replay tasks to avoid real LLM calls."""

    async def extract(
        self,
        *,
        source_message_id: str,
        detected_shape: str,
        subject: str,
        plain_text: str,
        raw_html: str,
        headers: Dict[str, str],
    ):
        from app.services.integrations.llm_email_extractor import ExtractedEmailFields

        preview = (plain_text or subject or raw_html or "Dry-run guest inquiry preview").strip()
        if len(preview) < 8:
            preview = "Dry-run guest inquiry preview"
        return ExtractedEmailFields(
            latest_guest_message=preview[:400],
            raw_property_mention="",
            requested_check_in=None,
            requested_check_out=None,
            requested_guests=None,
            sender_email="",
            sender_name="",
            parser_source="dryrun_llm_route_only_groq",
            parser_notes=[
                "dryrun:no_external_llm_call",
                f"dryrun_detected_shape:{detected_shape or 'unknown'}",
                f"dryrun_source_message_id:{source_message_id or 'unknown'}",
            ],
        )


def _replay_route_bucket(parser_source: str, *, non_guest_reason: str = "") -> str:
    source = (parser_source or "").strip().lower()
    if non_guest_reason:
        return "non_guest"
    if source.startswith("dryrun_llm_route_only_"):
        return "llm_route"
    if source.startswith(_REPLAY_EVENT_PARSER_PREFIXES):
        return "booking_event"
    if source.startswith("ota_parser_"):
        return "deterministic_ota_parser"
    if source == "direct_website_form_parser":
        return "deterministic_direct_parser"
    if source == "vendor_ops_email_parser":
        return "vendor_ops"
    if source:
        return "fallback_or_other_parser"
    return "unknown"


def _original_looked_like_guest_inquiry(original_parser_used: str, original_route_outcome: str) -> bool:
    parser_used = (original_parser_used or "").strip().lower()
    route_outcome = (original_route_outcome or "").strip().lower()
    if parser_used.startswith(_REPLAY_GUEST_PARSER_PREFIXES):
        return True
    if parser_used in _REPLAY_GUEST_PARSER_NAMES:
        return True
    return route_outcome.startswith("pre_booking")


def _replay_discrepancy_category(
    *,
    original_parser_used: str,
    original_route_outcome: str,
    new_route_bucket: str,
) -> str:
    if not _original_looked_like_guest_inquiry(original_parser_used, original_route_outcome):
        return "none"
    if new_route_bucket == "non_guest":
        return "possible_false_positive_non_guest"
    if new_route_bucket == "booking_event":
        return "possible_false_positive_booking_event"
    return "none"


# =============================================================================
# OTA MARKET SCRAPING
# =============================================================================

@celery_app.task(bind=True, max_retries=3)
def scrape_airbnb_market(self, market_id: str):
    """
    Scrape Airbnb market data.
    
    Collects:
    - Listing inventory
    - Availability snapshots
    - Pricing signals
    - Supply/demand pressure
    
    Frequency: Daily
    """
    try:
        if not _market_signals_enabled():
            logger.info("Skipping Airbnb scrape: market signals disabled in concierge-only mode")
            return {"status": "skipped", "reason": "market signals disabled"}
        logger.info(f"Starting Airbnb scrape for market: {market_id}")
        
        from app.workers.ingestion import scrape_market
        
        # Run async scraper in sync context
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            evidence = loop.run_until_complete(scrape_market(market_id))
        finally:
            loop.close()
        
        # Persist evidence to database via signal pipeline
        if evidence:
            try:
                from app.services.signals.signal_pipeline import get_signal_pipeline
                pipeline = get_signal_pipeline()
                loop2 = asyncio.new_event_loop()
                try:
                    loop2.run_until_complete(
                        pipeline.ingest_batch([e.__dict__ if hasattr(e, '__dict__') else e for e in evidence], market_id)
                    )
                except Exception:
                    pass
                finally:
                    loop2.close()
            except Exception as persist_exc:
                logger.warning(f"Evidence persist failed (non-fatal): {persist_exc}")

        logger.info(f"Airbnb scrape complete: {len(evidence)} evidence records for {market_id}")
        return {
            "status": "success",
            "market_id": market_id,
            "evidence_count": len(evidence),
            "evidence_types": list(set(e.evidence_type for e in evidence)),
        }
        
    except Exception as e:
        logger.error(f"Airbnb scrape failed for {market_id}: {e}")
        raise self.retry(exc=e, countdown=60 * (self.request.retries + 1))


@celery_app.task(bind=True, max_retries=3)
def scrape_events_for_market(self, market_id: str):
    """
    Scrape events for a market.
    
    Collects:
    - Festivals
    - Conferences
    - Sporting events
    - Holidays
    
    Frequency: Daily
    """
    try:
        if not _market_signals_enabled():
            logger.info("Skipping event scrape: market signals disabled in concierge-only mode")
            return {"status": "skipped", "reason": "market signals disabled"}
        logger.info(f"Starting event scrape for market: {market_id}")
        
        from app.workers.ingestion import scrape_events
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            evidence = loop.run_until_complete(scrape_events(market_id))
        finally:
            loop.close()
        
        logger.info(f"Event scrape complete: {len(evidence)} evidence records for {market_id}")
        return {
            "status": "success",
            "market_id": market_id,
            "evidence_count": len(evidence),
        }
        
    except Exception as e:
        logger.error(f"Event scrape failed for {market_id}: {e}")
        raise self.retry(exc=e, countdown=60 * (self.request.retries + 1))


@celery_app.task(bind=True)
def scrape_all_markets(self):
    """
    Scrape all configured markets.
    
    Queues individual market scrapes for parallel execution.
    """
    try:
        if not _market_signals_enabled():
            logger.info("Skipping market scrape batch: market signals disabled in concierge-only mode")
            return {"status": "skipped", "reason": "market signals disabled"}
        from app.workers.ingestion import MARKET_BOUNDS
        
        markets = list(MARKET_BOUNDS.keys())
        logger.info(f"Queueing scrapes for {len(markets)} markets: {markets}")
        
        for market_id in markets:
            scrape_airbnb_market.delay(market_id)
            scrape_events_for_market.delay(market_id)
        
        return {"status": "queued", "markets": markets}
        
    except Exception as e:
        logger.error(f"Failed to queue market scrapes: {e}")
        return {"status": "error", "error": str(e)}


# =============================================================================
# MARKET EVENT INGESTION
# =============================================================================

@celery_app.task(bind=True, max_retries=3)
def ingest_market_events(self, market_ids: Optional[List[str]] = None):
    """
    Ingest market events from external sources.
    
    Sources:
    - Event calendars (festivals, conferences)
    - Sports schedules
    - Holiday calendars
    
    Frequency: Daily
    """
    try:
        if not _market_signals_enabled():
            logger.info("Skipping market event ingestion: market signals disabled in concierge-only mode")
            return {"status": "skipped", "reason": "market signals disabled"}
        logger.info("Starting market event ingestion")
        
        # Use the new event scraper
        from app.workers.ingestion import KNOWN_EVENTS
        
        if market_ids is None:
            market_ids = list(KNOWN_EVENTS.keys())
        
        for market_id in market_ids:
            scrape_events_for_market.delay(market_id)
        # For now, this is a stub that demonstrates the pattern
        
        # Example flow:
        # 1. Fetch events from external APIs
        # 2. Transform to MarketEvidence format
        # 3. Store in market_evidence table
        # 4. Update MarketContext cache
        
        logger.info("Market event ingestion complete")
        return {"status": "success", "events_ingested": 0}
        
    except Exception as e:
        logger.error(f"Market event ingestion failed: {e}")
        raise self.retry(exc=e, countdown=60 * (self.request.retries + 1))


@celery_app.task(bind=True, max_retries=3)
def ingest_market_events_for_market(self, market_id: str):
    """
    Ingest events for a specific market.
    Called by webhook or on-demand.
    """
    try:
        if not _market_signals_enabled():
            logger.info("Skipping event ingestion: market signals disabled in concierge-only mode")
            return {"status": "skipped", "reason": "market signals disabled"}
        logger.info(f"Ingesting events for market: {market_id}")
        scrape_events_for_market.delay(market_id)
        return {"status": "queued", "market_id": market_id}
        
    except Exception as e:
        logger.error(f"Event ingestion for {market_id} failed: {e}")
        raise self.retry(exc=e, countdown=60)


# =============================================================================
# EXPERIENCE DEMAND REFRESH
# =============================================================================

@celery_app.task(bind=True, max_retries=3)
def refresh_experience_demand(self, market_ids: Optional[List[str]] = None):
    """
    Refresh experience demand signals.
    
    Sources:
    - Search trends (golf cart rentals, fishing charters)
    - OTA activity data
    - Partner availability signals
    
    Frequency: Weekly
    """
    try:
        if not _market_signals_enabled():
            logger.info("Skipping experience demand refresh: market signals disabled in concierge-only mode")
            return {"status": "skipped", "reason": "market signals disabled"}
        logger.info("Starting experience demand refresh")
        
        # Delegate to the market scraper for each market
        from app.workers.ingestion import MARKET_BOUNDS
        targets = market_ids or list(MARKET_BOUNDS.keys())
        for mid in targets:
            scrape_airbnb_market.delay(mid)
        logger.info("Experience demand refresh queued for %d markets", len(targets))
        return {"status": "queued", "markets": targets}
        
    except Exception as e:
        logger.error(f"Experience demand refresh failed: {e}")
        raise self.retry(exc=e, countdown=300)


# =============================================================================
# OPERATIONAL SNAPSHOT REFRESH
# =============================================================================

@celery_app.task(bind=True, max_retries=3)
def refresh_operational_snapshot(self, property_id: str):
    """
    Refresh operational snapshot for a single property.
    
    Sources:
    - PMS calendar
    - Cleaning schedule
    - Staff capacity
    - Known issues
    
    Called by: Webhook, on-demand, or hourly batch
    """
    try:
        logger.info(f"Refreshing operational snapshot for property: {property_id}")
        
        # Trigger a PMS sync for this property's active sessions
        from app.services.agents.pms_sync_agent import get_pms_sync_agent
        from app.core.database import get_db_session
        agent = get_pms_sync_agent()
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            async def _run():
                async with get_db_session() as db:
                    # sync_single_session needs a token; here we trigger a
                    # batch sync and filter to this property in the agent
                    return await agent.sync_all_active_sessions(db)
            result = loop.run_until_complete(_run())
        finally:
            loop.close()
        return {"status": "success", "property_id": property_id, "synced": result.synced}
        
    except Exception as e:
        logger.error(f"Operational snapshot refresh for {property_id} failed: {e}")
        raise self.retry(exc=e, countdown=60)


@celery_app.task(bind=True)
def refresh_operational_snapshots_batch(self):
    """
    Batch refresh operational snapshots for all active properties.
    
    Frequency: Hourly
    """
    try:
        logger.info("Starting batch operational snapshot refresh")
        
        from app.core.database import get_db_session
        from sqlalchemy import text
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            async def _get_props():
                async with get_db_session() as db:
                    res = await db.execute(
                        text("SELECT id FROM properties WHERE status = 'active' AND deleted_at IS NULL")
                    )
                    return [str(r[0]) for r in res.fetchall()]
            prop_ids = loop.run_until_complete(_get_props())
        finally:
            loop.close()
        for pid in prop_ids:
            refresh_operational_snapshot.delay(pid)
        logger.info("Batch operational snapshot refresh queued: %d properties", len(prop_ids))
        return {"status": "success", "properties_queued": len(prop_ids)}
        
    except Exception as e:
        logger.error(f"Batch operational snapshot refresh failed: {e}")
        return {"status": "error", "error": str(e)}


# =============================================================================
# PROACTIVE TRIGGER EVALUATION
# =============================================================================

@celery_app.task(bind=True, max_retries=3)
def evaluate_proactive_triggers(self, property_id: str, guest_id: str):
    """
    Evaluate proactive automation for a specific booked guest session.

    Compatibility note: the legacy task signature is preserved because older
    callers still pass `(property_code, session_token)`. The canonical runtime
    now keys execution by `session_token` so booked guests at the same property
    remain distinct while proactive sends flow through the stay workflow +
    action queue + brain composition path.
    """
    try:
        property_code = str(property_id or "")
        session_token = str(guest_id or "")
        logger.info(
            "Evaluating proactive runtime for session token %s at property %s",
            session_token,
            property_code,
        )

        from app.core.database import get_db_session
        from app.services.operator.stay_proactive_runtime import (
            get_stay_proactive_runtime_service,
        )
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            async def _run():
                async with get_db_session() as db:
                    svc = get_stay_proactive_runtime_service()
                    return await svc.execute_due_touch_for_token(
                        db,
                        session_token=session_token,
                    )
            result = loop.run_until_complete(_run())
        except Exception as exc:
            logger.warning("Proactive runtime evaluation error (non-fatal): %s", exc)
            result = {"status": "error", "error": str(exc)}
        finally:
            loop.close()
        return {
            "status": "success",
            "property_code": property_code,
            "session_token": session_token,
            **result,
        }
        
    except Exception as e:
        logger.error(f"Proactive trigger evaluation failed: {e}")
        raise self.retry(exc=e, countdown=60)


@celery_app.task(bind=True)
def evaluate_proactive_triggers_batch(self):
    """
    Batch evaluate automated proactive touches through the canonical stay
    workflow runtime.
    """
    try:
        logger.info("Starting batch proactive runtime evaluation")

        from app.core.database import get_db_session
        from app.services.operator.stay_proactive_runtime import (
            get_stay_proactive_runtime_service,
        )
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            async def _get_stays():
                async with get_db_session() as db:
                    svc = get_stay_proactive_runtime_service()
                    return await svc.list_candidate_tokens(db, limit=200)
            stays = loop.run_until_complete(_get_stays())
        finally:
            loop.close()
        for stay in stays:
            evaluate_proactive_triggers.delay(
                str(stay.get("property_code") or ""),
                str(stay.get("token") or ""),
            )
        logger.info("Batch proactive runtime queued for %d stays", len(stays))
        return {"status": "success", "stays_evaluated": len(stays)}
        
    except Exception as e:
        logger.error(f"Batch proactive runtime evaluation failed: {e}")
        return {"status": "error", "error": str(e)}


# =============================================================================
# SUPPLY/DEMAND PRESSURE REFRESH
# =============================================================================

@celery_app.task(bind=True, max_retries=3)
def refresh_supply_demand_pressure(self, market_id: str):
    """
    Refresh supply/demand pressure for a market.
    
    Computes:
    - Current availability vs historical
    - Booking velocity
    - Price movements
    
    Updates: MarketContext.supply_demand_pressure
    """
    try:
        if not _market_signals_enabled():
            logger.info("Skipping supply/demand refresh: market signals disabled in concierge-only mode")
            return {"status": "skipped", "reason": "market signals disabled"}
        logger.info(f"Refreshing supply/demand pressure for market: {market_id}")
        
        # Delegate to Airbnb market scraper which feeds the signal pipeline
        scrape_airbnb_market.delay(market_id)
        return {"status": "queued", "market_id": market_id}
        
    except Exception as e:
        logger.error(f"Supply/demand refresh for {market_id} failed: {e}")
        raise self.retry(exc=e, countdown=120)


# =============================================================================
# PMS SYNC
# =============================================================================

@celery_app.task(bind=True, max_retries=3)
def sync_pms_sessions(self):
    """
    Reconcile active concierge sessions against the live PMS.

    Detects door code / WiFi / timing changes and updates session rows.
    Fires Watch Layer alert on credential changes.

    Frequency: Hourly
    """
    try:
        logger.info("[PMS Sync] Starting session reconciliation")
        from app.services.agents.pms_sync_agent import get_pms_sync_agent
        from app.core.database import get_db_session

        agent = get_pms_sync_agent()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            async def _run():
                async with get_db_session() as db:
                    return await agent.sync_all_active_sessions(db)
            result = loop.run_until_complete(_run())
        finally:
            loop.close()

        logger.info(
            "[PMS Sync] Done: synced=%d changed=%d skipped=%d errors=%d",
            result.synced, result.changed, result.skipped, result.errors,
        )
        return {
            "status": "success",
            "synced": result.synced,
            "changed": result.changed,
            "skipped": result.skipped,
            "errors": result.errors,
        }
    except Exception as exc:
        logger.error("[PMS Sync] Task failed: %s", exc)
        raise self.retry(exc=exc, countdown=120)


# =============================================================================
# ESCALATION SLA CHECKS
# =============================================================================

@celery_app.task(bind=True, max_retries=3)
def check_escalation_slas(self):
    """
    Scan open escalation tickets for SLA breaches.

    Urgent: 15min ack / 1hr resolve
    High:   1hr ack  / 4hr resolve
    Medium: 4hr ack  / 24hr resolve

    Fires Watch Layer alert per breach.  Sets ack_sla_breached /
    resolve_sla_breached flags on the DB row.

    Frequency: Every 5 minutes
    """
    try:
        from app.services.agents.escalation_handoff_agent import get_escalation_handoff_agent
        from app.core.database import get_db_session

        agent = get_escalation_handoff_agent()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            async def _run():
                async with get_db_session() as db:
                    return await agent.check_sla_breaches(db)
            breaches = loop.run_until_complete(_run())
        finally:
            loop.close()

        if breaches:
            logger.warning("[EscalationSLA] %d breach(es) detected", len(breaches))
        return {"status": "success", "breaches": len(breaches)}
    except Exception as exc:
        logger.error("[EscalationSLA] Task failed: %s", exc)
        raise self.retry(exc=exc, countdown=60)


# =============================================================================
# KNOWLEDGE CURATION
# =============================================================================

@celery_app.task(bind=True, max_retries=2)
def curate_knowledge_gaps(self):
    """
    Scan knowledge gaps, cluster similar questions, draft FAQ entries
    for operator review.

    After operator approves a draft via the dashboard, the FAQ is indexed
    into the vector store and retrieval hit rate improves for that property.

    Frequency: Daily
    """
    try:
        logger.info("[KnowledgeCurator] Starting gap curation")
        from app.services.agents.knowledge_curator_agent import get_knowledge_curator_agent
        from app.core.database import get_db_session

        agent = get_knowledge_curator_agent()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            async def _run():
                async with get_db_session() as db:
                    return await agent.curate_gaps(db)
            report = loop.run_until_complete(_run())
        finally:
            loop.close()

        logger.info(
            "[KnowledgeCurator] Done: gaps=%d clusters=%d drafts_created=%d",
            report.gaps_scanned, report.clusters_found, report.drafts_created,
        )
        return {
            "status": "success",
            "gaps_scanned": report.gaps_scanned,
            "clusters_found": report.clusters_found,
            "drafts_created": report.drafts_created,
        }
    except Exception as exc:
        logger.error("[KnowledgeCurator] Task failed: %s", exc)
        raise self.retry(exc=exc, countdown=300)


@celery_app.task(bind=True, max_retries=2)
def scan_healer_proposals(self, window_hours: int = 24):
    """
    Scan recent audit signals and draft pending healer proposals.

    Proposals remain human-reviewed. This task only materializes pending
    suggestions from recent message normalization disagreements.

    Frequency: Daily
    """
    try:
        logger.info("[HealerRunner] Starting proposal scan window_hours=%d", window_hours)
        from app.services.agents.healer_runner import scan_all_tenants

        results = _run_async(scan_all_tenants(window_hours=window_hours))
        payload = {
            "status": "success",
            "window_hours": int(window_hours),
            "tenants_scanned": len(results),
            "proposals_drafted": sum(int(count) for count in results.values()),
            "per_tenant_counts": {str(tenant_id): int(count) for tenant_id, count in results.items()},
        }
        logger.info(
            "[HealerRunner] Done: tenants_scanned=%d proposals_drafted=%d",
            payload["tenants_scanned"],
            payload["proposals_drafted"],
        )
        return payload
    except Exception as exc:
        logger.error("[HealerRunner] Task failed: %s", exc)
        raise self.retry(exc=exc, countdown=300)


@celery_app.task(bind=True, max_retries=2)
def check_concierge_health(self):
    """
    Validate concierge runtime dependencies and report readiness.

    Checks:
    - required MCP servers (concierge/knowledge/pms)
    - core agent factories (pms sync, escalation handoff, knowledge curator)
    - detector registry visibility
    - DB counts for active sessions/open escalations
    """
    flags = _get_runtime_flags()
    if not flags["enable_concierge_health_checks"]:
        return {"status": "skipped", "reason": "concierge health checks disabled"}

    try:
        from app.services.agents.concierge_health import run_concierge_health_checks
        from app.core.database import get_db_session

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            async def _run():
                async with get_db_session() as db:
                    return await run_concierge_health_checks(db)
            report = loop.run_until_complete(_run())
        finally:
            loop.close()

        payload = {
            "status": "success" if report.healthy else "degraded",
            "healthy": report.healthy,
            "checked_at": report.checked_at,
            "checks": report.checks,
            "warnings": report.warnings,
            "errors": report.errors,
        }
        if not report.healthy:
            logger.warning("[ConciergeHealth] degraded: %s", report.errors)
        return payload
    except Exception as exc:
        logger.error("[ConciergeHealth] Task failed: %s", exc)
        raise self.retry(exc=exc, countdown=120)


@celery_app.task(bind=True, max_retries=2)
def check_normalization_coverage_tripwire(self):
    """
    Hourly monitoring-only guard for message_normalizations coverage.

    Logs an ERROR if the rolling 24-hour join coverage between
    pre_booking_inquiries and message_normalizations drops below 95%.
    """
    flags = _get_runtime_flags()
    if not flags["enable_concierge_health_checks"]:
        return {"status": "skipped", "reason": "concierge health checks disabled"}

    try:
        from app.core.database import get_db_session
        from app.services.messaging.coverage_monitor import (
            run_normalization_coverage_tripwire,
        )

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            async def _run():
                async with get_db_session() as db:
                    return await run_normalization_coverage_tripwire(db)

            snapshot = loop.run_until_complete(_run())
        finally:
            loop.close()

        if snapshot.total_inquiries == 0:
            return {
                "status": "no_data",
                "window_hours": snapshot.window_hours,
                "threshold_percent": snapshot.threshold_percent,
            }

        return {
            "status": "warning" if snapshot.tripwire_fired else "ok",
            "coverage_percent": snapshot.coverage_percent,
            "normalized_inquiries": snapshot.normalized_inquiries,
            "total_inquiries": snapshot.total_inquiries,
            "threshold_percent": snapshot.threshold_percent,
            "window_hours": snapshot.window_hours,
        }
    except Exception as exc:
        logger.error("[CoverageTripwire] Task failed: %s", exc)
        raise self.retry(exc=exc, countdown=120)


# =============================================================================
# ALERT ESCALATION CHAIN — runs every 5 minutes
# =============================================================================

@celery_app.task(bind=True)
def check_unacked_alerts(self):
    """
    Scan operator_alert_acks for alerts past their ack_deadline.
    Fires to the next contact in escalation_order.
    If nobody left → notifies Oyvoda ops via OYVODA_OPS_PHONE.

    Beat schedule: every 5 minutes.
    """
    try:
        from app.services.messaging.operator_alerts import get_alert_router
        from app.core.database import get_db_session

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            async def _run():
                async with get_db_session() as db:
                    router = get_alert_router(db=db)
                    return await router.check_unacked_alerts()
            escalated = loop.run_until_complete(_run())
        finally:
            loop.close()

        logger.info("[AlertEscalation] Fired %d escalations", escalated)
        return {"status": "success", "escalations_fired": escalated}
    except Exception as exc:
        logger.error("[AlertEscalation] Task failed: %s", exc)
        raise self.retry(exc=exc, countdown=60)


# =============================================================================
# OOO AUTO-RESTORE — runs every hour
# =============================================================================

@celery_app.task(bind=True)
def restore_expired_ooo(self):
    """
    Auto-restore alert contacts whose unavailable_until has passed.
    Clears is_available=FALSE and redirect_to_id for expired OOO records.

    Beat schedule: every hour.
    """
    try:
        from app.services.messaging.operator_alerts import get_alert_router
        from app.core.database import get_db_session

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            async def _run():
                async with get_db_session() as db:
                    router = get_alert_router(db=db)
                    return await router.auto_restore_expired_ooo()
            restored = loop.run_until_complete(_run())
        finally:
            loop.close()

        if restored:
            logger.info("[OOORestore] Restored %d contacts from OOO", restored)
        return {"status": "success", "contacts_restored": restored}
    except Exception as exc:
        logger.error("[OOORestore] Task failed: %s", exc)
        raise self.retry(exc=exc, countdown=300)


# =============================================================================
# PMS INGEST — syncs Escapia listings + bookings into DB
# =============================================================================

@celery_app.task(bind=True, max_retries=3)
def sync_pms_for_operator(self, company_id: str):
    """
    Full PMS ingest for one operator — listings + bookings → DB.
    Called by beat schedule (hourly) and manual trigger endpoint.
    """
    try:
        from app.services.connectors.pms_ingest_worker import run_pms_ingest
        from app.core.database import get_db_session
        import uuid

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            async def _run():
                async with get_db_session() as db:
                    return await run_pms_ingest(
                        company_id=uuid.UUID(company_id),
                        db=db,
                    )
            result = loop.run_until_complete(_run())
        finally:
            loop.close()

        if not result["success"]:
            logger.warning(f"[PMSIngest] Failed for {company_id}: {result['error']}")
        else:
            logger.info(
                f"[PMSIngest] {company_id}: "
                f"{result['listings_synced']} listings, "
                f"{result['bookings_synced']} bookings, "
                f"{result['active_stays']} active stays"
            )
        return result
    except Exception as exc:
        logger.error(f"[PMSIngest] Task error for {company_id}: {exc}")
        raise self.retry(exc=exc, countdown=300)


@celery_app.task(bind=True)
def sync_pms_all_operators(self):
    """
    Hourly beat task — triggers sync_pms_for_operator for every
    operator that has Escapia credentials configured.
    """
    try:
        from app.services.connectors.integration_gateway import (
            get_integration_credential_store, IntegrationProvider
        )
        from app.core.database import get_db_session
        from sqlalchemy import text

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            async def _get_operators():
                async with get_db_session() as db:
                    result = await db.execute(
                        text("SELECT DISTINCT company_id FROM operator_sync_log "
                             "UNION "
                             "SELECT id FROM companies WHERE is_active = TRUE")
                    )
                    return [str(r.company_id) for r in result.fetchall()]
            company_ids = loop.run_until_complete(_get_operators())
        finally:
            loop.close()

        # Fire individual task per operator (parallel, isolated failures)
        store = get_integration_credential_store()
        triggered = 0
        for cid in company_ids:
            try:
                import uuid
                store.get_credentials(uuid.UUID(cid), IntegrationProvider.ESCAPIA)
                sync_pms_for_operator.delay(cid)
                triggered += 1
            except ValueError:
                pass  # No Escapia credentials for this operator

        logger.info(f"[PMSIngest] Triggered sync for {triggered} operators")
        return {"triggered": triggered}
    except Exception as exc:
        logger.error(f"[PMSIngest] sync_pms_all_operators failed: {exc}")
        return {"error": str(exc)}


# =============================================================================
# ESCAPIA MESSAGE POLLING — pre-booking inquiries from Vrbo/Airbnb
# =============================================================================


@celery_app.task(bind=True, max_retries=2)
def poll_connected_inbox_for_operator(
    self,
    operator_id: str,
    preferred_query_mode: Optional[str] = None,
    source: str = "schedule",
    history_start_id: str = "",
    history_end_id: str = "",
):
    """
    Poll one connected operator inbox (Gmail or Microsoft/Outlook).

    Uses the same adapter path as the manual "poll now" button, but runs in
    the background so operators never need to log in and trigger inbox sync.
    """
    try:
        return _run_async(
            _poll_connected_inbox_for_operator_async(
                operator_id,
                preferred_query_mode=preferred_query_mode,
                source=source,
                history_start_id=history_start_id,
                history_end_id=history_end_id,
            )
        )
    except Exception as exc:
        logger.error("[InboxPoll] Task error for operator %s: %s", operator_id, exc)
        raise self.retry(exc=exc, countdown=120)


@celery_app.task(bind=True)
def poll_connected_inboxes_all_operators(self):
    """
    Beat task — every 5 minutes, poll all connected email inboxes.

    Covers both Gmail and Microsoft/Outlook inboxes stored in
    operator_gmail_creds. Scheduled polling remains the fallback safety net
    even after push delivery is enabled.
    """
    try:
        return _run_async(_poll_connected_inboxes_all_operators_async())
    except Exception as exc:
        logger.error("[InboxPoll] poll_all failed: %s", exc)
        return {"error": str(exc)}


@celery_app.task(bind=True)
def renew_gmail_inbox_watches(self):
    """
    Renew Gmail Pub/Sub watches before expiry so email push stays event-driven.
    """
    try:
        return _run_async(_renew_gmail_inbox_watches_async())
    except Exception as exc:
        logger.error("[GmailPush] renew watches failed: %s", exc)
        return {"error": str(exc)}


@celery_app.task(bind=True)
def replay_parsing_chain_dryrun(
    self,
    tenant_id: str,
    message_count: int = 100,
    include_states: Optional[List[str]] = None,
):
    """
    Dry-run replay of recent inbox messages through the live parsing chain.

    This fetches recent Gmail messages for the given tenant and runs the
    current router with a dry-run LLM extractor that marks LLM routing
    without making external API calls or mutating production state.
    """
    try:
        return _run_async(
            _replay_parsing_chain_dryrun_async(
                tenant_id=tenant_id,
                message_count=message_count,
                include_states=include_states,
            )
        )
    except Exception as exc:
        logger.error("[ReplayDryRun] tenant=%s failed: %s", tenant_id, exc)
        return {"status": "error", "tenant_id": tenant_id, "error": str(exc)}


async def _poll_connected_inboxes_all_operators_async() -> dict:
    from sqlalchemy import text

    from app.core.database import get_db_session

    async with get_db_session() as db:
        rows = (
            await db.execute(
                text(
                    """
                    SELECT
                        gc.operator_id,
                        gc.tenant_id,
                        gc.watched_email,
                        gc.refresh_token,
                        COALESCE(gc.email_provider, 'gmail') AS email_provider
                    FROM operator_gmail_creds gc
                    JOIN operator_accounts oa
                      ON oa.id = gc.operator_id
                    WHERE oa.status = 'active'
                      AND gc.refresh_token IS NOT NULL
                      AND COALESCE(gc.watched_email, '') <> ''
                    ORDER BY gc.updated_at NULLS LAST, gc.created_at NULLS LAST
                    """
                )
            )
        ).mappings().all()

    triggered = 0
    providers: dict[str, int] = {}
    for row in rows:
        provider = (row.get("email_provider") or "gmail").lower()
        poll_connected_inbox_for_operator.delay(str(row["operator_id"]))
        triggered += 1
        providers[provider] = providers.get(provider, 0) + 1

    logger.info("[InboxPoll] Triggered automatic inbox polling for %d operators: %s", triggered, providers)
    return {"triggered": triggered, "providers": providers}


async def _poll_connected_inbox_for_operator_async(
    operator_id: str,
    *,
    preferred_query_mode: Optional[str] = None,
    source: str = "schedule",
    history_start_id: str = "",
    history_end_id: str = "",
) -> dict:
    import uuid

    from sqlalchemy import text

    from app.core.database import get_db_session
    from app.services.messaging.inbox_adapters import (
        InboxAdapterBuildError,
        InboxAdapterConfig,
        build_inbox_adapter,
    )

    async with get_db_session() as db:
        row = (
            await db.execute(
                text(
                    """
                    SELECT
                        gc.operator_id,
                        gc.tenant_id,
                        gc.watched_email,
                        gc.refresh_token,
                        COALESCE(gc.email_provider, 'gmail') AS email_provider
                    FROM operator_gmail_creds gc
                    WHERE gc.operator_id = CAST(:oid AS uuid)
                    LIMIT 1
                    """
                ),
                {"oid": operator_id},
            )
        ).mappings().first()

        if not row:
            logger.info("[InboxPoll] No connected inbox found for operator %s", operator_id)
            return {"status": "skipped", "reason": "no_connected_inbox", "operator_id": operator_id}

        provider = row["email_provider"] or "gmail"
        try:
            poller = build_inbox_adapter(
                InboxAdapterConfig(
                    operator_id=str(row["operator_id"]),
                    company_id=uuid.UUID(str(row["tenant_id"])),
                    watched_email=row["watched_email"],
                    refresh_token=row["refresh_token"],
                    provider=provider,
                ),
                db=db,
            )
        except InboxAdapterBuildError as exc:
            logger.warning("[InboxPoll] Unsupported inbox provider for %s: %s", operator_id, exc)
            return {
                "status": "skipped",
                "reason": "unsupported_provider",
                "operator_id": operator_id,
                "provider": provider,
                "error": str(exc),
            }

        if not poller:
            logger.warning("[InboxPoll] Inbox adapter not configured for %s provider=%s", operator_id, provider)
            return {
                "status": "skipped",
                "reason": "adapter_not_configured",
                "operator_id": operator_id,
                "provider": provider,
            }

        fallback_used = False
        if (
            provider == "gmail"
            and preferred_query_mode == "gmail_history"
            and hasattr(poller, "poll_from_history")
        ):
            result = await poller.poll_from_history(
                history_start_id,
                end_history_id=history_end_id or None,
            )
            if result.query_mode == "recent_inbox":
                fallback_used = True
        elif preferred_query_mode:
            result = await poller.poll_with_mode(query_mode=preferred_query_mode)
        else:
            result = await poller.poll()
            if result.messages_found == 0 and not result.errors:
                fallback_used = True
                result = await poller.poll_with_mode(query_mode="recent_inbox")

        summary = {
            "status": "ok" if not result.errors else "warning",
            "operator_id": operator_id,
            "tenant_id": str(row["tenant_id"]),
            "provider": provider,
            "watched_email": row["watched_email"],
            "query_mode": result.query_mode,
            "fallback_used": fallback_used,
            "source": source,
            "messages_found": result.messages_found,
            "messages_processed": result.messages_processed,
            "new_pending_inquiries": result.new_pending_inquiries,
            "duplicate_inquiry_skips": result.duplicate_inquiry_skips,
            "already_processed_skips": result.already_processed_skips,
            "non_guest_skips": result.non_guest_skips,
            "errors": list(result.errors or []),
        }
        logger.info(
            "[InboxPoll] operator=%s provider=%s mode=%s found=%d processed=%d new=%d errors=%d",
            operator_id,
            provider,
            result.query_mode,
            result.messages_found,
            result.messages_processed,
            result.new_pending_inquiries,
            len(result.errors),
        )
        try:
            from app.services.operator.realtime_hub import get_operator_realtime_hub

            hub = get_operator_realtime_hub()
            await hub.publish(
                str(row["tenant_id"]),
                "summary.updated",
                {
                    "tenant_id": str(row["tenant_id"]),
                    "operator_id": operator_id,
                    "source": f"inbox_{source}",
                    "provider": provider,
                    "query_mode": result.query_mode,
                    "messages_found": result.messages_found,
                    "messages_processed": result.messages_processed,
                    "new_pending_inquiries": result.new_pending_inquiries,
                },
            )
        except Exception:
            logger.debug("[InboxPoll] realtime publish failed for operator=%s", operator_id, exc_info=True)
        return summary


async def _renew_gmail_inbox_watches_async() -> dict:
    from sqlalchemy import text

    from app.core.database import get_db_session
    from app.services.integrations.gmail_push import ensure_gmail_push_schema, register_gmail_watch

    async with get_db_session() as db:
        await ensure_gmail_push_schema(db)
        rows = (
            await db.execute(
                text(
                    """
                    SELECT
                        gc.operator_id,
                        gc.tenant_id,
                        gc.watched_email,
                        gc.refresh_token
                    FROM operator_gmail_creds gc
                    JOIN operator_accounts oa
                      ON oa.id = gc.operator_id
                    WHERE oa.status = 'active'
                      AND COALESCE(gc.email_provider, 'gmail') IN ('gmail', 'google')
                      AND gc.refresh_token IS NOT NULL
                      AND COALESCE(gc.watched_email, '') <> ''
                      AND (
                        gc.gmail_watch_expires_at IS NULL
                        OR gc.gmail_watch_expires_at <= NOW() + INTERVAL '24 hours'
                      )
                    ORDER BY gc.gmail_watch_expires_at NULLS FIRST, gc.updated_at NULLS LAST
                    """
                )
            )
        ).mappings().all()

        refreshed = 0
        skipped = 0
        failed = 0
        for row in rows:
            result = await register_gmail_watch(
                db,
                operator_id=str(row["operator_id"]),
                tenant_id=str(row["tenant_id"]),
                watched_email=str(row["watched_email"] or ""),
                refresh_token=str(row["refresh_token"] or ""),
            )
            if result.status == "ok":
                refreshed += 1
            elif result.status == "skipped":
                skipped += 1
            else:
                failed += 1

    logger.info(
        "[GmailPush] watch renewal complete refreshed=%d skipped=%d failed=%d",
        refreshed,
        skipped,
        failed,
    )
    return {
        "refreshed": refreshed,
        "skipped": skipped,
        "failed": failed,
    }


async def _replay_parsing_chain_dryrun_async(
    *,
    tenant_id: str,
    message_count: int,
    include_states: Optional[List[str]],
) -> dict:
    import uuid

    from sqlalchemy import text

    from app.core.database import get_db_session
    from app.services.messaging.inbox_adapters import (
        InboxAdapterBuildError,
        InboxAdapterConfig,
        build_inbox_adapter,
    )

    normalized_states = [
        str(state).strip().lower()
        for state in (include_states or list(_REPLAY_DEFAULT_STATES))
        if str(state).strip()
    ]
    scan_limit = max(int(message_count or 0), 1) * 3
    scan_limit = max(scan_limit, max(int(message_count or 0), 1) + 25)

    state_clause = ""
    params: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "scan_limit": scan_limit,
    }
    if normalized_states:
        placeholders = []
        for idx, state in enumerate(normalized_states):
            key = f"state_{idx}"
            params[key] = state
            placeholders.append(f":{key}")
        state_clause = f"AND COALESCE(gpm.processing_status, '') IN ({', '.join(placeholders)})"

    async with get_db_session() as db:
        rows = (
            await db.execute(
                text(
                    f"""
                    SELECT
                        gpm.operator_id,
                        gpm.gmail_message_id,
                        COALESCE(gpm.processing_status, '') AS processing_status,
                        COALESCE(gpm.last_failure_reason, '') AS last_failure_reason,
                        gc.tenant_id,
                        gc.watched_email,
                        gc.refresh_token,
                        COALESCE(gc.email_provider, 'gmail') AS email_provider,
                        COALESCE(mn.parser_used, '') AS original_parser_used,
                        COALESCE(mn.route_outcome, '') AS original_route_outcome,
                        COALESCE(mn.raw_subject, '') AS original_subject,
                        COALESCE(mn.sender_address, '') AS original_sender_address
                    FROM gmail_processed_messages gpm
                    JOIN operator_gmail_creds gc
                      ON gc.operator_id = CAST(gpm.operator_id AS uuid)
                    LEFT JOIN message_normalizations mn
                      ON mn.tenant_id = gc.tenant_id
                     AND mn.source_channel = 'email'
                     AND mn.source_message_id = gpm.gmail_message_id
                    WHERE gc.tenant_id = CAST(:tenant_id AS uuid)
                    {state_clause}
                    ORDER BY COALESCE(gpm.last_attempted_at, gpm.processed_at, gpm.first_seen_at) DESC NULLS LAST
                    LIMIT :scan_limit
                    """
                ),
                params,
            )
        ).mappings().all()

        if not rows:
            return {
                "status": "ok",
                "tenant_id": tenant_id,
                "message_count_requested": int(message_count or 0),
                "states_considered": normalized_states,
                "messages_selected": 0,
                "messages_fetched": 0,
                "messages_analyzed": 0,
                "counts_by_new_route": {},
                "counts_by_new_parser": {},
                "counts_by_original_parser": {},
                "counts_by_discrepancy": {},
                "sample_concerns": [],
                "sample_disagreements": [],
                "notes": [
                    "No gmail_processed_messages rows matched this tenant/state selection.",
                    "Dry-run replay makes no external LLM calls and does not mutate production state.",
                ],
            }

        poller_cache: Dict[str, Any] = {}
        headers_cache: Dict[str, Dict[str, str]] = {}
        counts_by_new_route: Counter[str] = Counter()
        counts_by_new_parser: Counter[str] = Counter()
        counts_by_original_parser: Counter[str] = Counter()
        counts_by_discrepancy: Counter[str] = Counter()
        sample_by_route: Dict[str, List[Dict[str, Any]]] = {}
        sample_concerns: List[Dict[str, Any]] = []
        sample_disagreements: List[Dict[str, Any]] = []
        missing_messages = 0
        fetch_errors = 0
        unsupported_rows = 0
        analyzed = 0

        for row in rows:
            if analyzed >= max(int(message_count or 0), 1):
                break

            operator_id = str(row["operator_id"])
            provider = (row["email_provider"] or "gmail").strip().lower()
            normalized_provider = "gmail" if provider in {"gmail", "google"} else provider
            if normalized_provider != "gmail":
                unsupported_rows += 1
                continue

            poller = poller_cache.get(operator_id)
            headers = headers_cache.get(operator_id)
            if poller is None:
                try:
                    poller = build_inbox_adapter(
                        InboxAdapterConfig(
                            operator_id=operator_id,
                            company_id=uuid.UUID(str(row["tenant_id"])),
                            watched_email=row["watched_email"],
                            refresh_token=row["refresh_token"],
                            provider=normalized_provider,
                        ),
                        db=db,
                    )
                except InboxAdapterBuildError as exc:
                    logger.warning("[ReplayDryRun] unsupported provider operator=%s provider=%s err=%s", operator_id, normalized_provider, exc)
                    unsupported_rows += 1
                    continue

                if not poller or not hasattr(poller, "_get_full_message") or not hasattr(poller, "_parse_with_ota_fallback"):
                    unsupported_rows += 1
                    continue

                token = await poller.token_manager.get_access_token()
                headers = poller.token_manager.auth_header(token)
                poller_cache[operator_id] = poller
                headers_cache[operator_id] = headers

            gmail_message_id = str(row["gmail_message_id"] or "").strip()
            if not gmail_message_id:
                continue

            try:
                raw_message = await poller._get_full_message(gmail_message_id, headers)
            except Exception as exc:
                fetch_errors += 1
                logger.warning("[ReplayDryRun] fetch failed tenant=%s operator=%s message=%s err=%s", tenant_id, operator_id, gmail_message_id, exc)
                continue

            if not raw_message:
                missing_messages += 1
                continue

            parsed = await poller._parse_with_ota_fallback(
                raw_message,
                llm_extractor_factory=_DryRunLLMExtractor,
            )
            non_guest_reason = getattr(poller, "_last_non_guest_reason", "") or ""
            new_parser_source = getattr(parsed, "parser_source", "") if parsed else ""
            new_route_bucket = _replay_route_bucket(
                new_parser_source,
                non_guest_reason=non_guest_reason,
            )
            original_parser_used = str(row["original_parser_used"] or "")
            original_route_outcome = str(row["original_route_outcome"] or "")
            discrepancy_category = _replay_discrepancy_category(
                original_parser_used=original_parser_used,
                original_route_outcome=original_route_outcome,
                new_route_bucket=new_route_bucket,
            )

            counts_by_new_route[new_route_bucket] += 1
            counts_by_new_parser[new_parser_source or "(none)"] += 1
            counts_by_original_parser[original_parser_used or "(none)"] += 1
            counts_by_discrepancy[discrepancy_category] += 1
            analyzed += 1

            subject = (
                getattr(parsed, "subject", "")
                or str(row["original_subject"] or "")
            )[:200]
            sender = (
                getattr(parsed, "raw_from", "")
                or str(row["original_sender_address"] or "")
            )[:200]

            sample = {
                "gmail_message_id": gmail_message_id,
                "operator_id": operator_id,
                "processing_status": str(row["processing_status"] or ""),
                "original_parser_used": original_parser_used or None,
                "original_route_outcome": original_route_outcome or None,
                "new_route_bucket": new_route_bucket,
                "new_parser_source": new_parser_source or None,
                "non_guest_reason": non_guest_reason or None,
                "subject": subject,
                "sender": sender,
            }
            route_samples = sample_by_route.setdefault(new_route_bucket, [])
            if len(route_samples) < 5:
                route_samples.append(sample)
            if discrepancy_category != "none" and len(sample_concerns) < 15:
                sample_concerns.append({**sample, "discrepancy": discrepancy_category})
            if (
                original_parser_used
                and new_parser_source
                and original_parser_used != new_parser_source
                and len(sample_disagreements) < 20
            ):
                sample_disagreements.append(sample)

    logger.info(
        "[ReplayDryRun] tenant=%s analyzed=%d llm=%d non_guest=%d booking_event=%d deterministic=%d missing=%d fetch_errors=%d",
        tenant_id,
        analyzed,
        counts_by_new_route.get("llm_route", 0),
        counts_by_new_route.get("non_guest", 0),
        counts_by_new_route.get("booking_event", 0),
        counts_by_new_route.get("deterministic_ota_parser", 0) + counts_by_new_route.get("deterministic_direct_parser", 0),
        missing_messages,
        fetch_errors,
    )

    return {
        "status": "ok",
        "tenant_id": tenant_id,
        "message_count_requested": int(message_count or 0),
        "states_considered": normalized_states,
        "messages_selected": len(rows),
        "messages_fetched": analyzed + missing_messages,
        "messages_missing": missing_messages,
        "messages_fetch_errors": fetch_errors,
        "messages_unsupported_provider": unsupported_rows,
        "messages_analyzed": analyzed,
        "counts_by_new_route": dict(sorted(counts_by_new_route.items())),
        "counts_by_new_parser": dict(sorted(counts_by_new_parser.items())),
        "counts_by_original_parser": dict(sorted(counts_by_original_parser.items())),
        "counts_by_discrepancy": dict(sorted(counts_by_discrepancy.items())),
        "sample_by_route": sample_by_route,
        "sample_concerns": sample_concerns,
        "sample_disagreements": sample_disagreements,
        "notes": [
            "Dry-run replay fetches real Gmail messages but never calls Groq or Anthropic.",
            "LLM-routed messages are marked with parser_source=dryrun_llm_route_only_groq.",
            "This replay validates routing decisions, not downstream send/write behavior.",
            "Anthropic fallback rates cannot be measured from this dry-run because no external providers are invoked.",
        ],
    }


# =============================================================================
# MESSAGE HISTORY — historical import + stale draft voiding
# =============================================================================

@celery_app.task(bind=True, max_retries=2)
def import_historical_messages_for_operator(self, company_id: str):
    """
    Pull full message history from Escapia for all known listings.
    Called once after onboarding and after any re-sync that adds new properties.
    Feeds historical Q&A into the property KB.
    """
    try:
        from app.services.concierge.message_history import HistoricalMessageImporter
        from app.services.connectors.integration_gateway import (
            get_integration_credential_store, IntegrationProvider
        )
        from app.core.database import get_db_session
        import uuid

        store = get_integration_credential_store()
        cid = uuid.UUID(company_id)
        creds = store.get_credentials(cid, IntegrationProvider.ESCAPIA)
        api_key = creds.get("api_key", "")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            async def _run():
                async with get_db_session() as db:
                    from sqlalchemy import text
                    # Get all known listing IDs for this operator
                    rows = await db.execute(
                        text("SELECT external_id FROM pms_listings WHERE company_id = :cid::uuid AND is_active = TRUE"),
                        {"cid": company_id},
                    )
                    listing_ids = [r.external_id for r in rows.fetchall()]

                    if not listing_ids:
                        return {"imported": 0, "reason": "no_listings"}

                    importer = HistoricalMessageImporter(api_key=api_key, company_id=cid)
                    result = await importer.import_all_listings(db, listing_ids)

                    # After import, extract FAQ signal for each listing
                    faq_total = 0
                    for lid in listing_ids:
                        faq_count = await importer.extract_faq_signal(db, lid, cid)
                        faq_total += faq_count

                    result["faq_pairs_extracted"] = faq_total
                    return result

            result = loop.run_until_complete(_run())
        finally:
            loop.close()

        logger.info(f"[HistoricalImport] {company_id}: {result}")
        return result
    except Exception as exc:
        logger.error(f"[HistoricalImport] Task error for {company_id}: {exc}")
        raise self.retry(exc=exc, countdown=600)


@celery_app.task(bind=True)
def void_stale_drafts_for_operator(self, company_id: str):
    """
    Hourly: check all pending_review drafts. If the thread was answered
    in Escapia without going through our pipeline, void the draft.
    Also auto-resolves orphaned messages if their listing ID is now known.
    """
    try:
        from app.services.concierge.message_history import (
            StaleMessageDetector, OrphanMessageHandler
        )
        from app.services.connectors.integration_gateway import (
            get_integration_credential_store, IntegrationProvider
        )
        from app.core.database import get_db_session
        import uuid

        store = get_integration_credential_store()
        cid = uuid.UUID(company_id)
        try:
            creds = store.get_credentials(cid, IntegrationProvider.ESCAPIA)
            api_key = creds.get("api_key", "")
        except ValueError:
            return {"voided": 0, "reason": "no_credentials"}

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            async def _run():
                async with get_db_session() as db:
                    detector = StaleMessageDetector(api_key)
                    voided = await detector.void_superseded_drafts(db, cid, api_key)

                    # Auto-resolve orphans whose listing IDs are now known
                    handler = OrphanMessageHandler()
                    auto_resolved = await handler.auto_resolve_after_sync(db, cid)

                    return {"voided": voided, "orphans_auto_resolved": auto_resolved}

            result = loop.run_until_complete(_run())
        finally:
            loop.close()

        if result["voided"] or result["orphans_auto_resolved"]:
            logger.info(f"[StaleCheck] {company_id}: voided={result['voided']} auto_resolved={result['orphans_auto_resolved']}")
        return result
    except Exception as exc:
        logger.error(f"[StaleCheck] Task error for {company_id}: {exc}")
        return {"error": str(exc)}


@celery_app.task(bind=True)
def void_stale_drafts_all_operators(self):
    """Hourly beat: run stale check for all operators with Escapia configured."""
    try:
        from app.services.concierge.message_history import _get_escapia_operator_ids
        operator_ids = _get_escapia_operator_ids()
        for cid in operator_ids:
            void_stale_drafts_for_operator.delay(cid)
        return {"triggered": len(operator_ids)}
    except Exception as exc:
        logger.error(f"[StaleCheck] all_operators failed: {exc}")
        return {"error": str(exc)}


# =============================================================================
# PLATFORM INTELLIGENCE REBUILD
# =============================================================================

@celery_app.task(bind=True)
def rebuild_platform_intelligence_task(self):
    """
    Nightly at 3am: aggregate anonymized edit events into platform intelligence.
    No operator IDs, no PII — only intent patterns + resolution rates.
    """
    try:
        from app.services.concierge.operator_learning import rebuild_platform_intelligence
        from app.core.database import get_db_session

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            async def _run():
                async with get_db_session() as db:
                    return await rebuild_platform_intelligence(db)
            result = loop.run_until_complete(_run())
        finally:
            loop.close()

        logger.info(f"[PlatformIntelligence] Rebuilt {result.get('updated', 0)} entries")
        return result
    except Exception as exc:
        logger.error(f"[PlatformIntelligence] Rebuild failed: {exc}")
        return {"error": str(exc)}


# =============================================================================
# MESSAGE RETENTION
# =============================================================================

@celery_app.task(bind=True)
def enforce_message_retention_policies(self):
    """
    Daily: enforce operator-configured retention windows.

    The goal is to keep live operations lean, preserve a short post-stay
    follow-up window, and scrub/delete older guest content before Oyvoda turns
    into a large raw-message warehouse.
    """
    try:
        from app.core.database import get_db_session
        from app.services.operator.message_retention_service import MessageRetentionService

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            async def _run():
                async with get_db_session() as db:
                    return await MessageRetentionService(db).run_all_tenants()
            result = loop.run_until_complete(_run())
        finally:
            loop.close()

        logger.info(
            "[Retention] tenants=%s processed=%s scrubbed(norm=%s prebooking=%s sessions=%s) deleted(messages=%s norm=%s prebooking=%s shells=%s)",
            result.get("tenants_considered", 0),
            result.get("tenants_processed", 0),
            result.get("message_normalizations_scrubbed", 0),
            result.get("pre_booking_scrubbed", 0),
            result.get("guest_sessions_scrubbed", 0),
            result.get("messages_deleted", 0),
            result.get("message_normalizations_deleted", 0),
            result.get("pre_booking_deleted", 0),
            result.get("guest_session_shells_deleted", 0),
        )
        return result
    except Exception as exc:
        logger.error(f"[Retention] enforcement failed: {exc}")
        return {"error": str(exc)}


# =============================================================================
# EVIDENCE CLEANUP
# =============================================================================

@celery_app.task(bind=True)
def cleanup_expired_evidence(self):
    """
    Clean up expired evidence records.
    
    Removes evidence where expires_at < now().
    
    Frequency: Daily (via beat schedule)
    """
    try:
        logger.info("Starting expired evidence cleanup")
        
        from app.core.database import get_db_session
        from sqlalchemy import text
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            async def _cleanup():
                async with get_db_session() as db:
                    res = await db.execute(
                        text("DELETE FROM market_events WHERE is_active = false AND end_date < NOW() - INTERVAL '30 days' RETURNING event_id")
                    )
                    await db.commit()
                    return res.rowcount or 0
            deleted = loop.run_until_complete(_cleanup())
        except Exception as exc:
            logger.warning("Evidence cleanup error (non-fatal): %s", exc)
            deleted = 0
        finally:
            loop.close()
        logger.info("Expired evidence cleanup complete: %d records deleted", deleted)
        return {"status": "success", "records_deleted": deleted}
        
    except Exception as e:
        logger.error(f"Evidence cleanup failed: {e}")
        return {"status": "error", "error": str(e)}


# =============================================================================
# AUTONOMY SNAPSHOTS
# =============================================================================

@celery_app.task(bind=True)
def snapshot_autonomy_all_operators(self):
    """
    Nightly at 6am: capture one portfolio-level autonomy snapshot row per
    active tenant in operator_autonomy_snapshots (append-only by date).

    Each row holds:
      - portfolio_score: directional 0..1 posture score
      - domain_bands: per-domain band words (Inquiry computed; others static v1)
      - components: readiness / escalation / behavior breakdown for tuning

    Fail-soft per tenant: one tenant's exception must not abort the batch.
    Idempotent per day: ON CONFLICT (tenant_id, snapshot_date) DO UPDATE.
    """
    import asyncio
    import json
    from datetime import date

    try:
        from app.core.database import get_db_session
        from app.services.operator.autonomy_score_service import compute_autonomy_snapshot_bundle
        from sqlalchemy import text

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            async def _run():
                succeeded = 0
                failed = 0

                async with get_db_session() as db:
                    # Guard: snapshot tables must exist (migration may not have run yet)
                    portfolio_table_exists = await db.scalar(
                        text(
                            """
                            SELECT EXISTS (
                                SELECT 1 FROM information_schema.tables
                                WHERE table_schema = 'public'
                                  AND table_name = 'operator_autonomy_snapshots'
                            )
                            """
                        )
                    )
                    property_table_exists = await db.scalar(
                        text(
                            """
                            SELECT EXISTS (
                                SELECT 1 FROM information_schema.tables
                                WHERE table_schema = 'public'
                                  AND table_name = 'operator_property_autonomy_snapshots'
                            )
                            """
                        )
                    )
                    if not portfolio_table_exists or not property_table_exists:
                        logger.warning(
                            "[AutonomySnapshot] autonomy snapshot tables not found — "
                            "have migrations 090 and 091 been applied?"
                        )
                        return {"succeeded": 0, "failed": 0, "skipped": "table_missing"}

                    # Collect active tenants
                    rows = (
                        await db.execute(
                            text(
                                """
                                SELECT DISTINCT tenant_id
                                FROM operator_accounts
                                WHERE status = 'active'
                                  AND tenant_id IS NOT NULL
                                """
                            )
                        )
                    ).fetchall()

                tenant_ids = [str(r[0]) for r in rows]
                today = date.today()

                for tid in tenant_ids:
                    try:
                        async with get_db_session() as db:
                            snapshot_bundle = await compute_autonomy_snapshot_bundle(db, tid)
                            snapshot = snapshot_bundle["portfolio"]
                            await db.execute(
                                text(
                                    """
                                    INSERT INTO operator_autonomy_snapshots
                                        (tenant_id, snapshot_date, portfolio_score,
                                         domain_bands, components)
                                    VALUES (
                                        CAST(:tid AS uuid),
                                        CAST(:snapshot_date AS date),
                                        :portfolio_score,
                                        CAST(:domain_bands AS jsonb),
                                        CAST(:components AS jsonb)
                                    )
                                    ON CONFLICT (tenant_id, snapshot_date)
                                    DO UPDATE SET
                                        portfolio_score = EXCLUDED.portfolio_score,
                                        domain_bands    = EXCLUDED.domain_bands,
                                        components      = EXCLUDED.components
                                    """
                                ),
                                {
                                    "tid": tid,
                                    "snapshot_date": today,
                                    "portfolio_score": snapshot["portfolio_score"],
                                    "domain_bands": json.dumps(snapshot["domain_bands"]),
                                    "components": json.dumps(snapshot["components"]),
                                },
                            )
                            for property_snapshot in snapshot_bundle["per_property"]:
                                inquiry = property_snapshot.get("domain_bands", {}).get("inquiry", {})
                                await db.execute(
                                    text(
                                        """
                                        INSERT INTO operator_property_autonomy_snapshots
                                            (tenant_id, property_id, snapshot_date, signal_status,
                                             inquiry_score, inquiry_band, guest_ops_band,
                                             maintenance_band, turnover_band, components, metrics)
                                        VALUES (
                                            CAST(:tid AS uuid),
                                            CAST(:property_id AS uuid),
                                            CAST(:snapshot_date AS date),
                                            :signal_status,
                                            :inquiry_score,
                                            :inquiry_band,
                                            :guest_ops_band,
                                            :maintenance_band,
                                            :turnover_band,
                                            CAST(:components AS jsonb),
                                            CAST(:metrics AS jsonb)
                                        )
                                        ON CONFLICT (tenant_id, property_id, snapshot_date)
                                        DO UPDATE SET
                                            signal_status    = EXCLUDED.signal_status,
                                            inquiry_score    = EXCLUDED.inquiry_score,
                                            inquiry_band     = EXCLUDED.inquiry_band,
                                            guest_ops_band   = EXCLUDED.guest_ops_band,
                                            maintenance_band = EXCLUDED.maintenance_band,
                                            turnover_band    = EXCLUDED.turnover_band,
                                            components       = EXCLUDED.components,
                                            metrics          = EXCLUDED.metrics
                                        """
                                    ),
                                    {
                                        "tid": tid,
                                        "property_id": property_snapshot["property_id"],
                                        "snapshot_date": today,
                                        "signal_status": property_snapshot["signal_status"],
                                        "inquiry_score": inquiry.get("score"),
                                        "inquiry_band": inquiry.get("band") or "Insufficient Signal",
                                        "guest_ops_band": property_snapshot["domain_bands"]["guest_ops"],
                                        "maintenance_band": property_snapshot["domain_bands"]["maintenance"],
                                        "turnover_band": property_snapshot["domain_bands"]["turnover"],
                                        "components": json.dumps(property_snapshot.get("components") or {}),
                                        "metrics": json.dumps(property_snapshot.get("metrics") or {}),
                                    },
                                )
                            await db.commit()
                            succeeded += 1
                            logger.info(
                                "[AutonomySnapshot] tenant=%s score=%.4f inquiry_band=%s per_property=%s excluded=%s",
                                tid,
                                snapshot["portfolio_score"],
                                snapshot["domain_bands"].get("inquiry", {}).get("band", "?"),
                                snapshot_bundle["rollup"]["included_properties"],
                                snapshot_bundle["rollup"]["excluded_properties"],
                            )
                    except Exception as exc:  # noqa: BLE001 — fail-soft per tenant
                        failed += 1
                        logger.error("[AutonomySnapshot] tenant=%s failed: %s", tid, exc)

                return {"succeeded": succeeded, "failed": failed, "date": today.isoformat()}

            result = loop.run_until_complete(_run())
        finally:
            loop.close()

        logger.info(
            "[AutonomySnapshot] batch done — succeeded=%s failed=%s date=%s",
            result.get("succeeded", 0),
            result.get("failed", 0),
            result.get("date", "?"),
        )
        return result

    except Exception as exc:
        logger.error("[AutonomySnapshot] batch failed: %s", exc)
        return {"error": str(exc)}
