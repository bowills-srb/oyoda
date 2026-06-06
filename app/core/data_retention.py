"""
data_retention.py — Automated Data Retention Enforcement

Runs as a Celery periodic task (beat schedule) to enforce retention policies.
Satisfies SOC 2 A1 and GDPR Article 5(1)(e) (storage limitation).

Retention policies:
  - Guest conversation records: 90 days after checkout → anonymize
  - Escalation records: 12 months → delete
  - API request logs: 30 days → Railway auto-handles
  - Audit log: 7 years → never auto-delete (legal hold)
  - Pre-booking inquiries: 180 days → delete
  - Expired guest sessions: 30 days post-expiry → anonymize

Schedule: runs daily at 3am UTC (configured in celery_config.py)

Usage:
  # Manual run:
  python -c "import asyncio; from app.core.data_retention import run_retention; asyncio.run(run_retention())"

  # Celery task (automatic):
  Configured in workers/tasks.py as a beat schedule
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone, date
from typing import Dict, Any

logger = logging.getLogger(__name__)


async def run_retention() -> Dict[str, Any]:
    """
    Run all data retention policies.
    Returns a summary of what was processed.
    """
    results = {
        "started_at": datetime.utcnow().isoformat(),
        "guest_sessions_anonymized": 0,
        "expired_sessions_cleaned": 0,
        "old_escalations_deleted": 0,
        "old_prebooking_deleted": 0,
        "errors": [],
    }

    try:
        from app.core.database import get_db_session
        from sqlalchemy import text

        async with get_db_session() as db:
            now = datetime.now(timezone.utc)

            # ── 1. Anonymize guest sessions 90 days post-checkout ─────────────
            # Replace PII fields with [DELETED] but preserve conversation counts
            # for analytics. Guest data is gone, aggregate stats remain.
            try:
                cutoff_90 = now - timedelta(days=90)
                result = await db.execute(text("""
                    UPDATE concierge_guest_sessions
                    SET
                        guest_name  = '[DELETED]',
                        guest_phone = '[DELETED]',
                        guest_email = '[DELETED]',
                        updated_at  = NOW()
                    WHERE
                        check_out < :cutoff
                        AND guest_name != '[DELETED]'
                        AND status IN ('closed', 'expired')
                """), {"cutoff": cutoff_90})
                count = result.rowcount
                await db.commit()
                results["guest_sessions_anonymized"] = count
                if count > 0:
                    logger.info(f"[Retention] Anonymized {count} expired guest sessions (90-day policy)")
            except Exception as e:
                results["errors"].append(f"guest_sessions: {e}")
                logger.error(f"[Retention] Guest session anonymization failed: {e}")

            # ── 2. Delete fully expired sessions (30 days post-checkout) ─────
            # Sessions where checkout was > 30 days ago AND already anonymized
            try:
                cutoff_30 = now - timedelta(days=120)  # 90 + 30 days
                result = await db.execute(text("""
                    DELETE FROM concierge_guest_sessions
                    WHERE
                        check_out < :cutoff
                        AND guest_name = '[DELETED]'
                """), {"cutoff": cutoff_30})
                count = result.rowcount
                await db.commit()
                results["expired_sessions_cleaned"] = count
                if count > 0:
                    logger.info(f"[Retention] Deleted {count} fully expired sessions (120-day policy)")
            except Exception as e:
                results["errors"].append(f"expired_sessions: {e}")

            # ── 3. Delete old escalations (12 months) ─────────────────────────
            try:
                cutoff_12m = now - timedelta(days=365)
                result = await db.execute(text("""
                    DELETE FROM concierge_escalations
                    WHERE
                        created_at < :cutoff
                        AND status IN ('resolved', 'closed')
                """), {"cutoff": cutoff_12m})
                count = result.rowcount
                await db.commit()
                results["old_escalations_deleted"] = count
                if count > 0:
                    logger.info(f"[Retention] Deleted {count} old escalations (12-month policy)")
            except Exception as e:
                results["errors"].append(f"escalations: {e}")

            # ── 4. Delete old pre-booking inquiries (180 days) ────────────────
            try:
                cutoff_180 = now - timedelta(days=180)
                result = await db.execute(text("""
                    DELETE FROM pre_booking_inquiries
                    WHERE
                        created_at < :cutoff
                        AND status IN ('sent', 'rejected', 'expired')
                """), {"cutoff": cutoff_180})
                count = result.rowcount
                await db.commit()
                results["old_prebooking_deleted"] = count
                if count > 0:
                    logger.info(f"[Retention] Deleted {count} old pre-booking inquiries (180-day policy)")
            except Exception as e:
                results["errors"].append(f"pre_booking: {e}")
                # Non-fatal — table may not exist yet

            # ── 5. Log retention run to audit trail ───────────────────────────
            try:
                from app.core.security_layer import security, AuditEventType
                security.audit.log(
                    event_type=AuditEventType.DATA_DELETE,
                    actor_id="system:retention_job",
                    action="data_retention_run",
                    resource_type="retention_policy",
                    success=len(results["errors"]) == 0,
                    metadata={
                        "guest_sessions_anonymized": results["guest_sessions_anonymized"],
                        "expired_sessions_cleaned": results["expired_sessions_cleaned"],
                        "old_escalations_deleted": results["old_escalations_deleted"],
                        "errors": results["errors"],
                    },
                )
            except Exception as e:
                logger.debug(f"[Retention] Audit log failed (non-fatal): {e}")

    except Exception as e:
        results["errors"].append(f"database_connection: {e}")
        logger.error(f"[Retention] Database connection failed: {e}")

    results["completed_at"] = datetime.utcnow().isoformat()
    results["success"] = len(results["errors"]) == 0

    logger.info(f"[Retention] Run complete: {results}")
    return results


# ─── Celery task registration ─────────────────────────────────────────────────

def register_retention_task():
    """
    Register the retention job with Celery beat.
    Call this from workers/tasks.py.
    """
    try:
        from celery import shared_task
        import asyncio

        @shared_task(name="data_retention.run_daily")
        def run_retention_task():
            """Daily data retention enforcement."""
            return asyncio.get_event_loop().run_until_complete(run_retention())

        return run_retention_task
    except ImportError:
        logger.debug("[Retention] Celery not available — retention task not registered")
        return None
