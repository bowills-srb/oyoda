"""
Event-Triggered Re-Evaluation System.

Let signals trigger re-analysis:
- Booking spike
- Cancellation cluster
- Weather anomaly
- Event detection

Creates:
- Audit trails
- "Why did pricing change?" answers
- Future automation hooks

No UI needed initially - just infrastructure.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set
from uuid import UUID, uuid4
import logging

logger = logging.getLogger(__name__)


# =============================================================================
# EVENT TYPES
# =============================================================================

class EventType(str, Enum):
    """Types of triggering events."""
    # Guest lifecycle events
    INQUIRY_RECEIVED = "inquiry_received"
    DRAFT_GENERATED = "draft_generated"
    SESSION_CREATED = "session_created"
    ESCALATION_RAISED = "escalation_raised"
    SESSION_CLOSED = "session_closed"

    # Booking events
    BOOKING_SPIKE = "booking_spike"
    BOOKING_DROUGHT = "booking_drought"
    CANCELLATION_CLUSTER = "cancellation_cluster"
    
    # Rate events
    COMPETITOR_RATE_CHANGE = "competitor_rate_change"
    OWN_RATE_CHANGE = "own_rate_change"
    
    # Market events
    SUPPLY_SURGE = "supply_surge"
    DEMAND_SURGE = "demand_surge"
    
    # External events
    WEATHER_ANOMALY = "weather_anomaly"
    LOCAL_EVENT_DETECTED = "local_event_detected"
    HOLIDAY_APPROACHING = "holiday_approaching"
    
    # Signal events
    SIGNAL_STALE = "signal_stale"
    SIGNAL_CONFIDENCE_DROP = "signal_confidence_drop"
    SIGNAL_ANOMALY = "signal_anomaly"
    
    # Manual triggers
    MANUAL_REVIEW = "manual_review"
    POLICY_CHANGE = "policy_change"


class EventSeverity(str, Enum):
    """Event severity levels."""
    LOW = "low"           # Log only
    MEDIUM = "medium"     # Re-evaluate, no alert
    HIGH = "high"         # Re-evaluate + alert
    CRITICAL = "critical" # Immediate action required


class EventAction(str, Enum):
    """Actions triggered by events."""
    LOG_ONLY = "log_only"
    RE_EVALUATE = "re_evaluate"
    ALERT_OPERATOR = "alert_operator"
    ALERT_MANAGER = "alert_manager"
    PAUSE_AUTOMATION = "pause_automation"
    URGENT_REVIEW = "urgent_review"


# =============================================================================
# EVENT MODELS
# =============================================================================

@dataclass
class TriggerEvent:
    """
    A detected event that may trigger re-evaluation.
    
    This is the core event model.
    """
    id: UUID = field(default_factory=uuid4)
    
    # Event type
    event_type: EventType = EventType.MANUAL_REVIEW
    
    # Severity
    severity: EventSeverity = EventSeverity.LOW
    
    # Context
    geo_id: Optional[str] = None
    property_id: Optional[UUID] = None
    tenant_id: Optional[UUID] = None
    
    # Event details
    description: str = ""
    data: Dict[str, Any] = field(default_factory=dict)
    
    # Thresholds that were exceeded
    threshold_exceeded: Optional[str] = None
    threshold_value: Optional[float] = None
    actual_value: Optional[float] = None
    
    # Timing
    detected_at: datetime = field(default_factory=datetime.utcnow)
    
    # Processing status
    processed: bool = False
    processed_at: Optional[datetime] = None
    actions_taken: List[EventAction] = field(default_factory=list)
    
    def to_audit_record(self) -> Dict[str, Any]:
        """Convert to audit record."""
        return {
            "event_id": str(self.id),
            "event_type": self.event_type.value,
            "severity": self.severity.value,
            "geo_id": self.geo_id,
            "property_id": str(self.property_id) if self.property_id else None,
            "description": self.description,
            "threshold_exceeded": self.threshold_exceeded,
            "detected_at": self.detected_at.isoformat(),
            "processed": self.processed,
            "actions_taken": [a.value for a in self.actions_taken],
        }


@dataclass
class EventRule:
    """
    A rule that defines when to trigger an event.
    
    Rules are evaluated against incoming data.
    """
    name: str
    event_type: EventType
    
    # Conditions
    metric: str  # What to measure
    operator: str  # "gt", "lt", "eq", "change_pct"
    threshold: float
    
    # Time window
    window_hours: int = 24
    
    # Resulting severity
    severity: EventSeverity = EventSeverity.MEDIUM
    
    # Actions to take
    actions: List[EventAction] = field(default_factory=lambda: [EventAction.RE_EVALUATE])
    
    # Active status
    is_active: bool = True
    
    def evaluate(self, current: float, previous: Optional[float] = None) -> Optional[TriggerEvent]:
        """
        Evaluate rule against values.
        
        Returns TriggerEvent if rule is triggered, None otherwise.
        """
        if not self.is_active:
            return None
        
        triggered = False
        
        if self.operator == "gt":
            triggered = current > self.threshold
        elif self.operator == "lt":
            triggered = current < self.threshold
        elif self.operator == "eq":
            triggered = abs(current - self.threshold) < 0.001
        elif self.operator == "change_pct" and previous is not None and previous != 0:
            change_pct = (current - previous) / previous
            triggered = abs(change_pct) > self.threshold
        
        if triggered:
            return TriggerEvent(
                event_type=self.event_type,
                severity=self.severity,
                description=f"{self.name}: {self.metric} {self.operator} {self.threshold}",
                threshold_exceeded=self.metric,
                threshold_value=self.threshold,
                actual_value=current,
            )
        
        return None


@dataclass
class EvaluationResult:
    """
    Result of a triggered re-evaluation.
    
    This is the audit trail entry.
    """
    id: UUID = field(default_factory=uuid4)
    
    # Trigger
    trigger_event: TriggerEvent = None
    
    # What changed
    previous_state: Dict[str, Any] = field(default_factory=dict)
    new_state: Dict[str, Any] = field(default_factory=dict)
    
    # Changes detected
    changes: List[str] = field(default_factory=list)
    
    # Actions taken
    actions_taken: List[EventAction] = field(default_factory=list)
    
    # Timing
    evaluated_at: datetime = field(default_factory=datetime.utcnow)
    evaluation_duration_ms: int = 0
    
    def to_audit_record(self) -> Dict[str, Any]:
        """Convert to full audit record."""
        return {
            "evaluation_id": str(self.id),
            "trigger": self.trigger_event.to_audit_record() if self.trigger_event else None,
            "changes": self.changes,
            "actions_taken": [a.value for a in self.actions_taken],
            "evaluated_at": self.evaluated_at.isoformat(),
            "duration_ms": self.evaluation_duration_ms,
        }


# =============================================================================
# DEFAULT RULES
# =============================================================================

class DefaultEventRules:
    """Default event rules for common scenarios."""
    
    @staticmethod
    def booking_spike() -> EventRule:
        """Detect booking spike (>50% above normal in 24h)."""
        return EventRule(
            name="Booking Spike Detection",
            event_type=EventType.BOOKING_SPIKE,
            metric="bookings_24h",
            operator="change_pct",
            threshold=0.50,  # 50% increase
            severity=EventSeverity.MEDIUM,
            actions=[EventAction.RE_EVALUATE, EventAction.LOG_ONLY],
        )
    
    @staticmethod
    def cancellation_cluster() -> EventRule:
        """Detect cancellation cluster (3+ in 24h)."""
        return EventRule(
            name="Cancellation Cluster Detection",
            event_type=EventType.CANCELLATION_CLUSTER,
            metric="cancellations_24h",
            operator="gt",
            threshold=3,
            severity=EventSeverity.HIGH,
            actions=[EventAction.RE_EVALUATE, EventAction.ALERT_OPERATOR],
        )
    
    @staticmethod
    def competitor_rate_change() -> EventRule:
        """Detect significant competitor rate change (>15%)."""
        return EventRule(
            name="Competitor Rate Movement",
            event_type=EventType.COMPETITOR_RATE_CHANGE,
            metric="competitor_rate_change_pct",
            operator="change_pct",
            threshold=0.15,
            severity=EventSeverity.MEDIUM,
            actions=[EventAction.RE_EVALUATE],
        )
    
    @staticmethod
    def signal_confidence_drop() -> EventRule:
        """Detect signal confidence drop (below 0.5)."""
        return EventRule(
            name="Signal Confidence Alert",
            event_type=EventType.SIGNAL_CONFIDENCE_DROP,
            metric="signal_confidence",
            operator="lt",
            threshold=0.5,
            severity=EventSeverity.HIGH,
            actions=[EventAction.ALERT_OPERATOR, EventAction.PAUSE_AUTOMATION],
        )
    
    @staticmethod
    def signal_stale() -> EventRule:
        """Detect stale signals (freshness < 0.3)."""
        return EventRule(
            name="Stale Signal Detection",
            event_type=EventType.SIGNAL_STALE,
            metric="signal_freshness",
            operator="lt",
            threshold=0.3,
            severity=EventSeverity.MEDIUM,
            actions=[EventAction.LOG_ONLY],
        )


# =============================================================================
# EVENT SERVICE
# =============================================================================

class EventTriggerService:
    """
    Event Trigger Service.
    
    Manages event detection, logging, and re-evaluation triggers.
    
    This is infrastructure for:
    - Audit trails
    - "Why did X change?" answers
    - Future automation
    """
    
    def __init__(self):
        self.version = "1.0.0"
        self._rules: List[EventRule] = []
        self._event_log: List[TriggerEvent] = []
        self._evaluation_log: List[EvaluationResult] = []
        self._handlers: Dict[EventType, List[Callable]] = {}
        
        # Load default rules
        self._load_default_rules()
    
    def _load_default_rules(self):
        """Load default event rules."""
        self._rules = [
            DefaultEventRules.booking_spike(),
            DefaultEventRules.cancellation_cluster(),
            DefaultEventRules.competitor_rate_change(),
            DefaultEventRules.signal_confidence_drop(),
            DefaultEventRules.signal_stale(),
        ]
    
    def register_rule(self, rule: EventRule) -> None:
        """Register a custom rule."""
        self._rules.append(rule)
    
    def register_handler(
        self,
        event_type: EventType,
        handler: Callable[[TriggerEvent], None],
    ) -> None:
        """Register an event handler."""
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)
    
    def check_events(
        self,
        metrics: Dict[str, float],
        previous_metrics: Optional[Dict[str, float]] = None,
        geo_id: Optional[str] = None,
        property_id: Optional[UUID] = None,
        tenant_id: Optional[UUID] = None,
    ) -> List[TriggerEvent]:
        """
        Check all rules against current metrics.
        
        Returns list of triggered events.
        """
        triggered_events = []
        
        for rule in self._rules:
            if rule.metric not in metrics:
                continue
            
            current = metrics[rule.metric]
            previous = previous_metrics.get(rule.metric) if previous_metrics else None
            
            event = rule.evaluate(current, previous)
            
            if event:
                event.geo_id = geo_id
                event.property_id = property_id
                event.tenant_id = tenant_id
                triggered_events.append(event)
                
                # Log event
                self._event_log.append(event)
                logger.info(f"Event triggered: {event.event_type.value} - {event.description}")
        
        return triggered_events
    
    def process_event(
        self,
        event: TriggerEvent,
        re_evaluation_fn: Optional[Callable] = None,
    ) -> EvaluationResult:
        """
        Process a triggered event.
        
        Args:
            event: The triggered event
            re_evaluation_fn: Optional function to call for re-evaluation
        
        Returns:
            EvaluationResult with actions taken
        """
        import time
        start = time.time()
        
        actions_taken = []
        changes = []
        previous_state = {}
        new_state = {}
        
        # Determine actions based on event severity and rules
        if EventAction.LOG_ONLY in event.actions_taken or event.severity == EventSeverity.LOW:
            actions_taken.append(EventAction.LOG_ONLY)
        
        if event.severity in [EventSeverity.MEDIUM, EventSeverity.HIGH, EventSeverity.CRITICAL]:
            # Re-evaluate if function provided
            if re_evaluation_fn:
                try:
                    result = re_evaluation_fn(event)
                    actions_taken.append(EventAction.RE_EVALUATE)
                    if isinstance(result, dict):
                        new_state = result
                        changes.append(f"Re-evaluation completed")
                except Exception as e:
                    logger.error(f"Re-evaluation failed: {e}")
        
        if event.severity in [EventSeverity.HIGH, EventSeverity.CRITICAL]:
            actions_taken.append(EventAction.ALERT_OPERATOR)
            changes.append("Operator alert sent")
        
        if event.severity == EventSeverity.CRITICAL:
            actions_taken.append(EventAction.PAUSE_AUTOMATION)
            changes.append("Automation paused pending review")
        
        # Mark event as processed
        event.processed = True
        event.processed_at = datetime.utcnow()
        event.actions_taken = actions_taken
        
        # Call registered handlers
        if event.event_type in self._handlers:
            for handler in self._handlers[event.event_type]:
                try:
                    handler(event)
                except Exception as e:
                    logger.error(f"Handler failed: {e}")
        
        # Create evaluation result
        duration_ms = int((time.time() - start) * 1000)
        
        result = EvaluationResult(
            trigger_event=event,
            previous_state=previous_state,
            new_state=new_state,
            changes=changes,
            actions_taken=actions_taken,
            evaluation_duration_ms=duration_ms,
        )
        
        self._evaluation_log.append(result)
        
        return result
    
    def get_event_log(
        self,
        limit: int = 100,
        event_types: Optional[List[EventType]] = None,
        since: Optional[datetime] = None,
    ) -> List[TriggerEvent]:
        """Get event log with optional filters."""
        events = self._event_log
        
        if event_types:
            events = [e for e in events if e.event_type in event_types]
        
        if since:
            events = [e for e in events if e.detected_at >= since]
        
        return events[-limit:]
    
    def get_audit_trail(
        self,
        geo_id: Optional[str] = None,
        property_id: Optional[UUID] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Get audit trail for a geo/property.
        
        This answers "Why did pricing change?"
        """
        evaluations = self._evaluation_log
        
        if geo_id:
            evaluations = [
                e for e in evaluations
                if e.trigger_event and e.trigger_event.geo_id == geo_id
            ]
        
        if property_id:
            evaluations = [
                e for e in evaluations
                if e.trigger_event and e.trigger_event.property_id == property_id
            ]
        
        return [e.to_audit_record() for e in evaluations[-limit:]]
    
    def emit_event(
        self,
        event_type: EventType,
        description: str,
        severity: EventSeverity = EventSeverity.MEDIUM,
        geo_id: Optional[str] = None,
        property_id: Optional[UUID] = None,
        tenant_id: Optional[UUID] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> TriggerEvent:
        """
        Manually emit an event.
        
        Useful for external triggers (weather API, event calendar, etc.)
        """
        event = TriggerEvent(
            event_type=event_type,
            severity=severity,
            geo_id=geo_id,
            property_id=property_id,
            tenant_id=tenant_id,
            description=description,
            data=data or {},
        )
        
        self._event_log.append(event)
        logger.info(f"Event emitted: {event_type.value} - {description}")
        
        return event


# =============================================================================
# SINGLETON & CONVENIENCE
# =============================================================================

_service: Optional[EventTriggerService] = None


def get_event_service() -> EventTriggerService:
    """Get event trigger service singleton."""
    global _service
    if _service is None:
        _service = EventTriggerService()
    return _service


def check_for_events(
    metrics: Dict[str, float],
    previous: Optional[Dict[str, float]] = None,
    **context,
) -> List[TriggerEvent]:
    """
    Check for triggered events.
    
    Example:
        events = check_for_events(
            {"bookings_24h": 15, "signal_confidence": 0.45},
            previous={"bookings_24h": 8},
            geo_id="30a-beaches"
        )
        
        for event in events:
            print(f"Triggered: {event.event_type.value}")
    """
    return get_event_service().check_events(metrics, previous, **context)


def emit_event(
    event_type: EventType,
    description: str,
    **kwargs,
) -> TriggerEvent:
    """Emit a manual event."""
    return get_event_service().emit_event(event_type, description, **kwargs)


def get_audit_trail(
    geo_id: Optional[str] = None,
    property_id: Optional[UUID] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """
    Get audit trail.
    
    Answers: "Why did pricing change for this property?"
    """
    return get_event_service().get_audit_trail(geo_id, property_id, limit)
