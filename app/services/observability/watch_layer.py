"""
Watch Layer — Observability for Beach Habitats

Lightweight W&B (Weights & Biases) + structured logging layer.

Tracks:
- Voice Pod interactions (latency, cost, EQ state)
- Tool executions (which tools, success/failure, approval flow)
- Agent runs (onboarding, market intelligence)
- Anomalies (crisis EQ detections, repeated failures)

Design:
- W&B is optional (gracefully disabled if not configured)
- All events also written to structured JSON logs
- Dashboard-ready: events emitted as SSE for the operator dashboard
- Zero-overhead when disabled (conditional short-circuit)

Usage:
    watch = get_watch_layer()

    # Log a Voice Pod response
    await watch.log_voice_interaction(
        session_id="sess_123",
        operator_id="op_456",
        user_message="Where's the nearest coffee shop?",
        response="Try Amavida Coffee, 0.3 miles away!",
        latency_ms=312,
        cost_usd=0.02,
        eq_state="neutral",
        eq_urgency="normal",
        retrieval_used=True,
    )

    # Log a tool execution
    await watch.log_tool_execution(
        session_id="sess_123",
        tool_name="opentable_book",
        success=True,
        latency_ms=890,
        approval_required=False,
    )
"""

import asyncio
import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    """Types of observable events."""
    VOICE_INTERACTION = "voice_interaction"
    TOOL_EXECUTION = "tool_execution"
    AGENT_RUN = "agent_run"
    EQ_ALERT = "eq_alert"
    ERROR = "error"
    PERFORMANCE = "performance"


@dataclass
class WatchEvent:
    """A single observable event."""
    event_type: EventType
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    
    # Context
    session_id: Optional[str] = None
    operator_id: Optional[str] = None
    property_code: Optional[str] = None
    
    # Metrics
    latency_ms: Optional[float] = None
    cost_usd: Optional[float] = None
    success: Optional[bool] = None
    
    # Payload (event-specific data)
    data: Dict[str, Any] = field(default_factory=dict)
    
    # Tags for W&B / filtering
    tags: List[str] = field(default_factory=list)


