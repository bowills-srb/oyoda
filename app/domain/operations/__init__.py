"""
Domain: Operations - Pure Models.

Operational state and constraints for decision-making.
No FastAPI. No DB sessions. No external API calls.

This layer represents:
- OperationalState (calendar, turnover, staff capacity)
- Real-time constraints that prevent bad decisions
- Permission-based decision inputs
"""

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from enum import Enum
from typing import Dict, List, Optional
from uuid import UUID


# =============================================================================
# ENUMS
# =============================================================================

class StaffCapacity(str, Enum):
    """Current staff capacity level."""
    STRAINED = "strained"    # At or over capacity
    NORMAL = "normal"        # Standard operations
    FLEXIBLE = "flexible"    # Extra capacity available


class TurnoverStatus(str, Enum):
    """Turnover window status."""
    TIGHT = "tight"          # Minimal buffer
    NORMAL = "normal"        # Standard buffer
    FLEXIBLE = "flexible"    # Extended buffer available


class CleaningStatus(str, Enum):
    """Cleaning status for a property."""
    NOT_SCHEDULED = "not_scheduled"
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    VERIFIED = "verified"


class MaintenanceUrgency(str, Enum):
    """Urgency level for maintenance issues."""
    CRITICAL = "critical"      # Must fix before guest arrival
    HIGH = "high"              # Should fix soon
    MEDIUM = "medium"          # Can wait
    LOW = "low"                # Cosmetic/minor


# =============================================================================
# CALENDAR STATE
# =============================================================================

@dataclass
class Reservation:
    """A single reservation."""
    reservation_id: str
    property_id: UUID
    
    check_in: datetime
    check_out: datetime
    
    guest_name: Optional[str] = None
    guest_count: int = 1
    
    # Status
    is_confirmed: bool = True
    is_checked_in: bool = False
    is_checked_out: bool = False
    
    @property
    def nights(self) -> int:
        return (self.check_out.date() - self.check_in.date()).days
    
    @property
    def is_active(self) -> bool:
        """Check if reservation is currently active."""
        now = datetime.now(timezone.utc)
        return self.check_in <= now <= self.check_out


@dataclass
class BlockedPeriod:
    """A blocked period (owner use, maintenance, etc.)."""
    block_id: str
    property_id: UUID
    
    start_date: date
    end_date: date
    
    reason: str = "owner_block"  # owner_block, maintenance, other
    notes: Optional[str] = None


@dataclass
class CalendarState:
    """
    Current calendar state for a property.
    
    Used by decision engine for availability checks.
    """
    property_id: UUID
    
    # Reservations
    reservations: List[Reservation] = field(default_factory=list)
    blocked_periods: List[BlockedPeriod] = field(default_factory=list)
    
    # Current state
    current_reservation: Optional[Reservation] = None
    next_reservation: Optional[Reservation] = None
    
    # Derived
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    def get_reservation_for_date(self, target: date) -> Optional[Reservation]:
        """Get reservation that includes this date."""
        for res in self.reservations:
            if res.check_in.date() <= target < res.check_out.date():
                return res
        return None
    
    def is_available(self, start: date, end: date) -> bool:
        """Check if date range is available."""
        for res in self.reservations:
            # Check overlap
            if not (end <= res.check_in.date() or start >= res.check_out.date()):
                return False
        for block in self.blocked_periods:
            if not (end <= block.start_date or start >= block.end_date):
                return False
        return True
    
    def get_next_checkin(self) -> Optional[datetime]:
        """Get next check-in datetime."""
        if self.next_reservation:
            return self.next_reservation.check_in
        return None
    
    def hours_until_next_checkin(self) -> Optional[float]:
        """Hours until next guest arrives."""
        next_checkin = self.get_next_checkin()
        if not next_checkin:
            return None
        delta = next_checkin - datetime.now(timezone.utc)
        return delta.total_seconds() / 3600


# =============================================================================
# KNOWN ISSUES
# =============================================================================

@dataclass
class KnownIssue:
    """A known issue at a property."""
    issue_id: str
    property_id: UUID
    
    # Description
    title: str
    description: str
    
    # Classification
    urgency: MaintenanceUrgency = MaintenanceUrgency.MEDIUM
    category: str = "maintenance"  # maintenance, cleanliness, amenity, safety
    
    # Status
    is_resolved: bool = False
    is_guest_impacting: bool = False
    
    # Timing
    reported_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_at: Optional[datetime] = None
    
    # Response
    guest_communication: Optional[str] = None  # Pre-approved message for guests


