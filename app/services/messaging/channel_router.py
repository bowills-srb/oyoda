"""
Oyvoda Messaging Channel Router

Abstract messaging layer that routes outbound messages to the right channel
based on guest capability detection:

  Priority order (highest richness first):
    1. Apple Messages for Business (iMessage-native, rich bubbles, Apple Pay)
    2. RCS via Twilio (rich cards, quick replies, read receipts) — Android + Google Messages
    3. SMS fallback (plain text, universal, always works)

Design principles:
  - Never call Twilio directly from anywhere else — always go through this router
  - Channel is resolved per-guest, per-message, cached after first detection
  - All channels use the same canonical message format (ChannelMessage)
  - Add new channels here without touching any other service
  - Graceful degradation: if RCS fails → SMS, if ABM fails → RCS → SMS

Channel status (March 2026):
  - SMS:                 ✅ Live (existing SMSService)
  - RCS via Twilio:      🔧 Wired, requires Twilio RCS alpha access
  - Apple Business Msg:  🔧 Wired, requires Apple partner registration
  - WhatsApp via Twilio: 📋 Stub (international operators, future)

Environment variables required:
  TWILIO_ACCOUNT_SID      = AC...
  TWILIO_AUTH_TOKEN       = ...
  TWILIO_MESSAGING_SID    = MG... (Messaging Service SID — owns the from number pool)
  TWILIO_RCS_ENABLED      = true/false (gate RCS until Twilio approves your account)
  ABM_BUSINESS_ACCOUNT_ID = ... (Apple Business Register account ID)
  ABM_API_KEY             = ... (Apple Business Messages API key)
  ABM_API_SECRET          = ... (Apple Business Messages API secret)
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID

logger = logging.getLogger(__name__)


# =============================================================================
# CHANNEL ENUM
# =============================================================================

class MessageChannel(str, Enum):
    """
    Supported messaging channels, in priority order (richest first).
    """
    APPLE_MESSAGES = "apple_messages"   # iMessage / Apple Messages for Business
    RCS = "rcs"                          # Rich Communication Services (Android/Google)
    WHATSAPP = "whatsapp"                # WhatsApp Business (future, international)
    SMS = "sms"                          # Plain SMS — always available fallback


# =============================================================================
# CANONICAL MESSAGE FORMAT
# =============================================================================

@dataclass
class QuickReply:
    """
    A tappable quick-reply button shown below a message.
    Works natively in RCS and ABM. Falls back to numbered list in SMS.
    """
    label: str           # Text shown on button (≤25 chars for RCS)
    payload: str         # Value sent when tapped
    icon_url: Optional[str] = None  # Optional icon for RCS


@dataclass
class RichCard:
    """
    A rich card with image, title, description, and action buttons.
    RCS and ABM native. Rendered as plain text in SMS.
    """
    title: str
    description: Optional[str] = None
    image_url: Optional[str] = None
    buttons: List[QuickReply] = field(default_factory=list)


@dataclass
class ChannelMessage:
    """
    Canonical message format. Channel adapters translate this to channel-specific payloads.

    Usage:
        msg = ChannelMessage(
            body="🌊 Today: Yellow flag — great for walking. Water 68°F.",
            quick_replies=[
                QuickReply("WiFi Password", "wifi"),
                QuickReply("Beach Report", "beach"),
                QuickReply("Book Kayaks", "book_kayaks"),
            ],
        )
        await router.send(guest_phone, msg, session_id=session.id)
    """
    body: str                                       # Main message text (required)
    quick_replies: List[QuickReply] = field(default_factory=list)   # Optional quick-reply chips
    card: Optional[RichCard] = None                 # Optional rich card
    media_url: Optional[str] = None                 # Optional image/GIF URL
    operator_id: Optional[str] = None               # For branded sender ID in RCS
    is_transactional: bool = True                   # True = guest-initiated flow


@dataclass
class DeliveryResult:
    """
    Result of a send attempt.
    """
    success: bool
    channel: MessageChannel
    message_sid: Optional[str] = None      # Twilio SID, ABM message ID, etc.
    fallback_used: bool = False            # True if we fell back to a lower-richness channel
    original_channel: Optional[MessageChannel] = None  # Channel we tried first
    error: Optional[str] = None
    sent_at: datetime = field(default_factory=datetime.utcnow)


# =============================================================================
# BASE CHANNEL ADAPTER
# =============================================================================

class BaseChannelAdapter(ABC):
    """
    Abstract base for all channel adapters.
    Each adapter translates ChannelMessage → channel-specific API call.
    """

    @property
    @abstractmethod
    def channel(self) -> MessageChannel:
        ...

    @abstractmethod
    async def send(
        self,
        to: str,
        message: ChannelMessage,
    ) -> DeliveryResult:
        """Send a message. Raise on hard failures, return DeliveryResult on soft failures."""
        ...

    @abstractmethod
    async def check_capability(self, phone: str) -> bool:
        """
        Check if the destination number is capable of receiving this channel's messages.
        
        For RCS: query Twilio's capability API.
        For ABM: check if guest has Apple Messages intent URL click-through.
        For SMS: always True.
        
        Results should be cached — don't call this on every message.
        """
        ...


# =============================================================================
# SMS ADAPTER (existing Twilio SMS, always available)
# =============================================================================

class SMSAdapter(BaseChannelAdapter):
    """
    Plain SMS via Twilio. The universal fallback.
    Quick replies are rendered as a numbered list in the body.
    """

    @property
    def channel(self) -> MessageChannel:
        return MessageChannel.SMS

    async def send(self, to: str, message: ChannelMessage) -> DeliveryResult:
        try:
            from twilio.rest import Client
            account_sid = os.getenv("TWILIO_ACCOUNT_SID")
            auth_token = os.getenv("TWILIO_AUTH_TOKEN")
            messaging_sid = os.getenv("TWILIO_MESSAGING_SID")
            from_number = os.getenv("TWILIO_PHONE_NUMBER")

            if not account_sid or not auth_token:
                return DeliveryResult(
                    success=False,
                    channel=self.channel,
                    error="Twilio credentials not configured",
                )

            client = Client(account_sid, auth_token)

            # Render quick replies as numbered list in SMS body
            body = message.body
            if message.quick_replies:
                body += "\n\nReply:"
                for i, qr in enumerate(message.quick_replies, 1):
                    body += f"\n{i}. {qr.label}"

            # Rich card text fallback
            if message.card:
                body += f"\n\n{message.card.title}"
                if message.card.description:
                    body += f"\n{message.card.description}"

            send_kwargs: Dict[str, Any] = {"body": body, "to": to}
            if messaging_sid:
                send_kwargs["messaging_service_sid"] = messaging_sid
            elif from_number:
                send_kwargs["from_"] = from_number
            else:
                return DeliveryResult(success=False, channel=self.channel, error="No from number or messaging SID configured")

            msg = client.messages.create(**send_kwargs)

            return DeliveryResult(
                success=True,
                channel=self.channel,
                message_sid=msg.sid,
            )

        except Exception as e:
            logger.error(f"[SMS] Send failed to {to}: {e}")
            return DeliveryResult(success=False, channel=self.channel, error=str(e))

    async def check_capability(self, phone: str) -> bool:
        return True  # SMS always works


# =============================================================================
# RCS ADAPTER (Twilio RCS — requires Twilio RCS alpha access)
# =============================================================================

class RCSAdapter(BaseChannelAdapter):
    """
    RCS via Twilio.

    Requirements:
      1. Twilio account approved for RCS Business Messaging (alpha/beta program)
      2. RCS brand registered and approved (business name, logo, contact info)
      3. TWILIO_RCS_ENABLED=true in environment
      4. TWILIO_MESSAGING_SID must be an RCS-capable Messaging Service

    RCS features used:
      - Branded sender (business name + verified checkmark)
      - Quick reply chips (up to 11, shown below message)
      - Rich cards (image + title + description + buttons)
      - Read receipts
      - Typing indicators

    Fallback: If guest's device/carrier doesn't support RCS, Twilio automatically
    falls back to SMS — but we lose the rich features. The router logs this.

    Twilio RCS API reference:
      https://www.twilio.com/docs/sms/api/message-resource#rcs-messages
    """

    @property
    def channel(self) -> MessageChannel:
        return MessageChannel.RCS

    async def send(self, to: str, message: ChannelMessage) -> DeliveryResult:
        rcs_enabled = os.getenv("TWILIO_RCS_ENABLED", "false").lower() == "true"
        if not rcs_enabled:
            return DeliveryResult(
                success=False,
                channel=self.channel,
                error="RCS not enabled (set TWILIO_RCS_ENABLED=true when Twilio approves your account)",
            )

        try:
            from twilio.rest import Client
            account_sid = os.getenv("TWILIO_ACCOUNT_SID")
            auth_token = os.getenv("TWILIO_AUTH_TOKEN")
            messaging_sid = os.getenv("TWILIO_MESSAGING_SID")

            if not all([account_sid, auth_token, messaging_sid]):
                return DeliveryResult(
                    success=False,
                    channel=self.channel,
                    error="Twilio credentials or Messaging SID not configured",
                )

            client = Client(account_sid, auth_token)

            # Build RCS content SID or inline content
            # For now, using Twilio Content API approach (recommended for RCS)
            # Quick replies become suggestion chips
            
            rcs_body = message.body
            
            # Add quick reply suggestions
            # Twilio RCS sends these as "suggested_actions" in the content payload
            # For simplicity in this stub, we append them to body
            # Production: use Twilio Content API to create templates
            if message.quick_replies:
                rcs_body += "\n\n" + "  ".join([f"[{qr.label}]" for qr in message.quick_replies])

            send_kwargs: Dict[str, Any] = {
                "body": rcs_body,
                "to": f"rcs:{to}",  # Twilio RCS uses "rcs:" prefix
                "messaging_service_sid": messaging_sid,
            }

            # Add media if present
            if message.media_url:
                send_kwargs["media_url"] = [message.media_url]

            msg = client.messages.create(**send_kwargs)

            logger.info(f"[RCS] Sent to {to}: {msg.sid}")
            return DeliveryResult(
                success=True,
                channel=self.channel,
                message_sid=msg.sid,
            )

        except Exception as e:
            logger.error(f"[RCS] Send failed to {to}: {e}")
            return DeliveryResult(success=False, channel=self.channel, error=str(e))

    async def check_capability(self, phone: str) -> bool:
        """
        Check if phone number supports RCS.
        Twilio provides a lookup API for this — requires a Lookup API call.
        Returns True if the carrier/device supports RCS.
        """
        try:
            from twilio.rest import Client
            account_sid = os.getenv("TWILIO_ACCOUNT_SID")
            auth_token = os.getenv("TWILIO_AUTH_TOKEN")

            if not account_sid or not auth_token:
                return False

            client = Client(account_sid, auth_token)

            # Twilio Channel Eligibility check
            # https://www.twilio.com/docs/lookup/v2-api/channel-eligibility
            lookup = client.lookups.v2.phone_numbers(phone).fetch(
                fields=["line_type_intelligence", "identity_match"]
            )

            # RCS eligibility is returned in channel_eligibility
            # This is in Twilio beta — field name may change
            channels = getattr(lookup, "channel_eligibility", {}) or {}
            rcs_eligible = channels.get("rcs", {}).get("eligible", False)

            logger.debug(f"[RCS] Capability check {phone}: {rcs_eligible}")
            return bool(rcs_eligible)

        except Exception as e:
            logger.warning(f"[RCS] Capability check failed for {phone}: {e}")
            return False  # Fail safe — fall back to SMS


# =============================================================================
# APPLE MESSAGES FOR BUSINESS ADAPTER
# =============================================================================

class AppleMessagesAdapter(BaseChannelAdapter):
    """
    Apple Messages for Business (ABM).

    Requirements:
      1. Registered as an Apple Messages for Business partner
         Apply at: https://register.apple.com/business/messaging/
      2. Business account approved (usually 4–8 weeks)
      3. ABM_BUSINESS_ACCOUNT_ID, ABM_API_KEY, ABM_API_SECRET configured
      4. Webhook endpoint registered at /webhooks/apple-messages

    ABM features available:
      - iMessage-native experience (blue bubbles)
      - Rich interactive messages (list pickers, time pickers, Apple Pay)
      - Business Chat button on Safari, Maps, Siri, Spotlight
      - End-to-end encrypted
      - Typing indicators, read receipts

    How guests initiate:
      - Business Chat button on your website (JavaScript snippet)
      - Direct URL: https://bcrw.apple.com/urn:biz:{ACCOUNT_ID}
      - Deep link from RCS/SMS: "Chat with us in iMessage → [link]"

    Note:
      ABM is pull-based for initial contact — guests initiate.
      Once a conversation is open, you can send proactively for 24h.
      After 24h, only transactional messages are allowed.
      
    Apple Messages API docs:
      https://developer.apple.com/documentation/businesschatapi
    """

    @property
    def channel(self) -> MessageChannel:
        return MessageChannel.APPLE_MESSAGES

    async def send(self, to: str, message: ChannelMessage) -> DeliveryResult:
        """
        Send via Apple Messages for Business.

        'to' here is the conversation_id, not a phone number —
        ABM uses conversation IDs assigned when a guest initiates.
        Phone numbers are not used directly in ABM.
        
        The router handles this: when ABM is available, 'to' becomes
        the conversation_id stored in the guest session.
        """
        abm_account_id = os.getenv("ABM_BUSINESS_ACCOUNT_ID")
        abm_api_key = os.getenv("ABM_API_KEY")
        abm_api_secret = os.getenv("ABM_API_SECRET")

        if not all([abm_account_id, abm_api_key, abm_api_secret]):
            return DeliveryResult(
                success=False,
                channel=self.channel,
                error="Apple Messages for Business credentials not configured",
            )

        try:
            import httpx
            import base64
            import json
            import uuid

            # ABM uses JWT-based auth
            # Production: use proper JWT library with ABM signing requirements
            auth_header = base64.b64encode(f"{abm_api_key}:{abm_api_secret}".encode()).decode()

            # Build ABM interactive message payload
            payload: Dict[str, Any] = {
                "v": "1.0",
                "id": str(uuid.uuid4()),
                "sourceId": abm_account_id,
                "destinationId": to,  # conversation_id from guest session
                "type": "interactive",
                "interactiveData": {
                    "data": {
                        "body": {
                            "sections": [
                                {
                                    "multipleSelection": False,
                                    "items": [
                                        {
                                            "title": message.body,
                                            "style": "default",
                                        }
                                    ]
                                }
                            ]
                        }
                    }
                }
            }

            # Add quick replies as list picker items if present
            if message.quick_replies:
                # Convert to ABM list picker format
                items = [
                    {
                        "title": qr.label,
                        "identifier": qr.payload,
                        "style": "default",
                    }
                    for qr in message.quick_replies
                ]
                payload["interactiveData"]["data"]["body"]["sections"][0]["items"] = items

            # Simpler text message if no quick replies
            if not message.quick_replies and not message.card:
                payload = {
                    "v": "1.0",
                    "id": str(uuid.uuid4()),
                    "sourceId": abm_account_id,
                    "destinationId": to,
                    "type": "text",
                    "body": message.body,
                }

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://mspapi.apple.com/api/v1/message/send",
                    json=payload,
                    headers={
                        "Authorization": f"Basic {auth_header}",
                        "Content-Type": "application/json",
                    },
                    timeout=10.0,
                )

            if response.status_code == 200:
                result_data = response.json()
                logger.info(f"[ABM] Sent to conversation {to}")
                return DeliveryResult(
                    success=True,
                    channel=self.channel,
                    message_sid=result_data.get("id"),
                )
            else:
                error_msg = f"ABM API returned {response.status_code}: {response.text}"
                logger.error(f"[ABM] {error_msg}")
                return DeliveryResult(
                    success=False,
                    channel=self.channel,
                    error=error_msg,
                )

        except Exception as e:
            logger.error(f"[ABM] Send failed to {to}: {e}")
            return DeliveryResult(success=False, channel=self.channel, error=str(e))

    async def check_capability(self, phone: str) -> bool:
        """
        ABM capability is determined by whether the guest has initiated
        an ABM conversation (i.e., we have a conversation_id for them).
        
        This is tracked in the guest session: session.abm_conversation_id
        
        We don't check phone number — ABM is pull-initiated.
        Returns True only if a conversation_id exists for this guest.
        """
        # In practice: look up session by phone, check for abm_conversation_id
        # Stub returns False until ABM is fully integrated
        return False


# =============================================================================
# CAPABILITY CACHE
# =============================================================================

class CapabilityCache:
    """
    In-memory cache for channel capability checks.
    
    Don't hit Twilio Lookup API on every message — cache results.
    TTL: 24 hours (capabilities rarely change within a stay).
    
    Production: replace with Redis for multi-instance deployments.
    """

    def __init__(self, ttl_seconds: int = 86400):  # 24 hours
        self._cache: Dict[str, Dict[str, Any]] = {}  # phone -> {channel: bool, expires: datetime}
        self.ttl = ttl_seconds

    def get(self, phone: str, channel: MessageChannel) -> Optional[bool]:
        if phone not in self._cache:
            return None
        entry = self._cache[phone].get(channel.value)
        if not entry:
            return None
        if datetime.utcnow().timestamp() > entry["expires"]:
            return None
        return entry["capable"]

    def set(self, phone: str, channel: MessageChannel, capable: bool) -> None:
        if phone not in self._cache:
            self._cache[phone] = {}
        self._cache[phone][channel.value] = {
            "capable": capable,
            "expires": datetime.utcnow().timestamp() + self.ttl,
        }


# =============================================================================
# CHANNEL ROUTER — the single entry point for all outbound messaging
# =============================================================================

class ChannelRouter:
    """
    The single entry point for all outbound guest messaging.

    Usage:
        router = get_channel_router()

        # Simple text
        result = await router.send(guest_phone, ChannelMessage("Your door code is 4821."))

        # Rich message with quick replies
        result = await router.send(
            guest_phone,
            ChannelMessage(
                body="🌊 Good morning! Yellow flag today — great for a walk.",
                quick_replies=[
                    QuickReply("Beach Report", "beach"),
                    QuickReply("Host Favorites", "favorites"),
                    QuickReply("Book Kayaks", "kayaks"),
                ],
            )
        )

        if result.fallback_used:
            logger.info(f"Fell back from {result.original_channel} to {result.channel}")

    Channel selection:
        Apple Messages for Business → if guest has open ABM conversation
        RCS (Twilio)                → if guest phone supports RCS + TWILIO_RCS_ENABLED=true
        SMS (Twilio)                → always available fallback
    """

    def __init__(self):
        self._adapters: Dict[MessageChannel, BaseChannelAdapter] = {
            MessageChannel.APPLE_MESSAGES: AppleMessagesAdapter(),
            MessageChannel.RCS: RCSAdapter(),
            MessageChannel.SMS: SMSAdapter(),
        }
        self._capability_cache = CapabilityCache()

        # Priority order: RCS first (broader reach, carrier-native on Android),
        # then Apple Messages for Business (iMessage, iPhone-initiated only),
        # then SMS universal fallback.
        self._priority: List[MessageChannel] = [
            MessageChannel.RCS,
            MessageChannel.APPLE_MESSAGES,
            MessageChannel.SMS,
        ]

    async def send(
        self,
        to: str,
        message: ChannelMessage,
        preferred_channel: Optional[MessageChannel] = None,
        session_id: Optional[UUID] = None,
    ) -> DeliveryResult:
        """
        Send a message to a guest, routing to the best available channel.

        Args:
            to: Phone number in E.164 format (or conversation_id if ABM is the preferred channel)
            message: Canonical ChannelMessage
            preferred_channel: Override channel selection (e.g., to force SMS for operator alerts)
            session_id: Optional session ID for logging

        Returns:
            DeliveryResult with channel used, SID, and fallback info
        """
        to = self._normalize_phone(to)

        channels_to_try = (
            [preferred_channel] + [c for c in self._priority if c != preferred_channel]
            if preferred_channel
            else self._priority
        )

        first_channel_tried = None

        for channel in channels_to_try:
            adapter = self._adapters.get(channel)
            if not adapter:
                continue

            # Check capability (cached)
            capable = await self._check_capability_cached(to, channel, adapter)
            if not capable:
                logger.debug(f"[Router] {channel} not capable for {to}, trying next")
                continue

            if first_channel_tried is None:
                first_channel_tried = channel

            result = await adapter.send(to, message)

            if result.success:
                if channel != first_channel_tried:
                    result.fallback_used = True
                    result.original_channel = first_channel_tried
                logger.info(f"[Router] Delivered via {channel} to {to} (SID: {result.message_sid})")
                return result
            else:
                logger.warning(f"[Router] {channel} failed for {to}: {result.error}, trying fallback")

        # All channels failed
        logger.error(f"[Router] All channels failed for {to}")
        return DeliveryResult(
            success=False,
            channel=MessageChannel.SMS,
            error="All messaging channels failed",
            fallback_used=True,
            original_channel=first_channel_tried,
        )

    async def send_operator_alert(
        self,
        operator_phone: str,
        body: str,
    ) -> DeliveryResult:
        """
        Send a plain SMS alert to an operator (not a guest).
        Operators always get SMS — no rich channels for internal alerts.
        """
        return await self.send(
            to=operator_phone,
            message=ChannelMessage(body=body, is_transactional=True),
            preferred_channel=MessageChannel.SMS,
        )

    async def send_morning_brief(
        self,
        guest_phone: str,
        property_name: str,
        env_status: str,
        env_narrative: str,
        event_teaser: Optional[str] = None,
    ) -> DeliveryResult:
        """
        Send the proactive morning brief to an arriving or in-stay guest.
        Includes beach/weather status and event teaser.
        """
        body = f"Good morning from {property_name}! 🌴\n\n{env_status}: {env_narrative}"
        if event_teaser:
            body += f"\n\n🎭 {event_teaser}"
        body += "\n\nAsk me anything — I'm your 24/7 co-host."

        return await self.send(
            to=guest_phone,
            message=ChannelMessage(
                body=body,
                quick_replies=[
                    QuickReply("Beach Report", "beach"),
                    QuickReply("Host's Favorites", "favorites"),
                    QuickReply("What's Happening", "events"),
                ],
            ),
        )

    async def send_maintenance_eta(
        self,
        guest_phone: str,
        vendor_name: str,
        eta_minutes: int,
        issue_description: str,
    ) -> DeliveryResult:
        """
        Send maintenance dispatch ETA to guest.
        """
        body = (
            f"🔧 Update on your {issue_description}:\n\n"
            f"{vendor_name} is on the way — ETA approximately {eta_minutes} minutes.\n\n"
            f"I'll let you know when they arrive. Any other questions?"
        )
        return await self.send(
            to=guest_phone,
            message=ChannelMessage(body=body),
        )

    async def _check_capability_cached(
        self,
        phone: str,
        channel: MessageChannel,
        adapter: BaseChannelAdapter,
    ) -> bool:
        cached = self._capability_cache.get(phone, channel)
        if cached is not None:
            return cached
        result = await adapter.check_capability(phone)
        self._capability_cache.set(phone, channel, result)
        return result

    def _normalize_phone(self, phone: str) -> str:
        phone = (
            phone.replace(" ", "")
                 .replace("-", "")
                 .replace("(", "")
                 .replace(")", "")
                 .replace(".", "")
        )
        if not phone.startswith("+"):
            if phone.startswith("1") and len(phone) == 11:
                phone = "+" + phone
            elif len(phone) == 10:
                phone = "+1" + phone
            else:
                phone = "+" + phone
        return phone


# =============================================================================
# WEBHOOK HANDLER STUBS
# =============================================================================

class InboundMessageHandler:
    """
    Handles inbound messages from all channels.
    Each channel delivers inbound messages differently — this normalizes them.

    Wire these endpoints in your FastAPI app:
      POST /webhooks/twilio/sms        → handle_twilio_inbound()
      POST /webhooks/twilio/rcs        → handle_twilio_inbound() (same handler, Twilio adds channel field)
      POST /webhooks/apple-messages    → handle_apple_messages_inbound()
    """

    @staticmethod
    async def handle_twilio_inbound(form_data: Dict[str, Any]) -> str:
        """
        Handle inbound SMS/RCS from Twilio webhook.
        Twilio posts form-encoded data to your webhook URL.
        The 'Channel' field distinguishes SMS from RCS ('rcs').

        Routes through the existing VoicePod pipeline (same as sms.py),
        giving RCS the same AI logic as SMS with no duplication.

        Required response: TwiML XML
        """
        from_number = form_data.get("From", "").replace("rcs:", "")  # Strip rcs: prefix if present
        body = form_data.get("Body", "").strip()
        channel = form_data.get("Channel", "sms")

        logger.info(f"[Inbound/{channel.upper()}] {from_number}: {body[:80]}")

        try:
            # Re-use the full VoicePod routing from sms.py
            # This gives RCS identical AI quality and escalation policy as SMS
            from app.api.v1.endpoints.sms import (
                _lookup_session_by_phone,
                _generate_via_voice_pod,
            )
            from app.db.session import AsyncSessionLocal

            async with AsyncSessionLocal() as db:
                db_row = await _lookup_session_by_phone(from_number, db)
                if db_row:
                    token = getattr(db_row, "token", None)
                    response_text = await _generate_via_voice_pod(body, token, db_row, db)
                else:
                    response_text = (
                        "Hi! I don't have your booking on file yet. "
                        "Please contact your host for your personalized co-host link."
                    )

            twiml = (
                '<?xml version="1.0" encoding="UTF-8">'
                f"<Response><Message>{response_text}</Message></Response>"
            )
            return twiml

        except Exception as e:
            logger.error(f"[Inbound/{channel.upper()}] Processing error: {e}", exc_info=True)
            return (
                '<?xml version="1.0" encoding="UTF-8">'
                "<Response><Message>Something went wrong. Please contact your host directly.</Message></Response>"
            )

    @staticmethod
    async def handle_apple_messages_inbound(payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle inbound message from Apple Messages for Business webhook.
        Apple sends JSON to your registered webhook endpoint.

        Required response: 200 OK with empty JSON body
        """
        conversation_id = payload.get("destinationId", "")
        source_id = payload.get("sourceId", "")  # Guest's anonymous ABM ID
        message_type = payload.get("type", "")
        body = ""

        if message_type == "text":
            body = payload.get("body", "")
        elif message_type == "interactive":
            # Quick reply / list picker selection
            reply_id = payload.get("interactiveData", {}).get("receivedMessage", {}).get("replyIdentifier", "")
            body = reply_id  # Use the payload identifier as the intent

        logger.info(f"[Inbound/ABM] conversation={conversation_id}: {body[:50]}")

        if body:
            try:
                # Look up guest session by ABM conversation ID
                # ABM doesn't give us a phone number — we match on abm_conversation_id stored in session
                from app.api.v1.endpoints.sms import _generate_via_voice_pod
                from app.db.session import AsyncSessionLocal
                from sqlalchemy import text

                async with AsyncSessionLocal() as db:
                    result = await db.execute(
                        text("""
                            SELECT * FROM concierge_guest_sessions
                            WHERE abm_conversation_id = :cid
                              AND status != 'expired'
                            ORDER BY created_at DESC LIMIT 1
                        """),
                        {"cid": conversation_id},
                    )
                    db_row = result.fetchone()

                    if db_row:
                        token = getattr(db_row, "token", None)
                        # Generate response via VoicePod — same AI pipeline as SMS/RCS
                        response_text = await _generate_via_voice_pod(body, token, db_row, db)

                        # Send response back via Apple Messages adapter
                        router = get_channel_router()
                        await router._adapters[MessageChannel.APPLE_MESSAGES].send(
                            to=conversation_id,
                            message=ChannelMessage(body=response_text),
                        )
                    else:
                        logger.warning(f"[Inbound/ABM] No session for conversation {conversation_id}")

            except Exception as e:
                logger.error(f"[Inbound/ABM] Processing error: {e}", exc_info=True)

        return {}


# =============================================================================
# SINGLETON
# =============================================================================

_channel_router: Optional[ChannelRouter] = None


def get_channel_router() -> ChannelRouter:
    global _channel_router
    if _channel_router is None:
        _channel_router = ChannelRouter()
    return _channel_router
