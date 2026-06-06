"""
Operator Alert Routing Service

Handles which person/phone receives which type of alert, with full support for:
  - Alert-type-specific contacts (maintenance ≠ owner)
  - Property-level overrides (property-specific maintenance contact)
  - Active hours (7am–9pm only, overnight, 24/7)
  - Vacation / OOO mode: mark a contact unavailable until a date → auto-skipped
  - Escalation chain: if primary doesn't ack in N minutes → secondary fires
  - Coverage-gap fallback: if ALL contacts unavailable → Oyvoda ops notified

Resolution order (most specific first):
    1. Property-level contact for this alert_type + property_code
    2. Operator-level contact for this alert_type
    3. Operator primary/general contact
    4. Oyvoda ops fallback (coverage gap — internal only)

Vacation handling:
    Each AlertContact has two fields:
        is_available: bool          — False = currently on vacation / OOO
        unavailable_until: datetime — auto-restores availability at this time

    The Settings → Alert Routing panel has a "Mark OOO" button per contact.
    When toggled, the router skips that contact and moves to the next in
    escalation_order. If all contacts for a type are unavailable, the
    coverage-gap logic fires.

DB schema additions (run MIGRATION_SQL below):
    ALTER TABLE operator_alert_contacts ADD COLUMN is_available BOOLEAN DEFAULT TRUE;
    ALTER TABLE operator_alert_contacts ADD COLUMN unavailable_until TIMESTAMPTZ;
    ALTER TABLE operator_alert_contacts ADD COLUMN redirect_to_id UUID REFERENCES operator_alert_contacts(id);

Escalation ack tracking (operator_alert_acks table):
    Celery beat task runs every 5 minutes checking for unacked alerts past timeout.
    If unacked → fires to next contact in chain.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

logger = logging.getLogger(__name__)


# =============================================================================
# ALERT TYPE ENUM
# =============================================================================

class AlertType(str, Enum):
    MAINTENANCE         = "maintenance"
    ESCALATION          = "escalation"
    KB_GAP              = "kb_gap"
    LATE_CHECKOUT_REQ   = "late_checkout_req"
    EXTEND_STAY_REQ     = "extend_stay_req"
    PRE_BOOKING_INBOUND = "pre_booking"
    SAFETY              = "safety"
    BILLING             = "billing"
    REVIEW_ALERT        = "review_alert"
    SYSTEM_NOTICE       = "system_notice"   # Low-priority ops notices (orphans, sync issues)
    GENERAL             = "general"


# Timeouts (minutes) before escalating to next contact if no ack
ESCALATION_TIMEOUTS: Dict[AlertType, int] = {
    AlertType.SAFETY:               5,    # Immediate — safety never waits
    AlertType.MAINTENANCE:         15,    # Fast — guest is impacted
    AlertType.ESCALATION:          20,    # Guest waiting for human
    AlertType.PRE_BOOKING_INBOUND: 60,    # Revenue-sensitive but not urgent
    AlertType.LATE_CHECKOUT_REQ:   30,
    AlertType.EXTEND_STAY_REQ:     60,
    AlertType.KB_GAP:             120,    # Just informational
    AlertType.BILLING:             60,
    AlertType.REVIEW_ALERT:       240,
    AlertType.GENERAL:             60,
}


# =============================================================================
# ALERT CONTACT MODEL
# =============================================================================

@dataclass
class AlertContact:
    """
    A configured alert contact for an operator.
    Stored in operator_alert_contacts table.
    """
    id: str
    company_id: str
    alert_type: AlertType
    property_code: Optional[str]        # None = applies to all properties

    contact_name: str
    contact_phone: Optional[str]        # E.164 format
    contact_email: Optional[str]

    is_primary: bool = True
    escalation_order: int = 1           # Lower = first to receive; ties resolved by id
    escalation_timeout_minutes: int = 30

    # Active hours (None = 24/7)
    active_hours_start: Optional[time] = None
    active_hours_end: Optional[time] = None

    # Vacation / OOO
    is_available: bool = True           # False = currently OOO
    unavailable_until: Optional[datetime] = None  # Auto-restore at this UTC time

    # Redirect: when unavailable, optionally hard-redirect to another contact ID
    redirect_to_id: Optional[str] = None

    notes: Optional[str] = None

    # ── Availability resolution ──────────────────────────────────────────────

    def effective_availability(self) -> bool:
        """
        Compute actual availability considering:
        1. is_available flag
        2. unavailable_until auto-expiry
        3. active_hours window
        """
        # Auto-restore if unavailable_until has passed
        if not self.is_available and self.unavailable_until:
            if datetime.utcnow() >= self.unavailable_until:
                # Would restore in DB; treat as available for this call
                self.is_available = True
                self.unavailable_until = None

        if not self.is_available:
            return False

        return self._is_within_active_hours()

    def _is_within_active_hours(self) -> bool:
        if not self.active_hours_start or not self.active_hours_end:
            return True  # 24/7

        now = datetime.utcnow().time()
        if self.active_hours_start <= self.active_hours_end:
            return self.active_hours_start <= now <= self.active_hours_end
        else:
            # Overnight window (e.g. 10pm–6am)
            return now >= self.active_hours_start or now <= self.active_hours_end

    def availability_reason(self) -> str:
        """Human-readable reason for unavailability — used in dashboard display."""
        if not self.is_available:
            if self.unavailable_until:
                return f"OOO until {self.unavailable_until.strftime('%b %d %I:%M %p')} UTC"
            return "Marked unavailable"
        if not self._is_within_active_hours():
            return f"Outside active hours ({self.active_hours_start}–{self.active_hours_end})"
        return "Available"


# =============================================================================
# ALERT SEND RESULT
# =============================================================================

@dataclass
class AlertSendResult:
    """
    Full audit trail of an alert send attempt — who received it, who was skipped, why.
    """
    alert_type: AlertType
    property_code: Optional[str]
    message_preview: str

    sent_to: List[Dict[str, str]] = field(default_factory=list)       # [{name, phone, channel}]
    skipped: List[Dict[str, str]] = field(default_factory=list)       # [{name, reason}]
    coverage_gap: bool = False                                         # True = nobody available
    oyvoda_notified: bool = False                                      # Fallback triggered

    sent_count: int = 0
    fired_at: datetime = field(default_factory=datetime.utcnow)

    def log_summary(self) -> None:
        if self.coverage_gap:
            logger.warning(
                f"[AlertRouter] COVERAGE GAP — {self.alert_type} @ {self.property_code}: "
                f"all contacts unavailable. Oyvoda notified: {self.oyvoda_notified}"
            )
        else:
            logger.info(
                f"[AlertRouter] {self.alert_type} @ {self.property_code} "
                f"→ sent to {[s['name'] for s in self.sent_to]} "
                f"(skipped: {[s['name'] for s in self.skipped]})"
            )


# =============================================================================
# ENV VAR FALLBACK CONTACTS
# =============================================================================

def _default_contacts_from_env(
    company_id: str,
    alert_type: AlertType,
    property_code: Optional[str],
) -> List[AlertContact]:
    """
    Fall back to env var contacts when DB isn't configured.
    Always returns at least the primary manager if set.
    """
    contacts = []

    primary_phone = (
        os.getenv("OPERATOR_ALERT_PRIMARY_PHONE")
        or os.getenv("TWILIO_PHONE_NUMBER")
    )
    if primary_phone:
        contacts.append(AlertContact(
            id="env_primary",
            company_id=company_id,
            alert_type=alert_type,
            property_code=None,
            contact_name="Primary Manager",
            contact_phone=primary_phone,
            contact_email=os.getenv("OPERATOR_ALERT_PRIMARY_EMAIL"),
            is_primary=True,
            escalation_order=1,
            escalation_timeout_minutes=ESCALATION_TIMEOUTS.get(alert_type, 30),
        ))

    # Maintenance-specific contact (insert before primary)
    if alert_type == AlertType.MAINTENANCE:
        maint_phone = os.getenv("OPERATOR_ALERT_MAINTENANCE_PHONE")
        if maint_phone:
            contacts.insert(0, AlertContact(
                id="env_maintenance",
                company_id=company_id,
                alert_type=alert_type,
                property_code=None,
                contact_name="Maintenance Coordinator",
                contact_phone=maint_phone,
                contact_email=os.getenv("OPERATOR_ALERT_MAINTENANCE_EMAIL"),
                is_primary=True,
                escalation_order=1,
                escalation_timeout_minutes=15,
            ))

    # Secondary / backup contact
    secondary_phone = os.getenv("OPERATOR_ALERT_SECONDARY_PHONE")
    if secondary_phone:
        contacts.append(AlertContact(
            id="env_secondary",
            company_id=company_id,
            alert_type=alert_type,
            property_code=None,
            contact_name="Secondary / Backup",
            contact_phone=secondary_phone,
            contact_email=os.getenv("OPERATOR_ALERT_SECONDARY_EMAIL"),
            is_primary=False,
            escalation_order=2,
            escalation_timeout_minutes=ESCALATION_TIMEOUTS.get(alert_type, 30),
        ))

    return contacts


# =============================================================================
# OPERATOR ALERT ROUTER
# =============================================================================

class OperatorAlertRouter:
    """
    Resolves the correct alert contacts and sends with full vacation/OOO support.

    Works with or without a DB session:
    - With DB: reads from operator_alert_contacts (full flexibility)
    - Without DB: falls back to env var contacts
    """

    def __init__(self, db=None):
        self.db = db

    # ── Public API ───────────────────────────────────────────────────────────

    async def get_recipients(
        self,
        company_id: str,
        alert_type: AlertType,
        property_code: Optional[str] = None,
        include_unavailable: bool = False,
    ) -> Tuple[List[AlertContact], List[AlertContact]]:
        """
        Get ordered (available, unavailable) contact lists for this alert.

        Returns:
            (available_contacts, skipped_contacts)
            available_contacts: ordered by escalation_order, active and not OOO
            skipped_contacts:   those who were skipped (OOO or outside hours)
        """
        raw = await self._fetch_contacts(company_id, alert_type, property_code)

        available = []
        skipped = []

        for contact in raw:
            # Resolve any redirect first
            effective = await self._resolve_redirect(contact, company_id)

            if effective.effective_availability():
                available.append(effective)
            else:
                skipped.append(effective)

        return available, skipped

    async def send_alert(
        self,
        company_id: str,
        alert_type: AlertType,
        message: str,
        property_code: Optional[str] = None,
        alert_id: Optional[str] = None,          # For ack tracking
        guest_session_url: Optional[str] = None,
    ) -> AlertSendResult:
        """
        Resolve recipients and send alert.

        Handles:
        - Skipping OOO / outside-hours contacts (logs reason)
        - Coverage-gap detection and Oyvoda ops fallback
        - Guest-facing fallback message when nobody available

        Does NOT handle:
        - Escalation timeouts (those are handled by Celery beat task)
        """
        from app.services.messaging.channel_router import (
            get_channel_router,
            ChannelMessage,
            MessageChannel,
        )

        available, skipped = await self.get_recipients(
            company_id=company_id,
            alert_type=alert_type,
            property_code=property_code,
        )

        result = AlertSendResult(
            alert_type=alert_type,
            property_code=property_code,
            message_preview=message[:80],
            skipped=[
                {
                    "name": c.contact_name,
                    "phone": c.contact_phone or "—",
                    "reason": c.availability_reason(),
                }
                for c in skipped
            ],
        )

        router = get_channel_router()

        if not available:
            # ── Coverage gap ──────────────────────────────────────────────
            result.coverage_gap = True

            # Notify Oyvoda ops team internally
            oyvoda_ops = os.getenv("OYVODA_OPS_PHONE")
            if oyvoda_ops:
                gap_msg = (
                    f"⚠️ COVERAGE GAP — Oyvoda alert has no available recipients.\n\n"
                    f"Company: {company_id}\n"
                    f"Alert type: {alert_type}\n"
                    f"Property: {property_code or 'all'}\n\n"
                    f"Message:\n{message}"
                )
                gap_result = await router.send_operator_alert(oyvoda_ops, gap_msg)
                result.oyvoda_notified = gap_result.success

            # Also try any skipped contacts' redirects as last resort
            for skipped_contact in skipped:
                if skipped_contact.redirect_to_id:
                    redirect = await self._fetch_contact_by_id(
                        skipped_contact.redirect_to_id, company_id
                    )
                    if redirect and redirect.effective_availability():
                        send_result = await router.send_operator_alert(
                            redirect.contact_phone, message
                        )
                        if send_result.success:
                            result.sent_to.append({
                                "name": redirect.contact_name,
                                "phone": redirect.contact_phone,
                                "channel": str(send_result.channel),
                                "note": f"redirect from {skipped_contact.contact_name}",
                            })
                            result.sent_count += 1
                            break  # One redirect is enough

            result.log_summary()
            return result

        # ── Normal send ───────────────────────────────────────────────────
        for contact in available:
            if not contact.contact_phone:
                continue

            send_result = await router.send_operator_alert(contact.contact_phone, message)

            if send_result.success:
                result.sent_to.append({
                    "name": contact.contact_name,
                    "phone": contact.contact_phone,
                    "channel": str(send_result.channel),
                    "escalation_order": contact.escalation_order,
                })
                result.sent_count += 1

                # Record ack expectation for escalation tracking
                if alert_id:
                    await self._record_alert_send(
                        alert_id=alert_id,
                        contact=contact,
                        alert_type=alert_type,
                    )
            else:
                logger.warning(
                    f"[AlertRouter] Send failed to {contact.contact_name} "
                    f"({contact.contact_phone}): {send_result.error}"
                )
                # Don't add to skipped — it was attempted, just delivery failed

        result.log_summary()
        return result

    # ── OOO management ───────────────────────────────────────────────────────

    async def mark_ooo(
        self,
        contact_id: str,
        company_id: str,
        unavailable_until: datetime,
        redirect_to_id: Optional[str] = None,
        marked_by: str = "operator",
    ) -> bool:
        """
        Mark a contact as OOO until a specific datetime.

        Args:
            contact_id: UUID of the contact to mark OOO
            company_id: Operator company ID (for authorization)
            unavailable_until: UTC datetime when they return
            redirect_to_id: Optional — all their alerts redirect to this contact while OOO
            marked_by: Who triggered this (operator self-service, admin, etc.)

        Returns:
            True on success
        """
        if not self.db:
            logger.warning("[AlertRouter] mark_ooo: No DB session")
            return False

        try:
            from sqlalchemy import text
            await self.db.execute(
                text("""
                    UPDATE operator_alert_contacts
                    SET
                        is_available      = FALSE,
                        unavailable_until = :until,
                        redirect_to_id    = :redirect,
                        notes             = CONCAT_WS(' | ', notes,
                            :note
                        ),
                        updated_at        = NOW()
                    WHERE id = :cid
                      AND company_id = :company
                """),
                {
                    "cid": contact_id,
                    "company": str(company_id),
                    "until": unavailable_until,
                    "redirect": redirect_to_id,
                    "note": f"OOO set by {marked_by} until {unavailable_until.strftime('%Y-%m-%d')}",
                },
            )
            await self.db.commit()
            logger.info(
                f"[AlertRouter] Contact {contact_id} marked OOO until "
                f"{unavailable_until} by {marked_by}"
            )
            return True
        except Exception as e:
            logger.error(f"[AlertRouter] mark_ooo failed: {e}")
            return False

    async def mark_available(
        self,
        contact_id: str,
        company_id: str,
    ) -> bool:
        """
        Mark a contact as available again (return from vacation).
        Also clears any redirect that was set.
        """
        if not self.db:
            return False

        try:
            from sqlalchemy import text
            await self.db.execute(
                text("""
                    UPDATE operator_alert_contacts
                    SET
                        is_available      = TRUE,
                        unavailable_until = NULL,
                        redirect_to_id    = NULL,
                        updated_at        = NOW()
                    WHERE id = :cid
                      AND company_id = :company
                """),
                {"cid": contact_id, "company": str(company_id)},
            )
            await self.db.commit()
            logger.info(f"[AlertRouter] Contact {contact_id} restored to available")
            return True
        except Exception as e:
            logger.error(f"[AlertRouter] mark_available failed: {e}")
            return False

    async def auto_restore_expired_ooo(self) -> int:
        """
        Restore contacts whose unavailable_until has passed.
        Called by Celery beat task every hour.

        Returns: number of contacts restored
        """
        if not self.db:
            return 0
        try:
            from sqlalchemy import text
            result = await self.db.execute(
                text("""
                    UPDATE operator_alert_contacts
                    SET
                        is_available      = TRUE,
                        unavailable_until = NULL,
                        redirect_to_id    = NULL,
                        updated_at        = NOW()
                    WHERE is_available = FALSE
                      AND unavailable_until IS NOT NULL
                      AND unavailable_until <= NOW()
                    RETURNING id, contact_name, company_id
                """)
            )
            restored = result.fetchall()
            await self.db.commit()
            if restored:
                logger.info(
                    f"[AlertRouter] Auto-restored {len(restored)} OOO contacts: "
                    f"{[r.contact_name for r in restored]}"
                )
            return len(restored)
        except Exception as e:
            logger.error(f"[AlertRouter] auto_restore_expired_ooo failed: {e}")
            return 0

    # ── Escalation ack tracking ───────────────────────────────────────────────

    async def _record_alert_send(
        self,
        alert_id: str,
        contact: AlertContact,
        alert_type: AlertType,
    ) -> None:
        """
        Record that an alert was sent to this contact and when we expect ack.
        The Celery beat task (check_unacked_alerts) reads this table and
        fires to the next contact if ack_deadline passes without acknowledgment.
        """
        if not self.db:
            return
        try:
            from sqlalchemy import text
            import uuid as _uuid
            timeout = ESCALATION_TIMEOUTS.get(alert_type, contact.escalation_timeout_minutes)
            ack_deadline = datetime.utcnow() + timedelta(minutes=timeout)

            await self.db.execute(
                text("""
                    INSERT INTO operator_alert_acks
                        (id, alert_id, contact_id, company_id, alert_type,
                         sent_at, ack_deadline, acked, escalated)
                    VALUES
                        (:id, :aid, :cid, :company, :atype,
                         NOW(), :deadline, FALSE, FALSE)
                    ON CONFLICT (alert_id, contact_id) DO NOTHING
                """),
                {
                    "id": str(_uuid.uuid4()),
                    "aid": alert_id,
                    "cid": contact.id,
                    "company": contact.company_id,
                    "atype": alert_type.value,
                    "deadline": ack_deadline,
                },
            )
            await self.db.commit()
        except Exception as e:
            logger.warning(f"[AlertRouter] _record_alert_send failed: {e}")

    async def check_unacked_alerts(self) -> int:
        """
        Called by Celery beat every 5 minutes.
        Finds alerts past their ack_deadline with no ack, then fires to next
        contact in escalation chain.

        Returns: number of escalations fired
        """
        if not self.db:
            return 0

        escalated = 0
        try:
            from sqlalchemy import text

            # Find overdue unacked alerts
            result = await self.db.execute(
                text("""
                    SELECT
                        aa.alert_id, aa.company_id, aa.alert_type,
                        aa.contact_id, oac.escalation_order,
                        aa.id AS ack_id
                    FROM operator_alert_acks aa
                    JOIN operator_alert_contacts oac ON oac.id = aa.contact_id
                    WHERE aa.acked = FALSE
                      AND aa.escalated = FALSE
                      AND aa.ack_deadline <= NOW()
                    ORDER BY aa.ack_deadline ASC
                    LIMIT 50
                """)
            )
            overdue = result.fetchall()

            for row in overdue:
                # Find next contact in escalation chain
                next_result = await self.db.execute(
                    text("""
                        SELECT id, contact_name, contact_phone, escalation_order
                        FROM operator_alert_contacts
                        WHERE company_id = :cid
                          AND alert_type = :atype
                          AND escalation_order > :current_order
                          AND is_available = TRUE
                        ORDER BY escalation_order ASC
                        LIMIT 1
                    """),
                    {
                        "cid": str(row.company_id),
                        "atype": row.alert_type,
                        "current_order": row.escalation_order,
                    },
                )
                next_contact_row = next_result.fetchone()

                if next_contact_row and next_contact_row.contact_phone:
                    # Retrieve original alert message from acks/escalations table
                    msg_result = await self.db.execute(
                        text("""
                            SELECT message FROM operator_alert_log
                            WHERE alert_id = :aid LIMIT 1
                        """),
                        {"aid": row.alert_id},
                    )
                    msg_row = msg_result.fetchone()
                    message = (
                        f"⏰ ESCALATED — no response from previous contact.\n\n"
                        + (msg_row.message if msg_row else f"Alert ID: {row.alert_id}")
                    )

                    from app.services.messaging.channel_router import get_channel_router, ChannelMessage
                    router = get_channel_router()
                    await router.send_operator_alert(next_contact_row.contact_phone, message)

                    escalated += 1
                    logger.info(
                        f"[AlertRouter] Escalated alert {row.alert_id} to "
                        f"{next_contact_row.contact_name} (order {next_contact_row.escalation_order})"
                    )
                else:
                    # No next contact — check Oyvoda ops fallback
                    oyvoda_ops = os.getenv("OYVODA_OPS_PHONE")
                    if oyvoda_ops:
                        await get_channel_router().send_operator_alert(
                            oyvoda_ops,
                            f"🚨 UNHANDLED ESCALATION — alert {row.alert_id} "
                            f"for company {row.company_id} has no available contacts. "
                            f"Oyvoda intervention required."
                        )
                        logger.warning(
                            f"[AlertRouter] Alert {row.alert_id} has no escalation path "
                            f"— Oyvoda ops notified"
                        )

                # Mark as escalated so we don't re-fire
                await self.db.execute(
                    text("""
                        UPDATE operator_alert_acks
                        SET escalated = TRUE
                        WHERE id = :id
                    """),
                    {"id": row.ack_id},
                )

            await self.db.commit()
        except Exception as e:
            logger.error(f"[AlertRouter] check_unacked_alerts failed: {e}")

        return escalated

    # ── Internal DB helpers ──────────────────────────────────────────────────

    async def _fetch_contacts(
        self,
        company_id: str,
        alert_type: AlertType,
        property_code: Optional[str],
    ) -> List[AlertContact]:
        """Fetch contacts from DB. Falls back to env vars if no DB."""
        if self.db:
            try:
                return await self._get_from_db(company_id, alert_type, property_code)
            except Exception as e:
                logger.error(f"[AlertRouter] DB fetch failed: {e}, using env fallback")

        return _default_contacts_from_env(company_id, alert_type, property_code)

    async def _get_from_db(
        self,
        company_id: str,
        alert_type: AlertType,
        property_code: Optional[str],
    ) -> List[AlertContact]:
        from sqlalchemy import text

        rows = await self.db.execute(
            text("""
                SELECT
                    id::text, company_id::text, alert_type, property_code,
                    contact_name, contact_phone, contact_email,
                    is_primary, escalation_order, escalation_timeout_minutes,
                    active_hours_start, active_hours_end,
                    is_available, unavailable_until, redirect_to_id::text, notes
                FROM operator_alert_contacts
                WHERE company_id = :cid
                  AND (alert_type = :atype OR alert_type = 'general')
                  AND (property_code = :prop OR property_code IS NULL)
                ORDER BY
                    CASE WHEN property_code = :prop THEN 0 ELSE 1 END,
                    CASE WHEN alert_type = :atype THEN 0 ELSE 1 END,
                    escalation_order ASC
            """),
            {
                "cid": str(company_id),
                "atype": alert_type.value,
                "prop": property_code or "",
            },
        )

        contacts = []
        for row in rows.fetchall():
            contacts.append(AlertContact(
                id=row.id,
                company_id=row.company_id,
                alert_type=AlertType(row.alert_type),
                property_code=row.property_code,
                contact_name=row.contact_name,
                contact_phone=row.contact_phone,
                contact_email=row.contact_email,
                is_primary=row.is_primary,
                escalation_order=row.escalation_order,
                escalation_timeout_minutes=row.escalation_timeout_minutes,
                active_hours_start=row.active_hours_start,
                active_hours_end=row.active_hours_end,
                is_available=row.is_available if row.is_available is not None else True,
                unavailable_until=row.unavailable_until,
                redirect_to_id=row.redirect_to_id,
                notes=row.notes,
            ))
        return contacts

    async def _fetch_contact_by_id(
        self,
        contact_id: str,
        company_id: str,
    ) -> Optional[AlertContact]:
        if not self.db:
            return None
        try:
            from sqlalchemy import text
            result = await self.db.execute(
                text("""
                    SELECT id::text, company_id::text, alert_type, property_code,
                           contact_name, contact_phone, contact_email,
                           is_primary, escalation_order, escalation_timeout_minutes,
                           active_hours_start, active_hours_end,
                           is_available, unavailable_until, redirect_to_id::text, notes
                    FROM operator_alert_contacts
                    WHERE id = :cid AND company_id = :company
                    LIMIT 1
                """),
                {"cid": contact_id, "company": str(company_id)},
            )
            row = result.fetchone()
            if not row:
                return None
            return AlertContact(
                id=row.id,
                company_id=row.company_id,
                alert_type=AlertType(row.alert_type),
                property_code=row.property_code,
                contact_name=row.contact_name,
                contact_phone=row.contact_phone,
                contact_email=row.contact_email,
                is_primary=row.is_primary,
                escalation_order=row.escalation_order,
                escalation_timeout_minutes=row.escalation_timeout_minutes,
                active_hours_start=row.active_hours_start,
                active_hours_end=row.active_hours_end,
                is_available=row.is_available if row.is_available is not None else True,
                unavailable_until=row.unavailable_until,
                redirect_to_id=row.redirect_to_id,
                notes=row.notes,
            )
        except Exception as e:
            logger.error(f"[AlertRouter] _fetch_contact_by_id failed: {e}")
            return None

    async def _resolve_redirect(
        self,
        contact: AlertContact,
        company_id: str,
    ) -> AlertContact:
        """
        If a contact has redirect_to_id set and is unavailable,
        return the redirect target instead.
        Only one level of redirect (no chains).
        """
        if contact.is_available:
            return contact
        if not contact.redirect_to_id:
            return contact

        redirect = await self._fetch_contact_by_id(contact.redirect_to_id, company_id)
        if redirect and redirect.effective_availability():
            logger.info(
                f"[AlertRouter] Redirecting {contact.contact_name} (OOO) "
                f"→ {redirect.contact_name}"
            )
            return redirect
        return contact  # Redirect also unavailable — return original for logging


# =============================================================================
# MESSAGE FORMATTERS
# =============================================================================

def format_maintenance_alert(
    guest_name: str,
    property_name: str,
    property_code: str,
    issue_description: str,
    priority: str = "high",
    session_url: Optional[str] = None,
) -> str:
    urgency = "🚨 URGENT" if priority == "urgent" else "⚠️ Maintenance"
    msg = (
        f"{urgency} — {property_name}\n\n"
        f"Guest: {guest_name}\n"
        f"Issue: {issue_description}\n\n"
    )
    msg += f"Session: {session_url}" if session_url else "Reply to respond to guest."
    return msg


def format_escalation_alert(
    guest_name: str,
    property_name: str,
    reason: str,
    last_message: str,
    session_url: Optional[str] = None,
) -> str:
    msg = (
        f"🔔 Guest escalation — {property_name}\n\n"
        f"Guest: {guest_name}\n"
        f"Reason: {reason}\n"
        f"Last message: \"{last_message[:80]}{'...' if len(last_message) > 80 else ''}\"\n\n"
    )
    if session_url:
        msg += f"View conversation: {session_url}"
    return msg


def format_coverage_gap_guest_message(
    property_name: str,
    operator_phone: Optional[str] = None,
) -> str:
    """
    Message sent to the guest when all operator contacts are unavailable.
    Tells them how to reach someone directly without exposing the internal gap.
    """
    msg = (
        f"Your host at {property_name} has been notified and will follow up shortly."
    )
    if operator_phone:
        msg += f"\n\nIf this is urgent, you can reach them directly at {operator_phone}."
    return msg


def format_kb_gap_alert(
    property_name: str,
    question: str,
    times_asked: int,
    suggested_answer: Optional[str] = None,
) -> str:
    msg = (
        f"📚 KB Gap — {property_name}\n\n"
        f"Guests are asking: \"{question}\"\n"
        f"Asked {times_asked}x this week\n\n"
    )
    if suggested_answer:
        msg += f"Suggested answer: {suggested_answer}\n\n"
    msg += "Add this to your Knowledge Base in the Oyvoda dashboard."
    return msg


def format_pre_booking_alert(
    platform: str,
    property_name: str,
    question: str,
    ai_draft: str,
) -> str:
    return (
        f"📬 Pre-booking inquiry ({platform}) — {property_name}\n\n"
        f"Question: \"{question}\"\n\n"
        f"AI Draft: \"{ai_draft}\"\n\n"
        f"Review and approve in the Oyvoda dashboard."
    )


# =============================================================================
# DB MIGRATION
# =============================================================================

MIGRATION_SQL = """
-- Extend operator_alert_contacts with OOO fields
ALTER TABLE operator_alert_contacts
    ADD COLUMN IF NOT EXISTS is_available      BOOLEAN DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS unavailable_until TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS redirect_to_id    UUID REFERENCES operator_alert_contacts(id);

