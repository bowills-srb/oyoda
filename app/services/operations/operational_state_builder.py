"""
Operational State Builder.

Hydrates OperationalState from calendar sources:
- PMS integrations
- Calendar exports
- Manual entries

This is REQUIRED for safe concierge decisions.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.domain.operations import (
    OperationalState,
    CalendarState,
    Reservation,
    BlockedPeriod,
    StaffCapacity,
    TurnoverStatus,
    CleaningStatus,
)


# =============================================================================
# CALENDAR SOURCES
# =============================================================================

@dataclass
class RawReservation:
    """Raw reservation data from PMS/calendar."""
    reservation_id: str
    guest_name: Optional[str]
    check_in: datetime
    check_out: datetime
    source: str = "unknown"  # airbnb, vrbo, direct, etc.
    status: str = "confirmed"  # confirmed, pending, cancelled
    guest_count: Optional[int] = None


@dataclass
class RawBlock:
    """Raw blocked period from calendar."""
    start: datetime
    end: datetime
    reason: str = "owner_block"


# =============================================================================
# OPERATIONAL STATE BUILDER
# =============================================================================

class OperationalStateBuilder:
    """
    Builds OperationalState from calendar data.
    
    Usage:
        builder = OperationalStateBuilder(property_id)
        
        # Add reservations
        builder.add_reservation(res1)
        builder.add_reservation(res2)
        
        # Set capacity
        builder.set_staff_capacity(StaffCapacity.NORMAL)
        
        # Build
        state = builder.build()
    """
    
    def __init__(self, property_id: UUID):
        self.property_id = property_id
        
        self._reservations: List[Reservation] = []
        self._blocks: List[BlockedPeriod] = []
        self._staff_capacity = StaffCapacity.NORMAL
        self._turnover_hours = 5.0
        self._known_issues: List[str] = []
        
        # Timing constraints
        self._standard_checkin = time(16, 0)  # 4 PM
        self._standard_checkout = time(11, 0)  # 11 AM
        
        # Cleaning
        self._cleaning_status = CleaningStatus.NOT_SCHEDULED
        self._cleaning_scheduled_at: Optional[datetime] = None
    
    def add_reservation(self, raw: RawReservation) -> "OperationalStateBuilder":
        """Add a reservation."""
        if raw.status == "cancelled":
            return self
        
        res = Reservation(
            reservation_id=raw.reservation_id,
            property_id=self.property_id,
            guest_name=raw.guest_name,
            check_in=raw.check_in,
            check_out=raw.check_out,
            guest_count=raw.guest_count or 1,
            is_confirmed=raw.status == "confirmed",
        )
        self._reservations.append(res)
        return self
    
    def add_reservations(self, reservations: List[RawReservation]) -> "OperationalStateBuilder":
        """Add multiple reservations."""
        for res in reservations:
            self.add_reservation(res)
        return self
    
    def add_block(self, raw: RawBlock) -> "OperationalStateBuilder":
        """Add a blocked period."""
        from uuid import uuid4 as make_uuid
        block = BlockedPeriod(
            block_id=f"block-{make_uuid().hex[:8]}",
            property_id=self.property_id,
            start_date=raw.start.date() if isinstance(raw.start, datetime) else raw.start,
            end_date=raw.end.date() if isinstance(raw.end, datetime) else raw.end,
            reason=raw.reason,
        )
        self._blocks.append(block)
        return self
    
    def set_staff_capacity(self, capacity: StaffCapacity) -> "OperationalStateBuilder":
        """Set staff capacity."""
        self._staff_capacity = capacity
        return self
    
    def set_turnover_hours(self, hours: float) -> "OperationalStateBuilder":
        """Set minimum turnover hours."""
        self._turnover_hours = hours
        return self
    
    def add_known_issue(self, issue: str) -> "OperationalStateBuilder":
        """Add a known issue."""
        self._known_issues.append(issue)
        return self
    
    def set_cleaning(
        self,
        status: CleaningStatus,
        scheduled_at: Optional[datetime] = None,
    ) -> "OperationalStateBuilder":
        """Set cleaning status."""
        self._cleaning_status = status
        self._cleaning_scheduled_at = scheduled_at
        return self
    
    def set_timing(
        self,
        checkin_time: time = None,
        checkout_time: time = None,
    ) -> "OperationalStateBuilder":
        """Set check-in/out times."""
        if checkin_time:
            self._standard_checkin = checkin_time
        if checkout_time:
            self._standard_checkout = checkout_time
        return self
    
    def build(self) -> OperationalState:
        """Build the OperationalState."""
        now = datetime.utcnow()
        
        # Sort reservations by check-in
        sorted_reservations = sorted(self._reservations, key=lambda r: r.check_in)
        
        # Find current and next reservations
        current_res = None
        next_res = None
        
        for res in sorted_reservations:
            if res.check_in <= now < res.check_out:
                current_res = res
            elif res.check_in > now and next_res is None:
                next_res = res
        
        # Build calendar state
        calendar = CalendarState(
            property_id=self.property_id,
            reservations=sorted_reservations,
            blocked_periods=self._blocks,
            current_reservation=current_res,
            next_reservation=next_res,
        )
        
        # Compute turnover status
        turnover_status = self._compute_turnover_status(current_res, next_res)
        
        # Compute next checkin datetime
        next_checkin = None
        if next_res:
            next_checkin = next_res.check_in
        
        return OperationalState(
            property_id=self.property_id,
            calendar=calendar,
            next_checkin=next_checkin,
            staff_capacity=self._staff_capacity,
            turnover_status=turnover_status,
            cleaning_status=self._cleaning_status,
            cleaning_scheduled_at=self._cleaning_scheduled_at,
            turnover_buffer_hours=self._turnover_hours,
        )
    
    def _compute_turnover_status(
        self,
        current: Optional[Reservation],
        next: Optional[Reservation],
    ) -> TurnoverStatus:
        """Compute turnover status based on reservations."""
        if not current or not next:
            return TurnoverStatus.FLEXIBLE
        
        # Calculate gap
        gap = next.check_in - current.check_out
        gap_hours = gap.total_seconds() / 3600
        
        if gap_hours < self._turnover_hours:
            return TurnoverStatus.TIGHT
        elif gap_hours < self._turnover_hours * 1.5:
            return TurnoverStatus.NORMAL
        else:
            return TurnoverStatus.FLEXIBLE


# =============================================================================
# FACTORY FUNCTIONS
# =============================================================================

def build_operational_state_from_ical(
    property_id: UUID,
    ical_data: str,
) -> OperationalState:
    """
    Build OperationalState from iCal data.
    
    Parses standard iCal format from Airbnb/VRBO exports.
    """
    builder = OperationalStateBuilder(property_id)
    
    # Simple iCal parsing (in production, use icalendar library)
    lines = ical_data.split('\n')
    current_event = {}
    
    for line in lines:
        line = line.strip()
        
        if line == "BEGIN:VEVENT":
            current_event = {}
        elif line == "END:VEVENT":
            if "DTSTART" in current_event and "DTEND" in current_event:
                try:
                    start = _parse_ical_date(current_event["DTSTART"])
                    end = _parse_ical_date(current_event["DTEND"])
                    summary = current_event.get("SUMMARY", "Reservation")
                    uid = current_event.get("UID", f"res-{start.isoformat()}")
                    
                    # Check if it's a block or reservation
                    if "blocked" in summary.lower() or "owner" in summary.lower():
                        builder.add_block(RawBlock(start=start, end=end, reason=summary))
                    else:
                        builder.add_reservation(RawReservation(
                            reservation_id=uid,
                            guest_name=summary,
                            check_in=start,
                            check_out=end,
                            source="ical_import",
                        ))
                except:
                    pass
            current_event = {}
        elif ":" in line:
            key, value = line.split(":", 1)
            current_event[key] = value
    
    return builder.build()


def _parse_ical_date(value: str) -> datetime:
    """Parse iCal date format."""
    # Handle date only (YYYYMMDD)
    if len(value) == 8:
        return datetime.strptime(value, "%Y%m%d")
    # Handle datetime (YYYYMMDDTHHmmss or YYYYMMDDTHHmmssZ)
    value = value.replace("Z", "")
    if "T" in value:
        return datetime.strptime(value[:15], "%Y%m%dT%H%M%S")
    return datetime.strptime(value[:8], "%Y%m%d")


def build_sample_operational_state(property_id: UUID) -> OperationalState:
    """
    Build a sample OperationalState for testing.
    
    Creates realistic calendar with upcoming reservations.
    """
    builder = OperationalStateBuilder(property_id)
    
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Current guest (if in-stay)
    if datetime.now().hour >= 16:  # After check-in
        builder.add_reservation(RawReservation(
            reservation_id="res-current",
            guest_name="Current Guest",
            check_in=today.replace(hour=16),
            check_out=(today + timedelta(days=3)).replace(hour=11),
            source="airbnb",
        ))
    
    # Upcoming reservations
    builder.add_reservation(RawReservation(
        reservation_id="res-next-1",
        guest_name="Smith Family",
        check_in=(today + timedelta(days=4)).replace(hour=16),
        check_out=(today + timedelta(days=7)).replace(hour=11),
        source="vrbo",
        guest_count=6,
    ))
    
    builder.add_reservation(RawReservation(
        reservation_id="res-next-2",
        guest_name="Johnson Party",
        check_in=(today + timedelta(days=10)).replace(hour=16),
        check_out=(today + timedelta(days=14)).replace(hour=11),
        source="direct",
        guest_count=8,
    ))
    
    # Owner block
    builder.add_block(RawBlock(
        start=(today + timedelta(days=20)).replace(hour=0),
        end=(today + timedelta(days=25)).replace(hour=0),
        reason="owner_block",
    ))
    
    builder.set_staff_capacity(StaffCapacity.NORMAL)
    builder.set_turnover_hours(5.0)
    
    return builder.build()
