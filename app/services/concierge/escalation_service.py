"""
Escalation Service

Handles situations where AI concierge needs to hand off to a human:
- Guest explicitly requests human
- Issue/complaint detected
- Complex maintenance request
- Booking modifications

Escalations are logged and can trigger SMS/email to on-call staff.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Set
from enum import Enum
import uuid

from app.services.concierge.guest_thread_service import get_guest_thread_service
from app.services.events.event_triggers import EventSeverity, EventType, emit_event

logger = logging.getLogger(__name__)


class EscalationPriority(str, Enum):
    LOW = "low"           # FYI, no rush
    MEDIUM = "medium"     # Same day response
    HIGH = "high"         # Within 1-2 hours
    URGENT = "urgent"     # Immediate attention needed


class EscalationReason(str, Enum):
    GUEST_REQUESTED = "guest_requested"
    PROPERTY_ISSUE = "property_issue"
    MAINTENANCE = "maintenance"
    COMPLAINT = "complaint"
    BOOKING_CHANGE = "booking_change"
    BILLING = "billing"
    SAFETY = "safety"
    COMPLEX_QUESTION = "complex_question"
    REPEATED_FAILURES = "repeated_failures"
    OTHER = "other"


class EscalationStatus(str, Enum):
    PENDING = "pending"
    ACKNOWLEDGED = "acknowledged"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"


@dataclass
class EscalationTicket:
    """Escalation ticket for human follow-up"""
    id: str
    
    # Session info
    session_token: str
    guest_name: str
    guest_phone: Optional[str]
    guest_email: Optional[str]
    property_name: str
    property_code: str
    
    # Escalation details
    reason: EscalationReason
    priority: EscalationPriority
    summary: str
    
    # Context
    conversation_history: List[Dict[str, str]] = field(default_factory=list)
    last_message: str = ""
    
    # Tracking
    status: EscalationStatus = EscalationStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    acknowledged_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    
    # Assignment
    assigned_to: Optional[str] = None
    notes: List[Dict[str, Any]] = field(default_factory=list)
    
    def add_note(self, author: str, text: str) -> None:
        self.notes.append({
            "author": author,
            "text": text,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })


class EscalationDetector:
    """Detects when a conversation should be escalated to human."""
    
    URGENT_TRIGGERS = [
        "emergency", "911", "fire", "flood", "gas leak",
        "hurt", "injured", "locked out", "no power", "no water",
    ]
    
    HIGH_PRIORITY_TRIGGERS = [
        "broken", "not working", "doesn't work", "stopped working",
        "leak", "leaking", "water damage", "mold",
        "ac not working", "no air conditioning", "too hot", "too cold",
        "pest", "bugs", "roaches", "ants", "mice",
        "dirty", "filthy", "disgusting", "unacceptable",
        "refund", "compensation", "money back",
    ]
    
    MEDIUM_PRIORITY_TRIGGERS = [
        "issue", "problem", "complaint", "concern",
        "manager", "supervisor", "human", "real person",
        "speak to someone", "talk to someone", "call me",
        "maintenance", "repair", "fix",
        "checkout time", "late checkout", "early checkin",
        "extend stay", "add nights", "change dates",
    ]
    
    def detect_escalation(
        self,
        message: str,
        conversation_history: List[Dict[str, str]],
    ) -> Optional[Dict[str, Any]]:
        """Analyze message to determine if escalation is needed."""
        message_lower = message.lower()
        
        # Check urgent triggers
        for trigger in self.URGENT_TRIGGERS:
            if trigger in message_lower:
                return {
                    "needed": True,
                    "priority": EscalationPriority.URGENT,
                    "reason": self._classify_reason(message_lower),
                    "summary": f"Urgent: Guest mentioned '{trigger}'",
                }
        
        # Check high priority triggers
        for trigger in self.HIGH_PRIORITY_TRIGGERS:
            if trigger in message_lower:
                return {
                    "needed": True,
                    "priority": EscalationPriority.HIGH,
                    "reason": self._classify_reason(message_lower),
                    "summary": f"Property issue: {trigger}",
                }
        
        # Check medium priority triggers
        for trigger in self.MEDIUM_PRIORITY_TRIGGERS:
            if trigger in message_lower:
                return {
                    "needed": True,
                    "priority": EscalationPriority.MEDIUM,
                    "reason": self._classify_reason(message_lower),
                    "summary": f"Guest request: {trigger}",
                }
        
        # Check for repeated questions (AI not helping)
        if len(conversation_history) >= 6:
            return {
                "needed": True,
                "priority": EscalationPriority.MEDIUM,
                "reason": EscalationReason.REPEATED_FAILURES,
                "summary": "Guest may not be getting the help they need",
            }
        
        return None
    
    def _classify_reason(self, message: str) -> EscalationReason:
        """Classify the reason for escalation"""
        if any(w in message for w in ["emergency", "911", "fire", "flood", "hurt", "injured"]):
            return EscalationReason.SAFETY
        if any(w in message for w in ["broken", "not working", "leak", "ac ", "maintenance", "repair"]):
            return EscalationReason.MAINTENANCE
        if any(w in message for w in ["dirty", "filthy", "disgusting", "complaint", "unacceptable"]):
            return EscalationReason.COMPLAINT
        if any(w in message for w in ["refund", "money", "billing", "charge"]):
            return EscalationReason.BILLING
        if any(w in message for w in ["checkout", "checkin", "extend", "change dates", "add nights"]):
            return EscalationReason.BOOKING_CHANGE
        if any(w in message for w in ["human", "person", "manager", "speak to", "talk to"]):
            return EscalationReason.GUEST_REQUESTED
        if any(w in message for w in ["issue", "problem"]):
            return EscalationReason.PROPERTY_ISSUE
        return EscalationReason.OTHER


class EscalationService:
    """Manages escalations and human handoff."""
    
    def __init__(self, notification_service=None):
        self.notifications = notification_service
        self.detector = EscalationDetector()
        self._tickets: Dict[str, EscalationTicket] = {}  # In-memory cache

    async def _get_escalation_columns(self) -> Set[str]:
        """Return the available concierge_escalations columns in the live database."""
        from app.core.database import get_db_session
        from sqlalchemy import text

        async with get_db_session() as db:
            result = await db.execute(
                text(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name = 'concierge_escalations'
                    """
                )
            )
            return {str(row[0]) for row in result.fetchall()}

    async def _persist_ticket(self, ticket: EscalationTicket) -> None:
        """Write escalation ticket to DB."""
        try:
            from app.core.database import get_db_session
            from sqlalchemy import text
            import json
            from app.services.operator.escalation_workflow_service import get_escalation_workflow_service
            columns = await self._get_escalation_columns()
            modern_schema = "ticket_id" in columns
            async with get_db_session() as db:
                tenant_id: Optional[str] = None
                if ticket.session_token:
                    tenant_row = await db.execute(
                        text(
                            """
                            SELECT tenant_id
                            FROM concierge_guest_sessions
                            WHERE token = :token
                            LIMIT 1
                            """
                        ),
                        {"token": ticket.session_token},
                    )
                    tenant = tenant_row.fetchone()
                    if tenant and tenant[0]:
                        tenant_id = str(tenant[0])
                guest_thread_id = await get_guest_thread_service().ensure_escalation_thread(
                    db,
                    tenant_id=tenant_id,
                    property_code=ticket.property_code,
                    guest_name=ticket.guest_name,
                    session_token=ticket.session_token or None,
                )
                if modern_schema:
                    await db.execute(
                        text("""
                            INSERT INTO concierge_escalations
                                (ticket_id, guest_thread_id, session_token, guest_name, guest_phone, guest_email,
                                 property_name, property_code, reason, priority, status, summary,
                                 last_message, conversation_history, created_at)
                            VALUES
                                (:ticket_id, CAST(:guest_thread_id AS uuid), :session_token, :guest_name, :guest_phone, :guest_email,
                                 :property_name, :property_code, :reason, :priority, :status, :summary,
                                 :last_message, :conversation_history, :created_at)
                            ON CONFLICT (ticket_id) DO UPDATE SET
                                guest_thread_id = COALESCE(EXCLUDED.guest_thread_id, concierge_escalations.guest_thread_id),
                                status = EXCLUDED.status,
                                summary = EXCLUDED.summary
                        """),
                        {
                            "ticket_id": ticket.id,
                            "guest_thread_id": guest_thread_id,
                            "session_token": ticket.session_token,
                            "guest_name": ticket.guest_name,
                            "guest_phone": ticket.guest_phone,
                            "guest_email": ticket.guest_email,
                            "property_name": ticket.property_name,
                            "property_code": ticket.property_code,
                            "reason": ticket.reason.value,
                            "priority": ticket.priority.value,
                            "status": ticket.status.value,
                            "summary": ticket.summary,
                            "last_message": ticket.last_message,
                            "conversation_history": json.dumps(ticket.conversation_history),
                            "created_at": ticket.created_at,
                        },
                    )
                else:
                    values = {
                        "id": ticket.id,
                        "guest_thread_id": guest_thread_id,
                        "session_token": ticket.session_token,
                        "guest_name": ticket.guest_name,
                        "guest_phone": ticket.guest_phone,
                        "guest_email": ticket.guest_email,
                        "property_name": ticket.property_name,
                        "property_code": ticket.property_code,
                        "reason": ticket.reason.value,
                        "priority": ticket.priority.value,
                        "status": ticket.status.value,
                        "summary": ticket.summary,
                        "created_at": ticket.created_at,
                        "updated_at": ticket.created_at,
                    }
                    insert_columns = [
                        col for col in (
                            "id",
                            "guest_thread_id",
                            "session_token",
                            "guest_name",
                            "guest_phone",
                            "guest_email",
                            "property_name",
                            "property_code",
                            "reason",
                            "priority",
                            "status",
                            "summary",
                            "created_at",
                            "updated_at",
                        )
                        if col in columns
                    ]
                    update_columns = [col for col in ("status", "summary", "updated_at") if col in columns]
                    if insert_columns:
                        formatted_values = {}
                        for key, value in values.items():
                            if key not in insert_columns:
                                continue
                            if key == "guest_thread_id":
                                formatted_values[key] = str(value)
                            else:
                                formatted_values[key] = value
                        value_expr = []
                        for col in insert_columns:
                            if col == "guest_thread_id":
                                value_expr.append("CAST(:guest_thread_id AS uuid)")
                            else:
                                value_expr.append(f":{col}")
                        await db.execute(
                            text(
                                f"""
                                INSERT INTO concierge_escalations ({", ".join(insert_columns)})
                                VALUES ({", ".join(value_expr)})
                                ON CONFLICT (id) DO UPDATE SET
                                    {", ".join(f"{col} = EXCLUDED.{col}" for col in update_columns)}
                                """
                            ),
                            formatted_values,
                        )
                await db.commit()
                emit_event(
                    EventType.ESCALATION_RAISED,
                    f"Escalation {ticket.id} raised for {ticket.property_code or ticket.property_name}",
                    severity=EventSeverity.HIGH if ticket.priority in {EscalationPriority.HIGH, EscalationPriority.URGENT} else EventSeverity.MEDIUM,
                    tenant_id=uuid.UUID(tenant_id) if tenant_id else None,
                    data={
                        "ticket_id": ticket.id,
                        "guest_thread_id": guest_thread_id,
                        "session_token": ticket.session_token,
                        "property_code": ticket.property_code,
                        "priority": ticket.priority.value,
                        "reason": ticket.reason.value,
                    },
                )
                if tenant_id:
                    await get_escalation_workflow_service().sync_ticket(db, tenant_id, ticket.id)
        except Exception as e:
            logger.warning(f"Escalation DB persist failed (ticket in memory): {e}")

    async def create_external_escalation(
        self,
        *,
        tenant_id: Optional[str],
        guest_name: str,
        property_name: str,
        property_code: str,
        message: str,
        conversation_history: List[Dict[str, str]],
    ) -> Optional[EscalationTicket]:
        """Run the shared escalation detector for non-session flows like pre-booking."""
        result = self.detector.detect_escalation(message, conversation_history)
        if not result or not result.get("needed"):
            return None

        ticket = EscalationTicket(
            id=f"ESC-{uuid.uuid4().hex[:8].upper()}",
            session_token="",
            guest_name=guest_name or "Guest",
            guest_phone=None,
            guest_email=None,
            property_name=property_name or property_code or "Unknown",
            property_code=property_code or "",
            reason=result["reason"],
            priority=result["priority"],
            summary=result["summary"],
            conversation_history=conversation_history[-10:],
            last_message=message,
        )
        self._tickets[ticket.id] = ticket
        await self._notify_operator(ticket)
        await self._persist_ticket(ticket)
        return ticket
    
    async def check_and_escalate(
        self,
        session_token: str,
        message: str,
        conversation_history: List[Dict[str, str]],
        session_info: Optional[Dict[str, Any]] = None,
    ) -> Optional[EscalationTicket]:
        """Check if escalation is needed and create ticket if so."""
        result = self.detector.detect_escalation(message, conversation_history)
        
        if not result or not result.get("needed"):
            return None
        
        ticket = EscalationTicket(
            id=f"ESC-{uuid.uuid4().hex[:8].upper()}",
            session_token=session_token,
            guest_name=session_info.get("guest_name", "Guest") if session_info else "Guest",
            guest_phone=session_info.get("guest_phone") if session_info else None,
            guest_email=session_info.get("guest_email") if session_info else None,
            property_name=session_info.get("property_name", "Unknown") if session_info else "Unknown",
            property_code=session_info.get("property_code", "") if session_info else "",
            reason=result["reason"],
            priority=result["priority"],
            summary=result["summary"],
            conversation_history=conversation_history[-10:],
            last_message=message,
        )
        
        self._tickets[ticket.id] = ticket
        await self._notify_operator(ticket)
        await self._persist_ticket(ticket)
        
        logger.info(f"Created escalation ticket {ticket.id}: {ticket.summary}")
        return ticket
    
    async def create_manual_escalation(
        self,
        session_token: str,
        reason: str,
        session_info: Dict[str, Any],
        conversation_history: List[Dict[str, str]],
    ) -> EscalationTicket:
        """Create escalation when guest explicitly requests human."""
        ticket = EscalationTicket(
            id=f"ESC-{uuid.uuid4().hex[:8].upper()}",
            session_token=session_token,
            guest_name=session_info.get("guest_name", "Guest"),
            guest_phone=session_info.get("guest_phone"),
            guest_email=session_info.get("guest_email"),
            property_name=session_info.get("property_name", "Unknown"),
            property_code=session_info.get("property_code", ""),
            reason=EscalationReason.GUEST_REQUESTED,
            priority=EscalationPriority.MEDIUM,
            summary=f"Guest requested human assistance: {reason}",
            conversation_history=conversation_history[-10:],
            last_message=reason,
        )
        
        self._tickets[ticket.id] = ticket
        await self._notify_operator(ticket)
        await self._persist_ticket(ticket)
        
        return ticket
    
    async def _notify_operator(self, ticket: EscalationTicket) -> None:
        """
        Send alert to the correct operator contact(s) based on escalation type.
        Uses OperatorAlertRouter to resolve property-specific and type-specific contacts.
        """
        import asyncio
        from app.services.messaging.operator_alerts import (
            get_alert_router,
            AlertType,
            format_escalation_alert,
            format_maintenance_alert,
        )

        # Map escalation reason to alert type
        alert_type_map = {
            EscalationReason.MAINTENANCE:      AlertType.MAINTENANCE,
            EscalationReason.PROPERTY_ISSUE:   AlertType.MAINTENANCE,
            EscalationReason.SAFETY:           AlertType.SAFETY,
            EscalationReason.BILLING:          AlertType.BILLING,
            EscalationReason.GUEST_REQUESTED:  AlertType.ESCALATION,
            EscalationReason.COMPLAINT:        AlertType.ESCALATION,
            EscalationReason.COMPLEX_QUESTION: AlertType.ESCALATION,
            EscalationReason.REPEATED_FAILURES: AlertType.ESCALATION,
            EscalationReason.BOOKING_CHANGE:   AlertType.ESCALATION,
            EscalationReason.OTHER:            AlertType.ESCALATION,
        }
        alert_type = alert_type_map.get(ticket.reason, AlertType.ESCALATION)

        # Format message based on type
        if alert_type == AlertType.MAINTENANCE:
            message = format_maintenance_alert(
                guest_name=ticket.guest_name,
                property_name=ticket.property_name,
                property_code=ticket.property_code,
                issue_description=ticket.summary,
                priority=ticket.priority.value,
            )
        else:
            message = format_escalation_alert(
                guest_name=ticket.guest_name,
                property_name=ticket.property_name,
                reason=ticket.reason.value,
                last_message=ticket.last_message,
            )

        # Get company_id from property_code (best effort)
        company_id = getattr(ticket, "company_id", ticket.property_code.split("_")[0] if ticket.property_code else "unknown")

        alert_router = get_alert_router()
        result = await alert_router.send_alert(
            company_id=company_id,
            alert_type=alert_type,
            message=message,
            property_code=ticket.property_code,
        )

        logger.info(
            f"[Escalation] Alert for ticket {ticket.id} ({ticket.reason}) "
            f"sent to {result['sent_to']} (property={ticket.property_code})"
        )
    
    def get_ticket(self, ticket_id: str) -> Optional[EscalationTicket]:
        return self._tickets.get(ticket_id)
    
    async def load_pending_from_db(self) -> int:
        """Load pending escalation tickets from DB into memory (call on startup or on demand)."""
        try:
            from app.core.database import get_db_session
            from sqlalchemy import text
            import json as _json
            columns = await self._get_escalation_columns()
            modern_schema = "ticket_id" in columns
            async with get_db_session() as db:
                if modern_schema:
                    phone_expr = "guest_phone" if "guest_phone" in columns else "NULL AS guest_phone"
                    email_expr = "guest_email" if "guest_email" in columns else "NULL AS guest_email"
                    last_message_expr = "last_message" if "last_message" in columns else "'' AS last_message"
                    history_expr = "conversation_history" if "conversation_history" in columns else "'[]'::jsonb AS conversation_history"
                    result = await db.execute(
                        text("""
                            SELECT ticket_id, session_token, guest_name, {phone_expr}, {email_expr},
                                   property_name, property_code, reason, priority, status, summary,
                                   {last_message_expr}, {history_expr}, created_at
                            FROM concierge_escalations
                            WHERE status IN ('pending', 'acknowledged')
                            ORDER BY created_at DESC
                            LIMIT 200
                        """.format(
                            phone_expr=phone_expr,
                            email_expr=email_expr,
                            last_message_expr=last_message_expr,
                            history_expr=history_expr,
                        ))
                    )
                else:
                    phone_expr = "guest_phone" if "guest_phone" in columns else "NULL AS guest_phone"
                    email_expr = "guest_email" if "guest_email" in columns else "NULL AS guest_email"
                    result = await db.execute(
                        text("""
                            SELECT id AS ticket_id, session_token, guest_name, {phone_expr}, {email_expr},
                                   property_name, property_code, reason, priority, status, summary,
                                   '' AS last_message, '[]'::jsonb AS conversation_history, created_at
                            FROM concierge_escalations
                            WHERE status IN ('pending', 'acknowledged', 'open')
                            ORDER BY created_at DESC
                            LIMIT 200
                        """.format(
                            phone_expr=phone_expr,
                            email_expr=email_expr,
                        ))
                    )
                rows = result.fetchall()
                loaded = 0
                for row in rows:
                    if row.ticket_id not in self._tickets:
                        ticket = EscalationTicket(
                            id=row.ticket_id,
                            session_token=row.session_token,
                            guest_name=row.guest_name,
                            guest_phone=row.guest_phone,
                            guest_email=row.guest_email,
                            property_name=row.property_name,
                            property_code=row.property_code,
                            reason=EscalationReason(row.reason),
                            priority=EscalationPriority(row.priority),
                            status=EscalationStatus(row.status),
                            summary=row.summary,
                            last_message=row.last_message or "",
                            conversation_history=_json.loads(row.conversation_history) if row.conversation_history else [],
                            created_at=row.created_at,
                        )
                        self._tickets[ticket.id] = ticket
                        loaded += 1
                return loaded
        except Exception as e:
            logger.warning(f"Escalation DB load failed: {e}")
            return 0

    def get_pending_tickets(self) -> List[EscalationTicket]:
        return [
            t for t in self._tickets.values()
            if t.status in (EscalationStatus.PENDING, EscalationStatus.ACKNOWLEDGED)
        ]
    
    def acknowledge_ticket(self, ticket_id: str, operator: str) -> Optional[EscalationTicket]:
        ticket = self._tickets.get(ticket_id)
        if ticket:
            ticket.status = EscalationStatus.ACKNOWLEDGED
            ticket.acknowledged_at = datetime.now(timezone.utc)
            ticket.assigned_to = operator
            ticket.add_note(operator, "Acknowledged")
        return ticket
    
    def resolve_ticket(self, ticket_id: str, operator: str, note: str) -> Optional[EscalationTicket]:
        ticket = self._tickets.get(ticket_id)
        if ticket:
            ticket.status = EscalationStatus.RESOLVED
            ticket.resolved_at = datetime.now(timezone.utc)
            ticket.add_note(operator, f"Resolved: {note}")
        return ticket


# Singleton
_escalation_service: Optional[EscalationService] = None

def get_escalation_service() -> EscalationService:
    global _escalation_service
    if _escalation_service is None:
        _escalation_service = EscalationService()
    return _escalation_service
