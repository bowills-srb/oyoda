from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict


class InboundTransportMode(str, Enum):
    POLLING = "polling"
    WEBHOOK = "webhook"
    PUSH_WATCH = "push_watch"
    HYBRID = "hybrid"


class InboundTransportSource(str, Enum):
    GMAIL = "gmail"
    MICROSOFT = "microsoft"
    ESCAPIA = "escapia"
    GUESTY = "guesty"
    TRACK = "track"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class InboundTransportCapability:
    source: InboundTransportSource
    preferred_mode: InboundTransportMode
    fallback_mode: InboundTransportMode
    parser_required: bool = True
    supports_real_time: bool = False
    notes: tuple[str, ...] = ()


@dataclass
class InboundTransportEnvelope:
    tenant_id: str
    operator_id: str
    source: InboundTransportSource
    transport_mode: InboundTransportMode
    watched_address: str
    source_message_id: str
    source_thread_id: str = ""
    received_at: datetime | None = None
    raw_headers: Dict[str, str] = field(default_factory=dict)
    raw_text: str = ""
    raw_html: str = ""
    raw_payload: Dict[str, Any] = field(default_factory=dict)


_CAPABILITIES: dict[InboundTransportSource, InboundTransportCapability] = {
    InboundTransportSource.GMAIL: InboundTransportCapability(
        source=InboundTransportSource.GMAIL,
        preferred_mode=InboundTransportMode.PUSH_WATCH,
        fallback_mode=InboundTransportMode.POLLING,
        parser_required=True,
        supports_real_time=True,
        notes=(
            "Use Gmail watch / push notifications when configured.",
            "Keep unread/recent polling as a fallback safety net.",
        ),
    ),
    InboundTransportSource.MICROSOFT: InboundTransportCapability(
        source=InboundTransportSource.MICROSOFT,
        preferred_mode=InboundTransportMode.WEBHOOK,
        fallback_mode=InboundTransportMode.POLLING,
        parser_required=True,
        supports_real_time=True,
        notes=(
            "Use Microsoft Graph subscriptions for mailbox events when configured.",
            "Keep inbox polling as a fallback safety net.",
        ),
    ),
    InboundTransportSource.ESCAPIA: InboundTransportCapability(
        source=InboundTransportSource.ESCAPIA,
        preferred_mode=InboundTransportMode.WEBHOOK,
        fallback_mode=InboundTransportMode.POLLING,
        parser_required=True,
        supports_real_time=True,
        notes=(
            "Prefer PMS/OTA webhook delivery for message and reservation events.",
            "Polling remains the fallback where webhook setup or provider support lags.",
        ),
    ),
    InboundTransportSource.GUESTY: InboundTransportCapability(
        source=InboundTransportSource.GUESTY,
        preferred_mode=InboundTransportMode.WEBHOOK,
        fallback_mode=InboundTransportMode.POLLING,
        parser_required=False,
        supports_real_time=True,
        notes=(
            "Guesty can send structured webhook payloads for bookings/messages.",
            "Normalize into the same internal inbound envelope before concierge processing.",
        ),
    ),
    InboundTransportSource.TRACK: InboundTransportCapability(
        source=InboundTransportSource.TRACK,
        preferred_mode=InboundTransportMode.WEBHOOK,
        fallback_mode=InboundTransportMode.POLLING,
        parser_required=False,
        supports_real_time=True,
        notes=(
            "Track should push structured PMS events where available.",
            "Polling remains the operational fallback.",
        ),
    ),
    InboundTransportSource.UNKNOWN: InboundTransportCapability(
        source=InboundTransportSource.UNKNOWN,
        preferred_mode=InboundTransportMode.POLLING,
        fallback_mode=InboundTransportMode.POLLING,
        parser_required=True,
        supports_real_time=False,
        notes=("Unknown source defaults to safe polling + parser path.",),
    ),
}


def normalize_transport_source(value: str) -> InboundTransportSource:
    normalized = (value or "").strip().lower()
    if normalized in {"gmail", "google"}:
        return InboundTransportSource.GMAIL
    if normalized in {"microsoft", "outlook", "office365", "m365"}:
        return InboundTransportSource.MICROSOFT
    if normalized == "escapia":
        return InboundTransportSource.ESCAPIA
    if normalized == "guesty":
        return InboundTransportSource.GUESTY
    if normalized == "track":
        return InboundTransportSource.TRACK
    return InboundTransportSource.UNKNOWN


def get_inbound_transport_capability(source: str) -> InboundTransportCapability:
    return _CAPABILITIES[normalize_transport_source(source)]