# =============================================================================
# OPERATIONAL STATE (MASTER)
# =============================================================================

@dataclass
class TurnoverWindow:
    """Turnover window between reservations."""
    previous_checkout: datetime
    next_checkin: datetime
    
    @property
    def buffer_hours(self) -> float:
        """Hours between checkout and checkin."""
        delta = self.next_checkin - self.previous_checkout
        return delta.total_seconds() / 3600
    
    @property
    def status(self) -> TurnoverStatus:
        """Get turnover status based on buffer."""
        if self.buffer_hours < 4:
            return TurnoverStatus.TIGHT
        elif self.buffer_hours < 6:
            return TurnoverStatus.NORMAL
        else:
            return TurnoverStatus.FLEXIBLE


@dataclass
class OperationalState:
    """
    Real-time operational state for a property.
    
    This is what prevents bad decisions.
    
    Used by:
    - Late checkout decision logic
    - Early check-in decision logic
    - Escalation triggers
    - Concierge responses about availability
    """
    property_id: UUID
    
    # === CALENDAR ===
    calendar: CalendarState = None
    
    # === TURNOVER ===
    turnover_status: TurnoverStatus = TurnoverStatus.NORMAL
    turnover_buffer_hours: float = 5.0
    
    # === CLEANING ===
    cleaning_status: CleaningStatus = CleaningStatus.NOT_SCHEDULED
    cleaning_scheduled_at: Optional[datetime] = None
    cleaning_completed_at: Optional[datetime] = None
    
    # === STAFF ===
    staff_capacity: StaffCapacity = StaffCapacity.NORMAL
    
    # === KNOWN ISSUES ===
    known_issues: List[KnownIssue] = field(default_factory=list)
    
    # === NEXT EVENTS ===
    next_checkin: Optional[datetime] = None
    next_checkout: Optional[datetime] = None
    
    # === METADATA ===
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    def __post_init__(self):
        if self.calendar is None:
            self.calendar = CalendarState(property_id=self.property_id)
    
    # === CONVENIENCE METHODS ===
    
    @property
    def hours_until_next_checkin(self) -> Optional[float]:
        """Hours until next guest arrives."""
        if not self.next_checkin:
            return None
        delta = self.next_checkin - datetime.now(timezone.utc)
        return delta.total_seconds() / 3600
    
    @property
    def has_critical_issues(self) -> bool:
        """Check for unresolved critical issues."""
        return any(
            issue for issue in self.known_issues
            if not issue.is_resolved and issue.urgency == MaintenanceUrgency.CRITICAL
        )
    
    @property
    def has_guest_impacting_issues(self) -> bool:
        """Check for issues that impact guest experience."""
        return any(
            issue for issue in self.known_issues
            if not issue.is_resolved and issue.is_guest_impacting
        )
    
    @property
    def active_issues(self) -> List[KnownIssue]:
        """Get unresolved issues."""
        return [i for i in self.known_issues if not i.is_resolved]
    
    @property
    def is_ready_for_guest(self) -> bool:
        """Check if property is ready for next guest."""
        return (
            self.cleaning_status in [CleaningStatus.COMPLETED, CleaningStatus.VERIFIED] and
            not self.has_critical_issues
        )


# =============================================================================
# OPERATIONAL CONSTRAINTS (for PropertyProfile)
# =============================================================================

@dataclass
class OperationalConstraints:
    """
    Operational constraints for a property.
    
    This is embedded in PropertyProfile.
    """
    # Standard times
    check_in_time: time = field(default_factory=lambda: time(16, 0))   # 4:00 PM
    check_out_time: time = field(default_factory=lambda: time(11, 0))  # 11:00 AM
    
    # Flexibility
    early_checkin_available: bool = False
    early_checkin_earliest: Optional[time] = None
    early_checkin_fee: float = 0.0
    
    late_checkout_available: bool = True
    late_checkout_latest: Optional[time] = field(default_factory=lambda: time(14, 0))  # 2:00 PM
    late_checkout_fee: float = 0.0
    
    # Turnover
    minimum_turnover_hours: float = 4.0
    preferred_turnover_hours: float = 5.0
    
    @property
    def check_in_str(self) -> str:
        return self.check_in_time.strftime("%I:%M %p").lstrip("0")
    
    @property
    def check_out_str(self) -> str:
        return self.check_out_time.strftime("%I:%M %p").lstrip("0")


