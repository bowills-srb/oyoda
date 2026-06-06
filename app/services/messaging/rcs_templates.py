"""
Oyvoda RCS Content Templates

RCS "cards" are created via the Twilio Content API, not inline in the message body.
Each template is a reusable Content SID (HX...) stored in the platform.

How it works:
  1. Call create_*_template() once during operator onboarding (or platform setup)
     → Twilio stores the template and returns a Content SID
  2. When sending a message, pass content_sid= to the Twilio Messages API
     → Twilio renders the card natively on RCS-capable devices
     → Falls back to plain text automatically on SMS

Template types used:
  twilio/card          — Single card: image + title + body + action buttons
  twilio/list-picker   — Scrollable list of selectable items
  twilio/call-to-action — Card with a single prominent CTA button

Content API docs: https://www.twilio.com/docs/content

All templates are idempotent — safe to call multiple times.
Templates are cached in operator_rcs_templates table after creation.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# TEMPLATE TYPE ENUM
# =============================================================================

class RCSTemplateType(str, Enum):
    MORNING_BRIEF         = "morning_brief"          # Daily arrival/in-stay brief
    MAINTENANCE_DISPATCH  = "maintenance_dispatch"   # Vendor dispatched + ETA
    MAINTENANCE_UPDATE    = "maintenance_update"     # Issue resolved
    VENDOR_BOOKING_CONFIRM = "vendor_booking_confirm" # Charter/chef/kayak confirmed
    LATE_CHECKOUT_OFFER   = "late_checkout_offer"    # Late checkout CTA
    EXTEND_STAY_OFFER     = "extend_stay_offer"      # Extra night offer
    ESCALATION_HANDOFF    = "escalation_handoff"     # Handing off to human
    QUICK_REPLY_MENU      = "quick_reply_menu"       # Opening menu with chips
    EVENT_ALERT           = "event_alert"            # Local event surfaced
    KB_GAP_FALLBACK       = "kb_gap_fallback"        # AI couldn't answer, offer options


# =============================================================================
# TEMPLATE DEFINITIONS
# =============================================================================

def morning_brief_template(
    property_name: str,
    env_status_label: str,
    env_narrative: str,
    flag_color: str = "🟡",
    event_teaser: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Daily morning brief card sent to arriving/in-stay guests.
    
    Card layout:
      [Oyvoda logo / property hero image]
      Title: Good morning from {property_name}!
      Body: {env_status} + {narrative}
      Chips: Beach Report | Host's Favorites | What's Happening
    """
    body = f"{flag_color} {env_status_label}\n\n{env_narrative}"
    if event_teaser:
        body += f"\n\n🎭 {event_teaser}"

    return {
        "friendly_name": f"oyvoda_morning_brief",
        "language": "en",
        "variables": {
            "1": property_name,
            "2": env_status_label,
            "3": env_narrative,
        },
        "types": {
            "twilio/card": {
                "title": f"Good morning from {property_name}! 🌴",
                "body": body,
                "actions": [
                    {"type": "QUICK_REPLY", "title": "Beach Report",     "id": "beach"},
                    {"type": "QUICK_REPLY", "title": "Host's Favorites", "id": "favorites"},
                    {"type": "QUICK_REPLY", "title": "What's Happening", "id": "events"},
                ],
            },
            # SMS fallback — plain text, no card
            "twilio/text": {
                "body": (
                    f"Good morning from {property_name}! 🌴\n\n"
                    f"{flag_color} {env_status_label}: {env_narrative}\n\n"
                    f"Reply: 1) Beach Report  2) Host Favorites  3) Events"
                    + (f"\n\n🎭 {event_teaser}" if event_teaser else "")
                ),
            },
        },
    }


def maintenance_dispatch_template(
    property_name: str,
    issue_description: str,
    vendor_name: str,
    eta_minutes: int,
) -> Dict[str, Any]:
    """
    Sent to guest when a maintenance vendor is dispatched.
    
    Card layout:
      🔧 [wrench icon visual]
      Title: Maintenance Update — {property_name}
      Body: {issue} — {vendor} is on the way. ETA ~{eta} min.
      Chips: Got it | Call me instead
    """
    return {
        "friendly_name": "oyvoda_maintenance_dispatch",
        "language": "en",
        "types": {
            "twilio/card": {
                "title": f"🔧 Maintenance Update — {property_name}",
                "body": (
                    f"We've got someone on the way for your {issue_description}.\n\n"
                    f"**{vendor_name}** is dispatched — estimated arrival in "
                    f"approximately **{eta_minutes} minutes**.\n\n"
                    f"I'll let you know when they're close."
                ),
                "actions": [
                    {"type": "QUICK_REPLY", "title": "Got it, thanks", "id": "ack_maintenance"},
                    {"type": "QUICK_REPLY", "title": "Ask a question",  "id": "question_maintenance"},
                ],
            },
            "twilio/text": {
                "body": (
                    f"🔧 Maintenance update for {property_name}:\n\n"
                    f"{vendor_name} dispatched for your {issue_description}. "
                    f"ETA ~{eta_minutes} min. I'll update you when they're close."
                ),
            },
        },
    }


