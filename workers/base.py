"""
Worker Base Infrastructure.

Provides the foundation for all worker types:
- Ingestion Workers
- Normalization Workers  
- Analytics Workers
- Concierge Intelligence Workers
- Feedback Loop Workers

Design Principles:
1. Each worker is idempotent
2. All workers respect tenant isolation
3. Workers never block the API
4. Failed jobs are retried with exponential backoff
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Dict, Generic, List, Optional, Type, TypeVar
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, ConfigDict

logger = logging.getLogger(__name__)


# =============================================================================
# WORKER TYPES
# =============================================================================

class WorkerCategory(str, Enum):
    """Categories of workers for routing and scaling."""
    INGESTION = "ingestion"
    NORMALIZATION = "normalization"
    ANALYTICS = "analytics"
    CONCIERGE = "concierge"
    FEEDBACK = "feedback"


class JobStatus(str, Enum):
    """Status of a worker job."""
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"
    CANCELLED = "cancelled"


class JobPriority(int, Enum):
    """Priority levels for job scheduling."""
    CRITICAL = 1   # System health, blocking issues
    HIGH = 2       # User-triggered, time-sensitive
    NORMAL = 3     # Scheduled background work
    LOW = 4        # Nice-to-have enrichment
    BACKGROUND = 5 # Can wait indefinitely


# =============================================================================
# JOB DEFINITION
# =============================================================================

class JobPayload(BaseModel):
    """Base class for job payloads."""
    tenant_id: UUID

    model_config = ConfigDict(extra="allow")


T = TypeVar("T", bound=JobPayload)


@dataclass
class Job(Generic[T]):
    """
    A unit of work for a worker.
    
    Jobs are:
    - Tenant-scoped (always have tenant_id)
    - Idempotent (can be retried safely)
    - Auditable (full history preserved)
    """
    job_id: UUID = field(default_factory=uuid4)
    
    # Classification
    worker_name: str = ""
    category: WorkerCategory = WorkerCategory.INGESTION
    
    # Payload
    payload: Optional[T] = None
    
    # Status
    status: JobStatus = JobStatus.PENDING
    priority: JobPriority = JobPriority.NORMAL
    
    # Timing
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    # Retry handling
    retry_count: int = 0
    max_retries: int = 3
    retry_delay_seconds: int = 60
    last_error: Optional[str] = None
    
    # Result
    result: Optional[Dict[str, Any]] = None
    
    @property
    def tenant_id(self) -> Optional[UUID]:
        return self.payload.tenant_id if self.payload else None
    
    def should_retry(self) -> bool:
        """Check if job should be retried."""
        return (
            self.status == JobStatus.FAILED and 
            self.retry_count < self.max_retries
        )
    
    def next_retry_at(self) -> datetime:
        """Calculate when to retry (exponential backoff)."""
        delay = self.retry_delay_seconds * (2 ** self.retry_count)
        return datetime.now(timezone.utc) + timedelta(seconds=delay)


@dataclass
class JobResult:
    """Result of a job execution."""
    success: bool
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    duration_ms: int = 0
    items_processed: int = 0
    warnings: List[str] = field(default_factory=list)


# =============================================================================
# BASE WORKER
# =============================================================================

class BaseWorker(ABC, Generic[T]):
    """
    Abstract base class for all workers.
    
    Subclasses implement:
    - process(): The actual work logic
    - validate_payload(): Input validation
    """
    
    # Class attributes - override in subclasses
    name: str = "base_worker"
    category: WorkerCategory = WorkerCategory.INGESTION
    max_retries: int = 3
    timeout_seconds: int = 300
    
    def __init__(self):
        self.logger = logging.getLogger(f"worker.{self.name}")
    
    @abstractmethod
    async def process(self, payload: T) -> JobResult:
        """
        Process a job payload.
        
        This is where the actual work happens.
        Must be idempotent - same input always produces same output.
        """
        pass
    
    def validate_payload(self, payload: T) -> Optional[str]:
        """
        Validate payload before processing.
        
        Returns error message if invalid, None if valid.
        """
        if not payload.tenant_id:
            return "tenant_id is required"
        return None
    
    async def execute(self, job: Job[T]) -> JobResult:
        """
        Execute a job with error handling and logging.
        
        This wraps process() with:
        - Validation
        - Timing
        - Error handling
        - Logging
        """
        start_time = datetime.now(timezone.utc)
        job.status = JobStatus.RUNNING
        job.started_at = start_time
        
        self.logger.info(
            f"Starting job {job.job_id} for tenant {job.tenant_id}"
        )
        
        try:
            # Validate
            validation_error = self.validate_payload(job.payload)
            if validation_error:
                raise ValueError(f"Validation failed: {validation_error}")
            
            # Process with timeout
            result = await asyncio.wait_for(
                self.process(job.payload),
                timeout=self.timeout_seconds
            )
            
            # Success
            job.status = JobStatus.COMPLETED
            job.completed_at = datetime.now(timezone.utc)
            job.result = result.data
            
            duration_ms = int((job.completed_at - start_time).total_seconds() * 1000)
            result.duration_ms = duration_ms
            
            self.logger.info(
                f"Completed job {job.job_id} in {duration_ms}ms, "
                f"processed {result.items_processed} items"
            )
            
            return result
            
        except asyncio.TimeoutError:
            error = f"Job timed out after {self.timeout_seconds}s"
            job.status = JobStatus.FAILED
            job.last_error = error
            self.logger.error(f"Job {job.job_id} timed out")
            return JobResult(success=False, error=error)
            
        except Exception as e:
            error = str(e)
            job.status = JobStatus.FAILED
            job.last_error = error
            job.retry_count += 1
            
            self.logger.exception(f"Job {job.job_id} failed: {error}")
            
            if job.should_retry():
                job.status = JobStatus.RETRYING
                self.logger.info(
                    f"Job {job.job_id} will retry at {job.next_retry_at()}"
                )
            
            return JobResult(success=False, error=error)
    
    def create_job(
        self, 
        payload: T, 
        priority: JobPriority = JobPriority.NORMAL
    ) -> Job[T]:
        """Create a new job for this worker."""
        return Job(
            worker_name=self.name,
            category=self.category,
            payload=payload,
            priority=priority,
            max_retries=self.max_retries,
        )


# =============================================================================
# WORKER REGISTRY
# =============================================================================

class WorkerRegistry:
    """
    Registry of all available workers.
    
    Workers register themselves here for discovery and routing.
    """
    
    _workers: Dict[str, Type[BaseWorker]] = {}
    _instances: Dict[str, BaseWorker] = {}
    
    @classmethod
    def register(cls, worker_class: Type[BaseWorker]) -> Type[BaseWorker]:
        """Register a worker class (can be used as decorator)."""
        cls._workers[worker_class.name] = worker_class
        return worker_class
    
    @classmethod
    def get_worker(cls, name: str) -> Optional[BaseWorker]:
        """Get or create a worker instance by name."""
        if name not in cls._instances:
            worker_class = cls._workers.get(name)
            if worker_class:
                cls._instances[name] = worker_class()
        return cls._instances.get(name)
    
    @classmethod
    def get_workers_by_category(
        cls, 
        category: WorkerCategory
    ) -> List[BaseWorker]:
        """Get all workers in a category."""
        return [
            cls.get_worker(name)
            for name, worker_class in cls._workers.items()
            if worker_class.category == category
        ]
    
    @classmethod
    def list_workers(cls) -> Dict[str, Dict[str, Any]]:
        """List all registered workers."""
        return {
            name: {
                "category": worker_class.category.value,
                "max_retries": worker_class.max_retries,
                "timeout_seconds": worker_class.timeout_seconds,
            }
            for name, worker_class in cls._workers.items()
        }


# Convenience decorator
def register_worker(cls: Type[BaseWorker]) -> Type[BaseWorker]:
    """Decorator to register a worker class."""
    return WorkerRegistry.register(cls)


# =============================================================================
# JOB QUEUE INTERFACE
# =============================================================================

class JobQueue(ABC):
    """
    Abstract interface for job queues.
    
    Implementations:
    - RedisJobQueue (production)
    - InMemoryJobQueue (testing)
    """
    
    @abstractmethod
    async def enqueue(self, job: Job) -> bool:
        """Add a job to the queue."""
        pass
    
    @abstractmethod
    async def dequeue(
        self, 
        category: Optional[WorkerCategory] = None
    ) -> Optional[Job]:
        """Get the next job from the queue."""
        pass
    
    @abstractmethod
    async def complete(self, job: Job) -> bool:
        """Mark a job as completed."""
        pass
    
    @abstractmethod
    async def fail(self, job: Job, error: str) -> bool:
        """Mark a job as failed."""
        pass
    
    @abstractmethod
    async def get_job(self, job_id: UUID) -> Optional[Job]:
        """Get a job by ID."""
        pass
    
    @abstractmethod
    async def get_queue_stats(self) -> Dict[str, Any]:
        """Get queue statistics."""
        pass


class InMemoryJobQueue(JobQueue):
    """Simple in-memory queue for testing."""
    
    def __init__(self):
        self._pending: Dict[WorkerCategory, List[Job]] = {
            cat: [] for cat in WorkerCategory
        }
        self._all_jobs: Dict[UUID, Job] = {}
    
    async def enqueue(self, job: Job) -> bool:
        job.status = JobStatus.QUEUED
        self._pending[job.category].append(job)
        self._all_jobs[job.job_id] = job
        # Sort by priority
        self._pending[job.category].sort(key=lambda j: j.priority.value)
        return True
    
    async def dequeue(
        self, 
        category: Optional[WorkerCategory] = None
    ) -> Optional[Job]:
        categories = [category] if category else list(WorkerCategory)
        
        for cat in categories:
            if self._pending[cat]:
                return self._pending[cat].pop(0)
        return None
    
    async def complete(self, job: Job) -> bool:
        job.status = JobStatus.COMPLETED
        job.completed_at = datetime.now(timezone.utc)
        return True
    
    async def fail(self, job: Job, error: str) -> bool:
        job.status = JobStatus.FAILED
        job.last_error = error
        return True
    
    async def get_job(self, job_id: UUID) -> Optional[Job]:
        return self._all_jobs.get(job_id)
    
    async def get_queue_stats(self) -> Dict[str, Any]:
        return {
            "pending": {
                cat.value: len(jobs) 
                for cat, jobs in self._pending.items()
            },
            "total_jobs": len(self._all_jobs),
        }


# =============================================================================
# WORKER RUNNER
# =============================================================================

class WorkerRunner:
    """
    Runs workers continuously, pulling jobs from the queue.
    
    Each runner handles one category of workers.
    """
    
    def __init__(
        self,
        queue: JobQueue,
        category: WorkerCategory,
        concurrency: int = 5,
    ):
        self.queue = queue
        self.category = category
        self.concurrency = concurrency
        self._running = False
        self._semaphore = asyncio.Semaphore(concurrency)
        self.logger = logging.getLogger(f"runner.{category.value}")
    
    async def start(self):
        """Start the worker runner."""
        self._running = True
        self.logger.info(
            f"Starting {self.category.value} runner with concurrency={self.concurrency}"
        )
        
        while self._running:
            async with self._semaphore:
                job = await self.queue.dequeue(self.category)
                
                if job:
                    asyncio.create_task(self._process_job(job))
                else:
                    # No jobs, sleep briefly
                    await asyncio.sleep(0.1)
    
    async def stop(self):
        """Stop the worker runner."""
        self._running = False
        self.logger.info(f"Stopping {self.category.value} runner")
    
    async def _process_job(self, job: Job):
        """Process a single job."""
        worker = WorkerRegistry.get_worker(job.worker_name)
        
        if not worker:
            self.logger.error(f"Unknown worker: {job.worker_name}")
            await self.queue.fail(job, f"Unknown worker: {job.worker_name}")
            return
        
        result = await worker.execute(job)
        
        if result.success:
            await self.queue.complete(job)
        else:
            if job.should_retry():
                # Re-enqueue for retry
                await self.queue.enqueue(job)
            else:
                await self.queue.fail(job, result.error or "Unknown error")
