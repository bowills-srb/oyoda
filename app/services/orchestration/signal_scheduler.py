"""
Orchestration: Signal Scheduler.

Manages WHEN signals are collected and processed.
Does not compute signals - coordinates the signal lifecycle.

Responsibilities:
- Schedule signal collection
- Manage refresh policies
- Prioritize signal processing
- Track signal freshness

Non-responsibilities:
- Signal computation (domain layer)
- Database access (repository layer)
- Actual scraping (adapter layer)
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Callable, Set
from uuid import UUID, uuid4

from app.domain.signals import SignalType, SignalStage


# =============================================================================
# REFRESH POLICIES
# =============================================================================

class RefreshPolicy(str, Enum):
    """How often signals should be refreshed."""
    REALTIME = "realtime"      # On every request
    HOURLY = "hourly"          # Once per hour
    DAILY = "daily"            # Once per day
    WEEKLY = "weekly"          # Once per week
    ON_DEMAND = "on_demand"    # Only when explicitly requested


# Default refresh policies by signal type
DEFAULT_REFRESH_POLICIES: Dict[SignalType, RefreshPolicy] = {
    # Real-time signals
    SignalType.COMPETITOR_RATE_MOVEMENT: RefreshPolicy.HOURLY,
    SignalType.INVENTORY_PRESSURE: RefreshPolicy.HOURLY,
    SignalType.BOOKING_LEAD_TIME: RefreshPolicy.HOURLY,
    
    # Daily signals
    SignalType.OCCUPANCY_MOMENTUM: RefreshPolicy.DAILY,
    SignalType.DEMAND_PRESSURE: RefreshPolicy.DAILY,
    SignalType.RATE_POSITION: RefreshPolicy.DAILY,
    SignalType.PRICE_ELASTICITY: RefreshPolicy.DAILY,
    
    # Weekly signals
    SignalType.SEASONALITY_CURVE: RefreshPolicy.WEEKLY,
    SignalType.PLATFORM_DOMINANCE: RefreshPolicy.WEEKLY,
    SignalType.AMENITY_LIFT: RefreshPolicy.WEEKLY,
    SignalType.OPERATOR_DELTA: RefreshPolicy.WEEKLY,
    SignalType.SUPPLY_VELOCITY: RefreshPolicy.WEEKLY,
    SignalType.MARKET_SIMILARITY: RefreshPolicy.WEEKLY,
    SignalType.EXPANSION_FIT: RefreshPolicy.WEEKLY,
    
    # On-demand signals
    SignalType.GUEST_INTENT_FREQUENCY: RefreshPolicy.DAILY,
    SignalType.SENTIMENT_TREND: RefreshPolicy.DAILY,
    SignalType.UNMET_DEMAND: RefreshPolicy.DAILY,
}


def get_refresh_interval(policy: RefreshPolicy) -> timedelta:
    """Get refresh interval for a policy."""
    intervals = {
        RefreshPolicy.REALTIME: timedelta(minutes=5),
        RefreshPolicy.HOURLY: timedelta(hours=1),
        RefreshPolicy.DAILY: timedelta(days=1),
        RefreshPolicy.WEEKLY: timedelta(weeks=1),
        RefreshPolicy.ON_DEMAND: timedelta(days=365),  # Effectively never
    }
    return intervals.get(policy, timedelta(days=1))


# =============================================================================
# SIGNAL FRESHNESS
# =============================================================================

@dataclass
class SignalFreshness:
    """Tracks freshness of a signal type for a scope."""
    signal_type: SignalType
    geo_id: Optional[str]
    property_id: Optional[UUID]
    tenant_id: UUID
    
    last_collected: Optional[datetime] = None
    last_processed: Optional[datetime] = None
    next_refresh: Optional[datetime] = None
    
    refresh_policy: RefreshPolicy = RefreshPolicy.DAILY
    
    @property
    def is_stale(self) -> bool:
        """Check if signal needs refresh."""
        if not self.last_collected:
            return True
        if not self.next_refresh:
            return True
        return datetime.utcnow() >= self.next_refresh
    
    @property
    def staleness_hours(self) -> Optional[float]:
        """How many hours since last collection."""
        if not self.last_collected:
            return None
        return (datetime.utcnow() - self.last_collected).total_seconds() / 3600
    
    def mark_collected(self):
        """Mark as freshly collected."""
        self.last_collected = datetime.utcnow()
        interval = get_refresh_interval(self.refresh_policy)
        self.next_refresh = self.last_collected + interval
    
    def mark_processed(self):
        """Mark as processed."""
        self.last_processed = datetime.utcnow()


# =============================================================================
# COLLECTION JOB
# =============================================================================

class JobPriority(str, Enum):
    """Priority levels for collection jobs."""
    CRITICAL = "critical"    # Must run now
    HIGH = "high"           # Should run soon
    NORMAL = "normal"       # Run when able
    LOW = "low"             # Run eventually


@dataclass
class CollectionJob:
    """A scheduled signal collection job."""
    id: UUID = field(default_factory=uuid4)
    
    # What to collect
    signal_types: List[SignalType] = field(default_factory=list)
    geo_id: Optional[str] = None
    property_id: Optional[UUID] = None
    tenant_id: Optional[UUID] = None
    
    # Scheduling
    priority: JobPriority = JobPriority.NORMAL
    scheduled_at: datetime = field(default_factory=datetime.utcnow)
    run_at: Optional[datetime] = None
    
    # Execution
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    success: Optional[bool] = None
    error: Optional[str] = None
    
    # Results
    signals_collected: int = 0
    
    @property
    def is_due(self) -> bool:
        """Check if job is due to run."""
        if not self.run_at:
            return True
        return datetime.utcnow() >= self.run_at
    
    @property
    def is_complete(self) -> bool:
        """Check if job is complete."""
        return self.completed_at is not None
    
    def start(self):
        """Mark job as started."""
        self.started_at = datetime.utcnow()
    
    def complete(self, signals_collected: int):
        """Mark job as successfully completed."""
        self.completed_at = datetime.utcnow()
        self.success = True
        self.signals_collected = signals_collected
    
    def fail(self, error: str):
        """Mark job as failed."""
        self.completed_at = datetime.utcnow()
        self.success = False
        self.error = error


# =============================================================================
# SIGNAL SCHEDULER
# =============================================================================

class SignalScheduler:
    """
    Orchestrates signal collection timing.
    
    This is the SCHEDULER - it decides WHEN to collect signals.
    It does NOT:
    - Actually collect signals (adapters do that)
    - Compute signal values (domain layer does that)
    - Store signals (repository does that)
    """
    
    def __init__(self):
        # Track freshness per signal type + scope
        self._freshness: Dict[str, SignalFreshness] = {}
        
        # Pending jobs
        self._job_queue: List[CollectionJob] = []
        
        # Completed jobs (for audit)
        self._completed_jobs: List[CollectionJob] = []
    
    # -------------------------------------------------------------------------
    # FRESHNESS TRACKING
    # -------------------------------------------------------------------------
    
    def _freshness_key(
        self,
        signal_type: SignalType,
        tenant_id: UUID,
        geo_id: Optional[str] = None,
        property_id: Optional[UUID] = None,
    ) -> str:
        """Build key for freshness tracking."""
        parts = [signal_type.value, str(tenant_id)]
        if geo_id:
            parts.append(geo_id)
        if property_id:
            parts.append(str(property_id))
        return ":".join(parts)
    
    def get_freshness(
        self,
        signal_type: SignalType,
        tenant_id: UUID,
        geo_id: Optional[str] = None,
        property_id: Optional[UUID] = None,
    ) -> SignalFreshness:
        """Get freshness record for a signal."""
        key = self._freshness_key(signal_type, tenant_id, geo_id, property_id)
        
        if key not in self._freshness:
            policy = DEFAULT_REFRESH_POLICIES.get(signal_type, RefreshPolicy.DAILY)
            self._freshness[key] = SignalFreshness(
                signal_type=signal_type,
                geo_id=geo_id,
                property_id=property_id,
                tenant_id=tenant_id,
                refresh_policy=policy,
            )
        
        return self._freshness[key]
    
    def mark_collected(
        self,
        signal_type: SignalType,
        tenant_id: UUID,
        geo_id: Optional[str] = None,
        property_id: Optional[UUID] = None,
    ):
        """Mark a signal as freshly collected."""
        freshness = self.get_freshness(signal_type, tenant_id, geo_id, property_id)
        freshness.mark_collected()
    
    # -------------------------------------------------------------------------
    # STALE SIGNAL DETECTION
    # -------------------------------------------------------------------------
    
    def get_stale_signals(
        self,
        tenant_id: UUID,
        geo_id: Optional[str] = None,
        signal_types: Optional[List[SignalType]] = None,
    ) -> List[SignalFreshness]:
        """Get all stale signals for a scope."""
        stale = []
        
        types_to_check = signal_types or list(SignalType)
        
        for signal_type in types_to_check:
            freshness = self.get_freshness(signal_type, tenant_id, geo_id)
            if freshness.is_stale:
                stale.append(freshness)
        
        return stale
    
    def needs_refresh(
        self,
        signal_type: SignalType,
        tenant_id: UUID,
        geo_id: Optional[str] = None,
        property_id: Optional[UUID] = None,
    ) -> bool:
        """Check if a signal needs refresh."""
        freshness = self.get_freshness(signal_type, tenant_id, geo_id, property_id)
        return freshness.is_stale
    
    # -------------------------------------------------------------------------
    # JOB SCHEDULING
    # -------------------------------------------------------------------------
    
    def schedule_collection(
        self,
        signal_types: List[SignalType],
        tenant_id: UUID,
        geo_id: Optional[str] = None,
        property_id: Optional[UUID] = None,
        priority: JobPriority = JobPriority.NORMAL,
        run_at: Optional[datetime] = None,
    ) -> CollectionJob:
        """Schedule a signal collection job."""
        job = CollectionJob(
            signal_types=signal_types,
            geo_id=geo_id,
            property_id=property_id,
            tenant_id=tenant_id,
            priority=priority,
            run_at=run_at,
        )
        
        self._job_queue.append(job)
        self._sort_queue()
        
        return job
    
    def schedule_stale_refresh(
        self,
        tenant_id: UUID,
        geo_id: Optional[str] = None,
        priority: JobPriority = JobPriority.NORMAL,
    ) -> Optional[CollectionJob]:
        """Schedule refresh of all stale signals."""
        stale = self.get_stale_signals(tenant_id, geo_id)
        
        if not stale:
            return None
        
        signal_types = [f.signal_type for f in stale]
        return self.schedule_collection(
            signal_types=signal_types,
            tenant_id=tenant_id,
            geo_id=geo_id,
            priority=priority,
        )
    
    def _sort_queue(self):
        """Sort job queue by priority and scheduled time."""
        priority_order = {
            JobPriority.CRITICAL: 0,
            JobPriority.HIGH: 1,
            JobPriority.NORMAL: 2,
            JobPriority.LOW: 3,
        }
        self._job_queue.sort(
            key=lambda j: (priority_order[j.priority], j.scheduled_at)
        )
    
    # -------------------------------------------------------------------------
    # JOB EXECUTION
    # -------------------------------------------------------------------------
    
    def get_next_job(self) -> Optional[CollectionJob]:
        """Get the next job to run."""
        due_jobs = [j for j in self._job_queue if j.is_due and not j.is_complete]
        
        if not due_jobs:
            return None
        
        return due_jobs[0]
    
    def get_pending_jobs(self) -> List[CollectionJob]:
        """Get all pending jobs."""
        return [j for j in self._job_queue if not j.is_complete]
    
    def complete_job(self, job_id: UUID, signals_collected: int):
        """Mark a job as complete."""
        for job in self._job_queue:
            if job.id == job_id:
                job.complete(signals_collected)
                
                # Update freshness for collected signals
                if job.tenant_id:
                    for signal_type in job.signal_types:
                        self.mark_collected(
                            signal_type, job.tenant_id, job.geo_id, job.property_id
                        )
                
                # Move to completed
                self._completed_jobs.append(job)
                self._job_queue.remove(job)
                return
    
    def fail_job(self, job_id: UUID, error: str):
        """Mark a job as failed."""
        for job in self._job_queue:
            if job.id == job_id:
                job.fail(error)
                self._completed_jobs.append(job)
                self._job_queue.remove(job)
                return
    
    # -------------------------------------------------------------------------
    # STATS
    # -------------------------------------------------------------------------
    
    def get_stats(self) -> Dict[str, Any]:
        """Get scheduler statistics."""
        return {
            "freshness_entries": len(self._freshness),
            "pending_jobs": len(self.get_pending_jobs()),
            "completed_jobs": len(self._completed_jobs),
            "stale_signals": sum(1 for f in self._freshness.values() if f.is_stale),
        }


# =============================================================================
# SINGLETON
# =============================================================================

_scheduler: Optional[SignalScheduler] = None


def get_scheduler() -> SignalScheduler:
    """Get the singleton scheduler."""
    global _scheduler
    if _scheduler is None:
        _scheduler = SignalScheduler()
    return _scheduler


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Enums
    "RefreshPolicy",
    "JobPriority",
    
    # Models
    "SignalFreshness",
    "CollectionJob",
    
    # Default policies
    "DEFAULT_REFRESH_POLICIES",
    "get_refresh_interval",
    
    # Scheduler
    "SignalScheduler",
    "get_scheduler",
]