# =============================================================================
# DECISION SUPPORT FUNCTIONS
# =============================================================================

def can_approve_late_checkout(
    state: OperationalState,
    requested_time: time,
    constraints: OperationalConstraints,
) -> tuple[bool, str]:
    """
    Evaluate if late checkout can be approved.
    
    Pure function - no IO.
    
    Returns:
        Tuple of (can_approve, reason)
    """
    # Check if late checkout is available at all
    if not constraints.late_checkout_available:
        return False, "Late checkout is not available for this property"
    
    # Check if requested time is within limits
    if constraints.late_checkout_latest and requested_time > constraints.late_checkout_latest:
        return False, f"Maximum late checkout is {constraints.late_checkout_latest.strftime('%I:%M %p')}"
    
    # Check turnover buffer
    if state.hours_until_next_checkin is not None:
        # Calculate new buffer with late checkout
        checkout_datetime = datetime.combine(date.today(), requested_time)
        regular_checkout = datetime.combine(date.today(), constraints.check_out_time)
        additional_hours = (checkout_datetime - regular_checkout).total_seconds() / 3600
        
        remaining_buffer = state.hours_until_next_checkin - additional_hours
        
        if remaining_buffer < constraints.minimum_turnover_hours:
            return False, "Insufficient turnover time before next guest"
    
    # Check staff capacity
    if state.staff_capacity == StaffCapacity.STRAINED:
        return False, "Staff capacity is currently limited"
    
    # All checks passed
    return True, "Approved"


def can_approve_early_checkin(
    state: OperationalState,
    requested_time: time,
    constraints: OperationalConstraints,
) -> tuple[bool, str]:
    """
    Evaluate if early check-in can be approved.
    
    Pure function - no IO.
    
    Returns:
        Tuple of (can_approve, reason)
    """
    # Check if early checkin is available
    if not constraints.early_checkin_available:
        return False, "Early check-in is not available for this property"
    
    # Check if requested time is within limits
    if constraints.early_checkin_earliest and requested_time < constraints.early_checkin_earliest:
        return False, f"Earliest check-in is {constraints.early_checkin_earliest.strftime('%I:%M %p')}"
    
    # Check if property is ready
    if not state.is_ready_for_guest:
        if state.cleaning_status == CleaningStatus.IN_PROGRESS:
            return False, "Cleaning is still in progress"
        elif state.cleaning_status in [CleaningStatus.NOT_SCHEDULED, CleaningStatus.SCHEDULED]:
            return False, "Property is not yet ready"
        elif state.has_critical_issues:
            return False, "Property has maintenance issues being addressed"
    
    # Check staff capacity
    if state.staff_capacity == StaffCapacity.STRAINED:
        return False, "Staff capacity is currently limited"
    
    return True, "Approved"


def should_escalate_to_manager(
    state: OperationalState,
    request_type: str,
) -> tuple[bool, str]:
    """
    Determine if a request should be escalated.
    
    Pure function - no IO.
    
    Returns:
        Tuple of (should_escalate, reason)
    """
    # Always escalate critical issues
    if state.has_critical_issues:
        return True, "Property has critical unresolved issues"
    
    # Escalate if staff is strained
    if state.staff_capacity == StaffCapacity.STRAINED:
        return True, "Staff capacity is limited - manager approval needed"
    
    # Escalate tight turnovers
    if state.turnover_status == TurnoverStatus.TIGHT:
        return True, "Tight turnover window - manager approval needed"
    
    return False, "No escalation needed"


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Enums
    "StaffCapacity",
    "TurnoverStatus",
    "CleaningStatus",
    "MaintenanceUrgency",
    
    # Calendar
    "Reservation",
    "BlockedPeriod",
    "CalendarState",
    
    # Issues
    "KnownIssue",
    
    # Turnover
    "TurnoverWindow",
    
    # Operational state (MASTER)
    "OperationalState",
    
    # Constraints
    "OperationalConstraints",
    
    # Decision functions
    "can_approve_late_checkout",
    "can_approve_early_checkin",
    "should_escalate_to_manager",
]
