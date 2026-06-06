"""
Worker System - Asynchronous computation for intelligence platform.

Worker Categories:
- Ingestion: PMS sync, webhooks, data fetching
- Normalization: Transform raw data to canonical schema
- Analytics: Market snapshots, pricing sensitivity, benchmarking
- Concierge: FAQ extraction, intent clustering, recommendations
- Feedback: Demand gaps, competitor insights, market trends

All workers are:
- Idempotent (safe to retry)
- Tenant-isolated (always scoped to tenant_id)
- Auditable (full execution history)
"""

from workers.base import (
    # Types
    WorkerCategory,
    JobStatus,
    JobPriority,
    
    # Core classes
    JobPayload,
    Job,
    JobResult,
    BaseWorker,
    
    # Registry
    WorkerRegistry,
    register_worker,
    
    # Queue
    JobQueue,
    InMemoryJobQueue,
    
    # Runner
    WorkerRunner,
)

__all__ = [
    # Types
    "WorkerCategory",
    "JobStatus", 
    "JobPriority",
    
    # Core classes
    "JobPayload",
    "Job",
    "JobResult",
    "BaseWorker",
    
    # Registry
    "WorkerRegistry",
    "register_worker",
    
    # Queue
    "JobQueue",
    "InMemoryJobQueue",
    
    # Runner
    "WorkerRunner",
]