def maintenance_resolved_template(
    property_name: str,
    issue_description: str,
    vendor_name: str,
) -> Dict[str, Any]:
    """Sent to guest when maintenance issue is marked resolved."""
    return {
        "friendly_name": "oyvoda_maintenance_resolved",
        "language": "en",
        "types": {
            "twilio/card": {
                "title": f"✅ Issue Resolved — {property_name}",
                "body": (
                    f"**{vendor_name}** has completed the {issue_description}. "
                    f"Everything should be working normally now.\n\n"
                    f"If the issue persists or you have any other questions, just let me know!"
                ),
                "actions": [
                    {"type": "QUICK_REPLY", "title": "All good, thanks", "id": "resolved_ack"},
                    {"type": "QUICK_REPLY", "title": "Still having issues", "id": "still_issue"},
                ],
            },
            "twilio/text": {
                "body": (
                    f"✅ {vendor_name} has resolved the {issue_description} at {property_name}. "
                    f"Reply if you're still having trouble."
                ),
            },
        },
    }


def vendor_booking_confirmed_template(
    vendor_name: str,
    service_type: str,
    booking_date: str,
    booking_time: str,
    details: str,
    vendor_phone: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Confirmation card when a vendor booking is made on behalf of guest.
    e.g. kayak rental, charter fishing, private chef.
    
    Card includes: vendor name, service, date/time, key details,
    and optionally a 'Call Vendor' button.
    """
    actions = [
        {"type": "QUICK_REPLY", "title": "Great, thanks!", "id": "booking_ack"},
    ]
    if vendor_phone:
        actions.append({
            "type": "PHONE_NUMBER",
            "title": f"Call {vendor_name}",
            "phone": vendor_phone,
        })

    return {
        "friendly_name": "oyvoda_vendor_booking_confirmed",
        "language": "en",
        "types": {
            "twilio/card": {
                "title": f"✅ {service_type} Confirmed!",
                "body": (
                    f"**{vendor_name}**\n"
                    f"📅 {booking_date} at {booking_time}\n\n"
                    f"{details}"
                ),
                "actions": actions,
            },
            "twilio/text": {
                "body": (
                    f"✅ {service_type} confirmed with {vendor_name}!\n"
                    f"{booking_date} at {booking_time}\n{details}"
                    + (f"\nVendor: {vendor_phone}" if vendor_phone else "")
                ),
            },
        },
    }


def late_checkout_offer_template(
    property_name: str,
    checkout_time: str = "10:00 AM",
    late_options: Optional[List[Dict]] = None,
) -> Dict[str, Any]:
    """
    Call-to-action card offering late checkout options.
    
    late_options format: [{"time": "12:00 PM", "price": 35}, {"time": "2:00 PM", "price": 65}]
    """
    if not late_options:
        late_options = [
            {"time": "12:00 PM", "price": 35},
            {"time": "2:00 PM", "price": 65},
        ]

    body = f"Standard checkout at {property_name} is {checkout_time}.\n\nNeed more time?\n\n"
    actions = []
    for opt in late_options:
        body += f"• Until {opt['time']}: ${opt['price']}\n"
        actions.append({
            "type": "QUICK_REPLY",
            "title": f"Until {opt['time']} (${opt['price']})",
            "id": f"late_checkout_{opt['time'].replace(':', '').replace(' ', '').lower()}",
        })
    actions.append({"type": "QUICK_REPLY", "title": "No thanks", "id": "checkout_no_change"})

    return {
        "friendly_name": "oyvoda_late_checkout_offer",
        "language": "en",
        "types": {
            "twilio/card": {
                "title": f"⏰ Late Checkout Available",
                "body": body.strip(),
                "actions": actions,
            },
            "twilio/text": {
                "body": (
                    f"⏰ Late checkout available at {property_name}!\n"
                    + "".join(f"• Until {o['time']}: ${o['price']}\n" for o in late_options)
                    + "\nReply with your preferred time to book."
                ),
            },
        },
    }


def extend_stay_offer_template(
    property_name: str,
    extra_night_date: str,
    discount_pct: int = 10,
) -> Dict[str, Any]:
    """Offer to extend stay for an extra night at discount."""
    return {
        "friendly_name": "oyvoda_extend_stay_offer",
        "language": "en",
        "types": {
            "twilio/card": {
                "title": f"🌟 Stay One More Night?",
                "body": (
                    f"We don't have anyone arriving tomorrow at {property_name}!\n\n"
                    f"Add **{extra_night_date}** at **{discount_pct}% off** — "
                    f"just tap below and we'll take care of the details."
                ),
                "actions": [
                    {"type": "QUICK_REPLY", "title": f"Yes, I'll stay!",   "id": "extend_yes"},
                    {"type": "QUICK_REPLY", "title": "No thanks",          "id": "extend_no"},
                ],
            },
            "twilio/text": {
                "body": (
                    f"🌟 Not ready to leave {property_name}? "
                    f"No one's arriving tomorrow — add {extra_night_date} at {discount_pct}% off! "
                    f"Reply YES to book or NO to pass."
                ),
            },
        },
    }


def event_alert_template(
    event_name: str,
    event_date: str,
    event_description: str,
    distance: str,
    price: str,
    event_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Local event surfaced proactively to guest.
    """
    actions = [
        {"type": "QUICK_REPLY", "title": "Tell me more",     "id": f"event_more"},
        {"type": "QUICK_REPLY", "title": "Not interested",   "id": f"event_skip"},
    ]
    if event_url:
        actions.insert(1, {
            "type": "URL",
            "title": "Get Tickets",
            "url": event_url,
        })

    return {
        "friendly_name": "oyvoda_event_alert",
        "language": "en",
        "types": {
            "twilio/card": {
                "title": f"🎭 {event_name}",
                "body": (
                    f"📅 {event_date}  •  📍 {distance} away  •  {price}\n\n"
                    f"{event_description}"
                ),
                "actions": actions,
            },
            "twilio/text": {
                "body": (
                    f"🎭 {event_name} — {event_date}\n"
                    f"{distance} away · {price}\n{event_description}"
                    + (f"\nInfo: {event_url}" if event_url else "")
                ),
            },
        },
    }


def kb_gap_fallback_template(
    guest_name: str,
    question_topic: str,
    property_name: str,
    operator_phone: str,
) -> Dict[str, Any]:
    """
    Sent when AI can't answer a question and escalates to operator.
    Shows guest their options clearly.
    """
    return {
        "friendly_name": "oyvoda_kb_gap_fallback",
        "language": "en",
        "types": {
            "twilio/card": {
                "title": f"Let me get you a better answer",
                "body": (
                    f"I don't have complete information about {question_topic} for {property_name}, "
                    f"{guest_name}.\n\n"
                    f"Your host has been notified and will follow up shortly. "
                    f"Or you can reach them directly using the button below."
                ),
                "actions": [
                    {
                        "type": "PHONE_NUMBER",
                        "title": "Call Host",
                        "phone": operator_phone,
                    },
                    {"type": "QUICK_REPLY", "title": "Ask something else", "id": "ask_other"},
                ],
            },
            "twilio/text": {
                "body": (
                    f"I don't have full info on that, {guest_name}. "
                    f"Your host at {property_name} has been notified. "
                    f"You can also reach them at {operator_phone}."
                ),
            },
        },
    }


# =============================================================================
# TWILIO CONTENT API CLIENT
# =============================================================================

class RCSTemplateManager:
    """
    Manages RCS Content Templates via Twilio Content API.

    Templates are created once and reused by Content SID.
    In production, store Content SIDs in operator_rcs_templates table.

    Usage:
        mgr = RCSTemplateManager()

        # Create template once (during operator setup)
        sid = await mgr.create_template(morning_brief_template(
            property_name="Gulf View Rentals",
            env_status_label="Yellow Flag",
            env_narrative="Moderate surf today — great for walking.",
        ))

        # Send using the SID
        await mgr.send_template(
            to="+15551234567",
            content_sid=sid,
        )

    Twilio Content API docs:
        https://www.twilio.com/docs/content/create-templates-with-the-content-api
    """

    BASE_URL = "https://content.twilio.com/v1/Content"

    def __init__(self):
        self.account_sid = os.getenv("TWILIO_ACCOUNT_SID")
        self.auth_token = os.getenv("TWILIO_AUTH_TOKEN")
        self.messaging_sid = os.getenv("TWILIO_MESSAGING_SID")
        self._client = None

    @property
    def client(self):
        if self._client is None:
            if not self.account_sid or not self.auth_token:
                raise RuntimeError("Twilio credentials not configured")
            from twilio.rest import Client
            self._client = Client(self.account_sid, self.auth_token)
        return self._client

    async def create_template(self, template_def: Dict[str, Any]) -> str:
        """
        Create a Content Template and return the Content SID (HX...).
        
        Args:
            template_def: Template dict as returned by the template functions above
            
        Returns:
            Content SID string (starts with HX)
        """
        import httpx

        async with httpx.AsyncClient() as http:
            response = await http.post(
                self.BASE_URL,
                auth=(self.account_sid, self.auth_token),
                json=template_def,
                timeout=15.0,
            )
            response.raise_for_status()
            data = response.json()
            sid = data["sid"]
            logger.info(f"[RCS] Created template '{template_def.get('friendly_name')}': {sid}")
            return sid

    async def list_templates(self) -> List[Dict[str, Any]]:
        """List all existing Content Templates for this account."""
        import httpx

        async with httpx.AsyncClient() as http:
            response = await http.get(
                self.BASE_URL,
                auth=(self.account_sid, self.auth_token),
                timeout=10.0,
            )
            response.raise_for_status()
            return response.json().get("contents", [])

    async def delete_template(self, content_sid: str) -> bool:
        """Delete a Content Template by SID."""
        import httpx

        async with httpx.AsyncClient() as http:
            response = await http.delete(
                f"{self.BASE_URL}/{content_sid}",
                auth=(self.account_sid, self.auth_token),
                timeout=10.0,
            )
            return response.status_code == 204

    async def send_template(
        self,
        to: str,
        content_sid: str,
        content_variables: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Send a message using a pre-created Content Template.
        Automatically falls back to the template's twilio/text type if RCS not available.

        Args:
            to: Guest phone number in E.164 format
            content_sid: Template SID (HX...)
            content_variables: Optional variable substitutions for the template

        Returns:
            Twilio Message dict with 'sid' and 'status'
        """
        if not self.messaging_sid:
            raise RuntimeError(
                "TWILIO_MESSAGING_SID required for Content Template sends. "
                "Create a Messaging Service at console.twilio.com → Messaging → Services."
            )

        try:
            kwargs: Dict[str, Any] = {
                "to": to,
                "messaging_service_sid": self.messaging_sid,
                "content_sid": content_sid,
            }
            if content_variables:
                import json
                kwargs["content_variables"] = json.dumps(content_variables)

            msg = self.client.messages.create(**kwargs)
            logger.info(f"[RCS] Template {content_sid} sent to {to}: {msg.sid}")
            return {"sid": msg.sid, "status": msg.status, "success": True}

        except Exception as e:
            logger.error(f"[RCS] Template send failed for {to}: {e}")
            return {"success": False, "error": str(e)}


# =============================================================================
# PLATFORM TEMPLATE REGISTRY
# =============================================================================

# These are created once at platform level during setup.
# Stored in environment or DB after first creation.
# Format: OYVODA_RCS_TEMPLATE_{TYPE} = HX...

PLATFORM_TEMPLATE_ENV_KEYS = {
    RCSTemplateType.MORNING_BRIEF:          "OYVODA_RCS_TEMPLATE_MORNING_BRIEF",
    RCSTemplateType.MAINTENANCE_DISPATCH:   "OYVODA_RCS_TEMPLATE_MAINTENANCE_DISPATCH",
    RCSTemplateType.MAINTENANCE_UPDATE:     "OYVODA_RCS_TEMPLATE_MAINTENANCE_UPDATE",
    RCSTemplateType.VENDOR_BOOKING_CONFIRM: "OYVODA_RCS_TEMPLATE_VENDOR_BOOKING",
    RCSTemplateType.LATE_CHECKOUT_OFFER:    "OYVODA_RCS_TEMPLATE_LATE_CHECKOUT",
    RCSTemplateType.EXTEND_STAY_OFFER:      "OYVODA_RCS_TEMPLATE_EXTEND_STAY",
    RCSTemplateType.EVENT_ALERT:            "OYVODA_RCS_TEMPLATE_EVENT_ALERT",
    RCSTemplateType.KB_GAP_FALLBACK:        "OYVODA_RCS_TEMPLATE_KB_GAP",
}


def get_template_sid(template_type: RCSTemplateType) -> Optional[str]:
    """Get a platform template SID from environment."""
    env_key = PLATFORM_TEMPLATE_ENV_KEYS.get(template_type)
    if not env_key:
        return None
    return os.getenv(env_key)


# =============================================================================
# SINGLETON
# =============================================================================

_template_manager: Optional[RCSTemplateManager] = None


def get_template_manager() -> RCSTemplateManager:
    global _template_manager
    if _template_manager is None:
        _template_manager = RCSTemplateManager()
    return _template_manager