class WatchLayer:
    """
    Centralized observability layer.
    
    Backends:
    1. Structured JSON log (always active)
    2. W&B Weave (when WANDB_API_KEY is set)
    3. In-memory ring buffer (for dashboard SSE)
    4. Alerting hooks (for crisis EQ, repeated failures)
    """
    
    MAX_BUFFER_SIZE = 1000  # In-memory ring buffer
    
    def __init__(self):
        self._wandb_enabled = False
        self._weave_client = None
        self._event_buffer: List[WatchEvent] = []
        self._alert_hooks: List[Callable] = []
        self._stats: Dict[str, Any] = {
            "total_interactions": 0,
            "total_cost_usd": 0.0,
            "avg_latency_ms": 0.0,
            "eq_alerts": 0,
            "tool_executions": 0,
            "errors": 0,
        }
        self._initialized = False
    
    async def initialize(self) -> None:
        """Initialize backends. Call once at startup."""
        if self._initialized:
            return
        
        # Try W&B Weave
        wandb_key = os.getenv("WANDB_API_KEY")
        if wandb_key:
            try:
                import weave
                weave.init("beach-habitats")
                self._wandb_enabled = True
                logger.info("[Watch] W&B Weave initialized")
            except ImportError:
                logger.info("[Watch] weave not installed (pip install weave). Using local logging only.")
            except Exception as e:
                logger.warning(f"[Watch] W&B init failed: {e}. Using local logging only.")
        else:
            logger.info("[Watch] WANDB_API_KEY not set. Using local logging only.")
        
        self._initialized = True
    
    # =========================================================================
    # HIGH-LEVEL LOGGING METHODS
    # =========================================================================
    
    async def log_voice_interaction(
        self,
        session_id: str,
        operator_id: str,
        user_message: str,
        response: str,
        latency_ms: float,
        cost_usd: float = 0.0,
        eq_state: str = "neutral",
        eq_urgency: str = "normal",
        retrieval_used: bool = False,
        quick_answer: bool = False,
        property_code: Optional[str] = None,
    ) -> None:
        """Log a Voice Pod interaction."""
        event = WatchEvent(
            event_type=EventType.VOICE_INTERACTION,
            session_id=session_id,
            operator_id=operator_id,
            property_code=property_code,
            latency_ms=latency_ms,
            cost_usd=cost_usd,
            success=True,
            data={
                "user_message_len": len(user_message),
                "response_len": len(response),
                "eq_state": eq_state,
                "eq_urgency": eq_urgency,
                "retrieval_used": retrieval_used,
                "quick_answer": quick_answer,
            },
            tags=["voice", f"eq:{eq_state}", f"urgency:{eq_urgency}"],
        )
        
        await self._emit(event)
        
        # Update stats
        self._stats["total_interactions"] += 1
        self._stats["total_cost_usd"] += cost_usd
        n = self._stats["total_interactions"]
        self._stats["avg_latency_ms"] = (
            (self._stats["avg_latency_ms"] * (n - 1) + latency_ms) / n
        )
        
        # Alert on crisis EQ
        if eq_urgency == "crisis":
            await self._alert_eq_crisis(session_id, operator_id, eq_state)
    
    async def log_tool_execution(
        self,
        session_id: str,
        tool_name: str,
        success: bool,
        latency_ms: float,
        operator_id: Optional[str] = None,
        approval_required: bool = False,
        approval_status: Optional[str] = None,
        error_code: Optional[str] = None,
        financial_impact: Optional[float] = None,
    ) -> None:
        """Log a tool execution."""
        event = WatchEvent(
            event_type=EventType.TOOL_EXECUTION,
            session_id=session_id,
            operator_id=operator_id,
            latency_ms=latency_ms,
            success=success,
            data={
                "tool_name": tool_name,
                "approval_required": approval_required,
                "approval_status": approval_status,
                "error_code": error_code,
                "financial_impact_usd": financial_impact,
            },
            tags=["tool", tool_name, "success" if success else "failure"],
        )
        
        await self._emit(event)
        self._stats["tool_executions"] += 1
        if not success:
            self._stats["errors"] += 1
    
    async def log_agent_run(
        self,
        agent_name: str,
        operator_id: str,
        success: bool,
        latency_ms: float,
        tokens_used: Optional[int] = None,
        cost_usd: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Log an agent run (onboarding, market intel, etc.)."""
        event = WatchEvent(
            event_type=EventType.AGENT_RUN,
            operator_id=operator_id,
            latency_ms=latency_ms,
            cost_usd=cost_usd,
            success=success,
            data={
                "agent": agent_name,
                "tokens_used": tokens_used,
                **(metadata or {}),
            },
            tags=["agent", agent_name],
        )
        await self._emit(event)
    
    async def log_retrieval_result(
        self,
        session_id: str,
        operator_id: str,
        property_code: str,
        query: str,
        hit: bool,
        chunk_count: int,
        latency_ms: float,
    ) -> None:
        """
        Log a knowledge retrieval attempt and whether it returned results.

        Hit rates are tracked per-property so a busy property doesn't
        mask degradation at a low-traffic property.  Degradation alert fires
        when a property's hit rate drops below 40% after 10+ attempts.
        """
        # Per-property counters (lazy init)
        if not hasattr(self, "_retrieval_by_property"):
            self._retrieval_by_property: Dict[str, Dict[str, int]] = {}

        prop_stats = self._retrieval_by_property.setdefault(
            property_code, {"attempts": 0, "hits": 0}
        )
        prop_stats["attempts"] += 1
        prop_stats["hits"] += 1 if hit else 0

        # Global counters kept for backward-compat / overview stats
        self._retrieval_attempts = getattr(self, "_retrieval_attempts", 0) + 1
        self._retrieval_hits = getattr(self, "_retrieval_hits", 0) + (1 if hit else 0)

        prop_hit_rate = prop_stats["hits"] / prop_stats["attempts"]

        event = WatchEvent(
            event_type=EventType.TOOL_EXECUTION,
            session_id=session_id,
            operator_id=operator_id,
            property_code=property_code,
            latency_ms=latency_ms,
            success=hit,
            data={
                "tool": "librarian.retrieve",
                "query_preview": query[:80],
                "hit": hit,
                "chunk_count": chunk_count,
                "property_hit_rate": round(prop_hit_rate, 3),
                "property_attempts": prop_stats["attempts"],
                "global_hit_rate": (
                    round(self._retrieval_hits / self._retrieval_attempts, 3)
                    if self._retrieval_attempts > 0 else None
                ),
            },
            tags=["retrieval", "hit" if hit else "miss", f"property:{property_code}"],
        )
        await self._emit(event)

        # Alert on sustained low hit rate for THIS property (>= 10 attempts)
        if prop_stats["attempts"] >= 10 and not hit and prop_hit_rate < 0.4:
            await self._alert_knowledge_degradation(
                operator_id=operator_id,
                property_code=property_code,
                hit_rate=prop_hit_rate,
                attempts=prop_stats["attempts"],
            )

    async def log_routing_decision(
        self,
        session_id: str,
        operator_id: str,
        property_code: str,
        message_preview: str,
        route: str,
        reason: str,
        trigger: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Log a routing decision from ConciergeRouter."""
        event = WatchEvent(
            event_type=EventType.AGENT_RUN,
            session_id=session_id,
            operator_id=operator_id,
            property_code=property_code,
            success=True,
            data={
                "agent": "concierge_router",
                "route": route,
                "reason": reason,
                "trigger": trigger,
                "message_preview": message_preview,
                **(metadata or {}),
            },
            tags=["routing", f"route:{route}"],
        )
        await self._emit(event)

    async def log_error(
        self,
        context: str,
        error: Exception,
        session_id: Optional[str] = None,
        operator_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Log an error."""
        event = WatchEvent(
            event_type=EventType.ERROR,
            session_id=session_id,
            operator_id=operator_id,
            success=False,
            data={
                "context": context,
                "error_type": type(error).__name__,
                "error_message": str(error),
                **(metadata or {}),
            },
            tags=["error", type(error).__name__],
        )
        await self._emit(event)
        self._stats["errors"] += 1
    
    # =========================================================================
    # STATS & DASHBOARD
    # =========================================================================
    
    def get_stats(self) -> Dict[str, Any]:
        """Get current aggregate stats."""
        return dict(self._stats)

    def get_retrieval_stats(self) -> Dict[str, Any]:
        """
        Per-property and global retrieval hit rate stats.
        Used by the operator dashboard Knowledge Gaps tab and Watch endpoint.
        """
        by_property = getattr(self, "_retrieval_by_property", {})
        global_attempts = getattr(self, "_retrieval_attempts", 0)
        global_hits = getattr(self, "_retrieval_hits", 0)

        property_stats = [
            {
                "property_code": code,
                "attempts": stats["attempts"],
                "hits": stats["hits"],
                "hit_rate": round(stats["hits"] / stats["attempts"], 3)
                if stats["attempts"] > 0 else None,
                "degraded": (
                    stats["attempts"] >= 10
                    and (stats["hits"] / stats["attempts"]) < 0.4
                ),
            }
            for code, stats in by_property.items()
        ]

        return {
            "global_attempts": global_attempts,
            "global_hits": global_hits,
            "global_hit_rate": round(global_hits / global_attempts, 3) if global_attempts > 0 else None,
            "by_property": sorted(property_stats, key=lambda x: x["attempts"], reverse=True),
            "degraded_properties": [p["property_code"] for p in property_stats if p["degraded"]],
        }
    
    def get_recent_events(
        self,
        n: int = 50,
        event_type: Optional[EventType] = None,
        operator_id: Optional[str] = None,
    ) -> List[WatchEvent]:
        """Get recent events from the ring buffer."""
        events = list(reversed(self._event_buffer))
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        if operator_id:
            events = [e for e in events if e.operator_id == operator_id]
        return events[:n]
    
    def add_alert_hook(self, hook: Callable) -> None:
        """
        Register a callback for alerts.
        Called with (event_type: str, data: dict) on notable events.
        
        Example:
            async def my_hook(event_type, data):
                await send_slack_message(f"Alert: {event_type}")
            
            watch.add_alert_hook(my_hook)
        """
        self._alert_hooks.append(hook)
    
    # =========================================================================
    # INTERNAL
    # =========================================================================
    
    async def _emit(self, event: WatchEvent) -> None:
        """Emit event to all backends."""
        # 1. Structured log (always)
        logger.info(
            "[Watch] %s | session=%s op=%s latency=%.1fms cost=$%.4f ok=%s",
            event.event_type.value,
            event.session_id or "-",
            event.operator_id or "-",
            event.latency_ms or 0,
            event.cost_usd or 0,
            event.success,
        )
        
        # 2. Ring buffer (for dashboard)
        self._event_buffer.append(event)
        if len(self._event_buffer) > self.MAX_BUFFER_SIZE:
            self._event_buffer = self._event_buffer[-self.MAX_BUFFER_SIZE:]
        
        # 3. W&B Weave (if enabled)
        if self._wandb_enabled:
            try:
                await self._emit_wandb(event)
            except Exception as e:
                logger.debug(f"[Watch] W&B emit failed: {e}")
    
    async def _emit_wandb(self, event: WatchEvent) -> None:
        """Emit to W&B Weave."""
        import weave
        
        # Log as a Weave call
        @weave.op()
        def _log_event(**kwargs):
            return kwargs
        
        _log_event(
            event_type=event.event_type.value,
            session_id=event.session_id,
            operator_id=event.operator_id,
            latency_ms=event.latency_ms,
            cost_usd=event.cost_usd,
            success=event.success,
            tags=event.tags,
            **event.data,
        )
    
    async def _alert_knowledge_degradation(
        self,
        operator_id: str,
        property_code: str,
        hit_rate: float,
        attempts: int,
    ) -> None:
        """Fire alert when retrieval hit rate drops below 40%."""
        logger.warning(
            "[Watch] Knowledge degradation: property=%s hit_rate=%.1f%% attempts=%d",
            property_code, hit_rate * 100, attempts,
        )
        self._stats["eq_alerts"] = self._stats.get("eq_alerts", 0) + 1

        alert_event = WatchEvent(
            event_type=EventType.EQ_ALERT,
            operator_id=operator_id,
            property_code=property_code,
            success=False,
            data={
                "alert_type": "knowledge_degradation",
                "hit_rate": round(hit_rate, 3),
                "attempts": attempts,
                "message": (
                    f"Retrieval hit rate for {property_code} is {hit_rate*100:.0f}% "
                    f"(threshold: 40%). Check vector store indexing for this property."
                ),
            },
            tags=["knowledge_degradation", f"property:{property_code}"],
        )
        await self._emit(alert_event)

        for hook in self._alert_hooks:
            try:
                payload = {
                    "alert_type": "knowledge_degradation",
                    "operator_id": operator_id,
                    "property_code": property_code,
                    "hit_rate": hit_rate,
                    "attempts": attempts,
                }
                if asyncio.iscoroutinefunction(hook):
                    await hook("knowledge_degradation", payload)
                else:
                    hook("knowledge_degradation", payload)
            except Exception as exc:
                logger.debug("[Watch] Alert hook failed: %s", exc)

    async def _alert_eq_crisis(
        self,
        session_id: str,
        operator_id: str,
        eq_state: str,
    ) -> None:
        """Fire alert hooks for crisis EQ detection."""
        self._stats["eq_alerts"] += 1
        
        crisis_event = WatchEvent(
            event_type=EventType.EQ_ALERT,
            session_id=session_id,
            operator_id=operator_id,
            success=False,  # Indicates intervention needed
            data={
                "eq_state": eq_state,
                "urgency": "crisis",
                "message": "Guest in crisis state — immediate attention recommended.",
            },
            tags=["eq_alert", "crisis"],
        )
        await self._emit(crisis_event)
        
        # Fire hooks
        for hook in self._alert_hooks:
            try:
                if asyncio.iscoroutinefunction(hook):
                    await hook("eq_crisis", {
                        "session_id": session_id,
                        "operator_id": operator_id,
                        "eq_state": eq_state,
                    })
                else:
                    hook("eq_crisis", {
                        "session_id": session_id,
                        "operator_id": operator_id,
                        "eq_state": eq_state,
                    })
            except Exception as e:
                logger.warning(f"[Watch] Alert hook failed: {e}")


# =========================================================================
# CONTEXT MANAGER — wrap any async op with automatic timing + logging
# =========================================================================

class WatchContext:
    """
    Context manager for timing and logging any async block.
    
    Usage:
        async with WatchContext(watch, "voice_pod.respond", session_id=sid) as ctx:
            result = await pod.respond(message)
            ctx.set_success(True)
            ctx.set_cost(0.02)
    """
    
    def __init__(
        self,
        watch: WatchLayer,
        label: str,
        session_id: Optional[str] = None,
        operator_id: Optional[str] = None,
    ):
        self.watch = watch
        self.label = label
        self.session_id = session_id
        self.operator_id = operator_id
        self._start: float = 0.0
        self._success: bool = True
        self._cost: float = 0.0
        self._metadata: Dict[str, Any] = {}
    
    def set_success(self, success: bool) -> None:
        self._success = success
    
    def set_cost(self, cost: float) -> None:
        self._cost = cost
    
    def set_metadata(self, **kwargs) -> None:
        self._metadata.update(kwargs)
    
    async def __aenter__(self) -> "WatchContext":
        self._start = time.time()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        latency_ms = (time.time() - self._start) * 1000
        
        if exc_type:
            self._success = False
            await self.watch.log_error(
                context=self.label,
                error=exc_val,
                session_id=self.session_id,
                operator_id=self.operator_id,
            )
        
        await self.watch.log_agent_run(
            agent_name=self.label,
            operator_id=self.operator_id or "unknown",
            success=self._success,
            latency_ms=latency_ms,
            cost_usd=self._cost,
            metadata=self._metadata,
        )


# =========================================================================
# SINGLETON
# =========================================================================

_watch_layer: Optional[WatchLayer] = None


def get_watch_layer() -> WatchLayer:
    """Get or create the global Watch Layer."""
    global _watch_layer
    if _watch_layer is None:
        _watch_layer = WatchLayer()
    return _watch_layer


async def init_watch_layer() -> WatchLayer:
    """Initialize and return the Watch Layer. Call at app startup."""
    watch = get_watch_layer()
    await watch.initialize()
    return watch
