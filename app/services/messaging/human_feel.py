"""
Human-Feel Messaging Layer

Makes AI responses feel like a real person is typing, not a bot firing instantly.

Three components:

1. TYPING DELAY — introduce a realistic pause before sending
   - Short messages (1-2 sentences): 1.5–3s
   - Medium messages (3-4 sentences): 3–5s
   - Long messages (5+ sentences): 4–7s
   - Maximum: 8s (never make guests wait longer)
   - Randomized within range to avoid robotic consistency

2. TYPING INDICATOR — send a "typing..." signal before the response
   - RCS: native typing indicator via Twilio
   - SMS: no indicator (not supported)
   - ABM: native typing indicator

3. RESPONSE VARIATION — same question, different phrasing
   - Each response runs through a light variation pass
   - Changes openers, adds/removes trailing warmth
   - Prevents the "always same answer" tell

4. TIME-AWARE TONE — response style shifts based on time of day
   - 6am–9am: "Good morning!" energy, bright
   - 9am–6pm: Normal helpful tone
   - 6pm–10pm: "Evening" greetings, slightly warmer
   - 10pm–6am: Quieter, "sorry to bother you late" acknowledgment

These run in the messaging pipeline AFTER AI response generation,
BEFORE the actual Twilio/RCS send call.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


# =============================================================================
# TYPING DELAY
# =============================================================================

def calculate_typing_delay(response_text: str) -> float:
    """
    Calculate a human-feeling typing delay based on response length.
    Returns delay in seconds.

    Reading speed of ~250wpm → typing speed of ~60wpm.
    We simulate a human who has to read the question, think, and type.

    Never returns 0 — even the fastest human takes a second.
    """
    # Count words
    words = len(response_text.split())

    if words <= 15:
        # Short reply: "Your WiFi is CoastalVibes / SunsetView2024"
        return random.uniform(1.2, 2.5)
    elif words <= 40:
        # Medium: standard 2-3 sentence reply
        return random.uniform(2.5, 4.5)
    elif words <= 80:
        # Longer: activity recommendations or detailed answer
        return random.uniform(3.5, 6.0)
    else:
        # Long: full proactive brief or multi-part answer
        return random.uniform(4.5, 7.5)


async def apply_typing_delay(response_text: str, fast_mode: bool = False) -> None:
    """
    Await the typing delay before sending.

    Args:
        response_text: The message we're about to send
        fast_mode: If True, use minimal delays (for testing or urgent messages)
    """
    if fast_mode or os.getenv("OYVODA_FAST_RESPONSES", "false").lower() == "true":
        await asyncio.sleep(0.3)
        return

    delay = calculate_typing_delay(response_text)
    logger.debug(f"[HumanFeel] Typing delay: {delay:.1f}s for {len(response_text.split())} words")
    await asyncio.sleep(delay)


# =============================================================================
# TYPING INDICATORS
# =============================================================================

async def send_typing_indicator(
    phone: str,
    channel: str = "sms",
) -> None:
    """
    Send a typing indicator to the guest before the actual response.
    Only meaningful on RCS and ABM — no-op on SMS.

    RCS typing indicator: Twilio supports this via the Content API.
    ABM typing indicator: Apple Messages native feature.
    """
    if channel == "rcs":
        await _send_rcs_typing_indicator(phone)
    elif channel == "apple_messages":
        await _send_abm_typing_indicator(phone)
    # SMS: no indicator supported, just add the delay


async def _send_rcs_typing_indicator(phone: str) -> None:
    """
    Send RCS typing indicator via Twilio.
    Twilio's RCS implementation supports isTyping events.
    """
    try:
        account_sid = os.getenv("TWILIO_ACCOUNT_SID")
        auth_token = os.getenv("TWILIO_AUTH_TOKEN")
        messaging_sid = os.getenv("TWILIO_MESSAGING_SID")

        if not all([account_sid, auth_token, messaging_sid]):
            return

        import httpx
        async with httpx.AsyncClient(timeout=5.0) as client:
            # Twilio RCS typing indicator endpoint (beta)
            await client.post(
                f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json",
                auth=(account_sid, auth_token),
                data={
                    "To": f"rcs:{phone}",
                    "MessagingServiceSid": messaging_sid,
                    "PersistentAction": ["typing_on"],
                },
                timeout=5.0,
            )
    except Exception as e:
        logger.debug(f"[HumanFeel] Typing indicator failed (non-fatal): {e}")


async def _send_abm_typing_indicator(conversation_id: str) -> None:
    """Send Apple Messages for Business typing indicator."""
    try:
        import httpx
        import base64
        api_key = os.getenv("ABM_API_KEY")
        api_secret = os.getenv("ABM_API_SECRET")
        account_id = os.getenv("ABM_BUSINESS_ACCOUNT_ID")

        if not all([api_key, api_secret, account_id]):
            return

        auth = base64.b64encode(f"{api_key}:{api_secret}".encode()).decode()
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                "https://mspapi.apple.com/api/v1/typing/start",
                headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"},
                json={"sourceId": account_id, "destinationId": conversation_id},
            )
    except Exception as e:
        logger.debug(f"[HumanFeel] ABM typing indicator failed (non-fatal): {e}")


# =============================================================================
# RESPONSE VARIATION
# =============================================================================

# Opener variations — swap the first sentence opener to avoid sameness
OPENER_VARIATIONS = {
    "Hi {name}": [
        "Hey {name}",
        "Hi {name}!",
        "{name}",
        "Hey there, {name}",
    ],
    "Of course": [
        "Absolutely",
        "Sure thing",
        "Happy to help",
        "For sure",
    ],
    "I'd be happy to": [
        "Love to",
        "Happy to",
        "Sure —",
        "Of course —",
    ],
    "Let me": [
        "Give me a sec to",
        "I'll",
        "Allow me to",
    ],
}

# Warm closers to occasionally append
WARM_CLOSERS = [
    "Let me know if you need anything else! 😊",
    "Happy to help with anything else!",
    "Just ask if you need anything more.",
    "I'm here if you have more questions!",
    "",  # Sometimes no closer (most natural)
    "",
    "",
]


def apply_response_variation(text: str, guest_first_name: str = "") -> str:
    """
    Apply light variation to a response to prevent robotic consistency.

    Changes:
    - Occasionally swap opener phrase
    - Occasionally add a warm closer (if response doesn't already end warmly)
    - Don't change facts or substance

    Called after AI generation, before delay/send.
    """
    # 30% chance to vary the opener
    if random.random() < 0.3:
        for original, variants in OPENER_VARIATIONS.items():
            trigger = original.replace("{name}", guest_first_name) if "{name}" in original else original
            if text.startswith(trigger):
                replacement = random.choice(variants).replace("{name}", guest_first_name)
                text = replacement + text[len(trigger):]
                break

    # 25% chance to add a warm closer (only if message doesn't end with emoji or question)
    if (random.random() < 0.25
            and not text.rstrip().endswith("?")
            and not any(text.rstrip()[-1] == c for c in "🌊🏖️🌴🔑🏊")):
        closer = random.choice(WARM_CLOSERS)
        if closer:
            text = text.rstrip() + " " + closer

    return text


# =============================================================================
# TIME-AWARE TONE INJECTOR
# =============================================================================

def get_time_aware_prefix(hour: Optional[int] = None) -> str:
    """
    Return an appropriate greeting prefix based on time of day.
    Injected into proactive messages (welcome brief, extend offer, etc.)
    NOT injected into reactive AI responses — those are already contextual.

    Args:
        hour: Hour in local time (0-23). If None, uses UTC hour.
    """
    if hour is None:
        hour = datetime.utcnow().hour  # Approximate — ideally use guest timezone

    if 6 <= hour < 9:
        return random.choice(["Good morning! ☀️ ", "Morning! 🌅 ", "Early riser! 🌄 "])
    elif 9 <= hour < 12:
        return random.choice(["Good morning! ", "Morning! "])
    elif 12 <= hour < 14:
        return random.choice(["Good afternoon! ", ""])
    elif 14 <= hour < 18:
        return random.choice(["", "", ""])  # Usually no prefix in afternoon
    elif 18 <= hour < 21:
        return random.choice(["Good evening! 🌅 ", "Hope you're having a great evening! "])
    elif 21 <= hour < 23:
        return random.choice(["", "Hope you've had a wonderful day! "])
    else:  # Late night / early morning
        return random.choice(["", ""])  # Silent at night — no opener for late messages


# =============================================================================
# MAIN PIPELINE WRAPPER
# =============================================================================

async def send_with_human_feel(
    phone: str,
    response_text: str,
    channel: str,
    send_fn,                        # Callable: async (phone, text) -> DeliveryResult
    guest_first_name: str = "",
    apply_variation: bool = True,
    urgent: bool = False,           # Skip delay for urgent messages (safety, gate codes)
) -> any:
    """
    Send a message with human-feeling delay and variation.

    This wraps the actual send function — call this instead of calling
    the channel router directly from the AI pipeline.

    Usage:
        result = await send_with_human_feel(
            phone=guest.phone,
            response_text=ai_response,
            channel="rcs",
            send_fn=lambda p, t: router.send(p, ChannelMessage(body=t)),
            guest_first_name="Sarah",
        )
    """
    # Apply variation first (so delay duration is based on final text)
    final_text = response_text
    if apply_variation and not urgent:
        final_text = apply_response_variation(response_text, guest_first_name)

    # Send typing indicator (non-blocking, fire and forget)
    if not urgent and channel in ("rcs", "apple_messages"):
        asyncio.ensure_future(send_typing_indicator(phone, channel))

    # Wait for human-feeling delay
    if not urgent:
        await apply_typing_delay(final_text)

    # Send the actual message
    return await send_fn(phone, final_text)


# =============================================================================
# CONSTANTS
# =============================================================================

# Suppress delays in test environments
FAST_MODE = os.getenv("OYVODA_FAST_RESPONSES", "false").lower() == "true"
