"""
Celery Application.

Background task processing for:
- Market event ingestion (daily)
- Experience demand refresh (weekly)
- Operational snapshot refresh (hourly/webhook)
- Proactive trigger evaluation (event-driven)
"""

from celery import Celery
from celery.schedules import crontab
import os


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


FOCUS_CONCIERGE_ONLY = _env_bool("FOCUS_CONCIERGE_ONLY", True)
ENABLE_CONCIERGE_MARKET_SIGNALS = _env_bool("ENABLE_CONCIERGE_MARKET_SIGNALS", True)
ENABLE_CONCIERGE_HEALTH_CHECKS = _env_bool("ENABLE_CONCIERGE_HEALTH_CHECKS", True)
ENABLE_INBOX_POLL_SCHEDULE = _env_bool("ENABLE_INBOX_POLL_SCHEDULE", False)

# Create Celery app
celery_app = Celery(
    "rental_intelligence",
    broker=os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0"),
    backend=os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/0"),
    include=["app.workers.tasks"],
)

# Celery configuration
task_routes = {
    "app.workers.tasks.refresh_operational_snapshot": {"queue": "operations"},
    "app.workers.tasks.evaluate_proactive_triggers": {"queue": "concierge"},
    "app.workers.tasks.sync_pms_sessions": {"queue": "concierge"},
    "app.workers.tasks.check_escalation_slas": {"queue": "concierge"},
    "app.workers.tasks.curate_knowledge_gaps": {"queue": "concierge"},
    "app.workers.tasks.scan_healer_proposals": {"queue": "concierge"},
    "app.workers.tasks.check_concierge_health": {"queue": "concierge"},
    "app.workers.tasks.check_normalization_coverage_tripwire": {"queue": "concierge"},
    "app.workers.tasks.poll_connected_inboxes_all_operators": {"queue": "ingestion"},
    "app.workers.tasks.poll_connected_inbox_for_operator": {"queue": "ingestion"},
    "app.workers.tasks.renew_gmail_inbox_watches": {"queue": "ingestion"},
    "app.workers.tasks.enforce_message_retention_policies": {"queue": "concierge"},
}
if (not FOCUS_CONCIERGE_ONLY) or ENABLE_CONCIERGE_MARKET_SIGNALS:
    task_routes.update(
        {
            "app.workers.tasks.ingest_market_events": {"queue": "ingestion"},
            "app.workers.tasks.refresh_experience_demand": {"queue": "ingestion"},
        }
    )

beat_schedule = {
    # Hourly: Refresh operational snapshots for active properties
    "refresh-operational-snapshots-hourly": {
        "task": "app.workers.tasks.refresh_operational_snapshots_batch",
        "schedule": crontab(minute=0),  # Top of every hour
        "args": (),
    },
    # Every 15 minutes: Evaluate proactive triggers
    "evaluate-proactive-triggers": {
        "task": "app.workers.tasks.evaluate_proactive_triggers_batch",
        "schedule": crontab(minute="*/15"),  # Every 15 minutes
        "args": (),
    },
    # Hourly: Reconcile concierge sessions against live PMS
    "sync-pms-sessions-hourly": {
        "task": "app.workers.tasks.sync_pms_sessions",
        "schedule": crontab(minute=30),  # :30 past each hour
        "args": (),
    },
    # Every 5 minutes: Check escalation SLA breaches
    "check-escalation-slas": {
        "task": "app.workers.tasks.check_escalation_slas",
        "schedule": crontab(minute="*/5"),
        "args": (),
    },
    # Every 5 minutes: Fire alert escalation chain for unacked operator alerts
    "check-unacked-alerts": {
        "task": "app.workers.tasks.check_unacked_alerts",
        "schedule": crontab(minute="*/5"),
        "args": (),
    },
    # Hourly: Sync all operators' Escapia listings + bookings into DB
    "sync-pms-all-operators": {
        "task": "app.workers.tasks.sync_pms_all_operators",
        "schedule": crontab(minute=45),  # :45 past each hour
        "args": (),
    },
    # Hourly: Check for stale/superseded drafts across all operators
    "void-stale-drafts": {
        "task": "app.workers.tasks.void_stale_drafts_all_operators",
        "schedule": crontab(minute=30),  # :30 past each hour
        "args": (),
    },
    # Nightly: Rebuild platform intelligence from anonymized edit signals
    "rebuild-platform-intelligence": {
        "task": "app.workers.tasks.rebuild_platform_intelligence_task",
        "schedule": crontab(hour=3, minute=0),  # 3am nightly
        "args": (),
    },
    # Hourly: Auto-restore contacts whose OOO period has expired
    "restore-expired-ooo": {
        "task": "app.workers.tasks.restore_expired_ooo",
        "schedule": crontab(minute=15),  # :15 past each hour
        "args": (),
    },
    # Daily: Curate knowledge gaps
    "curate-knowledge-gaps-daily": {
        "task": "app.workers.tasks.curate_knowledge_gaps",
        "schedule": crontab(hour=4, minute=0),
        "args": (),
    },
    "scan-healer-proposals-daily": {
        "task": "app.workers.tasks.scan_healer_proposals",
        "schedule": crontab(hour=5, minute=0),
        "kwargs": {"window_hours": 24},
    },
    "enforce-message-retention-daily": {
        "task": "app.workers.tasks.enforce_message_retention_policies",
        "schedule": crontab(hour=4, minute=30),
        "args": (),
    },
    # Nightly: Append one autonomy posture snapshot per active tenant (append-only history)
    "snapshot-autonomy-nightly": {
        "task": "app.workers.tasks.snapshot_autonomy_all_operators",
        "schedule": crontab(hour=6, minute=0),  # 6am nightly — 3am taken by platform-intel
        "args": (),
    },
}
if (not FOCUS_CONCIERGE_ONLY) or ENABLE_CONCIERGE_MARKET_SIGNALS:
    beat_schedule.update(
        {
            "ingest-market-events-daily": {
                "task": "app.workers.tasks.ingest_market_events",
                "schedule": crontab(hour=2, minute=0),
                "args": (),
            },
            "refresh-experience-demand-weekly": {
                "task": "app.workers.tasks.refresh_experience_demand",
                "schedule": crontab(hour=3, minute=0, day_of_week=1),
                "args": (),
            },
        }
    )
if ENABLE_CONCIERGE_HEALTH_CHECKS:
    beat_schedule["check-concierge-health"] = {
        "task": "app.workers.tasks.check_concierge_health",
        "schedule": crontab(minute="*/10"),
        "args": (),
    }
    beat_schedule["check-normalization-coverage-tripwire"] = {
        "task": "app.workers.tasks.check_normalization_coverage_tripwire",
        "schedule": crontab(minute=20),
        "args": (),
    }
if ENABLE_INBOX_POLL_SCHEDULE:
    beat_schedule["poll-email-inboxes"] = {
        "task": "app.workers.tasks.poll_connected_inboxes_all_operators",
        "schedule": crontab(minute="*/5"),
        "args": (),
    }
beat_schedule["renew-gmail-inbox-watches"] = {
    "task": "app.workers.tasks.renew_gmail_inbox_watches",
    "schedule": crontab(minute=10),
    "args": (),
}

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    
    # Task routing
    task_routes=task_routes,

    # Beat schedule (periodic tasks)
    beat_schedule=beat_schedule,
    
    # Task settings
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
)


# Optional: Flask/FastAPI integration helper
def init_celery(app=None):
    """
    Initialize Celery with application context (if using Flask/FastAPI).
    """
    if app:
        celery_app.conf.update(app.config)
    return celery_app
