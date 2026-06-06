"""
Guest SMS/Email Notification Service

Sends personalized concierge links to guests via:
- SMS (Twilio)
- Email (SendGrid)

Triggered when:
- New reservation synced from Escapia
- Manual send from operator dashboard
- Scheduled reminders (pre-arrival, check-in day)
"""

import logging
from dataclasses import dataclass
from datetime import datetime, date
from typing import Optional, List
from enum import Enum
import httpx

logger = logging.getLogger(__name__)


class NotificationType(str, Enum):
    WELCOME = "welcome"              # Initial link after booking
    PRE_ARRIVAL = "pre_arrival"      # 3 days before check-in
    CHECKIN_DAY = "checkin_day"      # Morning of check-in
    DURING_STAY = "during_stay"      # Mid-stay check-in
    CHECKOUT_REMINDER = "checkout"   # Morning of checkout


@dataclass
class SMSConfig:
    """Twilio configuration"""
    account_sid: str
    auth_token: str
    from_number: str  # Your Twilio number


@dataclass
class EmailConfig:
    """SendGrid configuration"""
    api_key: str
    from_email: str = "concierge@oyvoda.com"
    from_name: str = "Oyvoda Concierge"


class GuestNotificationService:
    """
    Sends personalized concierge links to guests.
    
    The link format is: https://your-domain.com/c/{token}
    """
    
    def __init__(
        self,
        sms_config: Optional[SMSConfig] = None,
        email_config: Optional[EmailConfig] = None,
        base_url: Optional[str] = None,
    ):
        import os
        # Resolve base_url: arg > env > settings > localhost fallback
        if base_url:
            self.BASE_URL = base_url.rstrip("/")
        elif os.getenv("BASE_URL"):
            self.BASE_URL = os.getenv("BASE_URL").rstrip("/")
        else:
            try:
                from app.core.config import get_settings
                self.BASE_URL = get_settings().base_url.rstrip("/")
            except Exception:
                self.BASE_URL = "http://localhost:8000"
        self.sms_config = sms_config
        self.email_config = email_config
    
    def get_concierge_url(self, token: str) -> str:
        """Generate the guest concierge URL"""
        return f"{self.BASE_URL}/c/{token}"
    
    # =========================================================================
    # SMS Messages
    # =========================================================================
    
    def _get_sms_message(
        self,
        notification_type: NotificationType,
        guest_name: str,
        property_name: str,
        concierge_url: str,
        check_in: Optional[date] = None,
    ) -> str:
        """Generate SMS message based on notification type"""
        
        if notification_type == NotificationType.WELCOME:
            return (
                f"Hi {guest_name}! 🏖️ We're excited to host you at {property_name}.\n\n"
                f"Meet Oyvo, your personal beach concierge - she knows everything about "
                f"your property and the 30A area:\n\n"
                f"{concierge_url}\n\n"
                f"Save this link - Oyvo is available 24/7 for any questions!"
            )
        
        elif notification_type == NotificationType.PRE_ARRIVAL:
            return (
                f"Hi {guest_name}! Your beach getaway at {property_name} is almost here! 🌊\n\n"
                f"Questions about your trip? Chat with Coral anytime:\n"
                f"{concierge_url}"
            )
        
        elif notification_type == NotificationType.CHECKIN_DAY:
            return (
                f"Welcome to 30A, {guest_name}! 🏖️\n\n"
                f"{property_name} is ready for you. Need check-in help, WiFi, or local tips?\n\n"
                f"Chat with Coral: {concierge_url}"
            )
        
        elif notification_type == NotificationType.DURING_STAY:
            return (
                f"Hi {guest_name}! How's your stay at {property_name}?\n\n"
                f"Need restaurant recs, beach tips, or help with anything?\n"
                f"{concierge_url}"
            )
        
        elif notification_type == NotificationType.CHECKOUT_REMINDER:
            return (
                f"Hi {guest_name}, checkout is today at {property_name}.\n\n"
                f"Questions about checkout or need late checkout? Ask Coral:\n"
                f"{concierge_url}\n\n"
                f"Thanks for staying with us! 🐚"
            )
        
        # Default
        return (
            f"Hi {guest_name}! Your Beach Habitats concierge is ready to help:\n"
            f"{concierge_url}"
        )
    
    # =========================================================================
    # Send SMS
    # =========================================================================
    
    async def send_sms(
        self,
        to_number: str,
        message: str,
    ) -> dict:
        """
        Send a message to a guest via the ChannelRouter.

        The router selects the best available channel automatically:
          Apple Messages for Business → RCS (if Twilio RCS enabled) → SMS fallback

        All Twilio/ABM credentials and channel logic live in channel_router.py.
        Nothing here calls Twilio directly.
        """
        try:
            from app.services.messaging.channel_router import (
                get_channel_router,
                ChannelMessage,
            )
            router = get_channel_router()
            result = await router.send(
                to=to_number,
                message=ChannelMessage(body=message),
            )
            if result.success:
                status = "sent"
                if result.fallback_used:
                    logger.info(
                        f"[Notification] Fell back from {result.original_channel} "
                        f"to {result.channel} for {to_number}"
                    )
                return {"status": status, "sid": result.message_sid, "channel": result.channel}
            else:
                logger.error(f"[Notification] All channels failed for {to_number}: {result.error}")
                return {"status": "failed", "error": result.error}
        except Exception as e:
            logger.error(f"[Notification] send_sms exception for {to_number}: {e}")
            return {"status": "failed", "error": str(e)}
    
    # =========================================================================
    # Send Email
    # =========================================================================
    
    async def send_email(
        self,
        to_email: str,
        to_name: str,
        subject: str,
        html_content: str,
    ) -> dict:
        """Send email via SendGrid"""
        if not self.email_config:
            logger.warning("Email config not set, skipping email")
            return {"status": "skipped", "reason": "no_config"}
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.sendgrid.com/v3/mail/send",
                    headers={
                        "Authorization": f"Bearer {self.email_config.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "personalizations": [{
                            "to": [{"email": to_email, "name": to_name}],
                            "subject": subject,
                        }],
                        "from": {
                            "email": self.email_config.from_email,
                            "name": self.email_config.from_name,
                        },
                        "content": [{"type": "text/html", "value": html_content}],
                    },
                    timeout=10.0,
                )
                response.raise_for_status()
                
                logger.info(f"Email sent to {to_email}")
                return {"status": "sent"}
                
        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {e}")
            return {"status": "failed", "error": str(e)}
    
    # =========================================================================
    # High-Level Send Functions
    # =========================================================================
    
    async def send_welcome_notification(
        self,
        session,  # GuestSession
        send_sms: bool = True,
        send_email: bool = True,
        db_session=None,  # Optional AsyncSession for generating join token
    ) -> dict:
        """
        Send welcome notification with concierge link.
        Includes a group share link so the lead guest can invite their party.
        Called when a new reservation is created/synced.
        """
        url = self.get_concierge_url(session.token)
        results = {}

        # Build group share link if we have a DB session
        group_invite_line = ""
        if db_session and hasattr(session, "session_id") and session.session_id:
            try:
                from app.services.concierge.group_session import (
                    get_group_session_service,
                    build_group_join_url,
                    build_group_invite_text,
                )
                grp_svc = get_group_session_service()
                join_token = await grp_svc.get_or_create_join_token(
                    db_session, session.session_id
                )
                join_url = build_group_join_url(join_token, self.BASE_URL)
                concierge_name = getattr(session, "concierge_name", "Oyvo")
                concierge_emoji = getattr(session, "concierge_emoji", "🐚")
                group_invite_line = "\n" + build_group_invite_text(
                    join_url, concierge_name, concierge_emoji
                )
            except Exception as _ge:
                logger.debug("[Notification] Group join link skipped: %s", _ge)

        # SMS
        if send_sms and session.guest_phone:
            message = self._get_sms_message(
                NotificationType.WELCOME,
                session.guest_first_name,
                session.property_name,
                url,
                session.check_in,
            ) + group_invite_line
            results["sms"] = await self.send_sms(session.guest_phone, message)

        # Email
        if send_email and session.guest_email:
            subject = f"🐚 Meet Oyvo, Your Beach Concierge for {session.property_name}"
            html = self._get_welcome_email_html(
                session.guest_first_name,
                session.property_name,
                url,
                session.check_in,
                session.check_out,
            )
            results["email"] = await self.send_email(
                session.guest_email,
                session.guest_name,
                subject,
                html,
            )

        return results
    
    async def send_checkin_notification(self, session) -> dict:
        """Send check-in day notification (SMS only for immediacy)"""
        url = self.get_concierge_url(session.token)
        message = self._get_sms_message(
            NotificationType.CHECKIN_DAY,
            session.guest_first_name,
            session.property_name,
            url,
        )
        
        if session.guest_phone:
            return {"sms": await self.send_sms(session.guest_phone, message)}
        return {"status": "skipped", "reason": "no_phone"}
    
    # =========================================================================
    # Email Templates
    # =========================================================================
    
    def _get_welcome_email_html(
        self,
        guest_name: str,
        property_name: str,
        concierge_url: str,
        check_in: date,
        check_out: date,
    ) -> str:
        """Generate branded welcome email HTML"""
        return f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f8fafc;">
    <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
        
        <!-- Header with Logo -->
        <div style="text-align: center; padding: 30px 0;">
            <img src="https://oyvoda.com/static/logo.png" alt="Oyvoda" style="height: 60px; width: auto;">
        </div>
        
        <!-- Main Card -->
        <div style="background: white; border-radius: 16px; overflow: hidden; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
            
            <!-- Hero -->
            <div style="background: linear-gradient(135deg, #0ea5e9 0%, #0284c7 100%); color: white; padding: 40px 30px; text-align: center;">
                <h1 style="margin: 0 0 10px 0; font-size: 28px;">Welcome, {guest_name}!</h1>
                <p style="margin: 0; opacity: 0.9; font-size: 16px;">Your beach getaway awaits</p>
            </div>
            
            <!-- Content -->
            <div style="padding: 30px;">
                <p style="font-size: 16px; color: #334155; line-height: 1.6;">
                    We're thrilled to host you at <strong>{property_name}</strong>!
                </p>
                
                <!-- Concierge Card -->
                <div style="background: #f0f9ff; border-radius: 12px; padding: 24px; margin: 24px 0; text-align: center;">
                    <div style="font-size: 48px; margin-bottom: 12px;">🐚</div>
                    <h2 style="margin: 0 0 8px 0; color: #0369a1; font-size: 22px;">Meet Oyvo</h2>
                    <p style="margin: 0 0 20px 0; color: #0284c7; font-size: 15px;">Your Personal Beach Concierge</p>
                    <a href="{concierge_url}" style="display: inline-block; background: #0ea5e9; color: white; padding: 14px 32px; border-radius: 30px; text-decoration: none; font-weight: 600; font-size: 16px;">
                        Chat with Oyvo
                    </a>
                </div>
                
                <p style="font-size: 15px; color: #475569; line-height: 1.6;">
                    Oyvo knows everything about your property and the 30A area. Ask her about:
                </p>
                <ul style="color: #475569; font-size: 15px; line-height: 1.8;">
                    <li>WiFi passwords & door codes</li>
                    <li>Restaurant recommendations</li>
                    <li>Beach tips & local favorites</li>
                    <li>Activities & attractions</li>
                    <li>Anything else you need!</li>
                </ul>
                
                <!-- Stay Details -->
                <div style="background: #f8fafc; border-radius: 8px; padding: 20px; margin-top: 24px;">
                    <h3 style="margin: 0 0 16px 0; color: #334155; font-size: 16px;">Your Stay Details</h3>
                    <table style="width: 100%; font-size: 15px; color: #475569;">
                        <tr>
                            <td style="padding: 8px 0;">Property</td>
                            <td style="padding: 8px 0; text-align: right; font-weight: 600; color: #334155;">{property_name}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0; border-top: 1px solid #e2e8f0;">Check-in</td>
                            <td style="padding: 8px 0; border-top: 1px solid #e2e8f0; text-align: right; font-weight: 600; color: #334155;">{check_in.strftime('%A, %B %d, %Y')}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0; border-top: 1px solid #e2e8f0;">Check-out</td>
                            <td style="padding: 8px 0; border-top: 1px solid #e2e8f0; text-align: right; font-weight: 600; color: #334155;">{check_out.strftime('%A, %B %d, %Y')}</td>
                        </tr>
                    </table>
                </div>
                
                <p style="font-size: 14px; color: #64748b; margin-top: 24px; text-align: center;">
                    Save Oyvo's link - she's available 24/7 throughout your stay!
                </p>
            </div>
        </div>
        
        <!-- Footer -->
        <div style="text-align: center; padding: 30px; color: #94a3b8; font-size: 13px;">
            <p style="margin: 0 0 8px 0;">Powered by Oyvoda · oyvoda.com</p>
            <p style="margin: 0;">AI-powered guest experience</p>
        </div>
    </div>
</body>
</html>
"""


# Singleton
_notification_service: Optional[GuestNotificationService] = None

def get_notification_service() -> GuestNotificationService:
    """Get or create notification service singleton"""
    global _notification_service
    if _notification_service is None:
        import os
        
        # Configure from environment
        sms_config = None
        if os.getenv("TWILIO_ACCOUNT_SID"):
            sms_config = SMSConfig(
                account_sid=os.getenv("TWILIO_ACCOUNT_SID"),
                auth_token=os.getenv("TWILIO_AUTH_TOKEN"),
                from_number=os.getenv("TWILIO_PHONE_NUMBER"),
            )
        
        email_config = None
        if os.getenv("SENDGRID_API_KEY"):
            email_config = EmailConfig(
                api_key=os.getenv("SENDGRID_API_KEY"),
                from_email=os.getenv("SENDGRID_FROM_EMAIL", "concierge@oyvoda.com"),
            )
        
        _notification_service = GuestNotificationService(
            sms_config=sms_config,
            email_config=email_config,
        )
    
    return _notification_service
