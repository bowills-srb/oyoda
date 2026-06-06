"""
SMS Notification Service using Twilio.

Handles:
- Welcome messages with concierge link
- Extend stay offers
- Check-in/checkout reminders
- Custom messages from operators
"""

from datetime import datetime
from typing import Optional
from uuid import UUID
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class SMSService:
    """Twilio SMS service for guest notifications."""
    
    def __init__(self):
        self._client = None
    
    @property
    def client(self):
        """Lazy-load Twilio client."""
        if self._client is None:
            if not settings.twilio_account_sid or not settings.twilio_auth_token:
                logger.warning("Twilio credentials not configured")
                return None
            
            from twilio.rest import Client
            self._client = Client(
                settings.twilio_account_sid,
                settings.twilio_auth_token,
            )
        return self._client
    
    @property
    def from_number(self) -> Optional[str]:
        return settings.twilio_phone_number
    
    async def send_sms(
        self,
        to: str,
        body: str,
        db: Optional[AsyncSession] = None,
        session_id: Optional[UUID] = None,
        notification_type: str = "custom",
    ) -> dict:
        """
        Send an SMS message.
        
        Args:
            to: Phone number (E.164 format preferred, e.g., +15551234567)
            body: Message content
            db: Database session for logging
            session_id: Guest session ID for tracking
            notification_type: Type of notification for logging
            
        Returns:
            {
                "success": bool,
                "message_sid": str or None,
                "error": str or None,
            }
        """
        # Normalize phone number
        to = self._normalize_phone(to)
        
        if not self.client:
            logger.error("Twilio client not available")
            return {
                "success": False,
                "message_sid": None,
                "error": "SMS service not configured",
            }
        
        if not self.from_number:
            logger.error("Twilio from number not configured")
            return {
                "success": False,
                "message_sid": None,
                "error": "SMS from number not configured",
            }
        
        try:
            message = self.client.messages.create(
                body=body,
                from_=self.from_number,
                to=to,
            )
            
            logger.info(f"SMS sent: {message.sid} to {to}")
            
            # Log to database if session provided
            if db and session_id:
                await self._log_notification(
                    db=db,
                    session_id=session_id,
                    notification_type=notification_type,
                    channel="sms",
                    recipient=to,
                    body=body,
                    status="sent",
                    external_id=message.sid,
                )
            
            return {
                "success": True,
                "message_sid": message.sid,
                "error": None,
            }
            
        except Exception as e:
            logger.error(f"SMS send failed: {e}")
            
            # Log failure to database
            if db and session_id:
                await self._log_notification(
                    db=db,
                    session_id=session_id,
                    notification_type=notification_type,
                    channel="sms",
                    recipient=to,
                    body=body,
                    status="failed",
                    error_message=str(e),
                )
            
            return {
                "success": False,
                "message_sid": None,
                "error": str(e),
            }
    
    async def send_welcome_sms(
        self,
        db: AsyncSession,
        session_id: UUID,
        guest_name: str,
        guest_phone: str,
        property_name: str,
        concierge_url: str,
    ) -> dict:
        """
        Send welcome SMS with concierge link.
        """
        body = f"""Hi {guest_name}! 🏖️

Welcome to {property_name}! I'm Coral, your Beach Habitats concierge.

I'm here to help with anything you need - restaurant recommendations, beach chairs, local tips, and more.

Tap here to chat: {concierge_url}

Have a wonderful stay!"""

        return await self.send_sms(
            to=guest_phone,
            body=body,
            db=db,
            session_id=session_id,
            notification_type="welcome",
        )
    
    async def send_extend_stay_offer(
        self,
        db: AsyncSession,
        session_id: UUID,
        guest_name: str,
        guest_phone: str,
        property_name: str,
        extra_night_date: str,
        discount_pct: int = 10,
    ) -> dict:
        """
        Send extend stay offer SMS.
        """
        body = f"""Hi {guest_name}! 🌟

Not ready to leave {property_name}? Good news - we don't have anyone arriving tomorrow!

🎁 Special offer: {discount_pct}% off if you'd like to stay {extra_night_date}.

Reply YES if interested and I'll take care of the details!"""

        return await self.send_sms(
            to=guest_phone,
            body=body,
            db=db,
            session_id=session_id,
            notification_type="extend_offer",
        )
    
    async def send_checkin_reminder(
        self,
        db: AsyncSession,
        session_id: UUID,
        guest_name: str,
        guest_phone: str,
        property_name: str,
        checkin_time: str = "4:00 PM",
        door_code_note: str = "Your door code will be sent shortly before check-in.",
    ) -> dict:
        """
        Send check-in day reminder SMS.
        """
        body = f"""Hi {guest_name}! 🎉

Today's the day! Check-in at {property_name} is at {checkin_time}.

{door_code_note}

Questions? Just reply to this message or tap the link I sent earlier to chat.

Safe travels!"""

        return await self.send_sms(
            to=guest_phone,
            body=body,
            db=db,
            session_id=session_id,
            notification_type="checkin_reminder",
        )
    
    async def send_checkout_reminder(
        self,
        db: AsyncSession,
        session_id: UUID,
        guest_name: str,
        guest_phone: str,
        property_name: str,
        checkout_time: str = "10:00 AM",
    ) -> dict:
        """
        Send checkout reminder SMS.
        """
        body = f"""Good morning {guest_name}! ☀️

Just a reminder that checkout at {property_name} is at {checkout_time}.

Before you go:
• Start the dishwasher
• Take out the trash
• Leave towels in the tub

Thank you for staying with Beach Habitats! We hope to see you again soon. 🏖️"""

        return await self.send_sms(
            to=guest_phone,
            body=body,
            db=db,
            session_id=session_id,
            notification_type="checkout_reminder",
        )
    
    def _normalize_phone(self, phone: str) -> str:
        """Normalize phone number to E.164 format."""
        # Remove common formatting
        phone = phone.replace(" ", "").replace("-", "").replace("(", "").replace(")", "").replace(".", "")
        
        # Add +1 for US numbers if not present
        if not phone.startswith("+"):
            if phone.startswith("1") and len(phone) == 11:
                phone = "+" + phone
            elif len(phone) == 10:
                phone = "+1" + phone
            else:
                phone = "+" + phone
        
        return phone
    
    async def _log_notification(
        self,
        db: AsyncSession,
        session_id: UUID,
        notification_type: str,
        channel: str,
        recipient: str,
        body: str,
        status: str,
        external_id: Optional[str] = None,
        error_message: Optional[str] = None,
    ):
        """Log notification to database."""
        from db.models.concierge_sessions import ConciergeNotificationModel
        from uuid import uuid4
        
        notification = ConciergeNotificationModel(
            notification_id=uuid4(),
            session_id=session_id,
            notification_type=notification_type,
            channel=channel,
            recipient=recipient,
            body=body,
            status=status,
            external_id=external_id,
            error_message=error_message,
            sent_at=datetime.utcnow() if status == "sent" else None,
        )
        
        db.add(notification)
        await db.commit()


# Singleton
_sms_service: Optional[SMSService] = None

def get_sms_service() -> SMSService:
    global _sms_service
    if _sms_service is None:
        _sms_service = SMSService()
    return _sms_service