-- Ack tracking table for escalation chain
CREATE TABLE IF NOT EXISTS operator_alert_acks (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    alert_id    TEXT NOT NULL,
    contact_id  UUID NOT NULL REFERENCES operator_alert_contacts(id),
    company_id  UUID NOT NULL,
    alert_type  TEXT NOT NULL,
    sent_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ack_deadline TIMESTAMPTZ NOT NULL,
    acked       BOOLEAN NOT NULL DEFAULT FALSE,
    acked_at    TIMESTAMPTZ,
    escalated   BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE(alert_id, contact_id)
);

-- Alert log (message text stored for escalation re-send)
CREATE TABLE IF NOT EXISTS operator_alert_log (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    alert_id    TEXT UNIQUE NOT NULL,
    company_id  UUID NOT NULL,
    alert_type  TEXT NOT NULL,
    property_code TEXT,
    message     TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_acks_deadline
    ON operator_alert_acks (acked, escalated, ack_deadline)
    WHERE acked = FALSE AND escalated = FALSE;
"""


# =============================================================================
# SINGLETON
# =============================================================================

_alert_router_no_db: Optional[OperatorAlertRouter] = None


def get_alert_router(db=None) -> OperatorAlertRouter:
    global _alert_router_no_db
    if db:
        return OperatorAlertRouter(db=db)
    if _alert_router_no_db is None:
        _alert_router_no_db = OperatorAlertRouter(db=None)
    return _alert_router_no_db
