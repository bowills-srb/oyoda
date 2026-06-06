"""
Detector Engine - Event-driven analytics triggers.

Detectors monitor data changes and trigger appropriate actions,
enabling real-time response to market conditions, new listings,
and operational events.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Type
from uuid import UUID, uuid4
import asyncio
import logging

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class DetectorEventType(str, Enum):
    """Types of events that detectors can emit."""
    NEW_LISTING = "new_listing"
    LISTING_UPDATE = "listing_update"
    PRICE_CHANGE = "price_change"
    OCCUPANCY_SHIFT = "occupancy_shift"
    BOOKING_MADE = "booking_made"
    BOOKING_CANCELLED = "booking_cancelled"
    MARKET_ANOMALY = "market_anomaly"
    COMPETITOR_CHANGE = "competitor_change"
    DEMAND_SURGE = "demand_surge"
    DEMAND_DROP = "demand_drop"
    GAP_DETECTED = "gap_detected"
    OWNER_BLOCK = "owner_block"
    PERFORMANCE_THRESHOLD = "performance_threshold"
    
    # Guest Messaging Events
    GUEST_MESSAGE_RECEIVED = "guest_message_received"
    GUEST_COMPLAINT = "guest_complaint"
    GUEST_DISCOUNT_REQUEST = "guest_discount_request"
    GUEST_LATE_CHECKOUT_REQUEST = "guest_late_checkout_request"
    GUEST_EARLY_CHECKIN_REQUEST = "guest_early_checkin_request"
    GUEST_MAINTENANCE_REQUEST = "guest_maintenance_request"
    GUEST_URGENT_ISSUE = "guest_urgent_issue"
    GUEST_POSITIVE_FEEDBACK = "guest_positive_feedback"


class DetectorPriority(int, Enum):
    """Priority levels for detector processing."""
    CRITICAL = 1  # Process immediately
    HIGH = 2      # Process within minutes
    NORMAL = 3    # Process within hour
    LOW = 4       # Process when convenient


@dataclass
class DetectorEvent:
    """
    An event emitted by a detector.
    
    Contains all context needed for downstream processing.
    """
    id: UUID = field(default_factory=uuid4)
    event_type: DetectorEventType = DetectorEventType.NEW_LISTING
    priority: DetectorPriority = DetectorPriority.NORMAL
    
    # Context
    company_id: UUID = None
    property_id: Optional[UUID] = None
    market_id: Optional[UUID] = None
    
    # Event data
    payload: Dict[str, Any] = field(default_factory=dict)
    
    # Metadata
    detected_at: datetime = field(default_factory=datetime.utcnow)
    detector_name: str = ""
    confidence: float = 1.0  # 0.0 to 1.0
    
    # Tracking
    processed: bool = False
    processed_at: Optional[datetime] = None
    actions_triggered: List[str] = field(default_factory=list)


class DetectorCondition(BaseModel):
    """A condition that must be met for a detector to fire."""
    field: str
    operator: str  # eq, ne, gt, gte, lt, lte, in, not_in, contains, regex
    value: Any
    
    def evaluate(self, data: Dict[str, Any]) -> bool:
        """Evaluate this condition against provided data."""
        actual_value = data.get(self.field)
        
        if actual_value is None:
            return False
        
        if self.operator == "eq":
            return actual_value == self.value
        elif self.operator == "ne":
            return actual_value != self.value
        elif self.operator == "gt":
            return actual_value > self.value
        elif self.operator == "gte":
            return actual_value >= self.value
        elif self.operator == "lt":
            return actual_value < self.value
        elif self.operator == "lte":
            return actual_value <= self.value
        elif self.operator == "in":
            return actual_value in self.value
        elif self.operator == "not_in":
            return actual_value not in self.value
        elif self.operator == "contains":
            return self.value in actual_value
        elif self.operator == "regex":
            import re
            return bool(re.match(self.value, str(actual_value)))
        
        return False


class BaseDetector(ABC):
    """
    Abstract base class for all detectors.
    
    Detectors monitor specific data sources or events and emit
    DetectorEvents when conditions are met.
    """
    
    name: str = "base_detector"
    description: str = "Base detector class"
    event_types: List[DetectorEventType] = []
    default_priority: DetectorPriority = DetectorPriority.NORMAL
    
    def __init__(
        self,
        company_id: UUID,
        conditions: List[DetectorCondition] = None,
        actions: List[str] = None,
        enabled: bool = True
    ):
        self.company_id = company_id
        self.conditions = conditions or []
        self.actions = actions or []
        self.enabled = enabled
        self._event_handlers: List[Callable] = []
    
    def add_event_handler(self, handler: Callable[[DetectorEvent], None]):
        """Register a handler to be called when events are detected."""
        self._event_handlers.append(handler)
    
    async def emit_event(self, event: DetectorEvent):
        """Emit an event to all registered handlers."""
        event.detector_name = self.name
        event.company_id = self.company_id
        
        logger.info(
            f"Detector '{self.name}' emitting event: {event.event_type.value}",
            extra={"event_id": str(event.id), "company_id": str(self.company_id)}
        )
        
        for handler in self._event_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(event)
                else:
                    handler(event)
            except Exception as e:
                logger.error(f"Error in event handler: {e}")
    
    def check_conditions(self, data: Dict[str, Any]) -> bool:
        """Check if all conditions are met."""
        if not self.conditions:
            return True
        return all(condition.evaluate(data) for condition in self.conditions)
    
    @abstractmethod
    async def detect(self, data: Dict[str, Any]) -> Optional[DetectorEvent]:
        """
        Main detection logic. Override in subclasses.
        
        Args:
            data: Input data to analyze
            
        Returns:
            DetectorEvent if detection criteria met, None otherwise
        """
        pass


class NewListingDetector(BaseDetector):
    """
    Detects new property listings within a company's market area.
    
    Triggers when:
    - MLS feed contains new listing
    - Manual property entry
    - PMS sync adds new property
    """
    
    name = "new_listing_detector"
    description = "Detects new property listings for business development"
    event_types = [DetectorEventType.NEW_LISTING]
    default_priority = DetectorPriority.HIGH
    
    def __init__(
        self,
        company_id: UUID,
        geofence_ids: List[UUID] = None,
        min_bedrooms: int = None,
        max_bedrooms: int = None,
        property_types: List[str] = None,
        **kwargs
    ):
        super().__init__(company_id, **kwargs)
        self.geofence_ids = geofence_ids or []
        self.min_bedrooms = min_bedrooms
        self.max_bedrooms = max_bedrooms
        self.property_types = property_types or []
    
    async def detect(self, data: Dict[str, Any]) -> Optional[DetectorEvent]:
        """Detect if incoming data represents a new listing of interest."""
        if not self.enabled:
            return None
        
        # Check if it's a new listing (not an update)
        if data.get("is_update", False):
            return None
        
        # Check bedroom range
        bedrooms = data.get("bedrooms")
        if bedrooms:
            if self.min_bedrooms and bedrooms < self.min_bedrooms:
                return None
            if self.max_bedrooms and bedrooms > self.max_bedrooms:
                return None
        
        # Check property type
        prop_type = data.get("property_type")
        if self.property_types and prop_type not in self.property_types:
            return None
        
        # Check geofence (would integrate with GeofencingEngine)
        # For now, assume geofence check is in data
        if self.geofence_ids and not data.get("within_geofence", True):
            return None
        
        # Check custom conditions
        if not self.check_conditions(data):
            return None
        
        # Create and emit event
        event = DetectorEvent(
            event_type=DetectorEventType.NEW_LISTING,
            priority=self.default_priority,
            property_id=data.get("property_id"),
            market_id=data.get("market_id"),
            payload={
                "address": data.get("address"),
                "bedrooms": bedrooms,
                "bathrooms": data.get("bathrooms"),
                "property_type": prop_type,
                "listed_price": data.get("listed_price"),
                "source": data.get("source", "unknown"),
                "listing_url": data.get("listing_url"),
            },
            confidence=data.get("confidence", 1.0)
        )
        
        await self.emit_event(event)
        return event


class PriceChangeDetector(BaseDetector):
    """
    Detects significant price changes in the market.
    
    Triggers when:
    - Competitor rates change significantly
    - Market benchmark rates shift
    - Own property rates are out of alignment
    """
    
    name = "price_change_detector"
    description = "Detects significant price changes requiring attention"
    event_types = [DetectorEventType.PRICE_CHANGE]
    default_priority = DetectorPriority.NORMAL
    
    def __init__(
        self,
        company_id: UUID,
        change_threshold_pct: float = 0.10,  # 10% change triggers
        **kwargs
    ):
        super().__init__(company_id, **kwargs)
        self.change_threshold_pct = change_threshold_pct
    
    async def detect(self, data: Dict[str, Any]) -> Optional[DetectorEvent]:
        """Detect if a price change exceeds threshold."""
        if not self.enabled:
            return None
        
        old_price = data.get("old_price", 0)
        new_price = data.get("new_price", 0)
        
        if old_price == 0:
            return None
        
        change_pct = abs(new_price - old_price) / old_price
        
        if change_pct < self.change_threshold_pct:
            return None
        
        if not self.check_conditions(data):
            return None
        
        direction = "increase" if new_price > old_price else "decrease"
        
        event = DetectorEvent(
            event_type=DetectorEventType.PRICE_CHANGE,
            priority=DetectorPriority.HIGH if change_pct > 0.20 else self.default_priority,
            property_id=data.get("property_id"),
            market_id=data.get("market_id"),
            payload={
                "old_price": old_price,
                "new_price": new_price,
                "change_pct": change_pct,
                "direction": direction,
                "source": data.get("source", "unknown"),
                "competitor_id": data.get("competitor_id"),
            }
        )
        
        await self.emit_event(event)
        return event


class OccupancyShiftDetector(BaseDetector):
    """
    Detects significant changes in occupancy patterns.
    
    Triggers when:
    - Booking is made
    - Cancellation occurs
    - Gap in calendar detected
    - Occupancy rate shifts significantly
    """
    
    name = "occupancy_shift_detector"
    description = "Detects occupancy changes requiring pricing action"
    event_types = [
        DetectorEventType.OCCUPANCY_SHIFT,
        DetectorEventType.BOOKING_MADE,
        DetectorEventType.BOOKING_CANCELLED,
        DetectorEventType.GAP_DETECTED
    ]
    default_priority = DetectorPriority.NORMAL
    
    def __init__(
        self,
        company_id: UUID,
        gap_threshold_days: int = 3,  # Gaps of 3 days or less trigger
        occupancy_change_threshold: float = 0.15,  # 15% shift triggers
        **kwargs
    ):
        super().__init__(company_id, **kwargs)
        self.gap_threshold_days = gap_threshold_days
        self.occupancy_change_threshold = occupancy_change_threshold
    
    async def detect(self, data: Dict[str, Any]) -> Optional[DetectorEvent]:
        """Detect occupancy-related events."""
        if not self.enabled:
            return None
        
        event_subtype = data.get("subtype")
        
        if event_subtype == "booking":
            return await self._detect_booking(data)
        elif event_subtype == "cancellation":
            return await self._detect_cancellation(data)
        elif event_subtype == "gap":
            return await self._detect_gap(data)
        elif event_subtype == "occupancy_change":
            return await self._detect_occupancy_change(data)
        
        return None
    
    async def _detect_booking(self, data: Dict[str, Any]) -> DetectorEvent:
        """Handle new booking detection."""
        event = DetectorEvent(
            event_type=DetectorEventType.BOOKING_MADE,
            priority=DetectorPriority.NORMAL,
            property_id=data.get("property_id"),
            payload={
                "check_in": data.get("check_in"),
                "check_out": data.get("check_out"),
                "nights": data.get("nights"),
                "revenue": data.get("revenue"),
                "booking_window": data.get("booking_window"),  # Days in advance
                "source": data.get("source"),
            }
        )
        await self.emit_event(event)
        return event
    
    async def _detect_cancellation(self, data: Dict[str, Any]) -> DetectorEvent:
        """Handle cancellation detection."""
        event = DetectorEvent(
            event_type=DetectorEventType.BOOKING_CANCELLED,
            priority=DetectorPriority.HIGH,  # Cancellations need quick attention
            property_id=data.get("property_id"),
            payload={
                "check_in": data.get("check_in"),
                "check_out": data.get("check_out"),
                "nights": data.get("nights"),
                "lost_revenue": data.get("lost_revenue"),
                "days_until_checkin": data.get("days_until_checkin"),
            }
        )
        await self.emit_event(event)
        return event
    
    async def _detect_gap(self, data: Dict[str, Any]) -> Optional[DetectorEvent]:
        """Handle gap detection."""
        gap_days = data.get("gap_days", 0)
        
        if gap_days > self.gap_threshold_days:
            return None  # Gap too large, not a typical gap-fill scenario
        
        event = DetectorEvent(
            event_type=DetectorEventType.GAP_DETECTED,
            priority=DetectorPriority.HIGH,
            property_id=data.get("property_id"),
            payload={
                "gap_start": data.get("gap_start"),
                "gap_end": data.get("gap_end"),
                "gap_days": gap_days,
                "surrounding_bookings": data.get("surrounding_bookings"),
            }
        )
        await self.emit_event(event)
        return event
    
    async def _detect_occupancy_change(self, data: Dict[str, Any]) -> Optional[DetectorEvent]:
        """Handle significant occupancy rate change."""
        old_rate = data.get("old_occupancy", 0)
        new_rate = data.get("new_occupancy", 0)
        
        change = abs(new_rate - old_rate)
        
        if change < self.occupancy_change_threshold:
            return None
        
        event = DetectorEvent(
            event_type=DetectorEventType.OCCUPANCY_SHIFT,
            priority=DetectorPriority.NORMAL,
            property_id=data.get("property_id"),
            market_id=data.get("market_id"),
            payload={
                "old_occupancy": old_rate,
                "new_occupancy": new_rate,
                "change": change,
                "period": data.get("period"),
            }
        )
        await self.emit_event(event)
        return event


class MarketAnomalyDetector(BaseDetector):
    """
    Detects unusual patterns in market data.
    
    Triggers when:
    - Market metrics deviate significantly from historical norms
    - Unusual booking patterns emerge
    - Supply/demand imbalance detected
    """
    
    name = "market_anomaly_detector"
    description = "Detects unusual market patterns"
    event_types = [
        DetectorEventType.MARKET_ANOMALY,
        DetectorEventType.DEMAND_SURGE,
        DetectorEventType.DEMAND_DROP
    ]
    default_priority = DetectorPriority.NORMAL
    
    def __init__(
        self,
        company_id: UUID,
        std_deviation_threshold: float = 2.0,  # 2 standard deviations
        **kwargs
    ):
        super().__init__(company_id, **kwargs)
        self.std_deviation_threshold = std_deviation_threshold
    
    async def detect(self, data: Dict[str, Any]) -> Optional[DetectorEvent]:
        """Detect market anomalies."""
        if not self.enabled:
            return None
        
        metric_name = data.get("metric")
        current_value = data.get("current_value")
        historical_mean = data.get("historical_mean")
        historical_std = data.get("historical_std", 1)
        
        if historical_std == 0:
            return None
        
        z_score = abs(current_value - historical_mean) / historical_std
        
        if z_score < self.std_deviation_threshold:
            return None
        
        # Determine event type based on direction
        if current_value > historical_mean:
            event_type = DetectorEventType.DEMAND_SURGE if "demand" in metric_name.lower() else DetectorEventType.MARKET_ANOMALY
        else:
            event_type = DetectorEventType.DEMAND_DROP if "demand" in metric_name.lower() else DetectorEventType.MARKET_ANOMALY
        
        event = DetectorEvent(
            event_type=event_type,
            priority=DetectorPriority.HIGH if z_score > 3.0 else self.default_priority,
            market_id=data.get("market_id"),
            payload={
                "metric": metric_name,
                "current_value": current_value,
                "historical_mean": historical_mean,
                "historical_std": historical_std,
                "z_score": z_score,
                "period": data.get("period"),
            },
            confidence=min(z_score / 5.0, 1.0)  # Higher z-score = higher confidence
        )
        
        await self.emit_event(event)
        return event


class DetectorRegistry:
    """
    Registry and manager for all detectors.
    
    Handles detector registration, configuration, and event routing.
    """
    
    _detector_classes: Dict[str, Type[BaseDetector]] = {
        "new_listing": NewListingDetector,
        "price_change": PriceChangeDetector,
        "occupancy_shift": OccupancyShiftDetector,
        "market_anomaly": MarketAnomalyDetector,
    }
    
    def __init__(self):
        self._active_detectors: Dict[str, BaseDetector] = {}
        self._global_handlers: List[Callable] = []
    
    @classmethod
    def register_detector_class(cls, name: str, detector_class: Type[BaseDetector]):
        """Register a new detector class."""
        cls._detector_classes[name] = detector_class
    
    def create_detector(
        self,
        detector_type: str,
        company_id: UUID,
        detector_id: str = None,
        **config
    ) -> BaseDetector:
        """Create and register a detector instance."""
        if detector_type not in self._detector_classes:
            raise ValueError(f"Unknown detector type: {detector_type}")
        
        detector_class = self._detector_classes[detector_type]
        detector = detector_class(company_id=company_id, **config)
        
        # Register global handlers
        for handler in self._global_handlers:
            detector.add_event_handler(handler)
        
        # Store in registry
        detector_id = detector_id or f"{detector_type}_{company_id}_{uuid4().hex[:8]}"
        self._active_detectors[detector_id] = detector
        
        return detector
    
    def add_global_handler(self, handler: Callable[[DetectorEvent], None]):
        """Add a handler that receives events from all detectors."""
        self._global_handlers.append(handler)
        
        # Add to existing detectors
        for detector in self._active_detectors.values():
            detector.add_event_handler(handler)
    
    def get_detector(self, detector_id: str) -> Optional[BaseDetector]:
        """Get a detector by ID."""
        return self._active_detectors.get(detector_id)
    
    def disable_detector(self, detector_id: str):
        """Disable a detector."""
        detector = self._active_detectors.get(detector_id)
        if detector:
            detector.enabled = False
    
    def enable_detector(self, detector_id: str):
        """Enable a detector."""
        detector = self._active_detectors.get(detector_id)
        if detector:
            detector.enabled = True
    
    async def process_data(self, detector_id: str, data: Dict[str, Any]) -> Optional[DetectorEvent]:
        """Send data to a specific detector for processing."""
        detector = self._active_detectors.get(detector_id)
        if not detector:
            raise ValueError(f"Detector not found: {detector_id}")
        
        return await detector.detect(data)
    
    async def broadcast_data(
        self,
        data: Dict[str, Any],
        company_id: UUID = None,
        detector_types: List[str] = None
    ) -> List[DetectorEvent]:
        """Broadcast data to multiple detectors."""
        events = []
        
        for detector_id, detector in self._active_detectors.items():
            # Filter by company if specified
            if company_id and detector.company_id != company_id:
                continue
            
            # Filter by type if specified
            if detector_types and detector.name not in detector_types:
                continue
            
            try:
                event = await detector.detect(data)
                if event:
                    events.append(event)
            except Exception as e:
                logger.error(f"Error in detector {detector_id}: {e}")
        
        return events


# Global registry instance
detector_registry = DetectorRegistry()
