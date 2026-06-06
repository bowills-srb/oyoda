"""
Concierge SMS Service

Thin compatibility shim — all outbound messaging now flows through
app.services.messaging.channel_router.ChannelRouter, which handles:
  - Channel selection: Apple Messages for Business → RCS → SMS fallback
  - Twilio credential management
  - Capability detection and caching
  - Delivery result logging

This module is kept for backward compatibility with callers that imported
send_sms / send_welcome_sms / send_extend_stay_sms directly.
New code should import get_channel_router() directly.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


async def send_sms(
    to_phone: str,
    message: str,
    from_phone: Optional[str] = None,  # ignored — router manages from-number
) -> dict:
    """
    Send a message via ChannelRouter (SMS fallback guaranteed).

    Returns:
        {"success": bool, "message_sid": str | None, "channel": str, "error": str | None}
    """
    try:
        from app.services.messaging.channel_router import get_channel_router, ChannelMessage
        router = get_channel_router()
        result = await router.send(to=to_phone, message=ChannelMessage(body=message))
        return {
            "success": result.success,
            "message_sid": result.message_sid,
            "channel": result.channel,
            "error": result.error,
        }
    except Exception as e:
        logger.error(f"[SMS shim] send_sms failed for {to_phone}: {e}")
        return {"success": False, "message_sid": None, "channel": "sms", "error": str(e)}


async def send_welcome_sms(
    guest_phone: str,
    guest_name: str,
    property_name: str,
    concierge_url: str,
) -> dict:
    message = (
        f"Hi {guest_name}! 🏖️\n\n"
        f"Welcome to {property_name}! I'm your digital co-host — here to help with "
        f"anything you need during your stay.\n\n"
        f"Tap to chat: {concierge_url}\n\n"
        f"Save this link — I'm available 24/7!"
    )
    return await send_sms(guest_phone, message)


async def send_extend_stay_sms(
    guest_phone: str,
    guest_name: str,
    property_name: str,
    extra_night_date: str,
    concierge_url: str,
) -> dict:
    message = (
        f"Hi {guest_name}! 🌟\n\n"
        f"Not ready to leave {property_name}? Good news — we don't have anyone arriving tomorrow!\n\n"
        f"🎁 Add {extra_night_date} at 10% off.\n\n"
        f"Interested? Reply YES or tap here: {concierge_url}"
    )
    return await send_sms(guest_phone, message)


async def send_checkout_reminder_sms(
    guest_phone: str,
    guest_name: str,
    checkout_time: str,
    concierge_url: str,
) -> dict:
    message = (
        f"Good morning {guest_name}! ☀️\n\n"
        f"Just a reminder — checkout is at {checkout_time} today.\n\n"
        f"Please start the dishwasher and take out trash. Safe travels!\n\n"
        f"Questions? {concierge_url}"
    )
    return await send_sms(guest_phone, message)


async def send_checkin_reminder_sms(
    guest_phone: str,
    guest_name: str,
    property_name: str,
    checkin_time: str,
    door_code: str,
    concierge_url: str,
) -> dict:
    message = (
        f"Hi {guest_name}! 🎉\n\n"
        f"Today's the day — {property_name} is ready for you!\n\n"
        f"🕓 Check-in: {checkin_time}\n"
        f"🔑 Door Code: {door_code}\n\n"
        f"Safe travels! I'm here if you need anything:\n{concierge_url}"
    )
    return await send_sms(guest_phone, message)
